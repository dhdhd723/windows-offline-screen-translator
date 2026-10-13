"""Small, offline, whole-line game title/credit policy, not a name detector.

Do not replace fragments in prose: Stardew Valley can also name a place.
Unknown titles, names and ALLCAPS menu labels remain model input unchanged.
Source and trial limitations: docs/翻译质量试验语料.md.
"""
from __future__ import annotations

import hashlib
import json
import re


GAME_TERMS_VERSION = 1
GAME_TITLES = {
    "Stardew Valley": "星露谷物语",
    "Hollow Knight": "空洞骑士",
    "Slay the Spire": "杀戮尖塔",
}
KNOWN_CREATORS = {
    "Eric Barone": "Eric Barone",
    "ConcernedApe": "ConcernedApe",
    'Eric Barone "ConcernedApe"': 'Eric Barone "ConcernedApe"',
    "Eric Barone “ConcernedApe”": "Eric Barone “ConcernedApe”",
}
# The regular expression must match the *whole* line; it is not a prose edit.
_CREDITS = re.compile(
    r"(?:(?P<title>.+?)\s+(?:-\s*)?)?"
    r"(?P<verb>created|developed)\s+by\s*:?(?:\s*(?P<creator>.+?))?\.?",
    re.IGNORECASE | re.ASCII,
)
_POLICY = {
    "version": GAME_TERMS_VERSION,
    "scope": "whole-line-known-titles-and-known-creator-credits",
    "titles": GAME_TITLES,
    "creators": KNOWN_CREATORS,
    "credits_pattern": _CREDITS.pattern,
    "templates": ["《{title}》制作：", "《{title}》由 {creator} 制作", "制作者：{creator}"],
}
_FINGERPRINT = hashlib.sha256(json.dumps(
    _POLICY, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
).encode("ascii")).hexdigest()


def _key(text: str) -> str:
    return " ".join(text.split()).casefold()


_TITLES = {_key(source): target for source, target in GAME_TITLES.items()}
_CREATORS = {_key(source): target for source, target in KNOWN_CREATORS.items()}


def translation_identity(model_id: str, direction: str) -> str:
    """Keep old results out of this policy, including after lazy model loading."""
    if direction != "en-zh":
        return model_id
    return f"{model_id}|game-terms-v{GAME_TERMS_VERSION}:{_FINGERPRINT}"


def translate_known_game_line(text: str, direction: str) -> str | None:
    """Return only a trusted full-line result, or None to use the model.

    Newline boundaries are the engine's responsibility. No fuzzy spelling,
    output repair, placeholder injection or unknown-person guessing is used.
    """
    if direction != "en-zh" or any(char in text for char in "\r\n\u2028\u2029"):
        return None
    line = " ".join(text.split())
    if not line:
        return None
    key = _key(line)
    if key in _TITLES:
        return _TITLES[key]
    if key in _CREATORS:
        return _CREATORS[key]
    match = _CREDITS.fullmatch(line)
    if match is None:
        return None
    title_source, creator_source = match.group("title"), match.group("creator")
    title = _TITLES.get(_key(title_source)) if title_source else None
    creator = _CREATORS.get(_key(creator_source)) if creator_source else None
    if (title_source and title is None) or (creator_source and creator is None):
        return None
    if title and creator:
        return f"《{title}》由 {creator} 制作"
    if title:
        return f"《{title}》制作："
    if creator:
        return f"制作者：{creator}"
    return None
