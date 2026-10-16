"""Conservative game-title rules and their engine integration, without models."""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from screen_translator.core.game_terms import (
    GAME_TERMS_VERSION,
    translate_known_game_line,
    translation_identity,
)
from screen_translator.inference import InferenceCancelled, InputLimitError
from screen_translator.inference.translation.ctranslate2_engine import CTranslate2Engine
from screen_translator.storage.translation_cache import make_cache_key


@pytest.mark.parametrize("source,expected", [
    ("STARDEW VALLEY", "星露谷物语"),
    ("  stardew   Valley  ", "星露谷物语"),
    ("Hollow Knight", "空洞骑士"),
    ("  HOLLOW   KNIGHT  ", "空洞骑士"),
    ("Slay the Spire", "杀戮尖塔"),
    ("  slay   THE   spire  ", "杀戮尖塔"),
])
def test_only_complete_known_titles_have_trusted_translations(source, expected):
    assert translate_known_game_line(source, "en-zh") == expected


@pytest.mark.parametrize("source,expected", [
    ("Stardew Valley created by:", "《星露谷物语》制作："),
    ("Created by Eric Barone", "制作者：Eric Barone"),
    ('Stardew Valley created by: Eric Barone "ConcernedApe"',
     '《星露谷物语》由 Eric Barone "ConcernedApe" 制作'),
    ("Eric Barone", "Eric Barone"),
    ("ConcernedApe", "ConcernedApe"),
    ('Eric Barone "ConcernedApe"', 'Eric Barone "ConcernedApe"'),
])
def test_complete_known_credits_preserve_the_author_names(source, expected):
    assert translate_known_game_line(source, "en-zh") == expected


@pytest.mark.parametrize("source", [
    "", "   ", "NEW", "LOAD", "EXIT", "NEW GAME", "OPTIONS",
    "Rust", "Portal", "UNKNOWN GAME", "JOHN SMITH",
    "Welcome to Stardew Valley", "I like Hollow Knight.",
    "Stardew Valley settings", "Stardew Valley 2", "Stardew Valley is fun.",
    "NotStardew Valley", "Stardew Valleyish", "Hollow Knightmare",
    "Created by JOHN SMITH", "Created by Unknown Creator",
    "Stardew Valley created by: Unknown Creator",
    "Developed by Eric Barone and another person",
    "Stardew Valley\nHollow Knight", "Stardew\nValley",
    "\nStardew Valley", "Stardew Valley\n",
])
def test_unknown_words_sentences_and_multiline_inputs_are_not_overridden(source):
    assert translate_known_game_line(source, "en-zh") is None


@pytest.mark.parametrize("direction", ["zh-en", "auto", "unknown"])
def test_rules_are_exclusively_for_explicit_en_zh(direction):
    assert translate_known_game_line("Stardew Valley", direction) is None
    assert translation_identity("fixture-model", direction) == "fixture-model"


def test_identity_is_stable_direction_scoped_and_separates_old_cached_results():
    assert GAME_TERMS_VERSION == 1
    identity = translation_identity("fixture-model", "en-zh")
    assert identity.startswith("fixture-model")
    assert identity != "fixture-model"
    assert translation_identity("fixture-model", "en-zh") == identity
    assert translation_identity("another-model", "en-zh") != identity
    assert make_cache_key(identity, "en-zh", "STARDEW VALLEY") != make_cache_key(
        "fixture-model", "en-zh", "STARDEW VALLEY")
    assert translation_identity("fixture-model", "zh-en") == "fixture-model"


class CharacterTokenizer:
    eos = "</s>"

    def encode(self, text):
        return list(text) + [self.eos]

    def decode(self, tokens):
        return "".join(token for token in tokens if token != self.eos)


class RecordingNative:
    def __init__(self):
        self.calls = []

    def translate_batch(self, sources, **kwargs):
        text = "".join(token for token in sources[0] if token != "</s>")
        self.calls.append(text)
        return [SimpleNamespace(hypotheses=[[f"NATIVE[{text}]", "</s>"]])]


@pytest.fixture
def fake_engine(tmp_path):
    engine = CTranslate2Engine(tmp_path)
    native = RecordingNative()
    for direction in ("en-zh", "zh-en"):
        engine._tokenizers[direction] = CharacterTokenizer()
        engine._translators[direction] = native
    return engine, native


@pytest.mark.parametrize("source,expected", [
    ("STARDEW VALLEY", "星露谷物语"),
    ("Hollow Knight", "空洞骑士"),
    ("Slay the Spire", "杀戮尖塔"),
    ("Created by Eric Barone", "制作者：Eric Barone"),
])
def test_engine_known_lines_do_not_enter_native_translation(fake_engine, source, expected):
    engine, native = fake_engine
    assert engine.translate(source, "en-zh") == expected
    assert native.calls == []


@pytest.mark.parametrize("source", [
    "NEW", "LOAD", "EXIT", "Rust", "Portal", "JOHN SMITH",
    "Welcome to Stardew Valley", "Stardew Valley settings",
    "Created by Unknown Creator", "Please water the crops before you leave.",
])
def test_engine_ordinary_lines_reach_native_unchanged(fake_engine, source):
    engine, native = fake_engine
    assert engine.translate(source, "en-zh") == f"NATIVE[{source}]"
    assert native.calls == [source]


