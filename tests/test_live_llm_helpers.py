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


def test_local_llm_counting_proxy_forwards_and_records_completion_requests() -> None:
    seen_upstream_bodies: list[str] = []

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
            payload = json.dumps({"choices": [{"message": {"content": "OK"}}]}).encode()
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
                "messages": [
                    {
                        "role": "user",
                        "content": "packet docs/specs/02-backstitch-core.md#SC-7",
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

            expected_payload = {
                **request_payload,
                "temperature": 0,
                "seed": 42,
            }
            assert [json.loads(body) for body in seen_upstream_bodies] == [
                expected_payload
            ]
            assert proxy.request_bodies == []

            seen_upstream_bodies.clear()
            proxy.start_analyze_phase()
            response = urllib.request.urlopen(request, timeout=5)  # noqa: S310
            assert response.status == 200
            proxy.stop_analyze_phase()

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


def test_local_llm_counting_proxy_relays_streaming_responses() -> None:
    # llm's Python API ignores `can_stream: false` (it is CLI-only), so real
    # local runs stream SSE through the proxy; this covers the shape
    # production actually uses, not just the plain-JSON response above.
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
            proxy.start_analyze_phase()
            request = urllib.request.Request(
                f"{proxy.endpoint}/chat/completions",
                data=json.dumps({"model": "m", "stream": True}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310 - loopback test server
                assert response.status == 200
                assert response.headers.get("Content-Type") == "text/event-stream"
                relayed = response.read()
            proxy.stop_analyze_phase()

            assert relayed == b"".join(sse_chunks)
            assert len(proxy.request_bodies) == 1
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
        json.dumps(
            {
                "model": "backstitch-local-model:latest",
                "messages": [
                    {
                        "role": "user",
                        "content": "invariant::INV.RES.1 invariant::INV.RES.2",
                    }
                ],
                "temperature": 1,
                "seed": 42,
            }
        ),
        json.dumps(
            {
                "model": "backstitch-local-model:latest",
                "messages": [
                    {
                        "role": "user",
                        "content": "invariant::INV.RES.1 invariant::INV.RES.2",
                    }
                ],
                "temperature": 0,
                "seed": 42,
            }
        ),
    ]

    with pytest.raises(AssertionError, match="unexpected inference controls"):
        live_llm._assert_analyze_hit_local_endpoint(
            proxy,
            expected_packet_ids=set(live_llm.LOCAL_LIVE_PACKET_IDS),
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


def test_local_live_packet_selector_matches_real_self_corpus(tmp_path: Path) -> None:
    packets_path = tmp_path / "invariant-packets.jsonl"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "backstitch",
            "packets",
            "--repo-root",
            ".",
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
        assert args[:5] == ("packets", "--repo-root", ".", "--kind", "invariant")
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
