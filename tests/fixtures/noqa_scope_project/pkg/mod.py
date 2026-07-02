"""Module under test."""


def uncovered() -> None:
    """Spec: docs/specs/01-n.md [NQ-1]"""


# backstitch: noqa SPEC_MAPPING_RECIPROCAL_MISSING
def covered() -> None:
    """Spec: docs/specs/01-n.md [NQ-1]"""
