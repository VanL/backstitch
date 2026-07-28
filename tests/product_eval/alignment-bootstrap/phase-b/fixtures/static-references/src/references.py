def candidate() -> int:
    return 1


def declared_reference() -> int:
    """Spec: docs/specs/01-core.md [CAND-1]"""
    return candidate()


def partially_declared_reference() -> int:
    """Spec: docs/specs/01-core.md [CAND-1]"""
    return candidate()


def untraced_disconfirming_reference() -> int:
    return candidate() + 1


def conflicted_reference() -> int:
    """Spec: docs/specs/01-core.md [CAND-1]
    Spec: docs/specs/01-core.md [CAND-1]
    """
    return candidate()
