"""Transport-neutral obligation inventory and alignment readiness.

This module projects one already-resolved, policy-independent trace report into
the obligation vocabulary.  It performs no filesystem reads, source parsing,
suppression, diagnostic policy, provider work, or artifact publication.

Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-2], [EVC-2.1],
[EVC-2.2], [EVC-8.3]
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from fnmatch import fnmatch
from pathlib import PurePosixPath
from typing import Literal

from backstitch.canonical import canonical_json_bytes
from backstitch.config import ProfileConfig
from backstitch.models import (
    Edge,
    InvariantDeclaration,
    Issue,
    Report,
    SpecMapping,
    SpecSection,
    SuppressionDecision,
    SuppressionDeclaration,
    SuppressionRule,
)

IntentState = Literal["identified"]
AlignmentState = Literal["untraced", "partial", "complete", "invalid"]
Disposition = Literal["evaluate", "skipped"]
ObligationRung = Literal["active", "planned", "exploratory", "meta"]
GateState = Literal["not_executable", "executable"]
ObligationKind = Literal["section", "invariant", "suppression"]
EvidenceRole = Literal["implementation", "test", "binding_test"]
ModelEvidenceRole = Literal["implementation", "test"]
EvidenceEligibility = Literal["implementation", "test", "binding_test", "invalid"]
ReciprocityState = Literal["complete", "one_sided"]
RelationKind = Literal[
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
]
GuidanceCode = Literal[
    "ADD_OR_CONFIGURE_SPEC_INTENT",
    "FIX_OBLIGATION_IDENTITY",
    "ADD_RECIPROCAL_MAPPING",
    "ADD_RECIPROCAL_BACKLINK",
    "ADD_INVARIANT_BIND",
    "ADD_BINDING_TEST",
    "REVIEW_UNTRACED_CANDIDATE",
    "REVIEW_CONFLICTED_TRACE",
    "REVIEW_SKIP_REASON",
    "RUN_DETERMINISTIC_CHECK",
    "RUN_CURRENT_ANALYSIS",
]
BlockingReasonCode = Literal[
    "IMPLEMENTATION_UNTRACED",
    "IMPLEMENTATION_PARTIAL",
    "TEST_UNTRACED",
    "TEST_PARTIAL",
    "INVARIANT_TARGET_MISSING",
    "BINDING_TEST_MISSING",
    "TRACE_CONFLICT",
    "OUT_OF_GATE_SCOPE",
    "SKIPPED",
]

_GUIDANCE_ORDER: tuple[GuidanceCode, ...] = (
    "ADD_OR_CONFIGURE_SPEC_INTENT",
    "FIX_OBLIGATION_IDENTITY",
    "ADD_RECIPROCAL_MAPPING",
    "ADD_RECIPROCAL_BACKLINK",
    "ADD_INVARIANT_BIND",
    "ADD_BINDING_TEST",
    "REVIEW_UNTRACED_CANDIDATE",
    "REVIEW_CONFLICTED_TRACE",
    "REVIEW_SKIP_REASON",
    "RUN_DETERMINISTIC_CHECK",
    "RUN_CURRENT_ANALYSIS",
)
_BLOCKING_REASON_ORDER: tuple[BlockingReasonCode, ...] = (
    "IMPLEMENTATION_UNTRACED",
    "IMPLEMENTATION_PARTIAL",
    "TEST_UNTRACED",
    "TEST_PARTIAL",
    "INVARIANT_TARGET_MISSING",
    "BINDING_TEST_MISSING",
    "TRACE_CONFLICT",
    "OUT_OF_GATE_SCOPE",
    "SKIPPED",
)
_UNADDRESSABLE_CODES = frozenset(
    {
        "SPEC_SECTION_HEADING_INVALID",
        "SPEC_SECTION_DUPLICATE",
        "INVARIANT_DUPLICATE",
        "INVARIANT_MARKER_INVALID",
    }
)
_SECTION_CONFLICT_CODES = frozenset(
    {
        "TARGET_PATH_AMBIGUOUS",
        "SPEC_SECTION_AMBIGUOUS",
    }
)


def is_unaddressable_issue(issue: Issue) -> bool:
    """Return whether one deterministic issue denotes reserved source intent."""

    return issue.code in _UNADDRESSABLE_CODES


def _validate_count(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a nonnegative integer")


@dataclass(frozen=True, slots=True)
class SnapshotIdentity:
    """Clone-independent identity and bounded manifest counts for one capture."""

    snapshot_hash: str
    file_count: int
    byte_count: int
    unreadable_count: int

    def __post_init__(self) -> None:
        if not self.snapshot_hash.strip():
            raise ValueError("snapshot_hash must be nonblank")
        _validate_count(self.file_count, "file_count")
        _validate_count(self.byte_count, "byte_count")
        _validate_count(self.unreadable_count, "unreadable_count")

    def to_row(self) -> dict[str, object]:
        return {
            "snapshot_hash": self.snapshot_hash,
            "file_count": self.file_count,
            "byte_count": self.byte_count,
            "unreadable_count": self.unreadable_count,
        }


@dataclass(frozen=True, slots=True)
class EvidenceCounts:
    implementation: int = 0
    test: int = 0
    binding_test: int = 0

    def __post_init__(self) -> None:
        _validate_count(self.implementation, "implementation")
        _validate_count(self.test, "test")
        _validate_count(self.binding_test, "binding_test")

    def to_row(self) -> dict[str, int]:
        return {
            "implementation": self.implementation,
            "test": self.test,
            "binding_test": self.binding_test,
        }


@dataclass(frozen=True, slots=True)
class CandidateCounts:
    declared: int = 0
    partially_declared: int = 0
    untraced: int = 0
    conflicted: int = 0

    def __post_init__(self) -> None:
        _validate_count(self.declared, "declared")
        _validate_count(self.partially_declared, "partially_declared")
        _validate_count(self.untraced, "untraced")
        _validate_count(self.conflicted, "conflicted")

    def to_row(self) -> dict[str, int]:
        return {
            "declared": self.declared,
            "partially_declared": self.partially_declared,
            "untraced": self.untraced,
            "conflicted": self.conflicted,
        }


@dataclass(frozen=True, slots=True)
class BlockingReason:
    code: BlockingReasonCode
    role: EvidenceRole | None = None
    relation_kind: RelationKind | None = None
    issue_identity: str | None = None

    def to_row(self) -> dict[str, object]:
        return {
            "code": self.code,
            "role": self.role,
            "relation_kind": self.relation_kind,
            "issue_identity": self.issue_identity,
        }


def suppression_rule_row(rule: SuppressionRule) -> dict[str, object]:
    """Project one normalized rule into its shared API/packet shape."""

    return {
        "mechanism": rule.mechanism,
        "provenance": rule.provenance,
        "path": rule.path,
        "sections": list(rule.sections),
        "codes": list(rule.codes),
        "declaration": rule.declaration,
        "origin": {
            "source": rule.origin.source,
            "position": rule.origin.position,
            "line": rule.origin.line,
        },
    }


@dataclass(frozen=True, slots=True)
class SuppressionObligationDetail:
    """Source declaration and complete normalized decision population."""

    declaration: SuppressionDeclaration
    rules: tuple[SuppressionRule, ...]
    matched_issue_count: int

    def __post_init__(self) -> None:
        if not self.rules:
            raise ValueError("suppression obligation requires at least one rule")
        _validate_count(self.matched_issue_count, "matched_issue_count")
        if self.matched_issue_count < 1:
            raise ValueError("suppression obligation requires a matched issue")

    def to_row(self) -> dict[str, object]:
        declaration = self.declaration
        return {
            "declaration": {
                "declaration_id": declaration.declaration_id,
                "reference": declaration.reference,
                "rationale": declaration.rationale,
                "path": declaration.path,
                "owner_section_id": declaration.owner_section_id,
                "owner_title": declaration.owner_title,
                "start_line": declaration.start_line,
                "end_line": declaration.end_line,
            },
            "suppression_rules": [suppression_rule_row(rule) for rule in self.rules],
            "matched_issue_count": self.matched_issue_count,
        }


@dataclass(frozen=True, slots=True)
class ObligationRecord:
    obligation_id: str
    kind: ObligationKind
    path: str
    start_line: int
    end_line: int
    title: str | None
    intent_state: IntentState
    alignment_state: AlignmentState
    disposition: Disposition
    obligation_rung: ObligationRung
    gate_state: GateState
    required_roles: tuple[EvidenceRole, ...]
    evidence_counts: EvidenceCounts
    candidate_counts: CandidateCounts
    blocking_reasons: tuple[BlockingReason, ...]
    next_actions: tuple[GuidanceCode, ...]
    suppression: SuppressionObligationDetail | None = None

    def list_row(self) -> dict[str, object]:
        return {
            "entry_type": "obligation",
            "entry_identity": self.obligation_id,
            "obligation_id": self.obligation_id,
            "kind": self.kind,
            "path": self.path,
            "start_line": self.start_line,
            "title": self.title,
            "intent_state": self.intent_state,
            "alignment_state": self.alignment_state,
            "disposition": self.disposition,
            "obligation_rung": self.obligation_rung,
            "gate_state": self.gate_state,
            "blocking_reason_codes": [item.code for item in self.blocking_reasons],
        }

    def to_row(self) -> dict[str, object]:
        row: dict[str, object] = {
            "obligation_id": self.obligation_id,
            "kind": self.kind,
            "path": self.path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "title": self.title,
            "intent_state": self.intent_state,
            "alignment_state": self.alignment_state,
            "disposition": self.disposition,
            "obligation_rung": self.obligation_rung,
            "gate_state": self.gate_state,
            "required_roles": list(self.required_roles),
            "evidence_counts": self.evidence_counts.to_row(),
            "candidate_counts": self.candidate_counts.to_row(),
            "blocking_reasons": [item.to_row() for item in self.blocking_reasons],
            "next_actions": list(self.next_actions),
        }
        if self.suppression is not None:
            row.update(self.suppression.to_row())
        return row


@dataclass(frozen=True, slots=True)
class UnaddressableIntent:
    entry_identity: str
    code: str
    path: str
    line: int | None
    message: str
    excerpt: str
    action: GuidanceCode = "FIX_OBLIGATION_IDENTITY"

    def list_row(self) -> dict[str, object]:
        return {
            "entry_type": "unaddressable_intent",
            "entry_identity": self.entry_identity,
            "diagnostic": {
                "code": self.code,
                "path": self.path,
                "line": self.line,
                "message": self.message,
            },
            "excerpt": self.excerpt,
            "action": self.action,
        }


@dataclass(frozen=True, slots=True)
class ObligationInventory:
    snapshot: SnapshotIdentity
    obligations: tuple[ObligationRecord, ...]
    unaddressable_intent: tuple[UnaddressableIntent, ...]
    next_actions: tuple[GuidanceCode, ...]

    def get(self, obligation_id: str) -> ObligationRecord | None:
        for obligation in self.obligations:
            if obligation.obligation_id == obligation_id:
                return obligation
        return None

    def list_result(self) -> dict[str, object]:
        entries: list[tuple[tuple[object, ...], dict[str, object]]] = []
        for item in self.unaddressable_intent:
            entries.append(
                (
                    (item.path, item.line or 0, 0, item.entry_identity),
                    item.list_row(),
                )
            )
        for obligation in self.obligations:
            entries.append(
                (
                    (
                        obligation.path,
                        obligation.start_line,
                        1,
                        obligation.obligation_id,
                    ),
                    obligation.list_row(),
                )
            )
        entries.sort(key=lambda item: item[0])
        return {
            "bootstrap_state": "intent_found" if entries else "no_intent",
            "entries": [row for _, row in entries],
            "next_cursor": None,
        }


@dataclass(frozen=True, slots=True)
class ResolvedEvidenceAtom:
    """One canonical role, relation, and eligibility decision ([EVC-2.2])."""

    source_role: EvidenceRole
    model_role: ModelEvidenceRole
    source_identity: str
    relation_kinds: tuple[RelationKind, ...]
    reciprocity_state: ReciprocityState
    eligibility: EvidenceEligibility
    reason: str | None

    def __post_init__(self) -> None:
        if not self.source_identity.strip():
            raise ValueError("source_identity must be nonblank")
        if not self.relation_kinds:
            raise ValueError("relation_kinds must be nonempty")
        if self.eligibility == "invalid":
            if self.reason is None or not self.reason.strip():
                raise ValueError("invalid evidence requires a nonblank reason")
        elif self.reason is not None:
            raise ValueError("eligible evidence cannot carry a blocking reason")

    def to_row(self) -> dict[str, object]:
        return {
            "source_role": self.source_role,
            "model_role": self.model_role,
            "source_identity": self.source_identity,
            "relation_kinds": list(self.relation_kinds),
            "reciprocity_state": self.reciprocity_state,
            "eligibility": self.eligibility,
            "reason": self.reason,
        }


_RELATION_ORDER: tuple[RelationKind, ...] = (
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


def resolved_source_identity(path: str, symbol: str | None) -> str:
    """Return the canonical graph-level identity for one resolved source."""

    identity = canonical_json_bytes(
        {
            "path": path,
            "symbol": symbol,
            "source_identity_version": 1,
        }
    )
    return f"source:sha256:{hashlib.sha256(identity).hexdigest()}"


def resolve_evidence_atom(
    *,
    path: str,
    symbol: str | None,
    relation_kinds: Sequence[RelationKind],
    reciprocity_state: ReciprocityState,
    test_roots: Sequence[str],
    source_identity: str | None = None,
    binding_test: bool = False,
    valid: bool = True,
    reason: str | None = None,
) -> ResolvedEvidenceAtom:
    """Resolve evidence once so consumers never reclassify it from a path."""

    if binding_test:
        source_role: EvidenceRole = "binding_test"
    else:
        source_role = "test" if _is_under(path, test_roots) else "implementation"
    ordered_relations = tuple(
        relation
        for relation in _RELATION_ORDER
        if relation in frozenset(relation_kinds)
    )
    return ResolvedEvidenceAtom(
        source_role=source_role,
        model_role="implementation" if source_role == "implementation" else "test",
        source_identity=source_identity or resolved_source_identity(path, symbol),
        relation_kinds=ordered_relations,
        reciprocity_state=reciprocity_state,
        eligibility=source_role if valid else "invalid",
        reason=reason if not valid else None,
    )


@dataclass(frozen=True, slots=True)
class _SectionEvidence:
    facts: tuple[ResolvedEvidenceAtom, ...]

    def for_role(
        self, role: Literal["implementation", "test"]
    ) -> tuple[ResolvedEvidenceAtom, ...]:
        return tuple(item for item in self.facts if item.source_role == role)

    def role_complete(self, role: Literal["implementation", "test"]) -> bool:
        facts = self.for_role(role)
        return any(
            item.eligibility == role and item.reciprocity_state == "complete"
            for item in facts
        )


def _is_under(path: str, roots: Sequence[str]) -> bool:
    pure = PurePosixPath(path)
    return any(pure.is_relative_to(PurePosixPath(root)) for root in roots)


def _mapping_covers(mapping: Edge, backlink: Edge) -> bool:
    path_matches = (
        backlink.code_path == mapping.code_path
        or backlink.code_path.startswith(mapping.code_path.rstrip("/") + "/")
    )
    if not path_matches:
        return False
    return mapping.code_symbol is None or mapping.code_symbol == backlink.code_symbol


def _mapping_declaration_matches_edge(mapping: SpecMapping, edge: Edge) -> bool:
    if (
        mapping.spec_path != edge.spec_path
        or mapping.section_id != edge.section_id
        or mapping.line != edge.line
    ):
        return False
    if mapping.target_symbol is not None and mapping.target_symbol != edge.code_symbol:
        return False
    return mapping.target_path is None or bool(mapping.target_path.rstrip("/"))


def associate_mapping_declaration_indexes(
    mappings: Sequence[SpecMapping], edges: Sequence[Edge]
) -> tuple[int | None, ...]:
    """Associate each resolved mapping edge with one source declaration.

    Exact paths win over suffix paths, declarations are consumed in source
    order, and repeated identical edges may reuse the declaration they already
    resolved.  Inventory and evidence-summary callers share this projection so
    line-coincident declarations cannot produce different readiness answers.
    """

    remaining = list(range(len(mappings)))
    rows: list[int | None] = []
    seen: list[Edge] = []
    for edge in edges:
        matches = [
            index
            for index in remaining
            if _mapping_declaration_matches_edge(mappings[index], edge)
        ]
        normalized_edge_path = edge.code_path.rstrip("/")
        exact = [
            index
            for index in matches
            if (target_path := mappings[index].target_path) is not None
            and target_path.rstrip("/") == normalized_edge_path
        ]
        if exact:
            declaration_index: int | None = exact[0]
        else:
            suffix = [
                index
                for index in matches
                if (target_path := mappings[index].target_path) is not None
                and normalized_edge_path.endswith("/" + target_path.rstrip("/"))
            ]
            if suffix:
                declaration_index = suffix[0]
            else:
                symbol_only = [
                    index for index in matches if mappings[index].target_path is None
                ]
                declaration_index = symbol_only[0] if symbol_only else None
        if declaration_index is None:
            declaration_index = next(
                (
                    previous_index
                    for previous_edge, previous_index in zip(seen, rows, strict=True)
                    if previous_edge == edge and previous_index is not None
                ),
                None,
            )
        rows.append(declaration_index)
        seen.append(edge)
        if declaration_index is not None and declaration_index in remaining:
            remaining.remove(declaration_index)
    return tuple(rows)


def _section_evidence(
    report: Report,
    section: SpecSection,
    test_roots: Sequence[str],
) -> _SectionEvidence:
    key = (section.path, section.section_id)
    mapping_edges = tuple(
        edge
        for edge in report.edges
        if edge.kind == "mapping" and (edge.spec_path, edge.section_id) == key
    )
    backlink_edges = tuple(
        edge
        for edge in report.edges
        if edge.kind == "backlink" and (edge.spec_path, edge.section_id) == key
    )
    source_mappings = tuple(
        mapping
        for mapping in report.spec_mappings
        if (mapping.spec_path, mapping.section_id) == key
    )
    declaration_indexes = associate_mapping_declaration_indexes(
        source_mappings, mapping_edges
    )
    facts: dict[tuple[str, str, str | None], ResolvedEvidenceAtom] = {}

    matched_mapping_edge_indexes: set[int] = set()
    matched_backlink_edges: set[Edge] = set()
    for backlink in backlink_edges:
        matching = tuple(
            index
            for index, mapping in enumerate(mapping_edges)
            if _mapping_covers(mapping, backlink)
        )
        if not matching:
            continue
        matched_backlink_edges.add(backlink)
        matched_mapping_edge_indexes.update(matching)
        atom = resolve_evidence_atom(
            path=backlink.code_path,
            symbol=backlink.code_symbol,
            relation_kinds=("spec_mapping", "code_backlink"),
            reciprocity_state="complete",
            test_roots=test_roots,
        )
        facts[(atom.source_role, backlink.code_path, backlink.code_symbol)] = atom

    for edge_index, mapping_edge in enumerate(mapping_edges):
        if edge_index in matched_mapping_edge_indexes:
            continue
        atom = resolve_evidence_atom(
            path=mapping_edge.code_path,
            symbol=mapping_edge.code_symbol,
            relation_kinds=("spec_mapping",),
            reciprocity_state="one_sided",
            test_roots=test_roots,
        )
        fact_key = (
            atom.source_role,
            mapping_edge.code_path,
            mapping_edge.code_symbol,
        )
        facts.setdefault(
            fact_key,
            atom,
        )

    resolved_mapping_indexes = {
        index for index in declaration_indexes if index is not None
    }
    for mapping_index, spec_mapping in enumerate(source_mappings):
        if mapping_index in resolved_mapping_indexes:
            continue
        path = spec_mapping.target_path or spec_mapping.target
        atom = resolve_evidence_atom(
            path=path,
            symbol=spec_mapping.target_symbol,
            relation_kinds=("spec_mapping",),
            reciprocity_state="one_sided",
            test_roots=test_roots if spec_mapping.target_path else (),
            valid=False,
            reason="mapping target did not resolve",
        )
        fact_key = (atom.source_role, path, spec_mapping.target_symbol)
        facts.setdefault(
            fact_key,
            atom,
        )

    for backlink in backlink_edges:
        if backlink in matched_backlink_edges:
            continue
        atom = resolve_evidence_atom(
            path=backlink.code_path,
            symbol=backlink.code_symbol,
            relation_kinds=("code_backlink",),
            reciprocity_state="one_sided",
            test_roots=test_roots,
        )
        fact_key = (atom.source_role, backlink.code_path, backlink.code_symbol)
        facts.setdefault(
            fact_key,
            atom,
        )

    return _SectionEvidence(
        tuple(
            sorted(
                facts.values(),
                key=lambda item: (
                    0 if item.source_role == "implementation" else 1,
                    item.source_identity,
                    item.relation_kinds,
                ),
            )
        )
    )


def _section_id(section: SpecSection) -> str:
    return f"{section.path}#{section.section_id}"


def _invariant_id(declaration: InvariantDeclaration) -> str:
    return f"invariant::{declaration.invariant_id}"


def _rung_for_section(
    section: SpecSection,
    profile: ProfileConfig,
    section_meta: frozenset[tuple[str, str]],
    meta_spec_globs: tuple[str, ...],
) -> ObligationRung:
    key = (section.path, section.section_id)
    if key in section_meta or any(
        fnmatch(section.path, pattern) for pattern in meta_spec_globs
    ):
        return "meta"
    if any(fnmatch(section.path, pattern) for pattern in profile.planned_spec_globs):
        return "planned"
    if any(
        fnmatch(section.path, pattern) for pattern in profile.exploratory_spec_globs
    ):
        return "exploratory"
    return "active"


def mapping_test_only_issues(
    report: Report,
    *,
    profile: ProfileConfig,
    section_meta: frozenset[tuple[str, str]],
    meta_spec_globs: tuple[str, ...],
) -> tuple[Issue, ...]:
    """Emit one BSC009 warning for each active test-only mapping ([SC-11])."""

    mapping_edges: dict[tuple[str, str], list[Edge]] = {}
    for edge in report.edges:
        if edge.kind == "mapping":
            mapping_edges.setdefault((edge.spec_path, edge.section_id), []).append(edge)
    issues: list[Issue] = []
    for section in report.spec_sections:
        if (
            _rung_for_section(section, profile, section_meta, meta_spec_globs)
            != "active"
        ):
            continue
        edges = mapping_edges.get((section.path, section.section_id), [])
        atoms = tuple(
            (
                edge,
                resolve_evidence_atom(
                    path=edge.code_path,
                    symbol=edge.code_symbol,
                    relation_kinds=("spec_mapping",),
                    reciprocity_state="one_sided",
                    test_roots=profile.test_roots,
                ),
            )
            for edge in edges
        )
        test_edges = [edge for edge, atom in atoms if atom.source_role == "test"]
        if not test_edges or any(
            atom.source_role == "implementation" for _edge, atom in atoms
        ):
            continue
        first = min(test_edges, key=lambda edge: (edge.line, edge.code_path))
        issues.append(
            Issue(
                code="SPEC_MAPPING_TEST_ONLY",
                severity="warning",
                path=section.path,
                line=first.line,
                message=(
                    f"section [{section.section_id}] maps implementation only"
                    " to configured test roots"
                ),
                section_id=section.section_id,
            )
        )
    return tuple(issues)


def _rung_for_invariant(
    declaration: InvariantDeclaration,
    sections: Mapping[tuple[str, str], SpecSection],
    profile: ProfileConfig,
    section_meta: frozenset[tuple[str, str]],
    meta_spec_globs: tuple[str, ...],
) -> ObligationRung:
    if declaration.declaration_kind == "code":
        return "active"
    section_id = declaration.section_id
    if section_id is None:
        return "active"
    section = sections.get((declaration.path, section_id))
    if section is None:
        return "active"
    return _rung_for_section(section, profile, section_meta, meta_spec_globs)


def _related_section_issues(report: Report, section: SpecSection) -> tuple[Issue, ...]:
    same_id_count = sum(
        1 for item in report.spec_sections if item.section_id == section.section_id
    )
    return tuple(
        issue
        for issue in report.issues
        if issue.section_id == section.section_id
        and (same_id_count == 1 or issue.path == section.path)
    )


def _sort_blockers(items: Sequence[BlockingReason]) -> tuple[BlockingReason, ...]:
    order = {code: index for index, code in enumerate(_BLOCKING_REASON_ORDER)}
    return tuple(
        sorted(
            items,
            key=lambda item: (
                order[item.code],
                item.role or "",
                item.relation_kind or "",
                item.issue_identity or "",
            ),
        )
    )


def _sort_guidance(items: Sequence[GuidanceCode]) -> tuple[GuidanceCode, ...]:
    present = set(items)
    return tuple(code for code in _GUIDANCE_ORDER if code in present)


def with_candidate_counts(
    obligation: ObligationRecord,
    candidate_counts: CandidateCounts,
) -> ObligationRecord:
    """Project discovery counts and their review action onto one obligation."""

    guidance = list(obligation.next_actions)
    if candidate_counts.conflicted:
        guidance.append("REVIEW_CONFLICTED_TRACE")
    if candidate_counts.untraced or candidate_counts.partially_declared:
        guidance.append("REVIEW_UNTRACED_CANDIDATE")
    return replace(
        obligation,
        candidate_counts=candidate_counts,
        next_actions=_sort_guidance(guidance),
    )


def _gate_state(
    *,
    alignment_state: AlignmentState,
    disposition: Disposition,
    rung: ObligationRung,
) -> GateState:
    if alignment_state != "complete":
        return "not_executable"
    if rung != "active" or disposition == "skipped":
        return "not_executable"
    return "executable"


def _section_record(  # noqa: C901 approved [SC-17.1] RUFF-SUP-054 exception
    report: Report,
    section: SpecSection,
    *,
    profile: ProfileConfig,
    required_roles: tuple[Literal["implementation", "test"], ...],
    section_meta: frozenset[tuple[str, str]],
    meta_spec_globs: tuple[str, ...],
    skipped: bool,
    candidate_counts: CandidateCounts,
    end_line: int,
) -> ObligationRecord:
    evidence = _section_evidence(report, section, profile.test_roots)
    related_issues = _related_section_issues(report, section)
    conflict = next(
        (issue for issue in related_issues if issue.code in _SECTION_CONFLICT_CODES),
        None,
    )
    blockers: list[BlockingReason] = []
    guidance: list[GuidanceCode] = []

    if conflict is not None:
        alignment_state: AlignmentState = "invalid"
        blockers.append(BlockingReason("TRACE_CONFLICT"))
        guidance.append("REVIEW_CONFLICTED_TRACE")
    else:
        complete_roles = sum(evidence.role_complete(role) for role in required_roles)
        has_required_evidence = any(evidence.for_role(role) for role in required_roles)
        if complete_roles == len(required_roles):
            alignment_state = "complete"
        elif not has_required_evidence:
            alignment_state = "untraced"
        else:
            alignment_state = "partial"

        for role in required_roles:
            if evidence.role_complete(role):
                continue
            role_facts = evidence.for_role(role)
            if role == "implementation":
                code: BlockingReasonCode = (
                    "IMPLEMENTATION_PARTIAL"
                    if role_facts
                    else "IMPLEMENTATION_UNTRACED"
                )
            else:
                code = "TEST_PARTIAL" if role_facts else "TEST_UNTRACED"
            relation_kind: RelationKind | None = (
                role_facts[0].relation_kinds[0] if role_facts else None
            )
            blockers.append(BlockingReason(code, role, relation_kind, None))

            relation_kinds = {
                relation_kind
                for fact in role_facts
                for relation_kind in fact.relation_kinds
            }
            if not role_facts or "code_backlink" in relation_kinds:
                guidance.append("ADD_RECIPROCAL_MAPPING")
            if not role_facts or "spec_mapping" in relation_kinds:
                guidance.append("ADD_RECIPROCAL_BACKLINK")

    rung = _rung_for_section(section, profile, section_meta, meta_spec_globs)
    disposition: Disposition = "skipped" if skipped else "evaluate"
    if rung != "active":
        blockers.append(BlockingReason("OUT_OF_GATE_SCOPE"))
    if skipped:
        blockers.append(BlockingReason("SKIPPED"))
        guidance.append("REVIEW_SKIP_REASON")
    guidance.append("RUN_DETERMINISTIC_CHECK")
    if alignment_state == "complete" and rung == "active" and not skipped:
        guidance.append("RUN_CURRENT_ANALYSIS")

    implementation_count = len(evidence.for_role("implementation"))
    test_count = len(evidence.for_role("test"))
    return ObligationRecord(
        obligation_id=_section_id(section),
        kind="section",
        path=section.path,
        start_line=section.line,
        end_line=end_line,
        title=section.title,
        intent_state="identified",
        alignment_state=alignment_state,
        disposition=disposition,
        obligation_rung=rung,
        gate_state=_gate_state(
            alignment_state=alignment_state,
            disposition=disposition,
            rung=rung,
        ),
        required_roles=required_roles,
        evidence_counts=EvidenceCounts(implementation_count, test_count, 0),
        candidate_counts=candidate_counts,
        blocking_reasons=_sort_blockers(blockers),
        next_actions=_sort_guidance(guidance),
    )


def _invariant_targets(
    report: Report,
    declaration: InvariantDeclaration,
    test_roots: Sequence[str],
    atomic_targets: frozenset[tuple[str, str | None]],
    atomic_code_invariant_ids: frozenset[str],
) -> tuple[tuple[tuple[str, str | None], ...], int]:
    if declaration.declaration_kind == "code":
        targets = (
            ((declaration.path, declaration.owner_symbol),)
            if declaration.invariant_id in atomic_code_invariant_ids
            else ()
        )
        return (
            targets,
            0 if targets else 1,
        )
    if declaration.section_id is None:
        return (), 0
    key = (declaration.path, declaration.section_id)
    source_mappings = tuple(
        mapping
        for mapping in report.spec_mappings
        if (mapping.spec_path, mapping.section_id) == key
    )
    mapping_edges = tuple(
        edge
        for edge in report.edges
        if edge.kind == "mapping" and (edge.spec_path, edge.section_id) == key
    )
    declaration_indexes = associate_mapping_declaration_indexes(
        source_mappings, mapping_edges
    )
    production_mapping_indexes = {
        index
        for index, mapping in enumerate(source_mappings)
        if resolve_evidence_atom(
            path=mapping.target_path or mapping.target,
            symbol=mapping.target_symbol,
            relation_kinds=("invariant_bind",),
            reciprocity_state="one_sided",
            test_roots=test_roots if mapping.target_path is not None else (),
        ).source_role
        == "implementation"
    }
    valid_indexes: set[int] = set()
    resolved_targets: set[tuple[str, str | None]] = set()
    for edge, mapping_index in zip(mapping_edges, declaration_indexes, strict=True):
        target = (edge.code_path, edge.code_symbol)
        atom = resolve_evidence_atom(
            path=edge.code_path,
            symbol=edge.code_symbol,
            relation_kinds=("invariant_bind",),
            reciprocity_state="one_sided",
            test_roots=test_roots,
        )
        if (
            mapping_index is None
            or atom.source_role != "implementation"
            or target not in atomic_targets
        ):
            continue
        valid_indexes.add(mapping_index)
        resolved_targets.add(target)
    broken_count = len(production_mapping_indexes - valid_indexes)
    return (
        tuple(sorted(resolved_targets, key=lambda item: (item[0], item[1] or ""))),
        broken_count,
    )


def _invariant_record(
    report: Report,
    declaration: InvariantDeclaration,
    *,
    sections: Mapping[tuple[str, str], SpecSection],
    profile: ProfileConfig,
    section_meta: frozenset[tuple[str, str]],
    meta_spec_globs: tuple[str, ...],
    skipped: bool,
    atomic_targets: frozenset[tuple[str, str | None]],
    atomic_code_invariant_ids: frozenset[str],
    candidate_counts: CandidateCounts,
    end_line: int,
) -> ObligationRecord:
    targets, broken_target_count = _invariant_targets(
        report,
        declaration,
        profile.test_roots,
        atomic_targets,
        atomic_code_invariant_ids,
    )
    binds = tuple(
        item for item in report.binds if item.invariant_id == declaration.invariant_id
    )
    blockers: list[BlockingReason] = []
    guidance: list[GuidanceCode] = []
    if not targets or broken_target_count:
        blockers.append(
            BlockingReason(
                "INVARIANT_TARGET_MISSING", "implementation", "invariant_bind"
            )
        )
        guidance.append("ADD_INVARIANT_BIND")
    if not binds:
        blockers.append(
            BlockingReason("BINDING_TEST_MISSING", "binding_test", "binding_test")
        )
        guidance.append("ADD_BINDING_TEST")

    if targets and binds and not broken_target_count:
        alignment_state: AlignmentState = "complete"
    elif targets or binds or broken_target_count:
        alignment_state = "partial"
    else:
        alignment_state = "untraced"

    rung = _rung_for_invariant(
        declaration, sections, profile, section_meta, meta_spec_globs
    )
    disposition: Disposition = "skipped" if skipped else "evaluate"
    if rung != "active":
        blockers.append(BlockingReason("OUT_OF_GATE_SCOPE"))
    if skipped:
        blockers.append(BlockingReason("SKIPPED"))
        guidance.append("REVIEW_SKIP_REASON")
    guidance.append("RUN_DETERMINISTIC_CHECK")
    if alignment_state == "complete" and rung == "active" and not skipped:
        guidance.append("RUN_CURRENT_ANALYSIS")

    return ObligationRecord(
        obligation_id=_invariant_id(declaration),
        kind="invariant",
        path=declaration.path,
        start_line=declaration.line,
        end_line=end_line,
        title=None,
        intent_state="identified",
        alignment_state=alignment_state,
        disposition=disposition,
        obligation_rung=rung,
        gate_state=_gate_state(
            alignment_state=alignment_state,
            disposition=disposition,
            rung=rung,
        ),
        required_roles=("implementation", "binding_test"),
        evidence_counts=EvidenceCounts(
            len(targets) + broken_target_count, 0, len(binds)
        ),
        candidate_counts=candidate_counts,
        blocking_reasons=_sort_blockers(blockers),
        next_actions=_sort_guidance(guidance),
    )


def _unaddressable_intent(
    issues: Sequence[Issue],
    excerpts: Mapping[tuple[str, str, int | None, int], str],
) -> tuple[UnaddressableIntent, ...]:
    ordinals: dict[tuple[str, str, int | None], int] = {}
    rows: list[UnaddressableIntent] = []
    for issue in issues:
        if not is_unaddressable_issue(issue):
            continue
        base = (issue.code, issue.path, issue.line)
        ordinal = ordinals.get(base, 0)
        ordinals[base] = ordinal + 1
        identity_preimage = {
            "code": issue.code,
            "path": issue.path,
            "line": issue.line,
            "ordinal": ordinal,
        }
        entry_identity = (
            "unaddressable:sha256:"
            + hashlib.sha256(canonical_json_bytes(identity_preimage)).hexdigest()
        )
        rows.append(
            UnaddressableIntent(
                entry_identity,
                issue.code,
                issue.path,
                issue.line,
                issue.message,
                excerpts.get((issue.code, issue.path, issue.line, ordinal), ""),
            )
        )
    return tuple(rows)


def _validate_required_roles(
    roles: tuple[Literal["implementation", "test"], ...],
) -> None:
    if roles not in {("implementation",), ("implementation", "test")}:
        raise ValueError(
            "section_required_roles must be ('implementation',) or "
            "('implementation', 'test')"
        )


def build_obligation_inventory(  # noqa: C901 approved [SC-17.1] RUFF-SUP-055 exception
    report: Report,
    *,
    profile: ProfileConfig,
    snapshot: SnapshotIdentity,
    section_required_roles: tuple[Literal["implementation", "test"], ...] = (
        "implementation",
    ),
    section_meta: frozenset[tuple[str, str]] = frozenset(),
    meta_spec_globs: tuple[str, ...] | None = None,
    skipped_obligation_ids: frozenset[str] = frozenset(),
    candidate_counts: Mapping[str, CandidateCounts] | None = None,
    source_end_lines: Mapping[str, int] | None = None,
    unaddressable_excerpts: Mapping[tuple[str, str, int | None, int], str]
    | None = None,
    atomic_invariant_targets: frozenset[tuple[str, str | None]] = frozenset(),
    atomic_code_invariant_ids: frozenset[str] = frozenset(),
    suppression_declarations: tuple[SuppressionDeclaration, ...] = (),
    suppression_decisions: tuple[SuppressionDecision, ...] = (),
) -> ObligationInventory:
    """Project one raw resolved report into deterministic obligation records.

    ``section_meta``, ``meta_spec_globs``, and ``skipped_obligation_ids`` are
    parser-owned hooks that
    are intentionally separate from ``Report.issues``.  They must come from the
    same captured scan as ``report``.  ``source_end_lines`` and
    ``unaddressable_excerpts`` likewise let the snapshot owner add presentation
    facts without this module reopening source.
    """

    _validate_required_roles(section_required_roles)
    if meta_spec_globs is None:
        meta_spec_globs = profile.meta_spec_globs
    candidate_counts = candidate_counts or {}
    source_end_lines = source_end_lines or {}
    unaddressable_excerpts = unaddressable_excerpts or {}

    duplicate_section_ids = {
        issue.section_id
        for issue in report.issues
        if issue.code == "SPEC_SECTION_DUPLICATE" and issue.section_id is not None
    }
    colliding_invariant_ids = {
        issue.invariant_id
        for issue in report.issues
        if issue.code == "INVARIANT_DUPLICATE" and issue.invariant_id is not None
    }
    invalid_section_ids = duplicate_section_ids | colliding_invariant_ids
    invalid_invariant_ids = colliding_invariant_ids

    valid_sections = tuple(
        section
        for section in report.spec_sections
        if section.section_id not in invalid_section_ids
    )
    section_index = {
        (section.path, section.section_id): section for section in valid_sections
    }
    valid_invariants = tuple(
        declaration
        for declaration in report.invariants
        if declaration.invariant_id not in invalid_invariant_ids
    )

    ordinary_ids = {_section_id(section) for section in valid_sections} | {
        _invariant_id(declaration) for declaration in valid_invariants
    }
    declarations_by_reference = {
        declaration.reference: declaration for declaration in suppression_declarations
    }
    decisions_by_reference: dict[str, list[SuppressionDecision]] = {}
    for decision in suppression_decisions:
        if decision.declaration is None or decision.rule is None:
            continue
        if decision.rule.declaration != decision.declaration:
            raise ValueError("suppression decision rule/declaration mismatch")
        if decision.declaration not in declarations_by_reference:
            raise ValueError(
                "suppression decision names an unresolved declaration: "
                f"{decision.declaration}"
            )
        decisions_by_reference.setdefault(decision.declaration, []).append(decision)
    suppression_ids = {
        f"suppression::{reference}" for reference in decisions_by_reference
    }
    known_ids = ordinary_ids | suppression_ids
    unknown_skips = skipped_obligation_ids - known_ids
    if unknown_skips:
        rendered = ", ".join(sorted(unknown_skips))
        raise ValueError(f"skipped obligation IDs are not addressable: {rendered}")
    suppression_skips = skipped_obligation_ids & suppression_ids
    if suppression_skips:
        rendered = ", ".join(sorted(suppression_skips))
        raise ValueError(f"suppression obligations cannot be skipped: {rendered}")
    unknown_counts = set(candidate_counts) - ordinary_ids
    if unknown_counts:
        rendered = ", ".join(sorted(unknown_counts))
        raise ValueError(f"candidate counts name unknown obligations: {rendered}")

    records: list[ObligationRecord] = []
    for section in valid_sections:
        obligation_id = _section_id(section)
        end_line = source_end_lines.get(obligation_id, section.line)
        if end_line < section.line:
            raise ValueError(f"source end line precedes start for {obligation_id}")
        records.append(
            _section_record(
                report,
                section,
                profile=profile,
                required_roles=section_required_roles,
                section_meta=section_meta,
                meta_spec_globs=meta_spec_globs,
                skipped=obligation_id in skipped_obligation_ids,
                candidate_counts=candidate_counts.get(obligation_id, CandidateCounts()),
                end_line=end_line,
            )
        )

    for declaration in valid_invariants:
        obligation_id = _invariant_id(declaration)
        skipped = obligation_id in skipped_obligation_ids
        if skipped and declaration.declaration_kind == "code":
            raise ValueError(
                f"code-only invariant {obligation_id} cannot carry a source skip"
            )
        end_line = source_end_lines.get(obligation_id, declaration.line)
        if end_line < declaration.line:
            raise ValueError(f"source end line precedes start for {obligation_id}")
        records.append(
            _invariant_record(
                report,
                declaration,
                sections=section_index,
                profile=profile,
                section_meta=section_meta,
                meta_spec_globs=meta_spec_globs,
                skipped=skipped,
                atomic_targets=atomic_invariant_targets,
                atomic_code_invariant_ids=atomic_code_invariant_ids,
                candidate_counts=candidate_counts.get(obligation_id, CandidateCounts()),
                end_line=end_line,
            )
        )

    for reference, decisions in decisions_by_reference.items():
        suppression_declaration = declarations_by_reference[reference]
        rules_by_bytes = {
            canonical_json_bytes(suppression_rule_row(decision.rule)): decision.rule
            for decision in decisions
            if decision.rule is not None
        }
        rules = tuple(rules_by_bytes[key] for key in sorted(rules_by_bytes))
        records.append(
            ObligationRecord(
                obligation_id=f"suppression::{reference}",
                kind="suppression",
                path=suppression_declaration.path,
                start_line=suppression_declaration.start_line,
                end_line=suppression_declaration.end_line,
                title=suppression_declaration.owner_title,
                intent_state="identified",
                alignment_state="complete",
                disposition="evaluate",
                obligation_rung="active",
                gate_state="executable",
                required_roles=(),
                evidence_counts=EvidenceCounts(),
                candidate_counts=CandidateCounts(),
                blocking_reasons=(),
                next_actions=(
                    "RUN_DETERMINISTIC_CHECK",
                    "RUN_CURRENT_ANALYSIS",
                ),
                suppression=SuppressionObligationDetail(
                    declaration=suppression_declaration,
                    rules=rules,
                    matched_issue_count=len(decisions),
                ),
            )
        )

    records.sort(
        key=lambda item: (item.path, item.start_line, item.kind, item.obligation_id)
    )
    unaddressable = _unaddressable_intent(report.issues, unaddressable_excerpts)
    if records or unaddressable:
        actions = _sort_guidance(
            [action for record in records for action in record.next_actions]
            + [item.action for item in unaddressable]
        )
    else:
        actions = ("ADD_OR_CONFIGURE_SPEC_INTENT",)
    return ObligationInventory(snapshot, tuple(records), unaddressable, actions)
