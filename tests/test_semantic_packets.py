"""Canonical semantic packet projection tests."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from backstitch.canonical import lf_slice
from backstitch.semantic_evidence import normalize_model_result
from backstitch.semantic_packets import (
    semantic_packet_hash,
    semantic_packet_projection,
)


def _packet() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "packet_id": "docs/specs/01-x.md#X-1",
        "kind": "section",
        "spec_path": "docs/specs/01-x.md",
        "section_id": "X-1",
        "title": "X",
        "section_text": "## X [X-1]\n\nCafé.",
        "section_start_line": 1,
        "owners": [
            {
                "path": "pkg/x.py",
                "symbol": None,
                "start_line": 1,
                "snippet": "x = 1",
                "future_nested": "excluded",
            }
        ],
        "tests": ["tests/test_x.py"],
        "issues": [
            {
                "code": "SPEC_SECTION_UNMAPPED",
                "severity": "info",
                "path": "docs/specs/01-x.md",
                "line": 1,
                "message": "unmapped",
                "section_id": "X-1",
                "symbol": None,
                "short_code": "BSS005",
                "context": None,
                "default_severity": "info",
                "invariant_id": None,
            }
        ],
        "packet_warnings": [],
        "instructions": "hostile legacy extension",
        "future_top_level": {"excluded": True},
    }


def test_projection_strips_all_nonsemantic_top_level_and_nested_fields() -> None:
    projection = semantic_packet_projection(_packet())

    assert "schema_version" not in projection
    assert "instructions" not in projection
    assert "future_top_level" not in projection
    assert "future_nested" not in projection["owners"][0]
    assert "severity" not in projection["issues"][0]


def test_projection_exposes_exact_citable_end_lines() -> None:
    section = semantic_packet_projection(_packet())
    invariant = semantic_packet_projection(_invariant_packet())

    assert section["section_start_line"] == 1
    assert section["section_end_line"] == 3
    assert section["owners"][0]["start_line"] == 1
    assert section["owners"][0]["end_line"] == 1
    assert invariant["targets"][0]["end_line"] == 2
    assert invariant["binding_tests"][0]["end_line"] == 2
    assert section["evidence_regions"] == [
        {
            "role": "requirement",
            "path": "docs/specs/01-x.md",
            "start_line": 1,
            "end_line": 3,
        },
        {
            "role": "implementation",
            "path": "pkg/x.py",
            "start_line": 1,
            "end_line": 1,
        },
    ]
    assert invariant["evidence_regions"] == [
        {
            "role": "requirement",
            "path": "pkg/x.py",
            "start_line": 2,
            "end_line": 2,
        },
        {
            "role": "implementation",
            "path": "pkg/x.py",
            "start_line": 1,
            "end_line": 2,
        },
        {
            "role": "test",
            "path": "tests/test_x.py",
            "start_line": 1,
            "end_line": 2,
        },
    ]


@pytest.mark.parametrize(
    "separator",
    ("\r", "\f", "\v", "\x85", "\u2028", "\u2029"),
    ids=(
        "cr",
        "form-feed",
        "vertical-tab",
        "nel",
        "line-separator",
        "paragraph-separator",
    ),
)
def test_non_lf_characters_preserve_receipts_and_citable_regions(
    separator: str,
) -> None:
    """Tests-invariant: [INV.LINE.1]

    Reproduce finding #5 for every character named by INV.LINE.1.

    The exact source is ``first<separator>still-first\nsecond\n``. Only the LF
    advances the source line, so receipt line 2 must be the exact bytes
    ``second\n``. The same separator inside a shown snippet must not advance
    its advertised end line; a model copying the advertised requirement and
    implementation regions must normalize successfully. Today byte
    ``splitlines`` mis-slices bare CR, while text ``splitlines`` invents an
    extra line for CR, form feed, vertical tab, NEL, U+2028, and U+2029; the
    model-facing region then disagrees with the normalizer's LF-only region.
    """

    raw = f"first{separator}still-first\nsecond\n".encode()
    assert lf_slice(raw, 2, 2, policy="clamped") == b"second\n"

    packet = _packet()
    packet["owners"][0]["start_line"] = 10
    packet["owners"][0]["snippet"] = f"first{separator}still-first\nsecond"
    packet["packet_hash"] = semantic_packet_hash(packet)
    projection = semantic_packet_projection(packet)
    implementation_region = next(
        row for row in projection["evidence_regions"] if row["role"] == "implementation"
    )
    requirement_region = next(
        row for row in projection["evidence_regions"] if row["role"] == "requirement"
    )

    result = normalize_model_result(
        packet,
        {
            "packet_id": packet["packet_id"],
            "assessment": {
                "classification": "confirmed_mismatch",
                "evidence": {
                    "requirement": [
                        {
                            key: requirement_region[key]
                            for key in ("path", "start_line", "end_line")
                        }
                    ],
                    "implementation": [
                        {
                            key: implementation_region[key]
                            for key in ("path", "start_line", "end_line")
                        }
                    ],
                },
            },
            "confidence": 0.9,
            "rationale": "The shown implementation conflicts with the requirement.",
            "summary": "The implementation disagrees with the contract.",
        },
        analysis_key="a" * 64,
    )

    assert implementation_region["end_line"] == 11
    assert result.verification_state == "evidence_bound"


def test_projection_excludes_nested_ambiguous_evidence_regions() -> None:
    packet = _packet()
    packet["owners"] = [
        {
            "path": "pkg/x.py",
            "symbol": None,
            "start_line": 1,
            "snippet": "first\nsecond\nthird",
        },
        {
            "path": "pkg/x.py",
            "symbol": "second",
            "start_line": 2,
            "snippet": "second",
        },
    ]

    projection = semantic_packet_projection(packet)
    implementation_regions = [
        region
        for region in projection["evidence_regions"]
        if region["role"] == "implementation"
    ]

    assert projection["owners"] == [
        {
            "path": "pkg/x.py",
            "symbol": None,
            "start_line": 1,
            "end_line": 3,
            "snippet": "first\nsecond\nthird",
        }
    ]
    assert implementation_regions == [
        {
            "role": "implementation",
            "path": "pkg/x.py",
            "start_line": 1,
            "end_line": 3,
        }
    ]


def test_every_model_visible_section_field_changes_packet_hash() -> None:
    baseline = _packet()
    original = semantic_packet_hash(baseline)
    mutations = {
        "packet_id": "docs/specs/01-x.md#X-2",
        "kind": "invariant",
        "spec_path": "docs/specs/02-x.md",
        "section_id": "X-2",
        "title": "Y",
        "section_text": "changed",
        "section_start_line": 2,
        "owners": [],
        "tests": [],
        "issues": [],
        "packet_warnings": ["warning"],
    }
    for field, value in mutations.items():
        changed = deepcopy(baseline)
        changed[field] = value
        if field == "kind":
            # Kind selects a different closed shape, so this malformed hybrid
            # is expected to fail projection rather than collide.
            try:
                semantic_packet_hash(changed)
            except KeyError:
                continue
        assert semantic_packet_hash(changed) != original, field

    for field, value in (
        ("instructions", "different hostile text"),
        ("schema_version", 999),
        ("future_top_level", "different extension"),
    ):
        changed = deepcopy(baseline)
        changed[field] = value
        assert semantic_packet_hash(changed) == original, field


def test_every_nested_section_projection_field_changes_packet_hash() -> None:
    baseline = _packet()
    original = semantic_packet_hash(baseline)
    owner_changes = {
        "path": "pkg/y.py",
        "symbol": "run",
        "start_line": 2,
        "snippet": "x = 2",
    }
    for field, value in owner_changes.items():
        changed = deepcopy(baseline)
        changed["owners"][0][field] = value
        assert semantic_packet_hash(changed) != original, f"owners.{field}"

    issue_changes = {
        "code": "SPEC_FILE_MISSING",
        "path": "docs/specs/other.md",
        "line": 2,
        "message": "changed",
        "section_id": None,
        "symbol": "run",
        "short_code": "BSS001",
        "context": "changed",
        "default_severity": "warning",
        "invariant_id": "INV.X.1",
    }
    for field, value in issue_changes.items():
        changed = deepcopy(baseline)
        changed["issues"][0][field] = value
        assert semantic_packet_hash(changed) != original, f"issues.{field}"

    changed = deepcopy(baseline)
    changed["issues"][0]["severity"] = "error"
    assert semantic_packet_hash(changed) == original


def _invariant_packet() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "packet_id": "invariant::INV.X.1",
        "kind": "invariant",
        "invariant_id": "INV.X.1",
        "tier": "required",
        "statement": "Must return one.",
        "declaration": {
            "kind": "code",
            "path": "pkg/x.py",
            "line": 2,
            "symbol": "run",
            "section_id": None,
            "start_line": 2,
            "end_line": 2,
            "excerpt": "Invariant: [INV.X.1] Must return one.",
        },
        "targets": [
            {
                "path": "pkg/x.py",
                "symbol": "run",
                "start_line": 1,
                "snippet": "def run():\n    return 1",
            }
        ],
        "binding_tests": [
            {
                "path": "tests/test_x.py",
                "symbol": "test_run",
                "start_line": 1,
                "snippet": "def test_run():\n    assert run() == 1",
            }
        ],
        "issues": deepcopy(_packet()["issues"]),
        "packet_warnings": [],
        "content_hash": "0" * 64,
    }


def test_every_invariant_projection_field_changes_packet_hash() -> None:
    baseline = _invariant_packet()
    original = semantic_packet_hash(baseline)
    top_changes: dict[str, Any] = {
        "packet_id": "invariant::INV.X.2",
        "kind": "section",
        "invariant_id": "INV.X.2",
        "tier": "draft",
        "statement": "Changed.",
        "declaration": {**baseline["declaration"], "line": 3},
        "targets": [],
        "binding_tests": [],
        "issues": [],
        "packet_warnings": ["warning"],
    }
    for field, value in top_changes.items():
        changed = deepcopy(baseline)
        changed[field] = value
        if field == "kind":
            try:
                semantic_packet_hash(changed)
            except KeyError:
                continue
        assert semantic_packet_hash(changed) != original, field

    declaration_changes: dict[str, Any] = {
        "kind": "spec",
        "path": "docs/specs/x.md",
        "line": 3,
        "symbol": None,
        "section_id": "X-1",
        "start_line": 3,
        "end_line": 3,
        "excerpt": "changed",
    }
    for field, value in declaration_changes.items():
        changed = deepcopy(baseline)
        changed["declaration"][field] = value
        assert semantic_packet_hash(changed) != original, f"declaration.{field}"

    snippet_changes: dict[str, Any] = {
        "path": "other.py",
        "symbol": "other",
        "start_line": 4,
        "snippet": "changed",
    }
    for list_name in ("targets", "binding_tests"):
        for field, value in snippet_changes.items():
            changed = deepcopy(baseline)
            changed[list_name][0][field] = value
            assert semantic_packet_hash(changed) != original, f"{list_name}.{field}"

    for field in (
        "code",
        "path",
        "line",
        "message",
        "section_id",
        "symbol",
        "short_code",
        "context",
        "default_severity",
        "invariant_id",
    ):
        changed = deepcopy(baseline)
        changed["issues"][0][field] = f"changed-{field}"
        assert semantic_packet_hash(changed) != original, f"issues.{field}"

    excluded_changes: dict[str, Any] = {
        "content_hash": "f" * 64,
        "packet_hash": "e" * 64,
        "instructions": "hostile",
    }
    for excluded, value in excluded_changes.items():
        changed = deepcopy(baseline)
        changed[excluded] = value
        assert semantic_packet_hash(changed) == original, excluded

    changed_schema = deepcopy(baseline)
    changed_schema["schema_version"] = 3
    with pytest.raises(KeyError):
        semantic_packet_hash(changed_schema)
