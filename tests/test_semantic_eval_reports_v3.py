"""Schema-3 semantic evaluation corpus and report contract tests.

Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-10.1]
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from backstitch.obligation_runtime import ALGORITHMS
from backstitch.semantic_eval_identity import derive_eval_search_epoch
from backstitch.semantic_eval_reports import (
    SemanticEvalContractError,
    SemanticEvalObservedFacts,
    SemanticEvalObservedVariantFacts,
    load_semantic_eval_corpus,
    load_semantic_eval_report,
    validate_semantic_eval_report_authoritatively,
)
from backstitch.semantic_identity import (
    ProviderIdentity,
    RequestIdentity,
    build_composition_identity,
)
from backstitch.semantic_packets import prompt_descriptor, semantic_packet_hash


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode()


def _prefixed_digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _receipt(
    *, path: str, locator: str, start_line: int, end_line: int, raw: bytes
) -> str:
    lines = raw.splitlines(keepends=True)
    span = b"".join(lines[start_line - 1 : end_line])
    value = {
        "receipt_version": 1,
        "path": path,
        "structural_locator": locator,
        "start_line": start_line,
        "end_line": end_line,
        "raw_sha256": hashlib.sha256(span).hexdigest(),
    }
    return hashlib.sha256(_canonical(value)).hexdigest()


def _candidate_id(*, kind: str, path: str, locator: str) -> str:
    value = {
        "candidate_identity_version": 1,
        "candidate_kind": kind,
        "path": path,
        "structural_locator": locator,
    }
    return "candidate:sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _deterministic_config() -> dict[str, Any]:
    return {
        "profile": {
            "spec_roots": ["docs/specs"],
            "plan_roots": ["docs/plans"],
            "code_roots": ["backstitch", "tests"],
            "test_roots": ["tests"],
            "planned_spec_globs": [],
            "exploratory_spec_globs": [],
            "meta_spec_globs": [],
        },
        "exclude_globs": [".git/**"],
        "obligations": {
            "section_required_roles": ["implementation"],
            "page_size": 5,
            "maximum_page_size": 100,
            "maximum_response_bytes": 65_536,
            "maximum_candidate_items": 2_000,
            "maximum_catalog_items": 100_000,
            "maximum_lexical_seeds": 100,
            "maximum_snapshot_files": 20_000,
            "maximum_file_bytes": 5_000_000,
            "maximum_snapshot_bytes": 100_000_000,
            "maximum_work_units": 2_000_000,
            "maximum_packet_bytes": 10_000_000,
            "maximum_packet_report_bytes": 10_000_000,
            "maximum_call_seconds": 10.0,
            "snapshot_capture_attempts": 3,
            "static_neighbor_depth": 1,
        },
    }


def _write_corpus(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    fixture = tmp_path / "fixture"
    source = fixture / "backstitch" / "feature.py"
    source.parent.mkdir(parents=True)
    raw = b"def enabled():\n    return True\n"
    source.write_bytes(raw)

    tree = {
        "schema_version": 1,
        "artifact": "backstitch-eval-fixture-tree",
        "files": [
            {
                "path": "backstitch/feature.py",
                "raw_sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
                "byte_count": len(raw),
                "executable": False,
            }
        ],
    }
    tree_path = tmp_path / "tree.json"
    tree_path.write_bytes(_canonical(tree))

    obligation_id = "docs/specs/01-feature.md#FEATURE-1"
    evidence_locator = "source-declaration:code_backlink:1:0"
    candidate_locator = "python-definition:enabled:function:0"
    evidence_receipt = _receipt(
        path="backstitch/feature.py",
        locator=evidence_locator,
        start_line=1,
        end_line=1,
        raw=raw,
    )
    candidate_receipt = _receipt(
        path="backstitch/feature.py",
        locator=candidate_locator,
        start_line=1,
        end_line=2,
        raw=raw,
    )
    manifest = {
        "schema_version": 3,
        "corpus_id": "minimal-report-corpus",
        "reviewed_historical_units": [],
        "critical_case_ids": [],
        "critical_vacuous_trace_case_ids": [],
        "cases": [
            {
                "case_id": "case-1",
                "deterministic_config": _deterministic_config(),
                "clean": {
                    "variant_id": "clean",
                    "fixture_path": "fixture",
                    "tree_manifest_path": "tree.json",
                    "tree_manifest_sha256": _prefixed_digest(tree),
                    "transform": None,
                    "control_tags": [],
                },
                "mutations": [],
                "gold_obligations": [
                    {
                        "gold_id": "obligation-1",
                        "variant_id": "clean",
                        "obligation_id": obligation_id,
                        "packet_id": obligation_id,
                        "intent_state": "identified",
                        "alignment_state": "complete",
                        "disposition": "evaluate",
                        "obligation_rung": "active",
                        "gate_state": "executable",
                    }
                ],
                "gold_evidence": [
                    {
                        "gold_id": "evidence-1",
                        "variant_id": "clean",
                        "obligation_id": obligation_id,
                        "source_role": "implementation",
                        "path": "backstitch/feature.py",
                        "structural_locator": evidence_locator,
                        "start_line": 1,
                        "end_line": 1,
                        "receipt_hash": evidence_receipt,
                        "reciprocity_state": "complete",
                    }
                ],
                "gold_candidates": [
                    {
                        "gold_id": "candidate-1",
                        "variant_id": "clean",
                        "obligation_id": obligation_id,
                        "candidate_id": _candidate_id(
                            kind="implementation_definition",
                            path="backstitch/feature.py",
                            locator=candidate_locator,
                        ),
                        "candidate_kind": "implementation_definition",
                        "path": "backstitch/feature.py",
                        "structural_locator": candidate_locator,
                        "start_line": 1,
                        "end_line": 2,
                        "receipt_hash": candidate_receipt,
                        "trace_state": "declared",
                    }
                ],
                "expected_findings": [
                    {
                        "gold_id": "finding-1",
                        "variant_id": "clean",
                        "packet_id": obligation_id,
                        "code": "SEMANTIC_CONFIRMED_MISMATCH",
                        "classification": "confirmed_mismatch",
                        "required_declared_evidence_gold_ids": ["evidence-1"],
                        "required_counterevidence_gold_ids": [],
                    }
                ],
                "critical": False,
            }
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_bytes(_canonical(manifest) + b"\n")
    return manifest_path, manifest


def _observed_packet(manifest: dict[str, Any]) -> dict[str, Any]:
    case = manifest["cases"][0]
    obligation = case["gold_obligations"][0]
    evidence = case["gold_evidence"][0]
    declared_source = {
        "source_role": evidence["source_role"],
        "receipt_hash": evidence["receipt_hash"],
        "relation_kinds": ["spec_mapping", "code_backlink"],
        "reciprocity_state": evidence["reciprocity_state"],
    }
    packet: dict[str, Any] = {
        "schema_version": 3,
        "packet_id": obligation["packet_id"],
        "packet_hash": "",
        "kind": "section",
        "obligation_id": obligation["obligation_id"],
        "source_snapshot": {
            "snapshot_hash": "1" * 64,
            "obligation_state_hash": "",
            "derivation_config_hash": "3" * 64,
        },
        "readiness": {
            "intent_state": "identified",
            "alignment_state": "complete",
            "disposition": "evaluate",
            "obligation_rung": "active",
            "gate_state": "executable",
            "required_roles": ["implementation"],
        },
        "requirement": {
            "role": "requirement",
            "path": "docs/specs/01-feature.md",
            "identity": "FEATURE-1",
            "title": "Feature",
            "start_line": 1,
            "end_line": 1,
            "text": "Feature must be enabled.",
        },
        "declared_evidence": [
            {
                "role": "implementation",
                "path": "backstitch/feature.py",
                "symbol": "enabled",
                "start_line": 1,
                "end_line": 2,
                "snippet": "def enabled():\n    return True",
                "sources": [declared_source],
            }
        ],
        "counterevidence": [],
        "trace_summary": {
            "declared_counts": [
                {
                    "source_role": "implementation",
                    "total": 1,
                    "complete": 1,
                    "one_sided": 0,
                },
                {
                    "source_role": "test",
                    "total": 0,
                    "complete": 0,
                    "one_sided": 0,
                },
                {
                    "source_role": "binding_test",
                    "total": 0,
                    "complete": 0,
                    "one_sided": 0,
                },
            ],
            "candidate_counts": [
                {
                    "candidate_kind": kind,
                    "declared": 1 if kind == "implementation_definition" else 0,
                    "partially_declared": 0,
                    "untraced": 0,
                    "conflicted": 0,
                }
                for kind in (
                    "implementation_definition",
                    "test_definition",
                    "static_reference",
                    "unresolved_reference",
                    "report_issue",
                )
            ],
            "relation_counts": [
                {
                    "relation_kind": relation,
                    "count": 1 if relation in {"spec_mapping", "code_backlink"} else 0,
                }
                for relation in (
                    "spec_mapping",
                    "code_backlink",
                    "invariant_declaration",
                    "invariant_bind",
                    "binding_test",
                    "static_import",
                    "static_call",
                    "static_reference",
                    "enclosing_definition",
                    "issue_target",
                )
            ],
        },
        "evidence_regions": [
            {
                "role": "requirement",
                "path": "docs/specs/01-feature.md",
                "start_line": 1,
                "end_line": 1,
            },
            {
                "role": "implementation",
                "path": "backstitch/feature.py",
                "start_line": 1,
                "end_line": 2,
            },
        ],
        "issues": [],
        "packet_warnings": [],
    }
    state = {
        "obligation_state_version": 1,
        "obligation_id": packet["obligation_id"],
        "kind": "section",
        "obligation_rung": "active",
        "intent_state": "identified",
        "alignment_state": "complete",
        "disposition": "evaluate",
        "gate_state": "executable",
        "required_roles": ["implementation"],
        "declared_sources": [declared_source],
    }
    packet["source_snapshot"]["obligation_state_hash"] = hashlib.sha256(
        _canonical(state)
    ).hexdigest()
    packet["packet_hash"] = semantic_packet_hash(packet)
    return packet


def _observed_facts(
    manifest: dict[str, Any], packet: dict[str, Any]
) -> SemanticEvalObservedFacts:
    case = manifest["cases"][0]

    def projection(field_name: str) -> tuple[dict[str, Any], ...]:
        return tuple(
            {
                key: value
                for key, value in item.items()
                if key not in {"gold_id", "variant_id"}
            }
            for item in case[field_name]
        )

    return SemanticEvalObservedFacts(
        variants=(
            SemanticEvalObservedVariantFacts(
                case_id=case["case_id"],
                variant_id="clean",
                obligations=projection("gold_obligations"),
                evidence=projection("gold_evidence"),
                candidates=projection("gold_candidates"),
                packets=(packet,),
            ),
        )
    )


def test_load_schema3_corpus_validates_canonical_manifest_and_tree(
    tmp_path: Path,
) -> None:
    manifest_path, manifest = _write_corpus(tmp_path)

    corpus = load_semantic_eval_corpus(manifest_path, mode="report")

    assert corpus.corpus_id == "minimal-report-corpus"
    assert corpus.corpus_sha256 == _prefixed_digest(manifest)
    assert corpus.case_ids == ("case-1",)
    assert corpus.variant_keys == (("case-1", "clean"),)
    assert corpus.fixture_files("case-1", "clean") == ("backstitch/feature.py",)


def test_fixture_materializes_validated_bytes_and_executable_bits(
    tmp_path: Path,
) -> None:
    manifest_path, manifest = _write_corpus(tmp_path)
    source = tmp_path / "fixture/backstitch/feature.py"
    source.chmod(0o755)
    tree_path = tmp_path / "tree.json"
    tree = json.loads(tree_path.read_bytes())
    tree["files"][0]["executable"] = True
    tree_path.write_bytes(_canonical(tree))
    manifest["cases"][0]["clean"]["tree_manifest_sha256"] = _prefixed_digest(tree)
    manifest_path.write_bytes(_canonical(manifest) + b"\n")
    corpus = load_semantic_eval_corpus(manifest_path, mode="report")

    destination = tmp_path / "materialized"
    corpus.fixture("case-1", "clean").materialize(destination)

    output = destination / "backstitch/feature.py"
    assert output.read_bytes() == source.read_bytes()
    assert output.stat().st_mode & 0o100


def test_manifest_rejects_noncanonical_bytes(tmp_path: Path) -> None:
    manifest_path, manifest = _write_corpus(tmp_path)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    with pytest.raises(SemanticEvalContractError, match="canonical JSON"):
        load_semantic_eval_corpus(manifest_path, mode="report")


def test_corpus_loader_preserves_validation_phase_error_priority(
    tmp_path: Path,
) -> None:
    manifest_path, manifest = _write_corpus(tmp_path / "schema")
    manifest["schema_version"] = 2
    manifest["cases"] = "invalid after schema"
    manifest_path.write_bytes(_canonical(manifest) + b"\n")
    with pytest.raises(SemanticEvalContractError) as schema_error:
        load_semantic_eval_corpus(manifest_path, mode="report")
    assert str(schema_error.value) == "semantic eval corpus schema_version must be 3"

    manifest_path, manifest = _write_corpus(tmp_path / "fixture")
    manifest["cases"][0]["clean"]["variant_id"] = "not-clean"
    manifest["cases"][0]["clean"]["tree_manifest_sha256"] = "sha256:" + "0" * 64
    manifest_path.write_bytes(_canonical(manifest) + b"\n")
    with pytest.raises(SemanticEvalContractError) as fixture_error:
        load_semantic_eval_corpus(manifest_path, mode="report")
    assert str(fixture_error.value) == (
        "cases[0].clean identity or transform is invalid"
    )

    manifest_path, manifest = _write_corpus(tmp_path / "critical")
    manifest["cases"][0]["critical"] = True
    manifest["cases"][0]["gold_obligations"][0]["variant_id"] = "unknown"
    manifest_path.write_bytes(_canonical(manifest) + b"\n")
    with pytest.raises(SemanticEvalContractError) as critical_error:
        load_semantic_eval_corpus(manifest_path, mode="report")
    assert str(critical_error.value) == (
        "critical_case_ids does not match critical cases"
    )

    manifest_path, manifest = _write_corpus(tmp_path / "gold")
    manifest["cases"][0]["gold_obligations"][0]["variant_id"] = "unknown"
    manifest["reviewed_historical_units"] = [{}]
    manifest_path.write_bytes(_canonical(manifest) + b"\n")
    with pytest.raises(SemanticEvalContractError) as gold_error:
        load_semantic_eval_corpus(manifest_path, mode="report")
    assert str(gold_error.value) == ("cases[0].gold_obligations[0] has unknown variant")


def _provenance() -> dict[str, Any]:
    return {
        "adapter_id": "tests.adapter",
        "adapter_version": 1,
        "plugin_version": "1",
        "model_class": "tests.Model",
        "provider_model_id": "model",
        "provider_model_revision": "revision",
        "response_id": "response",
        "input_tokens": 10,
        "output_tokens": 2,
    }


def _provider() -> ProviderIdentity:
    return ProviderIdentity(
        backend_id="llm",
        plugin_id="tests",
        model_id="model",
        model_revision="revision",
        adapter_id="tests.adapter",
        adapter_version=1,
        llm_distribution_version="1",
        plugin_distribution_name="tests-provider",
        plugin_distribution_version="1",
    )


def _eval_config(*, trials: int = 2) -> dict[str, Any]:
    return {
        "trials": trials,
        "interval_method": "wilson",
        "confidence_level": 0.95,
        "minimum_positive_units": 0,
        "minimum_negative_units": 0,
        "minimum_evidence_sufficiency_rate": 0.0,
        "minimum_conditional_precision": 0.0,
        "minimum_conditional_recall": 0.0,
        "minimum_end_to_end_recall": 0.0,
        "minimum_recall_lower_bound": 0.0,
        "maximum_false_positive_rate": 1.0,
        "maximum_false_positive_upper_bound": 1.0,
        "maximum_indeterminate_rate": 1.0,
        "maximum_uncached_flip_rate": 1.0,
        "require_all_critical": False,
    }


def _analysis_attempt(
    *,
    trial: int,
    corpus_sha256: str,
    packet_id: str,
    packet_hash: str,
    composition: dict[str, Any],
    classification: str = "ok",
    evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    base_epoch = composition["base_search_epoch"]
    effective = derive_eval_search_epoch(
        "eval-analyze", base_epoch, corpus_sha256, trial
    )
    contract = {
        "analysis_contract_version": composition["analysis_contract_version"],
        "packet_hash": packet_hash,
        "prompt": asdict(prompt_descriptor("section")),
        "provider": composition["provider"],
        "request": composition["request"],
        "search_epoch": effective,
    }
    analysis_key = hashlib.sha256(_canonical(contract)).hexdigest()
    result_evidence = [] if evidence is None else evidence
    result = {
        "schema_version": 2,
        "packet_id": packet_id,
        "kind": "section",
        "packet_hash": packet_hash,
        "analysis_key": analysis_key,
        "classification": classification,
        "confidence": 1.0,
        "rationale": "controlled",
        "summary": "No mismatch" if classification == "ok" else "Behavior differs",
        "evidence": result_evidence,
        "verification_state": "evidence_bound",
    }
    raw_response_sha256 = hashlib.sha256(b"controlled raw response").hexdigest()
    cache = {
        "schema_version": 1,
        "object_type": "semantic-result",
        "inference_contract": contract,
        "analysis_key": analysis_key,
        "result": result,
        "provenance": _provenance(),
        "raw_response_sha256": raw_response_sha256,
    }
    result_sha256 = hashlib.sha256(_canonical(result)).hexdigest()
    cache_sha256 = hashlib.sha256(_canonical(cache)).hexdigest()
    return {
        "trial_index": trial,
        "case_id": "case-1",
        "variant_id": "clean",
        "packet_id": packet_id,
        "packet_hash": packet_hash,
        "base_search_epoch": base_epoch,
        "effective_search_epoch": effective,
        "analysis_key": analysis_key,
        "primary_result": result,
        "replay_result": result,
        "primary_sha256": result_sha256,
        "replay_sha256": result_sha256,
        "primary_cache_object_sha256": cache_sha256,
        "replay_cache_object_sha256": cache_sha256,
        "primary_raw_response_sha256": raw_response_sha256,
        "replay_raw_response_sha256": raw_response_sha256,
        "primary_provenance": _provenance(),
        "replay_provenance": _provenance(),
    }


def _negative_report(corpus_sha256: str, packet_id: str) -> dict[str, Any]:
    provider = _provider()
    request = RequestIdentity("require", 0.0, 42, 512, "max")
    composition_identity = build_composition_identity(
        provider,
        request,
        analysis_search_epoch="analysis-base",
        verify_provider=provider,
        verify_request=request,
        verify_search_epochs=("verify-base",),
        required_verdicts=1,
        minimum_support_score=0.9,
        indeterminate="report",
    )
    analysis_composition = composition_identity.analysis_composition
    verify_composition = composition_identity.verify_composition
    packet_hash = "1" * 64
    attempts = [
        _analysis_attempt(
            trial=trial,
            corpus_sha256=corpus_sha256,
            packet_id=packet_id,
            packet_hash=packet_hash,
            composition=analysis_composition,
        )
        for trial in range(2)
    ]
    metrics = {
        "positive_unit_count": 0,
        "negative_unit_count": 1,
        "evidence_sufficiency_rate": None,
        "conditional_precision": None,
        "conditional_recall": None,
        "end_to_end_recall": None,
        "recall_lower_bound": None,
        "false_positive_rate": 0.0,
        "false_positive_upper_bound": 0.7934506856227624,
        "indeterminate_rate": None,
        "uncached_flip_rate": None,
        "false_positive_count": 0,
        "all_critical_passed": True,
    }
    config = _eval_config()
    checks: list[dict[str, Any]] = []
    names = (
        "minimum_positive_units",
        "minimum_negative_units",
        "minimum_evidence_sufficiency_rate",
        "minimum_conditional_precision",
        "minimum_conditional_recall",
        "minimum_end_to_end_recall",
        "minimum_recall_lower_bound",
        "maximum_false_positive_rate",
        "maximum_false_positive_upper_bound",
        "maximum_indeterminate_rate",
        "maximum_uncached_flip_rate",
    )
    observed = (
        0,
        1,
        None,
        None,
        None,
        None,
        None,
        0.0,
        0.7934506856227624,
        None,
        None,
    )
    failures: list[str] = []
    for name, value in zip(names, observed, strict=True):
        comparator = ">=" if name.startswith("minimum") else "<="
        threshold = config[name]
        passed = value is not None and (
            value >= threshold if comparator == ">=" else value <= threshold
        )
        checks.append(
            {
                "kind": "numeric",
                "name": name,
                "comparator": comparator,
                "threshold": threshold,
                "observed": value,
                "passed": passed,
            }
        )
        if not passed:
            failures.append(name)
    checks.append(
        {
            "kind": "boolean",
            "name": "require_all_critical",
            "comparator": "true",
            "threshold": True,
            "observed": True,
            "passed": True,
        }
    )
    return {
        "schema_version": 3,
        "artifact": "backstitch-verification-eval-report",
        "identity": {
            "corpus_sha256": corpus_sha256,
            "snapshot_algorithm_version": 1,
            "obligation_algorithm_version": 1,
            "discovery_algorithm_version": ALGORITHMS.discovery_algorithm_version,
            "packet_contract_version": 3,
            "normalization_version": 1,
            "analysis_composition": analysis_composition,
            "analysis_composition_sha256": composition_identity.analysis_composition_sha256,
            "verify_composition": verify_composition,
            "verify_composition_sha256": composition_identity.verify_composition_sha256,
            "composition_sha256": composition_identity.composition_sha256,
            "trials": 2,
            "eval_config": config,
        },
        "analysis_attempts": attempts,
        "events": [],
        "metrics": metrics,
        "by_code": [],
        "operational": {
            "cache_hits": 2,
            "cache_misses": 2,
            "provider_calls": 2,
            "analyzer_primary_cache_hits": 0,
            "analyzer_primary_cache_misses": 2,
            "analyzer_primary_provider_calls": 2,
            "analyzer_replay_cache_hits": 2,
            "analyzer_replay_cache_misses": 0,
            "analyzer_replay_provider_calls": 0,
            "verifier_primary_cache_hits": 0,
            "verifier_primary_cache_misses": 0,
            "verifier_primary_provider_calls": 0,
            "verifier_replay_cache_hits": 0,
            "verifier_replay_cache_misses": 0,
            "verifier_replay_provider_calls": 0,
            "analysis_cost": {
                "estimated_cost_microusd": None,
                "cost_rate_source": None,
            },
            "verify_cost": {
                "estimated_cost_microusd": 0,
                "cost_rate_source": None,
            },
            "total_estimated_cost_microusd": None,
        },
        "qualification": {
            "mode": "report",
            "positive_unit_count": 0,
            "negative_unit_count": 1,
            "checks": checks,
            "passed": False,
            "failure_reasons": failures,
        },
    }


def _event(
    *,
    trial: int,
    corpus_sha256: str,
    obligation_id: str,
    attempt: dict[str, Any],
    verify_composition: dict[str, Any],
    verifier_packet_hash: str = "2" * 64,
) -> dict[str, Any]:
    analyzer_result = attempt["primary_result"]
    code = "SEMANTIC_CONFIRMED_MISMATCH"
    claim_evidence = [
        {
            key: item[key]
            for key in (
                "role",
                "path",
                "start_line",
                "end_line",
                "excerpt_sha256",
            )
        }
        for item in analyzer_result["evidence"]
    ]
    claim = {
        "packet_id": attempt["packet_id"],
        "packet_hash": attempt["packet_hash"],
        "obligation_id": obligation_id,
        "kind": analyzer_result["kind"],
        "code": code,
        "classification": analyzer_result["classification"],
        "statement": analyzer_result["summary"],
        "evidence": claim_evidence,
    }
    claim_hash = hashlib.sha256(_canonical(claim)).hexdigest()
    base = verify_composition["search_epochs"][0]
    effective = derive_eval_search_epoch("eval-verify", base, corpus_sha256, trial)
    contract = {
        "verify_contract_version": verify_composition["verify_contract_version"],
        "verifier_packet_hash": verifier_packet_hash,
        "claim_hash": claim_hash,
        "prompt": verify_composition["prompt"],
        "provider": verify_composition["provider"],
        "request": verify_composition["request"],
        "base_search_epoch": base,
        "effective_search_epoch": effective,
    }
    verify_key = hashlib.sha256(_canonical(contract)).hexdigest()
    result = {
        "schema_version": 1,
        "packet_id": attempt["packet_id"],
        "packet_hash": attempt["packet_hash"],
        "claim_hash": claim_hash,
        "verifier_packet_hash": verifier_packet_hash,
        "verify_key": verify_key,
        "verdict": "support",
        "support_score": 1.0,
        "summary": "Claim survived falsification",
        "evidence": analyzer_result["evidence"],
    }
    raw_hash = hashlib.sha256(b"verification raw response").hexdigest()
    cache = {
        "schema_version": 1,
        "object_type": "verification-result",
        "inference_contract": contract,
        "verify_key": verify_key,
        "result": result,
        "provenance": _provenance(),
        "raw_response_sha256": raw_hash,
    }
    event_result = {
        "verify_key": verify_key,
        "base_search_epoch": base,
        "effective_search_epoch": effective,
        "result": result,
        "cache_object_sha256": hashlib.sha256(_canonical(cache)).hexdigest(),
        "raw_response_sha256": raw_hash,
        "provenance": _provenance(),
    }
    side = {
        "present": True,
        "results": [event_result],
        "aggregate_state": "independently_verified",
        "context": "independently_verified",
    }
    side_hash = hashlib.sha256(_canonical(side)).hexdigest()
    comparison_side = {
        "present": True,
        "results": [
            {
                "verdict": "support",
                "support_score": 1.0,
                "evidence": analyzer_result["evidence"],
            }
        ],
        "aggregate_state": "independently_verified",
        "context": "independently_verified",
    }
    comparison = {
        "case_id": "case-1",
        "variant_id": "clean",
        "packet_id": attempt["packet_id"],
        "code": code,
        "classification": "confirmed_mismatch",
        "claim_hash": claim_hash,
        "claim_evidence": claim_evidence,
        "primary": comparison_side,
        "replay": comparison_side,
    }
    return {
        "trial_index": trial,
        "case_id": "case-1",
        "variant_id": "clean",
        "obligation_id": obligation_id,
        "packet_id": attempt["packet_id"],
        "claim_hash": claim_hash,
        "code": code,
        "classification": "confirmed_mismatch",
        "claim_evidence": claim_evidence,
        "primary_present": True,
        "replay_present": True,
        "primary_results": [event_result],
        "replay_results": [event_result],
        "primary_aggregate_state": "independently_verified",
        "primary_context": "independently_verified",
        "replay_aggregate_state": "independently_verified",
        "replay_context": "independently_verified",
        "primary_sha256": side_hash,
        "replay_sha256": side_hash,
        "comparison_signature_sha256": hashlib.sha256(
            _canonical(comparison)
        ).hexdigest(),
    }


def _replace_qualification(report: dict[str, Any]) -> None:
    metrics = report["metrics"]
    by_code = tuple((row["code"], row["metrics"]) for row in report["by_code"])
    config = report["identity"]["eval_config"]
    checks: list[dict[str, Any]] = []
    failures: list[str] = []
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
    groups = [("", metrics), *[(f"{code}:", row) for code, row in by_code]]
    for prefix, row in groups:
        for name, field_name in field_by_check.items():
            observed = row[field_name]
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
            not config["require_all_critical"] or row["all_critical_passed"]
        )
        critical_name = prefix + "require_all_critical"
        checks.append(
            {
                "kind": "boolean",
                "name": critical_name,
                "comparator": "true",
                "threshold": True,
                "observed": row["all_critical_passed"],
                "passed": critical_passed,
            }
        )
        if not critical_passed:
            failures.append(critical_name)
    report["qualification"] = {
        "mode": "report",
        "positive_unit_count": metrics["positive_unit_count"],
        "negative_unit_count": metrics["negative_unit_count"],
        "checks": checks,
        "passed": not failures,
        "failure_reasons": failures,
    }


def _positive_report(
    corpus_sha256: str,
    packet_id: str,
    *,
    packet: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report = _negative_report(corpus_sha256, packet_id)
    evidence = [
        {
            "role": "implementation",
            "path": "backstitch/feature.py",
            "start_line": 1,
            "end_line": 2,
            "excerpt": "def enabled():\n    return True",
            "excerpt_sha256": hashlib.sha256(
                b"def enabled():\n    return True"
            ).hexdigest(),
        },
        {
            "role": "requirement",
            "path": "docs/specs/01-feature.md",
            "start_line": 1,
            "end_line": 1,
            "excerpt": "Feature must be enabled.",
            "excerpt_sha256": hashlib.sha256(b"Feature must be enabled.").hexdigest(),
        },
    ]
    composition = report["identity"]["analysis_composition"]
    attempts = [
        _analysis_attempt(
            trial=trial,
            corpus_sha256=corpus_sha256,
            packet_id=packet_id,
            packet_hash=("1" * 64 if packet is None else packet["packet_hash"]),
            composition=composition,
            classification="confirmed_mismatch",
            evidence=evidence,
        )
        for trial in range(2)
    ]
    report["analysis_attempts"] = attempts
    events: list[dict[str, Any]] = []
    for trial in range(2):
        verifier_packet_hash = "2" * 64
        if packet is not None:
            from backstitch.semantic_verification import (
                build_verification_request,
                derive_verification_claim,
            )

            claim = derive_verification_claim(packet, attempts[trial]["primary_result"])
            verifier_packet_hash = build_verification_request(
                packet, claim
            ).verifier_packet_hash
        events.append(
            _event(
                trial=trial,
                corpus_sha256=corpus_sha256,
                obligation_id=packet_id,
                attempt=attempts[trial],
                verify_composition=report["identity"]["verify_composition"],
                verifier_packet_hash=verifier_packet_hash,
            )
        )
    report["events"] = events
    metrics = {
        "positive_unit_count": 1,
        "negative_unit_count": 0,
        "evidence_sufficiency_rate": 1.0,
        "conditional_precision": 1.0,
        "conditional_recall": 1.0,
        "end_to_end_recall": 1.0,
        "recall_lower_bound": 0.20654931437723753,
        "false_positive_rate": None,
        "false_positive_upper_bound": None,
        "indeterminate_rate": 0.0,
        "uncached_flip_rate": 0.0,
        "false_positive_count": 0,
        "all_critical_passed": True,
    }
    report["metrics"] = metrics
    report["by_code"] = [{"code": "SEMANTIC_CONFIRMED_MISMATCH", "metrics": metrics}]
    report["operational"] = {
        **report["operational"],
        "cache_hits": 4,
        "cache_misses": 4,
        "provider_calls": 4,
        "verifier_primary_cache_misses": 2,
        "verifier_primary_provider_calls": 2,
        "verifier_replay_cache_hits": 2,
        "verify_cost": {
            "estimated_cost_microusd": None,
            "cost_rate_source": None,
        },
    }
    _replace_qualification(report)
    return report


def test_load_schema3_report_recomputes_local_identity_cache_and_metrics(
    tmp_path: Path,
) -> None:
    manifest_path, manifest = _write_corpus(tmp_path)
    manifest["cases"][0]["expected_findings"] = []
    manifest_path.write_bytes(_canonical(manifest) + b"\n")
    corpus = load_semantic_eval_corpus(manifest_path, mode="report")
    packet_id = manifest["cases"][0]["gold_obligations"][0]["packet_id"]
    report_value = _negative_report(corpus.corpus_sha256, packet_id)
    report_path = tmp_path / "report.json"
    report_path.write_bytes(_canonical(report_value) + b"\n")

    report = load_semantic_eval_report(report_path, corpus=corpus)

    assert report.report_sha256 == _prefixed_digest(report_value)
    assert report.passed is False
    assert (
        report.identity["composition_sha256"]
        == report_value["identity"]["composition_sha256"]
    )


def test_load_schema3_report_recomputes_events_and_by_code_metrics(
    tmp_path: Path,
) -> None:
    manifest_path, _manifest = _write_corpus(tmp_path)
    corpus = load_semantic_eval_corpus(manifest_path, mode="report")
    packet_id = corpus.to_dict()["cases"][0]["gold_obligations"][0]["packet_id"]
    report_value = _positive_report(corpus.corpus_sha256, packet_id)
    report_path = tmp_path / "report.json"
    report_path.write_bytes(_canonical(report_value) + b"\n")

    report = load_semantic_eval_report(report_path, corpus=corpus)

    assert report.report_sha256 == _prefixed_digest(report_value)
    assert report.to_dict()["events"][0]["primary_context"] == (
        "independently_verified"
    )
    assert report.to_dict()["by_code"][0]["code"] == ("SEMANTIC_CONFIRMED_MISMATCH")


def test_schema3_report_loader_applies_byte_ceiling_before_json_parsing(
    tmp_path: Path,
) -> None:
    manifest_path, _manifest = _write_corpus(tmp_path)
    corpus = load_semantic_eval_corpus(manifest_path, mode="report")
    report_path = tmp_path / "oversized-report.json"
    report_path.write_bytes(b"{" * 65)

    with pytest.raises(SemanticEvalContractError, match="bounded read"):
        load_semantic_eval_report(report_path, corpus=corpus, maximum_bytes=64)


def test_authoritative_validation_uses_separate_source_facts_for_metrics(
    tmp_path: Path,
) -> None:
    manifest_path, manifest = _write_corpus(tmp_path)
    corpus = load_semantic_eval_corpus(manifest_path, mode="report")
    packet = _observed_packet(manifest)
    packet_id = packet["packet_id"]
    report_value = _positive_report(corpus.corpus_sha256, packet_id, packet=packet)
    observed = _observed_facts(manifest, packet)

    validated = validate_semantic_eval_report_authoritatively(
        report_value, corpus=corpus, observed=observed
    )

    assert validated.to_dict()["metrics"]["end_to_end_recall"] == 1.0
    assert observed.variants[0].candidates[0]["trace_state"] == "declared"
    assert packet["counterevidence"] == []

    variant = observed.variants[0]
    contradictory = SemanticEvalObservedFacts(
        variants=(
            SemanticEvalObservedVariantFacts(
                case_id=variant.case_id,
                variant_id=variant.variant_id,
                obligations=variant.obligations,
                evidence=(),
                candidates=variant.candidates,
                packets=variant.packets,
            ),
        )
    )
    with pytest.raises(
        SemanticEvalContractError,
        match="metrics do not recompute from observed source facts",
    ):
        validate_semantic_eval_report_authoritatively(
            report_value, corpus=corpus, observed=contradictory
        )


@pytest.mark.parametrize("lane", ("analyze", "verify"))
def test_authoritative_validation_recomputes_effective_search_epoch(
    tmp_path: Path,
    lane: str,
) -> None:
    manifest_path, manifest = _write_corpus(tmp_path)
    corpus = load_semantic_eval_corpus(manifest_path, mode="report")
    packet = _observed_packet(manifest)
    report_value = _positive_report(
        corpus.corpus_sha256,
        packet["packet_id"],
        packet=packet,
    )
    observed = _observed_facts(manifest, packet)

    if lane == "analyze":
        report_value["analysis_attempts"][0]["effective_search_epoch"] = (
            "eval-analyze:" + "0" * 64
        )
    else:
        report_value["events"][0]["primary_results"][0]["effective_search_epoch"] = (
            "eval-verify:" + "0" * 64
        )

    with pytest.raises(
        SemanticEvalContractError,
        match="effective_search_epoch does not recompute",
    ):
        validate_semantic_eval_report_authoritatively(
            report_value,
            corpus=corpus,
            observed=observed,
        )
