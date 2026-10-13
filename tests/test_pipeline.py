from __future__ import annotations

import threading
import time
from dataclasses import replace

import numpy as np
import pytest

from screen_translator.contracts import OCRResult, Region, Settings, TextLine
from screen_translator.core.pipeline import Pipeline
from screen_translator.inference import InferenceCancelled, InputLimitError, ModelFilesError
from screen_translator.storage.translation_cache import TranslationCache


def wait_for(predicate, timeout=4.0):
    deadline = time.monotonic() + timeout
    event = threading.Event()
    while time.monotonic() < deadline:
        if predicate():
            return
        event.wait(0.015)
    assert predicate(), "Timed out waiting for worker state"


class Screen:
    def __init__(self):
        self.value = 40
        self.image = None
        self.grabs = 0
        self.closed = 0
        self.owner_threads = []
        self._lock = threading.Lock()

    def set(self, value):
        with self._lock:
            self.value = value

    def backend(self):
        screen = self
        owner = threading.get_ident()
        screen.owner_threads.append(owner)

        class Backend:
            def grab(self, region):
                assert threading.get_ident() == owner
                with screen._lock:
                    screen.grabs += 1
                    if screen.image is not None:
                        return screen.image.copy()
                    return np.full((region.height, region.width, 3), screen.value, dtype=np.uint8)

            def close(self):
                assert threading.get_ident() == owner
                screen.closed += 1

        return Backend()


class OCR:
    def __init__(self, texts=None, block=False):
        self.texts = texts or {40: "Hello world", 100: "Good morning", 160: "Good evening", 220: "Good night", 0: ""}
        self.calls = []
        self.block = block
        self.entered = threading.Event()
        self.release = threading.Event()
        self.configurations = []

    def configure_threads(self, count):
        self.configurations.append((count, threading.get_ident()))

    def recognize(self, image):
        self.calls.append((int(image[0, 0, 0]), threading.get_ident()))
        self.entered.set()
        if self.block and len(self.calls) == 1:
            assert self.release.wait(5)
        value = int(image[0, 0, 0])
        return OCRResult(self.texts[value], confidence=0.99)


class Translator:
    def __init__(self, block=False):
        self.calls = []
        self.block = block
        self.entered = threading.Event()
        self.release = threading.Event()
        self.configurations = []

    def configure_threads(self, count):
        self.configurations.append((count, threading.get_ident()))

    def model_id(self, direction):
        return "fake-model-" + direction

    def translate(self, text, direction):
        self.calls.append((text, direction, threading.get_ident()))
        self.entered.set()
        if self.block and len(self.calls) == 1:
            assert self.release.wait(5)
        return "译：" + text


@pytest.fixture
def make_pipeline():
    instances = []

    def factory(ocr=None, translator=None, screen=None, settings=None):
        screen = screen or Screen()
        ocr = ocr or OCR()
        translator = translator or Translator()
        results, statuses = [], []
        settings = settings or Settings(capture_fps=12, idle_fps=6, debounce_ms=80,
                                        min_ocr_interval_ms=200)
        pipeline = Pipeline(settings, ocr, translator, TranslationCache(), results.append,
                            statuses.append, screen.backend)
        instances.append((pipeline, ocr, translator))
        return pipeline, screen, ocr, translator, results, statuses

    yield factory
    for pipeline, ocr, translator in instances:
        ocr.release.set()
        translator.release.set()
        pipeline.shutdown(2)


def test_static_frames_translate_once_and_stop_closes_capture(make_pipeline):
    pipeline, screen, ocr, translator, results, _ = make_pipeline()
    pipeline.start(Region(-120, 0, 64, 32))
    wait_for(lambda: len(results) == 1)
    threading.Event().wait(0.5)
    assert len(ocr.calls) == len(translator.calls) == 1
    assert results[0].generation == pipeline.generation
    assert ocr.calls[0][1] == translator.calls[0][2]
    assert ocr.calls[0][1] != screen.owner_threads[0]
    pipeline.stop()
    wait_for(lambda: screen.closed == 1)
    grabs = screen.grabs
    threading.Event().wait(0.2)
    assert screen.grabs == grabs
    assert not pipeline.is_running


