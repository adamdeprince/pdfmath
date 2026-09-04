"""Inverting TeX's inter-atom glue table."""

from pdfmath.fonts.symbols import AtomClass
from pdfmath.parse.context import ParseContext
from pdfmath.parse.spacing import (MEDIUM, NONE, THICK, THIN, consistent_classes,
                                   expected_mu, observe)


def test_the_table_matches_the_texbook():
    assert expected_mu(AtomClass.ORD, AtomClass.BIN, False) == 4.0     # medium
    assert expected_mu(AtomClass.ORD, AtomClass.REL, False) == 5.0     # thick
    assert expected_mu(AtomClass.ORD, AtomClass.ORD, False) == 0.0
    assert expected_mu(AtomClass.OP, AtomClass.ORD, False) == 3.0      # thin
    # TeX puts nothing before a Punct atom and a thin space after it.
    assert expected_mu(AtomClass.ORD, AtomClass.PUNCT, False) == 0.0
    assert expected_mu(AtomClass.PUNCT, AtomClass.ORD, False) == 3.0


def test_parenthesised_entries_vanish_in_script_styles():
    assert expected_mu(AtomClass.ORD, AtomClass.BIN, script_style=True) == 0.0
    assert expected_mu(AtomClass.ORD, AtomClass.REL, script_style=True) == 0.0
    # An unparenthesised entry survives.
    assert expected_mu(AtomClass.OP, AtomClass.ORD, script_style=True) == 3.0


def test_impossible_pairs_are_reported_as_impossible():
    # TeX reclassifies a Bin that is next to a Rel, so the pair never occurs.
    assert expected_mu(AtomClass.BIN, AtomClass.REL, False) is None


def test_measured_gaps_land_on_the_table():
    ctx = ParseContext(text_size=10.0)
    quad = ctx.params.quad
    for gap_mu, name in ((0.0, "none"), (3.0, "thin"), (4.0, "medium"),
                         (5.0, "thick")):
        obs = observe(gap_mu * quad / 18.0, ctx)
        assert obs.name == name
        assert obs.is_clean


def test_author_spaces_are_whole_numbers_of_mu():
    ctx = ParseContext(text_size=10.0)
    quad = ctx.params.quad
    assert observe(18.0 * quad / 18.0, ctx).author_space == r"\quad"
    assert observe(3.0 * quad / 18.0, ctx).author_space == r"\,"
    assert observe(2.4 * quad / 18.0, ctx).author_space is None


def test_spacing_alone_constrains_the_atom_classes():
    ctx = ParseContext(text_size=10.0)
    obs = observe(5.0 * ctx.params.quad / 18.0, ctx)      # a thick space
    pairs = consistent_classes(obs, script_style=False)
    assert (AtomClass.ORD, AtomClass.REL) in pairs
    assert (AtomClass.ORD, AtomClass.BIN) not in pairs    # that would be medium
