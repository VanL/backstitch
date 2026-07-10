"""Semantic analysis tests with a fake model adapter (no network).

Spec: docs/specs/02-backstitch-core.md [SC-7]
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest

from backstitch.analysis_llm import analyze_packets, build_prompt

PACKET_A: dict[str, Any] = {
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
PACKET_B: dict[str, Any] = dict(
    PACKET_A, packet_id="docs/specs/01-X.md#X-2", section_id="X-2"
)
INVARIANT_PACKET: dict[str, Any] = {
    "packet_id": "invariant::INV.X.1",
    "kind": "invariant",
    "invariant_id": "INV.X.1",
    "tier": "required",
    "statement": "The result remains one.",
    "declaration": {
        "kind": "code",
        "path": "pkg/mod.py",
        "line": 10,
        "symbol": "run",
        "section_id": None,
    },
    "targets": [
        {
            "path": "pkg/mod.py",
            "symbol": "run",
            "start_line": 10,
            "snippet": "def run():\n    return 1",
        }
    ],
    "binding_tests": [
        {
            "path": "tests/test_mod.py",
            "symbol": "test_run",
            "start_line": 20,
            "snippet": "def test_run():\n    assert run() == 1",
        }
    ],
    "issues": [],
    "packet_warnings": [],
    "instructions": "Respond with JSON including a rationale.",
    "content_hash": "a" * 64,
}

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
        row = cast(dict[str, Any], json.loads(prompt.split("\n\n", 1)[1]))
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


def test_unexpected_model_output_type_is_contained_per_packet() -> None:
    rows, errors = analyze_packets(
        [PACKET_A], lambda prompt: cast(str, {"not": "text"})
    )
    assert rows[0]["classification"] == "ambiguous"
    assert any("output processing failed" in error for error in errors)


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
        row = cast(dict[str, Any], json.loads(prompt.split("\n\n", 1)[1]))
        return _ok_response(row["packet_id"])

    packets = [
        dict(PACKET_A, packet_id=f"docs/specs/01-X.md#X-{i}", section_id=f"X-{i}")
        for i in range(6)
    ]
    rows, errors = analyze_packets(packets, adapter, concurrency=4)
    assert errors == []
    assert [r["packet_id"] for r in rows] == [p["packet_id"] for p in packets]


def _invariant_response(
    *,
    classification: str = "ok",
    evidence: list[dict[str, object]] | None = None,
    **extra: object,
) -> str:
    row: dict[str, object] = {
        "packet_id": INVARIANT_PACKET["packet_id"],
        "classification": classification,
        "summary": "binding reviewed",
        "rationale": "shown evidence supports the result",
        "evidence": evidence if evidence is not None else [],
    }
    row.update(extra)
    return json.dumps(row)


def test_invariant_ok_requires_binding_test_evidence() -> None:
    target_only = [{"path": "pkg/mod.py", "line": 11}]
    rows, errors = analyze_packets(
        [INVARIANT_PACKET],
        lambda prompt: _invariant_response(evidence=target_only),
    )
    assert errors == []
    assert rows[0]["classification"] == "weak_binding"

    rows, errors = analyze_packets(
        [INVARIANT_PACKET],
        lambda prompt: _invariant_response(
            evidence=[{"path": "tests/test_mod.py", "line": 21}]
        ),
    )
    assert errors == []
    assert rows[0]["classification"] == "ok"


def test_invariant_zero_evidence_normalizes_ok_to_weak_binding() -> None:
    rows, errors = analyze_packets(
        [INVARIANT_PACKET], lambda prompt: _invariant_response()
    )
    assert errors == []
    assert rows[0]["classification"] == "weak_binding"


def test_model_cannot_launder_invariant_kind_or_hash() -> None:
    from backstitch.analysis_llm import render_results_jsonl
    from backstitch.analysis_results import load_analysis_results

    rows, errors = analyze_packets(
        [INVARIANT_PACKET],
        lambda prompt: _invariant_response(
            classification="weak_binding",
            kind="section",
            content_hash="f" * 64,
        ),
    )
    assert errors == []
    assert rows[0]["kind"] == "invariant"
    assert rows[0]["content_hash"] == INVARIANT_PACKET["content_hash"]
    load = load_analysis_results(
        render_results_jsonl(rows),
        {INVARIANT_PACKET["packet_id"]: "invariant"},
    )
    assert load.errors == ()


@pytest.mark.parametrize(
    ("packet", "classification"),
    [(PACKET_A, "weak_binding"), (INVARIANT_PACKET, "missing_trace")],
)
def test_wrong_kind_classification_is_contained_per_packet(
    packet: dict[str, Any],
    classification: str,
) -> None:
    packet_id = packet["packet_id"]
    response = json.dumps(
        {
            "packet_id": packet_id,
            "classification": classification,
            "summary": "wrong vocabulary",
            "rationale": "wrong vocabulary",
            "evidence": [],
        }
    )
    rows, errors = analyze_packets([packet], lambda prompt: response)
    assert rows[0]["classification"] == "ambiguous"
    assert len(errors) == 1


def test_invariant_evidence_must_be_inside_shown_target_or_test_range() -> None:
    rows, errors = analyze_packets(
        [INVARIANT_PACKET],
        lambda prompt: _invariant_response(
            evidence=[{"path": "tests/test_mod.py", "line": 999}]
        ),
    )
    assert rows[0]["classification"] == "ambiguous"
    assert any("outside the packet's shown content" in error for error in errors)

    rows, errors = analyze_packets(
        [INVARIANT_PACKET],
        lambda prompt: _invariant_response(
            evidence=[{"path": "tests/omitted.py", "line": 1}]
        ),
    )
    assert rows[0]["classification"] == "ambiguous"
    assert any("not part of the packet" in error for error in errors)


def test_empty_invariant_binding_snippet_has_no_citable_range() -> None:
    packet = dict(
        INVARIANT_PACKET,
        binding_tests=[
            {
                "path": "tests/test_mod.py",
                "symbol": "test_run",
                "start_line": 20,
                "snippet": "",
            }
        ],
    )
    rows, errors = analyze_packets(
        [packet],
        lambda prompt: _invariant_response(
            evidence=[{"path": "tests/test_mod.py", "line": 20}]
        ),
    )
    assert rows[0]["classification"] == "ambiguous"
    assert any("fabricated" in error for error in errors)


def test_mixed_kind_concurrency_preserves_packet_and_metadata_order() -> None:
    packets = [PACKET_A, INVARIANT_PACKET, PACKET_B]

    def adapter(prompt: str) -> str:
        packet = cast(dict[str, Any], json.loads(prompt.split("\n\n", 1)[1]))
        if packet.get("kind") == "invariant":
            return _invariant_response(classification="weak_binding")
        return _ok_response(packet["packet_id"])

    rows, errors = analyze_packets(packets, adapter, concurrency=3)

    assert errors == []
    assert [row["packet_id"] for row in rows] == [
        packet["packet_id"] for packet in packets
    ]
    assert [row["kind"] for row in rows] == ["section", "invariant", "section"]
    assert "content_hash" not in rows[0]
    assert rows[1]["content_hash"] == INVARIANT_PACKET["content_hash"]


def test_invariant_error_record_keeps_trusted_metadata_and_self_validates() -> None:
    from backstitch.analysis_llm import render_results_jsonl
    from backstitch.analysis_results import load_analysis_results

    rows, errors = analyze_packets([INVARIANT_PACKET], lambda prompt: "not json")
    load = load_analysis_results(render_results_jsonl(rows), None)

    assert len(errors) == 1
    assert load.errors == ()
    assert load.results[0].kind == "invariant"
    assert load.results[0].content_hash == INVARIANT_PACKET["content_hash"]


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


def test_default_adapter_requests_json_mode_when_model_supports_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Constrained decoding: when the resolved model's Options declares the
    # `json_object` field (llm's OpenAI-compatible models, cloud and
    # api_base-registered alike), the adapter must request provider-enforced
    # JSON output. The model boundary is the one acceptable fake.
    import llm

    from backstitch.analysis_llm import default_adapter

    prompts: list[tuple[str, dict[str, object]]] = []

    class _Response:
        def text(self) -> str:
            return "{}"

    class _JsonCapableModel:
        class Options:
            model_fields = {"json_object": object()}

        def prompt(self, text: str, **options: object) -> _Response:
            prompts.append((text, options))
            return _Response()

    monkeypatch.setattr(llm, "get_model", lambda *a: _JsonCapableModel())
    adapter = default_adapter("any-model")
    assert adapter("hello") == "{}"
    assert prompts == [("hello", {"json_object": True})]


def test_default_adapter_omits_json_mode_when_model_lacks_the_option(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Provider-neutral capability gate: a model whose Options does not
    # declare `json_object` (non-OpenAI plugins) must get the unchanged
    # call — passing an unknown option would raise inside llm.
    import llm

    from backstitch.analysis_llm import default_adapter

    prompts: list[tuple[str, dict[str, object]]] = []

    class _Response:
        def text(self) -> str:
            return "plain"

    class _PlainModel:
        class Options:
            model_fields = {"temperature": object()}

        def prompt(self, text: str, **options: object) -> _Response:
            if options:
                raise AssertionError(f"unexpected options: {options}")
            prompts.append((text, options))
            return _Response()

    monkeypatch.setattr(llm, "get_model", lambda *a: _PlainModel())
    adapter = default_adapter("any-model")
    assert adapter("hello") == "plain"
    assert prompts == [("hello", {})]


def test_default_adapter_falls_back_when_server_rejects_json_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The Options field proves the llm wrapper accepts `json_object`, not
    # that the server accepts `response_format`. A rejecting server must not
    # be worse off than before JSON mode existed: the failed JSON-mode call
    # falls back to a bare call, and subsequent calls skip JSON mode.
    import llm

    from backstitch.analysis_llm import default_adapter

    prompts: list[tuple[str, dict[str, object]]] = []

    class _Response:
        def text(self) -> str:
            return "bare"

    class _RejectingModel:
        class Options:
            model_fields = {"json_object": object()}

        def prompt(self, text: str, **options: object) -> _Response:
            prompts.append((text, options))
            if options.get("json_object"):
                raise RuntimeError("server rejected response_format")
            return _Response()

    monkeypatch.setattr(llm, "get_model", lambda *a: _RejectingModel())
    adapter = default_adapter("any-model")
    assert adapter("first") == "bare"
    assert adapter("second") == "bare"
    assert prompts == [
        ("first", {"json_object": True}),  # attempted once
        ("first", {}),  # fell back for the same prompt
        ("second", {}),  # JSON mode disabled for the adapter
    ]


def test_default_adapter_error_propagates_when_bare_call_also_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The fallback must not swallow genuine model failures: when the bare
    # retry also fails, the exception propagates so analyze contains it as a
    # per-packet error record exactly as before JSON mode existed.
    import llm

    from backstitch.analysis_llm import default_adapter

    class _BrokenModel:
        class Options:
            model_fields = {"json_object": object()}

        def prompt(self, text: str, **options: object) -> object:
            raise RuntimeError("model is down")

    monkeypatch.setattr(llm, "get_model", lambda *a: _BrokenModel())
    adapter = default_adapter("any-model")
    with pytest.raises(RuntimeError, match="model is down"):
        adapter("hello")


def test_llm_chat_options_map_json_object_to_response_format() -> None:
    # Dependency-contract pin against the installed llm (uv.lock pins 0.31):
    # extra-openai-models registrations become Chat, whose Options must keep
    # declaring `json_object` and mapping it to response_format json_object.
    # If a future llm drops or renames this, the adapter silently loses
    # constrained decoding — this test makes that loud. No network involved.
    from llm.default_plugins.openai_models import Chat

    model = Chat("backstitch-contract-probe", api_base="http://127.0.0.1:1/v1")
    assert "json_object" in model.Options.model_fields

    class _FakePrompt:
        prompt = "respond in JSON"
        system = None
        attachments = ()
        fragments = ()
        system_fragments = ()
        tools = ()
        schema = None
        options = model.Options(json_object=True)

    kwargs = model.build_kwargs(_FakePrompt(), stream=False)
    assert kwargs.get("response_format") == {"type": "json_object"}


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
