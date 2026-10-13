from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from ...core.game_terms import translate_known_game_line, translation_identity
from ...paths import model_root
from .. import (InferenceCancelled, InputLimitError, ModelFilesError,
                checked_path, read_manifest, verify_files)
from .tokenizer import MarianSentencePieceTokenizer, split_text_for_model


log = logging.getLogger(__name__)
REQUIRED_FILES = ("config.json", "model.bin", "source.spm", "target.spm", "vocab.json", "tokenizer_config.json")


class CTranslate2Engine:
    """Lazy, CPU-only OPUS-MT translators, called by one inference worker."""

    def __init__(self, model_dir: str | Path | None = None, cpu_threads: int = 2):
        self.root = Path(model_dir).resolve() if model_dir else model_root()
        if self.root.name == "translation":
            self.root = self.root.parent
        self.cpu_threads = max(1, min(4, int(cpu_threads)))
        self._translators: dict[str, Any] = {}
        self._tokenizers: dict[str, MarianSentencePieceTokenizer] = {}
        self._ids: dict[str, str] = {}

    def configure_threads(self, cpu_threads: int) -> None:
        """Called only by the inference worker, between jobs."""
        count = max(1, min(4, int(cpu_threads)))
        if count != self.cpu_threads:
            self.cpu_threads = count
            self._translators.clear()
            self._tokenizers.clear()

    def model_id(self, direction: str) -> str:
        self._check_direction(direction)
        if direction not in self._ids:
            entry = read_manifest(self.root).get("translation", {}).get(direction)
            if not entry or not isinstance(entry.get("id"), str) or not entry["id"]:
                raise ModelFilesError(f"本地 {direction} 翻译模型缺失，请使用包含模型的完整程序包。")
            self._ids[direction] = entry["id"]
        return translation_identity(self._ids[direction], direction)

    @staticmethod
    def _check_direction(direction: str) -> None:
        if direction not in {"zh-en", "en-zh"}:
            raise ValueError(f"Unsupported translation direction: {direction}")

    def _initialize(self, direction: str) -> None:
        self._check_direction(direction)
        if direction in self._translators:
            return
        entry = read_manifest(self.root).get("translation", {}).get(direction)
        if (not entry or not entry.get("path") or not isinstance(entry.get("id"), str)
                or not entry["id"]):
            raise ModelFilesError(f"本地 {direction} 翻译模型缺失，请使用包含模型的完整程序包。")
        folder = checked_path(self.root, entry["path"])
        required = [f"{entry['path']}/{filename}" for filename in REQUIRED_FILES]
        # CT2 supports either separate or shared converted vocabularies.
        vocab_names = ("source_vocabulary.json", "target_vocabulary.json")
        if (folder / "shared_vocabulary.json").is_file():
            vocab_names = ("shared_vocabulary.json",)
        required.extend(f"{entry['path']}/{filename}" for filename in vocab_names)
        verify_files(self.root, entry, required)
        try:
            import ctranslate2
        except ImportError as exc:
            raise ModelFilesError("翻译运行组件缺失，请重新解压完整程序包。") from exc
        try:
            tokenizer = MarianSentencePieceTokenizer(folder)
            translator = ctranslate2.Translator(
                str(folder), device="cpu", compute_type="int8",
                inter_threads=1, intra_threads=self.cpu_threads, max_queued_batches=1,
            )
        except (ImportError, OSError, ValueError, RuntimeError) as exc:
            raise ModelFilesError("本地翻译模型无法加载，请重新解压完整程序包。") from exc
        self._tokenizers[direction] = tokenizer
        self._translators[direction] = translator
        self._ids[direction] = entry["id"]
        log.info("Initialized offline translator: %s", entry["id"])

    def warmup(self, direction: str = "en-zh") -> None:
        self.translate("Hello." if direction == "en-zh" else "你好。", direction)

    def translate_cancellable(self, text: str, direction: str,
                              cancel_check: Callable[[], bool]) -> str:
        """Check source freshness between chunks; never interrupt a native call."""
        return self.translate(text, direction, cancel_check=cancel_check)

    @staticmethod
    def _check_cancel(cancel_check: Callable[[], bool] | None) -> None:
        if cancel_check is not None and cancel_check():
            raise InferenceCancelled()

    def translate(self, text: str, direction: str,
                  *, cancel_check: Callable[[], bool] | None = None) -> str:
        text = text.strip()
        if not text:
            return ""
        if len(text) > 16000:
            raise InputLimitError("框选文字过多，请缩小翻译区域；原文没有被截断。")
        self._check_cancel(cancel_check)
        self._initialize(direction)
        tokenizer = self._tokenizers[direction]
        paragraphs = text.splitlines()
        translated = []
        for paragraph in paragraphs:
            self._check_cancel(cancel_check)
            if not paragraph.strip():
                translated.append("")
                continue
            trusted = translate_known_game_line(paragraph, direction)
            if trusted is not None:
                translated.append(trusted)
                continue
            chunks = split_text_for_model(paragraph, tokenizer, max_tokens=192)
            outputs = [self._translate_chunk(chunk, direction, cancel_check=cancel_check)
                       for chunk in chunks]
            joiner = " " if direction == "zh-en" else ""
            translated.append(joiner.join(outputs))
        self._check_cancel(cancel_check)
        return "\n".join(translated).strip()

    def _translate_chunk(self, text: str, direction: str, depth: int = 0,
                         *, cancel_check: Callable[[], bool] | None = None) -> str:
        self._check_cancel(cancel_check)
        tokenizer = self._tokenizers[direction]
        translator = self._translators[direction]
        source = tokenizer.encode(text)
        result = translator.translate_batch(
            [source], beam_size=2, max_input_length=192,
            max_decoding_length=384, return_end_token=True,
            repetition_penalty=1.05, no_repeat_ngram_size=3,
        )[0]
        if not result.hypotheses or not result.hypotheses[0]:
            raise RuntimeError("本地翻译没有返回结果，请重试或缩小翻译区域。")
        tokens = result.hypotheses[0]
        if len(tokens) >= 384 and tokens[-1] != tokenizer.eos:
            # If output reaches the cap, split and retry rather than silently
            # displaying a translated prefix of the input.
            if depth >= 3 or len(text) < 4:
                raise InputLimitError("译文超过长度限制，请缩小翻译区域；原文没有被截断。")
            reduced_limit = max(4, len(source) // 2)
            chunks = split_text_for_model(text, tokenizer, max_tokens=reduced_limit)
            if len(chunks) <= 1:
                raise InputLimitError("译文超过长度限制，请缩小翻译区域；原文没有被截断。")
            joiner = " " if direction == "zh-en" else ""
            return joiner.join(self._translate_chunk(chunk, direction, depth + 1,
                                                     cancel_check=cancel_check) for chunk in chunks)
        self._check_cancel(cancel_check)
        return tokenizer.decode(tokens)
