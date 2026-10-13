"""Dialog edits merge into live application state, without native desktop input."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from screen_translator.application import hotkey_status
from screen_translator.contracts import Region, Settings
from screen_translator.ui.settings_window import SettingsDialog, merge_settings_changes


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


def test_open_dialog_does_not_restore_old_region_or_consent(qapp):
    original = Settings(region=Region(10, 20, 100, 40), runtime_terms_version="old")
    dialog = SettingsDialog(original)
    dialog.font_size.setValue(30)
    latest = Settings.from_dict(original.to_dict())
    latest.region = Region(400, 500, 250, 60)
    latest.overlay_position = (800, 700)
    latest.runtime_terms_version = "new-consent"
    result = merge_settings_changes(latest, dialog.editable_changes())
    assert result.font_size == 30
    assert result.region == latest.region
    assert result.overlay_position == latest.overlay_position
    assert result.runtime_terms_version == "new-consent"
    assert latest.font_size == 22
    dialog.close()


def test_unchanged_shortcuts_preserve_effective_fallback(qapp):
    original = Settings()
    dialog = SettingsDialog(original)
    dialog.opacity.setValue(55)
    latest = Settings.from_dict(original.to_dict())
    latest.hotkeys["select"] = "Ctrl+Shift+R"
    result = merge_settings_changes(latest, dialog.editable_changes())
    assert result.hotkeys["select"] == "Ctrl+Shift+R"
    assert "hotkeys" not in dialog.editable_changes()
    dialog.close()


def test_only_edited_shortcut_action_replaces_latest_binding(qapp):
    original = Settings()
    dialog = SettingsDialog(original)
    dialog.hotkeys["clear"].setText("Ctrl+Shift+C")
    latest = Settings.from_dict(original.to_dict())
    latest.hotkeys["select"] = "Ctrl+Shift+R"
    latest.hotkeys["toggle"] = "Ctrl+Shift+T"
    changes = dialog.editable_changes()
    assert changes == {"hotkeys": {"clear": "Ctrl+Shift+C"}}
    result = merge_settings_changes(latest, changes)
    assert result.hotkeys == {"select": "Ctrl+Shift+R", "toggle": "Ctrl+Shift+T",
                              "clear": "Ctrl+Shift+C"}
    dialog.close()


def test_unchanged_fields_preserve_concurrent_preferences(qapp):
    dialog = SettingsDialog(Settings())
    dialog.font_size.setValue(28)
    latest = Settings(direction="en-zh", opacity=0.4, capture_fps=1, idle_fps=1,
                      recording_compatibility=False)
    result = merge_settings_changes(latest, dialog.editable_changes())
    assert result.direction == "en-zh" and result.opacity == 0.4
    assert result.capture_fps == 1 and result.idle_fps == 1
    assert not result.recording_compatibility
    dialog.close()


def test_recording_compatibility_is_explicit_edit(qapp):
    dialog = SettingsDialog(Settings())
    assert dialog.recording_compatibility.isChecked()
    dialog.recording_compatibility.setChecked(False)
    changes = dialog.editable_changes()
    assert changes == {"recording_compatibility": False}
    assert not merge_settings_changes(Settings(), changes).recording_compatibility
    dialog.close()


@pytest.mark.parametrize("layout", ["continuous", "lines"])
def test_text_layout_control_displays_and_returns_saved_mode(qapp, layout):
    dialog = SettingsDialog(Settings(text_layout=layout))
    assert dialog.text_layout.currentData() == layout
    assert dialog.values().text_layout == layout
    assert dialog.editable_changes() == {}
    assert "Roblox" in dialog.text_layout.itemText(dialog.text_layout.findData("lines"))
    dialog.close()


def test_text_layout_is_explicit_edit_and_keeps_latest_application_state(qapp):
    dialog = SettingsDialog(Settings())
    dialog.text_layout.setCurrentIndex(dialog.text_layout.findData("lines"))
    changes = dialog.editable_changes()
    assert changes == {"text_layout": "lines"}
    latest = Settings(region=Region(200, 100, 300, 60), overlay_position=(100, 400),
                      runtime_terms_version="existing", direction="en-zh")
    result = merge_settings_changes(latest, changes)
    assert result.text_layout == "lines" and latest.text_layout == "continuous"
    assert result.region == latest.region and result.overlay_position == latest.overlay_position
    assert result.runtime_terms_version == "existing" and result.direction == "en-zh"
    dialog.close()


def test_unedited_text_layout_preserves_concurrent_dialog_change(qapp):
    dialog = SettingsDialog(Settings())
    dialog.font_size.setValue(28)
    result = merge_settings_changes(Settings(text_layout="lines"), dialog.editable_changes())
    assert result.text_layout == "lines" and result.font_size == 28
    dialog.close()


def test_invalid_text_layout_patch_uses_compatible_default():
    assert merge_settings_changes(Settings(text_layout="lines"),
                                  {"text_layout": "unknown"}).text_layout == "continuous"


@pytest.mark.parametrize("changes", [
    {"region": {"x": 1}}, {"runtime_terms_version": "replacement"},
    {"overlay_position": (1, 2)}, {"hotkeys": {"unknown": "Alt+X"}},
])
def test_noneditable_fields_cannot_enter_dialog_patch(changes):
    with pytest.raises(ValueError):
        merge_settings_changes(Settings(), changes)


def test_unavailable_shortcut_status_survives_saved_and_ready_messages():
    configured = Settings().hotkeys
    effective = {"select": configured["select"], "clear": configured["clear"]}
    for message in ("设置已保存", "已就绪", "监控中", "持续翻译已停止"):
        status = hotkey_status(message, configured, effective)
        assert status.startswith("快捷键不可用：启停(Alt+T)")
        assert "托盘" in status and message in status
    assert hotkey_status("已就绪", configured, configured) == "已就绪"


def test_idle_rate_remains_bounded_after_concurrent_merge():
    result = merge_settings_changes(Settings(capture_fps=1, idle_fps=1), {"idle_fps": 3})
    assert result.idle_fps == 1


def test_derived_idle_clamp_does_not_overwrite_live_unedited_idle_rate(qapp):
    dialog = SettingsDialog(Settings())
    dialog.capture_fps.setValue(1)
    changes = dialog.editable_changes()
    assert changes == {"capture_fps": 1}
    result = merge_settings_changes(Settings(idle_fps=0.5), changes)
    assert result.capture_fps == 1 and result.idle_fps == 0.5
    dialog.close()
