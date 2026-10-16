"""Source-side conservative terminology tests; no translation model required."""
from __future__ import annotations

import re

import pytest

from screen_translator.core.scoped_translation_terms import (
    TERMS_POLICY_ID, TranslationFragment, plan_translation_fragments,
    prepare_source_idioms,
)


def rendered(text: str, context: str = "") -> str:
    return "".join(part.text for part in plan_translation_fragments(text, context))


@pytest.mark.parametrize("source", [
    "", "   \t", "\r\n", "hello\x00 world\t\r\n",
    "Steam Rust Portal JOHN SMITH", "unknown GAME TITLE",
    "I like Hollow Knight.", "Stardew Valley is a place.",
    "Welcome to Stardew Valley", "I live in Stardew Valley.",
    "Phasmophobia is a clinical condition.",
    "A patient has Phasmophobia and a fear of ghosts.",
    "Red Barrels are containers.", "red barrels invites you to play.",
    "Murkoff is a word without context.",
    "NotPhasmophobia is a game.", "Phasmophobiaish is a game.",
    "Game Stardew Valley2; Game Hollow Knightmare; Game Slay the Spires",
    "游戏Phasmophobia game", "GamePhasmophobia",
])
def test_unscoped_unknown_and_identifier_sources_are_byte_exact(source):
    parts = plan_translation_fragments(source)
    assert "".join(part.text for part in parts) == source
    assert all(not part.literal for part in parts)


@pytest.mark.parametrize("source,expected", [
    ("Phasmophobia", "《恐鬼症》"),
    (" \tPhasmophobia\t ", " \t《恐鬼症》\t "),
    ("Join us playing Phasmophobia.", "Join us playing 《恐鬼症》."),
    ("Phasmophobia is a 4-player online co-op horror game.",
     "《恐鬼症》 is a 4-player online co-op horror game."),
    ("Phasmophobia features paranormal activity.", "《恐鬼症》 features paranormal activity."),
    ("I play Stardew Valley on Steam.", "I play 《星露谷物语》 on Steam."),
    ("The game Hollow Knight is fun.", "The game 《空洞骑士》 is fun."),
    ("Steam features Slay the Spire.", "Steam features 《杀戮尖塔》."),
    ("Game:\tStardew\tValley\r\nnew line",
     "Game:\t《星露谷物语》\r\nnew line"),
])
def test_only_known_titles_in_explicit_scopes_are_rendered(source, expected):
    assert rendered(source) == expected
    assert any(part.literal for part in plan_translation_fragments(source))


@pytest.mark.parametrize("source", [
    "I play stardew valley.", "HOLLOW KNIGHT is a game.",
    "Playing PHASMOPHOBIA", "STEAM features SLAY THE SPIRE.",
])
def test_inline_titles_require_exact_case_no_fuzzy_correction(source):
    assert rendered(source) == source
    assert all(not part.literal for part in plan_translation_fragments(source))


@pytest.mark.parametrize("source,context", [
    ("Welcome to Stardew Valley", "A Steam game."),
    ("I live in Stardew Valley", "Stardew Valley is a game."),
    ("She moved to Stardew Valley.", "playing on Steam"),
    ("The town called Stardew Valley", "game"),
    ("Phasmophobia", "This is a clinical condition, not the game."),
    ("Phasmophobia is a game.", "A patient discusses this condition."),
])
def test_negative_context_wins_over_external_positive_clues(source, context):
    assert rendered(source, context) == source
    assert all(not part.literal for part in plan_translation_fragments(source, context))


def test_original_paragraph_context_can_protect_a_sentence_without_repeating_context():
    assert rendered("Murkoff will let you leave.", "complete the therapy in Outlast") == (
        "Murkoff will let you leave.")
    assert plan_translation_fragments("Murkoff will let you leave.", "Outlast") == [
        TranslationFragment("Murkoff", True),
        TranslationFragment(" will let you leave.", False),
    ]
    assert rendered("Phasmophobia is frightening.", "online co-op game") == (
        "《恐鬼症》 is frightening.")


@pytest.mark.parametrize("source", [
    "Red Barrels invites you to experience terror.",
    "Red Barrels developed this game.",
    "The studio Red Barrels made the trials.",
    "Red\tBarrels invites you.",
    "Murkoff will let you leave after therapy.",
    "The Murkoff corporation is in Outlast.",
])
def test_preserved_latin_names_never_enter_nonliteral_fragments(source):
    parts = plan_translation_fragments(source)
    assert "".join(part.text for part in parts) == source
    assert any(part.literal and re.fullmatch(r"Red[ \t]+Barrels|Murkoff", part.text)
               for part in parts)
    assert not any("Red Barrels" in part.text or "Murkoff" in part.text
                   for part in parts if not part.literal)


def test_multiple_fragments_keep_order_surrounding_spaces_and_unknown_names():
    source = "Steam game Phasmophobia, by Red Barrels; Murkoff trials. Rust and Portal."
    parts = plan_translation_fragments(source)
    assert parts == [
        TranslationFragment("Steam game ", False),
        TranslationFragment("《恐鬼症》", True),
        TranslationFragment(", by ", False),
        TranslationFragment("Red Barrels", True),
        TranslationFragment("; ", False),
        TranslationFragment("Murkoff", True),
        TranslationFragment(" trials. Rust and Portal.", False),
    ]


