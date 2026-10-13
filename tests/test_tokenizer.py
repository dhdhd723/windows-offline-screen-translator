from __future__ import annotations

import json
import re
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

from screen_translator.inference.translation.tokenizer import MarianSentencePieceTokenizer, split_text_for_model


class CharacterTokenizer:
    def encode(self, text: str) -> list[str]:
        return list(text) + ["</s>"]


@pytest.mark.parametrize("text", [
    "你好，今天是星期一。请打开设置！字幕将自动翻译。",
    "A very long subtitle with several words. Another sentence follows! Done?",
    "0123456789" * 20,
    "First sentence... Second sentence?! 中文和 English 混合。",
    "  leading  and trailing    spaces   ",
])
def test_long_text_split_preserves_every_non_whitespace_character(text):
    tokenizer = CharacterTokenizer()
    parts = split_text_for_model(text, tokenizer, max_tokens=18)
    assert parts
    assert all(len(tokenizer.encode(part)) <= 18 for part in parts)
    assert re.sub(r"\s", "", "".join(parts)) == re.sub(r"\s", "", text)


def test_empty_text_has_no_chunks():
    assert split_text_for_model(" \n\t", CharacterTokenizer()) == []


def test_short_input_is_one_chunk_with_original_spacing():
    assert split_text_for_model("Hello,  world!", CharacterTokenizer()) == ["Hello,  world!"]


def test_limit_must_include_eos():
    with pytest.raises(ValueError):
        split_text_for_model("text", CharacterTokenizer(), max_tokens=3)


def make_fake_translation_engine(tmp_path, native):
    from screen_translator.inference.translation.ctranslate2_engine import CTranslate2Engine

    class Tokenizer(CharacterTokenizer):
        eos = "</s>"

        def decode(self, tokens):
            return "".join(token for token in tokens if token != self.eos)

    engine = CTranslate2Engine(tmp_path)
    engine._tokenizers["en-zh"] = Tokenizer()
    engine._translators["en-zh"] = native
    return engine


def test_ct2_long_input_chunks_preserve_all_source_and_eos_budget(tmp_path):
    calls = []

    class Native:
        def translate_batch(self, sources, **kwargs):
            calls.extend(sources)
            assert kwargs["max_input_length"] == 192
            return [SimpleNamespace(hypotheses=[sources[0]])]

    engine = make_fake_translation_engine(tmp_path, Native())
    source = "abcdefghijklmnop" * 40
    assert engine.translate(source, "en-zh") == source
    assert len(calls) > 1
    assert all(len(tokens) <= 192 and tokens[-1] == "</s>" for tokens in calls)


def test_ct2_decoding_cap_splits_and_retries_without_partial_output(tmp_path):
    calls = []

    class Native:
        def translate_batch(self, sources, **kwargs):
            source = sources[0]
            calls.append(source)
            tokens = ["overflow"] * 384 if len(source) > 9 else source
            return [SimpleNamespace(hypotheses=[tokens])]

    engine = make_fake_translation_engine(tmp_path, Native())
    source = "abcdefghijklmnopqrstu"
    assert engine.translate(source, "en-zh") == source
    assert len(calls) > 1


def test_ct2_irreducible_decoding_cap_is_permanent_not_truncated(tmp_path):
    from screen_translator.inference import InputLimitError, PermanentInferenceError

    class Native:
        def translate_batch(self, sources, **kwargs):
            return [SimpleNamespace(hypotheses=[["overflow"] * 384])]

    engine = make_fake_translation_engine(tmp_path, Native())
    with pytest.raises(InputLimitError) as error:
        engine.translate("abc", "en-zh")
    assert isinstance(error.value, PermanentInferenceError)


def test_ct2_long_chunks_cancel_before_second_native_call(tmp_path):
    from screen_translator.inference import InferenceCancelled
    calls = []

    class Native:
        def translate_batch(self, sources, **kwargs):
            calls.extend(sources)
            return [SimpleNamespace(hypotheses=[sources[0]])]

    engine = make_fake_translation_engine(tmp_path, Native())
    with pytest.raises(InferenceCancelled):
        engine.translate_cancellable("x" * 500, "en-zh", lambda: bool(calls))
    assert len(calls) == 1


