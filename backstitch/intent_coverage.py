"""Pure intent-coverage classification over canonical definitions and trace facts.

Spec: docs/specs/08-intent-coverage.md [COV-3], [COV-4], [COV-6]
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import PurePosixPath
from typing import Literal

from backstitch.canonical import canonical_json_bytes
from backstitch.git_baseline import edge_identity
from backstitch.models import Edge, Report
from backstitch.python_refs import CanonicalPythonDefinition

DefinitionKind = Literal[
    "module",
    "class",
    "function",
    "async_function",
    "method",
    "async_method",
]
DefinitionRole = Literal["production", "test"]
CoverageClassification = Literal["direct", "inherited", "exempt", "uncovered"]
RequirementState = Literal[
    "implemented",
    "absent_mapping",
    "declared_without_live_owner",
]


@dataclass(frozen=True, slots=True)
class CoverageDefinition:
    """One canonical Python definition supplied by the shared parser owner."""

    definition_id: str
    path: str
    structural_locator: str
    qualname: str | None
    kind: DefinitionKind
    role: DefinitionRole
    start_line: int
    end_line: int
    source_projection_sha256: str
    parent_definition_id: str | None
    tree: str = ""


@dataclass(frozen=True, slots=True)
class ClassifiedDefinition:
    """One definition plus its deterministic intent classification."""

    definition: CoverageDefinition
    classification: CoverageClassification
    governing_edge_ids: tuple[str, ...] = ()
    matching_exemption_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CoverageExemptionFact:
    """One valid exemption joined to canonical definition identities."""

    exemption_id: str
    matched_definition_ids: tuple[str, ...]
    origin: Literal["inline", "config_path", "config_glob"] = "config_path"
    path: str = ""
    line: int | None = None
    selector: str = ""
    reason: str = ""


@dataclass(frozen=True, slots=True)
class CoverageExemptionResult:
    """One valid exemption and its complete deterministic audit state."""

    exemption_id: str
    origin: Literal["inline", "config_path", "config_glob"]
    path: str
    line: int | None
    selector: str
    reason: str
    matched_definition_ids: tuple[str, ...]
    state: Literal["used", "overlap_only", "unused"]


@dataclass(frozen=True, slots=True)
class IntentCoverageResult:
    """The pure repository-state coverage result before rendering or Git."""

    definitions: tuple[ClassifiedDefinition, ...]
    worklist: tuple[str, ...]
    summary: CoverageCounts
    requirements: tuple[RequirementCoverage, ...]
    exemptions: tuple[CoverageExemptionResult, ...]


@dataclass(frozen=True, slots=True)
class CoverageCounts:
    """Exact integer metric inputs; renderers may derive display rates."""

    direct: int
    inherited: int
    exempt: int
    uncovered: int
    total: int
    direct_numerator: int
    accounted_numerator: int


@dataclass(frozen=True, slots=True)
class RequirementCoverage:
    """One spec requirement's implementation-side coverage state."""

    requirement_id: str
    path: str
    section_id: str
    rung: Literal["active", "planned", "exploratory", "meta"]
    implementation_state: RequirementState
    owner_definition_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CoverageFloorFact:
    """One configured scope and its optional exact enforcement targets."""

    scope: str
    direct_target: float | None
    accounted_target: float | None


@dataclass(frozen=True, slots=True)
class CoverageFloorResult:
    """One exact floor evaluation before presentation-rate rounding."""

    scope: str
    counts: CoverageCounts
    direct_target: float | None
    accounted_target: float | None
    passes: bool


@dataclass(frozen=True, slots=True)
class CoverageUnscannableFile:
    """One in-scope file omitted from the definition denominator."""

    path: str
    role: DefinitionRole
    tree: str
    issue_identities: tuple[tuple[str, str, int | None], ...]


