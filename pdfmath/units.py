"""Unit conversions.

PDF user space is measured in *big points* (bp), 1/72 inch.  TeX measures in *printer's
points* (pt), 1/72.27 inch.  They differ by 0.375%, which is small enough to look like
noise and large enough to wreck a comparison against TFM data: a 10 pt font is reported
by the PDF as size 9.9626.

Everything inside pdfmath above the extraction boundary is in TeX points, measured from
the page's bottom-left corner with y increasing upwards (PDF's own convention).  Convert
once, at the boundary, and never think about it again.
"""

from __future__ import annotations

PT_PER_BP = 72.27 / 72.0     # 1.00375
BP_PER_PT = 72.0 / 72.27     # 0.996264

#: TeX's internal unit; 1 pt = 65536 sp.  Useful when reproducing TeX's rounding.
SP_PER_PT = 65536


def bp_to_pt(v: float) -> float:
    """PDF big points -> TeX points."""
    return v * PT_PER_BP


def pt_to_bp(v: float) -> float:
    """TeX points -> PDF big points."""
    return v * BP_PER_PT


def round_to_sp(v_pt: float) -> float:
    """Round a length in pt to TeX's internal resolution (scaled points).

    TeX's arithmetic is exact in sp, so a quantity we *predict* should agree with a
    quantity we *measured* to within a couple of sp plus the PDF's own decimal rounding.
    """
    return round(v_pt * SP_PER_PT) / SP_PER_PT
