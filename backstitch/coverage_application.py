"""Typed application seam for intent-coverage reports and ratchets.

Spec: docs/specs/02-backstitch-core.md [SC-5], [SC-17]
Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-8.7], [EVC-12.2]
Spec: docs/specs/08-intent-coverage.md [COV-1], [COV-2], [COV-3], [COV-5],
[COV-7], [COV-9]
"""

from __future__ import annotations

import dataclasses
import hashlib
import time
from collections.abc import Sequence
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
from typing import Any, Literal, TypeAlias

from backstitch import artifact_publication, obligation_runtime
from backstitch.canonical import canonical_json_bytes
from backstitch.check_pipeline import (
    apply_check_policy,
    scan_check_report_from_snapshot,
)
from backstitch.config import ProfileConfig
from backstitch.diagnostics import issue_with_policy
from backstitch.evidence_discovery import resolved_python_module_names
from backstitch.git_baseline import (
    DriftEvent,
    DriftTransition,
    GitBaseline,
    GitBaselineError,
    GitBaselineMetadata,
    GitLimits,
    PolicyEvent,
    PolicyTransition,
    StaleDocTrend,
    baseline_metadata,
    compute_drift_event,
    current_content_identity,
    fold_policy_transitions,
    load_git_baseline,
    policy_identity,
)
from backstitch.intent_coverage import (
    CoverageDefinition,
    CoverageExemptionFact,
    CoverageFloorFact,
    CoverageFloorResult,
    CoverageUnscannableFile,
    DefinitionRole,
    IntentCoverageResult,
    classify_intent_coverage,
    coverage_definitions_from_python_inventory,
    evaluate_coverage_floors,
)
from backstitch.intent_coverage_reporting import build_coverage_report
from backstitch.intent_history import (
    IntentRevisionProjector,
    build_stale_doc_history,
)
from backstitch.markdown_specs import MarkdownParseMemo
from backstitch.models import Issue, Report, Severity, issue_sort_key
from backstitch.profiles import configured_profile
from backstitch.python_refs import python_definition_inventory_bytes
from backstitch.repository_snapshot import (
    RepositorySnapshot,
    SnapshotCaptureError,
    SnapshotFile,
)
from backstitch.resolver import ScanArtifacts
from backstitch.settings import (
    BackstitchSettings,
    ConfigLoadError,
    resolve_repository_config_from_blobs,
)

__all__ = (
    "CoverageDocument",
    "CoverageFailure",
    "CoverageRequest",
    "CoverageResult",
    "INTENT_DIAGNOSTIC_CONTEXTS",
    "publish_coverage",
    "run_coverage",
)

INTENT_DIAGNOSTIC_CONTEXTS: dict[str, dict[str | None, Severity]] = {
    "INTENT_UNCOVERED_DEFINITION": {
        "repository": "info",
        "patch": "error",
    },
    "INTENT_INHERITED_ONLY": {
        "repository": "info",
        "patch": "error",
    },
    "INTENT_EXEMPTION_UNUSED": {None: "warning"},
    "INTENT_EXEMPTION_UNREASONED": {None: "error"},
    "INTENT_REQUIREMENT_UNIMPLEMENTED": {None: "info"},
    "INTENT_DRIFT_SUSPECT": {None: "info"},
    "INTENT_COVERAGE_FLOOR_REGRESSION": {None: "error"},
    "INTENT_COVERAGE_INCOMPLETE": {
        "repository": "info",
        "patch": "error",
    },
    "INTENT_COVERAGE_POLICY_REGRESSION": {None: "error"},
}

CoverageFailureStage: TypeAlias = Literal[
    "snapshot",
    "ratchet",
    "history",
    "drift",
    "publication",
]


def _intent_severity(code: str, context: str | None = None) -> Severity:
    """Return the declared default severity for one intent diagnostic."""

    try:
        return INTENT_DIAGNOSTIC_CONTEXTS[code][context]
    except KeyError:
        raise AssertionError(
            f"undeclared intent diagnostic context: {code}:{context}"
        ) from None


@dataclass(frozen=True, slots=True)
class CoverageRequest:
    """Resolved repository, profile, and settings for one coverage run."""

    repo_root: Path
    profile: ProfileConfig
    settings: BackstitchSettings


