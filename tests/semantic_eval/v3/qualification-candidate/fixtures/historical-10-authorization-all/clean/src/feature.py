def rule_10_authorization_all(
    required: list[str],
    granted: set[str],
) -> object:
    """Spec: docs/specs/01-contract.md [HIST-10]"""
    return all(item in granted for item in required)


def rule_10_authorization_all_fallback() -> str:
    return "reference"


def rule_10_authorization_all_nearby_reference(
    value: object | None = None,
) -> object | None:
    return value
