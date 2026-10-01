"""Prepare the redistributable offline model pack (developer machine only).

The application never imports this module and never downloads models. Run this
script with the development environment, then ship the resulting models folder.
Downloads are pinned; every installed file is registered with a SHA-256 hash.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import sys
import time
import urllib.request


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OCR_SOURCES = {
    "det": {
        "url": "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/onnx/PP-OCRv5/det/ch_PP-OCRv5_det_mobile.onnx",
        "sha256": "4d97c44a20d30a81aad087d6a396b08f786c4635742afc391f6621f5c6ae78ae",
    },
    "rec": {
        "url": "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/onnx/PP-OCRv5/rec/ch_PP-OCRv5_rec_mobile.onnx",
        "sha256": "5825fc7ebf84ae7a412be049820b4d86d77620f204a041697b0494669b1742c5",
    },
}
TRANSLATION_SOURCES = {
    "zh-en": {
        "repo": "Helsinki-NLP/opus-mt-zh-en",
        "revision": "cf109095479db38d6df799875e34039d4938aaa6",
        "license": "CC-BY-4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/legalcode.txt",
    },
    "en-zh": {
        "repo": "Helsinki-NLP/opus-mt-en-zh",
        "revision": "408d9bc410a388e1d9aef112a2daba955b945255",
        "license": "Apache-2.0",
        "license_url": "https://www.apache.org/licenses/LICENSE-2.0.txt",
    },
}
HF_FILES = [
    "config.json", "generation_config.json", "pytorch_model.bin", "source.spm",
    "target.spm", "vocab.json", "tokenizer_config.json", "README.md",
]
TOKENIZER_FILES = ["source.spm", "target.spm", "vocab.json", "tokenizer_config.json"]
APACHE_LICENSE_URL = "https://www.apache.org/licenses/LICENSE-2.0.txt"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download_file(url: str, destination: Path, expected_sha256: str | None = None) -> None:
    """Retry downloads without exposing a half-written installed model."""
    if destination.is_file() and (expected_sha256 is None or sha256_file(destination) == expected_sha256):
        print(f"Already present: {destination.name}", flush=True)
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    last_error: Exception | None = None
    for attempt in range(1, 5):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "ScreenTranslator-model-preparation/1.0"})
            with urllib.request.urlopen(request, timeout=90) as response, partial.open("wb") as handle:
                length = int(response.headers.get("Content-Length", "0"))
                downloaded = 0
                next_report = 32 * 1024 * 1024
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    downloaded += len(chunk)
                    if downloaded >= next_report:
                        suffix = f" / {length / 1024**2:.1f} MiB" if length else " MiB"
                        print(f"{destination.name}: {downloaded / 1024**2:.1f}{suffix}", flush=True)
                        next_report += 32 * 1024 * 1024
            if length and downloaded != length:
                raise ValueError(f"Incomplete download: {destination.name} ({downloaded}/{length} bytes)")
            if expected_sha256 and sha256_file(partial) != expected_sha256:
                raise ValueError(f"SHA-256 mismatch: {destination.name}")
            os.replace(partial, destination)
            print(f"Downloaded: {destination.name}", flush=True)
            return
        except Exception as exc:
            last_error = exc
            print(f"Download attempt {attempt} failed for {destination.name}: {exc}", flush=True)
            if attempt < 4:
                time.sleep(min(3 * attempt, 9))
    raise RuntimeError(f"Could not download {url}: {last_error}") from last_error


def atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".tmp")
    partial.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(partial, path)


def file_records(root: Path, folder: Path) -> dict[str, dict]:
    return {
        path.relative_to(root).as_posix(): {"sha256": sha256_file(path), "size": path.stat().st_size}
        for path in sorted(folder.rglob("*")) if path.is_file() and not path.name.endswith((".part", ".tmp"))
    }


def load_manifest(root: Path) -> dict:
    path = root / "manifest.json"
    if path.is_file():
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest.get("schema_version") != 1:
            raise ValueError("Unsupported model manifest schema")
        return manifest
    return {"schema_version": 1, "ocr": None, "translation": {}}


def verify_entry(root: Path, entry: dict | None) -> bool:
    if not entry or not entry.get("files"):
        return False
    root_resolved = root.resolve()
    for relative, record in entry["files"].items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root_resolved) or not path.is_file():
            return False
        if path.stat().st_size != record["size"] or sha256_file(path) != record["sha256"]:
            return False
    return True


def prepare_ocr(root: Path, manifest: dict, force: bool = False) -> None:
    if not force and verify_entry(root, manifest.get("ocr")):
        print("OCR model pack already validated.", flush=True)
        return
    folder = root / "ocr"
    folder.mkdir(parents=True, exist_ok=True)
    for name, source in OCR_SOURCES.items():
        print(f"Preparing OCR {name}...", flush=True)
        download_file(source["url"], folder / f"{name}.onnx", source["sha256"])

    # RapidAI's ONNX recognition model embeds its exact dictionary. Extract that
    # dictionary instead of pairing PP-OCRv5 with a potentially wrong v4 file.
    import onnxruntime as ort
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(folder / "rec.onnx"), sess_options=options, providers=["CPUExecutionProvider"])
    characters = session.get_modelmeta().custom_metadata_map.get("character")
    if not characters or len(characters.splitlines()) < 100:
        raise RuntimeError("The recognition ONNX has no valid embedded character dictionary")
    (folder / "keys.txt").write_text(characters + "\n", encoding="utf-8")
    del session
    gc.collect()
    download_file(APACHE_LICENSE_URL, folder / "LICENSE.txt")
    notice = (
        "PP-OCRv5 mobile detection and Chinese/English recognition\n"
        "Authors: PaddlePaddle / PaddleOCR contributors. ONNX conversion: RapidAI / RapidOCR contributors.\n"
        "License: Apache License, Version 2.0.\n"
        "Source: https://github.com/PaddlePaddle/PaddleOCR\n"
        "ONNX source: https://github.com/RapidAI/RapidOCR\n"
        "Converted ONNX release: RapidAI/RapidOCR v3.9.2\n"
        "keys.txt is extracted without modification from ONNX metadata.\n"
    )
    (folder / "NOTICE.txt").write_text(notice, encoding="utf-8")
    manifest["ocr"] = {
        "id": "PP-OCRv5-mobile-RapidAI-v3.9.2",
        "license": "Apache-2.0",
        "config": {"det": "ocr/det.onnx", "rec": "ocr/rec.onnx", "keys": "ocr/keys.txt"},
        "sources": OCR_SOURCES,
        "files": file_records(root, folder),
    }
    atomic_json(root / "manifest.json", manifest)
    print("OCR prepared and checksummed.", flush=True)


def prepare_translation(root: Path, source_root: Path, manifest: dict, direction: str, force: bool = False) -> None:
    old_entry = manifest.get("translation", {}).get(direction)
    if not force and verify_entry(root, old_entry):
        print(f"Translation {direction} model pack already validated.", flush=True)
        return
    metadata = TRANSLATION_SOURCES[direction]
    source = source_root / f"{direction}-{metadata['revision']}"
    source.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {metadata['repo']} @ {metadata['revision']}...", flush=True)

    # Direct HTTPS resolve URLs avoid an API call or the optional Xet helper.
    # Endpoints can be explicitly overridden for a developer's regional mirror.
    endpoint = os.environ.get("HF_ENDPOINT", "https://huggingface.co").rstrip("/")
    for filename in HF_FILES:
        url = f"{endpoint}/{metadata['repo']}/resolve/{metadata['revision']}/{filename}"
        download_file(url, source / filename)

    from ctranslate2.converters import TransformersConverter
    folder = root / "translation" / f"{direction}-int8"
    # Conversion output lives in a sibling staging folder until fully ready.
    staging = folder.with_name(folder.name + "-staging")
    print(f"Converting {direction} to CTranslate2 INT8...", flush=True)
    converter = TransformersConverter(str(source), low_cpu_mem_usage=False)
    converter.convert(str(staging), quantization="int8", force=True)
    del converter
    gc.collect()
    for filename in TOKENIZER_FILES:
        shutil.copy2(source / filename, staging / filename)
    shutil.copy2(source / "generation_config.json", staging / "generation_config.json")
    shutil.copy2(source / "README.md", staging / "MODEL_CARD.md")
    download_file(metadata["license_url"], staging / "LICENSE.txt")
    notice = (
        f"Model: {metadata['repo']}\n"
        f"Authors: Helsinki-NLP / OPUS-MT contributors\n"
        f"Revision: {metadata['revision']}\n"
        f"Source: https://huggingface.co/{metadata['repo']}/tree/{metadata['revision']}\n"
        f"License: {metadata['license']} (see LICENSE.txt and MODEL_CARD.md)\n"
        "Changes: converted from Marian/PyTorch to CTranslate2, INT8 weight quantization.\n"
        "Original tokenizer and vocab files are included unchanged.\n"
        "No endorsement by the original authors is implied.\n"
    )
    (staging / "NOTICE.txt").write_text(notice, encoding="utf-8")
    required = ["model.bin", "config.json", "source_vocabulary.json", "target_vocabulary.json", *TOKENIZER_FILES]
    for filename in required:
        if not (staging / filename).is_file():
            # CT2 writes shared_vocabulary.json when the source/target vocab is
            # shared. It is equivalent; install explicit copies for uniformity.
            shared = staging / "shared_vocabulary.json"
            if filename in {"source_vocabulary.json", "target_vocabulary.json"} and shared.is_file():
                shutil.copy2(shared, staging / filename)
            else:
                raise RuntimeError(f"Converted model missing {filename}")
    folder.mkdir(parents=True, exist_ok=True)
    for filename in staging.iterdir():
        if filename.is_file():
            os.replace(filename, folder / filename.name)
    # Keep staging empty; no recursive removal of model folders is performed.
    staging.rmdir()
    entry = {
        "id": f"{metadata['repo']}@{metadata['revision'][:12]}-ct2-int8-v1",
        "path": f"translation/{direction}-int8",
        "source": metadata,
        "license": metadata["license"],
        "conversion": {"ctranslate2": importlib.metadata.version("ctranslate2"), "quantization": "int8"},
        "files": file_records(root, folder),
    }
    manifest.setdefault("translation", {})[direction] = entry
    atomic_json(root / "manifest.json", manifest)
    print(f"Translation {direction} prepared and checksummed.", flush=True)


def validate(root: Path, manifest: dict, require_ocr: bool = True, directions: list[str] | None = None) -> None:
    errors = []
    if require_ocr and not verify_entry(root, manifest.get("ocr")):
        errors.append("OCR missing or checksum mismatch")
    for direction in directions if directions is not None else list(TRANSLATION_SOURCES):
        if not verify_entry(root, manifest.get("translation", {}).get(direction)):
            errors.append(f"Translation {direction} missing or checksum mismatch")
    if errors:
        raise RuntimeError("; ".join(errors))
    print("All selected model files pass SHA-256 validation.", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models-dir", type=Path, default=PROJECT_ROOT / "models")
    parser.add_argument("--source-dir", type=Path, default=PROJECT_ROOT / "build" / "model_sources")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--ocr-only", action="store_true")
    selection.add_argument("--translation-only", action="store_true")
    parser.add_argument("--direction", action="append", choices=list(TRANSLATION_SOURCES), help="Only prepare the specified translation direction(s)")
    parser.add_argument("--validate-only", action="store_true", help="No network or conversion; verify installed files")
    parser.add_argument("--force", action="store_true", help="Recreate selected entries, retaining correctly downloaded sources")
    args = parser.parse_args()
    root = args.models_dir.resolve()
    manifest = load_manifest(root)
    directions = [] if args.ocr_only else (args.direction or ["en-zh", "zh-en"])
    use_ocr = not args.translation_only
    try:
        if not args.validate_only:
            if use_ocr:
                prepare_ocr(root, manifest, force=args.force)
            for direction in directions:
                prepare_translation(root, args.source_dir.resolve(), manifest, direction, force=args.force)
        validate(root, manifest, use_ocr, directions)
    except Exception as exc:
        print(f"Model preparation failed: {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
