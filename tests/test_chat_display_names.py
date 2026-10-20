"""Display-name opt-in uses the same explicit layout for language and models."""
import pytest

from screen_translator.core.chat_translation import (
    chat_direction_source, prepare_chat_translation,
)


@pytest.mark.parametrize("name", ["Cool Guy", "Other Player", "Guy Fieri", "Meat Puppy"])
@pytest.mark.parametrize("body", ["你好", "好的", "ty", "np", "Please wait for me."])
def test_explicit_lines_language_evidence_excludes_display_name(name, body):
    source = name + ": " + body
    assert chat_direction_source(source, "lines") == body
    # Continuous prose still requires the stricter single-identity grammar.
    assert chat_direction_source(source, "continuous") == source


@pytest.mark.parametrize("enabled", [True, False])
def test_explicit_lines_model_input_keeps_name_out_even_with_glossary_off(enabled):
    calls = []

    class Translator:
        def translate(self, text, direction):
            calls.append(text)
            return "请等我。"

    source = "Cool Guy: Please wait for me.\nOther Player: Please wait for me."
    plan = prepare_chat_translation(source, "lines", slang_enabled=enabled)
    assert plan.translate(Translator(), "en-zh") == (
        "Cool Guy: 请等我。\nOther Player: 请等我。")
    assert calls == ["Please wait for me.", "Please wait for me."]


@pytest.mark.parametrize("source", [
    "cool guy: ty", "This phrase is far too long: ty",
    "Here is a sentence: please wait", "https://example.test/ty", "C:/example/ty",
])
def test_uncertain_lowercase_long_phrase_url_and_path_are_not_display_names(source):
    assert chat_direction_source(source, "lines") == source
