"""Finding displayed equations on a page.

Detection deliberately does not block the decompiler: ``--page`` plus ``--bbox`` lets the
recogniser be measured on its own, and that is the path the synthetic corpus uses.  This
module is the convenience layer for real documents.

It is geometric, not neural, and it leans on the same TeX-specific evidence as the rest of
the system.  A displayed equation in a TeX document is a block that

* draws most of its characters from *math* fonts -- cmmi, cmsy, cmex, msam, msbm -- or
  contains rules of ``default_rule_thickness``;
* is horizontally inset from the text column on both sides, because ``\\[ ... \\]``
  centres it;
* is separated from the paragraphs above and below by more than the body leading.

The last two are what distinguish a display from inline mathematics in a paragraph, which
this module deliberately does not report.  ScanSSD, the detector in the MathSeer pipeline,
would find both, at the cost of a trained model and a rasterisation step; see
docs/prior-art.md for why that is kept off the critical path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from ..extraction.model import Glyph, PageExtract, Rule
from ..geometry.bbox import BBox
from ..geometry.index import vertical_bands

MATH_ENCODINGS = {"OML", "OMS", "OMX", "AMSA", "AMSB"}


@dataclass
class EquationRegion:
    """A candidate displayed equation."""

    bbox: BBox
    glyph_ids: list[int]
    rule_ids: list[int]
    confidence: float
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "bbox": [round(v, 4) for v in self.bbox.as_list()],
            "glyph_ids": self.glyph_ids,
            "rule_ids": self.rule_ids,
            "confidence": round(self.confidence, 4),
            "evidence": self.evidence,
        }


def _body_text_size(glyphs: list[Glyph]) -> float:
    sizes: dict[float, int] = {}
    for g in glyphs:
        sizes[round(g.size, 2)] = sizes.get(round(g.size, 2), 0) + 1
    return max(sizes, key=lambda s: sizes[s]) if sizes else 10.0


def find_displayed_equations(extract: PageExtract,
                             min_math_ratio: float = 0.45,
                             min_inset_ratio: float = 0.02) -> list[EquationRegion]:
    """Displayed equations on the page, in reading order."""
    if not extract.glyphs and not extract.rules:
        return []
    body = _body_text_size(extract.glyphs)
    items: list[Any] = list(extract.glyphs) + list(extract.rules)
    boxes = [it.bbox for it in items]
    # A body-text line is about 1.2 sizes tall; a bigger gap means a new block.
    bands = vertical_bands(boxes, gap=0.45 * body)

    # The text column is the widest block on the page: body paragraphs run margin to
    # margin, and a display is inset from them.  Taking the global extent instead would
    # let the equation define its own column and always look flush.
    band_boxes = [BBox.union([boxes[i] for i in band]) for band in bands]
    band_boxes = [b for b in band_boxes if b is not None]
    widest = max(band_boxes, key=lambda b: b.width) if band_boxes else None
    column_x0 = widest.x0 if widest else 0.0
    column_x1 = widest.x1 if widest else 1.0
    column_w = max(column_x1 - column_x0, 1e-6)
    single_block = len(band_boxes) < 2

    out: list[EquationRegion] = []
    for band in bands:
        members = [items[i] for i in band]
        glyphs = [m for m in members if isinstance(m, Glyph)]
        rules = [m for m in members if isinstance(m, Rule)]
        box = BBox.union([m.bbox for m in members])
        if box is None:
            continue

        math_glyphs = [g for g in glyphs
                       if g.font.encoding in MATH_ENCODINGS]
        ratio = len(math_glyphs) / len(glyphs) if glyphs else (1.0 if rules else 0.0)
        left_inset = (box.x0 - column_x0) / column_w
        right_inset = (column_x1 - box.x1) / column_w
        centred = left_inset > min_inset_ratio and right_inset > min_inset_ratio
        multi_size = len({round(g.size, 2) for g in glyphs}) > 1

        ev = {
            "math_font_ratio": round(ratio, 4),
            "n_glyphs": len(glyphs),
            "n_rules": len(rules),
            "left_inset_ratio": round(left_inset, 4),
            "right_inset_ratio": round(right_inset, 4),
            "centred": centred,
            "multiple_font_sizes": multi_size,
            "body_text_size_pt": round(body, 3),
        }
        if ratio < min_math_ratio and not rules:
            continue
        if single_block:
            # Nothing to be inset *from*; the centring test cannot be applied and the
            # font evidence has to stand on its own.
            ev["centred"] = None
        elif not centred and len(glyphs) > 3:
            ev["rejected"] = "spans the full text column: inline, not displayed"
            continue
        conf = min(0.99, 0.5 + 0.4 * ratio + (0.05 if multi_size else 0.0)
                   + (0.05 if rules else 0.0))
        out.append(EquationRegion(box, [g.id for g in glyphs],
                                  [r.id for r in rules], conf, ev))
    out.sort(key=lambda r: -r.bbox.y1)
    return out
