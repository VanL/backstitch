"""Packet-report creation and trust-boundary validation.

Spec: docs/specs/06-semantic-gates.md [SEM-7]
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from backstitch.artifact_contracts import ValidatedSemanticPacket
from backstitch.diagnostics import default_level_for, default_registry, short_code_for
from backstitch.semantic_evidence import normalize_model_result
from backstitch.semantic_identity import (
    InferenceIdentity,
    ProviderIdentity,
    RequestIdentity,
    build_inference_identity,
)
from backstitch.semantic_packets import (
    canonical_json_bytes,
    model_request_bytes,
    semantic_packet_hash,
)
from backstitch.semantic_reports import (
    AnalysisReport,
    AnalysisReportError,
    PacketReportError,
    _packet_report_source_shape,
    _validate_analysis_report_source_shape,
    build_packet_report,
    load_analysis_report,
    load_packet_report,
    load_packet_report_bytes,
    validate_analysis_report,
    validate_packet_report,
)
from backstitch.semantic_verification import (
    build_verification_request,
    derive_verification_claim,
)


def _packet(
    *, packet_id: str = "SC-1", warnings: tuple[str, ...] = ()
) -> dict[str, object]:
    row: dict[str, object] = {
        "packet_id": packet_id,
        "kind": "section",
        "spec_path": "docs/spec.md",
        "section_id": packet_id,
        "title": "Contract",
        "section_text": "The value is true.",
        "section_start_line": 4,
        "owners": [
            {
                "path": "pkg/core.py",
                "symbol": "value",
                "start_line": 8,
                "snippet": "value = True",
            }
        ],
        "tests": ["tests/test_core.py"],
        "issues": [],
        "packet_warnings": list(warnings),
    }
    row["schema_version"] = 2
    row["packet_hash"] = semantic_packet_hash(row)
    return row


def _validated(row: dict[str, object]) -> ValidatedSemanticPacket:
    return ValidatedSemanticPacket.from_row(row, cache_eligible=True)


_PROVIDER = ProviderIdentity(
    "controlled",
    "backstitch-tests",
    "controlled-adapter",
    "1",
    "backstitch.controlled",
    1,
    "controlled",
    "controlled",
    "controlled",
)
_REQUEST = RequestIdentity("require", 0.0, 0, 512)


def _identities(
    *rows: dict[str, object],
) -> tuple[InferenceIdentity, ...]:
    return tuple(build_inference_identity(row, _PROVIDER, _REQUEST) for row in rows)


def _current_packet() -> dict[str, Any]:
    source = {
        "source_role": "implementation",
        "receipt_hash": "4" * 64,
        "relation_kinds": ["spec_mapping", "code_backlink"],
        "reciprocity_state": "complete",
    }
    readiness = {
        "intent_state": "identified",
        "alignment_state": "complete",
        "disposition": "evaluate",
        "obligation_rung": "active",
        "gate_state": "executable",
        "required_roles": ["implementation"],
    }
    state = {
        "obligation_state_version": 1,
        "obligation_id": "docs/spec.md#SC-1",
        "kind": "section",
        "obligation_rung": "active",
        "intent_state": "identified",
        "alignment_state": "complete",
        "disposition": "evaluate",
        "gate_state": "executable",
        "required_roles": ["implementation"],
        "declared_sources": [source],
    }
    relation_kinds = (
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
    candidate_kinds = (
        "implementation_definition",
        "test_definition",
        "static_reference",
        "unresolved_reference",
        "report_issue",
    )
    row: dict[str, Any] = {
        "schema_version": 3,
        "packet_id": "docs/spec.md#SC-1",
        "packet_hash": "",
        "kind": "section",
        "obligation_id": "docs/spec.md#SC-1",
        "source_snapshot": {
            "snapshot_hash": "1" * 64,
            "obligation_state_hash": hashlib.sha256(
                canonical_json_bytes(state)
            ).hexdigest(),
            "derivation_config_hash": "3" * 64,
        },
        "readiness": readiness,
        "requirement": {
            "role": "requirement",
            "path": "docs/spec.md",
            "identity": "SC-1",
            "title": "Contract",
            "start_line": 3,
            "end_line": 3,
            "text": "Must return one.",
        },
        "declared_evidence": [
            {
                "role": "implementation",
                "path": "pkg/x.py",
                "symbol": "run",
                "start_line": 2,
                "end_line": 2,
                "snippet": "return 2",
                "sources": [source],
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
                for kind in candidate_kinds
            ],
            "relation_counts": [
                {
                    "relation_kind": kind,
                    "count": int(kind in {"spec_mapping", "code_backlink"}),
                }
                for kind in relation_kinds
            ],
        },
        "evidence_regions": [
            {
                "role": "requirement",
                "path": "docs/spec.md",
                "start_line": 3,
                "end_line": 3,
            },
            {
                "role": "implementation",
                "path": "pkg/x.py",
                "start_line": 2,
                "end_line": 2,
            },
        ],
        "issues": [],
        "packet_warnings": [],
    }
    row["packet_hash"] = semantic_packet_hash(row)
    return row


def _current_packets() -> tuple[ValidatedSemanticPacket, ...]:
    return (_validated(_current_packet()),)


def _jsonl(*rows: dict[str, object]) -> bytes:
    return b"".join(canonical_json_bytes(row) + b"\n" for row in rows)


def _rehash_v2_report(row: dict[str, Any]) -> None:
    projection = {
        field: row[field]
        for field in (
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
    row["packet_report_content_sha256"] = hashlib.sha256(
        canonical_json_bytes(projection)
    ).hexdigest()


def _v2_report() -> dict[str, Any]:
    row: dict[str, Any] = {
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
            "semantic_config_sha256": "2" * 64,
        },
        "packet_jsonl_sha256": "3" * 64,
        "packet_count": 1,
        "packet_bytes": 300,
        "selection_status": "selected",
        "readiness_counts": {
            "total": 1,
            "active": 1,
            "out_of_scope": 0,
            "selected": 1,
            "skipped": 0,
            "alignment_debt": 0,
            "blocked": 0,
        },
        "alignment_audit": [
            {
                "obligation_id": "docs/spec.md#SC-1",
                "kind": "section",
                "path": "docs/spec.md",
                "start_line": 1,
                "intent_state": "identified",
                "alignment_state": "complete",
                "disposition": "evaluate",
                "obligation_rung": "active",
                "gate_state": "executable",
                "skip": None,
            }
        ],
        "deterministic_issues": [],
        "packets": [{"packet_id": "docs/spec.md#SC-1", "packet_hash": "4" * 64}],
        "packet_report_content_sha256": "",
        "tool_version": "0.test",
        "created_at": "2026-07-16T12:00:00Z",
    }
    _rehash_v2_report(row)
    return row


def test_packet_report_byte_ceiling_precedes_json_parsing() -> None:
    with pytest.raises(PacketReportError, match="maximum_packet_report_bytes"):
        load_packet_report_bytes(b"{" + b"x" * 100, maximum_bytes=100)


def test_packet_report_v2_recomputes_audit_buckets_after_self_hash() -> None:
    valid = _v2_report()
    validate_packet_report(valid)

    forged = deepcopy(valid)
    forged["alignment_audit"][0].update(
        alignment_state="partial", gate_state="not_executable"
    )
    _rehash_v2_report(forged)
    with pytest.raises(PacketReportError, match="recompute from alignment_audit"):
        validate_packet_report(forged)


def test_packet_report_v2_recomputes_issue_contract_identity_and_order() -> None:
    report = _v2_report()
    code = "SPEC_FILE_MISSING"
    contexts = default_registry().require(code).contexts
    context = contexts[0] if contexts else None

    def issue(message: str, ordinal: int) -> dict[str, object]:
        identity = {
            "code": code,
            "context": context,
            "path": "docs/spec.md",
            "line": 1,
            "obligation_id": "docs/spec.md#SC-1",
            "ordinal": ordinal,
        }
        return {
            "issue_identity": hashlib.sha256(
                canonical_json_bytes(identity)
            ).hexdigest(),
            "code": code,
            "short_code": short_code_for(code),
            "context": context,
            "severity": default_level_for(code, context),
            "default_severity": default_level_for(code, context),
            "path": "docs/spec.md",
            "line": 1,
            "message": message,
            "obligation_id": "docs/spec.md#SC-1",
        }

    report["deterministic_issues"] = [issue("A missing source.", 0)]
    _rehash_v2_report(report)
    validate_packet_report(report)

    forged = deepcopy(report)
    forged["deterministic_issues"][0]["issue_identity"] = "0" * 64
    _rehash_v2_report(forged)
    with pytest.raises(PacketReportError, match="identity does not recompute"):
        validate_packet_report(forged)

    forged = deepcopy(report)
    forged["deterministic_issues"] = [
        issue("Z later message.", 0),
        issue("A earlier message.", 1),
    ]
    _rehash_v2_report(forged)
    with pytest.raises(PacketReportError, match="ordinary report order"):
        validate_packet_report(forged)


def test_build_packet_report_binds_exact_jsonl_and_recomputable_facts() -> None:
    first = _packet(warnings=("trimmed owner", "trimmed section"))
    second = _packet(packet_id="SC-2")
    packet_bytes = _jsonl(first, second)

    report = build_packet_report(
        packet_jsonl=packet_bytes,
        packets=(_validated(first), _validated(second)),
        identities=_identities(first, second),
        kind="section",
        eligible_counts={"section": 3, "invariant": 2},
    )

    assert report.to_dict() == {
        "schema_version": 1,
        "artifact": "backstitch-packet-report",
        "packet_jsonl_sha256": hashlib.sha256(packet_bytes).hexdigest(),
        "kind": "section",
        "eligible_counts": {"section": 3, "invariant": 2},
        "emitted_counts": {"section": 2, "invariant": 0},
        "packet_warning_count": 2,
        "prompt_byte_count": len(model_request_bytes(first))
        + len(model_request_bytes(second)),
        "packets": [
            {"packet_id": "SC-1", "packet_hash": first["packet_hash"]},
            {"packet_id": "SC-2", "packet_hash": second["packet_hash"]},
        ],
    }
    assert report.to_json_bytes() == canonical_json_bytes(report.to_dict())


def test_validate_packet_report_rejects_each_derived_mismatch() -> None:
    row = _packet(warnings=("trimmed",))
    packet_bytes = _jsonl(row)
    valid = build_packet_report(
        packet_jsonl=packet_bytes,
        packets=(_validated(row),),
        identities=_identities(row),
        kind="section",
        eligible_counts={"section": 1, "invariant": 0},
    ).to_dict()

    mutations: dict[str, dict[str, object]] = {
        "packet digest": {"packet_jsonl_sha256": "0" * 64},
        "emitted count": {"emitted_counts": {"section": 0, "invariant": 0}},
        "warning count": {"packet_warning_count": 0},
        "prompt bytes": {"prompt_byte_count": 0},
        "packet identity": {
            "packets": [{"packet_id": "OTHER", "packet_hash": row["packet_hash"]}]
        },
    }
    for label, replacement in mutations.items():
        candidate = dict(valid)
        candidate.update(replacement)
        with pytest.raises(PacketReportError, match="mismatch") as excinfo:
            validate_packet_report(
                candidate,
                packet_jsonl=packet_bytes,
                packets=(_validated(row),),
                identities=_identities(row),
            )
        assert label.split()[0] in str(excinfo.value)


@pytest.mark.parametrize(
    "mutation",
    [
        {"extra": True},
        {"schema_version": True},
        {"kind": "unknown"},
        {"eligible_counts": {"section": True, "invariant": 0}},
        {"eligible_counts": {"section": 0, "invariant": 0}},
        {"packets": [{"packet_id": "SC-1", "packet_hash": "A" * 64}]},
        {"packets": [{"packet_id": "SC-1", "packet_hash": "0" * 64, "extra": True}]},
    ],
)
def test_packet_report_closed_shape_and_ranges(mutation: dict[str, object]) -> None:
    row = _packet()
    report = build_packet_report(
        packet_jsonl=_jsonl(row),
        packets=(_validated(row),),
        identities=_identities(row),
        kind="section",
        eligible_counts={"section": 1, "invariant": 0},
    ).to_dict()
    report.update(mutation)
    with pytest.raises(PacketReportError):
        validate_packet_report(report)


def test_load_packet_report_rejects_noncanonical_or_trailing_content(
    tmp_path: Path,
) -> None:
    row = _packet()
    report = build_packet_report(
        packet_jsonl=_jsonl(row),
        packets=(_validated(row),),
        identities=_identities(row),
        kind="section",
        eligible_counts={"section": 1, "invariant": 0},
    ).to_dict()
    path = tmp_path / "packet-report.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    assert load_packet_report(path).to_dict() == report

    path.write_text(json.dumps(report) + " trailing", encoding="utf-8")
    with pytest.raises(PacketReportError, match="JSON"):
        load_packet_report(path)


def test_packet_report_rejects_duplicate_packet_ids() -> None:
    row = _packet()
    report = build_packet_report(
        packet_jsonl=_jsonl(row),
        packets=(_validated(row),),
        identities=_identities(row),
        kind="section",
        eligible_counts={"section": 1, "invariant": 0},
    ).to_dict()
    report["packets"] = [*report["packets"], report["packets"][0]]
    report["emitted_counts"] = {"section": 2, "invariant": 0}
    report["eligible_counts"] = {"section": 2, "invariant": 0}
    with pytest.raises(PacketReportError, match="duplicate"):
        validate_packet_report(report)


def _analysis_report() -> tuple[dict[str, Any], bytes]:
    result_jsonl = b"{}\n"
    implementation_excerpt = "return 2"
    requirement_excerpt = "Must return one."
    winning_policy_rule = {
        "source": "packaged:backstitch/defaults.toml",
        "position": 0,
        "selector": "SEMANTIC_CONFIRMED_MISMATCH:evidence_bound",
        "level": "warning",
    }
    diagnostic: dict[str, Any] = {
        "code": "SEMANTIC_CONFIRMED_MISMATCH",
        "short_code": "BSA001",
        "classification": "confirmed_mismatch",
        "packet_kind": "section",
        "packet_id": "docs/spec.md#SC-1",
        "packet_hash": "a" * 64,
        "finding_hash": "b" * 64,
        "verification_state": "evidence_bound",
        "evidence": [
            {
                "role": "implementation",
                "path": "pkg/x.py",
                "start_line": 2,
                "end_line": 2,
                "excerpt": implementation_excerpt,
                "excerpt_sha256": hashlib.sha256(
                    implementation_excerpt.encode("utf-8")
                ).hexdigest(),
            },
            {
                "role": "requirement",
                "path": "docs/spec.md",
                "start_line": 3,
                "end_line": 3,
                "excerpt": requirement_excerpt,
                "excerpt_sha256": hashlib.sha256(
                    requirement_excerpt.encode("utf-8")
                ).hexdigest(),
            },
        ],
        "default_severity": "warning",
        "severity": "warning",
        "summary": "The implementation differs.",
        "rationale": "Evidence is local to the packet.",
        "analysis_key": "c" * 64,
        "winning_policy_rule": winning_policy_rule,
    }
    return (
        {
            "schema_version": 1,
            "artifact": "backstitch-analysis-report",
            "packet_jsonl_sha256": "d" * 64,
            "result_jsonl_sha256": hashlib.sha256(result_jsonl).hexdigest(),
            "status": "complete",
            "analysis_exit_code": 0,
            "packet_count": 1,
            "result_count": 1,
            "packet_warning_count": 0,
            "packet_warning_debt": [],
            "candidate_debt": [],
            "cache_hits": 0,
            "cache_misses": 1,
            "provider_calls": 1,
            "prompt_byte_count": 100,
            "elapsed_milliseconds": 1,
            "estimated_cost_microusd": None,
            "cost_rate_source": None,
            "effective_policy_layers": ["packaged:backstitch/defaults.toml"],
            "semantic_diagnostics": [diagnostic],
            "unused_dispositions": [],
            "problems": [],
        },
        result_jsonl,
    )


def _verification_contract() -> dict[str, Any]:
    return {
        "verify_contract_version": 3,
        "prompt": {"id": "verify", "version": 1, "sha256": "5" * 64},
        "provider": {
            "backend_id": "llm",
            "plugin_id": "provider",
            "model_id": "model",
            "model_revision": "revision",
            "adapter_id": "adapter",
            "adapter_version": 1,
            "llm_distribution_version": "1.0",
            "plugin_distribution_name": "plugin-distribution",
            "plugin_distribution_version": "2.0",
        },
        "request": {
            "json_mode": "require",
            "temperature": 0.0,
            "seed": 42,
            "max_tokens": 512,
        },
        "search_epochs": ["1"],
        "required_verdicts": 1,
        "minimum_support_score": 0.9,
        "indeterminate": "report",
    }


def _claim_hash(diagnostic: dict[str, Any]) -> str:
    claim = {
        "packet_id": diagnostic["packet_id"],
        "packet_hash": diagnostic["packet_hash"],
        "obligation_id": diagnostic["packet_id"],
        "kind": diagnostic["packet_kind"],
        "code": diagnostic["code"],
        "classification": diagnostic["classification"],
        "statement": diagnostic["summary"],
        "evidence": [
            {
                field: item[field]
                for field in (
                    "role",
                    "path",
                    "start_line",
                    "end_line",
                    "excerpt_sha256",
                )
            }
            for item in diagnostic["evidence"]
        ],
    }
    return hashlib.sha256(canonical_json_bytes(claim)).hexdigest()


def _finding_hash(diagnostic: dict[str, Any]) -> str:
    identity = {
        "finding_contract_version": 1,
        "code": diagnostic["code"],
        "classification": diagnostic["classification"],
        "packet_kind": diagnostic["packet_kind"],
        "packet_id": diagnostic["packet_id"],
        "packet_hash": diagnostic["packet_hash"],
        "evidence": [
            {
                field: item[field]
                for field in (
                    "role",
                    "path",
                    "start_line",
                    "end_line",
                    "excerpt_sha256",
                )
            }
            for item in diagnostic["evidence"]
        ],
    }
    return hashlib.sha256(canonical_json_bytes(identity)).hexdigest()


def _enabled_verification(
    diagnostic: dict[str, Any],
    *,
    verdict: str = "support",
    score: float = 0.95,
) -> dict[str, Any]:
    contract = _verification_contract()
    packet = _current_packet()
    claim = derive_verification_claim(
        packet,
        {
            "packet_id": diagnostic["packet_id"],
            "packet_hash": diagnostic["packet_hash"],
            "kind": diagnostic["packet_kind"],
            "classification": diagnostic["classification"],
            "summary": diagnostic["summary"],
            "evidence": diagnostic["evidence"],
        },
    )
    request = build_verification_request(packet, claim)
    claim_hash = claim.claim_hash
    verifier_packet_hash = request.verifier_packet_hash
    inference_contract = {
        "verify_contract_version": 3,
        "verifier_packet_hash": verifier_packet_hash,
        "claim_hash": claim_hash,
        "prompt": contract["prompt"],
        "provider": contract["provider"],
        "request": contract["request"],
        "base_search_epoch": "1",
        "effective_search_epoch": "1",
    }
    verify_key = hashlib.sha256(canonical_json_bytes(inference_contract)).hexdigest()
    state_context = {
        "support": ("independently_verified", "independently_verified"),
        "refute": ("disputed", "disputed_by_verifier"),
        "indeterminate": (
            "verification_indeterminate",
            "verification_indeterminate",
        ),
    }
    aggregate_state, context = state_context[verdict]
    if verdict == "support" and score < contract["minimum_support_score"]:
        aggregate_state = "verification_indeterminate"
        context = "verification_indeterminate"
    evidence = [] if verdict == "indeterminate" else [diagnostic["evidence"][0]]
    return {
        "state": "enabled",
        "contract": contract,
        "events": [
            {
                "packet_id": diagnostic["packet_id"],
                "packet_hash": diagnostic["packet_hash"],
                "claim_hash": claim_hash,
                "verifier_packet_hash": verifier_packet_hash,
                "required_epochs": [
                    {"base_search_epoch": "1", "effective_search_epoch": "1"}
                ],
                "results": [
                    {
                        "verify_key": verify_key,
                        "base_search_epoch": "1",
                        "effective_search_epoch": "1",
                        "verdict": verdict,
                        "support_score": score,
                        "evidence": evidence,
                    }
                ],
                "aggregate_state": aggregate_state,
                "context": context,
            }
        ],
        "aggregate_counts": {
            "independently_verified": int(aggregate_state == "independently_verified"),
            "disputed": int(aggregate_state == "disputed"),
            "verification_indeterminate": int(
                aggregate_state == "verification_indeterminate"
            ),
        },
        "cache_hits": 0,
        "cache_misses": 1,
        "provider_calls": 1,
    }


def _analysis_report_v3(
    *,
    verification: bool = False,
    verdict: str = "support",
    score: float = 0.95,
) -> tuple[dict[str, Any], bytes, dict[str, Any]]:
    packet = _current_packet()
    _validated(packet)
    canonical_result = normalize_model_result(
        packet,
        {
            "packet_id": packet["packet_id"],
            "classification": "confirmed_mismatch",
            "confidence": 0.9,
            "rationale": "Evidence is local to the packet.",
            "summary": "The implementation differs.",
            "evidence": packet["evidence_regions"],
        },
        analysis_key="c" * 64,
    ).to_row()
    result_jsonl = canonical_json_bytes(canonical_result) + b"\n"
    packet_report = _v2_report()
    packet_jsonl = canonical_json_bytes(packet) + b"\n"
    packet_report["source_snapshot"]["snapshot_hash"] = packet["source_snapshot"][
        "snapshot_hash"
    ]
    packet_report["packet_jsonl_sha256"] = hashlib.sha256(packet_jsonl).hexdigest()
    packet_report["packet_bytes"] = len(packet_jsonl)
    packet_report["alignment_audit"][0].update(
        obligation_id=packet["packet_id"],
        path="docs/spec.md",
        start_line=3,
    )
    packet_report["packets"] = [
        {"packet_id": packet["packet_id"], "packet_hash": packet["packet_hash"]}
    ]
    _rehash_v2_report(packet_report)
    winning_policy_rule = {
        "source": "packaged:backstitch/defaults.toml",
        "position": 0,
        "selector": "SEMANTIC_CONFIRMED_MISMATCH:evidence_bound",
        "level": "warning",
    }
    diagnostic: dict[str, Any] = {
        "code": "SEMANTIC_CONFIRMED_MISMATCH",
        "short_code": "BSA001",
        "classification": canonical_result["classification"],
        "packet_kind": canonical_result["kind"],
        "packet_id": canonical_result["packet_id"],
        "packet_hash": canonical_result["packet_hash"],
        "finding_hash": "",
        "verification_state": "evidence_bound",
        "evidence": canonical_result["evidence"],
        "default_severity": "warning",
        "severity": "warning",
        "summary": canonical_result["summary"],
        "rationale": canonical_result["rationale"],
        "analysis_key": canonical_result["analysis_key"],
        "winning_policy_rule": winning_policy_rule,
    }
    diagnostic["finding_hash"] = _finding_hash(diagnostic)
    if verification:
        state_context = {
            "support": (
                "independently_verified"
                if score >= 0.9
                else "verification_indeterminate"
            ),
            "refute": "disputed_by_verifier",
            "indeterminate": "verification_indeterminate",
        }
        diagnostic["verification_state"] = state_context[verdict]
        winning_policy_rule["selector"] = (
            f"SEMANTIC_CONFIRMED_MISMATCH:{state_context[verdict]}"
        )
        if state_context[verdict] == "disputed_by_verifier":
            diagnostic["default_severity"] = "info"
            diagnostic["severity"] = "info"
            winning_policy_rule["level"] = "info"
    report = {
        "schema_version": 3,
        "artifact": "backstitch-analysis-report",
        "scope": "current_repository",
        "semantic_status": "evaluated",
        "artifact_integrity": "valid",
        "artifact_currentness": "current",
        "source_provenance": "captured_current",
        "source_snapshot": deepcopy(packet_report["source_snapshot"]),
        "packet_report_content_sha256": packet_report["packet_report_content_sha256"],
        "alignment_summary": deepcopy(packet_report["readiness_counts"]),
        "alignment_audit": deepcopy(packet_report["alignment_audit"]),
        "deterministic_issues": deepcopy(packet_report["deterministic_issues"]),
        "packet_jsonl_sha256": packet_report["packet_jsonl_sha256"],
        "result_jsonl_sha256": hashlib.sha256(result_jsonl).hexdigest(),
        "status": "complete",
        "analysis_exit_code": 0,
        "packet_count": 1,
        "result_count": 1,
        "packet_warning_count": 0,
        "packet_warning_debt": [],
        "finding_debt": [],
        "cache_hits": 0,
        "cache_misses": 1,
        "provider_calls": 1,
        "prompt_byte_count": 100,
        "elapsed_milliseconds": 1,
        "estimated_cost_microusd": None,
        "cost_rate_source": None,
        "effective_policy_layers": ["packaged:backstitch/defaults.toml"],
        "semantic_diagnostics": [diagnostic],
        "unused_dispositions": [],
        "problems": [],
        "verification": (
            _enabled_verification(diagnostic, verdict=verdict, score=score)
            if verification
            else {
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
        ),
    }
    return report, result_jsonl, packet_report


def _validate_v3(
    report: dict[str, Any],
    result_jsonl: bytes,
    packet_report: dict[str, Any],
    *,
    scope: str = "current_repository",
    semantic_status: str = "evaluated",
    currentness: str = "current",
    provenance: str = "captured_current",
) -> AnalysisReport:
    packets = () if report["packet_count"] == 0 else _current_packets()
    return validate_analysis_report(
        report,
        result_jsonl=result_jsonl,
        packet_report=packet_report,
        packets=packets,
        expected_scope=scope,
        expected_semantic_status=semantic_status,
        expected_artifact_currentness=currentness,
        expected_source_provenance=provenance,
    )


def _analysis_report_v4() -> tuple[dict[str, Any], bytes, dict[str, Any]]:
    report, result_jsonl, packet_report = _analysis_report_v3()
    packet_report["schema_version"] = 3
    packet_report["packet_schema_versions"] = [
        packet_report.pop("packet_schema_version")
    ]
    derivation = packet_report["derivation_contract"]
    derivation["packet_contract_versions"] = [derivation.pop("packet_contract_version")]
    packet_report["kind_counts"] = {
        "eligible": {"section": 1, "invariant": 0, "suppression": 0},
        "emitted": {"section": 1, "invariant": 0, "suppression": 0},
    }
    packet_report["packet_report_content_sha256"] = hashlib.sha256(
        canonical_json_bytes(
            {
                key: value
                for key, value in packet_report.items()
                if key
                not in {
                    "packet_report_content_sha256",
                    "tool_version",
                    "created_at",
                }
            }
        )
    ).hexdigest()
    report.update(
        schema_version=4,
        packet_schema_versions=[3],
        packet_report_content_sha256=packet_report["packet_report_content_sha256"],
        kind_counts={
            **deepcopy(packet_report["kind_counts"]),
            "results": {"section": 1, "invariant": 0, "suppression": 0},
            "cache_hits": {"section": 0, "invariant": 0, "suppression": 0},
            "cache_misses": {"section": 1, "invariant": 0, "suppression": 0},
            "provider_calls": {"section": 1, "invariant": 0, "suppression": 0},
        },
    )
    return report, result_jsonl, packet_report


def _analysis_report_v5() -> tuple[
    dict[str, Any],
    bytes,
    dict[str, Any],
    tuple[dict[str, Any], ...],
    tuple[dict[str, Any], ...],
]:
    report, old_result_jsonl, packet_report = _analysis_report_v4()
    packet = _current_packet()
    identity = build_inference_identity(packet, _PROVIDER, _REQUEST)
    result = json.loads(old_result_jsonl)
    result["analysis_key"] = identity.analysis_key
    result_jsonl = canonical_json_bytes(result) + b"\n"
    diagnostic = report["semantic_diagnostics"][0]
    diagnostic["analysis_key"] = identity.analysis_key
    diagnostic["finding_hash"] = _finding_hash(diagnostic)
    provenance = {
        "adapter_id": _PROVIDER.adapter_id,
        "adapter_version": _PROVIDER.adapter_version,
        "plugin_version": _PROVIDER.plugin_distribution_version,
        "model_class": None,
        "provider_model_id": _PROVIDER.model_id,
        "provider_model_revision": _PROVIDER.model_revision,
        "response_id": None,
        "input_tokens": None,
        "output_tokens": None,
    }
    result_object = {
        "schema_version": 1,
        "object_type": "semantic-result",
        "inference_contract": identity.contract,
        "analysis_key": identity.analysis_key,
        "result": result,
        "provenance": provenance,
        "raw_response_sha256": "d" * 64,
    }
    result_object_sha256 = hashlib.sha256(
        canonical_json_bytes(result_object)
    ).hexdigest()
    review_contract = {
        key: value for key, value in identity.contract.items() if key != "provider"
    }
    review_key = hashlib.sha256(canonical_json_bytes(review_contract)).hexdigest()
    source = {
        "packet_id": packet["packet_id"],
        "packet_hash": packet["packet_hash"],
        "analysis_key": identity.analysis_key,
        "review_key": review_key,
        "result_object_sha256": result_object_sha256,
        "inference_contract": identity.contract,
        "provenance": provenance,
        "selection": "live",
    }
    event = {
        "packet_id": packet["packet_id"],
        "packet_hash": packet["packet_hash"],
        "result_object_sha256": result_object_sha256,
        "selection": "live",
    }
    report.update(
        schema_version=5,
        result_jsonl_sha256=hashlib.sha256(result_jsonl).hexdigest(),
        result_reuse="evidence-stable",
        selected_inference={
            "provider": identity.contract["provider"],
            "request": identity.contract["request"],
            "analysis_contract_version": identity.contract["analysis_contract_version"],
            "search_epoch": identity.contract["search_epoch"],
            "prompts": [{"kind": packet["kind"], **identity.contract["prompt"]}],
        },
        exact_cache_hits=0,
        carried_results=0,
        result_sources=[source],
        result_providers=[
            {
                "provider": identity.contract["provider"],
                "observed_model": {
                    "model_class": None,
                    "provider_model_id": _PROVIDER.model_id,
                    "provider_model_revision": _PROVIDER.model_revision,
                },
                "result_count": 1,
                "carried_result_count": 0,
            }
        ],
    )
    return report, result_jsonl, packet_report, (result_object,), (event,)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (
            "shape",
            "packet report schema 2 does not match its closed shape",
        ),
        ("identity", "packet report source identity is invalid"),
        ("counts", "packet report readiness counts do not balance"),
        ("audit", "packet report alignment_audit count is invalid"),
        (
            "issues",
            "packet report deterministic_issues must be an array",
        ),
        ("packets", "packet report packets count is invalid"),
        ("content", "packet_report_content_sha256 does not recompute"),
        ("created", "created_at must be RFC 3339"),
    ],
)
def test_packet_report_source_shape_preserves_first_error_priority(
    mutation: str,
    expected: str,
) -> None:
    report = _v2_report()
    if mutation == "shape":
        report["extra"] = True
        report["artifact"] = "invalid"
    elif mutation == "identity":
        report["artifact"] = "invalid"
        report["deterministic_issues"] = None
    elif mutation == "counts":
        report["readiness_counts"]["total"] = 0
        report["alignment_audit"] = None
    elif mutation == "audit":
        report["alignment_audit"] = None
        report["deterministic_issues"] = None
    elif mutation == "issues":
        report["deterministic_issues"] = None
        report["packets"] = None
    elif mutation == "packets":
        report["packets"] = []
        report["packet_report_content_sha256"] = "0" * 64
    elif mutation == "content":
        report["packet_report_content_sha256"] = "0" * 64
        report["created_at"] = "invalid"
    else:
        report["created_at"] = "invalid"

    with pytest.raises(PacketReportError) as raised:
        _packet_report_source_shape(report)

    assert str(raised.value) == expected


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (
            "shape",
            "analysis report schema 3 does not match closed shape",
        ),
        ("artifact", "analysis report artifact is invalid"),
        ("scope", "analysis report scope is invalid"),
        ("semantic_status", "current semantic_status is invalid"),
        (
            "currentness",
            "current report currentness/provenance is invalid",
        ),
        ("status", "analysis report status is invalid"),
        ("packet_count", "packet_count must equal alignment_summary.selected"),
        (
            "warnings",
            "packet warning count and debt must be zero and empty for schema 3",
        ),
        ("finding_debt", "finding_debt must be a list"),
        ("diagnostics", "semantic_diagnostics must be a list"),
        ("problems", "problems must be a list"),
    ],
)
def test_analysis_report_source_shape_preserves_first_error_priority(
    mutation: str,
    expected: str,
) -> None:
    report, _result_jsonl, _packet_report = _analysis_report_v3()
    if mutation == "shape":
        report["extra"] = True
        report["artifact"] = "invalid"
    elif mutation == "artifact":
        report["artifact"] = "invalid"
        report["scope"] = "invalid"
    elif mutation == "scope":
        report["scope"] = "invalid"
        report["status"] = "invalid"
    elif mutation == "semantic_status":
        report["semantic_status"] = "invalid"
        report["source_snapshot"] = None
    elif mutation == "currentness":
        report["artifact_currentness"] = "stale"
        report["status"] = "invalid"
    elif mutation == "status":
        report["status"] = "invalid"
        report["packet_count"] = 0
    elif mutation == "packet_count":
        report["packet_count"] = 0
        report["packet_warning_count"] = 1
    elif mutation == "warnings":
        report["packet_warning_count"] = 1
        report["finding_debt"] = None
    elif mutation == "finding_debt":
        report["finding_debt"] = None
        report["semantic_diagnostics"] = None
    elif mutation == "diagnostics":
        report["semantic_diagnostics"] = None
        report["problems"] = None
    else:
        report["problems"] = None
        report["verification"] = None

    with pytest.raises(AnalysisReportError) as raised:
        _validate_analysis_report_source_shape(report)

    assert str(raised.value) == expected


def test_current_report_source_shapes_preserve_canonical_output() -> None:
    analysis, _result_jsonl, packet = _analysis_report_v4()

    assert _packet_report_source_shape(packet) == json.loads(
        canonical_json_bytes(packet)
    )
    assert _validate_analysis_report_source_shape(analysis) == json.loads(
        canonical_json_bytes(analysis)
    )


def test_analysis_report_v5_source_class_uses_operational_event_oracle() -> None:
    report, result_jsonl, packet_report, result_objects, selection_events = (
        _analysis_report_v5()
    )
    validated = validate_analysis_report(
        report,
        result_jsonl=result_jsonl,
        packet_report=packet_report,
        packets=_current_packets(),
        selected_result_objects=result_objects,
        selection_events=selection_events,
        expected_scope="current_repository",
        expected_semantic_status="evaluated",
        expected_artifact_currentness="current",
        expected_source_provenance="captured_current",
    )
    assert validated.to_dict()["result_sources"][0]["selection"] == "live"

    report["result_sources"][0]["selection"] = "exact-cache"
    report["exact_cache_hits"] = 1
    report["cache_hits"] = 1
    report["cache_misses"] = 0
    report["kind_counts"]["cache_hits"]["section"] = 1
    report["kind_counts"]["cache_misses"]["section"] = 0
    with pytest.raises(AnalysisReportError, match="selection event"):
        validate_analysis_report(
            report,
            result_jsonl=result_jsonl,
            packet_report=packet_report,
            packets=_current_packets(),
            selected_result_objects=result_objects,
            selection_events=selection_events,
            expected_scope="current_repository",
            expected_semantic_status="evaluated",
            expected_artifact_currentness="current",
            expected_source_provenance="captured_current",
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("object_hash", "result object hash mismatch"),
        ("event", "does not match selection event"),
        ("analysis_preimage", "analysis key does not recompute"),
        ("review_key", "review key does not recompute"),
        ("source_provider", "producer facts do not match"),
        ("source_provenance", "producer facts do not match"),
        ("source_count", "result_sources count"),
        ("selection_count", "exact_cache_hits"),
        ("provider_group", "result_providers does not recompute"),
    ],
)
def test_analysis_report_v5_rejects_mutated_authoritative_facts(
    mutation: str,
    message: str,
) -> None:
    report, result_jsonl, packet_report, raw_objects, raw_events = _analysis_report_v5()
    result_objects = list(deepcopy(raw_objects))
    selection_events = list(deepcopy(raw_events))
    source = report["result_sources"][0]

    if mutation == "object_hash":
        source["result_object_sha256"] = "0" * 64
    elif mutation == "event":
        selection_events[0]["selection"] = "exact-cache"
    elif mutation == "analysis_preimage":
        result_objects[0]["inference_contract"]["search_epoch"] = "mutated"
        object_hash = hashlib.sha256(
            canonical_json_bytes(result_objects[0])
        ).hexdigest()
        source["result_object_sha256"] = object_hash
        selection_events[0]["result_object_sha256"] = object_hash
    elif mutation == "review_key":
        source["review_key"] = "0" * 64
    elif mutation == "source_provider":
        source["inference_contract"]["provider"]["model_revision"] = "mutated"
    elif mutation == "source_provenance":
        source["provenance"]["provider_model_revision"] = "mutated"
    elif mutation == "source_count":
        report["result_sources"] = []
    elif mutation == "selection_count":
        report["exact_cache_hits"] = 1
    elif mutation == "provider_group":
        report["result_providers"][0]["result_count"] = 2
    else:
        raise AssertionError(f"unhandled mutation: {mutation}")

    with pytest.raises(AnalysisReportError, match=message):
        validate_analysis_report(
            report,
            result_jsonl=result_jsonl,
            packet_report=packet_report,
            packets=_current_packets(),
            selected_result_objects=result_objects,
            selection_events=selection_events,
            expected_scope="current_repository",
            expected_semantic_status="evaluated",
            expected_artifact_currentness="current",
            expected_source_provenance="captured_current",
        )


@pytest.mark.parametrize(
    "population",
    [
        "eligible",
        "emitted",
        "results",
        "cache_hits",
        "cache_misses",
        "provider_calls",
    ],
)
def test_analysis_report_v4_pairs_each_closed_kind_population(
    population: str,
) -> None:
    report, result_jsonl, packet_report = _analysis_report_v4()
    validated = validate_analysis_report(
        report,
        result_jsonl=result_jsonl,
        packet_report=packet_report,
        packets=_current_packets(),
        expected_scope="current_repository",
        expected_semantic_status="evaluated",
        expected_artifact_currentness="current",
        expected_source_provenance="captured_current",
    )
    assert (
        validated.to_dict()["kind_counts"][population]
        == report["kind_counts"][population]
    )

    report["kind_counts"][population]["section"] += 1
    with pytest.raises(AnalysisReportError, match="kind_counts|cache counters"):
        validate_analysis_report(
            report,
            result_jsonl=result_jsonl,
            packet_report=packet_report,
            packets=_current_packets(),
            expected_scope="current_repository",
            expected_semantic_status="evaluated",
            expected_artifact_currentness="current",
            expected_source_provenance="captured_current",
        )


def test_analysis_report_round_trips_through_its_own_loader(tmp_path: Path) -> None:
    report, result_jsonl = _analysis_report()
    validated = validate_analysis_report(
        report,
        result_jsonl=result_jsonl,
        packet_jsonl_sha256="d" * 64,
    )
    path = tmp_path / "analysis-report.json"
    path.write_bytes(validated.to_json_bytes())

    loaded = load_analysis_report(
        path,
        result_jsonl=result_jsonl,
        packet_jsonl_sha256="d" * 64,
    )

    assert loaded.to_dict() == report


def test_analysis_report_accepts_advisory_counterevidence() -> None:
    report, result_jsonl = _analysis_report()
    excerpt = "return 3"
    counter = {
        "role": "counterevidence",
        "path": "pkg/decoy.py",
        "start_line": 9,
        "end_line": 9,
        "excerpt": excerpt,
        "excerpt_sha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
    }
    test_excerpt = "assert run() == 1"
    test_evidence = {
        "role": "test",
        "path": "tests/test_x.py",
        "start_line": 12,
        "end_line": 12,
        "excerpt": test_excerpt,
        "excerpt_sha256": hashlib.sha256(test_excerpt.encode("utf-8")).hexdigest(),
    }
    evidence = report["semantic_diagnostics"][0]["evidence"]
    evidence.extend((counter, test_evidence))
    evidence.sort(
        key=lambda item: (
            item["role"],
            item["path"],
            item["start_line"],
            item["end_line"],
            item["excerpt_sha256"],
        )
    )

    validate_analysis_report(report, result_jsonl=result_jsonl)


def test_analysis_report_evidence_excerpt_must_match_inclusive_span() -> None:
    report, result_jsonl = _analysis_report()
    evidence = report["semantic_diagnostics"][0]["evidence"][0]
    evidence["excerpt"] = f"{evidence['excerpt']}\nextra line"
    evidence["excerpt_sha256"] = hashlib.sha256(
        evidence["excerpt"].encode("utf-8")
    ).hexdigest()

    with pytest.raises(AnalysisReportError, match="line span"):
        validate_analysis_report(report, result_jsonl=result_jsonl)


def test_analysis_report_rejects_cross_contract_forgeries() -> None:
    report, result_jsonl = _analysis_report()
    for mutate in (
        lambda value: value["semantic_diagnostics"][0].update(severity="error"),
        lambda value: value["semantic_diagnostics"][0]["winning_policy_rule"].update(
            source="absent-layer"
        ),
        lambda value: value["semantic_diagnostics"][0]["evidence"][0].update(
            excerpt_sha256="0" * 64
        ),
        lambda value: value.update(analysis_exit_code=2),
        lambda value: value.update(result_count=0),
        lambda value: value["semantic_diagnostics"][0].update(
            evidence=value["semantic_diagnostics"][0]["evidence"][:1]
        ),
    ):
        forged = deepcopy(report)
        mutate(forged)
        with pytest.raises(AnalysisReportError):
            validate_analysis_report(forged, result_jsonl=result_jsonl)


def test_analysis_report_binds_candidate_debt_to_one_diagnostic() -> None:
    report, result_jsonl = _analysis_report()
    diagnostic = report["semantic_diagnostics"][0]
    candidate = {
        key: diagnostic[key]
        for key in (
            "code",
            "packet_id",
            "packet_hash",
            "finding_hash",
            "verification_state",
        )
    }
    report["candidate_debt"] = [candidate]

    validate_analysis_report(report, result_jsonl=result_jsonl)

    for mutate in (
        lambda value: value["candidate_debt"][0].update(finding_hash="0" * 64),
        lambda value: value.update(candidate_debt=value["candidate_debt"] * 2),
        lambda value: value.update(
            semantic_diagnostics=value["semantic_diagnostics"] * 2
        ),
    ):
        forged = deepcopy(report)
        mutate(forged)
        with pytest.raises(AnalysisReportError):
            validate_analysis_report(forged, result_jsonl=result_jsonl)


def test_analysis_report_wrong_types_raise_only_analysis_report_error() -> None:
    report, result_jsonl = _analysis_report()
    for path, bad_value in (
        (("status",), []),
        (("analysis_exit_code",), []),
        (("semantic_diagnostics", 0, "code"), []),
        (("semantic_diagnostics", 0, "verification_state"), []),
        (("semantic_diagnostics", 0, "evidence", 0, "role"), []),
    ):
        forged = deepcopy(report)
        target: Any = forged
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = bad_value
        with pytest.raises(AnalysisReportError):
            validate_analysis_report(forged, result_jsonl=result_jsonl)


def test_analysis_report_v3_round_trips_with_runtime_and_packet_binding(
    tmp_path: Path,
) -> None:
    report, result_jsonl, packet_report = _analysis_report_v3()

    validated = validate_analysis_report(
        report,
        result_jsonl=result_jsonl,
        packet_jsonl_sha256=packet_report["packet_jsonl_sha256"],
        packet_report=packet_report,
        packets=_current_packets(),
        expected_scope="current_repository",
        expected_semantic_status="evaluated",
        expected_artifact_currentness="current",
        expected_source_provenance="captured_current",
    )
    path = tmp_path / "analysis-report-v3.json"
    path.write_bytes(validated.to_json_bytes())

    loaded = load_analysis_report(
        path,
        result_jsonl=result_jsonl,
        packet_report=packet_report,
        packets=_current_packets(),
        expected_scope="current_repository",
        expected_semantic_status="evaluated",
        expected_artifact_currentness="current",
        expected_source_provenance="captured_current",
    )

    assert loaded.to_dict() == report


@pytest.mark.parametrize(
    ("scope", "semantic_status", "currentness", "provenance"),
    (
        ("current_repository", "evaluated", "current", "captured_current"),
        (
            "historical_snapshot",
            "historical_replay",
            "unverifiable",
            "claimed_unverified",
        ),
    ),
    ids=("current", "historical"),
)
@pytest.mark.parametrize(
    ("warning_count", "warning_debt_kind"),
    ((1, "empty"), (0, "nonempty"), (1, "nonempty")),
    ids=("count-only", "debt-only", "matching-count-and-debt"),
)
def test_schema3_analysis_report_rejects_packet_warning_debt(
    scope: str,
    semantic_status: str,
    currentness: str,
    provenance: str,
    warning_count: int,
    warning_debt_kind: str,
) -> None:
    """Reproduce finding #10 at both schema-3 report scope boundaries.

    Current and historical-snapshot schema-3 analysis both consume schema-3
    packets, whose ``packet_warnings`` compatibility field is exactly empty.
    Independent count-only, debt-only, and internally consistent forgeries
    must all be rejected through the full packet/report binding helper. Legacy
    schema-1 report validation retains its historical audit vocabulary. Before
    Slice 2 count-only and internally consistent debt validate in both scopes;
    debt-only already fails the older count-consistency check.
    """

    report, result_jsonl, packet_report = _analysis_report_v3()
    packet_id = report["alignment_audit"][0]["obligation_id"]
    report.update(
        scope=scope,
        semantic_status=semantic_status,
        artifact_currentness=currentness,
        source_provenance=provenance,
        packet_warning_count=warning_count,
        packet_warning_debt=(
            []
            if warning_debt_kind == "empty"
            else [{"packet_id": packet_id, "warnings": ["forged warning"]}]
        ),
    )

    with pytest.raises(AnalysisReportError, match="packet warning"):
        _validate_v3(
            report,
            result_jsonl,
            packet_report,
            scope=scope,
            semantic_status=semantic_status,
            currentness=currentness,
            provenance=provenance,
        )


def test_analysis_report_v3_cannot_self_attest_or_use_legacy_arguments() -> None:
    report, result_jsonl, packet_report = _analysis_report_v3()
    with pytest.raises(AnalysisReportError, match="validate_analysis_report"):
        AnalysisReport.from_dict(report)
    with pytest.raises(AnalysisReportError, match="paired packet report"):
        validate_analysis_report(report, result_jsonl=result_jsonl)
    with pytest.raises(AnalysisReportError, match="runtime authority fields"):
        validate_analysis_report(
            report,
            result_jsonl=result_jsonl,
            packet_report=packet_report,
            packets=_current_packets(),
        )

    legacy, legacy_result = _analysis_report()
    with pytest.raises(AnalysisReportError, match="cannot validate legacy"):
        validate_analysis_report(
            legacy,
            result_jsonl=legacy_result,
            packet_report=packet_report,
            expected_scope="current_repository",
        )


@pytest.mark.parametrize(
    "mutation",
    [
        {"extra": True},
        {"artifact_integrity": "corrupt"},
        {"scope": "other"},
        {"semantic_status": "historical_replay"},
        {"artifact_currentness": "stale"},
        {"source_provenance": "compared_match"},
        {"candidate_debt": []},
    ],
)
def test_analysis_report_v3_top_level_and_current_scope_are_closed(
    mutation: dict[str, object],
) -> None:
    report, result_jsonl, packet_report = _analysis_report_v3()
    report.update(mutation)
    with pytest.raises(AnalysisReportError):
        _validate_v3(report, result_jsonl, packet_report)


@pytest.mark.parametrize(
    ("currentness", "provenance"),
    [
        ("unverifiable", "claimed_unverified"),
        ("current", "compared_match"),
        ("stale", "compared_mismatch"),
    ],
)
def test_analysis_report_v3_historical_scope_combinations(
    currentness: str, provenance: str
) -> None:
    report, result_jsonl, packet_report = _analysis_report_v3()
    report.update(
        scope="historical_snapshot",
        semantic_status="historical_replay",
        artifact_currentness=currentness,
        source_provenance=provenance,
    )

    _validate_v3(
        report,
        result_jsonl,
        packet_report,
        scope="historical_snapshot",
        semantic_status="historical_replay",
        currentness=currentness,
        provenance=provenance,
    )


@pytest.mark.parametrize(
    "field",
    [
        "packet_jsonl_sha256",
        "packet_count",
        "source_snapshot",
        "packet_report_content_sha256",
        "alignment_summary",
        "alignment_audit",
        "deterministic_issues",
    ],
)
def test_analysis_report_v3_packet_report_copies_are_exact(field: str) -> None:
    report, result_jsonl, packet_report = _analysis_report_v3()
    if field in {"packet_jsonl_sha256", "packet_report_content_sha256"}:
        report[field] = "0" * 64
    elif field == "packet_count":
        report[field] = 0
    elif field == "source_snapshot":
        report[field]["byte_count"] += 1
    elif field == "alignment_summary":
        report[field]["selected"] = 0
    elif field == "alignment_audit":
        report[field][0]["start_line"] += 1
    else:
        report[field] = [
            {
                "issue_identity": "0" * 64,
                "code": "SPEC_FILE_MISSING",
                "short_code": short_code_for("SPEC_FILE_MISSING"),
                "context": None,
                "severity": default_level_for("SPEC_FILE_MISSING", None),
                "default_severity": default_level_for("SPEC_FILE_MISSING", None),
                "path": "docs/spec.md",
                "line": 1,
                "message": "Missing.",
                "obligation_id": "docs/spec.md#SC-1",
            }
        ]
    with pytest.raises(AnalysisReportError):
        _validate_v3(report, result_jsonl, packet_report)


def test_analysis_report_v3_semantic_finding_packet_hash_matches_packet_report() -> (
    None
):
    report, result_jsonl, packet_report = _analysis_report_v3()
    report["semantic_diagnostics"][0]["packet_hash"] = "0" * 64
    report["semantic_diagnostics"][0]["finding_hash"] = _finding_hash(
        report["semantic_diagnostics"][0]
    )
    with pytest.raises(AnalysisReportError, match="packet identity"):
        _validate_v3(report, result_jsonl, packet_report)


def test_analysis_report_v3_finding_hash_recomputes_from_canonical_identity() -> None:
    report, result_jsonl, packet_report = _analysis_report_v3()
    report["semantic_diagnostics"][0]["finding_hash"] = "0" * 64
    with pytest.raises(AnalysisReportError, match="finding_hash does not recompute"):
        _validate_v3(report, result_jsonl, packet_report)


@pytest.mark.parametrize("field", ["summary", "rationale", "analysis_key"])
def test_analysis_report_v3_diagnostic_semantics_are_bound_to_result_rows(
    field: str,
) -> None:
    report, result_jsonl, packet_report = _analysis_report_v3()
    report["semantic_diagnostics"][0][field] = (
        "0" * 64 if field == "analysis_key" else "forged presentation"
    )
    with pytest.raises(AnalysisReportError, match=f"{field} does not match result"):
        _validate_v3(report, result_jsonl, packet_report)


@pytest.mark.parametrize(
    "result_jsonl",
    [
        b"{}\n",
        b'{"packet_id": "docs/spec.md#SC-1"}\n',
        b"[]\n",
    ],
)
def test_analysis_report_v3_revalidates_exact_result_jsonl_rows(
    result_jsonl: bytes,
) -> None:
    report, _valid_result, packet_report = _analysis_report_v3()
    report["result_jsonl_sha256"] = hashlib.sha256(result_jsonl).hexdigest()
    with pytest.raises(AnalysisReportError, match="result_jsonl"):
        _validate_v3(report, result_jsonl, packet_report)


def _all_skipped_pair(
    *, verification_enabled: bool
) -> tuple[dict[str, Any], dict[str, Any]]:
    report, _result_jsonl, packet_report = _analysis_report_v3()
    packet_report["packet_jsonl_sha256"] = hashlib.sha256(b"").hexdigest()
    packet_report["packet_count"] = 0
    packet_report["packet_bytes"] = 0
    packet_report["selection_status"] = "not_run_all_skipped"
    packet_report["readiness_counts"].update(selected=0, skipped=1)
    packet_report["alignment_audit"][0].update(
        disposition="skipped", gate_state="not_executable"
    )
    packet_report["alignment_audit"][0]["skip"] = {
        "reason": "not supported",
        "path": "docs/spec.md",
        "line": 1,
    }
    packet_report["packets"] = []
    _rehash_v2_report(packet_report)
    report.update(
        semantic_status="not_run_all_skipped",
        source_snapshot=deepcopy(packet_report["source_snapshot"]),
        packet_report_content_sha256=packet_report["packet_report_content_sha256"],
        alignment_summary=deepcopy(packet_report["readiness_counts"]),
        alignment_audit=deepcopy(packet_report["alignment_audit"]),
        packet_jsonl_sha256=packet_report["packet_jsonl_sha256"],
        result_jsonl_sha256=hashlib.sha256(b"").hexdigest(),
        packet_count=0,
        result_count=0,
        cache_hits=0,
        cache_misses=0,
        provider_calls=0,
        prompt_byte_count=0,
        semantic_diagnostics=[],
        finding_debt=[],
    )
    if verification_enabled:
        report["verification"] = {
            "state": "enabled",
            "contract": _verification_contract(),
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
    return report, packet_report


@pytest.mark.parametrize("verification_enabled", [False, True])
def test_analysis_report_v3_all_skipped_preserves_alignment_without_work(
    verification_enabled: bool,
) -> None:
    report, packet_report = _all_skipped_pair(verification_enabled=verification_enabled)
    validated = _validate_v3(
        report,
        b"",
        packet_report,
        semantic_status="not_run_all_skipped",
    )
    assert validated.to_dict()["alignment_audit"][0]["skip"]["reason"] == (
        "not supported"
    )


def test_analysis_report_v3_failed_verify_run_keeps_attempt_counters_without_event() -> (
    None
):
    report, result_jsonl, packet_report = _analysis_report_v3()
    report.update(
        status="failed",
        analysis_exit_code=2,
        semantic_diagnostics=[],
        finding_debt=[],
        problems=[
            {
                "packet_id": "docs/spec.md#SC-1",
                "obligation_id": "docs/spec.md#SC-1",
                "stage": "provider",
                "code": "provider_failure",
                "message": "Verifier provider failed.",
                "details": {},
            }
        ],
        verification={
            "state": "enabled",
            "contract": _verification_contract(),
            "events": [],
            "aggregate_counts": {
                "independently_verified": 0,
                "disputed": 0,
                "verification_indeterminate": 0,
            },
            "cache_hits": 0,
            "cache_misses": 1,
            "provider_calls": 1,
        },
    )
    _validate_v3(report, result_jsonl, packet_report)


def test_analysis_report_v3_finding_debt_is_exact_diagnostic_subset() -> None:
    report, result_jsonl, packet_report = _analysis_report_v3()
    diagnostic = report["semantic_diagnostics"][0]
    report["finding_debt"] = [
        {
            key: diagnostic[key]
            for key in (
                "code",
                "packet_id",
                "packet_hash",
                "finding_hash",
                "verification_state",
            )
        }
    ]
    _validate_v3(report, result_jsonl, packet_report)

    report["finding_debt"][0]["finding_hash"] = "0" * 64
    with pytest.raises(AnalysisReportError, match="finding_debt"):
        _validate_v3(report, result_jsonl, packet_report)


def test_analysis_report_v3_require_disposition_is_debt_only_incomplete() -> None:
    report, result_jsonl, packet_report = _analysis_report_v3()
    diagnostic = report["semantic_diagnostics"][0]
    report["finding_debt"] = [
        {
            key: diagnostic[key]
            for key in (
                "code",
                "packet_id",
                "packet_hash",
                "finding_hash",
                "verification_state",
            )
        }
    ]
    report.update(status="incomplete", analysis_exit_code=2)

    validated = _validate_v3(report, result_jsonl, packet_report)

    assert validated.to_dict()["problems"] == []


_PROBLEM_CASES = [
    ("config", "invalid_config", {}),
    ("input", "invalid_input", {}),
    ("cache", "corrupt_cache", {}),
    ("cache", "stale_cache", {}),
    ("lock", "lock_timeout", {}),
    ("provider", "provider_failure", {}),
    ("normalization", "malformed_result", {}),
    ("completeness", "incomplete_result", {}),
    ("budget", "budget_exceeded", {}),
    ("output", "output_failure", {}),
    ("internal", "internal_failure", {}),
    ("alignment", "no_active_intent", {}),
    ("alignment", "alignment_incomplete", {"obligation_ids": ["a"]}),
    ("alignment", "readiness_blocked", {"obligation_ids": ["a"]}),
    ("snapshot", "snapshot_unstable", {"attempts": 3}),
    (
        "snapshot",
        "source_changed",
        {"before_snapshot": "1" * 64, "after_snapshot": "2" * 64},
    ),
    (
        "input",
        "mutable_path_overlap",
        {"mutable_path": "/tmp/cache", "semantic_input": "/tmp/repo"},
    ),
    ("input", "unsupported_platform", {"platform": "other"}),
    (
        "input",
        "packet_report_budget_exhausted",
        {"limit_bytes": 100, "observed_bytes": 101},
    ),
    (
        "qualification",
        "required_qualification_unavailable",
        {
            "selectors": ["BSA001:independently_verified"],
            "reason": "identity_mismatch",
            "qualification_report_raw_sha256": "3" * 64,
            "expected_derivation_identity": {
                "snapshot_algorithm_version": 1,
                "obligation_algorithm_version": 1,
                "discovery_algorithm_version": 1,
                "packet_contract_version": 1,
                "normalization_version": 1,
            },
            "current_derivation_identity": {
                "snapshot_algorithm_version": 1,
                "obligation_algorithm_version": 1,
                "discovery_algorithm_version": 1,
                "packet_contract_version": 1,
                "normalization_version": 1,
            },
            "expected_qualification_identity": {
                "corpus_sha256": "6" * 64,
                "mode": "enforce",
                "trials": 1,
                "eval_config": {},
            },
            "current_qualification_identity": {
                "corpus_sha256": "6" * 64,
                "mode": "enforce",
                "trials": 1,
                "eval_config": {},
            },
            "expected_composition_sha256": "4" * 64,
            "current_composition_sha256": "5" * 64,
            "unqualified_analyzer_providers": [],
        },
    ),
]


@pytest.mark.parametrize(("stage", "code", "details"), _PROBLEM_CASES)
def test_analysis_report_v3_every_problem_pair_fires(
    stage: str, code: str, details: dict[str, Any]
) -> None:
    report, result_jsonl, packet_report = _analysis_report_v3()
    report["problems"] = [
        {
            "packet_id": None,
            "obligation_id": None,
            "stage": stage,
            "code": code,
            "message": "Operation failed.",
            "details": details,
        }
    ]
    report["status"] = "incomplete" if stage in {"completeness", "budget"} else "failed"
    if stage != "output":
        report["analysis_exit_code"] = 2

    _validate_v3(report, result_jsonl, packet_report)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda problem: problem.update(extra=True),
        lambda problem: problem.update(message="bad\nmessage"),
        lambda problem: problem.update(details={"attempts": 0}),
        lambda problem: problem.update(details={"attempts": 1, "extra": True}),
    ],
)
def test_analysis_report_v3_problem_rows_and_details_are_closed(mutate: Any) -> None:
    report, result_jsonl, packet_report = _analysis_report_v3()
    problem = {
        "packet_id": None,
        "obligation_id": None,
        "stage": "snapshot",
        "code": "snapshot_unstable",
        "message": "Snapshot unstable.",
        "details": {"attempts": 3},
    }
    mutate(problem)
    report.update(status="failed", analysis_exit_code=2, problems=[problem])
    with pytest.raises(AnalysisReportError):
        _validate_v3(report, result_jsonl, packet_report)


@pytest.mark.parametrize(
    ("verdict", "score", "expected_state"),
    [
        ("support", 0.95, "independently_verified"),
        ("support", 0.5, "verification_indeterminate"),
        ("refute", 0.1, "disputed"),
        ("indeterminate", 0.5, "verification_indeterminate"),
    ],
)
def test_analysis_report_v3_verification_aggregate_recomputes(
    verdict: str, score: float, expected_state: str
) -> None:
    report, result_jsonl, packet_report = _analysis_report_v3(
        verification=True, verdict=verdict, score=score
    )
    _validate_v3(report, result_jsonl, packet_report)
    assert report["verification"]["events"][0]["aggregate_state"] == expected_state


def test_analysis_report_v3_verification_cache_off_counter_shape() -> None:
    report, result_jsonl, packet_report = _analysis_report_v3(verification=True)
    report["verification"].update(cache_hits=0, cache_misses=0, provider_calls=1)

    _validate_v3(report, result_jsonl, packet_report)


def test_analysis_report_v3_verifier_packet_hash_cannot_self_attest() -> None:
    report, result_jsonl, packet_report = _analysis_report_v3(verification=True)
    verification = report["verification"]
    event = verification["events"][0]
    event["verifier_packet_hash"] = "0" * 64
    inference_contract = {
        "verify_contract_version": verification["contract"]["verify_contract_version"],
        "verifier_packet_hash": event["verifier_packet_hash"],
        "claim_hash": event["claim_hash"],
        "prompt": verification["contract"]["prompt"],
        "provider": verification["contract"]["provider"],
        "request": verification["contract"]["request"],
        "base_search_epoch": "1",
        "effective_search_epoch": "1",
    }
    event["results"][0]["verify_key"] = hashlib.sha256(
        canonical_json_bytes(inference_contract)
    ).hexdigest()

    with pytest.raises(AnalysisReportError, match="does not match packet request"):
        _validate_v3(report, result_jsonl, packet_report)


def test_analysis_report_v3_verifier_evidence_is_rebound_to_packet() -> None:
    report, result_jsonl, packet_report = _analysis_report_v3(verification=True)
    excerpt = "forged"
    report["verification"]["events"][0]["results"][0]["evidence"] = [
        {
            "role": "implementation",
            "path": "pkg/other.py",
            "start_line": 1,
            "end_line": 1,
            "excerpt": excerpt,
            "excerpt_sha256": hashlib.sha256(excerpt.encode()).hexdigest(),
        }
    ]

    with pytest.raises(AnalysisReportError, match="evidence is invalid"):
        _validate_v3(report, result_jsonl, packet_report)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda verification: verification.update(state="disabled"),
        lambda verification: verification["contract"].update(extra=True),
        lambda verification: verification["contract"].update(verify_contract_version=2),
        lambda verification: verification["contract"]["provider"].update(model_id=""),
        lambda verification: verification["contract"]["request"].update(max_tokens=0),
        lambda verification: verification["contract"].update(search_epochs=["1", "1"]),
        lambda verification: verification["events"][0].update(claim_hash="0" * 64),
        lambda verification: verification["events"][0]["results"][0].update(
            verify_key="0" * 64
        ),
        lambda verification: verification["events"][0]["results"][0].update(
            support_score=float("nan")
        ),
        lambda verification: verification["events"][0]["results"][0].update(
            evidence=[]
        ),
        lambda verification: verification["events"][0].update(
            aggregate_state="disputed", context="disputed_by_verifier"
        ),
        lambda verification: verification["aggregate_counts"].update(
            independently_verified=0
        ),
        lambda verification: verification.update(provider_calls=2),
    ],
)
def test_analysis_report_v3_verification_contract_relationships_fire(
    mutate: Any,
) -> None:
    report, result_jsonl, packet_report = _analysis_report_v3(verification=True)
    mutate(report["verification"])
    with pytest.raises(AnalysisReportError):
        _validate_v3(report, result_jsonl, packet_report)


@pytest.mark.parametrize("state", ["corroborated", "disputed"])
def test_analysis_report_v3_rejects_legacy_verification_states(state: str) -> None:
    report, result_jsonl, packet_report = _analysis_report_v3()
    report["semantic_diagnostics"][0]["verification_state"] = state
    with pytest.raises(AnalysisReportError, match="verification_state"):
        _validate_v3(report, result_jsonl, packet_report)
