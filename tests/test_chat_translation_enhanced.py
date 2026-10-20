"""Offline adapter-contract checks, not neural translation quality evidence."""
from __future__ import annotations

import json

import pytest

from screen_translator.core.chat_messages import CHAT_MESSAGE_POLICY_ID
from screen_translator.core.chat_normalization import CHAT_CANDIDATES_VERSION
from screen_translator.core.chat_translation import (
    _named_row, chat_source_layout, chat_translation_fingerprint, prepare_chat_translation,
)
from screen_translator.inference import InferenceCancelled, InputLimitError


class EnhancedModel:
    def __init__(self):
        self.calls = []

    def translate_chat(self, text, direction, *, hints, cancel_check):
        self.calls.append((text, direction, hints, cancel_check))
        return "增强译文：" + text

    def translate(self, text, direction):
        raise AssertionError("enhanced must never silently call fast translate")


@pytest.mark.parametrize("source", [
    "im low can u cover me", "ngl that was clean", "u good?", "def hold base",
    "ur aim is clean", "2 medkits", "oms report oms",
])
def test_enhanced_model_receives_unexpanded_body_and_nonbinding_hints(source):
    model = EnhancedModel()
    plan = prepare_chat_translation(source, mode="enhanced")
    assert plan.mode == "enhanced"
    assert plan.translate(model, "en-zh") == "增强译文：" + source
    assert len(model.calls) == 1
    text, direction, hints, cancel_check = model.calls[0]
    assert text == source and direction == "en-zh" and cancel_check is None
    assert all(text[hint.start:hint.end] == hint.token for hint in hints)


def test_default_fast_still_expands_the_original_sentence():
    class FastModel:
        def translate(self, text, direction):
            assert text == "definitely hold base" and direction == "en-zh"
            return "轻量译文"

    default = prepare_chat_translation("def hold base")
    explicit = prepare_chat_translation("def hold base", mode="fast")
    assert default.cache_source == explicit.cache_source == "definitely hold base"
    assert default.translate(FastModel(), "en-zh") == "轻量译文"


@pytest.mark.parametrize("source,answer", [("ty", "谢谢"), ("np!", "没问题!"),
                                           ("Player: ty", "Player: 谢谢")])
def test_clear_standalone_replies_remain_direct_in_enhanced(source, answer):
    model = EnhancedModel()
    assert prepare_chat_translation(source, mode="enhanced").translate(model, "en-zh") == answer
    assert model.calls == []


@pytest.mark.parametrize("token", ["def", "bc", "fr", "rn"])
@pytest.mark.parametrize("wrapper", ["{}", "({})!", '"{}"'])
def test_ambiguous_standalone_terms_are_not_forced_to_a_direct_answer(token, wrapper):
    source = wrapper.format(token)
    model = EnhancedModel()
    assert prepare_chat_translation(source, mode="enhanced").translate(model, "en-zh") == (
        "增强译文：" + source)
    assert model.calls[0][0] == source


def test_different_named_users_are_independent_requests_in_both_layouts():
    for layout in ("continuous", "lines"):
        model = EnhancedModel()
        source = "Ty: im low\nNp: def hold base\n玩家_一: u good?"
        actual = prepare_chat_translation(source, layout, mode="enhanced").translate(model, "en-zh")
        assert actual == "Ty: 增强译文：im low\nNp: 增强译文：def hold base\n玩家_一: 增强译文：u good?"
        assert [call[0] for call in model.calls] == ["im low", "def hold base", "u good?"]
        assert all("Ty" not in call[0] and "Np" not in call[0] and "玩家" not in call[0]
                   for call in model.calls)


def test_explicit_lines_never_combines_unnamed_messages():
    model = EnhancedModel()
    prepare_chat_translation("im low\nu good?", "lines", mode="enhanced").translate(model, "en-zh")
    assert [call[0] for call in model.calls] == ["im low", "u good?"]


