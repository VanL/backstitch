def rule_05_clamp_upper_bound(
    value: int,
    upper: int,
) -> object:
    """Spec: docs/specs/01-contract.md [HIST-05]"""
    return min(value, upper)


def rule_05_clamp_upper_bound_fallback() -> str:
    return "reference"


def rule_05_clamp_upper_bound_nearby_reference(
    value: object | None = None,
) -> object | None:
    return value
