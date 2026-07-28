"""Out-of-packet decoy fixture."""


def decoy_result() -> int:
    """Spec: docs/specs/01-Eval.md [EVAL-8]"""
    return 8


# This module-level marker is outside the mapped function's symbol snippet.
DECOY_TEXT = "harmless decoy"
