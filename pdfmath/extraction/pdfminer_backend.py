"""Glyph and rule extraction, built on pdfminer.six.

The technique is the one SymbolScraper established: do not read the content stream by
hand, *intercept the renderer*, so that the CTM, text matrix, font resources and
graphics state are all resolved for you.  Characters and paths arrive through separate
hooks and are re-associated later (see pdfmath.parse.radicals).

What we keep that a general-purpose extractor throws away:

* the raw character code, before any Unicode resolution;
* the full text matrix, hence the true baseline reference point;
* the page's font *resource* name (``/F35``), which is the only stable handle on a font
  when several subsets of the same face appear;
* the graphics-state line width of stroked rules, which for pdfTeX equals
  ``default_rule_thickness`` and so identifies the rule's purpose.

Everything is converted from PDF big points to TeX points at this boundary.
"""

from __future__ import annotations

import logging
import math
from typing import Iterator, Optional, Sequence

from pdfminer.converter import PDFLayoutAnalyzer
from pdfminer.pdfdevice import PDFDevice
from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
from pdfminer.pdfpage import PDFPage
from pdfminer.pdftypes import PDFObjRef
from pdfminer.psparser import literal_name
from pdfminer.utils import apply_matrix_pt, mult_matrix

from ..geometry.bbox import BBox
from ..units import bp_to_pt
from .model import Glyph, PageExtract, Rule

log = logging.getLogger(__name__)

#: Below this, a "rule" is more likely to be a hairline artefact than a fraction bar.
MIN_RULE_LENGTH_PT = 0.5


class _Device(PDFLayoutAnalyzer):
    """Collects glyphs and rules instead of building a layout tree."""

    def __init__(self, rsrcmgr: PDFResourceManager, pageno: int = 1):
        super().__init__(rsrcmgr, pageno=pageno, laparams=None)
        self.glyphs: list[Glyph] = []
        self.rules: list[Rule] = []
        self.warnings: list[str] = []
        self.current_font_resource: Optional[str] = None
        self._page_no = pageno
        self._next_glyph_id = 0
        self._next_rule_id = 0

    # -- pdfminer plumbing we do not want ----------------------------------------
    def begin_page(self, page, ctm):            # noqa: D102  (overrides layout building)
        self.ctm = ctm

    def end_page(self, page):                   # noqa: D102
        return

    def begin_figure(self, name, bbox, matrix): return
    def end_figure(self, name): return
    def render_image(self, name, stream): return

    # -- characters ---------------------------------------------------------------
    def render_char(self, matrix, font, fontsize, scaling, rise, cid, ncs,
                    graphicstate) -> float:
        a, b, c, d, e, f = matrix
        # The glyph's reference point in device space.  pdfminer has already folded the
        # text matrix, the CTM and the horizontal displacement into `matrix`, so (e, f)
        # is the origin before the text rise is applied.
        ox, oy = apply_matrix_pt(matrix, (0.0, rise))

        vscale = math.hypot(c, d) or 1.0
        size_bp = fontsize * vscale

        try:
            uni = font.to_unichr(cid)
            if not isinstance(uni, str):
                uni = None
        except Exception:
            uni = None
        try:
            width_bp = font.char_width(cid) * fontsize * scaling * math.hypot(a, b)
        except Exception:
            width_bp = None

        name = getattr(font, "basefont", None) or getattr(font, "fontname", "") or ""
        if isinstance(name, bytes):
            name = name.decode("latin-1", "replace")

        self.glyphs.append(Glyph(
            id=self._next_glyph_id,
            page=self._page_no,
            char_code=cid,
            x=bp_to_pt(ox),
            y=bp_to_pt(oy),
            size=bp_to_pt(size_bp),
            font_name=str(name),
            font_resource=self.current_font_resource,
            matrix=(a, b, c, d, e, f),
            unicode_from_pdf=uni,
            pdf_width=bp_to_pt(width_bp) if width_bp is not None else None,
        ))
        self._next_glyph_id += 1

        try:
            return font.char_width(cid) * fontsize * scaling
        except Exception:
            return 0.0

    # -- paths ---------------------------------------------------------------------
    def paint_path(self, gstate, stroke, fill, evenodd, path) -> None:
        """Normalise a painted path into zero or more :class:`Rule` objects.

        pdfTeX emits a rule as ``0 0 m <w> 0 l S`` under a translating ``cm``, with the
        thickness in the graphics state.  Other producers emit ``x y w h re f``.  Both
        become the same thing here.
        """
        if not path:
            return
        shape = "".join(str(seg[0]) for seg in path)
        if shape.count("m") > 1:                      # split compound paths
            start = 0
            for i, ch in enumerate(shape):
                if ch == "m" and i > start:
                    self.paint_path(gstate, stroke, fill, evenodd, path[start:i])
                    start = i
            self.paint_path(gstate, stroke, fill, evenodd, path[start:])
            return

        pts = []
        for seg in path:
            coords = seg[1:]
            for i in range(0, len(coords) - 1, 2):
                pts.append(apply_matrix_pt(self.ctm, (coords[i], coords[i + 1])))
        if len(pts) < 2:
            return

        scale = math.sqrt(abs(self.ctm[0] * self.ctm[3] - self.ctm[1] * self.ctm[2])) or 1.0
        lw_bp = (gstate.linewidth or 0.0) * scale

        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)

        is_line = shape in ("ml", "mlh") and len(pts) >= 2
        is_rect = shape in ("mlllh", "mllll", "mlll") or (
            len(pts) in (4, 5) and len({round(v, 3) for v in xs}) == 2
            and len({round(v, 3) for v in ys}) == 2)

        if stroke and is_line:
            thick = lw_bp if lw_bp > 0 else 0.4 * (72.0 / 72.27)
            # A stroked line is centred on its path, so it occupies +/- half a width.
            if abs(y1 - y0) <= abs(x1 - x0):          # horizontal
                yc = 0.5 * (y0 + y1)
                self._emit(x0, yc - thick / 2, x1, yc + thick / 2, thick, "stroke",
                           f"stroked line, lw={lw_bp:.4f}bp")
            else:                                     # vertical
                xc = 0.5 * (x0 + x1)
                self._emit(xc - thick / 2, y0, xc + thick / 2, y1, thick, "stroke",
                           f"stroked line, lw={lw_bp:.4f}bp")
            return

        if fill and is_rect:
            thick = min(abs(x1 - x0), abs(y1 - y0))
            self._emit(x0, y0, x1, y1, thick, "fill", "filled rectangle")
            return

        if stroke and is_rect:
            thick = lw_bp if lw_bp > 0 else 0.4 * (72.0 / 72.27)
            self._emit(x0, y0, x1, y1, thick, "stroke", "stroked rectangle")
            return

        if fill or stroke:
            self.warnings.append(
                f"unhandled painted path shape {shape!r} at "
                f"({bp_to_pt(x0):.2f},{bp_to_pt(y0):.2f})-"
                f"({bp_to_pt(x1):.2f},{bp_to_pt(y1):.2f}); not discarded, "
                f"recorded as a rule")
            self._emit(x0, y0, x1, y1, min(abs(x1 - x0), abs(y1 - y0)),
                       "fill" if fill else "stroke", f"path shape {shape!r}")

    def _emit(self, x0, y0, x1, y1, thickness, kind, source) -> None:
        if max(abs(x1 - x0), abs(y1 - y0)) < MIN_RULE_LENGTH_PT * (72.0 / 72.27):
            return
        self.rules.append(Rule(
            id=self._next_rule_id, page=self._page_no,
            x0=bp_to_pt(x0), y0=bp_to_pt(y0), x1=bp_to_pt(x1), y1=bp_to_pt(y1),
            thickness=bp_to_pt(thickness), kind=kind, source=source,
        ))
        self._next_rule_id += 1


