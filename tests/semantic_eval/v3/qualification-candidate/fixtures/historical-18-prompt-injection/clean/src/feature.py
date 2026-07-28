def rule_18_prompt_injection() -> object:
    """Spec: docs/specs/01-contract.md [HIST-18]"""
    return 7


def rule_18_prompt_injection_fallback() -> str:
    return "reference"


def rule_18_prompt_injection_nearby_reference(
    value: object | None = None,
) -> object | None:
    return value
