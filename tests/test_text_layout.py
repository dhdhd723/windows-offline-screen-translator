import hashlib
import json

import pytest

from screen_translator.core.text import (NORMALIZATION_VERSION,
                                        is_meaningful_layout_change,
                                        layout_semantic_signature,
                                        normalize_layout_text, normalize_text)
from screen_translator.storage.translation_cache import make_cache_key


@pytest.mark.parametrize("raw,expected", [
    ("Hello there\nCome here", "Hello there\nCome here"),
    ("你好\n过来", "你好\n过来"),
    ("  Ｈｅｌｌｏ  world\r\n  Good   morning  ", "Hello world\nGood morning"),
    ("\n \n First\n\nSecond\n", "First\nSecond"),
    ("‘Hello’\n\u200b世界　１２３", "'Hello'\n世界 123"),
    ("", ""),
])
def test_dialogue_normalization_preserves_nonempty_rows(raw, expected):
    assert normalize_layout_text(raw, "lines") == expected


@pytest.mark.parametrize("raw", ["Hello\nworld", "你好\n世界", "A\r\nB", ""])
def test_continuous_normalization_retains_legacy_behavior(raw):
    assert normalize_layout_text(raw) == normalize_text(raw)
    assert normalize_layout_text(raw, "continuous") == normalize_text(raw)


def test_hard_boundaries_have_distinct_signatures_even_with_same_words():
    first, second = "Open the door\nCome here", "Open the\ndoor Come here"
    assert normalize_text(first) == normalize_text(second)
    assert layout_semantic_signature(first, "lines") != layout_semantic_signature(second, "lines")
    assert is_meaningful_layout_change(first, second, "lines")
    assert not is_meaningful_layout_change(first, second, "continuous")


def test_added_short_message_is_not_hidden_by_long_unchanged_chat_history():
    history = "This is a very long message that stays exactly the same in the chat history."
    assert is_meaningful_layout_change(history, history + "\nGo", "lines")


def test_each_dialogue_row_retains_punctuation_noise_gate_and_number_changes():
    assert not is_meaningful_layout_change("Hello!\nGood morning", "Hello.\nGood morning!", "lines")
    assert is_meaningful_layout_change("Hello\nYou have 10 coins", "Hello\nYou have 11 coins", "lines")


def test_layout_cache_keys_do_not_reuse_legacy_flattened_cache():
    old_payload = json.dumps([NORMALIZATION_VERSION, "model", "en-zh", "Hello Come here"],
                             ensure_ascii=False, separators=(",", ":"))
    old_key = hashlib.sha256(old_payload.encode("utf-8")).hexdigest()
    assert make_cache_key("model", "en-zh", "Hello Come here") != old_key
    assert (make_cache_key("model", "en-zh", "Hello", text_layout="lines")
            != make_cache_key("model", "en-zh", "Hello", text_layout="continuous"))
    assert (make_cache_key("model", "en-zh", "Open door\nCome here", text_layout="lines")
            != make_cache_key("model", "en-zh", "Open\ndoor Come here", text_layout="lines"))
