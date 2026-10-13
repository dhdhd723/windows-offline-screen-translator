"""Offline inference utilities; importing this module does not load any model."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


class PermanentInferenceError(RuntimeError):
    """Retry only after the source, settings or local model pack changes."""


class InputLimitError(PermanentInferenceError, ValueError):
    """The complete source cannot be translated within safe local limits."""


class InferenceCancelled(Exception):
    """Cooperative cancellation at a safe boundary between native calls."""


class ModelFilesError(PermanentInferenceError):
    """A local model pack is incomplete or modified."""


def read_manifest(root: Path) -> dict:
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ModelFilesError("本地模型包缺失或损坏，请重新解压完整程序包。") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ModelFilesError("本地模型包版本不兼容，请重新解压完整程序包。")
    ocr = manifest.get("ocr")
    translation = manifest.get("translation")
    if (ocr is not None and (not isinstance(ocr, dict) or not isinstance(ocr.get("config", {}), dict))
            or translation is not None and (not isinstance(translation, dict)
                or any(not isinstance(entry, dict) for entry in translation.values()))):
        raise ModelFilesError("本地模型清单结构损坏，请重新解压完整程序包。")
    return manifest


def checked_path(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or "\x00" in relative:
        raise ModelFilesError("本地模型清单包含无效的文件路径。")
    try:
        root_resolved = root.resolve()
        path = (root_resolved / relative).resolve()
    except (OSError, ValueError) as exc:
        raise ModelFilesError("本地模型文件路径无法读取，请重新解压完整程序包。") from exc
    if not path.is_relative_to(root_resolved):
        raise ModelFilesError("模型文件路径超出了本地模型目录。")
    return path


def verify_files(root: Path, entry: dict, required: list[str]) -> None:
    """Check only inference files once at lazy initialization, never per frame."""
    records = entry.get("files", {})
    if not isinstance(records, dict):
        raise ModelFilesError("本地模型文件清单损坏，请重新解压完整程序包。")
    for relative in required:
        path = checked_path(root, relative)
        record = records.get(relative)
        try:
            if not isinstance(record, dict) or not record or not path.is_file():
                raise ModelFilesError(f"本地模型缺少文件：{relative}。请重新解压完整程序包。")
            if path.stat().st_size != record.get("size"):
                raise ModelFilesError(f"本地模型文件大小异常：{relative}。")
            checksum = hashlib.sha256()
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    checksum.update(block)
            if checksum.hexdigest() != record.get("sha256"):
                raise ModelFilesError(f"本地模型校验失败：{relative}。请重新解压完整程序包。")
        except OSError as exc:
            raise ModelFilesError(f"本地模型文件无法读取：{relative}。请重新解压完整程序包。") from exc


__all__ = ["PermanentInferenceError", "InputLimitError", "InferenceCancelled", "ModelFilesError",
           "read_manifest", "checked_path", "verify_files"]
