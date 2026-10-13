"""Nonfunctional project attribution survives compilation and source exports."""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import sys
import zipfile

from screen_translator import __author__, __version__


PROJECT = Path(__file__).resolve().parents[1]
MARKER = "dhdhd723"


def test_author_metadata_is_static_and_retained_in_optimized_bytecode():
    assert __author__ == MARKER and __version__ == "0.1.1"
    path = PROJECT / "src/screen_translator/__init__.py"
    source = path.read_bytes()
    for optimization in (0, 1, 2):
        code = compile(source, str(path), "exec", dont_inherit=True, optimize=optimization)
        assert MARKER in code.co_consts
    tree = ast.parse(source)
    assignments = {target.id: ast.literal_eval(node.value)
                   for node in tree.body if isinstance(node, ast.Assign)
                   for target in node.targets if isinstance(target, ast.Name)}
    assert assignments == {"__author__": MARKER, "__version__": "0.1.1"}
    # Importing the package cannot perform capture, input hooks or attribution I/O.
    assert all(isinstance(node, (ast.Assign, ast.Expr)) for node in tree.body)
    assert all(not isinstance(node, ast.Expr) or isinstance(node.value, ast.Constant)
               for node in tree.body)


def test_windows_version_comments_include_only_project_attribution():
    tree = ast.parse((PROJECT / "packaging/version_info.txt").read_bytes())
    comments = [ast.literal_eval(node.args[1]) for node in ast.walk(tree)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "StringStruct" and len(node.args) == 2
                and ast.literal_eval(node.args[0]) == "Comments"]
    assert comments == [f"Original project attribution: {MARKER}"]


def test_real_public_source_export_preserves_markers_without_private_files(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "attribution_export_tool", PROJECT / "tools/prepare_public_release.py")
    assert spec is not None and spec.loader is not None
    exporter = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = exporter
    spec.loader.exec_module(exporter)
    repo = tmp_path / "repo"
    exporter.export_repository(PROJECT, repo)
    archive_path = tmp_path / "source.zip"
    exporter.zip_directory(repo, archive_path)
    relatives = ("src/screen_translator/__init__.py", "packaging/version_info.txt", "README.md")
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.testzip() is None
        for relative in relatives:
            assert archive.read("repo/" + relative) == (PROJECT / relative).read_bytes()
            assert MARKER.encode("ascii") in archive.read("repo/" + relative)
        assert not any("__pycache__" in name or name.endswith((".pyc", ".log", ".sqlite3"))
                       for name in archive.namelist())
