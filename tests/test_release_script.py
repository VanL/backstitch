from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _load_release_module() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "bin" / "release.py"
    spec = importlib.util.spec_from_file_location("backstitch_release_helper", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


release = _load_release_module()


def _state(
    *,
    local: str | None = None,
    remote: str | None = None,
    github: bool = False,
    pypi: bool = False,
) -> object:
    return release.ReleaseState(
        target=release.ROOT_RELEASE_TARGET,
        version="0.2.0",
        tag_name="v0.2.0",
        github_release_exists=github,
        pypi_release_exists=pypi,
        local_tag_commit=local,
        remote_tag_commit=remote,
    )


def test_validate_version_requires_three_numeric_segments() -> None:
    assert release.validate_version(" 0.2.0 ") == "0.2.0"

    with pytest.raises(ValueError, match="X.Y.Z"):
        release.validate_version("0.2")

    with pytest.raises(ValueError, match="X.Y.Z"):
        release.validate_version("v0.2.0")


def test_root_release_target_formats_expected_tag() -> None:
    assert release.ROOT_RELEASE_TARGET.package_name == "backstitch"
    assert release.ROOT_RELEASE_TARGET.tag_name("0.2.0") == "v0.2.0"
    assert release.ROOT_RELEASE_TARGET.release_workflow.endswith("release-gate.yml")


def test_read_current_version_requires_pyproject_and_init_to_match(
    tmp_path: Path,
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    init = tmp_path / "backstitch" / "__init__.py"
    init.parent.mkdir()
    pyproject.write_text('[project]\nversion = "0.2.0"\n', encoding="utf-8")
    init.write_text('__version__ = "0.2.0"\n', encoding="utf-8")

    assert (
        release.read_current_version(pyproject_path=pyproject, version_path=init)
        == "0.2.0"
    )

    init.write_text('__version__ = "0.1.9"\n', encoding="utf-8")

    with pytest.raises(RuntimeError, match="Version mismatch"):
        release.read_current_version(pyproject_path=pyproject, version_path=init)


def test_write_version_files_updates_untyped_init_version(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    init = tmp_path / "backstitch" / "__init__.py"
    init.parent.mkdir()
    pyproject.write_text('[project]\nversion = "0.1.0"\n', encoding="utf-8")
    init.write_text('__version__ = "0.1.0"\n', encoding="utf-8")

    release.write_version_files("0.2.0", pyproject_path=pyproject, version_path=init)

    assert 'version = "0.2.0"' in pyproject.read_text(encoding="utf-8")
    assert '__version__ = "0.2.0"' in init.read_text(encoding="utf-8")


def test_precheck_commands_match_release_contract() -> None:
    commands = release.build_precheck_commands()
    command_text = "\n".join(" ".join(command) for command in commands)

    assert "pytest tests -q -n auto --dist loadgroup -m not live_llm" in command_text
    assert "pytest tests/live/test_live_llm.py -q" in command_text
    assert "pytest tests/live/test_live_llm.py -q --tb=short" in command_text
    assert "ruff check backstitch tests bin" in command_text
    assert "ruff format --check backstitch bin .github/scripts tests" in command_text
    assert (
        "mypy backstitch bin/release.py tests --config-file pyproject.toml"
        in command_text
    )
    assert "backstitch check --repo-root ." in command_text


def test_live_llm_precheck_opts_in_to_real_provider_path() -> None:
    env = release._precheck_env_overrides(release.LIVE_LLM_TEST_COMMAND)

    assert env == {
        "PYTEST_ADDOPTS": "-x --maxfail=1",
        "BACKSTITCH_LIVE_LLM": "1",
        "BACKSTITCH_LIVE_LLM_KIND": "openai",
    }


def test_local_llm_precheck_opts_in_to_local_provider_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in (
        "BACKSTITCH_LOCAL_LLM_ENDPOINT",
        "BACKSTITCH_LOCAL_LLM_UPSTREAM",
        "BACKSTITCH_LOCAL_LLM_BASE_MODEL",
        "BACKSTITCH_LOCAL_LLM_SERVED_MODEL",
        "OLLAMA_CONTEXT_LENGTH",
        "OLLAMA_NUM_PREDICT",
    ):
        monkeypatch.delenv(key, raising=False)

    env = release._precheck_env_overrides(release.LOCAL_LLM_TEST_COMMAND)

    assert env == {
        "PYTEST_ADDOPTS": "-x --maxfail=1",
        "BACKSTITCH_LIVE_LLM": "1",
        "BACKSTITCH_LIVE_LLM_KIND": "local",
        "BACKSTITCH_LOCAL_LLM_ENDPOINT": "http://127.0.0.1:11434/v1",
        "BACKSTITCH_LOCAL_LLM_UPSTREAM": "http://127.0.0.1:11434/v1",
        "BACKSTITCH_LOCAL_LLM_BASE_MODEL": "llama3.2:3b",
        "BACKSTITCH_LOCAL_LLM_SERVED_MODEL": "backstitch-local-model:latest",
        "OLLAMA_CONTEXT_LENGTH": "4096",
        "OLLAMA_NUM_PREDICT": "1024",
    }


def test_local_llm_prewarm_sends_deterministic_request_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[tuple[str, dict[str, object] | None]] = []
    env = {
        "BACKSTITCH_LOCAL_LLM_ENDPOINT": "http://127.0.0.1:11434/v1",
        "BACKSTITCH_LOCAL_LLM_SERVED_MODEL": "backstitch-local-model:latest",
    }

    monkeypatch.setattr(release, "_prepare_ollama_model", lambda value: None)

    def fake_json_api_request(
        url: str,
        *,
        payload: dict[str, object] | None = None,
        timeout: float,
    ) -> dict[str, object]:
        requests.append((url, payload))
        if url.endswith("/models"):
            return {"data": [{"id": "backstitch-local-model:latest"}]}
        return {}

    monkeypatch.setattr(release, "_json_api_request", fake_json_api_request)

    release._prewarm_local_llm(env)

    assert requests[-1] == (
        "http://127.0.0.1:11434/v1/chat/completions",
        {
            "model": "backstitch-local-model:latest",
            "messages": [{"role": "user", "content": "Reply with OK."}],
            "temperature": 0,
            "seed": 42,
            "max_tokens": 4,
            "stream": False,
        },
    )


def test_command_env_appends_pytest_addopts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYTEST_ADDOPTS", "-ra")

    env = release._merge_command_env({"PYTEST_ADDOPTS": "-x --maxfail=1"})

    assert env is not None
    assert env["PYTEST_ADDOPTS"] == "-ra -x --maxfail=1"


def test_postupdate_steps_run_version_sensitive_commands_after_update() -> None:
    steps = release.build_postupdate_steps()
    commands = tuple(step.command for step in steps)

    assert commands == (
        ("uv", "lock"),
        ("uv", "run", "backstitch", "--version"),
        ("uv", "build"),
    )


@pytest.mark.parametrize(
    ("remote_url", "slug"),
    [
        ("git@github.com:VanL/backstitch.git", "VanL/backstitch"),
        ("ssh://git@github.com/VanL/backstitch.git", "VanL/backstitch"),
        ("https://github.com/VanL/backstitch.git", "VanL/backstitch"),
        ("https://github.com/VanL/backstitch", "VanL/backstitch"),
        ("git@example.com:VanL/backstitch.git", None),
    ],
)
def test_github_repo_slug_from_remote(remote_url: str, slug: str | None) -> None:
    assert release.github_repo_slug_from_remote(remote_url) == slug


@pytest.mark.parametrize(
    ("github", "pypi", "message"),
    [
        (True, False, "GitHub Release"),
        (False, True, "PyPI publication"),
    ],
)
def test_resolve_target_version_rejects_published_destinations(
    monkeypatch: pytest.MonkeyPatch,
    github: bool,
    pypi: bool,
    message: str,
) -> None:
    monkeypatch.setattr(
        release,
        "inspect_release_state",
        lambda version, *, target: _state(github=github, pypi=pypi),
    )

    with pytest.raises(RuntimeError, match=message):
        release.resolve_target_version(
            "0.2.0",
            current_version="0.1.0",
            target=release.ROOT_RELEASE_TARGET,
        )


def test_plan_tag_action_for_new_or_matching_tags() -> None:
    head = "a" * 40

    assert (
        release.plan_tag_action(
            _state(),
            head_commit=head,
            version_changed=False,
            allow_retag=False,
        )
        == "create"
    )
    assert (
        release.plan_tag_action(
            _state(local=head),
            head_commit=head,
            version_changed=False,
            allow_retag=False,
        )
        == "push_local"
    )
    assert (
        release.plan_tag_action(
            _state(remote=head),
            head_commit=head,
            version_changed=False,
            allow_retag=False,
        )
        == "reuse_remote"
    )


def test_plan_tag_action_rejects_remote_tag_at_different_commit() -> None:
    head = "a" * 40
    remote = "b" * 40

    with pytest.raises(RuntimeError, match="already exists on origin"):
        release.plan_tag_action(
            _state(remote=remote),
            head_commit=head,
            version_changed=False,
            allow_retag=False,
        )

    assert (
        release.plan_tag_action(
            _state(remote=remote),
            head_commit=head,
            version_changed=False,
            allow_retag=True,
        )
        == "replace_remote"
    )


def test_main_rejects_dirty_real_release(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(release, "read_target_version", lambda target: "0.1.0")
    monkeypatch.setattr(release, "is_dirty_worktree", lambda: True)

    with pytest.raises(RuntimeError, match="Working tree must be clean"):
        release.main(["--version", "0.2.0"])


def test_all_target_rejects_explicit_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(release, "read_target_version", lambda target: "0.1.0")

    with pytest.raises(RuntimeError, match="cannot be used with target 'all'"):
        release.main(["all", "--version", "0.2.0"])


def test_dry_run_prints_commands_without_running(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    commands: list[tuple[str, ...]] = []

    def fake_run_command(
        command: tuple[str, ...],
        *,
        cwd: Path = release.PROJECT_ROOT,
        dry_run: bool = False,
        env_overrides: dict[str, str] | None = None,
    ) -> None:
        assert dry_run is True
        assert cwd == release.PROJECT_ROOT
        if command == release.LIVE_LLM_TEST_COMMAND:
            assert env_overrides == {
                "PYTEST_ADDOPTS": "-x --maxfail=1",
                "BACKSTITCH_LIVE_LLM": "1",
                "BACKSTITCH_LIVE_LLM_KIND": "openai",
            }
        commands.append(command)

    monkeypatch.setattr(release, "read_target_version", lambda target: "0.1.0")
    monkeypatch.setattr(release, "is_dirty_worktree", lambda: False)
    monkeypatch.setattr(
        release,
        "inspect_release_state",
        lambda version, *, target: _state(),
    )
    monkeypatch.setattr(release, "current_head_commit", lambda: "a" * 40)
    monkeypatch.setattr(release, "run_command", fake_run_command)

    assert release.main(["--version", "0.2.0", "--dry-run"]) == 0

    output = capsys.readouterr().out
    assert "dry-run: would update pyproject.toml, backstitch/__init__.py" in output
    assert ("uv", "lock") in commands
    assert ("git", "tag", "v0.2.0") in commands
    assert ("git", "push", "origin", "v0.2.0") in commands


def test_all_target_dry_run_reuses_current_unpublished_version(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    commands: list[tuple[str, ...]] = []

    def fake_run_command(
        command: tuple[str, ...],
        *,
        cwd: Path = release.PROJECT_ROOT,
        dry_run: bool = False,
        env_overrides: dict[str, str] | None = None,
    ) -> None:
        assert dry_run is True
        commands.append(command)

    monkeypatch.setattr(release, "read_target_version", lambda target: "0.2.0")
    monkeypatch.setattr(release, "is_dirty_worktree", lambda: False)
    monkeypatch.setattr(
        release,
        "inspect_release_state",
        lambda version, *, target: _state(),
    )
    monkeypatch.setattr(release, "current_head_commit", lambda: "a" * 40)
    monkeypatch.setattr(release, "run_command", fake_run_command)

    assert release.main(["all", "--dry-run", "--skip-checks"]) == 0

    output = capsys.readouterr().out
    assert "dry-run: current backstitch version 0.2.0 is unpublished" in output
    assert ("git", "tag", "v0.2.0") in commands
    assert ("git", "push", "origin", "v0.2.0") in commands


def test_retag_dry_run_pushes_branch_before_leased_remote_deletion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[tuple[str, ...]] = []
    old_commit = "b" * 40
    new_commit = "a" * 40

    def fake_run_command(
        command: tuple[str, ...],
        *,
        cwd: Path = release.PROJECT_ROOT,
        dry_run: bool = False,
        env_overrides: dict[str, str] | None = None,
    ) -> None:
        assert dry_run is True
        commands.append(command)

    monkeypatch.setattr(release, "read_target_version", lambda target: "0.2.0")
    monkeypatch.setattr(release, "is_dirty_worktree", lambda: False)
    monkeypatch.setattr(
        release,
        "inspect_release_state",
        lambda version, *, target: _state(local=old_commit, remote=old_commit),
    )
    monkeypatch.setattr(release, "current_head_commit", lambda: new_commit)
    monkeypatch.setattr(release, "run_command", fake_run_command)

    assert release.main(["all", "--dry-run", "--skip-checks", "--retag"]) == 0

    branch_push = commands.index(("git", "push"))
    leased_delete = commands.index(
        (
            "git",
            "push",
            f"--force-with-lease=refs/tags/v0.2.0:{old_commit}",
            "origin",
            ":refs/tags/v0.2.0",
        )
    )
    assert branch_push < leased_delete


@pytest.mark.parametrize(
    ("published_state", "destination"),
    [
        (_state(local="b" * 40, remote="b" * 40, pypi=True), "PyPI"),
        (_state(local="b" * 40, remote="b" * 40, github=True), "GitHub"),
    ],
)
def test_real_release_rechecks_publication_after_branch_push(
    monkeypatch: pytest.MonkeyPatch,
    published_state: object,
    destination: str,
) -> None:
    commands: list[tuple[str, ...]] = []
    old_commit = "b" * 40
    new_commit = "a" * 40
    states = iter(
        (
            _state(local=old_commit, remote=old_commit),
            published_state,
        )
    )

    monkeypatch.setattr(release, "read_target_version", lambda target: "0.2.0")
    monkeypatch.setattr(release, "is_dirty_worktree", lambda: False)
    monkeypatch.setattr(
        release,
        "inspect_release_state",
        lambda version, *, target: next(states),
    )
    monkeypatch.setattr(release, "current_head_commit", lambda: new_commit)
    monkeypatch.setattr(release, "build_postupdate_steps", tuple)
    monkeypatch.setattr(release, "release_files_changed", lambda target: False)
    monkeypatch.setattr(release, "_require_command", lambda command: None)
    monkeypatch.setattr(
        release,
        "active_release_gate_runs",
        lambda tag_name, *, target: (),
    )
    monkeypatch.setattr(
        release,
        "run_command",
        lambda command, **kwargs: commands.append(command),
    )

    with pytest.raises(
        RuntimeError,
        match=f"published during release preparation.*{destination}",
    ):
        release.main(["all", "--skip-checks", "--retag"])

    assert commands == [("git", "push")]


def test_real_release_refuses_active_release_gate_before_tag_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[tuple[str, ...]] = []
    old_commit = "b" * 40
    new_commit = "a" * 40

    monkeypatch.setattr(release, "read_target_version", lambda target: "0.2.0")
    monkeypatch.setattr(release, "is_dirty_worktree", lambda: False)
    monkeypatch.setattr(
        release,
        "inspect_release_state",
        lambda version, *, target: _state(local=old_commit, remote=old_commit),
    )
    monkeypatch.setattr(release, "current_head_commit", lambda: new_commit)
    monkeypatch.setattr(release, "build_postupdate_steps", tuple)
    monkeypatch.setattr(release, "release_files_changed", lambda target: False)
    monkeypatch.setattr(release, "_require_command", lambda command: None)
    monkeypatch.setattr(
        release,
        "active_release_gate_runs",
        lambda tag_name, *, target: ("https://github.test/actions/runs/123",),
    )
    monkeypatch.setattr(
        release,
        "run_command",
        lambda command, **kwargs: commands.append(command),
    )

    with pytest.raises(RuntimeError, match="release gate is still active"):
        release.main(["all", "--skip-checks", "--retag"])

    assert commands == [("git", "push")]


@pytest.mark.parametrize("local_tag_exists", [True, False])
def test_real_retag_pushes_branch_then_replaces_observed_tag(
    monkeypatch: pytest.MonkeyPatch,
    local_tag_exists: bool,
) -> None:
    commands: list[tuple[str, ...]] = []
    old_commit = "b" * 40
    new_commit = "a" * 40
    initial_state = _state(local=old_commit, remote=old_commit)
    refreshed_state = _state(
        local=old_commit if local_tag_exists else None,
        remote=old_commit,
    )
    states = iter((initial_state, refreshed_state))

    monkeypatch.setattr(release, "read_target_version", lambda target: "0.2.0")
    monkeypatch.setattr(release, "is_dirty_worktree", lambda: False)
    monkeypatch.setattr(
        release,
        "inspect_release_state",
        lambda version, *, target: next(states),
    )
    monkeypatch.setattr(release, "current_head_commit", lambda: new_commit)
    monkeypatch.setattr(release, "build_postupdate_steps", tuple)
    monkeypatch.setattr(release, "release_files_changed", lambda target: False)
    monkeypatch.setattr(release, "_require_command", lambda command: None)
    monkeypatch.setattr(
        release,
        "active_release_gate_runs",
        lambda tag_name, *, target: (),
    )
    monkeypatch.setattr(
        release,
        "run_command",
        lambda command, **kwargs: commands.append(command),
    )

    assert release.main(["all", "--skip-checks", "--retag"]) == 0

    expected_commands = [
        ("git", "push"),
        (
            "git",
            "push",
            f"--force-with-lease=refs/tags/v0.2.0:{old_commit}",
            "origin",
            ":refs/tags/v0.2.0",
        ),
    ]
    if local_tag_exists:
        expected_commands.append(("git", "tag", "-d", "v0.2.0"))
    expected_commands.extend(
        [
            ("git", "tag", "v0.2.0"),
            ("git", "push", "origin", "v0.2.0"),
        ]
    )
    assert commands == expected_commands


def test_active_release_gate_runs_returns_only_incomplete_tag_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_urls: list[str] = []
    monkeypatch.setattr(
        release,
        "origin_remote_url",
        lambda: "git@github.com:VanL/backstitch.git",
    )

    def fake_read_json_url(url: str) -> object:
        seen_urls.append(url)
        return {
            "workflow_runs": [
                {
                    "head_branch": "v0.2.0",
                    "status": "in_progress",
                    "html_url": "https://github.test/runs/1",
                },
                {
                    "head_branch": "v0.2.0",
                    "status": "completed",
                    "html_url": "https://github.test/runs/2",
                },
                {
                    "head_branch": "v0.1.0",
                    "status": "queued",
                    "html_url": "https://github.test/runs/3",
                },
            ]
        }

    monkeypatch.setattr(release, "_read_json_url", fake_read_json_url)

    assert release.active_release_gate_runs("v0.2.0") == ("https://github.test/runs/1",)
    assert "/actions/workflows/release-gate.yml/runs?" in seen_urls[0]
    assert "branch=v0.2.0" in seen_urls[0]


@pytest.mark.parametrize(
    "payload",
    [[], {}, {"workflow_runs": ["not-an-object"]}],
)
def test_active_release_gate_runs_rejects_malformed_responses(
    monkeypatch: pytest.MonkeyPatch,
    payload: object,
) -> None:
    monkeypatch.setattr(
        release,
        "origin_remote_url",
        lambda: "git@github.com:VanL/backstitch.git",
    )
    monkeypatch.setattr(release, "_read_json_url", lambda url: payload)

    with pytest.raises(RuntimeError, match="workflow-runs response.*malformed"):
        release.active_release_gate_runs("v0.2.0")


def test_refresh_release_state_refuses_changed_remote_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        release,
        "active_release_gate_runs",
        lambda tag_name, *, target: (),
    )
    monkeypatch.setattr(
        release,
        "inspect_release_state",
        lambda version, *, target: _state(remote="c" * 40),
    )

    with pytest.raises(RuntimeError, match="changed on origin"):
        release.refresh_release_state_before_tag_mutation(
            "0.2.0",
            target=release.ROOT_RELEASE_TARGET,
            observed_remote_tag_commit="b" * 40,
        )


def test_refresh_release_state_checks_active_gate_before_publication_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_active_runs(tag_name: str, *, target: object) -> tuple[()]:
        calls.append("active-runs")
        return ()

    def fake_inspect(version: str, *, target: object) -> object:
        calls.append("release-state")
        return _state(remote="b" * 40)

    monkeypatch.setattr(release, "active_release_gate_runs", fake_active_runs)
    monkeypatch.setattr(release, "inspect_release_state", fake_inspect)

    release.refresh_release_state_before_tag_mutation(
        "0.2.0",
        target=release.ROOT_RELEASE_TARGET,
        observed_remote_tag_commit="b" * 40,
    )

    assert calls == ["active-runs", "release-state"]


def test_capture_command_preserves_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(
        command: tuple[str, ...],
        *,
        cwd: Path,
        capture_output: bool,
        text: bool,
        encoding: str,
        errors: str,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        assert command == ("git", "rev-parse", "HEAD")
        assert cwd == release.PROJECT_ROOT
        assert capture_output is True
        assert text is True
        assert encoding == "utf-8"
        assert errors == "replace"
        assert check is False
        return subprocess.CompletedProcess(command, 0, "abc123\n", "")

    monkeypatch.setattr(release.subprocess, "run", fake_run)

    result = release._capture_command(("git", "rev-parse", "HEAD"))

    assert result.stdout == "abc123\n"
