"""Export a reconstructed tree as an LgEval label graph (``.lg``).

LgEval is the evaluation library the CROHME competitions and the MathSeer pipeline use,
so writing this format is what makes a head-to-head comparison against QD-GGA (MathSeer's
formula structure recogniser) something a reader can actually run rather than something
we assert.  See docs/comparison.md for the protocol.

The object-based format is two record types::

    O, <object id>, <label>, <weight>, <primitive id>...
    R, <parent object>, <child object>, <relation>, <weight>

Primitives are the extracted glyphs, identified by the ids ``pdfmath dump`` reports, so a
label graph produced from our output and one produced from ground truth are comparable
primitive-by-primitive.

The relation vocabulary is CROHME's: ``Right``, ``Sup``, ``Sub``, ``Above``, ``Below``,
``Inside``, ``PreAbove``, ``PreBelow``.  Our tree carries strictly more than that -- it
distinguishes a fraction's numerator from an operator's upper limit, both of which are
``Above`` here -- so the conversion is deliberately lossy in the direction that makes the
two systems comparable.
"""

from __future__ import annotations

from typing import Any, Iterator, Optional

from ..tree.nodes import (Accent, Delimited, Fraction, Leaf, MathNode, Matrix,
                          MatrixCell, MatrixRow, Overline, Radical, Row, Space, SubSup,
                          Subscript, Superscript, UnderOver, Underline, Unknown)


class _Writer:
    def __init__(self) -> None:
        self.objects: list[tuple[str, str, float, list[int]]] = []
        self.relations: list[tuple[str, str, str, float]] = []
        self._n = 0

    def new_object(self, label: str, weight: float, primitives: list[int]) -> str:
        self._n += 1
        oid = f"o_{self._n}"
        self.objects.append((oid, label or "?", weight, sorted(set(primitives))))
        return oid

    def relate(self, parent: str, child: str, label: str, weight: float) -> None:
        if parent and child:
            self.relations.append((parent, child, label, weight))

    def render(self, comment: str = "") -> str:
        lines = []
        if comment:
            lines += [f"# {line}" for line in comment.splitlines()]
        for oid, label, w, prims in self.objects:
            prim = ", ".join(str(p) for p in prims)
            lines.append(f"O, {oid}, {label}, {w:.4f}"
                         + (f", {prim}" if prim else ""))
        for a, b, label, w in self.relations:
            lines.append(f"R, {a}, {b}, {label}, {w:.4f}")
        return "\n".join(lines) + "\n"


def _label(node: MathNode) -> str:
    if isinstance(node, Leaf):
        return node.text or (node.glyph or "?")
    return node.kind


def _emit(node: MathNode, w: _Writer) -> tuple[Optional[str], Optional[str]]:
    """Emit ``node``; return (leftmost object, rightmost object) for chaining."""
    conf = node.prov.confidence

    if isinstance(node, Space):
        return None, None

    if isinstance(node, Leaf):
        oid = w.new_object(_label(node), conf, node.prov.glyph_ids)
        return oid, oid

    if isinstance(node, Row):
        first = last = None
        for child in node.children:
            l, r = _emit(child, w)
            if l is None:
                continue
            if last is not None:
                w.relate(last, l, "Right", conf)
            first = first or l
            last = r
        return first, last

    if isinstance(node, (Superscript, Subscript, SubSup)):
        base_l, base_r = _emit(node.children[0], w)
        rels = (("Sub", 1), ("Sup", 2)) if isinstance(node, SubSup) else (
            (("Sup", 1),) if isinstance(node, Superscript) else (("Sub", 1),))
        for rel, idx in rels:
            l, _ = _emit(node.children[idx], w)
            w.relate(base_r or base_l, l, rel, conf)
        return base_l, base_r

    if isinstance(node, Fraction):
        bar = w.new_object("-", conf, node.prov.glyph_ids[:0])
        num, _ = _emit(node.children[0], w)
        den, _ = _emit(node.children[1], w)
        w.relate(bar, num, "Above", conf)
        w.relate(bar, den, "Below", conf)
        return bar, bar

    if isinstance(node, Radical):
        surd = w.new_object("\\sqrt", conf, [])
        body, _ = _emit(node.children[0], w)
        w.relate(surd, body, "Inside", conf)
        if len(node.children) > 1:
            idx, _ = _emit(node.children[1], w)
            w.relate(surd, idx, "PreAbove", conf)
        return surd, surd

    if isinstance(node, UnderOver):
        op_l, op_r = _emit(node.children[0], w)
        i = 1
        if node.has_under:
            l, _ = _emit(node.children[i], w)
            w.relate(op_r or op_l, l, "Below", conf)
            i += 1
        if node.has_over:
            l, _ = _emit(node.children[i], w)
            w.relate(op_r or op_l, l, "Above", conf)
        return op_l, op_r

    if isinstance(node, Delimited):
        opener = w.new_object(node.open or "(", conf, [])
        body_l, body_r = _emit(node.children[0], w) if node.children else (None, None)
        closer = w.new_object(node.close or ")", conf, [])
        if body_l:
            w.relate(opener, body_l, "Right", conf)
            w.relate(body_r or body_l, closer, "Right", conf)
        else:
            w.relate(opener, closer, "Right", conf)
        return opener, closer

    if isinstance(node, (Accent, Overline)):
        base_l, base_r = _emit(node.children[0], w)
        mark = w.new_object(getattr(node, "accent", "") or "\\overline", conf, [])
        w.relate(base_r or base_l, mark, "Above", conf)
        return base_l, base_r

    if isinstance(node, Underline):
        base_l, base_r = _emit(node.children[0], w)
        mark = w.new_object("\\underline", conf, [])
        w.relate(base_r or base_l, mark, "Below", conf)
        return base_l, base_r

    if isinstance(node, Matrix):
        first = prev_row = None
        for row in node.children:
            l, _ = _emit(row, w)
            if l is None:
                continue
            if prev_row is not None:
                w.relate(prev_row, l, "Below", conf)
            first = first or l
            prev_row = l
        return first, first

    if isinstance(node, (MatrixRow, MatrixCell)):
        first = last = None
        for child in node.children:
            l, r = _emit(child, w)
            if l is None:
                continue
            if last is not None:
                w.relate(last, l, "Right", conf)
            first = first or l
            last = r
        return first, last

    # Anything else: emit the children in a Right chain rather than lose them.
    return _emit(Row(children=list(node.children)), w)


def to_label_graph(node: MathNode, comment: str = "") -> str:
    """Serialise a tree as an LgEval object-relationship label graph."""
    w = _Writer()
    _emit(node, w)
    return w.render(comment)
