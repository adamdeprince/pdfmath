"""Large operators and their limits -- the inversion of Appendix G rules 13 and 750-751.

Two TeX behaviours have to be undone.

**Axis centring.**  ``make_op`` shifts the operator's box down by
``(h - d)/2 - axis_height`` so that its middle lands on the maths axis.  The glyph's
drawn baseline is therefore *not* the line's baseline, and any recogniser that assumes
otherwise will misjudge everything to the right of a summation sign.  The shift is
computed from the glyph's own TFM height and depth, so we can undo it exactly and recover
the line's baseline from a lone integral.

**Limits above and below.**  In display style ``\\sum`` takes its limits over and under,
separated from the operator by

    shift_up   = max(big_op_spacing3 - d(upper),  big_op_spacing1)
    shift_down = max(big_op_spacing4 - h(lower),  big_op_spacing2)

with the upper limit displaced right by half the operator's italic correction and the
lower limit left by the same amount.  In text style the same source produces ordinary
scripts instead, which is why display and text ``\\sum_i`` look so different -- and why
seeing limits at all is evidence that the style is display.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable, Optional

from ..fonts.symbols import AtomClass, Role
from ..geometry.bbox import BBox
from ..geometry.index import vertical_bands
from ..tree.nodes import MathNode, Provenance, UnderOver
from .context import Explanation, ParseContext
from .units import Unit

ParseGroup = Callable[[list[Unit], ParseContext], MathNode]


def attach(units: list[Unit], ctx: ParseContext, parse_group: ParseGroup,
           row_baseline: float) -> list[Unit]:
    """Fold over/under limits into their operators."""
    # Two passes: a limit can sit to the *left* of its operator's reference point
    # (\prod's lower limit starts before the glyph does, because the limit box is wider
    # and both are centred), so nothing may be emitted until every claim is known.
    consumed: set[int] = set()
    built: dict[int, Unit] = {}
    for i, op in enumerate(units):
        if op.role != Role.LARGE_OP or i in consumed:
            continue
        above, below = [], []
        for j, u in enumerate(units):
            if j == i or j in consumed or u.role == Role.LARGE_OP:
                continue
            if not _is_limit_of(u, op, ctx):
                continue
            (above if u.baseline > op.baseline else below).append((j, u))
        if not above and not below:
            continue
        # A limit is centred on the operator and can be much wider than it, so only its
        # middle passes the centring test; the rest of the limit is found by following
        # the baseline outward from that seed.
        above = _extend_limit(above, units, consumed, op, ctx, upward=True)
        below = _extend_limit(below, units, consumed, op, ctx, upward=False)
        for j, _ in above + below:
            consumed.add(j)
        upper = _pack([u for _, u in above], ctx.superscript(), parse_group)
        lower = _pack([u for _, u in below], ctx.subscript(), parse_group)
        built[i] = _build(op, upper, lower, ctx)

    out: list[Unit] = []
    for i, u in enumerate(units):
        if i in consumed:
            continue
        out.append(built.get(i, u))
    return out


def _extend_limit(seeds: list[tuple[int, Unit]], units: list[Unit],
                  consumed: set[int], op: Unit, ctx: ParseContext,
                  upward: bool) -> list[tuple[int, Unit]]:
    """Grow a limit outward along its own baseline from the units already claimed."""
    if not seeds:
        return seeds
    claimed = {j for j, _ in seeds}
    baseline = seeds[0][1].baseline
    gap = 5.0 / 18.0 * (ctx.params.quad or ctx.size)     # a thick space
    changed = True
    while changed:
        changed = False
        members = [u for j, u in seeds]
        left = min(u.x0 for u in members)
        right = max(u.x1 for u in members)
        for j, u in enumerate(units):
            if j in claimed or j in consumed or u is op:
                continue
            if abs(u.baseline - baseline) > ctx.baseline_tol:
                continue
            if u.size > op.size + ctx.eps:
                continue
            if u.bbox.overlap_y(op.bbox) > 0:
                continue
            if left - gap <= u.x1 and u.x0 <= right + gap:
                seeds.append((j, u))
                claimed.add(j)
                changed = True
    return sorted(seeds)


def _is_limit_of(u: Unit, op: Unit, ctx: ParseContext) -> bool:
    """A limit is centred on the operator; a script sits strictly to its right."""
    if u.size > op.size + ctx.eps:
        return False
    if not (op.x0 - ctx.x_tol <= u.bbox.cx <= op.x1 + ctx.x_tol):
        return False
    if u.x0 >= op.x1 - ctx.eps:
        return False           # entirely to the right: that is a script, not a limit
    if u.bbox.overlap_y(op.bbox) > 0:
        return False           # overlapping the operator vertically: not above or below
    return abs(u.baseline - op.baseline) > ctx.baseline_tol


def _pack(group: list[Unit], ctx: ParseContext,
          parse_group: ParseGroup) -> Optional[Unit]:
    if not group:
        return None
    group = sorted(group, key=lambda u: u.x0)
    node = parse_group(group, ctx)
    box = BBox.union([u.bbox for u in group])
    gids = [g for u in group for g in u.glyph_ids]
    rids = [r for u in group for r in u.rule_ids]
    return Unit.composite(node, group[0].baseline, box,
                          max(u.size for u in group), gids, rids,
                          atom=AtomClass.ORD)


def _build(op: Unit, upper: Optional[Unit], lower: Optional[Unit],
           ctx: ParseContext) -> Unit:
    p = ctx.params
    ev: dict[str, Any] = {
        "operator": op.symbol.glyph if op.symbol else None,
        "operator_size_rank": op.symbol.size_rank if op.symbol else 0,
        "style": ctx.style.name,
        "axis_height_pt": round(p.axis_height, 5),
    }
    conf = 0.99
    if upper is not None:
        expected = max(p.big_op_spacing(3) - upper.depth, p.big_op_spacing(1))
        measured = (upper.baseline - upper.depth) - (op.baseline + op.height)
        ev["upper_gap_pt"] = round(measured, 5)
        ev["expected_upper_gap_pt"] = round(expected, 5)
        ev["upper_gap_residual_pt"] = round(measured - expected, 5)
        ev["upper_centre_offset_pt"] = round(upper.bbox.cx - op.bbox.cx, 5)
        conf = min(conf, _score(measured - expected, ctx))
    if lower is not None:
        expected = max(p.big_op_spacing(4) - lower.height, p.big_op_spacing(2))
        measured = (op.baseline - op.depth) - (lower.baseline + lower.height)
        ev["lower_gap_pt"] = round(measured, 5)
        ev["expected_lower_gap_pt"] = round(expected, 5)
        ev["lower_gap_residual_pt"] = round(measured - expected, 5)
        ev["lower_centre_offset_pt"] = round(lower.bbox.cx - op.bbox.cx, 5)
        conf = min(conf, _score(measured - expected, ctx))

    children: list[MathNode] = [op.node]
    if lower is not None:
        children.append(lower.node)
    if upper is not None:
        children.append(upper.node)
    node = UnderOver(children=children,
                     has_under=lower is not None, has_over=upper is not None)
    parts = [u for u in (op, upper, lower) if u is not None]
    gids = sorted({g for u in parts for g in u.glyph_ids})
    rids = sorted({r for u in parts for r in u.rule_ids})
    box = BBox.union([u.bbox for u in parts])
    node.prov = Provenance(gids, rids, box, conf, ev, "limits")
    ctx.trace.add(Explanation(
        relationship="limits", node_id=node.node_id,
        parts={"operator": op.node.node_id,
               "over": upper.node.node_id if upper else None,
               "under": lower.node.node_id if lower else None},
        confidence=conf, evidence=ev))
    return Unit.composite(node, op.baseline, box, op.size, gids, rids,
                          atom=AtomClass.OP)


def _score(residual: float, ctx: ParseContext) -> float:
    tol = max(0.05, 0.005 * ctx.text_size)
    a = abs(residual)
    if a <= tol:
        return 0.999
    return max(0.3, 0.95 - a / ctx.text_size)
