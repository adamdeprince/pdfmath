"""Presentation MathML serialisation.

The tree is already isomorphic to Presentation MathML, so this is mostly a rename.  Three
things need care.

**mathvariant.**  MathML's default for ``mi`` is italic for a single character and upright
for longer tokens, which happens to match TeX for Latin variables and function names but
*not* for upright capital Greek (``\\Gamma`` comes from cmr), for calligraphic capitals
(cmsy), for blackboard bold (msbm) or for fraktur (eufm).  We know which font each glyph
came from, so we emit the attribute exactly when it differs from the default, and not
otherwise.

**Stretchiness.**  We know from the PDF whether a fence was stretched -- a ``\\left(``
produces an axis-centred cmex glyph, a typed ``(`` does not -- so the ``stretchy``
attribute states a measured fact rather than a guess.

**Provenance.**  With ``include_provenance`` every element carries its node id and the
glyph and rule ids behind it, so a reader can go from a rendered symbol back to the bytes
it came from.  It is off by default because the attributes are not in the MathML schema.
"""

from __future__ import annotations

from typing import Any, Optional
from xml.sax.saxutils import escape, quoteattr

from ..tree.nodes import (Accent, Delimited, Fraction, Identifier, LargeOperator,
                          Leaf, Lines, MathNode, Matrix, MatrixCell, MatrixRow, Number,
                          Operator, Overline, Radical, Row, Space, SubSup, Subscript,
                          Superscript, Text, UnderOver, Underline, Unknown)

MATHML_NS = "http://www.w3.org/1998/Math/MathML"

#: TeX font family -> the MathML mathvariant that reproduces it.
_VARIANT = {
    "normal": "normal", "bold": "bold", "italic": "italic",
    "bold-italic": "bold-italic", "sans-serif": "sans-serif",
    "bold-sans-serif": "bold-sans-serif", "sans-serif-italic": "sans-serif-italic",
    "monospace": "monospace", "double-struck": "double-struck",
    "script": "script", "bold-script": "bold-script",
    "fraktur": "fraktur", "bold-fraktur": "bold-fraktur",
}


