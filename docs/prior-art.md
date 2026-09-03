# Prior-art audit

Status: complete for the systems named in the project brief.
Date of audit: 2026-09-03. Everything below was checked against source or full text,
not against abstracts.

The purpose of this document is to decide, per subsystem, **reuse / adapt / build**, and
to record the concrete evidence behind each decision so it can be revisited.

---

## 1. SymbolScraper (RIT / DPRL)

Two live versions exist. They are not the same program.

| | v0.1 | v0.2 ("server") |
|---|---|---|
| Location | https://github.com/zanibbi/SymbolScraper | https://gitlab.com/dprl/symbolscraper-server |
| License | Apache-2.0 (`LICENSE`, `COPYRIGHT`) | Apache-2.0 (`LICENSE.TXT`) |
| Copyright | Joshi, Mali, Kukkadapu, Mahdavi, Diehl, Zanibbi (2018–19) | rewritten by M. Langsenkamp |
| Language | Java 8 | Java 8+ |
| Build | Maven + Perl (`make`) | Maven + Javalin + optional Docker |
| PDF library | Apache PDFBox 2.0.7 + FontBox | Apache PDFBox |
| Cite | — | Shah, Dey & Zanibbi, ICDAR 2021 (MathSeer pipeline) |

### The component and what it actually does

The core is the package `TrueBox`. Its idea — and this is the part worth stealing — is to
**intercept the PDFBox rendering pipeline** rather than read the content stream naively:

* `BoundingBox.java` (v0.1) / `CharacterExtractor.java` (v0.2) extend `PDFTextStripper`
  and override `writeString` / `processTextPosition` to see every `TextPosition`.
* For each character it fetches the **glyph outline** from the embedded font program and
  computes the bounding box of the actual ink, not of the font's nominal ascent/descent
  box. Hence "TrueBox". Font-type dispatch lives in `FontUtils.getAdjustedGlyphPath`:
  * `PDType1Font` → `Type1Font.getPath(font.codeToName(code))` (FontBox parses the
    embedded `.pfb` charstrings)
  * `PDType1CFont` → CFF charstrings
  * `PDTrueTypeFont` → `getPath(code)`
  * `PDType0Font` → CID → GID → path
  * Type 3 → falls back to masking with Times-Roman (i.e. it gives up)
* `BarDetection.java` (v0.1) / `GraphicsItemExtractor.java` (v0.2) extend
  `PDFGraphicsStreamEngine` and capture `appendRectangle` / `strokePath` / `fillPath`,
  so **rules and paths are extracted**, separately from characters.
* v0.2 adds `MathPostProcessor` / `SplicePostProcessor`, which merge a graphics item into
  a character when they intersect — this is exactly the radical-sign + overbar case.

### Answers to the specific audit questions

* **PDF library** — Apache PDFBox 2.x, plus FontBox for glyph outlines.
* **Font resolution** — via PDFBox's `PDFont` hierarchy; the embedded Type 1 program's
  *built-in* encoding is used when the PDF has no `/Encoding`, which is the normal pdfTeX
  case.
* **Character-code mapping** — internally it has the raw code
  (`TextPosition.getCharacterCodes()[0]`) and maps it to a glyph name with
  `codeToName(code)`, then to Unicode with `TextPosition.getUnicode()`.
* **Bounding boxes** — ink boxes from glyph outlines, as `BBOX="x y w h"` in PDF user
  space. This is genuinely better than pdfminer/PyMuPDF nominal boxes.
* **Type 1 TeX fonts** — handled well; this is its main test case.
* **ToUnicode** — it trusts `TextPosition.getUnicode()`, i.e. PDFBox's resolution order
  (ToUnicode CMap → encoding → glyph list). It has no TeX-specific override.
* **Intermediate representation** — XML (and JSON in v0.2):
  `Pages > Page > Line > Word > Char`, where in v0.1 a `Char` carries only `id`, `BBOX`
  and its text; v0.2 optionally adds `fontName`, `fontSize`, `fontWeight`, `italicAngle`,
  `RGB`, and sibling `Graphic` elements with `points` and a full `Path` element
  (lines / quadratic / cubic segments).
