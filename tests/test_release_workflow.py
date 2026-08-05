"""Release and trusted-workflow contract tests.

Spec: docs/specs/02-backstitch-core.md [SC-10]
Spec: docs/specs/06-semantic-gates.md [SEM-9], [SEM-9.1], [SEM-10]
Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-12.2]
"""

from __future__ import annotations

import copy
import http.client
import re
import runpy
import subprocess
import tomllib
from pathlib import Path
from typing import Any, cast

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"


def _workflow_text(path: str) -> str:
    return (WORKFLOW_DIR / path).read_text(encoding="utf-8")


def _active_workflow_text(path: str) -> str:
    lines: list[str] = []
    for raw in _workflow_text(path).splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(raw.rstrip())
    return "\n".join(lines)


def _index(text: str, needle: str) -> int:
    position = text.find(needle)
    assert position != -1, f"missing expected workflow text: {needle}"
    return position


def _named_workflow_steps(text: str) -> dict[str, str]:
    steps: dict[str, str] = {}
    for chunk in text.split("\n      - name: ")[1:]:
        name, _, body = chunk.partition("\n")
        steps[name] = body
    return steps


def test_backstitch_runtime_directory_is_ignored_and_untracked() -> None:
    ignored = [
        subprocess.run(
            ["git", "check-ignore", "-q", path],
            cwd=ROOT,
            check=False,
        )
        for path in (
            ".backstitch/review/example.json",
            ".backstitch/semantic-cache/results/example.json",
        )
    ]
    tracked = subprocess.run(
        ["git", "ls-files", ".backstitch"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert all(result.returncode == 0 for result in ignored)
    assert tracked.stdout == ""


def test_ci_checks_release_helper_format_and_types() -> None:
    workflow = _workflow_text("ci.yml")

    assert workflow.count("uses: astral-sh/setup-uv@v7") == 4
    assert workflow.count("enable-cache: false") == 4
    assert workflow.count("run: uv sync --frozen --extra dev") == 3
    assert "uv run ruff format --check" in workflow
    assert "tests\n" in workflow
    assert (
        "uv run mypy backstitch bin/release.py tests --config-file pyproject.toml"
        in workflow
    )
    assert "uv run backstitch check --repo-root ." in workflow


def test_ci_runs_exact_lint_then_suppression_policy_commands() -> None:
    workflow = _active_workflow_text("ci.yml")
    lint_command = (
        "uv run --frozen --no-sync ruff check . bin/check-doc-paths "
        "bin/check-dom15-fixtures bin/coalesce-check"
    )
    suppression_command = (
        "uv run --frozen --no-sync python bin/ruff_suppression_index.py --check"
    )
    active_lines = [line.strip() for line in workflow.splitlines()]

    assert workflow.count(lint_command) == 1
    assert workflow.count(suppression_command) == 1
    lint_index = active_lines.index(lint_command)
    assert active_lines[lint_index + 1] == suppression_command
    assert "Complexity ceiling" not in workflow
    assert "ruff check backstitch bin --select C901" not in workflow


def test_ci_collects_and_uploads_coverage() -> None:
    workflow = _workflow_text("ci.yml")
    coverage_section = workflow.split("  coverage:", 1)[1].split("  binary-wheels:", 1)[
        0
    ]

    assert 'python-version: "3.12"' in coverage_section
    assert '-m "not live_llm and not benchmark"' in coverage_section
    assert "--cov=backstitch --cov-report=" in coverage_section
    assert "uv run coverage report --show-missing" in coverage_section
    assert "uv run coverage xml" in coverage_section
    assert (
        "codecov/codecov-action@fb8b3582c8e4def4969c97caa2f19720cb33a72f"
        in coverage_section
    )
    assert "files: ./coverage.xml" in coverage_section
    assert "fail_ci_if_error: false" in coverage_section
    assert "token: ${{ secrets.CODECOV_TOKEN }}" in coverage_section
    assert "slug: VanL/backstitch" in coverage_section


def test_coverage_policy_and_readme_badge_match_repository() -> None:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        coverage = tomllib.load(handle)["tool"]["coverage"]

    assert coverage["run"]["source"] == ["backstitch"]
    assert coverage["run"]["parallel"] is True
    assert coverage["report"]["show_missing"] is True

    codecov = (ROOT / ".codecov.yml").read_text(encoding="utf-8")
    assert "target: 75%" in codecov
    assert "target: 50%" in codecov
    assert "threshold: 2%" in codecov
    assert "threshold: 15%" in codecov

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "https://codecov.io/gh/VanL/backstitch/branch/main/graph/badge.svg" in readme
    assert "](https://codecov.io/gh/VanL/backstitch)" in readme


def test_local_pytest_enables_live_while_ci_explicitly_disables_it() -> None:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        pytest_options = tomllib.load(handle)["tool"]["pytest"]["ini_options"]
    assert pytest_options["run_live_llm"] is True
    assert any(marker.startswith("benchmark:") for marker in pytest_options["markers"])

    workflow = _workflow_text("ci.yml")
    test_section = workflow.split("  test:", 1)[1].split("  benchmark:", 1)[0]
    assert '-m "not live_llm and not benchmark"' in test_section
    assert (
        "env -u BACKSTITCH_LIVE_LLM uv run pytest "
        "tests/live/test_live_llm.py -q -o run_live_llm=false" in workflow
    )
    assert "grep -Eq 'SKIPPED \\[1\\]'" in workflow


def test_ci_runs_every_benchmark_in_a_standalone_serial_job() -> None:
    workflow = _workflow_text("ci.yml")
    benchmark_section = workflow.split("  benchmark:", 1)[1].split("  coverage:", 1)[0]

    assert "runs-on: ubuntu-latest" in benchmark_section
    assert 'python-version: "3.12"' in benchmark_section
    assert "uv sync --frozen --extra dev" in benchmark_section
    assert "uv run pytest tests -q -n 0 -m benchmark" in benchmark_section
    assert "-n auto" not in benchmark_section
    assert "--dist" not in benchmark_section


def test_ci_has_no_provider_secret_or_live_lane_before_semantic_promotion() -> None:
    workflow = _workflow_text("ci.yml")
    assert "live-llm:" not in workflow
    assert "OPENAI_API_KEY" not in workflow
    assert "BACKSTITCH_CI_LIVE_LLM" not in workflow
    assert "permissions:\n  contents: read" in workflow


def test_trusted_semantic_refresh_separates_reports_from_disposable_cache() -> None:
    workflow = _workflow_text("semantic-refresh.yml")
    active = _active_workflow_text("semantic-refresh.yml")
    steps = _named_workflow_steps(active)

    assert "name: semantic-refresh" in active
    assert "repository_dispatch:" in active
    assert "types: [semantic-refresh]" in active
    assert "workflow_dispatch:" not in active
    assert "push:" not in active
    assert "pull_request:" not in active
    assert "permissions:\n  contents: read" in workflow
    assert "concurrency:" in active
    assert "cancel-in-progress: false" in active
    assert "ref: ${{ github.sha }}" in active
    assert "persist-credentials: false" in active
    assert "submodules: false" in active
    assert "lfs: false" in active
    assert 'test "$(git rev-parse HEAD)" = "${GITHUB_SHA}"' in active
    assert "actions/checkout@93cb6efe18208431cddfb8368fd83d5badbf9bfd" in active
    assert "astral-sh/setup-uv@37802adc94f370d6bfd71619e3f0bf239e1f3b78" in active
    cache_action = "actions/cache"
    cache_pin = "caa296126883cff596d87d8935842f9db880ef25"
    assert f"{cache_action}/restore@{cache_pin}" in active
    assert f"{cache_action}/save@{cache_pin}" in active
    assert "actions/checkout@v5" not in active
    assert "astral-sh/setup-uv@v7" not in active
    assert "actions/cache/restore@v5" not in active
    assert "actions/cache/save@v5" not in active
    assert {
        line.strip().removeprefix("uses: ").split(" #", 1)[0]
        for line in active.splitlines()
        if line.strip().startswith("uses: ")
    } == {
        "actions/checkout@93cb6efe18208431cddfb8368fd83d5badbf9bfd",
        "astral-sh/setup-uv@37802adc94f370d6bfd71619e3f0bf239e1f3b78",
        f"{cache_action}/restore@{cache_pin}",
        f"{cache_action}/save@{cache_pin}",
        "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
    }
    job_preamble = active.split("steps:", 1)[0]
    assert "OPENAI_API_KEY" not in job_preamble
    assert active.count("OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}") == 3
    assert {
        name
        for name, body in steps.items()
        if "OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}" in body
    } == {
        "Require provider credential",
        "Refresh current-source dogfood cache",
        "Measure semantic eval baseline",
    }
    assert 'if [ -z "${OPENAI_API_KEY}" ]; then' in active
    assert "OPENAI_API_KEY is required" in active
    assert "skip" not in active.lower()

    assert "uv sync --locked --extra dev" in active
    assert "env -u LLM_MODEL uv run backstitch analyze" in active
    assert "--repo-root ." in active
    assert '--packets-output "${BACKSTITCH_REPORT_ROOT}/packets.jsonl"' in active
    assert (
        '--packet-report-output "${BACKSTITCH_REPORT_ROOT}/packet-report.json"'
        in active
    )
    assert "env -u LLM_MODEL uv run backstitch eval" in active
    assert active.count("--config pyproject.toml") == 2
    expected_options = {
        "--option analyze.cache_mode read-write",
        "--option verify.enabled true",
        "--option verify.cache_mode read-write",
    }
    for step_name in (
        "Refresh current-source dogfood cache",
        "Measure semantic eval baseline",
    ):
        option_lines = {
            line.strip()
            for line in steps[step_name].splitlines()
            if "--option " in line
        }
        assert option_lines == expected_options
        assert all("${{" not in line for line in option_lines)
        assert "client_payload" not in steps[step_name]
    assert "tests/semantic_eval/v3/manifest.json" in active
    assert "tests/semantic_eval/v3/qualification-candidate/manifest.json" not in active
    assert active.count("continue-on-error: true") == 4

    allowed_cache_paths = (
        "${{ env.BACKSTITCH_CACHE_ROOT }}/packets",
        "${{ env.BACKSTITCH_CACHE_ROOT }}/results",
        "${{ env.BACKSTITCH_CACHE_ROOT }}/baselines",
        "${{ env.BACKSTITCH_CACHE_ROOT }}/verify-results",
    )
    for step_name in (
        "Restore immutable semantic cache",
        "Save immutable semantic cache",
    ):
        path_block = steps[step_name].split("path: |", 1)[1].split("key:", 1)[0]
        assert {
            line.strip() for line in path_block.splitlines() if line.strip()
        } == set(allowed_cache_paths)
    assert (
        "semantic-refresh-v1-cache-v1-${{ github.run_id }}-${{ github.run_attempt }}"
        in active
    )
    assert "restore-keys: semantic-refresh-v1-cache-v1-" in active
    assert "steps.cache-restore.outcome" in active
    assert 'rm -rf "${BACKSTITCH_CACHE_ROOT}"' in active
    assert active.count('rm -rf "${BACKSTITCH_CACHE_ROOT}"') == 1
    assert (
        'if [ "${{ steps.cache-restore.outcome }}" = "failure" ]; then\n'
        '            rm -rf "${BACKSTITCH_CACHE_ROOT}"\n'
        "          fi"
    ) in workflow
    assert "\n        if:" not in steps["Prepare restored semantic cache"]
    assert "\n        if:" not in steps["Measure semantic eval baseline"]
    assert (
        "steps.cache-prep.outcome == 'success' && "
        "steps.analyze.outcome == 'success' && "
        "steps.eval.outcome == 'success'"
    ) in active
    assert "steps.cache-save.outcome" in active
    assert "semantic cache persistence failed" in active

    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in active
    assert "if: always()" in active
    assert "include-hidden-files: true" in active
    assert "retention-days: 14" in steps["Upload review evidence"]
    upload = active.split("- name: Upload review evidence", 1)[1].split(
        "- name: Enforce refresh result", 1
    )[0]
    assert "path: ${{ env.BACKSTITCH_REPORT_ROOT }}" in upload
    assert "semantic-cache" not in upload
    assert "steps.analyze.outcome" in active
    assert "steps.eval.outcome" in active

    restore_position = _index(active, "Restore immutable semantic cache")
    prepare_position = _index(active, "Prepare restored semantic cache")
    analyze_position = _index(active, "Refresh current-source dogfood cache")
    save_position = _index(active, "Save immutable semantic cache")
    upload_position = _index(active, "Upload review evidence")
    enforce_position = _index(active, "Enforce refresh result")
    assert restore_position < prepare_position < analyze_position < save_position
    assert save_position < upload_position < enforce_position

    assert "git commit" not in active
    assert "git push" not in active
    assert "gh pr" not in active


@pytest.mark.parametrize(
    "workflow_name",
    ("semantic-refresh.yml", "semantic-pr-report.yml"),
)
def test_secret_bearing_semantic_workflows_never_use_bare_backstitch(
    workflow_name: str,
) -> None:
    active = _active_workflow_text(workflow_name)
    invocation_lines = [
        line.strip()
        for line in active.splitlines()
        if "uv run" in line and "backstitch" in line
    ]

    assert invocation_lines
    for line in invocation_lines:
        assert re.search(r"\bbackstitch\s+[a-z][a-z-]*\b", line), line


def test_trusted_semantic_pr_report_has_closed_hostile_target_boundary() -> None:
    workflow = _workflow_text("semantic-pr-report.yml")
    active = _active_workflow_text("semantic-pr-report.yml")
    steps = _named_workflow_steps(active)

    assert "name: semantic-pr-report" in active
    assert "repository_dispatch:" in active
    assert "types: [semantic-pr-report]" in active
    assert "workflow_dispatch:" not in active
    assert "pull_request:" not in active
    assert "pull_request_target:" not in active
    assert "permissions:\n  contents: read\n  pull-requests: read" in workflow
    assert "contents: write" not in active
    assert "pull-requests: write" not in active
    assert "group: semantic-pr-report-${{ github.run_id }}" in active
    assert "TOOL_ROOT: ${{ github.workspace }}/tool" in active
    assert "TARGET_ROOT: ${{ github.workspace }}/target" in active
    assert (
        "BACKSTITCH_CACHE_ROOT: "
        "${{ github.workspace }}/tool/.backstitch/semantic-cache" in active
    )
    assert (
        "BACKSTITCH_REPORT_ROOT: "
        "${{ runner.temp }}/semantic-pr-report/.backstitch/review" in active
    )

    tool_checkout = steps["Check out trusted Backstitch"]
    target_checkout = steps["Check out hostile target as data"]
    assert "ref: ${{ github.sha }}" in tool_checkout
    assert "path: tool" in tool_checkout
    assert "repository: ${{ steps.resolve.outputs.head_repo }}" in target_checkout
    assert "ref: ${{ steps.resolve.outputs.head_sha }}" in target_checkout
    assert "path: target" in target_checkout
    for checkout in (tool_checkout, target_checkout):
        assert "persist-credentials: false" in checkout
        assert "submodules: false" in checkout
        assert "lfs: false" in checkout

    assert 'test "$(git -C "${TOOL_ROOT}" rev-parse HEAD)" = "${GITHUB_SHA}"' in active
    assert 'test "$(git -C "${TARGET_ROOT}" rev-parse HEAD)" =' in active
    assert '"${BACKSTITCH_CONFIRMED_HEAD_SHA}"' in active
    assert (
        'uv sync --project "${TOOL_ROOT}" --locked --extra dev'
        in steps["Install locked trusted dependencies"]
    )
    assert "target" not in steps["Install locked trusted dependencies"]

    assert {
        name
        for name, body in steps.items()
        if "OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}" in body
    } == {
        "Require provider credential",
        "Analyze hostile target with trusted Backstitch",
    }
    assert {
        name
        for name, body in steps.items()
        if "GITHUB_TOKEN: ${{ github.token }}" in body
    } == {
        "Resolve pull request identity",
        "Revalidate pull request identity",
    }
    assert (
        "client_payload.pull_request_number" in steps["Resolve pull request identity"]
    )
    assert "client_payload.head_sha" in steps["Resolve pull request identity"]
    assert active.count("client_payload.pull_request_number") == 2
    assert active.count("client_payload.head_sha") == 2
    revalidate = steps["Revalidate pull request identity"]
    assert "resolve_semantic_pr.py" in revalidate
    assert " revalidate" in revalidate

    analyze = steps["Analyze hostile target with trusted Backstitch"]
    assert 'uv run --project "${TOOL_ROOT}" backstitch analyze' in analyze
    assert '--repo-root "${TARGET_ROOT}"' in analyze
    assert '--config "${TOOL_ROOT}/pyproject.toml"' in analyze
    assert "--option analyze.cache_mode read-write" in analyze
    assert "--option verify.enabled true" in analyze
    assert "--option verify.cache_mode read-write" in analyze
    option_lines = {
        line.strip() for line in analyze.splitlines() if "--option " in line
    }
    assert option_lines == {
        "--option analyze.cache_mode read-write",
        "--option verify.enabled true",
        "--option verify.cache_mode read-write",
    }
    assert all("${{" not in line for line in option_lines)
    assert '--output "${BACKSTITCH_REPORT_ROOT}/results.jsonl"' in analyze
    assert "working-directory: target" not in active
    assert 'working-directory: "${TARGET_ROOT}"' not in active
    assert "PYTHONPATH" not in active
    assert "PATH=" not in active

    allowed_cache_paths = {
        "${{ env.BACKSTITCH_CACHE_ROOT }}/packets",
        "${{ env.BACKSTITCH_CACHE_ROOT }}/results",
        "${{ env.BACKSTITCH_CACHE_ROOT }}/baselines",
        "${{ env.BACKSTITCH_CACHE_ROOT }}/verify-results",
    }
    for step_name in (
        "Restore immutable PR semantic cache",
        "Save immutable PR semantic cache",
    ):
        path_block = steps[step_name].split("path: |", 1)[1].split("key:", 1)[0]
        assert {
            line.strip() for line in path_block.splitlines() if line.strip()
        } == allowed_cache_paths
    assert "semantic-pr-report-v1-cache-v1-" in active
    assert "semantic-refresh-v1-cache-v1-" not in active
    assert 'rm -rf "${BACKSTITCH_CACHE_ROOT}"' in active
    assert active.count('rm -rf "${BACKSTITCH_CACHE_ROOT}"') == 1
    assert (
        'if [ "${{ steps.cache-restore.outcome }}" = "failure" ]; then\n'
        '            rm -rf "${BACKSTITCH_CACHE_ROOT}"\n'
        "          fi"
    ) in workflow
    assert "\n        if:" not in steps["Prepare restored PR semantic cache"]
    assert "\n        if:" not in steps["Revalidate pull request identity"]
    assert (
        "steps.cache-prep.outcome == 'success' && steps.analyze.outcome == 'success'"
    ) in active

    upload = steps["Upload semantic PR report"]
    assert "if: always()" in upload
    assert "name: semantic-pr-report-${{ github.run_id }}" in upload
    assert "path: ${{ env.BACKSTITCH_REPORT_ROOT }}" in upload
    assert "semantic-cache" not in upload
    assert "retention-days: 14" in upload
    enforce = steps["Enforce semantic PR report result"]
    for message in (
        "initial pull request identity validation failed",
        "target checkout identity validation failed",
        "final pull request identity validation failed",
        "semantic PR analysis did not complete",
        "semantic PR cache persistence failed",
    ):
        assert message in enforce

    uses = [
        line.strip().removeprefix("uses: ").split(" #", 1)[0]
        for line in active.splitlines()
        if line.strip().startswith("uses: ")
    ]
    assert uses.count("actions/checkout@93cb6efe18208431cddfb8368fd83d5badbf9bfd") == 2
    assert set(uses) == {
        "actions/checkout@93cb6efe18208431cddfb8368fd83d5badbf9bfd",
        "astral-sh/setup-uv@37802adc94f370d6bfd71619e3f0bf239e1f3b78",
        "actions/cache/restore@caa296126883cff596d87d8935842f9db880ef25",
        "actions/cache/save@caa296126883cff596d87d8935842f9db880ef25",
        "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
    }
    for prohibited in (
        "git commit",
        "git push",
        "gh pr",
        "statuses/",
        "check-runs",
        "pulls/*/comments",
        "merge",
    ):
        assert prohibited not in active

    order = [
        "Check out trusted Backstitch",
        "Assert trusted tool identity",
        "Install locked trusted dependencies",
        "Resolve pull request identity",
        "Check out hostile target as data",
        "Assert hostile target identity",
        "Revalidate pull request identity",
        "Analyze hostile target with trusted Backstitch",
        "Save immutable PR semantic cache",
        "Upload semantic PR report",
        "Enforce semantic PR report result",
    ]
    positions = [_index(active, name) for name in order]
    assert positions == sorted(positions)

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "-f event_type=semantic-pr-report" in readme
    assert "client_payload[pull_request_number]" in readme
    assert "client_payload[head_sha]" in readme
    assert "observational" in readme


def _semantic_pr_helper() -> dict[str, object]:
    return runpy.run_path(str(ROOT / ".github/scripts/resolve_semantic_pr.py"))


def _valid_pull_request_payload() -> dict[str, object]:
    return {
        "number": 7,
        "state": "open",
        "base": {
            "ref": "main",
            "repo": {"full_name": "VanL/backstitch"},
        },
        "head": {
            "sha": "a" * 40,
            "repo": {"full_name": "example/backstitch"},
        },
    }


@pytest.mark.parametrize("value", ["", "0", "01", "-1", "1.0", "abc"])
def test_semantic_pr_number_requires_positive_canonical_decimal(value: str) -> None:
    parse_pr_number = _semantic_pr_helper()["parse_pr_number"]

    with pytest.raises(ValueError, match="positive decimal"):
        parse_pr_number(value)  # type: ignore[operator]


@pytest.mark.parametrize(
    "value",
    ["", "A" * 40, "a" * 39, "a" * 41, "g" * 40],
)
def test_semantic_pr_sha_requires_lowercase_full_hex(value: str) -> None:
    parse_head_sha = _semantic_pr_helper()["parse_head_sha"]

    with pytest.raises(ValueError, match="lowercase 40-hex"):
        parse_head_sha(value)  # type: ignore[operator]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (("number", 8), "number"),
        (("state", "closed"), "open"),
        (("base", None), "base"),
        (("base.ref", "develop"), "base"),
        (("base.repo", None), "base repository"),
        (("base.repo.full_name", "other/backstitch"), "base repository"),
        (("head", None), "head"),
        (("head.repo", None), "head repository"),
        (("head.repo.full_name", "../bad"), "head repository"),
        (("head.sha", "b" * 40), "expected head SHA"),
    ],
)
def test_semantic_pr_payload_rejects_every_identity_mismatch(
    mutation: tuple[str, object],
    message: str,
) -> None:
    validate = _semantic_pr_helper()["validate_pull_request"]
    payload = copy.deepcopy(_valid_pull_request_payload())
    target: object = payload
    parts = mutation[0].split(".")
    for part in parts[:-1]:
        assert isinstance(target, dict)
        target = target[part]
    assert isinstance(target, dict)
    target[parts[-1]] = mutation[1]

    with pytest.raises(ValueError, match=message):
        validate(  # type: ignore[operator]
            payload,
            expected_number=7,
            repository="VanL/backstitch",
            expected_head_sha="a" * 40,
        )


