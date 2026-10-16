"""Plan small, geometrically overlapping OCR crops without rewriting text.

The caller has already grouped and sorted one physical text row.  A strong
overlap starts a retry; at most one weaker immediate neighbour can join it.
This is deliberately not a general row or paragraph merger.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite

from ..contracts import TextLine


@dataclass(frozen=True)
class OverlapGroup:
    indices: tuple[int, ...]
    bounds: tuple[float, float, float, float]


@dataclass(frozen=True)
class _Geometry:
    bounds: tuple[float, float, float, float]
    slope: float

    @property
    def width(self) -> float:
        return self.bounds[2] - self.bounds[0]

    @property
    def height(self) -> float:
        return self.bounds[3] - self.bounds[1]


def _geometry(line: TextLine) -> _Geometry | None:
    # RapidOCR returns clockwise top-left, top-right, bottom-right,
    # bottom-left quadrilaterals. Reject malformed/rotated coordinates rather
    # than constructing an axis-aligned crop that could contain another row.
    try:
        if len(line.box) != 4:
            return None
        points = tuple((float(x), float(y)) for x, y in line.box)
    except (TypeError, ValueError, OverflowError):
        return None
    if not all(isfinite(value) and value >= 0 for point in points for value in point):
        return None
    top_left, top_right, bottom_right, bottom_left = points
    top_width = top_right[0] - top_left[0]
    bottom_width = bottom_right[0] - bottom_left[0]
    if (top_width <= 0 or bottom_width <= 0
            or bottom_left[1] <= top_left[1]
            or bottom_right[1] <= top_right[1]):
        return None
    top_slope = (top_right[1] - top_left[1]) / top_width
    bottom_slope = (bottom_right[1] - bottom_left[1]) / bottom_width
    if (not isfinite(top_slope) or not isfinite(bottom_slope)
            or abs(top_slope) > .15 or abs(bottom_slope) > .15
            or abs(top_slope - bottom_slope) > .10):
        return None
    # Require a convex quadrilateral with the expected point order.
    crosses = []
    for index in range(4):
        first, second, third = (points[(index + offset) % 4] for offset in range(3))
        crosses.append((second[0] - first[0]) * (third[1] - second[1])
                       - (second[1] - first[1]) * (third[0] - second[0]))
    if any(not isfinite(cross) or cross <= 0 for cross in crosses):
        return None
    xs, ys = zip(*points)
    bounds = min(xs), min(ys), max(xs), max(ys)
    if (bounds[2] <= bounds[0] or bounds[3] <= bounds[1]
            or not isfinite((bounds[2] - bounds[0]) * (bounds[3] - bounds[1]))):
        return None
    return _Geometry(bounds, (top_slope + bottom_slope) / 2)


def _same_baseline(first: _Geometry, second: _Geometry) -> bool:
    a, b = first.bounds, second.bounds
    smaller_height = min(first.height, second.height)
    larger_height = max(first.height, second.height)
    vertical_overlap = min(a[3], b[3]) - max(a[1], b[1])
    center_gap = abs((a[1] / 2 + a[3] / 2) - (b[1] / 2 + b[3] / 2))
    # Dimensionless comparisons keep the decisions unchanged under image
    # scaling, including values exactly on a threshold (modulo float noise).
    return (larger_height / smaller_height <= 1.6 + 1e-12
            and vertical_overlap / smaller_height >= .70 - 1e-12
            and center_gap / larger_height <= .30 + 1e-12
            and abs(first.slope - second.slope) <= .08 + 1e-12)


def _overlap_strength(first: _Geometry | None, second: _Geometry | None) -> float:
    if first is None or second is None or not _same_baseline(first, second):
        return 0.0
    a, b = first.bounds, second.bounds
    # Only adjacent boxes progressing left-to-right are eligible. Nested or
    # identically positioned detections need a different deduplication policy.
    if b[0] < a[0] or b[2] <= a[2]:
        return 0.0
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    if width <= 0 or height <= 0:
        return 0.0
    smaller_area = min(first.width * first.height, second.width * second.height)
    strength = width * height / smaller_area
    return strength if isfinite(strength) else 0.0


def _group_bounds(indices: tuple[int, ...], geometry: Sequence[_Geometry | None]
                  ) -> tuple[float, float, float, float] | None:
    items = [geometry[index] for index in indices]
    if any(item is None for item in items):
        return None
    valid = [item for item in items if item is not None]
    # Pairwise baseline checks stop a three-box chain from drifting into a
    # separate row even if each adjacent pair individually seems compatible.
    if any(not _same_baseline(first, second)
           for i, first in enumerate(valid) for second in valid[i + 1:]):
        return None
    bounds = (min(item.bounds[0] for item in valid),
              min(item.bounds[1] for item in valid),
              max(item.bounds[2] for item in valid),
              max(item.bounds[3] for item in valid))
    if (bounds[2] - bounds[0]) / (bounds[3] - bounds[1]) > 16 + 1e-12:
        return None
    return bounds


def plan_overlap_groups(row: Sequence[TextLine], max_groups: int = 12
                        ) -> tuple[OverlapGroup, ...]:
    """Return deterministic non-overlapping retry groups for one sorted row.

    All coordinates remain physical pixels. Text, confidence and input lines
    are untouched; accepting a recognition result is the caller's job.
    ``max_groups`` can reduce, but never raise, the hard per-call cap of 12.
    """
    if not isinstance(max_groups, int) or max_groups <= 0 or len(row) < 2:
        return ()
    limit = min(max_groups, 12)
    geometry = tuple(_geometry(line) for line in row)
    strengths = tuple(_overlap_strength(first, second)
                      for first, second in zip(geometry, geometry[1:]))
    used: set[int] = set()
    groups = []
    for index, strength in enumerate(strengths):
        if strength < .20 - 1e-12 or index in used or index + 1 in used:
            continue
        indices = (index, index + 1)
        bounds = _group_bounds(indices, geometry)
        if bounds is None:
            continue
        expansions: list[tuple[float, tuple[int, ...], tuple[float, float, float, float]]] = []
        if index > 0 and index - 1 not in used and strengths[index - 1] >= .08 - 1e-12:
            expanded = (index - 1, *indices)
            expanded_bounds = _group_bounds(expanded, geometry)
            if expanded_bounds is not None:
                expansions.append((strengths[index - 1], expanded, expanded_bounds))
        if (index + 2 < len(row) and index + 2 not in used
                and strengths[index + 1] >= .08 - 1e-12):
            expanded = (*indices, index + 2)
            expanded_bounds = _group_bounds(expanded, geometry)
            if expanded_bounds is not None:
                expansions.append((strengths[index + 1], expanded, expanded_bounds))
        if expansions:
            # Prefer the stronger adjoining seam; equal evidence favours the
            # left candidate, independent of confidence or recognized text.
            _, indices, bounds = min(expansions, key=lambda candidate: (-candidate[0], candidate[1]))
        used.update(indices)
        groups.append(OverlapGroup(indices, bounds))
        if len(groups) == limit:
            break
    return tuple(groups)
