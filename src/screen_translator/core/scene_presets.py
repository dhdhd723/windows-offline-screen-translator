"""Versioned, local scene preferences; never includes consent or translation data."""
from __future__ import annotations

import copy
from dataclasses import dataclass
import math
import unicodedata
from collections.abc import Callable

from screen_translator.contracts import Region, Settings

MAX_PRESETS = 20
MAX_NAME_LENGTH = 40
PRESET_FIELDS = frozenset({
    "direction", "text_layout", "chat_slang_enabled", "chat_slang_overrides",
    "capture_fps", "idle_fps", "debounce_ms", "min_ocr_interval_ms", "cpu_threads",
    "font_size", "opacity", "show_source", "esc_enabled", "recording_compatibility",
    "hotkeys", "cache_enabled",
})
SPATIAL_FIELDS = frozenset({"region", "overlay_position"})


class PresetError(ValueError):
    pass


def clean_preset_name(value: object) -> str:
    if not isinstance(value, str):
        raise PresetError("预设名称须为文字")
    value = unicodedata.normalize("NFKC", value).strip()
    if not 1 <= len(value) <= MAX_NAME_LENGTH or any(
            unicodedata.category(char).startswith("C") for char in value):
        raise PresetError("预设名称须为 1–40 个可见字符，不能含控制字符")
    return value


def checked_values(values: object, include_region: bool) -> dict:
    fields = PRESET_FIELDS | SPATIAL_FIELDS if include_region else PRESET_FIELDS
    if not isinstance(values, dict) or set(values) != fields:
        raise PresetError("预设字段缺失或包含不允许恢复的内容")
    data = copy.deepcopy(values)
    for key in ("chat_slang_enabled", "show_source", "esc_enabled",
                "recording_compatibility", "cache_enabled"):
        if not isinstance(data[key], bool):
            raise PresetError("预设开关格式无效")
    for key in ("capture_fps", "idle_fps", "debounce_ms", "min_ocr_interval_ms",
                "cpu_threads", "font_size", "opacity"):
        if (isinstance(data[key], bool) or not isinstance(data[key], (float, int))
                or not math.isfinite(data[key])):
            raise PresetError("预设数值格式无效")
    if data["direction"] not in ("auto", "en-zh", "zh-en") or data["text_layout"] not in ("lines", "continuous"):
        raise PresetError("预设翻译方向或排版无效")
    from screen_translator.core.chat_slang import sanitize_overrides
    if not isinstance(data["chat_slang_overrides"], dict) or sanitize_overrides(
            data["chat_slang_overrides"]) != data["chat_slang_overrides"]:
        raise PresetError("预设聊天词表无效")
    from screen_translator.platform.windows.hotkeys import parse_hotkey
    keys = data["hotkeys"]
    if not isinstance(keys, dict) or set(keys) != set(Settings().hotkeys):
        raise PresetError("预设快捷键字段无效")
    combinations = []
    for key in keys.values():
        if not isinstance(key, str):
            raise PresetError("预设快捷键格式无效")
        try:
            combinations.append(parse_hotkey(key))
        except ValueError as error:
            raise PresetError("预设快捷键格式无效") from error
    if len(set(combinations)) != len(combinations):
        raise PresetError("预设的三个快捷键不能重复")
    if include_region:
        region = data["region"]
        if region is not None:
            if not isinstance(region, dict) or set(region) != set(Region(0, 0, 12, 12).to_dict()):
                raise PresetError("预设选区格式无效")
            if any(isinstance(region[key], bool) or not isinstance(region[key], int)
                   or not -(2 ** 31) <= region[key] < 2 ** 31
                   for key in ("x", "y", "width", "height")):
                raise PresetError("预设选区坐标无效")
            if not isinstance(region["monitor_id"], str) or len(region["monitor_id"]) > 256:
                raise PresetError("预设显示器标识无效")
            bounds = region["monitor_bounds"]
            if bounds is not None and (not isinstance(bounds, (list, tuple)) or len(bounds) != 4
                    or any(isinstance(v, bool) or not isinstance(v, int) or not -(2 ** 31) <= v < 2 ** 31 for v in bounds)
                    or bounds[2] <= bounds[0] or bounds[3] <= bounds[1]):
                raise PresetError("预设显示器范围无效")
            if not Region.from_dict(region).valid():
                raise PresetError("预设选区太小")
        point = data["overlay_position"]
        if point is not None and (not isinstance(point, (list, tuple)) or len(point) != 2
                or any(isinstance(v, bool) or not isinstance(v, int) or not -(2 ** 31) <= v < 2 ** 31 for v in point)):
            raise PresetError("预设字幕位置无效")
    try:
        normalized = Settings.from_dict(data).to_dict()
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        raise PresetError("预设设置格式无效") from error
    return {key: normalized[key] for key in fields}


@dataclass(frozen=True)
class ScenePreset:
    name: str
    values: dict
    include_region: bool = True

    @classmethod
    def capture(cls, name: str, settings: Settings, include_region: bool = True) -> ScenePreset:
        if not isinstance(include_region, bool):
            raise PresetError("预设选区开关格式无效")
        fields = PRESET_FIELDS | SPATIAL_FIELDS if include_region else PRESET_FIELDS
        data = settings.to_dict()
        return cls(clean_preset_name(name), checked_values({key: data[key] for key in fields}, include_region),
                   include_region)

    @classmethod
    def from_dict(cls, data: object) -> ScenePreset:
        if not isinstance(data, dict) or set(data) != {"name", "values", "include_region"}:
            raise PresetError("预设记录格式无效")
        if not isinstance(data["include_region"], bool):
            raise PresetError("预设选区开关格式无效")
        return cls(clean_preset_name(data["name"]), checked_values(data["values"], data["include_region"]),
                   data["include_region"])

    def to_dict(self) -> dict:
        return {"name": self.name, "values": copy.deepcopy(self.values), "include_region": self.include_region}


def restore_preset(current: Settings, preset: ScenePreset,
                   validate_region: Callable[[Region], bool]) -> tuple[Settings, bool]:
    """Merge only scene preferences; failed spatial validation clears old area.

    Machine-wide startup choices and runtime consent always come from the latest
    live settings, never a preset. Caller persists before changing live state.
    """
    if not isinstance(preset, ScenePreset):
        raise PresetError("预设记录格式无效")
    preset = ScenePreset.from_dict(preset.to_dict())
    data = current.to_dict()
    data.update(preset.values)
    result = Settings.from_dict(data)
    reset_region = False
    if preset.include_region:
        try:
            valid = bool(result.region and validate_region(result.region))
        except (OSError, RuntimeError):
            valid = False
        if not valid:
            result.region = None
            result.overlay_position = None
            reset_region = True
    return result, reset_region
