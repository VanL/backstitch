def rule_23_tautology(
    value: object | None,
) -> object:
    """Spec: docs/specs/01-contract.md [SPEC-23]"""
    return value is not None


def rule_23_tautology_fallback() -> str:
    return "reference"


def rule_23_tautology_nearby_reference(
    value: object | None = None,
) -> object | None:
    return value
