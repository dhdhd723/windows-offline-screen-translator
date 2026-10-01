from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

NORMALIZATION_VERSION = 1
_SPACE = re.compile(r"\s+")
_HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_HAN_SPACE = re.compile(r"(?<=[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]) "
                        r"(?=[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff])")
_LATIN = re.compile(r"[A-Za-z]")
_NUMBERS = re.compile(r"\d+(?:[.,:]\d+)*")
_WORDS = re.compile(r"[\w]+", re.UNICODE)


def normalize_text(text: str) -> str:
    """Keep significant content while removing OCR formatting differences."""
    value = unicodedata.normalize("NFKC", text or "")
    value = value.translate(str.maketrans({"\u200b": "", "\ufeff": "", "‘": "'", "’": "'",
                                          "“": '"', "”": '"', "\u00ad": ""}))
    return _HAN_SPACE.sub("", _SPACE.sub(" ", value).strip())


def semantic_signature(text: str) -> tuple[str, ...]:
    return tuple(_WORDS.findall(normalize_text(text)))


def is_meaningful_change(previous: str, current: str, threshold: float = 0.94) -> bool:
    """Conservative noise gate; repeated near-matches are confirmed by Pipeline.

    Numbers, negation-sized strings and short labels bypass fuzzy matching. A
    stable one-character change in a longer sentence gets a second OCR instead
    of being silently ignored indefinitely.
    """
    old, new = normalize_text(previous), normalize_text(current)
    if old == new:
        return False
    if not old or not new:
        return True
    if max(len(old), len(new)) <= 4:
        return True
    if _NUMBERS.findall(old) != _NUMBERS.findall(new):
        return True
    if semantic_signature(old) == semantic_signature(new):
        return False
    try:
        from rapidfuzz.fuzz import ratio
        similarity = ratio(old, new) / 100.0
    except ImportError:
        similarity = SequenceMatcher(None, old, new, autojunk=False).ratio()
    return similarity < threshold


def choose_direction(text: str, direction: str = "auto") -> str | None:
    value = normalize_text(text)
    han, latin = len(_HAN.findall(value)), len(_LATIN.findall(value))
    if not han and not latin:
        return None
    if direction in {"zh-en", "en-zh"}:
        return direction
    return "zh-en" if han * 2 >= latin and han else "en-zh"
