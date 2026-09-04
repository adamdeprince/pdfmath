"""Serialising a recovered tree back to LaTeX."""

import pytest

from pdfmath.latex.serializer import to_latex
from pdfmath.tree.nodes import (Accent, Delimited, Fraction, Identifier, LargeOperator,
                                Matrix, MatrixCell, MatrixRow, Number, Operator,
                                Overline, Radical, Row, Space, SubSup, Subscript,
                                Superscript, UnderOver, Unknown)


def mi(t, glyph=None, font="CMMI10", variant="italic", atom="Ord"):
    return Identifier(text=t, glyph=glyph or t, font=font, mathvariant=variant,
                      atom=atom)


def mo(t, glyph, font="CMR10", atom="Bin"):
    return Operator(text=t, glyph=glyph, font=font, mathvariant="normal", atom=atom)


def test_letters_and_operators_come_from_latex_tables():
    row = Row(children=[mi("x"), mo("+", "plus"), mi("y")])
    assert to_latex(row).latex == "x + y"


def test_a_command_is_not_wrapped_in_an_alphabet():
    # cmr's "+" is a Bin; \mathrm{+} would be an Ord and the spacing would change.
    assert "\\mathrm" not in to_latex(mo("+", "plus")).latex


def test_greek_uses_its_own_command():
    assert to_latex(mi("α", "alpha")).latex == "\\alpha"
    # cmmi 0x0F is the lunate epsilon, which TeX calls \epsilon, not \varepsilon.
    assert to_latex(mi("ϵ", "epsilon1")).latex == "\\epsilon"
    assert to_latex(mi("ε", "epsilon")).latex == "\\varepsilon"


def test_blackboard_k_is_not_math_italic_k():
    """msbm's blackboard 'k' and cmmi's italic 'k' share a glyph name."""
    plain = to_latex(mi("k")).latex
    bb = to_latex(mi("R", "R", font="MSBM10", variant="double-struck")).latex
    assert plain == "k"
    assert bb == "\\mathbb{R}"


def test_structures():
    frac = Fraction(children=[mi("x"), mi("y")])
    assert to_latex(frac).latex == "\\frac{x}{y}"
    assert to_latex(Radical(children=[mi("x")])).latex == "\\sqrt{x}"
    assert to_latex(Radical(children=[mi("x"), mi("n")])).latex == "\\sqrt[n]{x}"
    assert to_latex(Superscript(children=[mi("x"), Number(text="2", glyph="two",
                                                          font="CMR10")])).latex \
        == "x^{2}"


def test_a_script_base_that_needs_bracing_gets_it():
    inner = Superscript(children=[mi("x"), Number(text="2", glyph="two", font="CMR10")])
    out = to_latex(Subscript(children=[inner, mi("i")])).latex
    assert out == "{{}x^{2}}_{i}"


def test_operator_limits_are_explicit():
    op = LargeOperator(text="∑", glyph="summationdisplay", font="CMEX10", display=True,
                       atom="Op")
    both = UnderOver(children=[op, mi("i"), mi("n")], has_under=True, has_over=True)
    assert to_latex(both).latex == "\\sum\\limits_{i}^{n}"
    # ... and an operator that took scripts instead has to say \nolimits, or display
    # style will move them under and over it.
    ints = LargeOperator(text="∫", glyph="integraldisplay", font="CMEX10", atom="Op")
    ss = SubSup(children=[ints, Number(text="0", glyph="zero", font="CMR10"),
                          Number(text="1", glyph="one", font="CMR10")])
    assert to_latex(ss).latex == "\\intop\\nolimits_{0}^{1}"


def test_stretchy_fences_use_left_and_right():
    stretched = Delimited(children=[mi("x")], open="(", close=")",
                          open_glyph="parenleftbig", close_glyph="parenrightbig",
                          stretchy=True)
    plain = Delimited(children=[mi("x")], open="(", close=")",
                      open_glyph="parenleft", close_glyph="parenright", stretchy=False)
    assert to_latex(stretched).latex == "\\left( x \\right)"
    assert to_latex(plain).latex == "( x )"


def test_measured_spaces_are_re_emitted_in_mu():
    row = Row(children=[mi("x"), Space(width_em=3.0 / 18.0), mi("d")])
    assert "\\mskip 3.000mu" in to_latex(row).latex


def test_an_ellipsis_goes_back_to_three_glyphs():
    dots = Operator(text="…", glyph=None, font="CMMI10", atom="Inner")
    assert to_latex(dots).latex == "\\ldots"


def test_matrix():
    cell = lambda t: MatrixCell(children=[mi(t)])  # noqa: E731
    m = Matrix(children=[MatrixRow(children=[cell("a"), cell("b")]),
                         MatrixRow(children=[cell("c"), cell("d")])])
    assert to_latex(m).latex == "\\begin{matrix} a & b \\\\ c & d \\end{matrix}"


def test_what_cannot_be_reproduced_is_reported_not_invented():
    r = to_latex(Row(children=[mi("x"), Unknown(text="", reason="rule with no material")]))
    assert not r.faithful
    assert "rule with no material" in r.unreproducible[0]
