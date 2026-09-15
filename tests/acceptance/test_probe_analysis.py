"""Probes 8-9: malformed model output contained; concurrency deterministic.

Spec: docs/specs/02-backstitch-core.md [SC-7], [SC-10]
Spec: docs/specs/06-semantic-gates.md [SEM-10]

The model boundary is the single permitted fake in acceptance probes
([SC-10]): these run in-process with an injected adapter because a black-box
probe would otherwise require a live model.
"""

from __future__ import annotations

import json

from backstitch.semantic_reports import load_analysis_report
from tests.acceptance.conftest import SemanticAnalysisHarness, semantic_packet


def _packet(pid: str) -> dict:
    return semantic_packet(pid)


def _row(pid: str) -> str:
    return json.dumps(
        {
            "packet_id": pid,
            "assessment": {"classification": "ok", "evidence": {}},
            "confidence": 0.9,
            "summary": f"fine {pid}",
            "rationale": "bounded packet is consistent",
        }
    )


def test_probe_8_malformed_model_output_contained_per_packet(
    semantic_analysis_harness: SemanticAnalysisHarness,
) -> None:
    packets = [_packet("a#A-1"), _packet("b#B-1"), _packet("c#C-1")]

    def adapter(prompt: str) -> str:
        if "b#B-1" in prompt:
            return "NOT JSON AT ALL {"
        pid = next(p["packet_id"] for p in packets if p["packet_id"] in prompt)
        return _row(pid)

    run, request = semantic_analysis_harness(packets=packets, adapter=adapter)
    # [SC-7]: one bad response yields one problem and no v2 row; later
    # packets continue and successful rows retain packet order.
    assert run.exit_code == 2
    assert [r["packet_id"] for r in run.results] == ["a#A-1", "c#C-1"]
    assert [r["classification"] for r in run.results] == ["ok", "ok"]
    assert [
        (problem.packet_id, problem.stage, problem.code) for problem in run.problems
    ] == [("b#B-1", "normalization", "malformed_result")]
    assert request.result_path is not None
    assert request.result_path.read_bytes() == run.result_jsonl
    assert request.report_path is not None
    loaded = load_analysis_report(
        request.report_path,
        result_jsonl=run.result_jsonl,
        packet_jsonl_sha256=request.packet_jsonl_sha256,
        packet_report=request.packet_report,
        packets=request.packets,
        expected_scope="historical_snapshot",
        expected_semantic_status="historical_replay",
        expected_artifact_currentness="unverifiable",
        expected_source_provenance="claimed_unverified",
    )
    loaded_row = loaded.to_dict()
    assert loaded_row["status"] == "failed"
    assert loaded_row["analysis_exit_code"] == 2
    assert loaded_row["result_count"] == 2


def test_probe_9_concurrent_output_byte_identical_to_serial(
    semantic_analysis_harness: SemanticAnalysisHarness,
) -> None:
    packets = [_packet(f"p{i}#S-{i}") for i in range(12)]

    def adapter(prompt: str) -> str:
        pid = next(p["packet_id"] for p in packets if p["packet_id"] in prompt)
        return _row(pid)

    serial, _ = semantic_analysis_harness(
        packets=packets,
        adapter=adapter,
        concurrency=1,
        name="serial",
    )
    parallel, _ = semantic_analysis_harness(
        packets=packets,
        adapter=adapter,
        concurrency=4,
        name="parallel",
    )
    assert serial.exit_code == parallel.exit_code == 0
    assert parallel.result_jsonl == serial.result_jsonl
