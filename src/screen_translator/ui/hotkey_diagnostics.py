"""Record shortcuts using events sent only to diagnostic-owned Qt widgets.

No system key injection, keyboard hook, global registration or user settings.
Kept in the shipped executable so the frozen UI can be checked without QtTest.
"""
from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QFocusEvent, QKeyEvent
from PySide6.QtWidgets import QApplication, QDialog, QTabWidget

from screen_translator.contracts import Settings
from screen_translator.ui.settings_window import SettingsDialog


def _key(field, kind, key, modifiers=Qt.KeyboardModifier.NoModifier) -> None:
    event = QKeyEvent(kind, key, modifiers)
    if kind == QEvent.Type.KeyPress:
        QCoreApplication.sendEvent(field, QKeyEvent(QEvent.Type.ShortcutOverride, key, modifiers))
    QCoreApplication.sendEvent(field, event)


def _combo(field, key, modifiers=Qt.KeyboardModifier.ControlModifier
           | Qt.KeyboardModifier.ShiftModifier) -> None:
    _key(field, QEvent.Type.KeyPress, key, modifiers)
    _key(field, QEvent.Type.KeyRelease, key, modifiers)
    for modifier, code in ((Qt.KeyboardModifier.ControlModifier, Qt.Key.Key_Control),
                           (Qt.KeyboardModifier.AltModifier, Qt.Key.Key_Alt),
                           (Qt.KeyboardModifier.ShiftModifier, Qt.Key.Key_Shift),
                           (Qt.KeyboardModifier.MetaModifier, Qt.Key.Key_Meta)):
        if modifiers & modifier:
            modifiers &= ~modifier
            _key(field, QEvent.Type.KeyRelease, code, modifiers)


def run_hotkey_recording_self_test() -> dict:
    app = QApplication.instance()
    if app is None:
        raise RuntimeError("A diagnostic QApplication is required")
    cases = []

    def check(name, callback):
        dialog = SettingsDialog(Settings())
        dialog.findChild(QTabWidget).setCurrentIndex(2)
        transitions = []
        dialog.hotkey_recording_changed.connect(transitions.append)
        try:
            dialog.show()
            app.processEvents()
            result = bool(callback(dialog, transitions))
            cases.append({"name": name, "passed": result})
        finally:
            dialog.close()
            dialog.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def record(dialog, transitions):
        editor = dialog.hotkeys["select"]
        before = editor.text()
        editor.button.click()
        if not editor.is_recording or dialog.save_button.isEnabled():
            return False
        _key(editor.field, QEvent.Type.KeyPress, Qt.Key.Key_K,
             Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        held = editor.text() == before and editor.is_recording
        _key(editor.field, QEvent.Type.KeyRelease, Qt.Key.Key_K,
             Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        _key(editor.field, QEvent.Type.KeyRelease, Qt.Key.Key_Shift,
             Qt.KeyboardModifier.ControlModifier)
        _key(editor.field, QEvent.Type.KeyRelease, Qt.Key.Key_Control)
        recorded = editor.text() == "Ctrl+Shift+K" and not editor.is_recording
        staged = dialog.editable_changes() == {"hotkeys": {"select": "Ctrl+Shift+K"}}
        unchanged_original = dialog._original.hotkeys["select"] == before
        dialog._save()
        return (held and recorded and staged and unchanged_original
                and dialog.result() == QDialog.DialogCode.Accepted
                and True in transitions and transitions[-1] is False)

    def invalid_and_cancel(dialog, transitions):
        editor = dialog.hotkeys["select"]
        before = editor.text()
        editor.button.click()
        _combo(editor.field, Qt.Key.Key_K, Qt.KeyboardModifier.NoModifier)
        invalid_rejected = editor.text() == before and editor.is_recording
        _key(editor.field, QEvent.Type.KeyPress, Qt.Key.Key_Control,
             Qt.KeyboardModifier.ControlModifier)
        _key(editor.field, QEvent.Type.KeyRelease, Qt.Key.Key_Control)
        modifiers_rejected = editor.text() == before and editor.is_recording
        _key(editor.field, QEvent.Type.KeyPress, Qt.Key.Key_Escape)
        return (invalid_rejected and modifiers_rejected and not editor.is_recording
                and dialog.isVisible() and editor.text() == before
                and dialog.editable_changes() == {} and transitions[-1] is False)

    def duplicate(dialog, transitions):
        editor = dialog.hotkeys["select"]
        before = editor.text()
        editor.button.click()
        _combo(editor.field, Qt.Key.Key_T, Qt.KeyboardModifier.AltModifier)
        rejected = editor.text() == before and editor.is_recording
        message = "重复" in dialog.hotkey_hint.text()
        editor.cancel_capture()
        return rejected and message and dialog.editable_changes() == {} and transitions[-1] is False

    def focus_cancel(dialog, transitions):
        editor = dialog.hotkeys["select"]
        before = editor.text()
        editor.button.click()
        _key(editor.field, QEvent.Type.KeyPress, Qt.Key.Key_K,
             Qt.KeyboardModifier.ControlModifier)
        QCoreApplication.sendEvent(editor.field, QFocusEvent(QEvent.Type.FocusOut))
        return (not editor.is_recording and editor.text() == before
                and transitions[-1] is False and dialog.save_button.isEnabled())

    def close_cancel(dialog, transitions):
        editor = dialog.hotkeys["select"]
        before = editor.text()
        editor.button.click()
        dialog.reject()
        return (not editor.is_recording and editor.text() == before
                and transitions[-1] is False and dialog.editable_changes() == {})

    def readonly(dialog, transitions):
        editor = dialog.hotkeys["select"]
        before = editor.text()
        _key(editor.field, QEvent.Type.KeyPress, Qt.Key.Key_A)
        return editor.field.isReadOnly() and editor.text() == before and not transitions

    for name, callback in (("press_hold_release_save", record),
                           ("invalid_modifier_only_escape_cancel", invalid_and_cancel),
                           ("duplicate_not_committed", duplicate),
                           ("focus_loss_reverts_pending", focus_cancel),
                           ("dialog_reject_restores_recording_state", close_cancel),
                           ("no_manual_text_entry", readonly)):
        check(name, callback)
    return {"passed": all(case["passed"] for case in cases), "cases": cases,
            "qt_platform": QApplication.platformName(), "desktop_input_sent": False,
            "global_hotkeys_registered": False, "native_focus_tested": False,
            "boundary": "Synthetic key events sent only to owned Qt settings fields; not system keyboard injection or live global shortcut validation."}
