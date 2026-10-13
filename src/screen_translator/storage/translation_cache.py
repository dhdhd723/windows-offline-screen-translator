from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

from screen_translator.core.text import LAYOUT_VERSION, NORMALIZATION_VERSION
from screen_translator.paths import data_root


def make_cache_key(model_id: str, direction: str, normalized_source: str,
                   *, text_layout: str = "continuous", translation_policy: str = "",
                   model_source: str | None = None) -> str:
    # Never reuse an old flattened translation for a structured chat input.
    # Keep the mode in the key even for one row, which may later gain rows.
    payload = [NORMALIZATION_VERSION, LAYOUT_VERSION, text_layout,
               model_id, direction, normalized_source]
    # Preserve ordinary cache keys; chat expansion is an explicit extra policy.
    if translation_policy or model_source is not None:
        payload.extend([translation_policy, model_source])
    value = json.dumps(payload,
                       ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class TranslationCache:
    """An exact LRU cache with explicitly opt-in SQLite persistence.

    Disabling persistence keeps existing disk data but never reads or updates
    it. All connection access is serialized because UI settings and inference
    can use this object from different threads.
    """

    def __init__(self, path: str | Path | None = None, max_entries: int = 2000) -> None:
        self._path = Path(path) if path is not None else None
        self.max_entries = max(1, int(max_entries))
        self._memory: OrderedDict[str, str] = OrderedDict()
        self._connection: sqlite3.Connection | None = None
        self._lock = threading.RLock()
        self._closed = False
        self.last_error: str | None = None

    @property
    def persistent(self) -> bool:
        with self._lock:
            return self._connection is not None

    def set_persistence(self, enabled: bool) -> None:
        with self._lock:
            if self._closed:
                return
            if not enabled:
                self._close_connection()
                return
            if self._connection is not None:
                return
            connection: sqlite3.Connection | None = None
            try:
                path = self._path or data_root() / "cache.sqlite3"
                path.parent.mkdir(parents=True, exist_ok=True)
                connection = sqlite3.connect(str(path), timeout=0.5, check_same_thread=False)
                connection.execute("PRAGMA auto_vacuum=INCREMENTAL")
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("PRAGMA busy_timeout=500")
                connection.execute("CREATE TABLE IF NOT EXISTS translations ("
                                   "key TEXT PRIMARY KEY, translation TEXT NOT NULL, "
                                   "touched REAL NOT NULL, size INTEGER NOT NULL)")
                connection.execute("CREATE INDEX IF NOT EXISTS translations_touched "
                                   "ON translations(touched)")
                connection.commit()
                self._connection = connection
                self.last_error = None
                self._trim_disk()
            except (OSError, sqlite3.Error) as exc:
                self.last_error = str(exc)
                if connection is not None:
                    connection.close()
                self._connection = None

    def _key(self, key: Any) -> str:
        return key if isinstance(key, str) else json.dumps(key, ensure_ascii=False, separators=(",", ":"))

    def get(self, key: Any) -> str | None:
        value = self._key(key)
        with self._lock:
            if value in self._memory:
                result = self._memory.pop(value)
                self._memory[value] = result
                return result
            if self._connection is None or self._closed:
                return None
            try:
                row = self._connection.execute("SELECT translation FROM translations WHERE key=?",
                                               (value,)).fetchone()
                if row is None:
                    return None
                self._connection.execute("UPDATE translations SET touched=? WHERE key=?",
                                         (time.time(), value))
                self._connection.commit()
                self._put_memory(value, str(row[0]))
                return str(row[0])
            except sqlite3.Error as exc:
                self.last_error = str(exc)
                return None

    def put(self, key: Any, translation: str) -> None:
        value = self._key(key)
        if not isinstance(translation, str) or not translation or len(translation) > 16000:
            return
        with self._lock:
            if self._closed:
                return
            self._put_memory(value, translation)
            if self._connection is None:
                return
            try:
                self._connection.execute("INSERT OR REPLACE INTO translations VALUES (?, ?, ?, ?)",
                                         (value, translation, time.time(),
                                          len(value.encode("utf-8")) + len(translation.encode("utf-8"))))
                self._trim_disk()
            except sqlite3.Error as exc:
                self.last_error = str(exc)

    def _put_memory(self, key: str, value: str) -> None:
        self._memory.pop(key, None)
        self._memory[key] = value
        while len(self._memory) > self.max_entries:
            self._memory.popitem(last=False)

    def _trim_disk(self) -> None:
        connection = self._connection
        if connection is None:
            return
        connection.execute("DELETE FROM translations WHERE key IN (SELECT key FROM translations "
                           "ORDER BY touched DESC LIMIT -1 OFFSET ?)", (self.max_entries,))
        # Bound logical data as well as row count; screenshots and source text
        # are never written to the database.
        total = connection.execute("SELECT COALESCE(SUM(size), 0) FROM translations").fetchone()[0]
        while total > 16 * 1024 * 1024:
            connection.execute("DELETE FROM translations WHERE key IN (SELECT key FROM translations "
                               "ORDER BY touched ASC LIMIT ?)", (max(1, self.max_entries // 10),))
            total = connection.execute("SELECT COALESCE(SUM(size), 0) FROM translations").fetchone()[0]
        connection.commit()
        connection.execute("PRAGMA incremental_vacuum(16)")

    def _close_connection(self) -> None:
        if self._connection is not None:
            try:
                self._connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error:
                pass
            self._connection.close()
            self._connection = None

    def close(self) -> None:
        with self._lock:
            self._close_connection()
            self._closed = True
            self._memory.clear()
