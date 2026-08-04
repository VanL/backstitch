"""Offline semantic inference identity.

Owns the offline inference identity used before adapter construction.

Spec: docs/specs/06-semantic-gates.md [SEM-3]
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Literal, cast

from backstitch.canonical import canonical_json_bytes
from backstitch.grammar import is_sha256_hex
from backstitch.semantic_packets import prompt_descriptor, prompt_instruction_bytes
from backstitch.semantic_verification_contract import (
    VERIFY_CONTRACT_VERSION,
    verification_prompt_descriptor,
)


@dataclass(frozen=True, slots=True)
class ProviderIdentity:
    backend_id: str
    plugin_id: str
    model_id: str
    model_revision: str
    adapter_id: str
    adapter_version: int
    llm_distribution_version: str
    plugin_distribution_name: str
    plugin_distribution_version: str

    def __post_init__(self) -> None:
        string_fields = (
            self.backend_id,
            self.plugin_id,
            self.model_id,
            self.model_revision,
            self.adapter_id,
            self.llm_distribution_version,
            self.plugin_distribution_name,
            self.plugin_distribution_version,
        )
        if not all(isinstance(value, str) for value in string_fields):
            raise ValueError("provider identity fields must be strings")
        if (
            isinstance(self.adapter_version, bool)
            or not isinstance(self.adapter_version, int)
            or self.adapter_version < 1
        ):
            raise ValueError("adapter_version must be a positive integer")
        if not self.adapter_id.strip():
            raise ValueError("adapter_id must be nonblank")
        if not self.llm_distribution_version.strip():
            raise ValueError("llm_distribution_version must be nonblank")
        if not self.plugin_distribution_name.strip():
            if (
                self.plugin_distribution_name != ""
                or self.plugin_distribution_version != ""
            ):
                raise ValueError(
                    "blank plugin distribution name requires an empty version"
                )
        elif not self.plugin_distribution_version.strip():
            raise ValueError(
                "plugin distribution version must be nonblank when a name is declared"
            )


@dataclass(frozen=True, slots=True)
class RequestIdentity:
    """Closed identity projection of the exact provider request.

    ``None`` means that the trusted capability descriptor resolved the field
    as absent.  The projection helper below omits absent fields rather than
    relying on an adapter or provider default.
    """

    json_mode: Literal["require", "off"] | None = None
    temperature: float | None = None
    seed: int | None = None
    max_tokens: int | None = None

    def __post_init__(self) -> None:
        if self.json_mode is not None and self.json_mode not in ("require", "off"):
            raise ValueError("json_mode must be require or off")
        if self.temperature is not None and (
            isinstance(self.temperature, bool)
            or not isinstance(self.temperature, (int, float))
            or not math.isfinite(self.temperature)
            or not 0 <= self.temperature <= 2
        ):
            raise ValueError("temperature must be a finite number from 0 through 2")
        if self.temperature is not None:
            object.__setattr__(self, "temperature", float(self.temperature))
        if self.seed is not None and (
            isinstance(self.seed, bool)
            or not isinstance(self.seed, int)
            or self.seed < 0
        ):
            raise ValueError("seed must be a nonnegative integer")
        if self.max_tokens is not None and (
            isinstance(self.max_tokens, bool)
            or not isinstance(self.max_tokens, int)
            or self.max_tokens < 1
        ):
            raise ValueError("max_tokens must be a positive integer")

    def to_dict(self) -> dict[str, object]:
        """Return the exact closed projection, omitting resolved-absent fields."""

        return {
            name: value
            for name, value in (
                ("json_mode", self.json_mode),
                ("temperature", self.temperature),
                ("seed", self.seed),
                ("max_tokens", self.max_tokens),
            )
            if value is not None
        }


@dataclass(frozen=True, slots=True)
class EffectiveRequest:
    """One immutable provider request before identity is derived."""

    json_mode: Literal["require", "off"] | None = None
    temperature: float | None = None
    seed: int | None = None
    max_tokens: int | None = None

    def __post_init__(self) -> None:
        # Reuse the identity validator so request and identity cannot drift.
        RequestIdentity(
            self.json_mode,
            self.temperature,
            self.seed,
            self.max_tokens,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            name: value
            for name, value in (
                ("json_mode", self.json_mode),
                ("temperature", self.temperature),
                ("seed", self.seed),
                ("max_tokens", self.max_tokens),
            )
            if value is not None
        }

    def identity(self) -> RequestIdentity:
        return RequestIdentity(
            self.json_mode,
            self.temperature,
            self.seed,
            self.max_tokens,
        )


RequestPresence = Literal["required", "optional", "forbidden"]


@dataclass(frozen=True, slots=True)
class RequestFieldConstraint:
    """Trusted presence and value contract for one request field."""

    presence: RequestPresence
    allowed_values: tuple[object, ...] | None
    minimum: int | float | None
    maximum: int | float | None

    def __post_init__(self) -> None:
        if self.presence not in {"required", "optional", "forbidden"}:
            raise ValueError("request field presence is invalid")
        if self.presence == "forbidden":
            if (
                self.allowed_values is not None
                or self.minimum is not None
                or self.maximum is not None
            ):
                raise ValueError("forbidden request fields cannot have value limits")
            return
        if self.allowed_values is not None:
            if (
                not self.allowed_values
                or self.minimum is not None
                or self.maximum is not None
            ):
                raise ValueError(
                    "allowed request values must be nonempty and cannot have bounds"
                )
            if any(
                value == earlier
                for index, value in enumerate(self.allowed_values)
                for earlier in self.allowed_values[:index]
            ):
                raise ValueError("allowed request values must not contain duplicates")
            return
        if (self.minimum is None) != (self.maximum is None):
            raise ValueError("request field bounds must be both present or both absent")
        if self.minimum is not None and self.maximum is not None:
            if (
                isinstance(self.minimum, bool)
                or isinstance(self.maximum, bool)
                or not isinstance(self.minimum, (int, float))
                or not isinstance(self.maximum, (int, float))
                or not math.isfinite(float(self.minimum))
                or not math.isfinite(float(self.maximum))
                or self.minimum > self.maximum
            ):
                raise ValueError("request field bounds are invalid")


@dataclass(frozen=True, slots=True)
class RequestConstraints:
    json_mode: RequestFieldConstraint
    temperature: RequestFieldConstraint
    seed: RequestFieldConstraint
    max_tokens: RequestFieldConstraint


@dataclass(frozen=True, slots=True)
class CapabilityDescriptor:
    """Committed authority for one stable model/request combination."""

    capability_schema_version: Literal[1]
    capability_revision: str
    model_id: str
    model_revision: str
    request_constraints: RequestConstraints
    maximum_input_bytes: int

    def __post_init__(self) -> None:
        if self.capability_schema_version != 1:
            raise ValueError("capability_schema_version must equal 1")
        if (
            not isinstance(self.capability_revision, str)
            or not self.capability_revision.strip()
        ):
            raise ValueError("capability_revision must be nonblank")
        if not isinstance(self.model_id, str) or not isinstance(
            self.model_revision, str
        ):
            raise ValueError("capability provider identity must be strings")
        if bool(self.model_id.strip()) != bool(self.model_revision.strip()):
            raise ValueError(
                "capability model_id and model_revision must be both blank or nonblank"
            )
        if (
            isinstance(self.maximum_input_bytes, bool)
            or not isinstance(self.maximum_input_bytes, int)
            or self.maximum_input_bytes < 1
        ):
            raise ValueError("maximum_input_bytes must be a positive integer")

    def to_dict(self) -> dict[str, object]:
        return {
            "capability_schema_version": self.capability_schema_version,
            "capability_revision": self.capability_revision,
            "provider": {
                "model_id": self.model_id,
                "model_revision": self.model_revision,
            },
            "request_constraints": {
                name: asdict(getattr(self.request_constraints, name))
                for name in ("json_mode", "temperature", "seed", "max_tokens")
            },
            "maximum_input_bytes": self.maximum_input_bytes,
        }


@dataclass(frozen=True, slots=True)
class CapabilityProvenance:
    source: str
    source_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("capability provenance source must be nonblank")
        if not is_sha256_hex(self.source_sha256):
            raise ValueError("capability provenance hash must be lowercase SHA-256")


def build_capability_provenance(
    capability: CapabilityDescriptor,
    *,
    source: str,
) -> CapabilityProvenance:
    return CapabilityProvenance(
        source,
        hashlib.sha256(canonical_json_bytes(capability.to_dict())).hexdigest(),
    )


@dataclass(frozen=True, slots=True)
class ResolvedInference:
    """Stable identity, raw transport, and frozen request with one owner."""

    provider_identity: ProviderIdentity
    adapter_model_id: str
    effective_request: EffectiveRequest
    request_identity: RequestIdentity
    capability: CapabilityDescriptor
    capability_provenance: CapabilityProvenance

    def __post_init__(self) -> None:
        if not self.adapter_model_id.strip():
            raise ValueError("adapter_model_id must be nonblank")
        if self.provider_identity.model_id != self.capability.model_id:
            raise ValueError(
                "capability model_id does not match stable provider identity"
            )
        if self.provider_identity.model_revision != self.capability.model_revision:
            raise ValueError(
                "capability model_revision does not match stable provider identity"
            )
        if self.request_identity.to_dict() != self.effective_request.to_dict():
            raise ValueError("request identity does not match the effective request")
        if self.capability_provenance != build_capability_provenance(
            self.capability,
            source=self.capability_provenance.source,
        ):
            raise ValueError("capability provenance does not match descriptor bytes")


def request_identity_dict(request: RequestIdentity) -> dict[str, object]:
    """Centralize the optional-field projection for identity/cache callers."""

    return request.to_dict()


def _validate_request_constraint(
    field_name: str,
    value: object | None,
    constraint: RequestFieldConstraint,
    *,
    key_prefix: str,
) -> None:
    key = f"{key_prefix}.{field_name}"
    if value is None:
        if constraint.presence == "required":
            raise ValueError(f"{key} is required by the selected model capability")
        return
    if constraint.presence == "forbidden":
        raise ValueError(f"{key} is forbidden by the selected model capability")
    if constraint.allowed_values is not None and value not in constraint.allowed_values:
        allowed = ", ".join(repr(item) for item in constraint.allowed_values)
        raise ValueError(f"{key} must be one of: {allowed}")
    if constraint.minimum is not None and (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or value < constraint.minimum
        or value > cast(int | float, constraint.maximum)
    ):
        raise ValueError(
            f"{key} must be from {constraint.minimum} through {constraint.maximum}"
        )


def resolve_inference(
    *,
    provider_identity: ProviderIdentity,
    adapter_model_id: str,
    requested: EffectiveRequest,
    capability: CapabilityDescriptor,
    capability_provenance: CapabilityProvenance,
    key_prefix: str,
) -> ResolvedInference:
    """Validate capability, then freeze the exact request and its identity."""

    constraints = capability.request_constraints
    for field_name in ("json_mode", "temperature", "seed", "max_tokens"):
        _validate_request_constraint(
            field_name,
            getattr(requested, field_name),
            getattr(constraints, field_name),
            key_prefix=key_prefix,
        )
    return ResolvedInference(
        provider_identity=provider_identity,
        adapter_model_id=adapter_model_id,
        effective_request=requested,
        request_identity=requested.identity(),
        capability=capability,
        capability_provenance=capability_provenance,
    )


@dataclass(frozen=True, slots=True)
class ReviewIdentity:
    """Provider-independent identity of one complete semantic review."""

    _canonical_contract: bytes
    review_key: str

    @property
    def contract(self) -> dict[str, Any]:
        value = json.loads(self._canonical_contract)
        assert isinstance(value, dict)
        return value

    @property
    def contract_bytes(self) -> bytes:
        return self._canonical_contract


@dataclass(frozen=True, slots=True)
class InferenceIdentity:
    _canonical_contract: bytes
    analysis_key: str
    _prompt_bytes: bytes
    review_identity: ReviewIdentity

    @property
    def contract(self) -> dict[str, Any]:
        value = json.loads(self._canonical_contract)
        assert isinstance(value, dict)
        return value

    @property
    def prompt_bytes(self) -> bytes:
        return self._prompt_bytes

    @property
    def contract_bytes(self) -> bytes:
        return self._canonical_contract


@dataclass(frozen=True, slots=True)
class CompositionIdentity:
    _analysis_composition: bytes
    analysis_composition_sha256: str
    _verify_composition: bytes
    verify_composition_sha256: str
    composition_sha256: str

    @property
    def analysis_composition(self) -> dict[str, Any]:
        value = json.loads(self._analysis_composition)
        assert isinstance(value, dict)
        return value

    @property
    def verify_composition(self) -> dict[str, Any]:
        value = json.loads(self._verify_composition)
        assert isinstance(value, dict)
        return value


def build_composition_identity(
    analysis_provider: ProviderIdentity,
    analysis_request: RequestIdentity,
    *,
    analysis_search_epoch: str,
    verify_provider: ProviderIdentity,
    verify_request: RequestIdentity,
    verify_search_epochs: tuple[str, ...],
    required_verdicts: int,
    minimum_support_score: float,
    indeterminate: str,
    analysis_contract_version: int = 1,
) -> CompositionIdentity:
    """Build the configuration-level analyzer/verifier qualification selector."""

    if (
        isinstance(analysis_contract_version, bool)
        or not isinstance(analysis_contract_version, int)
        or analysis_contract_version < 1
    ):
        raise ValueError("analysis_contract_version must be a positive integer")
    if not isinstance(analysis_search_epoch, str) or not analysis_search_epoch.strip():
        raise ValueError("analysis search epoch must be nonblank")
    if (
        not verify_search_epochs
        or any(
            not isinstance(item, str) or not item.strip()
            for item in verify_search_epochs
        )
        or len(set(verify_search_epochs)) != len(verify_search_epochs)
    ):
        raise ValueError("verify search epochs must be ordered unique nonblank strings")
    if (
        isinstance(required_verdicts, bool)
        or not isinstance(required_verdicts, int)
        or required_verdicts != len(verify_search_epochs)
    ):
        raise ValueError("required_verdicts must equal verify search epoch count")
    if (
        isinstance(minimum_support_score, bool)
        or not isinstance(minimum_support_score, (int, float))
        or not math.isfinite(minimum_support_score)
        or not 0 <= minimum_support_score <= 1
    ):
        raise ValueError("minimum_support_score must be finite from zero through one")
    if indeterminate not in {"allow", "report"}:
        raise ValueError("indeterminate must be allow or report")
    prompts = []
    for kind in ("section", "invariant"):
        descriptor = prompt_descriptor(kind)
        prompts.append({"kind": kind, **asdict(descriptor)})
    analysis = {
        "analysis_contract_version": analysis_contract_version,
        "provider": asdict(analysis_provider),
        "request": analysis_request.to_dict(),
        "prompts": prompts,
        "base_search_epoch": analysis_search_epoch,
    }
    verify = {
        "verify_contract_version": VERIFY_CONTRACT_VERSION,
        "prompt": asdict(verification_prompt_descriptor()),
        "provider": asdict(verify_provider),
        "request": verify_request.to_dict(),
        "search_epochs": list(verify_search_epochs),
        "required_verdicts": required_verdicts,
        "minimum_support_score": float(minimum_support_score),
        "indeterminate": indeterminate,
    }
    analysis_hash = hashlib.sha256(canonical_json_bytes(analysis)).hexdigest()
    verify_hash = hashlib.sha256(canonical_json_bytes(verify)).hexdigest()
    combined = hashlib.sha256(
        canonical_json_bytes(
            {
                "analysis_composition_sha256": analysis_hash,
                "verify_composition_sha256": verify_hash,
            }
        )
    ).hexdigest()
    return CompositionIdentity(
        canonical_json_bytes(analysis),
        analysis_hash,
        canonical_json_bytes(verify),
        verify_hash,
        combined,
    )


def _build_review_contract(
    packet: dict[str, Any],
    request: RequestIdentity,
    *,
    analysis_contract_version: int,
    search_epoch: str,
) -> tuple[dict[str, Any], bytes]:
    """Build the one provider-independent preimage shared by both identities."""

    if (
        isinstance(analysis_contract_version, bool)
        or not isinstance(analysis_contract_version, int)
        or analysis_contract_version < 1
    ):
        raise ValueError("analysis_contract_version must be a positive integer")
    if not isinstance(search_epoch, str) or not search_epoch.strip():
        raise ValueError("search_epoch must be nonblank")
    packet_hash = packet.get("packet_hash")
    if not is_sha256_hex(packet_hash):
        raise ValueError("packet_hash must be 64 lowercase hexadecimal characters")
    kind = packet.get("kind")
    if kind not in {"section", "invariant", "suppression"}:
        raise ValueError("packet kind is invalid")
    prompt_bytes = prompt_instruction_bytes(kind)
    prompt = prompt_descriptor(packet["kind"], instruction_bytes=prompt_bytes)
    return (
        {
            "analysis_contract_version": analysis_contract_version,
            "packet_hash": packet["packet_hash"],
            "prompt": asdict(prompt),
            "request": request.to_dict(),
            "search_epoch": search_epoch,
        },
        prompt_bytes,
    )


def build_analysis_identities(
    packet: dict[str, Any],
    provider: ProviderIdentity,
    request: RequestIdentity,
    *,
    analysis_contract_version: int = 1,
    search_epoch: str = "1",
) -> tuple[InferenceIdentity, ReviewIdentity]:
    """Construct both semantic identities from one frozen canonical owner."""

    review_contract, prompt_bytes = _build_review_contract(
        packet,
        request,
        analysis_contract_version=analysis_contract_version,
        search_epoch=search_epoch,
    )
    review_canonical = canonical_json_bytes(review_contract)
    review_identity = ReviewIdentity(
        _canonical_contract=review_canonical,
        review_key=hashlib.sha256(review_canonical).hexdigest(),
    )
    inference_contract = {
        "analysis_contract_version": analysis_contract_version,
        "packet_hash": packet["packet_hash"],
        "prompt": review_contract["prompt"],
        "provider": asdict(provider),
        "request": review_contract["request"],
        "search_epoch": search_epoch,
    }
    inference_canonical = canonical_json_bytes(inference_contract)
    return (
        InferenceIdentity(
            _canonical_contract=inference_canonical,
            analysis_key=hashlib.sha256(inference_canonical).hexdigest(),
            _prompt_bytes=prompt_bytes,
            review_identity=review_identity,
        ),
        review_identity,
    )


def build_inference_identity(
    packet: dict[str, Any],
    provider: ProviderIdentity,
    request: RequestIdentity,
    *,
    analysis_contract_version: int = 1,
    search_epoch: str = "1",
) -> InferenceIdentity:
    """Construct and hash the closed provider-sensitive inference contract."""

    return build_analysis_identities(
        packet,
        provider,
        request,
        analysis_contract_version=analysis_contract_version,
        search_epoch=search_epoch,
    )[0]


def build_review_identity(
    packet: dict[str, Any],
    request: RequestIdentity,
    *,
    analysis_contract_version: int = 1,
    search_epoch: str = "1",
) -> ReviewIdentity:
    """Construct and hash the provider-independent semantic review contract."""

    contract, _ = _build_review_contract(
        packet,
        request,
        analysis_contract_version=analysis_contract_version,
        search_epoch=search_epoch,
    )
    canonical = canonical_json_bytes(contract)
    return ReviewIdentity(
        _canonical_contract=canonical,
        review_key=hashlib.sha256(canonical).hexdigest(),
    )


def resolve_provider_identity(
    *,
    backend_id: str,
    plugin_id: str,
    model_id: str,
    model_revision: str,
    plugin_distribution_name: str,
) -> ProviderIdentity:
    """Resolve installed software versions without constructing an adapter."""

    try:
        llm_version = version("llm")
    except PackageNotFoundError as exc:
        raise ValueError("required `llm` distribution is not installed") from exc
    plugin_version = ""
    if plugin_distribution_name.strip():
        try:
            plugin_version = version(plugin_distribution_name)
        except PackageNotFoundError as exc:
            raise ValueError(
                f"declared plugin distribution is not installed: {plugin_distribution_name}"
            ) from exc
    return ProviderIdentity(
        backend_id=backend_id,
        plugin_id=plugin_id,
        model_id=model_id,
        model_revision=model_revision,
        adapter_id="backstitch.llm",
        adapter_version=3,
        llm_distribution_version=llm_version,
        plugin_distribution_name=plugin_distribution_name,
        plugin_distribution_version=plugin_version,
    )
