"""Normalization tests use temporary synthetic files and a mock trust verifier."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import struct
import sys

import pytest


@pytest.fixture
def tool():
    path = Path(__file__).resolve().parents[1] / "tools/normalize_microsoft_runtime.py"
    spec = importlib.util.spec_from_file_location("runtime_normalizer", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def pe_bytes(machine=0x8664):
    data = bytearray(70)
    data[:2], data[60:64] = b"MZ", struct.pack("<I", 64)
    data[64:70] = b"PE\0\0" + struct.pack("<H", machine)
    return bytes(data)


@pytest.fixture
def fixture(tool, tmp_path, monkeypatch):
    bundle, source = tmp_path / "bundle", tmp_path / "official"
    (bundle / "_internal/numpy.libs").mkdir(parents=True)
    (bundle / "ScreenTranslator.exe").write_bytes(pe_bytes())
    (bundle / "_internal/vcruntime140.dll").write_bytes(b"old vcruntime")
    (bundle / ("_internal/numpy.libs/msvcp140-" + "a" * 32 + ".dll")).write_bytes(b"old msvcp")
    (bundle / "_internal/custom.dll").write_bytes(b"never replace")
    source.mkdir()
    for name in tool.OFFICIAL_NAMES:
        (source / name).write_bytes(b"official " + name.encode())
    monkeypatch.setattr(tool, "OFFICIAL_HASHES", {name: tool.sha256(source / name) for name in tool.OFFICIAL_NAMES})
    inspector = lambda path: tool.DLLInfo("x64", (14, 50, 35719, 0), True, "Microsoft Corporation")
    return bundle, source, inspector


@pytest.mark.parametrize("name,want", [
    ("MSVCP140_1.dll", "msvcp140_1.dll"),
    ("vcruntime140-" + "f" * 32 + ".dll", "vcruntime140.dll"),
    ("msvcp140-abc.dll", None), ("msvcp140-extra.dll", None),
    ("foo-vcruntime140.dll", None), ("msvcp140.dll.exe", None),
])
def test_exact_name_mapping(tool, name, want):
    assert tool.canonical_name(name) == want


def test_default_check_does_not_touch_bundle_or_create_backups(tool, fixture, tmp_path):
    bundle, source, inspector = fixture
    before = {p.relative_to(bundle): p.read_bytes() for p in bundle.rglob("*") if p.is_file()}
    plan = tool.normalize(bundle, source, inspector=inspector)
    assert plan["passed"] and not plan["applied"] and len(plan["actions"]) == 2
    assert before == {p.relative_to(bundle): p.read_bytes() for p in bundle.rglob("*") if p.is_file()}
    assert not (tmp_path / "backup").exists()
    assert str(tmp_path) not in json.dumps(plan)


def test_apply_retains_hash_names_and_backups(tool, fixture, tmp_path):
    bundle, source, inspector = fixture
    report, backup = tmp_path / "report", tmp_path / "backup"
    plan = tool.normalize(bundle, source, apply=True, report_dir=report, backup_dir=backup, inspector=inspector)
    assert plan["applied"]
    for action in plan["actions"]:
        assert (bundle / action["target"]).read_bytes() == (source / action["source"]).read_bytes()
        assert tool.sha256(backup / action["target"]) == action["before"]["sha256"]
    assert (bundle / "_internal/custom.dll").read_bytes() == b"never replace"
    assert (backup / "OriginalsManifest.json").is_file()
    assert str(tmp_path) not in (report / "MicrosoftRuntimeManifest.json").read_text()


@pytest.mark.parametrize("info", [
    ("x86", (14, 50, 1, 0), True, "Microsoft Corporation"),
    ("x64", (14, 50, 1, 0), False, "Microsoft Corporation"),
    ("x64", (14, 50, 1, 0), True, "Fake Microsoft Corporation"),
    ("x64", (13, 50, 1, 0), True, "Microsoft Corporation"),
])
def test_all_source_preflight_before_any_writes(tool, fixture, tmp_path, info):
    bundle, source, inspector = fixture
    bad = lambda path: tool.DLLInfo(*info) if path.name == "vcomp140.dll" else inspector(path)
    with pytest.raises(tool.ValidationError):
        tool.normalize(bundle, source, apply=True, report_dir=tmp_path / "report", backup_dir=tmp_path / "backup", inspector=bad)
    assert not (tmp_path / "backup").exists()
    assert (bundle / "_internal/vcruntime140.dll").read_bytes() == b"old vcruntime"


def test_exact_microsoft_compatibility_publisher_is_accepted(tool, fixture):
    bundle, source, inspector = fixture
    compatibility = lambda path: tool.DLLInfo("x64", (14, 50, 35719, 0), True, "Microsoft Windows Software Compatibility Publisher")
    plan = tool.normalize(bundle, source, inspector=compatibility)
    assert plan["passed"]
    assert plan["sources"][0]["signature"]["publisher"] == "Microsoft Windows Software Compatibility Publisher"


def test_qt_targets_replaceable_but_qt_sources_forbidden(tool, fixture):
    bundle, source, inspector = fixture
    qt_targets = lambda path: tool.DLLInfo("x64", (14, 49, 1, 0), True, "The Qt Company Oy") if path.is_relative_to(bundle) else inspector(path)
    plan = tool.normalize(bundle, source, inspector=qt_targets)
    assert plan["actions"][0]["before"]["signature"]["publisher"] == "The Qt Company Oy"
    qt_source = lambda path: tool.DLLInfo("x64", (14, 50, 35719, 0), True, "The Qt Company Oy")
    with pytest.raises(tool.ValidationError, match="approved-publisher"):
        tool.normalize(bundle, source, inspector=qt_source)


def test_signed_source_also_requires_audited_exact_hash(tool, fixture):
    bundle, source, inspector = fixture
    (source / "msvcp140.dll").write_bytes(b"validly signed but wrong release bytes")
    with pytest.raises(tool.ValidationError, match="audited official package hash"):
        tool.normalize(bundle, source, inspector=inspector)


def test_missing_official_source_and_mixed_versions_rejected(tool, fixture):
    bundle, source, inspector = fixture
    mixed = lambda path: tool.DLLInfo("x64", (14, 49, 1, 0), True, "Microsoft Corporation") if path.name == "vcomp140.dll" else inspector(path)
    with pytest.raises(tool.ValidationError, match="one fixed version"):
        tool.normalize(bundle, source, inspector=mixed)
    (source / "vcomp140.dll").unlink()
    with pytest.raises(tool.ValidationError, match="incomplete"):
        tool.normalize(bundle, source, inspector=inspector)


def test_overlap_and_existing_output_rejected(tool, fixture, tmp_path):
    bundle, source, inspector = fixture
    with pytest.raises(tool.ValidationError, match="not overlap"):
        tool.normalize(bundle, source, apply=True, report_dir=bundle / "report", backup_dir=tmp_path / "backup", inspector=inspector)
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(tool.ValidationError, match="must be new"):
        tool.normalize(bundle, source, report_dir=existing, inspector=inspector)
    with pytest.raises(tool.ValidationError, match="requires separate"):
        tool.normalize(bundle, source, apply=True, inspector=inspector)


def test_add_vcomp_only_for_explicit_verified_native_import(tool, fixture, tmp_path):
    bundle, source, inspector = fixture
    native = bundle / "_internal/ctranslate2.dll"
    native.write_bytes(pe_bytes())
    unrelated = tool.normalize(bundle, source, native_imports=["_internal/ctranslate2.dll"], inspector=inspector, import_reader=lambda path: {"kernel32.dll"})
    assert not any(a["action"] == "add" for a in unrelated["actions"])
    plan = tool.normalize(bundle, source, apply=True, report_dir=tmp_path / "report", backup_dir=tmp_path / "backup",
                          native_imports=["_internal/ctranslate2.dll"], inspector=inspector,
                          import_reader=lambda path: {"vcomp140.dll"})
    assert (bundle / "_internal/vcomp140.dll").read_bytes() == (source / "vcomp140.dll").read_bytes()
    assert len([a for a in plan["actions"] if a["action"] == "add"]) == 1


def test_native_path_escape_and_downgrade_rejected(tool, fixture):
    bundle, source, inspector = fixture
    with pytest.raises(tool.ValidationError, match="relative file"):
        tool.normalize(bundle, source, native_imports=["../other.dll"], inspector=inspector)
    newer = lambda path: tool.DLLInfo("x64", (14, 51, 1, 0), True, "Microsoft Corporation") if path.is_relative_to(bundle) else inspector(path)
    with pytest.raises(tool.ValidationError, match="downgrade"):
        tool.normalize(bundle, source, inspector=newer)


def test_symlink_root_or_member_refused(tool, fixture, tmp_path):
    bundle, source, inspector = fixture
    link = tmp_path / "linked-official"
    try:
        link.symlink_to(source, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks requires Windows privileges")
    with pytest.raises(tool.ValidationError, match="symbolic links"):
        tool.normalize(bundle, link, inspector=inspector)


def test_commit_failure_restores_previous_targets(tool, fixture, tmp_path, monkeypatch):
    bundle, source, inspector = fixture
    before = {p.relative_to(bundle): p.read_bytes() for p in bundle.rglob("*") if p.is_file()}
    real_replace = tool.os.replace
    calls = 0
    def failing_replace(origin, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("synthetic second-commit failure")
        return real_replace(origin, target)
    monkeypatch.setattr(tool.os, "replace", failing_replace)
    with pytest.raises(OSError, match="synthetic"):
        tool.normalize(bundle, source, apply=True, report_dir=tmp_path / "report", backup_dir=tmp_path / "backup", inspector=inspector)
    assert before == {p.relative_to(bundle): p.read_bytes() for p in bundle.rglob("*") if p.is_file()}
    assert not list(bundle.rglob("*.tmp"))
    assert list((tmp_path / "backup").rglob("*.dll"))


def test_hard_linked_dll_refused(tool, fixture, tmp_path):
    bundle, source, inspector = fixture
    try:
        (tmp_path / "linked-dll.dll").hardlink_to(source / "vcomp140.dll")
    except OSError:
        pytest.skip("Filesystem cannot create hard links")
    with pytest.raises(tool.ValidationError, match="hard-linked"):
        tool.normalize(bundle, source, inspector=inspector)


def test_revalidation_detects_changed_source_before_writes(tool, fixture, tmp_path):
    bundle, source, inspector = fixture
    count = 0
    def changing(path):
        nonlocal count
        count += 1
        if count == len(tool.OFFICIAL_NAMES) + 3:
            (source / "vcomp140.dll").write_bytes(b"changed between checks")
        return inspector(path)
    with pytest.raises(tool.ValidationError, match="audited official package hash|Inputs changed"):
        tool.normalize(bundle, source, apply=True, report_dir=tmp_path / "report", backup_dir=tmp_path / "backup", inspector=changing)
    assert not (tmp_path / "backup").exists()


def test_pe_architecture_is_read_from_machine_field(tool, tmp_path):
    dll = tmp_path / "image.dll"
    dll.write_bytes(pe_bytes())
    assert tool.pe_architecture(dll) == "x64"
    dll.write_bytes(pe_bytes(0x14C))
    assert tool.pe_architecture(dll) == "x86"
    dll.write_bytes(b"not PE")
    with pytest.raises(tool.ValidationError):
        tool.pe_architecture(dll)
