"""Own preset widgets and temporary JSON only; no native capture or real config."""
from __future__ import annotations

from pathlib import Path
import tempfile

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QDialog

from screen_translator.contracts import Region, Settings
from screen_translator.core.scene_presets import PresetError, ScenePreset, restore_preset
from screen_translator.storage.presets import PresetStore
from screen_translator.ui.preset_dialog import PresetDialog


def run_preset_self_test() -> dict:
    app = QApplication.instance()
    if app is None:
        raise RuntimeError("A diagnostic QApplication is required")
    cases = []
    with tempfile.TemporaryDirectory(prefix="screen-translator-preset-check-") as folder:
        store = PresetStore(Path(folder) / "presets.json")
        current = Settings(runtime_terms_version="synthetic-current-consent", auto_start=True,
                           region=Region(20, 20, 160, 80), overlay_position=(30, 130))
        saved = Settings(direction="en-zh", text_layout="lines", font_size=32,
                         region=Region(200, 100, 240, 80), overlay_position=(210, 190))
        store.save("示例聊天", saved)
        store.save("示例阅读", Settings(font_size=36), False)
        store.rename("示例阅读", "阅读场景")
        rows = store.list_presets()
        cases.append({"name": "save_reload_rename", "passed":
                      [row.name for row in rows] == ["示例聊天", "阅读场景"]
                      and rows[0].values["text_layout"] == "lines"})
        restored, reset = restore_preset(current, rows[0], lambda region: True)
        cases.append({"name": "restore_scene_keep_global", "passed":
                      not reset and restored.font_size == 32 and restored.region == saved.region
                      and restored.runtime_terms_version == current.runtime_terms_version
                      and restored.auto_start == current.auto_start})
        restored, reset = restore_preset(current, rows[1], lambda region: False)
        cases.append({"name": "optional_region_keeps_current", "passed":
                      not reset and restored.region == current.region and restored.font_size == 36})
        restored, reset = restore_preset(current, rows[0], lambda region: False)
        cases.append({"name": "invalid_saved_region_requires_reselect", "passed":
                      reset and restored.region is None and restored.overlay_position is None})
        calls = []
        dialog = PresetDialog(store, lambda: current,
                              lambda row: (calls.append(row) or True, "synthetic applied"))
        try:
            dialog.show()
            app.processEvents()
            painted = dialog.grab()
            dialog.apply_button.click()
            cases.append({"name": "real_widget_apply_button", "passed":
                          not painted.isNull() and len(calls) == 1
                          and dialog.result() == QDialog.DialogCode.Accepted})
        finally:
            dialog.close()
            dialog.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        store.delete("示例聊天")
        cases.append({"name": "delete_keeps_other_presets", "passed":
                      [row.name for row in store.list_presets()] == ["阅读场景"]})
        damaged = Path(folder) / "damaged-presets.json"
        damaged.write_bytes(b"{")
        rejected = False
        try:
            PresetStore(damaged).save("test", Settings())
        except PresetError:
            rejected = True
        cases.append({"name": "corrupt_file_not_overwritten", "passed":
                      rejected and damaged.read_bytes() == b"{"})
    return {"passed": all(row["passed"] for row in cases), "cases": cases,
            "private_user_settings_read": False, "desktop_captured": False,
            "global_hotkeys_registered": False, "native_focus_tested": False,
            "actual_game_tested": False, "temporary_files_only": True}
