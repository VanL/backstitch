#!/usr/bin/env python3
"""Repo-local release helper for Backstitch maintainers."""

from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final, Literal
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
PYPROJECT_PATH: Final[Path] = PROJECT_ROOT / "pyproject.toml"
PACKAGE_INIT_PATH: Final[Path] = PROJECT_ROOT / "backstitch" / "__init__.py"
UV_LOCK_PATH: Final[Path] = PROJECT_ROOT / "uv.lock"
RELEASE_GATE_WORKFLOW: Final[str] = ".github/workflows/release-gate.yml"
GITHUB_API_BASE: Final[str] = "https://api.github.com"
PYPI_API_BASE: Final[str] = "https://pypi.org/pypi"
HTTP_TIMEOUT_SECONDS: Final[float] = 10.0
VERSION_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\d+\.\d+\.\d+$")
PYPROJECT_VERSION_PATTERN: Final[re.Pattern[str]] = re.compile(
    r'(?m)^version = "([^"]+)"$'
)
PACKAGE_INIT_VERSION_PATTERN: Final[re.Pattern[str]] = re.compile(
    r'(?m)^__version__(?::[^=]+)?\s*=\s*"([^"]+)"$'
)
PENDING_RELEASE_COMMIT: Final[str] = "<release-commit>"

HERMETIC_TEST_COMMAND: Final[tuple[str, ...]] = (
    "uv",
    "run",
    "pytest",
    "tests",
    "-q",
    "-m",
    "not live_llm",
)
LIVE_LLM_TEST_COMMAND: Final[tuple[str, ...]] = (
    "uv",
    "run",
    "pytest",
    "tests/live/test_live_llm.py",
    "-q",
)
RUFF_CHECK_COMMAND: Final[tuple[str, ...]] = (
    "uv",
    "run",
    "ruff",
    "check",
    "backstitch",
    "tests",
    "bin",
)
RUFF_FORMAT_COMMAND: Final[tuple[str, ...]] = (
    "uv",
    "run",
    "ruff",
    "format",
    "--check",
    "backstitch",
    "bin",
    ".github/scripts",
    "tests/test_release_script.py",
    "tests/test_release_workflow.py",
    "tests/test_release_workflow_gate.py",
)
MYPY_COMMAND: Final[tuple[str, ...]] = (
    "uv",
    "run",
    "mypy",
    "backstitch",
    "bin/release.py",
    "--config-file",
    "pyproject.toml",
)
SELF_CORPUS_COMMAND: Final[tuple[str, ...]] = (
    "uv",
    "run",
    "backstitch",
    "check",
    "--repo-root",
    ".",
)
VERSION_SMOKE_COMMAND: Final[tuple[str, ...]] = (
    "uv",
    "run",
    "backstitch",
    "--version",
)
PRECHECK_ENV_OVERRIDES: Final[dict[str, str]] = {"PYTEST_ADDOPTS": "-x --maxfail=1"}
TagAction = Literal[
    "create",
    "push_local",
    "replace_local",
    "replace_remote",
    "reuse_remote",
]


@dataclass(frozen=True)
class ReleaseTarget:
    """Release metadata for one publishable package in this repository."""

    key: str
    package_name: str
    display_name: str
    package_dir: Path
    pyproject_path: Path
    version_path: Path
    release_workflow: str
    github_release_enabled: bool = True

    def tag_name(self, version: str) -> str:
        """Return the Git tag used to release this package version."""

        return f"v{version}"


@dataclass(frozen=True)
class CommandStep:
    """One command executed by the release helper."""

    command: tuple[str, ...]
    cwd: Path = PROJECT_ROOT
    env_overrides: dict[str, str] | None = None


@dataclass(frozen=True)
class ReleaseState:
    """Observed publication and tag state for a package version."""

    target: ReleaseTarget
    version: str
    tag_name: str
    github_release_exists: bool
    pypi_release_exists: bool
    local_tag_commit: str | None
    remote_tag_commit: str | None

    @property
    def published(self) -> bool:
        """Whether the version was externally published."""

        return self.github_release_exists or self.pypi_release_exists


