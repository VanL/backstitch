from collections.abc import Callable


def rule_20_exception_propagation(
    payload: str,
    parser: Callable[[str], object],
) -> object:
    """Spec: docs/specs/01-contract.md [HIST-20]"""
    try:
        return parser(payload)
    except ValueError:
        return None


def rule_20_exception_propagation_fallback() -> str:
    return "reference"


def rule_20_exception_propagation_nearby_reference(
    value: object | None = None,
) -> object | None:
    return value
