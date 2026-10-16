from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

NORMALIZATION_VERSION = 1
LAYOUT_VERSION = 1
_SPACE = re.compile(r"\s+")
_HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_HAN_SPACE = re.compile(r"(?<=[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]) "
                        r"(?=[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff])")
_LATIN = re.compile(r"[A-Za-z]")
_KANA = re.compile(r"[\u3041-\u3096\u309d-\u309f\u30a1-\u30fa\u30fd-\u30ff\u31f0-\u31ff]")
_NUMBERS = re.compile(r"\d+(?:[.,:]\d+)*")
# Only discard familiar sentence/quote typography. Currency, signs, operators,
# percentages, slashes and other symbols can change the meaning of a subtitle.
_COSMETIC_PUNCTUATION = ".,!?…，。！？;；:：'\"`。、"
_SEMANTIC_PARTS = re.compile(r"\w+|[^\w\s" + re.escape(_COSMETIC_PUNCTUATION) + r"]", re.UNICODE)
_SEMANTIC_SYMBOLS = re.compile(r"[^\w\s" + re.escape(_COSMETIC_PUNCTUATION) + r"]", re.UNICODE)


def normalize_text(text: str) -> str:
    """Keep significant content while removing OCR formatting differences."""
    value = unicodedata.normalize("NFKC", text or "")
    value = value.translate(str.maketrans({"\u200b": "", "\ufeff": "", "‘": "'", "’": "'",
                                          "“": '"', "”": '"', "\u00ad": ""}))
    return _HAN_SPACE.sub("", _SPACE.sub(" ", value).strip())


def normalize_layout_text(text: str, text_layout: str = "continuous") -> str:
    """Keep hard dialogue rows without changing the legacy soft-wrap gate.

    OCR already groups fragments on the same baseline into one row. Chat mode
    preserves those rows; paragraph mode intentionally ignores visual wrapping.
    Blank OCR rows are not messages and are discarded in dialogue mode.
    """
    if text_layout != "lines":
        return normalize_text(text)
    rows = (normalize_text(row) for row in (text or "").splitlines())
    return "\n".join(row for row in rows if row)


def semantic_signature(text: str) -> tuple[str, ...]:
    return tuple(_SEMANTIC_PARTS.findall(normalize_text(text)))


def layout_semantic_signature(text: str, text_layout: str = "continuous") -> tuple[tuple[str, ...], ...]:
    value = normalize_layout_text(text, text_layout)
    return tuple(semantic_signature(row) for row in value.splitlines())


def is_meaningful_layout_change(previous: str, current: str,
                                text_layout: str = "continuous", threshold: float = 0.94) -> bool:
    if text_layout != "lines":
        return is_meaningful_change(previous, current, threshold)
    old, new = normalize_layout_text(previous, "lines"), normalize_layout_text(current, "lines")
    if old == new:
        return False
    old_rows, new_rows = old.splitlines(), new.splitlines()
    if len(old_rows) != len(new_rows):
        return True
    # Repartitioning identical words changes which message they belong to,
    # even when the old flattened comparison says nothing changed.
    if (semantic_signature(old) == semantic_signature(new)
            and layout_semantic_signature(old, "lines") != layout_semantic_signature(new, "lines")):
        return True
    return any(is_meaningful_change(left, right, threshold)
               for left, right in zip(old_rows, new_rows))


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
    if _SEMANTIC_SYMBOLS.findall(old) != _SEMANTIC_SYMBOLS.findall(new):
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
    if direction == "ja-zh":
        # Explicit selection resolves Han-only labels and kana-only dialogue.
        # Preserve the old auto mode: do not silently reroute English/Chinese.
        return "ja-zh" if han or latin or _KANA.search(value) else None
    if not han and not latin:
        return None
    if direction in {"zh-en", "en-zh"}:
        return direction
    return "zh-en" if han * 2 >= latin and han else "en-zh"
