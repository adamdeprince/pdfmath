"""TeX glyph-name knowledge: Unicode, math atom class, structural role.

Why glyph *names* and not character codes: the names in the Computer Modern, Latin
Modern and AMS Type 1 fonts are stable across families and sizes, whereas the codes are
only meaningful together with an encoding.  ``radicalBigg`` means the same thing in
cmex10 and in lmex10, and its name says both what it is (a radical) and how big it is,
which no Unicode code point records.

This is the layer that lets us prefer TeX evidence over ToUnicode.  A malformed or absent
ToUnicode map costs us nothing as long as we recognise the font.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional

from .data.extra_symbols import EXTRA_SYMBOLS


class AtomClass(IntEnum):
    """TeX's math atom classes (*The TeXbook*, ch. 17)."""

    ORD = 0
    OP = 1
    BIN = 2
    REL = 3
    OPEN = 4
    CLOSE = 5
    PUNCT = 6
    INNER = 7

    @property
    def short(self) -> str:
        return ("Ord", "Op", "Bin", "Rel", "Open", "Close", "Punct", "Inner")[int(self)]


class Role(IntEnum):
    """What a glyph does structurally, beyond its atom class."""

    SYMBOL = 0          # an ordinary printed symbol
    DELIM_OPEN = 1      # (  [  {  <  |  ceil/floor left
    DELIM_CLOSE = 2     # )  ]  }  >  |  ceil/floor right
    DELIM_PIECE = 3     # top / middle / bottom / extension piece of a built-up delimiter
    RADICAL = 4         # a surd, at any size, or one of its pieces
    LARGE_OP = 5        # sum / prod / int / ... in text or display size
    ACCENT = 6          # hat / tilde / bar / vec / dot, including the wide cmex forms
    SPACER = 7          # a glyph that prints nothing


#: The 26 x 2 Latin letters and 10 digits are handled programmatically, not listed.
_GREEK_LOWER = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ",
    "epsilon1": "ϵ", "epsilon": "ε", "zeta": "ζ", "eta": "η",
    "theta": "θ", "theta1": "ϑ", "iota": "ι", "kappa": "κ",
    "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ",
    "pi": "π", "pi1": "ϖ", "rho": "ρ", "rho1": "ϱ",
    "sigma": "σ", "sigma1": "ς", "tau": "τ", "upsilon": "υ",
    "phi": "ϕ", "phi1": "φ", "chi": "χ", "psi": "ψ",
    "omega": "ω",
}
_GREEK_UPPER = {
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ",
    "Xi": "Ξ", "Pi": "Π", "Sigma": "Σ", "Upsilon": "Υ",
    "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
}

#: name -> (unicode, atom class).  Structural roles are derived separately, below.
_TABLE: dict[str, tuple[str, AtomClass]] = {}


def _put(names: str, uni: str, cls: AtomClass) -> None:
    for n in names.split():
        _TABLE[n] = (uni, cls)


# --- ordinary letters, digits, punctuation -------------------------------------------
for _n, _u in {**_GREEK_LOWER, **_GREEK_UPPER}.items():
    _TABLE[_n] = (_u, AtomClass.ORD)
for _c in "0123456789":
    _TABLE[{"0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
            "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine"}[_c]] = (
        _c, AtomClass.ORD)
    _TABLE[{"0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
            "5": "five", "6": "six", "7": "seven", "8": "eight",
            "9": "nine"}[_c] + "oldstyle"] = (_c, AtomClass.ORD)
for _c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz":
    _TABLE[_c] = (_c, AtomClass.ORD)