def test_restart_uses_exact_cache_without_second_translation(make_pipeline):
    pipeline, screen, ocr, translator, results, _ = make_pipeline()
    region = Region(0, 0, 64, 32)
    pipeline.start(region)
    wait_for(lambda: len(results) == 1)
    pipeline.stop()
    pipeline.start(region)
    wait_for(lambda: len(results) == 2)
    assert len(translator.calls) == 1
    assert results[-1].cache_hit


def test_clear_suppresses_same_text_then_allows_new_source(make_pipeline):
    pipeline, screen, ocr, translator, results, _ = make_pipeline()
    pipeline.start(Region(0, 0, 64, 32))
    wait_for(lambda: len(results) == 1)
    pipeline.clear()
    cleared_generation = pipeline.generation
    wait_for(lambda: len(ocr.calls) >= 2)
    assert results[-1].translation == ""
    assert results[-1].generation == cleared_generation
    assert len(translator.calls) == 1
    screen.set(100)
    wait_for(lambda: results[-1].source == "Good morning")
    assert results[-1].generation == pipeline.generation


@pytest.mark.parametrize("stage", ["ocr", "translation"])
def test_clear_during_native_inference_discards_old_result(make_pipeline, stage):
    ocr = OCR(block=stage == "ocr")
    translator = Translator(block=stage == "translation")
    pipeline, screen, ocr, translator, results, _ = make_pipeline(ocr, translator)
    pipeline.start(Region(0, 0, 64, 32))
    engine = ocr if stage == "ocr" else translator
    assert engine.entered.wait(3)
    pipeline.clear()
    engine.release.set()
    wait_for(lambda: len(ocr.calls) >= 2)
    threading.Event().wait(0.25)
    assert all(not result.translation for result in results)
    screen.set(100)
    wait_for(lambda: any(result.source == "Good morning" for result in results))


def test_stop_during_translation_never_publishes_late_result(make_pipeline):
    translator = Translator(block=True)
    pipeline, screen, ocr, translator, results, _ = make_pipeline(translator=translator)
    pipeline.start(Region(0, 0, 64, 32))
    assert translator.entered.wait(3)
    pipeline.stop()
    translator.release.set()
    wait_for(lambda: screen.closed == 1)
    threading.Event().wait(0.2)
    assert not results


def test_mailbox_replaces_old_waiting_frames_with_latest(make_pipeline):
    ocr = OCR(block=True)
    pipeline, screen, ocr, translator, results, _ = make_pipeline(ocr=ocr)
    pipeline.start(Region(0, 0, 64, 32))
    assert ocr.entered.wait(3)
    for value in (100, 160, 220):
        screen.set(value)
        threading.Event().wait(0.32)
    ocr.release.set()
    wait_for(lambda: any(result.source == "Good night" for result in results))
    assert [value for value, _ in ocr.calls][:2] == [40, 220]
    assert not any(result.source in {"Good morning", "Good evening"} for result in results)
    assert not any(result.source == "Hello world" for result in results)


def test_slow_translation_never_publishes_ocr_confirmed_stale_source(make_pipeline):
    translator = Translator(block=True)
    pipeline, screen, ocr, translator, results, _ = make_pipeline(translator=translator)
    pipeline.start(Region(0, 0, 64, 32))
    assert translator.entered.wait(3)
    screen.set(100)
    wait_for(lambda: pipeline._pending is not None)
    translator.release.set()
    wait_for(lambda: any(result.source == "Good morning" for result in results))
    assert not any(result.source == "Hello world" for result in results)
    assert [value for value, _ in ocr.calls][:2] == [40, 100]


