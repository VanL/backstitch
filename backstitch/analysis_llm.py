"""Semantic analysis over packets through the ``llm`` Python API.

Spec: docs/specs/02-backstitch-core.md [SC-7], [SC-13]
Spec: docs/specs/05-backstitch-invariants.md [INV-5], [INV-6], [INV-7]
Spec: docs/specs/06-semantic-gates.md [SEM-3]

The adapter boundary exists so tests prove prompt construction, iteration,
parsing, and malformed-output handling with fakes; only the default adapter
touches ``llm`` and real models. Findings are advisory [SC-7].
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast

from backstitch.canonical import canonical_json_bytes, lf_end_line
from backstitch.semantic_cache import (
    ProviderAdapter,
    ProviderCallResult,
    SemanticProvenance,
)
from backstitch.semantic_evidence import (
    SemanticResultError,
    normalize_model_result,
)
from backstitch.semantic_identity import (
    InferenceIdentity,
    ProviderIdentity,
    RequestIdentity,
    build_inference_identity,
)
from backstitch.semantic_packets import model_request_bytes

ModelAdapter = Callable[[str], str]

_CONTROLLED_PROVIDER = ProviderIdentity(
    backend_id="controlled",
    plugin_id="backstitch-tests",
    model_id="controlled-adapter",
    model_revision="1",
    adapter_id="backstitch.controlled",
    adapter_version=1,
    llm_distribution_version="controlled",
    plugin_distribution_name="controlled",
    plugin_distribution_version="controlled",
)
_CONTROLLED_REQUEST = RequestIdentity(
    json_mode="require",
    temperature=0.0,
    seed=0,
    max_tokens=512,
)


def _install_completion_limit_shim(
    model: object,
    provider_identity: ProviderIdentity,
) -> None:
    """Translate Backstitch's logical output cap to the provider wire name."""

    model_id = provider_identity.model_id.lower()
    is_openai_adapter = provider_identity.plugin_id == "openai" or (
        type(model).__module__ == "llm.default_plugins.openai_models"
    )
    requires_completion_tokens = is_openai_adapter and (
        model_id.startswith(("gpt-5", "o1", "o3", "o4"))
    )
    if not requires_completion_tokens:
        return
    original = getattr(model, "build_kwargs", None)
    if not callable(original):
        raise ValueError("resolved OpenAI model cannot enforce max_completion_tokens")

    def build_kwargs(prompt: object, stream: bool) -> dict[str, object]:
        kwargs = dict(original(prompt, stream))
        if "max_tokens" in kwargs:
            if "max_completion_tokens" in kwargs:
                raise ValueError("resolved model emitted two completion token limits")
            kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
        return kwargs

    try:
        cast(Any, model).build_kwargs = build_kwargs
    except (AttributeError, TypeError) as exc:
        raise ValueError(
            "resolved OpenAI model cannot install max_completion_tokens support"
        ) from exc


def _resolved_model_adapter_parts(
    model_name: str | None = None,
    *,
    request_identity: RequestIdentity | None = None,
) -> tuple[Any, Callable[..., Any], str, dict[str, object]]:
    """Resolve one llm model and its exact supported request options."""

    import llm

    model = llm.get_model(model_name) if model_name else llm.get_model()
    model_prompt = cast(Any, model).prompt
    option_fields = getattr(getattr(model, "Options", None), "model_fields", {})
    if request_identity is None:
        json_mode = "require" if "json_object" in option_fields else "off"
        request_options: dict[str, object] = {}
    else:
        json_mode = request_identity.json_mode
        required_options = {"temperature", "seed", "max_tokens"}
        if json_mode == "require":
            required_options.add("json_object")
        missing_options = sorted(required_options - set(option_fields))
        if missing_options:
            raise ValueError(
                "resolved model does not support request options: "
                + ", ".join(missing_options)
            )
        request_options = {
            "temperature": request_identity.temperature,
            "seed": request_identity.seed,
            "max_tokens": request_identity.max_tokens,
        }
    return model, model_prompt, json_mode, request_options


