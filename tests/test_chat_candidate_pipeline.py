"""Accepted fast-route worker integration with fabricated capture/OCR only.

These tests exercise real pipeline threads, cache keys and cancellation, not a
native model, desktop screen, global hotkeys, game or semantic translation QA.
"""
from __future__ import annotations

from dataclasses import replace
import threading
import time

import numpy as np
import pytest

from screen_translator.contracts import OCRResult, Region, Settings, TextLine
from screen_translator.core.pipeline import Pipeline
from screen_translator.diagnostics import no_network
from screen_translator.inference import InferenceCancelled, ModelFilesError
from screen_translator.inference.translation.ctranslate2_engine import CTranslate2Engine
from screen_translator.storage.translation_cache import TranslationCache


REGION = Region(0, 0, 500, 160)


def wait_for(predicate, timeout=4):
    deadline = time.monotonic() + timeout
    pause = threading.Event()
    while time.monotonic() < deadline:
        if predicate():
            return
        pause.wait(.01)
    assert predicate(), "Synthetic fast chat worker state timed out"


def row(text, left=10, top=10, right=450, bottom=30):
    return TextLine(text, .99, ((left, top), (right, top), (right, bottom), (left, bottom)))


def observed(first="hello can you", continuation="wait for me", second="please wait", *, indent=90):
    rows = (row("Alice: " + first), row(continuation, indent, 34, 380, 54),
            row("Bob: " + second, 10, 60, 350, 80))
    return OCRResult("\n".join(item.text for item in rows), rows, .99, rows)


class Screen:
    def __init__(self):
        self.value = 40
        self.grabs = 0
        self.closed = []
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
                    return np.full((region.height, region.width, 3), screen.value, dtype=np.uint8)

            def close(self):
                assert threading.get_ident() == owner
                screen.closed.append(owner)

        return Backend()


class OCR:
    def __init__(self, records):
        self.records = records
        self.calls = []

    def recognize(self, image):
        value = int(image[0, 0, 0])
        self.calls.append((value, threading.get_ident()))
        return self.records[value]


class Cache(TranslationCache):
    def __init__(self):
        super().__init__()
        self.puts = []

    def put(self, key, value):
        self.puts.append((key, value, threading.get_ident()))
        super().put(key, value)


class Translator:
    formats_simplified_output = True

    def __init__(self, *, block_first=False):
        self.mode = "fast"
        self.configurations = []
        self.direction_configurations = []
        self.thread_configurations = []
        self.calls = []
        self.forbidden_chat_calls = []
        self.closed = []
        self.block_first = block_first
        self.entered = threading.Event()
        self.release = threading.Event()
        self.cancelled = threading.Event()

    def configure_chat_mode(self, mode):
        assert mode == "fast", "Unaccepted research backend reached a worker"
        self.mode = mode
        self.configurations.append((mode, threading.get_ident()))

    def configure_direction(self, direction):
        self.direction_configurations.append((direction, threading.get_ident()))

    def configure_threads(self, count):
        self.thread_configurations.append((count, threading.get_ident()))

    def model_id(self, direction):
        # Keep one synthetic ID: the pipeline's policy, not backend naming,
        # must distinguish glossary and message-boundary cache semantics.
        return "same-synthetic-fast-model-" + direction

    def translate(self, text, direction):
        return self.translate_cancellable(text, direction, lambda: False)

    def translate_cancellable(self, text, direction, cancel_check):
        self.calls.append((text, direction, self.mode, threading.get_ident()))
        if self.block_first and len(self.calls) == 1:
            self.entered.set()
            assert self.release.wait(5), "Unreleased synthetic fast translation"
        if cancel_check():
            self.cancelled.set()
            raise InferenceCancelled()
        return "轻量译文：" + text

    def translate_chat(self, *args, **kwargs):
        self.forbidden_chat_calls.append((args, kwargs))
        raise AssertionError("Rejected enhanced interface must never be used")

    def close(self):
        self.closed.append(threading.get_ident())


@pytest.fixture
def make_pipeline():
    instances = []

    def create(records=None, *, mode="fast", slang=True, translator=None):
        settings = Settings(direction="en-zh", text_layout="lines", chat_translation_mode=mode,
                            chat_slang_enabled=slang, capture_fps=12, idle_fps=6,
                            debounce_ms=80, min_ocr_interval_ms=200)
        screen = Screen()
        ocr = OCR(records or {40: observed()})
        translator = translator or Translator()
        results, statuses = [], []
        cache = Cache()
        pipeline = Pipeline(settings, ocr, translator, cache, results.append, statuses.append, screen.backend)
        instances.append((pipeline, translator))
        return pipeline, screen, ocr, translator, cache, results, statuses, settings

    yield create
    for pipeline, translator in instances:
        translator.release.set()
        pipeline.shutdown(3)


