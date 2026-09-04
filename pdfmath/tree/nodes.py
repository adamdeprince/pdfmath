"""The reconstructed math tree.

Two rules govern this module.

**Provenance is mandatory.**  Every node records the glyph ids and rule ids it was built
from, the box it occupies, a confidence, and the evidence dictionary that justified the
decision.  A decompiler whose output cannot be traced back to the bytes it came from is
not inspectable, and an inspectable wrong answer is worth more than an opaque right one.

**Uncertainty is preserved, never discarded.**  When a recogniser cannot explain a glyph
it becomes an :class:`Unknown` carrying the original geometry.  Nothing is dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Optional

from ..geometry.bbox import BBox


@dataclass(repr=False)
class Provenance:
    """Where a node came from and why we believe it."""

    glyph_ids: list[int] = field(default_factory=list)
    rule_ids: list[int] = field(default_factory=list)
    bbox: Optional[BBox] = None
    confidence: float = 1.0
    evidence: dict[str, Any] = field(default_factory=dict)
    rule_name: Optional[str] = None      # which recogniser fired

    def merged(self, *others: "Provenance") -> "Provenance":
        gids = list(self.glyph_ids)
        rids = list(self.rule_ids)
        boxes = [self.bbox]
        conf = self.confidence
        for o in others:
            gids += o.glyph_ids
            rids += o.rule_ids
            boxes.append(o.bbox)
            conf = min(conf, o.confidence)
        return Provenance(sorted(set(gids)), sorted(set(rids)),
                          BBox.union([b for b in boxes if b]), conf,
                          dict(self.evidence), self.rule_name)

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "glyph_ids": self.glyph_ids,
            "rule_ids": self.rule_ids,
            "confidence": round(self.confidence, 6),
        }
        if self.bbox:
            out["bbox"] = [round(v, 4) for v in self.bbox.as_list()]
        if self.rule_name:
            out["rule"] = self.rule_name
        if self.evidence:
            out["evidence"] = {
                k: (round(v, 6) if isinstance(v, float) else v)
                for k, v in self.evidence.items()
            }
        return out


_NODE_COUNTER = [0]


@dataclass(repr=False)
class MathNode:
    """Base class.  ``children`` is the ordered child list; subclasses name the slots."""

    prov: Provenance = field(default_factory=Provenance)
    children: list["MathNode"] = field(default_factory=list)
    node_id: int = field(default=0)

    def __post_init__(self) -> None:
        if not self.node_id:
            _NODE_COUNTER[0] += 1
            self.node_id = _NODE_COUNTER[0]

    # -- identity -----------------------------------------------------------------
    @property
    def kind(self) -> str:
        return type(self).__name__

    @property
    def bbox(self) -> Optional[BBox]:
        if self.prov.bbox:
            return self.prov.bbox
        return BBox.union([c.bbox for c in self.children if c.bbox])

    # -- traversal ----------------------------------------------------------------
    def walk(self) -> Iterator["MathNode"]:
        yield self
        for c in self.children:
            yield from c.walk()

    def find(self, node_id: int) -> Optional["MathNode"]:
        for n in self.walk():
            if n.node_id == node_id:
                return n
        return None

    # -- confidence -----------------------------------------------------------------
    def structural_confidence(self) -> float:
        """The weakest *structural* inference in this subtree.

        Deliberately excludes :class:`Space`, whose confidence measures something else:
        how cleanly a gap lands on one of TeX's glue widths.  A real paper is full of
        ``\\hskip``, ``\\phantom`` and stretched alignment glue that no inter-atom table
        explains, and letting that drag down the score for a perfectly recovered
        fraction would make the number useless.
        """
        return min((n.prov.confidence for n in self.walk()
                    if not isinstance(n, Space)), default=1.0)

    def spacing_confidence(self) -> float:
        """How well the gaps between atoms are accounted for by TeX's glue table."""
        return min((n.prov.confidence for n in self.walk()
                    if isinstance(n, Space)), default=1.0)

    # -- comparison ---------------------------------------------------------------
    def signature(self) -> Any:
        """A canonical, provenance-free form for comparing against ground truth."""
        return (self.kind, tuple(c.signature() for c in self.children))

    # -- serialisation ------------------------------------------------------------
    def _payload(self) -> dict[str, Any]:
        return {}

    def to_json(self) -> dict[str, Any]:
        out = {"kind": self.kind, "id": self.node_id}
        out.update(self._payload())
        out["provenance"] = self.prov.to_json()
        if self.children:
            out["children"] = [c.to_json() for c in self.children]
        return out

    def __repr__(self) -> str:
        inner = ", ".join(repr(c) for c in self.children)
        return f"{self.kind}({inner})"


# --------------------------------------------------------------------------- leaves

@dataclass(repr=False)
class Leaf(MathNode):
    """A single printed symbol."""

    text: str = ""
    glyph: Optional[str] = None
    font: Optional[str] = None
    mathvariant: str = "normal"
    atom: str = "Ord"

    def signature(self) -> Any:
        return (self.kind, self.text)

    def _payload(self) -> dict[str, Any]:
        return {"text": self.text, "glyph": self.glyph, "font": self.font,
                "mathvariant": self.mathvariant, "atom": self.atom}

    def __repr__(self) -> str:
        return f"{self.kind}({self.text!r})"


class Identifier(Leaf):
    """A variable or function name -> ``mi``."""


class Number(Leaf):
    """A numeric literal -> ``mn``."""


class Operator(Leaf):
    """An operator, relation, delimiter or punctuation mark -> ``mo``."""


