"""Speech, by way of MathJax's speech-rule-engine.

Speech is the output this project exists for, and it is the one output we should not
write ourselves.  MathSpeak and ClearSpeak are specified rule sets with years of user
testing behind them; ``speech-rule-engine`` (Apache-2.0) implements both, and a
hand-rolled approximation would be worse in ways that are hard to notice and easy to
trip over mid-paper.  So this module is a bridge, not an engine.

**Unidentified glyphs are announced.**  This is the one place we do not simply hand our
MathML over.  A glyph we could not name is written ``□`` in MathML, and read aloud that
becomes "white square" -- which is not a placeholder but a real operator (d'Alembertian,
or the modal box).  A reader has no way to tell the difference, so before speaking, every
:class:`Unknown` we could not name at all is replaced by a phrase that says so.  Silently
promoting our own ignorance into a plausible symbol is exactly the failure the rest of
the project is built to avoid; it would be worse here, because speech leaves no trace to
go back and check.

The engine runs once per batch.  Starting node and loading the rule tables costs more
than a page of equations, so :func:`speak_batch` should be preferred wherever there is
more than one thing to say.
"""

from __future__ import annotations

import copy as _copy
import json
import os
import shutil
import subprocess
import tempfile
from typing import Optional, Sequence

from ..mathml.serializer import to_mathml
from ..tree.nodes import MathNode, Space, Text, Unknown

#: Rule sets.  ClearSpeak reads the way a person would say it; MathSpeak is unambiguous
#: and reversible, which is what you want when checking someone else's algebra.
DOMAINS = ("clearspeak", "mathspeak")

#: Verbosity within a rule set.  MathSpeak's "brief" and "sbrief" drop the longer
#: bracketing phrases; ClearSpeak takes its preferences here too.
STYLES = ("default", "brief", "sbrief")

#: How an unnamed glyph is spoken.  Deliberately not a symbol.
UNKNOWN_PHRASE = "unrecognised symbol"

_BRIDGE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "tools", "sre", "speak.js")

_INSTALL = ("speech-rule-engine is not installed.  From the repository root:\n"
            "    cd tools/sre && npm install")


class SpeechError(RuntimeError):
    """The speech backend could not be reached, or refused the input."""


def install_hint() -> str:
    if shutil.which("node") is None:
        return ("node is not on PATH.  Install Node.js (for example `brew install "
                "node`), then:\n    cd tools/sre && npm install")
    return _INSTALL


def available() -> bool:
    """True when node and the rule engine are both present."""
    if shutil.which("node") is None or not os.path.exists(_BRIDGE):
        return False
    return os.path.isdir(os.path.join(os.path.dirname(_BRIDGE), "node_modules",
                                      "speech-rule-engine"))


def speech_mathml(tree: MathNode, **kw) -> str:
    """MathML prepared for speech.  See :func:`_prepare` for what changes and why."""
    return to_mathml(_prepare(tree), **kw)


def _prepare(node: MathNode) -> MathNode:
    """Two substitutions, both to stop the reader hearing something that is not there.

    *Unnamed glyphs are announced.*  A glyph whose character we do know is left alone --
    the engine will name the character, which is more useful than a generic phrase.  Only
    the case where we have no identity at all becomes :data:`UNKNOWN_PHRASE`.

    *Measured spacing is dropped.*  We record the gaps TeX inserted because they carry
    information about the structure, but an ``mspace`` is read aloud as "empty", so a
    ``\\quad`` before an equation number becomes a spoken word.  Speech gets its pauses
    from the rule set, not from the page.
    """
    if isinstance(node, Unknown) and not node.text:
        return Text(text=UNKNOWN_PHRASE, prov=node.prov)
    if not node.children:
        return node
    replaced = [_prepare(c) for c in node.children if not isinstance(c, Space)]
    if len(replaced) == len(node.children) and all(
            a is b for a, b in zip(replaced, node.children)):
        return node
    clone = _copy.copy(node)          # speech never emits provenance
    clone.children = replaced
    return clone


def speak_batch(items: Sequence[str], domain: str = "clearspeak",
                style: str = "default", locale: str = "en",
                markup: str = "none", timeout: int = 120) -> list[str]:
    """Speak a batch of MathML strings.  One engine start for the whole batch."""
    if not items:
        return []
    if domain not in DOMAINS:
        raise SpeechError(f"unknown rule set {domain!r}; expected one of "
                          f"{', '.join(DOMAINS)}")
    if not available():
        raise SpeechError(install_hint())
    request = {"domain": domain, "style": style, "locale": locale,
               "markup": markup, "items": list(items)}
    with tempfile.TemporaryDirectory() as tmp:
        inp = os.path.join(tmp, "in.json")
        out = os.path.join(tmp, "out.json")
        with open(inp, "w", encoding="utf-8") as fh:
            json.dump(request, fh)
        try:
            proc = subprocess.run(["node", _BRIDGE, inp, out],
                                  capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise SpeechError(f"the speech engine timed out after {timeout}s") from exc
        if not os.path.exists(out):
            raise SpeechError(proc.stderr.strip() or "the speech engine wrote nothing")
        with open(out, encoding="utf-8") as fh:
            answer = json.load(fh)
    if "error" in answer:
        raise SpeechError(answer["error"])
    return answer["speech"]


def speak(tree_or_mathml, domain: str = "clearspeak", style: str = "default",
          locale: str = "en", markup: str = "none") -> str:
    """Speak one equation, given either a tree or MathML."""
    xml = (tree_or_mathml if isinstance(tree_or_mathml, str)
           else speech_mathml(tree_or_mathml, indent=False))
    return speak_batch([xml], domain, style, locale, markup)[0]
