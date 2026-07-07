"""Contract tests for `backstitch doctor` ([SC-14]).

Spec: docs/specs/02-backstitch-core.md [SC-14], [SC-5], [SC-8]

The llm model boundary is the one acceptable fake (monkeypatched
`llm.get_model`/`llm.get_key`); HTTP reachability is proven against real
loopback `http.server` instances, never by mocking urllib.
"""

from __future__ import annotations

import http.server
import json
import re
import socket
import subprocess
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

import pytest

from backstitch.doctor import (
    CHECK_ORDER,
    CheckResult,
    doctor_exit_code,
    render_json,
    render_text,
    run_doctor,
)

ROOT = Path(__file__).resolve().parents[1]


class _Response:
    def text(self) -> str:  # pragma: no cover - never called by doctor
        raise AssertionError("doctor must never generate")


def _fake_model(
    *,
    needs_key: str | None = None,
    key_env_var: str | None = None,
    api_base: str | None = None,
    json_object: bool = True,
    model_name: str | None = None,
    model_id: str = "fake-model",
) -> object:
    class Options:
        model_fields = {"json_object": object()} if json_object else {}

    model = type(
        "FakeModel",
        (),
        {
            "Options": Options,
            "needs_key": needs_key,
            "key_env_var": key_env_var,
            "model_id": model_id,
            "prompt": lambda self, *a, **k: _Response(),
        },
    )()
    if api_base is not None:
        model.api_base = api_base
    if model_name is not None:
        model.model_name = model_name
    return model


def _install_fake_llm(
    monkeypatch: pytest.MonkeyPatch,
    model: object | None,
    *,
    key: str | None = None,
) -> None:
    import llm

    def fake_get_model(*args: object) -> object:
        if model is None:
            raise llm.UnknownModelError("unknown model: probe")
        return model

    monkeypatch.setattr(llm, "get_model", fake_get_model)
    monkeypatch.setattr(llm, "get_key", lambda **kwargs: key)


def _by_name(results: list[CheckResult]) -> dict[str, CheckResult]:
    return {result.name: result for result in results}


