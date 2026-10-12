#!/usr/bin/env python3
"""Pack the parts of mtkclient needed for milestone 1 (handshake + device info) into mtkclient_pkg.zip.

Usage:  python build_bundle.py /path/to/mtkclient   [out.zip]
The files are copied unmodified; nothing from Exploit/, Loader/, payloads or the GUI is included.
"""
import sys, zipfile, pathlib

KEEP = [
    "__init__.py",
    "config/__init__.py", "config/brom_config.py", "config/mtk_config.py", "config/usb_ids.py",
    "Library/__init__.py", "Library/gui_utils.py", "Library/utils.py", "Library/error.py",
    "Library/settings.py", "Library/Port.py", "Library/mtk_preloader.py",
    "Library/Auth/__init__.py", "Library/Auth/sla.py", "Library/Auth/sla_keys.py",
    "Library/Connection/__init__.py", "Library/Connection/devicehandler.py",
]

def main():
    repo = pathlib.Path(sys.argv[1])
    pkg = repo / "mtkclient"
    out = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else "mtkclient_pkg.zip")
    missing = [k for k in KEEP if not (pkg / k).is_file()]
    if missing:
        sys.exit(f"missing in {pkg}: {missing}")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for k in KEEP:
            z.write(pkg / k, f"mtkclient/{k}")
    print(f"wrote {out} ({out.stat().st_size // 1024} KB, {len(KEEP)} files)")

main()
