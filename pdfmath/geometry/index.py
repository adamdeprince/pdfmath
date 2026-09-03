"""Normalised spatial queries over extracted primitives.

Two design rules, both from the failure analysis of MaxTract in docs/prior-art.md:

* **No raw pixel thresholds.**  Every tolerance passed in here is expressed in points but
  is expected to have been *derived* from a TeX quantity by the caller -- a multiple of
  ``default_rule_thickness``, of the x-height, or of the current quad.  The index itself
  stays unit-agnostic; the recognisers own the units.
* **Baselines, not centres.**  ``same_baseline`` compares reference points.  Baker's
  evaluation showed this is the single decision that makes script detection exact.

Equations hold tens of primitives, so a sorted-by-x list with bisection beats a full
R-tree in both constant factor and clarity.  The interface is the one an R-tree would
offer, so swapping the implementation later changes nothing above it.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from typing import Callable, Generic, Iterable, Sequence, TypeVar

from .bbox import BBox

T = TypeVar("T")


@dataclass
class SpatialIndex(Generic[T]):
    """An x-sorted collection of items that expose a ``BBox``."""

    items: list[T]
    box_of: Callable[[T], BBox]

    def __post_init__(self) -> None:
        self.items = sorted(self.items, key=lambda it: (self.box_of(it).x0,
                                                        -self.box_of(it).y1))
        self._x0 = [self.box_of(it).x0 for it in self.items]

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self):
        return iter(self.items)

    # -- region queries ------------------------------------------------------------
    def _x_candidates(self, x0: float, x1: float, pad: float) -> Iterable[T]:
        """Items whose left edge is below ``x1``; cheap prefilter via bisection."""
        hi = bisect.bisect_right(self._x0, x1 + pad)
        return self.items[:hi]

    def inside(self, region: BBox, pad: float = 0.0) -> list[T]:
        """Items whose box lies wholly within ``region``."""
        return [it for it in self._x_candidates(region.x0, region.x1, pad)
                if region.contains(self.box_of(it), pad)]

    def centres_inside(self, region: BBox, pad: float = 0.0) -> list[T]:
        """Items whose *centre* lies within ``region`` -- the tolerant form."""
        out = []
        for it in self._x_candidates(region.x0, region.x1, pad):
            b = self.box_of(it)
            if region.contains_point(b.cx, b.cy, pad):
                out.append(it)
        return out

    def intersecting(self, region: BBox, pad: float = 0.0) -> list[T]:
        return [it for it in self._x_candidates(region.x0, region.x1, pad)
                if self.box_of(it).overlaps_x(region, pad)
                and self.box_of(it).overlaps_y(region, pad)]

    # -- directional queries --------------------------------------------------------
    def above(self, region: BBox, pad: float = 0.0) -> list[T]:
        """Items whose centre is above ``region`` and horizontally within its span."""
        out = []
        for it in self.items:
            b = self.box_of(it)
            if b.cy > region.y1 - pad and region.x0 - pad <= b.cx <= region.x1 + pad:
                out.append(it)
        return out

    def below(self, region: BBox, pad: float = 0.0) -> list[T]:
        out = []
        for it in self.items:
            b = self.box_of(it)
            if b.cy < region.y0 + pad and region.x0 - pad <= b.cx <= region.x1 + pad:
                out.append(it)
        return out

    def nearest_left(self, region: BBox, tol_y: float = 1e9) -> T | None:
        best, best_gap = None, float("inf")
        for it in self.items:
            b = self.box_of(it)
            if b.x1 <= region.x0 and abs(b.cy - region.cy) <= tol_y:
                gap = region.x0 - b.x1
                if gap < best_gap:
                    best, best_gap = it, gap
        return best

    def nearest_right(self, region: BBox, tol_y: float = 1e9) -> T | None:
        best, best_gap = None, float("inf")
        for it in self.items:
            b = self.box_of(it)
            if b.x0 >= region.x1 and abs(b.cy - region.cy) <= tol_y:
                gap = b.x0 - region.x1
                if gap < best_gap:
                    best, best_gap = it, gap
        return best


# -- baseline utilities ---------------------------------------------------------------

def same_baseline(a: float, b: float, tol: float) -> bool:
    """Do two reference points sit on one baseline, to within ``tol`` points?"""
    return abs(a - b) <= tol


def baseline_clusters(baselines: Sequence[float], tol: float) -> list[list[int]]:
    """Group indices whose baselines agree to within ``tol``.

    Single-link clustering on a sorted list: adjacent baselines closer than ``tol`` join.
    Returned groups are ordered by descending baseline (top of the page first).
    """
    order = sorted(range(len(baselines)), key=lambda i: -baselines[i])
    groups: list[list[int]] = []
    for i in order:
        if groups and abs(baselines[groups[-1][-1]] - baselines[i]) <= tol:
            groups[-1].append(i)
        else:
            groups.append([i])
    return groups


def vertical_bands(boxes: Sequence[BBox], gap: float) -> list[list[int]]:
    """Split indices into maximal groups separated by vertical whitespace > ``gap``.

    This is the "multiline" test: rows of a matrix, lines of an ``align``.  Unlike
    :func:`baseline_clusters` it looks at box extents, so a tall entry keeps its row
    together.
    """
    if not boxes:
        return []
    order = sorted(range(len(boxes)), key=lambda i: -boxes[i].y1)
    bands: list[list[int]] = [[order[0]]]
    floor = boxes[order[0]].y0
    for i in order[1:]:
        if boxes[i].y1 < floor - gap:
            bands.append([i])
            floor = boxes[i].y0
        else:
            bands[-1].append(i)
            floor = min(floor, boxes[i].y0)
    return bands


def horizontal_bands(boxes: Sequence[BBox], gap: float) -> list[list[int]]:
    """Split indices into maximal groups separated by horizontal whitespace > ``gap``."""
    if not boxes:
        return []
    order = sorted(range(len(boxes)), key=lambda i: boxes[i].x0)
    bands: list[list[int]] = [[order[0]]]
    edge = boxes[order[0]].x1
    for i in order[1:]:
        if boxes[i].x0 > edge + gap:
            bands.append([i])
            edge = boxes[i].x1
        else:
            bands[-1].append(i)
            edge = max(edge, boxes[i].x1)
    return bands