def test_semantic_pr_revalidation_rejects_head_repository_movement() -> None:
    validate = _semantic_pr_helper()["validate_pull_request"]
    payload = _valid_pull_request_payload()

    with pytest.raises(ValueError, match="changed head repository"):
        validate(  # type: ignore[operator]
            payload,
            expected_number=7,
            repository="VanL/backstitch",
            expected_head_sha="a" * 40,
            confirmed_head_repo="other/backstitch",
            confirmed_head_sha="a" * 40,
        )


def test_semantic_pr_revalidation_rejects_head_sha_movement() -> None:
    validate = _semantic_pr_helper()["validate_pull_request"]
    payload = _valid_pull_request_payload()

    with pytest.raises(ValueError, match="changed head SHA"):
        validate(  # type: ignore[operator]
            payload,
            expected_number=7,
            repository="VanL/backstitch",
            expected_head_sha="a" * 40,
            confirmed_head_repo="example/backstitch",
            confirmed_head_sha="b" * 40,
        )


def test_semantic_pr_valid_identity_returns_exact_checkout_pair() -> None:
    validate = _semantic_pr_helper()["validate_pull_request"]

    assert validate(  # type: ignore[operator]
        _valid_pull_request_payload(),
        expected_number=7,
        repository="VanL/backstitch",
        expected_head_sha="a" * 40,
    ) == ("example/backstitch", "a" * 40)


