"""Blinded verifier claim, request, identity, normalization, and aggregation.

Spec: docs/specs/06-semantic-gates.md [SEM-4], [SEM-10]
"""

from __future__ import annotations

import hashlib
import inspect
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from backstitch.semantic_cache import (
    ProviderAdapter,
    ProviderCallResult,
    SemanticProvenance,
    VerificationWork,
    inspect_verification_cache,
    verify_with_cache,
)
from backstitch.semantic_evidence import CanonicalSemanticResult, normalize_model_result
from backstitch.semantic_identity import (
    CompositionIdentity,
    ProviderIdentity,
    RequestIdentity,
    build_composition_identity,
)
from backstitch.semantic_packets import canonical_json_bytes, semantic_packet_hash
from backstitch.semantic_verification import (
    VerificationClaim,
    VerificationContractError,
    VerificationRequest,
    VerifyIdentity,
    aggregate_verification_results,
    build_verification_request,
    build_verify_identity,
    derive_verification_claim,
    load_canonical_verification_result,
    normalize_verifier_response,
    verification_prompt_bytes,
    verification_response_schema,
    verification_response_schema_from_prompt,
    verifier_request_bytes,
)

PROVIDER = ProviderIdentity(
    backend_id="llm",
    plugin_id="test-plugin",
    model_id="test-model",
    model_revision="rev-1",
    adapter_id="backstitch.test",
    adapter_version=1,
    llm_distribution_version="1.0",
    plugin_distribution_name="test-plugin-dist",
    plugin_distribution_version="2.0",
)
REQUEST = RequestIdentity("require", 0.0, 42, 512)
PROVENANCE = SemanticProvenance(
    adapter_id=PROVIDER.adapter_id,
    adapter_version=PROVIDER.adapter_version,
    plugin_version=PROVIDER.plugin_distribution_version,
    model_class="tests.Verifier",
    provider_model_id=PROVIDER.model_id,
    provider_model_revision=PROVIDER.model_revision,
    response_id="verify-response",
    input_tokens=10,
    output_tokens=5,
)


