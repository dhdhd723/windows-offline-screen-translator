import json
import sqlite3
import threading

import pytest

from screen_translator.contracts import Region, Settings
from screen_translator.storage.settings import SettingsStore
from screen_translator.storage.translation_cache import TranslationCache, make_cache_key


def test_settings_round_trip_negative_screen_coordinates(tmp_path):
    store = SettingsStore(tmp_path / "config.json")
    settings = Settings(region=Region(-1920, -80, 1000, 240, "DISPLAY2", (-1920, 0, 0, 1080)),
                        overlay_position=(-1800, 280), show_source=True)
    store.save(settings)
    restored = store.load()
    assert restored.to_dict() == settings.to_dict()
    assert not list(tmp_path.glob("*.tmp"))


def test_damaged_settings_are_preserved_and_fall_back(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{broken", encoding="utf-8")
    store = SettingsStore(path)
    assert store.load() == Settings()
    assert store.last_error
    assert path.read_text(encoding="utf-8") == "{broken"


def test_unknown_fields_and_out_of_range_values(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"capture_fps": 900, "idle_fps": 900, "opacity": 3,
                                "font_size": 3, "future_option": "ignore"}), encoding="utf-8")
    settings = SettingsStore(path).load()
    assert settings.capture_fps == settings.idle_fps == 12
    assert settings.opacity == 1.0
    assert settings.font_size == 12


def test_atomic_failure_keeps_last_good_settings(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    store = SettingsStore(path)
    store.save(Settings(font_size=18))

    def fail_replace(*args):
        raise PermissionError("busy file")

    monkeypatch.setattr("screen_translator.storage.settings.os.replace", fail_replace)
    with pytest.raises(PermissionError):
        store.save(Settings(font_size=24))
    assert store.load().font_size == 18
    assert not list(tmp_path.glob("*.tmp"))


def test_memory_lru_is_bounded_and_creates_no_disk_file(tmp_path):
    path = tmp_path / "cache.sqlite3"
    cache = TranslationCache(path, max_entries=2)
    cache.put("one", "一")
    cache.put("two", "二")
    assert cache.get("one") == "一"
    cache.put("three", "三")
    assert cache.get("two") is None
    assert not path.exists()
    cache.close()


def test_persistence_opt_in_caps_database_and_survives_new_instance(tmp_path):
    path = tmp_path / "cache.sqlite3"
    cache = TranslationCache(path, max_entries=2)
    cache.set_persistence(True)
    assert cache.persistent
    for i in range(4):
        cache.put(f"key{i}", f"translation{i}")
    cache.close()
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM translations").fetchone()[0] == 2
    other = TranslationCache(path, max_entries=2)
    assert other.get("key3") is None  # Disk is still opt-in on a new instance.
    other.set_persistence(True)
    assert other.get("key3") == "translation3"
    assert other.get("key0") is None
    other.close()


def test_sqlite_cache_is_safe_when_settings_and_inference_use_different_threads(tmp_path):
    cache = TranslationCache(tmp_path / "cache.sqlite3", max_entries=20)
    cache.set_persistence(True)
    errors = []

    def worker():
        try:
            for i in range(20):
                cache.put(str(i), f"结果 {i}")
                assert cache.get(str(i)) == f"结果 {i}"
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(3)
    assert not thread.is_alive()
    assert not errors
    cache.close()


def test_cache_key_never_fuzzy_matches_or_crosses_model_or_direction():
    key = make_cache_key("model-v1", "en-zh", "Remaining 10 seconds")
    assert key != make_cache_key("model-v1", "en-zh", "Remaining 19 seconds")
    assert key != make_cache_key("model-v2", "en-zh", "Remaining 10 seconds")
    assert key != make_cache_key("model-v1", "zh-en", "Remaining 10 seconds")
    assert "Remaining" not in key
