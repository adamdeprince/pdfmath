"""The round trip: expression -> pdfTeX -> PDF -> extraction -> decompiler -> comparison.

Metrics follow the brief:

* **glyph recovery** -- did every drawn symbol reach a leaf of the tree?
* **structural edges** -- what fraction of parent/child relationships is right?
* **node accuracy** -- were fractions called fractions and scripts called scripts?
* **exact expressions** -- is the whole reconstructed tree equal to the ground truth?

Breakdowns are by *construct*, taken from the generating expression rather than from the
result, so a construct that was missed entirely still counts against its own category.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Sequence

from ..extraction.model import PageExtract
from ..extraction.pdfminer_backend import extract_pages
from ..fonts.mathparams import Style
from ..parse.context import ParseContext, Trace, infer_math_sizes
from ..parse.driver import parse
from ..tree.nodes import MathNode, Space, Unknown
from .compile import CompiledCorpus, compile_expressions
from .grammar import Expr


# ------------------------------------------------------------------ tree comparison

def normalise(sig: Any) -> Any:
    """Canonicalise a signature before comparison.

    Both normalisations are forced on us by the medium rather than chosen; each is a
    distinction the page does not record, so ground truth must not claim it.

    **Nested rows are not observable.**  TeX renders ``{a+b}c`` and ``a+bc`` identically,
    so no decompiler can recover the grouping.  Row nesting is flattened on both sides.

    **Adjacent numbers are not observable.**  Math mode discards spaces between digits,
    so ``0 0`` and ``00`` are the same two glyphs at the same two positions -- verified,
    not assumed.  Runs of adjacent numeric siblings are therefore joined.

    Nothing else is normalised: node kinds, leaf text and child order must match exactly.
    """
    if not isinstance(sig, tuple):
        return sig
    kids = _kids(sig)
    if not kids:
        return sig
    flat: list[Any] = []
    for k in kids:
        nk = normalise(k)
        if sig[0] == "Row" and isinstance(nk, tuple) and nk and nk[0] == "Row":
            flat.extend(_kids(nk))
        elif nk is not None:
            flat.append(nk)
    flat = _join_numbers(flat)
    if sig[0] == "Row" and len(flat) == 1:
        return flat[0]
    return tuple(sig[:-1]) + (tuple(flat),)


def _join_numbers(kids: list[Any]) -> list[Any]:
    """Join runs of adjacent ``Number`` siblings; a gap between them would be a Space."""
    out: list[Any] = []
    for k in kids:
        if (out and isinstance(k, tuple) and len(k) == 2 and k[0] == "Number"
                and isinstance(out[-1], tuple) and len(out[-1]) == 2
                and out[-1][0] == "Number"):
            out[-1] = ("Number", out[-1][1] + k[1])
        else:
            out.append(k)
    return out

def edges(sig: Any, parent: Optional[str] = None,
          out: Optional[list[tuple[str, str, int]]] = None,
          index: int = 0) -> list[tuple[str, str, int]]:
    """Parent/child edges of a signature, as (parent kind, child kind, position)."""
    if out is None:
        out = []
    if sig is None:
        return out
    kind = sig[0] if isinstance(sig, tuple) else "?"
    if parent is not None:
        out.append((parent, str(kind), index))
    kids = _kids(sig)
    for i, k in enumerate(kids):
        edges(k, str(kind), out, i)
    return out


def _kids(sig: Any) -> tuple:
    if not isinstance(sig, tuple) or len(sig) < 2:
        return ()
    last = sig[-1]
    return last if isinstance(last, tuple) and all(
        isinstance(x, tuple) or x is None for x in last) else ()


def nodes_of(sig: Any) -> list[Any]:
    if sig is None:
        return []
    out = [sig[0] if isinstance(sig, tuple) else sig]
    for k in _kids(sig):
        out += nodes_of(k)
    return out


def leaf_texts(sig: Any) -> list[str]:
    """The printed text of every leaf, in order."""
    if sig is None:
        return []
    kids = _kids(sig)
    if not kids and isinstance(sig, tuple) and len(sig) >= 2 \
            and isinstance(sig[1], str):
        return [sig[1]]
    out: list[str] = []
    for k in kids:
        out += leaf_texts(k)
    return out


def _multiset_f1(a: Iterable, b: Iterable) -> tuple[int, int, int]:
    ca, cb = Counter(a), Counter(b)
    inter = sum((ca & cb).values())
    return inter, sum(ca.values()), sum(cb.values())


# ---------------------------------------------------------------------- one result

@dataclass
class CaseResult:
    index: int
    tex: str
    expected: Any
    actual: Any
    exact: bool
    edge_hits: int
    edge_expected: int
    edge_actual: int
    node_hits: int
    node_expected: int
    node_actual: int
    glyphs_extracted: int
    glyphs_in_tree: int
    unknown_nodes: int
    constructs: set[str]
    min_confidence: float
    error: Optional[str] = None
    tree: Optional[MathNode] = None
    ctx: Optional[ParseContext] = None
    extract: Optional[PageExtract] = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.exact


@dataclass
class Report:
    cases: list[CaseResult] = field(default_factory=list)

    # -- aggregate metrics ----------------------------------------------------------
    def _ratio(self, num: int, den: int) -> float:
        return 1.0 if den == 0 else num / den

    @property
    def exact(self) -> float:
        return self._ratio(sum(1 for c in self.cases if c.ok), len(self.cases))

    @property
    def glyph_recovery(self) -> float:
        return self._ratio(sum(c.glyphs_in_tree for c in self.cases),
                           sum(c.glyphs_extracted for c in self.cases))

    @property
    def edge_accuracy(self) -> float:
        hits = sum(c.edge_hits for c in self.cases)
        exp = sum(c.edge_expected for c in self.cases)
        act = sum(c.edge_actual for c in self.cases)
        p = self._ratio(hits, act)
        r = self._ratio(hits, exp)
        return 0.0 if p + r == 0 else 2 * p * r / (p + r)

    @property
    def node_accuracy(self) -> float:
        hits = sum(c.node_hits for c in self.cases)
        exp = sum(c.node_expected for c in self.cases)
        act = sum(c.node_actual for c in self.cases)
        p = self._ratio(hits, act)
        r = self._ratio(hits, exp)
        return 0.0 if p + r == 0 else 2 * p * r / (p + r)

    def by_construct(self) -> dict[str, tuple[int, int]]:
        counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for c in self.cases:
            for k in c.constructs:
                counts[k][1] += 1
                if c.ok:
                    counts[k][0] += 1
        return {k: (v[0], v[1]) for k, v in sorted(counts.items())}

    @property
    def failures(self) -> list[CaseResult]:
        return [c for c in self.cases if not c.ok]

    def to_json(self) -> dict[str, Any]:
        return {
            "cases": len(self.cases),
            "exact_expressions": round(self.exact, 6),
            "glyph_recovery": round(self.glyph_recovery, 6),
            "structural_edges": round(self.edge_accuracy, 6),
            "node_accuracy": round(self.node_accuracy, 6),
            "by_construct": {k: {"passed": p, "total": t,
                                 "rate": round(p / t, 6) if t else 1.0}
                             for k, (p, t) in self.by_construct().items()},
            "failures": [{"index": c.index, "tex": c.tex, "error": c.error,
                          "expected": repr(c.expected), "actual": repr(c.actual)}
                         for c in self.failures],
        }

    def format(self, verbose: bool = False) -> str:
        lines = [
            f"cases                     {len(self.cases)}",
            f"glyph recovery            {self.glyph_recovery * 100:9.3f}%",
            f"structural edges          {self.edge_accuracy * 100:9.3f}%",
            f"node accuracy             {self.node_accuracy * 100:9.3f}%",
            f"exact expressions         {self.exact * 100:9.3f}%",
            "",
        ]
        for k, (p, t) in self.by_construct().items():
            lines.append(f"  {k:<22s}  {p * 100.0 / t if t else 100.0:8.3f}%  ({p}/{t})")
        if verbose and self.failures:
            lines.append("")
            lines.append("failures:")
            for c in self.failures[:40]:
                lines.append(f"  [{c.index}] {c.tex}")
                if c.error:
                    lines.append(f"        error:    {c.error}")
                else:
                    lines.append(f"        expected: {c.expected}")
                    lines.append(f"        actual:   {c.actual}")
        return "\n".join(lines)


# ------------------------------------------------------------------------- the run

def run(expressions: Sequence[Expr], size: int = 10, display: bool = True,
        workdir: Optional[str] = None, keep: bool = False,
        style: Optional[Style] = None) -> Report:
    """Compile, extract, decompile and compare a batch of expressions."""
    tex = [e.to_tex() for e in expressions]
    corpus = compile_expressions(tex, workdir=workdir, size=size, display=display)
    return run_compiled(corpus, expressions, display=display, style=style, keep=keep)


def run_compiled(corpus: CompiledCorpus, expressions: Sequence[Expr],
                 display: bool = True, style: Optional[Style] = None,
                 keep: bool = False) -> Report:
    report = Report()
    pages = {p.page: p for p in extract_pages(corpus.pdf_path)}
    for i, expr in enumerate(expressions):
        page = pages.get(i + 1)
        tex = expr.to_tex()
        expected = normalise(expr.to_signature())
        if page is None:
            report.cases.append(_error_case(i, tex, expected, "page missing", expr))
            continue
        try:
            levels = infer_math_sizes([g.size for g in page.glyphs])
            ctx = ParseContext(
                text_size=levels[0],
                style=style or (Style.DISPLAY if display else Style.TEXT),
                trace=Trace(), math_sizes=levels)
            tree, ctx = parse(page.glyphs, page.rules, ctx)
        except Exception as exc:                      # a parser crash is a test failure
            report.cases.append(_error_case(
                i, tex, expected, f"{type(exc).__name__}: {exc}", expr))
            continue
        report.cases.append(_compare(i, tex, expected, tree, ctx, page, expr, keep))
    return report


def _error_case(i: int, tex: str, expected: Any, msg: str, expr: Expr) -> CaseResult:
    return CaseResult(i, tex, expected, None, False, 0, len(edges(expected)), 0,
                      0, len(nodes_of(expected)), 0, 0, 0, 0,
                      expr.constructs(), 0.0, msg)


def _compare(i: int, tex: str, expected: Any, tree: MathNode, ctx: ParseContext,
             page: PageExtract, expr: Expr, keep: bool) -> CaseResult:
    actual = normalise(tree.signature())
    e_edges, a_edges = edges(expected), edges(actual)
    eh, ee, ea = _multiset_f1(e_edges, a_edges)
    e_nodes, a_nodes = nodes_of(expected), nodes_of(actual)
    nh, ne, na = _multiset_f1(e_nodes, a_nodes)

    in_tree: set[int] = set()
    unknowns = 0
    min_conf = 1.0
    for n in tree.walk():
        in_tree.update(n.prov.glyph_ids)
        if isinstance(n, Unknown):
            unknowns += 1
        min_conf = min(min_conf, n.prov.confidence)

    return CaseResult(
        index=i, tex=tex, expected=expected, actual=actual,
        exact=(expected == actual),
        edge_hits=eh, edge_expected=ee, edge_actual=ea,
        node_hits=nh, node_expected=ne, node_actual=na,
        glyphs_extracted=len(page.glyphs), glyphs_in_tree=len(in_tree),
        unknown_nodes=unknowns, constructs=expr.constructs(),
        min_confidence=min_conf,
        tree=tree if keep else None, ctx=ctx if keep else None,
        extract=page if keep else None)
