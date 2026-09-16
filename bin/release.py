#!/usr/bin/env python3
"""Repo-local release helper for Backstitch maintainers."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Mapping
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
GITHUB_API_VERSION: Final[str] = "2026-03-10"
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
CORE_RELEASE_TARGET_KEY: Final[str] = "core"
ALL_RELEASE_TARGET_KEY: Final[str] = "all"
RELEASE_TAG_RULESET_NAME: Final[str] = "Protect release tags"
ACTIONS_ALLOWED_PATTERNS: Final[frozenset[str]] = frozenset(
    {
        "astral-sh/setup-uv@*",
        "codecov/codecov-action@*",
        "pypa/gh-action-pypi-publish@*",
        "softprops/action-gh-release@*",
    }
)
RELEASE_TAG_PATTERNS: Final[frozenset[str]] = frozenset({"refs/tags/v*"})
PYPI_ENVIRONMENT_TAG_PATTERNS: Final[frozenset[tuple[str, str]]] = frozenset(
    {("tag", "v*")}
)
REQUIRED_RELEASE_WORKFLOWS: Final[tuple[str, ...]] = ("CI", "local-llm")
DEFAULT_LOCAL_LLM_ENDPOINT: Final[str] = "http://127.0.0.1:11434/v1"
DEFAULT_LOCAL_LLM_BASE_MODEL: Final[str] = "qwen2.5-coder:14b-instruct-q4_K_M"
DEFAULT_LOCAL_LLM_SERVED_MODEL: Final[str] = "backstitch-local-model:latest"
DEFAULT_LOCAL_LLM_CONTEXT_LENGTH: Final[str] = "4096"
DEFAULT_LOCAL_LLM_NUM_PREDICT: Final[str] = "1024"
LOCAL_LLM_PREWARM_TIMEOUT_SECONDS: Final[int] = 25 * 60
LOCAL_LLM_PREWARM_POLL_SECONDS: Final[float] = 2.0
LOCAL_LLM_INFERENCE_SEED: Final[int] = 42

HERMETIC_TEST_COMMAND: Final[tuple[str, ...]] = (
    "uv",
    "run",
    "pytest",
    "tests",
    "-q",
    "-n",
    "auto",
    "--dist",
    "loadgroup",
    "-m",
    "not live_llm and not benchmark",
)
BENCHMARK_TEST_COMMAND: Final[tuple[str, ...]] = (
    "uv",
    "run",
    "pytest",
    "tests",
    "-q",
    "-n",
    "0",
    "-m",
    "benchmark",
)
LIVE_LLM_TEST_COMMAND: Final[tuple[str, ...]] = (
    "uv",
    "run",
    "pytest",
    "tests/live/test_live_llm.py",
    "-q",
    "-s",
)
LOCAL_LLM_TEST_COMMAND: Final[tuple[str, ...]] = (
    "uv",
    "run",
    "pytest",
    "tests/live/test_live_llm.py",
    "-q",
    "--tb=short",
)
RUFF_CHECK_COMMAND: Final[tuple[str, ...]] = (
    "uv",
    "run",
    "--frozen",
    "--no-sync",
    "ruff",
    "check",
    ".",
    "bin/check-doc-paths",
    "bin/check-dom15-fixtures",
    "bin/coalesce-check",
)
RUFF_SUPPRESSION_CHECK_COMMAND: Final[tuple[str, ...]] = (
    "uv",
    "run",
    "--frozen",
    "--no-sync",
    "python",
    "bin/ruff_suppression_index.py",
    "--check",
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
    "tests",
)
MYPY_COMMAND: Final[tuple[str, ...]] = (
    "uv",
    "run",
    "mypy",
    "backstitch",
    "bin/release.py",
    "tests",
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


@dataclass
class BackgroundCheck:
    """One background release precheck with delayed failure reporting."""

    name: str
    thread: threading.Thread
    errors: list[BaseException]


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


@dataclass(frozen=True)
class ReleaseCandidate:
    """One unpublished release that may be tagged after exact-SHA CI."""

    target: ReleaseTarget
    current_version: str
    release_version: str
    state: ReleaseState


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
        BENCHMARK_TEST_COMMAND,
        LIVE_LLM_TEST_COMMAND,
        LOCAL_LLM_TEST_COMMAND,
        RUFF_CHECK_COMMAND,
        RUFF_SUPPRESSION_CHECK_COMMAND,
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
    if command == LOCAL_LLM_TEST_COMMAND:
        env["BACKSTITCH_LIVE_LLM"] = "1"
        env["BACKSTITCH_LIVE_LLM_KIND"] = "local"
        env["BACKSTITCH_LOCAL_LLM_ENDPOINT"] = os.environ.get(
            "BACKSTITCH_LOCAL_LLM_ENDPOINT",
            DEFAULT_LOCAL_LLM_ENDPOINT,
        )
        env["BACKSTITCH_LOCAL_LLM_UPSTREAM"] = os.environ.get(
            "BACKSTITCH_LOCAL_LLM_UPSTREAM",
            DEFAULT_LOCAL_LLM_ENDPOINT,
        )
        env["BACKSTITCH_LOCAL_LLM_BASE_MODEL"] = os.environ.get(
            "BACKSTITCH_LOCAL_LLM_BASE_MODEL",
            DEFAULT_LOCAL_LLM_BASE_MODEL,
        )
        env["BACKSTITCH_LOCAL_LLM_SERVED_MODEL"] = os.environ.get(
            "BACKSTITCH_LOCAL_LLM_SERVED_MODEL",
            DEFAULT_LOCAL_LLM_SERVED_MODEL,
        )
        env["OLLAMA_CONTEXT_LENGTH"] = os.environ.get(
            "OLLAMA_CONTEXT_LENGTH",
            DEFAULT_LOCAL_LLM_CONTEXT_LENGTH,
        )
        env["OLLAMA_NUM_PREDICT"] = os.environ.get(
            "OLLAMA_NUM_PREDICT",
            DEFAULT_LOCAL_LLM_NUM_PREDICT,
        )
    return env or None


def build_postupdate_steps() -> tuple[CommandStep, ...]:
    """Return post-version-update verification/build steps."""

    return (
        CommandStep(("uv", "lock")),
        CommandStep(VERSION_SMOKE_COMMAND),
        CommandStep(("uv", "sync", "--frozen", "--group", "release")),
        CommandStep(
            (
                "uv",
                "run",
                "--frozen",
                "--no-sync",
                "python",
                "-m",
                "build",
                "--no-isolation",
            )
        ),
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


def _merge_public_and_private_command_env(
    env_overrides: dict[str, str] | None,
    private_env_overrides: dict[str, str] | None,
) -> dict[str, str] | None:
    """Merge logged and private command environment without logging secrets."""

    merged = _merge_command_env(env_overrides)
    if not private_env_overrides:
        return merged
    return _merge_command_env(private_env_overrides, base_env=merged)


def _format_command_prefix(
    env_overrides: dict[str, str] | None,
    *,
    private_env_keys: frozenset[str] = frozenset(),
) -> str:
    """Format environment overrides shown before a command in logs."""

    if not env_overrides and not private_env_keys:
        return ""
    public_parts = (
        (f"{key}={shlex.quote(value)}" for key, value in sorted(env_overrides.items()))
        if env_overrides
        else ()
    )
    private_parts = (f"{key}=<redacted>" for key in sorted(private_env_keys))
    return " ".join((*public_parts, *private_parts))


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
    private_env_overrides: dict[str, str] | None = None,
) -> None:
    """Run a command, printing it first."""

    overlapping_keys = set(env_overrides or ()) & set(private_env_overrides or ())
    if overlapping_keys:
        raise RuntimeError(
            "Command environment keys cannot be both public and private: "
            + ", ".join(sorted(overlapping_keys))
        )
    prefix = _format_command_prefix(
        env_overrides,
        private_env_keys=frozenset(private_env_overrides or ()),
    )
    formatted = _format_command(command)
    command_text = f"$ {prefix} {formatted}" if prefix else f"$ {formatted}"
    print(f"{command_text}{_format_cwd_suffix(cwd)}")
    if dry_run:
        return
    subprocess.run(
        command,
        cwd=cwd,
        check=True,
        env=_merge_public_and_private_command_env(
            env_overrides,
            private_env_overrides,
        ),
    )


def _json_api_request(
    url: str,
    *,
    payload: dict[str, object] | None = None,
    timeout: float = HTTP_TIMEOUT_SECONDS,
) -> dict[str, object]:
    """Return a JSON object from a local OpenAI-compatible endpoint."""

    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib_request.Request(url, data=data, headers=headers)
    try:
        with urllib_request.urlopen(request, timeout=timeout) as response:
            decoded = json.load(response)
    except urllib_error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"local LLM prewarm request failed: {exc.code} {detail}"
        ) from exc
    except urllib_error.URLError as exc:
        raise RuntimeError(f"local LLM prewarm request failed: {exc}") from exc

    if not isinstance(decoded, dict):
        raise RuntimeError("local LLM prewarm response was not a JSON object")
    return decoded


def _local_llm_url(endpoint: str, suffix: str) -> str:
    return f"{endpoint.rstrip('/')}/{suffix.lstrip('/')}"


def _local_llm_origin(endpoint: str) -> str:
    parsed = urllib_parse.urlparse(endpoint)
    if not parsed.scheme or not parsed.netloc:
        raise RuntimeError(f"invalid local LLM endpoint: {endpoint}")
    return f"{parsed.scheme}://{parsed.netloc}"


def _prepare_ollama_model(env: dict[str, str]) -> None:
    """Pull and recreate the bounded served model through Ollama's local API."""

    origin = _local_llm_origin(env["BACKSTITCH_LOCAL_LLM_UPSTREAM"])
    base_model = env["BACKSTITCH_LOCAL_LLM_BASE_MODEL"]
    served_model = env["BACKSTITCH_LOCAL_LLM_SERVED_MODEL"]
    context_length = env["OLLAMA_CONTEXT_LENGTH"]
    num_predict = env["OLLAMA_NUM_PREDICT"]

    _json_api_request(
        f"{origin}/api/pull",
        payload={"model": base_model, "stream": False},
        timeout=LOCAL_LLM_PREWARM_TIMEOUT_SECONDS,
    )
    _json_api_request(
        f"{origin}/api/create",
        payload={
            "model": served_model,
            "from": base_model,
            "parameters": {
                "num_ctx": int(context_length),
                "num_predict": int(num_predict),
                "temperature": 0,
            },
            "stream": False,
        },
        timeout=LOCAL_LLM_PREWARM_TIMEOUT_SECONDS,
    )


