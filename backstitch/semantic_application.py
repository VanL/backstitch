"""Typed application seam for current and historical semantic analysis.

Spec: docs/specs/02-backstitch-core.md [SC-5], [SC-7], [SC-17]
Spec: docs/specs/06-semantic-gates.md [SEM-1], [SEM-7]
Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-5.1], [EVC-8.7],
[EVC-9]
"""

from __future__ import annotations

import hashlib
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from backstitch import (
    analysis_packets,
    artifact_publication,
    obligation_runtime,
    semantic_analysis,
)
from backstitch.analysis_packets import (
    PacketPlan,
    SourceAlignedPacketError,
)
from backstitch.artifact_contracts import ValidatedSemanticPacket, load_packets_bytes
from backstitch.canonical import canonical_json_bytes
from backstitch.config import ProfileConfig, uncontained_test_root
from backstitch.evidence_discovery import EvidenceDiscoveryError
from backstitch.models import Report
from backstitch.operation_progress import (
    OperationDeadlineExceeded,
    OperationProgress,
    ProgressSink,
)
from backstitch.repository_snapshot import SnapshotCaptureError
from backstitch.semantic_budget import (
    AnalyzerBudgetProjection,
    project_cold_analyzer_budget,
    validate_cost_contract,
)
from backstitch.semantic_cache import AdapterFactory
from backstitch.semantic_identity import ResolvedInference
from backstitch.semantic_policy import SemanticPolicy
from backstitch.semantic_reports import (
    PacketReport,
    PacketReportError,
    build_source_packet_report,
    load_packet_report,
    validate_packet_report,
)
from backstitch.settings import (
    BackstitchSettings,
    VerifyEvalSettings,
    settings_to_json,
)

__all__ = (
    "SemanticApplicationFailure",
    "SemanticApplicationRequest",
    "SemanticApplicationResult",
    "SemanticPreparationBlocked",
    "SemanticPreflightResult",
    "SemanticReadinessBlocked",
    "analyze_semantics",
    "preflight_semantics",
    "validate_analysis_mode",
)

FailureStage = Literal[
    "validation",
    "snapshot",
    "alignment",
    "deterministic",
    "packet",
    "discovery",
    "report",
    "input",
    "currentness",
    "publication",
    "deadline",
    "config",
    "budget",
]


@dataclass(frozen=True, slots=True)
class SemanticApplicationRequest:
    """Resolved inputs for one current or historical analysis workflow."""

    settings: BackstitchSettings
    profile: ProfileConfig
    semantic_settings: semantic_analysis.ResolvedSemanticSettings
    policy: SemanticPolicy
    adapter_factory: AdapterFactory | None
    verification_settings: semantic_analysis.ResolvedVerificationSettings | None
    evaluation_settings: VerifyEvalSettings | None
    verification_adapter_factory: AdapterFactory | None
    repo_root: Path | None = None
    packets_path: Path | None = None
    packet_report_path: Path | None = None
    compare_repo_root: Path | None = None
    packets_output_path: Path | None = None
    packet_report_output_path: Path | None = None
    result_output_path: Path | None = None
    report_output_path: Path | None = None
    progress_sink: ProgressSink | None = field(
        default=None,
        compare=False,
        repr=False,
    )


@dataclass(frozen=True, slots=True)
class SemanticApplicationResult:
    """One completed semantic run after any required publication."""

    run: semantic_analysis.SemanticAnalysisRun


@dataclass(frozen=True, slots=True)
class SemanticReadinessBlocked:
    """A deterministic current-repository gate blocked provider work."""

    report: Report


@dataclass(frozen=True, slots=True)
class SemanticApplicationFailure:
    """One workflow failure before CLI presentation and exit mapping."""

    stage: FailureStage
    message: str
    code: str | None = None
    details: tuple[tuple[str, object], ...] = ()
    failed_path: Path | None = None
    published_paths: tuple[Path, ...] = ()


@dataclass(frozen=True, slots=True)
class SemanticPreflightResult:
    """Closed provider-free preparation assessment for CLI presentation."""

    document: dict[str, object]
    exit_code: Literal[0, 1, 2]

    def to_json_bytes(self) -> bytes:
        return canonical_json_bytes(self.document) + b"\n"


