"""Bounded semantic-review packet generation from deterministic results.

Spec: docs/specs/02-backstitch-core.md [SC-6], [SC-7]
Spec: docs/specs/05-backstitch-invariants.md [INV-5], [INV-6]

Packets are the semantic review boundary: the model judges only what a
packet contains and never roams the repository [SC-7]. Generation is
deterministic and never calls ``llm``.
"""

from __future__ import annotations

import dataclasses
import hashlib
from functools import partial
from typing import Any, Literal, cast

from backstitch.canonical import canonical_json_bytes, lf_line_count, lf_split
from backstitch.evidence_discovery import (
    PreparedEvidenceCatalog,
    get_candidate_source,
)
from backstitch.markdown_specs import project_section_packet_requirement
from backstitch.models import SuppressionDecision, issue_sort_key
from backstitch.obligation_runtime import ALGORITHMS, ObligationRuntime
from backstitch.obligations import ObligationRecord, suppression_rule_row
from backstitch.semantic_packets import (
    ISSUE_FIELDS,
    semantic_packet_hash,
)

PacketKind = Literal["section", "invariant", "suppression", "all"]


_SOURCE_ROLE_ORDER = {"implementation": 0, "test": 1, "binding_test": 2}
_MODEL_ROLE_ORDER = {
    "requirement": 0,
    "implementation": 1,
    "test": 2,
    "counterevidence": 3,
}
_CANDIDATE_KIND_ORDER = (
    "implementation_definition",
    "test_definition",
    "static_reference",
    "unresolved_reference",
    "report_issue",
)
_TRACE_STATE_ORDER = (
    "declared",
    "partially_declared",
    "untraced",
    "conflicted",
)
_RELATION_ORDER = (
    "spec_mapping",
    "code_backlink",
    "invariant_declaration",
    "invariant_bind",
    "binding_test",
    "static_import",
    "static_call",
    "static_reference",
    "enclosing_definition",
    "issue_target",
)
_RELATION_INDEX = {value: index for index, value in enumerate(_RELATION_ORDER)}