def _prewarm_local_llm(env: dict[str, str]) -> None:
    """Require and warm the local LLM endpoint before the live local test."""

    _prepare_ollama_model(env)

    endpoint = env["BACKSTITCH_LOCAL_LLM_ENDPOINT"]
    model = env["BACKSTITCH_LOCAL_LLM_SERVED_MODEL"]
    deadline = time.monotonic() + LOCAL_LLM_PREWARM_TIMEOUT_SECONDS
    last_error = "model was not checked"

    while time.monotonic() < deadline:
        try:
            payload = _json_api_request(_local_llm_url(endpoint, "models"), timeout=10)
            raw_models = payload.get("data", [])
            if not isinstance(raw_models, list):
                raise RuntimeError("local LLM /models response data was not a list")
            model_ids: list[str] = []
            for item in raw_models:
                if not isinstance(item, dict):
                    continue
                item_id = item.get("id")
                if isinstance(item_id, str):
                    model_ids.append(item_id)
            if model in model_ids:
                break
            last_error = f"{model!r} not listed; saw {model_ids!r}"
        except RuntimeError as exc:
            last_error = str(exc)
        time.sleep(LOCAL_LLM_PREWARM_POLL_SECONDS)
    else:
        raise RuntimeError(
            f"local LLM model {model!r} was not ready before timeout: {last_error}"
        )

    _json_api_request(
        _local_llm_url(endpoint, "chat/completions"),
        payload={
            "model": model,
            "messages": [{"role": "user", "content": "Reply with OK."}],
            "temperature": 0,
            "seed": LOCAL_LLM_INFERENCE_SEED,
            "max_tokens": 4,
            "stream": False,
        },
        timeout=LOCAL_LLM_PREWARM_TIMEOUT_SECONDS,
    )


