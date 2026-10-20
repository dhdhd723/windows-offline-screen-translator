"""Chat diagnostic probes use generated fixtures/fakes, never user screens."""
from __future__ import annotations

import json
import socket

import numpy as np
import pytest

from screen_translator import chat_diagnostics as diagnostic
from screen_translator.contracts import OCRResult
from screen_translator.inference import ModelFilesError


class FakeTranslator:
    formats_simplified_output = True

    def __init__(self, **kwargs):
        self.options = kwargs
        self.mode = None
        self.direction = None
        self.calls = []
        self.closes = 0

    def configure_chat_mode(self, mode):
        self.mode = mode

    def configure_direction(self, direction):
        self.direction = direction

    def model_id(self, direction):
        return "synthetic-fast-" + direction

    def translate(self, text, direction):
        self.calls.append((text, direction))
        return "你好，你怎么样？" if text.startswith("Hello") else "请等我。"

    def close(self):
        self.closes += 1


class FakeOCR:
    def __init__(self, **kwargs):
        self.options = kwargs

    def recognize(self, image):
        assert isinstance(image, np.ndarray)
        return OCRResult("\n".join(diagnostic.FIXTURE_ROWS), confidence=.99)


def run_fake(tmp_path, *, engine_class=FakeTranslator, ocr_class=FakeOCR):
    engines = []

    def factory(**kwargs):
        item = engine_class(**kwargs)
        engines.append(item)
        return item

    report = diagnostic.run_chat_self_test(tmp_path / "models", translator_factory=factory,
        ocr_factory=ocr_class, image_factory=lambda: np.zeros((220, 1080, 3), dtype=np.uint8))
    return report, engines[0]


def test_fake_runtime_ocr_plan_preserves_nicknames_and_closes_once(tmp_path):
    report, engine = run_fake(tmp_path)
    assert report["passed"] and engine.closes == 1
    assert engine.mode == "fast" and engine.direction == "en-zh"
    assert engine.options == {"model_dir": tmp_path / "models", "cpu_threads": 2}
    assert [call[0] for call in engine.calls] == ["Hello how are you?", "Please wait for me."]
    assert report["model_id"] == "synthetic-fast-en-zh"
    assert report["tests"][0]["translation"] == diagnostic.COMPOSED_EXPECTED
    assert report["tests"][0]["model_called"] is False
    assert report["tests"][2]["translation"] == "Alice: 你好，你怎么样？\nBob: 请等我。"
    assert report["cleanup"] == {"attempted": True, "passed": True}
    assert report["network_guard"]["blocked_attempts"] == []
    assert report["network_attempts"] == [] and not report["network_guard"]["loopback_allowed"]
    assert report["ocr_ms"] >= 0 and report["translation_ms_cold"] >= 0 and report["total_ms"] >= 0
    assert not any(report[key] for key in ("desktop_captured", "global_hotkeys_registered", "tray_created",
        "private_screenshot_read", "synthetic_image_saved", "actual_game_tested", "semantic_quality_verified",
        "os_network_audited"))
    assert list(tmp_path.iterdir()) == []


def test_synthetic_fixture_is_only_an_in_memory_image():
    image = diagnostic.synthetic_chat_image()
    assert image.shape == (220, 1080, 3) and image.dtype == np.uint8
    assert image.min() == 32 and image.max() == 255
    assert np.any(image[40:110] > 32) and np.any(image[120:190] > 32)


@pytest.mark.parametrize("bad_output", ["", " ", "hello", "<unk>", "你好 <unk>", "你好 <|end|>", "請等我。"])
def test_invalid_empty_special_english_or_traditional_output_fails_and_still_closes(tmp_path, bad_output):
    class BadOutput(FakeTranslator):
        def translate(self, *args, **kwargs):
            return bad_output
    report, engine = run_fake(tmp_path, engine_class=BadOutput)
    assert not report["passed"] and engine.closes == 1
    assert report["cleanup"]["passed"]


def test_ocr_mismatch_does_not_translate_or_hide_failure(tmp_path):
    class IncorrectOCR(FakeOCR):
        def recognize(self, image):
            return OCRResult("wrong fixture")
    report, engine = run_fake(tmp_path, ocr_class=IncorrectOCR)
    assert not report["passed"] and report["failure"] == "synthetic_ocr_mismatch"
    assert engine.calls == [] and engine.closes == 1


def test_missing_bundled_model_is_clear_failure_without_paths_or_automatic_download(tmp_path):
    class MissingPackage(FakeTranslator):
        def translate(self, *args, **kwargs):
            raise ModelFilesError("Do not echo sensitive internal path")
    report, engine = run_fake(tmp_path, engine_class=MissingPackage)
    assert not report["passed"] and report["failure"] == "translation_models_missing_or_invalid"
    assert "不会自动下载" in report["detail"]
    assert "sensitive" not in json.dumps(report) and engine.closes == 1


def test_exception_during_native_translation_closes_engine_and_reports_type_only(tmp_path):
    class NativeFailure(FakeTranslator):
        def translate(self, *args, **kwargs):
            raise OSError("private native detail")
    report, engine = run_fake(tmp_path, engine_class=NativeFailure)
    assert not report["passed"] and report["failure_stage"] == "translation"
    assert report["error_type"] == "OSError" and engine.closes == 1
    assert "private native detail" not in json.dumps(report)


def test_cleanup_failure_prevents_a_successful_diagnostic(tmp_path):
    class BadCleanup(FakeTranslator):
        def close(self):
            self.closes += 1
            raise RuntimeError("private child detail")
    report, engine = run_fake(tmp_path, engine_class=BadCleanup)
    assert not report["passed"] and report["failure"] == "chat_runtime_cleanup_failed"
    assert engine.closes == 1 and report["cleanup"] == {"attempted": True, "passed": False}


