"""Fixture tests for the runtime.

Spec: docs/specifications/01-Core.md [CORE-1]
"""

from src.runtime import Runtime


def test_frobnicate() -> None:
    """Spec: [CORE-1]"""
    assert Runtime().frobnicate() == 1
