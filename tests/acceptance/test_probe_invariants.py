"""Black-box invariant traceability probes ([SC-10], [INV-9])."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from backstitch.semantic_identity import (
    ProviderIdentity,
    RequestIdentity,
    build_inference_identity,
)
from backstitch.semantic_packets import semantic_packet_hash
from tests.acceptance.conftest import REPO_ROOT, run_cli

HERMETIC_MODEL = "backstitch-hermetic-model-that-must-not-exist"
_REPORT_PROVIDER = ProviderIdentity(
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
_REPORT_REQUEST = RequestIdentity("require", 0.0, 0, 512)


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _scan_args(root: Path) -> tuple[str, ...]:
    return (
        "--repo-root",
        str(root),
        "--no-config",
        "--spec-root",
        "docs/specs",
        "--plan-root",
        "docs/plans",
        "--code-root",
        "pkg",
        "--code-root",
        "tests",
        "--test-root",
        "tests",
    )


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


@pytest.fixture
def invariant_diagnostics_repo(tmp_path: Path) -> Path:
    _write(tmp_path, "docs/plans/.keep", "")
    _write(
        tmp_path,
        "docs/specs/01-invariants.md",
        "# Invariants\n\n"
        "## Bound [IP-1]\n\n"
        "Invariant: [INV.SPEC.1] the mapped function remains callable\n\n"
        "_Implementation mapping_:\n\n- `pkg/target.py::run`\n\n"
        "## Untested [IP-2]\n\n"
        "Invariant: [INV.UNTESTED.1] this declaration has no binding\n\n"
        "```text\nInvariant: [INV.PHANTOM.1] fenced sample\n```\n",
    )
    _write(
        tmp_path,
        "pkg/target.py",
        "def run() -> int:\n"
        '    """Spec: docs/specs/01-invariants.md [IP-1]\n\n'
        "    Invariant: [INV.CODE.1] the function returns one\n"
        '    """\n'
        "    return 1\n",
    )
    _write(
        tmp_path,
        "pkg/dup_a.py",
        '"""Invariant: [INV.DUP.1] first duplicate"""\n',
    )
    _write(
        tmp_path,
        "pkg/dup_b.py",
        '"""Invariant: [INV.DUP.1] second duplicate"""\n',
    )
    _write(
        tmp_path,
        "pkg/invalid.py",
        '"""Invariant: [not-valid] malformed identifier"""\n',
    )
    _write(
        tmp_path,
        "pkg/phantom.py",
        'sample = "Invariant: [INV.PHANTOM.2] ordinary string"\n',
    )
    _write(
        tmp_path,
        "tests/test_target.py",
        "def test_code() -> None:\n"
        '    """Tests-invariant: [INV.CODE.1]"""\n'
        "    assert True\n\n"
        "def test_spec() -> None:\n"
        '    """Tests-invariant: [INV.SPEC.1]"""\n'
        "    assert True\n\n"
        "def test_unknown() -> None:\n"
        '    """Tests-invariant: [INV.UNKNOWN.1]"""\n'
        "    assert True\n\n"
        "def helper() -> None:\n"
        '    """Tests-invariant: [INV.NOT.1]"""\n'
        "    pass\n",
    )
    return tmp_path


@pytest.fixture
def invariant_packet_repo(tmp_path: Path) -> Path:
    _write(tmp_path, "docs/plans/.keep", "")
    _write(
        tmp_path,
        "docs/specs/01-packets.md",
        "# Packets\n\n"
        "## Mapped [PK-1]\n\n"
        "Invariant: [INV.SPEC.1] mapped guarantee\n\n"
        "_Implementation mapping_:\n\n- `pkg/mod.py::run`\n\n"
        "## Targetless [PK-2]\n\n"
        "Invariant: [INV.SPEC.2] targetless guarantee\n",
    )
    _write(
        tmp_path,
        "pkg/mod.py",
        "def run() -> int:\n"
        '    """Spec: docs/specs/01-packets.md [PK-1]\n\n'
        "    Invariant: [INV.CODE.1] code guarantee\n"
        '    """\n'
        "    return 1\n",
    )
    _write(
        tmp_path,
        "tests/test_mod.py",
        "def test_code() -> None:\n"
        '    """Tests-invariant: [INV.CODE.1]"""\n'
        "    assert True\n\n"
        "def test_mapped() -> None:\n"
        '    """Tests-invariant: [INV.SPEC.1]"""\n'
        "    assert True\n\n"
        "def test_empty() -> None:\n"
        '    """Tests-invariant: [INV.SPEC.2]"""\n'
        "    assert True\n",
    )
    return tmp_path


