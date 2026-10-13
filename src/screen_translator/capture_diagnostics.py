"""Bounded, opt-in checks of the application's real capture path.

Images and recognized/translated text stay in memory. Reports deliberately
exclude coordinates, window titles, source text, translations and hashes.
This diagnoses pipeline stages, NOT visible game-overlay compatibility.
"""
from __future__ import annotations

import time

import numpy as np

from .capture.mss_backend import MSSCaptureBackend
from .contracts import Settings
from .core.text import choose_direction


def frame_statistics(image: np.ndarray, width: int, height: int) -> dict:
    if (not isinstance(image, np.ndarray) or image.dtype != np.uint8
            or image.shape != (height, width, 3)):
        raise ValueError("Invalid capture frame")
    pixels = image.astype(np.float32)
    luminance = pixels[:, :, 0] * .114 + pixels[:, :, 1] * .587 + pixels[:, :, 2] * .299
    near_black = float(np.mean(np.all(image <= 5, axis=2)))
    near_white = float(np.mean(np.all(image >= 250, axis=2)))
    return {
        "width": width, "height": height,
        "minimum_channel": int(image.min()), "maximum_channel": int(image.max()),
        "luminance_mean": round(float(luminance.mean()), 2),
        "luminance_std": round(float(luminance.std()), 2),
        "near_black_fraction": round(near_black, 4),
        "near_white_fraction": round(near_white, 4),
        "suspected_uniform_black": near_black >= .995,
        "suspected_uniform_white": near_white >= .995,
    }


def run_capture_test(settings: Settings, *, samples: int = 3, delay: float = 3.0,
                     capture_factory=MSSCaptureBackend, ocr_engine=None,
                     translator_engine=None, wait=time.sleep) -> dict:
    """Use only an existing ROI; no UI hooks, cache or settings writes.

An empty/black crop is a diagnostic observation, not an automatic error or
proof of DRM. Production factories and engines are created on this thread.
"""
    if not 1 <= samples <= 5 or not 0 <= delay <= 10:
        raise ValueError("Invalid diagnostic duration")
    report = {"mode": "saved-region-capture-health", "backend": "MSS-GDI",
              "completed": False, "samples_requested": samples, "samples": [],
              "failure_codes": [], "warnings": [],
              "stage_results": {"capture_succeeded": False,
                                "ocr_executed": False, "ocr_text_detected": False,
                                "local_translation_nonempty": False},
              "overlay_display_tested": False, "game_compatibility_tested": False,
              "privacy": {"screenshots_saved": False, "text_saved": False,
                          "coordinates_saved": False, "window_titles_saved": False}}
    region = settings.region
    if not region or not region.valid() or region.width * region.height > 80_000_000:
        report["failure_codes"].append("saved_region_missing_or_invalid")
        return report
    if ocr_engine is None:
        from .inference.ocr.rapidocr_engine import RapidOCREngine
        ocr_engine = RapidOCREngine(cpu_threads=settings.cpu_threads)
    if translator_engine is None:
        from .inference.translation.ctranslate2_engine import CTranslate2Engine
        translator_engine = CTranslate2Engine(cpu_threads=settings.cpu_threads)
    backend = None
    previous = None
    ocr_count = 0
    try:
        wait(delay)
        try:
            backend = capture_factory()
        except Exception:
            report["failure_codes"].append("capture_initialization_failed")
            return report
        for index in range(samples):
            started = time.perf_counter()
            try:
                image = backend.grab(region)
            except Exception:
                report["failure_codes"].append("capture_failed")
                break
            capture_ms = (time.perf_counter() - started) * 1000
            try:
                sample = frame_statistics(image, region.width, region.height)
            except (ValueError, TypeError):
                report["failure_codes"].append("capture_frame_invalid")
                break
            sample.update(index=index + 1, capture_ms=round(capture_ms, 1),
                          changed_from_previous=None if previous is None else not np.array_equal(previous, image))
            previous = image.copy()
            report["samples"].append(sample)
            started = time.perf_counter()
            try:
                recognized = ocr_engine.recognize(image)
            except Exception:
                report["failure_codes"].append("ocr_failed")
                break
            ocr_count += 1
            text = recognized.text.strip()
            direction = choose_direction(text, settings.direction) if text else None
            sample.update(ocr_ms=round((time.perf_counter() - started) * 1000, 1),
                          ocr_line_count=len(recognized.lines),
                          ocr_character_count=len(text),
                          ocr_confidence=round(float(recognized.confidence), 3),
                          direction=direction, translation_nonempty=False)
            if text:
                report["stage_results"]["ocr_text_detected"] = True
            if direction:
                started = time.perf_counter()
                try:
                    translation = translator_engine.translate(text, direction)
                    sample["translation_nonempty"] = bool(translation and translation.strip())
                    sample["translation_ms"] = round((time.perf_counter() - started) * 1000, 1)
                    if not sample["translation_nonempty"]:
                        report["failure_codes"].append("translation_empty")
                        break
                    report["stage_results"]["local_translation_nonempty"] = True
                    # Never put either transient string in a report or log.
                    del translation
                except Exception:
                    report["failure_codes"].append("translation_failed")
                    break
            del recognized, text, image
            if index + 1 < samples:
                wait(.25)
    finally:
        previous = None
        if backend is not None:
            try:
                backend.close()
            except Exception:
                report["failure_codes"].append("capture_cleanup_failed")
        report["stage_results"]["capture_succeeded"] = len(report["samples"]) == samples
        report["stage_results"]["ocr_executed"] = ocr_count == samples
        if report["samples"] and all(s["suspected_uniform_black"] for s in report["samples"]):
            report["warnings"].append("suspected_uniform_black_not_proof_of_capture_failure")
        if report["samples"] and all(s["suspected_uniform_white"] for s in report["samples"]):
            report["warnings"].append("suspected_uniform_white_not_proof_of_capture_failure")
        if ocr_count and not report["stage_results"]["ocr_text_detected"]:
            report["warnings"].append("no_text_detected_check_saved_region_and_display_mode")
        report["completed"] = not report["failure_codes"] and ocr_count == samples
    return report
