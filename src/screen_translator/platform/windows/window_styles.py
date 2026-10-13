from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes


def apply_overlay_styles(hwnd: int) -> bool:
    if sys.platform != "win32":
        return False
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
    ctypes.set_last_error(0)
    previous = setter(hwnd, -20, style)
    if previous == 0 and ctypes.get_last_error():
        return False
    positioned = user32.SetWindowPos(hwnd, wintypes.HWND(-1), 0, 0, 0, 0,
                                     0x0001 | 0x0002 | 0x0010 | 0x0020)
    required = 0x80 | 0x80000 | 0x8000000 | 0x20 | 0x8
    return bool(positioned and getter(hwnd, -20) & required == required)


def exclude_from_capture(hwnd: int) -> bool:
    return set_capture_exclusion(hwnd, True)


def set_capture_exclusion(hwnd: int, enabled: bool) -> bool:
    """Change only our own subtitle HWND, never another app's protection.

    WDA_NONE is the recording-compatible default. Capture exclusion is an
    explicit opt-in and must be cleared when switching modes or hiding.
    """
    if sys.platform != "win32":
        return False
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        setter = user32.SetWindowDisplayAffinity
        setter.argtypes = [wintypes.HWND, wintypes.DWORD]
        setter.restype = wintypes.BOOL
        requested = 0x11 if enabled else 0
        if not setter(hwnd, requested):
            return False
        getter = user32.GetWindowDisplayAffinity
        getter.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        getter.restype = wintypes.BOOL
        actual = wintypes.DWORD()
        return bool(getter(hwnd, ctypes.byref(actual)) and actual.value == requested)
    except (AttributeError, OSError):
        return False
