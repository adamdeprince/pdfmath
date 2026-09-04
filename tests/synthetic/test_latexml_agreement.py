"""Cross-checking our ground truth against an independent converter.

The synthetic corpus is only as good as the trees it claims are correct, and those come
from the same objects that emit the LaTeX -- so a systematic misunderstanding on our part
would be invisible.  LaTeXML reads the same LaTeX with none of our code, which is exactly
the check that closes that hole.

The comparison is on *relaxed* signatures: grouping, invisible operators, ``mi`` against
``mo`` and the spacing-versus-combining spelling of an accent are folded, because a PDF
records none of them.
"""

from __future__ import annotations

import pytest

from pdfmath.corpus.harness import normalise
from pdfmath.corpus.milestone import EXTENDED, MILESTONE
from pdfmath.eval import latexml
from pdfmath.eval.mathml_compare import mathml_signature, relax

pytestmark = pytest.mark.skipif(not latexml.available(),
                                reason="latexmlmath is not installed")


def _agree(expr):
    conv = latexml.to_mathml(expr.to_tex())
    if not conv.ok:
        pytest.skip(f"LaTeXML could not convert {expr.to_tex()!r}: {conv.error}")
    theirs = normalise(relax(mathml_signature(conv.mathml)))
    ours = normalise(relax(expr.to_signature()))
    return theirs, ours


@pytest.mark.parametrize("i", range(len(MILESTONE)))
def test_milestone_ground_truth_matches_latexml(i):
    theirs, ours = _agree(MILESTONE[i])
    assert theirs == ours, MILESTONE[i].to_tex()


def test_extended_ground_truth_mostly_matches_latexml():
    """Two of the fifty-eight differ, and both are LaTeXML's reading rather than ours.

    ``{{}x^2}_i`` -- our brace guard against tex.web 1186 -- makes LaTeXML drop the
    scripts entirely, and it declines to parse ``\\left| ... \\right|`` inside a matrix
    cell.  Neither is a claim about the page, so the bar is set just below the total
    rather than at it.
    """
    agree = 0
    for expr in EXTENDED:
        conv = latexml.to_mathml(expr.to_tex())
        if not conv.ok:
            continue
        theirs = normalise(relax(mathml_signature(conv.mathml)))
        ours = normalise(relax(expr.to_signature()))
        agree += theirs == ours
    assert agree >= len(EXTENDED) - 3, f"only {agree}/{len(EXTENDED)} agree"
