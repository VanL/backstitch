"""Shared test fixtures.

Spec: docs/specs/02-backstitch-core.md [SC-10]
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Protocol

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Fixture corpora are self-contained mini-projects containing intentionally
# broken code and their own test-shaped files; they are scan targets, never
# collectable tests.
collect_ignore_glob = ["fixtures/*", "acceptance/fixtures/*"]


class _IniConfig(Protocol):
    def getini(self, name: str) -> Any: ...


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the repository-owned live-test policy ([SC-7], [SC-10])."""

    parser.addini(
        "run_live_llm",
        "run tests marked live_llm by default",
        type="bool",
        default=False,
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip live tests unless pytest config or an explicit lane enables them."""

    if _live_llm_enabled(config):
        return

    skipped = pytest.mark.skip(
        reason=(
            "live LLM tests disabled; set run_live_llm=true or BACKSTITCH_LIVE_LLM=1"
        )
    )
    for item in items:
        if item.get_closest_marker("live_llm") is not None:
            item.add_marker(skipped)


def _live_llm_enabled(config: _IniConfig) -> bool:
    """Resolve every ini/environment enablement combination."""

    return bool(config.getini("run_live_llm")) or (
        os.environ.get("BACKSTITCH_LIVE_LLM") == "1"
    )


@pytest.fixture
def repo_root() -> Path:
    """Absolute path to this repository's root."""
    return REPO_ROOT
