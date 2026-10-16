"""Output policy, source completeness and caching without native models."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from screen_translator.core.chat_translation import prepare_chat_translation
from screen_translator.inference import InferenceCancelled
from screen_translator.inference.translation.ctranslate2_engine import CTranslate2Engine
from screen_translator.storage.translation_cache import make_cache_key


class Tokenizer:
    eos = "</s>"

    def encode(self, text):
        return list(text) + [self.eos]

    def decode(self, tokens):
        return "".join(token for token in tokens if token != self.eos)


def engine(tmp_path, output=None):
    calls = []

    class Native:
        def translate_batch(self, sources, **kwargs):
            text = "".join(token for token in sources[0] if token != "</s>")
            calls.append(text)
            target = output(text) if callable(output) else output or text
            return [SimpleNamespace(hypotheses=[[target, "</s>"]])]

    value = CTranslate2Engine(tmp_path)
    for direction in ("en-zh", "zh-en"):
        value._tokenizers[direction] = Tokenizer()
        value._translators[direction] = Native()
        value._ids[direction] = "fixture-model"
    return value, calls


def test_three_complete_sentences_are_all_submitted_in_order(tmp_path):
    value, calls = engine(tmp_path)
    text = "Gather the evidence. Use your equipment... Before you become part of the haunting yourself."
    actual = value.translate(text, "en-zh")
    assert calls == ["Gather the evidence.", "Use your equipment...",
                     "Before you become part of the haunting yourself."]
    assert "Before you become" in actual


def test_newline_message_count_and_order_not_changed(tmp_path):
    value, calls = engine(tmp_path)
    assert value.translate("First message. More detail.\nSecond message.", "en-zh").splitlines() == [
        "First message. More detail.", "Second message."]
    assert calls == ["First message.", "More detail.", "Second message."]


def test_known_names_never_enter_native_model_but_unknown_text_does(tmp_path):
    value, calls = engine(tmp_path)
    actual = value.translate("Red Barrels invites you to experience terror. Murkoff is a corporation.", "en-zh")
    assert "Red Barrels" in actual and "Murkoff" in actual
    assert not any("Red Barrels" in text or "Murkoff" in text for text in calls)
    assert calls == ["invites you to experience terror.", "is a corporation."]
    assert value.translate("The red barrels exploded.", "en-zh") == "The red barrels exploded."
    assert calls[-1] == "The red barrels exploded."


def test_script_conversion_only_once_through_engine_and_named_chat(tmp_path):
    value, calls = engine(tmp_path, "乾清宮")
    assert value.translate("A palace.", "en-zh") == "乾清宫"
    assert prepare_chat_translation("臺灣玩家: A palace.").translate(value, "en-zh") == "臺灣玩家: 乾清宫"
    assert prepare_chat_translation("A palace.").translate(value, "en-zh") == "乾清宫"


def test_raw_provider_normalized_once_without_touching_nickname_or_english():
    class Raw:
        def translate(self, text, direction):
            return "歡迎光臨乾清宮"
    assert prepare_chat_translation("臺灣玩家: welcome").translate(Raw(), "en-zh") == "臺灣玩家: 欢迎光临乾清宫"
    assert prepare_chat_translation("臺灣玩家: welcome").translate(Raw(), "zh-en") == "臺灣玩家: 歡迎光臨乾清宮"


def test_new_policy_isolates_legacy_cache_and_zh_en_remains_unchanged(tmp_path):
    value, _ = engine(tmp_path)
    new = value.model_id("en-zh")
    assert "quality-policy-v1" in new and "opencc-t2s" in new and "complete-sentences-v1" in new
    assert make_cache_key(new, "en-zh", "Hello") != make_cache_key("fixture-model", "en-zh", "Hello")
    assert value.model_id("zh-en") == "fixture-model"


def test_cancellation_prevents_later_sentence_or_dictionary_output(tmp_path):
    value, calls = engine(tmp_path)
    with pytest.raises(InferenceCancelled):
        value.translate("First. Second. Third.", "en-zh", cancel_check=lambda: bool(calls))
    assert calls == ["First."]


def test_zh_en_never_changes_script_or_splits_by_new_policy(tmp_path):
    value, calls = engine(tmp_path, "歡迎")
    assert value.translate("你好。世界。", "zh-en") == "歡迎"
    assert calls == ["你好。世界。"]
