from __future__ import annotations

import threading
import time
from collections import deque

import numpy as np
import pytest

from screen_translator.contracts import OCRResult, Region, Settings, TextLine
from screen_translator.core.pipeline import Pipeline, _Frame
from screen_translator.core.text import is_meaningful_change
from screen_translator.inference import InferenceCancelled
from screen_translator.storage.translation_cache import TranslationCache


SOURCE = "The translation works offline."
NEAR = "The t translation works offline."
BASE_BOX = ((22, 37), (594, 37), (594, 93), (22, 93))


def result(text=SOURCE, *, split=False, outside=False, boxed=True):
    if not text or not boxed:
        return OCRResult(text, confidence=0.99)
    if split:
        lines = tuple(TextLine(part, 0.99, ((left, 37), (right, 37),
                                          (right, 93), (left, 93)))
                      for part, left, right in (("The", 22, 80),
                                               ("t translation works", 85, 450),
                                               ("offline.", 455, 594)))
    elif outside:
        lines = (TextLine(SOURCE, 0.99, BASE_BOX),
                 TextLine("t", 0.99, ((630, 37), (645, 37), (645, 93), (630, 93))))
    else:
        lines = (TextLine(text, 0.99, BASE_BOX),)
    return OCRResult(text, lines, confidence=0.99)


def image(shade=32, *, edit=False, outside_edit=False):
    value = np.full((130, 1080, 3), 32, dtype=np.uint8)
    # A stable synthetic text band. No real screen capture or private data.
    value[40:90:5, 24:592:9] = 240
    value[:14] = shade
    value[116:] = shade
    if edit:
        value[55:60, 120:125] = 140
    if outside_edit:
        value[40:90, 630:645] = 240
    return value


class OCR:
    def __init__(self):
        self.responses = deque()
        self.calls = 0

    def recognize(self, value):
        self.calls += 1
        assert self.responses, "Unexpected extra OCR: provide its independent response"
        return self.responses.popleft()


class Translator:
    def __init__(self):
        self.calls = []
        self.on_translate = None

    def model_id(self, direction):
        return "pixel-evidence-fake-" + direction

    def translate_cancellable(self, text, direction, cancel_check):
        self.calls.append(text)
        if self.on_translate is not None:
            self.on_translate(cancel_check)
        return "译：" + text


class DirectPipeline(Pipeline):
    """Exercise inference decisions deterministically without GUI/capture races.

    Production worker concurrency remains covered by test_pipeline.py. Only
    worker launch is disabled here; the ordinary frame-processing path runs.
    """

    def _inference_loop(self):
        return

    def _capture_loop(self, region, session, stop_event):
        with self._lock:
            self._capture_threads.discard(threading.current_thread())


@pytest.fixture
def pipeline():
    ocr, translator = OCR(), Translator()
    results, statuses = [], []
    instance = DirectPipeline(Settings(), ocr, translator, TranslationCache(),
                              results.append, statuses.append)
    instance._inference_thread.join(1)
    assert not instance._inference_thread.is_alive()
    instance._running = True
    instance._generation = 1
    instance._session = 1
    yield instance, ocr, translator, results, statuses
    instance.shutdown(1)


def process(pipeline, pixels, recognized, *, generation=None):
    pipeline._process_frame(_Frame(pixels, generation or pipeline.generation,
                                   time.monotonic(), recognized))
    # The production inference-loop finally block clears this field per frame.
    pipeline._inflight_stage = ""


def test_background_near_noise_preserves_text_geometry_and_does_not_publish(pipeline):
    instance, ocr, translator, results, _ = pipeline
    process(instance, image(), result())
    trusted_boxes = instance._trusted_boxes
    assert trusted_boxes == ((14, 31, 602, 99),)
    boxes_epoch = instance._boxes_epoch
    for shade in range(40, 240, 8):
        process(instance, image(shade), result(NEAR, split=True))
        process(instance, image(shade + 1), result())
    assert instance._last_observed == SOURCE
    assert instance._trusted_boxes == trusted_boxes
    assert instance._boxes == trusted_boxes
    assert instance._boxes_epoch == boxes_epoch
    assert translator.calls == [SOURCE]
    assert [item.source for item in results] == [SOURCE]
    assert ocr.calls == 0


def test_background_blank_noise_does_not_clear_or_replace_trusted_boxes(pipeline):
    instance, _, translator, results, statuses = pipeline
    process(instance, image(), result())
    for shade in (50, 90, 130, 170):
        process(instance, image(shade), result(""))
    assert instance._last_observed == instance._trusted_text == SOURCE
    assert instance._trusted_boxes == ((14, 31, 602, 99),)
    assert instance._blank_count == 0
    assert translator.calls == [SOURCE]
    assert [item.source for item in results] == [SOURCE]
    assert not any("未识别到文字" in item for item in statuses)


