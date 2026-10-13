"""Owned-window policy tests; no NVIDIA/Steam UI or real input is exercised."""
from __future__ import annotations

import ctypes
import os
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from screen_translator.contracts import Settings, TranslationResult
from screen_translator.platform.windows import window_styles
from screen_translator.ui.main import MainUI


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


def test_affinity_sets_only_requested_own_window_policy_and_verifies(monkeypatch):
    api = MagicMock()
    actual = 0
    calls = []

    def set_affinity(hwnd, policy):
        nonlocal actual
        calls.append((hwnd, policy))
        actual = policy
        return True

    def get_affinity(hwnd, value):
        value._obj.value = actual
        return True

    api.SetWindowDisplayAffinity.side_effect = set_affinity
    api.GetWindowDisplayAffinity.side_effect = get_affinity
    monkeypatch.setattr(window_styles.sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: api)
    assert window_styles.set_capture_exclusion(101, False)
    assert window_styles.set_capture_exclusion(101, True)
    assert calls == [(101, 0), (101, 0x11)]
    api.GetWindowDisplayAffinity.side_effect = lambda hwnd, value: False
    assert not window_styles.set_capture_exclusion(101, False)


def test_default_recording_policy_never_requests_exclusion(qapp, monkeypatch):
    calls = []
    monkeypatch.setattr("screen_translator.ui.subtitle_overlay.apply_overlay_styles", lambda hwnd: True)
    monkeypatch.setattr("screen_translator.ui.subtitle_overlay.set_capture_exclusion",
                        lambda hwnd, enabled: calls.append(enabled) or True)
    ui = MainUI(Settings())
    try:
        ui.show_result(TranslationResult("source", "译文", "en-zh", 1))
        qapp.processEvents()
        assert ui.overlay.isVisible()
        assert ui.overlay.capture_policy_applied
        assert not ui.overlay.capture_excluded
        assert calls and not any(calls)
    finally:
        ui.close()


def test_switching_live_mode_and_hiding_clears_exclusion(qapp, monkeypatch):
    calls = []
    monkeypatch.setattr("screen_translator.ui.subtitle_overlay.apply_overlay_styles", lambda hwnd: True)
    monkeypatch.setattr("screen_translator.ui.subtitle_overlay.set_capture_exclusion",
                        lambda hwnd, enabled: calls.append(enabled) or True)
    ui = MainUI(Settings(recording_compatibility=False))
    try:
        ui.show_result(TranslationResult("source", "译文", "en-zh", 1))
        assert ui.overlay.capture_excluded and calls[-1] is True
        ui.update_settings(Settings(recording_compatibility=True))
        assert not ui.overlay.capture_excluded and calls[-1] is False
        ui.update_settings(Settings(recording_compatibility=False))
        assert ui.overlay.capture_excluded
        ui.set_hidden(True)
        assert calls[-1] is False
        assert not ui.overlay._topmost_timer.isActive()
        # A new result while Esc-hidden must not mark even the hidden HWND
        # as capture-excluded again or restart its topmost timer.
        hidden_call_count = len(calls)
        ui.show_result(TranslationResult("new source", "新译文", "en-zh", 1))
        ui.update_settings(Settings(recording_compatibility=False))
        assert len(calls) == hidden_call_count
        assert not ui.overlay.isVisible()
        assert not ui.overlay.capture_excluded
        assert not ui.overlay._topmost_timer.isActive()
        ui.set_hidden(False)
        assert calls[-1] is True
    finally:
        ui.close()


@pytest.mark.parametrize("style_ok, policy_ok", [(False, True), (True, False)])
def test_native_policy_failure_safely_hides_and_warns_once(qapp, monkeypatch, style_ok, policy_ok):
    monkeypatch.setattr("screen_translator.ui.subtitle_overlay.apply_overlay_styles", lambda hwnd: style_ok)
    monkeypatch.setattr("screen_translator.ui.subtitle_overlay.set_capture_exclusion", lambda hwnd, enabled: policy_ok)
    ui = MainUI(Settings())
    warnings = []
    monkeypatch.setattr(ui, "notify", lambda *args, **kwargs: warnings.append(args))
    try:
        ui.show_result(TranslationResult("source", "译文", "en-zh", 1))
        ui.set_hidden(False)
        assert not ui.overlay.isVisible()
        assert not ui.overlay._topmost_timer.isActive()
        assert len(warnings) == 1
        assert ui.copy_action.isEnabled()
    finally:
        ui.close()


def test_tray_labels_use_actual_successful_bindings(qapp, monkeypatch):
    monkeypatch.setattr("screen_translator.ui.subtitle_overlay.apply_overlay_styles", lambda hwnd: True)
    monkeypatch.setattr("screen_translator.ui.subtitle_overlay.set_capture_exclusion", lambda hwnd, enabled: True)
    ui = MainUI(Settings())
    try:
        ui.set_effective_hotkeys({"toggle": "Alt+T", "clear": "Alt+C"})
        assert "不可用" in ui.select_action.text()
        assert "Alt+T" in ui.toggle_action.text()
    finally:
        ui.close()


def test_legacy_settings_enable_recording_compatibility_without_losing_hotkeys():
    restored = Settings.from_dict({"hotkeys": {"select": "Alt+R", "toggle": "Alt+T", "clear": "Alt+C"}})
    assert restored.recording_compatibility
    assert restored.hotkeys["select"] == "Alt+R"
