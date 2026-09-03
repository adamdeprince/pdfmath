"""Delimiter pairing, including TeX's built-up ``\\left`` / ``\\right`` fences.

cmex represents a tall bracket in two different ways.  Up to ``\\Bigg`` there is a single
glyph per size (``parenleftbig`` ... ``parenleftBigg``), reached through the TFM charlist
chain from cmr's ``(``.  Beyond that TeX assembles a column of pieces -- ``parenlefttp``,
one or more ``parenleftex``, ``parenleftbt`` -- each drawn as its own ``TJ``.  The
merging of those pieces happens in units.merge_runs; what is left here is deciding which
opener goes with which closer.

Two facts make this more reliable than the orientation-based pairing that MaxTract
reported as a weakness:

* ``var_delimiter`` centres a ``\\left``/``\\right`` delimiter on the maths axis, which an
  ordinary ``(`` typed as a character is not.  Axis centring therefore identifies a
  genuine fence, and its measured centre gives an independent reading of the axis.
* both members of a pair are produced by the same call to ``var_delimiter`` with the same
  target height, so they have the *same size rank*.  Matching on rank as well as nesting
  keeps a stray closing bracket from capturing an opener several sizes away.

Neutral fences (``|``, ``\\|``) are the hard case Baker could not solve, and we do not
pretend otherwise: they are paired only when a region contains exactly two of the same
kind and nothing else claims them, and the resulting node records a lower confidence.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from ..fonts.symbols import NEUTRAL_DELIMITERS, Role
from ..geometry.bbox import BBox
from ..tree.nodes import Delimited, MathNode, Provenance, Row
from .context import Explanation, ParseContext
from .units import Unit

ParseGroup = Callable[[list[Unit], ParseContext], MathNode]


def _is_open(u: Unit) -> bool:
    s = u.symbol
    if s is None:
        return False
    return s.role is Role.DELIM_OPEN or (s.role is Role.DELIM_PIECE and s.side == "left")

def _is_close(u: Unit) -> bool:
    s = u.symbol
    if s is None:
        return False
    return s.role is Role.DELIM_CLOSE or (s.role is Role.DELIM_PIECE and s.side == "right")

def _is_neutral(u: Unit) -> bool:
    s = u.symbol
    return s is not None and s.base in NEUTRAL_DELIMITERS and s.glyph not in ("slash",)


def pair(units: list[Unit], ctx: ParseContext, parse_group: ParseGroup,
         row_baseline: float) -> list[Unit]:
    """Fold matching fences and their contents into :class:`Delimited` units."""
    out: list[Unit] = []
    i = 0
    n = len(units)
    while i < n:
        u = units[i]
        if _is_open(u):
            j = _match(units, i, ctx)
            if j is not None:
                inner = units[i + 1:j]
                out.append(_build(u, units[j], inner, ctx, parse_group, row_baseline))
                i = j + 1
                continue
        elif _is_neutral(u):
            j = _match_neutral(units, i, ctx)
            if j is not None:
                inner = units[i + 1:j]
                out.append(_build(u, units[j], inner, ctx, parse_group, row_baseline,
                                  neutral=True))
                i = j + 1
                continue
        out.append(u)
        i += 1
    return out


def _match(units: list[Unit], i: int, ctx: ParseContext) -> Optional[int]:
    depth = 0
    for j in range(i, len(units)):
        u = units[j]
        if _is_open(u):
            depth += 1
        elif _is_close(u):
            depth -= 1
            if depth == 0:
                return j if j > i + 0 else None
    return None


def _match_neutral(units: list[Unit], i: int, ctx: ParseContext) -> Optional[int]:
    base = units[i].symbol.base if units[i].symbol else None
    same = [j for j in range(i + 1, len(units))
            if _is_neutral(units[j]) and units[j].symbol
            and units[j].symbol.base == base]
    if len(same) != 1:
        return None                 # ambiguous; leave both as ordinary operators
    j = same[0]
    return j if j > i + 1 else None


def _build(op: Unit, cl: Unit, inner: list[Unit], ctx: ParseContext,
           parse_group: ParseGroup, row_baseline: float,
           neutral: bool = False) -> Unit:
    body = parse_group(inner, ctx.same()) if inner else Row()
    # The fence was axis-centred on the baseline of *its own* list, which is not the
    # enclosing row's when the group is itself a script.  parse.axis has already put the
    # unit back on that baseline, so read it from there rather than from the caller.
    baseline = op.baseline if op.axis_normalised else row_baseline
    axis = baseline + ctx.params.axis_height
    ev: dict[str, Any] = {
        "open_glyph": op.symbol.glyph if op.symbol else None,
        "close_glyph": cl.symbol.glyph if cl.symbol else None,
        "open_size_rank": op.symbol.size_rank if op.symbol else 0,
        "close_size_rank": cl.symbol.size_rank if cl.symbol else 0,
        "open_pieces": len(op.run.glyphs) if op.run else 1,
        "close_pieces": len(cl.run.glyphs) if cl.run else 1,
        "open_centre_offset_from_axis_pt": round(op.bbox.cy - axis, 5),
        "close_centre_offset_from_axis_pt": round(cl.bbox.cy - axis, 5),
        "axis_height_pt": round(ctx.params.axis_height, 5),
        "neutral_pairing": neutral,
    }
    ranks_match = ev["open_size_rank"] == ev["close_size_rank"]
    ev["size_ranks_match"] = ranks_match
    tol = max(0.1, 0.02 * ctx.text_size)
    axis_centred = (abs(ev["open_centre_offset_from_axis_pt"]) <= tol
                    and abs(ev["close_centre_offset_from_axis_pt"]) <= tol)
    ev["axis_centred"] = axis_centred
    ev["stretched_by_left_right"] = axis_centred and (ev["open_size_rank"] > 0
                                                      or ev["open_pieces"] > 1)
    conf = 0.999 if ranks_match else 0.85
    if neutral:
        conf = min(conf, 0.7)

    node = Delimited(children=[body],
                     open=op.symbol.unicode if op.symbol else "",
                     close=cl.symbol.unicode if cl.symbol else "",
                     stretchy=bool(ev["stretched_by_left_right"]),
                     open_glyph=ev["open_glyph"], close_glyph=ev["close_glyph"])
    gids = sorted(set(op.glyph_ids) | set(cl.glyph_ids)
                  | {g for u in inner for g in u.glyph_ids})
    rids = sorted(set(op.rule_ids) | set(cl.rule_ids)
                  | {r for u in inner for r in u.rule_ids})
    box = BBox.union([op.bbox, cl.bbox] + [u.bbox for u in inner])
    node.prov = Provenance(gids, rids, box, conf, ev, "delimited")
    ctx.trace.add(Explanation("delimited", node.node_id,
                              {"open": op.node.node_id, "close": cl.node.node_id},
                              conf, ev))
    return Unit.composite(node, baseline, box, max(op.size, cl.size), gids, rids)
