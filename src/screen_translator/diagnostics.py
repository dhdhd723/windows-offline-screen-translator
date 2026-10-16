from __future__ import annotations

from contextlib import contextmanager
import json
import logging
import socket
import time

from . import __version__
from .paths import model_root


@contextmanager
def no_network():
    originals = (socket.socket.connect, socket.socket.connect_ex, socket.create_connection)
    attempts = []

    def deny(*args, **kwargs):
        attempts.append(str(args[1:] if len(args) > 1 else args))
        raise RuntimeError("Network access is disabled during offline self-test")

    socket.socket.connect = deny
    socket.socket.connect_ex = deny
    socket.create_connection = deny
    try:
        yield attempts
    finally:
        socket.socket.connect, socket.socket.connect_ex, socket.create_connection = originals


def text_fixture(text: str):
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    from .ui.fonts import diagnostic_font_path
    # Read the font file directly. Headless/sandboxed Windows processes may
    # not enumerate native fonts and QPainter would then draw only tofu boxes.
    font_path = diagnostic_font_path(text)
    image = Image.new("RGB", (1080, 130), "#202020")
    painter = ImageDraw.Draw(image)
    painter.text((28, 65), text, font=ImageFont.truetype(str(font_path), 40),
                 fill="white", anchor="lm")
    return np.asarray(image)[:, :, ::-1].copy()


def run_self_test() -> dict:
    from .application import check_models
    report = {"passed": False, "version": __version__, "network_attempts": [], "tests": []}
    missing = check_models()
    if missing:
        report["error"] = "Missing model files: " + ", ".join(missing)
        return report
    try:
        with no_network() as attempts:
            from .inference.ocr.rapidocr_engine import RapidOCREngine
            from .inference.translation.ctranslate2_engine import CTranslate2Engine
            from .inference.translation.quality import evaluate_translation_quality
            ocr = RapidOCREngine(cpu_threads=2)
            translator = CTranslate2Engine(cpu_threads=2)
            cases = [("The translation works offline.", "en-zh", "offline", (("翻译",), ("离线", "脱机"))),
                     ("屏幕翻译支持离线运行。", "zh-en", "离线", (("screen",), ("offline",))),
                     ("STARDEW VALLEY", "en-zh", "stardew valley", (("星露谷物语",),))]
            for original, direction, expected_ocr, word_groups in cases:
                started = time.perf_counter()
                recognized = ocr.recognize(text_fixture(original))
                ocr_ms = (time.perf_counter() - started) * 1000
                started = time.perf_counter()
                translated = translator.translate(recognized.text, direction)
                translation_ms = (time.perf_counter() - started) * 1000
                valid_ocr = expected_ocr in recognized.text.casefold()
                valid_translation = all(any(word.casefold() in translated.casefold() for word in alternatives)
                                        for alternatives in word_groups)
                report["tests"].append({"input": original, "direction": direction,
                                        "ocr": recognized.text, "translation": translated,
                                        "ocr_ms_cold_or_warm": round(ocr_ms, 1),
                                        "translation_ms_cold": round(translation_ms, 1),
                                        "passed": valid_ocr and valid_translation})
                started = time.perf_counter()
                translator.translate(original, direction)
                report["tests"][-1]["translation_ms_warm"] = round((time.perf_counter() - started) * 1000, 1)
            report["translation_quality"] = evaluate_translation_quality(translator)
            from .inference.translation.policy_diagnostics import evaluate_output_policy
            report["output_policy"] = evaluate_output_policy(translator)
            from .core.chat_diagnostics import evaluate_chat_translation
            report["chat_translation"] = evaluate_chat_translation(ocr, translator, text_fixture)
            from .inference import read_manifest
            if "ja-zh" in read_manifest(model_root()).get("translation", {}):
                from .inference.translation.japanese_diagnostics import evaluate_japanese
                report["japanese_translation"] = evaluate_japanese(ocr, translator, text_fixture)
            report["network_attempts"] = attempts.copy()
            report["passed"] = (not attempts and all(case["passed"] for case in report["tests"])
                                and report["translation_quality"]["passed_required_scope"]
                                and report["output_policy"]["passed"]
                                and report["chat_translation"]["passed"]
                                and report.get("japanese_translation", {}).get("passed", True))
    except Exception as exc:
        logging.exception("Offline diagnostics failed")
        report["error"] = f"{type(exc).__name__}: {exc}"
    return report

