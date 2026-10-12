"""
WebSerialClass - drop-in replacement for mtkclient's SerialClass, backed by the
browser's Web Serial API through a small JS bridge (window.mtkBridge).

Why a bridge: mtkclient is synchronous Python, Web Serial is async JS. In Pyodide
we call the bridge's promises through pyodide.ffi.run_sync (needs JSPI, Chrome/Edge
137+). Outside the browser (unit tests) run_sync is the identity function and the
bridge can be any object with the same synchronous-looking methods.

Bridge contract (all may return promises in the browser):
    open()                -> bool      open the already-granted port (idempotent)
    close()               -> None
    write(Uint8Array)     -> None
    read(n, timeout_ms)   -> Uint8Array   up to n bytes, waits until n or timeout
    inWaiting()           -> int       bytes currently buffered
    setSignals(rts, dtr)  -> None
    sleep(ms)             -> None
    cancelled             -> bool
"""
import logging
import time

from mtkclient.Library.Connection.devicehandler import DeviceClass

try:  # running inside Pyodide
    from pyodide.ffi import run_sync, to_js
    IN_BROWSER = True
except ImportError:  # CPython (tests)
    IN_BROWSER = False

    def run_sync(x):
        return x

    def to_js(x):
        return x

_bridge = None


def set_bridge(bridge):
    global _bridge
    _bridge = bridge


def get_bridge():
    if _bridge is not None:
        return _bridge
    import js  # only exists in the browser
    return js.mtkBridge


def _to_bytes(res):
    if res is None:
        return b""
    if hasattr(res, "to_py"):
        res = res.to_py()
    return bytes(res)


class WebSerialClass(DeviceClass):
    """Implements the subset of SerialClass that Port / Preloader use."""

    def __init__(self, loglevel=logging.INFO, portconfig=None, devclass=-1):
        super().__init__(loglevel, portconfig, devclass)
        self.is_serial = True
        self.device = None
        self.portname = "WEBSERIAL"

    # -- connection ---------------------------------------------------------
    def connect(self, ep_in=-1, ep_out=-1):
        try:
            ok = bool(run_sync(get_bridge().open()))
        except Exception as err:
            self.warning(f"Web Serial open failed: {err}")
            ok = False
        self.device = get_bridge() if ok else None
        self.connected = ok
        return ok

    def setportname(self, portname: str):
        self.portname = portname

    def set_fast_mode(self, enabled):
        pass

    def close(self, reset=False):
        if self.connected:
            try:
                run_sync(get_bridge().close())
            except Exception as err:
                self.debug(f"close failed: {err}")
            self.device = None
            self.connected = False

    def detectdevices(self):
        return ["WEBSERIAL"]

    def get_device(self):
        return self.device

    def get_read_packetsize(self):
        return 0x200

    def get_write_packetsize(self):
        return 0x200

    # -- line settings (Web Serial fixes these at open(); keep calls harmless) --
    def set_line_coding(self, baudrate=None, parity=0, databits=8, stopbits=1):
        self.debug("set_line_coding ignored on Web Serial")

    def setbreak(self):
        self.debug("setbreak ignored on Web Serial")

    def setcontrollinestate(self, rts=None, dtr=None, is_ftdi=False):
        try:
            run_sync(get_bridge().setSignals(bool(rts), bool(dtr)))
        except Exception as err:
            self.debug(f"setSignals failed: {err}")

    def flush(self):
        return None

    # -- I/O ----------------------------------------------------------------
    def _in_waiting(self):
        try:
            return int(get_bridge().inWaiting())
        except Exception:
            return 0

    def write(self, command, pktsize=None):
        if pktsize is None:
            pktsize = 512
        if isinstance(command, str):
            command = bytes(command, "utf-8")
        command = bytes(command)
        if command == b"":
            return True
        br = get_bridge()
        try:
            for pos in range(0, len(command), pktsize):
                run_sync(br.write(to_js(command[pos:pos + pktsize])))
        except Exception as err:
            self.debug(str(err))
            return False
        self.verify_data(bytearray(command), "TX:")
        time.sleep(0.005)
        return True

    def usbwrite(self, data, pktsize=None):
        if pktsize is None:
            pktsize = len(data) or 1
        return self.write(data, pktsize)

    def read(self, length=None, timeout=-1):
        # timeout is in ms here (same as SerialClass.read)
        if timeout == -1:
            timeout = self.timeout
        if length is None:
            length = self._in_waiting()
            if length == 0:
                return b""
        return self.usbread(resplen=length, maxtimeout=timeout)

    def usbread(self, resplen=None, maxtimeout=0, timeout=0, w_max_packet_size=None):
        if self.device is None:
            return b""
        # Same timeout convention as SerialClass: maxtimeout in ms, timeout in s.
        if timeout == 0 and maxtimeout != 0:
            timeout = maxtimeout / 1000
        timeout = max(timeout, 0.02)
        if resplen is None:
            resplen = self._in_waiting()
        if resplen <= 0:
            return bytearray()
        # Browser round trips are slower than a native tty, so keep a small floor:
        # 50 ms for single-byte reads (handshake keeps its fast retry rate),
        # 250 ms for multi-byte reads (what SerialClass already tolerates).
        timeout = max(timeout, 0.25 if resplen > 1 else 0.05)
        try:
            data = _to_bytes(run_sync(get_bridge().read(int(resplen), int(timeout * 1000))))
        except Exception as err:
            self.debug(f"read failed: {err}")
            return bytearray()
        if self.loglevel == logging.DEBUG:
            self.verify_data(bytearray(data), "RX:")
        return bytearray(data[:resplen])

    def usbxmlread(self, timeout=0):
        # XML DA (v6) framing is not part of milestone 1; return what has arrived.
        n = self._in_waiting()
        return self.usbread(n, maxtimeout=int(timeout * 1000)) if n else bytearray()

    def usbreadwrite(self, data, resplen):
        self.usbwrite(data)
        return self.usbread(resplen)
