"""Artifact trust-boundary validators.

Spec: docs/specs/02-backstitch-core.md [SC-6], [SC-13]
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from backstitch.artifact_contracts import (
    invariant_content_hash,
    load_deterministic_report,
    load_packets,
)
from backstitch.semantic_packets import semantic_packet_hash


def _semantic_hash(packet: dict[str, Any]) -> str:
    return semantic_packet_hash(packet)


def _packet() -> dict[str, Any]:
    return {
        "packet_id": "docs/specs/01-x.md#X-1",
        "kind": "section",
        "spec_path": "docs/specs/01-x.md",
        "section_id": "X-1",
        "title": "X",
        "section_text": "## X [X-1]\n\nMust work.",
        "section_start_line": 1,
        "owners": [
            {"path": "pkg/x.py", "symbol": None, "start_line": 1, "snippet": "x = 1"}
        ],
        "tests": ["tests/test_x.py"],
        "issues": [],
        "packet_warnings": [],
        "instructions": "Return JSON.",
    }


def _v2_packet() -> dict[str, Any]:
    packet = _packet()
    packet.pop("instructions")
    packet["schema_version"] = 2
    packet["packet_hash"] = _semantic_hash(packet)
    return packet


def _v2_invariant_packet() -> dict[str, Any]:
    packet = _invariant_packet()
    packet.pop("instructions")
    declaration = packet["declaration"]
    assert isinstance(declaration, dict)
    declaration.update(
        {
            "start_line": declaration["line"],
            "end_line": declaration["line"],
            "excerpt": packet["statement"],
        }
    )
    packet["schema_version"] = 2
    packet["packet_hash"] = semantic_packet_hash(packet)
    return packet


def _invariant_packet() -> dict[str, Any]:
    targets = [
        {
            "path": "pkg/x.py",
            "symbol": "run",
            "start_line": 3,
            "snippet": "def run() -> int:\n    return 1",
        }
    ]
    binding_tests = [
        {
            "path": "tests/test_x.py",
            "symbol": "test_run",
            "start_line": 4,
            "snippet": "def test_run() -> None:\n    assert run() == 1",
        }
    ]
    statement = "The result is one."
    return {
        "packet_id": "invariant::INV.X.1",
        "kind": "invariant",
        "invariant_id": "INV.X.1",
        "tier": "required",
        "statement": statement,
        "declaration": {
            "kind": "code",
            "path": "pkg/x.py",
            "line": 3,
            "symbol": "run",
            "section_id": None,
        },
        "targets": targets,
        "binding_tests": binding_tests,
        "issues": [],
        "packet_warnings": [],
        "instructions": "Return JSON.",
        "content_hash": invariant_content_hash(statement, targets, binding_tests),
    }


def test_load_packets_normalizes_multiline_legacy_invariant_span(
    tmp_path: Path,
) -> None:
    path = tmp_path / "packets.jsonl"
    packet = _invariant_packet()
    packet["statement"] = "The result is one.\nIt remains stable."
    packet["content_hash"] = invariant_content_hash(
        packet["statement"], packet["targets"], packet["binding_tests"]
    )
    path.write_text(json.dumps(packet) + "\n", encoding="utf-8")

    loaded = load_packets(path)
    declaration = loaded[0].to_dict()["declaration"]

    assert loaded[0].cache_eligible is False
    assert declaration["start_line"] == 3
    assert declaration["end_line"] == 4
    assert declaration["excerpt"] == packet["statement"]


def _empty_report(tmp_path: Path) -> dict[str, object]:
    return {
        "profile": "backstitch-style-v1",
        "repo_root": str(tmp_path),
        "summary": {
            "spec_sections": 0,
            "code_refs": 0,
            "spec_mappings": 0,
            "invariants": 0,
            "errors": 0,
            "warnings": 0,
            "infos": 0,
        },
        "spec_sections": [],
        "code_refs": [],
        "spec_mappings": [],
        "edges": [],
        "invariants": [],
        "binds": [],
        "issues": [],
    }


def _issue(
    *,
    code: str = "SPEC_FILE_MISSING",
    short_code: str = "BSS001",
    context: str | None = None,
    default_severity: str = "error",
) -> dict[str, object]:
    return {
        "code": code,
        "short_code": short_code,
        "context": context,
        "severity": "error",
        "default_severity": default_severity,
        "path": "pkg/x.py",
        "line": 1,
        "message": "broken reference",
        "section_id": None,
        "symbol": None,
        "invariant_id": None,
    }


def test_load_packets_accepts_v2_packet_for_migration_but_not_semantic_use(
    tmp_path: Path,
) -> None:
    path = tmp_path / "packets.jsonl"
    packet = _v2_packet()
    path.write_text(json.dumps(packet) + "\n", encoding="utf-8")

    loaded = load_packets(path)

    assert len(loaded) == 1
    assert loaded[0].cache_eligible is False
    assert loaded[0].semantic_eligible is False
    assert loaded[0].to_dict() == packet


@pytest.mark.parametrize(
    ("mutation", "fragment"),
    [
        ("too-many-owners", "owners"),
        ("duplicate-owner", "owners"),
        ("overlong-owner", "snippet"),
        ("overlong-section", "section_text"),
        ("duplicate-test", "tests"),
        ("no-resolved-edge", "owners.*tests"),
    ],
)
def test_load_packets_rejects_v2_section_content_outside_producer_bounds(
    tmp_path: Path, mutation: str, fragment: str
) -> None:
    packet = _v2_packet()
    if mutation == "too-many-owners":
        owner = deepcopy(packet["owners"][0])
        packet["owners"] = [{**owner, "path": f"pkg/x{index}.py"} for index in range(9)]
    elif mutation == "duplicate-owner":
        packet["owners"] = [packet["owners"][0], deepcopy(packet["owners"][0])]
    elif mutation == "overlong-owner":
        packet["owners"][0]["snippet"] = "\n".join("x" for _ in range(121))
    elif mutation == "overlong-section":
        packet["section_text"] = "\n".join("x" for _ in range(101))
    elif mutation == "no-resolved-edge":
        packet["owners"] = []
        packet["tests"] = []
    else:
        packet["tests"] = ["tests/test_x.py", "tests/test_x.py"]
    packet["packet_hash"] = semantic_packet_hash(packet)
    path = tmp_path / "packets.jsonl"
    path.write_text(json.dumps(packet) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match=fragment):
        load_packets(path)


@pytest.mark.parametrize(
    ("mutation", "fragment"),
    [
        ("too-many-targets", "targets"),
        ("no-binding-tests", "binding_tests"),
        ("duplicate-binding-test", "binding_tests"),
        ("overlong-target", "snippet"),
        ("unrelated-code-target", "targets"),
        ("unsorted-issues", "issues"),
    ],
)
def test_load_packets_rejects_v2_invariant_content_outside_producer_bounds(
    tmp_path: Path, mutation: str, fragment: str
) -> None:
    packet = _v2_invariant_packet()
    if mutation == "too-many-targets":
        target = deepcopy(packet["targets"][0])
        packet["targets"] = [
            {**target, "path": f"pkg/x{index}.py"} for index in range(9)
        ]
    elif mutation == "no-binding-tests":
        packet["binding_tests"] = []
    elif mutation == "duplicate-binding-test":
        packet["binding_tests"] = [
            packet["binding_tests"][0],
            deepcopy(packet["binding_tests"][0]),
        ]
    elif mutation == "overlong-target":
        packet["targets"][0]["snippet"] = "\n".join("x" for _ in range(121))
    elif mutation == "unsorted-issues":
        packet["issues"] = [
            {
                "code": "INVARIANT_UNKNOWN",
                "path": "z.py",
                "line": 2,
                "message": "z",
                "section_id": None,
                "symbol": None,
                "short_code": "BSI002",
                "context": None,
                "default_severity": "error",
                "invariant_id": "INV.X.1",
            },
            {
                "code": "INVARIANT_UNKNOWN",
                "path": "a.py",
                "line": 1,
                "message": "a",
                "section_id": None,
                "symbol": None,
                "short_code": "BSI002",
                "context": None,
                "default_severity": "error",
                "invariant_id": "INV.X.1",
            },
        ]
    else:
        packet["targets"][0]["path"] = "pkg/unrelated.py"
    packet["content_hash"] = invariant_content_hash(
        packet["statement"], packet["targets"], packet["binding_tests"]
    )
    packet["packet_hash"] = semantic_packet_hash(packet)
    path = tmp_path / "packets.jsonl"
    path.write_text(json.dumps(packet) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match=fragment):
        load_packets(path)


@pytest.mark.parametrize("declaration_kind", ["spec", "code"])
def test_load_packets_rejects_v2_invariant_declaration_before_its_marker(
    tmp_path: Path, declaration_kind: str
) -> None:
    packet = _v2_invariant_packet()
    declaration = packet["declaration"]
    assert isinstance(declaration, dict)
    declaration.update(
        {
            "kind": declaration_kind,
            "path": "docs/specs/01-x.md" if declaration_kind == "spec" else "pkg/x.py",
            "line": 3,
            "symbol": None if declaration_kind == "spec" else "run",
            "section_id": "X-1" if declaration_kind == "spec" else None,
            "start_line": 2,
            "end_line": 3,
            "excerpt": "context\nInvariant: [INV.X.1] The result is one.",
        }
    )
    if declaration_kind == "spec":
        packet["targets"] = []
    packet["content_hash"] = invariant_content_hash(
        packet["statement"], packet["targets"], packet["binding_tests"]
    )
    packet["packet_hash"] = semantic_packet_hash(packet)
    path = tmp_path / "packets.jsonl"
    path.write_text(json.dumps(packet) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="declaration"):
        load_packets(path)


def test_load_packets_rejects_multiline_v2_spec_declaration(
    tmp_path: Path,
) -> None:
    packet = _v2_invariant_packet()
    declaration = packet["declaration"]
    assert isinstance(declaration, dict)
    declaration.update(
        {
            "kind": "spec",
            "path": "docs/specs/01-x.md",
            "line": 2,
            "symbol": None,
            "section_id": "X-1",
            "start_line": 2,
            "end_line": 3,
            "excerpt": "Invariant: [INV.X.1] The result is one.\nextra",
        }
    )
    packet["targets"] = []
    packet["content_hash"] = invariant_content_hash(
        packet["statement"], packet["targets"], packet["binding_tests"]
    )
    packet["packet_hash"] = semantic_packet_hash(packet)
    path = tmp_path / "packets.jsonl"
    path.write_text(json.dumps(packet) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="declaration"):
        load_packets(path)


def test_load_packets_normalizes_exact_legacy_section_packet(
    tmp_path: Path,
) -> None:
    path = tmp_path / "packets.jsonl"
    packet = _packet()
    del packet["kind"]
    path.write_text(json.dumps(packet) + "\n", encoding="utf-8")

    loaded = load_packets(path)

    normalized = loaded[0].to_dict()
    assert loaded[0].cache_eligible is False
    assert normalized["kind"] == "section"
    assert normalized["schema_version"] == 2
    assert normalized["packet_hash"] == _semantic_hash(normalized)
    assert "instructions" not in normalized


def test_load_packets_normalizes_legacy_nested_issue_shape(tmp_path: Path) -> None:
    path = tmp_path / "packets.jsonl"
    packet = _packet()
    del packet["kind"]
    issue = _issue()
    del issue["invariant_id"]
    packet["issues"] = [issue]
    path.write_text(json.dumps(packet) + "\n", encoding="utf-8")

    loaded = load_packets(path)

    assert loaded[0].to_dict()["issues"][0]["invariant_id"] is None


def test_load_packets_accepts_invariant_packet_and_unknown_fields(
    tmp_path: Path,
) -> None:
    path = tmp_path / "packets.jsonl"
    packet = _invariant_packet()
    packet["future_field"] = {"preserved": True}
    path.write_text(json.dumps(packet) + "\n", encoding="utf-8")

    loaded = load_packets(path)

    assert loaded[0].cache_eligible is False
    assert loaded[0].to_dict()["future_field"] == {"preserved": True}
    assert "instructions" not in loaded[0].to_dict()


@pytest.mark.parametrize(
    "mutation",
    ["tampered-hash", "missing-kind", "both-owners", "wrong-id"],
)
def test_load_packets_rejects_malformed_invariant_packet(
    tmp_path: Path,
    mutation: str,
) -> None:
    path = tmp_path / "packets.jsonl"
    packet = _invariant_packet()
    if mutation == "tampered-hash":
        packet["statement"] = "A changed statement."
    elif mutation == "missing-kind":
        del packet["kind"]
    elif mutation == "both-owners":
        declaration = packet["declaration"]
        assert isinstance(declaration, dict)
        declaration["section_id"] = "X-1"
    else:
        packet["packet_id"] = "invariant::INV.OTHER.1"
    path.write_text(json.dumps(packet) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="malformed packet"):
        load_packets(path)


@pytest.mark.parametrize("value", [None, ""])
def test_load_packets_rejects_invariant_only_field_on_section_packet(
    tmp_path: Path,
    value: object,
) -> None:
    path = tmp_path / "packets.jsonl"
    packet = _packet()
    packet["content_hash"] = value
    path.write_text(json.dumps(packet) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="invariant-only `content_hash`"):
        load_packets(path)


@pytest.mark.parametrize(
    ("kind", "packet_id"),
    [(None, "docs/specs/01-x.md#X-1"), ("missing", None)],
    ids=["explicit-null-kind", "non-string-legacy-packet-id"],
)
def test_load_packets_rejects_malformed_legacy_discriminator_without_crashing(
    tmp_path: Path,
    kind: str | None,
    packet_id: object,
) -> None:
    path = tmp_path / "packets.jsonl"
    packet = _packet()
    if kind == "missing":
        del packet["kind"]
    else:
        packet["kind"] = kind
    packet["packet_id"] = packet_id
    path.write_text(json.dumps(packet) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="malformed packet"):
        load_packets(path)


def test_load_packets_accepts_registry_context_and_packaged_default(
    tmp_path: Path,
) -> None:
    path = tmp_path / "packets.jsonl"
    packet = _packet()
    packet["issues"] = [
        _issue(
            code="SPEC_SECTION_AMBIGUOUS",
            short_code="BSS003",
            context="asserted",
            default_severity="error",
        )
    ]
    path.write_text(json.dumps(packet) + "\n", encoding="utf-8")

    loaded = load_packets(path)

    assert loaded[0].to_dict()["issues"][0]["context"] == "asserted"


@pytest.mark.parametrize(
    "issue",
    [
        _issue(
            code="SPEC_SECTION_AMBIGUOUS",
            short_code="BSS003",
            context=None,
            default_severity="error",
        ),
        _issue(context="bogus"),
    ],
    ids=["context-required", "context-forbidden"],
)
def test_load_packets_enforces_registry_context_shape(
    tmp_path: Path,
    issue: dict[str, object],
) -> None:
    path = tmp_path / "packets.jsonl"
    packet = _packet()
    packet["issues"] = [issue]
    path.write_text(json.dumps(packet) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid `issues` item"):
        load_packets(path)


@pytest.mark.parametrize(
    "issue",
    [
        _issue(default_severity="warning"),
        _issue(
            code="SPEC_SECTION_AMBIGUOUS",
            short_code="BSS003",
            context="weak",
            default_severity="error",
        ),
    ],
    ids=["contextless", "contextual"],
)
def test_load_packets_rejects_non_packaged_default_severity(
    tmp_path: Path,
    issue: dict[str, object],
) -> None:
    path = tmp_path / "packets.jsonl"
    packet = _packet()
    packet["issues"] = [issue]
    path.write_text(json.dumps(packet) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid `issues` item"):
        load_packets(path)


def test_load_packets_rejects_blank_required_identifier(tmp_path: Path) -> None:
    path = tmp_path / "packets.jsonl"
    packet = _packet()
    packet["title"] = " "
    path.write_text(json.dumps(packet) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="`title` must be non-empty"):
        load_packets(path)


def test_load_deterministic_report_accepts_empty_well_formed_report(
    tmp_path: Path,
) -> None:
    path = tmp_path / "report.json"
    report = _empty_report(tmp_path)
    path.write_text(json.dumps(report), encoding="utf-8")
    assert load_deterministic_report(path) == report


def test_load_deterministic_report_accepts_spec_owned_invariant(
    tmp_path: Path,
) -> None:
    path = tmp_path / "report.json"
    report = _empty_report(tmp_path)
    report["invariants"] = [
        {
            "invariant_id": "INV.SPEC.1",
            "statement": "The spec owns this invariant.",
            "tier": "draft",
            "declaration_kind": "spec",
            "path": "docs/specs/01-x.md",
            "line": 5,
            "owner_symbol": None,
            "section_id": "X-1",
        }
    ]
    summary = report["summary"]
    assert isinstance(summary, dict)
    summary["invariants"] = 1
    path.write_text(json.dumps(report), encoding="utf-8")

    assert load_deterministic_report(path) == report


def test_load_deterministic_report_normalizes_exact_legacy_shape(
    tmp_path: Path,
) -> None:
    path = tmp_path / "report.json"
    report = _empty_report(tmp_path)
    issue = _issue()
    del issue["invariant_id"]
    report["issues"] = [issue]
    summary = report["summary"]
    assert isinstance(summary, dict)
    summary["errors"] = 1
    del summary["invariants"]
    del report["invariants"]
    del report["binds"]
    path.write_text(json.dumps(report), encoding="utf-8")

    loaded = load_deterministic_report(path)

    assert loaded["summary"]["invariants"] == 0
    assert loaded["invariants"] == []
    assert loaded["binds"] == []
    assert loaded["issues"][0]["invariant_id"] is None


@pytest.mark.parametrize("missing", ["summary", "invariants", "binds"])
def test_load_deterministic_report_rejects_partial_invariant_shape(
    tmp_path: Path,
    missing: str,
) -> None:
    path = tmp_path / "report.json"
    report = _empty_report(tmp_path)
    if missing == "summary":
        summary = report["summary"]
        assert isinstance(summary, dict)
        del summary["invariants"]
    else:
        del report[missing]
    path.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(ValueError, match="partial invariant report shape"):
        load_deterministic_report(path)


def test_load_deterministic_report_accepts_invariant_and_bind_relations(
    tmp_path: Path,
) -> None:
    path = tmp_path / "report.json"
    report = _empty_report(tmp_path)
    report["invariants"] = [
        {
            "invariant_id": "INV.LOAD.1",
            "statement": "Loaded reports preserve relations.",
            "tier": "required",
            "declaration_kind": "code",
            "path": "pkg/x.py",
            "line": 2,
            "owner_symbol": "load",
            "section_id": None,
        }
    ]
    report["binds"] = [
        {
            "invariant_id": "INV.LOAD.1",
            "test_path": "tests/test_x.py",
            "test_symbol": "test_load",
            "marker_line": 4,
            "start_line": 3,
            "end_line": 6,
        }
    ]
    summary = report["summary"]
    assert isinstance(summary, dict)
    summary["invariants"] = 1
    path.write_text(json.dumps(report), encoding="utf-8")

    assert load_deterministic_report(path) == report


def test_load_deterministic_report_requires_new_issue_invariant_locator(
    tmp_path: Path,
) -> None:
    path = tmp_path / "report.json"
    report = _empty_report(tmp_path)
    issue = _issue()
    del issue["invariant_id"]
    report["issues"] = [issue]
    summary = report["summary"]
    assert isinstance(summary, dict)
    summary["errors"] = 1
    path.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(ValueError, match="issues\\[0\\]"):
        load_deterministic_report(path)


def test_load_deterministic_report_accepts_unknown_invariant_issue_locator(
    tmp_path: Path,
) -> None:
    path = tmp_path / "report.json"
    report = _empty_report(tmp_path)
    issue = _issue(
        code="INVARIANT_UNKNOWN",
        short_code="BSI002",
        default_severity="error",
    )
    issue["invariant_id"] = "INV.UNKNOWN.1"
    report["issues"] = [issue]
    summary = report["summary"]
    assert isinstance(summary, dict)
    summary["errors"] = 1
    path.write_text(json.dumps(report), encoding="utf-8")

    assert load_deterministic_report(path) == report


def test_load_deterministic_report_preserves_unknown_invariant_row_fields(
    tmp_path: Path,
) -> None:
    path = tmp_path / "report.json"
    report = _empty_report(tmp_path)
    report["invariants"] = [
        {
            "invariant_id": "INV.EXTRA.1",
            "statement": "Unknown fields pass through.",
            "tier": "required",
            "declaration_kind": "code",
            "path": "pkg/x.py",
            "line": 2,
            "owner_symbol": "run",
            "section_id": None,
            "future_field": {"kept": True},
        }
    ]
    summary = report["summary"]
    assert isinstance(summary, dict)
    summary["invariants"] = 1
    path.write_text(json.dumps(report), encoding="utf-8")

    assert load_deterministic_report(path) == report


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ("both-owners", "invariants\\[0\\]"),
        ("unknown-bind", "binds\\[0\\]"),
        ("duplicate-bind", "duplicate bind relation"),
        ("duplicate-declaration", "binds\\[0\\]"),
        ("section-collision", "binds\\[0\\]"),
        ("both-issue-ids", "issues\\[0\\]"),
        ("non-invariant-id", "issues\\[0\\]"),
        ("invariant-section-id", "issues\\[0\\]"),
    ],
)
def test_load_deterministic_report_rejects_invalid_invariant_relations(
    tmp_path: Path,
    mutation: str,
    match: str,
) -> None:
    path = tmp_path / "report.json"
    report = _empty_report(tmp_path)
    invariant = {
        "invariant_id": "INV.LOAD.1",
        "statement": "Loaded reports preserve relations.",
        "tier": "required",
        "declaration_kind": "code",
        "path": "pkg/x.py",
        "line": 2,
        "owner_symbol": "load",
        "section_id": None,
    }
    binding = {
        "invariant_id": "INV.LOAD.1",
        "test_path": "tests/test_x.py",
        "test_symbol": "test_load",
        "marker_line": 4,
        "start_line": 3,
        "end_line": 6,
    }
    report["invariants"] = [invariant]
    report["binds"] = [binding]
    summary = report["summary"]
    assert isinstance(summary, dict)
    summary["invariants"] = 1
    if mutation == "both-owners":
        invariant["section_id"] = "X-1"
    elif mutation == "unknown-bind":
        binding["invariant_id"] = "INV.UNKNOWN.1"
    elif mutation == "duplicate-bind":
        report["binds"] = [binding, dict(binding, marker_line=8)]
    elif mutation == "duplicate-declaration":
        report["invariants"] = [invariant, dict(invariant, line=8)]
        summary["invariants"] = 2
    elif mutation == "section-collision":
        report["spec_sections"] = [
            {
                "path": "docs/specs/01-x.md",
                "section_id": "INV.LOAD.1",
                "title": "Collision",
                "line": 3,
                "anchor": "collision-invload1",
                "kind": "heading",
            }
        ]
        summary["spec_sections"] = 1
    elif mutation == "both-issue-ids":
        issue = _issue()
        issue["section_id"] = "X-1"
        issue["invariant_id"] = "INV.LOAD.1"
        report["issues"] = [issue]
        summary["errors"] = 1
    elif mutation == "non-invariant-id":
        issue = _issue()
        issue["invariant_id"] = "INV.LOAD.1"
        report["issues"] = [issue]
        summary["errors"] = 1
    else:
        issue = _issue(
            code="INVARIANT_UNTESTED",
            short_code="BSI001",
            context="required",
            default_severity="error",
        )
        issue["section_id"] = "X-1"
        report["issues"] = [issue]
        summary["errors"] = 1
    path.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(ValueError, match=match):
        load_deterministic_report(path)


@pytest.mark.parametrize(
    ("summary_key", "bad_value"),
    [
        ("spec_sections", "missing"),
        ("code_refs", True),
        ("spec_mappings", "0"),
        ("invariants", 1),
        ("errors", -1),
    ],
)
def test_load_deterministic_report_rejects_bad_summary_counts(
    tmp_path: Path,
    summary_key: str,
    bad_value: object,
) -> None:
    path = tmp_path / "report.json"
    report = _empty_report(tmp_path)
    summary = report["summary"]
    assert isinstance(summary, dict)
    if bad_value == "missing":
        del summary[summary_key]
    else:
        summary[summary_key] = bad_value
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match=summary_key):
        load_deterministic_report(path)


def test_load_deterministic_report_rejects_summary_disagreement(
    tmp_path: Path,
) -> None:
    path = tmp_path / "report.json"
    report = _empty_report(tmp_path)
    summary = report["summary"]
    assert isinstance(summary, dict)
    summary["spec_sections"] = 1
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="summary counts disagree"):
        load_deterministic_report(path)
