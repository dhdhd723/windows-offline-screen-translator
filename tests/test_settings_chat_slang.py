"""Chat-word-list settings and bounded offscreen editor checks use fixtures only."""
from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QTabWidget

from screen_translator.contracts import Region, Settings
from screen_translator.core.chat_slang import BUILTIN_CHAT_SLANG
from screen_translator.core.chat_translation import BUILTIN_CHAT_ZH
from screen_translator.storage.settings import SettingsStore
from screen_translator.ui.settings_window import (SettingsDialog, merge_settings_changes,
                                                   parse_chat_slang_overrides)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


def test_chat_slang_defaults_are_enabled_with_independent_override_maps():
    first, second = Settings(), Settings()
    assert first.chat_slang_enabled is True and first.chat_slang_overrides == {}
    first.chat_slang_overrides["np"] = "not a problem"
    assert second.chat_slang_overrides == {}


def test_legacy_settings_load_without_rewriting_or_losing_existing_preferences(tmp_path):
    path = tmp_path / "config.json"
    original = {"text_layout": "lines", "font_size": 30, "runtime_terms_version": "existing",
                "hotkeys": {"select": "Alt+R", "toggle": "Alt+T", "clear": "Alt+C"}}
    path.write_text(json.dumps(original), encoding="utf-8")
    before = path.read_bytes()
    store = SettingsStore(path)
    loaded = store.load()
    assert loaded.chat_slang_enabled and loaded.chat_slang_overrides == {}
    assert loaded.text_layout == "lines" and loaded.font_size == 30
    assert loaded.runtime_terms_version == "existing" and loaded.hotkeys["select"] == "Alt+R"
    assert store.last_error is None and path.read_bytes() == before


@pytest.mark.parametrize("enabled", [True, False])
def test_chat_slang_fields_persist_without_touching_other_settings(tmp_path, enabled):
    settings = Settings(chat_slang_enabled=enabled, chat_slang_overrides={"np": "not a problem"},
                        region=Region(-100, 20, 200, 40), runtime_terms_version="existing")
    store = SettingsStore(tmp_path / "config.json")
    store.save(settings)
    assert store.load().to_dict() == settings.to_dict()
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("invalid", [None, "false", 0, 1, [], {}])
def test_malformed_enable_flag_defaults_to_true_without_losing_preferences(invalid):
    settings = Settings.from_dict({"chat_slang_enabled": invalid, "font_size": 28})
    assert settings.chat_slang_enabled is True and settings.font_size == 28


@pytest.mark.parametrize("invalid", [None, "np = no problem", [], 42])
def test_malformed_override_container_defaults_to_empty(invalid):
    settings = Settings.from_dict({"chat_slang_overrides": invalid, "font_size": 28})
    assert settings.chat_slang_overrides == {} and settings.font_size == 28


def test_damaged_override_entries_are_cleaned_tolerantly_and_capped():
    settings = Settings.from_dict({"chat_slang_overrides": {
        " NP ": " no problem ", "TYS": "thanks", "1np": "bad token", "n p": "bad token",
        "é": "bad token", "empty": "", "chinese": "谢谢", "multiline": "thank\nyou",
        "control": "no\tproblem", "nontext": 4, "np": "not a problem",
    }})
    assert settings.chat_slang_overrides == {"np": "not a problem", "tys": "thanks"}
    bounded = Settings.from_dict({"chat_slang_overrides": {f"key{i}": "some words" for i in range(101)}})
    assert len(bounded.chat_slang_overrides) == 100


def test_editor_accepts_case_normalization_ascii_expansion_and_equals():
    assert parse_chat_slang_overrides(" TYS = thanks \n\nNp = no problem\nr2 = right = twice") == {
        "tys": "thanks", "np": "no problem", "r2": "right = twice"}


@pytest.mark.parametrize("text", [
    "tys thanks", "= thanks", "1tys = thanks", "bad-token = thanks", "中文 = thanks",
    "np =", "np = 谢谢", "np = 123", "np = no\tproblem", "np = no problem\ncontinued",
    "np =\tno problem", "np = no problem\t", "np = no problem\vtys = thanks",
    "a" * 25 + " = thanks", "np = " + "a" * 161,
    "np = no problem\nNP = not a problem",
])
def test_editor_strictly_rejects_invalid_or_duplicate_entries(text):
    with pytest.raises(ValueError):
        parse_chat_slang_overrides(text)


def test_editor_accepts_maximum_entries_and_rejects_the_next_one():
    text = "\n".join(f"key{i} = some words" for i in range(100))
    assert len(parse_chat_slang_overrides(text)) == 100
    with pytest.raises(ValueError, match="100"):
        parse_chat_slang_overrides(text + "\nextra = some words")


def test_dialog_has_chat_tab_and_reads_clean_saved_preferences(qapp):
    settings = Settings(chat_slang_enabled=False, chat_slang_overrides={"tys": "thanks", "np": "not a problem"})
    dialog = SettingsDialog(settings)
    try:
        tabs = dialog.findChild(QTabWidget)
        assert "聊天词表" in [tabs.tabText(index) for index in range(tabs.count())]
        assert not dialog.chat_slang_enabled.isChecked()
        assert dialog.chat_slang_overrides.toPlainText() == "np = not a problem\ntys = thanks"
        assert dialog.values().to_dict() == settings.to_dict()
        assert dialog.editable_changes() == {}
    finally:
        dialog.close()


