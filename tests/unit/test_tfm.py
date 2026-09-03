"""The TFM reader, checked against values from the TeXbook and tftopl."""

import pytest

from pdfmath.fonts.mathparams import Style, params_for
from pdfmath.fonts.tfm import load_tfm

pytestmark = pytest.mark.skipif(load_tfm("cmr10") is None,
                                reason="no TeX installation with Computer Modern")


def test_design_sizes_and_coding_schemes():
    for name, scheme in (("cmr10", "TeX text"), ("cmmi10", "TeX math italic"),
                         ("cmsy10", "TeX math symbols"),
                         ("cmex10", "TeX math extension")):
        f = load_tfm(name)
        assert f.design_size == 10.0
        assert f.coding_scheme == scheme
        assert len(f.chars) == 128


def test_cmmi10_x_metrics():
    m = load_tfm("cmmi10").get(0x78)
    assert round(m.width, 6) == 0.571528
    assert round(m.height, 6) == 0.430555      # exactly the x-height
    assert m.depth == 0.0


def test_cmsy10_radical_hangs_below_the_baseline():
    # The surd's height is one rule thickness and its depth nearly a full em; a
    # recogniser that used ink extents would never predict where TeX put it.
    m = load_tfm("cmsy10").get(0x70)
    assert round(m.height, 3) == 0.040
    assert round(m.depth, 3) == 0.960


def test_math_symbol_font_has_22_parameters():
    f = load_tfm("cmsy10")
    assert f.is_math_symbol_font
    assert round(f.named_param("axis_height"), 5) == 0.25
    assert round(f.named_param("num1"), 5) == 0.67651
    assert round(f.named_param("sup2"), 5) == 0.36289


def test_math_extension_font_has_13_parameters():
    f = load_tfm("cmex10")
    assert f.is_math_extension_font
    assert round(f.named_param("default_rule_thickness"), 4) == 0.04
    assert round(f.named_param("big_op_spacing4"), 4) == 0.6


def test_charlist_walks_to_the_display_variant():
    ex = load_tfm("cmex10")
    # cmex's text summation has a larger display form; that chain is how we know
    # summationtext and summationdisplay are one operator at two sizes.
    chain = ex.charlist(0x50)
    assert chain[0] == 0x50 and 0x58 in chain


def test_extensible_recipe_for_a_tall_bracket():
    ex = load_tfm("cmex10")
    recipe = ex.extensible[0x30]          # parenlefttp
    assert recipe.top == 0x30 and recipe.bot == 0x40 and recipe.rep == 0x42


def test_rule_thickness_changes_with_style():
    # LaTeX loads cmex10 for text and script and cmex7 for scriptscript, so a nested
    # fraction bar is genuinely thinner.  Parsers that assume one value get this wrong.
    thick = [params_for(s, 10.0).default_rule_thickness()
             for s in (Style.TEXT, Style.SCRIPT, Style.SCRIPTSCRIPT)]
    assert [round(t, 3) for t in thick] == [0.400, 0.340, 0.243]