@dataclass(frozen=True, slots=True)
class CoverageDocument:
    """Validated report facts retained for CLI-owned rendering."""

    payload: dict[str, Any]
    source_result: IntentCoverageResult
    inherited_counts: bool
    floors: tuple[CoverageFloorResult, ...]
    unscannable_files: tuple[CoverageUnscannableFile, ...]
    issues: tuple[Issue, ...]
    baseline: GitBaselineMetadata | None
    changed_definition_ids: frozenset[str]
    policy_events: tuple[PolicyEvent, ...]
    drift_events: tuple[DriftEvent, ...]
    stale_doc_trends: tuple[StaleDocTrend, ...]
    spec_growth: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class CoverageResult:
    """One complete coverage document plus publication and gate decisions."""

    document: CoverageDocument
    output_path: Path | None
    blocks_gate: bool


@dataclass(frozen=True, slots=True)
class CoverageFailure:
    """One application failure classified before CLI exit presentation."""

    stage: CoverageFailureStage
    message: str


@dataclass(frozen=True, slots=True)
class _RepositoryState:
    snapshot: RepositorySnapshot
    raw_report: Report
    artifacts: ScanArtifacts
    python_rows: tuple[SnapshotFile, ...]
    definitions: tuple[CoverageDefinition, ...]
    exemptions: tuple[CoverageExemptionFact, ...]
    invalid_exemption_markers: tuple[tuple[str, int, str | None], ...]
    unscannable_paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _LoadedRatchet:
    baseline: GitBaseline | None
    deadline: float | None


@dataclass(frozen=True, slots=True)
class _RatchetState:
    baseline_source: GitBaseline | None
    changed_definition_ids: frozenset[str]
    baseline: GitBaselineMetadata | None
    policy_events: tuple[PolicyEvent, ...]
    drift_events: tuple[DriftEvent, ...]
    definition_locations: tuple[tuple[str, CoverageDefinition], ...]
    stale_doc_trends: tuple[StaleDocTrend, ...]
    spec_growth: dict[str, Any] | None


def _path_under_any(path: str, roots: Sequence[str]) -> bool:
    pure = PurePosixPath(path)
    return any(pure.is_relative_to(PurePosixPath(root)) for root in roots)


def _stable_id(preimage: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(preimage)).hexdigest()


def _requirement_rung(
    path: str,
    profile: ProfileConfig,
) -> Literal["active", "planned", "exploratory", "meta"]:
    if any(fnmatch(path, pattern) for pattern in profile.meta_spec_globs):
        return "meta"
    if any(fnmatch(path, pattern) for pattern in profile.planned_spec_globs):
        return "planned"
    if any(fnmatch(path, pattern) for pattern in profile.exploratory_spec_globs):
        return "exploratory"
    return "active"


def _git_limits(
    settings: BackstitchSettings,
    *,
    maximum_runtime_seconds: float | None = None,
) -> GitLimits:
    coverage = settings.coverage
    return GitLimits(
        maximum_baseline_files=coverage.maximum_baseline_files,
        maximum_file_bytes=coverage.maximum_file_bytes,
        maximum_baseline_bytes=coverage.maximum_baseline_bytes,
        maximum_history_commits=coverage.maximum_history_commits,
        maximum_git_command_seconds=coverage.maximum_git_command_seconds,
        maximum_git_commands=coverage.maximum_git_commands,
        maximum_git_output_bytes=coverage.maximum_git_output_bytes,
        maximum_commit_message_bytes=coverage.maximum_commit_message_bytes,
        maximum_runtime_seconds=(
            coverage.maximum_runtime_seconds
            if maximum_runtime_seconds is None
            else maximum_runtime_seconds
        ),
    )


