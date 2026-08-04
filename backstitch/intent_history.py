"""Revision-state projections for intent-coverage policy and drift.

Spec: docs/specs/08-intent-coverage.md [COV-5], [COV-8]
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from backstitch.canonical import canonical_json_bytes
from backstitch.check_pipeline import scan_check_report_from_snapshot
from backstitch.config import ProfileConfig
from backstitch.evidence_discovery import resolved_python_module_names
from backstitch.git_baseline import (
    DriftEvent,
    DriftState,
    DriftTransition,
    GitTransition,
    StaleDocTrend,
    compute_drift_event,
    connected_test_identity,
    edge_identity,
    mapping_identity,
    section_projection_hash,
)
from backstitch.intent_coverage import (
    CoverageDefinition,
    classify_intent_coverage,
    coverage_definitions_from_python_inventory,
)
from backstitch.markdown_specs import MarkdownParseMemo, parse_markdown_spec_bytes
from backstitch.profiles import get_profile
from backstitch.python_refs import python_definition_inventory_bytes
from backstitch.repository_snapshot import (
    FileStat,
    RepositorySnapshot,
    SnapshotFile,
    SnapshotPath,
)
from backstitch.scan_exclusions import is_excluded
from backstitch.settings import (
    BackstitchSettings,
    resolve_repository_config_from_blobs,
)


@dataclass(frozen=True, slots=True)
class IntentRevisionState:
    """One immutable source revision projected into exact drift inputs."""

    profile: ProfileConfig
    definitions: Mapping[str, CoverageDefinition]
    drift_states: Mapping[str, DriftState]
    section_rows: Mapping[tuple[str, str], tuple[str, int]]
    edge_sections: Mapping[str, tuple[str, str]]
    path_edges: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class StaleHistoryWork:
    """Deterministic work facts proving the history fold is path-indexed."""

    definitions_indexed: int
    edges_indexed: int
    transitions_indexed: int
    changed_paths_indexed: int
    edge_transitions_evaluated: int


@dataclass(frozen=True, slots=True)
class StaleHistoryResult:
    """Bounded stale-document trends and their exact work accounting."""

    trends: tuple[StaleDocTrend, ...]
    work: StaleHistoryWork


@dataclass(slots=True)
class IntentRevisionProjector:
    """Cache immutable revision projections across overlapping history walks."""

    _states: dict[str, IntentRevisionState]
    _markdown_parse_memo: MarkdownParseMemo
    _python_parse_memo: dict[tuple[str, str], Any]
    projection_builds: int
    cache_hits: int

    def __init__(self) -> None:
        self._states = {}
        self._markdown_parse_memo = {}
        self._python_parse_memo = {}
        self.projection_builds = 0
        self.cache_hits = 0

    def project(
        self,
        revision_id: str,
        blobs: Mapping[str, bytes],
        *,
        repo_root: Path,
        settings: BackstitchSettings,
    ) -> IntentRevisionState:
        """Return one revision state, reusing commit projections by identity."""

        cached = self._states.get(revision_id)
        if cached is not None:
            self.cache_hits += 1
            return cached
        state = build_intent_revision_state(
            blobs,
            repo_root=repo_root,
            settings=settings,
            markdown_parse_memo=self._markdown_parse_memo,
            python_parse_memo=self._python_parse_memo,
        )
        self._states[revision_id] = state
        self.projection_builds += 1
        return state


def build_intent_revision_state(
    blobs: Mapping[str, bytes],
    *,
    repo_root: Path,
    settings: BackstitchSettings,
    markdown_parse_memo: MarkdownParseMemo | None = None,
    python_parse_memo: dict[tuple[str, str], Any] | None = None,
) -> IntentRevisionState:
    """Build one deterministic graph and all exact COV-8 state hashes."""

    profile = _configured_profile(settings)
    snapshot = _snapshot_from_blobs(blobs, settings=settings, profile=profile)
    report, _artifacts = scan_check_report_from_snapshot(
        snapshot,
        repo_root.as_posix(),
        profile,
        settings,
        markdown_parse_memo=markdown_parse_memo,
        python_parse_memo=python_parse_memo,
    )
    python_paths = tuple(
        row.path
        for row in snapshot.files
        if row.path.endswith(".py")
        and any(
            PurePosixPath(row.path).is_relative_to(PurePosixPath(root))
            for root in profile.code_roots
        )
    )
    module_names = resolved_python_module_names(python_paths, profile, snapshot)
    definitions: list[CoverageDefinition] = []
    for path in python_paths:
        raw = snapshot.read_bytes(path)
        inventory = python_definition_inventory_bytes(
            raw,
            rel_path=path,
            module_name=module_names[path],
            parse_memo=python_parse_memo,
        )
        if inventory is None:
            continue
        definitions.extend(
            coverage_definitions_from_python_inventory(
                inventory,
                role=(
                    "test"
                    if any(
                        PurePosixPath(path).is_relative_to(PurePosixPath(root))
                        for root in profile.test_roots
                    )
                    else "production"
                ),
                tree=_longest_root(path, profile.code_roots),
            )
        )
    # Revision history needs edge ownership and requirement identities only.
    # Rungs, exemptions, and inherited accounting are current-policy report facts;
    # they must not change the exact COV-8 drift preimages reconstructed here.
    result = classify_intent_coverage(tuple(definitions), report)
    parsed_specs = {
        path: parse_markdown_spec_bytes(snapshot.read_bytes(path), path)
        for path in sorted({item.path for item in report.spec_sections})
    }
    section_hashes: dict[tuple[str, str], str] = {}
    section_rows: dict[tuple[str, str], tuple[str, int]] = {}
    for path, parsed in parsed_specs.items():
        source = snapshot.read_bytes(path)
        for section_id, start_line, end_line in parsed.section_spans:
            projection, digest = section_projection_hash(
                source,
                section_start_line=start_line,
                section_end_line=end_line,
                mapping_block_spans=parsed.mapping_block_spans,
                section_id=section_id,
            )
            section_hashes[(path, section_id)] = digest
            section_rows[(path, section_id)] = (digest, len(projection))
    mapping_hashes = {
        key: mapping_identity(
            tuple(
                (edge.code_path, edge.code_symbol)
                for edge in report.edges
                if edge.kind == "mapping" and (edge.spec_path, edge.section_id) == key
            )
        )
        for key in section_hashes
    }
    classified_by_id = {
        item.definition.definition_id: item for item in result.definitions
    }
    edge_sections: dict[str, tuple[str, str]] = {}
    edge_owner_definitions: dict[str, str] = {}
    for edge in report.edges:
        for definition in definitions:
            if definition.path != edge.code_path:
                continue
            edge_id = edge_identity(
                edge.spec_path,
                edge.section_id,
                edge.code_path,
                definition.structural_locator,
            )
            if edge_id in classified_by_id[definition.definition_id].governing_edge_ids:
                edge_sections[edge_id] = (edge.spec_path, edge.section_id)
                edge_owner_definitions[edge_id] = definition.definition_id
    connected: dict[tuple[str, str], set[tuple[str, str]]] = {
        key: set() for key in section_hashes
    }
    connected_paths: dict[tuple[str, str], set[str]] = {
        key: set() for key in section_hashes
    }
    for item in result.definitions:
        if item.definition.role != "test":
            continue
        for governing_edge in item.governing_edge_ids:
            section = edge_sections.get(governing_edge)
            if section is not None:
                connected.setdefault(section, set()).add(
                    (
                        item.definition.definition_id,
                        item.definition.source_projection_sha256,
                    )
                )
                connected_paths.setdefault(section, set()).add(item.definition.path)
    invariant_sections = {
        item.invariant_id: (item.path, item.section_id)
        for item in report.invariants
        if item.declaration_kind == "spec" and item.section_id is not None
    }
    definitions_by_path_symbol = {
        (item.path, item.qualname, item.start_line, item.end_line): item
        for item in definitions
    }
    for binding in report.binds:
        section = invariant_sections.get(binding.invariant_id)
        bound_definition = definitions_by_path_symbol.get(
            (
                binding.test_path,
                binding.test_symbol,
                binding.start_line,
                binding.end_line,
            )
        )
        if section is not None and bound_definition is not None:
            connected.setdefault(section, set()).add(
                (
                    bound_definition.definition_id,
                    bound_definition.source_projection_sha256,
                )
            )
            connected_paths.setdefault(section, set()).add(bound_definition.path)
    connected_hashes = {
        key: connected_test_identity(tuple(rows)) for key, rows in connected.items()
    }
    requirement_ids = {
        (item.path, item.section_id): item.requirement_id
        for item in result.requirements
    }
    drift_states: dict[str, DriftState] = {}
    edge_influence_paths: dict[str, set[str]] = {}
    for item in result.definitions:
        if item.definition.role != "production":
            continue
        for governing_edge in item.governing_edge_ids:
            if (
                edge_owner_definitions.get(governing_edge)
                != item.definition.definition_id
            ):
                continue
            section = edge_sections.get(governing_edge)
            if (
                section is None
                or section not in section_hashes
                or section not in requirement_ids
            ):
                continue
            drift_states[governing_edge] = DriftState(
                edge_id=governing_edge,
                requirement_id=requirement_ids[section],
                definition_id=item.definition.definition_id,
                section_hash=section_hashes[section],
                mapping_hash=mapping_hashes[section],
                implementation_hash=item.definition.source_projection_sha256,
                connected_test_hash=connected_hashes[section],
            )
            edge_influence_paths[governing_edge] = {
                section[0],
                item.definition.path,
                *connected_paths.get(section, set()),
            }
    path_edges: dict[str, list[str]] = {}
    for governing_edge, paths in edge_influence_paths.items():
        for path in paths:
            path_edges.setdefault(path, []).append(governing_edge)
    return IntentRevisionState(
        profile=profile,
        definitions={item.definition_id: item for item in definitions},
        drift_states=drift_states,
        section_rows=section_rows,
        edge_sections={edge_id: edge_sections[edge_id] for edge_id in drift_states},
        path_edges={
            path: tuple(sorted(edge_ids))
            for path, edge_ids in sorted(path_edges.items())
        },
    )


def fold_stale_doc_history(
    transitions: Sequence[
        tuple[GitTransition, IntentRevisionState, IntentRevisionState]
    ],
    *,
    current_state: IntentRevisionState,
    history_complete: bool,
) -> StaleHistoryResult:
    """Fold chronological history with path-to-edge indexes, never all edges."""

    events: dict[str, list[tuple[int, DriftEvent]]] = {}
    latest_section_change: dict[tuple[str, str], tuple[int, str]] = {}
    changed_paths_indexed = 0
    edge_transitions_evaluated = 0
    for index, (transition, before, after) in enumerate(transitions):
        changed_paths = tuple(path for path, _raw in transition.changes)
        changed_paths_indexed += len(changed_paths)
        candidate_edges: set[str] = set()
        for path in changed_paths:
            candidate_edges.update(before.path_edges.get(path, ()))
            candidate_edges.update(after.path_edges.get(path, ()))
            before_sections = {
                key: value
                for key, value in before.section_rows.items()
                if key[0] == path
            }
            after_sections = {
                key: value
                for key, value in after.section_rows.items()
                if key[0] == path
            }
            for section in before_sections.keys() | after_sections.keys():
                if before_sections.get(section) != after_sections.get(section):
                    latest_section_change[section] = (index, transition.commit)
        for edge_id in sorted(candidate_edges):
            before_state = before.drift_states.get(edge_id)
            after_state = after.drift_states.get(edge_id)
            if before_state is None or after_state is None:
                continue
            edge_transitions_evaluated += 1
            event = compute_drift_event(
                DriftTransition(
                    parent_commit=transition.parent_commit,
                    child_commit=transition.commit,
                    before=before_state,
                    after=after_state,
                    commit_message=transition.message,
                    current_diff=False,
                )
            )
            if event is not None and not event.acknowledged:
                events.setdefault(edge_id, []).append((index, event))

    commits_inspected = len(transitions)
    trends: list[StaleDocTrend] = []
    for edge_id in sorted(current_state.drift_states):
        section = current_state.edge_sections[edge_id]
        reset = latest_section_change.get(section)
        reset_index = -1 if reset is None else reset[0]
        unacknowledged = [
            event for index, event in events.get(edge_id, ()) if index >= reset_index
        ]
        trends.append(
            StaleDocTrend(
                edge_id=edge_id,
                section_change_commit=(None if reset is None else reset[1]),
                unacknowledged_event_count=len(unacknowledged),
                last_event_commit=(
                    unacknowledged[-1].transition_commit if unacknowledged else None
                ),
                history_complete=history_complete or reset is not None,
                commits_inspected=commits_inspected,
            )
        )
    return StaleHistoryResult(
        trends=tuple(trends),
        work=StaleHistoryWork(
            definitions_indexed=len(current_state.definitions),
            edges_indexed=len(current_state.drift_states),
            transitions_indexed=commits_inspected,
            changed_paths_indexed=changed_paths_indexed,
            edge_transitions_evaluated=edge_transitions_evaluated,
        ),
    )


def build_stale_doc_history(
    initial_blobs: Mapping[str, bytes],
    transitions: Sequence[GitTransition],
    *,
    repo_root: Path,
    config_path: str,
    current_state: IntentRevisionState,
    history_complete: bool,
    projector: IntentRevisionProjector,
    deadline: float,
) -> StaleHistoryResult:
    """Reconstruct bounded immutable history while reusing revision projections."""

    import time

    if not transitions:
        return fold_stale_doc_history(
            (),
            current_state=current_state,
            history_complete=history_complete,
        )

    def check_deadline() -> None:
        if time.monotonic() >= deadline:
            raise ValueError("intent coverage Git phase exceeded runtime budget")

    revision_blobs = dict(initial_blobs)
    check_deadline()
    settings = resolve_repository_config_from_blobs(
        repo_root,
        config_path,
        revision_blobs,
    )
    previous_state = projector.project(
        transitions[0].parent_commit,
        revision_blobs,
        repo_root=repo_root,
        settings=settings,
    )
    indexed: list[tuple[GitTransition, IntentRevisionState, IntentRevisionState]] = []
    for transition in transitions:
        check_deadline()
        for path, raw in transition.changes:
            if raw is None:
                revision_blobs.pop(path, None)
            else:
                revision_blobs[path] = raw
        settings = resolve_repository_config_from_blobs(
            repo_root,
            config_path,
            revision_blobs,
        )
        current_revision = projector.project(
            transition.commit,
            revision_blobs,
            repo_root=repo_root,
            settings=settings,
        )
        indexed.append((transition, previous_state, current_revision))
        previous_state = current_revision
    check_deadline()
    return fold_stale_doc_history(
        tuple(indexed),
        current_state=current_state,
        history_complete=history_complete,
    )


def _configured_profile(settings: BackstitchSettings) -> ProfileConfig:
    profile = get_profile(settings.profile or "backstitch-style-v1")
    overrides: dict[str, tuple[str, ...]] = {}
    for field in (
        "spec_roots",
        "plan_roots",
        "code_roots",
        "test_roots",
        "planned_spec_globs",
        "exploratory_spec_globs",
        "meta_spec_globs",
    ):
        value = getattr(settings.profile_overrides, field)
        if value is not None:
            overrides[field] = value
    return profile.with_overrides(**overrides) if overrides else profile


def _snapshot_from_blobs(
    blobs: Mapping[str, bytes],
    *,
    settings: BackstitchSettings,
    profile: ProfileConfig,
) -> RepositorySnapshot:
    files = tuple(
        SnapshotFile(
            path=path,
            state="readable",
            raw_bytes=raw,
            raw_sha256=hashlib.sha256(raw).hexdigest(),
            error_class=None,
            file_stat=FileStat(
                st_dev=0,
                st_ino=index + 1,
                file_type_and_permission_mode=0o100644,
                st_size=len(raw),
                st_mtime_ns=0,
                st_ctime_ns=0,
            ),
        )
        for index, (path, raw) in enumerate(sorted(blobs.items()))
        if not is_excluded(path, settings.exclude)
    )
    directories = {
        parent.as_posix()
        for row in files
        for parent in PurePosixPath(row.path).parents
        if parent.as_posix() not in {".", ""}
    }
    catalog = (
        *(SnapshotPath(path=path, kind="directory") for path in sorted(directories)),
        *(SnapshotPath(path=row.path, kind="regular_file") for row in files),
    )
    identity = canonical_json_bytes([[row.path, row.raw_sha256] for row in files])
    digest = hashlib.sha256(identity).hexdigest()
    identity_document = {
        "identity": "backstitch-repository-snapshot",
        "version": 1,
        "semantic_config": {
            "spec_roots": list(profile.spec_roots),
            "code_roots": list(profile.code_roots),
            "test_roots": list(profile.test_roots),
        },
    }
    return RepositorySnapshot(
        config_inputs=(),
        files=files,
        path_catalog=tuple(sorted(catalog, key=lambda row: (row.path, row.kind))),
        missing_roots=(),
        catalog_sha256=digest,
        snapshot_hash=digest,
        _identity_bytes=canonical_json_bytes(identity_document),
    )


def _longest_root(path: str, roots: tuple[str, ...]) -> str:
    pure = PurePosixPath(path)
    matches = [
        PurePosixPath(root)
        for root in roots
        if pure.is_relative_to(PurePosixPath(root))
    ]
    longest = max(len(item.parts) for item in matches)
    owners = sorted({item.as_posix() for item in matches if len(item.parts) == longest})
    if len(owners) != 1:
        raise ValueError(f"ambiguous code-root owner for {path}")
    return owners[0]
