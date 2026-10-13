"""Short, non-interactive startup presentation; never starts inference or capture."""
from __future__ import annotations

import math

from PySide6.QtCore import QElapsedTimer, Property, QPropertyAnimation, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QWidget


CARD_WIDTH = 360
CARD_HEIGHT = 196
PRESENTATION_MS = 2000


def card_geometry(available: QRect) -> QRect:
    """Center in one Qt logical work area, including small/negative-origin screens."""
    width = min(CARD_WIDTH, max(1, available.width()))
    height = min(CARD_HEIGHT, max(1, available.height()))
    left = available.left() + max(0, (available.width() - width) // 2)
    top = available.top() + max(0, (available.height() - height) // 2)
    return QRect(left, top, width, height)


class StartupCard(QWidget):
    """One-shot two-second card, with a static reduced-motion alternative.

    The caller is responsible for suppressing presentation in games/background
    launches. This widget does not activate, raise, remain on top, register
    shortcuts, read the desktop, or load translation models.
    """

    finished = Signal()
    completed = Signal()

    def __init__(self, status: str = "已启动 · 可从托盘操作", *,
                 animations_enabled: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.status = status
        self.animations_enabled = bool(animations_enabled)
        self._progress = 0.0
        self._started = False
        self._finished = False
        self._elapsed = QElapsedTimer()
        self.setObjectName("startupCard")
        self.setWindowTitle("本地屏幕翻译器")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                            | Qt.WindowType.WindowDoesNotAcceptFocus
                            | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.resize(CARD_WIDTH, CARD_HEIGHT)
        self._animation = QPropertyAnimation(self, b"progress", self)
        self._animation.setDuration(PRESENTATION_MS)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.finished.connect(self._complete)
        self._watchdog = QTimer(self)
        self._watchdog.setSingleShot(True)
        self._watchdog.setTimerType(Qt.TimerType.PreciseTimer)
        self._watchdog.setInterval(PRESENTATION_MS)
        self._watchdog.timeout.connect(self._complete)

    def get_progress(self) -> float:
        return self._progress

    def set_progress(self, value: float) -> None:
        value = float(value)
        if not math.isfinite(value):
            value = 0.0
        self._progress = min(1.0, max(0.0, value))
        self.update()

    progress = Property(float, get_progress, set_progress)

    def start(self) -> None:
        """Show once without blocking; repeated calls never extend its lifetime."""
        if self._started or self._finished:
            return
        self._started = True
        self._elapsed.start()
        app = QApplication.instance()
        screen = app.primaryScreen() if app is not None else None
        if screen is not None:
            self.setGeometry(card_geometry(screen.availableGeometry()))
        self.set_progress(0.0 if self.animations_enabled else 0.45)
        self.show()
        self._watchdog.start()
        if self.animations_enabled:
            self._animation.start()

    def _complete(self) -> None:
        """Natural expiry only; an animation clock cannot shorten the display."""
        if self._finished or not self._started:
            return
        remaining = PRESENTATION_MS - self._elapsed.elapsed()
        if remaining > 0:
            self._watchdog.start(remaining)
            return
        self._finish(completed=True)

    def finish_now(self) -> None:
        """Cancel once; never emit the successful-presentation signal."""
        self._finish(completed=False)

    def _finish(self, *, completed: bool) -> None:
        """Stop and hide before callbacks; queue deletion after both signals."""
        if self._finished:
            return
        self._finished = True
        self._watchdog.stop()
        self._animation.stop()
        self.hide()
        self.close()
        self.finished.emit()
        if completed:
            self.completed.emit()
        self.deleteLater()

    def closeEvent(self, event) -> None:
        self.finish_now()
        super().closeEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.scale(self.width() / CARD_WIDTH, self.height() / CARD_HEIGHT)
        opacity = 1.0
        if self.animations_enabled:
            opacity = min(1.0, self._progress / 0.14,
                          max(0.0, (1.0 - self._progress) / 0.20))
        painter.setOpacity(opacity)
        bounds = QRectF(1.0, 1.0, CARD_WIDTH - 2.0, CARD_HEIGHT - 2.0)
        background = QLinearGradient(0.0, 0.0, CARD_WIDTH, CARD_HEIGHT)
        background.setColorAt(0.0, QColor("#132c49"))
        background.setColorAt(1.0, QColor("#09182a"))
        painter.setBrush(background)
        painter.setPen(QPen(QColor("#345572"), 1.0))
        painter.drawRoundedRect(bounds, 18.0, 18.0)

        # Selection corners and the A / 中 pair are painted vectors, not assets.
        icon = QRectF(25.0, 25.0, 82.0, 53.0)
        path = QPainterPath()
        arm = 10.0
        for x, y, horizontal, vertical in (
            (icon.left(), icon.top(), 1, 1),
            (icon.right(), icon.top(), -1, 1),
            (icon.left(), icon.bottom(), 1, -1),
            (icon.right(), icon.bottom(), -1, -1),
        ):
            path.moveTo(x + horizontal * arm, y)
            path.lineTo(x, y)
            path.lineTo(x, y + vertical * arm)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#5bd8df"), 2.0))
        painter.drawPath(path)
        painter.setFont(QFont("Microsoft YaHei UI", 15, QFont.Weight.DemiBold))
        painter.setPen(QColor("#eef7ff"))
        painter.drawText(QRectF(32.0, 31.0, 25.0, 36.0), Qt.AlignmentFlag.AlignCenter, "A")
        painter.setPen(QColor("#5bd8df"))
        painter.drawText(QRectF(74.0, 31.0, 27.0, 36.0), Qt.AlignmentFlag.AlignCenter, "中")
        painter.setPen(QPen(QColor("#91a9c1"), 1.6))
        painter.drawLine(60, 47, 70, 47)
        painter.drawLine(67, 44, 70, 47)
        painter.drawLine(67, 50, 70, 47)
        painter.drawLine(70, 56, 60, 56)
        painter.drawLine(63, 53, 60, 56)
        painter.drawLine(63, 59, 60, 56)

        if self.animations_enabled:
            scan = icon.top() + icon.height() * min(1.0, max(0.0, (self._progress - 0.14) / 0.66))
            scan_gradient = QLinearGradient(icon.left(), scan, icon.right(), scan)
            scan_gradient.setColorAt(0.0, QColor(91, 216, 223, 0))
            scan_gradient.setColorAt(0.5, QColor(91, 216, 223, 200))
            scan_gradient.setColorAt(1.0, QColor(91, 216, 223, 0))
            painter.fillRect(QRectF(icon.left(), scan, icon.width(), 1.6), scan_gradient)

        painter.setPen(QColor("#f2f6fc"))
        painter.setFont(QFont("Microsoft YaHei UI", 17, QFont.Weight.DemiBold))
        painter.drawText(QRectF(24.0, 92.0, 312.0, 33.0),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         "本地屏幕翻译器")
        painter.setPen(QColor("#b7c7db"))
        painter.setFont(QFont("Microsoft YaHei UI", 9))
        painter.drawText(QRectF(25.0, 128.0, 311.0, 22.0),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         "本地 OCR · 离线中英翻译")
        painter.setPen(QColor("#7f9bb9"))
        painter.setFont(QFont("Microsoft YaHei UI", 9))
        status = painter.fontMetrics().elidedText(self.status, Qt.TextElideMode.ElideRight, 312)
        painter.drawText(QRectF(25.0, 159.0, 311.0, 20.0),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, status)
