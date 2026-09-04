"""Office MathML serialisation.

The structural cases are goldens; whether Word's own reader agrees is checked
independently in ``tests/synthetic/test_omml_agreement.py``.
"""

from xml.etree import ElementTree

import pytest

from pdfmath.omml.serializer import OMML_NS, to_omml
from pdfmath.tree.nodes import (Accent, Delimited, Fraction, Identifier, LargeOperator,
                                Lines, Matrix, MatrixCell, MatrixRow, Number, Operator,
                                Overline, Radical, Row, Space, SubSup, Subscript,
                                Superscript, Text, UnderOver, Underline, Unknown)

M = f"{{{OMML_NS}}}"


def it(t):
    return Identifier(text=t, mathvariant="italic")


def xml(node, **kw):
    return to_omml(node, indent=False, **kw).omml


def tree(node, **kw):
    return ElementTree.fromstring(xml(node, **kw))


def kinds(el):
    return [c.tag.replace(M, "m:") for c in el]


def test_output_is_well_formed_and_namespaced():
    root = tree(it("x"))
    assert root.tag == M + "oMath"


def test_display_wraps_in_a_paragraph_object():
    root = tree(it("x"), display=True)
    assert root.tag == M + "oMathPara"
    assert kinds(root) == ["m:oMath"]


def test_fraction_slots_are_in_order():
    root = tree(Fraction(children=[it("x"), it("y")]))
    f = root[0]
    assert kinds(f) == ["m:fPr", "m:num", "m:den"]
    assert f.find(f"{M}num/{M}r/{M}t").text == "x"
    assert f.find(f"{M}den/{M}r/{M}t").text == "y"


def test_a_barless_fraction_says_so():
    b = Fraction(line_thickness=0.0, children=[it("n"), it("k")])
    assert tree(b)[0].find(f"{M}fPr/{M}type").get(M + "val") == "noBar"


def test_scripts_use_the_matching_element():
    assert kinds(tree(Superscript(children=[it("x"), Number(text="2")]))) == ["m:sSup"]
    assert kinds(tree(Subscript(children=[it("x"), it("i")]))) == ["m:sSub"]
    assert kinds(tree(SubSup(children=[it("x"), it("i"),
                                       Number(text="2")]))) == ["m:sSubSup"]


def test_a_scripted_large_operator_becomes_an_n_ary():
    """Word has a dedicated object for these; a scripted run would not stretch."""
    s = UnderOver(has_under=True, has_over=True, children=[
        LargeOperator(text="∑", display=True),
        Row(children=[it("i"), Operator(text="="), Number(text="0")]),
        it("n")])
    n = tree(s)[0]
    assert n.tag == M + "nary"
    pr = n.find(M + "naryPr")
    assert pr.find(M + "chr").get(M + "val") == "∑"
    assert pr.find(M + "limLoc").get(M + "val") == "undOvr"
    assert pr.find(M + "subHide").get(M + "val") == "0"
    assert pr.find(M + "supHide").get(M + "val") == "0"


def test_an_inline_operator_puts_its_limits_beside_it():
    s = SubSup(children=[LargeOperator(text="∫", display=False),
                         Number(text="0"), Number(text="1")])
    assert tree(s)[0].find(f"{M}naryPr/{M}limLoc").get(M + "val") == "subSup"


def test_a_missing_limit_is_hidden_rather_than_empty():
    s = Subscript(children=[LargeOperator(text="∑", display=True), it("i")])
    pr = tree(s)[0].find(M + "naryPr")
    assert pr.find(M + "subHide").get(M + "val") == "0"
    assert pr.find(M + "supHide").get(M + "val") == "1"


def test_the_n_ary_operand_slot_is_left_empty():
    """TeX does not scope the operand inside ``\\sum``, so neither do we.

    Filling ``m:e`` would assert a grouping that is not in the source or the PDF.
    """
    s = Row(children=[
        Subscript(children=[LargeOperator(text="∑", display=True), it("i")]),
        Subscript(children=[it("x"), it("i")])])
    root = tree(s)
    assert kinds(root) == ["m:nary", "m:sSub"]
    assert list(root[0].find(M + "e")) == []


def test_radical_hides_its_degree_when_there_is_none():
    assert tree(Radical(children=[it("x")]))[0].find(
        f"{M}radPr/{M}degHide").get(M + "val") == "1"
    r = tree(Radical(children=[it("x"), it("n")]))[0]
    assert r.find(f"{M}radPr/{M}degHide").get(M + "val") == "0"
    assert r.find(f"{M}deg/{M}r/{M}t").text == "n"


def test_fences_are_always_stated():
    """``m:d`` defaults to parentheses, so brackets must say so explicitly."""
    d = tree(Delimited(open="[", close="]", children=[it("x")]))[0]
    pr = d.find(M + "dPr")
    assert pr.find(M + "begChr").get(M + "val") == "["
    assert pr.find(M + "endChr").get(M + "val") == "]"


def test_an_absent_fence_is_the_empty_string():
    """``\\left. x \\right)`` draws nothing on the left, which Word spells as ""."""
    d = tree(Delimited(open="", close=")", children=[it("x")]))[0]
    assert d.find(f"{M}dPr/{M}begChr").get(M + "val") == ""


def test_accents_and_bars():
    assert tree(Accent(accent="^", children=[it("x")]))[0].find(
        f"{M}accPr/{M}chr").get(M + "val") == "^"
    assert tree(Overline(children=[it("x")]))[0].find(
        f"{M}barPr/{M}pos").get(M + "val") == "top"
    assert tree(Underline(children=[it("x")]))[0].find(
        f"{M}barPr/{M}pos").get(M + "val") == "bot"


def test_matrix_declares_its_column_count():
    m = Matrix(children=[
        MatrixRow(children=[MatrixCell(children=[it("a")]),
                            MatrixCell(children=[it("b")])]),
        MatrixRow(children=[MatrixCell(children=[it("c")]),
                            MatrixCell(children=[it("d")])])])
    root = tree(m)[0]
    assert root.find(f"{M}mPr/{M}mcs/{M}mc/{M}mcPr/{M}count").get(M + "val") == "2"
    assert len(root.findall(M + "mr")) == 2


def test_display_lines_become_an_equation_array():
    ls = Lines(children=[it("x"), it("y")])
    assert kinds(tree(ls)) == ["m:eqArr"]


def test_style_is_stated_only_where_the_page_disagrees_with_word():
    """A run inside m:oMath is already italic and digits are already upright."""
    assert M + "rPr" not in xml(it("x"))
    assert M + "rPr" not in xml(Number(text="2"))
    assert M + "rPr" not in xml(Operator(text="+"))
    # An upright Greek capital from cmr has to say so.
    assert '<m:sty m:val="p"/>' in xml(Identifier(text="Γ", mathvariant="normal"))
    assert '<m:scr m:val="double-struck"/>' in xml(
        Identifier(text="R", mathvariant="double-struck"))


def test_prose_is_marked_as_ordinary_text():
    assert "<m:nor/>" in xml(Text(text="if"))


def test_an_unknown_glyph_is_kept_and_reported():
    r = to_omml(Row(children=[it("x"), Unknown(text="", reason="no name")]))
    assert not r.ok and r.unreproducible == ["no name"]
    assert "" in r.omml
