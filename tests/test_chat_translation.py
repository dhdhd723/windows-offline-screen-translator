"""Synthetic adapter regressions; no game, screenshots or model are invoked."""
from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest

from screen_translator.core.chat_slang import (
    BUILTIN_CHAT_SLANG, chat_slang_fingerprint, expand_chat_slang,
)
from screen_translator.core.chat_translation import (
    BUILTIN_CHAT_ZH, CHAT_TRANSLATION_VERSION, chat_direction_source, chat_source_layout,
    chat_translation_fingerprint, prepare_chat_translation,
)
from screen_translator.inference import InferenceCancelled
from screen_translator.inference import InputLimitError
from screen_translator.storage.translation_cache import make_cache_key


class Model:
    def __init__(self):
        self.calls = []

    def translate(self, text, direction):
        self.calls.append((text, direction))
        return "模型译文：" + text


def test_chinese_nickname_does_not_determine_english_body_direction():
    from screen_translator.core.text import choose_direction
    assert chat_direction_source("玩家_一: ty") == "ty"
    assert choose_direction(chat_direction_source("玩家_一: ty")) == "en-zh"
    assert chat_direction_source("Player: 你好") == "你好"


def test_direct_policy_does_not_bypass_existing_source_length_limit():
    with pytest.raises(InputLimitError):
        prepare_chat_translation("ty\n" * 6000, "lines")


def test_direct_glossary_has_exactly_the_existing_documented_keys():
    assert CHAT_TRANSLATION_VERSION == 3
    assert len(BUILTIN_CHAT_ZH) == 58
    assert set(BUILTIN_CHAT_ZH) == set(BUILTIN_CHAT_SLANG)
    assert all(value.strip() and any("\u4e00" <= char <= "\u9fff" for char in value)
               for value in BUILTIN_CHAT_ZH.values())


@pytest.mark.parametrize("token,answer", sorted(BUILTIN_CHAT_ZH.items()))
@pytest.mark.parametrize("layout", ["continuous", "lines"])
@pytest.mark.parametrize("template", ["{}", "{}!", "({})?", "[{}]", '"{}"'])
def test_all_standalone_terms_have_deterministic_chinese_without_model(
        token, answer, layout, template):
    model = Model()
    plan = prepare_chat_translation(template.format(token.upper()), layout)
    assert plan.translate(model, "en-zh", lambda: False) == template.format(answer)
    assert model.calls == []


@pytest.mark.parametrize("source,expected", [
    ("Ty: ty", "Ty: 谢谢"),
    ("[Ty]: ty!", "[Ty]: 谢谢!"),
    ("[Team] Ty: np", "[Team] Ty: 没问题"),
    ("RiverPilot123: gg", "RiverPilot123: 打得不错"),
    ("玩家_一: brb", "玩家_一: 马上回来"),
    ("Name.One-two: ty", "Name.One-two: 谢谢"),
    ("Fixture_ _User: np", "Fixture_ _User: 没问题"),
    ("CaptainFox: take lead", "CaptainFox: 带头"),
    ("CaptainFox: TAKE LEAD!", "CaptainFox: 带头!"),
])
@pytest.mark.parametrize("layout", ["continuous", "lines"])
def test_explicit_name_is_preserved_and_never_sent_to_model(source, expected, layout):
    model = Model()
    assert prepare_chat_translation(source, layout).translate(model, "en-zh") == expected
    assert model.calls == []


@pytest.mark.parametrize("layout", ["continuous", "lines"])
def test_multiple_named_messages_keep_order_and_names_in_both_layouts(layout):
    model = Model()
    source = "Ty: ty\nnp: np\nCaptainFox: take lead\nPlayer: hello there"
    result = prepare_chat_translation(source, layout).translate(model, "en-zh")
    assert result == "Ty: 谢谢\nnp: 没问题\nCaptainFox: 带头\nPlayer: 模型译文：hello there"
    assert model.calls == [("hello there", "en-zh")]


def test_named_longer_message_sends_only_body_and_expands_exactly_once():
    model = Model()
    plan = prepare_chat_translation("Ty: ty for the help!", overrides={"ty": "np"})
    assert plan.translate(model, "en-zh") == "Ty: 模型译文：np for the help!"
    assert model.calls == [("np for the help!", "en-zh")]


@pytest.mark.parametrize("token", sorted(BUILTIN_CHAT_ZH))
def test_custom_rule_outranks_every_builtin_direct_answer(token):
    model = Model()
    plan = prepare_chat_translation(token, overrides={token: "custom expansion"})
    assert plan.translate(model, "en-zh") == "模型译文：custom expansion"
    assert model.calls == [("custom expansion", "en-zh")]
    assert plan.cache_source == "custom expansion"


