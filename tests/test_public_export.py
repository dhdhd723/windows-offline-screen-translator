"""Privacy-release regression tests use synthetic data only."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import zipfile

import pytest


def _load_exporter():
    path = Path(__file__).resolve().parents[1] / "tools" / "prepare_public_release.py"
    spec = importlib.util.spec_from_file_location("public_release_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_license_collector():
    path = Path(__file__).resolve().parents[1] / "tools" / "collect_licenses.py"
    spec = importlib.util.spec_from_file_location("license_collector_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def exporter():
    return _load_exporter()


def _write(root: Path, relative: str, content: bytes | str = "synthetic source\n") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
    return path


def _files(root: Path) -> set[str]:
    return {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}


def _repository(root: Path) -> set[str]:
    accepted = {
        "README.md", ".gitignore", "pyproject.toml", "requirements-lock.txt", "launcher.py",
        "src/example/__init__.py", "src/example/main.py", "tests/test_app.py",
        "tools/example.py", "docs/PUBLISHING.md", "docs/guide.md",
        "packaging/ScreenTranslator.spec", "packaging/app.manifest",
        "packaging/version_info.txt", "packaging/icon.ico",
        "packaging/fonts/NotoSansCJKsc-Regular.otf", "packaging/fonts/OFL.txt",
        "packaging/fonts/README.md",
        "packaging/qt-notices/LGPL-3.0-only.txt",
        "packaging/extra-notices/example/LICENSE.txt",
        "packaging/extra-notices/example/NOTICE.txt",
    }
    for name in accepted:
        _write(root, name, b"icon" if name.endswith(".ico") else "synthetic public source\n")
    return accepted


def _portable(root: Path) -> set[str]:
    accepted = {
        "ScreenTranslator.exe", "_internal/example.dll", "_internal/base_library.zip",
        "_internal/example.pyd", "_internal/certifi/cacert.pem",
        "models/manifest.json", "models/ocr/det.onnx",
        "models/ocr/keys.txt", "models/translation/example/model.bin",
        "models/translation/example/config.json", "models/translation/example/source.spm",
        "LICENSES/example/LICENSE.txt", "LICENSES/ThirdPartyNotices.txt",
    }
    for name in accepted:
        _write(root, name, b"synthetic runtime bytes\x00\x01")
    return accepted


def test_repository_copies_only_explicit_source_groups(exporter, tmp_path):
    source = tmp_path / "project"
    accepted = _repository(source)
    destination = tmp_path / "public"
    report = exporter.export_repository(source, destination)
    assert isinstance(report, dict)
    assert accepted <= _files(destination)
    for name in accepted:
        assert (destination / name).read_bytes() == (source / name).read_bytes()


@pytest.mark.parametrize("relative", [
    ".git/config", ".git/objects/example", ".env", "secrets.json", "credentials.json",
    "config.json", "config.json.broken", "cache.sqlite3", "cache.sqlite3-wal",
    "application.log", "build/tests.xml", "build/raw-report.json", "dist/old.exe",
    "models/private/model.bin", "venv/Lib/private.py", "screenshots/sample.png",
    "src/example/__pycache__/private.py", "src/example/private.pyc",
    "packaging/extra-notices/example/private.whl", "packaging/private.pfx",
    "docs/private.json", "tests/private.sqlite3", "tools/private.pem",
    "packaging/fonts/private.otf", "packaging/fonts/private.ttf",
])
def test_repository_excludes_private_and_generated_files(exporter, tmp_path, relative):
    source = tmp_path / "project"
    _repository(source)
    _write(source, relative, "SYNTHETIC_EXCLUDED_MARKER\n")
    destination = tmp_path / "public"
    exporter.export_repository(source, destination)
    assert relative not in _files(destination)
    assert not any(b"SYNTHETIC_EXCLUDED_MARKER" in path.read_bytes()
                   for path in destination.rglob("*") if path.is_file())


def test_third_party_author_and_license_attribution_survives(exporter, tmp_path):
    source = tmp_path / "project"
    _repository(source)
    relative = "packaging/extra-notices/example/NOTICE.txt"
    notice = "Copyright Example Contributors.\nSource: https://example.org/project\n"
    _write(source, relative, notice)
    destination = tmp_path / "public"
    exporter.export_repository(source, destination)
    assert (destination / relative).read_text(encoding="utf-8") == notice


@pytest.mark.parametrize("name", ["LICENSE.txt", "NOTICE.txt", "COPYING", "README.md", "upstream.patch"])
def test_license_text_paths_are_acceptable(exporter, name):
    assert exporter.acceptable_license_path(Path("LICENSES") / "example" / name)


@pytest.mark.parametrize("name", ["private.whl", "private.exe", "private.dll", "private.pfx",
                                  "private.pem", "private.sqlite3", "private.pyc", ".env"])
def test_license_filter_does_not_allow_arbitrary_artifacts(exporter, name):
    assert not exporter.acceptable_license_path(Path("LICENSES") / "example" / name)


def test_portable_preserves_runtime_models_and_executable_exactly(exporter, tmp_path):
    portable = tmp_path / "portable"
    accepted = _portable(portable)
    repo = tmp_path / "repo"
    _repository(repo)
    destination = tmp_path / "release"
    report = exporter.export_portable(portable, repo, destination)
    assert isinstance(report, dict)
    assert accepted <= _files(destination)
    for name in accepted:
        assert (destination / name).read_bytes() == (portable / name).read_bytes()
    assert (destination / "source/src/example/main.py").read_bytes() == (
        repo / "src/example/main.py").read_bytes()


def test_portable_overlays_reviewed_source_notices(exporter, tmp_path):
    portable = tmp_path / "portable"
    _portable(portable)
    _write(portable, "LICENSES/upstream/example/LICENSE.txt", "obsolete notice\n")
    repo = tmp_path / "repo"
    _repository(repo)
    reviewed = "reviewed public notice\n"
    _write(repo, "packaging/extra-notices/example/LICENSE.txt", reviewed)
    destination = tmp_path / "release"
    report = exporter.export_portable(portable, repo, destination)
    assert report["reviewed_notice_files"] >= 1
    assert (destination / "LICENSES/upstream/example/LICENSE.txt").read_text(
        encoding="utf-8"
    ) == reviewed


def test_portable_readme_links_target_included_source_docs(exporter, tmp_path):
    portable = tmp_path / "portable"
    _portable(portable)
    repo = tmp_path / "repo"
    _repository(repo)
    _write(repo, "README.md", "[Publishing](docs/PUBLISHING.md)\n")
    destination = tmp_path / "release"
    exporter.export_portable(portable, repo, destination)
    assert (destination / "README.md").read_text(encoding="utf-8") == (
        "[Publishing](source/docs/PUBLISHING.md)\n"
    )
    assert (destination / "source/docs/PUBLISHING.md").is_file()


def test_portable_keeps_supplemental_library_source_but_excludes_wheels(exporter, tmp_path):
    portable = tmp_path / "portable"
    _portable(portable)
    repo = tmp_path / "repo"
    _repository(repo)
    notices = tmp_path / "reviewed-notices"
    archive = _write(notices, "example/library-source.tar.bz2", b"synthetic upstream source")
    _write(notices, "example/private.whl", b"synthetic excluded wheel")
    destination = tmp_path / "release"
    exporter.export_portable(portable, repo, destination, notices)
    assert (destination / "LICENSES/upstream/example/library-source.tar.bz2").read_bytes() == (
        archive.read_bytes()
    )
    assert not (destination / "LICENSES/upstream/example/private.whl").exists()


def test_repository_preserves_upstream_patches_but_not_source_archives(exporter, tmp_path):
    source = tmp_path / "project"
    _repository(source)
    patch = _write(source, "packaging/extra-notices/example/upstream.patch", "synthetic patch\n")
    _write(source, "packaging/extra-notices/example/library-source.tar.gz", b"upstream archive")
    destination = tmp_path / "public"
    exporter.export_repository(source, destination)
    assert (destination / "packaging/extra-notices/example/upstream.patch").read_bytes() == patch.read_bytes()
    assert not (destination / "packaging/extra-notices/example/library-source.tar.gz").exists()


@pytest.mark.parametrize("text", [
    None, "# Status\n", "<!-- release-status: blocked -->\n",
    "<!-- release-status: approved -->\n<!-- release-status: blocked -->\n",
    "<!-- release-status: approved -->\n<!-- release-status: approved -->\n",
])
def test_final_release_requires_one_explicit_reviewed_approval(exporter, tmp_path, text):
    source = tmp_path / "project"
    source.mkdir()
    if text is not None:
        _write(source, "docs/RELEASE_STATUS.md", text)
    with pytest.raises(ValueError):
        exporter.require_final_release_approval(source)


def test_final_release_accepts_explicit_approval_marker(exporter, tmp_path):
    source = tmp_path / "project"
    _write(source, "docs/RELEASE_STATUS.md", "# Status\n\n<!-- release-status: approved -->\n")
    exporter.require_final_release_approval(source)


@pytest.mark.parametrize("flags", [[], ["--candidate"]])
def test_cli_defaults_to_candidate_and_labels_manifest(exporter, tmp_path, monkeypatch, capsys, flags):
    source = tmp_path / "project"
    _repository(source)
    portable = tmp_path / "portable"
    _portable(portable)
    output = tmp_path / "export"
    monkeypatch.setattr(sys, "argv", ["prepare_public_release.py", "--source", str(source),
                                    "--portable", str(portable), "--output", str(output), *flags])
    exporter.main()
    assert (output / "ScreenTranslator-0.1.0-Windows-x64-candidate.zip").is_file()
    assert not (output / "ScreenTranslator-0.1.0-Windows-x64.zip").exists()
    assert '"release_channel": "candidate"' in (output / "EXPORT_MANIFEST.json").read_text()
    capsys.readouterr()


def test_cli_refuses_final_before_creating_any_output(exporter, tmp_path, monkeypatch, capsys):
    source = tmp_path / "project"
    _repository(source)
    _write(source, "docs/RELEASE_STATUS.md", "<!-- release-status: blocked -->\n")
    output = tmp_path / "export"
    monkeypatch.setattr(sys, "argv", ["prepare_public_release.py", "--source", str(source),
                                    "--portable", str(tmp_path / "missing-portable"),
                                    "--output", str(output), "--final"])
    with pytest.raises(SystemExit) as exc:
        exporter.main()
    assert exc.value.code == 2
    assert not output.exists()
    assert "review is incomplete" in capsys.readouterr().err


def test_cli_final_export_requires_flag_and_approval(exporter, tmp_path, monkeypatch, capsys):
    source = tmp_path / "project"
    _repository(source)
    _write(source, "docs/RELEASE_STATUS.md", "<!-- release-status: approved -->\n")
    portable = tmp_path / "portable"
    _portable(portable)
    output = tmp_path / "export"
    monkeypatch.setattr(sys, "argv", ["prepare_public_release.py", "--source", str(source),
                                    "--portable", str(portable), "--output", str(output), "--final"])
    exporter.main()
    assert (output / "ScreenTranslator-0.1.0-Windows-x64.zip").is_file()
    assert '"release_channel": "final"' in (output / "EXPORT_MANIFEST.json").read_text()
    capsys.readouterr()


def test_cli_candidate_and_final_are_mutually_exclusive(exporter, tmp_path, monkeypatch, capsys):
    output = tmp_path / "export"
    monkeypatch.setattr(sys, "argv", ["prepare_public_release.py", "--portable", "unused",
                                    "--output", str(output), "--candidate", "--final"])
    with pytest.raises(SystemExit) as exc:
        exporter.main()
    assert exc.value.code == 2
    assert not output.exists()
    capsys.readouterr()


def test_final_release_rejects_linked_status(exporter, tmp_path, monkeypatch):
    source = tmp_path / "project"
    status = _write(source, "docs/RELEASE_STATUS.md", "<!-- release-status: approved -->\n")
    original = exporter._linked
    monkeypatch.setattr(exporter, "_linked", lambda path: Path(path) == status or original(path))
    with pytest.raises(ValueError):
        exporter.require_final_release_approval(source)


def test_portable_status_links_target_included_source_docs(exporter, tmp_path):
    portable = tmp_path / "portable"
    _portable(portable)
    repo = tmp_path / "repo"
    _repository(repo)
    names = ("THIRD_PARTY_BINARY_NOTICES.md", "CPU_ONLY_BUILD_PLAN.md",
             "COPYLEFT_SOURCE_NOTICES.md", "MICROSOFT_RUNTIME_TERMS.md",
             "CPU_BUILD_PROVENANCE.md", "项目说明报告.md")
    text = "\n".join(f"[Notice]({name})" for name in names) + "\n"
    _write(repo, "docs/RELEASE_STATUS.md", text)
    for name in names:
        _write(repo, "docs/" + name)
    _write(repo, "docs/项目说明报告.md",
           "[Build](CPU_BUILD_PROVENANCE.md)\n[Readme](../README.md)\n")
    destination = tmp_path / "release"
    exporter.export_portable(portable, repo, destination)
    exported = (destination / "发布许可状态.md").read_text(encoding="utf-8")
    for name in names:
        assert f"](source/docs/{name})" in exported
        assert (destination / "source/docs" / name).is_file()
    report = (destination / "项目说明报告.md").read_text(encoding="utf-8")
    assert "](source/docs/CPU_BUILD_PROVENANCE.md)" in report
    assert "](source/README.md)" in report


def test_portable_does_not_reuse_old_source_reports_or_user_data(exporter, tmp_path):
    portable = tmp_path / "portable"
    _portable(portable)
    excluded = {
        "source/old.py", "validation/raw-test.json", "logs/application.log",
        "config.json", "config.json.broken", "cache.sqlite3", "cache.sqlite3-wal",
        ".env", ".git/config", "screenshots/sample.png", "private.md",
        "README.md", "LICENSES/example/private.whl",
        "_internal/example.dist-info/direct_url.json",
    }
    for name in excluded:
        _write(portable, name, "SYNTHETIC_PRIVATE_OLD_PACKAGE_MARKER\n")
    repo = tmp_path / "repo"
    _repository(repo)
    destination = tmp_path / "release"
    exporter.export_portable(portable, repo, destination)
    files = _files(destination)
    assert "source/old.py" not in files
    assert not any(name.startswith("validation/") for name in files)
    assert not any(b"SYNTHETIC_PRIVATE_OLD_PACKAGE_MARKER" in path.read_bytes()
                   for path in destination.rglob("*") if path.is_file())


def test_zip_uses_relative_names_fixed_dates_and_preserves_gitignore(exporter, tmp_path):
    source = tmp_path / "repository"
    _write(source, ".gitignore", "build/\n")
    _write(source, "src/example/main.py", "print('synthetic')\n")
    target = tmp_path / "public.zip"
    exporter.zip_directory(source, target)
    with zipfile.ZipFile(target) as archive:
        assert "repository/.gitignore" in archive.namelist()
        assert "repository/src/example/main.py" in archive.namelist()
        for info in archive.infolist():
            assert info.date_time == (2020, 1, 1, 0, 0, 0)
            assert not info.filename.startswith(("/", "\\"))
            assert ":" not in info.filename
            assert ".." not in Path(info.filename).parts
        assert archive.read("repository/.gitignore") == b"build/\n"


def test_zip_refuses_to_overwrite_existing_target(exporter, tmp_path):
    source = tmp_path / "repository"
    _write(source, "README.md")
    target = _write(tmp_path, "public.zip", b"existing synthetic archive")
    with pytest.raises((FileExistsError, ValueError, RuntimeError)):
        exporter.zip_directory(source, target)
    assert target.read_bytes() == b"existing synthetic archive"


def test_zip_rejects_output_inside_input_tree_without_creating_it(exporter, tmp_path):
    source = tmp_path / "repository"
    _write(source, "README.md")
    target = source / "nested" / "public.zip"
    with pytest.raises(ValueError):
        exporter.zip_directory(source, target)
    assert not target.exists()


def _symlink(link: Path, target: Path):
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(target, target_is_directory=target.is_dir())
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"Symbolic-link creation unavailable: {type(exc).__name__}")


def test_repository_rejects_symlinked_source_file(exporter, tmp_path):
    source = tmp_path / "project"
    _repository(source)
    outside = _write(tmp_path, "outside.py", "SYNTHETIC_EXTERNAL_MARKER\n")
    _symlink(source / "src/example/linked.py", outside)
    with pytest.raises((ValueError, RuntimeError, OSError)):
        exporter.export_repository(source, tmp_path / "public")


def test_portable_rejects_symlinked_runtime_directory(exporter, tmp_path):
    portable = tmp_path / "portable"
    _portable(portable)
    outside = tmp_path / "outside"
    _write(outside, "linked.dll")
    _symlink(portable / "_internal/linked", outside)
    repo = tmp_path / "repo"
    _repository(repo)
    with pytest.raises((ValueError, RuntimeError, OSError)):
        exporter.export_portable(portable, repo, tmp_path / "release")


def test_zip_rejects_symlinked_file(exporter, tmp_path):
    source = tmp_path / "repository"
    source.mkdir()
    outside = _write(tmp_path, "outside.txt")
    _symlink(source / "linked.txt", outside)
    with pytest.raises((ValueError, RuntimeError, OSError)):
        exporter.zip_directory(source, tmp_path / "public.zip")


def test_repository_rejects_linked_top_level_source(exporter, tmp_path):
    actual = tmp_path / "actual"
    _repository(actual)
    source = tmp_path / "linked-project"
    _symlink(source, actual)
    with pytest.raises((ValueError, RuntimeError, OSError)):
        exporter.export_repository(source, tmp_path / "public")


def test_repository_rejects_junction_directory(exporter, tmp_path, monkeypatch):
    source = tmp_path / "project"
    _repository(source)
    junction = source / "src/example/junction"
    _write(junction, "external.py")
    original = getattr(os.path, "isjunction", lambda _: False)
    monkeypatch.setattr(os.path, "isjunction",
                        lambda path: Path(path) == junction or original(path), raising=False)
    with pytest.raises((ValueError, RuntimeError, OSError)):
        exporter.export_repository(source, tmp_path / "public")


def test_repository_refuses_existing_destination_without_altering_it(exporter, tmp_path):
    source = tmp_path / "project"
    _repository(source)
    destination = tmp_path / "public"
    marker = _write(destination, "README.md", "existing synthetic source\n")
    with pytest.raises((FileExistsError, ValueError, RuntimeError)):
        exporter.export_repository(source, destination)
    assert marker.read_text(encoding="utf-8") == "existing synthetic source\n"


def test_exported_zip_preserves_models_configuration_and_runtime_certificate(exporter, tmp_path):
    portable = tmp_path / "portable"
    _portable(portable)
    repo = tmp_path / "repo"
    _repository(repo)
    release = tmp_path / "ScreenTranslator"
    exporter.export_portable(portable, repo, release)
    target = tmp_path / "portable.zip"
    exporter.zip_directory(release, target)
    with zipfile.ZipFile(target) as archive:
        for relative in ("models/translation/example/config.json", "_internal/certifi/cacert.pem"):
            assert archive.read("ScreenTranslator/" + relative) == (portable / relative).read_bytes()


def test_zip_bytes_are_reproducible(exporter, tmp_path):
    source = tmp_path / "repository"
    _write(source, ".gitignore", "build/\n")
    _write(source, "README.md", "synthetic source\n")
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    exporter.zip_directory(source, first)
    exporter.zip_directory(source, second)
    assert first.read_bytes() == second.read_bytes()


@pytest.mark.parametrize("relative", [
    "example.dist-info/licenses/LICENSE.txt", "example.dist-info/licenses/COPYING",
    "example.dist-info/LICENSE", "example.dist-info/NOTICE.txt",
    "example/licenses/freetype.txt", "example/license/third-party.html",
])
def test_license_collector_keeps_real_notice_texts(relative):
    collector = _load_license_collector()
    assert collector.is_notice_file(Path(relative))


@pytest.mark.parametrize("relative", [
    "example/license.py", "example/license.pyc", "example/licenses/private.py",
    "example/licenses/private.pyc", "example/licenses/private.dll",
    "example/licenses/private.pfx", "example/licenses/private.sqlite3",
    "example/licenses/private.whl", "example/unrelated.py", "example/dist-info/RECORD",
])
def test_license_collector_excludes_code_and_non_notice_artifacts(relative):
    collector = _load_license_collector()
    assert not collector.is_notice_file(Path(relative))
