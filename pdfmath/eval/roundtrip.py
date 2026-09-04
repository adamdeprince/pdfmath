"""Validate a decompilation by recompiling it.

The oracle this project actually wants.  A decompiler is not checked against a reference
implementation; it is checked by feeding its output back to the compiler and seeing
whether the result is the same program.  Here that is literal: serialise the recovered
tree to LaTeX, run pdfTeX on it, extract the glyphs, and compare them with the ones we
started from.  If every glyph lands in the same place relative to its neighbours, the
structure we recovered is one that TeX compiles to the original page.

Three things make this worth more than the synthetic corpus:

* **It needs no ground truth.**  It applies to real documents, where none exists -- the
  210 equations extracted from 1991-2002 arXiv preprints have no expected trees, and this
  gives them a pass/fail.
* **It needs no second system.**  No incumbent has to be installed, licensed or trusted.
* **It tests what actually matters.**  A tree that differs from ground truth in a way TeX
  cannot render differently is not a defect; a tree that recompiles to a different page
  is, whatever a tree-edit distance says about it.

What it cannot do is catch a structure that is *genuinely* ambiguous -- ``{a+b}^2`` and
``a+b^2`` recompile identically because they are the same page -- which is exactly the
class of difference the corpus comparison also declines to assert.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from ..corpus.compile import CompileError, compile_expressions, have_pdflatex
from ..extraction.model import Glyph, PageExtract, Rule
from ..extraction.pdfminer_backend import extract_page
from ..latex.serializer import to_latex
from ..parse.context import ParseContext
from ..tree.nodes import MathNode

#: pdfTeX writes coordinates to three decimals of a big point, so two compilations of the
#: same source agree to about a thousandth of a point.  Anything under this is rounding.
POSITION_TOLERANCE_PT = 0.02

#: Standard LaTeX class options and the text size each produces, in TeX points.
_CLASS_SIZES = {10: 10.0, 11: 10.95, 12: 12.0}


@dataclass
class GlyphDiff:
    index: int
    original: str
    rebuilt: str
    offset_pt: float = 0.0


@dataclass
class RoundTripResult:
    """What happened when the recovered tree was compiled again."""

    latex: str = ""
    unreproducible: list[str] = field(default_factory=list)
    compiled: bool = False
    error: Optional[str] = None
    n_original: int = 0
    n_rebuilt: int = 0
    identities_match: bool = False
    max_offset_pt: float = float("inf")
    rms_offset_pt: float = float("inf")
    rules_match: bool = False
    n_original_rules: int = 0
    n_rebuilt_rules: int = 0
    size_option: int = 10
    mismatches: list[GlyphDiff] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        """``exact`` | ``shifted`` | ``different`` | ``uncompilable`` | ``incomplete``."""
        if self.unreproducible:
            return "incomplete"
        if not self.compiled:
            return "uncompilable"
        if not self.identities_match:
            return "different"
        if self.max_offset_pt <= POSITION_TOLERANCE_PT and self.rules_match:
            return "exact"
        return "shifted"

    @property
    def ok(self) -> bool:
        return self.verdict == "exact"

    def to_json(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "latex": self.latex,
            "glyphs": {"original": self.n_original, "rebuilt": self.n_rebuilt,
                       "identities_match": self.identities_match},
            "rules": {"original": self.n_original_rules,
                      "rebuilt": self.n_rebuilt_rules, "match": self.rules_match},
            "max_offset_pt": (None if math.isinf(self.max_offset_pt)
                              else round(self.max_offset_pt, 5)),
            "rms_offset_pt": (None if math.isinf(self.rms_offset_pt)
                              else round(self.rms_offset_pt, 5)),
            "size_option": self.size_option,
            "unreproducible": self.unreproducible,
            "mismatches": [{"index": m.index, "original": m.original,
                            "rebuilt": m.rebuilt,
                            "offset_pt": round(m.offset_pt, 5)}
                           for m in self.mismatches[:12]],
            "error": self.error,
        }


def _identity(g: Glyph) -> str:
    return f"{g.font.base_name}:{g.char_code}"


def _ordered(glyphs: Sequence[Glyph]) -> list[Glyph]:
    return sorted(glyphs, key=lambda g: (round(g.x, 3), -round(g.y, 3)))


def size_option_for(text_size: float) -> int:
    """The ``\\documentclass`` option whose text size matches the document's."""
    return min(_CLASS_SIZES, key=lambda opt: abs(_CLASS_SIZES[opt] - text_size))


