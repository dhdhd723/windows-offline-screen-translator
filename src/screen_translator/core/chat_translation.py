"""Deterministic standalone chat terms and conservative message-name handling.

This is an offline adapter around the existing translator, not a general slang
or game-context detector. Unknown abbreviations (for example ``oms``) are never
assigned a guessed meaning. Longer messages still use the local model.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass

from screen_translator.core.chat_slang import (
    chat_slang_fingerprint, expand_chat_slang, sanitize_overrides,
)
from screen_translator.core.text import normalize_layout_text
from screen_translator.inference import InferenceCancelled, InputLimitError


CHAT_TRANSLATION_VERSION = 1
# Selected meanings match the existing, explicitly documented English glossary.
# These are reliable standalone-message answers, not replacements in sentences.
BUILTIN_CHAT_ZH = {
    "ty": "谢谢", "tys": "谢谢", "tysm": "非常感谢",
    "thx": "谢谢", "yw": "不客气", "np": "没问题",
    "brb": "马上回来", "afk": "暂时离开键盘",
    "idk": "我不知道", "imo": "我觉得", "imho": "依我拙见",
    "tbh": "说实话", "pls": "请", "plz": "请", "btw": "顺便说一下",
    "ngl": "说实话", "afaik": "据我所知", "iirc": "如果我没记错",
    "ikr": "我也这么觉得", "fwiw": "仅供参考",
    "gtg": "我得走了", "ttyl": "回头聊", "omw": "我在路上",
    "irl": "现实生活中", "nbd": "没什么大不了",
    "wdym": "你是什么意思", "wyd": "你在做什么",
    "lmk": "告诉我一声", "nvm": "算了", "ofc": "当然",
    "lol": "哈哈", "lmao": "笑死我了", "rofl": "笑死我了",
    "smh": "真让人失望", "gg": "打得不错",
    "glhf": "祝你好运，玩得开心", "ggwp": "打得不错，表现很好",
    "omg": "天啊", "fyi": "供你参考", "asap": "尽快",
}


def chat_translation_fingerprint(overrides: object = None) -> str:
    """Do not reuse pre-adapter expansions that translated names or echoed ty."""
    return (f"chat-translation-v{CHAT_TRANSLATION_VERSION}|"
            + chat_slang_fingerprint(True, overrides))

# Only a single short identity, optionally bracketed or with one channel tag.
# Arbitrary phrases before a colon are not accepted as usernames.
# A detector may split an underscore-containing identity into fragments,
# e.g. Fixture_ _User. Preserve that OCR prefix instead of translating it.
# Still reject arbitrary multiword phrases before a colon.
_IDENTIFIER = r"[\w][\w.-]{0,31}(?:[ \t]+_[\w.-]{0,31})?"
_NAME_ROW = re.compile(
    rf"(?P<prefix>(?:(?P<name>{_IDENTIFIER})"
    rf"|\[(?P<bracket_name>{_IDENTIFIER})\]"
    rf"|\[(?P<channel>{_IDENTIFIER})\] (?P<channel_name>{_IDENTIFIER})):[ \t]*)"
    r"(?P<body>.+)\Z"
)
# No backticks, slashes, hyphens, underscores or colon: code/paths/identity
# fragments must not become standalone direct answers.
_WRAPPER_START = r'[\(\[\{"\'“‘]*'
_WRAPPER_END = r'[\)\]\}"\'”’.,!?;…，。！？；]*'
_STANDALONE = re.compile(
    rf"(?P<before>{_WRAPPER_START})(?P<token>[A-Za-z][A-Za-z0-9]*)"
    rf"(?P<after>{_WRAPPER_END})\Z"
)
_TAKE_LEAD = re.compile(
    rf"(?P<before>{_WRAPPER_START})take lead(?P<after>{_WRAPPER_END})\Z",
    re.IGNORECASE,
)


def _named_row(row: str) -> tuple[str, str] | None:
    match = _NAME_ROW.fullmatch(row)
    if match is None:
        return None
    name = match.group("name") or match.group("bracket_name") or match.group("channel_name")
    if not any(character.isalpha() for character in name):
        # E.g. 12:30 and 123: 45 are not chat identities.
        return None
    body = match.group("body")
    if body.startswith("//") or (len(name) == 1 and body.startswith(("\\", "/"))):
        # https://..., C:\\... and C:/... are not chat prefixes.
        return None
    return match.group("prefix"), body


def chat_source_layout(text: str, text_layout: str = "continuous", enabled: bool = True) -> str:
    """Return effective layout; auto-preserve two clearly named chat messages.

    Ordinary wrapped prose, a single named row and disabled chat handling retain
    continuous-mode behavior. This is intentionally not a visual/game detector.
    """
    if text_layout == "lines":
        return "lines"
    if enabled:
        rows = normalize_layout_text(text, "lines").splitlines()
        if sum(_named_row(row) is not None for row in rows) >= 2:
            return "lines"
    return "continuous"


def chat_direction_source(text: str, text_layout: str = "continuous") -> str:
    """An explicit nickname must not decide the language of its message body."""
    source = normalize_layout_text(text, chat_source_layout(text, text_layout))
    return "\n".join((named[1] if (named := _named_row(row)) else row)
                     for row in source.splitlines())


@dataclass(frozen=True)
class _ChatRow:
    prefix: str
    body: str
    expanded: str
    direct: str | None


def _direct_answer(body: str, overrides: dict[str, str], *, named: bool) -> str | None:
    match = _STANDALONE.fullmatch(body)
    if match is not None:
        token = match.group("token").lower()
        if token not in overrides and token in BUILTIN_CHAT_ZH:
            return match.group("before") + BUILTIN_CHAT_ZH[token] + match.group("after")
    # This phrase has a non-metal sense in a named chat command only. Do not
    # perform a broad 'lead' rewrite or alter lead poisoning / lead bullets.
    if named and not any(token in overrides for token in ("take", "lead")):
        match = _TAKE_LEAD.fullmatch(body)
        if match is not None:
            return match.group("before") + "带头" + match.group("after")
    return None


def _check_cancel(cancel_check: Callable[[], bool] | None) -> None:
    if cancel_check is not None and cancel_check():
        raise InferenceCancelled()


def _model_translate(translator, text: str, direction: str,
                     cancel_check: Callable[[], bool] | None) -> str:
    _check_cancel(cancel_check)
    cancellable = getattr(translator, "translate_cancellable", None)
    if callable(cancellable) and cancel_check is not None:
        result = cancellable(text, direction, cancel_check)
    else:
        result = translator.translate(text, direction)
    _check_cancel(cancel_check)
    if not isinstance(result, str) or not result.strip():
        raise RuntimeError("本地模型返回空译文")
    return result.strip()


@dataclass(frozen=True)
class ChatTranslationPlan:
    """Immutable per-frame policy: names never enter the model in special rows."""

    cache_source: str
    _rows: tuple[_ChatRow, ...]
    _plain_model_text: str | None

    def translate(self, translator, direction: str,
                  cancel_check: Callable[[], bool] | None = None) -> str:
        """Translate an en-zh plan with freshness checks even for direct answers.

        The pipeline enables this adapter only for en-zh and the enabled chat
        setting. It remains responsible for generation-safe publication/cache.
        """
        _check_cancel(cancel_check)
        if self._plain_model_text is not None:
            if not self._plain_model_text:
                _check_cancel(cancel_check)
                return ""
            return _model_translate(translator, self._plain_model_text, direction, cancel_check)
        translated: list[str] = []
        for row in self._rows:
            _check_cancel(cancel_check)
            answer = row.direct
            if answer is None:
                answer = _model_translate(translator, row.expanded, direction, cancel_check)
            _check_cancel(cancel_check)
            translated.append(row.prefix + answer)
        _check_cancel(cancel_check)
        return "\n".join(translated)


def prepare_chat_translation(text: str, text_layout: str = "continuous",
                             overrides: object = None) -> ChatTranslationPlan:
    """Prepare once; custom English overrides always outrank direct answers.

    Longer ordinary text retains the existing one-pass expansion and single
    model invocation. Only recognized identities / direct rows become a small
    canonical structured cache source, keeping their boundaries and policy.
    """
    custom = sanitize_overrides(overrides)
    layout = chat_source_layout(text, text_layout)
    source = normalize_layout_text(text, layout)
    rows: list[_ChatRow] = []
    special = False
    for row in source.splitlines():
        named = _named_row(row)
        prefix, body = named if named is not None else ("", row)
        expanded = expand_chat_slang(body, custom)
        direct = _direct_answer(body, custom, named=bool(prefix))
        special = special or bool(prefix) or direct is not None
        rows.append(_ChatRow(prefix, body, expanded, direct))
    if special and len(source) > 16000:
        raise InputLimitError("框选文字过多，请缩小翻译区域；原文没有被截断。")
    if not special:
        model_text = expand_chat_slang(source, custom)
        return ChatTranslationPlan(model_text, tuple(rows), model_text)
    material = {
        "version": CHAT_TRANSLATION_VERSION,
        "layout": layout,
        "rows": [{"prefix": row.prefix, "body": row.body,
                  "expanded": row.expanded, "direct": row.direct} for row in rows],
    }
    cache_source = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return ChatTranslationPlan(cache_source, tuple(rows), None)