class Text(Leaf):
    """A run of upright prose inside mathematics -> ``mtext``."""


@dataclass(repr=False)
class Unknown(Leaf):
    """A glyph we could not explain.  Kept, with its geometry, rather than discarded."""

    reason: str = ""

    def signature(self) -> Any:
        return ("Unknown", self.text)

    def _payload(self) -> dict[str, Any]:
        d = super()._payload()
        d["reason"] = self.reason
        return d


@dataclass(repr=False)
class Space(MathNode):
    """Explicit horizontal space wide enough that TeX must have been told to insert it."""

    width_em: float = 0.0

    def signature(self) -> Any:
        return ("Space",)

    def _payload(self) -> dict[str, Any]:
        return {"width_em": round(self.width_em, 4)}


# ----------------------------------------------------------------------- containers

@dataclass(repr=False)
class Row(MathNode):
    """A horizontal sequence -> ``mrow``."""

    def signature(self) -> Any:
        # Spacing is presentation, not structure: an author's \\, does not change what
        # the expression *is*, so it stays out of the comparison signature (it is still
        # in the tree, the provenance and the MathML).
        kids = tuple(c.signature() for c in self.children
                     if not isinstance(c, Space))
        if len(kids) == 1:
            return kids[0]
        return ("Row", kids)


@dataclass(repr=False)
class Fraction(MathNode):
    """``mfrac``.  ``children == [numerator, denominator]``."""

    line_thickness: Optional[float] = None    # pt; 0 means \atop / \choose

    @property
    def numerator(self) -> MathNode: return self.children[0]
    @property
    def denominator(self) -> MathNode: return self.children[1]

    def _payload(self) -> dict[str, Any]:
        return {"line_thickness": (round(self.line_thickness, 5)
                                   if self.line_thickness is not None else None)}


@dataclass(repr=False)
class Superscript(MathNode):
    """``msup``.  ``children == [base, script]``."""


@dataclass(repr=False)
class Subscript(MathNode):
    """``msub``.  ``children == [base, script]``."""


@dataclass(repr=False)
class SubSup(MathNode):
    """``msubsup``.  ``children == [base, sub, sup]``."""


@dataclass(repr=False)
class UnderOver(MathNode):
    """``munder`` / ``mover`` / ``munderover`` -- limits set above and below a base.

    ``children == [base, under_or_none, over_or_none]`` with missing slots omitted;
    ``has_under`` / ``has_over`` say which are present.
    """

    has_under: bool = False
    has_over: bool = False

    def _payload(self) -> dict[str, Any]:
        return {"has_under": self.has_under, "has_over": self.has_over}

    def signature(self) -> Any:
        return (self.kind, self.has_under, self.has_over,
                tuple(c.signature() for c in self.children))


@dataclass(repr=False)
class Radical(MathNode):
    """``msqrt`` / ``mroot``.  ``children == [radicand]`` or ``[radicand, index]``."""

    @property
    def has_index(self) -> bool:
        return len(self.children) > 1


@dataclass(repr=False)
class Delimited(MathNode):
    """A fenced expression -> ``mrow`` with ``mo`` fences.

    ``children == [body]``; the fences themselves are recorded here rather than as
    children so that the body's structure is not polluted by them.
    """

    open: str = ""
    close: str = ""
    stretchy: bool = True
    open_glyph: Optional[str] = None
    close_glyph: Optional[str] = None

    def _payload(self) -> dict[str, Any]:
        return {"open": self.open, "close": self.close, "stretchy": self.stretchy,
                "open_glyph": self.open_glyph, "close_glyph": self.close_glyph}

    def signature(self) -> Any:
        return ("Delimited", self.open, self.close,
                tuple(c.signature() for c in self.children))


@dataclass(repr=False)
class LargeOperator(Leaf):
    """``\\sum``, ``\\int``, ... as a bare operator -> ``mo``.

    Limits, when present, are attached by wrapping this in :class:`UnderOver` or
    :class:`SubSup`, exactly as TeX itself does.
    """

    display: bool = False

    def _payload(self) -> dict[str, Any]:
        d = super()._payload()
        d["display"] = self.display
        return d


@dataclass(repr=False)
class Accent(MathNode):
    """``mover`` with ``accent="true"``.  ``children == [base]``."""

    accent: str = ""
    accent_glyph: Optional[str] = None
    stretchy: bool = False

    def _payload(self) -> dict[str, Any]:
        return {"accent": self.accent, "accent_glyph": self.accent_glyph,
                "stretchy": self.stretchy}

    def signature(self) -> Any:
        return ("Accent", self.accent, tuple(c.signature() for c in self.children))


@dataclass(repr=False)
class Overline(MathNode):
    """``\\overline`` -> ``mover`` with a bar.  ``children == [base]``."""


@dataclass(repr=False)
class Underline(MathNode):
    """``\\underline`` -> ``munder`` with a bar.  ``children == [base]``."""


@dataclass(repr=False)
class MatrixCell(MathNode):
    """``mtd``."""


@dataclass(repr=False)
class MatrixRow(MathNode):
    """``mtr``; children are :class:`MatrixCell`."""


@dataclass(repr=False)
class Matrix(MathNode):
    """``mtable``; children are :class:`MatrixRow`."""

    alignment: str = "center"

    def _payload(self) -> dict[str, Any]:
        return {"alignment": self.alignment}


@dataclass(repr=False)
class Lines(MathNode):
    """Several display lines, e.g. an ``align`` block, kept as a table."""
