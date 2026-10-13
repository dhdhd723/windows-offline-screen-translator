"""The dedicated diagnostic must not register inputs or initialize models."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from screen_translator.ui.startup_diagnostics import run_startup_self_test


def test_real_offscreen_card_moves_stops_and_deletes_without_loading_models():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    report = run_startup_self_test()
    assert report["passed"], report
    assert report["presentation_ms"] == 2000
    assert len(report["cases"]) == 3
    for case in report["cases"]:
        assert case["finished_count"] == 1 and case["destroyed"]
        assert case["active_card_timers_after_finish"] == 0
        assert case["running_card_animations_after_finish"] == 0
        assert case["precise_expiry_timer"]
        if case["early_close"]:
            assert case["settings_open_count"] == 0
            assert case["completed_count"] == 0
            assert case["elapsed_ms"] < 1000
            assert "completed_elapsed_ms" not in case
        else:
            assert case["settings_open_count"] == 1
            assert case["settings_visible_at_open"]
            assert case["settings_opened_after_card_hidden"]
            assert case["settings_open_elapsed_ms"] >= case["completed_elapsed_ms"]
            assert case["completed_count"] == 1
            assert case["finished_before_completed"]
            assert not case["visible_after_completed"]
            assert 1900 <= case["elapsed_ms"] <= 3000
            assert 1900 <= case["completed_elapsed_ms"] <= 3000
    assert report["qt_platform"] == "offscreen"
    assert not report["desktop_captured"] and not report["global_hotkeys_registered"]
    assert not report["inference_runtime_loaded"] and report["network_attempts"] == []
    assert not report["native_focus_tested"] and not report["game_tested"] and not report["nvidia_tested"]
