"""Unified semantic gate, budgets, reports, publication, and exit truth table.

Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-12.2]
"""

from __future__ import annotations

import hashlib
import json
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from backstitch.artifact_contracts import ValidatedSemanticPacket
from backstitch.semantic_analysis import (
    ResolvedSemanticSettings,
    ResolvedVerificationSettings,
    SemanticAnalysisRequest,
    SemanticAnalysisRun,
    _build_verification_work,
    required_independent_qualification_problem,
    run_semantic_analysis,
)
from backstitch.semantic_cache import (
    AdapterFactory,
    ProviderAdapter,
    ProviderCallResult,
    SemanticCacheInspection,
    SemanticProvenance,
)
from backstitch.semantic_eval import (
    SemanticEvalRequest,
    derive_semantic_eval_observed_facts,
    run_semantic_eval,
)
from backstitch.semantic_eval_reports import (
    load_semantic_eval_corpus,
    load_semantic_eval_report,
)
from backstitch.semantic_evidence import normalize_model_result
from backstitch.semantic_identity import (
    ProviderIdentity,
    RequestIdentity,
    build_composition_identity,
    build_inference_identity,
)
from backstitch.semantic_packets import (
    canonical_json_bytes,
    model_request_bytes,
    semantic_packet_hash,
)
from backstitch.semantic_policy import (
    SemanticPolicy,
    finding_hash,
    materialize_semantic_policy,
)
from backstitch.semantic_reports import PacketReport, validate_packet_report
from backstitch.settings import SemanticDisposition, VerifyEvalSettings, resolve_config


def test_invalid_option_fails_before_snapshot_provider_or_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import backstitch.analysis_llm as analysis_llm
    import backstitch.obligation_runtime as obligation_runtime
    from backstitch.cli import main

    output = tmp_path / "analysis.jsonl"
    monkeypatch.setattr(
        obligation_runtime,
        "capture_obligation_snapshot",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("snapshot capture reached")
        ),
    )
    monkeypatch.setattr(
        analysis_llm,
        "default_provider_adapter",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("provider construction reached")
        ),
    )

    exit_code = main(
        [
            "analyze",
            "--repo-root",
            str(tmp_path),
            "--output",
            str(output),
            "--option",
            "unknown.value",
            "x",
        ]
    )

    assert exit_code == 2
    assert "not runtime-overridable" in capsys.readouterr().err
    assert not output.exists()


PROVIDER = ProviderIdentity(
    backend_id="llm",
    plugin_id="openai",
    model_id="gpt-test",
    model_revision="2026-01-01",
    adapter_id="backstitch.llm",
    adapter_version=1,
    llm_distribution_version="0.31.1",
    plugin_distribution_name="llm-openai",
    plugin_distribution_version="1.2.3",
)
REQUEST = RequestIdentity("require", 0.0, 42, 512)
PROVENANCE = SemanticProvenance(
    adapter_id="backstitch.llm",
    adapter_version=1,
    plugin_version="1.2.3",
    model_class="tests.ControlledModel",
    provider_model_id="gpt-test",
    provider_model_revision="2026-01-01",
    response_id="response-1",
    input_tokens=10,
    output_tokens=5,
)
QUALIFICATION_CORPUS = (
    Path(__file__).parent
    / "semantic_eval"
    / "v3"
    / "qualification-candidate"
    / "manifest.json"
)


def _write_real_qualification(
    tmp_path: Path,
    analyze: ResolvedSemanticSettings,
    verify: ResolvedVerificationSettings,
) -> VerifyEvalSettings:
    corpus = load_semantic_eval_corpus(QUALIFICATION_CORPUS, mode="enforce")
    observed = derive_semantic_eval_observed_facts(corpus)
    case_rows = {
        row["case_id"]: row
        for row in cast(list[dict[str, Any]], corpus.to_dict()["cases"])
    }
    response_by_hash: dict[str, tuple[str, list[dict[str, object]]]] = {}
    for variant in observed.variants:
        case = case_rows[variant.case_id]
        expected = next(
            (
                row
                for row in cast(list[dict[str, Any]], case["expected_findings"])
                if row["variant_id"] == variant.variant_id
            ),
            None,
        )
        classification = (
            cast(str, expected["classification"]) if expected is not None else "ok"
        )
        for packet in variant.packets:
            regions = cast(list[dict[str, object]], packet["evidence_regions"])
            evidence = (
                []
                if classification == "ok"
                else [
                    {
                        key: region[key]
                        for key in ("role", "path", "start_line", "end_line")
                    }
                    for region in regions
                    if classification != "missing_trace"
                    or region["role"] == "requirement"
                ]
            )
            response_by_hash[cast(str, packet["packet_hash"])] = (
                classification,
                evidence,
            )

    def provenance(provider: ProviderIdentity) -> SemanticProvenance:
        return SemanticProvenance(
            adapter_id=provider.adapter_id,
            adapter_version=provider.adapter_version,
            plugin_version=provider.plugin_distribution_version or None,
            model_class="tests.RealQualificationModel",
            provider_model_id=provider.model_id,
            provider_model_revision=provider.model_revision,
            response_id="qualification-response",
            input_tokens=10,
            output_tokens=5,
        )

    def analyzer_factory() -> ProviderAdapter:
        def call(prompt: str) -> ProviderCallResult:
            packet = cast(dict[str, Any], json.loads(prompt.rsplit("\n\n", 1)[1]))
            packet_hash = hashlib.sha256(canonical_json_bytes(packet)).hexdigest()
            classification, evidence = response_by_hash[packet_hash]
            return ProviderCallResult(
                json.dumps(
                    {
                        "packet_id": packet["packet_id"],
                        "classification": classification,
                        "confidence": 1.0,
                        "rationale": "Controlled real qualification artifact.",
                        "summary": "Controlled qualification result.",
                        "evidence": evidence,
                    }
                ),
                provenance(analyze.provider_identity),
            )

        return call

    def verifier_factory() -> ProviderAdapter:
        def call(prompt: str) -> ProviderCallResult:
            request = cast(dict[str, Any], json.loads(prompt.rsplit("\n\n", 1)[1]))
            claim = cast(dict[str, Any], request["claim"])
            return ProviderCallResult(
                json.dumps(
                    {
                        "packet_id": claim["packet_id"],
                        "claim_hash": hashlib.sha256(
                            canonical_json_bytes(claim)
                        ).hexdigest(),
                        "verdict": "support",
                        "support_score": 1.0,
                        "summary": "Controlled claim support.",
                        "evidence": [
                            {
                                key: item[key]
                                for key in ("role", "path", "start_line", "end_line")
                            }
                            for item in cast(list[dict[str, Any]], claim["evidence"])
                        ],
                    }
                ),
                provenance(verify.provider_identity),
            )

        return call

    output = tmp_path / "qualification-report.json"
    evaluation = VerifyEvalSettings(
        mode="enforce",
        qualification_corpus=str(QUALIFICATION_CORPUS),
        qualification_corpus_sha256=corpus.corpus_sha256,
        qualification_report="",
        qualification_report_sha256="",
        trials=2,
        interval_method="wilson",
        confidence_level=0.95,
        minimum_positive_units=1,
        minimum_negative_units=1,
        minimum_evidence_sufficiency_rate=0.0,
        minimum_conditional_precision=0.0,
        minimum_conditional_recall=0.0,
        minimum_end_to_end_recall=0.0,
        minimum_recall_lower_bound=0.0,
        maximum_false_positive_rate=1.0,
        maximum_false_positive_upper_bound=1.0,
        maximum_indeterminate_rate=1.0,
        maximum_uncached_flip_rate=1.0,
        require_all_critical=False,
    )
    run = run_semantic_eval(
        SemanticEvalRequest(
            manifest_path=QUALIFICATION_CORPUS,
            output_path=output,
            settings=replace(
                analyze,
                maximum_provider_calls=200,
                maximum_runtime_seconds=300,
            ),
            verification_settings=replace(
                verify,
                maximum_provider_calls=200,
                maximum_runtime_seconds=300,
            ),
            eval_settings=evaluation,
            adapter_factory=analyzer_factory,
            verification_adapter_factory=verifier_factory,
        )
    )
    assert run.exit_code == 0
    report = load_semantic_eval_report(output, corpus=corpus)
    return replace(
        evaluation,
        qualification_report=str(output),
        qualification_report_sha256=report.report_sha256,
    )


def _packet(
    *,
    packet_id: str = "docs/specs/01-x.md#X-1",
    identity: str = "X-1",
) -> dict[str, object]:
    row: dict[str, object] = {
        "schema_version": 3,
        "packet_id": packet_id,
        "packet_hash": "",
        "kind": "section",
        "obligation_id": packet_id,
        "source_snapshot": {
            "snapshot_hash": "1" * 64,
            "obligation_state_hash": "2" * 64,
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
            "path": "docs/specs/01-x.md",
            "identity": identity,
            "title": "Value",
            "start_line": 6,
            "end_line": 6,
            "text": "Must return one.",
        },
        "declared_evidence": [
            {
                "role": "implementation",
                "path": "pkg/x.py",
                "symbol": "value",
                "start_line": 11,
                "end_line": 11,
                "snippet": "    return 2",
                "sources": [
                    {
                        "source_role": "implementation",
                        "receipt_hash": "4" * 64,
                        "relation_kinds": ["spec_mapping", "code_backlink"],
                        "reciprocity_state": "complete",
                    }
                ],
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
                    "declared": 0,
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
                    "relation_kind": kind,
                    "count": 1 if kind in {"spec_mapping", "code_backlink"} else 0,
                }
                for kind in (
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
                "path": "docs/specs/01-x.md",
                "start_line": 6,
                "end_line": 6,
            },
            {
                "role": "implementation",
                "path": "pkg/x.py",
                "start_line": 11,
                "end_line": 11,
            },
        ],
        "issues": [],
        "packet_warnings": [],
    }
    state = {
        "obligation_state_version": 1,
        "obligation_id": row["obligation_id"],
        "kind": row["kind"],
        "obligation_rung": "active",
        "intent_state": "identified",
        "alignment_state": "complete",
        "disposition": "evaluate",
        "gate_state": "executable",
        "required_roles": ["implementation"],
        "declared_sources": [
            {
                "source_role": "implementation",
                "receipt_hash": "4" * 64,
                "relation_kinds": ["spec_mapping", "code_backlink"],
                "reciprocity_state": "complete",
            }
        ],
    }
    source_snapshot = cast(dict[str, object], row["source_snapshot"])
    source_snapshot["obligation_state_hash"] = hashlib.sha256(
        canonical_json_bytes(state)
    ).hexdigest()
    row["packet_hash"] = semantic_packet_hash(row)
    return row


def _model_row(classification: str = "ok") -> dict[str, object]:
    evidence: list[dict[str, object]] = []
    if classification == "confirmed_mismatch":
        evidence = [
            {
                "role": "requirement",
                "path": "docs/specs/01-x.md",
                "start_line": 6,
                "end_line": 6,
            },
            {
                "role": "implementation",
                "path": "pkg/x.py",
                "start_line": 11,
                "end_line": 11,
            },
        ]
    return {
        "packet_id": "docs/specs/01-x.md#X-1",
        "classification": classification,
        "confidence": 0.9,
        "rationale": "Bounded review.",
        "summary": "Reviewed one packet.",
        "evidence": evidence,
    }


def _resolved(**overrides: object) -> ResolvedSemanticSettings:
    values: dict[str, object] = {
        "provider_identity": PROVIDER,
        "request_identity": REQUEST,
        "concurrency": 1,
        "cache_path": Path("unused-cache"),
        "cache_mode": "off",
        "result_reuse": "exact-inference",
        "search_epoch": "1",
        "require_complete": True,
        "required_kinds": ("section",),
        "minimum_packets": 1,
        "maximum_packets": 100,
        "maximum_prompt_bytes": 1_000_000,
        "finding_handling": "report",
        "maximum_provider_calls": 10,
        "lock_wait_timeout_seconds": 1,
        "maximum_runtime_seconds": 60,
        "maximum_estimated_cost_microusd": 0,
        "input_cost_microusd_per_million_tokens": 0,
        "output_cost_microusd_per_million_tokens": 0,
        "input_token_overhead": 256,
        "cost_rate_source": "",
        "dispositions": (),
    }
    values.update(overrides)
    return ResolvedSemanticSettings(**values)  # type: ignore[arg-type]