@pytest.mark.parametrize("interruption", [SOURCE, SOURCE + "!", ""])
def test_near_match_confirmation_counts_only_consecutive_observations(pipeline, interruption):
    instance, _, translator, results, _ = pipeline
    assert not is_meaningful_change(SOURCE, NEAR)
    process(instance, image(), result(boxed=False))
    process(instance, image(edit=True), result(NEAR, boxed=False))
    assert instance._candidate_count == 1
    process(instance, image(), result(interruption, boxed=False))
    process(instance, image(edit=True), result(NEAR, boxed=False))
    assert instance._candidate_count == 1
    assert translator.calls == [SOURCE]
    process(instance, image(edit=True), result(NEAR, boxed=False))
    assert translator.calls == [SOURCE, NEAR]
    assert [item.source for item in results] == [SOURCE, NEAR]


def test_real_small_pixel_edit_is_confirmed_and_updates_once(pipeline):
    instance, _, translator, results, _ = pipeline
    process(instance, image(), result())
    process(instance, image(edit=True), result(NEAR, split=True))
    assert instance._last_observed == SOURCE
    process(instance, image(edit=True), result(NEAR, split=True))
    process(instance, image(90, edit=True), result(NEAR, split=True))
    assert instance._last_observed == instance._trusted_text == NEAR
    assert translator.calls == [SOURCE, NEAR]
    assert [item.source for item in results] == [SOURCE, NEAR]


def test_rejected_pixel_noise_breaks_real_near_candidate_confirmation(pipeline):
    instance, _, translator, results, _ = pipeline
    process(instance, image(), result())
    process(instance, image(edit=True), result(NEAR, split=True))
    assert instance._candidate_count == 1
    process(instance, image(90), result(NEAR, split=True))
    assert instance._candidate_count == 0
    process(instance, image(edit=True), result(NEAR, split=True))
    assert instance._candidate_count == 1
    assert translator.calls == [SOURCE]
    assert [item.source for item in results] == [SOURCE]


@pytest.mark.parametrize("boundary", ["shape", "missing_box"])
def test_incomplete_pixel_evidence_falls_back_to_ordinary_confirmation(pipeline, boundary):
    instance, _, translator, results, _ = pipeline
    process(instance, image(), result())
    pixels = image(90)
    recognized = result(NEAR, boxed=False) if boundary == "missing_box" else result(NEAR)
    if boundary == "shape":
        pixels = np.pad(pixels, ((0, 1), (0, 0), (0, 0)), constant_values=32)
    process(instance, pixels, recognized)
    process(instance, pixels, recognized)
    assert translator.calls == [SOURCE, NEAR]
    assert [item.source for item in results] == [SOURCE, NEAR]


def test_real_blank_text_pixels_clear_only_after_confirmation(pipeline):
    instance, _, _, results, _ = pipeline
    process(instance, image(), result())
    blank = np.full((130, 1080, 3), 32, dtype=np.uint8)
    process(instance, blank, result(""))
    assert len(results) == 1
    assert instance._trusted_boxes
    process(instance, blank, result(""))
    assert [item.source for item in results] == [SOURCE, ""]
    assert not instance._trusted_boxes
    assert instance._trusted_pixels is None
    assert instance._last_observed == ""


@pytest.mark.parametrize("first,second", [
    ("The result is 10 units.", "The result is 11 units."),
    ("The result is +5 units.", "The result is -5 units."),
    ("The result is x > 5.", "The result is x < 5."),
])
def test_real_numeric_or_symbol_pixel_changes_bypass_near_noise_gate(pipeline, first, second):
    instance, _, translator, results, _ = pipeline
    assert is_meaningful_change(first, second)
    process(instance, image(), result(first))
    process(instance, image(edit=True), result(second))
    assert translator.calls == [first, second]
    assert [item.source for item in results] == [first, second]


def test_near_new_text_outside_trusted_boxes_is_not_suppressed(pipeline):
    instance, _, translator, results, _ = pipeline
    process(instance, image(), result())
    # Exact old-box pixels stay unchanged, but a genuinely new box is outside.
    new_image, new_result = image(outside_edit=True), result(NEAR, outside=True)
    process(instance, new_image, new_result)
    assert translator.calls == [SOURCE]
    process(instance, new_image, new_result)
    assert translator.calls == [SOURCE, NEAR]
    assert [item.source for item in results] == [SOURCE, NEAR]
    assert any(box[0] > 602 for box in instance._trusted_boxes)


def test_meaningful_text_change_with_stale_box_preserves_existing_behavior(pipeline):
    instance, _, translator, results, _ = pipeline
    changed_text = "A completely different dialogue."
    process(instance, image(), result())
    process(instance, image(outside_edit=True), result(changed_text))
    assert translator.calls == [SOURCE, changed_text]
    assert [item.source for item in results] == [SOURCE, changed_text]