def test_ct2_source_limit_is_permanent_before_loading_models(tmp_path):
    from screen_translator.inference import InputLimitError
    from screen_translator.inference.translation.ctranslate2_engine import CTranslate2Engine
    engine = CTranslate2Engine(tmp_path)
    with pytest.raises(InputLimitError):
        engine.translate("x" * 16001, "en-zh")
    assert not engine._translators


@pytest.mark.parametrize("manifest", [[], {"schema_version": 1, "ocr": []},
                                     {"schema_version": 1, "translation": {"en-zh": []}}])
def test_invalid_model_manifest_is_permanent(tmp_path, manifest):
    from screen_translator.inference import ModelFilesError, PermanentInferenceError, read_manifest
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ModelFilesError) as error:
        read_manifest(tmp_path)
    assert isinstance(error.value, PermanentInferenceError)


def test_missing_translation_identity_is_permanent(tmp_path):
    from screen_translator.inference import ModelFilesError
    from screen_translator.inference.translation.ctranslate2_engine import CTranslate2Engine
    manifest = {"schema_version": 1, "translation": {"en-zh": {"path": "translation/model"}}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    engine = CTranslate2Engine(tmp_path)
    with pytest.raises(ModelFilesError):
        engine.model_id("en-zh")


def test_unreadable_model_file_is_permanent(tmp_path, monkeypatch):
    from screen_translator.inference import ModelFilesError, verify_files
    path = tmp_path / "model.bin"
    path.write_bytes(b"model")
    entry = {"files": {"model.bin": {"size": 5, "sha256": "not-read"}}}
    original_open = Path.open

    def deny_model_read(value, *args, **kwargs):
        if value.name == "model.bin":
            raise PermissionError("Model file is unavailable")
        return original_open(value, *args, **kwargs)

    monkeypatch.setattr(Path, "open", deny_model_read)
    with pytest.raises(ModelFilesError):
        verify_files(tmp_path, entry, ["model.bin"])


def test_external_marian_vocabulary_controls_unk_and_eos(tmp_path, monkeypatch):
    """SPM's internal indexes must never be used as Marian vocabulary IDs."""
    source_calls = []
    target_calls = []

    class FakeSentencePiece:
        def __init__(self, model_proto):
            self.is_source = model_proto == b"source"

        def encode(self, text, out_type):
            assert self.is_source
            assert out_type is str
            source_calls.append(text)
            return ["▁Hello", "piece-not-in-marian-vocab"]

        def decode(self, pieces):
            assert not self.is_source
            target_calls.append(pieces)
            return "你好"

    monkeypatch.setitem(sys.modules, "sentencepiece", SimpleNamespace(SentencePieceProcessor=FakeSentencePiece))
    (tmp_path / "vocab.json").write_text(json.dumps({"</s>": 0, "<unk>": 1, "▁Hello": 17, "<pad>": 20}), encoding="utf-8")
    (tmp_path / "tokenizer_config.json").write_text("{}", encoding="utf-8")
    (tmp_path / "source.spm").write_bytes(b"source")
    (tmp_path / "target.spm").write_bytes(b"target")
    tokenizer = MarianSentencePieceTokenizer(tmp_path)
    assert tokenizer.encode("Hello") == ["▁Hello", "<unk>", "</s>"]
    assert tokenizer.decode(["<pad>", "▁你好", "</s>"]) == "你好"
    assert source_calls == ["Hello"]
    assert target_calls == [["▁你好"]]


@pytest.mark.parametrize("source_folder,samples", [
    ("en-zh-408d9bc410a388e1d9aef112a2daba955b945255", (
        "Hello, world!", "A fox jumps over the lazy dog.",
        "I have 19 seconds left.", "中文 English 123?!",
    )),
    ("zh-en-cf109095479db38d6df799875e34039d4938aaa6", (
        "你好，世界！", "还剩 19 秒。", "中英混合 OpenAI 123。",
    )),
])
def test_real_tokenizer_matches_huggingface_when_source_present(source_folder, samples):
    source = Path(__file__).resolve().parents[1] / "build/model_sources" / source_folder
    if not (source / "source.spm").is_file():
        pytest.skip("Pinned development source model is not present")
    transformers = pytest.importorskip("transformers")
    ours = MarianSentencePieceTokenizer(source)
    reference = transformers.MarianTokenizer.from_pretrained(str(source), local_files_only=True)
    for sample in samples:
        reference_ids = reference(sample)["input_ids"]
        assert [ours.vocab[token] for token in ours.encode(sample)] == reference_ids
        target_tokens = reference.convert_ids_to_tokens(reference_ids)
        assert ours.decode(target_tokens) == reference.decode(
            reference_ids, skip_special_tokens=True, use_source_tokenizer=False
        )


def test_real_offline_ocr_and_en_zh_model_when_pack_present(monkeypatch):
    root = Path(__file__).resolve().parents[1] / "models"
    if not (root / "manifest.json").is_file() or not (root / "translation/en-zh-int8/model.bin").is_file():
        pytest.skip("Offline model pack is not present")
    import cv2
    import numpy as np
    import requests
    import urllib.request
    from PIL import Image, ImageDraw, ImageFont
    from screen_translator.inference.ocr import RapidOCREngine
    from screen_translator.inference.translation import CTranslate2Engine

    def no_network(*args, **kwargs):
        raise AssertionError("Offline inference attempted a network request")

    monkeypatch.setattr(requests, "get", no_network)
    monkeypatch.setattr(urllib.request, "urlopen", no_network)

    image = Image.new("RGB", (900, 160), "white")
    painter = ImageDraw.Draw(image)
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 38)
    painter.text((20, 25), "Hello world!", font=font, fill="black")
    bgr = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
    ocr = RapidOCREngine(root, cpu_threads=2)
    ocr.warmup()
    result = ocr.recognize(bgr)
    assert "hello" in result.text.lower()
    assert "world" in result.text.lower()
    assert result.lines and all(0 <= x <= 900 and 0 <= y <= 160 for line in result.lines for x, y in line.box)
    translator = CTranslate2Engine(root, cpu_threads=2)
    translation = translator.translate("Hello world!", "en-zh")
    assert translation and re.search(r"[\u4e00-\u9fff]", translation)


