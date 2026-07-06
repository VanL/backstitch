from __future__ import annotations

import http.server
import importlib.util
import json
import socket
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

            proxy.start_analyze_phase()
            body = json.dumps(
                {
                    "model": "backstitch-local-model",
                    "messages": [
                        {
                            "role": "user",
                            "content": "packet docs/specs/02-backstitch-core.md#SC-7",
                        }
                    ],
                }
            ).encode()
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
            proxy.stop_analyze_phase()

            assert seen_upstream_bodies == [body.decode()]
            assert proxy.request_bodies == [body.decode()]
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
