"""Text-layout preferences migrate without changing unrelated local settings."""
from __future__ import annotations

import json

import pytest

from screen_translator.contracts import Region, Settings
from screen_translator.storage.settings import SettingsStore


def test_legacy_settings_default_to_continuous_without_losing_preferences(tmp_path):
    path = tmp_path / "config.json"
    legacy = {"font_size": 28, "direction": "en-zh",
              "hotkeys": {"select": "Alt+R", "toggle": "Alt+T", "clear": "Alt+C"},
              "region": {"x": -100, "y": 20, "width": 300, "height": 60},
              "runtime_terms_version": "accepted-existing-version"}
    path.write_text(json.dumps(legacy), encoding="utf-8")
    before = path.read_bytes()
    store = SettingsStore(path)
    loaded = store.load()
    assert loaded.text_layout == "continuous"
    assert loaded.font_size == 28 and loaded.direction == "en-zh"
    assert loaded.hotkeys["select"] == "Alt+R"
    assert loaded.region == Region(-100, 20, 300, 60)
    assert loaded.runtime_terms_version == "accepted-existing-version"
    assert store.last_error is None
    assert path.read_bytes() == before  # Reading never rewrites the user's file.


@pytest.mark.parametrize("layout", ["continuous", "lines"])
def test_text_layout_persists_and_round_trips(tmp_path, layout):
    store = SettingsStore(tmp_path / "config.json")
    settings = Settings(text_layout=layout, show_source=True,
                        overlay_position=(-300, 40), runtime_terms_version="existing")
    store.save(settings)
    assert store.load().to_dict() == settings.to_dict()
    assert json.loads(store.path.read_text(encoding="utf-8"))["text_layout"] == layout
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("invalid", ["unknown", "LINES", "", None, 3, True, [], {}])
def test_unknown_or_malformed_layout_falls_back_without_losing_other_settings(invalid):
    settings = Settings.from_dict({"text_layout": invalid, "font_size": 30,
                                   "direction": "zh-en", "runtime_terms_version": "existing"})
    assert settings.text_layout == "continuous"
    assert settings.font_size == 30 and settings.direction == "zh-en"
    assert settings.runtime_terms_version == "existing"
