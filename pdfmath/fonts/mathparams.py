"""The Appendix G parameters, gathered per *style* rather than per font.

TeX's layout rules read parameters out of the current family-2 (symbol) and family-3
(extension) fonts *at the size of the current style*.  In a 10 pt document that means
cmsy10 for text and display style, cmsy7 for script style, cmsy5 for scriptscript.  This
module hides that lookup behind a style name so the recognisers can just ask for
``params.sup1``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Optional

from .tfm import TfmFont, load_tfm


class Style(IntEnum):
    """TeX's eight math styles.  Even values are uncramped, odd are cramped."""

    DISPLAY = 0
    DISPLAY_CRAMPED = 1
    TEXT = 2
    TEXT_CRAMPED = 3
    SCRIPT = 4
    SCRIPT_CRAMPED = 5
    SCRIPTSCRIPT = 6
    SCRIPTSCRIPT_CRAMPED = 7

    @property
    def cramped(self) -> bool:
        return bool(self & 1)

    @property
    def is_display(self) -> bool:
        return self in (Style.DISPLAY, Style.DISPLAY_CRAMPED)

    def sup_style(self) -> "Style":
        """The style superscripts are set in (TeXbook, rule for ``\\sup``)."""
        base = Style.SCRIPT if self < Style.SCRIPT else Style.SCRIPTSCRIPT
        return Style(int(base) + (int(self) & 1))

    def sub_style(self) -> "Style":
        """Subscripts use the cramped variant of the superscript style."""
        return Style(int(self.sup_style()) | 1)

    def cramp(self) -> "Style":
        return Style(int(self) | 1)

    def numerator_style(self) -> "Style":
        return Style(max(int(Style.TEXT), (int(self) & ~1) + 2) + (int(self) & 1)) \
            if self < Style.SCRIPTSCRIPT else self

    def denominator_style(self) -> "Style":
        return self.numerator_style().cramp()

    @property
    def size_ratio(self) -> float:
        """Font size of this style relative to the text size, as a *fallback*.

        These are the ratios for a 10 pt document.  They are not universal: LaTeX's
        ``\\DeclareMathSizes`` gives 12/8/6 at 12 pt, so the script ratio there is 2/3,
        not 7/10.  Where the sizes can be read off the page -- which is almost always --
        :class:`~pdfmath.parse.context.ParseContext` uses those instead.
        """
        if self < Style.SCRIPT:
            return 1.0
        if self < Style.SCRIPTSCRIPT:
            return 0.7
        return 0.5


@dataclass
class MathParams:
    """sigma_1..sigma_22 and xi_1..xi_13, in points, for a given style and text size."""

    symbol_font: Optional[TfmFont]
    extension_font: Optional[TfmFont]
    size: float                       # the size the *style* is set at, in pt

    # -- sigma (from the family-2 font, scaled to `size`) -------------------------
    def _s(self, name: str, fallback: float) -> float:
        if self.symbol_font is None:
            return fallback * self.size
        return self.symbol_font.named_param(name, fallback) * self.size

    @property
    def x_height(self) -> float: return self._s("x_height", 0.430555)
    @property
    def quad(self) -> float: return self._s("quad", 1.0)
    @property
    def num1(self) -> float: return self._s("num1", 0.676508)
    @property
    def num2(self) -> float: return self._s("num2", 0.393732)
    @property
    def num3(self) -> float: return self._s("num3", 0.443731)
    @property
    def denom1(self) -> float: return self._s("denom1", 0.685951)
    @property
    def denom2(self) -> float: return self._s("denom2", 0.344841)
    @property
    def sup1(self) -> float: return self._s("sup1", 0.412892)
    @property
    def sup2(self) -> float: return self._s("sup2", 0.362892)
    @property
    def sup3(self) -> float: return self._s("sup3", 0.288889)
    @property
    def sub1(self) -> float: return self._s("sub1", 0.15)
    @property
    def sub2(self) -> float: return self._s("sub2", 0.247217)
    @property
    def sup_drop(self) -> float: return self._s("sup_drop", 0.386108)
    @property
    def sub_drop(self) -> float: return self._s("sub_drop", 0.05)
    @property
    def delim1(self) -> float: return self._s("delim1", 2.39)
    @property
    def delim2(self) -> float: return self._s("delim2", 1.01)
    @property
    def axis_height(self) -> float: return self._s("axis_height", 0.25)

    # -- xi (from the family-3 font; NB always at *text* size in TeX) --------------
    def _x(self, name: str, fallback: float, size: float) -> float:
        if self.extension_font is None:
            return fallback * size
        return self.extension_font.named_param(name, fallback) * size

    def default_rule_thickness(self, at: Optional[float] = None) -> float:
        return self._x("default_rule_thickness", 0.04, at if at is not None else self.size)

    def big_op_spacing(self, i: int, at: Optional[float] = None) -> float:
        fallback = {1: 0.111111, 2: 0.166667, 3: 0.2, 4: 0.6, 5: 0.1}[i]
        return self._x(f"big_op_spacing{i}", fallback,
                       at if at is not None else self.size)


def params_for(style: Style, text_size: float = 10.0,
               symbol_family: str = "cmsy", extension_family: str = "cmex",
               size: Optional[float] = None) -> MathParams:
    """Load the parameters TeX would have used for ``style`` in a ``text_size`` document.

    Both the family-2 and family-3 fonts are chosen at the *style's* size, following
    LaTeX's own size ranges for the Computer Modern families.  This matters: a fraction
    bar in script style comes out 0.34 pt thick rather than 0.40, because LaTeX's
    ``scriptfont3`` is cmex7, and a parser that assumed a single rule thickness would
    misjudge every nested fraction.
    """
    size = text_size * style.size_ratio if size is None else size
    sym = _load_at(symbol_family, size)
    ext = _load_at(extension_family, size)
    return MathParams(sym, ext, size)


#: LaTeX's ``\DeclareFontShape`` size ranges: (upper bound exclusive, design size).
#: A font is used *scaled to the requested size*, so only the metrics change, not the em.
_SIZE_RANGES = {
    "cmr":   [(6.0, 5), (8.0, 7), (None, 10)],
    "cmmi":  [(6.0, 5), (8.0, 7), (None, 10)],
    "cmsy":  [(6.0, 5), (8.0, 7), (None, 10)],
    "cmbsy": [(6.0, 5), (8.0, 7), (None, 10)],
    "cmmib": [(6.0, 5), (8.0, 7), (None, 10)],
    "cmex":  [(7.5, 7), (8.5, 8), (9.5, 9), (None, 10)],
    "lmsy":  [(6.0, 5), (8.0, 7), (None, 10)],
    "lmmi":  [(6.0, 5), (8.0, 7), (None, 10)],
    "lmex":  [(None, 10)],
}


def design_size_for(family: str, at: float) -> int:
    """Which design size of ``family`` LaTeX loads when asked for ``at`` points."""
    for upper, design in _SIZE_RANGES.get(family, [(None, 10)]):
        if upper is None or at < upper:
            return design
    return 10


def _load_at(family: str, size: float) -> Optional[TfmFont]:
    return (load_tfm(f"{family}{design_size_for(family, size)}")
            or load_tfm(f"{family}10"))
