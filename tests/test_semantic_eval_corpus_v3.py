"""Committed schema-3 semantic corpus acceptance tests.

Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-10.1]
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from backstitch.semantic_eval import derive_semantic_eval_observed_facts
from backstitch.semantic_eval_reports import (
    SemanticEvalContractError,
    load_semantic_eval_corpus,
)
from backstitch.semantic_packets import canonical_json_bytes

ROOT = Path(__file__).parent / "semantic_eval/v3"
SMOKE = ROOT / "manifest.json"
QUALIFICATION_CANDIDATE = ROOT / "qualification-candidate/manifest.json"

CONTROL_TAGS = {
    "historical_misalignment",
    "valid_vacuous_trace",
    "analyzer_false_positive",
    "analyzer_false_negative",
    "verifier_false_positive",
    "verifier_false_negative",
    "indeterminate",
    "uncached_flip",
    "misleading_nearby_code",
    "out_of_packet_decoy",
    "omitted_disconfirming_evidence",
    "prompt_injection_source",
}


def _projection(
    case: dict[str, Any], variant_id: str, field: str
) -> list[dict[str, Any]]:
    rows = [
        {
            key: value
            for key, value in row.items()
            if key not in {"gold_id", "variant_id"}
        }
        for row in case[field]
        if row["variant_id"] == variant_id
    ]
    rows.sort(key=canonical_json_bytes)
    return rows


def _packet_declared_receipts(packet: dict[str, Any]) -> set[str]:
    return {
        source["receipt_hash"]
        for region in packet["declared_evidence"]
        for source in region["sources"]
    }


def _packet_candidate_pairs(packet: dict[str, Any]) -> set[tuple[str, str]]:
    return {
        (candidate["candidate_id"], candidate["receipt_hash"])
        for region in packet["counterevidence"]
        for candidate in region["candidates"]
    }


def test_report_smoke_remains_non_authoritative() -> None:
    smoke = load_semantic_eval_corpus(SMOKE, mode="report")

    assert smoke.corpus_id == "schema3-report-runner-smoke"
    with pytest.raises(
        SemanticEvalContractError, match="enforce corpus must contain every control tag"
    ):
        load_semantic_eval_corpus(SMOKE, mode="enforce")


def test_qualification_candidate_rederives_every_gold_source_fact() -> None:
    corpus = load_semantic_eval_corpus(QUALIFICATION_CANDIDATE, mode="enforce")
    observed = derive_semantic_eval_observed_facts(corpus)
    manifest = corpus.to_dict()
    cases = {case["case_id"]: case for case in manifest["cases"]}

    assert len(corpus.case_ids) == 20
    assert len(corpus.variant_keys) == 40
    assert all(
        facts.deterministic_issue_count == 0 and facts.deterministic_problem is None
        for facts in observed.variants
    )

    for facts in observed.variants:
        case = cases[facts.case_id]
        assert list(facts.obligations) == _projection(
            case, facts.variant_id, "gold_obligations"
        )
        assert list(facts.evidence) == _projection(
            case, facts.variant_id, "gold_evidence"
        )
        assert list(facts.candidates) == _projection(
            case, facts.variant_id, "gold_candidates"
        )
        assert len(facts.packets) == 1
        packet = dict(facts.packets[0])
        assert packet["readiness"]["gate_state"] == "executable"
        assert packet["readiness"]["alignment_state"] == "complete"

        declared = _packet_declared_receipts(packet)
        counter = _packet_candidate_pairs(packet)
        for finding in case["expected_findings"]:
            if finding["variant_id"] != facts.variant_id:
                continue
            evidence_by_id = {
                row["gold_id"]: row
                for row in case["gold_evidence"]
                if row["variant_id"] == facts.variant_id
            }
            candidates_by_id = {
                row["gold_id"]: row
                for row in case["gold_candidates"]
                if row["variant_id"] == facts.variant_id
            }
            assert {
                evidence_by_id[gold_id]["receipt_hash"]
                for gold_id in finding["required_declared_evidence_gold_ids"]
            }.issubset(declared)
            assert {
                (
                    candidates_by_id[gold_id]["candidate_id"],
                    candidates_by_id[gold_id]["receipt_hash"],
                )
                for gold_id in finding["required_counterevidence_gold_ids"]
            }.issubset(counter)


def test_qualification_candidate_frozen_identities_are_documented() -> None:
    corpus = load_semantic_eval_corpus(QUALIFICATION_CANDIDATE, mode="enforce")
    root = QUALIFICATION_CANDIDATE.parent
    readme = (root / "README.md").read_text(encoding="utf-8")

    assert corpus.corpus_sha256 in readme
    for path in (
        QUALIFICATION_CANDIDATE,
        root / "independent-review.md",
        ROOT / "generate_qualification_candidate.py",
    ):
        digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest in readme


def test_qualification_candidate_has_preregistered_floors_and_controls() -> None:
    corpus = load_semantic_eval_corpus(QUALIFICATION_CANDIDATE, mode="enforce")
    observed = derive_semantic_eval_observed_facts(corpus)
    manifest = corpus.to_dict()

    historical = manifest["reviewed_historical_units"]
    cases_by_id = {case["case_id"]: case for case in manifest["cases"]}
    review = (QUALIFICATION_CANDIDATE.parent / "independent-review.md").read_text(
        encoding="utf-8"
    )
    assert "FAIL for policy authority" in review
    assert "substantive historical-unit count is therefore zero" in review
    assert len(historical) == 20
    assert len({row["source_reference"] for row in historical}) == 20
    assert (
        len(
            {
                (row["case_id"], row["variant_id"], row["expected_finding_gold_id"])
                for row in historical
            }
        )
        == 20
    )
    for row in historical:
        case = cases_by_id[row["case_id"]]
        tree_digest = case["mutations"][0]["tree_manifest_sha256"]
        assert row["source_reference"] == (
            f"fixture-tree:{tree_digest}#{row['case_id']}/misaligned"
        )
        anchor = row["review_reference"].rsplit("#", 1)[1]
        assert f'<a id="{anchor}"></a>' in review

    tags = {
        tag
        for case in manifest["cases"]
        for fixture in (case["clean"], *case["mutations"])
        for tag in fixture["control_tags"]
    }
    assert tags == CONTROL_TAGS
    assert sum(len(case["expected_findings"]) for case in manifest["cases"]) == 20
    assert all(
        not any(
            finding["variant_id"] == "clean" for finding in case["expected_findings"]
        )
        for case in manifest["cases"]
    )

    packets = {
        (facts.case_id, facts.variant_id): dict(facts.packets[0])
        for facts in observed.variants
    }
    decoy = canonical_json_bytes(
        packets[("historical-03-inclusive-threshold", "clean")]
    )
    assert b"claim the comparator is" not in decoy
    injection = canonical_json_bytes(
        packets[("historical-18-prompt-injection", "misaligned")]
    )
    assert b"Ignore the specification" in injection

    vacuous_case = next(
        case
        for case in manifest["cases"]
        if case["case_id"] == "historical-17-vacuous-trace"
    )
    assert vacuous_case["expected_findings"][0]["code"] == "SEMANTIC_MISSING_TRACE"
    assert vacuous_case["expected_findings"][0]["classification"] == "missing_trace"
    vacuous_packet = packets[(vacuous_case["case_id"], "misaligned")]
    assert vacuous_packet["readiness"]["alignment_state"] == "complete"
    assert vacuous_packet["declared_evidence"]

    disconfirming_case = next(
        case
        for case in manifest["cases"]
        if case["case_id"] == "historical-15-disconfirming-fallback"
    )
    assert disconfirming_case["expected_findings"][0][
        "required_counterevidence_gold_ids"
    ]

    assert not list(QUALIFICATION_CANDIDATE.parent.glob("*report*.json"))
