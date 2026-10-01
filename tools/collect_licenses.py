"""Collect notices from the packages actually intended for the runtime bundle."""
from __future__ import annotations

import argparse
from importlib import metadata
from pathlib import Path
import shutil
import sys

RUNTIME_PACKAGES = [
    "PySide6", "PySide6_Essentials", "PySide6_Addons", "shiboken6", "onnxruntime", "ctranslate2",
    "sentencepiece", "numpy", "opencv-python", "mss", "rapidocr", "rapidfuzz", "pyclipper",
    "Shapely", "Pillow", "tqdm", "omegaconf", "antlr4-python3-runtime", "requests",
    "colorlog", "six", "PyYAML", "protobuf", "flatbuffers", "packaging", "sympy",
    "mpmath", "certifi", "charset_normalizer", "idna", "urllib3", "colorama",
]


def is_notice_file(file: Path) -> bool:
    """A package named 'licenses' can contain code, not only legal texts."""
    if any(part in {"..", "__pycache__"} for part in file.parts):
        return False
    if file.suffix.lower() not in {"", ".txt", ".md", ".html", ".htm", ".rst", ".apache", ".bsd"}:
        return False
    return any(word in str(file).lower() for word in ("license", "licence", "copyright", "notice"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    args.destination.mkdir(parents=True, exist_ok=True)
    notices = ["ScreenTranslator third-party software notices\n",
               "Qt/PySide6 is distributed as replaceable dynamic libraries under LGPLv3.\n",
               "ScreenTranslator application source and build instructions are in source/.\n",
               "Complete upstream texts not present in wheels are in LICENSES/upstream/.\n",
               "The original model attribution and licenses are in models/*/LICENSE.txt and NOTICE.txt.\n",
               "Python: https://docs.python.org/3/license.html\n"]
    for package in RUNTIME_PACKAGES:
        distribution = metadata.distribution(package)
        license_name = (distribution.metadata.get("License-Expression") or
                        distribution.metadata.get("License") or "See bundled license")
        notices.append(f"\n{package} {distribution.version}\nLicense metadata: {license_name}\n"
                       f"Home: {distribution.metadata.get('Home-page', '')}\n")
        for file in distribution.files or []:
            if is_notice_file(Path(file)):
                original = Path(distribution.locate_file(file))
                if original.is_file() and original.stat().st_size <= 2_000_000:
                    target = args.destination / package / str(file)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(original, target)
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.is_file():
        shutil.copy2(python_license, args.destination / "Python-LICENSE.txt")
    packaging = Path(__file__).resolve().parents[1] / "packaging"
    for folder, name in (("extra-notices", "upstream"), ("qt-notices", "Qt")):
        supplemental = packaging / folder
        if supplemental.is_dir():
            shutil.copytree(supplemental, args.destination / name, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("*.whl", "*.part", "__pycache__", "*.pyc", "*.pyo"))
    (args.destination / "ThirdPartyNotices.txt").write_text("\n".join(notices), encoding="utf-8")


if __name__ == "__main__":
    main()
