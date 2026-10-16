"""Synthetic preset policy/storage tests; never uses real user data or desktop."""
from __future__ import annotations

import copy
import json

import pytest

from screen_translator.contracts import Region, Settings
from screen_translator.core.scene_presets import (
    MAX_PRESETS, PRESET_FIELDS, SPATIAL_FIELDS, PresetError, ScenePreset,
    clean_preset_name, restore_preset,
)
from screen_translator.storage.presets import MAX_PRESET_BYTES, PresetStore


def configured():
    return Settings(direction="en-zh", text_layout="lines", font_size=30, opacity=.65,
                    region=Region(-900, 20, 300, 100, "left", (-1920, 0, 0, 1080)),
                    overlay_position=(-800, 180), runtime_terms_version="current-consent",
                    auto_start=True, startup_animation=False,
                    hotkeys={"select":"Ctrl+Shift+R","toggle":"Ctrl+Shift+T","clear":"Ctrl+Shift+C"},
                    chat_slang_overrides={"rn":"registered nurse"}, cache_enabled=True)


@pytest.mark.parametrize("include", [True, False])
def test_capture_has_exact_allowlist_and_no_global_state_or_aliased_dicts(include):
    original = configured()
    preset = ScenePreset.capture("Roblox 聊天", original, include)
    assert set(preset.values) == (PRESET_FIELDS | SPATIAL_FIELDS if include else PRESET_FIELDS)
    assert not {"schema_version","runtime_terms_version","auto_start","startup_animation"} & set(preset.values)
    original.hotkeys["toggle"] = "Alt+Q"
    original.chat_slang_overrides["rn"] = "right now"
    assert preset.values["hotkeys"]["toggle"] == "Ctrl+Shift+T"
    assert preset.values["chat_slang_overrides"]["rn"] == "registered nurse"
    asdict = preset.to_dict()
    asdict["values"]["hotkeys"]["toggle"] = "Alt+Z"
    assert preset.values["hotkeys"]["toggle"] == "Ctrl+Shift+T"


@pytest.mark.parametrize("name,expected", [(" 游戏 ","游戏"),("Ｒｏｂｌｏｘ","Roblox"),("阅读 / 学习","阅读 / 学习"),("x"*40,"x"*40)])
def test_names_are_visible_bounded_normalized_labels_not_paths(name,expected):
    assert clean_preset_name(name) == expected


@pytest.mark.parametrize("name", [None, 1, "", " ", "x"*41, "name\nline", "\x00name", "name\u202e", "bad\ud800"])
def test_bad_names_are_rejected(name):
    with pytest.raises(PresetError):
        clean_preset_name(name)


def test_restore_scene_preserves_latest_consent_and_machine_preferences():
    saved = configured()
    preset = ScenePreset.capture("聊天", saved)
    current = Settings(runtime_terms_version="new-consent", auto_start=False, startup_animation=True)
    restored, reset = restore_preset(current, preset, lambda region: True)
    assert not reset and restored.region == saved.region
    assert restored.font_size == 30 and restored.text_layout == "lines"
    assert restored.runtime_terms_version == "new-consent"
    assert not restored.auto_start and restored.startup_animation
    assert current.font_size == 22 and current.region is None
    restored.hotkeys["toggle"] = "Alt+Y"
    assert preset.values["hotkeys"]["toggle"] == "Ctrl+Shift+T"


@pytest.mark.parametrize("available", [False, None, "raises"])
def test_unavailable_preset_region_does_not_fall_back_to_old_game_region(available):
    def validate(region):
        if available == "raises":
            raise OSError("unavailable")
        return available
    current = Settings(region=Region(10,10,80,60),overlay_position=(1,2))
    restored, reset = restore_preset(current, ScenePreset.capture("游戏",configured()), validate)
    assert reset and restored.region is None and restored.overlay_position is None
    assert current.region is not None


def test_without_spatial_snapshot_latest_region_and_position_are_preserved():
    current = Settings(region=Region(10,10,80,60),overlay_position=(1,2))
    def do_not_validate(region):
        raise AssertionError("Non-spatial preset must not restore old region")
    restored,reset = restore_preset(current, ScenePreset.capture("阅读",configured(),False),do_not_validate)
    assert not reset and restored.region == current.region and restored.overlay_position == (1,2)


