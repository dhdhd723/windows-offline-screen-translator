"""A bounded atomic JSON store, separate from settings and private caches."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import threading

from screen_translator.contracts import Settings
from screen_translator.core.scene_presets import MAX_PRESETS, PresetError, ScenePreset, clean_preset_name
from screen_translator.paths import data_root

MAX_PRESET_BYTES = 1_048_576


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PresetError("预设文件存在重复字段，未覆盖原文件")
        result[key] = value
    return result


class PresetStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else data_root() / "presets.json"
        self._lock = threading.RLock()

    def _read(self) -> list[ScenePreset]:
        try:
            if not self.path.exists():
                return []
            with self.path.open("rb") as stream:
                raw = stream.read(MAX_PRESET_BYTES + 1)
            if len(raw) > MAX_PRESET_BYTES:
                raise PresetError("预设文件过大，未覆盖原文件")
            data = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_object)
            if (not isinstance(data, dict) or set(data) != {"schema_version", "presets"}
                    or type(data["schema_version"]) is not int or data["schema_version"] != 1
                    or not isinstance(data["presets"], list) or len(data["presets"]) > MAX_PRESETS):
                raise PresetError("预设文件版本或格式不受支持，未覆盖原文件")
            presets = [ScenePreset.from_dict(row) for row in data["presets"]]
            if len({row.name.casefold() for row in presets}) != len(presets):
                raise PresetError("预设存在重名，未覆盖原文件")
            return presets
        except (UnicodeError, ValueError, TypeError, KeyError, OverflowError, RecursionError) as error:
            raise PresetError("预设文件损坏或格式不受支持，未覆盖原文件") from error

    def list_presets(self) -> list[ScenePreset]:
        with self._lock:
            return self._read()

    def _write(self, rows: list[ScenePreset]) -> None:
        encoded = (json.dumps({"schema_version": 1, "presets": [row.to_dict() for row in rows]},
                              ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
        if len(encoded) > MAX_PRESET_BYTES:
            raise PresetError("预设内容过大，未覆盖原文件")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=self.path.name + ".", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def save(self, name: str, settings: Settings, include_region: bool = True, *, replace: bool = False) -> None:
        preset = ScenePreset.capture(name, settings, include_region)
        with self._lock:
            rows = self._read()
            index = next((i for i, row in enumerate(rows) if row.name.casefold() == preset.name.casefold()), None)
            if index is not None:
                if not replace:
                    raise PresetError("名称已存在，请使用“用当前设置更新”")
                rows[index] = preset
            else:
                if replace:
                    raise PresetError("该预设已不存在，请刷新列表")
                if len(rows) >= MAX_PRESETS:
                    raise PresetError("最多保存 20 个预设，请先删除不用的预设")
                rows.append(preset)
            self._write(rows)

    def rename(self, name: str, new_name: str) -> None:
        clean = clean_preset_name(new_name)
        with self._lock:
            rows = self._read()
            index = next((i for i, row in enumerate(rows) if row.name == name), None)
            if index is None:
                raise PresetError("该预设已不存在，请刷新列表")
            if any(i != index and row.name.casefold() == clean.casefold() for i, row in enumerate(rows)):
                raise PresetError("名称已存在，请换一个名称")
            rows[index] = ScenePreset(clean, rows[index].values, rows[index].include_region)
            self._write(rows)

    def delete(self, name: str) -> None:
        with self._lock:
            rows = self._read()
            kept = [row for row in rows if row.name != name]
            if len(kept) == len(rows):
                raise PresetError("该预设已不存在，请刷新列表")
            self._write(kept)
