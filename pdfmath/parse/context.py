"""Parse context: the style, the size, the TeX parameters, and the trace."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from ..fonts.mathparams import MathParams, Style, params_for


@dataclass
class Explanation:
    """One recorded decision, for ``pdfmath explain``."""

    relationship: str
    node_id: Optional[int] = None
    parts: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "relationship": self.relationship,
            "node": self.node_id,
            **self.parts,
            "confidence": round(self.confidence, 6),
            "evidence": {k: (round(v, 6) if isinstance(v, float) else v)
                         for k, v in self.evidence.items()},
        }


@dataclass
class Trace:
    """Accumulates explanations across a whole parse."""

    entries: list[Explanation] = field(default_factory=list)

    def add(self, exp: Explanation) -> Explanation:
        self.entries.append(exp)
        return exp

    def for_node(self, node_id: int) -> list[Explanation]:
        return [e for e in self.entries if e.node_id == node_id]

    def to_json(self) -> list[dict[str, Any]]:
        return [e.to_json() for e in self.entries]


@dataclass
class ParseContext:
    """Everything a recogniser needs to turn geometry into a decision.

    ``text_size`` is the document's math text size in points -- 9.96264 bp in the PDF is
    10 pt here.  ``style`` is TeX's current math style, which determines both the font
    size and which Appendix G parameters apply.
    """

    text_size: float = 10.0
    style: Style = Style.DISPLAY
    symbol_family: str = "cmsy"
    extension_family: str = "cmex"
    trace: Trace = field(default_factory=Trace)
    depth: int = 0
    #: The sizes of text, script and scriptscript style, in points.  Read off the page
    #: where possible rather than assumed: LaTeX's \DeclareMathSizes gives 10/7/5 in a
    #: 10 pt document but 12/8/6 in a 12 pt one, and applying the wrong ratio puts every
    #: predicted script shift about a point out.
    math_sizes: Optional[tuple[float, float, float]] = None

    _params: Optional[MathParams] = field(default=None, repr=False)

    @property
    def params(self) -> MathParams:
        if self._params is None:
            self._params = params_for(self.style, self.text_size,
                                      self.symbol_family, self.extension_family,
                                      size=self.size)
        return self._params

    @property
    def size(self) -> float:
        """Font size of the current style, in points."""
        return self.size_of(self.style)

    def size_of(self, style: Style) -> float:
        if self.math_sizes is None:
            return self.text_size * style.size_ratio
        if style < Style.SCRIPT:
            return self.math_sizes[0]
        if style < Style.SCRIPTSCRIPT:
            return self.math_sizes[1]
        return self.math_sizes[2]

    # -- derived contexts -----------------------------------------------------------
    def _with(self, style: Style) -> "ParseContext":
        return ParseContext(self.text_size, style, self.symbol_family,
                            self.extension_family, self.trace, self.depth + 1,
                            self.math_sizes)

    def numerator(self) -> "ParseContext":  return self._with(self.style.numerator_style())
    def denominator(self) -> "ParseContext": return self._with(self.style.denominator_style())
    def superscript(self) -> "ParseContext": return self._with(self.style.sup_style())
    def subscript(self) -> "ParseContext":   return self._with(self.style.sub_style())
    def cramped(self) -> "ParseContext":     return self._with(self.style.cramp())
    def same(self) -> "ParseContext":        return self._with(self.style)

    # -- tolerances, all derived from TeX quantities rather than tuned --------------
    @property
    def rule_thickness(self) -> float:
        """theta = default_rule_thickness at the current size."""
        return self.params.default_rule_thickness()

    #: ``\\nulldelimiterspace``, the padding TeX puts on each side of a fraction (and of
    #: an empty delimiter).  1.2 pt in plain TeX and in every LaTeX class.
    null_delimiter_space: float = 1.2
    #: ``\\scriptspace``, added to the width of every script box.  0.5 pt.
    script_space: float = 0.5

    @property
    def eps(self) -> float:
        """The finest distance worth distinguishing.

        pdfTeX writes coordinates with three decimals of a big point, so anything below
        about a thousandth of a point is quantisation.  We allow a generous multiple so
        that accumulated rounding over a few operations still compares equal.
        """
        return 0.02

    @property
    def baseline_tol(self) -> float:
        """How far two reference points may differ and still count as one baseline.

        TeX places same-line atoms on *exactly* the same baseline, so this only has to
        absorb PDF coordinate rounding.  It is deliberately far smaller than the smallest
        real script shift (sub1 = 1.5 pt at 10 pt)."""
        return max(0.05, 0.005 * self.text_size)

    @property
    def x_tol(self) -> float:
        """Horizontal slack when testing containment inside a rule's span."""
        return max(0.1, 0.02 * self.text_size)


def infer_math_sizes(sizes: Sequence[float]) -> tuple[float, float, float]:
    """Recover (text, script, scriptscript) sizes from the sizes actually on the page.

    TeX only ever sets a formula at three sizes, and they are well separated, so the
    distinct sizes present -- clustered to absorb pdfTeX's rounding -- give them
    directly.  When an expression has no scripts there is nothing to read and the 10 pt
    ratios stand in.
    """
    if not sizes:
        return (10.0, 7.0, 5.0)
    ordered = sorted(sizes, reverse=True)
    levels: list[float] = [ordered[0]]
    for s in ordered[1:]:
        if s < levels[-1] * 0.95:
            levels.append(s)
        if len(levels) == 3:
            break
    text = levels[0]
    script = levels[1] if len(levels) > 1 else text * 0.7
    ss = levels[2] if len(levels) > 2 else script * (5.0 / 7.0)
    return (text, script, ss)


def infer_text_size(sizes: Sequence[float]) -> float:
    """Recover the document's math text size from the sizes actually observed.

    TeX sets scripts at 0.7 and scriptscripts at 0.5 of the text size, so the largest
    size present is the text size -- unless the expression is *entirely* scripted, which
    cannot happen for a top-level formula.
    """
    if not sizes:
        return 10.0
    return max(sizes)


def infer_style(sizes: Sequence[float], text_size: float,
                has_display_operator: bool = False) -> Style:
    """Display or text style?

    Two independent signals, either of which is decisive:

    * a large operator drawn from cmex's *display* variants (``summationdisplay``);
    * a fraction whose numerator is at full text size -- in text style TeX would have
      set it at script size.

    Callers pass the first; the second is left to the fraction recogniser, which records
    it as evidence.  With neither signal we assume display, because that is what a
    displayed equation is.
    """
    return Style.DISPLAY
