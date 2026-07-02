"""Probes 8-9: malformed model output contained; concurrency deterministic.

Spec: docs/specs/02-backstitch-core.md [SC-7], [SC-10]

The model boundary is the single permitted fake in acceptance probes
([SC-10]): these run in-process with an injected adapter because a black-box
probe would otherwise require a live model.
"""

from __future__ import annotations

import json

from backstitch.analysis_llm import analyze_packets, render_results_jsonl


def _packet(pid: str) -> dict:
    return {
        "packet_id": pid,
        "instructions": "return JSON",
        "section_id": pid,
    }


def _row(pid: str) -> str:
    return json.dumps(
        {
            "packet_id": pid,
            "classification": "ok",
            "confidence": 0.9,
            "summary": f"fine {pid}",
            "evidence": [],
        }
    )


def test_probe_8_malformed_model_output_contained_per_packet() -> None:
    packets = [_packet("a#A-1"), _packet("b#B-1"), _packet("c#C-1")]

    def adapter(prompt: str) -> str:
        if "b#B-1" in prompt:
            return "NOT JSON AT ALL {"
        pid = next(p["packet_id"] for p in packets if p["packet_id"] in prompt)
        return _row(pid)

    rows, errors = analyze_packets(packets, adapter, 1)
    # One bad response yields one error record; the others survive.
    assert len(rows) == 2
    assert len(errors) == 1
    assert "b#B-1" in errors[0]


def test_probe_9_concurrent_output_byte_identical_to_serial() -> None:
    packets = [_packet(f"p{i}#S-{i}") for i in range(12)]

    def adapter(prompt: str) -> str:
        pid = next(p["packet_id"] for p in packets if p["packet_id"] in prompt)
        return _row(pid)

    serial_rows, _ = analyze_packets(packets, adapter, 1)
    parallel_rows, _ = analyze_packets(packets, adapter, 4)
    assert render_results_jsonl(parallel_rows) == render_results_jsonl(
        serial_rows
    )