def test_custom_rule_can_alias_builtin_without_recursive_direct_or_expansion():
    model = Model()
    plan = prepare_chat_translation("ty!", overrides={"ty": "np", "np": "pls"})
    assert plan.translate(model, "en-zh") == "模型译文：np!"
    assert model.calls == [("np!", "en-zh")]


def test_custom_rules_are_snapshotted_and_invalid_rules_do_not_disable_builtin():
    overrides = {"ty": "thank you"}
    model = Model()
    plan = prepare_chat_translation("Ty: ty", overrides=overrides)
    overrides["ty"] = "different input"
    assert plan.translate(model, "en-zh") == "Ty: 模型译文：thank you"
    assert prepare_chat_translation("ty", overrides={"ty": "谢谢"}).translate(
        Model(), "en-zh") == "谢谢"


@pytest.mark.parametrize("source", [
    "lead poisoning", "take lead", "Take lead!", "oms report oms",
    "I found lead bullets.", "I need to take lead samples.",
    "Take lead in the laboratory.", "You should take lead.",
])
def test_unprefixed_ambiguous_phrase_and_unknown_terms_still_use_model(source):
    model = Model()
    plan = prepare_chat_translation(source)
    assert plan.cache_source == expand_chat_slang(source)
    assert plan.translate(model, "en-zh") == "模型译文：" + source
    assert model.calls == [(source, "en-zh")]


@pytest.mark.parametrize("body", ["lead poisoning", "oms report oms", "take lead samples"])
def test_named_ordinary_or_unknown_body_is_not_guessed(body):
    model = Model()
    assert prepare_chat_translation("CaptainFox: " + body).translate(model, "en-zh") == (
        "CaptainFox: 模型译文：" + body)
    assert model.calls == [(body, "en-zh")]


@pytest.mark.parametrize("source", [
    "https://example.com/ty", "C:\\Games\\ty\\notes.txt", "C:/Games/ty/notes.txt",
    "12:30", "123: 456", "This is a long sentence: ty", "`ty`",
    "ty.py", "@ty", "#ty", "Ty:", "_ty", "party", "ty's", "NP-hard",
])
def test_non_message_identity_or_protected_content_is_not_removed_or_direct_translated(source):
    model = Model()
    plan = prepare_chat_translation(source)
    expected = expand_chat_slang(source)
    assert plan.cache_source == expected
    assert plan.translate(model, "en-zh") == "模型译文：" + expected
    assert model.calls == [(expected, "en-zh")]


def test_links_and_code_in_named_body_are_preserved_during_expansion():
    source = "Ty: https://example.com/ty `np` ty"
    model = Model()
    assert prepare_chat_translation(source).translate(model, "en-zh") == (
        "Ty: 模型译文：https://example.com/ty `np` thanks")
    assert model.calls == [("https://example.com/ty `np` thanks", "en-zh")]


@pytest.mark.parametrize("source,mode,enabled,expected", [
    ("Ty: ty\nNp: np", "continuous", True, "lines"),
    ("[Team] Ty: ty\n[Other] Np: np", "continuous", True, "lines"),
    ("Ty: ty\nNp: np", "continuous", False, "continuous"),
    ("Ty: ty\nsoft wrapped text", "continuous", True, "continuous"),
    ("The train leaves\nin ten minutes", "continuous", True, "continuous"),
    ("https://example.com/ty\nC:/Games/np", "continuous", True, "continuous"),
    ("12:30\n13:40", "continuous", True, "continuous"),
    ("The train leaves\nin ten minutes", "lines", True, "lines"),
    ("Ty: ty\nNp: np", "lines", False, "lines"),
])
def test_source_layout_preserves_only_confident_multiple_named_messages(
        source, mode, enabled, expected):
    assert chat_source_layout(source, mode, enabled) == expected


@pytest.mark.parametrize("source,layout,expected", [
    ("ty for the help\nnp at all", "continuous", "thanks for the help no problem at all"),
    ("ty for the help\nnp at all", "lines", "thanks for the help\nno problem at all"),
    ("The train leaves\nin ten minutes.", "continuous", "The train leaves in ten minutes."),
])
def test_ordinary_longer_text_keeps_one_model_call_and_old_cache_source(source, layout, expected):
    model = Model()
    plan = prepare_chat_translation(source, layout)
    assert plan.cache_source == expected
    assert plan.translate(model, "en-zh") == "模型译文：" + expected
    assert model.calls == [(expected, "en-zh")]


def test_special_cache_source_is_canonical_and_covers_prefix_body_expansion_direct():
    plan = prepare_chat_translation("Ty: ty\nNp: np", "continuous")
    material = json.loads(plan.cache_source)
    assert material == {
        "version": 3, "layout": "lines", "rows": [
            {"prefix": "Ty: ", "body": "ty", "expanded": "thanks", "direct": "谢谢"},
            {"prefix": "Np: ", "body": "np", "expanded": "no problem", "direct": "没问题"},
        ],
    }
    assert plan.cache_source == json.dumps(material, ensure_ascii=False, sort_keys=True,
                                          separators=(",", ":"))
    assert plan.cache_source != prepare_chat_translation("Other: ty\nNp: np").cache_source
    assert plan.cache_source != prepare_chat_translation("Ty: ty\nNp: np", overrides={
        "ty": "thank you"}).cache_source


