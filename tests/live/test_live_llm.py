"""Optional live LLM smoke and contract test ([SC-7] live path).

Spec: docs/specs/02-backstitch-core.md [SC-7]
Plan: docs/plans/2026-07-03-live-llm-tests-plan.md
Plan: docs/plans/2026-07-03-local-llm-eval-lane-plan.md

Skipped unless ``BACKSTITCH_LIVE_LLM=1``. When enabled it drives the real CLI
(``packets`` -> ``analyze`` -> ``check`` -> ``summarize-analysis``) over this
repository's own specs, calling a real provider or a local OpenAI-compatible
endpoint through the production ``default_adapter``. It asserts structured
contracts and command behavior -- never model wording or classification.

Exit codes here prove the command path and artifact health, not model success:
``analyze`` exits 0 on partial failure ([SC-7]) and ``summarize-analysis`` exits
0 regardless of analysis-row quality. Cloud-provider runs assert that no result
row carries an ``error`` field. Local-endpoint runs are deliberately looser:
they assert endpoint reachability, a real adapter transport proof, that
``analyze`` sent the selected packet prompts through the local endpoint, and
non-total failure.
"""

from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from backstitch.analysis_llm import build_prompt
from backstitch.analysis_results import load_analysis_results, validate_analysis_row

# Function-level skip (not a module-level `pytest.skip(allow_module_level=True)`)
# so the test is COLLECTED and reported as skipped. A module-level skip makes
# `pytest tests/live/test_live_llm.py` collect nothing and exit 5 (no tests
# ran), which would fail the hermetic CI step that proves the gate skips.
# Collection stays hermetic: `import llm` lives inside the test body, not here.
pytestmark = [
    pytest.mark.live_llm,
    pytest.mark.skipif(
        os.environ.get("BACKSTITCH_LIVE_LLM") != "1",
        reason="live LLM tests are opt-in; set BACKSTITCH_LIVE_LLM=1 to run",
    ),
]

# Canonical default model. MUST stay byte-identical to
# DEFAULT_BACKSTITCH_LIVE_LLM_MODEL in .github/workflows/ci.yml -- treat the two
# copies as one value. Re-check `uv run llm models list` and OpenAI's model docs
# before changing it; availability changes faster than this repo.
DEFAULT_BACKSTITCH_LIVE_LLM_MODEL = "gpt-5.4-mini"
DEFAULT_BACKSTITCH_LOCAL_LLM_BASE_MODEL = "llama3.2:3b"
DEFAULT_BACKSTITCH_LOCAL_LLM_SERVED_MODEL = DEFAULT_BACKSTITCH_LOCAL_LLM_BASE_MODEL

REPO_ROOT = Path(__file__).resolve().parents[2]
LIVE_SPEC = "docs/specs/02-backstitch-core.md"
DEFAULT_LIVE_PACKETS = 1
DEFAULT_LOCAL_LIVE_PACKETS = 2
MAX_LIVE_PACKETS = 5
DEFAULT_LOCAL_ENDPOINT = "http://127.0.0.1:11434/v1"
LOCAL_HTTP_TIMEOUT_SECONDS = 20
LOCAL_SUBPROCESS_TIMEOUT_SECONDS = 300
LOCAL_ANALYZE_TIMEOUT_SECONDS = 900
# Conservative top of the plan's ~3-4 bytes/token range. Assumed, not measured:
# a target-runner bake-off has not produced a K figure yet (recorded in the
# plan); replace with the measured value when one exists.
LOCAL_ASSUMED_BYTES_PER_TOKEN = 4


def _local_prompt_byte_ceiling() -> int:
    """Prompt budget derived from the same context bound the server enforces.

    Reads ``OLLAMA_CONTEXT_LENGTH`` (the workflow's single-source context env)
    so retuning the workflow cannot silently desynchronize this guard from the
    served model's actual context window.
    """
    context_length = int(os.environ.get("OLLAMA_CONTEXT_LENGTH", "4096"))
    return context_length * LOCAL_ASSUMED_BYTES_PER_TOKEN


