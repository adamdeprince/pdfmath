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
from ..speech.engine import DOMAINS as SPEECH_DOMAINS
from ..speech.engine import STYLES as SPEECH_STYLES
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
        from ..parse.context import infer_math_sizes
        levels = infer_math_sizes([g.size for g in src.glyphs])
        tree, _ = parse(src.glyphs, src.rules,
                        ParseContext(text_size=levels[0], style=_style(args.style),
                                     trace=Trace(), math_sizes=levels))
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
    from ..parse.driver import parse_region
    return parse_region(page, region, style)


def cmd_extract(args: argparse.Namespace) -> int:
    from ..detection import find_equations

    style = _style(args.style)
    results = []
    spoken: list[tuple[dict, Any]] = []
    pages = list(extract_pages(args.pdf, [args.page] if args.page else None))
    region = _bbox(args.bbox, args.bbox_bp)
    for page in pages:
        regions = ([type("R", (), {"bbox": region, "confidence": 1.0, "style": None,
                                   "evidence": {"source": "--bbox"}})()]
                   if region is not None
                   else find_equations(page, inline=args.inline))
        equations = []
        for r in regions:
            # A region found inline was set in text style; one found by its shape was
            # set in display style.  Every Appendix G prediction depends on which.
            region_style = _style(r.style) if getattr(r, "style", None) else style
            src, tree, ctx = _parse_region(page, r.bbox, region_style)
            entry: dict[str, Any] = {
                "bbox": [round(v, 4) for v in r.bbox.as_list()],
                "style": region_style.name.lower(),
                "confidence": round(min(tree.structural_confidence(),
                                        r.confidence), 6),
                "spacing_confidence": round(tree.spacing_confidence(), 6),
                "detection_confidence": round(r.confidence, 6),
                "detection": r.evidence,
                "glyph_count": len(src.glyphs),
                "rule_count": len(src.rules),
            }
            if args.latex:
                from ..latex.serializer import to_latex
                rendered = to_latex(tree)
                entry["latex"] = rendered.latex
                if rendered.unreproducible:
                    entry["latex_unreproducible"] = rendered.unreproducible
            if args.asciimath:
                from ..asciimath.serializer import to_asciimath
                am = to_asciimath(tree)
                entry["asciimath"] = am.asciimath
                if am.unreproducible:
                    entry["asciimath_unreproducible"] = am.unreproducible
            if args.wpeq:
                from ..wordperfect.serializer import to_wpeq
                wp = to_wpeq(tree)
                entry["wpeq"] = wp.wpeq
                if wp.unreproducible:
                    entry["wpeq_unreproducible"] = wp.unreproducible
                if wp.unverified:
                    entry["wpeq_unverified"] = wp.unverified
            if args.omml:
                from ..omml.serializer import to_omml
                om = to_omml(tree, indent=not args.compact, display=True)
                entry["omml"] = om.omml
                if om.unreproducible:
                    entry["omml_unreproducible"] = om.unreproducible
            if args.mathml or not _requested(args):
                entry["mathml"] = to_mathml(tree, indent=not args.compact,
                                            include_provenance=args.provenance)
            if args.speech:
                spoken.append((entry, tree))
            if args.tree:
                entry["tree"] = tree.to_json()
            if args.lg:
                from ..mathml.lgeval import to_label_graph
                entry["label_graph"] = to_label_graph(
                    tree, f"pdfmath page {page.page} bbox {entry['bbox']}")
            if args.explain:
                from ..debug.explain import explain_tree
                entry["explanations"] = explain_tree(tree, ctx, min_confidence=1.01)
            equations.append(entry)
        results.append({"page": page.page, "equations": equations})

    if spoken:
        from ..speech import SpeechError, speak_batch, speech_mathml
        try:
            said = speak_batch([speech_mathml(t, indent=False) for _, t in spoken],
                               domain=args.speech_style,
                               style=args.speech_verbosity,
                               markup="ssml" if args.ssml else "none")
        except SpeechError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        for (entry, _), text in zip(spoken, said):
            entry["speech"] = text

    payload: Any = results[0] if args.page and results else results
    single = _single_text_format(args)
    if single and not args.json and not args.tree:
        found = 0
        for pg in results:
            for eq in pg["equations"]:
                print(eq[single])
                found += 1
        if not found:
            print("no displayed equation detected; pass --bbox to decompile a region "
                  "directly", file=sys.stderr)
            return 1
        return 0
    print(json.dumps(payload, indent=None if args.compact else 2, ensure_ascii=False))
    return 0


