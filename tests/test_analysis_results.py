"""Analysis result validation and summary tests.

Spec: docs/specs/02-backstitch-core.md [SC-6], [SC-7]
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from backstitch.analysis_results import (
    load_analysis_results,
    packet_identities_from_report,
    render_analysis_summary,
)
from backstitch.obligation_runtime import build_obligation_runtime
from backstitch.profiles import get_profile
from backstitch.settings import BackstitchSettings

FIXTURES = Path(__file__).parent / "fixtures"
CLEAN = FIXTURES / "clean_project"
CLEAN_PROFILE = get_profile("backstitch-style-v1").with_overrides(
    spec_roots=("docs/specs",), code_roots=("pkg",)
)

PACKET_ID = "docs/specs/01-Clean.md#CLEAN-1"

VALID_ROW: dict[str, Any] = {
    "packet_id": PACKET_ID,
    "classification": "ok",
    "confidence": 0.9,
    "rationale": "snippet matches the spec",
    "evidence": [{"path": "pkg/mod.py", "line": 8}],
    "summary": "implementation matches",
}


def _row(**overrides: object) -> str:
    row = dict(VALID_ROW)
    row.update(overrides)
    return json.dumps(row)


def test_valid_rows_load() -> None:
    load = load_analysis_results(_row() + "\n", {PACKET_ID})
    assert load.errors == ()
    assert len(load.results) == 1
    result = load.results[0]
    assert result.classification == "ok"
    assert result.confidence == 0.9
    assert result.kind == "section"
    assert result.content_hash is None


def _invariant_row(**overrides: object) -> str:
    row: dict[str, object] = {
        "packet_id": "invariant::INV.CLEAN.1",
        "kind": "invariant",
        "content_hash": "a" * 64,
        "classification": "weak_binding",
        "confidence": 0.7,
        "rationale": "the assertion is indirect",
        "evidence": [],
        "summary": "binding is weak",
    }
    row.update(overrides)
    return json.dumps(row)


def _v2_result_row(kind: str, classification: str) -> str:
    packet_id = PACKET_ID if kind == "section" else "invariant::INV.CLEAN.1"
    row: dict[str, object] = {
        "schema_version": 2,
        "packet_id": packet_id,
        "kind": kind,
        "packet_hash": "a" * 64,
        "analysis_key": "b" * 64,
        "classification": classification,
        "confidence": 0.5,
        "rationale": "bounded evidence",
        "summary": "Reviewed.",
        "evidence": [],
        "verification_state": "evidence_bound",
    }
    if kind == "invariant":
        row["content_hash"] = "c" * 64
    return json.dumps(row)


def _v3_suppression_result_row(
    classification: str = "rationale_insufficient",
) -> dict[str, object]:
    excerpt = "Generated code cannot carry a stable reciprocal backlink."
    return {
        "schema_version": 3,
        "packet_id": "suppression::docs/specs/01-Clean.md#SUP-GEN",
        "kind": "suppression",
        "packet_hash": "a" * 64,
        "analysis_key": "b" * 64,
        "classification": classification,
        "confidence": 0.5,
        "rationale": "The stated exception is not bounded.",
        "summary": "Suppression rationale needs review.",
        "evidence": [
            {
                "role": "requirement",
                "path": "docs/specs/01-Clean.md",
                "start_line": 8,
                "end_line": 8,
                "excerpt": excerpt,
                "excerpt_sha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
            }
        ],
        "verification_state": "evidence_bound",
    }


def test_current_suppression_result_uses_schema_3_and_closed_identity() -> None:
    row = _v3_suppression_result_row()

    load = load_analysis_results(json.dumps(row), None)

    assert load.errors == ()
    assert load.results[0].kind == "suppression"
    assert load.results[0].content_hash is None

    for field, replacement in (
        ("schema_version", 2),
        ("packet_id", "suppression::docs/specs/01-Clean.md#bad"),
        ("kind", "section"),
    ):
        changed = dict(row)
        changed[field] = replacement
        assert load_analysis_results(json.dumps(changed), None).errors
    forged_section = dict(row, schema_version=2, kind="section")
    assert load_analysis_results(json.dumps(forged_section), None).errors


def test_invariant_result_variant_loads() -> None:
    load = load_analysis_results(_invariant_row(), None)
    assert load.errors == ()
    assert load.results[0].kind == "invariant"
    assert load.results[0].content_hash == "a" * 64


def test_current_invariant_result_omits_legacy_content_hash() -> None:
    row = json.loads(_v2_result_row("invariant", "ambiguous"))
    row.pop("content_hash")
    excerpt = "Invariant must remain true."
    row["evidence"] = [
        {
            "role": "requirement",
            "path": "docs/specs/invariants.md",
            "start_line": 3,
            "end_line": 3,
            "excerpt": excerpt,
            "excerpt_sha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
        }
    ]

    load = load_analysis_results(json.dumps(row), None)

    assert load.errors == ()
    assert load.results[0].content_hash is None


def test_current_result_accepts_packet_region_with_trailing_blank_lines() -> None:
    row = json.loads(_v2_result_row("section", "ambiguous"))
    excerpt = "Requirement text.\n\n"
    row["evidence"] = [
        {
            "role": "requirement",
            "path": "docs/specs/01-Clean.md",
            "start_line": 3,
            "end_line": 5,
            "excerpt": excerpt,
            "excerpt_sha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
        }
    ]

    load = load_analysis_results(json.dumps(row), None)

    assert load.errors == ()


def test_current_result_presentation_accepts_advisory_counterevidence() -> None:
    row = json.loads(_v2_result_row("section", "ambiguous"))
    evidence = []
    for role, path, line, excerpt in (
        ("requirement", "docs/specs/01-Clean.md", 3, "Must return one."),
        ("counterevidence", "pkg/decoy.py", 8, "return 2"),
    ):
        evidence.append(
            {
                "role": role,
                "path": path,
                "start_line": line,
                "end_line": line,
                "excerpt": excerpt,
                "excerpt_sha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
            }
        )
    row["evidence"] = sorted(
        evidence,
        key=lambda item: (
            item["role"],
            item["path"],
            item["start_line"],
            item["end_line"],
            item["excerpt_sha256"],
        ),
    )

    load = load_analysis_results(json.dumps(row), None)

    assert load.errors == ()


def test_analysis_result_kind_vocabulary_is_closed() -> None:
    section = load_analysis_results(_row(classification="weak_binding"), None)
    invariant = load_analysis_results(
        _invariant_row(classification="missing_trace"), None
    )
    assert any("classification" in error for error in section.errors)
    assert any("classification" in error for error in invariant.errors)


@pytest.mark.parametrize(
    ("kind", "classification"),
    [
        ("section", "confirmed_mismatch"),
        ("section", "probable_mismatch"),
        ("section", "missing_trace"),
        ("section", "ambiguous"),
        ("invariant", "ok"),
        ("invariant", "weak_binding"),
        ("invariant", "confirmed_mismatch"),
        ("invariant", "probable_mismatch"),
        ("invariant", "ambiguous"),
    ],
)
def test_v2_presentation_rejects_every_missing_required_role_set(
    kind: str, classification: str
) -> None:
    load = load_analysis_results(_v2_result_row(kind, classification), None)

    assert load.results == ()
    assert len(load.errors) == 1
    assert "missing required evidence roles" in load.errors[0]


def test_analysis_result_legacy_and_partial_union_rules() -> None:
    legacy = load_analysis_results(_row(), None)
    assert legacy.errors == ()
    assert legacy.results[0].kind == "section"

    cases = (
        _row(kind="section", content_hash=None),
        _row(kind=None),
        _invariant_row(content_hash=None),
        _invariant_row(content_hash="A" * 64),
        _invariant_row(kind=None),
    )
    for text in cases:
        load = load_analysis_results(text, None)
        assert load.results == ()
        assert load.errors


def test_schema_less_legacy_result_cannot_be_reinterpreted_as_suppression() -> None:
    forged = _invariant_row(
        kind="suppression",
        classification="rationale_insufficient",
    )

    load = load_analysis_results(forged, None)

    assert load.results == ()
    assert len(load.errors) == 1
    assert "expected `section` or `invariant`" in load.errors[0]


def test_result_kind_must_match_report_derived_identity() -> None:
    identities = {
        PACKET_ID: "section",
        "invariant::INV.CLEAN.1": "invariant",
    }
    forged = _row(
        packet_id=PACKET_ID,
        kind="invariant",
        content_hash="a" * 64,
        classification="weak_binding",
    )
    load = load_analysis_results(forged, identities)
    assert load.results == ()
    assert any("identity" in error or "kind" in error for error in load.errors)


def test_invalid_json_row_is_analysis_error_not_crash() -> None:
    load = load_analysis_results("not json at all\n" + _row() + "\n", None)
    assert len(load.results) == 1
    assert len(load.errors) == 1
    assert "line 1" in load.errors[0]


def test_unknown_packet_id_is_analysis_error() -> None:
    load = load_analysis_results(
        _row(packet_id="docs/specs/01-Clean.md#NOPE-1") + "\n",
        {PACKET_ID},
    )
    assert load.results == ()
    assert any("unknown packet" in e for e in load.errors)


def test_unsupported_classification_is_analysis_error() -> None:
    load = load_analysis_results(_row(classification="probably_fine") + "\n", None)
    assert load.results == ()
    assert any("classification" in e for e in load.errors)


def test_boolean_confidence_is_rejected() -> None:
    load = load_analysis_results(_row(confidence=True) + "\n", None)
    assert load.results == ()
    assert any("confidence" in e for e in load.errors)


def test_null_rationale_is_absent_when_confidence_is_present() -> None:
    load = load_analysis_results(_row(rationale=None), None)
    assert load.errors == ()
    assert load.results[0].rationale == ""


def test_missing_required_field_is_analysis_error() -> None:
    row = {k: v for k, v in VALID_ROW.items() if k != "summary"}
    load = load_analysis_results(json.dumps(row) + "\n", None)
    assert load.results == ()
    assert any("summary" in e for e in load.errors)


def test_summary_separates_deterministic_from_semantic() -> None:
    report = build_obligation_runtime(
        CLEAN, CLEAN_PROFILE, BackstitchSettings()
    ).pipeline.raw_report
    load = load_analysis_results(
        _row(classification="probable_mismatch") + "\n" + _invariant_row(),
        None,
    )
    text = render_analysis_summary(report.summary(), load)
    assert "deterministic" in text
    assert "semantic findings (advisory)" in text
    assert "section packets:" in text
    assert "invariant packets:" in text
    assert "probable_mismatch" in text
    assert "weak_binding" in text
    # Semantic findings never alter deterministic counts [SC-7].
    assert "0 errors" in text


def test_packet_identities_include_only_packet_eligible_invariants() -> None:
    report = {
        "edges": [
            {
                "spec_path": "docs/specs/01-x.md",
                "section_id": "X-1",
            }
        ],
        "binds": [
            {"invariant_id": "INV.BOUND.1"},
            {"invariant_id": "INV.BOUND.1"},
        ],
        "invariants": [
            {"invariant_id": "INV.BOUND.1"},
            {"invariant_id": "INV.UNTESTED.1"},
        ],
        "suppressed_issues": [
            {"declaration": "docs/specs/04-exclusions.md#SUP-ONE"},
            {"declaration": "docs/specs/04-exclusions.md#SUP-ONE"},
            {"declaration": None},
        ],
    }
    assert packet_identities_from_report(report) == {
        "docs/specs/01-x.md#X-1": "section",
        "invariant::INV.BOUND.1": "invariant",
        "suppression::docs/specs/04-exclusions.md#SUP-ONE": "suppression",
    }


def test_cli_summarize_analysis(tmp_path: Path) -> None:
    report_path = tmp_path / "spec-trace.json"
    results_path = tmp_path / "analysis.jsonl"
    check = subprocess.run(
        [
            sys.executable,
            "-m",
            "backstitch",
            "check",
            "--repo-root",
            str(CLEAN),
            "--spec-root",
            "docs/specs",
            "--code-root",
            "pkg",
            "--no-config",
            "--format",
            "json",
            "--output",
            str(report_path),
        ],
        capture_output=True,
        text=True,
    )
    assert check.returncode == 0, check.stderr
    results_path.write_text(_row() + "\nbroken row\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "backstitch",
            "summarize-analysis",
            "--deterministic-report",
            str(report_path),
            "--analysis-results",
            str(results_path),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert "invalid analysis results" in result.stderr


def test_cli_summarize_analysis_malformed_report_exits_two(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "bad.json"
    report_path.write_text("{not json", encoding="utf-8")
    results_path = tmp_path / "analysis.jsonl"
    results_path.write_text("", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "backstitch",
            "summarize-analysis",
            "--deterministic-report",
            str(report_path),
            "--analysis-results",
            str(results_path),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert result.stderr
