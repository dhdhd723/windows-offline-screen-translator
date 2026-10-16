"""Exercise the real application's monitor timer using only fake desktop APIs."""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from screen_translator import application
from screen_translator.contracts import Region, Settings
from screen_translator.platform.windows import monitors


class Event:
    def __init__(self):
        self.handlers = []

    def connect(self, handler):
        self.handlers.append(handler)

    def emit(self, *args):
        for handler in tuple(self.handlers):
            handler(*args)


class Card:
    """Signal-order stand-in; no Qt widget, timer or desktop surface."""
    def __init__(self):
        self.finished = Event()
        self.completed = Event()
        self.closes = 0
        self.closed = False

    def finish_now(self):
        self.closes += 1
        if not self.closed:
            self.closed = True
            self.finished.emit()

    def finish_naturally(self):
        if not self.closed:
            self.closed = True
            self.finished.emit()
            self.completed.emit()


@pytest.fixture
def fake_desktop(monkeypatch):
    from PySide6 import QtCore, QtWidgets

    state = SimpleNamespace(timers=[], pipeline=None, ui=None, hotkeys=None, scenario=None,
                            queued=[], single_shots=[], environment_queries=0,
                            foreground_covers_monitor=False, environment_error=None)
    settings = Settings(region=Region(20, 20, 64, 32, "display-a", (0, 0, 1920, 1080)),
                        startup_animation=False)

    class App:
        def __init__(self, *args):
            pass

        def setQuitOnLastWindowClosed(self, *args):
            pass

        setApplicationName = setQuitOnLastWindowClosed
        setApplicationDisplayName = setQuitOnLastWindowClosed
        setOrganizationName = setQuitOnLastWindowClosed
        quit = setQuitOnLastWindowClosed

        def exec(self):
            assert len(state.timers) == 1
            assert state.timers[0].interval == 2500
            state.scenario(state.timers[0].timeout.emit)
            return 0

    class Timer:
        def __init__(self):
            self.timeout = Event()
            state.timers.append(self)

        def setInterval(self, value):
            self.interval = value

        def start(self):
            pass

        def stop(self):
            pass

        @staticmethod
        def singleShot(milliseconds, callback):
            state.single_shots.append(milliseconds)
            state.queued.append(callback)

    def run_pending():
        while state.queued:
            state.queued.pop(0)()

    state.run_pending = run_pending

    def query_startup_environment():
        state.environment_queries += 1
        if state.environment_error is not None:
            raise state.environment_error
        return SimpleNamespace(foreground_covers_monitor=state.foreground_covers_monitor,
                               animations_enabled=True)

    class UI:
        def __init__(self, saved):
            for name in ("selection_started", "selection_cancelled", "region_selected",
                         "toggle_requested", "clear_requested", "hide_requested",
                         "quit_requested", "settings_changed", "settings_opening", "hotkey_recording_changed"):
                setattr(self, name, Event())
            self.clears = 0
            self.opens = 0
            self.is_closed = False
            self.statuses = []
            self.settings_action = SimpleNamespace(triggered=Event())
            self.tray = SimpleNamespace(activated=Event())
            self.menu = SimpleNamespace(aboutToShow=Event())
            state.ui = self

        def set_status(self, message, running):
            self.statuses.append((message, running))

        def clear_result(self):
            self.clears += 1

        def select_region(self):
            raise AssertionError("This test must not create a selection window")

        def set_effective_hotkeys(self, *args):
            pass

        set_hidden = set_effective_hotkeys

        def open_settings(self):
            if not self.is_closed:
                self.settings_opening.emit()
                self.opens += 1

        def close(self):
            self.is_closed = True

    class Hotkeys:
        def __init__(self):
            self.action, self.error, self.binding_changed = Event(), Event(), Event()
            self.registrations_changed = Event()
            self.effective_hotkeys = dict(settings.hotkeys)
            self.monitoring = None
            state.hotkeys = self

        def start(self, saved):
            pass

        def set_monitoring(self, value):
            self.monitoring = value

        def set_recording(self, value):
            self.recording = value

        def set_selecting(self, value):
            self.selecting = value

        def close(self):
            pass

    class FakePipeline:
        def __init__(self, *args):
            self.is_running = True
            self.generation = 0
            self.stops = 0
            self.starts = 0
            self.clears = 0
            self.started_regions = []
            state.pipeline = self

        def stop(self):
            self.stops += 1
            self.is_running = False

        def start(self, *args):
            self.starts += 1
            self.started_regions.extend(args)
            self.is_running = True

        def shutdown(self, **kwargs):
            self.is_running = False

        def clear(self):
            self.clears += 1

    class Cache:
        def set_persistence(self, *args):
            pass

        def close(self):
            pass

    monkeypatch.setattr(QtWidgets, "QApplication", App)
    monkeypatch.setattr(QtCore, "QTimer", Timer)
    monkeypatch.setattr(application, "configure_logging", lambda: None)
    monkeypatch.setattr(application, "check_models", lambda: [])
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr("screen_translator.storage.settings.SettingsStore",
                        lambda: SimpleNamespace(load=lambda: settings))
    monkeypatch.setattr("screen_translator.runtime_terms.authorize_runtime_terms",
                        lambda *args, **kwargs: SimpleNamespace(accepted=True))
    monkeypatch.setattr("screen_translator.platform.windows.dpi.enable_dpi_awareness", lambda: None)
    monkeypatch.setattr("screen_translator.platform.windows.startup_environment.query_startup_environment",
                        query_startup_environment)
    monkeypatch.setattr(monitors, "validate_region", lambda region: True)
    monkeypatch.setattr("screen_translator.ui.fonts.register_chinese_fallback", lambda app: "test")
    monkeypatch.setattr("screen_translator.platform.windows.single_instance.SingleInstance",
                        lambda *args: SimpleNamespace(acquired=True, close=lambda: None))
    monkeypatch.setattr("screen_translator.platform.windows.hotkeys.WindowsHotkeys", Hotkeys)
    monkeypatch.setattr("screen_translator.ui.main.MainUI", UI)
    monkeypatch.setattr("screen_translator.storage.translation_cache.TranslationCache", Cache)
    monkeypatch.setattr("screen_translator.inference.ocr.rapidocr_engine.RapidOCREngine",
                        lambda **kwargs: object())
    monkeypatch.setattr("screen_translator.inference.translation.ctranslate2_engine.CTranslate2Engine",
                        lambda **kwargs: object())
    monkeypatch.setattr("screen_translator.core.pipeline.Pipeline", FakePipeline)
    return state