def test_dialog_default_empty_overrides_do_not_materialize_builtins(qapp):
    dialog = SettingsDialog(Settings())
    try:
        assert dialog.chat_slang_enabled.isChecked()
        assert dialog.chat_slang_overrides.toPlainText() == ""
        assert dialog.values().chat_slang_overrides == {}
        assert dialog.editable_changes() == {}
    finally:
        dialog.close()


def test_dialog_browsable_builtin_list_matches_actual_defaults_and_is_read_only(qapp):
    dialog = SettingsDialog(Settings(chat_slang_overrides={"np": "not a problem"}))
    try:
        assert dialog.chat_slang_builtin_list.isReadOnly()
        assert dialog.chat_slang_builtin_list.toPlainText() == "\n".join(
            f"{key} = {value} | 独立消息：{BUILTIN_CHAT_ZH.get(key, '交给模型')}"
            for key, value in sorted(BUILTIN_CHAT_SLANG.items()))
        assert f"{len(BUILTIN_CHAT_SLANG)} 条" in dialog.chat_slang_builtin_hint.text()
        assert "无需手动添加" in dialog.chat_slang_builtin_hint.text()
        assert dialog.chat_slang_overrides.toPlainText() == "np = not a problem"
        assert dialog.editable_changes() == {}
    finally:
        dialog.close()


def test_dialog_builtin_list_and_count_follow_new_program_defaults(qapp, monkeypatch):
    monkeypatch.setitem(BUILTIN_CHAT_SLANG, "futureword", "a newly included expression")
    dialog = SettingsDialog(Settings())
    try:
        assert "futureword = a newly included expression" in dialog.chat_slang_builtin_list.toPlainText()
        assert f"{len(BUILTIN_CHAT_SLANG)} 条" in dialog.chat_slang_builtin_hint.text()
        assert dialog.chat_slang_enabled.isChecked()
        assert dialog.chat_slang_overrides.toPlainText() == ""
        assert dialog.editable_changes() == {}
    finally:
        dialog.close()


def test_enable_flag_delta_does_not_erase_concurrent_overrides(qapp):
    dialog = SettingsDialog(Settings())
    try:
        dialog.chat_slang_enabled.setChecked(False)
        changes = dialog.editable_changes()
        assert changes == {"chat_slang_enabled": False}
        latest = Settings(chat_slang_overrides={"np": "not a problem"}, region=Region(20, 40, 200, 60),
                          runtime_terms_version="existing")
        merged = merge_settings_changes(latest, changes)
        assert not merged.chat_slang_enabled and merged.chat_slang_overrides == latest.chat_slang_overrides
        assert merged.region == latest.region and merged.runtime_terms_version == "existing"
        assert latest.chat_slang_enabled is True
    finally:
        dialog.close()


def test_override_delta_is_independent_of_concurrent_enable_flag(qapp):
    dialog = SettingsDialog(Settings())
    try:
        dialog.chat_slang_overrides.setPlainText("TYS = thanks\nNP = not a problem")
        changes = dialog.editable_changes()
        assert changes == {"chat_slang_overrides": {"tys": "thanks", "np": "not a problem"}}
        merged = merge_settings_changes(Settings(chat_slang_enabled=False), changes)
        assert merged.chat_slang_overrides == changes["chat_slang_overrides"]
        assert not merged.chat_slang_enabled
    finally:
        dialog.close()


def test_clearing_custom_overrides_is_a_real_edit(qapp):
    dialog = SettingsDialog(Settings(chat_slang_overrides={"np": "not a problem"}))
    try:
        dialog.chat_slang_overrides.clear()
        assert dialog.editable_changes() == {"chat_slang_overrides": {}}
    finally:
        dialog.close()


def test_unedited_chat_preferences_preserve_live_changes(qapp):
    dialog = SettingsDialog(Settings())
    try:
        dialog.font_size.setValue(28)
        merged = merge_settings_changes(Settings(chat_slang_enabled=False, chat_slang_overrides={"np": "not a problem"}),
                                         dialog.editable_changes())
        assert not merged.chat_slang_enabled and merged.chat_slang_overrides == {"np": "not a problem"}
    finally:
        dialog.close()


def test_invalid_chat_word_list_warns_without_accepting_dialog(qapp, monkeypatch):
    dialog = SettingsDialog(Settings())
    warnings, accepted = [], []
    monkeypatch.setattr("screen_translator.ui.settings_window.QMessageBox.warning",
                        lambda *args: warnings.append(args))
    monkeypatch.setattr(dialog, "accept", lambda: accepted.append(True))
    try:
        dialog.chat_slang_overrides.setPlainText("np =")
        dialog._save()
        assert not accepted and len(warnings) == 1
        assert warnings[0][1] == "聊天词表格式有误" and "第 1 行" in warnings[0][2]
        with pytest.raises(ValueError):
            dialog.values()
    finally:
        dialog.close()


def test_valid_chat_word_list_accepts_without_warning(qapp, monkeypatch):
    dialog = SettingsDialog(Settings())
    accepted = []
    monkeypatch.setattr("screen_translator.ui.settings_window.QMessageBox.warning",
                        lambda *args: pytest.fail("unexpected warning"))
    monkeypatch.setattr(dialog, "accept", lambda: accepted.append(True))
    try:
        dialog.chat_slang_overrides.setPlainText("tys = thanks\nnp = no problem")
        dialog._save()
        assert accepted == [True]
    finally:
        dialog.close()
