# pdfmath

A decompiler for TeX mathematics. It reads a born-digital PDF and gives you back the
equations — as MathML, speech, AsciiMath, LaTeX, Word's OMML, or WordPerfect 5.1.

```
old TeX-generated PDF
    ↓  positioned glyphs and rules
    ↓  inferred TeX boxes and relationships
    ↓  reconstructed math layout tree
MathML · speech · AsciiMath · LaTeX · OMML · WP5.1
```

Older mathematical papers are full of PDFs that show correct mathematics and record none
of it: no MathML, no tagging, often not even a usable ToUnicode map. The usual answer is
to rasterise the equation and ask a model to guess the LaTeX back. This project takes the
opposite view: **a TeX-produced PDF is not a picture of an equation, it is the compiled
output of a deterministic layout program, and the program's rules are published.** So we
do not recognise the equation from its appearance — we recover the structure implied by
the layout, and we can say in points how well it fits.

This README is a tutorial. For how it works inside, see [docs/architecture.md]; for how
well it works, [docs/evaluation.md].

---

## Install

**Required:** Python 3.10 or newer. That is all you need to decompile a PDF.

```bash
git clone <this repo> && cd math
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pdfmath --help
```

**Optional, each unlocking one thing:**

| You want | Install | Needed for |
|---|---|---|
| exact font metrics, the sample document | a TeX distribution (MacTeX, TeX Live) | TFM metrics, `benchmark`, `roundtrip` |
| speech | Node, then `cd tools/sre && npm install` | `pdfmath speak` |
| the serialiser oracle tests | `pip install -e ".[oracles]"` | AsciiMath and OMML round-trip tests |
| scoring against a paper's own source | `brew install latexml` | `pdfmath arxiv` |

Without TeX, extraction and every output format still work — the metrics come from the
PDF's own `/Widths` instead of the TFM files, so the residuals stop being meaningful but
the structure is still recovered.

Check the install:

```bash
python -m pytest tests/unit -q          # fast, no TeX needed
python -m pytest -q                     # everything, needs TeX
```

---

## Tutorial

### 1. Build the sample

The repository ships a small document to work on. Build it once:

```bash
pdflatex -output-directory=examples examples/sample.tex
```

It has three displayed equations and one inline formula. If you would rather use your
own paper, any born-digital PDF from pdfTeX will do — just substitute it below.

### 2. Decompile it

```bash
$ pdfmath extract examples/sample.pdf --asciimath
E = (x_i^2)/(sqrt(y))
sum_(k = 1)^n (1)/(k^2) = (pi^2)/(6) - epsilon_n.
A = ((a,b),(c,d)), quad det A = a d - b c.
sqrt(a^2 + b^2)
```

No page number, no coordinates. Three of those are displayed equations, found by their
shape; the fourth is inside a sentence, found by a different method entirely — see below.
Pass `--no-inline` for displays only.

Ask for MathML instead and you get the real target format:

```bash
$ pdfmath extract examples/sample.pdf --bbox 286,612,326,641 --mathml
<math display="block" xmlns="http://www.w3.org/1998/Math/MathML">
  <mrow>
    <mi>E</mi>
    <mo>=</mo>
    <mfrac>
      <msubsup>
        <mi>x</mi>
        <mi>i</mi>
        <mn>2</mn>
      </msubsup>
      <msqrt><mi>y</mi></msqrt>
    </mfrac>
  </mrow>
</math>
```

### 3. Read it aloud

```bash
$ pdfmath speak examples/sample.pdf
E equals the fraction with numerator x sub i squared and denominator the square root of y
the sum from k equals 1 to n of the fraction with numerator 1 and denominator k squared equals the fraction with numerator pi squared and denominator 6 minus epsilon sub n period
A equals the 2 by 2 matrix Row 1: a b Row 2: c d comma determinant A equals a d minus b c period
the square root of a squared plus b squared
```

The last line is the formula from inside the sentence. That is ClearSpeak, which reads the way a person would say it. MathSpeak is unambiguous
and reversible instead — what you want when checking someone else's algebra:

