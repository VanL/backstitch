"""Environment doctor for the semantic-analysis lane.

Spec: docs/specs/02-backstitch-core.md [SC-14]
Plan: docs/plans/2026-07-06-local-model-catalog-and-doctor-plan.md

Diagnoses the `llm`/model/endpoint environment `analyze` depends on, as an
ordered list of named checks with statuses, details, and remedies. Checks
are provider-neutral: only the `llm` library's public surface and generic
HTTP are consulted, never provider identities — remedies point at the
local-model catalog doc, which is where provider names live ([CFG-9]).
`llm` is imported only inside check functions, never at module import
([SC-8]); the `check`/`packets` quarantine is proven by the subprocess
test in tests/test_cli.py.
"""

from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Surface 3xx as its raw HTTPError instead of following it ([SC-14])."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


# Output order is part of the [SC-14] contract for both formats.
CHECK_ORDER = (
    "llm-import",
    "model",
    "credential",
    "json-mode",
    "memory",
    "endpoint",
)

CATALOG_DOC = "docs/implementation/06-choosing-a-local-model.md"
PROBE_TIMEOUT_SECONDS = 10
# A /models list is small; anything past this is not the payload the check
# is for, and an unbounded read is exactly the malformed-server hazard the
# probe must contain ([SC-14] bounded timeout).
PROBE_MAX_BODY_BYTES = 1_000_000


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str  # "pass" | "fail" | "skip" — per-check subsets in [SC-14]
    detail: str
    remedy: str = ""


def run_doctor(
    model_arg: str | None,
    *,
    configured: str | None,
    probe: bool,
) -> list[CheckResult]:
    """Run every [SC-14] check in contract order and return the results.

    ``model_arg`` is the CLI ``--model`` value; ``configured`` is the
    config-file ``[analyze].model`` value. Precedence between them (and
    ``LLM_MODEL`` and the ``llm`` default) belongs to
    ``resolve_model_name`` — never re-implemented here.
    """

    results: list[CheckResult] = []

    llm_ok, llm_result = _check_llm_import()
    results.append(llm_result)

    model, model_result = _check_model(llm_ok, model_arg, configured)
    results.append(model_result)

    results.append(_check_credential(model))
    results.append(_check_json_mode(model))
    results.append(_check_memory())
    results.append(_check_endpoint(model, probe))

    assert [result.name for result in results] == list(CHECK_ORDER)
    # One-line details are part of the contract; model/config values are
    # user-controlled strings and may carry newlines.
    return [
        CheckResult(
            result.name,
            result.status,
            _one_line(result.detail),
            _one_line(result.remedy),
        )
        for result in results
    ]


def _one_line(text: str) -> str:
    return " ".join(text.split())


def doctor_exit_code(results: list[CheckResult]) -> int:
    """[SC-14]/[SC-5]: 0 iff no check failed; otherwise 2, never 1."""

    return 2 if any(result.status == "fail" for result in results) else 0


def render_text(results: list[CheckResult]) -> str:
    lines = []
    for result in results:
        line = f"{result.status:<4}  {result.name}: {result.detail}"
        if result.remedy:
            line += f"\n      remedy: {result.remedy}"
        lines.append(line)
    lines.append("ok" if doctor_exit_code(results) == 0 else "problems found (exit 2)")
    return "\n".join(lines) + "\n"


def render_json(results: list[CheckResult]) -> str:
    payload = {
        "checks": [asdict(result) for result in results],
        "ok": doctor_exit_code(results) == 0,
    }
    return json.dumps(payload, indent=2) + "\n"


def _check_llm_import() -> tuple[bool, CheckResult]:
    try:
        import llm  # noqa: F401
    except Exception as exc:  # noqa: BLE001 - any import failure is the finding
        return False, CheckResult(
            "llm-import",
            "fail",
            f"the llm package failed to import: {exc}",
            "install project dependencies (for example `uv sync --extra dev`)",
        )
    version = _installed_llm_version()
    return True, CheckResult("llm-import", "pass", f"llm {version} importable")


def _installed_llm_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("llm")
    except PackageNotFoundError:  # pragma: no cover - import worked, odd env
        return "unknown version"


def _check_model(
    llm_ok: bool,
    model_arg: str | None,
    configured: str | None,
) -> tuple[Any | None, CheckResult]:
    if not llm_ok:
        return None, CheckResult("model", "skip", "not evaluated: llm failed to import")

    import llm

    from backstitch.analysis_llm import resolve_model_name

    resolved = resolve_model_name(model_arg, configured=configured)
    source = _model_source(model_arg, configured)
    try:
        model = llm.get_model(resolved) if resolved else llm.get_model()
    except llm.UnknownModelError as exc:
        attempted = resolved if resolved else "the llm default model"
        message = exc.args[0] if exc.args else exc
        return None, CheckResult(
            "model",
            "fail",
            f"{attempted} (from {source}) did not resolve: {message}",
            "set --model, [analyze].model, or LLM_MODEL to a model that "
            "`llm models list` knows",
        )
    name = resolved if resolved else getattr(model, "model_id", "default")
    return model, CheckResult("model", "pass", f"resolved {name} (from {source})")


