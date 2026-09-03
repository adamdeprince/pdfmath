"""The project's central claim, as a test: TeX's layout is exactly invertible.

Each case compiles a formula with stock pdfTeX, measures the result, computes what
Appendix G says the measurement should be, and requires the residual to be smaller than
pdfTeX's own coordinate rounding.  If these ever start to drift, every recogniser built
on top of them is unsafe, so they are checked directly rather than only through the
end-to-end corpus.
"""

from __future__ import annotations

import pytest

from pdfmath.corpus.compile import compile_expressions, have_pdflatex
from pdfmath.extraction.pdfminer_backend import extract_page
from pdfmath.fonts.mathparams import Style, params_for

pytestmark = pytest.mark.skipif(not have_pdflatex(), reason="pdflatex is not installed")

#: pdfTeX writes coordinates with three decimals of a big point, so nothing can be
#: predicted more precisely than about a thousandth of a point.
TOL = 0.005


@pytest.fixture(scope="module")
def page(tmp_path_factory):
    work = str(tmp_path_factory.mktemp("appendixg"))

    def build(tex: str):
        c = compile_expressions([tex], workdir=work)
        return extract_page(c.pdf_path, 1)

    return build


def _by_glyph(extract, name):
    return [g for g in extract.glyphs if g.glyph_name == name]


def test_rule_18_superscript_only(page):
    p = page(r"x^{2}")
    x = _by_glyph(p, "x")[0]
    two = _by_glyph(p, "two")[0]
    params = params_for(Style.DISPLAY, 10.0)
    # Rule 18c: a bare character nucleus gives u = 0, so shift_up is the maximum of
    # sup1 (display style) and depth(script) + x_height/4.
    expected = max(0.0, params.sup1, two.depth + params.x_height / 4)
    assert abs((two.y - x.y) - expected) < TOL


def test_rule_18_subscript_only(page):
    p = page(r"x_{i}")
    x = _by_glyph(p, "x")[0]
    i = _by_glyph(p, "i")[0]
    params = params_for(Style.DISPLAY, 10.0)
    expected = max(0.0, params.sub1, i.height - 0.8 * params.x_height)
    assert abs((x.y - i.y) - expected) < TOL


def test_rule_18f_clearance_between_the_two_scripts(page):
    p = page(r"x_{i}^{2}")
    x = _by_glyph(p, "x")[0]
    two, i = _by_glyph(p, "two")[0], _by_glyph(p, "i")[0]
    params = params_for(Style.DISPLAY, 10.0)
    theta = params.default_rule_thickness()

    shift_up = max(0.0, params.sup1, two.depth + params.x_height / 4)
    shift_down = max(0.0, params.sub2)
    gap = (shift_up - two.depth) - (i.height - shift_down)
    if gap < 4 * theta:
        shift_down += 4 * theta - gap
        psi = 0.8 * params.x_height - (shift_up - two.depth)
        if psi > 0:
            shift_up += psi
            shift_down -= psi
    assert abs((two.y - x.y) - shift_up) < TOL
    assert abs((x.y - i.y) - shift_down) < TOL
    # The clearance between the two scripts is *at least* 4*theta -- rule 18f enforces a
    # minimum, not an equality.  That guarantee is what lets the parser split a script
    # cluster into its superscript and subscript halves without a tuned threshold.
    assert ((two.y - two.depth) - (i.y + i.height)) >= 4 * theta - TOL


def test_superscript_is_displaced_by_the_italic_correction(page):
    p = page(r"f^{2}")
    f = _by_glyph(p, "f")[0]
    two = _by_glyph(p, "two")[0]
    assert f.italic > 0.5                      # cmmi's f has a large italic correction
    assert abs(two.x - (f.x + f.width + f.italic)) < TOL


def test_subscript_is_not_displaced_but_the_superscript_is(page):
    p = page(r"f_{i}^{2}")
    f = _by_glyph(p, "f")[0]
    assert abs(_by_glyph(p, "i")[0].x - (f.x + f.width)) < TOL
    assert abs(_by_glyph(p, "two")[0].x - (f.x + f.width + f.italic)) < TOL


def test_rule_15_fraction(page):
    p = page(r"\frac{x}{y}")
    x, y = _by_glyph(p, "x")[0], _by_glyph(p, "y")[0]
    bar = p.rules[0]
    params = params_for(Style.DISPLAY, 10.0)
    assert abs(bar.thickness - params.default_rule_thickness()) < TOL
    baseline = bar.y_center - params.axis_height
    assert abs((x.y - baseline) - params.num1) < TOL
    assert abs((baseline - y.y) - params.denom1) < TOL
    # The bar is exactly as wide as the wider of the two parts.
    assert abs(bar.width - max(x.width, y.width)) < 0.05


