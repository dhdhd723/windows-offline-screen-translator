"""Local scene settings and their atomic sidecars must never be published."""
from pathlib import Path
import pytest
from test_public_export import exporter, _repository, _write, _files  # noqa: F401


@pytest.mark.parametrize("relative", [
    "presets.json", "presets.json.backup", "presets.json.x.tmp",
    "docs/presets.json", "src/example/presets.json", "tests/presets.json",
    "packaging/extra-notices/example/presets.json",
    "packaging/extra-notices/example/presets.json.broken",
])
def test_presets_and_backups_are_private_at_any_depth(exporter,tmp_path,relative):
    source=tmp_path/"project"
    _repository(source)
    _write(source,relative,"SYNTHETIC_PRIVATE_SCENE_SETTINGS")
    destination=tmp_path/"public"
    exporter.export_repository(source,destination)
    assert relative not in _files(destination)
    assert all(b"SYNTHETIC_PRIVATE_SCENE_SETTINGS" not in path.read_bytes()
               for path in destination.rglob("*") if path.is_file())


@pytest.mark.parametrize("relative", ["presets.json","nested/presets.json", "presets.json.atomic.tmp", "PRESETS.JSON.broken"])
def test_preset_private_name_policy_is_case_insensitive(exporter,relative):
    assert exporter._private(Path(relative))
