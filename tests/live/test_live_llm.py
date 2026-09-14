"""Live LLM smoke and contract test ([SC-7], [SC-10] live path).

Spec: docs/specs/02-backstitch-core.md [SC-7]
Plan: docs/plans/2026-07-03-live-llm-tests-plan.md
Plan: docs/plans/2026-07-03-local-llm-eval-lane-plan.md

Enabled by this repository's ``run_live_llm`` pytest setting for ordinary local
runs. Current hermetic CI overrides that setting off; dedicated lanes may still
enable it with ``BACKSTITCH_LIVE_LLM=1``. When enabled it drives the real CLI
(``packets`` -> ``analyze`` -> ``check`` -> ``summarize-analysis``) over this
repository's own specs, calling a real provider or a local OpenAI-compatible
endpoint through the production ``default_provider_adapter``. It asserts structured
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
import http.server
import json
import os
import re
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from backstitch.analysis_llm import _semantic_response_schema
from backstitch.analysis_results import (
    INVARIANT_CLASSIFICATIONS,
    load_analysis_results,
    validate_analysis_row,
)
from backstitch.canonical import lf_end_line
from backstitch.semantic_packets import (
    model_request_bytes,
    prompt_instruction_bytes,
)

# The root collection hook applies policy skips after collecting this marker,
# so a disabled direct invocation reports one skip instead of exiting 5.
# Collection stays hermetic: `import llm` lives inside the test body, not here.
pytestmark = pytest.mark.live_llm

# Keep this reviewed default aligned with the repository descriptor. Live cloud
# probes normalize aliases to exact snapshots before provider construction.
DEFAULT_BACKSTITCH_LIVE_LLM_MODEL = "gpt-5.6-luna"
OPENAI_QUALIFICATION_MODELS = (
    "gpt-5.6-luna",
    "gpt-5.5-2026-04-23",
)
DEFAULT_BACKSTITCH_LOCAL_LLM_BASE_MODEL = "llama3.2:3b"
DEFAULT_BACKSTITCH_LOCAL_LLM_SERVED_MODEL = DEFAULT_BACKSTITCH_LOCAL_LLM_BASE_MODEL

REPO_ROOT = Path(__file__).resolve().parents[2]
LIVE_SPEC = "docs/specs/02-backstitch-core.md"
MAX_LIVE_PACKETS = 5
OPENAI_QUALIFICATION_MAX_CALLS = 2
OPENAI_QUALIFICATION_MAX_ESTIMATED_COST_MICROUSD = 100_000
OPENAI_QUALIFICATION_TIMEOUT_SECONDS = 300
LOCAL_LIVE_PACKET_IDS = (
    "invariant::INV.RES.1",
    "invariant::INV.RES.2",
)
DEFAULT_LOCAL_ENDPOINT = "http://127.0.0.1:11434/v1"
LOCAL_HTTP_TIMEOUT_SECONDS = 20
LOCAL_SUBPROCESS_TIMEOUT_SECONDS = 300
LOCAL_ANALYZE_TIMEOUT_SECONDS = 900
LOCAL_INFERENCE_TEMPERATURE = 0
LOCAL_INFERENCE_SEED = 42
LOCAL_ANALYZE_MAX_TOKENS = 1024
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
    """Local test proxy that applies and records effective inference controls."""

    upstream_endpoint: str
    server: Any | None = None
    thread: Any | None = None
    request_bodies: list[str] = field(default_factory=list)
    analyze_packet_ids: set[str] = field(default_factory=set)
    recording: bool = False

    def __enter__(self) -> _CountingProxy:
        handler = _counting_proxy_handler(self)
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
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
        self.analyze_packet_ids.clear()
        self.recording = True

    def stop_analyze_phase(self) -> None:
        self.recording = False


class _CountingProxyHandler(http.server.BaseHTTPRequestHandler):
    proxy: _CountingProxy

    def do_GET(self) -> None:  # noqa: N802 - stdlib hook name
        self._forward()

    def do_POST(self) -> None:  # noqa: N802 - stdlib hook name
        self._forward()

    def log_message(self, format: str, *args: object) -> None:
        return

    def _forward(self) -> None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length) if length else b""
        prepared = self._prepare_completion(body)
        if prepared is None:
            return
        request = self._upstream_request(prepared)
        self._relay(request)

    def _prepare_completion(self, body: bytes) -> bytes | None:
        if self.command != "POST" or not _is_completion_path(self.path):
            return body
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._send_400(f"invalid completion request JSON: {exc}")
            return None
        if not isinstance(payload, dict):
            self._send_400("invalid completion request JSON: expected an object")
            return None
        if self.proxy.recording:
            if not self._prepare_recorded_analyze(payload):
                return None
        normalized = json.dumps(payload).encode("utf-8")
        if self.proxy.recording:
            self.proxy.request_bodies.append(normalized.decode("utf-8"))
        return normalized

    def _prepare_recorded_analyze(self, payload: dict[str, Any]) -> bool:
        if payload.get("stream") is not True:
            self._send_400(
                "local analyze request must use the adapter's streaming path"
            )
            return False
        try:
            packet = _local_analyze_packet(payload)
            packet_id = str(packet["packet_id"])
            if packet_id in self.proxy.analyze_packet_ids:
                raise ValueError(
                    "local analyze packet may be forwarded upstream only once: "
                    f"{packet_id}"
                )
            if not self._has_expected_response_format(payload, packet):
                return False
        except ValueError as exc:
            self._send_400(str(exc))
            return False
        self.proxy.analyze_packet_ids.add(packet_id)
        return True

    def _has_expected_response_format(
        self, payload: dict[str, Any], packet: dict[str, Any]
    ) -> bool:
        if packet.get("packet_contract_version") != 3:
            if payload.get("response_format") != {"type": "json_object"}:
                self._send_400(
                    "local analyze request must arrive with the adapter's "
                    "json_object response format"
                )
                return False
            return True
        response_format = payload.get("response_format")
        json_schema = (
            response_format.get("json_schema")
            if isinstance(response_format, dict)
            else None
        )
        valid = (
            isinstance(response_format, dict)
            and response_format.get("type") == "json_schema"
            and isinstance(json_schema, dict)
            and isinstance(json_schema.get("schema"), dict)
            and json_schema["schema"]
            == _semantic_response_schema(_local_analyze_prompt(payload))
        )
        if not valid:
            self._send_400(
                "local analyze request must preserve the adapter's packet-bound "
                "JSON schema; got " + repr(response_format)[:500]
            )
            return False
        return True

    def _upstream_request(self, body: bytes) -> Any:
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower()
            not in {"host", "content-length", "connection", "accept-encoding"}
        }
        return urllib.request.Request(
            self.proxy.forward_url(self.path),
            data=body if body else None,
            headers=headers,
            method=self.command,
        )

    def _relay(self, request: Any) -> None:
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
                self._send_streaming_response(exc.code, exc.headers.items(), exc)
        except Exception as exc:  # noqa: BLE001 - preserve proxy diagnostics
            if self._response_started:
                # A status line is already on the wire. Drop the connection so
                # the client sees a short read instead of a second status line.
                self.close_connection = True
                return
            self._send_502(f"proxy forwarding error: {exc}")

    def _send_502(self, message: str) -> None:
        self._send_error(502, message)

    def _send_400(self, message: str) -> None:
        self._send_error(400, message)

    def _send_error(self, status: int, message: str) -> None:
        payload = message.encode()
        self.send_response(status)
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
        while chunk := source.readline():
            self.wfile.write(chunk)
            self.wfile.flush()
        self.close_connection = True


def _counting_proxy_handler(proxy: _CountingProxy) -> type[Any]:
    return type(
        "_BoundCountingProxyHandler",
        (_CountingProxyHandler,),
        {"proxy": proxy},
    )


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
        raise RuntimeError(
            f"{label} timed out after {timeout} seconds: {exc.cmd}"
        ) from exc


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


def _resolve_live_model(requested_model: str | None = None) -> str:
    import llm

    fixed_selection = requested_model is not None
    requested_model = (
        requested_model
        or os.environ.get("LLM_MODEL")
        or DEFAULT_BACKSTITCH_LIVE_LLM_MODEL
    )
    model_name = {
        "gpt-5.5": "gpt-5.5-2026-04-23",
    }.get(requested_model, requested_model)
    try:
        model = llm.get_model(model_name)
    except llm.UnknownModelError as exc:
        if fixed_selection:
            raise RuntimeError(
                f"adapter cannot resolve selected model {model_name!r}"
            ) from exc
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
            if fixed_selection:
                raise RuntimeError(
                    f"missing credential for selected model {model_name!r}"
                )
            hint = f" or `{env_var}`" if env_var else ""
            pytest.fail(
                f"live gate enabled but no credential for provider key "
                f"{needs_key!r}; store one with `llm keys set {needs_key}`{hint}"
            )
    return model_name


def _qualification_failure_category(error: BaseException) -> tuple[str, str]:
    """Map a bounded live failure to its release-process outcome."""

    detail = str(error).lower()
    status_match = re.search(
        r"(?:http|status(?: code)?|error code)\s*[:=]?\s*(\d{3})", detail
    )
    status = int(status_match.group(1)) if status_match is not None else None
    if status in {400, 404, 422} or any(
        marker in detail
        for marker in (
            "provider request incompatible",
            "does not support request options",
            "cannot resolve selected model",
            "error fields",
            "invalid result row",
            "closed schema",
            "normalization",
            "malformed_result",
        )
    ):
        return "incompatible", "exact request or closed response contract rejected"
    if status in {401, 403, 408, 409, 429} or status is not None and status >= 500:
        return "unavailable", "provider access or service unavailable"
    if any(
        marker in detail
        for marker in (
            "credential",
            "api key",
            "authorization",
            "rate limit",
            "timeout",
            "timed out",
            "connection",
            "connect",
            "dns",
            "tls",
            "network",
            "temporarily unavailable",
            "provider_failure",
        )
    ):
        return "unavailable", "provider access or service unavailable"
    return "qualification error", "local qualification setup or preflight failed"


def _qualification_selection_label(adapter_model_id: str) -> str:
    stable_model_id = {
        "gpt-5.6-luna": "pkg:service/openai.com/gpt-5.6-luna",
        "gpt-5.5-2026-04-23": "pkg:service/openai.com/gpt-5.5",
    }.get(adapter_model_id, "stable model unavailable")
    return f"{stable_model_id} / {adapter_model_id}"


def _assert_openai_qualification_bounds(
    *, provider_calls: int, estimated_cost_microusd: int
) -> None:
    if provider_calls > OPENAI_QUALIFICATION_MAX_CALLS:
        raise ValueError("OpenAI qualification exceeds its two-call ceiling")
    if estimated_cost_microusd > OPENAI_QUALIFICATION_MAX_ESTIMATED_COST_MICROUSD:
        raise ValueError("OpenAI qualification exceeds its $0.10 cost ceiling")


def _openai_qualification_estimated_cost_microusd(
    request_byte_count: int,
) -> int:
    """Project both fixed calls with the production conservative estimator."""

    if request_byte_count < 0:
        raise ValueError("qualification request byte count must be nonnegative")
    input_tokens = request_byte_count + 256

    def ceil_million(value: int) -> int:
        return (value + 999_999) // 1_000_000

    return sum(
        ceil_million(input_tokens * input_rate) + ceil_million(max_tokens * output_rate)
        for max_tokens, input_rate, output_rate in (
            (16_384, 400_000, 1_800_000),
            (1_024, 5_000_000, 30_000_000),
        )
    )


class _QualificationProcessFailure(RuntimeError):
    """One bounded, already-categorized release qualification failure."""


def _run_openai_qualifications(
    exercise: Callable[[str], tuple[int, int]],
) -> tuple[str, ...]:
    """Run both fixed selections and enforce event-wide bounds."""

    provider_calls = 0
    estimated_cost_microusd = 0
    messages: list[str] = []
    for model_name in OPENAI_QUALIFICATION_MODELS:
        selection = _qualification_selection_label(model_name)
        try:
            calls, cost = exercise(model_name)
        except Exception as exc:
            category, reason = _qualification_failure_category(exc)
            raise _QualificationProcessFailure(
                f"{category}: {selection} ({reason})"
            ) from exc
        if calls != 1:
            raise _QualificationProcessFailure(
                f"qualification error: {selection} "
                "(descriptor did not make exactly one provider call)"
            )
        provider_calls += calls
        estimated_cost_microusd += cost
        try:
            _assert_openai_qualification_bounds(
                provider_calls=provider_calls,
                estimated_cost_microusd=estimated_cost_microusd,
            )
        except ValueError as exc:
            raise _QualificationProcessFailure(
                f"qualification error: {selection} "
                "(OpenAI qualification budget preflight failed)"
            ) from exc
        messages.append(f"compatible: {selection}")
    if provider_calls != OPENAI_QUALIFICATION_MAX_CALLS:
        raise _QualificationProcessFailure(
            "qualification error: OpenAI qualification did not make two calls"
        )
    return tuple(messages)


def _live_descriptor_lines(*, kind: str, adapter_model_id: str) -> list[str]:
    """Return one complete, costed descriptor for the qualified transport."""

    if kind == "local":
        stable_model_id = "pkg:service/local.test/live-contract"
        plugin_id = "live-contract"
        capability_revision = "local-live-contract-v1"
        maximum_input_bytes = _local_prompt_byte_ceiling()
        temperature = float(LOCAL_INFERENCE_TEMPERATURE)
        input_rate = 0
        output_rate = 0
        maximum_cost = 0
        max_tokens = LOCAL_ANALYZE_MAX_TOKENS
        cost_source = "non-billable loopback live-contract endpoint"
    elif adapter_model_id == "gpt-5.6-luna":
        stable_model_id = "pkg:service/openai.com/gpt-5.6-luna"
        plugin_id = "openai"
        capability_revision = "openai-gpt-5.6-luna-2026-08-23"
        maximum_input_bytes = 1_600_000
        temperature = None
        input_rate = 400_000
        output_rate = 1_800_000
        maximum_cost = 100_000
        max_tokens = 16_384
        reasoning_effort = "max"
        cost_source = (
            "OpenAI GPT-5.6 Luna model page, reviewed 2026-08-23; "
            "conservative rates include the published long-prompt multiplier"
        )
    elif adapter_model_id == "gpt-5.5-2026-04-23":
        stable_model_id = "pkg:service/openai.com/gpt-5.5"
        plugin_id = "openai"
        capability_revision = "openai-gpt-5.5-responses-2026-08-23"
        maximum_input_bytes = 1_600_000
        temperature = None
        input_rate = 5_000_000
        output_rate = 30_000_000
        maximum_cost = 100_000
        max_tokens = 1_024
        reasoning_effort = None
        cost_source = "OpenAI GPT-5.5 model page, reviewed 2026-07-29"
    else:
        raise ValueError(
            f"live model {adapter_model_id!r} has no reviewed Backstitch "
            "capability and cost descriptor"
        )

    if kind == "local":
        reasoning_effort = None
        temperature_constraint = (
            f'{{ presence = "required", allowed_values = [{temperature}] }}'
        )
        seed_constraint = '{ presence = "required", minimum = 0, maximum = 2147483647 }'
    else:
        temperature_constraint = '{ presence = "forbidden" }'
        seed_constraint = '{ presence = "forbidden" }'
    reasoning_constraint = (
        '{ presence = "optional", allowed_values = ["max"] }'
        if reasoning_effort == "max"
        else '{ presence = "forbidden" }'
    )
    request_constraints = (
        "{ "
        'json_mode = { presence = "required", allowed_values = ["require"] }, '
        f"temperature = {temperature_constraint}, "
        f"seed = {seed_constraint}, "
        'max_tokens = { presence = "required", minimum = 1, maximum = 16384 }, '
        f"reasoning_effort = {reasoning_constraint} "
        "}"
    )
    lines = [
        'backend_id = "llm"',
        f"plugin_id = {json.dumps(plugin_id)}",
        'plugin_distribution_name = "llm"',
        f"model = {json.dumps(stable_model_id)}",
        f"adapter_model_id = {json.dumps(adapter_model_id)}",
        f"model_revision = {json.dumps(adapter_model_id)}",
        "capability_schema_version = 1",
        f"capability_revision = {json.dumps(capability_revision)}",
        f"request_constraints = {request_constraints}",
        f"maximum_input_bytes = {maximum_input_bytes}",
        f"max_tokens = {max_tokens}",
        f"maximum_estimated_cost_microusd = {maximum_cost}",
        f"input_cost_microusd_per_million_tokens = {input_rate}",
        f"output_cost_microusd_per_million_tokens = {output_rate}",
        "input_token_overhead = 256",
        f"cost_rate_source = {json.dumps(cost_source)}",
    ]
    if temperature is not None:
        lines.append(f"temperature = {temperature}")
        lines.append(f"seed = {LOCAL_INFERENCE_SEED}")
    if reasoning_effort is not None:
        lines.append(f"reasoning_effort = {json.dumps(reasoning_effort)}")
    if kind == "openai":
        lines.extend(
            (
                'required_kinds = ["section"]',
                "minimum_packets = 1",
                "maximum_packets = 1",
                "maximum_provider_calls = 1",
            )
        )
    return lines


def _select_live_packets(
    all_packets_text: str,
    count: int,
    *,
    require_semantic_owner: bool = True,
) -> list[dict[str, object]]:
    """Deterministically choose the bounded live subset from generated packets.

    There is no packet-filter subcommand and direct library analysis is
    forbidden, so the cloud filtering lives here. The local lane
    uses ``_select_local_live_packets`` and a curated invariant corpus instead.
    """

    candidates: list[tuple[int, dict[str, object]]] = []
    for index, raw in enumerate(all_packets_text.splitlines()):
        raw = raw.strip()
        if not raw:
            continue
        packet = json.loads(raw)
        if require_semantic_owner:
            requirement = packet.get("requirement")
            current_spec_path = (
                requirement.get("path")
                if isinstance(requirement, dict)
                else packet.get("spec_path")
            )
            if current_spec_path != LIVE_SPEC:
                continue
            evidence = packet.get("declared_evidence")
            owners = (
                evidence if isinstance(evidence, list) else packet.get("owners", [])
            )
            owner_paths = [str(owner.get("path", "")) for owner in owners]
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


def _write_live_contract_repo(root: Path, *, kind: str = "openai") -> Path:
    """Create a tiny aligned corpus for provider transport and schema probes."""

    (root / "docs/specs").mkdir(parents=True)
    (root / "docs/plans").mkdir(parents=True)
    (root / "pkg").mkdir()
    (root / "tests").mkdir()
    (root / "docs/plans/.keep").write_text("", encoding="utf-8")
    (root / ".backstitch.toml").write_text(
        '[profile]\nspec_roots = ["docs/specs"]\n'
        'plan_roots = ["docs/plans"]\ncode_roots = ["pkg", "tests"]\n'
        'test_roots = ["tests"]\n\n[analyze]\njson_mode = "require"\n'
        'cache_path = ".backstitch/semantic-cache"\n',
        encoding="utf-8",
    )
    if kind == "local":
        (root / "docs/specs/README.md").write_text(
            "# Live local contract\n", encoding="utf-8"
        )
        (root / "pkg/invariants.py").write_text(
            "def stable_one() -> int:\n"
            '    """Invariant: [INV.RES.1] stable_one keeps returning one."""\n'
            "    return 1\n\n"
            "def stable_two() -> int:\n"
            '    """Invariant: [INV.RES.2] stable_two keeps returning two."""\n'
            "    return 2\n",
            encoding="utf-8",
        )
        (root / "tests/test_invariants.py").write_text(
            "from pkg.invariants import stable_one, stable_two\n\n"
            "def test_stable_one() -> None:\n"
            '    """Tests-invariant: [INV.RES.1]"""\n'
            "    assert stable_one() == 1\n\n"
            "def test_stable_two() -> None:\n"
            '    """Tests-invariant: [INV.RES.2]"""\n'
            "    assert stable_two() == 2\n",
            encoding="utf-8",
        )
    else:
        (root / ".backstitch.toml").write_text(
            '[profile]\nspec_roots = ["docs/specs"]\n'
            'plan_roots = ["docs/plans"]\ncode_roots = ["pkg", "tests"]\n'
            'test_roots = ["tests"]\n\n[analyze]\njson_mode = "require"\n'
            'cache_path = ".backstitch/semantic-cache"\n',
            encoding="utf-8",
        )
        (root / "docs/specs/01-live.md").write_text(
            "# Live contract\n\n"
            "## Return one [LIVE-1]\n\n"
            "The live contract returns one.\n\n"
            "_Implementation mapping_:\n\n"
            "- `pkg/live.py::return_one`\n"
            "- `tests/test_live.py::test_return_one`\n",
            encoding="utf-8",
        )
        (root / "pkg/live.py").write_text(
            "def return_one() -> int:\n"
            '    """Spec: docs/specs/01-live.md [LIVE-1]"""\n'
            "    return 1\n",
            encoding="utf-8",
        )
        (root / "tests/test_live.py").write_text(
            "from pkg.live import return_one\n\n\n"
            "def test_return_one() -> None:\n"
            '    """Spec: docs/specs/01-live.md [LIVE-1]"""\n'
            "    assert return_one() == 1\n",
            encoding="utf-8",
        )
    return root


def _select_local_live_packets(
    all_packets_text: str,
) -> list[dict[str, object]]:
    """Select and validate the ordered invariant corpus owned by the local gate."""

    by_id: dict[str, list[dict[str, object]]] = {}
    for raw in all_packets_text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        packet = json.loads(raw)
        packet_id = str(packet.get("packet_id", ""))
        by_id.setdefault(packet_id, []).append(packet)

    selected: list[dict[str, object]] = []
    for packet_id in LOCAL_LIVE_PACKET_IDS:
        matches = by_id.get(packet_id, [])
        assert len(matches) == 1, (
            f"local live packet {packet_id!r} must occur exactly once; "
            f"found {len(matches)}"
        )
        packet = matches[0]
        assert packet.get("kind") == "invariant", (
            f"local live packet {packet_id!r} must have kind 'invariant'"
        )
        assert not packet.get("packet_warnings"), (
            f"local live packet {packet_id!r} must have no packet warnings"
        )
        declared = packet.get("declared_evidence")
        target_evidence = (
            _has_bounded_packet_evidence(declared, role="implementation")
            if isinstance(declared, list)
            else _has_bounded_packet_evidence(packet.get("targets"))
        )
        test_evidence = (
            _has_bounded_packet_evidence(declared, role="test")
            if isinstance(declared, list)
            else _has_bounded_packet_evidence(packet.get("binding_tests"))
        )
        assert target_evidence, (
            f"local live packet {packet_id!r} must have bounded target evidence"
        )
        assert test_evidence, (
            f"local live packet {packet_id!r} must have bounded binding-test evidence"
        )
        selected.append(packet)
    return selected


def _has_bounded_packet_evidence(items: object, *, role: str | None = None) -> bool:
    if not isinstance(items, list):
        return False
    return any(
        isinstance(item, dict)
        and (role is None or item.get("role") == role)
        and isinstance(item.get("path"), str)
        and bool(item["path"].strip())
        and isinstance(item.get("start_line"), int)
        and not isinstance(item["start_line"], bool)
        and item["start_line"] > 0
        and isinstance(item.get("snippet"), str)
        and bool(item["snippet"].strip())
        for item in items
    )


def _local_analyze_packet(payload: dict[str, object]) -> dict[str, object]:
    """Extract exactly one curated invariant packet from an analyze request."""

    messages = payload.get("messages")
    if not isinstance(messages, list):
        raise ValueError("local analyze request must contain one invariant packet")
    candidates: list[dict[str, object]] = []
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        _, separator, packet_text = content.rpartition("\n\n")
        if not separator:
            continue
        try:
            packet = json.loads(packet_text)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(packet, dict)
            and packet.get("kind") == "invariant"
            and packet.get("packet_id") in LOCAL_LIVE_PACKET_IDS
        ):
            candidates.append(packet)
    if len(candidates) != 1:
        raise ValueError("local analyze request must contain one invariant packet")
    return candidates[0]


def _local_evidence_schema(packet: dict[str, object]) -> list[dict[str, object]]:
    variants: list[dict[str, object]] = []
    for item_field in ("targets", "binding_tests"):
        items = packet.get(item_field)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            path = item.get("path")
            start_line = item.get("start_line")
            snippet = item.get("snippet")
            if (
                not isinstance(path, str)
                or not isinstance(start_line, int)
                or isinstance(start_line, bool)
                or not isinstance(snippet, str)
            ):
                continue
            end_line = lf_end_line(start_line, snippet)
            if end_line is None:
                continue
            variants.append(
                {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "const": path},
                        "line": {
                            "type": "integer",
                            "minimum": start_line,
                            "maximum": end_line,
                        },
                    },
                    "required": ["path", "line"],
                    "additionalProperties": False,
                }
            )
    return variants


def _local_analyze_response_format(
    payload: dict[str, object],
) -> dict[str, object]:
    """Build strict test-owned decoding bounds from the request's real packet."""

    packet = _local_analyze_packet(payload)
    if packet.get("packet_contract_version") == 3:
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "output",
                "schema": _semantic_response_schema(_local_analyze_prompt(payload)),
            },
        }
    evidence_variants = _local_evidence_schema(packet)
    if not evidence_variants:
        raise ValueError("local analyze invariant packet has no bounded evidence")
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "backstitch_invariant_analysis",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "packet_id": {
                        "type": "string",
                        "const": packet["packet_id"],
                    },
                    "classification": {
                        "type": "string",
                        "enum": list(INVARIANT_CLASSIFICATIONS),
                    },
                    "summary": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 48,
                    },
                    "rationale": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 72,
                    },
                    "evidence": {
                        "type": "array",
                        "maxItems": 1,
                        "items": {"anyOf": evidence_variants},
                    },
                },
                "required": [
                    "packet_id",
                    "classification",
                    "summary",
                    "rationale",
                    "evidence",
                ],
                "additionalProperties": False,
            },
        },
    }