def _policy_projection(
    settings: BackstitchSettings,
    profile: ProfileConfig,
) -> dict[str, object]:
    """Project the exact closed COV-5 policy mapping."""

    coverage = settings.coverage
    diagnostics = settings.diagnostics
    lint = settings.lint
    return {
        "schema": "intent-coverage-policy-v1",
        "profile": {
            "name": settings.profile,
            "spec_roots": list(profile.spec_roots),
            "code_roots": list(profile.code_roots),
            "test_roots": list(profile.test_roots),
            "planned_spec_globs": list(profile.planned_spec_globs),
            "exploratory_spec_globs": list(profile.exploratory_spec_globs),
            "meta_spec_globs": list(profile.meta_spec_globs),
            "process_spec_globs": list(
                settings.profile_overrides.process_spec_globs or ()
            ),
        },
        "exclude": list(settings.exclude),
        "coverage": {
            "mode": coverage.mode,
            "granularity": coverage.granularity,
            "inherited_counts": coverage.inherited_counts,
            "ratchet_base": coverage.ratchet_base,
            "exemptions": [
                {
                    "id": _stable_id(
                        [
                            "intent-exemption-v1",
                            ("config_path" if item.kind == "path" else "config_glob"),
                            item.selector,
                        ]
                    ),
                    "kind": item.kind,
                    "selector": item.selector,
                    "reason": item.reason,
                }
                for item in coverage.exemptions
            ],
            "floors": [
                {
                    "scope": item.scope,
                    "direct": item.direct,
                    "accounted": item.accounted,
                }
                for item in sorted(coverage.floors, key=lambda row: row.scope)
            ],
            "maximum_baseline_files": coverage.maximum_baseline_files,
            "maximum_file_bytes": coverage.maximum_file_bytes,
            "maximum_baseline_bytes": coverage.maximum_baseline_bytes,
            "maximum_history_commits": coverage.maximum_history_commits,
            "maximum_git_command_seconds": coverage.maximum_git_command_seconds,
            "maximum_git_commands": coverage.maximum_git_commands,
            "maximum_git_output_bytes": coverage.maximum_git_output_bytes,
            "maximum_commit_message_bytes": coverage.maximum_commit_message_bytes,
            "maximum_runtime_seconds": coverage.maximum_runtime_seconds,
        },
        "diagnostics": {
            "default_level": diagnostics.default_level,
            "fail_on": list(diagnostics.fail_on),
            "suppressible_levels": list(diagnostics.suppressible_levels),
            "levels": [
                {"selectors": list(item.selectors), "level": item.level}
                for item in diagnostics.levels
            ],
        },
        "suppressions": {
            "warn_unused_ignores": lint.warn_unused_ignores,
            "require_suppression_declarations": (lint.require_suppression_declarations),
            "per_file_ignores": [
                {"selector": selector, "codes": list(codes)}
                for selector, codes in sorted(lint.per_file_ignores.items())
            ],
            "per_section_ignores": [
                {"selector": selector, "codes": list(codes)}
                for selector, codes in sorted(lint.per_section_ignores.items())
            ],
            "rules": [
                {
                    "mechanism": item.mechanism,
                    "provenance": item.provenance,
                    "path": item.path,
                    "sections": list(item.sections),
                    "codes": list(item.codes),
                    "declaration": item.declaration,
                    "origin": {
                        "source": item.origin.source,
                        "position": item.origin.position,
                        "line": item.origin.line,
                    },
                }
                for item in lint.suppressions
            ],
        },
    }


def _current_blobs(
    head_blobs: dict[str, bytes],
    snapshot: RepositorySnapshot,
    settings: BackstitchSettings,
    profile: ProfileConfig,
    root: Path,
) -> dict[str, bytes]:
    """Overlay the accepted snapshot on HEAD without reopening source paths."""

    current = dict(head_blobs)
    roots = tuple(
        dict.fromkeys(
            (
                *profile.spec_roots,
                *profile.plan_roots,
                *profile.code_roots,
                *profile.test_roots,
            )
        )
    )
    for path in tuple(current):
        if _path_under_any(path, roots) and snapshot.path_kind(path) != "regular_file":
            current.pop(path)
    for row in snapshot.files:
        if row.raw_bytes is None:
            current.pop(row.path, None)
        else:
            current[row.path] = row.raw_bytes
    for identity in settings.config_layer_identities:
        try:
            path = Path(identity.path).resolve().relative_to(root).as_posix()
        except (OSError, ValueError) as exc:
            raise ValueError(
                "ratchet config layer must be inside the repository"
            ) from exc
        current[path] = identity.raw_bytes
    return current


def _check_deadline(deadline: float) -> None:
    if time.monotonic() > deadline:
        raise ValueError("intent coverage Git phase exceeded runtime budget")


def _longest_root(path: str, roots: Sequence[str]) -> str:
    pure = PurePosixPath(path)
    matches = [
        PurePosixPath(root)
        for root in roots
        if pure.is_relative_to(PurePosixPath(root))
    ]
    if not matches:
        raise ValueError(f"Python path is outside configured code roots: {path}")
    longest = max(len(root.parts) for root in matches)
    owners = sorted({root.as_posix() for root in matches if len(root.parts) == longest})
    if len(owners) != 1:
        raise ConfigLoadError(
            f"Python path has equal-specificity code-root owners: {path}"
        )
    return owners[0]


def _load_ratchet(
    root: Path,
    settings: BackstitchSettings,
) -> _LoadedRatchet | CoverageFailure:
    if settings.coverage.mode != "ratchet":
        return _LoadedRatchet(baseline=None, deadline=None)
    deadline = time.monotonic() + settings.coverage.maximum_runtime_seconds
    try:
        baseline = load_git_baseline(
            root,
            settings.coverage.ratchet_base,
            limits=_git_limits(
                settings,
                maximum_runtime_seconds=max(
                    deadline - time.monotonic(),
                    0.000_001,
                ),
            ),
        )
    except GitBaselineError as exc:
        return CoverageFailure(stage="ratchet", message=str(exc))
    return _LoadedRatchet(baseline=baseline, deadline=deadline)


