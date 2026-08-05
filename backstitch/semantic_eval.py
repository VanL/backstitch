"""Measured schema-3 semantic qualification over source-derived packets.

The runner owns fresh analyzer/verifier caches and calls the ordinary snapshot,
readiness, packet, normalization, cache, claim, and verifier boundaries. Gold
never enters a repository or provider request.

Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-10.1]
"""

from __future__ import annotations

import hashlib
import json
import math
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal, cast

from backstitch.artifact_contracts import ValidatedSemanticPacket
from backstitch.artifact_publication import atomic_replace_bytes
from backstitch.canonical import canonical_json_bytes
from backstitch.obligation_runtime import ALGORITHMS
from backstitch.semantic_analysis import (
    ResolvedSemanticSettings,
    ResolvedVerificationSettings,
)
from backstitch.semantic_cache import (
    AdapterFactory,
    ProviderAdapter,
    ProviderCallBudget,
    analyze_with_cache,
    verify_with_cache,
)
from backstitch.semantic_eval_identity import derive_eval_search_epoch
from backstitch.semantic_eval_observation import (
    SemanticEvalError,
    SemanticEvalVariantBuild,
    derive_semantic_eval_observed_facts,
    derive_semantic_eval_variant,
    observed_semantic_eval_facts,
    semantic_eval_case_rows,
)
from backstitch.semantic_eval_reports import (
    SemanticEvalContractError,
    SemanticEvalCorpus,
    derive_semantic_eval_metrics,
    load_semantic_eval_corpus,
    validate_semantic_eval_report_authoritatively,
)
from backstitch.semantic_identity import (
    InferenceIdentity,
    RequestIdentity,
    build_inference_identity,
)
from backstitch.semantic_packets import model_request_bytes
from backstitch.semantic_policy import SEMANTIC_DEFINITIONS
from backstitch.semantic_verification import (
    aggregate_verification_results,
    build_verification_work,
    verifier_request_bytes,
)
from backstitch.semantic_verification_contract import VerificationWork
from backstitch.settings import VerifyEvalSettings

__all__ = (
    "SemanticEvalError",
    "SemanticEvalRequest",
    "SemanticEvalRun",
    "derive_semantic_eval_observed_facts",
    "run_semantic_eval",
)

# [EVC-10.1] intentionally remains the measured BSA001-BSA005 corpus. Adding
# product classifications must not silently widen qualification authority.
_MEASURED_SHORT_CODES = ("BSA001", "BSA002", "BSA003", "BSA004", "BSA005")
_MEASURED_SEMANTIC_DEFINITIONS = tuple(
    definition
    for definition in SEMANTIC_DEFINITIONS
    if definition.short_code in _MEASURED_SHORT_CODES
)
_CODE_BY_CLASSIFICATION = {
    definition.classification: definition.code
    for definition in _MEASURED_SEMANTIC_DEFINITIONS
}
_CODE_ORDER = {
    definition.code: index
    for index, definition in enumerate(_MEASURED_SEMANTIC_DEFINITIONS)
}


@dataclass(frozen=True, slots=True)
class SemanticEvalRequest:
    manifest_path: Path
    output_path: Path
    settings: ResolvedSemanticSettings
    verification_settings: ResolvedVerificationSettings
    eval_settings: VerifyEvalSettings
    adapter_factory: AdapterFactory
    verification_adapter_factory: AdapterFactory


@dataclass(frozen=True, slots=True)
class SemanticEvalRun:
    report: dict[str, Any]
    report_json: bytes
    stderr_lines: tuple[str, ...]
    exit_code: Literal[0, 2]


@dataclass(frozen=True, slots=True)
class _AnalyzerObject:
    result: dict[str, Any]
    cache_object: dict[str, Any]
    cache_bytes: bytes


@dataclass(frozen=True, slots=True)
class _VerifierObject:
    canonical_result: Any
    result: dict[str, Any]
    cache_object: dict[str, Any]
    cache_bytes: bytes


@dataclass(frozen=True, slots=True)
class _FindingGroup:
    trial_index: int
    case_id: str
    variant_id: str
    obligation_id: str
    packet: dict[str, Any]
    finding_hash: str
    claim: Any
    request: Any
    identities: tuple[Any, ...]


def _shared_factory(factory: AdapterFactory) -> AdapterFactory:
    adapter: ProviderAdapter | None = None

    def build() -> ProviderAdapter:
        nonlocal adapter
        if adapter is None:
            adapter = factory()
        return adapter

    return build


