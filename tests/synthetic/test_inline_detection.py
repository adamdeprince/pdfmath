r"""Finding mathematics inside a paragraph.

The two failure modes worth testing are opposite and both easy to fall into: missing a
formula because most of its characters are roman, and claiming one where the paragraph
merely contains a number.  Every case here is compiled by pdfTeX, so what is being tested
is a real page rather than a model of one.
"""

from __future__ import annotations

import subprocess
import tempfile
import os

import pytest

from pdfmath.corpus.compile import have_pdflatex
from pdfmath.detection import find_equations
from pdfmath.detection.inline import find_inline_math
from pdfmath.extraction.pdfminer_backend import extract_page
from pdfmath.fonts.mathparams import Style
from pdfmath.latex.serializer import to_latex
from pdfmath.parse.driver import parse_region

pytestmark = pytest.mark.skipif(not have_pdflatex(), reason="pdflatex is not installed")

DOCUMENT = r"""
\documentclass[11pt]{article}
\usepackage{amsmath,amssymb}
\pagestyle{empty}
\begin{document}
\noindent
Let $x$ be a point and let $f(x)$ denote its image under $f$.
We showed in 2024 that $n = 1$ holds whenever $x + y \le 3$ and
$\alpha \in \Omega$. Theorem 2.1 states that $\log n$ grows and
the set $[0,1]$ is compact. Write $\mathbf{v}$ for the vector.
Note $\sqrt{a^2+b^2}$ appears inline here.
\end{document}
"""


@pytest.fixture(scope="module")
def page(tmp_path_factory):
    out = tmp_path_factory.mktemp("inline")
    tex = out / "probe.tex"
    tex.write_text(DOCUMENT)
    subprocess.run(["pdflatex", "-interaction=batchmode",
                    f"-output-directory={out}", str(tex)],
                   capture_output=True, check=True)
    return extract_page(str(out / "probe.pdf"), 1)


@pytest.fixture(scope="module")
def found(page):
    """Each region's characters, in order, as one string."""
    by_id = {g.id: g for g in page.glyphs}
    return ["".join(by_id[i].unicode or "�" for i in r.glyph_ids)
            for r in find_inline_math(page)]


def test_a_lone_variable_is_found(found):
    """The commonest case of all, and the one a screen reader most often skips."""
    assert "x" in found


def test_roman_delimiters_come_along(found):
    """TeX sets the parentheses of $f(x)$ from the roman font, so a purely
    font-based rule would report ``f`` and ``x`` as two separate formulas."""
    assert "f(x)" in found


def test_a_relation_and_its_operand_are_one_formula(found):
    """``=`` and ``1`` are both roman; only the gap says they belong with ``n``."""
    assert "n=1" in found


def test_a_whole_inequality_is_one_formula(found):
    assert "x+y≤3" in found


def test_capital_greek_is_absorbed(found):
    """TeX sets upright capital Greek from the roman font, so it looks like prose."""
    assert "α∈Ω" in found


def test_an_operator_name_is_absorbed(found):
    """``log`` is three roman letters set as mathematics; the thin space gives it away."""
    assert "logn" in found


def test_a_formula_made_almost_entirely_of_roman_characters(found):
    """Only the comma in ``[0,1]`` comes from a math font.  It is enough."""
    assert "[0,1]" in found


def test_a_raised_radical_stays_with_its_line(found):
    r"""A radical sign hangs from a raised reference point, so its nearest *baseline*
    is the line above and only its *box* identifies the line it belongs to."""
    assert "√a2+b2" in found


def test_a_sentence_period_is_not_part_of_the_formula(found):
    r"""``$f$.`` puts the period hard against the ``f``, so no gap test separates them."""
    assert "f" in found
    assert "f." not in found


# ------------------------------------------------------------------ false positives

def test_a_year_in_prose_is_not_mathematics(found):
    assert not any("2024" in f for f in found)


def test_a_numbered_theorem_is_not_mathematics(found):
    assert not any("2.1" in f for f in found)


def test_no_region_contains_an_english_word(found):
    for text in found:
        for word in ("the", "and", "Write", "Theorem", "states", "compact"):
            assert word not in text, f"{text!r} swallowed prose"


def test_bold_text_is_left_alone_and_that_is_documented(found):
    r"""``$\mathbf{v}$`` is cmbx, and so is bold prose.  TeX threw the distinction
    away, so this is undecidable rather than merely hard, and is not guessed at."""
    assert "v" not in found


# --------------------------------------------------------------------- end to end

def test_every_region_parses_and_keeps_all_its_glyphs(page):
    """A region is only useful if the decompiler can read it."""
    for region in find_inline_math(page):
        src, tree, _ = parse_region(page, region.bbox, Style.TEXT)
        assert len(src.glyphs) == len(region.glyph_ids)
        assert tree.structural_confidence() > 0.9


def test_the_formulas_come_back_as_the_latex_that_made_them(page):
    latex = set()
    for region in find_inline_math(page):
        _, tree, _ = parse_region(page, region.bbox, Style.TEXT)
        latex.add(to_latex(tree).latex)
    assert r"\sqrt{a^{2} + b^{2}}" in latex
    assert r"\alpha \in \Omega" in latex
    assert "n = 1" in latex


def test_regions_are_marked_with_the_style_they_were_set_in(page):
    """Text style, not display: every Appendix G prediction differs between them."""
    assert all(r.style == "text" for r in find_inline_math(page))


def test_a_displayed_equation_is_not_reported_twice(tmp_path):
    """Inline detection is given the displays to avoid."""
    tex = tmp_path / "d.tex"
    tex.write_text(r"""
\documentclass[11pt]{article}\usepackage{amsmath}\pagestyle{empty}
\begin{document}
The identity is
\[ E = \frac{x_i^2}{\sqrt{y}} \]
and it holds for all $x$.
\end{document}
""")
    subprocess.run(["pdflatex", "-interaction=batchmode",
                    f"-output-directory={tmp_path}", str(tex)],
                   capture_output=True, check=True)
    page = extract_page(str(tmp_path / "d.pdf"), 1)
    regions = find_equations(page, inline=True)
    styles = sorted(r.style for r in regions)
    assert styles == ["display", "text"], "the display was reported twice, or missed"
    display = next(r for r in regions if r.style == "display")
    inline = next(r for r in regions if r.style == "text")
    assert not (display.bbox.overlap_x(inline.bbox) > 0
                and display.bbox.overlap_y(inline.bbox) > 0)
