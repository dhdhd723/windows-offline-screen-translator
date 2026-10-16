"""Shortcut capture safety uses a fake native API, never desktop key input."""
from __future__ import annotations

import ctypes
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from screen_translator.contracts import Settings
from screen_translator.platform.windows import hotkeys as module
from screen_translator.platform.windows.hotkeys import WindowsHotkeys, parse_hotkey


class FakeUser32:
    def __init__(self):
        self.calls = []
        self.unregistered = []
        self.down: set[int] = set()
        self.blocked: set[tuple[int, int]] = set()
        self.queued: list[int] = []
        self.peek_calls = []
        self.read_error = False
        self.read_calls = []

    def RegisterHotKey(self, hwnd, hotkey_id, modifiers, key):
        self.calls.append((hotkey_id, modifiers, key))
        return (modifiers, key) not in self.blocked

    def UnregisterHotKey(self, hwnd, hotkey_id):
        self.unregistered.append(hotkey_id)
        return True

    def GetAsyncKeyState(self, key):
        self.read_calls.append(key)
        if self.read_error:
            raise OSError("native state unavailable")
        return 0x8000 if key in self.down else 0

    def PeekMessageW(self, pointer, hwnd, first, last, flags):
        self.peek_calls.append((hwnd, first, last, flags))
        if not self.queued:
            return False
        message = ctypes.cast(pointer, ctypes.POINTER(module._MSG)).contents
        message.message = 0x0312
        message.wParam = self.queued.pop(0)
        return True


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    yield app


@pytest.fixture
def manager(qapp):
    result = WindowsHotkeys()
    result._user32 = FakeUser32()
    result.update(Settings())
    yield result
    result.close()
    qapp.processEvents()


def native_message(manager, hotkey_id, message=0x0312):
    value = module._MSG()
    value.hwnd = manager._hwnd
    value.message = message
    value.wParam = hotkey_id
    return manager._filter.nativeEventFilter(b"windows_generic_MSG", ctypes.addressof(value))


def test_recording_synchronously_unregisters_only_our_shortcuts(manager):
    effective = manager.effective_hotkeys
    manager.set_recording(True)
    assert manager._recording and manager._input_suspended
    assert manager._registered == {}
    assert manager._user32.unregistered == [0xB100, 0xB101, 0xB102]
    assert manager.effective_hotkeys == effective
    assert not manager._timer.isActive()
    assert not manager._resume_timer.isActive()
    # Idempotent start does not unregister a second time.
    manager.set_recording(True)
    assert manager._user32.unregistered == [0xB100, 0xB101, 0xB102]


@pytest.mark.parametrize("hotkey_id", [0xB100, 0xB101, 0xB102])
@pytest.mark.parametrize("pending", [False, True])
def test_queued_global_actions_are_consumed_during_capture_and_release(manager, monkeypatch,
                                                                      hotkey_id, pending):
    monkeypatch.setattr(module.sys, "platform", "win32")
    actions = []
    manager.action.connect(actions.append)
    manager.set_recording(True)
    if pending:
        manager.set_recording(False)
    assert native_message(manager, hotkey_id) == (True, 0)
    assert actions == []
    assert native_message(manager, 0xB103) == (False, 0)
    assert native_message(manager, hotkey_id, message=0x0100) == (False, 0)


def test_normal_native_hotkey_dispatch_is_preserved(manager, monkeypatch):
    monkeypatch.setattr(module.sys, "platform", "win32")
    actions = []
    manager.action.connect(actions.append)
    assert native_message(manager, 0xB101) == (True, 0)
    assert actions == ["toggle"]


def test_resume_is_deferred_until_next_tick_even_when_nothing_is_held(manager):
    initial_count = len(manager._user32.calls)
    manager.set_recording(True)
    manager.set_recording(False)
    assert manager._resume_pending and manager._resume_timer.isActive()
    assert manager._resume_timer.interval() == 35
    assert len(manager._user32.calls) == initial_count
    manager._poll_recording_release()
    assert not manager._input_suspended
    assert not manager._resume_timer.isActive()
    assert len(manager._user32.calls) == initial_count + 3
    assert manager.effective_hotkeys == Settings().hotkeys


