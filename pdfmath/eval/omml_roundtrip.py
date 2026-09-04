"""An independent check on the OMML writer.

Nothing else in the suite reads the OMML we emit, so a wrong slot or a swapped numerator
would pass every other test.  Pandoc's ``docx`` reader parses OMML with no knowledge of
this project, so wrapping our markup in a minimal Word package and converting it back to
MathML compares two independent readings of the same tree.

The package written here is the smallest one pandoc will open: a content-type map, a
single relationship, and a ``document.xml`` holding one paragraph per equation.  All the
equations go into *one* document, because a pandoc process per expression dominates the
run time of the whole test suite.

Four differences are folded.  Each is a place where pandoc's MathML has no way to carry
something OMML stated, so neither side is wrong:

* **Limit position.**  ``m:limLoc`` says whether an n-ary's limits sit above and below or
  to the right; pandoc emits ``msubsup`` either way.
* **Empty operand.**  An n-ary's deliberately empty ``m:e`` is dropped rather than kept
  as an empty row, leaving a scripted node with only its operator.
* **Accents.**  ``m:acc`` comes back as a plain ``mover`` with no ``accent`` attribute,
  and the mark's codepoint is pandoc's choice -- U+0304 where we wrote U+0305, an arrow
  where we wrote a combining arrow.  Both are canonicalised.
* **Fences.**  ``m:d`` comes back as three loose tokens rather than a fenced row, so both
  sides are flattened to fence, body, fence.

What is still compared strictly: every token and its order, fraction numerator against
denominator, radical index against radicand, script base against sub against sup, the
n-ary's operator character, and the shape of every matrix.
"""

from __future__ import annotations

import os
import tempfile
import zipfile
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from ..omml.serializer import to_omml
from ..mathml.serializer import to_mathml
from ..tree.nodes import MathNode
from .mathml_compare import ACCENT_CANON, mathml_signature, relax

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType=\
"application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType=\
"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type=\
"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" \
Target="word/document.xml"/>
</Relationships>"""

_DOCUMENT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document \
xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" \
xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">\
<w:body>%s</w:body></w:document>"""

#: Marks the paragraph boundaries in pandoc's HTML so equations can be split apart.
_SPLIT = "<p>"


def available() -> bool:
    try:
        import pypandoc
        pypandoc.get_pandoc_version()
    except Exception:
        return False
    return True


def write_docx(omml: Sequence[str], path: str) -> str:
    """Write the smallest Word package holding *omml*, one equation per paragraph."""
    body = "".join(f"<w:p>{o}</w:p>" for o in omml)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("word/document.xml", _DOCUMENT % body)
    return path


def mathml_from_omml(omml: Sequence[str]) -> list[Optional[str]]:
    """Round-trip a batch through pandoc, returning one MathML string per input."""
    import pypandoc

    with tempfile.TemporaryDirectory() as tmp:
        path = write_docx(omml, os.path.join(tmp, "probe.docx"))
        html = pypandoc.convert_file(path, "html", format="docx",
                                     extra_args=["--mathml"])
    out: list[Optional[str]] = []
    for chunk in html.split(_SPLIT)[1:]:
        start = chunk.find("<math")
        end = chunk.find("</math>")
        out.append(chunk[start:end + len("</math>")] if start >= 0 and end > 0 else None)
    while len(out) < len(omml):
        out.append(None)
    return out


def fold(sig: Any) -> Any:
    """Fold the conventions pandoc's MathML cannot carry.  See the module docstring."""
    if not isinstance(sig, tuple) or not sig:
        return sig
    head = sig[0]
    if head == "Accent" and len(sig) == 3:
        return ("Accent", ACCENT_CANON.get(sig[1], sig[1]),
                tuple(fold(k) for k in sig[2]))
    if head == "UnderOver" and len(sig) == 4:
        kids = sig[3]
        # An mover carrying a known accent mark is an accent, whether or not the
        # producer said so.
        if len(kids) == 2 and sig[1] is False and sig[2] is True:
            mark = _mark(kids[1])
            if mark:
                return ("Accent", mark, (fold(kids[0]),))
        return ("Scripted", tuple(fold(k) for k in kids))
    if head in ("SubSup", "Subscript", "Superscript") and len(sig) == 2:
        kids = tuple(fold(k) for k in sig[1])
        # A lone operator is what is left of an n-ary whose operand slot was empty.
        return kids[0] if len(kids) == 1 else ("Scripted", kids)
    if head == "Delimited" and len(sig) == 4:
        parts = ([("Token", sig[1])] if sig[1] else [])
        parts += [fold(k) for k in sig[3]]
        parts += ([("Token", sig[2])] if sig[2] else [])
        return ("Row", tuple(parts))
    if head == "Row" and len(sig) == 2:
        kids = []
        for k in sig[1]:
            f = fold(k)
            if f == ("Row", ()):
                continue                      # the dropped empty operand slot
            # A flattened fence brings its own row; splice it so nesting cannot differ.
            if isinstance(f, tuple) and f and f[0] == "Row" and _was_fence(k):
                kids.extend(f[1])
            else:
                kids.append(f)
        return ("Row", tuple(kids)) if len(kids) != 1 else kids[0]
    return tuple(tuple(fold(k) for k in p) if isinstance(p, tuple) else p for p in sig)


def _was_fence(sig: Any) -> bool:
    return isinstance(sig, tuple) and bool(sig) and sig[0] == "Delimited"


def _mark(node: Any) -> Optional[str]:
    """The canonical name of an accent mark, if the node is one."""
    if isinstance(node, tuple) and len(node) > 1 and node[0] == "Token":
        return ACCENT_CANON.get(node[1])
    return None


@dataclass
class Verdict:
    """The outcome of one round trip."""

    omml: str
    ours: Any = None
    theirs: Any = None
    error: str = ""

    @property
    def agrees(self) -> bool:
        return not self.error and self.ours == self.theirs


def check_batch(trees: Sequence[MathNode]) -> list[Verdict]:
    """Write every tree as OMML, read them all back through one pandoc run, compare."""
    rendered = [to_omml(t, indent=False, namespace=False).omml for t in trees]
    back = mathml_from_omml(rendered)
    out = []
    for tree, omml, xml in zip(trees, rendered, back):
        if xml is None:
            out.append(Verdict(omml, error="pandoc produced no MathML"))
            continue
        theirs = mathml_signature(xml)
        if theirs is None:
            out.append(Verdict(omml, error="pandoc produced unparseable MathML"))
            continue
        out.append(Verdict(omml, fold(relax(mathml_signature(to_mathml(tree)))),
                           fold(relax(theirs))))
    return out


def check(tree: MathNode) -> Verdict:
    """Round-trip a single tree.  Prefer :func:`check_batch`: pandoc starts once."""
    return check_batch([tree])[0]
