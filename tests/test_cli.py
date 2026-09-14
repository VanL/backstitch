"""Subprocess CLI contract: exit codes, output modes, no tracebacks.

Spec: docs/specs/02-backstitch-core.md [SC-5], [SC-5.1]
Spec: docs/specs/03-backstitch-configuration.md [CFG-5.1], [CFG-9]
Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-12.2]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Literal

import pytest

from backstitch.coverage_application import INTENT_DIAGNOSTIC_CONTEXTS
from backstitch.settings import BackstitchSettings, ProfileSettings

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
        "--no-config",
        "--spec-root",
        "docs/specs",
        "--plan-root",
        "docs/plans",
        "--code-root",
        "pkg",
        *extra,
    )


def test_tty_progress_renderer_is_line_safe_and_portable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backstitch.cli import _tty_progress_sink
    from backstitch.operation_progress import ProgressEvent

    class TTYStderr:
        def __init__(self) -> None:
            self.value = ""
            self.flushes = 0

        def isatty(self) -> bool:
            return True

        def write(self, value: str) -> int:
            self.value += value
            return len(value)

        def flush(self) -> None:
            self.flushes += 1

    stderr = TTYStderr()
    monkeypatch.setattr(sys, "stderr", stderr)
    sink = _tty_progress_sink(enabled=True)
    assert sink is not None

    sink(
        ProgressEvent(
            phase="packet_accounting",
            completed_work_units=2,
            total_work_units=3,
            current_identity="docs/specs/01-core.md#CORE-1",
        )
    )

    assert stderr.value == (
        "backstitch: progress packet_accounting 2/3 docs/specs/01-core.md#CORE-1\n"
    )
    assert stderr.flushes == 1


def write_syntax_warning_repo(root: Path, *, inline_noqa: bool = False) -> None:
    spec_dir = root / "docs" / "specs"
    spec_dir.mkdir(parents=True)
    spec_dir.joinpath("01-x.md").write_text(
        "# X\n\n## Thing [X-1]\n\n_Implementation mapping_:\n\n- `pkg/good.py`\n",
        encoding="utf-8",
    )
    pkg = root / "pkg"
    pkg.mkdir()
    pkg.joinpath("good.py").write_text(
        '"""Spec: docs/specs/01-x.md [X-1]"""\n',
        encoding="utf-8",
    )
    prefix = "# backstitch: noqa PYTHON_SYNTAX_ERROR\n" if inline_noqa else ""
    pkg.joinpath("bad.py").write_text(f"{prefix}def broken(:\n", encoding="utf-8")


def test_clean_repo_exits_zero() -> None:
    result = check_clean()
    assert result.returncode == 0, result.stderr
    assert "0 errors" in result.stdout
    assert "Traceback" not in result.stderr


def test_coverage_report_uses_shared_snapshot_and_trace_graph() -> None:
    result = run_cli(
        "coverage",
        str(CLEAN),
        "--no-config",
        "--format",
        "json",
        "--option",
        "profile.spec_roots",
        '["docs/specs"]',
        "--option",
        "profile.plan_roots",
        "[]",
        "--option",
        "profile.code_roots",
        '["pkg"]',
        "--option",
        "profile.test_roots",
        "[]",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["artifact"] == "backstitch-intent-coverage-report"
    assert payload["summary"]["total"] == 2
    assert payload["summary"]["direct"] == 1
    assert payload["summary"]["inherited"] == 1
    assert payload["worklist"] == []


def test_coverage_path_aliases_are_mutually_exclusive() -> None:
    result = run_cli(
        "coverage",
        str(CLEAN),
        "--repo-root",
        str(CLEAN),
        "--no-config",
    )

    assert result.returncode == 2
    assert "mutually exclusive" in result.stderr
    assert "Traceback" not in result.stderr


def _write_ratchet_repo(
    root: Path,
    *,
    mapping: str = "pkg/api.py::answer",
    extra_coverage: str = "",
    code_roots: str = '["pkg"]',
    test_roots: str = "[]",
) -> None:
    (root / "docs" / "specs").mkdir(parents=True)
    (root / "pkg").mkdir()
    (root / "docs" / "specs" / "01-api.md").write_text(
        (f"# API\n\n## Answer [API-1]\n\n_Implementation mapping_:\n\n- `{mapping}`\n"),
        encoding="utf-8",
    )
    (root / "pkg" / "api.py").write_text(
        (
            '"""API implementation."""\n\n'
            "def answer() -> int:\n"
            '    """Spec: docs/specs/01-api.md [API-1]"""\n'
            "    return 1\n"
        ),
        encoding="utf-8",
    )
    (root / ".backstitch.toml").write_text(
        (
            "[profile]\n"
            'name = "backstitch-style-v1"\n'
            'spec_roots = ["docs/specs"]\n'
            "plan_roots = []\n"
            f"code_roots = {code_roots}\n"
            f"test_roots = {test_roots}\n\n"
            "[coverage]\n"
            'mode = "ratchet"\n'
            'ratchet_base = "baseline"\n'
            'format = "json"\n'
            f"{extra_coverage}"
        ),
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Intent Test",
            "-c",
            "user.email=intent@example.invalid",
            "commit",
            "-qm",
            "base",
        ],
        check=True,
    )
    subprocess.run(["git", "-C", str(root), "branch", "baseline"], check=True)


def _commit_ratchet_change(root: Path, message: str) -> None:
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Intent Test",
            "-c",
            "user.email=intent@example.invalid",
            "commit",
            "-qm",
            message,
        ],
        check=True,
    )


def _prepare_uncovered_diagnostics(root: Path) -> None:
    _write_ratchet_repo(root)
    with (root / "pkg" / "api.py").open("a", encoding="utf-8") as handle:
        handle.write("\n\ndef uncovered() -> None:\n    pass\n")


def _prepare_inherited_diagnostics(root: Path) -> None:
    _write_ratchet_repo(root, mapping="pkg/api.py")
    source = root / "pkg" / "api.py"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "API implementation.",
            "Changed API implementation.",
        ),
        encoding="utf-8",
    )


def _prepare_exemption_and_floor_diagnostics(root: Path) -> None:
    _write_ratchet_repo(
        root,
        extra_coverage=(
            '\n[[coverage.exemptions]]\npath = "pkg/missing.py"\n'
            'reason = "Generated elsewhere."\n\n'
            '[coverage.floors."pkg"]\ndirect = 1.0\n'
        ),
    )


def _prepare_unreasoned_and_unimplemented_diagnostics(root: Path) -> None:
    _write_ratchet_repo(root, mapping="pkg/missing.py::answer")
    source = root / "pkg" / "api.py"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "def answer() -> int:",
            "def answer() -> int:  # backstitch: no-spec",
        ),
        encoding="utf-8",
    )


def _prepare_drift_diagnostics(root: Path) -> None:
    _write_ratchet_repo(root)
    source = root / "pkg" / "api.py"
    source.write_text(
        source.read_text(encoding="utf-8").replace("return 1", "return 2"),
        encoding="utf-8",
    )
    _commit_ratchet_change(root, "change implementation")


def _prepare_incomplete_diagnostics(root: Path) -> None:
    _write_ratchet_repo(root)
    (root / "pkg" / "bad.py").write_text("def broken(:\n", encoding="utf-8")


def _prepare_policy_diagnostics(root: Path) -> None:
    _write_ratchet_repo(root)
    config = root / ".backstitch.toml"
    config.write_text(
        config.read_text(encoding="utf-8") + "\ninherited_counts = true\n",
        encoding="utf-8",
    )
    _commit_ratchet_change(root, "weaken coverage policy")


_INTENT_PRODUCER_SCENARIOS: tuple[tuple[str, Callable[[Path], None]], ...] = (
    ("uncovered", _prepare_uncovered_diagnostics),
    ("inherited", _prepare_inherited_diagnostics),
    ("exemption-and-floor", _prepare_exemption_and_floor_diagnostics),
    ("unreasoned-and-unimplemented", _prepare_unreasoned_and_unimplemented_diagnostics),
    ("drift", _prepare_drift_diagnostics),
    ("incomplete", _prepare_incomplete_diagnostics),
    ("policy", _prepare_policy_diagnostics),
)


def test_every_intent_diagnostic_context_fires_from_a_real_producer(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """Join the declared intent contract to real coverage CLI producers."""

    observed: set[tuple[str, str | None, str]] = set()
    for name, prepare in _INTENT_PRODUCER_SCENARIOS:
        root = tmp_path_factory.mktemp(f"intent-producer-{name}")
        prepare(root)
        result = run_cli(
            "coverage",
            str(root),
            "--require-ratchet",
            "baseline",
        )
        assert result.returncode in {0, 1}, result.stdout + result.stderr
        issues = json.loads(result.stdout)["issues"]
        scenario_facts = {
            (item["code"], item["context"], item["default_severity"])
            for item in issues
            if item["code"].startswith("INTENT_")
        }
        assert scenario_facts, f"{name} did not fire an intent diagnostic"
        assert all(
            item["severity"] == item["default_severity"]
            for item in issues
            if item["code"].startswith("INTENT_")
        )
        observed.update(scenario_facts)

    expected = {
        (code, context, severity)
        for code, contexts in INTENT_DIAGNOSTIC_CONTEXTS.items()
        for context, severity in contexts.items()
    }
    assert observed == expected


def test_coverage_ratchet_marks_dirty_uncovered_definition_as_patch(
    tmp_path: Path,
) -> None:
    _write_ratchet_repo(tmp_path)
    with (tmp_path / "pkg" / "api.py").open("a", encoding="utf-8") as handle:
        handle.write("\n\ndef uncovered() -> None:\n    pass\n")

    result = run_cli(
        "coverage",
        str(tmp_path),
        "--require-ratchet",
        "baseline",
    )

    assert result.returncode == 1, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    patch = [
        item
        for item in payload["issues"]
        if item["code"] == "INTENT_UNCOVERED_DEFINITION" and item["context"] == "patch"
    ]
    assert any(item["symbol"] == "uncovered" for item in patch)
    assert {
        item["context"]
        for item in payload["issues"]
        if item["code"] == "INTENT_UNCOVERED_DEFINITION"
    } == {"repository", "patch"}
    changed = [
        item for item in payload["definitions"] if item["qualname"] == "uncovered"
    ]
    assert changed[0]["changed"] is True
    assert payload["baseline"]["configured_ref"] == "baseline"


def test_coverage_ratchet_rejects_invalid_historical_root_containment(
    tmp_path: Path,
) -> None:
    _write_ratchet_repo(
        tmp_path,
        code_roots='["pkg"]',
        test_roots='["qa"]',
    )
    config = tmp_path / ".backstitch.toml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            'code_roots = ["pkg"]',
            'code_roots = ["pkg", "qa"]',
        ),
        encoding="utf-8",
    )
    (tmp_path / "qa").mkdir()

    result = run_cli(
        "coverage",
        str(tmp_path),
        "--require-ratchet",
        "baseline",
    )

    assert result.returncode == 2
    assert "test root 'qa'" in result.stderr
    assert "Traceback" not in result.stderr
    assert result.stdout == ""


def test_coverage_ratchet_computes_committed_drift_from_exact_projections(
    tmp_path: Path,
) -> None:
    _write_ratchet_repo(tmp_path)
    source = tmp_path / "pkg" / "api.py"
    source.write_text(
        source.read_text(encoding="utf-8").replace("return 1", "return 2"),
        encoding="utf-8",
    )
    _commit_ratchet_change(tmp_path, "change implementation")

    result = run_cli(
        "coverage",
        str(tmp_path),
        "--require-ratchet",
        "baseline",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert len(payload["drift_events"]) == 1
    event = payload["drift_events"][0]
    assert event["transition_commit"] is not None
    assert event["synthetic_current"] is False
    assert any(item["code"] == "INTENT_DRIFT_SUSPECT" for item in payload["issues"])
    assert payload["stale_doc_trends"] == [
        {
            "edge_id": event["edge_id"],
            "section_change_commit": None,
            "unacknowledged_event_count": 1,
            "last_event_commit": event["transition_commit"],
            "history_complete": True,
            "commits_inspected": 1,
        }
    ]


def test_coverage_ratchet_publishes_truncated_stale_history_without_zero_claim(
    tmp_path: Path,
) -> None:
    _write_ratchet_repo(
        tmp_path,
        extra_coverage="maximum_history_commits = 1\n",
    )
    source = tmp_path / "pkg" / "api.py"
    for value in (2, 3, 4):
        source.write_text(
            source.read_text(encoding="utf-8").replace(
                f"return {value - 1}",
                f"return {value}",
            ),
            encoding="utf-8",
        )
        _commit_ratchet_change(tmp_path, f"change implementation {value}")

    result = run_cli(
        "coverage",
        str(tmp_path),
        "--require-ratchet",
        "baseline",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    trend = payload["stale_doc_trends"][0]
    assert trend["history_complete"] is False
    assert trend["commits_inspected"] == 1
    assert trend["unacknowledged_event_count"] == 1
    assert (
        trend["last_event_commit"]
        == subprocess.run(
            ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )


def test_coverage_ratchet_blocks_unacknowledged_committed_policy_weakening(
    tmp_path: Path,
) -> None:
    _write_ratchet_repo(tmp_path)
    config = tmp_path / ".backstitch.toml"
    config.write_text(
        config.read_text(encoding="utf-8") + "\ninherited_counts = true\n",
        encoding="utf-8",
    )
    _commit_ratchet_change(tmp_path, "weaken coverage policy")

    result = run_cli(
        "coverage",
        str(tmp_path),
        "--require-ratchet",
        "baseline",
    )

    assert result.returncode == 1, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert len(payload["policy_events"]) == 1
    assert payload["policy_events"][0]["key"] == "/coverage/inherited_counts"
    issue = next(
        item
        for item in payload["issues"]
        if item["code"] == "INTENT_COVERAGE_POLICY_REGRESSION"
    )
    assert issue["severity"] == "error"

    text_result = run_cli(
        "coverage",
        str(tmp_path),
        "--format",
        "text",
        "--require-ratchet",
        "baseline",
    )
    assert text_result.returncode == 1
    assert "/coverage/inherited_counts" in text_result.stdout
    assert "Backstitch-Coverage-Policy-Ack:" in text_result.stdout
    assert "repository-owned configuration" in text_result.stdout
    assert "rerun `backstitch coverage`" in text_result.stdout


def test_coverage_ratchet_fires_inherited_repository_and_patch_contexts(
    tmp_path: Path,
) -> None:
    _write_ratchet_repo(tmp_path, mapping="pkg/api.py")
    source = tmp_path / "pkg" / "api.py"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "API implementation.",
            "Changed API implementation.",
        ),
        encoding="utf-8",
    )

    result = run_cli(
        "coverage",
        str(tmp_path),
        "--require-ratchet",
        "baseline",
    )

    assert result.returncode == 1, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    contexts = {
        item["context"]
        for item in payload["issues"]
        if item["code"] == "INTENT_INHERITED_ONLY"
    }
    assert contexts == {"repository", "patch"}


def test_coverage_fires_unused_exemption_and_floor_regression(
    tmp_path: Path,
) -> None:
    _write_ratchet_repo(
        tmp_path,
        extra_coverage=(
            '\n[[coverage.exemptions]]\npath = "pkg/missing.py"\n'
            'reason = "Generated elsewhere."\n\n'
            '[coverage.floors."pkg"]\ndirect = 1.0\n'
        ),
    )

    result = run_cli(
        "coverage",
        str(tmp_path),
        "--require-ratchet",
        "baseline",
    )

    assert result.returncode == 1, result.stdout + result.stderr
    codes = {item["code"] for item in json.loads(result.stdout)["issues"]}
    assert "INTENT_EXEMPTION_UNUSED" in codes
    assert "INTENT_COVERAGE_FLOOR_REGRESSION" in codes


def test_coverage_fires_unreasoned_marker_and_unimplemented_requirement(
    tmp_path: Path,
) -> None:
    _write_ratchet_repo(tmp_path, mapping="pkg/missing.py::answer")
    source = tmp_path / "pkg" / "api.py"
    source.write_text(
        source.read_text(encoding="utf-8").replace(
            "def answer() -> int:",
            "def answer() -> int:  # backstitch: no-spec",
        ),
        encoding="utf-8",
    )

    result = run_cli(
        "coverage",
        str(tmp_path),
        "--require-ratchet",
        "baseline",
    )

    assert result.returncode == 1, result.stdout + result.stderr
    codes = {item["code"] for item in json.loads(result.stdout)["issues"]}
    assert "INTENT_EXEMPTION_UNREASONED" in codes
    assert "INTENT_REQUIREMENT_UNIMPLEMENTED" in codes


def test_coverage_ratchet_fires_incomplete_repository_and_patch_contexts(
    tmp_path: Path,
) -> None:
    _write_ratchet_repo(tmp_path)
    (tmp_path / "pkg" / "bad.py").write_text("def broken(:\n", encoding="utf-8")

    result = run_cli(
        "coverage",
        str(tmp_path),
        "--require-ratchet",
        "baseline",
    )

    assert result.returncode == 1, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    contexts = {
        item["context"]
        for item in payload["issues"]
        if item["code"] == "INTENT_COVERAGE_INCOMPLETE"
    }
    assert contexts == {"repository", "patch"}


@pytest.mark.parametrize(
    ("argv", "handler"),
    (
        (
            (
                "check",
                "--repo-root",
                ".",
                "--show-suppressions",
                "--no-config",
            ),
            "_cmd_check",
        ),
        (
            (
                "coverage",
                ".",
                "--format",
                "json",
                "--no-config",
            ),
            "_cmd_coverage",
        ),
        (
            (
                "packets",
                "--repo-root",
                ".",
                "--output",
                "packets.jsonl",
                "--no-config",
            ),
            "_cmd_packets",
        ),
        (
            (
                "obligation",
                "list",
                "--repo-root",
                ".",
                "--format",
                "json",
                "--limit",
                "1",
                "--no-config",
            ),
            "_cmd_obligation",
        ),
        (
            (
                "analyze",
                "--repo-root",
                ".",
                "--packets-output",
                "packets.jsonl",
                "--packet-report-output",
                "packet-report.json",
                "--output",
                "results.jsonl",
                "--report",
                "report.json",
                "--format",
                "json",
                "--no-config",
            ),
            "_cmd_analyze",
        ),
        (
            (
                "analyze",
                "--packets",
                "packets.jsonl",
                "--packet-report",
                "packet-report.json",
                "--compare-repo-root",
                ".",
                "--output",
                "results.jsonl",
                "--report",
                "report.json",
                "--format",
                "json",
                "--no-config",
            ),
            "_cmd_analyze",
        ),
        (
            (
                "eval",
                "--corpus",
                "manifest.json",
                "--output",
                "eval-report.json",
                "--no-config",
            ),
            "_cmd_eval",
        ),
        (
            ("doctor", "--format", "json", "--no-config"),
            "_cmd_doctor",
        ),
        (
            ("config", "path", "--repo-root", ".", "--no-config"),
            "_cmd_config",
        ),
    ),
)
def test_config_consuming_invocation_resolves_settings_once(
    monkeypatch: pytest.MonkeyPatch,
    argv: tuple[str, ...],
    handler: str,
) -> None:
    import backstitch.cli as cli

    original = cli.resolve_config
    calls = 0

    def counted_resolve(*args: object, **kwargs: object) -> BackstitchSettings:
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(cli, "resolve_config", counted_resolve)
    monkeypatch.setattr(cli, handler, lambda *args, **kwargs: 0)

    assert cli.main([*argv, "--option", "diagnostics.fail_on", '["error"]']) == 0
    assert calls == 1


def test_bare_default_check_resolves_once_and_reuses_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backstitch.cli as cli

    settings = BackstitchSettings(default_command="check")
    calls = 0
    received: list[BackstitchSettings] = []

    def counted_resolve(*args: object, **kwargs: object) -> BackstitchSettings:
        nonlocal calls
        calls += 1
        assert kwargs["invocation_command"] is None
        return settings

    def check_handler(
        args: object,
        resolved: BackstitchSettings,
    ) -> int:
        received.append(resolved)
        return 0

    monkeypatch.setattr(cli, "resolve_config", counted_resolve)
    monkeypatch.setattr(cli, "_cmd_check", check_handler)

    assert cli.main([]) == 0
    assert calls == 1
    assert received == [settings]


@pytest.mark.parametrize(
    ("default_command", "argv", "handler_name", "expected_overrides"),
    (
        (
            "check",
            (".", "--format", "json"),
            "_cmd_check",
            {"check.format": "json"},
        ),
        (
            "analyze",
            (
                "--option",
                "diagnostics.fail_on",
                '["error"]',
                ".",
                "--model",
                "gpt-5.4-mini",
            ),
            "_cmd_analyze",
            {"analyze.model": "gpt-5.4-mini"},
        ),
    ),
)
def test_bare_default_forwards_path_and_command_arguments_with_one_resolution(
    monkeypatch: pytest.MonkeyPatch,
    default_command: Literal["check", "analyze"],
    argv: tuple[str, ...],
    handler_name: str,
    expected_overrides: dict[str, object],
) -> None:
    import backstitch.cli as cli

    settings = BackstitchSettings(default_command=default_command)
    calls = 0
    received: list[argparse.Namespace] = []

    def counted_resolve(*args: object, **kwargs: object) -> BackstitchSettings:
        nonlocal calls
        calls += 1
        assert kwargs["invocation_command"] is None
        assert kwargs["cli_options"] == (
            (("diagnostics.fail_on", '["error"]'),)
            if default_command == "analyze"
            else ()
        )
        overrides_by_command = kwargs["cli_overrides_by_command"]
        assert isinstance(overrides_by_command, dict)
        assert overrides_by_command[default_command] == expected_overrides
        return settings

    def handler(
        args: argparse.Namespace,
        resolved: BackstitchSettings,
    ) -> int:
        assert resolved is settings
        received.append(args)
        return 0

    monkeypatch.setattr(cli, "resolve_config", counted_resolve)
    monkeypatch.setattr(cli, handler_name, handler)

    assert cli.main(argv) == 0
    assert calls == 1
    assert received[0].repo_root == Path(".")
    if default_command == "check":
        assert received[0].format == "json"
    else:
        assert received[0].model == "gpt-5.4-mini"


@pytest.mark.parametrize(
    ("default_command", "handler_name", "expected_model"),
    (
        ("check", "_cmd_check", ""),
        ("analyze", "_cmd_analyze", "environment-model"),
    ),
)
def test_bare_cli_scopes_llm_model_after_selecting_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    default_command: str,
    handler_name: str,
    expected_model: str,
) -> None:
    import backstitch.cli as cli

    (tmp_path / ".backstitch.toml").write_text(
        f'default_command = "{default_command}"\n',
        encoding="utf-8",
    )
    received: list[BackstitchSettings] = []

    def handler(args: object, settings: BackstitchSettings) -> int:
        received.append(settings)
        return 0

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LLM_MODEL", "environment-model")
    monkeypatch.setattr(cli, handler_name, handler)

    assert cli.main([]) == 0
    assert received[0].analyze.model == expected_model


def test_explicit_analyze_wins_over_configured_default_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backstitch.cli as cli

    (tmp_path / ".backstitch.toml").write_text(
        'default_command = "check"\n',
        encoding="utf-8",
    )
    calls: list[str] = []

    def analyze_handler(args: object, settings: BackstitchSettings) -> int:
        calls.append("analyze")
        return 0

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_cmd_analyze", analyze_handler)
    monkeypatch.setattr(
        cli,
        "_cmd_check",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("default check redirected explicit analyze")
        ),
    )

    assert cli.main(["analyze", "--repo-root", "."]) == 0
    assert calls == ["analyze"]


def test_bare_no_default_reaches_no_scan_or_cache_handler(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backstitch.cli as cli

    def forbidden(*args: object, **kwargs: object) -> int:
        raise AssertionError("bare disabled invocation dispatched command work")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_cmd_check", forbidden)
    monkeypatch.setattr(cli, "_cmd_analyze", forbidden)

    assert cli.main(["--no-config"]) == 2
    assert not tmp_path.joinpath(".backstitch").exists()


@pytest.mark.parametrize(
    ("argv", "handler"),
    (
        (
            (
                "check",
                "--repo-root",
                ".",
                "--show-suppressions",
                "--no-config",
            ),
            "_cmd_check",
        ),
        (
            (
                "packets",
                "--repo-root",
                ".",
                "--output",
                "packets.jsonl",
                "--report",
                "packet-report.json",
                "--no-config",
            ),
            "_cmd_packets",
        ),
        (
            (
                "obligation",
                "item",
                "--repo-root",
                ".",
                "--find-evidence",
                "--limit",
                "1",
                "--format",
                "json",
                "--no-config",
            ),
            "_cmd_obligation",
        ),
        (
            (
                "analyze",
                "--repo-root",
                ".",
                "--packets-output",
                "packets.jsonl",
                "--packet-report-output",
                "packet-report.json",
                "--output",
                "results.jsonl",
                "--report",
                "report.json",
                "--format",
                "json",
                "--no-config",
            ),
            "_cmd_analyze",
        ),
        (
            (
                "analyze",
                "--packets",
                "packets.jsonl",
                "--packet-report",
                "packet-report.json",
                "--compare-repo-root",
                ".",
                "--output",
                "results.jsonl",
                "--report",
                "report.json",
                "--format",
                "json",
                "--no-config",
            ),
            "_cmd_analyze",
        ),
        (
            (
                "eval",
                "--corpus",
                "manifest.json",
                "--output",
                "eval-report.json",
                "--no-config",
            ),
            "_cmd_eval",
        ),
        (
            ("doctor", "--format", "json", "--no-config"),
            "_cmd_doctor",
        ),
    ),
)
def test_operational_nonaliases_compose_with_generic_options(
    monkeypatch: pytest.MonkeyPatch,
    argv: tuple[str, ...],
    handler: str,
) -> None:
    import backstitch.cli as cli

    monkeypatch.setattr(cli, handler, lambda *args, **kwargs: 0)

    assert cli.main([*argv, "--option", "diagnostics.fail_on", '["error"]']) == 0


def test_check_handler_uses_injected_settings_without_ambient_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backstitch.cli as cli

    args = cli.build_parser().parse_args(
        ["check", "--repo-root", str(CLEAN), "--format", "json"]
    )
    settings = BackstitchSettings(
        profile_overrides=ProfileSettings(
            spec_roots=("docs/specs",),
            plan_roots=("docs/plans",),
            code_roots=("pkg",),
            test_roots=(),
        )
    )
    monkeypatch.setattr(
        cli,
        "resolve_config",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("handler reread ambient configuration")
        ),
    )

    assert cli._cmd_check(args, settings) == 0


def test_check_routes_through_the_snapshot_backed_core(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_syntax_warning_repo(tmp_path)

    import backstitch.check_application as check_application
    import backstitch.cli as cli

    original = check_application.check_repository
    calls = 0

    def observe(
        request: check_application.CheckRequest,
    ) -> check_application.CheckResult | check_application.CheckFailure:
        nonlocal calls
        calls += 1
        return original(request)

    monkeypatch.setattr(check_application, "check_repository", observe)

    exit_code = cli.main(
        [
            "check",
            "--repo-root",
            str(tmp_path),
            "--spec-root",
            "docs/specs",
            "--code-root",
            "pkg",
            "--format",
            "json",
        ]
    )

    assert exit_code == 0
    assert calls == 1
    assert json.loads(capsys.readouterr().out)["summary"]["warnings"] == 1


def test_python_syntax_warning_does_not_fail_check_by_default(tmp_path: Path) -> None:
    write_syntax_warning_repo(tmp_path)
    result = run_cli(
        "check",
        "--repo-root",
        str(tmp_path),
        "--spec-root",
        "docs/specs",
        "--code-root",
        "pkg",
        "--format",
        "json",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["summary"]["warnings"] == 1
    assert data["issues"][0]["code"] == "PYTHON_SYNTAX_ERROR"
    assert data["issues"][0]["severity"] == "warning"


def test_python_syntax_warning_fails_check_with_warnings_as_errors(
    tmp_path: Path,
) -> None:
    write_syntax_warning_repo(tmp_path)
    result = run_cli(
        "check",
        "--repo-root",
        str(tmp_path),
        "--spec-root",
        "docs/specs",
        "--code-root",
        "pkg",
        "--warnings-as-errors",
        "--format",
        "json",
    )
    assert result.returncode == 1, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["issues"][0]["code"] == "PYTHON_SYNTAX_ERROR"
    assert data["issues"][0]["severity"] == "warning"
    assert data["issues"][0]["default_severity"] == "warning"


def test_all_info_policy_exits_zero_and_preserves_default_severity(
    tmp_path: Path,
) -> None:
    write_syntax_warning_repo(tmp_path)
    config = tmp_path / ".backstitch.toml"
    config.write_text(
        "\n".join(
            [
                "[profile]",
                'name = "backstitch-style-v1"',
                'spec_roots = ["docs/specs"]',
                "plan_roots = []",
                'code_roots = ["pkg"]',
                "",
                "[diagnostics]",
                "fail_on = []",
                "",
                "[[diagnostics.levels]]",
                'select = ["*"]',
                'level = "info"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    result = run_cli("check", "--repo-root", str(tmp_path), "--format", "json")
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    issue = data["issues"][0]
    assert issue["code"] == "PYTHON_SYNTAX_ERROR"
    assert issue["severity"] == "info"
    assert issue["default_severity"] == "warning"


def test_all_error_policy_exits_one_for_former_warning(tmp_path: Path) -> None:
    write_syntax_warning_repo(tmp_path)
    (tmp_path / ".backstitch.toml").write_text(
        "\n".join(
            [
                "[profile]",
                'name = "backstitch-style-v1"',
                'spec_roots = ["docs/specs"]',
                "plan_roots = []",
                'code_roots = ["pkg"]',
                "",
                "[[diagnostics.levels]]",
                'select = ["*"]',
                'level = "error"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    result = run_cli("check", "--repo-root", str(tmp_path), "--format", "json")
    assert result.returncode == 1, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["issues"][0]["severity"] == "error"
    assert data["issues"][0]["default_severity"] == "warning"


def test_off_policy_hides_issue_but_show_suppressions_audits_it(
    tmp_path: Path,
) -> None:
    write_syntax_warning_repo(tmp_path)
    (tmp_path / ".backstitch.toml").write_text(
        "\n".join(
            [
                "[profile]",
                'name = "backstitch-style-v1"',
                'spec_roots = ["docs/specs"]',
                "plan_roots = []",
                'code_roots = ["pkg"]',
                "",
                "[diagnostics]",
                "fail_on = []",
                "",
                "[[diagnostics.levels]]",
                'select = ["PYTHON_SYNTAX_ERROR"]',
                'level = "off"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    result = run_cli(
        "check",
        "--repo-root",
        str(tmp_path),
        "--show-suppressions",
        "--format",
        "json",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["issues"] == []
    assert data["summary"]["warnings"] == 0
    assert data["suppressed_issues"][0]["code"] == "PYTHON_SYNTAX_ERROR"
    assert data["suppressed_issues"][0]["reason"] == "diagnostic level off"


def test_packets_obeys_diagnostic_fail_on_policy(tmp_path: Path) -> None:
    write_syntax_warning_repo(tmp_path)
    (tmp_path / ".backstitch.toml").write_text(
        "\n".join(
            [
                "[profile]",
                'name = "backstitch-style-v1"',
                'spec_roots = ["docs/specs"]',
                "plan_roots = []",
                'code_roots = ["pkg"]',
                "",
                "[diagnostics]",
                'fail_on = ["warning"]',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "packets.jsonl"
    result = run_cli(
        "packets",
        "--repo-root",
        str(tmp_path),
        "--output",
        str(output),
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert not output.exists()


def test_packets_obeys_all_error_all_info_and_off_policy(tmp_path: Path) -> None:
    write_syntax_warning_repo(tmp_path)
    config = tmp_path / ".backstitch.toml"
    output = tmp_path / "packets.jsonl"
    profile = "\n".join(
        [
            "[profile]",
            'name = "backstitch-style-v1"',
            'spec_roots = ["docs/specs"]',
            "plan_roots = []",
            'code_roots = ["pkg"]',
            "",
        ]
    )

    cases = (
        ("error", "error", 1),
        ("info", "info", 1),
        ("off", "warning", 0),
    )
    for level, fail_on, expected_exit in cases:
        output.unlink(missing_ok=True)
        config.write_text(
            profile
            + "\n".join(
                [
                    "[diagnostics]",
                    f'fail_on = ["{fail_on}"]',
                    "",
                    "[[diagnostics.levels]]",
                    'select = ["PYTHON_SYNTAX_ERROR"]',
                    f'level = "{level}"',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        result = run_cli(
            "packets",
            "--repo-root",
            str(tmp_path),
            "--output",
            str(output),
        )
        assert result.returncode == expected_exit, (
            level,
            result.stdout,
            result.stderr,
        )
        if expected_exit == 0:
            assert output.read_text(encoding="utf-8").strip()
        else:
            assert not output.exists()


def test_default_level_config_changes_real_check_output(tmp_path: Path) -> None:
    write_syntax_warning_repo(tmp_path)
    (tmp_path / ".backstitch.toml").write_text(
        "\n".join(
            [
                "[profile]",
                'name = "backstitch-style-v1"',
                'spec_roots = ["docs/specs"]',
                "plan_roots = []",
                'code_roots = ["pkg"]',
                "",
                "[diagnostics]",
                'default_level = "error"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = run_cli("check", "--repo-root", str(tmp_path), "--format", "json")
    assert result.returncode == 1, result.stdout + result.stderr
    issue = next(
        item
        for item in json.loads(result.stdout)["issues"]
        if item["code"] == "PYTHON_SYNTAX_ERROR"
    )
    assert issue["severity"] == "error"
    assert issue["default_severity"] == "warning"


def test_suppressible_levels_config_changes_real_suppression_output(
    tmp_path: Path,
) -> None:
    write_syntax_warning_repo(tmp_path)
    (tmp_path / ".backstitch.toml").write_text(
        "\n".join(
            [
                "[profile]",
                'name = "backstitch-style-v1"',
                'spec_roots = ["docs/specs"]',
                "plan_roots = []",
                'code_roots = ["pkg"]',
                "",
                "[diagnostics]",
                "suppressible_levels = []",
                "",
                "[lint.per-file-ignores]",
                '"pkg/bad.py" = ["PYTHON_SYNTAX_ERROR"]',
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = run_cli(
        "check",
        "--repo-root",
        str(tmp_path),
        "--show-suppressions",
        "--format",
        "json",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert any(i["code"] == "PYTHON_SYNTAX_ERROR" for i in data["issues"])
    assert any(i["code"] == "SUPPRESSION_UNSUPPRESSIBLE_CODE" for i in data["issues"])
    assert not any(
        i["code"] == "PYTHON_SYNTAX_ERROR" for i in data["suppressed_issues"]
    )


def test_no_config_help_names_packaged_defaults() -> None:
    help_commands = (
        ("--help",),
        ("check", "--help"),
        ("packets", "--help"),
        ("analyze", "--help"),
        ("doctor", "--help"),
        ("config", "show", "--help"),
        ("config", "path", "--help"),
    )
    for args in help_commands:
        result = run_cli(*args)
        assert result.returncode == 0, result.stderr
        assert (
            "skip repository configuration; packaged defaults still load"
            in " ".join(result.stdout.split())
        )


def test_python_syntax_warning_does_not_fail_packets(tmp_path: Path) -> None:
    write_syntax_warning_repo(tmp_path)
    output = tmp_path / "packets.jsonl"
    result = run_cli(
        "packets",
        "--repo-root",
        str(tmp_path),
        "--spec-root",
        "docs/specs",
        "--code-root",
        "pkg",
        "--output",
        str(output),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert output.read_text(encoding="utf-8").strip()


def test_python_syntax_warning_config_suppression_and_inline_noqa_boundary(
    tmp_path: Path,
) -> None:
    write_syntax_warning_repo(tmp_path, inline_noqa=True)
    unsuppressed = run_cli(
        "check",
        "--repo-root",
        str(tmp_path),
        "--spec-root",
        "docs/specs",
        "--code-root",
        "pkg",
        "--format",
        "json",
    )
    unsuppressed_data = json.loads(unsuppressed.stdout)
    assert any(i["code"] == "PYTHON_SYNTAX_ERROR" for i in unsuppressed_data["issues"])

    (tmp_path / ".backstitch.toml").write_text(
        '[lint.per-file-ignores]\n"pkg/bad.py" = ["PYTHON_SYNTAX_ERROR"]\n',
        encoding="utf-8",
    )
    suppressed = run_cli(
        "check",
        "--repo-root",
        str(tmp_path),
        "--spec-root",
        "docs/specs",
        "--code-root",
        "pkg",
        "--show-suppressions",
        "--format",
        "json",
    )
    assert suppressed.returncode == 0, suppressed.stdout + suppressed.stderr
    suppressed_data = json.loads(suppressed.stdout)
    assert not any(
        i["code"] == "PYTHON_SYNTAX_ERROR" for i in suppressed_data["issues"]
    )
    assert any(
        i["code"] == "PYTHON_SYNTAX_ERROR" and i["reason"] == "config_file"
        for i in suppressed_data["suppressed_issues"]
    )


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


def test_deterministic_commands_do_not_import_llm(tmp_path: Path) -> None:
    """Tests-invariant: [INV.CLI.1]"""

    output = tmp_path / "packets.jsonl"
    commands = [
        [
            "check",
            "--repo-root",
            str(CLEAN),
            "--no-config",
            "--spec-root",
            "docs/specs",
            "--plan-root",
            "docs/plans",
            "--code-root",
            "pkg",
        ],
        [
            "packets",
            "--repo-root",
            str(CLEAN),
            "--no-config",
            "--spec-root",
            "docs/specs",
            "--plan-root",
            "docs/plans",
            "--code-root",
            "pkg",
            "--output",
            str(output),
        ],
        [
            "obligation",
            "list",
            "--repo-root",
            str(CLEAN),
            "--no-config",
            "--format",
            "json",
        ],
        ["guide", "alignment", "--format", "json"],
    ]
    for command in commands:
        snippet = (
            "import sys\n"
            "from backstitch.cli import main\n"
            f"code = main({command!r})\n"
            "assert 'llm' not in sys.modules, sorted(k for k in sys.modules if k == 'llm')\n"
            "raise SystemExit(code)\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", snippet],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr


def test_bare_no_default_does_not_import_llm_or_dispatch_command() -> None:
    snippet = (
        "import sys\n"
        "from backstitch.cli import main\n"
        "code = main(['--no-config'])\n"
        "assert code == 2, code\n"
        "assert 'llm' not in sys.modules\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", snippet],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "a command is required unless configuration sets default_command" in (
        result.stderr
    )
