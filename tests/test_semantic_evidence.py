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


def test_mismatch_evidence_is_reconstructed_from_exact_packet_spans() -> None:
    packet = _section_packet()
    result = normalize_model_result(
        packet,
        {
            "packet_id": packet["packet_id"],
            "classification": "confirmed_mismatch",
            "confidence": 0.9,
            "rationale": "The shown return conflicts with the requirement.",
            "summary": "The implementation returns two.",
            "evidence": [
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
        },
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
            "exactly role",
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
            {
                "packet_id": packet["packet_id"],
                "classification": "confirmed_mismatch",
                "confidence": None,
                "rationale": "mismatch",
                "summary": "Mismatch.",
                "evidence": evidence,
            },
            analysis_key="a" * 64,
        )


def test_closed_model_response_rejects_trusted_metadata() -> None:
    packet = _section_packet()
    with pytest.raises(SemanticResultError, match="closed schema"):
        normalize_model_result(
            packet,
            {
                "packet_id": packet["packet_id"],
                "classification": "ok",
                "confidence": 0.5,
                "rationale": "fine",
                "summary": "Fine.",
                "evidence": [],
                "verification_state": "human_verified",
            },
            analysis_key="a" * 64,
        )


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
    ],
)
def test_every_kind_classification_minimum_role_set_is_accepted(
    kind: str, classification: str, evidence: list[dict[str, object]]
) -> None:
    packet = _section_packet() if kind == "section" else _invariant_packet()
    result = normalize_model_result(
        packet,
        {
            "packet_id": packet["packet_id"],
            "classification": classification,
            "confidence": 0.5,
            "rationale": "bounded evidence",
            "summary": "Reviewed.",
            "evidence": evidence,
        },
        analysis_key="a" * 64,
    )
    assert result.classification == classification


def test_duplicate_evidence_items_are_rejected() -> None:
    packet = _section_packet()
    duplicate = [dict(_SECTION_REQUIREMENT), dict(_SECTION_REQUIREMENT)]
    with pytest.raises(SemanticResultError, match="duplicate"):
        normalize_model_result(
            packet,
            {
                "packet_id": packet["packet_id"],
                "classification": "ambiguous",
                "confidence": 0.5,
                "rationale": "ambiguous",
                "summary": "Ambiguous.",
                "evidence": duplicate,
            },
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
        {
            "packet_id": packet["packet_id"],
            "classification": "ok",
            "confidence": 0.5,
            "rationale": "fine",
            "summary": "Fine.",
            "evidence": evidence,
        },
        analysis_key="a" * 64,
    )

    assert len(evidence) == 1
    assert len(result.evidence) == 1
    assert result.evidence[0].start_line == evidence[0]["start_line"]
    assert result.evidence[0].end_line == evidence[0]["end_line"]
