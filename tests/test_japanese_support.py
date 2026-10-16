"""Japanese direction/settings/worker policy using owned data, no desktop."""
from __future__ import annotations

from dataclasses import replace
import json
import os
import re
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

from screen_translator.contracts import OCRResult, Region, Settings
from screen_translator.core.scene_presets import ScenePreset, restore_preset
from screen_translator.core.text import choose_direction
from screen_translator.inference import InferenceCancelled, ModelFilesError
from screen_translator.inference.translation.ctranslate2_engine import CTranslate2Engine, format_translation_output
from screen_translator.inference.translation.m2m_tokenizer import M2M100JapaneseTokenizer
from screen_translator.inference.translation.tokenizer import split_text_for_model
from screen_translator.storage.presets import PresetStore
from screen_translator.storage.settings import SettingsStore
from screen_translator.storage.translation_cache import TranslationCache, make_cache_key


@pytest.mark.parametrize("source", ["こんにちは", "ありがとう", "メニュー", "ｹﾞｰﾑ", "か\u3099", "終了",
                                    "保存", "敵は右側にいます。", "Player: ありがとう", "HPを10回復"])
def test_explicit_japanese_accepts_kana_han_and_mixed_text(source):
    assert choose_direction(source, "ja-zh") == "ja-zh"


@pytest.mark.parametrize("source", ["", " ", "123", "？", "ーー", "❤️"])
def test_explicit_japanese_does_not_translate_noise(source):
    assert choose_direction(source, "ja-zh") is None


@pytest.mark.parametrize("source,expected", [("Hello", "en-zh"), ("保存", "zh-en"), ("こんにちは", None)])
def test_auto_mode_is_still_legacy_chinese_english(source, expected):
    assert choose_direction(source) == expected


def test_japanese_direction_persists_and_round_trips_presets(tmp_path):
    original = Settings(direction="ja-zh", text_layout="lines", show_source=True,
                        hotkeys={"select":"Ctrl+Shift+R", "toggle":"Alt+T", "clear":"Alt+C"})
    settings = SettingsStore(tmp_path / "settings.json")
    settings.save(original)
    assert settings.load().direction == "ja-zh"
    store = PresetStore(tmp_path / "presets.json")
    store.save("日文游戏", original, False)
    saved = store.list_presets()[0]
    restored, reset = restore_preset(Settings(auto_start=True), saved, lambda region: True)
    assert restored.direction == "ja-zh" and restored.auto_start and not reset


def fake_japanese_engine(tmp_path, answer="你好", *, limit=False):
    calls = []
    class Tokenizer:
        eos = "</s>"
        target_prefix = ("__zh__",)
        def encode(self, text):
            return ["__ja__", *text, self.eos]
        def decode(self, tokens):
            return "".join(token for token in tokens if token not in {"__zh__", "</s>"})
    class Native:
        def translate_batch(self, sources, **kwargs):
            calls.append((sources, kwargs))
            assert kwargs["target_prefix"] == [["__zh__"]]
            target = sources[0][1:-1] if answer is None else [answer]
            return [SimpleNamespace(hypotheses=[["__zh__", *target, "</s>"]])]
    engine = CTranslate2Engine(tmp_path)
    engine._tokenizers["ja-zh"] = Tokenizer()
    engine._translators["ja-zh"] = Native()
    engine._ids["ja-zh"] = "owned-fake-japanese"
    return engine, calls


def test_japanese_targets_chinese_preserves_input_rows_and_converts_output_once(tmp_path):
    engine, calls = fake_japanese_engine(tmp_path, "乾清宮")
    source = "こんにちは。\nありがとう。"
    assert engine.translate(source, "ja-zh") == "乾清宫\n乾清宫"
    assert ["".join(row[0][0][1:-1]) for row in calls] == source.splitlines()
    assert "opencc-t2s" in engine.model_id("ja-zh")


def test_japanese_does_not_apply_english_slang_or_game_title_rules(tmp_path):
    engine, calls = fake_japanese_engine(tmp_path, None)
    assert engine.translate("ty\nSTARDEW VALLEY", "ja-zh") == "ty\nSTARDEW VALLEY"
    assert len(calls) == 2


def test_long_japanese_keeps_every_source_character_and_token_budget(tmp_path):
    engine, calls = fake_japanese_engine(tmp_path, None)
    source = "このドアを開けないでください。" * 40
    assert engine.translate(source, "ja-zh")
    submitted = "".join("".join(call[0][0][1:-1]) for call in calls)
    assert re.sub(r"\s", "", submitted) == source
    assert len(calls) > 1
    assert all(len(call[0][0]) <= 192 and call[0][0][0] == "__ja__" for call in calls)


def test_japanese_cancel_stops_before_next_model_chunk(tmp_path):
    engine, calls = fake_japanese_engine(tmp_path)
    with pytest.raises(InferenceCancelled):
        engine.translate_cancellable("ありがとう。" * 100, "ja-zh", lambda: bool(calls))
    assert len(calls) == 1


def test_japanese_cache_separates_directions_and_policy(tmp_path):
    engine, _ = fake_japanese_engine(tmp_path)
    key = make_cache_key(engine.model_id("ja-zh"), "ja-zh", "保存")
    assert key != make_cache_key(engine.model_id("ja-zh"), "en-zh", "保存")
    assert key != make_cache_key("owned-fake-japanese", "ja-zh", "保存")