@dataclass(frozen=True, slots=True)
class SemanticPreparationBlocked:
    """A current provider-free blocker with its complete operator assessment."""

    preflight: SemanticPreflightResult


class _RepositoryChangedDuringAnalysis(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _PreparedCurrentAnalysis:
    """Provider-free current analysis state consumed without reconstruction."""

    anchor: Path
    operational_exclusions: tuple[str, ...]
    runtime: obligation_runtime.ObligationRuntime
    packet_plan: PacketPlan
    packet_report: PacketReport
    validated_packets: tuple[ValidatedSemanticPacket, ...]
    budget_projection: AnalyzerBudgetProjection

    @property
    def packet_bytes(self) -> bytes:
        return self.packet_plan.packet_jsonl


@dataclass(frozen=True, slots=True)
class _BlockedCurrentPreparation:
    """Provider-free preparation facts retained for a blocked assessment."""

    runtime: obligation_runtime.ObligationRuntime
    failure: SemanticApplicationFailure
    packet_plan: PacketPlan | None = None
    budget_projection: AnalyzerBudgetProjection | None = None
    exit_code: Literal[1, 2] = 2


def _monotonic() -> float:
    """Return the preparation clock through one deterministic test seam."""

    return time.monotonic()


def _deadline_failure(
    error: OperationDeadlineExceeded,
) -> SemanticApplicationFailure:
    return SemanticApplicationFailure(
        stage="deadline",
        code="DEADLINE_EXCEEDED",
        message="Analysis preparation exceeded its configured deadline.",
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


def _test_root_failure(
    repo_root: Path,
    profile: ProfileConfig,
) -> SemanticApplicationFailure | None:
    invalid_test_root = uncontained_test_root(
        repo_root,
        profile.code_roots,
        profile.test_roots,
    )
    if invalid_test_root is None:
        return None
    return SemanticApplicationFailure(
        stage="validation",
        message=(
            f"test root {invalid_test_root!r} must be equal to or nested under a"
            " final effective code root"
        ),
    )


def _validate_request(
    request: SemanticApplicationRequest,
) -> SemanticApplicationFailure | None:
    mode_failure = validate_analysis_mode(
        repo_root=request.repo_root,
        packets_path=request.packets_path,
        packet_report_path=request.packet_report_path,
        compare_repo_root=request.compare_repo_root,
        packets_output_path=request.packets_output_path,
        packet_report_output_path=request.packet_report_output_path,
    )
    if mode_failure is not None:
        return mode_failure
    if request.repo_root is not None:
        return _test_root_failure(request.repo_root.resolve(), request.profile)
    return None


def validate_analysis_mode(
    *,
    repo_root: Path | None,
    packets_path: Path | None,
    packet_report_path: Path | None,
    compare_repo_root: Path | None,
    packets_output_path: Path | None,
    packet_report_output_path: Path | None,
) -> SemanticApplicationFailure | None:
    """Validate the current/historical CLI mode before provider resolution."""

    if repo_root is not None:
        if packet_report_path is not None or compare_repo_root is not None:
            return SemanticApplicationFailure(
                stage="validation",
                message=(
                    "current analyze forbids --packet-report and --compare-repo-root"
                ),
            )
        if (packets_output_path is None) != (packet_report_output_path is None):
            return SemanticApplicationFailure(
                stage="validation",
                message=(
                    "--packets-output and --packet-report-output must be "
                    "supplied together"
                ),
            )
        repo_root.resolve()
        return None
    if packets_path is None:
        return SemanticApplicationFailure(
            stage="validation",
            message="historical analyze requires --packets",
        )
    if packet_report_path is None:
        return SemanticApplicationFailure(
            stage="validation",
            message="historical analyze requires --packet-report",
        )
    if packets_output_path is not None or packet_report_output_path is not None:
        return SemanticApplicationFailure(
            stage="validation",
            message="historical analyze forbids packet output flags",
        )
    packets_path.resolve()
    return None


def _current_paths(
    request: SemanticApplicationRequest,
    anchor: Path,
) -> tuple[str, ...] | SemanticApplicationFailure:
    output_paths = tuple(
        path
        for path in (
            request.packets_output_path,
            request.packet_report_output_path,
            request.result_output_path,
            request.report_output_path,
        )
        if path is not None
    )
    resolved_outputs = tuple(path.resolve(strict=False) for path in output_paths)
    if len(resolved_outputs) != len(set(resolved_outputs)):
        return SemanticApplicationFailure(
            stage="validation",
            message="every requested analyze output path must be distinct",
        )
    profile = request.profile
    semantic_roots = tuple(
        (anchor / root).resolve(strict=False)
        for root in (
            *profile.spec_roots,
            *profile.plan_roots,
            *profile.code_roots,
            *profile.test_roots,
        )
    )
    for output in resolved_outputs:
        if any(
            output == root or output.is_relative_to(root) for root in semantic_roots
        ):
            return SemanticApplicationFailure(
                stage="validation",
                message=f"analyze output overlaps a semantic input root: {output}",
            )
    mutable_paths = [
        *resolved_outputs,
        request.semantic_settings.cache_path.resolve(strict=False),
    ]
    if request.verification_settings is not None:
        mutable_paths.append(
            request.verification_settings.cache_path.resolve(strict=False)
        )
    config_paths = {
        Path(item.path).resolve(strict=False)
        for item in request.settings.config_layer_identities
    }
    for mutable in mutable_paths:
        if mutable in config_paths:
            return SemanticApplicationFailure(
                stage="validation",
                message=(
                    f"analyze mutable path overlaps selected configuration: {mutable}"
                ),
            )
        if any(
            mutable == root or mutable.is_relative_to(root) for root in semantic_roots
        ):
            return SemanticApplicationFailure(
                stage="validation",
                message=f"analyze mutable path overlaps a semantic input root: {mutable}",
            )
    operational_exclusions: list[str] = []
    for path in mutable_paths:
        if path.is_relative_to(anchor):
            relative = path.relative_to(anchor).as_posix()
            operational_exclusions.extend(
                (
                    relative,
                    f"{Path(relative).parent.as_posix()}/.{Path(relative).name}.*.tmp",
                )
            )
    return tuple(operational_exclusions)


def _prepare_current_packets(
    request: SemanticApplicationRequest,
    *,
    anchor: Path,
    operational_exclusions: tuple[str, ...],
    runtime: obligation_runtime.ObligationRuntime,
    progress: OperationProgress,
) -> _PreparedCurrentAnalysis | _BlockedCurrentPreparation:
    """Own packet planning, cold admission, and current packet materialization."""

    try:
        inference = request.semantic_settings.inference
        maximum_input_bytes = (
            inference.capability.maximum_input_bytes if inference is not None else None
        )
        packet_plan = analysis_packets.plan_source_aligned_packets(
            runtime,
            maximum_packets=request.semantic_settings.maximum_packets,
            maximum_prompt_bytes=request.semantic_settings.maximum_prompt_bytes,
            maximum_input_bytes=maximum_input_bytes,
            progress=progress,
        )
        if not packet_plan.complete:
            return _BlockedCurrentPreparation(
                runtime=runtime,
                packet_plan=packet_plan,
                budget_projection=project_cold_analyzer_budget(
                    None,
                    request.semantic_settings,
                ),
                failure=SemanticApplicationFailure(
                    stage="packet",
                    code="PACKET_BUDGET_EXHAUSTED",
                    message=(
                        f"packet plan crossed {packet_plan.crossed_ceiling} at "
                        f"{packet_plan.first_crossing_packet_id}"
                    ),
                    details=tuple(sorted(packet_plan.to_summary().items())),
                ),
            )
        budget_projection = project_cold_analyzer_budget(
            tuple(
                contribution.request_byte_count
                for contribution in packet_plan.contributions
            ),
            request.semantic_settings,
        )
        if budget_projection.call_cost_status == "exceeds":
            return _BlockedCurrentPreparation(
                runtime=runtime,
                packet_plan=packet_plan,
                budget_projection=budget_projection,
                failure=SemanticApplicationFailure(
                    stage="budget",
                    code="COLD_BUDGET_EXHAUSTED",
                    message="exact no-cache analyzer projection exceeds budget",
                    details=tuple(sorted(budget_projection.to_row().items())),
                ),
            )
        packet_report = build_source_packet_report(runtime, packet_plan=packet_plan)
        validated_packets = load_packets_bytes(
            packet_plan.packet_jsonl,
            source="current repository",
        )
        progress.advance(
            "complete",
            completed_work_units=packet_plan.measured_packet_count,
            total_work_units=packet_plan.measured_packet_count,
            current_identity=runtime.snapshot.snapshot_hash,
        )
    except OperationDeadlineExceeded as exc:
        return _BlockedCurrentPreparation(
            runtime=runtime,
            failure=_deadline_failure(exc),
        )
    except SourceAlignedPacketError as exc:
        failure = SemanticApplicationFailure(
            stage="alignment",
            code=exc.code,
            message=str(exc),
        )
        return _BlockedCurrentPreparation(runtime=runtime, failure=failure)
    except EvidenceDiscoveryError as exc:
        failure = SemanticApplicationFailure(
            stage="discovery",
            code=exc.code,
            message=str(exc),
            details=tuple(sorted(exc.details.items())),
        )
        return _BlockedCurrentPreparation(runtime=runtime, failure=failure)
    except PacketReportError as exc:
        failure = SemanticApplicationFailure(stage="report", message=str(exc))
        return _BlockedCurrentPreparation(runtime=runtime, failure=failure)
    return _PreparedCurrentAnalysis(
        anchor=anchor,
        operational_exclusions=operational_exclusions,
        runtime=runtime,
        packet_plan=packet_plan,
        packet_report=packet_report,
        validated_packets=validated_packets,
        budget_projection=budget_projection,
    )


def _prepare_current(
    request: SemanticApplicationRequest,
) -> _PreparedCurrentAnalysis | _BlockedCurrentPreparation | SemanticApplicationFailure:
    """Build the one provider-free current analysis preparation."""

    assert request.repo_root is not None
    anchor = request.repo_root.resolve()
    operational_exclusions = _current_paths(request, anchor)
    if isinstance(operational_exclusions, SemanticApplicationFailure):
        return operational_exclusions
    progress = OperationProgress.start(
        request.settings.obligations.maximum_call_seconds,
        clock=_monotonic,
        sink=request.progress_sink,
    )
    try:
        runtime = obligation_runtime.build_obligation_runtime(
            anchor,
            request.profile,
            request.settings,
            operational_exclusions=operational_exclusions,
            progress=progress,
        )
    except OperationDeadlineExceeded as exc:
        return _deadline_failure(exc)
    except SnapshotCaptureError as exc:
        return SemanticApplicationFailure(stage="snapshot", message=str(exc))
    cost_violation = validate_cost_contract(
        request.semantic_settings,
        lane="analyze",
    )
    if cost_violation is None and request.verification_settings is not None:
        cost_violation = validate_cost_contract(
            request.verification_settings,
            lane="verify",
        )
    if cost_violation is not None:
        return _BlockedCurrentPreparation(
            runtime=runtime,
            failure=SemanticApplicationFailure(
                stage="config",
                code="INVALID_COST_CONTRACT",
                message=cost_violation.message,
            ),
        )
    active = tuple(
        item
        for item in runtime.inventory.obligations
        if item.obligation_rung == "active"
    )
    if not active:
        return _BlockedCurrentPreparation(
            runtime=runtime,
            failure=SemanticApplicationFailure(
                stage="alignment",
                code="NO_ACTIVE_INTENT",
                message="current repository has no active obligation",
            ),
        )
    debt_ids = tuple(
        item.obligation_id
        for item in active
        if item.disposition == "evaluate" and item.gate_state != "executable"
    )
    if debt_ids:
        return _BlockedCurrentPreparation(
            runtime=runtime,
            failure=SemanticApplicationFailure(
                stage="alignment",
                code="ALIGNMENT_DEBT",
                message="current repository has active non-executable alignment debt",
                details=(("obligation_ids", debt_ids),),
            ),
        )
    fail_on = set(request.settings.diagnostics.fail_on)
    if any(issue.severity in fail_on for issue in runtime.pipeline.report.issues):
        return _BlockedCurrentPreparation(
            runtime=runtime,
            exit_code=1,
            failure=SemanticApplicationFailure(
                stage="deterministic",
                code="selected_target_finding",
                message="deterministic findings selected by fail_on block analysis",
            ),
        )
    return _prepare_current_packets(
        request,
        anchor=anchor,
        operational_exclusions=operational_exclusions,
        runtime=runtime,
        progress=progress,
    )


def _recapture_matches(prepared: _PreparedCurrentAnalysis) -> bool:
    recaptured = obligation_runtime.capture_obligation_snapshot(
        prepared.anchor,
        prepared.runtime.profile,
        prepared.runtime.settings,
        operational_exclusions=prepared.operational_exclusions,
    )
    return recaptured.snapshot_hash == prepared.runtime.snapshot.snapshot_hash


def _execute_current(
    request: SemanticApplicationRequest,
    prepared: _PreparedCurrentAnalysis,
) -> SemanticApplicationResult | SemanticApplicationFailure:
    """Execute exactly one accepted preparation after a currentness boundary."""

    try:
        if not _recapture_matches(prepared):
            return SemanticApplicationFailure(
                stage="currentness",
                message="repository source changed before current analysis execution",
            )
    except SnapshotCaptureError as exc:
        return SemanticApplicationFailure(stage="snapshot", message=str(exc))

    packet_bytes = prepared.packet_bytes
    packet_report = prepared.packet_report
    validated_packets = prepared.validated_packets
    run = semantic_analysis.run_semantic_analysis(
        semantic_analysis.SemanticAnalysisRequest(
            packets=validated_packets,
            packet_jsonl_sha256=hashlib.sha256(packet_bytes).hexdigest(),
            packet_report=packet_report,
            settings=request.semantic_settings,
            policy=request.policy,
            adapter_factory=request.adapter_factory,
            result_path=None,
            report_path=None,
            packet_plan=prepared.packet_plan,
            verification_settings=request.verification_settings,
            evaluation_settings=request.evaluation_settings,
            verification_adapter_factory=request.verification_adapter_factory,
            scope="current_repository",
            semantic_status=(
                "not_run_all_skipped" if not validated_packets else "evaluated"
            ),
            artifact_currentness="current",
            source_provenance="captured_current",
        )
    )
    if run.exit_code == 2:
        return SemanticApplicationResult(run)
    artifacts = tuple(
        (final_path, content)
        for final_path, content in (
            (request.packets_output_path, packet_bytes),
            (request.packet_report_output_path, packet_report.to_json_bytes()),
            (request.result_output_path, run.result_jsonl),
            (request.report_output_path, run.report_json),
        )
        if final_path is not None
    )

    def require_current_snapshot() -> None:
        if not _recapture_matches(prepared):
            raise _RepositoryChangedDuringAnalysis

    try:
        artifact_publication.publish_artifact_set(
            artifacts,
            before_publish=require_current_snapshot,
        )
    except SnapshotCaptureError as exc:
        return SemanticApplicationFailure(stage="snapshot", message=str(exc))
    except _RepositoryChangedDuringAnalysis:
        return SemanticApplicationFailure(
            stage="currentness",
            message="repository source changed during current analysis",
        )
    except artifact_publication.ArtifactPublicationError as exc:
        return SemanticApplicationFailure(
            stage="publication",
            message=str(exc),
            failed_path=exc.failed_path,
            published_paths=exc.published_paths,
        )
    return SemanticApplicationResult(run)


def _analyze_current(
    request: SemanticApplicationRequest,
) -> (
    SemanticApplicationResult
    | SemanticPreparationBlocked
    | SemanticReadinessBlocked
    | SemanticApplicationFailure
):
    prepared = _prepare_current(request)
    if isinstance(prepared, _BlockedCurrentPreparation):
        if prepared.exit_code == 1:
            return SemanticReadinessBlocked(prepared.runtime.pipeline.report)
        return SemanticPreparationBlocked(
            SemanticPreflightResult(
                _preflight_document(
                    request,
                    prepared=prepared,
                    failure=prepared.failure,
                ),
                prepared.exit_code,
            )
        )
    if not isinstance(prepared, _PreparedCurrentAnalysis):
        return prepared
    return _execute_current(request, prepared)


def _historical_paths(
    request: SemanticApplicationRequest,
) -> SemanticApplicationFailure | None:
    assert request.packets_path is not None
    assert request.packet_report_path is not None
    inputs = {
        request.packets_path.resolve(strict=False),
        request.packet_report_path.resolve(strict=False),
    }
    outputs = tuple(
        path.resolve(strict=False)
        for path in (request.result_output_path, request.report_output_path)
        if path is not None
    )
    if len(outputs) != len(set(outputs)) or any(path in inputs for path in outputs):
        return SemanticApplicationFailure(
            stage="validation",
            message="historical analyze input and output paths must be distinct",
        )
    return None


def _analyze_historical(
    request: SemanticApplicationRequest,
) -> SemanticApplicationResult | SemanticApplicationFailure:
    assert request.packets_path is not None
    assert request.packet_report_path is not None
    path_failure = _historical_paths(request)
    if path_failure is not None:
        return path_failure
    try:
        packet_bytes = request.packets_path.read_bytes()
        validated_packets = load_packets_bytes(
            packet_bytes,
            source=request.packets_path,
        )
        packet_report = load_packet_report(
            request.packet_report_path,
            maximum_bytes=request.settings.obligations.maximum_packet_report_bytes,
        )
        report_schema = packet_report.to_dict()["schema_version"]
        packet_report = validate_packet_report(
            packet_report,
            packet_jsonl=packet_bytes,
            packets=validated_packets if report_schema == 2 else None,
        )
    except (OSError, ValueError) as exc:
        return SemanticApplicationFailure(stage="input", message=str(exc))
    artifact_currentness: Literal["current", "stale", "unverifiable"] = "unverifiable"
    source_provenance: Literal[
        "compared_match",
        "compared_mismatch",
        "claimed_unverified",
    ] = "claimed_unverified"
    if request.compare_repo_root is not None:
        compare_root = request.compare_repo_root.resolve()
        containment_failure = _test_root_failure(compare_root, request.profile)
        if containment_failure is not None:
            return containment_failure
        try:
            comparison = obligation_runtime.capture_obligation_snapshot(
                compare_root,
                request.profile,
                request.settings,
            )
        except SnapshotCaptureError as exc:
            return SemanticApplicationFailure(stage="snapshot", message=str(exc))
        claimed_snapshot = packet_report.to_dict()["source_snapshot"]["snapshot_hash"]
        if comparison.snapshot_hash == claimed_snapshot:
            artifact_currentness = "current"
            source_provenance = "compared_match"
        else:
            artifact_currentness = "stale"
            source_provenance = "compared_mismatch"
    run = semantic_analysis.run_semantic_analysis(
        semantic_analysis.SemanticAnalysisRequest(
            packets=validated_packets,
            packet_jsonl_sha256=hashlib.sha256(packet_bytes).hexdigest(),
            packet_report=packet_report,
            settings=request.semantic_settings,
            policy=request.policy,
            adapter_factory=request.adapter_factory,
            result_path=request.result_output_path,
            report_path=request.report_output_path,
            verification_settings=request.verification_settings,
            evaluation_settings=request.evaluation_settings,
            verification_adapter_factory=request.verification_adapter_factory,
            scope="historical_snapshot",
            semantic_status="historical_replay",
            artifact_currentness=artifact_currentness,
            source_provenance=source_provenance,
        )
    )
    return SemanticApplicationResult(run)


def _readiness_projection(
    runtime: obligation_runtime.ObligationRuntime,
    *,
    repo_root: Path,
) -> dict[str, object]:
    active = tuple(
        item
        for item in runtime.inventory.obligations
        if item.obligation_rung == "active"
    )
    executable = tuple(
        item
        for item in active
        if item.disposition == "evaluate" and item.gate_state == "executable"
    )
    blocked = tuple(
        item
        for item in active
        if item.disposition == "evaluate" and item.gate_state != "executable"
    )
    counts: Counter[str] = Counter()
    examples: defaultdict[str, list[str]] = defaultdict(list)
    for item in blocked:
        for reason in item.blocking_reasons:
            if reason.code in {"OUT_OF_GATE_SCOPE", "SKIPPED"}:
                continue
            counts[reason.code] += 1
            if len(examples[reason.code]) < 3:
                examples[reason.code].append(item.obligation_id)
    return {
        "total": len(active),
        "executable": len(executable),
        "blocked": len(blocked),
        "reason_groups": [
            {
                "code": code,
                "count": counts[code],
                "example_obligation_ids": examples[code],
            }
            for code in sorted(counts)
        ],
        "next_command": (
            "backstitch obligation list "
            f"--repo-root {repo_root.as_posix()} --active-only "
            "--gate-state not_executable"
        ),
    }


def _inference_projection(
    request: SemanticApplicationRequest,
) -> dict[str, object] | None:
    analyzer = request.semantic_settings.inference
    if analyzer is None:
        return None

    def project(inference: ResolvedInference) -> dict[str, object]:
        resolved = inference
        return {
            "stable_model_id": resolved.provider_identity.model_id,
            "adapter_model_id": resolved.adapter_model_id,
            "capability_revision": resolved.capability.capability_revision,
            "effective_request": resolved.effective_request.to_dict(),
            "request_identity": resolved.request_identity.to_dict(),
        }

    verifier = request.verification_settings
    return {
        "analyzer": project(analyzer),
        "verifier": (
            project(verifier.inference)
            if verifier is not None and verifier.inference is not None
            else None
        ),
    }


def _preflight_problem(
    failure: SemanticApplicationFailure,
    *,
    repo_root: Path,
) -> dict[str, object]:
    action = (
        "Run "
        f"`backstitch obligation list --repo-root {repo_root.as_posix()} "
        "--active-only --gate-state not_executable` and repair each active "
        "obligation."
        if failure.code in {"ALIGNMENT_DEBT", "NO_ACTIVE_INTENT"}
        else (
            "Run "
            f"`backstitch check --repo-root {repo_root.as_posix()}` and address "
            "findings selected by diagnostics.fail_on."
            if failure.stage == "deterministic"
            else "Correct the reported preparation problem, then rerun preflight."
        )
    )
    return {
        "stage": failure.stage,
        "code": failure.code or f"{failure.stage}_failed",
        "details": dict(failure.details),
        "action": action,
    }


def _budget_projection(
    request: SemanticApplicationRequest,
    prepared: _PreparedCurrentAnalysis | _BlockedCurrentPreparation | None,
) -> dict[str, object]:
    settings = request.semantic_settings
    inference = settings.inference
    analyzer_projection = (
        prepared.budget_projection
        if prepared is not None and prepared.budget_projection is not None
        else project_cold_analyzer_budget(None, settings)
    )
    verification = request.verification_settings
    verifier_enabled = verification is not None
    call_cost_status = analyzer_projection.call_cost_status
    if verifier_enabled and call_cost_status not in {"exceeds", "unavailable"}:
        call_cost_status = "unknown"
    return {
        "projection": "conservative_cold",
        "limits": {
            "maximum_packets": settings.maximum_packets or None,
            "maximum_prompt_bytes": settings.maximum_prompt_bytes or None,
            "maximum_input_bytes": (
                inference.capability.maximum_input_bytes
                if inference is not None
                else None
            ),
            "maximum_provider_calls": settings.maximum_provider_calls,
            "maximum_estimated_cost_microusd": (
                settings.maximum_estimated_cost_microusd or None
            ),
            "maximum_runtime_seconds": settings.maximum_runtime_seconds,
        },
        "analyzer": analyzer_projection.to_row(),
        "verifier": {
            "status": (
                "deferred_until_analyzer_results" if verifier_enabled else "disabled"
            ),
            "maximum_input_bytes": (
                verification.inference.capability.maximum_input_bytes
                if verification is not None and verification.inference is not None
                else None
            ),
            "maximum_prompt_bytes": (
                verification.maximum_prompt_bytes if verification is not None else None
            ),
            "maximum_provider_calls": (
                verification.maximum_provider_calls
                if verification is not None
                else None
            ),
            "maximum_estimated_cost_microusd": (
                (verification.maximum_estimated_cost_microusd or None)
                if verification is not None
                else None
            ),
            "maximum_runtime_seconds": (
                verification.maximum_runtime_seconds
                if verification is not None
                else None
            ),
        },
        "call_cost_status": call_cost_status,
    }


def _preflight_document(
    request: SemanticApplicationRequest,
    *,
    prepared: _PreparedCurrentAnalysis | _BlockedCurrentPreparation | None,
    failure: SemanticApplicationFailure | None,
) -> dict[str, object]:
    assert request.repo_root is not None
    runtime = prepared.runtime if prepared is not None else None
    packet_plan = (
        prepared.packet_plan
        if isinstance(prepared, (_PreparedCurrentAnalysis, _BlockedCurrentPreparation))
        else None
    )
    selected_path = (
        str(request.settings.config_path)
        if request.settings.config_path is not None
        else None
    )
    snapshot = (
        {
            "snapshot_hash": "sha256:" + runtime.snapshot.snapshot_hash,
            "file_count": runtime.snapshot.file_count,
            "byte_count": runtime.snapshot.byte_count,
        }
        if runtime is not None
        else None
    )
    readiness = (
        _readiness_projection(runtime, repo_root=request.repo_root.resolve())
        if runtime is not None
        else None
    )
    ready = isinstance(prepared, _PreparedCurrentAnalysis) and failure is None
    problems = (
        [_preflight_problem(failure, repo_root=request.repo_root.resolve())]
        if failure is not None
        else []
    )
    return {
        "schema_version": 2,
        "operation": "analysis.preflight",
        "ready": ready,
        "selected_command": "analyze",
        "config": {
            "selected_path": selected_path,
            "settings_sha256": (
                "sha256:"
                + hashlib.sha256(
                    settings_to_json(request.settings).encode("utf-8")
                ).hexdigest()
            ),
        },
        "snapshot": snapshot,
        "readiness": readiness,
        "packet_plan": packet_plan.to_summary() if packet_plan is not None else None,
        "inference": _inference_projection(request),
        "budgets": _budget_projection(request, prepared),
        "outputs": {"current_artifacts_would_publish": ready},
        "problems": problems,
    }


def preflight_semantics(
    request: SemanticApplicationRequest,
) -> SemanticPreflightResult | SemanticApplicationFailure:
    """Assess the exact provider-free preparation used by current analysis."""

    validation_failure = _validate_request(request)
    if validation_failure is not None:
        return validation_failure
    if request.repo_root is None:
        return SemanticApplicationFailure(
            stage="validation",
            message="analyze --preflight requires current --repo-root input",
        )
    if any(
        path is not None
        for path in (
            request.packets_output_path,
            request.packet_report_output_path,
            request.result_output_path,
            request.report_output_path,
        )
    ):
        return SemanticApplicationFailure(
            stage="validation",
            message="analyze --preflight forbids every semantic output path",
        )
    prepared = _prepare_current(request)
    if isinstance(prepared, SemanticApplicationFailure):
        return SemanticPreflightResult(
            _preflight_document(request, prepared=None, failure=prepared),
            2,
        )
    if isinstance(prepared, _BlockedCurrentPreparation):
        return SemanticPreflightResult(
            _preflight_document(
                request,
                prepared=prepared,
                failure=prepared.failure,
            ),
            prepared.exit_code,
        )
    return SemanticPreflightResult(
        _preflight_document(request, prepared=prepared, failure=None),
        0,
    )


def analyze_semantics(
    request: SemanticApplicationRequest,
) -> (
    SemanticApplicationResult
    | SemanticPreparationBlocked
    | SemanticReadinessBlocked
    | SemanticApplicationFailure
):
    """Run one semantic application workflow without CLI presentation."""

    validation_failure = _validate_request(request)
    if validation_failure is not None:
        return validation_failure
    if request.repo_root is not None:
        return _analyze_current(request)
    return _analyze_historical(request)
