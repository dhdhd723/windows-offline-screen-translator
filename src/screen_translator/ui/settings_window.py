from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFormLayout, QLabel,
                               QMessageBox, QPlainTextEdit, QSlider, QSpinBox, QTabWidget,
                               QPushButton, QVBoxLayout, QWidget)

from screen_translator.contracts import Settings
from screen_translator.core.chat_slang import BUILTIN_CHAT_SLANG, sanitize_overrides
from screen_translator.core.chat_translation import BUILTIN_CHAT_ZH
from screen_translator.platform.windows.hotkeys import parse_hotkey
from screen_translator.ui.hotkey_editor import HotkeyEditor


EDITABLE_SETTING_FIELDS = frozenset({
    "direction", "text_layout", "font_size", "opacity", "show_source", "esc_enabled", "auto_start",
    "cpu_threads", "capture_fps", "idle_fps", "debounce_ms", "min_ocr_interval_ms",
    "cache_enabled", "hotkeys", "recording_compatibility",
    "chat_slang_enabled", "chat_slang_overrides", "startup_animation",
})


def parse_chat_slang_overrides(text: str) -> dict[str, str]:
    """Strict editor validation; persisted settings use tolerant sanitization."""
    if any((ord(char) < 32 and char not in "\r\n") or ord(char) == 127 for char in text):
        raise ValueError("聊天词表不允许制表符或控制字符")
    entries: dict[str, str] = {}
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        if "=" not in line:
            raise ValueError(f"第 {line_number} 行格式有误，请使用 abbreviation = expansion")
        token, expansion = line.split("=", 1)
        clean = sanitize_overrides({token: expansion})
        if len(clean) != 1:
            raise ValueError(f"第 {line_number} 行无效：缩写须为 1–24 位英文字母或数字且以字母开头；"
                             "展开内容须为 1–160 个字符的单行英文")
        key, value = next(iter(clean.items()))
        if key in entries:
            raise ValueError(f"第 {line_number} 行缩写重复（大小写不区分）")
        if len(entries) >= 100:
            raise ValueError("自定义聊天词表最多允许 100 条")
        entries[key] = value
    return entries


def merge_settings_changes(current: Settings, changes: Mapping[str, object]) -> Settings:
    """Apply dialog edits to the latest state, never to an obsolete whole snapshot.

    Region selection, overlay placement and runtime consent are application state,
    not editable dialog fields. Unedited hotkeys keep any effective OS fallback.
    """
    if not isinstance(changes, Mapping) or set(changes) - EDITABLE_SETTING_FIELDS:
        raise ValueError("设置更新包含不可编辑的字段")
    data = current.to_dict()
    for key, value in changes.items():
        if key == "hotkeys":
            if not isinstance(value, Mapping) or set(value) - set(current.hotkeys):
                raise ValueError("快捷键更新格式无效")
            data[key] = {**current.hotkeys, **value}
        else:
            data[key] = value
    # Clamp the idle rate after merging: another editor may have changed capture_fps.
    data["idle_fps"] = min(float(data["idle_fps"]), float(data["capture_fps"]))
    return Settings.from_dict(data)


