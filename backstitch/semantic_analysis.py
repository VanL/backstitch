"""Unified policy-driven semantic analysis gate.

This is the single production owner for cache resolution, completeness and
budget decisions, semantic policy projection, reports, publication, and the
0/1/2 exit truth table.

Spec: docs/specs/02-backstitch-core.md [SC-7]
Spec: docs/specs/06-semantic-gates.md [SEM-1], [SEM-2], [SEM-7]
Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-5.1], [EVC-8.7],
[EVC-9], [EVC-11]
"""

from __future__ import annotations

import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

from backstitch.artifact_contracts import ValidatedSemanticPacket
from backstitch.canonical import canonical_json_bytes
from backstitch.grammar import is_sha256_hex
from backstitch.semantic_cache import (
    AdapterFactory,
    EvidenceStablePreparation,
    ProviderAdapter,
    ProviderCallBudget,
    SemanticCacheFailure,
    SemanticCacheRun,
    SemanticProblem,
    SemanticResultEnvelope,
    SemanticSelectionEvent,
    VerificationCacheRun,
    VerificationWork,
    analyze_with_cache,
    inspect_semantic_cache,
    inspect_verification_cache,
    prepare_evidence_stable_cache,
    resolve_prepared_evidence_stable_result,
    verify_with_cache,
)
from backstitch.semantic_identity import (
    CompositionIdentity,
    InferenceIdentity,
    ProviderIdentity,
    RequestIdentity,
    build_composition_identity,
    build_inference_identity,
    resolve_provider_identity,
)
from backstitch.semantic_packets import model_request_bytes
from backstitch.semantic_policy import (
    SemanticDiagnostic,
    SemanticPolicy,
    SemanticProjectionRun,
    finding_hash,
    project_semantic_results,
)
from backstitch.semantic_reports import (
    PacketReport,
    PacketReportError,
    atomic_replace_bytes,
    validate_analysis_report,
    validate_packet_report,
)
from backstitch.semantic_verification import (
    VerificationAggregate,
    aggregate_verification_results,
    build_verification_request,
    build_verify_identity,
    derive_verification_claim,
    verifier_request_bytes,
)
from backstitch.settings import (
    AnalyzeSettings,
    DisabledVerifySettings,
    SemanticDisposition,
    VerifyEvalSettings,
    VerifySettings,
)

ProblemStage = Literal[
    "config",
    "input",
    "cache",
    "lock",
    "provider",
    "normalization",
    "completeness",
    "budget",
    "output",
    "internal",
    "qualification",
]
ProblemCode = Literal[
    "invalid_config",
    "invalid_input",
    "corrupt_cache",
    "stale_cache",
    "lock_timeout",
    "provider_failure",
    "malformed_result",
    "incomplete_result",
    "budget_exceeded",
    "output_failure",
    "internal_failure",
    "required_qualification_unavailable",
]

_FAILED_STAGES = frozenset(
    {
        "config",
        "input",
        "cache",
        "lock",
        "provider",
        "normalization",
        "output",
        "internal",
        "qualification",
    }
)
_COST_FRAMING_TOKEN_BOUNDS: dict[tuple[str, str], int] = {
    # The built-in llm/OpenAI adapter is the first reviewed positive-cost
    # contract. Other backend/plugin pairs remain disabled until reviewed.
    ("llm", "openai"): 256,
}


