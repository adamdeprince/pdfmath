"""Hypothesis strategies over the expression grammar.

Property-based testing here has an unusual shape: the property is *round-tripping through
a compiler*, so every example costs a pdfTeX run.  Examples are therefore kept small and
the example budget modest by default; the bulk fuzzing is done by
``pdfmath.corpus.generate``, which batches thousands of expressions into one compile.
"""

from __future__ import annotations

from typing import Any

try:
    from hypothesis import strategies as st
except ImportError:                                   # pragma: no cover
    st = None                                         # type: ignore

from .grammar import (ACCENTS, BIG_OPS, DELIMS, Acc, BigOp, Delim, Expr, Frac, Ident,
                      Mat, Num, Op, OverLine, Seq, Sqrt, Sub, SubSup, Sup)

_LETTERS = list("abcdefgxyznikMN")
_GREEK = [("α", "\\alpha"), ("β", "\\beta"), ("θ", "\\theta"), ("π", "\\pi")]
_NUMBERS = ["0", "1", "2", "7", "10", "42"]
_OPS = [("+", "+"), ("−", "-"), ("=", "="), ("≤", "\\le"), ("×", "\\times"),
        (",", ","), ("∈", "\\in")]


def leaves():
    return st.one_of(
        st.sampled_from(_LETTERS).map(Ident),
        st.sampled_from(_GREEK).map(lambda g: Ident(g[0], g[1])),
        st.sampled_from(_NUMBERS).map(Num),
    )


def expressions(max_leaves: int = 8):
    """Expressions whose TeX and expected tree both come from the same object.

    Rows are excluded as script bases and single-row matrices are excluded entirely,
    for the same reason in both cases: TeX renders them identically to something
    simpler, so ground truth could not honestly distinguish them.
    """
    def extend(child):
        atomic = st.one_of(leaves(), child.filter(lambda e: not isinstance(e, Seq)))
        return st.one_of(
            st.tuples(child, child).map(lambda t: Frac(*t)),
            st.tuples(atomic, child).map(lambda t: Sup(*t)),
            st.tuples(atomic, child).map(lambda t: Sub(*t)),
            st.tuples(atomic, child, child).map(lambda t: SubSup(*t)),
            child.map(Sqrt),
            st.tuples(child, leaves()).map(lambda t: Sqrt(t[0], t[1])),
            st.tuples(child, st.sampled_from(sorted(DELIMS))).map(
                lambda t: Delim(t[0], t[1])),
            st.tuples(st.sampled_from(sorted(ACCENTS)), leaves()).map(
                lambda t: Acc(t[0], t[1])),
            child.map(OverLine),
            st.tuples(st.sampled_from(sorted(BIG_OPS)), child, child, child).map(
                lambda t: BigOp(t[0], t[1], t[2], t[3])),
            st.lists(st.lists(child, min_size=1, max_size=2).map(tuple),
                     min_size=2, max_size=2).map(
                lambda rows: Mat(tuple(_rectangular(rows)), "pmatrix")),
            st.lists(st.one_of(child, st.sampled_from(_OPS).map(lambda o: Op(*o))),
                     min_size=2, max_size=4).map(lambda ps: Seq(tuple(ps))),
        )

    return st.recursive(leaves(), extend, max_leaves=max_leaves)


def _rectangular(rows: list[tuple]) -> list[tuple]:
    n = min(len(r) for r in rows)
    return [r[:n] for r in rows]