def test_engine_mixed_rows_preserve_order_blank_rows_and_native_context(fake_engine):
    engine, native = fake_engine
    source = "STARDEW VALLEY\nNEW\n\nWelcome to Stardew Valley\nHollow Knight"
    result = engine.translate(source, "en-zh")
    assert result.splitlines() == [
        "星露谷物语", "NATIVE[NEW]", "",
        "NATIVE[Welcome to Stardew Valley]", "空洞骑士",
    ]
    assert len(result.splitlines()) == len(source.splitlines())
    assert native.calls == ["NEW", "Welcome to Stardew Valley"]


def test_engine_zh_en_never_uses_the_english_title_rules(fake_engine):
    engine, native = fake_engine
    assert engine.translate("Stardew Valley", "zh-en") == "NATIVE[Stardew Valley]"
    assert native.calls == ["Stardew Valley"]


def test_engine_cancelled_title_does_not_return_a_dictionary_result(fake_engine):
    engine, native = fake_engine
    with pytest.raises(InferenceCancelled):
        engine.translate_cancellable("STARDEW VALLEY", "en-zh", lambda: True)
    assert native.calls == []


def test_engine_rechecks_cancellation_during_all_known_multiline_input(fake_engine):
    engine, native = fake_engine
    checks = []

    def cancel_after_first_check():
        checks.append(True)
        return len(checks) > 1

    with pytest.raises(InferenceCancelled):
        engine.translate_cancellable(
            "Stardew Valley\nHollow Knight", "en-zh", cancel_after_first_check)
    assert len(checks) >= 2
    assert native.calls == []


@pytest.mark.parametrize("source", ["x" * 16001, "Stardew" + " " * 16000 + "Valley"])
def test_engine_input_limit_precedes_game_lookup_and_native_translation(fake_engine, source):
    engine, native = fake_engine
    with pytest.raises(InputLimitError):
        engine.translate(source, "en-zh")
    assert native.calls == []


def test_model_identity_is_unchanged_by_lazy_initialization(tmp_path, monkeypatch):
    from screen_translator.inference.translation import ctranslate2_engine as module

    manifest = {"translation": {
        "en-zh": {"id": "fixture-en-zh", "path": "translation/en-zh-int8"},
        "zh-en": {"id": "fixture-zh-en", "path": "translation/zh-en-int8"},
    }}
    monkeypatch.setattr(module, "read_manifest", lambda root: manifest)
    monkeypatch.setattr(module, "verify_files", lambda *args: None)
    monkeypatch.setattr(module, "MarianSentencePieceTokenizer", lambda folder: CharacterTokenizer())
    monkeypatch.setitem(sys.modules, "ctranslate2", SimpleNamespace(
        Translator=lambda *args, **kwargs: RecordingNative()))

    engine = CTranslate2Engine(tmp_path)
    before = engine.model_id("en-zh")
    from screen_translator.inference.translation.ctranslate2_engine import TRANSLATION_POLICY_ID
    assert before == translation_identity("fixture-en-zh", "en-zh") + "|" + TRANSLATION_POLICY_ID
    assert before != "fixture-en-zh"
    assert engine.translate("NEW", "en-zh") == "NATIVE[NEW]"
    assert engine.model_id("en-zh") == before
    engine._initialize("zh-en")
    assert engine.model_id("zh-en") == "fixture-zh-en"


def test_pipeline_ignores_old_title_cache_and_restarts_with_the_new_policy_cache(fake_engine):
    from screen_translator.contracts import Region, Settings
    from screen_translator.core.pipeline import Pipeline
    from screen_translator.storage.translation_cache import TranslationCache
    from test_dialogue_layout_pipeline import OCR, Screen, wait_for

    engine, native = fake_engine
    engine._ids["en-zh"] = "fixture-model"
    source = "STARDEW VALLEY"
    old_key = make_cache_key("fixture-model", "en-zh", source, text_layout="lines")
    new_key = make_cache_key(engine.model_id("en-zh"), "en-zh", source, text_layout="lines")
    assert old_key != new_key
    cache = TranslationCache()
    cache.put(old_key, "标准瓦利")
    screen, ocr = Screen(), OCR({40: source})
    results, statuses = [], []
    settings = Settings(text_layout="lines", direction="en-zh", chat_slang_enabled=False,
                        capture_fps=12, idle_fps=6, debounce_ms=80, min_ocr_interval_ms=200)
    pipeline = Pipeline(settings, ocr, engine, cache, results.append, statuses.append, screen.backend)
    try:
        pipeline.start(Region(0, 0, 64, 32))
        wait_for(lambda: len(results) == 1)
        assert results[0].source == source
        assert results[0].translation == "星露谷物语"
        assert results[0].cache_hit is False
        assert cache.get(old_key) == "标准瓦利"
        assert cache.get(new_key) == "星露谷物语"
        pipeline.stop()
        pipeline.start(Region(0, 0, 64, 32))
        wait_for(lambda: len(results) == 2)
        assert results[-1].translation == "星露谷物语"
        assert results[-1].cache_hit is True
        assert native.calls == []
    finally:
        pipeline.shutdown(2)