def _local_analyze_prompt(payload: dict[str, object]) -> str:
    messages = payload.get("messages")
    prompts = (
        [
            message.get("content")
            for message in messages
            if isinstance(message, dict)
            and message.get("role") == "user"
            and isinstance(message.get("content"), str)
        ]
        if isinstance(messages, list)
        else []
    )
    if len(prompts) != 1 or not isinstance(prompts[0], str):
        raise ValueError("local analyze request must contain one user prompt")
    return prompts[0]


def _local_response_schema_matches(payload: dict[str, object]) -> bool:
    """Compare packet authority while ignoring provider-operational schema names."""

    expected = _local_analyze_response_format(payload)
    packet = _local_analyze_packet(payload)
    actual = payload.get("response_format")
    if packet.get("packet_contract_version") != 3:
        return actual == expected
    if not isinstance(actual, dict) or actual.get("type") != "json_schema":
        return False
    actual_json_schema = actual.get("json_schema")
    expected_json_schema = expected.get("json_schema")
    return (
        isinstance(actual_json_schema, dict)
        and isinstance(expected_json_schema, dict)
        and actual_json_schema.get("schema") == expected_json_schema.get("schema")
    )


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
        # issues streaming (SSE) requests. The proxy preserves streaming while
        # adding the local gate's request-level temperature and seed controls.
        "can_stream": False,
        "supports_schema": True,
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

