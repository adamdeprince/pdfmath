# Real-paper tests

These tests run against PDFs you supply; none are committed, because redistributing
other people's papers is not ours to do.

Drop born-digital, pdfTeX-produced PDFs into this directory alongside a `<name>.json`
manifest:

```json
{
  "source": "https://arxiv.org/abs/...",
  "note": "1997 preprint, Computer Modern, no ToUnicode maps",
  "equations": [
    {"page": 3, "bbox": [120.0, 480.0, 400.0, 520.0],
     "mathml": "<math>...</math>",
     "note": "displayed equation (2.4)"}
  ]
}
```

`bbox` is in TeX points from the page's bottom-left -- the units `pdfmath dump` reports.
`mathml` is optional; without it the test only checks that every glyph reaches the tree
and that no decision falls below the confidence floor, which is the useful check when you
are triaging a new document.

Workflow for adding support for a new document:

1. `pdfmath dump paper.pdf --page 3` to see what was extracted.
2. `pdfmath debug-svg paper.pdf --page 3 --html -o /tmp/p3.html` and open it.
3. `pdfmath extract paper.pdf --page 3 --bbox ... --mathml`
4. `pdfmath explain paper.pdf --page 3 --bbox ... --max-confidence 0.99` to see which
   inferences the parser was unsure about.
5. Reproduce the failure as a *synthetic* case in `tests/regression/test_regressions.py`
   and fix the underlying rule. Do not special-case the document.
