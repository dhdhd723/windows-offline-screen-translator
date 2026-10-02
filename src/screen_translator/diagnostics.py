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
            ocr = RapidOCREngine(cpu_threads=2)
            translator = CTranslate2Engine(cpu_threads=2)
            cases = [("The translation works offline.", "en-zh"),
                     ("屏幕翻译支持离线运行。", "zh-en")]
            for original, direction in cases:
                started = time.perf_counter()
                recognized = ocr.recognize(text_fixture(original))
                ocr_ms = (time.perf_counter() - started) * 1000
                started = time.perf_counter()
                translated = translator.translate(recognized.text, direction)
                translation_ms = (time.perf_counter() - started) * 1000
                valid_ocr = ("offline" in recognized.text.lower() if direction == "en-zh"
                             else "离线" in recognized.text)
                valid_translation = (any("\u4e00" <= c <= "\u9fff" for c in translated)
                                     if direction == "en-zh" else
                                     any("a" <= c.lower() <= "z" for c in translated))
                report["tests"].append({"input": original, "direction": direction,
                                        "ocr": recognized.text, "translation": translated,
                                        "ocr_ms_cold_or_warm": round(ocr_ms, 1),
                                        "translation_ms_cold": round(translation_ms, 1),
                                        "passed": valid_ocr and valid_translation})
                started = time.perf_counter()
                translator.translate(original, direction)
                report["tests"][-1]["translation_ms_warm"] = round((time.perf_counter() - started) * 1000, 1)
            report["network_attempts"] = attempts.copy()
            report["passed"] = not attempts and all(case["passed"] for case in report["tests"])
    except Exception as exc:
        logging.exception("Offline diagnostics failed")
        report["error"] = f"{type(exc).__name__}: {exc}"
    return report

