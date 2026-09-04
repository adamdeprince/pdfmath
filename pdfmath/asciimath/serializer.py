"""AsciiMath serialisation.

AsciiMath is a linear syntax that stays readable as plain text, which makes it the useful
output when the reader magnifies rather than listens: ``(x+1)/(y+1)`` survives a 400%
zoom and a reflow where a two-dimensional layout does not.

The one thing that needs real care is **bracket consumption**.  In AsciiMath a bracket is
printed unless an enclosing construct eats it: ``(x+y)/2`` is a fraction whose numerator
is ``x+y`` with no parentheses drawn, while a bare ``(x+y)`` prints them.  The operators
that eat a following bracket are ``/``, ``^``, ``_`` and the named functions (``sqrt``,
``root``, ``hat`` ...).  Two consequences drive the code below:

* Every operand of ``/`` and every function argument is *always* bracketed, even when it
  is a single token.  Anything else risks ``a/b c`` regrouping on the reader.
* Brackets that were really on the page arrive as a :class:`Delimited` node and print
  their own pair.  Because the rule composes, a parenthesised numerator comes out as
  ``((x))/(y)`` -- the outer pair is eaten by ``/``, the inner pair is drawn, which is
  exactly what the PDF showed.

Superscripts and subscripts take the readable liberty: a single-token script is left
unbracketed (``x^2``, ``x_i``) because no regrouping is possible, and bracketed otherwise.

A glyph with no AsciiMath spelling is written as ``text(...)`` holding the character and
recorded in :attr:`AsciiMathResult.unreproducible`, never dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..tree.nodes import (Accent, Delimited, Fraction, Identifier, LargeOperator, Leaf,
                          Lines, MathNode, Matrix, MatrixCell, MatrixRow, Number,
                          Operator, Overline, Radical, Row, Space, SubSup, Subscript,
                          Superscript, Text, UnderOver, Underline, Unknown)

#: Unicode -> AsciiMath token.  Only entries whose AsciiMath spelling differs from the
#: character itself need to be here; ``+``, ``=``, digits and Latin letters pass through.
_TOKENS = {
    # characters whose ASCII spelling AsciiMath expects
    "−": "-", "∼": "~", "·": "*", "≃": "~=", "∣": "|",
    # relations
    "≤": "<=", "≥": ">=", "≠": "!=", "≈": "~~", "≡": "-=", "≅": "~=", "∝": "prop",
    "≺": "-<", "≻": ">-", "⊑": "sqsube", "⊒": "sqsupe", "≪": "<<", "≫": ">>",
    # binary operators
    "×": "xx", "÷": "-:", "±": "+-", "∓": "-+", "⋅": "*", "∘": "@", "⊗": "ox",
    "⊕": "o+", "⊙": "o.", "∗": "**", "⋆": "star", "∪": "uu", "∩": "nn",
    "⋀": "bigwedge", "⋁": "bigvee", "⋃": "uuu", "⋂": "nnn", "∧": "^^", "∨": "vv",
    # set theory and logic
    "∈": "in", "∉": "!in", "⊂": "sub", "⊆": "sube", "⊃": "sup", "⊇": "supe",
    "∅": "O/", "∀": "AA", "∃": "EE", "¬": "not", "∴": ":.", "∵": ":'",
    "⊢": "|--", "⊨": "|==",
    # arrows
    "→": "->", "←": "larr", "↔": "harr", "⇒": "=>", "⇐": "impliedby", "⇔": "<=>",
    "↦": "|->", "⟶": "->", "↑": "uarr", "↓": "darr",
    # miscellaneous symbols
    "∞": "oo", "∂": "del", "∇": "grad", "ℵ": "aleph", "∠": "angle", "△": "triangle",
    "…": "ldots", "⋯": "cdots", "⋮": "vdots", "⋱": "ddots", "′": "prime",
    "ℝ": "RR", "ℕ": "NN", "ℤ": "ZZ", "ℚ": "QQ", "ℂ": "CC",
    # large operators
    "∑": "sum", "∏": "prod", "∐": "coprod", "∫": "int", "∮": "oint", "√": "sqrt",
}

#: Greek letters spell themselves, so they are generated rather than listed.
_GREEK = {
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "ε": "epsilon",
    "ϵ": "epsilon", "ζ": "zeta", "η": "eta", "θ": "theta", "ϑ": "theta",
    "ι": "iota", "κ": "kappa", "λ": "lambda", "μ": "mu", "ν": "nu", "ξ": "xi",
    "π": "pi", "ρ": "rho", "σ": "sigma", "τ": "tau", "υ": "upsilon", "φ": "phi",
    "ϕ": "varphi", "χ": "chi", "ψ": "psi", "ω": "omega",
    "Γ": "Gamma", "Δ": "Delta", "Θ": "Theta", "Λ": "Lambda", "Ξ": "Xi", "Π": "Pi",
    "Σ": "Sigma", "Υ": "Upsilon", "Φ": "Phi", "Ψ": "Psi", "Ω": "Omega",
}
_TOKENS.update(_GREEK)

#: Accent character -> the AsciiMath function that draws it.  Both the spacing and the
#: combining form of each mark appear, because which one reaches us depends on the font.
_ACCENTS = {
    "^": "hat", "ˆ": "hat", "̂": "hat",
    "‾": "bar", "¯": "bar", "̄": "bar", "¯": "bar",
    "→": "vec", "⃗": "vec", "⃗": "vec",
    "˙": "dot", "̇": "dot", "¨": "ddot", "̈": "ddot",
    "~": "tilde", "˜": "tilde", "̃": "tilde",
}

#: AsciiMath's own function keywords: emitting one of these bare is correct.
_FUNCTIONS = frozenset(
    "sin cos tan sec csc cot sinh cosh tanh sech csch coth arcsin arccos arctan "
    "exp log ln det dim mod gcd lcm lub glb min max f g".split())

#: Bracket pairs AsciiMath understands directly.
_FENCES = {"(": "(", ")": ")", "[": "[", "]": "]", "{": "{", "}": "}",
           "⟨": "(:", "⟩": ":)", "|": "|", "‖": "||", "⌊": "|__", "⌋": "__|",
           "⌈": "|~", "⌉": "~|"}


@dataclass
class AsciiMathResult:
    """AsciiMath text, plus anything that could not be spelled in it."""

    asciimath: str
    unreproducible: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.unreproducible

    def __str__(self) -> str:
        return self.asciimath


class AsciiMathWriter:
    """Serialise a :class:`MathNode` to AsciiMath."""

    def __init__(self) -> None:
        self.unreproducible: list[str] = []

    def to_string(self, node: MathNode) -> AsciiMathResult:
        self.unreproducible = []
        text = _squeeze(self._node(node))
        return AsciiMathResult(text, list(self.unreproducible))

    # -- bracketing ------------------------------------------------------------------
    def _group(self, node: MathNode) -> str:
        """Bracket unconditionally: for operands whose grouping must not be guessable."""
        return f"({self._node(node)})"

    def _script(self, node: MathNode) -> str:
        """Bracket only when the script is more than one token."""
        s = self._node(node)
        return s if _is_single_token(s) else f"({s})"

    # -- dispatch --------------------------------------------------------------------
    def _node(self, node: MathNode) -> str:
        r = getattr(self, "_r_" + type(node).__name__, None)
        if r is None:
            return self._r_Row(node)
        return r(node)

    def _join(self, node: MathNode) -> str:
        return " ".join(p for p in (self._node(c) for c in node.children) if p)

    # -- leaves ----------------------------------------------------------------------
    def _r_Identifier(self, n: Identifier) -> str:
        if n.text in _TOKENS:
            return _TOKENS[n.text]
        if len(n.text) > 1 and n.text not in _FUNCTIONS:
            return f'text({n.text})'
        return n.text

    def _r_Number(self, n: Number) -> str:
        return n.text

    def _r_Operator(self, n: Operator) -> str:
        if n.text in _TOKENS:
            return _TOKENS[n.text]
        if n.text in _FENCES:
            return _FENCES[n.text]
        if n.text and not n.text.isascii():
            self.unreproducible.append(f"no AsciiMath token for {n.text!r}")
            return f'text({n.text})'
        return n.text

    def _r_Text(self, n: Text) -> str:
        return f'text({n.text})' if n.text else ""

    def _r_LargeOperator(self, n: LargeOperator) -> str:
        return _TOKENS.get(n.text, n.text)

    def _r_Unknown(self, n: Unknown) -> str:
        self.unreproducible.append(n.reason or "Unknown node")
        return f'text({n.text})' if n.text else 'text(?)'

    def _r_Space(self, n: Space) -> str:
        # AsciiMath collapses whitespace, so a measured gap can only be rendered as a
        # quad.  Anything narrower is spacing TeX inserted for looks, not for meaning.
        return "quad" if n.width_em >= 0.5 else ""

    # -- containers ------------------------------------------------------------------
    def _r_Row(self, n: MathNode) -> str:
        return self._join(n)

    def _r_Fraction(self, n: Fraction) -> str:
        num, den = n.children[0], n.children[1]
        if n.line_thickness is not None and n.line_thickness <= 0:
            # \binom and friends: a bar-less fraction is a stacked pair, which AsciiMath
            # spells as a one-column matrix rather than a division.
            return f"(({self._node(num)}),({self._node(den)}))"
        return f"{self._group(num)}/{self._group(den)}"

    def _r_Superscript(self, n: Superscript) -> str:
        return f"{self._base(n.children[0])}^{self._script(n.children[1])}"

    def _r_Subscript(self, n: Subscript) -> str:
        return f"{self._base(n.children[0])}_{self._script(n.children[1])}"

    def _r_SubSup(self, n: SubSup) -> str:
        base, sub, sup = n.children
        return (f"{self._base(base)}_{self._script(sub)}"
                f"^{self._script(sup)}")

    def _base(self, node: MathNode) -> str:
        """Group a compound base so the script binds to all of it.

        ``^`` and ``_`` take the *preceding* token, and a bracket before them is printed
        rather than eaten -- ``(x^2)_i`` would claim parentheses the page never showed.
        AsciiMath's invisible brackets ``{: :}`` group without drawing anything, which is
        what a TeX group did here.
        """
        s = self._node(node)
        if _is_single_token(s) or _is_bracketed(s):
            return s
        return f"{{:{s}:}}"

    def _r_UnderOver(self, n: UnderOver) -> str:
        base = n.children[0]
        rest = list(n.children[1:])
        under = rest.pop(0) if n.has_under else None
        over = rest.pop(0) if n.has_over else None
        out = self._base(base)
        # AsciiMath puts limits above and below automatically for sum-like operators and
        # uses the same _ ^ syntax, so no special form is needed.
        if under is not None:
            out += f"_{self._script(under)}"
        if over is not None:
            out += f"^{self._script(over)}"
        return out

    def _r_Radical(self, n: Radical) -> str:
        if n.has_index:
            return f"root{self._group(n.children[1])}{self._group(n.children[0])}"
        return f"sqrt{self._group(n.children[0])}"

    def _r_Delimited(self, n: Delimited) -> str:
        body = n.children[0] if n.children else None
        if body is not None and isinstance(_unwrap(body), Matrix):
            return self._matrix(_unwrap(body), n.open, n.close)
        inner = self._node(body) if body is not None else ""
        open_, close = _FENCES.get(n.open), _FENCES.get(n.close)
        if open_ is None or close is None:
            # An unmatched or exotic fence: keep the characters as text so the reader
            # still learns what was printed.
            if n.open and open_ is None:
                self.unreproducible.append(f"no AsciiMath fence for {n.open!r}")
            if n.close and close is None:
                self.unreproducible.append(f"no AsciiMath fence for {n.close!r}")
            open_ = open_ or (f'text({n.open})' if n.open else "{:")
            close = close or (f'text({n.close})' if n.close else ":}")
        if not n.open:
            open_ = "{:"
        if not n.close:
            close = ":}"
        return f"{open_}{inner}{close}"

    def _r_Accent(self, n: Accent) -> str:
        fn = _ACCENTS.get(n.accent)
        if fn is None:
            self.unreproducible.append(f"no AsciiMath accent for {n.accent!r}")
            return self._node(n.children[0])
        return f"{fn}{self._group(n.children[0])}"

    def _r_Overline(self, n: Overline) -> str:
        return f"bar{self._group(n.children[0])}"

    def _r_Underline(self, n: Underline) -> str:
        return f"ul{self._group(n.children[0])}"

    def _r_Matrix(self, n: Matrix) -> str:
        return self._matrix(n, "(", ")")

    def _matrix(self, n: Matrix, open_: str, close: str) -> str:
        o, c = _FENCES.get(open_, "("), _FENCES.get(close, ")")
        rows = ",".join(f"({self._row_cells(r)})" for r in n.children)
        return f"{o}{rows}{c}"

    def _row_cells(self, row: MathNode) -> str:
        return ",".join(self._node(cell) for cell in row.children)

    def _r_MatrixRow(self, n: MatrixRow) -> str:
        return f"({self._row_cells(n)})"

    def _r_MatrixCell(self, n: MatrixCell) -> str:
        return self._join(n)

    def _r_Lines(self, n: Lines) -> str:
        # Several display lines are separate expressions; AsciiMath has no vertical
        # stack outside a matrix, so they are joined by a newline for the reader.
        return "\n".join(self._node(c) for c in n.children)


def _unwrap(node: MathNode) -> MathNode:
    """See through a Row that exists only to hold one child."""
    while isinstance(node, Row) and len(node.children) == 1:
        node = node.children[0]
    return node


def _is_single_token(s: str) -> bool:
    """True when *s* cannot regroup if left unbracketed after ``^`` or ``_``."""
    return len(s) == 1 or (s.isalnum() and s.isascii()) or s in _TOKENS.values()


def _is_bracketed(s: str) -> bool:
    """True when *s* is already one balanced bracketed group."""
    pairs = {"(": ")", "[": "]", "{": "}"}
    if not s or s[0] not in pairs:
        return False
    depth = 0
    for i, ch in enumerate(s):
        if ch in pairs:
            depth += 1
        elif ch in pairs.values():
            depth -= 1
            if depth == 0:
                return i == len(s) - 1
    return False


def _squeeze(s: str) -> str:
    """Normalise whitespace.  AsciiMath ignores it, but a human reading the linear text
    does not, and ``x , y`` reads worse than ``x, y`` at high magnification."""
    out = " ".join(s.split())
    for mark in (",", ";", ".", "!"):
        out = out.replace(f" {mark}", mark)
    return out


def to_asciimath(node: MathNode) -> AsciiMathResult:
    """Convenience wrapper around :class:`AsciiMathWriter`."""
    return AsciiMathWriter().to_string(node)
