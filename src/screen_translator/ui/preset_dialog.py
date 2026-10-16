"""Manage local scene presets; applying is delegated to the live application."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QInputDialog, QLabel,
                               QListWidget, QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from screen_translator.contracts import Settings
from screen_translator.core.scene_presets import PresetError, ScenePreset
from screen_translator.storage.presets import PresetStore


class PresetDialog(QDialog):
    def __init__(self, store: PresetStore, current: Callable[[], Settings],
                 apply: Callable[[ScenePreset], tuple[bool, str]], parent=None):
        super().__init__(parent)
        self.store, self.current, self.apply = store, current, apply
        self.rows: list[ScenePreset] = []
        self.setWindowTitle("屏幕中英翻译 · 场景预设")
        self.setMinimumWidth(560)
        screen = self.screen()
        area = screen.availableGeometry() if screen else None
        self.resize(min(760, max(560, area.width() - 32)) if area else 760,
                    max(280, min(560, area.height() - 64)) if area else 560)
        self.setStyleSheet("QWidget { font-family: 'Microsoft YaHei UI'; font-size: 13px; }"
                           "QPushButton { padding: 7px 12px; }")
        layout = QVBoxLayout(self)
        hint = QLabel("把不同游戏、聊天或阅读场景保存为预设。保存的是当前已生效设置，不含设置窗口未保存的修改。\n"
                      "应用预设会清空字幕并暂停持续翻译；使用启停快捷键恢复。预设仅保存在本机。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        middle = QHBoxLayout()
        layout.addLayout(middle, 1)
        self.list = QListWidget()
        self.list.setMinimumWidth(180)
        self.list.currentRowChanged.connect(self._selected)
        middle.addWidget(self.list, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        panel = QWidget()
        controls = QVBoxLayout(panel)
        scroll.setWidget(panel)
        middle.addWidget(scroll, 2)
        self.summary = QLabel("尚无预设，请先保存当前设置。")
        self.summary.setWordWrap(True)
        self.summary.setAlignment(Qt.AlignmentFlag.AlignTop)
        controls.addWidget(self.summary, 1)
        self.include_region = QCheckBox("保存选区及字幕位置")
        self.include_region.setChecked(True)
        controls.addWidget(self.include_region)
        spatial_hint = QLabel("不勾选时，应用预设会保留当前选区。分辨率、显示器或游戏界面缩放改变后，请重新框选。\n"
                              "开机启动、启动动画和许可确认记录始终保留，不属于场景设置。")
        spatial_hint.setWordWrap(True)
        spatial_hint.setStyleSheet("color: #64748b; font-size: 12px;")
        controls.addWidget(spatial_hint)
        self.save_button = QPushButton("保存当前设置为新预设…")
        self.update_button = QPushButton("用当前设置更新所选预设…")
        self.apply_button = QPushButton("应用所选预设并暂停翻译")
        self.rename_button = QPushButton("重命名…")
        self.delete_button = QPushButton("删除…")
        for button, action in ((self.save_button, self._save_new), (self.update_button, self._update),
                               (self.apply_button, self._apply)):
            controls.addWidget(button)
            button.clicked.connect(action)
        maintenance = QHBoxLayout()
        for button, action in ((self.rename_button, self._rename), (self.delete_button, self._delete)):
            maintenance.addWidget(button)
            button.clicked.connect(action)
        controls.addLayout(maintenance)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        footer = QHBoxLayout()
        layout.addLayout(footer)
        self.refresh_button = QPushButton("刷新列表")
        self.refresh_button.clicked.connect(lambda: self.refresh())
        footer.addWidget(self.refresh_button)
        footer.addStretch()
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.close)
        footer.addWidget(close_button)
        self.refresh()

    def _error(self, error: Exception) -> None:
        self.status.setText(str(error) if isinstance(error, PresetError) else
                            "无法读写预设，请检查磁盘空间及用户数据目录权限；原文件未被替换。")

    def refresh(self, selected_name: str | None = None) -> None:
        self.list.clear()
        self.rows = []
        try:
            self.rows = self.store.list_presets()
        except (OSError, PresetError) as error:
            self._error(error)
            self.save_button.setEnabled(False)
            self._selected(-1)
            return
        self.save_button.setEnabled(True)
        self.list.addItems([row.name for row in self.rows])
        index = next((i for i, row in enumerate(self.rows) if row.name == selected_name), 0)
        self.list.setCurrentRow(index if self.rows else -1)
        self._selected(self.list.currentRow())

    def _selected(self, index: int) -> None:
        valid = 0 <= index < len(self.rows)
        for button in (self.apply_button, self.update_button, self.rename_button, self.delete_button):
            button.setEnabled(valid)
        if not valid:
            self.summary.setText("尚无可用预设，请保存当前设置。最多 20 个预设。")
            return
        row = self.rows[index]
        values = row.values
        self.include_region.setChecked(row.include_region)
        direction = {"auto": "自动中英互译", "en-zh": "英文 → 中文", "zh-en": "中文 → 英文"}[values["direction"]]
        region = values.get("region")
        spatial = (f"保存的选区：{region['width']} × {region['height']}" if region else "保存时没有选区") if row.include_region else "不恢复选区，保留当前区域"
        self.summary.setText(f"{row.name}\n\n{direction} · {'逐行对话' if values['text_layout'] == 'lines' else '连续文本'}\n"
                             f"字幕：{values['font_size']} pt · 不透明度 {round(values['opacity'] * 100)}%\n"
                             f"聊天词表：{'开启' if values['chat_slang_enabled'] else '关闭'}\n"
                             f"{spatial}\n启停键：{values['hotkeys']['toggle']}")

    def _row(self) -> ScenePreset | None:
        index = self.list.currentRow()
        return self.rows[index] if 0 <= index < len(self.rows) else None

    def _confirm(self, title: str, text: str) -> bool:
        return QMessageBox.question(self, title, text,
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def _save_new(self) -> None:
        name, accepted = QInputDialog.getText(self, "保存场景预设", "预设名称（1–40 个字符）")
        if not accepted:
            return
        try:
            self.store.save(name, self.current(), self.include_region.isChecked())
            from screen_translator.core.scene_presets import clean_preset_name
            self.refresh(clean_preset_name(name))
            self.status.setText("预设已保存；当前运行设置没有改变。")
        except (OSError, PresetError) as error:
            self._error(error)

    def _update(self) -> None:
        row = self._row()
        if row is None or not self._confirm("更新预设", f"用当前已生效设置覆盖“{row.name}”？"):
            return
        try:
            self.store.save(row.name, self.current(), self.include_region.isChecked(), replace=True)
            self.refresh(row.name)
            self.status.setText("预设已更新；当前运行设置没有改变。")
        except (OSError, PresetError) as error:
            self._error(error)

    def _rename(self) -> None:
        row = self._row()
        if row is None:
            return
        name, accepted = QInputDialog.getText(self, "重命名预设", "新名称", text=row.name)
        if not accepted:
            return
        try:
            self.store.rename(row.name, name)
            from screen_translator.core.scene_presets import clean_preset_name
            self.refresh(clean_preset_name(name))
            self.status.setText("预设已重命名。")
        except (OSError, PresetError) as error:
            self._error(error)

    def _delete(self) -> None:
        row = self._row()
        if row is None or not self._confirm("删除预设", f"删除“{row.name}”？此操作不可撤销，但不会改变当前设置。"):
            return
        try:
            self.store.delete(row.name)
            self.refresh()
            self.status.setText("预设已删除，当前设置保留。")
        except (OSError, PresetError) as error:
            self._error(error)

    def _apply(self) -> None:
        row = self._row()
        if row is None:
            return
        try:
            # Reread, so an external update/deletion is never applied stale.
            row = next((item for item in self.store.list_presets() if item.name == row.name), None)
            if row is None:
                raise PresetError("该预设已不存在，请刷新列表")
            success, message = self.apply(row)
            self.status.setText(message)
            if success:
                self.accept()
        except (OSError, PresetError) as error:
            self._error(error)
