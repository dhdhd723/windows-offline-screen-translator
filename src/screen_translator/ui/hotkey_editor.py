"""Focus-local shortcut recording; never installs a global keyboard hook."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from screen_translator.platform.windows.hotkeys import parse_hotkey


_MODIFIER_KEYS = {
    int(Qt.Key.Key_Control): Qt.KeyboardModifier.ControlModifier,
    int(Qt.Key.Key_Alt): Qt.KeyboardModifier.AltModifier,
    int(Qt.Key.Key_Shift): Qt.KeyboardModifier.ShiftModifier,
    int(Qt.Key.Key_Meta): Qt.KeyboardModifier.MetaModifier,
}
_MODIFIERS = (
    (Qt.KeyboardModifier.ControlModifier, "Ctrl"),
    (Qt.KeyboardModifier.AltModifier, "Alt"),
    (Qt.KeyboardModifier.ShiftModifier, "Shift"),
    (Qt.KeyboardModifier.MetaModifier, "Win"),
)
_MODIFIER_MASK = (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
                  | Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.MetaModifier)
_SPECIAL_KEYS = {
    int(Qt.Key.Key_Space): "Space",
    int(Qt.Key.Key_Return): "Enter",
    int(Qt.Key.Key_Enter): "Enter",
    int(Qt.Key.Key_Escape): "Esc",
    int(Qt.Key.Key_Tab): "Tab",
    int(Qt.Key.Key_Backtab): "Tab",
    int(Qt.Key.Key_Home): "Home",
    int(Qt.Key.Key_End): "End",
    int(Qt.Key.Key_PageUp): "PageUp",
    int(Qt.Key.Key_PageDown): "PageDown",
    int(Qt.Key.Key_Insert): "Insert",
    int(Qt.Key.Key_Delete): "Delete",
}


def _key_name(key: int) -> str | None:
    if int(Qt.Key.Key_A) <= key <= int(Qt.Key.Key_Z):
        return chr(key)
    if int(Qt.Key.Key_0) <= key <= int(Qt.Key.Key_9):
        return chr(key)
    if int(Qt.Key.Key_F1) <= key <= int(Qt.Key.Key_F24):
        return f"F{key - int(Qt.Key.Key_F1) + 1}"
    return _SPECIAL_KEYS.get(key)


class HotkeyEditor(QWidget):
    """Record one modifier-plus-key combination, committing on full release.

    The caller suspends its own global hotkeys when ``recording_changed(True)``
    fires. This widget receives only keys directed to its focused editor.
    ``text()`` is the committed value, even while a pending value is previewed.
    """

    recording_changed = Signal(bool)
    validation_error = Signal(str)
    key_recorded = Signal(str)

    def __init__(self, value: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._value = value.strip()
        self._recording = False
        self._pending: str | None = None
        self._held_keys: set[int] = set()
        self._held_modifiers = Qt.KeyboardModifier.NoModifier
        self._invalid_chord = False
        self._validator: Callable[[str], str | None] | None = None
        self._capture_window: QWidget | None = None

        self.field = QLineEdit(self._value, self)
        self.field.setReadOnly(True)
        self.field.setPlaceholderText("点击修改后，按下组合键")
        self.field.setAccessibleName("当前快捷键")
        self.field.setToolTip("不需要输入文字：点击修改，再按下想使用的组合键。")
        self.field.installEventFilter(self)
        self.button = QPushButton("修改", self)
        # Clicking Cancel must not first cause FocusOut and then begin again.
        self.button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.button.setAccessibleName("录入快捷键")
        self.button.clicked.connect(self._toggle_capture)
        self.hint = QLabel(self)
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: #65748b; font-size: 11px;")
        self.hint.hide()

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.field, 1)
        row.addWidget(self.button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        layout.addLayout(row)
        layout.addWidget(self.hint)
        self.setFocusProxy(self.field)

    @property
    def is_recording(self) -> bool:
        return self._recording

    def text(self) -> str:
        return self._value

    def setText(self, value: str) -> None:
        """Keep the existing settings/test interface without allowing typing."""
        self.cancel_capture()
        self._value = value.strip()
        self.field.setText(self._value)
        self.hint.hide()

    def set_validator(self, validator: Callable[[str], str | None] | None) -> None:
        self._validator = validator

    def _toggle_capture(self) -> None:
        if self._recording:
            self.cancel_capture()
        else:
            self.begin_capture()

    def begin_capture(self) -> None:
        if self._recording or not self.isEnabled():
            return
        self._recording = True
        self._pending = None
        self._held_keys.clear()
        self._held_modifiers = Qt.KeyboardModifier.NoModifier
        self._invalid_chord = False
        self.button.setText("取消录入")
        self.field.clear()
        self.field.setPlaceholderText("请按下组合键…")
        self._show_hint("请按 Ctrl / Alt / Shift / Win 加一个按键；Esc 取消。")
        self._capture_window = self.window()
        self._capture_window.installEventFilter(self)
        # Signal handlers unregister existing global bindings before focus/key input.
        self.recording_changed.emit(True)
        if self._recording:
            self.field.setFocus(Qt.FocusReason.OtherFocusReason)

    def cancel_capture(self) -> None:
        self._finish_capture(None)

    def _finish_capture(self, candidate: str | None) -> None:
        if not self._recording:
            return
        self._recording = False
        self._pending = None
        self._held_keys.clear()
        self._held_modifiers = Qt.KeyboardModifier.NoModifier
        self._invalid_chord = False
        if self._capture_window is not None:
            self._capture_window.removeEventFilter(self)
            self._capture_window = None
        if candidate is not None:
            self._value = candidate
        self.field.setText(self._value)
        self.field.setPlaceholderText("点击修改后，按下组合键")
        self.button.setText("修改")
        self.hint.hide()
        self.recording_changed.emit(False)
        if candidate is not None:
            self.key_recorded.emit(candidate)

    def _show_hint(self, message: str, *, error: bool = False) -> None:
        self.hint.setText(message)
        self.hint.setStyleSheet(f"color: {'#b33a32' if error else '#65748b'}; font-size: 11px;")
        self.hint.show()

    def _reject_chord(self, message: str) -> None:
        self._pending = None
        self._invalid_chord = True
        self.field.clear()
        self._show_hint(message, error=True)
        self.validation_error.emit(message)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if self._recording:
            if watched is self._capture_window and event.type() in (
                QEvent.Type.WindowDeactivate, QEvent.Type.Close, QEvent.Type.Hide,
            ):
                self.cancel_capture()
            elif watched is self.field:
                if event.type() == QEvent.Type.FocusOut:
                    self.cancel_capture()
                elif event.type() == QEvent.Type.ShortcutOverride:
                    # Prevent dialog default buttons, Esc, and application shortcuts.
                    event.accept()
                    return True
                elif event.type() in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
                    self._record_event(event)
                    event.accept()
                    return True
        return super().eventFilter(watched, event)

    def hideEvent(self, event) -> None:
        self.cancel_capture()
        super().hideEvent(event)

    def _record_event(self, event: QKeyEvent) -> None:
        if event.isAutoRepeat():
            return
        key = int(event.key())
        modifier = _MODIFIER_KEYS.get(key)
        pressed = event.type() == QEvent.Type.KeyPress
        if pressed:
            self._held_keys.add(key)
        else:
            self._held_keys.discard(key)
        modifiers = event.modifiers() & _MODIFIER_MASK
        if modifier is not None:
            if pressed:
                modifiers |= modifier
            else:
                modifiers &= ~modifier
        for held in self._held_keys:
            if held in _MODIFIER_KEYS:
                modifiers |= _MODIFIER_KEYS[held]
        self._held_modifiers = modifiers

        if not pressed:
            if not self._held_keys and not self._held_modifiers:
                if self._pending is not None and not self._invalid_chord:
                    self._finish_capture(self._pending)
                else:
                    # Keep the explanation, but allow another complete attempt.
                    self._invalid_chord = False
            return

        if key == int(Qt.Key.Key_Escape) and not modifiers:
            self.cancel_capture()
            return
        if modifier is not None:
            if self._pending is None and not self._invalid_chord:
                names = [name for flag, name in _MODIFIERS if modifiers & flag]
                self.field.setText("+".join(names) + "+…")
            return
        if self._invalid_chord:
            return
        ordinary_keys = self._held_keys - _MODIFIER_KEYS.keys()
        if len(ordinary_keys) > 1 or self._pending is not None:
            self._reject_chord("一次只能录入一个普通按键；请松开按键后重试。")
            return
        # Qt gives keypad digits the same key code as the number row, but
        # RegisterHotKey distinguishes VK_NUMPAD0 from VK_0. The current
        # settings parser only represents the latter, so never save a value
        # that would silently bind a different physical key.
        if (event.modifiers() & Qt.KeyboardModifier.KeypadModifier
                and int(Qt.Key.Key_0) <= key <= int(Qt.Key.Key_9)):
            self._reject_chord("暂不支持小键盘数字快捷键；请使用键盘上方的数字键。")
            return
        if event.modifiers() & Qt.KeyboardModifier.GroupSwitchModifier:
            self._reject_chord("暂不支持 AltGr 组合；请使用 Ctrl / Alt / Shift / Win。")
            return
        name = _key_name(key)
        if name is None:
            self._reject_chord("暂不支持这个按键；请使用字母、数字、F1–F24 或常用控制键。")
            return
        if not modifiers:
            self._reject_chord("需要 Ctrl / Alt / Shift / Win 加一个按键；请松开后重试。")
            return
        candidate = "+".join([*(name for flag, name in _MODIFIERS if modifiers & flag), name])
        try:
            parse_hotkey(candidate)
            error = self._validator(candidate) if self._validator is not None else None
        except ValueError as exc:
            error = str(exc)
        if error:
            self._reject_chord(error)
            return
        self._pending = candidate
        self.field.setText(candidate)
        self._show_hint(f"已识别 {candidate}；松开全部按键后完成录入，保存后生效。")