def _packet() -> dict[str, Any]:
    row: dict[str, Any] = {
        "schema_version": 3,
        "packet_id": "docs/specs/core.md#CORE-1",
        "packet_hash": "",
        "kind": "section",
        "obligation_id": "docs/specs/core.md#CORE-1",
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
            "path": "docs/specs/core.md",
            "identity": "CORE-1",
            "title": "Core",
            "start_line": 3,
            "end_line": 3,
            "text": "Must return one.",
        },
        "declared_evidence": [
            {
                "role": "implementation",
                "path": "pkg/core.py",
                "symbol": "run",
                "start_line": 8,
                "end_line": 9,
                "snippet": "def run():\n    return 2",
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
        "counterevidence": [
            {
                "role": "counterevidence",
                "path": "pkg/decoy.py",
                "start_line": 4,
                "end_line": 4,
                "snippet": "return 1",
                "candidates": [
                    {
                        "candidate_id": "candidate:sha256:" + "5" * 64,
                        "candidate_kind": "implementation_definition",
                        "receipt_hash": "6" * 64,
                        "trace_state": "untraced",
                        "discovery_bases": ["lexical_match"],
                        "relation_kinds": [],
                    }
                ],
            }
        ],
        "trace_summary": {
            "declared_counts": [],
            "candidate_counts": [],
            "relation_counts": [],
        },
        "evidence_regions": [
            {
                "role": "requirement",
                "path": "docs/specs/core.md",
                "start_line": 3,
                "end_line": 3,
            },
            {
                "role": "implementation",
                "path": "pkg/core.py",
                "start_line": 8,
                "end_line": 9,
            },
            {
                "role": "counterevidence",
                "path": "pkg/decoy.py",
                "start_line": 4,
                "end_line": 4,
            },
        ],
        "issues": [],
        "packet_warnings": [],
    }
    row["packet_hash"] = semantic_packet_hash(row)
    return row


def _suppression_packet() -> dict[str, Any]:
    row: dict[str, Any] = {
        "schema_version": 4,
        "packet_id": "suppression::docs/specs/core.md#SUP-GEN",
        "packet_hash": "",
        "kind": "suppression",
        "obligation_id": "suppression::docs/specs/core.md#SUP-GEN",
        "requirement": {
            "role": "requirement",
            "path": "docs/specs/core.md",
            "identity": "SUP-GEN",
            "title": "Generated code",
            "start_line": 40,
            "end_line": 40,
            "text": "Generated output has no stable reciprocal source location.",
        },
        "suppression_rules": [
            {
                "mechanism": "config",
                "path": "generated/**",
                "sections": [],
                "codes": ["CODE_X"],
                "declaration": "docs/specs/core.md#SUP-GEN",
                "origin": {"source": ".backstitch.toml", "position": 0},
            }
        ],
        "counterevidence": [
            {
                "role": "counterevidence",
                "path": "generated/x.py",
                "start_line": 2,
                "end_line": 2,
                "snippet": "dangerous_call()",
                "issue_indexes": [0],
            }
        ],
        "evidence_regions": [
            {
                "role": "requirement",
                "path": "docs/specs/core.md",
                "start_line": 40,
                "end_line": 40,
            },
            {
                "role": "counterevidence",
                "path": "generated/x.py",
                "start_line": 2,
                "end_line": 2,
            },
        ],
        "issues": [],
        "packet_warnings": [],
    }
    row["packet_hash"] = semantic_packet_hash(row)
    return row


def _finding(packet: dict[str, Any]) -> CanonicalSemanticResult:
    return normalize_model_result(
        packet,
        {
            "packet_id": packet["packet_id"],
            "classification": "confirmed_mismatch",
            "confidence": 0.9,
            "rationale": "This rationale must be blinded.",
            "summary": "Implementation returns two, not one.",
            "evidence": packet["evidence_regions"][:2],
        },
        analysis_key="7" * 64,
    )


@pytest.mark.parametrize(
    ("classification", "code"),
    [
        (
            "rationale_insufficient",
            "SEMANTIC_SUPPRESSION_RATIONALE_INSUFFICIENT",
        ),
        ("scope_overbroad", "SEMANTIC_SUPPRESSION_SCOPE_OVERBROAD"),
        ("risk_unaddressed", "SEMANTIC_SUPPRESSION_RISK_UNADDRESSED"),
    ],
)
def test_verifier_claim_admits_each_suppression_finding(
    classification: str,
    code: str,
) -> None:
    packet = _suppression_packet()
    evidence = [
        {
            "role": "requirement",
            "path": "docs/specs/core.md",
            "start_line": 40,
            "end_line": 40,
        }
    ]
    if classification != "rationale_insufficient":
        evidence.append(
            {
                "role": "counterevidence",
                "path": "generated/x.py",
                "start_line": 2,
                "end_line": 2,
            }
        )
    result = normalize_model_result(
        packet,
        {
            "packet_id": packet["packet_id"],
            "classification": classification,
            "confidence": 0.8,
            "rationale": "The shown issue is not justified by the declaration.",
            "summary": "Suppression needs review.",
            "evidence": evidence,
        },
        analysis_key="a" * 64,
    )

    claim = derive_verification_claim(packet, result)

    assert claim.value["kind"] == "suppression"
    assert claim.value["code"] == code


def _contracts() -> tuple[
    dict[str, Any], VerificationClaim, VerificationRequest, VerifyIdentity
]:
    packet = _packet()
    claim = derive_verification_claim(packet, _finding(packet))
    request = build_verification_request(packet, claim)
    identity = build_verify_identity(
        request,
        claim,
        PROVIDER,
        REQUEST,
        base_search_epoch="1",
    )
    return packet, claim, request, identity


def _response(
    packet: dict[str, Any], claim: VerificationClaim, verdict: str, score: float
) -> dict[str, Any]:
    return {
        "packet_id": packet["packet_id"],
        "claim_hash": claim.claim_hash,
        "verdict": verdict,
        "support_score": score,
        "summary": "The bounded evidence was adversarially reviewed.",
        "evidence": [packet["evidence_regions"][1]],
    }


def test_claim_and_verifier_request_are_reason_free_and_byte_closed() -> None:
    packet, claim, request, _ = _contracts()

    assert claim.value["statement"] == "Implementation returns two, not one."
    assert "rationale" not in canonical_json_bytes(claim.value).decode("utf-8")
    assert "confidence" not in claim.value
    assert (
        claim.claim_hash
        == hashlib.sha256(canonical_json_bytes(claim.value)).hexdigest()
    )
    assert request.value == {
        "verify_contract_version": 3,
        "packet": request.value["packet"],
        "claim": claim.value,
    }
    assert (
        request.verifier_packet_hash
        == hashlib.sha256(canonical_json_bytes(request.value)).hexdigest()
    )
    assert verifier_request_bytes(request) == (
        verification_prompt_bytes() + b"\n" + canonical_json_bytes(request.value)
    )
    assert packet["source_snapshot"][
        "snapshot_hash"
    ].encode() not in verifier_request_bytes(request)


def test_verify_identity_is_separate_and_epoch_bound() -> None:
    _, claim, request, identity = _contracts()
    other = build_verify_identity(
        request,
        claim,
        PROVIDER,
        REQUEST,
        base_search_epoch="1",
        effective_search_epoch="eval-verify:abc",
    )

    assert identity.verify_key != other.verify_key
    assert identity.contract["effective_search_epoch"] == "1"
    assert other.contract["base_search_epoch"] == "1"
    with pytest.raises(VerificationContractError, match="effective_search_epoch"):
        build_verify_identity(
            request,
            claim,
            PROVIDER,
            REQUEST,
            base_search_epoch="1",
            effective_search_epoch="",
        )


def test_claim_request_and_identity_are_immutable_canonical_values() -> None:
    _, claim, request, identity = _contracts()
    original_claim = claim.value
    original_request = request.value
    original_contract = identity.contract

    claim.value["statement"] = "forged"
    request.value["claim"]["statement"] = "forged"
    identity.contract["claim_hash"] = "0" * 64

    assert claim.value == original_claim
    assert request.value == original_request
    assert identity.contract == original_contract


def test_normalization_rejects_mismatched_claim_request_identity_tuple() -> None:
    packet, claim, request, identity = _contracts()
    second_finding = replace(
        _finding(packet), summary="A different normalized statement."
    )
    second_claim = derive_verification_claim(packet, second_finding)
    second_request = build_verification_request(packet, second_claim)
    response = _response(packet, second_claim, "support", 0.95)

    with pytest.raises(VerificationContractError, match="links mismatch"):
        normalize_verifier_response(
            packet, second_claim, second_request, identity, response
        )


def test_claim_reconstructs_analyzer_evidence_from_packet() -> None:
    packet = _packet()
    finding = _finding(packet)
    forged_evidence = list(finding.evidence)
    forged_evidence[0] = replace(
        forged_evidence[0], path="outside.py", excerpt_sha256="0" * 64
    )
    forged = replace(finding, evidence=tuple(forged_evidence))

    with pytest.raises(VerificationContractError, match="packet-bound"):
        derive_verification_claim(packet, forged)


@pytest.mark.parametrize(
    ("verdict", "score"),
    [("support", 0.95), ("refute", 0.1), ("indeterminate", 0.5)],
)
def test_verifier_response_normalizes_closed_bound_evidence(
    verdict: str, score: float
) -> None:
    packet, claim, request, identity = _contracts()
    response = _response(packet, claim, verdict, score)
    if verdict == "indeterminate":
        response["evidence"] = []

    result = normalize_verifier_response(packet, claim, request, identity, response)

    assert result.verdict == verdict
    assert result.to_row()["schema_version"] == 1
    assert (
        load_canonical_verification_result(
            packet, claim, request, identity, result.to_row()
        )
        == result
    )


@pytest.mark.parametrize("verdict", ["support", "refute"])
def test_support_and_refute_require_bound_evidence(verdict: str) -> None:
    packet, claim, request, identity = _contracts()
    response = _response(packet, claim, verdict, 0.5)
    response["evidence"] = []

    with pytest.raises(VerificationContractError, match="requires bound evidence"):
        normalize_verifier_response(packet, claim, request, identity, response)


@pytest.mark.parametrize("score", [float("nan"), float("inf"), -0.1, 1.1, True])
def test_verifier_score_is_finite_and_bounded(score: object) -> None:
    packet, claim, request, identity = _contracts()
    response = _response(packet, claim, "indeterminate", 0.5)
    response["support_score"] = score
    response["evidence"] = []

    with pytest.raises(VerificationContractError, match="support_score"):
        normalize_verifier_response(packet, claim, request, identity, response)


@pytest.mark.parametrize(
    ("verdicts", "scores", "state", "context"),
    [
        (
            ("support", "support"),
            (0.9, 1.0),
            "independently_verified",
            "independently_verified",
        ),
        (("support", "refute"), (1.0, 0.0), "disputed", "disputed_by_verifier"),
        (
            ("support", "support"),
            (1.0, 0.89),
            "verification_indeterminate",
            "verification_indeterminate",
        ),
        (
            ("support", "indeterminate"),
            (1.0, 0.5),
            "verification_indeterminate",
            "verification_indeterminate",
        ),
    ],
)
def test_aggregation_is_conservative(
    verdicts: tuple[str, str],
    scores: tuple[float, float],
    state: str,
    context: str,
) -> None:
    packet, claim, request, _ = _contracts()
    pairs = (("a", "a"), ("b", "b"))
    results = []
    identities = []
    for (base, effective), verdict, score in zip(pairs, verdicts, scores, strict=True):
        identity = build_verify_identity(
            request,
            claim,
            PROVIDER,
            REQUEST,
            base_search_epoch=base,
            effective_search_epoch=effective,
        )
        identities.append(identity)
        response = _response(packet, claim, verdict, score)
        if verdict == "indeterminate":
            response["evidence"] = []
        results.append(
            normalize_verifier_response(packet, claim, request, identity, response)
        )

    aggregate = aggregate_verification_results(
        packet,
        claim,
        request,
        required_epochs=pairs,
        identities=identities,
        results=results,
        minimum_support_score=0.9,
    )

    assert aggregate.aggregate_state == state
    assert aggregate.context == context
    assert aggregate.event["aggregate_state"] == state
    with pytest.raises(VerificationContractError, match="identity mismatch"):
        aggregate_verification_results(
            packet,
            claim,
            request,
            required_epochs=pairs,
            identities=tuple(reversed(identities)),
            results=results,
            minimum_support_score=0.9,
        )


def test_verifier_schema_closes_identity_verdict_score_and_regions() -> None:
    packet, claim, request, _ = _contracts()
    schema = cast(dict[str, Any], verification_response_schema(packet, claim))

    assert schema["additionalProperties"] is False
    assert schema["properties"]["packet_id"] == {"const": packet["packet_id"]}
    assert schema["properties"]["claim_hash"] == {"const": claim.claim_hash}
    assert len(schema["properties"]["evidence"]["items"]["oneOf"]) == 3
    assert schema["properties"]["evidence"]["uniqueItems"] is True
    assert schema["allOf"][0]["then"]["properties"]["evidence"] == {"minItems": 1}
    assert (
        verification_response_schema_from_prompt(
            verifier_request_bytes(request).decode("utf-8")
        )
        == schema
    )


def test_composition_identity_covers_configuration_not_packet_or_operation() -> None:
    composition = build_composition_identity(
        PROVIDER,
        REQUEST,
        analysis_search_epoch="analyze-1",
        verify_provider=PROVIDER,
        verify_request=REQUEST,
        verify_search_epochs=("v1", "v2"),
        required_verdicts=2,
        minimum_support_score=0.9,
        indeterminate="report",
    )
    same = build_composition_identity(
        PROVIDER,
        REQUEST,
        analysis_search_epoch="analyze-1",
        verify_provider=PROVIDER,
        verify_request=REQUEST,
        verify_search_epochs=("v1", "v2"),
        required_verdicts=2,
        minimum_support_score=0.9,
        indeterminate="report",
    )
    changed = build_composition_identity(
        PROVIDER,
        REQUEST,
        analysis_search_epoch="analyze-1",
        verify_provider=replace(PROVIDER, model_revision="rev-2"),
        verify_request=REQUEST,
        verify_search_epochs=("v1", "v2"),
        required_verdicts=2,
        minimum_support_score=0.9,
        indeterminate="report",
    )

    assert composition == same
    assert composition.composition_sha256 != changed.composition_sha256
    assert [item["kind"] for item in composition.analysis_composition["prompts"]] == [
        "section",
        "invariant",
    ]
    original = composition.analysis_composition
    composition.analysis_composition["base_search_epoch"] = "forged"
    composition.verify_composition["minimum_support_score"] = 0.0
    assert composition.analysis_composition == original


@pytest.mark.parametrize("version", [True, 0, -1, "1"])
def test_composition_rejects_invalid_analysis_contract_version(version: object) -> None:
    with pytest.raises(ValueError, match="analysis_contract_version"):
        build_composition_identity(
            PROVIDER,
            REQUEST,
            analysis_search_epoch="analyze-1",
            verify_provider=PROVIDER,
            verify_request=REQUEST,
            verify_search_epochs=("v1",),
            required_verdicts=1,
            minimum_support_score=0.9,
            indeterminate="report",
            analysis_contract_version=cast(int, version),
        )


def test_every_provider_and_request_composition_field_invalidates_its_side() -> None:
    def build(
        analysis_provider: ProviderIdentity = PROVIDER,
        analysis_request: RequestIdentity = REQUEST,
        verify_provider: ProviderIdentity = PROVIDER,
        verify_request: RequestIdentity = REQUEST,
    ) -> CompositionIdentity:
        return build_composition_identity(
            analysis_provider,
            analysis_request,
            analysis_search_epoch="a1",
            verify_provider=verify_provider,
            verify_request=verify_request,
            verify_search_epochs=("v1",),
            required_verdicts=1,
            minimum_support_score=0.9,
            indeterminate="report",
        )

    baseline = build()
    for field in PROVIDER.__dataclass_fields__:
        current = getattr(PROVIDER, field)
        changed_value = (
            current + "-changed" if isinstance(current, str) else current + 1
        )
        if field == "adapter_version":
            changed_provider = replace(
                PROVIDER, adapter_version=cast(int, changed_value)
            )
        elif field == "backend_id":
            changed_provider = replace(PROVIDER, backend_id=cast(str, changed_value))
        elif field == "plugin_id":
            changed_provider = replace(PROVIDER, plugin_id=cast(str, changed_value))
        elif field == "model_id":
            changed_provider = replace(PROVIDER, model_id=cast(str, changed_value))
        elif field == "model_revision":
            changed_provider = replace(
                PROVIDER, model_revision=cast(str, changed_value)
            )
        elif field == "adapter_id":
            changed_provider = replace(PROVIDER, adapter_id=cast(str, changed_value))
        elif field == "llm_distribution_version":
            changed_provider = replace(
                PROVIDER, llm_distribution_version=cast(str, changed_value)
            )
        elif field == "plugin_distribution_name":
            changed_provider = replace(
                PROVIDER, plugin_distribution_name=cast(str, changed_value)
            )
        else:
            assert field == "plugin_distribution_version"
            changed_provider = replace(
                PROVIDER, plugin_distribution_version=cast(str, changed_value)
            )
        analysis_changed = build(analysis_provider=changed_provider)
        verify_changed = build(verify_provider=changed_provider)
        assert (
            analysis_changed.analysis_composition_sha256
            != baseline.analysis_composition_sha256
        )
        assert (
            analysis_changed.verify_composition_sha256
            == baseline.verify_composition_sha256
        )
        assert (
            verify_changed.verify_composition_sha256
            != baseline.verify_composition_sha256
        )
        assert (
            verify_changed.analysis_composition_sha256
            == baseline.analysis_composition_sha256
        )

    request_variants = (
        replace(REQUEST, json_mode="off"),
        replace(REQUEST, temperature=0.1),
        replace(REQUEST, seed=43),
        replace(REQUEST, max_tokens=513),
    )
    for changed_request in request_variants:
        assert (
            build(analysis_request=changed_request).analysis_composition_sha256
            != baseline.analysis_composition_sha256
        )
        assert (
            build(verify_request=changed_request).verify_composition_sha256
            != baseline.verify_composition_sha256
        )


def test_composition_epoch_threshold_and_aggregation_fields_invalidate_exact_side() -> (
    None
):
    baseline = build_composition_identity(
        PROVIDER,
        REQUEST,
        analysis_search_epoch="a1",
        verify_provider=PROVIDER,
        verify_request=REQUEST,
        verify_search_epochs=("v1",),
        required_verdicts=1,
        minimum_support_score=0.9,
        indeterminate="report",
    )
    analysis_changed = build_composition_identity(
        PROVIDER,
        REQUEST,
        analysis_search_epoch="a2",
        verify_provider=PROVIDER,
        verify_request=REQUEST,
        verify_search_epochs=("v1",),
        required_verdicts=1,
        minimum_support_score=0.9,
        indeterminate="report",
        analysis_contract_version=2,
    )
    assert (
        analysis_changed.analysis_composition_sha256
        != baseline.analysis_composition_sha256
    )
    assert (
        analysis_changed.verify_composition_sha256 == baseline.verify_composition_sha256
    )

    for epochs, verdicts, score, indeterminate in (
        (("v2",), 1, 0.9, "report"),
        (("v1", "v2"), 2, 0.9, "report"),
        (("v1",), 1, 0.8, "report"),
        (("v1",), 1, 0.9, "allow"),
    ):
        changed = build_composition_identity(
            PROVIDER,
            REQUEST,
            analysis_search_epoch="a1",
            verify_provider=PROVIDER,
            verify_request=REQUEST,
            verify_search_epochs=epochs,
            required_verdicts=verdicts,
            minimum_support_score=score,
            indeterminate=indeterminate,
        )
        assert changed.verify_composition_sha256 != baseline.verify_composition_sha256
        assert (
            changed.analysis_composition_sha256 == baseline.analysis_composition_sha256
        )


def test_prompt_descriptors_invalidate_only_their_composition_side(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backstitch.semantic_packets as packet_module
    import backstitch.semantic_verification_contract as verify_contract

    def build() -> CompositionIdentity:
        return build_composition_identity(
            PROVIDER,
            REQUEST,
            analysis_search_epoch="a1",
            verify_provider=PROVIDER,
            verify_request=REQUEST,
            verify_search_epochs=("v1",),
            required_verdicts=1,
            minimum_support_score=0.9,
            indeterminate="report",
        )

    baseline = build()
    section = packet_module._PROMPTS["section"]
    monkeypatch.setitem(
        packet_module._PROMPTS, "section", (section[0] + ".changed", *section[1:])
    )
    analysis_changed = build()
    assert (
        analysis_changed.analysis_composition_sha256
        != baseline.analysis_composition_sha256
    )
    assert (
        analysis_changed.verify_composition_sha256 == baseline.verify_composition_sha256
    )

    monkeypatch.setattr(
        verify_contract,
        "VERIFY_PROMPT_VERSION",
        verify_contract.VERIFY_PROMPT_VERSION + 1,
    )
    verify_changed = build()
    assert (
        verify_changed.verify_composition_sha256
        != analysis_changed.verify_composition_sha256
    )
    assert (
        verify_changed.analysis_composition_sha256
        == analysis_changed.analysis_composition_sha256
    )


def test_composition_builder_has_no_packet_trial_path_cache_policy_or_cost_inputs() -> (
    None
):
    assert set(inspect.signature(build_composition_identity).parameters) == {
        "analysis_provider",
        "analysis_request",
        "analysis_search_epoch",
        "verify_provider",
        "verify_request",
        "verify_search_epochs",
        "required_verdicts",
        "minimum_support_score",
        "indeterminate",
        "analysis_contract_version",
    }


def _work() -> tuple[VerificationWork, dict[str, Any]]:
    packet, claim, request, identity = _contracts()
    response = _response(packet, claim, "support", 0.95)
    return (
        VerificationWork(packet, claim, request, identity, "1", "1"),
        response,
    )


def test_verifier_cache_miss_hit_and_require_replay(tmp_path: Path) -> None:
    work, response = _work()
    constructions = 0
    calls = 0

    def factory() -> ProviderAdapter:
        nonlocal constructions
        constructions += 1

        def adapter(prompt: str) -> ProviderCallResult:
            nonlocal calls
            calls += 1
            assert prompt.endswith(canonical_json_bytes(work.request.value).decode())
            return ProviderCallResult(json.dumps(response), PROVENANCE)

        return adapter

    first = verify_with_cache(
        work_items=(work,),
        cache_path=tmp_path / "cache",
        cache_mode="read-write",
        provider_identity=PROVIDER,
        request_identity=REQUEST,
        adapter_factory=factory,
        lock_wait_timeout_seconds=1,
    )
    second = verify_with_cache(
        work_items=(work,),
        cache_path=tmp_path / "cache",
        cache_mode="read-write",
        provider_identity=PROVIDER,
        request_identity=REQUEST,
        adapter_factory=factory,
        lock_wait_timeout_seconds=1,
    )
    replay = verify_with_cache(
        work_items=(work,),
        cache_path=tmp_path / "cache",
        cache_mode="require",
        provider_identity=PROVIDER,
        request_identity=REQUEST,
        adapter_factory=None,
        lock_wait_timeout_seconds=1,
    )

    assert first.problems == second.problems == replay.problems == ()
    assert (first.cache_hits, first.cache_misses, first.provider_calls) == (0, 1, 1)
    assert (second.cache_hits, second.cache_misses, second.provider_calls) == (1, 0, 0)
    assert (replay.cache_hits, replay.cache_misses, replay.provider_calls) == (1, 0, 0)
    assert [item.to_row() for item in first.results] == [
        item.to_row() for item in replay.results
    ]
    assert constructions == calls == 1


def test_verifier_cache_inspection_is_read_only_and_revalidates_hits(
    tmp_path: Path,
) -> None:
    work, response = _work()
    cache = tmp_path / "cache"
    missing = inspect_verification_cache(
        work_items=(work,),
        cache_path=cache,
        cache_mode="read-write",
        provider_identity=PROVIDER,
        request_identity=REQUEST,
    )
    assert missing.problems == ()
    assert (missing.planned_hits, missing.planned_misses) == (0, 1)
    assert not cache.exists()

    def factory() -> ProviderAdapter:
        return lambda prompt: ProviderCallResult(json.dumps(response), PROVENANCE)

    populated = verify_with_cache(
        work_items=(work,),
        cache_path=cache,
        cache_mode="read-write",
        provider_identity=PROVIDER,
        request_identity=REQUEST,
        adapter_factory=factory,
        lock_wait_timeout_seconds=1,
    )
    assert not populated.problems
    hit = inspect_verification_cache(
        work_items=(work,),
        cache_path=cache,
        cache_mode="require",
        provider_identity=PROVIDER,
        request_identity=REQUEST,
    )
    assert hit.problems == ()
    assert (hit.planned_hits, hit.planned_misses) == (1, 0)
    assert hit.planned_miss_verify_keys == ()


def test_verifier_single_flight_calls_provider_once(tmp_path: Path) -> None:
    work, response = _work()
    calls = 0
    call_entered = threading.Event()
    release = threading.Event()

    def factory() -> ProviderAdapter:
        def adapter(prompt: str) -> ProviderCallResult:
            nonlocal calls
            calls += 1
            call_entered.set()
            assert release.wait(2)
            return ProviderCallResult(json.dumps(response), PROVENANCE)

        return adapter

    runs = []

    def run() -> None:
        runs.append(
            verify_with_cache(
                work_items=(work,),
                cache_path=tmp_path / "cache",
                cache_mode="read-write",
                provider_identity=PROVIDER,
                request_identity=REQUEST,
                adapter_factory=factory,
                lock_wait_timeout_seconds=2,
                poll_interval_seconds=0.01,
            )
        )

    first = threading.Thread(target=run)
    second = threading.Thread(target=run)
    first.start()
    assert call_entered.wait(1)
    second.start()
    time.sleep(0.05)
    release.set()
    first.join(2)
    second.join(2)

    assert calls == 1
    assert len(runs) == 2
    assert all(not item.problems for item in runs)
    assert sorted(item.cache_hits for item in runs) == [0, 1]


def _remove_populated_verify_result(
    cache_path: Path,
) -> tuple[VerificationWork, bytes, tuple[dict[str, Any], ...]]:
    work, response = _work()

    def factory() -> ProviderAdapter:
        return lambda _prompt: ProviderCallResult(json.dumps(response), PROVENANCE)

    populated = verify_with_cache(
        work_items=(work,),
        cache_path=cache_path,
        cache_mode="read-write",
        provider_identity=PROVIDER,
        request_identity=REQUEST,
        adapter_factory=factory,
        lock_wait_timeout_seconds=1,
    )
    assert populated.problems == ()
    result_path = cache_path / "verify-results" / f"{work.identity.verify_key}.json"
    result_bytes = result_path.read_bytes()
    result_path.unlink()
    return work, result_bytes, tuple(item.to_row() for item in populated.results)


def test_verifier_wait_loop_timeout_serves_published_identical_result(
    tmp_path: Path,
) -> None:
    """Slice 7.0 pin for the wait-loop verifier contention route."""

    import backstitch.semantic_cache as semantic_cache

    cache_path = (tmp_path / "cache").resolve()
    work, result_bytes, expected_rows = _remove_populated_verify_result(cache_path)
    lock_path = cache_path / "verify-locks" / f"{work.identity.verify_key}.lock"
    lock_path.write_bytes(
        semantic_cache._new_owned_lock(work.identity.verify_key, "verify")
    )
    result_path = cache_path / "verify-results" / f"{work.identity.verify_key}.json"

    with semantic_cache._verify_guard(
        cache_path,
        work.identity.verify_key,
        timeout_seconds=1,
        poll_interval_seconds=0.01,
    ):
        with ThreadPoolExecutor(max_workers=1) as pool:
            coordinator = semantic_cache._OwnershipCoordinator(
                cache_path=cache_path,
                key=work.identity.verify_key,
                lock_kind="verify",
                result_path=result_path,
                lock_path=lock_path,
                timeout_seconds=0.05,
                poll_interval_seconds=0.01,
                load_result=lambda: semantic_cache._load_verify_hit(
                    cache_path, work, PROVIDER
                ),
                read_lock=lambda: semantic_cache._read_verify_lock(
                    lock_path, work.identity.verify_key
                ),
                remove_lock=lambda expected: semantic_cache._remove_verify_lock(
                    lock_path, work.identity.verify_key, expected
                ),
                wait_error="timed out waiting for verifier cache owner",
                ownership_name="verification lock",
            )
            future = pool.submit(
                coordinator.wait,
            )
            time.sleep(0.01)
            result_path.write_bytes(result_bytes)
            observed = future.result(timeout=0.2)

    assert observed.to_row() == expected_rows[0]


def test_verifier_initial_guard_timeout_serves_published_identical_result(
    tmp_path: Path,
) -> None:
    """Slice 7.0 pin for the initial guard-acquisition contention route."""

    import backstitch.semantic_cache as semantic_cache

    cache_path = (tmp_path / "cache").resolve()
    work, result_bytes, expected_rows = _remove_populated_verify_result(cache_path)
    result_path = cache_path / "verify-results" / f"{work.identity.verify_key}.json"

    with semantic_cache._verify_guard(
        cache_path,
        work.identity.verify_key,
        timeout_seconds=1,
        poll_interval_seconds=0.01,
    ):
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                verify_with_cache,
                work_items=(work,),
                cache_path=cache_path,
                cache_mode="read-write",
                provider_identity=PROVIDER,
                request_identity=REQUEST,
                adapter_factory=lambda: (_ for _ in ()).throw(
                    AssertionError("published-result fallback constructed adapter")
                ),
                lock_wait_timeout_seconds=0.05,
                poll_interval_seconds=0.01,
            )
            time.sleep(0.01)
            result_path.write_bytes(result_bytes)
            observed = future.result(timeout=0.2)

    assert observed.problems == ()
    assert observed.cache_hits == 1
    assert observed.cache_misses == 0
    assert observed.provider_calls == 0
    assert tuple(item.to_row() for item in observed.results) == expected_rows


def test_verifier_required_miss_and_corrupt_hit_fail_closed(tmp_path: Path) -> None:
    work, response = _work()
    missing = verify_with_cache(
        work_items=(work,),
        cache_path=tmp_path / "cache",
        cache_mode="require",
        provider_identity=PROVIDER,
        request_identity=REQUEST,
        adapter_factory=None,
        lock_wait_timeout_seconds=1,
    )
    assert missing.problems[0].code == "incomplete_result"

    def factory() -> ProviderAdapter:
        return lambda prompt: ProviderCallResult(json.dumps(response), PROVENANCE)

    populated = verify_with_cache(
        work_items=(work,),
        cache_path=tmp_path / "cache",
        cache_mode="read-write",
        provider_identity=PROVIDER,
        request_identity=REQUEST,
        adapter_factory=factory,
        lock_wait_timeout_seconds=1,
    )
    assert not populated.problems
    result_path = (
        tmp_path / "cache" / "verify-results" / f"{work.identity.verify_key}.json"
    )
    value = json.loads(result_path.read_text(encoding="utf-8"))
    value["result"]["evidence"][0]["start_line"] = 999
    value["result"]["evidence"][0]["end_line"] = 999
    result_path.write_bytes(canonical_json_bytes(value))

    corrupt = verify_with_cache(
        work_items=(work,),
        cache_path=tmp_path / "cache",
        cache_mode="require",
        provider_identity=PROVIDER,
        request_identity=REQUEST,
        adapter_factory=None,
        lock_wait_timeout_seconds=1,
    )
    assert corrupt.problems[0].code == "corrupt_cache"


@pytest.mark.parametrize(
    "mutation",
    ("provider", "request_controls", "base_epoch", "effective_epoch", "request"),
)
def test_verifier_work_is_fully_preflighted_before_side_effects(
    tmp_path: Path,
    mutation: str,
) -> None:
    work, response = _work()
    provider = PROVIDER
    request_identity = REQUEST
    if mutation == "provider":
        provider = replace(PROVIDER, model_revision="different-revision")
    elif mutation == "request_controls":
        request_identity = replace(REQUEST, max_tokens=999)
    elif mutation == "base_epoch":
        work = replace(work, base_search_epoch="different")
    elif mutation == "effective_epoch":
        work = replace(work, effective_search_epoch="different")
    else:
        _, _, other_request, _ = _contracts()
        changed = dict(other_request.value)
        changed["verify_contract_version"] = 999
        work = replace(work, request=VerificationRequest.from_value(changed))
    constructions = 0

    def factory() -> ProviderAdapter:
        nonlocal constructions
        constructions += 1
        return lambda prompt: ProviderCallResult(json.dumps(response), PROVENANCE)

    run = verify_with_cache(
        work_items=(work,),
        cache_path=tmp_path / "cache",
        cache_mode="read-write",
        provider_identity=provider,
        request_identity=request_identity,
        adapter_factory=factory,
        lock_wait_timeout_seconds=1,
    )

    assert run.results == ()
    assert run.problems[0].stage == "input"
    assert run.problems[0].code == "invalid_input"
    assert constructions == 0
    assert not (tmp_path / "cache").exists()


def test_verifier_malformed_adapter_return_is_contained(tmp_path: Path) -> None:
    work, _ = _work()

    def factory() -> ProviderAdapter:
        def malformed_adapter(prompt: str) -> ProviderCallResult:
            return cast(ProviderCallResult, "not-a-provider-result")

        return malformed_adapter

    run = verify_with_cache(
        work_items=(work,),
        cache_path=tmp_path / "unused",
        cache_mode="off",
        provider_identity=PROVIDER,
        request_identity=REQUEST,
        adapter_factory=factory,
        lock_wait_timeout_seconds=1,
    )

    assert run.results == ()
    assert run.problems[0].stage == "normalization"
    assert run.problems[0].code == "malformed_result"


def test_verifier_rechecks_whole_operation_deadline_after_provider_return(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backstitch.semantic_cache as semantic_cache

    work, response = _work()
    moments = iter((0.0, 2.0))
    monkeypatch.setattr(semantic_cache.time, "monotonic", lambda: next(moments))

    def factory() -> ProviderAdapter:
        return lambda prompt: ProviderCallResult(json.dumps(response), PROVENANCE)

    run = verify_with_cache(
        work_items=(work,),
        cache_path=tmp_path / "unused",
        cache_mode="off",
        provider_identity=PROVIDER,
        request_identity=REQUEST,
        adapter_factory=factory,
        lock_wait_timeout_seconds=10,
        runtime_deadline=1.0,
    )

    assert run.results == ()
    assert run.problems[0].stage == "budget"
    assert run.problems[0].code == "budget_exceeded"


def test_expired_verifier_deadline_precedes_required_cache_hit(tmp_path: Path) -> None:
    work, response = _work()

    def factory() -> ProviderAdapter:
        return lambda prompt: ProviderCallResult(json.dumps(response), PROVENANCE)

    populated = verify_with_cache(
        work_items=(work,),
        cache_path=tmp_path / "cache",
        cache_mode="read-write",
        provider_identity=PROVIDER,
        request_identity=REQUEST,
        adapter_factory=factory,
        lock_wait_timeout_seconds=1,
    )
    assert not populated.problems

    expired = verify_with_cache(
        work_items=(work,),
        cache_path=tmp_path / "cache",
        cache_mode="require",
        provider_identity=PROVIDER,
        request_identity=REQUEST,
        adapter_factory=None,
        lock_wait_timeout_seconds=1,
        runtime_deadline=-1.0,
    )

    assert expired.results == ()
    assert expired.cache_hits == 0
    assert expired.problems[0].stage == "budget"
    assert expired.problems[0].code == "budget_exceeded"
