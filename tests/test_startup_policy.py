"""Startup decisions use fake native functions, never a user's desktop."""
from __future__ import annotations

from contextlib import nullcontext
import ctypes
import sys
from types import SimpleNamespace

import pytest

from screen_translator import application
from screen_translator.contracts import Settings
from screen_translator.core.startup_policy import startup_presentation
from screen_translator.platform.windows import startup_environment as native


@pytest.mark.parametrize("changes", [dict(enabled=False), dict(background=True),
    dict(diagnostic=True), dict(suppress_once=True), dict(foreground_covers_monitor=True)])
def test_skip_reasons(changes):
    result = startup_presentation(**{**dict(enabled=True), **changes})
    assert not result.show and not result.animate


def test_reduced_motion_and_real_ready_status():
    result = startup_presentation(enabled=True, animations_enabled=False)
    assert result.show and not result.animate and "快捷键已就绪" in result.status
    failed = startup_presentation(enabled=True, hotkeys_ready=False)
    assert "不可用" in failed.status and "已就绪" not in failed.status


@pytest.mark.parametrize("window, monitor, expected", [
    ((0, 0, 1920, 1080), (0, 0, 1920, 1080), True),
    ((-8, -8, 1928, 1088), (0, 0, 1920, 1080), True),
    ((1, 1, 1919, 1079), (0, 0, 1920, 1080), True),
    ((10, 10, 1900, 1060), (0, 0, 1920, 1080), False),
    ((-1920, 0, 0, 1080), (-1920, 0, 0, 1080), True),
    ((0, 0, 2560, 1440), (0, 0, 2560, 1440), True),
    ((0, 0, 0, 0), (0, 0, 1920, 1080), False),
])
def test_covering_geometry_is_not_exclusive_game_detection(window, monitor, expected):
    assert native.covers_monitor(window, monitor) is expected


class FakeAPI:
    def __init__(self, *, window=(0, 0, 1920, 1080), class_name="TestGame",
                 hwnd=100, failure=None, animations=True):
        self.window, self.class_name, self.hwnd = window, class_name, hwnd
        self.failure, self.animations = failure, animations

    def GetForegroundWindow(self):
        return self.hwnd

    def GetClassNameW(self, hwnd, buffer, count):
        buffer.value = self.class_name
        return 0 if self.failure == "class" else len(self.class_name)

    def IsWindowVisible(self, hwnd):
        return True

    def GetWindowRect(self, hwnd, pointer):
        pointer._obj.left, pointer._obj.top, pointer._obj.right, pointer._obj.bottom = self.window
        return self.failure != "rect"

    def MonitorFromWindow(self, hwnd, fallback):
        assert fallback == 2
        return 0 if self.failure == "monitor" else 200

    def GetMonitorInfoW(self, monitor, pointer):
        assert pointer._obj.cbSize == ctypes.sizeof(native._MonitorInfo)
        pointer._obj.rcMonitor.left, pointer._obj.rcMonitor.top = 0, 0
        pointer._obj.rcMonitor.right, pointer._obj.rcMonitor.bottom = 1920, 1080
        return self.failure != "info"

    def SystemParametersInfoW(self, action, param, pointer, flags):
        assert (action, param, flags) == (0x1042, 0, 0)  # GET only, no system mutation
        pointer._obj.value = self.animations
        return self.failure != "animations"


@pytest.mark.parametrize("class_name", ["Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"])
def test_windows_desktop_is_not_blocked(class_name):
    assert not native._foreground_covers_monitor(FakeAPI(class_name=class_name))


@pytest.mark.parametrize("failure", ["class", "rect", "monitor", "info"])
def test_uncertain_geometry_fails_closed(failure):
    assert native._foreground_covers_monitor(FakeAPI(failure=failure))


def test_no_foreground_window_is_uncertain_and_suppresses_decoration():
    assert native._foreground_covers_monitor(FakeAPI(hwnd=0))


