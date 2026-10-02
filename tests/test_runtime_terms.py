"""Consent tests are synthetic; no native input registration or capture occurs."""
from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QDialog

from screen_translator.contracts import Settings
from screen_translator import runtime_terms
from screen_translator.runtime_terms import (TERMS_REVISION, authorize_runtime_terms,
                                              load_runtime_terms)
from screen_translator.storage.settings import SettingsStore
from screen_translator.ui.runtime_terms_dialog import RuntimeTermsDialog


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    yield app


def _write_terms(root: Path, text: str = "Synthetic runtime terms\n<b>Plain text only</b>\n",
                 *, frozen: bool = False) -> Path:
    relative = ("LICENSES/upstream/microsoft-runtime" if frozen else
                "packaging/extra-notices/microsoft-runtime")
    path = root / relative / "final-user-terms.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize("frozen", [False, True])
def test_terms_source_and_portable_locations_are_explicit(tmp_path, frozen):
    path = _write_terms(tmp_path, frozen=frozen)
    terms = load_runtime_terms(tmp_path, frozen=frozen)
    assert terms.path == path
    assert terms.version.startswith(TERMS_REVISION + ":")
    assert "<b>Plain text only</b>" in terms.text


def test_frozen_install_does_not_fall_back_to_a_source_document(tmp_path):
    _write_terms(tmp_path)
    with pytest.raises(FileNotFoundError):
        load_runtime_terms(tmp_path, frozen=True)


@pytest.mark.parametrize("content", [b"", b" \r\n", b"\xff", b"a" * 262145],
                         ids=["empty", "whitespace", "non-utf8", "too-large"])
def test_missing_or_invalid_document_fails_closed_even_with_explicit_accept(tmp_path, content):
    path = _write_terms(tmp_path)
    path.write_bytes(content)
    settings = Settings()
    store = SettingsStore(tmp_path / "user/config.json")
    result = authorize_runtime_terms(settings, store, explicit_accept=True, root=tmp_path,
                                     frozen=False)
    assert not result.accepted and result.failure == "document"
    assert settings.runtime_terms_version == ""
    assert not store.path.exists()


def test_missing_document_cannot_be_bypassed_by_a_saved_acceptance(tmp_path):
    settings = Settings(runtime_terms_version="previous-version")
    result = authorize_runtime_terms(settings, SettingsStore(tmp_path / "config.json"),
                                     explicit_accept=True, root=tmp_path, frozen=False)
    assert not result.accepted and result.failure == "document"


def test_old_configuration_defaults_to_no_acceptance_and_invalid_version_is_rejected(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"font_size": 26}', encoding="utf-8")
    store = SettingsStore(path)
    assert store.load().runtime_terms_version == ""
    path.write_text('{"runtime_terms_version": true}', encoding="utf-8")
    assert store.load().runtime_terms_version == ""
    assert store.last_error == "Invalid runtime terms acceptance version"


def test_rejection_and_noninteractive_run_do_not_write_consent(tmp_path):
    _write_terms(tmp_path)
    settings = Settings()
    store = SettingsStore(tmp_path / "user/config.json")
    decisions = []
    for prompt in (None, lambda terms: decisions.append(terms.version) or False):
        result = authorize_runtime_terms(settings, store, prompt=prompt, root=tmp_path, frozen=False)
        assert not result.accepted and result.failure == "declined"
        assert settings.runtime_terms_version == ""
        assert not store.path.exists()
    assert len(decisions) == 1


@pytest.mark.parametrize("explicit", [False, True])
def test_explicit_choice_persists_exact_version_only_in_user_configuration(tmp_path, explicit):
    terms_path = _write_terms(tmp_path)
    original = terms_path.read_bytes()
    store = SettingsStore(tmp_path / "user/config.json")
    settings = Settings(font_size=26, cache_enabled=True)
    result = authorize_runtime_terms(settings, store, explicit_accept=explicit,
                                     prompt=None if explicit else lambda terms: True,
                                     root=tmp_path, frozen=False)
    assert result.accepted
    assert result.acceptance == ("explicit-diagnostic" if explicit else "dialog")
    loaded = store.load()
    assert loaded.runtime_terms_version == result.version
    assert loaded.font_size == 26 and loaded.cache_enabled
    assert terms_path.read_bytes() == original
    repeated = authorize_runtime_terms(loaded, store,
                                       prompt=lambda terms: pytest.fail("Already accepted terms prompted again"),
                                       root=tmp_path, frozen=False)
    assert repeated.accepted and repeated.acceptance == "saved"


def test_changed_terms_require_a_fresh_choice_even_without_revision_label_change(tmp_path):
    path = _write_terms(tmp_path)
    store = SettingsStore(tmp_path / "config.json")
    settings = Settings()
    first = authorize_runtime_terms(settings, store, explicit_accept=True, root=tmp_path, frozen=False)
    path.write_text("Updated synthetic terms", encoding="utf-8")
    next_result = authorize_runtime_terms(settings, store, root=tmp_path, frozen=False)
    assert not next_result.accepted
    assert first.version != next_result.version
    assert settings.runtime_terms_version == first.version


