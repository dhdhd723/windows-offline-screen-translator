"""Startup-animation preferences migrate and merge using temporary/offscreen fixtures."""
from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QTabWidget

from screen_translator.contracts import Region, Settings
from screen_translator.storage.settings import SettingsStore
from screen_translator.ui.settings_window import (EDITABLE_SETTING_FIELDS, SettingsDialog,
                                                   merge_settings_changes)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


def test_new_settings_default_to_enabled_startup_animation():
    assert Settings().startup_animation is True
    assert Settings.from_dict({}).startup_animation is True


def test_legacy_settings_default_without_losing_preferences_or_rewriting_file(tmp_path):
    path = tmp_path / "config.json"
    legacy = {"font_size": 30, "direction": "en-zh", "text_layout": "lines",
              "chat_slang_enabled": False, "auto_start": True,
              "hotkeys": {"select": "Alt+R", "toggle": "Alt+T", "clear": "Alt+C"},
              "region": {"x": -120, "y": 20, "width": 300, "height": 60},
              "overlay_position": [-200, 400], "runtime_terms_version": "existing"}
    path.write_text(json.dumps(legacy), encoding="utf-8")
    before = path.read_bytes()
    store = SettingsStore(path)
    loaded = store.load()
    assert loaded.startup_animation is True
    assert loaded.font_size == 30 and loaded.direction == "en-zh" and loaded.text_layout == "lines"
    assert loaded.chat_slang_enabled is False and loaded.auto_start is True
    assert loaded.hotkeys["select"] == "Alt+R"
    assert loaded.region == Region(-120, 20, 300, 60)
    assert loaded.overlay_position == (-200, 400) and loaded.runtime_terms_version == "existing"
    assert store.last_error is None
    assert path.read_bytes() == before


@pytest.mark.parametrize("enabled", [True, False])
def test_boolean_startup_animation_persists_and_round_trips(tmp_path, enabled):
    settings = Settings(startup_animation=enabled, show_source=True, auto_start=True,
                        region=Region(-100, 20, 200, 40), runtime_terms_version="existing")
    store = SettingsStore(tmp_path / "config.json")
    store.save(settings)
    assert store.load().to_dict() == settings.to_dict()
    assert json.loads(store.path.read_text(encoding="utf-8"))["startup_animation"] is enabled
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("invalid", [None, "false", "true", 0, 1, 0.0, [], {}, [False]])
def test_bad_new_field_defaults_without_resetting_other_saved_fields(tmp_path, invalid):
    path = tmp_path / "config.json"
    original = Settings(font_size=30, direction="zh-en", auto_start=True,
                        runtime_terms_version="existing").to_dict()
    original["startup_animation"] = invalid
    path.write_text(json.dumps(original), encoding="utf-8")
    before = path.read_bytes()
    store = SettingsStore(path)
    loaded = store.load()
    assert loaded.startup_animation is True
    assert loaded.font_size == 30 and loaded.direction == "zh-en" and loaded.auto_start is True
    assert loaded.runtime_terms_version == "existing" and store.last_error is None
    assert path.read_bytes() == before


@pytest.mark.parametrize("enabled", [True, False])
def test_dialog_displays_saved_preference_and_no_implicit_edit(qapp, enabled):
    settings = Settings(startup_animation=enabled)
    dialog = SettingsDialog(settings)
    try:
        tabs = dialog.findChild(QTabWidget)
        index = next(index for index in range(tabs.count()) if tabs.tabText(index) == "快捷键")
        assert dialog.startup_animation.parent() is tabs.widget(index)
        assert dialog.startup_animation.text() == "手动启动时显示 2 秒启动动画，结束后打开设置"
        assert dialog.startup_animation.isChecked() is enabled
        assert dialog.values().to_dict() == settings.to_dict()
        assert dialog.editable_changes() == {}
        labels = [label.text() for label in tabs.widget(index).findChildren(QLabel)]
        assert any("2 秒" in text and "不抢焦点" in text and "诊断" in text
                   and "自动启动" in text for text in labels)
    finally:
        dialog.close()


@pytest.mark.parametrize("original, edited", [(True, False), (False, True)])
def test_dialog_animation_delta_merges_and_persists_latest_application_state(qapp, tmp_path, original, edited):
    dialog = SettingsDialog(Settings(startup_animation=original))
    try:
        dialog.startup_animation.setChecked(edited)
        changes = dialog.editable_changes()
        assert changes == {"startup_animation": edited}
        assert "startup_animation" in EDITABLE_SETTING_FIELDS
        latest = Settings(startup_animation=original, region=Region(20, 40, 200, 60),
                          overlay_position=(-500, 600), runtime_terms_version="new-consent",
                          direction="en-zh", font_size=30, auto_start=True,
                          chat_slang_overrides={"np": "not a problem"})
        latest.hotkeys["select"] = "Ctrl+Shift+R"
        merged = merge_settings_changes(latest, changes)
        expected = latest.to_dict()
        expected["startup_animation"] = edited
        assert merged.to_dict() == expected
        assert latest.startup_animation is original
        store = SettingsStore(tmp_path / "config.json")
        store.save(merged)
        assert store.load().to_dict() == merged.to_dict()
    finally:
        dialog.close()


def test_unedited_animation_preserves_concurrent_preference_change(qapp):
    dialog = SettingsDialog(Settings(startup_animation=True))
    try:
        dialog.font_size.setValue(28)
        changes = dialog.editable_changes()
        assert changes == {"font_size": 28}
        merged = merge_settings_changes(Settings(startup_animation=False), changes)
        assert merged.startup_animation is False and merged.font_size == 28
    finally:
        dialog.close()


def test_malformed_animation_patch_uses_field_default_not_whole_settings_reset():
    latest = Settings(startup_animation=False, font_size=30, auto_start=True)
    merged = merge_settings_changes(latest, {"startup_animation": "false"})
    assert merged.startup_animation is True
    assert merged.font_size == 30 and merged.auto_start is True
