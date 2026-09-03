"""Fraction, overline and underline recognition -- the inversion of Appendix G rule 15.

A horizontal rule in a TeX PDF is one of four things: a fraction bar, a radical overbar,
an ``\\overline``, or an ``\\underline``.  (It is never a minus sign: ``-`` is
``cmsy``'s ``minus`` *glyph*, so the classic OCR confusion does not arise here at all.)
Radical overbars are claimed first, by radicals.py, because they are identified by
touching a surd.  The remaining three are told apart by what surrounds them:

* material above **and** below  -> fraction bar
* material only below           -> overline
* material only above           -> underline

Having classified it, we check the arithmetic.  Rule 15 puts the bar's centre exactly
``axis_height`` above the fraction's own baseline, the numerator's baseline ``num1``
above that (in display style; ``num2`` otherwise), and the denominator's ``denom1`` /
``denom2`` below.  Those three numbers are recoverable, so the recogniser reports a
residual rather than a guess -- and the residual doubles as a style detector, since the
same measurement fits display and text style differently.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

from ..extraction.model import Rule
from ..fonts.mathparams import Style
from ..geometry.bbox import BBox
from . import blocks
from .context import ParseContext
from .units import FRACTION_BAR, OVERLINE, UNDERLINE, ClassifiedRule, GlyphRun


def _candidates(rule: Rule, runs: Sequence[GlyphRun], rules: Sequence[Rule],
                ctx: ParseContext) -> tuple[list[Any], list[Any]]:
    """Everything in the rule's column, split into what is above it and what is below."""
    span = rule.bbox
    pad = ctx.x_tol
    above: list[Any] = []
    below: list[Any] = []
    for r in runs:
        b = r.bbox
        if not (span.x0 - pad <= b.cx <= span.x1 + pad):
            continue
        (above if b.cy > span.y1 else below).append(r)
    for o in rules:
        if o.id == rule.id:
            continue
        b = o.bbox
        # Containment, not centring: rule 15 makes a bar exactly as wide as the wider of
        # its two parts, so a *nested* bar always lies strictly inside its parent's span
        # and never the reverse.  Testing containment is what lets the outermost bar win
        # the anchor contest for \\frac{\\frac{a}{b}}{c}.
        if not span.contains_x(b, pad):
            continue
        (above if b.cy > span.y1 else below).append(o)
    return above, below


def claim(rule: Rule, runs: Sequence[GlyphRun], rules: Sequence[Rule],
          ctx: ParseContext) -> tuple[list[GlyphRun], list[GlyphRun],
                                      list[Rule], list[Rule]]:
    """Partition the material in a bar's column into numerator and denominator parts.

    Membership is by box *centre* inside the bar's horizontal span -- rule 15 makes the
    bar precisely as wide as the wider of the two parts and centres the narrower one
    inside it, so anything belonging to the fraction has its centre in the span and
    anything outside it does not -- and then by structural cohesion (blocks.py), which
    is what keeps a fraction inside a matrix cell from reaching into the row above.
    """
    above, below = _candidates(rule, runs, rules, ctx)
    num = blocks.block_above(rule.bbox.y1, above, ctx)
    den = blocks.block_below(rule.bbox.y0, below, ctx)
    num = _absorb_orphans(rule, num, above, runs, ctx)
    den = _absorb_orphans(rule, den, below, runs, ctx)
    num, den = _match_bar_width(rule, num, den, above, below, ctx)
    num_r = [i for i in num if isinstance(i, GlyphRun)]
    num_l = [i for i in num if not isinstance(i, GlyphRun)]
    den_r = [i for i in den if isinstance(i, GlyphRun)]
    den_l = [i for i in den if not isinstance(i, GlyphRun)]
    return num_r, den_r, num_l, den_l


def _span(items: Sequence[Any]) -> float:
    if not items:
        return 0.0
    return max(i.bbox.x1 for i in items) - min(i.bbox.x0 for i in items)


def _absorb_orphans(rule: Rule, block: list[Any], side: Sequence[Any],
                    runs: Sequence[GlyphRun], ctx: ParseContext) -> list[Any]:
    """Pull in material that is inside the bar's span and belongs to nothing else.

    The parts of a fraction need not be vertically contiguous: a matrix in the
    denominator has rows that do not touch, so cohesion alone stops after the first one.
    The test that separates "another row of my denominator" from "another row of the
    enclosing table" is not a distance -- it is whether the candidate has a *baseline
    mate outside the bar's span*.  Material on a line that continues past the fraction
    belongs to that line; material on a line confined to the fraction's own column has
    nowhere else to be.
    """
    span = rule.bbox
    pad = ctx.x_tol
    claimed = list(block)
    for cand in side:
        if any(cand is c for c in claimed):
            continue
        if _has_baseline_mate_outside(cand, runs, span, pad, ctx):
            continue
        for extra in blocks.cohesive_block(list(side), cand, ctx):
            if not any(extra is c for c in claimed):
                claimed.append(extra)
    return claimed


def _has_baseline_mate_outside(cand: Any, runs: Sequence[GlyphRun], span: BBox,
                               pad: float, ctx: ParseContext) -> bool:
    """Does anything on this candidate's baseline lie outside the bar's column?"""
    baseline = getattr(cand, "head", None)
    y = baseline.y if baseline is not None else cand.bbox.cy
    for r in runs:
        if r is cand:
            continue
        cx = r.bbox.cx
        if span.x0 - pad <= cx <= span.x1 + pad:
            continue
        if abs(r.head.y - y) <= ctx.baseline_tol:
            return True
    return False


