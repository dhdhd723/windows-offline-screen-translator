"""Synthetic dialogue regressions; no game, desktop pixels or model files are read."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import replace

import numpy as np
import pytest

from screen_translator.contracts import OCRResult, Region, Settings, TextLine
from screen_translator.core.pipeline import Pipeline, _Frame
from screen_translator.core.text import NORMALIZATION_VERSION, normalize_text
from screen_translator.inference import InferenceCancelled
from screen_translator.storage.translation_cache import TranslationCache, make_cache_key


REGION = Region(0, 0, 64, 32)


def wait_for(predicate, timeout=4.0):
    deadline = time.monotonic() + timeout
    pause = threading.Event()
    while time.monotonic() < deadline:
        if predicate():
            return
        pause.wait(0.015)
    assert predicate(), "Timed out waiting for dialogue worker state"


class Screen:
    def __init__(self):
        self.value = 40
        self.grabs = 0
        self.closed = 0
        self._lock = threading.Lock()

    def set(self, value):
        with self._lock:
            self.value = value

    def backend(self):
        screen = self
        owner = threading.get_ident()

        class Backend:
            def grab(self, region):
                assert threading.get_ident() == owner
                with screen._lock:
                    screen.grabs += 1
                    return np.full((region.height, region.width, 3), screen.value,
                                   dtype=np.uint8)

            def close(self):
                assert threading.get_ident() == owner
                screen.closed += 1

        return Backend()


class OCR:
    def __init__(self, texts):
        self.texts = texts
        self.calls = []

    def recognize(self, image):
        value = int(image[0, 0, 0])
        self.calls.append(value)
        return OCRResult(self.texts[value], confidence=0.99)


class Translator:
    """Mirror the real translator's paragraph split without invoking a model."""

    def __init__(self, *, block_first=False, cancellable=False):
        self.calls = []
        self.paragraphs = []
        self.block_first = block_first
        self.cancellable = cancellable
        self.entered = threading.Event()
        self.release = threading.Event()
        self.cancelled = threading.Event()

    def model_id(self, direction):
        return "dialogue-fake-" + direction

    def translate(self, text, direction):
        self.calls.append((text, direction))
        self.entered.set()
        if self.block_first and len(self.calls) == 1:
            assert self.release.wait(5), "Unreleased synthetic translation"
        paragraphs = text.splitlines()
        self.paragraphs.extend((part, direction) for part in paragraphs)
        return "\n".join("译：" + part for part in paragraphs)

    def translate_cancellable(self, text, direction, cancel_check):
        if not self.cancellable:
            return self.translate(text, direction)
        self.calls.append((text, direction))
        self.entered.set()
        if self.block_first and len(self.calls) == 1:
            assert self.release.wait(5), "Unreleased synthetic translation"
        if cancel_check():
            self.cancelled.set()
            raise InferenceCancelled()
        paragraphs = text.splitlines()
        self.paragraphs.extend((part, direction) for part in paragraphs)
        return "\n".join("译：" + part for part in paragraphs)


@pytest.fixture
def make_pipeline():
    instances = []

    def factory(texts, *, text_layout="lines", translator=None, cache=None, ocr=None):
        settings = Settings(text_layout=text_layout, capture_fps=12, idle_fps=6,
                            debounce_ms=80, min_ocr_interval_ms=200)
        screen = Screen()
        ocr = ocr or OCR(texts)
        translator = translator or Translator()
        results, statuses = [], []
        pipeline = Pipeline(settings, ocr, translator, cache or TranslationCache(),
                            results.append, statuses.append, screen.backend)
        instances.append((pipeline, ocr, translator))
        return pipeline, screen, ocr, translator, results, settings

    yield factory
    for pipeline, ocr, translator in instances:
        if hasattr(ocr, "release"):
            ocr.release.set()
        translator.release.set()
        pipeline.shutdown(2)


@pytest.mark.parametrize("text,expected", [
    ("  Hello   there  \r\n\n  Good morning!  ", "Hello there\nGood morning!"),
    ("你 好\n世 界", "你好\n世界"),
    ("\n\t \r\n", ""),
    ("ＡＢＣ\u200b\r\n１２３", "ABC\n123"),
])
def test_line_normalization_preserves_order_without_blank_rows(text, expected):
    from screen_translator.core.text import normalize_layout_text

    assert normalize_layout_text(text, "lines") == expected
    assert normalize_layout_text(text, "continuous") == normalize_text(text)


