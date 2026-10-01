from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes

from PySide6.QtCore import QObject, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget

from screen_translator.contracts import Region
from screen_translator.platform.windows.monitors import cursor_position, monitor_for_point
from screen_translator.ui.display_coordinates import ScreenMapping, screen_mappings


class _SelectionWindow(QWidget):
    def __init__(self, selector: "RegionSelector", mapping: ScreenMapping) -> None:
        super().__init__()
        self.selector = selector
        self.mapping = mapping
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                            | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.winId()
        if self.windowHandle():
            self.windowHandle().setScreen(mapping.screen)
        self.setGeometry(mapping.screen.geometry())

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(7, 15, 23, 120))
        start, end = self.selector.start, self.selector.end
        if start is not None and end is not None:
            first = self.mapping.physical_to_local(*start)
            second = self.mapping.physical_to_local(*end)
            rect = QRect(first, second).normalized()
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            painter.fillRect(rect, QColor(0, 0, 0, 0))
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            painter.setPen(QPen(QColor("#6de2d0"), 2))
            painter.drawRect(rect)
            painter.setFont(QFont("Microsoft YaHei UI", 11))
            painter.setPen(QColor("white"))
            label = f"{abs(end[0] - start[0])} × {abs(end[1] - start[1])} 像素"
            painter.drawText(QPoint(max(12, min(rect.left(), self.width() - 160)),
                                   max(70, min(rect.top() - 12, self.height() - 16))), label)
        painter.setFont(QFont("Microsoft YaHei UI", 14))
        painter.setPen(QColor("white"))
        painter.drawText(QRect(20, 18, self.width() - 40, 65),
                         Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                         self.selector.message)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            position = self._cursor_or_cancel()
            if position is not None:
                self.selector.begin(position, self)
        elif event.button() == Qt.MouseButton.RightButton:
            self.selector.cancel()

    def mouseMoveEvent(self, event) -> None:
        if self.selector.start is not None:
            position = self._cursor_or_cancel()
            if position is not None:
                self.selector.move(position)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.selector.start is not None:
            position = self._cursor_or_cancel()
            if position is not None:
                self.selector.finish(position)

    def _cursor_or_cancel(self) -> tuple[int, int] | None:
        try:
            return cursor_position()
        except OSError as exc:
            self.selector.fail(str(exc))
            return None

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.selector.cancel()


class RegionSelector(QObject):
    selected = Signal(object)
    cancelled = Signal()
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.mappings = screen_mappings()
        self.windows: list[_SelectionWindow] = []
        self.start: tuple[int, int] | None = None
        self.end: tuple[int, int] | None = None
        self._grabber: _SelectionWindow | None = None
        self._foreground = None
        self._closed = False
        self.message = "拖动鼠标框选翻译区域 · Esc / 右键取消\n可在任意显示器框选，请在同一块显示器内完成"

    def show(self) -> None:
        if not self.mappings:
            self.cancel()
            return
        app = QApplication.instance()
        if app:
            app.setProperty("regionSelecting", True)
        if sys.platform == "win32":
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.GetForegroundWindow.restype = wintypes.HWND
            self._foreground = user32.GetForegroundWindow()
        position = cursor_position()
        active = None
        for mapping in self.mappings:
            window = _SelectionWindow(self, mapping)
            self.windows.append(window)
            window.show()
            window.raise_()
            if mapping.monitor.contains(*position):
                active = window
        (active or self.windows[0]).activateWindow()
        (active or self.windows[0]).setFocus()

    def begin(self, position: tuple[int, int], window: _SelectionWindow) -> None:
        self.start = self.end = position
        self._grabber = window
        window.grabMouse()
        self._refresh()

    def move(self, position: tuple[int, int]) -> None:
        self.end = position
        self._refresh()

    def finish(self, position: tuple[int, int]) -> None:
        self.end = position
        if self._grabber:
            self._grabber.releaseMouse()
            self._grabber = None
        if self.start is None:
            return
        monitors = [mapping.monitor for mapping in self.mappings]
        first = monitor_for_point(*self.start, monitors)
        last = monitor_for_point(*position, monitors)
        if first is None or last is None or first.id != last.id:
            self.message = "当前版本请在同一块显示器内框选 · 请重新拖动\nEsc / 右键取消"
            self.start = self.end = None
            self._refresh()
            return
        left, top = min(self.start[0], position[0]), min(self.start[1], position[1])
        width, height = abs(position[0] - self.start[0]), abs(position[1] - self.start[1])
        region = Region(left, top, width, height, first.id, first.bounds)
        if not region.valid():
            self.message = "区域过小，请至少框选 12 × 12 像素 · 请重新拖动\nEsc / 右键取消"
            self.start = self.end = None
            self._refresh()
            return
        self.shutdown()
        self.selected.emit(region)

    def _refresh(self) -> None:
        for window in self.windows:
            window.update()

    def cancel(self) -> None:
        if self._closed:
            return
        self.shutdown()
        self.cancelled.emit()

    def fail(self, message: str) -> None:
        if self._closed:
            return
        self.shutdown()
        self.cancelled.emit()
        self.failed.emit(message)

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._grabber:
            self._grabber.releaseMouse()
            self._grabber = None
        for window in self.windows:
            window.hide()
            window.close()
            window.deleteLater()
        self.windows.clear()
        app = QApplication.instance()
        if app:
            app.setProperty("regionSelecting", False)
            # Do not reinterpret the selector's cancelling Esc as a subtitle toggle.
            app.setProperty("regionEscapeSuppressedUntil", time.monotonic() + 0.25)
        if self._foreground and sys.platform == "win32":
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.SetForegroundWindow.argtypes = [wintypes.HWND]
            user32.SetForegroundWindow(self._foreground)
