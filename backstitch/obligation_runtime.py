"""One-view capture orchestration for obligation reads.

Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-2.1], [EVC-2.3],
[EVC-8.2]
Spec: docs/specs/05-backstitch-invariants.md [INV-11]
"""

from __future__ import annotations

import unicodedata
from collections.abc import MutableMapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, cast

from backstitch.canonical import canonical_repository_path, lf_split
from backstitch.check_pipeline import (
    CheckPipelineResult,
    build_check_report_from_snapshot,
)
from backstitch.code_parser import ParsedModule, parse_python_source
from backstitch.config import ProfileConfig
from backstitch.evidence_discovery import (
    EvidenceCandidate,
    PreparedEvidenceCatalog,
    discover_evidence_candidates,
    prepare_evidence_catalog,
)
from backstitch.evidence_summary import build_evidence_summary_items
from backstitch.markdown_specs import MarkdownParseMemo, parse_markdown_spec_bytes
from backstitch.models import Issue, Report
from backstitch.obligations import (
    ObligationInventory,
    ObligationRecord,
    SnapshotIdentity,
    build_obligation_inventory,
    is_unaddressable_issue,
    resolve_evidence_atom,
)
from backstitch.operation_progress import OperationProgress
from backstitch.repository_snapshot import (
    RepositorySnapshot,
    SnapshotAlgorithms,
    SnapshotCaptureError,
    SnapshotConfigSource,
    SnapshotSemanticConfig,
    capture_repository_snapshot,
)
from backstitch.settings import BackstitchSettings

ALGORITHMS = SnapshotAlgorithms(
    snapshot_algorithm_version=1,
    obligation_algorithm_version=1,
    discovery_algorithm_version=2,
    packet_contract_version=3,
    normalization_version=1,
)


@dataclass(frozen=True, slots=True)
class ObligationRuntime:
    """One immutable source, readiness, summary, and discovery boundary.

    Consumers receive no repository path that they could reopen. Every method
    derives from the accepted snapshot and resolver artifacts captured by the
    builder, so CLI reads and packet compilation cannot construct parallel
    readiness graphs.
    """

    snapshot: RepositorySnapshot
    pipeline: CheckPipelineResult
    inventory: ObligationInventory
    profile: ProfileConfig
    settings: BackstitchSettings
    repo_root_display: str

    def evidence_summary(
        self, obligation: ObligationRecord
    ) -> tuple[dict[str, object], ...]:
        """Return the complete source-declared evidence inventory."""

        if obligation.kind == "suppression":
            raise ValueError(
                "suppression obligations do not support evidence summaries"
            )
        return build_evidence_summary_items(
            self.pipeline.raw_report,
            obligation,
            self.snapshot,
            self.profile,
        )

    def discover_candidates(
        self,
        obligation: ObligationRecord,
        *,
        prepared_catalog: PreparedEvidenceCatalog | None = None,
        progress: OperationProgress | None = None,
        emit_progress: bool = True,
    ) -> tuple[EvidenceCandidate, ...]:
        """Return the complete deterministic candidate universe."""

        if obligation.kind == "suppression":
            raise ValueError(
                "suppression obligations do not support evidence discovery"
            )
        return discover_evidence_candidates(
            self.snapshot,
            self.pipeline.raw_report,
            self.profile,
            obligation,
            self.settings.obligations,
            self.pipeline.artifacts.obligation_search_text.get(
                obligation.obligation_id, ""
            ),
            prepared_catalog=prepared_catalog,
            progress=progress,
            emit_progress=emit_progress,
        )

    def prepare_discovery_catalog(
        self,
        *,
        progress: OperationProgress | None = None,
        emit_progress: bool = True,
    ) -> PreparedEvidenceCatalog:
        """Parse snapshot-owned Python input once for a multi-obligation read."""

        return prepare_evidence_catalog(
            self.snapshot,
            self.profile,
            self.settings.obligations,
            progress=progress,
            emit_progress=emit_progress,
        )


