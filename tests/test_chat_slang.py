"""Deterministic chat slang tests using only synthetic strings."""

from __future__ import annotations

import pytest

from screen_translator.core.chat_slang import (BUILTIN_CHAT_SLANG,
                                               chat_slang_fingerprint,
                                               expand_chat_slang,
                                               sanitize_overrides)


@pytest.mark.parametrize("token,expanded", sorted(BUILTIN_CHAT_SLANG.items()))
def test_builtin_complete_words_are_case_insensitive(token, expanded):
    assert expand_chat_slang(token) == expanded
    assert expand_chat_slang(token.upper()) == expanded
    assert expand_chat_slang("(" + token + ")!") == "(" + expanded + ")!"


def test_builtin_dictionary_has_valid_nonempty_english_rules():
    assert BUILTIN_CHAT_SLANG
    assert sanitize_overrides(BUILTIN_CHAT_SLANG) == BUILTIN_CHAT_SLANG
    assert all("\n" not in expansion and "\r" not in expansion
               for expansion in BUILTIN_CHAT_SLANG.values())


@pytest.mark.parametrize("token,expanded", sorted(BUILTIN_CHAT_SLANG.items()))
@pytest.mark.parametrize("template", [
    "{token}: {token}",
    "[{token}]: {token}",
    "@{token} {token}",
    "#{token} {token}",
    "https://example.com/{token}?reply={token} {token}",
    "{token}@example.com {token}",
    "C:\\Games\\{token}\\notes.txt {token}",
    "src/{token}/notes.txt {token}",
    "`{token}` {token}",
    "```text\n{token}\n```\n{token}",
])
def test_every_builtin_is_protected_in_explicit_identity_link_path_or_code(
        token, expanded, template):
    source = template.format(token=token)
    assert source.endswith(token)
    protected_prefix = source[:-len(token)]
    assert expand_chat_slang(source) == protected_prefix + expanded


def test_all_builtin_rules_keep_rows_and_spacing_without_recursive_expansion():
    tokens = sorted(BUILTIN_CHAT_SLANG)
    source = "\r\n".join("\t(" + token + ")!  " for token in tokens) + "\n"
    expected = "\r\n".join("\t(" + BUILTIN_CHAT_SLANG[token] + ")!  "
                             for token in tokens) + "\n"
    actual = expand_chat_slang(source)
    assert actual == expected
    assert actual.count("\n") == source.count("\n")
    assert actual.count("\r") == source.count("\r")


@pytest.mark.parametrize("token", sorted(BUILTIN_CHAT_SLANG))
@pytest.mark.parametrize("template", [
    "prefix{token}", "{token}suffix", "_{token}", "{token}_",
    "{token}123", "中文{token}", "{token}中文",
    "anti-{token}", "{token}-name", "{token}'s", "{token}’s",
])
def test_every_builtin_avoids_embedded_unicode_or_connected_words(token, template):
    source = template.format(token=token)
    assert expand_chat_slang(source) == source


@pytest.mark.parametrize("source", [
    "u r w l", "cap bet goat", "atm pm ig",
    "The cap fits; I bet the goat escaped.",
    "Compare variables u, r, w and l before changing them.",
])
def test_highly_ambiguous_short_or_ordinary_words_are_not_defaults(source):
    assert expand_chat_slang(source) == source


def test_expansion_keeps_newlines_spacing_and_sentence_punctuation():
    source = " ty!\r\nnp?\n\tpls,  brb.\n"
    assert expand_chat_slang(source) == " thanks!\r\nno problem?\n\tplease,  be right back.\n"


@pytest.mark.parametrize("source", [
    "pretty", "party", "tyson", "ty123", "_ty", "ty_", "word_np",
    "中文ty", "ty中文", "NP-hard", "anti-ty", "ty's", "ty’s", "ty.py",
])
def test_partial_unicode_or_connected_words_are_not_expanded(source):
    assert expand_chat_slang(source) == source


def test_custom_replacements_override_builtins_and_do_not_recurse():
    overrides = {"ty": "np", "np": "pls", "gg": "ty np"}
    assert expand_chat_slang("TY np gg pls", overrides) == "np pls ty np please"


