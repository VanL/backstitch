def rule_14_bounded_prefix(
    items: list[object],
    limit: int,
) -> object:
    """Spec: docs/specs/01-contract.md [HIST-14]"""
    return items[: max(0, limit - 1)]


def rule_14_bounded_prefix_fallback() -> str:
    return "reference"


def rule_14_bounded_prefix_nearby_reference(
    value: object | None = None,
) -> object | None:
    return value
