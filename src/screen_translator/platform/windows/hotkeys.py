from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication, QWidget

from screen_translator.contracts import Settings


def parse_hotkey(value: str) -> tuple[int, int]:
    parts = [part.strip().upper() for part in value.split("+") if part.strip()]
    if not parts:
        raise ValueError("快捷键不能为空")
    modifiers = {"ALT": 0x0001, "CTRL": 0x0002, "CONTROL": 0x0002,
                 "SHIFT": 0x0004, "WIN": 0x0008, "WINDOWS": 0x0008}
    mask = 0
    key = None
    for part in parts:
        if part in modifiers:
            bit = modifiers[part]
            if mask & bit:
                raise ValueError("快捷键修饰键重复")
            mask |= bit
            continue
        if key is not None:
            raise ValueError("每个快捷键只能有一个普通按键")
        if len(part) == 1 and ("A" <= part <= "Z" or "0" <= part <= "9"):
            key = ord(part)
        elif part.startswith("F") and part[1:].isdigit() and 1 <= int(part[1:]) <= 24:
            key = 0x70 + int(part[1:]) - 1
        else:
            key = {"SPACE": 0x20, "ENTER": 0x0D, "RETURN": 0x0D,
                   "ESC": 0x1B, "ESCAPE": 0x1B, "TAB": 0x09,
                   "HOME": 0x24, "END": 0x23, "PAGEUP": 0x21,
                   "PAGEDOWN": 0x22, "INSERT": 0x2D, "DELETE": 0x2E}.get(part)
            if key is None:
                raise ValueError(f"不支持的按键：{part}")
    if key is None or not mask:
        raise ValueError("请使用 Alt、Ctrl、Shift 或 Win 加一个按键")
    return mask | 0x4000, key  # MOD_NOREPEAT


class _MSG(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("message", wintypes.UINT),
                ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM),
                ("time", wintypes.DWORD), ("pt", wintypes.POINT)]


class _HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, owner: "WindowsHotkeys") -> None:
        super().__init__()
        self.owner = owner

    def nativeEventFilter(self, event_type, message):
        if sys.platform == "win32":
            msg = _MSG.from_address(int(message))
            hotkey_id = int(msg.wParam)
            if msg.message == 0x0312 and hotkey_id in (0xB100, 0xB101, 0xB102):
                # Windows can have already queued this message when recording
                # unregisters the shortcuts. Consume it even with an empty map.
                if self.owner._input_suspended:
                    return True, 0
                action = self.owner._registered.get(hotkey_id)
                if action is not None:
                    self.owner.action.emit(action)
                    return True, 0
        return False, 0


