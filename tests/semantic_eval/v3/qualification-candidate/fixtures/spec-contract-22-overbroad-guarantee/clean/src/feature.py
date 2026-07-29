def rule_22_overbroad_guarantee(
    score: int,
) -> object:
    """Spec: docs/specs/01-contract.md [SPEC-22]"""
    return max(0, min(score, 100))


def rule_22_overbroad_guarantee_fallback() -> str:
    return "reference"


def rule_22_overbroad_guarantee_nearby_reference(
    value: object | None = None,
) -> object | None:
    return value
