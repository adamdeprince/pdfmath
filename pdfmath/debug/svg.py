"""SVG rendering of everything the parser saw and everything it concluded.

If a parse goes wrong, the first question is always the same: what geometry did the
recogniser actually receive?  This renderer answers it.  Each kind of information is a
separate layer with its own CSS class, so layers can be switched off in the generated
HTML wrapper (``--html``) or by editing the ``<style>`` block of the standalone SVG.

Layers:

    glyphs        the characters, drawn in a fallback serif face
    boxes         each glyph's *TeX* box (width x height+depth), not its ink box
    baselines     the reference point and baseline of every glyph
    labels        glyph id, font and size
    rules         extracted rules, with their measured thickness
    structure     the recovered tree: fractions, scripts, radicals, fences, matrices
    links         parent-child edges of the tree

Note that ``boxes`` are TFM boxes.  They are what TeX positioned and therefore what the
parser reasons about; they are deliberately not the ink extents, and a glyph will often
overflow its own box (cmmi's ``f``) or sit far inside it (cmsy's radical).
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from ..extraction.model import Glyph, PageExtract, Rule
from ..geometry.bbox import BBox
from ..tree.nodes import (Accent, Delimited, Fraction, MathNode, Matrix, MatrixCell,
                          MatrixRow, Radical, SubSup, Subscript, Superscript, UnderOver)

_CSS = """
.bg     { fill: #ffffff; }
.glyph  { font-family: "Latin Modern Math","STIX Two Math","Cambria Math",serif;
          fill: #111; }
.box    { fill: none; stroke: #2a7ae2; stroke-width: 0.3; }
.ink    { fill: none; stroke: #b0b0b0; stroke-width: 0.2; stroke-dasharray: 1 1; }
.baseline { stroke: #d33; stroke-width: 0.25; }
.origin { fill: #d33; }
.label  { font-family: ui-monospace, Menlo, monospace; fill: #2a7ae2; }
.label2 { font-family: ui-monospace, Menlo, monospace; fill: #888; }
.rule   { fill: #e07b00; fill-opacity: .55; stroke: #a35a00; stroke-width: 0.25; }
.rulelabel { font-family: ui-monospace, Menlo, monospace; fill: #a35a00; }
.node-Fraction    { fill: none; stroke: #7b2ff7; stroke-width: 0.5; }
.node-Radical     { fill: none; stroke: #069; stroke-width: 0.5; }
.node-Superscript,.node-Subscript,.node-SubSup { fill: none; stroke: #0a0; stroke-width: 0.4; }
.node-Delimited   { fill: none; stroke: #c60; stroke-width: 0.5; }
.node-UnderOver   { fill: none; stroke: #099; stroke-width: 0.5; }
.node-Matrix      { fill: none; stroke: #a06; stroke-width: 0.6; }
.node-MatrixRow   { fill: none; stroke: #a06; stroke-width: 0.3; stroke-dasharray: 2 1; }
.node-MatrixCell  { fill: none; stroke: #d8a; stroke-width: 0.25; stroke-dasharray: 1 1; }
.node-Accent      { fill: none; stroke: #48c; stroke-width: 0.4; }
.node-label { font-family: ui-monospace, Menlo, monospace; fill: #7b2ff7; }
.link   { stroke: #7b2ff7; stroke-width: 0.25; stroke-dasharray: 2 1; fill: none; }
.region { fill: none; stroke: #333; stroke-width: 0.6; stroke-dasharray: 4 2; }
"""

_STRUCTURAL = (Fraction, Radical, Superscript, Subscript, SubSup, Delimited,
               UnderOver, Matrix, MatrixRow, MatrixCell, Accent)


@dataclass
class SvgOptions:
    scale: float = 3.0
    margin: float = 8.0
    show_glyphs: bool = True
    show_boxes: bool = True
    show_baselines: bool = True
    show_labels: bool = True
    show_rules: bool = True
    show_structure: bool = True
    show_links: bool = True
    label_size: float = 2.0


class SvgRenderer:
    """Turns a page extract (and optionally a parse tree) into an SVG document."""

    def __init__(self, extract: PageExtract, region: Optional[BBox] = None,
                 tree: Optional[MathNode] = None, opts: Optional[SvgOptions] = None):
        self.extract = extract
        self.tree = tree
        self.opts = opts or SvgOptions()
        box = region or extract.bbox or BBox(0, 0, extract.width, extract.height)
        self.region = box.expand(self.opts.margin)

    # -- coordinates ---------------------------------------------------------------
    def _x(self, x: float) -> float:
        return (x - self.region.x0) * self.opts.scale

    def _y(self, y: float) -> float:
        return (self.region.y1 - y) * self.opts.scale

    def _s(self, v: float) -> float:
        return v * self.opts.scale

    # -- pieces ---------------------------------------------------------------------
    def _rect(self, b: BBox, cls: str, extra: str = "") -> str:
        return (f'<rect class="{cls}" x="{self._x(b.x0):.2f}" y="{self._y(b.y1):.2f}" '
                f'width="{self._s(b.width):.2f}" height="{self._s(b.height):.2f}" '
                f'{extra}/>')

    def _text(self, x: float, y: float, s: str, cls: str, size: float,
              anchor: str = "start") -> str:
        return (f'<text class="{cls}" x="{self._x(x):.2f}" y="{self._y(y):.2f}" '
                f'font-size="{self._s(size):.2f}" text-anchor="{anchor}">'
                f'{html.escape(s)}</text>')

    def _glyph_layer(self) -> Iterable[str]:
        for g in self.extract.glyphs:
            ch = g.unicode or "□"
            yield self._text(g.x, g.y, ch, "glyph", g.size)

    def _box_layer(self) -> Iterable[str]:
        for g in self.extract.glyphs:
            yield self._rect(g.bbox, "box")
            if g.ink_bbox:
                yield self._rect(g.ink_bbox, "ink")

    def _baseline_layer(self) -> Iterable[str]:
        for g in self.extract.glyphs:
            yield (f'<line class="baseline" x1="{self._x(g.x):.2f}" '
                   f'y1="{self._y(g.y):.2f}" x2="{self._x(g.bbox.x1):.2f}" '
                   f'y2="{self._y(g.y):.2f}"/>')
            yield (f'<circle class="origin" cx="{self._x(g.x):.2f}" '
                   f'cy="{self._y(g.y):.2f}" r="{self._s(0.3):.2f}"/>')

    def _label_layer(self) -> Iterable[str]:
        for g in self.extract.glyphs:
            yield self._text(g.bbox.x0, g.bbox.y1 + 0.6, f"#{g.id}", "label",
                             self.opts.label_size)
            yield self._text(g.bbox.x0, g.bbox.y0 - 2.2,
                             f"{g.font.base_name}/{g.size:.3g}", "label2",
                             self.opts.label_size * 0.85)

    def _rule_layer(self) -> Iterable[str]:
        for r in self.extract.rules:
            yield self._rect(r.bbox, "rule")
            yield self._text(r.bbox.x1 + 0.5, r.bbox.cy, f"R{r.id} {r.thickness:.3f}pt",
                             "rulelabel", self.opts.label_size)

    def _structure_layer(self) -> Iterable[str]:
        if self.tree is None:
            return
        for node in self.tree.walk():
            if not isinstance(node, _STRUCTURAL) or node.bbox is None:
                continue
            cls = f"node-{type(node).__name__}"
            pad = 0.4 + 0.25 * _depth_of(self.tree, node)
            yield self._rect(node.bbox.expand(pad), cls)
            yield self._text(node.bbox.x0, node.bbox.y1 + pad + 0.4,
                             f"{type(node).__name__} #{node.node_id} "
                             f"({node.prov.confidence:.3f})",
                             "node-label", self.opts.label_size * 0.9)

    def _link_layer(self) -> Iterable[str]:
        if self.tree is None:
            return
        for node in self.tree.walk():
            if node.bbox is None:
                continue
            for child in node.children:
                if child.bbox is None:
                    continue
                yield (f'<path class="link" d="M {self._x(node.bbox.cx):.2f} '
                       f'{self._y(node.bbox.cy):.2f} L {self._x(child.bbox.cx):.2f} '
                       f'{self._y(child.bbox.cy):.2f}"/>')

    # -- assembly --------------------------------------------------------------------
    def to_svg(self) -> str:
        w = self._s(self.region.width)
        h = self._s(self.region.height)
        layers: list[tuple[str, bool, Iterable[str]]] = [
            ("rules", self.opts.show_rules, self._rule_layer()),
            ("boxes", self.opts.show_boxes, self._box_layer()),
            ("baselines", self.opts.show_baselines, self._baseline_layer()),
            ("glyphs", self.opts.show_glyphs, self._glyph_layer()),
            ("labels", self.opts.show_labels, self._label_layer()),
            ("structure", self.opts.show_structure, self._structure_layer()),
            ("links", self.opts.show_links, self._link_layer()),
        ]
        parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.0f}" height="{h:.0f}" '
            f'viewBox="0 0 {w:.2f} {h:.2f}">',
            f"<style>{_CSS}</style>",
            f'<rect class="bg" x="0" y="0" width="{w:.2f}" height="{h:.2f}"/>',
        ]
        for name, enabled, items in layers:
            body = "\n".join(items) if enabled else ""
            parts.append(f'<g id="layer-{name}" class="layer">{body}</g>')
        parts.append("</svg>")
        return "\n".join(parts)

    def to_html(self, title: str = "pdfmath debug") -> str:
        """The same SVG with checkboxes that switch the layers on and off."""
        names = ["rules", "boxes", "baselines", "glyphs", "labels", "structure", "links"]
        boxes = "".join(
            f'<label><input type="checkbox" checked data-layer="{n}"> {n}</label> '
            for n in names)
        return f"""<!doctype html>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
 body {{ font: 13px ui-monospace, Menlo, monospace; margin: 1rem; background:#fafafa; }}
 #controls {{ margin-bottom: .75rem; }}
 label {{ margin-right: .75rem; }}
 svg {{ border: 1px solid #ddd; background: #fff; }}
</style>
<div id="controls">{boxes}</div>
{self.to_svg()}
<script>
document.querySelectorAll('#controls input').forEach(cb => {{
  cb.addEventListener('change', () => {{
    const g = document.getElementById('layer-' + cb.dataset.layer);
    if (g) g.style.display = cb.checked ? '' : 'none';
  }});
}});
</script>
"""


def _depth_of(root: MathNode, target: MathNode, depth: int = 0) -> int:
    if root is target:
        return depth
    for c in root.children:
        d = _depth_of(c, target, depth + 1)
        if d >= 0:
            return d
    return -1


def render(extract: PageExtract, region: Optional[BBox] = None,
           tree: Optional[MathNode] = None, opts: Optional[SvgOptions] = None,
           as_html: bool = False, title: str = "pdfmath debug") -> str:
    r = SvgRenderer(extract, region, tree, opts)
    return r.to_html(title) if as_html else r.to_svg()