@pytest.mark.parametrize("source,direction", [
    ("Hello there.\nWhere is the train?", "en-zh"),
    ("你好。\n火车在哪里？", "zh-en"),
])
def test_two_dialogue_rows_reach_translator_and_result_separately(make_pipeline, source,
                                                               direction):
    from screen_translator.core.text import normalize_layout_text

    expected = normalize_layout_text(source, "lines")
    pipeline, _, _, translator, results, _ = make_pipeline({40: source})
    pipeline.start(REGION)
    wait_for(lambda: len(results) == 1)
    assert results[0].source == expected
    assert results[0].translation == "\n".join("译：" + part for part in expected.splitlines())
    assert results[0].direction == direction
    assert translator.calls == [(expected, direction)]
    assert translator.paragraphs == [(part, direction) for part in expected.splitlines()]


@pytest.mark.parametrize("source,direction", [
    ("Hello there.\nWhere is the train?", "en-zh"),
    ("你好。\n火车在哪里？", "zh-en"),
])
def test_real_translation_paragraph_loop_keeps_dialogue_boundaries(monkeypatch, source,
                                                                 direction):
    from screen_translator.inference.translation.ctranslate2_engine import CTranslate2Engine

    class CharacterTokenizer:
        def encode(self, text):
            return list(text) + ["</s>"]

    engine = CTranslate2Engine()
    engine._tokenizers[direction] = CharacterTokenizer()
    calls = []
    monkeypatch.setattr(engine, "_initialize", lambda requested: None)

    def translate_chunk(text, requested_direction, *, cancel_check=None):
        calls.append((text, requested_direction))
        return "译：" + text

    monkeypatch.setattr(engine, "_translate_chunk", translate_chunk)
    assert engine.translate(source, direction) == "\n".join(
        "译：" + part for part in source.splitlines())
    assert calls == [(part, direction) for part in source.splitlines()]


def test_continuous_mode_keeps_existing_soft_wrap_joining(make_pipeline):
    source = "The train leaves\nin ten minutes."
    expected = "The train leaves in ten minutes."
    pipeline, _, _, translator, results, _ = make_pipeline({40: source},
                                                          text_layout="continuous")
    pipeline.start(REGION)
    wait_for(lambda: len(results) == 1)
    assert translator.calls == [(expected, "en-zh")]
    assert results[0].source == expected
    assert results[0].translation == "译：" + expected


def test_moved_hard_boundary_is_not_deduplicated_by_same_flat_text(make_pipeline):
    sources = {40: "Take the\nblue door", 100: "Take\nthe blue door"}
    assert normalize_text(sources[40]) == normalize_text(sources[100])
    pipeline, screen, _, translator, results, _ = make_pipeline(sources)
    pipeline.start(REGION)
    wait_for(lambda: len(results) == 1)
    screen.set(100)
    wait_for(lambda: len(results) == 2)
    assert results[-1].source == sources[100]
    assert results[-1].translation == "译：Take\n译：the blue door"
    assert len(translator.calls) >= 2


def test_second_dialogue_line_change_updates_in_place_and_order(make_pipeline):
    sources = {40: "Wait near the station.\nThere are 10 tickets.",
               100: "Wait near the station.\nThere are 19 tickets."}
    pipeline, screen, _, _, results, _ = make_pipeline(sources)
    pipeline.start(REGION)
    wait_for(lambda: len(results) == 1)
    screen.set(100)
    wait_for(lambda: len(results) == 2)
    assert results[-1].source.splitlines() == sources[100].splitlines()
    assert results[-1].translation.splitlines() == [
        "译：Wait near the station.", "译：There are 19 tickets."]