from backstitch.analysis_llm import default_provider_adapter
from backstitch.semantic_identity import ProviderIdentity, RequestIdentity

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

adapter = default_provider_adapter(
    "backstitch-local",
    provider_identity=ProviderIdentity(
        "llm",
        "openai",
        "backstitch-local",
        "transport-preflight",
        "backstitch.llm",
        1,
        "live",
        "llm",
        "live",
    ),
    request_identity=RequestIdentity("require", 0.0, 42, 128),
    response_schema_builder=lambda _prompt: {{
        "type": "object",
        "additionalProperties": True,
    }},
)
out = adapter("Reply with JSON containing an OK value").raw_response
if not out.strip():
    raise SystemExit("transport preflight returned empty text")
print(out.strip())
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
        kind = packet["kind"]
        assert kind in {"section", "invariant"}
        prompt_bytes = len(
            model_request_bytes(
                packet,
                instruction_bytes=prompt_instruction_bytes(kind),
            )
        )
        if prompt_bytes > ceiling:
            too_large.append(f"{packet['packet_id']} ({prompt_bytes} bytes)")
    assert not too_large, (
        f"selected local-live packets exceed the prompt byte ceiling ({ceiling} "
        f"bytes = OLLAMA_CONTEXT_LENGTH * {LOCAL_ASSUMED_BYTES_PER_TOKEN} assumed "
        "bytes/token); curate smaller invariant packets or retune "
        f"OLLAMA_CONTEXT_LENGTH. Oversized: {too_large}"
    )


