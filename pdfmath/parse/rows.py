"""Horizontal rows: leaf classification, run merging, and spacing evidence.

By the time a row is built, every two-dimensional structure has been folded away and what
is left is a sequence of symbols on one baseline.  Three jobs remain.

**Classify each leaf.**  Digits become ``mn``, letters and letter-like symbols ``mi``,
everything else ``mo``.  Note what is deliberately *not* attempted: ``f(x)`` is reported
as ``f``, ``(``, ``x``, ``)``.  Whether that is function application or multiplication is
not encoded anywhere in the PDF, and inventing an answer would be exactly the kind of
fabricated semantics this project is meant to avoid.

**Merge runs.**  Adjacent digits form one number, as MathML expects.  Adjacent *upright
roman* letters in a maths font form a function name -- in maths mode a lone variable comes
from cmmi, so a run of two or more cmr letters means the author wrote ``\\sin``, ``\\log``
or ``\\operatorname``.  That is a TeX-specific inference and it is free.

**Record the spacing.**  The gap between each pair of neighbours is measured and compared
against TeX's inter-atom glue table (see spacing.py).  It is attached as evidence rather
than used to override the glyph-name classification, so that ``pdfmath explain`` can show
two independent derivations agreeing -- or disagreeing, which is the interesting case.
"""

from __future__ import annotations

from typing import Any, Optional

from ..fonts.symbols import AtomClass, Role
from ..geometry.bbox import BBox
from ..tree.nodes import (Identifier, LargeOperator, Leaf, MathNode, Number,
                          Operator, Provenance, Row, Space, Text, Unknown)
from . import spacing
from .context import ParseContext
from .units import GlyphRun, Unit

#: Ord symbols that Presentation MathML conventionally marks up as identifiers.
LETTERLIKE = set("∞∂ℵℓ℘∅ℜℑ⊤⊥ıȷ") | set(
    "αβγδεϵζηθϑικλμνξπϖρϱσςτυϕφχψωΓΔΘΛΞΠΣΥΦΨΩ")


def leaf_for(run: GlyphRun, ctx: ParseContext) -> Leaf:
    """Build the leaf node for a single symbol."""
    g = run.head
    sym = run.symbol
    text = g.unicode
    variant = g.font.mathvariant
    if g.font.has_script_capitals and sym.glyph and len(sym.glyph) == 1 \
            and sym.glyph.isalpha() and sym.glyph.isupper():
        variant = "script"

    common = dict(text=text, glyph=sym.glyph, font=g.font.base_name,
                  mathvariant=variant, atom=sym.atom.short)
    if sym.role == Role.LARGE_OP:
        node: Leaf = LargeOperator(display=bool(sym.size_rank), **common)
    elif not text:
        node = Unknown(reason=f"no Unicode for {g.font.base_name} code {g.char_code}",
                       **common)
    elif text.isdigit():
        node = Number(**common)
    elif sym.atom in (AtomClass.BIN, AtomClass.REL, AtomClass.OPEN,
                      AtomClass.CLOSE, AtomClass.PUNCT):
        node = Operator(**common)
    elif text.isalpha() or text in LETTERLIKE:
        node = Identifier(**common)
    else:
        node = Operator(**common)

    node.prov = Provenance(run.ids, [], run.bbox, 1.0, {
        "glyph": sym.glyph,
        "font": g.font.base_name,
        "char_code": g.char_code,
        "unicode_source": g.unicode_source,
        "atom_class": sym.atom.short,
        "font_size_pt": round(g.size, 4),
    }, "leaf")
    return node


