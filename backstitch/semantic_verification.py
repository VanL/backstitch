"""Blinded adversarial verification contracts and deterministic aggregation.

Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-3], [EVC-3.1],
[EVC-5]
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from importlib import resources
from typing import Any, Literal

from backstitch.canonical import canonical_json_bytes
from backstitch.grammar import is_sha256_hex
from backstitch.semantic_evidence import (
    CanonicalEvidence,
    SemanticResultError,
    normalize_packet_evidence,
)
from backstitch.semantic_identity import ProviderIdentity, RequestIdentity
from backstitch.semantic_packets import (
    PromptDescriptor,
    semantic_packet_projection,
)

VerifierVerdict = Literal["support", "refute", "indeterminate"]
AggregateState = Literal[
    "independently_verified", "disputed", "verification_indeterminate"
]

VERIFY_CONTRACT_VERSION = 3
VERIFY_PROMPT_ID = "backstitch.adversarial-verification"
VERIFY_PROMPT_VERSION = 1
VERIFY_PROMPT_RESOURCE = "adversarial_verification.md"

_RESPONSE_FIELDS = frozenset(
    {"packet_id", "claim_hash", "verdict", "support_score", "summary", "evidence"}
)
_CLASSIFICATION_CODES = {
    "confirmed_mismatch": "SEMANTIC_CONFIRMED_MISMATCH",
    "probable_mismatch": "SEMANTIC_PROBABLE_MISMATCH",
    "missing_trace": "SEMANTIC_MISSING_TRACE",
    "weak_binding": "SEMANTIC_WEAK_BINDING",
    "ambiguous": "SEMANTIC_AMBIGUOUS",
    "rationale_insufficient": "SEMANTIC_SUPPRESSION_RATIONALE_INSUFFICIENT",
    "scope_overbroad": "SEMANTIC_SUPPRESSION_SCOPE_OVERBROAD",
    "risk_unaddressed": "SEMANTIC_SUPPRESSION_RISK_UNADDRESSED",
}


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
class CanonicalVerificationResult:
    packet_id: str
    packet_hash: str
    claim_hash: str
    verifier_packet_hash: str
    verify_key: str
    verdict: VerifierVerdict
    support_score: float
    summary: str
    evidence: tuple[CanonicalEvidence, ...]

    def to_row(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "packet_id": self.packet_id,
            "packet_hash": self.packet_hash,
            "claim_hash": self.claim_hash,
            "verifier_packet_hash": self.verifier_packet_hash,
            "verify_key": self.verify_key,
            "verdict": self.verdict,
            "support_score": self.support_score,
            "summary": self.summary,
            "evidence": [item.to_row() for item in self.evidence],
        }


@dataclass(frozen=True, slots=True)
class VerificationAggregate:
    event: dict[str, Any]
    aggregate_state: AggregateState
    context: str


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


def _field(value: object, name: str) -> object:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _canonical_claim_evidence(
    packet: dict[str, Any], value: object
) -> list[dict[str, object]]:
    if not isinstance(value, (list, tuple)):
        raise VerificationContractError("analyzer evidence must be a sequence")
    coordinates: list[dict[str, object]] = []
    supplied_hashes: list[str] = []
    for item in value:
        role = _field(item, "role")
        path = _field(item, "path")
        start_line = _field(item, "start_line")
        end_line = _field(item, "end_line")
        excerpt_hash = _field(item, "excerpt_sha256")
        if (
            role not in {"requirement", "implementation", "test", "counterevidence"}
            or not isinstance(path, str)
            or not path.strip()
            or isinstance(start_line, bool)
            or not isinstance(start_line, int)
            or isinstance(end_line, bool)
            or not isinstance(end_line, int)
            or start_line < 1
            or end_line < start_line
            or not is_sha256_hex(excerpt_hash)
        ):
            raise VerificationContractError("analyzer claim evidence is invalid")
        coordinates.append(
            {
                "role": role,
                "path": path,
                "start_line": start_line,
                "end_line": end_line,
            }
        )
        supplied_hashes.append(excerpt_hash)
    try:
        reconstructed = normalize_packet_evidence(packet, coordinates)
    except SemanticResultError as exc:
        raise VerificationContractError(
            f"analyzer claim evidence is not packet-bound: {exc}"
        ) from None
    rows = [
        {
            "role": item.role,
            "path": item.path,
            "start_line": item.start_line,
            "end_line": item.end_line,
            "excerpt_sha256": item.excerpt_sha256,
        }
        for item in reconstructed
    ]
    if [item["excerpt_sha256"] for item in rows] != supplied_hashes:
        raise VerificationContractError(
            "analyzer claim evidence hash does not match packet reconstruction"
        )
    if rows != sorted(
        rows,
        key=lambda item: (
            item["role"],
            item["path"],
            item["start_line"],
            item["end_line"],
            item["excerpt_sha256"],
        ),
    ) or len({canonical_json_bytes(item) for item in rows}) != len(rows):
        raise VerificationContractError("analyzer claim evidence is not canonical")
    return rows


def derive_verification_claim(
    packet: dict[str, Any], analyzer_result: object
) -> VerificationClaim:
    """Derive the reason-free claim projection from one normalized finding."""

    classification = _field(analyzer_result, "classification")
    code = (
        _CLASSIFICATION_CODES.get(classification)
        if isinstance(classification, str)
        else None
    )
    if code is None:
        raise VerificationContractError("only analyzer findings create verifier claims")
    packet_id = _field(analyzer_result, "packet_id")
    packet_hash = _field(analyzer_result, "packet_hash")
    kind = _field(analyzer_result, "kind")
    statement = _field(analyzer_result, "summary")
    if (
        packet_id != packet.get("packet_id")
        or packet_hash != packet.get("packet_hash")
        or kind != packet.get("kind")
        or not isinstance(statement, str)
        or not statement.strip()
    ):
        raise VerificationContractError("analyzer finding does not match its packet")
    claim = {
        "packet_id": packet_id,
        "packet_hash": packet_hash,
        "obligation_id": packet.get("obligation_id", packet_id),
        "kind": kind,
        "code": code,
        "classification": classification,
        "statement": statement,
        "evidence": _canonical_claim_evidence(
            packet, _field(analyzer_result, "evidence")
        ),
    }
    return VerificationClaim.from_value(claim)


def build_verification_request(
    packet: dict[str, Any], claim: VerificationClaim
) -> VerificationRequest:
    value = {
        "verify_contract_version": VERIFY_CONTRACT_VERSION,
        "packet": semantic_packet_projection(packet),
        "claim": claim.value,
    }
    return VerificationRequest.from_value(value)


def verifier_request_bytes(
    request: VerificationRequest, *, prompt_bytes: bytes | None = None
) -> bytes:
    prompt = verification_prompt_bytes() if prompt_bytes is None else prompt_bytes
    if not prompt.strip():
        raise VerificationContractError("verification prompt is blank")
    separator = b"\n" if prompt.endswith(b"\n") else b"\n\n"
    return prompt + separator + canonical_json_bytes(request.value)


def build_verify_identity(
    request: VerificationRequest,
    claim: VerificationClaim,
    provider: ProviderIdentity,
    request_identity: RequestIdentity,
    *,
    base_search_epoch: str,
    effective_search_epoch: str | None = None,
) -> VerifyIdentity:
    if not isinstance(base_search_epoch, str) or not base_search_epoch.strip():
        raise VerificationContractError("base_search_epoch must be nonblank")
    effective = (
        base_search_epoch if effective_search_epoch is None else effective_search_epoch
    )
    if not isinstance(effective, str) or not effective.strip():
        raise VerificationContractError("effective_search_epoch must be nonblank")
    prompt_bytes = verification_prompt_bytes()
    contract = {
        "verify_contract_version": VERIFY_CONTRACT_VERSION,
        "verifier_packet_hash": request.verifier_packet_hash,
        "claim_hash": claim.claim_hash,
        "prompt": asdict(verification_prompt_descriptor(prompt_bytes=prompt_bytes)),
        "provider": asdict(provider),
        "request": asdict(request_identity),
        "base_search_epoch": base_search_epoch,
        "effective_search_epoch": effective,
    }
    return VerifyIdentity.from_contract(contract, prompt_bytes=prompt_bytes)


def validate_verification_links(
    packet: dict[str, Any],
    claim: VerificationClaim,
    request: VerificationRequest,
    identity: VerifyIdentity,
) -> None:
    """Recompute the complete provider-independent verifier work graph."""

    claim_value = claim.value
    request_value = request.value
    contract = identity.contract
    if set(claim_value) != {
        "packet_id",
        "packet_hash",
        "obligation_id",
        "kind",
        "code",
        "classification",
        "statement",
        "evidence",
    }:
        raise VerificationContractError("verifier claim has invalid closed shape")
    if set(request_value) != {"verify_contract_version", "packet", "claim"}:
        raise VerificationContractError("verifier request has invalid closed shape")
    if set(contract) != {
        "verify_contract_version",
        "verifier_packet_hash",
        "claim_hash",
        "prompt",
        "provider",
        "request",
        "base_search_epoch",
        "effective_search_epoch",
    }:
        raise VerificationContractError("verifier identity has invalid closed shape")
    classification = claim_value.get("classification")
    expected_code = (
        _CLASSIFICATION_CODES.get(classification)
        if isinstance(classification, str)
        else None
    )
    if (
        expected_code is None
        or claim_value.get("code") != expected_code
        or claim_value.get("packet_id") != packet.get("packet_id")
        or claim_value.get("packet_hash") != packet.get("packet_hash")
        or claim_value.get("obligation_id")
        != packet.get("obligation_id", packet.get("packet_id"))
        or claim_value.get("kind") != packet.get("kind")
        or not isinstance(claim_value.get("statement"), str)
        or not str(claim_value["statement"]).strip()
    ):
        raise VerificationContractError("verifier claim does not match its packet")
    canonical_evidence = _canonical_claim_evidence(packet, claim_value.get("evidence"))
    if claim_value.get("evidence") != canonical_evidence:
        raise VerificationContractError("verifier claim evidence is not canonical")
    if (
        request_value.get("verify_contract_version") != VERIFY_CONTRACT_VERSION
        or contract.get("verify_contract_version") != VERIFY_CONTRACT_VERSION
        or contract.get("prompt")
        != asdict(verification_prompt_descriptor(prompt_bytes=identity.prompt_bytes))
    ):
        raise VerificationContractError("verifier contract descriptor is invalid")
    request_contract = contract.get("request")
    if not isinstance(request_contract, dict):
        raise VerificationContractError("verifier request identity is invalid")
    try:
        normalized_request = asdict(RequestIdentity(**request_contract))
    except (TypeError, ValueError):
        raise VerificationContractError(
            "verifier request identity is invalid"
        ) from None
    if request_contract != normalized_request:
        raise VerificationContractError("verifier request identity is not canonical")
    for field in ("base_search_epoch", "effective_search_epoch"):
        value = contract.get(field)
        if not isinstance(value, str) or not value.strip():
            raise VerificationContractError(f"verifier {field} must be nonblank")
    if (
        claim.claim_hash
        != hashlib.sha256(canonical_json_bytes(claim_value)).hexdigest()
    ):
        raise VerificationContractError("claim hash does not recompute")
    if (
        request.verifier_packet_hash
        != hashlib.sha256(canonical_json_bytes(request_value)).hexdigest()
    ):
        raise VerificationContractError("verifier packet hash does not recompute")
    if (
        identity.verify_key
        != hashlib.sha256(canonical_json_bytes(contract)).hexdigest()
    ):
        raise VerificationContractError("verify key does not recompute")
    if (
        request_value.get("claim") != claim_value
        or request_value.get("packet") != semantic_packet_projection(packet)
        or contract.get("claim_hash") != claim.claim_hash
        or contract.get("verifier_packet_hash") != request.verifier_packet_hash
    ):
        raise VerificationContractError(
            "verifier claim/request/identity links mismatch"
        )


def normalize_verifier_response(
    packet: dict[str, Any],
    claim: VerificationClaim,
    request: VerificationRequest,
    identity: VerifyIdentity,
    response: object,
) -> CanonicalVerificationResult:
    validate_verification_links(packet, claim, request, identity)
    if not isinstance(response, dict) or set(response) != _RESPONSE_FIELDS:
        raise VerificationContractError(
            "verifier response does not match closed schema"
        )
    if response["packet_id"] != packet.get("packet_id"):
        raise VerificationContractError("verifier packet_id does not match")
    if response["claim_hash"] != claim.claim_hash:
        raise VerificationContractError("verifier claim_hash does not match")
    verdict = response["verdict"]
    if verdict not in {"support", "refute", "indeterminate"}:
        raise VerificationContractError("verifier verdict is invalid")
    score = response["support_score"]
    if (
        isinstance(score, bool)
        or not isinstance(score, (int, float))
        or not math.isfinite(score)
        or not 0 <= score <= 1
    ):
        raise VerificationContractError("verifier support_score is invalid")
    summary = response["summary"]
    if not isinstance(summary, str) or not summary.strip():
        raise VerificationContractError("verifier summary must be nonblank")
    try:
        evidence = normalize_packet_evidence(packet, response["evidence"])
    except SemanticResultError as exc:
        raise VerificationContractError(str(exc)) from None
    if verdict in {"support", "refute"} and not evidence:
        raise VerificationContractError(f"verifier {verdict} requires bound evidence")
    return CanonicalVerificationResult(
        packet_id=packet["packet_id"],
        packet_hash=packet["packet_hash"],
        claim_hash=claim.claim_hash,
        verifier_packet_hash=request.verifier_packet_hash,
        verify_key=identity.verify_key,
        verdict=verdict,
        support_score=float(score),
        summary=summary,
        evidence=evidence,
    )


def verification_response_schema(
    packet: dict[str, Any], claim: VerificationClaim
) -> dict[str, object]:
    variants = []
    for region in packet["evidence_regions"]:
        variants.append(
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    field: {"const": region[field]}
                    for field in ("role", "path", "start_line", "end_line")
                },
                "required": ["role", "path", "start_line", "end_line"],
            }
        )
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "packet_id": {"const": packet["packet_id"]},
            "claim_hash": {"const": claim.claim_hash},
            "verdict": {"enum": ["support", "refute", "indeterminate"]},
            "support_score": {"type": "number", "minimum": 0, "maximum": 1},
            "summary": {"type": "string", "minLength": 1},
            "evidence": {
                "type": "array",
                "items": {"oneOf": variants},
                "uniqueItems": True,
            },
        },
        "required": [
            "packet_id",
            "claim_hash",
            "verdict",
            "support_score",
            "summary",
            "evidence",
        ],
        "allOf": [
            {
                "if": {"properties": {"verdict": {"enum": ["support", "refute"]}}},
                "then": {"properties": {"evidence": {"minItems": 1}}},
            }
        ],
    }


def verification_response_schema_from_prompt(prompt: str) -> dict[str, object]:
    """Build the provider constraint from one exact verifier prompt."""

    try:
        raw = prompt.rsplit("\n\n", 1)[1]
        value = json.loads(raw)
    except (IndexError, json.JSONDecodeError) as exc:
        raise VerificationContractError(
            "verification prompt has no canonical request"
        ) from exc
    if not isinstance(value, dict) or set(value) != {
        "verify_contract_version",
        "packet",
        "claim",
    }:
        raise VerificationContractError("verification prompt request is invalid")
    packet = value["packet"]
    claim_value = value["claim"]
    if not isinstance(packet, dict) or not isinstance(claim_value, dict):
        raise VerificationContractError("verification prompt projections are invalid")
    claim = VerificationClaim.from_value(claim_value)
    return verification_response_schema(packet, claim)


def aggregate_verification_results(
    packet: dict[str, Any],
    claim: VerificationClaim,
    request: VerificationRequest,
    *,
    required_epochs: Sequence[tuple[str, str]],
    identities: Sequence[VerifyIdentity],
    results: Sequence[CanonicalVerificationResult],
    minimum_support_score: float,
) -> VerificationAggregate:
    if (
        isinstance(minimum_support_score, bool)
        or not isinstance(minimum_support_score, (int, float))
        or not math.isfinite(minimum_support_score)
        or not 0 <= minimum_support_score <= 1
    ):
        raise VerificationContractError("minimum_support_score is invalid")
    if (
        not required_epochs
        or len(required_epochs) != len(results)
        or len(identities) != len(results)
    ):
        raise VerificationContractError("verification epoch/result count mismatch")
    epoch_rows = [
        {"base_search_epoch": base, "effective_search_epoch": effective}
        for base, effective in required_epochs
    ]
    if any(
        not isinstance(value, str) or not value.strip()
        for pair in required_epochs
        for value in pair
    ) or len(set(required_epochs)) != len(required_epochs):
        raise VerificationContractError("required verification epochs are invalid")
    result_rows = []
    for (base, effective), identity, result in zip(
        required_epochs, identities, results, strict=True
    ):
        contract = identity.contract
        if (
            result.packet_id != packet["packet_id"]
            or result.packet_hash != packet["packet_hash"]
            or result.claim_hash != claim.claim_hash
            or result.verifier_packet_hash != request.verifier_packet_hash
            or result.verify_key != identity.verify_key
            or contract.get("base_search_epoch") != base
            or contract.get("effective_search_epoch") != effective
        ):
            raise VerificationContractError("verification result identity mismatch")
        result_rows.append(
            {
                "verify_key": result.verify_key,
                "base_search_epoch": base,
                "effective_search_epoch": effective,
                "verdict": result.verdict,
                "support_score": result.support_score,
                "evidence": [item.to_row() for item in result.evidence],
            }
        )
    if any(result.verdict == "refute" for result in results):
        state: AggregateState = "disputed"
        context = "disputed_by_verifier"
    elif all(
        result.verdict == "support" and result.support_score >= minimum_support_score
        for result in results
    ):
        state = "independently_verified"
        context = "independently_verified"
    else:
        state = "verification_indeterminate"
        context = "verification_indeterminate"
    event = {
        "packet_id": packet["packet_id"],
        "packet_hash": packet["packet_hash"],
        "claim_hash": claim.claim_hash,
        "verifier_packet_hash": request.verifier_packet_hash,
        "required_epochs": epoch_rows,
        "results": result_rows,
        "aggregate_state": state,
        "context": context,
    }
    return VerificationAggregate(event, state, context)


def load_canonical_verification_result(
    packet: dict[str, Any],
    claim: VerificationClaim,
    request: VerificationRequest,
    identity: VerifyIdentity,
    row: object,
) -> CanonicalVerificationResult:
    """Rebuild and byte-compare one cached canonical verifier result."""

    if not isinstance(row, dict):
        raise VerificationContractError("cached verification result is not an object")
    try:
        response = {
            "packet_id": row["packet_id"],
            "claim_hash": row["claim_hash"],
            "verdict": row["verdict"],
            "support_score": row["support_score"],
            "summary": row["summary"],
            "evidence": [
                {
                    "role": item["role"],
                    "path": item["path"],
                    "start_line": item["start_line"],
                    "end_line": item["end_line"],
                }
                for item in row["evidence"]
            ],
        }
    except (KeyError, TypeError):
        raise VerificationContractError(
            "cached verification result is missing required fields"
        ) from None
    rebuilt = normalize_verifier_response(packet, claim, request, identity, response)
    if canonical_json_bytes(row) != canonical_json_bytes(rebuilt.to_row()):
        raise VerificationContractError(
            "cached verification result does not match trusted reconstruction"
        )
    return rebuilt


def parse_verifier_response(raw_response: str) -> object:
    try:
        return json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise VerificationContractError(
            f"verifier response is not JSON: {exc}"
        ) from None
