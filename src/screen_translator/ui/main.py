from __future__ import annotations

from PySide6.QtCore import QObject, QRect, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QDialog, QMenu, QSystemTrayIcon

from screen_translator.contracts import Region, Settings, TranslationResult
from screen_translator.ui.region_selector import RegionSelector
from screen_translator.ui.settings_window import SettingsDialog
from screen_translator.ui.subtitle_overlay import SubtitleOverlay


def _tray_icon(running: bool = False) -> QIcon:
    image = QPixmap(64, 64)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#0f766e" if running else "#334155"))
    painter.drawRoundedRect(QRect(2, 2, 60, 60), 14, 14)
    painter.setFont(QFont("Microsoft YaHei UI", 32, QFont.Weight.Bold))
    painter.setPen(QColor("white"))
    painter.drawText(QRect(0, -2, 64, 64), Qt.AlignmentFlag.AlignCenter, "译")
    painter.end()
    return QIcon(image)


class MainUI(QObject):
    region_selected = Signal(object)
    selection_started = Signal()
    selection_cancelled = Signal()
    toggle_requested = Signal()
    clear_requested = Signal()
    hide_requested = Signal()
    quit_requested = Signal()
    settings_changed = Signal(object)

    def __init__(self, settings: Settings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.settings = Settings.from_dict(settings.to_dict())
        self.overlay = SubtitleOverlay(self.settings)
        self.hidden = False
        self.running = False
        self._closed = False
        self._latest: TranslationResult | None = None
        self._selector: RegionSelector | None = None
        self._settings_dialog: SettingsDialog | None = None
        self._was_visible_before_selection = False
        self._overlap_warning_shown = False
        self._status = "已就绪 · Alt+R 框选区域"
        self._normal_icon = _tray_icon()
        self._running_icon = _tray_icon(True)
        self.tray = QSystemTrayIcon(self._normal_icon, self)
        self.menu = QMenu()
        self.status_action = self.menu.addAction(self._status)
        self.status_action.setEnabled(False)
        self.menu.addSeparator()
        self.select_action = self.menu.addAction("框选翻译区域")
        self.select_action.triggered.connect(self.select_region)
        self.toggle_action = self.menu.addAction("开启持续翻译")
        self.toggle_action.triggered.connect(self.toggle_requested.emit)
        self.clear_action = self.menu.addAction("清空翻译结果")
        self.clear_action.triggered.connect(self.clear_requested.emit)
        self.hide_action = self.menu.addAction("临时隐藏字幕")
        self.hide_action.setCheckable(True)
        self.hide_action.triggered.connect(lambda: self.hide_requested.emit())
        self.copy_action = self.menu.addAction("复制当前译文")
        self.copy_action.setEnabled(False)
        self.copy_action.triggered.connect(self._copy_translation)
        self.menu.addSeparator()
        self.settings_action = self.menu.addAction("设置…")
        self.settings_action.triggered.connect(self._show_settings)
        exit_action = self.menu.addAction("退出")
        exit_action.triggered.connect(self.quit_requested.emit)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._tray_activated)
        self._update_action_labels()
        self.tray.setToolTip("屏幕中英翻译\n" + self._status)
        self.tray.show()

    @property
    def is_hidden(self) -> bool:
        return self.hidden

    def _tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.toggle_requested.emit()

    def _update_action_labels(self) -> None:
        self.select_action.setText("框选翻译区域    " + self.settings.hotkeys.get("select", ""))
        self.toggle_action.setText(("停止持续翻译    " if self.running else "开启持续翻译    ")
                                  + self.settings.hotkeys.get("toggle", ""))
        self.clear_action.setText("清空翻译结果    " + self.settings.hotkeys.get("clear", ""))
        self.hide_action.setText("临时隐藏字幕    Esc" if self.settings.esc_enabled else "临时隐藏字幕")

    def set_status(self, message: str, running: bool | None = None) -> None:
        self._status = str(message)
        self.status_action.setText(self._status[:150])
        self.tray.setToolTip(("屏幕中英翻译\n" + self._status)[:127])
        if running is not None:
            self.running = bool(running)
            self.tray.setIcon(self._running_icon if self.running else self._normal_icon)
            self._update_action_labels()

    def notify(self, title: str, message: str, warning: bool = False) -> None:
        icon = QSystemTrayIcon.MessageIcon.Warning if warning else QSystemTrayIcon.MessageIcon.Information
        self.tray.showMessage(str(title), str(message), icon, 3500)

    def show_result(self, result: TranslationResult) -> None:
        self._latest = result
        self.copy_action.setEnabled(bool(result.translation))
        self.overlay.set_result(result)
        if not self.hidden and self._selector is None and result.translation.strip():
            self._show_overlay_safely()

    def _show_overlay_safely(self) -> None:
        self.overlay.show()
        if self.overlay.overlaps_capture and not self.overlay.capture_excluded:
            self.overlay.hide()
            if not self._overlap_warning_shown:
                self._overlap_warning_shown = True
                self.notify("字幕暂未显示", "选区没有留出字幕空间，系统也未能排除字幕截图。"
                            "请缩小选区；当前完整译文仍可从托盘复制。", warning=True)

    def clear_result(self) -> None:
        self._latest = None
        self.copy_action.setEnabled(False)
        self.overlay.clear_result()

    def set_hidden(self, enabled: bool) -> None:
        self.hidden = bool(enabled)
        self.hide_action.blockSignals(True)
        self.hide_action.setChecked(self.hidden)
        self.hide_action.blockSignals(False)
        if self.hidden:
            self.overlay.hide()
        elif self._latest and self._latest.translation.strip() and self._selector is None:
            self._show_overlay_safely()

    def select_region(self) -> None:
        if self._selector is not None or self._closed:
            return
        self._was_visible_before_selection = self.overlay.isVisible()
        self.overlay.hide()
        self.selection_started.emit()
        selector = RegionSelector(self)
        self._selector = selector
        selector.selected.connect(self._region_selected)
        selector.cancelled.connect(self._selection_cancelled)
        selector.failed.connect(lambda message: self.notify("无法读取鼠标位置", message, warning=True))
        try:
            selector.show()
        except OSError as exc:
            selector.cancel()
            self.notify("无法框选区域", str(exc), warning=True)

    def _release_selector(self) -> None:
        selector, self._selector = self._selector, None
        if selector:
            selector.deleteLater()

    def _region_selected(self, region: Region) -> None:
        self._release_selector()
        self.settings.region = region
        self._overlap_warning_shown = False
        self.overlay.update_settings(self.settings)
        self.clear_result()
        self.region_selected.emit(region)

    def _selection_cancelled(self) -> None:
        self._release_selector()
        if self._was_visible_before_selection and not self.hidden and self._latest:
            self._show_overlay_safely()
        self.selection_cancelled.emit()

    def update_settings(self, settings: Settings) -> None:
        self.settings = Settings.from_dict(settings.to_dict())
        self._overlap_warning_shown = False
        self.overlay.update_settings(self.settings)
        self._update_action_labels()
        if self.overlay.isVisible() and self._latest and not self.hidden:
            self._show_overlay_safely()

    def _show_settings(self) -> None:
        if self._settings_dialog is not None:
            self._settings_dialog.raise_()
            self._settings_dialog.activateWindow()
            return
        dialog = SettingsDialog(self.settings)
        self._settings_dialog = dialog
        dialog.finished.connect(lambda result: self._settings_finished(dialog, result))
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _settings_finished(self, dialog: SettingsDialog, result: int) -> None:
        if result == QDialog.DialogCode.Accepted:
            self.settings_changed.emit(dialog.values())
        if self._settings_dialog is dialog:
            self._settings_dialog = None
        dialog.deleteLater()

    def _copy_translation(self) -> None:
        if self._latest:
            QApplication.clipboard().setText(self._latest.translation)

    def close(self) -> None:
        self._closed = True
        if self._selector:
            self._selector.shutdown()
            self._release_selector()
        if self._settings_dialog:
            self._settings_dialog.close()
        self.overlay.close()
        self.tray.hide()
        self.menu.close()
        self.menu.deleteLater()
