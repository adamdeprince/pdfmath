"""Recognising a TeX font from the name the PDF gives us."""

import pytest

from pdfmath.fonts.metrics import FontMetrics
from pdfmath.fonts.normalize import glyph_name, identify
from pdfmath.fonts.tfm import load_tfm


def test_subset_prefix_is_stripped():
    assert identify("FFANCX+CMMI10").base_name == "CMMI10"


@pytest.mark.parametrize("name,family,size,encoding", [
    ("CMR7", "cmr", 7.0, "OT1"),
    ("CMMI10", "cmmi", 10.0, "OML"),
    ("CMSY10", "cmsy", 10.0, "OMS"),
    ("CMEX10", "cmex", 10.0, "OMX"),
    ("MSBM10", "msbm", 10.0, "AMSB"),
    ("LMRoman10-Regular", "lmr", 10.0, "OT1"),
    ("LMMathItalic10-Regular", "lmmi", 10.0, "OML"),
])
def test_families(name, family, size, encoding):
    i = identify(name)
    assert (i.family, i.design_size, i.encoding) == (family, size, encoding)


def test_unknown_font_is_reported_as_unknown_not_guessed():
    i = identify("Helvetica")
    assert i.family is None and i.encoding is None and not i.is_tex_font


def test_encoding_beats_tounicode():
    # The glyph name comes from the font family's own encoding, so a missing or wrong
    # ToUnicode map costs nothing.
    assert glyph_name(identify("CMMI10"), 0x78) == "x"
    assert glyph_name(identify("CMSY10"), 0x70) == "radical"
    assert glyph_name(identify("CMEX10"), 0x58) == "summationdisplay"


def test_mathvariant_follows_the_family():
    assert identify("CMMI10").mathvariant == "italic"
    assert identify("CMR10").mathvariant == "normal"
    assert identify("MSBM10").mathvariant == "double-struck"
    assert identify("EUFM10").mathvariant == "fraktur"
    assert identify("CMSY10").has_script_capitals


@pytest.mark.skipif(load_tfm("cmmi10") is None, reason="no TeX installation")
def test_lookup_scales_metrics_to_the_size_used():
    g = FontMetrics.lookup("ABCDEF+CMMI10", 0x78, 10.0)
    assert g.glyph == "x" and g.unicode == "x"
    assert round(g.metrics.width, 4) == 5.7153
    assert g.metrics.source == "tfm"
    half = FontMetrics.lookup("ABCDEF+CMMI10", 0x78, 5.0)
    assert abs(half.metrics.width * 2 - g.metrics.width) < 1e-9


@pytest.mark.skipif(load_tfm("cmex10") is None, reason="no TeX installation")
def test_extensible_pieces_come_from_the_tfm():
    pieces = FontMetrics.extensible_pieces("CMEX10")
    assert 0x0C in pieces          # vextendsingle repeats itself for a tall bar
    assert 0x3E in pieces          # braceex
    assert 0x00 not in pieces      # code 0 means "no piece"
