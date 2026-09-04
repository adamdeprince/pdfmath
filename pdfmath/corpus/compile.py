"""Compile generated expressions with pdfTeX, one expression per page.

One page per expression sidesteps equation detection entirely, which is what lets the
decompiler be measured on its own before a detector exists (see docs/prior-art.md).
``\\pagestyle{empty}`` keeps page numbers out of the extraction, so every glyph on a page
belongs to the formula.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Optional, Sequence

DEFAULT_PREAMBLE = r"""
\documentclass[%(size)dpt]{article}
\usepackage{amsmath}
\usepackage{amssymb}
\pagestyle{empty}
\setlength{\parindent}{0pt}
\begin{document}
"""

DEFAULT_POSTAMBLE = r"""
\end{document}
"""


class CompileError(RuntimeError):
    pass


@dataclass
class CompiledCorpus:
    """A PDF whose page *i+1* holds ``expressions[i]``."""

    pdf_path: str
    tex_path: str
    log_path: str
    expressions: list[str]
    workdir: str

    def page_of(self, index: int) -> int:
        return index + 1


def have_pdflatex() -> bool:
    return shutil.which("pdflatex") is not None


def build_document(tex_expressions: Sequence[str], size: int = 10,
                   display: bool = True, preamble: Optional[str] = None) -> str:
    """The LaTeX source of a one-expression-per-page document."""
    parts = [(preamble or DEFAULT_PREAMBLE) % {"size": size}]
    for i, e in enumerate(tex_expressions):
        if display:
            parts.append(f"\\[\n{e}\n\\]\n")
        else:
            parts.append(f"$ {e} $\n")
        if i != len(tex_expressions) - 1:
            parts.append("\\newpage\n")
    parts.append(DEFAULT_POSTAMBLE)
    return "".join(parts)


def compile_expressions(tex_expressions: Sequence[str], workdir: Optional[str] = None,
                        size: int = 10, display: bool = True,
                        name: Optional[str] = None,
                        preamble: Optional[str] = None,
                        cache: bool = True,
                        halt_on_error: bool = True,
                        source: Optional[str] = None) -> CompiledCorpus:
    """Run pdfTeX over the expressions and return the resulting PDF.

    Compilation is cached on a hash of the source, so re-running a test suite that has
    not changed costs nothing.
    """
    if not have_pdflatex():
        raise CompileError("pdflatex is not on PATH")
    source = source or build_document(tex_expressions, size=size, display=display,
                                      preamble=preamble)
    digest = hashlib.sha256(source.encode()).hexdigest()[:16]
    stem = name or f"corpus_{digest}"
    workdir = workdir or os.path.join(tempfile.gettempdir(), "pdfmath-corpus")
    os.makedirs(workdir, exist_ok=True)

    tex_path = os.path.join(workdir, stem + ".tex")
    pdf_path = os.path.join(workdir, stem + ".pdf")
    log_path = os.path.join(workdir, stem + ".log")

    if cache and os.path.exists(pdf_path) and os.path.exists(tex_path):
        with open(tex_path) as fh:
            if fh.read() == source:
                return CompiledCorpus(pdf_path, tex_path, log_path,
                                      list(tex_expressions), workdir)

    with open(tex_path, "w") as fh:
        fh.write(source)
    command = ["pdflatex", "-interaction=nonstopmode"]
    if halt_on_error:
        # Off for real documents: a paper's preamble routinely refers to labels and
        # files we do not have, and stopping at the first would lose every display
        # after it.  The page count is checked by the caller instead.
        command.append("-halt-on-error")
    command += ["-output-directory", workdir, tex_path]
    proc = subprocess.run(command, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0 or not os.path.exists(pdf_path):
        tail = proc.stdout[-3000:] if proc.stdout else proc.stderr[-3000:]
        raise CompileError(f"pdflatex failed for {stem}:\n{tail}")
    return CompiledCorpus(pdf_path, tex_path, log_path, list(tex_expressions), workdir)
