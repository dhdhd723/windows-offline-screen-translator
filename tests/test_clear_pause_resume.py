"""Clear-and-stop regressions use synthetic frames and offscreen Qt only.

These tests exercise our workers and event routes without screen capture,
system hotkey registration, game input, or the user's settings/data directory.
"""
from __future__ import annotations

import os
import threading
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QFormLayout, QLabel

from screen_translator import application
from screen_translator.contracts import OCRResult, Region, Settings
from screen_translator.core.pipeline import Pipeline
from screen_translator.storage.translation_cache import TranslationCache
from screen_translator.ui.main import MainUI
from screen_translator.ui.settings_window import SettingsDialog
from test_application_capture_recovery import fake_desktop


def wait_for(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        threading.Event().wait(0.01)
    assert predicate(), "Timed out waiting for a synthetic worker state"


class SyntheticScreen:
    def __init__(self):
        self._lock = threading.Lock()
        self.value = 40
        self.grabs = 0
        self.closed = 0
        self.regions = []

    def set(self, value):
        with self._lock:
            self.value = value

    def backend(self):
        screen = self

        class Backend:
            def grab(self, region):
                with screen._lock:
                    screen.grabs += 1
                    screen.regions.append(region)
                    return np.full((region.height, region.width, 3), screen.value,
                                   dtype=np.uint8)

            def close(self):
                with screen._lock:
                    screen.closed += 1

        return Backend()


class SyntheticOCR:
    def __init__(self, block=False):
        self.block = block
        self.calls = []
        self.entered = threading.Event()
        self.release = threading.Event()

    def recognize(self, image):
        self.calls.append(int(image[0, 0, 0]))
        self.entered.set()
        if self.block and len(self.calls) == 1:
            assert self.release.wait(4), "Synthetic OCR was not released"
        return OCRResult({40: "Hello world", 100: "Good morning"}[int(image[0, 0, 0])],
                         confidence=0.99)


class SyntheticTranslator:
    def __init__(self, block=False):
        self.block = block
        self.calls = []
        self.entered = threading.Event()
        self.release = threading.Event()

    def model_id(self, direction):
        return "clear-pause-test-" + direction

    def translate(self, text, direction):
        self.calls.append((text, direction))
        self.entered.set()
        if self.block and len(self.calls) == 1:
            assert self.release.wait(4), "Synthetic translation was not released"
        return "译：" + text


@pytest.fixture
def make_pipeline(tmp_path):
    instances = []

    def create(*, stage=None, persistent=False):
        screen = SyntheticScreen()
        ocr = SyntheticOCR(block=stage == "ocr")
        translator = SyntheticTranslator(block=stage == "translation")
        settings = Settings(capture_fps=12, idle_fps=6, debounce_ms=80,
                            min_ocr_interval_ms=200, cache_enabled=persistent)
        cache = TranslationCache(tmp_path / f"cache-{len(instances)}.sqlite3")
        results, statuses = [], []
        pipeline = Pipeline(settings, ocr, translator, cache, results.append,
                            statuses.append, screen.backend)
        ui = SimpleNamespace(clear_result=lambda: None)
        monitoring = []
        hotkeys = SimpleNamespace(set_monitoring=monitoring.append)
        instances.append((pipeline, ocr, translator))
        return pipeline, screen, ocr, translator, results, statuses, cache, ui, hotkeys, monitoring

    yield create
    for pipeline, ocr, translator in instances:
        ocr.release.set()
        translator.release.set()
        pipeline.shutdown(2)


@pytest.mark.parametrize("already_stopped", [True, False])
def test_clear_session_stops_before_clear_and_disables_escape_monitoring(already_stopped):
    calls = []
    pipeline = SimpleNamespace(is_running=not already_stopped)

    def stop():
        calls.append("stop")
        pipeline.is_running = False

    def clear():
        assert not pipeline.is_running, "Stop must precede result clearing"
        calls.append("pipeline-clear")

    pipeline.stop, pipeline.clear = stop, clear
    ui = SimpleNamespace(clear_result=lambda: calls.append("ui-clear"))
    hotkeys = SimpleNamespace(set_monitoring=lambda active: calls.append(("monitoring", active)))
    application.clear_translation_session(pipeline, ui, hotkeys)
    assert calls == ["stop", "pipeline-clear", "ui-clear", ("monitoring", False)]
    assert not pipeline.is_running
    application.clear_translation_session(pipeline, ui, hotkeys)
    assert calls[4:] == calls[:4], "A second clear must stay stopped and empty"


@pytest.mark.parametrize("persistent", [True, False])
def test_clear_stops_capture_and_resume_reuses_original_region_and_same_text(make_pipeline, persistent):
    pipeline, screen, ocr, translator, results, _, cache, ui, hotkeys, monitoring = make_pipeline(
        persistent=persistent)
    region = Region(-120, 20, 64, 32, "synthetic-display", (-1920, 0, 0, 1080))
    pipeline.start(region)
    wait_for(lambda: any(result.translation for result in results))
    first = results[-1]
    application.clear_translation_session(pipeline, ui, hotkeys)
    assert not pipeline.is_running and pipeline.capture_state == "stopped"
    assert monitoring == [False]
    assert results[-1].translation == "" and results[-1].generation == pipeline.generation
    assert first.generation != pipeline.generation
    assert cache.persistent is persistent, "Clearing captions is not deleting the cache"
    wait_for(lambda: screen.closed == 1)
    counts = screen.grabs, len(ocr.calls), len(translator.calls), len(results)
    screen.set(100)
    threading.Event().wait(0.25)
    assert counts == (screen.grabs, len(ocr.calls), len(translator.calls), len(results)), (
        "A changed screen must not capture, OCR, or translate during the paused session")
    screen.set(40)
    pipeline.start(region)
    wait_for(lambda: results[-1].translation and results[-1].generation == pipeline.generation)
    assert results[-1].source == first.source == "Hello world"
    assert results[-1].cache_hit and len(translator.calls) == 1
    assert len(ocr.calls) == 2
    assert set(screen.regions) == {region}


@pytest.mark.parametrize("stage", ["ocr", "translation"])
def test_clear_stops_inflight_work_and_discards_late_result_then_resumes_uncached(make_pipeline, stage):
    pipeline, screen, ocr, translator, results, _, _, ui, hotkeys, _ = make_pipeline(stage=stage)
    region = Region(0, 0, 64, 32)
    pipeline.start(region)
    blocked = ocr if stage == "ocr" else translator
    assert blocked.entered.wait(3)
    old_generation = pipeline.generation
    application.clear_translation_session(pipeline, ui, hotkeys)
    clear_generation = pipeline.generation
    assert clear_generation != old_generation
    blocked.release.set()
    wait_for(lambda: screen.closed == 1 and pipeline._inflight_stage == "")
    threading.Event().wait(0.15)
    assert len(results) == 1 and not results[0].translation
    assert results[0].generation == clear_generation
    before_ocr, before_translation = len(ocr.calls), len(translator.calls)
    pipeline.start(region)
    wait_for(lambda: results[-1].translation and results[-1].generation == pipeline.generation)
    assert results[-1].source == "Hello world" and not results[-1].cache_hit
    assert len(ocr.calls) == before_ocr + 1
    assert len(translator.calls) == before_translation + 1
    assert not any(result.translation and result.generation == old_generation for result in results)


def test_queued_result_generation_cannot_restore_caption_after_clear_or_restart(make_pipeline):
    pipeline, _, _, _, results, _, _, ui, hotkeys, _ = make_pipeline()
    region = Region(0, 0, 64, 32)
    pipeline.start(region)
    wait_for(lambda: any(result.translation for result in results))
    queued_result = results[-1]
    application.clear_translation_session(pipeline, ui, hotkeys)
    # Match the actual GUI's queued-signal generation gate in receive_result.
    assert queued_result.generation != pipeline.generation
    cleared_result = results[-1]
    assert cleared_result.generation == pipeline.generation and not cleared_result.translation
    pipeline.start(region)
    wait_for(lambda: results[-1].translation and results[-1].generation == pipeline.generation)
    assert queued_result.generation != pipeline.generation
    assert cleared_result.generation != pipeline.generation


@pytest.mark.parametrize("route", ["tray", "hotkey"])
@pytest.mark.parametrize("toggle_binding", ["Alt+T", "Ctrl+Shift+T"])
def test_actual_application_clear_route_stops_and_toggle_resumes_without_selection(
        fake_desktop, route, toggle_binding):
    from screen_translator.storage.settings import SettingsStore

    SettingsStore().load().hotkeys["toggle"] = toggle_binding
    expected_region = Region(20, 20, 64, 32, "display-a", (0, 0, 1920, 1080))

    def scenario(tick):
        starts, calls = [], []
        pipeline, ui, hotkeys = fake_desktop.pipeline, fake_desktop.ui, fake_desktop.hotkeys
        old_stop, old_start = pipeline.stop, pipeline.start

        def stop():
            calls.append("stop")
            old_stop()

        def clear():
            assert not pipeline.is_running
            calls.append("clear")

        def start(region):
            starts.append(region)
            old_start(region)

        pipeline.stop, pipeline.clear, pipeline.start = stop, clear, start
        (ui.clear_requested if route == "tray" else hotkeys.action).emit(
            *([] if route == "tray" else ["clear"]))
        assert calls == ["stop", "clear"]
        assert not pipeline.is_running and hotkeys.monitoring is False
        assert ui.clears == 1
        assert toggle_binding in ui.statuses[-1][0] and ui.statuses[-1][1] is False
        tick()
        assert pipeline.starts == 0 and not pipeline.is_running
        (ui.clear_requested if route == "tray" else hotkeys.action).emit(
            *([] if route == "tray" else ["clear"]))
        assert calls == ["stop", "clear", "stop", "clear"]
        assert not pipeline.is_running and ui.clears == 2
        (ui.toggle_requested if route == "tray" else hotkeys.action).emit(
            *([] if route == "tray" else ["toggle"]))
        assert pipeline.is_running and hotkeys.monitoring is True
        assert starts == [expected_region]
        assert pipeline.starts == 1

    fake_desktop.scenario = scenario
    assert application.main([]) == 0


def test_clear_cancels_pending_automatic_resume_after_region_selection(fake_desktop):
    def scenario(tick):
        pipeline, ui, hotkeys = fake_desktop.pipeline, fake_desktop.ui, fake_desktop.hotkeys
        assert pipeline.is_running
        # Opening a region selector normally requests resuming its prior session.
        ui.selection_started.emit()
        assert not pipeline.is_running and pipeline.starts == 0
        hotkeys.action.emit("clear")
        assert not pipeline.is_running and hotkeys.monitoring is False
        ui.selection_cancelled.emit()
        tick()
        assert not pipeline.is_running and pipeline.starts == 0
        assert hotkeys.monitoring is False
        # Only a deliberate toggle restores the saved region after this clear.
        hotkeys.action.emit("toggle")
        assert pipeline.is_running and pipeline.starts == 1

    fake_desktop.scenario = scenario
    assert application.main([]) == 0


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


def test_settings_clear_label_explains_stop_without_changing_saved_bindings(qapp):
    settings = Settings(hotkeys={"select": "Alt+L", "toggle": "Ctrl+Shift+T", "clear": "Alt+C"})
    dialog = SettingsDialog(settings)
    try:
        labels = [layout.labelForField(dialog.hotkeys["clear"])
                  for layout in dialog.findChildren(QFormLayout)]
        assert any(isinstance(label, QLabel) and "清空并停止" in label.text() for label in labels)
        assert dialog.values().hotkeys == settings.hotkeys
        assert dialog.editable_changes() == {}
    finally:
        dialog.close()


def test_tray_clear_label_and_action_explain_combined_behavior(qapp, monkeypatch):
    monkeypatch.setattr("screen_translator.ui.subtitle_overlay.apply_overlay_styles", lambda hwnd: True)
    monkeypatch.setattr("screen_translator.ui.subtitle_overlay.set_capture_exclusion",
                        lambda hwnd, enabled: True)
    ui = MainUI(Settings())
    events = []
    ui.clear_requested.connect(lambda: events.append("clear"))
    try:
        assert "清空" in ui.clear_action.text() and "停止" in ui.clear_action.text()
        assert "Alt+C" in ui.clear_action.text()
        ui.set_status("Synthetic monitoring", True)
        ui.clear_action.trigger()
        assert events == ["clear"]
        ui.set_status("Synthetic paused", False)
        assert "清空" in ui.clear_action.text() and "停止" in ui.clear_action.text()
        ui.set_effective_hotkeys({"select": "Alt+L", "toggle": "Ctrl+Shift+T", "clear": "Ctrl+Alt+C"})
        assert "Ctrl+Alt+C" in ui.clear_action.text()
    finally:
        ui.close()
        qapp.processEvents()