@pytest.mark.parametrize("source,expected", [
    ("Ty: ty", "Ty: thanks"),
    ("[Ty]:np", "[Ty]:no problem"),
    ("Player Ty: pls", "Player Ty: please"),
    ("ty: np\nnp: ty", "ty: no problem\nnp: thanks"),
    ("@ty np @NP!", "@ty no problem @NP!"),
    ("#ty np #NP!", "#ty no problem #NP!"),
    ("https://example.com/ty?reply=np&ask=pls ty",
     "https://example.com/ty?reply=np&ask=pls thanks"),
    ("steam://ty/np ty", "steam://ty/np thanks"),
    ("example.ty/np ty", "example.ty/np thanks"),
    ("ty@example.com np@domain.ty ty", "ty@example.com np@domain.ty thanks"),
    ("C:\\Games\\ty\\np.txt ty", "C:\\Games\\ty\\np.txt thanks"),
    ("D:/games/ty/np.txt ty", "D:/games/ty/np.txt thanks"),
    ("src/ty/np.txt ty", "src/ty/np.txt thanks"),
    ("`ty np` ty", "`ty np` thanks"),
    ("```text\nty=np\n```\nty", "```text\nty=np\n```\nthanks"),
])
def test_explicit_identity_links_paths_and_code_are_protected(source, expected):
    assert expand_chat_slang(source) == expected


@pytest.mark.parametrize("value", [None, True, 7, "ty=thanks", [], ["ty", "thanks"]])
def test_non_dictionary_overrides_are_ignored(value):
    assert sanitize_overrides(value) == {}


def test_sanitize_trims_keys_and_values_and_last_valid_duplicate_wins():
    raw = {" TY ": " thank you ", "ty": "many thanks", " np ": " no problem ",
           "TY": "\n\t"}
    assert sanitize_overrides(raw) == {"ty": "many thanks", "np": "no problem"}
    assert expand_chat_slang("ty np", raw) == "many thanks no problem"


def test_sanitize_discards_invalid_key_or_value_without_throwing():
    valid_long_key = "a" + "b" * 23
    raw = {None: "thanks", 7: "thanks", "": "thanks", "123ty": "thanks",
           "ty_": "thanks", "ty-name": "thanks", "ty's": "thanks",
           "中文": "thanks", "a" + "b" * 24: "thanks", "empty": "",
           "number": "123", "symbol": "!@#", "boolean": True,
           "nested": {"ty": "thanks"}, "line": "many\nthanks",
           "tab": "many\tthanks", "control": "many\x00thanks",
           "unicode": "谢谢", "toolong": "a" * 161,
           valid_long_key: " a "}
    assert sanitize_overrides(raw) == {valid_long_key: "a"}


def test_sanitize_caps_valid_custom_dictionary_entries_at_one_hundred():
    raw = {"term" + str(index): "replacement" for index in range(105)}
    sanitized = sanitize_overrides(raw)
    assert len(sanitized) == 100
    assert set(sanitized).issubset(raw)
    assert all(value == "replacement" for value in sanitized.values())


def test_fingerprint_is_deterministic_for_equivalent_sanitized_dictionaries():
    first = {" TY ": " thank you ", "np": "no problem"}
    second = {"np": "no problem", "ty": "thank you"}
    assert chat_slang_fingerprint(True, first) == chat_slang_fingerprint(True, second)
    assert chat_slang_fingerprint(True) == chat_slang_fingerprint(True, {})


def test_fingerprint_separates_activation_and_changed_custom_policy():
    assert chat_slang_fingerprint(True) != chat_slang_fingerprint(False)
    assert chat_slang_fingerprint(True, {"ty": "thank you"}) != chat_slang_fingerprint(
        True, {"ty": "many thanks"})
    assert chat_slang_fingerprint(True, {"ty": "thanks"}) == chat_slang_fingerprint(True)
    assert chat_slang_fingerprint(True, {"zz": "thanks"}) != chat_slang_fingerprint(True)


@pytest.mark.parametrize("token,expanded", sorted(BUILTIN_CHAT_SLANG.items()))
def test_every_builtin_can_be_overridden_with_cache_policy_change(token, expanded):
    original_policy = chat_slang_fingerprint(True)
    if token == "asf":
        assert chat_slang_fingerprint(True, {token: expanded}) != original_policy
    else:
        assert chat_slang_fingerprint(True, {token: expanded}) == original_policy
    custom = "custom expansion for " + token
    overrides = {token: custom}
    assert expand_chat_slang(token.upper(), overrides) == custom
    assert chat_slang_fingerprint(True, overrides) != original_policy


def test_adding_a_builtin_changes_active_fingerprint_but_not_disabled_policy(
        monkeypatch):
    original_active = chat_slang_fingerprint(True)
    original_disabled = chat_slang_fingerprint(False)
    monkeypatch.setitem(BUILTIN_CHAT_SLANG, "freshterm", "a newly added expression")
    assert chat_slang_fingerprint(True) != original_active
    assert chat_slang_fingerprint(False) == original_disabled
    assert expand_chat_slang("freshterm") == "a newly added expression"


def test_ordinary_text_and_empty_input_are_unchanged():
    assert expand_chat_slang("") == ""
    assert expand_chat_slang("Please wait by the station.") == "Please wait by the station."


def test_long_unbroken_identifier_stays_intact_without_looking_like_a_url_scheme():
    source = "X" * 16000 + " ty!"
    assert expand_chat_slang(source) == "X" * 16000 + " thanks!"