def _project_definitions(
    snapshot: RepositorySnapshot,
    profile: ProfileConfig,
    settings: BackstitchSettings,
    python_parse_memo: dict[tuple[str, str], Any],
) -> tuple[
    tuple[SnapshotFile, ...],
    tuple[CoverageDefinition, ...],
    tuple[CoverageExemptionFact, ...],
    tuple[tuple[str, int, str | None], ...],
    tuple[str, ...],
]:
    python_rows = tuple(
        row
        for row in snapshot.files
        if row.path.endswith(".py") and _path_under_any(row.path, profile.code_roots)
    )
    module_names = resolved_python_module_names(
        tuple(row.path for row in python_rows),
        profile,
        snapshot,
    )
    definitions: list[CoverageDefinition] = []
    exemptions: list[CoverageExemptionFact] = []
    invalid_markers: list[tuple[str, int, str | None]] = []
    unscannable_paths: list[str] = []
    for row in python_rows:
        if row.raw_bytes is None:
            unscannable_paths.append(row.path)
            continue
        inventory = python_definition_inventory_bytes(
            row.raw_bytes,
            rel_path=row.path,
            module_name=module_names[row.path],
            parse_memo=python_parse_memo,
        )
        if inventory is None:
            unscannable_paths.append(row.path)
            continue
        role: DefinitionRole = (
            "test" if _path_under_any(row.path, profile.test_roots) else "production"
        )
        projected = coverage_definitions_from_python_inventory(
            inventory,
            role=role,
            tree=_longest_root(row.path, profile.code_roots),
        )
        definitions.extend(projected)
        definition_by_locator = {item.structural_locator: item for item in projected}
        for source_definition in inventory:
            owner = definition_by_locator[source_definition.structural_locator]
            for marker in source_definition.no_spec_markers:
                if not marker.valid or marker.reason is None:
                    invalid_markers.append((row.path, marker.line, owner.qualname))
                    continue
                exemptions.append(
                    CoverageExemptionFact(
                        exemption_id=_stable_id(
                            [
                                "intent-exemption-v1",
                                "inline",
                                row.path,
                                marker.line,
                                marker.reason,
                            ]
                        ),
                        matched_definition_ids=(owner.definition_id,),
                        origin="inline",
                        path=row.path,
                        line=marker.line,
                        selector=owner.structural_locator,
                        reason=marker.reason,
                    )
                )
    for configured in settings.coverage.exemptions:
        matched = tuple(
            sorted(
                item.definition_id
                for item in definitions
                if (
                    item.path == configured.selector
                    if configured.kind == "path"
                    else fnmatch(item.path, configured.selector)
                )
            )
        )
        origin: Literal["config_path", "config_glob"] = (
            "config_path" if configured.kind == "path" else "config_glob"
        )
        exemptions.append(
            CoverageExemptionFact(
                exemption_id=_stable_id(
                    ["intent-exemption-v1", origin, configured.selector]
                ),
                matched_definition_ids=matched,
                origin=origin,
                path=(
                    settings.config_path.as_posix()
                    if settings.config_path is not None
                    else ""
                ),
                line=None,
                selector=configured.selector,
                reason=configured.reason,
            )
        )
    return (
        python_rows,
        tuple(definitions),
        tuple(exemptions),
        tuple(invalid_markers),
        tuple(unscannable_paths),
    )


def _repository_state(
    root: Path,
    profile: ProfileConfig,
    settings: BackstitchSettings,
    snapshot: RepositorySnapshot,
    markdown_parse_memo: MarkdownParseMemo,
    python_parse_memo: dict[tuple[str, str], Any],
) -> _RepositoryState:
    raw_report, artifacts = scan_check_report_from_snapshot(
        snapshot,
        root.as_posix(),
        profile,
        settings,
        python_parse_memo=python_parse_memo,
        markdown_parse_memo=markdown_parse_memo,
    )
    (
        python_rows,
        definitions,
        exemptions,
        invalid_markers,
        unscannable_paths,
    ) = _project_definitions(snapshot, profile, settings, python_parse_memo)
    return _RepositoryState(
        snapshot=snapshot,
        raw_report=raw_report,
        artifacts=artifacts,
        python_rows=python_rows,
        definitions=definitions,
        exemptions=exemptions,
        invalid_exemption_markers=invalid_markers,
        unscannable_paths=unscannable_paths,
    )


def _empty_ratchet() -> _RatchetState:
    return _RatchetState(
        baseline_source=None,
        changed_definition_ids=frozenset(),
        baseline=None,
        policy_events=(),
        drift_events=(),
        definition_locations=(),
        stale_doc_trends=(),
        spec_growth=None,
    )


