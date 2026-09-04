# Testing the hypothesis against MathSeer

## The claim being tested

> If a PDF is known to be produced by TeX with recognisable TeX fonts, a parser that
> explicitly inverts TeX's layout rules may outperform a generic mathematical
> structure-recognition system.

Narrow on purpose. It is not a claim that this system is better at formula recognition.
MathSeer's parser (QD-GGA) works on *images*, including handwriting and scans, where none
of the evidence this project relies on exists. On that ground it wins by default, because
we cannot compete at all. The question is only whether, on the ground where TeX evidence
*is* available, using it beats not using it.

## What has been established

**The evidence exists and is exact.** Every Appendix G prediction agrees with stock
pdfTeX output to under a thousandth of a point (`tests/synthetic/test_appendix_g.py`).
That is the precondition for the hypothesis, and it holds without qualification.

**Using it gives exact reconstruction on the constrained corpus**: 100% exact expressions
on the 17-case first milestone and the 58-case extended set, and 94.7%–98.0% on randomly
generated expressions from three seeds the parser was never tuned against, with 100%
glyph recovery throughout (`pdfmath benchmark`).  Held-out seeds are reported rather than
the development seed, because only the former is evidence.

**It survives contact with real 1991–2002 papers.** On 30 pages of three arXiv preprints
(`math/9201254` 1992, `hep-th/9108028` 1991, `math/0211159` 2002 — Computer Modern, AMS
fonts, no useful ToUnicode maps), 210 displayed equations were detected and decompiled
with **100% glyph recovery** (10776/10776) and a median structural confidence of 0.916.
99.93% of glyphs were identified from the *TeX font encoding* rather than from the PDF's
Unicode metadata, which is the specific advantage the hypothesis rests on: those documents
largely do not carry a usable ToUnicode map, and a system that trusted one would be
guessing.

**What has not been established** is the comparison itself. QD-GGA has not been run here,
so no relative number is claimed, and none should be inferred from the figures above.

## Why the comparison was not run

Running MathSeer end-to-end needs, in order: a JVM and Maven for SymbolScraper (this
machine has no Java runtime), ScanSSD for formula detection (PyTorch plus trained
weights), and QD-GGA for structure recognition (PyTorch plus trained weights, and a
rasterisation step for the visual features). Standing that up is a substantial exercise
and its results would depend on which checkpoints were used.

Rather than assert an untested comparison, the repository ships what makes the comparison
*runnable by a reader*, which is the part that was missing.

## Protocol

Both systems are scored with **LgEval**, DPRL's own evaluation library
(<https://gitlab.com/dprl/lgeval>), which is what CROHME and the MathSeer papers use, so
neither system is being judged by a metric of our choosing.

1. **Generate the corpus.** The expressions and their ground truth come from the same
   objects, so ground truth is independent of both systems:

   ```bash
   pdfmath benchmark --suite random --n 2000 --seed 1 \
                     --lg-dir /tmp/lg --workdir /tmp/corpus
   ```

   This writes `/tmp/corpus/*.pdf` (one expression per page) and, under
   `/tmp/lg/random(...)/`, `ground_truth/*.lg` and `output/*.lg` — object-relationship
   label graphs whose primitive ids are the glyph ids `pdfmath dump` reports.

2. **Run MathSeer on the same PDFs.** SymbolScraper for characters, then QD-GGA for
   structure, emitting `.lg` per page. Formula detection can be skipped: each page holds
   exactly one formula, which removes ScanSSD as a confound and tests the *parsers*
   rather than the pipelines.

3. **Score both** against the same ground truth:

   ```bash
   evaluate /tmp/lg/random.../output /tmp/lg/random.../ground_truth
   evaluate /path/to/qdgga_output    /tmp/lg/random.../ground_truth
   ```

4. **Report** structure rate, detection rate and expression rate for each, broken down by
   construct — the corpus records which constructs each expression uses, so the breakdown
   in `pdfmath benchmark` output can be reproduced per system.

## What a fair reading would have to account for

* **The corpus is the hypothesis's home ground**, and saying so is part of the result.
  Every expression is stock pdfTeX with Computer Modern. A system that inverts pdfTeX's
  layout should do well there; the interesting question is *how much* better, and whether
  the margin survives the second corpus below.
* **A second corpus is needed to bound the claim**: the same expressions typeset with
  XeTeX or LuaTeX in an OpenType math font. This project's font layer does not yet handle
  those, so it should degrade toward the generic case while QD-GGA is unaffected. That
  measurement is what would turn "may outperform" into a statement with a stated scope.
* **The two systems do not fail the same way.** Ours reports a residual in points and an
  `Unknown` node; a graph parser reports a class probability. Comparing only aggregate
  rates hides that, and the confidence-stratified breakdown (`pdfmath survey --floor`) is
  the more useful comparison for anyone deciding which to deploy.
* **Glyph recovery is not a fair comparison at all.** SymbolScraper's ink boxes are better
  than ours for fonts we do not recognise; ours are exact for fonts we do. The
  `symbolscraper_adapter` exists so that the two can be swapped and the *parser* compared
  on identical input, which is the only version of that comparison worth running.
