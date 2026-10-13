"""Settings recovery uses offscreen widgets, never games or physical input."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from screen_translator.contracts import Settings, TranslationResult
from screen_translator.ui.main import MainUI


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


@pytest.fixture
def ui(qapp, monkeypatch):
    monkeypatch.setattr("screen_translator.ui.subtitle_overlay.apply_overlay_styles", lambda hwnd: True)
    monkeypatch.setattr("screen_translator.ui.subtitle_overlay.set_capture_exclusion",
                        lambda hwnd, enabled: True)
    value = MainUI(Settings())
    monkeypatch.setattr(value, "notify", lambda *args, **kwargs: None)
    yield value
    # The selector marker in the state-boundary test is not a native selector.
    value._selector = None
    value.close()
    qapp.processEvents()


def test_settings_restore_caption_after_automatic_overlap_hide(ui, qapp, monkeypatch):
    original_reposition = ui.overlay.reposition

    def reposition():
        original_reposition()
        # A smaller font leaves enough space outside this synthetic region.
        ui.overlay.overlaps_capture = ui.overlay.settings.font_size > 20

    monkeypatch.setattr(ui.overlay, "reposition", reposition)
    result = TranslationResult("source", "译文", "en-zh", 1)
    ui.show_result(result)
    assert not ui.overlay.isVisible()
    assert not ui.hidden
    assert ui.copy_action.isEnabled()

    ui.update_settings(Settings(font_size=20))
    qapp.processEvents()
    assert ui.overlay.isVisible()
    assert ui.overlay.translation_label.text() == result.translation


def test_settings_restore_caption_after_native_policy_recovers(ui, qapp, monkeypatch):
    policy_ok = False
    monkeypatch.setattr("screen_translator.ui.subtitle_overlay.set_capture_exclusion",
                        lambda hwnd, enabled: policy_ok)
    ui.show_result(TranslationResult("source", "译文", "en-zh", 1))
    assert not ui.overlay.isVisible()
    assert not ui.hidden

    policy_ok = True
    ui.update_settings(Settings(opacity=0.6))
    qapp.processEvents()
    assert ui.overlay.isVisible()
    assert ui.overlay.capture_policy_applied


def test_settings_do_not_restore_explicitly_hidden_caption(ui, qapp):
    ui.show_result(TranslationResult("source", "译文", "en-zh", 1))
    assert ui.overlay.isVisible()
    ui.set_hidden(True)

    ui.update_settings(Settings(font_size=24))
    qapp.processEvents()
    assert ui.hidden
    assert not ui.overlay.isVisible()
    assert not ui.overlay._topmost_timer.isActive()


def test_settings_do_not_show_caption_during_region_selection(ui, qapp):
    ui.show_result(TranslationResult("source", "译文", "en-zh", 1))
    ui.overlay.hide()
    ui._selector = object()

    ui.update_settings(Settings(opacity=0.6))
    qapp.processEvents()
    assert not ui.overlay.isVisible()
    assert not ui.overlay._topmost_timer.isActive()


def test_settings_do_not_show_caption_for_empty_translation(ui, qapp):
    ui.show_result(TranslationResult("source", "", "en-zh", 1))
    assert not ui.overlay.isVisible()

    ui.update_settings(Settings(font_size=24))
    qapp.processEvents()
    assert not ui.overlay.isVisible()
    assert not ui.copy_action.isEnabled()
    assert not ui.overlay._topmost_timer.isActive()