def _start_local_llm_prewarm(*, dry_run: bool) -> BackgroundCheck | None:
    """Start local LLM prewarm in parallel with earlier release checks."""

    env_overrides = _precheck_env_overrides(LOCAL_LLM_TEST_COMMAND)
    assert env_overrides is not None
    prefix = _format_command_prefix(env_overrides)
    print(f"$ {prefix} prewarm local LLM endpoint (background)")
    if dry_run:
        return None

    merged = _merge_command_env(env_overrides)
    assert merged is not None
    errors: list[BaseException] = []

    def run() -> None:
        try:
            _prewarm_local_llm(merged)
        except BaseException as exc:  # noqa: BLE001 - report after foreground gates
            errors.append(exc)

    thread = threading.Thread(target=run, name="local-llm-prewarm", daemon=True)
    thread.start()
    return BackgroundCheck(name="local LLM prewarm", thread=thread, errors=errors)


def _wait_for_background_check(check: BackgroundCheck | None) -> None:
    if check is None:
        return
    check.thread.join()
    if check.errors:
        raise RuntimeError(f"{check.name} failed: {check.errors[0]}")


def run_precheck_commands(*, dry_run: bool = False) -> None:
    """Run release prechecks, warming the local LLM endpoint in parallel."""

    local_prewarm = _start_local_llm_prewarm(dry_run=dry_run)
    for command in build_precheck_commands():
        if command == LOCAL_LLM_TEST_COMMAND:
            _wait_for_background_check(local_prewarm)
        run_command(
            command,
            dry_run=dry_run,
            env_overrides=_precheck_env_overrides(command),
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


def current_branch() -> str:
    """Return the current branch name, rejecting detached HEAD."""

    branch = _git_output(
        ("git", "branch", "--show-current"),
        label="current branch",
    )
    if not branch:
        raise RuntimeError("A real release cannot run from detached HEAD")
    return branch


def require_main_branch() -> None:
    """Require real releases to run from the main branch."""

    branch = current_branch()
    if branch != "main":
        raise RuntimeError(
            f"A real release must run from main; current branch is {branch}"
        )


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


def _github_api_json(path: str, token: str) -> object:
    """Return one authenticated GitHub API JSON response."""

    if not path.startswith("/"):
        raise RuntimeError("GitHub API path must start with /")
    request = urllib_request.Request(
        f"{GITHUB_API_BASE}{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "backstitch-release-helper",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        },
    )
    try:
        with urllib_request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return json.load(response)
    except urllib_error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"GitHub API request failed for {path}: HTTP {exc.code}: {detail}"
        ) from exc
    except urllib_error.URLError as exc:
        raise RuntimeError(
            f"GitHub API request failed for {path}: {exc.reason}"
        ) from exc


