"""PDF big points and TeX points are not the same unit, and the difference matters."""

from pdfmath.units import BP_PER_PT, PT_PER_BP, bp_to_pt, pt_to_bp, round_to_sp


def test_ten_tex_points_is_the_font_size_pdftex_writes():
    # pdfTeX writes "9.9626 Tf" for a 10 pt font: 10 pt = 10 * 72/72.27 bp.
    assert round(pt_to_bp(10.0), 4) == 9.9626


def test_round_trip():
    for v in (1.0, 9.9626, 72.0, 613.0):
        assert abs(bp_to_pt(pt_to_bp(v)) - v) < 1e-12


def test_ratio_is_the_inch_definition():
    assert abs(PT_PER_BP - 72.27 / 72.0) < 1e-15
    assert abs(BP_PER_PT * PT_PER_BP - 1.0) < 1e-15


def test_scaled_point_rounding():
    assert round_to_sp(1 / 3) == round((1 / 3) * 65536) / 65536