def merge_leaves(units: list[Unit], ctx: ParseContext) -> list[Unit]:
    """Merge digit runs into numbers and upright-roman runs into function names.

    Accent glyphs are set aside first.  ``make_math_accent`` gives the accent box zero
    width and centres it over its nucleus, so in ``\\ddot{42}`` the dieresis is drawn
    *between* the two digits without being between them in the horizontal list.  Left in
    place it would cut the number in half.
    """
    from .accents import is_accent_glyph
    marks = [u for u in units if is_accent_glyph(u)]
    if marks:
        rest = merge_leaves([u for u in units if not is_accent_glyph(u)], ctx)
        return sorted(rest + marks, key=lambda u: (u.x0, -u.baseline))
    out: list[Unit] = []
    i = 0
    while i < len(units):
        u = units[i]
        node = u.node
        if isinstance(node, Number):
            j = i + 1
            group = [u]
            while j < len(units):
                v = units[j]
                if not isinstance(v.node, Number) and not (
                        isinstance(v.node, Operator) and v.node.text == "."
                        and j + 1 < len(units) and isinstance(units[j + 1].node, Number)):
                    break
                if not _adjacent(group[-1], v, ctx):
                    break
                group.append(v)
                j += 1
            if len(group) > 1:
                out.append(_join(group, Number, ctx, "digit-run"))
                i = j
                continue
        elif isinstance(node, Operator) and node.text in (".", "⋅"):
            # \ldots and \cdots are three separate glyphs in the PDF -- plain TeX
            # defines them as three \ldotp / \cdotp atoms -- and MathML wants one
            # token.  Three or more on a baseline, evenly spaced, is an ellipsis.
            j = i + 1
            group = [u]
            while j < len(units) and isinstance(units[j].node, Operator) \
                    and units[j].node.text == node.text \
                    and abs(units[j].baseline - u.baseline) <= ctx.baseline_tol \
                    and units[j].x0 - group[-1].x1 <= 0.45 * ctx.size:
                group.append(units[j])
                j += 1
            if len(group) >= 3:
                out.append(_join_text(group, "…" if node.text == "." else "⋯",
                                      ctx, "ellipsis"))
                i = j
                continue
        elif isinstance(node, Identifier) and _is_upright_roman(u):
            j = i + 1
            group = [u]
            while j < len(units) and _is_upright_roman(units[j]) \
                    and isinstance(units[j].node, Identifier) \
                    and _adjacent(group[-1], units[j], ctx):
                group.append(units[j])
                j += 1
            if len(group) > 1:
                out.append(_join(group, Identifier, ctx, "roman-run"))
                i = j
                continue
        out.append(u)
        i += 1
    return out


def _is_upright_roman(u: Unit) -> bool:
    if u.run is None or len(u.run.glyphs) != 1:
        return False
    g = u.run.head
    return (g.font.encoding in ("OT1", "CMSS", "OT1TT")
            and bool(g.unicode) and g.unicode.isalpha())


def _adjacent(a: Unit, b: Unit, ctx: ParseContext) -> bool:
    """True when nothing but a kern separates two symbols on one baseline."""
    if abs(a.baseline - b.baseline) > ctx.baseline_tol:
        return False
    if abs(a.size - b.size) > ctx.eps:
        return False
    gap = b.x0 - a.x1
    return -0.3 * ctx.size <= gap <= 0.02 * ctx.size


def _join_text(group: list[Unit], text: str, ctx: ParseContext, why: str) -> Unit:
    """Replace a run of glyphs with a single token of different text."""
    first = group[0].node
    node = Operator(text=text, glyph=None, font=getattr(first, "font", None),
                    mathvariant="normal", atom="Inner")
    gids = sorted({g for u in group for g in u.glyph_ids})
    box = BBox.union([u.bbox for u in group])
    node.prov = Provenance(gids, [], box, 0.98,
                           {"merged_from": [getattr(u.node, "text", "") for u in group],
                            "reason": why}, why)
    return Unit.composite(node, group[0].baseline, box, group[0].size, gids, [],
                          x0=group[0].x0, x1=group[-1].x1)


