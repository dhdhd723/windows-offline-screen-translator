"""Synthetic slang policy integration; no desktop or game interaction."""

from __future__ import annotations

import threading
from dataclasses import replace

import pytest

from screen_translator.contracts import Region, Settings
from screen_translator.core.chat_slang import chat_slang_fingerprint, expand_chat_slang
from screen_translator.core.chat_translation import (chat_translation_fingerprint,
                                                    prepare_chat_translation)
from screen_translator.core.pipeline import Pipeline
from screen_translator.core.text import normalize_layout_text
from screen_translator.storage.translation_cache import TranslationCache, make_cache_key

from test_dialogue_layout_pipeline import OCR, Screen, Translator, wait_for


REGION = Region(0, 0, 64, 32)


@pytest.fixture
def make_pipeline():
    instances = []

    def factory(texts, *, text_layout="lines", direction="auto", enabled=True,
                overrides=None, translator=None, cache=None):
        settings = Settings(text_layout=text_layout, direction=direction,
                            chat_slang_enabled=enabled, chat_slang_overrides=overrides or {},
                            capture_fps=12, idle_fps=6, debounce_ms=80,
                            min_ocr_interval_ms=200)
        screen, ocr = Screen(), OCR(texts)
        translator = translator or Translator()
        results, statuses = [], []
        pipeline = Pipeline(settings, ocr, translator, cache or TranslationCache(),
                            results.append, statuses.append, screen.backend)
        instances.append((pipeline, translator))
        return pipeline, screen, ocr, translator, results, settings

    yield factory
    for pipeline, translator in instances:
        translator.release.set()
        pipeline.shutdown(2)


def test_standalone_slang_translates_directly_without_changing_original_dialogue(make_pipeline):
    source = "Ty: ty!\nnp."
    pipeline, _, _, translator, results, _ = make_pipeline({40: source})
    pipeline.start(REGION)
    wait_for(lambda: len(results) == 1)
    assert translator.calls == []
    assert results[0].source == source
    assert results[0].translation == "Ty: 谢谢!\n没问题."
    assert results[0].direction == "en-zh"
    assert len(results[0].source.splitlines()) == len(results[0].translation.splitlines()) == 2


@pytest.mark.parametrize("text_layout", ["continuous", "lines"])
@pytest.mark.parametrize("source,expected", [("ty", "谢谢"), ("np", "没问题")])
def test_standalone_slang_works_in_both_layouts_by_default(make_pipeline, text_layout,
                                                        source, expected):
    pipeline, _, _, translator, results, _ = make_pipeline({40: source},
                                                          text_layout=text_layout)
    pipeline.start(REGION)
    wait_for(lambda: len(results) == 1)
    assert translator.calls == []
    assert results[0].source == source
    assert results[0].translation == expected
    assert results[0].direction == "en-zh"


def test_longer_slang_expands_one_model_batch_without_changing_dialogue(make_pipeline):
    source = "ty for the help!\nnp at all."
    pipeline, _, _, translator, results, _ = make_pipeline({40: source})
    pipeline.start(REGION)
    wait_for(lambda: len(results) == 1)
    assert translator.calls == [("thanks for the help!\nno problem at all.", "en-zh")]
    assert results[0].source == source
    assert results[0].translation == "译：thanks for the help!\n译：no problem at all."


@pytest.mark.parametrize("text_layout", ["continuous", "lines"])
def test_named_longer_body_keeps_speaker_out_of_model(make_pipeline, text_layout):
    source = "Ty:ty for the help!"
    pipeline, _, _, translator, results, _ = make_pipeline({40: source},
                                                          text_layout=text_layout)
    pipeline.start(REGION)
    wait_for(lambda: len(results) == 1)
    assert translator.calls == [("thanks for the help!", "en-zh")]
    assert results[0].source == source
    assert results[0].translation == "Ty:译：thanks for the help!"


@pytest.mark.parametrize("text_layout", ["continuous", "lines"])
@pytest.mark.parametrize("source,expected", [
    ("Ty:ty!", "Ty:谢谢!"),
    ("Ty: ty!", "Ty: 谢谢!"),
    ("Player: take lead", "Player: 带头"),
])
def test_named_standalone_preserves_prefix_bytes_without_using_model(make_pipeline,
                                                                    text_layout, source,
                                                                    expected):
    pipeline, _, _, translator, results, _ = make_pipeline({40: source},
                                                          text_layout=text_layout)
    pipeline.start(REGION)
    wait_for(lambda: len(results) == 1)
    assert translator.calls == []
    assert results[0].source == source
    assert results[0].translation == expected


@pytest.mark.parametrize("text_layout", ["continuous", "lines"])
def test_two_named_messages_preserve_rows_even_in_default_layout(make_pipeline, text_layout):
    source = "First:ty!\nSecond:np."
    pipeline, _, _, translator, results, _ = make_pipeline({40: source},
                                                          text_layout=text_layout)
    pipeline.start(REGION)
    wait_for(lambda: len(results) == 1)
    assert translator.calls == []
    assert results[0].source == source
    assert results[0].translation == "First:谢谢!\nSecond:没问题."


