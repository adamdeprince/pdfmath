"""Inverting TeX's inter-atom spacing.

TeX inserts glue between adjacent math atoms according to a table indexed by the pair of
atom classes (*The TeXbook*, ch. 18).  The amounts are multiples of ``mu``, one
eighteenth of the *math quad* -- ``\\fontdimen6`` of the current family-2 font, 10 pt in
cmsy10 -- so at 10 pt a thin space is 1.667 pt, a medium space 2.222 pt and a thick space
2.778 pt.  These are large, well separated, and computed from a font parameter we hold.

That makes the map invertible.  Measure the gap between two glyph boxes, divide by the
math quad, and the result lands on one of four values.  Knowing which one constrains the
pair of atom classes that produced it, which is independent evidence for -- or against --
the classification we derived from the glyph names.

The parenthesised entries in the table are inserted only in display and text style; in
script styles they vanish.  That is itself a style detector.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..fonts.symbols import AtomClass
from .context import ParseContext

NONE, THIN, MEDIUM, THICK = 0, 1, 2, 3

#: mu per space class.  1 mu = 1/18 quad.
MU = {NONE: 0.0, THIN: 3.0, MEDIUM: 4.0, THICK: 5.0}

_X = None    # an impossible pair (a Bin next to a Rel, say): TeX would have reclassified

#: table[left][right] -> (class, script_styles_too)
#  Rows and columns are ordered Ord, Op, Bin, Rel, Open, Close, Punct, Inner.
_TABLE: list[list[Optional[tuple[int, bool]]]] = [
    # Ord
    [(NONE, True), (THIN, True), (MEDIUM, False), (THICK, False),
     (NONE, True), (NONE, True), (NONE, True), (THIN, False)],
    # Op
    [(THIN, True), (THIN, True), _X, (THICK, False),
     (NONE, True), (NONE, True), (NONE, True), (THIN, False)],
    # Bin
    [(MEDIUM, False), (MEDIUM, False), _X, _X,
     (MEDIUM, False), _X, _X, (MEDIUM, False)],
    # Rel
    [(THICK, False), (THICK, False), _X, (NONE, True),
     (THICK, False), (NONE, True), (NONE, True), (THICK, False)],
    # Open
    [(NONE, True), (NONE, True), _X, (NONE, True),
     (NONE, True), (NONE, True), (NONE, True), (NONE, True)],
    # Close
    [(NONE, True), (THIN, True), (MEDIUM, False), (THICK, False),
     (NONE, True), (NONE, True), (NONE, True), (THIN, False)],
    # Punct
    [(THIN, False), (THIN, False), _X, (THIN, False),
     (THIN, False), (THIN, False), (THIN, False), (THIN, False)],
    # Inner
    [(THIN, False), (THIN, True), (MEDIUM, False), (THICK, False),
     (THIN, False), (NONE, True), (THIN, False), (THIN, False)],
]


def expected_mu(left: AtomClass, right: AtomClass, script_style: bool) -> Optional[float]:
    """The glue TeX inserts between these classes, in mu, or ``None`` if the pair is
    one TeX would never produce."""
    entry = _TABLE[int(left)][int(right)]
    if entry is None:
        return None
    cls, always = entry
    if not always and script_style:
        return 0.0
    return MU[cls]


@dataclass(frozen=True)
class SpaceObservation:
    """A measured gap, with the classification it best supports."""

    gap_pt: float
    gap_mu: float
    nearest_class: int
    nearest_mu: float
    residual_mu: float
    quad_pt: float

    @property
    def name(self) -> str:
        return {NONE: "none", THIN: "thin", MEDIUM: "medium", THICK: "thick"}[
            self.nearest_class]

    @property
    def is_clean(self) -> bool:
        """Within a quarter of a mu of an exact TeX space."""
        return abs(self.residual_mu) <= 0.25


def observe(gap_pt: float, ctx: ParseContext) -> SpaceObservation:
    """Classify a measured inter-atom gap."""
    quad = ctx.params.quad or ctx.size
    mu = gap_pt / (quad / 18.0)
    best = min(MU.items(), key=lambda kv: abs(kv[1] - mu))
    return SpaceObservation(gap_pt, mu, best[0], best[1], mu - best[1], quad)


def consistent_classes(obs: SpaceObservation, script_style: bool
                       ) -> list[tuple[AtomClass, AtomClass]]:
    """Every atom-class pair that would produce the observed space.

    Used by ``pdfmath explain`` to show what the spacing alone proves, independently of
    the glyph-name evidence.
    """
    out = []
    for l in AtomClass:
        for r in AtomClass:
            e = expected_mu(l, r, script_style)
            if e is not None and abs(e - obs.nearest_mu) < 1e-9:
                out.append((l, r))
    return out