_put("period", ".", AtomClass.ORD)
_put("comma", ",", AtomClass.PUNCT)
_put("semicolon", ";", AtomClass.PUNCT)
_put("colon", ":", AtomClass.REL)          # \colon is Punct, ':' is Rel in plain TeX
_put("exclam", "!", AtomClass.CLOSE)
_put("question", "?", AtomClass.CLOSE)
_put("slash", "/", AtomClass.ORD)
_put("backslash", "∖", AtomClass.ORD)
_put("bar", "|", AtomClass.ORD)
_put("bardbl", "‖", AtomClass.ORD)
_put("dotlessi", "ı", AtomClass.ORD)
_put("dotlessj", "ȷ", AtomClass.ORD)
_put("space", " ", AtomClass.ORD)
_put("quoteright", "’", AtomClass.ORD)
_put("quoteleft", "‘", AtomClass.ORD)
_put("hyphen", "-", AtomClass.ORD)
_put("endash", "–", AtomClass.ORD)
_put("emdash", "—", AtomClass.ORD)
_put("percent", "%", AtomClass.ORD)
_put("ampersand", "&", AtomClass.ORD)
_put("numbersign", "#", AtomClass.ORD)
_put("dollar", "$", AtomClass.ORD)
_put("at", "@", AtomClass.ORD)
_put("fi fl ff ffi ffl", "", AtomClass.ORD)          # ligatures; fixed up below
_TABLE["ff"] = ("ff", AtomClass.ORD)
_TABLE["fi"] = ("fi", AtomClass.ORD)
_TABLE["fl"] = ("fl", AtomClass.ORD)
_TABLE["ffi"] = ("ffi", AtomClass.ORD)
_TABLE["ffl"] = ("ffl", AtomClass.ORD)

# --- binary operators -----------------------------------------------------------------
_put("plus", "+", AtomClass.BIN)
_put("minus", "−", AtomClass.BIN)
_put("periodcentered", "⋅", AtomClass.BIN)
_put("multiply", "×", AtomClass.BIN)
_put("asteriskmath", "∗", AtomClass.BIN)
_put("divide", "÷", AtomClass.BIN)
_put("diamondmath", "⋄", AtomClass.BIN)
_put("plusminus", "±", AtomClass.BIN)
_put("minusplus", "∓", AtomClass.BIN)
_put("circleplus", "⊕", AtomClass.BIN)
_put("circleminus", "⊖", AtomClass.BIN)
_put("circlemultiply", "⊗", AtomClass.BIN)
_put("circledivide", "⊘", AtomClass.BIN)
_put("circledot", "⊙", AtomClass.BIN)
_put("circlecopyrt", "©", AtomClass.ORD)
_put("openbullet", "◦", AtomClass.BIN)
_put("bullet", "∙", AtomClass.BIN)
_put("union", "∪", AtomClass.BIN)
_put("intersection", "∩", AtomClass.BIN)
_put("unionmulti", "⊎", AtomClass.BIN)
_put("logicaland", "∧", AtomClass.BIN)
_put("logicalor", "∨", AtomClass.BIN)
_put("unionsq", "⊔", AtomClass.BIN)
_put("intersectionsq", "⊓", AtomClass.BIN)
_put("wreathproduct", "≀", AtomClass.BIN)
_put("dagger", "†", AtomClass.BIN)
_put("daggerdbl", "‡", AtomClass.BIN)
_put("triangle", "△", AtomClass.ORD)
_put("triangleinv", "▽", AtomClass.ORD)
_put("triangleleft", "◁", AtomClass.BIN)
_put("triangleright", "▷", AtomClass.BIN)
_put("star", "⋆", AtomClass.BIN)

