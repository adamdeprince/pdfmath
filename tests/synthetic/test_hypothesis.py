"""Property-based round-tripping.

The property: for any expression the grammar can produce, decompiling the PDF that
pdfTeX makes from it recovers the tree the expression describes.

Each example costs a pdfTeX run, so the budget is small by default and raised in CI via
``PDFMATH_HYPOTHESIS_EXAMPLES``.  Bulk fuzzing lives in ``pdfmath benchmark``, which
batches thousands of expressions into a single compile.
"""

from __future__ import annotations

import os

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import HealthCheck, given, settings  # noqa: E402

from pdfmath.corpus.compile import have_pdflatex  # noqa: E402
from pdfmath.corpus.harness import run  # noqa: E402
from pdfmath.corpus.strategies import expressions  # noqa: E402

pytestmark = pytest.mark.skipif(not have_pdflatex(), reason="pdflatex is not installed")

EXAMPLES = int(os.environ.get("PDFMATH_HYPOTHESIS_EXAMPLES", "15"))


@settings(max_examples=EXAMPLES, deadline=None,
          suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large])
@given(expressions(max_leaves=6))
def test_decompiles_to_the_generating_tree(expr):
    report = run([expr])
    case = report.cases[0]
    assert case.error is None, f"{case.tex}: {case.error}"
    assert case.glyphs_in_tree == case.glyphs_extracted, f"{case.tex}: glyph lost"
    assert case.exact, (f"{case.tex}\n  expected {case.expected}\n"
                        f"  actual   {case.actual}")