def test_static_dialogue_and_cosmetic_noise_still_deduplicate(make_pipeline):
    sources = {40: "Hello, world!\nWhere is the train?",
               100: "Hello world.\nWhere is the train!",
               160: "Hello world.\nWhere is the train!"}
    pipeline, screen, ocr, translator, results, _ = make_pipeline(sources)
    pipeline.start(REGION)
    wait_for(lambda: len(results) == 1)
    initial_calls = len(translator.calls)
    threading.Event().wait(0.35)
    assert len(ocr.calls) == 1
    assert len(translator.calls) == initial_calls
    screen.set(100)
    wait_for(lambda: 100 in ocr.calls)
    screen.set(160)
    wait_for(lambda: 160 in ocr.calls)
    threading.Event().wait(0.25)
    assert len(results) == 1
    assert len(translator.calls) == initial_calls


def test_cache_keys_include_layout_and_are_not_legacy_flat_keys():
    model_id, direction, source = "dialogue-fake-en-zh", "en-zh", "Hello world"
    old_material = json.dumps([NORMALIZATION_VERSION, model_id, direction, source],
                              ensure_ascii=False, separators=(",", ":"))
    old_key = hashlib.sha256(old_material.encode("utf-8")).hexdigest()
    continuous = make_cache_key(model_id, direction, source, text_layout="continuous")
    lines = make_cache_key(model_id, direction, source, text_layout="lines")
    assert continuous != old_key
    assert lines != old_key
    assert lines != continuous
    assert make_cache_key(model_id, direction, "Hello\nworld", text_layout="lines") != lines
    assert make_cache_key(model_id, direction, source) == continuous


def test_old_flat_and_continuous_cache_do_not_replace_line_result(make_pipeline):
    source = "Hello there.\nWhere is the train?"
    flat = normalize_text(source)
    translator = Translator()
    cache = TranslationCache()
    model_id = translator.model_id("en-zh")
    legacy_material = json.dumps([NORMALIZATION_VERSION, model_id, "en-zh", flat],
                                 ensure_ascii=False, separators=(",", ":"))
    cache.put(hashlib.sha256(legacy_material.encode("utf-8")).hexdigest(),
              "Old incorrectly merged result")
    cache.put(make_cache_key(model_id, "en-zh", flat, text_layout="continuous"),
              "Continuous result")
    pipeline, _, _, translator, results, _ = make_pipeline({40: source}, translator=translator,
                                                          cache=cache)
    pipeline.start(REGION)
    wait_for(lambda: len(results) == 1)
    assert not results[0].cache_hit
    assert results[0].translation == "译：Hello there.\n译：Where is the train?"
    assert translator.calls
    pipeline.stop()
    pipeline.start(REGION)
    wait_for(lambda: len(results) == 2)
    assert results[-1].cache_hit
    assert results[-1].translation == results[0].translation


@pytest.mark.parametrize("action", ["clear", "stop"])
def test_clear_or_stop_during_line_translation_never_revives_old_rows(make_pipeline, action):
    translator = Translator(block_first=True)
    pipeline, screen, _, translator, results, _ = make_pipeline(
        {40: "Hello there.\nWhere is the train?", 100: "Take the bus.\nIt leaves soon."},
        translator=translator)
    pipeline.start(REGION)
    assert translator.entered.wait(3)
    getattr(pipeline, action)()
    translator.release.set()
    if action == "stop":
        wait_for(lambda: screen.closed == 1)
        threading.Event().wait(0.25)
        assert not results
    else:
        threading.Event().wait(0.4)
        assert results and all(not result.translation for result in results)
        screen.set(100)
        wait_for(lambda: any(result.source == "Take the bus.\nIt leaves soon." for result in results))
        assert results[-1].translation == "译：Take the bus.\n译：It leaves soon."


def test_layout_switch_restarts_and_drops_inflight_old_layout(make_pipeline):
    source = "Hello there.\nWhere is the train?"
    translator = Translator(block_first=True)
    pipeline, screen, _, translator, results, settings = make_pipeline(
        {40: source}, text_layout="continuous", translator=translator)
    pipeline.start(REGION)
    assert translator.entered.wait(3)
    old_generation = pipeline.generation
    pipeline.update_settings(replace(settings, text_layout="lines"))
    assert pipeline.generation > old_generation
    translator.release.set()
    wait_for(lambda: bool(results))
    assert all(result.generation == pipeline.generation for result in results)
    assert all(result.source == source for result in results)
    assert all(result.translation == "译：Hello there.\n译：Where is the train?" for result in results)
    wait_for(lambda: screen.closed >= 1)