def _match_bar_width(rule: Rule, num: list[Any], den: list[Any],
                     above: Sequence[Any], below: Sequence[Any],
                     ctx: ParseContext) -> tuple[list[Any], list[Any]]:
    """Widen an under-claimed numerator or denominator until rule 15 is satisfied.

    Rule 15 makes the bar *exactly* as wide as the wider of the two parts.  That is a
    check we can run, and a repair: if neither claimed block is as wide as the bar, the
    cohesion test stopped too early -- a matrix in the numerator has rows that do not
    touch each other -- and the next block outward has to be pulled in.  Growing to a
    measurable target beats guessing at a gap threshold.
    """
    tol = max(0.1, 0.02 * ctx.text_size)
    for _ in range(8):
        if max(_span(num), _span(den)) >= rule.width - tol:
            break
        side, pool = ((num, above) if _span(num) <= _span(den) else (den, below))
        rest = [i for i in pool if i not in side]
        if not rest:
            side, pool = ((den, below) if side is num else (num, above))
            rest = [i for i in pool if i not in side]
            if not rest:
                break
        edge = min(rest, key=lambda i: abs(i.bbox.cy - rule.y_center))
        side.extend(blocks.cohesive_block(rest, edge, ctx))
    return num, den


def classify_rule(rule: Rule, runs: Sequence[GlyphRun], other_rules: Sequence[Rule],
                  ctx: ParseContext) -> ClassifiedRule:
    """Decide what a horizontal rule is for, from the material in its column.

    A horizontal rule in a TeX PDF is one of four things, and what surrounds it says
    which: material above *and* below is a fraction bar, only below is an ``\\overline``,
    only above an ``\\underline``.  (Radical overbars never reach here -- radicals.py
    claims them first, by the surd they touch.)  It is never a minus sign: ``-`` is
    cmsy's ``minus`` *glyph*, so the classic OCR confusion does not arise at all.
    """
    num_r, den_r, num_l, den_l = claim(rule, runs, other_rules, ctx)
    above = num_r + num_l
    below = den_r + den_l

    ev: dict[str, Any] = {
        "rule_width_pt": round(rule.width, 4),
        "rule_thickness_pt": round(rule.thickness, 5),
        "expected_default_rule_thickness_pt": round(ctx.rule_thickness, 5),
        "thickness_residual_pt": round(rule.thickness - ctx.rule_thickness, 5),
        "n_above": len(above),
        "n_below": len(below),
    }
    if above and below:
        return ClassifiedRule(rule, FRACTION_BAR, ev, 1.0)
    if below and not above:
        return ClassifiedRule(rule, OVERLINE, ev, 1.0)
    if above and not below:
        return ClassifiedRule(rule, UNDERLINE, ev, 1.0)
    return ClassifiedRule(rule, FRACTION_BAR, ev, 0.2)


def verify(rule: Rule, num_baseline: Optional[float], den_baseline: Optional[float],
           ctx: ParseContext) -> dict[str, Any]:
    """Score a candidate fraction against rule 15, and infer the enclosing style.

    Returns the evidence dictionary; ``style_fit`` names whichever of display / text
    style explains the measurement, and ``residual_pt`` is how far off it is.
    """
    ev: dict[str, Any] = {}
    best: tuple[float, str, dict[str, float]] | None = None
    for style, label in ((Style.DISPLAY, "display"), (Style.TEXT, "text")):
        p = ctx._with(style).params
        baseline = rule.y_center - p.axis_height
        u = p.num1 if style.is_display else p.num2
        v = p.denom1 if style.is_display else p.denom2
        res = 0.0
        parts: dict[str, float] = {}
        if num_baseline is not None:
            d = (num_baseline - baseline) - u
            parts["numerator_residual_pt"] = d
            res = max(res, abs(d))
        if den_baseline is not None:
            d = (baseline - den_baseline) - v
            parts["denominator_residual_pt"] = d
            res = max(res, abs(d))
        if best is None or res < best[0]:
            best = (res, label, parts)
    assert best is not None
    ev["style_fit"] = best[1]
    ev["residual_pt"] = round(best[0], 5)
    ev.update({k: round(v, 5) for k, v in best[2].items()})
    ev["axis_height_pt"] = round(ctx.params.axis_height, 5)
    # The clearance rules in 15e can legitimately push a baseline further out, never
    # nearer, so a positive residual is expected and a negative one is suspicious.
    ev["consistent_with_rule_15"] = best[0] <= max(0.05, 0.01 * ctx.text_size) or all(
        v >= -0.05 for v in best[2].values())
    return ev


def confidence_from(ev: dict[str, Any], ctx: ParseContext) -> float:
    """Turn a rule-15 residual into a confidence in [0, 1]."""
    res = float(ev.get("residual_pt", 0.0))
    thick = abs(float(ev.get("thickness_residual_pt", 0.0)))
    tol = max(0.05, 0.01 * ctx.text_size)
    if res <= tol and thick <= 0.05:
        return 0.999
    if ev.get("consistent_with_rule_15"):
        return max(0.6, 0.95 - min(0.35, res / (4 * ctx.text_size)))
    return max(0.3, 0.8 - min(0.5, res / (2 * ctx.text_size)))