def fake_dll(api):
    # Real ctypes function objects accept argtypes/restype; regular bound methods
    # do not. Thin fake callables cover the declaration path without user32.
    return SimpleNamespace(**{name: (lambda *args, method=getattr(api, name): method(*args))
        for name in ("GetForegroundWindow", "GetClassNameW", "IsWindowVisible", "GetWindowRect",
                     "MonitorFromWindow", "GetMonitorInfoW", "SystemParametersInfoW")})


@pytest.mark.parametrize("animation,failure,expected", [(True, None, True),
    (False, None, False), (True, "animations", False)])
def test_query_respects_system_motion_and_failure(monkeypatch, animation, failure, expected):
    monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **kw: fake_dll(FakeAPI(
        animations=animation, failure=failure, window=(10, 10, 800, 600))))
    result = native.query_startup_environment()
    assert result.animations_enabled is expected
    assert not result.foreground_covers_monitor


def test_query_api_failure_safely_suppresses_card(monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("fake inaccessible desktop")
    monkeypatch.setattr(ctypes, "WinDLL", fail)
    assert native.query_startup_environment() == native.StartupEnvironment()


@pytest.mark.parametrize("options", [dict(background=True), dict(diagnostic=True),
                                    dict(suppress_once=True), dict(enabled=False)])
def test_suppressed_card_does_not_query_native_or_create_ui(monkeypatch, options):
    settings = Settings(startup_animation=options.pop("enabled", True))
    def forbidden():
        raise AssertionError("Suppressed startup must not inspect the desktop")
    monkeypatch.setattr(native, "query_startup_environment", forbidden)
    assert application.show_startup_card(settings, **options) is None


def test_full_monitor_foreground_does_not_import_ui(monkeypatch):
    monkeypatch.setattr(native, "query_startup_environment", lambda: native.StartupEnvironment(True, True))
    assert application.show_startup_card(Settings()) is None


def test_card_starts_without_wait_or_model_loading(monkeypatch):
    from screen_translator.ui import startup_card
    calls = []
    class Card:
        def __init__(self, **kwargs):
            calls.append(kwargs)
        def start(self):
            calls.append("start")
        def finish_now(self):
            calls.append("finish")
    monkeypatch.setattr(startup_card, "StartupCard", Card)
    monkeypatch.setattr(native, "query_startup_environment", lambda: native.StartupEnvironment(False, False))
    result = application.show_startup_card(Settings(), hotkeys_ready=False)
    assert isinstance(result, Card)
    assert calls == [dict(status="程序已驻留托盘 · 部分快捷键不可用", animations_enabled=False), "start"]


def test_failed_decoration_is_not_a_startup_failure(monkeypatch):
    from screen_translator.ui import startup_card
    calls = []
    class Card:
        def __init__(self, **kwargs):
            pass
        def start(self):
            raise RuntimeError("fake rendering failure")
        def finish_now(self):
            calls.append("finish")
    monkeypatch.setattr(startup_card, "StartupCard", Card)
    monkeypatch.setattr(native, "query_startup_environment", lambda: native.StartupEnvironment(True, False))
    assert application.show_startup_card(Settings()) is None
    assert calls == ["finish"]


@pytest.mark.parametrize("frozen", [True, False])
def test_new_autostart_registration_uses_background_without_changing_registry(monkeypatch, frozen):
    calls = []
    fake = SimpleNamespace(HKEY_CURRENT_USER=1, REG_SZ=1,
        CreateKey=lambda *args: nullcontext("fakekey"),
        SetValueEx=lambda *args: calls.append(args))
    monkeypatch.setitem(sys.modules, "winreg", fake)
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    monkeypatch.setattr(application, "install_root", lambda: __import__("pathlib").Path("C:/demo"))
    application.set_auto_start(True)
    assert len(calls) == 1 and calls[0][-1].endswith(" --background")
    assert ("launcher.py" in calls[0][-1]) is not frozen