#: Output formats that are text a person can read straight out of the terminal.  When
#: exactly one is asked for, it is printed bare rather than wrapped in JSON.
_TEXT_FORMATS = ("mathml", "latex", "asciimath", "omml", "wpeq", "speech")


def _requested(args: argparse.Namespace) -> bool:
    """True when the command line named any output format at all."""
    return bool(args.tree or args.lg
                or any(getattr(args, f, False) for f in _TEXT_FORMATS))


def _single_text_format(args: argparse.Namespace) -> Optional[str]:
    chosen = [f for f in _TEXT_FORMATS if getattr(args, f, False)]
    if not chosen and not _requested(args):
        return "mathml"
    return chosen[0] if len(chosen) == 1 else None


def cmd_speak(args: argparse.Namespace) -> int:
    """Read a document's equations aloud, as text."""
    from ..detection import find_equations
    from ..speech import SpeechError, speak_batch, speech_mathml

    style = _style(args.style)
    found: list[tuple[int, Any, Any]] = []
    for page in extract_pages(args.pdf, [args.page] if args.page else None):
        region = _bbox(args.bbox, args.bbox_bp)
        if region is not None:
            regions = [(region, style)]
        else:
            regions = [(r.bbox, _style(r.style))
                       for r in find_equations(page, inline=args.inline)]
        for box, region_style in regions:
            _, tree, _ = _parse_region(page, box, region_style)
            found.append((page.page, box, tree))
    if not found:
        print("no displayed equation detected; pass --bbox to speak a region directly",
              file=sys.stderr)
        return 1
    try:
        said = speak_batch([speech_mathml(t, indent=False) for _, _, t in found],
                           domain=args.rules, style=args.verbosity,
                           markup="ssml" if args.ssml else "none")
    except SpeechError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    for (page_no, _, _), text in zip(found, said):
        print(f"page {page_no}: {text}" if args.label else text)
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
        report = run(corpus, workdir=args.workdir, size=args.size,
                     keep=bool(args.lg_dir))
        if args.lg_dir:
            _write_label_graphs(args.lg_dir, name, corpus, report)
        reports[name] = report
        if not args.json:
            print(f"=== {name} " + "=" * max(0, 50 - len(name)))
            print(report.format(verbose=args.verbose))
            print()
    if args.json:
        print(json.dumps({k: v.to_json() for k, v in reports.items()},
                         indent=2, ensure_ascii=False))
    return 0 if all(r.exact >= args.threshold for r in reports.values()) else 1


def cmd_roundtrip(args: argparse.Namespace) -> int:
    """Recompile what we recovered and check it lands on the same page.

    The oracle needs no ground truth and no second system, so unlike ``benchmark`` it
    works on real documents.  A verdict of ``exact`` means every glyph came back in the
    same place relative to its neighbours -- that is, the structure we recovered is one
    TeX compiles to the page we started from.
    """
    from ..detection.equations import find_displayed_equations
    from ..eval.roundtrip import roundtrip

    style = _style(args.style)
    region = _bbox(args.bbox, args.bbox_bp)
    rows: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for page in extract_pages(args.pdf, args.pages):
        regions = ([type("R", (), {"bbox": region})()] if region is not None
                   else find_displayed_equations(page))
        for i, r in enumerate(regions):
            src, tree, ctx = _parse_region(page, r.bbox, style)
            res = roundtrip(tree, src, ctx, workdir=args.workdir,
                            name=f"rt_p{page.page}_{i}")
            counts[res.verdict] = counts.get(res.verdict, 0) + 1
            entry = res.to_json()
            entry["page"] = page.page
            entry["bbox"] = [round(v, 2) for v in r.bbox.as_list()]
            entry["glyphs"]["region"] = len(src.glyphs)
            rows.append(entry)

    total = sum(counts.values())
    summary = {"equations": total, "verdicts": counts,
               "exact_rate": round(counts.get("exact", 0) / total, 6) if total else 1.0}
    if args.json:
        print(json.dumps({"summary": summary, "equations": rows}, indent=2,
                         ensure_ascii=False))
        return 0 if total and counts.get("exact", 0) == total else 1

    print(f"{args.pdf}")
    print(f"  equations            {total}")
    for verdict in ("exact", "shifted", "different", "incomplete", "uncompilable"):
        if verdict in counts:
            print(f"  {verdict:<20s} {counts[verdict]:4d}"
                  f"   {100 * counts[verdict] / total:5.1f}%")
    print()
    shown = 0
    for row in rows:
        if row["verdict"] == "exact" and not args.all:
            continue
        if shown >= args.show:
            break
        shown += 1
        print(f"  page {row['page']} {row['bbox']}  [{row['verdict']}] "
              f"glyphs {row['glyphs']['original']}/{row['glyphs']['rebuilt']}"
              + (f"  max offset {row['max_offset_pt']} pt"
                 if row.get("max_offset_pt") is not None else ""))
        print(f"      {row['latex'][:160]}")
        for m in row["mismatches"][:3]:
            print(f"      #{m['index']}: {m['original']} -> {m['rebuilt']}")
        for u in row["unreproducible"][:2]:
            print(f"      unreproducible: {u}")
    return 0 if total and counts.get("exact", 0) == total else 1