@pytest.mark.parametrize("endpoint", ["127.0.0.1", "::1", "localhost", "example.invalid", "192.0.2.1"])
def test_existing_guard_blocks_all_connection_endpoints_including_loopback(endpoint):
    with diagnostic.no_network() as attempts:
        with pytest.raises(RuntimeError, match="disabled"):
            socket.create_connection((endpoint, 80))
    assert len(attempts) == 1


@pytest.mark.parametrize("operation", ["connect", "connect_ex"])
def test_existing_guard_blocks_socket_tcp_methods(operation):
    with socket.socket() as sock:
        with diagnostic.no_network() as attempts:
            with pytest.raises(RuntimeError, match="disabled"):
                getattr(sock, operation)(("127.0.0.1", 80))
    assert len(attempts) == 1


def test_suppressed_network_exception_still_fails_and_report_redacts_endpoint(tmp_path):
    class SuppressedNetwork(FakeTranslator):
        def translate(self, text, direction):
            try:
                socket.create_connection(("sensitive-hostname.invalid", 80))
            except RuntimeError:
                pass
            return super().translate(text, direction)
    report, engine = run_fake(tmp_path, engine_class=SuppressedNetwork)
    assert not report["passed"] and engine.closes == 1
    assert report["network_attempts"] == [{"endpoint": "redacted"}, {"endpoint": "redacted"}]
    assert "sensitive-hostname" not in json.dumps(report)


def test_python_socket_api_objects_are_restored_even_when_body_raises():
    originals = (socket.socket.connect, socket.socket.connect_ex, socket.create_connection)
    with pytest.raises(ValueError):
        with diagnostic.no_network():
            raise ValueError("synthetic")
    assert originals == (socket.socket.connect, socket.socket.connect_ex, socket.create_connection)


def test_chat_diagnostic_reuses_existing_guard_without_replacing_its_policy():
    from screen_translator.diagnostics import no_network
    assert diagnostic.no_network is no_network


def test_deterministic_composition_regression_is_not_masked_by_a_model(tmp_path, monkeypatch):
    class BrokenComposition:
        def translate(self, *args, **kwargs):
            return "ty np lol"
    monkeypatch.setattr(diagnostic, "prepare_chat_translation", lambda *args, **kwargs: BrokenComposition())
    report = diagnostic.run_chat_self_test(tmp_path, translator_factory=lambda **kwargs: pytest.fail("Do not start model"))
    assert not report["passed"] and report["failure"] == "compound_replies_mismatch"
    assert report["cleanup"] == {"attempted": False, "passed": False}


def setup_cli(monkeypatch, tmp_path):
    from screen_translator import application, runtime_terms
    monkeypatch.setattr(application, "configure_logging", lambda: None)
    monkeypatch.setattr(runtime_terms, "install_root", lambda: tmp_path)
    terms = tmp_path / "packaging/extra-notices/microsoft-runtime/final-user-terms.txt"
    terms.parent.mkdir(parents=True)
    terms.write_text("Synthetic runtime terms for isolated CLI test only.", encoding="utf-8")
    monkeypatch.setenv("SCREEN_TRANSLATOR_DATA", str(tmp_path / "old-default-data"))
    monkeypatch.setattr("PySide6.QtWidgets.QApplication", lambda *args: pytest.fail("Chat self-test must not open Qt/tray"))
    monkeypatch.setattr("screen_translator.platform.windows.hotkeys.WindowsHotkeys", lambda *args: pytest.fail("No hotkey registration"))
    monkeypatch.setattr("screen_translator.core.pipeline.Pipeline", lambda *args: pytest.fail("No capture pipeline"))
    return application


def test_chat_cli_requires_existing_runtime_consent_before_running_diagnostic(monkeypatch, tmp_path):
    application = setup_cli(monkeypatch, tmp_path)
    monkeypatch.setattr(diagnostic, "run_chat_self_test", lambda: pytest.fail("Do not run before consent"))
    output = tmp_path / "declined.json"
    assert application.main(["--chat-self-test", "--data-dir", str(tmp_path / "data"), "--report", str(output)]) == 3
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["failure"] == "runtime_terms_declined"


@pytest.mark.parametrize("passed,code", [(True, 0), (False, 1)])
def test_authorized_chat_cli_writes_report_and_never_opens_desktop_integration(monkeypatch, tmp_path, passed, code):
    application = setup_cli(monkeypatch, tmp_path)
    monkeypatch.setattr(diagnostic, "run_chat_self_test", lambda: {"passed": passed, "synthetic": True})
    output = tmp_path / "report/result.json"
    data = tmp_path / "isolated-data"
    assert application.main(["--chat-self-test", "--accept-runtime-terms", "--data-dir", str(data), "--report", str(output)]) == code
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["passed"] is passed and report["runtime_terms_acceptance"] == "explicit-diagnostic"
    assert (data / "config.json").is_file() and not (tmp_path / "old-default-data").exists()


@pytest.mark.parametrize("other", ["--self-test", "--smoke-test", "--capture-test", "--startup-self-test"])
def test_chat_cli_is_mutually_exclusive_with_existing_diagnostics(monkeypatch, tmp_path, other):
    application = setup_cli(monkeypatch, tmp_path)
    with pytest.raises(SystemExit) as error:
        application.main(["--chat-self-test", other, "--accept-runtime-terms"])
    assert error.value.code == 2
