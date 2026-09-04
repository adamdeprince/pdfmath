"""Serialise a recovered tree back to LaTeX.

This exists for one reason: a decompiler is validated by *recompiling*.  If the structure
we recovered is right, feeding it back to pdfTeX must put every glyph in the same place
it was on the original page.  That test needs no ground truth and no second system, and
it works on any born-digital TeX document -- see pdfmath.eval.roundtrip.

Fidelity therefore matters more than legibility.  Two consequences:

* **Commands are chosen by atom class.**  cmsy slot 0x6A is both ``\\mid`` (a relation)
  and ``\\vert`` (ordinary); emitting the wrong one changes the inter-atom glue and moves
  everything after it.  The tables in latex/data are generated from LaTeX's own
  declarations and keep the class.
* **Measured spaces are re-emitted as they were measured**, in ``mu``, rather than
  guessed at from a name.

Where a glyph could not be identified at all the output is marked unreproducible rather
than patched over, because a round trip that quietly substitutes something else proves
nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..fonts.normalize import identify
from ..fonts.symbols import lookup
from ..tree.nodes import (Accent, Delimited, Fraction, Identifier, LargeOperator, Leaf,
                          Lines, MathNode, Matrix, MatrixCell, MatrixRow, Number,
                          Operator, Overline, Radical, Row, Space, SubSup, Subscript,
                          Superscript, Text, UnderOver, Underline, Unknown)
from .data.tex_commands import ACCENT_BY_GLYPH, BY_CLASS, COMMAND_BY_GLYPH

#: MathML mathvariant -> the LaTeX alphabet command that selects that font.
_ALPHABET = {
    "normal": "\\mathrm", "bold": "\\mathbf", "italic": None,
    "bold-italic": "\\boldsymbol", "sans-serif": "\\mathsf", "monospace": "\\mathtt",
    "double-struck": "\\mathbb", "script": "\\mathcal", "bold-script": "\\mathcal",
    "fraktur": "\\mathfrak", "bold-fraktur": "\\mathfrak",
    "bold-sans-serif": "\\mathsf", "sans-serif-italic": "\\mathsf",
}

#: base delimiter name -> (opening glyph, closing glyph) at text size
_DELIM_GLYPHS = {
    "paren": ("parenleft", "parenright"),
    "bracket": ("bracketleft", "bracketright"),
    "brace": ("braceleft", "braceright"),
    "angbracket": ("angbracketleft", "angbracketright"),
    "floor": ("floorleft", "floorright"),
    "ceiling": ("ceilingleft", "ceilingright"),
    "bar": ("bar", "bar"),
    "bardbl": ("bardbl", "bardbl"),
}

#: merged-token text -> the command that produces the same glyphs
_MERGED = {"…": "\\ldots", "⋯": "\\cdots"}

#: characters TeX reads as markup rather than as themselves
_ESCAPE = {"#": "\\#", "$": "\\$", "%": "\\%", "&": "\\&", "_": "\\_",
           "{": "\\{", "}": "\\}", "~": "\\textasciitilde{}",
           "^": "\\textasciicircum{}", "\\": "\\backslash"}

#: text encodings, whose glyphs are not the ones a bare character selects in math mode
_TEXT_ENCODINGS = {"OT1", "OT1TT", "CMTI", "CMSS"}

#: expressions that must be braced before a script can be attached to them
_NEEDS_BRACES = (Superscript, Subscript, SubSup, UnderOver, Row, Lines)


@dataclass
class LatexResult:
    """The LaTeX, and an honest account of what could not be put back."""

    latex: str
    unreproducible: list[str] = field(default_factory=list)

    @property
    def faithful(self) -> bool:
        return not self.unreproducible

    def __str__(self) -> str:
        return self.latex


class LatexWriter:
    def __init__(self, explicit_classes: bool = False):
        #: wrap every leaf in \mathord{} and friends, forcing the recovered atom class
        self.explicit_classes = explicit_classes
        self.unreproducible: list[str] = []

    # -- entry point ---------------------------------------------------------------
    def render(self, node: MathNode) -> LatexResult:
        self.unreproducible = []
        return LatexResult(self._node(node).strip(), list(self.unreproducible))

    # -- helpers -------------------------------------------------------------------
    def _brace(self, node: MathNode) -> str:
        """A script base, braced so that TeX groups it the way the tree says.

        The leading ``{}`` is not decoration: tex.web 1186 replaces an Ord noad by an
        accent noad when a group contains nothing else, so ``{\\hat u_a}_b`` collapses
        into one accent with two subscripts and is rejected.  An empty Ord in front makes
        the group two noads, and it is exactly layout-neutral.
        """
        body = self._node(node)
        if isinstance(node, _NEEDS_BRACES) or isinstance(node, (Accent, Overline)):
            return "{{}" + body + "}"
        if isinstance(node, Leaf) and len(body) <= 1:
            return body
        return "{" + body + "}"

    def _group(self, node: MathNode) -> str:
        return "{" + self._node(node) + "}"

    def _leaf_command(self, leaf: Leaf) -> str:
        return self._command(leaf)[0]

    def _command(self, leaf: Leaf) -> tuple[str, bool]:
        """(LaTeX for this leaf, whether it came from LaTeX's own tables).

        The flag matters: a command out of the tables carries its font *and* its atom
        class, so wrapping it in ``\\mathrm`` would turn cmr's ``+`` -- a Bin -- into an
        Ord and change every space around it.  Only a bare character we fell back to
        needs its font naming.
        """
        if leaf.text in _MERGED:
            return _MERGED[leaf.text], True
        if leaf.glyph:
            key = (self._encoding(leaf), leaf.glyph)
            by_class = BY_CLASS.get(key, {})
            cmd = by_class.get(leaf.atom) or COMMAND_BY_GLYPH.get(key)
            if cmd:
                return cmd, True
        if leaf.text and all(c.isalnum() for c in leaf.text):
            return leaf.text, False                # a merged digit run or roman word
        if leaf.text and all(0x20 <= ord(c) < 0x7F for c in leaf.text):
            # A text-font glyph inside mathematics -- the comma and full stop of an
            # \hbox, say.  There is no math command for it, but the character itself
            # plus the alphabet wrapper selects the same font and the same slot.
            return "".join(_ESCAPE.get(c, c) for c in leaf.text), False
        if leaf.text:
            self.unreproducible.append(
                f"no command for {leaf.glyph or leaf.text!r}")
            return leaf.text, False
        self.unreproducible.append(f"unidentified glyph in {leaf.kind}")
        return "", False

    @staticmethod
    def _encoding(leaf: Leaf) -> str:
        return identify(leaf.font or "").encoding or "OML"

    def _wrap_alphabet(self, body: str, leaf: Leaf) -> str:
        encoding = self._encoding(leaf)
        alphabet = _ALPHABET.get(leaf.mathvariant)
        if leaf.mathvariant == "italic" and encoding in _TEXT_ENCODINGS:
            # cmti's italic is not cmmi's: a bare "e" in maths selects math italic, and
            # a text-italic "e" needs \mathit to get the same glyph back.
            alphabet = "\\mathit"
        if alphabet is None:
            return body
        # A command already carries its own font; only literal characters need wrapping.
        if body.startswith("\\"):
            return body
        return f"{alphabet}{{{body}}}"

    def _delim(self, glyph: Optional[str], fallback: str, opening: bool) -> str:
        if glyph:
            base = lookup(glyph).base
            pair = _DELIM_GLYPHS.get(base or "")
            if pair:
                name = pair[0] if opening else pair[1]
                for enc in ("OMS", "OT1", "OML"):
                    cmd = COMMAND_BY_GLYPH.get((enc, name))
                    if cmd:
                        return cmd
        if fallback in ("{", "}"):
            return "\\lbrace" if fallback == "{" else "\\rbrace"
        return fallback or "."

    def _large_op(self, leaf: LargeOperator) -> str:
        base = lookup(leaf.glyph).base if leaf.glyph else None
        cmd = COMMAND_BY_GLYPH.get(("OMX", f"{base}text")) if base else None
        return cmd or self._leaf_command(leaf)

    # -- dispatch --------------------------------------------------------------------
    def _node(self, node: MathNode) -> str:
        return getattr(self, "_n_" + type(node).__name__, self._n_Row)(node)

    def _n_Row(self, n: MathNode) -> str:
        return " ".join(p for p in (self._node(c) for c in n.children) if p)

    def _n_Identifier(self, n: Identifier) -> str:
        body, from_table = self._command(n)
        if from_table and body.startswith("\\"):
            return body
        return self._wrap_alphabet(body, n)

    def _n_Number(self, n: Number) -> str:
        body, from_table = self._command(n)
        return body if from_table else self._wrap_alphabet(body, n)

    def _n_Operator(self, n: Operator) -> str:
        # A command out of LaTeX's tables carries its font *and* its atom class, so
        # wrapping it would turn cmr's "+" from a Bin into an Ord and change every space
        # around it.  Only a bare character we fell back to needs its font naming.
        body, from_table = self._command(n)
        return body if from_table else self._wrap_alphabet(body, n)

    def _n_Text(self, n: Text) -> str:
        return f"\\text{{{n.text}}}"

    def _n_Unknown(self, n: Unknown) -> str:
        self.unreproducible.append(n.reason or "Unknown node")
        return ""

    def _n_LargeOperator(self, n: LargeOperator) -> str:
        return self._large_op(n)

    def _n_Space(self, n: Space) -> str:
        return f"\\mskip {n.width_em * 18.0:.3f}mu"

    def _n_Fraction(self, n: Fraction) -> str:
        num, den = self._node(n.children[0]), self._node(n.children[1])
        if n.line_thickness is not None and n.line_thickness <= 0:
            return "{" + num + " \\atop " + den + "}"
        return f"\\frac{{{num}}}{{{den}}}"

    def _n_Superscript(self, n: Superscript) -> str:
        return f"{self._brace(n.children[0])}^{self._group(n.children[1])}"

    def _n_Subscript(self, n: Subscript) -> str:
        return f"{self._brace(n.children[0])}_{self._group(n.children[1])}"

    def _n_SubSup(self, n: SubSup) -> str:
        base, sub, sup = n.children
        core = f"{self._brace(base)}_{self._group(sub)}^{self._group(sup)}"
        # An operator that took scripts rather than limits must say so, or display style
        # will move them under and over it.
        if isinstance(base, LargeOperator):
            return f"{self._node(base)}\\nolimits_{self._group(sub)}^{self._group(sup)}"
        return core

    def _n_UnderOver(self, n: UnderOver) -> str:
        base = n.children[0]
        i = 1
        under = over = None
        if n.has_under:
            under = n.children[i]; i += 1
        if n.has_over:
            over = n.children[i]
        head = self._node(base)
        if isinstance(base, LargeOperator):
            head += "\\limits"
        else:
            head = f"\\mathop{{{head}}}\\limits"
        if under is not None:
            head += "_" + self._group(under)
        if over is not None:
            head += "^" + self._group(over)
        return head

    def _n_Radical(self, n: Radical) -> str:
        body = self._node(n.children[0])
        if len(n.children) > 1:
            return f"\\sqrt[{self._node(n.children[1])}]{{{body}}}"
        return f"\\sqrt{{{body}}}"

    def _n_Delimited(self, n: Delimited) -> str:
        op = self._delim(n.open_glyph, n.open, opening=True)
        cl = self._delim(n.close_glyph, n.close, opening=False)
        body = self._node(n.children[0]) if n.children else ""
        if n.stretchy:
            return f"\\left{op} {body} \\right{cl}"
        return f"{op} {body} {cl}"

    def _n_Accent(self, n: Accent) -> str:
        cmd = next((c for (enc, g), c in ACCENT_BY_GLYPH.items()
                    if g == (n.accent_glyph or "")), None)
        if cmd is None:
            self.unreproducible.append(f"no command for accent {n.accent_glyph!r}")
            cmd = "\\hat"
        return f"{cmd}{{{self._node(n.children[0])}}}"

    def _n_Overline(self, n: Overline) -> str:
        return f"\\overline{{{self._node(n.children[0])}}}"

    def _n_Underline(self, n: Underline) -> str:
        return f"\\underline{{{self._node(n.children[0])}}}"

    def _n_Matrix(self, n: Matrix) -> str:
        rows = " \\\\ ".join(self._node(r) for r in n.children)
        return f"\\begin{{matrix}} {rows} \\end{{matrix}}"

    def _n_MatrixRow(self, n: MatrixRow) -> str:
        return " & ".join(self._node(c) for c in n.children)

    def _n_MatrixCell(self, n: MatrixCell) -> str:
        return self._n_Row(n)

    def _n_Lines(self, n: Lines) -> str:
        rows = " \\\\ ".join(self._node(c) for c in n.children)
        return f"\\begin{{matrix}} {rows} \\end{{matrix}}"


def to_latex(node: MathNode, explicit_classes: bool = False) -> LatexResult:
    """Serialise a recovered tree back to LaTeX."""
    return LatexWriter(explicit_classes).render(node)
