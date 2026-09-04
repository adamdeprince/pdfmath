"""Recompiling what was recovered.

The strongest check in the suite: a decompiler is validated by recompiling.  Feed the
recovered tree back to pdfTeX and every glyph must land in the same place it was on the
original page.  Unlike the corpus comparison this needs no ground truth, so the same
machinery works on real documents -- see ``pdfmath roundtrip``.

It is also *stricter* than the corpus comparison in one direction and looser in another.
Stricter, because it catches anything the tree records but the serializer cannot put back
-- a glyph with no command, an atom class that changes the surrounding glue.  Looser,
because two trees that TeX renders identically both pass, which is the right answer:
``{a+b}^2`` and ``a+b^2`` are the same page.
"""

from __future__ import annotations

import pytest

from pdfmath.corpus.compile import compile_expressions, have_pdflatex
from pdfmath.corpus.milestone import EXTENDED, MILESTONE
from pdfmath.eval.roundtrip import POSITION_TOLERANCE_PT, roundtrip, size_option_for
from pdfmath.extraction.pdfminer_backend import extract_pages
from pdfmath.parse.driver import parse

pytestmark = pytest.mark.skipif(not have_pdflatex(), reason="pdflatex is not installed")


def _run(corpus, workdir, tag):
    pdf = compile_expressions([e.to_tex() for e in corpus], workdir=workdir)
    out = []
    for i, (expr, page) in enumerate(zip(corpus, extract_pages(pdf.pdf_path))):
        tree, ctx = parse(page.glyphs, page.rules)
        out.append((expr, roundtrip(tree, page, ctx, workdir=workdir,
                                    name=f"{tag}{i}")))
    return out


@pytest.fixture(scope="module")
def milestone(tmp_path_factory):
    return _run(MILESTONE, str(tmp_path_factory.mktemp("rt_milestone")), "m")


@pytest.fixture(scope="module")
def extended(tmp_path_factory):
    return _run(EXTENDED, str(tmp_path_factory.mktemp("rt_extended")), "e")


def test_the_first_milestone_recompiles_to_the_same_page(milestone):
    bad = [(e.to_tex(), r.verdict, r.latex, round(r.max_offset_pt, 4))
           for e, r in milestone if not r.ok]
    assert bad == []


def test_the_extended_corpus_recompiles_to_the_same_page(extended):
    bad = [(e.to_tex(), r.verdict, r.latex) for e, r in extended if not r.ok]
    assert bad == []


def test_every_glyph_comes_back_identical(milestone):
    for expr, r in milestone:
        assert r.identities_match, expr.to_tex()
        assert r.n_original == r.n_rebuilt


def test_rules_come_back_too(milestone):
    for expr, r in milestone:
        assert r.rules_match, f"{expr.to_tex()}: {r.n_original_rules} vs {r.n_rebuilt_rules}"


def test_positions_agree_to_within_pdftex_rounding(milestone):
    worst = max(r.max_offset_pt for _, r in milestone)
    assert worst <= POSITION_TOLERANCE_PT, f"worst offset {worst:.5f} pt"


def test_the_serialiser_leaves_nothing_behind(milestone, extended):
    for expr, r in list(milestone) + list(extended):
        assert not r.unreproducible, f"{expr.to_tex()}: {r.unreproducible}"


def test_document_size_is_chosen_from_the_text_size():
    assert size_option_for(10.0) == 10
    assert size_option_for(10.95) == 11
    assert size_option_for(12.0) == 12
