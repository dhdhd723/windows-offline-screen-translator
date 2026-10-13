"""Qt behaviour tests use an offscreen platform; native input is not simulated."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QApplication

from screen_translator.contracts import Region, Settings, TranslationResult
from screen_translator.platform.windows.hotkeys import WindowsHotkeys, parse_hotkey
from screen_translator.platform.windows.monitors import Monitor
from screen_translator.ui.display_coordinates import ScreenMapping
from screen_translator.ui.main import MainUI
from screen_translator.ui.settings_window import SettingsDialog


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    yield app


@pytest.fixture
def ui(qapp, monkeypatch):
    monkeypatch.setattr("screen_translator.ui.subtitle_overlay.apply_overlay_styles", lambda hwnd: True)
    monkeypatch.setattr("screen_translator.ui.subtitle_overlay.set_capture_exclusion", lambda hwnd, enabled: True)
    value = MainUI(Settings())
    yield value
    value.close()
    qapp.processEvents()


def test_coordinate_mapping_uses_monitor_origin_not_absolute_scale():
    class Screen:
        def geometry(self):
            return QRect(-2560, -200, 1280, 800)

    monitor = Monitor("left", (-1920, -300, 0, 900), (-1920, -300, 0, 850))
    mapping = ScreenMapping(Screen(), monitor)
    qt_point = mapping.physical_to_qt(-1770, -150)
    assert (qt_point.x(), qt_point.y()) == (-2460, -100)
    assert mapping.qt_to_physical(qt_point.x(), qt_point.y()) == (-1770, -150)
    assert mapping.physical_rect_to_qt(monitor.bounds) == QRect(-2560, -200, 1280, 800)
    assert mapping.qt_rect_to_physical(QRect(-2460, -100, 200, 80)) == (-1770, -150, -1470, -30)


def test_public_open_settings_creates_one_editable_dialog_and_reuses_it(ui):
    openings = []
    ui.settings_opening.connect(lambda: openings.append(True))
    assert not ui.is_closed
    ui.open_settings()
    dialog = ui._settings_dialog
    assert isinstance(dialog, SettingsDialog) and dialog.isVisible()
    assert not (dialog.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus)
    assert not (dialog.windowFlags() & Qt.WindowType.WindowTransparentForInput)
    dialog.font_size.setValue(23)
    ui.open_settings()
    assert ui._settings_dialog is dialog and dialog.font_size.value() == 23
    assert len(openings) == 2


def test_public_open_settings_after_shutdown_is_ignored(ui):
    ui.close()
    assert ui.is_closed
    openings = []
    ui.settings_opening.connect(lambda: openings.append(True))
    ui.open_settings()
    assert ui._settings_dialog is None and openings == []


def test_settings_opening_handler_can_shutdown_without_creating_a_dialog(ui):
    ui.settings_opening.connect(ui.close)
    ui.open_settings()
    assert ui.is_closed and ui._settings_dialog is None


def test_region_topology_validation(monkeypatch):
    from screen_translator.platform.windows import monitors
    monitor = Monitor("left", (-1920, 0, 0, 1080), (-1920, 0, 0, 1040))
    monkeypatch.setattr(monitors, "enumerate_monitors", lambda: [monitor])
    assert monitors.validate_region(Region(-1800, 20, 500, 100, "left", monitor.bounds))
    assert not monitors.validate_region(Region(-100, 20, 500, 100, "left", monitor.bounds))
    assert not monitors.validate_region(Region(-1800, 20, 500, 100, "gone", monitor.bounds))
    assert not monitors.validate_region(Region(-1800, 20, 500, 100, "left", (-1920, 0, 0, 1200)))


def test_shortcuts_validate_modifiers_and_duplicates():
    assert parse_hotkey("Alt+R") == (0x4001, ord("R"))
    assert parse_hotkey("Ctrl+Shift+F12") == (0x4006, 0x7B)
    for bad in ("", "R", "Alt+R+C", "Alt+Alt+R", "Alt+F25"):
        with pytest.raises(ValueError):
            parse_hotkey(bad)


class _FakeUser32:
    def __init__(self, blocked=()):
        self.blocked = set(blocked)
        self.calls = []
        self.unregistered = []

    def RegisterHotKey(self, hwnd, hotkey_id, modifiers, key):
        combination = (modifiers, key)
        self.calls.append((hotkey_id, combination))
        return combination not in self.blocked

    def UnregisterHotKey(self, hwnd, hotkey_id):
        self.unregistered.append(hotkey_id)

    def GetAsyncKeyState(self, key):
        return 0


def _legacy_settings() -> Settings:
    return Settings(hotkeys={**Settings().hotkeys, "select": "Alt+R"})


def test_default_select_avoids_nvidia_alt_r_and_alt_shift_r(qapp):
    hotkeys = WindowsHotkeys()
    fake = _FakeUser32()
    hotkeys._user32 = fake
    changed = []
    errors = []
    hotkeys.binding_changed.connect(lambda action, key: changed.append((action, key)))
    hotkeys.error.connect(errors.append)
    hotkeys.update(Settings())
    assert hotkeys.effective_hotkeys["select"] == "Ctrl+Alt+R"
    assert fake.calls[0][1] == parse_hotkey("Ctrl+Alt+R")
    assert not changed and not errors
    hotkeys.close()


def test_occupied_default_alt_r_uses_first_available_fallback(qapp):
    hotkeys = WindowsHotkeys()
    fake = _FakeUser32({parse_hotkey("Alt+R")})
    hotkeys._user32 = fake
    changed = []
    errors = []
    hotkeys.binding_changed.connect(lambda action, key: changed.append((action, key)))
    hotkeys.error.connect(errors.append)
    hotkeys.update(_legacy_settings())
    assert [call[1] for call in fake.calls[:2]] == [parse_hotkey("Alt+R"), parse_hotkey("Ctrl+Alt+R")]
    assert hotkeys.effective_hotkeys["select"] == "Ctrl+Alt+R"
    assert changed == [("select", "Ctrl+Alt+R")]
    assert not errors
    hotkeys.close()


def test_fallback_preserves_another_explicit_shortcut(qapp):
    settings = _legacy_settings()
    settings.hotkeys["toggle"] = "Ctrl+Alt+R"
    hotkeys = WindowsHotkeys()
    fake = _FakeUser32({parse_hotkey("Alt+R")})
    hotkeys._user32 = fake
    changed = []
    hotkeys.binding_changed.connect(lambda action, key: changed.append((action, key)))
    hotkeys.update(settings)
    assert hotkeys.effective_hotkeys["select"] == "Ctrl+Shift+R"
    assert hotkeys.effective_hotkeys["toggle"] == "Ctrl+Alt+R"
    assert (0xB100, parse_hotkey("Ctrl+Alt+R")) not in fake.calls
    assert changed == [("select", "Ctrl+Shift+R")]
    hotkeys.close()


def test_second_fallback_when_first_is_also_occupied(qapp):
    blocked = {parse_hotkey("Alt+R"), parse_hotkey("Ctrl+Alt+R")}
    hotkeys = WindowsHotkeys()
    fake = _FakeUser32(blocked)
    hotkeys._user32 = fake
    changed = []
    hotkeys.binding_changed.connect(lambda action, key: changed.append((action, key)))
    hotkeys.update(_legacy_settings())
    assert hotkeys.effective_hotkeys["select"] == "Ctrl+Shift+R"
    assert changed == [("select", "Ctrl+Shift+R")]
    assert [call[1] for call in fake.calls[:3]] == [parse_hotkey(key) for key in
                                                   ("Alt+R", "Ctrl+Alt+R", "Ctrl+Shift+R")]
    hotkeys.close()


def test_custom_shortcut_failure_does_not_fallback(qapp):
    settings = Settings()
    settings.hotkeys["select"] = "Alt+X"
    hotkeys = WindowsHotkeys()
    fake = _FakeUser32({parse_hotkey("Alt+X")})
    hotkeys._user32 = fake
    changed = []
    errors = []
    hotkeys.binding_changed.connect(lambda action, key: changed.append((action, key)))
    hotkeys.error.connect(errors.append)
    hotkeys.update(settings)
    assert "select" not in hotkeys.effective_hotkeys
    assert [call[1] for call in fake.calls] == [parse_hotkey("Alt+X"),
                                               parse_hotkey("Alt+T"), parse_hotkey("Alt+C")]
    assert not changed and len(errors) == 1
    hotkeys.close()


def test_default_select_errors_only_after_all_fallbacks_fail(qapp):
    blocked = {parse_hotkey(key) for key in ("Alt+R", "Ctrl+Alt+R", "Ctrl+Shift+R")}
    hotkeys = WindowsHotkeys()
    fake = _FakeUser32(blocked)
    hotkeys._user32 = fake
    errors = []
    hotkeys.error.connect(errors.append)
    hotkeys.update(_legacy_settings())
    assert "select" not in hotkeys.effective_hotkeys
    assert len(errors) == 1 and "Ctrl+Shift+R" in errors[0]
    assert [call[1] for call in fake.calls[:3]] == [parse_hotkey(key) for key in
                                                   ("Alt+R", "Ctrl+Alt+R", "Ctrl+Shift+R")]
    hotkeys.close()


def test_overlay_renders_plain_text_preferences_hide_clear(ui, qapp):
    preferences = Settings(font_size=30, opacity=0.35, show_source=True)
    ui.update_settings(preferences)
    result = TranslationResult("<b>source & text</b>", "<script>literal text</script>", "en-zh", 1)
    ui.show_result(result)
    qapp.processEvents()
    assert ui.overlay.translation_label.textFormat() == Qt.TextFormat.PlainText
    assert ui.overlay.source_label.textFormat() == Qt.TextFormat.PlainText
    assert ui.overlay.translation_label.text() == result.translation
    assert ui.overlay.source_label.text() == result.source
    assert ui.overlay.translation_label.font().pointSize() == 30
    assert ui.overlay.settings.opacity == 0.35
    assert ui.overlay.source_label.isVisible()
    assert ui.overlay.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    assert ui.overlay.windowFlags() & Qt.WindowType.WindowTransparentForInput
    ui.set_hidden(True)
    assert ui.hidden and not ui.overlay.isVisible()
    ui.set_hidden(False)
    assert ui.overlay.isVisible()
    ui.clear_result()
    assert not ui.overlay.isVisible()
    assert not ui.overlay.translation_label.text()
    assert not ui.copy_action.isEnabled()


def test_long_result_has_visible_truncation_but_copy_remains_complete(ui, qapp):
    text = "This is a long translation paragraph. " * 1000
    result = TranslationResult("source", text, "en-zh", 1)
    ui.show_result(result)
    qapp.processEvents()
    assert ui.overlay.translation_label.text().endswith("…〔已截断〕")
    assert len(ui.overlay.translation_label.text()) < len(text)
    assert ui.overlay.height() <= 560
    ui._copy_translation()
    assert qapp.clipboard().text() == text


def test_dialogue_rows_render_and_copy_with_hard_line_breaks(ui, qapp):
    ui.update_settings(Settings(text_layout="lines", show_source=True))
    result = TranslationResult("Where are you?\nCome here.", "你在哪里?\n过来。", "en-zh", 1)
    ui.show_result(result)
    qapp.processEvents()
    assert ui.overlay.source_label.text() == result.source
    assert ui.overlay.translation_label.text() == result.translation
    assert ui.overlay.translation_label.text().splitlines() == ["你在哪里?", "过来。"]
    assert ui.overlay.translation_label.wordWrap()
    ui._copy_translation()
    assert qapp.clipboard().text() == result.translation
    ui.clear_result()
    assert not ui.overlay.translation_label.text()
    assert not ui.copy_action.isEnabled()


def test_many_dialogue_rows_mark_truncation_but_copy_all_rows(ui, qapp):
    ui.update_settings(Settings(text_layout="lines"))
    text = "\n".join(f"Dialogue message {index}." for index in range(150))
    ui.show_result(TranslationResult("source", text, "zh-en", 1))
    qapp.processEvents()
    shown = ui.overlay.translation_label.text()
    assert shown.endswith("…〔已截断〕")
    assert "\n" in shown
    assert len(shown) < len(text)
    ui._copy_translation()
    assert qapp.clipboard().text() == text


def test_unsafe_overlap_never_shows_subtitles_or_repeats_warning(ui, monkeypatch):
    notices = []
    monkeypatch.setattr(ui, "notify", lambda *args, **kwargs: notices.append((args, kwargs)))
    monkeypatch.setattr(ui.overlay, "reposition", lambda: None)
    ui.overlay.overlaps_capture = True
    ui.overlay.capture_excluded = False
    ui.show_result(TranslationResult("source", "translation", "en-zh", 1))
    assert not ui.overlay.isVisible()
    assert len(notices) == 1
    ui.set_hidden(False)
    assert not ui.overlay.isVisible()
    assert len(notices) == 1
    assert ui.copy_action.isEnabled()


def test_settings_roundtrip_covers_auto_start_and_cache(qapp):
    dialog = SettingsDialog(Settings())
    dialog.auto_start.setChecked(True)
    dialog.cache.setChecked(True)
    dialog.font_size.setValue(28)
    dialog.opacity.setValue(60)
    dialog.cpu_threads.setValue(3)
    dialog.direction.setCurrentIndex(dialog.direction.findData("zh-en"))
    result = dialog.values()
    assert result.auto_start and result.cache_enabled
    assert result.font_size == 28 and result.opacity == 0.60
    assert result.cpu_threads == 3 and result.direction == "zh-en"
    dialog.close()


def test_cursor_read_failure_cancels_selection_instead_of_trapping_user(ui, monkeypatch):
    from screen_translator.ui import region_selector
    notices = []
    monkeypatch.setattr(ui, "notify", lambda *args, **kwargs: notices.append(args))
    monkeypatch.setattr(region_selector, "cursor_position", lambda: (0, 0))
    ui.select_region()
    selector = ui._selector
    assert selector is not None and selector.windows

    def denied():
        raise OSError(5, "cursor unavailable")

    monkeypatch.setattr(region_selector, "cursor_position", denied)
    assert selector.windows[0]._cursor_or_cancel() is None
    assert selector._closed and ui._selector is None
    assert notices and "cursor unavailable" in notices[0][1]
