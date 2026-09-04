"""Score the decompiler against a real paper's own source.

The pipeline, for one arXiv identifier:

    e-print source ──> displays ──> LaTeXML ──> expected MathML ──> signature
           │                                                            ║
           └──> one display per page ──> pdfTeX ──> PDF ──> pdfmath ──> signature

Both sides start from the same LaTeX and neither is derived from the other: LaTeXML reads
the source, we read the page.  Setting one display per page removes equation detection
from the measurement, so what is scored is the decompiler.

Comparison is on *relaxed* signatures (see mathml_compare.relax): grouping, invisible
operators, ``mi`` against ``mo`` and the spacing-versus-combining spelling of an accent
are all folded, because a PDF cannot record any of them and being scored on them would
measure the converters' conventions rather than the mathematics.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional

from ..corpus.arxiv import ArxivPaper, load, macro_file, one_per_page
from ..corpus.compile import CompileError, compile_expressions, have_pdflatex
from ..corpus.harness import normalise
from ..extraction.pdfminer_backend import extract_pages
from ..parse.driver import parse
from ..tree.nodes import MathNode, Unknown
from . import latexml
from .mathml_compare import mathml_signature, relax


@dataclass
class DisplayResult:
    index: int
    tex: str
    expected: Any = None
    actual: Any = None
    matched: bool = False
    skipped: Optional[str] = None
    glyphs: int = 0
    glyphs_in_tree: int = 0
    unknown_nodes: int = 0
    confidence: float = 1.0
    tree: Optional[MathNode] = None

    @property
    def scored(self) -> bool:
        return self.skipped is None


@dataclass
class PaperResult:
    paper: ArxivPaper
    results: list[DisplayResult] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def scored(self) -> list[DisplayResult]:
        return [r for r in self.results if r.scored]

    @property
    def matched(self) -> int:
        return sum(1 for r in self.scored if r.matched)

    @property
    def accuracy(self) -> float:
        s = self.scored
        return self.matched / len(s) if s else 0.0

    @property
    def glyph_recovery(self) -> float:
        total = sum(r.glyphs for r in self.results)
        got = sum(r.glyphs_in_tree for r in self.results)
        return got / total if total else 1.0

    def to_json(self) -> dict[str, Any]:
        skipped: dict[str, int] = {}
        for r in self.results:
            if r.skipped:
                skipped[r.skipped] = skipped.get(r.skipped, 0) + 1
        return {
            "identifier": self.paper.identifier,
            "documentclass": self.paper.documentclass,
            "displays_in_source": len(self.paper.displays),
            "multiline_displays_skipped": len(self.paper.multiline),
            "scored": len(self.scored),
            "matched": self.matched,
            "accuracy": round(self.accuracy, 6),
            "glyph_recovery": round(self.glyph_recovery, 6),
            "skipped": skipped,
            "error": self.error,
        }


def evaluate(identifier: str, cache_dir: str, workdir: Optional[str] = None,
             limit: Optional[int] = None, keep_trees: bool = False) -> PaperResult:
    """Fetch, re-set, decompile and score one paper."""
    paper = load(identifier, cache_dir)
    out = PaperResult(paper)
    if not paper.is_latex:
        out.error = paper.note
        return out
    if not paper.displays:
        out.error = "no single-formula displays in the source"
        return out
    if not have_pdflatex():
        out.error = "pdflatex is not installed"
        return out

    displays = paper.displays[:limit] if limit else paper.displays
    workdir = workdir or os.path.join(cache_dir, "build")
    os.makedirs(workdir, exist_ok=True)
    stem = "arxiv_" + identifier.replace("/", "_").replace(".", "_")

    try:
        corpus = compile_expressions(
            displays, workdir=workdir, name=stem, halt_on_error=False,
            source=one_per_page(paper, displays))
    except CompileError as exc:
        out.error = str(exc).splitlines()[-1] if str(exc) else "pdflatex failed"
        return out

    pages = {p.page: p for p in extract_pages(corpus.pdf_path)}
    macros = macro_file(paper, os.path.join(workdir, stem + "_macros.tex"))

    for i, tex in enumerate(displays):
        r = DisplayResult(index=i, tex=tex)
        page = pages.get(i + 1)
        if page is None:
            r.skipped = "page missing: the display did not typeset"
            out.results.append(r)
            continue
        if not page.glyphs:
            r.skipped = "page is empty"
            out.results.append(r)
            continue

        conv = latexml.to_mathml(tex, preloads=[macros])
        if not conv.ok:
            r.skipped = "LaTeXML could not convert the source"
            out.results.append(r)
            continue
        expected = mathml_signature(conv.mathml)
        if expected is None:
            r.skipped = "LaTeXML produced no MathML"
            out.results.append(r)
            continue

        try:
            tree, ctx = parse(page.glyphs, page.rules)
        except Exception as exc:                       # a crash is a failure, not a skip
            r.skipped = None
            r.expected = normalise(relax(expected))
            r.actual = f"{type(exc).__name__}: {exc}"
            out.results.append(r)
            continue

        used = {g for n in tree.walk() for g in n.prov.glyph_ids}
        r.glyphs = len(page.glyphs)
        r.glyphs_in_tree = len(used)
        r.unknown_nodes = sum(1 for n in tree.walk() if isinstance(n, Unknown))
        r.confidence = tree.structural_confidence()
        r.expected = normalise(relax(expected))
        r.actual = normalise(relax(tree.signature()))
        r.matched = r.expected == r.actual
        if keep_trees:
            r.tree = tree
        out.results.append(r)
    return out
