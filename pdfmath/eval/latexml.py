"""LaTeXML as an independent oracle.

LaTeXML (<https://math.nist.gov/~BMiller/LaTeXML/>) is the reference converter from LaTeX
to MathML, and it is independent of everything here: it reads the *source*, we read the
*page*.  Where both are available -- an arXiv paper, whose LaTeX and PDF are both
published -- that turns a real document into a labelled example, which is the one thing
the synthetic corpus cannot provide.

Using it as an oracle needs its output read back into a comparison signature (see
mathml_compare) and needs the paper's own macros, or half a real document's mathematics
is undefined control sequences.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional, Sequence


def available() -> bool:
    return shutil.which("latexmlmath") is not None


@dataclass
class Conversion:
    tex: str
    mathml: Optional[str]
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return bool(self.mathml)


def to_mathml(tex: str, preloads: Sequence[str] = (), timeout: int = 120,
              display: bool = True) -> Conversion:
    """Convert one LaTeX math fragment to Presentation MathML.

    ``preloads`` are files LaTeXML should read first -- the paper's macro definitions,
    and the packages it relies on.
    """
    if not available():
        return Conversion(tex, None, "latexmlmath is not installed")
    cmd = ["latexmlmath", "--quiet", "--quiet"]
    for name in ("amsmath.sty", "amssymb.sty", *preloads):
        cmd.append(f"--preload={name}")
    cmd += ["--pmml=-", tex if display else f"\\textstyle {tex}"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return Conversion(tex, None, f"{type(exc).__name__}: {exc}")
    out = proc.stdout.strip()
    if not out.startswith("<"):
        tail = (proc.stderr or "").strip().splitlines()
        return Conversion(tex, None, tail[-1] if tail else "no output")
    return Conversion(tex, out)


def to_mathml_batch(fragments: Sequence[str], preloads: Sequence[str] = (),
                    timeout: int = 120) -> list[Conversion]:
    return [to_mathml(f, preloads, timeout) for f in fragments]