* **Rules / paths** — yes, as `Graphic` elements.
* **Equation regions** — **no.** Formula *detection* in the MathSeer pipeline is
  ScanSSD (a neural SSD over rendered page images); formula *structure recognition* is
  QD-GGA (a graph-attention parser). Neither lives in SymbolScraper.
* **Import as a library** — not from Python. It is a JVM program invoked as a jar, a
  Javalin HTTP service on port 7002, or a Docker container.
* **License obligations** — Apache-2.0: keep the notice, state changes. Compatible with
  our chosen license. No obstacle to adapting the *ideas*; verbatim code would require
  carrying the notice.

### The blocking problem: its output drops what a TeX decompiler needs

The `Char` record is the whole contract, and it does not serialise:

* the **raw PDF character code** (`120` for `x` in CMMI10) — only a resolved Unicode
  string,
* the **text matrix / glyph origin**, hence no **baseline**,
* the **PDF font resource name** (`/F35`) or the un-subsetted font name,
* the **font size in the PDF sense** distinct from a scaling factor.

For a generic recogniser that is fine — an ink box plus a Unicode label is what a visual
parser wants. For this project it is fatal, because the two strongest TeX signals are
exactly the ones discarded:

1. **The pair (font, code)** — `CMMI10 + 0x78` is a *stronger* identity than the Unicode
   `x`, and for `CMEX10 + 0x70` (a radical extension piece) Unicode is close to
   meaningless.
2. **The baseline**, which is what TeX's layout rules are expressed in. Appendix G talks
   about shift_up / shift_down of *baselines*, never about ink boxes.

There is a second, weaker problem: the `Line`/`Word` grouping is PDFBox `PDFTextStripper`
reading order, which actively damages math (in the shipped sample `math.xml`, `x` and its
superscript `n` are merged into one "Word", and the relationship is gone).

And a third, environmental: this machine has **no JVM** (`java -version` fails), so the
reference implementation cannot even be executed here without adding a Java + Maven
toolchain to a Python project's dependency set.

---

## 2. MathFIRE (RIT / DPRL)

* Location: https://gitlab.com/dprl/mathfire
* License: **AGPL-3.0**
* What it is: a **formula retrieval** system — an OpenSearch/Elasticsearch index over
  TangentCFT formula embeddings, with faiss for fast nearest-neighbour search.
* Its "math representation" code is not a layout library. `latex_mathml_conversion_utils.py`
  and `latexml_conversion_tool.py` are wrappers around **LaTeXML** and **pypandoc** that
  go LaTeX → MathML and MathML → LaTeX for *indexing*. The Symbol Layout Trees come from
  the separate `tangents` package and are a *search* representation: a tree whose edges
  are labelled with Tangent's baseline relations (`n` next, `a` above, `b` below,
  `o` over, `u` under, `w` within).

Consequences:

* **License**: AGPL-3.0 would propagate to anything that links it. That alone rules it
  out as a dependency of a permissively licensed library.
* **Direction is wrong**: it converts *LaTeX* to MathML with an external converter. We
  need to convert a *recovered layout tree* to MathML. There is no code for that.
* **The SLT is lossy for us**: relation-labelled edges cannot express "this `mfrac` came
  from rule #4 with numerator glyphs {17,18,19}". Provenance is a hard requirement here.

The SLT relation vocabulary is still worth borrowing as a *concept* — our tree keeps the
same distinctions (`above`/`below`/`within` are Fraction/Radical/Delimited; `sup`/`sub`
are the Tangent `a`/`b` on a nucleus) — but the datatype should be ours.

---

## 3. MaxTract (Baker, Sexton, Sorge — Birmingham)

Read in full:

* J. Baker, A. Sexton, V. Sorge, *Faithful mathematical formula recognition from PDF
  documents*, DAS 2010, doi:10.1145/1815330.1815393.