def default_adapter(
    model_name: str | None = None,
    *,
    request_identity: RequestIdentity | None = None,
) -> ModelAdapter:
    """Build the legacy string-only adapter for an ``llm`` model.

    With no name, ``llm``'s configured default model is used (whatever
    ``llm models default`` reports).

    When the resolved model's ``Options`` declares ``json_object`` (llm's
    OpenAI-compatible models, cloud and ``api_base``-registered alike), the
    adapter requests provider-enforced JSON output: constrained decoding
    makes syntactically invalid output impossible on servers that honor
    ``response_format``, which measurably dominates small-model failure
    rates. The gate is a capability check, never a provider name, and models
    without the option get the unchanged call
    (docs/plans/2026-07-06-analyze-json-mode-plan.md).

    The Options field proves only that the wrapper accepts the option. A
    provider that rejects the resolved request mode raises through this
    boundary. There is no second bare request under the same event identity.
    """

    _, model_prompt, json_mode, request_options = _resolved_model_adapter_parts(
        model_name, request_identity=request_identity
    )

    def call(prompt: str) -> str:
        options = dict(request_options)
        if json_mode == "require":
            options["json_object"] = True
        return str(model_prompt(prompt, **options).text())

    return call


def default_provider_adapter(
    model_name: str | None,
    *,
    provider_identity: ProviderIdentity,
    request_identity: RequestIdentity,
    response_schema_builder: Callable[[str], dict[str, object]] | None = None,
) -> ProviderAdapter:
    """Build the provenance-preserving adapter used by immutable caching."""

    if (model_name or "") != provider_identity.model_id:
        raise ValueError("model name does not match provider identity model_id")

    model, model_prompt, json_mode, request_options = _resolved_model_adapter_parts(
        model_name, request_identity=request_identity
    )
    _install_completion_limit_shim(model, provider_identity)
    if json_mode == "require" and not getattr(model, "supports_schema", False):
        raise ValueError("resolved model does not support schema-constrained output")
    model_class = f"{type(model).__module__}.{type(model).__qualname__}"

    def optional_nonblank(value: object) -> str | None:
        return value if isinstance(value, str) and value.strip() else None

    def call(prompt: str) -> ProviderCallResult:
        options = dict(request_options)
        if json_mode == "require":
            schema_builder = response_schema_builder or _semantic_response_schema
            options["schema"] = schema_builder(prompt)
        response = model_prompt(prompt, **options)
        raw_response = str(response.text())
        response_json = getattr(response, "response_json", None)
        if not isinstance(response_json, dict):
            response_json = None
        usage_method = getattr(response, "usage", None)
        usage = usage_method() if callable(usage_method) else None
        input_tokens = getattr(usage, "input", None)
        output_tokens = getattr(usage, "output", None)
        provenance = SemanticProvenance(
            adapter_id=provider_identity.adapter_id,
            adapter_version=provider_identity.adapter_version,
            plugin_version=provider_identity.plugin_distribution_version or None,
            model_class=model_class,
            provider_model_id=optional_nonblank(
                (response_json or {}).get("model")
                or getattr(response, "resolved_model", None)
            ),
            provider_model_revision=optional_nonblank(
                (response_json or {}).get("model_revision")
            ),
            response_id=optional_nonblank((response_json or {}).get("id")),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        return ProviderCallResult(raw_response, provenance)

    return call


def _semantic_response_schema(prompt: str) -> dict[str, object]:
    """Constrain untrusted evidence to exact packet-local coordinate choices."""

    try:
        projection_raw = prompt.rsplit("\n\n", 1)[1]
        projection = json.loads(projection_raw)
    except (IndexError, json.JSONDecodeError) as exc:
        raise ValueError("semantic prompt has no canonical packet projection") from exc
    if not isinstance(projection, dict):
        raise ValueError("semantic prompt packet projection must be an object")
    packet_id = projection.get("packet_id")
    kind = projection.get("kind")
    regions = projection.get("evidence_regions")
    if not isinstance(packet_id, str) or kind not in ("section", "invariant"):
        raise ValueError("semantic prompt packet identity is invalid")
    if not isinstance(regions, list) or not regions:
        raise ValueError("semantic prompt has no citable evidence regions")

    region_variants: list[dict[str, object]] = []
    fields = ("role", "path", "start_line", "end_line")
    for region in regions:
        if not isinstance(region, dict) or set(region) != set(fields):
            raise ValueError("semantic prompt evidence region is invalid")
        region_variants.append(
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {field: {"const": region[field]} for field in fields},
                "required": list(fields),
            }
        )

    classifications = (
        [
            "ok",
            "confirmed_mismatch",
            "probable_mismatch",
            "missing_trace",
            "ambiguous",
        ]
        if kind == "section"
        else [
            "ok",
            "weak_binding",
            "confirmed_mismatch",
            "probable_mismatch",
            "ambiguous",
        ]
    )
    required = [
        "packet_id",
        "classification",
        "confidence",
        "rationale",
        "evidence",
        "summary",
    ]
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "packet_id": {"const": packet_id},
            "classification": {"type": "string", "enum": classifications},
            "confidence": {
                "anyOf": [
                    {"type": "number", "minimum": 0, "maximum": 1},
                    {"type": "null"},
                ]
            },
            "rationale": {"type": "string"},
            "evidence": {
                "type": "array",
                "items": {"anyOf": region_variants},
            },
            "summary": {"type": "string"},
        },
        "required": required,
    }


