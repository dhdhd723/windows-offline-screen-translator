"""Pure callback/state tests; no Qt, native APIs, input or model loading."""
from __future__ import annotations

import logging

import pytest

from screen_translator.core.startup_flow import StartupSettingsFlow


def test_scheduler_failure_is_logged_and_cancels_optional_handoff(caplog):
    def broken_schedule(callback):
        raise RuntimeError("diagnostic scheduler failure")

    opened = []
    flow = StartupSettingsFlow(schedule=broken_schedule,
                               open_settings=lambda: opened.append(True),
                               allow_open=lambda: True)
    flow.arm()
    flow.completed()
    flow.arm()
    flow.completed()
    assert not flow.pending and opened == []
    assert "scheduling skipped" in caplog.text


@pytest.fixture
def harness():
    callbacks = []
    calls = []

    def schedule(callback):
        calls.append("schedule")
        callbacks.append(callback)

    def allowed():
        calls.append("allow")
        return True

    def opened():
        calls.append("open")

    flow = StartupSettingsFlow(schedule=schedule, open_settings=opened, allow_open=allowed)
    return flow, callbacks, calls


def test_unarmed_completion_never_schedules_or_opens(harness):
    flow, callbacks, calls = harness
    flow.completed()
    flow.completed()
    assert not flow.pending
    assert flow.open_count == 0
    assert callbacks == calls == []


def test_arm_waits_for_completion_and_defers_opening(harness):
    flow, callbacks, calls = harness
    flow.arm()
    assert not flow.pending
    assert callbacks == calls == []
    flow.completed()
    assert flow.pending
    assert flow.open_count == 0
    assert len(callbacks) == 1
    assert calls == ["schedule"]
    callbacks[0]()
    assert calls == ["schedule", "allow", "open"]
    assert not flow.pending
    assert flow.open_count == 1


def test_unarmed_completion_does_not_prevent_later_arm(harness):
    flow, callbacks, calls = harness
    flow.completed()
    flow.arm()
    flow.completed()
    callbacks[0]()
    assert flow.open_count == 1
    assert calls == ["schedule", "allow", "open"]


def test_one_shot_survives_repeated_arm_completion_and_callback(harness):
    flow, callbacks, calls = harness
    for _ in range(3):
        flow.arm()
    flow.completed()
    for _ in range(3):
        flow.arm()
        flow.completed()
    assert len(callbacks) == 1
    for _ in range(3):
        callbacks[0]()
    flow.arm()
    flow.completed()
    assert len(callbacks) == 1
    assert flow.open_count == 1
    assert calls == ["schedule", "allow", "open"]


@pytest.mark.parametrize("when", ["before_arm", "after_arm", "after_schedule"])
def test_cancel_at_each_pre_open_boundary_is_terminal(harness, when):
    flow, callbacks, calls = harness
    if when == "before_arm":
        flow.cancel()
    flow.arm()
    if when == "after_arm":
        flow.cancel()
    flow.completed()
    if when == "after_schedule":
        assert flow.pending
        flow.cancel()
    assert not flow.pending
    for callback in callbacks:
        callback()
        callback()
    flow.cancel()
    flow.arm()
    flow.completed()
    assert flow.open_count == 0
    assert calls == (["schedule"] if when == "after_schedule" else [])


def test_cancel_after_open_never_reopens_or_erases_actual_open_count(harness):
    flow, callbacks, calls = harness
    flow.arm()
    flow.completed()
    callbacks[0]()
    flow.cancel()
    flow.cancel()
    flow.arm()
    flow.completed()
    callbacks[0]()
    assert not flow.pending
    assert flow.open_count == 1
    assert calls == ["schedule", "allow", "open"]


def test_allow_false_skips_open_and_consumes_handoff():
    callbacks, calls = [], []
    flow = StartupSettingsFlow(schedule=callbacks.append,
        allow_open=lambda: calls.append("allow") or False,
        open_settings=lambda: calls.append("open"))
    flow.arm()
    flow.completed()
    callbacks[0]()
    callbacks[0]()
    flow.arm()
    flow.completed()
    assert calls == ["allow"]
    assert flow.open_count == 0 and not flow.pending
    assert len(callbacks) == 1


