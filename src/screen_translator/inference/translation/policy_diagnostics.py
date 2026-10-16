"""Shipped output-policy checks on public/synthetic text, without desktop I/O."""
from __future__ import annotations

from screen_translator.core.chinese_script import to_simplified
from screen_translator.core.chat_translation import prepare_chat_translation
from screen_translator.core.translation_structure import split_complete_sentences


def evaluate_output_policy(translator) -> dict:
    fixtures = (
        ("immersive", "Immersive Experience: Realistic graphics and sounds as well as a minimal user "
         "interface ensure a totally immersive experience that will keep you on your toes."),
        ("peppa", "Join Peppa's World"),
        ("phasmophobia", "Phasmophobia is a 4-player, online co-op, psychological horror game. "
         "Use your ghost-hunting equipment to gather paranormal evidence... "
         "Before you become part of the haunting yourself."),
        ("studio", "Red Barrels invites you to experience terror, this time with friends. "
         "If you complete the therapy, Murkoff will happily let you leave... but will you be the same?"),
        ("negative_control", "The pipes release steam. The iron gate is covered in rust. Open the portal."),
    )
    native_inputs = []
    original = translator._translate_chunk

    def observed(text, direction, depth=0, *, cancel_check=None):
        native_inputs.append(text)
        return original(text, direction, depth, cancel_check=cancel_check)

    translator._translate_chunk = observed
    cases = []
    try:
        for name, source in fixtures:
            native_inputs.clear()
            result = translator.translate(source, "en-zh")
            checks = {"nonempty": bool(result.strip())}
            if name == "immersive":
                checks.update(heading="沉浸式体验" in result,
                              idiom_not_literal="脚趾" not in result and "脚步" not in result,
                              idiom_prepared=any("keep you alert" in item for item in native_inputs))
            elif name == "peppa":
                checks.update(known_title="佩奇的世界" in result,
                              no_title_in_native=not any("Peppa" in item or item == "World" for item in native_inputs))
            elif name == "phasmophobia":
                checks.update(known_title="《恐鬼症》" in result,
                    tail_submitted=any(item.startswith("Before you become") for item in native_inputs),
                    tail_output="之前" in result,
                    no_title_in_native=not any("Phasmophobia" in item for item in native_inputs))
            elif name == "studio":
                checks.update(names_preserved="Red Barrels" in result and "Murkoff" in result,
                    names_not_in_native=not any("Red Barrels" in item or "Murkoff" in item for item in native_inputs),
                    final_question_submitted=any(item.startswith("but will") for item in native_inputs))
            elif name == "negative_control":
                checks.update(ordinary_words_not_protected=len(native_inputs) == 3,
                              all_sentences_submitted=native_inputs == split_complete_sentences(source))
            cases.append({"name": name, "source": source, "translation": result,
                          "native_inputs": native_inputs.copy(), "checks": checks,
                          "passed": all(checks.values())})
    finally:
        translator._translate_chunk = original

    class Raw:
        def translate(self, text, direction):
            return "歡迎光臨乾清宮"

    script_checks = {
        "traditional_to_simplified": to_simplified("繁體中文，這是對話與試驗。") == "繁体中文，这是对话与试验。",
        "phrase_exception": to_simplified("乾清宮") == "乾清宫",
        "english_unchanged": to_simplified("Ctrl+Alt+R 123 Red Barrels") == "Ctrl+Alt+R 123 Red Barrels",
        "nickname_preserved": prepare_chat_translation("臺灣玩家: welcome").translate(Raw(), "en-zh")
                              == "臺灣玩家: 欢迎光临乾清宫",
    }
    return {"passed": all(case["passed"] for case in cases) and all(script_checks.values()),
            "cases": cases, "script_checks": script_checks,
            "policy_id": translator.quality_policy_id,
            "desktop_captured": False, "actual_games_tested": False,
            "limits": "Checks script policy, trusted names and submitted sentence tails on fixed text. Not a guarantee of general meaning, fluency or complete clauses within every sentence."}
