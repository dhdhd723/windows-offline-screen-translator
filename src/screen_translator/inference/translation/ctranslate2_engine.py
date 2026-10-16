from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Callable

from ...core.game_terms import translate_known_game_line, translation_identity
from ...core.chinese_script import SCRIPT_POLICY_ID, to_simplified
from ...core.translation_structure import STRUCTURE_POLICY_ID, split_complete_sentences
from ...core.scoped_translation_terms import (TERMS_POLICY_ID, plan_translation_fragments,
                                             prepare_source_idioms)
from ...paths import model_root
from .. import (InferenceCancelled, InputLimitError, ModelFilesError,
                checked_path, read_manifest, verify_files)
from .tokenizer import MarianSentencePieceTokenizer, split_text_for_model


log = logging.getLogger(__name__)
REQUIRED_FILES = ("config.json", "model.bin", "source.spm", "target.spm", "vocab.json", "tokenizer_config.json")
TRANSLATION_POLICY_ID = ("quality-policy-v1|" + SCRIPT_POLICY_ID + "|"
                         + STRUCTURE_POLICY_ID + "|" + TERMS_POLICY_ID
                         + "|beam2-repeat1.05-ngram3-target-tag-none")


def format_translation_output(text: str, direction: str) -> str:
    """Normalize only translated Chinese; callers keep identity prefixes apart."""
    return to_simplified(text) if direction == "en-zh" else text


class CTranslate2Engine:
    """Lazy, CPU-only OPUS-MT translators, called by one inference worker."""

    quality_policy_id = TRANSLATION_POLICY_ID
    formats_simplified_output = True

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
        identity = translation_identity(self._ids[direction], direction)
        return identity + "|" + TRANSLATION_POLICY_ID if direction == "en-zh" else identity

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
            if direction == "en-zh":
                prepared = prepare_source_idioms(paragraph, context=paragraph)
                units = split_complete_sentences(prepared)
                outputs = [self._translate_sentence(unit, paragraph, cancel_check)
                           for unit in units]
                # Keep hard input/message rows only. Sentence splitting must
                # not manufacture new chat messages or reorder the paragraph.
                translated.append(" ".join(output for output in outputs if output))
            else:
                chunks = split_text_for_model(paragraph, tokenizer, max_tokens=192)
                translated.append(" ".join(self._translate_chunk(chunk, direction,
                    cancel_check=cancel_check) for chunk in chunks))
        self._check_cancel(cancel_check)
        return format_translation_output("\n".join(translated).strip(), direction)

    def _translate_sentence(self, sentence: str, context: str,
                            cancel_check: Callable[[], bool] | None) -> str:
        parts = []
        tokenizer = self._tokenizers["en-zh"]
        for fragment in plan_translation_fragments(sentence, context=context):
            self._check_cancel(cancel_check)
            if fragment.literal:
                parts.append(fragment.text)
                continue
            source = fragment.text.strip()
            if not source:
                continue
            # Punctuation/emoji-only gaps and already-Chinese headings are not
            # English sentences. Preserve them rather than asking the model to
            # invent context or translate a protected name's adjacent separator.
            if not re.search(r"[A-Za-z]", source):
                parts.append(source)
                continue
            chunks = split_text_for_model(source, tokenizer, max_tokens=192)
            result = "".join(self._translate_chunk(chunk, "en-zh",
                cancel_check=cancel_check) for chunk in chunks)
            if not result.strip():
                raise RuntimeError("本地翻译有一段未返回译文，请缩小区域后重试。")
            parts.append(result)
        self._check_cancel(cancel_check)
        return "".join(parts).strip()

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
