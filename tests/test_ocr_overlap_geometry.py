"""Geometry-only overlap planning: no OCR model or desktop capture."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from math import inf, nan

import pytest

from screen_translator.contracts import TextLine
from screen_translator.core.ocr_overlap import OverlapGroup, plan_overlap_groups


def line(left, top, right, bottom, text="word", confidence=.99):
    return TextLine(text, confidence, ((left, top), (right, top),
                                      (right, bottom), (left, bottom)))


def test_strong_pair_preserves_input_and_reports_union_physical_bounds():
    row = [line(10, 20, 110, 60, "keep"), line(85, 22, 210, 62, "P you")]
    before = tuple(row)
    assert plan_overlap_groups(row) == (OverlapGroup((0, 1), (10., 20., 210., 62.)),)
    assert tuple(row) == before


def test_weak_left_neighbor_joins_strong_pair_as_one_triplet():
    row = [line(1030, 296, 1166, 341, "but will"),
           line(1153, 290, 1265, 346, "I you b"),
           line(1235, 292, 1484, 343, "be the same?")]
    assert plan_overlap_groups(row) == (
        OverlapGroup((0, 1, 2), (1030., 290., 1484., 346.)),)


def test_weak_right_neighbor_can_join_seed():
    row = [line(0, 10, 100, 50), line(75, 10, 175, 50), line(166, 10, 266, 50)]
    assert plan_overlap_groups(row)[0].indices == (0, 1, 2)


def test_weak_overlaps_alone_never_seed_a_retry():
    assert plan_overlap_groups([line(0, 0, 100, 40), line(90, 0, 190, 40),
                                line(180, 0, 280, 40)]) == ()


def test_expansion_prefers_stronger_seam_and_caps_at_three_boxes():
    row = [line(0, 0, 100, 40), line(90, 0, 190, 40),
           line(165, 0, 265, 40), line(250, 0, 350, 40)]
    assert plan_overlap_groups(row)[0].indices == (1, 2, 3)


def test_equal_expansion_strengths_choose_left_deterministically():
    row = [line(0, 0, 100, 40), line(90, 0, 190, 40),
           line(165, 0, 265, 40), line(255, 0, 355, 40)]
    expected = (OverlapGroup((0, 1, 2), (0., 0., 265., 40.)),)
    assert plan_overlap_groups(row) == expected
    assert plan_overlap_groups(tuple(row)) == expected


def test_groups_never_reuse_a_box_in_a_strong_chain():
    row = [line(index * 70, 0, index * 70 + 100, 40) for index in range(7)]
    groups = plan_overlap_groups(row)
    flattened = [index for group in groups for index in group.indices]
    assert len(flattened) == len(set(flattened))
    assert all(2 <= len(group.indices) <= 3 for group in groups)
    assert flattened == sorted(flattened)


@pytest.mark.parametrize("second", [
    line(101, 20, 201, 60),
    line(100, 20, 200, 60),
    line(75, 65, 175, 105),
    line(75, 40, 175, 80),
    line(75, 38, 175, 78),
    line(75, 10, 175, 80),
])
def test_disjoint_or_different_baseline_boxes_do_not_merge(second):
    assert plan_overlap_groups([line(0, 20, 100, 60, "no"), second]) == ()


def test_identical_text_on_two_rows_stays_separate():
    assert plan_overlap_groups([line(0, 20, 100, 60, "no no"),
                                line(0, 70, 100, 110, "no no")]) == ()


def test_chain_cannot_drift_onto_another_baseline():
    # Adjacent centres are close enough, but first/last differ by 16/40 px.
    row = [line(0, 0, 100, 40), line(75, 8, 175, 48), line(150, 16, 250, 56)]
    assert plan_overlap_groups(row) == (OverlapGroup((0, 1), (0., 0., 175., 48.)),)


@pytest.mark.parametrize("box", [None, (), ((0, 0),),
    ((0, 0), (10, 0), (10, 0), (0, 0)),
    ((10, 0), (0, 0), (0, 40), (10, 40)),
    ((-1, 0), (99, 0), (99, 40), (-1, 40)),
    ((0, nan), (100, 0), (100, 40), (0, 40)),
    ((0, 0), (inf, 0), (100, 40), (0, 40)),
    ((0, 0), (1e200, 0), (1e200, 1e200), (0, 1e200)),
    ((0, 0), (100, 0), (0, 40), (100, 40)),
    ((0, 0), (100, 30), (100, 70), (0, 40)),
    ((0, 0), (100, 0), (100, 70), (0, 40)),
    ((0, 0), (100, 0), (100, 40), (0, 40), (0, 0)),
])
def test_missing_degenerate_nonfinite_negative_or_nonhorizontal_boxes_are_ineligible(box):
    assert plan_overlap_groups([TextLine("bad", .99, box), line(75, 0, 175, 40)]) == ()


def test_malformed_points_do_not_crash_planner():
    malformed = TextLine("bad", .99, ((0, 0), (100, 0), (100, 40), (None, 40)))
    assert plan_overlap_groups([malformed, line(75, 0, 175, 40)]) == ()


def test_near_horizontal_parallel_slopes_are_eligible_but_conflicting_slopes_are_not():
    first = TextLine("first", .99, ((0, 0), (100, 5), (100, 45), (0, 40)))
    compatible = TextLine("second", .99, ((75, 4), (175, 9), (175, 49), (75, 44)))
    conflicting = TextLine("second", .99, ((75, 8), (175, 3), (175, 43), (75, 48)))
    assert len(plan_overlap_groups([first, compatible])) == 1
    assert plan_overlap_groups([first, conflicting]) == ()


def test_excessively_wide_union_does_not_trigger_row_sized_recognition():
    assert plan_overlap_groups([line(0, 0, 400, 20), line(300, 0, 700, 20)]) == ()


def test_nested_or_unsorted_boxes_are_not_candidates():
    assert plan_overlap_groups([line(0, 0, 200, 40), line(75, 0, 175, 40)]) == ()
    assert plan_overlap_groups([line(75, 0, 175, 40), line(0, 0, 100, 40)]) == ()


def test_text_and_confidence_have_no_influence_on_geometry_planning():
    boxes = [line(0, 0, 100, 40), line(75, 0, 175, 40)]
    varied = [TextLine("中文 foo_bar 11 11", .01, boxes[0].box),
              TextLine("no no !!!", float("nan"), boxes[1].box)]
    assert plan_overlap_groups(boxes) == plan_overlap_groups(varied)


def test_group_and_caller_caps_are_enforced():
    row = []
    for index in range(20):
        start = index * 300
        row.extend([line(start, 0, start + 100, 40),
                    line(start + 75, 0, start + 175, 40)])
    assert len(plan_overlap_groups(row)) == 12
    assert len(plan_overlap_groups(row, max_groups=1000)) == 12
    assert len(plan_overlap_groups(row, max_groups=2)) == 2
    assert plan_overlap_groups(row, max_groups=0) == ()
    assert plan_overlap_groups(row, max_groups=-1) == ()


@pytest.mark.parametrize("scale", [.25, .5, 1, 1.25, 2, 4])
def test_planning_is_scale_equivariant(scale):
    row = [line(1030, 296, 1166, 341), line(1153, 290, 1265, 346),
           line(1235, 292, 1484, 343)]
    scaled = [TextLine(item.text, item.confidence,
                       tuple((x * scale, y * scale) for x, y in item.box)) for item in row]
    expected = plan_overlap_groups(row)
    actual = plan_overlap_groups(scaled)
    assert [group.indices for group in actual] == [group.indices for group in expected]
    for first, second in zip(actual, expected):
        assert first.bounds == pytest.approx(tuple(value * scale for value in second.bounds))


@pytest.mark.parametrize("scale", [.001, .013, .1, .33, 1, 1.337, 20])
def test_exact_threshold_seed_remains_scale_equivariant(scale):
    row = [line(0, 0, 100 * scale, 40 * scale),
           line(80 * scale, 0, 180 * scale, 40 * scale)]
    assert [group.indices for group in plan_overlap_groups(row)] == [(0, 1)]


def test_groups_are_frozen_and_empty_rows_are_supported():
    assert plan_overlap_groups([]) == ()
    assert plan_overlap_groups([line(0, 0, 100, 40)]) == ()
    group = OverlapGroup((0, 1), (0., 0., 175., 40.))
    with pytest.raises(FrozenInstanceError):
        group.indices = (1, 2)