class SourceAlignedPacketError(ValueError):
    """Current source cannot produce one complete packet artifact."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _receipt_hash(receipt: object) -> str:
    return hashlib.sha256(canonical_json_bytes(receipt)).hexdigest()


def _canonical_span_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return normalized[:-1] if normalized.endswith("\n") else normalized


def _source_row(item: dict[str, object]) -> dict[str, object]:
    relation_kinds = item["relation_kinds"]
    assert isinstance(relation_kinds, list)
    return {
        "source_role": item["role"],
        "receipt_hash": _receipt_hash(item["receipt"]),
        "relation_kinds": list(relation_kinds),
        "reciprocity_state": item["reciprocity_state"],
    }


def _source_order(item: dict[str, object]) -> tuple[object, ...]:
    relations = item["relation_kinds"]
    assert isinstance(relations, list)
    return (
        _SOURCE_ROLE_ORDER[str(item["source_role"])],
        item["receipt_hash"],
        tuple(_RELATION_INDEX[str(value)] for value in relations),
    )


def _unique_rows(
    rows: list[dict[str, object]],
    *,
    order: Any,
) -> list[dict[str, object]]:
    unique: dict[bytes, dict[str, object]] = {}
    for row in rows:
        unique.setdefault(canonical_json_bytes(row), row)
    return sorted(unique.values(), key=order)


def _merge_declared_regions(
    atoms: list[dict[str, object]],
) -> list[dict[str, object]]:
    atoms.sort(
        key=lambda item: (
            _MODEL_ROLE_ORDER[str(item["role"])],
            item["path"],
            item["start_line"],
            -cast(int, item["end_line"]),
            item["symbol"] or "",
        )
    )
    merged: list[dict[str, object]] = []
    symbol_sets: list[set[str | None]] = []
    for atom in atoms:
        container_index = next(
            (
                index
                for index, region in enumerate(merged)
                if region["role"] == atom["role"]
                and region["path"] == atom["path"]
                and cast(int, region["start_line"]) <= cast(int, atom["start_line"])
                and cast(int, atom["end_line"]) <= cast(int, region["end_line"])
            ),
            None,
        )
        atom_sources = atom["sources"]
        assert isinstance(atom_sources, list)
        if container_index is None:
            merged.append(dict(atom))
            symbol_sets.append({atom["symbol"]})  # type: ignore[arg-type]
            continue
        current_sources = merged[container_index]["sources"]
        assert isinstance(current_sources, list)
        merged[container_index]["sources"] = _unique_rows(
            [*current_sources, *atom_sources], order=_source_order
        )
        symbol_sets[container_index].add(atom["symbol"])  # type: ignore[arg-type]
    for region, symbols in zip(merged, symbol_sets, strict=True):
        region["symbol"] = next(iter(symbols)) if len(symbols) == 1 else None
        sources = region["sources"]
        assert isinstance(sources, list)
        region["sources"] = _unique_rows(sources, order=_source_order)
    merged.sort(
        key=lambda item: (
            _MODEL_ROLE_ORDER[str(item["role"])],
            item["path"],
            item["start_line"],
            item["end_line"],
            item["symbol"] or "",
        )
    )
    return merged


def _candidate_source_order(item: dict[str, object]) -> str:
    return str(item["candidate_id"])


def _merge_counterevidence_regions(
    atoms: list[dict[str, object]],
) -> list[dict[str, object]]:
    atoms.sort(
        key=lambda item: (
            item["path"],
            item["start_line"],
            -cast(int, item["end_line"]),
            cast(list[dict[str, object]], item["candidates"])[0]["candidate_id"],
        )
    )
    merged: list[dict[str, object]] = []
    for atom in atoms:
        container = next(
            (
                region
                for region in merged
                if region["path"] == atom["path"]
                and cast(int, region["start_line"]) <= cast(int, atom["start_line"])
                and cast(int, atom["end_line"]) <= cast(int, region["end_line"])
            ),
            None,
        )
        if container is None:
            merged.append(dict(atom))
            continue
        current = container["candidates"]
        incoming = atom["candidates"]
        assert isinstance(current, list) and isinstance(incoming, list)
        container["candidates"] = _unique_rows(
            [*current, *incoming], order=_candidate_source_order
        )
    for region in merged:
        candidates = region["candidates"]
        assert isinstance(candidates, list)
        region["candidates"] = _unique_rows(candidates, order=_candidate_source_order)
    merged.sort(
        key=lambda item: (
            item["path"],
            item["start_line"],
            item["end_line"],
            cast(list[dict[str, object]], item["candidates"])[0]["candidate_id"],
        )
    )
    return merged


def _requirement(
    runtime: ObligationRuntime, obligation: ObligationRecord
) -> dict[str, object]:
    if obligation.kind == "section":
        sections = [
            item
            for item in runtime.pipeline.raw_report.spec_sections
            if f"{item.path}#{item.section_id}" == obligation.obligation_id
        ]
        if len(sections) != 1:
            raise SourceAlignedPacketError(
                "REQUIREMENT_INVALID", "section requirement is not uniquely captured"
            )
        projection = project_section_packet_requirement(
            runtime.snapshot.read_bytes(obligation.path),
            path=obligation.path,
            section=sections[0],
            end_line=obligation.end_line,
            mappings=runtime.pipeline.raw_report.spec_mappings,
            skips=runtime.pipeline.artifacts.obligation_skips,
            declarations=runtime.pipeline.artifacts.suppression_declarations,
        )
        identity = sections[0].section_id
        title = obligation.title
        text = projection.text
        start_line = projection.start_line
        end_line = projection.end_line
    else:
        invariant_id = obligation.obligation_id.removeprefix("invariant::")
        declarations = [
            item
            for item in runtime.pipeline.raw_report.invariants
            if item.invariant_id == invariant_id
        ]
        if len(declarations) != 1:
            raise SourceAlignedPacketError(
                "REQUIREMENT_INVALID", "invariant requirement is not uniquely captured"
            )
        declaration = declarations[0]
        identity = invariant_id
        title = None
        text = declaration.statement
        start_line = declaration.line
        end_line = start_line + max(1, lf_line_count(text)) - 1
    if not text.strip():
        raise SourceAlignedPacketError(
            "REQUIREMENT_INVALID", "packet requirement text is blank"
        )
    return {
        "role": "requirement",
        "path": obligation.path,
        "identity": identity,
        "title": title,
        "start_line": start_line,
        "end_line": end_line,
        "text": text,
    }


def _packet_issues(
    runtime: ObligationRuntime, obligation: ObligationRecord
) -> list[dict[str, object]]:
    identity = obligation.obligation_id.rsplit("#", 1)[-1]
    if obligation.kind == "invariant":
        identity = obligation.obligation_id.removeprefix("invariant::")
    rows: list[dict[str, object]] = []
    for issue in runtime.pipeline.report.issues:
        attributed = (
            issue.section_id == identity
            if obligation.kind == "section"
            else issue.invariant_id == identity
        )
        if not attributed:
            continue
        source = dataclasses.asdict(issue)
        rows.append({field: source[field] for field in ISSUE_FIELDS})
    return rows


def _derivation_config(
    runtime: ObligationRuntime,
    *,
    packet_contract_version: int = ALGORITHMS.packet_contract_version,
) -> dict[str, object]:
    settings = runtime.settings.obligations
    return {
        "derivation_config_version": 1,
        "section_required_roles": list(settings.section_required_roles),
        "maximum_candidate_items": settings.maximum_candidate_items,
        "maximum_catalog_items": settings.maximum_catalog_items,
        "maximum_lexical_seeds": settings.maximum_lexical_seeds,
        "maximum_work_units": settings.maximum_work_units,
        "maximum_packet_bytes": settings.maximum_packet_bytes,
        "maximum_packet_report_bytes": settings.maximum_packet_report_bytes,
        "static_neighbor_depth": settings.static_neighbor_depth,
        "obligation_algorithm_version": ALGORITHMS.obligation_algorithm_version,
        "discovery_algorithm_version": ALGORITHMS.discovery_algorithm_version,
        "packet_contract_version": packet_contract_version,
        "normalization_version": ALGORITHMS.normalization_version,
    }


def _compile_source_aligned_packet(
    runtime: ObligationRuntime,
    obligation: ObligationRecord,
    prepared_catalog: PreparedEvidenceCatalog,
) -> dict[str, Any]:
    declared_items = [dict(item) for item in runtime.evidence_summary(obligation)]
    declared_sources = _unique_rows(
        [_source_row(item) for item in declared_items], order=_source_order
    )
    declared_atoms: list[dict[str, object]] = []
    for item in declared_items:
        source_role = str(item["role"])
        declared_atoms.append(
            {
                "role": "implementation" if source_role == "implementation" else "test",
                "path": item["path"],
                "symbol": item["symbol"],
                "start_line": item["start_line"],
                "end_line": item["end_line"],
                "snippet": _canonical_span_text(str(item["excerpt"])),
                "sources": [_source_row(item)],
            }
        )
    declared_regions = _merge_declared_regions(declared_atoms)
    declared_receipts = {str(source["receipt_hash"]) for source in declared_sources}

    candidates = runtime.discover_candidates(
        obligation,
        prepared_catalog=prepared_catalog,
    )
    counter_atoms: list[dict[str, object]] = []
    candidate_rows: list[dict[str, object]] = []
    for candidate in candidates:
        relations = sorted(
            {
                item.relation_kind
                for item in (*candidate.declared_relations, *candidate.static_relations)
            },
            key=_RELATION_INDEX.__getitem__,
        )
        receipt_hash = _receipt_hash(candidate.receipt.to_row())
        source_row: dict[str, object] = {
            "candidate_id": candidate.candidate_id,
            "candidate_kind": candidate.candidate_kind,
            "receipt_hash": receipt_hash,
            "trace_state": candidate.trace_state,
            "discovery_bases": list(candidate.discovery_bases),
            "relation_kinds": relations,
        }
        candidate_rows.append(source_row)
        if candidate.trace_state == "declared" and receipt_hash in declared_receipts:
            continue
        source = get_candidate_source(candidate)
        counter_atoms.append(
            {
                "role": "counterevidence",
                "path": candidate.path,
                "start_line": candidate.start_line,
                "end_line": candidate.end_line,
                "snippet": _canonical_span_text(source.text),
                "candidates": [source_row],
            }
        )
    counter_regions = _merge_counterevidence_regions(counter_atoms)

    declared_count_rows = []
    for role in ("implementation", "test", "binding_test"):
        rows = [item for item in declared_sources if item["source_role"] == role]
        declared_count_rows.append(
            {
                "source_role": role,
                "total": len(rows),
                "complete": sum(
                    item["reciprocity_state"] == "complete" for item in rows
                ),
                "one_sided": sum(
                    item["reciprocity_state"] == "one_sided" for item in rows
                ),
            }
        )
    candidate_count_rows = []
    for kind in _CANDIDATE_KIND_ORDER:
        rows = [item for item in candidate_rows if item["candidate_kind"] == kind]
        candidate_count_rows.append(
            {
                "candidate_kind": kind,
                **{
                    state: sum(item["trace_state"] == state for item in rows)
                    for state in _TRACE_STATE_ORDER
                },
            }
        )
    memberships: set[tuple[str, str, str]] = set()
    for item in declared_sources:
        for relation in cast(list[str], item["relation_kinds"]):
            memberships.add(
                (
                    "declared",
                    f"{item['source_role']}:{item['receipt_hash']}",
                    relation,
                )
            )
    for item in candidate_rows:
        for relation in cast(list[str], item["relation_kinds"]):
            memberships.add(("candidate", str(item["candidate_id"]), relation))
    relation_count_rows = [
        {
            "relation_kind": relation,
            "count": sum(item[2] == relation for item in memberships),
        }
        for relation in _RELATION_ORDER
    ]
    trace_summary = {
        "declared_counts": declared_count_rows,
        "candidate_counts": candidate_count_rows,
        "relation_counts": relation_count_rows,
    }
    requirement = _requirement(runtime, obligation)
    evidence_regions = [
        {
            "role": "requirement",
            "path": requirement["path"],
            "start_line": requirement["start_line"],
            "end_line": requirement["end_line"],
        },
        *(
            {
                "role": item["role"],
                "path": item["path"],
                "start_line": item["start_line"],
                "end_line": item["end_line"],
            }
            for item in declared_regions
            if str(item["snippet"]).strip()
        ),
        *(
            {
                "role": "counterevidence",
                "path": item["path"],
                "start_line": item["start_line"],
                "end_line": item["end_line"],
            }
            for item in counter_regions
            if str(item["snippet"]).strip()
        ),
    ]
    evidence_regions.sort(
        key=lambda item: (
            _MODEL_ROLE_ORDER[str(item["role"])],
            item["path"],
            item["start_line"],
            item["end_line"],
        )
    )
    state = {
        "obligation_state_version": 1,
        "obligation_id": obligation.obligation_id,
        "kind": obligation.kind,
        "obligation_rung": obligation.obligation_rung,
        "intent_state": obligation.intent_state,
        "alignment_state": obligation.alignment_state,
        "disposition": obligation.disposition,
        "gate_state": obligation.gate_state,
        "required_roles": list(obligation.required_roles),
        "declared_sources": declared_sources,
    }
    derivation = _derivation_config(runtime)
    packet: dict[str, Any] = {
        "schema_version": 3,
        "packet_id": obligation.obligation_id,
        "packet_hash": "",
        "kind": obligation.kind,
        "obligation_id": obligation.obligation_id,
        "source_snapshot": {
            "snapshot_hash": runtime.snapshot.snapshot_hash,
            "obligation_state_hash": hashlib.sha256(
                canonical_json_bytes(state)
            ).hexdigest(),
            "derivation_config_hash": hashlib.sha256(
                canonical_json_bytes(derivation)
            ).hexdigest(),
        },
        "readiness": {
            "intent_state": obligation.intent_state,
            "alignment_state": obligation.alignment_state,
            "disposition": obligation.disposition,
            "obligation_rung": obligation.obligation_rung,
            "gate_state": obligation.gate_state,
            "required_roles": list(obligation.required_roles),
        },
        "requirement": requirement,
        "declared_evidence": declared_regions,
        "counterevidence": counter_regions,
        "trace_summary": trace_summary,
        "evidence_regions": evidence_regions,
        "issues": _packet_issues(runtime, obligation),
        "packet_warnings": [],
    }
    packet["packet_hash"] = semantic_packet_hash(packet)
    return packet


def _suppression_issue_rows(
    decisions: list[SuppressionDecision],
) -> list[dict[str, object]]:
    """Project the complete decision population in ordinary issue order."""

    rows: list[dict[str, object]] = []
    for decision in decisions:
        source = dataclasses.asdict(decision.issue)
        rows.append({field: source[field] for field in ISSUE_FIELDS})
    return sorted(
        rows,
        key=partial(
            issue_sort_key,
            severity_field="default_severity",
            canonical_tiebreak=True,
        ),
    )


def _suppression_counterevidence(
    runtime: ObligationRuntime,
    issues: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Read exact issue lines from the already accepted snapshot."""

    grouped: dict[tuple[str, int], list[int]] = {}
    for index, issue in enumerate(issues):
        path = issue["path"]
        line = issue["line"]
        if not isinstance(path, str) or not path or not isinstance(line, int):
            continue
        grouped.setdefault((path, line), []).append(index)

    rows: list[dict[str, object]] = []
    decoded: dict[str, tuple[str, ...]] = {}
    for (path, line), issue_indexes in sorted(grouped.items()):
        if path not in decoded:
            try:
                decoded[path] = tuple(
                    lf_split(
                        runtime.snapshot.read_bytes(path).decode("utf-8", "replace")
                    )
                )
            except KeyError:
                raise SourceAlignedPacketError(
                    "SUPPRESSION_EVIDENCE_INVALID",
                    f"suppressed issue source is not in the accepted snapshot: {path}",
                ) from None
        if line < 1 or line > len(decoded[path]):
            raise SourceAlignedPacketError(
                "SUPPRESSION_EVIDENCE_INVALID",
                f"suppressed issue line is outside the accepted snapshot: {path}:{line}",
            )
        rows.append(
            {
                "role": "counterevidence",
                "path": path,
                "start_line": line,
                "end_line": line,
                "snippet": decoded[path][line - 1],
                "issue_indexes": issue_indexes,
            }
        )
    return rows


