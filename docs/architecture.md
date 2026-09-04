# Architecture

## The idea in one paragraph

TeX compiles a math list into boxes, glue, kerns and rules by rules that are published in
full (*The TeXbook*, Appendix G) and parameterised by numbers that ship with the fonts
(the TFM files). pdfTeX then writes those boxes out as PDF drawing operations. Nothing in
that chain is lossy in a way that matters: the positions on the page are the *output of a
known function* of the structure we want back. So the job is not recognition, it is
inversion — and where inversion is ambiguous, the honest answer is to say so rather than
to guess.

## Pipeline

```
   PDF
    │  extraction/pdfminer_backend.py      intercept the renderer
    ▼
   Glyph[] + Rule[]                        raw code, font, size, text matrix, baseline
    │                                      rules normalised from stroked paths
    │  fonts/                              TFM metrics, TeX encodings, atom classes
    ▼
   resolved glyphs                         (font, code) -> glyph name -> symbol, box
    │  parse/units.py                      merge built-up delimiters and radicals
    ▼
   Unit[]                                  a box with a baseline and TeX's invisible
    │                                      leading/trailing advances
    │  parse/driver.py                     claim regions, recurse, fold relations
    ▼
   MathNode tree                           with provenance and evidence on every node
    │  mathml/serializer.py
    ▼
   Presentation MathML
```

## Units, and why they are TeX points

PDF user space is big points (1/72 in); TeX is printer's points (1/72.27 in). A 10 pt
font is written `9.9626 Tf`. Everything above `extraction/` is in TeX points, converted
once at the boundary, so that a TFM value scaled by the font size is directly comparable
to a measured position. Getting this wrong costs 0.375% — small enough to look like noise
and large enough to make every residual meaningless.

## The five facts the architecture is built on

Established empirically on stock pdfTeX 1.40.29 output; see `docs/prior-art.md` §4 and
`tests/synthetic/test_appendix_g.py`.

1. **Rules are stroked lines, not filled rectangles.** pdfTeX draws a fraction bar as
   `0 0 m 13.544 0 l S` with the thickness in the graphics state. Anything that only
   looks for `re f` misses every fraction bar.
2. **The radical overbar is a separate object from the surd**, and must be re-associated:
   the bar's left edge is at the surd's right edge, and their tops agree.
3. **Font size encodes style**: 0.7 for script and 0.5 for scriptscript, and the *font
   changes too* (cmmi10 → cmmi7), so there are two independent readings of the style.
4. **The TFM box is not the ink box.** cmsy's `radical` has height 0.04 and depth 0.96 —
   almost entirely below the baseline. TeX positioned it with those numbers, so those are
   the numbers to reason with; outline-derived ink boxes answer a different question.
5. **Everything is baseline-relative.** Appendix G is written in terms of baselines, and
   Baker's evaluation found this to be the single decision that makes script detection
   exact. Ink centroids lose it.

## Module map

