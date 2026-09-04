"""AsciiMath serialisation.

The cases that matter are the ones where AsciiMath's bracket-consumption rules make a
naive rendering say something the page did not.
"""

from pdfmath.asciimath.serializer import to_asciimath
from pdfmath.tree.nodes import (Accent, Delimited, Fraction, Identifier, LargeOperator,
                                Matrix, MatrixCell, MatrixRow, Number, Operator,
                                Overline, Radical, Row, Space, SubSup, Subscript,
                                Superscript, Text, UnderOver, Underline, Unknown)


def it(t):
    return Identifier(text=t, mathvariant="italic")


def am(node):
    return to_asciimath(node).asciimath


def test_leaves_and_rows():
    assert am(it("x")) == "x"
    assert am(Row(children=[it("x"), Operator(text="+"), it("y")])) == "x + y"
    assert am(Number(text="42")) == "42"


def test_greek_and_symbols_use_their_keywords():
    assert am(it("α")) == "alpha"
    assert am(Operator(text="≤")) == "<="
    assert am(Operator(text="∞")) == "oo"
    assert am(Operator(text="∈")) == "in"
    # U+2212 MINUS SIGN is what the PDF holds; AsciiMath spells it with a hyphen.
    assert am(Operator(text="−")) == "-"


def test_fraction_operands_are_always_bracketed():
    """``a/b`` alone is fine, but the rule has to hold for compounds too, and a reader
    cannot tell which case they are looking at from the output.  Bracket both, always."""
    assert am(Fraction(children=[it("x"), it("y")])) == "(x)/(y)"
    assert am(Fraction(children=[
        Row(children=[it("x"), Operator(text="+"), Number(text="1")]),
        it("y")])) == "(x + 1)/(y)"


def test_nested_fractions_nest():
    inner = Fraction(children=[it("a"), it("b")])
    assert am(Fraction(children=[inner, it("c")])) == "((a)/(b))/(c)"


def test_single_token_scripts_are_left_unbracketed():
    assert am(Superscript(children=[it("x"), Number(text="2")])) == "x^2"
    assert am(Subscript(children=[it("x"), it("i")])) == "x_i"
    assert am(SubSup(children=[it("x"), it("i"), Number(text="2")])) == "x_i^2"


def test_compound_scripts_are_bracketed():
    inner = Superscript(children=[it("y"), Number(text="2")])
    assert am(Superscript(children=[it("x"), inner])) == "x^(y^2)"


def test_a_compound_base_is_grouped_invisibly():
    """``^`` and ``_`` eat what *follows* them, so a bracket before one is printed.

    ``(x^2)_i`` would assert parentheses the page never showed; ``{: :}`` groups without
    drawing anything, which is what the TeX group did.
    """
    base = Superscript(children=[it("x"), Number(text="2")])
    assert am(Subscript(children=[base, it("i")])) == "{:x^2:}_i"
    frac = Fraction(children=[it("a"), it("b")])
    assert am(Subscript(children=[frac, it("i")])) == "{:(a)/(b):}_i"


def test_brackets_that_were_really_printed_survive():
    """A parenthesised numerator keeps its own pair: the outer one is eaten by ``/``."""
    d = Delimited(open="(", close=")", children=[it("x")])
    assert am(d) == "(x)"
    assert am(Fraction(children=[d, it("y")])) == "((x))/(y)"


def test_radicals():
    assert am(Radical(children=[it("x")])) == "sqrt(x)"
    assert am(Radical(children=[it("x"), it("n")])) == "root(n)(x)"


def test_large_operators_carry_their_limits():
    s = UnderOver(has_under=True, has_over=True, children=[
        LargeOperator(text="∑", display=True),
        Row(children=[it("i"), Operator(text="="), Number(text="0")]),
        it("n")])
    assert am(s) == "sum_(i = 0)^n"


def test_fences():
    assert am(Delimited(open="[", close="]", children=[it("x")])) == "[x]"
    assert am(Delimited(open="⟨", close="⟩", children=[it("x")])) == "(:x:)"
    assert am(Delimited(open="|", close="|", children=[it("x")])) == "|x|"


def test_an_absent_fence_becomes_an_invisible_one():
    """``\\left. ... \\right)`` has nothing on the left; AsciiMath still needs a pair."""
    assert am(Delimited(open="", close=")", children=[it("x")])) == "{:x)"


def test_accents():
    assert am(Accent(accent="^", children=[it("x")])) == "hat(x)"
    assert am(Accent(accent="⃗", children=[it("x")])) == "vec(x)"
    assert am(Overline(children=[Row(children=[
        it("x"), Operator(text="+"), it("y")])])) == "bar(x + y)"
    assert am(Underline(children=[it("x")])) == "ul(x)"


def test_matrices_take_their_brackets_from_the_fence():
    m = Matrix(children=[
        MatrixRow(children=[MatrixCell(children=[it("a")]),
                            MatrixCell(children=[it("b")])]),
        MatrixRow(children=[MatrixCell(children=[it("c")]),
                            MatrixCell(children=[it("d")])])])
    assert am(Delimited(open="(", close=")", children=[m])) == "((a,b),(c,d))"
    assert am(Delimited(open="[", close="]", children=[m])) == "[(a,b),(c,d)]"


def test_a_barless_fraction_is_a_stack_not_a_division():
    """``\\binom`` has no rule, so writing it as ``a/b`` would invent a division."""
    b = Fraction(line_thickness=0.0, children=[it("n"), it("k")])
    assert am(b) == "((n),(k))"


def test_an_unknown_glyph_is_kept_and_reported():
    r = to_asciimath(Row(children=[it("x"), Unknown(text="", reason="no name")]))
    assert not r.ok
    assert "" in r.asciimath
    assert r.unreproducible == ["no name"]


def test_punctuation_does_not_float():
    """The text itself is what a magnifying reader reads, so ``x , y`` is a defect."""
    assert am(Row(children=[it("x"), Operator(text=","), it("y")])) == "x, y"


def test_prose_becomes_a_text_run():
    assert am(Text(text="if")) == "text(if)"
    assert am(Identifier(text="sin", mathvariant="normal")) == "sin"
    assert am(Identifier(text="Ric", mathvariant="normal")) == "text(Ric)"