def cmd_survey(args: argparse.Namespace) -> int:
    """Triage a real document: what was found, how sure we are, what is unresolved.

    This is the second-milestone workflow in one command.  It does not need ground
    truth, because the things worth looking at first do not: a glyph that never reached
    the tree, an ``Unknown`` node, a structural inference below the confidence floor.
    Each of those is a lead, and the intended next step is to reproduce it as a
    *synthetic* case rather than to special-case the document.
    """
    from ..detection.equations import find_displayed_equations
    from ..tree.nodes import Space, Unknown

    style = _style(args.style)
    pages = list(extract_pages(args.pdf, args.pages))
    rows: list[dict[str, Any]] = []
    totals = {"equations": 0, "glyphs": 0, "glyphs_in_tree": 0, "unknown_nodes": 0,
              "low_confidence_nodes": 0}
    weakest: dict[str, int] = {}

    for page in pages:
        for region in find_displayed_equations(page):
            src, tree, ctx = _parse_region(page, region.bbox, style)
            in_tree = {g for n in tree.walk() for g in n.prov.glyph_ids}
            missing = sorted({g.id for g in src.glyphs} - in_tree)
            unknowns = [n for n in tree.walk() if isinstance(n, Unknown)]
            weak = [n for n in tree.walk()
                    if not isinstance(n, Space) and n.prov.rule_name
                    and n.prov.rule_name != "leaf"
                    and n.prov.confidence < args.floor]
            for n in weak:
                weakest[n.prov.rule_name] = weakest.get(n.prov.rule_name, 0) + 1

            totals["equations"] += 1
            totals["glyphs"] += len(src.glyphs)
            totals["glyphs_in_tree"] += len(in_tree)
            totals["unknown_nodes"] += len(unknowns)
            totals["low_confidence_nodes"] += len(weak)

            row: dict[str, Any] = {
                "page": page.page,
                "bbox": [round(v, 2) for v in region.bbox.as_list()],
                "glyphs": len(src.glyphs),
                "confidence": round(tree.structural_confidence(), 4),
                "spacing_confidence": round(tree.spacing_confidence(), 4),
                "unresolved_glyphs": missing,
                "unknown_nodes": [{"id": n.node_id, "reason": n.reason}
                                  for n in unknowns],
                "weak_inferences": [
                    {"id": n.node_id, "kind": n.kind, "rule": n.prov.rule_name,
                     "confidence": round(n.prov.confidence, 4),
                     "evidence": {k: v for k, v in n.prov.evidence.items()
                                  if "residual" in k or "expected" in k}}
                    for n in weak],
            }
            if args.mathml:
                row["mathml"] = to_mathml(tree, indent=False)
            rows.append(row)

    summary = {
        **totals,
        "glyph_recovery": (round(totals["glyphs_in_tree"] / totals["glyphs"], 6)
                           if totals["glyphs"] else 1.0),
        "weak_inferences_by_recogniser": dict(sorted(weakest.items(),
                                                     key=lambda kv: -kv[1])),
        "confidence_floor": args.floor,
    }
    if args.json:
        print(json.dumps({"summary": summary, "equations": rows}, indent=2,
                         ensure_ascii=False))
        return 0

    print(f"{args.pdf}")
    print(f"  equations              {summary['equations']}")
    print(f"  glyph recovery         {summary['glyph_recovery'] * 100:.3f}%  "
          f"({summary['glyphs_in_tree']}/{summary['glyphs']})")
    print(f"  Unknown nodes          {summary['unknown_nodes']}")
    print(f"  inferences below {args.floor:.2f}  {summary['low_confidence_nodes']}")
    if summary["weak_inferences_by_recogniser"]:
        print("  by recogniser:")
        for name, n in summary["weak_inferences_by_recogniser"].items():
            print(f"    {name:<20s} {n}")
    print()
    shown = 0
    for row in sorted(rows, key=lambda r: r["confidence"]):
        if shown >= args.show:
            break
        shown += 1
        print(f"  page {row['page']} bbox {row['bbox']}  "
              f"confidence {row['confidence']:.4f}  glyphs {row['glyphs']}")
        for u in row["unknown_nodes"]:
            print(f"      unknown #{u['id']}: {u['reason']}")
        for w in row["weak_inferences"][:3]:
            print(f"      {w['rule']} #{w['id']} at {w['confidence']:.4f}  "
                  f"{w['evidence']}")
        if args.mathml:
            print(f"      {row['mathml'][:200]}")
    return 0


