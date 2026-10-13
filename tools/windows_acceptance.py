"""Test native Windows integration against this process's own caption window.

No keyboard injection, no user-screen images saved, no external application
settings changed. The only screen crop is the rectangle of our test window.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from screen_translator.platform.windows.dpi import enable_dpi_awareness
enable_dpi_awareness()

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontInfo, QPainter
from PySide6.QtWidgets import QApplication, QWidget
from screen_translator.capture.mss_backend import MSSCaptureBackend
from screen_translator.contracts import Region, Settings, TranslationResult
from screen_translator.diagnostics import no_network
from screen_translator.inference.ocr.rapidocr_engine import RapidOCREngine
from screen_translator.platform.windows.hotkeys import WindowsHotkeys
from screen_translator.platform.windows.monitors import cursor_position, enumerate_monitors
from screen_translator.ui.subtitle_overlay import SubtitleOverlay
from screen_translator.ui.fonts import register_chinese_fallback


class CaptionWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.text = "The translation works offline."
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                            | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.resize(1000, 160)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#202020"))
        painter.setPen(QColor("white"))
        painter.setFont(QFont("Microsoft YaHei UI", 30))
        painter.drawText(self.rect().adjusted(28, 0, -24, 0), Qt.AlignmentFlag.AlignVCenter, self.text)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    user32.GetWindowDisplayAffinity.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowDisplayAffinity.restype = wintypes.BOOL
    get_style = user32.GetWindowLongPtrW
    get_style.argtypes = [wintypes.HWND, ctypes.c_int]
    get_style.restype = ctypes.c_ssize_t
    report = {"passed_core_native": False, "screenshots_saved": False,
              "interactive_drag_tested": False, "physical_escape_tested": False,
              "capture_tests": [], "hotkey_errors": []}
    report["caption_font_provider"] = register_chinese_fallback(app)
    caption = CaptionWindow()
    hotkeys = WindowsHotkeys()
    overlay = None
    backend = None

    def settle():
        for _ in range(6):
            app.processEvents()
            time.sleep(0.05)

    def affinity(window):
        value = wintypes.DWORD()
        if not user32.GetWindowDisplayAffinity(int(window.winId()), ctypes.byref(value)):
            raise ctypes.WinError(ctypes.get_last_error())
        return value.value

    try:
        report["font_family"] = QFontInfo(QFont("Microsoft YaHei UI", 30)).family()
        try:
            cursor_position()
            report["cursor_api_available"] = True
        except OSError:
            report["cursor_api_available"] = False
        monitors = enumerate_monitors()
        monitor = next((m for m in monitors if m.primary), monitors[0])
        caption.move(app.primaryScreen().geometry().x() + 50, app.primaryScreen().geometry().y() + 50)
        original_foreground = user32.GetForegroundWindow()
        caption.show()
        settle()
        bounds = wintypes.RECT()
        if not user32.GetWindowRect(int(caption.winId()), ctypes.byref(bounds)):
            raise OSError("Could not get own test window rectangle")
        region = Region(bounds.left, bounds.top, bounds.right - bounds.left,
                        bounds.bottom - bounds.top, monitor.id, monitor.bounds)
        backend = MSSCaptureBackend()
        ocr = RapidOCREngine()
        with no_network() as attempts:
            for text, expected in (("The translation works offline.", "offline"),
                                   ("屏幕翻译支持离线运行。", "离线")):
                caption.text = text
                caption.update()
                settle()
                # The sample rectangle belongs to our visible HWND. Only a
                # crop matching its background is accepted for OCR.
                image = backend.grab(region)
                background_ok = bool((image[4, 4, :3] == [32, 32, 32]).all())
                recognized = ocr.recognize(image).text if background_ok else ""
                report["capture_tests"].append({"input": text, "ocr": recognized,
                                               "passed": background_ok and expected in recognized})
            overlay = SubtitleOverlay(Settings(region=region, show_source=False))
            overlay.set_result(TranslationResult("caption", "这是悬浮字幕窗口测试", "en-zh", 1))
            before_overlay = user32.GetForegroundWindow()
            overlay.show()
            settle()
            report["overlay_did_not_take_focus"] = user32.GetForegroundWindow() == before_overlay
            style = get_style(int(overlay.winId()), -20)
            required = 0x08000000 | 0x00080000 | 0x00000080 | 0x00000020 | 0x00000008
            report["overlay_native_styles_ok"] = (style & required) == required
            report["default_capture_affinity"] = affinity(overlay)
            report["default_recording_policy_ok"] = (
                overlay.capture_policy_applied and not overlay.capture_excluded
                and report["default_capture_affinity"] == 0)
            # Move our own overlay onto our own caption. The recording-compatible
            # default must allow the subtitle to appear in this own-window crop.
            overlay.move(caption.pos())
            settle()
            recognized = ocr.recognize(backend.grab(region)).text
            report["default_overlay_visible_in_mss"] = "悬浮" in recognized
            # Exclusion remains an explicitly selected option, not the default.
            overlay.update_settings(Settings(region=region, show_source=False,
                                             recording_compatibility=False))
            overlay.move(caption.pos())
            settle()
            report["optional_capture_affinity"] = affinity(overlay)
            report["optional_exclusion_policy_ok"] = (
                overlay.capture_policy_applied and overlay.capture_excluded
                and report["optional_capture_affinity"] == 0x11)
            recognized = ocr.recognize(backend.grab(region)).text
            report["overlay_excluded_from_mss"] = "离线" in recognized and "悬浮" not in recognized
            overlay.hide()
            settle()
            report["hidden_capture_affinity"] = affinity(overlay)
            report["hidden_policy_cleared"] = report["hidden_capture_affinity"] == 0
            overlay.set_result(TranslationResult("new caption", "后台新字幕测试", "en-zh", 1))
            overlay.update_settings(Settings(region=region, show_source=False,
                                             recording_compatibility=False))
            settle()
            report["hidden_background_updates_stay_safe"] = (
                affinity(overlay) == 0 and not overlay.isVisible()
                and not overlay._topmost_timer.isActive())
            report["nvidia_recording_tested"] = False
            report["exclusive_fullscreen_game_tested"] = False
            report["network_attempts"] = attempts.copy()
        actions = []
        hotkeys.action.connect(actions.append)
        hotkeys.error.connect(report["hotkey_errors"].append)
        hotkeys.start(Settings())
        for hotkey_id in hotkeys._registered:
            user32.PostMessageW(hotkeys._hwnd, 0x0312, hotkey_id, 0)
        settle()
        report["registered_hotkey_actions"] = list(hotkeys._registered.values())
        report["native_hotkey_message_routing_ok"] = sorted(actions) == sorted(hotkeys._registered.values())
        report["all_hotkey_actions_registered"] = len(hotkeys._registered) == 3
        report["effective_hotkeys"] = hotkeys.effective_hotkeys
        report["requested_hotkeys_all_available"] = hotkeys.effective_hotkeys == Settings().hotkeys
        report["caption_did_not_take_focus"] = before_overlay == original_foreground
        report["passed_core_native"] = (all(c["passed"] for c in report["capture_tests"])
            and report["overlay_did_not_take_focus"] and report["overlay_native_styles_ok"]
            and report["native_hotkey_message_routing_ok"]
            and report["all_hotkey_actions_registered"] and not report["hotkey_errors"]
            and report["default_recording_policy_ok"] and report["default_overlay_visible_in_mss"]
            and report["optional_exclusion_policy_ok"] and report["overlay_excluded_from_mss"]
            and report["hidden_policy_cleared"]
            and report["hidden_background_updates_stay_safe"]
            and not report["network_attempts"])
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        hotkeys.close()
        if backend:
            backend.close()
        if overlay:
            overlay.close()
        caption.close()
        app.processEvents()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed_core_native"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