def snapshot_semantic_config(
    profile: ProfileConfig, settings: BackstitchSettings
) -> SnapshotSemanticConfig:
    """Project exact identity-bearing read settings into the snapshot owner."""

    limits = settings.obligations
    return SnapshotSemanticConfig(
        profile_name=profile.name,
        spec_roots=profile.spec_roots,
        plan_roots=profile.plan_roots,
        code_roots=profile.code_roots,
        test_roots=profile.test_roots,
        exclusions=settings.exclude,
        planned_spec_globs=profile.planned_spec_globs,
        exploratory_spec_globs=profile.exploratory_spec_globs,
        section_required_roles=limits.section_required_roles,
        maximum_candidate_items=limits.maximum_candidate_items,
        maximum_catalog_items=limits.maximum_catalog_items,
        maximum_lexical_seeds=limits.maximum_lexical_seeds,
        maximum_snapshot_files=limits.maximum_snapshot_files,
        maximum_file_bytes=limits.maximum_file_bytes,
        maximum_snapshot_bytes=limits.maximum_snapshot_bytes,
        maximum_work_units=limits.maximum_work_units,
        maximum_packet_bytes=limits.maximum_packet_bytes,
        maximum_packet_report_bytes=limits.maximum_packet_report_bytes,
        static_neighbor_depth=limits.static_neighbor_depth,
    )


def repository_config_paths(
    repo_root: Path, settings: BackstitchSettings
) -> tuple[str, ...]:
    """Return every applied repository config path or reject an escape."""

    return tuple(
        path for path, _raw_sha256 in _repository_config_identities(repo_root, settings)
    )


def unaddressable_issue_excerpts(
    snapshot: RepositorySnapshot,
    issues: Sequence[Issue],
) -> dict[tuple[str, str, int | None, int], str]:
    """Return exact captured source lines keyed by issue occurrence.

    The inventory owns issue selection and identity. This snapshot-facing seam
    owns only byte-to-line projection, so obligation reads never reopen a path
    after capture ([EVC-2.1], [EVC-8.2]).
    """

    ordinals: dict[tuple[str, str, int | None], int] = {}
    excerpts: dict[tuple[str, str, int | None, int], str] = {}
    decoded_lines: dict[str, tuple[str, ...] | None] = {}
    for issue in issues:
        if not is_unaddressable_issue(issue):
            continue
        base = (issue.code, issue.path, issue.line)
        ordinal = ordinals.get(base, 0)
        ordinals[base] = ordinal + 1
        if issue.line is None:
            continue
        if issue.path not in decoded_lines:
            try:
                raw_bytes = snapshot.file(issue.path).raw_bytes
            except KeyError:
                raw_bytes = None
            try:
                decoded_lines[issue.path] = (
                    None if raw_bytes is None else lf_split(raw_bytes.decode("utf-8"))
                )
            except UnicodeDecodeError:
                decoded_lines[issue.path] = None
        lines = decoded_lines[issue.path]
        if lines is None or issue.line > len(lines):
            continue
        excerpts[(issue.code, issue.path, issue.line, ordinal)] = lines[issue.line - 1]
    return excerpts


def atomic_invariant_targets(
    snapshot: RepositorySnapshot,
    report: Report,
    profile: ProfileConfig,
    *,
    parse_memo: MutableMapping[tuple[str, str], ParsedModule] | None = None,
) -> frozenset[tuple[str, str | None]]:
    """Return mapping targets with one exact captured Python owner receipt."""

    targets: set[tuple[str, str | None]] = set()
    for edge in report.edges:
        if edge.kind != "mapping":
            continue
        atom = resolve_evidence_atom(
            path=edge.code_path,
            symbol=edge.code_symbol,
            relation_kinds=("invariant_bind",),
            reciprocity_state="one_sided",
            test_roots=profile.test_roots,
        )
        if (
            atom.source_role != "implementation"
            or snapshot.path_kind(edge.code_path) != "regular_file"
            or PurePosixPath(edge.code_path).suffix != ".py"
        ):
            continue
        try:
            parsed = _parse_snapshot_python(snapshot, edge.code_path, parse_memo)
        except (KeyError, OSError, UnicodeDecodeError):
            continue
        if not parsed.parse_ok:
            continue
        if edge.code_symbol is not None:
            normalized_symbol = unicodedata.normalize("NFC", edge.code_symbol)
            if (
                sum(
                    unicodedata.normalize("NFC", definition.qualname)
                    == normalized_symbol
                    for definition in parsed.definitions
                )
                != 1
            ):
                continue
        targets.add((edge.code_path, edge.code_symbol))
    return frozenset(targets)


