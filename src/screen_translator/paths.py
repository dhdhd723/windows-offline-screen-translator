from __future__ import annotations

import os
import sys
from pathlib import Path


def install_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def model_root() -> Path:
    override = os.environ.get("SCREEN_TRANSLATOR_MODELS")
    return Path(override).resolve() if override else install_root() / "models"


def data_root() -> Path:
    override = os.environ.get("SCREEN_TRANSLATOR_DATA")
    if override:
        root = Path(override).resolve()
    else:
        root = Path(os.environ.get("LOCALAPPDATA", str(install_root()))) / "ScreenTranslator"
    root.mkdir(parents=True, exist_ok=True)
    return root
