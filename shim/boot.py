"""
Bootstrap for running mtkclient inside Pyodide (milestone 1: handshake + device info).

Nothing in mtkclient is modified. We only:
  1. register stand-ins for modules that cannot exist in a browser (pyusb, pyserial,
     colorama) and alias Cryptodome -> Crypto when pycryptodomex isn't available,
  2. make time.sleep yield to the browser event loop (and be cancellable),
  3. build the minimal session object that mtkclient's Port / Preloader expect.
"""
import json
import logging
import sys
import time
import types

import webserial_class
from webserial_class import IN_BROWSER, get_bridge, run_sync


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    mod.__dict__.update(attrs)
    sys.modules[name] = mod
    return mod


class _Blank:
    def __getattr__(self, _):
        return ""


def install_stubs():
    # Transport modules: Port.py does `from ...seriallib import SerialClass`,
    # so handing it WebSerialClass needs no change to mtkclient itself.
    class _NoUsb:
        def __init__(self, *a, **k):
            raise RuntimeError("Raw USB transport is not available in the browser; use Web Serial.")

    _stub("usb")
    _stub("mtkclient.Library.Connection.usblib", UsbClass=_NoUsb, usb=sys.modules["usb"])
    _stub("mtkclient.Library.Connection.seriallib", SerialClass=webserial_class.WebSerialClass)

    try:
        import colorama  # noqa: F401
    except ImportError:
        _stub("colorama", Fore=_Blank(), Style=_Blank(), Back=_Blank(), init=lambda *a, **k: None)

    try:
        import Cryptodome  # noqa: F401
    except ImportError:
        _alias_cryptodome()


def _alias_cryptodome():
    """Map Cryptodome.* onto Crypto.* (Pyodide ships pycryptodome, which uses the 'Crypto' name)."""
    import importlib
    import importlib.abc
    import importlib.util

    class _Alias(importlib.abc.MetaPathFinder, importlib.abc.Loader):
        def find_spec(self, name, path, target=None):
            if name == "Cryptodome" or name.startswith("Cryptodome."):
                return importlib.util.spec_from_loader(name, self)
            return None

        def create_module(self, spec):
            return importlib.import_module("Crypto" + spec.name[len("Cryptodome"):])

        def exec_module(self, module):
            pass

    sys.meta_path.insert(0, _Alias())


def install_async_sleep():
    """time.sleep would freeze the page (and the Web Serial reader with it). Yield instead."""
    if not IN_BROWSER:
        return

    def sleep(seconds):
        br = get_bridge()
        if br.cancelled:
            raise KeyboardInterrupt("cancelled")
        if seconds > 0:
            run_sync(br.sleep(int(seconds * 1000)))
        if br.cancelled:
            raise KeyboardInterrupt("cancelled")

    time.sleep = sleep


class Session:
    """The few attributes Port and Preloader read from the object mtkclient calls `mtk`."""

    def __init__(self, config, serialportname="WEBSERIAL"):
        self.config = config
        self.serialportname = serialportname
        self.port = None
        self.preloader = None


def check_environment():
    if IN_BROWSER:
        from pyodide.ffi import can_run_sync
        if not can_run_sync():
            raise RuntimeError("This needs JSPI (Chrome or Edge 137+). Stack switching is unavailable here.")


def probe(loglevel=logging.INFO):
    """Run mtkclient's own serial handshake and Preloader.init(), return the device info as JSON."""
    check_environment()
    install_stubs()
    install_async_sleep()

    from mtkclient.config.mtk_config import MtkConfig
    from mtkclient.config.usb_ids import default_ids
    from mtkclient.Library.Port import Port
    from mtkclient.Library.mtk_preloader import Preloader

    config = MtkConfig(loglevel=loglevel)
    session = Session(config)
    session.port = Port(mtk=session, portconfig=default_ids, serialportname="WEBSERIAL", loglevel=loglevel)
    session.preloader = Preloader(session, loglevel)

    ok = session.preloader.init()
    cc = config.chipconfig

    def hx(v):
        return hex(v) if isinstance(v, int) else v

    info = {
        "ok": bool(ok),
        "cpu": getattr(cc, "name", None),
        "description": getattr(cc, "description", None),
        "hwcode": hx(config.hwcode),
        "hwver": hx(config.hwver),
        "hw_sub_code": hx(config.hw_sub_code) if hasattr(config, "hw_sub_code") else None,
        "swver": hx(config.swver),
        "is_brom": config.is_brom,
        "blver": config.blver,
        "target_config": config.target_config,
        "meid": config.meid.hex() if getattr(config, "meid", None) else None,
        "socid": config.socid.hex() if getattr(config, "socid", None) else None,
    }
    try:
        session.port.close()
    except Exception:
        pass
    return json.dumps(info, default=str)