```bash
$ pdfmath speak examples/sample.pdf --rules mathspeak --verbosity brief --bbox 286,612,326,641
upper E equals StartFrac x Sub i Sup 2 Base Over StartRoot y EndRoot EndFrac
```

`--ssml` emits SSML instead of plain text, so a synthesiser pauses in the right places.

Speech is a bridge to MathJax's [speech-rule-engine][sre] (Apache-2.0) rather than rules
of our own — MathSpeak and ClearSpeak are specified and user-tested, and an approximation
would be worse in ways that are hard to notice mid-paper. It needs Node:
`cd tools/sre && npm install`.

Two things are changed before speaking, both so you do not hear something that is not on
the page. A glyph we could not name is written `□` in MathML, which reads aloud as "white
square" — a real operator, and indistinguishable from one we meant; it is announced as
unrecognised instead. And the measured inter-atom spacing is dropped, because `mspace` is
read aloud as "empty", so a `\quad` before an equation number became a spoken word.

### 4. The other formats

| Format | Flag | What it is for |
|---|---|---|
| Presentation MathML | `--mathml` | the primary target; `--provenance` adds glyph ids |
| Speech | `speak`, `--speech` | ClearSpeak or MathSpeak text, or SSML |
| AsciiMath | `--asciimath` | linear, and stays readable magnified |
| LaTeX | `--latex` | the round-trip oracle, and useful on its own |
| Office MathML | `--omml` | what a `.docx` stores, so Word can *edit* it |
| WordPerfect 5.1 | `--wpeq` | the 1989 equation editor's command language |
| JSON tree | `--tree` | every node with provenance, residuals, confidence |
| LgEval label graph | `--lg` | comparison against MathSeer/CROHME tooling |

Ask for one and it prints bare; ask for several and you get JSON.

