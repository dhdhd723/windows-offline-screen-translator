"""Fail-closed text validation for geometry-triggered OCR re-recognition.

This module never rewrites text or infers overlap from strings. The caller must
first establish overlapping image crops; this guard only limits what a second
recognition is allowed to remove from their original text.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
import math
import re
import unicodedata


_WORDS = re.compile(r"[A-Za-z]+(?:['\u2019][A-Za-z]+)?|[0-9]+")
_STANDALONE_TOKENS = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Za-z]+(?:['\u2019][A-Za-z]+)?|[0-9]+)(?![A-Za-z0-9])")
_LETTER_RUNS = re.compile(r"[A-Za-z]{2,}")
_CLEAN_WORDS = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{2,}(?![A-Za-z0-9])")
_SINGLE_WORDS = re.compile(r"(?<![A-Za-z0-9])[Ia](?![A-Za-z0-9])", re.IGNORECASE)
_STANDALONE_NUMBERS = re.compile(r"(?<![A-Za-z0-9])[0-9]+(?![A-Za-z0-9])")
_DOMAIN = re.compile(r"\b[A-Za-z0-9-]+\.[A-Za-z]{2,}\b")
_ALLOWED_PUNCTUATION = frozenset(".,;:'\"?!()-\u2018\u2019\u201c\u201d")
_NEGATIONS = frozenset({
    "no", "not", "never", "neither", "nor", "without", "cannot",
    "ain't", "can't", "couldn't", "didn't", "doesn't", "don't", "hadn't",
    "hasn't", "haven't", "isn't", "mustn't", "needn't", "shouldn't",
    "wasn't", "weren't", "won't", "wouldn't",
})
_CONFUSABLE_GROUPS = (frozenset("il1|"), frozenset("co"))
_MAX_FRAGMENTS = 8
_MAX_CHARACTERS = 2048
_MAX_ALIGNMENT_STATES = 4096


def _normalized(value: str) -> str:
    return unicodedata.normalize("NFKC", value)


def _canonical(value: str) -> str:
    return "".join(character for character in value.casefold() if not character.isspace())


def _prose_only(value: str) -> bool:
    if not value.strip() or any(character in value for character in "\r\n\v\f\x85\u2028\u2029"):
        return False
    for index, character in enumerate(value):
        if character in " \t" or character.isascii() and character.isalnum():
            continue
        if character not in _ALLOWED_PUNCTUATION:
            return False
        # An ordinary word hyphen is allowed; signed numbers and operators are
        # outside this prose-only policy, even if their glyphs could be kept.
        if character == "-" and not (
            index > 0 and index + 1 < len(value)
            and value[index - 1].isascii() and value[index - 1].isalnum()
            and value[index + 1].isascii() and value[index + 1].isalpha()
        ):
            return False
    return not _DOMAIN.search(value)


def _prepare(fragments: Sequence[str]) -> list[str] | None:
    if isinstance(fragments, (str, bytes)) or not isinstance(fragments, Sequence):
        return None
    if not 2 <= len(fragments) <= _MAX_FRAGMENTS:
        return None
    if not all(isinstance(fragment, str) for fragment in fragments):
        return None
    normalized = [_normalized(fragment) for fragment in fragments]
    if sum(map(len, normalized)) > _MAX_CHARACTERS:
        return None
    if not all(_prose_only(fragment) for fragment in normalized):
        return None
    if not _LETTER_RUNS.search(" ".join(normalized)):
        return None
    return normalized


def overlap_text_eligible(fragments: Sequence[str]) -> bool:
    """Whether this small group is eligible for a prose-only image retry."""
    return _prepare(fragments) is not None


def _tokens(value: str) -> Counter[str]:
    return Counter(match.group().casefold().replace("\u2019", "'")
                   for match in _WORDS.finditer(value))


def _edge_matches(first: str, second: str) -> bool:
    if first.isdigit() or second.isdigit():
        return first == second
    return first == second or any(first in group and second in group
                                  for group in _CONFUSABLE_GROUPS)


def _deletion_options(fragments: list[str]) -> tuple[str, dict[int, tuple[int, ...]]]:
    canonical = [_canonical(fragment) for fragment in fragments]
    protected: set[int] = set()
    offset = 0
    for fragment in fragments:
        for expression in (_LETTER_RUNS, _STANDALONE_NUMBERS, _SINGLE_WORDS):
            for match in expression.finditer(fragment):
                start = offset + len(_canonical(fragment[:match.start()]))
                stop = offset + len(_canonical(fragment[:match.end()]))
                protected.update(range(start, stop))
        offset += len(_canonical(fragment))
    options: dict[int, list[int]] = {}
    boundary = 0
    for seam, (left, right) in enumerate(zip(canonical, canonical[1:])):
        boundary += len(left)
        for position in range(max(boundary - min(2, len(left)), 0), boundary):
            character = left[position - (boundary - len(left))]
            if (position not in protected and character.isalnum()
                    and _edge_matches(character, right[0])):
                options.setdefault(position, []).append(seam)
        for relative in range(min(2, len(right))):
            position = boundary + relative
            character = right[relative]
            if (position not in protected and character.isalnum()
                    and _edge_matches(character, left[-1])):
                options.setdefault(position, []).append(seam)
    return "".join(canonical), {index: tuple(seams) for index, seams in options.items()}


def _deletions_only(source: str, candidate: str, options: dict[int, tuple[int, ...]],
                    seam_count: int) -> bool:
    difference = len(source) - len(candidate)
    if difference < 0 or difference > seam_count:
        return False
    pending = [(0, 0, 0)]
    seen: set[tuple[int, int, int]] = set()
    while pending:
        position, target, used_seams = pending.pop()
        state = position, target, used_seams
        if state in seen:
            continue
        seen.add(state)
        if len(seen) > _MAX_ALIGNMENT_STATES:
            return False
        while position < len(source):
            # Try deletion even when this character also matches. Identical
            # adjacent digits can otherwise align to a protected occurrence.
            if used_seams.bit_count() < difference:
                for seam in options.get(position, ()):
                    flag = 1 << seam
                    if not used_seams & flag:
                        pending.append((position + 1, target, used_seams | flag))
            if target >= len(candidate) or source[position] != candidate[target]:
                break
            position += 1
            target += 1
        else:
            if target == len(candidate):
                return True
    return False


def accept_overlap_text(fragments: Sequence[str], candidate: str, confidence: float,
                        baseline_confidence: float) -> bool:
    """Accept only high-confidence, seam-local deletions of unprotected glyphs.

    Every original multi-letter run and standalone number is protected. This
    intentionally rejects malformed attached tokens such as ``Before|eyou``;
    the independently recognized ``Before|e you`` can be accepted instead.
    """
    normalized = _prepare(fragments)
    if normalized is None or not isinstance(candidate, str):
        return False
    if isinstance(confidence, bool) or isinstance(baseline_confidence, bool):
        return False
    try:
        score, baseline = float(confidence), float(baseline_confidence)
    except (TypeError, ValueError, OverflowError):
        return False
    if (not math.isfinite(score) or not math.isfinite(baseline)
            or not 0.85 <= score <= 1.0 or not 0.0 <= baseline <= 1.0
            or baseline - score > 0.08 + 1e-12):
        return False
    candidate = _normalized(candidate)
    if not _prose_only(candidate) or len(candidate) > _MAX_CHARACTERS:
        return False
    source, options = _deletion_options(normalized)
    candidate_canonical = _canonical(candidate)
    if source == candidate_canonical:
        return False
    # Keep clean original words as words, not merely as an unbroken sequence
    # after whitespace is removed. Never permit therapist -> the rapist or
    # some|one -> someone while correcting an unrelated seam glyph.
    for expression in (_CLEAN_WORDS, _SINGLE_WORDS):
        original_words = Counter(match.group().casefold() for fragment in normalized
                                 for match in expression.finditer(fragment))
        candidate_words = Counter(match.group().casefold()
                                  for match in expression.finditer(candidate))
        if any(candidate_words[word] < count for word, count in original_words.items()):
            return False
    original_numbers = {number for fragment in normalized
                        for number in re.findall(r"[0-9]+", fragment)}
    if not original_numbers.issubset(set(re.findall(r"[0-9]+", candidate))):
        return False
    original_tokens, candidate_tokens = _tokens(" ".join(normalized)), _tokens(candidate)
    if any(original_tokens[token] != candidate_tokens[token] for token in _NEGATIONS):
        return False
    repeated = Counter(match.group().casefold().replace("\u2019", "'")
                       for fragment in normalized
                       for match in _STANDALONE_TOKENS.finditer(fragment))
    if any(candidate_tokens[token] < count
           for token, count in repeated.items() if count > 1):
        return False
    # Do not turn two real numbers into a new number by removing their space.
    # A preserved standalone number may attach to an existing letter in the
    # retry (isa4|4-player -> is a4-player), but its digit run stays intact.
    numbers = iter(re.findall(r"[0-9]+", candidate))
    for fragment in normalized:
        for match in _STANDALONE_NUMBERS.finditer(fragment):
            if not any(number == match.group() for number in numbers):
                return False
    return _deletions_only(source, candidate_canonical, options, len(normalized) - 1)