# --- relations ------------------------------------------------------------------------
_put("equal", "=", AtomClass.REL)
_put("less", "<", AtomClass.REL)
_put("greater", ">", AtomClass.REL)
_put("equivasymptotic", "≍", AtomClass.REL)
_put("equivalence", "≡", AtomClass.REL)
_put("reflexsubset", "⊆", AtomClass.REL)
_put("reflexsuperset", "⊇", AtomClass.REL)
_put("lessequal", "≤", AtomClass.REL)
_put("greaterequal", "≥", AtomClass.REL)
_put("precedesequal", "⪯", AtomClass.REL)
_put("followsequal", "⪰", AtomClass.REL)
_put("similar", "∼", AtomClass.REL)
_put("approxequal", "≈", AtomClass.REL)
_put("propersubset", "⊂", AtomClass.REL)
_put("propersuperset", "⊃", AtomClass.REL)
_put("lessmuch", "≪", AtomClass.REL)
_put("greatermuch", "≫", AtomClass.REL)
_put("precedes", "≺", AtomClass.REL)
_put("follows", "≻", AtomClass.REL)
_put("similarequal", "≃", AtomClass.REL)
_put("proportional", "∝", AtomClass.REL)
_put("element", "∈", AtomClass.REL)
_put("owner", "∋", AtomClass.REL)
_put("negationslash", "̸", AtomClass.ORD)
_put("mapsto", "↦", AtomClass.REL)
_put("turnstileleft", "⊢", AtomClass.REL)
_put("turnstileright", "⊣", AtomClass.REL)
_put("subsetsqequal", "⊑", AtomClass.REL)
_put("supersetsqequal", "⊒", AtomClass.REL)
_put("perpendicular", "⊥", AtomClass.ORD)
_put("latticetop", "⊤", AtomClass.ORD)
_put("arrowleft", "←", AtomClass.REL)
_put("arrowright", "→", AtomClass.REL)
_put("arrowup", "↑", AtomClass.REL)
_put("arrowdown", "↓", AtomClass.REL)
_put("arrowboth", "↔", AtomClass.REL)
_put("arrowbothv", "↕", AtomClass.ORD)
_put("arrownortheast", "↗", AtomClass.REL)
_put("arrowsoutheast", "↘", AtomClass.REL)
_put("arrownorthwest", "↖", AtomClass.REL)
_put("arrowsouthwest", "↙", AtomClass.REL)
_put("arrowdblleft", "⇐", AtomClass.REL)
_put("arrowdblright", "⇒", AtomClass.REL)
_put("arrowdblup", "⇑", AtomClass.REL)
_put("arrowdbldown", "⇓", AtomClass.REL)
_put("arrowdblboth", "⇔", AtomClass.REL)
_put("arrowdblbothv", "⇕", AtomClass.ORD)
_put("arrowhookleft", "↩", AtomClass.REL)
_put("arrowhookright", "↪", AtomClass.REL)
_put("arrowlefttophalf", "↼", AtomClass.REL)
_put("arrowleftbothalf", "↽", AtomClass.REL)
_put("arrowrighttophalf", "⇀", AtomClass.REL)
_put("arrowrightbothalf", "⇁", AtomClass.REL)

# --- ordinary math symbols ------------------------------------------------------------
_put("infinity", "∞", AtomClass.ORD)
_put("prime", "′", AtomClass.ORD)
_put("partialdiff", "∂", AtomClass.ORD)
_put("nabla", "∇", AtomClass.ORD)
_put("universal", "∀", AtomClass.ORD)
_put("existential", "∃", AtomClass.ORD)
_put("logicalnot", "¬", AtomClass.ORD)
_put("emptyset", "∅", AtomClass.ORD)
_put("aleph", "ℵ", AtomClass.ORD)
_put("Rfractur", "ℜ", AtomClass.ORD)
_put("Ifractur", "ℑ", AtomClass.ORD)
_put("weierstrass", "℘", AtomClass.ORD)
_put("lscript", "ℓ", AtomClass.ORD)
_put("flat", "♭", AtomClass.ORD)
_put("natural", "♮", AtomClass.ORD)
_put("sharp", "♯", AtomClass.ORD)
_put("club", "♣", AtomClass.ORD)
_put("diamond", "♢", AtomClass.ORD)
_put("heart", "♡", AtomClass.ORD)
_put("spade", "♠", AtomClass.ORD)
_put("section", "§", AtomClass.ORD)
_put("paragraph", "¶", AtomClass.ORD)
_put("ellipsis", "…", AtomClass.ORD)

# --- accents --------------------------------------------------------------------------
_ACCENTS = {
    "circumflex": "̂", "tilde": "̃", "macron": "̄", "breve": "̆",
    "dotaccent": "̇", "dieresis": "̈", "ring": "̊", "acute": "́",
    "grave": "̀", "hungarumlaut": "̋", "caron": "̌", "cedilla": "̧",
    "vector": "⃗", "tie": "͡", "bar": "̄",
}
for _n, _u in _ACCENTS.items():
    _TABLE.setdefault(_n, (_u, AtomClass.ORD))

# --- delimiters -----------------------------------------------------------------------
#: base delimiter name -> (opening unicode, closing unicode)
_DELIM_PAIRS = {
    "paren": ("(", ")"),
    "bracket": ("[", "]"),
    "brace": ("{", "}"),
    "angbracket": ("⟨", "⟩"),
    "floor": ("⌊", "⌋"),
    "ceiling": ("⌈", "⌉"),
}
#: size suffixes used by cmex, in increasing order.  "" is the text-size cmr/cmsy form.
_DELIM_SIZES = ["", "big", "Big", "bigg", "Bigg"]

