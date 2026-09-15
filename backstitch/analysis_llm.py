"""Provider request construction and wire adaptation for semantic analysis.

Spec: docs/specs/02-backstitch-core.md [SC-7], [SC-13]
Spec: docs/specs/06-semantic-gates.md [SEM-3]

This module is the lazy ``llm`` adapter. Packet iteration, prompt identity,
result normalization, caching, and failure policy belong to the shipping
semantic-analysis modules.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from typing import Any, cast

from backstitch.semantic_cache import (
    ProviderAdapter,
    ProviderCallResult,
    SemanticProvenance,
)
from backstitch.semantic_evidence import (
    EVIDENCE_ROLES,
    INVARIANT_CLASSIFICATIONS,
    SECTION_CLASSIFICATIONS,
    SUPPRESSION_CLASSIFICATIONS,
    required_evidence_roles,
)
from backstitch.semantic_identity import (
    EffectiveRequest,
    ProviderIdentity,
    RequestIdentity,
    ResolvedInference,
)

__all__ = ("default_provider_adapter", "resolve_model_name")


def _is_llm_responses_model(model: object) -> bool:
    """Identify ``llm``'s public OpenAI Responses model family."""

    return any(
        base.__module__ == "llm.default_plugins.openai_models"
        and base.__name__ == "Responses"
        for base in type(model).__mro__
    )


def _install_completion_limit_shim(
    model: object,
    provider_identity: ProviderIdentity,
    *,
    adapter_model_id: str | None,
) -> None:
    """Translate Backstitch's logical output cap to the provider wire name."""

    # ``llm`` 0.33's Responses adapter owns the public logical-to-wire mapping
    # from max_tokens to max_output_tokens. The legacy Chat shim must never
    # patch that independent path.
    if _is_llm_responses_model(model):
        return

    model_id = (adapter_model_id or cast(str, getattr(model, "model_id", ""))).lower()
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
        raise ValueError(
            "provider request incompatible: resolved OpenAI model cannot enforce "
            "max_completion_tokens"
        )

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
            "provider request incompatible: resolved OpenAI model cannot install "
            "max_completion_tokens support"
        ) from exc


def _install_responses_no_retry_policy(model: object) -> None:
    """Make one Backstitch Responses call exactly one remote HTTP attempt."""

    if not _is_llm_responses_model(model):
        return
    original = getattr(model, "get_client", None)
    if not callable(original):
        raise ValueError(
            "provider request incompatible: resolved Responses model cannot control "
            "provider retries"
        )

    def get_client(key: str | None, *, async_: bool = False) -> object:
        client = original(key, async_=async_)
        with_options = getattr(client, "with_options", None)
        if not callable(with_options):
            raise ValueError(
                "provider request incompatible: resolved Responses client cannot "
                "disable provider retries"
            )
        no_retry_client = with_options(max_retries=0)
        if getattr(no_retry_client, "max_retries", None) != 0:
            raise ValueError(
                "provider request incompatible: resolved Responses client did not "
                "disable provider retries"
            )
        return no_retry_client

    try:
        cast(Any, model).get_client = get_client
    except (AttributeError, TypeError) as exc:
        raise ValueError(
            "provider request incompatible: resolved Responses model cannot install "
            "no-retry provider policy"
        ) from exc


def _resolved_model_adapter_parts(
    model_name: str | None,
    *,
    effective_request: EffectiveRequest,
) -> tuple[Any, Callable[..., Any], str, dict[str, object]]:
    """Resolve one ``llm`` model and its exact supported request options."""

    import llm

    model = llm.get_model(model_name) if model_name else llm.get_model()
    model_prompt = cast(Any, model).prompt
    option_fields = getattr(getattr(model, "Options", None), "model_fields", {})
    json_mode = effective_request.json_mode or "off"
    request = effective_request.to_dict()
    required_options: set[str] = {
        name
        for name in ("temperature", "seed", "max_tokens", "reasoning_effort")
        if name in request
    }
    if json_mode == "require":
        required_options.add("json_object")
    missing_options = sorted(required_options - set(option_fields))
    if missing_options:
        raise ValueError(
            "provider request incompatible: resolved model does not support request "
            "options: " + ", ".join(missing_options)
        )
    request_options: dict[str, object] = {
        name: request[name]
        for name in ("temperature", "seed", "max_tokens", "reasoning_effort")
        if name in request
    }
    if _is_llm_responses_model(model):
        try:
            prompt_parameters = inspect.signature(model_prompt).parameters
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "provider request incompatible: resolved Responses model cannot prove "
                "hide_reasoning support"
            ) from exc
        if "hide_reasoning" not in prompt_parameters:
            raise ValueError(
                "provider request incompatible: resolved Responses model does not "
                "support hide_reasoning"
            )
        # This protocol constant prevents llm from implicitly requesting
        # reasoning summaries. It is covered by the keyed adapter version, not
        # by the user-controlled request identity.
        request_options["hide_reasoning"] = True
    return model, model_prompt, json_mode, request_options