* J. Baker, A. Sexton, V. Sorge, *MaxTract: Converting PDF to LaTeX, MathML and Text*,
  CICM/AISC 2012, doi:10.1007/978-3-642-31374-5_29.
* J. Baker, *A linear grammar approach for the analysis of mathematical documents*,
  PhD thesis, University of Birmingham, 2012 —
  https://etheses.bham.ac.uk/id/eprint/3377/ (`Baker12PhD.pdf`, 141pp).

**Source availability**: the MaxTract web service and source are no longer published;
no open-source license is discoverable. Treat as *literature only*. Nothing is copied.

### The algorithm, as described in the thesis (ch. 6)

A **linear grammar** over a totally ordered set of symbols. A symbol is the 6-tuple
`⟨P, F, N, B, X₂, Y₂⟩` = point size, font name, symbol name, bounding box, and the
**basepoint** `(X₂, Y₂)` — i.e. Baker also insisted on the true baseline, not the ink
centre. The order is by `X₁` then `Y₁`. Parsing consumes the ordered set left to right
carrying a partial tree `B`, with fifteen rules; the ones that matter here:

| Rule | Trigger | Preconditions (paraphrased) |
|---|---|---|
| Leaf | leading symbol, nothing else applies | — |
| Linearise | tree `B` then next symbol, nothing else applies | — |
| Superscript | symbols near upper-right of `B` | `maxY₂(B) < minY₂(T₁)`, `avgP(B) > avgP(T₁)`, `maxY₁(B) < minY₁(T₁)`, `minX₁(B) < minX₁(T₁)`, `space(T₁) ≤ H`, `minX₁(T₁) − maxX₃(B) ≤ H` |
| Subscript | mirror of the above | |
| Super-subscript | both | |
| Fraction | **leading symbol is an `hline`** with material above and below, both inside the line's x-extent | `tX₁ < minX₁(T₁)`, `tX₃ > maxX₃(T₁)`, `tY₁ > maxY₁(T₁)`, and mirrored for `T₂` |
| Limits | a set with material above and below, centred on it | `minX₁(T₁) < avgX₂(T₂)`, `maxX₃(T₁) > avgX₂(T₂)`, … |
| Over / Under | material above / below, centred, smaller | includes `avgP(T₁) > avgP(T₂)` |
| Root | **leading symbol is a `radical`** | index left-and-above, body inside the radical's box |
| Multiline | vertical gap `> V` | |
| Case | leading symbol vertically bounds a multiline remainder | |
| Matrix element / row | horizontal gap `> H`, vertical gap `> V` | |

Output is a tree; separate "drivers" walk it to LaTeX and to MathML.

### What worked

* **Baselines beat centroids.** Over 250 sub/superscripts in the evaluation corpus, all
  correct, *including* cases where the author abused an accent command to fake a script.
  Baker is explicit that this beats statistical image-based methods (he compares against
  Aly/Uchida/Suzuki 2008) purely because the PDF hands you the true basepoint.
* **Limits** on `∑` / `∫`: "perfect results", again from baseline analysis alone.
* **Enclosures** (`√`): "perfect results", because the PDF gives the surd's extent
  directly instead of requiring it to be traced in an image.
* **Glyph names carry semantics for free**: `summationdisplay` vs `summationtext` vs
  `Sigma` distinguishes a large operator from a Greek letter with no dictionary.
  This is a TeX-specific fact and it generalises to our whole font-normalisation layer.

### Where it failed, and why

| Failure | Root cause |
|---|---|
| Matrices with no whitespace between rows became "bracketed expression with sub/superscripts" | thresholds `H`, `V` are global constants, not derived from the font |
| `À` recognised as superscript-acute, producing invalid LaTeX | the grammar has no atom-class model, so an accent that sits high-right is a script |
| Fences paired by naive left/right orientation; neutral fences (`|`) unhandled; unbalanced fences patched with `\left.`/`\right.` | no model of TeX's `\left`/`\right` delimiter *sizing*, which is the actual evidence |
| Matrix columns left-aligned rather than at true positions | grammar discards the spatial data it had |
| Interspersed text inside formulae not segmented | no atom-class / font-family model |

