def rule_08_timeout_units(
    seconds: int,
) -> object:
    """Spec: docs/specs/01-contract.md [HIST-08]"""
    return seconds * 1000


def rule_08_timeout_units_fallback() -> str:
    return "reference"


def rule_08_timeout_units_nearby_reference(
    value: object | None = None,
) -> object | None:
    return value