def _model_source(model_arg: str | None, configured: str | None) -> str:
    """Presentation of which [CFG-5] source won.

    Mirrors (never replaces) ``resolve_model_name``: the value always comes
    from that helper; this only labels the winning source for the report.
    """

    if model_arg is not None and model_arg.strip():
        return "--model"
    if os.environ.get("LLM_MODEL", "").strip():
        return "LLM_MODEL environment variable"
    if configured is not None and configured.strip():
        return "config [analyze].model"
    return "llm default model"


def _check_credential(model: Any | None) -> CheckResult:
    if model is None:
        return CheckResult("credential", "skip", "not evaluated: model unresolved")

    import llm

    needs_key = getattr(model, "needs_key", None)
    if not needs_key:
        return CheckResult(
            "credential",
            "pass",
            "keyless model (local api_base registration); no credential needed",
        )
    # Same discovery order the analyze call path uses: a key already
    # attached to the resolved model wins before stored/env lookup (llm 0.31
    # checks self.key first when executing a prompt).
    if getattr(model, "key", None):
        return CheckResult(
            "credential", "pass", "credential attached to the resolved model"
        )
    env_var = getattr(model, "key_env_var", None) or ""
    key = llm.get_key(key_alias=needs_key, env_var=env_var)
    if key:
        return CheckResult("credential", "pass", f"credential for {needs_key!r} found")
    hint = f" or set `{env_var}`" if env_var else ""
    return CheckResult(
        "credential",
        "fail",
        f"model requires key {needs_key!r} and no credential was found",
        f"store one with `llm keys set {needs_key}`{hint}",
    )


def _check_json_mode(model: Any | None) -> CheckResult:
    if model is None:
        return CheckResult("json-mode", "skip", "not evaluated: model unresolved")
    option_fields = getattr(getattr(model, "Options", None), "model_fields", {})
    if "json_object" in option_fields:
        return CheckResult(
            "json-mode",
            "pass",
            "model accepts a JSON-mode request; analyze will send it, but "
            "output is constrained only if the endpoint honors response_format "
            f"(server-dependent — see {CATALOG_DOC})",
        )
    return CheckResult(
        "json-mode",
        "pass",
        "constrained decoding not available for this model; analyze falls "
        "back to prompt-level JSON (more per-row error records likely)",
    )


def _check_memory() -> CheckResult:
    detected = _detected_memory_gib()
    memory = f"{detected:.0f} GiB" if detected is not None else "unknown"
    return CheckResult(
        "memory",
        "pass",
        f"detected physical memory: {memory}; for sizing a local model see "
        f"{CATALOG_DOC}",
    )


def _detected_memory_gib() -> float | None:
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
    except ValueError, OSError, AttributeError:
        return None
    if pages <= 0 or page_size <= 0:
        return None
    return pages * page_size / 2**30


def _safe_models_url(api_base: str) -> str | None:
    """Build ``<api_base>/models`` as ``scheme://host[:port]/path/models``.

    Returns None if ``api_base`` is malformed. ``api_base`` is user-controlled
    and may embed a credential as userinfo (``https://KEY@host``) or a query
    (``?api_key=``); both are stripped, which is what makes the probe the
    *unauthenticated* GET [SC-14] requires — no credential ever reaches the
    wire — and the same reduced string is what doctor displays, so the request
    target and the reported endpoint are one credential-free value. ``/models``
    is joined onto the parsed path (not the raw string) so a query in
    ``api_base`` cannot swallow it. A non-integer port (which ``parts.port``
    raises on) or a missing scheme/host returns None, so the caller reports an
    endpoint failure instead of raising past the check report.
    """

    import urllib.parse

    try:
        parts = urllib.parse.urlsplit(str(api_base))
        port = parts.port
    except ValueError:
        return None
    # http(s) only: the probe is a plain HTTP GET, and letting ftp:// or file://
    # through would hand urllib a non-HTTP handler for a "reachability" check.
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    # urlsplit strips the brackets from an IPv6 literal (``[::1]`` -> ``::1``);
    # a netloc must put them back or the colons read as a port separator.
    host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    if port is not None:
        host = f"{host}:{port}"
    path = parts.path.rstrip("/") + "/models"
    return urllib.parse.urlunsplit((parts.scheme, host, path, "", ""))


def _response_socket(response: Any) -> Any:
    """Best-effort handle on the response's underlying socket.

    urllib exposes no public accessor, so ``_read_bounded`` shrinks this
    socket's timeout to the remaining budget before each read to hard-bound
    wall-clock. If the internal layout differs and this returns None, the
    per-iteration deadline still bounds total time to at most one socket
    timeout of slack rather than the (former) unbounded buffer-fill.
    """

    fp = getattr(response, "fp", None)
    raw = getattr(fp, "raw", None)
    return getattr(raw, "_sock", None)


