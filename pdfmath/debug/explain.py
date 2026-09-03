"""``pdfmath explain`` -- why the parser decided what it decided.

Every recogniser records the numbers it compared, so an explanation is a report, not a
reconstruction.  A superscript decision, for instance, comes back as the measured shift,
the shift Appendix G predicts for that nucleus and that style, and the residual between
them; a fraction comes back with the style its geometry fits and how far off it was.
"""

from __future__ import annotations

from typing import Any, Optional

from ..parse.context import ParseContext
from ..tree.nodes import MathNode


def explain_node(tree: MathNode, ctx: ParseContext, node_id: int) -> dict[str, Any]:
    node = tree.find(node_id)
    if node is None:
        return {"error": f"no node with id {node_id}"}
    return _describe(node, ctx)


def explain_tree(tree: MathNode, ctx: ParseContext,
                 min_confidence: float = 1.01) -> list[dict[str, Any]]:
    """Every structural decision, optionally filtered to the uncertain ones."""
    out = []
    for node in tree.walk():
        if not node.prov.rule_name or node.prov.rule_name == "leaf":
            continue
        if node.prov.confidence >= min_confidence:
            continue
        out.append(_describe(node, ctx))
    return out


def _describe(node: MathNode, ctx: ParseContext) -> dict[str, Any]:
    out: dict[str, Any] = {
        "node": node.node_id,
        "kind": node.kind,
        "relationship": node.prov.rule_name,
        "confidence": round(node.prov.confidence, 6),
        "glyphs": node.prov.glyph_ids,
        "rules": node.prov.rule_ids,
        "children": [c.node_id for c in node.children],
        "evidence": node.prov.evidence,
    }
    if node.prov.bbox:
        out["bbox"] = [round(v, 4) for v in node.prov.bbox.as_list()]
    traces = ctx.trace.for_node(node.node_id)
    if traces:
        out["trace"] = [t.to_json() for t in traces]
    return out


def format_text(entry: dict[str, Any]) -> str:
    """A compact human-readable rendering of one explanation."""
    if "error" in entry:
        return entry["error"]
    lines = [f"node {entry['node']}  {entry['kind']}"
             f"  [{entry.get('relationship')}]"
             f"  confidence {entry['confidence']:.4f}"]
    if entry.get("bbox"):
        b = entry["bbox"]
        lines.append(f"  bbox      {b[0]:.2f},{b[1]:.2f} .. {b[2]:.2f},{b[3]:.2f} (pt)")
    if entry.get("glyphs"):
        lines.append(f"  glyphs    {entry['glyphs']}")
    if entry.get("rules"):
        lines.append(f"  rules     {entry['rules']}")
    if entry.get("children"):
        lines.append(f"  children  {entry['children']}")
    ev = entry.get("evidence") or {}
    if ev:
        lines.append("  evidence:")
        width = max((len(k) for k in ev), default=0)
        for k, v in ev.items():
            if isinstance(v, float):
                lines.append(f"    {k:<{width}}  {v:+.5f}" if "residual" in k
                             else f"    {k:<{width}}  {v:.5f}")
            else:
                lines.append(f"    {k:<{width}}  {v}")
    return "\n".join(lines)