| module | job |
|---|---|
| `units.py` | bp ↔ pt, scaled points |
| `extraction/model.py` | `Glyph`, `Rule`, `PageExtract` — the measured IR |
| `extraction/pdfminer_backend.py` | renderer interception; paths → rules |
| `extraction/symbolscraper_adapter.py` | ingest SymbolScraper XML/JSON for cross-checking |
| `fonts/tfm.py` | TFM reader: per-glyph metrics, σ/ξ parameters, charlists, extensible recipes |
| `fonts/data/tex_encodings.py` | generated from the AFMs; ships so no TeX is required |
| `fonts/symbols.py` | glyph name → Unicode, atom class, structural role, size rank |
| `fonts/normalize.py` | PDF font name → family, encoding, design size, mathvariant |
| `fonts/metrics.py` | `FontMetrics.lookup(font, code, size)` |
| `fonts/mathparams.py` | Appendix G parameters by *style*, with LaTeX's size ranges |
| `geometry/` | boxes, spatial queries, baseline clustering, banding |
| `tree/nodes.py` | the node set, with mandatory provenance |
| `parse/context.py` | style, size, parameters, and the decision trace |
| `parse/axis.py` | undo `make_op` / `var_delimiter` axis centring |
| `parse/blocks.py` | structural cohesion: what belongs to a two-dimensional construct |
| `parse/style.py` | recover the math style from thickness and size |
| `parse/spacing.py` | invert TeX's inter-atom glue table |
| `parse/{fractions,radicals,scripts,delimiters,operators,accents,matrices,rows}.py` | the recognisers |
| `parse/driver.py` | anchor claiming and the recursion |
| `mathml/serializer.py` | Presentation MathML, optionally with provenance attributes |
| `mathml/lgeval.py` | LgEval label graphs, for comparison with CROHME/MathSeer tooling |
| `latex/serializer.py` | the tree back to LaTeX, for the round-trip oracle |
| `latex/data/tex_commands.py` | generated from LaTeX's own \DeclareMathSymbol tables |
| `eval/roundtrip.py` | recompile and compare |
| `eval/mathml_compare.py` | read MathML back into a comparison signature |
| `eval/latexml.py` | LaTeXML as an independent oracle |
| `eval/arxiv_eval.py` | score against a paper's own source |
| `corpus/arxiv.py` | fetch an e-print, split out its displays |
| `detection/equations.py` | geometric displayed-equation detection |
| `debug/{svg,explain}.py` | the debug renderer and `pdfmath explain` |
| `corpus/` | grammar, generator, compiler, harness, shrinker, Hypothesis strategies |

## Parse order, and why

`parse_units` runs recognisers in an order that mirrors `mlist_to_hlist` run backwards.

1. **Merge runs** — built-up delimiters and radicals become single symbols, using the
   font's own extensible recipes to decide what is a piece.
2. **Claim anchors** — fraction bars and radicals own regions of the page, and those
   regions nest. The outermost (largest claim) is collapsed first, recursing into it.
3. **Merge tokens** — digit runs into numbers, upright-roman runs into function names.
   Before scripts, so that `10_0` subscripts the number and not its last digit; accents
   are set aside first because they have zero width in TeX's hlist.
4. **Axis normalisation** — large operators and fences are moved back onto the line's
   baseline.
5. **Limits** onto large operators (rules 13 / §750–751).
6. **Accents** onto their nuclei (rule 12), driven from the accent because a wide one
   starts left of its base.
7. **Fences** paired, recursing into the body — where a `pmatrix` finds its rows.
8. **Rows** split, if the material occupies more than one line.
9. **Scripts** folded (rule 18).
10. **Row emitted**, with leaf classification and the inter-atom spacing measured.

## The rules that are inverted

| construct | rule | what is checked |
|---|---|---|
| superscript | 18c | `shift_up = max(u, clr, d(sup) + x_height/4)`; `clr` is `sup1`/`sup2`/`sup3` by style |
| subscript | 18b | `shift_down = max(v, sub1, h(sub) − 0.8·x_height)` |
| both | 18f | `sub2`, then a `4·θ` clearance, then the `ψ` correction |
| italic | §749 | superscript at `x + w + italic`, subscript at `x + w` |
| fraction | 15 | bar centre at `axis_height`; `num1/num2` up, `denom1/denom2` down; bar width `= max(w_num, w_den)` |
| radical | 11 | `clr = θ + x_height/4` (display) or `θ + θ/4`, plus half of any surplus surd depth |
| large operator | 13 | axis centring `= (h − d)/2 − axis_height` |
| limits | §750–751 | `big_op_spacing1..4` |
| accent | 12 | accent baseline `= nucleus baseline + h − min(h, x_height)`, centred |
| overline | 9 | clearance `3θ`, thickness `θ` |
| spacing | ch. 18 | the 8×8 atom-class table, in `mu` = quad/18 |

