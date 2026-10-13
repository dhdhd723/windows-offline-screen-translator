"""Cancellable one-shot animation-to-settings handoff, independent of Qt."""
from __future__ import annotations

from collections.abc import Callable
import logging


class StartupSettingsFlow:
    def __init__(self, *, schedule: Callable[[Callable[[], None]], None],
                 open_settings: Callable[[], None], allow_open: Callable[[], bool]) -> None:
        self._schedule = schedule
        self._open_settings = open_settings
        self._allow_open = allow_open
        self._armed = False
        self._completed = False
        self._cancelled = False
        self._pending = False
        self.open_count = 0

    @property
    def pending(self) -> bool:
        return self._pending

    def arm(self) -> None:
        if not self._cancelled and not self._completed:
            self._armed = True

    def cancel(self) -> None:
        self._cancelled = True
        self._armed = False
        self._pending = False

    def completed(self) -> None:
        if not self._armed or self._cancelled or self._completed:
            return
        self._completed = True
        self._armed = False
        self._pending = True
        try:
            self._schedule(self._handoff)
        except Exception:
            self.cancel()
            logging.exception("Startup settings scheduling skipped after an error")

    def _handoff(self) -> None:
        if not self._pending or self._cancelled:
            return
        self._pending = False
        try:
            if self._allow_open() and not self._cancelled:
                self._open_settings()
                self.open_count += 1
        except Exception:
            logging.exception("Startup settings handoff skipped after an error")