@dataclass(frozen=True, slots=True)
class SemanticAnalysisProblem:
    packet_id: str | None
    stage: ProblemStage
    code: ProblemCode
    message: str
    obligation_id: str | None = None
    details: dict[str, object] = field(default_factory=dict)

    def to_row(self) -> dict[str, object]:
        return {
            "packet_id": self.packet_id,
            "obligation_id": self.obligation_id,
            "stage": self.stage,
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


@dataclass(frozen=True, slots=True)
class IndependentQualificationAuthority:
    """One authoritatively validated qualification bound to one analyzer."""

    selectors: tuple[str, ...]
    analyzer_provider: ProviderIdentity
    problem_details: dict[str, object]


@dataclass(frozen=True, slots=True)
class ResolvedSemanticSettings:
    """All non-policy inputs needed after config and provider resolution."""

    provider_identity: ProviderIdentity
    request_identity: RequestIdentity
    concurrency: int
    cache_path: Path
    cache_mode: str
    search_epoch: str
    require_complete: bool
    required_kinds: tuple[str, ...]
    minimum_packets: int
    maximum_packets: int
    maximum_prompt_bytes: int
    finding_handling: str
    maximum_provider_calls: int
    lock_wait_timeout_seconds: int
    maximum_runtime_seconds: int
    maximum_estimated_cost_microusd: int
    input_cost_microusd_per_million_tokens: int
    output_cost_microusd_per_million_tokens: int
    input_token_overhead: int
    cost_rate_source: str
    dispositions: tuple[SemanticDisposition, ...]
    result_reuse: str = "evidence-stable"


@dataclass(frozen=True, slots=True)
class ResolvedVerificationSettings:
    """Complete verifier inputs after provider/request resolution."""

    provider_identity: ProviderIdentity
    request_identity: RequestIdentity
    composition_identity: CompositionIdentity
    concurrency: int
    cache_path: Path
    cache_mode: str
    search_epochs: tuple[str, ...]
    required_verdicts: int
    minimum_support_score: float
    indeterminate: str
    maximum_provider_calls: int
    maximum_prompt_bytes: int
    lock_wait_timeout_seconds: int
    maximum_runtime_seconds: int
    maximum_estimated_cost_microusd: int
    input_cost_microusd_per_million_tokens: int
    output_cost_microusd_per_million_tokens: int
    input_token_overhead: int
    cost_rate_source: str
    effective_search_epochs: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class SemanticAnalysisRequest:
    packets: tuple[ValidatedSemanticPacket, ...]
    packet_jsonl_sha256: str
    packet_report: PacketReport | None
    settings: ResolvedSemanticSettings
    policy: SemanticPolicy
    adapter_factory: AdapterFactory | None
    result_path: Path | None
    report_path: Path | None
    verification_settings: ResolvedVerificationSettings | None = None
    evaluation_settings: VerifyEvalSettings | None = None
    verification_adapter_factory: AdapterFactory | None = None
    scope: Literal["current_repository", "historical_snapshot"] = "historical_snapshot"
    semantic_status: Literal[
        "evaluated", "not_run_all_skipped", "historical_replay"
    ] = "historical_replay"
    artifact_currentness: Literal["current", "stale", "unverifiable"] = "unverifiable"
    source_provenance: Literal[
        "captured_current",
        "compared_match",
        "compared_mismatch",
        "claimed_unverified",
    ] = "claimed_unverified"


@dataclass(frozen=True, slots=True)
class SemanticAnalysisRun:
    results: tuple[dict[str, Any], ...]
    diagnostics: tuple[SemanticDiagnostic, ...]
    problems: tuple[SemanticAnalysisProblem, ...]
    result_jsonl: bytes
    report: dict[str, Any]
    report_json: bytes
    stderr_lines: tuple[str, ...]
    exit_code: int
    selected_result_objects: tuple[dict[str, Any], ...] = ()
    selection_events: tuple[dict[str, object], ...] = ()


def resolve_semantic_settings(settings: AnalyzeSettings) -> ResolvedSemanticSettings:
    """Resolve the offline provider and request identity before cache lookup."""

    if settings.cache_mode in {"read-write", "require"}:
        identities = {
            "backend_id": settings.backend_id,
            "plugin_id": settings.plugin_id,
            "plugin_distribution_name": settings.plugin_distribution_name,
            "model": settings.model,
            "model_revision": settings.model_revision,
        }
        blank = [name for name, value in identities.items() if not value.strip()]
        if blank:
            raise ValueError(
                "analyze cached modes require resolved nonblank provider identity: "
                + ", ".join(blank)
            )
    resolved_json_mode = "off" if settings.json_mode == "prefer" else settings.json_mode
    request_identity = RequestIdentity(
        json_mode=resolved_json_mode,  # type: ignore[arg-type]
        temperature=settings.temperature,
        seed=settings.seed,
        max_tokens=settings.max_tokens,
    )
    provider_identity = resolve_provider_identity(
        backend_id=settings.backend_id,
        plugin_id=settings.plugin_id,
        model_id=settings.model,
        model_revision=settings.model_revision,
        plugin_distribution_name=settings.plugin_distribution_name,
    )
    return ResolvedSemanticSettings(
        provider_identity=provider_identity,
        request_identity=request_identity,
        concurrency=settings.concurrency,
        cache_path=Path(settings.cache_path),
        cache_mode=settings.cache_mode,
        result_reuse=settings.result_reuse,
        search_epoch=settings.search_epoch,
        require_complete=settings.require_complete,
        required_kinds=settings.required_kinds,
        minimum_packets=settings.minimum_packets,
        maximum_packets=settings.maximum_packets,
        maximum_prompt_bytes=settings.maximum_prompt_bytes,
        finding_handling=settings.finding_handling,
        maximum_provider_calls=settings.maximum_provider_calls,
        lock_wait_timeout_seconds=settings.lock_wait_timeout_seconds,
        maximum_runtime_seconds=settings.maximum_runtime_seconds,
        maximum_estimated_cost_microusd=(settings.maximum_estimated_cost_microusd),
        input_cost_microusd_per_million_tokens=(
            settings.input_cost_microusd_per_million_tokens
        ),
        output_cost_microusd_per_million_tokens=(
            settings.output_cost_microusd_per_million_tokens
        ),
        input_token_overhead=settings.input_token_overhead,
        cost_rate_source=settings.cost_rate_source,
        dispositions=settings.dispositions,
    )


def resolve_verification_settings(
    settings: DisabledVerifySettings | VerifySettings,
    analyze: ResolvedSemanticSettings,
) -> ResolvedVerificationSettings | None:
    """Resolve a complete verifier descriptor without constructing an adapter."""

    if not settings.enabled:
        return None
    resolved_json_mode = "off" if settings.json_mode == "prefer" else settings.json_mode
    request_identity = RequestIdentity(
        json_mode=resolved_json_mode,  # type: ignore[arg-type]
        temperature=settings.temperature,
        seed=settings.seed,
        max_tokens=settings.max_tokens,
    )
    if settings.provider_source == "analyze":
        provider_identity = analyze.provider_identity
        input_cost = analyze.input_cost_microusd_per_million_tokens
        output_cost = analyze.output_cost_microusd_per_million_tokens
        input_overhead = analyze.input_token_overhead
        cost_source = analyze.cost_rate_source
    else:
        provider = settings.provider
        if provider is None:
            raise ValueError("verify override provider is incomplete")
        provider_identity = resolve_provider_identity(
            backend_id=provider.backend_id,
            plugin_id=provider.plugin_id,
            model_id=provider.model,
            model_revision=provider.model_revision,
            plugin_distribution_name=provider.plugin_distribution_name,
        )
        input_cost = provider.input_cost_microusd_per_million_tokens
        output_cost = provider.output_cost_microusd_per_million_tokens
        input_overhead = provider.input_token_overhead
        cost_source = provider.cost_rate_source
    composition = build_composition_identity(
        analyze.provider_identity,
        analyze.request_identity,
        analysis_search_epoch=analyze.search_epoch,
        verify_provider=provider_identity,
        verify_request=request_identity,
        verify_search_epochs=settings.search_epochs,
        required_verdicts=settings.required_verdicts,
        minimum_support_score=settings.minimum_support_score,
        indeterminate=settings.indeterminate,
    )
    return ResolvedVerificationSettings(
        provider_identity=provider_identity,
        request_identity=request_identity,
        composition_identity=composition,
        concurrency=settings.concurrency,
        cache_path=Path(settings.cache_path),
        cache_mode=settings.cache_mode,
        search_epochs=settings.search_epochs,
        required_verdicts=settings.required_verdicts,
        minimum_support_score=settings.minimum_support_score,
        indeterminate=settings.indeterminate,
        maximum_provider_calls=settings.maximum_provider_calls,
        maximum_prompt_bytes=settings.maximum_prompt_bytes,
        lock_wait_timeout_seconds=settings.lock_wait_timeout_seconds,
        maximum_runtime_seconds=settings.maximum_runtime_seconds,
        maximum_estimated_cost_microusd=settings.maximum_estimated_cost_microusd,
        input_cost_microusd_per_million_tokens=input_cost,
        output_cost_microusd_per_million_tokens=output_cost,
        input_token_overhead=input_overhead,
        cost_rate_source=cost_source,
    )


def packet_report_required(settings: ResolvedSemanticSettings) -> bool:
    """Every semantic execution is bound to one complete packet report."""

    return True


def _problem(
    stage: ProblemStage,
    code: ProblemCode,
    message: str,
    *,
    packet_id: str | None = None,
    obligation_id: str | None = None,
    details: dict[str, object] | None = None,
) -> SemanticAnalysisProblem:
    return SemanticAnalysisProblem(
        packet_id,
        stage,
        code,
        message,
        obligation_id,
        details or {},
    )


def _cache_problem(problem: SemanticProblem) -> SemanticAnalysisProblem:
    return SemanticAnalysisProblem(
        problem.packet_id,
        problem.stage,
        problem.code,
        problem.message,
        details=problem.details,
    )


def _path_alias_problem(request: SemanticAnalysisRequest) -> str | None:
    if request.result_path is None or request.report_path is None:
        return None
    try:
        result = request.result_path.resolve(strict=False)
        report = request.report_path.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        return f"cannot resolve semantic output/report paths: {exc}"
    if result == report:
        return "semantic result and report paths must be distinct"
    return None


def _packet_report_preflight(
    request: SemanticAnalysisRequest,
    rows: tuple[dict[str, Any], ...],
    identities: tuple[InferenceIdentity, ...],
) -> tuple[list[SemanticAnalysisProblem], PacketReport | None]:
    problems: list[SemanticAnalysisProblem] = []
    if packet_report_required(request.settings) and request.packet_report is None:
        problems.append(
            _problem(
                "input",
                "invalid_input",
                "packet report is required by the resolved analysis settings",
            )
        )
        return problems, None
    if request.packet_report is None:
        return problems, None
    try:
        report = validate_packet_report(
            request.packet_report,
            packets=request.packets,
            identities=identities,
        )
    except PacketReportError as exc:
        problems.append(_problem("input", "invalid_input", str(exc)))
        return problems, None
    if report.packet_jsonl_sha256 != request.packet_jsonl_sha256:
        problems.append(
            _problem("input", "invalid_input", "packet report digest mismatch")
        )
        return problems, None

    value = report.to_dict()
    report_schema = value["schema_version"]
    if report_schema not in {2, 3} or any(
        not packet.semantic_eligible for packet in request.packets
    ):
        problems.append(
            _problem(
                "input",
                "invalid_input",
                "semantic analysis requires packet schema 3 or 4 and "
                "packet-report schema 2 or 3",
            )
        )
        return problems, None
    if value["selection_status"] == "not_run_all_skipped":
        return problems, report
    emitted = {
        "section": sum(row["kind"] == "section" for row in rows),
        "invariant": sum(row["kind"] == "invariant" for row in rows),
        "suppression": sum(row["kind"] == "suppression" for row in rows),
    }
    prompt_byte_count = (
        sum(
            len(model_request_bytes(row, instruction_bytes=identity.prompt_bytes))
            for row, identity in zip(rows, identities, strict=True)
        )
        if len(identities) == len(rows)
        else 0
    )
    for kind in request.settings.required_kinds:
        if kind == "suppression":
            # Current packet-report validation has already proved that every
            # eligible suppression audit row has one emitted packet. Zero
            # eligible suppressions is therefore the only valid empty case.
            missing = False
        else:
            missing = emitted[kind] == 0
        if missing:
            problems.append(
                _problem(
                    "completeness",
                    "incomplete_result",
                    f"required packet kind is missing: {kind}",
                )
            )
    count = len(rows)
    if count < request.settings.minimum_packets:
        problems.append(
            _problem(
                "completeness",
                "incomplete_result",
                "packet count is below analyze.minimum_packets",
            )
        )
    if request.settings.maximum_packets and count > request.settings.maximum_packets:
        problems.append(
            _problem(
                "budget",
                "budget_exceeded",
                "packet count exceeds analyze.maximum_packets",
            )
        )
    if (
        request.settings.maximum_prompt_bytes
        and prompt_byte_count > request.settings.maximum_prompt_bytes
    ):
        problems.append(
            _problem(
                "budget",
                "budget_exceeded",
                "prompt bytes exceed analyze.maximum_prompt_bytes",
            )
        )
    return problems, report


def _validate_cost_contract(
    settings: ResolvedSemanticSettings,
) -> SemanticAnalysisProblem | None:
    if settings.maximum_estimated_cost_microusd == 0:
        return None
    pair = (
        settings.provider_identity.backend_id,
        settings.provider_identity.plugin_id,
    )
    minimum_overhead = _COST_FRAMING_TOKEN_BOUNDS.get(pair)
    if minimum_overhead is None:
        return _problem(
            "config",
            "invalid_config",
            "positive cost ceiling has no reviewed backend/plugin cost contract",
        )
    if settings.input_token_overhead < minimum_overhead:
        return _problem(
            "config",
            "invalid_config",
            "input token overhead is below the adapter's code-owned framing bound",
        )
    if not settings.cost_rate_source.strip():
        return _problem(
            "config",
            "invalid_config",
            "positive cost ceiling requires a nonblank cost rate source",
        )
    if (
        pair == ("llm", "openai")
        and settings.input_cost_microusd_per_million_tokens == 0
        and settings.output_cost_microusd_per_million_tokens == 0
    ):
        return _problem(
            "config",
            "invalid_config",
            "positive cost ceiling cannot use zero rates for both cloud directions",
        )
    return None


def _validate_verification_cost_contract(
    settings: ResolvedVerificationSettings | None,
) -> SemanticAnalysisProblem | None:
    if settings is None or settings.maximum_estimated_cost_microusd == 0:
        return None
    pair = (settings.provider_identity.backend_id, settings.provider_identity.plugin_id)
    minimum_overhead = _COST_FRAMING_TOKEN_BOUNDS.get(pair)
    if minimum_overhead is None:
        return _problem(
            "config",
            "invalid_config",
            "positive verifier cost ceiling has no reviewed backend/plugin contract",
        )
    if settings.input_token_overhead < minimum_overhead:
        return _problem(
            "config",
            "invalid_config",
            "verifier input token overhead is below the adapter framing bound",
        )
    if not settings.cost_rate_source.strip():
        return _problem(
            "config",
            "invalid_config",
            "positive verifier cost ceiling requires a nonblank rate source",
        )
    if (
        pair == ("llm", "openai")
        and settings.input_cost_microusd_per_million_tokens == 0
        and settings.output_cost_microusd_per_million_tokens == 0
    ):
        return _problem(
            "config",
            "invalid_config",
            "positive verifier cost ceiling cannot use two zero cloud rates",
        )
    return None


def _estimate_cost(
    rows: tuple[dict[str, Any], ...],
    identities: tuple[InferenceIdentity, ...],
    miss_packet_ids: tuple[str, ...],
    settings: ResolvedSemanticSettings,
) -> int:
    misses = set(miss_packet_ids)
    total = 0
    for row, identity in zip(rows, identities, strict=True):
        if row["packet_id"] not in misses:
            continue
        input_tokens = (
            len(model_request_bytes(row, instruction_bytes=identity.prompt_bytes))
            + settings.input_token_overhead
        )
        total += _ceil_million(
            input_tokens * settings.input_cost_microusd_per_million_tokens
        )
        total += _ceil_million(
            settings.request_identity.max_tokens
            * settings.output_cost_microusd_per_million_tokens
        )
    return total


def _ceil_million(value: int) -> int:
    return (value + 999_999) // 1_000_000


def _empty_projection(
    request: SemanticAnalysisRequest,
) -> SemanticProjectionRun:
    return project_semantic_results(
        (),
        request.policy,
        request.settings.dispositions,
        finding_handling=request.settings.finding_handling,
    )


def _execute_cache(
    request: SemanticAnalysisRequest,
    identities: tuple[InferenceIdentity, ...],
    *,
    runtime_deadline: float,
    provider_call_packet_ids: frozenset[str] | None,
) -> tuple[
    tuple[dict[str, Any], ...],
    bytes,
    tuple[SemanticProblem, ...],
    int,
    int,
    int,
    dict[str, dict[str, int]],
    tuple[SemanticResultEnvelope, ...],
    tuple[SemanticSelectionEvent, ...],
]:
    provider_call_budget = ProviderCallBudget(request.settings.maximum_provider_calls)
    adapter_factory = request.adapter_factory
    if request.settings.concurrency > 1 and adapter_factory is not None:
        construction_lock = threading.Lock()
        shared_adapter: ProviderAdapter | None = None
        construction_error: Exception | None = None

        def build_shared_adapter() -> ProviderAdapter:
            nonlocal shared_adapter, construction_error
            with construction_lock:
                if construction_error is not None:
                    raise RuntimeError("semantic adapter construction failed") from (
                        construction_error
                    )
                if shared_adapter is None:
                    try:
                        shared_adapter = adapter_factory()
                    except Exception as exc:
                        construction_error = exc
                        raise
                return shared_adapter

        effective_adapter_factory: AdapterFactory | None = build_shared_adapter
    else:
        effective_adapter_factory = adapter_factory

    def analyze_packets(
        packets: tuple[ValidatedSemanticPacket, ...],
        packet_identities: tuple[InferenceIdentity, ...],
    ) -> SemanticCacheRun:
        return analyze_with_cache(
            packets=packets,
            cache_path=request.settings.cache_path,
            cache_mode=request.settings.cache_mode,
            result_reuse="exact-inference",
            provider_identity=request.settings.provider_identity,
            request_identity=request.settings.request_identity,
            adapter_factory=effective_adapter_factory,
            search_epoch=request.settings.search_epoch,
            lock_wait_timeout_seconds=request.settings.lock_wait_timeout_seconds,
            runtime_deadline=runtime_deadline,
            provider_call_budget=provider_call_budget,
            provider_call_packet_ids=provider_call_packet_ids,
            identities=packet_identities,
        )

    if request.settings.concurrency <= 1 or len(request.packets) <= 1:
        run = analyze_packets(request.packets, identities)
        return (
            run.results,
            run.result_jsonl,
            run.problems,
            run.cache_hits,
            run.cache_misses,
            run.provider_calls,
            run.kind_counts,
            run.result_envelopes,
            run.selection_events,
        )

    def analyze_one(
        pair: tuple[ValidatedSemanticPacket, InferenceIdentity],
    ) -> SemanticCacheRun:
        packet, identity = pair
        return analyze_packets((packet,), (identity,))

    with ThreadPoolExecutor(max_workers=request.settings.concurrency) as executor:
        runs = tuple(
            executor.map(
                analyze_one,
                zip(request.packets, identities, strict=True),
            )
        )
    kind_counts = _empty_analyzer_kind_counts()
    for run in runs:
        for event in kind_counts:
            for packet_kind in kind_counts[event]:
                kind_counts[event][packet_kind] += run.kind_counts[event][packet_kind]
    return (
        tuple(result for run in runs for result in run.results),
        b"".join(run.result_jsonl for run in runs),
        tuple(problem for run in runs for problem in run.problems),
        sum(run.cache_hits for run in runs),
        sum(run.cache_misses for run in runs),
        sum(run.provider_calls for run in runs),
        kind_counts,
        tuple(envelope for run in runs for envelope in run.result_envelopes),
        tuple(event for run in runs for event in run.selection_events),
    )


def _execute_evidence_stable_preparation(
    request: SemanticAnalysisRequest,
    preparation: EvidenceStablePreparation,
    *,
    runtime_deadline: float,
    provider_call_packet_ids: frozenset[str] | None,
) -> tuple[
    tuple[dict[str, Any], ...],
    bytes,
    tuple[SemanticProblem, ...],
    int,
    int,
    int,
    dict[str, dict[str, int]],
    tuple[SemanticResultEnvelope, ...],
    tuple[SemanticSelectionEvent, ...],
]:
    """Resolve a held run-wide evidence-stable selection after preflight."""

    provider_call_budget = ProviderCallBudget(request.settings.maximum_provider_calls)
    adapter: ProviderAdapter | None = None
    adapter_error: Exception | None = None
    adapter_lock = threading.Lock()
    counter_lock = threading.Lock()
    provider_calls = 0
    provider_calls_by_kind = {
        "section": 0,
        "invariant": 0,
        "suppression": 0,
    }

    def get_adapter() -> ProviderAdapter:
        nonlocal adapter, adapter_error
        with adapter_lock:
            if adapter_error is not None:
                raise RuntimeError("semantic adapter construction failed") from (
                    adapter_error
                )
            if adapter is None:
                if request.adapter_factory is None:
                    raise RuntimeError("no provider adapter is available")
                try:
                    adapter = request.adapter_factory()
                except Exception as exc:
                    adapter_error = exc
                    raise
            return adapter

    def resolve_item(item: Any) -> SemanticSelectionEvent | SemanticProblem:
        packet = item.packet
        if request.settings.cache_mode == "require" and item.selection is None:
            return SemanticProblem(
                packet["packet_id"],
                "completeness",
                "incomplete_result",
                "required semantic cache result is missing",
            )

        def call_provider() -> Any:
            nonlocal provider_calls
            if time.monotonic() >= runtime_deadline:
                raise SemanticCacheFailure(
                    "budget",
                    "budget_exceeded",
                    "maximum semantic analysis runtime exceeded before provider call",
                )
            if (
                provider_call_packet_ids is not None
                and packet["packet_id"] not in provider_call_packet_ids
            ):
                raise SemanticCacheFailure(
                    "budget",
                    "budget_exceeded",
                    "unplanned provider call is outside the conservative cost preflight",
                )
            if not provider_call_budget.reserve():
                raise SemanticCacheFailure(
                    "budget",
                    "budget_exceeded",
                    "maximum semantic provider calls exceeded during execution",
                )
            try:
                selected_adapter = get_adapter()
            except Exception as exc:
                provider_call_budget.release()
                detail = exc.args[0] if isinstance(exc, KeyError) and exc.args else exc
                raise SemanticCacheFailure(
                    "provider",
                    "provider_failure",
                    f"adapter construction failed: {detail}",
                ) from exc
            with counter_lock:
                provider_calls += 1
                provider_calls_by_kind[cast(str, packet["kind"])] += 1
            try:
                response = selected_adapter(
                    model_request_bytes(
                        packet, instruction_bytes=item.identity.prompt_bytes
                    ).decode("utf-8")
                )
                if time.monotonic() >= runtime_deadline:
                    raise SemanticCacheFailure(
                        "budget",
                        "budget_exceeded",
                        "maximum semantic analysis runtime exceeded "
                        "during provider call",
                    )
                return response
            except SemanticCacheFailure:
                raise
            except Exception as exc:
                raise SemanticCacheFailure(
                    "provider", "provider_failure", f"model call failed: {exc}"
                ) from exc

        try:
            return resolve_prepared_evidence_stable_result(
                item,
                call_provider=call_provider,
                runtime_deadline=runtime_deadline,
            )
        except SemanticCacheFailure as exc:
            return SemanticProblem(
                packet["packet_id"], exc.stage, exc.code, exc.message
            )
        except Exception as exc:  # noqa: BLE001 - contain one packet boundary
            return SemanticProblem(
                packet["packet_id"],
                "cache",
                "corrupt_cache",
                f"unexpected cache failure: {exc}",
            )

    if request.settings.concurrency <= 1 or len(preparation.items) <= 1:
        outcomes = tuple(resolve_item(item) for item in preparation.items)
    else:
        with ThreadPoolExecutor(max_workers=request.settings.concurrency) as executor:
            outcomes = tuple(executor.map(resolve_item, preparation.items))

    problems = tuple(
        outcome for outcome in outcomes if isinstance(outcome, SemanticProblem)
    )
    events = tuple(
        outcome for outcome in outcomes if isinstance(outcome, SemanticSelectionEvent)
    )
    envelopes = tuple(event.envelope for event in events)
    results = tuple(envelope.result for envelope in envelopes)
    result_jsonl = b"".join(canonical_json_bytes(result) + b"\n" for result in results)
    kind_counts = _empty_analyzer_kind_counts()
    cache_hits = 0
    cache_misses = 0
    for item, outcome in zip(preparation.items, outcomes, strict=True):
        packet_kind = cast(str, item.packet["kind"])
        if item.is_genuine_miss and (
            not isinstance(outcome, SemanticSelectionEvent) or outcome.source == "live"
        ):
            cache_misses += 1
            kind_counts["cache_misses"][packet_kind] += 1
        elif isinstance(outcome, SemanticSelectionEvent):
            cache_hits += 1
            kind_counts["cache_hits"][packet_kind] += 1
    kind_counts["provider_calls"].update(provider_calls_by_kind)
    return (
        results,
        result_jsonl,
        problems,
        cache_hits,
        cache_misses,
        provider_calls,
        kind_counts,
        envelopes,
        events,
    )


def _run_evidence_stable_cache(
    request: SemanticAnalysisRequest,
    rows: tuple[dict[str, Any], ...],
    identities: tuple[InferenceIdentity, ...],
    authority: IndependentQualificationAuthority | None,
    *,
    runtime_deadline: float,
) -> tuple[
    tuple[dict[str, Any], ...],
    bytes,
    tuple[SemanticProblem, ...],
    int,
    int,
    int,
    dict[str, dict[str, int]],
    tuple[SemanticResultEnvelope, ...],
    tuple[SemanticSelectionEvent, ...],
    int | None,
]:
    """Hold the run-wide review cohort through qualification and preflight."""

    problems: list[SemanticProblem] = []
    estimated_cost: int | None = None
    try:
        with prepare_evidence_stable_cache(
            packets=request.packets,
            cache_path=request.settings.cache_path,
            cache_mode=cast(Any, request.settings.cache_mode),
            provider_identity=request.settings.provider_identity,
            identities=identities,
            lock_wait_timeout_seconds=request.settings.lock_wait_timeout_seconds,
            runtime_deadline=runtime_deadline,
        ) as preparation:
            producer_identities = tuple(
                item.producing_provider_identity for item in preparation.items
            )
            qualification_problem = _unqualified_selected_provider_problem(
                authority, producer_identities
            )
            if qualification_problem is not None:
                problems.append(
                    SemanticProblem(
                        qualification_problem.packet_id,
                        cast(Any, qualification_problem.stage),
                        cast(Any, qualification_problem.code),
                        qualification_problem.message,
                        qualification_problem.details,
                    )
                )
            planned_miss_ids = tuple(
                item.packet["packet_id"]
                for item in preparation.items
                if item.is_genuine_miss
            )
            planned_provider_calls = (
                len(planned_miss_ids)
                if request.settings.cache_mode == "read-write"
                else 0
            )
            if (
                not problems
                and planned_provider_calls > request.settings.maximum_provider_calls
            ):
                problems.append(
                    SemanticProblem(
                        None,
                        "budget",
                        "budget_exceeded",
                        "planned provider calls exceed analyze.maximum_provider_calls",
                    )
                )
            provider_call_packet_ids: frozenset[str] | None = None
            if request.settings.maximum_estimated_cost_microusd > 0:
                cost_miss_ids = (
                    planned_miss_ids
                    if request.settings.cache_mode == "read-write"
                    else ()
                )
                estimated_cost = _estimate_cost(
                    rows, identities, cost_miss_ids, request.settings
                )
                provider_call_packet_ids = frozenset(cost_miss_ids)
                if estimated_cost > request.settings.maximum_estimated_cost_microusd:
                    problems.append(
                        SemanticProblem(
                            None,
                            "budget",
                            "budget_exceeded",
                            "planned provider cost exceeds configured ceiling",
                        )
                    )
            if problems:
                return (
                    (),
                    b"",
                    tuple(problems),
                    0,
                    0,
                    0,
                    _empty_analyzer_kind_counts(),
                    (),
                    (),
                    estimated_cost,
                )
            execution = _execute_evidence_stable_preparation(
                request,
                preparation,
                runtime_deadline=runtime_deadline,
                provider_call_packet_ids=provider_call_packet_ids,
            )
            return (*execution, estimated_cost)
    except SemanticCacheFailure as exc:
        problems.append(SemanticProblem(None, exc.stage, exc.code, exc.message))
    except Exception as exc:  # noqa: BLE001 - untrusted filesystem boundary
        problems.append(
            SemanticProblem(
                None,
                "cache",
                "corrupt_cache",
                f"unexpected cache preparation failure: {exc}",
            )
        )
    return (
        (),
        b"",
        tuple(problems),
        0,
        0,
        0,
        _empty_analyzer_kind_counts(),
        (),
        (),
        estimated_cost,
    )


def _empty_analyzer_kind_counts() -> dict[str, dict[str, int]]:
    return {
        event: {"section": 0, "invariant": 0, "suppression": 0}
        for event in ("cache_hits", "cache_misses", "provider_calls")
    }


def _disabled_verification_report() -> dict[str, Any]:
    return {
        "state": "disabled",
        "contract": None,
        "events": [],
        "aggregate_counts": {
            "independently_verified": 0,
            "disputed": 0,
            "verification_indeterminate": 0,
        },
        "cache_hits": 0,
        "cache_misses": 0,
        "provider_calls": 0,
    }


def _enabled_verification_report(
    settings: ResolvedVerificationSettings,
    aggregates: tuple[VerificationAggregate, ...],
    run: VerificationCacheRun,
) -> dict[str, Any]:
    counts = {
        "independently_verified": 0,
        "disputed": 0,
        "verification_indeterminate": 0,
    }
    for aggregate in aggregates:
        counts[aggregate.aggregate_state] += 1
    return {
        "state": "enabled",
        "contract": settings.composition_identity.verify_composition,
        "events": [aggregate.event for aggregate in aggregates],
        "aggregate_counts": counts,
        "cache_hits": run.cache_hits,
        "cache_misses": run.cache_misses,
        "provider_calls": run.provider_calls,
    }


def _build_verification_work(
    rows: tuple[dict[str, Any], ...],
    results: tuple[dict[str, Any], ...],
    settings: ResolvedVerificationSettings,
) -> tuple[
    tuple[VerificationWork, ...],
    tuple[tuple[str, dict[str, Any], Any, Any, tuple[Any, ...]], ...],
]:
    packets = {row["packet_id"]: row for row in rows}
    effective_epochs = settings.effective_search_epochs or settings.search_epochs
    if (
        len(effective_epochs) != len(settings.search_epochs)
        or len(set(effective_epochs)) != len(effective_epochs)
        or any(not epoch.strip() for epoch in effective_epochs)
    ):
        raise ValueError(
            "effective verifier search epochs must be unique nonblank values "
            "matching verify.search_epochs cardinality"
        )
    work: list[VerificationWork] = []
    groups: list[tuple[str, dict[str, Any], Any, Any, tuple[Any, ...]]] = []
    for result in results:
        if result["classification"] == "ok":
            continue
        packet = packets[result["packet_id"]]
        claim = derive_verification_claim(packet, result)
        verifier_request = build_verification_request(packet, claim)
        identities = tuple(
            build_verify_identity(
                verifier_request,
                claim,
                settings.provider_identity,
                settings.request_identity,
                base_search_epoch=base_epoch,
                effective_search_epoch=effective_epoch,
            )
            for base_epoch, effective_epoch in zip(
                settings.search_epochs, effective_epochs, strict=True
            )
        )
        for base_epoch, effective_epoch, identity in zip(
            settings.search_epochs, effective_epochs, identities, strict=True
        ):
            work.append(
                VerificationWork(
                    packet,
                    claim,
                    verifier_request,
                    identity,
                    base_epoch,
                    effective_epoch,
                )
            )
        groups.append(
            (finding_hash(result), packet, claim, verifier_request, identities)
        )
    return tuple(work), tuple(groups)


def _estimate_verification_cost(
    work: tuple[VerificationWork, ...],
    miss_keys: tuple[str, ...],
    settings: ResolvedVerificationSettings,
) -> int:
    misses = set(miss_keys)
    total = 0
    for item in work:
        if item.identity.verify_key not in misses:
            continue
        input_tokens = (
            len(
                verifier_request_bytes(
                    item.request, prompt_bytes=item.identity.prompt_bytes
                )
            )
            + settings.input_token_overhead
        )
        total += _ceil_million(
            input_tokens * settings.input_cost_microusd_per_million_tokens
        )
        total += _ceil_million(
            settings.request_identity.max_tokens
            * settings.output_cost_microusd_per_million_tokens
        )
    return total


def _execute_verification_cache(
    request: SemanticAnalysisRequest,
    settings: ResolvedVerificationSettings,
    work: tuple[VerificationWork, ...],
    *,
    runtime_deadline: float,
) -> VerificationCacheRun:
    budget = ProviderCallBudget(settings.maximum_provider_calls)
    adapter_factory = request.verification_adapter_factory
    if settings.concurrency > 1 and adapter_factory is not None:
        construction_lock = threading.Lock()
        shared_adapter: ProviderAdapter | None = None
        construction_error: Exception | None = None

        def shared_factory() -> ProviderAdapter:
            nonlocal shared_adapter, construction_error
            with construction_lock:
                if construction_error is not None:
                    raise RuntimeError(
                        "verifier adapter construction failed"
                    ) from construction_error
                if shared_adapter is None:
                    try:
                        shared_adapter = adapter_factory()
                    except Exception as exc:
                        construction_error = exc
                        raise
                return shared_adapter

        effective_factory: AdapterFactory | None = shared_factory
    else:
        effective_factory = adapter_factory

    def execute(items: tuple[VerificationWork, ...]) -> VerificationCacheRun:
        return verify_with_cache(
            work_items=items,
            cache_path=settings.cache_path,
            cache_mode=settings.cache_mode,
            provider_identity=settings.provider_identity,
            request_identity=settings.request_identity,
            adapter_factory=effective_factory,
            lock_wait_timeout_seconds=settings.lock_wait_timeout_seconds,
            runtime_deadline=runtime_deadline,
            provider_call_budget=budget,
        )

    if settings.concurrency <= 1 or len(work) <= 1:
        return execute(work)
    with ThreadPoolExecutor(max_workers=settings.concurrency) as executor:
        runs = tuple(executor.map(lambda item: execute((item,)), work))
    return VerificationCacheRun(
        tuple(result for run in runs for result in run.results),
        tuple(problem for run in runs for problem in run.problems),
        sum(run.cache_hits for run in runs),
        sum(run.cache_misses for run in runs),
        sum(run.provider_calls for run in runs),
    )


def _execute_verification(
    request: SemanticAnalysisRequest,
    rows: tuple[dict[str, Any], ...],
    results: tuple[dict[str, Any], ...],
    *,
    runtime_deadline: float,
) -> tuple[
    dict[str, VerificationAggregate],
    dict[str, Any],
    tuple[SemanticProblem, ...],
    int | None,
]:
    settings = request.verification_settings
    if settings is None:
        return {}, _disabled_verification_report(), (), None
    work, groups = _build_verification_work(rows, results, settings)
    empty_run = VerificationCacheRun((), (), 0, 0, 0)
    if not work:
        return {}, _enabled_verification_report(settings, (), empty_run), (), None
    prompt_bytes = sum(
        len(
            verifier_request_bytes(
                item.request, prompt_bytes=item.identity.prompt_bytes
            )
        )
        for item in work
    )
    if prompt_bytes > settings.maximum_prompt_bytes:
        problem = SemanticProblem(
            None,
            "budget",
            "budget_exceeded",
            "verifier prompt bytes exceed verify.maximum_prompt_bytes",
        )
        return (
            {},
            _enabled_verification_report(settings, (), empty_run),
            (problem,),
            None,
        )
    inspection = inspect_verification_cache(
        work_items=work,
        cache_path=settings.cache_path,
        cache_mode=settings.cache_mode,
        provider_identity=settings.provider_identity,
        request_identity=settings.request_identity,
    )
    if inspection.problems:
        return (
            {},
            _enabled_verification_report(settings, (), empty_run),
            inspection.problems,
            None,
        )
    if inspection.planned_misses > settings.maximum_provider_calls:
        problem = SemanticProblem(
            None,
            "budget",
            "budget_exceeded",
            "planned verifier calls exceed verify.maximum_provider_calls",
        )
        return (
            {},
            _enabled_verification_report(settings, (), empty_run),
            (problem,),
            None,
        )
    estimated_cost: int | None = None
    if settings.maximum_estimated_cost_microusd > 0:
        estimated_cost = _estimate_verification_cost(
            work, inspection.planned_miss_verify_keys, settings
        )
        if estimated_cost > settings.maximum_estimated_cost_microusd:
            problem = SemanticProblem(
                None,
                "budget",
                "budget_exceeded",
                "planned verifier cost exceeds configured ceiling",
            )
            return (
                {},
                _enabled_verification_report(settings, (), empty_run),
                (problem,),
                estimated_cost,
            )
    run = _execute_verification_cache(
        request,
        settings,
        work,
        runtime_deadline=runtime_deadline,
    )
    if run.problems:
        return (
            {},
            _enabled_verification_report(settings, (), run),
            run.problems,
            estimated_cost,
        )
    result_by_key = {result.verify_key: result for result in run.results}
    aggregates: list[VerificationAggregate] = []
    by_finding: dict[str, VerificationAggregate] = {}
    for result_finding_hash, packet, claim, verifier_request, identities in groups:
        group_results = tuple(
            result_by_key[identity.verify_key] for identity in identities
        )
        aggregate = aggregate_verification_results(
            packet,
            claim,
            verifier_request,
            required_epochs=tuple(
                zip(
                    settings.search_epochs,
                    settings.effective_search_epochs or settings.search_epochs,
                    strict=True,
                )
            ),
            identities=identities,
            results=group_results,
            minimum_support_score=settings.minimum_support_score,
        )
        aggregates.append(aggregate)
        by_finding[result_finding_hash] = aggregate
    return (
        by_finding,
        _enabled_verification_report(settings, tuple(aggregates), run),
        (),
        estimated_cost,
    )


def _status(problems: list[SemanticAnalysisProblem]) -> str:
    if any(problem.stage in _FAILED_STAGES for problem in problems):
        return "failed"
    if problems:
        return "incomplete"
    return "complete"


def _exit_code(
    problems: list[SemanticAnalysisProblem],
    diagnostics: tuple[SemanticDiagnostic, ...],
) -> int:
    if problems:
        return 2
    if any(diagnostic.is_failure for diagnostic in diagnostics):
        return 1
    return 0


def _disposition_row(disposition: Any) -> dict[str, object]:
    return {
        "code": disposition.code,
        "packet_id": disposition.packet_id,
        "packet_hash": disposition.packet_hash,
        "finding_hash": disposition.finding_hash,
        "status": disposition.status,
        "reason": disposition.reason,
    }


def _resolve_independent_qualification(
    policy: SemanticPolicy,
    verification_settings: ResolvedVerificationSettings | None,
    evaluation_settings: VerifyEvalSettings | None = None,
) -> tuple[SemanticAnalysisProblem | None, IndependentQualificationAuthority | None]:
    """Resolve requested verifier failure authority before repository work."""

    selectors = list(
        dict.fromkeys(
            f"{entry.code}:independently_verified"
            for entry in policy.entries
            if entry.verification_state == "independently_verified"
            and entry.level in policy.fail_on
        )
    )
    if not selectors:
        return None, None
    current_composition: str | None = (
        verification_settings.composition_identity.composition_sha256
        if verification_settings is not None
        else None
    )
    from backstitch.obligation_runtime import ALGORITHMS

    current_derivation = {
        "snapshot_algorithm_version": ALGORITHMS.snapshot_algorithm_version,
        "obligation_algorithm_version": ALGORITHMS.obligation_algorithm_version,
        "discovery_algorithm_version": ALGORITHMS.discovery_algorithm_version,
        "packet_contract_version": ALGORITHMS.packet_contract_version,
        "normalization_version": ALGORITHMS.normalization_version,
    }
    current_qualification: dict[str, object] | None = None
    if evaluation_settings is not None and evaluation_settings.mode == "enforce":
        current_qualification = {
            "corpus_sha256": evaluation_settings.qualification_corpus_sha256,
            "mode": evaluation_settings.mode,
            "trials": evaluation_settings.trials,
            "eval_config": {
                "trials": evaluation_settings.trials,
                "interval_method": evaluation_settings.interval_method,
                "confidence_level": evaluation_settings.confidence_level,
                "minimum_positive_units": evaluation_settings.minimum_positive_units,
                "minimum_negative_units": evaluation_settings.minimum_negative_units,
                "minimum_evidence_sufficiency_rate": (
                    evaluation_settings.minimum_evidence_sufficiency_rate
                ),
                "minimum_conditional_precision": (
                    evaluation_settings.minimum_conditional_precision
                ),
                "minimum_conditional_recall": (
                    evaluation_settings.minimum_conditional_recall
                ),
                "minimum_end_to_end_recall": (
                    evaluation_settings.minimum_end_to_end_recall
                ),
                "minimum_recall_lower_bound": (
                    evaluation_settings.minimum_recall_lower_bound
                ),
                "maximum_false_positive_rate": (
                    evaluation_settings.maximum_false_positive_rate
                ),
                "maximum_false_positive_upper_bound": (
                    evaluation_settings.maximum_false_positive_upper_bound
                ),
                "maximum_indeterminate_rate": (
                    evaluation_settings.maximum_indeterminate_rate
                ),
                "maximum_uncached_flip_rate": (
                    evaluation_settings.maximum_uncached_flip_rate
                ),
                "require_all_critical": evaluation_settings.require_all_critical,
            },
        }
    action = (
        "Re-run qualification for the current source-derivation, qualification, "
        "and inference contracts or remove the failure-authority selector."
    )

    def qualification_details(
        identity: dict[str, object] | None,
    ) -> dict[str, object] | None:
        if identity is None:
            return None
        normalized = dict(identity)
        corpus_sha256 = normalized.get("corpus_sha256")
        if isinstance(corpus_sha256, str):
            normalized["corpus_sha256"] = corpus_sha256.removeprefix("sha256:")
        return normalized

    def unavailable(
        reason: str,
        *,
        raw_report_sha256: str | None = None,
        expected_derivation: dict[str, object] | None = None,
        expected_qualification: dict[str, object] | None = None,
        expected_composition: str | None = None,
    ) -> SemanticAnalysisProblem:
        return _problem(
            "qualification",
            "required_qualification_unavailable",
            action,
            details={
                "selectors": selectors,
                "reason": reason,
                "qualification_report_raw_sha256": raw_report_sha256,
                "expected_derivation_identity": expected_derivation,
                "current_derivation_identity": current_derivation,
                "expected_qualification_identity": qualification_details(
                    expected_qualification
                ),
                "current_qualification_identity": qualification_details(
                    current_qualification
                ),
                "expected_composition_sha256": expected_composition,
                "current_composition_sha256": current_composition,
                "unqualified_analyzer_providers": [],
            },
        )

    if (
        verification_settings is None
        or evaluation_settings is None
        or evaluation_settings.mode != "enforce"
        or not evaluation_settings.qualification_corpus.strip()
        or not evaluation_settings.qualification_corpus_sha256
        or not evaluation_settings.qualification_report.strip()
        or not evaluation_settings.qualification_report_sha256
    ):
        return unavailable("missing"), None

    corpus_path = Path(evaluation_settings.qualification_corpus)
    report_path = Path(evaluation_settings.qualification_report)
    raw_report_sha256: str | None = None
    try:
        from backstitch.semantic_eval import (
            derive_semantic_eval_observed_facts,
        )
        from backstitch.semantic_eval_reports import (
            load_semantic_eval_corpus,
            load_semantic_eval_report_bytes,
            read_semantic_eval_report_bytes,
            validate_semantic_eval_report_authoritatively,
        )

        resolved_report_path, raw_report = read_semantic_eval_report_bytes(report_path)
        raw_report_sha256 = hashlib.sha256(raw_report).hexdigest()
        corpus = load_semantic_eval_corpus(corpus_path, mode="enforce")
        if corpus.corpus_sha256 != evaluation_settings.qualification_corpus_sha256:
            return (
                unavailable("identity_mismatch", raw_report_sha256=raw_report_sha256),
                None,
            )
        report = load_semantic_eval_report_bytes(
            raw_report,
            path=resolved_report_path,
            corpus=corpus,
        )
        if report.report_sha256 != evaluation_settings.qualification_report_sha256:
            return (
                unavailable("identity_mismatch", raw_report_sha256=raw_report_sha256),
                None,
            )
        observed = derive_semantic_eval_observed_facts(corpus)
        report = validate_semantic_eval_report_authoritatively(
            report,
            corpus=corpus,
            observed=observed,
            path=resolved_report_path,
        )
    except FileNotFoundError:
        return unavailable("missing", raw_report_sha256=raw_report_sha256), None
    except (OSError, ValueError):
        return unavailable("corrupt", raw_report_sha256=raw_report_sha256), None

    report_value = report.to_dict()
    report_identity = cast(dict[str, Any], report_value["identity"])
    expected_derivation = {
        key: cast(object, report_identity[key]) for key in current_derivation
    }
    qualification = cast(dict[str, Any], report_value["qualification"])
    expected_qualification = {
        "corpus_sha256": report_identity["corpus_sha256"],
        "mode": qualification["mode"],
        "trials": report_identity["trials"],
        "eval_config": report_identity["eval_config"],
    }
    expected_composition = cast(str, report_identity["composition_sha256"])
    identity_matches = (
        expected_derivation == current_derivation
        and expected_qualification == current_qualification
        and expected_composition == current_composition
    )
    if not identity_matches:
        return (
            unavailable(
                "identity_mismatch",
                raw_report_sha256=raw_report_sha256,
                expected_derivation=expected_derivation,
                expected_qualification=expected_qualification,
                expected_composition=expected_composition,
            ),
            None,
        )
    qualified_codes = {
        cast(str, item["code"])
        for item in cast(list[dict[str, Any]], report_value["by_code"])
    }
    selected_codes = {selector.rsplit(":", 1)[0] for selector in selectors}
    if not report.passed or not selected_codes <= qualified_codes:
        return (
            unavailable(
                "failed",
                raw_report_sha256=raw_report_sha256,
                expected_derivation=expected_derivation,
                expected_qualification=expected_qualification,
                expected_composition=expected_composition,
            ),
            None,
        )
    assert verification_settings is not None
    details: dict[str, object] = {
        "selectors": selectors,
        "reason": "identity_mismatch",
        "qualification_report_raw_sha256": raw_report_sha256,
        "expected_derivation_identity": expected_derivation,
        "current_derivation_identity": current_derivation,
        "expected_qualification_identity": qualification_details(
            expected_qualification
        ),
        "current_qualification_identity": qualification_details(current_qualification),
        "expected_composition_sha256": expected_composition,
        "current_composition_sha256": current_composition,
        "unqualified_analyzer_providers": [],
    }
    return (
        None,
        IndependentQualificationAuthority(
            selectors=tuple(selectors),
            analyzer_provider=ProviderIdentity(
                **cast(
                    dict[str, Any],
                    verification_settings.composition_identity.analysis_composition[
                        "provider"
                    ],
                )
            ),
            problem_details=details,
        ),
    )


def required_independent_qualification_problem(
    policy: SemanticPolicy,
    verification_settings: ResolvedVerificationSettings | None,
    evaluation_settings: VerifyEvalSettings | None = None,
) -> SemanticAnalysisProblem | None:
    """Resolve requested verifier failure authority before repository work."""

    problem, _authority = _resolve_independent_qualification(
        policy,
        verification_settings,
        evaluation_settings,
    )
    return problem


def _unqualified_selected_provider_problem(
    authority: IndependentQualificationAuthority | None,
    providers: tuple[ProviderIdentity, ...],
) -> SemanticAnalysisProblem | None:
    if authority is None:
        return None
    foreign = {
        canonical_json_bytes(asdict(provider)): asdict(provider)
        for provider in providers
        if provider != authority.analyzer_provider
    }
    if not foreign:
        return None
    details = dict(authority.problem_details)
    details["unqualified_analyzer_providers"] = [
        foreign[key] for key in sorted(foreign)
    ]
    return _problem(
        "qualification",
        "required_qualification_unavailable",
        "Re-run qualification for the current source-derivation, qualification, "
        "and inference contracts or remove the failure-authority selector.",
        details=details,
    )


def _build_report(
    *,
    request: SemanticAnalysisRequest,
    rows: tuple[dict[str, Any], ...],
    results: tuple[dict[str, Any], ...],
    result_jsonl: bytes,
    projection: SemanticProjectionRun,
    problems: list[SemanticAnalysisProblem],
    analysis_exit_code: int,
    cache_hits: int,
    cache_misses: int,
    provider_calls: int,
    analyzer_kind_counts: dict[str, dict[str, int]],
    prompt_byte_count: int,
    elapsed_milliseconds: int,
    estimated_cost_microusd: int | None,
    cost_rate_source: str | None,
    verification: dict[str, Any],
    identities: tuple[InferenceIdentity, ...],
    result_envelopes: tuple[SemanticResultEnvelope, ...],
    selection_events: tuple[SemanticSelectionEvent, ...],
) -> dict[str, Any]:
    if request.packet_report is None:
        raise ValueError("current analysis report requires a packet report")
    packet_report = request.packet_report.to_dict()
    packet_report_schema = packet_report.get("schema_version")
    if packet_report_schema not in {2, 3}:
        raise ValueError("analysis report requires packet report schema 2 or 3")
    schema_version = 5 if packet_report_schema == 3 else 3
    report = {
        "schema_version": schema_version,
        "artifact": "backstitch-analysis-report",
        "scope": request.scope,
        "semantic_status": request.semantic_status,
        "artifact_integrity": "valid",
        "artifact_currentness": request.artifact_currentness,
        "source_provenance": request.source_provenance,
        "source_snapshot": packet_report["source_snapshot"],
        "packet_report_content_sha256": packet_report["packet_report_content_sha256"],
        "alignment_summary": packet_report["readiness_counts"],
        "alignment_audit": packet_report["alignment_audit"],
        "deterministic_issues": packet_report["deterministic_issues"],
        "packet_jsonl_sha256": request.packet_jsonl_sha256,
        "result_jsonl_sha256": hashlib.sha256(result_jsonl).hexdigest(),
        "status": (
            "incomplete" if projection.requires_disposition else _status(problems)
        ),
        "analysis_exit_code": analysis_exit_code,
        "packet_count": len(rows),
        "result_count": len(results),
        "packet_warning_count": 0,
        "packet_warning_debt": [],
        "finding_debt": [item.to_row() for item in projection.finding_debt],
        "cache_hits": cache_hits,
        "cache_misses": cache_misses,
        "provider_calls": provider_calls,
        "prompt_byte_count": prompt_byte_count,
        "elapsed_milliseconds": elapsed_milliseconds,
        "estimated_cost_microusd": estimated_cost_microusd,
        "cost_rate_source": cost_rate_source,
        "effective_policy_layers": list(request.policy.effective_policy_layers),
        "semantic_diagnostics": [
            diagnostic.to_row() for diagnostic in projection.diagnostics
        ],
        "unused_dispositions": [
            _disposition_row(item) for item in projection.unused_dispositions
        ],
        "verification": verification,
        "problems": [problem.to_row() for problem in problems],
    }
    if schema_version == 5:
        # [SEM-7] blast radius: these aggregate counters and the per-kind
        # projection must be derived from the same actual cache/provider events.
        operational_totals = {
            event: sum(analyzer_kind_counts[event].values())
            for event in ("cache_hits", "cache_misses", "provider_calls")
        }
        report.update(operational_totals)
        report["packet_schema_versions"] = packet_report["packet_schema_versions"]
        report["kind_counts"] = {
            "eligible": dict(packet_report["kind_counts"]["eligible"]),
            "emitted": dict(packet_report["kind_counts"]["emitted"]),
            "results": {
                packet_kind: sum(row["kind"] == packet_kind for row in results)
                for packet_kind in ("section", "invariant", "suppression")
            },
            **{
                event: dict(analyzer_kind_counts[event])
                for event in ("cache_hits", "cache_misses", "provider_calls")
            },
        }
        prompts_by_kind: dict[str, dict[str, object]] = {}
        for packet_row, identity in zip(rows, identities, strict=True):
            prompt = cast(dict[str, object], identity.contract["prompt"])
            prompts_by_kind.setdefault(
                cast(str, packet_row["kind"]),
                {"kind": packet_row["kind"], **prompt},
            )
        source_rows: list[dict[str, object]] = []
        provider_groups: dict[bytes, dict[str, object]] = {}
        for envelope, event in zip(result_envelopes, selection_events, strict=True):
            result = envelope.result
            provenance = asdict(envelope.provenance)
            source_rows.append(
                {
                    "packet_id": result["packet_id"],
                    "packet_hash": result["packet_hash"],
                    "analysis_key": envelope.analysis_key,
                    "review_key": event.review_key,
                    "result_object_sha256": envelope.result_object_sha256,
                    "inference_contract": envelope.inference_contract,
                    "provenance": provenance,
                    "selection": event.source,
                }
            )
            observed_model = {
                key: provenance[key]
                for key in (
                    "model_class",
                    "provider_model_id",
                    "provider_model_revision",
                )
            }
            provider = asdict(envelope.provider_identity)
            group_key = canonical_json_bytes(
                {"provider": provider, "observed_model": observed_model}
            )
            group = provider_groups.setdefault(
                group_key,
                {
                    "provider": provider,
                    "observed_model": observed_model,
                    "result_count": 0,
                    "carried_result_count": 0,
                },
            )
            group["result_count"] = cast(int, group["result_count"]) + 1
            group["carried_result_count"] = cast(
                int, group["carried_result_count"]
            ) + int(event.source == "carried")
        report.update(
            {
                "result_reuse": request.settings.result_reuse,
                "selected_inference": {
                    "provider": asdict(request.settings.provider_identity),
                    "request": asdict(request.settings.request_identity),
                    "analysis_contract_version": 1,
                    "search_epoch": request.settings.search_epoch,
                    "prompts": [
                        prompts_by_kind[kind]
                        for kind in ("section", "invariant", "suppression")
                        if kind in prompts_by_kind
                    ],
                },
                "exact_cache_hits": sum(
                    event.source == "exact-cache" for event in selection_events
                ),
                "carried_results": sum(
                    event.source == "carried" for event in selection_events
                ),
                "result_sources": source_rows,
                "result_providers": [
                    provider_groups[key] for key in sorted(provider_groups)
                ],
            }
        )
    return report


def _analysis_validation_facts(
    envelopes: tuple[SemanticResultEnvelope, ...],
    events: tuple[SemanticSelectionEvent, ...],
) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, object], ...]]:
    objects = tuple(envelope.object for envelope in envelopes)
    event_rows = tuple(
        {
            "packet_id": event.envelope.result["packet_id"],
            "packet_hash": event.envelope.result["packet_hash"],
            "result_object_sha256": event.envelope.result_object_sha256,
            "selection": event.source,
        }
        for event in events
    )
    return objects, event_rows


