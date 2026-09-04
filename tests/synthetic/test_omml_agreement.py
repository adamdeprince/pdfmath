"""Cross-checking the OMML writer against Word's format, read by someone else.

Nothing else in the suite reads OMML, so a swapped slot or a dropped child would pass
every other test.  Pandoc's ``docx`` reader parses it with no knowledge of this project;
comparing its MathML against ours is the same check LaTeXML performs on the ground truth.

What is folded before comparison, and why, is documented in
:mod:`pdfmath.eval.omml_roundtrip`.
"""

from __future__ import annotations

import pytest

from pdfmath.corpus.compile import compile_expressions, have_pdflatex
from pdfmath.corpus.milestone import EXTENDED, MILESTONE
from pdfmath.eval import omml_roundtrip as rt
from pdfmath.extraction.pdfminer_backend import extract_page
from pdfmath.omml.serializer import to_omml
from pdfmath.parse.driver import parse_page

pytestmark = [
    pytest.mark.skipif(not have_pdflatex(), reason="pdflatex is not installed"),
    pytest.mark.skipif(not rt.available(), reason="pandoc is not installed"),
]


@pytest.fixture(scope="module")
def trees(tmp_path_factory):
    tex = [e.to_tex() for e in EXTENDED]
    corpus = compile_expressions(tex, workdir=str(tmp_path_factory.mktemp("omml")))
    out = []
    for i, t in enumerate(tex):
        page = extract_page(corpus.pdf_path, corpus.page_of(i))
        out.append((t, parse_page(page)[0]))
    return out


@pytest.fixture(scope="module")
def verdicts(trees):
    """One pandoc run for the whole corpus; starting it per expression dominates."""
    return list(zip([t for t, _ in trees], rt.check_batch([n for _, n in trees])))


def test_milestone_survives_the_round_trip(verdicts):
    milestone = {e.to_tex() for e in MILESTONE}
    bad = [(t, v.error or v.ours) for t, v in verdicts
           if t in milestone and not v.agrees]
    assert bad == []


def test_extended_corpus_survives_the_round_trip(verdicts):
    bad = [(t, v.error or (v.ours, v.theirs)) for t, v in verdicts if not v.agrees]
    assert bad == []


def test_every_equation_is_expressible(trees):
    bad = [(t, r.unreproducible) for t, tree in trees
           for r in [to_omml(tree)] if not r.ok]
    assert bad == []


def test_the_package_we_build_is_a_readable_document(trees, tmp_path):
    """The wrapper matters as much as the markup: Word must be able to open it."""
    import pypandoc

    path = rt.write_docx(
        [to_omml(n, indent=False, namespace=False).omml for _, n in trees[:3]],
        str(tmp_path / "probe.docx"))
    text = pypandoc.convert_file(path, "plain", format="docx")
    assert text.strip(), "pandoc opened the package but found nothing in it"