def _read_bounded(
    response: Any, max_bytes: int, budget_seconds: float, time_module: Any
) -> tuple[bytes, bool]:
    """Read up to ``max_bytes`` within ``budget_seconds`` of wall-clock.

    Returns ``(body, overrun)``: ``overrun`` is True when the server sent more
    than the cap or held a read past the budget. Two mechanisms bound time:
    ``read1`` (not ``read``) returns after a single recv rather than looping to
    fill the buffer, and the socket timeout is shrunk to the remaining budget
    before each read so a single slow read cannot exceed the deadline (a fire
    raises ``TimeoutError``, reported as ``overrun``).
    """

    deadline = time_module.monotonic() + budget_seconds
    sock = _response_socket(response)
    chunks: list[bytes] = []
    total = 0
    while True:
        remaining = deadline - time_module.monotonic()
        if remaining <= 0:
            return b"", True
        if sock is not None:
            try:
                sock.settimeout(remaining)
            except OSError:  # pragma: no cover - socket already torn down
                pass
        try:
            chunk = response.read1(65536)
        except TimeoutError:
            return b"", True
        if not chunk:
            return b"".join(chunks), False
        total += len(chunk)
        if total > max_bytes:
            return b"", True
        chunks.append(chunk)


def _check_endpoint(model: Any | None, probe: bool) -> CheckResult:
    if not probe:
        return CheckResult(
            "endpoint", "skip", "not evaluated: run with --probe to test"
        )
    if model is None:
        return CheckResult("endpoint", "skip", "not evaluated: model unresolved")
    api_base = getattr(model, "api_base", None)
    if not api_base:
        return CheckResult(
            "endpoint",
            "skip",
            "not evaluated: resolved model has no api_base endpoint",
        )

    import http.client
    import time
    import urllib.error

    # The probed url is stripped of userinfo/query so no credential in
    # api_base ever reaches the wire ([SC-14] unauthenticated GET); the same
    # credential-free string is what every detail shows. A malformed api_base
    # (bad scheme/host or a non-integer port) is an endpoint failure, never an
    # uncaught traceback that would drop the ordered check report.
    url = _safe_models_url(api_base)
    if url is None:
        return CheckResult(
            "endpoint",
            "fail",
            "resolved model api_base is not a valid http(s) URL",
            "fix the model registration's api_base to scheme://host[:port]/path",
        )
    # [SC-14]: any status other than 200/401/403 is a failure — a silently
    # followed 3xx would both hide the status and probe a different URL, so
    # redirects are surfaced as their raw status instead of followed.
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        with opener.open(request, timeout=PROBE_TIMEOUT_SECONDS) as response:
            body, overrun = _read_bounded(
                response, PROBE_MAX_BODY_BYTES, PROBE_TIMEOUT_SECONDS, time
            )
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return CheckResult(
                "endpoint",
                "pass",
                f"{url} reachable; model list is authentication-gated "
                f"(HTTP {exc.code}), membership not verified",
            )
        return CheckResult(
            "endpoint",
            "fail",
            f"{url} answered HTTP {exc.code}",
            "confirm the endpoint serves a standard model-list route at /models",
        )
    except (
        urllib.error.URLError,
        TimeoutError,
        OSError,
        ValueError,
        http.client.HTTPException,
    ) as exc:
        return CheckResult(
            "endpoint",
            "fail",
            f"{url} is unreachable: {_one_line(str(exc))}",
            "start the local model server (or fix the model registration's "
            "api_base; see the README local-lane section), then re-run "
            "with --probe",
        )
    if overrun:
        return CheckResult(
            "endpoint",
            "fail",
            f"{url} did not deliver a bounded model list (over "
            f"{PROBE_MAX_BODY_BYTES} bytes or past the "
            f"{PROBE_TIMEOUT_SECONDS} s budget)",
            "confirm the endpoint serves a standard model-list route at /models",
        )

    try:
        payload = json.loads(body)
    except ValueError:
        payload = None
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return CheckResult(
            "endpoint",
            "fail",
            f"{url} answered 200 but not with a standard model-list payload",
            "confirm the endpoint serves a standard model-list route at /models",
        )

    served = getattr(model, "model_name", None) or getattr(model, "model_id", "")
    ids = [
        str(item.get("id"))
        for item in payload["data"]
        if isinstance(item, dict) and item.get("id") is not None
    ]
    if served in ids:
        return CheckResult("endpoint", "pass", f"{url} reachable; {served!r} is served")
    return CheckResult(
        "endpoint",
        "fail",
        f"{url} reachable but {served!r} is not in the served model list: {ids}",
        "pull or load the model on the server, or point model_name at one "
        "of the served ids",
    )
