from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable

import numpy as np

from screen_translator.capture.change_detector import changed, fingerprint
from screen_translator.capture.mss_backend import MSSCaptureBackend
from screen_translator.contracts import OCRResult, Region, Settings, TranslationResult
from screen_translator.core.text import (choose_direction, is_meaningful_change,
                                        normalize_text, semantic_signature)
from screen_translator.storage.translation_cache import make_cache_key

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Frame:
    image: np.ndarray
    generation: int
    captured_at: float


class Pipeline:
    """Two workers, one pending frame and generation-safe result delivery.

    Callbacks run on a worker thread (or the caller for clear/stop) and should
    emit a Qt signal rather than access widgets directly. Capture factories are
    called without arguments on the capture worker and return an object with
    grab(Region) -> BGR ndarray and optional close(). Native inference calls
    always run on the single inference worker.
    """

    def __init__(self, settings: Settings, ocr_engine, translator_engine, cache,
                 on_result: Callable[[TranslationResult], None],
                 on_status: Callable[[str], None], capture_factory=None) -> None:
        self._settings = Settings.from_dict(settings.to_dict())
        self._ocr = ocr_engine
        self._translator = translator_engine
        self._cache = cache
        self._on_result = on_result
        self._on_status = on_status
        self._capture_factory = capture_factory or MSSCaptureBackend
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._pending: _Frame | None = None
        self._generation = 0
        self._session = 0
        self._running = False
        self._closed = False
        self._region: Region | None = None
        self._capture_stop: threading.Event | None = None
        self._capture_threads: set[threading.Thread] = set()
        self._force_epoch = 0
        self._boxes: tuple[tuple[int, int, int, int], ...] = ()
        self._boxes_epoch = 0
        self._boxes_anchor = None
        self._last_observed = ""
        self._last_output = ""
        self._candidate_text = ""
        self._candidate_count = 0
        self._blank_count = 0
        self._suppressed_text: str | None = None
        self._suppress_next = False
        self._inflight_stage = ""
        self._prewarm_requested = False
        self._configuration_requested = True
        self._configured_threads: int | None = None
        self._retry_not_before = 0.0
        self._error_count = 0
        self._last_error_status = 0.0
        self._cache.set_persistence(self._settings.cache_enabled)
        self._inference_thread = threading.Thread(target=self._inference_loop,
                                                  name="Translator-Inference", daemon=True)
        self._inference_thread.start()

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._running

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    def prewarm(self) -> None:
        with self._condition:
            if not self._closed:
                self._prewarm_requested = True
                self._condition.notify()

    def start(self, region: Region) -> None:
        if not region.valid() or region.width * region.height > 80_000_000:
            raise ValueError("请选择至少 12×12 像素且大小合理的屏幕区域")
        self.stop()
        with self._condition:
            if self._closed:
                raise RuntimeError("Pipeline has been shut down")
            self._generation += 1
            self._session += 1
            session = self._session
            self._region = region
            self._running = True
            self._pending = None
            self._last_observed = ""
            self._candidate_text = ""
            self._candidate_count = 0
            self._blank_count = 0
            self._suppressed_text = None
            self._suppress_next = False
            self._boxes = ()
            self._boxes_anchor = None
            self._boxes_epoch += 1
            self._force_epoch += 1
            self._retry_not_before = 0.0
            stop_event = threading.Event()
            self._capture_stop = stop_event
            thread = threading.Thread(target=self._capture_loop,
                                      args=(region, session, stop_event),
                                      name=f"Translator-Capture-{session}", daemon=True)
            self._capture_threads.add(thread)
            thread.start()
        self._status("持续翻译已开启")

    def stop(self) -> None:
        with self._condition:
            was_running = self._running
            self._running = False
            self._generation += 1
            self._session += 1
            self._pending = None
            if self._capture_stop is not None:
                self._capture_stop.set()
                self._capture_stop = None
            self._condition.notify_all()
        if was_running:
            self._status("持续翻译已停止")

    def clear(self) -> None:
        with self._condition:
            self._generation += 1
            self._pending = None
            self._suppressed_text = self._last_observed or None
            # While OCR is in flight, its source is not yet known. Establish a
            # fresh baseline after the clear instead of showing its late result.
            self._suppress_next = self._inflight_stage == "ocr" or not self._last_observed
            self._candidate_text = ""
            self._candidate_count = 0
            self._blank_count = 0
            self._last_output = ""
            self._force_epoch += 1
            self._deliver_locked(TranslationResult("", "", "", self._generation))
            self._condition.notify_all()

    def update_settings(self, settings: Settings) -> None:
        new_settings = Settings.from_dict(settings.to_dict())
        with self._condition:
            old_settings = self._settings
            restart = self._running and old_settings.direction != new_settings.direction
            region = self._region
            self._settings = new_settings
            if old_settings.cpu_threads != new_settings.cpu_threads:
                self._configuration_requested = True
                self._condition.notify()
        self._cache.set_persistence(new_settings.cache_enabled)
        if restart and region is not None:
            self.start(region)

    def shutdown(self, timeout: float = 2.0) -> None:
        self.stop()
        deadline = time.monotonic() + max(0.0, timeout)
        with self._condition:
            self._closed = True
            self._prewarm_requested = False
            self._condition.notify_all()
            threads = list(self._capture_threads)
        for thread in threads + [self._inference_thread]:
            if thread is not threading.current_thread():
                thread.join(max(0.0, deadline - time.monotonic()))
        self._cache.close()

    def _current_locked(self, generation: int) -> bool:
        return self._running and not self._closed and generation == self._generation

    def _status(self, status: str) -> None:
        try:
            self._on_status(status)
        except Exception:
            _LOG.exception("Status callback failed")

    def _deliver_locked(self, result: TranslationResult) -> None:
        # Serialize publication with clear/stop. The GUI must additionally
        # check generation when a queued signal reaches its event loop.
        try:
            self._on_result(result)
        except Exception:
            _LOG.exception("Result callback failed")

    def _capture_loop(self, region: Region, session: int, stop_event: threading.Event) -> None:
        backend = None
        anchor_full = anchor_focus = previous = previous_full = None
        local_boxes_epoch = -1
        seen_force = -1
        candidate_since: float | None = None
        stable_since = time.monotonic()
        raw_stable_since = stable_since
        full_raw_stable_since = stable_since
        last_changed = stable_since
        last_submit = 0.0
        last_probe = 0.0
        try:
            backend = self._capture_factory()
            while not stop_event.is_set():
                now = time.monotonic()
                with self._lock:
                    if self._closed or not self._running or session != self._session:
                        break
                    settings = self._settings
                    boxes, boxes_epoch = self._boxes, self._boxes_epoch
                    boxes_anchor = self._boxes_anchor
                    force_epoch = self._force_epoch
                    generation = self._generation
                    retry_not_before = self._retry_not_before
                frame = np.ascontiguousarray(backend.grab(region), dtype=np.uint8)
                if frame.ndim != 3 or frame.shape[2] < 3:
                    raise ValueError("Screen capture returned an invalid BGR frame")
                if frame.shape[2] > 3:
                    frame = frame[:, :, :3].copy()
                full = fingerprint(frame)
                focus = fingerprint(frame, boxes) if boxes else full
                if boxes_epoch != local_boxes_epoch:
                    anchor_focus = boxes_anchor
                    previous = None
                    local_boxes_epoch = boxes_epoch
                    raw_stable_since = now
                frame_moved = changed(previous, focus)
                if frame_moved:
                    stable_since = now
                if previous is None or previous.digest != focus.digest:
                    raw_stable_since = now
                previous = focus
                if previous_full is None or previous_full.digest != full.digest:
                    full_raw_stable_since = now
                previous_full = full
                full_changed = changed(anchor_full, full)
                focus_changed = changed(anchor_focus, focus)
                forced = force_epoch != seen_force
                # Periodic full-region probes discover new text outside the
                # preceding detection boxes. Animated backgrounds are bounded
                # by debounce/max-wait, not mistaken for stable frames.
                digest_changed = anchor_focus is None or anchor_focus.digest != focus.digest
                raw_stable = now - raw_stable_since >= settings.debounce_ms / 1000.0
                # Exact checksums catch localized glyph edits that downsampling
                # can miss. Static screens never trigger a periodic OCR; only
                # changed pixels get a bounded verification.
                tiny_change = digest_changed and raw_stable
                outside_boxes_stable = bool(boxes and anchor_full is not None
                                            and full.digest != anchor_full.digest
                                            and now - full_raw_stable_since
                                            >= settings.debounce_ms / 1000.0)
                probe = bool(now - last_probe >= 2.0 and (
                    (boxes and (full_changed or anchor_full is None or full.digest != anchor_full.digest))
                    or digest_changed))
                candidate = forced or focus_changed or tiny_change or outside_boxes_stable or probe
                if candidate:
                    last_changed = now
                    if candidate_since is None:
                        candidate_since = now
                else:
                    candidate_since = None
                stable = now - stable_since >= settings.debounce_ms / 1000.0
                waited = candidate_since is not None and now - candidate_since >= max(
                    0.8, settings.debounce_ms / 1000.0 * 3)
                interval_ready = (now - last_submit >= settings.min_ocr_interval_ms / 1000.0
                                  and now >= retry_not_before)
                if candidate and (stable or waited) and interval_ready:
                    with self._condition:
                        if self._current_locked(generation) and session == self._session:
                            self._pending = _Frame(frame, generation, now)
                            self._condition.notify()
                            anchor_full, anchor_focus = full, focus
                            seen_force = force_epoch
                            last_submit = now
                            if probe:
                                last_probe = now
                            candidate_since = None
                fps = settings.idle_fps if now - last_changed > 5.0 else settings.capture_fps
                stop_event.wait(max(0.01, 1.0 / fps - (time.monotonic() - now)))
        except Exception as exc:
            _LOG.exception("Capture failed")
            with self._condition:
                current = session == self._session and not self._closed
                if current:
                    self._running = False
                    self._generation += 1
                    self._pending = None
            if current:
                self._status(f"屏幕捕获失败：{exc}")
        finally:
            if backend is not None and callable(getattr(backend, "close", None)):
                try:
                    backend.close()
                except Exception:
                    _LOG.exception("Capture backend cleanup failed")
            with self._lock:
                self._capture_threads.discard(threading.current_thread())

    def _inference_loop(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._closed or self._pending is not None
                                         or self._prewarm_requested or self._configuration_requested)
                if self._closed:
                    return
                configure = self._configuration_requested
                self._configuration_requested = False
                frame = self._pending
                self._pending = None
                warmup = frame is None and self._prewarm_requested
                if warmup:
                    self._prewarm_requested = False
            if configure:
                self._configure_engines()
            if warmup:
                self._warmup()
                continue
            if frame is None:
                continue
            try:
                self._process_frame(frame)
                with self._lock:
                    if self._current_locked(frame.generation):
                        self._error_count = 0
                        self._retry_not_before = 0.0
            except Exception as exc:
                _LOG.exception("Local inference failed")
                now = time.monotonic()
                with self._lock:
                    current = self._current_locked(frame.generation)
                    if current:
                        self._error_count += 1
                        self._retry_not_before = now + min(10.0, 0.75 * 2 ** min(self._error_count - 1, 4))
                        self._force_epoch += 1
                        notify = now - self._last_error_status > 5.0
                        if notify:
                            self._last_error_status = now
                if current and notify:
                    self._status(f"本地识别或翻译失败，将自动重试：{exc}")
            finally:
                with self._lock:
                    self._inflight_stage = ""

    def _warmup(self) -> None:
        self._status("正在预热本地模型…")
        try:
            for engine in (self._ocr, self._translator):
                method = getattr(engine, "warmup", None) or getattr(engine, "prewarm", None)
                if callable(method):
                    method()
            if not self._closed:
                self._status("本地模型已就绪")
        except Exception as exc:
            _LOG.exception("Model warmup failed")
            if not self._closed:
                self._status(f"模型预热失败：{exc}")

    def _configure_engines(self) -> None:
        with self._lock:
            threads = self._settings.cpu_threads
        if self._configured_threads == threads:
            return
        try:
            for engine in (self._ocr, self._translator):
                configure = getattr(engine, "configure_threads", None)
                if callable(configure):
                    configure(threads)
            self._configured_threads = threads
        except Exception as exc:
            _LOG.exception("Inference thread configuration failed")
            self._status(f"推理线程设置失败：{exc}")

    def _set_boxes_locked(self, result: OCRResult, image: np.ndarray) -> None:
        height, width = image.shape[:2]
        boxes = []
        for line in result.lines:
            if not line.box:
                continue
            xs, ys = zip(*line.box)
            box = (max(0, int(min(xs)) - 8), max(0, int(min(ys)) - 6),
                   min(width - 1, int(max(xs)) + 8), min(height - 1, int(max(ys)) + 6))
            if box[2] > box[0] and box[3] > box[1]:
                boxes.append(box)
        value = tuple(boxes)
        if value != self._boxes:
            self._boxes = value
            self._boxes_anchor = fingerprint(image, value)
            self._boxes_epoch += 1

    def _process_frame(self, frame: _Frame) -> None:
        started = time.monotonic()
        with self._lock:
            if not self._current_locked(frame.generation):
                return
            self._inflight_stage = "ocr"
        result: OCRResult = self._ocr.recognize(frame.image)
        text = normalize_text(result.text)
        with self._lock:
            if not self._current_locked(frame.generation):
                return
            self._set_boxes_locked(result, frame.image)
            if self._suppress_next:
                self._suppress_next = False
                self._suppressed_text = text
                self._last_observed = text
                return
            if not text:
                self._blank_count += 1
                if self._blank_count < 2:
                    self._force_epoch += 1
                    return
                self._last_observed = ""
                self._suppressed_text = None
                self._candidate_text = ""
                if self._last_output:
                    self._last_output = ""
                    self._deliver_locked(TranslationResult("", "", "", frame.generation))
                return
            self._blank_count = 0
            previous = self._last_observed
            if text == previous:
                return
            meaningful = is_meaningful_change(previous, text)
            if not meaningful:
                if semantic_signature(previous) == semantic_signature(text):
                    self._last_observed = text
                    return
                if text == self._candidate_text:
                    self._candidate_count += 1
                else:
                    self._candidate_text, self._candidate_count = text, 1
                if self._candidate_count < 2:
                    self._force_epoch += 1
                    return
            self._candidate_text = ""
            self._candidate_count = 0
            self._suppressed_text = None
            self._last_observed = text
            direction = choose_direction(text, self._settings.direction)
            if direction is None:
                self._last_output = ""
                self._deliver_locked(TranslationResult(text, "", "", frame.generation))
                return
            self._inflight_stage = "translation"
        try:
            cache_key = make_cache_key(self._translator.model_id(direction), direction, text)
            translation = self._cache.get(cache_key)
            cache_hit = translation is not None
            if translation is None:
                translation = self._translator.translate(text, direction)
            if not translation or not translation.strip():
                raise RuntimeError("本地模型返回空译文")
            with self._lock:
                if not self._current_locked(frame.generation):
                    return
                if not cache_hit:
                    self._cache.put(cache_key, translation)
                self._last_output = translation
                self._deliver_locked(TranslationResult(text, translation, direction, frame.generation,
                                                       (time.monotonic() - started) * 1000.0, cache_hit))
        except Exception:
            with self._lock:
                if self._current_locked(frame.generation):
                    self._last_observed = previous
            raise
