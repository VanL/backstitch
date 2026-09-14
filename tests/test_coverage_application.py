"""Typed intent-coverage application and CLI equivalence.

Spec: docs/specs/02-backstitch-core.md [SC-5], [SC-10]
Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-8.7], [EVC-12.2]
Spec: docs/specs/08-intent-coverage.md [COV-3], [COV-5], [COV-9]
Plan: docs/plans/2026-07-29-architecture-quality-remediation-plan.md Slice 5
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Literal

import pytest

from backstitch import cli, coverage_application
from backstitch.coverage_application import (
    CoverageFailure,
    CoverageRequest,
    CoverageResult,
    publish_coverage,
    run_coverage,
)
from backstitch.intent_coverage_reporting import render_coverage_json
from backstitch.profiles import configured_profile
from backstitch.repository_snapshot import SnapshotCaptureError
from backstitch.resolver import ScanError
from backstitch.settings import (
    BackstitchSettings,
    CoverageSettings,
    ProfileSettings,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CLEAN = FIXTURES / "clean_project"


def _settings(
    *,
    format_name: Literal["text", "json"] = "json",
) -> BackstitchSettings:
    return BackstitchSettings(
        profile_overrides=ProfileSettings(
            spec_roots=("docs/specs",),
            plan_roots=(),
            code_roots=("pkg",),
            test_roots=(),
        ),
        coverage=CoverageSettings(
            format=format_name,
        ),
    )


def _render(result: CoverageResult, format_name: str) -> str:
    document = result.document
    if format_name == "json":
        return render_coverage_json(
            document.payload,
            source_result=document.source_result,
            inherited_counts=document.inherited_counts,
            floors=document.floors,
            unscannable_files=document.unscannable_files,
            issues=document.issues,
            baseline=document.baseline,
            changed_definition_ids=document.changed_definition_ids,
            policy_events=document.policy_events,
            drift_events=document.drift_events,
            stale_doc_trends=document.stale_doc_trends,
            spec_growth=document.spec_growth,
        )
    summary = document.payload["summary"]
    definition_rows = {
        item["definition_id"]: item for item in document.payload["definitions"]
    }
    worklist_lines = "".join(
        "uncovered "
        f"{definition_rows[definition_id]['role']} "
        f"{definition_rows[definition_id]['path']} "
        f"{definition_rows[definition_id]['structural_locator']}\n"
        for definition_id in document.payload["worklist"]
    )
    return (
        "Intent coverage: "
        f"{summary['direct']} direct, {summary['inherited']} inherited, "
        f"{summary['exempt']} exempt, {summary['uncovered']} uncovered, "
        f"{summary['total']} total\n"
        f"{worklist_lines}"
    )


@pytest.mark.parametrize("format_name", ("json", "text"))
def test_coverage_application_matches_cli_bytes_and_exit(
    capsys: pytest.CaptureFixture[str],
    format_name: Literal["text", "json"],
) -> None:
    settings = _settings(format_name=format_name)
    outcome = run_coverage(
        CoverageRequest(
            repo_root=CLEAN,
            profile=configured_profile(settings),
            settings=settings,
        )
    )
    assert isinstance(outcome, CoverageResult)
    expected = _render(outcome, format_name)

    args = cli.build_parser().parse_args(["coverage", str(CLEAN)])
    exit_code = cli._cmd_coverage(args, settings)
    captured = capsys.readouterr()

    assert exit_code == (1 if outcome.blocks_gate else 0)
    assert captured.out == expected
    assert captured.err == ""


def test_coverage_publication_matches_cli_and_cleans_staging(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    application_output = tmp_path / "application/report.json"
    cli_output = tmp_path / "cli/report.json"
    settings = _settings()
    outcome = run_coverage(
        CoverageRequest(
            repo_root=CLEAN,
            profile=configured_profile(settings),
            settings=settings,
            output_path=application_output,
        )
    )
    assert isinstance(outcome, CoverageResult)
    rendered = _render(outcome, "json")

    assert publish_coverage(outcome, rendered) is None
    assert application_output.read_text(encoding="utf-8") == rendered
    assert tuple(application_output.parent.glob(".*.tmp")) == ()

    cli_settings = _settings()
    args = cli.build_parser().parse_args(
        ["coverage", str(CLEAN), "--output", str(cli_output)]
    )
    exit_code = cli._cmd_coverage(args, cli_settings)
    captured = capsys.readouterr()

    assert exit_code == (1 if outcome.blocks_gate else 0)
    assert captured.out == ""
    assert captured.err == ""
    assert cli_output.read_bytes() == application_output.read_bytes()
    assert tuple(cli_output.parent.glob(".*.tmp")) == ()


def test_coverage_application_classifies_snapshot_failure_before_cli_mapping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()

    def fail_capture(*_args: object, **_kwargs: object) -> object:
        raise SnapshotCaptureError(
            "snapshot_unstable",
            "SNAPSHOT_UNSTABLE after 3 capture attempts",
            attempts=3,
        )

    monkeypatch.setattr(
        coverage_application.obligation_runtime,
        "capture_obligation_snapshot",
        fail_capture,
    )
    outcome = run_coverage(
        CoverageRequest(tmp_path, configured_profile(settings), settings)
    )
    assert outcome == CoverageFailure(
        stage="snapshot",
        message="SNAPSHOT_UNSTABLE after 3 capture attempts",
    )

    args = cli.build_parser().parse_args(["coverage", str(tmp_path)])
    with pytest.raises(ScanError, match="SNAPSHOT_UNSTABLE"):
        cli._cmd_coverage(args, settings)


def test_coverage_publication_failure_maps_to_one_cli_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "report.json"
    output.mkdir()
    settings = _settings()
    outcome = run_coverage(
        CoverageRequest(CLEAN, configured_profile(settings), settings, output)
    )
    assert isinstance(outcome, CoverageResult)
    rendered = _render(outcome, "json")
    failure = publish_coverage(outcome, rendered)
    assert isinstance(failure, CoverageFailure)
    assert failure.stage == "publication"

    args = cli.build_parser().parse_args(
        ["coverage", str(CLEAN), "--output", str(output)]
    )
    exit_code = cli._cmd_coverage(args, settings)
    captured = capsys.readouterr()

    assert exit_code == 2
    assert captured.out == ""
    prefix = f"cannot write --output {output}: "
    assert failure.message.startswith(prefix)
    assert captured.err.startswith(f"backstitch: error: {prefix}")
    assert output.is_dir()
    assert tuple(tmp_path.glob(".*.tmp")) == ()


def test_coverage_application_and_cli_remain_provider_free() -> None:
    command = [
        "coverage",
        str(CLEAN),
        "--no-config",
    ]
    snippet = (
        "import sys\n"
        "from backstitch.cli import main\n"
        f"code = main({command!r})\n"
        "assert 'llm' not in sys.modules\n"
        "assert 'backstitch.analysis_llm' not in sys.modules\n"
        "assert code in (0, 1)\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", snippet],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
