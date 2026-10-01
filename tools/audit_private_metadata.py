"""Read-only artifact audit. Never print matched private values or execute code."""
from __future__ import annotations

import argparse
from collections import Counter
import io
import json
import marshal
import os
from pathlib import Path
import re
import types
import zipfile

from PyInstaller.archive.readers import CArchiveReader


USER_PATH = re.compile(rb"(?:[A-Za-z]:[\\/](?:Users|Documents and Settings)[\\/][^\x00\r\n\"<>]{1,180})", re.I)
ABS_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|/)")
TEXT_EXTENSIONS = {".txt", ".md", ".json", ".xml", ".toml", ".ini", ".cfg", ".py", ".spec", ".ps1", ".yml", ".yaml", ".html", ".csv", ".log"}


def path_kind(value: str) -> str | None:
    if re.match(r"^[A-Za-z]:[\\/](?:Users|Documents and Settings)[\\/]", value, re.I):
        return "user_profile_absolute_path"
    if ABS_PATH.match(value):
        return "other_absolute_path"
    return None


def is_current_profile(value: str) -> bool:
    profile = os.environ.get("USERPROFILE", "").replace("\\", "/").rstrip("/").lower()
    return bool(profile and value.replace("\\", "/").lower().startswith(profile + "/"))


def code_paths(code: types.CodeType, counts: Counter) -> None:
    kind = path_kind(code.co_filename)
    if kind:
        counts[kind] += 1
        if is_current_profile(code.co_filename):
            counts["current_profile_code_path"] += 1
    for item in code.co_consts:
        if isinstance(item, types.CodeType):
            code_paths(item, counts)


def content_hits(data: bytes, counts: Counter) -> None:
    # Include UTF-16LE documents and PE resources without revealing a match.
    for blob in (data, data.replace(b"\x00", b"")):
        path_blob = blob.replace(b"\\\\", b"\\")
        counts["embedded_user_profile_path"] += len(USER_PATH.findall(path_blob))
        profile = os.environ.get("USERPROFILE", "")
        if profile:
            counts["embedded_current_profile_path"] += len(re.findall(re.escape(profile.encode("utf-8")), path_blob, re.I))
        for env_name, category in (("USERNAME", "current_account_name"), ("COMPUTERNAME", "current_computer_name")):
            value = os.environ.get(env_name, "")
            if len(value) >= 3:
                counts[category] += len(re.findall(re.escape(value.encode("utf-8")), blob, re.I))


def pe_debug_paths(data: bytes, counts: Counter) -> None:
    # CodeView RSDS header: signature + GUID + age + null-terminated PDB name.
    for match in re.finditer(b"RSDS", data):
        offset = match.start() + 24
        end = data.find(b"\x00", offset, min(len(data), offset + 1024))
        if end <= offset:
            continue
        value = data[offset:end].decode("utf-8", "replace")
        if not value.lower().endswith(".pdb"):
            continue
        counts["pdb_path"] += 1
        kind = path_kind(value)
        if kind:
            counts["pdb_" + kind] += 1
        if is_current_profile(value):
            counts["pdb_current_profile_path"] += 1


def zip_audit(archive: zipfile.ZipFile, prefix: str, findings: list, summary: Counter) -> None:
    summary["zip_entries"] += len(archive.infolist())
    for info in archive.infolist():
        if info.is_dir():
            continue
        relative = prefix + info.filename
        counts = Counter()
        name_kind = path_kind(info.filename)
        if name_kind:
            counts["archive_entry_" + name_kind] += 1
        suffix = Path(info.filename).suffix.lower()
        if suffix in TEXT_EXTENSIONS and info.file_size <= 8 * 1024 * 1024:
            content_hits(archive.read(info), counts)
        if suffix == ".pyc" and info.file_size <= 8 * 1024 * 1024:
            try:
                code = marshal.loads(archive.read(info)[16:])
                if isinstance(code, types.CodeType):
                    code_paths(code, counts)
                    summary["pyc_modules_inspected"] += 1
            except (ValueError, EOFError, TypeError):
                counts["pyc_read_error"] += 1
        if suffix == ".zip" and info.file_size <= 8 * 1024 * 1024:
            try:
                with zipfile.ZipFile(io.BytesIO(archive.read(info))) as nested:
                    zip_audit(nested, relative + "!", findings, summary)
            except zipfile.BadZipFile:
                counts["nested_zip_read_error"] += 1
        if any(counts.values()):
            findings.append({"file": relative, "categories": {k: v for k, v in counts.items() if v}})
            summary.update(counts)


def exe_audit(path: Path, findings: list, summary: Counter) -> None:
    reader = CArchiveReader(str(path))
    for name, entry in reader.toc.items():
        counts = Counter()
        typecode = entry[-1]
        if typecode == "z":
            pyz = reader.open_embedded_archive(name)
            for module_name in pyz.toc:
                code = pyz.extract(module_name)
                if not isinstance(code, types.CodeType):
                    continue
                module_counts = Counter()
                code_paths(code, module_counts)
                summary["pyz_modules_inspected"] += 1
                if module_counts:
                    findings.append({"file": path.name + "!" + name + "!" + module_name, "categories": dict(module_counts)})
                    summary.update(module_counts)
        elif typecode in {"s", "m", "M"}:
            try:
                code = marshal.loads(reader.extract(name))
                if isinstance(code, types.CodeType):
                    code_paths(code, counts)
                    summary["bootstrap_modules_inspected"] += 1
            except (ValueError, EOFError, TypeError):
                counts["code_read_error"] += 1
        if counts:
            findings.append({"file": path.name + "!" + name, "categories": dict(counts)})
            summary.update(counts)
    counts = Counter()
    data = path.read_bytes()
    content_hits(data, counts)
    pe_debug_paths(data, counts)
    if any(counts.values()):
        findings.append({"file": path.name, "categories": {k: v for k, v in counts.items() if v}})
        summary.update(counts)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()
    results = []
    for path in args.paths:
        findings: list[dict] = []
        summary = Counter()
        if path.suffix.lower() == ".exe":
            exe_audit(path, findings, summary)
        elif path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as archive:
                zip_audit(archive, "", findings, summary)
        elif path.is_dir():
            for item in path.rglob("*"):
                if item.suffix.lower() not in {".exe", ".dll", ".pyd"}:
                    continue
                counts = Counter()
                data = item.read_bytes()
                content_hits(data, counts)
                pe_debug_paths(data, counts)
                summary["pe_files_inspected"] += 1
                if any(counts.values()):
                    findings.append({"file": str(item.relative_to(path)), "categories": {k: v for k, v in counts.items() if v}})
                    summary.update(counts)
        results.append({"artifact": path.name, "summary": dict(summary), "findings": findings})
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
