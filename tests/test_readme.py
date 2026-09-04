"""The README is a tutorial, so its commands have to work.

A tutorial that has drifted from the tool is worse than no tutorial: the reader cannot
tell which of the two is wrong.  This extracts every ``pdfmath`` invocation shown in
README.md, runs it against the sample document, and checks it succeeds -- and where the
README shows a command's complete output, checks that too.

Commands needing the network or a separate install (``arxiv``) are skipped by name.
"""

from __future__ import annotations

import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from pdfmath.corpus.compile import have_pdflatex
from pdfmath.speech import engine

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
SAMPLE_TEX = ROOT / "examples" / "sample.tex"

#: Shown in the README but not runnable here: needs the network and LaTeXML.
SKIP = ("arxiv",)

#: `roundtrip` exits non-zero unless every equation recompiles glyph-identically, which
#: is deliberate -- it makes the command usable as a CI gate.  The sample has one
#: `shifted` display, so a non-zero status here is the documented behaviour, not a break.
TOLERATE_NONZERO = ("roundtrip",)

#: Commands whose full output the README prints, keyed by the flag that selects it.
#: Anything elided in the README is not checked for output, only for success.
EXACT = ("--asciimath", "--wpeq", "--latex", "--mathml")


def readme_commands() -> list[str]:
    """Every ``pdfmath ...`` line inside a fenced block, with any ``$ `` prompt removed."""
    text = README.read_text()
    blocks = re.findall(r"```bash\n(.*?)```", text, re.S)
    out = []
    for block in blocks:
        for line in block.splitlines():
            line = line.strip()
            line = re.sub(r"^\$\s*", "", line)
            line = re.sub(r"\s+#.*$", "", line)          # trailing comment
            if line.startswith("pdfmath ") and not any(s in line for s in SKIP):
                out.append(line)
    return out


pytestmark = pytest.mark.skipif(not have_pdflatex(),
                                reason="the tutorial's sample needs pdflatex")


@pytest.fixture(scope="module")
def sample(tmp_path_factory) -> Path:
    """Build examples/sample.tex exactly as the README's first step says to."""
    out = tmp_path_factory.mktemp("readme")
    subprocess.run(["pdflatex", "-interaction=batchmode",
                    f"-output-directory={out}", str(SAMPLE_TEX)],
                   capture_output=True, check=True)
    pdf = out / "sample.pdf"
    assert pdf.exists()
    return pdf


def run(command: str, sample: Path, cwd: Path) -> subprocess.CompletedProcess:
    argv = shlex.split(command)
    argv = [str(sample) if a == "examples/sample.pdf" else a for a in argv]
    return subprocess.run([sys.executable, "-m", "pdfmath.cli.main"] + argv[1:],
                          capture_output=True, text=True, cwd=cwd)


def test_the_readme_shows_some_commands():
    assert len(readme_commands()) >= 8, "the tutorial's commands stopped being found"


@pytest.mark.parametrize("command", readme_commands())
def test_every_readme_command_runs(command, sample, tmp_path):
    if "speak" in command and not engine.available():
        pytest.skip("speech-rule-engine is not installed")
    proc = run(command, sample, tmp_path)
    if any(c in command for c in TOLERATE_NONZERO):
        assert proc.stdout.strip(), f"{command} printed nothing\n{proc.stderr}"
        return
    assert proc.returncode == 0, f"{command}\n{proc.stderr}"


def _shown_outputs(text: str):
    """Yield (command, printed output) for each ``$ pdfmath`` line in a fenced block.

    A block can hold more than one command, so it is split on the prompts rather than
    assumed to contain a single one.
    """
    for block in re.findall(r"```bash\n(.*?)```", text, re.S):
        command, buffered = None, []
        for line in block.splitlines():
            if line.startswith("$ "):
                if command is not None:
                    yield command, "\n".join(buffered).strip()
                command, buffered = line[2:].strip(), []
            elif command is not None:
                buffered.append(line)
        if command is not None:
            yield command, "\n".join(buffered).strip()


def test_the_outputs_the_readme_prints_in_full_are_current(sample, tmp_path):
    """Where the README shows a whole output, it must still be the whole output."""
    checked = 0
    for command, expected in _shown_outputs(README.read_text()):
        if not command.startswith("pdfmath"):
            continue
        if any(s in command for s in SKIP) or not any(f in command for f in EXACT):
            continue
        proc = run(command, sample, tmp_path)
        assert proc.returncode == 0, f"{command}\n{proc.stderr}"
        assert proc.stdout.strip() == expected, (
            f"{command}\n  README says:\n{expected}\n  now prints:\n{proc.stdout}")
        checked += 1
    assert checked >= 3, "no fully-printed outputs were checked"
