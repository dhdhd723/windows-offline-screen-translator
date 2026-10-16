"""Shortcut recorder tests exercise Qt events, not the user's native keyboard."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QPushButton, QVBoxLayout

from screen_translator.platform.windows.hotkeys import parse_hotkey
from screen_translator.ui.hotkey_editor import HotkeyEditor


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    yield app


@pytest.fixture
def recorder(qapp):
    dialog = QDialog()
    layout = QVBoxLayout(dialog)
    value = HotkeyEditor("Alt+R", dialog)
    layout.addWidget(value)
    other = QLineEdit(dialog)
    layout.addWidget(other)
    dialog.show()
    dialog.activateWindow()
    qapp.processEvents()
    value.other = other
    value.dialog = dialog
    yield value
    dialog.close()
    qapp.processEvents()


def send(recorder, kind, key, modifiers=Qt.KeyboardModifier.NoModifier, *, repeat=False):
    event = QKeyEvent(kind, key, modifiers, "", repeat)
    QApplication.sendEvent(recorder.field, event)
    return event


def press(recorder, key, modifiers=Qt.KeyboardModifier.NoModifier, *, repeat=False):
    return send(recorder, QEvent.Type.KeyPress, key, modifiers, repeat=repeat)


def release(recorder, key, modifiers=Qt.KeyboardModifier.NoModifier, *, repeat=False):
    return send(recorder, QEvent.Type.KeyRelease, key, modifiers, repeat=repeat)


def test_keyboard_typing_cannot_edit_shortcut_before_recording(recorder):
    recorder.field.setFocus()
    QTest.keyClicks(recorder.field, "alt+c")
    assert recorder.field.isReadOnly()
    assert recorder.text() == recorder.field.text() == "Alt+R"
    assert not recorder.is_recording


def test_click_modify_then_physical_qt_chord_records_canonical_value(recorder):
    states, values = [], []
    recorder.recording_changed.connect(states.append)
    recorder.key_recorded.connect(values.append)
    QTest.mouseClick(recorder.button, Qt.MouseButton.LeftButton)
    assert recorder.is_recording and recorder.field.hasFocus()
    assert recorder.button.text() == "取消录入" and states == [True]
    QTest.keyClick(recorder.field, Qt.Key.Key_T, Qt.KeyboardModifier.ControlModifier
                   | Qt.KeyboardModifier.ShiftModifier)
    assert recorder.text() == "Ctrl+Shift+T"
    assert recorder.field.text() == "Ctrl+Shift+T"
    assert values == ["Ctrl+Shift+T"] and states == [True, False]
    assert recorder.button.text() == "修改" and not recorder.is_recording


def test_old_binding_stays_committed_until_all_keys_are_released(recorder):
    states = []
    recorder.recording_changed.connect(states.append)
    recorder.begin_capture()
    press(recorder, Qt.Key.Key_Control)
    press(recorder, Qt.Key.Key_Alt, Qt.KeyboardModifier.ControlModifier)
    press(recorder, Qt.Key.Key_L, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
    assert recorder.text() == "Alt+R" and recorder.field.text() == "Ctrl+Alt+L"
    release(recorder, Qt.Key.Key_L, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
    assert recorder.is_recording and states == [True]
    release(recorder, Qt.Key.Key_Control, Qt.KeyboardModifier.AltModifier)
    assert recorder.is_recording
    release(recorder, Qt.Key.Key_Alt)
    assert recorder.text() == "Ctrl+Alt+L" and states == [True, False]


def test_key_release_flags_that_include_released_modifier_do_not_stall(recorder):
    recorder.begin_capture()
    press(recorder, Qt.Key.Key_Alt, Qt.KeyboardModifier.AltModifier)
    press(recorder, Qt.Key.Key_F12, Qt.KeyboardModifier.AltModifier)
    release(recorder, Qt.Key.Key_F12, Qt.KeyboardModifier.AltModifier)
    release(recorder, Qt.Key.Key_Alt, Qt.KeyboardModifier.AltModifier)
    assert recorder.text() == "Alt+F12" and not recorder.is_recording


def test_modifier_only_does_not_commit_or_finish(recorder):
    values = []
    recorder.key_recorded.connect(values.append)
    recorder.begin_capture()
    press(recorder, Qt.Key.Key_Control)
    assert "Ctrl" in recorder.field.text()
    release(recorder, Qt.Key.Key_Control)
    assert recorder.is_recording and recorder.text() == "Alt+R" and values == []


def test_autorepeat_press_and_release_do_not_commit_held_chord(recorder):
    recorder.begin_capture()
    press(recorder, Qt.Key.Key_Control)
    press(recorder, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier)
    press(recorder, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier, repeat=True)
    release(recorder, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier, repeat=True)
    assert recorder.is_recording and recorder.text() == "Alt+R"
    release(recorder, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier)
    release(recorder, Qt.Key.Key_Control)
    assert recorder.text() == "Ctrl+K" and not recorder.is_recording


@pytest.mark.parametrize("release_order", ["ordinary-first", "modifier-first"])
def test_multiple_ordinary_keys_reject_entire_attempt_then_allow_retry(recorder, release_order):
    errors = []
    recorder.validation_error.connect(errors.append)
    recorder.begin_capture()
    press(recorder, Qt.Key.Key_Control)
    press(recorder, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    press(recorder, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier)
    assert errors and "一个普通按键" in errors[-1]
    if release_order == "ordinary-first":
        release(recorder, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        release(recorder, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier)
        release(recorder, Qt.Key.Key_Control)
    else:
        release(recorder, Qt.Key.Key_Control)
        release(recorder, Qt.Key.Key_B)
        release(recorder, Qt.Key.Key_A)
    assert recorder.is_recording and recorder.text() == "Alt+R"
    QTest.keyClick(recorder.field, Qt.Key.Key_C, Qt.KeyboardModifier.AltModifier)
    assert recorder.text() == "Alt+C" and not recorder.is_recording


def test_bare_key_rejected_without_changing_saved_value(recorder):
    recorder.begin_capture()
    QTest.keyClick(recorder.field, Qt.Key.Key_A)
    assert recorder.is_recording and recorder.text() == "Alt+R"
    assert "需要" in recorder.hint.text()
    QTest.keyClick(recorder.field, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    assert recorder.text() == "Ctrl+A"


@pytest.mark.parametrize("key", [Qt.Key.Key_Backspace, Qt.Key.Key_Comma, Qt.Key.Key_Left,
                                  Qt.Key.Key_CapsLock, Qt.Key.Key_MediaPlay])
def test_unsupported_keys_show_error_and_allow_retry(recorder, key):
    recorder.begin_capture()
    QTest.keyClick(recorder.field, key, Qt.KeyboardModifier.AltModifier)
    assert recorder.is_recording and recorder.text() == "Alt+R"
    assert "暂不支持" in recorder.hint.text()
    QTest.keyClick(recorder.field, Qt.Key.Key_Home, Qt.KeyboardModifier.AltModifier)
    assert recorder.text() == "Alt+Home" and not recorder.is_recording


@pytest.mark.parametrize(("key", "name"), [
    (Qt.Key.Key_A, "A"), (Qt.Key.Key_Z, "Z"), (Qt.Key.Key_0, "0"), (Qt.Key.Key_9, "9"),
    (Qt.Key.Key_F1, "F1"), (Qt.Key.Key_F24, "F24"), (Qt.Key.Key_Space, "Space"),
    (Qt.Key.Key_Return, "Enter"), (Qt.Key.Key_Enter, "Enter"), (Qt.Key.Key_Escape, "Esc"),
    (Qt.Key.Key_Tab, "Tab"), (Qt.Key.Key_Backtab, "Tab"), (Qt.Key.Key_Home, "Home"),
    (Qt.Key.Key_End, "End"), (Qt.Key.Key_PageUp, "PageUp"),
    (Qt.Key.Key_PageDown, "PageDown"), (Qt.Key.Key_Insert, "Insert"),
    (Qt.Key.Key_Delete, "Delete"),
])
def test_each_supported_key_uses_the_existing_windows_parser(recorder, key, name):
    recorder.begin_capture()
    press(recorder, Qt.Key.Key_Control)
    press(recorder, key, Qt.KeyboardModifier.ControlModifier)
    release(recorder, key, Qt.KeyboardModifier.ControlModifier)
    release(recorder, Qt.Key.Key_Control)
    assert recorder.text() == f"Ctrl+{name}"
    parse_hotkey(recorder.text())


def test_modifier_order_is_canonical_regardless_of_press_order(recorder):
    recorder.begin_capture()
    press(recorder, Qt.Key.Key_Meta)
    press(recorder, Qt.Key.Key_Shift, Qt.KeyboardModifier.MetaModifier)
    press(recorder, Qt.Key.Key_Alt, Qt.KeyboardModifier.MetaModifier | Qt.KeyboardModifier.ShiftModifier)
    press(recorder, Qt.Key.Key_Control, Qt.KeyboardModifier.MetaModifier
          | Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.AltModifier)
    all_modifiers = Qt.KeyboardModifier.MetaModifier | Qt.KeyboardModifier.ShiftModifier \
        | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ControlModifier
    press(recorder, Qt.Key.Key_7, all_modifiers)
    release(recorder, Qt.Key.Key_7, all_modifiers)
    release(recorder, Qt.Key.Key_Meta, all_modifiers & ~Qt.KeyboardModifier.MetaModifier)
    release(recorder, Qt.Key.Key_Alt, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    release(recorder, Qt.Key.Key_Shift, Qt.KeyboardModifier.ControlModifier)
    release(recorder, Qt.Key.Key_Control)
    assert recorder.text() == "Ctrl+Alt+Shift+Win+7"


def test_duplicate_validator_rejects_pending_value_before_commit(recorder):
    recorder.set_validator(lambda value: "与启停快捷键重复" if value == "Alt+T" else None)
    recorder.begin_capture()
    QTest.keyClick(recorder.field, Qt.Key.Key_T, Qt.KeyboardModifier.AltModifier)
    assert recorder.is_recording and recorder.text() == "Alt+R"
    assert "重复" in recorder.hint.text()
    QTest.keyClick(recorder.field, Qt.Key.Key_L, Qt.KeyboardModifier.AltModifier)
    assert recorder.text() == "Alt+L" and not recorder.is_recording


def test_validator_valueerror_is_displayed_as_retryable_error(recorder):
    def validate(value):
        raise ValueError("这个快捷键不合适")
    recorder.set_validator(validate)
    recorder.begin_capture()
    QTest.keyClick(recorder.field, Qt.Key.Key_Q, Qt.KeyboardModifier.AltModifier)
    assert recorder.text() == "Alt+R" and recorder.is_recording
    assert recorder.hint.text() == "这个快捷键不合适"


def test_esc_cancels_without_rejecting_dialog_or_committing_pending(recorder):
    states, rejected = [], []
    recorder.recording_changed.connect(states.append)
    recorder.dialog.rejected.connect(lambda: rejected.append(True))
    recorder.begin_capture()
    QTest.keyClick(recorder.field, Qt.Key.Key_Escape)
    assert recorder.dialog.isVisible() and rejected == []
    assert recorder.text() == recorder.field.text() == "Alt+R"
    assert not recorder.is_recording and states == [True, False]


def test_cancel_button_cancels_once_without_restarting_capture(recorder):
    states = []
    recorder.recording_changed.connect(states.append)
    QTest.mouseClick(recorder.button, Qt.MouseButton.LeftButton)
    assert recorder.is_recording
    QTest.mouseClick(recorder.button, Qt.MouseButton.LeftButton)
    assert not recorder.is_recording and recorder.text() == "Alt+R"
    assert states == [True, False]


@pytest.mark.parametrize("method", ["focus", "hide", "window-deactivate", "close"])
def test_losing_capture_scope_restores_old_binding_and_emits_cleanup(recorder, qapp, method):
    states = []
    recorder.recording_changed.connect(states.append)
    recorder.begin_capture()
    press(recorder, Qt.Key.Key_Alt)
    press(recorder, Qt.Key.Key_L, Qt.KeyboardModifier.AltModifier)
    if method == "focus":
        recorder.other.setFocus()
    elif method == "hide":
        recorder.hide()
    elif method == "window-deactivate":
        QApplication.sendEvent(recorder.dialog, QEvent(QEvent.Type.WindowDeactivate))
    else:
        recorder.dialog.close()
    qapp.processEvents()
    assert not recorder.is_recording and recorder.text() == "Alt+R"
    assert states == [True, False]


def test_enter_and_tab_do_not_activate_dialog_default_button_or_move_focus(recorder):
    clicked = []
    default_button = QPushButton("保存", recorder.dialog)
    default_button.setDefault(True)
    default_button.clicked.connect(lambda: clicked.append(True))
    recorder.dialog.layout().addWidget(default_button)
    recorder.begin_capture()
    QTest.keyClick(recorder.field, Qt.Key.Key_Tab)
    assert recorder.is_recording and recorder.field.hasFocus()
    assert recorder.text() == "Alt+R"
    QTest.keyClick(recorder.field, Qt.Key.Key_Return)
    assert recorder.is_recording and clicked == []
    QTest.keyClick(recorder.field, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
    assert recorder.text() == "Ctrl+Enter" and clicked == []


def test_shortcut_override_is_accepted_only_during_capture(recorder):
    recorder.begin_capture()
    event = send(recorder, QEvent.Type.ShortcutOverride, Qt.Key.Key_T, Qt.KeyboardModifier.AltModifier)
    assert event.isAccepted() and recorder.text() == "Alt+R"


def test_legacy_set_text_cancels_pending_capture_and_updates_committed_value(recorder):
    states = []
    recorder.recording_changed.connect(states.append)
    recorder.begin_capture()
    press(recorder, Qt.Key.Key_Alt)
    press(recorder, Qt.Key.Key_L, Qt.KeyboardModifier.AltModifier)
    recorder.setText(" Ctrl+Shift+C ")
    assert recorder.text() == recorder.field.text() == "Ctrl+Shift+C"
    assert not recorder.is_recording and states == [True, False]


def test_begin_cancel_are_idempotent_and_disabled_editor_cannot_record(recorder):
    states = []
    recorder.recording_changed.connect(states.append)
    recorder.cancel_capture()
    recorder.setEnabled(False)
    recorder.begin_capture()
    assert not recorder.is_recording and states == []
    recorder.setEnabled(True)
    recorder.begin_capture()
    recorder.begin_capture()
    recorder.cancel_capture()
    recorder.cancel_capture()
    assert states == [True, False]


def test_keypad_digit_is_not_silently_recorded_as_number_row(recorder):
    recorder.begin_capture()
    press(recorder, Qt.Key.Key_Control)
    press(recorder, Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.KeypadModifier)
    release(recorder, Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.KeypadModifier)
    release(recorder, Qt.Key.Key_Control)
    assert recorder.text() == "Alt+R" and recorder.is_recording
    assert "小键盘" in recorder.hint.text()
    QTest.keyClick(recorder.field, Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier)
    assert recorder.text() == "Ctrl+1"


def test_altgr_does_not_silently_record_as_another_modifier(recorder):
    recorder.begin_capture()
    press(recorder, Qt.Key.Key_Q, Qt.KeyboardModifier.GroupSwitchModifier
          | Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
    release(recorder, Qt.Key.Key_Q)
    assert recorder.text() == "Alt+R" and recorder.is_recording
    assert "AltGr" in recorder.hint.text()


def test_numpad_enter_is_supported_because_it_uses_the_same_windows_vk(recorder):
    recorder.begin_capture()
    press(recorder, Qt.Key.Key_Control)
    press(recorder, Qt.Key.Key_Enter, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.KeypadModifier)
    release(recorder, Qt.Key.Key_Enter, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.KeypadModifier)
    release(recorder, Qt.Key.Key_Control)
    assert recorder.text() == "Ctrl+Enter"


def test_true_signal_is_sent_before_field_focus_and_can_cancel_reentrantly(recorder):
    states = []
    def on_recording(recording):
        states.append(recording)
        if recording:
            assert recorder.is_recording
            recorder.cancel_capture()
    recorder.recording_changed.connect(on_recording)
    recorder.begin_capture()
    assert states == [True, False] and not recorder.is_recording
    assert recorder.text() == recorder.field.text() == "Alt+R"