def test_slow_translation_confirms_near_match_before_discarding_old_source(make_pipeline):
    translator = Translator(block=True)
    texts = {40: "The quick brown fox jumps over the lazy dog.",
             100: "The quick brown fox jumps over the lazy dogs."}
    pipeline, screen, ocr, translator, results, _ = make_pipeline(ocr=OCR(texts), translator=translator)
    pipeline.start(Region(0, 0, 64, 32))
    assert translator.entered.wait(3)
    screen.set(100)
    wait_for(lambda: pipeline._pending is not None)
    translator.release.set()
    wait_for(lambda: any(result.source == texts[100] for result in results))
    assert not any(result.source == texts[40] for result in results)
    assert len([value for value, _ in ocr.calls if value == 100]) >= 2


def test_background_change_during_slow_translation_does_not_starve_result(make_pipeline):
    translator = Translator(block=True)
    ocr = OCR({40: "Hello world", 100: "Hello world", 160: "Hello world"})
    pipeline, screen, ocr, translator, results, _ = make_pipeline(ocr=ocr, translator=translator)
    pipeline.start(Region(0, 0, 64, 32))
    assert translator.entered.wait(3)
    screen.set(100)
    wait_for(lambda: pipeline._pending is not None)
    translator.release.set()
    wait_for(lambda: len(results) == 1)
    screen.set(160)
    wait_for(lambda: any(value == 160 for value, _ in ocr.calls))
    assert results[0].source == "Hello world"
    assert len(translator.calls) == 1


def test_long_translation_cooperatively_cancels_after_source_confirmation(make_pipeline):
    class ChunkedTranslator(Translator):
        def __init__(self):
            super().__init__()
            self.first_chunk = threading.Event()
            self.completed_chunks = []

        def translate_cancellable(self, text, direction, cancel_check):
            self.calls.append((text, direction, threading.get_ident()))
            for chunk in range(3):
                if cancel_check():
                    raise InferenceCancelled()
                self.completed_chunks.append((text, chunk))
                if text == "Hello world" and chunk == 0:
                    self.first_chunk.set()
                    assert self.release.wait(5)
            return "译：" + text

    translator = ChunkedTranslator()
    pipeline, screen, ocr, translator, results, statuses = make_pipeline(translator=translator)
    pipeline.start(Region(0, 0, 64, 32))
    assert translator.first_chunk.wait(3)
    screen.set(100)
    wait_for(lambda: pipeline._pending is not None)
    translator.release.set()
    wait_for(lambda: any(result.source == "Good morning" for result in results))
    assert translator.completed_chunks.count(("Hello world", 0)) == 1
    assert ("Hello world", 1) not in translator.completed_chunks
    assert not any(result.source == "Hello world" for result in results)
    assert not any("自动重试" in status for status in statuses)


@pytest.mark.parametrize("action", ["stop", "clear"])
def test_clear_or_stop_during_freshness_ocr_never_revives_subtitle(make_pipeline, action):
    class BlocksFreshness(OCR):
        def __init__(self):
            super().__init__()
            self.freshness_entered = threading.Event()
            self.freshness_release = threading.Event()

        def recognize(self, image):
            if int(image[0, 0, 0]) == 100 and not self.freshness_entered.is_set():
                self.freshness_entered.set()
                assert self.freshness_release.wait(5)
            return super().recognize(image)

    translator = Translator(block=True)
    pipeline, screen, ocr, translator, results, _ = make_pipeline(ocr=BlocksFreshness(), translator=translator)
    pipeline.start(Region(0, 0, 64, 32))
    assert translator.entered.wait(3)
    screen.set(100)
    wait_for(lambda: pipeline._pending is not None)
    translator.release.set()
    assert ocr.freshness_entered.wait(3)
    getattr(pipeline, action)()
    ocr.freshness_release.set()
    if action == "clear":
        wait_for(lambda: any(value == 100 for value, _ in ocr.calls))
        threading.Event().wait(0.4)
    else:
        wait_for(lambda: screen.closed == 1)
    assert all(not result.translation for result in results)


