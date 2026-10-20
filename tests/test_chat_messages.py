"""Synthetic OCR/message geometry; no desktop, user settings or game access."""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from screen_translator.contracts import OCRResult, TextLine
from screen_translator.core.chat_messages import assemble_chat_messages
from screen_translator.inference.ocr import RapidOCREngine


def row(text, left=10, top=10, right=350, bottom=30, confidence=0.99):
    return TextLine(text, confidence,
                    ((left, top), (right, top), (right, bottom), (left, bottom)))


def result(*rows):
    return OCRResult("\n".join(item.text for item in rows), rows, 0.99, rows)


def wrapped():
    return result(row("Alice: im low can u"),
                  row("cover me rn", 75, 34, 250, 54),
                  row("Bob: omw", 10, 60, 190, 80))


def test_named_hanging_continuation_preserves_next_speaker_and_raw_evidence():
    recognized = wrapped()
    before = recognized.lines
    assert assemble_chat_messages(recognized) == "Alice: im low can u cover me rn\nBob: omw"
    assert recognized.text == "Alice: im low can u\ncover me rn\nBob: omw"
    assert recognized.lines is before


def test_three_visual_rows_can_form_one_named_message():
    recognized = result(row("Alice: can u cover me"),
                        row("while i get meds", 75, 34, 310, 54),
                        row("pls im low", 77, 58, 230, 78))
    assert assemble_chat_messages(recognized) == "Alice: can u cover me while i get meds pls im low"


def test_each_new_identity_is_a_boundary_even_with_hanging_indentation():
    recognized = result(row("Alice: ty"), row("Bob: np", 75, 34, 240, 54))
    assert assemble_chat_messages(recognized) == recognized.text


def test_same_speaker_repeat_is_a_new_message_not_continuation():
    recognized = result(row("Alice: im low"), row("Alice: need meds", 75, 34, 340, 54))
    assert assemble_chat_messages(recognized) == recognized.text


def test_unnamed_rows_never_start_a_join_group():
    recognized = result(row("im low can u"), row("cover me", 75, 34, 250, 54))
    assert assemble_chat_messages(recognized) == recognized.text


def test_same_left_margin_is_ambiguous_even_after_a_wide_named_row():
    recognized = result(row("Alice: im low can u"), row("cover me", 10, 34, 300, 54))
    assert assemble_chat_messages(recognized) == recognized.text


def test_unmerged_windows_line_endings_remain_byte_identical():
    recognized = result(row("Alice: im low can u"), row("cover me", 10, 34, 300, 54))
    recognized = replace(recognized, text=recognized.text.replace("\n", "\r\n"))
    assert assemble_chat_messages(recognized) == recognized.text


def test_font_height_cannot_gradually_drift_into_another_text_style():
    recognized = result(row("Alice: can u cover me"),
                        row("while i get meds", 75, 34, 310, 61),
                        row("other heading", 75, 66, 310, 102))
    assert assemble_chat_messages(recognized) == (
        "Alice: can u cover me while i get meds\nother heading")


@pytest.mark.parametrize("field,value", [("enabled", False), ("text_layout", "continuous"),
                                        ("text_layout", "invalid")])
def test_explicit_opt_out_or_non_chat_layout_keeps_old_text(field, value):
    recognized = wrapped()
    assert assemble_chat_messages(recognized, **{field: value}) == recognized.text


def test_old_three_argument_ocr_contract_remains_compatible():
    recognized = wrapped()
    legacy = OCRResult(recognized.text, recognized.lines, 0.99)
    assert legacy.visual_rows == ()
    assert assemble_chat_messages(legacy) == recognized.text


@pytest.mark.parametrize("visual_rows", [(), (row("Alice: wrong"),),
                                        (row("Alice: wrong"), row("cover me"), row("Bob: omw"))])
def test_missing_or_stale_visual_text_cannot_replace_original_text(visual_rows):
    recognized = replace(wrapped(), visual_rows=visual_rows)
    assert assemble_chat_messages(recognized) == recognized.text


@pytest.mark.parametrize("bad_box", [(), ((1, 1),), ((1, 1), (1, 1), (1, 1), (1, 1)),
                                    ((-1, 34), (200, 34), (200, 54), (-1, 54)),
                                    ((float("nan"), 34), (200, 34), (200, 54), (75, 54)),
                                    ((75, 34), (float("inf"), 34), (200, 54), (75, 54)),
                                    ((75, 34, 0), (200, 34), (200, 54), (75, 54))])
def test_invalid_geometry_falls_back_without_mutation_or_error(bad_box):
    recognized = wrapped()
    broken = replace(recognized.visual_rows[1], box=bad_box)
    recognized = replace(recognized, visual_rows=(recognized.visual_rows[0], broken,
                                                recognized.visual_rows[2]))
    assert assemble_chat_messages(recognized) == recognized.text


@pytest.mark.parametrize("confidence", [0.40, 0.64, -1, float("nan"), float("inf"), 1.2])
def test_uncertain_confidence_is_not_used_to_change_message_boundaries(confidence):
    recognized = wrapped()
    rows = list(recognized.visual_rows)
    rows[1] = replace(rows[1], confidence=confidence)
    assert assemble_chat_messages(replace(recognized, visual_rows=tuple(rows))) == recognized.text


@pytest.mark.parametrize("continuation", [
    row("cover me", 20, 34, 250, 54),  # Insufficient indentation.
    row("cover me", 200, 34, 340, 54),  # Very deep unrelated column.
    row("cover me", 350, 34, 490, 54),  # Outside the named row.
    row("cover me", 75, 60, 250, 80),  # A separate paragraph / message gap.
    row("cover me", 75, 31, 250, 66),  # Different font / row height.
    row("cover me", 75, 20, 250, 40),  # Excessive vertical overlap.
    row("cover me", 75, 34, 800, 54),  # Row spanning another visual column.
])
def test_negative_geometric_evidence_keeps_boundary(continuation):
    recognized = result(row("Alice: im low can u"), continuation)
    assert assemble_chat_messages(recognized) == recognized.text


