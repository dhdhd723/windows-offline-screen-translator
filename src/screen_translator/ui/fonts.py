"""Application-local Chinese fallback; Windows fonts are never redistributed."""
from __future__ import annotations

import os
from pathlib import Path
import sys

from screen_translator.paths import install_root


FALLBACK_FILENAME = "NotoSansCJKsc-Regular.otf"
FALLBACK_FAMILY = "Noto Sans CJK SC"
CHINESE_SAMPLE = "屏幕翻译使用条款离线同意"


def bundled_font_path(root: Path | None = None, *, frozen: bool | None = None) -> Path:
    root = install_root() if root is None else Path(root)
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    return root / ("_internal/fonts" if frozen else "packaging/fonts") / FALLBACK_FILENAME


def _has_usable_chinese_font() -> bool:
    from PySide6.QtGui import QFont, QFontDatabase, QRawFont
    families = QFontDatabase.families(QFontDatabase.WritingSystem.SimplifiedChinese)
    for family in families:
        raw = QRawFont.fromFont(QFont(family))
        if raw.isValid() and all(raw.supportsCharacter(ord(character)) for character in CHINESE_SAMPLE):
            return True
    return False


def register_chinese_fallback(app, *, path: Path | None = None) -> str:
    """Keep installed fonts; add a bundled Han fallback only when needed.

    This requires a QApplication but makes no native input or capture calls.
    It adds a process-local font, not a Windows-installed font. An empty Qt
    font database (for example offscreen QA) also gets a readable default.
    """
    from PySide6.QtGui import QFont, QFontDatabase
    if _has_usable_chinese_font():
        return "system"
    path = bundled_font_path() if path is None else Path(path)
    font_id = QFontDatabase.addApplicationFont(str(path)) if path.is_file() else -1
    if font_id < 0:
        raise RuntimeError("Chinese display font is unavailable. Extract the complete application package, including _internal/fonts.")
    families = QFontDatabase.applicationFontFamilies(font_id)
    if FALLBACK_FAMILY not in families:
        raise RuntimeError("Bundled Chinese display font could not be registered.")
    # PySide 6.9.3 does not expose Qt's QChar-based script-fallback API.
    # Our UI consistently requests this family; supply a process-local
    # substitution only in the no-usable-Chinese-font case. This does not
    # overwrite or rename a Windows font.
    QFont.insertSubstitution("Microsoft YaHei UI", FALLBACK_FAMILY)
    # Do not change normal English Windows UI typography. If Qt cannot obtain
    # the existing default at all, Noto supplies both Latin and Chinese glyphs.
    available = QFontDatabase.families()
    if app.font().family() not in available:
        replacement = QFont(app.font())
        replacement.setFamily(FALLBACK_FAMILY)
        app.setFont(replacement)
    else:
        replacement = QFont(app.font())
        replacement.setFamilies(list(dict.fromkeys([*replacement.families(), FALLBACK_FAMILY])))
        app.setFont(replacement)
    return FALLBACK_FAMILY


def diagnostic_font_path(text: str, *, windows_fonts: Path | None = None,
                         fallback: Path | None = None) -> Path:
    """Choose a known CJK font for Chinese, never Arial's missing glyph boxes."""
    windows_fonts = (Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
                     if windows_fonts is None else Path(windows_fonts))
    fallback = bundled_font_path() if fallback is None else Path(fallback)
    for filename in ("msyh.ttc", "msjh.ttc", "simsun.ttc"):
        candidate = windows_fonts / filename
        if candidate.is_file():
            return candidate
    if fallback.is_file():
        return fallback
    needs_cjk = any("\u2e80" <= character <= "\u9fff" or "\uf900" <= character <= "\ufaff"
                    for character in text)
    latin = windows_fonts / "arial.ttf"
    if not needs_cjk and latin.is_file():
        return latin
    raise RuntimeError("Offline diagnostic font is unavailable. Extract the complete application package, including _internal/fonts.")
