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

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "backstitch", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )


def test_probe_13_self_acceptance_round_trip(tmp_path: Path) -> None:
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

    # Real packets pass analyze's packet loading (proven by reaching model
    # selection with a hermetic model name, which fails AFTER validation).
    packets_path = tmp_path / "packets.jsonl"
    result = _run(
        "packets",
        "--repo-root",
        str(REPO_ROOT),
        "--output",
        str(packets_path),
    )
    assert result.returncode == 0, result.stderr
    assert packets_path.read_text(encoding="utf-8").strip(), "no packets emitted"
    result = _run(
        "analyze",
        "--packets",
        str(packets_path),
        "--no-config",
        "--model",
        "backstitch-hermetic-model-that-must-not-exist",
    )
    assert result.returncode == 2
    assert "Unknown model" in result.stderr, result.stderr
    assert "malformed packet" not in result.stderr

    # analyze's own error records pass validate_analysis_row.
    from backstitch.analysis_llm import analyze_packets, render_results_jsonl
    from backstitch.analysis_results import load_analysis_results

    packet = json.loads(packets_path.read_text(encoding="utf-8").splitlines()[0])
    rows, errors = analyze_packets([packet], lambda prompt: "not json")
    assert errors, "garbage response must be recorded as an error"
    load = load_analysis_results(render_results_jsonl(rows), None)
    assert load.errors == ()
    assert load.results[0].classification == "ambiguous"
