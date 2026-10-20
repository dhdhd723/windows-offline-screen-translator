"""Conservative visual soft-wrap joining for explicitly selected chat rows.

Geometry can support a hanging continuation, but cannot prove that two
left-aligned messages share a speaker. Uncertain rows retain their boundaries.
This module never reads pixels, guesses missing glyphs, or mutates OCR evidence.
"""
from __future__ import annotations

import math
import re
from collections.abc import Callable

from screen_translator.contracts import OCRResult, TextLine


CHAT_MESSAGE_POLICY_ID = "conservative-chat-messages-v1"
PrefixParser = Callable[[str], tuple[str, str] | None]

_DEFAULT_PREFIX = re.compile(
    r"(?P<prefix>(?:[\w][\w.-]{0,31}|\[[\w][\w.-]{0,31}\]):[ \t]+)(?P<body>\S.*)\Z"
)
_SENTENCE_END = re.compile(r"[.!?。！？][\"'”’\)\]]*\Z")


def _default_prefix(text: str) -> tuple[str, str] | None:
    match = _DEFAULT_PREFIX.fullmatch(text)
    if match is None:
        return None
    identity = match.group("prefix").split(":", 1)[0].strip("[]")
    if not any(character.isalpha() for character in identity):
        return None
    body = match.group("body")
    if body.startswith("//") or (len(identity) == 1 and body.startswith(("\\", "/"))):
        return None
    return match.group("prefix"), body


def _bounds(row: TextLine) -> tuple[float, float, float, float] | None:
    try:
        if len(row.box) != 4 or any(len(point) != 2 for point in row.box):
            return None
        xs, ys = zip(*row.box)
        if not all(math.isfinite(value) for value in (*xs, *ys)):
            return None
        left, top, right, bottom = min(xs), min(ys), max(xs), max(ys)
        if left < 0 or top < 0 or right <= left or bottom <= top:
            return None
        if not math.isfinite(row.confidence) or not 0.65 <= row.confidence <= 1.0:
            return None
        return left, top, right, bottom
    except (TypeError, ValueError, OverflowError):
        return None


def assemble_chat_messages(result: OCRResult, *, text_layout: str = "lines",
                           enabled: bool = True,
                           prefix_parser: PrefixParser | None = None) -> str:
    """Join only named-message hanging continuations with matching OCR rows.

    ``prefix_parser`` must recognize a *whole* row and return the preserved
    prefix and nonempty body. The chat adapter can supply its own identity
    policy (for example display names containing spaces) without a circular
    dependency. Returning ``None`` means that the row has no proven identity.

    All visual-row strings must exactly match ``result.text`` before geometry
    is used. The optional metadata can therefore never reintroduce raw text
    superseded by an accepted OCR crop repair. Missing/invalid metadata leaves
    the original text untouched. Explicitly named rows always start messages;
    rows without names are never joined to one another on their own.
    """
    original = result.text
    if not enabled or text_layout != "lines" or not result.visual_rows:
        return original
    texts = original.splitlines()
    rows = result.visual_rows
    if len(texts) != len(rows) or any(text != row.text for text, row in zip(texts, rows)):
        return original
    bounds = [_bounds(row) for row in rows]
    if any(box is None for box in bounds):
        return original
    # Do not silently reorder words if metadata and reading order disagree.
    # The OCR engine already sorts visual rows and same-baseline fragments.
    if any((first[1] + first[3]) >= (second[1] + second[3])
           for first, second in zip(bounds, bounds[1:])):
        return original
    parser = prefix_parser or _default_prefix
    output: list[str] = []
    anchor: tuple[float, float, float, float] | None = None
    previous: tuple[float, float, float, float] | None = None
    continuation_left: float | None = None
    joined_any = False
    for text, box in zip(texts, bounds):
        named = parser(text)
        if named is not None:
            output.append(text)
            anchor = box
            previous = box
            continuation_left = None
            continue
        join = False
        if anchor is not None and previous is not None:
            height = previous[3] - previous[1]
            anchor_height = anchor[3] - anchor[1]
            current_height = box[3] - box[1]
            gap = box[1] - previous[3]
            # At least three quarters of a text height of indentation is
            # required. Same-margin lines are inherently ambiguous and stay
            # separate even when the preceding message fills the whole width.
            join = (0.70 <= current_height / height <= 1.40
                    and 0.70 <= current_height / anchor_height <= 1.40
                    and -0.15 * height <= gap <= 0.80 * height
                    and 0.75 * height <= box[0] - anchor[0] <= 8.0 * height
                    and box[0] <= anchor[2] - height
                    and box[2] <= anchor[2] + 0.50 * height
                    and (continuation_left is None
                         or abs(box[0] - continuation_left) <= 0.50 * height)
                    and not _SENTENCE_END.search(output[-1].rstrip()))
        if join:
            output[-1] += " " + text
            joined_any = True
            previous = box
            continuation_left = box[0] if continuation_left is None else continuation_left
        else:
            output.append(text)
            anchor = previous = None
            continuation_left = None
    return "\n".join(output) if joined_any else original
