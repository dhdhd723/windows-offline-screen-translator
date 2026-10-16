"""Conservative OCR retry text guard; no screen or model inference is used."""

import math

import pytest

from screen_translator.core.ocr_overlap_text import (accept_overlap_text,
                                                      overlap_text_eligible)


def accept(fragments, candidate, confidence=0.99, baseline=0.99):
    return accept_overlap_text(fragments, candidate, confidence, baseline)


@pytest.mark.parametrize("fragments,candidate", [
    (["keep", "P you alert"], "keep you alert"),
    (["isa4", "4-player game"], "is a4-player game"),
    (["Before", "e you leave"], "Before you leave"),
    (["Use y", "your equipment"], "Use your equipment"),
    (["part c", "of the game"], "part of the game"),
    (["the", "e game"], "the game"),
    (["Ｕｓｅ ｙ", "your equipment"], "Use your equipment"),
    (["keep", "p you alert!"], "KEEP YOU ALERT!"),
])
def test_seam_local_deletions_of_single_letter_noise_are_accepted(fragments, candidate):
    assert overlap_text_eligible(fragments)
    assert accept(fragments, candidate)


@pytest.mark.parametrize("fragments,candidate", [
    (["Before", "eyou leave"], "Before you leave"),
    (["but will", "I you"], "but wil you"),
    (["will", "leave"], "wil leave"),
    (["very", "very cold"], "very cold"),
    (["no", "no way"], "no way"),
    (["I", "I agree"], "I agree"),
    (["a", "a word"], "a word"),
    (["is a 4", "4-player game"], "is a 4-player game"),
    (["11", "players"], "1 players"),
    (["1", "1 player"], "11 player"),
    (["1", "1 player"], "1 player"),
    (["will", "1 you leave"], "will you leave"),
    (["will", "1you leave"], "will you leave"),
    (["will", "Iknow?"], "will know?"),
    (["extra", "a cost"], "extra cost"),
    (["but will", "I you b", "be same?"], "but will you be same?"),
    (["therapist", "p says"], "the rapist says"),
    (["some", "p one here"], "someone here"),
    (["room I", "1 today"], "room I today"),
    (["room 1", "I today"], "room 1 today"),
    (["room1", "I today"], "room1 today"),
    (["roomI", "1 today"], "roomI today"),
    (["value 5", "0 today"], "value 50 today"),
    (["value 50", "today"], "value 5 today"),
    (["not", "now"], "now"),
    (["cannot", "not do it"], "cannot do it"),
    (["can't", "not do it"], "can not do it"),
    (["never", "leave"], "leave"),
    (["shouldn't", "leave"], "should leave"),
    (["keep", "p you alert"], "keep me alert"),
    (["keep", "p you alert"], "keep you very alert"),
    (["keep", "p you alert"], "keep you alert?"),
    (["keep", "p you alert!"], "keep you alert"),
    (["keep", "p you alert?"], "keep you alert!"),
    (["only c", "be careful"], "only be careful"),
    (["keep", "p p you alert"], "keep you alert"),
    (["p keep", "you alert"], "keep you alert"),
])
def test_meaning_numbers_repetitions_and_nonseam_characters_are_protected(fragments, candidate):
    assert not accept(fragments, candidate)


@pytest.mark.parametrize("fragments", [
    ["玩家A", "ty"], ["谢谢", "谢谢"], ["user_11", "joined"],
    ["@someone", "hello"], ["#channel", "hello"], ["$5", "today"],
    ["C:\\game", "file"], ["https://example.com", "hello"],
    ["example.com", "hello"], ["x == y", "now"], ["x + y", "now"],
    ["amount -5", "today"], ["a/b", "test"], ["array[1]", "test"],
    ["hello\nworld", "again"], ["hello\rworld", "again"],
    ["hello\u2028world", "again"], ["hello\x00", "world"],
    ["1", "1"], ["", "hello"], ["hello"], [], "hello", None,
    ["hello", 5], ["hello"] * 9, ["x" * 2049, "world"],
])
def test_nonprose_or_unsupported_input_is_ineligible(fragments):
    assert not overlap_text_eligible(fragments)
    assert not accept(fragments, "hello world")


@pytest.mark.parametrize("score,baseline", [
    (0.849, 0.90), (0.90, 0.981), (math.nan, 0.99), (math.inf, 0.99),
    (0.99, math.nan), (0.99, math.inf), (-1, 0.99), (1.01, 0.99),
    (0.99, -1), (0.99, 1.01), (None, 0.99), ("bad", 0.99),
    (0.99, None), (0.99, "bad"), (True, 0.99), (0.99, False),
])
def test_bad_confidence_rejects_without_raising(score, baseline):
    assert not accept(["keep", "p you"], "keep you", score, baseline)


@pytest.mark.parametrize("score,baseline", [(0.85, 0.93), (0.91, 0.99), (0.99, 0.85)])
def test_exact_score_and_drop_boundaries_are_accepted(score, baseline):
    assert accept(["keep", "p you"], "keep you", score, baseline)


@pytest.mark.parametrize("candidate", ["", " ", None, 5, "keep\nyou", "keep\ryou",
                                       "keep\u2028you", "keep @you", "keep 你"])
def test_bad_candidate_is_rejected(candidate):
    assert not accept(["keep", "p you"], candidate)


def test_unchanged_text_is_not_a_correction_and_cannot_rewrite_whitespace():
    for fragments, candidate in [
        (["very", "very cold"], "very very cold"),
        (["no", "no way"], "no no way"),
        (["is a 4", "4-player game"], "is a 4 4-player game"),
        (["1", "1 player"], "1 1 player"),
        (["11", "players"], "11 players"),
        (["cannot", "not do it"], "cannot not do it"),
    ]:
        assert not accept(fragments, candidate)


@pytest.mark.parametrize("fragments,candidate", [
    (["Use", "your equipment"], "Use your equipment"),
    (["some", "one here"], "someone here"),
    (["therapist", "says"], "the rapist says"),
    (["a", "cost"], "acost"),
    (["I", "know"], "Iknow"),
])
def test_zero_deletion_candidates_never_rewrite_word_boundaries(fragments, candidate):
    assert not accept(fragments, candidate)
