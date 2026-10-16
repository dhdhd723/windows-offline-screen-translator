"""Small offline chat glossary, not a general language or identity detector."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping

CHAT_SLANG_VERSION = 3
MAX_OVERRIDES = 100
MAX_EXPANSION_LENGTH = 160
# Selected chat senses, not an exhaustive or context-aware slang dictionary.
# Source/ambiguity notes: docs/聊天内置词表.md. No runtime network lookup.
# 'tys' is the user's requested interpretation, not a universal definition.
BUILTIN_CHAT_SLANG = {
    "ty": "thanks", "tys": "thanks", "tysm": "thank you so much",
    "thx": "thanks", "yw": "no need to thank me",
    "np": "no problem", "brb": "be right back", "afk": "away from keyboard",
    "idk": "I do not know", "imo": "in my opinion",
    "imho": "in my humble opinion", "tbh": "to be honest",
    "pls": "please", "plz": "please",
    "btw": "by the way", "ngl": "to be honest",
    "afaik": "as far as I know", "iirc": "if I remember correctly",
    "ikr": "I know, right", "fwiw": "for what it is worth",
    "gtg": "got to go", "ttyl": "talk to you later",
    "omw": "on my way", "irl": "in real life", "nbd": "no big deal",
    "wdym": "what do you mean", "wyd": "what are you doing",
    "lmk": "let me know", "nvm": "never mind", "ofc": "of course",
    # Meaning-preserving paraphrases: literal idioms produced bad translations
    # with the bundled model (e.g. LMAO became a sentence about body parts).
    "lol": "haha", "lmao": "I cannot stop laughing",
    "rofl": "I cannot stop laughing", "smh": "I am disappointed",
    "gg": "good match", "glhf": "good luck, have fun",
    "ggwp": "good match, well played", "omg": "oh my God",
    "fyi": "for your information", "asap": "as soon as possible",
    "sm1": "someone", "l8r": "later",
    "cya": "see you", "cyaa": "see you", "prolly": "probably",
    "cuz": "because", "bc": "because", "ppl": "people", "pic": "picture",
    "rn": "right now", "fr": "for real", "hbu": "how about you",
    "yk": "you know", "def": "definitely", "istg": "I swear to God",
    # User-confirmed compatibility spelling, not an automatic typo corrector.
    "tytl": "talk to you later",
    # Vulgar selected chat senses; see the visible glossary/source notes.
    "mdfk": "motherfucker", "asf": "as fuck",
}
_KEY = re.compile(r"[a-z][a-z0-9]{0,23}", re.ASCII)
_LETTER = re.compile(r"[A-Za-z]", re.ASCII)
# Unicode word boundaries prevent edits inside names, identifiers and Han text.
# Hyphens/possessive apostrophes are deliberately not chat-token boundaries.
# A postfix intensifier needs English word order before reaching the small NMT
# model. Only listed adjective + asf pairs are reordered, never arbitrary prose.
_ASF_ADJECTIVES = (
    "tired|cool|scared|funny|good|bad|slow|fast|hard|easy|hot|cold|crazy|angry|"
    "sad|happy|loud|quiet|annoying|boring|strong|weak|expensive|cheap"
)
_TOKEN = re.compile(
    r"(?<![\w\-'’])(?:"
    rf"(?P<adjective>{_ASF_ADJECTIVES})(?P<gap>[ \t]+)(?P<intensifier>asf)"
    r"|(?P<token>[A-Za-z][A-Za-z0-9]*|2))(?![\w\-'’])", re.IGNORECASE,
)
# Never treat the numeral as a universal word. Only these narrow, whitespace-
# separated chat constructions opt in. Matching uses the original input once.
_NUMERIC_TO = re.compile(
    r"(?<![\w\-'’])(?:"
    r"(?:want|need|have|got|going|try|trying|ready|able)[ \t]+(?P<infinitive>2)"
    r"(?=[ \t]+(?:go|join|play|help|leave|wait|come|talk|see|get|buy|sell|win|run|start|stop)\b)"
    r"|(?:talk|speak|listen|send|give|pass)[ \t]+(?P<recipient>2)"
    r"(?=[ \t]+(?:me|you|him|her|us|them)\b)"
    r"|(?:go|come|head|return)[ \t]+(?P<destination>2)"
    r"(?=[ \t]+(?:me|you|him|her|us|them|the|my|our|your|spawn|base|lobby)\b)"
    r")", re.IGNORECASE,
)
_PROTECTED = re.compile(
    r"```[\s\S]*?(?:```|\Z)"
    r"|`[^`\n]*(?:`|$)"
    r"|(?<![\w+.-])(?:[A-Za-z][A-Za-z0-9+.-]{0,31}://|www\.)[^\s<>]+"
    r"|(?<![\w@])[\w.+-]+@(?:[\w-]+\.)+[\w-]+"
    r"|(?<!\w)(?:[A-Za-z]:[\\/]|\\\\)[^\s]+"
    r"|(?<!\w)(?:\.{0,2}[\\/])[A-Za-z0-9_.-]+(?:[\\/][A-Za-z0-9_.-]+)*"
    r"|(?<!\w)[A-Za-z0-9_.-]+(?:[\\/][A-Za-z0-9_.-]+)+"
    r"|(?<!\w)(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,24}(?::\d+)?(?:/[^\s<>]*)?"
    r"|[@#][\w.-]+"
    # Explicit dates and Python function syntax are not conversational senses.
    r"|(?i:(?<!\w)(?:[0-9]{1,4}[ \t]+bc|bc[ \t]+[0-9]{1,4})(?!\w))"
    r"|\bdef[ \t]+[A-Za-z_]\w*[ \t]*\("
    r"|^[^\n:]{1,64}:\s*",
    re.MULTILINE,
)


def sanitize_overrides(value: object) -> dict[str, str]:
    """Ignore damaged stored rules; the editor validates strictly before saving."""
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, str] = {}
    for key, expansion in value.items():
        if not isinstance(key, str) or not isinstance(expansion, str):
            continue
        # Check the untrimmed value too, so newline/control injection cannot
        # become an apparently valid rule after strip().
        if any(ord(char) < 32 or ord(char) > 126 for char in expansion):
            continue
        key, expansion = key.strip(), expansion.strip()
        if not key.isascii():
            continue
        key = key.lower()
        if (not _KEY.fullmatch(key) or not 1 <= len(expansion) <= MAX_EXPANSION_LENGTH
                or not _LETTER.search(expansion)):
            continue
        if key not in result and len(result) >= MAX_OVERRIDES:
            continue
        result[key] = expansion
    return result


def _glossary(overrides: object) -> dict[str, str]:
    return {**BUILTIN_CHAT_SLANG, **sanitize_overrides(overrides)}


def chat_slang_fingerprint(enabled: bool, overrides: object = None) -> str:
    """Bind cached results to the exact effective, ordered-independent policy."""
    if not enabled:
        return f"chat-slang-v{CHAT_SLANG_VERSION}:disabled"
    custom = sanitize_overrides(overrides)
    # An explicit ASF override disables phrase reordering even if its English
    # text equals the builtin. The cache must distinguish that behavior too.
    material = {"glossary": _glossary(custom),
                "postfix_asf_user_override": "asf" in custom}
    blob = json.dumps(material, sort_keys=True, ensure_ascii=True,
                      separators=(",", ":")).encode("ascii")
    return f"chat-slang-v{CHAT_SLANG_VERSION}:" + hashlib.sha256(blob).hexdigest()


def expand_chat_slang(text: str, overrides: object = None) -> str:
    """Expand once, outside explicit name/link/code spans, without changing rows.

    Bare words cannot reliably be distinguished from unlabelled usernames. No
    fuzzy spelling corrections or guesses for unknown slang are made here.
    """
    custom = sanitize_overrides(overrides)
    glossary = _glossary(custom)
    spans = [match.span() for match in _PROTECTED.finditer(text)]
    numeric_to_spans = {
        match.span(group)
        for match in _NUMERIC_TO.finditer(text)
        for group in ("infinitive", "recipient", "destination")
        if match.group(group) is not None
    }
    position = 0

    def replacement(match: re.Match[str]) -> str:
        nonlocal position
        while position < len(spans) and spans[position][1] <= match.start():
            position += 1
        if (position < len(spans) and match.start() < spans[position][1]
                and match.end() > spans[position][0]):
            return match.group(0)
        adjective = match.group("adjective")
        if adjective is not None:
            if "asf" not in custom and adjective.lower() not in custom:
                return "extremely " + adjective
            return (glossary.get(adjective.lower(), adjective) + match.group("gap")
                    + glossary["asf"])
        token = match.group("token").lower()
        if token == "2":
            return "to" if match.span() in numeric_to_spans else match.group(0)
        return glossary.get(token, match.group(0))

    return _TOKEN.sub(replacement, text)