def _configure_semantic_pr_main(
    monkeypatch: pytest.MonkeyPatch,
    *,
    output: Path,
) -> tuple[Any, dict[str, object]]:
    helper = _semantic_pr_helper()
    main = cast(Any, helper["main"])
    calls: dict[str, object] = {}

    def fake_api_get(**kwargs: object) -> dict[str, object]:
        calls.update(kwargs)
        return _valid_pull_request_payload()

    monkeypatch.setitem(main.__globals__, "github_api_get", fake_api_get)
    monkeypatch.setenv("GITHUB_REPOSITORY", "VanL/backstitch")
    monkeypatch.setenv("GITHUB_API_URL", "https://api.github.test")
    monkeypatch.setenv("GITHUB_TOKEN", "secret-token")
    monkeypatch.setenv("BACKSTITCH_PR_NUMBER", "7")
    monkeypatch.setenv("BACKSTITCH_EXPECTED_HEAD_SHA", "a" * 40)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    return main, calls


def test_semantic_pr_main_resolves_and_revalidates_through_env_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "github-output"
    main, calls = _configure_semantic_pr_main(
        monkeypatch,
        output=output,
    )

    assert main(["resolve"]) == 0
    assert output.read_text(encoding="utf-8") == (
        f"head_repo=example/backstitch\nhead_sha={'a' * 40}\n"
    )
    assert calls == {
        "api_url": "https://api.github.test",
        "repository": "VanL/backstitch",
        "number": 7,
        "token": "secret-token",
    }
    captured = capsys.readouterr()
    assert "secret-token" not in captured.out
    assert captured.err == ""

    monkeypatch.setenv("BACKSTITCH_CONFIRMED_HEAD_REPO", "example/backstitch")
    monkeypatch.setenv("BACKSTITCH_CONFIRMED_HEAD_SHA", "a" * 40)
    assert main(["revalidate"]) == 0


