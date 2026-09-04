"""Bounded random generation of expressions.

The generator is deliberately *not* uniform over the grammar.  Weights fall with depth so
that recursion terminates, and the pools of leaves are small so that failures are easy to
read.  Every expression carries its own ground truth, so a batch of ten thousand can be
compiled in one pdfTeX run and checked without a human ever seeing them.

Reproducibility matters more here than variety: a run is identified by its seed, and
``expressions(seed, n)`` returns the same list every time, so a failure found in CI can be
reproduced exactly.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional, Sequence

from .grammar import (ACCENTS, BIG_OPS, DELIMS, MATRIX_ENVS, Acc, BigOp, Delim, Expr,
                      Frac, Ident, Mat, Num, Op, OverLine, Seq, Sqrt, Sub, SubSup, Sup,
                      ThinSpace)

LETTERS = list("abcdefghijklmnopqrstuvwxyz") + list("ABCDEFGHIJKLMNPQRSTUVWXYZ")
GREEK = [("α", "\\alpha"), ("β", "\\beta"), ("γ", "\\gamma"), ("δ", "\\delta"),
         ("θ", "\\theta"), ("λ", "\\lambda"), ("μ", "\\mu"), ("ν", "\\nu"),
         ("ξ", "\\xi"), ("π", "\\pi"), ("ρ", "\\rho"), ("σ", "\\sigma"),
         ("τ", "\\tau"), ("ϕ", "\\phi"), ("χ", "\\chi"), ("ψ", "\\psi"),
         ("ω", "\\omega")]
NUMBERS = ["0", "1", "2", "3", "7", "9", "10", "42", "100"]
BINARY = [("+", "+"), ("−", "-"), ("×", "\\times"), ("±", "\\pm"), ("∪", "\\cup"),
          ("∩", "\\cap"), ("⋅", "\\cdot")]
RELATION = [("=", "="), ("<", "<"), (">", ">"), ("≤", "\\le"), ("≥", "\\ge"),
            ("≈", "\\approx"), ("≡", "\\equiv"), ("∈", "\\in"), ("⊂", "\\subset")]
PUNCT = [(",", ","), (";", ";")]


@dataclass
class GenConfig:
    """What the generator is allowed to produce, and how often."""

    max_depth: int = 4
    max_row: int = 4
    constructs: tuple[str, ...] = (
        "identifier", "number", "row", "script", "fraction", "radical",
        "delimiter", "largeop", "accent", "matrix", "space",
    )
    #: relative weight of each construct at depth 0; each falls off with depth
    weights: dict[str, float] = field(default_factory=lambda: {
        "identifier": 6.0, "number": 3.0, "row": 5.0, "script": 5.0,
        "fraction": 4.0, "radical": 3.0, "delimiter": 3.0, "largeop": 2.0,
        "accent": 2.0, "matrix": 1.0, "space": 0.0,
    })
    greek: bool = True

    def allowed(self, name: str) -> bool:
        return name in self.constructs


def _leaf(rng: random.Random, cfg: GenConfig) -> Expr:
    r = rng.random()
    if r < 0.25 and cfg.allowed("number"):
        return Num(rng.choice(NUMBERS))
    if cfg.greek and r < 0.35:
        u, t = rng.choice(GREEK)
        return Ident(u, t)
    return Ident(rng.choice(LETTERS))


def random_expr(rng: random.Random, cfg: Optional[GenConfig] = None,
                depth: int = 0) -> Expr:
    """One random expression, at most ``cfg.max_depth`` levels deep."""
    cfg = cfg or GenConfig()
    if depth >= cfg.max_depth:
        return _leaf(rng, cfg)

    fall = 0.55 ** depth
    choices: list[tuple[str, float]] = []
    for name, w in cfg.weights.items():
        if not cfg.allowed(name):
            continue
        if name in ("identifier", "number"):
            choices.append((name, w / max(fall, 1e-6)))
        else:
            choices.append((name, w * fall))
    names = [c[0] for c in choices]
    weights = [c[1] for c in choices]
    kind = rng.choices(names, weights=weights)[0]

    if kind in ("identifier", "number"):
        return _leaf(rng, cfg)
    if kind == "row":
        return _random_row(rng, cfg, depth)
    if kind == "script":
        return _random_script(rng, cfg, depth)
    if kind == "fraction":
        return Frac(random_expr(rng, cfg, depth + 1), random_expr(rng, cfg, depth + 1))
    if kind == "radical":
        if rng.random() < 0.25:
            return Sqrt(random_expr(rng, cfg, depth + 1), _leaf(rng, cfg))
        return Sqrt(random_expr(rng, cfg, depth + 1))
    if kind == "delimiter":
        return Delim(random_expr(rng, cfg, depth + 1),
                     rng.choice(list(DELIMS)), big=rng.random() < 0.75)
    if kind == "largeop":
        return _random_bigop(rng, cfg, depth)
    if kind == "accent":
        if rng.random() < 0.2:
            return OverLine(random_expr(rng, cfg, depth + 1))
        return Acc(rng.choice(list(ACCENTS)), _leaf(rng, cfg))
    if kind == "matrix":
        return _random_matrix(rng, cfg, depth)
    return _leaf(rng, cfg)


def _random_row(rng: random.Random, cfg: GenConfig, depth: int) -> Expr:
    n = rng.randint(2, cfg.max_row)
    parts: list[Expr] = [random_expr(rng, cfg, depth + 1)]
    for _ in range(n - 1):
        # (an operator is inserted below with high probability; see the note in
        # _no_adjacent_numbers about why a bare number pair is excluded)
        r = rng.random()
        if r < 0.45:
            parts.append(Op(*rng.choice(BINARY)))
        elif r < 0.75:
            parts.append(Op(*rng.choice(RELATION)))
        elif r < 0.85:
            parts.append(Op(*rng.choice(PUNCT)))
        elif r < 0.9 and cfg.allowed("space"):
            parts.append(ThinSpace())
        parts.append(random_expr(rng, cfg, depth + 1))
    return Seq(tuple(_no_adjacent_numbers(parts)))


def _no_adjacent_numbers(parts: list[Expr]) -> list[Expr]:
    """Drop a number that directly follows another number.

    TeX puts no glue between two Ord atoms, so "1 1" and "11" are the same page and the
    corpus must not claim they differ.  The decompiler merges digit runs into one ``mn``,
    which is the MathML convention and the only reading the geometry supports.
    """
    out: list[Expr] = []
    for part in parts:
        if (out and isinstance(part, Num) and isinstance(out[-1], Num)):
            continue
        out.append(part)
    return out or [Num("1")]


def _script_base(rng: random.Random, cfg: GenConfig, depth: int) -> Expr:
    """A base whose script placement is actually observable.

    ``{a+b}^2`` and ``a+b^2`` are rendered identically by TeX whenever the group is no
    taller than its last atom, which is the usual case: rule 18a's ``u = h - sup_drop``
    then loses to ``sup2`` and the superscript lands in the same place either way.  No
    decompiler can recover the grouping from the page, so the corpus must not claim it
    is there.  Structures that change the box -- a fraction, a radical, a fenced group,
    a matrix -- are fine, and are exercised heavily.
    """
    for _ in range(6):
        e = random_expr(rng, cfg, depth + 1)
        if not isinstance(e, Seq):
            return e
    return _leaf(rng, cfg)


def _random_script(rng: random.Random, cfg: GenConfig, depth: int) -> Expr:
    base = _script_base(rng, cfg, depth)
    r = rng.random()
    if r < 0.4:
        return Sup(base, random_expr(rng, cfg, depth + 1))
    if r < 0.75:
        return Sub(base, random_expr(rng, cfg, depth + 1))
    return SubSup(base, random_expr(rng, cfg, depth + 1),
                  random_expr(rng, cfg, depth + 1))


def _random_bigop(rng: random.Random, cfg: GenConfig, depth: int) -> Expr:
    op = rng.choice(list(BIG_OPS))
    r = rng.random()
    lower = random_expr(rng, cfg, depth + 2) if r < 0.8 else None
    upper = random_expr(rng, cfg, depth + 2) if r < 0.55 or r > 0.85 else None
    body = random_expr(rng, cfg, depth + 1) if rng.random() < 0.8 else None
    return BigOp(op, lower, upper, body)


def _random_matrix(rng: random.Random, cfg: GenConfig, depth: int) -> Expr:
    # At least two rows.  A single-row matrix is not recoverable and must not be in the
    # corpus: TeX renders "\\begin{pmatrix} a & b \\end{pmatrix}" exactly as it renders
    # "\\left( a \\quad b \\right)", and "\\begin{matrix} x \\end{matrix}" exactly as it
    # renders "x".  Ground truth may not assert structure the page does not show.
    rows = rng.randint(2, 3)
    cols = rng.randint(1, 3)
    cells = tuple(tuple(random_expr(rng, cfg, depth + 2) for _ in range(cols))
                  for _ in range(rows))
    return Mat(cells, rng.choice(list(MATRIX_ENVS)))


def expressions(seed: int, n: int, cfg: Optional[GenConfig] = None) -> list[Expr]:
    """``n`` reproducible random expressions."""
    rng = random.Random(seed)
    cfg = cfg or GenConfig()
    return [random_expr(rng, cfg) for _ in range(n)]
