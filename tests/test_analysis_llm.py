"""Shipping provider-adapter tests with a fake model seam.

Spec: docs/specs/02-backstitch-core.md [SC-7], [SC-13]
Spec: docs/specs/06-semantic-gates.md [SEM-3]
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest

from backstitch.analysis_llm import (
    _install_completion_limit_shim,
    _semantic_response_schema,
    default_provider_adapter,
)
from backstitch.semantic_identity import (
    CapabilityDescriptor,
    EffectiveRequest,
    ProviderIdentity,
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

HERMETIC_MODEL = "backstitch-hermetic-model-that-must-not-exist"


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
            }

        def prompt(self, text: str, **options: object) -> _Response:
            prompts.append((text, options))
            return _Response()

    monkeypatch.setattr(llm, "get_model", lambda *args: _Model())
    request = RequestIdentity("require", 0.0, 42, 256)
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
    assert "schema" in prompts[0][1]
    assert "json_object" not in prompts[0][1]


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
    variants = properties["evidence"]["items"]["anyOf"]
    assert [
        {
            key: variant["properties"][key]["const"]
            for key in ("role", "path", "start_line", "end_line")
        }
        for variant in variants
    ] == semantic_packet_projection(packet)["evidence_regions"]


def test_provider_schema_admits_exact_suppression_classifications() -> None:
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
    properties = cast(dict[str, Any], schema["properties"])

    assert properties["classification"]["enum"] == [
        "ok",
        "rationale_insufficient",
        "scope_overbroad",
        "risk_unaddressed",
        "ambiguous",
    ]


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