def _resolved_verify(
    analyze: ResolvedSemanticSettings,
    **overrides: object,
) -> ResolvedVerificationSettings:
    composition = build_composition_identity(
        analyze.provider_identity,
        analyze.request_identity,
        analysis_search_epoch=analyze.search_epoch,
        verify_provider=PROVIDER,
        verify_request=REQUEST,
        verify_search_epochs=("verify-1",),
        required_verdicts=1,
        minimum_support_score=0.8,
        indeterminate="report",
    )
    values: dict[str, object] = {
        "provider_identity": PROVIDER,
        "request_identity": REQUEST,
        "composition_identity": composition,
        "concurrency": 1,
        "cache_path": Path("unused-verify-cache"),
        "cache_mode": "off",
        "search_epochs": ("verify-1",),
        "required_verdicts": 1,
        "minimum_support_score": 0.8,
        "indeterminate": "report",
        "maximum_provider_calls": 10,
        "maximum_prompt_bytes": 1_000_000,
        "lock_wait_timeout_seconds": 1,
        "maximum_runtime_seconds": 60,
        "maximum_estimated_cost_microusd": 0,
        "input_cost_microusd_per_million_tokens": 0,
        "output_cost_microusd_per_million_tokens": 0,
        "input_token_overhead": 256,
        "cost_rate_source": "",
    }
    values.update(overrides)
    return ResolvedVerificationSettings(**values)  # type: ignore[arg-type]


def _policy(tmp_path: Path, config_text: str | None = None) -> SemanticPolicy:
    if config_text is None:
        loaded = resolve_config(tmp_path, use_repo_config=False)
    else:
        config = tmp_path / ".backstitch.toml"
        config.write_text(config_text, encoding="utf-8")
        loaded = resolve_config(tmp_path, explicit=config)
    return materialize_semantic_policy(
        loaded.diagnostics,
        loaded.policy_rule_origins,
        loaded.config_layers,
    )


def test_effective_verifier_epochs_change_event_keys_not_composition() -> None:
    row = _packet()
    analyzer_identity = build_inference_identity(row, PROVIDER, REQUEST)
    result = normalize_model_result(
        row,
        _model_row("confirmed_mismatch"),
        analysis_key=analyzer_identity.analysis_key,
    ).to_row()
    analyze = _resolved()
    composition = build_composition_identity(
        analyze.provider_identity,
        analyze.request_identity,
        analysis_search_epoch=analyze.search_epoch,
        verify_provider=PROVIDER,
        verify_request=REQUEST,
        verify_search_epochs=("base-a", "base-b"),
        required_verdicts=2,
        minimum_support_score=0.8,
        indeterminate="report",
    )
    settings = _resolved_verify(
        analyze,
        composition_identity=composition,
        search_epochs=("base-a", "base-b"),
        effective_search_epochs=("effective-a", "effective-b"),
        required_verdicts=2,
    )

    work, _ = _build_verification_work((row,), (result,), settings)

    assert [(item.base_search_epoch, item.effective_search_epoch) for item in work] == [
        ("base-a", "effective-a"),
        ("base-b", "effective-b"),
    ]
    assert [item.identity.contract["effective_search_epoch"] for item in work] == [
        "effective-a",
        "effective-b",
    ]
    assert settings.composition_identity.verify_composition["search_epochs"] == [
        "base-a",
        "base-b",
    ]


def _packet_report(
    packet_jsonl: bytes,
    packets: tuple[ValidatedSemanticPacket, ...],
) -> PacketReport:
    rows = tuple(packet.to_dict() for packet in packets)
    audit = [
        {
            "obligation_id": row["obligation_id"],
            "kind": row["kind"],
            "path": row["requirement"]["path"],
            "start_line": row["requirement"]["start_line"],
            "intent_state": "identified",
            "alignment_state": "complete",
            "disposition": "evaluate",
            "obligation_rung": "active",
            "gate_state": "executable",
            "skip": None,
        }
        for row in rows
    ]
    value: dict[str, Any] = {
        "schema_version": 2,
        "artifact": "backstitch-packet-report",
        "packet_schema_version": 3,
        "scope": "source_snapshot",
        "source_snapshot": {
            "snapshot_hash": "1" * 64,
            "file_count": 3,
            "byte_count": 120,
            "unreadable_count": 0,
        },
        "derivation_contract": {
            "obligation_algorithm_version": 1,
            "discovery_algorithm_version": 1,
            "packet_contract_version": 3,
            "normalization_version": 1,
            "semantic_config_sha256": "5" * 64,
        },
        "packet_jsonl_sha256": hashlib.sha256(packet_jsonl).hexdigest(),
        "packet_count": len(rows),
        "packet_bytes": len(packet_jsonl),
        "selection_status": "selected",
        "readiness_counts": {
            "total": len(rows),
            "active": len(rows),
            "out_of_scope": 0,
            "selected": len(rows),
            "skipped": 0,
            "alignment_debt": 0,
            "blocked": 0,
        },
        "alignment_audit": audit,
        "deterministic_issues": [],
        "packets": [
            {"packet_id": row["packet_id"], "packet_hash": row["packet_hash"]}
            for row in rows
        ],
        "packet_report_content_sha256": "",
        "tool_version": "test",
        "created_at": "2026-07-16T12:00:00Z",
    }
    content_fields = (
        "schema_version",
        "artifact",
        "packet_schema_version",
        "scope",
        "source_snapshot",
        "derivation_contract",
        "packet_jsonl_sha256",
        "packet_count",
        "packet_bytes",
        "selection_status",
        "readiness_counts",
        "alignment_audit",
        "deterministic_issues",
        "packets",
    )
    value["packet_report_content_sha256"] = hashlib.sha256(
        canonical_json_bytes({field: value[field] for field in content_fields})
    ).hexdigest()
    return validate_packet_report(
        value,
        packet_jsonl=packet_jsonl,
        packets=packets,
    )


def _packet_report_v3(
    packet_jsonl: bytes,
    packets: tuple[ValidatedSemanticPacket, ...],
) -> PacketReport:
    value = _packet_report(packet_jsonl, packets).to_dict()
    value["schema_version"] = 3
    value["packet_schema_versions"] = [value.pop("packet_schema_version")]
    derivation = value["derivation_contract"]
    derivation["packet_contract_versions"] = [derivation.pop("packet_contract_version")]
    rows = tuple(packet.to_dict() for packet in packets)
    counts = {
        packet_kind: sum(row["kind"] == packet_kind for row in rows)
        for packet_kind in ("section", "invariant", "suppression")
    }
    value["kind_counts"] = {"eligible": counts, "emitted": dict(counts)}
    value["packet_report_content_sha256"] = hashlib.sha256(
        canonical_json_bytes(
            {
                key: item
                for key, item in value.items()
                if key
                not in {
                    "packet_report_content_sha256",
                    "tool_version",
                    "created_at",
                }
            }
        )
    ).hexdigest()
    return validate_packet_report(
        value,
        packet_jsonl=packet_jsonl,
        packets=packets,
    )


def _all_skipped_packet_report() -> PacketReport:
    value: dict[str, Any] = {
        "schema_version": 2,
        "artifact": "backstitch-packet-report",
        "packet_schema_version": 3,
        "scope": "source_snapshot",
        "source_snapshot": {
            "snapshot_hash": "1" * 64,
            "file_count": 1,
            "byte_count": 20,
            "unreadable_count": 0,
        },
        "derivation_contract": {
            "obligation_algorithm_version": 1,
            "discovery_algorithm_version": 1,
            "packet_contract_version": 3,
            "normalization_version": 1,
            "semantic_config_sha256": "5" * 64,
        },
        "packet_jsonl_sha256": hashlib.sha256(b"").hexdigest(),
        "packet_count": 0,
        "packet_bytes": 0,
        "selection_status": "not_run_all_skipped",
        "readiness_counts": {
            "total": 1,
            "active": 1,
            "out_of_scope": 0,
            "selected": 0,
            "skipped": 1,
            "alignment_debt": 0,
            "blocked": 0,
        },
        "alignment_audit": [
            {
                "obligation_id": "docs/specs/01-x.md#X-1",
                "kind": "section",
                "path": "docs/specs/01-x.md",
                "start_line": 1,
                "intent_state": "identified",
                "alignment_state": "complete",
                "disposition": "skipped",
                "obligation_rung": "active",
                "gate_state": "not_executable",
                "skip": {
                    "reason": "Checked elsewhere.",
                    "path": "docs/specs/01-x.md",
                    "line": 1,
                },
            }
        ],
        "deterministic_issues": [],
        "packets": [],
        "packet_report_content_sha256": "",
        "tool_version": "test",
        "created_at": "2026-07-16T12:00:00Z",
    }
    projection = {
        key: value[key]
        for key in (
            "schema_version",
            "artifact",
            "packet_schema_version",
            "scope",
            "source_snapshot",
            "derivation_contract",
            "packet_jsonl_sha256",
            "packet_count",
            "packet_bytes",
            "selection_status",
            "readiness_counts",
            "alignment_audit",
            "deterministic_issues",
            "packets",
        )
    }
    value["packet_report_content_sha256"] = hashlib.sha256(
        canonical_json_bytes(projection)
    ).hexdigest()
    return validate_packet_report(value, packet_jsonl=b"", packets=())


def _analysis_request(
    tmp_path: Path,
    *,
    settings: ResolvedSemanticSettings | None = None,
    policy: SemanticPolicy | None = None,
    model_row: dict[str, object] | None = None,
    packet_report: bool = True,
    adapter_factory: AdapterFactory | None = None,
) -> SemanticAnalysisRequest:
    row = _packet()
    validated = ValidatedSemanticPacket.from_row(row, cache_eligible=True)
    packet_jsonl = canonical_json_bytes(row) + b"\n"
    report = _packet_report(packet_jsonl, (validated,)) if packet_report else None
    response = model_row or _model_row()

    def default_factory() -> ProviderAdapter:
        def call(prompt: str) -> ProviderCallResult:
            return ProviderCallResult(json.dumps(response), PROVENANCE)

        return call

    return SemanticAnalysisRequest(
        packets=(validated,),
        packet_jsonl_sha256=hashlib.sha256(packet_jsonl).hexdigest(),
        packet_report=report,
        settings=settings or _resolved(cache_path=tmp_path / "cache"),
        policy=policy or _policy(tmp_path),
        adapter_factory=adapter_factory or default_factory,
        result_path=tmp_path / "analysis.jsonl",
        report_path=tmp_path / "analysis-report.json",
    )


def test_complete_clean_run_publishes_closed_report_and_exits_zero(
    tmp_path: Path,
) -> None:
    request = _analysis_request(tmp_path)

    run = run_semantic_analysis(request)

    assert run.exit_code == 0
    assert run.problems == ()
    assert len(run.results) == 1
    assert run.diagnostics == ()
    assert request.result_path is not None
    assert request.result_path.read_bytes() == run.result_jsonl
    assert request.report_path is not None
    assert request.report_path.read_bytes() == run.report_json


def test_current_report_counts_operational_events_and_zero_suppressions_vacuously(
    tmp_path: Path,
) -> None:
    request = _analysis_request(
        tmp_path,
        settings=_resolved(
            cache_path=tmp_path / "cache",
            required_kinds=("section", "suppression"),
        ),
    )
    packet_jsonl = b"".join(
        canonical_json_bytes(packet.to_dict()) + b"\n" for packet in request.packets
    )
    request = replace(
        request,
        packet_report=_packet_report_v3(packet_jsonl, request.packets),
    )

    run = run_semantic_analysis(request)

    assert run.exit_code == 0
    assert run.report["schema_version"] == 5
    assert run.report["packet_schema_versions"] == [3]
    assert run.report["kind_counts"] == {
        "eligible": {"section": 1, "invariant": 0, "suppression": 0},
        "emitted": {"section": 1, "invariant": 0, "suppression": 0},
        "results": {"section": 1, "invariant": 0, "suppression": 0},
        "cache_hits": {"section": 0, "invariant": 0, "suppression": 0},
        "cache_misses": {"section": 0, "invariant": 0, "suppression": 0},
        "provider_calls": {"section": 1, "invariant": 0, "suppression": 0},
    }
    assert run.report["result_reuse"] == "exact-inference"