def coverage_definitions_from_python_inventory(
    inventory: tuple[CanonicalPythonDefinition, ...],
    *,
    role: DefinitionRole,
    tree: str,
) -> tuple[CoverageDefinition, ...]:
    """Project canonical parser facts into stable coverage identities."""

    definition_id_by_locator = {
        item.structural_locator: _stable_id(
            ["intent-definition-v1", item.path, item.structural_locator]
        )
        for item in inventory
    }
    raw_kind_by_locator = {item.structural_locator: item.kind for item in inventory}
    rows: list[CoverageDefinition] = []
    for item in inventory:
        parent_kind = (
            raw_kind_by_locator.get(item.parent_locator)
            if item.parent_locator is not None
            else None
        )
        if item.kind == "module":
            kind: DefinitionKind = "module"
        elif item.kind == "class":
            kind = "class"
        elif item.kind == "async-function":
            kind = "async_method" if parent_kind == "class" else "async_function"
        else:
            kind = "method" if parent_kind == "class" else "function"
        rows.append(
            CoverageDefinition(
                definition_id=definition_id_by_locator[item.structural_locator],
                path=item.path,
                structural_locator=item.structural_locator,
                qualname=item.qualname,
                kind=kind,
                role=role,
                start_line=item.start_line,
                end_line=item.end_line,
                source_projection_sha256=item.source_projection_sha256,
                parent_definition_id=(
                    definition_id_by_locator[item.parent_locator]
                    if item.parent_locator is not None
                    else None
                ),
                tree=tree,
            )
        )
    return tuple(rows)


def classify_intent_coverage(
    definitions: tuple[CoverageDefinition, ...],
    report: Report,
    *,
    exemptions: tuple[CoverageExemptionFact, ...] = (),
    inherited_counts: bool = False,
    requirement_rungs: Mapping[
        tuple[str, str],
        Literal["active", "planned", "exploratory", "meta"],
    ]
    | None = None,
) -> IntentCoverageResult:
    """Classify canonical definitions using an already resolved trace report."""

    classified = _propagate_direct_owners(_classify_definitions(definitions, report))
    classified, exemption_results = _apply_exemptions(classified, exemptions)
    worklist = tuple(
        item.definition.definition_id
        for item in sorted(
            (row for row in classified if row.classification == "uncovered"),
            key=lambda row: (
                0 if row.definition.role == "production" else 1,
                row.definition.path,
                row.definition.structural_locator,
            ),
        )
    )
    counts = {
        classification: sum(
            item.classification == classification for item in classified
        )
        for classification in ("direct", "inherited", "exempt", "uncovered")
    }
    direct = counts["direct"]
    inherited = counts["inherited"]
    exempt = counts["exempt"]
    return IntentCoverageResult(
        definitions=classified,
        worklist=worklist,
        summary=CoverageCounts(
            direct=direct,
            inherited=inherited,
            exempt=exempt,
            uncovered=counts["uncovered"],
            total=len(classified),
            direct_numerator=direct,
            accounted_numerator=direct
            + exempt
            + (inherited if inherited_counts else 0),
        ),
        requirements=_classify_requirements(
            classified,
            report,
            requirement_rungs=requirement_rungs or {},
        ),
        exemptions=exemption_results,
    )


def evaluate_coverage_floors(
    result: IntentCoverageResult,
    floors: tuple[CoverageFloorFact, ...],
    *,
    inherited_counts: bool,
) -> tuple[CoverageFloorResult, ...]:
    """Evaluate configured floors from integer counts, never rounded rates."""

    rows: list[CoverageFloorResult] = []
    for floor in sorted(floors, key=lambda item: item.scope):
        scope = PurePosixPath(floor.scope)
        definitions = tuple(
            item
            for item in result.definitions
            if PurePosixPath(item.definition.path).is_relative_to(scope)
        )
        counts_by_name = {
            name: sum(item.classification == name for item in definitions)
            for name in ("direct", "inherited", "exempt", "uncovered")
        }
        direct = counts_by_name["direct"]
        inherited = counts_by_name["inherited"]
        exempt = counts_by_name["exempt"]
        total = len(definitions)
        accounted = direct + exempt + (inherited if inherited_counts else 0)
        direct_passes = _meets_floor(direct, total, floor.direct_target)
        accounted_passes = _meets_floor(
            accounted,
            total,
            floor.accounted_target,
        )
        rows.append(
            CoverageFloorResult(
                scope=floor.scope,
                counts=CoverageCounts(
                    direct=direct,
                    inherited=inherited,
                    exempt=exempt,
                    uncovered=counts_by_name["uncovered"],
                    total=total,
                    direct_numerator=direct,
                    accounted_numerator=accounted,
                ),
                direct_target=floor.direct_target,
                accounted_target=floor.accounted_target,
                passes=direct_passes and accounted_passes,
            )
        )
    return tuple(rows)


