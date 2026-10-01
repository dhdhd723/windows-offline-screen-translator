from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes


def apply_overlay_styles(hwnd: int) -> None:
    if sys.platform != "win32":
        return
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    getter = user32.GetWindowLongPtrW
    getter.argtypes = [wintypes.HWND, ctypes.c_int]
    getter.restype = ctypes.c_ssize_t
    setter = user32.SetWindowLongPtrW
    setter.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    setter.restype = ctypes.c_ssize_t
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.SetWindowPos.restype = wintypes.BOOL
    # TOOLWINDOW | LAYERED | NOACTIVATE | TRANSPARENT
    style = getter(hwnd, -20) | 0x80 | 0x80000 | 0x8000000 | 0x20
    setter(hwnd, -20, style)
    user32.SetWindowPos(hwnd, wintypes.HWND(-1), 0, 0, 0, 0,
                       0x0001 | 0x0002 | 0x0010 | 0x0020)  # size/move/focus preserved


def exclude_from_capture(hwnd: int) -> bool:
    if sys.platform != "win32":
        return False
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        setter = user32.SetWindowDisplayAffinity
        setter.argtypes = [wintypes.HWND, wintypes.DWORD]
        setter.restype = wintypes.BOOL
        return bool(setter(hwnd, 0x11))  # WDA_EXCLUDEFROMCAPTURE, Windows 10 2004+
    except (AttributeError, OSError):
        return False