def _json_mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def _setting_payload(
    *,
    label: str,
    path: str,
    token: str,
    issues: list[str],
) -> object | None:
    try:
        return _github_api_json(path, token)
    except RuntimeError as exc:
        issues.append(f"{label} could not be verified: {exc}")
        return None


def _check_immutable_release_setting(
    base: str,
    token: str,
    issues: list[str],
) -> None:
    immutable = _setting_payload(
        label="immutable releases",
        path=f"{base}/immutable-releases",
        token=token,
        issues=issues,
    )
    immutable_mapping = _json_mapping(immutable)
    if immutable is not None and (
        immutable_mapping is None or immutable_mapping.get("enabled") is not True
    ):
        issues.append("immutable releases must be enabled")


def _check_actions_settings(
    base: str,
    token: str,
    issues: list[str],
) -> None:
    actions = _setting_payload(
        label="Actions SHA pinning",
        path=f"{base}/actions/permissions",
        token=token,
        issues=issues,
    )
    actions_mapping = _json_mapping(actions)
    if actions is not None and (
        actions_mapping is None or actions_mapping.get("allowed_actions") != "selected"
    ):
        issues.append("Actions must allow selected actions only")
    if actions is not None and (
        actions_mapping is None
        or actions_mapping.get("sha_pinning_required") is not True
    ):
        issues.append("Actions SHA pinning must require full commit SHAs")

    if actions_mapping is None or actions_mapping.get("allowed_actions") != "selected":
        return
    selected_actions = _setting_payload(
        label="selected Actions policy",
        path=f"{base}/actions/permissions/selected-actions",
        token=token,
        issues=issues,
    )
    selected = _json_mapping(selected_actions)
    if selected_actions is None:
        return
    if selected is None or selected.get("verified_allowed") is not False:
        issues.append("Actions must not allow all verified publishers")
    if selected is None or selected.get("github_owned_allowed") is not True:
        issues.append("Actions must allow GitHub-owned actions")
    raw_patterns = selected.get("patterns_allowed") if selected is not None else None
    observed = (
        {pattern for pattern in raw_patterns if isinstance(pattern, str)}
        if isinstance(raw_patterns, list)
        else set()
    )
    if (
        not isinstance(raw_patterns, list)
        or len(raw_patterns) != len(ACTIONS_ALLOWED_PATTERNS)
        or observed != set(ACTIONS_ALLOWED_PATTERNS)
    ):
        issues.append("Actions must use the exact four third-party action patterns")


def _check_pypi_environment_settings(
    base: str,
    token: str,
    issues: list[str],
) -> None:
    environment = _setting_payload(
        label="pypi environment policy",
        path=f"{base}/environments/pypi",
        token=token,
        issues=issues,
    )
    environment_mapping = _json_mapping(environment)
    deployment_policy = (
        _json_mapping(environment_mapping.get("deployment_branch_policy"))
        if environment_mapping is not None
        else None
    )
    if environment is not None and (
        deployment_policy is None
        or deployment_policy.get("protected_branches") is not False
        or deployment_policy.get("custom_branch_policies") is not True
    ):
        issues.append("pypi environment must use custom tag deployment policies only")

    policies = _setting_payload(
        label="pypi environment tag policies",
        path=f"{base}/environments/pypi/deployment-branch-policies",
        token=token,
        issues=issues,
    )
    policies_mapping = _json_mapping(policies)
    raw_policies = (
        policies_mapping.get("branch_policies")
        if policies_mapping is not None
        else None
    )
    observed: set[tuple[str, str]] = set()
    if isinstance(raw_policies, list):
        for raw_policy in raw_policies:
            policy = _json_mapping(raw_policy)
            if policy is None:
                continue
            policy_type = policy.get("type")
            name = policy.get("name")
            if isinstance(policy_type, str) and isinstance(name, str):
                observed.add((policy_type, name))
    if policies is not None and observed != set(PYPI_ENVIRONMENT_TAG_PATTERNS):
        issues.append("pypi environment tag policies must be exactly v*")


