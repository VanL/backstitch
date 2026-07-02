"""Sibling repository discovery for target corpus checks.

Spec: docs/specs/02-backstitch-core.md [SC-12]
Spec: docs/specs/03-backstitch-configuration.md [CFG-5], [CFG-6]

Discovery precedence: environment override, then configured
``[target_roots]`` path, then the sibling of the MAIN repository checkout.
The worktree case is the one that breaks in practice ([SC-12]): naive
``<checkout-parent>/<name>`` resolves to ``.worktrees/<name>`` from a linked
worktree, so worktree paths are normalized to the main repository root
before sibling lookup.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from backstitch.settings import BackstitchSettings

_ENV_OVERRIDES = {
    "weft": "BACKSTITCH_WEFT_ROOT",
}


def git_worktree_root(start: Path | None = None) -> Path:
    """Return the root of the current git worktree."""

    start_path = (start or Path.cwd()).resolve()
    try:
        toplevel = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=start_path,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except subprocess.CalledProcessError, FileNotFoundError:
        return start_path
    return Path(toplevel).resolve()


def git_main_repo_root(start: Path | None = None) -> Path:
    """Normalize a worktree checkout path to the main repository root."""

    root = git_worktree_root(start)
    parts = root.parts
    if ".worktrees" in parts:
        index = parts.index(".worktrees")
        return Path(*parts[:index])
    return root


def discover_sibling_repo(
    name: str,
    *,
    anchor: Path | None = None,
    configured_path: str | None = None,
) -> Path | None:
    """Locate a sibling repository directory next to the main repo."""

    env_key = _ENV_OVERRIDES.get(name.lower())
    if env_key:
        override = os.environ.get(env_key)
        if override:
            path = Path(override).expanduser().resolve()
            if path.is_dir():
                return path

    if configured_path:
        path = Path(configured_path).expanduser().resolve()
        if path.is_dir():
            return path

    main_repo = git_main_repo_root(anchor)
    candidate = main_repo.parent / name
    if candidate.is_dir():
        return candidate.resolve()
    return None


def discover_weft(
    *,
    anchor: Path | None = None,
    settings: BackstitchSettings | None = None,
) -> Path | None:
    configured = settings.target_roots.weft if settings is not None else None
    return discover_sibling_repo("weft", anchor=anchor, configured_path=configured)
