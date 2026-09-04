"""Superscript and subscript recognition -- the inversion of Appendix G rule 18.

This is the recogniser the whole project's hypothesis rests on, so it is worth being
precise about what it does *not* do.  It does not ask whether a glyph is small and high.
It computes the shift TeX would have applied, from the nucleus's TFM box, the script
box's TFM box and the sigma parameters of the current style, and compares that number
with the measured baseline difference.  On stock pdfTeX output the residual is under a
thousandth of a point -- the PDF's own coordinate rounding.

The rule, transcribed from tex.web 756-759:

    if the nucleus is a bare character:  u = v = 0
    otherwise:                           u = h(nucleus) - sup_drop(t)
                                         v = d(nucleus) + sub_drop(t)     [t = script size]

    superscript only:
        clr      = sup3 if cramped else sup1 if display else sup2
        shift_up = max(u, clr, d(sup) + |x_height|/4)

    subscript only:
        shift_down = max(v, sub1, h(sub) - (4/5)|x_height|)

    both:
        shift_up   as above
        shift_down = max(v, sub2)
        if (shift_up - d(sup)) - (h(sub) - shift_down) < 4*theta:
            shift_down += 4*theta - ((shift_up - d(sup)) - (h(sub) - shift_down))
            psi = (4/5)|x_height| - (shift_up - d(sup))
            if psi > 0: shift_up += psi;  shift_down -= psi

    horizontally: the superscript starts at x + w + italic, the subscript at x + w.

Splitting a script cluster into its superscript and subscript halves uses the same
source of truth: the final clause guarantees at least ``4 * default_rule_thickness`` of
clearance between them, which is far more than the zero gap inside either half.  The
"threshold" is therefore a TeX constant, not a tuned one.
"""

from __future__ import annotations

from typing import Any, Callable, Optional, Sequence

from ..fonts.symbols import AtomClass, Role
from ..geometry.bbox import BBox
from ..geometry.index import vertical_bands
from ..tree.nodes import MathNode, Provenance, SubSup, Subscript, Superscript
from .context import Explanation, ParseContext
from .units import Unit

ParseGroup = Callable[[list[Unit], ParseContext], MathNode]


def predict_shifts(base: Unit, sup: Optional[Unit], sub: Optional[Unit],
                   ctx: ParseContext) -> tuple[Optional[float], Optional[float]]:
    """(shift_up, shift_down) that TeX would have used, in points."""
    p = ctx.params
    sup_p = ctx.superscript().params        # sigma_18/19 come from the *script* size
    if base.is_char:
        u = v = 0.0
    else:
        u = base.height - sup_p.sup_drop
        v = base.depth + sup_p.sub_drop

    shift_up = shift_down = None
    if sup is not None:
        if ctx.style.cramped:
            clr = p.sup3
        elif ctx.style.is_display:
            clr = p.sup1
        else:
            clr = p.sup2
        shift_up = max(u, clr, sup.depth + abs(p.x_height) / 4)
    if sub is not None and sup is None:
        shift_down = max(v, p.sub1, sub.height - 0.8 * abs(p.x_height))
    elif sub is not None:
        shift_down = max(v, p.sub2)
        theta = ctx.rule_thickness
        gap = (shift_up - sup.depth) - (sub.height - shift_down)
        if gap < 4 * theta:
            shift_down += 4 * theta - gap
            psi = 0.8 * abs(p.x_height) - (shift_up - sup.depth)
            if psi > 0:
                shift_up += psi
                shift_down -= psi
    return shift_up, shift_down


def _split_cluster(cluster: Sequence[Unit], base: Unit,
                   ctx: ParseContext) -> tuple[list[Unit], list[Unit]]:
    """Divide a script cluster into (superscript units, subscript units)."""
    if not cluster:
        return [], []
    boxes = [u.bbox for u in cluster]
    theta = ctx.rule_thickness
    bands = vertical_bands(boxes, gap=2 * theta)
    if len(bands) == 1:
        above = sum(1 for u in cluster if u.baseline > base.baseline)
        return (list(cluster), []) if above * 2 >= len(cluster) else ([], list(cluster))
    if len(bands) == 2:
        top = [cluster[i] for i in bands[0]]
        bot = [cluster[i] for i in bands[1]]
        return top, bot
    # More than two bands should not happen for a script pair; keep everything rather
    # than dropping material, splitting on the base's baseline.
    top = [u for u in cluster if u.baseline > base.baseline]
    bot = [u for u in cluster if u.baseline <= base.baseline]
    return top, bot