Note the shape of that table: **every one of Baker's structural failures is a place where
he used a tuned constant instead of a TeX quantity that was recoverable from the PDF.**
That is the gap this project is aimed at.

### What we have that he did not (2010 → 2026)

1. **The TFM files are on disk.** `kpsewhich cmr10.tfm` resolves. That gives exact
   width/height/depth/italic-correction per glyph *and* the 22 math parameters
   (`num1…denom2`, `sup1…sub2`, `sup_drop`, `sub_drop`, `axis_height`, `default_rule_thickness`,
   `big_op_spacing1…5`) that TeX itself used to place these boxes. Baker's `H` and `V`
   constants can be replaced by `σ`/`ξ` parameters.
2. **TeXbook Appendix G is a specification of the encoder.** Rules 15 (fractions),
   18a–18f (scripts), 11 (radicals), 13 (large operators) are closed-form. We can compute
   the *expected* shift for a candidate structure and score the residual, instead of
   thresholding.
3. **PDF units are big points; TeX units are printer's points.** `9.9626 bp = 10 pt`
   exactly (72.27/72). Converting once at the boundary makes every TFM number directly
   comparable to a measured position. Baker worked in raw PDF units throughout.
4. **Unlimited labelled ground truth.** pdfTeX is a deterministic compiler we can run.
   Baker hand-checked 128 expressions from two books; we can generate and check millions,
   with the *structure* known a priori rather than annotated after the fact.
5. Mature Python PDF tooling (`pdfminer.six`, `pikepdf`, `fontTools`) — Baker had to write
   a "bespoke PDF parser".

---

## 4. The experiment that settled the extraction decision

`\[ \frac{x_i^2}{\sqrt{y}} \]` compiled with stock pdfTeX 3.141592653-2.6-1.40.29,
`article`, 10pt. Uncompressed content stream, in full:

```
BT
/F35 9.9626 Tf 300.542 638.167 Td [(x)]TJ
/F31 6.9738 Tf 5.694 3.615 Td [(2)]TJ
/F34 6.9738 Tf 0 -6.208 Td [(i)]TJ
ET
q 1 0 0 1 298.852 633.918 cm []0 d 0 J 0.398 w 0 0 m 13.544 0 l S Q
BT /F38 9.9626 Tf 298.852 630.8 Td [(p)]TJ ET
q 1 0 0 1 307.154 631 cm []0 d 0 J 0.398 w 0 0 m 5.242 0 l S Q
BT /F35 9.9626 Tf 307.154 624.593 Td [(y)]TJ ET
```

