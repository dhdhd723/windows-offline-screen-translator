"""Strict optional-model preset migration, isolated from actual user files."""
from __future__ import annotations

import copy
import json

import pytest

from screen_translator.contracts import Region, Settings
from screen_translator.core.scene_presets import PRESET_FIELDS, PresetError, ScenePreset, restore_preset
from screen_translator.storage.presets import PresetStore


def legacy_record(include_region=True):
    settings = Settings(direction="en-zh", text_layout="lines", font_size=30,
                        region=Region(-900, 20, 300, 100), overlay_position=(-800, 180),
                        chat_slang_overrides={"def": "defense"})
    record = ScenePreset.capture("Roblox", settings, include_region).to_dict()
    del record["values"]["chat_translation_mode"]
    return record


@pytest.mark.parametrize("include_region", [True, False])
@pytest.mark.parametrize("mode", ["fast", "enhanced"])
def test_capture_and_restore_include_explicit_chat_mode_without_restoring_machine_state(include_region, mode):
    saved = Settings(chat_translation_mode=mode, text_layout="lines",
                     runtime_terms_version="saved", auto_start=True)
    preset = ScenePreset.capture("聊天", saved, include_region)
    assert preset.values["chat_translation_mode"] == mode
    current = Settings(runtime_terms_version="latest", auto_start=False,
                       region=Region(30, 40, 150, 60))
    restored, _ = restore_preset(current, preset, lambda region: True)
    assert restored.chat_translation_mode == mode and restored.text_layout == "lines"
    assert restored.runtime_terms_version == "latest" and not restored.auto_start
    assert current.chat_translation_mode == "fast"


@pytest.mark.parametrize("include_region", [True, False])
def test_exact_old_allowlist_migrates_in_memory_only_and_does_not_mutate_input(include_region):
    record = legacy_record(include_region)
    before = copy.deepcopy(record)
    preset = ScenePreset.from_dict(record)
    assert preset.values["chat_translation_mode"] == "fast"
    assert preset.values["font_size"] == 30
    assert preset.values["chat_slang_overrides"] == {"def": "defense"}
    assert record == before and "chat_translation_mode" not in record["values"]


@pytest.mark.parametrize("include_region", [True, False])
def test_legacy_preset_read_keeps_file_untouched_and_later_explicit_write_retains_all_old_preferences(tmp_path, include_region):
    path = tmp_path / "presets.json"
    record = legacy_record(include_region)
    path.write_text(json.dumps({"schema_version": 1, "presets": [record]}), encoding="utf-8")
    before = path.read_bytes()
    store = PresetStore(path)
    loaded = store.list_presets()
    assert len(loaded) == 1 and loaded[0].values["chat_translation_mode"] == "fast"
    assert path.read_bytes() == before
    store.save("增强聊天", Settings(chat_translation_mode="enhanced"), False)
    reread = PresetStore(path).list_presets()
    assert [preset.values["chat_translation_mode"] for preset in reread] == ["fast", "enhanced"]
    assert reread[0].values["font_size"] == 30
    assert reread[0].values["chat_slang_overrides"] == {"def": "defense"}
    assert reread[0].include_region == include_region


@pytest.mark.parametrize("missing_field", sorted(PRESET_FIELDS - {"chat_translation_mode"}))
def test_legacy_migration_does_not_fill_any_other_missing_field(missing_field):
    record = legacy_record(False)
    del record["values"][missing_field]
    with pytest.raises(PresetError):
        ScenePreset.from_dict(record)


@pytest.mark.parametrize("field,value", [("unknown", "anything"), ("translation", "private text"),
                                        ("runtime_terms_version", "bad"), ("model_path", "bad")])
@pytest.mark.parametrize("legacy", [True, False])
def test_unknown_fields_are_rejected_in_new_and_legacy_snapshots(field, value, legacy):
    record = legacy_record(False)
    if not legacy:
        record["values"]["chat_translation_mode"] = "fast"
    record["values"][field] = value
    with pytest.raises(PresetError):
        ScenePreset.from_dict(record)


@pytest.mark.parametrize("mode", [None, "", "FAST", "auto", "remote", True, False, 0, 1, [], {}, ["enhanced"]])
def test_present_but_malformed_mode_is_rejected_not_silently_migrated(mode):
    record = legacy_record(False)
    record["values"]["chat_translation_mode"] = mode
    with pytest.raises(PresetError, match="模式无效"):
        ScenePreset.from_dict(record)


def test_malformed_legacy_file_is_not_overwritten_during_read_or_new_save(tmp_path):
    path = tmp_path / "presets.json"
    record = legacy_record(False)
    del record["values"]["font_size"]
    path.write_text(json.dumps({"schema_version": 1, "presets": [record]}), encoding="utf-8")
    before = path.read_bytes()
    store = PresetStore(path)
    for operation in (store.list_presets, lambda: store.save("新场景", Settings())):
        with pytest.raises(PresetError):
            operation()
        assert path.read_bytes() == before