def test_rule_11_radical_clearance(page):
    p = page(r"\sqrt{y}")
    y = _by_glyph(p, "y")[0]
    surd = [g for g in p.glyphs if g.glyph_name == "radical"][0]
    overbar = max(p.rules, key=lambda r: r.bbox.y1)
    params = params_for(Style.DISPLAY, 10.0)
    theta = params.default_rule_thickness()

    clr = theta + abs(params.x_height) / 4          # display style
    delta = surd.depth - (y.height + y.depth + clr)
    if delta > 0:
        clr += delta / 2
    assert abs((overbar.bbox.y0 - (y.y + y.height)) - clr) < TOL
    assert abs(overbar.thickness - theta) < TOL
    # The bar starts where the surd ends and their tops agree: that is how they are
    # re-associated, and it is exact rather than approximate.
    assert abs(overbar.bbox.x0 - (surd.x + surd.width)) < TOL
    assert abs(overbar.bbox.y1 - (surd.y + surd.height)) < TOL


def test_rule_13_operator_is_centred_on_the_axis(page):
    p = page(r"\int_{0}^{1} x")
    integral = [g for g in p.glyphs if g.role.name == "LARGE_OP"][0]
    x = _by_glyph(p, "x")[0]
    params = params_for(Style.DISPLAY, 10.0)
    shift = 0.5 * (integral.height - integral.depth) - params.axis_height
    # Undoing the shift recovers the line's baseline, which "x" sits on.
    assert abs((integral.y + shift) - x.y) < TOL


def test_limits_use_big_op_spacing(page):
    p = page(r"\sum_{i}^{n} x")
    op = [g for g in p.glyphs if g.role.name == "LARGE_OP"][0]
    n = _by_glyph(p, "n")[0]
    i = _by_glyph(p, "i")[0]
    params = params_for(Style.DISPLAY, 10.0)
    up = max(params.big_op_spacing(3) - n.depth, params.big_op_spacing(1))
    down = max(params.big_op_spacing(4) - i.height, params.big_op_spacing(2))
    assert abs(((n.y - n.depth) - (op.y + op.height)) - up) < TOL
    assert abs(((op.y - op.depth) - (i.y + i.height)) - down) < TOL


def test_rule_12_accent_sits_on_the_nucleus_baseline(page):
    p = page(r"\hat{x}")
    x = _by_glyph(p, "x")[0]
    hat = _by_glyph(p, "circumflex")[0]
    params = params_for(Style.DISPLAY, 10.0)
    delta = min(x.height, params.x_height)
    assert abs(hat.y - (x.y + x.height - delta)) < TOL
    # Horizontally the accent is centred *plus* the font's skew kern between the nucleus
    # and cmmi's skewchar, which we do not read out of the lig/kern program.  It is
    # small and bounded, and the recogniser treats it as evidence rather than a
    # constraint (see accents.py); the baseline above is the exact test.
    skew = hat.x - (x.x + 0.5 * (x.width - hat.width))
    assert 0 <= skew < 0.1 * 10.0


def test_inter_atom_glue_matches_the_spacing_table(page):
    from pdfmath.parse.context import ParseContext
    from pdfmath.parse.spacing import observe

    ctx = ParseContext(text_size=10.0)
    # (source, gap index, expected class).  TeX's table is asymmetric: it puts nothing
    # before a Punct atom and a thin space after it, which is why the comma is checked
    # on its right-hand side.
    cases = [(r"x + y", 0, "medium"), (r"x + y", 1, "medium"),
             (r"x = y", 0, "thick"), (r"x = y", 1, "thick"),
             (r"x y", 0, "none"),
             (r"x , y", 0, "none"), (r"x , y", 1, "thin")]
    for tex, k, expect in cases:
        p = page(tex)
        gs = sorted(p.glyphs, key=lambda g: g.x)
        gap = gs[k + 1].bbox.x0 - gs[k].bbox.x1
        obs = observe(gap, ctx)
        assert obs.name == expect, f"{tex} gap {k}: {gap:.4f} pt -> {obs.name}"
        assert obs.is_clean, f"{tex}: {obs.residual_mu:.3f} mu off an exact TeX space"
