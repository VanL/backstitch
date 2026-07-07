"""Shared helpers for the [SC-10] acceptance probe suite.

Probes are black-box: subprocess invocations asserting exit-code classes,
structured JSON fields, and no tracebacks. The single permitted fake is the
model boundary (probes 8-9), per [SC-10].
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, "-m", "backstitch", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    assert "Traceback" not in result.stderr, result.stderr
    return result


def check_json(
    repo: Path, *extra: str, expect_exit: int | None = None
) -> dict[str, Any]:
    result = run_cli(
        "check",
        "--repo-root",
        str(repo),
        "--format",
        "json",
        *extra,
    )
    if expect_exit is not None:
        assert result.returncode == expect_exit, result.stderr
    return cast(dict[str, Any], json.loads(result.stdout))


@pytest.fixture
def mini_repo(tmp_path: Path) -> Path:
    """A minimal clean corpus the probes mutate per scenario."""

    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "docs/plans").mkdir(parents=True)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "docs/specs/01-p.md").write_text(
        "# P\n\n## One [PR-1]\n\n_Implementation mapping_:\n\n- `pkg/mod.py`\n",
        encoding="utf-8",
    )
    (tmp_path / "pkg/mod.py").write_text(
        '"""Spec: docs/specs/01-p.md [PR-1]"""\n', encoding="utf-8"
    )
    return tmp_path


ROOTS = ("--spec-root", "docs/specs", "--plan-root", "docs/plans", "--code-root", "pkg")
