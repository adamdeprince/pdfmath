"""WordPerfect 5.1 equation-language serialisation.

Unlike the MathML, AsciiMath and OMML writers, this one has no independent reader to
check it against -- nothing available parses WordPerfect equations -- so these goldens
are the whole guarantee.  They are written against the grammar cited in
``pdfmath/wordperfect/serializer.py``.
"""

from pdfmath.tree.nodes import (Accent, Delimited, Fraction, Identifier, LargeOperator,
                                Lines, Matrix, MatrixCell, MatrixRow, Number, Operator,
                                Overline, Radical, Row, Space, SubSup, Subscript,
                                Superscript, Text, UnderOver, Underline, Unknown)
from pdfmath.wordperfect.serializer import UNVERIFIED, to_wpeq


def it(t):
    return Identifier(text=t, mathvariant="italic")


def wp(node):
    return to_wpeq(node).wpeq


def test_leaves_and_rows():
    assert wp(it("x")) == "x"
    assert wp(Row(children=[it("x"), Operator(text="+"), it("y")])) == "x + y"


def test_fraction_operands_are_always_braced():
    """WordPerfect braces group without printing, so bracing costs nothing and an
    unbraced ``a + 1 over b`` would divide only the 1."""
    assert wp(Fraction(children=[it("x"), it("y")])) == "{x} over {y}"
    assert wp(Fraction(children=[
        Row(children=[it("x"), Operator(text="+"), Number(text="1")]),
        it("y")])) == "{x + 1} over {y}"


def test_nested_fractions_nest():
    inner = Fraction(children=[it("a"), it("b")])
    assert wp(Fraction(children=[inner, it("c")])) == "{{a} over {b}} over {c}"


def test_scripts_use_the_keyword_form():
    assert wp(Superscript(children=[it("x"), Number(text="2")])) == "x sup 2"
    assert wp(Subscript(children=[it("x"), it("i")])) == "x sub i"
    assert wp(SubSup(children=[it("x"), it("i"),
                               Number(text="2")])) == "x sub i sup 2"


def test_a_compound_script_or_base_is_braced():
    inner = Superscript(children=[it("y"), Number(text="2")])
    assert wp(Superscript(children=[it("x"), inner])) == "x sup {y sup 2}"
    base = Superscript(children=[it("x"), Number(text="2")])
    assert wp(Subscript(children=[base, it("i")])) == "{x sup 2} sub i"


def test_roots():
    assert wp(Radical(children=[it("x")])) == "sqrt {x}"
    assert wp(Radical(children=[it("x"), it("n")])) == "nroot {n} {x}"


def test_limits_above_and_below_use_from_and_to():
    """``from``/``to`` is the editor's spelling for limits stacked on an operator;
    ``sub``/``sup`` puts them beside it.  We know from the page which happened."""
    s = UnderOver(has_under=True, has_over=True, children=[
        LargeOperator(text="∑", display=True),
        Row(children=[it("i"), Operator(text="="), Number(text="0")]),
        it("n")])
    assert wp(s) == "sum from {i = 0} to n"
    beside = SubSup(children=[LargeOperator(text="∫", display=False),
                              Number(text="0"), Number(text="1")])
    assert wp(beside) == "int sub 0 sup 1"


def test_a_fence_that_grew_uses_left_and_right():
    d = Delimited(open="(", close=")", stretchy=True, children=[
        Fraction(children=[it("x"), it("y")])])
    assert wp(d) == "left ( {x} over {y} right )"


def test_a_fence_that_did_not_grow_is_written_plainly():
    """``left``/``right`` grows a fence to fit.  A typed ``(`` did not grow, and the
    PDF says which one this was, so saying ``left (`` would change the page."""
    assert wp(Delimited(open="(", close=")", stretchy=False,
                        children=[it("x")])) == "( x )"


def test_left_and_right_stay_paired_when_one_side_is_absent():
    """The editor requires the pair, so a missing side becomes ``none``."""
    out = to_wpeq(Delimited(open="", close=")", stretchy=True, children=[it("x")]))
    assert out.wpeq == "left none x right )"
    assert "none" in out.unverified


def test_matrix_separates_columns_with_ampersand_and_rows_with_hash():
    m = Matrix(children=[
        MatrixRow(children=[MatrixCell(children=[it("a")]),
                            MatrixCell(children=[it("b")])]),
        MatrixRow(children=[MatrixCell(children=[it("c")]),
                            MatrixCell(children=[it("d")])])])
    assert wp(m) == "matrix {a & b # c & d}"
    assert wp(Delimited(open="(", close=")", stretchy=True,
                        children=[m])) == "left ( matrix {a & b # c & d} right )"


def test_a_barless_fraction_is_a_stack():
    b = Fraction(line_thickness=0.0, children=[it("n"), it("k")])
    assert wp(b) == "stack {n # k}"


def test_accents():
    assert wp(Accent(accent="^", children=[it("x")])) == "hat {x}"
    assert wp(Accent(accent="⃗", children=[it("x")])) == "vec {x}"
    assert wp(Overline(children=[it("x")])) == "overline {x}"
    assert wp(Underline(children=[it("x")])) == "underline {x}"


def test_the_two_space_widths():
    assert wp(Space(width_em=1.0)) == "~"
    assert wp(Space(width_em=0.16)) == "`"


def test_multi_letter_names_are_kept_upright_with_func():
    """Without ``func`` the editor italicises each letter as its own variable."""
    assert wp(Identifier(text="Ric", mathvariant="normal")) == "func Ric"
    assert wp(Identifier(text="sin", mathvariant="normal")) == "sin"


def test_greek_case_follows_the_letter():
    assert wp(it("α")) == "alpha"
    assert wp(Identifier(text="Γ", mathvariant="normal")) == "GAMMA"


def test_an_unknown_glyph_is_kept_and_reported():
    r = to_wpeq(Row(children=[it("x"), Unknown(text="", reason="no name")]))
    assert not r.ok and r.unreproducible == ["no name"]


def test_commands_without_a_citable_reference_are_reported():
    """The core grammar is sourced; the accent names are not, so they say so."""
    r = to_wpeq(Overline(children=[it("x")]))
    assert r.ok                       # it is still expressible
    assert r.unverified == ["overline"]
    assert "overline" in UNVERIFIED


def test_a_sourced_command_is_not_flagged():
    assert to_wpeq(Fraction(children=[it("x"), it("y")])).unverified == []
