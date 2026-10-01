"""Offline inference utilities; importing this module does not load any model."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


class ModelFilesError(RuntimeError):
    """A local model pack is incomplete or modified."""


def read_manifest(root: Path) -> dict:
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ModelFilesError("本地模型包缺失或损坏，请重新解压完整程序包。") from exc
    if manifest.get("schema_version") != 1:
        raise ModelFilesError("本地模型包版本不兼容，请重新解压完整程序包。")
    return manifest


def checked_path(root: Path, relative: str) -> Path:
    root_resolved = root.resolve()
    path = (root_resolved / relative).resolve()
    if not path.is_relative_to(root_resolved):
        raise ModelFilesError("模型文件路径超出了本地模型目录。")
    return path


def verify_files(root: Path, entry: dict, required: list[str]) -> None:
    """Check only inference files once at lazy initialization, never per frame."""
    records = entry.get("files", {})
    for relative in required:
        path = checked_path(root, relative)
        record = records.get(relative)
        if not record or not path.is_file():
            raise ModelFilesError(f"本地模型缺少文件：{relative}。请重新解压完整程序包。")
        if path.stat().st_size != record.get("size"):
            raise ModelFilesError(f"本地模型文件大小异常：{relative}。")
        checksum = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                checksum.update(block)
        if checksum.hexdigest() != record.get("sha256"):
            raise ModelFilesError(f"本地模型校验失败：{relative}。请重新解压完整程序包。")


__all__ = ["ModelFilesError", "read_manifest", "checked_path", "verify_files"]