def test_explicit_spatial_preset_without_region_clears_previous_region():
    preset = ScenePreset.capture("未框选",Settings(),True)
    result,reset = restore_preset(configured(),preset,lambda _:True)
    assert reset and result.region is None and result.overlay_position is None


@pytest.mark.parametrize("field,value", [
    ("opacity",float("nan")),("capture_fps",float("inf")),("cpu_threads",True),
    ("font_size","22"),("chat_slang_enabled",1),("cache_enabled","yes"),
    ("direction","en"),("text_layout","unknown"),("hotkeys",{"toggle":"Alt+T"}),
    ("hotkeys",{"select":"Alt+T","toggle":"Alt+T","clear":"Alt+C"}),
    ("hotkeys",{"select":"Ctrl+Alt+R","toggle":False,"clear":"Alt+C"}),
    ("chat_slang_overrides",{"rn":"现在"}),("overlay_position",[1]),
    ("overlay_position",[True,2]),("overlay_position",[2**40,2]),
])
def test_damaged_snapshot_values_are_rejected(field,value):
    row=ScenePreset.capture("测试",configured()).to_dict()
    row["values"][field]=value
    with pytest.raises(PresetError):
        ScenePreset.from_dict(row)


@pytest.mark.parametrize("field,value", [("width",1),("x",True),("x",2**40),("monitor_bounds",[1,2,3]),("monitor_id",1)])
def test_invalid_spatial_coordinates_are_rejected(field,value):
    row=ScenePreset.capture("测试",configured()).to_dict()
    row["values"]["region"][field]=value
    with pytest.raises(PresetError):
        ScenePreset.from_dict(row)


@pytest.mark.parametrize("global_field", ["runtime_terms_version","auto_start","startup_animation","schema_version","translation","cache"])
def test_snapshot_cannot_smuggle_non_scene_fields(global_field):
    row=ScenePreset.capture("测试",configured()).to_dict()
    row["values"][global_field]="not allowed"
    with pytest.raises(PresetError):
        ScenePreset.from_dict(row)


def test_disk_roundtrip_crud_and_no_implicit_application(tmp_path):
    path=tmp_path/"user-data"/"presets.json"
    store=PresetStore(path)
    assert store.list_presets()==[] and not path.exists()
    current=configured()
    before=copy.deepcopy(current.to_dict())
    store.save("聊天",current)
    store.save("阅读",Settings(font_size=32),False)
    rows=PresetStore(path).list_presets()
    assert [row.name for row in rows]==["聊天","阅读"]
    assert rows[0].values["region"]["x"]==-900 and not rows[1].include_region
    assert current.to_dict()==before
    store.rename("聊天","组队聊天")
    store.save("组队聊天",Settings(font_size=42),False,replace=True)
    assert store.list_presets()[0].values["font_size"]==42
    store.delete("组队聊天")
    assert [row.name for row in store.list_presets()]==["阅读"]
    assert current.to_dict()==before
    assert list(path.parent.iterdir())==[path]


def test_casefold_and_nfkc_duplicates_require_explicit_update(tmp_path):
    store=PresetStore(tmp_path/"presets.json")
    store.save("Roblox",Settings())
    for name in ("roblox","Ｒｏｂｌｏｘ"):
        with pytest.raises(PresetError):
            store.save(name,Settings(font_size=30))
    assert store.list_presets()[0].values["font_size"]==22
    store.save("ROBLOX",Settings(font_size=30),replace=True)
    assert len(store.list_presets())==1
    store.rename("ROBLOX","Roblox")
    assert store.list_presets()[0].name=="Roblox"


def test_missing_update_rename_delete_never_changes_file(tmp_path):
    store=PresetStore(tmp_path/"presets.json")
    store.save("阅读",Settings())
    before=store.path.read_bytes()
    for operation in (lambda:store.save("missing",Settings(),replace=True),
                      lambda:store.rename("missing","new"),lambda:store.delete("missing")):
        with pytest.raises(PresetError):
            operation()
        assert store.path.read_bytes()==before