def test_blank_screen_requires_confirmation_then_clears_subtitle(make_pipeline):
    pipeline, screen, ocr, translator, results, statuses = make_pipeline()
    pipeline.start(Region(0, 0, 64, 32))
    wait_for(lambda: len(results) == 1)
    screen.set(0)
    wait_for(lambda: len(results) >= 2 and results[-1].translation == "")
    assert results[-1].source == ""
    assert len([value for value, _ in ocr.calls if value == 0]) >= 2
    assert len(translator.calls) == 1
    assert len([status for status in statuses if "未识别到文字" in status]) == 1
    threading.Event().wait(0.5)
    assert len([status for status in statuses if "未识别到文字" in status]) == 1
    screen.set(100)
    wait_for(lambda: results[-1].source == "Good morning")
    assert statuses[-1] == "译文已更新，持续监控中"


@pytest.mark.parametrize("new", ["Balance is -100 dollars", "Balance is 100% dollars"])
def test_semantic_symbol_change_updates_subtitle(make_pipeline, new):
    texts = {40: "Balance is 100 dollars", 100: new}
    pipeline, screen, ocr, translator, results, _ = make_pipeline(ocr=OCR(texts))
    pipeline.start(Region(0, 0, 64, 32))
    wait_for(lambda: len(results) == 1)
    screen.set(100)
    wait_for(lambda: len(results) == 2)
    assert results[-1].source == new


def test_stable_near_matching_sentence_is_confirmed_not_ignored(make_pipeline):
    texts = {40: "The quick brown fox jumps over the lazy dog.",
             100: "The quick brown fox jumps over the lazy dogs."}
    pipeline, screen, ocr, translator, results, _ = make_pipeline(ocr=OCR(texts))
    pipeline.start(Region(0, 0, 64, 32))
    wait_for(lambda: len(results) == 1)
    screen.set(100)
    wait_for(lambda: len(results) == 2)
    assert len([value for value, _ in ocr.calls if value == 100]) >= 2
    assert results[-1].source.endswith("dogs.")


def test_ui_settings_do_not_restart_capture_or_duplicate_inference(make_pipeline):
    settings = Settings(capture_fps=12, idle_fps=6, debounce_ms=80, min_ocr_interval_ms=200)
    pipeline, screen, ocr, translator, results, _ = make_pipeline(settings=settings)
    pipeline.start(Region(0, 0, 64, 32))
    wait_for(lambda: len(results) == 1)
    generation = pipeline.generation
    pipeline.update_settings(replace(settings, font_size=30, opacity=0.6, show_source=True))
    threading.Event().wait(0.3)
    assert pipeline.generation == generation
    assert len(ocr.calls) == len(translator.calls) == 1
    assert len(screen.owner_threads) == 1


def test_cpu_configuration_runs_only_on_inference_thread(make_pipeline):
    settings = Settings(capture_fps=12, idle_fps=6, debounce_ms=80, min_ocr_interval_ms=200)
    pipeline, screen, ocr, translator, results, _ = make_pipeline(settings=settings)
    pipeline.start(Region(0, 0, 64, 32))
    wait_for(lambda: len(results) == 1)
    pipeline.update_settings(replace(settings, cpu_threads=3))
    wait_for(lambda: len(ocr.configurations) >= 2 and len(translator.configurations) >= 2)
    assert [count for count, _ in ocr.configurations] == [2, 3]
    assert all(owner == ocr.calls[0][1] for _, owner in ocr.configurations + translator.configurations)