def _join(group: list[Unit], cls, ctx: ParseContext, why: str) -> Unit:
    text = "".join(getattr(u.node, "text", "") for u in group)
    first = group[0].node
    node = cls(text=text, glyph=None, font=getattr(first, "font", None),
               mathvariant=getattr(first, "mathvariant", "normal"),
               atom=getattr(first, "atom", "Ord"))
    gids = sorted({g for u in group for g in u.glyph_ids})
    box = BBox.union([u.bbox for u in group])
    node.prov = Provenance(gids, [], box, 0.99,
                           {"merged_from": [getattr(u.node, "text", "") for u in group],
                            "reason": why}, why)
    # TeX attached any script to the *last* atom of the run -- "10_0" is the atom "1"
    # followed by "0" with a subscript -- so the merged unit inherits the last glyph's
    # box for the purposes of rule 18, while spanning the whole run horizontally.
    last = group[-1]
    unit = Unit.composite(node, last.baseline, box, last.size, gids, [],
                          italic=last.italic, x0=group[0].x0, x1=last.x1)
    unit.height = last.height
    unit.depth = last.depth
    unit.is_char = last.is_char
    unit.trail = last.trail
    return unit


def build(units: list[Unit], ctx: ParseContext) -> MathNode:
    """Assemble a row, recording the inter-atom spacing as evidence."""
    units = sorted(units, key=lambda u: (u.x0, -u.baseline))
    if not units:
        return Row()

    children: list[MathNode] = []
    script_style = ctx.style >= 4
    for k, u in enumerate(units):
        if k:
            prev = units[k - 1]
            # Between the *boxes*: the italic kern after a character nucleus and the
            # \scriptspace after a script box are invisible but real, and a gap measured
            # without them lands between two entries of TeX's glue table.
            gap = u.box_x0 - prev.box_x1
            obs = spacing.observe(gap, ctx)
            left, right = prev.atom, u.atom
            expected = spacing.expected_mu(left, right, script_style)
            ev: dict[str, Any] = {
                "gap_pt": round(obs.gap_pt, 5),
                "ink_gap_pt": round(u.x0 - prev.x1, 5),
                "left_trailing_kern_pt": round(prev.trail, 5),
                "right_leading_space_pt": round(u.lead, 5),
                "gap_mu": round(obs.gap_mu, 3),
                "nearest_tex_space": obs.name,
                "nearest_tex_space_mu": obs.nearest_mu,
                "residual_mu": round(obs.residual_mu, 3),
                "integral_mu": obs.is_integral_mu,
                "author_space": obs.author_space,
                "math_quad_pt": round(obs.quad_pt, 4),
                "left_atom": left.short,
                "right_atom": right.short,
                "expected_mu_from_atom_classes": expected,
                "atom_classes_consistent": (
                    expected is not None and abs(expected - obs.nearest_mu) < 1e-9),
            }
            u.node.prov.evidence.setdefault("spacing_left", ev)
            # A gap that TeX's own glue table does not account for was asked for by the
            # author -- a \\,, a \\quad, an \\hspace.  Those are worth keeping; the
            # automatic glue is not, because a MathML renderer re-inserts it itself.
            if (not ev["atom_classes_consistent"] and obs.gap_pt > 0.02 * ctx.size
                    and obs.nearest_class != spacing.NONE):
                sp = Space(width_em=obs.gap_pt / max(ctx.size, 1e-6))
                # A space is a measurement, not a structural guess: how sure we are
                # that the author asked for it is how cleanly the gap lands on one of
                # TeX's four glue widths.
                sp.prov = Provenance(
                    [], [], None,
                    0.99 if (obs.is_clean or obs.is_integral_mu) else 0.8,
                    dict(ev, reason="gap not explained by TeX inter-atom glue for "
                                    "these atom classes"), "explicit-space")
                children.append(sp)
        children.append(u.node)

    if len(children) == 1:
        return children[0]
    row = Row(children=children)
    row.prov = Provenance(
        sorted({g for u in units for g in u.glyph_ids}),
        sorted({r for u in units for r in u.rule_ids}),
        BBox.union([u.bbox for u in units]), 1.0, {}, "row")
    return row