@pytest.mark.parametrize("failure", ["allow", "open"])
def test_callback_error_is_contained_logged_and_not_retried(caplog, failure):
    callbacks, calls = [], []

    def allowed():
        calls.append("allow")
        if failure == "allow":
            raise RuntimeError("synthetic permission failure")
        return True

    def opened():
        calls.append("open")
        raise RuntimeError("synthetic settings failure")

    flow = StartupSettingsFlow(schedule=callbacks.append, allow_open=allowed, open_settings=opened)
    flow.arm()
    flow.completed()
    with caplog.at_level(logging.ERROR):
        callbacks[0]()
        callbacks[0]()
        flow.arm()
        flow.completed()
    assert calls == (["allow"] if failure == "allow" else ["allow", "open"])
    assert flow.open_count == 0 and not flow.pending
    assert len(callbacks) == 1
    errors = [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert len(errors) == 1
    assert errors[0].exc_info is not None
    assert "handoff skipped" in errors[0].message


def test_allow_can_cancel_even_when_returning_true():
    callbacks, calls = [], []

    def allowed():
        calls.append("allow")
        flow.cancel()
        return True

    flow = StartupSettingsFlow(schedule=callbacks.append, allow_open=allowed,
                               open_settings=lambda: calls.append("open"))
    flow.arm()
    flow.completed()
    callbacks[0]()
    callbacks[0]()
    flow.arm()
    flow.completed()
    assert calls == ["allow"]
    assert flow.open_count == 0 and not flow.pending
    assert len(callbacks) == 1


def test_open_callback_can_cancel_without_reentrant_open():
    callbacks, calls = [], []

    def opened():
        calls.append("open")
        flow.cancel()
        callbacks[0]()
        flow.arm()
        flow.completed()

    flow = StartupSettingsFlow(schedule=callbacks.append, allow_open=lambda: True,
                               open_settings=opened)
    flow.arm()
    flow.completed()
    callbacks[0]()
    callbacks[0]()
    assert calls == ["open"]
    assert flow.open_count == 1 and not flow.pending
    assert len(callbacks) == 1


@pytest.mark.parametrize("reentry", ["allow", "open"])
def test_callback_reentry_cannot_schedule_or_open_twice(reentry):
    callbacks, calls = [], []

    def reenter():
        assert not flow.pending
        callbacks[0]()
        flow.arm()
        flow.completed()

    def allowed():
        calls.append("allow")
        if reentry == "allow":
            reenter()
        return True

    def opened():
        calls.append("open")
        if reentry == "open":
            reenter()

    flow = StartupSettingsFlow(schedule=callbacks.append, allow_open=allowed, open_settings=opened)
    flow.arm()
    flow.completed()
    callbacks[0]()
    assert calls == ["allow", "open"]
    assert flow.open_count == 1 and not flow.pending
    assert len(callbacks) == 1


def test_synchronous_scheduler_is_safe_and_one_shot():
    callbacks, calls = [], []

    def schedule(callback):
        assert flow.pending
        calls.append("schedule")
        callbacks.append(callback)
        callback()
        callback()

    flow = StartupSettingsFlow(schedule=schedule,
        allow_open=lambda: calls.append("allow") or True,
        open_settings=lambda: calls.append("open"))
    flow.arm()
    flow.completed()
    flow.arm()
    flow.completed()
    assert calls == ["schedule", "allow", "open"]
    assert flow.open_count == 1 and not flow.pending
    assert len(callbacks) == 1


def test_schedule_can_cancel_before_executing_queued_callback():
    callbacks, calls = [], []

    def schedule(callback):
        callbacks.append(callback)
        flow.cancel()
        callback()

    flow = StartupSettingsFlow(schedule=schedule,
        allow_open=lambda: calls.append("allow") or True,
        open_settings=lambda: calls.append("open"))
    flow.arm()
    flow.completed()
    callbacks[0]()
    flow.arm()
    flow.completed()
    assert calls == []
    assert flow.open_count == 0 and not flow.pending
    assert len(callbacks) == 1
