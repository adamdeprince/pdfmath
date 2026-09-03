"""Ingest SymbolScraper output into our extraction model.

Our own extractor is the default, for the reasons set out in docs/prior-art.md: the
serialised form below drops the character code, the text matrix and the font resource
name, which are the three fields that carry the TeX signal.  This adapter exists so that
SymbolScraper *can* be used -- to cross-check our glyph boxes against its outline-derived
ones, or on documents whose fonts we do not recognise, where its ink boxes are better than
anything a TFM lookup can give us.

Both serialisations are accepted:

* v0.1 XML  -- ``Pages > Page > Line > Word > Char`` with ``BBOX="x y w h"``
* v0.2 XML/JSON -- the same, plus ``fontName``, ``fontSize`` and sibling ``Graphic``
  elements carrying ``points`` and a ``Path``

Coordinates are PDF big points and are converted to TeX points on the way in.
"""

from __future__ import annotations

import json
from typing import Any, Optional
from xml.etree import ElementTree

from ..geometry.bbox import BBox
from ..units import bp_to_pt
from .model import Glyph, PageExtract, Rule


def _bbox(attr: str) -> Optional[BBox]:
    try:
        x, y, w, h = (float(v) for v in attr.split())
    except (ValueError, AttributeError):
        return None
    return BBox(bp_to_pt(x), bp_to_pt(y), bp_to_pt(x + w), bp_to_pt(y + h))


def from_xml(text: str, page_number: int = 1) -> PageExtract:
    """Parse SymbolScraper XML into a :class:`PageExtract`."""
    root = ElementTree.fromstring(text)
    pages = root.findall(".//Page") or [root]
    page_el = None
    for p in pages:
        if int(p.get("id", "0")) + 1 == page_number or len(pages) == 1:
            page_el = p
            break
    if page_el is None:
        page_el = pages[0]

    glyphs: list[Glyph] = []
    rules: list[Rule] = []
    warnings = ["glyph geometry from SymbolScraper: ink boxes, no character codes, "
                "no text matrix, no baselines"]
    for i, ch in enumerate(page_el.findall(".//Char")):
        box = _bbox(ch.get("BBOX", ""))
        if box is None:
            continue
        text_value = (ch.text or ch.get("value") or "").strip()
        size = float(ch.get("fontSize", "0") or 0)
        font = ch.get("fontName") or "unknown"
        g = Glyph(
            id=int(ch.get("id", i)), page=page_number,
            char_code=-1,                       # SymbolScraper does not serialise it
            x=box.x0, y=box.y0,                 # no baseline available; box bottom stands in
            size=bp_to_pt(size) if size else 10.0,
            font_name=font, unicode_from_pdf=text_value or None,
            ink_bbox=box,
        )
        glyphs.append(g)

    for j, gr in enumerate(page_el.findall(".//Graphic")):
        box = _bbox(gr.get("BBOX", ""))
        if box is None:
            continue
        rules.append(Rule(id=j, page=page_number, x0=box.x0, y0=box.y0,
                          x1=box.x1, y1=box.y1,
                          thickness=min(box.width, box.height),
                          kind="fill", source="SymbolScraper Graphic"))

    return PageExtract(page=page_number, width=0.0, height=0.0,
                       glyphs=glyphs, rules=rules, warnings=warnings)


def from_json(text: str, page_number: int = 1) -> PageExtract:
    """Parse SymbolScraper v0.2 JSON into a :class:`PageExtract`."""
    data: Any = json.loads(text)
    pages = data.get("Pages") or data.get("pages") or [data]
    page = pages[min(page_number - 1, len(pages) - 1)]

    glyphs: list[Glyph] = []
    rules: list[Rule] = []
    counter = 0

    def walk(node: Any) -> None:
        nonlocal counter
        if isinstance(node, dict):
            if "BBOX" in node and ("value" in node or "charID" in node):
                box = _bbox(node["BBOX"] if isinstance(node["BBOX"], str)
                            else " ".join(str(v) for v in node["BBOX"]))
                if box is not None:
                    size = float(node.get("fontSize", 0) or 0)
                    glyphs.append(Glyph(
                        id=int(node.get("charID", counter)), page=page_number,
                        char_code=-1, x=box.x0, y=box.y0,
                        size=bp_to_pt(size) if size else 10.0,
                        font_name=node.get("fontName", "unknown"),
                        unicode_from_pdf=node.get("value"), ink_bbox=box))
                    counter += 1
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(page)
    return PageExtract(page=page_number, width=0.0, height=0.0,
                       glyphs=glyphs, rules=rules,
                       warnings=["glyph geometry from SymbolScraper JSON"])
