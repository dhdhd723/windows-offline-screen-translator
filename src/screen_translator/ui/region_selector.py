from __future__ import annotations

import ctypes
import logging
import sys
import time
from ctypes import wintypes

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer, Signal
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
                self._selection_input(self.selector.begin, position, self)
        elif event.button() == Qt.MouseButton.RightButton:
            self.selector.cancel()

    def mouseMoveEvent(self, event) -> None:
        if self.selector.start is not None:
            position = self._cursor_or_cancel()
            if position is not None:
                self._selection_input(self.selector.move, position)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.selector.start is not None:
            position = self._cursor_or_cancel()
            if position is not None:
                self._selection_input(self.selector.finish, position)

    def _selection_input(self, operation, *args) -> None:
        try:
            operation(*args)
        except Exception as exc:
            logging.getLogger(__name__).exception("Region selection input failed")
            self.selector.fail("框选发生错误，已关闭全部选区蒙层。请重新框选。\n" + str(exc))

    def _cursor_or_cancel(self) -> tuple[int, int] | None:
        try:
            return cursor_position()
        except Exception as exc:
            logging.getLogger(__name__).exception("Could not read selection cursor")
            self.selector.fail(str(exc))
            return None

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.selector.cancel()

    def closeEvent(self, event) -> None:
        if not self.selector._closed:
            self.selector.cancel("框选窗口已关闭，已取消框选。")
        event.accept()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        if not self.selector._closed:
            self.selector.cancel("框选窗口已隐藏，已取消框选。", restore_foreground=False)

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.WindowDeactivate:
            self.selector.schedule_focus_check()
        elif event.type() == QEvent.Type.UngrabMouse and self.selector._grabber is self:
            self.selector.cancel("鼠标框选已被其他操作中断，已取消框选。", restore_foreground=False)
        return super().event(event)


class RegionSelector(QObject):
    selected = Signal(object)
    cancelled = Signal()
    failed = Signal(str)
    TIMEOUT_MS = 90_000

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.mappings = screen_mappings()
        self.windows: list[_SelectionWindow] = []
        self.start: tuple[int, int] | None = None
        self.end: tuple[int, int] | None = None
        self._grabber: _SelectionWindow | None = None
        self._foreground = None
        self._closed = False
        self._opening = False
        self._app = None
        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.timeout.connect(lambda: self.cancel("90 秒内未完成框选，已自动关闭蒙层。请按框选快捷键重新选择。"))
        self._focus_check = QTimer(self)
        self._focus_check.setSingleShot(True)
        self._focus_check.setInterval(150)
        self._focus_check.timeout.connect(self._check_focus)
        self.message = "拖动鼠标框选翻译区域 · Esc / 右键取消 · 90 秒未完成自动取消\n可在任意显示器框选，请在同一块显示器内完成"

    def show(self) -> None:
        if self._closed:
            return
        if not self.mappings:
            self.cancel("未找到可用显示器，无法框选。")
            return
        app = QApplication.instance()
        if app:
            app.setProperty("regionSelecting", True)
            app.installEventFilter(self)
            self._app = app
        self._opening = True
        try:
            self._remember_foreground()
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
            self._timeout.start(self.TIMEOUT_MS)
        except Exception as exc:
            logging.getLogger(__name__).exception("Could not open region selector")
            self.fail("无法框选，已关闭全部选区蒙层。请重新框选。\n" + str(exc))
        finally:
            self._opening = False

    def _remember_foreground(self) -> None:
        if sys.platform == "win32":
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.GetForegroundWindow.restype = wintypes.HWND
            self._foreground = user32.GetForegroundWindow()

    def _restore_foreground(self) -> None:
        if self._foreground and sys.platform == "win32":
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.SetForegroundWindow.argtypes = [wintypes.HWND]
            user32.SetForegroundWindow(self._foreground)

    def eventFilter(self, watched, event) -> bool:
        if watched is self._app and event.type() in (
                QEvent.Type.ApplicationDeactivate, QEvent.Type.ApplicationStateChange):
            self.schedule_focus_check()
        return False

    def schedule_focus_check(self) -> None:
        if not self._closed and not self._opening:
            self._focus_check.start()

    def _owns_focus(self) -> bool:
        app = QApplication.instance()
        return bool(app and app.applicationState() == Qt.ApplicationState.ApplicationActive
                    and app.activeWindow() in self.windows)

    def _check_focus(self) -> None:
        # Focus moving between our monitor windows is normal, not cancellation.
        if self._closed or self._opening or self._owns_focus():
            return
        self.cancel("已切换到其他窗口，框选已取消，蒙层已关闭。", restore_foreground=False)

    def _release_mouse(self) -> None:
        grabber, self._grabber = self._grabber, None
        if grabber:
            try:
                grabber.releaseMouse()
            except RuntimeError:
                logging.getLogger(__name__).warning("Selection mouse grabber was already destroyed")

    def begin(self, position: tuple[int, int], window: _SelectionWindow) -> None:
        if self._closed:
            return
        self.start = self.end = position
        self._grabber = window
        window.grabMouse()
        self._refresh()

    def move(self, position: tuple[int, int]) -> None:
        if self._closed:
            return
        self.end = position
        self._refresh()

    def finish(self, position: tuple[int, int]) -> None:
        if self._closed:
            return
        self.end = position
        self._release_mouse()
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

    def cancel(self, reason: str | None = None, *, restore_foreground: bool = True) -> None:
        if self._closed:
            return
        self.shutdown(restore_foreground=restore_foreground)
        self.cancelled.emit()
        if reason:
            self.failed.emit(reason)

    def fail(self, message: str) -> None:
        if self._closed:
            return
        self.cancel(message)

    def shutdown(self, *, restore_foreground: bool = True) -> None:
        if self._closed:
            return
        restore = restore_foreground and self._owns_focus()
        self._closed = True
        self._timeout.stop()
        self._focus_check.stop()
        self._release_mouse()
        windows, self.windows = self.windows, []
        for window in windows:
            for operation in (window.hide, window.close, window.deleteLater):
                try:
                    operation()
                except RuntimeError:
                    logging.getLogger(__name__).warning("Selection window was already destroyed")
        app = QApplication.instance()
        if app:
            if self._app is app:
                app.removeEventFilter(self)
                self._app = None
            app.setProperty("regionSelecting", False)
            # Do not reinterpret the selector's cancelling Esc as a subtitle toggle.
            app.setProperty("regionEscapeSuppressedUntil", time.monotonic() + 0.25)
        if restore:
            try:
                self._restore_foreground()
            except OSError:
                logging.getLogger(__name__).warning("Could not restore foreground after selection")
