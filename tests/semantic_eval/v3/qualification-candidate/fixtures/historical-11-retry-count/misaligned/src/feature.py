from collections.abc import Callable


def rule_11_retry_count(
    maximum_attempts: int,
    attempt: Callable[[], object],
) -> object:
    """Spec: docs/specs/01-contract.md [HIST-11]"""
    results = []
    for _ in range(maximum_attempts + 1):
        results.append(attempt())
    return results


def rule_11_retry_count_fallback() -> str:
    return "reference"


def rule_11_retry_count_nearby_reference(
    value: object | None = None,
) -> object | None:
    return value