@pytest.mark.parametrize("prefix", ["Cool Guy: ", "[Cool Guy]: ", "[Team] Cool Guy: ",
                                   "Captain Awesome Dude: "])
def test_display_names_are_opt_in_and_never_sent_to_enhanced_model(prefix):
    source = prefix + "im low"
    assert _named_row(source) is None
    assert _named_row(source, allow_display_name=True) == (prefix, "im low")
    model = EnhancedModel()
    assert prepare_chat_translation(source, "lines", mode="enhanced").translate(model, "en-zh") == (
        prefix + "增强译文：im low")
    assert model.calls[0][0] == "im low"


@pytest.mark.parametrize("source", [
    "cool guy: im low", "This is a long sentence: ty", "https://example.com/ty",
    "C:\\Games\\ty", "C:/Games/ty", "12:30", "123: 456",
    "First Second Third Fourth: im low", "Aaaaaaaaaaaaaaaa Bbbbbbbbbbbbbbbb: im low",
])
def test_display_name_policy_rejects_unproven_phrases_and_paths(source):
    assert _named_row(source, allow_display_name=True) is None


def test_display_name_rule_does_not_change_default_auto_layout():
    assert chat_source_layout("Cool Guy: ty\nOther Person: np") == "continuous"


def test_custom_sense_is_snapshotted_prioritized_and_keeps_original_body():
    model = EnhancedModel()
    overrides = {"def": "defense", "zz": "a user custom term"}
    source = "ngl def hold base zz"
    plan = prepare_chat_translation("Name: " + source, overrides=overrides, mode="enhanced")
    overrides["def"] = "a changed later value"
    plan.translate(model, "en-zh")
    text, _, hints, _ = model.calls[0]
    assert text == source
    assert [(hint.token, hint.candidates) for hint in hints][:2] == [
        ("def", ("defense",)), ("zz", ("a user custom term",)),
    ]
    assert hints[-1].token == "ngl"


def test_custom_short_reply_disables_direct_answer_without_rewriting_raw():
    model = EnhancedModel()
    prepare_chat_translation("ty", overrides={"ty": "many thanks"}, mode="enhanced").translate(
        model, "en-zh")
    assert model.calls[0][0] == "ty"
    assert model.calls[0][2][0].candidates == ("many thanks",)


def test_unsupported_backend_raises_instead_of_silently_using_fast():
    class FastOnly:
        def translate(self, text, direction):
            raise AssertionError("must not use fast")

    with pytest.raises(RuntimeError, match="不支持增强聊天接口"):
        prepare_chat_translation("u good?", mode="enhanced").translate(FastOnly(), "en-zh")


@pytest.mark.parametrize("mode", ["", "turbo", None, True])
def test_unknown_modes_are_rejected(mode):
    with pytest.raises(ValueError, match="模式"):
        prepare_chat_translation("ty", mode=mode)
    with pytest.raises(ValueError, match="模式"):
        chat_translation_fingerprint(mode=mode)


def test_enhanced_cache_binds_raw_candidates_mode_and_geometry_policy():
    plan = prepare_chat_translation("Player: def hold base", "lines", mode="enhanced")
    material = json.loads(plan.cache_source)
    assert material["mode"] == "enhanced"
    assert material["candidate_version"] == CHAT_CANDIDATES_VERSION
    assert material["message_policy"] == CHAT_MESSAGE_POLICY_ID
    assert material["rows"][0]["body"] == material["rows"][0]["expanded"] == "def hold base"
    assert material["rows"][0]["hints"][0]["candidates"] == ["definitely", "defense"]
    assert plan.cache_source != prepare_chat_translation("Player: def hold base", "lines").cache_source
    assert plan.cache_source != prepare_chat_translation("Other: def hold base", "lines",
                                                        mode="enhanced").cache_source
    assert plan.cache_source != prepare_chat_translation("Player: def hold base", "lines",
                                                        {"def": "defense"},
                                                        mode="enhanced").cache_source
    fingerprint = chat_translation_fingerprint(mode="enhanced")
    assert "mode=enhanced" in fingerprint
    assert f"chat-candidates-v{CHAT_CANDIDATES_VERSION}" in fingerprint
    assert CHAT_MESSAGE_POLICY_ID in fingerprint
    assert fingerprint != chat_translation_fingerprint()
    assert fingerprint != chat_translation_fingerprint({"def": "defense"}, mode="enhanced")


