from __future__ import annotations

import ctypes
import sys


def enable_dpi_awareness() -> bool:
    """Call before QApplication: keep capture and native cursor in physical pixels."""
    if sys.platform != "win32":
        return False
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    try:
        setter = user32.SetProcessDpiAwarenessContext
        setter.argtypes = [ctypes.c_void_p]
        setter.restype = ctypes.c_bool
        if setter(ctypes.c_void_p(-4)):  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
            return True
        # ERROR_ACCESS_DENIED means the manifest or host already set the mode.
        if ctypes.get_last_error() == 5:
            return True
    except AttributeError:
        pass
    try:
        shcore = ctypes.WinDLL("shcore", use_last_error=True)
        setter = shcore.SetProcessDpiAwareness
        setter.argtypes = [ctypes.c_int]
        setter.restype = ctypes.c_long
        return setter(2) in (0, -2147024891)
    except (AttributeError, OSError):
        try:
            return bool(user32.SetProcessDPIAware())
        except AttributeError:
            return False
