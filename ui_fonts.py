"""Shared private-process font registration for the app and Windows installer."""
from __future__ import annotations

import ctypes
from pathlib import Path
import sys

FONT_FAMILY = "Peyda"
FONT_FILES = ("Peyda-Regular.ttf", "Peyda-Bold.ttf")


def register_fonts(asset_dir: Path) -> None:
    """Load bundled faces without installing fonts into the user's Windows account."""
    if sys.platform != "win32":
        return
    add_font = ctypes.windll.gdi32.AddFontResourceExW
    add_font.argtypes = [ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_void_p]
    add_font.restype = ctypes.c_int
    for filename in FONT_FILES:
        path = asset_dir / filename
        if path.is_file():
            add_font(str(path), 0x10, None)  # FR_PRIVATE: only this process can use it.
