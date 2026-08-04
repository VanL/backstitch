"""Verifier prompt metadata and cache-independent work contracts.

This leaf owns data needed by both semantic identity construction and verifier
execution. It deliberately imports neither runtime, cache, nor analysis code.

Spec: docs/specs/02-backstitch-core.md [SC-17]
Spec: docs/specs/06-semantic-gates.md [SEM-3]
Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-3.1]
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from importlib import resources
from typing import Any

from backstitch.canonical import canonical_json_bytes
from backstitch.semantic_packets import PromptDescriptor

VERIFY_CONTRACT_VERSION = 3
VERIFY_PROMPT_ID = "backstitch.adversarial-verification"
VERIFY_PROMPT_VERSION = 1
VERIFY_PROMPT_RESOURCE = "adversarial_verification.md"


class VerificationContractError(ValueError):
    """A claim, verifier response, identity, or aggregate is invalid."""


@dataclass(frozen=True, slots=True)
class VerificationClaim:
    _canonical_value: bytes
    claim_hash: str

    @classmethod
    def from_value(cls, value: dict[str, Any]) -> VerificationClaim:
        canonical = canonical_json_bytes(value)
        return cls(canonical, hashlib.sha256(canonical).hexdigest())

    @property
    def value(self) -> dict[str, Any]:
        value = json.loads(self._canonical_value)
        assert isinstance(value, dict)
        return value


@dataclass(frozen=True, slots=True)
class VerificationRequest:
    _canonical_value: bytes
    verifier_packet_hash: str

    @classmethod
    def from_value(cls, value: dict[str, Any]) -> VerificationRequest:
        canonical = canonical_json_bytes(value)
        return cls(canonical, hashlib.sha256(canonical).hexdigest())

    @property
    def value(self) -> dict[str, Any]:
        value = json.loads(self._canonical_value)
        assert isinstance(value, dict)
        return value


@dataclass(frozen=True, slots=True)
class VerifyIdentity:
    _canonical_contract: bytes
    verify_key: str
    _prompt_bytes: bytes

    @classmethod
    def from_contract(
        cls, contract: dict[str, Any], *, prompt_bytes: bytes
    ) -> VerifyIdentity:
        canonical = canonical_json_bytes(contract)
        return cls(canonical, hashlib.sha256(canonical).hexdigest(), prompt_bytes)

    @property
    def contract(self) -> dict[str, Any]:
        value = json.loads(self._canonical_contract)
        assert isinstance(value, dict)
        return value

    @property
    def prompt_bytes(self) -> bytes:
        return self._prompt_bytes


@dataclass(frozen=True, slots=True)
class VerificationWork:
    """One cache-independent verifier request and its complete identity."""

    packet: dict[str, Any]
    claim: VerificationClaim
    request: VerificationRequest
    identity: VerifyIdentity
    base_search_epoch: str
    effective_search_epoch: str


def verification_prompt_bytes() -> bytes:
    prompt = (
        resources.files("backstitch") / "prompts" / VERIFY_PROMPT_RESOURCE
    ).read_bytes()
    if not prompt.strip():
        raise VerificationContractError("verification prompt is blank")
    return prompt


def verification_prompt_descriptor(
    *, prompt_bytes: bytes | None = None
) -> PromptDescriptor:
    prompt = verification_prompt_bytes() if prompt_bytes is None else prompt_bytes
    if not prompt.strip():
        raise VerificationContractError("verification prompt is blank")
    return PromptDescriptor(
        id=VERIFY_PROMPT_ID,
        version=VERIFY_PROMPT_VERSION,
        sha256=hashlib.sha256(prompt).hexdigest(),
    )