def test_application_clear_stops_and_toggle_resumes_saved_region(fake_desktop):
    def scenario(tick):
        ui, pipeline, hotkeys = fake_desktop.ui, fake_desktop.pipeline, fake_desktop.hotkeys
        assert pipeline.is_running
        ui.clear_requested.emit()
        assert not pipeline.is_running and pipeline.clears == 1 and ui.clears == 1
        assert hotkeys.monitoring is False
        assert "Alt+T" in ui.statuses[-1][0] and "停止" in ui.statuses[-1][0]
        # UI.select_region raises in this harness, so a passing resume also
        # proves that clear preserved the configured valid region.
        ui.toggle_requested.emit()
        assert pipeline.is_running and pipeline.starts == 1 and hotkeys.monitoring is True
        assert len(pipeline.started_regions) == 1
        assert pipeline.started_regions[0] == Region(20, 20, 64, 32, "display-a", (0, 0, 1920, 1080))
    fake_desktop.scenario = scenario
    assert application.main([]) == 0


@pytest.mark.parametrize("temporary", ["empty_snapshot", "native_api_error"])
def test_application_timer_preserves_monitoring_through_unavailable_desktop(fake_desktop, monkeypatch, temporary):
    snapshot = [monitors.Monitor("display-a", (0, 0, 1920, 1080), (0, 0, 1920, 1080))]

    def query():
        if temporary == "native_api_error" and not snapshot:
            raise OSError("temporary test monitor API failure")
        return list(snapshot)

    monkeypatch.setattr(monitors, "enumerate_monitors", query)

    def scenario(tick):
        snapshot.clear()
        for _ in range(4):
            tick()
            assert fake_desktop.pipeline.is_running
            assert fake_desktop.pipeline.stops == fake_desktop.ui.clears == 0
        snapshot.append(monitors.Monitor("display-a", (0, 0, 1920, 1080), (0, 0, 1920, 1080)))
        tick()
        assert fake_desktop.pipeline.is_running
        assert fake_desktop.pipeline.starts == fake_desktop.pipeline.stops == 0

    fake_desktop.scenario = scenario
    assert application.main([]) == 0


