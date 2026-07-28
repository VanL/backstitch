def declared_candidate() -> int:
    """Spec: docs/specs/01-core.md [CAND-1]"""
    return 0


def accepted_declared_candidate() -> int:
    """Spec: docs/specs/01-core.md [CAND-1]"""
    return 1


def partially_declared_candidate() -> int:
    """Spec: docs/specs/01-core.md [CAND-1]"""
    return 1


def untraced_candidate() -> int:
    return 1


def conflicted_candidate() -> int:
    """Spec: docs/specs/01-core.md [CAND-1]"""
    return 1


def candidate_fixture_housekeeping() -> str:
    """Return fixture metadata; this is not product behavior."""
    return "candidate-fixture"
