"""Non-binding chat spelling/slang hints for an optional enhanced translator.

The source is never rewritten here. In particular, a glossary sense such as
``def = definitely`` is not substituted before the model can read the sentence.
These candidates are small, offline hints, not a language/identity detector or a
claim that any listed sense is correct for a particular message.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from screen_translator.core.chat_slang import BUILTIN_CHAT_SLANG, sanitize_overrides


CHAT_CANDIDATES_VERSION = 2
MAX_CHAT_HINTS = 16
MAX_CHAT_HINT_CHARACTERS = 640
MAX_CHAT_SCAN_CHARACTERS = 16_000

# Keep the existing selected chat senses available as optional hints. Ambiguous
# spellings get alternatives, never a silently chosen replacement. There is no
# bare "r" or numeric "2" rule.
_CANDIDATES = {token: (expansion,) for token, expansion in BUILTIN_CHAT_SLANG.items()}
_CANDIDATES.update({
    "def": ("definitely", "defense"),
    "bc": ("because", "before Christ"),
    "fr": ("for real", "French or France"),
    "rn": ("right now", "registered nurse"),
    "u": ("you",),
    "ur": ("your", "you are"),
    "im": ("I am",),
    "dont": ("do not",),
    "cant": ("cannot",),
    "wont": ("will not",),
    "didnt": ("did not",),
    "doesnt": ("does not",),
    "isnt": ("is not",),
    "dw": ("do not worry",),
    "mb": ("my bad", "maybe"),
})

_TOKEN = re.compile(r"(?<![\w/'’.\\-])[A-Za-z][A-Za-z0-9]*(?![\w/'’.\\-])")
_PROTECTED = re.compile(
    r"```[\s\S]*?(?:```|\Z)"
    r"|`[^`\n]*(?:`|$)"
    r'|"(?:\\.|[^"\\\n])*(?:"|$)'
    r"|(?<!\w)'(?:\\.|[^'\\\n])*(?:'|$)"
    r"|“[^”\n]*(?:”|$)|‘[^’\n]*(?:’|$)"
    r"|「[^」\n]*(?:」|$)|『[^』\n]*(?:』|$)"
    r"|(?<![\w+.-])(?:[A-Za-z][A-Za-z0-9+.-]{0,31}://|www\.)[^\s<>]+"
    r"|(?<![\w@])[\w.+-]+@(?:[\w-]+\.)+[\w-]+"
    r"|(?<!\w)(?:[A-Za-z]:[\\/]|\\\\)[^\s]+"
    r"|(?<!\w)(?:\.{0,2}[\\/])[A-Za-z0-9_.-]+(?:[\\/][A-Za-z0-9_.-]+)*"
    r"|(?<!\w)[A-Za-z0-9_.-]+(?:[\\/][A-Za-z0-9_.-]+)+"
    r"|(?<!\w)(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,24}(?::\d+)?(?:/[^\s<>]*)?"
    r"|[@#][\w.-]+"
    r"|(?i:(?<!\w)(?:[0-9]{1,4}[ \t]+bc|bc[ \t]+[0-9]{1,4})(?!\w))"
    r"|\bdef[ \t]+[A-Za-z_]\w*[ \t]*\([^\n]*"
    r"|^[^\n]*(?:=>|:=|==|(?<![!<>])=(?!=))[^\n]*$"
    r"|^[ \t]*[^\n:]{1,64}:[ \t]*",
    re.MULTILINE,
)


@dataclass(frozen=True)
class ChatHint:
    """Possible senses of one original token; offsets refer to ``raw``."""

    token: str
    start: int
    end: int
    candidates: tuple[str, ...]

    @property
    def ambiguous(self) -> bool:
        return len(self.candidates) > 1


@dataclass(frozen=True)
class ChatCandidates:
    """Original input plus bounded suggestions which a backend may ignore."""

    raw: str
    hints: tuple[ChatHint, ...]


def _protected_spans(text: str) -> list[tuple[int, int]]:
    spans = [match.span() for match in _PROTECTED.finditer(text)]
    offset = 0
    for row in text.splitlines(keepends=True):
        # Only suggest English-chat spellings in English rows. Emoji/punctuation
        # are allowed, but mixed-language prose is not guessed at or rewritten.
        if any(character.isalpha() and not character.isascii() for character in row):
            spans.append((offset, offset + len(row)))
        offset += len(row)
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def conservative_chat_candidates(text: str, overrides: object = None) -> ChatCandidates:
    """Preserve input exactly and annotate only complete, unprotected tokens.

    Suggestions never span rows, terms are deduplicated case-insensitively, and
    fixed count/character budgets avoid growing an inference prompt without
    bound. Inputs above the scanning budget are returned untouched without
    hints, not truncated. Validated custom senses have priority in the bounded
    hints, but still never replace the original input. Bare names without explicit syntax remain ambiguous;
    callers should still separate message identities before model inference.
    """
    if len(text) > MAX_CHAT_SCAN_CHARACTERS:
        return ChatCandidates(text, ())
    custom = sanitize_overrides(overrides)
    glossary = {**_CANDIDATES, **{key: (value,) for key, value in custom.items()}}
    spans = _protected_spans(text)
    position = 0
    seen: set[str] = set()
    matches: list[ChatHint] = []
    for match in _TOKEN.finditer(text):
        while position < len(spans) and spans[position][1] <= match.start():
            position += 1
        if position < len(spans) and match.end() > spans[position][0]:
            continue
        token = match.group()
        key = token.lower()
        candidates = glossary.get(key)
        if candidates is None or key in seen:
            continue
        matches.append(ChatHint(token, match.start(), match.end(), candidates))
        seen.add(key)
    # Stable ordering keeps body order within each group. A late custom term
    # must not be crowded out by the first sixteen ordinary builtin hints.
    matches.sort(key=lambda hint: hint.token.lower() not in custom)
    hints: list[ChatHint] = []
    characters = 0
    for hint in matches:
        cost = len(hint.token) + sum(len(candidate) for candidate in hint.candidates)
        if characters + cost > MAX_CHAT_HINT_CHARACTERS:
            continue
        hints.append(hint)
        characters += cost
        if len(hints) >= MAX_CHAT_HINTS:
            break
    return ChatCandidates(text, tuple(hints))
