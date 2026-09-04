"""Scoring against a real paper's own LaTeX source.

Runs only when a cache of arXiv e-prints is available: set ``PDFMATH_ARXIV_CACHE`` to a
directory and the sources are downloaded into it once. Nothing is committed, because
redistributing other people's papers is not ours to do.

    PDFMATH_ARXIV_CACHE=/tmp/arxiv pytest tests/real_papers/test_arxiv.py

The bars below are deliberately a little under the numbers observed while writing this,
so that the test catches a regression rather than pinning an exact figure that will move
as the parser improves.
"""

from __future__ import annotations

import os

import pytest

from pdfmath.corpus.compile import have_pdflatex
from pdfmath.eval import latexml

CACHE = os.environ.get("PDFMATH_ARXIV_CACHE")

pytestmark = [
    pytest.mark.skipif(not CACHE, reason="set PDFMATH_ARXIV_CACHE to run"),
    pytest.mark.skipif(not latexml.available(), reason="latexmlmath is not installed"),
    pytest.mark.skipif(not have_pdflatex(), reason="pdflatex is not installed"),
]

#: (identifier, the accuracy this paper should not fall below)
PAPERS = [
    ("math/0211159v1", 0.85),      # Perelman, "The entropy formula...", 2002
    ("math/0303109v1", 0.50),      # Perelman, "Finite extinction time...", 2003
    ("math/0405568v1", 0.40),
]


@pytest.fixture(scope="module")
def results():
    from pdfmath.eval.arxiv_eval import evaluate
    return {ident: evaluate(ident, CACHE) for ident, _ in PAPERS}


@pytest.mark.parametrize("identifier,floor", PAPERS)
def test_structure_agrees_with_the_papers_own_source(results, identifier, floor):
    r = results[identifier]
    if r.error:
        pytest.skip(r.error)
    assert r.scored, "nothing was scored"
    assert r.accuracy >= floor, (
        f"{identifier}: {r.matched}/{len(r.scored)} = {r.accuracy:.3f}")


@pytest.mark.parametrize("identifier,_floor", PAPERS)
def test_no_glyph_is_dropped_on_a_real_paper(results, identifier, _floor):
    r = results[identifier]
    if r.error:
        pytest.skip(r.error)
    assert r.glyph_recovery == 1.0, f"{identifier}: {r.glyph_recovery:.5f}"


def test_overall_accuracy(results):
    scored = sum(len(r.scored) for r in results.values() if not r.error)
    matched = sum(r.matched for r in results.values() if not r.error)
    if not scored:
        pytest.skip("no papers were scored")
    assert matched / scored >= 0.80, f"{matched}/{scored}"
