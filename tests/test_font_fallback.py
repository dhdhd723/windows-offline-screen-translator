"""Process-local font and synthetic-image tests, without screen capture."""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import ImageFont
from PySide6.QtGui import QFont, QRawFont
from PySide6.QtWidgets import QApplication

from screen_translator.diagnostics import text_fixture
from screen_translator.ui import fonts


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    yield app


def test_source_and_frozen_font_paths(tmp_path):
    assert fonts.bundled_font_path(tmp_path, frozen=False) == (
        tmp_path / "packaging/fonts/NotoSansCJKsc-Regular.otf")
    assert fonts.bundled_font_path(tmp_path, frozen=True) == (
        tmp_path / "_internal/fonts/NotoSansCJKsc-Regular.otf")


def test_real_system_cjk_font_precedes_bundle(tmp_path):
    windows_fonts = tmp_path / "Windows/Fonts"
    windows_fonts.mkdir(parents=True)
    existing = windows_fonts / "msyh.ttc"
    existing.write_bytes(b"Synthetic font path selection")
    assert fonts.diagnostic_font_path("中文", windows_fonts=windows_fonts,
                                       fallback=tmp_path / "missing.otf") == existing


@pytest.mark.parametrize("text", ["中文条款", "English terms"])
def test_english_windows_uses_bundled_font_for_synthetic_tests(tmp_path, text):
    windows_fonts = tmp_path / "Windows/Fonts"
    windows_fonts.mkdir(parents=True)
    (windows_fonts / "arial.ttf").write_bytes(b"Synthetic Latin-only font")
    fallback = fonts.bundled_font_path()
    assert fallback.is_file()
    assert fonts.diagnostic_font_path(text, windows_fonts=windows_fonts, fallback=fallback) == fallback


def test_chinese_never_silently_uses_a_latin_only_font(tmp_path):
    (tmp_path / "arial.ttf").write_bytes(b"Synthetic Latin-only font")
    fallback = tmp_path / "missing.otf"
    with pytest.raises(RuntimeError, match="Offline diagnostic font is unavailable"):
        fonts.diagnostic_font_path("屏幕离线翻译", windows_fonts=tmp_path, fallback=fallback)
    assert fonts.diagnostic_font_path("English", windows_fonts=tmp_path, fallback=fallback) == (
        tmp_path / "arial.ttf")


def test_working_system_font_is_not_replaced_or_dependent_on_bundle(monkeypatch, tmp_path, qapp):
    before = qapp.font().toString()
    monkeypatch.setattr(fonts, "_has_usable_chinese_font", lambda: True)
    assert fonts.register_chinese_fallback(qapp, path=tmp_path / "missing.otf") == "system"
    assert qapp.font().toString() == before


def test_missing_font_is_reported_when_no_system_chinese_font_exists(monkeypatch, tmp_path, qapp):
    monkeypatch.setattr(fonts, "_has_usable_chinese_font", lambda: False)
    with pytest.raises(RuntimeError, match="Chinese display font is unavailable"):
        fonts.register_chinese_fallback(qapp, path=tmp_path / "missing.otf")


def test_fallback_preserves_existing_latin_default_as_first_family(qapp, monkeypatch):
    from PySide6.QtGui import QFontDatabase
    monkeypatch.setattr(fonts, "_has_usable_chinese_font", lambda: False)
    monkeypatch.setattr(QFontDatabase, "families", lambda: ["Arial", fonts.FALLBACK_FAMILY])

    class SyntheticEnglishApp:
        def __init__(self):
            self.default = QFont("Arial", 10)

        def font(self):
            return QFont(self.default)

        def setFont(self, font):
            self.default = QFont(font)

    application = SyntheticEnglishApp()
    assert fonts.register_chinese_fallback(application) == fonts.FALLBACK_FAMILY
    assert application.default.families() == ["Arial", fonts.FALLBACK_FAMILY]
    assert application.default.pointSize() == 10


def test_official_static_font_supplies_real_distinct_chinese_glyphs(qapp, monkeypatch):
    monkeypatch.setattr(fonts, "_has_usable_chinese_font", lambda: False)
    assert fonts.register_chinese_fallback(qapp) == fonts.FALLBACK_FAMILY
    raw = QRawFont.fromFont(QFont("Microsoft YaHei UI"))
    assert raw.isValid()
    glyphs = raw.glyphIndexesForString(fonts.CHINESE_SAMPLE)
    assert len(glyphs) == len(fonts.CHINESE_SAMPLE)
    assert all(glyph > 0 for glyph in glyphs)
    assert len(set(glyphs)) == len(set(fonts.CHINESE_SAMPLE))
    pillow_font = ImageFont.truetype(str(fonts.bundled_font_path()), 40)
    assert pillow_font.getname() == (fonts.FALLBACK_FAMILY, "Regular")
    assert bytes(pillow_font.getmask("屏")) != bytes(pillow_font.getmask("翻"))


def test_no_windows_fonts_still_produces_chinese_ocr_fixture(monkeypatch, tmp_path):
    monkeypatch.setenv("WINDIR", str(tmp_path / "empty-windows"))
    image = text_fixture("屏幕翻译支持离线运行。")
    assert image.shape == (130, 1080, 3)
    assert (image[:, :, 0] > 100).sum() > 1000
