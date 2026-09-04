r"""WordPerfect 5.1 equation language.

The Equation Editor that shipped with WordPerfect 5.1 in 1989 took a linear command
language descended from troff's ``eqn``: ``{x} over {y}``, ``x sup 2``, ``sqrt {x}``,
``sum from {k=1} to n``.  It is a perfectly good target -- closer to our tree than
AsciiMath is, because its braces group without printing, so a compound base needs no
special trick.

**What is verified and what is not.**  The core grammar below is taken from a WordPerfect
equation FAQ (linked in the README): ``over``, ``sup``/``sub`` and their ``^``/``_``
shorthands, ``sqrt``, ``nroot``, ``from``/``to``, ``left``/``right`` used strictly in
pairs, ``{}`` for grouping, ``~`` for a full space and a backtick for a thin one,
``matrix`` with ``&`` between columns and ``#`` between rows, ``matform``, ``stack``,
``stackalign``, ``func`` for upright function names, ``int``, ``sum`` and ``lim``.

The accent commands (``overline``, ``bar``, ``vec``, ``hat``, ``tilde``, ``dot``,
``ddot``) and the Greek convention -- lower-case name for a lower-case letter,
capitalised name for a capital -- follow the ``eqn`` family and the WordPerfect symbol
palette, but I could not find a citable 5.1 reference for them.  They are marked in
:data:`UNVERIFIED` so a reader who remembers the editor can correct them in one place.

**There is no oracle for this one.**  The MathML, AsciiMath and OMML writers are each
checked by reading their output back with software that is not ours; nothing available
parses WordPerfect equations, so this writer is covered by goldens alone.  That is a
genuinely weaker guarantee and is stated rather than glossed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..tree.nodes import (Accent, Delimited, Fraction, Identifier, LargeOperator, Leaf,
                          Lines, MathNode, Matrix, MatrixCell, MatrixRow, Number,
                          Operator, Overline, Radical, Row, Space, SubSup, Subscript,
                          Superscript, Text, UnderOver, Underline, Unknown)

#: Commands whose spelling follows the ``eqn`` family and the symbol palette rather than
#: a citable WordPerfect 5.1 reference.  See the module docstring.
UNVERIFIED = frozenset({
    "overline", "underline", "bar", "vec", "hat", "tilde", "dot", "ddot",
    "lbrace", "rbrace", "langle", "rangle", "lfloor", "rfloor", "lceil", "rceil",
    "none",
})

#: Unicode -> WordPerfect command name.  Characters that stand for themselves -- digits,
#: Latin letters, ``+``, ``-``, ``=`` -- are not listed.
_TOKENS = {
    # relations
    "≤": "leq", "≥": "geq", "≠": "neq", "≈": "approx", "≡": "equiv", "∼": "sim",
    "≅": "cong", "∝": "prop", "≪": "ll", "≫": "gg", "≺": "prec", "≻": "succ",
    # binary operators
    "×": "times", "÷": "div", "±": "pm", "∓": "mp", "⋅": "cdot", "∘": "circ",
    "⊗": "otimes", "⊕": "oplus", "∗": "ast", "⋆": "star", "∪": "cup", "∩": "cap",
    "∧": "wedge", "∨": "vee", "−": "-",
    # sets and logic
    "∈": "in", "∉": "notin", "⊂": "subset", "⊆": "subseteq", "⊃": "supset",
    "⊇": "supseteq", "∅": "emptyset", "∀": "forall", "∃": "exists", "¬": "neg",
    "∴": "therefore", "∵": "because",
    # arrows
    "→": "->", "←": "<-", "↔": "<->", "⇒": "=>", "⇐": "<=", "⇔": "<=>",
    "↦": "mapsto", "↑": "uparrow", "↓": "downarrow",
    # miscellaneous
    "∞": "inf", "∂": "partial", "∇": "grad", "ℵ": "aleph", "∠": "angle",
    "…": "dotslow", "⋯": "dotsaxis", "⋮": "dotsvert", "⋱": "dotsdiag", "′": "prime",
    # large operators
    "∑": "sum", "∏": "prod", "∐": "coprod", "∫": "int", "∮": "oint", "√": "sqrt",
    "⋃": "bigcup", "⋂": "bigcap",
}

#: Greek follows the palette convention: the name's case is the letter's case.
_GREEK = {
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "ε": "epsilon",
    "ϵ": "epsilon", "ζ": "zeta", "η": "eta", "θ": "theta", "ϑ": "vartheta",
    "ι": "iota", "κ": "kappa", "λ": "lambda", "μ": "mu", "ν": "nu", "ξ": "xi",
    "π": "pi", "ρ": "rho", "σ": "sigma", "τ": "tau", "υ": "upsilon", "φ": "phi",
    "ϕ": "varphi", "χ": "chi", "ψ": "psi", "ω": "omega",
    "Γ": "GAMMA", "Δ": "DELTA", "Θ": "THETA", "Λ": "LAMBDA", "Ξ": "XI", "Π": "PI",
    "Σ": "SIGMA", "Υ": "UPSILON", "Φ": "PHI", "Ψ": "PSI", "Ω": "OMEGA",
}
_TOKENS.update(_GREEK)

#: Accent character -> command.  Spacing and combining forms both appear, because which
#: one reaches us depends on the font.
_ACCENTS = {
    "^": "hat", "ˆ": "hat", "̂": "hat",
    "‾": "bar", "¯": "bar", "̄": "bar", "̅": "bar",
    "→": "vec", "⃗": "vec",
    "˙": "dot", "̇": "dot", "¨": "ddot", "̈": "ddot",
    "~": "tilde", "˜": "tilde", "̃": "tilde",
}

#: Fence character -> what follows ``left`` or ``right``.
_FENCES = {"(": "(", ")": ")", "[": "[", "]": "]", "|": "|", "‖": "dline",
           "{": "lbrace", "}": "rbrace", "⟨": "langle", "⟩": "rangle",
           "⌊": "lfloor", "⌋": "rfloor", "⌈": "lceil", "⌉": "rceil"}

#: Function names the editor sets upright without being told.
_FUNCTIONS = frozenset(
    "sin cos tan sec csc cot sinh cosh tanh log ln exp lim max min sup inf det "
    "gcd arg dim ker deg hom".split())


@dataclass
class WpEqResult:
    """Equation-language text, plus anything that could not be expressed in it."""

    wpeq: str
    unreproducible: list[str] = field(default_factory=list)
    unverified: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.unreproducible

    def __str__(self) -> str:
        return self.wpeq


class WpEqWriter:
    """Serialise a :class:`MathNode` to the WordPerfect 5.1 equation language."""

    def __init__(self) -> None:
        self.unreproducible: list[str] = []
        self.unverified: list[str] = []

    def to_string(self, node: MathNode) -> WpEqResult:
        self.unreproducible = []
        self.unverified = []
        text = " ".join(self._node(node).split())
        return WpEqResult(text, list(self.unreproducible),
                          sorted(set(self.unverified)))

    # -- helpers ---------------------------------------------------------------------
    def _cmd(self, name: str) -> str:
        if name in UNVERIFIED:
            self.unverified.append(name)
        return name

    def _group(self, node: MathNode) -> str:
        """Brace an operand.  WordPerfect's braces group without printing, so this is
        always safe and never changes what appears on the page."""
        inner = self._node(node)
        return inner if _is_single_token(inner) else "{" + inner + "}"

    def _always_group(self, node: MathNode) -> str:
        return "{" + self._node(node) + "}"

    # -- dispatch --------------------------------------------------------------------
    def _node(self, node: MathNode) -> str:
        r = getattr(self, "_r_" + type(node).__name__, None)
        return r(node) if r is not None else self._r_Row(node)

    def _join(self, node: MathNode) -> str:
        return " ".join(p for p in (self._node(c) for c in node.children) if p)

    # -- leaves ----------------------------------------------------------------------
    def _r_Identifier(self, n: Identifier) -> str:
        if n.text in _TOKENS:
            return _TOKENS[n.text]
        if len(n.text) > 1:
            # func keeps a multi-letter name upright; without it the editor italicises
            # every letter as a separate variable.
            return f"func {n.text}" if n.text not in _FUNCTIONS else n.text
        return n.text

    def _r_Number(self, n: Number) -> str:
        return n.text

    def _r_Operator(self, n: Operator) -> str:
        if n.text in _TOKENS:
            return _TOKENS[n.text]
        if n.text and not n.text.isascii():
            self.unreproducible.append(f"no equation-language name for {n.text!r}")
            return f'"{n.text}"'
        return n.text

    def _r_Text(self, n: Text) -> str:
        return f'"{n.text}"' if n.text else ""

    def _r_LargeOperator(self, n: LargeOperator) -> str:
        return _TOKENS.get(n.text, n.text)

    def _r_Unknown(self, n: Unknown) -> str:
        self.unreproducible.append(n.reason or "Unknown node")
        return f'"{n.text}"' if n.text else '"?"'

    def _r_Space(self, n: Space) -> str:
        # ~ is a full space, ` a thin one -- the editor's own two widths.
        return "~" if n.width_em >= 0.5 else "`"

    # -- containers ------------------------------------------------------------------
    def _r_Row(self, n: MathNode) -> str:
        return self._join(n)

    def _r_Fraction(self, n: Fraction) -> str:
        num, den = n.children[0], n.children[1]
        if n.line_thickness is not None and n.line_thickness <= 0:
            # No rule: a binomial is a stack, not a division.
            return f"stack {{{self._node(num)} # {self._node(den)}}}"
        return f"{self._always_group(num)} over {self._always_group(den)}"

    def _r_Superscript(self, n: Superscript) -> str:
        return f"{self._group(n.children[0])} sup {self._group(n.children[1])}"

    def _r_Subscript(self, n: Subscript) -> str:
        return f"{self._group(n.children[0])} sub {self._group(n.children[1])}"

    def _r_SubSup(self, n: SubSup) -> str:
        base, sub, sup = n.children
        return (f"{self._group(base)} sub {self._group(sub)} "
                f"sup {self._group(sup)}")

    def _r_UnderOver(self, n: UnderOver) -> str:
        base = n.children[0]
        rest = list(n.children[1:])
        under = rest.pop(0) if n.has_under else None
        over = rest.pop(0) if n.has_over else None
        out = self._node(base)
        # from/to is the editor's own spelling for limits under and over an operator.
        if under is not None:
            out += f" from {self._group(under)}"
        if over is not None:
            out += f" to {self._group(over)}"
        return out

    def _r_Radical(self, n: Radical) -> str:
        if n.has_index:
            return (f"nroot {self._always_group(n.children[1])} "
                    f"{self._always_group(n.children[0])}")
        return f"sqrt {self._always_group(n.children[0])}"

    def _r_Delimited(self, n: Delimited) -> str:
        """``left``/``right`` grow a fence to fit; a typed ``(`` does not.

        We know from the PDF which happened -- a ``\\left(`` produces an axis-centred
        cmex glyph and a typed one does not -- so the pair is only used where the page
        shows a fence that actually grew.
        """
        body = n.children[0] if n.children else None
        inner = self._node(body) if body is not None else ""
        if not n.stretchy and n.open in _FENCES and n.close in _FENCES:
            return f"{_FENCES[n.open]} {inner} {_FENCES[n.close]}"
        return f"left {self._fence(n.open)} {inner} right {self._fence(n.close)}"

    def _fence(self, ch: str) -> str:
        """left and right must always be paired, so an absent side becomes ``none``."""
        if not ch:
            return self._cmd("none")
        name = _FENCES.get(ch)
        if name is None:
            self.unreproducible.append(f"no equation-language fence for {ch!r}")
            return self._cmd("none")
        return self._cmd(name) if name in UNVERIFIED else name

    def _r_Accent(self, n: Accent) -> str:
        cmd = _ACCENTS.get(n.accent)
        if cmd is None:
            self.unreproducible.append(f"no equation-language accent for {n.accent!r}")
            return self._node(n.children[0])
        return f"{self._cmd(cmd)} {self._always_group(n.children[0])}"

    def _r_Overline(self, n: Overline) -> str:
        return f"{self._cmd('overline')} {self._always_group(n.children[0])}"

    def _r_Underline(self, n: Underline) -> str:
        return f"{self._cmd('underline')} {self._always_group(n.children[0])}"

    # -- tables ----------------------------------------------------------------------
    def _r_Matrix(self, n: Matrix) -> str:
        rows = " # ".join(self._row_cells(r) for r in n.children)
        return f"matrix {{{rows}}}"

    def _row_cells(self, row: MathNode) -> str:
        return " & ".join(self._node(c) for c in row.children)

    def _r_MatrixRow(self, n: MatrixRow) -> str:
        return self._row_cells(n)

    def _r_MatrixCell(self, n: MatrixCell) -> str:
        return self._join(n)

    def _r_Lines(self, n: Lines) -> str:
        # stackalign lines up the rows on a chosen column; plain stack centres them.
        return "stack {" + " # ".join(self._node(c) for c in n.children) + "}"


def _is_single_token(s: str) -> bool:
    """True when *s* needs no braces: one character, or one bare command word."""
    return len(s) == 1 or (s.isalnum() and s.isascii()) or s in _TOKENS.values()


def to_wpeq(node: MathNode) -> WpEqResult:
    """Convenience wrapper around :class:`WpEqWriter`."""
    return WpEqWriter().to_string(node)
