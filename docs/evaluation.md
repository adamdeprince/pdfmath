# Evaluation

How well pdfmath works, measured three ways: against a synthetic corpus whose
ground truth is generated rather than judged, against real papers' own LaTeX
source through LaTeXML, and by recompiling what was recovered and comparing the
pages glyph by glyph.

Run any of it yourself with `pdfmath benchmark`, `pdfmath arxiv` and
`pdfmath roundtrip` — see the tutorial in the README.

## Does it work?

Yes, to a measurable degree. For `\frac{x_i^2}{\sqrt{y}}` compiled by stock pdfTeX,
every prediction Appendix G makes agrees with the PDF to under a thousandth of a point:

| quantity | predicted | measured | residual |
|---|---|---|---|
| superscript shift (rule 18c, text style) | 3.62891 pt | 3.62856 pt | −0.00035 |
| subscript shift (rule 18f clearance) | 2.60295 pt | 2.60272 pt | +0.00023 |
| numerator baseline (rule 15, `num1`) | 6.76508 pt | 6.76493 pt | −0.00015 |
| denominator baseline (`denom1`) | 6.85951 pt | 6.85997 pt | +0.00046 |
| radical clearance (rule 11) | 1.92455 pt | 1.92530 pt | +0.00075 |

The residuals are pdfTeX's own three-decimal coordinate rounding. There is nothing left
to fit.

On synthetic corpora, compiled with pdfTeX and checked against ground truth generated
from the same source objects — never from the PDF:

```
                          milestone   extended   random, held-out seeds
glyph recovery              100.000%   100.000%   100.000%
structural edges            100.000%   100.000%    94.3% - 98.9%
node accuracy               100.000%   100.000%    98.0% - 99.6%
exact expressions           100.000%   100.000%    95.7% - 99.0%
```

The random figures are from three seeds the parser was never tuned against (7, 11, 23),
n=300 each. `pdfmath benchmark --suite all --seed N` reproduces any of them.

And on real documents it holds up. Thirty pages of three arXiv preprints — papers from
1991, 1992 and 2002, though the PDFs arXiv serves for them were rendered through dvips and
Ghostscript in 2018 and 2024. Computer Modern and AMS fonts, essentially no usable
ToUnicode maps:

```
210 displayed equations detected and decompiled
100.000%  glyph recovery (10776/10776); no glyph silently dropped
  0.916   median structural confidence
     22   Unknown nodes -- kept, with their geometry, rather than guessed at
 99.93%   of glyphs identified from the TeX font encoding, not from PDF Unicode metadata
```

That last line is the one that matters. Those documents mostly do not carry the metadata a
Unicode-first extractor needs; knowing that `CMMI10 + 0x78` is `x` is what makes them
readable at all. `pdfmath survey paper.pdf` produces the report.

## Real papers, real ground truth

arXiv publishes the LaTeX *source* of papers whose PDFs we can also read. LaTeXML reads
the source, we read the page pdfTeX makes from it, and neither is derived from the other
— so those papers are labelled examples that we did not write. `pdfmath arxiv` re-sets
each display on its own page using the paper's own preamble (which takes equation
detection out of the measurement), decompiles it, and compares.

```
math/0211159  Perelman, "The entropy formula for the Ricci flow", 2002
                41 / 43 displays exact  (95.3%)
math/0303109  Perelman, "Finite extinction time...", 2003
                 4 /  6                 (66.7%)
math/0405568
                 3 /  6                 (50.0%)
                --------------------------------
      total    48 / 55 = 87.3% exact,  100.000% glyph recovery
```

The same machinery cross-checks the synthetic corpus: LaTeXML independently agrees with
17 of 17 first-milestone ground-truth trees and 56 of 58 extended ones, which closes the
hole that our expected answers and our LaTeX come from the same objects.

## The stronger check: recompile it

A decompiler is validated by recompiling. `pdfmath roundtrip` serialises the recovered
tree back to LaTeX, runs pdfTeX on it, and compares the glyphs with the ones it started
from. If every glyph lands in the same place relative to its neighbours, the structure we
recovered is one TeX compiles to the original page. No ground truth, no second system —
so unlike `benchmark` it works on real documents.

```
                    milestone   extended   random (held out)   real papers
recompiles exactly   17 / 17    58 / 58      94% - 95%           3.9%
```

That number is not comparable with the 87.3% above, and an earlier draft of this file
wrongly put the two side by side. They differ in *what they measure*, not only in how the
equation regions were found:

* 87.3% is **structural agreement** — the recovered tree matches LaTeXML's reading of the
  author's source.
* 3.9% is **glyph-identical recompilation** — a far stricter test that also holds the
  LaTeX serializer and the spacing model to account.

Holding the paper (`math/0211159`) and the metric fixed, and varying only where the
equation regions come from:

| regions from | recompiles identically |
|---|---|
| the paper's own source, one display per page | 28.3% |
| our detector, on the PDF arXiv serves | 10.4% |

So detection costs about 18 points, not 83. The dominant gap is between the two metrics:
95.3% of these displays match LaTeXML structurally, and 28.3% recompile identically. The
difference is almost entirely `shifted` verdicts — right glyphs, right structure, positions
off by a point or two — which is the LaTeX serializer's spacing fidelity rather than the
parse.

Chasing one of those found a real TeX detail: `clean_box` hpacks a script *before* it
drops the italic kern (tex.web §720–721), so a subscript's box keeps the italic correction
of its last character even though the kern node is gone. Modelling that took the
source-region figure from 17.4% to 28.3%. More of the same is likely left.

A caveat on the second row: the PDFs arXiv serves for these papers were produced by
Ghostscript in 2018 and 2024, not by pdfTeX in 1991. They are genuine TeX output rendered
through dvips, so the extraction results hold, but comparing them against a TeX Live 2026
rebuild introduces a toolchain difference that the first row does not have.

