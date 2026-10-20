"""Requested glossary additions and conservative numeric-chat regressions.

All input is synthetic. These tests exercise the adapter and threaded pipeline,
not real OCR, a live game, physical shortcuts, or translation-model quality.
"""
from __future__ import annotations

import json

import pytest

from screen_translator.contracts import Region
from screen_translator.core.chat_slang import (
    BUILTIN_CHAT_SLANG, CHAT_SLANG_VERSION, chat_slang_fingerprint,
    expand_chat_slang, sanitize_overrides,
)
from screen_translator.core.chat_translation import (
    BUILTIN_CHAT_ZH, CHAT_TRANSLATION_VERSION, chat_direction_source,
    chat_translation_fingerprint, prepare_chat_translation,
)
from screen_translator.core.text import choose_direction
from screen_translator.storage.translation_cache import TranslationCache, make_cache_key

from test_chat_slang_pipeline import make_pipeline  # noqa: F401 -- shared fixture
from test_dialogue_layout_pipeline import Translator, wait_for


ADDITIONS = {
    "sm1": ("someone", "有人"),
    "l8r": ("later", "回头见"),
    "cya": ("see you", "再见"),
    "cyaa": ("see you", "再见"),
    "prolly": ("probably", "大概吧"),
    "cuz": ("because", "因为"),
    "bc": ("because", "因为"),
    "ppl": ("people", "人们"),
    "pic": ("picture", "图片"),
    "rn": ("right now", "现在"),
    "fr": ("for real", "真的"),
    "hbu": ("how about you", "你呢"),
    "yk": ("you know", "你知道的"),
    "def": ("definitely", "肯定"),
    "istg": ("I swear to God", "我发誓"),
    # Explicit user-approved compatibility spelling, not general correction.
    "tytl": ("talk to you later", "回头聊"),
    "mdfk": ("motherfucker", "混蛋（粗口）"),
    "asf": ("as fuck", "……得要命（粗俗强调）"),
}
REGION = Region(0, 0, 64, 32)


def test_requested_policy_is_versioned_and_dictionaries_remain_aligned():
    assert CHAT_SLANG_VERSION == 3
    assert CHAT_TRANSLATION_VERSION == 4
    assert len(BUILTIN_CHAT_SLANG) == len(BUILTIN_CHAT_ZH) == 58
    assert set(BUILTIN_CHAT_SLANG) == set(BUILTIN_CHAT_ZH)
    assert sanitize_overrides(BUILTIN_CHAT_SLANG) == BUILTIN_CHAT_SLANG
    assert "2" not in BUILTIN_CHAT_SLANG and "2" not in BUILTIN_CHAT_ZH


@pytest.mark.parametrize("token,meanings", sorted(ADDITIONS.items()))
def test_each_requested_addition_has_explicit_english_and_chinese(token, meanings):
    english, chinese = meanings
    assert BUILTIN_CHAT_SLANG[token] == english
    assert BUILTIN_CHAT_ZH[token] == chinese
    assert expand_chat_slang(token.upper()) == english


@pytest.mark.parametrize("token,meanings", sorted(ADDITIONS.items()))
@pytest.mark.parametrize("layout", ["continuous", "lines"])
def test_each_addition_directly_translates_with_name_and_punctuation(token, meanings, layout):
    translator = Translator()
    source = "Fixture_User: (" + token.upper() + ")!"
    actual = prepare_chat_translation(source, layout).translate(translator, "en-zh")
    assert actual == "Fixture_User: (" + meanings[1] + ")!"
    assert translator.calls == []


@pytest.mark.parametrize("token", sorted(ADDITIONS))
def test_every_addition_accepts_override_without_direct_answer_or_recursion(token):
    translator = Translator()
    plan = prepare_chat_translation("Player: " + token.upper(), overrides={token: "np"})
    assert plan.translate(translator, "en-zh") == "Player: 译：np"
    assert translator.calls == [("np", "en-zh")]
    assert chat_translation_fingerprint({token: "np"}) != chat_translation_fingerprint()


def test_long_message_expands_all_requested_tokens_once_without_changing_rows():
    source = "sm1 prolly wants a pic rn\r\ncyaa l8r, cuz ppl need help fr"
    expected = ("someone probably wants a picture right now\r\n"
                "see you later, because people need help for real")
    assert expand_chat_slang(source) == expected


