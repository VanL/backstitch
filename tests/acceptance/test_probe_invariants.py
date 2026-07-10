"""Black-box invariant traceability probes ([SC-10], [INV-9])."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from tests.acceptance.conftest import REPO_ROOT, run_cli

HERMETIC_MODEL = "backstitch-hermetic-model-that-must-not-exist"


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


def _expected_hash(packet: dict[str, Any]) -> str:
    fields = ("path", "symbol", "start_line", "snippet")
    projection = {
        "statement": packet["statement"],
        "targets": [{key: item[key] for key in fields} for item in packet["targets"]],
        "binding_tests": [
            {key: item[key] for key in fields} for item in packet["binding_tests"]
        ],
    }
    encoded = json.dumps(
        projection, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
    assert report["summary"]["invariants"] == 3
    assert {item["invariant_id"] for item in report["invariants"]} == {
        "INV.CLI.1",
        "INV.RES.1",
        "INV.RES.2",
    }
    assert {
        (item["invariant_id"], item["test_path"], item["test_symbol"])
        for item in report["binds"]
    } == {
        (
            "INV.CLI.1",
            "tests/test_cli.py",
            "test_deterministic_commands_do_not_import_llm",
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
    assert partial_exits == {1}

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
        "INV.CLI.1",
        "INV.RES.1",
        "INV.RES.2",
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
        "INV.CLI.1",
        "INV.RES.1",
        "INV.RES.2",
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
    assert paths_by_kind["all"].read_bytes() == (
        paths_by_kind["section"].read_bytes() + paths_by_kind["invariant"].read_bytes()
    )
    assert {row["kind"] for row in rows_by_kind["section"]} == {"section"}
    assert {row["kind"] for row in rows_by_kind["invariant"]} == {"invariant"}
    assert [row["packet_id"] for row in rows_by_kind["all"]] == [
        *[row["packet_id"] for row in rows_by_kind["section"]],
        *[row["packet_id"] for row in rows_by_kind["invariant"]],
    ]
    assert [row["kind"] for row in rows_by_kind["all"]] == [
        *(["section"] * len(rows_by_kind["section"])),
        *(["invariant"] * len(rows_by_kind["invariant"])),
    ]
    empty = next(
        row for row in rows_by_kind["invariant"] if row["invariant_id"] == "INV.SPEC.2"
    )
    assert empty["targets"] == []
    assert any(
        "no target code resolved for spec-declared invariant" in warning
        for warning in empty["packet_warnings"]
    )
    assert not [
        warning
        for row in rows_by_kind["invariant"]
        if row["invariant_id"] != "INV.SPEC.2"
        for warning in row["packet_warnings"]
        if "no target code resolved for spec-declared invariant" in warning
    ]
    for row in rows_by_kind["invariant"]:
        assert re.fullmatch(r"[0-9a-f]{64}", row["content_hash"])
        assert row["content_hash"] == _expected_hash(row)
    invariant_hashes = {
        row["packet_id"]: row["content_hash"] for row in rows_by_kind["invariant"]
    }
    assert invariant_hashes == {
        row["packet_id"]: row["content_hash"]
        for row in rows_by_kind["all"]
        if row["kind"] == "invariant"
    }


def test_probe_invariant_new_and_legacy_artifacts_self_accept(
    invariant_packet_repo: Path,
    tmp_path: Path,
) -> None:
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
    result = run_cli(
        "packets",
        *_scan_args(invariant_packet_repo),
        "--kind",
        "all",
        "--output",
        str(all_packets),
    )
    assert result.returncode == 0, result.stderr
    packets = _jsonl(all_packets)
    result = run_cli(
        "analyze",
        "--packets",
        str(all_packets),
        "--no-config",
        "--model",
        HERMETIC_MODEL,
    )
    assert result.returncode == 2
    assert "Unknown model" in result.stderr
    assert "malformed packet" not in result.stderr

    section_packet = next(row for row in packets if row["kind"] == "section")
    invariant_packet = next(row for row in packets if row["kind"] == "invariant")
    results_path = tmp_path / "results.jsonl"
    results_path.write_text(
        json.dumps(
            {
                "packet_id": section_packet["packet_id"],
                "kind": "section",
                "classification": "ok",
                "confidence": 0.5,
                "summary": "section result",
                "evidence": [],
            }
        )
        + "\n"
        + json.dumps(
            {
                "packet_id": invariant_packet["packet_id"],
                "kind": "invariant",
                "content_hash": invariant_packet["content_hash"],
                "classification": "weak_binding",
                "confidence": 0.5,
                "summary": "invariant result",
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

    legacy_packet = dict(section_packet)
    del legacy_packet["kind"]
    legacy_packets_path = tmp_path / "legacy-packet.jsonl"
    legacy_packets_path.write_text(json.dumps(legacy_packet) + "\n", encoding="utf-8")
    result = run_cli(
        "analyze",
        "--packets",
        str(legacy_packets_path),
        "--no-config",
        "--model",
        HERMETIC_MODEL,
    )
    assert result.returncode == 2
    assert "Unknown model" in result.stderr
    assert "malformed packet" not in result.stderr

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