def test_slow_result_with_same_words_but_new_boundaries_is_cancelled(make_pipeline):
    sources = {40: "Take the\nblue door", 100: "Take\nthe blue door"}
    translator = Translator(block_first=True, cancellable=True)
    pipeline, screen, _, translator, results, _ = make_pipeline(sources, translator=translator)
    pipeline.start(REGION)
    assert translator.entered.wait(3)
    screen.set(100)
    wait_for(lambda: pipeline._pending is not None)
    translator.release.set()
    wait_for(lambda: bool(results))
    assert translator.cancelled.is_set()
    assert all(result.source == sources[100] for result in results)
    assert results[-1].translation == "译：Take\n译：the blue door"


@pytest.mark.parametrize("stage", ["ocr", "freshness"])
def test_line_to_continuous_switch_during_ocr_discards_old_layout(make_pipeline, stage):
    sources = {40: "Hello there.\nWhere is the train?",
               100: "Take the bus.\nIt leaves soon."}

    class BlockingOCR(OCR):
        def __init__(self):
            super().__init__(sources)
            self.entered = threading.Event()
            self.release = threading.Event()
            self.block_value = 40 if stage == "ocr" else 100

        def recognize(self, image):
            value = int(image[0, 0, 0])
            if value == self.block_value and not self.entered.is_set():
                self.entered.set()
                assert self.release.wait(5), "Unreleased synthetic OCR"
            return super().recognize(image)

    ocr = BlockingOCR()
    translator = Translator(block_first=stage == "freshness")
    pipeline, screen, _, translator, results, settings = make_pipeline(
        sources, ocr=ocr, translator=translator)
    pipeline.start(REGION)
    if stage == "freshness":
        assert translator.entered.wait(3)
        screen.set(100)
        wait_for(lambda: pipeline._pending is not None)
        translator.release.set()
    assert ocr.entered.wait(3)
    old_generation = pipeline.generation
    pipeline.update_settings(replace(settings, text_layout="continuous"))
    assert pipeline.generation > old_generation
    ocr.release.set()
    wait_for(lambda: bool(results))
    expected = normalize_text(sources[40 if stage == "ocr" else 100])
    assert all(result.generation == pipeline.generation for result in results)
    assert all(result.source == expected for result in results)
    assert all(result.translation == "译：" + expected for result in results)
    if stage == "ocr":
        assert translator.calls == [(expected, "en-zh")]
    wait_for(lambda: screen.closed >= 1)


def test_trusted_identical_text_pixels_do_not_suppress_hard_boundary_change():
    class DirectPipeline(Pipeline):
        def _inference_loop(self):
            return

    translator = Translator()
    results = []
    pipeline = DirectPipeline(Settings(text_layout="lines"), OCR({}), translator,
                              TranslationCache(), results.append, lambda status: None)
    try:
        pipeline._inference_thread.join(1)
        assert not pipeline._inference_thread.is_alive()
        pipeline._running = True
        pipeline._generation = 1
        pipeline._session = 1
        image = np.full((32, 64, 3), 40, dtype=np.uint8)
        image[4:28:4, 5:60:5] = 230
        row_boxes = (((3, 2), (61, 2), (61, 14), (3, 14)),
                     ((3, 16), (61, 16), (61, 29), (3, 29)))

        def process(source):
            rows = tuple(TextLine(text, 0.99, box)
                         for text, box in zip(source.splitlines(), row_boxes))
            recognized = OCRResult(source, rows, 0.99)
            pipeline._process_frame(_Frame(image, pipeline.generation, time.monotonic(),
                                            recognized))
            pipeline._inflight_stage = ""

        process("Take the\nblue door")
        assert pipeline._trusted_boxes
        old_digest = pipeline._trusted_pixels.digest
        assert pipeline._trusted_text == "Take the\nblue door"
        process("Take\nthe blue door")
        assert pipeline._trusted_pixels.digest == old_digest
        assert [result.source for result in results] == ["Take the\nblue door", "Take\nthe blue door"]
        assert results[-1].translation == "译：Take\n译：the blue door"
        assert translator.calls == [("Take the\nblue door", "en-zh"),
                                    ("Take\nthe blue door", "en-zh")]
    finally:
        pipeline.shutdown(1)
