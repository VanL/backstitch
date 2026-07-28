def rule_01_literal_reversal() -> object:
    """Spec: docs/specs/01-contract.md [HIST-01]"""
    return "enabled"


def rule_01_literal_reversal_fallback() -> str:
    return "reference"


def rule_01_literal_reversal_nearby_reference(
    value: object | None = None,
) -> object | None:
    return value
