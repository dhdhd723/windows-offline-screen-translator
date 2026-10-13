"""Offscreen selector cleanup tests; no physical input or foreground mutation."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

from screen_translator.platform.windows.monitors import Monitor
from screen_translator.ui.display_coordinates import ScreenMapping
from screen_translator.ui.region_selector import RegionSelector


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


@pytest.fixture
def selector(qapp, monkeypatch):
    from screen_translator.ui import region_selector
    screen = qapp.primaryScreen()
    mappings = [ScreenMapping(screen, Monitor("first", (0, 0, 800, 800), (0, 0, 800, 760))),
                ScreenMapping(screen, Monitor("second", (-800, 0, 0, 800), (-800, 0, 0, 760)))]
    monkeypatch.setattr(region_selector, "screen_mappings", lambda: mappings)
    monkeypatch.setattr(region_selector, "cursor_position", lambda: (50, 50))
    monkeypatch.setattr(RegionSelector, "_remember_foreground", lambda self: None)
    monkeypatch.setattr(RegionSelector, "_restore_foreground", lambda self: None)
    value = RegionSelector()
    yield value
    value.shutdown(restore_foreground=False)
    qapp.processEvents()


def test_partially_opened_selector_cleans_up_after_show_failure(selector, monkeypatch, qapp):
    from screen_translator.ui import region_selector
    factory = region_selector._SelectionWindow
    created = []
    notices, cancellations = [], []
    selector.failed.connect(notices.append)
    selector.cancelled.connect(lambda: cancellations.append(True))

    def fail_second(owner, mapping):
        if created:
            raise OSError("second monitor unavailable")
        window = factory(owner, mapping)
        created.append(window)
        return window

    monkeypatch.setattr(region_selector, "_SelectionWindow", fail_second)
    selector.show()
    assert selector._closed and selector.windows == []
    assert all(not window.isVisible() for window in created)
    assert qapp.property("regionSelecting") is False
    assert len(cancellations) == 1 and "second monitor unavailable" in notices[0]
    assert not selector._timeout.isActive()


def test_external_window_close_cleans_all_monitors_once(selector, qapp):
    cancellations = []
    selector.cancelled.connect(lambda: cancellations.append(True))
    selector.show()
    windows = list(selector.windows)
    windows[0].close()
    assert selector._closed and selector.windows == []
    assert all(not window.isVisible() for window in windows)
    assert qapp.property("regionSelecting") is False
    assert cancellations == [True]


def test_timeout_closes_all_monitor_windows_and_emits_clear_reason(selector, qapp):
    notices = []
    selector.failed.connect(notices.append)
    selector.show()
    assert selector._timeout.isActive()
    selector._timeout.timeout.emit()
    assert selector._closed and not selector.windows
    assert notices and "90 秒" in notices[0]
    assert qapp.property("regionSelecting") is False


def test_focus_move_between_own_monitor_windows_does_not_cancel(selector, monkeypatch):
    selector.show()
    monkeypatch.setattr(QApplication, "activeWindow", staticmethod(lambda: selector.windows[1]))
    selector._check_focus()
    assert not selector._closed and len(selector.windows) == 2


def test_external_focus_loss_cancels_without_stealing_foreground(selector, monkeypatch):
    restored, notices = [], []
    selector.failed.connect(notices.append)
    selector.show()
    monkeypatch.setattr(QApplication, "activeWindow", staticmethod(lambda: None))
    monkeypatch.setattr(selector, "_restore_foreground", lambda: restored.append(True))
    selector._check_focus()
    assert selector._closed and not selector.windows
    assert not restored and "其他窗口" in notices[0]


def test_normal_mouse_release_does_not_trigger_ungrab_cancellation(selector):
    selector.show()
    window = selector.windows[0]
    selector.begin((20, 20), window)
    selector._release_mouse()
    window.event(QEvent(QEvent.Type.UngrabMouse))
    assert selector._grabber is None and not selector._closed


def test_unexpected_mouse_grab_loss_cleans_all_windows(selector):
    selector.show()
    window = selector.windows[0]
    selector.begin((20, 20), window)
    window.event(QEvent(QEvent.Type.UngrabMouse))
    assert selector._closed and selector._grabber is None and not selector.windows


def test_cleanup_is_idempotent_and_stops_all_timers(selector, qapp):
    selector.show()
    selector.schedule_focus_check()
    selector.begin((20, 20), selector.windows[0])
    selector.cancel()
    selector.cancel()
    selector.shutdown()
    assert selector._grabber is None and not selector.windows
    assert not selector._timeout.isActive() and not selector._focus_check.isActive()
    assert qapp.property("regionSelecting") is False


def test_successful_selection_and_cross_monitor_retry(selector):
    selected = []
    selector.selected.connect(selected.append)
    selector.show()
    selector.begin((20, 20), selector.windows[0])
    selector.finish((-30, 50))
    assert not selector._closed and not selected and selector.start is None
    selector.begin((20, 20), selector.windows[0])
    selector.finish((120, 80))
    assert selector._closed and len(selected) == 1
    assert (selected[0].width, selected[0].height) == (100, 60)


def test_window_input_error_does_not_leave_any_overlay(selector, monkeypatch):
    selector.show()
    window = selector.windows[0]
    notices = []
    selector.failed.connect(notices.append)

    def broken(*args):
        raise RuntimeError("selection input failure")

    window._selection_input(broken)
    assert selector._closed and not selector.windows
    assert "selection input failure" in notices[0]


def test_cursor_exception_always_cleans_up_selector(selector, monkeypatch):
    from screen_translator.ui import region_selector
    selector.show()
    window = selector.windows[0]

    def unavailable():
        raise RuntimeError("cursor backend unavailable")

    monkeypatch.setattr(region_selector, "cursor_position", unavailable)
    assert window._cursor_or_cancel() is None
    assert selector._closed and not selector.windows
