import numpy as np

from screen_translator.capture.change_detector import changed, fingerprint
from screen_translator.core.text import choose_direction, is_meaningful_change, normalize_text


def test_normalize_unicode_and_ocr_line_breaks():
    assert normalize_text("  Ｈｅｌｌｏ\n\u200b世界　１２３  ") == "Hello 世界 123"
    assert normalize_text("“Hello”") == '"Hello"'
    assert normalize_text("你好\n世界") == "你好世界"


def test_short_labels_and_numbers_are_always_meaningful():
    assert is_meaningful_change("ON", "NO")
    assert is_meaningful_change("剩余时间为 10 秒，请等待载入完毕", "剩余时间为 19 秒，请等待载入完毕")
    assert is_meaningful_change("The current price is 199.99 dollars", "The current price is 199.98 dollars")
    assert is_meaningful_change("好", "坏")


def test_spacing_punctuation_and_exact_duplicates_do_not_translate_again():
    assert not is_meaningful_change("Hello world!", "Hello world.")
    assert not is_meaningful_change("Hello   world", "Hello world")
    assert not is_meaningful_change("这是一个测试句子", "这是一个测试句子")
    assert is_meaningful_change("Please open the door", "Please close the window")


def test_long_near_match_requests_confirmation_in_pipeline():
    assert not is_meaningful_change("The quick brown fox jumps over the lazy dog.",
                                    "The quick brown fox jumps over the lazy dogs.")


def test_direction_handles_short_mixed_and_nonlanguage_content():
    assert choose_direction("你好，世界！") == "zh-en"
    assert choose_direction("Hello world") == "en-zh"
    assert choose_direction("OK 可以") == "zh-en"
    assert choose_direction("123 + / -") is None
    assert choose_direction("你好", "en-zh") == "en-zh"


def test_exact_fingerprint_catches_tiny_glyph_outside_sample_grid():
    old = np.zeros((1440, 2560, 3), dtype=np.uint8)
    new = old.copy()
    new[702:713, 2002:2005] = 255
    old_fp, new_fp = fingerprint(old), fingerprint(new)
    assert old_fp.digest != new_fp.digest
    # Tiny differences use checksum-stability verification even if the coarse
    # perceptual threshold is not met.
    assert fingerprint(old).digest == old_fp.digest


def test_focused_change_score_uses_text_area_denominator():
    old = np.zeros((1440, 2560, 3), dtype=np.uint8)
    new = old.copy()
    new[670:720, 1980:2010] = 255
    boxes = ((1950, 650, 2050, 750),)
    assert changed(fingerprint(old, boxes), fingerprint(new, boxes))
