def rule_13_fallback_selection(
    primary: object | None,
    fallback: object,
) -> object:
    """Spec: docs/specs/01-contract.md [HIST-13]"""
    return fallback if primary is None else primary


def rule_13_fallback_selection_fallback() -> str:
    return "reference"


def rule_13_fallback_selection_nearby_reference(
    value: object | None = None,
) -> object | None:
    return value
