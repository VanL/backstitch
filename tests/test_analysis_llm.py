"""Shipping provider-adapter tests with a fake model seam.

Spec: docs/specs/02-backstitch-core.md [SC-7], [SC-13]
Spec: docs/specs/06-semantic-gates.md [SEM-3]
"""

from __future__ import annotations

import http.server
import json
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, cast

import pytest

from backstitch.analysis_llm import (
    _install_completion_limit_shim,
    _semantic_response_schema,
    default_provider_adapter,
)
from backstitch.semantic_analysis import resolve_semantic_settings
from backstitch.semantic_evidence import SemanticResultError, normalize_model_result
from backstitch.semantic_identity import (
    CapabilityDescriptor,
    EffectiveRequest,
    ProviderIdentity,
    ReasoningEffort,
    RequestConstraints,
    RequestFieldConstraint,
    RequestIdentity,
    ResolvedInference,
    build_capability_provenance,
    resolve_inference,
)
from backstitch.semantic_packets import (
    model_request_bytes,
    prompt_instruction_bytes,
    semantic_packet_hash,
    semantic_packet_projection,
)
from backstitch.settings import resolve_config

HERMETIC_MODEL = "backstitch-hermetic-model-that-must-not-exist"
REPO_ROOT = Path(__file__).resolve().parents[1]


def _section_packet() -> dict[str, Any]:
    packet: dict[str, Any] = {
        "schema_version": 2,
        "packet_id": "docs/specs/01-X.md#X-1",
        "kind": "section",
        "spec_path": "docs/specs/01-X.md",
        "section_id": "X-1",
        "title": "Thing",
        "section_text": "## Thing [X-1]\n\nMust frob.",
        "section_start_line": 1,
        "owners": [
            {
                "path": "pkg/mod.py",
                "symbol": None,
                "start_line": 1,
                "snippet": "x = 1",
            }
        ],
        "tests": [],
        "issues": [],
        "packet_warnings": [],
    }
    packet["packet_hash"] = semantic_packet_hash(packet)
    return packet


def _provider(model_id: str = "declared-model") -> ProviderIdentity:
    return ProviderIdentity(
        "llm",
        "plugin",
        model_id,
        "declared-revision",
        "backstitch.llm",
        2,
        "0.31.1",
        "llm-plugin",
        "1.2.3",
    )


def _resolved_inference(
    provider: ProviderIdentity,
    *,
    adapter_model_id: str,
    temperature: float | None = 0.0,
    reasoning_effort: ReasoningEffort | None = None,
) -> ResolvedInference:
    constraints = RequestConstraints(
        json_mode=RequestFieldConstraint("required", ("require",), None, None),
        temperature=(
            RequestFieldConstraint("forbidden", None, None, None)
            if temperature is None
            else RequestFieldConstraint("required", (temperature,), None, None)
        ),
        seed=RequestFieldConstraint("required", None, 0, 2**31 - 1),
        max_tokens=RequestFieldConstraint("required", None, 1, 16_384),
        reasoning_effort=(
            RequestFieldConstraint("forbidden", None, None, None)
            if reasoning_effort is None
            else RequestFieldConstraint("required", (reasoning_effort,), None, None)
        ),
    )
    capability = CapabilityDescriptor(
        1,
        "test-v1",
        provider.model_id,
        provider.model_revision,
        constraints,
        1_000_000,
    )
    return resolve_inference(
        provider_identity=provider,
        adapter_model_id=adapter_model_id,
        requested=EffectiveRequest(
            json_mode="require",
            temperature=temperature,
            seed=42,
            max_tokens=256,
            reasoning_effort=reasoning_effort,
        ),
        capability=capability,
        capability_provenance=build_capability_provenance(
            capability,
            source="packaged:test",
        ),
        key_prefix="analyze",
    )


def _prompt(packet: dict[str, Any]) -> str:
    return model_request_bytes(
        packet,
        instruction_bytes=prompt_instruction_bytes("section"),
    ).decode("utf-8")


def test_analyze_model_flag_is_optional() -> None:
    from backstitch.cli import build_parser

    args = build_parser().parse_args(
        ["analyze", "--packets", "p.jsonl", "--output", "out.jsonl"]
    )
    assert args.model is None