def compare(original: PageExtract, rebuilt: PageExtract,
            result: RoundTripResult) -> RoundTripResult:
    """Fill in the comparison fields of ``result`` from two extractions.

    Absolute position is not comparable -- the rebuilt equation is alone on a fresh page
    -- so the two are aligned by the *median* displacement and the residuals about that
    are what is reported.  Using the median rather than the first glyph means one
    misplaced symbol cannot drag the whole comparison with it.
    """
    a, b = _ordered(original.glyphs), _ordered(rebuilt.glyphs)
    result.n_original, result.n_rebuilt = len(a), len(b)
    ids_a = [_identity(g) for g in a]
    ids_b = [_identity(g) for g in b]
    result.identities_match = ids_a == ids_b

    if not result.identities_match:
        for i in range(max(len(ids_a), len(ids_b))):
            x = ids_a[i] if i < len(ids_a) else "-"
            y = ids_b[i] if i < len(ids_b) else "-"
            if x != y:
                result.mismatches.append(GlyphDiff(i, x, y))
        return result

    if not a:
        result.max_offset_pt = result.rms_offset_pt = 0.0
        result.rules_match = (len(original.rules) == len(rebuilt.rules))
        result.n_original_rules = len(original.rules)
        result.n_rebuilt_rules = len(rebuilt.rules)
        return result

    dxs = [g.x - h.x for g, h in zip(a, b)]
    dys = [g.y - h.y for g, h in zip(a, b)]
    mdx, mdy = statistics.median(dxs), statistics.median(dys)
    offsets = [math.hypot(dx - mdx, dy - mdy) for dx, dy in zip(dxs, dys)]
    result.max_offset_pt = max(offsets)
    result.rms_offset_pt = math.sqrt(sum(o * o for o in offsets) / len(offsets))
    for i, (g, off) in enumerate(zip(a, offsets)):
        if off > POSITION_TOLERANCE_PT:
            result.mismatches.append(GlyphDiff(i, _identity(g), _identity(b[i]), off))

    ra = sorted(original.rules, key=lambda r: (round(r.bbox.x0, 3), -round(r.bbox.y0, 3)))
    rb = sorted(rebuilt.rules, key=lambda r: (round(r.bbox.x0, 3), -round(r.bbox.y0, 3)))
    result.n_original_rules, result.n_rebuilt_rules = len(ra), len(rb)
    result.rules_match = len(ra) == len(rb) and all(
        abs(x.width - y.width) <= POSITION_TOLERANCE_PT
        and abs(x.thickness - y.thickness) <= POSITION_TOLERANCE_PT
        and math.hypot((x.bbox.x0 - y.bbox.x0) - mdx,
                       (x.bbox.y0 - y.bbox.y0) - mdy) <= POSITION_TOLERANCE_PT
        for x, y in zip(ra, rb))
    return result


def roundtrip(tree: MathNode, original: PageExtract, ctx: Optional[ParseContext] = None,
              workdir: Optional[str] = None, display: bool = True,
              name: Optional[str] = None) -> RoundTripResult:
    """Serialise ``tree``, recompile it, and compare with ``original``."""
    rendered = to_latex(tree)
    text_size = (ctx.text_size if ctx is not None
                 else max((g.size for g in original.glyphs), default=10.0))
    result = RoundTripResult(latex=rendered.latex,
                             unreproducible=list(rendered.unreproducible),
                             size_option=size_option_for(text_size))
    if not have_pdflatex():
        result.error = "pdflatex is not installed"
        return result
    if not rendered.latex.strip():
        result.error = "nothing to recompile"
        return result

    try:
        corpus = compile_expressions([rendered.latex], workdir=workdir,
                                     size=result.size_option, display=display,
                                     name=name)
    except CompileError as exc:
        result.error = str(exc).splitlines()[-1] if str(exc) else "pdflatex failed"
        return result
    result.compiled = True
    return compare(original, extract_page(corpus.pdf_path, 1), result)
