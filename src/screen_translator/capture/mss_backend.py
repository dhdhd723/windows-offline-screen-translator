from __future__ import annotations

import threading

import numpy as np

from screen_translator.contracts import Region
from screen_translator.platform.windows.monitors import enumerate_monitors, monitor_for_region


class InvalidCaptureRegionError(ValueError):
    """A confirmed display-layout change requires a new user-selected region."""


def _validate_capture_region(region: Region) -> None:
    if not region.valid():
        raise InvalidCaptureRegionError("屏幕选区无效，请重新框选")
    monitors = enumerate_monitors()
    # An unavailable desktop can temporarily expose no monitor information.
    # Do not mistake that for a confirmed layout change during sleep/lock.
    if not monitors:
        raise OSError("屏幕暂不可用，等待恢复")
    monitor = monitor_for_region(region, monitors)
    if (monitor is None
            or (region.monitor_id and region.monitor_id.casefold() != monitor.id.casefold())
            or (region.monitor_bounds and tuple(region.monitor_bounds) != monitor.bounds)):
        raise InvalidCaptureRegionError("显示器或屏幕选区已改变，请重新框选")


def is_transient_capture_error(exc: Exception) -> bool:
    """Limit automatic recovery to native screen-acquisition failures."""
    if isinstance(exc, OSError):
        return True
    from mss.exception import ScreenShotError
    return isinstance(exc, ScreenShotError)


class MSSCaptureBackend:
    """Own and use MSS exclusively on the capture thread."""

    def __init__(self) -> None:
        import mss
        self._owner = threading.get_ident()
        self._capture = mss.mss()
        self._closed = False

    def grab(self, region: Region) -> np.ndarray:
        if threading.get_ident() != self._owner:
            raise RuntimeError("Screen capture must remain on its owning thread")
        if self._closed:
            raise RuntimeError("Screen capture has been closed")
        # Revalidate before every native grab, including after a long recovery
        # wait. Never silently reuse coordinates on a different display.
        _validate_capture_region(region)
        shot = self._capture.grab({"left": region.x, "top": region.y,
                                   "width": region.width, "height": region.height})
        return np.asarray(shot)[:, :, :3].copy()

    def close(self) -> None:
        if threading.get_ident() != self._owner:
            raise RuntimeError("Screen capture must close on its owning thread")
        if not self._closed:
            self._closed = True
            self._capture.close()
