"""TeX's atom-class reclassification, run forwards so that spacing can be inverted.

The class printed on a glyph is not the class TeX used.  ``mlist_to_hlist`` rewrites the
list before it inserts any glue (tex.web 727-728):

* a **Bin** atom becomes **Ord** when it is the first atom of the list, or when the atom
  before it is Bin, Op, Rel, Open or Punct.  This is why the minus in ``-x`` is set tight
  against the ``x`` while the one in ``a-b`` is not, using the same glyph.
* a **Rel**, **Close** or **Punct** atom turns the *previous* atom into **Ord** if that
  was a Bin.  This is why ``a+=b`` -- were anyone to write it -- spaces the ``+`` as an
  ordinary symbol.

Reproducing both rules is what makes the inter-atom spacing table predictive rather than
approximate.  Without them, every unary minus in a document produces a gap the table
cannot explain, and the parser reports an author-inserted space that is not there.

Running the rewrite forwards and comparing the result with the measured gaps is also the
experiment the project set out to run: if the reclassified classes predict every gap, the
classes are recoverable from the page, because the prediction and the measurement agree.
"""

from __future__ import annotations

from typing import Sequence

from ..fonts.symbols import AtomClass

#: Classes that make a following Bin behave as an Ord (tex.web 727).
_DEMOTES_NEXT_BIN = (AtomClass.BIN, AtomClass.OP, AtomClass.REL,
                     AtomClass.OPEN, AtomClass.PUNCT)

#: Classes that make a preceding Bin behave as an Ord (tex.web 728).
_DEMOTES_PREVIOUS_BIN = (AtomClass.REL, AtomClass.CLOSE, AtomClass.PUNCT)


def reclassify(classes: Sequence[AtomClass]) -> list[AtomClass]:
    """Apply TeX's Bin-to-Ord rewriting to a horizontal list of atom classes."""
    out = list(classes)
    for i, cls in enumerate(out):
        if cls is not AtomClass.BIN:
            continue
        if i == 0 or out[i - 1] in _DEMOTES_NEXT_BIN:
            out[i] = AtomClass.ORD
    for i, cls in enumerate(out):
        if cls in _DEMOTES_PREVIOUS_BIN and i > 0 and out[i - 1] is AtomClass.BIN:
            out[i - 1] = AtomClass.ORD
    return out


def infer_middle_class(left_mu: float, right_mu: float,
                       left: AtomClass, right: AtomClass,
                       script_style: bool = False,
                       tol: float = 0.25) -> set[AtomClass]:
    """Which atom class explains the glue on both sides of an atom?

    This is the inverse problem the project set out to test.  ``a\\mathbin{b}c`` prints
    ``b`` as an ordinary cmmi letter, so the glyph says nothing about its class -- but
    TeX put a medium space on each side of it, and the only class that produces medium
    against Ord in both directions is Bin.  The answer is a *set*, because the map is not
    always injective: nothing distinguishes Open from Ord when both neighbours are Ord.
    """
    from .spacing import expected_mu

    out = set()
    for middle in AtomClass:
        lhs = expected_mu(left, middle, script_style)
        rhs = expected_mu(middle, right, script_style)
        if lhs is None or rhs is None:
            continue
        if abs(lhs - left_mu) <= tol and abs(rhs - right_mu) <= tol:
            out.add(middle)
    return out


def describe(before: Sequence[AtomClass], after: Sequence[AtomClass]) -> list[str]:
    """Human-readable notes on what the rewrite changed, for ``pdfmath explain``."""
    notes = []
    for i, (b, a) in enumerate(zip(before, after)):
        if b is not a:
            notes.append(f"atom {i}: {b.short} -> {a.short} "
                         f"({'first in the list' if i == 0 else 'after ' + after[i - 1].short})")
    return notes
