def test_declared_candidate() -> None:
    """Spec: docs/specs/01-core.md [CAND-1]"""
    assert 1 == 1


def test_partially_declared_candidate() -> None:
    """Spec: docs/specs/01-core.md [CAND-1]"""
    assert 1 == 1


def test_untraced_candidate() -> None:
    assert 1 == 1


def test_conflicted_candidate() -> None:
    """Spec: docs/specs/01-core.md [CAND-1]"""
    assert 1 == 1