@dataclass
class _CountingProxy:
    """Tiny stdlib proxy used only by the opt-in local live lane."""

    upstream_endpoint: str
    server: Any | None = None
    thread: Any | None = None
    request_bodies: list[str] = field(default_factory=list)
    recording: bool = False

    def __enter__(self) -> _CountingProxy:
        import http.server
        import threading
        import urllib.error
        import urllib.request

        proxy = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - stdlib hook name
                self._forward()

            def do_POST(self) -> None:  # noqa: N802 - stdlib hook name
                self._forward()

            def log_message(self, format: str, *args: object) -> None:
                return

            def _forward(self) -> None:
                length = int(self.headers.get("Content-Length", "0") or "0")
                body = self.rfile.read(length) if length else b""
                if (
                    proxy.recording
                    and self.command == "POST"
                    and _is_completion_path(self.path)
                ):
                    proxy.request_bodies.append(body.decode("utf-8", errors="replace"))

                headers = {
                    key: value
                    for key, value in self.headers.items()
                    if key.lower()
                    not in {"host", "content-length", "connection", "accept-encoding"}
                }
                request = urllib.request.Request(
                    proxy.forward_url(self.path),
                    data=body if body else None,
                    headers=headers,
                    method=self.command,
                )
                self._response_started = False
                try:
                    try:
                        with urllib.request.urlopen(
                            request, timeout=LOCAL_ANALYZE_TIMEOUT_SECONDS
                        ) as response:
                            self._send_streaming_response(
                                response.status, response.headers.items(), response
                            )
                    except urllib.error.HTTPError as exc:
                        self._send_streaming_response(
                            exc.code, exc.headers.items(), exc
                        )
                except Exception as exc:  # noqa: BLE001 - preserve proxy diagnostics
                    if self._response_started:
                        # The status line and headers are already on the wire; a
                        # trailing 502 would inject a second status line into the
                        # body. Drop the connection so the client sees a short
                        # read instead of corrupt HTTP.
                        self.close_connection = True
                        return
                    self._send_502(f"proxy forwarding error: {exc}")

            def _send_502(self, message: str) -> None:
                payload = message.encode()
                self.send_response(502)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def _send_streaming_response(
                self,
                status: int,
                headers: Any,
                source: Any,
            ) -> None:
                self._response_started = True
                self.send_response(status)
                for key, value in headers:
                    if key.lower() in {
                        "connection",
                        "content-length",
                        "transfer-encoding",
                    }:
                        continue
                    self.send_header(key, value)
                self.send_header("Connection", "close")
                self.end_headers()
                while True:
                    chunk = source.readline()
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
                self.close_connection = True

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=5)

    @property
    def endpoint(self) -> str:
        assert self.server is not None
        return f"http://127.0.0.1:{self.server.server_port}/v1"

    def forward_url(self, path: str) -> str:
        # The adapter's api_base is `<proxy>/v1`, so client paths arrive as
        # `/v1/...`. Map that suffix onto the upstream endpoint — which may
        # carry its own path prefix (e.g. `/ollama/v1`) — instead of assuming
        # the upstream path is exactly `/v1`.
        if path == "/v1" or path.startswith("/v1/"):
            return _joined_endpoint(self.upstream_endpoint, path[len("/v1") :])
        return f"{_endpoint_origin(self.upstream_endpoint)}{path}"

    def start_analyze_phase(self) -> None:
        self.request_bodies.clear()
        self.recording = True

    def stop_analyze_phase(self) -> None:
        self.recording = False


@dataclass(frozen=True)
class _LocalConfig:
    upstream_endpoint: str
    adapter_endpoint: str
    served_model: str
    llm_home: Path


