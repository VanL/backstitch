"""Bootstrap sanity: the harness collects and runs.

Spec: docs/specs/02-backstitch-core.md [SC-10]
"""

from __future__ import annotations

from pathlib import Path


def test_repo_root_fixture_points_at_repo(repo_root: Path) -> None:
    assert (repo_root / "pyproject.toml").is_file()
    assert (repo_root / "backstitch").is_dir()