@pytest.mark.parametrize("source,expected,font_name,direction", [
    ("The translation works offline.", "offline", "arial.ttf", "en-zh"),
    ("屏幕翻译支持离线运行。", "离线", "msyh.ttc", "zh-en"),
])
def test_real_white_on_dark_subtitles_both_directions(source, expected, font_name, direction):
    root = Path(__file__).resolve().parents[1] / "models"
    if not (root / f"translation/{direction}-int8/model.bin").is_file():
        pytest.skip("Offline model pack is not present")
    import time
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    from screen_translator.inference.ocr import RapidOCREngine
    from screen_translator.inference.translation import CTranslate2Engine

    image = Image.new("RGB", (1080, 130), "#202020")
    painter = ImageDraw.Draw(image)
    painter.text((28, 32), source, font=ImageFont.truetype(f"C:/Windows/Fonts/{font_name}", 39), fill="#FFFFFF")
    bgr = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
    ocr = RapidOCREngine(root)
    start = time.perf_counter()
    result = ocr.recognize(bgr)
    ocr_ms = (time.perf_counter() - start) * 1000
    print(direction, "OCR:", repr(result.text), "confidence:", round(result.confidence, 3), "ms:", round(ocr_ms, 1))
    assert expected.lower() in result.text.lower()

    translator = CTranslate2Engine(root)
    start = time.perf_counter()
    translation = translator.translate(result.text, direction)
    translation_ms = (time.perf_counter() - start) * 1000
    print(direction, "translation:", repr(translation), "ms:", round(translation_ms, 1))
    assert translation
    if direction == "en-zh":
        assert re.search(r"[\u4e00-\u9fff]", translation)
    else:
        assert re.search(r"[A-Za-z]", translation)
