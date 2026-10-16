"""OpenCC 官方 t2s 词典驱动的轻量转换，仅用于最终中文译文。

This is not the complete OpenCC engine or a regional vocabulary converter.
The pinned dictionary is compiled into the executable; no model, DLL, network
access, or mutable external dictionary is needed. Phrase replacements are final
and are never fed back through character conversion (for example, 乾隆).
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from threading import Lock
from types import MappingProxyType
from typing import Mapping


_EXPECTED_DATA_SHA256 = "72f97b4327c93bdd767896bab5f3f78b380ab77d84ebf3112011e6bb29100d61"
SCRIPT_POLICY_ID = "opencc-t2s-ver.1.1.9-greedy-v1:" + _EXPECTED_DATA_SHA256
_HAN = re.compile("[\u3400-\u9fff\uf900-\ufaff\U00020000-\U000323af]")
_LOAD_LOCK = Lock()


@dataclass(frozen=True)
class _Converter:
    characters: Mapping[str, str]
    phrases_by_start: Mapping[str, tuple[tuple[str, str], ...]]


_converter: _Converter | None = None


def _load_converter() -> _Converter:
    """Validate and build one immutable converter, lazily and thread-safely."""
    global _converter
    with _LOAD_LOCK:
        if _converter is not None:
            return _converter
        # Keep this a local static import: lazy at runtime, discoverable by
        # PyInstaller without adding a runtime resource or hidden dependency.
        try:
            from . import _opencc_t2s_data as data
        except ImportError as exc:
            raise RuntimeError("离线简体词典缺失，请重新解压完整运行包。") from exc

        characters = data.TS_CHARACTERS
        phrases = data.TS_PHRASES
        canonical = json.dumps([characters, phrases], ensure_ascii=False,
                               separators=(",", ":")).encode("utf-8")
        actual_hash = hashlib.sha256(canonical).hexdigest()
        if (data.CANONICAL_PAIRS_SHA256 != _EXPECTED_DATA_SHA256
                or actual_hash != _EXPECTED_DATA_SHA256
                or data.OPENCC_TAG != "ver.1.1.9"
                or data.OPENCC_COMMIT != "556ed22496d650bd0b13b6c163be9814637970ae"):
            raise RuntimeError("离线简体词典完整性校验失败，请重新解压完整运行包。")
        if (len(characters) != 4113 or len(phrases) != 278
                or any(len(key) != 1 or not value for key, value in characters)
                or any(len(key) < 2 or not value for key, value in phrases)
                or len(dict(characters)) != len(characters)
                or len(dict(phrases)) != len(phrases)):
            raise RuntimeError("离线简体词典结构错误，请重新解压完整运行包。")
        grouped: dict[str, list[tuple[str, str]]] = {}
        for key, value in phrases:
            grouped.setdefault(key[0], []).append((key, value))
        by_start = {
            start: tuple(sorted(rows, key=lambda row: (-len(row[0]), row[0])))
            for start, rows in grouped.items()
        }
        _converter = _Converter(
            MappingProxyType(dict(characters)), MappingProxyType(by_start),
        )
        return _converter


def to_simplified(text: str) -> str:
    """Convert Chinese script without rewriting whitespace or non-Han text.

    At each original text position, choose the longest official phrase; fall
    back to the first official character candidate. Unknown characters remain
    unchanged. Dictionary loss/corruption raises instead of silently returning
    traditional output. The caller must separately protect identities and apply
    this only to en→zh output; this function does not infer a language direction.
    """
    if not text or _HAN.search(text) is None:
        return text
    converter = _load_converter()
    result: list[str] = []
    position = 0
    while position < len(text):
        char = text[position]
        for phrase, replacement in converter.phrases_by_start.get(char, ()):
            if text.startswith(phrase, position):
                result.append(replacement)
                position += len(phrase)
                break
        else:
            result.append(converter.characters.get(char, char))
            position += 1
    return "".join(result)
