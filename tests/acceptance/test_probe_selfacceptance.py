"""Probe 13: self-acceptance round-trip ([SC-13] self-acceptance).

Spec: docs/specs/02-backstitch-core.md [SC-10], [SC-13]

Every machine-readable artifact the tool writes must survive the tool's
own reading: validators reject forgeries AND accept real output. The model
boundary is the single permitted fake ([SC-10]).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from backstitch.semantic_reports import load_analysis_report
from tests.acceptance.conftest import SemanticAnalysisHarness

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "backstitch", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )


def test_probe_13_self_acceptance_round_trip(
    tmp_path: Path,
    semantic_analysis_harness: SemanticAnalysisHarness,
) -> None:
    # A real check report passes summarize-analysis validation unchanged.
    report_path = tmp_path / "report.json"
    result = _run(
        "check",
        "--repo-root",
        str(REPO_ROOT),
        "--format",
        "json",
        "--output",
        str(report_path),
    )
    assert result.returncode == 0, result.stderr
    rows_path = tmp_path / "rows.jsonl"
    rows_path.write_text("", encoding="utf-8")
    result = _run(
        "summarize-analysis",
        "--deterministic-report",
        str(report_path),
        "--analysis-results",
        str(rows_path),
    )
    assert result.returncode == 0, result.stderr

    # A real aligned fixture passes packet/report loading. The repository's
    # broader source corpus intentionally retains active alignment debt, so it
    # is not a valid complete-current packet corpus yet.
    aligned_root = REPO_ROOT / "tests/product_eval/phase_c/fixtures/aligned-base"
    packets_path = tmp_path / "packets.jsonl"
    packet_report_path = tmp_path / "packet-report.json"
    result = _run(
        "packets",
        "--repo-root",
        str(aligned_root),
        "--kind",
        "all",
        "--output",
        str(packets_path),
        "--report",
        str(packet_report_path),
    )
    assert result.returncode == 0, result.stderr
    assert packets_path.read_text(encoding="utf-8").strip(), "no packets emitted"
    result = _run(
        "analyze",
        "--packets",
        str(packets_path),
        "--packet-report",
        str(packet_report_path),
        "--no-config",
        "--model",
        "backstitch-hermetic-model-that-must-not-exist",
        "--output",
        str(tmp_path / "analysis.jsonl"),
    )
    assert result.returncode == 2
    assert "Unknown model" in result.stderr, result.stderr
    assert "malformed packet" not in result.stderr

    # The production runner publishes and accepts its closed failed report.
    packet = json.loads(packets_path.read_text(encoding="utf-8").splitlines()[0])
    run, request = semantic_analysis_harness(
        packets=[packet],
        adapter=lambda prompt: "not json",
        name="self-acceptance-malformed",
    )
    assert run.exit_code == 2
    assert run.results == ()
    assert [(problem.stage, problem.code) for problem in run.problems] == [
        ("normalization", "malformed_result")
    ]
    assert request.report_path is not None
    assert request.result_path is not None
    loaded = load_analysis_report(
        request.report_path,
        result_jsonl=request.result_path.read_bytes(),
        packet_report=request.packet_report,
        packets=request.packets,
        expected_scope=request.scope,
        expected_semantic_status=request.semantic_status,
        expected_artifact_currentness=request.artifact_currentness,
        expected_source_provenance=request.source_provenance,
    )
    loaded_row = loaded.to_dict()
    assert loaded_row["status"] == "failed"
    assert loaded_row["analysis_exit_code"] == 2