def test_semantic_pr_main_contains_output_and_transport_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_directory = tmp_path / "output-directory"
    output_directory.mkdir()
    main, _ = _configure_semantic_pr_main(
        monkeypatch,
        output=output_directory,
    )

    assert main(["resolve"]) == 2
    captured = capsys.readouterr()
    assert "semantic PR identity error:" in captured.err
    assert "Traceback" not in captured.err

    def fail_api_get(**kwargs: object) -> dict[str, object]:
        raise TimeoutError("timed out")

    monkeypatch.setitem(main.__globals__, "github_api_get", fail_api_get)
    assert main(["resolve"]) == 2
    captured = capsys.readouterr()
    assert "semantic PR identity error: timed out" in captured.err
    assert "Traceback" not in captured.err

    def fail_incomplete_read(**kwargs: object) -> dict[str, object]:
        raise http.client.IncompleteRead(b"partial", 10)

    monkeypatch.setitem(main.__globals__, "github_api_get", fail_incomplete_read)
    assert main(["resolve"]) == 2
    captured = capsys.readouterr()
    assert "semantic PR identity error:" in captured.err
    assert "Traceback" not in captured.err


def test_local_llm_workflow_is_separate_and_guarded() -> None:
    workflow = _workflow_text("local-llm.yml")
    active = _active_workflow_text("local-llm.yml")

    assert "name: local-llm" in active
    assert "workflow_dispatch:" in active
    # Graduated to run on push to main so the release commit has a green
    # local-llm run for the release gate to require. Still NOT on
    # pull_request: fork-PR exposure is a separate threat-model-gated step.
    assert "push:" in active
    assert "branches: [main]" in active
    assert "pull_request:" not in active
    assert "permissions:" in active
    assert "contents: read" in active
    assert "concurrency:" in active
    assert "group: local-llm-${{ github.ref }}" in active
    assert "cancel-in-progress: false" in active
    assert "2 vCPU / 8 GB" in workflow

    assert "uses: astral-sh/setup-uv@v7" in active
    assert 'python-version: "3.11"' in active
    assert "enable-cache: false" in active
    assert "ollama/ollama@sha256:" in active
    assert "ollama/ollama:latest" not in active
    assert "timeout-minutes: 20" in active
    assert "timeout-minutes: 15" in active
    assert "OLLAMA_CONTEXT_LENGTH:" in active
    assert "OLLAMA_NUM_PREDICT:" in active
    assert "PARAMETER num_ctx ${OLLAMA_CONTEXT_LENGTH}" in workflow
    assert "PARAMETER num_predict ${OLLAMA_NUM_PREDICT}" in workflow
    assert "BACKSTITCH_LOCAL_LLM_BASE_MODEL:" in active
    assert "BACKSTITCH_LOCAL_LLM_BASE_MODEL: llama3.2:3b" in active
    assert "BACKSTITCH_LOCAL_LLM_SERVED_MODEL: backstitch-local-model:latest" in active
    # Deterministic-output tuning from the local bake-off: temperature 0 in the
    # Modelfile, proven server-side alongside num_ctx/num_predict.
    assert "PARAMETER temperature 0" in workflow
    assert 'grep -Eq "^temperature[[:space:]]+0([[:space:]]|$)"' in workflow
    assert "BACKSTITCH_LIVE_LLM_KIND: local" in active
    assert "BACKSTITCH_LOCAL_LLM_ALLOW_NONLOCAL" not in active
    assert "127.0.0.1:11434:11434" in active

    assert "id: restore" in active
    assert "id: pull" in active
    assert "id: model-poll" in active
    assert "restore-keys" not in active
    assert active.count("path: ${{ env.OLLAMA_CACHE_DIR }}") == 2
    assert "continue-on-error: true" in active
    assert (
        "if: ${{ !cancelled() && steps.pull.outcome == 'success' && "
        "steps.model-poll.outcome == 'success' && "
        "steps.restore.outputs.cache-hit != 'true' && "
        "github.ref == 'refs/heads/main' }}"
    ) in active

    # A failed save (permissions/unreadable files) must fail the job on
    # trusted runs instead of hiding behind continue-on-error; "key already
    # exists" does not produce a failure outcome in actions/cache/save@v5.
    assert "if: ${{ !cancelled() && steps.save.outcome == 'failure' }}" in active
    # The context-bound verification greps must be anchored at both ends so
    # neither a prefixed key (foo_num_ctx) nor a longer value (40960 vs 4096)
    # can satisfy the check.
    assert (
        'grep -Eq "^num_ctx[[:space:]]+${OLLAMA_CONTEXT_LENGTH}([[:space:]]|$)"'
        in workflow
    )
    assert (
        'grep -Eq "^num_predict[[:space:]]+${OLLAMA_NUM_PREDICT}([[:space:]]|$)"'
        in workflow
    )
    # Per-run weight provenance: manifest checksums are the only trace of what
    # actually ran (the cache key is tag-based and tags are mutable), and the
    # evidence must be non-empty, not best-effort.
    assert "sha256sum" in active
    assert 'test -n "${manifests}"' in workflow

    test_position = _index(active, "Run local live LLM tests")
    chown_position = _index(active, "Normalize Ollama cache ownership")
    save_position = _index(active, "Save Ollama model cache")
    assert test_position < chown_position < save_position
    save_check_position = _index(active, "Fail on broken cache save")
    assert save_position < save_check_position