@pytest.mark.parametrize("source,expected", [
    ("want 2 play", "want to play"),
    ("need 2 go rn", "need to go right now"),
    ("have 2 leave", "have to leave"),
    ("got 2 run", "got to run"),
    ("going 2 join", "going to join"),
    ("try 2 win", "try to win"),
    ("trying 2 help", "trying to help"),
    ("ready 2 start", "ready to start"),
    ("able 2 come", "able to come"),
    ("talk 2 you", "talk to you"),
    ("speak 2 them", "speak to them"),
    ("listen 2 me", "listen to me"),
    ("send 2 her", "send to her"),
    ("give 2 him", "give to him"),
    ("pass 2 us", "pass to us"),
    ("go 2 base", "go to base"),
    ("come 2 spawn", "come to spawn"),
    ("head 2 lobby", "head to lobby"),
    ("return 2 our base", "return to our base"),
    ("(WANT\t2\tPLAY)!", "(WANT\tto\tPLAY)!"),
    ("sm1 want 2 play rn", "someone want to play right now"),
    ("want 2 go 2 base", "want to go to base"),
    ("need 2 go\n2 players", "need to go\n2 players"),
    ("go 2 the next room for 2 players", "go to the next room for 2 players"),
])
def test_numeric_to_is_limited_to_explicit_original_chat_context(source, expected):
    assert expand_chat_slang(source) == expected


@pytest.mark.parametrize("source", [
    "2", "2!", "(2)", "2 players", "level 2", "version 2.0", "12:30",
    "2:1", "2-1", "R2D2", "go 2 miles", "need 2 players", "press 2",
    "room 2", "2/3", "2.5", "2,000", "want 20 play", "want 12 play",
    "want2play", "want 2.0 play", "want 2 play2", "want\n2 play",
    "want 2\nplay", "talk 2 3 players", "give 2 items", "send 2 pictures",
    "wait 2 seconds", "2 go", "2 me", "2 base", "anti-want 2 play",
])
def test_numeric_values_or_unpromised_context_are_never_replaced(source):
    assert expand_chat_slang(source) == source


@pytest.mark.parametrize("source,expected", [
    ("`want 2 play rn` want 2 play rn", "`want 2 play rn` want to play right now"),
    ("```text\nwant 2 play rn\n```\nneed 2 go",
     "```text\nwant 2 play rn\n```\nneed to go"),
    ("want 2 play: want 2 play", "want 2 play: want to play"),
    ("https://example.com/rn/2 want 2 play",
     "https://example.com/rn/2 want to play"),
    ("rn@example.com want 2 play", "rn@example.com want to play"),
    ("C:\\Games\\rn\\2.txt want 2 play", "C:\\Games\\rn\\2.txt want to play"),
    ("src/rn/2.txt want 2 play", "src/rn/2.txt want to play"),
    ("@rn #fr want 2 play", "@rn #fr want to play"),
])
def test_numeric_context_never_bypasses_original_protected_spans(source, expected):
    assert expand_chat_slang(source) == expected


@pytest.mark.parametrize("source,expected", [
    ("400 BC bc I said so", "400 BC because I said so"),
    ("bc 400 bc I said so", "bc 400 because I said so"),
    ("400 bc, 20 Bc and BC 44", "400 bc, 20 Bc and BC 44"),
    ("400BC bc", "400BC because"),
    ("def hbu(arg)", "def hbu(arg)"),
    ("def rn(x) def", "def rn(x) definitely"),
    ("def _fr():\n    `rn`", "def _fr():\n    `rn`"),
    ("`def rn(): return ppl` rn", "`def rn(): return ppl` right now"),
    ("bc we can def win", "because we can definitely win"),
])
def test_explicit_bc_dates_and_python_def_syntax_are_not_chat_senses(source, expected):
    assert expand_chat_slang(source) == expected


def test_numeric_override_is_rejected_without_weakening_context_rule():
    assert sanitize_overrides({"2": "two", "rn": "registered nurse"}) == {
        "rn": "registered nurse"}
    assert expand_chat_slang("want 2 play rn", {"2": "two", "rn": "registered nurse"}) == (
        "want to play registered nurse")


def test_naked_numeric_message_remains_undetermined_in_auto_direction():
    assert chat_direction_source("Player: 2") == "2"
    assert choose_direction(chat_direction_source("Player: 2")) is None
    translator = Translator()
    plan = prepare_chat_translation("2")
    assert plan.cache_source == "2"
    # No standalone '到' is guessed, even if a caller explicitly requests en-zh.
    assert plan.translate(translator, "en-zh") == "译：2"
    assert translator.calls == [("2", "en-zh")]


