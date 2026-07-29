def rule_25_nondiscriminating_prose(
    state: str,
) -> object:
    """Spec: docs/specs/01-contract.md [SPEC-25]"""
    return "allow" if state == "ready" else "deny"


def rule_25_nondiscriminating_prose_fallback() -> str:
    return "reference"


def rule_25_nondiscriminating_prose_nearby_reference(
    value: object | None = None,
) -> object | None:
    return value