def _config_path(
    root: Path,
    settings: BackstitchSettings,
) -> str | CoverageFailure:
    if settings.config_path is None:
        return CoverageFailure(
            stage="ratchet",
            message="ratchet mode requires a repository config file",
        )
    try:
        return settings.config_path.resolve().relative_to(root).as_posix()
    except (OSError, ValueError):
        return CoverageFailure(
            stage="ratchet",
            message="ratchet config path must be inside the repository",
        )


def _transition_drift(
    before: Any,
    after: Any,
    *,
    parent_commit: str,
    child_commit: str | None,
    commit_message: str = "",
) -> tuple[DriftEvent, ...]:
    events: list[DriftEvent] = []
    for edge_id in sorted(before.drift_states.keys() & after.drift_states.keys()):
        event = compute_drift_event(
            DriftTransition(
                parent_commit=parent_commit,
                child_commit=child_commit,
                before=before.drift_states[edge_id],
                after=after.drift_states[edge_id],
                commit_message=commit_message,
                current_diff=True,
            )
        )
        if event is not None:
            events.append(event)
    return tuple(events)


def _ratchet_state(
    root: Path,
    profile: ProfileConfig,
    settings: BackstitchSettings,
    repository: _RepositoryState,
    loaded: _LoadedRatchet,
) -> _RatchetState | CoverageFailure:
    baseline_source = loaded.baseline
    if baseline_source is None:
        return _empty_ratchet()
    config_path = _config_path(root, settings)
    if isinstance(config_path, CoverageFailure):
        return config_path
    assert loaded.deadline is not None
    deadline = loaded.deadline
    projector = IntentRevisionProjector()
    try:
        _check_deadline(deadline)
        revision_blobs = dict(baseline_source.blobs)
        baseline_settings = resolve_repository_config_from_blobs(
            root,
            config_path,
            revision_blobs,
        )
        baseline_profile = configured_profile(baseline_settings)
        baseline_policy = _policy_projection(baseline_settings, baseline_profile)
        previous_policy = baseline_policy
        previous_state = projector.project(
            baseline_source.merge_base,
            revision_blobs,
            repo_root=root,
            settings=baseline_settings,
        )
        baseline_state = previous_state
        locations = dict(baseline_state.definitions)
        policy_transitions: list[PolicyTransition] = []
        drift_rows: list[DriftEvent] = []
        for transition in baseline_source.transitions:
            _check_deadline(deadline)
            for path, raw in transition.changes:
                if raw is None:
                    revision_blobs.pop(path, None)
                else:
                    revision_blobs[path] = raw
            revision_settings = resolve_repository_config_from_blobs(
                root,
                config_path,
                revision_blobs,
            )
            revision_profile = configured_profile(revision_settings)
            revision_policy = _policy_projection(
                revision_settings,
                revision_profile,
            )
            revision_state = projector.project(
                transition.commit,
                revision_blobs,
                repo_root=root,
                settings=revision_settings,
            )
            locations.update(revision_state.definitions)
            policy_transitions.append(
                PolicyTransition(
                    parent_commit=transition.parent_commit,
                    transition_commit=transition.commit,
                    before=previous_policy,
                    after=revision_policy,
                    commit_message=transition.message,
                )
            )
            drift_rows.extend(
                _transition_drift(
                    previous_state,
                    revision_state,
                    parent_commit=transition.parent_commit,
                    child_commit=transition.commit,
                    commit_message=transition.message,
                )
            )
            previous_policy = revision_policy
            previous_state = revision_state
        head_state = previous_state
        current_blobs = _current_blobs(
            revision_blobs,
            repository.snapshot,
            settings,
            profile,
            root,
        )
        current_state = projector.project(
            f"accepted:{repository.snapshot.snapshot_hash}",
            current_blobs,
            repo_root=root,
            settings=settings,
        )
        locations.update(current_state.definitions)
        current_policy = _policy_projection(settings, profile)
        policy_transitions.append(
            PolicyTransition(
                parent_commit=baseline_source.head_commit,
                transition_commit=None,
                before=previous_policy,
                after=current_policy,
            )
        )
        drift_rows.extend(
            _transition_drift(
                previous_state,
                current_state,
                parent_commit=baseline_source.head_commit,
                child_commit=None,
            )
        )
        policy_events = fold_policy_transitions(policy_transitions)
        drift_events = tuple(sorted(drift_rows, key=lambda item: item.event_id))
        changed_definition_ids = frozenset(
            item.definition_id
            for item in repository.definitions
            if (
                item.definition_id not in baseline_state.definitions
                or baseline_state.definitions[
                    item.definition_id
                ].source_projection_sha256
                != item.source_projection_sha256
            )
        )
        source_hashes = {
            row.path: f"sha256:{row.raw_sha256}"
            for row in repository.snapshot.files
            if row.raw_sha256 is not None
        }
        baseline = baseline_metadata(
            baseline_source,
            current_snapshot_sha256=(f"sha256:{repository.snapshot.snapshot_hash}"),
            current_content_sha256=current_content_identity(source_hashes),
            baseline_policy_sha256=policy_identity(baseline_policy),
            current_policy_sha256=policy_identity(current_policy),
        )
        changed_sections = {
            key
            for key in baseline_state.section_rows.keys()
            | current_state.section_rows.keys()
            if baseline_state.section_rows.get(key)
            != current_state.section_rows.get(key)
        }
        spec_growth = {
            "changed_sections": len(changed_sections),
            "utf8_byte_delta": sum(
                current_state.section_rows.get(key, ("", 0))[1]
                - baseline_state.section_rows.get(key, ("", 0))[1]
                for key in changed_sections
            ),
            "requirement_ids": sorted(
                _stable_id(["intent-requirement-v1", path, section_id])
                for path, section_id in changed_sections
            ),
        }
        stale_history = build_stale_doc_history(
            baseline_source.history_blobs,
            baseline_source.history_transitions,
            repo_root=root,
            config_path=config_path,
            current_state=head_state,
            history_complete=baseline_source.history_complete,
            projector=projector,
            deadline=deadline,
        )
        _check_deadline(deadline)
    except (ConfigLoadError, GitBaselineError, ValueError) as exc:
        return CoverageFailure(stage="history", message=str(exc))
    return _RatchetState(
        baseline_source=baseline_source,
        changed_definition_ids=changed_definition_ids,
        baseline=baseline,
        policy_events=policy_events,
        drift_events=drift_events,
        definition_locations=tuple(sorted(locations.items())),
        stale_doc_trends=stale_history.trends,
        spec_growth=spec_growth,
    )