def _bands(cluster: Sequence[Unit], ctx: ParseContext) -> list[list[Unit]]:
    """Split units into vertically separated groups.

    The separation is guaranteed by TeX: rule 18f forces at least
    ``4 * default_rule_thickness`` between a superscript and a subscript on one nucleus,
    far more than the (usually negative) gap between a base and its own script.  The
    threshold is a TeX constant, not a tuned one.
    """
    boxes = [u.bbox for u in cluster]
    groups = vertical_bands(boxes, gap=2 * ctx.rule_thickness)
    return [[cluster[i] for i in g] for g in groups]


def _band_baseline(band: Sequence[Unit]) -> float:
    return min(band, key=lambda u: u.x0).baseline


def attach(units: list[Unit], ctx: ParseContext, parse_group: ParseGroup,
           row_baseline: float) -> list[Unit]:
    """Fold script clusters into their bases, left to right.

    Two things have to be got right at once.

    *Which side a unit is on.*  A subscript can contain its own superscript, and that
    superscript can sit above the base's baseline -- ``x_{9^s}`` is the small case, an
    operator with its own limits inside a subscript the large one.  Comparing every
    unit's baseline against the base's therefore gets the wrong answer.  What is
    reliable is the pair of boxes that *start* at the base's advance: rule 18f keeps them
    ``4 * default_rule_thickness`` apart, so the gap between them is a cut line, and
    everything in the cluster falls on one side of it or the other.

    *Where the cluster stops belonging to this nucleus.*  In ``{x^2}_i`` the subscript
    is attached to the box, not to ``x``, and starts after that box ends.  So the set is
    grown by horizontal contiguity from the leading column, and whatever begins beyond
    its right edge is chained onto the result instead.
    """
    out: list[Unit] = []
    i = 0
    n = len(units)
    expected = ctx.size_of(ctx.style.sup_style())
    tol = max(0.1, 0.02 * ctx.text_size)
    # Returning to the row means returning to the row's *size* as well as its baseline.
    # A script nested two levels deep can land within rounding distance of the row
    # baseline by coincidence -- the superscript of a subscript often does -- and
    # ending the cluster there would strand everything after it.
    row_size = max((u.size for u in units
                    if abs(u.baseline - row_baseline) <= ctx.baseline_tol),
                   default=ctx.size)
    while i < n:
        base = units[i]
        j = i + 1
        cluster: list[Unit] = []
        while j < n:
            u = units[j]
            if (abs(u.baseline - row_baseline) <= ctx.baseline_tol
                    and u.size >= row_size - ctx.eps):
                break
            if u.x0 < base.x1 - ctx.x_tol:
                break
            if u.size > base.size + ctx.eps:
                break
            # TeX sets scripts one style down, so their size is fixed in advance.
            if u.size > expected + ctx.eps:
                break
            cluster.append(u)
            j += 1
        if not cluster:
            out.append(base)
            i += 1
            continue

        cur = base
        pending = list(cluster)
        for _ in range(len(cluster)):
            if not pending:
                break
            attached, pending = _attach_one(cur, pending, ctx, parse_group, tol)
            if attached is cur:
                break
            cur = attached
        out.append(cur)
        for u in pending:                 # never drop anything we could not explain
            out.append(u)
        i = j
    return out