def test_default_continuous_short_reply_sequence_uses_direct_composition(make_pipeline):
    pipeline, _, _, translator, results, _ = make_pipeline(
        {40: "ty!\nnp."}, text_layout="continuous")
    pipeline.start(REGION)
    wait_for(lambda: len(results) == 1)
    assert results[0].source == "ty! np."
    assert translator.calls == []
    assert results[0].translation == "谢谢!，没问题."


def test_default_continuous_plain_soft_wrap_stays_one_model_batch(make_pipeline):
    pipeline, _, _, translator, results, _ = make_pipeline(
        {40: "ty for helping!\npls wait."}, text_layout="continuous")
    pipeline.start(REGION)
    wait_for(lambda: len(results) == 1)
    assert results[0].source == "ty for helping! pls wait."
    assert translator.calls == [("thanks for helping! please wait.", "en-zh")]
    assert results[0].translation == "译：thanks for helping! please wait."


@pytest.mark.parametrize("text_layout,direction,enabled,source", [
    ("lines", "zh-en", True, "你好np\n请等一下ty"),
    ("continuous", "zh-en", True, "你好np\n请等一下ty"),
    ("lines", "en-zh", False, "ty!\nnp."),
    ("continuous", "en-zh", False, "ty!\nnp."),
])
def test_inactive_mode_or_direction_does_not_expand(make_pipeline, text_layout, direction,
                                                  enabled, source):
    expected = normalize_layout_text(source, text_layout)
    pipeline, _, _, translator, results, _ = make_pipeline(
        {40: source}, text_layout=text_layout, direction=direction, enabled=enabled,
        overrides={"ty": "thank you"})
    pipeline.start(REGION)
    wait_for(lambda: len(results) == 1)
    assert translator.calls == [(expected, direction)]
    assert results[0].source == expected
    assert results[0].translation == "\n".join("译：" + row for row in expected.splitlines())


def test_static_and_cosmetic_ocr_noise_deduplicate_original_not_expanded_text(make_pipeline):
    sources = {40: "ty for the help!\nnp at all.",
               100: "ty for the help.\nnp at all!", 160: "ty for the help.\nnp at all!"}
    pipeline, screen, ocr, translator, results, _ = make_pipeline(sources)
    pipeline.start(REGION)
    wait_for(lambda: len(results) == 1)
    threading.Event().wait(0.35)
    assert len(ocr.calls) == 1
    assert len(translator.calls) == 1
    screen.set(100)
    wait_for(lambda: 100 in ocr.calls)
    screen.set(160)
    wait_for(lambda: 160 in ocr.calls)
    threading.Event().wait(0.25)
    assert len(results) == len(translator.calls) == 1
    assert results[0].source == sources[40]


def test_short_row_punctuation_keeps_existing_conservative_refresh_rule(make_pipeline):
    # The pre-existing <=4 character gate treats even punctuation as meaningful.
    # Slang expansion must not silently replace that original-source policy.
    sources = {40: "ty!\nnp.", 100: "ty.\nnp!"}
    pipeline, screen, _, translator, results, _ = make_pipeline(sources)
    pipeline.start(REGION)
    wait_for(lambda: len(results) == 1)
    screen.set(100)
    wait_for(lambda: len(results) == 2)
    assert results[-1].source == sources[100]
    assert translator.calls == []
    assert results[0].translation == "谢谢!\n没问题."
    assert results[-1].translation == "谢谢.\n没问题!"


def test_clear_suppresses_original_source_and_allows_new_original_dialogue(make_pipeline):
    sources = {40: "ty for helping!\nnp today.", 100: "brb soon!\npls come."}
    pipeline, screen, ocr, translator, results, _ = make_pipeline(sources)
    pipeline.start(REGION)
    wait_for(lambda: len(results) == 1)
    pipeline.clear()
    wait_for(lambda: len(ocr.calls) >= 2)
    threading.Event().wait(0.25)
    assert results[-1].translation == ""
    assert len(translator.calls) == 1
    screen.set(100)
    wait_for(lambda: results[-1].source == sources[100])
    assert results[-1].translation == "译：be right back soon!\n译：please come."