def atomic_code_invariant_ids(
    snapshot: RepositorySnapshot,
    report: Report,
    *,
    parse_memo: MutableMapping[tuple[str, str], ParsedModule] | None = None,
) -> frozenset[str]:
    """Return code invariant IDs with one exact captured owner receipt."""

    invariant_ids: set[str] = set()
    for declaration in report.invariants:
        if (
            declaration.declaration_kind != "code"
            or snapshot.path_kind(declaration.path) != "regular_file"
            or PurePosixPath(declaration.path).suffix != ".py"
        ):
            continue
        try:
            parsed = _parse_snapshot_python(snapshot, declaration.path, parse_memo)
        except (KeyError, OSError, UnicodeDecodeError):
            continue
        if not parsed.parse_ok:
            continue
        if declaration.owner_symbol in {"module", "<module>"}:
            invariant_ids.add(declaration.invariant_id)
            continue
        if declaration.owner_symbol is None:
            continue
        normalized_symbol = unicodedata.normalize("NFC", declaration.owner_symbol)
        matches = [
            definition
            for definition in parsed.definitions
            if unicodedata.normalize("NFC", definition.qualname) == normalized_symbol
            and definition.attachment_line <= declaration.line <= definition.end_line
        ]
        if len(matches) == 1:
            invariant_ids.add(declaration.invariant_id)
    return frozenset(invariant_ids)


def _parse_snapshot_python(
    snapshot: RepositorySnapshot,
    path: str,
    parse_memo: MutableMapping[tuple[str, str], ParsedModule] | None,
) -> ParsedModule:
    row = snapshot.file(path)
    if row.raw_bytes is None:
        raise OSError(f"snapshot source is unreadable: {path}")
    assert row.raw_sha256 is not None
    key = (row.path, row.raw_sha256)
    parsed = None if parse_memo is None else parse_memo.get(key)
    if parsed is None:
        parsed = parse_python_source(row.raw_bytes)
        if parse_memo is not None:
            parse_memo[key] = parsed
    return parsed


def _repository_config_identities(
    repo_root: Path,
    settings: BackstitchSettings,
) -> tuple[tuple[str, str], ...]:
    root = repo_root.resolve()
    sources = _configuration_sources(settings)
    rows: list[tuple[str, str]] = []
    for source in sources:
        path = source.path
        if path.is_relative_to(root):
            rows.append((path.relative_to(root).as_posix(), source.raw_sha256))
    if len({path for path, _raw_sha256 in rows}) != len(rows):
        raise SnapshotCaptureError(
            "invalid_path",
            "repository configuration layer identities are duplicated",
        )
    return tuple(rows)


def _configuration_sources(
    settings: BackstitchSettings,
) -> tuple[SnapshotConfigSource, ...]:
    configured_layers = tuple(
        raw for raw in settings.config_layers if not raw.startswith("packaged:")
    )
    identities = settings.config_layer_identities
    if tuple(item.path for item in identities) != configured_layers:
        raise SnapshotCaptureError(
            "invalid_path",
            "repository configuration layers have no matching byte identities",
        )
    return tuple(
        SnapshotConfigSource(
            path=Path(identity.path),
            raw_bytes=identity.raw_bytes,
            raw_sha256=identity.raw_sha256,
            stat_identity=identity.stat_identity,
        )
        for identity in identities
    )


def _captured_config_identities_match(
    snapshot: RepositorySnapshot,
    expected: tuple[tuple[str, str], ...],
) -> bool:
    for path, raw_sha256 in expected:
        try:
            row = snapshot.file(path)
        except KeyError:
            return False
        if row.raw_sha256 != raw_sha256:
            return False
    return True


