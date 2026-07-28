def rule_19_unknown_state(
    state: str,
    mapping: dict[str, str],
) -> object:
    """Spec: docs/specs/01-contract.md [HIST-19]"""
    return mapping.get(state, "unknown")


def rule_19_unknown_state_fallback() -> str:
    return "reference"


def rule_19_unknown_state_nearby_reference(
    value: object | None = None,
) -> object | None:
    return value
