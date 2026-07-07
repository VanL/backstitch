"""Artifact trust-boundary validators.

Spec: docs/specs/02-backstitch-core.md [SC-6], [SC-13]
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backstitch.artifact_contracts import load_deterministic_report, load_packets


def _packet() -> dict[str, object]:
    return {
        "packet_id": "docs/specs/01-x.md#X-1",
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


def _empty_report(tmp_path: Path) -> dict[str, object]:
    return {
        "profile": "backstitch-style-v1",
        "repo_root": str(tmp_path),
        "summary": {
            "spec_sections": 0,
            "code_refs": 0,
            "spec_mappings": 0,
            "errors": 0,
            "warnings": 0,
            "infos": 0,
        },
        "spec_sections": [],
        "code_refs": [],
        "spec_mappings": [],
        "edges": [],
        "issues": [],
    }


def test_load_packets_accepts_full_packet_contract(tmp_path: Path) -> None:
    path = tmp_path / "packets.jsonl"
    packet = _packet()
    path.write_text(json.dumps(packet) + "\n", encoding="utf-8")
    assert load_packets(path) == [packet]


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


@pytest.mark.parametrize(
    ("summary_key", "bad_value"),
    [
        ("spec_sections", "missing"),
        ("code_refs", True),
        ("spec_mappings", "0"),
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
