"""Research-mode compatibility stays inert in the candidate settings UI."""
from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QComboBox, QLabel

from screen_translator.contracts import Region, Settings
from screen_translator.storage.settings import SettingsStore
from screen_translator.ui.settings_window import SettingsDialog, merge_settings_changes


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


def test_missing_chat_model_preference_is_lightweight_by_default():
    assert Settings().chat_translation_mode == "fast"
    loaded = Settings.from_dict({"font_size": 28, "chat_slang_enabled": False})
    assert loaded.chat_translation_mode == "fast"
    assert loaded.font_size == 28 and not loaded.chat_slang_enabled


@pytest.mark.parametrize("value", [None, "", "FAST", "Enhanced", "remote", "auto", 0, 1,
                                  True, False, [], {}, ["enhanced"], {"enhanced": True}])
def test_invalid_chat_mode_safely_defaults_without_discarding_other_preferences(value):
    settings = Settings.from_dict({"chat_translation_mode": value, "font_size": 31})
    assert settings.chat_translation_mode == "fast" and settings.font_size == 31


@pytest.mark.parametrize("mode", ["fast", "enhanced"])
def test_valid_modes_roundtrip_through_settings_store_without_network_or_migration_loss(tmp_path, mode):
    settings = Settings(chat_translation_mode=mode, chat_slang_enabled=False,
                        chat_slang_overrides={"def": "defense"}, text_layout="lines",
                        region=Region(-900, 20, 300, 100), runtime_terms_version="existing")
    store = SettingsStore(tmp_path / "config.json")
    store.save(settings)
    assert store.load().to_dict() == settings.to_dict()
    assert not list(tmp_path.glob("*.tmp"))


def test_legacy_settings_load_does_not_rewrite_disk_or_force_enhancement(tmp_path):
    path = tmp_path / "config.json"
    data = {"direction": "en-zh", "text_layout": "lines", "font_size": 30,
            "chat_slang_overrides": {"np": "not a problem"}, "runtime_terms_version": "existing"}
    path.write_text(json.dumps(data), encoding="utf-8")
    before = path.read_bytes()
    loaded = SettingsStore(path).load()
    assert loaded.chat_translation_mode == "fast"
    assert loaded.text_layout == "lines" and loaded.font_size == 30
    assert loaded.chat_slang_overrides == data["chat_slang_overrides"]
    assert loaded.runtime_terms_version == "existing" and path.read_bytes() == before


@pytest.mark.parametrize("mode", ["fast", "enhanced"])
def test_research_mode_is_not_editable_and_preserves_raw_preference_without_false_delta(qapp, mode):
    settings = Settings(chat_translation_mode=mode)
    dialog = SettingsDialog(settings)
    try:
        assert not hasattr(dialog, "chat_translation_mode")
        assert all(combo.findData("enhanced") == -1 for combo in dialog.findChildren(QComboBox))
        assert dialog.values().to_dict() == settings.to_dict()
        assert dialog.editable_changes() == {}
        labels = "\n".join(label.text() for label in dialog.findChildren(QLabel))
        assert "1.13 GB" not in labels and "离线增强" not in labels
        assert "不需额外安装聊天模型" in dialog.chat_translation_hint.text()
    finally:
        dialog.close()


@pytest.mark.parametrize("mode", ["fast", "enhanced"])
def test_hidden_research_mode_cannot_be_submitted_as_an_editable_delta(mode):
    current = Settings(chat_slang_enabled=False, chat_slang_overrides={"def": "defense"},
                       region=Region(300, 400, 200, 80), runtime_terms_version="latest")
    before = current.to_dict()
    with pytest.raises(ValueError, match="不可编辑"):
        merge_settings_changes(current, {"chat_translation_mode": mode})
    assert current.to_dict() == before


def test_unedited_mode_does_not_revert_a_concurrent_enhancement_preference(qapp):
    dialog = SettingsDialog(Settings())
    try:
        dialog.font_size.setValue(32)
        changes = dialog.editable_changes()
        assert "chat_translation_mode" not in changes
        merged = merge_settings_changes(Settings(chat_translation_mode="enhanced"), changes)
        assert merged.chat_translation_mode == "enhanced" and merged.font_size == 32
    finally:
        dialog.close()


def test_cancel_does_not_mutate_a_preserved_research_preference(qapp):
    current = Settings(chat_translation_mode="enhanced")
    dialog = SettingsDialog(current)
    try:
        dialog.font_size.setValue(32)
        assert dialog.editable_changes() == {"font_size": 32}
        dialog.reject()
        assert current.chat_translation_mode == "enhanced"
    finally:
        dialog.close()
