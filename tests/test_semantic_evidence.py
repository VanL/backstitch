"""Semantic evidence reconstruction and result normalization.

Exercises closed model rows, canonical results, and evidence reconstruction.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest

from backstitch.semantic_evidence import SemanticResultError, normalize_model_result
from backstitch.semantic_packets import (
    semantic_packet_hash,
    semantic_packet_projection,
)


def _section_packet() -> dict[str, Any]:
    packet: dict[str, Any] = {
        "schema_version": 2,
        "packet_id": "docs/specs/01-x.md#X-1",
        "kind": "section",
        "spec_path": "docs/specs/01-x.md",
        "section_id": "X-1",
        "title": "X",
        "section_text": "## X [X-1]\n\nMust return one.",
        "section_start_line": 4,
        "owners": [
            {
                "path": "pkg/x.py",
                "symbol": "run",
                "start_line": 10,
                "snippet": "def run() -> int:\n    return 2",
            }
        ],
        "tests": [],
        "issues": [],
        "packet_warnings": [],
    }
    packet["packet_hash"] = semantic_packet_hash(packet)
    return packet


def _invariant_packet() -> dict[str, Any]:
    packet: dict[str, Any] = {
        "schema_version": 2,
        "packet_id": "invariant::INV.X.1",
        "kind": "invariant",
        "invariant_id": "INV.X.1",
        "tier": "required",
        "statement": "Must return one.",
        "declaration": {
            "kind": "code",
            "path": "pkg/x.py",
            "line": 1,
            "symbol": "run",
            "section_id": None,
            "start_line": 1,
            "end_line": 1,
            "excerpt": "Invariant: [INV.X.1] Must return one.",
        },
        "targets": [
            {
                "path": "pkg/x.py",
                "symbol": "run",
                "start_line": 10,
                "snippet": "def run() -> int:\n    return 1",
            }
        ],
        "binding_tests": [
            {
                "path": "tests/test_x.py",
                "symbol": "test_run",
                "start_line": 20,
                "snippet": "def test_run():\n    assert run() == 1",
            }
        ],
        "issues": [],
        "packet_warnings": [],
        "content_hash": "f" * 64,
    }
    packet["packet_hash"] = semantic_packet_hash(packet)
    return packet


def _suppression_packet() -> dict[str, Any]:
    packet: dict[str, Any] = {
        "schema_version": 4,
        "packet_id": "suppression::docs/specs/01-x.md#SUP-X",
        "kind": "suppression",
        "obligation_id": "suppression::docs/specs/01-x.md#SUP-X",
        "requirement": {
            "role": "requirement",
            "path": "docs/specs/01-x.md",
            "identity": "SUP-X",
            "title": "Suppression",
            "start_line": 7,
            "end_line": 7,
            "text": "The generated file cannot carry a stable source mapping.",
        },
        "suppression_rules": [
            {
                "mechanism": "config",
                "path": "generated/**",
                "sections": [],
                "codes": ["CODE_X"],
                "declaration": "docs/specs/01-x.md#SUP-X",
                "origin": {"source": ".backstitch.toml", "position": 0},
            }
        ],
        "counterevidence": [
            {
                "role": "counterevidence",
                "path": "generated/x.py",
                "start_line": 2,
                "end_line": 2,
                "snippet": "unmapped_generated_call()",
                "issue_indexes": [0],
            }
        ],
        "evidence_regions": [
            {
                "role": "requirement",
                "path": "docs/specs/01-x.md",
                "start_line": 7,
                "end_line": 7,
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
    packet["packet_hash"] = semantic_packet_hash(packet)
    return packet


def _model_response(
    packet: dict[str, Any],
    *,
    classification: str = "ok",
    evidence: list[dict[str, object]] | None = None,
    confidence: float | None = 0.5,
    rationale: str = "bounded evidence",
    summary: str = "Reviewed.",
) -> dict[str, object]:
    evidence_by_role: dict[str, list[dict[str, object]]] = {}
    for item in evidence or []:
        coordinate = dict(item)
        role = coordinate.pop("role")
        assert isinstance(role, str)
        evidence_by_role.setdefault(role, []).append(coordinate)
    return {
        "packet_id": packet["packet_id"],
        "assessment": {
            "classification": classification,
            "evidence": evidence_by_role,
        },
        "confidence": confidence,
        "rationale": rationale,
        "summary": summary,
    }


def test_model_result_rejects_wrong_packet_identity() -> None:
    packet = _section_packet()
    response = _model_response(packet)
    response["packet_id"] = "docs/specs/99-wrong.md#WRONG-1"

    with pytest.raises(SemanticResultError, match="packet_id does not match"):
        normalize_model_result(packet, response, analysis_key="a" * 64)


@pytest.mark.parametrize(
    ("packet_factory", "classification"),
    [
        (_section_packet, "weak_binding"),
        (_invariant_packet, "missing_trace"),
    ],
)
def test_model_result_rejects_classification_from_another_packet_kind(
    packet_factory: Any,
    classification: str,
) -> None:
    packet = packet_factory()

    with pytest.raises(SemanticResultError, match="invalid for the packet kind"):
        normalize_model_result(
            packet,
            _model_response(packet, classification=classification),
            analysis_key="a" * 64,
        )


def test_invariant_ok_without_test_evidence_downgrades_to_weak_binding() -> None:
    packet = _invariant_packet()

    result = normalize_model_result(
        packet,
        _model_response(
            packet,
            evidence=[_INVARIANT_REQUIREMENT, _INVARIANT_IMPLEMENTATION],
        ),
        analysis_key="a" * 64,
    )

    assert result.classification == "weak_binding"


def test_invariant_ok_without_binding_or_implementation_evidence_is_rejected() -> None:
    packet = _invariant_packet()

    with pytest.raises(SemanticResultError, match="invariant ok requires"):
        normalize_model_result(
            packet,
            _model_response(packet, evidence=[_INVARIANT_REQUIREMENT]),
            analysis_key="a" * 64,
        )


def test_mismatch_evidence_is_reconstructed_from_exact_packet_spans() -> None:
    packet = _section_packet()
    result = normalize_model_result(
        packet,
        _model_response(
            packet,
            classification="confirmed_mismatch",
            confidence=0.9,
            rationale="The shown return conflicts with the requirement.",
            summary="The implementation returns two.",
            evidence=[
                {
                    "role": "implementation",
                    "path": "pkg/x.py",
                    "start_line": 10,
                    "end_line": 11,
                },
                {
                    "role": "requirement",
                    "path": "docs/specs/01-x.md",
                    "start_line": 4,
                    "end_line": 6,
                },
            ],
        ),
        analysis_key="a" * 64,
    )

    assert result.verification_state == "evidence_bound"
    assert [item.role for item in result.evidence] == [
        "implementation",
        "requirement",
    ]
    assert result.evidence[0].excerpt == "def run() -> int:\n    return 2"
    assert (
        result.evidence[0].excerpt_sha256
        == hashlib.sha256(b"def run() -> int:\n    return 2").hexdigest()
    )
    row = result.to_row()
    assert row["schema_version"] == 2
    assert row["packet_hash"] == packet["packet_hash"]
    assert row["analysis_key"] == "a" * 64

    from backstitch.analysis_results import load_analysis_results

    loaded = load_analysis_results(json.dumps(row) + "\n", None)
    assert loaded.errors == ()
    assert loaded.results[0].classification == "confirmed_mismatch"


@pytest.mark.parametrize(
    ("evidence", "match"),
    [
        (
            [
                {
                    "role": "requirement",
                    "path": "docs/specs/01-x.md",
                    "start_line": 6,
                    "end_line": 6,
                    "excerpt": "forged",
                }
            ],
            "closed schema",
        ),
        (
            [
                {
                    "role": "requirement",
                    "path": "docs/specs/01-x.md",
                    "start_line": 99,
                    "end_line": 99,
                }
            ],
            "exactly one shown",
        ),
        (
            [
                {
                    "role": "implementation",
                    "path": "pkg/x.py",
                    "start_line": 10,
                    "end_line": 11,
                }
            ],
            "missing required evidence roles",
        ),
    ],
)
def test_mismatch_rejects_extra_forged_and_one_sided_evidence(
    evidence: list[dict[str, object]], match: str
) -> None:
    packet = _section_packet()
    with pytest.raises(SemanticResultError, match=match):
        normalize_model_result(
            packet,
            _model_response(
                packet,
                classification="confirmed_mismatch",
                confidence=None,
                rationale="mismatch",
                summary="Mismatch.",
                evidence=evidence,
            ),
            analysis_key="a" * 64,
        )


def test_closed_model_response_rejects_trusted_metadata() -> None:
    packet = _section_packet()
    with pytest.raises(SemanticResultError, match="closed schema"):
        normalize_model_result(
            packet,
            {
                **_model_response(packet, rationale="fine", summary="Fine."),
                "verification_state": "human_verified",
            },
            analysis_key="a" * 64,
        )


def test_closed_model_response_rejects_role_inside_coordinate() -> None:
    packet = _section_packet()
    response = _model_response(packet, evidence=[_SECTION_REQUIREMENT])
    assessment = response["assessment"]
    assert isinstance(assessment, dict)
    evidence = assessment["evidence"]
    assert isinstance(evidence, dict)
    requirement = evidence["requirement"]
    assert isinstance(requirement, list)
    coordinate = requirement[0]
    assert isinstance(coordinate, dict)
    coordinate["role"] = "implementation"

    with pytest.raises(SemanticResultError, match="closed schema"):
        normalize_model_result(packet, response, analysis_key="a" * 64)


def test_closed_model_response_rejects_unavailable_empty_role() -> None:
    packet = _section_packet()
    response = _model_response(packet)
    assessment = response["assessment"]
    assert isinstance(assessment, dict)
    evidence = assessment["evidence"]
    assert isinstance(evidence, dict)
    evidence["test"] = []

    with pytest.raises(SemanticResultError, match="unavailable in the packet"):
        normalize_model_result(packet, response, analysis_key="a" * 64)


_SECTION_REQUIREMENT = {
    "role": "requirement",
    "path": "docs/specs/01-x.md",
    "start_line": 4,
    "end_line": 6,
}
_SECTION_IMPLEMENTATION = {
    "role": "implementation",
    "path": "pkg/x.py",
    "start_line": 10,
    "end_line": 11,
}
_INVARIANT_REQUIREMENT = {
    "role": "requirement",
    "path": "pkg/x.py",
    "start_line": 1,
    "end_line": 1,
}
_INVARIANT_IMPLEMENTATION = {
    "role": "implementation",
    "path": "pkg/x.py",
    "start_line": 10,
    "end_line": 11,
}
_INVARIANT_TEST = {
    "role": "test",
    "path": "tests/test_x.py",
    "start_line": 20,
    "end_line": 21,
}
_SUPPRESSION_REQUIREMENT = {
    "role": "requirement",
    "path": "docs/specs/01-x.md",
    "start_line": 7,
    "end_line": 7,
}
_SUPPRESSION_COUNTEREVIDENCE = {
    "role": "counterevidence",
    "path": "generated/x.py",
    "start_line": 2,
    "end_line": 2,
}


@pytest.mark.parametrize(
    ("kind", "classification", "evidence"),
    [
        ("section", "ok", []),
        (
            "section",
            "confirmed_mismatch",
            [_SECTION_REQUIREMENT, _SECTION_IMPLEMENTATION],
        ),
        (
            "section",
            "probable_mismatch",
            [_SECTION_REQUIREMENT, _SECTION_IMPLEMENTATION],
        ),
        ("section", "missing_trace", [_SECTION_REQUIREMENT]),
        ("section", "ambiguous", [_SECTION_REQUIREMENT]),
        ("invariant", "ok", [_INVARIANT_TEST]),
        (
            "invariant",
            "weak_binding",
            [_INVARIANT_REQUIREMENT, _INVARIANT_IMPLEMENTATION],
        ),
        (
            "invariant",
            "confirmed_mismatch",
            [_INVARIANT_REQUIREMENT, _INVARIANT_IMPLEMENTATION],
        ),
        (
            "invariant",
            "probable_mismatch",
            [_INVARIANT_REQUIREMENT, _INVARIANT_IMPLEMENTATION],
        ),
        ("invariant", "ambiguous", [_INVARIANT_REQUIREMENT]),
        ("suppression", "ok", [_SUPPRESSION_REQUIREMENT]),
        (
            "suppression",
            "rationale_insufficient",
            [_SUPPRESSION_REQUIREMENT],
        ),
        (
            "suppression",
            "scope_overbroad",
            [_SUPPRESSION_REQUIREMENT, _SUPPRESSION_COUNTEREVIDENCE],
        ),
        (
            "suppression",
            "risk_unaddressed",
            [_SUPPRESSION_REQUIREMENT, _SUPPRESSION_COUNTEREVIDENCE],
        ),
        ("suppression", "ambiguous", [_SUPPRESSION_REQUIREMENT]),
    ],
)
def test_every_kind_classification_minimum_role_set_is_accepted(
    kind: str, classification: str, evidence: list[dict[str, object]]
) -> None:
    packet = {
        "section": _section_packet,
        "invariant": _invariant_packet,
        "suppression": _suppression_packet,
    }[kind]()
    result = normalize_model_result(
        packet,
        _model_response(packet, classification=classification, evidence=evidence),
        analysis_key="a" * 64,
    )
    assert result.classification == classification
    assert result.to_row()["schema_version"] == (3 if kind == "suppression" else 2)


@pytest.mark.parametrize("classification", ["scope_overbroad", "risk_unaddressed"])
def test_suppression_one_sided_risk_finding_is_malformed(
    classification: str,
) -> None:
    packet = _suppression_packet()

    with pytest.raises(SemanticResultError, match="counterevidence"):
        normalize_model_result(
            packet,
            _model_response(
                packet,
                classification=classification,
                rationale="The declaration does not address the shown issue.",
                summary="Suppression needs review.",
                evidence=[_SUPPRESSION_REQUIREMENT],
            ),
            analysis_key="a" * 64,
        )


def test_suppression_kind_requires_packet_contract_4() -> None:
    packet = _suppression_packet()
    packet["schema_version"] = 3

    with pytest.raises(SemanticResultError, match="contract version"):
        normalize_model_result(
            packet,
            _model_response(packet, evidence=[_SUPPRESSION_REQUIREMENT]),
            analysis_key="a" * 64,
        )


def test_duplicate_evidence_items_are_rejected() -> None:
    packet = _section_packet()
    duplicate = [dict(_SECTION_REQUIREMENT), dict(_SECTION_REQUIREMENT)]
    with pytest.raises(SemanticResultError, match="duplicate"):
        normalize_model_result(
            packet,
            _model_response(
                packet,
                classification="ambiguous",
                rationale="ambiguous",
                summary="Ambiguous.",
                evidence=duplicate,
            ),
            analysis_key="a" * 64,
        )


@pytest.mark.parametrize("overlap", ["equal", "nested"])
def test_normalization_uses_the_deduplicated_model_visible_regions(
    overlap: str,
) -> None:
    packet = _section_packet()
    original = packet["owners"][0]
    if overlap == "equal":
        packet["owners"] = [original, {**original, "symbol": "run_alias"}]
    else:
        outer = {
            **original,
            "snippet": "def run() -> int:\n    value = 2\n    return value",
        }
        inner = {
            "path": original["path"],
            "symbol": "run.value",
            "start_line": 11,
            "snippet": "    value = 2",
        }
        packet["owners"] = [outer, inner]
    packet["packet_hash"] = semantic_packet_hash(packet)
    visible = semantic_packet_projection(packet)
    evidence = [
        region
        for region in visible["evidence_regions"]
        if region["role"] == "implementation"
    ]

    result = normalize_model_result(
        packet,
        _model_response(packet, rationale="fine", summary="Fine.", evidence=evidence),
        analysis_key="a" * 64,
    )

    assert len(evidence) == 1
    assert len(result.evidence) == 1
    assert result.evidence[0].start_line == evidence[0]["start_line"]
    assert result.evidence[0].end_line == evidence[0]["end_line"]
