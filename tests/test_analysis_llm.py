"""Semantic analysis tests with a fake model adapter (no network).

Spec: docs/specs/02-backstitch-core.md [SC-7]
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from backstitch.analysis_llm import analyze_packets, build_prompt

PACKET_A = {
    "packet_id": "docs/specs/01-X.md#X-1",
    "spec_path": "docs/specs/01-X.md",
    "section_id": "X-1",
    "title": "Thing",
    "section_text": "## Thing [X-1]\n\nMust frob.",
    "owners": [
        {"path": "pkg/mod.py", "symbol": None, "start_line": 1, "snippet": "x = 1"}
    ],
    "tests": [],
    "issues": [],
    "warnings": [],
    "instructions": "Respond with JSON including packet_id and classification.",
}
PACKET_B = dict(PACKET_A, packet_id="docs/specs/01-X.md#X-2", section_id="X-2")

# [SC-7] hermetic testing: a name no local `llm` alias could plausibly
# resolve, so CLI tests can never construct a real adapter or call a model.
HERMETIC_MODEL = "backstitch-hermetic-model-that-must-not-exist"


def _ok_response(packet_id: str) -> str:
    return json.dumps(
        {
            "packet_id": packet_id,
            "classification": "ok",
            "confidence": 0.8,
            "rationale": "fine",
            "evidence": [{"path": "pkg/mod.py", "line": 1}],
            "summary": "looks implemented",
        }
    )


def test_prompt_contains_instructions_and_packet_but_not_duplicated() -> None:
    prompt = build_prompt(PACKET_A)
    assert prompt.startswith(PACKET_A["instructions"])
    assert "Must frob." in prompt
    assert PACKET_A["packet_id"] in prompt
    # The instructions field itself is stripped from the embedded packet.
    assert prompt.count("Respond with JSON") == 1


def test_analyze_iterates_packets_and_collects_rows() -> None:
    prompts_seen: list[str] = []

    def adapter(prompt: str) -> str:
        prompts_seen.append(prompt)
        row = json.loads(prompt.split("\n\n", 1)[1])
        return _ok_response(row["packet_id"])

    rows, errors = analyze_packets([PACKET_A, PACKET_B], adapter)
    assert errors == []
    assert [r["packet_id"] for r in rows] == [
        PACKET_A["packet_id"],
        PACKET_B["packet_id"],
    ]
    assert len(prompts_seen) == 2


def test_fenced_model_output_is_parsed() -> None:
    def adapter(prompt: str) -> str:
        return f"```json\n{_ok_response(PACKET_A['packet_id'])}\n```"

    rows, errors = analyze_packets([PACKET_A], adapter)
    assert errors == []
    assert rows[0]["classification"] == "ok"


def test_malformed_model_output_yields_ambiguous_record() -> None:
    # [SC-7]: one bad response yields one `ambiguous`/error record for the
    # packet -- the packet never vanishes from the results JSONL.
    rows, errors = analyze_packets([PACKET_A], lambda prompt: "I cannot help")
    assert len(rows) == 1
    assert rows[0]["packet_id"] == PACKET_A["packet_id"]
    assert rows[0]["classification"] == "ambiguous"
    assert "analysis error" in rows[0]["summary"]
    assert len(errors) == 1
    assert PACKET_A["packet_id"] in errors[0]
    # The record reaches the rendered JSONL and passes consumer validation.
    from backstitch.analysis_llm import render_results_jsonl
    from backstitch.analysis_results import validate_analysis_row

    rendered = render_results_jsonl(rows)
    assert rendered.strip(), "error record missing from rendered JSONL"
    validated = validate_analysis_row(json.loads(rendered), {PACKET_A["packet_id"]})
    assert not isinstance(validated, str), validated


def test_wrong_packet_id_in_output_is_error_record() -> None:
    # [SC-7]: the record's packet_id comes from the packet, never from the
    # (hallucinated) model response.
    rows, errors = analyze_packets(
        [PACKET_A], lambda prompt: _ok_response("docs/specs/99.md#Z-9")
    )
    assert len(rows) == 1
    assert rows[0]["packet_id"] == PACKET_A["packet_id"]
    assert rows[0]["classification"] == "ambiguous"
    assert any("packet_id" in e for e in errors)


def test_adapter_exception_is_error_for_that_packet_only() -> None:
    def adapter(prompt: str) -> str:
        if PACKET_A["packet_id"] in prompt:
            raise RuntimeError("model unavailable")
        return _ok_response(PACKET_B["packet_id"])

    rows, errors = analyze_packets([PACKET_A, PACKET_B], adapter)
    assert [r["packet_id"] for r in rows] == [
        PACKET_A["packet_id"],
        PACKET_B["packet_id"],
    ]
    assert rows[0]["classification"] == "ambiguous"
    assert rows[1]["classification"] == "ok"
    assert len(errors) == 1
    assert "model unavailable" in errors[0]


def test_concurrency_preserves_packet_order() -> None:
    def adapter(prompt: str) -> str:
        row = json.loads(prompt.split("\n\n", 1)[1])
        return _ok_response(row["packet_id"])

    packets = [
        dict(PACKET_A, packet_id=f"docs/specs/01-X.md#X-{i}", section_id=f"X-{i}")
        for i in range(6)
    ]
    rows, errors = analyze_packets(packets, adapter, concurrency=4)
    assert errors == []
    assert [r["packet_id"] for r in rows] == [p["packet_id"] for p in packets]


def test_missing_instructions_field_is_error_record_not_crash() -> None:
    packet = {k: v for k, v in PACKET_A.items() if k != "instructions"}
    rows, errors = analyze_packets([packet], lambda prompt: "unused")
    assert len(rows) == 1
    assert rows[0]["classification"] == "ambiguous"
    assert any("instructions" in e for e in errors)


def test_analyze_exit_code_rules() -> None:
    from backstitch.analysis_llm import analyze_exit_code

    # [SC-5]: analyze never exits 1 (semantic findings are advisory; 1 is
    # reserved for deterministic target findings). Total failure -- every
    # packet errored -- is a tool/model statement: exit 2. Partial exits 0.
    assert analyze_exit_code([], []) == 0
    assert analyze_exit_code([{"packet_id": "x"}], []) == 0
    assert (
        analyze_exit_code([{"packet_id": "x"}, {"packet_id": "y"}], ["one failed"]) == 0
    )
    assert analyze_exit_code([{"packet_id": "x"}], ["all failed"]) == 2


def test_analyze_model_flag_is_optional() -> None:
    from backstitch.cli import build_parser

    args = build_parser().parse_args(["analyze", "--packets", "p.jsonl"])
    assert args.model is None


def test_default_adapter_without_name_uses_llm_default_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Hermetic proof of OUR wiring: with no name, default_adapter must call
    # llm.get_model() with no argument (llm then applies its configured
    # default). The model boundary is the one acceptable fake.
    import llm

    from backstitch.analysis_llm import default_adapter

    calls: list[tuple] = []

    class _FakeModel:
        def prompt(self, text: str) -> object:
            raise AssertionError("adapter construction must not prompt")

    def fake_get_model(*args: object) -> _FakeModel:
        calls.append(args)
        return _FakeModel()

    monkeypatch.setattr(llm, "get_model", fake_get_model)
    adapter = default_adapter(None)
    assert callable(adapter)
    assert calls == [()]


def test_cli_analyze_non_object_packet_line_exits_two(tmp_path: Path) -> None:
    packets = tmp_path / "packets.jsonl"
    packets.write_text("42\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "backstitch",
            "analyze",
            "--packets",
            str(packets),
            "--model",
            HERMETIC_MODEL,
            "--no-config",
            "--output",
            str(tmp_path / "out.jsonl"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "not a JSON object" in result.stderr


def test_cli_analyze_missing_packets_file_exits_two(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "backstitch",
            "analyze",
            "--packets",
            str(tmp_path / "missing.jsonl"),
            "--model",
            HERMETIC_MODEL,
            "--no-config",
            "--output",
            str(tmp_path / "out.jsonl"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert result.stderr
