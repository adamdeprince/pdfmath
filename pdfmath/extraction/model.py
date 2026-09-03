"""The extraction IR: positioned glyphs and rules, with full provenance.

This is the boundary between "what the PDF says" and "what we infer".  Everything here
is measured, nothing is guessed.  Lengths are in **TeX points** (see pdfmath.units) and
y grows upwards from the bottom-left of the page, matching both PDF and TeX conventions.

The fields deliberately include information that a general-purpose extractor discards --
the raw character code, the text matrix, the PDF font resource name -- because for a TeX
document those are stronger evidence than the resolved Unicode.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from ..fonts.metrics import FontMetrics, ResolvedGlyph
from ..fonts.symbols import AtomClass, Role
from ..geometry.bbox import BBox


@dataclass
class Glyph:
    """One character drawn on the page."""

    id: int
    page: int
    char_code: int
    x: float                       # baseline reference point, pt
    y: float
    size: float                    # font size in pt (the PDF's bp value converted)
    font_name: str                 # raw /BaseFont, e.g. "FFANCX+CMMI10"
    font_resource: Optional[str] = None   # the page resource key, e.g. "F35"
    matrix: tuple[float, float, float, float, float, float] = (1, 0, 0, 1, 0, 0)
    unicode_from_pdf: Optional[str] = None
    pdf_width: Optional[float] = None     # from /Widths, in pt
    ink_bbox: Optional[BBox] = None       # if an outline-based extractor supplied one
    _resolved: Optional[ResolvedGlyph] = field(default=None, repr=False, compare=False)

    # -- resolution ---------------------------------------------------------------
    @property
    def resolved(self) -> ResolvedGlyph:
        if self._resolved is None:
            self._resolved = FontMetrics.lookup(
                self.font_name, self.char_code, self.size,
                self.pdf_width, self.unicode_from_pdf)
        return self._resolved

    @property
    def font(self):        return self.resolved.font
    @property
    def glyph_name(self):  return self.resolved.glyph
    @property
    def symbol(self):      return self.resolved.symbol
    @property
    def atom(self) -> AtomClass: return self.resolved.atom
    @property
    def role(self) -> Role:      return self.resolved.role
    @property
    def unicode(self) -> str:    return self.resolved.unicode

    @property
    def is_extensible_piece(self) -> bool:
        """Is this glyph one of the stacked pieces of a built-up delimiter or radical?"""
        if self.role is Role.DELIM_PIECE:
            return True
        if not self.font.is_extension_font:
            return False
        return self.char_code in FontMetrics.extensible_pieces(self.font_name)

    @property
    def unicode_source(self) -> str:
        if self.resolved.symbol.unicode:
            return "tex-encoding"
        if self.unicode_from_pdf:
            return "tounicode"
        return "none"

    # -- geometry -----------------------------------------------------------------
    @property
    def width(self) -> float:  return self.resolved.metrics.width
    @property
    def height(self) -> float: return self.resolved.metrics.height
    @property
    def depth(self) -> float:  return self.resolved.metrics.depth
    @property
    def italic(self) -> float: return self.resolved.metrics.italic

    @property
    def bbox(self) -> BBox:
        """The *TeX* box: width x (height + depth) hung off the reference point.

        Not the ink box.  TeX placed this glyph using these numbers, so this is the box
        whose position we can predict and check.
        """
        return BBox.from_baseline(self.x, self.y, self.width, self.height, self.depth)

    @property
    def advance(self) -> float:
        """Where the next glyph's reference point would be if nothing intervened."""
        return self.x + self.width

    def to_json(self) -> dict[str, Any]:
        r = self.resolved
        return {
            "id": self.id,
            "page": self.page,
            "char_code": self.char_code,
            "glyph": self.glyph_name,
            "unicode": self.unicode,
            "unicode_source": self.unicode_source,
            "font": self.font.base_name,
            "font_raw": self.font_name,
            "font_resource": self.font_resource,
            "family": self.font.family,
            "encoding": self.font.encoding,
            "mathvariant": self.font.mathvariant,
            "font_size": round(self.size, 5),
            "x": round(self.x, 4),
            "y": round(self.y, 4),
            "baseline": round(self.y, 4),
            "bbox": [round(v, 4) for v in self.bbox.as_list()],
            "ink_bbox": [round(v, 4) for v in self.ink_bbox.as_list()] if self.ink_bbox else None,
            "matrix": [round(v, 6) for v in self.matrix],
            "tex": {
                "width": round(self.width, 5),
                "height": round(self.height, 5),
                "depth": round(self.depth, 5),
                "italic": round(self.italic, 5),
                "source": r.metrics.source,
                "atom": r.atom.short,
                "role": r.role.name,
                "base": r.symbol.base,
                "size_rank": r.symbol.size_rank,
            },
        }


@dataclass
class Rule:
    """A horizontal or vertical line: a fraction bar, a radical overbar, a table rule.

    pdfTeX draws these as *stroked* paths (``0 0 m w 0 l S``) with the line width in the
    graphics state, not as filled rectangles, so both forms are normalised here into a
    box plus a thickness.
    """

    id: int
    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    thickness: float
    kind: str = "stroke"            # "stroke" | "fill"
    source: Optional[str] = None    # a note about where it came from

    @property
    def bbox(self) -> BBox:
        return BBox(min(self.x0, self.x1), min(self.y0, self.y1),
                    max(self.x0, self.x1), max(self.y0, self.y1))

    @property
    def width(self) -> float: return abs(self.x1 - self.x0)
    @property
    def height(self) -> float: return abs(self.y1 - self.y0)

    @property
    def is_horizontal(self) -> bool:
        return self.width >= max(self.height, self.thickness) * 2

    @property
    def is_vertical(self) -> bool:
        return self.height >= max(self.width, self.thickness) * 2

    @property
    def y_center(self) -> float:
        return 0.5 * (self.y0 + self.y1)

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "page": self.page,
            "bbox": [round(v, 4) for v in self.bbox.as_list()],
            "thickness": round(self.thickness, 5),
            "orientation": "horizontal" if self.is_horizontal
                           else ("vertical" if self.is_vertical else "other"),
            "kind": self.kind,
            "source": self.source,
        }


@dataclass
class PageExtract:
    """Everything drawn on one page that could carry mathematics."""

    page: int
    width: float                    # media box, pt
    height: float
    glyphs: list[Glyph] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def bbox(self) -> Optional[BBox]:
        return BBox.union([g.bbox for g in self.glyphs] + [r.bbox for r in self.rules])

    def in_region(self, region: BBox) -> "PageExtract":
        """A copy restricted to the glyphs and rules whose centres lie in ``region``."""
        return PageExtract(
            page=self.page, width=self.width, height=self.height,
            glyphs=[g for g in self.glyphs
                    if region.contains_point(g.bbox.cx, g.bbox.cy, pad=0.1)],
            rules=[r for r in self.rules
                   if region.contains_point(r.bbox.cx, r.bbox.cy, pad=0.1)],
            warnings=list(self.warnings),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "page": self.page,
            "page_size": [round(self.width, 3), round(self.height, 3)],
            "units": "TeX points (1/72.27 in); y increases upwards from the page bottom",
            "glyphs": [g.to_json() for g in self.glyphs],
            "rules": [r.to_json() for r in self.rules],
            "warnings": self.warnings,
        }
