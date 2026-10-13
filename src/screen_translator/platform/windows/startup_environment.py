"""One-time read-only Windows queries for optional startup presentation.

Covering the monitor is a conservative geometry heuristic, not exclusive-game
mode detection. Maximized applications may also suppress the startup card.
No window titles, process names, screenshots or coordinates are persisted.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import sys


@dataclass(frozen=True)
class StartupEnvironment:
    animations_enabled: bool = False
    foreground_covers_monitor: bool = True


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


def covers_monitor(window: tuple[int, int, int, int],
                   monitor: tuple[int, int, int, int]) -> bool:
    wl, wt, wr, wb = window
    ml, mt, mr, mb = monitor
    # Rectangles use physical coordinates under the app's DPI-aware context.
    # Permit at most two physical pixels of rounding, not a DPI-scaled border.
    return (wr > wl and wb > wt and mr > ml and mb > mt
            and wl <= ml + 2 and wt <= mt + 2
            and wr >= mr - 2 and wb >= mb - 2)


def _foreground_covers_monitor(api: object) -> bool:
    hwnd = api.GetForegroundWindow()
    if not hwnd:
        # NULL can occur during activation changes, not only on an idle desktop.
        # Prefer no decoration when we cannot reliably classify the foreground.
        return True
    class_name = ctypes.create_unicode_buffer(128)
    if not api.GetClassNameW(hwnd, class_name, len(class_name)):
        return True
    if class_name.value in {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}:
        return False
    if not api.IsWindowVisible(hwnd):
        return False
    rect = wintypes.RECT()
    if not api.GetWindowRect(hwnd, ctypes.byref(rect)):
        return True
    monitor = api.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
    info = _MonitorInfo()
    info.cbSize = ctypes.sizeof(info)
    if not monitor or not api.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return True
    return covers_monitor((rect.left, rect.top, rect.right, rect.bottom),
                          (info.rcMonitor.left, info.rcMonitor.top,
                           info.rcMonitor.right, info.rcMonitor.bottom))


def query_startup_environment() -> StartupEnvironment:
    if sys.platform != "win32":
        return StartupEnvironment()
    try:
        api = ctypes.WinDLL("user32", use_last_error=True)
        api.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT,
                                              ctypes.c_void_p, wintypes.UINT]
        api.SystemParametersInfoW.restype = wintypes.BOOL
        api.GetForegroundWindow.argtypes = []
        api.GetForegroundWindow.restype = wintypes.HWND
        api.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        api.GetClassNameW.restype = ctypes.c_int
        api.IsWindowVisible.argtypes = [wintypes.HWND]
        api.IsWindowVisible.restype = wintypes.BOOL
        api.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        api.GetWindowRect.restype = wintypes.BOOL
        api.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        api.MonitorFromWindow.restype = wintypes.HANDLE
        api.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_MonitorInfo)]
        api.GetMonitorInfoW.restype = wintypes.BOOL
        enabled = wintypes.BOOL()
        animate = bool(api.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0)
                       and enabled.value)
        return StartupEnvironment(animate, _foreground_covers_monitor(api))
    except (OSError, AttributeError, TypeError, ValueError):
        # A decorative window must never turn a failed desktop query into a
        # startup failure or suddenly cover an application we cannot inspect.
        return StartupEnvironment()
