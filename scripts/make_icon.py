"""Regenerate packaging/app.ico, the EXE's icon, from the tray mascot.

Run with the project's Python: python scripts/make_icon.py
Writes every size in ICON_SIZES (each scaling step's small icon, and the
larger ones Explorer uses) plus a PNG-compressed 256 px image for large icons
and shortcuts; the old file held a single 16 px image, blown up everywhere
else. Importing the app only reads its settings; nothing else is
written.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import desktop_gremlin as gm  # noqa: E402

DESTINATION = os.path.join(ROOT, "packaging", "app.ico")

if __name__ == "__main__":
    gm._write_ico(DESTINATION, sizes=gm.ICON_SIZES, png_sizes=(256,))
    print(DESTINATION, os.path.getsize(DESTINATION), "bytes")
