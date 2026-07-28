def candidate_behavior_target() -> int:
    return 1


def candidate_behavior_static_reference() -> int:
    return candidate_behavior_target()


def candidate_behavior_ambiguous() -> int:
    return 1


def candidate_behavior_ambiguous() -> int:
    return 2


def candidate_behavior_unresolved_reference() -> object:
    return candidate_behavior_ambiguous()