def test_openai_reasoning_model_uses_max_completion_tokens_on_the_wire() -> None:
    class _Model:
        def build_kwargs(self, _prompt: object, _stream: bool) -> dict[str, object]:
            return {"max_tokens": 256, "seed": 42}

    model = _Model()
    provider = ProviderIdentity(
        "llm",
        "openai",
        "pkg:service/openai.com/gpt-5.4-mini",
        "gpt-5.4-mini-2026-03-17",
        "backstitch.llm",
        3,
        "0.31.1",
        "llm",
        "0.31.1",
    )

    _install_completion_limit_shim(
        model,
        provider,
        adapter_model_id="gpt-5.4-mini-2026-03-17",
    )

    assert model.build_kwargs(None, False) == {
        "max_completion_tokens": 256,
        "seed": 42,
    }


def test_openai_responses_model_does_not_receive_chat_completion_shim() -> None:
    from llm.default_plugins.openai_models import Responses

    model = Responses("gpt-5.6-luna")
    provider = ProviderIdentity(
        "llm",
        "openai",
        "pkg:service/openai.com/gpt-5.6-luna",
        "gpt-5.6-luna",
        "backstitch.llm",
        4,
        "0.33",
        "llm",
        "0.33",
    )
    original_build_kwargs = model.build_kwargs

    _install_completion_limit_shim(
        model,
        provider,
        adapter_model_id="gpt-5.6-luna",
    )

    assert model.build_kwargs == original_build_kwargs


def test_provider_adapter_sends_exact_request_and_closed_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import llm

    prompts: list[tuple[str, dict[str, object]]] = []

    class _Usage:
        input = 12
        output = 3

    class _Response:
        response_json = {
            "id": "provider-response-1",
            "model": "resolved-model-2026-01-01",
            "model_revision": "2026-01-01",
            "ignored_headers": {"secret": "never cache"},
        }

        def text(self) -> str:
            return '{"packet_id":"x"}'

        def usage(self) -> _Usage:
            return _Usage()

    class _Model:
        supports_schema = True

        class Options:
            model_fields = {
                "json_object": object(),
                "temperature": object(),
                "seed": object(),
                "max_tokens": object(),
                "reasoning_effort": object(),
            }

        def prompt(self, text: str, **options: object) -> _Response:
            prompts.append((text, options))
            return _Response()

    monkeypatch.setattr(llm, "get_model", lambda *args: _Model())
    request = RequestIdentity("require", 0.0, 42, 256, "max")
    adapter = default_provider_adapter(
        "declared-model",
        provider_identity=_provider(),
        request_identity=request,
    )
    packet = _section_packet()
    prompt = _prompt(packet)

    result = adapter(prompt)

    assert result.raw_response == '{"packet_id":"x"}'
    assert result.provenance.adapter_id == "backstitch.llm"
    assert result.provenance.plugin_version == "1.2.3"
    assert result.provenance.model_class is not None
    assert result.provenance.model_class.endswith("._Model")
    assert result.provenance.provider_model_id == "resolved-model-2026-01-01"
    assert result.provenance.provider_model_revision == "2026-01-01"
    assert result.provenance.response_id == "provider-response-1"
    assert result.provenance.input_tokens == 12
    assert result.provenance.output_tokens == 3
    assert set(result.provenance.to_dict()) == {
        "adapter_id",
        "adapter_version",
        "plugin_version",
        "model_class",
        "provider_model_id",
        "provider_model_revision",
        "response_id",
        "input_tokens",
        "output_tokens",
    }
    assert prompts[0][0] == prompt
    assert prompts[0][1]["temperature"] == 0.0
    assert prompts[0][1]["seed"] == 42
    assert prompts[0][1]["max_tokens"] == 256
    assert prompts[0][1]["reasoning_effort"] == "max"
    assert "schema" in prompts[0][1]
    assert "json_object" not in prompts[0][1]


