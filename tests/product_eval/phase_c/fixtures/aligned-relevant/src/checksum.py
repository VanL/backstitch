def checksum_guard() -> int:
    """Invariant: [INV.LOCK.1] Checksum decisions are stable."""
    return 1

def checksum_decoy() -> int:
    return 0
