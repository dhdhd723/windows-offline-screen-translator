"""Explicit, versioned consent before using redistributed Microsoft runtimes.

The consent record belongs to the user's local configuration, not the program
directory. It is not a telemetry event and is never sent elsewhere.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import sys
from typing import Callable

from .contracts import Settings
from .paths import install_root
from .storage.settings import SettingsStore


TERMS_REVISION = "microsoft-runtime-2026-10-02-v1"
TERMS_FILENAME = "final-user-terms.txt"


@dataclass(frozen=True)
class RuntimeTerms:
    text: str
    version: str
    path: Path


@dataclass(frozen=True)
class ConsentResult:
    accepted: bool
    version: str = ""
    error: str = ""
    acceptance: str = ""
    failure: str = ""


def load_runtime_terms(root: Path | None = None, *, frozen: bool | None = None) -> RuntimeTerms:
    """Read the shipped terms; do not substitute terms from another install."""
    root = install_root() if root is None else Path(root)
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    relative = (Path("LICENSES/upstream/microsoft-runtime") if frozen else
                Path("packaging/extra-notices/microsoft-runtime"))
    path = root / relative / TERMS_FILENAME
    if path.stat().st_size > 262144:
        raise ValueError("Microsoft runtime terms file is too large")
    encoded = path.read_bytes()
    text = encoded.decode("utf-8-sig")
    if not text.strip():
        raise ValueError("Microsoft runtime terms file is empty")
    # A changed document requires a new decision, even if a distributor forgets
    # to change the human-readable revision label.
    digest = hashlib.sha256(encoded).hexdigest()
    return RuntimeTerms(text, f"{TERMS_REVISION}:{digest}", path)


def authorize_runtime_terms(
    settings: Settings,
    store: SettingsStore,
    *,
    explicit_accept: bool = False,
    prompt: Callable[[RuntimeTerms], bool] | None = None,
    root: Path | None = None,
    frozen: bool | None = None,
) -> ConsentResult:
    """Fail closed without a readable document and an explicit or saved choice.

    ``explicit_accept`` is only exposed for deliberately authorized diagnostic
    runs. Normal GUI startup always obtains the first decision from the dialog.
    No Windows input hooks or capture providers are needed by this function.
    """
    try:
        terms = load_runtime_terms(root, frozen=frozen)
    except (OSError, UnicodeError, ValueError):
        return ConsentResult(False, error="微软运行库使用条款缺失或无法读取。请重新解压完整发布包；程序未启动监控。",
                             failure="document")
    if settings.runtime_terms_version == terms.version:
        return ConsentResult(True, terms.version, acceptance="saved")
    if not explicit_accept and (prompt is None or not prompt(terms)):
        return ConsentResult(False, terms.version,
                             "尚未同意微软运行库使用条款，程序未启动监控。", failure="declined")
    old_version = settings.runtime_terms_version
    settings.runtime_terms_version = terms.version
    try:
        store.save(settings)
    except (OSError, ValueError, TypeError):
        settings.runtime_terms_version = old_version
        return ConsentResult(False, terms.version,
                             "无法保存使用条款确认。请检查用户数据目录是否可写；程序未启动监控。", failure="save")
    return ConsentResult(True, terms.version,
                         acceptance="explicit-diagnostic" if explicit_accept else "dialog")