def _meets_floor(numerator: int, denominator: int, target: float | None) -> bool:
    if target is None:
        return True
    if denominator == 0:
        return Decimal(str(target)) == 0
    return Decimal(numerator) >= Decimal(str(target)) * Decimal(denominator)


def _classify_requirements(
    definitions: tuple[ClassifiedDefinition, ...],
    report: Report,
    *,
    requirement_rungs: Mapping[
        tuple[str, str],
        Literal["active", "planned", "exploratory", "meta"],
    ],
) -> tuple[RequirementCoverage, ...]:
    mapping_keys = {(item.spec_path, item.section_id) for item in report.spec_mappings}
    edges_by_requirement: dict[tuple[str, str], list[Edge]] = {}
    for edge in report.edges:
        if edge.kind == "mapping":
            edges_by_requirement.setdefault(
                (edge.spec_path, edge.section_id), []
            ).append(edge)
    rows: list[RequirementCoverage] = []
    for section in sorted(
        report.spec_sections,
        key=lambda item: (item.path, item.section_id),
    ):
        key = (section.path, section.section_id)
        edges = edges_by_requirement.get(key, [])
        owners = tuple(
            sorted(
                {
                    item.definition.definition_id
                    for item in definitions
                    if any(
                        edge.code_path == item.definition.path
                        and (
                            (
                                edge.code_symbol is None
                                and item.definition.kind == "module"
                            )
                            or (
                                edge.code_symbol is not None
                                and edge.code_symbol == item.definition.qualname
                            )
                        )
                        for edge in edges
                    )
                }
            )
        )
        state: RequirementState
        if owners:
            state = "implemented"
        elif key in mapping_keys:
            state = "declared_without_live_owner"
        else:
            state = "absent_mapping"
        rows.append(
            RequirementCoverage(
                requirement_id=_stable_id(
                    ["intent-requirement-v1", section.path, section.section_id]
                ),
                path=section.path,
                section_id=section.section_id,
                rung=requirement_rungs.get(key, "active"),
                implementation_state=state,
                owner_definition_ids=owners,
            )
        )
    return tuple(rows)


def _apply_exemptions(
    definitions: tuple[ClassifiedDefinition, ...],
    exemptions: tuple[CoverageExemptionFact, ...],
) -> tuple[
    tuple[ClassifiedDefinition, ...],
    tuple[CoverageExemptionResult, ...],
]:
    known_ids = {item.definition.definition_id for item in definitions}
    matches: dict[str, list[str]] = {}
    for exemption in exemptions:
        for definition_id in exemption.matched_definition_ids:
            if definition_id in known_ids:
                matches.setdefault(definition_id, []).append(exemption.exemption_id)
    projected = tuple(
        replace(
            item,
            classification=(
                item.classification
                if item.classification == "direct"
                or not matches.get(item.definition.definition_id)
                else "exempt"
            ),
            matching_exemption_ids=tuple(
                sorted(matches.get(item.definition.definition_id, ()))
            ),
        )
        for item in definitions
    )
    direct_ids = {
        item.definition.definition_id
        for item in definitions
        if item.classification == "direct"
    }
    results = tuple(
        CoverageExemptionResult(
            exemption_id=item.exemption_id,
            origin=item.origin,
            path=item.path,
            line=item.line,
            selector=item.selector,
            reason=item.reason,
            matched_definition_ids=tuple(
                sorted(set(item.matched_definition_ids) & known_ids)
            ),
            state=(
                "unused"
                if not set(item.matched_definition_ids) & known_ids
                else (
                    "overlap_only"
                    if set(item.matched_definition_ids) & known_ids <= direct_ids
                    else "used"
                )
            ),
        )
        for item in sorted(exemptions, key=lambda row: row.exemption_id)
    )
    return projected, results


def _propagate_direct_owners(
    definitions: tuple[ClassifiedDefinition, ...],
) -> tuple[ClassifiedDefinition, ...]:
    by_id = {item.definition.definition_id: item for item in definitions}
    changed = True
    while changed:
        changed = False
        for definition_id, item in tuple(by_id.items()):
            if item.classification == "direct":
                continue
            parent_id = item.definition.parent_definition_id
            parent = by_id.get(parent_id) if parent_id is not None else None
            if (
                parent is None
                or parent.definition.kind == "module"
                or parent.classification != "direct"
            ):
                continue
            by_id[definition_id] = replace(
                item,
                classification="direct",
                governing_edge_ids=parent.governing_edge_ids,
            )
            changed = True
    return tuple(by_id[item.definition.definition_id] for item in definitions)


