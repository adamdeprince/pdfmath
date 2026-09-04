# pdfmath

A decompiler for TeX mathematics.

```
old TeX-generated PDF
    ↓  positioned glyphs and rules
    ↓  inferred TeX boxes and relationships
    ↓  reconstructed math layout tree
Presentation MathML
```

Older mathematical papers are full of PDFs that show correct mathematics and record none
of it: no MathML, no tagging, often not even a usable ToUnicode map. The usual answer is
to rasterise the equation and ask a model to guess the LaTeX back. This project takes the
opposite view.

**A TeX-produced PDF is not a picture of an equation. It is the compiled output of a
deterministic layout program, and the program's rules are published.** *The TeXbook*'s
Appendix G says exactly where a superscript goes, how far a fraction bar sits above the
baseline, and how much clearance a radical leaves over its radicand — as closed-form
expressions in font parameters that are still sitting on disk in the TFM files. So we do
not recognise the equation from its appearance. We recover the structure implied by the
layout.

That is a decompiler, and it behaves like one: exact where the input is what it claims to
be, and explicit about it when it is not.

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
structural edges            100.000%   100.000%    92.7% - 97.7%
node accuracy               100.000%   100.000%    97.7% - 99.3%
exact expressions           100.000%   100.000%    94.0% - 97.7%
```

The random figures are from three seeds the parser was never tuned against (7, 11, 23),
n=300 each. `pdfmath benchmark --suite all --seed N` reproduces any of them.

And on real documents it holds up. Thirty pages of three arXiv preprints from 1991, 1992
and 2002 — Computer Modern and AMS fonts, essentially no usable ToUnicode maps:

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

## Quickstart

```bash
pip install -e ".[dev]"

pdfmath dump      paper.pdf --page 3                 # positioned glyphs and rules
pdfmath debug-svg paper.pdf --page 3 --html -o p3.html
pdfmath extract   paper.pdf --page 3 --mathml
pdfmath extract   paper.pdf --page 3 --bbox 120,480,400,520 --mathml
pdfmath explain   paper.pdf --page 3 --node 17
pdfmath benchmark --suite all --n 500
pdfmath fonts     CMEX10 --code 0x58
```

A TeX installation is needed for the TFM metrics and for the synthetic corpus; the
extraction and MathML paths work without one, with reduced precision.

## What it gives you

**Provenance on every node.** A reconstructed `mfrac` knows which rule object it came
from and which glyph ids are in its numerator.

**An explanation for every inference**, in the units of the rule that produced it:

```
$ pdfmath explain paper.pdf --page 1 --node 4
node 4  SubSup  [subsuperscript]  confidence 0.9990
  glyphs    [0, 1, 2]
  evidence:
    base_is_char                   True
    style                          TEXT
    superscript_shift_pt           3.62856
    expected_superscript_shift_pt  3.62891
    superscript_residual_pt        -0.00035
    font_ratio_superscript         0.70000
    subscript_shift_pt             2.60272
    expected_subscript_shift_pt    2.60295
    subscript_residual_pt          -0.00023
```

**Uncertainty preserved rather than resolved.** A glyph nobody can explain becomes an
`Unknown` carrying its original geometry. Nothing is silently dropped — there is a test
for that.

**Atom classes solved backwards from the spacing.** ``\mathbin{b}`` and ``\mathrel{b}``
print the same glyph, so the character says nothing -- but TeX's inter-atom glue does, and
it is an exact multiple of a font parameter we hold. Measuring the gaps either side of
``b`` recovers Bin, Rel and Punct *uniquely*; Ord/Open/Close and Op/Inner collapse,
because those pairs produce identical pages and no method could separate them. The table
is in `docs/architecture.md`; the experiment runs as a test.

**A debug view of exactly what the parser saw**: glyph boxes, baselines, extracted rules,
and the recovered tree, in one SVG with toggleable layers.

## How it differs from the neighbours

`docs/prior-art.md` is the audit: SymbolScraper, MathFIRE and MaxTract, read from source
and from the papers, with a reuse/adapt/build decision and its evidence for each
subsystem. In short:

* **SymbolScraper** (RIT/DPRL, Apache-2.0) has the right *technique* — intercept the
  renderer, take characters and graphics through separate engines — and we copy it. Its
  serialised output drops the character code, the text matrix and the font resource name,
  which are the three fields that carry the TeX signal, so the extractor is ours, on
  `pdfminer.six`. An adapter can ingest its XML/JSON for cross-checking.
* **MathFIRE** is a formula *retrieval* system under AGPL-3.0 whose MathML machinery is a
  LaTeXML wrapper going the other way. Not reusable here.
* **MaxTract** (Baker, Sexton & Sorge) attacked this exact problem in 2010 and is the
  design reference. Its source is not available under any open licence and none is used.
  Its linear grammar is reimplemented independently with one systematic change: every
  precondition Baker expressed as a tuned constant is re-expressed as a TeX quantity and
  checked against the Appendix G rule that produced the layout. Every structural failure
  he documented — matrices with tight rows, accents read as scripts, fences paired by
  orientation — is at a place where a constant stood in for a recoverable number.

## Status and scope

Supported and measured: pdfTeX output, Computer Modern and Latin Modern, AMS symbol
fonts, displayed equations, display and text style, fractions, scripts, radicals,
delimiters (including built-up cmex assemblies), large operators with limits, matrices,
accents, over/underlines, and the inter-atom spacing table.

Not yet: inline equations inside paragraphs, XeTeX/LuaTeX OpenType math, Type 3 fonts,
scanned pages (out of scope by design), `\overbrace`-style horizontal braces, and
alignment recovery in `align`/`eqnarray` beyond a table of rows. See
`docs/architecture.md` for the known limitations with reasons.

## Licence

MIT. Dependencies are MIT/BSD/MPL; PyMuPDF is deliberately avoided because it is
AGPL-3.0 and would be viral for downstream users.