def _release_ruleset_detail_matches(detail: object) -> bool:
    detail_mapping = _json_mapping(detail)
    conditions = (
        _json_mapping(detail_mapping.get("conditions"))
        if detail_mapping is not None
        else None
    )
    ref_name = (
        _json_mapping(conditions.get("ref_name")) if conditions is not None else None
    )
    includes = ref_name.get("include") if ref_name is not None else None
    excludes = ref_name.get("exclude") if ref_name is not None else None
    bypass_actors = (
        detail_mapping.get("bypass_actors") if detail_mapping is not None else None
    )
    raw_rules = detail_mapping.get("rules") if detail_mapping is not None else None
    rule_types = (
        {
            rule_type
            for raw_rule in raw_rules
            if (rule := _json_mapping(raw_rule)) is not None
            and isinstance((rule_type := rule.get("type")), str)
        }
        if isinstance(raw_rules, list)
        else set()
    )
    return (
        isinstance(includes, list)
        and {item for item in includes if isinstance(item, str)}
        == set(RELEASE_TAG_PATTERNS)
        and excludes == []
        and bypass_actors == []
        and rule_types == {"update", "deletion"}
    )


def _check_release_tag_ruleset(
    base: str,
    token: str,
    issues: list[str],
) -> None:
    rulesets = _setting_payload(
        label="release-tag ruleset",
        path=f"{base}/rulesets",
        token=token,
        issues=issues,
    )
    if rulesets is None:
        return
    matching = (
        [
            ruleset
            for raw_ruleset in rulesets
            if (ruleset := _json_mapping(raw_ruleset)) is not None
            and ruleset.get("name") == RELEASE_TAG_RULESET_NAME
            and ruleset.get("target") == "tag"
            and ruleset.get("enforcement") == "active"
        ]
        if isinstance(rulesets, list)
        else []
    )
    if len(matching) != 1:
        issues.append(
            "release-tag ruleset 'Protect release tags' must exist and be active"
        )
        return
    ruleset_id = matching[0].get("id")
    if not isinstance(ruleset_id, int) or isinstance(ruleset_id, bool):
        issues.append("release-tag ruleset did not contain a numeric id")
        return
    detail = _setting_payload(
        label="release-tag ruleset",
        path=f"{base}/rulesets/{ruleset_id}",
        token=token,
        issues=issues,
    )
    if detail is not None and not _release_ruleset_detail_matches(detail):
        issues.append(
            "release-tag ruleset must block updates and deletions for "
            "v* tags, allow creation, and have no bypass actors"
        )


def repository_settings_issues(repo_slug: str, token: str) -> tuple[str, ...]:
    """Return targeted issues for every required release repository setting."""

    issues: list[str] = []
    encoded_repo = urllib_parse.quote(repo_slug, safe="/")
    base = f"/repos/{encoded_repo}"
    _check_immutable_release_setting(base, token, issues)
    _check_actions_settings(base, token, issues)
    _check_pypi_environment_settings(base, token, issues)
    _check_release_tag_ruleset(base, token, issues)
    return tuple(issues)


def require_repository_settings() -> None:
    """Fail closed unless authenticated GitHub settings match release policy."""

    token = _github_api_token()
    if not token:
        raise RuntimeError(
            "Authenticated GitHub access is required to verify repository settings"
        )
    remote_url = origin_remote_url()
    repo_slug = github_repo_slug_from_remote(remote_url)
    if repo_slug is None:
        raise RuntimeError(
            f"Unable to determine GitHub repository from origin remote: {remote_url}"
        )
    issues = repository_settings_issues(repo_slug, token)
    if issues:
        raise RuntimeError(
            "Repository settings are not ready for release:\n- " + "\n- ".join(issues)
        )
    print("repository setting ok: immutable releases enabled")
    print("repository setting ok: release tags are write-once")
    print("repository setting ok: pypi accepts only release tags")
    print("repository setting ok: Actions use the exact allowlist and full SHAs")


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


