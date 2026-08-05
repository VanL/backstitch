"""Closed model-output normalization and packet-local evidence reconstruction.

Owns closed model rows, canonical results, and evidence reconstruction.

Spec: docs/specs/06-semantic-gates.md [SEM-5]
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Literal

from backstitch.canonical import canonical_json_bytes, lf_split
from backstitch.semantic_packets import semantic_packet_projection

EvidenceRole = Literal["requirement", "implementation", "test", "counterevidence"]

SECTION_CLASSIFICATIONS = frozenset(
    {
        "ok",
        "confirmed_mismatch",
        "probable_mismatch",
        "missing_trace",
        "ambiguous",
    }
)
INVARIANT_CLASSIFICATIONS = frozenset(
    {
        "ok",
        "weak_binding",
        "confirmed_mismatch",
        "probable_mismatch",
        "ambiguous",
    }
)
SUPPRESSION_CLASSIFICATIONS = frozenset(
    {
        "ok",
        "rationale_insufficient",
        "scope_overbroad",
        "risk_unaddressed",
        "ambiguous",
    }
)
MODEL_RESULT_FIELDS = frozenset(
    {
        "packet_id",
        "classification",
        "confidence",
        "rationale",
        "summary",
        "evidence",
    }
)
MODEL_EVIDENCE_FIELDS = frozenset({"role", "path", "start_line", "end_line"})


class SemanticResultError(ValueError):
    """Untrusted model output violated the semantic result contract."""


@dataclass(frozen=True, slots=True)
class CanonicalEvidence:
    role: EvidenceRole
    path: str
    start_line: int
    end_line: int
    excerpt: str
    excerpt_sha256: str

    def to_row(self) -> dict[str, object]:
        return {
            "role": self.role,
            "path": self.path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "excerpt": self.excerpt,
            "excerpt_sha256": self.excerpt_sha256,
        }


@dataclass(frozen=True, slots=True)
class CanonicalSemanticResult:
    packet_id: str
    kind: Literal["section", "invariant", "suppression"]
    packet_hash: str
    analysis_key: str
    classification: str
    confidence: float | None
    rationale: str
    summary: str
    evidence: tuple[CanonicalEvidence, ...]
    verification_state: Literal["evidence_bound"] = "evidence_bound"
    content_hash: str | None = None

    def to_row(self) -> dict[str, object]:
        row: dict[str, object] = {
            "schema_version": 3 if self.kind == "suppression" else 2,
            "packet_id": self.packet_id,
            "kind": self.kind,
            "packet_hash": self.packet_hash,
            "analysis_key": self.analysis_key,
            "classification": self.classification,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "summary": self.summary,
            "evidence": [item.to_row() for item in self.evidence],
            "verification_state": self.verification_state,
        }
        if self.content_hash is not None:
            row["content_hash"] = self.content_hash
        return row


@dataclass(frozen=True, slots=True)
class _ShownRegion:
    role: EvidenceRole
    path: str
    start_line: int
    lines: tuple[str, ...]

    @property
    def end_line(self) -> int:
        return self.start_line + len(self.lines) - 1

    def excerpt(self) -> str:
        return "\n".join(self.lines)


def _region(
    role: EvidenceRole,
    path: object,
    start_line: object,
    text: object,
) -> _ShownRegion | None:
    lines = lf_split(text) if isinstance(text, str) else ()
    if isinstance(text, str) and text.endswith("\n"):
        lines = (*lines, "")
    if (
        not isinstance(path, str)
        or not path.strip()
        or isinstance(start_line, bool)
        or not isinstance(start_line, int)
        or start_line < 1
        or not isinstance(text, str)
        or not lines
        or not text.strip()
    ):
        return None
    return _ShownRegion(role, path, start_line, lines)


def _append_region(
    regions: list[_ShownRegion],
    role: EvidenceRole,
    row: dict[str, Any],
    text_key: str,
) -> None:
    shown = _region(role, row["path"], row["start_line"], row[text_key])
    if shown is not None:
        regions.append(shown)


def _source_packet_regions(projection: dict[str, Any]) -> tuple[_ShownRegion, ...]:
    regions: list[_ShownRegion] = []
    _append_region(regions, "requirement", projection["requirement"], "text")
    if projection["packet_contract_version"] == 3:
        for item in projection["declared_evidence"]:
            _append_region(regions, item["role"], item, "snippet")
    for item in projection["counterevidence"]:
        _append_region(regions, "counterevidence", item, "snippet")
    return tuple(regions)


def _legacy_section_regions(projection: dict[str, Any]) -> tuple[_ShownRegion, ...]:
    regions: list[_ShownRegion] = []
    requirement = _region(
        "requirement",
        projection["spec_path"],
        projection["section_start_line"],
        projection["section_text"],
    )
    if requirement is not None:
        regions.append(requirement)
    for owner in projection["owners"]:
        _append_region(regions, "implementation", owner, "snippet")
    return tuple(regions)


def _legacy_invariant_regions(projection: dict[str, Any]) -> tuple[_ShownRegion, ...]:
    regions: list[_ShownRegion] = []
    _append_region(regions, "requirement", projection["declaration"], "excerpt")
    for item in projection["targets"]:
        _append_region(regions, "implementation", item, "snippet")
    for item in projection["binding_tests"]:
        _append_region(regions, "test", item, "snippet")
    return tuple(regions)


def _shown_regions(packet: dict[str, Any]) -> tuple[_ShownRegion, ...]:
    projection = semantic_packet_projection(packet)
    if projection.get("packet_contract_version") in {3, 4}:
        return _source_packet_regions(projection)
    if projection["kind"] == "section":
        return _legacy_section_regions(projection)
    return _legacy_invariant_regions(projection)


def _normalize_evidence(
    packet: dict[str, Any], evidence_raw: object
) -> tuple[CanonicalEvidence, ...]:
    if not isinstance(evidence_raw, list):
        raise SemanticResultError("missing or invalid `evidence`; expected a list")
    regions = _shown_regions(packet)
    seen: set[tuple[object, ...]] = set()
    normalized: list[CanonicalEvidence] = []
    for item in evidence_raw:
        if not isinstance(item, dict) or set(item) != MODEL_EVIDENCE_FIELDS:
            raise SemanticResultError(
                "invalid evidence item; expected exactly role, path, start_line, end_line"
            )
        role = item["role"]
        path = item["path"]
        start_line = item["start_line"]
        end_line = item["end_line"]
        if (
            role not in ("requirement", "implementation", "test", "counterevidence")
            or not isinstance(path, str)
            or not path.strip()
            or isinstance(start_line, bool)
            or not isinstance(start_line, int)
            or isinstance(end_line, bool)
            or not isinstance(end_line, int)
            or start_line < 1
            or end_line < start_line
        ):
            raise SemanticResultError("invalid evidence role, path, or span")
        identity = (role, path, start_line, end_line)
        if identity in seen:
            raise SemanticResultError("duplicate evidence item")
        seen.add(identity)
        matches = [
            region
            for region in regions
            if region.role == role
            and region.path == path
            and region.start_line == start_line
            and region.end_line == end_line
        ]
        if len(matches) != 1:
            raise SemanticResultError(
                "evidence span must match exactly one shown packet region"
            )
        excerpt = matches[0].excerpt()
        normalized.append(
            CanonicalEvidence(
                role=role,
                path=path,
                start_line=start_line,
                end_line=end_line,
                excerpt=excerpt,
                excerpt_sha256=hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
            )
        )
    normalized.sort(
        key=lambda item: (
            item.role,
            item.path,
            item.start_line,
            item.end_line,
            item.excerpt_sha256,
        )
    )
    return tuple(normalized)


def normalize_packet_evidence(
    packet: dict[str, Any], evidence_raw: object
) -> tuple[CanonicalEvidence, ...]:
    """Reconstruct untrusted model coordinates from one packet projection."""

    return _normalize_evidence(packet, evidence_raw)


def required_evidence_roles(kind: str, classification: str) -> frozenset[EvidenceRole]:  # noqa: C901 approved [SC-17.1] RUFF-SUP-102 exception
    """Return the minimum canonical evidence roles for one result variant."""

    if kind == "section":
        if classification in ("confirmed_mismatch", "probable_mismatch"):
            return frozenset({"requirement", "implementation"})
        if classification in ("missing_trace", "ambiguous"):
            return frozenset({"requirement"})
        if classification == "ok":
            return frozenset()
    elif kind == "invariant":
        if classification == "ok":
            return frozenset({"test"})
        if classification in (
            "weak_binding",
            "confirmed_mismatch",
            "probable_mismatch",
        ):
            return frozenset({"requirement", "implementation"})
        if classification == "ambiguous":
            return frozenset({"requirement"})
    elif kind == "suppression":
        if classification in ("ok", "rationale_insufficient", "ambiguous"):
            return frozenset({"requirement"})
        if classification in ("scope_overbroad", "risk_unaddressed"):
            return frozenset({"requirement", "counterevidence"})
    raise ValueError(f"invalid semantic result variant: {kind}/{classification}")


def normalize_model_result(  # noqa: C901 approved [SC-17.1] RUFF-SUP-101 exception
    packet: dict[str, Any],
    response: object,
    *,
    analysis_key: str,
) -> CanonicalSemanticResult:
    """Validate one closed model response and add trusted result metadata."""

    if not isinstance(response, dict) or set(response) != MODEL_RESULT_FIELDS:
        raise SemanticResultError("model response does not match the closed schema")
    if response["packet_id"] != packet["packet_id"]:
        raise SemanticResultError("model response packet_id does not match the packet")
    kind = packet["kind"]
    if (kind == "suppression") != (packet.get("schema_version") == 4):
        raise SemanticResultError(
            "suppression kind and packet contract version must agree"
        )
    classifications = {
        "section": SECTION_CLASSIFICATIONS,
        "invariant": INVARIANT_CLASSIFICATIONS,
        "suppression": SUPPRESSION_CLASSIFICATIONS,
    }.get(kind)
    if classifications is None:
        raise SemanticResultError("packet kind is invalid for semantic analysis")
    classification = response["classification"]
    if classification not in classifications:
        raise SemanticResultError("classification is invalid for the packet kind")
    confidence = response["confidence"]
    if confidence is not None and (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0 <= confidence <= 1
    ):
        raise SemanticResultError("confidence must be null or a number from 0 to 1")
    rationale = response["rationale"]
    summary = response["summary"]
    if not isinstance(rationale, str):
        raise SemanticResultError("rationale must be a string")
    if not isinstance(summary, str) or not summary.strip():
        raise SemanticResultError("summary must be a nonblank string")
    if confidence is None and not rationale.strip():
        raise SemanticResultError("confidence or a nonblank rationale is required")
    evidence = normalize_packet_evidence(packet, response["evidence"])
    roles = {item.role for item in evidence}
    required = required_evidence_roles(kind, classification)
    if kind == "invariant" and classification == "ok" and "test" not in roles:
        if {"requirement", "implementation"}.issubset(roles):
            classification = "weak_binding"
            required = frozenset({"requirement", "implementation"})
        else:
            raise SemanticResultError(
                "invariant ok requires test evidence, or requirement and implementation"
            )
    if not required.issubset(roles):
        missing = ", ".join(sorted(required - roles))
        raise SemanticResultError(f"missing required evidence roles: {missing}")
    result = CanonicalSemanticResult(
        packet_id=packet["packet_id"],
        kind=kind,
        packet_hash=packet["packet_hash"],
        analysis_key=analysis_key,
        classification=classification,
        confidence=float(confidence) if confidence is not None else None,
        rationale=rationale,
        summary=summary,
        evidence=evidence,
        content_hash=(
            packet.get("content_hash") if packet.get("schema_version") != 3 else None
        ),
    )
    return result


def revalidate_canonical_result(
    packet: dict[str, Any],
    row: object,
    *,
    analysis_key: str,
) -> CanonicalSemanticResult:
    """Rebuild and byte-compare a cached canonical result against its packet."""

    if not isinstance(row, dict):
        raise SemanticResultError("canonical result is not an object")
    try:
        response = {
            "packet_id": row["packet_id"],
            "classification": row["classification"],
            "confidence": row["confidence"],
            "rationale": row["rationale"],
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
        raise SemanticResultError(
            "canonical result is missing required fields"
        ) from None
    rebuilt = normalize_model_result(packet, response, analysis_key=analysis_key)
    if canonical_json_bytes(row) != canonical_json_bytes(rebuilt.to_row()):
        raise SemanticResultError(
            "canonical result does not match trusted packet reconstruction"
        )
    return rebuilt