def test_tiny_localized_digit_edit_in_large_region_is_not_missed(make_pipeline):
    screen = Screen()
    screen.image = np.full((1440, 2560, 3), 40, dtype=np.uint8)
    ocr = OCR({40: "Remaining 10 seconds before launch", 100: "Remaining 19 seconds before launch"})
    pipeline, screen, ocr, translator, results, _ = make_pipeline(ocr=ocr, screen=screen)
    pipeline.start(Region(0, 0, 2560, 1440))
    wait_for(lambda: len(results) == 1)
    with screen._lock:
        # Four physical pixels are below the coarse perceptual gate. The
        # changed checksum becomes eligible once the new frame is stable.
        screen.image[0:2, 0:2] = 100
    wait_for(lambda: len(results) == 2)
    assert "19" in results[-1].source
    assert len(translator.calls) == 2


def test_new_text_outside_previous_boxes_gets_stable_full_frame_check(make_pipeline):
    class BoxedOCR(OCR):
        def recognize(self, image):
            self.calls.append((int(image[0, 0, 0]), threading.get_ident()))
            moved = image[-1, -1, 0] == 100
            text = "Good morning" if moved else "Hello world"
            box = ((0, 0), (20, 0), (20, 12), (0, 12))
            return OCRResult(text, (TextLine(text, 0.99, box),), 0.99)

    screen = Screen()
    screen.image = np.full((320, 640, 3), 40, dtype=np.uint8)
    pipeline, screen, ocr, translator, results, _ = make_pipeline(ocr=BoxedOCR(), screen=screen)
    pipeline.start(Region(0, 0, 640, 320))
    wait_for(lambda: len(results) == 1)
    with screen._lock:
        screen.image[-2:, -2:] = 100
    wait_for(lambda: len(results) == 2, timeout=1.5)
    assert results[-1].source == "Good morning"


def test_transient_model_error_retries_without_waiting_for_new_text(make_pipeline):
    class FailsOnce(Translator):
        def translate(self, text, direction):
            result = super().translate(text, direction)
            if len(self.calls) == 1:
                raise RuntimeError("transient inference error")
            return result

    pipeline, screen, ocr, translator, results, statuses = make_pipeline(translator=FailsOnce())
    pipeline.start(Region(0, 0, 64, 32))
    wait_for(lambda: len(results) == 1)
    assert len(translator.calls) == 2
    assert any("自动重试" in status for status in statuses)


def test_permanent_input_error_waits_for_changed_text(make_pipeline):
    class TooLong(Translator):
        def translate(self, text, direction):
            super().translate(text, direction)
            if len(text) > 16000:
                raise InputLimitError("Please select a smaller source")
            return "译：" + text

    texts = {40: "Long source " * 1600, 100: "Good morning"}
    pipeline, screen, ocr, translator, results, statuses = make_pipeline(ocr=OCR(texts), translator=TooLong())
    pipeline.start(Region(0, 0, 64, 32))
    wait_for(lambda: any("暂不可用" in status for status in statuses))
    threading.Event().wait(1.0)
    assert len(ocr.calls) == len(translator.calls) == 1
    assert not any("自动重试" in status for status in statuses)
    assert not results
    screen.set(100)
    wait_for(lambda: len(results) == 1)
    assert results[0].source == "Good morning"


def test_permanent_model_error_retries_on_explicit_settings_change(make_pipeline):
    class MissingModel(OCR):
        repaired = False

        def recognize(self, image):
            self.calls.append((int(image[0, 0, 0]), threading.get_ident()))
            if not self.repaired:
                raise ModelFilesError("Local model is missing")
            return OCRResult("Hello world")

    settings = Settings(capture_fps=12, idle_fps=6, debounce_ms=80, min_ocr_interval_ms=200)
    pipeline, screen, ocr, translator, results, statuses = make_pipeline(ocr=MissingModel(), settings=settings)
    pipeline.start(Region(0, 0, 64, 32))
    wait_for(lambda: any("暂不可用" in status for status in statuses))
    threading.Event().wait(1.0)
    assert len(ocr.calls) == 1
    ocr.repaired = True
    pipeline.update_settings(replace(settings, cpu_threads=3))
    wait_for(lambda: len(results) == 1)
    assert len(ocr.calls) == 2
    assert results[0].source == "Hello world"
