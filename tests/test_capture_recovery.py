"""Synthetic capture recovery tests: no screen, GUI, input, or user files."""
from __future__ import annotations

import logging
import threading
import time

import numpy as np
import pytest
from mss.exception import ScreenShotError

from screen_translator.capture.mss_backend import InvalidCaptureRegionError, MSSCaptureBackend
from screen_translator.contracts import OCRResult, Region, Settings
from screen_translator.core.pipeline import Pipeline
from screen_translator.storage.translation_cache import TranslationCache


def wait_for(predicate, timeout=4.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        threading.Event().wait(0.01)
    assert predicate(), "Timed out waiting for synthetic worker state"


class CaptureFactory:
    def __init__(self, *, errors=(), creation_errors=(), shape=(32, 64, 3), block_first_close=False):
        self.errors = list(errors)
        self.creation_errors = list(creation_errors)
        self.creation_attempts = 0
        self.creation_times = []
        self.shape = shape
        self.value = 40
        self.fail_next = threading.Event()
        self.block_first_close = block_first_close
        self.close_entered = threading.Event()
        self.close_release = threading.Event()
        self.created = []
        self.operations = []
        self.regions = []
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def __call__(self):
        factory = self
        owner = threading.get_ident()
        with factory.lock:
            factory.creation_attempts += 1
            factory.creation_times.append(time.monotonic())
            if factory.creation_errors:
                raise factory.creation_errors.pop(0)

        class Backend:
            closed = False

            def grab(self, region):
                assert threading.get_ident() == owner
                assert not self.closed
                with factory.lock:
                    factory.operations.append(("grab", id(self), owner))
                    factory.regions.append((id(self), region))
                    if factory.errors:
                        raise factory.errors.pop(0)
                    if factory.fail_next.is_set():
                        factory.fail_next.clear()
                        raise OSError("private /diagnostic/path")
                    return np.full(factory.shape, factory.value, dtype=np.uint8)

            def close(self):
                assert threading.get_ident() == owner
                assert not self.closed, "Backend closed more than once"
                with factory.lock:
                    self.closed = True
                    factory.active -= 1
                    factory.operations.append(("close", id(self), owner))
                if factory.block_first_close and factory.created[0][0] is self:
                    factory.close_entered.set()
                    assert factory.close_release.wait(4)

        backend = Backend()
        with factory.lock:
            factory.created.append((backend, owner))
            factory.active += 1
            factory.max_active = max(factory.max_active, factory.active)
        return backend

    def assert_released(self, *, single_owner=True):
        assert self.active == 0
        assert all(backend.closed for backend, _ in self.created)
        assert self.max_active == 1
        if single_owner:
            assert len({owner for _, owner in self.created}) == 1
        for backend, owner in self.created:
            ops = [op for op in self.operations if op[1] == id(backend)]
            assert all(op[2] == owner for op in ops)
            assert sum(op[0] == "close" for op in ops) == 1


class OCR:
    def __init__(self, block=False):
        self.calls = 0
        self.block = block
        self.entered = threading.Event()
        self.release = threading.Event()

    def recognize(self, image):
        self.calls += 1
        self.entered.set()
        value = int(image[0, 0, 0])
        if self.block and self.calls == 1:
            assert self.release.wait(4)
        return OCRResult("Hello world" if value == 40 else "Good morning", confidence=0.99)


class Translator:
    def __init__(self, block=False):
        self.calls = []
        self.block = block
        self.entered = threading.Event()
        self.release = threading.Event()

    def model_id(self, direction):
        return "synthetic-recovery-" + direction

    def translate(self, text, direction):
        self.calls.append(text)
        self.entered.set()
        if self.block and len(self.calls) == 1:
            assert self.release.wait(4)
        return "译：" + text


@pytest.fixture
def make_pipeline(monkeypatch):
    # Most regressions compress waits, never creating desktop windows or
    # spending five seconds on each deliberately injected acquisition failure.
    monkeypatch.setattr(Pipeline, "CAPTURE_RETRY_DELAYS", (0.005, 0.01, 0.02))
    monkeypatch.setattr(Pipeline, "CAPTURE_SLOW_RETRY_SECONDS", 0.04)
    instances = []

    def make(factory, *, ocr=None, translator=None, status_callback=None):
        ocr, translator = ocr or OCR(), translator or Translator()
        results, statuses = [], []

        def status(value):
            statuses.append(value)
            if status_callback:
                status_callback(value)

        pipeline = Pipeline(Settings(capture_fps=12, idle_fps=6, debounce_ms=80,
                                     min_ocr_interval_ms=200), ocr, translator,
                            TranslationCache(), results.append, status, factory)
        instances.append((pipeline, ocr, translator, factory))
        return pipeline, ocr, translator, results, statuses

    yield make
    for pipeline, ocr, translator, factory in instances:
        ocr.release.set()
        translator.release.set()
        factory.close_release.set()
        pipeline.shutdown(2)


@pytest.mark.parametrize("error", [OSError("private /path"), ScreenShotError("private /path")])
def test_single_native_capture_failure_rebuilds_on_owner_and_resumes(make_pipeline, error):
    factory = CaptureFactory(errors=[error])
    pipeline, _, translator, results, statuses = make_pipeline(factory)
    pipeline.start(Region(-64, 0, 64, 32))
    wait_for(lambda: len(results) == 1)
    assert pipeline.is_running
    assert len(factory.created) == 2
    assert translator.calls == ["Hello world"]
    assert any("已恢复" in status for status in statuses)
    assert not any("private" in status or "/path" in status for status in statuses)
    pipeline.stop()
    wait_for(lambda: factory.active == 0)
    factory.assert_released()


def test_production_capture_recovery_delays_are_bounded():
    assert Pipeline.CAPTURE_RETRY_DELAYS == (0.15, 0.30, 0.60)
    assert Pipeline.CAPTURE_SLOW_RETRY_SECONDS == 5.0
    assert Pipeline.CAPTURE_FAILURE_LOG_INTERVAL_SECONDS == 30.0


def test_persistent_native_failure_waits_then_recovers_in_same_session(make_pipeline):
    factory = CaptureFactory(errors=[ScreenShotError("private /path") for _ in range(8)])
    pipeline, ocr, translator, results, statuses = make_pipeline(factory)
    assert pipeline.capture_state == "stopped"
    with pytest.raises(AttributeError):
        pipeline.capture_state = "capturing"
    pipeline.start(Region(0, 0, 64, 32))
    session = pipeline._session
    wait_for(lambda: any("等待恢复" in status for status in statuses))
    assert pipeline.is_running and pipeline.capture_state == "recovering"
    assert ocr.calls == 0 and not translator.calls and not results
    wait_for(lambda: len(results) == 1)
    assert pipeline._session == session
    assert pipeline.is_running and pipeline.capture_state == "capturing"
    assert len(factory.created) == 9
    assert results[0].source == "Hello world"
    assert results[0].generation == pipeline.generation
    assert any("已恢复" in status for status in statuses)
    assert not any("已停止监控" in status for status in statuses)
    assert not any("private" in status for status in statuses)
    pipeline.stop()
    wait_for(lambda: not pipeline._capture_threads)
    assert pipeline.capture_state == "stopped"
    factory.assert_released()


def test_persistent_failure_limits_slow_probes_resources_and_logs(make_pipeline, monkeypatch, caplog):
    monkeypatch.setattr(Pipeline, "CAPTURE_SLOW_RETRY_SECONDS", 0.20)
    monkeypatch.setattr(Pipeline, "CAPTURE_FAILURE_LOG_INTERVAL_SECONDS", 60.0)
    caplog.set_level(logging.WARNING, logger="screen_translator.core.pipeline")
    factory = CaptureFactory(errors=[ScreenShotError("unavailable") for _ in range(1000)])
    pipeline, ocr, translator, results, statuses = make_pipeline(factory)
    pipeline.start(Region(0, 0, 64, 32))
    wait_for(lambda: any("等待恢复" in status for status in statuses))
    assert len(factory.created) == 4 and factory.active == 0
    assert len(pipeline._capture_threads) == 1
    wait_for(lambda: len(factory.created) >= 6)
    pipeline.stop()
    wait_for(lambda: not pipeline._capture_threads)
    assert all(right - left >= 0.18 for left, right in
               zip(factory.creation_times[3:], factory.creation_times[4:]))
    assert ocr.calls == 0 and not translator.calls and not results
    acquisition_logs = [record for record in caplog.records
                        if "Transient screen acquisition failure" in record.message]
    assert len(acquisition_logs) == 1 and acquisition_logs[0].exc_info
    assert sum("等待恢复" in status for status in statuses) == 1
    factory.assert_released()


@pytest.mark.parametrize("action", ["stop", "shutdown"])
def test_real_five_second_recovery_wait_is_promptly_cancellable(make_pipeline, monkeypatch, action):
    monkeypatch.setattr(Pipeline, "CAPTURE_SLOW_RETRY_SECONDS", 5.0)
    waiting = threading.Event()
    factory = CaptureFactory(errors=[ScreenShotError("unavailable") for _ in range(1000)])
    pipeline, _, _, results, statuses = make_pipeline(
        factory, status_callback=lambda value: waiting.set() if "等待恢复" in value else None)
    pipeline.start(Region(0, 0, 64, 32))
    assert waiting.wait(2)
    assert pipeline.is_running and pipeline.capture_state == "recovering"
    count = len(factory.created)
    started = time.monotonic()
    getattr(pipeline, action)()
    wait_for(lambda: not pipeline._capture_threads, timeout=0.75)
    assert time.monotonic() - started < 0.75
    assert len(factory.created) == count == 4
    assert not pipeline.is_running and pipeline.capture_state == "stopped"
    assert not results and not any("已恢复" in value for value in statuses)
    factory.assert_released()


def test_restart_after_wait_uses_new_region_and_rejects_old_session_status(make_pipeline):
    factory = CaptureFactory(errors=[ScreenShotError("unavailable") for _ in range(1000)])
    pipeline, _, _, results, statuses = make_pipeline(factory)
    old_region, new_region = Region(0, 0, 64, 32), Region(128, 64, 64, 32)
    pipeline.start(old_region)
    old_session, old_stop = pipeline._session, pipeline._capture_stop
    wait_for(lambda: any("等待恢复" in value for value in statuses))
    pipeline.stop()
    wait_for(lambda: not pipeline._capture_threads)
    with factory.lock:
        factory.errors.clear()
        factory.value = 100
    before = len(factory.regions)
    pipeline.start(new_region)
    wait_for(lambda: len(results) == 1)
    assert results[0].source == "Good morning"
    assert all(region == new_region for _, region in factory.regions[before:])
    capture_messages = [value for value in statuses if value.startswith("屏幕捕获")]
    assert not pipeline._capture_status(old_session, old_stop, "屏幕捕获已恢复", "capturing")
    assert capture_messages == [value for value in statuses if value.startswith("屏幕捕获")]
    assert pipeline.capture_state == "capturing"
    pipeline.stop()
    wait_for(lambda: not pipeline._capture_threads)
    assert not pipeline._capture_status(pipeline._session, threading.Event(),
                                        "屏幕捕获已恢复", "capturing")
    assert pipeline.capture_state == "stopped"
    factory.assert_released(single_owner=False)


def test_transient_backend_initialization_failure_can_recover(make_pipeline):
    factory = CaptureFactory(creation_errors=[OSError("temporary")])
    pipeline, _, _, results, _ = make_pipeline(factory)
    pipeline.start(Region(0, 0, 64, 32))
    wait_for(lambda: len(results) == 1)
    assert factory.creation_attempts == 2 and len(factory.created) == 1
    pipeline.stop()
    wait_for(lambda: factory.active == 0)
    factory.assert_released()


@pytest.mark.parametrize("value", [0, 255])
def test_extreme_brightness_is_not_a_capture_failure(make_pipeline, value):
    # A dark transition or white page is legitimate data, not evidence that a
    # capture API failed. No heuristic recovery or automatic backend switch.
    factory = CaptureFactory()
    factory.value = value
    pipeline, _, _, results, _ = make_pipeline(factory)
    pipeline.start(Region(0, 0, 64, 32))
    wait_for(lambda: len(results) == 1)
    assert pipeline.is_running and factory.creation_attempts == 1
    pipeline.stop()
    wait_for(lambda: factory.active == 0)
    factory.assert_released()


@pytest.mark.parametrize("shape", [(31, 64, 3), (32, 63, 3), (32, 64), (32, 64, 2), (0, 64, 3)])
def test_invalid_or_mismatched_frame_stops_without_rebuild(make_pipeline, shape):
    factory = CaptureFactory(shape=shape)
    pipeline, ocr, _, results, _ = make_pipeline(factory)
    pipeline.start(Region(0, 0, 64, 32))
    wait_for(lambda: not pipeline.is_running)
    wait_for(lambda: factory.active == 0)
    assert len(factory.created) == 1
    assert ocr.calls == 0 and not results
    assert pipeline.capture_state == "stopped"
    factory.assert_released()


@pytest.mark.parametrize("error, expected_message", [
    (RuntimeError("unexpected private /path"), "屏幕捕获失败"),
    (ValueError("invalid frame"), "屏幕捕获失败"),
    (InvalidCaptureRegionError("invalid saved region"), "屏幕选区已失效"),
])
def test_unexpected_capture_exception_is_not_retried(make_pipeline, error, expected_message):
    factory = CaptureFactory(errors=[error])
    pipeline, _, _, results, statuses = make_pipeline(factory)
    pipeline.start(Region(0, 0, 64, 32))
    wait_for(lambda: not pipeline.is_running)
    wait_for(lambda: factory.active == 0)
    assert len(factory.created) == 1 and not results
    assert pipeline.capture_state == "stopped"
    assert any(expected_message in status for status in statuses)
    assert not any("private" in status for status in statuses)
    factory.assert_released()


@pytest.mark.parametrize("action", ["stop", "shutdown"])
def test_stop_during_backoff_prevents_backend_reconstruction(make_pipeline, monkeypatch, action):
    monkeypatch.setattr(Pipeline, "CAPTURE_RETRY_DELAYS", (0.75, 0.75, 0.75))
    factory = CaptureFactory(errors=[OSError("temporary")])
    retry_entered = threading.Event()

    def status(value):
        if "自动重试" in value:
            retry_entered.set()

    pipeline, _, _, results, _ = make_pipeline(factory, status_callback=status)
    pipeline.start(Region(0, 0, 64, 32))
    assert retry_entered.wait(2)
    getattr(pipeline, action)()
    wait_for(lambda: not pipeline._capture_threads)
    assert len(factory.created) == 1 and not results
    assert pipeline.capture_state == "stopped"
    factory.assert_released()


@pytest.mark.parametrize("stage", ["ocr", "translation"])
def test_recovery_discards_inflight_old_generation_then_translates_static_source(make_pipeline, stage):
    factory = CaptureFactory()
    ocr, translator = OCR(block=stage == "ocr"), Translator(block=stage == "translation")
    pipeline, _, _, results, statuses = make_pipeline(factory, ocr=ocr, translator=translator)
    pipeline.start(Region(0, 0, 64, 32))
    assert (ocr.entered if stage == "ocr" else translator.entered).wait(2)
    old_generation = pipeline.generation
    with factory.lock:
        factory.errors.extend(ScreenShotError("long outage") for _ in range(8))
    factory.fail_next.set()
    wait_for(lambda: any("已恢复" in status for status in statuses))
    assert pipeline.generation > old_generation
    ocr.release.set()
    translator.release.set()
    wait_for(lambda: len(results) == 1)
    assert results[0].generation == pipeline.generation
    assert results[0].source == "Hello world"
    assert pipeline.is_running
    assert any("等待恢复" in status for status in statuses)
    pipeline.stop()
    wait_for(lambda: factory.active == 0)
    factory.assert_released()


@pytest.mark.parametrize("error", [OSError("old transient failure"), RuntimeError("old terminal failure")])
def test_old_session_failure_after_native_close_cannot_change_new_capture_state(make_pipeline, error):
    factory = CaptureFactory(errors=[error], block_first_close=True)
    pipeline, _, _, results, statuses = make_pipeline(factory)
    pipeline.start(Region(0, 0, 64, 32))
    assert factory.close_entered.wait(2)
    pipeline.start(Region(128, 64, 64, 32))
    wait_for(lambda: len(results) == 1)
    capture_messages = [value for value in statuses if value.startswith("屏幕捕获")]
    factory.close_release.set()
    wait_for(lambda: len(pipeline._capture_threads) == 1)
    assert pipeline.is_running and pipeline.capture_state == "capturing"
    assert capture_messages == [value for value in statuses if value.startswith("屏幕捕获")]
    assert all(result.generation == pipeline.generation for result in results)
    pipeline.stop()
    wait_for(lambda: not pipeline._capture_threads)
    factory.assert_released(single_owner=False)


@pytest.mark.parametrize("stage", ["ocr", "translation"])
def test_old_inflight_result_cannot_publish_during_native_close(make_pipeline, stage):
    factory = CaptureFactory(block_first_close=True)
    ocr, translator = OCR(block=stage == "ocr"), Translator(block=stage == "translation")
    pipeline, _, _, results, _ = make_pipeline(factory, ocr=ocr, translator=translator)
    pipeline.start(Region(0, 0, 64, 32))
    assert (ocr.entered if stage == "ocr" else translator.entered).wait(2)
    old_generation = pipeline.generation
    factory.fail_next.set()
    assert factory.close_entered.wait(2)
    assert pipeline.generation > old_generation
    ocr.release.set()
    translator.release.set()
    wait_for(lambda: not pipeline._inflight_stage)
    assert not results and len(factory.created) == 1
    factory.close_release.set()
    wait_for(lambda: len(results) == 1)
    assert results[0].generation == pipeline.generation
    pipeline.stop()
    wait_for(lambda: not pipeline._capture_threads)
    factory.assert_released()


def test_recovery_preserves_clear_suppression_for_unchanged_text(make_pipeline):
    factory = CaptureFactory()
    pipeline, _, translator, results, statuses = make_pipeline(factory)
    pipeline.start(Region(0, 0, 64, 32))
    wait_for(lambda: len(results) == 1)
    pipeline.clear()
    wait_for(lambda: len(results) == 2)
    factory.fail_next.set()
    wait_for(lambda: any("已恢复" in status for status in statuses))
    threading.Event().wait(0.4)
    assert len(results) == 2 and translator.calls == ["Hello world"]
    factory.value = 100
    wait_for(lambda: len(results) == 3)
    assert results[-1].source == "Good morning"
    pipeline.stop()
    wait_for(lambda: factory.active == 0)
    factory.assert_released()


@pytest.mark.parametrize("stage", ["ocr", "translation"])
def test_clear_during_inflight_work_stays_suppressed_after_recovery(make_pipeline, stage):
    factory = CaptureFactory()
    ocr, translator = OCR(block=stage == "ocr"), Translator(block=stage == "translation")
    pipeline, _, _, results, statuses = make_pipeline(factory, ocr=ocr, translator=translator)
    pipeline.start(Region(0, 0, 64, 32))
    assert (ocr.entered if stage == "ocr" else translator.entered).wait(2)
    pipeline.clear()
    assert len(results) == 1 and not results[0].translation
    factory.fail_next.set()
    wait_for(lambda: any("已恢复" in status for status in statuses))
    ocr.release.set()
    translator.release.set()
    wait_for(lambda: ocr.calls >= 2)
    threading.Event().wait(0.3)
    assert len(results) == 1
    factory.value = 100
    wait_for(lambda: len(results) == 2)
    assert results[-1].source == "Good morning"
    pipeline.stop()
    wait_for(lambda: factory.active == 0)
    factory.assert_released()


@pytest.mark.parametrize("clear_when", ["before_outage", "during_slow_wait"])
def test_clear_remains_suppressed_across_long_capture_outage(make_pipeline, clear_when):
    factory = CaptureFactory()
    pipeline, ocr, translator, results, statuses = make_pipeline(factory)
    pipeline.start(Region(0, 0, 64, 32))
    wait_for(lambda: len(results) == 1)
    if clear_when == "before_outage":
        pipeline.clear()
    with factory.lock:
        factory.errors.extend(ScreenShotError("temporary unavailable") for _ in range(8))
    wait_for(lambda: any("等待恢复" in value for value in statuses))
    if clear_when == "during_slow_wait":
        pipeline.clear()
    assert len(results) == 2 and not results[-1].translation
    wait_for(lambda: any("已恢复" in value for value in statuses))
    wait_for(lambda: ocr.calls >= 2)
    threading.Event().wait(0.15)
    assert len(results) == 2 and translator.calls == ["Hello world"]
    factory.value = 100
    wait_for(lambda: len(results) == 3)
    assert results[-1].source == "Good morning"
    pipeline.stop()
    wait_for(lambda: not pipeline._capture_threads)
    factory.assert_released()


def test_successful_frame_resets_reconstruction_budget(make_pipeline):
    factory = CaptureFactory(errors=[OSError("temporary") for _ in range(3)])
    pipeline, _, _, results, statuses = make_pipeline(factory)
    pipeline.start(Region(0, 0, 64, 32))
    wait_for(lambda: len(results) == 1)
    with factory.lock:
        factory.errors.extend(OSError("temporary") for _ in range(3))
    wait_for(lambda: len(factory.created) == 7)
    wait_for(lambda: sum("已恢复" in status for status in statuses) == 2)
    assert pipeline.is_running
    pipeline.stop()
    wait_for(lambda: factory.active == 0)
    factory.assert_released()


def test_mss_wrapper_close_is_idempotent_and_owner_only(monkeypatch):
    class Native:
        calls = 0

        def close(self):
            self.calls += 1

    native = Native()
    monkeypatch.setattr("mss.mss", lambda: native)
    backend = MSSCaptureBackend()
    errors = []

    def wrong_owner():
        for operation in (lambda: backend.grab(Region(0, 0, 64, 32)), backend.close):
            try:
                operation()
            except RuntimeError as exc:
                errors.append(str(exc))

    thread = threading.Thread(target=wrong_owner)
    thread.start()
    thread.join(2)
    assert len(errors) == 2 and native.calls == 0
    backend.close()
    backend.close()
    assert native.calls == 1
    with pytest.raises(RuntimeError, match="closed"):
        backend.grab(Region(0, 0, 64, 32))
