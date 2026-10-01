"""Exercise the real offline OCR and translation models through Pipeline.

The capture is a thread-owned synthetic BGR frame provider. This deliberately
does not verify native MSS access, window exclusion, global shortcuts or the
desktop overlay. Network connections are blocked for the entire run.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np

from screen_translator.contracts import Region, Settings
from screen_translator.core.pipeline import Pipeline
from screen_translator.diagnostics import no_network, text_fixture
from screen_translator.inference.ocr.rapidocr_engine import RapidOCREngine
from screen_translator.inference.translation.ctranslate2_engine import CTranslate2Engine
from screen_translator.storage.translation_cache import TranslationCache


class FixtureScreen:
    def __init__(self, image: np.ndarray):
        self._image = image
        self._lock = threading.Lock()
        self.grabs = 0
        self.closed = 0
        self.owner_thread: int | None = None

    def switch(self, image: np.ndarray) -> None:
        with self._lock:
            self._image = image

    def backend(self):
        source = self
        owner = threading.get_ident()
        source.owner_thread = owner

        class Backend:
            def grab(self, region: Region):
                if threading.get_ident() != owner:
                    raise RuntimeError("Capture accessed outside its owning thread")
                with source._lock:
                    source.grabs += 1
                    return source._image.copy()

            def close(self):
                if threading.get_ident() != owner:
                    raise RuntimeError("Capture closed outside its owning thread")
                source.closed += 1

        return Backend()


class CountingOCR:
    def __init__(self, inner):
        self.inner = inner
        self.calls: list[dict] = []
        self._lock = threading.Lock()

    def configure_threads(self, count: int):
        self.inner.configure_threads(count)

    def recognize(self, image: np.ndarray):
        start = time.perf_counter()
        result = self.inner.recognize(image)
        with self._lock:
            self.calls.append({"at": time.monotonic(),
                               "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                               "text": result.text, "thread": threading.get_ident()})
        return result

    def count(self) -> int:
        with self._lock:
            return len(self.calls)


class CountingTranslator:
    def __init__(self, inner):
        self.inner = inner
        self.calls: list[dict] = []
        self._lock = threading.Lock()
        self._pause_next = False
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()

    def configure_threads(self, count: int):
        self.inner.configure_threads(count)

    def model_id(self, direction: str):
        return self.inner.model_id(direction)

    def arm_pause(self):
        with self._lock:
            self._pause_next = True
            self.release.clear()
            self.entered.clear()

    def release_pause(self):
        self.release.set()

    def translate(self, text: str, direction: str):
        with self._lock:
            pause = self._pause_next
            self._pause_next = False
        if pause:
            self.entered.set()
            if not self.release.wait(15):
                raise TimeoutError("Benchmark pause was not released")
        start = time.perf_counter()
        result = self.inner.translate(text, direction)
        with self._lock:
            self.calls.append({"at": time.monotonic(),
                               "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                               "direction": direction, "source": text,
                               "translation": result})
        return result

    def count(self) -> int:
        with self._lock:
            return len(self.calls)


def wait_for(predicate, label: str, timeout: float = 15.0):
    deadline = time.monotonic() + timeout
    sleeper = threading.Event()
    while time.monotonic() < deadline:
        if predicate():
            return
        sleeper.wait(0.025)
    raise TimeoutError(f"Timed out waiting for {label}")


def cpu_seconds() -> float:
    times = os.times()
    return times.user + times.system


def benchmark(stable_seconds: float = 5.0) -> dict:
    english = "The translation works offline."
    chinese = "屏幕翻译支持离线运行。"
    number_10 = "There are 10 seconds remaining."
    number_19 = "There are 19 seconds remaining."
    stopped_text = "The window is closed."
    screen = FixtureScreen(text_fixture(english))
    ocr = CountingOCR(RapidOCREngine(cpu_threads=2))
    translator = CountingTranslator(CTranslate2Engine(cpu_threads=2))
    cache = TranslationCache(max_entries=2000)
    result_lock = threading.Lock()
    results: list[dict] = []
    statuses: list[str] = []
    network_attempts: list[str] = []

    def record_result(result):
        with result_lock:
            results.append({"at": time.monotonic(), "source": result.source,
                            "translation": result.translation, "direction": result.direction,
                            "generation": result.generation, "cache_hit": result.cache_hit,
                            "elapsed_ms": round(result.elapsed_ms, 1)})

    def find_result(predicate):
        with result_lock:
            return next((item for item in reversed(results) if predicate(item)), None)

    report = {"passed": False, "capture": "synthetic BGR frames; native MSS not tested",
              "network_attempts": [], "checks": {}, "timings_ms": {}, "counts": {},
              "results": [], "statuses": []}
    settings = Settings(capture_fps=6, idle_fps=2, debounce_ms=180,
                        min_ocr_interval_ms=450, cpu_threads=2, cache_enabled=False)
    region = Region(0, 0, 1080, 130)
    pipeline = Pipeline(settings, ocr, translator, cache, record_result,
                        statuses.append, screen.backend)
    started = time.monotonic()
    try:
        with no_network() as attempts:
            network_attempts = attempts
            pipeline.start(region)
            wait_for(lambda: find_result(lambda item: "offline" in item["source"].lower()
                                         and item["direction"] == "en-zh"), "first English translation")
            first = find_result(lambda item: "offline" in item["source"].lower()
                                and item["direction"] == "en-zh")
            report["timings_ms"]["cold_first_result"] = round((first["at"] - started) * 1000, 1)
            report["checks"]["first_english_to_chinese"] = bool(first["translation"]
                and any("\u4e00" <= char <= "\u9fff" for char in first["translation"]))

            stable_ocr = ocr.count()
            stable_translations = translator.count()
            stable_grabs = screen.grabs
            cpu_start, stable_start = cpu_seconds(), time.monotonic()
            threading.Event().wait(stable_seconds)
            stable_wall = time.monotonic() - stable_start
            stable_cpu = cpu_seconds() - cpu_start
            report["timings_ms"]["stable_wall"] = round(stable_wall * 1000, 1)
            report["counts"]["stable_ocr_delta"] = ocr.count() - stable_ocr
            report["counts"]["stable_translation_delta"] = translator.count() - stable_translations
            report["counts"]["stable_capture_grabs"] = screen.grabs - stable_grabs
            report["counts"]["stable_cpu_percent_one_core"] = round(100 * stable_cpu / stable_wall, 2)
            report["checks"]["static_no_duplicate_inference"] = (
                ocr.count() == stable_ocr and translator.count() == stable_translations)

            pipeline.clear()
            translations_after_clear = translator.count()
            wait_for(lambda: ocr.count() > stable_ocr, "forced OCR after clear", 6.0)
            threading.Event().wait(0.7)
            report["checks"]["clear_suppresses_same_text"] = (
                find_result(lambda item: item["generation"] == pipeline.generation) is not None
                and find_result(lambda item: item["generation"] == pipeline.generation)["translation"] == ""
                and translator.count() == translations_after_clear)

            changed_at = time.monotonic()
            screen.switch(text_fixture(chinese))
            wait_for(lambda: find_result(lambda item: item["direction"] == "zh-en"
                                         and "离线" in item["source"]), "Chinese translation")
            zh_result = find_result(lambda item: item["direction"] == "zh-en"
                                    and "离线" in item["source"])
            report["timings_ms"]["chinese_switch_to_result"] = round(
                (zh_result["at"] - changed_at) * 1000, 1)
            report["checks"]["chinese_to_english"] = bool(zh_result["translation"]
                and any("a" <= char.lower() <= "z" for char in zh_result["translation"]))

            screen.switch(text_fixture(number_10))
            wait_for(lambda: find_result(lambda item: item["direction"] == "en-zh"
                                         and "10" in item["source"]), "numeric source 10")
            translations_at_10 = translator.count()
            changed_at = time.monotonic()
            screen.switch(text_fixture(number_19))
            wait_for(lambda: find_result(lambda item: item["direction"] == "en-zh"
                                         and "19" in item["source"]), "numeric source 19")
            numeric = find_result(lambda item: item["direction"] == "en-zh"
                                  and "19" in item["source"])
            report["timings_ms"]["numeric_change_to_result"] = round(
                (numeric["at"] - changed_at) * 1000, 1)
            report["checks"]["numeric_change_not_suppressed"] = (
                translator.count() == translations_at_10 + 1 and "19" in numeric["source"])

            translator.arm_pause()
            screen.switch(text_fixture(stopped_text))
            wait_for(lambda: translator.entered.is_set(), "translation in flight before stop")
            with result_lock:
                before_stop = len(results)
            pipeline.stop()
            translator.release_pause()
            wait_for(lambda: translator.count() >= translations_at_10 + 2,
                     "late native translation completion")
            threading.Event().wait(0.2)
            with result_lock:
                after_stop = len(results)
            report["checks"]["stop_discards_late_translation"] = before_stop == after_stop
            wait_for(lambda: screen.closed == 1, "capture backend closure")
            report["checks"]["capture_owned_by_separate_thread"] = bool(
                screen.owner_thread is not None and ocr.calls
                and screen.owner_thread != threading.get_ident()
                and screen.owner_thread != ocr.calls[0]["thread"])
            report["network_attempts"] = attempts.copy()
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["network_attempts"] = network_attempts.copy()
    finally:
        translator.release_pause()
        pipeline.shutdown(timeout=5.0)
        report["counts"]["total_ocr"] = ocr.count()
        report["counts"]["total_translation"] = translator.count()
        report["counts"]["total_capture_grabs"] = screen.grabs
        report["counts"]["capture_backends_closed"] = screen.closed
        with result_lock:
            report["results"] = results.copy()
        report["statuses"] = statuses.copy()
        report["passed"] = all(report["checks"].values()) and not report["network_attempts"] \
            and "error" not in report
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build" / "pipeline-benchmark.json")
    parser.add_argument("--stable-seconds", type=float, default=5.0)
    args = parser.parse_args()
    report = benchmark(max(1.0, args.stable_seconds))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "error": report.get("error"),
                      "checks": report["checks"], "timings_ms": report["timings_ms"],
                      "counts": report["counts"], "report": str(args.output)},
                     ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
