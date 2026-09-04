"""Math accents -- the inversion of Appendix G rule 12 (tex.web 738).

``\\hat{x}`` is not a superscript, and telling them apart was one of MaxTract's recorded
failures: an accent that sits high and slightly right looks exactly like a script to a
geometric rule.  TeX's own construction distinguishes them without ambiguity.

``make_math_accent`` centres the accent glyph over the nucleus and puts its reference
point at

    baseline(accent) = baseline(nucleus) + h(nucleus) - min(h(nucleus), x_height)

so for any nucleus no taller than the x-height -- every lowercase letter -- the accent is
drawn *on the nucleus's own baseline*, and it is the glyph's own height that lifts it
into place.  A superscript, by contrast, is shifted up by at least ``sup2`` and starts to
the right of the nucleus's full width.  The two are never close.
"""

from __future__ import annotations

from typing import Any, Optional

from ..fonts.symbols import AtomClass, Role
from ..geometry.bbox import BBox
from ..tree.nodes import Accent, Provenance
from .context import Explanation, ParseContext
from .units import Unit

#: Glyph names that TeX uses as math accents, by ``\\mathaccent`` class.
ACCENT_GLYPHS = {
    "circumflex": ("^", "hat"),
    "tilde": ("~", "tilde"),
    "macron": ("¯", "bar"),
    "breve": ("˘", "breve"),
    "dotaccent": ("˙", "dot"),
    "dieresis": ("¨", "ddot"),
    "ring": ("˚", "mathring"),
    "acute": ("´", "acute"),
    "grave": ("`", "grave"),
    "caron": ("ˇ", "check"),
    "hungarumlaut": ("˝", "Hungarian"),
    "vector": ("⃗", "vec"),
    "tie": ("͡", "tie"),
    "hat": ("^", "widehat"),
    "widehat": ("^", "widehat"),
}


def is_accent_glyph(unit: Unit) -> bool:
    s = unit.symbol
    if s is None:
        return False
    if s.role == Role.ACCENT:
        return True
    return s.glyph in ACCENT_GLYPHS


def attach(units: list[Unit], ctx: ParseContext) -> list[Unit]:
    """Fold accent glyphs onto the nucleus they sit over.

    Driven from the accent rather than from the nucleus, because ``make_math_accent``
    centres the accent over the nucleus: a wide accent such as ``\\vec`` starts to the
    *left* of its base, so scanning forward from the base would never find it.
    """
    consumed: set[int] = set()
    built: dict[int, Unit] = {}
    for j, acc in enumerate(units):
        if not is_accent_glyph(acc) or j in consumed:
            continue
        i = _find_nucleus(units, j, acc, ctx, consumed)
        if i is None:
            continue
        consumed.add(j)
        built[i] = _build(units[i], acc, ctx)
    return [built.get(i, u) for i, u in enumerate(units) if i not in consumed]


def _find_nucleus(units: list[Unit], j: int, acc: Unit, ctx: ParseContext,
                  consumed: set[int]) -> Optional[int]:
    """The unit this accent sits over, chosen by how well rule 12 explains it."""
    best, best_err = None, float("inf")
    x_height = ctx.params.x_height
    tol = max(0.1, 0.02 * ctx.text_size)
    for i, base in enumerate(units):
        if i == j or i in consumed or is_accent_glyph(base):
            continue
        if abs(base.size - acc.size) > ctx.eps:
            continue
        if base.bbox.overlap_x(acc.bbox) <= 0:
            continue
        if acc.baseline < base.baseline - ctx.baseline_tol:
            continue
        delta = min(base.height, x_height)
        want_baseline = base.baseline + base.height - delta
        want_x0 = base.x0 + 0.5 * (base.width - acc.width)
        err = abs(acc.baseline - want_baseline) + 0.5 * abs(acc.x0 - want_x0)
        if err < best_err:
            best, best_err = i, err
    if best is None or best_err > 3 * tol + 0.5 * ctx.size:
        return None
    return best


def _build(base: Unit, acc: Unit, ctx: ParseContext) -> Unit:
    x_height = ctx.params.x_height
    delta = min(base.height, x_height)
    predicted_baseline = base.baseline + base.height - delta
    predicted_x0 = base.x0 + 0.5 * (base.width - acc.width)
    ev: dict[str, Any] = {
        "accent_glyph": acc.symbol.glyph if acc.symbol else None,
        "baseline_pt": round(acc.baseline, 5),
        "expected_baseline_pt": round(predicted_baseline, 5),
        "baseline_residual_pt": round(acc.baseline - predicted_baseline, 5),
        "centre_offset_pt": round(acc.x0 - predicted_x0, 5),
        "skew_pt": round(acc.x0 - predicted_x0, 5),
        "x_height_pt": round(x_height, 5),
        "nucleus_height_pt": round(base.height, 5),
        "same_font_size": abs(acc.size - base.size) <= ctx.eps,
    }
    residual = abs(acc.baseline - predicted_baseline)
    tol = max(0.05, 0.005 * ctx.text_size)
    conf = 0.999 if residual <= tol else max(0.4, 0.95 - residual / ctx.text_size)

    name = acc.symbol.glyph if acc.symbol else ""
    uni, tex = ACCENT_GLYPHS.get(name or "", (acc.node.text if hasattr(acc.node, "text")
                                              else "", name))
    if acc.symbol and acc.symbol.role == Role.ACCENT and acc.symbol.size_rank:
        uni = acc.symbol.unicode or uni
    node = Accent(children=[base.node], accent=uni, accent_glyph=name,
                  stretchy=bool(acc.symbol and acc.symbol.size_rank))
    gids = sorted(set(base.glyph_ids) | set(acc.glyph_ids))
    rids = sorted(set(base.rule_ids) | set(acc.rule_ids))
    box = base.bbox | acc.bbox
    node.prov = Provenance(gids, rids, box, conf, ev, "accent")
    ctx.trace.add(Explanation("accent", node.node_id,
                              {"base": base.node.node_id, "accent": tex},
                              conf, ev))
    # make_math_accent leaves the nucleus's class alone.
    return Unit.composite(node, base.baseline, box, base.size, gids, rids,
                          italic=base.italic, x0=base.x0, x1=base.x1,
                          lead=base.lead, trail=base.trail, atom=base.atom)
