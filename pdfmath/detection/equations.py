"""Finding displayed equations on a page.

Detection deliberately does not block the decompiler: ``--page`` plus ``--bbox`` lets the
recogniser be measured on its own, and that is the path the synthetic corpus uses.  This
module is the convenience layer for real documents.

It is geometric, not neural, and it leans on the same TeX-specific evidence as the rest of
the system.

The unit of analysis is the **text line**, found by clustering baselines rather than by
looking for whitespace between boxes.  That distinction is what makes it work on a real
page: consecutive lines of a 10 pt paragraph leave under 4 pt of whitespace once
ascenders and descenders are counted, so any box-gap threshold loose enough to keep a
display's numerator with its denominator also merges whole paragraphs.  Baselines do not
have that problem -- a line's glyphs share one exactly.

A line is then a display candidate when it

* draws most of its characters from *math* fonts (cmmi, cmsy, cmex, msam, msbm) or
  contains rules of ``default_rule_thickness``, and
* is horizontally inset from the body text column, because ``\\[ ... \\]`` centres it.

Adjacent candidate lines are merged, which is what reassembles a fraction (whose numerator
and denominator are separate baselines) and a multi-line display into one region.

Inline mathematics inside a paragraph is deliberately not reported: it fails the inset
test, and reporting it would need a different notion of a region.  ScanSSD, the detector
in the MathSeer pipeline, finds both, at the cost of a trained model and a rasterisation
step; docs/prior-art.md says why that is kept off the critical path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from ..extraction.model import Glyph, PageExtract, Rule
from ..geometry.bbox import BBox
from ..geometry.index import vertical_bands

MATH_ENCODINGS = {"OML", "OMS", "OMX", "AMSA", "AMSB"}


@dataclass
class EquationRegion:
    """A candidate displayed equation."""

    bbox: BBox
    glyph_ids: list[int]
    rule_ids: list[int]
    confidence: float
    evidence: dict[str, Any] = field(default_factory=dict)

    #: The math style its contents were set in.  A displayed equation is display style
    #: and an inline one is text style, and every Appendix G prediction differs between
    #: them, so the region has to carry it to whoever parses it.
    style: str = "display"

    def to_json(self) -> dict[str, Any]:
        return {
            "bbox": [round(v, 4) for v in self.bbox.as_list()],
            "glyph_ids": self.glyph_ids,
            "rule_ids": self.rule_ids,
            "confidence": round(self.confidence, 4),
            "style": self.style,
            "evidence": self.evidence,
        }


def _body_text_size(glyphs: list[Glyph]) -> float:
    sizes: dict[float, int] = {}
    for g in glyphs:
        sizes[round(g.size, 2)] = sizes.get(round(g.size, 2), 0) + 1
    return max(sizes, key=lambda s: sizes[s]) if sizes else 10.0


@dataclass
class _Line:
    """One text line: the glyphs sharing a baseline, plus the rules that sit on it."""

    baseline: float
    glyphs: list[Glyph] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)

    @property
    def bbox(self) -> BBox:
        return BBox.union([g.bbox for g in self.glyphs]
                          + [r.bbox for r in self.rules])

    @property
    def math_ratio(self) -> float:
        if not self.glyphs:
            return 1.0 if self.rules else 0.0
        math = sum(1 for g in self.glyphs if g.font.encoding in MATH_ENCODINGS)
        return math / len(self.glyphs)


def _lines(extract: PageExtract, tol: float) -> list[_Line]:
    """Cluster glyphs into text lines by baseline, top of page first."""
    lines: list[_Line] = []
    for g in sorted(extract.glyphs, key=lambda g: -g.y):
        if lines and abs(lines[-1].baseline - g.y) <= tol:
            lines[-1].glyphs.append(g)
        else:
            lines.append(_Line(g.y, [g], []))
    for r in extract.rules:
        if not lines:
            break
        nearest = min(lines, key=lambda ln: abs(ln.baseline - r.bbox.cy))
        nearest.rules.append(r)
    return lines


def _text_column(lines: list[_Line], body: float) -> tuple[float, float, bool]:
    """The body text column: the extent of the widest prose lines.

    Prose lines run margin to margin and are the most common shape on the page, so the
    widest line that is *not* math-heavy defines the column a display is inset from.
    """
    prose = [ln for ln in lines if ln.math_ratio < 0.45 and len(ln.glyphs) > 5]
    pool = prose or lines
    if not pool:
        return (0.0, 1.0, False)
    widest = max(pool, key=lambda ln: ln.bbox.width)
    return (widest.bbox.x0, widest.bbox.x1, bool(prose))


def find_displayed_equations(extract: PageExtract,
                             min_math_ratio: float = 0.45,
                             min_inset_ratio: float = 0.02) -> list[EquationRegion]:
    """Displayed equations on the page, in reading order."""
    if not extract.glyphs and not extract.rules:
        return []
    body = _body_text_size(extract.glyphs)
    lines = _lines(extract, tol=max(0.05, 0.02 * body))
    if not lines:
        return []
    col_x0, col_x1, has_prose = _text_column(lines, body)
    col_w = max(col_x1 - col_x0, 1e-6)
    # With no prose on the page there is no column to be inset from and no paragraph to
    # be set off from: the page *is* the equation.  This is the case a single-formula
    # test PDF presents, and the geometric tests have to be skipped rather than failed.
    single_block = len(lines) < 2 or not has_prose

    # A line is prose if it is not math-heavy enough to be a display in its own right
    # and it runs most of the way across the column.  The threshold has to be the *same*
    # one used to accept a display, or the last line of a paragraph -- which is short and
    # often ends in mathematics -- falls between the two tests and gets swept into the
    # display above it, prose and all.
    prose_lines = [ln for ln in lines
                   if ln.math_ratio < min_math_ratio
                   and ln.bbox.width > 0.5 * col_w and len(ln.glyphs) > 5]

    def inside_a_paragraph_line(ln: _Line) -> bool:
        """Does this baseline sit *within* a line of prose?

        Inline mathematics puts its scripts on their own baselines, and those are
        narrow, centred-looking and often entirely math-font -- indistinguishable from a
        small display until you notice that they overlap the text line they belong to.
        A display does not: TeX's display skips put clear air around it.
        """
        return any(ln.bbox.overlap_y(p.bbox) > 0 for p in prose_lines if p is not ln)

    def is_candidate(ln: _Line) -> tuple[bool, dict[str, Any]]:
        box = ln.bbox
        left = (box.x0 - col_x0) / col_w
        right = (col_x1 - box.x1) / col_w
        ev = {
            "math_font_ratio": round(ln.math_ratio, 4),
            "n_glyphs": len(ln.glyphs),
            "n_rules": len(ln.rules),
            "left_inset_ratio": round(left, 4),
            "right_inset_ratio": round(right, 4),
        }
        if ln.math_ratio < min_math_ratio and not ln.rules:
            ev["rejected"] = "not enough material from math fonts"
            return False, ev
        # A displayed equation is set at the document's text size.  A line whose largest
        # glyph is script-size is a *piece* of something -- a row of subscripts, a
        # detached limit -- and reporting it as a formula in its own right produces
        # fragments that begin in the middle of an expression.  Such lines still join a
        # display through the growth step below; they just cannot start one.
        biggest = max((g.size for g in ln.glyphs), default=body)
        ev["largest_glyph_pt"] = round(biggest, 3)
        if ln.glyphs and biggest < 0.85 * body:
            ev["rejected"] = "script-size throughout: a fragment, not a display"
            return False, ev
        if not single_block and inside_a_paragraph_line(ln):
            ev["rejected"] = "overlaps a line of prose: inline, not displayed"
            return False, ev
        ev["centred"] = left > min_inset_ratio and right > min_inset_ratio
        if not single_block and left <= min_inset_ratio:
            # A line that starts at the left margin is part of the paragraph flow, and
            # its mathematics is inline.  \[ ... \] centres, and \begin{equation}
            # centres the body and puts the number flush right, so both leave the left
            # margin clear.
            ev["rejected"] = "starts at the text margin: inline, not displayed"
            return False, ev
        return True, ev

    def isolated(first: int, last: int) -> tuple[bool, float, float]:
        """Is the block set off from the surrounding prose by real whitespace?

        Measured between *boxes*, not baselines: a display's topmost ink is a
        superscript that reaches up towards the line above, so the baseline distance
        says very little.  The threshold is set by TeX's own skips --
        ``\\belowdisplayshortskip`` is the smallest at 6 pt plus 3 minus 3 in a 10 pt
        document -- against the 2 to 4 pt that separates two prose lines.

        Only one side has to be clear: when the paragraph's last line is short and does
        not reach the display, TeX uses ``\\abovedisplayshortskip``, which is 0 pt plus
        3, and there is essentially no gap above at all.
        """
        box = BBox.union([lines[m].bbox for m in range(first, last + 1)])
        above = (lines[first - 1].bbox.y0 - box.y1
                 if first > 0 and box else float("inf"))
        below = (box.y0 - lines[last + 1].bbox.y1
                 if last + 1 < len(lines) and box else float("inf"))
        return (max(above, below) > 0.4 * body, above, below)

    # Body leading, from the modal gap between consecutive baselines.  A display's own
    # parts (a numerator and its denominator) are closer together than two prose lines.
    gaps = sorted(lines[i].baseline - lines[i + 1].baseline
                  for i in range(len(lines) - 1))
    leading = gaps[len(gaps) // 2] if gaps else 1.2 * body
    # With no prose on the page, the "median gap" is measured between the *parts* of the
    # formula -- a numerator and its denominator -- and is far smaller than a line.
    # There is nothing to separate, so every candidate line joins one region.
    merge_bound = float("inf") if single_block else 1.8 * leading
    flags = [is_candidate(ln) for ln in lines]

    out: list[EquationRegion] = []
    i = 0
    while i < len(lines):
        ok, ev = flags[i]
        if not ok:
            i += 1
            continue
        first = i
        j = i + 1
        while j < len(lines):
            gap = lines[j - 1].baseline - lines[j].baseline
            if gap > merge_bound:
                break
            if not flags[j][0] and lines[j] in prose_lines:
                break     # a paragraph line ends the display
            # A line that is not a candidate on its own can still be part of the
            # display: a superscript is often a row of cmr digits with no math font in
            # it, and a limit like "i = 0" is mostly cmr too.  Only prose ends the run.
            j += 1
        # ... but do not let a trailing non-candidate line that sits outside the
        # display's own column extend the region.
        while j > first + 1 and not flags[j - 1][0]:
            span = BBox.union([lines[m].bbox for m in range(first, j - 1)])
            if span is not None and span.contains_x(lines[j - 1].bbox,
                                                    pad=0.02 * col_w):
                break
            j -= 1

        # Grow the region over lines that *overlap it vertically*, whether or not they
        # look like maths on their own.  A superscript is often a line of cmr digits
        # with no math-font glyph in it at all, and the reason it belongs to the display
        # is not its fonts but that it sits inside the display's own vertical extent.
        # Prose is not absorbed this way: \abovedisplayskip keeps it clear of the box.
        def overlaps(k: int, lo: int, hi: int) -> bool:
            if lines[k] in prose_lines:
                return False        # a paragraph line is never part of a display
            box = BBox.union([lines[m].bbox for m in range(lo, hi)])
            if box is None or lines[k].bbox.overlap_y(box) <= 0:
                return False
            # ... and it has to sit *within* the display's own column.  Consecutive
            # prose lines overlap vertically too (ascenders meet descenders), so
            # vertical overlap alone would swallow the whole paragraph; a script line
            # is narrower than the formula it belongs to, a paragraph line is not.
            return box.contains_x(lines[k].bbox, pad=0.02 * col_w)

        while first > 0 and overlaps(first - 1, first, j):
            first -= 1
        while j < len(lines) and overlaps(j, first, j):
            j += 1
        group = lines[first:j]

        ok_iso, gap_above, gap_below = isolated(first, j - 1)
        centred = all(flags[k][1].get("centred") for k in range(first, j)
                      if flags[k][0])
        if not single_block and not (centred or ok_iso):
            i = j
            continue

        glyphs = [g for ln in group for g in ln.glyphs]
        rules = [r for ln in group for r in ln.rules]
        box = BBox.union([ln.bbox for ln in group])
        ratio = (sum(1 for g in glyphs if g.font.encoding in MATH_ENCODINGS)
                 / len(glyphs)) if glyphs else 1.0
        multi_size = len({round(g.size, 2) for g in glyphs}) > 1
        evidence = {
            "math_font_ratio": round(ratio, 4),
            "n_lines": len(group),
            "n_glyphs": len(glyphs),
            "n_rules": len(rules),
            "left_inset_ratio": round((box.x0 - col_x0) / col_w, 4),
            "right_inset_ratio": round((col_x1 - box.x1) / col_w, 4),
            "multiple_font_sizes": multi_size,
            "body_text_size_pt": round(body, 3),
            "body_leading_pt": round(leading, 3),
            "text_column_pt": [round(col_x0, 2), round(col_x1, 2)],
            "gap_above_pt": (round(gap_above, 3) if gap_above != float("inf")
                             else None),
            "gap_below_pt": (round(gap_below, 3) if gap_below != float("inf")
                             else None),
        }
        conf = min(0.99, 0.5 + 0.4 * ratio + (0.05 if multi_size else 0.0)
                   + (0.05 if rules else 0.0))
        out.append(EquationRegion(box, [g.id for g in glyphs],
                                  [r.id for r in rules], conf, evidence))
        i = j
    return out
