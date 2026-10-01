from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QGuiApplication, QScreen

from screen_translator.platform.windows.monitors import Monitor, enumerate_monitors


@dataclass(frozen=True)
class ScreenMapping:
    screen: QScreen
    monitor: Monitor

    @property
    def scale_x(self) -> float:
        return self.monitor.width / max(1, self.screen.geometry().width())

    @property
    def scale_y(self) -> float:
        return self.monitor.height / max(1, self.screen.geometry().height())

    def physical_to_qt(self, x: float, y: float) -> QPoint:
        geometry = self.screen.geometry()
        return QPoint(geometry.x() + round((x - self.monitor.x) / self.scale_x),
                      geometry.y() + round((y - self.monitor.y) / self.scale_y))

    def physical_rect_to_qt(self, bounds: tuple[int, int, int, int]) -> QRect:
        left, top, right, bottom = bounds
        point = self.physical_to_qt(left, top)
        return QRect(point.x(), point.y(), round((right - left) / self.scale_x),
                     round((bottom - top) / self.scale_y))

    def physical_to_local(self, x: float, y: float) -> QPoint:
        return QPoint(round((x - self.monitor.x) / self.scale_x),
                      round((y - self.monitor.y) / self.scale_y))

    def qt_to_physical(self, x: float, y: float) -> tuple[int, int]:
        geometry = self.screen.geometry()
        return (self.monitor.x + round((x - geometry.x()) * self.scale_x),
                self.monitor.y + round((y - geometry.y()) * self.scale_y))

    def qt_rect_to_physical(self, rect: QRect) -> tuple[int, int, int, int]:
        left, top = self.qt_to_physical(rect.x(), rect.y())
        return left, top, left + round(rect.width() * self.scale_x), top + round(rect.height() * self.scale_y)


def _device_name(name: str) -> str:
    return name.replace("\\\\.\\", "").casefold()


def screen_mappings() -> list[ScreenMapping]:
    screens = QGuiApplication.screens()
    try:
        native = enumerate_monitors()
    except OSError:
        native = []
    result: list[ScreenMapping] = []
    used: set[str] = set()
    for screen in screens:
        monitor = next((item for item in native
                        if _device_name(item.id) == _device_name(screen.name())), None)
        if monitor is None:
            monitor = next((item for item in native if item.id not in used), None)
        if monitor is None:
            # Test/headless fallback only; production uses EnumDisplayMonitors.
            rect = screen.geometry()
            ratio = screen.devicePixelRatio()
            left, top = round(rect.x() * ratio), round(rect.y() * ratio)
            bounds = (left, top, left + round(rect.width() * ratio),
                      top + round(rect.height() * ratio))
            work = screen.availableGeometry()
            area = (left + round((work.x() - rect.x()) * ratio),
                    top + round((work.y() - rect.y()) * ratio),
                    left + round((work.right() + 1 - rect.x()) * ratio),
                    top + round((work.bottom() + 1 - rect.y()) * ratio))
            monitor = Monitor(screen.name(), bounds, area,
                              screen == QGuiApplication.primaryScreen())
        used.add(monitor.id)
        result.append(ScreenMapping(screen, monitor))
    return result
