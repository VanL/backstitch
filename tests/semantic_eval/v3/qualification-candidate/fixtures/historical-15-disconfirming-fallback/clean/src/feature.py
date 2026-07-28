def rule_15_disconfirming_fallback() -> object:
    """Spec: docs/specs/01-contract.md [HIST-15]"""
    return "ready"


def rule_15_disconfirming_fallback_fallback() -> str:
    return "ready"


def rule_15_disconfirming_fallback_nearby_reference(
    value: object | None = None,
) -> object | None:
    return value
