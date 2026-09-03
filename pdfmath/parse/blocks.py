"""Deciding which material belongs to a two-dimensional structure.

This is the problem MaxTract solved with two global constants, ``H`` and ``V``, and it is
where its matrix recognition failed: a matrix set with little space between rows was read
as a bracketed expression full of spurious scripts.  Replacing the constants with better
constants does not work either, because the quantities genuinely overlap.  In a 10 pt
document a display fraction leaves 4.1 pt between its bar and its numerator, a text-style
fraction leaves 5.7 pt between its bar and a short denominator, an operator with a short
limit leaves up to 6 pt -- and the rows of a ``pmatrix`` are only about 5 pt apart.  No
threshold separates those.

What separates them is *structure*.  Within a single hbox, material is connected: boxes
that sit side by side on a baseline overlap vertically, and where they do not, something
is holding them apart -- a fraction bar, a radical, a large operator with limits.  Those
things are visible.  So we build a graph in which

* two items are joined when their boxes overlap vertically (they are on, or near, one
  baseline), and
* a *bridging* item -- a horizontal rule, or a large operator -- is joined to the nearest
  item above it and the nearest item below it within its own horizontal span, because
  that is precisely the relationship it was drawn to express,

and take the connected component.  A matrix row above has no bridge to the row below and
does not overlap it, so it is excluded; a triply nested fraction is fully connected
through its own bars, so it is included, however far apart its parts are.
"""

from __future__ import annotations

from typing import Any, Callable, Optional, Sequence

from ..fonts.symbols import Role
from ..geometry.bbox import BBox
from .context import ParseContext


def _is_bridge(item: Any) -> bool:
    """Does this item structurally connect material above it to material below it?"""
    sym = getattr(item, "symbol", None)
    if sym is not None:
        return sym.role in (Role.LARGE_OP, Role.RADICAL)
    return getattr(item, "is_horizontal", False)      # a Rule


def _neighbours_of_bridge(bridge: Any, items: Sequence[Any],
                          pad: float) -> list[Any]:
    """The items a bridge holds apart: the nearest above and the nearest below."""
    bb = bridge.bbox
    above = [it for it in items
             if it is not bridge and it.bbox.y0 >= bb.y1 - pad
             and bb.x0 - pad <= it.bbox.cx <= bb.x1 + pad]
    below = [it for it in items
             if it is not bridge and it.bbox.y1 <= bb.y0 + pad
             and bb.x0 - pad <= it.bbox.cx <= bb.x1 + pad]
    out = []
    if above:
        out.append(min(above, key=lambda it: it.bbox.y0))
    if below:
        out.append(max(below, key=lambda it: it.bbox.y1))
    return out


def cohesive_block(candidates: Sequence[Any], seed: Any,
                   ctx: ParseContext) -> list[Any]:
    """The connected component of ``seed`` under vertical cohesion and bridging."""
    if not candidates:
        return []
    tol = 0.5 * ctx.params.x_height
    pad = ctx.x_tol
    n = len(candidates)
    adj: list[set[int]] = [set() for _ in range(n)]

    # Only vertical cohesion matters.  The candidates have already been restricted to
    # the structure's own horizontal span, and *within* that span neighbouring symbols
    # are routinely separated by an inter-atom space of up to 5/18 em, so a horizontal
    # proximity test would cut "x + 1" into three pieces.
    for i in range(n):
        for j in range(i + 1, n):
            if candidates[i].bbox.overlap_y(candidates[j].bbox) > -tol:
                adj[i].add(j)
                adj[j].add(i)

    index = {id(c): i for i, c in enumerate(candidates)}
    for i, c in enumerate(candidates):
        if not _is_bridge(c):
            continue
        for nb in _neighbours_of_bridge(c, candidates, pad):
            j = index.get(id(nb))
            if j is not None:
                adj[i].add(j)
                adj[j].add(i)

    start = index.get(id(seed))
    if start is None:
        return []
    seen = {start}
    stack = [start]
    while stack:
        k = stack.pop()
        for m in adj[k]:
            if m not in seen:
                seen.add(m)
                stack.append(m)
    return [candidates[i] for i in sorted(seen)]


def block_above(edge: float, candidates: Sequence[Any],
                ctx: ParseContext) -> list[Any]:
    """The cohesive block of material sitting immediately above ``edge``."""
    if not candidates:
        return []
    seed = min(candidates, key=lambda it: it.bbox.y0)
    return cohesive_block(candidates, seed, ctx)


def block_below(edge: float, candidates: Sequence[Any],
                ctx: ParseContext) -> list[Any]:
    """The cohesive block of material sitting immediately below ``edge``."""
    if not candidates:
        return []
    seed = max(candidates, key=lambda it: it.bbox.y1)
    return cohesive_block(candidates, seed, ctx)