@pytest.mark.parametrize("ending", [".", "!", "?", '。', '！', '？', '."', "?')"])
def test_complete_sentence_does_not_absorb_unnamed_next_message(ending):
    recognized = result(row("Alice: im low" + ending), row("cover me", 75, 34, 250, 54))
    assert assemble_chat_messages(recognized) == recognized.text


def test_changed_continuation_indent_ends_named_group():
    recognized = result(row("Alice: can u cover me"),
                        row("while i get meds", 75, 34, 310, 54),
                        row("another message", 110, 58, 320, 78))
    assert assemble_chat_messages(recognized) == (
        "Alice: can u cover me while i get meds\nanother message")


def test_no_orphan_join_after_unaccepted_row():
    recognized = result(row("Alice: im low can u"),
                        row("unrelated", 10, 34, 250, 54),
                        row("cover me", 75, 58, 250, 78))
    assert assemble_chat_messages(recognized) == recognized.text


def test_geometry_order_disagreement_is_not_silently_reordered():
    recognized = result(row("Alice: im low can u", top=60, bottom=80),
                        row("cover me", 75, 34, 250, 54))
    assert assemble_chat_messages(recognized) == recognized.text


@pytest.mark.parametrize("source", ["12: 30", "123: 456", "https: //example.com", "C: /Games/file"])
def test_timestamps_and_paths_do_not_become_names(source):
    recognized = result(row(source), row("cover me", 75, 34, 250, 54))
    assert assemble_chat_messages(recognized) == recognized.text


def test_caller_parser_handles_multiword_names_without_circular_dependency():
    calls = []

    def parser(text):
        calls.append(text)
        return tuple(text.split(": ", 1)) if text.startswith(("Meat Puppy: ", "Guy Fieri: ")) else None

    recognized = result(row("Meat Puppy: im low can u"), row("cover me", 75, 34, 250, 54),
                        row("Guy Fieri: omw", 10, 60, 300, 80))
    assert assemble_chat_messages(recognized, prefix_parser=parser) == (
        "Meat Puppy: im low can u cover me\nGuy Fieri: omw")
    assert calls == recognized.text.splitlines()


@pytest.mark.parametrize("scale", [0.75, 1, 1.5, 2, 3])
def test_grouping_scales_with_physical_font_size_without_dpi_assumptions(scale):
    recognized = wrapped()
    rows = tuple(replace(item, box=tuple((x * scale, y * scale) for x, y in item.box))
                 for item in recognized.visual_rows)
    recognized = replace(recognized, visual_rows=rows)
    assert assemble_chat_messages(recognized) == "Alice: im low can u cover me rn\nBob: omw"


def fake_engine(fragments):
    engine = RapidOCREngine()
    output = SimpleNamespace(txts=[item.text for item in fragments],
                             scores=[item.confidence for item in fragments],
                             boxes=[item.box for item in fragments])
    engine._engine = lambda image, **kwargs: output
    return engine


def test_production_ocr_sorts_fragments_and_adds_visual_rows_without_changing_raw_lines():
    fragments = (row("cover me", 75, 34, 250, 54),
                 row("im low can u", 100, 11, 350, 30), row("Alice:", 10, 10, 90, 30))
    recognized = fake_engine(fragments).recognize(np.zeros((600, 1800, 3), dtype=np.uint8))
    assert recognized.text == "Alice: im low can u\ncover me"
    assert [item.text for item in recognized.lines] == ["Alice:", "im low can u", "cover me"]
    assert [item.text for item in recognized.visual_rows] == recognized.text.splitlines()
    assert recognized.visual_rows[0].box == row("", 10, 10, 350, 30).box
    assert assemble_chat_messages(recognized) == "Alice: im low can u cover me"


def test_visual_rows_use_accepted_reread_text_not_raw_overlap_fragments(monkeypatch):
    fragments = (row("Alice:", 10, 10, 90, 30), row("im loww", 85, 10, 350, 30),
                 row("can u cover me", 75, 34, 300, 54))
    engine = fake_engine(fragments)
    monkeypatch.setattr(engine, "_assemble_rows", lambda rows, image: ["Alice: im low", "can u cover me"])
    recognized = engine.recognize(np.zeros((600, 1800, 3), dtype=np.uint8))
    assert recognized.lines[1].text == "im loww"
    assert recognized.visual_rows[0].text == "Alice: im low"
    assert assemble_chat_messages(recognized) == "Alice: im low can u cover me"


def test_upsampled_ocr_returns_visual_row_coordinates_in_original_physical_pixels():
    recognized = fake_engine((row("Alice: hello", 20, 10, 500, 50),)).recognize(
        np.zeros((60, 300, 3), dtype=np.uint8))
    assert recognized.visual_rows[0].box == row("", 10, 5, 250, 25).box
    assert recognized.visual_rows[0].box == recognized.lines[0].box


def test_no_boxes_means_visual_text_is_available_but_grouping_declines_geometry():
    engine = RapidOCREngine()
    engine._engine = lambda image, **kwargs: SimpleNamespace(
        txts=["Alice: im low", "cover me"], scores=[0.99, 0.99], boxes=None)
    recognized = engine.recognize(np.zeros((600, 1800, 3), dtype=np.uint8))
    assert tuple(item.text for item in recognized.visual_rows) == tuple(recognized.text.splitlines())
    assert all(not item.box for item in recognized.visual_rows)
    assert assemble_chat_messages(recognized) == recognized.text