def _classification_issues(  # noqa: C901 approved [SC-17.1] RUFF-SUP-034 exception
    result: IntentCoverageResult,
    floor_results: tuple[CoverageFloorResult, ...],
    repository: _RepositoryState,
    ratchet: _RatchetState,
    settings: BackstitchSettings,
) -> tuple[Issue, ...] | CoverageFailure:
    coverage_issues: list[Issue] = []
    for item in result.definitions:
        code = (
            "INTENT_UNCOVERED_DEFINITION"
            if item.classification == "uncovered"
            else (
                "INTENT_INHERITED_ONLY" if item.classification == "inherited" else None
            )
        )
        if code is None:
            continue
        issue, _ = issue_with_policy(
            Issue(
                code=code,
                severity=_intent_severity(code, "repository"),
                path=item.definition.path,
                line=item.definition.start_line,
                symbol=item.definition.qualname,
                context="repository",
                message=(
                    "definition has no direct intent edge"
                    if code == "INTENT_UNCOVERED_DEFINITION"
                    else "definition is covered only by a whole-file intent edge"
                ),
            ),
            effective_policy=settings.diagnostics,
        )
        if issue is not None:
            coverage_issues.append(issue)
        if item.definition.definition_id in ratchet.changed_definition_ids and (
            item.classification == "uncovered"
            or (
                item.classification == "inherited"
                and not settings.coverage.inherited_counts
            )
        ):
            patch_issue, _ = issue_with_policy(
                Issue(
                    code=code,
                    severity=_intent_severity(code, "patch"),
                    path=item.definition.path,
                    line=item.definition.start_line,
                    symbol=item.definition.qualname,
                    context="patch",
                    message="changed definition lacks direct intent coverage",
                ),
                effective_policy=settings.diagnostics,
            )
            if patch_issue is not None:
                coverage_issues.append(patch_issue)
    for path in repository.unscannable_paths:
        issue, _ = issue_with_policy(
            Issue(
                code="INTENT_COVERAGE_INCOMPLETE",
                severity=_intent_severity("INTENT_COVERAGE_INCOMPLETE", "repository"),
                path=path,
                line=None,
                context="repository",
                message="Python file could not be classified for intent coverage",
            ),
            effective_policy=settings.diagnostics,
        )
        if issue is not None:
            coverage_issues.append(issue)
        current_row = next(row for row in repository.python_rows if row.path == path)
        if (
            ratchet.baseline_source is not None
            and ratchet.baseline_source.blobs.get(path) != current_row.raw_bytes
        ):
            patch_issue, _ = issue_with_policy(
                Issue(
                    code="INTENT_COVERAGE_INCOMPLETE",
                    severity=_intent_severity("INTENT_COVERAGE_INCOMPLETE", "patch"),
                    path=path,
                    line=None,
                    context="patch",
                    message="changed Python file could not be classified",
                ),
                effective_policy=settings.diagnostics,
            )
            if patch_issue is not None:
                coverage_issues.append(patch_issue)
    for path, line, symbol in repository.invalid_exemption_markers:
        issue, _ = issue_with_policy(
            Issue(
                code="INTENT_EXEMPTION_UNREASONED",
                severity=_intent_severity("INTENT_EXEMPTION_UNREASONED"),
                path=path,
                line=line,
                symbol=symbol,
                message="inline no-spec marker requires a valid nonblank reason",
            ),
            effective_policy=settings.diagnostics,
        )
        if issue is not None:
            coverage_issues.append(issue)
    for exemption in result.exemptions:
        if exemption.state != "unused":
            continue
        issue, _ = issue_with_policy(
            Issue(
                code="INTENT_EXEMPTION_UNUSED",
                severity=_intent_severity("INTENT_EXEMPTION_UNUSED"),
                path=exemption.path,
                line=exemption.line,
                message=(
                    f"intent exemption matches no definition: {exemption.selector}"
                ),
            ),
            effective_policy=settings.diagnostics,
        )
        if issue is not None:
            coverage_issues.append(issue)
    for requirement in result.requirements:
        if (
            requirement.rung != "active"
            or requirement.implementation_state != "declared_without_live_owner"
        ):
            continue
        issue, _ = issue_with_policy(
            Issue(
                code="INTENT_REQUIREMENT_UNIMPLEMENTED",
                severity=_intent_severity("INTENT_REQUIREMENT_UNIMPLEMENTED"),
                path=requirement.path,
                line=None,
                section_id=requirement.section_id,
                message=("implementation mappings resolve to no live definition owner"),
            ),
            effective_policy=settings.diagnostics,
        )
        if issue is not None:
            coverage_issues.append(issue)
    for floor in floor_results:
        if floor.passes:
            continue
        issue, _ = issue_with_policy(
            Issue(
                code="INTENT_COVERAGE_FLOOR_REGRESSION",
                severity=_intent_severity("INTENT_COVERAGE_FLOOR_REGRESSION"),
                path=floor.scope,
                line=None,
                message="intent coverage is below a configured floor",
            ),
            effective_policy=settings.diagnostics,
        )
        if issue is not None:
            coverage_issues.append(issue)
    locations = dict(ratchet.definition_locations)
    for event in ratchet.drift_events:
        if event.acknowledged:
            continue
        definition = locations.get(event.definition_id)
        if definition is None:
            return CoverageFailure(
                stage="drift",
                message=(f"drift event has no retained definition: {event.event_id}"),
            )
        issue, _ = issue_with_policy(
            Issue(
                code="INTENT_DRIFT_SUSPECT",
                severity=_intent_severity("INTENT_DRIFT_SUSPECT"),
                path=definition.path,
                line=definition.start_line,
                symbol=definition.qualname,
                message=("implementation changed without governing evidence movement"),
            ),
            effective_policy=settings.diagnostics,
        )
        if issue is not None:
            coverage_issues.append(issue)
    return tuple(coverage_issues)


