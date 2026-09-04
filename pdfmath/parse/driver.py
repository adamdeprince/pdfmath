"""The recursive descent that turns positioned primitives into a math tree.

The order of work follows the structure of TeX's own ``mlist_to_hlist``, run backwards.

1. **Merge** the pieces of built-up delimiters and radicals back into single symbols.
2. **Claim regions.**  Fraction bars and radicals are *anchors*: each one owns a region
   of the page, and those regions nest.  We repeatedly take the anchor with the largest
   claim -- the outermost -- collapse its region into one unit by recursing into it, and
   continue.  Maximal-by-inclusion is the right rule here because TeX's fraction bar is
   exactly as wide as the wider of its parts, so a nested bar is always strictly inside
   its parent's span.
3. **Fold limits** onto large operators, undoing the axis centring so that a lone
   integral still tells us where the line's baseline is.
4. **Fold accents**, which sit over their nucleus rather than after it.
5. **Pair fences**, recursing into the body -- this is where a ``pmatrix`` gets its rows.
6. **Split rows** if what remains occupies more than one line.
7. **Fold scripts**, inverting rule 18.
8. **Emit the row**, classifying leaves and measuring the inter-atom glue.

Nothing is discarded at any stage.  A primitive that no rule claims arrives at step 8 and
becomes a leaf -- an :class:`Unknown` if we cannot even name it.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional, Sequence

from ..extraction.model import Glyph, PageExtract, Rule
from ..fonts.mathparams import Style
from ..fonts.symbols import AtomClass, Role
from ..geometry.bbox import BBox
from ..tree.nodes import (Fraction, MathNode, Overline, Provenance, Radical, Row,
                          Underline)
from . import (accents, axis, delimiters, fractions, matrices, operators,
               radicals, rows, scripts)
from .style import numerator_style_of, style_for_size, style_from_rule_thickness
from .context import Explanation, ParseContext, Trace, infer_math_sizes
from .units import (FRACTION_BAR, OVERLINE, UNDERLINE, UNUSED, GlyphRun, Unit,
                    merge_runs)


# --------------------------------------------------------------------------- helpers

def _row_baseline(units: Sequence[Unit], ctx: ParseContext) -> float:
    """The baseline shared by the widest run of full-size material.

    Large operators have already had their axis centring undone by
    ``operators.normalise_axis_centring``, so every unit's baseline is comparable here.
    """
    if not units:
        return 0.0
    max_size = max(u.size for u in units)
    cands = [u for u in units if u.size >= max_size - ctx.eps] or list(units)
    entries = sorted(((u.baseline, max(u.width, 0.05)) for u in cands),
                     key=lambda t: t[0])
    groups: list[list[tuple[float, float]]] = [[entries[0]]]
    for e in entries[1:]:
        if e[0] - groups[-1][-1][0] <= ctx.baseline_tol:
            groups[-1].append(e)
        else:
            groups.append([e])
    best = max(groups, key=lambda g: sum(w for _, w in g))
    return sum(b * w for b, w in best) / sum(w for _, w in best)


def _leaf_units(runs: Iterable[GlyphRun], ctx: ParseContext) -> list[Unit]:
    return [Unit.from_run(r, rows.leaf_for(r, ctx)) for r in runs]


# ------------------------------------------------------------------------- anchoring

class _Anchor:
    """A fraction bar or a radical, with the material it claims."""

    def __init__(self, kind: str, rule: Optional[Rule], surd: Optional[GlyphRun],
                 overbar: Optional[Rule], claim_runs: list[GlyphRun],
                 claim_rules: list[Rule], extra: dict[str, Any]):
        self.kind = kind
        self.rule = rule
        self.surd = surd
        self.overbar = overbar
        self.claim_runs = claim_runs
        self.claim_rules = claim_rules
        self.extra = extra

    @property
    def size(self) -> int:
        return len(self.claim_runs) + len(self.claim_rules)

    @property
    def box(self) -> Optional[BBox]:
        boxes = [r.bbox for r in self.claim_runs] + [r.bbox for r in self.claim_rules]
        if self.rule is not None:
            boxes.append(self.rule.bbox)
        if self.surd is not None:
            boxes.append(self.surd.bbox)
        if self.overbar is not None:
            boxes.append(self.overbar.bbox)
        return BBox.union(boxes)


def _find_anchors(runs: list[GlyphRun], rls: list[Rule],
                  ctx: ParseContext) -> list[_Anchor]:
    anchors: list[_Anchor] = []
    used_overbars: set[int] = set()

    for run in runs:
        if not radicals.is_surd(run):
            continue
        ob = radicals.find_overbar(run, rls, ctx)
        if ob is None:
            continue
        used_overbars.add(ob.id)
        radicand, inner_rules, index = radicals.claim(run, ob, runs, rls, ctx)
        anchors.append(_Anchor("radical", None, run, ob,
                               radicand + index, inner_rules,
                               {"index": index, "radicand": radicand}))

    for r in rls:
        if r.id in used_overbars or not r.is_horizontal:
            continue
        cls = fractions.classify_rule(r, runs, rls, ctx)
        num_r, den_r, num_l, den_l = fractions.claim(r, runs, rls, ctx)
        anchors.append(_Anchor(cls.kind, r, None, None,
                               num_r + den_r, num_l + den_l,
                               {"classified": cls, "num_runs": num_r,
                                "den_runs": den_r, "num_rules": num_l,
                                "den_rules": den_l}))
    return anchors


def _build_units(runs: list[GlyphRun], rls: list[Rule], ctx: ParseContext) -> list[Unit]:
    """Collapse anchored regions into composite units, outermost first."""
    remaining_runs = list(runs)
    remaining_rules = list(rls)
    units: list[Unit] = []

    while True:
        anchors = _find_anchors(remaining_runs, remaining_rules, ctx)
        anchors = [a for a in anchors if a.kind not in (UNUSED, "unclassified")]
        if not anchors:
            break
        # Maximal by inclusion: the outermost structure claims the most material.
        anchors.sort(key=lambda a: (a.size, a.box.area if a.box else 0.0), reverse=True)
        a = anchors[0]
        unit = _collapse(a, ctx)
        if unit is None:
            break
        units.append(unit)
        claimed_run_ids = {id(r) for r in a.claim_runs}
        if a.surd is not None:
            claimed_run_ids.add(id(a.surd))
        claimed_rule_ids = {r.id for r in a.claim_rules}
        if a.rule is not None:
            claimed_rule_ids.add(a.rule.id)
        if a.overbar is not None:
            claimed_rule_ids.add(a.overbar.id)
        remaining_runs = [r for r in remaining_runs if id(r) not in claimed_run_ids]
        remaining_rules = [r for r in remaining_rules if r.id not in claimed_rule_ids]

    units.extend(_leaf_units(remaining_runs, ctx))
    for r in remaining_rules:
        units.append(_orphan_rule_unit(r, ctx))
    units = axis.normalise(units, ctx)
    units.sort(key=lambda u: (u.x0, -u.baseline))
    return units


def _orphan_rule_unit(r: Rule, ctx: ParseContext) -> Unit:
    """A rule nothing claimed.  Kept as an Unknown rather than dropped."""
    from ..tree.nodes import Unknown
    thick = r.thickness > 4 * ctx.rule_thickness
    node = Unknown(text="", glyph="rule",
                   reason=("filled box, too thick to be a mathematical rule"
                           if thick else
                           "horizontal rule with no material above or below it"))
    node.prov = Provenance([], [r.id], r.bbox, 0.3,
                           {"thickness_pt": round(r.thickness, 5),
                            "width_pt": round(r.width, 5),
                            "expected_rule_thickness_pt": round(ctx.rule_thickness, 5),
                            "orientation": "horizontal" if r.is_horizontal
                                           else ("vertical" if r.is_vertical else "other")},
                           "orphan-rule")
    return Unit.composite(node, r.y_center, r.bbox, ctx.size, [], [r.id])


def _collapse(a: _Anchor, ctx: ParseContext) -> Optional[Unit]:
    if a.kind == "radical":
        return _build_radical(a, ctx)
    if a.kind == FRACTION_BAR:
        return _build_fraction(a, ctx)
    if a.kind in (OVERLINE, UNDERLINE):
        return _build_line_over_under(a, ctx)
    return None


def _build_fraction(a: _Anchor, ctx: ParseContext) -> Optional[Unit]:
    r = a.rule
    assert r is not None
    num_runs, den_runs = a.extra["num_runs"], a.extra["den_runs"]
    num_rules, den_rules = a.extra["num_rules"], a.extra["den_rules"]
    if not (num_runs or num_rules) or not (den_runs or den_rules):
        return None

    # The style is recoverable, and must be: a fraction nested inside a superscript is
    # set two styles down from the enclosing context, so using ``ctx`` directly would
    # apply the wrong num1/denom1 and the wrong script sizes to everything inside it.
    content_size = max((g.head.size for g in num_runs + den_runs), default=ctx.size)
    own = style_from_rule_thickness(r.thickness, ctx.text_size, prefer=ctx.style)
    by_content = numerator_style_of(content_size, ctx.text_size)
    if not own.is_display and by_content is not Style.DISPLAY:
        own = by_content if by_content != Style.TEXT or own == Style.TEXT else own
    fctx = ctx._with(own)
    nctx, dctx = fctx.numerator(), fctx.denominator()
    num_node, num_units = _parse_group(num_runs, num_rules, nctx)
    den_node, den_units = _parse_group(den_runs, den_rules, dctx)
    num_baseline = _row_baseline(num_units, nctx) if num_units else None
    den_baseline = _row_baseline(den_units, dctx) if den_units else None

    ev = dict(a.extra["classified"].evidence)
    ev.update(fractions.verify(r, num_baseline, den_baseline, fctx))
    ev["inferred_style"] = own.name
    ev["numerator_font_size_pt"] = round(max((u.size for u in num_units), default=0), 4)
    ev["denominator_font_size_pt"] = round(max((u.size for u in den_units), default=0), 4)
    ev["numerator_at_text_size"] = abs(ev["numerator_font_size_pt"] - ctx.text_size) < 0.05
    conf = fractions.confidence_from(ev, fctx)

    node = Fraction(children=[num_node, den_node], line_thickness=r.thickness)
    gids = sorted({g for u in num_units + den_units for g in u.glyph_ids})
    rids = sorted({r.id} | {i for u in num_units + den_units for i in u.rule_ids})
    box = BBox.union([r.bbox] + [u.bbox for u in num_units + den_units])
    node.prov = Provenance(gids, rids, box, conf, ev, "fraction")
    ctx.trace.add(Explanation("fraction", node.node_id,
                              {"numerator": num_node.node_id,
                               "denominator": den_node.node_id, "rule": r.id},
                              conf, ev))
    baseline = r.y_center - fctx.params.axis_height
    # A fraction is an Inner atom (TeXbook, chapter 17), which is why a relation after
    # one takes a thick space rather than none.
    return Unit.composite(node, baseline, box, fctx.size, gids, rids,
                          lead=ctx.null_delimiter_space,
                          trail=ctx.null_delimiter_space, atom=AtomClass.INNER)


def _build_radical(a: _Anchor, ctx: ParseContext) -> Optional[Unit]:
    surd, ob = a.surd, a.overbar
    assert surd is not None and ob is not None
    radicand_runs = a.extra["radicand"]
    index_runs = a.extra["index"]
    if not radicand_runs and not a.claim_rules:
        return None

    own = style_for_size(surd.head.size, ctx.text_size, prefer=ctx.style,
                         math_sizes=ctx.math_sizes)
    rctx = ctx._with(own).cramped()
    rad_node, rad_units = _parse_group(radicand_runs, a.claim_rules, rctx)
    rad_box = BBox.union([u.bbox for u in rad_units]) if rad_units else None
    rad_baseline = _row_baseline(rad_units, rctx) if rad_units else None
    ev = radicals.verify(surd, ob, rad_box, rad_baseline, ctx._with(own))
    ev["inferred_style"] = own.name
    conf = radicals.confidence_from(ev, ctx)

    children: list[MathNode] = [rad_node]
    if index_runs:
        ictx = ctx._with(Style.SCRIPTSCRIPT)
        idx_node, idx_units = _parse_group(index_runs, [], ictx)
        children.append(idx_node)
        ev["index_font_size_pt"] = round(max((u.size for u in idx_units), default=0), 4)
    node = Radical(children=children)

    gids = sorted(set(surd.ids) | {g for u in rad_units for g in u.glyph_ids}
                  | {g for r in index_runs for g in r.ids})
    rids = sorted({ob.id} | {i for u in rad_units for i in u.rule_ids})
    box = BBox.union([surd.bbox, ob.bbox] + [u.bbox for u in rad_units]
                     + [r.bbox for r in index_runs])
    node.prov = Provenance(gids, rids, box, conf, ev, "radical")
    ctx.trace.add(Explanation("radical", node.node_id,
                              {"radicand": rad_node.node_id, "surd_glyphs": surd.ids,
                               "overbar_rule": ob.id}, conf, ev))
    baseline = rad_baseline if rad_baseline is not None else box.y0
    # \root sets the index after a \mkern5mu, so the box starts 5 mu to the left of
    # the index's ink.  Without that, the gap to whatever precedes the radical measures
    # 5 mu too wide and looks like a space the author asked for.
    lead = (5.0 / 18.0 * (ctx.params.quad or ctx.size)) if index_runs else 0.0
    return Unit.composite(node, baseline, box, surd.head.size, gids, rids,
                          atom=AtomClass.ORD, lead=lead)


def _build_line_over_under(a: _Anchor, ctx: ParseContext) -> Optional[Unit]:
    r = a.rule
    assert r is not None
    runs = a.extra["den_runs"] if a.kind == OVERLINE else a.extra["num_runs"]
    rls = a.extra["den_rules"] if a.kind == OVERLINE else a.extra["num_rules"]
    if not runs and not rls:
        return None
    own = style_from_rule_thickness(r.thickness, ctx.text_size, prefer=ctx.style)
    bctx = ctx._with(own)
    bctx = bctx.cramped() if a.kind == OVERLINE else bctx
    node_inner, inner_units = _parse_group(runs, rls, bctx)
    inner_box = BBox.union([u.bbox for u in inner_units])
    baseline = _row_baseline(inner_units, bctx)

    theta = bctx.rule_thickness
    ev = dict(a.extra["classified"].evidence)
    ev["inferred_style"] = own.name
    if a.kind == OVERLINE:
        # Rule 9: the bar clears the box by 3*theta and is theta thick.
        expected = 3 * theta
        measured = r.bbox.y0 - inner_box.y1
        node: MathNode = Overline(children=[node_inner])
    else:
        expected = 3 * theta
        measured = inner_box.y0 - r.bbox.y1
        node = Underline(children=[node_inner])
    ev["expected_clearance_pt"] = round(expected, 5)
    ev["measured_clearance_pt"] = round(measured, 5)
    ev["clearance_residual_pt"] = round(measured - expected, 5)
    tol = max(0.05, 0.005 * ctx.text_size)
    conf = 0.995 if abs(measured - expected) <= tol else 0.75

    gids = sorted({g for u in inner_units for g in u.glyph_ids})
    rids = sorted({r.id} | {i for u in inner_units for i in u.rule_ids})
    box = BBox.union([r.bbox, inner_box])
    node.prov = Provenance(gids, rids, box, conf, ev, a.kind)
    ctx.trace.add(Explanation(a.kind, node.node_id,
                              {"base": node_inner.node_id, "rule": r.id}, conf, ev))
    return Unit.composite(node, baseline, box, bctx.size, gids, rids,
                          atom=AtomClass.ORD)


# ------------------------------------------------------------------------- top level

def _parse_group(runs: Sequence[GlyphRun], rls: Sequence[Rule],
                 ctx: ParseContext) -> tuple[MathNode, list[Unit]]:
    """Parse a claimed sub-region; returns the node and the units it was built from."""
    units = _build_units(list(runs), list(rls), ctx)
    return parse_units(units, ctx), units


def parse_units(units: list[Unit], ctx: ParseContext,
                inside_fence: bool = False) -> MathNode:
    """Fold a flat list of positioned units into a tree."""
    if not units:
        return Row()
    units = sorted(units, key=lambda u: (u.x0, -u.baseline))
    # Digit runs and upright-roman runs become single tokens before anything else looks
    # at them, so that a script on "10" attaches to the number rather than to its last
    # digit and an accent over "42" covers both digits.
    units = rows.merge_leaves(units, ctx)
    baseline = _row_baseline(units, ctx)

    units = operators.attach(units, ctx, _sub_parse, baseline)
    units = accents.attach(units, ctx)
    units = delimiters.pair(units, ctx, _sub_parse_fenced, baseline)

    # An aligned block *beside* other material is tested first: a \vcenter table puts
    # the enclosing line's baseline between its rows, so splitting all the baselines
    # would make the material next to the table into a row of it.
    block_rows, outside = matrices.aligned_block(units, ctx, baseline)
    if block_rows is not None:
        block = matrices.build(block_rows, ctx, _sub_parse, inside_fence)
        units = sorted(outside + [block], key=lambda u: (u.x0, -u.baseline))
    else:
        lines = matrices.split_rows(units, ctx)
        if len(lines) > 1:
            return matrices.build(lines, ctx, _sub_parse, inside_fence).node

    baseline = _row_baseline(units, ctx)
    units = scripts.attach(units, ctx, _sub_parse, baseline)
    return rows.build(units, ctx)


def _sub_parse(units: list[Unit], ctx: ParseContext) -> MathNode:
    return parse_units(units, ctx, inside_fence=False)


def _sub_parse_fenced(units: list[Unit], ctx: ParseContext) -> MathNode:
    return parse_units(units, ctx, inside_fence=True)


def parse(glyphs: Sequence[Glyph], rls: Sequence[Rule],
          ctx: Optional[ParseContext] = None) -> tuple[MathNode, ParseContext]:
    """Decompile a set of primitives into a math tree.

    The text size is read off the glyphs -- TeX never sets a top-level formula entirely
    in script size, so the largest size present is the document's -- and the style is
    taken from the caller, defaulting to display, which is what a displayed equation is.
    """
    if ctx is None:
        sizes = [g.size for g in glyphs]
        levels = infer_math_sizes(sizes)
        ctx = ParseContext(text_size=levels[0], style=Style.DISPLAY, trace=Trace(),
                           math_sizes=levels)
    elif ctx.math_sizes is None:
        ctx.math_sizes = infer_math_sizes([g.size for g in glyphs])
        ctx._params = None
    runs = merge_runs(list(glyphs), tol=max(0.05, 0.005 * ctx.text_size))
    units = _build_units(runs, list(rls), ctx)
    return parse_units(units, ctx), ctx


def parse_page(extract: PageExtract, region: Optional[BBox] = None,
               ctx: Optional[ParseContext] = None) -> tuple[MathNode, ParseContext]:
    src = extract.in_region(region) if region is not None else extract
    return parse(src.glyphs, src.rules, ctx)