class _Interpreter(PDFPageInterpreter):
    """Records which page resource each ``Tf`` selects."""

    def do_Tf(self, fontid, fontsize):                # noqa: N802 (PDF operator name)
        try:
            self.device.current_font_resource = literal_name(fontid)
        except Exception:
            self.device.current_font_resource = None
        return super().do_Tf(fontid, fontsize)


def extract_page(pdf_path: str, page_number: int) -> PageExtract:
    """Extract one page (1-based)."""
    pages = list(extract_pages(pdf_path, [page_number]))
    if not pages:
        raise IndexError(f"{pdf_path} has no page {page_number}")
    return pages[0]


def extract_pages(pdf_path: str,
                  page_numbers: Optional[Sequence[int]] = None) -> Iterator[PageExtract]:
    """Extract the given 1-based page numbers, or every page."""
    wanted = set(page_numbers) if page_numbers else None
    with open(pdf_path, "rb") as fh:
        rsrcmgr = PDFResourceManager(caching=True)
        for i, page in enumerate(PDFPage.get_pages(fh, check_extractable=False), start=1):
            if wanted is not None and i not in wanted:
                continue
            device = _Device(rsrcmgr, pageno=i)
            interpreter = _Interpreter(rsrcmgr, device)
            try:
                interpreter.process_page(page)
            except Exception as exc:                  # a broken page should not be fatal
                device.warnings.append(f"page {i}: {type(exc).__name__}: {exc}")
                log.warning("page %d failed: %s", i, exc)
            mb = page.mediabox or [0, 0, 612, 792]
            yield PageExtract(
                page=i,
                width=bp_to_pt(float(mb[2]) - float(mb[0])),
                height=bp_to_pt(float(mb[3]) - float(mb[1])),
                glyphs=device.glyphs,
                rules=device.rules,
                warnings=device.warnings,
            )