ROOT_RELEASE_TARGET: Final[ReleaseTarget] = ReleaseTarget(
    key="core",
    package_name="backstitch",
    display_name="backstitch",
    package_dir=PROJECT_ROOT,
    pyproject_path=PYPROJECT_PATH,
    version_path=PACKAGE_INIT_PATH,
    release_workflow=RELEASE_GATE_WORKFLOW,
)


def validate_version(version: str) -> str:
    """Validate the explicit release version."""

    normalized = version.strip()
    if not VERSION_PATTERN.fullmatch(normalized):
        raise ValueError("Version must use X.Y.Z format, for example: 0.2.0")
    return normalized


def _extract_version(
    path: Path,
    pattern: re.Pattern[str],
    *,
    label: str,
) -> str:
    text = path.read_text(encoding="utf-8")
    match = pattern.search(text)
    if match is None:
        raise RuntimeError(f"Could not find version in {label}: {path}")
    return match.group(1)


def read_current_version(
    *,
    pyproject_path: Path = PYPROJECT_PATH,
    version_path: Path = PACKAGE_INIT_PATH,
) -> str:
    """Read and verify the root package version."""

    pyproject_version = _extract_version(
        pyproject_path,
        PYPROJECT_VERSION_PATTERN,
        label="pyproject.toml",
    )
    package_version = _extract_version(
        version_path,
        PACKAGE_INIT_VERSION_PATTERN,
        label="backstitch/__init__.py",
    )
    if pyproject_version != package_version:
        raise RuntimeError(
            "Version mismatch between pyproject.toml "
            f"({pyproject_version}) and backstitch/__init__.py "
            f"({package_version})"
        )
    return pyproject_version


def read_target_version(target: ReleaseTarget = ROOT_RELEASE_TARGET) -> str:
    """Read the current version for the target package."""

    return read_current_version(
        pyproject_path=target.pyproject_path,
        version_path=target.version_path,
    )


def _replace_version(
    text: str,
    pattern: re.Pattern[str],
    version: str,
    *,
    label: str,
) -> str:
    updated_text, count = pattern.subn(
        lambda match: match.group(0).replace(match.group(1), version),
        text,
        count=1,
    )
    if count != 1:
        raise RuntimeError(f"Expected one version assignment in {label}, found {count}")
    return updated_text


def write_version_files(
    version: str,
    *,
    pyproject_path: Path = PYPROJECT_PATH,
    version_path: Path = PACKAGE_INIT_PATH,
) -> None:
    """Update the canonical package version files together."""

    normalized = validate_version(version)
    pyproject_text = pyproject_path.read_text(encoding="utf-8")
    version_text = version_path.read_text(encoding="utf-8")

    updated_pyproject = _replace_version(
        pyproject_text,
        PYPROJECT_VERSION_PATTERN,
        normalized,
        label="pyproject.toml",
    )
    updated_version_file = _replace_version(
        version_text,
        PACKAGE_INIT_VERSION_PATTERN,
        normalized,
        label="backstitch/__init__.py",
    )

    pyproject_path.write_text(updated_pyproject, encoding="utf-8")
    version_path.write_text(updated_version_file, encoding="utf-8")


def write_target_version(
    target: ReleaseTarget,
    version: str,
) -> None:
    """Update the version source files for the release target."""

    write_version_files(
        version,
        pyproject_path=target.pyproject_path,
        version_path=target.version_path,
    )