@pytest.mark.parametrize("stored_mode", ["fast", "enhanced"])
def test_saved_research_mode_never_activates_rejected_backend(make_pipeline, stored_mode):
    pipeline, _, ocr, translator, _, results, _, _ = make_pipeline(mode=stored_mode)
    pipeline.start(REGION)
    wait_for(lambda: len(results) == 1)
    assert results[0].source == "Alice: hello can you wait for me\nBob: please wait"
    assert results[0].translation == (
        "Alice: 轻量译文：hello can you wait for me\nBob: 轻量译文：please wait")
    assert [call[0] for call in translator.calls] == ["hello can you wait for me", "please wait"]
    assert translator.forbidden_chat_calls == []
    assert all(call[2] == "fast" for call in translator.calls)
    inference_id = pipeline._inference_thread.ident
    assert all(call[-1] == inference_id for call in translator.calls + ocr.calls)
    assert all(owner == inference_id and mode == "fast" for mode, owner in translator.configurations)
    assert all(owner == inference_id for _, owner in translator.direction_configurations)


@pytest.mark.parametrize("slang", [True, False])
def test_title_case_display_names_never_enter_model_in_explicit_lines(make_pipeline, slang):
    original = observed()
    rows = (replace(original.visual_rows[0], text="Meat Puppy: hello can you"),
            original.visual_rows[1], replace(original.visual_rows[2], text="Guy Fieri: please wait"))
    record = OCRResult("\n".join(item.text for item in rows), rows, .99, rows)
    pipeline, _, _, translator, _, results, _, _ = make_pipeline({40: record}, slang=slang)
    pipeline.start(REGION)
    wait_for(lambda: len(results) == 1)
    assert results[0].source == "Meat Puppy: hello can you wait for me\nGuy Fieri: please wait"
    assert results[0].translation.startswith("Meat Puppy: 轻量译文：hello can you wait for me\nGuy Fieri: ")
    assert [call[0] for call in translator.calls] == ["hello can you wait for me", "please wait"]


@pytest.mark.parametrize("metadata", ["missing", "stale"])
def test_untrusted_geometry_keeps_explicit_rows_separate(make_pipeline, metadata):
    original = observed()
    visual = () if metadata == "missing" else (replace(original.visual_rows[0], text="wrong"),
                                               *original.visual_rows[1:])
    pipeline, _, _, translator, _, results, _, _ = make_pipeline({40: replace(original, visual_rows=visual)})
    pipeline.start(REGION)
    wait_for(lambda: len(results) == 1)
    assert results[0].source == original.text
    assert [call[0] for call in translator.calls] == ["hello can you", "wait for me", "please wait"]


def test_slang_off_disables_expansion_but_retains_identity_and_message_boundaries(make_pipeline):
    rows = (row("Meat Puppy: ty"), row("Guy Fieri: pls wait", 10, 40, 350, 60))
    record = OCRResult("\n".join(item.text for item in rows), rows, .99, rows)
    pipeline, _, _, translator, cache, results, _, settings = make_pipeline({40: record}, slang=False)
    pipeline.start(REGION)
    wait_for(lambda: len(results) == 1)
    assert results[0].source == record.text
    assert results[0].translation == "Meat Puppy: 轻量译文：ty\nGuy Fieri: 轻量译文：pls wait"
    assert [call[0] for call in translator.calls] == ["ty", "pls wait"]
    pipeline.update_settings(replace(settings, chat_slang_enabled=True))
    wait_for(lambda: len(results) == 2)
    assert not results[1].cache_hit
    assert results[1].translation.startswith("Meat Puppy: 谢谢\nGuy Fieri: ")
    assert translator.calls[-1][0] == "please wait"
    assert cache.puts[0][0] != cache.puts[1][0]
    assert translator.forbidden_chat_calls == []


def test_raw_mode_setting_changes_restart_safely_but_share_effective_fast_cache(make_pipeline):
    pipeline, _, _, translator, cache, results, _, settings = make_pipeline(mode="enhanced")
    pipeline.start(REGION)
    wait_for(lambda: len(results) == 1)
    assert not results[0].cache_hit
    generation, calls = pipeline.generation, len(translator.calls)
    pipeline.update_settings(replace(settings, chat_translation_mode="fast"))
    assert pipeline.generation > generation
    wait_for(lambda: len(results) == 2)
    assert results[1].cache_hit and results[1].translation == results[0].translation
    assert len(translator.calls) == calls and len(cache.puts) == 1
    assert [mode for mode, _ in translator.configurations] == ["fast", "fast"]
    assert translator.forbidden_chat_calls == []


@pytest.mark.parametrize("action", ["stop", "clear"])
def test_cancelled_result_is_never_published_or_cached(make_pipeline, action):
    translator = Translator(block_first=True)
    pipeline, _, _, translator, cache, results, _, _ = make_pipeline(translator=translator)
    pipeline.start(REGION)
    assert translator.entered.wait(3)
    getattr(pipeline, action)()
    translator.release.set()
    wait_for(lambda: translator.cancelled.is_set())
    assert cache.puts == []
    assert not any(result.translation for result in results)


