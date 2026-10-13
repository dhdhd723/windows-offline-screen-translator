import builtins
import json

import pytest

from screen_translator import application


@pytest.mark.parametrize("arguments", [
    ["--capture-test"],
    ["--capture-test", "--report", "unused.json", "--capture-samples", "0"],
    ["--capture-test", "--report", "unused.json", "--capture-delay", "11"],
    ["--capture-test", "--self-test", "--report", "unused.json"],
    ["--startup-self-test", "--self-test"],
    ["--startup-self-test", "--smoke-test"],
    ["--startup-self-test", "--capture-test", "--report", "unused.json"],
])
def test_invalid_capture_cli_stops_before_capture(arguments):
    with pytest.raises(SystemExit) as error:
        application.main(arguments)
    assert error.value.code == 2


def test_capture_diagnostic_cannot_bypass_consent_or_start_qt(monkeypatch, tmp_path):
    monkeypatch.setenv("SCREEN_TRANSLATOR_DATA", str(tmp_path / "data"))
    original_import = builtins.__import__
    def checked_import(name, *args, **kwargs):
        if name.startswith("PySide6") or name.endswith("capture_diagnostics"):
            raise AssertionError("Native capture/Qt started before consent")
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", checked_import)
    destination = tmp_path / "report.json"
    assert application.main(["--capture-test", "--report", str(destination)]) == 3
    report = json.loads(destination.read_text(encoding="utf-8"))
    assert report["failure"] == "runtime_terms_declined"
    assert not (tmp_path / "data" / "config.json").exists()
