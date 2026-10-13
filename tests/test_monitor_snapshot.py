"""Fake WinAPI monitor snapshots; no native UI, screen capture, or user files."""
from __future__ import annotations

import pytest

from screen_translator.capture import mss_backend
from screen_translator.contracts import Region
from screen_translator.platform.windows import monitors


class NativeFunction:
    def __init__(self, implementation):
        self.implementation = implementation

    def __call__(self, *args):
        return self.implementation(*args)


class FakeUser32:
    def __init__(self, *, handles=(1, 2), failed_handles=(), enumeration_ok=True):
        self.handles = handles
        self.failed_handles = set(failed_handles)
        self.enumeration_ok = enumeration_ok
        self.info_calls = []
        self.callback_returns = []
        self.GetMonitorInfoW = NativeFunction(self.get_monitor_info)
        self.EnumDisplayMonitors = NativeFunction(self.enum_display_monitors)

    def get_monitor_info(self, handle, pointer):
        self.info_calls.append(handle)
        if handle in self.failed_handles:
            return False
        info = pointer._obj
        info.szDevice = f"DISPLAY-{handle}"
        left = -1920 if handle == 1 else 0
        for field in (info.rcMonitor, info.rcWork):
            field.left, field.top = left, 0
            field.right, field.bottom = left + 1920, 1080
        info.dwFlags = int(handle == 2)
        return True

    def enum_display_monitors(self, dc, rect, callback, data):
        assert dc is None and rect is None and data == 0
        for handle in self.handles:
            self.callback_returns.append(callback(handle, None, None, data))
        return self.enumeration_ok


def install_native(monkeypatch, **kwargs):
    native = FakeUser32(**kwargs)
    monkeypatch.setattr(monitors.sys, "platform", "win32")
    monkeypatch.setattr(monitors.ctypes, "WinDLL", lambda *args, **kw: native, raising=False)
    monkeypatch.setattr(monitors.ctypes, "get_last_error", lambda: 31, raising=False)
    # Keep callbacks ordinary Python functions; no callback enters native code.
    monkeypatch.setattr(monitors.ctypes, "WINFUNCTYPE",
                        lambda *args: lambda function: function, raising=False)
    return native


def test_complete_two_display_snapshot_retains_identity_and_geometry(monkeypatch):
    native = install_native(monkeypatch)
    snapshot = monitors.enumerate_monitors()
    assert snapshot == [
        monitors.Monitor("DISPLAY-1", (-1920, 0, 0, 1080), (-1920, 0, 0, 1080)),
        monitors.Monitor("DISPLAY-2", (0, 0, 1920, 1080), (0, 0, 1920, 1080), True),
    ]
    assert native.info_calls == [1, 2]
    assert native.callback_returns == [True, True]


@pytest.mark.parametrize("failed_handle", [1, 2])
def test_partial_snapshot_is_temporary_even_when_other_display_is_readable(monkeypatch, failed_handle):
    native = install_native(monkeypatch, failed_handles=(failed_handle,))
    with pytest.raises(OSError, match="暂不完整") as error:
        monitors.enumerate_monitors()
    assert mss_backend.is_transient_capture_error(error.value)
    assert native.info_calls == [1, 2]
    assert native.callback_returns == [True, True]
    # A transient error on either the selected or the other display must not
    # be reclassified as a confirmed invalid region by the capture backend.
    selected = Region(-1800, 80, 64, 32, "DISPLAY-1", (-1920, 0, 0, 1080))
    with pytest.raises(OSError) as capture_error:
        mss_backend._validate_capture_region(selected)
    assert not isinstance(capture_error.value, mss_backend.InvalidCaptureRegionError)
    assert mss_backend.is_transient_capture_error(capture_error.value)


def test_enumeration_failure_rejects_even_complete_records(monkeypatch):
    native = install_native(monkeypatch, enumeration_ok=False)
    with pytest.raises(OSError, match="无法读取"):
        monitors.enumerate_monitors()
    assert native.info_calls == [1, 2]
    assert native.callback_returns == [True, True]


def test_complete_empty_snapshot_remains_available_for_temporary_classification(monkeypatch):
    native = install_native(monkeypatch, handles=())
    assert monitors.enumerate_monitors() == []
    selected = Region(0, 0, 64, 32)
    with pytest.raises(OSError, match="暂不可用") as error:
        mss_backend._validate_capture_region(selected)
    assert mss_backend.is_transient_capture_error(error.value)
    assert native.info_calls == []


def test_monitor_info_failure_with_no_error_code_still_rejects_partial_snapshot(monkeypatch):
    native = install_native(monkeypatch, failed_handles=(1,))
    monkeypatch.setattr(monitors.ctypes, "get_last_error", lambda: 0)
    with pytest.raises(OSError, match="暂不完整") as error:
        monitors.enumerate_monitors()
    assert error.value.errno == 0
    assert native.callback_returns == [True, True]


@pytest.mark.parametrize("region, expected", [
    (Region(-1800, 80, 64, 32, "display-1", (-1920, 0, 0, 1080)), True),
    (Region(-1800, 80, 64, 32), True),
    (None, False),
    (Region(0, 0, 1, 1), False),
    (Region(-1800, 80, 64, 32, "different-display"), False),
    (Region(-1800, 80, 64, 32, "DISPLAY-1", (-1920, 0, 0, 1200)), False),
    (Region(-20, 80, 64, 32), False),
])
def test_availability_distinguishes_valid_from_confirmed_invalid(monkeypatch, region, expected):
    install_native(monkeypatch)
    assert monitors.region_availability(region) is expected
    assert monitors.validate_region(region) is expected


@pytest.mark.parametrize("native_arguments", [
    {"handles": ()},
    {"failed_handles": (1,)},
    {"failed_handles": (2,)},
    {"enumeration_ok": False},
])
def test_availability_is_unknown_for_temporary_snapshot_failure(monkeypatch, native_arguments):
    install_native(monkeypatch, **native_arguments)
    selected = Region(-1800, 80, 64, 32, "DISPLAY-1", (-1920, 0, 0, 1080))
    assert monitors.region_availability(selected) is None
    assert monitors.validate_region(selected) is False
