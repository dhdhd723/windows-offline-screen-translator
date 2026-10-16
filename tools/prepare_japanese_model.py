"""Developer-only pinned M2M100 conversion. The app never imports/downloads this.

Run in a separate conversion environment with CPU PyTorch, Transformers,
SentencePiece and CTranslate2. Original weights are checked before loading.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil

from prepare_models import atomic_json, download_file, file_records, load_manifest, verify_entry

REPOSITORY = "facebook/m2m100_418M"
REVISION = "55c2e61bbf05dfb8d7abccdc3fae6fc8512fd636"
SOURCE_HASHES = {
    "pytorch_model.bin": "d907ea45e4e4b9db163382a6674f6218b3c59566fe06d77f4055c208b4e87ed1",
    "config.json": "df0ae43e4e4b0d7e3c97b7f447857a70ef6b6a2aa1f145cedbcc730d95f67134",
    "README.md": "1fd660f130aedc5ecf1796b47ab47d43d3c4b36541f5387b7adb3df75cb5dfdb",
    "sentencepiece.bpe.model": "d8f7c76ed2a5e0822be39f0a4f95a55eb19c78f4593ce609e2edbc2aea4d380a",
    "special_tokens_map.json": "c1a4f86c3874d279ae1b2a05162858db5dd6c61665d84223ed886cbcff08fda6",
    "tokenizer_config.json": "a53e6aa83da0b82565ed90c3849056307a9453843322ac5b8439ec4b9497fe48",
    "vocab.json": "b6e77e474aeea8f441363aca7614317c06381f3eacfe10fb9856d5081d1074cc",
}
FAIRSEQ_REVISION = "3d262bb25690e4eb2e7d3c1309b1e9c406ca4b99"
LICENSE_URL = f"https://raw.githubusercontent.com/facebookresearch/fairseq/{FAIRSEQ_REVISION}/LICENSE"


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare(root: Path, source_root: Path) -> None:
    manifest = load_manifest(root)
    old = manifest.get("translation", {}).get("ja-zh")
    if verify_entry(root, old):
        print("Japanese model pack already validated.", flush=True)
        return
    if old:
        raise RuntimeError("Existing Japanese entry is invalid; use a new model directory")
    source = source_root / REVISION
    source.mkdir(parents=True, exist_ok=True)
    for name, digest in SOURCE_HASHES.items():
        download_file(f"https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/{name}", source / name, digest)
        if sha256(source / name) != digest:
            raise RuntimeError("Pinned original source checksum mismatch")
    folder = root / "translation/ja-zh-int8"
    if folder.exists():
        raise RuntimeError("Japanese model destination exists; nothing overwritten")
    folder.parent.mkdir(parents=True, exist_ok=True)
    from ctranslate2.converters import TransformersConverter
    print("Converting pinned Japanese model to CPU INT8...", flush=True)
    converter = TransformersConverter(str(source), low_cpu_mem_usage=False)
    converter.convert(str(folder), quantization="int8")
    del converter
    gc.collect()
    for name in ("sentencepiece.bpe.model", "vocab.json", "tokenizer_config.json", "special_tokens_map.json"):
        shutil.copyfile(source / name, folder / name)
    shutil.copyfile(source / "README.md", folder / "MODEL_CARD.md")
    download_file(LICENSE_URL, folder / "LICENSE.txt")
    notice = (
        f"Model: {REPOSITORY}\nOriginal revision: {REVISION}\n"
        "Authors: Meta / Facebook AI Research, M2M100 and Fairseq contributors.\n"
        f"Model source: https://huggingface.co/{REPOSITORY}/tree/{REVISION}\n"
        "The original model card declares MIT. The Fairseq MIT text is retained unchanged.\n"
        f"License source: {LICENSE_URL}\n"
        "Changes: converted to CTranslate2 with INT8 weights; original SentencePiece/vocabulary retained.\n"
        "Application exposes Japanese to Chinese only, not a claim of general translation accuracy.\n"
        "No endorsement by the original authors is implied.\n"
    )
    (folder / "NOTICE.txt").write_text(notice, encoding="utf-8")
    # Converter can emit a shared vocabulary or equal source/target files.
    shared = folder / "shared_vocabulary.json"
    if not shared.is_file():
        first, second = folder / "source_vocabulary.json", folder / "target_vocabulary.json"
        if not first.is_file() or not second.is_file() or first.read_bytes() != second.read_bytes():
            raise RuntimeError("M2M100 converted vocabulary is not shared")
        shutil.copyfile(first, shared)
    entry = {
        "id": f"{REPOSITORY}@{REVISION[:12]}-ct2-int8-ja-zh-v1",
        "backend": "m2m100-ja-zh-v1", "path": "translation/ja-zh-int8", "license": "MIT",
        "source": {"repository": REPOSITORY, "revision": REVISION, "sha256": SOURCE_HASHES},
        "conversion": {"ctranslate2": importlib.metadata.version("ctranslate2"),
                       "transformers": importlib.metadata.version("transformers"),
                       "torch": importlib.metadata.version("torch"), "quantization": "int8"},
        "files": file_records(root, folder),
    }
    manifest.setdefault("translation", {})["ja-zh"] = entry
    if not verify_entry(root, entry):
        raise RuntimeError("Converted Japanese files failed verification")
    atomic_json(root / "manifest.json", manifest)
    print(json.dumps({"japanese_model_prepared": True, "files": len(entry["files"]),
                      "model_bytes": (folder / "model.bin").stat().st_size}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models-dir", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.models_dir.resolve(), args.source_dir.resolve())