def test_real_llm_responses_wire_shape_and_closed_normalizer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[SC-10]: prove the real wrapper wire path with only HTTP faked."""

    import llm

    packet = _section_packet()
    requirement = semantic_packet_projection(packet)["evidence_regions"][0]
    requirement_coordinate = {
        field: requirement[field] for field in ("path", "start_line", "end_line")
    }
    model_response = {
        "packet_id": packet["packet_id"],
        "assessment": {
            "classification": "ambiguous",
            "evidence": {"requirement": [requirement_coordinate]},
        },
        "confidence": 0.8,
        "rationale": "The bounded evidence does not settle the requirement.",
        "summary": "Evidence remains ambiguous.",
    }
    requests: list[tuple[str, dict[str, Any]]] = []

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - stdlib hook name
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = json.loads(self.rfile.read(length))
            requests.append((self.path, body))
            event = {
                "type": "response.output_text.delta",
                "sequence_number": 1,
                "item_id": "msg_backstitch",
                "output_index": 0,
                "content_index": 0,
                "delta": json.dumps(model_response, separators=(",", ":")),
                "logprobs": [],
            }
            payload = (f"data: {json.dumps(event)}\n\ndata: [DONE]\n\n").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv(
            "OPENAI_BASE_URL", f"http://127.0.0.1:{server.server_port}/v1"
        )
        monkeypatch.setenv("OPENAI_API_KEY", "test-owned-no-network-key")
        model = llm.get_model("gpt-5.6-luna")
        assert (
            f"{type(model).__module__}.{type(model).__qualname__}"
            == "llm.default_plugins.openai_models.Responses"
        )

        settings = resolve_config(REPO_ROOT, environment={}).analyze
        resolved = resolve_semantic_settings(settings)
        assert resolved.inference is not None
        assert (
            resolved.inference.capability.request_constraints.temperature.presence
            == ("forbidden")
        )
        result = default_provider_adapter(resolved.inference)(_prompt(packet))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert len(requests) == 1
    path, body = requests[0]
    assert path == "/v1/responses"
    assert body["model"] == "gpt-5.6-luna"
    assert body["max_output_tokens"] == 16_384
    assert "max_tokens" not in body
    assert "max_completion_tokens" not in body
    assert body["reasoning"] == {"effort": "max"}
    assert "summary" not in body["reasoning"]
    assert "temperature" not in body
    assert "seed" not in body
    assert body["store"] is False
    response_format = body["text"]["format"]
    assert response_format["schema"] == _semantic_response_schema(_prompt(packet))
    assert response_format["strict"] is False

    parsed = json.loads(result.raw_response)
    normalized = normalize_model_result(packet, parsed, analysis_key="a" * 64)
    assert normalized.packet_id == packet["packet_id"]

    with pytest.raises(SemanticResultError, match="closed schema"):
        normalize_model_result(
            packet,
            {**parsed, "unexpected": True},
            analysis_key="a" * 64,
        )
    outside = json.loads(json.dumps(parsed))
    outside["assessment"]["evidence"]["requirement"][0]["path"] = "outside.py"
    with pytest.raises(SemanticResultError):
        normalize_model_result(packet, outside, analysis_key="a" * 64)
    assert len(requests) == 1


def test_real_llm_responses_disables_sdk_transport_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[SC-10]: one logical qualification call is one HTTP attempt."""

    import openai

    request_count = 0

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - stdlib hook name
            nonlocal request_count
            request_count += 1
            length = int(self.headers.get("Content-Length", "0") or "0")
            self.rfile.read(length)
            payload = json.dumps(
                {
                    "error": {
                        "message": "test-owned unavailable response",
                        "type": "server_error",
                        "code": "server_error",
                    }
                }
            ).encode()
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv(
            "OPENAI_BASE_URL", f"http://127.0.0.1:{server.server_port}/v1"
        )
        monkeypatch.setenv("OPENAI_API_KEY", "test-owned-no-network-key")
        settings = resolve_config(REPO_ROOT, environment={}).analyze
        resolved = resolve_semantic_settings(settings)
        assert resolved.inference is not None
        adapter = default_provider_adapter(resolved.inference)

        with pytest.raises(openai.InternalServerError):
            adapter(_prompt(_section_packet()))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert request_count == 1


