"""LgEval label-graph export, so the MathSeer comparison is runnable."""

from pdfmath.mathml.lgeval import to_label_graph
from pdfmath.tree.nodes import (Fraction, Identifier, LargeOperator, Number, Operator,
                                Provenance, Radical, Row, SubSup, UnderOver)


def _relations(lg: str) -> set[tuple[str, str]]:
    out = set()
    for line in lg.splitlines():
        if line.startswith("R,"):
            _, a, b, label, _ = [p.strip() for p in line.split(",")]
            out.add((label, f"{a}->{b}"))
    return {r[0] for r in out}


def _labels(lg: str) -> list[str]:
    return [line.split(",")[2].strip() for line in lg.splitlines()
            if line.startswith("O,")]


def test_scripts_use_crohme_relations():
    tree = SubSup(children=[Identifier(text="x"), Identifier(text="i"),
                            Number(text="2")])
    lg = to_label_graph(tree)
    assert _relations(lg) == {"Sub", "Sup"}
    assert set(_labels(lg)) == {"x", "i", "2"}


def test_fraction_becomes_above_and_below_a_bar():
    tree = Fraction(children=[Identifier(text="x"), Identifier(text="y")])
    lg = to_label_graph(tree)
    assert _relations(lg) == {"Above", "Below"}
    assert "-" in _labels(lg)


def test_radical_uses_inside():
    tree = Radical(children=[Identifier(text="y")])
    assert _relations(to_label_graph(tree)) == {"Inside"}


def test_limits_are_above_and_below_the_operator():
    tree = UnderOver(children=[LargeOperator(text="∑", display=True),
                               Identifier(text="i"), Identifier(text="n")],
                     has_under=True, has_over=True)
    assert _relations(to_label_graph(tree)) == {"Above", "Below"}


def test_row_becomes_a_right_chain():
    tree = Row(children=[Identifier(text="a"), Operator(text="+"),
                         Identifier(text="b")])
    lg = to_label_graph(tree)
    assert _relations(lg) == {"Right"}
    assert lg.count("R,") == 2


def test_primitive_ids_are_carried_through():
    leaf = Identifier(text="x")
    leaf.prov = Provenance([7, 9], [], None, 1.0, {}, "leaf")
    lg = to_label_graph(Row(children=[leaf]))
    assert "7, 9" in lg


def test_comment_lines_are_prefixed():
    lg = to_label_graph(Identifier(text="x"), "note")
    assert lg.splitlines()[0] == "# note"