def _read_json_url(url: str) -> object:
    """Read one JSON endpoint with the release helper's GitHub authentication."""

    headers = {
        "Accept": "application/json",
        "User-Agent": "backstitch-release-helper",
    }
    if url.startswith(GITHUB_API_BASE):
        headers.update(_github_api_auth_headers())
    request = urllib_request.Request(url, headers=headers)
    try:
        with urllib_request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return json.load(response)
    except urllib_error.HTTPError as exc:
        raise RuntimeError(f"Unable to query {url}: HTTP {exc.code}") from exc
    except urllib_error.URLError as exc:
        raise RuntimeError(f"Unable to query {url}: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Unable to parse JSON from {url}: {exc}") from exc


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


def active_release_gate_runs(
    tag_name: str,
    *,
    target: ReleaseTarget = ROOT_RELEASE_TARGET,
) -> tuple[str, ...]:
    """Return active release-gate run URLs for a tag, if any."""

    remote_url = origin_remote_url()
    repo_slug = github_repo_slug_from_remote(remote_url)
    if repo_slug is None:
        raise RuntimeError(
            f"Unable to determine GitHub repository from origin remote: {remote_url}"
        )
    workflow_name = Path(target.release_workflow).name
    encoded_workflow = urllib_parse.quote(workflow_name, safe="")
    query = urllib_parse.urlencode({"branch": tag_name, "per_page": 20})
    url = (
        f"{GITHUB_API_BASE}/repos/{repo_slug}/actions/workflows/"
        f"{encoded_workflow}/runs?{query}"
    )
    payload = _read_json_url(url)
    if not isinstance(payload, dict) or not isinstance(
        payload.get("workflow_runs"), list
    ):
        raise RuntimeError(
            f"GitHub workflow-runs response for {workflow_name} was malformed"
        )
    active: list[str] = []
    for run in payload["workflow_runs"]:
        if not isinstance(run, dict):
            raise RuntimeError(
                f"GitHub workflow-runs response for {workflow_name} was malformed"
            )
        if run.get("head_branch") != tag_name or run.get("status") == "completed":
            continue
        active.append(str(run.get("html_url") or run.get("id") or "unknown run"))
    return tuple(active)


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


