"""Matrices, cases and aligned multi-line structures.

Baker's evaluation records two matrix failures, and both come from the same cause: the
row and column separators were global constants ``V`` and ``H``, so a matrix set tightly
enough was read as a bracketed expression full of spurious scripts.  The fix is not a
better constant, it is to stop using one.

Rows are separated by whitespace that TeX derived from ``\\baselineskip`` and the boxes'
own heights, and columns by ``\\arraycolsep`` or an explicit ``\\quad`` -- quantities that
vary between environments and document classes.  What does *not* vary is that within one
matrix the separators are consistent.  So instead of asking "is this gap bigger than
``H``", we look at the sorted list of gaps and cut it at its own largest step, then check
that every row yields the same column count.  If they do not, this is not a matrix, and
we say so instead of forcing one.
"""

from __future__ import annotations

from typing import Any, Callable, Optional, Sequence

from ..geometry.bbox import BBox
from ..geometry.index import vertical_bands
from ..tree.nodes import (Lines, MathNode, Matrix, MatrixCell, MatrixRow,
                          Provenance, Row)
from .context import Explanation, ParseContext
from .units import Unit

ParseGroup = Callable[[list[Unit], ParseContext], MathNode]


def split_rows(units: Sequence[Unit], ctx: ParseContext) -> list[list[Unit]]:
    """Group units into visual rows separated by real vertical whitespace.

    The gap threshold is half an x-height: smaller than any inter-row gap TeX produces
    (``\\baselineskip`` leaves several points) and larger than the negative gap a script
    makes with its own base, which always overlaps it.
    """
    boxes = [u.bbox for u in units]
    gap = 0.5 * ctx.params.x_height
    bands = vertical_bands(boxes, gap=gap)
    return [sorted((units[i] for i in band), key=lambda u: u.x0) for band in bands]


def _widest_automatic_space(ctx: ParseContext) -> float:
    """The widest gap TeX's own inter-atom glue can produce: a thick space, 5/18 quad.

    Anything wider was put there by the document -- an ``&`` in an alignment, a
    ``\\quad``, an ``\\arraycolsep``.  That is the principled dividing line between
    "these symbols are adjacent" and "these symbols are in different columns", and it
    replaces the tuned constant ``H`` whose failure Baker documented.
    """
    return 5.0 / 18.0 * (ctx.params.quad or ctx.size)


def _columns(row: Sequence[Unit], threshold: float) -> list[list[Unit]]:
    cols: list[list[Unit]] = [[row[0]]]
    edge = row[0].x1
    for u in row[1:]:
        if u.x0 - edge > threshold:
            cols.append([u])
        else:
            cols[-1].append(u)
        edge = max(edge, u.x1)
    return cols


def find_column_split(rows: Sequence[Sequence[Unit]],
                      ctx: ParseContext) -> tuple[Optional[float], dict[str, Any]]:
    """Find a gap threshold that splits every row into the same number of columns.

    Returns ``(None, evidence)`` when the rows do not agree, in which case the caller
    keeps them as separate lines rather than forcing a table on them.
    """
    gaps: list[float] = []
    for row in rows:
        for a, b in zip(row, row[1:]):
            gaps.append(b.x0 - a.x1)
    glue_max = _widest_automatic_space(ctx)
    ev: dict[str, Any] = {
        "n_rows": len(rows),
        "gaps_pt": [round(g, 4) for g in sorted(gaps)],
        "widest_automatic_space_pt": round(glue_max, 4),
    }
    if not gaps:
        ev["reason"] = "no horizontal gaps: a single column"
        ev["column_counts"] = [1] * len(rows)
        return None, ev

    margin = 1.25                      # a separator must clearly beat automatic glue
    seps = [g for g in gaps if g > glue_max * margin]
    intra = [g for g in gaps if g <= glue_max * margin]
    if not seps:
        ev["reason"] = "no gap exceeds the widest automatic inter-atom space"
        ev["column_counts"] = [1] * len(rows)
        return None, ev

    lo = max(intra) if intra else glue_max
    threshold = 0.5 * (lo + min(seps))
    ev["threshold_pt"] = round(threshold, 4)
    ev["threshold_em"] = round(threshold / max(ctx.size, 1e-6), 4)
    ev["separator_gaps_pt"] = [round(g, 4) for g in sorted(seps)]
    counts = [len(_columns(r, threshold)) for r in rows]
    ev["column_counts"] = counts
    if len(set(counts)) != 1:
        ev["reason"] = "column counts disagree between rows"
        return None, ev
    return threshold, ev


def build(rows: list[list[Unit]], ctx: ParseContext, parse_group: ParseGroup,
          inside_fence: bool) -> Unit:
    """Build a :class:`Matrix` when the rows really align, a :class:`Lines` otherwise."""
    threshold, ev = find_column_split(rows, ctx)
    ev["inside_fence"] = inside_fence
    box = BBox.union([u.bbox for row in rows for u in row])
    gids = sorted({g for row in rows for u in row for g in u.glyph_ids})
    rids = sorted({r for row in rows for u in row for r in u.rule_ids})
    size = max((u.size for row in rows for u in row), default=ctx.size)

    # One column per row is still a table -- and it serialises to exactly the same
    # ``mtable`` -- so it is reported as a Matrix.  ``Lines`` is reserved for the case
    # where the rows genuinely *disagree* about their column structure, which is a real
    # "we could not tell" rather than a shape worth asserting.
    single_column = threshold is None and ev.get("column_counts") == [1] * len(rows)
    if threshold is not None or single_column:
        mrows = []
        for row in rows:
            cells = []
            for col in ([list(row)] if threshold is None
                        else _columns(row, threshold)):
                cell = MatrixCell(children=[parse_group(col, ctx.same())])
                cell.prov = Provenance(
                    sorted({g for u in col for g in u.glyph_ids}),
                    sorted({r for u in col for r in u.rule_ids}),
                    BBox.union([u.bbox for u in col]), 0.99, {}, "matrix-cell")
                cells.append(cell)
            mrow = MatrixRow(children=cells)
            mrow.prov = Provenance(
                sorted({g for u in row for g in u.glyph_ids}),
                sorted({r for u in row for r in u.rule_ids}),
                BBox.union([u.bbox for u in row]), 0.99, {}, "matrix-row")
            mrows.append(mrow)
        node: MathNode = Matrix(children=mrows)
        conf = 0.98
        rule_name = "matrix"
    else:
        node = Lines(children=[parse_group(row, ctx.same()) for row in rows])
        conf = 0.9
        rule_name = "lines"

    node.prov = Provenance(gids, rids, box, conf, ev, rule_name)
    ctx.trace.add(Explanation(rule_name, node.node_id, {}, conf, ev))
    baseline = rows[len(rows) // 2][0].baseline if rows and rows[0] else box.cy
    return Unit.composite(node, baseline, box, size, gids, rids)