def test_pre_cancelled_plan_calls_neither_backend_nor_direct_answer():
    model = EnhancedModel()
    for source in ("ty", "u good?", "Player: im low"):
        with pytest.raises(InferenceCancelled):
            prepare_chat_translation(source, mode="enhanced").translate(model, "en-zh", lambda: True)
    assert model.calls == []


def test_original_cancel_callback_is_forwarded_and_stale_completion_is_rejected():
    stale = False

    def cancel_check():
        return stale

    class BecomingStale(EnhancedModel):
        def translate_chat(self, text, direction, *, hints, cancel_check):
            nonlocal stale
            assert not cancel_check()
            stale = True
            return super().translate_chat(text, direction, hints=hints, cancel_check=cancel_check)

    model = BecomingStale()
    with pytest.raises(InferenceCancelled):
        prepare_chat_translation("Player: im low\nOther: help me", "lines", mode="enhanced").translate(
            model, "en-zh", cancel_check)
    assert len(model.calls) == 1
    assert model.calls[0][0] == "im low" and model.calls[0][3] is cancel_check


@pytest.mark.parametrize("value", ["", "  ", None, 4])
def test_invalid_enhanced_result_is_not_masked_by_username(value):
    class Invalid(EnhancedModel):
        def translate_chat(self, text, direction, *, hints, cancel_check):
            return value

    with pytest.raises(RuntimeError, match="空译文"):
        prepare_chat_translation("Player: im low", mode="enhanced").translate(Invalid(), "en-zh")


def test_empty_enhanced_plan_and_oversized_source_are_handled_without_truncation():
    model = EnhancedModel()
    assert prepare_chat_translation("\n ", mode="enhanced").translate(model, "en-zh") == ""
    assert model.calls == []
    with pytest.raises(InputLimitError):
        prepare_chat_translation("im low\n" * 3000, "lines", mode="enhanced")


def test_disabled_slang_retains_message_identity_isolation_without_hints_or_direct_answers():
    model = EnhancedModel()
    plan = prepare_chat_translation("Cool Guy: ty\nOther: def hold base", "lines",
                                    {"ty": "custom thanks", "def": "custom sense"},
                                    mode="enhanced", slang_enabled=False)
    assert plan.translate(model, "en-zh") == "Cool Guy: 增强译文：ty\nOther: 增强译文：def hold base"
    assert [call[0] for call in model.calls] == ["ty", "def hold base"]
    assert all(call[2] == () for call in model.calls)


def test_disabled_slang_cache_ignores_inactive_overrides_and_differs_from_enabled():
    source = "Cool Guy: ty"
    plan = prepare_chat_translation(source, "lines", mode="enhanced", slang_enabled=False)
    assert plan.cache_source == prepare_chat_translation(source, "lines", {"ty": "many thanks"},
        mode="enhanced", slang_enabled=False).cache_source
    assert plan.cache_source != prepare_chat_translation(source, "lines", mode="enhanced").cache_source
    policy = chat_translation_fingerprint(mode="enhanced", slang_enabled=False)
    assert policy == chat_translation_fingerprint({"ty": "many thanks"}, mode="enhanced",
                                                  slang_enabled=False)
    assert policy != chat_translation_fingerprint(mode="enhanced")
    assert "slang=disabled" in policy


@pytest.mark.parametrize("value", [None, 0, 1, "false"])
def test_slang_switch_must_be_a_real_boolean(value):
    with pytest.raises(ValueError, match="布尔"):
        prepare_chat_translation("ty", slang_enabled=value)
    with pytest.raises(ValueError, match="布尔"):
        chat_translation_fingerprint(slang_enabled=value)
