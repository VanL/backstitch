"""Hermetic behavior tests for the coalescing session-start gate."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _command(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def _git(repo: Path, *args: str) -> str:
    result = _command("git", *args, cwd=repo)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _repository(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Backstitch Tests")
    _git(repo, "config", "user.email", "tests@example.invalid")
    (repo / "bin").mkdir()
    (repo / "docs").mkdir()
    shutil.copy2(ROOT / "bin" / "coalesce-check", repo / "bin" / "coalesce-check")
    (repo / "docs" / "coalescing.md").write_text("# Coalescing\n", encoding="utf-8")
    (repo / "docs" / "lessons.md").write_text("# Lessons\n", encoding="utf-8")
    (repo / "published.txt").write_text("published\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "published baseline")
    published = _git(repo, "rev-parse", "HEAD")

    remote = tmp_path / "remote.git"
    remote.mkdir()
    _git(remote, "init", "--bare")
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-u", "origin", "main")

    (repo / "local.txt").write_text("local only\n", encoding="utf-8")
    _git(repo, "add", "local.txt")
    _git(repo, "commit", "-m", "local-only evidence")
    local_only = _git(repo, "rev-parse", "HEAD")
    return repo, published, local_only


def _run_gate(repo: Path) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("COALESCE_SIBLING_ROOT", None)
    return subprocess.run(
        [sys.executable, str(repo / "bin" / "coalesce-check")],
        cwd=repo,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def test_coalesce_check_reports_local_only_and_foreign_without_failing(
    tmp_path: Path,
) -> None:
    repo, _published, local_only = _repository(tmp_path)
    foreign = "f" * 40
    (repo / "docs" / "coalescing.md").write_text(
        "# Coalescing\n\n"
        f"Local claim `{local_only}` with cue `git show {local_only}:local.txt`.\n"
        f"Foreign provenance from taut `{foreign}`.\n",
        encoding="utf-8",
    )
    (repo / "docs" / "lessons.md").write_text(
        "# Lessons\n\n"
        "## 2026-08-01: Leading date\n\n"
        "## Trailing date (2026-08-02)\n\n"
        "## Undated heading\n",
        encoding="utf-8",
    )

    result = _run_gate(repo)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "local-only pin (1)" in result.stdout
    assert f"{local_only}  [not in origin/main" in result.stdout
    assert "foreign claim (1)" in result.stdout
    assert f"{foreign} @ taut" in result.stdout
    assert "1 retrieval cue(s)" in result.stdout
    assert (
        "lessons dated H2 sections: 2 (1 leading-date, 1 trailing-date)"
        in result.stdout
    )
    assert "all cues resolve" in result.stdout


def test_coalesce_check_fails_for_unattributed_and_broken_retrieval_cues(
    tmp_path: Path,
) -> None:
    repo, published, _local_only = _repository(tmp_path)
    unresolved = "e" * 40
    (repo / "docs" / "coalescing.md").write_text(
        f"Claim `{unresolved}`.\nBroken cue `git show {published}:missing.txt`.\n",
        encoding="utf-8",
    )

    result = _run_gate(repo)

    assert result.returncode == 1
    assert "BROKEN (2)" in result.stdout
    assert (
        f"`{unresolved}` resolves nowhere here and names no repository" in result.stdout
    )
    assert (
        f"cue `git show {published}:missing.txt` does not resolve here" in result.stdout
    )
