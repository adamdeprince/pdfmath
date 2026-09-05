r"""Finding mathematics *inside* a line of prose.

Displayed equations are found by their shape on the page -- centred, set off, in a gap.
An inline formula has none of that: it sits in the middle of a sentence, on the same
baseline, in the same paragraph.  What it does have is TeX's own bookkeeping, and that is
enough.

**The font is the first signal, and it is nearly decisive.**  TeX sets prose from the
roman text font and mathematics from cmmi, cmsy and cmex.  A cmmi glyph in a paragraph
did not come from prose -- there is no way to type one outside maths -- so every glyph in
a math encoding is a *seed*.  This catches more than variables: the comma in ``$[0,1]$``
comes from cmmi, which is what gives that formula away when every other character in it
is roman.

**The gap is the second, and it is self-calibrating.**  Interword glue stretches and
shrinks so the line can be justified; math glue does not.  So the interword space is a
property of *this line*, measurable from the gaps between its own words, and any gap
noticeably tighter than it is not a word boundary.  That is what separates ``log n``
(operator name, thin space) from ``log n`` as two words, without a threshold in points
that would be wrong at another size or another measure.

**The character class is the third.**  Roman glyphs do appear inside formulas -- digits,
``+``, ``=``, parentheses, brackets, capital Greek -- so a seed grows outward through
those, and stops at a roman *letter*, which is prose.  The exception is an operator name
(``log``, ``sin``, ``max``): those are roman letters set as mathematics, and they are
recognised as a set rather than guessed at.

What this cannot do is find a formula with no math-font glyph in it at all.  ``$\mathbf{v}$``
is cmbx, and so is bold prose; ``$2$`` is a roman digit, and so is a page number.  Those
are not hard, they are *undecidable* from the page -- TeX threw the distinction away --
and they are left alone rather than guessed at.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Optional, Sequence

from ..extraction.model import Glyph, PageExtract, Rule
from ..geometry.bbox import BBox
from .equations import MATH_ENCODINGS, EquationRegion, _body_text_size

#: Roman characters that occur inside mathematics as well as in prose.  A seed may grow
#: through these; it may not grow through a roman letter, which is prose.
MATH_ROMAN = set("0123456789+=()[]/.,;:!?*<>|'-")

#: Capital Greek comes from the roman font (TeX sets it upright), so it looks like prose
#: to an encoding test and has to be named.
GREEK_CAPITALS = set("ΓΔΘΛΞΠΣΥΦΨΩ")

#: The reverse case: glyphs that live in cmsy but belong to prose.  TeX takes ``\S``,
#: ``\dag``, ``\ddag`` and ``\P`` from the symbol font in text mode as well as in
#: maths, so a citation like "[4, §6]" otherwise seeds a formula and swallows the
#: bracket and the number around it.  They may still be *absorbed* into a formula that
#: something else has already seeded; they simply may not start one.
PROSE_IN_MATH_FONT = frozenset({"section", "dagger", "daggerdbl", "paragraph"})

#: Roman letter runs that are mathematics: TeX's own \log-like operators.  A run of these
#: is absorbed only when the gap to the formula is tighter than the line's interword
#: space, which is what an operator's thin space looks like.
OPERATOR_NAMES = frozenset("""
arccos arcsin arctan arg cos cosh cot coth csc deg det dim exp gcd hom inf ker lg lim
liminf limsup ln log max min Pr sec sin sinh sup tan tanh mod bmod pmod
""".split())

#: How far below the line's own interword space a gap must fall to be inside a formula.
#: Measured in points, and small, because the line calibrates itself: every interword
#: space on one line is the same glue stretched by the same factor, so they agree to a
#: hundredth of a point.  All that has to be absorbed here is the italic correction that
#: shifts a measured gap either side of the glue TeX actually inserted.
MARGIN_PT = 0.2

#: The fallback when a line is too short to measure its own interword space.  TeX's
#: interword glue is 6 mu at its natural width and the widest automatic math glue is
#: thick at 5 mu, so the boundary sits between them -- above 5 to allow for italic
#: correction, below 6 so a natural word space is never swallowed.
MAX_MATH_MU = 5.8

#: A line needs this many glyphs before it counts as prose rather than as something
#: hanging off a neighbouring line -- a lone radical sign, say, whose baseline is its
#: own.  Without it a tall symbol invents a line and takes its formula with it.
MIN_LINE_GLYPHS = 3

#: Punctuation that ends a sentence rather than a formula.  ``$f$.`` puts the period hard
#: against the ``f`` with no space at all, so no gap test can separate them; what settles
#: it is that mathematics does not *end* on one.  Interior punctuation -- the comma in
#: ``[0,1]``, the point in ``3.14`` -- is untouched, because only the ends are trimmed.
EDGE_PUNCTUATION = set(".,;:!?")

#: A glyph smaller than this fraction of the body size is a script, and scripts are
#: mathematics -- with one exception, a footnote marker, which is why a lone superscript
#: digit with no other evidence is not enough on its own.
SCRIPT_RATIO = 0.85


@dataclass
class _Line:
    """One line of prose, with everything sitting on it.

    Scripts and radicals are not on the baseline, so a line is built from its *dominant*
    baseline and then collects the glyphs that hang off it.
    """

    baseline: float
    glyphs: list[Glyph]
    rules: list[Rule]

    def sorted(self) -> list[Glyph]:
        return sorted(self.glyphs, key=lambda g: g.bbox.x0)


def _leading(baselines: Sequence[float]) -> float:
    """The distance between consecutive lines, which sets how far a script can stray."""
    if len(baselines) < 2:
        return 12.0
    steps = [a - b for a, b in zip(baselines, baselines[1:]) if a - b > 0.5]
    return statistics.median(steps) if steps else 12.0


def _outside(extract: PageExtract, boxes: Sequence[BBox]) -> PageExtract:
    """The page with everything belonging to a displayed equation removed.

    A display's limits and scripts sit on baselines of their own, several points from
    any line of prose and often too sparse to be a line in their own right, so left in
    place they attach themselves to whichever paragraph happens to be nearest -- a sum's
    ``k = 1`` landing in the middle of the sentence below it.  They are already accounted
    for by the display that owns them.
    """
    if not boxes:
        return extract
    def keep(box: BBox) -> bool:
        cx, cy = box.cx, box.cy
        return not any(b.x0 <= cx <= b.x1 and b.y0 <= cy <= b.y1 for b in boxes)
    return extract.__class__(
        page=extract.page,
        glyphs=[g for g in extract.glyphs if keep(g.bbox)],
        rules=[r for r in extract.rules if keep(r.bbox)],
        **{k: v for k, v in vars(extract).items()
           if k not in {"page", "glyphs", "rules"}})


def _lines(extract: PageExtract, body: float) -> list[_Line]:
    """Group glyphs into prose lines, scripts and tall symbols included.

    Baselines come from the full-size glyphs, and a baseline only becomes a line when
    enough glyphs share it.  Both restrictions are about the same failure: a superscript
    sits on its own baseline a few points up, and a radical sign sits on one of its own
    as well, so clustering naively turns one line of prose into three and cuts a formula
    across the seams.
    """
    full = [g for g in extract.glyphs if g.size >= body * SCRIPT_RATIO]
    if not full:
        return []
    clusters: list[list[float]] = []
    for g in sorted(full, key=lambda g: -g.y):
        if clusters and abs(clusters[-1][-1] - g.y) <= body * 0.3:
            clusters[-1].append(g.y)
        else:
            clusters.append([g.y])
    anchors = [statistics.median(c) for c in clusters
               if len(c) >= MIN_LINE_GLYPHS]
    if not anchors:
        anchors = [statistics.median(c) for c in clusters]
    lead = _leading(anchors)

    lines = [_Line(y, [], []) for y in anchors]
    for g in extract.glyphs:
        # A radical sign is hung from a raised reference point with almost all of its box
        # below, so the nearest *baseline* is the line above and the nearest *box* is the
        # right one.  Prefer a line whose baseline the glyph's box actually spans.
        spanning = [ln for ln in lines if g.bbox.y0 <= ln.baseline <= g.bbox.y1]
        if spanning:
            nearest = min(spanning, key=lambda ln: abs(ln.baseline - g.y))
        else:
            nearest = min(lines, key=lambda ln: abs(ln.baseline - g.y))
            # Half the leading, not most of it: a script or a numerator strays a few
            # points from its line, and anything further away belongs to another one.
            if abs(nearest.baseline - g.y) > lead * 0.5:
                continue
        nearest.glyphs.append(g)
    for r in extract.rules:
        nearest = min(lines, key=lambda ln: abs(ln.baseline - r.bbox.cy))
        if abs(nearest.baseline - r.bbox.cy) <= lead * 0.5:
            nearest.rules.append(r)
    return [ln for ln in lines if ln.glyphs]


def _is_math_font(g: Glyph) -> bool:
    return g.font.encoding in MATH_ENCODINGS


def _is_seed(g: Glyph) -> bool:
    """Could this glyph only have come from mathematics?  See :data:`PROSE_IN_MATH_FONT`."""
    return _is_math_font(g) and g.glyph_name not in PROSE_IN_MATH_FONT


def _interword(line: _Line, body: float) -> Optional[float]:
    """This line's interword space, measured from the line itself.

    Only gaps between two roman letters count, because those are certainly word
    boundaries.  The median resists the odd formula sitting between two words.
    """
    glyphs = line.sorted()
    gaps = []
    for left, right in zip(glyphs, glyphs[1:]):
        if _is_math_font(left) or _is_math_font(right):
            continue
        if not (left.unicode.isalpha() and right.unicode.isalpha()):
            continue
        gap = right.bbox.x0 - left.bbox.x1
        if gap > body * 0.08:                 # anything smaller is within a word
            gaps.append(gap)
    return statistics.median(gaps) if len(gaps) >= 3 else None


def _absorbable(g: Glyph, body: float) -> bool:
    """Could this glyph be part of a formula, given only what it is?"""
    if _is_math_font(g):
        return True
    if g.size < body * SCRIPT_RATIO:          # a script, whatever font it is in
        return True
    text = g.unicode
    return bool(text) and (text in MATH_ROMAN or text in GREEK_CAPITALS)


def _tight_gap(interword: Optional[float], ctx_quad: float) -> float:
    """The widest gap that is still inside a formula, on this line.

    Where the line could measure its own word space, that is the answer and it is exact:
    the same glue stretched by the same factor appears between every pair of words on the
    line.  Where it could not -- a line with fewer than three word boundaries -- the
    bound falls back to the widest automatic math glue.
    """
    ceiling = MAX_MATH_MU * (ctx_quad / 18.0)
    if interword is None:
        return ceiling
    return min(interword - MARGIN_PT, max(ceiling, interword - MARGIN_PT))


def _operator_run(glyphs: Sequence[Glyph], end: int, body: float,
                  tight: float) -> int:
    """How many roman letters before *end* spell an operator name set as mathematics.

    Returns 0 unless the letters both spell a known name and are joined to what follows
    by a gap tighter than a word boundary -- an operator's thin space.  Both tests are
    needed: "log" appears in prose too.
    """
    start = end
    while start > 0:
        g = glyphs[start - 1]
        if _is_math_font(g) or not g.unicode.isalpha() or g.size < body * SCRIPT_RATIO:
            break
        if start - 1 > 0:
            # Stop at a word boundary, or the walk swallows the whole sentence and
            # "that log" fails to spell an operator name.
            before = glyphs[start - 2]
            if g.bbox.x0 - before.bbox.x1 > tight:
                start -= 1
                break
        start -= 1
    if start == end:
        return 0
    word = "".join(g.unicode for g in glyphs[start:end])
    if word.lower() not in OPERATOR_NAMES and word not in OPERATOR_NAMES:
        return 0
    gap = glyphs[end].bbox.x0 - glyphs[end - 1].bbox.x1
    if gap > tight:
        return 0                              # a word, followed by a formula
    return end - start


def _grow(glyphs: Sequence[Glyph], seed: int, body: float,
          tight: float) -> tuple[int, int]:
    """Extend a seed to the run of glyphs that belongs with it.  Returns [lo, hi)."""
    lo = hi = seed

    while lo > 0:
        left, right = glyphs[lo - 1], glyphs[lo]
        gap = right.bbox.x0 - left.bbox.x1
        if _absorbable(left, body) and gap <= tight:
            lo -= 1
            continue
        taken = _operator_run(glyphs, lo, body, tight)
        if taken:
            lo -= taken
            continue
        break

    while hi + 1 < len(glyphs):
        left, right = glyphs[hi], glyphs[hi + 1]
        gap = right.bbox.x0 - left.bbox.x1
        if _absorbable(right, body) and gap <= tight:
            hi += 1
            continue
        break
    return _trim(glyphs, lo, hi + 1)


def _trim(glyphs: Sequence[Glyph], lo: int, hi: int) -> tuple[int, int]:
    """Drop sentence punctuation from the ends.  See :data:`EDGE_PUNCTUATION`."""
    while hi > lo and glyphs[hi - 1].unicode in EDGE_PUNCTUATION:
        hi -= 1
    while lo < hi and glyphs[lo].unicode in EDGE_PUNCTUATION:
        lo += 1
    return lo, hi


def find_inline_math(extract: PageExtract, body_size: Optional[float] = None,
                     exclude: Sequence[BBox] = ()) -> list[EquationRegion]:
    """Every inline formula on the page.

    ``exclude`` takes the displayed equations already found, so a caller that wants both
    does not get the displays reported twice.
    """
    if not extract.glyphs:
        return []
    body = body_size or _body_text_size(list(extract.glyphs))
    extract = _outside(extract, list(exclude))
    if not extract.glyphs:
        return []
    # The math quad is only needed for the fallback bound, and a text-size quad is the
    # right one: an inline formula is set in text style by definition.
    quad = body
    out: list[EquationRegion] = []

    for line in _lines(extract, body):
        glyphs = line.sorted()
        if _skip(line, exclude):
            continue
        interword = _interword(line, body)
        tight = _tight_gap(interword, quad)
        seeds = [i for i, g in enumerate(glyphs) if _is_seed(g)]
        spans: list[tuple[int, int]] = []
        for seed in seeds:
            if spans and spans[-1][0] <= seed < spans[-1][1]:
                continue                      # already inside the run we just grew
            lo, hi = _grow(glyphs, seed, body, tight)
            if lo >= hi:
                continue                      # trimmed away to nothing
            if spans and lo <= spans[-1][1]:
                spans[-1] = (spans[-1][0], max(spans[-1][1], hi))
            else:
                spans.append((lo, hi))
        for lo, hi in spans:
            region = _region(glyphs[lo:hi], line, body, interword, exclude)
            if region is not None:
                out.append(region)
    return out


def _skip(line: _Line, exclude: Sequence[BBox]) -> bool:
    """Is this whole line already accounted for by a displayed equation?"""
    box = BBox.union([g.bbox for g in line.glyphs])
    for other in exclude:
        overlap = max(0.0, box.overlap_x(other)) * max(0.0, box.overlap_y(other))
        if box.area > 0 and overlap / box.area > 0.6:
            return True
    return False


def _region(run: Sequence[Glyph], line: _Line, body: float,
            interword: Optional[float],
            exclude: Sequence[BBox]) -> Optional[EquationRegion]:
    if not run:
        return None
    box = BBox.union([g.bbox for g in run])
    for other in exclude:
        if box.overlap_x(other) > 0 and box.overlap_y(other) > 0:
            return None
    rules = [r for r in line.rules
             if r.bbox.x0 >= box.x0 - body and r.bbox.x1 <= box.x1 + body]
    if rules:
        box = BBox.union([box] + [r.bbox for r in rules])

    math_glyphs = sum(1 for g in run if _is_math_font(g))
    scripts = sum(1 for g in run if g.size < body * SCRIPT_RATIO)
    evidence = {
        "source": "inline",
        "n_glyphs": len(run),
        "math_font_glyphs": math_glyphs,
        "script_glyphs": scripts,
        "n_rules": len(rules),
        "interword_pt": round(interword, 4) if interword is not None else None,
        "body_text_size_pt": round(body, 4),
        "baseline_pt": round(line.baseline, 4),
    }
    return EquationRegion(
        bbox=box,
        glyph_ids=[g.id for g in run],
        rule_ids=[r.id for r in rules],
        confidence=_confidence(len(run), math_glyphs, scripts, interword),
        style="text",
        evidence=evidence)


def _confidence(total: int, math_glyphs: int, scripts: int,
                interword: Optional[float]) -> float:
    """How sure we are, and about what.

    A run that is entirely math-font glyphs is not in doubt.  Confidence falls as roman
    characters make up more of it, because each one was a judgement about a gap, and it
    falls again when the line was too short to measure its own interword space.
    """
    confidence = 0.60 + 0.35 * (math_glyphs / total)
    if scripts:
        confidence += 0.03
    if interword is None:
        confidence -= 0.15
    return round(max(0.05, min(0.99, confidence)), 4)
