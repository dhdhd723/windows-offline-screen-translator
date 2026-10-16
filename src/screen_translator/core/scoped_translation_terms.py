"""Small, explicitly scoped source-side terms; not a proper-name detector.

Literal fragments bypass the translation model. Nonliteral fragments retain
their source spelling, whitespace and order exactly. Concatenating every
fragment reproduces the source except for the documented title/heading
translations. No placeholders or model-output replacements are used.

Rules are intentionally conservative: a known title in ordinary prose can
still name a place, and a capitalised phrase is not automatically a name.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re


@dataclass(frozen=True, slots=True)
class TranslationFragment:
    text: str
    literal: bool


_INLINE_TITLES = {
    "Phasmophobia": "《恐鬼症》",
    "Stardew Valley": "《星露谷物语》",
    "Hollow Knight": "《空洞骑士》",
    "Slay the Spire": "《杀戮尖塔》",
}
_GAME_CONTEXT = re.compile(
    r"\b(?:game|games|gameplay|gaming|steam|playing|play|played)\b"
    r"|\b(?:4|four)[ \t-]*players?\b"
    r"|\bonline[ \t]+co[ -]?op\b",
    re.IGNORECASE | re.ASCII,
)
_PHASMOPHOBIA_CONTEXT = re.compile(
    _GAME_CONTEXT.pattern + r"|\b(?:paranormal|ghost[ -]?hunting)\b",
    re.IGNORECASE | re.ASCII,
)
_CLINICAL_CONTEXT = re.compile(
    r"\b(?:clinical|diagnos(?:is|es|ed|tic)|condition|disorder|patient|patients|"
    r"symptom|symptoms|phobia|fear[ \t]+of|treat(?:ing|ment)?)\b",
    re.IGNORECASE | re.ASCII,
)
_PLACE_CONTEXT = re.compile(
    r"\b(?:welcome[ \t]+to|(?:live|living|lived|arrive|arriving|arrived|"
    r"stay|staying|stayed|move|moving|moved|travel|travelling|traveling)"
    r"[ \t]+(?:in|to|at)|(?:town|village|place)[ \t]+(?:of|called))"
    r"[ \t]+Stardew[ \t]+Valley\b",
    re.IGNORECASE | re.ASCII,
)
_STUDIO_CONTEXT = re.compile(
    r"\b(?:invites?|developed|developer|developers|studio|studios|"
    r"trials|Murkoff|Outlast)\b",
    re.IGNORECASE | re.ASCII,
)
_MURKOFF_CONTEXT = re.compile(
    r"\b(?:Outlast|trials|therapy|company|corporation)\b",
    re.IGNORECASE | re.ASCII,
)
_PEPPA_CONTEXT = re.compile(
    r"(?<!\w)(?:Join[ \t]+Peppa(?:['’]s)?[ \t]+World(?:[ \t]+Adventures)?"
    r"|Peppa['’]s[ \t]+World(?:[ \t]+Adventures)?)(?!\w)",
)
_PEPPA_PERSONAL_CONTEXT = re.compile(
    r"\b(?:pet|dog|cat|nickname|username|named|called)\b",
    re.IGNORECASE | re.ASCII,
)
_IDIOM = re.compile(
    r"(?<!\w)keep[ \t]+you[ \t]+on[ \t]+your[ \t]+toes(?!\w)",
    re.IGNORECASE,
)
_IDIOM_CONTEXT = re.compile(
    _GAME_CONTEXT.pattern + r"|\b(?:immersive|ghost|ghosts)\b",
    re.IGNORECASE | re.ASCII,
)
_LITERAL_TOES_CONTEXT = re.compile(
    r"\b(?:ballet|dance|dancing|dancer|dancers|toe|toes|foot|feet|"
    r"pointe|physical|literally)\b",
    re.IGNORECASE | re.ASCII,
)
# Recognise only this exact heading, including one common OCR missing-space
# form. The prefix is not replaced, so bullets and line endings are retained.
_HEADING = re.compile(
    r"(?:^[ \t]*(?:[-*•][ \t]+)?|(?<=[.!?])[ \t]+)"
    r"(?P<heading>Immersive[ \t]*Experience[ \t]*:)",
    re.MULTILINE,
)
_PROTECTED = re.compile(
    r"```[\s\S]*?(?:```|\Z)|`[^`\n]*(?:`|$)"
    r"|(?<![\w+.-])(?:[A-Za-z][A-Za-z0-9+.-]{0,31}://|www\.)[^\s<>]+"
    r"|(?<![\w@])[\w.+-]+@(?:[\w-]+\.)+[\w-]+"
    r"|(?<!\w)(?:[A-Za-z]:[\\/]|\\\\)[^\s]+"
    r"|(?<!\w)(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,24}(?::\d+)?(?:/[^\s<>]*)?"
    r"|[@#][\w.-]+",
)

_NAME_PATTERNS = {
    name: re.compile(r"(?<!\w)" + r"[ \t]+".join(map(re.escape, name.split()))
                     + r"(?!\w)")
    for name in (*_INLINE_TITLES, "Red Barrels", "Murkoff")
}
# Keep the confirmed possessive title together. Feeding an isolated "World"
# to the bundled model produced repeated "世界" in a native regression test.
_NAME_PATTERNS["Peppa"] = re.compile(
    r"(?<!\w)Peppa(?:['’]s[ \t]+World|['’]s)?(?!\w)")

_POLICY = {
    "version": 1,
    "scope": "exact-case-known-inline-terms-with-positive-and-negative-context",
    "fragment_policy": "no-placeholder;source-order;untouched-nonliteral-spans",
    "titles": _INLINE_TITLES,
    "preserved_names": ["Red Barrels", "Murkoff"],
    "scoped_ip_name": {
        "Peppa": "佩奇", "Peppa's": "佩奇的", "Peppa’s": "佩奇的",
        "Peppa's World": "佩奇的世界", "Peppa’s World": "佩奇的世界",
    },
    "heading_output": "沉浸式体验：",
    "idiom_output": "keep you alert",
    "patterns": {
        "game": _GAME_CONTEXT.pattern,
        "phasmophobia": _PHASMOPHOBIA_CONTEXT.pattern,
        "clinical_veto": _CLINICAL_CONTEXT.pattern,
        "place_veto": _PLACE_CONTEXT.pattern,
        "studio": _STUDIO_CONTEXT.pattern,
        "murkoff": _MURKOFF_CONTEXT.pattern,
        "peppa": _PEPPA_CONTEXT.pattern,
        "peppa_personal_veto": _PEPPA_PERSONAL_CONTEXT.pattern,
        "idiom": _IDIOM.pattern,
        "idiom_context": _IDIOM_CONTEXT.pattern,
        "literal_toes_veto": _LITERAL_TOES_CONTEXT.pattern,
        "heading": _HEADING.pattern,
        "protected": _PROTECTED.pattern,
        "names": {name: pattern.pattern for name, pattern in _NAME_PATTERNS.items()},
    },
}
TERMS_POLICY_ID = "scoped-terms-v1:" + hashlib.sha256(json.dumps(
    _POLICY, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
).encode("ascii")).hexdigest()


def _scope(text: str, context: str) -> str:
    return text if not context or context == text else text + "\n" + context


def _intersects(start: int, end: int, protected: list[tuple[int, int]]) -> bool:
    return any(start < stop and end > begin for begin, stop in protected)


def _is_complete_line(text: str, start: int, end: int) -> bool:
    before = max(text.rfind("\n", 0, start), text.rfind("\r", 0, start)) + 1
    following = [index for mark in ("\n", "\r")
                 if (index := text.find(mark, end)) >= 0]
    after = min(following) if following else len(text)
    return not text[before:start].strip() and not text[end:after].strip()


def plan_translation_fragments(text: str, context: str = "") -> list[TranslationFragment]:
    """Return source fragments and narrowly trusted literal output in order.

    ``context`` may be the unchunked paragraph when this function receives a
    smaller sentence. It permits positive clues but also negative vetoes;
    it is never copied into the returned fragments.
    """
    if not text:
        return []
    scope = _scope(text, context)
    protected = [match.span() for match in _PROTECTED.finditer(text)]
    spans: list[tuple[int, int, str]] = []
    for match in _HEADING.finditer(text):
        start, end = match.span("heading")
        if not _intersects(start, end, protected):
            spans.append((start, end, "沉浸式体验："))
    for name, pattern in _NAME_PATTERNS.items():
        for match in pattern.finditer(text):
            start, end = match.span()
            if _intersects(start, end, protected):
                continue
            if name == "Red Barrels":
                allowed = bool(_STUDIO_CONTEXT.search(scope))
                output = match.group(0)
            elif name == "Murkoff":
                allowed = bool(_MURKOFF_CONTEXT.search(scope))
                output = match.group(0)
            elif name == "Peppa":
                allowed = bool(_PEPPA_CONTEXT.search(scope)) and not (
                    _PEPPA_PERSONAL_CONTEXT.search(scope))
                if match.group(0).endswith("World"):
                    output = "佩奇的世界"
                else:
                    output = "佩奇的" if match.group(0).endswith(("'s", "’s")) else "佩奇"
            elif name == "Phasmophobia":
                allowed = not _CLINICAL_CONTEXT.search(scope) and (
                    _is_complete_line(text, start, end)
                    or bool(_PHASMOPHOBIA_CONTEXT.search(scope)))
                output = _INLINE_TITLES[name]
            else:
                allowed = bool(_GAME_CONTEXT.search(scope))
                if name == "Stardew Valley" and _PLACE_CONTEXT.search(scope):
                    allowed = False
                output = _INLINE_TITLES[name]
            if allowed:
                spans.append((start, end, output))
    fragments: list[TranslationFragment] = []
    position = 0
    for start, end, output in sorted(spans):
        if start < position:
            continue
        if start > position:
            fragments.append(TranslationFragment(text[position:start], False))
        fragments.append(TranslationFragment(output, True))
        position = end
    if position < len(text):
        fragments.append(TranslationFragment(text[position:], False))
    return fragments


def prepare_source_idioms(text: str, context: str = "") -> str:
    """Paraphrase one confirmed gaming idiom before model tokenisation.

    This is not a fluency pass. Dance/body-part context vetoes the change,
    unknown idioms remain unchanged, and model output is never repaired.
    """
    scope = _scope(text, context)
    # Remove the idiom itself before checking a body-part veto: otherwise
    # its own word "toes" would disqualify every idiomatic occurrence.
    without_idiom = _IDIOM.sub("", scope)
    if not _IDIOM_CONTEXT.search(scope) or _LITERAL_TOES_CONTEXT.search(without_idiom):
        return text
    protected = [match.span() for match in _PROTECTED.finditer(text)]

    def replacement(match: re.Match[str]) -> str:
        if _intersects(*match.span(), protected):
            return match.group(0)
        first = match.group(0).split()[0]
        if first.isupper():
            return "KEEP YOU ALERT"
        if first[0].isupper():
            return "Keep you alert"
        return "keep you alert"

    return _IDIOM.sub(replacement, text)