Each recogniser reports a **residual** in points, and the residual becomes the node's
confidence. That is the difference between this and a threshold-based parser: a wrong
answer shows up as a large residual rather than as a confident mistake.

## Thresholds, and the ones that remain

The project's rule is that a tolerance must be *derived*, not tuned. The ones in use:

| where | value | why that value |
|---|---|---|
| script cluster split | `2θ` | rule 18f guarantees `4θ` between a sup and a sub |
| vertical cohesion | `x_height/2` | material on one baseline overlaps; a different line does not |
| script growth (tight) | 0.05 pt | box-to-box contiguity; medium/thick glue vanishes in script styles |
| script growth (wide) | `5/18` quad | a thick space, the widest glue that survives in script style |
| column separator | `> 1.25 × 5/18` quad | wider than any automatic inter-atom space |
| row split (baselines) | `text_size/2` | smaller than `\baselineskip`, larger than any script shift |
| baseline equality | `0.005 × text_size` | absorbs pdfTeX's coordinate rounding, nothing more |
| residual → confidence | `0.002 × text_size` | the PDF's own precision |

Rows are separated by *baseline*, not by whitespace: a fraction in the top row of a table
hangs down close to the row beneath it and a script in one row reaches up past the row
above, so there is frequently no gap to find. What validates a split is not coverage but
*size* -- every row of a table is set at the enclosing size and a script never is. The one
remaining judgement call is the row-split threshold itself, documented at the call site in
`parse/matrices.py`.

## Ground truth

`corpus/grammar.py` objects emit **both** the LaTeX and the expected tree, so no expected
answer is ever derived from a PDF. Two normalisations are applied to both sides, and both
are forced by the medium rather than chosen:

* **Nested rows are flattened.** TeX renders `{a+b}c` and `a+bc` identically.
* **Spacing is excluded from the comparison signature**, though it stays in the tree and
  the MathML. An author's `\,` does not change what the expression *is*.

Two shapes are excluded from generation for the same reason, and the shrinker refuses to
produce them (`corpus/shrink.is_recoverable`):

* a **single-row matrix** — `\begin{pmatrix} a & b \end{pmatrix}` renders exactly like
  `\left( a \quad b \right)`, and `\begin{matrix} x \end{matrix}` exactly like `x`;
* a **row as a script base** — `{a+b}^2` and `a+b^2` are the same page whenever the group
  is no taller than its last atom, because rule 18a's `u = h − sup_drop` then loses to
  `sup2`.

Asserting either would be blaming the decompiler for an ambiguity in the ground truth.

## Known limitations

Each of these is a real failure with a known cause, not a mystery.

1. **Real documents do not round-trip.** 3.9% of detected equations in the arXiv corpus
   recompile identically, against 100% of the synthetic corpus. The oracle attributes most
   of the gap to detection producing regions that are not single displayed equations, and
   the rest to structures in complex real equations that we get wrong — visible as a
   `\left(` whose size implies content we did not recover. This is the largest open item
   in the project and the reason the confidence scores should not be read as accuracy.
2. **A script on a braced group whose last atom is not the tallest thing in it** —
   `{\sum_a^b\, k}^x`. The outer superscript is placed on the group's box, which is taller
   than `k`, so it lands higher than a script on `k` would; the parser attaches it to `k`
   anyway. The evidence to fix it is there — the residual against `k` is large and against
   the group is not — but acting on it means letting a script recogniser extend its own
   base leftward, which is not yet implemented.
3. **Skew kerns are not read.** `make_math_accent` shifts an accent by the kern between
   the nucleus and the font's `\skewchar`, which lives in the TFM's lig/kern program — the
   one part of the TFM this reader skips. The accent recogniser therefore reports the skew
   as evidence rather than checking it. Parsing lig/kern would make accents exact.
4. **Inline mathematics is not detected**, only displayed equations. The decompiler itself
   is style-agnostic; pass `--bbox` for inline formulae.
