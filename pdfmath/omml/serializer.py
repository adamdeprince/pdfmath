"""Office MathML (OMML) serialisation -- the equation format Word actually stores.

Word does not read Presentation MathML from its own file format; a ``.docx`` holds OMML
(ECMA-376 Part 1, clause 22.1) instead.  Emitting it is what lets a decompiled equation
be pasted into a document and then *edited*, rather than pinned in as a picture.

The tree maps cleanly except in three places.

**N-ary operators.**  OMML has a dedicated ``m:nary`` for sums, products and integrals,
carrying the operator character, whether the limits sit above and below or to the right,
and which limits exist.  A :class:`LargeOperator` wrapped in scripts becomes one of
these.  Its operand slot ``m:e`` is left *empty* and the operand follows as a sibling,
because that is what the source says: TeX does not scope ``x_i`` inside ``\\sum_i`` and
neither does the PDF, so filling the slot would invent a bracket nobody typed.

**Italics.**  A run inside ``m:oMath`` is already italic, and digits and operators are
already upright, so an ``m:rPr`` is emitted only where the font on the page disagrees
with that default -- the same test the MathML writer applies to ``mathvariant``.

**Fences.**  ``m:d`` defaults to parentheses, so both characters are always stated; an
absent fence (from ``\\left.``) is stated as the empty string, which is how Word spells
an invisible delimiter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
from xml.sax.saxutils import escape, quoteattr

from ..tree.nodes import (Accent, Delimited, Fraction, Identifier, LargeOperator, Leaf,
                          Lines, MathNode, Matrix, MatrixCell, MatrixRow, Number,
                          Operator, Overline, Radical, Row, Space, SubSup, Subscript,
                          Superscript, Text, UnderOver, Underline, Unknown)

OMML_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"

#: Our mathvariant -> (m:scr value, m:sty value).  ``None`` leaves the attribute out.
#: ``m:sty`` "p" is upright, "i" italic, "b" bold, "bi" bold italic.
_VARIANT = {
    "normal": (None, "p"),
    "italic": (None, None),          # the default inside m:oMath
    "bold": (None, "b"),
    "bold-italic": (None, "bi"),
    "sans-serif": ("sans-serif", "p"),
    "bold-sans-serif": ("sans-serif", "b"),
    "sans-serif-italic": ("sans-serif", "i"),
    "monospace": ("monospace", "p"),
    "double-struck": ("double-struck", "p"),
    "script": ("script", "p"),
    "bold-script": ("script", "b"),
    "fraktur": ("fraktur", "p"),
    "bold-fraktur": ("fraktur", "b"),
}

#: Operators Word draws as n-ary: a big glyph whose limits are part of the object.
_NARY = set("∑∏∐∫∬∭∮∯∰⋃⋂⋀⋁⨁⨂⨀")


@dataclass
class OmmlResult:
    """OMML markup, plus anything that could not be expressed in it."""

    omml: str
    unreproducible: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.unreproducible

    def __str__(self) -> str:
        return self.omml


class OmmlWriter:
    """Serialise a :class:`MathNode` to OMML."""

    def __init__(self, indent: bool = True, display: bool = False,
                 namespace: bool = True):
        self.indent = indent
        self.display = display
        self.namespace = namespace
        self.unreproducible: list[str] = []

    # -- entry point -----------------------------------------------------------------
    def to_string(self, node: MathNode) -> OmmlResult:
        self.unreproducible = []
        attrs = {"xmlns:m": OMML_NS} if self.namespace else {}
        depth = 1 if self.display else 0
        body = self._node(node, depth + 1)
        math = self._el("m:oMath", {} if self.display else attrs, body, depth)
        if self.display:
            math = self._el("m:oMathPara", attrs, math, 0)
        return OmmlResult(math, list(self.unreproducible))

    # -- xml helpers -----------------------------------------------------------------
    def _pad(self, d: int) -> str:
        return "  " * d if self.indent else ""

    def _nl(self) -> str:
        return "\n" if self.indent else ""

    def _el(self, name: str, attrs: dict, body: str, d: int) -> str:
        a = "".join(f" {k}={quoteattr(str(v))}" for k, v in attrs.items()
                    if v is not None)
        if body == "":
            return f"{self._pad(d)}<{name}{a}/>"
        if "\n" not in body:
            return f"{self._pad(d)}<{name}{a}>{body.strip()}</{name}>"
        return (f"{self._pad(d)}<{name}{a}>{self._nl()}{body}{self._nl()}"
                f"{self._pad(d)}</{name}>")

    def _val(self, name: str, value: str, d: int) -> str:
        """A property element, which carries its payload in the ``m:val`` attribute."""
        return self._el(name, {"m:val": value}, "", d)

    def _slot(self, name: str, node: Optional[MathNode], d: int) -> str:
        """One of OMML's named argument slots (``m:num``, ``m:sup``, ...)."""
        return self._el(name, {}, "" if node is None else self._node(node, d + 1), d)

    def _seq(self, parts: list[str]) -> str:
        return self._nl().join(p for p in parts if p)

    # -- dispatch --------------------------------------------------------------------
    def _node(self, node: MathNode, d: int) -> str:
        r = getattr(self, "_r_" + type(node).__name__, None)
        return r(node, d) if r is not None else self._r_Row(node, d)

    def _children(self, node: MathNode, d: int) -> str:
        return self._seq([self._node(c, d) for c in node.children])

    # -- runs ------------------------------------------------------------------------
    def _run(self, text: str, leaf: Optional[Leaf], d: int,
             preserve: bool = False) -> str:
        props = self._run_props(leaf, text, d + 1)
        t = self._el("m:t", {"xml:space": "preserve"} if preserve else {},
                     escape(text), d + 1)
        return self._el("m:r", {}, self._seq([props, t]), d)

    def _run_props(self, leaf: Optional[Leaf], text: str, d: int) -> str:
        """Only state a style where the page disagrees with OMML's own default.

        Inside ``m:oMath`` letters are italic and everything else upright, which is
        already what TeX does for cmmi variables, digits and operators.
        """
        if leaf is None or not any(c.isalpha() for c in text):
            return ""
        scr, sty = _VARIANT.get(leaf.mathvariant, (None, "p"))
        if scr is None and sty is None:
            return ""
        parts = []
        if scr is not None:
            parts.append(self._val("m:scr", scr, d + 1))
        if sty is not None:
            parts.append(self._val("m:sty", sty, d + 1))
        return self._el("m:rPr", {}, self._seq(parts), d)

    # -- leaves ----------------------------------------------------------------------
    def _r_Identifier(self, n: Identifier, d: int) -> str:
        return self._run(n.text, n, d)

    def _r_Number(self, n: Number, d: int) -> str:
        return self._run(n.text, n, d)

    def _r_Operator(self, n: Operator, d: int) -> str:
        return self._run(n.text, n, d)

    def _r_Text(self, n: Text, d: int) -> str:
        # m:nor marks a run as ordinary text rather than mathematics, which stops Word
        # italicising it and keeps its spaces.
        props = self._el("m:rPr", {}, self._el("m:nor", {}, "", d + 2), d + 1)
        t = self._el("m:t", {"xml:space": "preserve"}, escape(n.text), d + 1)
        return self._el("m:r", {}, self._seq([props, t]), d)

    def _r_LargeOperator(self, n: LargeOperator, d: int) -> str:
        # A bare large operator with no limits is still an n-ary, with both slots hidden.
        if n.text in _NARY:
            return self._nary(n, None, None, d, limits_above=n.display)
        return self._run(n.text, n, d)

    def _r_Unknown(self, n: Unknown, d: int) -> str:
        self.unreproducible.append(n.reason or "Unknown node")
        return self._run(n.text or "�", n, d)

    def _r_Space(self, n: Space, d: int) -> str:
        return self._run(" ", None, d, preserve=True)

    # -- containers ------------------------------------------------------------------
    def _r_Row(self, n: MathNode, d: int) -> str:
        return self._children(n, d)

    def _r_Fraction(self, n: Fraction, d: int) -> str:
        kind = ("noBar" if n.line_thickness is not None and n.line_thickness <= 0
                else "bar")
        props = self._el("m:fPr", {}, self._val("m:type", kind, d + 2), d + 1)
        return self._el("m:f", {}, self._seq([
            props,
            self._slot("m:num", n.children[0], d + 1),
            self._slot("m:den", n.children[1], d + 1)]), d)

    # -- scripts ---------------------------------------------------------------------
    def _r_Superscript(self, n: Superscript, d: int) -> str:
        base, sup = n.children
        if self._is_nary(base):
            return self._nary(base, None, sup, d)
        return self._el("m:sSup", {}, self._seq([
            self._slot("m:e", base, d + 1),
            self._slot("m:sup", sup, d + 1)]), d)

    def _r_Subscript(self, n: Subscript, d: int) -> str:
        base, sub = n.children
        if self._is_nary(base):
            return self._nary(base, sub, None, d)
        return self._el("m:sSub", {}, self._seq([
            self._slot("m:e", base, d + 1),
            self._slot("m:sub", sub, d + 1)]), d)

    def _r_SubSup(self, n: SubSup, d: int) -> str:
        base, sub, sup = n.children
        if self._is_nary(base):
            return self._nary(base, sub, sup, d)
        return self._el("m:sSubSup", {}, self._seq([
            self._slot("m:e", base, d + 1),
            self._slot("m:sub", sub, d + 1),
            self._slot("m:sup", sup, d + 1)]), d)

    def _r_UnderOver(self, n: UnderOver, d: int) -> str:
        base = n.children[0]
        rest = list(n.children[1:])
        under = rest.pop(0) if n.has_under else None
        over = rest.pop(0) if n.has_over else None
        if self._is_nary(base):
            return self._nary(base, under, over, d, limits_above=True)
        # Not an n-ary: Word stacks a limit on any base with m:limLow / m:limUpp, but
        # only one at a time, so both together nest.
        out = base
        if under is not None:
            out = _Wrapped("m:limLow", "m:lim", out, under)
        if over is not None:
            out = _Wrapped("m:limUpp", "m:lim", out, over)
        return self._wrapped(out, d)

    def _wrapped(self, node, d: int) -> str:
        if not isinstance(node, _Wrapped):
            return self._node(node, d)
        inner = (self._wrapped(node.base, d + 2) if isinstance(node.base, _Wrapped)
                 else self._node(node.base, d + 2))
        return self._el(node.tag, {}, self._seq([
            self._el("m:e", {}, inner, d + 1),
            self._slot(node.slot, node.limit, d + 1)]), d)

    def _is_nary(self, node: MathNode) -> bool:
        return isinstance(node, LargeOperator) and node.text in _NARY

    def _nary(self, op: LargeOperator, sub: Optional[MathNode],
              sup: Optional[MathNode], d: int, limits_above: Optional[bool] = None) -> str:
        """``m:nary``: the operator, where its limits sit, and which ones exist."""
        above = op.display if limits_above is None else limits_above
        props = [
            self._val("m:chr", op.text, d + 2),
            self._val("m:limLoc", "undOvr" if above else "subSup", d + 2),
            self._val("m:subHide", "0" if sub is not None else "1", d + 2),
            self._val("m:supHide", "0" if sup is not None else "1", d + 2),
        ]
        return self._el("m:nary", {}, self._seq([
            self._el("m:naryPr", {}, self._seq(props), d + 1),
            self._slot("m:sub", sub, d + 1),
            self._slot("m:sup", sup, d + 1),
            # Left empty on purpose -- see the module docstring.
            self._el("m:e", {}, "", d + 1)]), d)

    # -- radicals, fences, accents ---------------------------------------------------
    def _r_Radical(self, n: Radical, d: int) -> str:
        index = n.children[1] if n.has_index else None
        props = self._el("m:radPr", {},
                         self._val("m:degHide", "0" if index else "1", d + 2), d + 1)
        return self._el("m:rad", {}, self._seq([
            props,
            self._slot("m:deg", index, d + 1),
            self._slot("m:e", n.children[0], d + 1)]), d)

    def _r_Delimited(self, n: Delimited, d: int) -> str:
        props = self._el("m:dPr", {}, self._seq([
            self._val("m:begChr", n.open, d + 2),
            self._val("m:endChr", n.close, d + 2),
            self._val("m:grow", "1" if n.stretchy else "0", d + 2)]), d + 1)
        body = n.children[0] if n.children else None
        return self._el("m:d", {}, self._seq([props,
                                              self._slot("m:e", body, d + 1)]), d)

    def _r_Accent(self, n: Accent, d: int) -> str:
        props = self._el("m:accPr", {}, self._val("m:chr", n.accent, d + 2), d + 1)
        return self._el("m:acc", {}, self._seq([
            props, self._slot("m:e", n.children[0], d + 1)]), d)

    def _r_Overline(self, n: Overline, d: int) -> str:
        return self._bar(n, "top", d)

    def _r_Underline(self, n: Underline, d: int) -> str:
        return self._bar(n, "bot", d)

    def _bar(self, n: MathNode, pos: str, d: int) -> str:
        props = self._el("m:barPr", {}, self._val("m:pos", pos, d + 2), d + 1)
        return self._el("m:bar", {}, self._seq([
            props, self._slot("m:e", n.children[0], d + 1)]), d)

    # -- tables ----------------------------------------------------------------------
    def _r_Matrix(self, n: Matrix, d: int) -> str:
        cols = max((len(r.children) for r in n.children), default=1)
        just = {"left": "left", "right": "right"}.get(n.alignment, "center")
        mcpr = self._el("m:mcPr", {}, self._seq([
            self._val("m:count", str(cols), d + 5),
            self._val("m:mcJc", just, d + 5)]), d + 4)
        props = self._el("m:mPr", {},
                         self._el("m:mcs", {},
                                  self._el("m:mc", {}, mcpr, d + 3), d + 2), d + 1)
        return self._el("m:m", {}, self._seq(
            [props] + [self._node(r, d + 1) for r in n.children]), d)

    def _r_MatrixRow(self, n: MatrixRow, d: int) -> str:
        return self._el("m:mr", {}, self._seq(
            [self._node(c, d + 1) for c in n.children]), d)

    def _r_MatrixCell(self, n: MatrixCell, d: int) -> str:
        return self._el("m:e", {}, self._children(n, d + 1), d)

    def _r_Lines(self, n: Lines, d: int) -> str:
        return self._el("m:eqArr", {}, self._seq(
            [self._slot("m:e", c, d + 1) for c in n.children]), d)


@dataclass
class _Wrapped:
    """A pending ``m:limLow``/``m:limUpp``, so the two can nest without a second pass."""

    tag: str
    slot: str
    base: object
    limit: MathNode


def to_omml(node: MathNode, indent: bool = True, display: bool = False,
            namespace: bool = True) -> OmmlResult:
    """Convenience wrapper around :class:`OmmlWriter`."""
    return OmmlWriter(indent, display, namespace).to_string(node)