def _compile_suppression_packet(
    runtime: ObligationRuntime,
    obligation: ObligationRecord,
) -> dict[str, Any]:
    """Compile one complete schema-4 packet from the shared decision model."""

    detail = obligation.suppression
    if detail is None:
        raise SourceAlignedPacketError(
            "SUPPRESSION_EVIDENCE_INVALID",
            "suppression obligation has no declaration detail",
        )
    declaration = detail.declaration
    decisions = [
        decision
        for decision in runtime.pipeline.suppressed
        if decision.declaration == declaration.reference and decision.rule is not None
    ]
    if len(decisions) != detail.matched_issue_count:
        raise SourceAlignedPacketError(
            "SUPPRESSION_EVIDENCE_INVALID",
            "suppression obligation decision population changed after inventory",
        )
    issues = _suppression_issue_rows(decisions)
    if not issues:
        raise SourceAlignedPacketError(
            "SUPPRESSION_EVIDENCE_INVALID",
            "suppression packet requires at least one matched issue",
        )
    counterevidence = _suppression_counterevidence(runtime, issues)
    requirement = {
        "role": "requirement",
        "path": declaration.path,
        "identity": declaration.declaration_id,
        "title": declaration.owner_title,
        "start_line": declaration.start_line,
        "end_line": declaration.end_line,
        "text": declaration.rationale,
    }
    evidence_regions = [
        {
            "role": "requirement",
            "path": declaration.path,
            "start_line": declaration.start_line,
            "end_line": declaration.end_line,
        },
        *(
            {
                "role": "counterevidence",
                "path": item["path"],
                "start_line": item["start_line"],
                "end_line": item["end_line"],
            }
            for item in counterevidence
        ),
    ]
    state = {
        "obligation_state_version": 1,
        "obligation_id": obligation.obligation_id,
        "kind": obligation.kind,
        "obligation_rung": obligation.obligation_rung,
        "intent_state": obligation.intent_state,
        "alignment_state": obligation.alignment_state,
        "disposition": obligation.disposition,
        "gate_state": obligation.gate_state,
        "required_roles": [],
        "declared_sources": [],
    }
    derivation = _derivation_config(runtime, packet_contract_version=4)
    packet: dict[str, Any] = {
        "schema_version": 4,
        "packet_id": obligation.obligation_id,
        "packet_hash": "",
        "kind": "suppression",
        "obligation_id": obligation.obligation_id,
        "source_snapshot": {
            "snapshot_hash": runtime.snapshot.snapshot_hash,
            "obligation_state_hash": hashlib.sha256(
                canonical_json_bytes(state)
            ).hexdigest(),
            "derivation_config_hash": hashlib.sha256(
                canonical_json_bytes(derivation)
            ).hexdigest(),
        },
        "readiness": {
            "intent_state": "identified",
            "alignment_state": "complete",
            "disposition": "evaluate",
            "obligation_rung": "active",
            "gate_state": "executable",
            "required_roles": [],
        },
        "requirement": requirement,
        "suppression_rules": [suppression_rule_row(rule) for rule in detail.rules],
        "counterevidence": counterevidence,
        "evidence_regions": evidence_regions,
        "issues": issues,
        "packet_warnings": [],
    }
    packet["packet_hash"] = semantic_packet_hash(packet)
    return packet