_put("parenleft", "(", AtomClass.OPEN)
_put("parenright", ")", AtomClass.CLOSE)
_put("bracketleft", "[", AtomClass.OPEN)
_put("bracketright", "]", AtomClass.CLOSE)
_put("braceleft", "{", AtomClass.OPEN)
_put("braceright", "}", AtomClass.CLOSE)
_put("angbracketleft", "⟨", AtomClass.OPEN)
_put("angbracketright", "⟩", AtomClass.CLOSE)
_put("floorleft", "⌊", AtomClass.OPEN)
_put("floorright", "⌋", AtomClass.CLOSE)
_put("ceilingleft", "⌈", AtomClass.OPEN)
_put("ceilingright", "⌉", AtomClass.CLOSE)
_put("vextendsingle", "|", AtomClass.ORD)
_put("vextenddouble", "‖", AtomClass.ORD)
_put("radical", "√", AtomClass.ORD)
_put("coproduct", "∐", AtomClass.OP)
_put("integral", "∫", AtomClass.OP)
_put("summation", "∑", AtomClass.OP)
_put("product", "∏", AtomClass.OP)
_put("contintegral", "∮", AtomClass.OP)

#: base name of a large operator -> unicode
_LARGE_OP_BASE = {
    "summation": "∑", "product": "∏", "coproduct": "∐",
    "integral": "∫", "contintegral": "∮", "union": "⋃",
    "intersection": "⋂", "unionmulti": "⨄", "unionsq": "⨆",
    "logicaland": "⋀", "logicalor": "⋁", "circledot": "⨀",
    "circleplus": "⨁", "circlemultiply": "⨂",
}

_WIDE_ACCENT_BASE = {"hat": "̂", "tilde": "̃"}


@dataclass(frozen=True)
class SymbolInfo:
    """What we know about one glyph."""

    glyph: str                       # the font's own glyph name, e.g. "summationdisplay"
    unicode: str                     # best-effort Unicode, "" if genuinely unknown
    atom: AtomClass
    role: Role = Role.SYMBOL
    base: Optional[str] = None       # size-independent identity, e.g. "summation"
    size_rank: int = 0               # 0 = text size; higher = larger cmex variant
    side: Optional[str] = None       # "left" / "right" for delimiters
    piece: Optional[str] = None      # "tp" / "mid" / "bt" / "ex" for built-up pieces

    @property
    def is_delimiter(self) -> bool:
        return self.role in (Role.DELIM_OPEN, Role.DELIM_CLOSE, Role.DELIM_PIECE)


_PIECE_RE = re.compile(
    r"^(?P<base>paren|bracket|brace|angbracket|floor|ceiling)"
    r"(?P<side>left|right)"
    r"(?P<suffix>tp|mid|bt|ex|big|Big|bigg|Bigg)?$"
)
_LARGEOP_RE = re.compile(
    r"^(?P<base>" + "|".join(sorted(_LARGE_OP_BASE, key=len, reverse=True)) + r")"
    r"(?P<size>text|display)$"
)
_RADICAL_RE = re.compile(r"^radical(?P<suffix>big|Big|bigg|Bigg|tp|vertex|bt)?$")
_WIDE_ACC_RE = re.compile(r"^(?P<base>hat|tilde)(?P<size>wide|wider|widest)$")


