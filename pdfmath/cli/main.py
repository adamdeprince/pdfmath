"""The ``pdfmath`` command line.

    pdfmath dump      paper.pdf --page 3
    pdfmath debug-svg paper.pdf --page 3 -o out.html
    pdfmath extract   paper.pdf --page 5 --mathml
    pdfmath extract   paper.pdf --page 5 --bbox x0,y0,x1,y1
    pdfmath explain   paper.pdf --page 5 --node 17
    pdfmath benchmark --n 500
    pdfmath fonts     cmmi10

Coordinates on the command line are in TeX points measured from the bottom-left of the
page, the same units the tool reports; ``--bbox-bp`` accepts PDF big points instead.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Optional

from ..extraction.pdfminer_backend import extract_page, extract_pages
from ..fonts.mathparams import Style, params_for
from ..fonts.metrics import FontMetrics
from ..fonts.normalize import identify
from ..fonts.tfm import SIGMA_NAMES, XI_NAMES, load_tfm
from ..geometry.bbox import BBox
from ..mathml.serializer import to_mathml
from ..parse.context import ParseContext, Trace
from ..parse.driver import parse
from ..units import bp_to_pt


def _bbox(arg: Optional[str], in_bp: bool = False) -> Optional[BBox]:
    if not arg:
        return None
    try:
        v = [float(x) for x in arg.replace(" ", "").split(",")]
    except ValueError:
        raise SystemExit(f"--bbox expects four numbers, got {arg!r}")
    if len(v) != 4:
        raise SystemExit(f"--bbox expects four numbers, got {arg!r}")
    if in_bp:
        v = [bp_to_pt(x) for x in v]
    return BBox(min(v[0], v[2]), min(v[1], v[3]), max(v[0], v[2]), max(v[1], v[3]))


def _style(name: str) -> Style:
    return {"display": Style.DISPLAY, "text": Style.TEXT,
            "script": Style.SCRIPT, "scriptscript": Style.SCRIPTSCRIPT}[name]


# --------------------------------------------------------------------------- commands

def cmd_dump(args: argparse.Namespace) -> int:
    pages = list(extract_pages(args.pdf, [args.page] if args.page else None))
    payload: Any = [p.to_json() for p in pages]
    if args.page:
        payload = payload[0] if payload else {}
    print(json.dumps(payload, indent=None if args.compact else 2, ensure_ascii=False))
    return 0


def cmd_debug_svg(args: argparse.Namespace) -> int:
    from ..debug.svg import SvgOptions, render

    page = extract_page(args.pdf, args.page)
    region = _bbox(args.bbox, args.bbox_bp)
    tree = None
    if not args.no_parse:
        src = page.in_region(region) if region else page
        tree, _ = parse(src.glyphs, src.rules,
                        ParseContext(text_size=max((g.size for g in src.glyphs),
                                                   default=10.0),
                                     style=_style(args.style), trace=Trace()))
    opts = SvgOptions(scale=args.scale)
    out = render(page, region, tree, opts, as_html=args.html,
                 title=f"{args.pdf} page {args.page}")
    if args.output:
        with open(args.output, "w") as fh:
            fh.write(out)
        print(f"wrote {args.output}", file=sys.stderr)
    else:
        print(out)
    return 0


def _parse_region(page, region: Optional[BBox], style: Style):
    src = page.in_region(region) if region else page
    ctx = ParseContext(text_size=max((g.size for g in src.glyphs), default=10.0),
                       style=style, trace=Trace())
    tree, ctx = parse(src.glyphs, src.rules, ctx)
    return src, tree, ctx


def cmd_extract(args: argparse.Namespace) -> int:
    from ..detection.equations import find_displayed_equations

    style = _style(args.style)
    results = []
    pages = list(extract_pages(args.pdf, [args.page] if args.page else None))
    region = _bbox(args.bbox, args.bbox_bp)
    for page in pages:
        regions = ([type("R", (), {"bbox": region, "confidence": 1.0,
                                   "evidence": {"source": "--bbox"}})()]
                   if region is not None
                   else find_displayed_equations(page))
        equations = []
        for r in regions:
            src, tree, ctx = _parse_region(page, r.bbox, style)
            conf = min([n.prov.confidence for n in tree.walk()] or [1.0])
            entry: dict[str, Any] = {
                "bbox": [round(v, 4) for v in r.bbox.as_list()],
                "confidence": round(min(conf, r.confidence), 6),
                "detection": r.evidence,
                "glyph_count": len(src.glyphs),
                "rule_count": len(src.rules),
            }
            if args.mathml or not args.tree:
                entry["mathml"] = to_mathml(tree, indent=not args.compact,
                                            include_provenance=args.provenance)
            if args.tree:
                entry["tree"] = tree.to_json()
            if args.explain:
                from ..debug.explain import explain_tree
                entry["explanations"] = explain_tree(tree, ctx, min_confidence=1.01)
            equations.append(entry)
        results.append({"page": page.page, "equations": equations})

    payload: Any = results[0] if args.page and results else results
    if args.mathml and not args.json:
        found = 0
        for pg in results:
            for eq in pg["equations"]:
                print(eq["mathml"])
                found += 1
        if not found:
            print("no displayed equation detected; pass --bbox to decompile a region "
                  "directly", file=sys.stderr)
            return 1
        return 0
    print(json.dumps(payload, indent=None if args.compact else 2, ensure_ascii=False))
    return 0


def cmd_explain(args: argparse.Namespace) -> int:
    from ..debug.explain import explain_node, explain_tree, format_text

    page = extract_page(args.pdf, args.page)
    _, tree, ctx = _parse_region(page, _bbox(args.bbox, args.bbox_bp), _style(args.style))
    if args.node is not None:
        entries = [explain_node(tree, ctx, args.node)]
    else:
        entries = explain_tree(tree, ctx, min_confidence=args.max_confidence)
    if args.json:
        print(json.dumps(entries, indent=2, ensure_ascii=False))
    else:
        for e in entries:
            print(format_text(e))
            print()
    return 0


def cmd_benchmark(args: argparse.Namespace) -> int:
    from ..corpus.generate import GenConfig, expressions
    from ..corpus.harness import run
    from ..corpus.milestone import EXTENDED, MILESTONE

    suites: list[tuple[str, list]] = []
    if args.suite in ("all", "milestone"):
        suites.append(("milestone", MILESTONE))
    if args.suite in ("all", "extended"):
        suites.append(("extended", EXTENDED))
    if args.suite in ("all", "random"):
        suites.append((f"random(seed={args.seed}, n={args.n})",
                       expressions(args.seed, args.n,
                                   GenConfig(max_depth=args.max_depth))))
    reports = {}
    for name, corpus in suites:
        report = run(corpus, workdir=args.workdir, size=args.size)
        reports[name] = report
        if not args.json:
            print(f"=== {name} " + "=" * max(0, 50 - len(name)))
            print(report.format(verbose=args.verbose))
            print()
    if args.json:
        print(json.dumps({k: v.to_json() for k, v in reports.items()},
                         indent=2, ensure_ascii=False))
    return 0 if all(r.exact >= args.threshold for r in reports.values()) else 1


def cmd_fonts(args: argparse.Namespace) -> int:
    ident = identify(args.font)
    tfm = load_tfm(ident.tfm_name) if ident.tfm_name else None
    out: dict[str, Any] = {
        "input": args.font,
        "base_name": ident.base_name,
        "family": ident.family,
        "design_size": ident.design_size,
        "encoding": ident.encoding,
        "mathvariant": ident.mathvariant,
        "tfm": ident.tfm_name,
        "tfm_found": tfm is not None,
        "description": ident.description,
    }
    if tfm is not None:
        out["tfm_path"] = tfm.path
        out["coding_scheme"] = tfm.coding_scheme
        names = SIGMA_NAMES if tfm.is_math_symbol_font else XI_NAMES
        out["parameters"] = {names[i]: round(tfm.param(i), 6)
                             for i in range(1, min(len(tfm.params), len(names)))}
        if args.code is not None:
            g = FontMetrics.lookup(args.font, args.code, args.size)
            out["glyph"] = {
                "code": args.code, "name": g.glyph, "unicode": g.unicode,
                "atom": g.atom.short, "role": g.role.name,
                "width_pt": round(g.metrics.width, 5),
                "height_pt": round(g.metrics.height, 5),
                "depth_pt": round(g.metrics.depth, 5),
                "italic_pt": round(g.metrics.italic, 5),
                "larger_variants": [hex(c) for c in tfm.charlist(args.code)[1:]],
            }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


# ------------------------------------------------------------------------------ parser

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pdfmath",
        description="Decompile TeX mathematics from born-digital PDFs.")
    sub = p.add_subparsers(dest="command", required=True)

    def add_common(sp, page_required=False):
        sp.add_argument("pdf")
        sp.add_argument("--page", type=int, default=None if not page_required else 1,
                        required=page_required, help="1-based page number")
        sp.add_argument("--bbox", default=None,
                        help="x0,y0,x1,y1 in TeX points from the page's bottom-left")
        sp.add_argument("--bbox-bp", action="store_true",
                        help="interpret --bbox in PDF big points instead")
        sp.add_argument("--style", default="display",
                        choices=["display", "text", "script", "scriptscript"])

    d = sub.add_parser("dump", help="positioned glyphs and rules, as JSON")
    d.add_argument("pdf")
    d.add_argument("--page", type=int, default=None)
    d.add_argument("--compact", action="store_true")
    d.set_defaults(func=cmd_dump)

    s = sub.add_parser("debug-svg", help="render what the parser saw")
    add_common(s, page_required=True)
    s.add_argument("-o", "--output")
    s.add_argument("--html", action="store_true", help="wrap in HTML with layer toggles")
    s.add_argument("--scale", type=float, default=3.0)
    s.add_argument("--no-parse", action="store_true", help="skip the structure layers")
    s.set_defaults(func=cmd_debug_svg)

    e = sub.add_parser("extract", help="decompile equations to MathML")
    add_common(e)
    e.add_argument("--mathml", action="store_true", help="print MathML only")
    e.add_argument("--tree", action="store_true", help="include the full tree")
    e.add_argument("--json", action="store_true", help="force JSON output")
    e.add_argument("--explain", action="store_true", help="include the decision trace")
    e.add_argument("--provenance", action="store_true",
                   help="emit glyph ids as MathML attributes")
    e.add_argument("--compact", action="store_true")
    e.set_defaults(func=cmd_extract)

    x = sub.add_parser("explain", help="why the parser made an inference")
    add_common(x, page_required=True)
    x.add_argument("--node", type=int, default=None)
    x.add_argument("--max-confidence", type=float, default=1.01,
                   help="only report decisions below this confidence")
    x.add_argument("--json", action="store_true")
    x.set_defaults(func=cmd_explain)

    b = sub.add_parser("benchmark", help="compile a synthetic corpus and score it")
    b.add_argument("--suite", default="all",
                   choices=["all", "milestone", "extended", "random"])
    b.add_argument("--n", type=int, default=200)
    b.add_argument("--seed", type=int, default=1)
    b.add_argument("--max-depth", type=int, default=3)
    b.add_argument("--size", type=int, default=10)
    b.add_argument("--workdir", default="corpus/build")
    b.add_argument("--threshold", type=float, default=0.0,
                   help="exit non-zero if exact-expression accuracy falls below this")
    b.add_argument("--verbose", action="store_true")
    b.add_argument("--json", action="store_true")
    b.set_defaults(func=cmd_benchmark)

    f = sub.add_parser("fonts", help="what we know about a TeX font")
    f.add_argument("font", help="a PDF font name, e.g. CMMI10 or ABCDEF+CMSY7")
    f.add_argument("--code", type=lambda v: int(v, 0), default=None)
    f.add_argument("--size", type=float, default=10.0)
    f.set_defaults(func=cmd_fonts)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
