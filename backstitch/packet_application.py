"""Typed application seam for source packet production and publication.

Spec: docs/specs/02-backstitch-core.md [SC-5], [SC-7], [SC-17]
Spec: docs/specs/06-semantic-gates.md [SEM-7]
Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-8.3], [EVC-8.7]
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, TypeAlias

from backstitch import (
    analysis_packets,
    artifact_publication,
    obligation_runtime,
    semantic_reports,
)
from backstitch.check_pipeline import CheckPipelineResult
from backstitch.config import ProfileConfig
from backstitch.evidence_discovery import EvidenceDiscoveryError
from backstitch.operation_progress import (
    OperationDeadlineExceeded,
    OperationProgress,
    ProgressSink,
)
from backstitch.repository_snapshot import SnapshotCaptureError
from backstitch.settings import BackstitchSettings

__all__ = (
    "PacketBlocked",
    "PacketFailure",
    "PacketRequest",
    "PacketResult",
    "publish_packets",
)

PacketKind: TypeAlias = Literal["section", "invariant", "suppression", "all"]
PacketFailureStage: TypeAlias = Literal[
    "snapshot",
    "packet",
    "discovery",
    "report",
    "publication",
    "deadline",
]
PacketFailureDetail: TypeAlias = str | int | None


@dataclass(frozen=True, slots=True)
class PacketRequest:
    """Resolved inputs and final paths for one packet publication."""

    repo_root: Path
    profile: ProfileConfig
    settings: BackstitchSettings
    output_path: Path
    report_path: Path | None
    kind: PacketKind
    progress_sink: ProgressSink | None = field(
        default=None,
        compare=False,
        repr=False,
    )


@dataclass(frozen=True, slots=True)
class PacketResult:
    """A complete packet artifact set published in caller-specified order."""

    pipeline: CheckPipelineResult
    warnings: tuple[str, ...]
    packet_count: int


@dataclass(frozen=True, slots=True)
class PacketBlocked:
    """Deterministic policy blocked packet generation before publication."""

    pipeline: CheckPipelineResult
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PacketFailure:
    """One typed packet-production failure before CLI message rendering."""

    stage: PacketFailureStage
    message: str
    warnings: tuple[str, ...] = ()
    code: str | None = None
    details: tuple[tuple[str, PacketFailureDetail], ...] = ()
    failed_path: Path | None = None
    published_paths: tuple[Path, ...] = ()


def _discovery_details(
    error: EvidenceDiscoveryError,
) -> tuple[tuple[str, PacketFailureDetail], ...]:
    details: list[tuple[str, PacketFailureDetail]] = []
    for key, value in sorted(error.details.items()):
        if value is not None and not isinstance(value, (str, int)):
            raise TypeError(f"unsupported evidence-discovery detail: {key}")
        details.append((key, value))
    return tuple(details)


def _monotonic() -> float:
    """Return the operation clock through one deterministic test seam."""

    return time.monotonic()


def _deadline_failure(error: OperationDeadlineExceeded) -> PacketFailure:
    return PacketFailure(
        stage="deadline",
        code="DEADLINE_EXCEEDED",
        message="Packet generation exceeded its configured deadline.",
        details=(
            ("limit_milliseconds", error.limit_milliseconds),
            ("phase", error.phase),
            ("configured_key", "obligations.maximum_call_seconds"),
            (
                "cooperative_tolerance_milliseconds",
                error.cooperative_tolerance_milliseconds,
            ),
        ),
    )


def publish_packets(  # noqa: C901 approved [SC-17.1] RUFF-SUP-056 exception
    request: PacketRequest,
) -> PacketResult | PacketBlocked | PacketFailure:
    """Build one source packet corpus and publish its requested artifacts."""

    progress = OperationProgress.start(
        request.settings.obligations.maximum_call_seconds,
        clock=_monotonic,
        sink=request.progress_sink,
    )
    try:
        runtime = obligation_runtime.build_obligation_runtime(
            request.repo_root,
            request.profile,
            request.settings,
            progress=progress,
        )
    except OperationDeadlineExceeded as exc:
        return _deadline_failure(exc)
    except SnapshotCaptureError as exc:
        return PacketFailure(stage="snapshot", code=exc.kind, message=str(exc))
    pipeline = runtime.pipeline
    fail_on = set(request.settings.diagnostics.fail_on)
    if any(issue.severity in fail_on for issue in pipeline.report.issues):
        return PacketBlocked(pipeline=pipeline, warnings=pipeline.warnings)
    try:
        plan = analysis_packets.plan_source_aligned_packets(
            runtime,
            require_complete_corpus=request.report_path is not None,
            kind=request.kind,
            progress=progress,
        )
        if not plan.complete:
            return PacketFailure(
                stage="packet",
                code="PACKET_BUDGET_EXHAUSTED",
                message=(
                    f"packet plan crossed {plan.crossed_ceiling} at "
                    f"{plan.first_crossing_packet_id}"
                ),
                warnings=pipeline.warnings,
                details=(
                    ("measured_packet_count", plan.measured_packet_count),
                    ("unmeasured_packet_count", plan.unmeasured_packet_count),
                    ("measured_packet_bytes", plan.measured_packet_bytes),
                    ("measured_prompt_bytes", plan.measured_prompt_bytes),
                ),
            )
    except analysis_packets.SourceAlignedPacketError as exc:
        return PacketFailure(
            stage="packet",
            code=exc.code,
            message=str(exc),
            warnings=pipeline.warnings,
        )
    except OperationDeadlineExceeded as exc:
        return _deadline_failure(exc)
    except EvidenceDiscoveryError as exc:
        return PacketFailure(
            stage="discovery",
            code=exc.code,
            message=str(exc),
            warnings=pipeline.warnings,
            details=_discovery_details(exc),
        )
    packets = list(plan.packets)
    rendered = plan.packet_jsonl
    try:
        packet_report = (
            semantic_reports.build_source_packet_report(
                runtime,
                packet_plan=plan,
            )
            if request.report_path is not None
            else None
        )
    except semantic_reports.PacketReportError as exc:
        return PacketFailure(
            stage="report",
            message=str(exc),
            warnings=pipeline.warnings,
        )
    try:
        progress.advance(
            "packet_accounting",
            completed_work_units=len(packets),
            total_work_units=len(packets),
            current_identity=runtime.snapshot.snapshot_hash,
        )
        progress.advance(
            "complete",
            completed_work_units=len(packets),
            total_work_units=len(packets),
            current_identity=runtime.snapshot.snapshot_hash,
        )
    except OperationDeadlineExceeded as exc:
        return _deadline_failure(exc)
    artifacts = [(request.output_path, rendered)]
    if request.report_path is not None:
        assert packet_report is not None
        artifacts.append((request.report_path, packet_report.to_json_bytes()))
    try:
        artifact_publication.publish_artifact_set(artifacts)
    except artifact_publication.ArtifactPublicationError as exc:
        return PacketFailure(
            stage="publication",
            message=str(exc),
            warnings=pipeline.warnings,
            failed_path=exc.failed_path,
            published_paths=exc.published_paths,
        )
    return PacketResult(
        pipeline=pipeline,
        warnings=pipeline.warnings,
        packet_count=len(packets),
    )
