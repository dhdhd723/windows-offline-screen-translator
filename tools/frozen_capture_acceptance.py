"""Native acceptance of the *frozen* Windows capture/OCR/translation path.

This is intentionally an interactive-desktop test, not a unit test. It only
captures this process's CaptionWindow client area and posts WM_HOTKEY to a
window whose PID is the frozen executable spawned below. It never synthesizes
physical keyboard input or targets an unrelated process. Run with desktop
access after building dist/ScreenTranslator/ScreenTranslator.exe.
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def _api():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetClientRect.restype = wintypes.BOOL
    user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user32.ClientToScreen.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                   wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.WindowFromPoint.argtypes = [wintypes.POINT]
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.IsChild.argtypes = [wintypes.HWND, wintypes.HWND]
    user32.IsChild.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT,
                                       wintypes.WPARAM, wintypes.LPARAM]
    user32.PostThreadMessageW.restype = wintypes.BOOL
    return user32, callback


def _client_region(hwnd: int):
    from screen_translator.contracts import Region
    from screen_translator.platform.windows.monitors import monitor_for_region

    user32, _ = _api()
    rect = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        raise OSError(ctypes.get_last_error(), "Cannot read own caption client rectangle")
    origin = wintypes.POINT(rect.left, rect.top)
    if not user32.ClientToScreen(hwnd, ctypes.byref(origin)):
        raise OSError(ctypes.get_last_error(), "Cannot map own caption client rectangle")
    candidate = Region(origin.x, origin.y, rect.right - rect.left,
                       rect.bottom - rect.top)
    monitor = monitor_for_region(candidate)
    if monitor is None or not candidate.valid():
        raise RuntimeError("Own caption ROI is not wholly inside one physical monitor")
    return Region(candidate.x, candidate.y, candidate.width, candidate.height,
                  monitor.id, monitor.bounds)


def _child_windows(pid: int) -> list[int]:
    user32, callback_type = _api()
    result: list[int] = []

    @callback_type
    def collect(hwnd, data):
        actual = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(actual))
        if actual.value == pid:
            result.append(int(hwnd))
        return True

    if not user32.EnumWindows(collect, 0):
        raise OSError(ctypes.get_last_error(), "Cannot enumerate desktop windows")
    return result


def _post_toggle(hwnd: int, child: subprocess.Popen) -> None:
    """Post only after re-checking the HWND belongs to our live Popen PID."""
    if child.poll() is not None:
        raise RuntimeError(f"Frozen child exited before toggle (code {child.returncode})")
    user32, _ = _api()
    actual = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(actual))
    if actual.value != child.pid:
        raise RuntimeError("Refusing to post WM_HOTKEY: HWND no longer belongs to spawned child")
    # The app's RegisterHotKey ID for Alt+T is 0xB101. This message is posted
    # to its own HWND; no SendInput or system-wide keyboard event is used.
    if not user32.PostMessageW(hwnd, 0x0312, 0xB101, (ord("T") << 16) | 0x0001):
        raise OSError(ctypes.get_last_error(), "Could not post toggle to spawned child")


def _pump_for(app, seconds: float) -> None:
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        app.processEvents()
        time.sleep(0.05)


def _cache_rows(cache_file: Path) -> dict[str, str]:
    if not cache_file.is_file():
        return {}
    try:
        uri = cache_file.resolve().as_uri() + "?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=0.5) as connection:
            return {str(key): str(value) for key, value in connection.execute(
                "SELECT key, translation FROM translations")}
    except sqlite3.Error:
        # The child may be creating its schema or committing a translation.
        return {}


def _assert_own_caption_visible(caption, region) -> None:
    """Refuse to proceed when another HWND covers any sample in our crop."""
    user32, _ = _api()
    hwnd = int(caption.winId())
    if not caption.isVisible():
        raise RuntimeError("Own caption window is no longer visible")
    if not user32.SetWindowPos(hwnd, wintypes.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010):
        raise OSError(ctypes.get_last_error(), "Cannot keep own test caption on top")
    for x_ratio, y_ratio in ((.1, .1), (.9, .1), (.1, .9), (.9, .9), (.5, .5)):
        point = wintypes.POINT(region.x + int(region.width * x_ratio),
                              region.y + int(region.height * y_ratio))
        actual = user32.WindowFromPoint(point)
        if actual != hwnd and not user32.IsChild(hwnd, actual):
            raise RuntimeError("Own caption is occluded; refusing to accept another window's text")


def _expected_cache_key(exe: Path, direction: str, text: str) -> str:
    from screen_translator.core.text import normalize_text
    from screen_translator.storage.translation_cache import make_cache_key
    manifest = json.loads((exe.parent / "models" / "manifest.json").read_text(encoding="utf-8"))
    return make_cache_key(manifest["translation"][direction]["id"], direction, normalize_text(text))


def _wait_for_translation(app, child: subprocess.Popen, cache_file: Path,
                          expected_key: str, expected_words: tuple[str, ...],
                          caption, region, timeout: float) -> tuple[str, int, float]:
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        app.processEvents()
        if child.poll() is not None:
            raise RuntimeError(f"Frozen child exited during translation (code {child.returncode})")
        _assert_own_caption_visible(caption, region)
        rows = _cache_rows(cache_file)
        translation = rows.get(expected_key)
        if translation is not None:
            if not all(word in translation.casefold() for word in expected_words):
                raise RuntimeError("Exact source was recognized, but translation lacks required sample meaning")
            return translation, len(rows), time.monotonic() - started
        time.sleep(0.10)
    raise TimeoutError(f"Expected exact source/direction cache key not produced within {timeout:.0f}s")


def _write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def run(args: argparse.Namespace) -> int:
    report: dict = {"passed": False, "mode": "frozen-native-capture",
                    "exe": str(args.exe), "stages": [], "child_pid": None,
                    "data_dir": None, "error": None}
    child: subprocess.Popen | None = None
    caption = None
    app = None
    target_hwnd: int | None = None
    started = False
    stop_posted = False
    try:
        if sys.platform != "win32":
            raise RuntimeError("This acceptance test requires Windows")
        if not args.exe.is_file():
            raise FileNotFoundError(args.exe)

        # The call must precede QApplication and any physical-coordinate query.
        from screen_translator.platform.windows.dpi import enable_dpi_awareness
        from screen_translator.contracts import Settings
        from screen_translator.storage.settings import SettingsStore
        enable_dpi_awareness()
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QFont
        from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
        import mss
        import numpy as np

        class CaptionWindow(QWidget):
            def __init__(self):
                super().__init__()
                self.setWindowTitle("本地翻译器验收字幕窗")
                self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
                self.setStyleSheet("background-color: #202020;")
                layout = QVBoxLayout(self)
                layout.setContentsMargins(14, 8, 14, 8)
                self.label = QLabel("The translation works offline.")
                self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.label.setFont(QFont("Microsoft YaHei", 29))
                self.label.setStyleSheet("color: white; background-color: #202020;")
                layout.addWidget(self.label)

        app = QApplication([])
        app.setQuitOnLastWindowClosed(False)
        caption = CaptionWindow()
        available = app.primaryScreen().availableGeometry()
        width = max(240, min(1000, available.width() - 64))
        caption.setFixedSize(width, min(180, max(100, available.height() - 64)))
        caption.move(available.x() + (available.width() - caption.width()) // 2,
                     available.y() + max(20, (available.height() - caption.height()) // 3))
        caption.show()
        caption.raise_()
        _pump_for(app, 0.7)
        region = _client_region(int(caption.winId()))
        report["caption_roi"] = region.to_dict()
        _assert_own_caption_visible(caption, region)
        with mss.MSS() as capture:
            image = np.asarray(capture.grab({"left": region.x, "top": region.y,
                                             "width": region.width, "height": region.height}))
            contrast = int(np.ptp(image[:, :, :3]))
        report["own_roi_contrast"] = contrast
        if contrast < 35:
            raise RuntimeError("Own caption ROI is nearly uniform; cannot verify visible text")

        # A fresh per-run directory prevents prior translations and user config
        # from satisfying this test. Only the spawned exe receives --data-dir.
        run_dir = args.data_dir / f"run-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
        run_dir.mkdir(parents=True, exist_ok=False)
        report["data_dir"] = str(run_dir)
        SettingsStore(run_dir / "config.json").save(Settings(region=region, cache_enabled=True))
        child = subprocess.Popen([str(args.exe), "--data-dir", str(run_dir)],
                                 cwd=str(args.exe.parent), stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        report["child_pid"] = child.pid

        ready_deadline = time.monotonic() + args.launch_timeout
        while time.monotonic() < ready_deadline:
            app.processEvents()
            if child.poll() is not None:
                raise RuntimeError(f"Frozen child exited at launch (code {child.returncode})")
            windows = _child_windows(child.pid)
            if windows:
                target_hwnd = windows[0]
                break
            time.sleep(0.10)
        if target_hwnd is None:
            raise TimeoutError("No HWND belonging to the spawned exe appeared")
        report["target_hwnd"] = target_hwnd
        _pump_for(app, 0.8)
        _post_toggle(target_hwnd, child)
        started = True

        cache_file = run_dir / "cache.sqlite3"
        english_translation, count, elapsed = _wait_for_translation(
            app, child, cache_file, _expected_cache_key(args.exe, "en-zh", "The translation works offline."),
            ("翻译", "离线"), caption, region, args.stage_timeout)
        report["stages"].append({"caption": "The translation works offline.",
                                 "expected_direction": "en-zh", "translation": english_translation,
                                 "cache_rows": count, "seconds": round(elapsed, 2),
                                 "exact_source_and_direction_verified": True, "passed": True})

        chinese_changed_at = time.monotonic()
        caption.label.setText("屏幕翻译支持离线运行。")
        _pump_for(app, 0.7)
        chinese_translation, count, elapsed = _wait_for_translation(
            app, child, cache_file, _expected_cache_key(args.exe, "zh-en", "屏幕翻译支持离线运行。"),
            ("screen", "offline"), caption, region, args.stage_timeout)
        elapsed = time.monotonic() - chinese_changed_at
        report["stages"].append({"caption": "屏幕翻译支持离线运行。",
                                 "expected_direction": "zh-en", "translation": chinese_translation,
                                 "cache_rows": count, "seconds": round(elapsed, 2),
                                 "exact_source_and_direction_verified": True, "passed": True})

        _post_toggle(target_hwnd, child)
        stop_posted = True
        _pump_for(app, 0.3)
        report["passed"] = True
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if child is not None and child.poll() is None:
            if started and not stop_posted and target_hwnd is not None:
                try:
                    _post_toggle(target_hwnd, child)
                except Exception as exc:
                    report["stop_error"] = f"{type(exc).__name__}: {exc}"
            # Ask only our spawned child's UI thread to end its event loop.
            # If unsupported, terminate only the Popen handle and report this
            # cleanup as forced, not as a normal application exit.
            try:
                user32, _ = _api()
                process_id = wintypes.DWORD()
                thread_id = user32.GetWindowThreadProcessId(target_hwnd, ctypes.byref(process_id)) if target_hwnd else 0
                if thread_id and process_id.value == child.pid:
                    user32.PostThreadMessageW(thread_id, 0x0012, 0, 0)
                child.wait(timeout=5)
                report["cleanup"] = "own-child-WM_QUIT"
            except subprocess.TimeoutExpired:
                child.terminate()
                child.wait(timeout=10)
                report["cleanup"] = "own-child-terminated; normal exit checked separately by smoke test"
            except Exception as exc:
                report["cleanup_error"] = f"{type(exc).__name__}: {exc}"
                report["passed"] = False
        if caption is not None:
            caption.close()
        if app is not None:
            app.processEvents()
        report["child_exit_code"] = child.poll() if child is not None else None
        _write_report(args.report, report)
    return 0 if report["passed"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path,
                        default=PROJECT_ROOT / "dist" / "ScreenTranslator" / "ScreenTranslator.exe")
    parser.add_argument("--data-dir", type=Path,
                        default=PROJECT_ROOT / "build" / "frozen-capture-acceptance")
    parser.add_argument("--report", type=Path,
                        default=PROJECT_ROOT / "build" / "frozen-capture-test.json")
    parser.add_argument("--launch-timeout", type=float, default=25.0)
    parser.add_argument("--stage-timeout", type=float, default=90.0)
    args = parser.parse_args()
    args.exe = args.exe.resolve()
    args.data_dir = args.data_dir.resolve()
    args.report = args.report.resolve()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
