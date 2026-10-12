"""CPython check of the shim: unpack the bundle, fake a BROM that answers the handshake, run mtkclient's own Port code."""
import sys, zipfile, tempfile, types, logging
from unittest.mock import MagicMock

tmp = tempfile.mkdtemp()
zipfile.ZipFile("mtkclient_pkg.zip").extractall(tmp)
sys.path[:0] = [tmp, "shim"]
sys.modules["colorama"] = None  # simulate Pyodide: colorama not installed

# Cryptodome isn't installed in this sandbox; the handshake path never touches it.
for name in ["Cryptodome", "Cryptodome.Cipher", "Cryptodome.Hash", "Cryptodome.PublicKey",
             "Cryptodome.Util", "Cryptodome.Util.number", "Cryptodome.Signature", "Cryptodome.Random"]:
    sys.modules[name] = MagicMock()

class FakeBrom:
    """Speaks just enough BROM: handshake (a0 0a 50 05 -> 5f f5 af fa), GET_HW_CODE (fd)."""
    cancelled = False
    def __init__(self): self.rx = bytearray(); self.is_open = False; self.writes = []
    def open(self): self.is_open = True; return True
    def close(self): self.is_open = False
    def setSignals(self, rts, dtr): pass
    def sleep(self, ms): pass
    def inWaiting(self): return len(self.rx)
    def write(self, data):
        for b in bytes(data):
            self.writes.append(b)
            if b in (0xA0, 0x0A, 0x50, 0x05): self.rx.append(~b & 0xFF)
            elif b == 0xFD: self.rx += bytes([0xFD])
    def read(self, n, ms):
        out = bytes(self.rx[:n]); del self.rx[:n]; return out

import boot            # browser does `import boot` first
import webserial_class
fake = FakeBrom(); webserial_class.set_bridge(fake)
boot.install_stubs()

from mtkclient.config.mtk_config import MtkConfig
from mtkclient.config.usb_ids import default_ids
from mtkclient.Library.Port import Port
from mtkclient.Library.mtk_preloader import Preloader

config = MtkConfig(loglevel=logging.INFO)
sess = boot.Session(config)
sess.port = Port(mtk=sess, portconfig=default_ids, serialportname="WEBSERIAL", loglevel=logging.INFO)
sess.preloader = Preloader(sess, logging.INFO)
assert type(sess.port.cdc).__name__ == "WebSerialClass", type(sess.port.cdc)

assert sess.port.serial_handshake(maxtries=3) is True
assert fake.writes[:4] == [0xA0, 0x0A, 0x50, 0x05], fake.writes
print("PASS handshake through mtkclient Port.serial_handshake; sent", [hex(w) for w in fake.writes])

assert sess.port.echo(b"\xfd") is True
fake.rx += bytes.fromhex("0335ca00")
val = sess.port.rdword()
assert val == 0x0335CA00, hex(val)
print("PASS echo + rdword ->", hex(val), "(hwcode", hex(val >> 16), "hwver", hex(val & 0xFFFF) + ")")
sess.port.close(); assert fake.is_open is False
print("PASS close")