def test_tytl_is_an_explicit_alias_not_fuzzy_typo_correction():
    assert expand_chat_slang("tytl ttyl tylt ttl") == (
        "talk to you later talk to you later tylt ttl")


def test_vulgar_terms_retain_explicit_register_in_both_dictionaries():
    assert expand_chat_slang("mdfk asf") == "motherfucker as fuck"
    assert "粗口" in BUILTIN_CHAT_ZH["mdfk"]
    assert "粗俗" in BUILTIN_CHAT_ZH["asf"]


@pytest.mark.parametrize("source,expected", [
    ("tired asf", "extremely tired"),
    ("cool ASF", "extremely cool"),
    ("I am TIRED AsF!", "I am extremely TIRED!"),
    ("tired\tasf", "extremely tired"),
    ("tired asf rn", "extremely tired right now"),
    ("tired asf\ncool ASF", "extremely tired\nextremely cool"),
    ("tired\nasf", "tired\nas fuck"),
    ("tired\r\nasf", "tired\r\nas fuck"),
    # The limited adjective list is not an unrestricted phrase corrector.
    ("sleepy asf", "sleepy as fuck"),
    ("tired-asf", "tired-asf"),
    ("tired asf-name", "tired asf-name"),
    ("tired asf's", "tired asf's"),
])
def test_known_postfix_asf_pairs_get_model_friendly_order_without_crossing_rows(source,
                                                                               expected):
    assert expand_chat_slang(source) == expected


@pytest.mark.parametrize("source,expected", [
    ("`tired asf` cool asf", "`tired asf` extremely cool"),
    ("```text\ntired asf\n```\ncool asf", "```text\ntired asf\n```\nextremely cool"),
    ("C:\\Games\\tired\\asf.txt cool ASF", "C:\\Games\\tired\\asf.txt extremely cool"),
    ("src/tired/asf.txt cool asf", "src/tired/asf.txt extremely cool"),
    ("https://example.com/tired/asf cool asf",
     "https://example.com/tired/asf extremely cool"),
    ("tired@asf.example cool asf", "tired@asf.example extremely cool"),
    ("@tired asf", "@tired asf"),
    ("tired asf: cool asf", "tired asf: extremely cool"),
])
def test_postfix_asf_rewrite_does_not_touch_any_overlapping_protected_span(source, expected):
    assert expand_chat_slang(source) == expected


@pytest.mark.parametrize("overrides,expected", [
    ({"asf": "a lot"}, "tired a lot"),
    ({"tired": "sleepy"}, "sleepy as fuck"),
    ({"asf": "a lot", "tired": "sleepy"}, "sleepy a lot"),
    ({"ASF": "a lot", "TIRED": "sleepy"}, "sleepy a lot"),
    # An explicit equal-to-default user rule still outranks phrase reordering.
    ({"asf": "as fuck"}, "tired as fuck"),
    ({"tired": "rn"}, "rn as fuck"),
])
def test_postfix_asf_normalization_respects_either_custom_token_without_recursion(overrides,
                                                                                 expected):
    assert expand_chat_slang("tired asf", overrides) == expected


def test_postfix_asf_keeps_hard_rows_but_continuous_layout_can_join_soft_wrap():
    translator = Translator()
    line_plan = prepare_chat_translation("tired\nasf", "lines")
    assert line_plan.translate(translator, "en-zh") == (
        "译：tired\n" + BUILTIN_CHAT_ZH["asf"])
    assert translator.calls == [("tired", "en-zh")]
    # Continuous layout intentionally treats an unlabelled newline as wrapping.
    assert prepare_chat_translation("tired\nasf", "continuous").cache_source == (
        "extremely tired")


def test_equal_to_builtin_asf_override_has_distinct_phrase_cache_policy():
    assert expand_chat_slang("tired asf") == "extremely tired"
    assert expand_chat_slang("tired asf", {"asf": "as fuck"}) == "tired as fuck"
    assert chat_slang_fingerprint(True) != chat_slang_fingerprint(True, {"asf": "as fuck"})
    assert chat_translation_fingerprint() != chat_translation_fingerprint({"asf": "as fuck"})


