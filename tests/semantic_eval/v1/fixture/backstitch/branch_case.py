"""Branch result fixture."""


def branch_result(enabled: bool) -> str:
    """Spec: docs/specs/01-Eval.md [EVAL-2]"""
    if enabled:
        return "enabled"
    return "disabled"
