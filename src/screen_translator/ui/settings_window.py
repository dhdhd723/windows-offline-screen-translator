from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFormLayout, QLabel, QLineEdit,
                               QMessageBox, QSlider, QSpinBox, QTabWidget,
                               QVBoxLayout, QWidget)

from screen_translator.contracts import Settings
from screen_translator.platform.windows.hotkeys import parse_hotkey


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._original = Settings.from_dict(settings.to_dict())
        self.setWindowTitle("屏幕中英翻译 · 设置")
        self.setMinimumWidth(540)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self.setStyleSheet("QWidget { font-family: 'Microsoft YaHei UI'; font-size: 13px; }"
                           "QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { padding: 5px; }"
                           "QTabWidget::pane { padding: 10px; }")
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        display = QWidget()
        display_form = QFormLayout(display)
        display_form.setVerticalSpacing(16)
        self.direction = QComboBox()
        for text, data in (("自动判断中英方向", "auto"),
                           ("中文 → 英文", "zh-en"), ("英文 → 中文", "en-zh")):
            self.direction.addItem(text, data)
        self.direction.setCurrentIndex(max(0, self.direction.findData(settings.direction)))
        display_form.addRow("翻译方向", self.direction)
        self.font_size = QSpinBox()
        self.font_size.setRange(12, 48)
        self.font_size.setSuffix(" pt")
        self.font_size.setValue(settings.font_size)
        display_form.addRow("字幕字号", self.font_size)
        opacity_box = QWidget()
        opacity_layout = QVBoxLayout(opacity_box)
        opacity_layout.setContentsMargins(0, 0, 0, 0)
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(25, 100)
        self.opacity.setValue(round(settings.opacity * 100))
        self.opacity_label = QLabel(f"{self.opacity.value()}%")
        self.opacity.valueChanged.connect(lambda value: self.opacity_label.setText(f"{value}%"))
        opacity_layout.addWidget(self.opacity)
        opacity_layout.addWidget(self.opacity_label)
        display_form.addRow("背景不透明度", opacity_box)
        self.show_source = QCheckBox("在译文上方同时显示原文")
        self.show_source.setChecked(settings.show_source)
        display_form.addRow("原文", self.show_source)
        hint = QLabel("字幕窗始终置顶、鼠标穿透，不会抢走当前程序焦点。\n框选成功后，字幕默认显示在区域外侧。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #64748b; font-size: 12px;")
        display_form.addRow(hint)
        tabs.addTab(display, "显示与翻译")

        controls = QWidget()
        controls_form = QFormLayout(controls)
        controls_form.setVerticalSpacing(14)
        self.hotkeys: dict[str, QLineEdit] = {}
        for key, label in (("select", "框选区域"), ("toggle", "开启 / 停止"), ("clear", "清空结果")):
            field = QLineEdit(settings.hotkeys.get(key, ""))
            field.setPlaceholderText("例如 Alt+R 或 Ctrl+Shift+R")
            controls_form.addRow(label, field)
            self.hotkeys[key] = field
        self.esc = QCheckBox("监控期间按 Esc 隐藏 / 恢复字幕")
        self.esc.setChecked(settings.esc_enabled)
        controls_form.addRow(self.esc)
        self.auto_start = QCheckBox("登录 Windows 后自动启动到托盘")
        self.auto_start.setChecked(settings.auto_start)
        controls_form.addRow(self.auto_start)
        hint = QLabel("Esc 会继续传递给当前程序。关闭此选项后仍可用托盘菜单隐藏字幕。\n快捷键如果被其他程序占用，保存后会显示提示。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #64748b; font-size: 12px;")
        controls_form.addRow(hint)
        tabs.addTab(controls, "快捷键")

        performance = QWidget()
        performance_form = QFormLayout(performance)
        performance_form.setVerticalSpacing(14)
        self.cpu_threads = QSpinBox()
        self.cpu_threads.setRange(1, 4)
        self.cpu_threads.setValue(settings.cpu_threads)
        performance_form.addRow("推理 CPU 线程", self.cpu_threads)
        self.capture_fps = QDoubleSpinBox()
        self.capture_fps.setRange(1, 12)
        self.capture_fps.setDecimals(1)
        self.capture_fps.setValue(settings.capture_fps)
        self.capture_fps.setSuffix(" 帧 / 秒")
        performance_form.addRow("正常监控频率", self.capture_fps)
        self.idle_fps = QDoubleSpinBox()
        self.idle_fps.setRange(0.5, 12)
        self.idle_fps.setDecimals(1)
        self.idle_fps.setValue(settings.idle_fps)
        self.idle_fps.setSuffix(" 帧 / 秒")
        performance_form.addRow("静态画面监控频率", self.idle_fps)
        self.debounce = QSpinBox()
        self.debounce.setRange(80, 1000)
        self.debounce.setSingleStep(20)
        self.debounce.setValue(settings.debounce_ms)
        self.debounce.setSuffix(" ms")
        performance_form.addRow("文字稳定等待", self.debounce)
        self.ocr_interval = QSpinBox()
        self.ocr_interval.setRange(200, 3000)
        self.ocr_interval.setSingleStep(50)
        self.ocr_interval.setValue(settings.min_ocr_interval_ms)
        self.ocr_interval.setSuffix(" ms")
        performance_form.addRow("最短识别间隔", self.ocr_interval)
        self.cache = QCheckBox("允许将翻译缓存保存在本机")
        self.cache.setChecked(settings.cache_enabled)
        performance_form.addRow(self.cache)
        hint = QLabel("关闭磁盘缓存时仍在内存中去重，退出程序后内存缓存消失。\n所有识别和翻译均在本机完成，不会上传屏幕或文字。\n降低频率、使用 1–2 个推理线程有助于减少常驻占用。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #64748b; font-size: 12px;")
        performance_form.addRow(hint)
        tabs.addTab(performance, "性能与缓存")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self) -> None:
        combinations: set[tuple[int, int]] = set()
        try:
            for field in self.hotkeys.values():
                parsed = parse_hotkey(field.text().strip())
                if parsed in combinations:
                    raise ValueError("三个快捷键不能重复")
                combinations.add(parsed)
        except ValueError as exc:
            QMessageBox.warning(self, "快捷键格式有误", str(exc))
            return
        self.accept()

    def values(self) -> Settings:
        data = self._original.to_dict()
        data.update(direction=self.direction.currentData(),
                    font_size=self.font_size.value(), opacity=self.opacity.value() / 100,
                    show_source=self.show_source.isChecked(), esc_enabled=self.esc.isChecked(),
                    auto_start=self.auto_start.isChecked(),
                    hotkeys={key: field.text().strip() for key, field in self.hotkeys.items()},
                    cpu_threads=self.cpu_threads.value(), capture_fps=self.capture_fps.value(),
                    idle_fps=min(self.idle_fps.value(), self.capture_fps.value()),
                    debounce_ms=self.debounce.value(), min_ocr_interval_ms=self.ocr_interval.value(),
                    cache_enabled=self.cache.isChecked())
        return Settings.from_dict(data)
