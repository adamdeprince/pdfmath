"""An independent check on the AsciiMath writer.

The AsciiMath we emit is only worth trusting if something that is not our code reads it
back the way we meant it.  ``py-asciimath`` parses AsciiMath to MathML with no knowledge
of this project, so ``tree -> AsciiMath -> MathML`` compared against ``tree -> MathML``
closes the same hole LaTeXML closes for the ground truth.

Two families of difference are folded, both because AsciiMath cannot express the
distinction rather than because either side is wrong:

* **Limit position.**  ``sum_(i=0)^n`` is the only spelling AsciiMath has; whether a
  renderer sets the limits above and below or to the right is its own decision, and the
  PDF's answer (which we keep) simply cannot survive the round trip.
* **Accent codepoint.**  An overbar is U+0305, U+00AF or U+203E depending on who is
  writing, and ``py-asciimath`` reaches for a *low* line for ``bar``.  Both sides place
  the same mark over the same base, so the marks are canonicalised before comparison.

Everything else -- nesting, tokens, fences, fractions, radicals, scripts, matrices -- is
compared strictly.
"""

from __future__ import annotations

import contextlib
import html.entities
import io
import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

from ..asciimath.serializer import to_asciimath
from ..mathml.serializer import to_mathml
from ..tree.nodes import MathNode
from .mathml_compare import mathml_signature, relax

#: XML's own five entities must survive; everything else py-asciimath emits by name.
_XML_ENTITIES = frozenset({"lt", "gt", "amp", "quot", "apos"})

#: Marks that mean the same accent whichever codepoint is used to write them.
_ACCENT_CANON = {
    "^": "hat", "ˆ": "hat", "̂": "hat",
    "‾": "bar", "¯": "bar", "̄": "bar", "̅": "bar", "_": "bar", "̲": "bar",
    "→": "vec", "⃗": "vec",
    "˙": "dot", "̇": "dot", ".": "dot",
    "¨": "ddot", "̈": "ddot",
    "~": "tilde", "˜": "tilde", "̃": "tilde",
}

#: Operators TeX sets with limits above and below in display style.
_LARGE = set("∑∏∐∫∮⋃⋂⋀⋁")


def available() -> bool:
    try:
        import py_asciimath.translator.translator  # noqa: F401
    except Exception:
        return False
    return True


def resolve_entities(xml: str) -> str:
    """Turn ``&alpha;`` into the character, leaving XML's own five entities alone."""
    start = xml.find("<math")
    if start > 0:
        xml = xml[start:]                    # drop py-asciimath's DOCTYPE
    return re.sub(
        r"&([A-Za-z][A-Za-z0-9]*);",
        lambda m: (m.group(0) if m.group(1) in _XML_ENTITIES
                   else html.entities.html5.get(m.group(1) + ";", m.group(0))),
        xml)


def to_mathml_via_asciimath(text: str) -> Optional[str]:
    """Parse AsciiMath with py-asciimath, silencing its very chatty logger."""
    from py_asciimath.translator.translator import ASCIIMath2MathML

    level = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            out = ASCIIMath2MathML(log=False, inplace=True).translate(
                text, dtd_validation=False, xml_declaration=False)
    except Exception:
        return None
    finally:
        logging.disable(level)
    return resolve_entities(out)


def fold(sig: Any) -> Any:
    """Fold the distinctions AsciiMath has no syntax for.  See the module docstring."""
    if not isinstance(sig, tuple) or not sig:
        return sig
    head = sig[0]
    if head == "Token" and len(sig) > 1:
        # U+2212 MINUS SIGN and the ASCII hyphen are the same operator.
        return ("Token", sig[1].replace("−", "-"))
    if head in ("UnderOver", "SubSup", "Subscript", "Superscript"):
        base, scripts = _limits(sig)
        if base is not None and base[0] == "Token" and base[1] in _LARGE:
            return ("Limits", base, tuple(fold(s) for s in scripts))
    if head == "UnderOver" and len(sig) == 4 and sig[1] is False and sig[2] is True:
        kids = sig[3]
        if len(kids) == 2:
            mark = _canon_mark(kids[1])
            if mark:
                return ("Accent", mark, (fold(kids[0]),))
    if head == "Accent" and len(sig) == 3:
        return ("Accent", _ACCENT_CANON.get(sig[1], sig[1]),
                tuple(fold(k) for k in sig[2]))
    return tuple(tuple(fold(k) for k in p) if isinstance(p, tuple) else p for p in sig)


def _canon_mark(node: Any) -> Optional[str]:
    """The accent mark, whether written as one token or (for ``ddot``) two."""
    if node[0] == "Token" and len(node) > 1:
        return _ACCENT_CANON.get(node[1])
    if node[0] == "Row" and len(node) > 1:
        marks = {_canon_mark(k) for k in node[1]}
        if marks == {"dot"} and len(node[1]) == 2:
            return "ddot"
    return None


def _limits(sig: Any) -> tuple[Optional[Any], tuple]:
    """Split a scripted node into its base and its scripts, whatever the node kind."""
    if sig[0] == "UnderOver" and len(sig) == 4:
        kids = sig[3]
        return (kids[0], tuple(kids[1:])) if kids else (None, ())
    if len(sig) == 2 and isinstance(sig[1], tuple) and sig[1]:
        return sig[1][0], tuple(sig[1][1:])
    return None, ()


@dataclass
class Verdict:
    """The outcome of one round trip."""

    asciimath: str
    ours: Any = None
    theirs: Any = None
    error: str = ""

    @property
    def agrees(self) -> bool:
        return not self.error and self.ours == self.theirs


def check(tree: MathNode) -> Verdict:
    """Write *tree* as AsciiMath, read it back independently, compare."""
    text = to_asciimath(tree).asciimath
    back = to_mathml_via_asciimath(text)
    if back is None:
        return Verdict(text, error="py-asciimath could not parse the output")
    theirs = mathml_signature(back)
    if theirs is None:
        return Verdict(text, error="py-asciimath produced unparseable MathML")
    return Verdict(text, fold(relax(mathml_signature(to_mathml(tree)))),
                   fold(relax(theirs)))