@pytest.mark.parametrize("noise", ["near", "blank"])
def test_pending_background_noise_does_not_cancel_inflight_translation(pipeline, noise):
    instance, ocr, translator, results, _ = pipeline
    checks = []

    def during_translation(cancel_check):
        pending_result = result(NEAR, split=True) if noise == "near" else result("")
        instance._pending = _Frame(image(160), instance.generation,
                                   time.monotonic() + 1, pending_result)
        checks.append(cancel_check())

    translator.on_translate = during_translation
    process(instance, image(), result())
    assert checks == [False]
    assert instance._pending is None
    assert translator.calls == [SOURCE]
    assert [item.source for item in results] == [SOURCE]
    assert ocr.calls == 0
    assert instance._trusted_boxes == ((14, 31, 602, 99),)


@pytest.mark.parametrize("noise", ["near", "blank"])
def test_first_frame_provisional_pixels_reject_pending_noise_before_baseline_committed(pipeline, noise):
    instance, ocr, translator, results, _ = pipeline
    pending_result = result(NEAR, split=True) if noise == "near" else result("")
    instance._pending = _Frame(image(160), instance.generation,
                               time.monotonic() + 1, pending_result)
    assert not instance._trusted_boxes
    process(instance, image(), result())
    assert instance._pending is None
    assert translator.calls == [SOURCE]
    assert [item.source for item in results] == [SOURCE]
    assert ocr.calls == 0


def test_pending_rechecks_pixel_evidence_after_independent_confirmation(pipeline):
    instance, ocr, translator, results, _ = pipeline
    ocr.responses.append(result(NEAR, split=True))
    # First OCR has no boxes, so it cannot prove noise yet. Its confirmation
    # supplies boxes wholly inside the unchanged baseline and must not cancel.
    instance._pending = _Frame(image(160), instance.generation,
                               time.monotonic() + 1, result(NEAR, boxed=False))
    process(instance, image(), result())
    assert instance._pending is None
    assert translator.calls == [SOURCE]
    assert [item.source for item in results] == [SOURCE]
    assert ocr.calls == 1


@pytest.mark.parametrize("outside", [False, True])
def test_pending_real_near_edit_cancels_old_translation_and_keeps_new_candidate(pipeline, outside):
    instance, ocr, translator, results, _ = pipeline
    new_image = image(outside_edit=True) if outside else image(edit=True)
    new_result = result(NEAR, outside=True) if outside else result(NEAR, split=True)
    ocr.responses.append(new_result)
    checks = []

    def during_translation(cancel_check):
        instance._pending = _Frame(new_image, instance.generation,
                                   time.monotonic() + 1, new_result)
        checks.append(cancel_check())
        if checks[-1]:
            raise InferenceCancelled()

    translator.on_translate = during_translation
    with pytest.raises(InferenceCancelled):
        process(instance, image(), result())
    assert checks == [True]
    assert results == []
    assert instance._pending is not None
    pending = instance._pending
    instance._pending = None
    translator.on_translate = None
    instance._process_frame(pending)
    assert [item.source for item in results] == [NEAR]
    assert translator.calls == [SOURCE, NEAR]
    assert ocr.calls == 1


def test_clear_preserves_pixel_evidence_and_does_not_revive_noisy_baseline(pipeline):
    instance, _, translator, results, _ = pipeline
    process(instance, image(), result())
    instance.clear()
    for recognized in (result(NEAR, split=True), result(""), result()):
        process(instance, image(100), recognized)
    assert [item.source for item in results] == [SOURCE, ""]
    assert translator.calls == [SOURCE]
    assert instance._trusted_text == SOURCE
    process(instance, image(edit=True), result(NEAR, split=True))
    process(instance, image(edit=True), result(NEAR, split=True))
    assert [item.source for item in results] == [SOURCE, "", NEAR]


def test_clear_during_ocr_baseline_ignores_noise_before_consuming_suppress_next(pipeline):
    instance, _, translator, results, _ = pipeline
    process(instance, image(), result())
    instance._inflight_stage = "ocr"
    instance.clear()
    process(instance, image(100), result(NEAR, split=True))
    assert instance._suppress_next
    process(instance, image(100), result())
    assert not instance._suppress_next
    assert [item.source for item in results] == [SOURCE, ""]
    assert translator.calls == [SOURCE]


def test_old_generation_frame_cannot_change_trusted_observation(pipeline):
    instance, _, translator, results, _ = pipeline
    old_generation = instance.generation
    process(instance, image(), result())
    instance.clear()
    process(instance, image(edit=True), result(NEAR), generation=old_generation)
    assert instance._last_observed == instance._trusted_text == SOURCE
    assert [item.source for item in results] == [SOURCE, ""]
    assert translator.calls == [SOURCE]


def test_start_discards_old_region_pixel_evidence(pipeline):
    instance, _, _, _, _ = pipeline
    process(instance, image(), result())
    assert instance._trusted_boxes
    instance.start(Region(0, 0, 1080, 130))
    assert instance._last_observed == instance._trusted_text == ""
    assert instance._trusted_boxes == ()
    assert instance._trusted_pixels is None
    assert instance._trusted_shape is None