def test_direct_cache_material_is_not_the_old_expanded_plain_source():
    plan = prepare_chat_translation("ty")
    old_key = make_cache_key("fake-model", "en-zh", "ty", translation_policy="old-policy",
                             model_source="thanks")
    new_key = make_cache_key("fake-model", "en-zh", "ty", translation_policy="new-policy",
                             model_source=plan.cache_source)
    assert old_key != new_key
    assert plan.cache_source != "thanks"


def test_adapter_policy_is_versioned_and_changes_with_sanitized_custom_rules():
    default = chat_translation_fingerprint()
    from screen_translator.core.chinese_script import SCRIPT_POLICY_ID
    assert default == "chat-translation-v3|" + chat_slang_fingerprint(True) + "|" + SCRIPT_POLICY_ID
    assert default != chat_slang_fingerprint(True)
    assert default == chat_translation_fingerprint({"ty": "thanks"})
    assert default != chat_translation_fingerprint({"ty": "np"})
    assert chat_translation_fingerprint({"TY": " thank you "}) == (
        chat_translation_fingerprint({"ty": "thank you"}))


def test_plan_and_row_snapshot_are_frozen():
    plan = prepare_chat_translation("Ty: ty")
    with pytest.raises(FrozenInstanceError):
        plan.cache_source = "mutated"
    with pytest.raises(FrozenInstanceError):
        plan._rows[0].prefix = "mutated"


@pytest.mark.parametrize("source", ["ty", "Ty: ty", "ty for the help", "Ty: hello"])
def test_pre_cancelled_plan_does_not_call_model_or_produce_even_direct_answer(source):
    model = Model()
    with pytest.raises(InferenceCancelled):
        prepare_chat_translation(source).translate(model, "en-zh", lambda: True)
    assert model.calls == []


def test_direct_answer_is_cancel_checked_after_its_lookup_before_return():
    checks = iter([False, False, True])
    with pytest.raises(InferenceCancelled):
        prepare_chat_translation("ty").translate(Model(), "en-zh", lambda: next(checks))


def test_cancel_between_rows_never_calls_next_model_or_returns_partial_result():
    checked = 0

    def cancel_check():
        nonlocal checked
        checked += 1
        return checked >= 4

    model = Model()
    with pytest.raises(InferenceCancelled):
        prepare_chat_translation("Ty: ty\nOther: ordinary text").translate(
            model, "en-zh", cancel_check)
    assert model.calls == []


def test_plain_model_completion_rechecks_freshness():
    stale = False

    class BecomingStaleModel(Model):
        def translate(self, text, direction):
            nonlocal stale
            stale = True
            return super().translate(text, direction)

    model = BecomingStaleModel()
    with pytest.raises(InferenceCancelled):
        prepare_chat_translation("ordinary sentence").translate(model, "en-zh", lambda: stale)
    assert model.calls == [("ordinary sentence", "en-zh")]


def test_named_model_completion_rechecks_freshness_without_returning_username_only():
    stale = False

    class BecomingStaleModel(Model):
        def translate(self, text, direction):
            nonlocal stale
            stale = True
            return super().translate(text, direction)

    model = BecomingStaleModel()
    with pytest.raises(InferenceCancelled):
        prepare_chat_translation("Ty: ordinary sentence").translate(model, "en-zh", lambda: stale)
    assert model.calls == [("ordinary sentence", "en-zh")]


def test_cancellable_translator_receives_original_cancel_callback():
    checks = []

    def cancel_check():
        checks.append(1)
        return False

    class CancellableModel(Model):
        def translate_cancellable(self, text, direction, received):
            assert received is cancel_check
            assert not received()
            return self.translate(text, direction)

    model = CancellableModel()
    assert prepare_chat_translation("Ty: ty for the help").translate(
        model, "en-zh", cancel_check) == "Ty: 模型译文：thanks for the help"
    assert len(checks) >= 5
    assert model.calls == [("thanks for the help", "en-zh")]


@pytest.mark.parametrize("value", ["", "  ", None, 4])
def test_empty_model_body_is_not_hidden_by_preserved_username(value):
    class EmptyModel(Model):
        def translate(self, text, direction):
            return value

    with pytest.raises(RuntimeError, match="空译文"):
        prepare_chat_translation("Ty: ordinary sentence").translate(EmptyModel(), "en-zh")


def test_empty_plan_does_not_need_a_model():
    model = Model()
    assert prepare_chat_translation("\n  ").translate(model, "en-zh", lambda: False) == ""
    assert model.calls == []