class MathMLWriter:
    """Serialise a :class:`MathNode` to Presentation MathML."""

    def __init__(self, indent: bool = True, include_provenance: bool = False,
                 display: str = "block", namespace: bool = True):
        self.indent = indent
        self.include_provenance = include_provenance
        self.display = display
        self.namespace = namespace

    # -- entry point ---------------------------------------------------------------
    def to_string(self, node: MathNode) -> str:
        attrs: dict[str, Any] = {"display": self.display}
        if self.namespace:
            attrs["xmlns"] = MATHML_NS
        body = self._render(node, 1)
        return self._tag("math", attrs, body, 0)

    # -- helpers -------------------------------------------------------------------
    def _pad(self, depth: int) -> str:
        return "  " * depth if self.indent else ""

    def _nl(self) -> str:
        return "\n" if self.indent else ""

    def _prov_attrs(self, node: MathNode) -> dict[str, Any]:
        if not self.include_provenance:
            return {}
        out: dict[str, Any] = {"id": f"pdfmath-{node.node_id}"}
        if node.prov.glyph_ids:
            out["data-glyphs"] = " ".join(str(i) for i in node.prov.glyph_ids)
        if node.prov.rule_ids:
            out["data-rules"] = " ".join(str(i) for i in node.prov.rule_ids)
        if node.prov.confidence < 1.0:
            out["data-confidence"] = f"{node.prov.confidence:.4f}"
        if node.prov.rule_name:
            out["data-recogniser"] = node.prov.rule_name
        return out

    def _tag(self, name: str, attrs: dict[str, Any], body: str, depth: int) -> str:
        a = "".join(f" {k}={quoteattr(str(v))}" for k, v in attrs.items()
                    if v is not None)
        if body == "":
            return f"{self._pad(depth)}<{name}{a}/>"
        if "\n" not in body:
            return f"{self._pad(depth)}<{name}{a}>{body.strip()}</{name}>"
        return (f"{self._pad(depth)}<{name}{a}>{self._nl()}"
                f"{body}{self._nl()}{self._pad(depth)}</{name}>")

    def _children(self, node: MathNode, depth: int) -> str:
        return self._nl().join(self._render(c, depth) for c in node.children)

    def _wrap_row(self, node: MathNode, depth: int) -> str:
        """A MathML slot takes exactly one element; wrap a multi-child row."""
        return self._render(node, depth)

    # -- variants ------------------------------------------------------------------
    def _variant_attr(self, leaf: Leaf, element: str) -> Optional[str]:
        want = _VARIANT.get(leaf.mathvariant, "normal")
        if element == "mi":
            default = "italic" if len(leaf.text) == 1 else "normal"
        else:
            default = "normal"
        return None if want == default else want

    # -- dispatch ------------------------------------------------------------------
    def _render(self, node: MathNode, depth: int) -> str:
        r = getattr(self, "_r_" + type(node).__name__, None)
        if r is None:
            return self._r_Row(node, depth) if node.children else ""
        return r(node, depth)

    # leaves
    def _r_Identifier(self, n: Identifier, d: int) -> str:
        a = self._prov_attrs(n)
        v = self._variant_attr(n, "mi")
        if v:
            a["mathvariant"] = v
        return self._tag("mi", a, escape(n.text), d)

    def _r_Number(self, n: Number, d: int) -> str:
        return self._tag("mn", self._prov_attrs(n), escape(n.text), d)

    def _r_Operator(self, n: Operator, d: int) -> str:
        a = self._prov_attrs(n)
        # A variant is only meaningful for letter-like content.  TeX draws the maths
        # comma and the "less" sign from cmmi, but that says where the glyph lives, not
        # that the punctuation is italic, and asserting mathvariant="italic" on an <mo>
        # would change how a renderer treats it.
        if n.text and any(c.isalpha() for c in n.text):
            v = self._variant_attr(n, "mo")
            if v:
                a["mathvariant"] = v
        return self._tag("mo", a, escape(n.text), d)

    def _r_Text(self, n: Text, d: int) -> str:
        return self._tag("mtext", self._prov_attrs(n), escape(n.text), d)

    def _r_LargeOperator(self, n: LargeOperator, d: int) -> str:
        a = self._prov_attrs(n)
        a["largeop"] = "true"
        a["symmetric"] = "true"
        if n.display:
            a["movablelimits"] = "false"
        return self._tag("mo", a, escape(n.text), d)

    def _r_Unknown(self, n: Unknown, d: int) -> str:
        a = self._prov_attrs(n)
        a["class"] = "pdfmath-unknown"
        a["data-reason"] = n.reason or None
        if n.text:
            return self._tag("mi", a, escape(n.text), d)
        return self._tag("mtext", a, "□", d)     # WHITE SQUARE placeholder

    def _r_Space(self, n: Space, d: int) -> str:
        a = self._prov_attrs(n)
        a["width"] = f"{n.width_em:.3f}em"
        return self._tag("mspace", a, "", d)

    # containers
    def _r_Row(self, n: MathNode, d: int) -> str:
        if len(n.children) == 1 and not self.include_provenance:
            return self._render(n.children[0], d)
        return self._tag("mrow", self._prov_attrs(n), self._children(n, d + 1), d)

    def _r_Fraction(self, n: Fraction, d: int) -> str:
        a = self._prov_attrs(n)
        if n.line_thickness is not None and n.line_thickness <= 0:
            a["linethickness"] = "0"
        return self._tag("mfrac", a, self._children(n, d + 1), d)

    def _r_Superscript(self, n: Superscript, d: int) -> str:
        return self._tag("msup", self._prov_attrs(n), self._children(n, d + 1), d)

    def _r_Subscript(self, n: Subscript, d: int) -> str:
        return self._tag("msub", self._prov_attrs(n), self._children(n, d + 1), d)

    def _r_SubSup(self, n: SubSup, d: int) -> str:
        return self._tag("msubsup", self._prov_attrs(n), self._children(n, d + 1), d)

    def _r_UnderOver(self, n: UnderOver, d: int) -> str:
        tag = ("munderover" if n.has_under and n.has_over
               else "munder" if n.has_under else "mover")
        return self._tag(tag, self._prov_attrs(n), self._children(n, d + 1), d)

    def _r_Radical(self, n: Radical, d: int) -> str:
        if n.has_index:
            return self._tag("mroot", self._prov_attrs(n), self._children(n, d + 1), d)
        return self._tag("msqrt", self._prov_attrs(n), self._children(n, d + 1), d)

    def _r_Delimited(self, n: Delimited, d: int) -> str:
        parts = []
        fence_attrs = {"fence": "true", "stretchy": "true" if n.stretchy else "false"}
        if n.open:
            parts.append(self._tag("mo", dict(fence_attrs, form="prefix"),
                                   escape(n.open), d + 1))
        parts.append(self._render(n.children[0], d + 1) if n.children
                     else self._tag("mrow", {}, "", d + 1))
        if n.close:
            parts.append(self._tag("mo", dict(fence_attrs, form="postfix"),
                                   escape(n.close), d + 1))
        return self._tag("mrow", self._prov_attrs(n), self._nl().join(parts), d)

    def _r_Accent(self, n: Accent, d: int) -> str:
        a = self._prov_attrs(n)
        a["accent"] = "true"
        acc = self._tag("mo", {"stretchy": "true" if n.stretchy else "false"},
                        escape(n.accent), d + 1)
        body = self._nl().join([self._render(n.children[0], d + 1), acc])
        return self._tag("mover", a, body, d)

    def _r_Overline(self, n: Overline, d: int) -> str:
        a = self._prov_attrs(n)
        a["accent"] = "false"
        bar = self._tag("mo", {"stretchy": "true"}, "‾", d + 1)
        return self._tag("mover", a,
                         self._nl().join([self._render(n.children[0], d + 1), bar]), d)

    def _r_Underline(self, n: Underline, d: int) -> str:
        a = self._prov_attrs(n)
        a["accentunder"] = "false"
        bar = self._tag("mo", {"stretchy": "true"}, "_", d + 1)
        return self._tag("munder", a,
                         self._nl().join([self._render(n.children[0], d + 1), bar]), d)

    def _r_Matrix(self, n: Matrix, d: int) -> str:
        return self._tag("mtable", self._prov_attrs(n), self._children(n, d + 1), d)

    def _r_MatrixRow(self, n: MatrixRow, d: int) -> str:
        return self._tag("mtr", self._prov_attrs(n), self._children(n, d + 1), d)

    def _r_MatrixCell(self, n: MatrixCell, d: int) -> str:
        return self._tag("mtd", self._prov_attrs(n), self._children(n, d + 1), d)

    def _r_Lines(self, n: Lines, d: int) -> str:
        rows = self._nl().join(
            self._tag("mtr", {}, self._tag("mtd", {}, self._render(c, d + 3), d + 2),
                      d + 1)
            for c in n.children)
        return self._tag("mtable", self._prov_attrs(n), rows, d)


def to_mathml(node: MathNode, indent: bool = True, include_provenance: bool = False,
              display: str = "block", namespace: bool = True) -> str:
    """Convenience wrapper around :class:`MathMLWriter`."""
    return MathMLWriter(indent, include_provenance, display, namespace).to_string(node)