def default_provider_adapter(  # noqa: C901 approved [SC-17.1] RUFF-SUP-014 exception
    model_name: ResolvedInference | str | None,
    *,
    provider_identity: ProviderIdentity | None = None,
    request_identity: RequestIdentity | None = None,
    resolved_inference: ResolvedInference | None = None,
    response_schema_builder: Callable[[str], dict[str, object]] | None = None,
) -> ProviderAdapter:
    """Build the provenance-preserving adapter used by immutable caching."""

    raw_model_name: str | None
    if resolved_inference is not None:
        if isinstance(model_name, ResolvedInference):
            raise ValueError("resolved inference must be supplied through one seam")
        inference = resolved_inference
        if model_name != inference.adapter_model_id:
            raise ValueError("raw model name does not match resolved inference")
        if (
            provider_identity is not None
            and provider_identity != inference.provider_identity
            or request_identity is not None
            and request_identity != inference.request_identity
        ):
            raise ValueError(
                "legacy identity arguments do not match resolved inference"
            )
        raw_model_name = inference.adapter_model_id
        provider_identity = inference.provider_identity
        effective_request = inference.effective_request
    elif isinstance(model_name, ResolvedInference):
        if provider_identity is not None or request_identity is not None:
            raise ValueError(
                "resolved inference cannot be combined with legacy identity arguments"
            )
        inference = model_name
        raw_model_name = inference.adapter_model_id
        provider_identity = inference.provider_identity
        effective_request = inference.effective_request
    else:
        # Compatibility for callers that already froze a request identity.
        # Production resolution uses ``ResolvedInference`` and never compares
        # its stable PURL with this raw transport selector.
        raw_model_name = model_name
        if provider_identity is None or request_identity is None:
            raise ValueError(
                "legacy adapter construction requires provider and request identity"
            )
        if (raw_model_name or "") != provider_identity.model_id:
            raise ValueError("model name does not match provider identity model_id")
        effective_request = EffectiveRequest(
            json_mode=request_identity.json_mode,
            temperature=request_identity.temperature,
            seed=request_identity.seed,
            max_tokens=request_identity.max_tokens,
            reasoning_effort=request_identity.reasoning_effort,
        )

    model, model_prompt, json_mode, request_options = _resolved_model_adapter_parts(
        raw_model_name, effective_request=effective_request
    )
    _install_responses_no_retry_policy(model)
    _install_completion_limit_shim(
        model,
        provider_identity,
        adapter_model_id=raw_model_name,
    )
    if json_mode == "require" and not getattr(model, "supports_schema", False):
        raise ValueError(
            "provider request incompatible: resolved model does not support "
            "schema-constrained output"
        )
    model_class = f"{type(model).__module__}.{type(model).__qualname__}"

    def optional_nonblank(value: object) -> str | None:
        return value if isinstance(value, str) and value.strip() else None

    def call(prompt: str) -> ProviderCallResult:
        options = dict(request_options)
        if json_mode == "require":
            schema_builder = response_schema_builder or _semantic_response_schema
            options["schema"] = schema_builder(prompt)
        try:
            response = model_prompt(prompt, **options)
            raw_response = str(response.text())
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "provider request incompatible: adapter serialization or response "
                "decoding failed"
            ) from exc
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


def _assessment_variants(kind: str, regions: list[object]) -> list[dict[str, object]]:
    regions_by_role: dict[str, list[dict[str, object]]] = {}
    fields = ("role", "path", "start_line", "end_line")
    for region in regions:
        if not isinstance(region, dict) or set(region) != set(fields):
            raise ValueError("semantic prompt evidence region is invalid")
        role = region["role"]
        if role not in EVIDENCE_ROLES:
            raise ValueError("semantic prompt evidence region role is invalid")
        coordinate_fields = ("path", "start_line", "end_line")
        regions_by_role.setdefault(role, []).append(
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    field: {"const": region[field]} for field in coordinate_fields
                },
                "required": list(coordinate_fields),
            }
        )

    classifications = {
        "section": SECTION_CLASSIFICATIONS,
        "invariant": INVARIANT_CLASSIFICATIONS,
        "suppression": SUPPRESSION_CLASSIFICATIONS,
    }[kind]
    assessment_variants: list[dict[str, object]] = []
    available_roles = frozenset(regions_by_role)
    for classification in sorted(classifications):
        required_roles = required_evidence_roles(kind, classification)
        if not required_roles.issubset(available_roles):
            continue
        evidence_schema: dict[str, object] = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                role: {
                    "type": "array",
                    "items": {"anyOf": variants},
                    "uniqueItems": True,
                    **({"minItems": 1} if role in required_roles else {}),
                }
                for role, variants in regions_by_role.items()
            },
        }
        if required_roles:
            evidence_schema["required"] = sorted(required_roles)
        assessment_variants.append(
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "classification": {"const": classification},
                    "evidence": evidence_schema,
                },
                "required": ["classification", "evidence"],
            }
        )
    if not assessment_variants:
        raise ValueError("semantic prompt has no feasible result classification")
    return assessment_variants


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
    if not isinstance(packet_id, str) or kind not in (
        "section",
        "invariant",
        "suppression",
    ):
        raise ValueError("semantic prompt packet identity is invalid")
    if not isinstance(regions, list) or not regions:
        raise ValueError("semantic prompt has no citable evidence regions")
    assessment_variants = _assessment_variants(kind, regions)
    required = [
        "packet_id",
        "assessment",
        "confidence",
        "rationale",
        "summary",
    ]
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "packet_id": {"const": packet_id},
            "assessment": {"anyOf": assessment_variants},
            "confidence": {
                "anyOf": [
                    {"type": "number", "minimum": 0, "maximum": 1},
                    {"type": "null"},
                ]
            },
            "rationale": {"type": "string"},
            "summary": {"type": "string"},
        },
        "required": required,
    }


def resolve_model_name(
    explicit: str | None = None,
    *,
    configured: str | None = None,
) -> str | None:
    """Return an already resolved model or defer to the provider default.

    ``None`` means "let ``llm`` use its configured default". Backstitch
    configuration precedence, including ``LLM_MODEL``, belongs to
    :func:`backstitch.settings.resolve_config`.
    """

    if explicit is not None and explicit.strip():
        return explicit.strip()
    if configured is not None and configured.strip():
        return configured.strip()
    return None
