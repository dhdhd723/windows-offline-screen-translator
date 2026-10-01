from __future__ import annotations

from dataclasses import dataclass
import hashlib

import numpy as np


@dataclass(frozen=True)
class Fingerprint:
    gray: np.ndarray
    edges: np.ndarray
    digest: bytes
    analyzed_pixels: int


def fingerprint(image_bgr: np.ndarray, boxes: tuple[tuple[int, int, int, int], ...] = ()) -> Fingerprint:
    image = np.asarray(image_bgr)
    if image.ndim < 2 or not image.size:
        raise ValueError("Screen capture returned an empty image")
    height, width = image.shape[:2]
    # Sampling avoids a dependency on OpenCV and keeps per-frame work bounded.
    ys = np.linspace(0, height - 1, min(height, 72), dtype=np.intp)
    xs = np.linspace(0, width - 1, min(width, 224), dtype=np.intp)
    small = image[np.ix_(ys, xs)]
    if small.ndim == 3:
        gray = (small[..., 0].astype(np.float32) * 0.114
                + small[..., 1].astype(np.float32) * 0.587
                + small[..., 2].astype(np.float32) * 0.299)
    else:
        gray = small.astype(np.float32)
    analyzed_pixels = gray.size
    checksum = hashlib.blake2b(digest_size=8)
    if boxes:
        mask = np.zeros(gray.shape, dtype=bool)
        for x1, y1, x2, y2 in boxes:
            mask |= ((ys[:, None] >= y1) & (ys[:, None] <= y2)
                     & (xs[None, :] >= x1) & (xs[None, :] <= x2))
            crop = np.ascontiguousarray(image[max(0, y1):min(height, y2 + 1),
                                             max(0, x1):min(width, x2 + 1)])
            checksum.update(crop)
        if mask.any():
            gray = np.where(mask, gray, 0)
            analyzed_pixels = int(mask.sum())
    else:
        checksum.update(np.ascontiguousarray(image))
    edges = np.zeros_like(gray, dtype=np.bool_)
    edges[:, 1:] |= np.abs(np.diff(gray, axis=1)) > 22
    edges[1:, :] |= np.abs(np.diff(gray, axis=0)) > 22
    return Fingerprint(gray.astype(np.uint8), edges, checksum.digest(), analyzed_pixels)


def changed(first: Fingerprint | None, second: Fingerprint) -> bool:
    if first is None or first.gray.shape != second.gray.shape:
        return True
    diff = np.abs(first.gray.astype(np.int16) - second.gray.astype(np.int16))
    count = max(1, max(first.analyzed_pixels, second.analyzed_pixels))
    return bool((np.count_nonzero(diff > 14) / count >= 0.003 and diff.sum() / count >= 0.18)
                or np.count_nonzero(first.edges != second.edges) / count >= 0.003)
