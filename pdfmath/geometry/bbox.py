"""Axis-aligned boxes, in TeX points, in PDF orientation (y grows upwards)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass(frozen=True)
class BBox:
    x0: float
    y0: float          # bottom
    x1: float
    y1: float          # top

    # -- construction ------------------------------------------------------------
    @staticmethod
    def from_baseline(x: float, y: float, width: float, height: float,
                      depth: float) -> "BBox":
        """The TeX box of a glyph whose reference point is at ``(x, y)``."""
        return BBox(x, y - depth, x + width, y + height)

    @staticmethod
    def union(boxes: Iterable["BBox"]) -> Optional["BBox"]:
        boxes = [b for b in boxes if b is not None]
        if not boxes:
            return None
        return BBox(min(b.x0 for b in boxes), min(b.y0 for b in boxes),
                    max(b.x1 for b in boxes), max(b.y1 for b in boxes))

    # -- measures ----------------------------------------------------------------
    @property
    def width(self) -> float: return self.x1 - self.x0
    @property
    def height(self) -> float: return self.y1 - self.y0
    @property
    def cx(self) -> float: return 0.5 * (self.x0 + self.x1)
    @property
    def cy(self) -> float: return 0.5 * (self.y0 + self.y1)
    @property
    def area(self) -> float: return max(0.0, self.width) * max(0.0, self.height)

    def as_list(self) -> list[float]:
        return [self.x0, self.y0, self.x1, self.y1]

    # -- relations ---------------------------------------------------------------
    def overlaps_x(self, other: "BBox", pad: float = 0.0) -> bool:
        return self.x0 - pad < other.x1 and other.x0 - pad < self.x1

    def overlaps_y(self, other: "BBox", pad: float = 0.0) -> bool:
        return self.y0 - pad < other.y1 and other.y0 - pad < self.y1

    def overlap_x(self, other: "BBox") -> float:
        """Length of the shared x-interval (negative if disjoint = the gap)."""
        return min(self.x1, other.x1) - max(self.x0, other.x0)

    def overlap_y(self, other: "BBox") -> float:
        return min(self.y1, other.y1) - max(self.y0, other.y0)

    def contains_x(self, other: "BBox", pad: float = 0.0) -> bool:
        return self.x0 - pad <= other.x0 and other.x1 <= self.x1 + pad

    def contains(self, other: "BBox", pad: float = 0.0) -> bool:
        return (self.x0 - pad <= other.x0 and other.x1 <= self.x1 + pad
                and self.y0 - pad <= other.y0 and other.y1 <= self.y1 + pad)

    def contains_point(self, x: float, y: float, pad: float = 0.0) -> bool:
        return (self.x0 - pad <= x <= self.x1 + pad
                and self.y0 - pad <= y <= self.y1 + pad)

    def expand(self, dx: float, dy: Optional[float] = None) -> "BBox":
        dy = dx if dy is None else dy
        return BBox(self.x0 - dx, self.y0 - dy, self.x1 + dx, self.y1 + dy)

    def __or__(self, other: "BBox") -> "BBox":
        return BBox(min(self.x0, other.x0), min(self.y0, other.y0),
                    max(self.x1, other.x1), max(self.y1, other.y1))
