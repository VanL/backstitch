"""Closed preregistration input for alignment product evaluation.

This module validates evaluation fixtures and gold labels. Its output is an
evaluation plan identity only: it is never imported into obligation readiness,
candidate discovery, packet construction, or semantic policy.

Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-10.2]
"""

from __future__ import annotations

import difflib
import hashlib
import json
import math
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

from backstitch.canonical import canonical_json_bytes, lf_line_count, lf_slice, lf_split
from backstitch.check_pipeline import build_check_report_from_snapshot
from backstitch.config import ProfileConfig
from backstitch.contract_validation import ValidationPolicy, make_validators
from backstitch.evidence_discovery import (
    EvidenceCandidate,
    WorkBudget,
    add_issue_candidates,
    catalog_python,
    discover_evidence_candidates,
)
from backstitch.filesystem_io import (
    StableReadError,
    file_stat_identity,
    read_regular_nofollow,
)
from backstitch.grammar import candidate_ref, candidate_ref_digest, is_sha256_hex
from backstitch.models import Report
from backstitch.obligation_runtime import (
    atomic_code_invariant_ids,
    atomic_invariant_targets,
    capture_obligation_snapshot,
)
from backstitch.obligations import SnapshotIdentity, build_obligation_inventory
from backstitch.settings import BackstitchSettings, resolve_config


class AlignmentEvalError(ValueError):
    """The product-evaluation preregistration is invalid."""


_ALIGNMENT_VALIDATORS = make_validators(
    AlignmentEvalError, ValidationPolicy(require_nfc=True)
)


@dataclass(frozen=True, slots=True)
class AlignmentEvalPlan:
    """Validated identity and public sample counts for one frozen plan."""

    manifest_sha256: str
    phase_a_qualification_sha256: str
    phase_b_qualification_sha256: str
    phase_a_fixture_ids: tuple[str, ...]
    phase_b_fixture_ids: tuple[str, ...]
    phase_a_sessions: int
    phase_b_sessions: int
    critical_candidate_ids: tuple[str, ...]
    tested_distribution_sha256: str
    guide_sha256: str
    skill_sha256: str
    _root: Path = field(repr=False, compare=False)
    _phase_a: _PhaseManifest = field(repr=False, compare=False)
    _phase_b: _PhaseManifest = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class AlignmentEvalResult:
    """Identity and recomputed outcome of one closed qualification result."""

    result_sha256: str
    phase: str
    passed: bool
    metrics: dict[str, object]
    phase_qualification_sha256: str
    tested_distribution_sha256: str
    guide_sha256: str
    skill_sha256: str