def _stderr_lines(
    request: SemanticAnalysisRequest,
    projection: SemanticProjectionRun,
    problems: list[SemanticAnalysisProblem],
    verification: dict[str, Any],
) -> tuple[str, ...]:
    lines: list[str] = []
    for problem in problems:
        locator = f" {problem.packet_id}" if problem.packet_id is not None else ""
        message = " ".join(problem.message.split())
        lines.append(
            f"backstitch: error: {problem.stage}/{problem.code}{locator}: {message}"
        )
    for diagnostic in projection.diagnostics:
        if diagnostic.severity == "off":
            continue
        lines.append(
            f"backstitch: {diagnostic.severity}: {diagnostic.short_code}"
            f" {diagnostic.packet_id} ({diagnostic.verification_state})"
        )
    if projection.finding_debt:
        lines.append(
            f"backstitch: warning: {len(projection.finding_debt)} semantic finding(s)"
            " require review"
        )
    if (
        request.verification_settings is not None
        and request.verification_settings.indeterminate == "report"
        and verification["aggregate_counts"]["verification_indeterminate"]
    ):
        lines.append(
            "backstitch: warning: "
            f"{verification['aggregate_counts']['verification_indeterminate']} "
            "semantic verification event(s) are indeterminate"
        )
    return tuple(lines)


