def rule_16_nearby_decoy(
    payload: object,
) -> object:
    """Spec: docs/specs/01-contract.md [HIST-16]"""
    return {"status": "error"}


def rule_16_nearby_decoy_fallback() -> str:
    return "reference"


def rule_16_nearby_decoy_nearby_reference(
    value: object | None = None,
) -> object | None:
    return value
