"""Minimised regressions.

Every entry here is a bug the fuzzer found, reduced by ``pdfmath.corpus.shrink`` to the
smallest expression that still exhibited it, and kept so that the underlying *rule* --
not the individual document -- stays fixed.  The comment on each case names the TeX
behaviour it exercises, because that is what the fix generalises to.
"""

from __future__ import annotations

import pytest

from pdfmath.corpus.compile import have_pdflatex
from pdfmath.corpus.grammar import (Acc, BigOp, Delim, Frac, Ident, Mat, Num, Op,
                                    OverLine, Seq, Sqrt, Sub, SubSup, Sup)
from pdfmath.corpus.harness import run

pytestmark = pytest.mark.skipif(not have_pdflatex(), reason="pdflatex is not installed")

I, N = Ident, Num
x, y, z, a, b, c, d, i, n = (Ident(ch) for ch in "xyzabcdin")

#: (name, expression, what the fix generalised to)
CASES = [
    ("nested-fraction-anchor-order",
     Frac(Frac(Frac(a, b), c), d),
     "the outermost bar must win the anchor contest; a nested bar is contained in its "
     "parent's horizontal span, never the reverse"),

    ("style-dependent-rule-thickness",
     Frac(Frac(a, b), c),
     "LaTeX loads cmex7 for scriptscript, so a deeply nested bar is 0.243 pt, not 0.4"),

    ("large-operator-axis-centring",
     BigOp("\\sum", Seq((i, Op("=", "="), N("0"))), n, Sub(x, i)),
     "make_op shifts the operator so its middle is on the axis; undoing that recovers "
     "the line's baseline"),

    ("limit-starts-left-of-the-operator-origin",
     BigOp("\\prod", Seq((i, Op("=", "="), N("1"))), n, Sub(x, i)),
     "a centred limit can begin before its operator does, so claims must be resolved "
     "before anything is emitted"),

    ("explicit-space-and-flat-rows",
     BigOp("\\int", N("0"), N("1"), Seq((Sup(x, N("2")), I("d"), x))),
     "row nesting is not observable, so ground truth and output are both flattened"),

    ("delimiter-axis-centring",
     Delim(Sqrt(Frac(x, y)), "paren"),
     "var_delimiter centres every \\left/\\right fence on the axis; the text-size "
     "delimiters have a shift of exactly zero, so the correction is unconditional"),

    ("radical-index-is-scriptscript",
     Delim(Sqrt(x), "paren"),
     "an opening fence to the left of a surd is not a root index; the index is set in "
     "scriptscript style and raised"),

    ("accent-left-of-its-nucleus",
     Acc("\\vec", x),
     "make_math_accent centres the accent, so a wide one starts left of its base"),

    ("overline-of-a-row",
     OverLine(Seq((x, Op("+", "+"), y))),
     "cohesion within a structure is vertical only; horizontal inter-atom space must "
     "not split a numerator or an overlined row"),

    ("fraction-must-not-reach-into-the-row-above",
     Mat(((Sup(a, N("2")), b), (c, Frac(x, y))), "pmatrix"),
     "a fraction inside a matrix cell claims only material structurally connected to "
     "its own bar"),

    ("matrix-in-a-fraction-part",
     Frac(x, Mat(((N("3"), N("100")), (N("0"), I("B"))), "matrix")),
     "rule 15 makes the bar exactly as wide as the wider part, which is a check and a "
     "repair when cohesion stops early"),

    ("script-on-a-multi-digit-number",
     Sub(N("10"), N("0")),
     "digit runs are merged into one token before scripts are attached"),

    ("accent-over-a-multi-digit-number",
     Acc("\\ddot", N("42")),
     "an accent has zero width in TeX's hlist and must not split a digit run"),

    ("stacked-extensible-bars",
     Delim(Frac(Frac(a, b), Frac(c, d)), "vert"),
     "a tall | is several stacked cmex glyphs; the TFM's extensible recipes say which"),

    ("built-up-brace-pairs-like-any-fence",
     Frac(Mat(((I("H"), I("P")), (I("w"), I("k"))), "Bmatrix"), a),
     "an assembled \\left\\{ keeps the Open atom class of the delimiter it builds"),

    ("chained-script-on-a-box",
     Sub(Sup(x, N("2")), i),
     "both scripts of one nucleus start at its advance width; a script on the enclosing "
     "box starts after that box ends"),

    ("superscript-inside-a-subscript",
     Sub(x, Sup(N("9"), I("s"))),
     "a subscript's own superscript can sit above the base's baseline, so sides are "
     "decided by the cut line between the two leading boxes, not by the base baseline"),

    ("operator-with-scripts-inside-a-subscript",
     Sub(x, Seq((BigOp("\\prod", I("L"), I("V")), N("0")))),
     "an operator takes limits only in display style; in a script it takes scripts"),

    ("delimited-group-as-a-subscript",
     SubSup(N("10"), Delim(I("r"), "paren"), Ident("τ", "\\tau")),
     "a fence inside a script is centred on the script's baseline, not the row's"),

    ("single-column-table",
     Mat(((c,), (N("100"),), (I("o"),)), "matrix"),
     "one column per row is still an mtable"),

    ("nested-script-tower",
     Sup(x, Sup(y, N("2"))),
     "a script's own script is contiguous with it, so the assigned set grows across it"),

    ("radical-over-a-fraction",
     Sqrt(Frac(x, y)),
     "the radicand lies inside the surd's own vertical extent, which var_delimiter "
     "sized to cover it"),

    ("integral-with-a-delimited-superscript",
     Seq((BigOp("\\int", x, Delim(I("g"), "bracket")), x)),
     "\\int takes scripts, not limits, and its subscript sits at w - italic while its "
     "superscript sits at w"),
]


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    return run([e for _, e, _ in CASES],
               workdir=str(tmp_path_factory.mktemp("regression")))


@pytest.mark.parametrize("index,name", [(i, c[0]) for i, c in enumerate(CASES)])
def test_regression(report, index, name):
    case = report.cases[index]
    rationale = CASES[index][2]
    assert case.error is None, f"{name}: {case.error}"
    assert case.exact, (f"{name} ({rationale})\n  {case.tex}\n"
                        f"  expected {case.expected}\n  actual   {case.actual}")


def test_nothing_is_ever_dropped(report):
    for case, (name, _, _) in zip(report.cases, CASES):
        assert case.glyphs_in_tree == case.glyphs_extracted, f"{name}: glyph lost"