def _run_cli(
    *args: str,
    label: str = "backstitch",
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke the CLI as a subprocess using the running interpreter.

    Uses ``sys.executable -m backstitch`` so the subprocess shares this test's
    venv, ``backstitch``, and ``llm`` install rather than whatever bare
    ``python`` resolves to on PATH.
    """

    try:
        return subprocess.run(
            [sys.executable, "-m", "backstitch", *args],
            capture_output=True,
            text=True,
            check=False,
            cwd=REPO_ROOT,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(f"{label} timed out after {timeout} seconds: {exc.cmd}")


def _assert_no_traceback(result: subprocess.CompletedProcess[str], label: str) -> None:
    assert "Traceback (most recent call last)" not in result.stderr, (
        f"{label} printed a traceback:\n{result.stderr}"
    )


def _live_kind() -> str:
    kind = os.environ.get("BACKSTITCH_LIVE_LLM_KIND", "openai")
    if kind not in {"openai", "local"}:
        pytest.fail(
            f"BACKSTITCH_LIVE_LLM_KIND must be `openai` or `local`, got {kind!r}"
        )
    return kind


def _resolve_live_model() -> str:
    import llm

    model_name = os.environ.get("LLM_MODEL") or DEFAULT_BACKSTITCH_LIVE_LLM_MODEL
    try:
        model = llm.get_model(model_name)
    except llm.UnknownModelError as exc:
        pytest.fail(
            f"live model {model_name!r} is not registered in llm; set LLM_MODEL "
            f"or update DEFAULT_BACKSTITCH_LIVE_LLM_MODEL ({exc})"
        )
    # Provider-general credential preflight driven by the model's own declared
    # key requirement -- do not guess a provider. A keyless (local) model needs
    # no credential; the plan asks that new providers extend this explicitly.
    needs_key = getattr(model, "needs_key", None)
    if needs_key:
        env_var = getattr(model, "key_env_var", None) or ""
        key = llm.get_key(key_alias=needs_key, env_var=env_var)
        if not key:
            hint = f" or `{env_var}`" if env_var else ""
            pytest.fail(
                f"live gate enabled but no credential for provider key "
                f"{needs_key!r}; store one with `llm keys set {needs_key}`{hint}"
            )
    return model_name


def _select_live_packets(
    all_packets_text: str,
    count: int,
    *,
    require_semantic_owner: bool = True,
) -> list[dict[str, object]]:
    """Deterministically choose the bounded live subset from generated packets.

    There is no packet-filter subcommand and calling ``analyze_packets``
    directly is forbidden, so the filtering lives here. Cloud runs keep the
    historic semantic-module focus; local CPU runs may choose the smallest real
    packets from the repository corpus to keep the transport canary bounded.
    """

    candidates: list[tuple[int, dict[str, object]]] = []
    for index, raw in enumerate(all_packets_text.splitlines()):
        raw = raw.strip()
        if not raw:
            continue
        packet = json.loads(raw)
        if require_semantic_owner:
            if packet.get("spec_path") != LIVE_SPEC:
                continue
            owner_paths = [
                str(owner.get("path", "")) for owner in packet.get("owners", [])
            ]
            if not any(
                path == "backstitch/cli.py"
                or fnmatch.fnmatch(path, "backstitch/analysis_*.py")
                for path in owner_paths
            ):
                continue
        candidates.append((index, packet))
    candidates.sort(
        key=lambda item: (len(json.dumps(item[1])), str(item[1]["packet_id"]), item[0])
    )
    return [packet for _, packet in candidates[:count]]


def _endpoint_origin(endpoint: str) -> str:
    import urllib.parse

    parsed = urllib.parse.urlsplit(endpoint)
    if not parsed.scheme or not parsed.netloc:
        pytest.fail(f"local LLM endpoint must be absolute, got {endpoint!r}")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def _joined_endpoint(endpoint: str, path: str) -> str:
    return f"{endpoint.rstrip('/')}/{path.lstrip('/')}"


def _is_completion_path(path: str) -> bool:
    return path.startswith("/v1/") and "completions" in path


def _assert_loopback_endpoint(endpoint: str) -> None:
    import urllib.parse

    if os.environ.get("BACKSTITCH_LOCAL_LLM_ALLOW_NONLOCAL") == "1":
        return
    parsed = urllib.parse.urlsplit(endpoint)
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail(
            "BACKSTITCH_LIVE_LLM_KIND=local requires a loopback endpoint; "
            "set BACKSTITCH_LOCAL_LLM_ALLOW_NONLOCAL=1 only for a deliberate "
            f"non-local test endpoint (got {endpoint!r})"
        )


def _resolve_local_upstream() -> str:
    """Resolve the upstream endpoint the proxy forwards to, exactly once.

    The proxy carries the resolved value afterwards, so the loopback guard
    always validates the same endpoint the traffic actually uses — never a
    second, independently resolved copy.
    """

    upstream = (
        os.environ.get("BACKSTITCH_LOCAL_LLM_UPSTREAM")
        or os.environ.get("BACKSTITCH_LOCAL_LLM_ENDPOINT")
        or DEFAULT_LOCAL_ENDPOINT
    )
    _assert_loopback_endpoint(upstream)
    return upstream


def _read_json_url(url: str) -> dict[str, object]:
    import urllib.error
    import urllib.request

    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(
            request, timeout=LOCAL_HTTP_TIMEOUT_SECONDS
        ) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        pytest.fail(f"{url} returned HTTP {exc.code}: {detail}")
    except urllib.error.URLError as exc:
        pytest.fail(f"{url} is unreachable: {exc}")
    except json.JSONDecodeError as exc:
        pytest.fail(f"{url} did not return JSON: {exc}")

    if not isinstance(payload, dict):
        pytest.fail(f"{url} returned non-object JSON: {payload!r}")
    return payload


def _assert_model_listed(config: _LocalConfig) -> None:
    url = _joined_endpoint(config.adapter_endpoint, "models")
    payload = _read_json_url(url)
    raw_data = payload.get("data")
    if not isinstance(raw_data, list):
        pytest.fail(f"{url} returned no OpenAI-style data list: {payload!r}")
    ids = [
        str(item.get("id"))
        for item in raw_data
        if isinstance(item, dict) and item.get("id") is not None
    ]
    if config.served_model not in ids:
        pytest.fail(
            f"{url} did not list model {config.served_model!r}; seen ids: {ids}"
        )


def _configure_local_llm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    proxy: _CountingProxy,
) -> _LocalConfig:
    upstream = proxy.upstream_endpoint
    served_model = os.environ.get(
        "BACKSTITCH_LOCAL_LLM_SERVED_MODEL",
        DEFAULT_BACKSTITCH_LOCAL_LLM_SERVED_MODEL,
    )

    llm_home = tmp_path / "llm-home"
    llm_home.mkdir()
    model_record = {
        "model_id": "backstitch-local",
        "model_name": served_model,
        "api_base": proxy.endpoint,
        # Honored only by llm's CLI; the Python API path `analyze` uses still
        # issues streaming (SSE) requests, which the proxy relays untouched.
        "can_stream": False,
    }
    (llm_home / "extra-openai-models.yaml").write_text(
        json.dumps([model_record]), encoding="utf-8"
    )
    monkeypatch.setenv("LLM_USER_PATH", str(llm_home))
    monkeypatch.setenv("LLM_MODEL", "backstitch-local")

    return _LocalConfig(
        upstream_endpoint=upstream,
        adapter_endpoint=proxy.endpoint,
        served_model=served_model,
        llm_home=llm_home,
    )


def _assert_local_transport(config: _LocalConfig) -> None:
    script = f"""
import sys

import llm

from backstitch.analysis_llm import default_adapter

expected_api_base = {config.adapter_endpoint!r}.rstrip("/")
model = llm.get_model("backstitch-local")
actual_api_base = getattr(model, "api_base", None)
if actual_api_base is None:
    raise SystemExit("llm model has no api_base; re-check llm version binding")
if str(actual_api_base).rstrip("/") != expected_api_base:
    raise SystemExit(
        f"api_base mismatch: {{actual_api_base!r}} != {{expected_api_base!r}}"
    )
if getattr(model, "needs_key", None) is not None:
    raise SystemExit(
        f"local api_base model unexpectedly requires key {{model.needs_key!r}}"
    )

adapter = default_adapter("backstitch-local")
out = adapter("Reply with the single word OK")
if not str(out).strip():
    raise SystemExit("transport preflight returned empty text")
print(str(out).strip())
"""
    try:
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            check=False,
            cwd=REPO_ROOT,
            timeout=LOCAL_SUBPROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(
            "local transport preflight timed out after "
            f"{LOCAL_SUBPROCESS_TIMEOUT_SECONDS} seconds: {exc.cmd}"
        )
    _assert_no_traceback(result, "local transport preflight")
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip(), "local transport preflight returned no text"


def _assert_local_prompt_budget(subset: list[dict[str, object]]) -> None:
    ceiling = _local_prompt_byte_ceiling()
    too_large: list[str] = []
    for packet in subset:
        prompt_bytes = len(build_prompt(packet).encode("utf-8"))
        if prompt_bytes > ceiling:
            too_large.append(f"{packet['packet_id']} ({prompt_bytes} bytes)")
    assert not too_large, (
        f"selected local-live packets exceed the prompt byte ceiling ({ceiling} "
        f"bytes = OLLAMA_CONTEXT_LENGTH * {LOCAL_ASSUMED_BYTES_PER_TOKEN} assumed "
        "bytes/token); shrink DEFAULT_LOCAL_LIVE_PACKETS or retune "
        f"OLLAMA_CONTEXT_LENGTH. Oversized: {too_large}"
    )


def _assert_analyze_hit_local_endpoint(
    proxy: _CountingProxy,
    *,
    expected_packet_ids: set[str],
    served_model: str,
) -> None:
    assert len(proxy.request_bodies) >= len(expected_packet_ids), (
        "local analyze did not send enough completion requests through the "
        f"counting proxy: {len(proxy.request_bodies)} requests for "
        f"{len(expected_packet_ids)} packets"
    )
    joined = "\n".join(proxy.request_bodies)
    missing_ids = sorted(
        packet_id for packet_id in expected_packet_ids if packet_id not in joined
    )
    assert not missing_ids, (
        f"local analyze requests did not include selected packet ids: {missing_ids}"
    )
    wrong_models: list[object] = []
    for body in proxy.request_bodies:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            pytest.fail(f"local analyze request body was not JSON: {exc}: {body}")
        if isinstance(payload, dict) and payload.get("model") != served_model:
            wrong_models.append(payload.get("model"))
    assert not wrong_models, (
        f"local analyze used unexpected model values: {wrong_models}; "
        f"expected {served_model!r}"
    )


def test_live_llm_analysis_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kind = _live_kind()

    if kind == "local":
        with _CountingProxy(_resolve_local_upstream()) as proxy:
            _exercise_live_llm_analysis_contract(
                tmp_path,
                monkeypatch,
                kind=kind,
                proxy=proxy,
            )
        return

    _exercise_live_llm_analysis_contract(
        tmp_path,
        monkeypatch,
        kind=kind,
        proxy=None,
    )


def _exercise_live_llm_analysis_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    kind: str,
    proxy: _CountingProxy | None,
) -> None:
    local_config: _LocalConfig | None = None
    if kind == "local":
        assert proxy is not None
        local_config = _configure_local_llm(tmp_path, monkeypatch, proxy)

    live_model = _resolve_live_model()

    if local_config is not None:
        _assert_model_listed(local_config)
        _assert_local_transport(local_config)

    all_packets = tmp_path / "all-packets.jsonl"
    live_packets = tmp_path / "live-packets.jsonl"
    analysis = tmp_path / "analysis.jsonl"
    report = tmp_path / "report.json"

    # 1. Generate the full packet corpus through the real CLI.
    gen = _run_cli("packets", "--repo-root", ".", "--output", str(all_packets))
    _assert_no_traceback(gen, "packets")
    assert gen.returncode == 0, gen.stderr
    all_text = all_packets.read_text(encoding="utf-8")
    assert all_text.strip(), "packets produced empty output"

    # 2. Build the bounded live subset in-process and write it out.
    packet_count = (
        DEFAULT_LOCAL_LIVE_PACKETS if kind == "local" else DEFAULT_LIVE_PACKETS
    )
    subset = _select_live_packets(
        all_text,
        packet_count,
        require_semantic_owner=kind != "local",
    )
    if kind == "local":
        assert subset, "local live LLM testing needs at least one generated packet"
    else:
        assert subset, (
            f"no packets from {LIVE_SPEC} own a semantic-analysis module; the "
            "dogfood corpus stopped exercising the live semantic path"
        )
    assert len(subset) <= MAX_LIVE_PACKETS
    if kind == "local":
        assert len(subset) >= 2, (
            "local live LLM testing needs at least two packets; with one packet "
            "a single error row is total failure, making leniency vacuous"
        )
        _assert_local_prompt_budget(subset)
    expected_packet_ids = {str(packet["packet_id"]) for packet in subset}
    live_packets.write_text(
        "".join(json.dumps(packet) + "\n" for packet in subset), encoding="utf-8"
    )

    # 3. Real provider call through the public analyze command.
    if proxy is not None:
        proxy.start_analyze_phase()
    ana = _run_cli(
        "analyze",
        "--packets",
        str(live_packets),
        "--model",
        live_model,
        "--concurrency",
        "1",
        "--no-config",
        "--output",
        str(analysis),
        label="analyze",
        timeout=LOCAL_ANALYZE_TIMEOUT_SECONDS if kind == "local" else None,
    )
    if proxy is not None:
        proxy.stop_analyze_phase()
    _assert_no_traceback(ana, "analyze")
    assert ana.returncode == 0, ana.stderr
    if local_config is not None and proxy is not None:
        _assert_analyze_hit_local_endpoint(
            proxy,
            expected_packet_ids=expected_packet_ids,
            served_model=local_config.served_model,
        )

    # 4. Deterministic report over the full repo (committed config, not
    #    --no-config) so summarize can resolve subset packet IDs against the
    #    same report surface a normal user produces.
    chk = _run_cli(
        "check", "--repo-root", ".", "--format", "json", "--output", str(report)
    )
    _assert_no_traceback(chk, "check")
    assert chk.returncode == 0, chk.stderr

    # 5. Summary consumer accepts the model output.
    summ = _run_cli(
        "summarize-analysis",
        "--deterministic-report",
        str(report),
        "--analysis-results",
        str(analysis),
    )
    _assert_no_traceback(summ, "summarize-analysis")
    assert summ.returncode == 0, summ.stderr

    # --- Row-level contract assertions (these carry the real weight) ---
    analysis_text = analysis.read_text(encoding="utf-8")
    raw_rows = [json.loads(line) for line in analysis_text.splitlines() if line.strip()]
    assert len(raw_rows) == len(subset), (
        f"expected one result row per live packet ({len(subset)}), got {len(raw_rows)}"
    )

    # Cloud-provider model assertion: a contained provider/model failure is a
    # schema-valid `ambiguous` row WITH an `error` field. Local-endpoint runs
    # tolerate individual error rows, but still require non-total failure.
    errored = [row for row in raw_rows if "error" in row]
    strict = os.environ.get("BACKSTITCH_LIVE_LLM_STRICT") == "1"
    if kind == "openai" or strict:
        assert not errored, f"live analysis rows carry error fields: {errored}"
    else:
        non_error_count = sum(1 for row in raw_rows if "error" not in row)
        assert non_error_count >= 1, (
            "local live analysis produced no non-error rows; transport may have "
            f"worked but every packet failed: {raw_rows}"
        )
        assert len(errored) < len(raw_rows), (
            "local live analysis produced only error rows; analyze should have "
            f"exited 2 instead of passing: {raw_rows}"
        )
        if len(raw_rows) >= 3:
            assert non_error_count >= 2, (
                "local live analysis with three or more packets needs at least "
                f"two non-error rows; got {non_error_count}: {raw_rows}"
            )

    for row in raw_rows:
        result = validate_analysis_row(row, expected_packet_ids)
        assert not isinstance(result, str), f"invalid result row: {result}"
        assert str(row["packet_id"]) in expected_packet_ids

    # Independent of summarize's exit code: summarize renders analysis-load
    # problems and still exits 0 when the report is valid.
    load = load_analysis_results(analysis_text, expected_packet_ids)
    assert load.errors == (), f"analysis load errors: {load.errors}"
