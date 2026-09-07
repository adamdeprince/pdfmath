"""Spoken output.

The engine itself is MathJax's and is not retested here; what is tested is the bridge to
it, and the one place we deliberately change the MathML before speaking.
"""

import pytest

from pdfmath.mathml.serializer import to_mathml
from pdfmath.speech import engine
from pdfmath.speech.engine import UNKNOWN_PHRASE, speak, speech_mathml
from pdfmath.tree.nodes import (Fraction, Identifier, Operator, Radical, Row, SubSup,
                                Number, Text, Unknown)

needs_sre = pytest.mark.skipif(not engine.available(),
                               reason="speech-rule-engine is not installed")


def it(t):
    return Identifier(text=t, mathvariant="italic")


def test_an_unnamed_glyph_is_announced_rather_than_read_as_a_symbol():
    """``□`` is not a placeholder to a reader: it is the d'Alembertian.

    Speaking it as "white square" would turn our own ignorance into a plausible piece of
    mathematics, with nothing left in the audio to check it against.
    """
    tree = Row(children=[it("x"), Operator(text="+"),
                         Unknown(text="", reason="no glyph name")])
    assert "□" in to_mathml(tree)
    prepared = speech_mathml(tree)
    assert "□" not in prepared
    assert UNKNOWN_PHRASE in prepared


def test_a_glyph_we_can_name_is_left_for_the_engine_to_speak():
    """Knowing the character but not its role is still worth speaking as the character."""
    tree = Row(children=[it("x"), Unknown(text="ℶ", reason="unclassified")])
    assert "ℶ" in speech_mathml(tree)
    assert UNKNOWN_PHRASE not in speech_mathml(tree)


def test_preparing_for_speech_does_not_disturb_the_tree():
    u = Unknown(text="", reason="no glyph name")
    tree = Row(children=[it("x"), u])
    speech_mathml(tree)
    assert tree.children[1] is u


def test_measured_spacing_is_not_spoken():
    """``mspace`` is read aloud as "empty", so a ``\\quad`` becomes a spoken word.

    The gaps are worth recording -- they are how the parser knows what it knows -- but
    speech takes its pauses from the rule set, not from the page.
    """
    from pdfmath.tree.nodes import Space
    tree = Row(children=[it("x"), Space(width_em=1.0), Number(text="1")])
    assert "mspace" in to_mathml(tree)
    assert "mspace" not in speech_mathml(tree)


def test_an_unknown_rule_set_is_refused_before_the_engine_starts():
    with pytest.raises(engine.SpeechError, match="unknown rule set"):
        engine.speak_batch(["<math></math>"], domain="esperanto")


def test_the_install_hint_names_something_runnable(monkeypatch):
    """The hint is only a hint when something is actually missing.

    It has to name a directory the reader can create, because a pip install has nowhere
    to put sixty megabytes of JavaScript and there may be no checkout in sight.
    """
    monkeypatch.setattr(engine, "_engine_home", lambda: None)
    hint = engine.install_hint()
    assert "npm install speech-rule-engine" in hint
    assert "PDFMATH_SRE_HOME" in hint


def test_the_hint_says_so_when_nothing_is_missing(monkeypatch):
    monkeypatch.setattr(engine.shutil, "which", lambda name: "/usr/bin/node")
    monkeypatch.setattr(engine, "_engine_home", lambda: "/somewhere")
    assert engine.install_hint() == "speech is available"


def test_the_bridge_travels_with_the_package():
    """A pip install has no tools/sre, so speak.js ships inside pdfmath itself."""
    import os
    assert os.path.exists(engine._bridge())
    assert os.path.basename(engine._bridge()) == "speak.js"


def test_an_empty_batch_needs_no_engine():
    assert engine.speak_batch([]) == []


@needs_sre
def test_clearspeak_reads_a_fraction_the_way_a_person_would():
    tree = Fraction(children=[
        Row(children=[it("x"), Operator(text="+"), Number(text="1")]), it("y")])
    said = speak(tree)
    assert "fraction" in said and "x plus 1" in said


@needs_sre
def test_mathspeak_brackets_what_clearspeak_leaves_implicit():
    tree = Fraction(children=[it("x"), it("y")])
    assert speak(tree, domain="mathspeak") == "StartFraction x Over y EndFraction"
    assert speak(tree, domain="clearspeak") == "x over y"


@needs_sre
def test_verbosity_shortens_the_bracketing():
    tree = Radical(children=[Fraction(children=[it("x"), it("y")])])
    assert len(speak(tree, domain="mathspeak", style="sbrief")) < \
           len(speak(tree, domain="mathspeak", style="default"))


@needs_sre
def test_ssml_carries_the_pauses_a_synthesiser_needs():
    out = speak(Fraction(children=[it("x"), it("y")]), markup="ssml")
    assert "<speak" in out and "prosody" in out


@needs_sre
def test_the_announcement_actually_reaches_the_speech():
    tree = Row(children=[it("x"), Operator(text="+"),
                         Unknown(text="", reason="no glyph name")])
    said = speak(tree)
    assert UNKNOWN_PHRASE in said
    assert "square" not in said


@needs_sre
def test_a_batch_speaks_in_order():
    trees = [it("x"), Fraction(children=[it("a"), it("b")]), Number(text="42")]
    said = engine.speak_batch([to_mathml(t, indent=False) for t in trees])
    assert said == ["x", "a over b", "42"]