def test_application_timer_stops_only_after_confirmed_layout_change(fake_desktop, monkeypatch):
    snapshot = []
    monkeypatch.setattr(monitors, "enumerate_monitors", lambda: list(snapshot))

    def scenario(tick):
        tick()
        assert fake_desktop.pipeline.is_running
        snapshot.append(monitors.Monitor("replacement", (0, 0, 1920, 1080), (0, 0, 1920, 1080)))
        tick()
        assert not fake_desktop.pipeline.is_running
        assert fake_desktop.pipeline.stops == fake_desktop.ui.clears == 1
        assert fake_desktop.hotkeys.monitoring is False
        assert "重新框选" in fake_desktop.ui.statuses[-1][0]

    fake_desktop.scenario = scenario
    assert application.main([]) == 0


def test_application_timer_never_restarts_manual_stop_after_screen_returns(fake_desktop, monkeypatch):
    snapshot = []
    monkeypatch.setattr(monitors, "enumerate_monitors", lambda: list(snapshot))

    def scenario(tick):
        tick()
        assert fake_desktop.pipeline.is_running
        fake_desktop.ui.toggle_requested.emit()
        assert not fake_desktop.pipeline.is_running
        snapshot.append(monitors.Monitor("display-a", (0, 0, 1920, 1080), (0, 0, 1920, 1080)))
        tick()
        assert fake_desktop.pipeline.stops == 1
        assert fake_desktop.pipeline.starts == fake_desktop.ui.clears == 0

    fake_desktop.scenario = scenario
    assert application.main([]) == 0


@pytest.mark.parametrize("action", ["toggle", "clear", "hide", "selection", "settings", "tray", "menu", "quit"])
def test_application_interactions_immediately_dismiss_startup_card(fake_desktop, monkeypatch, action):
    card = Card()
    monkeypatch.setattr(application, "show_startup_card", lambda *args, **kwargs: card)
    fake_desktop.ui = None
    # These routes need only trivial UI setters; no rendering or desktop API.
    def scenario(tick):
        fake_desktop.ui.set_hidden = lambda *args: None
        fake_desktop.pipeline.clear = lambda: None
        events = {"toggle": fake_desktop.ui.toggle_requested,
            "clear": fake_desktop.ui.clear_requested, "hide": fake_desktop.ui.hide_requested,
            "selection": fake_desktop.ui.selection_started,
            "settings": fake_desktop.ui.settings_opening,
            "tray": fake_desktop.ui.tray.activated, "quit": fake_desktop.ui.quit_requested}
        events["menu"] = fake_desktop.ui.menu.aboutToShow
        events[action].emit()
        assert card.closes == 1
        # Repeated interaction and normal shutdown must not touch a deleted card.
        fake_desktop.ui.settings_opening.emit()
        assert card.closes == 1
    fake_desktop.scenario = scenario
    assert application.main([]) == 0
    assert card.closes == 1


def test_startup_finished_releases_card_reference(fake_desktop, monkeypatch):
    card = Card()
    monkeypatch.setattr(application, "show_startup_card", lambda *args, **kwargs: card)
    def scenario(tick):
        card.finished.emit()
        fake_desktop.ui.settings_opening.emit()
        assert card.closes == 0
        assert fake_desktop.queued == []
    fake_desktop.scenario = scenario
    assert application.main([]) == 0
    assert card.closes == 0


def test_natural_startup_completion_queues_settings_once_after_release(fake_desktop, monkeypatch):
    card = Card()
    monkeypatch.setattr(application, "show_startup_card", lambda *args, **kwargs: card)

    def scenario(tick):
        fake_desktop.pipeline.is_running = False
        assert fake_desktop.ui.opens == 0
        assert fake_desktop.queued == []
        card.finish_naturally()
        assert fake_desktop.ui.opens == 0
        assert fake_desktop.environment_queries == 0
        assert fake_desktop.single_shots == [0]
        assert len(fake_desktop.queued) == 1
        assert card.closes == 0
        # Duplicate successful signals cannot queue a second handoff.
        card.completed.emit()
        assert len(fake_desktop.queued) == 1
        fake_desktop.run_pending()
        assert fake_desktop.ui.opens == 1
        assert fake_desktop.environment_queries == 1
        assert card.closes == 0
        card.completed.emit()
        fake_desktop.run_pending()
        assert fake_desktop.ui.opens == 1
        assert fake_desktop.single_shots == [0]

    fake_desktop.scenario = scenario
    assert application.main([]) == 0
    assert card.closes == 0


def test_early_card_cancellation_never_queues_settings(fake_desktop, monkeypatch):
    card = Card()
    monkeypatch.setattr(application, "show_startup_card", lambda *args, **kwargs: card)

    def scenario(tick):
        fake_desktop.pipeline.is_running = False
        card.finish_now()
        assert fake_desktop.queued == []
        assert fake_desktop.single_shots == []
        card.finish_naturally()
        fake_desktop.run_pending()
        assert fake_desktop.ui.opens == 0
        assert fake_desktop.environment_queries == 0

    fake_desktop.scenario = scenario
    assert application.main([]) == 0
    assert card.closes == 1


