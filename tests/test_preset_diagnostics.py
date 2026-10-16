"""Run the same owned-widget diagnostics shipped in the exe."""
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
from PySide6.QtWidgets import QApplication
from screen_translator.ui.preset_diagnostics import run_preset_self_test


def test_frozen_compatible_preset_diagnostics_use_only_temporary_files():
    app=QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    report=run_preset_self_test()
    assert report["passed"] and len(report["cases"])==7
    assert not report["private_user_settings_read"]
    assert not report["global_hotkeys_registered"] and not report["desktop_captured"]
    assert report["temporary_files_only"] and not report["actual_game_tested"]
