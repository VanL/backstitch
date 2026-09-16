"""Release-helper contract tests.

Spec: docs/specs/02-backstitch-core.md [SC-10]
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

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


def test_precheck_propagates_protected_live_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[tuple[str, ...]] = []

    def fake_run_command(
        command: tuple[str, ...],
        *,
        cwd: Path = release.PROJECT_ROOT,
        dry_run: bool = False,
        env_overrides: dict[str, str] | None = None,
    ) -> None:
        assert cwd == release.PROJECT_ROOT
        assert dry_run is False
        commands.append(command)
        if command == release.LIVE_LLM_TEST_COMMAND:
            assert env_overrides == {
                "PYTEST_ADDOPTS": "-x --maxfail=1",
                "BACKSTITCH_LIVE_LLM": "1",
                "BACKSTITCH_LIVE_LLM_KIND": "openai",
            }
            raise subprocess.CalledProcessError(7, command)

    monkeypatch.setattr(release, "_start_local_llm_prewarm", lambda **_kwargs: None)
    monkeypatch.setattr(release, "run_command", fake_run_command)

    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        release.run_precheck_commands()

    assert excinfo.value.returncode == 7
    assert commands[-1] == release.LIVE_LLM_TEST_COMMAND
    assert release.LOCAL_LLM_TEST_COMMAND not in commands


def test_prechecks_include_canonical_ruff_gates() -> None:
    commands = release.build_precheck_commands()

    assert release.RUFF_CHECK_COMMAND in commands
    assert release.RUFF_SUPPRESSION_CHECK_COMMAND in commands


def test_benchmark_precheck_disables_ambient_xdist(
    tmp_path: Path,
) -> None:
    probe = tmp_path / "test_serial_probe.py"
    probe.write_text(
        "import os\n\n"
        "def test_not_in_xdist_worker() -> None:\n"
        '    assert "PYTEST_XDIST_WORKER" not in os.environ\n',
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment.pop("PYTEST_XDIST_WORKER", None)
    environment.pop("PYTEST_XDIST_WORKER_COUNT", None)
    environment["PYTEST_ADDOPTS"] = "-n auto"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(probe),
            "-q",
            "-n",
            "0",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )

    assert result.returncode == 0, result.stdout + result.stderr


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
        "BACKSTITCH_LOCAL_LLM_BASE_MODEL": "qwen2.5-coder:14b-instruct-q4_K_M",
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
        ("uv", "sync", "--frozen", "--group", "release"),
        (
            "uv",
            "run",
            "--frozen",
            "--no-sync",
            "python",
            "-m",
            "build",
            "--no-isolation",
        ),
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


def _repository_settings_payloads() -> dict[str, object]:
    return {
        "/repos/VanL/backstitch/immutable-releases": {"enabled": True},
        "/repos/VanL/backstitch/actions/permissions": {
            "allowed_actions": "selected",
            "sha_pinning_required": True,
        },
        "/repos/VanL/backstitch/actions/permissions/selected-actions": {
            "github_owned_allowed": True,
            "verified_allowed": False,
            "patterns_allowed": [
                "astral-sh/setup-uv@*",
                "codecov/codecov-action@*",
                "pypa/gh-action-pypi-publish@*",
                "softprops/action-gh-release@*",
            ],
        },
        "/repos/VanL/backstitch/environments/pypi": {
            "deployment_branch_policy": {
                "protected_branches": False,
                "custom_branch_policies": True,
            }
        },
        "/repos/VanL/backstitch/environments/pypi/deployment-branch-policies": {
            "branch_policies": [{"type": "tag", "name": "v*"}]
        },
        "/repos/VanL/backstitch/rulesets": [
            {
                "id": 42,
                "name": "Protect release tags",
                "target": "tag",
                "enforcement": "active",
            }
        ],
        "/repos/VanL/backstitch/rulesets/42": {
            "id": 42,
            "name": "Protect release tags",
            "target": "tag",
            "enforcement": "active",
            "bypass_actors": [],
            "conditions": {"ref_name": {"include": ["refs/tags/v*"], "exclude": []}},
            "rules": [{"type": "update"}, {"type": "deletion"}],
        },
    }


def test_repository_settings_accept_only_the_hardened_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads = _repository_settings_payloads()
    monkeypatch.setattr(
        release,
        "_github_api_json",
        lambda path, token: payloads[path],
    )

    assert release.repository_settings_issues("VanL/backstitch", "token") == ()


@pytest.mark.parametrize(
    ("path", "replacement", "message"),
    (
        (
            "/repos/VanL/backstitch/immutable-releases",
            {"enabled": False},
            "immutable releases",
        ),
        (
            "/repos/VanL/backstitch/actions/permissions",
            {"allowed_actions": "all", "sha_pinning_required": True},
            "selected actions",
        ),
        (
            "/repos/VanL/backstitch/actions/permissions",
            {"allowed_actions": "selected", "sha_pinning_required": False},
            "SHA pinning",
        ),
        (
            "/repos/VanL/backstitch/environments/pypi",
            {"deployment_branch_policy": None},
            "pypi environment",
        ),
        ("/repos/VanL/backstitch/rulesets", [], "release-tag ruleset"),
    ),
)
def test_repository_settings_report_each_missing_control(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    replacement: object,
    message: str,
) -> None:
    payloads = _repository_settings_payloads()
    payloads[path] = replacement
    monkeypatch.setattr(
        release,
        "_github_api_json",
        lambda requested, token: payloads[requested],
    )

    issues = release.repository_settings_issues("VanL/backstitch", "token")

    assert any(message in issue for issue in issues)


def test_repository_settings_reject_wrong_selected_action_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads = _repository_settings_payloads()
    selected_path = "/repos/VanL/backstitch/actions/permissions/selected-actions"
    selected = dict(payloads[selected_path])  # type: ignore[call-overload]
    selected["patterns_allowed"] = ["astral-sh/setup-uv@*"]
    payloads[selected_path] = selected
    monkeypatch.setattr(
        release,
        "_github_api_json",
        lambda requested, token: payloads[requested],
    )

    issues = release.repository_settings_issues("VanL/backstitch", "token")

    assert any("third-party action patterns" in issue for issue in issues)


def test_repository_settings_command_is_standalone() -> None:
    args = release._build_parser().parse_args(["--check-repository-settings"])

    assert args.check_repository_settings is True


def test_repository_settings_check_cannot_be_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = release._PreparedRelease(
        current_version="0.2.0",
        target_version="0.2.0",
        state=_state(),
        tag_action="create",
        version_changed=False,
        dirty=False,
    )

    def reject() -> None:
        raise RuntimeError("repository settings blocked release")

    monkeypatch.setattr(release, "require_main_branch", lambda: None)
    monkeypatch.setattr(release, "require_repository_settings", reject)

    with pytest.raises(RuntimeError, match="repository settings blocked release"):
        release._run_real_release(
            SimpleNamespace(publish=False),
            release.ROOT_RELEASE_TARGET,
            prepared,
        )


def test_real_release_requires_main_before_running_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = release._PreparedRelease(
        current_version="0.2.0",
        target_version="0.2.0",
        state=_state(),
        tag_action="create",
        version_changed=False,
        dirty=False,
    )

    def reject() -> None:
        raise RuntimeError("real releases require main")

    monkeypatch.setattr(release, "require_main_branch", reject)
    monkeypatch.setattr(
        release,
        "require_repository_settings",
        lambda: pytest.fail("settings check must follow the branch check"),
    )

    with pytest.raises(RuntimeError, match="require main"):
        release._run_real_release(
            SimpleNamespace(publish=False),
            release.ROOT_RELEASE_TARGET,
            prepared,
        )


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
        )
        == "create"
    )
    assert (
        release.plan_tag_action(
            _state(local=head),
            head_commit=head,
            version_changed=False,
        )
        == "push_local"
    )
    assert (
        release.plan_tag_action(
            _state(remote=head),
            head_commit=head,
            version_changed=False,
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
        private_env_overrides: dict[str, str] | None = None,
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
    assert ("git", "push", "origin", "main") in commands
    assert ("git", "tag", "v0.2.0", release.PENDING_RELEASE_COMMIT) in commands
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
        private_env_overrides: dict[str, str] | None = None,
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

    assert release.main(["all", "--dry-run"]) == 0

    output = capsys.readouterr().out
    assert "dry-run: current backstitch version 0.2.0 is unpublished" in output
    assert ("git", "push", "origin", "main") in commands
    assert ("git", "tag", "v0.2.0", "a" * 40) in commands
    assert ("git", "push", "origin", "v0.2.0") in commands


def test_release_helper_has_no_remote_retag_escape_hatch() -> None:
    parser = release._build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["--retag"])


def test_release_helper_has_no_skip_checks_escape_hatch() -> None:
    parser = release._build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["--skip-checks"])


def test_remote_tag_reuse_note_names_guarded_dispatch_command() -> None:
    note = release._remote_tag_reuse_note(_state(remote="a" * 40))

    assert "gh workflow run release-gate.yml --ref v0.2.0" in note
    assert "already contains the workflow_dispatch trigger" in note
    assert "older tags require a new version" in note


def test_workflow_wait_passes_token_only_through_redacted_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def record(command: tuple[str, ...], **kwargs: object) -> None:
        calls.append((command, kwargs))

    monkeypatch.setattr(release, "_github_api_token", lambda: "top-secret-token")
    monkeypatch.setattr(
        release,
        "origin_remote_url",
        lambda: "git@github.com:VanL/backstitch.git",
    )
    monkeypatch.setattr(release, "run_command", record)

    release.wait_for_release_workflows("a" * 40)

    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command[:6] == (
        "uv",
        "run",
        "--project",
        str(release.PROJECT_ROOT),
        "--locked",
        "python",
    )
    assert ".github/scripts/require_green_workflows.py" in command
    assert command.count("--workflow") == 2
    assert "CI" in command
    assert "local-llm" in command
    assert "top-secret-token" not in " ".join(command)
    assert kwargs["private_env_overrides"] == {"GITHUB_TOKEN": "top-secret-token"}


def test_sensitive_command_environment_is_redacted() -> None:
    rendered = release._format_command_prefix(
        {"SAFE": "visible"},
        private_env_keys=frozenset({"GITHUB_TOKEN"}),
    )

    assert "GITHUB_TOKEN=<redacted>" in rendered
    assert "SAFE=visible" in rendered


def test_private_command_environment_reaches_subprocess_but_not_log(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed_env: dict[str, str] = {}

    def run(command: tuple[str, ...], **kwargs: object) -> None:
        env = kwargs["env"]
        assert isinstance(env, dict)
        observed_env.update(env)

    monkeypatch.setattr(release.subprocess, "run", run)

    release.run_command(
        ("example-command",),
        private_env_overrides={"GITHUB_TOKEN": "top-secret-token"},
    )

    output = capsys.readouterr().out
    assert observed_env["GITHUB_TOKEN"] == "top-secret-token"
    assert "top-secret-token" not in output
    assert "GITHUB_TOKEN=<redacted>" in output


def test_release_sha_must_remain_reachable_from_fetched_main(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[tuple[str, ...]] = []
    sha = "a" * 40
    monkeypatch.setattr(
        release,
        "run_command",
        lambda command, **kwargs: commands.append(command),
    )
    monkeypatch.setattr(
        release,
        "_capture_command",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0, "", ""),
    )

    release.require_release_sha_on_origin_main(sha)

    assert commands == [("git", "fetch", "origin", "main")]


def test_release_sha_removed_from_main_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sha = "a" * 40
    monkeypatch.setattr(release, "run_command", lambda command, **kwargs: None)
    monkeypatch.setattr(
        release,
        "_capture_command",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 1, "", ""),
    )

    with pytest.raises(RuntimeError, match="no longer reachable from origin/main"):
        release.require_release_sha_on_origin_main(sha)


def test_failed_pre_tag_ci_creates_no_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = release.ReleaseCandidate(
        target=release.ROOT_RELEASE_TARGET,
        current_version="0.2.0",
        release_version="0.2.0",
        state=_state(),
    )
    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        release,
        "run_command",
        lambda command, **kwargs: commands.append(command),
    )

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("required workflow run failed")

    monkeypatch.setattr(release, "wait_for_release_workflows", fail)

    with pytest.raises(RuntimeError, match="required workflow run failed"):
        release.publish_release_tags_after_ci((candidate,), "a" * 40)

    assert commands == [("git", "push", "origin", "main")]


def test_failed_origin_main_reachability_creates_no_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = release.ReleaseCandidate(
        target=release.ROOT_RELEASE_TARGET,
        current_version="0.2.0",
        release_version="0.2.0",
        state=_state(),
    )
    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        release,
        "run_command",
        lambda command, **kwargs: commands.append(command),
    )
    monkeypatch.setattr(
        release,
        "wait_for_release_workflows",
        lambda release_sha, **kwargs: None,
    )

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("release SHA no longer reachable")

    monkeypatch.setattr(release, "require_release_sha_on_origin_main", fail)

    with pytest.raises(RuntimeError, match="no longer reachable"):
        release.publish_release_tags_after_ci((candidate,), "a" * 40)

    assert commands == [("git", "push", "origin", "main")]


def test_release_orders_push_wait_reachability_then_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sha = "a" * 40
    candidate = release.ReleaseCandidate(
        target=release.ROOT_RELEASE_TARGET,
        current_version="0.2.0",
        release_version="0.2.0",
        state=_state(),
    )
    events: list[object] = []
    monkeypatch.setattr(
        release,
        "run_command",
        lambda command, **kwargs: events.append(command),
    )
    monkeypatch.setattr(
        release,
        "wait_for_release_workflows",
        lambda release_sha, **kwargs: events.append(("wait", release_sha)),
    )
    monkeypatch.setattr(
        release,
        "require_release_sha_on_origin_main",
        lambda release_sha, **kwargs: events.append(("reachable", release_sha)),
    )
    monkeypatch.setattr(
        release,
        "inspect_release_state",
        lambda version, *, target: _state(),
    )

    release.publish_release_tags_after_ci((candidate,), sha)

    assert events == [
        ("git", "push", "origin", "main"),
        ("wait", sha),
        ("reachable", sha),
        ("git", "tag", "v0.2.0", sha),
        ("git", "push", "origin", "v0.2.0"),
    ]


@pytest.mark.parametrize(
    ("published_state", "destination"),
    [
        (_state(pypi=True), "PyPI"),
        (_state(github=True), "GitHub"),
    ],
)
def test_release_rechecks_publication_after_ci_wait(
    monkeypatch: pytest.MonkeyPatch,
    published_state: object,
    destination: str,
) -> None:
    candidate = release.ReleaseCandidate(
        target=release.ROOT_RELEASE_TARGET,
        current_version="0.2.0",
        release_version="0.2.0",
        state=_state(),
    )
    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        release,
        "run_command",
        lambda command, **kwargs: commands.append(command),
    )
    monkeypatch.setattr(
        release,
        "wait_for_release_workflows",
        lambda release_sha, **kwargs: None,
    )
    monkeypatch.setattr(
        release,
        "require_release_sha_on_origin_main",
        lambda release_sha, **kwargs: None,
    )
    monkeypatch.setattr(
        release,
        "inspect_release_state",
        lambda version, *, target: published_state,
    )

    with pytest.raises(RuntimeError, match=f"pre-tag wait.*{destination}"):
        release.publish_release_tags_after_ci((candidate,), "a" * 40)

    assert commands == [("git", "push", "origin", "main")]


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