def test_version_four_cache_covers_direct_answer_expansion_and_user_override():
    default = chat_translation_fingerprint()
    assert default.startswith("chat-translation-v4|chat-slang-v3:")
    assert chat_slang_fingerprint(False) == "chat-slang-v3:disabled"
    assert default != default.replace("-v3", "-v2")
    plan = prepare_chat_translation("Player: rn")
    material = json.loads(plan.cache_source)
    assert material["version"] == 4
    assert material["rows"] == [{"prefix": "Player: ", "body": "rn",
                                  "expanded": "right now", "direct": "现在"}]
    overridden = prepare_chat_translation("Player: rn", overrides={"rn": "registered nurse"})
    assert plan.cache_source != overridden.cache_source
    numeric = prepare_chat_translation("want 2 play")
    assert numeric.cache_source == "want to play"
    assert make_cache_key("fixture", "en-zh", "want 2 play", translation_policy=default,
                          model_source=numeric.cache_source) != make_cache_key(
        "fixture", "en-zh", "want 2 play", translation_policy="old-policy",
        model_source="want 2 play")


@pytest.mark.parametrize("layout", ["continuous", "lines"])
def test_pipeline_all_new_standalone_messages_use_default_direct_glossary(make_pipeline, layout):
    source = "\n".join("Player" + str(index) + ": " + token.upper()
                       for index, token in enumerate(ADDITIONS))
    expected = "\n".join("Player" + str(index) + ": " + meanings[1]
                         for index, meanings in enumerate(ADDITIONS.values()))
    pipeline, _, _, translator, results, _ = make_pipeline({40: source}, text_layout=layout)
    pipeline.start(REGION)
    wait_for(lambda: len(results) == 1)
    assert results[0].source == source
    assert results[0].translation == expected
    assert results[0].direction == "en-zh" and not translator.calls


@pytest.mark.parametrize("layout", ["continuous", "lines"])
@pytest.mark.parametrize("enabled", [True, False])
def test_pipeline_switch_controls_new_words_and_numeric_context_together(make_pipeline, layout,
                                                                        enabled):
    source = "sm1 want 2 play rn"
    expected = "someone want to play right now" if enabled else source
    pipeline, _, _, translator, results, _ = make_pipeline({40: source}, text_layout=layout,
                                                          enabled=enabled)
    pipeline.start(REGION)
    wait_for(lambda: len(results) == 1)
    assert translator.calls == [(expected, "en-zh")]
    assert results[0].source == source
    assert results[0].translation == "译：" + expected


@pytest.mark.parametrize("layout", ["continuous", "lines"])
def test_pipeline_custom_rules_outrank_new_standalone_answers(make_pipeline, layout):
    source = "Alex: RN\nSam: DEF"
    pipeline, _, _, translator, results, _ = make_pipeline(
        {40: source}, text_layout=layout,
        overrides={"rn": "registered nurse", "def": "defense"})
    pipeline.start(REGION)
    wait_for(lambda: len(results) == 1)
    assert translator.calls == [("registered nurse", "en-zh"), ("defense", "en-zh")]
    assert results[0].source == source
    assert results[0].translation == "Alex: 译：registered nurse\nSam: 译：defense"


def test_pipeline_zh_en_direction_does_not_apply_new_english_chat_rules(make_pipeline):
    source = "want 2 play rn"
    pipeline, _, _, translator, results, _ = make_pipeline({40: source}, direction="zh-en")
    pipeline.start(REGION)
    wait_for(lambda: len(results) == 1)
    assert translator.calls == [(source, "zh-en")]
    assert results[0].translation == "译：" + source


def test_pipeline_ignores_legacy_echo_cache_and_reuses_new_direct_answer(make_pipeline):
    translator = Translator()
    cache = TranslationCache()
    source = "rn"
    cache.put(make_cache_key(translator.model_id("en-zh"), "en-zh", source,
                             text_layout="lines",
                             translation_policy="chat-translation-v2|chat-slang-v2:legacy",
                             model_source=source), "rn")
    pipeline, _, _, translator, results, _ = make_pipeline({40: source}, cache=cache,
                                                          translator=translator)
    pipeline.start(REGION)
    wait_for(lambda: len(results) == 1)
    assert results[0].translation == "现在" and not results[0].cache_hit
    pipeline.stop()
    pipeline.start(REGION)
    wait_for(lambda: len(results) == 2)
    assert results[1].translation == "现在" and results[1].cache_hit
    assert translator.calls == []
