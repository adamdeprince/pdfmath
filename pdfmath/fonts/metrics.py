"""``FontMetrics.lookup(font, glyph)`` -- the TeX metric API for the rest of the system.

Every geometric decision the parser makes should go through here rather than measuring
ink.  The distinction matters: TeX positions boxes using TFM *width / height / depth*,
which are frequently not the ink extent at all.  cmsy10's ``radical`` has height 0.04 and
depth 0.96 -- a box hanging almost entirely below the baseline -- and cmex10's operators
are declared with the depth that makes vertical centring on the axis come out right.
Measure ink and you are reverse-engineering the wrong quantity.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from .normalize import FontIdentity, glyph_name, identify
from .symbols import AtomClass, Role, SymbolInfo, lookup as lookup_symbol
from .tfm import TfmFont, load_tfm


@dataclass(frozen=True)
class GlyphMetrics:
    """TeX's box for one glyph, in points at the size it was actually set."""

    width: float
    height: float          # above the baseline
    depth: float           # below the baseline
    italic: float          # italic correction
    source: str            # "tfm" | "pdf-widths" | "unknown"

    @property
    def total_height(self) -> float:
        return self.height + self.depth


@dataclass(frozen=True)
class ResolvedGlyph:
    """A character code resolved against everything we know."""

    font: FontIdentity
    code: int
    glyph: Optional[str]
    symbol: SymbolInfo
    metrics: GlyphMetrics
    size: float                     # the size the glyph was set at, in pt
    unicode_from_pdf: Optional[str] = None

    @property
    def unicode(self) -> str:
        """Prefer the TeX identity; fall back to the PDF's own ToUnicode."""
        return self.symbol.unicode or (self.unicode_from_pdf or "")

    @property
    def atom(self) -> AtomClass:
        return self.symbol.atom

    @property
    def role(self) -> Role:
        return self.symbol.role


class FontMetrics:
    """Resolution of ``(pdf font name, character code, size)`` to TeX facts."""

    @staticmethod
    @lru_cache(maxsize=512)
    def tfm_for(pdf_font_name: str) -> Optional[TfmFont]:
        ident = identify(pdf_font_name)
        if ident.tfm_name is None:
            return None
        return load_tfm(ident.tfm_name)

    @staticmethod
    @lru_cache(maxsize=65536)
    def lookup(pdf_font_name: str, code: int, size: float = 10.0,
               pdf_width: Optional[float] = None,
               unicode_from_pdf: Optional[str] = None) -> ResolvedGlyph:
        """Resolve one glyph.

        ``size`` is the size the glyph was set at, in **TeX points**.  ``pdf_width`` (also
        pt) is the width from the PDF's ``/Widths`` array, used only when no TFM is
        available.
        """
        ident = identify(pdf_font_name)
        name = glyph_name(ident, code)
        sym = lookup_symbol(name, ident.encoding) if name else SymbolInfo(
            f"code{code}", unicode_from_pdf or "", AtomClass.ORD, Role.SYMBOL)

        tfm = FontMetrics.tfm_for(pdf_font_name)
        if tfm is not None:
            scaled = tfm.scaled(code, size)
            if scaled is not None:
                w, h, d, it = scaled
                m = GlyphMetrics(w, h, d, it, "tfm")
            else:
                m = GlyphMetrics(pdf_width or 0.0, size * 0.7, 0.0, 0.0, "pdf-widths")
        elif pdf_width is not None:
            m = GlyphMetrics(pdf_width, size * 0.7, size * 0.2, 0.0, "pdf-widths")
        else:
            m = GlyphMetrics(0.0, 0.0, 0.0, 0.0, "unknown")

        return ResolvedGlyph(ident, code, name, sym, m, size, unicode_from_pdf)

    @staticmethod
    @lru_cache(maxsize=256)
    def extensible_pieces(pdf_font_name: str) -> frozenset[int]:
        """Codes this font uses as top / middle / bottom / repeat pieces.

        Read straight out of the TFM's extensible recipes, so it is a fact about the
        font rather than a list we maintain.  It is how we know that four stacked
        ``vextendsingle`` glyphs are one tall bar and not four vertical strokes.
        Code 0 means "no piece" in a recipe and is excluded.
        """
        tfm = FontMetrics.tfm_for(pdf_font_name)
        if tfm is None:
            return frozenset()
        out: set[int] = set()
        for recipe in tfm.extensible.values():
            for piece in (recipe.top, recipe.mid, recipe.bot, recipe.rep):
                if piece:
                    out.add(piece)
        return frozenset(out)

    @staticmethod
    def charlist(pdf_font_name: str, code: int) -> list[int]:
        """Successively larger variants of a glyph (TeX's charlist chain)."""
        tfm = FontMetrics.tfm_for(pdf_font_name)
        return tfm.charlist(code) if tfm else [code]
