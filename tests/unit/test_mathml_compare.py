"""Reading Presentation MathML back into a comparison signature."""

from pdfmath.eval.mathml_compare import mathml_signature, normalise_text, relax

NS = 'xmlns="http://www.w3.org/1998/Math/MathML"'


def sig(inner: str):
    return mathml_signature(f"<math {NS}>{inner}</math>")


def test_leaves():
    assert sig("<mi>x</mi>") == ("Identifier", "x")
    assert sig("<mn>42</mn>") == ("Number", "42")
    assert sig("<mo>+</mo>") == ("Operator", "+")


def test_structures():
    assert sig("<mfrac><mi>x</mi><mi>y</mi></mfrac>") == (
        "Fraction", (("Identifier", "x"), ("Identifier", "y")))
    assert sig("<msqrt><mi>y</mi></msqrt>") == ("Radical", (("Identifier", "y"),))
    assert sig("<msubsup><mi>x</mi><mi>i</mi><mn>2</mn></msubsup>") == (
        "SubSup", (("Identifier", "x"), ("Identifier", "i"), ("Number", "2")))


def test_a_slot_is_not_flattened_but_a_row_is():
    """mfrac's arguments are two boxes; flattening them would dissolve the fraction."""
    frac = sig("<mfrac><mrow><mi>x</mi><mo>+</mo><mn>1</mn></mrow><mi>y</mi></mfrac>")
    assert frac[0] == "Fraction" and len(frac[1]) == 2
    assert frac[1][0][0] == "Row"
    # ... whereas a row inside a row is just a row.
    assert sig("<mrow><mrow><mi>a</mi><mi>b</mi></mrow><mi>c</mi></mrow>") == (
        "Row", (("Identifier", "a"), ("Identifier", "b"), ("Identifier", "c")))


def test_invisible_operators_are_dropped():
    """A converter marks function application with U+2061; a page cannot show it."""
    assert sig("<mrow><mi>f</mi><mo>&#x2061;</mo><mi>x</mi></mrow>") == (
        "Row", (("Identifier", "f"), ("Identifier", "x")))


def test_a_fenced_row_becomes_a_delimited_group():
    out = sig("<mrow><mo>(</mo><mi>x</mi><mo>)</mo></mrow>")
    assert out == ("Delimited", "(", ")", (("Identifier", "x"),))


def test_tables():
    out = sig("<mtable><mtr><mtd><mi>a</mi></mtd><mtd><mi>b</mi></mtd></mtr></mtable>")
    assert out[0] == "Matrix"
    assert out[1][0][0] == "MatrixRow"


def test_mathematical_alphanumerics_fold_to_their_base_letter():
    """LaTeXML writes a differential as U+1D451; we see a cmmi glyph and write 'd'."""
    assert normalise_text("\U0001D451") == "d"


def test_relax_folds_what_a_page_cannot_record():
    mi = relax(("Identifier", "x"))
    mo = relax(("Operator", "x"))
    assert mi == mo == ("Token", "x")
    # ... and whether a word is one token or several is a convention.
    assert relax(("Identifier", "Ric")) == (
        "Row", (("Token", "R"), ("Token", "i"), ("Token", "c")))


def test_relax_canonicalises_accent_marks():
    """LaTeXML writes a combining macron; we write a spacing one."""
    combining = relax(("Accent", "̄", (("Identifier", "x"),)))
    spacing = relax(("Accent", "¯", (("Identifier", "x"),)))
    assert combining == spacing
    # An \overline is an mover over a bar either way.
    assert relax(("Overline", (("Identifier", "x"),))) == combining


def test_malformed_input_is_reported_not_raised():
    assert mathml_signature("<math") is None
    assert mathml_signature("") is None
