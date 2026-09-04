"""Real papers with real ground truth: arXiv's LaTeX source next to its PDF.

The synthetic corpus proves the decompiler on mathematics we wrote.  arXiv publishes the
*source* of papers whose PDFs we can also read, so for those the expected answer comes
from the document's own author rather than from us -- via LaTeXML, which reads the source
while we read the page.

Two practical constraints shape this module.

**One display per page.**  The displays are re-set, using the paper's own preamble, one
to a page.  That removes the alignment problem entirely -- page *i* is display *i* -- and
takes equation *detection* out of the measurement, so what is being scored is the
decompiler rather than the pipeline.  It also means the layout is the paper's own: same
class, same options, same macros, same fonts.

**LaTeX only.**  A 1992 AmSTeX paper (``\\input amstex``) is not a LaTeX document and
pdflatex will not build it.  Those are reported as unsupported rather than mangled.
"""

from __future__ import annotations

import gzip
import io
import os
import re
import tarfile
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

ARXIV_SOURCE = "https://arxiv.org/e-print/{identifier}"
USER_AGENT = "pdfmath-eval/0.1 (research; https://arxiv.org/help/api)"

#: Display-math environments that hold a *single* formula.  Multi-line ones (align,
#: eqnarray, gather) are a different structure and are collected separately.
_SINGLE = ("equation", "displaymath", "equation*", "math")
_MULTI = ("align", "align*", "eqnarray", "eqnarray*", "gather", "gather*",
          "multline", "multline*", "split", "alignat", "alignat*")

_ENV = re.compile(r"\\begin\{(?P<env>[a-zA-Z*]+)\}(?P<body>.*?)\\end\{(?P=env)\}", re.S)
_BRACKET = re.compile(r"\\\[(?P<body>.*?)\\\]", re.S)
_DOLLARS = re.compile(r"(?<!\\)\$\$(?P<body>.*?)(?<!\\)\$\$", re.S)
_COMMENT = re.compile(r"(?<!\\)%.*?$", re.M)


@dataclass
class ArxivPaper:
    identifier: str
    source: str                     # the main .tex, comments stripped
    documentclass: Optional[str]
    preamble: str                   # everything between \documentclass and \begin{document}
    displays: list[str] = field(default_factory=list)
    multiline: list[str] = field(default_factory=list)
    note: Optional[str] = None

    @property
    def is_latex(self) -> bool:
        return self.documentclass is not None

    @property
    def class_options(self) -> str:
        if not self.documentclass:
            return ""
        m = re.search(r"\[(.*?)\]", self.documentclass)
        return m.group(1) if m else ""

    @property
    def class_name(self) -> str:
        """The paper's own class.  amsart is not article, and its macros know it."""
        if not self.documentclass:
            return "article"
        m = re.search(r"\{([^}]*)\}", self.documentclass)
        return (m.group(1).split(",")[0].strip() if m else "article") or "article"


def fetch_source(identifier: str, cache_dir: str) -> bytes:
    """Download an arXiv e-print, cached on disk."""
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, identifier.replace("/", "_") + ".src")
    if os.path.exists(path) and os.path.getsize(path):
        with open(path, "rb") as fh:
            return fh.read()
    request = urllib.request.Request(ARXIV_SOURCE.format(identifier=identifier),
                                     headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read()
    with open(path, "wb") as fh:
        fh.write(data)
    return data


def main_tex(data: bytes) -> Optional[str]:
    """The main .tex file from an e-print, which may be a bare gzip or a tarball."""
    try:
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            members = [m for m in tar.getmembers()
                       if m.isfile() and m.name.endswith(".tex")]
            if not members:
                return None
            # The main file is the one with \documentclass or \documentstyle in it;
            # failing that, the largest.
            best = None
            for m in members:
                fh = tar.extractfile(m)
                if fh is None:
                    continue
                text = fh.read().decode("utf-8", "replace")
                if re.search(r"\\document(class|style)", text):
                    return text
                if best is None or len(text) > len(best):
                    best = text
            return best
    except tarfile.TarError:
        pass
    try:
        return gzip.decompress(data).decode("utf-8", "replace")
    except OSError:
        return data.decode("utf-8", "replace")


def parse(identifier: str, text: str) -> ArxivPaper:
    """Split a paper into its preamble and its display equations."""
    stripped = _COMMENT.sub("", text)
    cls = re.search(r"\\documentclass[^\n]*", stripped)
    begin = stripped.find("\\begin{document}")
    preamble = ""
    if cls and begin > 0:
        preamble = stripped[cls.end():begin]
    body = stripped[begin:] if begin > 0 else stripped

    displays: list[str] = []
    multiline: list[str] = []
    consumed: list[tuple[int, int]] = []
    for m in _ENV.finditer(body):
        env = m.group("env")
        if env in _SINGLE:
            displays.append(m.group("body").strip())
            consumed.append(m.span())
        elif env in _MULTI:
            multiline.append(m.group("body").strip())
            consumed.append(m.span())

    def outside(span):
        return not any(a <= span[0] < b for a, b in consumed)

    for pattern in (_BRACKET, _DOLLARS):
        for m in pattern.finditer(body):
            if outside(m.span()):
                displays.append(m.group("body").strip())

    return ArxivPaper(identifier=identifier, source=stripped,
                      documentclass=cls.group(0) if cls else None,
                      preamble=preamble, displays=displays, multiline=multiline)


def load(identifier: str, cache_dir: str) -> ArxivPaper:
    data = fetch_source(identifier, cache_dir)
    text = main_tex(data)
    if text is None:
        return ArxivPaper(identifier, "", None, "", note="no .tex in the e-print")
    paper = parse(identifier, text)
    if not paper.is_latex:
        paper.note = ("not a LaTeX document (plain TeX or AmSTeX); pdflatex cannot "
                      "build it")
    return paper


def one_per_page(paper: ArxivPaper, displays: Optional[list[str]] = None) -> str:
    """A document that re-sets each display on its own page, with the paper's macros."""
    body = []
    chosen = paper.displays if displays is None else displays
    for i, tex in enumerate(chosen):
        body.append("\\[\n" + tex + "\n\\]\n")
        if i != len(chosen) - 1:
            body.append("\\newpage\n")
    options = f"[{paper.class_options}]" if paper.class_options else ""
    # Only add packages the paper does not already load: "\usepackage{amsmath}" after
    # the paper's own "\usepackage[centertags]{amsmath}" is an option clash and stops
    # the build.
    extra = "".join(f"\\usepackage{{{name}}}\n" for name in ("amsmath", "amssymb")
                    if not re.search(r"\\usepackage[^\n]*\{[^}]*\b" + name + r"\b",
                                     paper.preamble))
    return (f"\\documentclass{options}{{{paper.class_name}}}\n"
            f"{extra}"
            f"{paper.preamble}\n"
            "\\pagestyle{empty}\n\\setlength{\\parindent}{0pt}\n"
            "\\begin{document}\n" + "".join(body) + "\\end{document}\n")


def macro_file(paper: ArxivPaper, path: str) -> str:
    """Write the paper's preamble where LaTeXML can preload it."""
    with open(path, "w") as fh:
        fh.write(paper.preamble)
    return path