def _attach_one(base: Unit, cluster: list[Unit], ctx: ParseContext,
                parse_group: ParseGroup, tol: float) -> tuple[Unit, list[Unit]]:
    """Attach the scripts that belong to ``base``; return the rest of the cluster."""
    reach = base.box_x1 + tol
    # box_x0, not x0: a fraction's box starts \nulldelimiterspace to the left of its
    # rule, so a fraction used as a superscript begins at the nucleus's advance even
    # though its ink starts 1.2 pt further right.  Measuring the ink would leave it out
    # of the leading column and lose the cut line that separates it from the subscript.
    leading = [u for u in cluster if u.box_x0 <= reach]
    if not leading:
        leading = [min(cluster, key=lambda u: u.box_x0)]

    lead_bands = _bands(leading, ctx)
    cut: Optional[float] = None
    if len(lead_bands) >= 2:
        upper = max(lead_bands, key=lambda b: min(u.bbox.y0 for u in b))
        lower = min(lead_bands, key=lambda b: max(u.bbox.y1 for u in b))
        cut = 0.5 * (min(u.bbox.y0 for u in upper) + max(u.bbox.y1 for u in lower))

    # Growing the assigned set.  Two tolerances, and the difference between them is
    # what separates "more of this script" from "a script on the whole box".
    #
    #   tight  -- box-to-box contiguity.  Inside a script, TeX's medium and thick glue
    #             is suppressed (those table entries are parenthesised, i.e. display and
    #             text style only), so consecutive atoms touch.
    #   wide   -- up to a thick space, which does survive in script styles between, say,
    #             an operator and an ordinary atom.
    #
    # A unit already on the same side of the base's baseline as the leading group is
    # allowed the wide tolerance; one on the far side has to be genuinely contiguous,
    # because that is how "{x^2}_i" (subscript on the box, separated by \scriptspace)
    # differs from "x_{9^s}" (superscript inside the subscript, touching it).
    tight = max(0.05, 0.005 * ctx.text_size)
    wide = 5.0 / 18.0 * (ctx.superscript().params.quad or ctx.size)
    lead_above = _band_baseline(leading) > base.baseline
    assigned = list(leading)
    edge = max(u.box_x1 for u in assigned)
    changed = True
    while changed:
        changed = False
        for u in cluster:
            if any(u is a for a in assigned):
                continue
            same_side = (u.baseline > base.baseline) == lead_above
            limit = wide if (same_side or cut is not None) else tight
            if u.box_x0 > edge + limit:
                continue
            # Contiguity is necessary but not sufficient.  In "{D^0}^x" the outer
            # superscript follows the inner one across a \scriptspace and is the same
            # size as it -- and a script of the inner one would have been *smaller*, so
            # equal size on a different baseline means a different level.  Material that
            # really is part of this script either shares its baseline or is a script of
            # something in it, which TeX sets one style down again.
            group = [a for a in assigned
                     if (a.baseline > base.baseline) == (u.baseline > base.baseline)]
            if group:
                lead = min(group, key=lambda a: a.x0)
                if (abs(u.baseline - lead.baseline) > ctx.baseline_tol
                        and u.size >= lead.size - ctx.eps):
                    continue
            assigned.append(u)
            edge = max(edge, u.box_x1)
            changed = True

    if cut is not None:
        sup_units = [u for u in assigned if u.bbox.cy > cut]
        sub_units = [u for u in assigned if u.bbox.cy <= cut]
    else:
        sup_units = list(assigned) if lead_above else []
        sub_units = [] if lead_above else list(assigned)

    built = _build(base,
                   _pack(sup_units, ctx.superscript(), parse_group),
                   _pack(sub_units, ctx.subscript(), parse_group), ctx)
    rest = [u for u in cluster if not any(u is a for a in assigned)]
    return built, rest


def _pack(group: list[Unit], ctx: ParseContext,
          parse_group: ParseGroup) -> Optional[Unit]:
    if not group:
        return None
    node = parse_group(group, ctx)
    box = BBox.union([u.bbox for u in group])
    baseline = min(group, key=lambda u: u.x0).baseline
    # A group's baseline is that of its leftmost full-size member, matching how TeX
    # would have hpack'd it.
    full = [u for u in group if abs(u.size - max(g.size for g in group)) <= 1e-6]
    if full:
        baseline = min(full, key=lambda u: u.x0).baseline
    gids = [g for u in group for g in u.glyph_ids]
    rids = [r for u in group for r in u.rule_ids]
    # A braced sub-list is an Ord atom, whatever it contains, and it keeps the trailing
    # italic kern of its rightmost member (see _build).
    last = max(group, key=lambda u: u.x1)
    return Unit.composite(node, baseline, box, max(u.size for u in group), gids,
                          rids, atom=AtomClass.ORD, trail=last.trail)


def _candidate_styles(ctx: ParseContext) -> list[ParseContext]:
    """Styles that could have produced a script at this size.

    Display, text and their cramped variants all use the same font size and differ only
    in ``clr`` -- ``sup1`` against ``sup2`` against ``sup3``.  When a region is handed to
    us out of context (a bbox on a page, rather than a corpus expression we compiled) we
    do not know which applied, so all of them are tried and the one that explains the
    measurement is reported.  That is inference from evidence, not a fallback: the winner
    is recorded as ``style_fit`` and its residual is what sets the confidence.
    """
    from ..fonts.mathparams import Style
    if ctx.style < Style.SCRIPT:
        candidates = [Style.DISPLAY, Style.DISPLAY_CRAMPED,
                      Style.TEXT, Style.TEXT_CRAMPED]
    elif ctx.style < Style.SCRIPTSCRIPT:
        candidates = [Style.SCRIPT, Style.SCRIPT_CRAMPED]
    else:
        candidates = [Style.SCRIPTSCRIPT, Style.SCRIPTSCRIPT_CRAMPED]
    ordered = [ctx.style] + [c for c in candidates if c != ctx.style]
    return [ctx if c == ctx.style else ctx._with(c) for c in ordered]


