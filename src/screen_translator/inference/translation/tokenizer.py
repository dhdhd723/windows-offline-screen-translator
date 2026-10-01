"""Marian tokenization without PyTorch or Transformers at runtime.

SentencePiece IDs are deliberately never passed to Marian: the external Marian
vocab IDs have a different order. We map pieces through vocab.json, then feed
the resulting token strings to CTranslate2's converted vocabulary.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Protocol


class TokenCounter(Protocol):
    def encode(self, text: str) -> list[str]: ...


class MarianSentencePieceTokenizer:
    def __init__(self, folder: str | Path):
        import sentencepiece as spm
        folder = Path(folder)
        self.vocab: dict[str, int] = json.loads((folder / "vocab.json").read_text(encoding="utf-8"))
        config = json.loads((folder / "tokenizer_config.json").read_text(encoding="utf-8"))
        self.unk = config.get("unk_token", "<unk>")
        self.eos = config.get("eos_token", "</s>")
        self.pad = config.get("pad_token", "<pad>")
        for name in ("unk", "eos", "pad"):
            token = getattr(self, name)
            if isinstance(token, dict):
                setattr(self, name, token["content"])
        if self.unk not in self.vocab or self.eos not in self.vocab:
            raise ValueError("Marian vocabulary has no UNK/EOS tokens")
        self.inverse_vocab = {value: key for key, value in self.vocab.items()}
        # Python resolves Unicode Windows paths; the native SentencePiece loader
        # receives bytes and does not need to open a non-ASCII path itself.
        self.source = spm.SentencePieceProcessor(model_proto=(folder / "source.spm").read_bytes())
        self.target = spm.SentencePieceProcessor(model_proto=(folder / "target.spm").read_bytes())
        self.special_tokens = {self.unk, self.eos, self.pad, "<eop>", "<eod>"}
        for token in config.get("additional_special_tokens", []):
            self.special_tokens.add(token["content"] if isinstance(token, dict) else token)

    def encode(self, text: str) -> list[str]:
        prefix = []
        if text.startswith(">>"):
            end = text.find("<<")
            if end >= 0:
                prefix = [text[:end + 2]]
                text = text[end + 2:]
        pieces = prefix + self.source.encode(text, out_type=str)
        # Going through the Marian map is necessary even though CT2 accepts
        # strings: a SentencePiece piece absent from vocab.json maps to UNK.
        tokens = [self.inverse_vocab[self.vocab.get(piece, self.vocab[self.unk])] for piece in pieces]
        return tokens + [self.eos]

    def decode(self, tokens: list[str]) -> str:
        pieces = [token for token in tokens if token not in self.special_tokens]
        return self.target.decode(pieces).replace("▁", " ").strip()


def split_text_for_model(text: str, tokenizer: TokenCounter, max_tokens: int = 192) -> list[str]:
    """Split on sentences/word boundaries, with a character fallback; never drop text.

    Whitespace at cut points may be normalized, but every non-whitespace source
    character is included exactly once, and each chunk fits including EOS.
    """
    text = text.strip()
    if not text:
        return []
    if max_tokens < 4:
        raise ValueError("max_tokens must allow at least four tokens")
    if len(tokenizer.encode(text)) <= max_tokens:
        return [text]
    # Keep sentence-ending punctuation attached to its preceding sentence.
    sentences = re.findall(r"[^。！？.!?]+[。！？.!?]*|[。！？.!?]+", text)
    chunks: list[str] = []
    pending = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        candidate = (pending + " " + sentence).strip() if pending else sentence
        if len(tokenizer.encode(candidate)) <= max_tokens:
            pending = candidate
            continue
        if pending:
            chunks.append(pending)
            pending = ""
        while len(tokenizer.encode(sentence)) > max_tokens:
            # Binary-search an input prefix, not output token truncation. This
            # preserves accented text, CJK, and punctuation in the remainder.
            low, high = 1, len(sentence)
            while low < high:
                middle = (low + high + 1) // 2
                if len(tokenizer.encode(sentence[:middle])) <= max_tokens:
                    low = middle
                else:
                    high = middle - 1
            cut = low
            whitespace = sentence.rfind(" ", 0, cut + 1)
            if whitespace >= cut * 0.60:
                cut = whitespace
            part = sentence[:cut].strip()
            if not part or len(tokenizer.encode(part)) > max_tokens:
                raise ValueError("A single source character exceeds the tokenizer input limit")
            chunks.append(part)
            sentence = sentence[cut:].strip()
        pending = sentence
    if pending:
        chunks.append(pending)
    return chunks