@pytest.mark.parametrize("change", ["override", "disable"])
def test_policy_change_during_blocked_translation_never_publishes_old_policy(make_pipeline,
                                                                           change):
    source = "ty for helping!\nnp today."
    translator = Translator(block_first=True)
    pipeline, screen, _, translator, results, settings = make_pipeline(
        {40: source}, translator=translator, overrides={"ty": "thank you"})
    pipeline.start(REGION)
    assert translator.entered.wait(3)
    old_generation = pipeline.generation
    if change == "override":
        new_settings = replace(settings, chat_slang_overrides={"ty": "many thanks"})
        expected_model_source = "many thanks for helping!\nno problem today."
    else:
        new_settings = replace(settings, chat_slang_enabled=False)
        expected_model_source = source
    pipeline.update_settings(new_settings)
    assert pipeline.generation > old_generation
    translator.release.set()
    wait_for(lambda: bool(results))
    assert all(result.source == source for result in results)
    assert all(result.generation == pipeline.generation for result in results)
    assert all(result.translation == "\n".join("译：" + row
               for row in expected_model_source.splitlines()) for result in results)
    assert translator.calls[-1] == (expected_model_source, "en-zh")
    wait_for(lambda: screen.closed >= 1)


def test_active_slang_does_not_hit_old_non_policy_cache_and_restart_uses_new_cache(make_pipeline):
    source = "ty!\nnp."
    translator = Translator()
    cache = TranslationCache()
    cache.put(make_cache_key(translator.model_id("en-zh"), "en-zh", source,
                             text_layout="lines"), "Old literal slang translation")
    cache.put(make_cache_key(translator.model_id("en-zh"), "en-zh", source,
                             text_layout="lines",
                             translation_policy=chat_slang_fingerprint(True),
                             model_source=expand_chat_slang(source)),
              "Old expanded slang translation")
    pipeline, _, _, translator, results, _ = make_pipeline(
        {40: source}, translator=translator, cache=cache)
    pipeline.start(REGION)
    wait_for(lambda: len(results) == 1)
    assert not results[0].cache_hit
    assert results[0].translation == "谢谢!\n没问题."
    assert translator.calls == []
    plan = prepare_chat_translation(source, "lines")
    assert cache.get(make_cache_key(translator.model_id("en-zh"), "en-zh", source,
                                   text_layout="lines",
                                   translation_policy=chat_translation_fingerprint(),
                                   model_source=plan.cache_source)) == "谢谢!\n没问题."
    pipeline.stop()
    pipeline.start(REGION)
    wait_for(lambda: len(results) == 2)
    assert results[-1].cache_hit
    assert translator.calls == []
    assert results[-1].translation == "谢谢!\n没问题."


@pytest.mark.parametrize("change", ["override", "disable", "unused_term"])
def test_policy_changes_isolate_cache_even_when_original_source_is_same(make_pipeline, change):
    source = "ty for helping!\nnp today."
    pipeline, _, _, translator, results, settings = make_pipeline({40: source})
    pipeline.start(REGION)
    wait_for(lambda: len(results) == 1)
    old_generation = pipeline.generation
    if change == "override":
        updated = replace(settings, chat_slang_overrides={"ty": "thank you"})
        expected = "thank you for helping!\nno problem today."
    elif change == "disable":
        updated = replace(settings, chat_slang_enabled=False)
        expected = source
    else:
        updated = replace(settings, chat_slang_overrides={"zz": "all good"})
        expected = "thanks for helping!\nno problem today."
    pipeline.update_settings(updated)
    wait_for(lambda: len(results) == 2)
    assert pipeline.generation > old_generation
    assert not results[-1].cache_hit
    assert len(translator.calls) == 2
    assert translator.calls[-1] == (expected, "en-zh")
    assert results[-1].source == source
    assert results[-1].translation == "\n".join("译：" + row for row in expected.splitlines())


def test_inactive_slang_keeps_ordinary_cache_key(make_pipeline):
    source = "ty!\nnp."
    translator = Translator()
    cache = TranslationCache()
    cache.put(make_cache_key(translator.model_id("en-zh"), "en-zh", source,
                             text_layout="lines"), "Existing regular translation")
    pipeline, _, _, translator, results, _ = make_pipeline(
        {40: source}, enabled=False, translator=translator, cache=cache)
    pipeline.start(REGION)
    wait_for(lambda: len(results) == 1)
    assert results[0].cache_hit
    assert results[0].translation == "Existing regular translation"
    assert not translator.calls


def test_cache_key_distinguishes_policy_and_effective_model_source():
    source = "ty!\nnp."
    model_id, direction = "dialogue-fake-en-zh", "en-zh"
    policy = chat_translation_fingerprint()
    model_source = prepare_chat_translation(source, "lines").cache_source
    plain = make_cache_key(model_id, direction, source, text_layout="lines")
    expanded = make_cache_key(model_id, direction, source, text_layout="lines",
                              translation_policy=policy, model_source=model_source)
    assert plain != expanded
    assert expanded != make_cache_key(model_id, direction, source, text_layout="lines",
                                      translation_policy=chat_translation_fingerprint(
                                          {"zz": "all good"}), model_source=model_source)
    assert expanded != make_cache_key(model_id, direction, source, text_layout="lines",
                                      translation_policy=policy, model_source="thank you!\nno problem.")