def _repair_targetless_invariant(root: Path) -> None:
    spec = root / "docs/specs/01-packets.md"
    spec.write_text(
        spec.read_text(encoding="utf-8") + "\n_Implementation mapping_:\n\n"
        "- `pkg/targetless.py::targetless`\n",
        encoding="utf-8",
    )
    _write(
        root,
        "pkg/targetless.py",
        "def targetless() -> int:\n"
        '    """Spec: docs/specs/01-packets.md [PK-2]"""\n'
        "    return 2\n",
    )


def test_probe_invariant_dogfood_and_root_override_contract(tmp_path: Path) -> None:
    result = run_cli(
        "check",
        "--repo-root",
        str(REPO_ROOT),
        "--show-suppressions",
        "--format",
        "json",
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["summary"]["invariants"] == 8
    assert {item["invariant_id"] for item in report["invariants"]} == {
        "INV.CANON.1",
        "INV.CFG.2",
        "INV.CLI.1",
        "INV.LINE.1",
        "INV.PERF.1",
        "INV.RES.1",
        "INV.RES.2",
        "INV.SCAN.1",
    }
    assert {
        (item["invariant_id"], item["test_path"], item["test_symbol"])
        for item in report["binds"]
    } == {
        (
            "INV.CANON.1",
            "tests/test_canonical_owners.py",
            "test_canonical_json_has_one_production_owner",
        ),
        (
            "INV.CANON.1",
            "tests/test_canonical_owners.py",
            "test_sha256_and_candidate_grammars_have_one_production_owner",
        ),
        (
            "INV.CANON.1",
            "tests/test_canonical_owners.py",
            "test_issue_sort_key_has_one_production_owner",
        ),
        (
            "INV.CANON.1",
            "tests/test_canonical_owners.py",
            "test_no_follow_read_and_stat_identity_have_one_owner_module",
        ),
        (
            "INV.CFG.2",
            "tests/test_evidence_spike_boundary_pins.py",
            "test_concrete_obligation_dataclass_defaults_equal_packaged_defaults",
        ),
        (
            "INV.CLI.1",
            "tests/test_cli.py",
            "test_deterministic_commands_do_not_import_llm",
        ),
        (
            "INV.LINE.1",
            "tests/test_canonical_owners.py",
            "test_line_arithmetic_uses_the_lf_only_owner",
        ),
        (
            "INV.LINE.1",
            "tests/test_semantic_packets.py",
            "test_non_lf_characters_preserve_receipts_and_citable_regions",
        ),
        (
            "INV.PERF.1",
            "tests/test_evidence_spike_cache_perf_pins.py",
            "test_default_check_performs_zero_static_syntax_fact_derivations",
        ),
        (
            "INV.PERF.1",
            "tests/test_evidence_spike_cache_perf_pins.py",
            "test_default_check_captures_an_already_covered_mapping_target_once",
        ),
        (
            "INV.PERF.1",
            "tests/test_evidence_spike_cache_perf_pins.py",
            "test_self_corpus_default_check_uses_one_external_snapshot_capture",
        ),
        (
            "INV.PERF.1",
            "tests/test_evidence_spike_cache_perf_pins.py",
            "test_obligation_list_parses_each_unique_python_file_at_most_once",
        ),
        (
            "INV.RES.1",
            "tests/test_resolver.py",
            "test_report_is_stable_across_runs",
        ),
        (
            "INV.RES.2",
            "tests/test_resolver_ladder.py",
            "test_ladder_multiple_candidates_ambiguous_error_no_edge",
        ),
        (
            "INV.SCAN.1",
            "tests/test_evidence_spike_cache_perf_pins.py",
            "test_live_scan_and_legacy_packet_twins_have_no_production_owner",
        ),
    }
    assert not [
        issue for issue in report["issues"] if issue["code"].startswith("INVARIANT_")
    ]
    assert not [
        issue
        for issue in report["suppressed_issues"]
        if issue["code"].startswith("INVARIANT_")
    ]

    partial_exits: set[int] = set()
    partial_outputs: list[Path] = []
    for kind in ("section", "invariant", "all"):
        output = tmp_path / f"partial-{kind}.jsonl"
        partial = run_cli(
            "packets",
            "--repo-root",
            str(REPO_ROOT),
            "--code-root",
            "backstitch",
            "--kind",
            kind,
            "--output",
            str(output),
        )
        partial_exits.add(partial.returncode)
        assert partial.stderr == ""
        partial_outputs.append(output)
    assert partial_exits == {1}
    assert all(not output.exists() for output in partial_outputs)

    partial = run_cli(
        "check",
        "--repo-root",
        str(REPO_ROOT),
        "--code-root",
        "backstitch",
        "--format",
        "json",
    )
    assert partial.returncode == 1
    partial_report = json.loads(partial.stdout)
    partial_invariant_issues = [
        issue
        for issue in partial_report["issues"]
        if issue["code"].startswith("INVARIANT_")
    ]
    assert {issue["short_code"] for issue in partial_invariant_issues} == {"BSI001"}
    assert {issue["invariant_id"] for issue in partial_invariant_issues} == {
        "INV.CANON.1",
        "INV.CFG.2",
        "INV.CLI.1",
        "INV.LINE.1",
        "INV.PERF.1",
        "INV.RES.1",
        "INV.RES.2",
        "INV.SCAN.1",
    }

    restored = run_cli(
        "check",
        "--repo-root",
        str(REPO_ROOT),
        "--test-root",
        "tests",
        "--format",
        "json",
    )
    assert restored.returncode == 0, restored.stderr
    restored_report = json.loads(restored.stdout)
    assert {item["invariant_id"] for item in restored_report["binds"]} == {
        "INV.CANON.1",
        "INV.CFG.2",
        "INV.CLI.1",
        "INV.LINE.1",
        "INV.PERF.1",
        "INV.RES.1",
        "INV.RES.2",
        "INV.SCAN.1",
    }
    assert not [
        issue
        for issue in restored_report["issues"]
        if issue["code"].startswith("INVARIANT_")
    ]


def test_probe_all_bsi_codes_fire_without_marker_leakage(
    invariant_diagnostics_repo: Path,
) -> None:
    result = run_cli(
        "check",
        *_scan_args(invariant_diagnostics_repo),
        "--format",
        "json",
    )
    assert result.returncode == 1, result.stderr
    report = json.loads(result.stdout)
    invariant_issue_rows = [
        issue for issue in report["issues"] if issue["code"].startswith("INVARIANT_")
    ]
    assert Counter(issue["code"] for issue in invariant_issue_rows) == {
        "INVARIANT_UNTESTED": 1,
        "INVARIANT_UNKNOWN": 1,
        "INVARIANT_DUPLICATE": 1,
        "INVARIANT_BINDING_NOT_TEST": 1,
        "INVARIANT_MARKER_INVALID": 1,
    }
    assert {issue["code"]: issue["short_code"] for issue in invariant_issue_rows} == {
        "INVARIANT_UNTESTED": "BSI001",
        "INVARIANT_UNKNOWN": "BSI002",
        "INVARIANT_DUPLICATE": "BSI003",
        "INVARIANT_BINDING_NOT_TEST": "BSI004",
        "INVARIANT_MARKER_INVALID": "BSI005",
    }
    assert {issue["code"]: issue["invariant_id"] for issue in invariant_issue_rows} == {
        "INVARIANT_UNTESTED": "INV.UNTESTED.1",
        "INVARIANT_UNKNOWN": "INV.UNKNOWN.1",
        "INVARIANT_DUPLICATE": "INV.DUP.1",
        "INVARIANT_BINDING_NOT_TEST": "INV.NOT.1",
        "INVARIANT_MARKER_INVALID": None,
    }
    assert not [
        section_id
        for ref in report["code_refs"]
        for section_id in ref["section_ids"]
        if section_id.startswith("INV.")
    ]
    assert not [
        edge for edge in report["edges"] if edge["section_id"].startswith("INV.")
    ]
    phantom_ids = {
        "INV.PHANTOM.1",
        "INV.PHANTOM.2",
    }
    assert not phantom_ids.intersection(
        item["invariant_id"] for item in report["invariants"]
    )
    assert not phantom_ids.intersection(
        item["invariant_id"] for item in report["binds"]
    )
    assert not phantom_ids.intersection(
        issue["invariant_id"]
        for issue in report["issues"]
        if issue["invariant_id"] is not None
    )


def test_probe_invariant_packet_kinds_order_targetless_and_hash(
    invariant_packet_repo: Path,
    tmp_path: Path,
) -> None:
    inspection_rows: dict[str, list[dict[str, Any]]] = {}
    for kind in ("section", "invariant", "all"):
        output = tmp_path / f"inspection-{kind}.jsonl"
        result = run_cli(
            "packets",
            *_scan_args(invariant_packet_repo),
            "--kind",
            kind,
            "--output",
            str(output),
        )
        assert result.returncode == 0, result.stderr
        inspection_rows[kind] = _jsonl(output)
    for rows in inspection_rows.values():
        assert not {
            "docs/specs/01-packets.md#PK-2",
            "invariant::INV.SPEC.2",
        }.intersection(row["obligation_id"] for row in rows)
    assert {row["kind"] for row in inspection_rows["section"]} == {"section"}
    assert {row["kind"] for row in inspection_rows["invariant"]} == {"invariant"}

    _repair_targetless_invariant(invariant_packet_repo)
    rows_by_kind: dict[str, list[dict[str, Any]]] = {}
    paths_by_kind: dict[str, Path] = {}
    exits: set[int] = set()
    for kind in ("section", "invariant", "all"):
        output = tmp_path / f"{kind}.jsonl"
        result = run_cli(
            "packets",
            *_scan_args(invariant_packet_repo),
            "--kind",
            kind,
            "--output",
            str(output),
        )
        exits.add(result.returncode)
        rows_by_kind[kind] = _jsonl(output)
        paths_by_kind[kind] = output
    default_output = tmp_path / "default.jsonl"
    default_result = run_cli(
        "packets",
        *_scan_args(invariant_packet_repo),
        "--output",
        str(default_output),
    )
    exits.add(default_result.returncode)
    assert exits == {0}
    assert default_output.read_bytes() == paths_by_kind["section"].read_bytes()
    assert {row["kind"] for row in rows_by_kind["section"]} == {"section"}
    assert {row["kind"] for row in rows_by_kind["invariant"]} == {"invariant"}
    assert [
        row for row in rows_by_kind["all"] if row["kind"] == "section"
    ] == rows_by_kind["section"]
    assert [
        row for row in rows_by_kind["all"] if row["kind"] == "invariant"
    ] == rows_by_kind["invariant"]
    assert [
        (
            row["requirement"]["path"],
            row["requirement"]["start_line"],
            row["obligation_id"],
        )
        for row in rows_by_kind["all"]
    ] == sorted(
        (
            row["requirement"]["path"],
            row["requirement"]["start_line"],
            row["obligation_id"],
        )
        for row in rows_by_kind["all"]
    )
    empty = next(
        row
        for row in rows_by_kind["invariant"]
        if row["obligation_id"] == "invariant::INV.SPEC.2"
    )
    assert {item["role"] for item in empty["declared_evidence"]} == {
        "implementation",
        "test",
    }
    assert empty["packet_warnings"] == []
    for row in rows_by_kind["all"]:
        assert re.fullmatch(r"[0-9a-f]{64}", row["packet_hash"])
        assert row["packet_hash"] == semantic_packet_hash(row)
    invariant_hashes = {
        row["packet_id"]: row["packet_hash"] for row in rows_by_kind["invariant"]
    }
    assert invariant_hashes == {
        row["packet_id"]: row["packet_hash"]
        for row in rows_by_kind["all"]
        if row["kind"] == "invariant"
    }


def test_probe_invariant_new_and_legacy_artifacts_self_accept(
    invariant_packet_repo: Path,
    tmp_path: Path,
) -> None:
    _repair_targetless_invariant(invariant_packet_repo)
    report_path = tmp_path / "report.json"
    result = run_cli(
        "check",
        *_scan_args(invariant_packet_repo),
        "--format",
        "json",
        "--output",
        str(report_path),
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(report_path.read_text(encoding="utf-8"))

    all_packets = tmp_path / "all.jsonl"
    packet_report_path = tmp_path / "packet-report.json"
    result = run_cli(
        "packets",
        *_scan_args(invariant_packet_repo),
        "--kind",
        "all",
        "--output",
        str(all_packets),
        "--report",
        str(packet_report_path),
    )
    assert result.returncode == 0, result.stderr
    packets = _jsonl(all_packets)
    result = run_cli(
        "analyze",
        "--packets",
        str(all_packets),
        "--packet-report",
        str(packet_report_path),
        "--no-config",
        "--model",
        HERMETIC_MODEL,
        "--output",
        str(tmp_path / "analysis.jsonl"),
    )
    assert result.returncode == 2
    assert "Unknown model" in result.stderr
    assert "malformed packet" not in result.stderr

    section_packet = next(row for row in packets if row["kind"] == "section")
    invariant_packet = next(row for row in packets if row["kind"] == "invariant")
    binding_test = next(
        item for item in invariant_packet["declared_evidence"] if item["role"] == "test"
    )
    binding_excerpt = binding_test["snippet"]
    results_path = tmp_path / "results.jsonl"
    results_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "packet_id": section_packet["packet_id"],
                "kind": "section",
                "packet_hash": section_packet["packet_hash"],
                "analysis_key": "a" * 64,
                "classification": "ok",
                "confidence": 0.5,
                "rationale": "The section is supported.",
                "summary": "section result",
                "evidence": [],
                "verification_state": "evidence_bound",
            }
        )
        + "\n"
        + json.dumps(
            {
                "schema_version": 2,
                "packet_id": invariant_packet["packet_id"],
                "kind": "invariant",
                "packet_hash": invariant_packet["packet_hash"],
                "analysis_key": "b" * 64,
                "classification": "ok",
                "confidence": 0.5,
                "rationale": "The invariant binding is supported.",
                "summary": "invariant result",
                "evidence": [
                    {
                        "role": "test",
                        "path": binding_test["path"],
                        "start_line": binding_test["start_line"],
                        "end_line": binding_test["end_line"],
                        "excerpt": binding_excerpt,
                        "excerpt_sha256": hashlib.sha256(
                            binding_excerpt.encode("utf-8")
                        ).hexdigest(),
                    }
                ],
                "verification_state": "evidence_bound",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    result = run_cli(
        "summarize-analysis",
        "--deterministic-report",
        str(report_path),
        "--analysis-results",
        str(results_path),
    )
    assert result.returncode == 0, result.stderr
    assert "section packets:" in result.stdout
    assert "invariant packets:" in result.stdout
    assert section_packet["packet_id"] in result.stdout
    assert invariant_packet["packet_id"] in result.stdout
    assert "analysis input problems" not in result.stdout

    legacy_report = dict(report)
    legacy_report["summary"] = dict(report["summary"])
    del legacy_report["summary"]["invariants"]
    del legacy_report["invariants"]
    del legacy_report["binds"]
    legacy_report["issues"] = [dict(issue) for issue in report["issues"]]
    for issue in legacy_report["issues"]:
        issue.pop("invariant_id", None)
    legacy_report_path = tmp_path / "legacy-report.json"
    legacy_report_path.write_text(json.dumps(legacy_report), encoding="utf-8")
    empty_results = tmp_path / "empty-results.jsonl"
    empty_results.write_text("", encoding="utf-8")
    result = run_cli(
        "summarize-analysis",
        "--deterministic-report",
        str(legacy_report_path),
        "--analysis-results",
        str(empty_results),
    )
    assert result.returncode == 0, result.stderr

    legacy_packet = {
        "packet_id": "docs/specs/01-packets.md#PK-1",
        "spec_path": "docs/specs/01-packets.md",
        "section_id": "PK-1",
        "title": "Mapped",
        "section_text": "Mapped invariant section.",
        "section_start_line": 3,
        "owners": [],
        "tests": [],
        "issues": [],
        "packet_warnings": [],
        "instructions": "legacy instructions are discarded",
    }
    legacy_packets_path = tmp_path / "legacy-packet.jsonl"
    legacy_packets_path.write_text(json.dumps(legacy_packet) + "\n", encoding="utf-8")
    from backstitch.artifact_contracts import load_packets
    from backstitch.semantic_reports import build_packet_report

    legacy_validated = load_packets(legacy_packets_path)
    legacy_packet_report_path = tmp_path / "legacy-packet-report.json"
    legacy_packet_report_path.write_bytes(
        build_packet_report(
            packet_jsonl=legacy_packets_path.read_bytes(),
            packets=legacy_validated,
            identities=tuple(
                build_inference_identity(
                    packet.to_dict(),
                    _REPORT_PROVIDER,
                    _REPORT_REQUEST,
                )
                for packet in legacy_validated
            ),
            kind="section",
            eligible_counts={"section": 1, "invariant": 0},
        ).to_json_bytes()
    )
    result = run_cli(
        "analyze",
        "--packets",
        str(legacy_packets_path),
        "--packet-report",
        str(legacy_packet_report_path),
        "--no-config",
        "--model",
        HERMETIC_MODEL,
        "--output",
        str(tmp_path / "legacy-analysis.jsonl"),
    )
    assert result.returncode == 2
    assert "schema 3" in result.stderr
    assert "Unknown model" not in result.stderr

    legacy_result_path = tmp_path / "legacy-result.jsonl"
    legacy_result_path.write_text(
        json.dumps(
            {
                "packet_id": section_packet["packet_id"],
                "classification": "ok",
                "confidence": 0.5,
                "summary": "legacy section result",
                "evidence": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    result = run_cli(
        "summarize-analysis",
        "--deterministic-report",
        str(report_path),
        "--analysis-results",
        str(legacy_result_path),
    )
    assert result.returncode == 0, result.stderr
    assert "analysis input problems" not in result.stdout