def _cache_object(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SemanticEvalError(
            f"evaluation cache object is invalid JSON: {path}"
        ) from exc
    if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
        raise SemanticEvalError(f"evaluation cache object is not canonical: {path}")
    return cast(dict[str, Any], value), raw


def _analysis_cost(
    packets: Mapping[str, tuple[ValidatedSemanticPacket, InferenceIdentity]],
    settings: ResolvedSemanticSettings,
) -> tuple[int | None, str | None]:
    if not packets:
        return 0, None
    if not settings.cost_rate_source.strip():
        return None, None
    total = 0
    for packet, identity in packets.values():
        input_units = (
            len(
                model_request_bytes(
                    packet.to_dict(),
                    instruction_bytes=identity.prompt_bytes,
                )
            )
            + settings.input_token_overhead
        )
        total += math.ceil(
            input_units * settings.input_cost_microusd_per_million_tokens / 1_000_000
        )
        total += math.ceil(
            _costed_max_tokens(settings.request_identity)
            * settings.output_cost_microusd_per_million_tokens
            / 1_000_000
        )
    return total, settings.cost_rate_source


def _verification_cost(
    work: Mapping[str, VerificationWork], settings: ResolvedVerificationSettings
) -> tuple[int | None, str | None]:
    if not work:
        return 0, None
    if not settings.cost_rate_source.strip():
        return None, None
    total = 0
    for item in work.values():
        input_units = (
            len(
                verifier_request_bytes(
                    item.request, prompt_bytes=item.identity.prompt_bytes
                )
            )
            + settings.input_token_overhead
        )
        total += math.ceil(
            input_units * settings.input_cost_microusd_per_million_tokens / 1_000_000
        )
        total += math.ceil(
            _costed_max_tokens(settings.request_identity)
            * settings.output_cost_microusd_per_million_tokens
            / 1_000_000
        )
    return total, settings.cost_rate_source


def _costed_max_tokens(request: RequestIdentity) -> int:
    if request.max_tokens is None:
        raise ValueError("costed inference requires present max_tokens")
    return request.max_tokens


def _eval_config(settings: VerifyEvalSettings) -> dict[str, Any]:
    return {
        "trials": settings.trials,
        "interval_method": settings.interval_method,
        "confidence_level": settings.confidence_level,
        "minimum_positive_units": settings.minimum_positive_units,
        "minimum_negative_units": settings.minimum_negative_units,
        "minimum_evidence_sufficiency_rate": settings.minimum_evidence_sufficiency_rate,
        "minimum_conditional_precision": settings.minimum_conditional_precision,
        "minimum_conditional_recall": settings.minimum_conditional_recall,
        "minimum_end_to_end_recall": settings.minimum_end_to_end_recall,
        "minimum_recall_lower_bound": settings.minimum_recall_lower_bound,
        "maximum_false_positive_rate": settings.maximum_false_positive_rate,
        "maximum_false_positive_upper_bound": settings.maximum_false_positive_upper_bound,
        "maximum_indeterminate_rate": settings.maximum_indeterminate_rate,
        "maximum_uncached_flip_rate": settings.maximum_uncached_flip_rate,
        "require_all_critical": settings.require_all_critical,
    }


def _identity(
    corpus: SemanticEvalCorpus,
    request: SemanticEvalRequest,
) -> dict[str, Any]:
    composition = request.verification_settings.composition_identity
    return {
        "corpus_sha256": corpus.corpus_sha256,
        "snapshot_algorithm_version": ALGORITHMS.snapshot_algorithm_version,
        "obligation_algorithm_version": ALGORITHMS.obligation_algorithm_version,
        "discovery_algorithm_version": ALGORITHMS.discovery_algorithm_version,
        "packet_contract_version": ALGORITHMS.packet_contract_version,
        "normalization_version": ALGORITHMS.normalization_version,
        "analysis_composition": composition.analysis_composition,
        "analysis_composition_sha256": composition.analysis_composition_sha256,
        "verify_composition": composition.verify_composition,
        "verify_composition_sha256": composition.verify_composition_sha256,
        "composition_sha256": composition.composition_sha256,
        "trials": request.eval_settings.trials,
        "eval_config": _eval_config(request.eval_settings),
    }


def _require_clean_run(problems: tuple[Any, ...], label: str) -> None:
    if problems:
        raise SemanticEvalError(
            f"{label}: {problems[0].stage}/{problems[0].code}: {problems[0].message}"
        )


def _analyze_unique_packets(
    *,
    packets: Mapping[str, tuple[ValidatedSemanticPacket, InferenceIdentity]],
    settings: ResolvedSemanticSettings,
    effective_epoch: str,
    cache_root: Path,
    adapter_factory: AdapterFactory,
    budget: ProviderCallBudget,
    deadline: float,
) -> tuple[dict[str, _AnalyzerObject], dict[str, int]]:
    objects: dict[str, _AnalyzerObject] = {}
    counters = {
        "primary_hits": 0,
        "primary_misses": 0,
        "primary_calls": 0,
        "replay_hits": 0,
        "replay_misses": 0,
        "replay_calls": 0,
    }
    for key, (packet, identity) in packets.items():
        primary = analyze_with_cache(
            packets=(packet,),
            cache_path=cache_root,
            cache_mode="read-write",
            result_reuse="exact-inference",
            provider_identity=settings.provider_identity,
            request_identity=settings.request_identity,
            adapter_factory=adapter_factory,
            search_epoch=effective_epoch,
            lock_wait_timeout_seconds=settings.lock_wait_timeout_seconds,
            runtime_deadline=deadline,
            provider_call_budget=budget,
            identities=(identity,),
        )
        _require_clean_run(primary.problems, f"analyzer primary {key}")
        if len(primary.results) != 1:
            raise SemanticEvalError(
                f"analyzer primary {key} produced no complete result"
            )
        replay = analyze_with_cache(
            packets=(packet,),
            cache_path=cache_root,
            cache_mode="require",
            result_reuse="exact-inference",
            provider_identity=settings.provider_identity,
            request_identity=settings.request_identity,
            adapter_factory=None,
            search_epoch=effective_epoch,
            lock_wait_timeout_seconds=settings.lock_wait_timeout_seconds,
            runtime_deadline=deadline,
            provider_call_budget=budget,
            identities=(identity,),
        )
        _require_clean_run(replay.problems, f"analyzer replay {key}")
        if primary.result_jsonl != replay.result_jsonl or replay.provider_calls:
            raise SemanticEvalError(
                f"analyzer replay {key} is not byte-identical zero-call"
            )
        result = primary.results[0]
        object_path = cache_root / "results" / f"{result['analysis_key']}.json"
        cache_object, cache_bytes = _cache_object(object_path)
        objects[key] = _AnalyzerObject(result, cache_object, cache_bytes)
        counters["primary_hits"] += primary.cache_hits
        counters["primary_misses"] += primary.cache_misses
        counters["primary_calls"] += primary.provider_calls
        counters["replay_hits"] += replay.cache_hits
        counters["replay_misses"] += replay.cache_misses
        counters["replay_calls"] += replay.provider_calls
    return objects, counters


def _verify_unique_work(
    *,
    work: Mapping[str, VerificationWork],
    settings: ResolvedVerificationSettings,
    cache_root: Path,
    adapter_factory: AdapterFactory,
    budget: ProviderCallBudget,
    deadline: float,
) -> tuple[dict[str, _VerifierObject], dict[str, int]]:
    objects: dict[str, _VerifierObject] = {}
    counters = {
        "primary_hits": 0,
        "primary_misses": 0,
        "primary_calls": 0,
        "replay_hits": 0,
        "replay_misses": 0,
        "replay_calls": 0,
    }
    for key, item in work.items():
        primary = verify_with_cache(
            work_items=(item,),
            cache_path=cache_root,
            cache_mode="read-write",
            provider_identity=settings.provider_identity,
            request_identity=settings.request_identity,
            adapter_factory=adapter_factory,
            lock_wait_timeout_seconds=settings.lock_wait_timeout_seconds,
            runtime_deadline=deadline,
            provider_call_budget=budget,
        )
        _require_clean_run(primary.problems, f"verifier primary {key}")
        if len(primary.results) != 1:
            raise SemanticEvalError(
                f"verifier primary {key} produced no complete result"
            )
        replay = verify_with_cache(
            work_items=(item,),
            cache_path=cache_root,
            cache_mode="require",
            provider_identity=settings.provider_identity,
            request_identity=settings.request_identity,
            adapter_factory=None,
            lock_wait_timeout_seconds=settings.lock_wait_timeout_seconds,
            runtime_deadline=deadline,
            provider_call_budget=budget,
        )
        _require_clean_run(replay.problems, f"verifier replay {key}")
        if replay.provider_calls or tuple(
            row.to_row() for row in primary.results
        ) != tuple(row.to_row() for row in replay.results):
            raise SemanticEvalError(
                f"verifier replay {key} is not byte-identical zero-call"
            )
        result = primary.results[0].to_row()
        object_path = cache_root / "verify-results" / f"{result['verify_key']}.json"
        cache_object, cache_bytes = _cache_object(object_path)
        objects[key] = _VerifierObject(
            primary.results[0], result, cache_object, cache_bytes
        )
        counters["primary_hits"] += primary.cache_hits
        counters["primary_misses"] += primary.cache_misses
        counters["primary_calls"] += primary.provider_calls
        counters["replay_hits"] += replay.cache_hits
        counters["replay_misses"] += replay.cache_misses
        counters["replay_calls"] += replay.provider_calls
    return objects, counters


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _analysis_attempt_row(
    *,
    trial_index: int,
    build: SemanticEvalVariantBuild,
    packet: ValidatedSemanticPacket,
    base_epoch: str,
    effective_epoch: str,
    item: _AnalyzerObject,
) -> dict[str, Any]:
    result_sha256 = _sha256(item.result)
    cache_sha256 = hashlib.sha256(item.cache_bytes).hexdigest()
    raw_sha256 = cast(str, item.cache_object["raw_response_sha256"])
    provenance = cast(dict[str, Any], item.cache_object["provenance"])
    return {
        "trial_index": trial_index,
        "case_id": build.observation.case_id,
        "variant_id": build.observation.variant_id,
        "packet_id": item.result["packet_id"],
        "packet_hash": item.result["packet_hash"],
        "base_search_epoch": base_epoch,
        "effective_search_epoch": effective_epoch,
        "analysis_key": item.result["analysis_key"],
        "primary_result": item.result,
        "replay_result": item.result,
        "primary_sha256": result_sha256,
        "replay_sha256": result_sha256,
        "primary_cache_object_sha256": cache_sha256,
        "replay_cache_object_sha256": cache_sha256,
        "primary_raw_response_sha256": raw_sha256,
        "replay_raw_response_sha256": raw_sha256,
        "primary_provenance": provenance,
        "replay_provenance": provenance,
    }


def _event_result_row(item: VerificationWork, value: _VerifierObject) -> dict[str, Any]:
    return {
        "verify_key": item.identity.verify_key,
        "base_search_epoch": item.base_search_epoch,
        "effective_search_epoch": item.effective_search_epoch,
        "result": value.result,
        "cache_object_sha256": hashlib.sha256(value.cache_bytes).hexdigest(),
        "raw_response_sha256": value.cache_object["raw_response_sha256"],
        "provenance": value.cache_object["provenance"],
    }


def _event_row(
    group: _FindingGroup,
    work_by_key: Mapping[str, VerificationWork],
    objects: Mapping[str, _VerifierObject],
    minimum_support_score: float,
) -> dict[str, Any]:
    ordered_work = [work_by_key[item.verify_key] for item in group.identities]
    results = [objects[item.identity.verify_key] for item in ordered_work]
    aggregate = aggregate_verification_results(
        group.packet,
        group.claim,
        group.request,
        required_epochs=[
            (item.base_search_epoch, item.effective_search_epoch)
            for item in ordered_work
        ],
        identities=group.identities,
        results=[item.canonical_result for item in results],
        minimum_support_score=minimum_support_score,
    )
    event_results = [
        _event_result_row(work, result)
        for work, result in zip(ordered_work, results, strict=True)
    ]
    side = {
        "present": True,
        "results": event_results,
        "aggregate_state": aggregate.aggregate_state,
        "context": aggregate.context,
    }
    comparison_side = {
        "present": True,
        "results": [
            {
                "verdict": result.result["verdict"],
                "support_score": result.result["support_score"],
                "evidence": result.result["evidence"],
            }
            for result in results
        ],
        "aggregate_state": aggregate.aggregate_state,
        "context": aggregate.context,
    }
    claim = group.claim.value
    comparison = {
        "case_id": group.case_id,
        "variant_id": group.variant_id,
        "packet_id": claim["packet_id"],
        "code": claim["code"],
        "classification": claim["classification"],
        "claim_hash": group.claim.claim_hash,
        "claim_evidence": claim["evidence"],
        "primary": comparison_side,
        "replay": comparison_side,
    }
    side_sha256 = _sha256(side)
    return {
        "trial_index": group.trial_index,
        "case_id": group.case_id,
        "variant_id": group.variant_id,
        "obligation_id": claim["obligation_id"],
        "packet_id": claim["packet_id"],
        "claim_hash": group.claim.claim_hash,
        "code": claim["code"],
        "classification": claim["classification"],
        "claim_evidence": claim["evidence"],
        "primary_present": True,
        "replay_present": True,
        "primary_results": event_results,
        "replay_results": event_results,
        "primary_aggregate_state": aggregate.aggregate_state,
        "primary_context": aggregate.context,
        "replay_aggregate_state": aggregate.aggregate_state,
        "replay_context": aggregate.context,
        "primary_sha256": side_sha256,
        "replay_sha256": side_sha256,
        "comparison_signature_sha256": _sha256(comparison),
    }


def _qualification(
    *,
    mode: str,
    metrics: dict[str, Any],
    by_code: tuple[dict[str, Any], ...],
    config: dict[str, Any],
) -> dict[str, Any]:
    field_by_check = {
        "minimum_positive_units": "positive_unit_count",
        "minimum_negative_units": "negative_unit_count",
        "minimum_evidence_sufficiency_rate": "evidence_sufficiency_rate",
        "minimum_conditional_precision": "conditional_precision",
        "minimum_conditional_recall": "conditional_recall",
        "minimum_end_to_end_recall": "end_to_end_recall",
        "minimum_recall_lower_bound": "recall_lower_bound",
        "maximum_false_positive_rate": "false_positive_rate",
        "maximum_false_positive_upper_bound": "false_positive_upper_bound",
        "maximum_indeterminate_rate": "indeterminate_rate",
        "maximum_uncached_flip_rate": "uncached_flip_rate",
    }
    checks: list[dict[str, Any]] = []
    failures: list[str] = []
    groups = [("", metrics)] + [
        (f"{item['code']}:", cast(dict[str, Any], item["metrics"])) for item in by_code
    ]
    for prefix, metric in groups:
        for name, field in field_by_check.items():
            observed = metric[field]
            comparator = ">=" if name.startswith("minimum") else "<="
            threshold = config[name]
            passed = observed is not None and (
                observed >= threshold if comparator == ">=" else observed <= threshold
            )
            check_name = prefix + name
            checks.append(
                {
                    "kind": "numeric",
                    "name": check_name,
                    "comparator": comparator,
                    "threshold": threshold,
                    "observed": observed,
                    "passed": passed,
                }
            )
            if not passed:
                failures.append(check_name)
        critical_passed = (
            not config["require_all_critical"] or metric["all_critical_passed"]
        )
        critical_name = prefix + "require_all_critical"
        checks.append(
            {
                "kind": "boolean",
                "name": critical_name,
                "comparator": "true",
                "threshold": True,
                "observed": metric["all_critical_passed"],
                "passed": critical_passed,
            }
        )
        if not critical_passed:
            failures.append(critical_name)
    return {
        "mode": mode,
        "positive_unit_count": metrics["positive_unit_count"],
        "negative_unit_count": metrics["negative_unit_count"],
        "checks": checks,
        "passed": not failures,
        "failure_reasons": failures,
    }


def _merge_counters(target: dict[str, int], source: Mapping[str, int]) -> None:
    for key, value in source.items():
        target[key] = target.get(key, 0) + value


def _assert_prompt_limits(
    packets: Mapping[str, tuple[ValidatedSemanticPacket, InferenceIdentity]],
    work: Mapping[str, VerificationWork],
    request: SemanticEvalRequest,
) -> None:
    if any(
        len(
            model_request_bytes(
                packet.to_dict(),
                instruction_bytes=identity.prompt_bytes,
            )
        )
        > request.settings.maximum_prompt_bytes
        for packet, identity in packets.values()
    ):
        raise SemanticEvalError(
            "analyzer evaluation prompt exceeds maximum_prompt_bytes"
        )
    if any(
        len(
            verifier_request_bytes(
                item.request, prompt_bytes=item.identity.prompt_bytes
            )
        )
        > request.verification_settings.maximum_prompt_bytes
        for item in work.values()
    ):
        raise SemanticEvalError(
            "verifier evaluation prompt exceeds maximum_prompt_bytes"
        )


def _assert_cost_ceiling(amount: int | None, maximum: int, *, lane: str) -> None:
    if maximum > 0 and amount is not None and amount > maximum:
        raise SemanticEvalError(
            f"{lane} evaluation estimated cost {amount} exceeds ceiling {maximum}"
        )


def _validate_corpus_external_path(
    corpus: SemanticEvalCorpus,
    path: Path,
    *,
    label: str,
) -> Path:
    resolved = path.resolve(strict=False)
    root = corpus.path.parent
    manifest = corpus.to_dict()
    inputs = {corpus.path.resolve()}
    fixture_roots: list[Path] = []
    for case in cast(list[dict[str, Any]], manifest["cases"]):
        fixtures = [case["clean"], *cast(list[dict[str, Any]], case["mutations"])]
        for fixture in fixtures:
            fixture_roots.append((root / fixture["fixture_path"]).resolve())
            inputs.add((root / fixture["tree_manifest_path"]).resolve())
    if resolved in inputs or any(
        resolved == fixture or resolved.is_relative_to(fixture)
        for fixture in fixture_roots
    ):
        raise SemanticEvalError(f"{label} overlaps a corpus input")
    return resolved


def _validate_output_path(corpus: SemanticEvalCorpus, output: Path) -> Path:
    resolved = _validate_corpus_external_path(
        corpus,
        output,
        label="evaluation output",
    )
    try:
        if output.is_symlink() or (output.exists() and not output.is_file()):
            raise SemanticEvalError(
                "evaluation output must be absent or a regular non-symlink file"
            )
    except OSError as exc:
        raise SemanticEvalError(f"cannot inspect evaluation output: {exc}") from exc
    return resolved


def run_semantic_eval(request: SemanticEvalRequest) -> SemanticEvalRun:  # noqa: C901 approved [SC-17.1] RUFF-SUP-090 exception
    """Run one cold-primary/cache-replay semantic qualification execution."""

    try:
        corpus = load_semantic_eval_corpus(
            request.manifest_path,
            mode=cast(Literal["report", "enforce"], request.eval_settings.mode),
        )
    except (OSError, SemanticEvalContractError) as exc:
        raise SemanticEvalError(str(exc)) from exc
    configured_hash = request.eval_settings.qualification_corpus_sha256
    configured_path = request.eval_settings.qualification_corpus.strip()
    if configured_path and Path(configured_path).resolve() != corpus.path:
        raise SemanticEvalError(
            "configured qualification corpus path does not match evaluated corpus"
        )
    if configured_hash and configured_hash != corpus.corpus_sha256:
        raise SemanticEvalError(
            "configured qualification corpus digest does not match validated corpus"
        )
    output_path = _validate_output_path(corpus, request.output_path)
    configured_report = request.eval_settings.qualification_report.strip()
    configured_report_path = (
        _validate_corpus_external_path(
            corpus,
            Path(configured_report),
            label="configured qualification report",
        )
        if configured_report
        else None
    )
    if configured_report_path == output_path:
        raise SemanticEvalError(
            "evaluation output overlaps configured qualification report"
        )

    cases = semantic_eval_case_rows(corpus)
    builds: list[SemanticEvalVariantBuild] = []
    with tempfile.TemporaryDirectory(prefix="backstitch-semantic-fixtures-") as raw:
        fixture_root = Path(raw)
        for case_id, variant_id in corpus.variant_keys:
            try:
                build = derive_semantic_eval_variant(
                    corpus,
                    cases[case_id],
                    variant_id,
                    fixture_root / case_id / variant_id,
                )
            except (OSError, SemanticEvalContractError, ValueError) as exc:
                raise SemanticEvalError(
                    f"cannot derive semantic fixture {case_id}/{variant_id}: {exc}"
                ) from exc
            if build.observation.deterministic_problem is not None:
                raise SemanticEvalError(
                    f"semantic fixture {case_id}/{variant_id} is not executable: "
                    f"{build.observation.deterministic_problem}"
                )
            builds.append(build)

        analysis_jobs: list[
            tuple[int, str, SemanticEvalVariantBuild, ValidatedSemanticPacket, str]
        ] = []
        unique_analysis: dict[
            str, tuple[ValidatedSemanticPacket, InferenceIdentity]
        ] = {}
        frozen_analysis_requests: dict[
            tuple[str, str],
            tuple[ValidatedSemanticPacket, InferenceIdentity],
        ] = {}
        for trial in range(request.eval_settings.trials):
            effective = derive_eval_search_epoch(
                "eval-analyze",
                request.settings.search_epoch,
                corpus.corpus_sha256,
                trial,
            )
            for build in builds:
                for packet in sorted(
                    build.packets,
                    key=lambda item: cast(str, item.to_dict()["packet_id"]),
                ):
                    packet_row = packet.to_dict()
                    request_key = (
                        cast(str, packet_row["packet_hash"]),
                        effective,
                    )
                    frozen = frozen_analysis_requests.get(request_key)
                    if frozen is None:
                        identity = build_inference_identity(
                            packet_row,
                            request.settings.provider_identity,
                            request.settings.request_identity,
                            search_epoch=effective,
                        )
                        frozen = (packet, identity)
                        frozen_analysis_requests[request_key] = frozen
                    identity = frozen[1]
                    unique_analysis.setdefault(identity.analysis_key, frozen)
                    analysis_jobs.append(
                        (trial, effective, build, packet, identity.analysis_key)
                    )
        _assert_prompt_limits(unique_analysis, {}, request)
        analysis_cost, analysis_rate_source = _analysis_cost(
            unique_analysis, request.settings
        )
        _assert_cost_ceiling(
            analysis_cost,
            request.settings.maximum_estimated_cost_microusd,
            lane="analyzer",
        )

        deadline = time.monotonic() + min(
            request.settings.maximum_runtime_seconds,
            request.verification_settings.maximum_runtime_seconds,
        )
        analyzer_budget = ProviderCallBudget(request.settings.maximum_provider_calls)
        verifier_budget = ProviderCallBudget(
            request.verification_settings.maximum_provider_calls
        )
        analyzer_factory = _shared_factory(request.adapter_factory)
        verifier_factory = _shared_factory(request.verification_adapter_factory)
        analyzer_counters: dict[str, int] = {}
        verifier_counters: dict[str, int] = {}
        analyzer_objects: dict[str, _AnalyzerObject] = {}
        finding_groups: list[_FindingGroup] = []
        all_work: dict[str, VerificationWork] = {}

        with tempfile.TemporaryDirectory(prefix="backstitch-semantic-caches-") as cache:
            cache_root = Path(cache)
            analyze_cache = cache_root / "analyze"
            verify_cache = cache_root / "verify"
            analyze_cache.mkdir()
            verify_cache.mkdir()
            if any(analyze_cache.iterdir()) or any(verify_cache.iterdir()):
                raise SemanticEvalError("evaluation cache roots are not empty")

            jobs_by_trial: dict[
                int,
                dict[
                    str,
                    tuple[ValidatedSemanticPacket, InferenceIdentity],
                ],
            ] = {}
            for trial, _effective, _build, _packet, key in analysis_jobs:
                jobs_by_trial.setdefault(trial, {}).setdefault(
                    key, unique_analysis[key]
                )
            for trial in range(request.eval_settings.trials):
                effective = derive_eval_search_epoch(
                    "eval-analyze",
                    request.settings.search_epoch,
                    corpus.corpus_sha256,
                    trial,
                )
                objects, counters = _analyze_unique_packets(
                    packets=jobs_by_trial.get(trial, {}),
                    settings=request.settings,
                    effective_epoch=effective,
                    cache_root=analyze_cache,
                    adapter_factory=analyzer_factory,
                    budget=analyzer_budget,
                    deadline=deadline,
                )
                analyzer_objects.update(objects)
                _merge_counters(analyzer_counters, counters)

            attempts: list[dict[str, Any]] = []
            for trial, effective, build, packet, analysis_key in analysis_jobs:
                item = analyzer_objects[analysis_key]
                attempts.append(
                    _analysis_attempt_row(
                        trial_index=trial,
                        build=build,
                        packet=packet,
                        base_epoch=request.settings.search_epoch,
                        effective_epoch=effective,
                        item=item,
                    )
                )
                if item.result["classification"] == "ok":
                    continue
                effective_verify = tuple(
                    derive_eval_search_epoch(
                        "eval-verify", base, corpus.corpus_sha256, trial
                    )
                    for base in request.verification_settings.search_epochs
                )
                trial_settings = replace(
                    request.verification_settings,
                    effective_search_epochs=effective_verify,
                )
                work, groups = build_verification_work(
                    (packet.to_dict(),), (item.result,), trial_settings
                )
                if len(groups) != 1:
                    raise SemanticEvalError(
                        "analyzer finding produced no verifier claim"
                    )
                finding_hash, packet_row, claim, verify_request, identities = groups[0]
                finding_groups.append(
                    _FindingGroup(
                        trial,
                        build.observation.case_id,
                        build.observation.variant_id,
                        cast(str, packet_row["obligation_id"]),
                        packet_row,
                        finding_hash,
                        claim,
                        verify_request,
                        identities,
                    )
                )
                for work_item in work:
                    all_work.setdefault(work_item.identity.verify_key, work_item)

            _assert_prompt_limits({}, all_work, request)
            verify_cost, verify_rate_source = _verification_cost(
                all_work, request.verification_settings
            )
            _assert_cost_ceiling(
                verify_cost,
                request.verification_settings.maximum_estimated_cost_microusd,
                lane="verifier",
            )
            verifier_objects, counters = _verify_unique_work(
                work=all_work,
                settings=request.verification_settings,
                cache_root=verify_cache,
                adapter_factory=verifier_factory,
                budget=verifier_budget,
                deadline=deadline,
            )
            _merge_counters(verifier_counters, counters)
            events = tuple(
                sorted(
                    (
                        _event_row(
                            group,
                            all_work,
                            verifier_objects,
                            request.verification_settings.minimum_support_score,
                        )
                        for group in finding_groups
                    ),
                    key=lambda item: (
                        item["trial_index"],
                        item["case_id"],
                        corpus.variant_keys.index(
                            (item["case_id"], item["variant_id"])
                        ),
                        item["packet_id"],
                        _CODE_ORDER[item["code"]],
                        item["classification"],
                        item["claim_hash"],
                    ),
                )
            )

        attempts.sort(
            key=lambda item: (
                item["trial_index"],
                corpus.variant_keys.index((item["case_id"], item["variant_id"])),
                item["packet_id"],
            )
        )
        report_identity = _identity(corpus, request)
        observed_facts = observed_semantic_eval_facts(tuple(builds))
        metrics, by_code_values = derive_semantic_eval_metrics(
            corpus=corpus,
            identity=report_identity,
            analysis_attempts=tuple(attempts),
            events=events,
            observed=observed_facts,
        )
        by_code = tuple(by_code_values)
        analysis_cost_record = {
            "estimated_cost_microusd": analysis_cost,
            "cost_rate_source": analysis_rate_source,
        }
        verify_cost_record = {
            "estimated_cost_microusd": verify_cost,
            "cost_rate_source": verify_rate_source,
        }
        total_cost = (
            None
            if analysis_cost is None or verify_cost is None
            else analysis_cost + verify_cost
        )
        operational = {
            "cache_hits": analyzer_counters.get("replay_hits", 0)
            + verifier_counters.get("replay_hits", 0),
            "cache_misses": analyzer_counters.get("primary_misses", 0)
            + verifier_counters.get("primary_misses", 0),
            "provider_calls": analyzer_counters.get("primary_calls", 0)
            + verifier_counters.get("primary_calls", 0),
            "analyzer_primary_cache_hits": analyzer_counters.get("primary_hits", 0),
            "analyzer_primary_cache_misses": analyzer_counters.get("primary_misses", 0),
            "analyzer_primary_provider_calls": analyzer_counters.get(
                "primary_calls", 0
            ),
            "analyzer_replay_cache_hits": analyzer_counters.get("replay_hits", 0),
            "analyzer_replay_cache_misses": analyzer_counters.get("replay_misses", 0),
            "analyzer_replay_provider_calls": analyzer_counters.get("replay_calls", 0),
            "verifier_primary_cache_hits": verifier_counters.get("primary_hits", 0),
            "verifier_primary_cache_misses": verifier_counters.get("primary_misses", 0),
            "verifier_primary_provider_calls": verifier_counters.get(
                "primary_calls", 0
            ),
            "verifier_replay_cache_hits": verifier_counters.get("replay_hits", 0),
            "verifier_replay_cache_misses": verifier_counters.get("replay_misses", 0),
            "verifier_replay_provider_calls": verifier_counters.get("replay_calls", 0),
            "analysis_cost": analysis_cost_record,
            "verify_cost": verify_cost_record,
            "total_estimated_cost_microusd": total_cost,
        }
        config = _eval_config(request.eval_settings)
        qualification = _qualification(
            mode=request.eval_settings.mode,
            metrics=metrics,
            by_code=by_code,
            config=config,
        )
        report = {
            "schema_version": 3,
            "artifact": "backstitch-verification-eval-report",
            "identity": report_identity,
            "analysis_attempts": attempts,
            "events": list(events),
            "metrics": metrics,
            "by_code": list(by_code),
            "operational": operational,
            "qualification": qualification,
        }
        try:
            validated = validate_semantic_eval_report_authoritatively(
                report,
                corpus=corpus,
                observed=observed_facts,
            )
            report_json = validated.to_json_bytes()
            atomic_replace_bytes(output_path, report_json)
        except (OSError, SemanticEvalContractError) as exc:
            raise SemanticEvalError(
                f"cannot publish semantic eval report: {exc}"
            ) from exc
        failed_enforce = (
            request.eval_settings.mode == "enforce" and not validated.passed
        )
        stderr = (
            tuple(
                f"semantic qualification failed: {name}"
                for name in qualification["failure_reasons"]
            )
            if failed_enforce
            else ()
        )
        return SemanticEvalRun(
            report=report,
            report_json=report_json,
            stderr_lines=stderr,
            exit_code=2 if failed_enforce else 0,
        )
