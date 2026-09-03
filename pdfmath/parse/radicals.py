"""Radical recognition -- the inversion of Appendix G rule 11.

TeX draws a square root as two independent objects: a surd glyph (cmsy's ``radical``, one
of cmex's ``radicalbig``..``radicalBigg``, or a column of ``radicaltp`` / ``radicalvertex``
/ ``radicalbt`` pieces) and a *separate stroked rule* over the radicand.  Neither carries
any indication that it belongs to the other.  They are re-associated by geometry, and
rule 11 says exactly what that geometry must be:

* the overbar's left edge sits at the surd's right edge;
* the overbar's top sits at the surd's top;
* the overbar's thickness is ``default_rule_thickness``;
* the gap between the radicand's top and the overbar's bottom is ``clr``, where
  ``clr = theta + |sigma_5|/4`` in display style and ``theta + theta/4`` otherwise,
  increased by half of any surplus depth in the chosen surd variant.

That last clause is what makes a naive "bar just above something" test fail on real
documents: the gap varies with which surd cmex handed back.  Computing it exactly turns a
fuzzy match into an equality.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

from ..extraction.model import Rule
from ..fonts.symbols import Role
from ..geometry.bbox import BBox
from .context import ParseContext
from .units import GlyphRun


def find_overbar(surd: GlyphRun, rules: Sequence[Rule],
                 ctx: ParseContext) -> Optional[Rule]:
    """The rule that this surd covers, or ``None``.

    Matched on the two coincidences rule 11 guarantees: the bar starts where the surd
    ends, and their tops agree.
    """
    b = surd.bbox
    tol = max(0.08, 0.01 * ctx.text_size)
    best, best_err = None, float("inf")
    for r in rules:
        if not r.is_horizontal:
            continue
        err = abs(r.bbox.x0 - b.x1) + abs(r.bbox.y1 - b.y1)
        if err < best_err and abs(r.bbox.x0 - b.x1) <= tol * 3 \
                and abs(r.bbox.y1 - b.y1) <= tol * 3:
            best, best_err = r, err
    return best


def claim(surd: GlyphRun, overbar: Rule, runs: Sequence[GlyphRun],
          rules: Sequence[Rule], ctx: ParseContext
          ) -> tuple[list[GlyphRun], list[Rule], list[GlyphRun]]:
    """Split the surrounding material into (radicand, radicand rules, index).

    The radicand is whatever lies under the overbar; the index -- the ``n`` of
    ``\\sqrt[n]{x}`` -- is whatever sits above and to the left of the surd.
    """
    span = overbar.bbox
    pad = ctx.x_tol
    sb = surd.bbox
    radicand: list[GlyphRun] = []
    index: list[GlyphRun] = []
    inner_rules: list[Rule] = []

    def under_the_bar(b) -> bool:
        # The surd was sized by var_delimiter to *cover* the radicand, so the radicand
        # lies within the surd's own vertical extent.  That is an exact bound and needs
        # no tolerance, which keeps material from a neighbouring line out.
        return (span.x0 - pad <= b.cx <= span.x1 + pad
                and sb.y0 - ctx.eps <= b.cy <= span.y0 + ctx.eps)

    for r in runs:
        if r is surd:
            continue
        b = r.bbox
        if under_the_bar(b):
            radicand.append(r)
        elif _looks_like_index(r, surd, ctx):
            index.append(r)
    for o in rules:
        if o.id == overbar.id:
            continue
        if under_the_bar(o.bbox):
            inner_rules.append(o)
    return radicand, inner_rules, index


def _looks_like_index(run: GlyphRun, surd: GlyphRun, ctx: ParseContext) -> bool:
    """Is this the ``n`` of ``\\sqrt[n]{x}``?

    ``\\root`` sets the index in *scriptscript* style and raises it by 0.6 of the
    radical box's height-minus-depth, placing it to the left of the surd and overlapping
    it by 5 mu.  The size test is what keeps an ordinary symbol standing to the left of
    the radical -- an opening bracket, say -- from being mistaken for an index.
    """
    b = run.bbox
    if b.x1 > surd.bbox.x1:
        return False
    if run.head.size > ctx.size * 0.6 + ctx.eps:      # scriptscript is 0.5 of text size
        return False
    return b.cy > surd.bbox.cy


def verify(surd: GlyphRun, overbar: Rule, radicand_box: Optional[BBox],
           radicand_baseline: Optional[float], ctx: ParseContext) -> dict[str, Any]:
    """Check the measured clearance against rule 11 and return the evidence."""
    theta = ctx.rule_thickness
    sigma5 = ctx.params.x_height
    clr = theta + (abs(sigma5) / 4 if ctx.style.is_display else abs(theta) / 4)
    surd_depth = surd.head.y - surd.bbox.y0
    ev: dict[str, Any] = {
        "surd_glyph": surd.symbol.glyph,
        "surd_size_rank": surd.symbol.size_rank,
        "surd_pieces": len(surd.glyphs),
        "overbar_thickness_pt": round(overbar.thickness, 5),
        "expected_thickness_pt": round(theta, 5),
        "left_edge_residual_pt": round(overbar.bbox.x0 - surd.bbox.x1, 5),
        "top_edge_residual_pt": round(overbar.bbox.y1 - surd.bbox.y1, 5),
        "style": ctx.style.name,
    }
    if radicand_box is not None:
        h = radicand_box.y1 - (radicand_baseline if radicand_baseline is not None
                               else radicand_box.y0)
        d = (radicand_baseline if radicand_baseline is not None
             else radicand_box.y0) - radicand_box.y0
        delta = surd_depth - (h + d + clr)
        clr_adj = clr + delta / 2 if delta > 0 else clr
        measured = overbar.bbox.y0 - radicand_box.y1
        ev["expected_clearance_pt"] = round(clr_adj, 5)
        ev["measured_clearance_pt"] = round(measured, 5)
        ev["clearance_residual_pt"] = round(measured - clr_adj, 5)
    return ev


def confidence_from(ev: dict[str, Any], ctx: ParseContext) -> float:
    tol = max(0.05, 0.01 * ctx.text_size)
    edge = abs(ev.get("left_edge_residual_pt", 0.0)) + abs(ev.get("top_edge_residual_pt", 0.0))
    clr = abs(ev.get("clearance_residual_pt", 0.0))
    if edge <= tol and clr <= tol:
        return 0.999
    if edge <= 4 * tol:
        return max(0.7, 0.97 - clr / (2 * ctx.text_size))
    return 0.5


def is_surd(run: GlyphRun) -> bool:
    return run.symbol.role == Role.RADICAL