with `/F35 = CMMI10`, `/F31 = CMR7`, `/F34 = CMMI7`, `/F38 = CMSY10`, all Type 1,
no `/Encoding` (so the embedded program's built-in encoding governs).

Five facts fall straight out, and they set the architecture:

1. **Rules are stroked lines, not filled rectangles.** `0 0 m 13.544 0 l S` with
   `0.398 w`. Anything that only looks at `re f` (as SymbolScraper v0.1's
   `appendRectangle` primarily does) will miss every pdfTeX fraction bar and radical
   overbar. `0.398 bp = 0.39906 pt ≈ 0.4 pt = cmex10's default_rule_thickness`.
2. **The radical overbar is a *separate* stroked line**, not part of the `√` glyph.
   The surd is `CMSY10 + 0x70`; the bar is a path. They must be re-associated.
3. **Font size encodes style**: `6.9738 / 9.9626 = 0.700` exactly — scriptstyle. And the
   *font changes* too (CMMI10 → CMMI7), which is an independent confirmation.
4. **`9.9626` is 10 TeX points in big points.** Work in pt, not bp.
5. **Everything is a baseline-relative `Td`.** `5.694 3.615 Td` is precisely the
   (italic-corrected horizontal, Rule-18c vertical) displacement of the superscript.
   This is the residual we want to invert.

`pdfminer.six` (MIT) was then checked against the same file with a `PDFLayoutAnalyzer`
subclass overriding `render_char` and `paint_path`. It yields, per glyph: the raw `cid`,
the font name, the font size, the **full text matrix**, the `/Widths` entry, and — for
paths — the segment list and the graphics-state line width. That is the complete set of
fields SymbolScraper's serialisation drops.

---

## 5. Decisions

```
PDF extraction:
    BUILD, on pdfminer.six (MIT), adopting SymbolScraper's technique.

    Reason: SymbolScraper's method (intercept the renderer; take characters and
    graphics through separate engines; re-associate them afterwards) is right and we
    copy it. Its *serialised IR* is not usable: it drops the character code, the text
    matrix and therefore the baseline, and the font resource name — the three fields
    that carry the TeX signal. It is also a JVM program (no JVM on this host) and
    would make a Python library depend on Maven or Docker.

    We keep the door open: pdfmath/extraction/symbolscraper_adapter.py ingests
    SymbolScraper v0.1/v0.2 XML and JSON into our Glyph/Rule model, so its ink boxes
    can be used as a cross-check or for non-TeX fonts where TFM data is absent.

Glyph metrics:
    BUILD a TFM reader, in preference to glyph-outline ink boxes.

    Reason: SymbolScraper's outline boxes are the best available answer when you do not
    know who typeset the document. For a TeX PDF we can do strictly better: the TFM is
    the metric TeX *actually used* to lay the page out, so width/height/depth/italic
    from cmmi10.tfm reproduce the encoder's own arithmetic exactly, with no outline
    parsing and no rounding. Outline boxes remain the fallback for unknown fonts.

equation detection:
    DEFER, and accept --page/--bbox meanwhile.

    Reason: SymbolScraper contains no detector. MathSeer's detector is ScanSSD, a neural
    SSD over page *images* with trained weights — the exact "rasterise and infer" path
    the brief excludes from the critical path. Displayed equations in TeX are cheaply
    findable geometrically (a math-font run, horizontally centred, vertically isolated),
    so our own detector goes in pdfmath/detection/ later. ScanSSD stays available as an
    optional adapter for hard cases.

tree representation:
    BUILD (pdfmath/tree/nodes.py).

    Reason: MathFIRE's SLT is AGPL, comes from the retrieval stack, and is a
    relation-labelled search tree with no place for provenance. Our hard requirement —
    every node carries the glyph and rule ids it was built from, plus the evidence that
    justified it — has no existing implementation to reuse. We borrow the *vocabulary*
    (above/below/within/sup/sub) and Baker's node set (leaf, lin, sup, sub, supsub,
    frac, root, limits, over, under, line, case, col, row).

MathML:
    BUILD (pdfmath/mathml/serializer.py).

    Reason: MathFIRE's converter is LaTeX→MathML via LaTeXML/pandoc, under AGPL, and
    solves a different problem. Our tree is already isomorphic to Presentation MathML;
    the serializer is ~200 lines and must emit provenance ids as attributes, which no
    off-the-shelf converter will do.

parser architecture:
    BUILD, using MaxTract's grammar as the reference design.

    Reason: source is unavailable and unlicensed, so nothing can be reused literally.
    The rule *set* is sound and we reimplement it independently, with one systematic
    change: every precondition Baker expressed with a tuned constant (H, V, "avgP(B) >
    avgP(T)") is re-expressed in TFM units and checked against the Appendix G rule that
    generated the layout. That is the project's actual hypothesis.
```

## 6. Licensing note

`pdfmath` is MIT. Dependencies: `pdfminer.six` (MIT), `pikepdf` (MPL-2.0, optional),
`fontTools` (MIT), `lxml` (BSD), `hypothesis` (MPL-2.0, test-only). **PyMuPDF is
deliberately not used** — it is AGPL-3.0 and would be viral for downstream users, even
though it is present in this machine's virtualenv.

TFM files read at runtime are the user's own TeX installation; Computer Modern is under
Knuth's permissive licence and the metrics we *ship* (as a small extracted table for
environments with no TeX) are facts about a typeface, plus we prefer live `kpsewhich`
lookup wherever a TeX installation exists.
