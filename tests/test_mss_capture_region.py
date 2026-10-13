"""Display validation with fake monitor/native APIs; no desktop capture."""
from __future__ import annotations

import numpy as np
import pytest

from screen_translator.capture import mss_backend
from screen_translator.contracts import Region
from screen_translator.platform.windows.monitors import Monitor


@pytest.fixture
def native_capture(monkeypatch):
    class Native:
        def __init__(self):
            self.grabs = []
            self.closed = 0

        def grab(self, rect):
            self.grabs.append(rect)
            return np.full((rect["height"], rect["width"], 4), 80, dtype=np.uint8)

        def close(self):
            self.closed += 1

    native = Native()
    monkeypatch.setattr("mss.mss", lambda: native)
    return native


def display(identifier="display-a", bounds=(-1920, 0, 0, 1080)):
    return Monitor(identifier, bounds, bounds)


def selected_region():
    return Region(-1800, 80, 64, 32, "DISPLAY-A", (-1920, 0, 0, 1080))


def test_valid_negative_coordinates_and_case_insensitive_display_id(monkeypatch, native_capture):
    monkeypatch.setattr(mss_backend, "enumerate_monitors", lambda: [display()])
    backend = mss_backend.MSSCaptureBackend()
    try:
        image = backend.grab(selected_region())
        assert image.shape == (32, 64, 3)
        assert native_capture.grabs == [{"left": -1800, "top": 80, "width": 64, "height": 32}]
    finally:
        backend.close()
    assert native_capture.closed == 1


@pytest.mark.parametrize("items", [
    [display("different-display")],
    [display(bounds=(-1920, 0, 0, 1200))],
    [display(bounds=(0, 0, 1920, 1080))],
])
def test_confirmed_layout_or_identity_change_never_grabs(monkeypatch, native_capture, items):
    monkeypatch.setattr(mss_backend, "enumerate_monitors", lambda: items)
    backend = mss_backend.MSSCaptureBackend()
    try:
        with pytest.raises(mss_backend.InvalidCaptureRegionError):
            backend.grab(selected_region())
        assert native_capture.grabs == []
        assert not mss_backend.is_transient_capture_error(mss_backend.InvalidCaptureRegionError())
    finally:
        backend.close()


def test_region_is_revalidated_on_next_grab(monkeypatch, native_capture):
    items = [display()]
    monkeypatch.setattr(mss_backend, "enumerate_monitors", lambda: list(items))
    backend = mss_backend.MSSCaptureBackend()
    try:
        backend.grab(selected_region())
        items[:] = [display("replacement-at-same-coordinates")]
        with pytest.raises(mss_backend.InvalidCaptureRegionError):
            backend.grab(selected_region())
        assert len(native_capture.grabs) == 1
    finally:
        backend.close()


def test_empty_monitor_snapshot_is_temporary_and_can_recover(monkeypatch, native_capture):
    items = []
    monkeypatch.setattr(mss_backend, "enumerate_monitors", lambda: list(items))
    backend = mss_backend.MSSCaptureBackend()
    try:
        with pytest.raises(OSError) as exc:
            backend.grab(selected_region())
        assert mss_backend.is_transient_capture_error(exc.value)
        assert native_capture.grabs == []
        items[:] = [display()]
        assert backend.grab(selected_region()).shape == (32, 64, 3)
    finally:
        backend.close()


def test_monitor_api_error_stays_temporary_without_native_grab(monkeypatch, native_capture):
    def unavailable():
        raise OSError("temporary native monitor failure")

    monkeypatch.setattr(mss_backend, "enumerate_monitors", unavailable)
    backend = mss_backend.MSSCaptureBackend()
    try:
        with pytest.raises(OSError) as exc:
            backend.grab(selected_region())
        assert mss_backend.is_transient_capture_error(exc.value)
        assert native_capture.grabs == []
    finally:
        backend.close()


@pytest.mark.parametrize("region", [Region(0, 0, 0, 32), Region(0, 0, 64, 1), Region(-10, 0, 64, 32)])
def test_invalid_or_monitor_spanning_region_never_grabs(monkeypatch, native_capture, region):
    monkeypatch.setattr(mss_backend, "enumerate_monitors", lambda: [display(bounds=(0, 0, 1920, 1080))])
    backend = mss_backend.MSSCaptureBackend()
    try:
        with pytest.raises(mss_backend.InvalidCaptureRegionError):
            backend.grab(region)
        assert not native_capture.grabs
    finally:
        backend.close()
