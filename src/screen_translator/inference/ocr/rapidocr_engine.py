from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any

import numpy as np

from ...contracts import OCRResult, TextLine
from ...core.ocr_overlap import plan_overlap_groups
from ...core.ocr_overlap_text import accept_overlap_text, overlap_text_eligible
from ...paths import model_root
from .. import ModelFilesError, checked_path, read_manifest, verify_files


log = logging.getLogger(__name__)
OCR_OVERLAP_POLICY_ID = "adjacent-crop-reread-v1"
MAX_OVERLAP_RETRIES = 12


def _same_text_row(first: TextLine, second: TextLine) -> bool:
    """Attach small baseline fragments without guessing or rewriting glyphs."""
    if not first.box or not second.box:
        return False

    def bounds(line):
        xs, ys = zip(*line.box)
        return min(xs), min(ys), max(xs), max(ys)

    left = bounds(first)
    right = bounds(second)
    first_height, second_height = left[3] - left[1], right[3] - right[1]
    if min(first_height, second_height) <= 0:
        return False
    first_center, second_center = (left[1] + left[3]) / 2, (right[1] + right[3]) / 2
    if abs(first_center - second_center) <= max(4, min(first_height, second_height) * .45):
        return True
    # A dot or short fragment can sit near the bottom of the text row instead
    # of sharing its center. Require containment and horizontal adjacency so
    # a small independent message below/away from the row remains separate.
    big, small = (left, right) if first_height >= second_height else (right, left)
    big_height, small_height = big[3] - big[1], small[3] - small[1]
    gap = max(0, big[0] - small[2], small[0] - big[2])
    return (small_height <= big_height * .45
            and small[1] >= big[1] - 2 and small[3] <= big[3] + 2
            and gap <= max(4, big_height * .5))


