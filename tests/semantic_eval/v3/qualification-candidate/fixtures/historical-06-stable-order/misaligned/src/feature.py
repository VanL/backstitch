def rule_06_stable_order(
    names: list[str],
) -> object:
    """Spec: docs/specs/01-contract.md [HIST-06]"""
    return sorted(names, reverse=True)


def rule_06_stable_order_fallback() -> str:
    return "reference"


def rule_06_stable_order_nearby_reference(
    value: object | None = None,
) -> object | None:
    return value
