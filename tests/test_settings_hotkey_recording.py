"""Settings/main-UI capture coordination on diagnostic-owned offscreen widgets."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QTabWidget

from screen_translator.contracts import Settings
from screen_translator.ui.hotkey_diagnostics import run_hotkey_recording_self_test
from screen_translator.ui.main import MainUI
from screen_translator.ui.settings_window import SettingsDialog


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


@pytest.fixture
def dialog(qapp):
    value = SettingsDialog(Settings())
    value.findChild(QTabWidget).setCurrentIndex(2)
    value.show()
    qapp.processEvents()
    yield value
    value.close()
    value.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_frozen_compatible_key_event_diagnostic(qapp):
    report = run_hotkey_recording_self_test()
    assert report["passed"], report
    assert len(report["cases"]) == 6
    assert all(case["passed"] for case in report["cases"])
    assert not report["desktop_input_sent"] and not report["global_hotkeys_registered"]


def test_second_editor_cancels_first_without_enabling_global_hotkeys(dialog):
    transitions = []
    dialog.hotkey_recording_changed.connect(transitions.append)
    first, second = dialog.hotkeys["select"], dialog.hotkeys["toggle"]
    first.begin_capture()
    assert first.is_recording and transitions == [True]
    second.begin_capture()
    assert second.is_recording and not first.is_recording
    assert all(transitions) and not dialog.save_button.isEnabled()
    assert dialog.editable_changes() == {}
    second.cancel_capture()
    assert transitions[-1] is False and dialog.save_button.isEnabled()


def test_window_deactivation_cancels_unfinished_recording(dialog):
    editor = dialog.hotkeys["select"]
    transitions = []
    dialog.hotkey_recording_changed.connect(transitions.append)
    editor.begin_capture()
    QCoreApplication.sendEvent(dialog, QEvent(QEvent.Type.WindowDeactivate))
    assert not editor.is_recording and transitions[-1] is False
    assert dialog.editable_changes() == {} and dialog.save_button.isEnabled()


def test_changing_tabs_cancels_capture(dialog):
    editor = dialog.hotkeys["select"]
    editor.begin_capture()
    dialog.findChild(QTabWidget).setCurrentIndex(0)
    assert not editor.is_recording and dialog.save_button.isEnabled()


def test_save_during_capture_is_not_an_implicit_commit(dialog):
    editor = dialog.hotkeys["select"]
    editor.begin_capture()
    dialog._save()
    assert dialog.isVisible() and editor.is_recording
    assert dialog.editable_changes() == {}


def test_main_ui_forwards_capture_and_shutdown_cancels(qapp, monkeypatch):
    monkeypatch.setattr("screen_translator.ui.subtitle_overlay.apply_overlay_styles", lambda hwnd: True)
    monkeypatch.setattr("screen_translator.ui.subtitle_overlay.set_capture_exclusion", lambda hwnd, enabled: True)
    ui = MainUI(Settings())
    transitions, changes = [], []
    ui.hotkey_recording_changed.connect(transitions.append)
    ui.settings_changed.connect(changes.append)
    try:
        ui.open_settings()
        value = ui._settings_dialog
        value.findChild(QTabWidget).setCurrentIndex(2)
        qapp.processEvents()
        value.hotkeys["select"].begin_capture()
        assert transitions[-1] is True
        ui.close()
        assert transitions[-1] is False and changes == []
    finally:
        if not ui.is_closed:
            ui.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_commit_validation_still_rejects_programmatic_duplicate(dialog, monkeypatch):
    warnings = []
    monkeypatch.setattr("screen_translator.ui.settings_window.QMessageBox.warning",
                        lambda *args: warnings.append(args))
    dialog.hotkeys["select"].setText("Alt+T")
    dialog._save()
    assert warnings and "重复" in warnings[0][-1]
    assert dialog.isVisible()
