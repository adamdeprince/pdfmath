"""Finding the mathematics on a page.

Two problems, not one.  A *displayed* equation is found by its shape: centred, set off,
with space above and below (:mod:`.equations`).  An *inline* formula has no shape at all
-- it is in the middle of a sentence -- and is found instead from TeX's own bookkeeping,
the fonts it switched to and the glue it inserted (:mod:`.inline`).

:func:`find_equations` runs both and hands back one list, displays first, with each
region carrying the math style its contents were set in.
"""

from __future__ import annotations

from typing import Optional

from ..extraction.model import PageExtract
from .equations import EquationRegion, find_displayed_equations
from .inline import find_inline_math

__all__ = ["EquationRegion", "find_displayed_equations", "find_inline_math",
           "find_equations"]


def find_equations(extract: PageExtract, inline: bool = True,
                   body_size: Optional[float] = None) -> list[EquationRegion]:
    """Every formula on the page: displayed always, inline on request.

    Inline detection is given the displayed regions to avoid, so an equation that was
    already found by its shape is not reported a second time by its fonts.
    """
    displayed = find_displayed_equations(extract)
    if not inline:
        return displayed
    return displayed + find_inline_math(
        extract, body_size=body_size, exclude=[r.bbox for r in displayed])
