"""Cross-checking the AsciiMath writer against an independent parser.

Serialising is the one place where a mistake is invisible to the rest of the test suite:
the tree can be perfectly right and the text still say something else, because nothing
downstream reads it.  ``py-asciimath`` has no knowledge of this project, so pushing our
output back through it and comparing MathML closes that hole -- the same job LaTeXML does
for the ground truth.

What is folded before comparison, and why, is documented in
:mod:`pdfmath.eval.asciimath_roundtrip`.
"""

from __future__ import annotations

import pytest

from pdfmath.corpus.compile import compile_expressions, have_pdflatex
from pdfmath.corpus.milestone import EXTENDED, MILESTONE
from pdfmath.eval import asciimath_roundtrip as rt
from pdfmath.extraction.pdfminer_backend import extract_page
from pdfmath.parse.driver import parse_page

pytestmark = [
    pytest.mark.skipif(not have_pdflatex(), reason="pdflatex is not installed"),
    pytest.mark.skipif(not rt.available(), reason="py-asciimath is not installed"),
]

#: py-asciimath's unary table has no ``tilde``, though asciimath.org's accent table does
#: and so does the reference ASCIIMathML.js.  The gap is the oracle's, not ours, so the
#: expression is named here rather than quietly folded in the comparator.
ORACLE_GAPS = {"\\tilde{x}"}


@pytest.fixture(scope="module")
def trees(tmp_path_factory):
    """Compile the extended corpus once and decompile every page."""
    tex = [e.to_tex() for e in EXTENDED]
    corpus = compile_expressions(tex, workdir=str(tmp_path_factory.mktemp("asciimath")))
    out = []
    for i, t in enumerate(tex):
        page = extract_page(corpus.pdf_path, corpus.page_of(i))
        out.append((t, parse_page(page)[0]))
    return out


def test_milestone_survives_the_round_trip(trees):
    milestone = {e.to_tex() for e in MILESTONE}
    bad = [(t, v.asciimath, v.error) for t, tree in trees if t in milestone
           for v in [rt.check(tree)] if not v.agrees]
    assert bad == []


def test_extended_corpus_survives_the_round_trip(trees):
    bad = [(t, v.asciimath) for t, tree in trees if t not in ORACLE_GAPS
           for v in [rt.check(tree)] if not v.agrees]
    assert bad == []


def test_the_named_oracle_gap_is_still_only_the_oracle(trees):
    """If py-asciimath learns ``tilde``, this test says so and the exception can go."""
    by_tex = dict(trees)
    for tex in ORACLE_GAPS:
        v = rt.check(by_tex[tex])
        assert v.asciimath == "tilde(x)", "our output should not have changed"
        if v.agrees:
            pytest.fail(f"py-asciimath now handles {tex}; drop it from ORACLE_GAPS")


def test_nothing_in_the_corpus_is_unspellable(trees):
    """Every glyph the corpus produces has an AsciiMath spelling."""
    from pdfmath.asciimath.serializer import to_asciimath
    unspellable = [(t, r.unreproducible) for t, tree in trees
                   for r in [to_asciimath(tree)] if not r.ok]
    assert unspellable == []