def test_japanese_missing_pack_has_actionable_error_without_loading_or_network(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"schema_version":1,"translation":{}}))
    engine = CTranslate2Engine(tmp_path)
    for operation in (lambda: engine.model_id("ja-zh"), lambda: engine.translate("こんにちは", "ja-zh")):
        with pytest.raises(ModelFilesError, match="日语增强完整包"):
            operation()
    assert not engine._translators


def test_model_release_policy_retains_legacy_pair_but_never_both_language_families(tmp_path):
    engine = CTranslate2Engine(tmp_path)
    engine._translators = {"ja-zh":object(), "zh-en":object(), "en-zh":object()}
    engine._tokenizers = dict(engine._translators)
    engine.configure_direction("ja-zh")
    assert set(engine._translators) == set(engine._tokenizers) == {"ja-zh"}
    engine.configure_direction("auto")
    assert not engine._translators and not engine._tokenizers
    assert engine._preferred_direction == "en-zh"
    engine._translators = {"zh-en":object(), "en-zh":object()}
    engine.configure_direction("zh-en")
    assert set(engine._translators) == {"zh-en", "en-zh"}


def test_selected_direction_is_used_for_prewarm(tmp_path, monkeypatch):
    engine = CTranslate2Engine(tmp_path)
    engine.configure_direction("ja-zh")
    calls = []
    monkeypatch.setattr(engine, "translate", lambda text, direction: calls.append((text,direction)))
    engine.warmup()
    assert calls == [("こんにちは。", "ja-zh")]


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


def test_japanese_ui_values_and_preset_summary(qapp, tmp_path):
    from screen_translator.ui.settings_window import SettingsDialog
    from screen_translator.ui.preset_dialog import PresetDialog
    dialog = SettingsDialog(Settings())
    index = dialog.direction.findData("ja-zh")
    assert index >= 0
    dialog.direction.setCurrentIndex(index)
    assert dialog.values().direction == "ja-zh"
    assert dialog.editable_changes() == {"direction":"ja-zh"}
    store = PresetStore(tmp_path / "presets.json")
    store.save("日文游戏", dialog.values(), False)
    manager = PresetDialog(store, lambda: Settings(), lambda row: (True, "ok"))
    manager.list.setCurrentRow(0)
    assert "日语 → 简体中文" in manager.summary.text()
    manager.close()
    dialog.close()


def test_tokenizer_uses_language_tokens_and_external_vocabulary_not_spm_ids(tmp_path, monkeypatch):
    seen = []
    class FakeSP:
        def __init__(self, model_proto):
            assert model_proto == b"fixture-spm"
        def encode(self, text, out_type):
            assert out_type is str
            return ["▁こんにちは", "unknown-piece"]
        def decode(self, pieces):
            seen.append(pieces)
            return "你好"
    monkeypatch.setitem(sys.modules, "sentencepiece", SimpleNamespace(SentencePieceProcessor=FakeSP))
    (tmp_path / "vocab.json").write_text(json.dumps({"<unk>":3,"</s>":2,"▁こんにちは":19}))
    (tmp_path / "sentencepiece.bpe.model").write_bytes(b"fixture-spm")
    (tmp_path / "shared_vocabulary.json").write_text(json.dumps(["__ja__","__zh__","</s>","<unk>","__en__"]))
    tokenizer = M2M100JapaneseTokenizer(tmp_path)
    assert tokenizer.encode("こんにちは") == ["__ja__","▁こんにちは","<unk>","</s>"]
    assert tokenizer.decode(["__zh__","你好","</s>","__en__"]) == "你好"
    assert seen == [["你好"]]


def test_japanese_real_pipeline_reuses_cache_and_releases_model_on_worker(tmp_path):
    from screen_translator.core.pipeline import Pipeline
    owner = threading.get_ident()
    output, statuses = [], []
    class OCR:
        def recognize(self, image):
            return OCRResult("ありがとう", confidence=.99)
    class Translator:
        def __init__(self):
            self.calls, self.configs = [], []
        def configure_direction(self, direction):
            self.configs.append((direction,threading.get_ident()))
        def model_id(self, direction):
            return "fixture-" + direction
        def translate(self, text, direction):
            self.calls.append((text,direction,threading.get_ident()))
            return "谢谢"
    class Backend:
        def grab(self, region):
            return np.full((50,200,3),80,dtype=np.uint8)
        def close(self):
            pass
    translator = Translator()
    settings = Settings(direction="ja-zh",debounce_ms=80,min_ocr_interval_ms=200)
    cache = TranslationCache(tmp_path / "cache.sqlite")
    pipeline = Pipeline(settings, OCR(), translator, cache, output.append, statuses.append, Backend)
    def wait(predicate):
        deadline = time.monotonic() + 5
        while not predicate() and time.monotonic() < deadline:
            time.sleep(.01)
        assert predicate()
    try:
        pipeline.start(Region(0,0,200,50))
        wait(lambda: any(row.translation == "谢谢" for row in output))
        assert translator.calls[0][:2] == ("ありがとう","ja-zh")
        pipeline.stop()
        pipeline.clear()
        pipeline.start(Region(0,0,200,50))
        wait(lambda: any(row.cache_hit for row in output))
        assert len(translator.calls) == 1
        pipeline.stop()
        pipeline.update_settings(replace(settings,direction="en-zh"))
        wait(lambda: any(mode == "en-zh" for mode, thread in translator.configs))
        assert all(thread != owner for _, thread in translator.configs)
        assert all(thread != owner for _, _, thread in translator.calls)
    finally:
        pipeline.shutdown()