def test_failed_consent_save_restores_old_setting_and_does_not_start(tmp_path, monkeypatch):
    _write_terms(tmp_path)
    store = SettingsStore(tmp_path / "config.json")
    settings = Settings(runtime_terms_version="old")

    def denied(value):
        raise PermissionError("Synthetic unwritable user directory")

    monkeypatch.setattr(store, "save", denied)
    result = authorize_runtime_terms(settings, store, explicit_accept=True, root=tmp_path, frozen=False)
    assert not result.accepted and result.failure == "save"
    assert settings.runtime_terms_version == "old"


def test_dialog_has_plain_readable_document_and_no_default_agreement(qapp, tmp_path):
    _write_terms(tmp_path)
    terms = load_runtime_terms(tmp_path, frozen=False)
    dialog = RuntimeTermsDialog(terms)
    assert dialog.document.isReadOnly()
    assert dialog.document.toPlainText() == terms.text.replace("\r\n", "\n")
    assert not dialog.confirmation.isChecked()
    assert not dialog.accept_button.isEnabled()
    dialog._accept_if_confirmed()
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert "<b>" in dialog.document.toPlainText()
    dialog.confirmation.setChecked(True)
    assert dialog.accept_button.isEnabled()
    dialog._accept_if_confirmed()
    assert dialog.result() == QDialog.DialogCode.Accepted
    dialog.close()


def _prepare_main(monkeypatch, tmp_path):
    from screen_translator import application
    monkeypatch.setattr(application, "configure_logging", lambda: None)
    monkeypatch.setattr(runtime_terms, "install_root", lambda: tmp_path)
    monkeypatch.setenv("SCREEN_TRANSLATOR_DATA", str(tmp_path / "user"))
    return application


def test_cli_cannot_silently_accept_terms_for_normal_gui_startup(monkeypatch, tmp_path):
    application = _prepare_main(monkeypatch, tmp_path)
    with pytest.raises(SystemExit) as error:
        application.main(["--accept-runtime-terms"])
    assert error.value.code == 2
    assert not (tmp_path / "user/config.json").exists()


@pytest.mark.parametrize("diagnostic", ["--self-test", "--smoke-test"])
def test_diagnostic_without_consent_stops_before_qt_or_native_integration(monkeypatch, tmp_path, diagnostic):
    application = _prepare_main(monkeypatch, tmp_path)
    _write_terms(tmp_path)
    monkeypatch.setattr("PySide6.QtWidgets.QApplication",
                        lambda *args: pytest.fail("Qt initialized before diagnostic consent"))
    report_path = tmp_path / "report.json"
    assert application.main([diagnostic, "--report", str(report_path)]) == 3
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert not report["passed"]
    assert report["failure"] == "runtime_terms_declined"
    assert report["required_runtime_terms_version"].startswith(TERMS_REVISION)
    assert not (tmp_path / "user/config.json").exists()


def test_authorized_synthetic_diagnostic_records_version_without_real_inference(monkeypatch, tmp_path, qapp):
    application = _prepare_main(monkeypatch, tmp_path)
    _write_terms(tmp_path)
    monkeypatch.setattr("PySide6.QtWidgets.QApplication", lambda *args: qapp)
    monkeypatch.setattr("screen_translator.platform.windows.dpi.enable_dpi_awareness", lambda: None)
    monkeypatch.setattr("screen_translator.diagnostics.run_self_test", lambda: {"passed": True})
    report_path = tmp_path / "report.json"
    assert application.main(["--self-test", "--accept-runtime-terms", "--report", str(report_path)]) == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["runtime_terms_acceptance"] == "explicit-diagnostic"
    settings = SettingsStore(tmp_path / "user/config.json").load()
    assert settings.runtime_terms_version == report["runtime_terms_version"]


def test_gui_rejection_occurs_before_hotkeys_and_capture_initialization(monkeypatch, tmp_path, qapp):
    application = _prepare_main(monkeypatch, tmp_path)
    _write_terms(tmp_path)
    monkeypatch.setattr("PySide6.QtWidgets.QApplication", lambda *args: qapp)
    monkeypatch.setattr("screen_translator.platform.windows.dpi.enable_dpi_awareness", lambda: None)
    monkeypatch.setattr("screen_translator.ui.runtime_terms_dialog.prompt_runtime_terms", lambda terms: False)
    monkeypatch.setattr("screen_translator.platform.windows.hotkeys.WindowsHotkeys",
                        lambda: pytest.fail("Hotkeys initialized after rejection"))
    monkeypatch.setattr("screen_translator.core.pipeline.Pipeline",
                        lambda *args: pytest.fail("Pipeline initialized after rejection"))
    assert application.main([]) == 3
    assert not (tmp_path / "user/config.json").exists()
