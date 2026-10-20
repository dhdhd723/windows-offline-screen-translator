"""Synthetic tests: raw chat remains the source, hints are never replacements."""
from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from screen_translator.core.chat_normalization import (
    MAX_CHAT_HINT_CHARACTERS,
    MAX_CHAT_HINTS,
    MAX_CHAT_SCAN_CHARACTERS,
    conservative_chat_candidates,
)
from screen_translator.core.chat_slang import BUILTIN_CHAT_SLANG


@pytest.mark.parametrize("text", [
    "", " ", "im low can u cover me", "ngl that was clean", "u good?",
    "def hold base", "ur aim is clean", "ur low", "2 medkits", "u r w l",
    "ty!\r\nNP?\n\tMB 😅  ", "ty 中文", "@im: cant help rn",
])
def test_raw_source_is_preserved_exactly(text):
    assert conservative_chat_candidates(text).raw == text


@pytest.mark.parametrize("token,expansion", sorted(BUILTIN_CHAT_SLANG.items()))
def test_builtin_sense_is_available_as_nonbinding_hint(token, expansion):
    result = conservative_chat_candidates(token.upper())
    assert result.raw == token.upper()
    assert len(result.hints) == 1
    hint = result.hints[0]
    assert hint.token == token.upper()
    assert expansion in hint.candidates
    assert result.raw[hint.start:hint.end] == hint.token


@pytest.mark.parametrize("token,candidates", [
    ("def", ("definitely", "defense")),
    ("ur", ("your", "you are")),
    ("mb", ("my bad", "maybe")),
])
def test_ambiguity_is_explicit_instead_of_chosen(token, candidates):
    hint = conservative_chat_candidates(token).hints[0]
    assert hint.candidates == candidates
    assert hint.ambiguous


def test_high_frequency_spelling_hints_do_not_replace_the_sentence():
    raw = "im low can u cover me? dont leave, ur good, dw mb"
    result = conservative_chat_candidates(raw)
    assert result.raw == raw
    assert {hint.token for hint in result.hints} == {"im", "u", "dont", "ur", "dw", "mb"}


@pytest.mark.parametrize("text", ["r 2", "r = 2", "2 medkits", "want 2 go", "R2 U2"])
def test_bare_r_and_numbers_do_not_get_hints(text):
    assert not conservative_chat_candidates(text).hints


@pytest.mark.parametrize("template", [
    "@{0}", "#{0}", "{0}: hello", "[{0}]: hello", "[Team] {0}: hello",
    "https://example.com/{0}?reply={0}", "steam://{0}/x", "www.example.com/{0}",
    "{0}@example.com", "C:\\Games\\{0}\\notes.txt", "src/{0}/notes.txt",
    "example.com/{0}", "`{0}`", "```python\n{0}\n```",
    '"{0}"', "'{0}'", "“{0}”", "‘{0}’", "「{0}」", "『{0}』",
    "prefix{0}", "{0}suffix", "_{0}", "{0}_", "{0}123", "anti-{0}",
    "{0}-name", "{0}'s", "{0}’s", "{0}.py", "中文{0}", "{0}中文",
])
@pytest.mark.parametrize("token", ["ty", "def", "im", "u", "ur", "mb"])
def test_protected_identity_code_quote_link_or_identifier_has_no_hints(template, token):
    text = template.format(token)
    assert conservative_chat_candidates(text).raw == text
    assert not conservative_chat_candidates(text).hints


@pytest.mark.parametrize("text", [
    "def heal(u): return u", "u=2; im=4", "ty == np", "100 bc", "bc 100",
    '"ty np', "'ty np", "`ty np", "```python\nty np",
    "我说 ty", "café pls", "こんにちは im",
])
def test_code_unterminated_quotes_and_non_english_rows_are_not_annotated(text):
    assert not conservative_chat_candidates(text).hints


def test_protected_span_does_not_suppress_following_chat_body():
    result = conservative_chat_candidates("[ty]: @np https://example.com/ur `im` ty!")
    assert [hint.token for hint in result.hints] == ["ty"]
    assert result.hints[0].start == result.raw.rindex("ty")


def test_contractions_are_not_mistaken_for_opening_quotes():
    result = conservative_chat_candidates("don't worry, ty; I'm here rn")
    assert [hint.token for hint in result.hints] == ["ty", "rn"]


def test_hints_are_deduplicated_and_do_not_span_message_rows():
    raw = "@ty: TY np\r\n@np: ty im\n@ur: ur mb\n中文 u\npls"
    result = conservative_chat_candidates(raw)
    assert [hint.token for hint in result.hints] == ["TY", "np", "im", "ur", "mb", "pls"]
    for hint in result.hints:
        assert raw[hint.start:hint.end] == hint.token
        assert "\n" not in hint.token


def test_count_and_character_budgets_bound_hints_without_truncating_raw():
    raw = " ".join(BUILTIN_CHAT_SLANG) + " ty" * 500
    result = conservative_chat_candidates(raw)
    assert result.raw == raw
    assert len(result.hints) <= MAX_CHAT_HINTS
    assert sum(len(hint.token) + sum(map(len, hint.candidates))
               for hint in result.hints) <= MAX_CHAT_HINT_CHARACTERS
    assert len({hint.token.lower() for hint in result.hints}) == len(result.hints)


def test_oversized_input_is_not_truncated_or_scanned():
    text = "ty " * (MAX_CHAT_SCAN_CHARACTERS // 3 + 1)
    result = conservative_chat_candidates(text)
    assert result.raw == text
    assert not result.hints


def test_hints_are_immutable_and_unknown_terms_are_not_guessed():
    assert not conservative_chat_candidates("oms cap bet goat qqq").hints
    result = conservative_chat_candidates("ty")
    with pytest.raises(FrozenInstanceError):
        result.raw = "thanks"
    with pytest.raises(FrozenInstanceError):
        result.hints[0].token = "thanks"


def test_custom_senses_are_candidates_not_source_rewrites():
    source = "def hold base, oms report oms"
    overrides = {"def": "defense", "oms": "our medical supplies"}
    result = conservative_chat_candidates(source, overrides)
    overrides["oms"] = "a changed later sense"
    assert result.raw == source
    assert [(hint.token, hint.candidates) for hint in result.hints] == [
        ("def", ("defense",)), ("oms", ("our medical supplies",)),
    ]


@pytest.mark.parametrize("source", [
    "@zz", "#zz", "zz: ordinary text", "https://example.com/zz", "`zz`", '"zz"',
    "prefixzz", "zz_name", "C:\\Games\\zz\\notes.txt", "我说 zz",
])
def test_custom_tokens_use_the_same_protection_policy(source):
    assert not conservative_chat_candidates(source, {"zz": "a custom sense"}).hints


def test_custom_terms_take_budget_priority_over_builtin_terms():
    source = " ".join(BUILTIN_CHAT_SLANG) + " zz"
    result = conservative_chat_candidates(source, {"zz": "a custom sense"})
    assert result.hints[0].token == "zz"
    assert len(result.hints) <= MAX_CHAT_HINTS
    assert result.raw == source


@pytest.mark.parametrize("overrides", [None, 7, ["ty"], {"zz": "中文"}, {"zz": "a\nb"}])
def test_invalid_custom_rules_are_ignored(overrides):
    assert not conservative_chat_candidates("zz", overrides).hints
