"""Local rerecognition integration; no desktop, input injection or models."""
from types import SimpleNamespace

import numpy as np
import pytest

from screen_translator.inference.ocr.rapidocr_engine import MAX_OVERLAP_RETRIES, RapidOCREngine


def box(left, top, right, bottom):
    return ((left, top), (right, top), (right, bottom), (left, bottom))


def run(fragments, candidates=None, *, score=.99, shape=(600, 1800, 3), fail=False):
    class Native:
        def __init__(self):
            self.detections = []
            self.rereads = []

        def __call__(self, image, **kwargs):
            self.detections.append((image.shape, kwargs))
            return SimpleNamespace(txts=[item[0] for item in fragments],
                                   scores=[.99] * len(fragments),
                                   boxes=[item[1] for item in fragments])

        def recognize_txt(self, crops):
            self.rereads.append([crop.shape for crop in crops])
            if fail:
                raise RuntimeError("fixture native retry failed")
            values = candidates if candidates is not None else ["keep you on"] * len(crops)
            return SimpleNamespace(txts=values, scores=[score] * len(values))

    native = Native()
    engine = RapidOCREngine()
    engine._engine = native
    result = engine.recognize(np.zeros(shape, dtype=np.uint8))
    return result, native


def pair(top=40):
    return [("keep", box(20, top, 120, top + 50)), ("P you on", box(95, top, 260, top + 50))]


def test_confirmed_pixel_reread_changes_only_assembled_text_not_raw_evidence():
    fragments = pair()
    result, native = run(fragments)
    assert result.text == "keep you on"
    assert [(line.text, line.box) for line in result.lines] == fragments
    assert result.confidence == pytest.approx(.99)
    assert len(native.detections) == 1
    assert len(native.rereads) == 1
    assert native.rereads[0] == [(54, 244, 3)]
    assert native.detections[0][1]["use_det"] is True


def test_identical_strings_without_overlapping_pixels_never_reread():
    result, native = run([("keep", box(20, 40, 120, 90)),
                          ("P you on", box(140, 40, 300, 90))])
    assert result.text == "keep P you on"
    assert native.rereads == []


@pytest.mark.parametrize("candidate", ["keep on", "ke you on", "keep you 10 on", "keep you on?"])
def test_retry_must_not_drop_real_content_or_add_numbers_or_punctuation(candidate):
    result, native = run(pair(), [candidate])
    assert native.rereads
    assert result.text == "keep P you on"


@pytest.mark.parametrize("score,fail", [(.4, False), (float("nan"), False), (.99, True)])
def test_uncertain_or_failed_retry_keeps_successful_original_ocr(score, fail):
    result, _ = run(pair(), score=score, fail=fail)
    assert result.text == "keep P you on"


def test_partial_native_batch_result_is_not_applied():
    result, _ = run(pair(), [])
    assert result.text == "keep P you on"


def test_cjk_rows_do_not_trigger_latin_repair_or_merge_messages():
    result, native = run([("玩家甲", box(20, 40, 120, 90)),
                          ("你好", box(95, 40, 260, 90)),
                          ("玩家乙", box(20, 150, 120, 200))])
    assert result.text == "玩家甲 你好\n玩家乙"
    assert native.rereads == []


def test_different_rows_never_join_even_when_glyphs_repeat():
    result, native = run([("keep", box(20, 40, 120, 90)),
                          ("P you on", box(95, 150, 260, 200))])
    assert result.text == "keep\nP you on"
    assert native.rereads == []


def test_tiny_input_uses_physical_crop_coordinates_after_detection_upscale():
    # Native boxes are doubled by the existing tiny-ROI preprocessing.
    fragments = [(text, tuple((x * 2, y) for x, y in bounds)) for text, bounds in pair()]
    result, native = run(fragments, shape=(80, 320, 3))
    assert result.text == "keep you on"
    assert native.detections[0][0] == (160, 640, 3)
    assert native.rereads[0] == [(29, 244, 3)]
    assert result.lines[0].box[0] == (20, 20)


@pytest.mark.parametrize("shape", [(600, 1800), (600, 1800, 4)])
def test_grayscale_and_bgra_use_bgr_retry_crops(shape):
    result, native = run(pair(), shape=shape)
    assert result.text == "keep you on"
    assert native.rereads[0][0][-1] == 3


def test_global_retry_budget_and_single_batch_are_bounded():
    fragments = [part for index in range(MAX_OVERLAP_RETRIES + 1) for part in pair(40 + index * 100)]
    result, native = run(fragments, shape=(1600, 1800, 3))
    assert len(native.detections) == len(native.rereads) == 1
    assert len(native.rereads[0]) == MAX_OVERLAP_RETRIES
    assert result.text.splitlines() == ["keep you on"] * MAX_OVERLAP_RETRIES + ["keep P you on"]
