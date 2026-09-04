"""Read Presentation MathML back into a comparison signature.

Written so that an *independent* converter can be used as an oracle.  LaTeXML turns LaTeX
into MathML and is the reference implementation for that direction; if we can read its
output into the same signature form our own tree produces, then any LaTeX source with a
matching PDF becomes a labelled example -- which is what makes the arXiv corpus usable.

Normalisation is where the care goes.  Two converters that agree about the mathematics
still disagree about markup, and the differences are systematic rather than interesting:

* nested ``mrow`` grouping, which no renderer distinguishes;
* invisible operators (U+2061..U+2064) that LaTeXML inserts to mark function application
  and implied multiplication, and that a decompiler cannot see because they are not on
  the page;
* ``mstyle`` / ``mpadded`` / ``semantics`` wrappers that carry no structure;
* whether a symbol is tagged ``mi`` or ``mo``, which is a judgement about its role, not
  about what was printed.

Everything those hide is genuinely invisible in a PDF, so folding them is not conceding a
point -- it is declining to be scored on something the medium does not record.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional
from xml.etree import ElementTree

MATHML_NS = "{http://www.w3.org/1998/Math/MathML}"

#: Elements that carry no structure of their own.
_TRANSPARENT = {"mstyle", "mpadded", "mphantom", "menclose", "semantics", "math",
                "annotation-xml", "mrow"}
_IGNORED = {"annotation", "mspace", "maligngroup", "malignmark", "none"}

#: Invisible operators a converter inserts and a page cannot show.
_INVISIBLE = re.compile(r"[⁡-⁤​⁠]")

#: Accent marks come in spacing and combining forms, and converters differ over which to
#: use: LaTeXML writes U+0304 COMBINING MACRON where we write U+00AF MACRON, and U+2192
#: RIGHTWARDS ARROW for a vector where we write U+20D7.  Same mark on the page.
ACCENT_CANON = {
    "^": "hat", "\u0302": "hat", "\u02c6": "hat",
    "\u00af": "bar", "\u0304": "bar", "\u203e": "bar", "\u0305": "bar",
    "\u02d9": "dot", "\u0307": "dot",
    "\u00a8": "ddot", "\u0308": "ddot",
    "~": "tilde", "\u0303": "tilde", "\u02dc": "tilde", "\u223c": "tilde",
    "\u20d7": "vec", "\u2192": "vec", "\u2b0d": "vec",
    "\u02c7": "check", "\u030c": "check",
    "\u02d8": "breve", "\u0306": "breve",
    "\u00b4": "acute", "\u0301": "acute",
    "`": "grave", "\u0300": "grave",
    "\u02da": "ring", "\u030a": "ring",
}

#: Fence characters, for recognising a delimited group inside an mrow.
_OPEN = set("([{⟨⌊⌈|‖")
_CLOSE = set(")]}⟩⌋⌉|‖")


def _tag(el) -> str:
    return el.tag.replace(MATHML_NS, "").split("}")[-1]


def normalise_text(text: str) -> str:
    """Fold the ways two converters can spell the same printed character.

    LaTeXML writes a differential as U+1D451 MATHEMATICAL ITALIC SMALL D, having decided
    it is an operator; we write ``d``, having seen a cmmi glyph.  Both are the same ink.
    NFKC maps the Mathematical Alphanumeric Symbols block onto its base letters, which is
    exactly that distinction and no other.
    """
    return unicodedata.normalize("NFKC", _INVISIBLE.sub("", text)).strip()


def _text(el) -> str:
    return normalise_text("".join(el.itertext()))


def _row(parts: list[Any]) -> Any:
    parts = [p for p in parts if p is not None]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return ("Row", tuple(parts))


def _leaf(kind: str, text: str) -> Optional[Any]:
    return (kind, text) if text else None


def _children(el, flatten: bool = False) -> list[Any]:
    """The element's children as signatures.

    ``flatten`` only for containers whose children are a *sequence* -- an mrow, the math
    root.  Flattening inside an mfrac or an msubsup would dissolve the very boundary the
    element exists to draw, turning a numerator of three atoms into three arguments.
    """
    out: list[Any] = []
    for child in el:
        sig = _convert(child)
        if sig is None:
            continue
        if flatten and isinstance(sig, tuple) and sig and sig[0] == "Row":
            out.extend(sig[1])
        else:
            out.append(sig)
    return out


def _fenced(parts: list[Any]) -> Optional[Any]:
    """Turn ``mo(fence) ... mo(fence)`` into a Delimited, as our tree records it."""
    if len(parts) < 2:
        return None
    first, last = parts[0], parts[-1]
    if not (isinstance(first, tuple) and first[0] == "Operator"
            and isinstance(last, tuple) and last[0] == "Operator"):
        return None
    if first[1] not in _OPEN or last[1] not in _CLOSE:
        return None
    body = _row(parts[1:-1])
    return ("Delimited", first[1], last[1], (body,) if body is not None else ((),))


def _convert(el) -> Optional[Any]:
    tag = _tag(el)
    if tag in _IGNORED:
        return None
    if tag == "mi":
        return _leaf("Identifier", _text(el))
    if tag == "mn":
        return _leaf("Number", _text(el))
    if tag in ("mo", "ms"):
        return _leaf("Operator", _text(el))
    if tag == "mtext":
        return _leaf("Text", _text(el))
    if tag == "mfrac":
        kids = _children(el)
        return ("Fraction", tuple(kids[:2])) if len(kids) >= 2 else _row(kids)
    if tag == "msqrt":
        return ("Radical", (_row(_children(el, flatten=True)),))
    if tag == "mroot":
        kids = _children(el)
        return ("Radical", tuple(kids[:2])) if len(kids) >= 2 else _row(kids)
    if tag in ("msup", "msub", "msubsup"):
        kids = _children(el)
        name = {"msup": "Superscript", "msub": "Subscript", "msubsup": "SubSup"}[tag]
        return (name, tuple(kids))
    if tag in ("munder", "mover", "munderover"):
        kids = _children(el)
        if tag == "mover" and el.get("accent") == "true" and len(kids) == 2:
            mark = kids[1][1] if isinstance(kids[1], tuple) and len(kids[1]) > 1 else ""
            return ("Accent", mark, (kids[0],))
        has_under = tag in ("munder", "munderover")
        has_over = tag in ("mover", "munderover")
        return ("UnderOver", has_under, has_over, tuple(kids))
    if tag == "mtable":
        return ("Matrix", tuple(k for k in _children(el)))
    if tag == "mtr" or tag == "mlabeledtr":
        return ("MatrixRow", tuple(_children(el)))
    if tag == "mtd":
        return ("MatrixCell", (_row(_children(el, flatten=True)),))
    if tag in _TRANSPARENT:
        parts = _children(el, flatten=True)
        fence = _fenced(parts)
        return fence if fence is not None else _row(parts)
    return _row(_children(el, flatten=True))


def mathml_signature(xml: str) -> Optional[Any]:
    """Parse Presentation MathML into the signature form used for comparison."""
    xml = xml.strip()
    if not xml:
        return None
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return None
    return _convert(root)


def relax(sig: Any) -> Any:
    """Fold distinctions two converters may make differently but a page does not.

    ``mi`` against ``mo`` is a claim about a symbol's role and ``LargeOperator`` against
    ``Operator`` a claim about its size class.  Neither changes what was printed, so a
    decompiler that reported one where a converter reported the other has not made a
    mistake about the document.
    """
    if sig is None or not isinstance(sig, tuple) or not sig:
        return sig
    head = sig[0]
    if head in ("Identifier", "Operator", "LargeOperator", "Text"):
        text = normalise_text(sig[1]) if len(sig) > 1 else ""
        if len(text) > 1:
            # Whether "Ric" is one token or three, and whether a double prime is one
            # character or two, is a convention of the converter rather than a fact
            # about the page.  Both sides are split so neither is scored on it.
            return ("Row", tuple(("Token", c) for c in text))
        return ("Token", text)
    if head == "Number":
        return ("Number", normalise_text(sig[1]) if len(sig) > 1 else "")
    if head in ("Overline", "Underline") and len(sig) == 2:
        # LaTeXML calls an \overline an accent with a bar; we keep it as its own node
        # because it is not one.  Both are an mover over the same rule.
        mark = "bar" if head == "Overline" else "underbar"
        return ("Accent", mark, tuple(relax(k) for k in sig[1]))
    if head == "Accent" and len(sig) == 3:
        mark = normalise_text(sig[1])
        return ("Accent", ACCENT_CANON.get(mark, mark),
                tuple(relax(k) for k in sig[2]))
    return tuple(
        tuple(relax(k) for k in part) if isinstance(part, tuple) else part
        for part in sig)