@pytest.mark.parametrize("source", [
    "Steam game `Phasmophobia`", "Steam game ```Phasmophobia```",
    "Steam game https://example.com/Phasmophobia",
    "Steam game Phasmophobia@example.com", "Steam game @Phasmophobia",
    "Steam game #Phasmophobia", "Steam game C:\\Phasmophobia\\save",
    "Game `Red Barrels invites you`", "Outlast `Murkoff`",
    "Game `Immersive Experience:`",
])
def test_code_links_addresses_and_handles_are_not_terminology_spans(source):
    assert rendered(source) == source
    assert all(not part.literal for part in plan_translation_fragments(source))


@pytest.mark.parametrize("source,expected", [
    ("Immersive Experience: Realistic graphics.", "沉浸式体验： Realistic graphics."),
    ("ImmersiveExperience: Realistic graphics.", "沉浸式体验： Realistic graphics."),
    ("• Immersive Experience: sounds.", "• 沉浸式体验： sounds."),
    ("Features. Immersive Experience: sounds.", "Features. 沉浸式体验： sounds."),
    ("\tImmersive\tExperience : sounds.\r\n", "\t沉浸式体验： sounds.\r\n"),
])
def test_exact_heading_has_its_own_literal_fragment(source, expected):
    assert rendered(source) == expected
    assert [part.text for part in plan_translation_fragments(source) if part.literal] == [
        "沉浸式体验："]


@pytest.mark.parametrize("source", [
    "An Immersive Experience: sounds.", "immersive experience: sounds.",
    "IMMERSIVE EXPERIENCE: sounds.", "Immersive Experience without a colon.",
    "Immersive Experiences: sounds.", "TheImmersiveExperience: sounds.",
])
def test_heading_rule_is_not_a_general_global_phrase_replacement(source):
    assert rendered(source) == source
    assert all(not part.literal for part in plan_translation_fragments(source))


@pytest.mark.parametrize("source,context,expected", [
    ("The game will keep you on your toes.", "", "The game will keep you alert."),
    ("Immersive Experience: sounds keep you on your toes.", "",
     "Immersive Experience: sounds keep you alert."),
    ("Ghosts keep you on your toes.", "", "Ghosts keep you alert."),
    ("Keep you on your toes.", "Steam game", "Keep you alert."),
    ("KEEP YOU ON YOUR TOES!", "ghosts", "KEEP YOU ALERT!"),
    ("sounds keep\tyou on your toes.", "game", "sounds keep you alert."),
])
def test_one_explicit_idiom_uses_source_paraphrase_in_gaming_context(source, context, expected):
    assert prepare_source_idioms(source, context) == expected


@pytest.mark.parametrize("source,context", [
    ("This job will keep you on your toes.", ""),
    ("The ballet game will keep you on your toes.", ""),
    ("keep you on your toes", "dance and gameplay"),
    ("keep you on your toes", "literally standing in a game"),
    ("Game toes and feet keep you on your toes", ""),
    ("Ghosts `keep you on your toes`", ""),
    ("Game https://example.com/keep%20you%20on%20your%20toes", ""),
    ("Ghosts keep you on your toesies.", ""),
    ("Ghosts keepyou on your toes.", ""),
    ("Ghosts KEEP YOU ON YOUR FEET.", ""),
])
def test_idiom_without_context_or_with_literal_or_protected_scope_is_unchanged(source, context):
    assert prepare_source_idioms(source, context) == source


def test_policy_id_is_stable_content_derived_and_namespaced():
    assert re.fullmatch(r"scoped-terms-v1:[0-9a-f]{64}", TERMS_POLICY_ID)
    assert TERMS_POLICY_ID == __import__(
        "screen_translator.core.scoped_translation_terms", fromlist=["TERMS_POLICY_ID"]
    ).TERMS_POLICY_ID


def test_fragment_dataclass_is_immutable():
    fragment = TranslationFragment("Murkoff", True)
    with pytest.raises(AttributeError):
        fragment.text = "altered"


@pytest.mark.parametrize("source,expected", [
    ("Join Peppa's World", "Join 佩奇的世界"),
    ("Join Peppa’s World", "Join 佩奇的世界"),
    ("Join Peppa World Adventures", "Join 佩奇 World Adventures"),
    ("The game Peppa's World Adventures.", "The game 佩奇的世界 Adventures."),
    ("Join Peppa's\tWorld", "Join 佩奇的世界"),
])
def test_peppa_ip_name_has_explicit_world_phrase_scope_and_preserves_possessive(source, expected):
    assert rendered(source) == expected
    literal = [part.text for part in plan_translation_fragments(source) if part.literal]
    assert literal in (["佩奇的世界"], ["佩奇"])
    assert all(not part.text.startswith(("'s", "’s"))
               for part in plan_translation_fragments(source) if not part.literal)


@pytest.mark.parametrize("source", [
    "Peppa", "Peppa is a pet.", "Peppa is a player in this game world.",
    "My dog Peppa's World is small.", "A username called Peppa's World.",
    "Join peppa's World", "Join PEPPA'S WORLD", "Join NotPeppa's World",
    "Join Peppa's Worlds", "Game `Peppa's World`", "Game https://example.com/Peppa",
])
def test_peppa_rule_does_not_guess_personal_names_or_fuzzy_spellings(source):
    assert rendered(source) == source
    assert all(not part.literal for part in plan_translation_fragments(source))


def test_peppa_confirmed_possessive_title_does_not_feed_lone_world_to_model():
    assert plan_translation_fragments("Join Peppa's World") == [
        TranslationFragment("Join ", False),
        TranslationFragment("佩奇的世界", True),
    ]
    assert plan_translation_fragments("Join Peppa’s World Adventures") == [
        TranslationFragment("Join ", False),
        TranslationFragment("佩奇的世界", True),
        TranslationFragment(" Adventures", False),
    ]
