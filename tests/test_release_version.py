"""Keep source, Windows version resources and candidate status aligned without exec."""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import sys


PROJECT = Path(__file__).resolve().parents[1]


def _exporter():
    spec = importlib.util.spec_from_file_location("version_release_tool", PROJECT / "tools/prepare_public_release.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_project_and_application_version_agree():
    assert _exporter().read_release_version(PROJECT) == "0.1.1"


def test_windows_file_and_product_version_resources_agree():
    version = _exporter().read_release_version(PROJECT)
    tree = ast.parse((PROJECT / "packaging/version_info.txt").read_text(encoding="utf-8-sig"))
    strings = {}
    numeric = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id == "StringStruct" and len(node.args) == 2:
            key, value = (ast.literal_eval(arg) for arg in node.args)
            if key in {"FileVersion", "ProductVersion"}:
                assert key not in strings
                strings[key] = value
        if node.func.id == "FixedFileInfo":
            for keyword in node.keywords:
                if keyword.arg in {"filevers", "prodvers"}:
                    numeric[keyword.arg] = ast.literal_eval(keyword.value)
    assert strings == {"FileVersion": version, "ProductVersion": version}
    expected = tuple(int(part) for part in version.split(".")) + (0,)
    assert numeric == {"filevers": expected, "prodvers": expected}


def test_new_release_is_pending_and_not_using_previous_exe_hash():
    status = (PROJECT / "docs/RELEASE_STATUS.md").read_text(encoding="utf-8-sig")
    assert "<!-- release-status: pending -->" in status
    assert "<!-- release-version: 0.1.1 -->" in status
    assert "<!-- release-status: approved -->" not in status
    assert "1974b547d5557a7b1fecb521b52af815e0bdbc6290f1f9e9e62aa6488c354241" not in status