def _assert_analyze_hit_local_endpoint(
    proxy: _CountingProxy,
    *,
    expected_packet_ids: set[str],
    served_model: str,
) -> None:
    assert len(proxy.request_bodies) == len(expected_packet_ids), (
        "local analyze must send exactly one analyze request per selected packet: "
        f"{len(proxy.request_bodies)} requests for {len(expected_packet_ids)} packets"
    )
    request_packet_ids: list[str] = []
    wrong_models: list[object] = []
    wrong_controls: list[tuple[object, object]] = []
    wrong_stream_modes: list[tuple[object, object]] = []
    wrong_token_limits: list[object] = []
    wrong_response_formats: list[object] = []
    for body in proxy.request_bodies:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            pytest.fail(f"local analyze request body was not JSON: {exc}: {body}")
        if not isinstance(payload, dict):
            pytest.fail(f"local analyze request body was not an object: {payload!r}")
        if payload.get("model") != served_model:
            wrong_models.append(payload.get("model"))
        try:
            packet = _local_analyze_packet(payload)
        except ValueError as exc:
            pytest.fail(f"local analyze request did not contain one packet: {exc}")
        request_packet_ids.append(str(packet["packet_id"]))
        if not _local_response_schema_matches(payload):
            wrong_response_formats.append(payload.get("response_format"))
        controls = (payload.get("temperature"), payload.get("seed"))
        if controls != (LOCAL_INFERENCE_TEMPERATURE, LOCAL_INFERENCE_SEED):
            wrong_controls.append(controls)
        stream_mode = (payload.get("stream"), payload.get("stream_options"))
        if stream_mode != (True, {"include_usage": True}):
            wrong_stream_modes.append(stream_mode)
        if payload.get("max_tokens") != LOCAL_ANALYZE_MAX_TOKENS:
            wrong_token_limits.append(payload.get("max_tokens"))
    assert not wrong_models, (
        f"local analyze used unexpected model values: {wrong_models}; "
        f"expected {served_model!r}"
    )
    assert not wrong_controls, (
        f"local analyze used unexpected inference controls: {wrong_controls}; "
        f"expected temperature={LOCAL_INFERENCE_TEMPERATURE}, "
        f"seed={LOCAL_INFERENCE_SEED}"
    )
    assert not wrong_stream_modes, (
        "local analyze upstream requests did not preserve production streaming: "
        f"{wrong_stream_modes}"
    )
    assert not wrong_token_limits, (
        "local analyze upstream requests used unexpected token limits: "
        f"{wrong_token_limits}"
    )
    assert sorted(request_packet_ids) == sorted(expected_packet_ids), (
        "local analyze requests must contain each selected packet exactly once; "
        f"saw {request_packet_ids}"
    )
    assert not wrong_response_formats, (
        "local analyze requests used unexpected response schemas: "
        f"{wrong_response_formats}"
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

    def exercise(model_name: str) -> tuple[int, int]:
        return _exercise_live_llm_analysis_contract(
            tmp_path / model_name,
            monkeypatch,
            kind=kind,
            proxy=None,
            requested_model=model_name,
        )

    try:
        messages = _run_openai_qualifications(exercise)
    except _QualificationProcessFailure as exc:
        pytest.fail(str(exc), pytrace=False)
    for message in messages:
        print(message)


def _live_packet_generation_args(
    kind: str,
    scan_args: list[str],
    *,
    output: Path,
    report: Path,
) -> list[str]:
    """Build the report-compatible packet-generation command."""

    args = [
        "packets",
        *scan_args,
        "--kind",
        "all" if kind == "local" else "section",
        "--output",
        str(output),
    ]
    # Packet reports describe the complete generated packet set. The CLI
    # therefore permits ``--report`` only with ``--kind all``. The bounded
    # OpenAI lane does not need a packet report for its one section packet.
    if kind == "local":
        args.extend(("--report", str(report)))
    return args


def _exercise_live_llm_analysis_contract(  # noqa: C901 approved [SC-17.1] RUFF-SUP-145 exception
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    kind: str,
    proxy: _CountingProxy | None,
    requested_model: str | None = None,
) -> tuple[int, int]:
    local_config: _LocalConfig | None = None
    if kind == "local":
        assert proxy is not None
        local_config = _configure_local_llm(tmp_path, monkeypatch, proxy)
    live_root = _write_live_contract_repo(
        tmp_path / "live-contract-repo",
        kind=kind,
    )
    scan_args = [
        "--repo-root",
        str(live_root),
        "--code-root",
        "pkg",
        "--code-root",
        "tests",
        "--test-root",
        "tests",
    ]

    live_packets = tmp_path / "live-packets.jsonl"
    live_packet_report = tmp_path / "live-packet-report.json"
    selection_packets = (
        live_packets
        if kind == "local"
        else tmp_path / "qualification-preflight-packets.jsonl"
    )
    analysis = tmp_path / "analysis.jsonl"
    analysis_report = tmp_path / "analysis-report.json"
    replay_analysis = tmp_path / "replay-analysis.jsonl"
    replay_analysis_report = tmp_path / "replay-analysis-report.json"
    report = tmp_path / "report.json"

    # 1. Generate a small source-aligned contract corpus through the real CLI.
    packet_args = _live_packet_generation_args(
        kind,
        scan_args,
        output=selection_packets,
        report=live_packet_report,
    )
    gen = _run_cli(*packet_args)
    _assert_no_traceback(gen, "packets")
    assert gen.returncode == 0, gen.stderr
    all_text = selection_packets.read_text(encoding="utf-8")
    assert all_text.strip(), "packets produced empty output"

    # 2. Build the bounded live subset in-process and write it out.
    if kind == "local":
        subset = _select_local_live_packets(all_text)
    else:
        subset = _select_live_packets(
            all_text,
            1,
            require_semantic_owner=False,
        )
        assert subset, "live contract corpus produced no selectable section packet"
        assert {packet["kind"] for packet in subset} == {"section"}
    assert len(subset) <= MAX_LIVE_PACKETS
    if kind == "local":
        assert len(subset) >= 2, (
            "local live LLM testing needs at least two packets; with one packet "
            "a single error row is total failure, making leniency vacuous"
        )
        _assert_local_prompt_budget(subset)
    generated_packet_ids = {
        str(json.loads(line)["packet_id"])
        for line in all_text.splitlines()
        if line.strip()
    }
    expected_packet_ids = {str(packet["packet_id"]) for packet in subset}
    assert expected_packet_ids == generated_packet_ids
    if kind == "openai":
        assert len(subset) == 1
        request_byte_count = len(
            model_request_bytes(
                subset[0],
                instruction_bytes=prompt_instruction_bytes("section"),
            )
        )
        _assert_openai_qualification_bounds(
            provider_calls=2,
            estimated_cost_microusd=(
                _openai_qualification_estimated_cost_microusd(request_byte_count)
            ),
        )

    # Curated corpus validity is a precondition for provider activity. Resolve
    # and probe the model only after packet generation, selection, and bounds.
    live_model = _resolve_live_model(requested_model)
    if local_config is not None:
        _assert_model_listed(local_config)
        _assert_local_transport(local_config)
    live_config = live_root / ".backstitch.toml"
    descriptor_lines = _live_descriptor_lines(
        kind=kind,
        adapter_model_id=live_model,
    )
    live_config.write_text(
        live_config.read_text(encoding="utf-8").replace(
            "[analyze]\n",
            "[analyze]\n" + "\n".join(descriptor_lines) + "\n",
            1,
        ),
        encoding="utf-8",
    )
    if kind == "local":
        analyze_source_args = [
            "--packets",
            str(live_packets),
            "--packet-report",
            str(live_packet_report),
        ]
    else:
        analyze_source_args = [
            "--repo-root",
            str(live_root),
            "--packets-output",
            str(live_packets),
            "--packet-report-output",
            str(live_packet_report),
        ]

    # 3. Real provider call through the public analyze command.
    if proxy is not None:
        proxy.start_analyze_phase()
    ana = _run_cli(
        "analyze",
        *analyze_source_args,
        "--model",
        live_model,
        "--concurrency",
        "1",
        "--config",
        str(live_config),
        "--option",
        "analyze.cache_mode",
        "read-write",
        "--output",
        str(analysis),
        "--report",
        str(analysis_report),
        label="analyze",
        timeout=(
            LOCAL_ANALYZE_TIMEOUT_SECONDS
            if kind == "local"
            else OPENAI_QUALIFICATION_TIMEOUT_SECONDS
        ),
    )
    if proxy is not None:
        proxy.stop_analyze_phase()
    _assert_no_traceback(ana, "analyze")
    if not analysis_report.is_file():
        raise RuntimeError(
            json.dumps(
                {
                    "returncode": ana.returncode,
                    "stderr": ana.stderr[-2_000:],
                },
                sort_keys=True,
            )
        )
    if kind != "openai":
        assert ana.returncode == 0, ana.stderr
    analysis_report_data = json.loads(analysis_report.read_text(encoding="utf-8"))
    if kind == "openai" and (
        ana.returncode != 0
        or analysis_report_data["status"] != "complete"
        or analysis_report_data["problems"]
    ):
        raise RuntimeError(
            json.dumps(
                {
                    "stderr": ana.stderr[-2_000:],
                    "problems": analysis_report_data["problems"],
                },
                sort_keys=True,
            )
        )
    assert analysis_report_data["status"] == "complete"
    assert analysis_report_data["problems"] == []
    assert analysis_report_data["result_count"] == len(subset)
    if kind == "openai":
        assert analysis_report_data["provider_calls"] == 1
    if local_config is not None and proxy is not None:
        _assert_analyze_hit_local_endpoint(
            proxy,
            expected_packet_ids=expected_packet_ids,
            served_model=local_config.served_model,
        )

    # 4. The same immutable cache objects replay with zero provider calls.
    replay = _run_cli(
        "analyze",
        "--packets",
        str(live_packets),
        "--packet-report",
        str(live_packet_report),
        "--model",
        live_model,
        "--concurrency",
        "1",
        "--config",
        str(live_config),
        "--option",
        "analyze.cache_mode",
        "require",
        "--output",
        str(replay_analysis),
        "--report",
        str(replay_analysis_report),
        label="analyze require replay",
        timeout=LOCAL_ANALYZE_TIMEOUT_SECONDS if kind == "local" else None,
    )
    _assert_no_traceback(replay, "analyze require replay")
    assert replay.returncode == 0, replay.stderr
    replay_report_data = json.loads(replay_analysis_report.read_text(encoding="utf-8"))
    assert replay_report_data["provider_calls"] == 0
    assert replay_report_data["cache_misses"] == 0
    assert replay_analysis.read_bytes() == analysis.read_bytes()

    # 5. Deterministic report over the same source-aligned contract corpus.
    chk = _run_cli(
        "check",
        *scan_args,
        "--show-suppressions",
        "--format",
        "json",
        "--output",
        str(report),
    )
    _assert_no_traceback(chk, "check")
    assert chk.returncode == 0, chk.stderr

    # 6. Summary consumer accepts the model output.
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
        if kind == "openai" and errored:
            raise RuntimeError(
                "live analysis rows carry error fields: "
                + json.dumps(errored, sort_keys=True)[-2_000:]
            )
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
    return (
        int(analysis_report_data["provider_calls"]),
        int(analysis_report_data["estimated_cost_microusd"] or 0),
    )
