"""Canonical semantic packet identity and prompt-boundary projections.

Owns semantic packet identity, prompt descriptors, and model-visible projection.

Spec: docs/specs/06-semantic-gates.md [SEM-3]
Spec: docs/specs/05-backstitch-invariants.md [INV-11]
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from importlib import resources
from typing import Any, Literal, cast

from backstitch.canonical import canonical_json_bytes, lf_end_line

SemanticPacketKind = Literal["section", "invariant"]
MAX_SNIPPET_LINES = 120
MAX_OWNERS_PER_PACKET = 8
MAX_SECTION_LINES = 100
MAX_INVARIANT_TARGETS_PER_PACKET = 8
MAX_BINDING_TESTS_PER_PACKET = 8


@dataclass(frozen=True, slots=True)
class PromptDescriptor:
    id: str
    version: int
    sha256: str


_PROMPTS: dict[SemanticPacketKind, tuple[str, int, str]] = {
    "section": (
        "backstitch.section-analysis",
        3,
        "backstitch_style_analysis.md",
    ),
    "invariant": (
        "backstitch.invariant-analysis",
        3,
        "invariant_binding_analysis.md",
    ),
}

SECTION_PROJECTION_FIELDS = (
    "packet_id",
    "kind",
    "spec_path",
    "section_id",
    "title",
    "section_text",
    "section_start_line",
    "owners",
    "tests",
    "issues",
    "packet_warnings",
)
INVARIANT_PROJECTION_FIELDS = (
    "packet_id",
    "kind",
    "invariant_id",
    "tier",
    "statement",
    "declaration",
    "targets",
    "binding_tests",
    "issues",
    "packet_warnings",
)
SNIPPET_FIELDS = ("path", "symbol", "start_line", "snippet")
DECLARATION_FIELDS = (
    "kind",
    "path",
    "line",
    "symbol",
    "section_id",
    "start_line",
    "end_line",
    "excerpt",
)
ISSUE_FIELDS = (
    "code",
    "path",
    "line",
    "message",
    "section_id",
    "symbol",
    "short_code",
    "context",
    "default_severity",
    "invariant_id",
)
PACKET_V3_PROJECTION_FIELDS = (
    "packet_id",
    "kind",
    "obligation_id",
    "requirement",
    "declared_evidence",
    "counterevidence",
    "trace_summary",
    "evidence_regions",
    "issues",
    "packet_warnings",
)


def prompt_instruction_bytes(kind: SemanticPacketKind) -> bytes:
    """Load the exact code-owned instruction bytes for one packet kind."""

    try:
        _, _, filename = _PROMPTS[kind]
    except KeyError:
        raise ValueError(f"unknown semantic packet kind: {kind!r}") from None
    instruction_bytes = (
        resources.files("backstitch") / "prompts" / filename
    ).read_bytes()
    if not instruction_bytes.strip():
        raise ValueError(f"semantic prompt for {kind!r} is blank")
    return instruction_bytes


def prompt_descriptor(
    kind: SemanticPacketKind,
    *,
    instruction_bytes: bytes | None = None,
) -> PromptDescriptor:
    """Return the stable descriptor for the exact code-owned prompt bytes."""

    try:
        prompt_id, version, _ = _PROMPTS[kind]
    except KeyError:
        raise ValueError(f"unknown semantic packet kind: {kind!r}") from None
    if instruction_bytes is None:
        instruction_bytes = prompt_instruction_bytes(kind)
    if not instruction_bytes.strip():
        raise ValueError(f"semantic prompt for {kind!r} is blank")
    return PromptDescriptor(
        id=prompt_id,
        version=version,
        sha256=hashlib.sha256(instruction_bytes).hexdigest(),
    )


def model_request_bytes(
    packet: dict[str, Any],
    *,
    instruction_bytes: bytes | None = None,
) -> bytes:
    """Build the exact prompt bytes from kind-owned instructions and projection."""

    kind = packet.get("kind")
    if kind not in _PROMPTS:
        raise ValueError(f"unknown semantic packet kind: {kind!r}")
    prompt = (
        prompt_instruction_bytes(kind)
        if instruction_bytes is None
        else instruction_bytes
    )
    if not prompt.strip():
        raise ValueError(f"semantic prompt for {kind!r} is blank")
    return prompt + b"\n\n" + canonical_json_bytes(semantic_packet_projection(packet))


def _closed_record(record: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: record[field] for field in fields}


def _with_derived_end_line(record: dict[str, Any]) -> dict[str, Any]:
    projection = _closed_record(record, SNIPPET_FIELDS)
    projection["end_line"] = lf_end_line(record["start_line"], record["snippet"])
    return projection


def _maximal_snippet_records(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    maximal: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        end = lf_end_line(record["start_line"], record["snippet"])
        if end is None:
            maximal.append(record)
            continue
        start = record["start_line"]
        contained = False
        for other_index, other in enumerate(records):
            if index == other_index or record["path"] != other["path"]:
                continue
            other_end = lf_end_line(other["start_line"], other["snippet"])
            if other_end is None:
                continue
            other_start = other["start_line"]
            if (
                other_start <= start
                and end <= other_end
                and (other_start < start or end < other_end or other_index < index)
            ):
                contained = True
                break
        if not contained:
            maximal.append(record)
    return maximal


def _evidence_region(
    role: str,
    path: str,
    start_line: int,
    text: str,
) -> dict[str, object] | None:
    end_line = lf_end_line(start_line, text)
    if end_line is None:
        return None
    return {
        "role": role,
        "path": path,
        "start_line": start_line,
        "end_line": end_line,
    }


def _maximal_evidence_regions(
    regions: list[dict[str, object] | None],
) -> list[dict[str, object]]:
    concrete = [region for region in regions if region is not None]
    maximal: list[dict[str, object]] = []
    for index, region in enumerate(concrete):
        start = cast(int, region["start_line"])
        end = cast(int, region["end_line"])
        contained = False
        for other_index, other in enumerate(concrete):
            if index == other_index:
                continue
            if region["role"] != other["role"] or region["path"] != other["path"]:
                continue
            other_start = cast(int, other["start_line"])
            other_end = cast(int, other["end_line"])
            if (
                other_start <= start
                and end <= other_end
                and (other_start < start or end < other_end or other_index < index)
            ):
                contained = True
                break
        if not contained:
            maximal.append(region)
    return maximal


def semantic_packet_projection(packet: dict[str, Any]) -> dict[str, Any]:
    """Build the closed model-visible projection for a validated packet."""

    if packet.get("schema_version") == 3:
        return {
            "packet_contract_version": 3,
            **_closed_record(packet, PACKET_V3_PROJECTION_FIELDS),
        }

    kind = packet["kind"]
    if kind == "section":
        projection = _closed_record(packet, SECTION_PROJECTION_FIELDS)
        model_owners = _maximal_snippet_records(packet["owners"])
        section_end_line = lf_end_line(
            packet["section_start_line"], packet["section_text"]
        )
        projection["section_end_line"] = (
            section_end_line
            if section_end_line is not None
            else packet["section_start_line"] - 1
        )
        projection["owners"] = [_with_derived_end_line(item) for item in model_owners]
        evidence_regions = [
            _evidence_region(
                "requirement",
                packet["spec_path"],
                packet["section_start_line"],
                packet["section_text"],
            ),
            *(
                _evidence_region(
                    "implementation",
                    item["path"],
                    item["start_line"],
                    item["snippet"],
                )
                for item in model_owners
            ),
        ]
    elif kind == "invariant":
        projection = _closed_record(packet, INVARIANT_PROJECTION_FIELDS)
        model_targets = _maximal_snippet_records(packet["targets"])
        model_binding_tests = _maximal_snippet_records(packet["binding_tests"])
        projection["declaration"] = _closed_record(
            packet["declaration"], DECLARATION_FIELDS
        )
        projection["targets"] = [_with_derived_end_line(item) for item in model_targets]
        projection["binding_tests"] = [
            _with_derived_end_line(item) for item in model_binding_tests
        ]
        declaration = packet["declaration"]
        evidence_regions = [
            _evidence_region(
                "requirement",
                declaration["path"],
                declaration["start_line"],
                declaration["excerpt"],
            ),
            *(
                _evidence_region(
                    "implementation",
                    item["path"],
                    item["start_line"],
                    item["snippet"],
                )
                for item in model_targets
            ),
            *(
                _evidence_region(
                    "test",
                    item["path"],
                    item["start_line"],
                    item["snippet"],
                )
                for item in model_binding_tests
            ),
        ]
    else:
        raise ValueError(f"unknown semantic packet kind: {kind!r}")
    projection["evidence_regions"] = _maximal_evidence_regions(evidence_regions)
    projection["issues"] = [
        _closed_record(item, ISSUE_FIELDS) for item in packet["issues"]
    ]
    return projection


def semantic_packet_hash(packet: dict[str, Any]) -> str:
    """Hash the exact model-visible semantic projection."""

    return hashlib.sha256(
        canonical_json_bytes(semantic_packet_projection(packet))
    ).hexdigest()