```bash
$ pdfmath extract examples/sample.pdf --latex
E = \frac{x_{i}^{2}}{\sqrt{y}}
\sum\limits_{k = 1}^{n} \frac{1}{k^{2}} = \frac{\pi^{2}}{6} - \varepsilon_{n} .
A = \left( \begin{matrix} a & b \\ c & d \end{matrix} \right) , \mskip 39.006mu \mathrm{det} \mskip 2.988mu A = a d - b c .
\sqrt{a^{2} + b^{2}}

$ pdfmath extract examples/sample.pdf --wpeq
E = {x sub i sup 2} over {sqrt {y}}
sum from {k = 1} to n {1} over {k sup 2} = {pi sup 2} over {6} - epsilon sub n .
A = left ( matrix {a & b # c & d} right ) , ~ det ` A = a d - b c .
sqrt {a sup 2 + b sup 2}
```

The LaTeX writer aims to recompile to the identical page rather than to look idiomatic,
which is why the spacing is explicit; it reports whatever it could not reproduce instead
of guessing.

### 5. When an equation is missed

The sample's last sentence also names a vector `$\mathbf{v}$`, and nothing finds it —
`\mathbf` and bold prose are the same font, so the distinction is not on the page to be
found. Give it the box directly:

```bash
$ pdfmath extract examples/sample.pdf --bbox 178,446,186,456 --style text --asciimath
v
```

`--bbox` is `x0,y0,x1,y1` in TeX points from the bottom-left of the page (`--bbox-bp` for
PDF big points), and `--style` tells the parser which math style to expect, since that
changes every Appendix G prediction. This is also the workaround when detection misses a
display — numbered equations are one known case, because the tag pushed out by `\hfill`
widens the line past what the detector expects.

#### How inline detection works

An inline formula has no shape to find it by: it sits in the middle of a sentence, on the
same baseline, in the same paragraph. What it has instead is TeX's own bookkeeping.

* **The font.** TeX sets prose from the roman font and mathematics from cmmi, cmsy and
  cmex. There is no way to type a cmmi glyph outside mathematics, so every one is a seed.
  This finds more than variables: the comma in `$[0,1]$` comes from cmmi, and it is the
  only non-roman character in that formula.
* **The gap, which calibrates itself.** Interword glue stretches so a line can be
  justified; math glue does not. So the word space is a property of *this line*,
  measurable from the line's own gaps — 6.4 mu on one line here, 6.1 on the next — and
  every automatic math space is at most 5 mu. That is what separates `\log n` from two
  words, with no threshold in points that would be wrong at another size.
* **The character class.** Roman characters do appear in formulas — digits, `+`, `=`,
  parentheses, capital Greek — so a seed grows outward through those and stops at a roman
  *letter*, which is prose. Operator names (`log`, `sin`, `max`) are the exception and are
  recognised as a set.

What it cannot do is find a formula containing no math-font glyph at all: `$\mathbf{v}$`
is cmbx and so is bold prose; `$2$` is a roman digit and so is a page number. Those are
undecidable rather than hard — TeX threw the distinction away — and they are left alone.

**Which is why this is on by default.** A missed inline formula is not silence: its
characters are still there and are still read. And the formulas this method misses are
exactly the ones made entirely of ordinary characters, so reading them as characters is
already right — `$\mathbf{v}$` says "v", which is what it is. The asymmetry runs the
other way from most detection problems: finding one is a large gain, missing one costs
nothing, and only a false positive would do harm. `--no-inline` turns it off.

### 6. Ask why

Every inference records its evidence in the units of the rule that produced it:

```bash
$ pdfmath explain examples/sample.pdf --page 1 --bbox 286,612,326,641
node 7  Fraction  [fraction]  confidence 0.9990
  bbox      310.48,611.83 .. 325.37,639.57 (pt)
  glyphs    [26, 27, 28, 29, 30]
  rules     [0, 1]
  children  [4, 6]
  evidence:
    rule_width_pt                       14.88660
    rule_thickness_pt                   0.43763
    expected_default_rule_thickness_pt  0.43799
    thickness_residual_pt               -0.00035
    n_above                             3
    n_below                             3
    style_fit                           display
    residual_pt                         +0.00039
    numerator_residual_pt               +0.00018
    denominator_residual_pt             -0.00039
    axis_height_pt                      2.73750
    consistent_with_rule_15             True
    ...                                 (and the measured inter-atom spacing either
                                         side, in mu, with the atom classes it implies)
```

A residual of 0.0004 pt is the fraction bar landing exactly where Appendix G rule 15 says
it must. That is the difference between a decompiler and a recogniser: the number is a
measurement, not a score.

### 7. Triage a document

```bash
$ pdfmath survey examples/sample.pdf
examples/sample.pdf
  equations              3
  glyph recovery         100.000%  (43/43)
  Unknown nodes          0
  inferences below 0.90  0

  page 1 bbox [223.17, 484.9, 389.37, 511.18]  confidence 0.9800  glyphs 20
  page 1 bbox [263.06, 546.47, 349.47, 577.01]  confidence 0.9900  glyphs 16
  page 1 bbox [285.97, 611.83, 325.37, 639.57]  confidence 0.9990  glyphs 7
```

`--floor 0.9` lists everything below a confidence you choose. A glyph nobody can explain
becomes an `Unknown` carrying its original geometry — nothing is silently dropped, and
there is a test for that.

### 8. See what the parser saw

```bash
pdfmath debug-svg examples/sample.pdf --page 1 --html -o page1.html
```

Glyph boxes, baselines, extracted rules and the recovered tree, in one SVG with
toggleable layers. `pdfmath dump` gives the same thing as JSON, one record per glyph,
before any parsing happens.

---

## Checking the output against something else

The interesting question is not whether the tool is confident but whether it is right, so
every claim has a check that does not run our code.

```bash
pdfmath roundtrip examples/sample.pdf     # recompile the LaTeX, compare pages glyph by glyph
pdfmath benchmark --suite all --n 200     # generate a corpus with known answers, score it
pdfmath arxiv math/0211159v1              # score against the paper's own source, via LaTeXML
```

`roundtrip` is the strongest of the three: it takes what we recovered, compiles it with
pdfTeX, and compares the resulting page against the original glyph by glyph. `exact`
means every glyph is the same character from the same font within 0.01 pt.

```bash
$ pdfmath roundtrip examples/sample.pdf
examples/sample.pdf
  equations            3
  exact                   2    66.7%
  shifted                 1    33.3%
