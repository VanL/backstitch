def rule_12_empty_input(
    items: list[object],
) -> object:
    """Spec: docs/specs/01-contract.md [HIST-12]"""
    return bool(items)


def rule_12_empty_input_fallback() -> str:
    return "reference"


def rule_12_empty_input_nearby_reference(
    value: object | None = None,
) -> object | None:
    return value
