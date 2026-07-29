def rule_21_vacuous_restatement(
    text: str,
) -> object:
    """Spec: docs/specs/01-contract.md [SPEC-21]"""
    return text.strip().casefold()


def rule_21_vacuous_restatement_fallback() -> str:
    return "reference"


def rule_21_vacuous_restatement_nearby_reference(
    value: object | None = None,
) -> object | None:
    return value