def test_evidence_stable_mixed_run_carries_unchanged_and_calls_changed(
    tmp_path: Path,
) -> None:
    first = _packet()
    second = _packet(packet_id="docs/specs/01-x.md#X-2", identity="X-2")
    initial_packets = tuple(
        ValidatedSemanticPacket.from_row(row, cache_eligible=True)
        for row in (first, second)
    )
    cache_path = tmp_path / "cache"
    provider_calls = 0

    def adapter_factory(provider: ProviderIdentity) -> AdapterFactory:
        def factory() -> ProviderAdapter:
            def call(prompt: str) -> ProviderCallResult:
                nonlocal provider_calls
                provider_calls += 1
                packet = json.loads(prompt.rsplit("\n\n", 1)[1])
                response = _model_row()
                response["packet_id"] = packet["packet_id"]
                return ProviderCallResult(
                    json.dumps(response),
                    replace(
                        PROVENANCE,
                        provider_model_id=provider.model_id,
                        provider_model_revision=provider.model_revision,
                        response_id=f"response-{provider_calls}",
                    ),
                )

            return call

        return factory

    def request_for(
        packets: tuple[ValidatedSemanticPacket, ...],
        provider: ProviderIdentity,
        stem: str,
    ) -> SemanticAnalysisRequest:
        packet_jsonl = b"".join(
            canonical_json_bytes(packet.to_dict()) + b"\n" for packet in packets
        )
        return SemanticAnalysisRequest(
            packets=packets,
            packet_jsonl_sha256=hashlib.sha256(packet_jsonl).hexdigest(),
            packet_report=_packet_report_v3(packet_jsonl, packets),
            settings=_resolved(
                provider_identity=provider,
                cache_path=cache_path,
                cache_mode="read-write",
                result_reuse="evidence-stable",
                minimum_packets=2,
            ),
            policy=_policy(tmp_path),
            adapter_factory=adapter_factory(provider),
            result_path=tmp_path / f"{stem}.jsonl",
            report_path=tmp_path / f"{stem}-report.json",
        )

    initial = run_semantic_analysis(request_for(initial_packets, PROVIDER, "initial"))
    assert initial.exit_code == 0
    assert provider_calls == 2

    changed_second = dict(second)
    changed_requirement = dict(cast(dict[str, object], changed_second["requirement"]))
    changed_requirement["text"] = "Must return two."
    changed_second["requirement"] = changed_requirement
    changed_second["packet_hash"] = semantic_packet_hash(changed_second)
    next_packets = (
        initial_packets[0],
        ValidatedSemanticPacket.from_row(changed_second, cache_eligible=True),
    )
    next_provider = replace(
        PROVIDER,
        model_id="pkg:service/openai.com/gpt-next",
        model_revision="2026-07-28",
    )

    mixed = run_semantic_analysis(request_for(next_packets, next_provider, "mixed"))

    assert mixed.exit_code == 0
    assert mixed.report["provider_calls"] == 1
    assert mixed.report["cache_hits"] == 1
    assert mixed.report["carried_results"] == 1
    assert [row["selection"] for row in mixed.report["result_sources"]] == [
        "carried",
        "live",
    ]
    assert len(mixed.report["result_providers"]) == 2
    assert provider_calls == 3

    qualified_settings = _resolved(
        provider_identity=next_provider,
        cache_path=cache_path,
        cache_mode="read-write",
        result_reuse="evidence-stable",
        minimum_packets=2,
    )
    verification = _resolved_verify(
        qualified_settings,
        cache_path=tmp_path / "qualification-verify-cache",
    )
    evaluation = _write_real_qualification(
        tmp_path,
        qualified_settings,
        verification,
    )
    policy_root = tmp_path / "strong-policy"
    policy_root.mkdir()
    strong_policy = _policy(
        policy_root,
        "[[diagnostics.levels]]\n"
        'select = ["BSA001:independently_verified"]\n'
        'level = "error"\n',
    )

    blocked_request = replace(
        request_for(next_packets, next_provider, "qualification-blocked"),
        settings=qualified_settings,
        policy=strong_policy,
        verification_settings=verification,
        evaluation_settings=evaluation,
    )
    blocked = run_semantic_analysis(blocked_request)

    assert blocked.exit_code == 2
    assert provider_calls == 3
    assert blocked.report["provider_calls"] == 0
    assert blocked.report["problems"][0]["code"] == (
        "required_qualification_unavailable"
    )
    foreign = blocked.report["problems"][0]["details"]["unqualified_analyzer_providers"]
    assert [row["model_id"] for row in foreign] == [PROVIDER.model_id]


