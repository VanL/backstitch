"""Shared test fixtures.

Spec: docs/specs/02-backstitch-core.md [SC-10]
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Fixture corpora are self-contained mini-projects containing intentionally
# broken code and their own test-shaped files; they are scan targets, never
# collectable tests.
collect_ignore_glob = ["fixtures/*", "acceptance/fixtures/*"]


@pytest.fixture
def repo_root() -> Path:
    """Absolute path to this repository's root."""
    return REPO_ROOT