def _fit_style(base: Unit, sup: Optional[Unit], sub: Optional[Unit],
               ctx: ParseContext) -> tuple[ParseContext, Optional[float],
                                           Optional[float], float]:
    """(context, shift_up, shift_down, worst residual) for the best-fitting style."""
    best = None
    for cand in _candidate_styles(ctx):
        up, down = predict_shifts(base, sup, sub, cand)
        worst = 0.0
        if sup is not None and up is not None:
            worst = max(worst, abs((sup.baseline - base.baseline) - up))
        if sub is not None and down is not None:
            worst = max(worst, abs((base.baseline - sub.baseline) - down))
        if best is None or worst < best[3] - 1e-9:
            best = (cand, up, down, worst)
    assert best is not None
    return best


def _build(base: Unit, sup: Optional[Unit], sub: Optional[Unit],
           ctx: ParseContext) -> Unit:
    fitted, pred_up, pred_down, _ = _fit_style(base, sup, sub, ctx)
    ctx = fitted
    ev: dict[str, Any] = {
        "base_is_char": base.is_char,
        "style": ctx.style.name,
        "style_fit": ctx.style.name,
        "font_size_base_pt": round(base.size, 4),
        "script_size_pt": round(ctx.size_of(ctx.style.sup_style()), 4),
    }
    conf = 1.0
    if sup is not None:
        measured = sup.baseline - base.baseline
        ev["superscript_shift_pt"] = round(measured, 5)
        ev["expected_superscript_shift_pt"] = round(pred_up, 5)
        ev["superscript_residual_pt"] = round(measured - pred_up, 5)
        ev["superscript_shift_em"] = round(measured / base.size, 4)
        ev["font_size_superscript_pt"] = round(sup.size, 4)
        ev["font_ratio_superscript"] = round(sup.size / base.size, 4)
        dx = sup.x0 - base.x1
        ev["superscript_dx_pt"] = round(dx, 5)
        ev["expected_superscript_dx_pt"] = round(base.italic, 5)
        ev["italic_correction_pt"] = round(base.italic, 5)
        conf = min(conf, _score(measured - pred_up, ctx))
    if sub is not None:
        measured = base.baseline - sub.baseline
        ev["subscript_shift_pt"] = round(measured, 5)
        ev["expected_subscript_shift_pt"] = round(pred_down, 5)
        ev["subscript_residual_pt"] = round(measured - pred_down, 5)
        ev["subscript_shift_em"] = round(measured / base.size, 4)
        ev["font_size_subscript_pt"] = round(sub.size, 4)
        ev["font_ratio_subscript"] = round(sub.size / base.size, 4)
        ev["subscript_dx_pt"] = round(sub.x0 - base.x1, 5)
        conf = min(conf, _score(measured - pred_down, ctx))

    parts = [u for u in (base, sup, sub) if u is not None]
    gids = sorted({g for u in parts for g in u.glyph_ids})
    rids = sorted({r for u in parts for r in u.rule_ids})
    box = BBox.union([u.bbox for u in parts])

    if sup is not None and sub is not None:
        node: MathNode = SubSup(children=[base.node, sub.node, sup.node])
        rel = "subsuperscript"
    elif sup is not None:
        node = Superscript(children=[base.node, sup.node])
        rel = "superscript"
    else:
        node = Subscript(children=[base.node, sub.node])
        rel = "subscript"
    node.prov = Provenance(gids, rids, box, conf, ev, rel)
    ctx.trace.add(Explanation(
        relationship=rel, node_id=node.node_id,
        parts={"base": base.node.node_id,
               "superscript": sup.node.node_id if sup else None,
               "subscript": sub.node.node_id if sub else None},
        confidence=conf, evidence=ev))
    # How far the finished atom reaches.  clean_box hpacks the script *before* it drops
    # the italic kern (tex.web 720-721), so the kern node goes but its contribution to
    # the width stays -- a subscript ending in cmmi's "Y" is 1.9 pt wider at 8 pt than
    # its ink.  \scriptspace is then added to each script box.  Miss either and the next
    # atom looks displaced, and the parser reports a space the author never asked for.
    reach = base.x1 + (base.trail if sub is None else 0.0)
    for script in (sup, sub):
        if script is not None:
            reach = max(reach, script.x1 + script.trail + ctx.script_space)
    return Unit.composite(node, base.baseline, box, base.size, gids, rids,
                          italic=base.italic, lead=base.lead,
                          trail=max(0.0, reach - box.x1), atom=base.atom)


def _score(residual: float, ctx: ParseContext) -> float:
    """Confidence from an Appendix G residual, in points."""
    tol = max(0.02, 0.002 * ctx.text_size)
    a = abs(residual)
    if a <= tol:
        return 0.999
    if a <= 10 * tol:
        return 0.99 - 0.2 * (a - tol) / (9 * tol)
    return max(0.2, 0.75 - a / ctx.text_size)
