"""The synthetic corpora, end to end.

These are the acceptance tests for the first milestone: compile with stock pdfTeX,
extract, decompile, and compare the reconstructed tree against ground truth generated
from the same source object.  Nothing about the expected answer is derived from the PDF.
"""

from __future__ import annotations

import pytest

from pdfmath.corpus.compile import have_pdflatex
from pdfmath.corpus.harness import run
from pdfmath.corpus.milestone import EXTENDED, MILESTONE

pytestmark = pytest.mark.skipif(not have_pdflatex(), reason="pdflatex is not installed")


@pytest.fixture(scope="module")
def milestone_report(tmp_path_factory):
    return run(MILESTONE, workdir=str(tmp_path_factory.mktemp("milestone")))


@pytest.fixture(scope="module")
def extended_report(tmp_path_factory):
    return run(EXTENDED, workdir=str(tmp_path_factory.mktemp("extended")))


def test_first_milestone_is_exact(milestone_report):
    failures = [(c.tex, c.expected, c.actual) for c in milestone_report.failures]
    assert failures == [], f"{len(failures)} of {len(MILESTONE)} milestone cases failed"


def test_no_glyph_is_ever_dropped(milestone_report, extended_report):
    for report in (milestone_report, extended_report):
        for case in report.cases:
            assert case.glyphs_in_tree == case.glyphs_extracted, (
                f"{case.tex}: {case.glyphs_extracted - case.glyphs_in_tree} glyph(s) "
                f"did not reach the tree")


def test_extended_corpus_is_exact(extended_report):
    failures = [(c.tex, c.expected, c.actual) for c in extended_report.failures]
    assert failures == []


def test_every_structural_decision_is_confident(milestone_report, tmp_path_factory):
    from pdfmath.corpus.compile import compile_expressions
    from pdfmath.extraction.pdfminer_backend import extract_pages
    from pdfmath.parse.driver import parse
    from pdfmath.tree.nodes import Space

    work = str(tmp_path_factory.mktemp("confidence"))
    corpus = compile_expressions([e.to_tex() for e in MILESTONE], workdir=work)
    for page, expr in zip(extract_pages(corpus.pdf_path), MILESTONE):
        tree, _ = parse(page.glyphs, page.rules)
        for node in tree.walk():
            if isinstance(node, Space):
                continue      # a measured space, not a structural inference
            assert node.prov.confidence > 0.9, (
                f"{expr.to_tex()}: {node.kind} at {node.prov.confidence:.3f}")


def test_no_unknown_nodes_in_the_milestone(milestone_report):
    for case in milestone_report.cases:
        assert case.unknown_nodes == 0, f"{case.tex} produced an Unknown node"


def test_mathml_is_well_formed(milestone_report, tmp_path_factory):
    from xml.etree import ElementTree

    from pdfmath.corpus.compile import compile_expressions
    from pdfmath.extraction.pdfminer_backend import extract_pages
    from pdfmath.mathml.serializer import to_mathml
    from pdfmath.parse.driver import parse

    work = str(tmp_path_factory.mktemp("mathml"))
    corpus = compile_expressions([e.to_tex() for e in MILESTONE], workdir=work)
    for page in extract_pages(corpus.pdf_path):
        tree, _ = parse(page.glyphs, page.rules)
        xml = to_mathml(tree, include_provenance=True)
        root = ElementTree.fromstring(xml)          # raises if malformed
        assert root.tag.endswith("math")
