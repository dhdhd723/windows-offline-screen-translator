"""Conservative sentence boundaries for offline translation, without text rewriting.

OCR paragraph/layout decisions belong to the caller.  This helper only separates
clear sentence endings so a model cannot silently omit a later sentence from a
multi-sentence input.  Ambiguous abbreviations remain together; token budgeting
still belongs to the model's tokenizer.
"""

from __future__ import annotations

import re


# Include this version in translation cache identities when the policy changes.
STRUCTURE_POLICY_ID = "complete-sentences-v1"

_CLOSING = '\"\'\u201d\u2019\u00bb\u300d\u300f\u3011\u300b\u3009)]}\uFF09'
_OPENING = '\"\'\u201c\u2018\u00ab\u300c\u300e\u3010\u300a\u3008([{\uFF08'
_ENDINGS = re.compile(r"[.!?\u3002\uff01\uff1f\u2026]+")
_WORD_BEFORE_DOT = re.compile(r"([A-Za-z]+(?:\.[A-Za-z]+)*)$")
_INITIALISM = re.compile(r"[A-Za-z](?:\.[A-Za-z])+")
_LIST_MARKER = re.compile(r"(?:[-*\u2022]\s*)?\d{1,3}")
_ABBREVIATIONS = frozenset(
    {
        "mr", "mrs", "ms", "dr", "prof", "rev", "jr", "sr", "st", "mt",
        "gen", "sgt", "lt", "capt", "cmdr", "col", "adm", "sen", "rep", "gov",
        "e.g", "i.e", "a.m", "p.m", "etc", "vs", "no", "fig", "figs", "dept",
        "approx", "est", "inc", "ltd", "co", "corp", "vol", "pp", "op", "ed",
        "eds", "ch", "al",
    }
)
_PROTECTED_TOKEN = re.compile(
    r"(?:https?://|ftp://|www\.)[^\s<>\"\u201c\u201d]+"
    r"|[A-Za-z0-9_.+%-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
    r"|(?:[A-Za-z]:[\\/]|\\\\)[^\s<>\"\u201c\u201d]+",
    re.IGNORECASE,
)


def _is_cjk(character: str) -> bool:
    return bool(character) and (
        "\u3400" <= character <= "\u9fff"
        or "\uf900" <= character <= "\ufaff"
        or "\U00020000" <= character <= "\U0003134f"
    )


def _protected_spans(text: str) -> list[tuple[int, int]]:
    spans = []
    for match in _PROTECTED_TOKEN.finditer(text):
        end = match.end()
        # A URL/path can be followed by a prose period and closing quotes.  A
        # terminal '?' or '!' can also be part of its query/path, so leave those
        # ambiguous cases protected rather than invent a sentence boundary.
        while end > match.start() and text[end - 1] in "." + _CLOSING:
            end -= 1
        spans.append((match.start(), end))
    return spans


def _period_is_ambiguous(text: str, start: int, position: int) -> bool:
    before = text[:position]
    word = _WORD_BEFORE_DOT.search(before)
    if word:
        token = word.group(1)
        if token.casefold() in _ABBREVIATIONS or _INITIALISM.fullmatch(token):
            return True
        if len(token) == 1 and token.isupper():
            # Initials (A. Smith) and lettered list markers (A. Example).
            return True
    if _LIST_MARKER.fullmatch(text[start:position].strip()):
        return True
    return False


def split_complete_sentences(text: str) -> list[str]:
    """Split clear terminal punctuation, preserving all non-whitespace in order.

    Returned pieces are stripped, but their contents, punctuation, and closing
    quotes are otherwise untouched.  Empty/whitespace-only input returns an
    empty list; an unsplit input returns exactly ``[text.strip()]``.  The caller
    should invoke this per paragraph, not use it to reinterpret OCR visual rows
    as separate chat messages.
    """
    if not text.strip():
        return []
    spans = _protected_spans(text)
    result: list[str] = []
    start = 0
    for match in _ENDINGS.finditer(text):
        position, end = match.span()
        if any(left <= position < right for left, right in spans):
            continue
        punctuation = match.group()
        while end < len(text) and text[end] in _CLOSING:
            end += 1
        next_position = end
        while next_position < len(text) and text[next_position].isspace():
            next_position += 1
        if next_position == len(text):
            # The trailing fragment is appended once below, including all marks.
            continue
        lookahead = next_position
        while lookahead < len(text) and text[lookahead] in _OPENING:
            lookahead += 1
        next_character = text[lookahead] if lookahead < len(text) else ""
        separated = next_position > end
        newline = "\n" in text[end:next_position] or "\r" in text[end:next_position]
        cjk_boundary = any(mark in punctuation for mark in "\u3002\uff01\uff1f")
        cjk_next = _is_cjk(next_character)
        # Avoid splitting decimals, versions, hostnames, and filename/path parts.
        if not separated and not cjk_boundary and not cjk_next:
            continue
        if punctuation == "." and _period_is_ambiguous(text, start, position):
            continue
        ellipsis = "\u2026" in punctuation or "..." in punctuation
        if ellipsis:
            # Ellipses often indicate hesitation within one sentence.  A capital,
            # paragraph break, CJK continuation, or explicit "but" starts a new
            # translation unit, including "evidence... Before you ...".
            next_word_is_but = bool(re.match(r"but\b", text[lookahead:], re.IGNORECASE))
            clear = newline or next_character.isupper() or cjk_next or next_word_is_but
        elif punctuation == ".":
            clear = newline or next_character.isupper() or next_character.isdigit() or cjk_next
        else:
            clear = bool(next_character)
        if not clear:
            continue
        piece = text[start:end].strip()
        if piece:
            result.append(piece)
        start = next_position
    remainder = text[start:].strip()
    if remainder:
        result.append(remainder)
    return result
