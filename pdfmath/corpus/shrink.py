"""Shrinking a failing expression to the smallest one that still fails.

A fuzzer that reports ``\\frac{x^{a+b}}{\\sqrt{\\frac{c_i}{d}}}`` has told you almost
nothing.  The same fuzzer reporting ``x^{a+b}`` has told you what to fix.  Shrinking is
therefore not a convenience here; it is what turns fuzzing into a usable engineering tool.

The search is a straightforward greedy descent over structural simplifications --
replace a node by one of its children, replace a subtree by a leaf, drop a row element --
re-testing after each.  Candidates are batched into a single pdfTeX run, because
compilation dominates the cost and a batch of fifty costs barely more than one.
"""

from __future__ import annotations

from typing import Callable, Iterator, Optional, Sequence

from .grammar import Expr, Ident, Mat, Num, Seq, Sub, SubSup, Sup
from .harness import Report, run

#: A predicate that says whether an expression still exhibits the bug.
Fails = Callable[[Sequence[Expr]], list[bool]]


def candidates(e: Expr) -> Iterator[Expr]:
    """Structurally simpler expressions to try, roughly smallest-first."""
    kids = list(e.children())

    # 1. replace the whole thing by one of its children
    for k in kids:
        if k.size() < e.size():
            yield k

    # 2. shrink a row by dropping elements
    if isinstance(e, Seq) and len(e.parts) > 2:
        for i in range(len(e.parts)):
            rest = e.parts[:i] + e.parts[i + 1:]
            if rest:
                yield Seq(rest) if len(rest) > 1 else rest[0]

    # 3. shrink a matrix by dropping a row or a column
    if isinstance(e, Mat):
        if len(e.rows) > 1:
            for i in range(len(e.rows)):
                yield Mat(e.rows[:i] + e.rows[i + 1:], e.env)
        if e.rows and len(e.rows[0]) > 1:
            for j in range(len(e.rows[0])):
                yield Mat(tuple(r[:j] + r[j + 1:] for r in e.rows), e.env)

    # 4. simplify one child at a time, keeping the shape
    for i, k in enumerate(kids):
        for small in _simplify(k):
            new_kids = list(kids)
            new_kids[i] = small
            try:
                yield e.replace_children(new_kids)
            except (IndexError, StopIteration):
                pass


def _simplify(e: Expr) -> Iterator[Expr]:
    if isinstance(e, (Ident, Num)):
        if isinstance(e, Num) and e.text != "1":
            yield Num("1")
        elif isinstance(e, Ident) and e.text != "x":
            yield Ident("x")
        return
    yield Ident("x")
    for k in e.children():
        if k.size() < e.size():
            yield k


def is_recoverable(e: Expr) -> bool:
    """Would TeX render this distinguishably from something simpler?

    Shrinking is free to produce shapes the generator deliberately avoids, and two of
    them are not recoverable from the page at all: a matrix with a single row (which
    renders exactly like a spaced row) and a row used as a script base (whose grouping
    TeX does not show).  Reporting either as a failure would blame the decompiler for an
    ambiguity in the ground truth, so they are filtered out of the search.
    """
    if isinstance(e, Mat) and len(e.rows) < 2:
        return False
    if isinstance(e, (Sup, Sub, SubSup)) and isinstance(e.base, Seq):
        return False
    return all(is_recoverable(c) for c in e.children())


def shrink(expr: Expr, still_fails: Fails, max_rounds: int = 40,
           batch: int = 48) -> Expr:
    """Greedily simplify ``expr`` while ``still_fails`` keeps returning True."""
    best = expr
    for _ in range(max_rounds):
        pool: list[Expr] = []
        seen: set[str] = {best.to_tex()}
        for c in candidates(best):
            t = c.to_tex()
            if t in seen or not is_recoverable(c):
                continue
            seen.add(t)
            pool.append(c)
            if len(pool) >= batch:
                break
        if not pool:
            break
        verdicts = still_fails(pool)
        failing = [c for c, bad in zip(pool, verdicts) if bad]
        if not failing:
            break
        best = min(failing, key=lambda c: (c.size(), len(c.to_tex())))
    return best


def failure_predicate(workdir: Optional[str] = None) -> Fails:
    """A ``still_fails`` predicate that compiles and decompiles a batch of expressions."""

    def check(exprs: Sequence[Expr]) -> list[bool]:
        try:
            report = run(list(exprs), workdir=workdir)
        except Exception:
            return [False] * len(exprs)
        by_index = {c.index: c for c in report.cases}
        return [not by_index[i].ok if i in by_index else False
                for i in range(len(exprs))]

    return check