def _format_command(command: tuple[str, ...]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def _display_path(path: Path) -> str:
    """Return a stable display path for logs and errors."""

    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _release_file_paths(
    target: ReleaseTarget = ROOT_RELEASE_TARGET,
) -> tuple[Path, ...]:
    """Return tracked files the helper may update for a release."""

    return (target.pyproject_path, target.version_path, UV_LOCK_PATH)


def _release_file_args(target: ReleaseTarget = ROOT_RELEASE_TARGET) -> tuple[str, ...]:
    return tuple(_display_path(path) for path in _release_file_paths(target))


def build_precheck_commands() -> tuple[tuple[str, ...], ...]:
    """Return release-helper precheck commands."""

    return (
        HERMETIC_TEST_COMMAND,
        LIVE_LLM_TEST_COMMAND,
        RUFF_CHECK_COMMAND,
        RUFF_FORMAT_COMMAND,
        MYPY_COMMAND,
        SELF_CORPUS_COMMAND,
    )


def _precheck_env_overrides(command: tuple[str, ...]) -> dict[str, str] | None:
    """Return precheck environment overrides for one command."""

    env: dict[str, str] = {}
    if command[:3] == ("uv", "run", "pytest"):
        env.update(PRECHECK_ENV_OVERRIDES)
    if command == LIVE_LLM_TEST_COMMAND:
        env["BACKSTITCH_LIVE_LLM"] = "1"
        env["BACKSTITCH_LIVE_LLM_KIND"] = "openai"
    return env or None


def build_postupdate_steps() -> tuple[CommandStep, ...]:
    """Return post-version-update verification/build steps."""

    return (
        CommandStep(("uv", "lock")),
        CommandStep(VERSION_SMOKE_COMMAND),
        CommandStep(("uv", "build")),
    )


def _merge_command_env(
    env_overrides: dict[str, str] | None,
    *,
    base_env: dict[str, str] | None = None,
) -> dict[str, str] | None:
    """Merge per-command environment overrides onto the current environment."""

    if not env_overrides:
        return None

    merged = os.environ.copy() if base_env is None else base_env.copy()
    for key, value in env_overrides.items():
        if key == "PYTEST_ADDOPTS":
            existing = merged.get(key, "").strip()
            merged[key] = f"{existing} {value}".strip() if existing else value
            continue
        merged[key] = value
    return merged


def _format_command_prefix(env_overrides: dict[str, str] | None) -> str:
    """Format environment overrides shown before a command in logs."""

    if not env_overrides:
        return ""
    return " ".join(
        f"{key}={shlex.quote(value)}" for key, value in sorted(env_overrides.items())
    )


def _format_cwd_suffix(cwd: Path) -> str:
    if cwd == PROJECT_ROOT:
        return ""
    return f"  (cwd={_display_path(cwd)})"


def run_command(
    command: tuple[str, ...],
    *,
    cwd: Path = PROJECT_ROOT,
    dry_run: bool = False,
    env_overrides: dict[str, str] | None = None,
) -> None:
    """Run a command, printing it first."""

    prefix = _format_command_prefix(env_overrides)
    formatted = _format_command(command)
    command_text = f"$ {prefix} {formatted}" if prefix else f"$ {formatted}"
    print(f"{command_text}{_format_cwd_suffix(cwd)}")
    if dry_run:
        return
    subprocess.run(
        command,
        cwd=cwd,
        check=True,
        env=_merge_command_env(env_overrides),
    )


def is_dirty_worktree() -> bool:
    """Return True when git reports local modifications."""

    result = subprocess.run(
        ("git", "status", "--porcelain"),
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return bool(result.stdout.strip())


def _require_command(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"Required command not found on PATH: {name}")


def _capture_command(
    command: tuple[str, ...],
    *,
    cwd: Path = PROJECT_ROOT,
) -> subprocess.CompletedProcess[str]:
    """Run a command and capture its output."""

    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _git_output(command: tuple[str, ...], *, label: str) -> str:
    """Return git stdout or raise a targeted release-helper error."""

    result = _capture_command(command)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown git error"
        raise RuntimeError(f"Unable to determine {label}: {detail}")
    return result.stdout.strip()


def current_head_commit() -> str:
    """Return the current HEAD commit SHA."""

    return _git_output(("git", "rev-parse", "HEAD"), label="current HEAD commit")


def local_tag_commit(tag_name: str) -> str | None:
    """Return the local tag commit SHA or ``None`` if the tag is absent."""

    result = _capture_command(
        ("git", "rev-parse", "-q", "--verify", f"refs/tags/{tag_name}^{{commit}}")
    )
    if result.returncode != 0:
        return None
    commit = result.stdout.strip()
    return commit or None


def remote_tag_commit(tag_name: str) -> str | None:
    """Return the origin tag commit SHA or ``None`` if the tag is absent."""

    result = _capture_command(
        (
            "git",
            "ls-remote",
            "--tags",
            "origin",
            f"refs/tags/{tag_name}",
            f"refs/tags/{tag_name}^{{}}",
        )
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown git error"
        raise RuntimeError(f"Unable to inspect origin tag {tag_name}: {detail}")

    direct_ref = f"refs/tags/{tag_name}"
    peeled_ref = f"{direct_ref}^{{}}"
    direct_commit: str | None = None
    peeled_commit: str | None = None
    for line in result.stdout.splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            continue
        sha, ref = parts
        if ref == peeled_ref:
            peeled_commit = sha
        elif ref == direct_ref:
            direct_commit = sha
    return peeled_commit or direct_commit


def origin_remote_url() -> str:
    """Return the `origin` remote URL."""

    return _git_output(
        ("git", "remote", "get-url", "origin"), label="origin remote URL"
    )


def github_repo_slug_from_remote(remote_url: str) -> str | None:
    """Extract ``owner/repo`` from a GitHub remote URL."""

    stripped = remote_url.strip()
    if stripped.startswith("git@github.com:"):
        path = stripped.removeprefix("git@github.com:")
    elif stripped.startswith("ssh://git@github.com/"):
        path = stripped.removeprefix("ssh://git@github.com/")
    elif stripped.startswith(("https://github.com/", "http://github.com/")):
        path = urllib_parse.urlparse(stripped).path.lstrip("/")
    else:
        return None

    if path.endswith(".git"):
        path = path[:-4]
    if path.count("/") != 1:
        return None
    owner, repo = path.split("/", maxsplit=1)
    if not owner or not repo:
        return None
    return f"{owner}/{repo}"


@lru_cache(maxsize=1)
def _github_api_token() -> str | None:
    """Return an auth token for GitHub API requests when one is available."""

    for env_var in ("GITHUB_TOKEN", "GH_TOKEN"):
        token = os.environ.get(env_var, "").strip()
        if token:
            return token

    if shutil.which("gh") is None:
        return None

    result = _capture_command(("gh", "auth", "token"))
    if result.returncode != 0:
        return None

    token = result.stdout.strip()
    return token or None


def _github_api_auth_headers() -> dict[str, str]:
    """Return GitHub API auth headers for authenticated release lookups."""

    token = _github_api_token()
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def _url_exists(url: str) -> bool:
    """Return whether a JSON endpoint exists, treating 404 as missing."""

    headers = {
        "Accept": "application/json",
        "User-Agent": "backstitch-release-helper",
    }
    if url.startswith(GITHUB_API_BASE):
        headers.update(_github_api_auth_headers())

    request = urllib_request.Request(url, headers=headers)
    try:
        with urllib_request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS):
            return True
    except urllib_error.HTTPError as exc:
        if exc.code == 404:
            return False
        raise RuntimeError(f"Unable to query {url}: HTTP {exc.code}") from exc
    except urllib_error.URLError as exc:
        raise RuntimeError(f"Unable to query {url}: {exc.reason}") from exc


def github_release_exists(tag_name: str) -> bool:
    """Return whether GitHub already has a published release for the tag."""

    remote_url = origin_remote_url()
    repo_slug = github_repo_slug_from_remote(remote_url)
    if repo_slug is None:
        raise RuntimeError(
            f"Unable to determine GitHub repository from origin remote: {remote_url}"
        )
    encoded_tag = urllib_parse.quote(tag_name, safe="")
    return _url_exists(
        f"{GITHUB_API_BASE}/repos/{repo_slug}/releases/tags/{encoded_tag}"
    )


def pypi_version_exists(package_name: str, version: str) -> bool:
    """Return whether PyPI already has the package version."""

    encoded_project = urllib_parse.quote(package_name, safe="")
    encoded_version = urllib_parse.quote(version, safe="")
    return _url_exists(f"{PYPI_API_BASE}/{encoded_project}/{encoded_version}/json")


def inspect_release_state(
    version: str,
    *,
    target: ReleaseTarget = ROOT_RELEASE_TARGET,
) -> ReleaseState:
    """Collect publication and tag state for a package version."""

    tag_name = target.tag_name(version)
    github_published = (
        github_release_exists(tag_name) if target.github_release_enabled else False
    )
    return ReleaseState(
        target=target,
        version=version,
        tag_name=tag_name,
        github_release_exists=github_published,
        pypi_release_exists=pypi_version_exists(target.package_name, version),
        local_tag_commit=local_tag_commit(tag_name),
        remote_tag_commit=remote_tag_commit(tag_name),
    )


def published_destinations(state: ReleaseState) -> str:
    """Return a human-readable list of external publication destinations."""

    destinations: list[str] = []
    if state.target.github_release_enabled and state.github_release_exists:
        destinations.append("GitHub Release")
    if state.pypi_release_exists:
        destinations.append("PyPI publication")
    return " and ".join(destinations)


def resolve_target_version(
    requested_version: str | None,
    *,
    current_version: str,
    target: ReleaseTarget = ROOT_RELEASE_TARGET,
) -> tuple[str, ReleaseState]:
    """Resolve the target version and ensure it has not been externally published."""

    target_version = (
        current_version
        if requested_version is None
        else validate_version(requested_version)
    )
    state = inspect_release_state(target_version, target=target)
    if state.published:
        if requested_version is None:
            raise RuntimeError(
                f"Current {target.display_name} version {current_version} already has "
                f"a {published_destinations(state)}. Pass --version with a new version."
            )
        raise RuntimeError(
            f"{target.display_name} version {target_version} already has a "
            f"{published_destinations(state)}. Choose a new version."
        )
    return target_version, state


def _short_commit(commit: str) -> str:
    return commit[:12]


def plan_tag_action(
    state: ReleaseState,
    *,
    head_commit: str,
    version_changed: bool,
    allow_retag: bool,
) -> TagAction:
    """Plan how the helper should handle the target tag safely."""

    if version_changed:
        if state.remote_tag_commit is not None:
            if allow_retag:
                return "replace_remote"
            raise RuntimeError(
                f"Tag {state.tag_name} already exists on origin at "
                f"{_short_commit(state.remote_tag_commit)}. Choose a different version "
                "or pass --retag."
            )
        if state.local_tag_commit is not None:
            return "replace_local"
        return "create"

    if state.remote_tag_commit is not None and state.remote_tag_commit != head_commit:
        if allow_retag:
            return "replace_remote"
        raise RuntimeError(
            f"Tag {state.tag_name} already exists on origin at "
            f"{_short_commit(state.remote_tag_commit)}, but HEAD is "
            f"{_short_commit(head_commit)}. Reusing this unpublished version "
            "would move the remote tag; choose a new version or pass --retag."
        )

    if state.local_tag_commit is not None and state.local_tag_commit != head_commit:
        if state.remote_tag_commit is None:
            return "replace_local"
        raise RuntimeError(
            f"Tag {state.tag_name} already exists on local repo at "
            f"{_short_commit(state.local_tag_commit)}, but origin already has "
            f"{_short_commit(state.remote_tag_commit)}. Fix the local tag or "
            "delete it manually before retrying."
        )

    if state.remote_tag_commit is not None:
        return "reuse_remote"
    if state.local_tag_commit is not None:
        return "push_local"
    return "create"


def release_files_changed(target: ReleaseTarget = ROOT_RELEASE_TARGET) -> bool:
    """Return True when release files have unstaged modifications."""

    result = _capture_command(
        ("git", "diff", "--quiet", "--", *_release_file_args(target))
    )
    if result.returncode == 0:
        return False
    if result.returncode == 1:
        return True
    detail = result.stderr.strip() or result.stdout.strip() or "unknown git error"
    raise RuntimeError(f"Unable to inspect release file changes: {detail}")


def _remote_tag_reuse_note(state: ReleaseState) -> str:
    return (
        f"Tag {state.tag_name} already exists on origin at HEAD. Pushing the same tag "
        f"again will not retrigger {state.target.release_workflow}; rerun the "
        "existing release-gate workflow manually in GitHub Actions if needed."
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a local Backstitch release")
    parser.add_argument(
        "-v",
        "--version",
        help=(
            "Explicit release version in X.Y.Z format. When omitted, the helper "
            "reuses the current version if it has not been published yet."
        ),
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help=(
            "Deprecated compatibility flag. Tag-push release-gate workflows "
            "build, publish to PyPI via Trusted Publishing, and create GitHub "
            "Releases; this helper does not publish directly."
        ),
    )
    parser.add_argument(
        "--skip-checks",
        action="store_true",
        help="Skip preflight test/lint/type-check commands",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned actions without modifying files or running commands",
    )
    parser.add_argument(
        "--retag",
        action="store_true",
        help=(
            "Delete and recreate unpublished remote tags when the existing tag "
            "points at the wrong commit."
        ),
    )
    return parser


def _prepare_tag_action(
    state: ReleaseState,
    *,
    tag_action: TagAction,
    dry_run: bool,
) -> None:
    """Apply local tag mutations and remote tag deletions."""

    tag_name = state.tag_name
    if tag_action == "replace_local":
        run_command(("git", "tag", "-d", tag_name), dry_run=dry_run)

    if tag_action == "replace_remote":
        if state.local_tag_commit is not None:
            run_command(("git", "tag", "-d", tag_name), dry_run=dry_run)
        run_command(("git", "push", "--delete", "origin", tag_name), dry_run=dry_run)

    if tag_action in {"create", "replace_local", "replace_remote"}:
        run_command(("git", "tag", tag_name), dry_run=dry_run)


def _push_tag_action(
    state: ReleaseState,
    *,
    tag_action: TagAction,
    dry_run: bool,
) -> None:
    """Push a prepared tag to origin when required."""

    tag_name = state.tag_name
    if tag_action in {"create", "push_local", "replace_local", "replace_remote"}:
        run_command(("git", "push", "origin", tag_name), dry_run=dry_run)
        return

    note = _remote_tag_reuse_note(state)
    print(note if not dry_run else f"dry-run: {note}")


def _print_publish_note() -> None:
    print(
        "--publish is ignored: tag-push release-gate workflows publish to PyPI "
        "(via Trusted Publishing) and create GitHub Releases; this helper does "
        "not publish directly."
    )


def _print_release_plan(
    *,
    target: ReleaseTarget,
    current_version: str,
    target_version: str,
    release_state: ReleaseState,
    tag_action: TagAction,
) -> None:
    print(f"target:  {target.display_name}")
    print(f"current: {current_version}")
    print(f"release: {target_version}")
    print("status:  unpublished on GitHub Release and PyPI")
    print(f"tag:     {release_state.tag_name} ({tag_action})")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    target = ROOT_RELEASE_TARGET

    current_version = read_target_version(target)
    dirty = is_dirty_worktree()

    if dirty and not args.dry_run:
        raise RuntimeError("Working tree must be clean before release.")

    target_version, release_state = resolve_target_version(
        args.version,
        current_version=current_version,
        target=target,
    )
    version_changed = target_version != current_version
    initial_head_commit = current_head_commit()
    planning_head_commit = (
        PENDING_RELEASE_COMMIT if version_changed else initial_head_commit
    )
    tag_action = plan_tag_action(
        release_state,
        head_commit=planning_head_commit,
        version_changed=version_changed,
        allow_retag=args.retag,
    )

    _print_release_plan(
        target=target,
        current_version=current_version,
        target_version=target_version,
        release_state=release_state,
        tag_action=tag_action,
    )

    if args.dry_run:
        if dirty:
            print("dry-run: working tree is dirty; a real release would fail")
        if args.publish:
            _print_publish_note()
        if not args.skip_checks:
            for command in build_precheck_commands():
                run_command(
                    command,
                    dry_run=True,
                    env_overrides=_precheck_env_overrides(command),
                )
        if version_changed:
            print(
                "dry-run: would update "
                + ", ".join(
                    _display_path(path)
                    for path in _release_file_paths(target)
                    if path != UV_LOCK_PATH
                )
            )
        else:
            print(
                f"dry-run: current {target.display_name} version {target_version} "
                "is unpublished; would reuse existing version files"
            )
        for step in build_postupdate_steps():
            run_command(
                step.command,
                cwd=step.cwd,
                dry_run=True,
                env_overrides=step.env_overrides,
            )
        if version_changed:
            run_command(("git", "add", *_release_file_args(target)), dry_run=True)
            run_command(
                (
                    "git",
                    "commit",
                    "-m",
                    f"Release {target.display_name} {target_version}",
                ),
                dry_run=True,
            )
        else:
            print(
                "dry-run: no release commit needed unless generated release files "
                "change during post-update checks"
            )
        _prepare_tag_action(release_state, tag_action=tag_action, dry_run=True)
        run_command(("git", "push"), dry_run=True)
        _push_tag_action(release_state, tag_action=tag_action, dry_run=True)
        print(
            "dry-run: next step is to wait for "
            f"{target.release_workflow} on {release_state.tag_name}"
        )
        return 0

    _require_command("uv")
    if args.publish:
        _print_publish_note()

    if not args.skip_checks:
        for command in build_precheck_commands():
            run_command(command, env_overrides=_precheck_env_overrides(command))

    if version_changed:
        write_target_version(target, target_version)
        print(
            "Updated version files: "
            + ", ".join(
                _display_path(path)
                for path in _release_file_paths(target)
                if path != UV_LOCK_PATH
            )
        )
    else:
        print(
            f"Reusing current unpublished {target.display_name} version "
            f"{target_version}; version files unchanged"
        )

    for step in build_postupdate_steps():
        run_command(step.command, cwd=step.cwd, env_overrides=step.env_overrides)

    release_commit_created = version_changed or release_files_changed(target)
    if release_commit_created:
        run_command(("git", "add", *_release_file_args(target)))
        run_command(
            ("git", "commit", "-m", f"Release {target.display_name} {target_version}")
        )
    else:
        print("No release commit needed; release files already match target version")

    head_commit = current_head_commit()
    tag_action = plan_tag_action(
        release_state,
        head_commit=head_commit,
        version_changed=release_commit_created,
        allow_retag=args.retag,
    )

    _prepare_tag_action(release_state, tag_action=tag_action, dry_run=False)
    run_command(("git", "push"))
    _push_tag_action(release_state, tag_action=tag_action, dry_run=False)

    print(
        "Next step: wait for "
        f"{target.release_workflow} on {release_state.tag_name}. "
        "It will publish to PyPI via Trusted Publishing and create the GitHub Release."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except subprocess.CalledProcessError as exc:
        print(f"error: command failed with exit code {exc.returncode}", file=sys.stderr)
        raise SystemExit(exc.returncode) from exc
