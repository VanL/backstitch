def rule_04_default_value(
    value: str | None,
) -> object:
    """Spec: docs/specs/01-contract.md [HIST-04]"""
    return "safe" if value is None else value


def rule_04_default_value_fallback() -> str:
    return "reference"


def rule_04_default_value_nearby_reference(
    value: object | None = None,
) -> object | None:
    return value