@contextmanager
def _models_server(payload: object, status: int = 200) -> Iterator[str]:
    """Loopback server answering GET /v1/models with `payload` at `status`."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib hook name
            # The probe must hit exactly <api_base>/models and never carry
            # a credential.
            assert self.path == "/v1/models", self.path
            assert self.headers.get("Authorization") is None
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


# --- static checks ---------------------------------------------------------


def test_all_pass_for_keyless_api_base_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_llm(monkeypatch, _fake_model(api_base="http://127.0.0.1:9/v1"))
    results = run_doctor("some-model", configured=None, probe=False)
    by_name = _by_name(results)
    assert [result.name for result in results] == list(CHECK_ORDER)
    assert by_name["llm-import"].status == "pass"
    assert by_name["model"].status == "pass"
    assert "--model" in by_name["model"].detail
    assert by_name["credential"].status == "pass"
    assert "keyless" in by_name["credential"].detail
    assert by_name["json-mode"].status == "pass"
    # Honest wording: the model accepts the request, but the detail must not
    # promise enforcement (server-dependent — Ollama honors it, LM Studio
    # ignores it), and it points at the catalog for the specifics.
    detail = by_name["json-mode"].detail
    assert "analyze will send it" in detail
    assert "endpoint honors" in detail
    assert "06-choosing-a-local-model.md" in detail
    assert by_name["memory"].status == "pass"
    assert "06-choosing-a-local-model.md" in by_name["memory"].detail
    assert by_name["endpoint"].status == "skip"
    assert doctor_exit_code(results) == 0


def test_unresolvable_model_fails_and_dependents_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_llm(monkeypatch, None)
    results = run_doctor("nope", configured=None, probe=True)
    by_name = _by_name(results)
    assert by_name["model"].status == "fail"
    assert "nope" in by_name["model"].detail
    assert by_name["model"].remedy
    assert by_name["credential"].status == "skip"
    assert by_name["json-mode"].status == "skip"
    assert by_name["endpoint"].status == "skip"
    assert doctor_exit_code(results) == 2


def test_missing_credential_fails_with_remedy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_llm(
        monkeypatch,
        _fake_model(needs_key="provider-alias", key_env_var="PROVIDER_KEY"),
        key=None,
    )
    results = run_doctor(None, configured="configured-model", probe=False)
    by_name = _by_name(results)
    assert by_name["credential"].status == "fail"
    assert "provider-alias" in by_name["credential"].detail
    assert "llm keys set" in by_name["credential"].remedy
    assert doctor_exit_code(results) == 2


def test_present_credential_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_llm(monkeypatch, _fake_model(needs_key="provider-alias"), key="sk-x")
    results = run_doctor("m", configured=None, probe=False)
    assert _by_name(results)["credential"].status == "pass"


def test_credential_attached_to_model_passes_before_stored_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # llm 0.31's execution path honors a key already attached to the model
    # before stored/env lookup — doctor must match analyze's discovery, so
    # an attached key passes even when get_key finds nothing.
    model = cast(Any, _fake_model(needs_key="provider-alias"))
    model.key = "attached-key"
    _install_fake_llm(monkeypatch, model, key=None)
    results = run_doctor("m", configured=None, probe=False)
    check = _by_name(results)["credential"]
    assert check.status == "pass"
    assert "attached" in check.detail


def test_json_mode_absence_is_reported_not_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_llm(monkeypatch, _fake_model(json_object=False))
    results = run_doctor("m", configured=None, probe=False)
    check = _by_name(results)["json-mode"]
    assert check.status == "pass"
    assert "not available" in check.detail
    assert doctor_exit_code(results) == 0


def test_model_source_reports_env_config_and_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_llm(monkeypatch, _fake_model())
    monkeypatch.setenv("LLM_MODEL", "env-model")
    assert (
        "LLM_MODEL"
        in _by_name(run_doctor(None, configured="c", probe=False))["model"].detail
    )
    monkeypatch.delenv("LLM_MODEL")
    assert (
        "config"
        in _by_name(run_doctor(None, configured="c", probe=False))["model"].detail
    )
    assert (
        "default"
        in _by_name(run_doctor(None, configured=None, probe=False))["model"].detail
    )


# --- probe (endpoint) checks ----------------------------------------------


def test_probe_passes_when_served_model_listed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _models_server({"data": [{"id": "served-name"}]}) as endpoint:
        _install_fake_llm(
            monkeypatch,
            _fake_model(api_base=endpoint, model_name="served-name"),
        )
        results = run_doctor("alias", configured=None, probe=True)
    check = _by_name(results)["endpoint"]
    assert check.status == "pass"
    assert doctor_exit_code(results) == 0


def test_probe_fails_when_model_absent_and_names_seen_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _models_server({"data": [{"id": "other-a"}, {"id": "other-b"}]}) as endpoint:
        _install_fake_llm(
            monkeypatch,
            _fake_model(api_base=endpoint, model_name="served-name"),
        )
        results = run_doctor("alias", configured=None, probe=True)
    check = _by_name(results)["endpoint"]
    assert check.status == "fail"
    assert "other-a" in check.detail
    assert check.remedy


def test_probe_membership_falls_back_to_model_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _models_server({"data": [{"id": "the-id"}]}) as endpoint:
        _install_fake_llm(
            monkeypatch, _fake_model(api_base=endpoint, model_id="the-id")
        )
        results = run_doctor("alias", configured=None, probe=True)
    assert _by_name(results)["endpoint"].status == "pass"


def test_probe_auth_challenge_counts_as_reachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _models_server({"error": "auth"}, status=401) as endpoint:
        _install_fake_llm(monkeypatch, _fake_model(api_base=endpoint))
        results = run_doctor("alias", configured=None, probe=True)
    check = _by_name(results)["endpoint"]
    assert check.status == "pass"
    assert "authentication" in check.detail
    assert doctor_exit_code(results) == 0


def test_probe_connection_refused_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An accept-and-close listener: connection succeeds, response never comes.
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
        _install_fake_llm(
            monkeypatch, _fake_model(api_base=f"http://127.0.0.1:{port}/v1")
        )
        results = run_doctor("alias", configured=None, probe=True)
    finally:
        stop.set()
        broken.close()
        closer.join(timeout=5)
    assert _by_name(results)["endpoint"].status == "fail"
    assert doctor_exit_code(results) == 2


def test_probe_other_http_error_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    with _models_server({"error": "gone"}, status=500) as endpoint:
        _install_fake_llm(monkeypatch, _fake_model(api_base=endpoint))
        results = run_doctor("alias", configured=None, probe=True)
    assert _by_name(results)["endpoint"].status == "fail"


def test_probe_skips_without_api_base(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_llm(monkeypatch, _fake_model())
    results = run_doctor("m", configured=None, probe=True)
    assert _by_name(results)["endpoint"].status == "skip"


def test_probe_auth_forbidden_also_counts_as_reachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _models_server({"error": "forbidden"}, status=403) as endpoint:
        _install_fake_llm(monkeypatch, _fake_model(api_base=endpoint))
        results = run_doctor("alias", configured=None, probe=True)
    assert _by_name(results)["endpoint"].status == "pass"


def test_probe_does_not_follow_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # [SC-14]: any status besides 200/401/403 fails — a silently followed
    # 3xx would hide the status and probe a different URL.
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib hook name
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:9/elsewhere")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        endpoint = f"http://127.0.0.1:{server.server_port}/v1"
        _install_fake_llm(monkeypatch, _fake_model(api_base=endpoint))
        results = run_doctor("alias", configured=None, probe=True)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    check = _by_name(results)["endpoint"]
    assert check.status == "fail"
    assert "302" in check.detail


def test_probe_rejects_oversized_model_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backstitch.doctor import PROBE_MAX_BODY_BYTES

    huge = {"data": [], "pad": "x" * (PROBE_MAX_BODY_BYTES + 4096)}
    with _models_server(huge) as endpoint:
        _install_fake_llm(monkeypatch, _fake_model(api_base=endpoint))
        results = run_doctor("alias", configured=None, probe=True)
    check = _by_name(results)["endpoint"]
    assert check.status == "fail"
    assert "bounded" in check.detail


def test_probe_malformed_api_base_fails_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A malformed api_base makes urllib.request.Request raise ValueError; it
    # must surface as an endpoint failure, never an uncaught traceback that
    # would drop the [SC-14] check report.
    _install_fake_llm(monkeypatch, _fake_model(api_base="http://[unclosed"))
    results = run_doctor("alias", configured=None, probe=True)
    check = _by_name(results)["endpoint"]
    assert check.status == "fail"
    assert [r.name for r in results] == list(CHECK_ORDER)


def test_probe_truncated_body_fails_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A server that promises more bytes than it sends raises
    # http.client.IncompleteRead during the read; the broadened except must
    # turn that into an endpoint failure, not a doctor traceback.
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib hook name
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "10000")
            self.end_headers()
            self.wfile.write(b'{"data"')  # far short of the promised length
            self.wfile.flush()
            self.close_connection = True

        def log_message(self, format: str, *args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        endpoint = f"http://127.0.0.1:{server.server_port}/v1"
        _install_fake_llm(monkeypatch, _fake_model(api_base=endpoint))
        results = run_doctor("alias", configured=None, probe=True)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert _by_name(results)["endpoint"].status == "fail"


def test_safe_models_url_strips_credentials_and_rejects_malformed() -> None:
    # api_base may embed a token as userinfo or a query param; the probed
    # (and displayed) url must carry neither, so no credential reaches the
    # wire. /models joins onto the path (not the raw string) so a query cannot
    # swallow it. A malformed api_base (bad port, missing scheme/host) returns
    # None so the caller reports a failure, not a crash.
    from backstitch.doctor import _safe_models_url

    assert (
        _safe_models_url("https://s3cr3t@host:1234/v1?api_key=s3cr3t")
        == "https://host:1234/v1/models"
    )
    assert _safe_models_url("http://127.0.0.1:11434/v1") == (
        "http://127.0.0.1:11434/v1/models"
    )
    assert _safe_models_url("http://127.0.0.1:11434/v1/") == (
        "http://127.0.0.1:11434/v1/models"
    )
    # IPv6 loopback (a valid api_base per the lane's loopback allowlist) must
    # keep its brackets or the colons read as a port separator.
    assert _safe_models_url("http://[::1]:1234/v1") == "http://[::1]:1234/v1/models"
    assert _safe_models_url("http://[::1]/v1") == "http://[::1]/v1/models"
    assert _safe_models_url("http://127.0.0.1:notaport/v1") is None
    assert _safe_models_url("not-a-url") is None
    # http(s) only — a non-HTTP scheme is not a reachability probe target.
    assert _safe_models_url("ftp://127.0.0.1/v1") is None
    assert _safe_models_url("file:///etc/passwd") is None


def test_probe_never_sends_or_echoes_api_base_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A token embedded in api_base (userinfo and query) must reach neither
    # the wire nor the output. The loopback handler asserts the request path
    # is exactly /v1/models with no Authorization header, so a leaked query
    # or userinfo-as-auth fails the probe there; the output check proves no
    # echo. The probe still succeeds because the sanitized url resolves to
    # the same loopback server.
    with _models_server({"data": [{"id": "served-name"}]}) as endpoint:
        scheme, rest = endpoint.split("://", 1)
        creds = f"{scheme}://s3cr3t-token@{rest}?api_key=s3cr3t-token"
        _install_fake_llm(
            monkeypatch, _fake_model(api_base=creds, model_name="served-name")
        )
        results = run_doctor("alias", configured=None, probe=True)
    assert _by_name(results)["endpoint"].status == "pass", _by_name(results)["endpoint"]
    blob = json.dumps([asdict(r) for r in results])
    assert "s3cr3t-token" not in blob, blob


def test_read_bounded_stops_at_wall_clock_deadline() -> None:
    # A server that never sends EOF must not hold the read past the budget:
    # the per-iteration deadline check bounds total wall-clock (read1 returns
    # after one recv rather than looping to fill the buffer).
    from backstitch.doctor import _read_bounded

    class _FakeClock:
        def __init__(self, times: list[float]) -> None:
            self._times = iter(times)

        def monotonic(self) -> float:
            return next(self._times)

    class _DripResponse:
        def read1(self, _n: int) -> bytes:
            return b"x"  # always more data, never EOF

        def read(self, _n: int) -> bytes:  # guards against a read1->read regress
            raise AssertionError("_read_bounded must use read1, not read")

    # deadline = 0.0 + 1.0; two reads under it, then the clock passes it.
    clock = _FakeClock([0.0, 0.2, 0.4, 2.0])
    body, overrun = _read_bounded(
        _DripResponse(), max_bytes=10_000, budget_seconds=1.0, time_module=clock
    )
    assert overrun is True
    assert body == b""


def test_probe_slow_server_is_bounded_by_the_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A server that promises a large body then stalls must not hang the probe:
    # the read is bounded by the (shrunk) budget and reported as a failure well
    # before the server would have finished.
    import time as _time

    monkeypatch.setattr("backstitch.doctor.PROBE_TIMEOUT_SECONDS", 1)

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib hook name
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "1000000")
            self.end_headers()
            self.wfile.write(b'{"data": [')
            self.wfile.flush()
            _time.sleep(10)  # never deliver the rest of the promised body

        def log_message(self, format: str, *args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        endpoint = f"http://127.0.0.1:{server.server_port}/v1"
        _install_fake_llm(monkeypatch, _fake_model(api_base=endpoint))
        start = _time.monotonic()
        results = run_doctor("alias", configured=None, probe=True)
        elapsed = _time.monotonic() - start
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert _by_name(results)["endpoint"].status == "fail"
    assert elapsed < 6, f"probe was not bounded by the budget: {elapsed:.1f}s"


def test_response_socket_resolves_on_a_real_urllib_response() -> None:
    # The hard wall-clock bound depends on reaching the response's socket to
    # shrink its per-read timeout. If a future Python changes the internal
    # layout so _response_socket returns None, the bound silently degrades —
    # this fails loudly instead, flagging that _response_socket needs updating.
    import socket as _socket
    import urllib.request

    from backstitch.doctor import _response_socket

    with _models_server({"data": []}) as endpoint:
        with urllib.request.urlopen(endpoint + "/models", timeout=5) as response:
            assert isinstance(_response_socket(response), _socket.socket)


def test_probe_bad_port_fails_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A non-integer port makes urlsplit().port raise ValueError; it must be
    # an endpoint failure, not an uncaught traceback dropping the report.
    _install_fake_llm(monkeypatch, _fake_model(api_base="http://127.0.0.1:notaport/v1"))
    results = run_doctor("alias", configured=None, probe=True)
    assert _by_name(results)["endpoint"].status == "fail"
    assert [r.name for r in results] == list(CHECK_ORDER)


def test_llm_import_failure_fails_and_dependents_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A None entry in sys.modules makes `import llm` raise ImportError —
    # the hermetic stand-in for a broken install.
    monkeypatch.setitem(sys.modules, "llm", None)
    results = run_doctor("m", configured=None, probe=False)
    by_name = _by_name(results)
    assert by_name["llm-import"].status == "fail"
    assert by_name["llm-import"].remedy
    assert by_name["model"].status == "skip"
    assert by_name["credential"].status == "skip"
    assert doctor_exit_code(results) == 2


def test_details_are_single_line_even_with_hostile_model_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_llm(monkeypatch, None)
    results = run_doctor("bad\nname\twith spaces", configured=None, probe=False)
    for result in results:
        assert "\n" not in result.detail and "\n" not in result.remedy
    assert "bad name" in _by_name(results)["model"].detail


# --- rendering and exit contract -------------------------------------------


def test_json_rendering_shape() -> None:
    results = [
        CheckResult("llm-import", "pass", "llm 0.31", ""),
        CheckResult("model", "fail", "bad", "set --model"),
    ]
    payload = json.loads(render_json(results))
    assert payload == {
        "checks": [
            {
                "name": "llm-import",
                "status": "pass",
                "detail": "llm 0.31",
                "remedy": "",
            },
            {
                "name": "model",
                "status": "fail",
                "detail": "bad",
                "remedy": "set --model",
            },
        ],
        "ok": False,
    }


def test_text_rendering_includes_status_and_remedy() -> None:
    text = render_text([CheckResult("model", "fail", "bad name", "use --model")])
    assert "model" in text
    assert "fail" in text
    assert "use --model" in text


def test_exit_code_ignores_skips() -> None:
    results = [
        CheckResult("llm-import", "pass", "", ""),
        CheckResult("endpoint", "skip", "", ""),
    ]
    assert doctor_exit_code(results) == 0


# --- CLI integration --------------------------------------------------------


def test_cli_doctor_json_exits_zero_on_healthy_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Real CLI path with the fake registered through LLM_USER_PATH — the
    # registration path is what makes an api_base model keyless (direct
    # construction keeps a key requirement; verified against llm 0.31).
    llm_home = tmp_path / "llm-home"
    llm_home.mkdir()
    (llm_home / "extra-openai-models.yaml").write_text(
        json.dumps(
            [
                {
                    "model_id": "doctor-test-local",
                    "model_name": "served",
                    "api_base": "http://127.0.0.1:9/v1",
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LLM_USER_PATH", str(llm_home))
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "backstitch",
            "doctor",
            "--no-config",
            "--model",
            "doctor-test-local",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    )
    assert "Traceback" not in result.stderr
    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert [check["name"] for check in payload["checks"]] == list(CHECK_ORDER)


def test_cli_doctor_exits_two_without_traceback_on_unknown_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_USER_PATH", str(tmp_path / "empty-llm-home"))
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "backstitch",
            "doctor",
            "--no-config",
            "--model",
            "definitely-not-a-registered-model",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    )
    assert "Traceback" not in result.stderr
    assert result.returncode == 2, result.stdout
    assert "fail" in result.stdout


def test_cli_doctor_rejects_config_and_no_config_together() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "backstitch",
            "doctor",
            "--no-config",
            "--config",
            "x.toml",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    )
    assert result.returncode == 2
    assert "Traceback" not in result.stderr


# --- boundaries -------------------------------------------------------------


def test_doctor_module_has_no_top_level_llm_import_and_no_provider_names() -> None:
    source = (ROOT / "backstitch" / "doctor.py").read_text(encoding="utf-8")
    for line in source.splitlines():
        # Column-0 imports are module-level; indented ones are the intended
        # function-level lazy imports ([SC-8]).
        assert not re.match(r"^(import llm\b|from llm\b)", line), (
            "llm must be imported only inside doctor execution/check "
            f"functions, found module-level import: {line!r}"
        )
    # Provider neutrality [CFG-9]: no provider identities in runtime code,
    # including remedy strings — no carve-outs (the plan bans them
    # outright; even llm's `extra-openai-models.yaml` filename stays out of
    # runtime strings, with remedies pointing at README/docs instead).
    lowered = source.lower()
    for provider in ("ollama", "openai", "anthropic", "lm studio", "lmstudio"):
        assert provider not in lowered, f"provider name {provider!r} in doctor.py"


def test_doctor_is_not_in_the_llm_quarantine_command_list() -> None:
    # The [SC-10] quarantine subprocess test covers exactly the deterministic
    # commands; doctor is an llm-touching command and must stay out of it.
    source = (ROOT / "tests" / "test_cli.py").read_text(encoding="utf-8")
    quarantine = next(
        (
            segment
            for segment in source.split("def ")
            if "not in sys.modules" in segment
        ),
        "",
    )
    assert quarantine, "quarantine test not found in tests/test_cli.py"
    assert '"doctor"' not in quarantine and "'doctor'" not in quarantine