def lookup(glyph: str, encoding: Optional[str] = None) -> SymbolInfo:
    """Everything we know about a glyph name.

    Never raises: an unknown name comes back with an empty ``unicode`` and
    ``AtomClass.ORD`` so that nothing is silently dropped.  ``encoding``, when given,
    unlocks the generated AMS table -- the hand-written tables here cover Computer
    Modern, and msam/msbm are filled in from LaTeXML's own declarations.
    """
    g = glyph

    m = _RADICAL_RE.match(g)
    if m:
        sfx = m.group("suffix")
        rank = {None: 0, "big": 1, "Big": 2, "bigg": 3, "Bigg": 4}.get(sfx)
        if rank is None:                      # tp / vertex / bt: pieces of a tall surd
            return SymbolInfo(g, "√", AtomClass.ORD, Role.RADICAL, "radical",
                              5, piece={"tp": "tp", "vertex": "ex", "bt": "bt"}[sfx])
        return SymbolInfo(g, "√", AtomClass.ORD, Role.RADICAL, "radical", rank)

    m = _LARGEOP_RE.match(g)
    if m:
        base = m.group("base")
        return SymbolInfo(g, _LARGE_OP_BASE[base], AtomClass.OP, Role.LARGE_OP, base,
                          1 if m.group("size") == "display" else 0)

    m = _WIDE_ACC_RE.match(g)
    if m:
        base = m.group("base")
        rank = {"wide": 1, "wider": 2, "widest": 3}[m.group("size")]
        return SymbolInfo(g, _WIDE_ACCENT_BASE[base], AtomClass.ORD, Role.ACCENT,
                          base, rank)

    m = _PIECE_RE.match(g)
    if m:
        base, side, sfx = m.group("base"), m.group("side"), m.group("suffix")
        uni = _DELIM_PAIRS[base][0 if side == "left" else 1]
        if sfx in ("tp", "mid", "bt", "ex"):
            # A piece keeps the atom class of the delimiter it builds: an assembled
            # \left\{ has to pair with its \right\} like any other fence.
            atom = AtomClass.OPEN if side == "left" else AtomClass.CLOSE
            return SymbolInfo(g, uni, atom, Role.DELIM_PIECE, base,
                              5, side=side, piece=sfx)
        rank = _DELIM_SIZES.index(sfx) if sfx else 0
        role = Role.DELIM_OPEN if side == "left" else Role.DELIM_CLOSE
        atom = AtomClass.OPEN if side == "left" else AtomClass.CLOSE
        return SymbolInfo(g, uni, atom, role, base, rank, side=side)

    if g in ("braceex", "bracehtipdownleft", "bracehtipdownright",
             "bracehtipupleft", "bracehtipupright"):
        return SymbolInfo(g, "", AtomClass.ORD, Role.DELIM_PIECE, "brace", 5, piece="ex")
    if g in ("arrowvertex", "arrowvertexdbl", "arrowtp", "arrowbt",
             "arrowdbltp", "arrowdblbt"):
        return SymbolInfo(g, "", AtomClass.ORD, Role.DELIM_PIECE, "arrow", 5, piece="ex")
    if g in ("slashbig", "slashBig", "slashbigg", "slashBigg"):
        return SymbolInfo(g, "/", AtomClass.ORD, Role.SYMBOL, "slash",
                          _DELIM_SIZES.index(g[5:]))
    if g in ("backslashbig", "backslashBig", "backslashbigg", "backslashBigg"):
        return SymbolInfo(g, "∖", AtomClass.ORD, Role.SYMBOL, "backslash",
                          _DELIM_SIZES.index(g[9:]))

    if g in _TABLE:
        uni, atom = _TABLE[g]
        role = Role.SYMBOL
        if atom is AtomClass.OPEN:
            role = Role.DELIM_OPEN
        elif atom is AtomClass.CLOSE:
            role = Role.DELIM_CLOSE
        elif g == "radical":
            role = Role.RADICAL
        base = g
        if g in ("bar", "vextendsingle"):
            base = "bar"
        return SymbolInfo(g, uni, atom, role, base)

    if encoding is not None:
        entry = EXTRA_SYMBOLS.get((encoding, g))
        if entry is not None:
            uni, atom_name = entry
            atom = getattr(AtomClass, atom_name, AtomClass.ORD)
            role = (Role.DELIM_OPEN if atom is AtomClass.OPEN else
                    Role.DELIM_CLOSE if atom is AtomClass.CLOSE else Role.SYMBOL)
            return SymbolInfo(g, uni, atom, role, g)
    return SymbolInfo(g, "", AtomClass.ORD, Role.SYMBOL, g)


#: Names of the ``\left``/``\right``-style neutral delimiters, which are their own mirror.
NEUTRAL_DELIMITERS = {"bar", "bardbl", "vextendsingle", "vextenddouble",
                      "arrowbothv", "arrowdblbothv", "backslash", "slash"}