def generate_source_aligned_packets(
    runtime: ObligationRuntime,
    *,
    require_complete_corpus: bool = True,
    kind: PacketKind = "all",
) -> list[dict[str, Any]]:
    """Compile the complete current executable corpus from one runtime."""

    active = [
        item
        for item in runtime.inventory.obligations
        if item.obligation_rung == "active"
    ]
    if not active:
        raise SourceAlignedPacketError(
            "NO_ACTIVE_INTENT", "current repository has no active obligation"
        )
    debt = [
        item
        for item in active
        if item.disposition == "evaluate" and item.gate_state != "executable"
    ]
    if debt and require_complete_corpus:
        raise SourceAlignedPacketError(
            "ALIGNMENT_DEBT",
            "current repository has active non-executable alignment debt",
        )
    selected = [
        item
        for item in active
        if item.disposition == "evaluate"
        and item.gate_state == "executable"
        and (kind == "all" or item.kind == kind)
    ]
    if not selected:
        return []
    prepared_catalog = (
        runtime.prepare_discovery_catalog()
        if any(item.kind != "suppression" for item in selected)
        else None
    )
    packets: list[dict[str, Any]] = []
    for item in selected:
        if item.kind == "suppression":
            packets.append(_compile_suppression_packet(runtime, item))
        else:
            assert prepared_catalog is not None
            packets.append(
                _compile_source_aligned_packet(runtime, item, prepared_catalog)
            )
    rendered = render_packets_jsonl(packets).encode("utf-8")
    if len(rendered) > runtime.settings.obligations.maximum_packet_bytes:
        raise SourceAlignedPacketError(
            "PACKET_BUDGET_EXHAUSTED",
            "complete packet JSONL exceeds maximum_packet_bytes",
        )
    return packets


def render_packets_jsonl(packets: list[dict[str, Any]]) -> str:
    """Render packets as JSONL, one packet per line."""

    return b"".join(canonical_json_bytes(packet) + b"\n" for packet in packets).decode(
        "utf-8"
    )
