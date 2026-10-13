"""Create NEW, allowlisted public exports; never modify private input artifacts.

This is an export filter, not a guarantee that newly edited source contains no
secrets. Review the output and run audit_private_metadata.py before publishing.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tomllib
from typing import Callable, Iterator
import zipfile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROOT_SOURCE_FILES = {".gitignore", "README.md", "pyproject.toml", "requirements-lock.txt", "launcher.py",
                     "LICENSE", "LICENSE.txt", "LICENSE.md", "NOTICE", "NOTICE.txt"}
PRIVATE_DIRS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
                "logs", "reports", "validation", "screenshots", "captures", "recordings",
                "venv", ".venv", "env", "node_modules"}
PRIVATE_SUFFIXES = {".pyc", ".pyo", ".log", ".db", ".sqlite", ".sqlite3", ".pem", ".key",
                    ".p12", ".pfx", ".whl", ".part", ".bak", ".tmp"}
PRIVATE_NAMES = {"config.json", "settings.json", "credentials.json", "secrets.json", "tests.xml",
                 "id_rsa", "id_ed25519"}
TEXT_SUFFIXES = {".txt", ".md", ".html", ".htm", ".rst", ".apache", ".bsd", ".patch"}
ARCHIVE_SUFFIXES = (".tar.xz", ".tar.gz", ".tgz", ".tar.bz2")
ZIP_TIME = (2020, 1, 1, 0, 0, 0)


def read_release_version(source: Path) -> str:
    """Read literal project versions without importing or executing source code."""
    source = Path(source)
    if _linked(source) or not source.is_dir():
        raise ValueError("Source must be an unlinked directory")
    paths = (Path("pyproject.toml"), Path("src/screen_translator/__init__.py"))
    for relative in paths:
        for parent in (relative, *relative.parents):
            if _linked(source / parent):
                raise ValueError("Linked version declarations are not accepted")
        if not (source / relative).is_file():
            raise ValueError("Source is missing a required version declaration")
    try:
        project_version = tomllib.loads((source / paths[0]).read_text(encoding="utf-8-sig"))[
            "project"]["version"]
        tree = ast.parse((source / paths[1]).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, SyntaxError, KeyError, TypeError, tomllib.TOMLDecodeError) as exc:
        raise ValueError("Cannot parse source version declarations") from exc
    values = []
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else (
            [node.target] if isinstance(node, ast.AnnAssign) else [])
        if any(isinstance(target, ast.Name) and target.id == "__version__" for target in targets):
            if not isinstance(node.value, ast.Constant) or not isinstance(node.value.value, str):
                raise ValueError("Application __version__ must be a literal string")
            values.append(node.value.value)
    if len(values) != 1:
        raise ValueError("Application must have exactly one __version__ declaration")
    if not isinstance(project_version, str) or not re.fullmatch(
            r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", project_version):
        raise ValueError("Release version must be a safe numeric X.Y.Z string")
    if project_version != values[0]:
        raise ValueError("pyproject and application versions do not match")
    return project_version


def require_final_release_approval(source: Path) -> None:
    """Require a manually reviewed status before naming an export as final.

    This is an accidental-publication guard, not an automated legal review.
    Update the status only after the documented release checks are complete.
    """
    version = read_release_version(source)
    status = Path(source) / "docs" / "RELEASE_STATUS.md"
    if not status.is_file() or _linked(status):
        raise ValueError("Final release requires a reviewed docs/RELEASE_STATUS.md")
    lines = status.read_text(encoding="utf-8-sig").splitlines()
    markers = [line.strip() for line in lines
               if line.strip().startswith("<!-- release-status:")]
    if markers != ["<!-- release-status: approved -->"]:
        raise ValueError("Release review is incomplete; export a candidate instead")
    version_markers = [line.strip() for line in lines
                       if line.strip().startswith("<!-- release-version:")]
    if version_markers != [f"<!-- release-version: {version} -->"]:
        raise ValueError("Release approval does not match this source version")


def _linked(path: Path) -> bool:
    return path.is_symlink() or (hasattr(os.path, "isjunction") and os.path.isjunction(path))


def _private(relative: Path) -> bool:
    parts = [part.lower() for part in relative.parts]
    name = relative.name.lower()
    return (any(part in PRIVATE_DIRS for part in parts) or relative.suffix.lower() in PRIVATE_SUFFIXES
            or name in PRIVATE_NAMES or name == ".env" or name.startswith(".env.")
            or name.startswith(("config.json.", "settings.json."))
            or any(marker in name for marker in (".sqlite-", ".sqlite3-", ".db-", ".log.")))


def _new_directory(path: Path) -> None:
    if path.exists() or _linked(path):
        raise FileExistsError("Export destination already exists; choose a new directory")
    path.mkdir(parents=True, exist_ok=False)


def _files(root: Path, private_filter: Callable[[Path], bool] = _private) -> Iterator[Path]:
    """Do not follow filesystem links or traverse excluded private directories."""
    if _linked(root):
        raise ValueError("Linked input directories are not accepted")
    resolved_root = root.resolve(strict=True)
    if not resolved_root.is_dir():
        raise ValueError("Input must be a directory")

    def visit(directory: Path) -> Iterator[Path]:
        for item in sorted(directory.iterdir()):
            relative = item.relative_to(root)
            if private_filter(relative):
                continue
            if _linked(item) or not item.resolve().is_relative_to(resolved_root):
                raise ValueError("Refusing linked or out-of-root input")
            if item.is_dir():
                yield from visit(item)
            elif item.is_file():
                yield item
    yield from visit(root)


def _copy_files(root: Path, destination: Path, predicate: Callable[[Path], bool],
                private_filter: Callable[[Path], bool] = _private) -> int:
    count = 0
    for item in _files(root, private_filter):
        relative = item.relative_to(root)
        if predicate(relative):
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            # copyfile deliberately avoids copying private filesystem timestamps.
            shutil.copyfile(item, target)
            count += 1
    return count


def _model_private(path: Path) -> bool:
    # These are immutable model architecture parameters, not user settings.
    if len(path.parts) >= 3 and path.parts[0] == "translation" and path.name == "config.json":
        return False
    return _private(path)


def _runtime_private(path: Path) -> bool:
    # PEP 610 records how pip installed a wheel; local file URLs disclose the
    # developer's build directory and are not needed by the frozen runtime.
    if path.name.lower() == "direct_url.json" and any(
        part.lower().endswith(".dist-info") for part in path.parts
    ):
        return True
    # certifi's public CA bundle is not a private key. Preserve stock runtime.
    if path.as_posix() == "certifi/cacert.pem":
        return False
    return _private(path)


def acceptable_license_path(path: Path) -> bool:
    if _private(path):
        return False
    name = path.name.lower()
    return (path.suffix.lower() in TEXT_SUFFIXES or name.endswith(ARCHIVE_SUFFIXES)
            or (not path.suffix and any(word in name for word in ("license", "licence", "copyright", "notice", "copying", "authors"))))


def _source_file(path: Path) -> bool:
    if _private(path):
        return False
    if len(path.parts) == 1:
        return path.name in ROOT_SOURCE_FILES
    folder = path.parts[0]
    if folder in {"src", "tests", "tools"}:
        return path.suffix == ".py"
    if folder == "docs":
        return path.suffix == ".md"
    if folder == "packaging":
        return (path == Path("packaging/icon.ico") or path.suffix in {".spec", ".manifest"}
                or path == Path("packaging/fonts/NotoSansCJKsc-Regular.otf")
                or (acceptable_license_path(path) and not path.name.lower().endswith(ARCHIVE_SUFFIXES)))
    return False


def export_repository(source: Path, destination: Path) -> dict:
    source = Path(source)
    destination = Path(destination)
    if _linked(source) or not source.is_dir():
        raise ValueError("Source must be an unlinked directory")
    if destination.resolve().is_relative_to(source.resolve()):
        # build/ is a documented output location; never traverse that subtree.
        if destination.resolve().relative_to(source.resolve()).parts[0] not in {"build", "dist", "public-export"}:
            raise ValueError("Nested source export must be under an excluded build directory")
    _new_directory(destination)
    count = 0
    for name in sorted(ROOT_SOURCE_FILES):
        original = source / name
        if original.is_file():
            if _linked(original):
                raise ValueError("Refusing linked source file")
            shutil.copyfile(original, destination / name)
            count += 1
    for folder in ("src", "tests", "tools", "docs", "packaging"):
        root = source / folder
        if root.is_dir():
            count += _copy_files(root, destination / folder, lambda p, f=folder: _source_file(Path(f) / p))
    return {"source_files": count}


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _rewrite_document_links(text: str, targets: dict[str, str]) -> str:
    """Move only exact local inline targets known to exist in the public export.

    Literal boundaries avoid rewriting external URLs, traversal paths or a
    similarly prefixed filename. Keep optional heading fragments unchanged.
    """
    for original, replacement in targets.items():
        text = text.replace(f"]({original})", f"]({replacement})")
        text = text.replace(f"]({original}#", f"]({replacement}#")
    return text


def export_portable(portable: Path, repo: Path, destination: Path,
                    supplemental_notices: Path | None = None) -> dict:
    portable = Path(portable)
    destination = Path(destination)
    if _linked(portable) or destination.resolve().is_relative_to(portable.resolve()):
        raise ValueError("Portable output must be separate from an unlinked input directory")
    executable = portable / "ScreenTranslator.exe"
    if not executable.is_file() or _linked(executable):
        raise ValueError("Expected unlinked ScreenTranslator.exe")
    _new_directory(destination)
    shutil.copyfile(executable, destination / executable.name)
    counts = {}
    for folder in ("_internal", "models", "LICENSES"):
        root = portable / folder
        if not root.is_dir():
            raise ValueError("Portable input is missing a required runtime directory")
        predicate = acceptable_license_path if folder == "LICENSES" else lambda _: True
        private_filter = {"models": _model_private, "_internal": _runtime_private,
                          "LICENSES": _private}[folder]
        counts[folder + "_files"] = _copy_files(root, destination / folder, predicate, private_filter)
    # The input portable may have been built before a notice audit was completed.
    # Overlay the reviewed, source-controlled notices so a fresh public export
    # cannot silently keep an obsolete license text from an older package.
    reviewed_notices = (Path(supplemental_notices) if supplemental_notices is not None
                        else Path(repo) / "packaging" / "extra-notices")
    if reviewed_notices.is_dir():
        counts["reviewed_notice_files"] = _copy_files(
            reviewed_notices,
            destination / "LICENSES" / "upstream",
            acceptable_license_path,
        )
    else:
        counts["reviewed_notice_files"] = 0
    counts["source_files"] = _copy_files(Path(repo), destination / "source", _source_file)
    # Derive navigation from files that survived the existing source allowlist,
    # not a hard-coded list which goes stale whenever a new release note is added.
    docs_root = destination / "source" / "docs"
    included_docs = ([item.relative_to(docs_root).as_posix()
                      for item in _files(docs_root) if item.suffix == ".md"]
                     if docs_root.is_dir() else [])
    readme_targets = {prefix + name: "source/docs/" + name
                      for name in included_docs for prefix in ("docs/", "./docs/")}
    doc_targets = {prefix + name: "source/docs/" + name
                   for name in included_docs for prefix in ("", "./")}
    if (destination / "source" / "README.md").is_file():
        doc_targets["../README.md"] = "source/README.md"
    for name, relative in (("README.md", "README.md"), ("使用说明.md", "docs/使用说明.md"),
                           ("技术方案.md", "docs/技术方案.md"),
                           ("项目说明报告.md", "docs/项目说明报告.md"),
                           ("发布许可状态.md", "docs/RELEASE_STATUS.md"),
                           ("0.1.1验收说明.md", "docs/0.1.1验收说明.md")):
        # Old bundle documents may contain machine-specific acceptance notes.
        # Only reuse the reviewed source documentation, never old package docs.
        original = Path(repo) / relative
        if not original.is_file():
            continue
        if _linked(original):
            raise ValueError("Refusing linked documentation")
        text = original.read_text(encoding="utf-8-sig")
        if relative == "README.md":
            text = _rewrite_document_links(text, readme_targets)
        elif relative.startswith("docs/"):
            text = _rewrite_document_links(text, doc_targets)
        (destination / name).write_text(text, encoding="utf-8")
    (destination / "发布隐私说明.md").write_text(
        "# 公开运行包的隐私边界\n\n"
        "本包使用独立导出目录，不附带原始验收报告、运行日志、用户配置、译文数据库、真实截图或原 Git 历史。"
        "第三方署名和许可证保留；可执行文件和模型未为脱敏而修改。\n\n"
        "程序运行后仍会在用户设备上产生本地设置和诊断数据。请勿将这些数据直接提交到公开仓库。"
        "本文件只说明导出规则。第三方二进制核验依据、适用条件和剩余边界见 "
        "source/docs/THIRD_PARTY_BINARY_NOTICES.md 与 source/docs/PUBLISHING.md。\n",
        encoding="utf-8")
    before, after = sha256(executable), sha256(destination / executable.name)
    if before != after:
        raise RuntimeError("Executable integrity check failed")
    return {**counts, "executable_unchanged": True, "executable_sha256": after}


def zip_directory(root: Path, target: Path) -> None:
    root = Path(root)
    target = Path(target)
    if target.resolve().is_relative_to(root.resolve()):
        raise ValueError("Archive output must be outside the archived directory")
    if target.exists() or _linked(target):
        raise FileExistsError("Archive already exists; choose a new target")
    with zipfile.ZipFile(target, mode="x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        # The input is an already-filtered export. Preserve model config.json
        # and public CA files; a second filename filter would break the runtime.
        for item in _files(root, lambda _: False):
            info = zipfile.ZipInfo((Path(root.name) / item.relative_to(root)).as_posix(), ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            with item.open("rb") as source, archive.open(info, "w", force_zip64=True) as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--portable", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    channel = parser.add_mutually_exclusive_group()
    channel.add_argument("--candidate", action="store_true",
                         help="Export a non-final release candidate (the default)")
    channel.add_argument("--final", action="store_true",
                         help="Export a final release only after the documented review is approved")
    args = parser.parse_args()
    try:
        version = read_release_version(args.source)
    except ValueError as exc:
        parser.error(str(exc))
    if args.final:
        try:
            require_final_release_approval(args.source)
        except ValueError as exc:
            parser.error(str(exc))
    _new_directory(args.output)
    repo = args.output / "repo"
    portable = args.output / "ScreenTranslator"
    results = {"repository": export_repository(args.source, repo),
               "portable": export_portable(args.portable, repo, portable,
                                           args.source / "packaging" / "extra-notices")}
    results["release_channel"] = "final" if args.final else "candidate"
    results["source_version"] = version
    portable_name = (f"ScreenTranslator-{version}-Windows-x64.zip" if args.final
                     else f"ScreenTranslator-{version}-Windows-x64-candidate.zip")
    for root, name in ((repo, f"ScreenTranslator-{version}-source.zip"),
                       (portable, portable_name)):
        target = args.output / name
        zip_directory(root, target)
        results[name] = {"sha256": sha256(target), "bytes": target.stat().st_size}
    (args.output / "EXPORT_MANIFEST.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
