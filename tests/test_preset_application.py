"""The real application callback, with fake native UI/capture only."""
from __future__ import annotations

import pytest

from screen_translator import application
from screen_translator.contracts import Region, Settings
from screen_translator.core.scene_presets import ScenePreset
from screen_translator.platform.windows import monitors
from test_application_capture_recovery import fake_desktop  # noqa: F401


@pytest.mark.parametrize("include_region", [False, True])
def test_real_apply_callback_persists_pauses_clears_and_resumes_on_toggle(fake_desktop,include_region):
    def scenario(tick):
        ui,pipeline,hotkeys=fake_desktop.ui,fake_desktop.pipeline,fake_desktop.hotkeys
        current=ui.preset_current()
        chosen=Settings(direction="en-zh",font_size=36,text_layout="lines",
                        region=Region(100,100,320,100),runtime_terms_version="should-not-copy",
                        auto_start=True,startup_animation=True,
                        hotkeys={"select":"Ctrl+Shift+R","toggle":"Ctrl+Shift+T","clear":"Ctrl+Shift+C"})
        preset=ScenePreset.capture("组队",chosen,include_region)
        success,message=ui.preset_apply(preset)
        assert success and "暂停" in message and "Ctrl+Shift+T" in message
        assert not pipeline.is_running and pipeline.clears==1 and ui.clears>=1
        assert hotkeys.monitoring is False
        assert pipeline.settings.font_size==ui.settings.font_size==36
        live=ui.preset_current()
        assert live.runtime_terms_version==current.runtime_terms_version
        assert live.auto_start==current.auto_start and live.startup_animation==current.startup_animation
        assert live.region==(chosen.region if include_region else current.region)
        assert fake_desktop.saved_settings[-1].to_dict()==live.to_dict()
        assert hotkeys.effective_hotkeys["toggle"]=="Ctrl+Shift+T"
        ui.toggle_requested.emit()
        assert pipeline.is_running and pipeline.started_regions[-1]==live.region
    fake_desktop.scenario=scenario
    assert application.main([])==0


def test_failed_config_write_preserves_running_session_and_live_settings(fake_desktop):
    def scenario(tick):
        ui,pipeline=fake_desktop.ui,fake_desktop.pipeline
        before=ui.preset_current().to_dict()
        fake_desktop.save_error=PermissionError("synthetic denied")
        success,message=ui.preset_apply(ScenePreset.capture("阅读",Settings(font_size=40)))
        assert not success and "保持不变" in message
        assert pipeline.is_running and pipeline.stops==0 and pipeline.clears==0
        assert ui.preset_current().to_dict()==before and fake_desktop.saved_settings==[]
    fake_desktop.scenario=scenario
    assert application.main([])==0


def test_invalid_preset_region_clears_previous_and_requires_reselection(fake_desktop,monkeypatch):
    monkeypatch.setattr(monitors,"validate_region",lambda region: region is not None and region.monitor_id!="missing")
    def scenario(tick):
        ui,pipeline=fake_desktop.ui,fake_desktop.pipeline
        saved=Settings(region=Region(100,100,80,60,"missing"),overlay_position=(100,170))
        success,message=ui.preset_apply(ScenePreset.capture("旧显示器",saved))
        assert success and "重新框选" in message
        assert ui.preset_current().region is None and ui.preset_current().overlay_position is None
        assert not pipeline.is_running
    fake_desktop.scenario=scenario
    assert application.main([])==0
