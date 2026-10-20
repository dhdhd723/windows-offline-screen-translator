"""Offline chat smoke test using generated pixels, never the user's screen.

Reuses the existing no_network guard, including for loopback connections. This
guards selected Python TCP APIs, not DNS/UDP, native libraries or OS traffic.
"""
from __future__ import annotations

from pathlib import Path
import re
import time

from . import __version__
from .core.chat_translation import prepare_chat_translation
from .core.chinese_script import to_simplified
from .diagnostics import no_network
from .inference import ModelFilesError
from .paths import model_root


FIXTURE_ROWS = ("Alice: Hello how are you?", "Bob: Please wait for me.")
COMPOSED_SOURCE = "Alice: ty np lol\nBob: brb; cya"
COMPOSED_EXPECTED = "Alice: 谢谢，没问题，哈哈\nBob: 马上回来，再见"
_HAN = re.compile(r"[\u3400-\u9fff]")
_SPECIAL = re.compile(r"<\s*unk\s*>|<\|[^>]*>|<｜[^>]*>", re.IGNORECASE)


class _NoModelExpected:
    """A deterministic glossary test must fail if it falls through to a model."""

    def translate(self, *args, **kwargs):
        raise RuntimeError("Deterministic short replies unexpectedly called a model")


def synthetic_chat_image():
    """Build fixed two-speaker pixels in memory; never open a screenshot."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    from .ui.fonts import diagnostic_font_path
    font = ImageFont.truetype(str(diagnostic_font_path(" ".join(FIXTURE_ROWS))), 38)
    image = Image.new("RGB", (1080, 220), "#202020")
    draw = ImageDraw.Draw(image)
    for top, text in zip((45, 125), FIXTURE_ROWS):
        draw.text((28, top), text, font=font, fill="white", anchor="lt")
    return np.asarray(image)[:, :, ::-1].copy()


def run_chat_self_test(model_dir: Path | None = None, *, cpu_threads: int = 2,
                       ocr_factory=None, translator_factory=None, image_factory=None) -> dict:
    """Check bundled OCR/fast model/chat plumbing, not general translation quality."""
    report = {"passed": False, "version": __version__, "mode": "fast", "direction": "en-zh",
              "model_id": "", "tests": [], "desktop_captured": False, "global_hotkeys_registered": False,
              "tray_created": False, "synthetic_image_saved": False, "private_screenshot_read": False,
              "actual_game_tested": False, "semantic_quality_verified": False, "os_network_audited": False,
              "cleanup": {"attempted": False, "passed": False}, "network_attempts": [],
              "network_guard": {"blocked_attempts": [], "loopback_allowed": False},
              "boundary": "Generated two-message OCR fixture through the bundled fast local model and chat adapter, plus a deterministic short-reply check. Passing is not general semantic-quality, live Roblox, fullscreen, recording or clean-Windows acceptance. The existing no_network guard blocks selected Python TCP calls, including loopback; DNS/UDP, native and OS traffic are not audited."}
    engine = None
    stage = "initialization"
    started = time.perf_counter()
    with no_network() as attempts:
        try:
            stage = "deterministic_replies"
            composed = prepare_chat_translation(COMPOSED_SOURCE, "lines", mode="fast").translate(
                _NoModelExpected(), "en-zh")
            composed_ok = composed == COMPOSED_EXPECTED
            report["tests"].append({"name": "compound_replies_without_model", "source": COMPOSED_SOURCE,
                                    "translation": composed, "expected": COMPOSED_EXPECTED,
                                    "model_called": False, "passed": composed_ok})
            if not composed_ok:
                report.update(failure="compound_replies_mismatch", detail="固定短回复组合未通过；没有读屏。")
            else:
                stage = "initialization"
                if ocr_factory is None:
                    from .inference.ocr.rapidocr_engine import RapidOCREngine
                    ocr_factory = RapidOCREngine
                if translator_factory is None:
                    from .inference.translation.ctranslate2_engine import CTranslate2Engine
                    translator_factory = CTranslate2Engine
                root = model_root() if model_dir is None else Path(model_dir)
                engine = translator_factory(model_dir=root, cpu_threads=cpu_threads)
                engine.configure_chat_mode("fast")
                engine.configure_direction("en-zh")
                report["model_id"] = engine.model_id("en-zh")
                ocr = ocr_factory(model_dir=root, cpu_threads=cpu_threads)
                stage = "ocr"
                ocr_started = time.perf_counter()
                recognized = ocr.recognize((image_factory or synthetic_chat_image)())
                report["ocr_ms"] = round((time.perf_counter() - ocr_started) * 1000, 1)
                rows = recognized.text.splitlines()
                expected = FIXTURE_ROWS
                ocr_exact = len(rows) == len(expected) and all(
                    re.sub(r"\s", "", text).casefold() == re.sub(r"\s", "", actual).casefold()
                    for text, actual in zip(expected, rows))
                report["tests"].append({"name": "synthetic_two_message_ocr", "passed": ocr_exact,
                                        "expected": list(expected), "ocr": recognized.text})
                if not ocr_exact:
                    report.update(failure="synthetic_ocr_mismatch", detail="固定双行聊天 OCR 未与生成文本匹配；没有读屏。")
                else:
                    stage = "translation"
                    translation_started = time.perf_counter()
                    plan = prepare_chat_translation(recognized.text, "lines", mode="fast")
                    translated = plan.translate(engine, "en-zh")
                    report["translation_ms_cold"] = round((time.perf_counter() - translation_started) * 1000, 1)
                    outputs = translated.splitlines()
                    prefixes = ("Alice: ", "Bob: ")
                    nicknames = len(outputs) == 2 and all(text.startswith(prefix) for text, prefix in zip(outputs, prefixes))
                    bodies = [text[len(prefix):] for text, prefix in zip(outputs, prefixes)] if nicknames else []
                    # Fixed simple greetings only; not a general semantic or
                    # script evaluator for arbitrary user dialogue/proper names.
                    basic = bool(bodies) and all(body.strip() and _HAN.search(body)
                                                and not _SPECIAL.search(body) for body in bodies)
                    simplified = basic and all(to_simplified(body) == body for body in bodies)
                    report["tests"].append({"name": "fast_two_message_translation", "translation": translated,
                                            "nicknames_preserved": nicknames, "nonempty_chinese": bool(basic),
                                            "fixed_fixture_simplified": bool(simplified), "passed": bool(nicknames and simplified)})
                    if not nicknames or not simplified:
                        report.update(failure="chat_output_invalid", detail="轻量模型已返回结果，但昵称、非空中文或简体检查失败。")
        except ModelFilesError:
            report.update(failure="translation_models_missing_or_invalid" if stage != "ocr" else "ocr_models_missing_or_invalid",
                          detail="本地翻译模型缺失或校验失败，请完整解压运行包；程序不会自动下载。"
                          if stage != "ocr" else "本地 OCR 模型缺失或校验失败，请完整解压运行包。")
        except Exception as error:
            report.update(failure="chat_diagnostic_failed", failure_stage=stage,
                          error_type=type(error).__name__, detail="本地聊天自检未完成；请检查运行包中的模型和组件。")
        finally:
            if engine is not None:
                report["cleanup"]["attempted"] = True
                try:
                    engine.close()
                    report["cleanup"]["passed"] = True
                except Exception as error:
                    report.update(failure="chat_runtime_cleanup_failed", error_type=type(error).__name__,
                                  detail="本地运行组件清理未成功，自检不通过。")
            # The legacy guard stores API arguments. Do not put endpoint names
            # or exception details in this public diagnostic report.
            report["network_attempts"] = [{"endpoint": "redacted"} for _ in attempts]
            report["network_guard"] = {"blocked_attempts": list(report["network_attempts"]),
                                       "loopback_allowed": False,
                                       "scope": "Existing Python TCP connection guard only; DNS/UDP, native and OS traffic not audited."}
    report["total_ms"] = round((time.perf_counter() - started) * 1000, 1)
    report["passed"] = (not report.get("failure") and len(report["tests"]) == 3
                        and all(test["passed"] for test in report["tests"])
                        and report["cleanup"]["passed"] and not report["network_attempts"])
    return report
