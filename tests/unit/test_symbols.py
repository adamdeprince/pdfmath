"""Glyph names carry more than Unicode does."""

from pdfmath.fonts.symbols import AtomClass, Role, lookup


def test_large_operator_size_variants_share_a_base():
    text, display = lookup("summationtext"), lookup("summationdisplay")
    assert text.base == display.base == "summation"
    assert text.unicode == display.unicode == "∑"
    assert display.size_rank > text.size_rank
    assert text.role is Role.LARGE_OP and text.atom is AtomClass.OP


def test_sigma_the_letter_is_not_the_summation_operator():
    # This distinction is free from the glyph name and expensive from the image.
    assert lookup("Sigma").role is Role.SYMBOL
    assert lookup("Sigma").atom is AtomClass.ORD
    assert lookup("summationdisplay").role is Role.LARGE_OP


def test_delimiter_sizes_and_sides():
    for name, rank in (("parenleft", 0), ("parenleftbig", 1), ("parenleftBig", 2),
                       ("parenleftbigg", 3), ("parenleftBigg", 4)):
        s = lookup(name)
        assert s.base == "paren" and s.size_rank == rank
        assert s.role is Role.DELIM_OPEN and s.unicode == "("


def test_built_up_delimiter_pieces_keep_their_side_and_class():
    top = lookup("bracelefttp")
    assert top.role is Role.DELIM_PIECE and top.side == "left" and top.piece == "tp"
    assert top.atom is AtomClass.OPEN
    assert lookup("bracerightbt").atom is AtomClass.CLOSE


def test_radical_variants():
    assert lookup("radical").role is Role.RADICAL
    assert lookup("radicalBigg").size_rank == 4
    assert lookup("radicalvertex").piece == "ex"


def test_atom_classes_follow_plain_tex():
    assert lookup("plus").atom is AtomClass.BIN
    assert lookup("minus").atom is AtomClass.BIN
    assert lookup("equal").atom is AtomClass.REL
    assert lookup("lessequal").atom is AtomClass.REL
    assert lookup("comma").atom is AtomClass.PUNCT


def test_unknown_names_are_reported_not_dropped():
    s = lookup("nosuchglyph")
    assert s.unicode == "" and s.glyph == "nosuchglyph"
