"""Sibling discovery contract: worktree-safe, env/config precedence.

Spec: docs/specs/02-backstitch-core.md [SC-12]
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from backstitch.settings import BackstitchSettings, TargetRootSettings
from backstitch.target_roots import (
    discover_weft,
    git_main_repo_root,
)


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def worktree_layout(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A real main repo, a linked worktree under .worktrees, and a sibling."""

    main = tmp_path / "mainrepo"
    main.mkdir()
    _git("init", "-q", cwd=main)
    _git("config", "user.email", "t@example.com", cwd=main)
    _git("config", "user.name", "t", cwd=main)
    (main / "README.md").write_text("x\n", encoding="utf-8")
    _git("add", "README.md", cwd=main)
    _git("commit", "-q", "-m", "init", cwd=main)
    worktree = main / ".worktrees" / "feature"
    _git("worktree", "add", "-q", str(worktree), "-b", "feature", cwd=main)
    sibling = tmp_path / "weft"
    sibling.mkdir()
    return main, worktree, sibling


def test_sibling_discovery_from_linked_worktree(
    worktree_layout: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # [SC-12]: from a linked worktree, naive `parent/weft` would resolve to
    # `.worktrees/weft`; discovery must find the MAIN checkout's sibling.
    main, worktree, sibling = worktree_layout
    monkeypatch.delenv("BACKSTITCH_WEFT_ROOT", raising=False)
    assert not (worktree.parent / "weft").exists()
    found = discover_weft(anchor=worktree)
    assert found == sibling.resolve()


def test_main_repo_root_normalizes_worktree_paths(
    worktree_layout: tuple[Path, Path, Path],
) -> None:
    main, worktree, _sibling = worktree_layout
    assert git_main_repo_root(worktree) == main.resolve()
    assert git_main_repo_root(main) == main.resolve()


def test_env_override_beats_sibling(
    worktree_layout: tuple[Path, Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _main, worktree, _sibling = worktree_layout
    override = tmp_path / "elsewhere-weft"
    override.mkdir()
    monkeypatch.setenv("BACKSTITCH_WEFT_ROOT", str(override))
    assert discover_weft(anchor=worktree) == override.resolve()


def test_config_override_beats_sibling(
    worktree_layout: tuple[Path, Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _main, worktree, _sibling = worktree_layout
    monkeypatch.delenv("BACKSTITCH_WEFT_ROOT", raising=False)
    configured = tmp_path / "configured-weft"
    configured.mkdir()
    settings = BackstitchSettings(
        target_roots=TargetRootSettings(weft=str(configured))
    )
    assert discover_weft(anchor=worktree, settings=settings) == configured.resolve()


def test_env_beats_config(
    worktree_layout: tuple[Path, Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _main, worktree, _sibling = worktree_layout
    env_dir = tmp_path / "env-weft"
    env_dir.mkdir()
    config_dir = tmp_path / "config-weft"
    config_dir.mkdir()
    monkeypatch.setenv("BACKSTITCH_WEFT_ROOT", str(env_dir))
    settings = BackstitchSettings(
        target_roots=TargetRootSettings(weft=str(config_dir))
    )
    assert discover_weft(anchor=worktree, settings=settings) == env_dir.resolve()


def test_missing_everything_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BACKSTITCH_WEFT_ROOT", raising=False)
    lonely = tmp_path / "lonely"
    lonely.mkdir()
    _git("init", "-q", cwd=lonely)
    assert discover_weft(anchor=lonely) is None
