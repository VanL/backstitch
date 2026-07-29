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
from typing import Any, Literal

from backstitch.canonical import canonical_json_bytes
from backstitch.grammar import is_sha256_hex
from backstitch.semantic_packets import prompt_descriptor, prompt_instruction_bytes


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
    json_mode: Literal["require", "off"]
    temperature: float
    seed: int
    max_tokens: int

    def __post_init__(self) -> None:
        if self.json_mode not in ("require", "off"):
            raise ValueError("json_mode must be require or off")
        if (
            isinstance(self.temperature, bool)
            or not isinstance(self.temperature, (int, float))
            or not math.isfinite(self.temperature)
            or not 0 <= self.temperature <= 2
        ):
            raise ValueError("temperature must be a finite number from 0 through 2")
        object.__setattr__(self, "temperature", float(self.temperature))
        if (
            isinstance(self.seed, bool)
            or not isinstance(self.seed, int)
            or self.seed < 0
        ):
            raise ValueError("seed must be a nonnegative integer")
        if (
            isinstance(self.max_tokens, bool)
            or not isinstance(self.max_tokens, int)
            or self.max_tokens < 1
        ):
            raise ValueError("max_tokens must be a positive integer")


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

    from backstitch.semantic_verification import (
        VERIFY_CONTRACT_VERSION,
        verification_prompt_descriptor,
    )

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
        "request": asdict(analysis_request),
        "prompts": prompts,
        "base_search_epoch": analysis_search_epoch,
    }
    verify = {
        "verify_contract_version": VERIFY_CONTRACT_VERSION,
        "prompt": asdict(verification_prompt_descriptor()),
        "provider": asdict(verify_provider),
        "request": asdict(verify_request),
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
            "request": asdict(request),
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
