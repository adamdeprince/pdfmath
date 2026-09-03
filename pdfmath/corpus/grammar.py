"""A generative grammar for mathematical expressions.

The point of this module is that a single object produces *both* the LaTeX source and the
expected tree.  Ground truth is therefore never derived from the PDF, and a bug in the
decompiler can never quietly become part of its own test oracle.

    Fraction(Sup(Ident("x"), Num("2")), Sqrt(Ident("y")))
        .to_tex()        ->  \\frac{x^{2}}{\\sqrt{y}}
        .to_signature()  ->  ('Fraction', (('Superscript', ...), ('Radical', ...)))

The signatures are exactly what :meth:`pdfmath.tree.nodes.MathNode.signature` produces, so
comparison is a plain equality test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

Sig = Any


#: Expression kinds that must be braced when they appear as the base of a script.
#: Two reasons: ``x^2_i`` is one atom carrying two scripts while ``{x^2}_i`` is a script
#: on a box, and ``\\sum_a^b^2`` is not even legal TeX.  Atoms are deliberately *not*
#: braced -- ``{f}^2`` differs from ``f^2``, because a box nucleus contributes no italic
#: correction to the superscript's position.
_NEEDS_BRACES = ("Sup", "Sub", "SubSup", "Seq", "BigOp")


def _base_tex(e: "Expr") -> str:
    t = e.to_tex()
    return "{" + t + "}" if type(e).__name__ in _NEEDS_BRACES else t


def _row_sig(parts: Sequence[Sig]) -> Sig:
    parts = [p for p in parts if p is not None]
    if len(parts) == 1:
        return parts[0]
    return ("Row", tuple(parts))


@dataclass(frozen=True)
class Expr:
    """Base class for generated expressions."""

    def to_tex(self) -> str:                    # pragma: no cover - abstract
        raise NotImplementedError

    def to_signature(self, display: bool = True) -> Sig:   # pragma: no cover
        """The tree this expression describes.

        ``display`` is TeX's ``cur_style < text_style`` -- true at the top level of a
        displayed equation, and false inside a fraction, a script, a matrix cell or an
        operator's limits.  It has to be threaded through because it changes what the
        *rendered page* looks like: ``\\sum_i`` sets its limit under the operator in
        display style and beside it everywhere else, so the expected tree is a different
        shape in the two cases.
        """
        raise NotImplementedError

    def children(self) -> Sequence["Expr"]:
        return ()

    def replace_children(self, kids: Sequence["Expr"]) -> "Expr":
        return self

    @property
    def name(self) -> str:
        return type(self).__name__

    def size(self) -> int:
        return 1 + sum(c.size() for c in self.children())

    def constructs(self) -> set[str]:
        out = {self.construct}
        for c in self.children():
            out |= c.constructs()
        return out

    @property
    def construct(self) -> str:
        return type(self).__name__.lower()


# ------------------------------------------------------------------------- atoms

@dataclass(frozen=True)
class Ident(Expr):
    """A variable.  ``tex`` differs from ``text`` for Greek letters."""

    text: str
    tex: Optional[str] = None

    def to_tex(self) -> str:
        return self.tex if self.tex is not None else self.text

    def to_signature(self, display: bool = True) -> Sig:
        return ("Identifier", self.text)

    @property
    def construct(self) -> str:
        return "identifier"


@dataclass(frozen=True)
class Num(Expr):
    text: str

    def to_tex(self) -> str:
        return self.text

    def to_signature(self, display: bool = True) -> Sig:
        return ("Number", self.text)

    @property
    def construct(self) -> str:
        return "number"


@dataclass(frozen=True)
class Op(Expr):
    """An infix operator or relation."""

    text: str
    tex: str

    def to_tex(self) -> str:
        return self.tex

    def to_signature(self, display: bool = True) -> Sig:
        return ("Operator", self.text)

    @property
    def construct(self) -> str:
        return "operator"


# ---------------------------------------------------------------------- structures

@dataclass(frozen=True)
class Seq(Expr):
    """A horizontal sequence -> ``Row``."""

    parts: tuple[Expr, ...]

    def to_tex(self) -> str:
        # Space-separated: TeX ignores spaces in maths mode, but without them a control
        # word runs into whatever follows it ("x\\le y" would become "x\\ley").
        return " ".join(p.to_tex() for p in self.parts)

    def to_signature(self, display: bool = True) -> Sig:
        return _row_sig([p.to_signature(display) for p in self.parts])

    def children(self) -> Sequence[Expr]:
        return self.parts

    def replace_children(self, kids):
        return Seq(tuple(kids))

    @property
    def construct(self) -> str:
        return "row"


@dataclass(frozen=True)
class Frac(Expr):
    num: Expr
    den: Expr

    def to_tex(self) -> str:
        return f"\\frac{{{self.num.to_tex()}}}{{{self.den.to_tex()}}}"

    def to_signature(self, display: bool = True) -> Sig:
        # A fraction sets both parts one style down, so nothing inside is display style.
        return ("Fraction", (self.num.to_signature(False), self.den.to_signature(False)))

    def children(self): return (self.num, self.den)
    def replace_children(self, kids): return Frac(kids[0], kids[1])

    @property
    def construct(self) -> str: return "fraction"


@dataclass(frozen=True)
class Sup(Expr):
    base: Expr
    script: Expr

    def to_tex(self) -> str:
        return f"{_base_tex(self.base)}^{{{self.script.to_tex()}}}"

    def to_signature(self, display: bool = True) -> Sig:
        return ("Superscript", (self.base.to_signature(display),
                                self.script.to_signature(False)))

    def children(self): return (self.base, self.script)
    def replace_children(self, kids): return Sup(kids[0], kids[1])

    @property
    def construct(self) -> str: return "script"


@dataclass(frozen=True)
class Sub(Expr):
    base: Expr
    script: Expr

    def to_tex(self) -> str:
        return f"{_base_tex(self.base)}_{{{self.script.to_tex()}}}"

    def to_signature(self, display: bool = True) -> Sig:
        return ("Subscript", (self.base.to_signature(display),
                              self.script.to_signature(False)))

    def children(self): return (self.base, self.script)
    def replace_children(self, kids): return Sub(kids[0], kids[1])

    @property
    def construct(self) -> str: return "script"


@dataclass(frozen=True)
class SubSup(Expr):
    base: Expr
    sub: Expr
    sup: Expr

    def to_tex(self) -> str:
        return (f"{_base_tex(self.base)}_{{{self.sub.to_tex()}}}"
                f"^{{{self.sup.to_tex()}}}")

    def to_signature(self, display: bool = True) -> Sig:
        return ("SubSup", (self.base.to_signature(display),
                           self.sub.to_signature(False), self.sup.to_signature(False)))

    def children(self): return (self.base, self.sub, self.sup)
    def replace_children(self, kids): return SubSup(kids[0], kids[1], kids[2])

    @property
    def construct(self) -> str: return "script"


@dataclass(frozen=True)
class Sqrt(Expr):
    radicand: Expr
    index: Optional[Expr] = None

    def to_tex(self) -> str:
        if self.index is None:
            return f"\\sqrt{{{self.radicand.to_tex()}}}"
        return f"\\sqrt[{self.index.to_tex()}]{{{self.radicand.to_tex()}}}"

    def to_signature(self, display: bool = True) -> Sig:
        # The radicand is set in the *cramped* current style, which is still display
        # style as far as the limits rule is concerned.
        kids = [self.radicand.to_signature(display)]
        if self.index is not None:
            kids.append(self.index.to_signature(False))
        return ("Radical", tuple(kids))

    def children(self):
        return (self.radicand,) if self.index is None else (self.radicand, self.index)

    def replace_children(self, kids):
        return Sqrt(kids[0], kids[1] if len(kids) > 1 else None)

    @property
    def construct(self) -> str: return "radical"


#: TeX name -> (opening character, closing character)
DELIMS = {
    "paren": ("(", ")"), "bracket": ("[", "]"), "brace": ("\\{", "\\}"),
    "angle": ("\\langle", "\\rangle"), "vert": ("|", "|"),
    "floor": ("\\lfloor", "\\rfloor"), "ceil": ("\\lceil", "\\rceil"),
}
DELIM_TEXT = {
    "paren": ("(", ")"), "bracket": ("[", "]"), "brace": ("{", "}"),
    "angle": ("⟨", "⟩"), "vert": ("|", "|"),
    "floor": ("⌊", "⌋"), "ceil": ("⌈", "⌉"),
}


@dataclass(frozen=True)
class Delim(Expr):
    body: Expr
    kind: str = "paren"
    big: bool = True                # \left ... \right rather than bare characters

    def to_tex(self) -> str:
        o, c = DELIMS[self.kind]
        if self.big:
            return f"\\left{o} {self.body.to_tex()} \\right{c}"
        return f"{o} {self.body.to_tex()} {c}"

    def to_signature(self, display: bool = True) -> Sig:
        o, c = DELIM_TEXT[self.kind]
        return ("Delimited", o, c, (self.body.to_signature(display),))

    def children(self): return (self.body,)
    def replace_children(self, kids): return Delim(kids[0], self.kind, self.big)

    @property
    def construct(self) -> str: return "delimiter"


#: TeX command -> the Unicode character the operator is drawn with
BIG_OPS = {
    "\\sum": "∑", "\\prod": "∏", "\\int": "∫", "\\coprod": "∐",
    "\\bigcup": "⋃", "\\bigcap": "⋂", "\\oint": "∮",
}
#: Operators whose limits go above and below in display style (\int does not).
LIMIT_OPS = {"\\sum", "\\prod", "\\coprod", "\\bigcup", "\\bigcap"}


@dataclass(frozen=True)
class BigOp(Expr):
    op: str
    lower: Optional[Expr] = None
    upper: Optional[Expr] = None
    body: Optional[Expr] = None

    def to_tex(self) -> str:
        s = self.op
        if self.lower is not None:
            s += f"_{{{self.lower.to_tex()}}}"
        if self.upper is not None:
            s += f"^{{{self.upper.to_tex()}}}"
        if self.body is not None:
            s += " " + self.body.to_tex()
        return s

    def to_signature(self, display: bool = True) -> Sig:
        opsig = ("LargeOperator", BIG_OPS[self.op])
        # "if (subtype(q)=normal) and (cur_style<text_style) then subtype(q):=limits"
        # -- an operator takes limits above and below only in display style.
        limits = display and self.op in LIMIT_OPS
        if self.lower is None and self.upper is None:
            core: Sig = opsig
        elif limits:
            kids = [opsig]
            if self.lower is not None:
                kids.append(self.lower.to_signature(False))
            if self.upper is not None:
                kids.append(self.upper.to_signature(False))
            core = ("UnderOver", self.lower is not None, self.upper is not None,
                    tuple(kids))
        elif self.lower is not None and self.upper is not None:
            core = ("SubSup", (opsig, self.lower.to_signature(False),
                               self.upper.to_signature(False)))
        elif self.lower is not None:
            core = ("Subscript", (opsig, self.lower.to_signature(False)))
        else:
            core = ("Superscript", (opsig, self.upper.to_signature(False)))
        if self.body is None:
            return core
        return _row_sig([core, self.body.to_signature(display)])

    def children(self):
        return tuple(c for c in (self.lower, self.upper, self.body) if c is not None)

    def replace_children(self, kids):
        it = iter(kids)
        lower = next(it) if self.lower is not None else None
        upper = next(it) if self.upper is not None else None
        body = next(it) if self.body is not None else None
        return BigOp(self.op, lower, upper, body)

    @property
    def construct(self) -> str: return "largeop"


#: TeX accent command -> the character MathML uses for it
ACCENTS = {
    "\\hat": "^", "\\bar": "¯", "\\vec": "⃗", "\\dot": "˙",
    "\\ddot": "¨", "\\tilde": "~", "\\check": "ˇ", "\\breve": "˘",
    "\\acute": "´", "\\grave": "`",
}


@dataclass(frozen=True)
class Acc(Expr):
    cmd: str
    base: Expr

    def to_tex(self) -> str:
        return f"{self.cmd}{{{self.base.to_tex()}}}"

    def to_signature(self, display: bool = True) -> Sig:
        return ("Accent", ACCENTS[self.cmd], (self.base.to_signature(display),))

    def children(self): return (self.base,)
    def replace_children(self, kids): return Acc(self.cmd, kids[0])

    @property
    def construct(self) -> str: return "accent"


@dataclass(frozen=True)
class OverLine(Expr):
    base: Expr

    def to_tex(self) -> str:
        return f"\\overline{{{self.base.to_tex()}}}"

    def to_signature(self, display: bool = True) -> Sig:
        return ("Overline", (self.base.to_signature(display),))

    def children(self): return (self.base,)
    def replace_children(self, kids): return OverLine(kids[0])

    @property
    def construct(self) -> str: return "accent"


#: environment -> (opening character, closing character) or None for a bare matrix
MATRIX_ENVS = {
    "pmatrix": ("(", ")"), "bmatrix": ("[", "]"), "Bmatrix": ("{", "}"),
    "vmatrix": ("|", "|"), "matrix": None,
}


@dataclass(frozen=True)
class Mat(Expr):
    rows: tuple[tuple[Expr, ...], ...]
    env: str = "pmatrix"

    def to_tex(self) -> str:
        body = " \\\\ ".join(" & ".join(c.to_tex() for c in row) for row in self.rows)
        return f"\\begin{{{self.env}}} {body} \\end{{{self.env}}}"

    def to_signature(self, display: bool = True) -> Sig:
        # Matrix cells are set in text style, never display.
        table = ("Matrix", tuple(
            ("MatrixRow", tuple(("MatrixCell", (c.to_signature(False),)) for c in row))
            for row in self.rows))
        fences = MATRIX_ENVS[self.env]
        if fences is None:
            return table
        return ("Delimited", fences[0], fences[1], (table,))

    def children(self):
        return tuple(c for row in self.rows for c in row)

    def replace_children(self, kids):
        it = iter(kids)
        rows = tuple(tuple(next(it) for _ in row) for row in self.rows)
        return Mat(rows, self.env)

    @property
    def construct(self) -> str: return "matrix"


@dataclass(frozen=True)
class ThinSpace(Expr):
    """``\\,`` -- glue TeX would not have inserted, so the parser should notice it."""

    def to_tex(self) -> str:
        return "\\,"

    def to_signature(self, display: bool = True) -> Sig:
        return None                 # filtered out of Row signatures

    @property
    def construct(self) -> str: return "space"
