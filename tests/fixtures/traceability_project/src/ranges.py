"""Range, list, and ambiguity reference fixture.

Spec: [CORE.2.1]-[CORE.2.2]

Spec references:
- docs/specifications/01-Core.md [CORE-1], [CORE-2]
"""


def compact_range() -> None:
    # Spec: [CORE.2.1-CORE.2.2]
    return None


def comma_list() -> None:
    # Spec: [CORE-1, CORE-2]
    return None


def ambiguous() -> None:
    # Spec: [DUP-1]
    return None


def bad_range() -> None:
    # Spec: [CORE-1]-[LAYER-1]
    return None


def ghost() -> None:
    # Spec: [CORE-99]
    return None


def prose_reference() -> None:
    # bootstrap and queue binding - see [CORE-3] for details
    return None


def endash_range() -> None:
    # Spec: [CORE.2.1]–[CORE.2.2]
    return None


def indexing_noise(window: list[int]) -> int:
    # shift window[N-1] left; unknown prefix N stays silent at resolution
    return window[0]