def _write_label_graphs(directory: str, suite: str, corpus, report) -> None:
    """Write matching ground-truth and output label graphs for LgEval.

    Two files per expression, named so that LgEval's ``evaluate`` can pair them.  The
    ground truth is written from the generating expression, never from the PDF, so the
    same files also serve as ground truth for any other system run on the same corpus.
    """
    import os

    from ..mathml.lgeval import to_label_graph
    from ..parse.driver import parse

    gt_dir = os.path.join(directory, suite, "ground_truth")
    out_dir = os.path.join(directory, suite, "output")
    os.makedirs(gt_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)
    for i, (expr, case) in enumerate(zip(corpus, report.cases)):
        stem = f"{suite}_{i:05d}.lg"
        if case.tree is not None:
            with open(os.path.join(out_dir, stem), "w") as fh:
                fh.write(to_label_graph(case.tree, case.tex))
        if case.extract is not None:
            truth, _ = parse(case.extract.glyphs, case.extract.rules)
            with open(os.path.join(gt_dir, stem), "w") as fh:
                fh.write("# ground truth is the generating expression, not a parse\n"
                         f"# {case.tex}\n" + to_label_graph(truth, ""))
    print(f"wrote label graphs for {suite} to {directory}", file=sys.stderr)


def cmd_arxiv(args: argparse.Namespace) -> int:
    """Score the decompiler against a real paper's own LaTeX source.

    Both sides start from the same source and neither is derived from the other: LaTeXML
    reads it, we read the page pdfTeX makes from it.  Each display is re-set on its own
    page using the paper's preamble, which takes equation detection out of the
    measurement so that what is scored is the decompiler.
    """
    from ..eval.arxiv_eval import evaluate
    from ..eval.latexml import available

    if not available():
        print("latexmlmath is not installed (brew install latexml)", file=sys.stderr)
        return 2

    reports = []
    scored = matched = glyphs = in_tree = 0
    for identifier in args.identifiers:
        result = evaluate(identifier, args.cache, workdir=args.workdir,
                          limit=args.limit)
        reports.append(result)
        scored += len(result.scored)
        matched += result.matched
        glyphs += sum(r.glyphs for r in result.results)
        in_tree += sum(r.glyphs_in_tree for r in result.results)

    if args.json:
        print(json.dumps({
            "papers": [r.to_json() for r in reports],
            "totals": {"scored": scored, "matched": matched,
                       "accuracy": round(matched / scored, 6) if scored else 0.0,
                       "glyph_recovery": (round(in_tree / glyphs, 6) if glyphs else 1.0)},
        }, indent=2, ensure_ascii=False))
        return 0

    for result in reports:
        j = result.to_json()
        if j["error"]:
            print(f"  {j['identifier']:<20s} skipped: {j['error']}")
            continue
        print(f"  {j['identifier']:<20s} {j['scored']:3d} scored  {j['matched']:3d} "
              f"matched ({100 * j['accuracy']:5.1f}%)  glyph recovery "
              f"{100 * j['glyph_recovery']:6.2f}%")
        for reason, n in j["skipped"].items():
            print(f"        {n:3d} skipped: {reason}")
        if args.show:
            for r in [x for x in result.scored if not x.matched][:args.show]:
                print(f"        DIFF {r.tex[:70]!r}")
                print(f"             expected {str(r.expected)[:120]}")
                print(f"             actual   {str(r.actual)[:120]}")
    if scored:
        print()
        print(f"  total: {matched}/{scored} = {100 * matched / scored:.1f}% exact, "
              f"glyph recovery {100 * in_tree / max(glyphs, 1):.3f}%")
    return 0


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
    e.add_argument("--inline", action="store_true",
                   help="also find formulas inside paragraphs, not just displays")
    e.add_argument("--mathml", action="store_true", help="print MathML only")
    e.add_argument("--latex", action="store_true", help="include LaTeX")
    e.add_argument("--asciimath", action="store_true",
                   help="include AsciiMath, a linear syntax that stays readable")
    e.add_argument("--omml", action="store_true",
                   help="include Office MathML, the equation format Word stores")
    e.add_argument("--wpeq", action="store_true",
                   help="include the WordPerfect 5.1 equation language")
    e.add_argument("--speech", action="store_true",
                   help="include a spoken rendering (needs tools/sre; see `speak`)")
    e.add_argument("--speech-style", choices=SPEECH_DOMAINS, default="clearspeak",
                   help="which rule set to speak with (default: clearspeak)")
    e.add_argument("--speech-verbosity", choices=SPEECH_STYLES, default="default",
                   help="how much bracketing to speak (default: default)")
    e.add_argument("--ssml", action="store_true",
                   help="emit SSML rather than plain text, for a speech synthesiser")
    e.add_argument("--tree", action="store_true", help="include the full tree")
    e.add_argument("--lg", action="store_true",
                   help="include an LgEval label graph, for comparison against "
                        "CROHME/MathSeer tooling")
    e.add_argument("--json", action="store_true", help="force JSON output")
    e.add_argument("--explain", action="store_true", help="include the decision trace")
    e.add_argument("--provenance", action="store_true",
                   help="emit glyph ids as MathML attributes")
    e.add_argument("--compact", action="store_true")
    e.set_defaults(func=cmd_extract)

    k = sub.add_parser("speak", help="read a document's equations aloud, as text")
    k.add_argument("pdf")
    k.add_argument("--page", type=int, help="1-based page number")
    k.add_argument("--bbox", help="x0,y0,x1,y1 in TeX points from the page's bottom-left")
    k.add_argument("--bbox-bp", action="store_true",
                   help="interpret --bbox in PDF big points instead")
    k.add_argument("--style", choices=[s.name.lower() for s in Style], default="display")
    k.add_argument("--inline", action="store_true",
                   help="also read formulas inside paragraphs, not just displays")
    k.add_argument("--rules", choices=SPEECH_DOMAINS, default="clearspeak",
                   help="clearspeak reads naturally; mathspeak is unambiguous")
    k.add_argument("--verbosity", choices=SPEECH_STYLES, default="default",
                   help="brief and sbrief drop the longer bracketing phrases")
    k.add_argument("--ssml", action="store_true",
                   help="emit SSML, so a synthesiser pauses in the right places")
    k.add_argument("--label", action="store_true", help="prefix each line with its page")
    k.set_defaults(func=cmd_speak)

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
    b.add_argument("--lg-dir", default=None,
                   help="also write LgEval label graphs here, for comparison against "
                        "CROHME/MathSeer tooling")
    b.set_defaults(func=cmd_benchmark)

    t = sub.add_parser("roundtrip",
                       help="recompile what was recovered and compare the pages")
    t.add_argument("pdf")
    t.add_argument("--pages", type=int, nargs="*", default=None)
    t.add_argument("--bbox", default=None,
                   help="x0,y0,x1,y1 in TeX points; skips equation detection")
    t.add_argument("--bbox-bp", action="store_true")
    t.add_argument("--style", default="display",
                   choices=["display", "text", "script", "scriptscript"])
    t.add_argument("--workdir", default=None)
    t.add_argument("--show", type=int, default=8)
    t.add_argument("--all", action="store_true", help="list the exact ones too")
    t.add_argument("--json", action="store_true")
    t.set_defaults(func=cmd_roundtrip)

    v = sub.add_parser("survey", help="triage a real document")
    v.add_argument("pdf")
    v.add_argument("--pages", type=int, nargs="*", default=None,
                   help="1-based page numbers; default every page")
    v.add_argument("--style", default="display",
                   choices=["display", "text", "script", "scriptscript"])
    v.add_argument("--floor", type=float, default=0.9,
                   help="report structural inferences below this confidence")
    v.add_argument("--show", type=int, default=8,
                   help="how many of the weakest equations to print")
    v.add_argument("--mathml", action="store_true")
    v.add_argument("--json", action="store_true")
    v.set_defaults(func=cmd_survey)

    a = sub.add_parser("arxiv",
                       help="score against a real paper's own LaTeX source, via LaTeXML")
    a.add_argument("identifiers", nargs="+",
                   help="arXiv identifiers, e.g. math/0211159v1")
    a.add_argument("--cache", default="corpus/arxiv",
                   help="where to keep downloaded sources")
    a.add_argument("--workdir", default=None)
    a.add_argument("--limit", type=int, default=None,
                   help="score at most this many displays per paper")
    a.add_argument("--show", type=int, default=0,
                   help="print this many disagreements per paper")
    a.add_argument("--json", action="store_true")
    a.set_defaults(func=cmd_arxiv)

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
