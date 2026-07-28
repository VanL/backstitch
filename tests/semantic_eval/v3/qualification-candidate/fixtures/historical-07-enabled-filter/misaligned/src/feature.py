def rule_07_enabled_filter(
    records: list[dict[str, bool]],
) -> object:
    """Spec: docs/specs/01-contract.md [HIST-07]"""
    return [item for item in records if not item["enabled"]]


def rule_07_enabled_filter_fallback() -> str:
    return "reference"


def rule_07_enabled_filter_nearby_reference(
    value: object | None = None,
) -> object | None:
    return value
