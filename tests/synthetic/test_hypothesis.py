"""Property-based round-tripping.

The property: for any expression the grammar can produce, decompiling the PDF that
pdfTeX makes from it recovers the tree the expression describes.

Each example costs a pdfTeX run, so the budget is small by default and raised in CI via
``PDFMATH_HYPOTHESIS_EXAMPLES``.  Bulk fuzzing lives in ``pdfmath benchmark``, which
batches thousands of expressions into a single compile.
"""

from __future__ import annotations

import dataclasses
import os

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import HealthCheck, assume, given, settings  # noqa: E402

from pdfmath.corpus.compile import have_pdflatex  # noqa: E402
from pdfmath.corpus.harness import run  # noqa: E402
from pdfmath.corpus.grammar import Frac, Mat  # noqa: E402
from pdfmath.corpus.strategies import expressions  # noqa: E402

pytestmark = pytest.mark.skipif(not have_pdflatex(), reason="pdflatex is not installed")

EXAMPLES = int(os.environ.get("PDFMATH_HYPOTHESIS_EXAMPLES", "15"))


def _known_open(expr) -> bool:
    """A single-column matrix with a fraction below the first row.

    The fraction bar claims its numerator before matrix rows are segmented, so the
    search walks up into the row above.  It is minimised, pinned as a strict xfail in
    ``tests/regression/test_regressions.py`` (``KNOWN_OPEN``) and described in
    ``docs/architecture.md``; rejecting it here lets the fuzzer look for *new* bugs
    instead of rediscovering this one every run.  Delete this when it is fixed -- the
    strict xfail will fail loudly and point here.
    """
    if not isinstance(expr, Mat):
        return False
    if any(len(row) != 1 for row in expr.rows):
        return False
    return any(_contains_fraction(cell) for row in expr.rows[1:] for cell in row)


def _contains_fraction(node) -> bool:
    """Every grammar node is a dataclass, so its children are its fields."""
    if isinstance(node, Frac):
        return True
    if not dataclasses.is_dataclass(node):
        return False
    for field in dataclasses.fields(node):
        value = getattr(node, field.name)
        for child in (value if isinstance(value, tuple) else (value,)):
            for leaf in (child if isinstance(child, tuple) else (child,)):
                if _contains_fraction(leaf):
                    return True
    return False


@settings(max_examples=EXAMPLES, deadline=None,
          suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large])
@given(expressions(max_leaves=6))
def test_decompiles_to_the_generating_tree(expr):
    assume(not _known_open(expr))
    report = run([expr])
    case = report.cases[0]
    assert case.error is None, f"{case.tex}: {case.error}"
    assert case.glyphs_in_tree == case.glyphs_extracted, f"{case.tex}: glyph lost"
    assert case.exact, (f"{case.tex}\n  expected {case.expected}\n"
                        f"  actual   {case.actual}")