class RapidOCREngine:
    """PP-OCRv5 mobile via CPU ONNX Runtime, entirely from local files.

    Create and call on the single inference worker. Returned boxes always use
    the original input image's physical pixel coordinates.
    """

    def __init__(self, model_dir: str | Path | None = None, cpu_threads: int = 2):
        self.root = Path(model_dir).resolve() if model_dir else model_root()
        if self.root.name == "ocr":
            self.root = self.root.parent
        self.cpu_threads = max(1, min(4, int(cpu_threads)))
        self._engine: Any = None

    def configure_threads(self, cpu_threads: int) -> None:
        """Called only by the inference worker, between jobs."""
        count = max(1, min(4, int(cpu_threads)))
        if count != self.cpu_threads:
            self.cpu_threads = count
            self._engine = None

    def _initialize(self) -> None:
        if self._engine is not None:
            return
        manifest = read_manifest(self.root)
        entry = manifest.get("ocr")
        if not entry:
            raise ModelFilesError("本地 OCR 模型尚未安装，请使用包含模型的完整程序包。")
        config = entry.get("config", {})
        required = [config.get(key, "") for key in ("det", "rec", "keys")]
        if not all(required):
            raise ModelFilesError("本地 OCR 模型清单不完整。")
        verify_files(self.root, entry, required)
        try:
            from rapidocr import RapidOCR
            from rapidocr.utils.typings import EngineType, LangDet, LangRec, ModelType, OCRVersion
        except ImportError as exc:
            raise RuntimeError("OCR 运行组件缺失，请重新解压完整程序包。") from exc
        self._engine = RapidOCR(params={
            "Global.use_cls": False,
            "Global.use_det": True,
            "Global.use_rec": True,
            "Global.text_score": 0.40,
            "Global.return_word_box": False,
            "Global.return_single_char_box": False,
            "Global.log_level": "error",
            "Global.max_side_len": 2560,
            "Global.model_root_dir": str(self.root / "ocr"),
            "Det.engine_type": EngineType.ONNXRUNTIME,
            "Det.ocr_version": OCRVersion.PPOCRV5,
            "Det.model_type": ModelType.MOBILE,
            "Det.lang_type": LangDet.CH,
            "Det.model_path": str(checked_path(self.root, config["det"])),
            "Det.limit_type": "max",
            "Det.limit_side_len": 1280,
            "Det.box_thresh": 0.45,
            # RapidOCR 3.9.2 constructs a classifier session even when
            # use_cls=False. It is never executed, but requires a local ONNX
            # path to avoid an implicit ModelScope download at startup.
            "Cls.engine_type": EngineType.ONNXRUNTIME,
            "Cls.model_path": str(checked_path(self.root, config["det"])),
            "Rec.engine_type": EngineType.ONNXRUNTIME,
            "Rec.ocr_version": OCRVersion.PPOCRV5,
            "Rec.model_type": ModelType.MOBILE,
            "Rec.lang_type": LangRec.CH,
            "Rec.model_path": str(checked_path(self.root, config["rec"])),
            "Rec.rec_keys_path": str(checked_path(self.root, config["keys"])),
            "Rec.rec_batch_num": 4,
            "EngineConfig.onnxruntime.intra_op_num_threads": self.cpu_threads,
            "EngineConfig.onnxruntime.inter_op_num_threads": 1,
            "EngineConfig.onnxruntime.use_cuda": False,
            "EngineConfig.onnxruntime.use_dml": False,
            "EngineConfig.onnxruntime.use_cann": False,
            "EngineConfig.onnxruntime.use_coreml": False,
            "EngineConfig.onnxruntime.enable_cpu_mem_arena": False,
        })
        log.info("Initialized offline OCR model: %s", entry.get("id"))

    def warmup(self) -> None:
        blank = np.full((64, 256, 3), 255, dtype=np.uint8)
        self.recognize(blank)
        # RapidOCR loads recognition lazily after a successful detection. Blank
        # warmup has no boxes, so use the public recognition-only path once.
        self._engine(blank, use_det=False, use_cls=False, use_rec=True, return_word_box=False)

    def _assemble_rows(self, rows: list[list[TextLine]], image: np.ndarray) -> list[str]:
        """Reread only suspicious adjacent crops; never rewrite raw OCR evidence.

        Geometry can indicate overlapping glyphs, not prove duplication. The
        recognizer must independently confirm the joint pixel crop and a
        conservative text guard must accept it. Failed/uncertain rereads leave
        the original text intact. No extra detection pass or whole-row fallback.
        """
        texts = [" ".join(line.text for line in row) for row in rows]
        recognize = getattr(self._engine, "recognize_txt", None)
        if not callable(recognize):
            return texts
        pending, crops = [], []
        height, width = image.shape[:2]
        for row_index, row in enumerate(rows):
            if len(pending) >= MAX_OVERLAP_RETRIES:
                break
            groups = plan_overlap_groups(row, max_groups=MAX_OVERLAP_RETRIES - len(pending))
            for group in groups:
                fragments = tuple(row[index].text for index in group.indices)
                if not overlap_text_eligible(fragments):
                    continue
                left, top, right, bottom = group.bounds
                x0, y0 = max(0, math.floor(left) - 2), max(0, math.floor(top) - 2)
                x1, y1 = min(width, math.ceil(right) + 2), min(height, math.ceil(bottom) + 2)
                if x1 - x0 < 6 or y1 - y0 < 6:
                    continue
                crop = np.ascontiguousarray(image[y0:y1, x0:x1])
                if not crop.size:
                    continue
                baseline = sum(row[index].confidence * len(row[index].text) for index in group.indices)
                baseline /= max(1, sum(len(row[index].text) for index in group.indices))
                crops.append(crop)
                pending.append((row_index, group.indices, fragments, baseline))
        if not crops:
            return texts
        try:
            result = recognize(crops)
            candidates, scores = getattr(result, "txts", None), getattr(result, "scores", None)
            if candidates is None or scores is None or len(candidates) != len(pending) or len(scores) != len(pending):
                return texts
        except Exception:
            # Optional repair must not turn successful OCR into a frame error.
            # Neither crop pixels nor recognized text are logged.
            log.debug("Optional adjacent-crop OCR reread unavailable")
            return texts
        replacements: dict[int, dict[int, tuple[tuple[int, ...], str]]] = {}
        for (row_index, indices, fragments, baseline), candidate, score in zip(pending, candidates, scores):
            try:
                if not isinstance(candidate, str) or not accept_overlap_text(fragments, candidate, float(score), baseline):
                    continue
            except (TypeError, ValueError, OverflowError):
                continue
            replacements.setdefault(row_index, {})[indices[0]] = (indices, candidate.strip())
        for row_index, groups in replacements.items():
            consumed: set[int] = set()
            pieces = []
            for index, line in enumerate(rows[row_index]):
                if index in consumed:
                    continue
                replacement = groups.get(index)
                if replacement:
                    indices, candidate = replacement
                    consumed.update(indices)
                    pieces.append(candidate)
                else:
                    pieces.append(line.text)
            texts[row_index] = " ".join(pieces)
        return texts

    def recognize(self, image_bgr: np.ndarray) -> OCRResult:
        if image_bgr is None or image_bgr.size == 0:
            return OCRResult("")
        self._initialize()
        import cv2
        image = np.asarray(image_bgr)
        if image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        elif image.ndim != 3 or image.shape[2] not in (3, 4):
            raise ValueError("OCR expects a BGR image with three channels")
        elif image.shape[2] == 4:
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        image = np.ascontiguousarray(image, dtype=np.uint8)
        physical_image = image
        original_h, original_w = image.shape[:2]
        scale = 1.0
        if original_h < 120 and original_w <= 1280:
            scale = 2.0
            image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        output = self._engine(image, use_det=True, use_cls=False, use_rec=True, return_word_box=False)
        texts = getattr(output, "txts", None)
        scores = getattr(output, "scores", None)
        boxes = getattr(output, "boxes", None)
        if texts is None or scores is None:
            return OCRResult("")
        lines = []
        for index, (text, confidence) in enumerate(zip(texts, scores)):
            text = str(text).strip()
            confidence = float(confidence)
            if not text or confidence < 0.40:
                continue
            box = ()
            if boxes is not None and index < len(boxes):
                box = tuple(
                    (min(float(original_w), max(0.0, float(x) / scale)),
                     min(float(original_h), max(0.0, float(y) / scale)))
                    for x, y in boxes[index]
                )
            lines.append(TextLine(text, confidence, box))
        # Group near-aligned boxes before sorting horizontally. A plain (y, x)
        # sort can swap fragments on the same baseline due to one-pixel jitter.
        lines.sort(key=lambda line: min((point[1] for point in line.box), default=0))
        ordered: list[TextLine] = []
        rows: list[list[TextLine]] = []
        for line in lines:
            if not line.box:
                rows.append([line])
                continue
            if rows and rows[-1][0].box:
                # A small fragment may be adjacent to the rightmost word, not
                # the tallest box in a row containing several OCR fragments.
                if any(_same_text_row(previous, line) for previous in rows[-1]):
                    rows[-1].append(line)
                    continue
            rows.append([line])
        for row in rows:
            row.sort(key=lambda line: min((point[0] for point in line.box), default=0))
            ordered.extend(row)
        text_rows = self._assemble_rows(rows, physical_image)
        confidence = sum(line.confidence * len(line.text) for line in ordered) / max(1, sum(len(line.text) for line in ordered))
        return OCRResult("\n".join(text_rows), tuple(ordered), confidence)
