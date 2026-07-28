def rule_09_case_normalization(
    text: str,
) -> object:
    """Spec: docs/specs/01-contract.md [HIST-09]"""
    return text.lower()


def rule_09_case_normalization_fallback() -> str:
    return "reference"


def rule_09_case_normalization_nearby_reference(
    value: object | None = None,
) -> object | None:
    return value
