"""Fixture runtime module.

Spec: docs/specifications/01-Core.md [CORE-1]
"""


class Runtime:
    """Runtime owner for frobnication.

    Spec: [CORE-1]
    """

    def frobnicate(self) -> int:
        """Frobnicate once.

        Spec: docs/specifications/01-Core.md [CORE-1]
        """
        return 1

    def save(self) -> None:
        # Spec: docs/specifications/01-Core.md [CORE-2]
        return None


def plan_shards() -> None:
    # Spec: docs/specifications/01A-Core_Planned.md [CORE-P1]
    return None


def broad_reader() -> None:
    """Reads the whole core spec without naming a section.

    Spec: docs/specifications/01-Core.md
    """
    return None


def read_reference_docs() -> None:
    """Broad reference used for warning tests.

    Spec: docs/specifications/01-Core.md#persistence-rules-core-2
    """
    return None