def _unscannable_files(
    repository: _RepositoryState,
    profile: ProfileConfig,
) -> tuple[CoverageUnscannableFile, ...]:
    return tuple(
        CoverageUnscannableFile(
            path=path,
            role=(
                "test" if _path_under_any(path, profile.test_roots) else "production"
            ),
            tree=_longest_root(path, profile.code_roots),
            issue_identities=tuple(
                sorted(
                    {
                        (issue.code, issue.path, issue.line)
                        for issue in repository.raw_report.issues
                        if issue.path == path
                    },
                    key=lambda row: (row[0], row[1], row[2] or 0),
                )
            ),
        )
        for path in sorted(repository.unscannable_paths)
    )


def _coverage_result(
    root: Path,
    profile: ProfileConfig,
    settings: BackstitchSettings,
    repository: _RepositoryState,
    ratchet: _RatchetState,
) -> CoverageResult | CoverageFailure:
    result = classify_intent_coverage(
        tuple(
            sorted(
                repository.definitions,
                key=lambda item: (item.path, item.structural_locator),
            )
        ),
        repository.raw_report,
        exemptions=repository.exemptions,
        inherited_counts=settings.coverage.inherited_counts,
        requirement_rungs={
            (section.path, section.section_id): _requirement_rung(
                section.path,
                profile,
            )
            for section in repository.raw_report.spec_sections
        },
    )
    floor_results = evaluate_coverage_floors(
        result,
        tuple(
            CoverageFloorFact(
                scope=item.scope,
                direct_target=item.direct,
                accounted_target=item.accounted,
            )
            for item in settings.coverage.floors
        ),
        inherited_counts=settings.coverage.inherited_counts,
    )
    coverage_issues = _classification_issues(
        result,
        floor_results,
        repository,
        ratchet,
        settings,
    )
    if isinstance(coverage_issues, CoverageFailure):
        return coverage_issues
    combined_report = dataclasses.replace(
        repository.raw_report,
        issues=(*repository.raw_report.issues, *coverage_issues),
    )
    pipeline = apply_check_policy(
        combined_report,
        repository.artifacts,
        profile,
        settings,
    )
    policy_issues = tuple(
        Issue(
            code="INTENT_COVERAGE_POLICY_REGRESSION",
            severity=_intent_severity("INTENT_COVERAGE_POLICY_REGRESSION"),
            path=(
                settings.config_path.resolve().relative_to(root).as_posix()
                if settings.config_path is not None
                else ""
            ),
            line=None,
            message=(
                "unacknowledged intent coverage policy transition "
                f"{event.key}: {event.event_id}"
            ),
        )
        for event in ratchet.policy_events
        if not event.acknowledged
    )
    issues = tuple(
        sorted(
            (*pipeline.report.issues, *policy_issues),
            key=issue_sort_key,
        )
    )
    unscannable_files = _unscannable_files(repository, profile)
    payload = build_coverage_report(
        result,
        profile=profile.name,
        repo_root=root.as_posix(),
        mode=settings.coverage.mode,
        inherited_counts=settings.coverage.inherited_counts,
        issues=issues,
        floors=floor_results,
        unscannable_files=unscannable_files,
        baseline=ratchet.baseline,
        changed_definition_ids=ratchet.changed_definition_ids,
        policy_events=ratchet.policy_events,
        drift_events=ratchet.drift_events,
        stale_doc_trends=ratchet.stale_doc_trends,
        spec_growth=ratchet.spec_growth,
    )
    fail_on = set(settings.diagnostics.fail_on)
    return CoverageResult(
        document=CoverageDocument(
            payload=payload,
            source_result=result,
            inherited_counts=settings.coverage.inherited_counts,
            floors=floor_results,
            unscannable_files=unscannable_files,
            issues=issues,
            baseline=ratchet.baseline,
            changed_definition_ids=ratchet.changed_definition_ids,
            policy_events=ratchet.policy_events,
            drift_events=ratchet.drift_events,
            stale_doc_trends=ratchet.stale_doc_trends,
            spec_growth=ratchet.spec_growth,
        ),
        output_path=(
            Path(settings.coverage.output)
            if settings.coverage.output is not None
            else None
        ),
        blocks_gate=bool(policy_issues)
        or any(issue.severity in fail_on for issue in issues),
    )


