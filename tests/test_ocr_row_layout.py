"""Synthetic OCR box grouping; no desktop capture or model loading is needed."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from screen_translator.inference.ocr import RapidOCREngine


def rectangle(left, top, right, bottom):
    return ((left, top), (right, top), (right, bottom), (left, bottom))


def recognize_fragments(fragments):
    """Exercise production recognize() after replacing only native inference."""
    engine = RapidOCREngine()
    output = SimpleNamespace(txts=[text for text, _, _ in fragments],
                             scores=[score for _, _, score in fragments],
                             boxes=[box for _, box, _ in fragments])
    engine._engine = lambda image, **kwargs: output
    image = np.zeros((600, 1800, 3), dtype=np.uint8)
    result = engine.recognize(image)
    # Grouping must not drop any recognized character, box or confidence.
    assert len(result.lines) == len(fragments)
    assert sorted((line.text, line.confidence, line.box) for line in result.lines) == sorted(
        (text, score, box) for text, box, score in fragments)
    expected_confidence = sum(score * len(text) for text, _, score in fragments) / sum(
        len(text) for text, _, _ in fragments)
    assert result.confidence == pytest.approx(expected_confidence)
    return result


def test_small_trailing_zero_detection_stays_on_second_dialogue_row():
    # Geometry observed in the failed owned-window two-line acceptance test.
    # The OCR label is preserved as '0'; grouping must not pretend it is '。'.
    fragments = [
        ("第二行文本", rectangle(508, 182, 933, 258), 0.99),
        ("0", rectangle(929, 231, 943, 244), 0.77),
        ("第一行文本", rectangle(508, 92, 933, 168), 0.98),
    ]
    result = recognize_fragments(fragments)
    assert result.text == "第一行文本\n第二行文本 0"
    assert [line.text for line in result.lines] == ["第一行文本", "第二行文本", "0"]


@pytest.mark.parametrize("token", [".", ",", "0"])
@pytest.mark.parametrize("gap", [-4, 8, 38])
def test_small_contained_off_center_fragment_within_gap_limit_joins_row(token, gap):
    fragments = [
        (token, rectangle(933 + gap, 231, 947 + gap, 244), 0.81),
        ("Dialogue text", rectangle(508, 182, 933, 258), 0.99),
    ]
    result = recognize_fragments(fragments)
    assert result.text == "Dialogue text " + token
    assert [line.text for line in result.lines] == ["Dialogue text", token]


def test_small_standalone_next_row_does_not_join_previous_dialogue():
    result = recognize_fragments([
        ("Dialogue text", rectangle(508, 182, 933, 258), 0.99),
        ("0", rectangle(929, 300, 943, 313), 0.90),
    ])
    assert result.text == "Dialogue text\n0"


@pytest.mark.parametrize("left", [972, 1050])
def test_far_horizontal_off_center_fragment_is_not_reclassified_as_same_row(left):
    # Center distance fails the original near-center rule. The new small-box
    # branch must reject a gap greater than half of the large box's height.
    result = recognize_fragments([
        ("Dialogue text", rectangle(508, 182, 933, 258), 0.99),
        ("0", rectangle(left, 231, left + 14, 244), 0.90),
    ])
    assert result.text == "Dialogue text\n0"


def test_small_fragment_crossing_bottom_edge_is_not_contained():
    result = recognize_fragments([
        ("Dialogue text", rectangle(508, 182, 933, 258), 0.99),
        ("0", rectangle(929, 250, 943, 270), 0.90),
    ])
    assert result.text == "Dialogue text\n0"


def test_off_center_fragment_above_small_height_ratio_does_not_join():
    result = recognize_fragments([
        ("Dialogue text", rectangle(508, 182, 933, 258), 0.99),
        ("field", rectangle(929, 222, 970, 258), 0.90),
    ])
    assert result.text == "Dialogue text\nfield"


def test_near_center_fragments_keep_left_to_right_sort_despite_detector_jitter():
    result = recognize_fragments([
        ("world", rectangle(200, 21, 290, 59), 0.99),
        ("!", rectangle(310, 23, 324, 58), 0.91),
        ("Hello", rectangle(20, 20, 120, 60), 0.99),
    ])
    assert result.text == "Hello world !"
    assert [line.text for line in result.lines] == ["Hello", "world", "!"]


def test_two_normal_stacked_dialogue_rows_remain_separate():
    result = recognize_fragments([
        ("Bottom row", rectangle(20, 82, 400, 132), 0.99),
        ("Top row", rectangle(20, 20, 400, 70), 0.99),
    ])
    assert result.text == "Top row\nBottom row"


def test_contained_small_box_returned_first_does_not_break_size_asymmetry():
    # Equal top coordinates preserve the detector's ordering before grouping,
    # so the tiny box can be the previous row anchor instead of the new item.
    result = recognize_fragments([
        ("(", rectangle(494, 182, 508, 195), 0.91),
        ("Dialogue text", rectangle(508, 182, 933, 258), 0.99),
    ])
    assert result.text == "( Dialogue text"
    assert [line.text for line in result.lines] == ["(", "Dialogue text"]


def test_small_trailing_fragment_can_join_the_neighboring_part_of_split_row():
    result = recognize_fragments([
        ("Hello", rectangle(20, 20, 120, 60), 0.99),
        ("world", rectangle(200, 21, 290, 59), 0.98),
        ("0", rectangle(289, 50, 302, 60), 0.81),
    ])
    assert result.text == "Hello world 0"
    assert [line.text for line in result.lines] == ["Hello", "world", "0"]