def _is_under(path: str, root: str) -> bool:
    if root == ".":
        return True
    return PurePosixPath(path).is_relative_to(PurePosixPath(root))


def _declared_mapping_targets(
    snapshot: RepositorySnapshot,
    *,
    allow_unknown_codes: bool,
    markdown_parse_memo: MarkdownParseMemo | None = None,
) -> tuple[str, ...]:
    identity = snapshot.identity_document()
    semantic_config = identity.get("semantic_config")
    if not isinstance(semantic_config, dict):
        raise RuntimeError("snapshot semantic_config identity is invalid")
    roots = semantic_config.get("spec_roots")
    if not isinstance(roots, list) or not all(isinstance(item, str) for item in roots):
        raise RuntimeError("snapshot spec_roots identity is invalid")

    targets: dict[str, tuple[str, str]] = {}
    target_owners: dict[str, set[tuple[str, str]]] = {}
    bare_symbols: list[tuple[str, str, str]] = []
    for row in snapshot.files:
        if (
            row.raw_bytes is None
            or not row.path.endswith(".md")
            or not any(_is_under(row.path, root) for root in roots)
        ):
            continue
        try:
            parsed = parse_markdown_spec_bytes(
                row.raw_bytes,
                row.path,
                allow_unknown_codes=allow_unknown_codes,
                parse_memo=markdown_parse_memo,
            )
        except UnicodeDecodeError:
            continue
        for mapping in parsed.mappings:
            if mapping.target_path is None:
                if mapping.kind == "symbol":
                    bare_symbols.append(
                        (mapping.spec_path, mapping.section_id, mapping.target)
                    )
                continue
            raw_path = (
                mapping.target.partition("::")[0]
                if mapping.kind == "path_symbol"
                else mapping.target
            )
            normalized = canonical_repository_path(raw_path)
            if normalized is None:
                continue
            previous = targets.get(normalized.canonical)
            if previous is not None and previous[0] != raw_path:
                raise SnapshotCaptureError(
                    "invalid_path",
                    "declared mapping paths collide after canonicalization: "
                    f"{previous[0]!r} and {raw_path!r}",
                    path=normalized.canonical,
                )
            targets.setdefault(
                normalized.canonical,
                (raw_path, normalized.native),
            )
            target_owners.setdefault(normalized.canonical, set()).add(
                (mapping.spec_path, mapping.section_id)
            )

    # Bare symbols remain advisory. They participate only in collision
    # detection when another declaration has already established the same
    # token as a repository path.
    for spec_path, section_id, raw_symbol in bare_symbols:
        normalized = canonical_repository_path(raw_symbol)
        if normalized is None:
            continue
        previous = targets.get(normalized.canonical)
        if (
            previous is not None
            and previous[0] != raw_symbol
            and (spec_path, section_id)
            in target_owners.get(normalized.canonical, set())
        ):
            raise SnapshotCaptureError(
                "invalid_path",
                "declared mapping paths collide after canonicalization: "
                f"{previous[0]!r} and {raw_symbol!r}",
                path=normalized.canonical,
            )
    return tuple(targets[path][1] for path in sorted(targets))


def capture_obligation_snapshot(
    repo_root: Path,
    profile: ProfileConfig,
    settings: BackstitchSettings,
    *,
    operational_exclusions: tuple[str, ...] = (),
    markdown_parse_memo: MarkdownParseMemo | None = None,
    progress: OperationProgress | None = None,
) -> RepositorySnapshot:
    """Capture and converge the exact declared-target set within one ceiling."""

    semantic_config = snapshot_semantic_config(profile, settings)
    config_sources = _configuration_sources(settings)
    config_identities = _repository_config_identities(repo_root, settings)
    config_paths = tuple(path for path, _raw_sha256 in config_identities)
    attempts = settings.obligations.snapshot_capture_attempts
    snapshot = capture_repository_snapshot(
        repo_root,
        semantic_config,
        ALGORITHMS,
        config_sources=config_sources,
        config_paths=config_paths,
        operational_exclusions=operational_exclusions,
        capture_attempts=attempts,
        additional_paths_deriver=lambda candidate: _declared_mapping_targets(
            candidate,
            allow_unknown_codes=settings.allow_unknown_keys,
            markdown_parse_memo=markdown_parse_memo,
        ),
        progress=progress,
    )
    if not _captured_config_identities_match(snapshot, config_identities):
        raise SnapshotCaptureError(
            "snapshot_unstable",
            f"SNAPSHOT_UNSTABLE after {attempts} capture attempts",
            attempts=attempts,
        )
    return snapshot