def build_prompt(
    packet: dict[str, Any],
    *,
    identity: InferenceIdentity | None = None,
    prompt_bytes: bytes | None = None,
) -> str:
    """Compose the exact code-owned prompt and canonical packet projection."""

    if (identity is None) == (prompt_bytes is None):
        raise ValueError("build_prompt requires exactly one frozen prompt authority")
    instruction_bytes = (
        identity.prompt_bytes if identity is not None else cast(bytes, prompt_bytes)
    )
    return model_request_bytes(packet, instruction_bytes=instruction_bytes).decode(
        "utf-8"
    )


def _packet_evidence_bounds(
    packet: dict[str, Any],
) -> dict[str, tuple[tuple[int, int], ...]]:
    """What the model was shown, as path -> allowed line ranges ([SC-7]).

    Owner snippets and the spec section text are line-bounded, so evidence
    must fall inside one of those ranges. Linked tests are named by PATH
    only -- the model never saw their content, so a path with no ranges is
    known to the packet but cannot carry line evidence.
    """

    if packet.get("kind", "section") == "invariant":
        return _snippet_evidence_bounds(
            (*packet.get("targets", ()), *packet.get("binding_tests", ()))
        )

    bounds: dict[str, list[tuple[int, int]]] = {}
    spec_path = packet.get("spec_path")
    # Blank paths never name a packet member: an empty or whitespace-only
    # string must not become a citable evidence path (load-time validation
    # rejects these, but analyze_packets is also a library entry point).
    if isinstance(spec_path, str) and spec_path.strip():
        ranges = bounds.setdefault(spec_path, [])
        start = packet.get("section_start_line")
        text = packet.get("section_text")
        end = (
            lf_end_line(start, text)
            if isinstance(start, int) and isinstance(text, str)
            else None
        )
        if end is not None:
            ranges.append((cast(int, start), end))
    for test in packet.get("tests", ()):
        if isinstance(test, str) and test.strip():
            bounds.setdefault(test, [])
    for owner in packet.get("owners", ()):
        if (
            not isinstance(owner, dict)
            or not isinstance(owner.get("path"), str)
            or not owner["path"].strip()
        ):
            continue
        ranges = bounds.setdefault(owner["path"], [])
        start = owner.get("start_line")
        snippet = owner.get("snippet")
        # An EMPTY snippet (directory mappings) showed no line content:
        # like tests, the path is known but carries no valid line evidence.
        end = (
            lf_end_line(start, snippet)
            if isinstance(start, int) and isinstance(snippet, str)
            else None
        )
        if end is not None:
            ranges.append((cast(int, start), end))
    return {path: tuple(ranges) for path, ranges in bounds.items()}


def _snippet_evidence_bounds(
    items: Iterable[object],
) -> dict[str, tuple[tuple[int, int], ...]]:
    bounds: dict[str, list[tuple[int, int]]] = {}
    for item in items:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("path"), str)
            or not item["path"].strip()
        ):
            continue
        ranges = bounds.setdefault(item["path"], [])
        start = item.get("start_line")
        snippet = item.get("snippet")
        end = (
            lf_end_line(start, snippet)
            if isinstance(start, int) and isinstance(snippet, str)
            else None
        )
        if end is not None:
            ranges.append((cast(int, start), end))
    return {path: tuple(ranges) for path, ranges in bounds.items()}