def run_coverage(request: CoverageRequest) -> CoverageResult | CoverageFailure:
    """Build one current or ratcheted coverage document without rendering."""

    root = request.repo_root.resolve()
    markdown_parse_memo: MarkdownParseMemo = {}
    python_parse_memo: dict[tuple[str, str], Any] = {}
    try:
        snapshot = obligation_runtime.capture_obligation_snapshot(
            root,
            request.profile,
            request.settings,
            markdown_parse_memo=markdown_parse_memo,
        )
    except SnapshotCaptureError as exc:
        return CoverageFailure(stage="snapshot", message=str(exc))
    loaded = _load_ratchet(root, request.settings)
    if isinstance(loaded, CoverageFailure):
        return loaded
    repository = _repository_state(
        root,
        request.profile,
        request.settings,
        snapshot,
        markdown_parse_memo,
        python_parse_memo,
    )
    ratchet = _ratchet_state(
        root,
        request.profile,
        request.settings,
        repository,
        loaded,
    )
    if isinstance(ratchet, CoverageFailure):
        return ratchet
    return _coverage_result(
        root,
        request.profile,
        request.settings,
        repository,
        ratchet,
    )


def publish_coverage(
    result: CoverageResult,
    rendered: str,
) -> CoverageFailure | None:
    """Publish rendered coverage bytes when the resolved run names an output."""

    if result.output_path is None:
        return None
    try:
        artifact_publication.atomic_replace_bytes(
            result.output_path,
            rendered.encode("utf-8"),
        )
    except OSError as exc:
        return CoverageFailure(
            stage="publication",
            message=f"cannot write --output {result.output_path}: {exc}",
        )
    return None