_PLAN_KEYS = {
    "schema_version",
    "artifact",
    "phase_a_fixture_manifest_path",
    "phase_a_fixture_manifest_sha256",
    "phase_b_fixture_manifest_path",
    "phase_b_fixture_manifest_sha256",
    "phase_a_reviewer_protocol_path",
    "phase_a_reviewer_protocol_sha256",
    "phase_b_reviewer_protocol_path",
    "phase_b_reviewer_protocol_sha256",
    "phase_a_sessions",
    "phase_b_sessions",
    "critical_candidate_ids",
    "tested_distribution_sha256",
    "guide_sha256",
    "skill_sha256",
    "thresholds",
}
_PHASE_KEYS = {"schema_version", "artifact", "phase", "fixtures"}
_FIXTURE_KEYS = {
    "fixture_id",
    "fixture_path",
    "tree_manifest_path",
    "tree_manifest_sha256",
    "task_obligation_id",
    "expected_bootstrap_outcome",
    "expected_diagnosis",
    "first_diff_required",
    "required_trace_declarations",
    "gold_candidates",
    "candidate_artifact_path",
    "candidate_artifact_sha256",
}
_TREE_KEYS = {"schema_version", "artifact", "files"}
_TREE_FILE_KEYS = {"path", "raw_sha256", "byte_count", "executable"}
_DIAGNOSIS_KEYS = {
    "bootstrap_state",
    "blocking_reason_codes",
    "next_action_codes",
}
_DECLARATION_KEYS = {"form", "target_id", "evidence_role", "gold_id"}
_GOLD_KEYS = {
    "gold_id",
    "candidate_id",
    "candidate_kind",
    "path",
    "start_line",
    "end_line",
    "structural_locator",
    "receipt",
    "trace_state",
    "disposition_label",
    "critical",
}
_CANDIDATE_ARTIFACT_KEYS = {
    "schema_version",
    "artifact",
    "obligation_id",
    "snapshot",
    "candidates",
}
_CANDIDATE_KINDS = (
    "implementation_definition",
    "test_definition",
    "static_reference",
    "unresolved_reference",
    "report_issue",
)
_TRACE_STATES = ("declared", "partially_declared", "untraced", "conflicted")
_REACHABLE_CANDIDATE_PAIRS = frozenset(
    (kind, state)
    for kind in _CANDIDATE_KINDS
    for state in _TRACE_STATES
    if kind != "report_issue" or state in {"partially_declared", "conflicted"}
)
_DISPOSITION_LABELS = ("accepted", "rejected", "irrelevant")
_DECLARATION_FORMS = (
    "spec_mapping",
    "code_backlink",
    "binding_test",
)
_EVIDENCE_ROLES = ("implementation", "test", "binding_test")
_BLOCKING_REASONS = (
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
_GUIDANCE_CODES = (
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
_INITIAL_THRESHOLDS: dict[str, float | bool] = {
    "minimum_bootstrap_completion_rate": 1.0,
    "minimum_authority_comprehension_rate": 1.0,
    "minimum_candidate_capture_rate": 0.9,
    "minimum_trace_state_precision": 1.0,
    "maximum_irrelevant_candidate_rate": 0.2,
    "minimum_first_diff_correct_rate": 1.0,
    "require_all_critical_candidates": True,
}


@dataclass(frozen=True, slots=True)
class _FixtureTree:
    root: Path
    files: dict[str, bytes]
    profile: ProfileConfig


@dataclass(frozen=True, slots=True)
class _FixtureDefinition:
    fixture_id: str
    tree: _FixtureTree
    tree_manifest_sha256: str
    task_obligation_id: str | None
    expected_bootstrap_outcome: str | None
    expected_diagnosis: dict[str, Any] | None
    first_diff_required: bool
    required_trace_declarations: tuple[dict[str, Any], ...]
    gold_candidates: tuple[dict[str, Any], ...]
    initial_state: str
    candidate_artifact: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class _PhaseManifest:
    fixture_ids: tuple[str, ...]
    critical_candidate_ids: tuple[str, ...]
    candidate_pairs: frozenset[tuple[str, str]]
    disposition_labels: frozenset[str]
    phase_a_coverage: frozenset[str]
    has_first_diff: bool
    has_accepted_declared: bool
    fixtures: tuple[_FixtureDefinition, ...]


def _object(value: object, keys: set[str], context: str) -> dict[str, Any]:
    return _ALIGNMENT_VALIDATORS.closed_record(value, keys, context)


def _json_file(path: Path, context: str) -> tuple[dict[str, Any], bytes]:  # noqa: C901 approved [SC-17.1] RUFF-SUP-004 exception
    try:
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            raise AlignmentEvalError(f"{context} must be a regular non-symlink file")
        raw = path.read_bytes()
    except AlignmentEvalError:
        raise
    except OSError as exc:
        raise AlignmentEvalError(f"cannot read {context}: {path}: {exc}") from exc

    def closed_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise AlignmentEvalError(f"{context} contains duplicate key {key!r}")
            value[key] = item
        return value

    def reject_constant(value: str) -> None:
        raise AlignmentEvalError(f"{context} contains non-finite number {value}")

    try:
        parsed = json.loads(
            raw,
            object_pairs_hook=closed_object,
            parse_constant=reject_constant,
        )
    except AlignmentEvalError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AlignmentEvalError(f"{context} is not valid JSON: {exc}") from None
    if not isinstance(parsed, dict):
        raise AlignmentEvalError(f"{context} must be an object")
    return cast(dict[str, Any], parsed), raw


def _sha256(value: object, context: str) -> str:
    return _ALIGNMENT_VALIDATORS.digest(value, context, prefixed=True)


def _canonical_sha256(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


_CACHE_DIRECTORY_NAMES = frozenset(
    {"__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache"}
)
_CACHE_FILE_SUFFIXES = (".pyc", ".pyo")


def _authoritative_stat_identity(value: os.stat_result) -> tuple[int, ...]:
    return file_stat_identity(value)


def _authoritative_regular_input(
    root: Path,
    relative: str,
    context: str,
    *,
    expected_stat: os.stat_result | None = None,
) -> tuple[bytes, int]:
    try:
        raw, observed = read_regular_nofollow(
            root,
            relative,
            expected_stat=expected_stat,
        )
    except StableReadError as exc:
        if str(exc) == "POSIX no-follow descriptors are unavailable":
            raise AlignmentEvalError(
                "authoritative product identity requires POSIX no-follow descriptors"
            ) from exc
        raise AlignmentEvalError(f"cannot read {context}: {exc}") from exc
    return raw, observed.st_mode


def _authoritative_regular_bytes(root: Path, relative: str, context: str) -> bytes:
    return _authoritative_regular_input(root, relative, context)[0]


def _authoritative_distribution_inventory(root: Path) -> list[dict[str, object]]:  # noqa: C901 approved [SC-17.1] RUFF-SUP-001 exception
    try:
        root_mode = root.lstat().st_mode
    except OSError as exc:
        raise AlignmentEvalError(
            f"cannot inspect authoritative repository root: {exc}"
        ) from exc
    if stat.S_ISLNK(root_mode) or not stat.S_ISDIR(root_mode):
        raise AlignmentEvalError(
            "authoritative repository root must be a real directory"
        )

    rows: list[dict[str, object]] = []
    inventory_paths: set[str] = set()

    def add(relative: str, raw: bytes, mode: int) -> None:
        canonical = _unicode_text(relative, f"tested distribution path {relative!r}")
        if canonical in inventory_paths:
            raise AlignmentEvalError(
                f"tested distribution contains duplicate path: {canonical}"
            )
        inventory_paths.add(canonical)
        rows.append(
            {
                "path": canonical,
                "raw_sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
                "byte_count": len(raw),
                "executable": bool(mode & stat.S_IXUSR),
            }
        )

    for relative in ("pyproject.toml", "uv.lock"):
        raw, mode = _authoritative_regular_input(
            root, relative, f"tested distribution {relative}"
        )
        add(relative, raw, mode)

    package_root = root / "backstitch"
    try:
        package_mode = package_root.lstat().st_mode
    except OSError as exc:
        raise AlignmentEvalError(
            f"cannot inspect tested distribution backstitch/: {exc}"
        ) from exc
    if stat.S_ISLNK(package_mode) or not stat.S_ISDIR(package_mode):
        raise AlignmentEvalError(
            "tested distribution backstitch/ must be a real directory"
        )

    def visit(directory: Path) -> None:
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as exc:
            raise AlignmentEvalError(
                f"cannot inventory tested distribution: {exc}"
            ) from exc
        for entry in entries:
            entry_path = Path(entry.path)
            relative = entry_path.relative_to(root).as_posix()
            try:
                mode = entry.stat(follow_symlinks=False).st_mode
            except OSError as exc:
                raise AlignmentEvalError(
                    f"cannot inspect tested distribution {relative}: {exc}"
                ) from exc
            if stat.S_ISLNK(mode):
                raise AlignmentEvalError(
                    f"tested distribution contains symlink: {relative}"
                )
            if stat.S_ISDIR(mode):
                if entry.name not in _CACHE_DIRECTORY_NAMES:
                    visit(entry_path)
                continue
            if not stat.S_ISREG(mode):
                raise AlignmentEvalError(
                    f"tested distribution contains non-regular object: {relative}"
                )
            if entry.name.endswith(_CACHE_FILE_SUFFIXES):
                continue
            raw, opened_mode = _authoritative_regular_input(
                root,
                relative,
                f"tested distribution {relative}",
                expected_stat=entry.stat(follow_symlinks=False),
            )
            add(relative, raw, opened_mode)

    visit(package_root)
    rows.sort(key=lambda row: cast(str, row["path"]))
    return rows


def _authoritative_product_identities(
    repository_root: Path | None = None,
) -> dict[str, str]:
    """Hash the exact installed product surfaces named by [EVC-10.2]."""

    root = Path(__file__).parent.parent if repository_root is None else repository_root
    inventory = _authoritative_distribution_inventory(root)
    guide = _authoritative_regular_bytes(
        root,
        "backstitch/guides/alignment.md",
        "installed alignment guide",
    )
    skill = _authoritative_regular_bytes(
        root,
        "skills/backstitch-alignment/SKILL.md",
        "installed alignment skill",
    )
    repeated_inventory = _authoritative_distribution_inventory(root)
    repeated_guide = _authoritative_regular_bytes(
        root,
        "backstitch/guides/alignment.md",
        "installed alignment guide",
    )
    repeated_skill = _authoritative_regular_bytes(
        root,
        "skills/backstitch-alignment/SKILL.md",
        "installed alignment skill",
    )
    if (
        inventory != repeated_inventory
        or guide != repeated_guide
        or skill != repeated_skill
    ):
        raise AlignmentEvalError(
            "authoritative product inputs changed during identity capture"
        )
    return {
        "tested_distribution_sha256": _canonical_sha256(
            {
                "schema_version": 1,
                "artifact": "backstitch-tested-distribution-inventory",
                "files": inventory,
            }
        ),
        "guide_sha256": "sha256:" + hashlib.sha256(guide).hexdigest(),
        "skill_sha256": "sha256:" + hashlib.sha256(skill).hexdigest(),
    }


def _contained_existing(
    base: Path,
    value: object,
    context: str,
    *,
    directory: bool,
) -> Path:
    path = _relative_path(base, value, context)
    current = base
    parts = cast(str, value).split("/")
    try:
        for index, part in enumerate(parts):
            with os.scandir(current) as entries:
                native_names = [entry.name for entry in entries]
            normalized_matches = [
                name
                for name in native_names
                if unicodedata.normalize("NFC", name) == part
            ]
            if len(normalized_matches) != 1 or normalized_matches[0] != part:
                raise AlignmentEvalError(
                    f"{context} has a noncanonical or colliding native path"
                )
            current = current / part
            mode = current.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise AlignmentEvalError(f"{context} cannot traverse a symlink")
            is_final = index == len(parts) - 1
            if not is_final and not stat.S_ISDIR(mode):
                raise AlignmentEvalError(
                    f"{context} has a non-directory path component"
                )
        final_mode = path.lstat().st_mode
    except AlignmentEvalError:
        raise
    except OSError as exc:
        raise AlignmentEvalError(f"cannot resolve {context}: {exc}") from exc
    if directory and not stat.S_ISDIR(final_mode):
        raise AlignmentEvalError(f"{context} must be a directory")
    if not directory and not stat.S_ISREG(final_mode):
        raise AlignmentEvalError(f"{context} must be a regular file")
    return path


def _unicode_scalar_text(value: object, context: str) -> str:
    if not isinstance(value, str):
        raise AlignmentEvalError(f"{context} must be a string")
    if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise AlignmentEvalError(f"{context} cannot contain a Unicode surrogate")
    return value


def _unicode_text(value: object, context: str) -> str:
    value = _unicode_scalar_text(value, context)
    if unicodedata.normalize("NFC", value) != value:
        raise AlignmentEvalError(f"{context} must be Unicode NFC")
    return value


def _reject_normalized_path_collisions(values: list[object], context: str) -> None:
    seen: dict[str, str] = {}
    for index, value in enumerate(values):
        raw = _unicode_scalar_text(value, f"{context}[{index}]")
        normalized = unicodedata.normalize("NFC", raw)
        prior = seen.get(normalized)
        if prior is not None and prior != raw:
            raise AlignmentEvalError(f"{context} has a normalized path collision")
        seen[normalized] = raw


def _validate_frozen_config(tree: Path, files: dict[str, bytes]) -> ProfileConfig:
    context = f"fixture {tree} frozen config"
    try:
        raw = files[".backstitch.toml"].decode("utf-8")
    except KeyError:
        raise AlignmentEvalError(f"{context} is missing .backstitch.toml") from None
    except UnicodeDecodeError as exc:
        raise AlignmentEvalError(f"{context} is not UTF-8: {exc}") from None
    try:
        parsed = tomllib.loads(raw)
    except tomllib.TOMLDecodeError as exc:
        raise AlignmentEvalError(f"{context} is invalid TOML: {exc}") from None
    top = _object(parsed, {"profile"}, context)
    profile = _object(
        top["profile"],
        {"name", "spec_roots", "plan_roots", "code_roots", "test_roots"},
        f"{context}.profile",
    )
    expected: dict[str, object] = {
        "name": "backstitch-style-v1",
        "spec_roots": ["docs/specs"],
        "plan_roots": [],
        "code_roots": ["src", "tests"],
        "test_roots": ["tests"],
    }
    if profile != expected:
        raise AlignmentEvalError(
            f"{context}.profile must freeze docs/specs, src, and tests roots"
        )
    for root in ("docs/specs", "src", "tests"):
        target = tree.joinpath(*root.split("/"))
        try:
            mode = target.lstat().st_mode
        except OSError as exc:
            raise AlignmentEvalError(
                f"{context} root {root} is unavailable: {exc}"
            ) from exc
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise AlignmentEvalError(f"{context} root {root} must be a real directory")
    return ProfileConfig(
        name="backstitch-style-v1",
        spec_roots=("docs/specs",),
        plan_roots=(),
        code_roots=("src", "tests"),
        test_roots=("tests",),
        planned_spec_globs=(),
        exploratory_spec_globs=(),
        meta_spec_globs=(),
    )


def _fixture_snapshot(
    path: Path, context: str
) -> tuple[list[dict[str, object]], dict[str, bytes]]:
    rows: list[dict[str, object]] = []
    files: dict[str, bytes] = {}
    normalized_paths: dict[str, str] = {}

    def visit(directory: Path) -> None:
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError as exc:
            raise AlignmentEvalError(f"cannot inventory {context}: {exc}") from exc
        for entry in entries:
            entry_path = Path(entry.path)
            try:
                mode = entry.stat(follow_symlinks=False).st_mode
            except OSError as exc:
                raise AlignmentEvalError(f"cannot inspect {context}: {exc}") from exc
            relative = entry_path.relative_to(path).as_posix()
            normalized = unicodedata.normalize("NFC", relative)
            prior = normalized_paths.get(normalized)
            if prior is not None and prior != relative:
                raise AlignmentEvalError(f"{context} has a normalized path collision")
            normalized_paths[normalized] = relative
            _relative_path(path, relative, f"{context} path")
            if stat.S_ISLNK(mode):
                raise AlignmentEvalError(f"{context} contains symlink: {relative}")
            if stat.S_ISDIR(mode):
                visit(entry_path)
                continue
            if not stat.S_ISREG(mode):
                raise AlignmentEvalError(
                    f"{context} contains non-regular object: {relative}"
                )
            try:
                content = entry_path.read_bytes()
            except OSError as exc:
                raise AlignmentEvalError(
                    f"cannot read {context} file {relative}: {exc}"
                ) from exc
            rows.append(
                {
                    "path": relative,
                    "raw_sha256": "sha256:" + hashlib.sha256(content).hexdigest(),
                    "byte_count": len(content),
                    "executable": bool(mode & stat.S_IXUSR),
                }
            )
            files[relative] = content

    visit(path)
    rows.sort(key=lambda row: cast(str, row["path"]))
    return rows, files


def _validate_tree(  # noqa: C901 approved [SC-17.1] RUFF-SUP-012 exception
    *,
    phase_base: Path,
    fixture_path: object,
    tree_manifest_path: object,
    declared_tree_sha256: object,
    context: str,
) -> _FixtureTree:
    fixture = _contained_existing(
        phase_base, fixture_path, f"{context}.fixture_path", directory=True
    )
    tree_path = _contained_existing(
        phase_base,
        tree_manifest_path,
        f"{context}.tree_manifest_path",
        directory=False,
    )
    if tree_path == fixture or fixture in tree_path.parents:
        raise AlignmentEvalError(
            f"{context}.tree_manifest_path must be outside fixture"
        )
    raw, _ = _json_file(tree_path, f"{context} tree manifest")
    manifest = _object(raw, _TREE_KEYS, f"{context} tree manifest")
    if manifest["schema_version"] != 1:
        raise AlignmentEvalError(f"{context} tree manifest schema_version must be 1")
    if manifest["artifact"] != "backstitch-eval-fixture-tree":
        raise AlignmentEvalError(f"{context} tree manifest artifact is invalid")
    expected_digest = _sha256(declared_tree_sha256, f"{context}.tree_manifest_sha256")
    if _canonical_sha256(manifest) != expected_digest:
        raise AlignmentEvalError(f"{context} tree manifest hash does not match")
    file_rows = manifest["files"]
    if not isinstance(file_rows, list):
        raise AlignmentEvalError(f"{context} tree manifest files must be an array")
    normalized: list[dict[str, object]] = []
    paths: list[str] = []
    _reject_normalized_path_collisions(
        [
            cast(dict[str, Any], value).get("path") if isinstance(value, dict) else None
            for value in file_rows
        ],
        f"{context} tree manifest paths",
    )
    for index, value in enumerate(file_rows):
        row_context = f"{context} tree manifest files[{index}]"
        row = _object(value, _TREE_FILE_KEYS, row_context)
        relative = row["path"]
        _relative_path(fixture, relative, f"{row_context}.path")
        if (
            isinstance(row["byte_count"], bool)
            or not isinstance(row["byte_count"], int)
            or row["byte_count"] < 0
        ):
            raise AlignmentEvalError(f"{row_context}.byte_count must be nonnegative")
        if not isinstance(row["executable"], bool):
            raise AlignmentEvalError(f"{row_context}.executable must be boolean")
        _sha256(row["raw_sha256"], f"{row_context}.raw_sha256")
        paths.append(cast(str, relative))
        normalized.append(cast(dict[str, object], row))
    if paths != sorted(set(paths)):
        raise AlignmentEvalError(
            f"{context} tree manifest paths must be unique and sorted"
        )
    actual_rows, files = _fixture_snapshot(fixture, context)
    if normalized != actual_rows:
        raise AlignmentEvalError(f"{context} fixture tree does not match manifest")
    return _FixtureTree(
        root=fixture,
        files=files,
        profile=_validate_frozen_config(fixture, files),
    )


def _nonblank(value: object, context: str) -> str:
    return _ALIGNMENT_VALIDATORS.nonblank(_unicode_text(value, context), context)


def _phase_a_initial_state(
    tree: _FixtureTree,
    task_obligation_id: str | None,
    settings: BackstitchSettings,
) -> str:
    """Classify only the preregistered task obligation through readiness."""

    snapshot = capture_obligation_snapshot(tree.root, tree.profile, settings)
    pipeline = build_check_report_from_snapshot(
        snapshot,
        tree.root.as_posix(),
        tree.profile,
        settings,
    )
    required_roles = cast(
        tuple[Literal["implementation", "test"], ...],
        settings.obligations.section_required_roles,
    )
    inventory = build_obligation_inventory(
        pipeline.raw_report,
        profile=tree.profile,
        snapshot=SnapshotIdentity(
            snapshot_hash=snapshot.snapshot_hash,
            file_count=snapshot.file_count,
            byte_count=snapshot.byte_count,
            unreadable_count=snapshot.unreadable_count,
        ),
        section_required_roles=required_roles,
        section_meta=frozenset(
            key for key, enabled in pipeline.artifacts.section_meta.items() if enabled
        ),
        meta_spec_globs=pipeline.effective_meta_spec_globs,
        skipped_obligation_ids=frozenset(
            item.obligation_id for item in pipeline.artifacts.obligation_skips
        ),
        source_end_lines=pipeline.artifacts.obligation_source_end_lines,
        atomic_invariant_targets=atomic_invariant_targets(
            snapshot, pipeline.raw_report, tree.profile
        ),
        atomic_code_invariant_ids=atomic_code_invariant_ids(
            snapshot, pipeline.raw_report
        ),
    )
    if task_obligation_id is None:
        if inventory.obligations:
            raise AlignmentEvalError(
                "Phase A no-intent fixture contains an addressable obligation"
            )
        return "no_intent"
    obligation = inventory.get(task_obligation_id)
    if obligation is None:
        raise AlignmentEvalError(
            f"Phase A task obligation is not addressable: {task_obligation_id}"
        )
    if obligation.disposition == "skipped":
        return "skipped"
    if obligation.gate_state == "executable":
        return "complete"
    if obligation.alignment_state == "partial":
        return "partial"
    if obligation.alignment_state == "untraced":
        return "untraced"
    raise AlignmentEvalError(
        f"Phase A task obligation has unsupported initial readiness: "
        f"{obligation.alignment_state}/{obligation.gate_state}"
    )


def _production_fixture_view(
    tree: _FixtureTree,
    obligation_id: str,
    settings: BackstitchSettings,
) -> tuple[
    dict[str, object],
    tuple[EvidenceCandidate, ...],
    BackstitchSettings,
    Report,
]:
    """Derive the eval view through the production snapshot/report/discovery path."""

    snapshot = capture_obligation_snapshot(tree.root, tree.profile, settings)
    pipeline = build_check_report_from_snapshot(
        snapshot,
        tree.root.as_posix(),
        tree.profile,
        settings,
    )
    required_roles = cast(
        tuple[Literal["implementation", "test"], ...],
        settings.obligations.section_required_roles,
    )
    inventory = build_obligation_inventory(
        pipeline.raw_report,
        profile=tree.profile,
        snapshot=SnapshotIdentity(
            snapshot_hash=snapshot.snapshot_hash,
            file_count=snapshot.file_count,
            byte_count=snapshot.byte_count,
            unreadable_count=snapshot.unreadable_count,
        ),
        section_required_roles=required_roles,
        section_meta=frozenset(
            key for key, enabled in pipeline.artifacts.section_meta.items() if enabled
        ),
        meta_spec_globs=pipeline.effective_meta_spec_globs,
        skipped_obligation_ids=frozenset(
            item.obligation_id for item in pipeline.artifacts.obligation_skips
        ),
        source_end_lines=pipeline.artifacts.obligation_source_end_lines,
        atomic_invariant_targets=atomic_invariant_targets(
            snapshot, pipeline.raw_report, tree.profile
        ),
        atomic_code_invariant_ids=atomic_code_invariant_ids(
            snapshot, pipeline.raw_report
        ),
    )
    obligation = inventory.get(obligation_id)
    if obligation is None:
        raise AlignmentEvalError(
            f"candidate artifact obligation is not addressable: {obligation_id}"
        )
    candidates = discover_evidence_candidates(
        snapshot,
        pipeline.raw_report,
        tree.profile,
        obligation,
        settings.obligations,
        obligation_search_text=pipeline.artifacts.obligation_search_text.get(
            obligation.obligation_id,
            "",
        ),
    )
    snapshot_row: dict[str, object] = {
        "snapshot_hash": snapshot.snapshot_hash,
        "file_count": snapshot.file_count,
        "byte_count": snapshot.byte_count,
        "unreadable_count": snapshot.unreadable_count,
    }
    return snapshot_row, candidates, settings, pipeline.raw_report


def _candidate_artifact_value(
    tree: _FixtureTree,
    obligation_id: str,
    settings: BackstitchSettings,
) -> dict[str, object]:
    snapshot, candidates, _settings, _report = _production_fixture_view(
        tree, obligation_id, settings
    )
    return {
        "schema_version": 1,
        "artifact": "backstitch-alignment-dogfood-candidates",
        "obligation_id": obligation_id,
        "snapshot": snapshot,
        "candidates": [candidate.to_row() for candidate in candidates],
    }


def _source_bound_candidate_catalog(
    tree: _FixtureTree,
    obligation_id: str,
    settings: BackstitchSettings,
) -> dict[str, dict[str, object]]:
    """Rebuild source candidate identities before obligation selection."""

    snapshot = capture_obligation_snapshot(tree.root, tree.profile, settings)
    pipeline = build_check_report_from_snapshot(
        snapshot,
        tree.root.as_posix(),
        tree.profile,
        settings,
    )
    required_roles = cast(
        tuple[Literal["implementation", "test"], ...],
        settings.obligations.section_required_roles,
    )
    inventory = build_obligation_inventory(
        pipeline.raw_report,
        profile=tree.profile,
        snapshot=SnapshotIdentity(
            snapshot_hash=snapshot.snapshot_hash,
            file_count=snapshot.file_count,
            byte_count=snapshot.byte_count,
            unreadable_count=snapshot.unreadable_count,
        ),
        section_required_roles=required_roles,
        section_meta=frozenset(
            key for key, enabled in pipeline.artifacts.section_meta.items() if enabled
        ),
        meta_spec_globs=pipeline.effective_meta_spec_globs,
        skipped_obligation_ids=frozenset(
            item.obligation_id for item in pipeline.artifacts.obligation_skips
        ),
        source_end_lines=pipeline.artifacts.obligation_source_end_lines,
        atomic_invariant_targets=atomic_invariant_targets(
            snapshot, pipeline.raw_report, tree.profile
        ),
        atomic_code_invariant_ids=atomic_code_invariant_ids(
            snapshot, pipeline.raw_report
        ),
    )
    obligation = inventory.get(obligation_id)
    if obligation is None:
        raise AlignmentEvalError(
            f"gold catalog obligation is not addressable: {obligation_id}"
        )
    work = WorkBudget(settings.obligations.maximum_work_units)
    nodes, _definitions, _parsed, _module_names, _raw = catalog_python(
        snapshot,
        tree.profile,
        settings.obligations,
        work,
    )
    add_issue_candidates(
        nodes,
        snapshot,
        pipeline.raw_report,
        obligation,
        work,
    )
    return {
        candidate_id: {
            "candidate_id": node.candidate_id,
            "candidate_kind": node.candidate_kind,
            "path": node.path,
            "start_line": node.start_line,
            "end_line": node.end_line,
            "structural_locator": node.structural_locator,
            "receipt": node.receipt.to_row(),
        }
        for candidate_id, node in nodes.items()
    }


def _ordered_codes(
    value: object, vocabulary: tuple[str, ...], context: str
) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise AlignmentEvalError(f"{context} must be an array of closed codes")
    codes = cast(list[str], value)
    order = {code: index for index, code in enumerate(vocabulary)}
    if any(code not in order for code in codes):
        raise AlignmentEvalError(f"{context} contains an unknown code")
    if codes != sorted(set(codes), key=order.__getitem__):
        raise AlignmentEvalError(f"{context} must be unique and canonically ordered")
    return tuple(codes)


def _validate_diagnosis(value: object, context: str) -> frozenset[str]:
    diagnosis = _object(value, _DIAGNOSIS_KEYS, context)
    if diagnosis["bootstrap_state"] not in {"no_intent", "intent_found"}:
        raise AlignmentEvalError(f"{context}.bootstrap_state is invalid")
    blocking = _ordered_codes(
        diagnosis["blocking_reason_codes"],
        _BLOCKING_REASONS,
        f"{context}.blocking_reason_codes",
    )
    _ordered_codes(
        diagnosis["next_action_codes"],
        _GUIDANCE_CODES,
        f"{context}.next_action_codes",
    )
    coverage: set[str] = set()
    if diagnosis["bootstrap_state"] == "no_intent":
        coverage.add("no_intent")
    if "IMPLEMENTATION_UNTRACED" in blocking:
        coverage.add("untraced")
    if "IMPLEMENTATION_PARTIAL" in blocking:
        coverage.add("partial")
    if "SKIPPED" in blocking:
        coverage.add("skipped")
    return frozenset(coverage)


def _validate_declarations(
    value: object,
    context: str,
    *,
    gold_ids: frozenset[str],
) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        raise AlignmentEvalError(f"{context} must be an array")
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        row_context = f"{context}[{index}]"
        row = _object(item, _DECLARATION_KEYS, row_context)
        if row["form"] not in _DECLARATION_FORMS:
            raise AlignmentEvalError(f"{row_context}.form is invalid")
        _nonblank(row["target_id"], f"{row_context}.target_id")
        if row["evidence_role"] not in _EVIDENCE_ROLES:
            raise AlignmentEvalError(f"{row_context}.evidence_role is invalid")
        gold_id = _nonblank(row["gold_id"], f"{row_context}.gold_id")
        if gold_id not in gold_ids:
            raise AlignmentEvalError(f"{row_context}.gold_id does not resolve")
        rows.append(row)
    order = {value: index for index, value in enumerate(_DECLARATION_FORMS)}

    def key(row: dict[str, Any]) -> tuple[int, str, str, str]:
        return (
            order[cast(str, row["form"])],
            cast(str, row["target_id"]),
            cast(str, row["evidence_role"]),
            cast(str, row["gold_id"]),
        )

    if rows != sorted(rows, key=key) or len({key(row) for row in rows}) != len(rows):
        raise AlignmentEvalError(f"{context} must be unique and canonically ordered")
    return tuple(rows)


def _required_declaration_set(
    tree: _FixtureTree,
    obligation_id: str,
    gold: tuple[dict[str, Any], ...],
    *,
    existing_declarations: tuple[dict[str, Any], ...] = (),
) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    test_roots = tuple(root.rstrip("/") for root in tree.profile.test_roots)

    def is_test_path(path: str) -> bool:
        return any(path == root or path.startswith(root + "/") for root in test_roots)

    for candidate in gold:
        if (
            candidate["disposition_label"] != "accepted"
            or candidate["trace_state"] == "declared"
        ):
            continue
        if candidate["candidate_kind"] not in {
            "implementation_definition",
            "test_definition",
        }:
            raise AlignmentEvalError(
                "accepted non-declared gold must be a traceable definition candidate"
            )
        gold_id = cast(str, candidate["gold_id"])
        path = cast(str, candidate["path"])
        if obligation_id.startswith("invariant::"):
            target = obligation_id.removeprefix("invariant::")
            if is_test_path(path):
                rows.append(
                    {
                        "form": "binding_test",
                        "target_id": target,
                        "evidence_role": "binding_test",
                        "gold_id": gold_id,
                    }
                )
            else:
                rows.append(
                    {
                        "form": "spec_mapping",
                        "target_id": target,
                        "evidence_role": "implementation",
                        "gold_id": gold_id,
                    }
                )
            continue
        role = "test" if is_test_path(path) else "implementation"
        rows.extend(
            (
                {
                    "form": "spec_mapping",
                    "target_id": obligation_id,
                    "evidence_role": role,
                    "gold_id": gold_id,
                },
                {
                    "form": "code_backlink",
                    "target_id": obligation_id,
                    "evidence_role": role,
                    "gold_id": gold_id,
                },
            )
        )
    if not rows:
        return ()
    existing = {
        (
            cast(str, row["form"]),
            cast(str, row["target_id"]),
            cast(str, row["evidence_role"]),
            cast(str, row["gold_id"]),
        )
        for row in existing_declarations
    }
    rows = [
        row
        for row in rows
        if (
            cast(str, row["form"]),
            cast(str, row["target_id"]),
            cast(str, row["evidence_role"]),
            cast(str, row["gold_id"]),
        )
        not in existing
    ]
    order = {name: index for index, name in enumerate(_DECLARATION_FORMS)}
    return tuple(
        sorted(
            rows,
            key=lambda row: (
                order[cast(str, row["form"])],
                cast(str, row["target_id"]),
                cast(str, row["evidence_role"]),
                cast(str, row["gold_id"]),
            ),
        )
    )


def _validate_gold(  # noqa: C901 approved [SC-17.1] RUFF-SUP-010 exception
    value: object,
    tree: _FixtureTree,
    context: str,
    *,
    candidate_artifact: dict[str, Any] | None,
    settings: BackstitchSettings,
) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        raise AlignmentEvalError(f"{context} must be an array")
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        row_context = f"{context}[{index}]"
        row = _object(item, _GOLD_KEYS, row_context)
        _nonblank(row["gold_id"], f"{row_context}.gold_id")
        candidate_id = _nonblank(row["candidate_id"], f"{row_context}.candidate_id")
        if candidate_ref_digest(candidate_id) is None:
            raise AlignmentEvalError(f"{row_context}.candidate_id is invalid")
        if row["candidate_kind"] not in _CANDIDATE_KINDS:
            raise AlignmentEvalError(f"{row_context}.candidate_kind is invalid")
        if row["trace_state"] not in _TRACE_STATES:
            raise AlignmentEvalError(f"{row_context}.trace_state is invalid")
        if row["disposition_label"] not in _DISPOSITION_LABELS:
            raise AlignmentEvalError(f"{row_context}.disposition_label is invalid")
        if not isinstance(row["critical"], bool):
            raise AlignmentEvalError(f"{row_context}.critical must be boolean")
        if row["critical"] and row["disposition_label"] == "irrelevant":
            raise AlignmentEvalError(
                f"{row_context} critical gold cannot be irrelevant"
            )
        candidate_path = row["path"]
        _relative_path(tree.root, candidate_path, f"{row_context}.path")
        if candidate_path not in tree.files:
            raise AlignmentEvalError(f"{row_context}.path is absent from fixture")
        start = row["start_line"]
        end = row["end_line"]
        if (
            isinstance(start, bool)
            or not isinstance(start, int)
            or isinstance(end, bool)
            or not isinstance(end, int)
            or start < 1
            or end < start
        ):
            raise AlignmentEvalError(f"{row_context} span is invalid")
        try:
            line_count = lf_line_count(tree.files[candidate_path].decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise AlignmentEvalError(
                f"{row_context}.path is not UTF-8: {exc}"
            ) from None
        if end > line_count:
            raise AlignmentEvalError(f"{row_context} span exceeds fixture bytes")
        locator = _nonblank(
            row["structural_locator"], f"{row_context}.structural_locator"
        )
        expected_candidate_id = candidate_ref(
            hashlib.sha256(
                canonical_json_bytes(
                    {
                        "candidate_identity_version": 1,
                        "candidate_kind": row["candidate_kind"],
                        "path": candidate_path,
                        "structural_locator": locator,
                    }
                )
            ).hexdigest()
        )
        if candidate_id != expected_candidate_id:
            raise AlignmentEvalError(f"{row_context}.candidate_id does not recompute")
        receipt = _object(
            row["receipt"],
            {
                "receipt_version",
                "path",
                "structural_locator",
                "start_line",
                "end_line",
                "raw_sha256",
            },
            f"{row_context}.receipt",
        )
        span = lf_slice(tree.files[candidate_path], start, end, policy="strict")
        expected_receipt = {
            "receipt_version": 1,
            "path": candidate_path,
            "structural_locator": locator,
            "start_line": start,
            "end_line": end,
            "raw_sha256": hashlib.sha256(span).hexdigest(),
        }
        if receipt != expected_receipt:
            raise AlignmentEvalError(f"{row_context}.receipt does not recompute")
        rows.append(row)
    ids = [cast(str, row["gold_id"]) for row in rows]
    if ids != sorted(set(ids)):
        raise AlignmentEvalError(f"{context} IDs must be unique and sorted")
    candidate_ids = [cast(str, row["candidate_id"]) for row in rows]
    if len(set(candidate_ids)) != len(candidate_ids):
        raise AlignmentEvalError(f"{context} candidate IDs must be unique")
    coordinates = [
        (
            row["candidate_kind"],
            row["path"],
            row["start_line"],
            row["end_line"],
            row["structural_locator"],
        )
        for row in rows
    ]
    if len(set(coordinates)) != len(coordinates):
        raise AlignmentEvalError(f"{context} candidate coordinates must be unique")
    if candidate_artifact is not None:
        source_catalog = _source_bound_candidate_catalog(
            tree,
            cast(str, candidate_artifact["obligation_id"]),
            settings,
        )
        for row in rows:
            source_candidate = source_catalog.get(cast(str, row["candidate_id"]))
            source_projection = {
                key: row[key]
                for key in (
                    "candidate_id",
                    "candidate_kind",
                    "path",
                    "start_line",
                    "end_line",
                    "structural_locator",
                    "receipt",
                )
            }
            if source_candidate != source_projection:
                raise AlignmentEvalError(
                    f"{context} gold candidate is not source-bound production syntax"
                )
        artifact_rows = cast(list[dict[str, Any]], candidate_artifact["candidates"])
        artifact_by_id = {
            cast(str, candidate["candidate_id"]): candidate
            for candidate in artifact_rows
        }
        if len(artifact_by_id) != len(artifact_rows):
            raise AlignmentEvalError("candidate artifact candidate IDs must be unique")
        if not set(artifact_by_id).issubset(candidate_ids):
            raise AlignmentEvalError(
                f"{context} must label every production-discovered candidate exactly once"
            )
        for row in rows:
            candidate = artifact_by_id.get(cast(str, row["candidate_id"]))
            if candidate is None:
                if row["disposition_label"] == "irrelevant":
                    raise AlignmentEvalError(
                        f"{context} absent gold must be accepted or rejected"
                    )
                continue
            projection = {
                key: candidate[key]
                for key in (
                    "candidate_id",
                    "candidate_kind",
                    "path",
                    "start_line",
                    "end_line",
                    "structural_locator",
                    "receipt",
                )
            }
            gold_projection = {key: row[key] for key in projection}
            if gold_projection != projection:
                raise AlignmentEvalError(
                    f"{context} gold identity does not match production candidate"
                )
    return tuple(rows)


def _validate_candidate_artifact(
    *,
    phase_base: Path,
    tree: _FixtureTree,
    obligation_id: str,
    path_value: object,
    digest_value: object,
    context: str,
    settings: BackstitchSettings,
) -> dict[str, Any]:
    artifact_path = _contained_existing(
        phase_base,
        path_value,
        f"{context}.candidate_artifact_path",
        directory=False,
    )
    artifact, raw = _json_file(artifact_path, f"{context} candidate artifact")
    artifact = _object(
        artifact,
        _CANDIDATE_ARTIFACT_KEYS,
        f"{context} candidate artifact",
    )
    if raw != canonical_json_bytes(artifact):
        raise AlignmentEvalError(
            f"{context} candidate artifact must use exact canonical JSON"
        )
    expected_hash = _sha256(
        digest_value,
        f"{context}.candidate_artifact_sha256",
    )
    if "sha256:" + hashlib.sha256(raw).hexdigest() != expected_hash:
        raise AlignmentEvalError(f"{context} candidate artifact hash does not match")
    if (
        artifact["schema_version"] != 1
        or artifact["artifact"] != "backstitch-alignment-dogfood-candidates"
        or artifact["obligation_id"] != obligation_id
    ):
        raise AlignmentEvalError(f"{context} candidate artifact identity is invalid")
    derived = _candidate_artifact_value(tree, obligation_id, settings)
    if artifact != derived or raw != canonical_json_bytes(derived):
        raise AlignmentEvalError(
            f"{context} candidate artifact does not rederive from production discovery"
        )
    return artifact


def _phase_ids(  # noqa: C901 approved [SC-17.1] RUFF-SUP-005 exception
    path: Path, expected_phase: str, declared_sha256: object
) -> _PhaseManifest:
    raw, manifest_bytes = _json_file(path, f"Phase {expected_phase} fixture manifest")
    manifest = _object(raw, _PHASE_KEYS, f"Phase {expected_phase} fixture manifest")
    if manifest_bytes != canonical_json_bytes(manifest):
        raise AlignmentEvalError(
            f"Phase {expected_phase} fixture manifest must use exact canonical JSON"
        )
    if "sha256:" + hashlib.sha256(manifest_bytes).hexdigest() != _sha256(
        declared_sha256, f"phase_{expected_phase.lower()}_fixture_manifest_sha256"
    ):
        raise AlignmentEvalError(
            f"Phase {expected_phase} fixture manifest hash does not match"
        )
    if manifest["schema_version"] != 1:
        raise AlignmentEvalError(
            f"Phase {expected_phase} fixture manifest schema_version must be 1"
        )
    if manifest["artifact"] != "backstitch-alignment-dogfood-fixtures":
        raise AlignmentEvalError(
            f"Phase {expected_phase} fixture manifest artifact is invalid"
        )
    if manifest["phase"] != expected_phase:
        raise AlignmentEvalError(
            f"Phase {expected_phase} fixture manifest phase is invalid"
        )
    fixtures = manifest["fixtures"]
    if not isinstance(fixtures, list) or not fixtures:
        raise AlignmentEvalError(
            f"Phase {expected_phase} fixture manifest fixtures must be nonempty"
        )
    ids: list[str] = []
    critical_ids: list[str] = []
    candidate_pairs: set[tuple[str, str]] = set()
    labels: set[str] = set()
    phase_a_coverage: set[str] = set()
    has_first_diff = False
    has_accepted_declared = False
    fixture_paths: set[str] = set()
    definitions: list[_FixtureDefinition] = []
    for index, value in enumerate(fixtures):
        context = f"Phase {expected_phase} fixtures[{index}]"
        row = _object(
            value,
            _FIXTURE_KEYS,
            context,
        )
        fixture_id = row["fixture_id"]
        if not isinstance(fixture_id, str) or not fixture_id.strip():
            raise AlignmentEvalError(
                f"Phase {expected_phase} fixtures[{index}].fixture_id must be nonblank"
            )
        ids.append(fixture_id)
        fixture_path = _nonblank(row["fixture_path"], f"{context}.fixture_path")
        if fixture_path in fixture_paths:
            raise AlignmentEvalError(
                f"Phase {expected_phase} fixture paths must be unique"
            )
        fixture_paths.add(fixture_path)
        tree = _validate_tree(
            phase_base=path.parent,
            fixture_path=fixture_path,
            tree_manifest_path=row["tree_manifest_path"],
            declared_tree_sha256=row["tree_manifest_sha256"],
            context=f"Phase {expected_phase} fixture {fixture_id}",
        )
        settings = resolve_config(tree.root, environment={})
        first_diff = row["first_diff_required"]
        if not isinstance(first_diff, bool):
            raise AlignmentEvalError(f"{context}.first_diff_required must be boolean")
        task_obligation_id = (
            None
            if row["task_obligation_id"] is None
            else _nonblank(row["task_obligation_id"], f"{context}.task_obligation_id")
        )
        initial_state = (
            _phase_a_initial_state(tree, task_obligation_id, settings)
            if expected_phase == "A"
            else "not_applicable"
        )
        candidate_artifact: dict[str, Any] | None = None
        if expected_phase == "A":
            phase_a_coverage.add(initial_state)
            if (
                row["candidate_artifact_path"] is not None
                or row["candidate_artifact_sha256"] is not None
            ):
                raise AlignmentEvalError(
                    f"{context} Phase A candidate artifact fields must be null"
                )
            gold = _validate_gold(
                row["gold_candidates"],
                tree,
                f"{context}.gold_candidates",
                candidate_artifact=None,
                settings=settings,
            )
            declarations = _validate_declarations(
                row["required_trace_declarations"],
                f"{context}.required_trace_declarations",
                gold_ids=frozenset(),
            )
            if first_diff or declarations or gold:
                raise AlignmentEvalError(
                    f"{context} Phase A diff declarations and gold must be empty"
                )
            outcome = row["expected_bootstrap_outcome"]
            if outcome == "completed":
                if task_obligation_id is None:
                    raise AlignmentEvalError(
                        f"{context}.task_obligation_id must be nonblank"
                    )
                if row["expected_diagnosis"] is not None:
                    raise AlignmentEvalError(
                        f"{context}.expected_diagnosis must be null for completed"
                    )
            elif outcome == "correctly_diagnosed":
                phase_a_coverage.update(
                    _validate_diagnosis(
                        row["expected_diagnosis"], f"{context}.expected_diagnosis"
                    )
                )
            else:
                raise AlignmentEvalError(
                    f"{context}.expected_bootstrap_outcome is invalid"
                )
        else:
            if task_obligation_id is None:
                raise AlignmentEvalError(
                    f"{context}.task_obligation_id must be nonblank"
                )
            obligation_id = task_obligation_id
            if any(
                row[key] is not None
                for key in ("expected_bootstrap_outcome", "expected_diagnosis")
            ):
                raise AlignmentEvalError(
                    f"{context} Phase B bootstrap fields must be null"
                )
            candidate_artifact = _validate_candidate_artifact(
                phase_base=path.parent,
                tree=tree,
                obligation_id=obligation_id,
                path_value=row["candidate_artifact_path"],
                digest_value=row["candidate_artifact_sha256"],
                context=context,
                settings=settings,
            )
            gold = _validate_gold(
                row["gold_candidates"],
                tree,
                f"{context}.gold_candidates",
                candidate_artifact=candidate_artifact,
                settings=settings,
            )
            gold_by_id = {
                cast(str, candidate["gold_id"]): candidate for candidate in gold
            }
            surfaced_candidate_ids = {
                cast(str, candidate["candidate_id"])
                for candidate in cast(
                    list[dict[str, Any]], candidate_artifact["candidates"]
                )
            }
            declarations = _validate_declarations(
                row["required_trace_declarations"],
                f"{context}.required_trace_declarations",
                gold_ids=frozenset(gold_by_id),
            )
            if not gold:
                raise AlignmentEvalError(f"{context} Phase B gold must be nonempty")
            guidance_gold = tuple(
                candidate
                for candidate in gold
                if candidate["candidate_id"] in surfaced_candidate_ids
            )
            original_declarations = _declaration_projection(
                tree.root,
                tree.profile,
                settings,
                obligation_id=obligation_id,
                gold_candidates=tuple(
                    candidate
                    for candidate in guidance_gold
                    if candidate["disposition_label"] == "accepted"
                    and candidate["trace_state"] != "declared"
                    and candidate["candidate_kind"]
                    in {"implementation_definition", "test_definition"}
                ),
            )
            expected_declarations = _required_declaration_set(
                tree,
                obligation_id,
                guidance_gold,
                existing_declarations=original_declarations,
            )
            if declarations != expected_declarations:
                raise AlignmentEvalError(
                    f"{context} does not contain the exact required declaration set"
                )
            accepted_non_declared = {
                cast(str, candidate["gold_id"])
                for candidate in gold
                if candidate["disposition_label"] == "accepted"
                and candidate["trace_state"] != "declared"
                and candidate["candidate_id"] in surfaced_candidate_ids
            }
            accepted_declared = any(
                candidate["disposition_label"] == "accepted"
                and candidate["trace_state"] == "declared"
                and candidate["candidate_id"] in surfaced_candidate_ids
                for candidate in gold
            )
            if accepted_non_declared and (not first_diff or not declarations):
                raise AlignmentEvalError(
                    f"{context} accepted untraced gold requires a first diff and declarations"
                )
            if not accepted_non_declared and (first_diff or declarations):
                raise AlignmentEvalError(
                    f"{context} without accepted non-declared gold cannot preregister a diff"
                )
            has_first_diff = has_first_diff or first_diff
            if accepted_declared:
                has_accepted_declared = True
            for gold_row in gold:
                candidate_pairs.add(
                    (
                        cast(str, gold_row["candidate_kind"]),
                        cast(str, gold_row["trace_state"]),
                    )
                )
                labels.add(cast(str, gold_row["disposition_label"]))
                if gold_row["critical"]:
                    critical_ids.append(
                        f"{fixture_id}#{cast(str, gold_row['gold_id'])}"
                    )
        definitions.append(
            _FixtureDefinition(
                fixture_id=fixture_id,
                tree=tree,
                tree_manifest_sha256=cast(str, row["tree_manifest_sha256"]),
                task_obligation_id=task_obligation_id,
                expected_bootstrap_outcome=cast(
                    str | None, row["expected_bootstrap_outcome"]
                ),
                expected_diagnosis=cast(
                    dict[str, Any] | None, row["expected_diagnosis"]
                ),
                first_diff_required=first_diff,
                required_trace_declarations=declarations,
                gold_candidates=gold,
                initial_state=initial_state,
                candidate_artifact=candidate_artifact,
            )
        )
    if ids != sorted(set(ids)):
        raise AlignmentEvalError(
            f"Phase {expected_phase} fixture IDs must be unique and sorted"
        )
    return _PhaseManifest(
        fixture_ids=tuple(ids),
        critical_candidate_ids=tuple(sorted(critical_ids)),
        candidate_pairs=frozenset(candidate_pairs),
        disposition_labels=frozenset(labels),
        phase_a_coverage=frozenset(phase_a_coverage),
        has_first_diff=has_first_diff,
        has_accepted_declared=has_accepted_declared,
        fixtures=tuple(definitions),
    )


def _relative_path(base: Path, value: object, context: str) -> Path:
    text = _unicode_text(value, context)
    try:
        text = _ALIGNMENT_VALIDATORS.relative_path(text, context)
    except AlignmentEvalError:
        raise AlignmentEvalError(f"{context} must be a contained POSIX path") from None
    return base.joinpath(*text.split("/"))


def _session_count(value: object, context: str) -> int:
    try:
        return _ALIGNMENT_VALIDATORS.integer(value, context, minimum=2)
    except AlignmentEvalError:
        raise AlignmentEvalError(
            f"{context} must be an integer of at least 2"
        ) from None


def _regular_bytes(path: Path, context: str) -> bytes:
    try:
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            raise AlignmentEvalError(f"{context} must be a regular non-symlink file")
        return path.read_bytes()
    except AlignmentEvalError:
        raise
    except OSError as exc:
        raise AlignmentEvalError(f"cannot read {context}: {path}: {exc}") from exc


def _validate_thresholds(value: object) -> None:
    thresholds = _object(
        value, set(_INITIAL_THRESHOLDS), "alignment evaluation plan thresholds"
    )
    for key, expected in _INITIAL_THRESHOLDS.items():
        observed = thresholds[key]
        if isinstance(expected, bool):
            valid = isinstance(observed, bool) and observed is expected
        else:
            valid = (
                not isinstance(observed, bool)
                and isinstance(observed, (int, float))
                and math.isfinite(observed)
                and float(observed) == expected
            )
        if not valid:
            raise AlignmentEvalError(
                "alignment evaluation plan initial thresholds must exactly equal "
                "the EVC-10.2 values"
            )


def _phase_qualification_sha256(
    manifest: dict[str, Any], phase: Literal["A", "B"]
) -> str:
    """Hash only the frozen inputs owned by one qualification phase."""

    prefix = "phase_a" if phase == "A" else "phase_b"
    threshold_names = (
        (
            "minimum_bootstrap_completion_rate",
            "minimum_authority_comprehension_rate",
        )
        if phase == "A"
        else (
            "minimum_candidate_capture_rate",
            "minimum_trace_state_precision",
            "maximum_irrelevant_candidate_rate",
            "minimum_first_diff_correct_rate",
            "require_all_critical_candidates",
        )
    )
    value: dict[str, object] = {
        "schema_version": 1,
        "artifact": "backstitch-alignment-dogfood-phase-plan",
        "phase": phase,
        "fixture_manifest_path": manifest[f"{prefix}_fixture_manifest_path"],
        "fixture_manifest_sha256": manifest[f"{prefix}_fixture_manifest_sha256"],
        "reviewer_protocol_path": manifest[f"{prefix}_reviewer_protocol_path"],
        "reviewer_protocol_sha256": manifest[f"{prefix}_reviewer_protocol_sha256"],
        "session_count": manifest[f"{prefix}_sessions"],
        "tested_distribution_sha256": manifest["tested_distribution_sha256"],
        "guide_sha256": manifest["guide_sha256"],
        "skill_sha256": manifest["skill_sha256"],
        "thresholds": {
            name: cast(dict[str, object], manifest["thresholds"])[name]
            for name in threshold_names
        },
    }
    if phase == "B":
        value["critical_candidate_ids"] = manifest["critical_candidate_ids"]
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def load_alignment_eval_plan(  # noqa: C901 approved [SC-17.1] RUFF-SUP-013 exception
    path: Path, *, require_current_product: bool = False
) -> AlignmentEvalPlan:
    """Load one preregistration, optionally requiring the current product bytes."""

    raw, manifest_bytes = _json_file(path, "alignment evaluation plan")
    manifest = _object(raw, _PLAN_KEYS, "alignment evaluation plan")
    if manifest_bytes not in {
        canonical_json_bytes(manifest),
        canonical_json_bytes(manifest) + b"\n",
    }:
        raise AlignmentEvalError(
            "alignment evaluation plan must use canonical JSON bytes"
        )
    if isinstance(manifest["schema_version"], bool) or manifest["schema_version"] != 2:
        raise AlignmentEvalError("alignment evaluation plan schema_version must be 2")
    if manifest["artifact"] != "backstitch-alignment-dogfood-plan":
        raise AlignmentEvalError("alignment evaluation plan artifact is invalid")
    _validate_thresholds(manifest["thresholds"])
    product_identities = {
        key: _sha256(manifest[key], key)
        for key in (
            "tested_distribution_sha256",
            "guide_sha256",
            "skill_sha256",
        )
    }
    if require_current_product:
        current_product_identities = _authoritative_product_identities()
        for key, expected in current_product_identities.items():
            if product_identities[key] != expected:
                raise AlignmentEvalError(
                    f"alignment evaluation plan {key} does not match authoritative bytes"
                )
    else:
        current_product_identities = None
    for key, observed in product_identities.items():
        if observed != manifest[key]:
            raise AlignmentEvalError(
                f"alignment evaluation plan {key} is not canonical"
            )
    base = path.parent.resolve(strict=True)
    phase_a_path = _contained_existing(
        base,
        manifest["phase_a_fixture_manifest_path"],
        "phase_a_fixture_manifest_path",
        directory=False,
    )
    phase_b_path = _contained_existing(
        base,
        manifest["phase_b_fixture_manifest_path"],
        "phase_b_fixture_manifest_path",
        directory=False,
    )
    for prefix, label in (("phase_a", "Phase A"), ("phase_b", "Phase B")):
        protocol_path = _contained_existing(
            base,
            manifest[f"{prefix}_reviewer_protocol_path"],
            f"{prefix}_reviewer_protocol_path",
            directory=False,
        )
        protocol_digest = (
            "sha256:"
            + hashlib.sha256(
                _regular_bytes(protocol_path, f"{label} reviewer protocol")
            ).hexdigest()
        )
        if protocol_digest != _sha256(
            manifest[f"{prefix}_reviewer_protocol_sha256"],
            f"{prefix}_reviewer_protocol_sha256",
        ):
            raise AlignmentEvalError(f"{label} reviewer protocol hash does not match")
    critical = manifest["critical_candidate_ids"]
    if (
        not isinstance(critical, list)
        or not critical
        or any(not isinstance(item, str) or not item.strip() for item in critical)
        or critical != sorted(set(critical))
    ):
        raise AlignmentEvalError(
            "critical_candidate_ids must be nonempty, unique, and sorted"
        )
    phase_a = _phase_ids(phase_a_path, "A", manifest["phase_a_fixture_manifest_sha256"])
    phase_b = _phase_ids(phase_b_path, "B", manifest["phase_b_fixture_manifest_sha256"])
    required_phase_a = {"no_intent", "untraced", "partial", "complete", "skipped"}
    if phase_a.phase_a_coverage != required_phase_a:
        raise AlignmentEvalError(
            "Phase A fixtures must cover no intent, untraced, partial, complete, and skipped"
        )
    if phase_b.candidate_pairs != _REACHABLE_CANDIDATE_PAIRS:
        raise AlignmentEvalError(
            "Phase B gold must cover every reachable candidate-kind/trace-state pair"
        )
    if phase_b.disposition_labels != set(_DISPOSITION_LABELS):
        raise AlignmentEvalError(
            "Phase B gold must cover accepted, rejected, and irrelevant labels"
        )
    if not phase_b.has_first_diff:
        raise AlignmentEvalError("Phase B must preregister at least one first diff")
    if not phase_b.has_accepted_declared:
        raise AlignmentEvalError(
            "Phase B must include an accepted already-declared candidate"
        )
    if tuple(cast(list[str], critical)) != phase_b.critical_candidate_ids:
        raise AlignmentEvalError(
            "critical_candidate_ids must exactly project Phase B critical gold"
        )
    if require_current_product and (
        _authoritative_product_identities() != current_product_identities
    ):
        raise AlignmentEvalError(
            "authoritative product inputs changed while loading the plan"
        )
    return AlignmentEvalPlan(
        manifest_sha256="sha256:"
        + hashlib.sha256(canonical_json_bytes(manifest)).hexdigest(),
        phase_a_qualification_sha256=_phase_qualification_sha256(manifest, "A"),
        phase_b_qualification_sha256=_phase_qualification_sha256(manifest, "B"),
        phase_a_fixture_ids=phase_a.fixture_ids,
        phase_b_fixture_ids=phase_b.fixture_ids,
        phase_a_sessions=_session_count(
            manifest["phase_a_sessions"], "phase_a_sessions"
        ),
        phase_b_sessions=_session_count(
            manifest["phase_b_sessions"], "phase_b_sessions"
        ),
        critical_candidate_ids=tuple(critical),
        tested_distribution_sha256=product_identities["tested_distribution_sha256"],
        guide_sha256=product_identities["guide_sha256"],
        skill_sha256=product_identities["skill_sha256"],
        _root=base,
        _phase_a=phase_a,
        _phase_b=phase_b,
    )


_RESULT_KEYS = {
    "schema_version",
    "artifact",
    "phase",
    "phase_qualification_sha256",
    "prior_phase_result_sha256",
    "tested_distribution_sha256",
    "guide_sha256",
    "skill_sha256",
    "sessions",
    "candidate_runs",
    "metrics",
    "checks",
    "passed",
    "failure_reasons",
}
_SESSION_KEYS = {
    "session_id",
    "participant_kind",
    "participant_identity_sha256",
    "public_help_only",
    "tasks",
    "authority_answers",
}
_TASK_KEYS = {
    "fixture_id",
    "human_accepted_candidate_ids",
    "bootstrap_outcome",
    "elapsed_milliseconds",
    "backstitch_call_count",
    "reviewed_diff_attempt_count",
    "review_round_count",
    "changed_source_paths",
    "changed_source_line_count",
    "source_revisions",
    "backstitch_calls",
    "cli_observations",
}
_REVISION_KEYS = {
    "ordinal",
    "diff_path",
    "diff_sha256",
    "result_tree_manifest_path",
    "result_tree_manifest_sha256",
    "observed_trace_declarations",
}
_OBSERVATION_KEYS = {
    "ordinal",
    "argv",
    "source_revision_ordinal",
    "source_tree_manifest_path",
    "source_tree_manifest_sha256",
    "output_path",
    "output_sha256",
}
_BACKSTITCH_CALL_KEYS = {"ordinal", "argv", "source_revision_ordinal"}
_CANDIDATE_RUN_KEYS = {
    "fixture_id",
    "obligation_id",
    "source_tree_manifest_path",
    "source_tree_manifest_sha256",
    "output_path",
    "output_sha256",
    "candidates",
}
_CANDIDATE_PROJECTION_KEYS = {
    "candidate_id",
    "candidate_kind",
    "path",
    "start_line",
    "end_line",
    "trace_state",
    "matched_gold_id",
}
_PUBLIC_ENVELOPE_KEYS = {
    "schema_version",
    "operation",
    "snapshot",
    "result",
    "guidance",
    "problems",
}
_PUBLIC_CANDIDATE_KEYS = {
    "candidate_id",
    "candidate_kind",
    "path",
    "owner",
    "start_line",
    "end_line",
    "structural_locator",
    "receipt",
    "discovery_bases",
    "lexical_score",
    "static_relations",
    "declared_relations",
    "trace_state",
    "suggested_trace_edits",
}
_LIST_ENTRY_KEYS = {
    "entry_type",
    "entry_identity",
    "obligation_id",
    "kind",
    "path",
    "start_line",
    "title",
    "intent_state",
    "alignment_state",
    "disposition",
    "obligation_rung",
    "gate_state",
    "blocking_reason_codes",
}
_PHASE_A_METRIC_KEYS = {
    "bootstrap_task_count",
    "bootstrap_success_count",
    "authority_session_count",
    "authority_session_pass_count",
    "bootstrap_completion_rate",
    "authority_comprehension_rate",
}
_PHASE_B_METRIC_KEYS = {
    "eligible_gold_candidate_count",
    "captured_eligible_gold_candidate_count",
    "captured_trace_state_correct_count",
    "surfaced_candidate_count",
    "irrelevant_candidate_count",
    "first_diff_required_count",
    "first_diff_correct_count",
    "critical_candidate_count",
    "critical_candidate_captured_count",
    "candidate_capture_rate",
    "trace_state_precision",
    "irrelevant_candidate_rate",
    "first_diff_correct_rate",
    "all_critical_candidates_captured",
}
_CHECK_KEYS = {"name", "comparator", "threshold", "observed", "passed"}
_AUTHORITY_RUBRIC = (
    ("repository source is the alignment authority", True),
    ("candidates are advice", True),
    ("Backstitch neither edits nor ratifies source relations", True),
    ("semantic success cannot repair incomplete alignment", True),
)


@dataclass(frozen=True, slots=True)
class _CandidateRunBinding:
    fixture_id: str
    obligation_id: str
    source_tree_manifest_path: str
    source_tree_manifest_sha256: str
    output_path: str
    output_sha256: str
    output_raw: bytes
    envelope: dict[str, Any]


def _nonnegative_integer(value: object, context: str) -> int:
    try:
        return _ALIGNMENT_VALIDATORS.integer(value, context)
    except AlignmentEvalError:
        raise AlignmentEvalError(f"{context} must be a nonnegative integer") from None


def _canonical_artifact(
    base: Path, relative: object, declared_sha256: object, context: str
) -> tuple[dict[str, Any], bytes, Path]:
    path = _contained_existing(base, relative, f"{context}.path", directory=False)
    value, raw = _json_file(path, context)
    if raw not in {canonical_json_bytes(value), canonical_json_bytes(value) + b"\n"}:
        raise AlignmentEvalError(f"{context} must use canonical JSON bytes")
    expected = _sha256(declared_sha256, f"{context}.sha256")
    observed = "sha256:" + hashlib.sha256(raw).hexdigest()
    if observed != expected:
        raise AlignmentEvalError(f"{context} hash does not match")
    return value, raw, path


def _artifact_bytes(
    base: Path, relative: object, declared_sha256: object, context: str
) -> tuple[bytes, Path]:
    path = _contained_existing(base, relative, f"{context}.path", directory=False)
    raw = _regular_bytes(path, context)
    if "sha256:" + hashlib.sha256(raw).hexdigest() != _sha256(
        declared_sha256, f"{context}.sha256"
    ):
        raise AlignmentEvalError(f"{context} hash does not match")
    return raw, path


def _tree_rows_from_artifact(
    base: Path,
    relative: object,
    digest: object,
    expected_root: Path,
    context: str,
) -> tuple[list[dict[str, object]], str]:
    manifest, _, _ = _canonical_artifact(base, relative, digest, context)
    tree = _object(manifest, _TREE_KEYS, context)
    if (
        tree["schema_version"] != 1
        or tree["artifact"] != "backstitch-eval-fixture-tree"
    ):
        raise AlignmentEvalError(f"{context} has invalid tree identity")
    if _canonical_sha256(tree) != digest:
        raise AlignmentEvalError(f"{context} canonical hash does not match")
    values = tree["files"]
    if not isinstance(values, list):
        raise AlignmentEvalError(f"{context}.files must be an array")
    paths = [
        cast(dict[str, Any], row).get("path") if isinstance(row, dict) else None
        for row in values
    ]
    _reject_normalized_path_collisions(paths, f"{context}.files paths")
    rows: list[dict[str, object]] = []
    for index, value in enumerate(values):
        row_context = f"{context}.files[{index}]"
        row = _object(value, _TREE_FILE_KEYS, row_context)
        _relative_path(expected_root, row["path"], f"{row_context}.path")
        _sha256(row["raw_sha256"], f"{row_context}.raw_sha256")
        _nonnegative_integer(row["byte_count"], f"{row_context}.byte_count")
        if not isinstance(row["executable"], bool):
            raise AlignmentEvalError(f"{row_context}.executable must be boolean")
        rows.append(cast(dict[str, object], row))
    if [row["path"] for row in rows] != sorted(
        {cast(str, row["path"]) for row in rows}
    ):
        raise AlignmentEvalError(f"{context}.files paths must be unique and sorted")
    actual, _ = _fixture_snapshot(expected_root, context)
    if rows != actual:
        raise AlignmentEvalError(f"{context} does not match result tree")
    return rows, _sha256(digest, f"{context}.sha256")


def _declaration_projection(  # noqa: C901 approved [SC-17.1] RUFF-SUP-003 exception
    root: Path,
    profile: ProfileConfig,
    settings: BackstitchSettings,
    *,
    obligation_id: str,
    gold_candidates: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    _tree_rows, files = _fixture_snapshot(root, "declaration projection")
    tree = _FixtureTree(root=root, files=files, profile=profile)
    _snapshot, candidates, _settings, report = _production_fixture_view(
        tree, obligation_id, settings
    )
    gold_by_coordinate = {
        (
            cast(str, row["candidate_kind"]),
            cast(str, row["path"]),
            cast(str, row["structural_locator"]),
        ): cast(str, row["gold_id"])
        for row in gold_candidates
    }
    rows: list[tuple[str, str, str, str]] = []
    test_roots = tuple(item.rstrip("/") + "/" for item in profile.test_roots)

    def role(path: str) -> str:
        return (
            "test"
            if path in profile.test_roots or path.startswith(test_roots)
            else "implementation"
        )

    def definition_kind(path: str) -> str:
        return (
            "test_definition" if role(path) == "test" else "implementation_definition"
        )

    def matching_gold(path: str, symbol: str | None, candidate_kind: str) -> str | None:
        matches = [
            candidate
            for candidate in candidates
            if candidate.path == path
            and candidate.candidate_kind == candidate_kind
            and (
                candidate.candidate_kind,
                candidate.path,
                candidate.structural_locator,
            )
            in gold_by_coordinate
            and (
                symbol is None
                and candidate.structural_locator.startswith("python-module:")
                or symbol is not None
                and candidate.owner == symbol
                and not candidate.structural_locator.startswith("python-module:")
            )
        ]
        if len(matches) > 1:
            raise AlignmentEvalError(
                "source declaration resolves to multiple frozen gold candidates"
            )
        return (
            None
            if not matches
            else gold_by_coordinate[
                (
                    matches[0].candidate_kind,
                    matches[0].path,
                    matches[0].structural_locator,
                )
            ]
        )

    if obligation_id.startswith("invariant::"):
        invariant_id = obligation_id.removeprefix("invariant::")
        for declaration in report.invariants:
            if (
                declaration.invariant_id == invariant_id
                and declaration.declaration_kind == "code"
            ):
                gold_id = matching_gold(
                    declaration.path,
                    declaration.owner_symbol,
                    "implementation_definition",
                )
                if gold_id is not None:
                    rows.append(
                        (
                            "spec_mapping",
                            invariant_id,
                            role(declaration.path),
                            gold_id,
                        )
                    )
        for binding in report.binds:
            if binding.invariant_id == invariant_id:
                gold_id = matching_gold(
                    binding.test_path,
                    binding.test_symbol,
                    "test_definition",
                )
                if gold_id is not None:
                    rows.append(("binding_test", invariant_id, "binding_test", gold_id))
    else:
        spec_path, section_id = obligation_id.rsplit("#", 1)
        for mapping in report.spec_mappings:
            if (
                mapping.spec_path == spec_path
                and mapping.section_id == section_id
                and mapping.target_path is not None
            ):
                gold_id = matching_gold(
                    mapping.target_path,
                    mapping.target_symbol,
                    definition_kind(mapping.target_path),
                )
                if gold_id is not None:
                    rows.append(
                        (
                            "spec_mapping",
                            obligation_id,
                            role(mapping.target_path),
                            gold_id,
                        )
                    )
        for reference in report.code_refs:
            if (
                reference.ref_context == "asserted"
                and reference.spec_path == spec_path
                and section_id in reference.section_ids
            ):
                gold_id = matching_gold(
                    reference.path,
                    reference.owner_symbol,
                    definition_kind(reference.path),
                )
                if gold_id is not None:
                    rows.append(
                        (
                            "code_backlink",
                            obligation_id,
                            role(reference.path),
                            gold_id,
                        )
                    )
    order = {name: index for index, name in enumerate(_DECLARATION_FORMS)}
    if len(set(rows)) != len(rows):
        raise AlignmentEvalError(
            "source declarations contain duplicate gold-bound relations"
        )
    return tuple(
        {
            "form": form,
            "target_id": target,
            "evidence_role": evidence_role,
            "gold_id": gold_id,
        }
        for form, target, evidence_role, gold_id in sorted(
            rows, key=lambda row: (order[row[0]], row[1], row[2], row[3])
        )
    )


def _tree_delta_stats(original: Path, revised: Path) -> tuple[list[str], int]:
    """Measure source cost from exact before/after bytes, never patch headers."""

    _original_rows, original_files = _fixture_snapshot(original, "original tree")
    _revised_rows, revised_files = _fixture_snapshot(revised, "revised tree")
    changed_paths = sorted(
        path
        for path in set(original_files) | set(revised_files)
        if original_files.get(path) != revised_files.get(path)
    )
    changed_lines = 0
    for path in changed_paths:
        before = lf_split(original_files.get(path, b""), keepends=True)
        after = lf_split(revised_files.get(path, b""), keepends=True)
        matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
        for (
            tag,
            before_start,
            before_end,
            after_start,
            after_end,
        ) in matcher.get_opcodes():
            if tag == "equal":
                continue
            changed_lines += (before_end - before_start) + (after_end - after_start)
    return changed_paths, changed_lines


def _apply_revision(
    fixture: _FixtureDefinition,
    raw_diff: bytes,
    result_base: Path,
    tree_path: object,
    tree_hash: object,
    context: str,
    *,
    obligation_id: str,
    gold_candidates: tuple[dict[str, Any], ...],
    original_settings: BackstitchSettings,
) -> tuple[
    Path,
    tempfile.TemporaryDirectory[str],
    tuple[dict[str, Any], ...],
    list[str],
    int,
    bool,
    BackstitchSettings,
]:
    temporary = tempfile.TemporaryDirectory(prefix="backstitch-eval-")
    copy = Path(temporary.name) / "fixture"
    shutil.copytree(fixture.tree.root, copy)
    completed = subprocess.run(
        ["git", "apply", "--whitespace=nowarn", "-"],
        cwd=copy,
        input=raw_diff,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        temporary.cleanup()
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        raise AlignmentEvalError(
            f"{context} diff does not apply to original: {message}"
        )
    _tree_rows_from_artifact(
        result_base, tree_path, tree_hash, copy, f"{context} result tree"
    )

    def declaration_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
        return (
            cast(str, row["form"]),
            cast(str, row["target_id"]),
            cast(str, row["evidence_role"]),
            cast(str, row["gold_id"]),
        )

    revised_settings = resolve_config(copy, environment={})
    original = Counter(
        declaration_key(row)
        for row in _declaration_projection(
            fixture.tree.root,
            fixture.tree.profile,
            original_settings,
            obligation_id=obligation_id,
            gold_candidates=gold_candidates,
        )
    )
    final = Counter(
        declaration_key(row)
        for row in _declaration_projection(
            copy,
            fixture.tree.profile,
            revised_settings,
            obligation_id=obligation_id,
            gold_candidates=gold_candidates,
        )
    )
    added = final - original
    order = {name: index for index, name in enumerate(_DECLARATION_FORMS)}
    declarations = tuple(
        {
            "form": form,
            "target_id": target,
            "evidence_role": evidence_role,
            "gold_id": gold_id,
        }
        for form, target, evidence_role, gold_id in sorted(
            added.elements(),
            key=lambda row: (order[row[0]], row[1], row[2], row[3]),
        )
    )
    paths, changed_lines = _tree_delta_stats(fixture.tree.root, copy)
    if not paths or changed_lines == 0:
        raise AlignmentEvalError(f"{context} must produce a nonempty tree delta")
    _rows, revised_files = _fixture_snapshot(copy, f"{context} revised readiness")
    revised_state = _phase_a_initial_state(
        _FixtureTree(root=copy, files=revised_files, profile=fixture.tree.profile),
        obligation_id,
        revised_settings,
    )
    return (
        copy,
        temporary,
        declarations,
        paths,
        changed_lines,
        revised_state == "complete",
        revised_settings,
    )


def _public_envelope(  # noqa: C901 approved [SC-17.1] RUFF-SUP-006 exception
    base: Path,
    path: object,
    digest: object,
    context: str,
    *,
    expected_snapshot: dict[str, object] | None = None,
) -> tuple[dict[str, Any], bytes]:
    value, raw, _ = _canonical_artifact(base, path, digest, context)
    envelope = _object(value, _PUBLIC_ENVELOPE_KEYS, context)
    if envelope["schema_version"] != 2:
        raise AlignmentEvalError(f"{context}.schema_version must be 2")
    if envelope["operation"] not in {
        "obligation.list",
        "obligation.get",
        "obligation.summarize_evidence",
        "obligation.find_evidence",
        "obligation.get_candidate",
    }:
        raise AlignmentEvalError(f"{context}.operation is invalid")
    snapshot = _object(
        envelope["snapshot"],
        {"snapshot_hash", "file_count", "byte_count", "unreadable_count"},
        f"{context}.snapshot",
    )
    snapshot_hash = _nonblank(
        snapshot["snapshot_hash"], f"{context}.snapshot.snapshot_hash"
    )
    if not is_sha256_hex(snapshot_hash):
        raise AlignmentEvalError(f"{context}.snapshot.snapshot_hash is invalid")
    for key in ("file_count", "byte_count", "unreadable_count"):
        _nonnegative_integer(snapshot[key], f"{context}.snapshot.{key}")
    if cast(int, snapshot["unreadable_count"]) > cast(int, snapshot["file_count"]):
        raise AlignmentEvalError(f"{context}.snapshot unreadable_count is invalid")
    if expected_snapshot is not None and snapshot != expected_snapshot:
        raise AlignmentEvalError(f"{context}.snapshot does not match the bound tree")
    if not isinstance(envelope["problems"], list):
        raise AlignmentEvalError(f"{context}.problems must be an array")
    if envelope["problems"]:
        raise AlignmentEvalError(f"{context} must be a successful public output")
    if not isinstance(envelope["guidance"], list):
        raise AlignmentEvalError(f"{context}.guidance must be an array")
    if envelope["result"] is None or not envelope["guidance"]:
        raise AlignmentEvalError(f"{context} success needs a result and guidance")
    return envelope, raw


def _guidance_codes(value: object, context: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise AlignmentEvalError(f"{context} must be an array")
    codes: list[str] = []
    for index, item in enumerate(value):
        row = _object(item, {"code", "message", "action"}, f"{context}[{index}]")
        code = cast(str, row["code"])
        if code not in _GUIDANCE_CODES:
            raise AlignmentEvalError(f"{context}[{index}].code is invalid")
        _nonblank(row["message"], f"{context}[{index}].message")
        _nonblank(row["action"], f"{context}[{index}].action")
        codes.append(code)
    order = {code: index for index, code in enumerate(_GUIDANCE_CODES)}
    if codes != sorted(codes, key=order.__getitem__):
        raise AlignmentEvalError(f"{context} must be canonically ordered")
    return tuple(codes)


def _recompute_bootstrap_outcome(  # noqa: C901 approved [SC-17.1] RUFF-SUP-007 exception
    fixture: _FixtureDefinition, envelope: dict[str, Any], context: str
) -> str:
    operation = envelope["operation"]
    result = envelope["result"]
    guidance = _guidance_codes(envelope["guidance"], f"{context}.guidance")
    expected = fixture.expected_bootstrap_outcome
    if expected == "completed":
        if operation != "obligation.get":
            raise AlignmentEvalError(
                f"{context} completed outcome must use obligation.get"
            )
        detail = _object(
            result,
            {
                "obligation_id",
                "kind",
                "path",
                "start_line",
                "end_line",
                "title",
                "intent_state",
                "alignment_state",
                "disposition",
                "obligation_rung",
                "gate_state",
                "required_roles",
                "evidence_counts",
                "candidate_counts",
                "blocking_reasons",
                "next_actions",
            },
            f"{context}.result",
        )
        if (
            detail["obligation_id"] != fixture.task_obligation_id
            or detail["gate_state"] != "executable"
            or detail["alignment_state"] != "complete"
            or detail["disposition"] != "evaluate"
        ):
            return "incorrect"
        if detail["blocking_reasons"] != []:
            raise AlignmentEvalError(f"{context}.result blocking_reasons must be empty")
        _ordered_codes(
            detail["next_actions"],
            _GUIDANCE_CODES,
            f"{context}.result.next_actions",
        )
        if guidance != tuple(detail["next_actions"]):
            raise AlignmentEvalError(
                f"{context}.guidance must equal result next_actions"
            )
        return "completed"
    if expected == "correctly_diagnosed":
        if operation != "obligation.list":
            raise AlignmentEvalError(f"{context} diagnosis must use obligation.list")
        listed = _object(
            result,
            {
                "bootstrap_state",
                "applied_filters",
                "readiness_summary",
                "filtered_count",
                "entries",
                "next_cursor",
            },
            f"{context}.result",
        )
        entries = listed["entries"]
        if not isinstance(entries, list):
            raise AlignmentEvalError(f"{context}.result.entries must be an array")
        if listed["applied_filters"] != {
            "active_only": False,
            "alignment_states": [],
            "gate_states": [],
            "kinds": [],
            "reasons": [],
        }:
            raise AlignmentEvalError(
                f"{context}.result.applied_filters must be the unfiltered view"
            )
        if listed["filtered_count"] != len(entries):
            raise AlignmentEvalError(
                f"{context}.result.filtered_count does not recompute"
            )
        if not entries and listed["readiness_summary"] != {
            "total": 0,
            "active_evaluate": 0,
            "executable": 0,
            "skipped": 0,
            "alignment_debt": 0,
            "blocked": 0,
            "out_of_scope": 0,
            "reason_counts": [],
        }:
            raise AlignmentEvalError(
                f"{context}.result.readiness_summary does not recompute"
            )
        if listed["next_cursor"] is not None:
            raise AlignmentEvalError(f"{context}.result.next_cursor must be null")
        blocking: list[str] = []
        for index, entry_value in enumerate(entries):
            entry = _object(
                entry_value,
                _LIST_ENTRY_KEYS,
                f"{context}.result.entries[{index}]",
            )
            if (
                entry["entry_type"] != "obligation"
                or entry["entry_identity"] != entry["obligation_id"]
            ):
                raise AlignmentEvalError(
                    f"{context}.result.entries[{index}] identity is invalid"
                )
            blocking.extend(
                _ordered_codes(
                    entry["blocking_reason_codes"],
                    _BLOCKING_REASONS,
                    f"{context}.result.entries[{index}].blocking_reason_codes",
                )
            )
        expected_diagnosis = cast(dict[str, Any], fixture.expected_diagnosis)
        observed = {
            "bootstrap_state": listed["bootstrap_state"],
            "blocking_reason_codes": list(
                _ordered_codes(blocking, _BLOCKING_REASONS, f"{context}.blocking")
            ),
            "next_action_codes": list(guidance),
        }
        return "correctly_diagnosed" if observed == expected_diagnosis else "incorrect"
    raise AlignmentEvalError(f"{context} has no Phase A expected outcome")


def _candidate_projection(  # noqa: C901 approved [SC-17.1] RUFF-SUP-002 exception
    value: object, fixture: _FixtureDefinition, context: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    row = _object(value, _PUBLIC_CANDIDATE_KEYS, context)
    candidate_id = _nonblank(row["candidate_id"], f"{context}.candidate_id")
    if row["candidate_kind"] not in _CANDIDATE_KINDS:
        raise AlignmentEvalError(f"{context}.candidate_kind is invalid")
    path = _nonblank(row["path"], f"{context}.path")
    _relative_path(fixture.tree.root, path, f"{context}.path")
    if path not in fixture.tree.files:
        raise AlignmentEvalError(f"{context}.path is absent from fixture")
    start = _nonnegative_integer(row["start_line"], f"{context}.start_line")
    end = _nonnegative_integer(row["end_line"], f"{context}.end_line")
    if start < 1 or end < start:
        raise AlignmentEvalError(f"{context} has invalid span")
    raw = fixture.tree.files[path]
    try:
        line_count = lf_line_count(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise AlignmentEvalError(f"{context}.path is not UTF-8: {exc}") from None
    if end > line_count:
        raise AlignmentEvalError(f"{context} span exceeds fixture bytes")
    span = lf_slice(raw, start, end, policy="strict")
    if row["trace_state"] not in _TRACE_STATES:
        raise AlignmentEvalError(f"{context}.trace_state is invalid")
    if row["owner"] is not None:
        _nonblank(row["owner"], f"{context}.owner")
    _nonblank(row["structural_locator"], f"{context}.structural_locator")
    expected_candidate_id = candidate_ref(
        hashlib.sha256(
            canonical_json_bytes(
                {
                    "candidate_identity_version": 1,
                    "candidate_kind": row["candidate_kind"],
                    "path": path,
                    "structural_locator": row["structural_locator"],
                }
            )
        ).hexdigest()
    )
    if candidate_id != expected_candidate_id:
        raise AlignmentEvalError(f"{context}.candidate_id does not recompute")
    receipt = _object(
        row["receipt"],
        {
            "receipt_version",
            "path",
            "structural_locator",
            "start_line",
            "end_line",
            "raw_sha256",
        },
        f"{context}.receipt",
    )
    if (
        receipt["receipt_version"] != 1
        or receipt["path"] != path
        or receipt["structural_locator"] != row["structural_locator"]
        or receipt["start_line"] != start
        or receipt["end_line"] != end
        or receipt["raw_sha256"] != hashlib.sha256(span).hexdigest()
    ):
        raise AlignmentEvalError(f"{context}.receipt does not match candidate")
    bases = row["discovery_bases"]
    basis_order = (
        "declared_relation",
        "invariant_relation",
        "resolver_issue",
        "lexical_match",
        "static_neighbor",
        "ambiguous_relation",
    )
    _ordered_codes(bases, basis_order, f"{context}.discovery_bases")
    lexical = _object(
        row["lexical_score"],
        {"shared_token_count", "shared_token_byte_count"},
        f"{context}.lexical_score",
    )
    _nonnegative_integer(
        lexical["shared_token_count"], f"{context}.lexical_score.shared_token_count"
    )
    _nonnegative_integer(
        lexical["shared_token_byte_count"],
        f"{context}.lexical_score.shared_token_byte_count",
    )
    relation_keys = {
        "relation_kind",
        "source_candidate_id",
        "target_candidate_id",
        "source_locator",
        "target_locator",
    }
    for field_name in ("static_relations", "declared_relations"):
        relations = row[field_name]
        if not isinstance(relations, list):
            raise AlignmentEvalError(f"{context}.{field_name} must be an array")
        for index, relation in enumerate(relations):
            relation_row = _object(
                relation, relation_keys, f"{context}.{field_name}[{index}]"
            )
            _nonblank(
                relation_row["relation_kind"],
                f"{context}.{field_name}[{index}].relation_kind",
            )
            for key in relation_keys - {"relation_kind"}:
                if relation_row[key] is not None:
                    _nonblank(
                        relation_row[key], f"{context}.{field_name}[{index}].{key}"
                    )
    advice = row["suggested_trace_edits"]
    if not isinstance(advice, list):
        raise AlignmentEvalError(f"{context}.suggested_trace_edits must be an array")
    for index, item in enumerate(advice):
        advice_row = _object(
            item,
            {
                "guidance_code",
                "target_id",
                "evidence_role",
                "supported_forms",
                "review_warning",
            },
            f"{context}.suggested_trace_edits[{index}]",
        )
        if advice_row["guidance_code"] not in _GUIDANCE_CODES:
            raise AlignmentEvalError(
                f"{context}.suggested_trace_edits[{index}].guidance_code is invalid"
            )
        _nonblank(
            advice_row["target_id"],
            f"{context}.suggested_trace_edits[{index}].target_id",
        )
        if advice_row["evidence_role"] not in _EVIDENCE_ROLES:
            raise AlignmentEvalError(
                f"{context}.suggested_trace_edits[{index}].evidence_role is invalid"
            )
        forms = advice_row["supported_forms"]
        if not isinstance(forms, list) or not forms:
            raise AlignmentEvalError(
                f"{context}.suggested_trace_edits[{index}].supported_forms is invalid"
            )
        _ordered_codes(
            forms,
            _DECLARATION_FORMS,
            f"{context}.suggested_trace_edits[{index}].supported_forms",
        )
        if (
            advice_row["review_warning"]
            != "Advice is not evidence; review the source relation before editing."
        ):
            raise AlignmentEvalError(
                f"{context}.suggested_trace_edits[{index}].review_warning is invalid"
            )
    matches = [
        gold for gold in fixture.gold_candidates if gold["candidate_id"] == candidate_id
    ]
    if len(matches) != 1:
        raise AlignmentEvalError(f"{context} has an unmatched or ambiguous gold row")
    gold = matches[0]
    for key in (
        "candidate_kind",
        "path",
        "start_line",
        "end_line",
        "structural_locator",
        "receipt",
    ):
        if row[key] != gold[key]:
            raise AlignmentEvalError(f"{context}.{key} does not match exact gold")
    return (
        {
            "candidate_id": candidate_id,
            "candidate_kind": row["candidate_kind"],
            "path": path,
            "start_line": start,
            "end_line": end,
            "trace_state": row["trace_state"],
            "matched_gold_id": gold["gold_id"],
        },
        gold,
    )


def _candidate_sort_key(
    candidate: dict[str, Any], public: dict[str, Any]
) -> tuple[object, ...]:
    # Explicit EVC order is conflicted, partially-declared, untraced, declared.
    state_order = {
        "conflicted": 0,
        "partially_declared": 1,
        "untraced": 2,
        "declared": 3,
    }
    kind_order = {value: index for index, value in enumerate(_CANDIDATE_KINDS)}
    score = cast(dict[str, int], public["lexical_score"])
    return (
        state_order[cast(str, candidate["trace_state"])],
        kind_order[cast(str, candidate["candidate_kind"])],
        -score["shared_token_count"],
        -score["shared_token_byte_count"],
        candidate["path"],
        candidate["start_line"],
        public["structural_locator"],
        candidate["candidate_id"],
    )


_STATIC_RELATION_KINDS = {
    "static_import",
    "static_call",
    "static_reference",
    "enclosing_definition",
}
_DECLARED_RELATION_KINDS = {
    "spec_mapping",
    "code_backlink",
    "invariant_declaration",
    "invariant_bind",
    "binding_test",
    "issue_target",
}


def _validate_candidate_relationships(  # noqa: C901 approved [SC-17.1] RUFF-SUP-008 exception
    candidates: list[dict[str, Any]],
    obligation_id: str,
    context: str,
) -> None:
    by_id = {cast(str, row["candidate_id"]): row for row in candidates}
    if len(by_id) != len(candidates):
        raise AlignmentEvalError(f"{context} candidate IDs must be unique")
    coordinates = {
        (
            row["candidate_kind"],
            row["path"],
            row["start_line"],
            row["end_line"],
            row["structural_locator"],
        )
        for row in candidates
    }
    if len(coordinates) != len(candidates):
        raise AlignmentEvalError(f"{context} candidate coordinates must be unique")
    obligation_locator = f"markdown-section:{obligation_id.rsplit('#', 1)[-1]}"
    for candidate in candidates:
        candidate_id = cast(str, candidate["candidate_id"])
        candidate_locator = cast(str, candidate["structural_locator"])
        for field_name, allowed in (
            ("static_relations", _STATIC_RELATION_KINDS),
            ("declared_relations", _DECLARED_RELATION_KINDS),
        ):
            relations = cast(list[dict[str, Any]], candidate[field_name])
            seen: set[tuple[object, ...]] = set()
            for relation in relations:
                kind = cast(str, relation["relation_kind"])
                if kind not in allowed:
                    raise AlignmentEvalError(
                        f"{context}.{field_name} relation kind is invalid"
                    )
                source_id = cast(str | None, relation["source_candidate_id"])
                target_id = cast(str | None, relation["target_candidate_id"])
                source_locator = cast(str | None, relation["source_locator"])
                target_locator = cast(str | None, relation["target_locator"])
                if source_id is not None:
                    if source_id not in by_id:
                        raise AlignmentEvalError(
                            f"{context}.{field_name} source candidate does not resolve"
                        )
                    if source_locator != by_id[source_id]["structural_locator"]:
                        raise AlignmentEvalError(
                            f"{context}.{field_name} source locator is invalid"
                        )
                if target_id is not None:
                    if target_id not in by_id:
                        raise AlignmentEvalError(
                            f"{context}.{field_name} target candidate does not resolve"
                        )
                    if target_locator != by_id[target_id]["structural_locator"]:
                        raise AlignmentEvalError(
                            f"{context}.{field_name} target locator is invalid"
                        )
                if kind in _STATIC_RELATION_KINDS and (
                    source_id is None or target_id is None
                ):
                    raise AlignmentEvalError(
                        f"{context}.{field_name} static relation is incomplete"
                    )
                if kind in {
                    "spec_mapping",
                    "invariant_declaration",
                    "invariant_bind",
                } and (
                    source_id is not None
                    or target_id != candidate_id
                    or source_locator != obligation_locator
                    or target_locator != candidate_locator
                ):
                    raise AlignmentEvalError(
                        f"{context}.{field_name} target relation is invalid"
                    )
                if kind in {
                    "code_backlink",
                    "binding_test",
                    "issue_target",
                } and (
                    source_id != candidate_id
                    or target_id is not None
                    or source_locator != candidate_locator
                    or target_locator != obligation_locator
                ):
                    raise AlignmentEvalError(
                        f"{context}.{field_name} source relation is invalid"
                    )
                key = (
                    kind,
                    source_id,
                    target_id,
                    source_locator,
                    target_locator,
                )
                if key in seen:
                    raise AlignmentEvalError(
                        f"{context}.{field_name} relation rows must be unique"
                    )
                seen.add(key)


def _snapshot_row(
    root: Path,
    profile: ProfileConfig,
    settings: BackstitchSettings,
) -> dict[str, object]:
    snapshot = capture_obligation_snapshot(root, profile, settings)
    return {
        "snapshot_hash": snapshot.snapshot_hash,
        "file_count": snapshot.file_count,
        "byte_count": snapshot.byte_count,
        "unreadable_count": snapshot.unreadable_count,
    }


def _public_argv(operation: str, obligation_id: str | None) -> list[str]:
    if operation == "obligation.list":
        target = "list"
        selector: list[str] = []
    elif operation == "obligation.get":
        if obligation_id is None:
            raise AlignmentEvalError("obligation.get needs an exact obligation ID")
        target = obligation_id
        selector = []
    elif operation == "obligation.find_evidence":
        if obligation_id is None:
            raise AlignmentEvalError(
                "obligation.find_evidence needs an exact obligation ID"
            )
        target = obligation_id
        selector = ["--find-evidence", "--limit", "100"]
    else:
        raise AlignmentEvalError(f"unsupported recorded public operation: {operation}")
    return [
        "backstitch",
        "obligation",
        target,
        *selector,
        "--repo-root",
        ".",
        "--format",
        "json",
    ]


def _rerun_public_command(
    argv: list[str], root: Path, expected_raw: bytes, context: str
) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "backstitch", *argv[1:]],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0 or completed.stderr:
        error = completed.stderr.decode("utf-8", errors="replace").strip()
        raise AlignmentEvalError(
            f"{context} public command did not succeed exactly: {error}"
        )
    if completed.stdout != expected_raw:
        raise AlignmentEvalError(
            f"{context} output is not the byte-exact public command result"
        )


def _validate_recorded_backstitch_argv(argv: tuple[str, ...], context: str) -> None:  # noqa: C901 approved [SC-17.1] RUFF-SUP-011 exception
    """Validate a complete read-only dogfood call without narrowing proof output."""

    if len(argv) < 2 or argv[0] != "backstitch":
        raise AlignmentEvalError(f"{context}.argv must start with backstitch")
    command = argv[1]
    if command == "obligation":
        if len(argv) < 3 or argv[2].startswith("-"):
            raise AlignmentEvalError(f"{context}.argv needs an obligation target")
        value_options = {
            "--repo-root",
            "--format",
            "--candidate",
            "--limit",
            "--cursor",
        }
        flag_options = {"--summarize-evidence", "--find-evidence"}
        seen: set[str] = set()
        values: dict[str, str] = {}
        index = 3
        while index < len(argv):
            option = argv[index]
            if option in seen or option not in value_options | flag_options:
                raise AlignmentEvalError(f"{context}.argv has an invalid option")
            seen.add(option)
            if option in flag_options:
                index += 1
                continue
            if index + 1 >= len(argv):
                raise AlignmentEvalError(f"{context}.argv option has no value")
            values[option] = argv[index + 1]
            index += 2
        if values.get("--repo-root") != "." or (
            "--format" in values and values["--format"] not in {"json", "text"}
        ):
            raise AlignmentEvalError(
                f"{context}.argv must bind repo root and public format"
            )
        selectors = sum(
            option in seen
            for option in ("--summarize-evidence", "--find-evidence", "--candidate")
        )
        if selectors > 1:
            raise AlignmentEvalError(f"{context}.argv selectors conflict")
        candidate = values.get("--candidate")
        if candidate is not None and candidate_ref_digest(candidate) is None:
            raise AlignmentEvalError(f"{context}.argv candidate is invalid")
        limit = values.get("--limit")
        if limit is not None and (not limit.isdigit() or int(limit) < 1):
            raise AlignmentEvalError(f"{context}.argv limit is invalid")
        if ("--limit" in seen or "--cursor" in seen) and not (
            "--summarize-evidence" in seen or "--find-evidence" in seen
        ):
            raise AlignmentEvalError(
                f"{context}.argv pagination needs a paginated selector"
            )
        return
    if command == "check":
        value_options = {"--repo-root", "--format"}
        flag_options = {"--show-suppressions"}
        check_seen: set[str] = set()
        check_values: dict[str, str] = {}
        index = 2
        while index < len(argv):
            option = argv[index]
            if option in check_seen or option not in value_options | flag_options:
                raise AlignmentEvalError(f"{context}.argv has an invalid option")
            check_seen.add(option)
            if option in flag_options:
                index += 1
                continue
            if index + 1 >= len(argv):
                raise AlignmentEvalError(f"{context}.argv option has no value")
            check_values[option] = argv[index + 1]
            index += 2
        if check_values.get("--repo-root") != "." or (
            "--format" in check_values
            and check_values["--format"] not in {"json", "text"}
        ):
            raise AlignmentEvalError(
                f"{context}.argv must bind the fixture repository root"
            )
        return
    raise AlignmentEvalError(f"{context}.argv command is not read-only dogfood")


@dataclass(frozen=True, slots=True)
class _TaskRevisionState:
    roots: dict[int, Path]
    tree_hashes: dict[int, str]
    settings_by_root: dict[Path, BackstitchSettings]
    first_diff_correct: bool
    final_paths: list[str]
    final_line_count: int


@dataclass(frozen=True, slots=True)
class _TaskObservationState:
    rows: list[dict[str, Any]]
    envelopes: list[dict[str, Any]]
    raw_outputs: list[bytes]
    revision_ordinals: list[int | None]


class _TaskValidator:
    """Validate one task through revision, call, observation, and phase gates."""

    def __init__(
        self,
        *,
        result_base: Path,
        fixture: _FixtureDefinition,
        value: object,
        phase: str,
        context: str,
        candidate_run: _CandidateRunBinding | None,
    ) -> None:
        self.result_base = result_base
        self.fixture = fixture
        self.value = value
        self.phase = phase
        self.context = context
        self.candidate_run = candidate_run
        self.task: dict[str, Any] = {}
        self.revisions: list[object] = []
        self.temporaries: list[tempfile.TemporaryDirectory[str]] = []

    def validate(self) -> tuple[str | None, bool]:
        self.validate_header()
        base_settings = resolve_config(self.fixture.tree.root, environment={})
        settings_by_root = {self.fixture.tree.root: base_settings}
        try:
            revision_state = self.validate_revisions(
                base_settings,
                settings_by_root,
            )
            self.validate_changed_sources(revision_state)
            recorded_calls = self.validate_recorded_calls(revision_state.roots)
            observations = self.validate_observations(revision_state)
            self.validate_observation_proof(recorded_calls, observations)
            if self.phase == "A":
                outcome = self.validate_phase_a(revision_state, observations)
                return outcome, revision_state.first_diff_correct
            self.validate_phase_b(revision_state, observations)
            return None, revision_state.first_diff_correct
        finally:
            for temporary in self.temporaries:
                temporary.cleanup()

    def validate_header(self) -> None:
        task = _object(self.value, _TASK_KEYS, self.context)
        self.task = task
        if task["fixture_id"] != self.fixture.fixture_id:
            raise AlignmentEvalError(f"{self.context}.fixture_id is out of order")
        accepted_value = task["human_accepted_candidate_ids"]
        if not isinstance(accepted_value, list) or any(
            not isinstance(item, str) or not item.strip() for item in accepted_value
        ):
            raise AlignmentEvalError(
                f"{self.context}.human_accepted_candidate_ids must be an array of IDs"
            )
        accepted_candidate_ids = cast(list[str], accepted_value)
        if accepted_candidate_ids != sorted(set(accepted_candidate_ids)):
            raise AlignmentEvalError(
                f"{self.context}.human_accepted_candidate_ids must be unique and sorted"
            )
        expected_ids = (
            []
            if self.phase == "A"
            else sorted(
                cast(str, candidate["candidate_id"])
                for candidate in self.fixture.gold_candidates
                if candidate["disposition_label"] == "accepted"
            )
        )
        if accepted_candidate_ids != expected_ids:
            raise AlignmentEvalError(
                f"{self.context}.human_accepted_candidate_ids do not match frozen human disposition"
            )
        for name in (
            "elapsed_milliseconds",
            "backstitch_call_count",
            "reviewed_diff_attempt_count",
            "review_round_count",
            "changed_source_line_count",
        ):
            _nonnegative_integer(task[name], f"{self.context}.{name}")
        revisions = task["source_revisions"]
        if not isinstance(revisions, list):
            raise AlignmentEvalError(
                f"{self.context}.source_revisions must be an array"
            )
        self.revisions = revisions
        if task["reviewed_diff_attempt_count"] != len(revisions):
            raise AlignmentEvalError(
                f"{self.context}.reviewed_diff_attempt_count does not recompute"
            )

    def validate_revisions(
        self,
        base_settings: BackstitchSettings,
        settings_by_root: dict[Path, BackstitchSettings],
    ) -> _TaskRevisionState:
        roots: dict[int, Path] = {}
        tree_hashes: dict[int, str] = {}
        first_diff_correct = False
        final_paths: list[str] = []
        final_line_count = 0
        for index, item in enumerate(self.revisions, start=1):
            revision_context = f"{self.context}.source_revisions[{index - 1}]"
            revision = _object(item, _REVISION_KEYS, revision_context)
            if revision["ordinal"] != index:
                raise AlignmentEvalError(
                    f"{revision_context}.ordinal is not contiguous"
                )
            diff, _ = _artifact_bytes(
                self.result_base,
                revision["diff_path"],
                revision["diff_sha256"],
                f"{revision_context} diff",
            )
            (
                root,
                temporary,
                derived,
                paths,
                changed_lines,
                obligation_executable,
                revision_settings,
            ) = _apply_revision(
                self.fixture,
                diff,
                self.result_base,
                revision["result_tree_manifest_path"],
                revision["result_tree_manifest_sha256"],
                revision_context,
                obligation_id=cast(str, self.fixture.task_obligation_id),
                gold_candidates=self.fixture.gold_candidates,
                original_settings=base_settings,
            )
            self.temporaries.append(temporary)
            self.validate_revision_declarations(revision, derived, revision_context)
            roots[index] = root
            settings_by_root[root] = revision_settings
            tree_hashes[index] = cast(str, revision["result_tree_manifest_sha256"])
            if index == 1:
                first_diff_correct = (
                    derived == self.fixture.required_trace_declarations
                    and obligation_executable
                )
            if index == len(self.revisions):
                final_paths = paths
                final_line_count = changed_lines
        return _TaskRevisionState(
            roots,
            tree_hashes,
            settings_by_root,
            first_diff_correct,
            final_paths,
            final_line_count,
        )

    def validate_revision_declarations(
        self,
        revision: dict[str, Any],
        derived: tuple[dict[str, Any], ...],
        revision_context: str,
    ) -> None:
        stored = _validate_declarations(
            revision["observed_trace_declarations"],
            f"{revision_context}.observed_trace_declarations",
            gold_ids=frozenset(
                cast(str, candidate["gold_id"])
                for candidate in self.fixture.gold_candidates
            ),
        )
        if stored != derived:
            raise AlignmentEvalError(
                f"{revision_context}.observed_trace_declarations do not recompute"
            )

    def validate_changed_sources(self, state: _TaskRevisionState) -> None:
        changed_paths_value = self.task["changed_source_paths"]
        if not isinstance(changed_paths_value, list):
            raise AlignmentEvalError(
                f"{self.context}.changed_source_paths must be an array"
            )
        changed_paths = [
            _unicode_text(item, f"{self.context}.changed_source_paths[{index}]")
            for index, item in enumerate(changed_paths_value)
        ]
        for index, path in enumerate(changed_paths):
            _relative_path(
                self.fixture.tree.root,
                path,
                f"{self.context}.changed_source_paths[{index}]",
            )
        if changed_paths != sorted(set(changed_paths)):
            raise AlignmentEvalError(
                f"{self.context}.changed_source_paths must be unique and sorted"
            )
        if (
            changed_paths != state.final_paths
            or self.task["changed_source_line_count"] != state.final_line_count
        ):
            raise AlignmentEvalError(
                f"{self.context} changed-source fields do not recompute"
            )

    def validate_recorded_calls(
        self,
        revision_roots: dict[int, Path],
    ) -> list[tuple[tuple[str, ...], int | None]]:
        calls = self.task["backstitch_calls"]
        if not isinstance(calls, list) or not calls:
            raise AlignmentEvalError(
                f"{self.context}.backstitch_calls must be nonempty"
            )
        if self.task["backstitch_call_count"] != len(calls):
            raise AlignmentEvalError(
                f"{self.context}.backstitch_call_count does not recompute"
            )
        recorded: list[tuple[tuple[str, ...], int | None]] = []
        for index, item in enumerate(calls, start=1):
            call_context = f"{self.context}.backstitch_calls[{index - 1}]"
            call = _object(item, _BACKSTITCH_CALL_KEYS, call_context)
            if call["ordinal"] != index:
                raise AlignmentEvalError(f"{call_context}.ordinal is not contiguous")
            argv = call["argv"]
            if not isinstance(argv, list) or not argv:
                raise AlignmentEvalError(f"{call_context}.argv must be nonempty")
            normalized_argv = tuple(
                _nonblank(arg, f"{call_context}.argv[{arg_index}]")
                for arg_index, arg in enumerate(argv)
            )
            _validate_recorded_backstitch_argv(normalized_argv, call_context)
            revision_ordinal = call["source_revision_ordinal"]
            if revision_ordinal is not None and (
                isinstance(revision_ordinal, bool)
                or not isinstance(revision_ordinal, int)
                or revision_ordinal not in revision_roots
            ):
                raise AlignmentEvalError(
                    f"{call_context}.source_revision_ordinal does not resolve"
                )
            recorded.append((normalized_argv, revision_ordinal))
        return recorded

    def validate_observations(
        self,
        state: _TaskRevisionState,
    ) -> _TaskObservationState:
        observations = self.task["cli_observations"]
        if not isinstance(observations, list) or not observations:
            raise AlignmentEvalError(
                f"{self.context}.cli_observations must be nonempty"
            )
        rows = cast(list[dict[str, Any]], observations)
        envelopes: list[dict[str, Any]] = []
        raw_outputs: list[bytes] = []
        revision_ordinals: list[int | None] = []
        original_rows, _ = _fixture_snapshot(self.fixture.tree.root, self.context)
        for index, item in enumerate(observations, start=1):
            envelope, output_raw, revision_ordinal = self.validate_observation(
                item,
                index,
                state,
                original_rows,
            )
            envelopes.append(envelope)
            raw_outputs.append(output_raw)
            revision_ordinals.append(revision_ordinal)
        return _TaskObservationState(
            rows,
            envelopes,
            raw_outputs,
            revision_ordinals,
        )

    def validate_observation(
        self,
        item: object,
        index: int,
        state: _TaskRevisionState,
        original_rows: list[dict[str, object]],
    ) -> tuple[dict[str, Any], bytes, int | None]:
        observation_context = f"{self.context}.cli_observations[{index - 1}]"
        observation = _object(item, _OBSERVATION_KEYS, observation_context)
        if observation["ordinal"] != index:
            raise AlignmentEvalError(f"{observation_context}.ordinal is not contiguous")
        argv = observation["argv"]
        if not isinstance(argv, list) or not argv:
            raise AlignmentEvalError(f"{observation_context}.argv must be nonempty")
        for arg_index, arg in enumerate(argv):
            _nonblank(arg, f"{observation_context}.argv[{arg_index}]")
        revision_ordinal = observation["source_revision_ordinal"]
        if revision_ordinal is None:
            expected_root = self.fixture.tree.root
            expected_hash = _canonical_sha256(
                {
                    "schema_version": 1,
                    "artifact": "backstitch-eval-fixture-tree",
                    "files": original_rows,
                }
            )
        else:
            if (
                isinstance(revision_ordinal, bool)
                or not isinstance(revision_ordinal, int)
                or revision_ordinal not in state.roots
            ):
                raise AlignmentEvalError(
                    f"{observation_context}.source_revision_ordinal does not resolve"
                )
            expected_root = state.roots[revision_ordinal]
            expected_hash = state.tree_hashes[revision_ordinal]
        if observation["source_tree_manifest_sha256"] != expected_hash:
            raise AlignmentEvalError(
                f"{observation_context} source tree hash is incorrect"
            )
        _tree_rows_from_artifact(
            self.result_base,
            observation["source_tree_manifest_path"],
            observation["source_tree_manifest_sha256"],
            expected_root,
            f"{observation_context} source tree",
        )
        expected_snapshot = _snapshot_row(
            expected_root,
            self.fixture.tree.profile,
            state.settings_by_root[expected_root],
        )
        envelope, output_raw = _public_envelope(
            self.result_base,
            observation["output_path"],
            observation["output_sha256"],
            f"{observation_context} output",
            expected_snapshot=expected_snapshot,
        )
        canonical_argv = _public_argv(
            cast(str, envelope["operation"]),
            self.fixture.task_obligation_id,
        )
        if argv != canonical_argv:
            raise AlignmentEvalError(
                f"{observation_context}.argv is not the exact public command"
            )
        _rerun_public_command(
            canonical_argv,
            expected_root,
            output_raw,
            observation_context,
        )
        return envelope, output_raw, cast(int | None, revision_ordinal)

    def validate_observation_proof(
        self,
        recorded_calls: list[tuple[tuple[str, ...], int | None]],
        observations: _TaskObservationState,
    ) -> None:
        proof_calls = Counter(
            (tuple(cast(list[str], row["argv"])), revision_ordinal)
            for row, revision_ordinal in zip(
                observations.rows,
                observations.revision_ordinals,
                strict=True,
            )
        )
        if proof_calls - Counter(recorded_calls):
            raise AlignmentEvalError(
                f"{self.context}.cli_observations must be included in backstitch_calls"
            )

    def validate_phase_a(
        self,
        revisions: _TaskRevisionState,
        observations: _TaskObservationState,
    ) -> str:
        incomplete = self.fixture.initial_state in {
            "partial",
            "untraced",
            "skipped",
        }
        if incomplete:
            self.validate_incomplete_phase_a(revisions, observations)
        elif self.revisions:
            raise AlignmentEvalError(
                f"{self.context} complete/no-intent Phase A task cannot add revisions"
            )
        last_envelope = observations.envelopes[-1]
        if self.fixture.initial_state == "no_intent":
            if last_envelope["operation"] != "obligation.list":
                raise AlignmentEvalError(
                    f"{self.context} no-intent outcome must use obligation.list"
                )
        elif last_envelope["operation"] != "obligation.get":
            raise AlignmentEvalError(
                f"{self.context} final authoring observation must use obligation.get"
            )
        outcome = _recompute_bootstrap_outcome(
            self.fixture,
            last_envelope,
            self.context,
        )
        if self.task["bootstrap_outcome"] != outcome:
            raise AlignmentEvalError(
                f"{self.context}.bootstrap_outcome does not recompute"
            )
        return outcome

    def validate_incomplete_phase_a(
        self,
        revisions: _TaskRevisionState,
        observations: _TaskObservationState,
    ) -> None:
        if not self.revisions:
            raise AlignmentEvalError(
                f"{self.context} incomplete Phase A task needs a source revision"
            )
        if observations.envelopes[0]["operation"] != "obligation.list":
            raise AlignmentEvalError(
                f"{self.context} first observation must record initial production state"
            )
        if observations.revision_ordinals[0] is not None:
            raise AlignmentEvalError(
                f"{self.context} first observation must bind the original tree"
            )
        if observations.revision_ordinals[-1] != len(self.revisions):
            raise AlignmentEvalError(
                f"{self.context} final observation must bind the final revision"
            )

    def validate_phase_b(
        self,
        revisions: _TaskRevisionState,
        observations: _TaskObservationState,
    ) -> None:
        if self.candidate_run is None:
            raise AlignmentEvalError(f"{self.context} has no canonical candidate run")
        if len(observations.envelopes) != 1:
            raise AlignmentEvalError(
                f"{self.context} Phase B task must record exactly one candidate run"
            )
        if self.task["bootstrap_outcome"] is not None:
            raise AlignmentEvalError(
                f"{self.context}.bootstrap_outcome must be null for Phase B"
            )
        if self.fixture.first_diff_required != bool(self.revisions):
            raise AlignmentEvalError(
                f"{self.context} source revisions do not match first-diff preregistration"
            )
        last_envelope = observations.envelopes[-1]
        if last_envelope["operation"] != "obligation.find_evidence":
            raise AlignmentEvalError(
                f"{self.context} final observation must be obligation.find_evidence"
            )
        if observations.revision_ordinals[-1] is not None:
            raise AlignmentEvalError(
                f"{self.context} candidate observation must bind the original fixture tree"
            )
        observation = observations.rows[-1]
        candidate_run = self.candidate_run
        if (
            cast(str, last_envelope["result"]["obligation_id"])
            != candidate_run.obligation_id
            or observation["source_tree_manifest_path"]
            != candidate_run.source_tree_manifest_path
            or observation["source_tree_manifest_sha256"]
            != candidate_run.source_tree_manifest_sha256
            or observation["output_path"] != candidate_run.output_path
            or observations.raw_outputs[-1] != candidate_run.output_raw
            or observation["output_sha256"] != candidate_run.output_sha256
        ):
            raise AlignmentEvalError(
                f"{self.context} output does not match the canonical candidate run"
            )


def _validate_task(
    *,
    result_base: Path,
    fixture: _FixtureDefinition,
    value: object,
    phase: str,
    context: str,
    candidate_run: _CandidateRunBinding | None = None,
) -> tuple[str | None, bool]:
    return _TaskValidator(
        result_base=result_base,
        fixture=fixture,
        value=value,
        phase=phase,
        context=context,
        candidate_run=candidate_run,
    ).validate()


def _validate_candidate_runs(  # noqa: C901 approved [SC-17.1] RUFF-SUP-009 exception
    result_base: Path,
    phase: _PhaseManifest,
    value: object,
) -> tuple[
    list[tuple[str, dict[str, Any], dict[str, Any]]],
    set[tuple[str, str]],
    dict[str, _CandidateRunBinding],
]:
    if not isinstance(value, list):
        raise AlignmentEvalError("candidate_runs must be an array")
    if len(value) != len(phase.fixtures):
        raise AlignmentEvalError(
            "candidate_runs must exist exactly once per Phase B fixture"
        )
    surfaced: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    captured: set[tuple[str, str]] = set()
    bindings: dict[str, _CandidateRunBinding] = {}
    for index, (item, fixture) in enumerate(zip(value, phase.fixtures, strict=True)):
        context = f"candidate_runs[{index}]"
        run = _object(item, _CANDIDATE_RUN_KEYS, context)
        if run["fixture_id"] != fixture.fixture_id:
            raise AlignmentEvalError(f"{context}.fixture_id is out of order")
        obligation_id = _nonblank(run["obligation_id"], f"{context}.obligation_id")
        if obligation_id != fixture.task_obligation_id:
            raise AlignmentEvalError(f"{context}.obligation_id is incorrect")
        if run["source_tree_manifest_sha256"] != fixture.tree_manifest_sha256:
            raise AlignmentEvalError(f"{context} source tree hash is incorrect")
        _tree_rows_from_artifact(
            result_base,
            run["source_tree_manifest_path"],
            run["source_tree_manifest_sha256"],
            fixture.tree.root,
            f"{context} source tree",
        )
        artifact = fixture.candidate_artifact
        if artifact is None:
            raise AlignmentEvalError(f"{context} fixture has no candidate artifact")
        expected_snapshot = cast(dict[str, object], artifact["snapshot"])
        envelope, output_raw = _public_envelope(
            result_base,
            run["output_path"],
            run["output_sha256"],
            f"{context} output",
            expected_snapshot=expected_snapshot,
        )
        if envelope["operation"] != "obligation.find_evidence":
            raise AlignmentEvalError(
                f"{context} output must be obligation.find_evidence"
            )
        result = _object(
            envelope["result"],
            {"obligation_id", "candidates", "next_cursor"},
            f"{context} output.result",
        )
        if result["obligation_id"] != obligation_id:
            raise AlignmentEvalError(f"{context} output obligation_id is incorrect")
        if result["next_cursor"] is not None:
            raise AlignmentEvalError(f"{context} candidate output must be complete")
        public_candidates = result["candidates"]
        if not isinstance(public_candidates, list):
            raise AlignmentEvalError(f"{context} output candidates must be an array")
        if public_candidates != artifact["candidates"]:
            raise AlignmentEvalError(
                f"{context} candidates differ from production-derived preregistration"
            )
        reconstructed: list[dict[str, Any]] = []
        sort_rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
        candidate_ids: set[str] = set()
        for candidate_index, public in enumerate(public_candidates):
            candidate_context = f"{context} output candidates[{candidate_index}]"
            projection, gold = _candidate_projection(public, fixture, candidate_context)
            candidate_id = cast(str, projection["candidate_id"])
            if candidate_id in candidate_ids:
                raise AlignmentEvalError(f"{context} candidate IDs must be unique")
            candidate_ids.add(candidate_id)
            reconstructed.append(projection)
            sort_rows.append((projection, cast(dict[str, Any], public)))
            captured.add((fixture.fixture_id, cast(str, gold["gold_id"])))
            surfaced.append((fixture.fixture_id, projection, gold))
        _validate_candidate_relationships(
            cast(list[dict[str, Any]], public_candidates),
            obligation_id,
            f"{context} output candidates",
        )
        if sort_rows != sorted(
            sort_rows, key=lambda item: _candidate_sort_key(item[0], item[1])
        ):
            raise AlignmentEvalError(f"{context} candidates are not in EVC-7 order")
        stored = run["candidates"]
        if not isinstance(stored, list):
            raise AlignmentEvalError(f"{context}.candidates must be an array")
        for candidate_index, candidate in enumerate(stored):
            _object(
                candidate,
                _CANDIDATE_PROJECTION_KEYS,
                f"{context}.candidates[{candidate_index}]",
            )
        if stored != reconstructed:
            raise AlignmentEvalError(
                f"{context}.candidates do not reconstruct from CLI output"
            )
        matched_gold_ids = [
            cast(str, projection["matched_gold_id"]) for projection in reconstructed
        ]
        if len(set(matched_gold_ids)) != len(matched_gold_ids):
            raise AlignmentEvalError(
                f"{context} candidate rows must match distinct gold rows"
            )
        bindings[fixture.fixture_id] = _CandidateRunBinding(
            fixture_id=fixture.fixture_id,
            obligation_id=obligation_id,
            source_tree_manifest_path=cast(str, run["source_tree_manifest_path"]),
            source_tree_manifest_sha256=cast(str, run["source_tree_manifest_sha256"]),
            output_path=cast(str, run["output_path"]),
            output_sha256=cast(str, run["output_sha256"]),
            output_raw=output_raw,
            envelope=envelope,
        )
    return surfaced, captured, bindings


def _rate(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def _validate_stored_metrics(
    stored: object, expected: dict[str, object], keys: set[str], context: str
) -> None:
    row = _object(stored, keys, context)
    for key, value in row.items():
        if key.endswith("_count"):
            _nonnegative_integer(value, f"{context}.{key}")
        elif key.endswith("_rate"):
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0 <= float(value) <= 1
            ):
                raise AlignmentEvalError(
                    f"{context}.{key} must be null or a finite rate"
                )
    if row != expected:
        raise AlignmentEvalError(f"{context} does not recompute")


def _expected_checks(phase: str, metrics: dict[str, object]) -> list[dict[str, object]]:
    definitions: tuple[tuple[str, str, object], ...]
    if phase == "A":
        definitions = (
            (
                "minimum_bootstrap_completion_rate",
                ">=",
                metrics["bootstrap_completion_rate"],
            ),
            (
                "minimum_authority_comprehension_rate",
                ">=",
                metrics["authority_comprehension_rate"],
            ),
        )
    else:
        definitions = (
            (
                "minimum_candidate_capture_rate",
                ">=",
                metrics["candidate_capture_rate"],
            ),
            (
                "minimum_trace_state_precision",
                ">=",
                metrics["trace_state_precision"],
            ),
            (
                "maximum_irrelevant_candidate_rate",
                "<=",
                metrics["irrelevant_candidate_rate"],
            ),
            (
                "minimum_first_diff_correct_rate",
                ">=",
                metrics["first_diff_correct_rate"],
            ),
            (
                "require_all_critical_candidates",
                "true",
                metrics["all_critical_candidates_captured"],
            ),
        )
    rows: list[dict[str, object]] = []
    for name, comparator, observed in definitions:
        threshold = _INITIAL_THRESHOLDS[name]
        if comparator == ">=":
            passed = observed is not None and cast(float, observed) >= cast(
                float, threshold
            )
        elif comparator == "<=":
            passed = observed is not None and cast(float, observed) <= cast(
                float, threshold
            )
        else:
            passed = observed is True and threshold is True
        rows.append(
            {
                "name": name,
                "comparator": comparator,
                "threshold": threshold,
                "observed": observed,
                "passed": passed,
            }
        )
    return rows


@dataclass(frozen=True, slots=True)
class _AlignmentResultPreamble:
    result: dict[str, Any]
    raw_bytes: bytes
    phase_name: str
    phase: _PhaseManifest
    result_base: Path
    qualification_sha256: str
    distribution_sha256: str
    guide_sha256: str
    skill_sha256: str
    expected_session_count: int


@dataclass(frozen=True, slots=True)
class _AlignmentSessionEvaluation:
    sessions: list[dict[str, Any]]
    bootstrap_success_count: int
    authority_pass_count: int
    first_diff_correct_count: int
    invalid_observation: bool
    surfaced: list[tuple[str, dict[str, Any], dict[str, Any]]]
    captured: set[tuple[str, str]]


def _load_alignment_result_preamble(
    plan: AlignmentEvalPlan,
    result_path: Path,
    *,
    prior_phase_result_path: Path | None,
    require_current_product: bool,
) -> _AlignmentResultPreamble:
    raw, raw_bytes = _json_file(result_path, "alignment evaluation result")
    if raw_bytes != canonical_json_bytes(raw):
        raise AlignmentEvalError(
            "alignment evaluation result must use exact canonical JSON"
        )
    result = _object(raw, _RESULT_KEYS, "alignment evaluation result")
    if result["schema_version"] != 2:
        raise AlignmentEvalError("alignment evaluation result schema_version must be 2")
    if result["artifact"] != "backstitch-alignment-dogfood-result":
        raise AlignmentEvalError("alignment evaluation result artifact is invalid")
    phase_name = result["phase"]
    if phase_name not in {"A", "B"}:
        raise AlignmentEvalError("alignment evaluation result phase must be A or B")
    phase = plan._phase_a if phase_name == "A" else plan._phase_b
    result_base = result_path.parent.resolve(strict=True)
    qualification_sha256 = (
        plan.phase_a_qualification_sha256
        if phase_name == "A"
        else plan.phase_b_qualification_sha256
    )
    if result["phase_qualification_sha256"] != qualification_sha256:
        raise AlignmentEvalError("result phase qualification identity does not match")
    distribution = _sha256(
        result["tested_distribution_sha256"],
        "tested_distribution_sha256",
    )
    guide = _sha256(result["guide_sha256"], "guide_sha256")
    skill = _sha256(result["skill_sha256"], "skill_sha256")
    if (
        distribution != plan.tested_distribution_sha256
        or guide != plan.guide_sha256
        or skill != plan.skill_sha256
    ):
        raise AlignmentEvalError(
            "result product identities do not match the qualification manifest"
        )
    expected_session_count = _validate_prior_phase_result(
        plan,
        result,
        cast(str, phase_name),
        distribution,
        guide,
        skill,
        prior_phase_result_path=prior_phase_result_path,
        require_current_product=require_current_product,
    )
    return _AlignmentResultPreamble(
        result,
        raw_bytes,
        cast(str, phase_name),
        phase,
        result_base,
        qualification_sha256,
        distribution,
        guide,
        skill,
        expected_session_count,
    )


def _validate_prior_phase_result(
    plan: AlignmentEvalPlan,
    result: dict[str, Any],
    phase_name: str,
    distribution: str,
    guide: str,
    skill: str,
    *,
    prior_phase_result_path: Path | None,
    require_current_product: bool,
) -> int:
    if phase_name == "A":
        if result["prior_phase_result_sha256"] is not None:
            raise AlignmentEvalError("Phase A prior_phase_result_sha256 must be null")
        if prior_phase_result_path is not None:
            raise AlignmentEvalError("Phase A cannot be given a prior result")
        return plan.phase_a_sessions
    prior_hash = _sha256(
        result["prior_phase_result_sha256"],
        "prior_phase_result_sha256",
    )
    if prior_phase_result_path is None:
        raise AlignmentEvalError("Phase B requires its bound Phase A result")
    prior = _load_alignment_eval_result(
        plan,
        prior_phase_result_path,
        prior_phase_result_path=None,
        require_current_product=require_current_product,
    )
    if prior.phase != "A" or not prior.passed:
        raise AlignmentEvalError(
            "Phase B prior result must be a passing Phase A result"
        )
    if prior.result_sha256 != prior_hash:
        raise AlignmentEvalError("Phase B prior result hash does not match")
    if (
        prior.phase_qualification_sha256 != plan.phase_a_qualification_sha256
        or prior.tested_distribution_sha256 != distribution
        or prior.guide_sha256 != guide
        or prior.skill_sha256 != skill
    ):
        raise AlignmentEvalError("Phase B prior result identities do not match")
    return plan.phase_b_sessions


class _AlignmentSessionEvaluator:
    """Recompute session observations while retaining invalid-task semantics."""

    def __init__(self, preamble: _AlignmentResultPreamble) -> None:
        self.preamble = preamble
        self.result = preamble.result
        self.sessions: list[dict[str, Any]] = []
        self.session_ids: set[str] = set()
        self.participant_ids: set[str] = set()
        self.bootstrap_success_count = 0
        self.authority_pass_count = 0
        self.first_diff_correct_count = 0
        self.invalid_observation = False
        self.surfaced: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        self.captured: set[tuple[str, str]] = set()
        self.candidate_bindings: dict[str, _CandidateRunBinding] = {}

    def evaluate(self) -> _AlignmentSessionEvaluation:
        sessions = self.result["sessions"]
        if (
            not isinstance(sessions, list)
            or len(sessions) != self.preamble.expected_session_count
        ):
            raise AlignmentEvalError(
                "result session count does not match preregistration"
            )
        self.sessions = cast(list[dict[str, Any]], sessions)
        self.validate_candidate_runs()
        for session_index, item in enumerate(sessions):
            self.validate_session(item, session_index)
        return _AlignmentSessionEvaluation(
            self.sessions,
            self.bootstrap_success_count,
            self.authority_pass_count,
            self.first_diff_correct_count,
            self.invalid_observation,
            self.surfaced,
            self.captured,
        )

    def validate_candidate_runs(self) -> None:
        if self.preamble.phase_name == "A":
            if self.result["candidate_runs"] != []:
                raise AlignmentEvalError("Phase A candidate_runs must be empty")
            return
        try:
            (
                self.surfaced,
                self.captured,
                self.candidate_bindings,
            ) = _validate_candidate_runs(
                self.preamble.result_base,
                self.preamble.phase,
                self.result["candidate_runs"],
            )
        except AlignmentEvalError:
            self.invalid_observation = True

    def validate_session(self, item: object, session_index: int) -> None:
        context = f"sessions[{session_index}]"
        session = _object(item, _SESSION_KEYS, context)
        session_id = _nonblank(session["session_id"], f"{context}.session_id")
        participant_id = _sha256(
            session["participant_identity_sha256"],
            f"{context}.participant_identity_sha256",
        )
        if session_id in self.session_ids:
            raise AlignmentEvalError("session IDs must be unique")
        if participant_id in self.participant_ids:
            raise AlignmentEvalError("participant hashes must be unique within a phase")
        self.session_ids.add(session_id)
        self.participant_ids.add(participant_id)
        if session["participant_kind"] not in {"human", "agent"}:
            raise AlignmentEvalError(f"{context}.participant_kind is invalid")
        if session["public_help_only"] is not True:
            raise AlignmentEvalError(f"{context}.public_help_only must be true")
        self.validate_tasks(session, context)
        self.validate_authority_answers(session, context)

    def validate_tasks(self, session: dict[str, Any], context: str) -> None:
        tasks = session["tasks"]
        if not isinstance(tasks, list) or len(tasks) != len(
            self.preamble.phase.fixtures
        ):
            raise AlignmentEvalError(f"{context} must run every fixture exactly once")
        for task_index, (task, fixture) in enumerate(
            zip(tasks, self.preamble.phase.fixtures, strict=True)
        ):
            try:
                outcome, first_diff_correct = _validate_task(
                    result_base=self.preamble.result_base,
                    fixture=fixture,
                    value=task,
                    phase=self.preamble.phase_name,
                    context=f"{context}.tasks[{task_index}]",
                    candidate_run=self.candidate_bindings.get(fixture.fixture_id),
                )
            except AlignmentEvalError:
                self.invalid_observation = True
                outcome = None
                first_diff_correct = False
            if (
                self.preamble.phase_name == "A"
                and outcome == fixture.expected_bootstrap_outcome
            ):
                self.bootstrap_success_count += 1
            if (
                self.preamble.phase_name == "B"
                and fixture.first_diff_required
                and first_diff_correct
            ):
                self.first_diff_correct_count += 1

    def validate_authority_answers(
        self,
        session: dict[str, Any],
        context: str,
    ) -> None:
        authority = session["authority_answers"]
        if not isinstance(authority, list):
            raise AlignmentEvalError(f"{context}.authority_answers must be an array")
        if self.preamble.phase_name == "A":
            if self.authority_answers_are_correct(authority, context):
                self.authority_pass_count += 1
        elif authority:
            raise AlignmentEvalError(
                f"{context}.authority_answers must be empty for Phase B"
            )

    @staticmethod
    def authority_answers_are_correct(
        authority: list[object],
        context: str,
    ) -> bool:
        if len(authority) != len(_AUTHORITY_RUBRIC):
            raise AlignmentEvalError(
                f"{context} must answer all authority propositions"
            )
        correct = True
        for answer_index, (answer, rubric) in enumerate(
            zip(authority, _AUTHORITY_RUBRIC, strict=True)
        ):
            proposition, expected_answer = rubric
            row = _object(
                answer,
                {"proposition", "answer"},
                f"{context}.authority_answers[{answer_index}]",
            )
            if row["proposition"] != proposition or not isinstance(row["answer"], bool):
                raise AlignmentEvalError(
                    f"{context}.authority_answers do not match the frozen rubric"
                )
            correct = correct and row["answer"] is expected_answer
        return correct


def _alignment_result_metrics(
    preamble: _AlignmentResultPreamble,
    evaluation: _AlignmentSessionEvaluation,
) -> tuple[dict[str, object], set[str]]:
    sessions = evaluation.sessions
    phase = preamble.phase
    if preamble.phase_name == "A":
        task_count = len(sessions) * len(phase.fixtures)
        return (
            {
                "bootstrap_task_count": task_count,
                "bootstrap_success_count": evaluation.bootstrap_success_count,
                "authority_session_count": len(sessions),
                "authority_session_pass_count": evaluation.authority_pass_count,
                "bootstrap_completion_rate": _rate(
                    evaluation.bootstrap_success_count,
                    task_count,
                ),
                "authority_comprehension_rate": _rate(
                    evaluation.authority_pass_count,
                    len(sessions),
                ),
            },
            _PHASE_A_METRIC_KEYS,
        )
    gold_by_identity = {
        (fixture.fixture_id, cast(str, gold["gold_id"])): gold
        for fixture in phase.fixtures
        for gold in fixture.gold_candidates
    }
    eligible = {
        identity
        for identity, gold in gold_by_identity.items()
        if gold["disposition_label"] in {"accepted", "rejected"}
    }
    critical = {
        identity for identity, gold in gold_by_identity.items() if gold["critical"]
    }
    captured_eligible = evaluation.captured & eligible
    captured_critical = evaluation.captured & critical
    trace_correct = sum(
        projection["trace_state"] == gold["trace_state"]
        for _, projection, gold in evaluation.surfaced
    )
    irrelevant_count = sum(
        gold["disposition_label"] == "irrelevant" for _, _, gold in evaluation.surfaced
    )
    required_diff_count = len(sessions) * sum(
        fixture.first_diff_required for fixture in phase.fixtures
    )
    return (
        {
            "eligible_gold_candidate_count": len(eligible),
            "captured_eligible_gold_candidate_count": len(captured_eligible),
            "captured_trace_state_correct_count": trace_correct,
            "surfaced_candidate_count": len(evaluation.surfaced),
            "irrelevant_candidate_count": irrelevant_count,
            "first_diff_required_count": required_diff_count,
            "first_diff_correct_count": evaluation.first_diff_correct_count,
            "critical_candidate_count": len(critical),
            "critical_candidate_captured_count": len(captured_critical),
            "candidate_capture_rate": _rate(len(captured_eligible), len(eligible)),
            "trace_state_precision": _rate(
                trace_correct,
                len(evaluation.surfaced),
            ),
            "irrelevant_candidate_rate": _rate(
                irrelevant_count,
                len(evaluation.surfaced),
            ),
            "first_diff_correct_rate": _rate(
                evaluation.first_diff_correct_count,
                required_diff_count,
            ),
            "all_critical_candidates_captured": bool(critical)
            and len(captured_critical) == len(critical),
        },
        _PHASE_B_METRIC_KEYS,
    )


def _finish_alignment_eval_result(
    plan: AlignmentEvalPlan,
    preamble: _AlignmentResultPreamble,
    evaluation: _AlignmentSessionEvaluation,
    metrics: dict[str, object],
    metric_keys: set[str],
    *,
    require_current_product: bool,
) -> AlignmentEvalResult:
    result = preamble.result
    _validate_stored_metrics(result["metrics"], metrics, metric_keys, "metrics")
    expected_checks = _expected_checks(preamble.phase_name, metrics)
    checks = result["checks"]
    if not isinstance(checks, list):
        raise AlignmentEvalError("checks must be an array")
    for index, check in enumerate(checks):
        _object(check, _CHECK_KEYS, f"checks[{index}]")
    if checks != expected_checks:
        raise AlignmentEvalError("checks do not recompute")
    failure_reasons = (
        ["INVALID_OBSERVATION"] if evaluation.invalid_observation else []
    ) + [cast(str, check["name"]) for check in expected_checks if not check["passed"]]
    passed = not evaluation.invalid_observation and not any(
        not cast(bool, check["passed"]) for check in expected_checks
    )
    if result["passed"] is not passed:
        raise AlignmentEvalError("result passed flag does not recompute")
    if result["failure_reasons"] != failure_reasons:
        raise AlignmentEvalError("result failure_reasons do not recompute")
    if require_current_product and _authoritative_product_identities() != {
        "tested_distribution_sha256": plan.tested_distribution_sha256,
        "guide_sha256": plan.guide_sha256,
        "skill_sha256": plan.skill_sha256,
    }:
        raise AlignmentEvalError(
            "authoritative product inputs changed while loading the result"
        )
    return AlignmentEvalResult(
        result_sha256="sha256:" + hashlib.sha256(preamble.raw_bytes).hexdigest(),
        phase=preamble.phase_name,
        passed=passed,
        metrics=metrics,
        phase_qualification_sha256=preamble.qualification_sha256,
        tested_distribution_sha256=preamble.distribution_sha256,
        guide_sha256=preamble.guide_sha256,
        skill_sha256=preamble.skill_sha256,
    )


def _load_alignment_eval_result(
    plan: AlignmentEvalPlan,
    result_path: Path,
    *,
    prior_phase_result_path: Path | None,
    require_current_product: bool,
) -> AlignmentEvalResult:
    preamble = _load_alignment_result_preamble(
        plan,
        result_path,
        prior_phase_result_path=prior_phase_result_path,
        require_current_product=require_current_product,
    )
    evaluation = _AlignmentSessionEvaluator(preamble).evaluate()
    metrics, metric_keys = _alignment_result_metrics(preamble, evaluation)
    return _finish_alignment_eval_result(
        plan,
        preamble,
        evaluation,
        metrics,
        metric_keys,
        require_current_product=require_current_product,
    )


def load_alignment_eval_result(
    plan_path: Path,
    result_path: Path,
    *,
    prior_phase_result_path: Path | None = None,
    require_current_product: bool = False,
) -> AlignmentEvalResult:
    """Validate and recompute one Phase A or B product-evaluation result.

    Result and observation artifacts remain qualification evidence only. This
    API never contributes runtime trace relations or obligation readiness.
    """

    plan = load_alignment_eval_plan(
        plan_path, require_current_product=require_current_product
    )
    return _load_alignment_eval_result(
        plan,
        result_path,
        prior_phase_result_path=prior_phase_result_path,
        require_current_product=require_current_product,
    )