def _classify_definitions(  # noqa: C901 approved [SC-17.1] RUFF-SUP-046 exception
    definitions: tuple[CoverageDefinition, ...],
    report: Report,
) -> tuple[ClassifiedDefinition, ...]:
    by_path: dict[str, list[CoverageDefinition]] = {}
    for definition in definitions:
        by_path.setdefault(definition.path, []).append(definition)
    direct: dict[str, set[str]] = {}
    inherited: dict[str, set[str]] = {}

    def add_inherited(path: str, edge: Edge) -> None:
        path_definitions = by_path.get(path, [])
        module = next(
            (item for item in path_definitions if item.kind == "module"),
            None,
        )
        if module is None:
            return
        edge_id = _edge_id(edge, module.structural_locator)
        for candidate in path_definitions:
            inherited.setdefault(candidate.definition_id, set()).add(edge_id)

    for edge in report.edges:
        if edge.kind == "mapping" and edge.code_symbol is None:
            add_inherited(edge.code_path, edge)
            continue
        if edge.kind == "backlink" and edge.code_symbol == "module":
            add_inherited(edge.code_path, edge)
            continue
        path_definitions = by_path.get(edge.code_path, [])
        if edge.kind == "mapping":
            candidates = tuple(
                item for item in path_definitions if item.qualname == edge.code_symbol
            )
        else:
            candidates = _smallest_physical_owners(
                tuple(
                    item
                    for item in path_definitions
                    if item.qualname == edge.code_symbol
                    and item.start_line <= edge.line <= item.end_line
                )
            )
        for candidate in candidates:
            direct.setdefault(candidate.definition_id, set()).add(
                _edge_id(edge, candidate.structural_locator)
            )

    for invariant in report.invariants:
        if invariant.declaration_kind != "code":
            continue
        candidates = _smallest_physical_owners(
            tuple(
                definition
                for definition in by_path.get(invariant.path, [])
                if (
                    definition.qualname == invariant.owner_symbol
                    or (
                        invariant.owner_symbol in {None, "<module>", "module"}
                        and definition.kind == "module"
                    )
                )
                and definition.start_line <= invariant.line <= definition.end_line
            )
        )
        for candidate in candidates:
            direct.setdefault(candidate.definition_id, set()).add(
                _stable_id(
                    [
                        "intent-invariant-owner-v1",
                        invariant.invariant_id,
                        invariant.path,
                        candidate.structural_locator,
                    ]
                )
            )
    for binding in report.binds:
        candidates = _smallest_physical_owners(
            tuple(
                definition
                for definition in by_path.get(binding.test_path, [])
                if definition.qualname == binding.test_symbol
                and definition.start_line == binding.start_line
                and definition.end_line == binding.end_line
            )
        )
        for candidate in candidates:
            direct.setdefault(candidate.definition_id, set()).add(
                _stable_id(
                    [
                        "intent-invariant-bind-v1",
                        binding.invariant_id,
                        binding.test_path,
                        candidate.structural_locator,
                    ]
                )
            )
    return tuple(
        ClassifiedDefinition(
            definition=item,
            classification=(
                "direct"
                if direct.get(item.definition_id)
                else ("inherited" if inherited.get(item.definition_id) else "uncovered")
            ),
            governing_edge_ids=tuple(
                sorted(
                    direct.get(item.definition_id)
                    or inherited.get(item.definition_id)
                    or ()
                )
            ),
        )
        for item in definitions
    )


def _smallest_physical_owners(
    candidates: tuple[CoverageDefinition, ...],
) -> tuple[CoverageDefinition, ...]:
    if not candidates:
        return ()
    smallest_span = min(item.end_line - item.start_line for item in candidates)
    smallest = tuple(
        item for item in candidates if item.end_line - item.start_line == smallest_span
    )
    first_bounds = (smallest[0].start_line, smallest[0].end_line)
    same_bounds = tuple(
        item for item in smallest if (item.start_line, item.end_line) == first_bounds
    )
    return same_bounds if len(same_bounds) == len(smallest) else ()


def _edge_id(edge: Edge, structural_locator: str) -> str:
    return edge_identity(
        edge.spec_path,
        edge.section_id,
        edge.code_path,
        structural_locator,
    )


def _stable_id(preimage: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(preimage)).hexdigest()