def test_foreign_multi_packet_winner_blocks_qualified_waiter_before_calls(
    tmp_path: Path,
) -> None:
    packets = tuple(
        ValidatedSemanticPacket.from_row(row, cache_eligible=True)
        for row in (
            _packet(),
            _packet(packet_id="docs/specs/01-x.md#X-2", identity="X-2"),
        )
    )
    packet_jsonl = b"".join(
        canonical_json_bytes(packet.to_dict()) + b"\n" for packet in packets
    )
    packet_report = _packet_report_v3(packet_jsonl, packets)
    cache_path = tmp_path / "cache"
    qualified_provider = replace(
        PROVIDER,
        model_id="pkg:service/openai.com/qualified",
        model_revision="qualified-revision",
    )
    foreign_provider = replace(
        PROVIDER,
        model_id="pkg:service/openai.com/foreign",
        model_revision="foreign-revision",
    )
    qualified_settings = _resolved(
        provider_identity=qualified_provider,
        cache_path=cache_path,
        cache_mode="read-write",
        result_reuse="evidence-stable",
        minimum_packets=2,
    )
    verification = _resolved_verify(
        qualified_settings,
        cache_path=tmp_path / "qualification-verify-cache",
    )
    evaluation = _write_real_qualification(
        tmp_path,
        qualified_settings,
        verification,
    )
    policy_root = tmp_path / "strong-policy"
    policy_root.mkdir()
    strong_policy = _policy(
        policy_root,
        "[[diagnostics.levels]]\n"
        'select = ["BSA001:independently_verified"]\n'
        'level = "error"\n',
    )
    winner_entered = threading.Event()
    release_winner = threading.Event()
    calls = {"winner": 0, "loser": 0}

    def factory(
        provider: ProviderIdentity,
        lane: str,
    ) -> AdapterFactory:
        def build() -> ProviderAdapter:
            def call(prompt: str) -> ProviderCallResult:
                calls[lane] += 1
                if lane == "winner" and calls[lane] == 1:
                    winner_entered.set()
                    assert release_winner.wait(timeout=2)
                packet = cast(dict[str, Any], json.loads(prompt.rsplit("\n\n", 1)[1]))
                response = _model_row()
                response["packet_id"] = packet["packet_id"]
                return ProviderCallResult(
                    json.dumps(response),
                    replace(
                        PROVENANCE,
                        provider_model_id=provider.model_id,
                        provider_model_revision=provider.model_revision,
                    ),
                )

            return call

        return build

    def request(
        provider: ProviderIdentity,
        lane: str,
        *,
        qualified: bool,
    ) -> SemanticAnalysisRequest:
        return SemanticAnalysisRequest(
            packets=packets,
            packet_jsonl_sha256=hashlib.sha256(packet_jsonl).hexdigest(),
            packet_report=packet_report,
            settings=(
                qualified_settings
                if qualified
                else _resolved(
                    provider_identity=provider,
                    cache_path=cache_path,
                    cache_mode="read-write",
                    result_reuse="evidence-stable",
                    minimum_packets=2,
                )
            ),
            policy=strong_policy if qualified else _policy(tmp_path),
            adapter_factory=factory(provider, lane),
            verification_settings=verification if qualified else None,
            evaluation_settings=evaluation if qualified else None,
            result_path=tmp_path / f"{lane}.jsonl",
            report_path=tmp_path / f"{lane}-report.json",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        winner_future = pool.submit(
            run_semantic_analysis,
            request(foreign_provider, "winner", qualified=False),
        )
        assert winner_entered.wait(timeout=2)
        assert len(list((cache_path / "review-locks").glob("*.lock"))) == 2
        loser_future = pool.submit(
            run_semantic_analysis,
            request(qualified_provider, "loser", qualified=True),
        )
        time.sleep(0.05)
        assert not loser_future.done()
        assert calls["loser"] == 0
        release_winner.set()
        winner = winner_future.result(timeout=3)
        loser = loser_future.result(timeout=3)

    assert winner.exit_code == 0
    assert calls == {"winner": 2, "loser": 0}
    assert loser.exit_code == 2
    assert loser.report["provider_calls"] == 0
    assert loser.report["problems"][0]["code"] == ("required_qualification_unavailable")
    foreign = loser.report["problems"][0]["details"]["unqualified_analyzer_providers"]
    assert [row["model_id"] for row in foreign] == [foreign_provider.model_id]
    assert len(list((cache_path / "baselines").glob("*.json"))) == 2


@pytest.mark.parametrize("ownership_state", ["replaced", "absent"])
def test_analysis_report_accepts_hit_after_provider_call_on_ownership_loss(
    tmp_path: Path,
    ownership_state: str,
) -> None:
    cache_path = tmp_path / "cache"
    settings = _resolved(cache_path=cache_path, cache_mode="read-write")
    request = _analysis_request(tmp_path, settings=settings)
    packet_jsonl = b"".join(
        canonical_json_bytes(packet.to_dict()) + b"\n" for packet in request.packets
    )
    request = replace(
        request,
        packet_report=_packet_report_v3(packet_jsonl, request.packets),
    )
    populated = run_semantic_analysis(request)
    assert populated.exit_code == 0

    row = request.packets[0].to_dict()
    identity = build_inference_identity(
        row,
        settings.provider_identity,
        settings.request_identity,
        search_epoch=settings.search_epoch,
    )
    result_path = cache_path / "results" / f"{identity.analysis_key}.json"
    result_bytes = result_path.read_bytes()
    result_path.unlink()
    lock_path = cache_path / "locks" / f"{identity.analysis_key}.lock"

    def publish_winner(_prompt: str) -> ProviderCallResult:
        if ownership_state == "replaced":
            lock = json.loads(lock_path.read_bytes())
            lock["owner_token"] = "e" * 64
            lock_path.write_bytes(canonical_json_bytes(lock))
        else:
            lock_path.unlink()
        result_path.write_bytes(result_bytes)
        return ProviderCallResult(json.dumps(_model_row()), PROVENANCE)

    raced = run_semantic_analysis(
        replace(
            request,
            adapter_factory=lambda: publish_winner,
            result_path=tmp_path / "raced-analysis.jsonl",
            report_path=tmp_path / "raced-analysis-report.json",
        )
    )

    assert raced.exit_code == 0
    assert raced.result_jsonl == populated.result_jsonl
    assert raced.report["cache_hits"] == 1
    assert raced.report["cache_misses"] == 0
    assert raced.report["provider_calls"] == 1
    assert raced.report["kind_counts"]["cache_hits"]["section"] == 1
    assert raced.report["kind_counts"]["cache_misses"]["section"] == 0
    assert raced.report["kind_counts"]["provider_calls"]["section"] == 1


def test_prompt_resource_mutation_cannot_change_frozen_preflight_or_budget_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Slice 7.0 pin for the prompt identity lifecycle.

    The request and packet report are built from the original prompt resource.
    A later resource mutation must not change report validation, prompt-budget
    math, cost math, or dispatch because all four consume the one frozen
    identity byte string.
    """

    import backstitch.semantic_analysis as semantic_analysis
    import backstitch.semantic_cache as semantic_cache
    import backstitch.semantic_packets as semantic_packets

    request = _analysis_request(tmp_path)
    row = request.packets[0].to_dict()
    frozen_identity = build_inference_identity(row, PROVIDER, REQUEST)
    frozen_request = model_request_bytes(
        row, instruction_bytes=frozen_identity.prompt_bytes
    )
    observed: list[bytes] = []

    def factory() -> ProviderAdapter:
        def call(prompt: str) -> ProviderCallResult:
            observed.append(prompt.encode())
            return ProviderCallResult(json.dumps(_model_row()), PROVENANCE)

        return call

    request = replace(
        request,
        settings=replace(
            request.settings,
            maximum_prompt_bytes=len(frozen_request),
        ),
        adapter_factory=factory,
    )
    monkeypatch.setattr(
        semantic_cache,
        "build_inference_identity",
        lambda *_args, **_kwargs: frozen_identity,
    )
    monkeypatch.setattr(
        semantic_analysis,
        "build_inference_identity",
        lambda *_args, **_kwargs: frozen_identity,
        raising=False,
    )
    monkeypatch.setattr(
        semantic_packets,
        "prompt_instruction_bytes",
        lambda _kind: b"mutated after request identity freeze\n" * 100,
    )

    run = run_semantic_analysis(request)

    assert run.exit_code == 0
    assert run.problems == ()
    assert len(run.results) == 1
    assert observed == [frozen_request]


def test_shared_runner_rechecks_qualification_with_request_eval_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backstitch.semantic_analysis as semantic_analysis

    evaluation = VerifyEvalSettings(
        mode="report",
        qualification_corpus="",
        qualification_corpus_sha256="",
        qualification_report="",
        qualification_report_sha256="",
        trials=2,
        interval_method="wilson",
        confidence_level=0.95,
        minimum_positive_units=1,
        minimum_negative_units=1,
        minimum_evidence_sufficiency_rate=0.0,
        minimum_conditional_precision=0.0,
        minimum_conditional_recall=0.0,
        minimum_end_to_end_recall=0.0,
        minimum_recall_lower_bound=0.0,
        maximum_false_positive_rate=1.0,
        maximum_false_positive_upper_bound=1.0,
        maximum_indeterminate_rate=1.0,
        maximum_uncached_flip_rate=1.0,
        require_all_critical=False,
    )
    request = replace(
        _analysis_request(tmp_path),
        evaluation_settings=evaluation,
    )
    observed: list[VerifyEvalSettings | None] = []

    def qualify(
        policy: SemanticPolicy,
        verification: ResolvedVerificationSettings | None,
        current: VerifyEvalSettings | None,
    ) -> tuple[None, None]:
        del policy, verification
        observed.append(current)
        return None, None

    monkeypatch.setattr(
        semantic_analysis,
        "_resolve_independent_qualification",
        qualify,
    )

    run = run_semantic_analysis(request)

    assert run.exit_code == 0
    assert observed == [evaluation]
    assert run.report["status"] == "complete"
    assert run.report["analysis_exit_code"] == 0
    assert run.report["packet_count"] == run.report["result_count"] == 1
    assert run.report_json.endswith(b"\n")
    assert set(run.report) == {
        "schema_version",
        "artifact",
        "scope",
        "semantic_status",
        "artifact_integrity",
        "artifact_currentness",
        "source_provenance",
        "source_snapshot",
        "packet_report_content_sha256",
        "alignment_summary",
        "alignment_audit",
        "deterministic_issues",
        "packet_jsonl_sha256",
        "result_jsonl_sha256",
        "status",
        "analysis_exit_code",
        "packet_count",
        "result_count",
        "packet_warning_count",
        "packet_warning_debt",
        "finding_debt",
        "cache_hits",
        "cache_misses",
        "provider_calls",
        "prompt_byte_count",
        "elapsed_milliseconds",
        "estimated_cost_microusd",
        "cost_rate_source",
        "effective_policy_layers",
        "semantic_diagnostics",
        "unused_dispositions",
        "verification",
        "problems",
    }


def test_same_result_and_report_path_is_rejected_before_any_side_effect(
    tmp_path: Path,
) -> None:
    constructed = 0

    def forbidden_factory() -> ProviderAdapter:
        nonlocal constructed
        constructed += 1
        raise AssertionError("adapter constructed")

    request = _analysis_request(tmp_path, adapter_factory=forbidden_factory)
    request = replace(request, report_path=request.result_path)

    run = run_semantic_analysis(request)

    assert run.exit_code == 2
    assert constructed == 0
    assert request.result_path is not None
    assert not request.result_path.exists()
    assert run.problems[0].stage == "input"


def test_missing_required_packet_report_and_call_budget_fail_before_adapter(
    tmp_path: Path,
) -> None:
    constructed = 0

    def forbidden_factory() -> ProviderAdapter:
        nonlocal constructed
        constructed += 1
        raise AssertionError("adapter constructed")

    missing_report = _analysis_request(
        tmp_path,
        packet_report=False,
        adapter_factory=forbidden_factory,
    )
    report_run = run_semantic_analysis(missing_report)
    assert missing_report.result_path is not None
    assert not missing_report.result_path.exists()
    assert missing_report.report_path is not None
    assert not missing_report.report_path.exists()
    over_budget = replace(
        _analysis_request(tmp_path, adapter_factory=forbidden_factory),
        settings=_resolved(
            cache_path=tmp_path / "cache",
            maximum_provider_calls=0,
        ),
    )
    budget_run = run_semantic_analysis(over_budget)

    assert report_run.exit_code == budget_run.exit_code == 2
    assert constructed == 0
    assert report_run.problems[0].stage == "input"
    assert budget_run.problems[0].stage == "budget"


def test_evidence_bound_candidate_is_reported_but_not_exit_one(tmp_path: Path) -> None:
    run = run_semantic_analysis(
        _analysis_request(tmp_path, model_row=_model_row("confirmed_mismatch"))
    )

    assert run.exit_code == 0
    assert run.diagnostics[0].verification_state == "evidence_bound"
    assert run.diagnostics[0].severity == "warning"
    assert run.report["finding_debt"]
    assert not run.diagnostics[0].is_failure


@pytest.mark.parametrize(
    ("verdict", "score", "expected_state", "expected_context"),
    [
        ("support", 0.95, "independently_verified", "independently_verified"),
        ("refute", 0.1, "disputed", "disputed_by_verifier"),
        (
            "indeterminate",
            0.5,
            "verification_indeterminate",
            "verification_indeterminate",
        ),
    ],
)
def test_verifier_events_compose_policy_without_rewriting_analyzer_results(
    tmp_path: Path,
    verdict: str,
    score: float,
    expected_state: str,
    expected_context: str,
) -> None:
    analyze = _resolved(cache_path=tmp_path / "analysis-cache")
    verify = _resolved_verify(analyze, cache_path=tmp_path / "verify-cache")
    calls = 0

    def verifier_factory() -> ProviderAdapter:
        def call(prompt: str) -> ProviderCallResult:
            nonlocal calls
            calls += 1
            request = json.loads(prompt.rsplit("\n\n", 1)[1])
            claim = request["claim"]
            response = {
                "packet_id": request["packet"]["packet_id"],
                "claim_hash": hashlib.sha256(canonical_json_bytes(claim)).hexdigest(),
                "verdict": verdict,
                "support_score": score,
                "summary": "Adversarial check completed.",
                "evidence": [
                    {
                        "role": "requirement",
                        "path": "docs/specs/01-x.md",
                        "start_line": 6,
                        "end_line": 6,
                    }
                ],
            }
            return ProviderCallResult(json.dumps(response), PROVENANCE)

        return call

    request = _analysis_request(
        tmp_path,
        settings=analyze,
        model_row=_model_row("confirmed_mismatch"),
    )
    run = run_semantic_analysis(
        replace(
            request,
            verification_settings=verify,
            verification_adapter_factory=verifier_factory,
        )
    )

    assert run.exit_code == 0
    assert calls == 1
    assert run.results[0]["verification_state"] == "evidence_bound"
    assert run.diagnostics[0].verification_state == expected_context
    event = run.report["verification"]["events"][0]
    assert event["aggregate_state"] == expected_state
    assert run.report["verification"]["aggregate_counts"][expected_state] == 1
    if verdict == "indeterminate":
        assert any("indeterminate" in line for line in run.stderr_lines)


@pytest.mark.parametrize(
    ("analyze_cost", "expected_source"),
    (
        ({}, "verifier rates reviewed 2026-07-16"),
        (
            {
                "maximum_estimated_cost_microusd": 100,
                "input_cost_microusd_per_million_tokens": 1,
                "output_cost_microusd_per_million_tokens": 1,
                "input_token_overhead": 256,
                "cost_rate_source": "analyzer rates reviewed 2026-07-16",
            },
            "analyze: analyzer rates reviewed 2026-07-16; "
            "verify: verifier rates reviewed 2026-07-16",
        ),
    ),
)
def test_composed_cost_estimate_reports_every_rate_source(
    tmp_path: Path,
    analyze_cost: dict[str, object],
    expected_source: str,
) -> None:
    analyze = _resolved(cache_path=tmp_path / "analysis-cache", **analyze_cost)
    verify = _resolved_verify(
        analyze,
        cache_path=tmp_path / "verify-cache",
        maximum_estimated_cost_microusd=100,
        input_cost_microusd_per_million_tokens=1,
        output_cost_microusd_per_million_tokens=1,
        input_token_overhead=256,
        cost_rate_source="verifier rates reviewed 2026-07-16",
    )

    def verifier_factory() -> ProviderAdapter:
        def call(prompt: str) -> ProviderCallResult:
            request = json.loads(prompt.rsplit("\n\n", 1)[1])
            claim = request["claim"]
            return ProviderCallResult(
                json.dumps(
                    {
                        "packet_id": request["packet"]["packet_id"],
                        "claim_hash": hashlib.sha256(
                            canonical_json_bytes(claim)
                        ).hexdigest(),
                        "verdict": "support",
                        "support_score": 0.95,
                        "summary": "The claim survived the adversarial pass.",
                        "evidence": [request["packet"]["evidence_regions"][0]],
                    }
                ),
                PROVENANCE,
            )

        return call

    request = _analysis_request(
        tmp_path,
        settings=analyze,
        model_row=_model_row("confirmed_mismatch"),
    )

    run = run_semantic_analysis(
        replace(
            request,
            verification_settings=verify,
            verification_adapter_factory=verifier_factory,
        )
    )

    assert run.exit_code == 0
    assert cast(int, run.report["estimated_cost_microusd"]) > 0
    assert run.report["cost_rate_source"] == expected_source


def test_enabled_verification_with_no_findings_constructs_no_adapter(
    tmp_path: Path,
) -> None:
    analyze = _resolved(cache_path=tmp_path / "analysis-cache")
    verify = _resolved_verify(analyze, cache_path=tmp_path / "verify-cache")

    def forbidden_factory() -> ProviderAdapter:
        raise AssertionError("zero-finding verification constructed an adapter")

    request = _analysis_request(tmp_path, settings=analyze)
    run = run_semantic_analysis(
        replace(
            request,
            verification_settings=verify,
            verification_adapter_factory=forbidden_factory,
        )
    )

    assert run.exit_code == 0
    assert run.report["verification"]["state"] == "enabled"
    assert run.report["verification"]["events"] == []
    assert run.report["verification"]["provider_calls"] == 0


def test_exact_accepted_disposition_and_exact_policy_rule_can_exit_one(
    tmp_path: Path,
) -> None:
    row = _packet()
    identity = build_inference_identity(row, PROVIDER, REQUEST)
    canonical = normalize_model_result(
        row,
        _model_row("confirmed_mismatch"),
        analysis_key=identity.analysis_key,
    )
    disposition = SemanticDisposition(
        code="SEMANTIC_CONFIRMED_MISMATCH",
        packet_id=str(row["packet_id"]),
        packet_hash=str(row["packet_hash"]),
        finding_hash=finding_hash(canonical),
        status="accepted",
        reason="Reviewed against the implementation.",
    )
    policy = _policy(
        tmp_path,
        "[[diagnostics.levels]]\n"
        'select = ["SEMANTIC_CONFIRMED_MISMATCH:human_verified"]\n'
        'level = "error"\n',
    )
    settings = _resolved(
        cache_path=tmp_path / "cache",
        dispositions=(disposition,),
    )

    run = run_semantic_analysis(
        _analysis_request(
            tmp_path,
            settings=settings,
            policy=policy,
            model_row=_model_row("confirmed_mismatch"),
        )
    )

    assert run.exit_code == 1
    assert run.diagnostics[0].verification_state == "human_verified"
    assert run.diagnostics[0].severity == "error"
    assert run.report["finding_debt"] == []


def test_require_disposition_is_incomplete_not_a_finding(
    tmp_path: Path,
) -> None:
    candidate_run = run_semantic_analysis(
        _analysis_request(
            tmp_path,
            settings=_resolved(
                cache_path=tmp_path / "cache-2",
                finding_handling="require_disposition",
            ),
            model_row=_model_row("confirmed_mismatch"),
        )
    )

    assert candidate_run.exit_code == 2
    assert candidate_run.report["status"] == "incomplete"
    assert candidate_run.problems == ()
    assert candidate_run.report["finding_debt"]


def test_unknown_positive_cost_contract_fails_before_adapter(tmp_path: Path) -> None:
    constructed = 0

    def forbidden_factory() -> ProviderAdapter:
        nonlocal constructed
        constructed += 1
        raise AssertionError("adapter constructed")

    unknown = replace(PROVIDER, plugin_id="unknown-plugin")
    settings = _resolved(
        provider_identity=unknown,
        cache_path=tmp_path / "cache",
        maximum_estimated_cost_microusd=100,
        input_cost_microusd_per_million_tokens=1,
        output_cost_microusd_per_million_tokens=1,
        input_token_overhead=256,
        cost_rate_source="2026-07-14 reviewed rates",
    )

    run = run_semantic_analysis(
        _analysis_request(
            tmp_path,
            settings=settings,
            adapter_factory=forbidden_factory,
        )
    )

    assert run.exit_code == 2
    assert constructed == 0
    assert run.problems[0].stage == "config"
    assert "cost" in run.problems[0].message


def test_concurrency_runs_provider_misses_in_parallel_but_keeps_packet_order(
    tmp_path: Path,
) -> None:
    first = _packet()
    second = _packet(packet_id="docs/specs/01-x.md#X-2", identity="X-2")
    validated = tuple(
        ValidatedSemanticPacket.from_row(row, cache_eligible=True)
        for row in (first, second)
    )
    packet_jsonl = b"".join(
        canonical_json_bytes(row) + b"\n" for row in (first, second)
    )
    packet_report = _packet_report(packet_jsonl, validated)
    barrier = threading.Barrier(2)
    factory_calls = 0

    def factory() -> ProviderAdapter:
        nonlocal factory_calls
        factory_calls += 1

        def call(prompt: str) -> ProviderCallResult:
            packet = json.loads(prompt.rsplit("\n\n", 1)[1])
            barrier.wait(timeout=2)
            response = _model_row()
            response["packet_id"] = packet["packet_id"]
            return ProviderCallResult(json.dumps(response), PROVENANCE)

        return call

    request = SemanticAnalysisRequest(
        packets=validated,
        packet_jsonl_sha256=hashlib.sha256(packet_jsonl).hexdigest(),
        packet_report=packet_report,
        settings=_resolved(
            cache_path=tmp_path / "cache",
            concurrency=2,
            minimum_packets=2,
        ),
        policy=_policy(tmp_path),
        adapter_factory=factory,
        result_path=tmp_path / "analysis.jsonl",
        report_path=tmp_path / "report.json",
    )

    run = run_semantic_analysis(request)

    assert run.exit_code == 0, run.stderr_lines
    assert factory_calls == 1
    assert run.report["provider_calls"] == 2
    assert [row["packet_id"] for row in run.results] == [
        first["packet_id"],
        second["packet_id"],
    ]


def test_zero_packets_without_required_report_fail_before_adapter(
    tmp_path: Path,
) -> None:
    constructed = 0

    def forbidden_factory() -> ProviderAdapter:
        nonlocal constructed
        constructed += 1
        raise AssertionError("empty input cannot construct an adapter")

    request = SemanticAnalysisRequest(
        packets=(),
        packet_jsonl_sha256=hashlib.sha256(b"").hexdigest(),
        packet_report=None,
        settings=_resolved(
            cache_path=tmp_path / "cache",
            require_complete=False,
            required_kinds=(),
            minimum_packets=0,
            maximum_packets=0,
            maximum_prompt_bytes=0,
        ),
        policy=_policy(tmp_path),
        adapter_factory=forbidden_factory,
        result_path=tmp_path / "empty.jsonl",
        report_path=tmp_path / "empty-report.json",
    )

    run = run_semantic_analysis(request)

    assert run.exit_code == 2
    assert run.result_jsonl == b""
    assert request.result_path is not None
    assert not request.result_path.exists()
    assert request.report_path is not None
    assert not request.report_path.exists()
    assert constructed == 0


def test_result_publication_failure_is_reported_and_takes_exit_precedence(
    tmp_path: Path,
) -> None:
    blocking_parent = tmp_path / "not-a-directory"
    blocking_parent.write_text("file", encoding="utf-8")
    request = replace(
        _analysis_request(tmp_path),
        result_path=blocking_parent / "analysis.jsonl",
    )

    run = run_semantic_analysis(request)

    assert run.exit_code == 2
    assert run.report["analysis_exit_code"] == 0
    assert run.report["status"] == "failed"
    assert run.problems[-1].stage == "output"
    assert request.report_path is not None
    assert request.report_path.read_bytes() == run.report_json


def test_supported_positive_cost_ceiling_fails_on_conservative_preflight(
    tmp_path: Path,
) -> None:
    constructed = 0

    def forbidden_factory() -> ProviderAdapter:
        nonlocal constructed
        constructed += 1
        raise AssertionError("cost failure must precede adapter construction")

    settings = _resolved(
        cache_path=tmp_path / "cache",
        maximum_estimated_cost_microusd=1,
        input_cost_microusd_per_million_tokens=1,
        output_cost_microusd_per_million_tokens=1,
        input_token_overhead=256,
        cost_rate_source="2026-07-14 reviewed rates",
    )

    run = run_semantic_analysis(
        _analysis_request(
            tmp_path,
            settings=settings,
            adapter_factory=forbidden_factory,
        )
    )

    assert run.exit_code == 2
    assert constructed == 0
    assert run.report["estimated_cost_microusd"] == 2
    assert run.problems[0].stage == "budget"


def test_cloud_positive_cost_ceiling_rejects_two_zero_rates(tmp_path: Path) -> None:
    constructed = 0

    def forbidden_factory() -> ProviderAdapter:
        nonlocal constructed
        constructed += 1
        raise AssertionError("invalid cloud rates constructed an adapter")

    run = run_semantic_analysis(
        _analysis_request(
            tmp_path,
            settings=_resolved(
                cache_path=tmp_path / "cache",
                maximum_estimated_cost_microusd=1,
                input_cost_microusd_per_million_tokens=0,
                output_cost_microusd_per_million_tokens=0,
                input_token_overhead=256,
                cost_rate_source="2026-07-14 reviewed rates",
            ),
            adapter_factory=forbidden_factory,
        )
    )

    assert run.exit_code == 2
    assert run.problems[0].stage == "config"
    assert "zero rates" in run.problems[0].message
    assert constructed == 0


def test_provider_failure_emits_partial_ordered_output_and_continues(
    tmp_path: Path,
) -> None:
    first = _packet()
    second = _packet(packet_id="docs/specs/01-x.md#X-2", identity="X-2")
    rows = (first, second)
    validated = tuple(
        ValidatedSemanticPacket.from_row(row, cache_eligible=True) for row in rows
    )
    packet_jsonl = b"".join(canonical_json_bytes(row) + b"\n" for row in rows)
    packet_report = _packet_report(packet_jsonl, validated)

    def factory() -> ProviderAdapter:
        def call(prompt: str) -> ProviderCallResult:
            packet = json.loads(prompt.rsplit("\n\n", 1)[1])
            if packet["packet_id"] == first["packet_id"]:
                return ProviderCallResult("not json", PROVENANCE)
            response = _model_row()
            response["packet_id"] = packet["packet_id"]
            return ProviderCallResult(json.dumps(response), PROVENANCE)

        return call

    request = SemanticAnalysisRequest(
        packets=validated,
        packet_jsonl_sha256=hashlib.sha256(packet_jsonl).hexdigest(),
        packet_report=packet_report,
        settings=_resolved(
            cache_path=tmp_path / "cache",
            cache_mode="read-write",
            minimum_packets=2,
        ),
        policy=_policy(tmp_path),
        adapter_factory=factory,
        result_path=tmp_path / "partial.jsonl",
        report_path=tmp_path / "partial-report.json",
    )

    run = run_semantic_analysis(request)

    assert run.exit_code == 2
    assert run.report["provider_calls"] == 2
    assert run.report["cache_misses"] == 2
    assert [row["packet_id"] for row in run.results] == [second["packet_id"]]
    assert [problem.packet_id for problem in run.problems] == [first["packet_id"]]
    assert run.problems[0].stage == "normalization"
    assert request.result_path is not None
    assert request.result_path.read_bytes() == run.result_jsonl
    assert run.result_jsonl.count(b"\n") == 1


def test_cached_replay_reapplies_policy_with_zero_adapter_calls(tmp_path: Path) -> None:
    row = _packet()
    identity = build_inference_identity(row, PROVIDER, REQUEST)
    canonical = normalize_model_result(
        row,
        _model_row("confirmed_mismatch"),
        analysis_key=identity.analysis_key,
    )
    disposition = SemanticDisposition(
        code="SEMANTIC_CONFIRMED_MISMATCH",
        packet_id=str(row["packet_id"]),
        packet_hash=str(row["packet_hash"]),
        finding_hash=finding_hash(canonical),
        status="accepted",
        reason="Reviewed once; policy remains independently configurable.",
    )
    cache_path = tmp_path / "cache"
    first_request = _analysis_request(
        tmp_path,
        settings=_resolved(
            cache_path=cache_path,
            cache_mode="read-write",
            dispositions=(disposition,),
        ),
        model_row=_model_row("confirmed_mismatch"),
    )
    first = run_semantic_analysis(first_request)

    constructed = 0

    def forbidden_factory() -> ProviderAdapter:
        nonlocal constructed
        constructed += 1
        raise AssertionError("require replay constructed an adapter")

    failing_policy = _policy(
        tmp_path,
        "[[diagnostics.levels]]\n"
        'select = ["SEMANTIC_CONFIRMED_MISMATCH:human_verified"]\n'
        'level = "error"\n',
    )
    replay_request = replace(
        first_request,
        settings=replace(first_request.settings, cache_mode="require"),
        policy=failing_policy,
        adapter_factory=None,
        result_path=tmp_path / "replay.jsonl",
        report_path=tmp_path / "replay-report.json",
    )
    replay = run_semantic_analysis(replay_request)

    assert first.exit_code == 0
    assert first.report["provider_calls"] == 1
    assert replay.exit_code == 1
    assert replay.report["provider_calls"] == 0
    assert replay.report["cache_hits"] == 1
    assert replay.result_jsonl == first.result_jsonl
    assert constructed == 0


def test_live_call_budget_survives_a_preflight_hit_disappearing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backstitch.semantic_analysis as semantic_analysis

    cache_path = tmp_path / "cache"
    populated_request = _analysis_request(
        tmp_path,
        settings=_resolved(
            cache_path=cache_path,
            cache_mode="read-write",
        ),
    )
    populated = run_semantic_analysis(populated_request)
    assert populated.exit_code == 0
    identity = build_inference_identity(_packet(), PROVIDER, REQUEST)
    result_path = cache_path / "results" / f"{identity.analysis_key}.json"
    real_inspection = semantic_analysis.inspect_semantic_cache

    def inspect_then_remove(**kwargs: Any) -> SemanticCacheInspection:
        inspection = real_inspection(**kwargs)
        result_path.unlink()
        return inspection

    monkeypatch.setattr(
        semantic_analysis,
        "inspect_semantic_cache",
        inspect_then_remove,
    )
    factory_calls = 0

    def forbidden_factory() -> ProviderAdapter:
        nonlocal factory_calls
        factory_calls += 1
        raise AssertionError("zero call budget constructed an adapter")

    guarded = run_semantic_analysis(
        replace(
            populated_request,
            settings=replace(
                populated_request.settings,
                maximum_provider_calls=0,
            ),
            adapter_factory=forbidden_factory,
            result_path=tmp_path / "guarded.jsonl",
            report_path=tmp_path / "guarded-report.json",
        )
    )

    assert guarded.exit_code == 2
    assert guarded.report["provider_calls"] == 0
    assert guarded.problems[0].stage == "budget"
    assert guarded.problems[0].code == "budget_exceeded"
    assert factory_calls == 0


def test_require_mode_missing_hit_reports_zero_provider_cost(tmp_path: Path) -> None:
    request = _analysis_request(
        tmp_path,
        settings=_resolved(
            cache_path=tmp_path / "missing-cache",
            cache_mode="require",
            maximum_estimated_cost_microusd=10,
            input_cost_microusd_per_million_tokens=1,
            output_cost_microusd_per_million_tokens=1,
            input_token_overhead=256,
            cost_rate_source="2026-07-14 reviewed rates",
        ),
    )

    run = run_semantic_analysis(replace(request, adapter_factory=None))

    assert run.exit_code == 2
    assert run.report["provider_calls"] == 0
    assert run.report["estimated_cost_microusd"] == 0
    assert run.report["cost_rate_source"] == "2026-07-14 reviewed rates"


def test_positive_cost_budget_forbids_a_post_preflight_unplanned_miss(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backstitch.semantic_analysis as semantic_analysis

    cache_path = tmp_path / "cache"
    populated_request = _analysis_request(
        tmp_path,
        settings=_resolved(
            cache_path=cache_path,
            cache_mode="read-write",
        ),
    )
    assert run_semantic_analysis(populated_request).exit_code == 0
    identity = build_inference_identity(_packet(), PROVIDER, REQUEST)
    result_path = cache_path / "results" / f"{identity.analysis_key}.json"
    real_inspection = semantic_analysis.inspect_semantic_cache

    def inspect_then_remove(**kwargs: Any) -> SemanticCacheInspection:
        inspection = real_inspection(**kwargs)
        result_path.unlink()
        return inspection

    monkeypatch.setattr(
        semantic_analysis,
        "inspect_semantic_cache",
        inspect_then_remove,
    )
    factory_calls = 0

    def forbidden_factory() -> ProviderAdapter:
        nonlocal factory_calls
        factory_calls += 1
        raise AssertionError("unplanned cost miss constructed an adapter")

    guarded = run_semantic_analysis(
        replace(
            populated_request,
            settings=replace(
                populated_request.settings,
                maximum_provider_calls=10,
                maximum_estimated_cost_microusd=10,
                input_cost_microusd_per_million_tokens=1,
                output_cost_microusd_per_million_tokens=1,
                input_token_overhead=256,
                cost_rate_source="2026-07-14 reviewed rates",
            ),
            adapter_factory=forbidden_factory,
            result_path=tmp_path / "cost-guarded.jsonl",
            report_path=tmp_path / "cost-guarded-report.json",
        )
    )

    assert guarded.exit_code == 2
    assert guarded.report["provider_calls"] == 0
    assert guarded.report["estimated_cost_microusd"] == 0
    assert guarded.problems[0].stage == "budget"
    assert factory_calls == 0


def test_cli_resolves_env_model_into_identity_and_reads_packet_bytes_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backstitch.semantic_analysis as semantic_analysis
    from backstitch.cli import main

    packets = tmp_path / "packets.jsonl"
    packets.write_bytes(b"")
    packet_report = _all_skipped_packet_report()
    packet_report_path = tmp_path / "packet-report.json"
    packet_report_path.write_bytes(packet_report.to_json_bytes())
    config = tmp_path / "cached.toml"
    config.write_text(
        "\n".join(
            [
                "[analyze]",
                'json_mode = "require"',
                'cache_mode = "read-write"',
                "",
                '[analyze.models."pkg:service/openai.com/env-model"]',
                'adapter_model_id = "env-model"',
                'backend_id = "llm"',
                'plugin_id = "openai"',
                'plugin_distribution_name = "llm"',
                'model_revision = "2026-01-01"',
                "input_cost_microusd_per_million_tokens = 0",
                "output_cost_microusd_per_million_tokens = 0",
                "input_token_overhead = 256",
                'cost_rate_source = "controlled test rates"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    captured: list[SemanticAnalysisRequest] = []

    def fake_run(request: SemanticAnalysisRequest) -> SemanticAnalysisRun:
        captured.append(request)
        return SemanticAnalysisRun((), (), (), b"", {}, b"", (), 0)

    original_read_bytes = Path.read_bytes
    packet_reads = 0

    def counted_read_bytes(path: Path) -> bytes:
        nonlocal packet_reads
        if path == packets:
            packet_reads += 1
        return original_read_bytes(path)

    monkeypatch.setattr(semantic_analysis, "run_semantic_analysis", fake_run)
    monkeypatch.setattr(Path, "read_bytes", counted_read_bytes)
    monkeypatch.setenv("LLM_MODEL", "pkg:service/openai.com/env-model")

    exit_code = main(
        [
            "analyze",
            "--packets",
            str(packets),
            "--packet-report",
            str(packet_report_path),
            "--config",
            str(config),
            "--output",
            str(tmp_path / "analysis.jsonl"),
        ]
    )

    assert exit_code == 0
    assert packet_reads == 1
    assert (
        captured[0].settings.provider_identity.model_id
        == "pkg:service/openai.com/env-model"
    )
    assert captured[0].settings.cache_mode == "read-write"


def test_cli_rejects_cached_env_model_that_disagrees_with_declared_revision_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import backstitch.semantic_analysis as semantic_analysis
    from backstitch.cli import main

    packets = tmp_path / "packets.jsonl"
    packets.write_bytes(b"")
    packet_report = _all_skipped_packet_report()
    packet_report_path = tmp_path / "packet-report.json"
    packet_report_path.write_bytes(packet_report.to_json_bytes())
    config = tmp_path / "cached.toml"
    config.write_text(
        "\n".join(
            [
                "[analyze]",
                'backend_id = "llm"',
                'plugin_id = "openai"',
                'plugin_distribution_name = "llm"',
                'model = "declared-model"',
                'model_revision = "declared-model-2026-01-01"',
                "input_cost_microusd_per_million_tokens = 0",
                "output_cost_microusd_per_million_tokens = 0",
                "input_token_overhead = 256",
                'cost_rate_source = "controlled test rates"',
                'json_mode = "require"',
                'cache_mode = "read-write"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LLM_MODEL", "different-model")
    monkeypatch.setattr(
        semantic_analysis,
        "run_semantic_analysis",
        lambda request: (_ for _ in ()).throw(
            AssertionError("mismatched cached model reached analysis")
        ),
    )

    exit_code = main(
        [
            "analyze",
            "--packets",
            str(packets),
            "--packet-report",
            str(packet_report_path),
            "--config",
            str(config),
            "--output",
            str(tmp_path / "analysis.jsonl"),
        ]
    )

    assert exit_code == 2
    assert "has no trusted analyze model descriptor" in capsys.readouterr().err


def _write_all_skipped_current_repo(root: Path) -> None:
    for directory in ("docs/specs", "docs/plans", "backstitch", "tests"):
        root.joinpath(directory).mkdir(parents=True, exist_ok=True)
    root.joinpath("docs/specs/01-core.md").write_text(
        "# Core\n\n"
        "## Contract [CORE-1] <!-- backstitch: skip-obligation [CORE-1] "
        '"External owner." -->\n\n'
        "The external owner supplies this behavior.\n",
        encoding="utf-8",
    )


def test_cli_current_all_skipped_reports_current_without_provider_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import backstitch.analysis_llm as analysis_llm
    from backstitch.cli import main

    _write_all_skipped_current_repo(tmp_path)
    monkeypatch.setattr(
        analysis_llm,
        "default_provider_adapter",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("all-skipped current analysis constructed an adapter")
        ),
    )
    exit_code = main(
        [
            "analyze",
            "--repo-root",
            str(tmp_path),
            "--no-config",
            "--format",
            "json",
        ]
    )

    assert exit_code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["scope"] == "current_repository"
    assert report["semantic_status"] == "not_run_all_skipped"
    assert report["artifact_currentness"] == "current"
    assert report["source_provenance"] == "captured_current"
    assert report["provider_calls"] == 0


def _write_current_analysis_repo(root: Path) -> None:
    for directory in ("docs/specs", "docs/plans", "backstitch", "tests"):
        root.joinpath(directory).mkdir(parents=True, exist_ok=True)
    root.joinpath("docs/specs/01-core.md").write_text(
        "# Core\n\n"
        "## Contract [CORE-1]\n\n"
        "The implementation returns one.\n\n"
        "_Implementation mapping_:\n\n"
        "- `backstitch/impl.py::fulfill`\n",
        encoding="utf-8",
    )
    root.joinpath("backstitch/impl.py").write_text(
        "def fulfill() -> int:\n"
        '    """Spec: docs/specs/01-core.md [CORE-1]"""\n'
        "    return 1\n",
        encoding="utf-8",
    )


def test_cli_current_analysis_publishes_one_source_bound_artifact_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import backstitch.analysis_llm as analysis_llm
    from backstitch.cli import main

    _write_current_analysis_repo(tmp_path)

    calls = 0

    def adapter_factory(*args: object, **kwargs: object) -> ProviderAdapter:
        nonlocal calls
        provider = cast(ProviderIdentity, kwargs["provider_identity"])

        def call(prompt: str) -> ProviderCallResult:
            nonlocal calls
            calls += 1
            return ProviderCallResult(
                json.dumps(
                    {
                        "packet_id": "docs/specs/01-core.md#CORE-1",
                        "classification": "ok",
                        "confidence": 0.9,
                        "rationale": "The declared implementation matches.",
                        "summary": "The obligation is supported.",
                        "evidence": [],
                    }
                ),
                SemanticProvenance(
                    adapter_id=provider.adapter_id,
                    adapter_version=provider.adapter_version,
                    plugin_version=provider.plugin_distribution_version or None,
                    model_class="tests.ControlledModel",
                    provider_model_id=provider.model_id or None,
                    provider_model_revision=provider.model_revision or None,
                    response_id="current-response",
                    input_tokens=10,
                    output_tokens=5,
                ),
            )

        return call

    monkeypatch.setattr(
        analysis_llm,
        "default_provider_adapter",
        adapter_factory,
    )
    output_dir = tmp_path / "artifacts"
    packets_path = output_dir / "packets.jsonl"
    packet_report_path = output_dir / "packet-report.json"
    result_path = output_dir / "analysis.jsonl"
    report_path = output_dir / "analysis-report.json"

    exit_code = main(
        [
            "analyze",
            "--repo-root",
            str(tmp_path),
            "--no-config",
            "--packets-output",
            str(packets_path),
            "--packet-report-output",
            str(packet_report_path),
            "--output",
            str(result_path),
            "--report",
            str(report_path),
            "--format",
            "json",
        ]
    )

    assert exit_code == 0
    assert calls == 1
    stdout_report = json.loads(capsys.readouterr().out)
    stored_report = json.loads(report_path.read_bytes())
    assert stdout_report == stored_report
    assert stored_report["scope"] == "current_repository"
    assert stored_report["artifact_currentness"] == "current"
    assert stored_report["provider_calls"] == 1
    assert len(packets_path.read_text(encoding="utf-8").splitlines()) == 1
    assert json.loads(packet_report_path.read_bytes())["packet_count"] == 1
    assert len(result_path.read_text(encoding="utf-8").splitlines()) == 1


def test_bare_default_analyze_matches_explicit_provider_capable_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import backstitch.analysis_llm as analysis_llm
    from backstitch.cli import main

    _write_current_analysis_repo(tmp_path)
    tmp_path.joinpath(".backstitch.toml").write_text(
        "\n".join(
            (
                'default_command = "analyze"',
                "[analyze]",
                'backend_id = "llm"',
                'plugin_id = "openai"',
                'plugin_distribution_name = "llm"',
                'model = "controlled-model"',
                'model_revision = "2026-07-28"',
                "input_cost_microusd_per_million_tokens = 0",
                "output_cost_microusd_per_million_tokens = 0",
                "input_token_overhead = 256",
                'cost_rate_source = "controlled test rates"',
                "maximum_provider_calls = 1",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    calls = 0

    def adapter_factory(*args: object, **kwargs: object) -> ProviderAdapter:
        provider = cast(ProviderIdentity, kwargs["provider_identity"])

        def call(prompt: str) -> ProviderCallResult:
            nonlocal calls
            calls += 1
            return ProviderCallResult(
                json.dumps(
                    {
                        "packet_id": "docs/specs/01-core.md#CORE-1",
                        "classification": "ok",
                        "confidence": 0.9,
                        "rationale": "The declared implementation matches.",
                        "summary": "The obligation is supported.",
                        "evidence": [],
                    }
                ),
                SemanticProvenance(
                    adapter_id=provider.adapter_id,
                    adapter_version=provider.adapter_version,
                    plugin_version=provider.plugin_distribution_version or None,
                    model_class="tests.ControlledDefaultModel",
                    provider_model_id=provider.model_id or None,
                    provider_model_revision=provider.model_revision or None,
                    response_id="default-command-response",
                    input_tokens=10,
                    output_tokens=5,
                ),
            )

        return call

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(analysis_llm, "default_provider_adapter", adapter_factory)

    bare_exit = main([])
    bare_output = capsys.readouterr()
    explicit_exit = main(["analyze", "--repo-root", "."])
    explicit_output = capsys.readouterr()

    assert bare_exit == explicit_exit == 0
    assert bare_output.out == explicit_output.out
    assert bare_output.err == explicit_output.err
    assert calls == 2


def test_cli_cache_modes_rebuild_resample_and_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import backstitch.analysis_llm as analysis_llm
    from backstitch.cli import main

    target = tmp_path / "target"
    _write_current_analysis_repo(target)
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    cache = trusted / "semantic-cache"
    calls = 0
    constructions = 0
    monkeypatch.delenv("LLM_MODEL", raising=False)

    def adapter_factory(*args: object, **kwargs: object) -> ProviderAdapter:
        nonlocal constructions
        constructions += 1
        provider = cast(ProviderIdentity, kwargs["provider_identity"])

        def call(prompt: str) -> ProviderCallResult:
            nonlocal calls
            calls += 1
            return ProviderCallResult(
                json.dumps(
                    {
                        "packet_id": "docs/specs/01-core.md#CORE-1",
                        "classification": "ok",
                        "confidence": 0.9,
                        "rationale": "The declared implementation matches.",
                        "summary": "The obligation is supported.",
                        "evidence": [],
                    }
                ),
                SemanticProvenance(
                    adapter_id=provider.adapter_id,
                    adapter_version=provider.adapter_version,
                    plugin_version=provider.plugin_distribution_version or None,
                    model_class="tests.ControlledLifecycleModel",
                    provider_model_id=provider.model_id or None,
                    provider_model_revision=provider.model_revision or None,
                    response_id=f"lifecycle-{calls}",
                    input_tokens=10,
                    output_tokens=5,
                ),
            )

        return call

    monkeypatch.setattr(analysis_llm, "default_provider_adapter", adapter_factory)

    def run(
        mode: str,
        epoch: str,
        stem: str,
        *,
        expect_report: bool = True,
    ) -> tuple[int, dict[str, Any]]:
        config = trusted / f"{mode}-{epoch}.toml"
        config.write_text(
            "\n".join(
                [
                    "[analyze]",
                    'backend_id = "llm"',
                    'plugin_id = "openai"',
                    'plugin_distribution_name = "llm"',
                    'model = "lifecycle-controlled-model"',
                    'model_revision = "2026-07-27"',
                    "input_cost_microusd_per_million_tokens = 0",
                    "output_cost_microusd_per_million_tokens = 0",
                    "input_token_overhead = 256",
                    'cost_rate_source = "controlled test rates"',
                    'json_mode = "require"',
                    f'cache_path = "{cache.as_posix()}"',
                    f'cache_mode = "{mode}"',
                    f'search_epoch = "{epoch}"',
                    f"maximum_provider_calls = {0 if mode == 'require' else 10}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        artifact_root = trusted / "reports"
        report_path = artifact_root / f"{stem}-report.json"
        exit_code = main(
            [
                "analyze",
                "--repo-root",
                str(target),
                "--config",
                str(config),
                "--packets-output",
                str(artifact_root / f"{stem}-packets.jsonl"),
                "--packet-report-output",
                str(artifact_root / f"{stem}-packet-report.json"),
                "--output",
                str(artifact_root / f"{stem}-results.jsonl"),
                "--report",
                str(report_path),
                "--format",
                "json",
            ]
        )
        captured = capsys.readouterr()
        if not expect_report:
            assert not report_path.exists()
            return exit_code, {"stderr": captured.err}
        assert report_path.is_file(), captured.err or captured.out
        return exit_code, json.loads(report_path.read_bytes())

    first_exit, first = run("read-write", "epoch-1", "current")
    second_exit, second = run("read-write", "epoch-1", "current")
    require_exit, require = run("require", "epoch-1", "require")
    cache_before_off = {
        path.relative_to(cache): path.read_bytes()
        for path in cache.rglob("*")
        if path.is_file()
    }
    off_exit, off = run("off", "epoch-1", "off")
    cache_after_off = {
        path.relative_to(cache): path.read_bytes()
        for path in cache.rglob("*")
        if path.is_file()
    }
    resample_exit, resample = run("read-write", "epoch-2", "resample")

    assert first_exit == second_exit == require_exit == off_exit == resample_exit == 0
    assert first["provider_calls"] == 1
    assert second["provider_calls"] == require["provider_calls"] == 0
    assert second["cache_hits"] == require["cache_hits"] == 1
    assert off["provider_calls"] == 1
    assert off["cache_hits"] == off["cache_misses"] == 0
    assert cache_after_off == cache_before_off
    assert resample["provider_calls"] == resample["cache_misses"] == 1
    assert len(list((cache / "results").glob("*.json"))) == 2
    assert calls == 3
    assert constructions == 3

    shutil.rmtree(cache)
    missing_exit, missing = run("require", "epoch-1", "missing", expect_report=False)
    assert missing_exit == 2
    assert "required semantic cache result is missing" in missing["stderr"]
    assert calls == 3
    assert constructions == 3

    rebuild_exit, rebuild = run("read-write", "epoch-1", "rebuild")
    assert rebuild_exit == 0
    assert rebuild["provider_calls"] == rebuild["cache_misses"] == 1
    assert calls == 4
    assert constructions == 4

    cached_result = next((cache / "results").glob("*.json"))
    cached_result.write_text("corrupt\n", encoding="utf-8")
    corrupt_exit, corrupt = run("read-write", "epoch-1", "corrupt", expect_report=False)
    assert corrupt_exit == 2
    assert "cache" in corrupt["stderr"]
    assert calls == 4
    assert constructions == 4


def test_cli_current_source_change_withholds_every_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import backstitch.analysis_llm as analysis_llm
    from backstitch.cli import main

    _write_current_analysis_repo(tmp_path)
    spec_path = tmp_path / "docs/specs/01-core.md"

    def adapter_factory(*args: object, **kwargs: object) -> ProviderAdapter:
        provider = cast(ProviderIdentity, kwargs["provider_identity"])

        def call(prompt: str) -> ProviderCallResult:
            spec_path.write_text(
                spec_path.read_text(encoding="utf-8").replace(
                    "returns one", "returns exactly one"
                ),
                encoding="utf-8",
            )
            return ProviderCallResult(
                json.dumps(
                    {
                        "packet_id": "docs/specs/01-core.md#CORE-1",
                        "classification": "ok",
                        "confidence": 0.9,
                        "rationale": "The pre-mutation evidence matched.",
                        "summary": "The captured obligation was supported.",
                        "evidence": [],
                    }
                ),
                SemanticProvenance(
                    adapter_id=provider.adapter_id,
                    adapter_version=provider.adapter_version,
                    plugin_version=provider.plugin_distribution_version or None,
                    model_class="tests.ControlledModel",
                    provider_model_id=provider.model_id or None,
                    provider_model_revision=provider.model_revision or None,
                    response_id="mutating-response",
                    input_tokens=10,
                    output_tokens=5,
                ),
            )

        return call

    monkeypatch.setattr(
        analysis_llm,
        "default_provider_adapter",
        adapter_factory,
    )
    outputs = tuple(
        tmp_path / "artifacts" / name
        for name in (
            "packets.jsonl",
            "packet-report.json",
            "analysis.jsonl",
            "analysis-report.json",
        )
    )

    exit_code = main(
        [
            "analyze",
            "--repo-root",
            str(tmp_path),
            "--no-config",
            "--packets-output",
            str(outputs[0]),
            "--packet-report-output",
            str(outputs[1]),
            "--output",
            str(outputs[2]),
            "--report",
            str(outputs[3]),
        ]
    )

    assert exit_code == 2
    assert (
        "repository source changed during current analysis" in capsys.readouterr().err
    )
    assert all(not path.exists() for path in outputs)


def test_cli_historical_replay_never_claims_current_repository_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import backstitch.analysis_llm as analysis_llm
    from backstitch.cli import main

    _write_all_skipped_current_repo(tmp_path)
    monkeypatch.setattr(
        analysis_llm,
        "default_provider_adapter",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("all-skipped replay constructed an adapter")
        ),
    )
    output_dir = tmp_path / "artifacts"
    packets_path = output_dir / "packets.jsonl"
    packet_report_path = output_dir / "packet-report.json"
    current_exit = main(
        [
            "analyze",
            "--repo-root",
            str(tmp_path),
            "--no-config",
            "--packets-output",
            str(packets_path),
            "--packet-report-output",
            str(packet_report_path),
            "--format",
            "json",
        ]
    )
    assert current_exit == 0
    capsys.readouterr()

    def replay(*extra: str) -> dict[str, Any]:
        exit_code = main(
            [
                "analyze",
                "--packets",
                str(packets_path),
                "--packet-report",
                str(packet_report_path),
                "--no-config",
                "--format",
                "json",
                *extra,
            ]
        )
        assert exit_code == 0
        return cast(dict[str, Any], json.loads(capsys.readouterr().out))

    compared = replay("--compare-repo-root", str(tmp_path))
    unverified = replay()
    spec_path = tmp_path / "docs/specs/01-core.md"
    spec_path.write_text(
        spec_path.read_text(encoding="utf-8") + "\nChanged after capture.\n",
        encoding="utf-8",
    )
    stale = replay("--compare-repo-root", str(tmp_path))

    assert compared["scope"] == "historical_snapshot"
    assert compared["semantic_status"] == "historical_replay"
    assert compared["artifact_currentness"] == "current"
    assert compared["source_provenance"] == "compared_match"
    assert unverified["scope"] == "historical_snapshot"
    assert unverified["artifact_currentness"] == "unverifiable"
    assert unverified["source_provenance"] == "claimed_unverified"
    assert stale["scope"] == "historical_snapshot"
    assert stale["artifact_currentness"] == "stale"
    assert stale["source_provenance"] == "compared_mismatch"


def test_cli_current_rejects_cache_root_inside_semantic_input_before_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import backstitch.analysis_llm as analysis_llm
    from backstitch.cli import main

    _write_current_analysis_repo(tmp_path)
    tmp_path.joinpath(".backstitch.toml").write_text(
        '[analyze]\ncache_path = "backstitch/semantic-cache"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        analysis_llm,
        "default_provider_adapter",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("overlapping cache path constructed an adapter")
        ),
    )

    exit_code = main(
        [
            "analyze",
            "--repo-root",
            str(tmp_path),
            "--output",
            str(tmp_path / "artifacts/analysis.jsonl"),
        ]
    )

    assert exit_code == 2
    assert "mutable path overlaps a semantic input root" in capsys.readouterr().err
    assert not tmp_path.joinpath("artifacts/analysis.jsonl").exists()


@pytest.mark.parametrize(
    ("provider_source", "expected_same_provider"),
    (("analyze", True), ("override", False)),
)
def test_cli_current_verifier_uses_complete_resolved_provider_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    provider_source: str,
    expected_same_provider: bool,
) -> None:
    import backstitch.analysis_llm as analysis_llm
    from backstitch.cli import main

    _write_current_analysis_repo(tmp_path)
    config_lines = [
        "[analyze]",
        'backend_id = "llm"',
        'plugin_id = "controlled"',
        'plugin_distribution_name = "llm"',
        'model = "controlled-model"',
        'model_revision = "2026-07-16"',
        "input_cost_microusd_per_million_tokens = 0",
        "output_cost_microusd_per_million_tokens = 0",
        "input_token_overhead = 256",
        'cost_rate_source = "controlled test rates"',
        'json_mode = "prefer"',
        'cache_mode = "off"',
        "",
        "[verify]",
        "enabled = true",
        f'provider_source = "{provider_source}"',
        "concurrency = 1",
        'cache_path = "verify-cache"',
        'cache_mode = "off"',
        'search_epochs = ["verify-1"]',
        'json_mode = "prefer"',
        "temperature = 0.0",
        "seed = 42",
        "max_tokens = 512",
        "required_verdicts = 1",
        "minimum_support_score = 0.8",
        'indeterminate = "report"',
        "maximum_provider_calls = 1",
        "maximum_prompt_bytes = 1000000",
        "lock_wait_timeout_seconds = 1",
        "maximum_runtime_seconds = 60",
        "maximum_estimated_cost_microusd = 0",
    ]
    if provider_source == "override":
        config_lines.extend(
            (
                "",
                "[verify.provider]",
                'backend_id = "llm"',
                'plugin_id = "controlled-verifier"',
                'plugin_distribution_name = "llm"',
                'model = "controlled-verifier-model"',
                'model_revision = "2026-07-16-verifier"',
                "input_cost_microusd_per_million_tokens = 0",
                "output_cost_microusd_per_million_tokens = 0",
                "input_token_overhead = 256",
                'cost_rate_source = "controlled test rates"',
            )
        )
    tmp_path.joinpath(".backstitch.toml").write_text(
        "\n".join(config_lines) + "\n",
        encoding="utf-8",
    )
    providers: list[ProviderIdentity] = []

    def adapter_factory(*args: object, **kwargs: object) -> ProviderAdapter:
        provider = cast(ProviderIdentity, kwargs["provider_identity"])
        providers.append(provider)
        is_verifier = "response_schema_builder" in kwargs

        def call(prompt: str) -> ProviderCallResult:
            request = cast(dict[str, Any], json.loads(prompt.rsplit("\n\n", 1)[1]))
            if is_verifier:
                claim = cast(dict[str, Any], request["claim"])
                response: dict[str, object] = {
                    "packet_id": request["packet"]["packet_id"],
                    "claim_hash": hashlib.sha256(
                        canonical_json_bytes(claim)
                    ).hexdigest(),
                    "verdict": "support",
                    "support_score": 0.95,
                    "summary": "The adversarial pass could not falsify the claim.",
                    "evidence": [request["packet"]["evidence_regions"][0]],
                }
            else:
                evidence = [
                    item
                    for item in request["evidence_regions"]
                    if item["role"] in {"requirement", "implementation"}
                ]
                response = {
                    "packet_id": request["packet_id"],
                    "classification": "confirmed_mismatch",
                    "confidence": 0.9,
                    "rationale": "The controlled analyzer reports a mismatch.",
                    "summary": "The declared implementation conflicts.",
                    "evidence": evidence,
                }
            return ProviderCallResult(
                json.dumps(response),
                SemanticProvenance(
                    adapter_id=provider.adapter_id,
                    adapter_version=provider.adapter_version,
                    plugin_version=provider.plugin_distribution_version or None,
                    model_class="tests.ControlledModel",
                    provider_model_id=provider.model_id or None,
                    provider_model_revision=provider.model_revision or None,
                    response_id=(
                        "verify-response" if is_verifier else "analyze-response"
                    ),
                    input_tokens=10,
                    output_tokens=5,
                ),
            )

        return call

    monkeypatch.setattr(
        analysis_llm,
        "default_provider_adapter",
        adapter_factory,
    )

    exit_code = main(
        [
            "analyze",
            "--repo-root",
            str(tmp_path),
            "--format",
            "json",
        ]
    )

    assert exit_code == 0
    report = json.loads(capsys.readouterr().out)
    assert len(providers) == 2
    assert (providers[0] == providers[1]) is expected_same_provider
    if not expected_same_provider:
        assert providers[1].model_id == "controlled-verifier-model"
    assert report["provider_calls"] == 1
    assert report["verification"]["provider_calls"] == 1
    assert report["verification"]["events"][0]["aggregate_state"] == (
        "independently_verified"
    )


def test_cli_current_exact_independent_failure_selector_requires_qualification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import backstitch.analysis_llm as analysis_llm
    import backstitch.obligation_runtime as obligation_runtime
    from backstitch.cli import main

    _write_current_analysis_repo(tmp_path)
    tmp_path.joinpath(".backstitch.toml").write_text(
        "[[diagnostics.levels]]\n"
        'select = ["BSA001:independently_verified"]\n'
        'level = "error"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        analysis_llm,
        "default_provider_adapter",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("unqualified failure authority constructed an adapter")
        ),
    )
    monkeypatch.setattr(
        obligation_runtime,
        "build_obligation_runtime",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("unqualified failure authority captured the repository")
        ),
    )

    exit_code = main(
        [
            "analyze",
            "--repo-root",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "qualification/required_qualification_unavailable" in captured.err
    assert '"reason":"missing"' in captured.err
    assert (
        '"selectors":["SEMANTIC_CONFIRMED_MISMATCH:independently_verified"]'
        in captured.err
    )
    assert '"current_derivation_identity":{' in captured.err
    assert '"current_composition_sha256":null' in captured.err
    assert (
        "Re-run qualification for the current source-derivation, qualification, "
        "and inference contracts or remove the failure-authority selector."
    ) in captured.err


@pytest.mark.parametrize(
    ("state", "expected_reason"),
    (
        ("success", None),
        ("corrupt", "corrupt"),
        ("failed", "failed"),
        ("identity_mismatch", "identity_mismatch"),
    ),
)
def test_independent_failure_authority_loads_exact_enforce_qualification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    state: str,
    expected_reason: str | None,
) -> None:
    import backstitch.semantic_eval as semantic_eval
    import backstitch.semantic_eval_reports as eval_reports
    from backstitch.obligation_runtime import ALGORITHMS

    policy = _policy(
        tmp_path,
        "[[diagnostics.levels]]\n"
        'select = ["BSA001:independently_verified"]\n'
        'level = "error"\n',
    )
    analyze = _resolved()
    verify = _resolved_verify(analyze)
    corpus_path = tmp_path / "corpus.json"
    report_path = tmp_path / "report.json"
    report_path.write_bytes(b"controlled report bytes\n")
    corpus_sha256 = f"sha256:{'b' * 64}"
    report_sha256 = f"sha256:{'c' * 64}"
    evaluation = VerifyEvalSettings(
        mode="enforce",
        qualification_corpus=str(corpus_path),
        qualification_corpus_sha256=corpus_sha256,
        qualification_report=str(report_path),
        qualification_report_sha256=report_sha256,
        trials=2,
        interval_method="wilson",
        confidence_level=0.95,
        minimum_positive_units=1,
        minimum_negative_units=1,
        minimum_evidence_sufficiency_rate=0.8,
        minimum_conditional_precision=0.8,
        minimum_conditional_recall=0.8,
        minimum_end_to_end_recall=0.8,
        minimum_recall_lower_bound=0.1,
        maximum_false_positive_rate=0.0,
        maximum_false_positive_upper_bound=0.2,
        maximum_indeterminate_rate=0.2,
        maximum_uncached_flip_rate=0.2,
        require_all_critical=True,
    )
    eval_config = {
        key: getattr(evaluation, key)
        for key in (
            "trials",
            "interval_method",
            "confidence_level",
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
            "require_all_critical",
        )
    }
    identity = {
        "corpus_sha256": corpus_sha256,
        "snapshot_algorithm_version": ALGORITHMS.snapshot_algorithm_version,
        "obligation_algorithm_version": ALGORITHMS.obligation_algorithm_version,
        "discovery_algorithm_version": ALGORITHMS.discovery_algorithm_version,
        "packet_contract_version": ALGORITHMS.packet_contract_version,
        "normalization_version": ALGORITHMS.normalization_version,
        "composition_sha256": verify.composition_identity.composition_sha256,
        "trials": 2,
        "eval_config": eval_config,
    }
    if state == "identity_mismatch":
        identity["composition_sha256"] = "d" * 64
    report_value = {
        "identity": identity,
        "qualification": {"mode": "enforce"},
        "by_code": [{"code": "SEMANTIC_CONFIRMED_MISMATCH"}],
    }
    report = SimpleNamespace(
        report_sha256=report_sha256,
        passed=state != "failed",
        to_dict=lambda: report_value,
    )
    corpus = SimpleNamespace(corpus_sha256=corpus_sha256)
    monkeypatch.setattr(
        eval_reports,
        "load_semantic_eval_corpus",
        lambda *args, **kwargs: corpus,
    )
    if state == "corrupt":
        monkeypatch.setattr(
            eval_reports,
            "load_semantic_eval_report_bytes",
            lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("corrupt")),
        )
    else:
        monkeypatch.setattr(
            eval_reports,
            "load_semantic_eval_report_bytes",
            lambda *args, **kwargs: report,
        )
    monkeypatch.setattr(
        eval_reports,
        "validate_semantic_eval_report_authoritatively",
        lambda *args, **kwargs: report,
    )
    monkeypatch.setattr(
        semantic_eval,
        "derive_semantic_eval_observed_facts",
        lambda *args, **kwargs: object(),
    )

    problem = required_independent_qualification_problem(policy, verify, evaluation)

    if expected_reason is None:
        assert problem is None
    else:
        assert problem is not None
        assert problem.details["reason"] == expected_reason
        assert problem.details["qualification_report_raw_sha256"] == (
            hashlib.sha256(report_path.read_bytes()).hexdigest()
        )


def test_cli_current_publication_failure_reports_earlier_published_artifacts(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from backstitch.cli import main

    _write_all_skipped_current_repo(tmp_path)
    outputs = tuple(
        tmp_path / "artifacts" / name
        for name in (
            "packets.jsonl",
            "packet-report.json",
            "analysis.jsonl",
            "analysis-report.json",
        )
    )
    outputs[2].mkdir(parents=True)

    exit_code = main(
        [
            "analyze",
            "--repo-root",
            str(tmp_path),
            "--no-config",
            "--packets-output",
            str(outputs[0]),
            "--packet-report-output",
            str(outputs[1]),
            "--output",
            str(outputs[2]),
            "--report",
            str(outputs[3]),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert outputs[0].exists()
    assert outputs[1].exists()
    assert outputs[2].is_dir()
    assert not outputs[3].exists()
    assert "already published" in captured.err
    assert str(outputs[0]) in captured.err
    assert str(outputs[1]) in captured.err
    assert str(outputs[2]) in captured.err
    assert tuple((tmp_path / "artifacts").glob(".*.tmp")) == ()
