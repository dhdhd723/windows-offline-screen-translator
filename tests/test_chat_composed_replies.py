"""Only a short sequence of independent responses is composed deterministically."""
import pytest
from screen_translator.core.chat_translation import prepare_chat_translation


class Echo:
    def __init__(self):
        self.calls = []

    def translate(self, text, direction):
        self.calls.append(text)
        return "MODEL: " + text

    def translate_chat(self, text, direction, *, hints=(), cancel_check=None):
        self.calls.append(text)
        return "MODEL: " + text


@pytest.mark.parametrize("mode", ["fast", "enhanced"])
@pytest.mark.parametrize(("source", "target"), [
    ("ty np lol", "谢谢，没问题，哈哈"),
    ("GG, thx!", "打得不错，谢谢!"),
    ("omg lol", "天啊，哈哈"),
    ("brb; cya", "马上回来，再见"),
    ("Fixture: ty np lol!", "Fixture: 谢谢，没问题，哈哈!"),
])
def test_independent_replies_need_no_model(source, target, mode):
    engine = Echo()
    assert prepare_chat_translation(source, "lines", mode=mode).translate(engine, "en-zh") == target
    assert engine.calls == []


@pytest.mark.parametrize("source", [
    "not ty", "ty for helping", "bc ppl rn", "def fr", "the gg", "ty/np",
    "ty_np", "`ty np`", '"ty np"', "https://ty.np", "ty np lol omg gg brb",
    "unknown lol", "do not lol", "np 2", "rn lol",
])
def test_sentence_unknown_code_number_and_ambiguous_forms_are_not_composed(source):
    engine = Echo()
    assert prepare_chat_translation(source, "lines", mode="enhanced").translate(engine, "en-zh").startswith("MODEL: ")
    assert engine.calls == [source]


@pytest.mark.parametrize("mode", ["fast", "enhanced"])
def test_user_override_or_disabled_glossary_does_not_use_builtin_composition(mode):
    engine = Echo()
    plan = prepare_chat_translation("ty np lol", "lines", {"ty": "take your time"}, mode=mode)
    assert plan.translate(engine, "en-zh").startswith("MODEL: ")
    engine.calls.clear()
    plan = prepare_chat_translation("ty np lol", "lines", mode=mode, slang_enabled=False)
    assert plan.translate(engine, "en-zh").startswith("MODEL: ")
    assert engine.calls
