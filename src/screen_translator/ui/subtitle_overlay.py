from __future__ import annotations

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from screen_translator.contracts import Settings, TranslationResult
from screen_translator.platform.windows.window_styles import apply_overlay_styles, set_capture_exclusion
from screen_translator.ui.display_coordinates import screen_mappings


class SubtitleOverlay(QWidget):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = Settings.from_dict(settings.to_dict())
        self.capture_excluded = False
        self.capture_policy_applied = False
        self.native_input_safe = False
        self.overlaps_capture = False
        self.physical_bounds: tuple[int, int, int, int] | None = None
        self._native_hwnd: int | None = None
        self._applied_exclusion: bool | None = None
        self._topmost_timer = QTimer(self)
        self._topmost_timer.setInterval(1000)
        self._topmost_timer.timeout.connect(self._apply_native)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                            | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.WindowDoesNotAcceptFocus
                            | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(18, 12, 18, 12)
        self._layout.setSpacing(8)
        self.source_label = QLabel()
        self.translation_label = QLabel()
        for label in (self.source_label, self.translation_label):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            label.setStyleSheet("background: transparent; color: white;")
            label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.source_label.setStyleSheet("background: transparent; color: #c7d0dc;")
        self._layout.addWidget(self.source_label)
        self._layout.addWidget(self.translation_label)
        self._result: TranslationResult | None = None
        self.update_settings(settings)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(13, 20, 30, round(255 * self.settings.opacity)))
        painter.drawRoundedRect(self.rect(), 12, 12)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._apply_native()
        if self.isVisible() and self.native_input_safe:
            self._topmost_timer.start()

    def hideEvent(self, event) -> None:
        self._topmost_timer.stop()
        if self._native_hwnd is not None:
            set_capture_exclusion(self._native_hwnd, False)
        self.capture_excluded = False
        self._applied_exclusion = None
        super().hideEvent(event)

    def _apply_native(self) -> None:
        # New background results/settings must not reapply exclusion or
        # topmost to an Esc-hidden subtitle window. showEvent restores it.
        if not self.isVisible():
            return
        hwnd = int(self.winId())
        if hwnd != self._native_hwnd:
            self._native_hwnd = hwnd
            self._applied_exclusion = None
        # Reassert topmost without activation after a borderless game changes
        # its own z-order. This does not promise exclusive-fullscreen support.
        self.native_input_safe = apply_overlay_styles(hwnd)
        requested = not self.settings.recording_compatibility
        if requested != self._applied_exclusion:
            self.capture_policy_applied = set_capture_exclusion(hwnd, requested)
            self.capture_excluded = requested and self.capture_policy_applied
            if self.capture_policy_applied:
                self._applied_exclusion = requested
        if not self.native_input_safe or (self.settings.recording_compatibility
                                         and not self.capture_policy_applied):
            self.hide()

    def update_settings(self, settings: Settings) -> None:
        self.settings = Settings.from_dict(settings.to_dict())
        self.translation_label.setFont(QFont("Microsoft YaHei UI", self.settings.font_size))
        self.source_label.setFont(QFont("Microsoft YaHei UI", max(10, self.settings.font_size - 7)))
        self.source_label.setVisible(self.settings.show_source and bool(self.source_label.text()))
        self.reposition()
        self._applied_exclusion = None
        if self.isVisible():
            self._apply_native()
        self.update()

    def set_result(self, result: TranslationResult) -> None:
        self._result = result
        self.source_label.setVisible(self.settings.show_source and bool(result.source))
        self.reposition()

    def clear_result(self) -> None:
        self._result = None
        self.source_label.clear()
        self.translation_label.clear()
        self.hide()

    @staticmethod
    def _fit_text(text: str, font: QFont, width: int, max_height: int, source: bool = False) -> str:
        """Fit actual word-wrapped glyphs and explicitly mark any visual truncation."""
        if not text:
            return ""
        metrics = QFontMetrics(font)
        suffix = "…〔原文截断〕" if source else "…〔已截断〕"

        def fits(candidate: str) -> bool:
            rect = metrics.boundingRect(QRect(0, 0, width, 100000),
                                        Qt.TextFlag.TextWordWrap, candidate)
            return rect.height() <= max_height

        if len(text) <= 12000 and fits(text):
            return text
        low, high = 0, min(len(text), 12000)
        while low < high:
            mid = (low + high + 1) // 2
            if fits(text[:mid].rstrip() + suffix):
                low = mid
            else:
                high = mid - 1
        return text[:low].rstrip() + suffix

    def reposition(self) -> None:
        mappings = screen_mappings()
        if not mappings:
            return
        region = self.settings.region
        mapping = next((item for item in mappings if region and (
            item.monitor.id.casefold() == region.monitor_id.casefold()
            or item.monitor.contains(region.x, region.y))), None)
        mapping = mapping or next((item for item in mappings if item.monitor.primary), mappings[0])
        self.winId()
        if self.windowHandle():
            self.windowHandle().setScreen(mapping.screen)
        area = mapping.physical_rect_to_qt(mapping.monitor.work_area)
        preferred_width = min(780, max(280, area.width() - 32))
        if region:
            preferred_width = min(preferred_width, max(320, round(region.width / mapping.scale_x)))
        self.setFixedWidth(min(preferred_width, max(100, area.width() - 16)))
        max_height = max(44, min(560, round(area.height() * 0.45), area.height() - 32))
        content_width = max(64, self.width() - 36)
        source_height = 0
        if self._result:
            if self.settings.show_source and self._result.source:
                source_height = min(QFontMetrics(self.source_label.font()).lineSpacing() * 3,
                                    max_height // 3)
                self.source_label.setText(self._fit_text(self._result.source, self.source_label.font(),
                                                         content_width, source_height, source=True))
                source_height = QFontMetrics(self.source_label.font()).boundingRect(
                    QRect(0, 0, content_width, 100000), Qt.TextFlag.TextWordWrap,
                    self.source_label.text()).height() + 8
            else:
                self.source_label.setText(self._result.source[:12000])
            translation_height = max(QFontMetrics(self.translation_label.font()).lineSpacing(),
                                     max_height - 24 - source_height)
            self.translation_label.setText(self._fit_text(self._result.translation,
                                                         self.translation_label.font(),
                                                         content_width, translation_height))
        self._layout.activate()
        hint_height = self.heightForWidth(self.width())
        if hint_height < 0:
            hint_height = self.sizeHint().height()
        self.setFixedHeight(max(44, min(hint_height, max_height)))
        gap = 12
        x = area.x() + (area.width() - self.width()) // 2
        y = area.bottom() - self.height() - gap
        if self.settings.overlay_position:
            point = mapping.physical_to_qt(*self.settings.overlay_position)
            x, y = point.x(), point.y()
        elif region:
            rect = mapping.physical_rect_to_qt((region.x, region.y,
                                               region.x + region.width,
                                               region.y + region.height))
            x = rect.x() + (rect.width() - self.width()) // 2
            if rect.bottom() + gap + self.height() <= area.bottom():
                y = rect.bottom() + gap
            elif rect.top() - gap - self.height() >= area.top():
                y = rect.top() - gap - self.height()
            elif rect.right() + gap + self.width() <= area.right():
                x, y = rect.right() + gap, rect.top()
            elif rect.left() - gap - self.width() >= area.left():
                x, y = rect.left() - gap - self.width(), rect.top()
        x = max(area.left() + 8, min(x, area.right() - self.width() - 8))
        y = max(area.top() + 8, min(y, area.bottom() - self.height() - 8))
        self.move(x, y)
        self.physical_bounds = mapping.qt_rect_to_physical(self.geometry())
        if region:
            left, top, right, bottom = self.physical_bounds
            self.overlaps_capture = (left < region.x + region.width and right > region.x
                                     and top < region.y + region.height and bottom > region.y)
        else:
            self.overlaps_capture = False
        if self._native_hwnd is not None and self.isVisible():
            self._apply_native()