def build_obligation_runtime(
    repo_root: Path,
    profile: ProfileConfig,
    settings: BackstitchSettings,
    *,
    operational_exclusions: tuple[str, ...] = (),
    progress: OperationProgress | None = None,
) -> ObligationRuntime:
    """Capture and resolve the one runtime shared by reads and packet gates."""

    root = repo_root.resolve()
    markdown_parse_memo: MarkdownParseMemo = {}
    python_parse_memo: dict[tuple[str, str], ParsedModule] = {}
    snapshot = capture_obligation_snapshot(
        root,
        profile,
        settings,
        operational_exclusions=operational_exclusions,
        markdown_parse_memo=markdown_parse_memo,
        progress=progress,
    )
    return build_obligation_runtime_from_snapshot(
        snapshot,
        root,
        profile,
        settings,
        python_parse_memo=python_parse_memo,
        markdown_parse_memo=markdown_parse_memo,
    )


def build_obligation_runtime_from_snapshot(
    snapshot: RepositorySnapshot,
    repo_root: Path,
    profile: ProfileConfig,
    settings: BackstitchSettings,
    *,
    python_parse_memo: MutableMapping[tuple[str, str], ParsedModule] | None = None,
    markdown_parse_memo: MarkdownParseMemo | None = None,
) -> ObligationRuntime:
    """Resolve an already accepted snapshot without reopening repository input."""

    root = repo_root.resolve()
    if python_parse_memo is None:
        python_parse_memo = {}
    pipeline = build_check_report_from_snapshot(
        snapshot,
        root.as_posix(),
        profile,
        settings,
        python_parse_memo=python_parse_memo,
        markdown_parse_memo=markdown_parse_memo,
    )
    required_roles = cast(
        tuple[Literal["implementation", "test"], ...],
        settings.obligations.section_required_roles,
    )
    inventory = build_obligation_inventory(
        pipeline.raw_report,
        profile=profile,
        snapshot=SnapshotIdentity(
            snapshot_hash=snapshot.snapshot_hash,
            file_count=snapshot.file_count,
            byte_count=snapshot.byte_count,
            unreadable_count=snapshot.unreadable_count,
        ),
        section_required_roles=required_roles,
        section_meta=pipeline.effective_section_meta,
        meta_spec_globs=pipeline.effective_meta_spec_globs,
        skipped_obligation_ids=frozenset(
            item.obligation_id for item in pipeline.artifacts.obligation_skips
        ),
        source_end_lines=pipeline.artifacts.obligation_source_end_lines,
        unaddressable_excerpts=unaddressable_issue_excerpts(
            snapshot, pipeline.raw_report.issues
        ),
        atomic_invariant_targets=atomic_invariant_targets(
            snapshot,
            pipeline.raw_report,
            profile,
            parse_memo=python_parse_memo,
        ),
        atomic_code_invariant_ids=atomic_code_invariant_ids(
            snapshot,
            pipeline.raw_report,
            parse_memo=python_parse_memo,
        ),
        suppression_declarations=pipeline.artifacts.suppression_declarations,
        suppression_decisions=pipeline.suppressed,
    )
    return ObligationRuntime(
        snapshot=snapshot,
        pipeline=pipeline,
        inventory=inventory,
        profile=profile,
        settings=settings,
        repo_root_display=root.as_posix(),
    )
