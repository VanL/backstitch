"""Typed packet application and CLI equivalence.

Spec: docs/specs/02-backstitch-core.md [SC-5], [SC-7], [SC-10]
Spec: docs/specs/06-semantic-gates.md [SEM-7]
Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-8.3], [EVC-8.7]
Plan: docs/plans/2026-07-29-architecture-quality-remediation-plan.md Slice 5
"""

from __future__ import annotations

from pathlib import Path

import pytest

import backstitch.packet_application as packet_application
from backstitch import cli
from backstitch.config import ProfileConfig
from backstitch.operation_progress import ProgressEvent
from backstitch.packet_application import (
    PacketBlocked,
    PacketFailure,
    PacketRequest,
    PacketResult,
    publish_packets,
)
from backstitch.profiles import get_profile
from backstitch.reporting import render_json
from backstitch.settings import BackstitchSettings, ProfileSettings

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CLEAN = FIXTURES / "clean_project"


def _settings() -> BackstitchSettings:
    return BackstitchSettings(
        profile_overrides=ProfileSettings(
            spec_roots=("docs/specs",),
            plan_roots=(),
            code_roots=("pkg",),
            test_roots=(),
        )
    )


def _profile() -> ProfileConfig:
    return get_profile("backstitch-style-v1").with_overrides(
        spec_roots=("docs/specs",),
        plan_roots=(),
        code_roots=("pkg",),
        test_roots=(),
    )


def test_packet_application_matches_cli_artifact_bytes_and_count(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = _settings()
    application_output = tmp_path / "application.jsonl"
    cli_output = tmp_path / "cli.jsonl"
    outcome = publish_packets(
        PacketRequest(
            repo_root=CLEAN,
            profile=_profile(),
            settings=settings,
            output_path=application_output,
            report_path=None,
            kind="section",
        )
    )
    assert isinstance(outcome, PacketResult)

    args = cli.build_parser().parse_args(
        [
            "packets",
            "--repo-root",
            str(CLEAN),
            "--output",
            str(cli_output),
        ]
    )
    exit_code = cli._cmd_packets(args, settings)
    captured = capsys.readouterr()

    assert exit_code == 0
    assert cli_output.read_bytes() == application_output.read_bytes()
    assert captured.out == ""
    assert captured.err == (
        "".join(f"warning: {warning}\n" for warning in outcome.warnings)
        + f"wrote {outcome.packet_count} packets to {cli_output}\n"
    )


@pytest.mark.parametrize(
    "deadline_phase",
    ("snapshot", "packet_materialization", "packet_accounting"),
)
def test_packet_application_deadline_publishes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    deadline_phase: str,
) -> None:
    now = [0.0]

    def expire_in_phase(event: ProgressEvent) -> None:
        if event.phase == deadline_phase:
            now[0] = 11.0

    monkeypatch.setattr(packet_application, "_monotonic", lambda: now[0])
    output = tmp_path / "packets.jsonl"
    outcome = publish_packets(
        PacketRequest(
            repo_root=CLEAN,
            profile=_profile(),
            settings=_settings(),
            output_path=output,
            report_path=None,
            kind="section",
            progress_sink=expire_in_phase,
        )
    )

    assert isinstance(outcome, PacketFailure)
    assert outcome.stage == "deadline"
    assert outcome.code == "DEADLINE_EXCEEDED"
    assert dict(outcome.details) == {
        "limit_milliseconds": 10000,
        "phase": deadline_phase,
        "configured_key": "obligations.maximum_call_seconds",
        "cooperative_tolerance_milliseconds": 100,
    }
    assert not output.exists()


def test_packet_application_progress_sink_failure_does_not_change_artifact(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline.jsonl"
    with_broken_progress = tmp_path / "broken-progress.jsonl"
    baseline_outcome = publish_packets(
        PacketRequest(
            repo_root=CLEAN,
            profile=_profile(),
            settings=_settings(),
            output_path=baseline,
            report_path=None,
            kind="section",
        )
    )
    seen: list[str] = []

    def broken_sink(event: ProgressEvent) -> None:
        seen.append(event.phase)
        raise RuntimeError("renderer failed")

    progress_outcome = publish_packets(
        PacketRequest(
            repo_root=CLEAN,
            profile=_profile(),
            settings=_settings(),
            output_path=with_broken_progress,
            report_path=None,
            kind="section",
            progress_sink=broken_sink,
        )
    )

    assert isinstance(baseline_outcome, PacketResult)
    assert isinstance(progress_outcome, PacketResult)
    assert seen == ["snapshot"]
    assert with_broken_progress.read_bytes() == baseline.read_bytes()


def test_packet_application_preserves_partial_publication_context(
    tmp_path: Path,
) -> None:
    output = tmp_path / "artifacts/packets.jsonl"
    report = tmp_path / "artifacts/packet-report.json"
    report.mkdir(parents=True)

    outcome = publish_packets(
        PacketRequest(
            repo_root=CLEAN,
            profile=_profile(),
            settings=_settings(),
            output_path=output,
            report_path=report,
            kind="all",
        )
    )

    assert isinstance(outcome, PacketFailure)
    assert outcome.stage == "publication"
    assert outcome.failed_path == report
    assert outcome.published_paths == (output,)
    assert output.is_file()
    assert report.is_dir()
    assert tuple(report.parent.glob(".*.tmp")) == ()


def test_packet_application_and_cli_share_deterministic_block_precedence(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = tmp_path / "repo"
    (repo / "docs/specs").mkdir(parents=True)
    (repo / "pkg").mkdir()
    (repo / "docs/specs/01-x.md").write_text(
        "# X\n\n## Contract [X-1]\n\n_Implementation mapping_:\n\n"
        "- `pkg/missing.py::run`\n",
        encoding="utf-8",
    )
    application_output = tmp_path / "application.jsonl"
    cli_output = tmp_path / "cli.jsonl"
    settings = _settings()
    outcome = publish_packets(
        PacketRequest(
            repo_root=repo,
            profile=_profile(),
            settings=settings,
            output_path=application_output,
            report_path=None,
            kind="section",
        )
    )
    assert isinstance(outcome, PacketBlocked)

    args = cli.build_parser().parse_args(
        [
            "packets",
            "--repo-root",
            str(repo),
            "--output",
            str(cli_output),
        ]
    )
    exit_code = cli._cmd_packets(args, settings)
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == render_json(outcome.pipeline.report)
    assert captured.err == "".join(
        f"warning: {warning}\n" for warning in outcome.warnings
    )
    assert not application_output.exists()
    assert not cli_output.exists()
