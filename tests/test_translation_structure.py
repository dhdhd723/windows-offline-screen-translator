from __future__ import annotations

import random
import re

import pytest

from screen_translator.core.translation_structure import STRUCTURE_POLICY_ID, split_complete_sentences


@pytest.mark.parametrize("text", ["", " ", "\n\t\r", "\u3000"])
def test_empty_input(text):
    assert split_complete_sentences(text) == []


@pytest.mark.parametrize("text", [
    " Hello,  world! ",
    "Single sentence with no terminal punctuation",
    "\t Dr. Smith meets Mr. Jones. \n",
    "Wait... let me think.",
    "The U.S. Navy uses version 1.2.3.",
    "Visit https://example.com/a.b?q=x.y&ok=yes now.",
    "Visit https://example.com/? Next link is below.",
    "Visit https://example.com/path! Another ambiguous URL follows.",
    "Contact first.last@example.com or open settings.json.",
    "Read C:\\Games\\screen.translator\\settings.json now.",
    "Open /usr/local/bin/app.py or ./config/settings.json.",
    "A. Smith and J. R. R. Tolkien are names.",
    "Choose e.g. English or i.e. another language.",
    "The estimate is approx. 3.14 at 9 a.m. today.",
    "Ask Fig. 2 or No. 3, etc. Next step is uncertain.",
    "This is one sentence. lowercase continuation is ambiguous.",
])
def test_unsplit_text_is_unchanged_except_outer_whitespace(text):
    assert split_complete_sentences(text) == [text.strip()]


@pytest.mark.parametrize(("text", "expected"), [
    ("First sentence. Another follows! Done?", ["First sentence.", "Another follows!", "Done?"]),
    ("Question? yes. End.", ["Question?", "yes.", "End."]),
    ("What?! Really!! Done.", ["What?!", "Really!!", "Done."]),
    ('She said, "Go now." Then left.', ['She said, "Go now."', "Then left."]),
    ("他说：“出发！”然后离开。", ["他说：“出发！”", "然后离开。"]),
    ("第一句。第二句！第三句？结束", ["第一句。", "第二句！", "第三句？", "结束"]),
    ("First. “Second.” Third.", ["First.", "“Second.”", "Third."]),
    ("(First.) [Second!] Third.", ["(First.)", "[Second!]", "Third."]),
    ("你好.继续。Hello! 再见！", ["你好.", "继续。", "Hello!", "再见！"]),
    ("Gather paranormal evidence... Before you become part of the haunting yourself.",
     ["Gather paranormal evidence...", "Before you become part of the haunting yourself."]),
    ("You may leave... but will you be the same?", ["You may leave...", "but will you be the same?"]),
    ("Not yet… Before you go.", ["Not yet…", "Before you go."]),
    ("Not yet...\nperhaps later.", ["Not yet...", "perhaps later."]),
    ("First sentence.\nsecond sentence.", ["First sentence.", "second sentence."]),
    ("First sentence.\r\nsecond sentence.", ["First sentence.", "second sentence."]),
    ("He met Dr. Smith. It was late.", ["He met Dr. Smith.", "It was late."]),
    ("Use e.g. a meter. Then stop.", ["Use e.g. a meter.", "Then stop."]),
    ("The number is 3.14. The version is v1.2.3.",
     ["The number is 3.14.", "The version is v1.2.3."]),
    ("Visit https://example.com/a?x=y. Then stop.",
     ["Visit https://example.com/a?x=y.", "Then stop."]),
    ("Email first.last@example.com. Then stop.", ["Email first.last@example.com.", "Then stop."]),
    ("Open C:\\Games\\settings.json. Then stop.", ["Open C:\\Games\\settings.json.", "Then stop."]),
    ("Use \\\\server\\share\\file.txt. Then stop.", ["Use \\\\server\\share\\file.txt.", "Then stop."]),
    ("Read settings.json. Then stop.", ["Read settings.json.", "Then stop."]),
    ("1. First item. 2. Second item.", ["1. First item.", "2. Second item."]),
    ("- 1. First item. 2. Second item.", ["- 1. First item.", "2. Second item."]),
])
def test_clear_sentence_boundaries(text, expected):
    assert split_complete_sentences(text) == expected
    assert re.sub(r"\s", "", "".join(expected)) == re.sub(r"\s", "", text)


def test_many_sentences_keep_tail_and_all_punctuation():
    source = "First statement. Another statement! Evidence... Before the final warning? Last sentence."
    assert split_complete_sentences(source) == [
        "First statement.", "Another statement!", "Evidence...", "Before the final warning?", "Last sentence.",
    ]


def test_long_sentence_is_not_truncated_or_token_budgeted_here():
    source = "long source " * 2000 + "ending. Final warning."
    assert split_complete_sentences(source) == ["long source " * 2000 + "ending.", "Final warning."]


def test_deterministic_policy_identity():
    assert STRUCTURE_POLICY_ID == "complete-sentences-v1"


def test_randomized_inputs_preserve_all_non_whitespace_exactly_once():
    rng = random.Random(723)
    fragments = [
        "hello", "Second", "世界", "Dr.", "U.S.", "e.g.", "1.2.3", "3.14", "a@example.com",
        "https://example.com/a?q=x.y", "C:\\folder\\file.py", ".", "!", "?", "...", "…", "?!",
        "。", "！", "？", "\n", "\r\n", " ", "  ", "\t", "\u3000", '"', "”", "’", ")", "[", "but",
    ]
    for _ in range(1000):
        source = "".join(rng.choices(fragments, k=rng.randint(1, 80)))
        pieces = split_complete_sentences(source)
        assert re.sub(r"\s", "", "".join(pieces)) == re.sub(r"\s", "", source)
        assert all(piece and piece == piece.strip() for piece in pieces)
        assert split_complete_sentences(source) == pieces
        if len(pieces) == 1:
            assert pieces == [source.strip()]
