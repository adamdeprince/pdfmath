"""Displayed-equation detection on a page that also contains prose.

Detection is deliberately not on the critical path -- ``--bbox`` bypasses it -- but it
has to be good enough that ``pdfmath extract`` on a real paper is useful, and the two
failure modes that matter are both testable: swallowing the surrounding paragraph, and
cutting a display in half by leaving out a line that is not itself math-heavy.
"""

from __future__ import annotations

import pytest

from pdfmath.corpus.compile import compile_expressions, have_pdflatex
from pdfmath.detection.equations import find_displayed_equations
from pdfmath.extraction.pdfminer_backend import extract_page

pytestmark = pytest.mark.skipif(not have_pdflatex(), reason="pdflatex is not installed")

PROSE = ("Let us consider the following identity, which appears in every treatment "
         "of the subject and is proved by a routine calculation that we omit here "
         "because it adds nothing at all to the discussion that follows below. ")

PREAMBLE = r"""
\documentclass[%(size)dpt]{article}
\usepackage{amsmath}
\usepackage{amssymb}
\pagestyle{empty}
\begin{document}
"""


@pytest.fixture(scope="module")
def page(tmp_path_factory):
    work = str(tmp_path_factory.mktemp("detect"))
    src = (PREAMBLE % {"size": 10}
           + PROSE * 3
           + r"\[ \frac{x_i^2}{\sqrt{y}} \]" + "\n"
           + PROSE * 3
           + r"\[ \sum_{i=0}^{n} a_i = b^{2} \]" + "\n"
           + PROSE * 2 + r" and inline $z^{2}+w$ within the sentence. " + PROSE
           + "\n\\end{document}\n")
    import os
    import subprocess
    tex = os.path.join(work, "page.tex")
    with open(tex, "w") as fh:
        fh.write(src)
    subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error",
                    "-output-directory", work, tex], capture_output=True, timeout=120)
    return extract_page(os.path.join(work, "page.pdf"), 1)


def test_finds_exactly_the_two_displays(page):
    regions = find_displayed_equations(page)
    assert len(regions) == 2, [r.evidence for r in regions]


def test_regions_do_not_swallow_the_paragraphs(page):
    regions = find_displayed_equations(page)
    for r in regions:
        # A display here is at most a couple of lines; a paragraph is far more glyphs.
        assert len(r.glyph_ids) < 60, r.evidence


def test_the_superscript_line_is_not_left_out(page):
    """The '2' of x_i^2 is a cmr7 digit on its own baseline with no math font on it."""
    regions = find_displayed_equations(page)
    from pdfmath.parse.driver import parse_page
    tree, _ = parse_page(page, regions[0].bbox)
    kinds = {n.kind for n in tree.walk()}
    assert "SubSup" in kinds and "Fraction" in kinds and "Radical" in kinds


def test_inline_mathematics_is_not_reported(page):
    for r in find_displayed_equations(page):
        # The inline z^2+w sits inside a full-width paragraph line.
        assert r.evidence["left_inset_ratio"] > 0.02 or \
               r.evidence["right_inset_ratio"] > 0.02


def test_every_region_is_decompilable(page):
    from pdfmath.parse.driver import parse_page
    for r in find_displayed_equations(page):
        tree, _ = parse_page(page, r.bbox)
        src = page.in_region(r.bbox)
        in_tree = {g for n in tree.walk() for g in n.prov.glyph_ids}
        assert {g.id for g in src.glyphs} <= in_tree