def run_semantic_analysis(request: SemanticAnalysisRequest) -> SemanticAnalysisRun:
    """Run the complete semantic gate once and publish result then report."""

    return _run_semantic_analysis(request, runtime_deadline=None)


def _run_semantic_analysis(
    request: SemanticAnalysisRequest,
    *,
    runtime_deadline: float | None,
) -> SemanticAnalysisRun:
    """Internal shared runner with an optional enclosing absolute deadline."""

    started = time.monotonic()
    problems: list[SemanticAnalysisProblem] = []
    results: tuple[dict[str, Any], ...] = ()
    result_jsonl = b""
    result_envelopes: tuple[SemanticResultEnvelope, ...] = ()
    selection_events: tuple[SemanticSelectionEvent, ...] = ()
    cache_hits = 0
    cache_misses = 0
    provider_calls = 0
    analyzer_kind_counts = _empty_analyzer_kind_counts()
    estimated_cost: int | None = None
    verification_cost: int | None = None
    verification_report = (
        _disabled_verification_report()
        if request.verification_settings is None
        else _enabled_verification_report(
            request.verification_settings,
            (),
            VerificationCacheRun((), (), 0, 0, 0),
        )
    )
    planned_miss_packet_ids: tuple[str, ...] = ()
    rows = tuple(packet.to_dict() for packet in request.packets)
    try:
        identities = tuple(
            build_inference_identity(
                row,
                request.settings.provider_identity,
                request.settings.request_identity,
                search_epoch=request.settings.search_epoch,
            )
            for row in rows
        )
    except ValueError as exc:
        identities = ()
        problems.append(
            _problem(
                "input",
                "invalid_input",
                f"cannot freeze semantic inference identity: {exc}",
            )
        )
    prompt_byte_count = (
        sum(
            len(model_request_bytes(row, instruction_bytes=identity.prompt_bytes))
            for row, identity in zip(rows, identities, strict=True)
        )
        if len(identities) == len(rows)
        else 0
    )

    alias_problem = _path_alias_problem(request)
    skip_publication = alias_problem is not None
    if alias_problem is not None:
        problems.append(_problem("input", "invalid_input", alias_problem))
    if not is_sha256_hex(request.packet_jsonl_sha256):
        problems.append(
            _problem(
                "input",
                "invalid_input",
                "packet_jsonl_sha256 must be lowercase SHA-256",
            )
        )
    packet_ids = [row["packet_id"] for row in rows]
    if len(packet_ids) != len(set(packet_ids)):
        problems.append(
            _problem("input", "invalid_input", "duplicate semantic packet ID")
        )

    validated_report: PacketReport | None = None
    if not problems:
        report_problems, validated_report = _packet_report_preflight(
            request, rows, identities
        )
        problems.extend(report_problems)
    cost_problem = _validate_cost_contract(request.settings)
    if cost_problem is not None:
        problems.append(cost_problem)
    verification_cost_problem = _validate_verification_cost_contract(
        request.verification_settings
    )
    if verification_cost_problem is not None:
        problems.append(verification_cost_problem)
    if request.settings.cache_mode == "require" and request.adapter_factory is not None:
        problems.append(
            _problem(
                "config",
                "invalid_config",
                "require cache mode forbids an adapter factory",
            )
        )
    if (
        request.verification_settings is not None
        and request.verification_settings.cache_mode == "require"
        and request.verification_adapter_factory is not None
    ):
        problems.append(
            _problem(
                "config",
                "invalid_config",
                "require verifier cache mode forbids an adapter factory",
            )
        )
    if (
        request.verification_settings is None
        and request.verification_adapter_factory is not None
    ):
        problems.append(
            _problem(
                "config",
                "invalid_config",
                "disabled verification forbids a verifier adapter factory",
            )
        )
    if request.settings.concurrency < 1:
        problems.append(
            _problem(
                "config",
                "invalid_config",
                "semantic analysis concurrency must be at least one",
            )
        )
    if request.settings.result_reuse not in {
        "evidence-stable",
        "exact-inference",
    }:
        problems.append(
            _problem(
                "config",
                "invalid_config",
                "semantic result reuse must be evidence-stable or exact-inference",
            )
        )
    qualification_problem, qualification_authority = _resolve_independent_qualification(
        request.policy,
        request.verification_settings,
        request.evaluation_settings,
    )
    if qualification_problem is not None:
        problems.append(qualification_problem)

    projection = _empty_projection(request)
    configured_runtime = request.settings.maximum_runtime_seconds
    if request.verification_settings is not None:
        configured_runtime = min(
            configured_runtime,
            request.verification_settings.maximum_runtime_seconds,
        )
    deadline = (
        runtime_deadline
        if runtime_deadline is not None
        else started + configured_runtime
    )
    evidence_stable_cached = (
        request.settings.result_reuse == "evidence-stable"
        and request.settings.cache_mode in {"read-write", "require"}
    )
    if not problems and not evidence_stable_cached:
        inspection = inspect_semantic_cache(
            packets=request.packets,
            cache_path=request.settings.cache_path,
            cache_mode=request.settings.cache_mode,
            provider_identity=request.settings.provider_identity,
            request_identity=request.settings.request_identity,
            search_epoch=request.settings.search_epoch,
            identities=identities,
        )
        cache_hits = inspection.planned_hits
        cache_misses = inspection.planned_misses
        planned_miss_packet_ids = inspection.planned_miss_packet_ids
        problems.extend(_cache_problem(problem) for problem in inspection.problems)
        if (
            not problems
            and inspection.planned_misses > request.settings.maximum_provider_calls
        ):
            problems.append(
                _problem(
                    "budget",
                    "budget_exceeded",
                    "planned provider calls exceed analyze.maximum_provider_calls",
                )
            )
        if request.settings.maximum_estimated_cost_microusd > 0:
            estimated_cost = _estimate_cost(
                rows,
                identities,
                (
                    ()
                    if request.settings.cache_mode == "require"
                    else inspection.planned_miss_packet_ids
                ),
                request.settings,
            )
            if estimated_cost > request.settings.maximum_estimated_cost_microusd:
                problems.append(
                    _problem(
                        "budget",
                        "budget_exceeded",
                        "planned provider cost exceeds configured ceiling",
                    )
                )

    if not problems:
        if evidence_stable_cached:
            (
                results,
                result_jsonl,
                cache_problems,
                cache_hits,
                cache_misses,
                provider_calls,
                analyzer_kind_counts,
                result_envelopes,
                selection_events,
                stable_estimated_cost,
            ) = _run_evidence_stable_cache(
                request,
                rows,
                identities,
                qualification_authority,
                runtime_deadline=deadline,
            )
            if stable_estimated_cost is not None:
                estimated_cost = stable_estimated_cost
        else:
            (
                results,
                result_jsonl,
                cache_problems,
                cache_hits,
                cache_misses,
                provider_calls,
                analyzer_kind_counts,
                result_envelopes,
                selection_events,
            ) = _execute_cache(
                request,
                identities,
                runtime_deadline=deadline,
                provider_call_packet_ids=(
                    frozenset(planned_miss_packet_ids)
                    if request.settings.maximum_estimated_cost_microusd > 0
                    else None
                ),
            )
        problems.extend(_cache_problem(problem) for problem in cache_problems)
        verification_aggregates: dict[str, VerificationAggregate] = {}
        if not problems:
            (
                verification_aggregates,
                verification_report,
                verification_problems,
                verification_cost,
            ) = _execute_verification(
                request,
                rows,
                results,
                runtime_deadline=deadline,
            )
            problems.extend(
                _cache_problem(problem) for problem in verification_problems
            )
        if not problems:
            projection = project_semantic_results(
                results,
                request.policy,
                request.settings.dispositions,
                finding_handling=request.settings.finding_handling,
                verification_aggregates=verification_aggregates,
            )
        if (
            request.settings.require_complete
            and len(results) != len(rows)
            and not problems
        ):
            problems.append(
                _problem(
                    "completeness",
                    "incomplete_result",
                    "one valid semantic result is required for every packet",
                )
            )

    if any(problem.stage in {"config", "input"} for problem in problems):
        skip_publication = True

    analysis_exit_code = (
        2
        if projection.requires_disposition
        else _exit_code(problems, projection.diagnostics)
    )
    cost_rate_source: str | None = None
    if estimated_cost is not None:
        cost_rate_source = request.settings.cost_rate_source
    if verification_cost is not None:
        assert request.verification_settings is not None
        verify_source = request.verification_settings.cost_rate_source
        if cost_rate_source is None or cost_rate_source == verify_source:
            cost_rate_source = verify_source
        else:
            cost_rate_source = f"analyze: {cost_rate_source}; verify: {verify_source}"
        estimated_cost = (estimated_cost or 0) + verification_cost
    elapsed = max(0, int((time.monotonic() - started) * 1000))
    selected_result_objects, selection_event_rows = _analysis_validation_facts(
        result_envelopes,
        selection_events,
    )
    if validated_report is None:
        return SemanticAnalysisRun(
            results=results,
            diagnostics=projection.diagnostics,
            problems=tuple(problems),
            result_jsonl=result_jsonl,
            report={},
            report_json=b"",
            stderr_lines=_stderr_lines(
                request,
                projection,
                problems,
                verification_report,
            ),
            exit_code=2,
            selected_result_objects=selected_result_objects,
            selection_events=selection_event_rows,
        )
    report = _build_report(
        request=request,
        rows=rows,
        results=results,
        result_jsonl=result_jsonl,
        projection=projection,
        problems=problems,
        analysis_exit_code=analysis_exit_code,
        cache_hits=cache_hits,
        cache_misses=cache_misses,
        provider_calls=provider_calls,
        analyzer_kind_counts=analyzer_kind_counts,
        prompt_byte_count=(prompt_byte_count),
        elapsed_milliseconds=elapsed,
        estimated_cost_microusd=estimated_cost,
        cost_rate_source=cost_rate_source,
        verification=verification_report,
        identities=identities,
        result_envelopes=result_envelopes,
        selection_events=selection_events,
    )
    schema5_result_objects = (
        selected_result_objects
        if validated_report.to_dict()["schema_version"] == 3
        else None
    )
    schema5_selection_events = (
        selection_event_rows
        if validated_report.to_dict()["schema_version"] == 3
        else None
    )
    validated_analysis_report = validate_analysis_report(
        report,
        result_jsonl=result_jsonl,
        packet_jsonl_sha256=request.packet_jsonl_sha256,
        packet_report=validated_report,
        packets=request.packets,
        selected_result_objects=schema5_result_objects,
        selection_events=schema5_selection_events,
        expected_scope=request.scope,
        expected_semantic_status=request.semantic_status,
        expected_artifact_currentness=request.artifact_currentness,
        expected_source_provenance=request.source_provenance,
    )
    report = validated_analysis_report.to_dict()
    report_json = validated_analysis_report.to_json_bytes()
    final_exit_code = analysis_exit_code

    if not skip_publication:
        if request.result_path is not None:
            try:
                atomic_replace_bytes(request.result_path, result_jsonl)
            except OSError as exc:
                problems.append(
                    _problem(
                        "output",
                        "output_failure",
                        f"cannot publish semantic result: {exc}",
                    )
                )
                final_exit_code = 2
                report = _build_report(
                    request=request,
                    rows=rows,
                    results=results,
                    result_jsonl=result_jsonl,
                    projection=projection,
                    problems=problems,
                    analysis_exit_code=analysis_exit_code,
                    cache_hits=cache_hits,
                    cache_misses=cache_misses,
                    provider_calls=provider_calls,
                    analyzer_kind_counts=analyzer_kind_counts,
                    prompt_byte_count=prompt_byte_count,
                    elapsed_milliseconds=elapsed,
                    estimated_cost_microusd=estimated_cost,
                    cost_rate_source=cost_rate_source,
                    verification=verification_report,
                    identities=identities,
                    result_envelopes=result_envelopes,
                    selection_events=selection_events,
                )
                validated_analysis_report = validate_analysis_report(
                    report,
                    result_jsonl=result_jsonl,
                    packet_jsonl_sha256=request.packet_jsonl_sha256,
                    packet_report=validated_report,
                    packets=request.packets,
                    selected_result_objects=schema5_result_objects,
                    selection_events=schema5_selection_events,
                    expected_scope=request.scope,
                    expected_semantic_status=request.semantic_status,
                    expected_artifact_currentness=request.artifact_currentness,
                    expected_source_provenance=request.source_provenance,
                )
                report = validated_analysis_report.to_dict()
                report_json = validated_analysis_report.to_json_bytes()
        if request.report_path is not None:
            try:
                atomic_replace_bytes(request.report_path, report_json)
            except OSError as exc:
                problems.append(
                    _problem(
                        "output",
                        "output_failure",
                        f"cannot publish semantic report: {exc}",
                    )
                )
                final_exit_code = 2
                report = _build_report(
                    request=request,
                    rows=rows,
                    results=results,
                    result_jsonl=result_jsonl,
                    projection=projection,
                    problems=problems,
                    analysis_exit_code=analysis_exit_code,
                    cache_hits=cache_hits,
                    cache_misses=cache_misses,
                    provider_calls=provider_calls,
                    analyzer_kind_counts=analyzer_kind_counts,
                    prompt_byte_count=prompt_byte_count,
                    elapsed_milliseconds=elapsed,
                    estimated_cost_microusd=estimated_cost,
                    cost_rate_source=cost_rate_source,
                    verification=verification_report,
                    identities=identities,
                    result_envelopes=result_envelopes,
                    selection_events=selection_events,
                )
                validated_analysis_report = validate_analysis_report(
                    report,
                    result_jsonl=result_jsonl,
                    packet_jsonl_sha256=request.packet_jsonl_sha256,
                    packet_report=validated_report,
                    packets=request.packets,
                    selected_result_objects=schema5_result_objects,
                    selection_events=schema5_selection_events,
                    expected_scope=request.scope,
                    expected_semantic_status=request.semantic_status,
                    expected_artifact_currentness=request.artifact_currentness,
                    expected_source_provenance=request.source_provenance,
                )
                report = validated_analysis_report.to_dict()
                report_json = validated_analysis_report.to_json_bytes()

    return SemanticAnalysisRun(
        results=results,
        diagnostics=projection.diagnostics,
        problems=tuple(problems),
        result_jsonl=result_jsonl,
        report=report,
        report_json=report_json,
        stderr_lines=_stderr_lines(
            request,
            projection,
            problems,
            verification_report,
        ),
        exit_code=final_exit_code,
        selected_result_objects=selected_result_objects,
        selection_events=selection_event_rows,
    )