@pytest.mark.parametrize("key", [0x10, 0x11, 0x12, 0x5B, 0x5C, 0x1B,
                                ord("R"), ord("T"), ord("C")])
def test_any_held_modifier_escape_or_binding_key_delays_resume(manager, key):
    initial_count = len(manager._user32.calls)
    manager.set_recording(True)
    manager._user32.down.add(key)
    manager.set_recording(False)
    manager._poll_recording_release()
    assert manager._resume_pending and manager._resume_timer.isActive()
    assert len(manager._user32.calls) == initial_count
    manager._user32.down.clear()
    manager._poll_recording_release()
    assert not manager._input_suspended
    assert len(manager._user32.calls) == initial_count + 3


def test_unrelated_ordinary_key_does_not_block_global_shortcut_recovery(manager):
    manager.set_recording(True)
    manager._user32.down.add(ord("Q"))
    manager.set_recording(False)
    manager._poll_recording_release()
    assert not manager._input_suspended


@pytest.mark.parametrize("during_pending", [False, True])
def test_settings_updated_while_suspended_register_only_latest_values(manager, during_pending):
    before = manager.effective_hotkeys
    initial_count = len(manager._user32.calls)
    manager.set_recording(True)
    if during_pending:
        manager.set_recording(False)
    settings = Settings(hotkeys={"select": "Ctrl+Shift+X", "toggle": "Alt+Y", "clear": "Alt+Z"})
    manager.update(settings)
    settings.hotkeys["select"] = "Alt+Q"  # Manager owns a copy, not the caller's dict.
    assert len(manager._user32.calls) == initial_count
    assert manager.effective_hotkeys == before
    assert ord("X") in manager._resume_keys
    if not during_pending:
        manager.set_recording(False)
    manager._poll_recording_release()
    assert manager.effective_hotkeys == {"select": "Ctrl+Shift+X", "toggle": "Alt+Y", "clear": "Alt+Z"}
    assert manager._user32.calls[-3:] == [
        (0xB100, *parse_hotkey("Ctrl+Shift+X")),
        (0xB101, *parse_hotkey("Alt+Y")),
        (0xB102, *parse_hotkey("Alt+Z")),
    ]


def test_new_capture_cancels_pending_resume_without_registering(manager):
    initial_count = len(manager._user32.calls)
    manager.set_recording(True)
    manager.set_recording(False)
    manager.set_recording(True)
    assert manager._recording and not manager._resume_pending
    assert not manager._resume_timer.isActive()
    manager._poll_recording_release()
    assert len(manager._user32.calls) == initial_count
    manager.set_recording(False)
    manager._poll_recording_release()
    assert len(manager._user32.calls) == initial_count + 3


def test_escape_never_hides_subtitle_during_capture_or_pending_release(manager):
    manager.set_monitoring(True)
    assert manager._timer.isActive()
    actions = []
    manager.action.connect(actions.append)
    manager.set_recording(True)
    manager._user32.down.add(0x1B)
    manager._poll_escape()
    manager.set_monitoring(True)
    assert not manager._timer.isActive()
    manager.set_recording(False)
    manager._poll_escape()
    manager._poll_recording_release()
    assert actions == []
    assert not manager._timer.isActive()
    manager._user32.down.clear()
    manager._poll_recording_release()
    assert manager._timer.isActive()
    manager._user32.down.add(0x1B)
    manager._poll_escape()
    assert actions == ["hide"]


def test_disable_monitoring_while_recording_keeps_escape_stopped_after_resume(manager):
    manager.set_monitoring(True)
    manager.set_recording(True)
    manager.set_monitoring(False)
    manager.set_recording(False)
    manager._poll_recording_release()
    assert not manager._timer.isActive()


