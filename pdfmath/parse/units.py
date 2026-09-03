"""The parser's working unit: a positioned thing with a TeX box and a baseline.

A unit is either an atomic glyph, a group of glyphs that TeX assembled into one symbol
(an extensible delimiter, a built-up radical), or an already-recognised composite.  All
of them answer the same questions -- where is your baseline, how tall are you, what is
your horizontal extent -- so the recognisers above never need to know which they have.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from ..extraction.model import Glyph, Rule
from ..fonts.symbols import AtomClass, Role, SymbolInfo
from ..geometry.bbox import BBox
from ..tree.nodes import MathNode, Provenance


@dataclass
class GlyphRun:
    """One or more glyphs that TeX drew as a single logical symbol.

    cmex builds a tall delimiter from a top hook, repeated extension modules and a bottom
    hook, each of which is a separate ``TJ``.  Reporting them as four symbols would be
    faithful to the PDF and useless as mathematics, so they are merged here, with the
    merge recorded in the provenance.
    """

    glyphs: list[Glyph]

    @property
    def head(self) -> Glyph:
        return self.glyphs[0]

    @property
    def symbol(self) -> SymbolInfo:
        return self.head.symbol

    @property
    def bbox(self) -> BBox:
        return BBox.union([g.bbox for g in self.glyphs])

    @property
    def ids(self) -> list[int]:
        return [g.id for g in self.glyphs]

    @property
    def is_merged(self) -> bool:
        return len(self.glyphs) > 1


@dataclass
class Unit:
    """A positioned participant in the horizontal list being parsed."""

    node: MathNode
    x0: float
    x1: float
    baseline: float
    height: float                  # above the baseline
    depth: float                   # below the baseline
    size: float                    # font size in pt this unit was set at
    italic: float = 0.0
    run: Optional[GlyphRun] = None       # set when the unit is a plain symbol
    is_char: bool = False                # Appendix G rule 18a: a bare character nucleus
    axis_normalised: bool = False        # axis centring already undone (see parse.axis)
    lead: float = 0.0                    # invisible advance TeX put *before* the ink
    trail: float = 0.0                   # ... and after it (italic kern, \scriptspace)
    glyph_ids: list[int] = field(default_factory=list)
    rule_ids: list[int] = field(default_factory=list)

    # -- geometry ------------------------------------------------------------------
    @property
    def bbox(self) -> BBox:
        return BBox(self.x0, self.baseline - self.depth, self.x1, self.baseline + self.height)

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def box_x0(self) -> float:
        """Left edge of the *box* TeX packed, which can sit outside the ink.

        A fraction's box extends ``\\nulldelimiterspace`` beyond its rule on each side.
        """
        return self.x0 - self.lead

    @property
    def box_x1(self) -> float:
        """Right edge of the box, including the italic kern or ``\\scriptspace``.

        TeX appends the nucleus's italic correction as a kern when there is no
        subscript, and adds ``\\scriptspace`` to the width of every script box.  Both
        are invisible, and both shift the following atom -- so a gap measured from the
        ink alone will not match the inter-atom glue table.
        """
        return self.x1 + self.trail

    @property
    def symbol(self) -> Optional[SymbolInfo]:
        return self.run.symbol if self.run else None

    @property
    def atom(self) -> AtomClass:
        s = self.symbol
        return s.atom if s else AtomClass.ORD

    @property
    def role(self) -> Role:
        s = self.symbol
        return s.role if s else Role.SYMBOL

    def provenance(self, rule_name: str, confidence: float = 1.0,
                   evidence: Optional[dict[str, Any]] = None) -> Provenance:
        return Provenance(sorted(set(self.glyph_ids)), sorted(set(self.rule_ids)),
                          self.bbox, confidence, evidence or {}, rule_name)

    @staticmethod
    def from_run(run: GlyphRun, node: MathNode) -> "Unit":
        b = run.bbox
        head = run.head
        return Unit(node=node, x0=b.x0, x1=b.x1, baseline=head.y,
                    height=b.y1 - head.y, depth=head.y - b.y0,
                    size=head.size, italic=head.italic, run=run,
                    is_char=True, glyph_ids=run.ids, trail=head.italic)

    @staticmethod
    def composite(node: MathNode, baseline: float, box: BBox, size: float,
                  glyph_ids: Sequence[int] = (), rule_ids: Sequence[int] = (),
                  italic: float = 0.0, x0: Optional[float] = None,
                  x1: Optional[float] = None, lead: float = 0.0,
                  trail: float = 0.0) -> "Unit":
        """``x0``/``x1`` override the ink extent when TeX's *box* is narrower.

        An accent is the case that matters: ``make_math_accent`` sets the vbox's width
        to the nucleus's width, so a wide ``\\vec`` overhangs its own box on both sides
        and anything measured from the ink would place the next atom too far right.
        """
        return Unit(node=node, x0=box.x0 if x0 is None else x0,
                    x1=box.x1 if x1 is None else x1, baseline=baseline,
                    height=box.y1 - baseline, depth=baseline - box.y0,
                    size=size, italic=italic, is_char=False, lead=lead, trail=trail,
                    glyph_ids=list(glyph_ids), rule_ids=list(rule_ids))


# --------------------------------------------------------------------------- merging

def merge_runs(glyphs: Sequence[Glyph], tol: float) -> list[GlyphRun]:
    """Group vertically stacked pieces of extensible delimiters and radicals.

    Which glyphs *are* pieces is not a list we maintain: it comes from the extensible
    recipes in the font's own TFM (see ``FontMetrics.extensible_pieces``).  That is how
    a tall ``|`` -- four stacked copies of cmex's ``vextendsingle``, each its own
    ``TJ`` -- is recognised as one delimiter rather than four vertical strokes.

    Pieces join when they share an identity and a column and are vertically adjacent.
    """
    pieces = [g for g in glyphs if g.is_extensible_piece
              or (g.role == Role.RADICAL and g.symbol.piece)]
    piece_ids = {id(g) for g in pieces}
    runs: list[GlyphRun] = [GlyphRun([g]) for g in glyphs if id(g) not in piece_ids]

    by_identity: dict[tuple, list[Glyph]] = {}
    for g in pieces:
        by_identity.setdefault((g.font.base_name, g.symbol.base, g.symbol.side), []).append(g)

    for group in by_identity.values():
        for column in _columns_by_x(group, tol * 4):
            column.sort(key=lambda g: -g.bbox.y1)
            cur = [column[0]]
            for g in column[1:]:
                if g.bbox.y1 <= cur[-1].bbox.y0 + tol * 4:
                    cur.append(g)
                else:
                    runs.append(GlyphRun(cur))
                    cur = [g]
            runs.append(GlyphRun(cur))

    runs.sort(key=lambda r: (r.bbox.x0, -r.bbox.y1))
    return runs


def _columns_by_x(glyphs: list[Glyph], tol: float) -> list[list[Glyph]]:
    """Single-link clustering of glyphs by their left edge."""
    out: list[list[Glyph]] = []
    for g in sorted(glyphs, key=lambda g: g.x):
        if out and abs(g.x - out[-1][-1].x) <= tol:
            out[-1].append(g)
        else:
            out.append([g])
    return out


def connected_block(edge: float, items: Sequence[Any], upward: bool,
                    tol_normal: float, tol_large_op: float,
                    is_large_op=lambda it: False) -> list[Any]:
    """The vertically contiguous run of ``items`` starting at ``edge``.

    A fraction's numerator is one hbox: its contents are stacked around a single
    baseline, so the union of their boxes is vertically connected.  Material on a
    *different line* -- the cell above in a matrix, say -- is separated by real
    whitespace.  Growing outward from the bar and stopping at the first real gap is
    therefore what distinguishes them, and it replaces the global constant ``V`` whose
    failure on tightly-set matrices Baker documented.

    The tolerance is a TeX quantity, not a tuned one.  Inside an hbox the largest gap
    TeX's own rules can leave between vertically adjacent material is the clearance of
    whichever construction produced it: ``4 * theta`` for a nested fraction or overline,
    ``big_op_spacing2`` for a limit under an operator, and up to ``big_op_spacing4``
    when that limit is unusually short -- which is why a block already containing a
    large operator is allowed the wider bound.
    """
    ordered = sorted(items, key=(lambda it: it.bbox.y0) if upward
                     else (lambda it: -it.bbox.y1))
    accepted: list[Any] = []
    frontier = edge
    saw_large_op = False
    for it in ordered:
        near = it.bbox.y0 if upward else it.bbox.y1
        gap = (near - frontier) if upward else (frontier - near)
        tol = tol_large_op if saw_large_op else tol_normal
        # The *nearest* item is always part of the block: the distance from a fraction
        # bar to its numerator is set by num1/num2, which is much larger than any gap
        # *within* the numerator, and TeX's clearance rules only ever increase it.
        if accepted and gap > tol:
            break
        accepted.append(it)
        far = it.bbox.y1 if upward else it.bbox.y0
        frontier = max(frontier, far) if upward else min(frontier, far)
        saw_large_op = saw_large_op or is_large_op(it)
    return accepted


# ----------------------------------------------------------------------- rule kinds

FRACTION_BAR = "fraction-bar"
RADICAL_BAR = "radical-overbar"
OVERLINE = "overline"
UNDERLINE = "underline"
UNUSED = "unclassified"


@dataclass
class ClassifiedRule:
    """A rule together with the structural role we assigned it, and why."""

    rule: Rule
    kind: str
    evidence: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
