from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

from screen_translator.contracts import Settings
from screen_translator.paths import data_root


class SettingsStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else data_root() / "config.json"
        self._lock = threading.RLock()
        self.last_error: str | None = None

    def load(self) -> Settings:
        with self._lock:
            self.last_error = None
            try:
                if not self.path.exists():
                    return Settings()
                if self.path.stat().st_size > 262144:
                    raise ValueError("Settings file is too large")
                with self.path.open("r", encoding="utf-8-sig") as stream:
                    data = json.load(stream)
                if not isinstance(data, dict):
                    raise ValueError("Settings must be an object")
                settings = Settings.from_dict(data)
                if not isinstance(settings.hotkeys, dict):
                    raise ValueError("Invalid hotkey configuration")
                defaults = Settings().hotkeys
                settings.hotkeys = {key: str(settings.hotkeys.get(key, value))
                                    for key, value in defaults.items()}
                for key in ("show_source", "esc_enabled", "cache_enabled", "auto_start"):
                    if not isinstance(getattr(settings, key), bool):
                        raise ValueError(f"Invalid boolean setting: {key}")
                if (not isinstance(settings.runtime_terms_version, str)
                        or len(settings.runtime_terms_version) > 256):
                    raise ValueError("Invalid runtime terms acceptance version")
                if settings.region and not settings.region.valid():
                    settings.region = None
                if settings.region and settings.region.monitor_bounds is not None and (
                        len(settings.region.monitor_bounds) != 4
                        or settings.region.monitor_bounds[2] <= settings.region.monitor_bounds[0]
                        or settings.region.monitor_bounds[3] <= settings.region.monitor_bounds[1]):
                    settings.region = None
                if settings.overlay_position and (len(settings.overlay_position) != 2
                        or not all(isinstance(v, int) for v in settings.overlay_position)):
                    settings.overlay_position = None
                return settings
            except (OSError, ValueError, TypeError, KeyError, OverflowError) as exc:
                self.last_error = str(exc)
                # Never replace the user's damaged file during a read.
                return Settings()

    def save(self, settings: Settings) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            encoded = json.dumps(settings.to_dict(), ensure_ascii=False, indent=2)
            descriptor, temporary = tempfile.mkstemp(prefix=self.path.name + ".", suffix=".tmp",
                                                      dir=str(self.path.parent))
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                    stream.write(encoded)
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
                self.last_error = None
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
