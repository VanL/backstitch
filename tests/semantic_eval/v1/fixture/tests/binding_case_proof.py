"""Binding proof for the evaluation invariant."""

from backstitch.binding_case import binding_value


def test_binding_value() -> None:
    """Tests-invariant: [INV.EVAL.1]"""
    assert binding_value() == 7
