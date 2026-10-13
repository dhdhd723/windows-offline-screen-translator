import json

import numpy as np
import pytest

from screen_translator.capture_diagnostics import frame_statistics, run_capture_test
from screen_translator.contracts import OCRResult, Region, Settings, TextLine


class Capture:
    def __init__(self, image, error=None):
        self.image = image
        self.error = error
        self.closed = 0

    def grab(self, region):
        if self.error:
            raise self.error
        return self.image.copy()

    def close(self):
        self.closed += 1


class OCR:
    def __init__(self, text="secret source text"):
        self.text = text

    def recognize(self, image):
        return OCRResult(self.text, (TextLine(self.text, .9),) if self.text else (), .9)


class Translator:
    def translate(self, text, direction):
        return "secret translated text"


def check(capture, *, ocr=None, samples=3):
    return run_capture_test(Settings(region=Region(-123, 456, 24, 12)),
                            capture_factory=lambda: capture, ocr_engine=ocr or OCR(),
                            translator_engine=Translator(), wait=lambda _: None,
                            samples=samples)


def test_stages_without_private_text_coordinates_or_hashes():
    capture = Capture(np.arange(24 * 12 * 3, dtype=np.uint8).reshape(12, 24, 3))
    report = check(capture)
    assert report["completed"]
    assert all(report["stage_results"].values())
    assert not report["game_compatibility_tested"]
    assert not report["overlay_display_tested"]
    assert capture.closed == 1
    assert report["samples"][0]["changed_from_previous"] is None
    assert report["samples"][1]["changed_from_previous"] is False
    encoded = json.dumps(report)
    for private in ("secret", "-123", "456", "digest", "sha256", "source_text", '"window_title":'):
        assert private not in encoded


@pytest.mark.parametrize("value,warning", [(0, "suspected_uniform_black"), (255, "suspected_uniform_white")])
def test_uniform_frames_are_observations_not_automatic_failures(value, warning):
    capture = Capture(np.full((12, 24, 3), value, np.uint8))
    report = check(capture, ocr=OCR(""))
    assert report["completed"]
    assert any(warning in item for item in report["warnings"])
    assert not report["stage_results"]["ocr_text_detected"]
    assert not report["stage_results"]["local_translation_nonempty"]


def test_grab_failure_is_sanitized_and_closed():
    capture = Capture(None, OSError("/diagnostics-fixture/screenshots/secret.png"))
    report = check(capture)
    assert report["failure_codes"] == ["capture_failed"]
    assert not report["completed"]
    assert capture.closed == 1
    assert "diagnostics-fixture" not in json.dumps(report)


def test_wrong_size_is_rejected_and_closed():
    capture = Capture(np.zeros((13, 24, 3), np.uint8))
    assert check(capture)["failure_codes"] == ["capture_frame_invalid"]
    assert capture.closed == 1


def test_missing_region_does_not_construct_capture():
    def forbidden():
        raise AssertionError("capture was constructed")
    report = run_capture_test(Settings(), capture_factory=forbidden, ocr_engine=OCR(),
                              translator_engine=Translator(), wait=lambda _: None)
    assert report["failure_codes"] == ["saved_region_missing_or_invalid"]


@pytest.mark.parametrize("samples,delay", [(0, 0), (6, 0), (1, -1), (1, 11)])
def test_diagnostic_bounds(samples, delay):
    with pytest.raises(ValueError):
        run_capture_test(Settings(), samples=samples, delay=delay)


def test_cleanup_failure_is_not_success():
    capture = Capture(np.full((12, 24, 3), 50, np.uint8))
    def failure():
        capture.closed += 1
        raise OSError("private path")
    capture.close = failure
    report = check(capture)
    assert report["failure_codes"] == ["capture_cleanup_failed"]
    assert not report["completed"]


def test_invalid_pixel_format():
    with pytest.raises(ValueError):
        frame_statistics(np.zeros((12, 24, 4), np.uint8), 24, 12)
    with pytest.raises(ValueError):
        frame_statistics(np.zeros((12, 24, 3), np.float32), 24, 12)
