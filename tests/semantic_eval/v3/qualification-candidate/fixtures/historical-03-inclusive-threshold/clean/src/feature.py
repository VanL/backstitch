def rule_03_inclusive_threshold(
    value: int,
    limit: int,
) -> object:
    """Spec: docs/specs/01-contract.md [HIST-03]"""
    return value >= limit


def rule_03_inclusive_threshold_fallback() -> str:
    return "reference"


def rule_03_inclusive_threshold_nearby_reference(
    value: object | None = None,
) -> object | None:
    return value