@pytest.mark.parametrize("action", ["toggle", "clear", "hide", "selection", "settings", "tray", "menu", "quit"])
def test_interaction_cancels_already_queued_startup_settings(fake_desktop, monkeypatch, action):
    card = Card()
    monkeypatch.setattr(application, "show_startup_card", lambda *args, **kwargs: card)

    def scenario(tick):
        fake_desktop.pipeline.is_running = False
        card.finish_naturally()
        assert len(fake_desktop.queued) == 1
        if action == "settings":
            # This user-requested settings window must not be duplicated later.
            fake_desktop.ui.open_settings()
        else:
            events = {"toggle": fake_desktop.ui.toggle_requested,
                      "clear": fake_desktop.ui.clear_requested,
                      "hide": fake_desktop.ui.hide_requested,
                      "selection": fake_desktop.ui.selection_started,
                      "tray": fake_desktop.ui.tray.activated,
                      "menu": fake_desktop.ui.menu.aboutToShow,
                      "quit": fake_desktop.ui.quit_requested}
            if action == "tray":
                events[action].emit("trigger")
            else:
                events[action].emit()
        fake_desktop.run_pending()
        assert fake_desktop.ui.opens == (1 if action == "settings" else 0)
        assert fake_desktop.environment_queries == 0
        assert card.closes == 0
        # A later duplicate completion must not resurrect the cancelled task.
        card.completed.emit()
        fake_desktop.run_pending()
        assert fake_desktop.ui.opens == (1 if action == "settings" else 0)
        assert fake_desktop.single_shots == [0]

    fake_desktop.scenario = scenario
    assert application.main([]) == 0
    assert card.closes == 0


@pytest.mark.parametrize("boundary", ["foreground_fullscreen", "query_error", "ui_closed", "pipeline_running"])
def test_queued_settings_rechecks_current_safe_boundary(fake_desktop, monkeypatch, boundary):
    card = Card()
    monkeypatch.setattr(application, "show_startup_card", lambda *args, **kwargs: card)

    def scenario(tick):
        fake_desktop.pipeline.is_running = False
        card.finish_naturally()
        assert len(fake_desktop.queued) == 1
        assert fake_desktop.environment_queries == 0
        if boundary == "foreground_fullscreen":
            fake_desktop.foreground_covers_monitor = True
        elif boundary == "query_error":
            fake_desktop.environment_error = OSError("test foreground-query failure")
        elif boundary == "ui_closed":
            fake_desktop.ui.close()
        else:
            fake_desktop.pipeline.is_running = True
        fake_desktop.run_pending()
        assert fake_desktop.ui.opens == 0
        assert fake_desktop.environment_queries == (1 if boundary in
            {"foreground_fullscreen", "query_error"} else 0)
        assert card.closes == 0
        # Consuming an unsafe handoff does not create a delayed surprise popup.
        fake_desktop.foreground_covers_monitor = False
        fake_desktop.environment_error = None
        fake_desktop.pipeline.is_running = False
        card.completed.emit()
        fake_desktop.run_pending()
        assert fake_desktop.ui.opens == 0
        assert fake_desktop.single_shots == [0]

    fake_desktop.scenario = scenario
    assert application.main([]) == 0


def test_no_startup_card_has_no_automatic_settings_handoff(fake_desktop, monkeypatch):
    monkeypatch.setattr(application, "show_startup_card", lambda *args, **kwargs: None)

    def scenario(tick):
        fake_desktop.pipeline.is_running = False
        fake_desktop.run_pending()
        assert fake_desktop.ui.opens == 0
        assert fake_desktop.single_shots == []
        assert fake_desktop.environment_queries == 0

    fake_desktop.scenario = scenario
    assert application.main([]) == 0


def test_repeated_instance_has_no_startup_card(fake_desktop, monkeypatch):
    monkeypatch.setattr("screen_translator.platform.windows.single_instance.SingleInstance",
                        lambda *args: SimpleNamespace(acquired=False, close=lambda: None))
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.information", lambda *args: None)
    monkeypatch.setattr(application, "show_startup_card",
                        lambda *args, **kwargs: pytest.fail("Repeated instance must not play startup card"))
    assert application.main([]) == 0
    assert fake_desktop.pipeline is None
