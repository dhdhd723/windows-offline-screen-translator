"""SentencePiece adapter for the pinned M2M100 ja->zh pack, no Transformers.

Language markers belong to the converted vocabulary, not SentencePiece IDs.
Encoding is independently compared with the original tokenizer during build QA.
"""
from __future__ import annotations

import json
from pathlib import Path
import re


class M2M100JapaneseTokenizer:
    eos = "</s>"
    target_prefix = ("__zh__",)

    def __init__(self, folder: str | Path):
        import sentencepiece as spm
        root = Path(folder)
        vocab = json.loads((root / "vocab.json").read_text(encoding="utf-8"))
        if not isinstance(vocab, dict) or not {"<unk>", "</s>"}.issubset(vocab):
            raise ValueError("M2M100 vocabulary is invalid")
        self.vocab = vocab
        self.model = spm.SentencePieceProcessor(
            model_proto=(root / "sentencepiece.bpe.model").read_bytes())
        converted = json.loads((root / "shared_vocabulary.json").read_text(encoding="utf-8"))
        if (not isinstance(converted, list) or not {"__ja__", "__zh__", "</s>", "<unk>"}.issubset(converted)):
            raise ValueError("Converted M2M100 language vocabulary is invalid")
        self.special_tokens = {"<s>", "</s>", "<pad>", "<unk>"} | {
            token for token in converted if isinstance(token, str)
            and re.fullmatch(r"__(?:[a-z]{2,3}|madeupword\d+)__", token)}

    def encode(self, text: str) -> list[str]:
        pieces = self.model.encode(text, out_type=str)
        return ["__ja__", *[piece if piece in self.vocab else "<unk>" for piece in pieces], self.eos]

    def decode(self, tokens: list[str]) -> str:
        return self.model.decode([token for token in tokens if token not in self.special_tokens]).strip()