class WindowsHotkeys(QObject):
    action = Signal(str)
    error = Signal(str)
    binding_changed = Signal(str, str)
    registrations_changed = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._window = QWidget()
        self._window.setObjectName("HotkeyMessageWindow")
        self._hwnd = int(self._window.winId())
        self._registered: dict[int, str] = {}
        self._effective_hotkeys: dict[str, str] = {}
        self._filter = _HotkeyFilter(self)
        self._settings = Settings()
        self._monitoring = False
        self._selecting = False
        self._escape_down = False
        self._closed = False
        self._recording = False
        self._resume_pending = False
        self._resume_keys: set[int] = set()
        self._resume_error_reported = False
        self._timer = QTimer(self)
        self._timer.setInterval(35)
        self._timer.timeout.connect(self._poll_escape)
        self._resume_timer = QTimer(self)
        self._resume_timer.setInterval(35)
        self._resume_timer.timeout.connect(self._poll_recording_release)
        self._installed = False
        self._user32 = None
        if sys.platform == "win32":
            self._user32 = ctypes.WinDLL("user32", use_last_error=True)
            self._user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int,
                                                    wintypes.UINT, wintypes.UINT]
            self._user32.RegisterHotKey.restype = wintypes.BOOL
            self._user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
            self._user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
            self._user32.GetAsyncKeyState.restype = ctypes.c_short
            self._user32.PeekMessageW.argtypes = [ctypes.POINTER(_MSG), wintypes.HWND,
                                                 wintypes.UINT, wintypes.UINT, wintypes.UINT]
            self._user32.PeekMessageW.restype = wintypes.BOOL

    def start(self, settings: Settings) -> None:
        if self._closed:
            return
        app = QApplication.instance()
        if app is not None and not self._installed:
            app.installNativeEventFilter(self._filter)
            self._installed = True
        self.update(settings)

    @property
    def effective_hotkeys(self) -> dict[str, str]:
        """Effective bindings, retained while native registration is suspended."""
        return self._effective_hotkeys.copy()

    @property
    def _input_suspended(self) -> bool:
        return self._closed or self._recording or self._resume_pending

    def update(self, settings: Settings) -> None:
        if self._closed:
            return
        self._settings = Settings.from_dict(settings.to_dict())
        if self._recording or self._resume_pending:
            self._remember_release_keys()
            return
        self._register_settings()

    def _register_settings(self) -> None:
        if self._input_suspended:
            return
        settings = self._settings
        self._unregister()
        taken: set[tuple[int, int]] = set()
        labels = {"select": "框选", "toggle": "启停", "clear": "清空"}
        # A fallback must not claim a shortcut the user assigned to another action.
        reserved_for_others: set[tuple[int, int]] = set()
        for other in ("toggle", "clear"):
            try:
                reserved_for_others.add(parse_hotkey(settings.hotkeys.get(other, "")))
            except ValueError:
                pass
        for index, action in enumerate(("select", "toggle", "clear")):
            if self._input_suspended:
                break
            value = settings.hotkeys.get(action, "")
            try:
                combination = parse_hotkey(value)
                if combination in taken:
                    raise ValueError("与另一个快捷键重复")
                hotkey_id = 0xB100 + index
                if self._user32 is None:
                    continue
                if self._user32.RegisterHotKey(self._hwnd, hotkey_id, *combination):
                    self._registered[hotkey_id] = action
                    self._effective_hotkeys[action] = value
                    taken.add(combination)
                    continue
                # Preserve custom choices and every non-selection action. A
                # default-only alternate keeps Alt+R working where available.
                if action != "select" or "".join(value.split()).casefold() != "alt+r":
                    raise ValueError("已被其他程序占用或系统不允许")
                fallback = None
                for candidate in ("Ctrl+Alt+R", "Ctrl+Shift+R"):
                    alternate = parse_hotkey(candidate)
                    if alternate in taken or alternate in reserved_for_others:
                        continue
                    if self._user32.RegisterHotKey(self._hwnd, hotkey_id, *alternate):
                        fallback = (candidate, alternate)
                        break
                if fallback is None:
                    raise ValueError("已被占用；Ctrl+Alt+R 和 Ctrl+Shift+R 也不可用")
                effective, alternate = fallback
                self._registered[hotkey_id] = action
                self._effective_hotkeys[action] = effective
                taken.add(alternate)
                self.binding_changed.emit(action, effective)
            except ValueError as exc:
                self.error.emit(f"{labels[action]}快捷键 {value}：{exc}。可从托盘菜单操作或修改快捷键。")
        self._update_escape_timer()
        if not self._input_suspended:
            self.registrations_changed.emit(self.effective_hotkeys)

    def set_recording(self, enabled: bool) -> None:
        """Release our global shortcuts while a focused widget records a chord.

        Restoring registrations is deferred until held keys are released, so
        ending or cancelling recording cannot itself trigger a global action.
        This reads key state only during that short release guard; it is not a
        global keyboard recorder.
        """
        if self._closed:
            return
        if enabled:
            if self._recording:
                return
            self._recording = True
            self._resume_pending = False
            self._resume_timer.stop()
            self._resume_error_reported = False
            self._remember_release_keys()
            self._timer.stop()
            self._escape_down = False
            self._unregister(preserve_effective=True)
            return
        if not self._recording:
            return
        self._recording = False
        self._remember_release_keys()
        if self._user32 is None:
            self._resume_keys.clear()
            self._register_settings()
            return
        self._resume_pending = True
        # Always allow an event-loop turn to consume queued WM_HOTKEY messages.
        self._resume_timer.start()

    def _remember_release_keys(self) -> None:
        # Generic modifier virtual keys include both left and right variants.
        self._resume_keys.update((0x10, 0x11, 0x12, 0x5B, 0x5C, 0x1B))
        for value in (*self._effective_hotkeys.values(), *self._settings.hotkeys.values()):
            try:
                self._resume_keys.add(parse_hotkey(value)[1])
            except ValueError:
                pass

    def _poll_recording_release(self) -> None:
        if self._closed or self._recording or not self._resume_pending:
            self._resume_timer.stop()
            return
        if self._user32 is not None:
            try:
                if any(self._user32.GetAsyncKeyState(key) & 0x8000
                       for key in self._resume_keys):
                    return
                self._discard_queued_hotkeys()
            except (OSError, RuntimeError) as exc:
                # Failing safely is preferable to activating a still-held chord.
                # Keep the non-blocking timer running in case the failure clears.
                if not self._resume_error_reported:
                    self._resume_error_reported = True
                    self.error.emit(f"暂时无法确认按键已松开，快捷键将稍后恢复：{exc}")
                return
        self._resume_timer.stop()
        self._resume_pending = False
        self._resume_keys.clear()
        self._resume_error_reported = False
        self._register_settings()

    def _discard_queued_hotkeys(self) -> None:
        peek = getattr(self._user32, "PeekMessageW", None)
        if peek is None:
            return
        message = _MSG()
        # There are only three MOD_NOREPEAT bindings. Bound the drain even if a
        # faulty native adapter keeps reporting messages, and retry next tick.
        for _ in range(64):
            if not peek(ctypes.byref(message), self._hwnd, 0x0312, 0x0312, 0x0001):
                return
        raise RuntimeError("快捷键消息队列仍有待清理消息")

    def set_monitoring(self, enabled: bool) -> None:
        if self._closed:
            return
        self._monitoring = bool(enabled)
        self._update_escape_timer()

    def set_selecting(self, enabled: bool) -> None:
        if self._closed:
            return
        self._selecting = bool(enabled)
        if self._user32 is not None:
            self._escape_down = bool(self._user32.GetAsyncKeyState(0x1B) & 0x8000)

    def _update_escape_timer(self) -> None:
        if (not self._input_suspended and self._monitoring
                and self._settings.esc_enabled and self._user32 is not None):
            self._escape_down = bool(self._user32.GetAsyncKeyState(0x1B) & 0x8000)
            self._timer.start()
        else:
            self._timer.stop()
            self._escape_down = False

    def _poll_escape(self) -> None:
        if self._input_suspended or self._user32 is None:
            return
        down = bool(self._user32.GetAsyncKeyState(0x1B) & 0x8000)
        app = QApplication.instance()
        selecting = self._selecting or bool(app and app.property("regionSelecting"))
        suppressed_until = app.property("regionEscapeSuppressedUntil") if app else None
        suppressed = bool(suppressed_until and time.monotonic() < float(suppressed_until))
        if down and not self._escape_down and not selecting and not suppressed:
            self.action.emit("hide")
        self._escape_down = down

    def _unregister(self, *, preserve_effective: bool = False) -> None:
        if self._user32 is not None:
            for hotkey_id in tuple(self._registered):
                self._user32.UnregisterHotKey(self._hwnd, hotkey_id)
        self._registered.clear()
        if not preserve_effective:
            self._effective_hotkeys.clear()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._timer.stop()
        self._resume_timer.stop()
        self._recording = False
        self._resume_pending = False
        self._resume_keys.clear()
        self._unregister()
        app = QApplication.instance()
        if app is not None and self._installed:
            app.removeNativeEventFilter(self._filter)
            self._installed = False
        self._window.close()
        self._window.deleteLater()
