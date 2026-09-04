"""Inverting TeX's spacing to recover atom classes.

The controlled experiment the project set out to run.  ``\\mathbin{b}`` and
``\\mathrel{b}`` print the *same glyph* -- an ordinary cmmi ``b`` -- so no amount of
looking at the character says which the author wrote.  TeX's inter-atom glue does say,
because the two classes take different spaces against their neighbours, and those spaces
are exact multiples of ``mu`` computed from a font parameter we hold.

The results, in one sentence: the classes are recoverable wherever they change the
spacing, and where they do not change the spacing they are not recoverable and the answer
comes back as a set rather than a guess.
"""

from __future__ import annotations

import pytest

from pdfmath.corpus.compile import compile_expressions, have_pdflatex
from pdfmath.extraction.pdfminer_backend import extract_pages
from pdfmath.fonts.symbols import AtomClass
from pdfmath.parse.atoms import infer_middle_class, reclassify
from pdfmath.parse.context import ParseContext
from pdfmath.parse.spacing import observe

pytestmark = pytest.mark.skipif(not have_pdflatex(), reason="pdflatex is not installed")

#: (source, the class the middle atom was declared with)
CASES = [
    (r"a \mathbin{b} c", AtomClass.BIN),
    (r"a \mathrel{b} c", AtomClass.REL),
    (r"a \mathop{b} c", AtomClass.OP),
    (r"a \mathpunct{b} c", AtomClass.PUNCT),
    (r"a \mathord{b} c", AtomClass.ORD),
]


@pytest.fixture(scope="module")
def measured(tmp_path_factory):
    """(source, [gap in mu between consecutive glyph boxes]) for each case."""
    work = str(tmp_path_factory.mktemp("atoms"))
    corpus = compile_expressions([c[0] for c in CASES], workdir=work)
    ctx = ParseContext(text_size=10.0)
    out = []
    for page in extract_pages(corpus.pdf_path):
        gs = sorted(page.glyphs, key=lambda g: g.x)
        gaps = [observe(gs[i + 1].bbox.x0 - (gs[i].bbox.x1 + gs[i].italic), ctx).gap_mu
                for i in range(len(gs) - 1)]
        out.append(gaps)
    return out


def test_each_declared_class_produces_its_own_spacing(measured):
    """The five declarations give five distinguishable spacing signatures."""
    signatures = {tuple(round(g) for g in gaps) for gaps in measured}
    # Ord and Open would collide, but none of the five cases here does.
    assert len(signatures) == len(CASES), signatures


def test_the_class_is_recovered_from_the_spacing_alone(measured):
    for (source, declared), gaps in zip(CASES, measured):
        assert len(gaps) == 2, source
        candidates = infer_middle_class(gaps[0], gaps[1],
                                        AtomClass.ORD, AtomClass.ORD)
        assert declared in candidates, (
            f"{source}: measured {gaps} mu, candidates {[c.short for c in candidates]}")


def test_where_the_answer_is_ambiguous_it_is_reported_as_a_set(measured):
    """Ord and Open take the same space against Ord on both sides.

    The inverse is not injective, and saying so is the point: a decompiler that reported
    a single class here would be inventing a distinction the page does not make.
    """
    ord_gaps = measured[[c[1] for c in CASES].index(AtomClass.ORD)]
    candidates = infer_middle_class(ord_gaps[0], ord_gaps[1],
                                    AtomClass.ORD, AtomClass.ORD)
    assert AtomClass.ORD in candidates and AtomClass.OPEN in candidates
    assert AtomClass.BIN not in candidates


def test_unary_minus_is_reclassified_the_way_tex_does_it(tmp_path_factory):
    """``-x`` and ``a-b`` use one glyph and two classes; only the rewrite explains both."""
    work = str(tmp_path_factory.mktemp("unary"))
    corpus = compile_expressions([r"-x", r"a-b"], workdir=work)
    ctx = ParseContext(text_size=10.0)
    pages = list(extract_pages(corpus.pdf_path))

    unary = sorted(pages[0].glyphs, key=lambda g: g.x)
    gap = observe(unary[1].bbox.x0 - unary[0].bbox.x1, ctx)
    assert gap.name == "none", f"unary minus took {gap.gap_mu:.2f} mu"

    binary = sorted(pages[1].glyphs, key=lambda g: g.x)
    gap = observe(binary[1].bbox.x0 - binary[0].bbox.x1, ctx)
    assert gap.name == "medium", f"binary minus took {gap.gap_mu:.2f} mu"

    # ... and reclassify() reproduces exactly that difference from the classes alone.
    assert reclassify([AtomClass.BIN, AtomClass.ORD])[0] is AtomClass.ORD
    assert reclassify([AtomClass.ORD, AtomClass.BIN, AtomClass.ORD])[1] is AtomClass.BIN