def _has_binding_test_evidence(
    packet: dict[str, Any],
    evidence: tuple[tuple[str, int], ...],
) -> bool:
    bounds = _snippet_evidence_bounds(packet.get("binding_tests", ()))
    return any(
        any(start <= line <= end for start, end in bounds.get(path, ()))
        for path, line in evidence
    )


def _parse_model_output(
    raw: str,
    packet: dict[str, Any],
    identity: InferenceIdentity,
) -> dict[str, Any] | str:
    try:
        row = json.loads(raw)
    except json.JSONDecodeError:
        return "model output is not valid JSON"
    try:
        result = normalize_model_result(packet, row, analysis_key=identity.analysis_key)
    except SemanticResultError as exc:
        return f"model output invalid: {exc}"
    return result.to_row()


def analyze_packets(
    packets: Iterable[dict[str, Any]],
    adapter: ModelAdapter,
    concurrency: int = 1,
    *,
    provider_identity: ProviderIdentity = _CONTROLLED_PROVIDER,
    request_identity: RequestIdentity = _CONTROLLED_REQUEST,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Run the adapter over every packet; collect rows and per-packet errors.

    This legacy helper is the controlled-adapter test seam. Malformed/provider
    failures produce no v2 row and are returned as problems. Output rows keep
    successful packet order regardless of concurrency.
    """

    packet_list = list(packets)

    def run_one(packet: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
        packet_id = packet.get("packet_id", "<missing packet_id>")
        try:
            identity = build_inference_identity(
                packet, provider_identity, request_identity
            )
            prompt = build_prompt(packet, identity=identity)
        except Exception as exc:  # noqa: BLE001 - contain one packet boundary
            message = f"packet preparation failed: {exc}"
            return None, f"{packet_id}: {message}"
        try:
            raw = adapter(prompt)
        except Exception as exc:  # noqa: BLE001 - adapter is an external boundary
            message = f"model call failed: {exc}"
            return None, f"{packet_id}: {message}"
        try:
            parsed = _parse_model_output(raw, packet, identity)
        except Exception as exc:  # noqa: BLE001 - contain one packet boundary
            message = f"model output processing failed: {exc}"
            return None, f"{packet_id}: {message}"
        if isinstance(parsed, str):
            return None, f"{packet_id}: {parsed}"
        return parsed, None

    if concurrency <= 1:
        outcomes = [run_one(packet) for packet in packet_list]
    else:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            outcomes = list(pool.map(run_one, packet_list))

    rows = [row for row, _ in outcomes if row is not None]
    errors = [error for _, error in outcomes if error is not None]
    return rows, errors


def analyze_exit_code(rows: list[dict[str, Any]], errors: list[str]) -> int:
    """Exit 2 for any incomplete controlled-adapter analysis; 0 otherwise.

    [SC-5]: exit 1 is reserved for deterministic findings about the target
    repository, and semantic findings are advisory -- `analyze` never
    returns 1. Total failure (every packet errored; rows include the
    per-packet error records) is a statement about the tool or the model,
    so it is exit 2. Partial failure still exits 0 because the output is
    usable; total failure must be scriptable without scraping stderr.
    """

    return 2 if errors else 0


def render_results_jsonl(rows: list[dict[str, Any]]) -> str:
    """Render analysis rows as JSONL, one result per line."""

    return "".join(canonical_json_bytes(row).decode("utf-8") + "\n" for row in rows)


def resolve_model_name(
    explicit: str | None = None,
    *,
    configured: str | None = None,
) -> str | None:
    """Return an already resolved model or defer to the provider default.

    Returns ``None`` to mean "let ``llm`` use its configured default" so the
    lazy-import boundary stays in ``default_adapter``. Backstitch configuration
    precedence, including ``LLM_MODEL``, is owned by
    :func:`backstitch.settings.resolve_config` ([CFG-5.1]).
    """

    if explicit is not None and explicit.strip():
        return explicit.strip()
    if configured is not None and configured.strip():
        return configured.strip()
    return None
