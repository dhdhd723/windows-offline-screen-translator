"""Own Qt widgets only, isolated files and no desktop input or translation model."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QInputDialog, QMessageBox

from screen_translator.contracts import Region, Settings
from screen_translator.storage.presets import PresetStore
from screen_translator.ui.main import MainUI
from screen_translator.ui.preset_dialog import PresetDialog
from screen_translator.ui.settings_window import SettingsDialog


@pytest.fixture(scope="module")
def qapp():
    app=QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


@pytest.fixture
def manager(qapp,tmp_path):
    current=Settings(region=Region(10,20,160,80),font_size=30)
    calls=[]
    dialog=PresetDialog(PresetStore(tmp_path/"presets.json"),lambda:current,
                        lambda row:(calls.append(row) or True,"applied"))
    yield dialog,current,calls
    dialog.close()


def test_empty_manager_has_only_creation_enabled_and_does_not_write(manager):
    dialog,_,_=manager
    assert dialog.save_button.isEnabled() and dialog.list.count()==0
    assert not any(button.isEnabled() for button in (dialog.apply_button,dialog.update_button,dialog.rename_button,dialog.delete_button))
    assert not dialog.store.path.exists()


def test_save_uses_latest_live_settings_not_open_time_snapshot(manager,monkeypatch):
    dialog,current,calls=manager
    current.font_size=42
    dialog.include_region.setChecked(False)
    monkeypatch.setattr(QInputDialog,"getText",lambda *args,**kwargs:("阅读",True))
    dialog.save_button.click()
    assert dialog.list.count()==1 and dialog.list.currentItem().text()=="阅读"
    saved=dialog.store.list_presets()[0]
    assert saved.values["font_size"]==42 and not saved.include_region
    assert "保留当前区域" in dialog.summary.text()
    assert calls==[] and current.font_size==42


def test_cancel_save_writes_nothing(manager,monkeypatch):
    dialog,_,_=manager
    monkeypatch.setattr(QInputDialog,"getText",lambda *args,**kwargs:("",False))
    dialog.save_button.click()
    assert not dialog.store.path.exists()


def test_update_rename_delete_require_confirmation_and_preserve_current(manager,monkeypatch):
    dialog,current,calls=manager
    dialog.store.save("游戏",Settings(font_size=22))
    dialog.refresh()
    monkeypatch.setattr(QMessageBox,"question",lambda *args,**kwargs:QMessageBox.StandardButton.No)
    dialog.update_button.click()
    dialog.delete_button.click()
    assert dialog.store.list_presets()[0].values["font_size"]==22
    monkeypatch.setattr(QMessageBox,"question",lambda *args,**kwargs:QMessageBox.StandardButton.Yes)
    dialog.update_button.click()
    assert dialog.store.list_presets()[0].values["font_size"]==30
    monkeypatch.setattr(QInputDialog,"getText",lambda *args,**kwargs:("Roblox 聊天",True))
    dialog.rename_button.click()
    assert dialog.list.currentItem().text()=="Roblox 聊天"
    dialog.delete_button.click()
    assert dialog.store.list_presets()==[] and calls==[] and current.font_size==30


def test_duplicate_and_bad_name_are_inline_errors_not_overwrites(manager,monkeypatch):
    dialog,_,_=manager
    dialog.store.save("游戏",Settings())
    dialog.refresh()
    before=dialog.store.path.read_bytes()
    for name in ("游戏","", "bad\nname"):
        monkeypatch.setattr(QInputDialog,"getText",lambda *args,**kwargs:(name,True))
        dialog.save_button.click()
        assert dialog.status.text() and dialog.store.path.read_bytes()==before


def test_apply_rereads_updated_preset_from_disk(manager):
    dialog,_,calls=manager
    dialog.store.save("游戏",Settings(font_size=22))
    dialog.refresh()
    dialog.store.save("游戏",Settings(font_size=40),replace=True)
    dialog.apply_button.click()
    assert len(calls)==1 and calls[0].values["font_size"]==40
    assert dialog.result()==QDialog.DialogCode.Accepted


def test_deleted_preset_is_not_applied_from_stale_widget(manager):
    dialog,_,calls=manager
    dialog.store.save("游戏",Settings())
    dialog.refresh()
    dialog.store.delete("游戏")
    dialog.apply_button.click()
    assert calls==[] and "不存在" in dialog.status.text()


def test_failed_application_keeps_manager_open(qapp,tmp_path):
    store=PresetStore(tmp_path/"presets.json")
    store.save("游戏",Settings())
    dialog=PresetDialog(store,Settings,lambda row:(False,"无法保存，原设置保留"))
    try:
        dialog.apply_button.click()
        assert dialog.result()!=QDialog.DialogCode.Accepted and "原设置保留" in dialog.status.text()
    finally:
        dialog.close()


def test_corrupt_file_disables_write_and_refresh_can_recover(manager):
    dialog,_,_=manager
    dialog.store.path.write_bytes(b"{")
    dialog.refresh()
    assert not dialog.save_button.isEnabled() and not dialog.apply_button.isEnabled()
    assert "未覆盖" in dialog.status.text()
    assert dialog.store.path.read_bytes()==b"{"


def test_store_write_error_is_reported_without_changing_current(manager,monkeypatch):
    dialog,current,_=manager
    monkeypatch.setattr(QInputDialog,"getText",lambda *args,**kwargs:("游戏",True))
    def fail(*args,**kwargs):
        raise PermissionError("synthetic denied")
    monkeypatch.setattr(dialog.store,"save",fail)
    dialog.save_button.click()
    assert "无法读写" in dialog.status.text() and current.font_size==30


def test_settings_entry_does_not_change_editable_setting_delta(qapp):
    dialog=SettingsDialog(Settings())
    try:
        events=[]
        dialog.manage_presets_requested.connect(lambda:events.append("open"))
        dialog.manage_presets_button.click()
        assert events==["open"] and dialog.editable_changes()=={}
    finally:
        dialog.close()


def test_main_ui_opens_one_manager_and_close_releases_it(qapp,tmp_path):
    ui=MainUI(Settings())
    try:
        ui.configure_presets(PresetStore(tmp_path/"presets.json"),Settings,lambda row:(True,"done"))
        ui.presets_action.trigger()
        dialog=ui._preset_dialog
        assert dialog is not None
        ui.presets_action.trigger()
        assert ui._preset_dialog is dialog
        ui.close()
        assert ui._preset_dialog is None
    finally:
        if not ui.is_closed:
            ui.close()


def test_unsaved_settings_are_not_discarded_by_opening_presets(qapp,tmp_path,monkeypatch):
    ui=MainUI(Settings())
    try:
        ui.configure_presets(PresetStore(tmp_path/"presets.json"),Settings,lambda row:(True,"done"))
        ui.open_settings()
        dialog=ui._settings_dialog
        dialog.font_size.setValue(40)
        notices=[]
        monkeypatch.setattr(QMessageBox,"information",lambda *args,**kwargs:notices.append(args[2]))
        dialog.manage_presets_button.click()
        assert ui._settings_dialog is dialog and ui._preset_dialog is None
        assert dialog.font_size.value()==40 and notices
    finally:
        ui.close()


def test_clean_settings_handoff_cancels_old_dialog_without_saving(qapp,tmp_path):
    ui=MainUI(Settings())
    try:
        updates=[]
        ui.settings_changed.connect(updates.append)
        ui.configure_presets(PresetStore(tmp_path/"presets.json"),Settings,lambda row:(True,"done"))
        ui.open_settings()
        ui._settings_dialog.manage_presets_button.click()
        assert ui._settings_dialog is None and ui._preset_dialog is not None and updates==[]
    finally:
        ui.close()
