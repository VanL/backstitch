def rule_02_branch_polarity(
    enabled: bool,
) -> object:
    """Spec: docs/specs/01-contract.md [HIST-02]"""
    return "allow" if enabled else "deny"


def rule_02_branch_polarity_fallback() -> str:
    return "reference"


def rule_02_branch_polarity_nearby_reference(
    value: object | None = None,
) -> object | None:
    return value
