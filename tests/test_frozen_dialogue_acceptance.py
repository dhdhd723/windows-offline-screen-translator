"""Pure fixture/key/assertion tests; no capture, desktop input or exe is run."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest

from screen_translator.core.text import normalize_layout_text, normalize_text
from screen_translator.core.chat_slang import chat_slang_fingerprint, expand_chat_slang
from screen_translator.core.chat_translation import chat_translation_fingerprint, prepare_chat_translation
from screen_translator.core.game_terms import translation_identity
from screen_translator.storage.translation_cache import make_cache_key


@pytest.fixture(scope="module")
def helper():
    path = Path(__file__).resolve().parents[1] / "tools" / "frozen_capture_acceptance.py"
    spec = importlib.util.spec_from_file_location("frozen_dialogue_acceptance_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_default_fixtures_remain_two_single_line_directions(helper):
    stages = helper._caption_stages("continuous")
    assert [(stage.caption, stage.direction) for stage in stages] == [
        ("The translation works offline.", "en-zh"),
        ("屏幕翻译支持离线运行。", "zh-en"),
    ]
    assert all(stage.line_word_groups is None for stage in stages)


def test_dialogue_fixtures_preserve_two_rows_and_control_second_row_change(helper):
    english, chinese, changed, boundary = helper._caption_stages("lines")
    assert english.direction == "en-zh" and chinese.direction == changed.direction == "zh-en"
    assert all(len(stage.caption.splitlines()) == 2 and len(stage.line_word_groups) == 2
               for stage in (english, chinese, changed, boundary))
    old_rows, new_rows = chinese.caption.splitlines(), changed.caption.splitlines()
    assert old_rows == ["屏幕翻译支持离线运行。", "火车已经到站了"]
    assert new_rows == ["屏幕翻译支持离线运行。", "火车将在10分钟后离开"]
    assert boundary.caption.splitlines() == ["屏幕翻译支持", "离线运行。 火车将在10分钟后离开"]
    assert old_rows[0] == new_rows[0] and old_rows[1] != new_rows[1]
    assert changed.stable_first_line_from == chinese.name
    assert boundary.same_flattened_source_as_previous
    assert normalize_text(boundary.caption) == normalize_text(changed.caption)
    assert normalize_layout_text(boundary.caption, "lines") != normalize_layout_text(changed.caption, "lines")


@pytest.mark.parametrize("layout", ["continuous", "lines"])
def test_expected_cache_key_uses_layout_aware_normalization_and_mode(helper, tmp_path, layout):
    exe = tmp_path / "ScreenTranslator.exe"
    models = tmp_path / "models"
    models.mkdir()
    (models / "manifest.json").write_text(json.dumps({"translation": {"en-zh": {"id": "fixture-model"}}}),
                                          encoding="utf-8")
    text = " First sentence.\n Second sentence. "
    source = normalize_layout_text(text, layout)
    policy = chat_translation_fingerprint()
    assert helper._expected_cache_key(exe, "en-zh", text, layout) == make_cache_key(
        translation_identity("fixture-model", "en-zh"), "en-zh", source, text_layout=layout,
        translation_policy=policy, model_source=prepare_chat_translation(source, layout).cache_source)


def test_optional_chat_slang_fixture_is_exactly_two_independent_rows(helper):
    stages = helper._caption_stages("lines", chat_slang_samples=True)
    assert len(stages) == 5
    slang = stages[-1]
    assert slang.caption == "tys, that helped a lot!\nnp, you are welcome."
    assert expand_chat_slang(slang.caption) == "thanks, that helped a lot!\nno problem, you are welcome."
    assert len(slang.line_word_groups) == 2 and slang.direction == "en-zh"
    helper._verify_translation("谢谢，那帮了大忙！\n没问题，不客气。", (), line_word_groups=slang.line_word_groups)
    with pytest.raises(RuntimeError):
        helper._verify_translation("没问题，那帮了大忙！\n谢谢，不客气。", (), line_word_groups=slang.line_word_groups)
    with pytest.raises(ValueError):
        helper._caption_stages("continuous", chat_slang_samples=True)


def test_identical_flattened_words_with_different_boundaries_have_distinct_keys(helper, tmp_path):
    models = tmp_path / "models"
    models.mkdir()
    (models / "manifest.json").write_text(json.dumps({"translation": {"zh-en": {"id": "fixture-model"}}}),
                                          encoding="utf-8")
    stages = helper._caption_stages("lines")
    exe = tmp_path / "ScreenTranslator.exe"
    assert helper._expected_cache_key(exe, "zh-en", stages[2].caption, "lines") != helper._expected_cache_key(
        exe, "zh-en", stages[3].caption, "lines")
    assert helper._expected_cache_key(exe, "zh-en", stages[2].caption) == helper._expected_cache_key(
        exe, "zh-en", stages[3].caption)


@pytest.mark.parametrize("translation", ["翻译可以离线进行。\n火车在车站。", "翻译可以离线进行。\n列车在站台。"])
def test_two_row_validation_accepts_own_row_meaning_and_alternatives(helper, translation):
    stage = helper._caption_stages("lines")[0]
    helper._verify_translation(translation, stage.expected_words, line_word_groups=stage.line_word_groups)


@pytest.mark.parametrize("translation", [
    "翻译可以离线进行。 火车在车站。",  # Flattened output cannot pass.
    "火车在车站。\n翻译可以离线进行。",  # Meaning in the wrong row cannot pass.
    "翻译可以离线进行。\n",  # Missing second message cannot pass.
    "翻译可以离线进行。\n\n火车在车站。",  # Spurious empty row cannot pass.
])
def test_two_row_validation_rejects_joined_reordered_or_missing_rows(helper, translation):
    stage = helper._caption_stages("lines")[0]
    with pytest.raises(RuntimeError):
        helper._verify_translation(translation, stage.expected_words, line_word_groups=stage.line_word_groups)


def test_second_row_update_requires_unchanged_first_translation(helper):
    stage = helper._caption_stages("lines")[2]
    helper._verify_translation("Screen translation works offline.\nThe train leaves in 10 minutes.", (),
                               line_word_groups=stage.line_word_groups,
                               stable_first_line="Screen translation works offline.")
    with pytest.raises(RuntimeError, match="first translated row"):
        helper._verify_translation("The screen translation works offline.\nThe train leaves in 10 minutes.", (),
                                   line_word_groups=stage.line_word_groups,
                                   stable_first_line="Screen translation works offline.")


def test_boundary_fixture_checks_only_row_shape_not_sentence_meaning(helper):
    stage = helper._caption_stages("lines")[3]
    helper._verify_translation("First translated row.\nSecond translated row.", (),
                               line_word_groups=stage.line_word_groups)
    with pytest.raises(RuntimeError):
        helper._verify_translation("Only one translated row.", (), line_word_groups=stage.line_word_groups)


def test_unknown_fixture_layout_is_rejected(helper):
    with pytest.raises(ValueError):
        helper._caption_stages("unknown")


@pytest.mark.parametrize("arguments, expected", [([], "continuous"), (["--text-layout", "lines"], "lines")])
def test_cli_passes_default_or_explicit_layout_without_running_native(helper, monkeypatch, arguments, expected):
    received = []
    monkeypatch.setattr(sys, "argv", ["frozen_capture_acceptance.py", *arguments])
    monkeypatch.setattr(helper, "run", lambda args: received.append(args) or 0)
    assert helper.main() == 0
    assert received[0].text_layout == expected


def test_cli_rejects_unknown_layout_before_native_run(helper, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["frozen_capture_acceptance.py", "--text-layout", "unknown"])
    monkeypatch.setattr(helper, "run", lambda args: pytest.fail("native run must not start"))
    with pytest.raises(SystemExit) as error:
        helper.main()
    assert error.value.code == 2
