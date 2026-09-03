"""The first-milestone corpus: the expressions named in the project brief.

These are the cases that must be essentially perfect before support is broadened.  They
are written out longhand rather than generated so that the list is auditable against the
brief.
"""

from __future__ import annotations

from .grammar import (Acc, BigOp, Delim, Expr, Frac, Ident, Mat, Num, Op, OverLine,
                      Seq, Sqrt, Sub, SubSup, Sup, ThinSpace)

x, y, z, n, i = (Ident(c) for c in "xyzni")
a, b, c_, d = (Ident(ch) for ch in "abcd")


#: The 18 expressions of "First milestone" in the brief, in order.
MILESTONE: list[Expr] = [
    x,
    Seq((x, Op("+", "+"), y)),
    Sup(x, Num("2")),
    Sub(x, i),
    SubSup(x, i, Num("2")),
    Sup(x, Sup(y, Num("2"))),
    Frac(x, y),
    Frac(Seq((x, Op("+", "+"), Num("1"))), Seq((y, Op("+", "+"), Num("1")))),
    Frac(Sup(x, Num("2")), Sub(y, i)),
    Frac(Frac(a, b), c_),
    Sqrt(x),
    Sqrt(Seq((x, Op("+", "+"), y))),
    Sqrt(Frac(x, y)),
    BigOp("\\sum", Seq((i, Op("=", "="), Num("0"))), n, Sub(x, i)),
    BigOp("\\int", Num("0"), Num("1"),
          Seq((Sup(x, Num("2")), ThinSpace(), Ident("d"), x))),
    Delim(Frac(x, y), "paren"),
    Mat(((a, b), (c_, d)), "pmatrix"),
]


#: A wider hand-written set covering the constructs listed under "Grammar-based generator".
EXTENDED: list[Expr] = MILESTONE + [
    Ident("α", "\\alpha"),
    Ident("β", "\\beta"),
    Num("42"),
    Seq((x, Op("−", "-"), y)),
    Seq((x, Op("=", "="), y)),
    Seq((x, Op("≤", "\\le"), y)),
    Seq((x, Op(",", ","), y)),
    Sup(x, Sub(y, i)),
    Sub(Sup(x, Num("2")), i),
    Frac(Sqrt(x), Sqrt(y)),
    Frac(Sup(x, Num("2")), Sqrt(Seq((y, Op("+", "+"), Num("1"))))),
    Sqrt(Sqrt(x)),
    Sqrt(x, n),
    Sqrt(Seq((x, Op("+", "+"), y)), Num("3")),
    Delim(Seq((x, Op("+", "+"), y)), "bracket"),
    Delim(Frac(a, b), "brace"),
    Delim(x, "angle"),
    Delim(Seq((x, Op("+", "+"), y)), "vert"),
    Delim(Sqrt(Frac(x, y)), "paren"),
    Delim(x, "paren", big=False),
    BigOp("\\sum", i, None, Sub(x, i)),
    BigOp("\\prod", Seq((i, Op("=", "="), Num("1"))), n, Sub(x, i)),
    BigOp("\\int", None, None, Seq((Ident("f"), Delim(x, "paren", big=False)))),
    BigOp("\\int", Num("0"), Ident("∞", "\\infty"), Sup(Ident("e"), x)),
    BigOp("\\bigcup", Seq((i, Op("=", "="), Num("1"))), n, Sub(Ident("A"), i)),
    Acc("\\hat", x),
    Acc("\\bar", x),
    Acc("\\vec", x),
    Acc("\\dot", x),
    Acc("\\ddot", x),
    Acc("\\tilde", x),
    OverLine(Seq((x, Op("+", "+"), y))),
    Mat(((a, b), (c_, d)), "bmatrix"),
    Mat(((a, b, c_), (d, x, y)), "pmatrix"),
    Mat(((Sup(a, Num("2")), b), (c_, Frac(x, y))), "pmatrix"),
    Mat(((a,), (b,)), "pmatrix"),
    Seq((Ident("f"), Delim(x, "paren", big=False))),
    Frac(Frac(Frac(a, b), c_), d),
    Sup(x, Frac(a, b)),
    Sub(Frac(a, b), i),
    Seq((Sqrt(x), Op("+", "+"), Frac(y, z), Op("=", "="), Sup(z, Num("2")))),
]
