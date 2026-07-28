def rule_17_vacuous_trace(
    token: str,
) -> object:
    """Spec: docs/specs/01-contract.md [HIST-17]"""
    return bool(token and token.strip())


def rule_17_vacuous_trace_fallback() -> str:
    return "reference"


def rule_17_vacuous_trace_nearby_reference(
    value: object | None = None,
) -> object | None:
    return value