def refresh_release_state_before_tag_mutation(
    version: str,
    *,
    target: ReleaseTarget,
    observed_remote_tag_commit: str | None,
) -> ReleaseState:
    """Recheck one-way-door and remote-tag state after long release checks."""

    tag_name = target.tag_name(version)
    active_runs = active_release_gate_runs(tag_name, target=target)
    if active_runs:
        raise RuntimeError(
            f"A release gate is still active for {tag_name}: "
            f"{', '.join(active_runs)}; refusing tag mutation."
        )
    state = inspect_release_state(version, target=target)
    if state.published:
        raise RuntimeError(
            f"{target.display_name} version {version} was published during release "
            f"preparation to {published_destinations(state)}; refusing tag mutation."
        )
    if state.remote_tag_commit != observed_remote_tag_commit:
        raise RuntimeError(
            f"Tag {state.tag_name} changed on origin during release preparation; "
            "refusing tag mutation."
        )
    return state


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
) -> TagAction:
    """Plan how the helper should handle the target tag safely."""

    if version_changed:
        if state.remote_tag_commit is not None:
            raise RuntimeError(
                f"Tag {state.tag_name} already exists on origin at "
                f"{_short_commit(state.remote_tag_commit)}. Choose a new version; "
                "remote release tags are permanent."
            )
        if state.local_tag_commit is not None:
            return "replace_local"
        return "create"

    if state.remote_tag_commit is not None and state.remote_tag_commit != head_commit:
        raise RuntimeError(
            f"Tag {state.tag_name} already exists on origin at "
            f"{_short_commit(state.remote_tag_commit)}, but HEAD is "
            f"{_short_commit(head_commit)}. Reusing this unpublished version "
            "would move the remote tag. Choose a new version; remote release "
            "tags are permanent."
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
    workflow_name = Path(state.target.release_workflow).name
    return (
        f"Tag {state.tag_name} already exists on origin at HEAD. Pushing the same tag "
        f"again will not retrigger {state.target.release_workflow}. Rerun an existing "
        "release-gate run when GitHub permits it. If no run can be rerun, dispatch "
        "only when this immutable tag already contains the workflow_dispatch trigger; "
        "older tags require a new version and must never be moved. Recovery command: "
        f"gh workflow run {workflow_name} --ref {state.tag_name}"
    )


def _github_repo_slug() -> str:
    remote_url = origin_remote_url()
    repo_slug = github_repo_slug_from_remote(remote_url)
    if repo_slug is None:
        raise RuntimeError(
            f"Unable to determine GitHub repository from origin remote: {remote_url}"
        )
    return repo_slug


def wait_for_release_workflows(
    release_sha: str,
    *,
    dry_run: bool = False,
) -> None:
    """Invoke the shared exact-SHA workflow poller without exposing its token."""

    token = "dry-run-authenticated-token"
    if not dry_run:
        token = _github_api_token() or ""
        if not token:
            raise RuntimeError(
                "Authenticated GitHub access is required to wait for release CI"
            )
    command: list[str] = [
        "uv",
        "run",
        "--project",
        str(PROJECT_ROOT),
        "--locked",
        "python",
        ".github/scripts/require_green_workflows.py",
        "--repo",
        _github_repo_slug(),
        "--sha",
        release_sha,
    ]
    for workflow in REQUIRED_RELEASE_WORKFLOWS:
        command.extend(("--workflow", workflow))
    run_command(
        tuple(command),
        dry_run=dry_run,
        private_env_overrides={"GITHUB_TOKEN": token},
    )


def require_release_sha_on_origin_main(
    release_sha: str,
    *,
    dry_run: bool = False,
) -> None:
    """Fetch main and require it still contains the tested release commit."""

    run_command(("git", "fetch", "origin", "main"), dry_run=dry_run)
    if dry_run:
        print(
            "dry-run: would require the tested release SHA to remain reachable "
            "from origin/main"
        )
        return
    result = _capture_command(
        ("git", "merge-base", "--is-ancestor", release_sha, "origin/main")
    )
    if result.returncode == 0:
        return
    if result.returncode == 1:
        raise RuntimeError(
            f"Tested release SHA {release_sha} is no longer reachable from origin/main"
        )
    detail = result.stderr.strip() or result.stdout.strip() or "unknown git error"
    raise RuntimeError(f"Unable to verify origin/main ancestry: {detail}")


def publish_release_tags_after_ci(
    candidates: tuple[ReleaseCandidate, ...],
    release_sha: str,
    *,
    dry_run: bool = False,
) -> None:
    """Push main, wait for exact-SHA CI, then create and push final tags."""

    run_command(("git", "push", "origin", "main"), dry_run=dry_run)
    wait_for_release_workflows(release_sha, dry_run=dry_run)
    require_release_sha_on_origin_main(release_sha, dry_run=dry_run)

    for candidate in candidates:
        state = (
            candidate.state
            if dry_run
            else inspect_release_state(
                candidate.release_version,
                target=candidate.target,
            )
        )
        if state.published:
            raise RuntimeError(
                f"{candidate.target.display_name} {candidate.release_version} was "
                f"published during the pre-tag wait via {published_destinations(state)}"
            )
        tag_action = plan_tag_action(
            state,
            head_commit=release_sha,
            version_changed=False,
        )
        _prepare_tag_action(
            state,
            tag_action=tag_action,
            dry_run=dry_run,
            target_commit=release_sha,
        )
        _push_tag_action(
            state,
            tag_action=tag_action,
            dry_run=dry_run,
        )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a local Backstitch release")
    parser.add_argument(
        "target",
        nargs="?",
        choices=(CORE_RELEASE_TARGET_KEY, ALL_RELEASE_TARGET_KEY),
        default=CORE_RELEASE_TARGET_KEY,
        help=(
            "Release target. Backstitch has one package, so 'all' is an alias "
            "for releasing the current root package version. Defaults to core."
        ),
    )
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
        "--dry-run",
        action="store_true",
        help="Print planned actions without modifying files or running commands",
    )
    parser.add_argument(
        "--check-repository-settings",
        action="store_true",
        help="Read and verify release-related GitHub repository settings",
    )
    return parser


def _prepare_tag_action(
    state: ReleaseState,
    *,
    tag_action: TagAction,
    dry_run: bool,
    target_commit: str,
) -> None:
    """Apply local-only tag mutations after exact-SHA CI succeeds."""

    tag_name = state.tag_name
    if tag_action == "replace_local":
        run_command(("git", "tag", "-d", tag_name), dry_run=dry_run)

    if tag_action in {"create", "replace_local"}:
        run_command(("git", "tag", tag_name, target_commit), dry_run=dry_run)


def _push_tag_action(
    state: ReleaseState,
    *,
    tag_action: TagAction,
    dry_run: bool,
) -> None:
    """Push a prepared tag to origin when required."""

    tag_name = state.tag_name
    if tag_action in {"create", "push_local", "replace_local"}:
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


@dataclass(frozen=True)
class _PreparedRelease:
    current_version: str
    target_version: str
    state: ReleaseState
    tag_action: TagAction
    version_changed: bool
    dirty: bool