5. **Non-TeX fonts degrade to ToUnicode**, flagged as `unicode_source: "tounicode"`, with
   metrics from the PDF's `/Widths`. Structure recovery still works but the residuals stop
   being meaningful.

## Inverting TeX's spacing: the result

The project set out to ask whether TeX's atom classes can be solved backwards from the
page. They can, partially, and the partition is exact rather than statistical.

``\mathbin{b}`` and ``\mathrel{b}`` print the same glyph -- an ordinary cmmi ``b`` -- so
the character says nothing. The glue does. Measuring the gaps either side of ``b`` in
``a \math???{b} c``, in units of ``mu`` = quad/18:

| declared | left | right | classes consistent with the measurement |
|---|---|---|---|
| Ord | 0.000 | 0.001 | Ord, Open, Close |
| Op | 2.999 | 3.000 | Op, Inner |
| **Bin** | 3.996 | 3.997 | **Bin** |
| **Rel** | 5.004 | 5.005 | **Rel** |
| Open | 0.000 | 0.001 | Ord, Open, Close |
| Close | 0.000 | 0.001 | Ord, Open, Close |
| **Punct** | 0.000 | 3.007 | **Punct** |
| Inner | 3.006 | 2.989 | Op, Inner |

Three classes are recovered uniquely; the other five collapse into two groups. The
collapse is not a limitation of the method -- those classes produce *identical* pages
between Ord neighbours, so no procedure whatever could separate them, and reporting a
single answer there would be inventing a distinction the document does not make. The
measurements land within 0.007 mu of the table, which is the PDF's rounding.

Two things follow, and both are implemented.

**TeX's own rewriting has to be reproduced first.** ``mlist_to_hlist`` demotes a Bin to
an Ord when it starts a list or follows a Bin, Op, Rel, Open or Punct, and demotes a Bin
that precedes a Rel, Close or Punct (tex.web 727-728). This is why ``-x`` and ``a-b`` use
one glyph with two spacings. Without the rewrite, every unary sign in a document produces
a gap the table cannot explain and the parser reports an author-inserted space that is
not there. `parse/atoms.py` applies it; `tests/synthetic/test_atom_classes.py` is the
experiment above, run as a test.

**A gap the table *cannot* explain is therefore informative.** It means the author asked
for it -- a ``\,``, a ``\quad``, an ``\hspace`` -- and that is the only case where a
``Space`` node is emitted. Automatic glue is left out, because a MathML renderer inserts
its own.

## The round-trip oracle

`pdfmath/eval/roundtrip.py`, driven by `pdfmath roundtrip`. Serialise the recovered tree
back to LaTeX (`pdfmath/latex/`), recompile with pdfTeX, extract, and compare glyph
positions with the original after aligning on the *median* displacement — median rather
than first glyph, so one misplaced symbol cannot drag the whole comparison.

