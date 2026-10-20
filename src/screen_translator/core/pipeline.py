from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from functools import partial
from typing import Callable

import numpy as np

from screen_translator.capture.change_detector import changed, fingerprint
from screen_translator.capture.mss_backend import (InvalidCaptureRegionError,
                                                  MSSCaptureBackend,
                                                  is_transient_capture_error)
from screen_translator.contracts import OCRResult, Region, Settings, TranslationResult
from screen_translator.core.chat_translation import (chat_direction_source, chat_source_layout,
    chat_translation_fingerprint, prepare_chat_translation, _named_row)
from screen_translator.core.chat_messages import assemble_chat_messages
from screen_translator.core.text import (choose_direction, is_meaningful_layout_change,
                                        layout_semantic_signature, normalize_layout_text)
from screen_translator.inference import InferenceCancelled, PermanentInferenceError
from screen_translator.storage.translation_cache import make_cache_key

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Frame:
    image: np.ndarray
    generation: int
    captured_at: float
    recognized: OCRResult | None = None


class Pipeline:
    """Two workers, one pending frame and generation-safe result delivery.

    Callbacks run on a worker thread (or the caller for clear/stop) and should
    emit a Qt signal rather than access widgets directly. Capture factories are
    called without arguments on the capture worker and return an object with
    grab(Region) -> BGR ndarray and optional close(). Native inference calls
    always run on the single inference worker.
    """

    CAPTURE_RETRY_DELAYS = (0.15, 0.30, 0.60)
    CAPTURE_SLOW_RETRY_SECONDS = 5.0
    CAPTURE_FAILURE_LOG_INTERVAL_SECONDS = 30.0

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
        self._capture_state = "stopped"
        self._closed = False
        self._region: Region | None = None
        self._capture_stop: threading.Event | None = None
        self._capture_threads: set[threading.Thread] = set()
        self._force_epoch = 0
        self._boxes: tuple[tuple[int, int, int, int], ...] = ()
        self._boxes_epoch = 0
        self._boxes_anchor = None
        self._trusted_text = ""
        self._trusted_boxes: tuple[tuple[int, int, int, int], ...] = ()
        self._trusted_pixels = None
        self._trusted_shape: tuple[int, ...] | None = None
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
        self._permanent_error = False
        self._no_text_notified = False
        self._cache.set_persistence(self._settings.cache_enabled)
        self._inference_thread = threading.Thread(target=self._inference_loop,
                                                  name="Translator-Inference", daemon=True)
        self._inference_thread.start()

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._running

    @property
    def capture_state(self) -> str:
        """Capture health, separate from the user's continuing monitor intent."""
        with self._lock:
            return self._capture_state

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
            self._capture_state = "capturing"
            self._pending = None
            self._last_observed = ""
            self._candidate_text = ""
            self._candidate_count = 0
            self._blank_count = 0
            self._suppressed_text = None
            self._suppress_next = False
            self._boxes = ()
            self._boxes_anchor = None
            self._trusted_text = ""
            self._trusted_boxes = ()
            self._trusted_pixels = None
            self._trusted_shape = None
            self._boxes_epoch += 1
            self._force_epoch += 1
            self._retry_not_before = 0.0
            self._permanent_error = False
            self._no_text_notified = False
            stop_event = threading.Event()
            self._capture_stop = stop_event
            thread = threading.Thread(target=self._capture_loop,
                                      args=(region, session, stop_event),
                                      name=f"Translator-Capture-{session}", daemon=True)
            self._capture_threads.add(thread)
            # Publish before the new worker can report a capture failure.
            self._status("持续翻译已开启")
            thread.start()

    def stop(self) -> None:
        with self._condition:
            was_running = self._running
            self._running = False
            self._capture_state = "stopped"
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
            restart = self._running and (old_settings.direction != new_settings.direction
                                         or old_settings.text_layout != new_settings.text_layout
                                         or old_settings.chat_slang_enabled != new_settings.chat_slang_enabled
                                         or old_settings.chat_translation_mode != new_settings.chat_translation_mode
                                         or old_settings.chat_slang_overrides != new_settings.chat_slang_overrides)
            region = self._region
            if restart:
                # Invalidate in-flight OCR/translation before applying a new
                # layout policy or touching potentially slower disk-cache IO.
                self.stop()
            self._settings = new_settings
            if self._permanent_error and old_settings != new_settings:
                # A known invalid source/model must not spin on a static frame.
                # An explicit settings change is a safe user-controlled retry.
                self._permanent_error = False
                self._last_observed = ""
                self._retry_not_before = 0.0
                self._force_epoch += 1
            if (old_settings.cpu_threads != new_settings.cpu_threads
                    or old_settings.chat_translation_mode != new_settings.chat_translation_mode
                    or old_settings.direction != new_settings.direction):
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

    def _capture_status(self, session: int, stop_event: threading.Event,
                        message: str, state: str) -> bool:
        """Serialize capture state/messages with stop and replacement sessions.

        As with result delivery, callbacks must enqueue a UI signal, not block
        waiting for another thread to stop this session.
        """
        with self._condition:
            if (self._closed or not self._running or session != self._session
                    or stop_event.is_set()):
                return False
            self._capture_state = state
            self._status(message)
            return True

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
        recovery_attempts = 0
        last_failure_log = float("-inf")
        logged_failure_traceback = False
        try:
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
                try:
                    if backend is None:
                        backend = self._capture_factory()
                    captured = backend.grab(region)
                except Exception as exc:
                    if not is_transient_capture_error(exc):
                        raise
                    old_backend, backend = backend, None
                    with self._condition:
                        current = (not self._closed and self._running and session == self._session
                                   and not stop_event.is_set())
                        if current:
                            self._capture_state = "recovering"
                            # Reobserve after a mode switch, like a new capture
                            # session. Preserve clear's explicit suppression,
                            # but discard stale pending/accepted pixel evidence
                            # before potentially slow native cleanup.
                            self._generation += 1
                            self._pending = None
                            self._last_observed = self._suppressed_text or ""
                            self._candidate_text = ""
                            self._candidate_count = 0
                            self._blank_count = 0
                            self._boxes = ()
                            self._boxes_anchor = None
                            self._trusted_text = ""
                            self._trusted_boxes = ()
                            self._trusted_pixels = None
                            self._trusted_shape = None
                            self._boxes_epoch += 1
                            self._force_epoch += 1
                            self._condition.notify_all()
                    if old_backend is not None and callable(getattr(old_backend, "close", None)):
                        old_backend.close()
                    if not current:
                        break
                    recovery_attempts += 1
                    failure_time = time.monotonic()
                    if (failure_time - last_failure_log
                            >= self.CAPTURE_FAILURE_LOG_INTERVAL_SECONDS):
                        _LOG.warning("Transient screen acquisition failure (%s); "
                                     "automatic recovery attempt %d",
                                     type(exc).__name__, recovery_attempts,
                                     exc_info=not logged_failure_traceback)
                        last_failure_log = failure_time
                        logged_failure_traceback = True
                    if recovery_attempts == 1:
                        if not self._capture_status(session, stop_event,
                                                    "屏幕捕获暂时中断，正在自动重试…",
                                                    "recovering"):
                            break
                    if recovery_attempts <= len(self.CAPTURE_RETRY_DELAYS):
                        recovery_delay = self.CAPTURE_RETRY_DELAYS[recovery_attempts - 1]
                    else:
                        recovery_delay = self.CAPTURE_SLOW_RETRY_SECONDS
                        if recovery_attempts == len(self.CAPTURE_RETRY_DELAYS) + 1:
                            message = ("屏幕捕获暂时不可用，正在等待恢复"
                                       f"（每 {recovery_delay:g} 秒自动重试）；Alt+T 可停止。")
                            if not self._capture_status(session, stop_event, message,
                                                        "recovering"):
                                break
                    # Wait is cancellable: stop/shutdown never creates another
                    # backend after entering this mode-switch backoff.
                    if stop_event.wait(recovery_delay):
                        break
                    anchor_full = anchor_focus = previous = previous_full = None
                    local_boxes_epoch = -1
                    seen_force = -1
                    candidate_since = None
                    stable_since = raw_stable_since = full_raw_stable_since = time.monotonic()
                    last_changed = stable_since
                    last_submit = last_probe = 0.0
                    continue
                frame = np.ascontiguousarray(captured, dtype=np.uint8)
                if (frame.ndim != 3 or frame.shape[2] < 3
                        or frame.shape[:2] != (region.height, region.width)):
                    raise ValueError("Screen capture returned an invalid BGR frame")
                if frame.shape[2] > 3:
                    frame = frame[:, :, :3].copy()
                with self._lock:
                    if (self._closed or not self._running or session != self._session
                            or stop_event.is_set()):
                        break
                if recovery_attempts:
                    recovery_attempts = 0
                    if not self._capture_status(session, stop_event,
                                                "屏幕捕获已恢复，持续监控中",
                                                "capturing"):
                        break
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
            with self._condition:
                current = (session == self._session and not self._closed
                           and self._running and not stop_event.is_set())
                if current:
                    _LOG.exception("Capture failed")
                    self._running = False
                    self._capture_state = "stopped"
                    self._generation += 1
                    self._pending = None
                    stop_event.set()
                    if self._capture_stop is stop_event:
                        self._capture_stop = None
                    message = ("屏幕选区已失效，已停止监控；请重新框选。"
                               if isinstance(exc, InvalidCaptureRegionError) else
                               "屏幕捕获失败，已停止监控；请检查选区或显示模式后重新开启。")
                    self._status(message)
        finally:
            if backend is not None and callable(getattr(backend, "close", None)):
                try:
                    backend.close()
                except Exception:
                    _LOG.exception("Capture backend cleanup failed")
            with self._lock:
                self._capture_threads.discard(threading.current_thread())

    def _inference_loop(self) -> None:
        try:
            self._run_inference_loop()
        finally:
            close = getattr(self._translator, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    _LOG.exception("Local translation runtime cleanup failed")

    def _run_inference_loop(self) -> None:
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
            except InferenceCancelled:
                # Stop/clear or a newer OCR-confirmed source superseded this
                # task. No error, forced recapture or retry backoff is needed.
                pass
            except PermanentInferenceError as exc:
                _LOG.warning("Local inference paused: %s", exc)
                with self._lock:
                    current = self._current_locked(frame.generation)
                    if current:
                        self._permanent_error = True
                        self._retry_not_before = 0.0
                        self._error_count = 0
                if current:
                    self._status(f"本地识别或翻译暂不可用：{exc} 等待区域文字或设置变化后重试。")
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
            direction = self._settings.direction
        try:
            # Release inactive language weights only on this inference worker,
            # never concurrently with a native translation or on the UI thread.
            select = getattr(self._translator, "configure_direction", None)
            if callable(select):
                select(direction)
            select_chat = getattr(self._translator, "configure_chat_mode", None)
            if callable(select_chat):
                # Preserve unpublished research values in settings/presets,
                # but never activate a model that failed quality acceptance.
                select_chat("fast")
            if self._configured_threads == threads:
                return
            for engine in (self._ocr, self._translator):
                configure = getattr(engine, "configure_threads", None)
                if callable(configure):
                    configure(threads)
            self._configured_threads = threads
        except Exception as exc:
            _LOG.exception("Inference thread configuration failed")
            self._status(f"推理线程设置失败：{exc}")

    @staticmethod
    def _ocr_boxes(result: OCRResult, image: np.ndarray) -> tuple[tuple[int, int, int, int], ...]:
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
        return tuple(boxes)

    def _set_boxes_locked(self, result: OCRResult, image: np.ndarray) -> None:
        value = self._ocr_boxes(result, image)
        if value != self._boxes:
            self._boxes = value
            self._boxes_anchor = fingerprint(image, value)
            self._boxes_epoch += 1

    def _accept_observation_locked(self, text: str, result: OCRResult, image: np.ndarray) -> None:
        """Keep text boxes/pixel evidence only for an accepted OCR baseline.

        A stable baseline must not learn new boxes from a rejected near-match
        or a transient blank. Repeated identical text with identical text pixels
        also keeps its established geometry instead of learning detector jitter.
        Only fingerprints/crop digests are retained, not another full ROI image.
        """
        if (text and text == self._trusted_text and self._trusted_boxes
                and self._trusted_shape == image.shape and self._trusted_pixels is not None
                and fingerprint(image, self._trusted_boxes).digest == self._trusted_pixels.digest):
            return
        self._set_boxes_locked(result, image)
        self._trusted_text = text
        self._trusted_boxes = self._boxes if text else ()
        self._trusted_shape = image.shape if self._trusted_boxes else None
        self._trusted_pixels = fingerprint(image, self._trusted_boxes) if self._trusted_boxes else None

    def _normalize_observation(self, text: str) -> str:
        return normalize_layout_text(text, self._observation_layout(text))

    def _normalize_recognition(self, result: OCRResult) -> str:
        """One canonical message policy for dedup, cancellation and display."""
        enabled = ((self._settings.chat_slang_enabled
                    or self._settings.text_layout == "lines")
                   and choose_direction(chat_direction_source(result.text, self._settings.text_layout),
                                        self._settings.direction) == "en-zh")
        parser = partial(_named_row, allow_display_name=True) if (
            self._settings.text_layout == "lines") else _named_row
        text = assemble_chat_messages(result, text_layout=self._settings.text_layout,
                                      enabled=enabled, prefix_parser=parser)
        return self._normalize_observation(text)

    def _observation_layout(self, text: str) -> str:
        active = ((self._settings.chat_slang_enabled
                   or self._settings.text_layout == "lines")
                  and choose_direction(chat_direction_source(text, self._settings.text_layout),
                                       self._settings.direction) == "en-zh")
        return chat_source_layout(text, self._settings.text_layout, enabled=active)

    def _semantic_signature(self, text: str) -> tuple[tuple[str, ...], ...]:
        return layout_semantic_signature(text, self._observation_layout(text))

    def _is_meaningful_change(self, previous: str, current: str) -> bool:
        layout = ("lines" if "lines" in (self._observation_layout(previous),
                                        self._observation_layout(current)) else "continuous")
        return is_meaningful_layout_change(previous, current, layout)

    def _unchanged_pixels_noise_locked(self, reference: str, result: OCRResult,
                                       image: np.ndarray, baseline: _Frame | None = None) -> bool:
        """Reject only near/blank OCR drift contradicted by unchanged text pixels.

        Full-region probes remain enabled. New boxes outside the accepted text
        geometry, actual pixel edits, and meaningful changes take the original
        path. An in-flight frame's recognized text may provide provisional
        evidence before its observation has been committed to the baseline.
        """
        candidate = self._normalize_recognition(result)
        if (not reference or candidate == reference
                or (candidate and self._is_meaningful_change(reference, candidate))):
            return False
        if self._trusted_text == reference and self._trusted_boxes and self._trusted_pixels is not None:
            boxes, pixels, shape = self._trusted_boxes, self._trusted_pixels, self._trusted_shape
        elif (baseline is not None and baseline.recognized is not None
              and self._normalize_recognition(baseline.recognized) == reference):
            boxes = self._ocr_boxes(baseline.recognized, baseline.image)
            if not boxes:
                return False
            pixels, shape = fingerprint(baseline.image, boxes), baseline.image.shape
        else:
            return False
        if image.shape != shape:
            return False
        if candidate:
            if not result.lines:
                return False
            for line in result.lines:
                if not line.box:
                    return False
                xs, ys = zip(*line.box)
                if not any(left <= min(xs) and min(ys) >= top
                           and max(xs) <= right and max(ys) <= bottom
                           for left, top, right, bottom in boxes):
                    return False
        return fingerprint(image, boxes).digest == pixels.digest

    def _reset_text_candidate_locked(self) -> None:
        self._candidate_text = ""
        self._candidate_count = 0

    def _newer_text_pending(self, frame: _Frame, text: str) -> bool:
        """Verify one newer debounced candidate on the inference worker.

        Pixel animation alone never cancels translation. Near matches need a
        second matching OCR, just like the ordinary text noise gate. Retain the
        verified result in the one-slot mailbox so it need not be recognized
        again. Native calls themselves remain non-interruptible.
        """
        with self._lock:
            if not self._current_locked(frame.generation):
                return True
            pending = self._pending
            if (pending is None or pending.generation != frame.generation
                    or pending.captured_at <= frame.captured_at):
                return False
            self._pending = None
            preceding_stage = self._inflight_stage
            self._inflight_stage = "ocr"
        result = pending.recognized or self._ocr.recognize(pending.image)
        latest = self._normalize_recognition(result)
        with self._condition:
            if not self._current_locked(frame.generation):
                return True
            if self._unchanged_pixels_noise_locked(text, result, pending.image, frame):
                self._inflight_stage = preceding_stage
                self._reset_text_candidate_locked()
                self._blank_count = 0
                return False
        meaningful = self._is_meaningful_change(text, latest)
        different = self._semantic_signature(text) != self._semantic_signature(latest)
        if different and (not meaningful or not latest):
            # A single near-match or blank OCR can be noise. This candidate
            # has already passed capture debounce; confirm its text once more.
            confirmation = self._ocr.recognize(pending.image)
            confirmed = self._normalize_recognition(confirmation) == latest
            result = confirmation
            latest = self._normalize_recognition(confirmation)
            meaningful = confirmed
            different = self._semantic_signature(text) != self._semantic_signature(latest)
        with self._condition:
            if not self._current_locked(frame.generation):
                return True
            self._inflight_stage = preceding_stage
            if self._unchanged_pixels_noise_locked(text, result, pending.image, frame):
                self._reset_text_candidate_locked()
                self._blank_count = 0
                return False
            # Keep an unconfirmed different candidate for the normal gate too;
            # consuming it would lose a small edit after the image anchor moved.
            if meaningful or different:
                verified = _Frame(pending.image, pending.generation, pending.captured_at, result)
                if self._pending is None or self._pending.captured_at < verified.captured_at:
                    self._pending = verified
                    self._condition.notify()
            return meaningful

    def _process_frame(self, frame: _Frame) -> None:
        started = time.monotonic()
        with self._lock:
            if not self._current_locked(frame.generation):
                return
            self._inflight_stage = "ocr"
        result: OCRResult = frame.recognized or self._ocr.recognize(frame.image)
        text = self._normalize_recognition(result)
        frame = _Frame(frame.image, frame.generation, frame.captured_at, result)
        with self._lock:
            if not self._current_locked(frame.generation):
                return
            if self._unchanged_pixels_noise_locked(self._last_observed, result, frame.image):
                self._reset_text_candidate_locked()
                self._blank_count = 0
                return
            if self._suppress_next:
                self._suppress_next = False
                self._suppressed_text = text
                self._last_observed = text
                self._accept_observation_locked(text, result, frame.image)
                return
        if self._newer_text_pending(frame, text):
            return
        with self._lock:
            if not self._current_locked(frame.generation):
                return
            if not text:
                self._reset_text_candidate_locked()
                self._blank_count += 1
                if self._blank_count < 2:
                    self._force_epoch += 1
                    return
                self._last_observed = ""
                self._permanent_error = False
                self._suppressed_text = None
                self._candidate_text = ""
                self._accept_observation_locked("", result, frame.image)
                if not self._no_text_notified:
                    self._no_text_notified = True
                    self._status("当前区域未识别到文字：请只框选清晰对白；全屏游戏可尝试无边框或窗口模式。")
                if self._last_output:
                    self._last_output = ""
                    self._deliver_locked(TranslationResult("", "", "", frame.generation))
                return
            self._blank_count = 0
            self._no_text_notified = False
            previous = self._last_observed
            if text == previous:
                self._reset_text_candidate_locked()
                self._accept_observation_locked(text, result, frame.image)
                return
            meaningful = self._is_meaningful_change(previous, text)
            if not meaningful:
                if self._semantic_signature(previous) == self._semantic_signature(text):
                    self._reset_text_candidate_locked()
                    self._last_observed = text
                    self._accept_observation_locked(text, result, frame.image)
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
            self._accept_observation_locked(text, result, frame.image)
            chat_active = (self._settings.chat_slang_enabled
                           or self._settings.text_layout == "lines")
            direction_source = (chat_direction_source(text, self._settings.text_layout)
                                if chat_active else text)
            direction = choose_direction(direction_source, self._settings.direction)
            text_layout = self._settings.text_layout
            if direction is None:
                self._last_output = ""
                self._permanent_error = False
                self._deliver_locked(TranslationResult(text, "", "", frame.generation))
                return
            # Preserve source/identity independently of the model. The default
            # paragraph layout must not silently disable an enabled chat policy.
            model_text, translation_policy, chat_plan = text, "", None
            if direction == "en-zh" and chat_active:
                chat_plan = prepare_chat_translation(text, text_layout,
                                                     self._settings.chat_slang_overrides,
                                                     mode="fast",
                                                     slang_enabled=self._settings.chat_slang_enabled)
                if self._settings.chat_slang_enabled or chat_plan.uses_row_adapter:
                    model_text = chat_plan.cache_source
                    translation_policy = chat_translation_fingerprint(self._settings.chat_slang_overrides,
                        mode="fast",
                        slang_enabled=self._settings.chat_slang_enabled)
                else:
                    # Explicit lines can protect names with the glossary off,
                    # but anonymous unchanged text keeps its ordinary cache
                    # identity and the existing single model invocation.
                    chat_plan = None
            self._inflight_stage = "translation"
        try:
            cache_key = make_cache_key(self._translator.model_id(direction), direction, text,
                                      text_layout=text_layout,
                                      translation_policy=translation_policy,
                                      model_source=model_text if translation_policy else None)
            translation = self._cache.get(cache_key)
            cache_hit = translation is not None
            if translation is None:
                cancel_check = lambda: self._newer_text_pending(frame, text)
                if chat_plan is not None:
                    translation = chat_plan.translate(self._translator, direction, cancel_check)
                else:
                    cancellable = getattr(self._translator, "translate_cancellable", None)
                    if callable(cancellable):
                        translation = cancellable(model_text, direction, cancel_check)
                    else:
                        translation = self._translator.translate(model_text, direction)
            if not translation or not translation.strip():
                raise RuntimeError("本地模型返回空译文")
            if self._newer_text_pending(frame, text):
                with self._lock:
                    if self._current_locked(frame.generation):
                        self._last_observed = previous
                return
            with self._lock:
                if not self._current_locked(frame.generation):
                    return
                if not cache_hit:
                    self._cache.put(cache_key, translation)
                self._last_output = translation
                self._permanent_error = False
                self._deliver_locked(TranslationResult(text, translation, direction, frame.generation,
                                                       (time.monotonic() - started) * 1000.0, cache_hit))
                self._status("译文已更新，持续监控中")
        except PermanentInferenceError:
            # Preserve the invalid input baseline. The same stable source will
            # neither retranslate nor force another OCR just to fail again.
            raise
        except Exception:
            with self._lock:
                if self._current_locked(frame.generation):
                    self._last_observed = previous
            raise