def _prepare_release(
    args: argparse.Namespace, target: ReleaseTarget
) -> _PreparedRelease:
    if args.target == ALL_RELEASE_TARGET_KEY and args.version is not None:
        raise RuntimeError(
            "--version cannot be used with target 'all'. Update the package "
            "version files first, then run `bin/release.py all`."
        )

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
    )

    _print_release_plan(
        target=target,
        current_version=current_version,
        target_version=target_version,
        release_state=release_state,
        tag_action=tag_action,
    )
    return _PreparedRelease(
        current_version=current_version,
        target_version=target_version,
        state=release_state,
        tag_action=tag_action,
        version_changed=version_changed,
        dirty=dirty,
    )


def _print_dry_run_version_action(
    prepared: _PreparedRelease, target: ReleaseTarget
) -> None:
    if prepared.version_changed:
        paths = (
            _display_path(path)
            for path in _release_file_paths(target)
            if path != UV_LOCK_PATH
        )
        print("dry-run: would update " + ", ".join(paths))
        return
    print(
        f"dry-run: current {target.display_name} version {prepared.target_version} "
        "is unpublished; would reuse existing version files"
    )


def _run_dry_release(
    args: argparse.Namespace, target: ReleaseTarget, prepared: _PreparedRelease
) -> int:
    print(
        "dry-run: a real release would require main and verified GitHub "
        "repository settings"
    )
    if prepared.dirty:
        print("dry-run: working tree is dirty; a real release would fail")
    if args.publish:
        _print_publish_note()
    run_precheck_commands(dry_run=True)
    _print_dry_run_version_action(prepared, target)
    for step in build_postupdate_steps():
        run_command(
            step.command,
            cwd=step.cwd,
            dry_run=True,
            env_overrides=step.env_overrides,
        )
    if prepared.version_changed:
        run_command(("git", "add", *_release_file_args(target)), dry_run=True)
        run_command(
            (
                "git",
                "commit",
                "-m",
                f"Release {target.display_name} {prepared.target_version}",
            ),
            dry_run=True,
        )
    else:
        print(
            "dry-run: no release commit needed unless generated release files "
            "change during post-update checks"
        )
    release_sha = (
        PENDING_RELEASE_COMMIT if prepared.version_changed else current_head_commit()
    )
    candidate = ReleaseCandidate(
        target=target,
        current_version=prepared.current_version,
        release_version=prepared.target_version,
        state=prepared.state,
    )
    publish_release_tags_after_ci((candidate,), release_sha, dry_run=True)
    print(
        "dry-run: next step is to wait for "
        f"{target.release_workflow} on {prepared.state.tag_name}"
    )
    return 0


def _write_release_version(target: ReleaseTarget, prepared: _PreparedRelease) -> None:
    if prepared.version_changed:
        write_target_version(target, prepared.target_version)
        changed = (
            _display_path(path)
            for path in _release_file_paths(target)
            if path != UV_LOCK_PATH
        )
        print("Updated version files: " + ", ".join(changed))
        return
    print(
        f"Reusing current unpublished {target.display_name} version "
        f"{prepared.target_version}; version files unchanged"
    )


def _commit_release_files(target: ReleaseTarget, prepared: _PreparedRelease) -> bool:
    release_commit_created = prepared.version_changed or release_files_changed(target)
    if not release_commit_created:
        print("No release commit needed; release files already match target version")
        return False
    run_command(("git", "add", *_release_file_args(target)))
    run_command(
        (
            "git",
            "commit",
            "-m",
            f"Release {target.display_name} {prepared.target_version}",
        )
    )
    return True


def _run_real_release(
    args: argparse.Namespace, target: ReleaseTarget, prepared: _PreparedRelease
) -> int:
    require_main_branch()
    require_repository_settings()
    _require_command("uv")
    if args.publish:
        _print_publish_note()
    run_precheck_commands()
    _write_release_version(target, prepared)
    for step in build_postupdate_steps():
        run_command(step.command, cwd=step.cwd, env_overrides=step.env_overrides)
    _commit_release_files(target, prepared)
    release_sha = current_head_commit()
    candidate = ReleaseCandidate(
        target=target,
        current_version=prepared.current_version,
        release_version=prepared.target_version,
        state=prepared.state,
    )
    publish_release_tags_after_ci((candidate,), release_sha)
    print(
        "Next step: wait for "
        f"{target.release_workflow} on {prepared.state.tag_name}. "
        "It will publish to PyPI via Trusted Publishing and create the GitHub Release."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.check_repository_settings:
        require_repository_settings()
        return 0
    target = ROOT_RELEASE_TARGET
    prepared = _prepare_release(args, target)
    if args.dry_run:
        return _run_dry_release(args, target, prepared)
    return _run_real_release(args, target, prepared)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except subprocess.CalledProcessError as exc:
        print(f"error: command failed with exit code {exc.returncode}", file=sys.stderr)
        raise SystemExit(exc.returncode) from exc