def test_twenty_presets_limit_and_duplicate_rename_are_non_destructive(tmp_path):
    store=PresetStore(tmp_path/"presets.json")
    for index in range(MAX_PRESETS):
        store.save("scene"+str(index),Settings())
    before=store.path.read_bytes()
    with pytest.raises(PresetError):
        store.save("extra",Settings())
    with pytest.raises(PresetError):
        store.rename("scene0","SCENE1")
    assert store.path.read_bytes()==before


@pytest.mark.parametrize("content", [b"{",b"[]",b"null",b'\xff',b'{"schema_version":2,"presets":[]}',
                                     b'{"schema_version":true,"presets":[]}',b"x"*(MAX_PRESET_BYTES+1)],
                         ids=["truncated","array","null","encoding","future","boolean-version","oversized"])
def test_corrupt_or_future_store_is_never_replaced_by_read_or_write(tmp_path,content):
    store=PresetStore(tmp_path/"presets.json")
    store.path.write_bytes(content)
    for operation in (store.list_presets,lambda:store.save("new",Settings()),lambda:store.delete("old")):
        with pytest.raises(PresetError):
            operation()
        assert store.path.read_bytes()==content


def test_store_reloads_external_updates_before_each_write(tmp_path):
    path=tmp_path/"presets.json"
    first,second=PresetStore(path),PresetStore(path)
    first.save("first",Settings())
    second.save("second",Settings())
    assert [row.name for row in first.list_presets()]==["first","second"]
    second.delete("first")
    with pytest.raises(PresetError):
        first.save("first",Settings(),replace=True)


def test_atomic_replace_failure_keeps_original_and_removes_temporary(tmp_path,monkeypatch):
    import screen_translator.storage.presets as module
    store=PresetStore(tmp_path/"presets.json")
    store.save("original",Settings())
    before=store.path.read_bytes()
    def denied(*args):
        raise PermissionError("synthetic denied")
    monkeypatch.setattr(module.os,"replace",denied)
    with pytest.raises(PermissionError):
        store.save("new",Settings())
    assert store.path.read_bytes()==before and list(tmp_path.iterdir())==[store.path]


def test_serialized_presets_have_no_legal_or_runtime_content(tmp_path):
    store=PresetStore(tmp_path/"presets.json")
    store.save("聊天",configured())
    raw=store.path.read_text(encoding="utf-8")
    assert "current-consent" not in raw
    assert all(word not in raw for word in ("runtime_terms_version","auto_start","startup_animation","translation"))
    record=json.loads(raw)
    assert len(record["presets"])==1 and record["schema_version"]==1


@pytest.mark.parametrize("content", [b'{"schema_version":1,"schema_version":1,"presets":[]}',
                                     b"["*1200+b"]"*1200],ids=["duplicate-fields","deep-nesting"])
def test_ambiguous_and_recursive_damaged_files_are_preserved(tmp_path,content):
    store=PresetStore(tmp_path/"presets.json")
    store.path.write_bytes(content)
    with pytest.raises(PresetError):
        store.save("new",Settings())
    assert store.path.read_bytes()==content


@pytest.mark.parametrize("monitor_id,bounds,valid", [
    ("left",(-1920,0,0,1080),True),
    ("LEFT",(-1920,0,0,1080),True),
    ("replaced",(-1920,0,0,1080),False),
    ("left",(-1600,0,0,900),False),
    ("left",(0,0,1920,1080),False),
])
def test_monitor_identity_and_physical_layout_are_checked_on_restore(monkeypatch,monitor_id,bounds,valid):
    from screen_translator.platform.windows import monitors
    monkeypatch.setattr(monitors,"enumerate_monitors",lambda:[monitors.Monitor(monitor_id,bounds,bounds)])
    restored,reset=restore_preset(Settings(),ScenePreset.capture("游戏",configured()),monitors.validate_region)
    assert bool(restored.region)==valid and reset is not valid


def test_non_preset_input_is_rejected_before_any_restore():
    with pytest.raises(PresetError):
        restore_preset(Settings(),{"name":"not-a-preset"},lambda _:True)
