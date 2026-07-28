def candidate_behavior_duplicate() -> int:
    return 1


def candidate_behavior_duplicate() -> int:
    return 2


def candidate_behavior_declared_reference() -> object:
    """Spec: docs/specs/01-core.md [CAND-1]"""
    return candidate_behavior_duplicate()


def candidate_behavior_partially_declared_reference() -> object:
    """Spec: docs/specs/01-core.md [CAND-1]"""
    return candidate_behavior_duplicate()


def candidate_behavior_untraced_reference() -> object:
    return candidate_behavior_duplicate()


def candidate_behavior_other_reference() -> object:
    """Spec: docs/specs/01-core.md [CAND-1]"""
    return candidate_behavior_duplicate()