def test_release_gate_waits_for_ci_before_publishing() -> None:
    workflow = _workflow_text("release-gate.yml")

    require_position = workflow.index("Require CI and local-llm workflows to be green")
    publish_position = workflow.index("publish-to-pypi:")

    assert require_position < publish_position
    assert '--workflow "CI"' in workflow
    # The Docker/Ollama local-llm lane (Linux-only) must be green on the
    # release commit before publishing, following simplebroker's model of
    # requiring the service-backed test workflow by name.
    assert '--workflow "local-llm"' in workflow
    assert "verify-tag-current:" in workflow
    assert "expected: ${EXPECTED_SHA}" in workflow


def test_release_gate_verifies_tag_matches_package_version() -> None:
    workflow = _workflow_text("release-gate.yml")

    assert "Verify tag matches package version" in workflow
    assert 'TAG_VERSION="${TAG_NAME#v}"' in workflow
    assert 'PACKAGE_PYPROJECT="${PACKAGE_DIR}/pyproject.toml"' in workflow
    assert "tomllib.load" in workflow
    assert "tag {tag} != pyproject version {package_version}" in workflow


def test_release_gate_uses_trusted_publishing_and_attestations() -> None:
    workflow = _workflow_text("release-gate.yml")

    assert "environment:" in workflow
    assert "name: pypi" in workflow
    assert "uses: pypa/gh-action-pypi-publish@" in workflow
    assert "uses: actions/attest@" in workflow
    assert "attestations: write" in workflow
    assert "artifact-metadata: write" in workflow
    assert "id-token: write" in workflow


def test_release_gate_builds_with_backstitch_python_version() -> None:
    workflow = _workflow_text("release-gate.yml")

    assert "uses: astral-sh/setup-uv@v7" in workflow
    assert 'python-version: "3.11"' in workflow
    assert "enable-cache: false" in workflow
    assert "uv build" in workflow


def test_github_release_uploads_only_distributions_and_attestation() -> None:
    workflow = _workflow_text("release-gate.yml")
    github_release_section = workflow.split("  github-release:", 1)[1]

    assert "dist/*.tar.gz" in github_release_section
    assert "dist/*.whl" in github_release_section
    assert "attestations/*.sigstore.json" in github_release_section
    assert "dist/*\n" not in github_release_section
    assert "subject-path" not in github_release_section
