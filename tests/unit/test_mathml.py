"""Presentation MathML serialisation."""

from xml.etree import ElementTree

from pdfmath.mathml.serializer import to_mathml
from pdfmath.tree.nodes import (Accent, Delimited, Fraction, Identifier, LargeOperator,
                                Matrix, MatrixCell, MatrixRow, Number, Operator,
                                Provenance, Radical, Row, Space, SubSup, Superscript,
                                UnderOver, Unknown)


def _body(xml: str) -> str:
    return xml.replace("\n", "").replace("  ", "")


def test_structure_maps_one_to_one():
    # mathvariant is explicit here because a hand-built node has no font to read it
    # from; a parsed one always carries the family's variant.
    it = lambda t: Identifier(text=t, mathvariant="italic")  # noqa: E731
    tree = Fraction(children=[
        SubSup(children=[it("x"), it("i"), Number(text="2")]),
        Radical(children=[it("y")])])
    xml = _body(to_mathml(tree))
    assert "<mfrac>" in xml and "<msubsup>" in xml and "<msqrt>" in xml
    assert "<mi>x</mi>" in xml and "<mn>2</mn>" in xml


def test_mathvariant_only_when_it_differs_from_the_default():
    # A single-character mi defaults to italic, which is what cmmi gives us.
    assert "mathvariant" not in to_mathml(Identifier(text="x", mathvariant="italic"))
    # An upright capital Greek from cmr has to say so.
    assert 'mathvariant="normal"' in to_mathml(
        Identifier(text="Γ", mathvariant="normal"))
    # A multi-character token defaults to upright, so a function name needs nothing.
    assert "mathvariant" not in to_mathml(Identifier(text="sin", mathvariant="normal"))
    assert 'mathvariant="double-struck"' in to_mathml(
        Identifier(text="R", mathvariant="double-struck"))


def test_operators_are_not_italicised_by_their_font():
    # TeX draws the maths comma from cmmi; that is where the glyph lives, not a claim
    # that the punctuation is italic.
    assert "mathvariant" not in to_mathml(Operator(text=",", mathvariant="italic"))
    assert 'mathvariant="italic"' not in to_mathml(Operator(text="<", mathvariant="italic"))


def test_delimiters_report_whether_they_were_stretched():
    stretched = to_mathml(Delimited(children=[Identifier(text="x")], open="(",
                                    close=")", stretchy=True))
    plain = to_mathml(Delimited(children=[Identifier(text="x")], open="(",
                                close=")", stretchy=False))
    assert 'stretchy="true"' in stretched
    assert 'stretchy="false"' in plain


def test_under_over_picks_the_right_element():
    op = LargeOperator(text="∑", display=True)
    both = UnderOver(children=[op, Identifier(text="i"), Identifier(text="n")],
                     has_under=True, has_over=True)
    assert "<munderover" in to_mathml(both)
    under = UnderOver(children=[op, Identifier(text="i")], has_under=True)
    assert "<munder" in to_mathml(under)
    over = UnderOver(children=[op, Identifier(text="n")], has_over=True)
    assert "<mover" in to_mathml(over)


def test_matrix_becomes_a_table():
    cell = lambda t: MatrixCell(children=[Identifier(text=t)])  # noqa: E731
    m = Matrix(children=[MatrixRow(children=[cell("a"), cell("b")]),
                         MatrixRow(children=[cell("c"), cell("d")])])
    xml = _body(to_mathml(m))
    assert xml.count("<mtr>") == 2 and xml.count("<mtd>") == 4


def test_unknown_is_visible_not_silent():
    xml = to_mathml(Unknown(text="", reason="no Unicode for FOO code 7"))
    assert "pdfmath-unknown" in xml and "□" in xml


def test_provenance_attributes_are_opt_in():
    node = Identifier(text="x")
    node.prov = Provenance([3, 4], [], None, 0.98, {}, "leaf")
    assert "data-glyphs" not in to_mathml(node)
    with_prov = to_mathml(node, include_provenance=True)
    assert 'data-glyphs="3 4"' in with_prov and 'data-confidence="0.9800"' in with_prov


def test_spaces_are_emitted_as_mspace():
    row = Row(children=[Identifier(text="x"), Space(width_em=0.167),
                        Identifier(text="d")])
    assert '<mspace width="0.167em"/>' in _body(to_mathml(row))


def test_output_is_well_formed_xml():
    tree = Row(children=[
        Accent(children=[Identifier(text="x")], accent="^"),
        Operator(text="+"),
        Delimited(children=[Fraction(children=[Number(text="1"), Number(text="2")])],
                  open="(", close=")")])
    root = ElementTree.fromstring(to_mathml(tree))
    assert root.tag.endswith("math")