def test_provider_adapter_uses_raw_transport_without_replacing_stable_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[SEM-3]: the PURL owns identity; only the raw alias reaches ``llm``."""

    import llm

    resolved_names: list[str | None] = []

    class _Response:
        response_json: dict[str, object] = {}

        def text(self) -> str:
            return "{}"

    class _Model:
        supports_schema = True

        class Options:
            model_fields = {
                "json_object": object(),
                "temperature": object(),
                "seed": object(),
                "max_tokens": object(),
            }

        def prompt(self, _text: str, **_options: object) -> _Response:
            return _Response()

    def get_model(name: str | None = None) -> _Model:
        resolved_names.append(name)
        return _Model()

    monkeypatch.setattr(llm, "get_model", get_model)
    stable = _provider("pkg:service/openai/gpt-5.5@2026-04-23")

    adapter = default_provider_adapter(
        _resolved_inference(
            stable,
            adapter_model_id="gpt-5.5-2026-04-23",
            temperature=1.0,
        )
    )
    adapter(_prompt(_section_packet()))

    assert stable.model_id == "pkg:service/openai/gpt-5.5@2026-04-23"
    assert resolved_names == ["gpt-5.5-2026-04-23"]


def test_provider_adapter_constrains_evidence_to_packet_regions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import llm

    prompts: list[tuple[str, dict[str, object]]] = []

    class _Response:
        response_json: dict[str, object] = {}

        def text(self) -> str:
            return "{}"

    class _Model:
        supports_schema = True

        class Options:
            model_fields = {
                "json_object": object(),
                "temperature": object(),
                "seed": object(),
                "max_tokens": object(),
            }

        def prompt(self, text: str, **options: object) -> _Response:
            prompts.append((text, options))
            return _Response()

    monkeypatch.setattr(llm, "get_model", lambda *args: _Model())
    adapter = default_provider_adapter(
        "declared-model",
        provider_identity=_provider(),
        request_identity=RequestIdentity("require", 0.0, 42, 256),
    )
    packet = _section_packet()

    adapter(_prompt(packet))

    schema = cast(dict[str, Any], prompts[0][1]["schema"])
    properties = cast(dict[str, Any], schema["properties"])
    assert properties["packet_id"] == {"const": packet["packet_id"]}
    assessment_variants = properties["assessment"]["anyOf"]
    ambiguous = next(
        variant
        for variant in assessment_variants
        if variant["properties"]["classification"]["const"] == "ambiguous"
    )
    requirement_variants = ambiguous["properties"]["evidence"]["properties"][
        "requirement"
    ]["items"]["anyOf"]
    assert [
        {
            key: variant["properties"][key]["const"]
            for key in ("path", "start_line", "end_line")
        }
        for variant in requirement_variants
    ] == [
        {key: region[key] for key in ("path", "start_line", "end_line")}
        for region in semantic_packet_projection(packet)["evidence_regions"]
        if region["role"] == "requirement"
    ]


def test_provider_schema_omits_classifications_with_unavailable_required_roles() -> (
    None
):
    projection = {
        "packet_id": "suppression::docs/specs/01-X.md#SUP-X",
        "kind": "suppression",
        "evidence_regions": [
            {
                "role": "requirement",
                "path": "docs/specs/01-X.md",
                "start_line": 3,
                "end_line": 3,
            }
        ],
    }

    schema = _semantic_response_schema(
        "suppression prompt\n\n" + json.dumps(projection)
    )
    variants = cast(dict[str, Any], schema["properties"])["assessment"]["anyOf"]

    assert {
        variant["properties"]["classification"]["const"] for variant in variants
    } == {"ok", "rationale_insufficient", "ambiguous"}


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (
            "section",
            {
                "ok": frozenset(),
                "confirmed_mismatch": frozenset({"requirement", "implementation"}),
                "probable_mismatch": frozenset({"requirement", "implementation"}),
                "missing_trace": frozenset({"requirement"}),
                "ambiguous": frozenset({"requirement"}),
            },
        ),
        (
            "invariant",
            {
                "ok": frozenset({"test"}),
                "weak_binding": frozenset({"requirement", "implementation"}),
                "confirmed_mismatch": frozenset({"requirement", "implementation"}),
                "probable_mismatch": frozenset({"requirement", "implementation"}),
                "ambiguous": frozenset({"requirement"}),
            },
        ),
        (
            "suppression",
            {
                "ok": frozenset({"requirement"}),
                "rationale_insufficient": frozenset({"requirement"}),
                "scope_overbroad": frozenset({"requirement", "counterevidence"}),
                "risk_unaddressed": frozenset({"requirement", "counterevidence"}),
                "ambiguous": frozenset({"requirement"}),
            },
        ),
    ],
)
def test_provider_schema_matches_spec_required_role_matrix(
    kind: str, expected: dict[str, frozenset[str]]
) -> None:
    projection = {
        "packet_id": "packet",
        "kind": kind,
        "evidence_regions": [
            {"role": role, "path": f"{role}.txt", "start_line": 1, "end_line": 1}
            for role in ("requirement", "implementation", "test", "counterevidence")
        ],
    }
    schema = _semantic_response_schema("prompt\n\n" + json.dumps(projection))
    variants = cast(dict[str, Any], schema["properties"])["assessment"]["anyOf"]
    observed = {
        variant["properties"]["classification"]["const"]: frozenset(
            variant["properties"]["evidence"].get("required", [])
        )
        for variant in variants
    }

    assert observed == expected


def test_provider_adapter_rejects_model_identity_mismatch_before_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import llm

    monkeypatch.setattr(
        llm,
        "get_model",
        lambda *args: (_ for _ in ()).throw(
            AssertionError("mismatched model reached resolution")
        ),
    )

    with pytest.raises(ValueError, match="model name does not match provider identity"):
        default_provider_adapter(
            "different-model",
            provider_identity=_provider("keyed-model"),
            request_identity=RequestIdentity("require", 0.0, 42, 256),
        )


def test_provider_adapter_rejects_unsupported_resolved_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import llm

    class _Model:
        class Options:
            model_fields = {"temperature": object()}

        def prompt(self, text: str, **options: object) -> object:
            raise AssertionError("unsupported request reached provider")

    monkeypatch.setattr(llm, "get_model", lambda *args: _Model())

    with pytest.raises(ValueError, match="does not support request options"):
        default_provider_adapter(
            "declared-model",
            provider_identity=_provider(),
            request_identity=RequestIdentity("require", 0.0, 42, 256),
        )


def test_provider_adapter_omits_schema_when_request_mode_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import llm

    prompts: list[dict[str, object]] = []

    class _Response:
        response_json: dict[str, object] = {}

        def text(self) -> str:
            return "plain"

    class _Model:
        class Options:
            model_fields = {
                "temperature": object(),
                "seed": object(),
                "max_tokens": object(),
            }

        def prompt(self, _text: str, **options: object) -> _Response:
            prompts.append(options)
            return _Response()

    monkeypatch.setattr(llm, "get_model", lambda *args: _Model())
    adapter = default_provider_adapter(
        "declared-model",
        provider_identity=_provider(),
        request_identity=RequestIdentity("off", 0.0, 42, 256),
    )

    assert adapter("plain request").raw_response == "plain"
    assert prompts == [{"temperature": 0.0, "seed": 42, "max_tokens": 256}]


def test_provider_adapter_serializes_resolved_absence_without_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """[SEM-3]: an absent field stays absent on the provider call."""

    import llm

    calls: list[dict[str, object]] = []

    class _Response:
        response_json: dict[str, object] = {}

        def text(self) -> str:
            return "{}"

    class _Model:
        supports_schema = True

        class Options:
            model_fields = {
                "json_object": object(),
                "seed": object(),
                "max_tokens": object(),
            }

        def prompt(self, _prompt: str, **options: object) -> _Response:
            calls.append(options)
            return _Response()

    monkeypatch.setattr(llm, "get_model", lambda *_args: _Model())
    provider = _provider("pkg:service/openai.com/gpt-5.5")
    inference = _resolved_inference(
        provider,
        adapter_model_id="gpt-5.5",
        temperature=None,
    )

    default_provider_adapter(inference)(_prompt(_section_packet()))

    assert set(calls[0]) == {"seed", "max_tokens", "schema"}
    assert "temperature" not in calls[0]


def test_provider_adapter_does_not_retry_rejected_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import llm

    prompts: list[tuple[str, dict[str, object]]] = []

    class _Model:
        supports_schema = True

        class Options:
            model_fields = {
                "json_object": object(),
                "temperature": object(),
                "seed": object(),
                "max_tokens": object(),
            }

        def prompt(self, text: str, **options: object) -> object:
            prompts.append((text, options))
            raise RuntimeError("server rejected response format")

    monkeypatch.setattr(llm, "get_model", lambda *args: _Model())
    adapter = default_provider_adapter(
        "declared-model",
        provider_identity=_provider(),
        request_identity=RequestIdentity("require", 0.0, 42, 256),
    )

    with pytest.raises(RuntimeError, match="server rejected"):
        adapter(_prompt(_section_packet()))
    assert len(prompts) == 1


def test_llm_chat_options_map_json_object_to_response_format() -> None:
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
        check=False,
    )
    assert result.returncode == 2
    assert "requires --packet-report" in result.stderr


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
        check=False,
    )
    assert result.returncode == 2
    assert "requires --packet-report" in result.stderr