def test_queue_is_drained_before_registration_restores(manager):
    manager.set_recording(True)
    manager._user32.queued = [0xB100, 0xB101, 0xB102]
    manager.set_recording(False)
    manager._poll_recording_release()
    assert manager._user32.queued == []
    assert manager._user32.peek_calls == [(manager._hwnd, 0x0312, 0x0312, 0x0001)] * 4
    assert not manager._input_suspended


def test_queue_drain_is_bounded_and_retries_next_tick(manager):
    manager.set_recording(True)
    manager._user32.queued = [0xB101] * 65
    errors = []
    manager.error.connect(errors.append)
    manager.set_recording(False)
    manager._poll_recording_release()
    assert len(manager._user32.queued) == 1
    assert manager._resume_pending and manager._registered == {}
    assert len(errors) == 1
    manager._poll_recording_release()
    assert not manager._input_suspended
    assert manager._user32.queued == []


def test_failed_key_state_read_never_restores_and_warns_once_before_retry(manager):
    manager.set_recording(True)
    manager._user32.read_error = True
    manager.set_recording(False)
    errors = []
    manager.error.connect(errors.append)
    manager._poll_recording_release()
    manager._poll_recording_release()
    assert manager._resume_pending and not manager._registered
    assert len(errors) == 1
    manager._user32.read_error = False
    manager._poll_recording_release()
    assert not manager._input_suspended


def test_effective_registration_signal_only_reports_completed_registrations(manager):
    seen = []
    errors = []
    manager.registrations_changed.connect(seen.append)
    manager.error.connect(errors.append)
    manager.set_recording(True)
    settings = Settings(hotkeys={"select": "Alt+X", "toggle": "Alt+T", "clear": "Alt+C"})
    manager.update(settings)
    assert seen == []
    manager._user32.blocked.add(parse_hotkey("Alt+X"))
    manager.set_recording(False)
    manager._poll_recording_release()
    assert seen == [{"toggle": "Alt+T", "clear": "Alt+C"}]
    assert len(errors) == 1 and "Alt+X" in errors[0]
    assert manager.effective_hotkeys == seen[0]


def test_default_fallback_still_works_if_binding_is_claimed_during_recording(manager):
    settings = Settings(hotkeys={**Settings().hotkeys, "select": "Alt+R"})
    manager.update(settings)
    manager.set_recording(True)
    manager._user32.blocked.add(parse_hotkey("Alt+R"))
    changed = []
    manager.binding_changed.connect(lambda action, key: changed.append((action, key)))
    manager.set_recording(False)
    manager._poll_recording_release()
    assert manager.effective_hotkeys["select"] == "Ctrl+Alt+R"
    assert changed == [("select", "Ctrl+Alt+R")]


def test_no_native_api_can_start_and_finish_recording_without_wait_timer(manager):
    manager.set_recording(True)
    manager._user32 = None
    manager.set_recording(False)
    assert not manager._input_suspended
    assert not manager._resume_timer.isActive()
    assert not manager._timer.isActive()
    assert manager.effective_hotkeys == {}


@pytest.mark.parametrize("pending", [False, True])
def test_close_is_idempotent_and_recorder_cleanup_cannot_reregister(manager, monkeypatch, pending):
    monkeypatch.setattr(module.sys, "platform", "win32")
    actions = []
    manager.action.connect(actions.append)
    manager.set_recording(True)
    if pending:
        manager.set_recording(False)
    manager.close()
    calls = list(manager._user32.calls)
    reads = list(manager._user32.read_calls)
    unregistered = list(manager._user32.unregistered)
    manager.set_recording(False)
    manager.set_recording(True)
    manager.update(Settings())
    manager.start(Settings())
    manager.set_monitoring(True)
    manager.set_selecting(True)
    manager._poll_recording_release()
    manager._poll_escape()
    manager.close()
    assert manager._user32.calls == calls
    assert manager._user32.read_calls == reads
    assert manager._user32.unregistered == unregistered
    assert not manager._timer.isActive() and not manager._resume_timer.isActive()
    assert manager.effective_hotkeys == {}
    assert native_message(manager, 0xB101) == (True, 0)
    assert actions == []
