from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from dataclasses import dataclass

from screen_translator.contracts import Region


@dataclass(frozen=True)
class Monitor:
    id: str
    bounds: tuple[int, int, int, int]
    work_area: tuple[int, int, int, int]
    primary: bool = False

    @property
    def x(self) -> int:
        return self.bounds[0]

    @property
    def y(self) -> int:
        return self.bounds[1]

    @property
    def width(self) -> int:
        return self.bounds[2] - self.bounds[0]

    @property
    def height(self) -> int:
        return self.bounds[3] - self.bounds[1]

    def contains(self, x: int, y: int) -> bool:
        left, top, right, bottom = self.bounds
        return left <= x < right and top <= y < bottom


class _MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD),
                ("szDevice", wintypes.WCHAR * 32)]


def _rect(rect: wintypes.RECT) -> tuple[int, int, int, int]:
    return rect.left, rect.top, rect.right, rect.bottom


def enumerate_monitors() -> list[Monitor]:
    """Native virtual-desktop rectangles; right/bottom are exclusive."""
    if sys.platform != "win32":
        return []
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HANDLE,
                                      wintypes.HDC, ctypes.POINTER(wintypes.RECT),
                                      wintypes.LPARAM)
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE,
                                      ctypes.POINTER(_MONITORINFOEXW)]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    user32.EnumDisplayMonitors.argtypes = [wintypes.HDC,
                                          ctypes.POINTER(wintypes.RECT),
                                          callback_type, wintypes.LPARAM]
    user32.EnumDisplayMonitors.restype = wintypes.BOOL
    result: list[Monitor] = []
    monitor_info_error: int | None = None

    @callback_type
    def collect(handle, dc, rect, data):
        nonlocal monitor_info_error
        info = _MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(info)
        if user32.GetMonitorInfoW(handle, ctypes.byref(info)):
            result.append(Monitor(str(info.szDevice), _rect(info.rcMonitor),
                                  _rect(info.rcWork), bool(info.dwFlags & 1)))
        else:
            # Raising inside a ctypes callback cannot propagate reliably.
            # Reject a partial snapshot after enumeration instead: a missing
            # record is not proof that the user's selected display disappeared.
            monitor_info_error = ctypes.get_last_error()
        return True

    if not user32.EnumDisplayMonitors(None, None, collect, 0):
        raise OSError(ctypes.get_last_error(), "无法读取显示器信息")
    if monitor_info_error is not None:
        raise OSError(monitor_info_error, "显示器信息暂不完整，等待恢复")
    return result


def monitor_for_point(x: int, y: int, monitors: list[Monitor] | None = None) -> Monitor | None:
    return next((m for m in (monitors if monitors is not None else enumerate_monitors())
                 if m.contains(x, y)), None)


def monitor_for_region(region: Region, monitors: list[Monitor] | None = None) -> Monitor | None:
    items = monitors if monitors is not None else enumerate_monitors()
    for monitor in items:
        left, top, right, bottom = monitor.bounds
        if (left <= region.x and top <= region.y
                and region.x + region.width <= right
                and region.y + region.height <= bottom):
            return monitor
    return None


def region_availability(region: Region | None) -> bool | None:
    """True for valid, False for invalid, None for a temporarily unreadable desktop.

    Only a complete, non-empty monitor snapshot can confirm a layout change.
    Callers monitoring an active session must not turn an unavailable desktop
    into a permanent stop, or the capture worker cannot recover after sleep.
    """
    if region is None or not region.valid():
        return False
    try:
        items = enumerate_monitors()
    except OSError:
        return None
    if not items:
        return None
    monitor = monitor_for_region(region, items)
    if monitor is None:
        return False
    if region.monitor_id and region.monitor_id.casefold() != monitor.id.casefold():
        return False
    if region.monitor_bounds and tuple(region.monitor_bounds) != monitor.bounds:
        return False
    return True


def validate_region(region: Region | None) -> bool:
    """Boolean compatibility check; unavailable desktops are not valid for starting."""
    return region_availability(region) is True


def cursor_position() -> tuple[int, int]:
    if sys.platform == "win32":
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        user32.GetCursorPos.restype = wintypes.BOOL
        point = wintypes.POINT()
        if not user32.GetCursorPos(ctypes.byref(point)):
            raise OSError(ctypes.get_last_error(), "无法读取鼠标位置")
        return point.x, point.y
    from PySide6.QtGui import QCursor
    point = QCursor.pos()
    return point.x(), point.y()
