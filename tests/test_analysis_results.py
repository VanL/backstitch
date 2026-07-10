"""Analysis result validation and summary tests.

Spec: docs/specs/02-backstitch-core.md [SC-6], [SC-7]
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from backstitch.analysis_results import (
    load_analysis_results,
    packet_identities_from_report,
    render_analysis_summary,
)
from backstitch.profiles import get_profile
from backstitch.resolver import scan_repository

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


def test_invariant_result_variant_loads() -> None:
    load = load_analysis_results(_invariant_row(), None)
    assert load.errors == ()
    assert load.results[0].kind == "invariant"
    assert load.results[0].content_hash == "a" * 64


def test_analysis_result_kind_vocabulary_is_closed() -> None:
    section = load_analysis_results(_row(classification="weak_binding"), None)
    invariant = load_analysis_results(
        _invariant_row(classification="missing_trace"), None
    )
    assert any("classification" in error for error in section.errors)
    assert any("classification" in error for error in invariant.errors)


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
    report = scan_repository(CLEAN, CLEAN_PROFILE)
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
    }
    assert packet_identities_from_report(report) == {
        "docs/specs/01-x.md#X-1": "section",
        "invariant::INV.BOUND.1": "invariant",
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
    assert result.returncode == 0, result.stderr
    assert "semantic findings (advisory)" in result.stdout
    assert "analysis input problems" in result.stdout


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