Verdicts: `exact` (same glyphs, same relative positions to within pdfTeX's own rounding),
`shifted` (same glyphs, moved), `different` (different glyphs), `incomplete` (something in
the tree has no LaTeX that reproduces it), `uncompilable`.

Three things make it worth more than the corpus comparison:

* it needs no ground truth, so it applies to real documents where none exists;
* it needs no second system, so nothing has to be installed, licensed or trusted;
* it tests what matters — a tree that differs from ground truth in a way TeX cannot render
  differently is not a defect, and a tree that recompiles to a different page is one
  whatever a tree-edit distance says.

It cannot catch a genuinely ambiguous structure: `{a+b}^2` and `a+b^2` recompile
identically because they are the same page, which is the same class of difference the
corpus comparison declines to assert.

The LaTeX serializer is built for fidelity, not legibility. Commands come from LaTeX's own
`\DeclareMathSymbol` tables (generated by `tools/gen_commands.py`) and are chosen **by
atom class**: cmsy slot 0x6A is both `\mid` (a relation) and `\vert` (ordinary), and
emitting the wrong one changes the inter-atom glue and moves everything after it.
Measured spaces go back out as `\mskip <n>mu` rather than being guessed from a name.

Building it paid for itself immediately: it found that composite units were reporting the
atom class `Ord` instead of the class TeX gives the structure — `Inner` for a fraction and
a `\left...\right` group, `Op` for an operator with limits — which had been making the
space after every summation sign look unexplained.

## Real ground truth: arXiv source through LaTeXML

`pdfmath/corpus/arxiv.py` and `pdfmath/eval/arxiv_eval.py`, driven by `pdfmath arxiv`.

```
e-print source ──> displays ──> LaTeXML ──> expected MathML ──> signature
       │                                                            ║  compare
       └──> one display per page ──> pdfTeX ──> PDF ──> pdfmath ──> signature
```

Two design decisions carry it. **One display per page**, re-set with the paper's own
preamble, so page *i* is display *i* — that removes the alignment problem and takes
equation detection out of the measurement, leaving the decompiler as the thing being
scored. And **LaTeX only**: a 1992 AmSTeX paper is not a LaTeX document, pdflatex will not
build it, and it is reported as unsupported rather than mangled.

Comparison runs on *relaxed* signatures (`eval/mathml_compare.py`). Four things are folded,
and each is folded because a PDF cannot record it:

* nested `mrow` grouping, which no renderer distinguishes;
* invisible operators (U+2061..U+2064) that mark function application and implied
  multiplication;
* `mi` against `mo`, and `LargeOperator` against `Operator` — claims about a symbol's
  role, not about what was printed;
* the spacing-versus-combining spelling of an accent, and whether a word like `Ric` is one
  token or three.

Folding these is not conceding a point; it is declining to be scored on the converters'
conventions. Everything else — every fraction, script, radical, fence and table — has to
match exactly.

The same comparator turns LaTeXML into a check on our *own* ground truth, which is
otherwise generated by the same objects that emit the LaTeX. It agrees with 17 of 17
first-milestone trees and 56 of 58 extended ones.

Filling the symbol tables came out of this. Real papers use msam, msbm and latexsym, which
our hand-written Computer Modern tables did not cover, so `\Box` arrived as an `Unknown`.
`tools/gen_extra_symbols.py` composes LaTeXML's `DefMath` command→Unicode declarations
with LaTeX's `\DeclareMathSymbol` command→slot declarations to get glyph→Unicode and
glyph→atom-class for 201 more symbols, generated rather than transcribed.

## Comparison with MathSeer

`docs/comparison.md` states the hypothesis the project is meant to test, what has been
established, what has not, and a runnable protocol using DPRL's own LgEval. The short
version: the evidence the hypothesis depends on has been shown to exist and to be exact,
and the system built on it reconstructs the constrained corpus perfectly and real 1990s
papers with 100% glyph recovery — but QD-GGA has not been run here, so no comparative
number is claimed. `pdfmath benchmark --lg-dir` and `pdfmath extract --lg` emit label
graphs so that a reader with the MathSeer stack can run the comparison.

## Extending it

The workflow, in order:

1. Reproduce the failure as a **synthetic** expression in `corpus/grammar.py` terms.
2. `pdfmath debug-svg ... --html` to see the geometry the parser received.
3. `pdfmath explain ... --max-confidence 0.99` to see which inference was uncertain and
   what evidence it had.
4. Find the **TeX rule** that produced the layout, and invert it. If you find yourself
   choosing a constant, you have not found the rule yet.
5. Add the minimised case to `tests/regression/test_regressions.py` with a note saying
   what the fix generalises to.
6. `pdfmath benchmark --suite all` to check nothing else moved.

The shrinker is the tool that makes step 1 cheap: `corpus/shrink.shrink` reduced a
three-row matrix expression with seven nested constructs to `\begin{matrix} x \end{matrix}`
in about a second, and that reduction is what identified the ground-truth ambiguity above.
