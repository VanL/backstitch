from __future__ import annotations

import http.server
import importlib.util
import json
import socket
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path
from types import ModuleType

import pytest

from backstitch.analysis_llm import default_provider_adapter
from backstitch.semantic_identity import ProviderIdentity, RequestIdentity
from backstitch.settings import resolve_config

ROOT = Path(__file__).resolve().parents[1]


def _load_live_module() -> ModuleType:
    path = ROOT / "tests" / "live" / "test_live_llm.py"
    spec = importlib.util.spec_from_file_location("backstitch_live_llm_test", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


live_llm = _load_live_module()


@pytest.mark.parametrize(
    ("error", "category"),
    (
        (RuntimeError("Error code: 400"), "incompatible"),
        (RuntimeError("HTTP 404"), "incompatible"),
        (RuntimeError("HTTP 422"), "incompatible"),
        (RuntimeError("model output normalization failed"), "incompatible"),
        (RuntimeError("missing credential"), "unavailable"),
        (RuntimeError("Error code: 401"), "unavailable"),
        (RuntimeError("HTTP 403"), "unavailable"),
        (RuntimeError("rate limit"), "unavailable"),
        (RuntimeError("connection timed out"), "unavailable"),
        (RuntimeError("DNS resolution failed"), "unavailable"),
        (RuntimeError("TLS handshake failed"), "unavailable"),
        (RuntimeError("HTTP 503"), "unavailable"),
        (
            RuntimeError(
                "provider request incompatible: cannot prove hide_reasoning support"
            ),
            "incompatible",
        ),
        (
            RuntimeError(
                "provider request incompatible: does not support "
                "schema-constrained output"
            ),
            "incompatible",
        ),
        (RuntimeError("invalid descriptor"), "qualification error"),
        (RuntimeError("corrupt cache object"), "qualification error"),
        (RuntimeError("bad fixture"), "qualification error"),
    ),
)
def test_openai_qualification_failure_categories(
    error: BaseException,
    category: str,
) -> None:
    actual, reason = live_llm._qualification_failure_category(error)

    assert actual == category
    assert reason
    assert str(error) not in reason


def test_openai_qualification_bounds_and_selection_labels() -> None:
    bounded_cost = live_llm._openai_qualification_estimated_cost_microusd(1_000)
    live_llm._assert_openai_qualification_bounds(
        provider_calls=2,
        estimated_cost_microusd=bounded_cost,
    )
    assert bounded_cost <= 100_000
    oversized_cost = live_llm._openai_qualification_estimated_cost_microusd(100_000)
    assert oversized_cost > 100_000

    with pytest.raises(ValueError, match="two-call"):
        live_llm._assert_openai_qualification_bounds(
            provider_calls=3,
            estimated_cost_microusd=100_000,
        )
    with pytest.raises(ValueError, match=r"\$0\.10"):
        live_llm._assert_openai_qualification_bounds(
            provider_calls=2,
            estimated_cost_microusd=100_001,
        )
    assert live_llm.OPENAI_QUALIFICATION_MODELS == (
        "gpt-5.6-luna",
        "gpt-5.5-2026-04-23",
    )
    assert live_llm._qualification_selection_label("gpt-5.6-luna") == (
        "pkg:service/openai.com/gpt-5.6-luna / gpt-5.6-luna"
    )


def test_live_packet_generation_respects_report_kind_contract(
    tmp_path: Path,
) -> None:
    output = tmp_path / "packets.jsonl"
    report = tmp_path / "packet-report.json"

    assert live_llm._live_packet_generation_args(
        "local",
        ["--repo-root", str(tmp_path)],
        output=output,
        report=report,
    ) == [
        "packets",
        "--repo-root",
        str(tmp_path),
        "--kind",
        "all",
        "--output",
        str(output),
        "--report",
        str(report),
    ]
    assert live_llm._live_packet_generation_args(
        "openai",
        ["--repo-root", str(tmp_path)],
        output=output,
        report=report,
    ) == [
        "packets",
        "--repo-root",
        str(tmp_path),
        "--kind",
        "section",
        "--output",
        str(output),
    ]


def test_openai_qualification_requires_both_exact_selections() -> None:
    seen: list[str] = []

    def compatible(model_name: str) -> tuple[int, int]:
        seen.append(model_name)
        return 1, 25_000

    messages = live_llm._run_openai_qualifications(compatible)

    assert tuple(seen) == live_llm.OPENAI_QUALIFICATION_MODELS
    assert messages == (
        "compatible: pkg:service/openai.com/gpt-5.6-luna / gpt-5.6-luna",
        "compatible: pkg:service/openai.com/gpt-5.5 / gpt-5.5-2026-04-23",
    )


@pytest.mark.parametrize(
    ("error", "prefix"),
    (
        (RuntimeError("HTTP 400"), "incompatible:"),
        (RuntimeError("connection timeout"), "unavailable:"),
        (RuntimeError("fixture broke"), "qualification error:"),
    ),
)
def test_openai_qualification_blocks_with_bounded_categorized_message(
    error: Exception,
    prefix: str,
) -> None:
    def fail(_model_name: str) -> tuple[int, int]:
        raise error

    with pytest.raises(live_llm._QualificationProcessFailure) as excinfo:
        live_llm._run_openai_qualifications(fail)

    message = str(excinfo.value)
    assert message.startswith(prefix)
    assert "pkg:service/openai.com/gpt-5.6-luna / gpt-5.6-luna" in message
    assert str(error) not in message


def test_openai_qualification_blocks_if_second_descriptor_or_budget_fails() -> None:
    attempts: list[str] = []

    def second_unavailable(model_name: str) -> tuple[int, int]:
        attempts.append(model_name)
        if model_name == "gpt-5.5-2026-04-23":
            raise RuntimeError("missing credential")
        return 1, 25_000

    with pytest.raises(
        live_llm._QualificationProcessFailure,
        match=r"^unavailable: pkg:service/openai\.com/gpt-5\.5 /",
    ):
        live_llm._run_openai_qualifications(second_unavailable)
    assert attempts == list(live_llm.OPENAI_QUALIFICATION_MODELS)

    with pytest.raises(
        live_llm._QualificationProcessFailure,
        match=r"^qualification error:.*budget preflight failed",
    ):
        live_llm._run_openai_qualifications(lambda _model: (1, 100_001))

    with pytest.raises(
        live_llm._QualificationProcessFailure,
        match=r"^qualification error:.*exactly one provider call",
    ):
        live_llm._run_openai_qualifications(lambda _model: (0, 0))


def test_openai_qualification_categorizes_invalid_selected_descriptor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(live_llm, "OPENAI_QUALIFICATION_MODELS", ("unknown-model",))

    def invalid_descriptor(model_name: str) -> tuple[int, int]:
        live_llm._live_descriptor_lines(
            kind="openai",
            adapter_model_id=model_name,
        )
        raise AssertionError("invalid descriptor construction unexpectedly returned")

    with pytest.raises(
        live_llm._QualificationProcessFailure,
        match=(
            r"^qualification error: stable model unavailable / unknown-model "
            r"\(local qualification setup or preflight failed\)$"
        ),
    ):
        live_llm._run_openai_qualifications(invalid_descriptor)


@pytest.mark.parametrize(
    (
        "adapter_model_id",
        "stable_model_id",
        "reasoning_effort",
        "max_tokens",
        "input_rate",
        "output_rate",
    ),
    (
        (
            "gpt-5.6-luna",
            "pkg:service/openai.com/gpt-5.6-luna",
            "max",
            16_384,
            400_000,
            1_800_000,
        ),
        (
            "gpt-5.5-2026-04-23",
            "pkg:service/openai.com/gpt-5.5",
            None,
            1_024,
            5_000_000,
            30_000_000,
        ),
    ),
)
def test_cloud_live_descriptor_is_complete_and_costed(
    tmp_path: Path,
    adapter_model_id: str,
    stable_model_id: str,
    reasoning_effort: str | None,
    max_tokens: int,
    input_rate: int,
    output_rate: int,
) -> None:
    config = tmp_path / ".backstitch.toml"
    descriptor = live_llm._live_descriptor_lines(
        kind="openai",
        adapter_model_id=adapter_model_id,
    )
    config.write_text(
        "[analyze]\n"
        + "\n".join(descriptor)
        + '\njson_mode = "require"\n'
        + 'cache_path = ".backstitch/semantic-cache"\n',
        encoding="utf-8",
    )

    analyze = resolve_config(
        tmp_path,
        explicit=config,
        environment={},
    ).analyze

    assert analyze.model == stable_model_id
    assert analyze.adapter_model_id == adapter_model_id
    assert analyze.plugin_id == "openai"
    assert analyze.model_revision == adapter_model_id
    assert analyze.capability_schema_version == 1
    assert (
        analyze.capability_revision
        == {
            "gpt-5.6-luna": "openai-gpt-5.6-luna-2026-08-23",
            "gpt-5.5-2026-04-23": "openai-gpt-5.5-responses-2026-08-23",
        }[adapter_model_id]
    )
    assert analyze.maximum_input_bytes == 1_600_000
    assert analyze.temperature is None
    assert analyze.seed is None
    assert analyze.reasoning_effort == reasoning_effort
    assert analyze.max_tokens == max_tokens
    assert analyze.request_constraints.temperature.presence == "forbidden"
    assert analyze.request_constraints.seed.presence == "forbidden"
    assert analyze.request_constraints.reasoning_effort.presence == (
        "optional" if reasoning_effort is not None else "forbidden"
    )
    assert analyze.request_constraints.reasoning_effort.allowed_values == (
        ("max",) if reasoning_effort is not None else None
    )
    assert analyze.maximum_estimated_cost_microusd == 100_000
    assert analyze.required_kinds == ("section",)
    assert analyze.minimum_packets == 1
    assert analyze.maximum_packets == 1
    assert analyze.maximum_provider_calls == 1
    assert analyze.input_cost_microusd_per_million_tokens == input_rate
    assert analyze.output_cost_microusd_per_million_tokens == output_rate
    assert analyze.cost_rate_source


def test_local_live_descriptor_keeps_controls_and_forbids_reasoning(
    tmp_path: Path,
) -> None:
    config = tmp_path / ".backstitch.toml"
    descriptor = live_llm._live_descriptor_lines(
        kind="local",
        adapter_model_id="backstitch-local",
    )
    config.write_text(
        "[analyze]\n"
        + "\n".join(descriptor)
        + '\njson_mode = "require"\n'
        + 'cache_path = ".backstitch/semantic-cache"\n',
        encoding="utf-8",
    )

    analyze = resolve_config(tmp_path, explicit=config, environment={}).analyze

    assert analyze.temperature == 0
    assert analyze.seed == 42
    assert analyze.max_tokens == 1024
    assert analyze.reasoning_effort is None
    assert analyze.request_constraints.reasoning_effort.presence == "forbidden"


def _local_packet(packet_id: str) -> dict[str, object]:
    suffix = packet_id.rsplit(".", 1)[-1]
    return {
        "packet_id": packet_id,
        "kind": "invariant",
        "invariant_id": f"INV.RES.{suffix}",
        "tier": "required",
        "statement": "The resolver preserves the requested contract.",
        "declaration": {
            "kind": "code",
            "path": "backstitch/resolver.py",
            "line": 10,
            "symbol": "resolve",
            "section_id": None,
            "start_line": 10,
            "end_line": 10,
            "excerpt": "Invariant: the resolver preserves the requested contract.",
        },
        "targets": [
            {
                "path": "backstitch/resolver.py",
                "symbol": "resolve",
                "start_line": 10,
                "snippet": "x",
            }
        ],
        "binding_tests": [
            {
                "path": f"tests/test_resolver_{suffix}.py",
                "symbol": "test_resolve",
                "start_line": 20,
                "snippet": "assert x",
            }
        ],
        "issues": [],
        "packet_warnings": [],
    }


def _recorded_local_payload(
    packet_id: str,
    *,
    temperature: int = 0,
) -> dict[str, object]:
    packet = _local_packet(packet_id)
    payload: dict[str, object] = {
        "model": "backstitch-local-model:latest",
        "messages": [{"role": "user", "content": "review\n\n" + json.dumps(packet)}],
        "temperature": temperature,
        "seed": 42,
        "stream": False,
        "max_tokens": 1024,
    }
    payload["response_format"] = live_llm._local_analyze_response_format(payload)
    return payload


def test_local_llm_counting_proxy_forwards_and_records_completion_requests() -> None:
    seen_upstream_bodies: list[str] = []
    assistant_content = '  first\n"quoted" \\ slash ☃\nlast  '
    packet = {
        "packet_id": "invariant::INV.RES.1",
        "kind": "invariant",
        "targets": [
            {
                "path": "backstitch/resolver.py",
                "start_line": 798,
                "snippet": "line one\nline two",
            }
        ],
        "binding_tests": [
            {
                "path": "tests/test_resolver.py",
                "start_line": 482,
                "snippet": "assert first\nassert second",
            }
        ],
    }

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib hook name
            assert self.path == "/v1/models"
            payload = json.dumps({"data": [{"id": "backstitch-local-model"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self) -> None:  # noqa: N802 - stdlib hook name
            assert self.path == "/v1/chat/completions"
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length).decode()
            seen_upstream_bodies.append(body)
            payload = json.dumps(
                {"choices": [{"message": {"content": assistant_content}}]}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        upstream = f"http://127.0.0.1:{server.server_port}/v1"
        with live_llm._CountingProxy(upstream) as proxy:
            models = urllib.request.urlopen(  # noqa: S310 - loopback test server
                f"{proxy.endpoint}/models", timeout=5
            ).read()
            assert json.loads(models)["data"][0]["id"] == "backstitch-local-model"
            assert proxy.request_bodies == []

            request_payload = {
                "model": "backstitch-local-model",
                "temperature": 1,
                "seed": 7,
                "stream": True,
                "stream_options": {"include_usage": True},
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "user",
                        "content": "review this invariant\n\n" + json.dumps(packet),
                    }
                ],
            }
            body = json.dumps(request_payload).encode()
            request = urllib.request.Request(
                f"{proxy.endpoint}/chat/completions",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            response = urllib.request.urlopen(  # noqa: S310 - loopback test server
                request, timeout=5
            )
            assert response.status == 200

            expected_payload = request_payload
            assert [json.loads(body) for body in seen_upstream_bodies] == [
                expected_payload
            ]
            assert proxy.request_bodies == []

            seen_upstream_bodies.clear()
            proxy.start_analyze_phase()
            response = urllib.request.urlopen(request, timeout=5)  # noqa: S310
            assert response.status == 200
            relayed = response.read()
            proxy.stop_analyze_phase()

            assert json.loads(relayed)["choices"][0]["message"]["content"] == (
                assistant_content
            )
            assert [json.loads(body) for body in seen_upstream_bodies] == [
                expected_payload
            ]
            assert [json.loads(body) for body in proxy.request_bodies] == [
                expected_payload
            ]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("body", [b"not-json", b"\xff", b"[]"])
def test_local_llm_counting_proxy_rejects_invalid_completion_json(
    body: bytes,
) -> None:
    upstream_calls = 0

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - stdlib hook name
            nonlocal upstream_calls
            upstream_calls += 1
            self.send_response(500)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with live_llm._CountingProxy(
            f"http://127.0.0.1:{server.server_port}/v1"
        ) as proxy:
            proxy.start_analyze_phase()
            request = urllib.request.Request(
                f"{proxy.endpoint}/chat/completions",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with pytest.raises(urllib.error.HTTPError) as excinfo:
                urllib.request.urlopen(request, timeout=5)  # noqa: S310
            assert excinfo.value.code == 400
            assert b"invalid completion request JSON" in excinfo.value.read()
            assert upstream_calls == 0
            assert proxy.request_bodies == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_local_llm_counting_proxy_rejects_analyze_without_one_packet_prompt() -> None:
    upstream_calls = 0

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - stdlib hook name
            nonlocal upstream_calls
            upstream_calls += 1
            self.send_response(500)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with live_llm._CountingProxy(
            f"http://127.0.0.1:{server.server_port}/v1"
        ) as proxy:
            proxy.start_analyze_phase()
            request = urllib.request.Request(
                f"{proxy.endpoint}/chat/completions",
                data=json.dumps(
                    {
                        "model": "backstitch-local-model",
                        "stream": True,
                        "response_format": {"type": "json_object"},
                        "messages": [{"role": "user", "content": "no packet"}],
                    }
                ).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with pytest.raises(urllib.error.HTTPError) as excinfo:
                urllib.request.urlopen(request, timeout=5)  # noqa: S310
            assert excinfo.value.code == 400
            assert b"one invariant packet" in excinfo.value.read()
            assert upstream_calls == 0
            assert proxy.request_bodies == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize(
    "response_format",
    [None, {"type": "json_schema"}],
)
def test_local_llm_counting_proxy_requires_adapter_json_object_before_schema(
    response_format: object,
) -> None:
    upstream_calls = 0

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - stdlib hook name
            nonlocal upstream_calls
            upstream_calls += 1
            self.send_response(500)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with live_llm._CountingProxy(
            f"http://127.0.0.1:{server.server_port}/v1"
        ) as proxy:
            proxy.start_analyze_phase()
            payload = {
                "model": "backstitch-local-model",
                "stream": True,
                "messages": [
                    {
                        "role": "user",
                        "content": "review\n\n"
                        + json.dumps(_local_packet("invariant::INV.RES.1")),
                    }
                ],
            }
            if response_format is not None:
                payload["response_format"] = response_format
            request = urllib.request.Request(
                f"{proxy.endpoint}/chat/completions",
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with pytest.raises(urllib.error.HTTPError) as excinfo:
                urllib.request.urlopen(request, timeout=5)  # noqa: S310
            assert excinfo.value.code == 400
            assert b"json_object" in excinfo.value.read()
            assert upstream_calls == 0
            assert proxy.request_bodies == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_local_llm_proxy_allows_one_upstream_attempt_through_provider_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upstream_calls = 0
    upstream_bodies: list[dict[str, object]] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - stdlib hook name
            nonlocal upstream_calls
            upstream_calls += 1
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = json.loads(self.rfile.read(length))
            assert isinstance(body, dict)
            upstream_bodies.append(body)
            payload = b"{}"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with live_llm._CountingProxy(
            f"http://127.0.0.1:{server.server_port}/v1"
        ) as proxy:
            live_llm._configure_local_llm(
                tmp_path,
                monkeypatch,
                proxy,
            )
            proxy.start_analyze_phase()
            packet = _local_packet("invariant::INV.RES.1")
            packet["packet_contract_version"] = 3
            packet["evidence_regions"] = [
                {
                    "role": "requirement",
                    "path": "backstitch/resolver.py",
                    "start_line": 10,
                    "end_line": 10,
                }
            ]
            adapter = default_provider_adapter(
                "backstitch-local",
                provider_identity=ProviderIdentity(
                    "llm",
                    "openai",
                    "backstitch-local",
                    "test-revision",
                    "backstitch.llm",
                    1,
                    "test",
                    "llm",
                    "test",
                ),
                request_identity=RequestIdentity("require", 0.0, 42, 1024),
            )

            adapter("review\n\n" + json.dumps(packet))

            assert upstream_calls == 1
            assert len(proxy.request_bodies) == 1
            assert len(upstream_bodies) == 1
            forwarded = upstream_bodies[0]
            assert forwarded["response_format"] == (
                live_llm._local_analyze_response_format(forwarded)
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_local_llm_proxy_rejects_v3_schema_drift_before_upstream() -> None:
    upstream_calls = 0

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - stdlib hook name
            nonlocal upstream_calls
            upstream_calls += 1
            self.send_response(500)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        packet = _local_packet("invariant::INV.RES.1")
        packet["packet_contract_version"] = 3
        packet["evidence_regions"] = [
            {
                "role": "requirement",
                "path": "backstitch/resolver.py",
                "start_line": 10,
                "end_line": 10,
            }
        ]
        prompt = "review\n\n" + json.dumps(packet)
        payload = {
            "model": "backstitch-local",
            "stream": True,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "output",
                    "schema": {"type": "object", "additionalProperties": True},
                },
            },
        }
        with live_llm._CountingProxy(
            f"http://127.0.0.1:{server.server_port}/v1"
        ) as proxy:
            proxy.start_analyze_phase()
            request = urllib.request.Request(
                f"{proxy.endpoint}/chat/completions",
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with pytest.raises(urllib.error.HTTPError) as excinfo:
                urllib.request.urlopen(request, timeout=5)  # noqa: S310
            assert excinfo.value.code == 400
            assert b"preserve the adapter's packet-bound JSON schema" in (
                excinfo.value.read()
            )
            assert upstream_calls == 0
            assert proxy.request_bodies == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_local_llm_counting_proxy_relays_streaming_responses() -> None:
    # The observational proxy relays provider streaming responses unchanged.
    sse_chunks = [
        b'data: {"choices": [{"delta": {"content": "O"}}]}\n\n',
        b'data: {"choices": [{"delta": {"content": "K"}}]}\n\n',
        b"data: [DONE]\n\n",
    ]

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - stdlib hook name
            assert self.path == "/v1/chat/completions"
            length = int(self.headers.get("Content-Length", "0") or "0")
            self.rfile.read(length)
            # No Content-Length: the body is delimited by connection close,
            # like a live SSE stream the proxy must relay incrementally.
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for chunk in sse_chunks:
                self.wfile.write(chunk)
                self.wfile.flush()

        def log_message(self, format: str, *args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        upstream = f"http://127.0.0.1:{server.server_port}/v1"
        with live_llm._CountingProxy(upstream) as proxy:
            request = urllib.request.Request(
                f"{proxy.endpoint}/chat/completions",
                data=json.dumps(
                    {
                        "model": "m",
                        "stream": True,
                        "messages": [
                            {
                                "role": "user",
                                "content": "review\n\n"
                                + json.dumps(_local_packet("invariant::INV.RES.1")),
                            }
                        ],
                    }
                ).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310 - loopback test server
                assert response.status == 200
                assert response.headers.get("Content-Type") == "text/event-stream"
                relayed = response.read()
            proxy.stop_analyze_phase()

            assert relayed == b"".join(sse_chunks)
            assert proxy.request_bodies == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_local_llm_counting_proxy_maps_v1_paths_onto_upstream_prefix() -> None:
    prefixed = live_llm._CountingProxy("http://127.0.0.1:9/ollama/v1")
    assert (
        prefixed.forward_url("/v1/chat/completions")
        == "http://127.0.0.1:9/ollama/v1/chat/completions"
    )
    assert prefixed.forward_url("/v1/models") == "http://127.0.0.1:9/ollama/v1/models"

    plain = live_llm._CountingProxy("http://127.0.0.1:9/v1")
    assert plain.forward_url("/v1/models") == "http://127.0.0.1:9/v1/models"
    assert plain.forward_url("/health") == "http://127.0.0.1:9/health"


def test_local_llm_counting_proxy_returns_502_when_upstream_is_unreachable() -> None:
    # A listener that accepts and immediately closes: the upstream dies before
    # any response bytes are written, so the proxy must answer 502 with a
    # diagnostic rather than dying in the handler thread. (A hermetic stand-in
    # for a down/broken upstream — no assumption about closed host ports.)
    broken = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    broken.bind(("127.0.0.1", 0))
    broken.listen(5)
    port = broken.getsockname()[1]
    stop = threading.Event()

    def _accept_and_close() -> None:
        while not stop.is_set():
            try:
                conn, _ = broken.accept()
            except OSError:
                return
            conn.close()

    closer = threading.Thread(target=_accept_and_close, daemon=True)
    closer.start()
    try:
        with live_llm._CountingProxy(f"http://127.0.0.1:{port}/v1") as proxy:
            request = urllib.request.Request(
                f"{proxy.endpoint}/chat/completions",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with pytest.raises(urllib.error.HTTPError) as excinfo:
                urllib.request.urlopen(request, timeout=10)  # noqa: S310 - loopback test server
            assert excinfo.value.code == 502
            assert b"proxy forwarding error" in excinfo.value.read()
    finally:
        stop.set()
        broken.close()
        closer.join(timeout=5)


def test_local_analyze_transport_assertion_rejects_wrong_inference_controls() -> None:
    proxy = live_llm._CountingProxy("http://127.0.0.1:9/v1")
    proxy.request_bodies = [
        json.dumps(_recorded_local_payload("invariant::INV.RES.1", temperature=1)),
        json.dumps(_recorded_local_payload("invariant::INV.RES.2")),
    ]

    with pytest.raises(AssertionError, match="unexpected inference controls"):
        live_llm._assert_analyze_hit_local_endpoint(
            proxy,
            expected_packet_ids=set(live_llm.LOCAL_LIVE_PACKET_IDS),
            served_model="backstitch-local-model:latest",
        )


def test_local_analyze_transport_assertion_rejects_duplicate_packet_request() -> None:
    packet = {
        "packet_id": "invariant::INV.RES.1",
        "kind": "invariant",
        "targets": [{"path": "a.py", "start_line": 1, "snippet": "x"}],
        "binding_tests": [
            {"path": "test_a.py", "start_line": 1, "snippet": "assert x"}
        ],
    }
    body = json.dumps(
        {
            "model": "backstitch-local-model:latest",
            "messages": [
                {"role": "user", "content": "review\n\n" + json.dumps(packet)}
            ],
            "temperature": 0,
            "seed": 42,
        }
    )
    proxy = live_llm._CountingProxy("http://127.0.0.1:9/v1")
    proxy.request_bodies = [body, body]

    with pytest.raises(AssertionError, match="exactly one analyze request"):
        live_llm._assert_analyze_hit_local_endpoint(
            proxy,
            expected_packet_ids={"invariant::INV.RES.1"},
            served_model="backstitch-local-model:latest",
        )


def test_live_packet_selector_keeps_cloud_focus_and_bounds_local_size() -> None:
    packet_rows = [
        {
            "packet_id": "docs/specs/03-backstitch-configuration.md#CFG-2",
            "spec_path": "docs/specs/03-backstitch-configuration.md",
            "owners": [{"path": "backstitch/settings.py"}],
            "payload": "x",
        },
        {
            "packet_id": "docs/specs/02-backstitch-core.md#SC-7",
            "spec_path": "docs/specs/02-backstitch-core.md",
            "owners": [{"path": "backstitch/analysis_llm.py"}],
            "payload": "x" * 100,
        },
        {
            "packet_id": "docs/specs/02-backstitch-core.md#SC-5",
            "spec_path": "docs/specs/02-backstitch-core.md",
            "owners": [{"path": "backstitch/cli.py"}],
            "payload": "x" * 200,
        },
    ]
    packets_text = "".join(json.dumps(packet) + "\n" for packet in packet_rows)

    cloud = live_llm._select_live_packets(
        packets_text,
        2,
        require_semantic_owner=True,
    )
    local = live_llm._select_live_packets(
        packets_text,
        2,
        require_semantic_owner=False,
    )

    assert [packet["packet_id"] for packet in cloud] == [
        "docs/specs/02-backstitch-core.md#SC-7",
        "docs/specs/02-backstitch-core.md#SC-5",
    ]
    assert [packet["packet_id"] for packet in local] == [
        "docs/specs/03-backstitch-configuration.md#CFG-2",
        "docs/specs/02-backstitch-core.md#SC-7",
    ]


def test_local_live_packet_selector_uses_curated_invariant_order() -> None:
    def invariant_packet(packet_id: str, payload: str) -> dict[str, object]:
        return {
            "packet_id": packet_id,
            "kind": "invariant",
            "targets": [
                {
                    "path": "backstitch/resolver.py",
                    "start_line": 10,
                    "snippet": "def resolve():\n    return True",
                }
            ],
            "binding_tests": [
                {
                    "path": "tests/test_resolver.py",
                    "start_line": 20,
                    "snippet": "def test_resolve():\n    assert resolve()",
                }
            ],
            "packet_warnings": [],
            "payload": payload,
        }

    packet_rows = [
        invariant_packet("invariant::UNRELATED.1", ""),
        invariant_packet("invariant::INV.RES.2", "x" * 200),
        invariant_packet("invariant::INV.RES.1", "x" * 100),
    ]
    packets_text = "".join(json.dumps(packet) + "\n" for packet in packet_rows)

    selected = live_llm._select_local_live_packets(packets_text)

    assert [packet["packet_id"] for packet in selected] == [
        "invariant::INV.RES.1",
        "invariant::INV.RES.2",
    ]


def test_local_live_packet_selector_rejects_warned_packet() -> None:
    def invariant_packet(packet_id: str) -> dict[str, object]:
        return {
            "packet_id": packet_id,
            "kind": "invariant",
            "targets": [
                {"path": "backstitch/resolver.py", "start_line": 10, "snippet": "x"}
            ],
            "binding_tests": [
                {"path": "tests/test_resolver.py", "start_line": 20, "snippet": "y"}
            ],
            "packet_warnings": [],
        }

    first = invariant_packet("invariant::INV.RES.1")
    first["packet_warnings"] = ["snippet truncated"]
    packets_text = "\n".join(
        json.dumps(packet)
        for packet in (first, invariant_packet("invariant::INV.RES.2"))
    )

    with pytest.raises(AssertionError, match="must have no packet warnings"):
        live_llm._select_local_live_packets(packets_text)


def test_local_live_packet_selector_requires_bounded_target_evidence() -> None:
    def invariant_packet(packet_id: str) -> dict[str, object]:
        return {
            "packet_id": packet_id,
            "kind": "invariant",
            "targets": [
                {"path": "backstitch/resolver.py", "start_line": 10, "snippet": "x"}
            ],
            "binding_tests": [
                {"path": "tests/test_resolver.py", "start_line": 20, "snippet": "y"}
            ],
            "packet_warnings": [],
        }

    first = invariant_packet("invariant::INV.RES.1")
    first["targets"] = []
    packets_text = "\n".join(
        json.dumps(packet)
        for packet in (first, invariant_packet("invariant::INV.RES.2"))
    )

    with pytest.raises(AssertionError, match="bounded target evidence"):
        live_llm._select_local_live_packets(packets_text)


@pytest.mark.parametrize(
    ("field", "item", "message"),
    [
        ("targets", {"path": "", "start_line": 1, "snippet": "x"}, "target"),
        ("targets", {"path": "a.py", "start_line": 0, "snippet": "x"}, "target"),
        ("targets", {"path": "a.py", "start_line": True, "snippet": "x"}, "target"),
        ("targets", {"path": "a.py", "start_line": 1, "snippet": " "}, "target"),
        (
            "binding_tests",
            {"path": "", "start_line": 1, "snippet": "x"},
            "binding-test",
        ),
        (
            "binding_tests",
            {"path": "test_a.py", "start_line": 0, "snippet": "x"},
            "binding-test",
        ),
        (
            "binding_tests",
            {"path": "test_a.py", "start_line": True, "snippet": "x"},
            "binding-test",
        ),
        (
            "binding_tests",
            {"path": "test_a.py", "start_line": 1, "snippet": " "},
            "binding-test",
        ),
    ],
)
def test_local_live_packet_selector_requires_qualifying_evidence_items(
    field: str,
    item: dict[str, object],
    message: str,
) -> None:
    def invariant_packet(packet_id: str) -> dict[str, object]:
        return {
            "packet_id": packet_id,
            "kind": "invariant",
            "targets": [{"path": "a.py", "start_line": 1, "snippet": "x"}],
            "binding_tests": [{"path": "test_a.py", "start_line": 1, "snippet": "y"}],
            "packet_warnings": [],
        }

    first = invariant_packet("invariant::INV.RES.1")
    first[field] = [item]
    packets_text = "\n".join(
        json.dumps(packet)
        for packet in (first, invariant_packet("invariant::INV.RES.2"))
    )

    with pytest.raises(AssertionError, match=f"bounded {message} evidence"):
        live_llm._select_local_live_packets(packets_text)


@pytest.mark.parametrize(
    ("packets", "message"),
    [
        (["invariant::INV.RES.1"], "must occur exactly once; found 0"),
        (
            ["invariant::INV.RES.1", "invariant::INV.RES.1", "invariant::INV.RES.2"],
            "must occur exactly once; found 2",
        ),
    ],
)
def test_local_live_packet_selector_requires_exactly_one_curated_packet(
    packets: list[str],
    message: str,
) -> None:
    def invariant_packet(packet_id: str) -> dict[str, object]:
        return {
            "packet_id": packet_id,
            "kind": "invariant",
            "targets": [{"path": "a.py", "start_line": 1, "snippet": "x"}],
            "binding_tests": [{"path": "test_a.py", "start_line": 1, "snippet": "y"}],
            "packet_warnings": [],
        }

    packets_text = "\n".join(json.dumps(invariant_packet(item)) for item in packets)

    with pytest.raises(AssertionError, match=message):
        live_llm._select_local_live_packets(packets_text)


def test_local_live_packet_selector_rejects_non_invariant_kind() -> None:
    packets = []
    for packet_id in live_llm.LOCAL_LIVE_PACKET_IDS:
        packets.append(
            {
                "packet_id": packet_id,
                "kind": "section" if packet_id.endswith(".1") else "invariant",
                "targets": [{"path": "a.py", "start_line": 1, "snippet": "x"}],
                "binding_tests": [
                    {"path": "test_a.py", "start_line": 1, "snippet": "y"}
                ],
                "packet_warnings": [],
            }
        )

    with pytest.raises(AssertionError, match="must have kind 'invariant'"):
        live_llm._select_local_live_packets(
            "\n".join(json.dumps(packet) for packet in packets)
        )


def test_local_live_packet_selector_matches_real_contract_corpus(
    tmp_path: Path,
) -> None:
    contract_root = live_llm._write_live_contract_repo(
        tmp_path / "contract",
        kind="local",
    )
    packets_path = tmp_path / "invariant-packets.jsonl"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "backstitch",
            "packets",
            "--repo-root",
            str(contract_root),
            "--code-root",
            "pkg",
            "--code-root",
            "tests",
            "--test-root",
            "tests",
            "--kind",
            "invariant",
            "--output",
            str(packets_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    selected = live_llm._select_local_live_packets(
        packets_path.read_text(encoding="utf-8")
    )

    assert tuple(str(packet["packet_id"]) for packet in selected) == (
        "invariant::INV.RES.1",
        "invariant::INV.RES.2",
    )


def test_openai_live_contract_is_ready_in_current_preflight(
    tmp_path: Path,
) -> None:
    contract_root = live_llm._write_live_contract_repo(
        tmp_path / "contract",
        kind="openai",
    )
    config = contract_root / ".backstitch.toml"
    descriptor = live_llm._live_descriptor_lines(
        kind="openai",
        adapter_model_id="gpt-5.6-luna",
    )
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "[analyze]\n",
            "[analyze]\n" + "\n".join(descriptor) + "\n",
            1,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "backstitch",
            "analyze",
            "--repo-root",
            str(contract_root),
            "--preflight",
            "--format",
            "json",
            "--config",
            str(config),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    prepared = json.loads(result.stdout)
    assert prepared["ready"] is True
    assert prepared["packet_plan"]["packet_count"] == 1
    assert prepared["budgets"]["analyzer"]["provider_calls"] == 1


def test_openai_cost_overage_fails_before_model_or_provider_activity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_resolutions = 0

    def unexpected_model_resolution(requested_model: str | None = None) -> str:
        nonlocal model_resolutions
        model_resolutions += 1
        return requested_model or "unexpected"

    monkeypatch.setattr(
        live_llm,
        "_openai_qualification_estimated_cost_microusd",
        lambda _request_bytes: (
            live_llm.OPENAI_QUALIFICATION_MAX_ESTIMATED_COST_MICROUSD + 1
        ),
    )
    monkeypatch.setattr(
        live_llm,
        "_resolve_live_model",
        unexpected_model_resolution,
    )

    with pytest.raises(ValueError, match=r"\$0\.10"):
        live_llm._exercise_live_llm_analysis_contract(
            tmp_path,
            monkeypatch,
            kind="openai",
            proxy=None,
            requested_model="gpt-5.6-luna",
        )

    assert model_resolutions == 0


def test_openai_qualification_replays_and_rejects_corrupt_cache_hermetically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise accepted replay and corrupt replay through the real CLI/cache."""

    requests: list[dict[str, object]] = []

    def strings(value: object) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, dict):
            return [text for child in value.values() for text in strings(child)]
        if isinstance(value, list):
            return [text for child in value for text in strings(child)]
        return []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - stdlib hook name
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = json.loads(self.rfile.read(length))
            requests.append(body)
            prompt = next(
                text
                for text in strings(body.get("input"))
                if '"packet_id"' in text and '"evidence_regions"' in text
            )
            projection = json.loads(prompt.rsplit("\n\n", 1)[1])
            model_response = {
                "packet_id": projection["packet_id"],
                "classification": "ambiguous",
                "confidence": 0.5,
                "rationale": "The bounded evidence does not settle the requirement.",
                "evidence": [projection["evidence_regions"][0]],
                "summary": "Evidence remains ambiguous.",
            }
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

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv(
            "OPENAI_BASE_URL", f"http://127.0.0.1:{server.server_port}/v1"
        )
        monkeypatch.setenv("OPENAI_API_KEY", "test-owned-no-network-key")
        provider_calls, estimated_cost = live_llm._exercise_live_llm_analysis_contract(
            tmp_path,
            monkeypatch,
            kind="openai",
            proxy=None,
            requested_model="gpt-5.6-luna",
        )

        assert provider_calls == 1
        assert estimated_cost <= (
            live_llm.OPENAI_QUALIFICATION_MAX_ESTIMATED_COST_MICROUSD
        )
        assert len(requests) == 1

        cache_root = tmp_path / "live-contract-repo" / ".backstitch" / "semantic-cache"
        result_objects = sorted((cache_root / "results").glob("*.json"))
        assert len(result_objects) == 1
        result_objects[0].write_text("{", encoding="utf-8")

        corrupt_report = tmp_path / "corrupt-replay-report.json"
        corrupt = live_llm._run_cli(
            "analyze",
            "--packets",
            str(tmp_path / "live-packets.jsonl"),
            "--packet-report",
            str(tmp_path / "live-packet-report.json"),
            "--model",
            "gpt-5.6-luna",
            "--concurrency",
            "1",
            "--config",
            str(tmp_path / "live-contract-repo" / ".backstitch.toml"),
            "--option",
            "analyze.cache_mode",
            "require",
            "--output",
            str(tmp_path / "corrupt-replay.jsonl"),
            "--report",
            str(corrupt_report),
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    corrupt_data = json.loads(corrupt_report.read_text(encoding="utf-8"))
    assert corrupt.returncode == 2
    assert corrupt_data["provider_calls"] == 0
    assert corrupt_data["problems"][0]["code"] == "corrupt_cache"
    assert len(requests) == 1

    def corrupt_replay(_model_name: str) -> tuple[int, int]:
        raise RuntimeError(json.dumps(corrupt_data["problems"], sort_keys=True))

    with pytest.raises(
        live_llm._QualificationProcessFailure,
        match=r"^qualification error:.*local qualification setup or preflight failed",
    ):
        live_llm._run_openai_qualifications(corrupt_replay)


def test_invalid_local_corpus_fails_before_provider_activity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    packet = {
        "packet_id": "invariant::INV.RES.1",
        "kind": "invariant",
        "targets": [{"path": "a.py", "start_line": 1, "snippet": "x"}],
        "binding_tests": [{"path": "test_a.py", "start_line": 1, "snippet": "y"}],
        "packet_warnings": [],
    }

    def fake_run_cli(*args: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert args[0] == "packets"
        assert args[args.index("--kind") + 1] == "all"
        output = Path(args[args.index("--output") + 1])
        output.write_text(json.dumps(packet) + "\n", encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, "", "")

    model_resolutions = 0
    model_listings = 0
    transport_probes = 0

    def unexpected_model_resolution() -> str:
        nonlocal model_resolutions
        model_resolutions += 1
        return "unexpected"

    def unexpected_model_listing(config: object) -> None:
        nonlocal model_listings
        model_listings += 1

    def unexpected_transport_probe(config: object) -> None:
        nonlocal transport_probes
        transport_probes += 1

    monkeypatch.setattr(live_llm, "_run_cli", fake_run_cli)
    monkeypatch.setattr(live_llm, "_resolve_live_model", unexpected_model_resolution)
    monkeypatch.setattr(live_llm, "_assert_model_listed", unexpected_model_listing)
    monkeypatch.setattr(
        live_llm,
        "_assert_local_transport",
        unexpected_transport_probe,
    )

    with live_llm._CountingProxy("http://127.0.0.1:9/v1") as proxy:
        with pytest.raises(AssertionError, match="must occur exactly once; found 0"):
            live_llm._exercise_live_llm_analysis_contract(
                tmp_path,
                monkeypatch,
                kind="local",
                proxy=proxy,
            )
        assert model_resolutions == 0
        assert model_listings == 0
        assert transport_probes == 0
        assert proxy.request_bodies == []