class SettingsDialog(QDialog):
    manage_presets_requested = Signal()
    hotkey_recording_changed = Signal(bool)

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
                           ("中文 → 英文", "zh-en"), ("英文 → 中文", "en-zh"),
                           ("日语 → 简体中文（需日语模型包）", "ja-zh")):
            self.direction.addItem(text, data)
        self.direction.setCurrentIndex(max(0, self.direction.findData(settings.direction)))
        display_form.addRow("翻译方向", self.direction)
        japanese_hint = QLabel("日语请手动选择；自动模式仍只处理中英。\n"
                               "日语增强包首次翻译需加载模型，优先框选横排清晰文字。")
        japanese_hint.setWordWrap(True)
        japanese_hint.setStyleSheet("color: #64748b; font-size: 12px;")
        display_form.addRow(japanese_hint)
        self.text_layout = QComboBox()
        for text, data in (("连续文本（段落／长句）", "continuous"),
                           ("逐行对话（聊天／Roblox）", "lines")):
            self.text_layout.addItem(text, data)
        self.text_layout.setCurrentIndex(max(0, self.text_layout.findData(settings.text_layout)))
        display_form.addRow("文字排版", self.text_layout)
        layout_hint = QLabel("两条独立对话请选择逐行对话，译文保留上下行顺序。\n"
                             "同一句话因宽度不足自动折行时，请选连续文本以保留上下文。")
        layout_hint.setWordWrap(True)
        layout_hint.setStyleSheet("color: #64748b; font-size: 12px;")
        display_form.addRow(layout_hint)
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
        self.recording_compatibility = QCheckBox("兼容截图和录屏（字幕可以入镜）")
        self.recording_compatibility.setChecked(settings.recording_compatibility)
        display_form.addRow("截图与录屏", self.recording_compatibility)
        recording_hint = QLabel("开启后不会要求系统将字幕从截图和录屏中排除。\n字幕仍会避开 OCR 选区，避免识别到自己的译文。")
        recording_hint.setWordWrap(True)
        recording_hint.setStyleSheet("color: #64748b; font-size: 12px;")
        display_form.addRow(recording_hint)
        hint = QLabel("字幕窗始终置顶、鼠标穿透，不会抢走当前程序焦点。\n框选成功后，字幕默认显示在区域外侧。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #64748b; font-size: 12px;")
        display_form.addRow(hint)
        tabs.addTab(display, "显示与翻译")

        chat = QWidget()
        chat_layout = QVBoxLayout(chat)
        chat_layout.setSpacing(12)
        self.chat_slang_enabled = QCheckBox("启用聊天缩写词表")
        self.chat_slang_enabled.setChecked(self._original.chat_slang_enabled)
        chat_layout.addWidget(self.chat_slang_enabled)
        chat_hint = QLabel("翻译方向为英文 → 中文时生效，开关默认启用。\n"
                           "两种文字排版均生效；独立的内置缩写直接显示中文，长句先展开再翻译。\n"
                           "明确的昵称冒号前缀原样保留；未知词交给模型，词义仍可能不准确。\n"
                           "rn、fr、bc、def 按聊天含义处理；MDFK、ASF 含粗俗语气，多义场景可关闭此功能。")
        chat_hint.setWordWrap(True)
        chat_hint.setStyleSheet("color: #64748b; font-size: 12px;")
        chat_layout.addWidget(chat_hint)
        examples = [key for key in ("ty", "np", "brb", "idk") if key in BUILTIN_CHAT_SLANG]
        self.chat_slang_builtin_hint = QLabel(
            f"已内置 {len(BUILTIN_CHAT_SLANG)} 条缩写，无需手动添加。"
            + (f"例如：{'、'.join(examples)}。" if examples else ""))
        self.chat_slang_builtin_hint.setWordWrap(True)
        chat_layout.addWidget(self.chat_slang_builtin_hint)
        glossary_tabs = QTabWidget()
        chat_layout.addWidget(glossary_tabs)
        builtin_page = QWidget()
        builtin_layout = QVBoxLayout(builtin_page)
        builtin_layout.addWidget(QLabel("内置词表随程序提供，以下内容可浏览和复制，不能直接修改。"))
        self.chat_slang_builtin_list = QPlainTextEdit()
        self.chat_slang_builtin_list.setReadOnly(True)
        self.chat_slang_builtin_list.setMinimumHeight(160)
        self.chat_slang_builtin_list.setPlainText("\n".join(
            f"{key} = {value} | 独立消息：{BUILTIN_CHAT_ZH.get(key, '交给模型')}"
            for key, value in sorted(BUILTIN_CHAT_SLANG.items())))
        builtin_layout.addWidget(self.chat_slang_builtin_list)
        numeric_hint = QLabel("数字 2 仅在 want 2 play、talk 2 you 等明确短语中按 to 处理；\n"
                              "单独的 2 和数量不替换。TYTL 按用户确认兼容为“回头聊”。")
        numeric_hint.setWordWrap(True)
        builtin_layout.addWidget(numeric_hint)
        glossary_tabs.addTab(builtin_page, "内置词表")
        custom_page = QWidget()
        custom_layout = QVBoxLayout(custom_page)
        custom_layout.addWidget(QLabel("自定义词表（可选）：每行 abbreviation = expansion，最多 100 条"))
        self.chat_slang_overrides = QPlainTextEdit()
        self.chat_slang_overrides.setMinimumHeight(160)
        self.chat_slang_overrides.setPlaceholderText("tys = thanks\nnp = no problem")
        self.chat_slang_overrides.setPlainText("\n".join(
            f"{key} = {value}" for key, value in sorted(self._original.chat_slang_overrides.items())))
        custom_layout.addWidget(self.chat_slang_overrides)
        format_hint = QLabel("缩写须以英文字母开头，仅含英文字母或数字，最长 24 位，不区分大小写。\n"
                             "右侧填写非空单行英文（最长 160 字符）。留空仍使用内置项。\n"
                             "自定义项可覆盖内置；移除自定义项会恢复内置含义，不能用空值删除内置。")
        format_hint.setWordWrap(True)
        format_hint.setStyleSheet("color: #64748b; font-size: 12px;")
        custom_layout.addWidget(format_hint)
        glossary_tabs.addTab(custom_page, "自定义（可选）")
        tabs.addTab(chat, "聊天词表")

        controls = QWidget()
        controls_form = QFormLayout(controls)
        controls_form.setVerticalSpacing(14)
        self.hotkeys: dict[str, HotkeyEditor] = {}
        for key, label in (("select", "框选区域"), ("toggle", "开启 / 恢复 / 停止"), ("clear", "清空并停止")):
            field = HotkeyEditor(settings.hotkeys.get(key, ""))
            field.set_validator(lambda value, action=key: self._validate_recorded_hotkey(action, value))
            field.recording_changed.connect(lambda active, editor=field: self._hotkey_recording(editor, active))
            field.validation_error.connect(self._hotkey_validation_error)
            field.key_recorded.connect(lambda value: self.hotkey_hint.setText(
                f"已录入 {value}；点击保存后生效。"))
            controls_form.addRow(label, field)
            self.hotkeys[key] = field
        self.hotkey_hint = QLabel("点击“修改”，按住 Ctrl / Alt / Shift / Win，再按一个键，松开后完成。\n"
                                 "无需输入文字；录入时按 Esc 或点击取消可保留原键。保存后才生效。")
        self.hotkey_hint.setWordWrap(True)
        self.hotkey_hint.setStyleSheet("color: #64748b; font-size: 12px;")
        controls_form.addRow(self.hotkey_hint)
        action_hint = QLabel("清空并停止会保留翻译选区；按“开启 / 恢复 / 停止”的快捷键即可恢复。")
        action_hint.setWordWrap(True)
        action_hint.setStyleSheet("color: #64748b; font-size: 12px;")
        controls_form.addRow(action_hint)
        self.esc = QCheckBox("监控期间按 Esc 隐藏 / 恢复字幕")
        self.esc.setChecked(settings.esc_enabled)
        controls_form.addRow(self.esc)
        self.auto_start = QCheckBox("登录 Windows 后自动启动到托盘")
        self.auto_start.setChecked(settings.auto_start)
        controls_form.addRow(self.auto_start)
        self.startup_animation = QCheckBox("手动启动时显示 2 秒启动动画，结束后打开设置")
        self.startup_animation.setChecked(self._original.startup_animation)
        controls_form.addRow(self.startup_animation)
        startup_hint = QLabel("动画约 2 秒，不抢焦点；正常结束后打开可编辑的设置窗口。\n"
                              "登录 Windows 自动启动、诊断运行时不显示。")
        startup_hint.setWordWrap(True)
        startup_hint.setStyleSheet("color: #64748b; font-size: 12px;")
        controls_form.addRow(startup_hint)
        hint = QLabel("录入期间暂停本程序的全局快捷键，避免误触发框选或翻译。\n"
                      "Esc 会继续传递给当前程序。关闭此选项后仍可用托盘菜单隐藏字幕。\n"
                      "系统保留组合键或被其他程序占用的快捷键可能不可用，保存后会显示提示。")
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

        presets = QWidget()
        preset_layout = QVBoxLayout(presets)
        preset_hint = QLabel("可将游戏、聊天、阅读等场景的设置保存为独立预设，之后快速恢复。\n"
                             "请先保存本窗口的修改，再打开管理器；也可从托盘“场景预设…”进入。\n"
                             "应用预设会清空字幕并暂停翻译，选区可选保存。预设仅存于本机。")
        preset_hint.setWordWrap(True)
        preset_layout.addWidget(preset_hint)
        self.manage_presets_button = QPushButton("管理场景预设…")
        self.manage_presets_button.clicked.connect(self.manage_presets_requested.emit)
        preset_layout.addWidget(self.manage_presets_button)
        preset_layout.addStretch()
        tabs.addTab(presets, "场景预设")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        self.save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _validate_recorded_hotkey(self, action: str, value: str) -> str | None:
        try:
            candidate = parse_hotkey(value)
            for other, field in self.hotkeys.items():
                if other != action and parse_hotkey(field.text()) == candidate:
                    return "与另一个快捷键重复，请换一个组合键。"
        except ValueError as exc:
            return str(exc)
        return None

    def _hotkey_validation_error(self, message: str) -> None:
        self.hotkey_hint.setText(message)

    def _hotkey_recording(self, editor: HotkeyEditor, active: bool) -> None:
        if active:
            # Direct signals make suspension synchronous, before key events can
            # arrive. Switching fields cancels only the unfinished recording.
            for other in self.hotkeys.values():
                if other is not editor:
                    other.cancel_capture()
            self.hotkey_hint.setText("请按组合键，全部松开后完成。Esc 取消；原快捷键暂时不会触发。")
        recording = any(field.is_recording for field in self.hotkeys.values())
        self.save_button.setEnabled(not recording)
        self.hotkey_recording_changed.emit(recording)

    def _cancel_hotkey_recording(self) -> None:
        for field in self.hotkeys.values():
            field.cancel_capture()

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.WindowDeactivate and hasattr(self, "hotkeys"):
            self._cancel_hotkey_recording()
        return super().event(event)

    def done(self, result: int) -> None:
        self._cancel_hotkey_recording()
        super().done(result)

    def _save(self) -> None:
        if any(field.is_recording for field in self.hotkeys.values()):
            return
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
        try:
            parse_chat_slang_overrides(self.chat_slang_overrides.toPlainText())
        except ValueError as exc:
            QMessageBox.warning(self, "聊天词表格式有误", str(exc))
            return
        self.accept()

    def values(self) -> Settings:
        data = self._original.to_dict()
        data.update(direction=self.direction.currentData(),
                    text_layout=self.text_layout.currentData(),
                    chat_slang_enabled=self.chat_slang_enabled.isChecked(),
                    chat_slang_overrides=parse_chat_slang_overrides(self.chat_slang_overrides.toPlainText()),
                    font_size=self.font_size.value(), opacity=self.opacity.value() / 100,
                    show_source=self.show_source.isChecked(), esc_enabled=self.esc.isChecked(),
                    recording_compatibility=self.recording_compatibility.isChecked(),
                    auto_start=self.auto_start.isChecked(),
                    startup_animation=self.startup_animation.isChecked(),
                    hotkeys={key: field.text().strip() for key, field in self.hotkeys.items()},
                    cpu_threads=self.cpu_threads.value(), capture_fps=self.capture_fps.value(),
                    idle_fps=min(self.idle_fps.value(), self.capture_fps.value()),
                    debounce_ms=self.debounce.value(), min_ocr_interval_ms=self.ocr_interval.value(),
                    cache_enabled=self.cache.isChecked())
        return Settings.from_dict(data)

    def editable_changes(self) -> dict[str, object]:
        """Return only fields the user actually changed while this dialog was open."""
        original = self._original.to_dict()
        edited = self.values().to_dict()
        # values() also bounds idle_fps for its legacy whole-settings return.
        # Do not mistake that derived clamp for a user edit; merge clamps later.
        edited["idle_fps"] = self.idle_fps.value()
        changes = {key: edited[key] for key in EDITABLE_SETTING_FIELDS - {"hotkeys"}
                   if edited[key] != original[key]}
        hotkeys = {key: value for key, value in edited["hotkeys"].items()
                   if value != original["hotkeys"].get(key)}
        if hotkeys:
            changes["hotkeys"] = hotkeys
        return changes