```

It then prints each equation that was not exact, with the LaTeX it recovered and the
glyphs that moved, so a `shifted` verdict points at the box width we got wrong rather
than just failing. The command exits non-zero unless every equation is exact, which makes
it usable as a CI gate.

The serialisers are checked the same way, each against a reader that is not ours: MathML
against LaTeXML, AsciiMath against `py-asciimath`, OMML against pandoc's `docx` reader.
WordPerfect has no automated check yet — its vocabulary is taken from the equation parser
in the `wp51` project, but that exposes no command for a bare equation string — so it
rests on goldens, and the handful of commands still unconfirmed are flagged in the
output.

Numbers and method: [docs/evaluation.md].

---

## How it works

Four stages, one file each to start reading from.

1. **Extraction** (`extraction/pdfminer_backend.py`) intercepts pdfminer's renderer and
   records every glyph's character code, font, size and text matrix, plus every rule
   drawn as a filled rectangle. Not a bounding box from a page image — the numbers the
   typesetter used.
2. **Font knowledge** (`fonts/tfm.py`) reads the TFM files TeX itself used, giving
   per-character widths, heights, depths and italic corrections, and the σ and ξ
   parameters Appendix G is written in terms of.
3. **Parsing** (`parse/`) runs recognisers that each invert one published rule — rule 15
   for fractions, 18a–f for scripts, 11 for radicals, 13 for large operators — and report
   a residual in points rather than a threshold verdict. Anchors are claimed outermost
   first so a nested construct cannot steal its parent's.
4. **Serialisation** (`mathml/`, `speech/`, `asciimath/`, `latex/`, `omml/`,
   `wordperfect/`) walks the finished tree. Every node carries provenance back to the
   glyphs and rules it came from; that is not optional.

The design decisions, the inverted rules with their closed forms, the thresholds that
survive and why, and the known limitations with their causes are all in
[docs/architecture.md].

---

## Status and scope

Supported and measured: pdfTeX output, Computer Modern and Latin Modern, AMS symbol
fonts, displayed equations, display and text style, fractions, scripts, radicals,
delimiters (including built-up cmex assemblies), large operators with limits, matrices,
accents, over/underlines, and the inter-atom spacing table.

Inline formulas are found by default, from the fonts TeX switched to and the glue it
inserted rather than from any shape on the page; `--no-inline` restricts to displays.

Not yet: displayed equations in two-column layouts (inline formulas are found there
regardless, because that works line by line), numbered displays reliably detected,
XeTeX/LuaTeX OpenType math, Type 3 fonts, scanned pages (out of scope by
design), `\overbrace`-style horizontal braces, and alignment recovery in `align` beyond a
table of rows. [docs/architecture.md] lists the known limitations with reasons.

## Where to read more

| Document | What is in it |
|---|---|
| [docs/architecture.md] | how it works: pipeline, module map, inverted rules, thresholds, limitations |
| [docs/evaluation.md] | how well it works: synthetic corpus, real papers, recompilation |
| [docs/prior-art.md] | the audit of SymbolScraper, MathFIRE and MaxTract, with reuse decisions |
| [docs/comparison.md] | the MathSeer hypothesis and the protocol for testing it |

## Licence

MIT. Dependencies are MIT/BSD/MPL; PyMuPDF is deliberately avoided because it is
AGPL-3.0 and would be viral for downstream users.

[docs/architecture.md]: docs/architecture.md
[docs/evaluation.md]: docs/evaluation.md
[docs/prior-art.md]: docs/prior-art.md
[docs/comparison.md]: docs/comparison.md
[sre]: https://github.com/Speech-Rule-Engine/speech-rule-engine