def test_setting_change_discards_inflight_result_and_uses_new_policy_cache(make_pipeline):
    translator = Translator(block_first=True)
    pipeline, _, _, translator, cache, results, _, settings = make_pipeline(translator=translator)
    pipeline.start(REGION)
    assert translator.entered.wait(3)
    generation = pipeline.generation
    pipeline.update_settings(replace(settings, chat_slang_enabled=False))
    assert pipeline.generation > generation
    translator.release.set()
    wait_for(lambda: bool(results))
    assert translator.cancelled.is_set()
    assert all(result.generation == pipeline.generation for result in results)
    assert len(cache.puts) == 1


def test_new_visual_text_cancels_old_message_using_same_grouping_for_freshness(make_pipeline):
    translator = Translator(block_first=True)
    records = {40: observed(), 120: observed(first="the door is", continuation="on the left", second="come here")}
    pipeline, screen, _, translator, cache, results, _, _ = make_pipeline(records, translator=translator)
    pipeline.start(REGION)
    assert translator.entered.wait(3)
    screen.set(120)
    wait_for(lambda: pipeline._pending is not None)
    translator.release.set()
    wait_for(lambda: bool(results))
    assert translator.cancelled.is_set()
    assert all(result.source == "Alice: the door is on the left\nBob: come here" for result in results)
    assert len(cache.puts) == 1 and "hello" not in cache.puts[0][1]
    assert [call[0] for call in translator.calls][-2:] == ["the door is on the left", "come here"]


def test_geometry_change_with_same_visual_text_has_distinct_message_cache(make_pipeline):
    records = {40: observed(), 120: observed(indent=10)}
    assert records[40].text == records[120].text
    pipeline, screen, _, translator, cache, results, _, _ = make_pipeline(records)
    pipeline.start(REGION)
    wait_for(lambda: len(results) == 1)
    assert results[0].source == "Alice: hello can you wait for me\nBob: please wait"
    screen.set(120)
    wait_for(lambda: len(results) == 2)
    assert results[1].source == records[120].text and not results[1].cache_hit
    assert [call[0] for call in translator.calls][-3:] == ["hello can you", "wait for me", "please wait"]
    assert len(cache.puts) == 2 and cache.puts[0][0] != cache.puts[1][0]


def test_shutdown_closes_translator_once_on_inference_worker(make_pipeline):
    pipeline, screen, _, translator, _, results, _, _ = make_pipeline()
    pipeline.start(REGION)
    wait_for(lambda: bool(results))
    inference_id, caller_id = pipeline._inference_thread.ident, threading.get_ident()
    pipeline.shutdown(3)
    assert not pipeline._inference_thread.is_alive()
    assert translator.closed == [inference_id] and inference_id != caller_id
    assert len(screen.closed) == 1 and screen.closed[0] != inference_id
    pipeline.shutdown(3)
    assert translator.closed == [inference_id]


def test_idle_shutdown_never_captures_or_translates_and_closes_on_worker(make_pipeline):
    pipeline, screen, ocr, translator, cache, results, _, _ = make_pipeline()
    pipeline.shutdown(3)
    assert translator.closed == [pipeline._inference_thread.ident]
    assert screen.grabs == 0 and ocr.calls == [] and translator.calls == []
    assert translator.forbidden_chat_calls == [] and cache.puts == [] and results == []


@pytest.mark.parametrize("mode", ["enhanced", "", "cloud", None, 2])
def test_direct_backend_configuration_rejects_unaccepted_modes_without_allocating(tmp_path, mode):
    engine = CTranslate2Engine(tmp_path)
    with no_network() as attempts:
        with pytest.raises(ValueError):
            engine.configure_chat_mode(mode)
        assert engine._translators == {} and engine._tokenizers == {}
    assert attempts == []


def test_fast_backend_needs_only_local_weights_and_fails_missing_pack_without_network(tmp_path):
    engine = CTranslate2Engine(tmp_path)
    engine.configure_chat_mode("fast")
    assert not hasattr(engine, "_chat_engine")
    assert not hasattr(engine, "translate_chat")
    with no_network() as attempts:
        with pytest.raises(ModelFilesError):
            engine.translate("Hello there", "en-zh")
    assert attempts == [] and engine._translators == {} and engine._tokenizers == {}
    engine.close()
    engine.close()


def test_fast_backend_cancel_before_model_read_has_no_network_or_allocation(tmp_path):
    engine = CTranslate2Engine(tmp_path)
    with no_network() as attempts:
        with pytest.raises(InferenceCancelled):
            engine.translate_cancellable("Please wait", "en-zh", lambda: True)
    assert attempts == [] and engine._translators == {} and engine._tokenizers == {}
