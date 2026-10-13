"""Own-widget animation diagnostics; no desktop capture or input registration."""
from __future__ import annotations

import hashlib
import sys
import time

from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QEvent, QEventLoop, QTimer, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from screen_translator.contracts import Settings
from screen_translator.core.startup_flow import StartupSettingsFlow
from screen_translator.core.startup_policy import startup_presentation
from screen_translator.ui.settings_window import SettingsDialog
from screen_translator.ui.startup_card import PRESENTATION_MS, StartupCard


def _painting_hash(card: StartupCard, progress: float) -> str:
    card.setProperty("progress", progress)
    image = QImage(card.size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    card.render(image)
    return hashlib.sha256(image.constBits()).hexdigest()


def _lifecycle(*, animated: bool, early_close: bool = False) -> dict:
    card = StartupCard(animations_enabled=animated)
    flags = card.windowFlags()
    checks = {"non_topmost": not bool(flags & Qt.WindowType.WindowStaysOnTopHint),
              "no_focus_flag": bool(flags & Qt.WindowType.WindowDoesNotAcceptFocus),
              "input_transparent_flag": bool(flags & Qt.WindowType.WindowTransparentForInput),
              "show_without_activating": card.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating),
              "precise_expiry_timer": card._watchdog.timerType() == Qt.TimerType.PreciseTimer}
    painting = [_painting_hash(card, value) for value in (0.12, 0.45, 0.74)]
    elapsed = time.perf_counter()
    samples: list[float] = []
    loop = QEventLoop()
    sample_timer = QTimer()
    sample_timer.setInterval(50)
    sample_timer.timeout.connect(lambda: samples.append(float(card.property("progress"))))
    timeout = QTimer()
    timeout.setSingleShot(True)
    result = {"finished_count": 0, "completed_count": 0, "settings_open_count": 0,
              "destroyed": False, "timed_out": False}
    settings_dialog: SettingsDialog | None = None

    def open_settings():
        nonlocal settings_dialog
        # Only a diagnostic-owned Qt widget: no tray, native APIs or hotkeys.
        settings_dialog = SettingsDialog(Settings())
        settings_dialog.show()
        result["settings_open_count"] += 1
        result["settings_open_elapsed_ms"] = round((time.perf_counter() - elapsed) * 1000, 1)
        result["settings_visible_at_open"] = settings_dialog.isVisible()
        result["settings_opened_after_card_hidden"] = (
            result.get("visible_after_finish") is False
            and result.get("visible_after_completed") is False)
        loop.quit()

    flow = StartupSettingsFlow(schedule=lambda callback: QTimer.singleShot(0, callback),
                               open_settings=open_settings, allow_open=lambda: True)
    flow.arm()

    def finished():
        sample_timer.stop()
        result["finished_count"] += 1
        result["finished_elapsed_ms"] = round((time.perf_counter() - elapsed) * 1000, 1)
        result["visible_after_finish"] = card.isVisible()
        result["active_card_timers_after_finish"] = sum(timer.isActive() for timer in card.findChildren(QTimer))
        result["running_card_animations_after_finish"] = sum(
            item.state() == QAbstractAnimation.State.Running
            for item in card.findChildren(QAbstractAnimation))
        if early_close or result["timed_out"]:
            flow.cancel()
            loop.quit()

    def completed():
        result["completed_count"] += 1
        result["completed_elapsed_ms"] = round((time.perf_counter() - elapsed) * 1000, 1)
        result["finished_before_completed"] = result["finished_count"] == 1
        result["visible_after_completed"] = card.isVisible()

    def timed_out():
        result["timed_out"] = True
        flow.cancel()
        if not result["destroyed"]:
            card.finish_now()
        loop.quit()

    card.finished.connect(finished)
    card.completed.connect(completed)
    card.completed.connect(flow.completed)
    card.destroyed.connect(lambda *args: result.update(destroyed=True))
    timeout.timeout.connect(timed_out)
    early_timer = QTimer()
    early_timer.setSingleShot(True)
    early_timer.timeout.connect(card.close)
    card.start()
    sample_timer.start()
    timeout.start(4500)
    if early_close:
        early_timer.start(30)
    loop.exec()
    result["elapsed_ms"] = round((time.perf_counter() - elapsed) * 1000, 1)
    for timer in (sample_timer, timeout, early_timer):
        timer.stop()
    flow.cancel()
    if settings_dialog is not None:
        settings_dialog.close()
        settings_dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    result.update(checks, animated=animated, early_close=early_close,
                  frame_hashes=painting, painted_frames_differ=len(set(painting)) == 3,
                  progress_samples=samples)
    timing = (result["elapsed_ms"] < 1000 if early_close
              else 1900 <= result["elapsed_ms"] <= 3000)
    completion = (result["completed_count"] == 0 if early_close
                  else result["completed_count"] == 1
                  and result.get("finished_before_completed") is True
                  and result.get("visible_after_completed") is False
                  and 1900 <= result.get("completed_elapsed_ms", 0) <= 3000)
    motion = not animated or early_close or (samples and max(samples) - min(samples) > 0.5)
    handoff = (result["settings_open_count"] == 0 if early_close
               else result["settings_open_count"] == 1
               and result.get("settings_visible_at_open") is True
               and result.get("settings_opened_after_card_hidden") is True
               and result.get("settings_open_elapsed_ms", 0) >= result.get("completed_elapsed_ms", 0))
    result["passed"] = bool(all(checks.values()) and timing and completion and motion and handoff
        and result["finished_count"] == 1 and result["destroyed"] and not result["timed_out"]
        and result.get("visible_after_finish") is False
        and result.get("active_card_timers_after_finish") == 0
        and result.get("running_card_animations_after_finish") == 0
        and (result["painted_frames_differ"] if animated else len(set(painting)) == 1))
    return result


def run_startup_self_test() -> dict:
    from screen_translator.diagnostics import no_network
    with no_network() as attempts:
        cases = [_lifecycle(animated=True), _lifecycle(animated=False),
                 _lifecycle(animated=True, early_close=True)]
        # Decisions are tested independently of actual screen contents.
        skips = {key: not startup_presentation(**{**dict(enabled=True), **value}).show
                 for key, value in {
                     "diagnostic": dict(diagnostic=True), "background": dict(background=True),
                     "disabled": dict(enabled=False), "one_launch": dict(suppress_once=True),
                     "covering_foreground": dict(foreground_covers_monitor=True)}.items()}
    models_loaded = any(name in sys.modules for name in ("ctranslate2", "onnxruntime", "rapidocr"))
    return {"passed": all(item["passed"] for item in cases) and all(skips.values())
            and not attempts and not models_loaded,
            "cases": cases, "skip_policy": skips, "network_attempts": attempts,
            "presentation_ms": PRESENTATION_MS,
            "inference_runtime_loaded": models_loaded,
            "qt_platform": QApplication.platformName(), "desktop_captured": False,
            "global_hotkeys_registered": False, "native_focus_tested": False,
            "game_tested": False, "nvidia_tested": False,
            "boundary": "Own startup widget lifecycle/flags and queued settings-widget handoff only; offscreen runs do not prove native foreground focus, game overlay or recording compatibility."}
