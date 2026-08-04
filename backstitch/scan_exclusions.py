"""Pure scan-exclusion matching for current and historical source adapters.

Spec: docs/specs/02-backstitch-core.md [SC-17]
Spec: docs/specs/05-backstitch-invariants.md [INV-11]
Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-8.2]
"""

from __future__ import annotations

from fnmatch import fnmatch


def is_excluded(rel_path: str, excludes: tuple[str, ...]) -> bool:
    """Return whether one normalized repository path matches an exclusion."""

    normalized = rel_path.replace("\\", "/")
    parts = set(normalized.split("/"))
    for pattern in excludes:
        if fnmatch(normalized, pattern) or fnmatch(normalized, f"**/{pattern}"):
            return True
        if pattern in parts:
            return True
        if normalized.startswith(f"{pattern}/") or normalized == pattern:
            return True
    return False
