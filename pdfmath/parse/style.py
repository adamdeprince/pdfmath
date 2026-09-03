"""Recovering the math *style* a sub-expression was set in.

TeX's layout rules are all parameterised by style, so a decompiler that assumes one style
throughout will use the wrong ``num1``, the wrong ``sup2`` and the wrong rule thickness as
soon as it looks inside a superscript.  The style is not written in the PDF, but it is
over-determined by things that are:

* **font size** -- text and display style use the text size, script style 0.7 of it,
  scriptscript 0.5;
* **rule thickness** -- LaTeX loads cmex10 for text and script and cmex7 for
  scriptscript, so a fraction bar is 0.400 pt, 0.340 pt or 0.243 pt in a 10 pt document,
  three values that cannot be confused;
* **which cmex variant a large operator uses** -- ``summationdisplay`` only appears in
  display style.

Display and text style share every font size and every parameter *except* num1/num2,
denom1/denom2, sup1/sup2 and the radical clearance, so they are separated by the
placement residual rather than by size (see fractions.verify).
"""

from __future__ import annotations

from typing import Optional

from ..fonts.mathparams import Style, params_for

#: The four style sizes, in units of the document's text size.
_SIZE_RATIOS = [(Style.DISPLAY, 1.0), (Style.TEXT, 1.0),
                (Style.SCRIPT, 0.7), (Style.SCRIPTSCRIPT, 0.5)]


def style_for_size(size: float, text_size: float,
                   prefer: Optional[Style] = None) -> Style:
    """The style whose font size is ``size``.

    ``prefer`` breaks the display/text tie, which font size alone cannot.
    """
    ratio = size / max(text_size, 1e-6)
    best = min(_SIZE_RATIOS[1:], key=lambda sr: abs(sr[1] - ratio))
    if best[0] is Style.TEXT and prefer is not None and prefer.is_display:
        return Style.DISPLAY
    return best[0]


def style_from_rule_thickness(thickness: float, text_size: float,
                              prefer: Optional[Style] = None) -> Style:
    """The style whose ``default_rule_thickness`` is ``thickness``.

    This is the sharpest signal available for a fraction, because it does not depend on
    what the numerator happens to contain.
    """
    scored = []
    for style in (Style.TEXT, Style.SCRIPT, Style.SCRIPTSCRIPT):
        theta = params_for(style, text_size).default_rule_thickness()
        scored.append((abs(theta - thickness), style))
    best = min(scored)[1]
    if best is Style.TEXT and prefer is not None and prefer.is_display:
        return Style.DISPLAY
    return best


def numerator_style_of(observed_numerator_size: float, text_size: float) -> Style:
    """The style of a fraction whose numerator was set at ``observed_numerator_size``."""
    for style in (Style.DISPLAY, Style.TEXT, Style.SCRIPT, Style.SCRIPTSCRIPT):
        expected = text_size * style.numerator_style().size_ratio
        if abs(expected - observed_numerator_size) < 0.05 * text_size:
            return style
    return Style.TEXT
