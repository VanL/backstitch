"""Subprocess CLI contract: exit codes, output modes, no tracebacks.

Spec: docs/specs/02-backstitch-core.md [SC-5]
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CLEAN = FIXTURES / "clean_project"
BROKEN = FIXTURES / "traceability_project"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "backstitch", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def check_clean(*extra: str) -> subprocess.CompletedProcess[str]:
    return run_cli(
        "check",
        "--repo-root",
        str(CLEAN),
        "--spec-root",
        "docs/specs",
        "--plan-root",
        "docs/plans",
        "--code-root",
        "pkg",
        *extra,
    )


def test_clean_repo_exits_zero() -> None:
    result = check_clean()
    assert result.returncode == 0, result.stderr
    assert "0 errors" in result.stdout
    assert "Traceback" not in result.stderr


def test_broken_repo_exits_one() -> None:
    result = run_cli(
        "check",
        "--repo-root",
        str(BROKEN),
        "--spec-root",
        "docs/specifications",
        "--code-root",
        "src",
        "--code-root",
        "tests",
    )
    assert result.returncode == 1, result.stderr
    assert "Traceback" not in result.stderr


def test_bad_repo_root_exits_two() -> None:
    result = run_cli("check", "--repo-root", "/nonexistent-backstitch-xyz")
    assert result.returncode == 2
    assert "backstitch: error:" in result.stderr
    assert "Traceback" not in result.stderr


def test_unknown_profile_exits_two() -> None:
    result = run_cli("check", "--repo-root", str(CLEAN), "--profile", "nope")
    assert result.returncode == 2
    assert "unknown profile" in result.stderr


def test_json_format_and_output_file(tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    result = check_clean("--format", "json", "--output", str(out))
    assert result.returncode == 0, result.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["summary"]["errors"] == 0


def test_check_unwritable_output_exits_two(tmp_path: Path) -> None:
    target = tmp_path / "no-such-dir" / "report.json"
    result = check_clean("--output", str(target))
    assert result.returncode == 2
    assert "backstitch: error:" in result.stderr
    assert "Traceback" not in result.stderr
