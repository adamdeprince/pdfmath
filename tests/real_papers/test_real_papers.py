"""Tests against real PDFs, if any have been provided.

See README.md in this directory.  The suite skips cleanly when the directory is empty,
which is the normal state of a fresh checkout.
"""

from __future__ import annotations

import glob
import json
import os
import re

import pytest

HERE = os.path.dirname(__file__)
MANIFESTS = sorted(glob.glob(os.path.join(HERE, "*.json")))


def _pdf_for(manifest: str) -> str:
    return os.path.splitext(manifest)[0] + ".pdf"


def _normalise(xml: str) -> str:
    """Ignore whitespace and provenance attributes when comparing MathML."""
    xml = re.sub(r'\s(id|data-[a-z-]+)="[^"]*"', "", xml)
    return re.sub(r">\s+<", "><", xml).strip()


@pytest.mark.skipif(not MANIFESTS, reason="no real-paper fixtures present")
@pytest.mark.parametrize("manifest", MANIFESTS,
                         ids=[os.path.basename(m) for m in MANIFESTS])
def test_real_paper(manifest):
    from pdfmath.extraction.pdfminer_backend import extract_page
    from pdfmath.geometry.bbox import BBox
    from pdfmath.mathml.serializer import to_mathml
    from pdfmath.parse.driver import parse_page

    with open(manifest) as fh:
        spec = json.load(fh)
    pdf = _pdf_for(manifest)
    assert os.path.exists(pdf), f"{manifest} has no matching {os.path.basename(pdf)}"

    for entry in spec["equations"]:
        page = extract_page(pdf, entry["page"])
        region = BBox(*entry["bbox"]) if entry.get("bbox") else None
        tree, ctx = parse_page(page, region)

        src = page.in_region(region) if region else page
        in_tree = {g for node in tree.walk() for g in node.prov.glyph_ids}
        missing = {g.id for g in src.glyphs} - in_tree
        assert not missing, (f"page {entry['page']}: glyphs {sorted(missing)} did not "
                             f"reach the tree")

        if entry.get("mathml"):
            assert _normalise(to_mathml(tree)) == _normalise(entry["mathml"]), (
                f"page {entry['page']}: {entry.get('note', '')}")
        else:
            worst = min(n.prov.confidence for n in tree.walk())
            assert worst > 0.5, f"page {entry['page']}: confidence {worst:.3f}"
