"""Closed schema-3 semantic evaluation corpus and report contracts.

This module is deliberately provider-free.  It validates committed corpus,
fixture-tree, and qualification-report bytes and exposes a separate observed-
facts boundary for the production source pipeline.

Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-10.1]
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Literal, cast

from backstitch.canonical import canonical_json_bytes, lf_slice
from backstitch.contract_validation import ValidationPolicy, make_validators
from backstitch.filesystem_io import StableReadError, read_regular_nofollow
from backstitch.grammar import candidate_ref
from backstitch.semantic_eval_identity import derive_eval_search_epoch
from backstitch.semantic_verification_contract import VerificationContractError

_DEFAULT_MANIFEST_BYTES = 16 * 1024 * 1024
_DEFAULT_TREE_MANIFEST_BYTES = 16 * 1024 * 1024
_DEFAULT_REPORT_BYTES = 64 * 1024 * 1024

_CONTROL_TAGS = (
    "historical_misalignment",
    "valid_vacuous_trace",
    "analyzer_false_positive",
    "analyzer_false_negative",
    "verifier_false_positive",
    "verifier_false_negative",
    "indeterminate",
    "uncached_flip",
    "misleading_nearby_code",
    "out_of_packet_decoy",
    "omitted_disconfirming_evidence",
    "prompt_injection_source",
)
_POSITIVE_CONTROL_TAGS = frozenset(
    {
        "analyzer_false_negative",
        "verifier_false_negative",
        "indeterminate",
        "uncached_flip",
        "valid_vacuous_trace",
        "omitted_disconfirming_evidence",
    }
)
_NEGATIVE_CONTROL_TAGS = frozenset(
    {"analyzer_false_positive", "verifier_false_positive"}
)
_SEMANTIC_CODES = (
    "SEMANTIC_CONFIRMED_MISMATCH",
    "SEMANTIC_PROBABLE_MISMATCH",
    "SEMANTIC_MISSING_TRACE",
    "SEMANTIC_WEAK_BINDING",
    "SEMANTIC_AMBIGUOUS",
)
_CODE_BY_CLASSIFICATION = {
    "confirmed_mismatch": "SEMANTIC_CONFIRMED_MISMATCH",
    "probable_mismatch": "SEMANTIC_PROBABLE_MISMATCH",
    "missing_trace": "SEMANTIC_MISSING_TRACE",
    "weak_binding": "SEMANTIC_WEAK_BINDING",
    "ambiguous": "SEMANTIC_AMBIGUOUS",
}
_CANDIDATE_KINDS = (
    "implementation_definition",
    "test_definition",
    "static_reference",
    "unresolved_reference",
    "report_issue",
)
_TRACE_STATES = ("declared", "partially_declared", "untraced", "conflicted")
_SOURCE_ROLES = ("implementation", "test", "binding_test")
_INTENT_STATES = ("identified",)
_ALIGNMENT_STATES = ("untraced", "partial", "complete", "invalid")
_DISPOSITIONS = ("evaluate", "skipped")
_RUNGS = ("active", "planned", "exploratory", "meta")
_GATE_STATES = ("not_executable", "executable")
_RECIPROCITY_STATES = ("complete", "one_sided")

_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "corpus_id",
        "reviewed_historical_units",
        "critical_case_ids",
        "critical_vacuous_trace_case_ids",
        "cases",
    }
)
_CASE_FIELDS = frozenset(
    {
        "case_id",
        "deterministic_config",
        "clean",
        "mutations",
        "gold_obligations",
        "gold_evidence",
        "gold_candidates",
        "expected_findings",
        "critical",
    }
)
_FIXTURE_FIELDS = frozenset(
    {
        "variant_id",
        "fixture_path",
        "tree_manifest_path",
        "tree_manifest_sha256",
        "transform",
        "control_tags",
    }
)
_GOLD_OBLIGATION_FIELDS = frozenset(
    {
        "gold_id",
        "variant_id",
        "obligation_id",
        "packet_id",
        "intent_state",
        "alignment_state",
        "disposition",
        "obligation_rung",
        "gate_state",
    }
)
_GOLD_EVIDENCE_FIELDS = frozenset(
    {
        "gold_id",
        "variant_id",
        "obligation_id",
        "source_role",
        "path",
        "structural_locator",
        "start_line",
        "end_line",
        "receipt_hash",
        "reciprocity_state",
    }
)
_GOLD_CANDIDATE_FIELDS = frozenset(
    {
        "gold_id",
        "variant_id",
        "obligation_id",
        "candidate_id",
        "candidate_kind",
        "path",
        "structural_locator",
        "start_line",
        "end_line",
        "receipt_hash",
        "trace_state",
    }
)
_EXPECTED_FINDING_FIELDS = frozenset(
    {
        "gold_id",
        "variant_id",
        "packet_id",
        "code",
        "classification",
        "required_declared_evidence_gold_ids",
        "required_counterevidence_gold_ids",
    }
)
_HISTORICAL_FIELDS = frozenset(
    {
        "unit_id",
        "case_id",
        "variant_id",
        "expected_finding_gold_id",
        "source_reference",
        "review_reference",
    }
)
_DETERMINISTIC_CONFIG_FIELDS = frozenset({"profile", "exclude_globs", "obligations"})
_PROFILE_FIELDS = frozenset(
    {
        "spec_roots",
        "plan_roots",
        "code_roots",
        "test_roots",
        "planned_spec_globs",
        "exploratory_spec_globs",
        "meta_spec_globs",
    }
)
_OBLIGATION_CONFIG_FIELDS = frozenset(
    {
        "section_required_roles",
        "page_size",
        "maximum_page_size",
        "maximum_response_bytes",
        "maximum_candidate_items",
        "maximum_catalog_items",
        "maximum_lexical_seeds",
        "maximum_snapshot_files",
        "maximum_file_bytes",
        "maximum_snapshot_bytes",
        "maximum_work_units",
        "maximum_packet_bytes",
        "maximum_packet_report_bytes",
        "maximum_call_seconds",
        "snapshot_capture_attempts",
        "static_neighbor_depth",
    }
)
_TREE_FIELDS = frozenset({"schema_version", "artifact", "files"})
_TREE_FILE_FIELDS = frozenset({"path", "raw_sha256", "byte_count", "executable"})


class SemanticEvalContractError(ValueError):
    """A schema-3 semantic evaluation artifact violated [EVC-10.1]."""


_EVAL_VALIDATORS = make_validators(
    SemanticEvalContractError, ValidationPolicy(require_nfc=True)
)


@dataclass(frozen=True, slots=True)
class SemanticEvalFixture:
    """One validated fixture variant and its exact frozen file inventory."""

    case_id: str
    variant_id: str
    control_tags: tuple[str, ...]
    tree_manifest_sha256: str
    files: tuple[str, ...]
    executable_files: tuple[str, ...]
    _file_bytes: Mapping[str, bytes] = field(repr=False, compare=False)

    def read_bytes(self, path: str) -> bytes:
        """Return one already-validated frozen file; never reopen the fixture."""

        try:
            return self._file_bytes[path]
        except KeyError:
            raise SemanticEvalContractError(
                f"fixture {self.case_id}/{self.variant_id} has no file {path!r}"
            ) from None

    def materialize(self, destination: Path) -> None:
        """Write this frozen tree without reopening its corpus source."""

        if destination.exists():
            if not destination.is_dir() or any(destination.iterdir()):
                raise SemanticEvalContractError(
                    "fixture destination must be absent or an empty directory"
                )
        destination.mkdir(parents=True, exist_ok=True)
        executable = set(self.executable_files)
        for path in self.files:
            target = destination / PurePosixPath(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                with target.open("xb") as handle:
                    handle.write(self._file_bytes[path])
                target.chmod(0o755 if path in executable else 0o644)
            except OSError as exc:
                raise SemanticEvalContractError(
                    f"cannot materialize fixture file {path!r}: {exc}"
                ) from exc


@dataclass(frozen=True, slots=True)
class SemanticEvalCorpus:
    """Validated schema-3 corpus plus frozen fixture bytes."""

    path: Path = field(repr=False, compare=False)
    corpus_id: str
    corpus_sha256: str
    mode: Literal["report", "enforce"]
    case_ids: tuple[str, ...]
    variant_keys: tuple[tuple[str, str], ...]
    _canonical: bytes = field(repr=False, compare=False)
    _fixtures: Mapping[tuple[str, str], SemanticEvalFixture] = field(
        repr=False, compare=False
    )

    def to_dict(self) -> dict[str, Any]:
        value = json.loads(self._canonical)
        assert isinstance(value, dict)
        return cast(dict[str, Any], value)

    def fixture(self, case_id: str, variant_id: str) -> SemanticEvalFixture:
        try:
            return self._fixtures[(case_id, variant_id)]
        except KeyError:
            raise SemanticEvalContractError(
                f"unknown semantic eval fixture {case_id}/{variant_id}"
            ) from None

    def fixture_files(self, case_id: str, variant_id: str) -> tuple[str, ...]:
        return self.fixture(case_id, variant_id).files


@dataclass(frozen=True, slots=True)
class SemanticEvalObservedVariantFacts:
    """Source-pipeline facts for one already-derived corpus variant.

    These values are produced by the ordinary snapshot, obligation,
    discovery, and packet pipeline.  They are deliberately separate from the
    report so a report cannot assert the source facts used to grade itself.
    """

    case_id: str
    variant_id: str
    obligations: tuple[Mapping[str, Any], ...]
    evidence: tuple[Mapping[str, Any], ...]
    candidates: tuple[Mapping[str, Any], ...]
    packets: tuple[Mapping[str, Any], ...]
    deterministic_issue_count: int = 0
    deterministic_problem: str | None = None


@dataclass(frozen=True, slots=True)
class SemanticEvalObservedFacts:
    """Complete source-pipeline observations for one corpus evaluation."""

    variants: tuple[SemanticEvalObservedVariantFacts, ...]


def _closed(value: object, fields: frozenset[str], name: str) -> dict[str, Any]:
    return _EVAL_VALIDATORS.closed_record(value, fields, name)


def _array(value: object, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise SemanticEvalContractError(f"{name} must be an array")
    return value


def _nonblank(value: object, name: str) -> str:
    return _EVAL_VALIDATORS.nonblank(value, name)


def _enum(value: object, choices: tuple[str, ...], name: str) -> str:
    if value not in choices:
        raise SemanticEvalContractError(f"{name} is outside its closed vocabulary")
    return value


def _boolean(value: object, name: str) -> bool:
    return _EVAL_VALIDATORS.boolean(value, name)


def _integer(value: object, name: str, *, minimum: int = 0) -> int:
    return _EVAL_VALIDATORS.integer(value, name, minimum=minimum)


def _finite(value: object, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise SemanticEvalContractError(f"{name} must be a finite number")
    return float(value)


def _digest(value: object, name: str, *, prefixed: bool = False) -> str:
    return _EVAL_VALIDATORS.digest(value, name, prefixed=prefixed)


def _relative_path(value: object, name: str) -> str:
    return _EVAL_VALIDATORS.relative_path(value, name)


def _ordered_unique_strings(
    value: object,
    name: str,
    *,
    order: tuple[str, ...] | None = None,
    allow_empty: bool = True,
    require_sorted: bool = False,
) -> tuple[str, ...]:
    rows = _array(value, name)
    result = tuple(
        _nonblank(item, f"{name}[{index}]") for index, item in enumerate(rows)
    )
    if not allow_empty and not result:
        raise SemanticEvalContractError(f"{name} must not be empty")
    if len(set(result)) != len(result):
        raise SemanticEvalContractError(f"{name} must contain unique strings")
    expected = (
        tuple(sorted(result))
        if order is None
        else tuple(item for item in order if item in result)
    )
    if (order is not None or require_sorted) and result != expected:
        raise SemanticEvalContractError(f"{name} is out of canonical order")
    return result


def _contained_artifact_path(root: Path, relative: str, name: str) -> Path:
    """Resolve containment while retaining lexical paths for symlink checks."""

    path = root / PurePosixPath(relative)
    try:
        resolved = path.resolve()
    except OSError as exc:
        raise SemanticEvalContractError(f"cannot resolve {name}: {exc}") from exc
    if not resolved.is_relative_to(root):
        raise SemanticEvalContractError(f"{name} escapes the manifest root")
    current = root
    for part in PurePosixPath(relative).parts:
        current /= part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            break
        except OSError as exc:
            raise SemanticEvalContractError(f"cannot inspect {name}: {exc}") from exc
        if stat.S_ISLNK(mode):
            raise SemanticEvalContractError(f"{name} contains a symlink component")
    return path


def _read_regular(path: Path, *, maximum_bytes: int, name: str) -> bytes:
    _integer(maximum_bytes, f"{name}.maximum_bytes", minimum=1)
    try:
        before = path.lstat()
    except OSError as exc:
        raise SemanticEvalContractError(f"cannot inspect {name}: {exc}") from exc
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise SemanticEvalContractError(f"{name} must be a regular non-symlink file")
    if before.st_size > maximum_bytes:
        raise SemanticEvalContractError(f"{name} exceeds its bounded read")
    try:
        raw, _observed = read_regular_nofollow(
            path.parent,
            path.name,
            expected_stat=before,
            maximum_bytes=maximum_bytes,
        )
    except StableReadError as exc:
        raise SemanticEvalContractError(f"cannot read {name}: {exc}") from exc
    return raw


def _parse_canonical_object(
    raw: bytes,
    *,
    name: str,
    final_lf: Literal["optional", "required", "forbidden"],
) -> tuple[dict[str, Any], bytes]:
    payload = raw
    if final_lf == "required":
        if not raw.endswith(b"\n") or raw.endswith(b"\n\n"):
            raise SemanticEvalContractError(f"{name} requires exactly one final LF")
        payload = raw[:-1]
    elif final_lf == "optional" and raw.endswith(b"\n"):
        payload = raw[:-1]
    elif final_lf == "forbidden" and raw.endswith(b"\n"):
        raise SemanticEvalContractError(f"{name} must not have a final LF")
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SemanticEvalContractError(f"{name} is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise SemanticEvalContractError(f"{name} must be a JSON object")
    try:
        canonical = canonical_json_bytes(value)
    except (TypeError, ValueError) as exc:
        raise SemanticEvalContractError(
            f"{name} is not canonicalizable: {exc}"
        ) from exc
    if payload != canonical:
        raise SemanticEvalContractError(f"{name} must use canonical JSON bytes")
    return cast(dict[str, Any], value), canonical


def _validate_deterministic_config(value: object, name: str) -> None:  # noqa: C901 approved [SC-17.1] RUFF-SUP-094 exception
    row = _closed(value, _DETERMINISTIC_CONFIG_FIELDS, name)
    profile = _closed(row["profile"], _PROFILE_FIELDS, f"{name}.profile")
    roots: dict[str, tuple[str, ...]] = {}
    for field_name in ("spec_roots", "plan_roots", "code_roots", "test_roots"):
        values = tuple(
            _relative_path(item, f"{name}.profile.{field_name}[{index}]")
            for index, item in enumerate(
                _array(profile[field_name], f"{name}.profile.{field_name}")
            )
        )
        if len(set(values)) != len(values):
            raise SemanticEvalContractError(
                f"{name}.profile.{field_name} must be unique"
            )
        roots[field_name] = values
    if any(
        not any(
            test == code or PurePosixPath(test).is_relative_to(PurePosixPath(code))
            for code in roots["code_roots"]
        )
        for test in roots["test_roots"]
    ):
        raise SemanticEvalContractError(f"{name}.profile.test_roots escape code_roots")
    for field_name in (
        "planned_spec_globs",
        "exploratory_spec_globs",
        "meta_spec_globs",
    ):
        values = _ordered_unique_strings(
            profile[field_name], f"{name}.profile.{field_name}"
        )
        if any("\\" in item for item in values):
            raise SemanticEvalContractError(
                f"{name}.profile.{field_name} must use POSIX syntax"
            )
    _ordered_unique_strings(row["exclude_globs"], f"{name}.exclude_globs")
    obligations = _closed(
        row["obligations"], _OBLIGATION_CONFIG_FIELDS, f"{name}.obligations"
    )
    roles = _ordered_unique_strings(
        obligations["section_required_roles"],
        f"{name}.obligations.section_required_roles",
        order=("implementation", "test"),
        allow_empty=False,
    )
    if "implementation" not in roles:
        raise SemanticEvalContractError(
            f"{name}.obligations.section_required_roles requires implementation"
        )
    positive_fields = tuple(
        field_name
        for field_name in _OBLIGATION_CONFIG_FIELDS
        if field_name
        not in {
            "section_required_roles",
            "maximum_call_seconds",
            "static_neighbor_depth",
        }
    )
    integers = {
        field_name: _integer(
            obligations[field_name], f"{name}.obligations.{field_name}", minimum=1
        )
        for field_name in positive_fields
    }
    depth = _integer(
        obligations["static_neighbor_depth"],
        f"{name}.obligations.static_neighbor_depth",
    )
    if depth > 3:
        raise SemanticEvalContractError(
            f"{name}.obligations.static_neighbor_depth must be at most 3"
        )
    attempts = integers["snapshot_capture_attempts"]
    if attempts > 10:
        raise SemanticEvalContractError(
            f"{name}.obligations.snapshot_capture_attempts must be at most 10"
        )
    deadline = _finite(
        obligations["maximum_call_seconds"],
        f"{name}.obligations.maximum_call_seconds",
    )
    if deadline <= 0:
        raise SemanticEvalContractError(
            f"{name}.obligations.maximum_call_seconds must be positive"
        )
    if integers["maximum_response_bytes"] < 16_384:
        raise SemanticEvalContractError(f"{name}.maximum_response_bytes is too small")
    if integers["page_size"] > integers["maximum_page_size"]:
        raise SemanticEvalContractError(f"{name}.page_size exceeds maximum_page_size")
    if integers["maximum_snapshot_bytes"] < integers["maximum_file_bytes"]:
        raise SemanticEvalContractError(
            f"{name}.maximum_snapshot_bytes is below maximum_file_bytes"
        )
    if integers["maximum_packet_bytes"] < 16_384:
        raise SemanticEvalContractError(f"{name}.maximum_packet_bytes is too small")
    if integers["maximum_packet_report_bytes"] < 16_384:
        raise SemanticEvalContractError(
            f"{name}.maximum_packet_report_bytes is too small"
        )


def _load_fixture_tree(  # noqa: C901 approved [SC-17.1] RUFF-SUP-091 exception
    root: Path,
    tree_path: Path,
    *,
    expected_digest: str,
    maximum_tree_manifest_bytes: int,
    maximum_files: int,
    maximum_file_bytes: int,
    maximum_total_bytes: int,
    name: str,
) -> tuple[tuple[str, ...], tuple[str, ...], Mapping[str, bytes]]:
    raw = _read_regular(
        tree_path, maximum_bytes=maximum_tree_manifest_bytes, name=f"{name}.tree"
    )
    tree, canonical = _parse_canonical_object(
        raw, name=f"{name}.tree", final_lf="forbidden"
    )
    if "sha256:" + hashlib.sha256(canonical).hexdigest() != expected_digest:
        raise SemanticEvalContractError(f"{name}.tree digest does not match")
    row = _closed(tree, _TREE_FIELDS, f"{name}.tree")
    if row["schema_version"] != 1 or row["artifact"] != "backstitch-eval-fixture-tree":
        raise SemanticEvalContractError(f"{name}.tree identity is invalid")
    expected_rows: list[dict[str, Any]] = []
    prior_path: str | None = None
    for index, item in enumerate(_array(row["files"], f"{name}.tree.files")):
        entry = _closed(item, _TREE_FILE_FIELDS, f"{name}.tree.files[{index}]")
        path = _relative_path(entry["path"], f"{name}.tree.files[{index}].path")
        if prior_path is not None and path <= prior_path:
            raise SemanticEvalContractError(
                f"{name}.tree.files is not unique and ordered"
            )
        prior_path = path
        expected_rows.append(
            {
                "path": path,
                "raw_sha256": _digest(
                    entry["raw_sha256"],
                    f"{name}.tree.files[{index}].raw_sha256",
                    prefixed=True,
                ),
                "byte_count": _integer(
                    entry["byte_count"], f"{name}.tree.files[{index}].byte_count"
                ),
                "executable": _boolean(
                    entry["executable"], f"{name}.tree.files[{index}].executable"
                ),
            }
        )
    if len(expected_rows) > maximum_files:
        raise SemanticEvalContractError(f"{name} exceeds maximum_snapshot_files")
    try:
        root_mode = root.lstat().st_mode
    except OSError as exc:
        raise SemanticEvalContractError(
            f"cannot inspect {name}.fixture: {exc}"
        ) from exc
    if stat.S_ISLNK(root_mode) or not stat.S_ISDIR(root_mode):
        raise SemanticEvalContractError(
            f"{name}.fixture must be a non-symlink directory"
        )
    observed_rows: list[dict[str, Any]] = []
    files: dict[str, bytes] = {}
    total = 0
    for current, directories, names in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        for directory in directories:
            child = current_path / directory
            mode = child.lstat().st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
                raise SemanticEvalContractError(
                    f"{name}.fixture contains a non-directory or symlink: {child}"
                )
        for filename in names:
            child = current_path / filename
            relative = child.relative_to(root).as_posix()
            relative = _relative_path(relative, f"{name}.fixture file")
            data = _read_regular(
                child,
                maximum_bytes=maximum_file_bytes,
                name=f"{name}.fixture/{relative}",
            )
            total += len(data)
            if total > maximum_total_bytes:
                raise SemanticEvalContractError(
                    f"{name} exceeds maximum_snapshot_bytes"
                )
            mode = child.lstat().st_mode
            files[relative] = data
            observed_rows.append(
                {
                    "path": relative,
                    "raw_sha256": "sha256:" + hashlib.sha256(data).hexdigest(),
                    "byte_count": len(data),
                    "executable": bool(mode & stat.S_IXUSR),
                }
            )
    observed_rows.sort(key=lambda item: cast(str, item["path"]))
    if observed_rows != expected_rows:
        raise SemanticEvalContractError(
            f"{name}.fixture does not match its tree manifest"
        )
    executable = tuple(
        cast(str, item["path"])
        for item in expected_rows
        if cast(bool, item["executable"])
    )
    ordered_files = tuple(cast(str, item["path"]) for item in expected_rows)
    return ordered_files, executable, MappingProxyType(dict(files))


def _receipt_hash(
    *,
    path: str,
    structural_locator: str,
    start_line: int,
    end_line: int,
    raw: bytes,
) -> str:
    try:
        span = lf_slice(raw, start_line, end_line, policy="strict")
    except ValueError:
        message = (
            "gold span is outside an empty fixture file"
            if raw == b""
            else "gold span is outside its fixture file"
        )
        raise SemanticEvalContractError(message) from None
    receipt = {
        "receipt_version": 1,
        "path": path,
        "structural_locator": structural_locator,
        "start_line": start_line,
        "end_line": end_line,
        "raw_sha256": hashlib.sha256(span).hexdigest(),
    }
    return hashlib.sha256(canonical_json_bytes(receipt)).hexdigest()


def _candidate_id(*, kind: str, path: str, locator: str) -> str:
    digest = hashlib.sha256(
        canonical_json_bytes(
            {
                "candidate_identity_version": 1,
                "candidate_kind": kind,
                "path": path,
                "structural_locator": locator,
            }
        )
    ).hexdigest()
    return candidate_ref(digest)


def _validate_span_record(
    row: dict[str, Any], fixture: SemanticEvalFixture, name: str
) -> tuple[str, str, int, int]:
    path = _relative_path(row["path"], f"{name}.path")
    locator = _nonblank(row["structural_locator"], f"{name}.structural_locator")
    start = _integer(row["start_line"], f"{name}.start_line", minimum=1)
    end = _integer(row["end_line"], f"{name}.end_line", minimum=1)
    if end < start:
        raise SemanticEvalContractError(f"{name} has a reversed span")
    raw = fixture.read_bytes(path)
    expected = _receipt_hash(
        path=path,
        structural_locator=locator,
        start_line=start,
        end_line=end,
        raw=raw,
    )
    if _digest(row["receipt_hash"], f"{name}.receipt_hash") != expected:
        raise SemanticEvalContractError(f"{name}.receipt_hash does not recompute")
    return path, locator, start, end


@dataclass(slots=True)
class _SemanticEvalCorpusValidator:
    """Ordered schema-3 corpus validation over one frozen manifest."""

    manifest_path: Path
    canonical: bytes
    row: dict[str, Any]
    corpus_id: str
    corpus_sha256: str
    mode: Literal["report", "enforce"]
    maximum_tree_manifest_bytes: int
    case_ids: list[str] = field(default_factory=list)
    fixtures: dict[tuple[str, str], SemanticEvalFixture] = field(default_factory=dict)
    case_rows: dict[str, dict[str, Any]] = field(default_factory=dict)
    fixture_paths: set[Path] = field(default_factory=set)
    tree_paths: set[Path] = field(default_factory=set)
    critical: tuple[str, ...] = ()
    critical_vacuous: tuple[str, ...] = ()
    expected_by_case_variant: dict[tuple[str, str], list[dict[str, Any]]] = field(
        default_factory=dict
    )
    finding_by_gold: dict[tuple[str, str, str], dict[str, Any]] = field(
        default_factory=dict
    )
    historical_targets: set[tuple[str, str, str]] = field(default_factory=set)

    def validate(self) -> SemanticEvalCorpus:
        self._load_cases()
        self._validate_critical_cases()
        self._validate_gold()
        self._validate_critical_vacuous_cases()
        self._validate_historical_units()
        self._validate_enforce_requirements()
        return SemanticEvalCorpus(
            path=self.manifest_path,
            corpus_id=self.corpus_id,
            corpus_sha256=self.corpus_sha256,
            mode=self.mode,
            case_ids=tuple(self.case_ids),
            variant_keys=tuple(self.fixtures),
            _canonical=self.canonical,
            _fixtures=MappingProxyType(dict(self.fixtures)),
        )

    def _load_cases(self) -> None:
        cases = _array(self.row["cases"], "semantic eval corpus.cases")
        for case_index, item in enumerate(cases):
            case = _closed(item, _CASE_FIELDS, f"cases[{case_index}]")
            case_id = _nonblank(case["case_id"], f"cases[{case_index}].case_id")
            if self.case_ids and case_id <= self.case_ids[-1]:
                raise SemanticEvalContractError(
                    "semantic eval case IDs must be unique and ordered"
                )
            self.case_ids.append(case_id)
            self.case_rows[case_id] = case
            _validate_deterministic_config(
                case["deterministic_config"],
                f"cases[{case_index}].deterministic_config",
            )
            _boolean(case["critical"], f"cases[{case_index}].critical")
            fixture_values = [
                case["clean"],
                *_array(case["mutations"], f"cases[{case_index}].mutations"),
            ]
            variant_ids: list[str] = []
            for variant_index, fixture_value in enumerate(fixture_values):
                self._load_fixture(
                    case_index,
                    case_id,
                    case,
                    variant_index,
                    fixture_value,
                    variant_ids,
                )

    def _load_fixture(
        self,
        case_index: int,
        case_id: str,
        case: dict[str, Any],
        variant_index: int,
        fixture_value: object,
        variant_ids: list[str],
    ) -> None:
        name = f"cases[{case_index}].fixtures[{variant_index}]"
        fixture_row = _closed(fixture_value, _FIXTURE_FIELDS, name)
        variant_id = _nonblank(
            fixture_row["variant_id"],
            f"{name}.variant_id",
        )
        self._validate_fixture_identity(
            case_index,
            variant_index,
            variant_id,
            fixture_row["transform"],
            variant_ids,
        )
        variant_ids.append(variant_id)
        fixture_relative = _relative_path(
            fixture_row["fixture_path"],
            f"{name}.fixture_path",
        )
        tree_relative = _relative_path(
            fixture_row["tree_manifest_path"],
            f"{name}.tree_manifest_path",
        )
        manifest_root = self.manifest_path.parent
        fixture_path = _contained_artifact_path(
            manifest_root,
            fixture_relative,
            f"{name}.fixture_path",
        )
        tree_path = _contained_artifact_path(
            manifest_root,
            tree_relative,
            f"{name}.tree_manifest_path",
        )
        if tree_path.resolve().is_relative_to(fixture_path.resolve()):
            raise SemanticEvalContractError("tree manifest must be outside its fixture")
        if fixture_path in self.fixture_paths or tree_path in self.tree_paths:
            raise SemanticEvalContractError("fixture and tree paths must be unique")
        self.fixture_paths.add(fixture_path)
        self.tree_paths.add(tree_path)
        tags = _ordered_unique_strings(
            fixture_row["control_tags"],
            f"{name}.control_tags",
            order=_CONTROL_TAGS,
        )
        deterministic = cast(dict[str, Any], case["deterministic_config"])
        limits = cast(dict[str, Any], deterministic["obligations"])
        tree_digest = _digest(
            fixture_row["tree_manifest_sha256"],
            f"{name}.tree_manifest_sha256",
            prefixed=True,
        )
        file_names, executable_files, file_bytes = _load_fixture_tree(
            fixture_path,
            tree_path,
            expected_digest=tree_digest,
            maximum_tree_manifest_bytes=self.maximum_tree_manifest_bytes,
            maximum_files=cast(int, limits["maximum_snapshot_files"]),
            maximum_file_bytes=cast(int, limits["maximum_file_bytes"]),
            maximum_total_bytes=cast(int, limits["maximum_snapshot_bytes"]),
            name=name,
        )
        self.fixtures[(case_id, variant_id)] = SemanticEvalFixture(
            case_id=case_id,
            variant_id=variant_id,
            control_tags=tags,
            tree_manifest_sha256=tree_digest,
            files=file_names,
            executable_files=executable_files,
            _file_bytes=MappingProxyType(dict(file_bytes)),
        )

    @staticmethod
    def _validate_fixture_identity(
        case_index: int,
        variant_index: int,
        variant_id: str,
        transform: object,
        variant_ids: list[str],
    ) -> None:
        if variant_index == 0:
            if variant_id != "clean" or transform is not None:
                raise SemanticEvalContractError(
                    f"cases[{case_index}].clean identity or transform is invalid"
                )
        elif (
            variant_id == "clean"
            or not isinstance(transform, str)
            or not transform.strip()
        ):
            raise SemanticEvalContractError(
                f"cases[{case_index}].mutations[{variant_index - 1}] transform is invalid"
            )
        elif variant_ids[1:] and variant_id <= variant_ids[-1]:
            raise SemanticEvalContractError(
                f"cases[{case_index}].mutations must be unique and ordered"
            )
        if variant_id in variant_ids:
            raise SemanticEvalContractError(f"cases[{case_index}] repeats variant_id")

    def _validate_critical_cases(self) -> None:
        critical_expected = tuple(
            case_id
            for case_id in self.case_ids
            if cast(bool, self.case_rows[case_id]["critical"])
        )
        self.critical = _ordered_unique_strings(
            self.row["critical_case_ids"],
            "semantic eval corpus.critical_case_ids",
            require_sorted=True,
        )
        if self.critical != critical_expected:
            raise SemanticEvalContractError(
                "critical_case_ids does not match critical cases"
            )
        self.critical_vacuous = _ordered_unique_strings(
            self.row["critical_vacuous_trace_case_ids"],
            "semantic eval corpus.critical_vacuous_trace_case_ids",
            require_sorted=True,
        )
        if not set(self.critical_vacuous).issubset(self.critical):
            raise SemanticEvalContractError(
                "critical_vacuous_trace_case_ids is not a critical subset"
            )

    def _validate_gold(self) -> None:
        for case_index, case_id in enumerate(self.case_ids):
            self._validate_case_gold(case_index, case_id)

    def _validate_case_gold(self, case_index: int, case_id: str) -> None:
        case = self.case_rows[case_id]
        variants = [
            "clean",
            *[
                cast(dict[str, Any], item)["variant_id"]
                for item in cast(list[Any], case["mutations"])
            ],
        ]
        variant_order = {variant: index for index, variant in enumerate(variants)}
        obligations: dict[tuple[str, str], dict[str, Any]] = {}
        evidence: dict[str, dict[str, Any]] = {}
        candidates: dict[str, dict[str, Any]] = {}
        all_gold_ids: set[str] = set()
        arrays = (
            ("gold_obligations", _GOLD_OBLIGATION_FIELDS),
            ("gold_evidence", _GOLD_EVIDENCE_FIELDS),
            ("gold_candidates", _GOLD_CANDIDATE_FIELDS),
            ("expected_findings", _EXPECTED_FINDING_FIELDS),
        )
        for array_name, fields in arrays:
            rows = _array(case[array_name], f"cases[{case_index}].{array_name}")
            prior: tuple[int, str] | None = None
            for row_index, value in enumerate(rows):
                gold = _closed(
                    value,
                    fields,
                    f"cases[{case_index}].{array_name}[{row_index}]",
                )
                gold_id, variant, prior = self._validate_gold_identity(
                    case_index,
                    array_name,
                    row_index,
                    gold,
                    variant_order,
                    prior,
                    all_gold_ids,
                )
                self._validate_gold_row(
                    case_index,
                    case_id,
                    array_name,
                    gold_id,
                    variant,
                    gold,
                    obligations,
                    evidence,
                    candidates,
                )
        self._validate_expected_packet_uniqueness()
        self._validate_readiness(case_id, case, obligations)
        self._validate_finding_evidence(
            case_id,
            obligations,
            evidence,
            candidates,
        )
        self._validate_controls(case_id, variants)

    @staticmethod
    def _validate_gold_identity(
        case_index: int,
        array_name: str,
        row_index: int,
        gold: dict[str, Any],
        variant_order: dict[str, int],
        prior: tuple[int, str] | None,
        all_gold_ids: set[str],
    ) -> tuple[str, str, tuple[int, str]]:
        gold_id = _nonblank(
            gold["gold_id"],
            f"cases[{case_index}].{array_name}[{row_index}].gold_id",
        )
        variant = _nonblank(
            gold["variant_id"],
            f"cases[{case_index}].{array_name}[{row_index}].variant_id",
        )
        if variant not in variant_order:
            raise SemanticEvalContractError(
                f"cases[{case_index}].{array_name}[{row_index}] has unknown variant"
            )
        order_key = (variant_order[variant], gold_id)
        if prior is not None and order_key <= prior:
            raise SemanticEvalContractError(
                f"cases[{case_index}].{array_name} is not unique and ordered"
            )
        if gold_id in all_gold_ids:
            raise SemanticEvalContractError(
                f"cases[{case_index}] repeats gold_id {gold_id!r}"
            )
        all_gold_ids.add(gold_id)
        return gold_id, variant, order_key

    def _validate_gold_row(
        self,
        case_index: int,
        case_id: str,
        array_name: str,
        gold_id: str,
        variant: str,
        gold: dict[str, Any],
        obligations: dict[tuple[str, str], dict[str, Any]],
        evidence: dict[str, dict[str, Any]],
        candidates: dict[str, dict[str, Any]],
    ) -> None:
        if array_name == "gold_obligations":
            self._validate_gold_obligation(
                case_index,
                gold_id,
                variant,
                gold,
                obligations,
            )
        elif array_name == "gold_evidence":
            self._validate_gold_evidence(
                case_id,
                gold_id,
                variant,
                gold,
                obligations,
                evidence,
            )
        elif array_name == "gold_candidates":
            self._validate_gold_candidate(
                case_id,
                gold_id,
                variant,
                gold,
                obligations,
                candidates,
            )
        else:
            self._validate_expected_finding(
                case_id,
                gold_id,
                variant,
                gold,
                obligations,
            )

    @staticmethod
    def _validate_gold_obligation(
        case_index: int,
        gold_id: str,
        variant: str,
        gold: dict[str, Any],
        obligations: dict[tuple[str, str], dict[str, Any]],
    ) -> None:
        obligation_id = _nonblank(
            gold["obligation_id"],
            f"obligation {gold_id}.obligation_id",
        )
        packet_id = _nonblank(gold["packet_id"], f"obligation {gold_id}.packet_id")
        if packet_id != obligation_id:
            raise SemanticEvalContractError(
                f"obligation {gold_id} packet_id must equal obligation_id"
            )
        _enum(
            gold["intent_state"], _INTENT_STATES, f"obligation {gold_id}.intent_state"
        )
        _enum(
            gold["alignment_state"],
            _ALIGNMENT_STATES,
            f"obligation {gold_id}.alignment_state",
        )
        _enum(
            gold["disposition"],
            _DISPOSITIONS,
            f"obligation {gold_id}.disposition",
        )
        _enum(
            gold["obligation_rung"],
            _RUNGS,
            f"obligation {gold_id}.obligation_rung",
        )
        _enum(
            gold["gate_state"],
            _GATE_STATES,
            f"obligation {gold_id}.gate_state",
        )
        key = (variant, obligation_id)
        if key in obligations:
            raise SemanticEvalContractError(
                f"cases[{case_index}] repeats obligation identity"
            )
        obligations[key] = gold

    def _validate_gold_evidence(
        self,
        case_id: str,
        gold_id: str,
        variant: str,
        gold: dict[str, Any],
        obligations: dict[tuple[str, str], dict[str, Any]],
        evidence: dict[str, dict[str, Any]],
    ) -> None:
        obligation_id = _nonblank(
            gold["obligation_id"],
            f"evidence {gold_id}.obligation_id",
        )
        if (variant, obligation_id) not in obligations:
            raise SemanticEvalContractError(
                f"evidence {gold_id} has unknown obligation"
            )
        _enum(gold["source_role"], _SOURCE_ROLES, f"evidence {gold_id}.source_role")
        _enum(
            gold["reciprocity_state"],
            _RECIPROCITY_STATES,
            f"evidence {gold_id}.reciprocity_state",
        )
        _validate_span_record(
            gold,
            self.fixtures[(case_id, variant)],
            f"evidence {gold_id}",
        )
        evidence[gold_id] = gold

    def _validate_gold_candidate(
        self,
        case_id: str,
        gold_id: str,
        variant: str,
        gold: dict[str, Any],
        obligations: dict[tuple[str, str], dict[str, Any]],
        candidates: dict[str, dict[str, Any]],
    ) -> None:
        obligation_id = _nonblank(
            gold["obligation_id"],
            f"candidate {gold_id}.obligation_id",
        )
        if (variant, obligation_id) not in obligations:
            raise SemanticEvalContractError(
                f"candidate {gold_id} has unknown obligation"
            )
        kind = _enum(
            gold["candidate_kind"],
            _CANDIDATE_KINDS,
            f"candidate {gold_id}.candidate_kind",
        )
        state = _enum(
            gold["trace_state"],
            _TRACE_STATES,
            f"candidate {gold_id}.trace_state",
        )
        if kind == "report_issue" and state not in {
            "partially_declared",
            "conflicted",
        }:
            raise SemanticEvalContractError(
                f"candidate {gold_id} has impossible report_issue trace state"
            )
        candidate_path, locator, _start, _end = _validate_span_record(
            gold,
            self.fixtures[(case_id, variant)],
            f"candidate {gold_id}",
        )
        expected_id = _candidate_id(kind=kind, path=candidate_path, locator=locator)
        if gold["candidate_id"] != expected_id:
            raise SemanticEvalContractError(
                f"candidate {gold_id}.candidate_id does not recompute"
            )
        candidates[gold_id] = gold

    def _validate_expected_finding(
        self,
        case_id: str,
        gold_id: str,
        variant: str,
        gold: dict[str, Any],
        obligations: dict[tuple[str, str], dict[str, Any]],
    ) -> None:
        packet_id = _nonblank(gold["packet_id"], f"finding {gold_id}.packet_id")
        obligation_matches = [
            item
            for (candidate_variant, _obligation), item in obligations.items()
            if candidate_variant == variant and item["packet_id"] == packet_id
        ]
        if len(obligation_matches) != 1:
            raise SemanticEvalContractError(
                f"finding {gold_id} has unknown or ambiguous packet"
            )
        classification = _nonblank(
            gold["classification"],
            f"finding {gold_id}.classification",
        )
        code = _nonblank(gold["code"], f"finding {gold_id}.code")
        if _CODE_BY_CLASSIFICATION.get(classification) != code:
            raise SemanticEvalContractError(
                f"finding {gold_id} code/classification mismatch"
            )
        self.expected_by_case_variant.setdefault((case_id, variant), []).append(gold)
        self.finding_by_gold[(case_id, variant, gold_id)] = gold

    def _validate_expected_packet_uniqueness(self) -> None:
        for key, rows in self.expected_by_case_variant.items():
            packet_ids = [cast(str, finding["packet_id"]) for finding in rows]
            if len(packet_ids) != len(set(packet_ids)):
                raise SemanticEvalContractError(
                    f"{key[0]}/{key[1]} has multiple expected findings for one packet"
                )

    def _validate_readiness(
        self,
        case_id: str,
        case: dict[str, Any],
        obligations: dict[tuple[str, str], dict[str, Any]],
    ) -> None:
        for (variant, obligation_id), obligation in obligations.items():
            if cast(str, obligation["gate_state"]) == "executable" and (
                obligation["intent_state"] != "identified"
                or obligation["alignment_state"] != "complete"
                or obligation["disposition"] != "evaluate"
                or obligation["obligation_rung"] != "active"
            ):
                raise SemanticEvalContractError(
                    f"{case_id}/{variant}/{obligation_id} has inconsistent executable readiness"
                )
            if (
                cast(bool, case["critical"])
                and self.mode == "enforce"
                and obligation["disposition"] == "skipped"
            ):
                raise SemanticEvalContractError(
                    "skip is invalid on a qualifying critical unit"
                )

    def _validate_finding_evidence(
        self,
        case_id: str,
        obligations: dict[tuple[str, str], dict[str, Any]],
        evidence: dict[str, dict[str, Any]],
        candidates: dict[str, dict[str, Any]],
    ) -> None:
        for (variant, _obligation_id), obligation in obligations.items():
            packet_id = cast(str, obligation["packet_id"])
            for finding in self.expected_by_case_variant.get((case_id, variant), []):
                if finding["packet_id"] != packet_id:
                    continue
                declared = _ordered_unique_strings(
                    finding["required_declared_evidence_gold_ids"],
                    f"finding {finding['gold_id']}.required_declared_evidence_gold_ids",
                    require_sorted=True,
                )
                counter = _ordered_unique_strings(
                    finding["required_counterevidence_gold_ids"],
                    f"finding {finding['gold_id']}.required_counterevidence_gold_ids",
                    require_sorted=True,
                )
                self._validate_finding_references(
                    finding,
                    variant,
                    obligation,
                    declared,
                    counter,
                    evidence,
                    candidates,
                )

    @staticmethod
    def _validate_finding_references(
        finding: dict[str, Any],
        variant: str,
        obligation: dict[str, Any],
        declared: tuple[str, ...],
        counter: tuple[str, ...],
        evidence: dict[str, dict[str, Any]],
        candidates: dict[str, dict[str, Any]],
    ) -> None:
        for referenced in declared:
            item = evidence.get(referenced)
            if (
                item is None
                or item["variant_id"] != variant
                or item["obligation_id"] != obligation["obligation_id"]
            ):
                raise SemanticEvalContractError(
                    f"finding {finding['gold_id']} has cross-variant or cross-obligation declared evidence"
                )
        for referenced in counter:
            item = candidates.get(referenced)
            if (
                item is None
                or item["variant_id"] != variant
                or item["obligation_id"] != obligation["obligation_id"]
            ):
                raise SemanticEvalContractError(
                    f"finding {finding['gold_id']} has cross-variant or cross-obligation counterevidence"
                )

    def _validate_controls(self, case_id: str, variants: list[str]) -> None:
        for variant in variants:
            tag_set = set(self.fixtures[(case_id, variant)].control_tags)
            findings = self.expected_by_case_variant.get((case_id, variant), [])
            if tag_set & _NEGATIVE_CONTROL_TAGS and findings:
                raise SemanticEvalContractError(
                    f"{case_id}/{variant} false-positive control must be negative"
                )
            if tag_set & _POSITIVE_CONTROL_TAGS and not findings:
                raise SemanticEvalContractError(
                    f"{case_id}/{variant} positive control requires an expected finding"
                )

    def _validate_critical_vacuous_cases(self) -> None:
        for case_id in self.critical_vacuous:
            variants = [key for key in self.fixtures if key[0] == case_id]
            if not any(
                "valid_vacuous_trace" in self.fixtures[key].control_tags
                and any(
                    finding["code"] == "SEMANTIC_MISSING_TRACE"
                    for finding in self.expected_by_case_variant.get(key, [])
                )
                for key in variants
            ):
                raise SemanticEvalContractError(
                    f"critical vacuous case {case_id!r} has no matching missing-trace finding"
                )

    def _validate_historical_units(self) -> None:
        historical = _array(
            self.row["reviewed_historical_units"],
            "reviewed_historical_units",
        )
        prior_unit: str | None = None
        source_refs: set[str] = set()
        for index, value in enumerate(historical):
            unit = _closed(
                value,
                _HISTORICAL_FIELDS,
                f"reviewed_historical_units[{index}]",
            )
            unit_id = _nonblank(
                unit["unit_id"],
                f"reviewed_historical_units[{index}].unit_id",
            )
            if prior_unit is not None and unit_id <= prior_unit:
                raise SemanticEvalContractError(
                    "reviewed historical unit IDs must be unique and ordered"
                )
            prior_unit = unit_id
            self._validate_historical_unit(index, unit_id, unit, source_refs)

    def _validate_historical_unit(
        self,
        index: int,
        unit_id: str,
        unit: dict[str, Any],
        source_refs: set[str],
    ) -> None:
        case_id = _nonblank(
            unit["case_id"],
            f"reviewed_historical_units[{index}].case_id",
        )
        variant_id = _nonblank(
            unit["variant_id"],
            f"reviewed_historical_units[{index}].variant_id",
        )
        finding_id = _nonblank(
            unit["expected_finding_gold_id"],
            f"reviewed_historical_units[{index}].expected_finding_gold_id",
        )
        if (case_id, variant_id, finding_id) not in self.finding_by_gold:
            raise SemanticEvalContractError(
                f"reviewed historical unit {unit_id!r} has no expected finding"
            )
        source_ref = _nonblank(
            unit["source_reference"],
            f"reviewed_historical_units[{index}].source_reference",
        )
        _nonblank(
            unit["review_reference"],
            f"reviewed_historical_units[{index}].review_reference",
        )
        if source_ref in source_refs:
            raise SemanticEvalContractError(
                "reviewed historical source references must be unique"
            )
        source_refs.add(source_ref)
        target = (case_id, variant_id, finding_id)
        if target in self.historical_targets:
            raise SemanticEvalContractError(
                "reviewed historical target tuples must be unique"
            )
        self.historical_targets.add(target)
        if (
            "historical_misalignment"
            not in self.fixtures[(case_id, variant_id)].control_tags
        ):
            raise SemanticEvalContractError(
                f"reviewed historical unit {unit_id!r} lacks its control tag"
            )

    def _validate_enforce_requirements(self) -> None:
        if self.mode != "enforce":
            return
        observed_tags = {
            tag for fixture in self.fixtures.values() for tag in fixture.control_tags
        }
        if observed_tags != set(_CONTROL_TAGS):
            raise SemanticEvalContractError(
                "enforce corpus must contain every control tag"
            )
        if not self.critical or not self.critical_vacuous:
            raise SemanticEvalContractError(
                "enforce corpus requires critical and vacuous-critical cases"
            )
        if len(self.historical_targets) < 20:
            raise SemanticEvalContractError(
                "enforce corpus requires 20 reviewed historical targets"
            )


def load_semantic_eval_corpus(
    path: Path,
    *,
    mode: Literal["report", "enforce"],
    maximum_manifest_bytes: int = _DEFAULT_MANIFEST_BYTES,
    maximum_tree_manifest_bytes: int = _DEFAULT_TREE_MANIFEST_BYTES,
) -> SemanticEvalCorpus:
    """Load one closed schema-3 corpus and freeze all addressed fixture bytes."""

    if mode not in ("report", "enforce"):
        raise SemanticEvalContractError("semantic eval corpus mode is invalid")
    manifest_path = path.resolve()
    raw = _read_regular(
        manifest_path,
        maximum_bytes=maximum_manifest_bytes,
        name="semantic eval corpus manifest",
    )
    manifest, canonical = _parse_canonical_object(
        raw,
        name="semantic eval corpus manifest",
        final_lf="optional",
    )
    row = _closed(manifest, _MANIFEST_FIELDS, "semantic eval corpus manifest")
    if row["schema_version"] != 3:
        raise SemanticEvalContractError("semantic eval corpus schema_version must be 3")
    corpus_id = _nonblank(row["corpus_id"], "semantic eval corpus.corpus_id")
    return _SemanticEvalCorpusValidator(
        manifest_path=manifest_path,
        canonical=canonical,
        row=row,
        corpus_id=corpus_id,
        corpus_sha256="sha256:" + hashlib.sha256(canonical).hexdigest(),
        mode=mode,
        maximum_tree_manifest_bytes=maximum_tree_manifest_bytes,
    ).validate()


_REPORT_FIELDS = frozenset(
    {
        "schema_version",
        "artifact",
        "identity",
        "analysis_attempts",
        "events",
        "metrics",
        "by_code",
        "operational",
        "qualification",
    }
)
_IDENTITY_FIELDS = frozenset(
    {
        "corpus_sha256",
        "snapshot_algorithm_version",
        "obligation_algorithm_version",
        "discovery_algorithm_version",
        "packet_contract_version",
        "normalization_version",
        "analysis_composition",
        "analysis_composition_sha256",
        "verify_composition",
        "verify_composition_sha256",
        "composition_sha256",
        "trials",
        "eval_config",
    }
)
_PROVIDER_FIELDS = frozenset(
    {
        "backend_id",
        "plugin_id",
        "model_id",
        "model_revision",
        "adapter_id",
        "adapter_version",
        "llm_distribution_version",
        "plugin_distribution_name",
        "plugin_distribution_version",
    }
)
_REQUEST_FIELDS = frozenset(
    {"json_mode", "temperature", "seed", "max_tokens", "reasoning_effort"}
)
_PROMPT_FIELDS = frozenset({"id", "version", "sha256"})
_ANALYSIS_COMPOSITION_FIELDS = frozenset(
    {
        "analysis_contract_version",
        "provider",
        "request",
        "prompts",
        "base_search_epoch",
    }
)
_VERIFY_COMPOSITION_FIELDS = frozenset(
    {
        "verify_contract_version",
        "prompt",
        "provider",
        "request",
        "search_epochs",
        "required_verdicts",
        "minimum_support_score",
        "indeterminate",
    }
)
_EVAL_CONFIG_FIELDS = frozenset(
    {
        "trials",
        "interval_method",
        "confidence_level",
        "minimum_positive_units",
        "minimum_negative_units",
        "minimum_evidence_sufficiency_rate",
        "minimum_conditional_precision",
        "minimum_conditional_recall",
        "minimum_end_to_end_recall",
        "minimum_recall_lower_bound",
        "maximum_false_positive_rate",
        "maximum_false_positive_upper_bound",
        "maximum_indeterminate_rate",
        "maximum_uncached_flip_rate",
        "require_all_critical",
    }
)
_ANALYSIS_ATTEMPT_FIELDS = frozenset(
    {
        "trial_index",
        "case_id",
        "variant_id",
        "packet_id",
        "packet_hash",
        "base_search_epoch",
        "effective_search_epoch",
        "analysis_key",
        "primary_result",
        "replay_result",
        "primary_sha256",
        "replay_sha256",
        "primary_cache_object_sha256",
        "replay_cache_object_sha256",
        "primary_raw_response_sha256",
        "replay_raw_response_sha256",
        "primary_provenance",
        "replay_provenance",
    }
)
_ANALYSIS_RESULT_FIELDS = frozenset(
    {
        "schema_version",
        "packet_id",
        "kind",
        "packet_hash",
        "analysis_key",
        "classification",
        "confidence",
        "rationale",
        "summary",
        "evidence",
        "verification_state",
    }
)
_EVENT_FIELDS = frozenset(
    {
        "trial_index",
        "case_id",
        "variant_id",
        "obligation_id",
        "packet_id",
        "claim_hash",
        "code",
        "classification",
        "claim_evidence",
        "primary_present",
        "replay_present",
        "primary_results",
        "replay_results",
        "primary_aggregate_state",
        "primary_context",
        "replay_aggregate_state",
        "replay_context",
        "primary_sha256",
        "replay_sha256",
        "comparison_signature_sha256",
    }
)
_EVENT_RESULT_FIELDS = frozenset(
    {
        "verify_key",
        "base_search_epoch",
        "effective_search_epoch",
        "result",
        "cache_object_sha256",
        "raw_response_sha256",
        "provenance",
    }
)
_VERIFICATION_RESULT_FIELDS = frozenset(
    {
        "schema_version",
        "packet_id",
        "packet_hash",
        "claim_hash",
        "verifier_packet_hash",
        "verify_key",
        "verdict",
        "support_score",
        "summary",
        "evidence",
    }
)
_CLAIM_EVIDENCE_FIELDS = frozenset(
    {"role", "path", "start_line", "end_line", "excerpt_sha256"}
)
_CANONICAL_EVIDENCE_FIELDS = frozenset(
    {"role", "path", "start_line", "end_line", "excerpt", "excerpt_sha256"}
)
_PROVENANCE_FIELDS = frozenset(
    {
        "adapter_id",
        "adapter_version",
        "plugin_version",
        "model_class",
        "provider_model_id",
        "provider_model_revision",
        "response_id",
        "input_tokens",
        "output_tokens",
    }
)
_METRIC_FIELDS = frozenset(
    {
        "positive_unit_count",
        "negative_unit_count",
        "evidence_sufficiency_rate",
        "conditional_precision",
        "conditional_recall",
        "end_to_end_recall",
        "recall_lower_bound",
        "false_positive_rate",
        "false_positive_upper_bound",
        "indeterminate_rate",
        "uncached_flip_rate",
        "false_positive_count",
        "all_critical_passed",
    }
)
_BY_CODE_FIELDS = frozenset({"code", "metrics"})
_OPERATIONAL_FIELDS = frozenset(
    {
        "cache_hits",
        "cache_misses",
        "provider_calls",
        "analyzer_primary_cache_hits",
        "analyzer_primary_cache_misses",
        "analyzer_primary_provider_calls",
        "analyzer_replay_cache_hits",
        "analyzer_replay_cache_misses",
        "analyzer_replay_provider_calls",
        "verifier_primary_cache_hits",
        "verifier_primary_cache_misses",
        "verifier_primary_provider_calls",
        "verifier_replay_cache_hits",
        "verifier_replay_cache_misses",
        "verifier_replay_provider_calls",
        "analysis_cost",
        "verify_cost",
        "total_estimated_cost_microusd",
    }
)
_COST_FIELDS = frozenset({"estimated_cost_microusd", "cost_rate_source"})
_QUALIFICATION_FIELDS = frozenset(
    {
        "mode",
        "positive_unit_count",
        "negative_unit_count",
        "checks",
        "passed",
        "failure_reasons",
    }
)
_CHECK_FIELDS = frozenset(
    {"kind", "name", "comparator", "threshold", "observed", "passed"}
)
_CHECK_NAMES = (
    "minimum_positive_units",
    "minimum_negative_units",
    "minimum_evidence_sufficiency_rate",
    "minimum_conditional_precision",
    "minimum_conditional_recall",
    "minimum_end_to_end_recall",
    "minimum_recall_lower_bound",
    "maximum_false_positive_rate",
    "maximum_false_positive_upper_bound",
    "maximum_indeterminate_rate",
    "maximum_uncached_flip_rate",
    "require_all_critical",
)


@dataclass(frozen=True, slots=True)
class SemanticEvalReport:
    """Validated schema-3 report with its external canonical-object digest."""

    path: Path | None = field(repr=False, compare=False)
    report_sha256: str
    passed: bool
    identity: Mapping[str, Any]
    _canonical: bytes = field(repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        value = json.loads(self._canonical)
        assert isinstance(value, dict)
        return cast(dict[str, Any], value)

    def to_json_bytes(self) -> bytes:
        return self._canonical + b"\n"


def _validate_provider(value: object, name: str) -> dict[str, Any]:
    from backstitch.semantic_identity import ProviderIdentity

    row = _closed(value, _PROVIDER_FIELDS, name)
    try:
        provider = ProviderIdentity(
            backend_id=_nonblank(row["backend_id"], f"{name}.backend_id"),
            plugin_id=_nonblank(row["plugin_id"], f"{name}.plugin_id"),
            model_id=_nonblank(row["model_id"], f"{name}.model_id"),
            model_revision=_nonblank(row["model_revision"], f"{name}.model_revision"),
            adapter_id=_nonblank(row["adapter_id"], f"{name}.adapter_id"),
            adapter_version=_integer(
                row["adapter_version"], f"{name}.adapter_version", minimum=1
            ),
            llm_distribution_version=_nonblank(
                row["llm_distribution_version"],
                f"{name}.llm_distribution_version",
            ),
            plugin_distribution_name=cast(str, row["plugin_distribution_name"]),
            plugin_distribution_version=cast(str, row["plugin_distribution_version"]),
        )
    except ValueError as exc:
        raise SemanticEvalContractError(f"{name} is invalid: {exc}") from exc
    return {
        "backend_id": provider.backend_id,
        "plugin_id": provider.plugin_id,
        "model_id": provider.model_id,
        "model_revision": provider.model_revision,
        "adapter_id": provider.adapter_id,
        "adapter_version": provider.adapter_version,
        "llm_distribution_version": provider.llm_distribution_version,
        "plugin_distribution_name": provider.plugin_distribution_name,
        "plugin_distribution_version": provider.plugin_distribution_version,
    }


def _validate_request(value: object, name: str) -> dict[str, Any]:
    from backstitch.semantic_identity import RequestIdentity, request_identity_dict

    if not isinstance(value, dict) or not set(value) <= _REQUEST_FIELDS:
        raise SemanticEvalContractError(f"{name} has invalid closed shape")
    row = value
    try:
        request = RequestIdentity(**row)
    except (TypeError, ValueError) as exc:
        raise SemanticEvalContractError(f"{name} is invalid: {exc}") from exc
    normalized = request_identity_dict(request)
    if row != normalized:
        raise SemanticEvalContractError(f"{name} is not canonical")
    return normalized


def _validate_eval_config(value: object) -> dict[str, Any]:
    row = _closed(value, _EVAL_CONFIG_FIELDS, "report.identity.eval_config")
    _integer(row["trials"], "eval_config.trials", minimum=1)
    if row["interval_method"] != "wilson":
        raise SemanticEvalContractError("eval_config.interval_method must be wilson")
    confidence = _finite(row["confidence_level"], "eval_config.confidence_level")
    if not 0 < confidence < 1:
        raise SemanticEvalContractError(
            "eval_config.confidence_level must be between zero and one"
        )
    for name in ("minimum_positive_units", "minimum_negative_units"):
        _integer(row[name], f"eval_config.{name}")
    for name in _CHECK_NAMES[2:-1]:
        rate = _finite(row[name], f"eval_config.{name}")
        if not 0 <= rate <= 1:
            raise SemanticEvalContractError(f"eval_config.{name} must be a rate")
    _boolean(row["require_all_critical"], "eval_config.require_all_critical")
    return row


def _validate_identity(value: object, corpus: SemanticEvalCorpus) -> dict[str, Any]:  # noqa: C901 approved [SC-17.1] RUFF-SUP-096 exception
    from backstitch.obligation_runtime import ALGORITHMS
    from backstitch.semantic_identity import (
        ProviderIdentity,
        RequestIdentity,
        build_composition_identity,
    )

    row = _closed(value, _IDENTITY_FIELDS, "report.identity")
    if row["corpus_sha256"] != corpus.corpus_sha256:
        raise SemanticEvalContractError("report identity corpus digest does not match")
    versions = {
        "snapshot_algorithm_version": ALGORITHMS.snapshot_algorithm_version,
        "obligation_algorithm_version": ALGORITHMS.obligation_algorithm_version,
        "discovery_algorithm_version": ALGORITHMS.discovery_algorithm_version,
        "packet_contract_version": ALGORITHMS.packet_contract_version,
        "normalization_version": ALGORITHMS.normalization_version,
    }
    for field_name, current in versions.items():
        observed = _integer(row[field_name], f"report.identity.{field_name}", minimum=1)
        if observed != current:
            raise SemanticEvalContractError(
                f"report identity {field_name} is not current"
            )
    analysis = _closed(
        row["analysis_composition"],
        _ANALYSIS_COMPOSITION_FIELDS,
        "report.identity.analysis_composition",
    )
    verify = _closed(
        row["verify_composition"],
        _VERIFY_COMPOSITION_FIELDS,
        "report.identity.verify_composition",
    )
    analysis_provider = _validate_provider(
        analysis["provider"], "report.identity.analysis_composition.provider"
    )
    analysis_request = _validate_request(
        analysis["request"], "report.identity.analysis_composition.request"
    )
    verify_provider = _validate_provider(
        verify["provider"], "report.identity.verify_composition.provider"
    )
    verify_request = _validate_request(
        verify["request"], "report.identity.verify_composition.request"
    )
    prompts = _array(
        analysis["prompts"], "report.identity.analysis_composition.prompts"
    )
    if len(prompts) != 2:
        raise SemanticEvalContractError(
            "analysis composition requires section and invariant prompts"
        )
    for index, kind in enumerate(("section", "invariant")):
        prompt = _closed(
            prompts[index], _PROMPT_FIELDS | {"kind"}, f"analysis prompt {index}"
        )
        if prompt["kind"] != kind:
            raise SemanticEvalContractError("analysis prompts are out of order")
        _nonblank(prompt["id"], f"analysis prompt {index}.id")
        _integer(prompt["version"], f"analysis prompt {index}.version", minimum=1)
        _digest(prompt["sha256"], f"analysis prompt {index}.sha256")
    prompt = _closed(verify["prompt"], _PROMPT_FIELDS, "verification prompt")
    _nonblank(prompt["id"], "verification prompt.id")
    _integer(prompt["version"], "verification prompt.version", minimum=1)
    _digest(prompt["sha256"], "verification prompt.sha256")
    analysis_contract = _integer(
        analysis["analysis_contract_version"],
        "report.identity.analysis_composition.analysis_contract_version",
        minimum=1,
    )
    base_epoch = _nonblank(
        analysis["base_search_epoch"],
        "report.identity.analysis_composition.base_search_epoch",
    )
    verify_contract = _integer(
        verify["verify_contract_version"],
        "report.identity.verify_composition.verify_contract_version",
        minimum=1,
    )
    epochs = _ordered_unique_strings(
        verify["search_epochs"],
        "report.identity.verify_composition.search_epochs",
        allow_empty=False,
    )
    required = _integer(
        verify["required_verdicts"],
        "report.identity.verify_composition.required_verdicts",
        minimum=1,
    )
    if required != len(epochs):
        raise SemanticEvalContractError(
            "required_verdicts must equal search epoch count"
        )
    support = _finite(
        verify["minimum_support_score"],
        "report.identity.verify_composition.minimum_support_score",
    )
    if not 0 <= support <= 1:
        raise SemanticEvalContractError(
            "minimum_support_score must be from zero through one"
        )
    indeterminate = _enum(
        verify["indeterminate"],
        ("allow", "report"),
        "verification indeterminate",
    )
    try:
        rebuilt = build_composition_identity(
            ProviderIdentity(**analysis_provider),
            RequestIdentity(**analysis_request),
            analysis_search_epoch=base_epoch,
            verify_provider=ProviderIdentity(**verify_provider),
            verify_request=RequestIdentity(**verify_request),
            verify_search_epochs=epochs,
            required_verdicts=required,
            minimum_support_score=support,
            indeterminate=indeterminate,
            analysis_contract_version=analysis_contract,
        )
    except ValueError as exc:
        raise SemanticEvalContractError(
            f"report composition is invalid: {exc}"
        ) from exc
    if verify_contract != rebuilt.verify_composition["verify_contract_version"]:
        raise SemanticEvalContractError("verification contract version is not current")
    if canonical_json_bytes(analysis) != canonical_json_bytes(
        rebuilt.analysis_composition
    ):
        raise SemanticEvalContractError(
            "analysis composition differs from installed identity"
        )
    if canonical_json_bytes(verify) != canonical_json_bytes(rebuilt.verify_composition):
        raise SemanticEvalContractError(
            "verify composition differs from installed identity"
        )
    expected_hashes = (
        rebuilt.analysis_composition_sha256,
        rebuilt.verify_composition_sha256,
        rebuilt.composition_sha256,
    )
    observed_hashes = (
        _digest(row["analysis_composition_sha256"], "analysis_composition_sha256"),
        _digest(row["verify_composition_sha256"], "verify_composition_sha256"),
        _digest(row["composition_sha256"], "composition_sha256"),
    )
    if observed_hashes != expected_hashes:
        raise SemanticEvalContractError("report composition hashes do not recompute")
    config = _validate_eval_config(row["eval_config"])
    trials = _integer(row["trials"], "report.identity.trials", minimum=1)
    if trials != config["trials"]:
        raise SemanticEvalContractError(
            "identity.trials differs from eval_config.trials"
        )
    return row


def _validate_provenance(value: object, name: str) -> dict[str, Any]:
    row = _closed(value, _PROVENANCE_FIELDS, name)
    _nonblank(row["adapter_id"], f"{name}.adapter_id")
    _integer(row["adapter_version"], f"{name}.adapter_version", minimum=1)
    for field_name in (
        "plugin_version",
        "model_class",
        "provider_model_id",
        "provider_model_revision",
        "response_id",
    ):
        item = row[field_name]
        if item is not None:
            _nonblank(item, f"{name}.{field_name}")
    for field_name in ("input_tokens", "output_tokens"):
        item = row[field_name]
        if item is not None:
            _integer(item, f"{name}.{field_name}")
    return row


def _validate_canonical_evidence(value: object, name: str) -> tuple[Any, ...]:
    row = _closed(value, _CANONICAL_EVIDENCE_FIELDS, name)
    role = _enum(
        row["role"],
        ("requirement", "implementation", "test", "counterevidence"),
        f"{name}.role",
    )
    path = _relative_path(row["path"], f"{name}.path")
    start = _integer(row["start_line"], f"{name}.start_line", minimum=1)
    end = _integer(row["end_line"], f"{name}.end_line", minimum=1)
    if end < start:
        raise SemanticEvalContractError(f"{name} has a reversed span")
    excerpt = row["excerpt"]
    if not isinstance(excerpt, str):
        raise SemanticEvalContractError(f"{name}.excerpt must be a string")
    expected = hashlib.sha256(excerpt.encode()).hexdigest()
    if _digest(row["excerpt_sha256"], f"{name}.excerpt_sha256") != expected:
        raise SemanticEvalContractError(f"{name}.excerpt_sha256 does not recompute")
    return role, path, start, end, expected


def _validate_analysis_result(
    value: object,
    *,
    packet_id: str,
    packet_hash: str,
    analysis_key: str,
    name: str,
) -> dict[str, Any]:
    row = _closed(value, _ANALYSIS_RESULT_FIELDS, name)
    if row["schema_version"] != 2:
        raise SemanticEvalContractError(f"{name}.schema_version must be 2")
    if (
        row["packet_id"] != packet_id
        or row["packet_hash"] != packet_hash
        or row["analysis_key"] != analysis_key
    ):
        raise SemanticEvalContractError(f"{name} identity differs from its attempt")
    kind = _enum(row["kind"], ("section", "invariant"), f"{name}.kind")
    classification = _nonblank(row["classification"], f"{name}.classification")
    allowed = (
        {
            "ok",
            "confirmed_mismatch",
            "probable_mismatch",
            "missing_trace",
            "ambiguous",
        }
        if kind == "section"
        else {
            "ok",
            "weak_binding",
            "confirmed_mismatch",
            "probable_mismatch",
            "ambiguous",
        }
    )
    if classification not in allowed:
        raise SemanticEvalContractError(
            f"{name}.classification is invalid for its kind"
        )
    confidence = row["confidence"]
    if (
        confidence is not None
        and not 0 <= _finite(confidence, f"{name}.confidence") <= 1
    ):
        raise SemanticEvalContractError(f"{name}.confidence must be null or a rate")
    if not isinstance(row["rationale"], str):
        raise SemanticEvalContractError(f"{name}.rationale must be a string")
    _nonblank(row["summary"], f"{name}.summary")
    if row["verification_state"] != "evidence_bound":
        raise SemanticEvalContractError(
            f"{name}.verification_state must be evidence_bound"
        )
    evidence_rows = _array(row["evidence"], f"{name}.evidence")
    identities = [
        _validate_canonical_evidence(item, f"{name}.evidence[{index}]")
        for index, item in enumerate(evidence_rows)
    ]
    if identities != sorted(set(identities)):
        raise SemanticEvalContractError(f"{name}.evidence must be unique and ordered")
    roles = {cast(str, item["role"]) for item in evidence_rows}
    required_roles: set[str]
    if kind == "section":
        required_roles = (
            set()
            if classification == "ok"
            else {"requirement"}
            if classification in {"missing_trace", "ambiguous"}
            else {"requirement", "implementation"}
        )
    else:
        required_roles = (
            {"test"}
            if classification == "ok"
            else {"requirement"}
            if classification == "ambiguous"
            else {"requirement", "implementation"}
        )
    if not required_roles <= roles:
        raise SemanticEvalContractError(
            f"{name}.evidence lacks required roles for its classification"
        )
    return row


def _validate_analysis_attempt(  # noqa: C901 approved [SC-17.1] RUFF-SUP-093 exception
    value: object,
    *,
    corpus: SemanticEvalCorpus,
    identity: dict[str, Any],
    index: int,
) -> tuple[dict[str, Any], str]:
    from dataclasses import asdict

    from backstitch.semantic_packets import prompt_descriptor

    name = f"report.analysis_attempts[{index}]"
    row = _closed(value, _ANALYSIS_ATTEMPT_FIELDS, name)
    trial = _integer(row["trial_index"], f"{name}.trial_index")
    if trial >= cast(int, identity["trials"]):
        raise SemanticEvalContractError(
            f"{name}.trial_index is outside configured trials"
        )
    case_id = _nonblank(row["case_id"], f"{name}.case_id")
    variant_id = _nonblank(row["variant_id"], f"{name}.variant_id")
    corpus.fixture(case_id, variant_id)
    packet_id = _nonblank(row["packet_id"], f"{name}.packet_id")
    packet_hash = _digest(row["packet_hash"], f"{name}.packet_hash")
    analysis = cast(dict[str, Any], identity["analysis_composition"])
    base = _nonblank(row["base_search_epoch"], f"{name}.base_search_epoch")
    if base != analysis["base_search_epoch"]:
        raise SemanticEvalContractError(
            f"{name}.base_search_epoch differs from composition"
        )
    effective = _nonblank(
        row["effective_search_epoch"], f"{name}.effective_search_epoch"
    )
    if effective != derive_eval_search_epoch(
        "eval-analyze", base, corpus.corpus_sha256, trial
    ):
        raise SemanticEvalContractError(
            f"{name}.effective_search_epoch does not recompute"
        )
    primary_value = row["primary_result"]
    kind = primary_value.get("kind") if isinstance(primary_value, dict) else None
    if kind not in {"section", "invariant"}:
        raise SemanticEvalContractError(f"{name}.primary_result.kind is invalid")
    contract = {
        "analysis_contract_version": analysis["analysis_contract_version"],
        "packet_hash": packet_hash,
        "prompt": asdict(
            prompt_descriptor(cast(Literal["section", "invariant"], kind))
        ),
        "provider": analysis["provider"],
        "request": analysis["request"],
        "search_epoch": effective,
    }
    analysis_key = hashlib.sha256(canonical_json_bytes(contract)).hexdigest()
    if row["analysis_key"] != analysis_key:
        raise SemanticEvalContractError(f"{name}.analysis_key does not recompute")
    primary = _validate_analysis_result(
        row["primary_result"],
        packet_id=packet_id,
        packet_hash=packet_hash,
        analysis_key=analysis_key,
        name=f"{name}.primary_result",
    )
    replay = _validate_analysis_result(
        row["replay_result"],
        packet_id=packet_id,
        packet_hash=packet_hash,
        analysis_key=analysis_key,
        name=f"{name}.replay_result",
    )
    primary_bytes = canonical_json_bytes(primary)
    if primary_bytes != canonical_json_bytes(replay):
        raise SemanticEvalContractError(f"{name} replay result is not byte-identical")
    result_hash = hashlib.sha256(primary_bytes).hexdigest()
    if (
        _digest(row["primary_sha256"], f"{name}.primary_sha256") != result_hash
        or _digest(row["replay_sha256"], f"{name}.replay_sha256") != result_hash
    ):
        raise SemanticEvalContractError(f"{name} result hashes do not recompute")
    raw_hash = _digest(
        row["primary_raw_response_sha256"],
        f"{name}.primary_raw_response_sha256",
    )
    if (
        _digest(
            row["replay_raw_response_sha256"],
            f"{name}.replay_raw_response_sha256",
        )
        != raw_hash
    ):
        raise SemanticEvalContractError(f"{name} replay raw-response digest differs")
    primary_provenance = _validate_provenance(
        row["primary_provenance"], f"{name}.primary_provenance"
    )
    replay_provenance = _validate_provenance(
        row["replay_provenance"], f"{name}.replay_provenance"
    )
    if canonical_json_bytes(primary_provenance) != canonical_json_bytes(
        replay_provenance
    ):
        raise SemanticEvalContractError(f"{name} replay provenance differs")
    cache = {
        "schema_version": 1,
        "object_type": "semantic-result",
        "inference_contract": contract,
        "analysis_key": analysis_key,
        "result": primary,
        "provenance": primary_provenance,
        "raw_response_sha256": raw_hash,
    }
    cache_hash = hashlib.sha256(canonical_json_bytes(cache)).hexdigest()
    if (
        _digest(
            row["primary_cache_object_sha256"],
            f"{name}.primary_cache_object_sha256",
        )
        != cache_hash
        or _digest(
            row["replay_cache_object_sha256"],
            f"{name}.replay_cache_object_sha256",
        )
        != cache_hash
    ):
        raise SemanticEvalContractError(f"{name} cache-object hashes do not recompute")
    return row, analysis_key


def _validate_claim_evidence(value: object, name: str) -> list[dict[str, Any]]:
    rows = _array(value, name)
    identities: list[tuple[Any, ...]] = []
    validated: list[dict[str, Any]] = []
    for index, item in enumerate(rows):
        row = _closed(item, _CLAIM_EVIDENCE_FIELDS, f"{name}[{index}]")
        role = _enum(
            row["role"],
            ("requirement", "implementation", "test", "counterevidence"),
            f"{name}[{index}].role",
        )
        path = _relative_path(row["path"], f"{name}[{index}].path")
        start = _integer(row["start_line"], f"{name}[{index}].start_line", minimum=1)
        end = _integer(row["end_line"], f"{name}[{index}].end_line", minimum=1)
        if end < start:
            raise SemanticEvalContractError(f"{name}[{index}] has a reversed span")
        digest = _digest(row["excerpt_sha256"], f"{name}[{index}].excerpt_sha256")
        identities.append((role, path, start, end, digest))
        validated.append(row)
    if identities != sorted(set(identities)):
        raise SemanticEvalContractError(f"{name} must be unique and ordered")
    return validated


def _validate_event_result(
    value: object,
    *,
    name: str,
    identity: dict[str, Any],
    corpus_sha256: str,
    trial: int,
    packet_id: str,
    packet_hash: str,
    claim_hash: str,
    expected_base_epoch: str,
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    row = _closed(value, _EVENT_RESULT_FIELDS, name)
    base = _nonblank(row["base_search_epoch"], f"{name}.base_search_epoch")
    if base != expected_base_epoch:
        raise SemanticEvalContractError(
            f"{name}.base_search_epoch is out of configured order"
        )
    effective = _nonblank(
        row["effective_search_epoch"], f"{name}.effective_search_epoch"
    )
    if effective != derive_eval_search_epoch("eval-verify", base, corpus_sha256, trial):
        raise SemanticEvalContractError(
            f"{name}.effective_search_epoch does not recompute"
        )
    result = _closed(row["result"], _VERIFICATION_RESULT_FIELDS, f"{name}.result")
    if result["schema_version"] != 1:
        raise SemanticEvalContractError(f"{name}.result.schema_version must be 1")
    if (
        result["packet_id"] != packet_id
        or result["packet_hash"] != packet_hash
        or result["claim_hash"] != claim_hash
    ):
        raise SemanticEvalContractError(
            f"{name}.result identity differs from its event"
        )
    verifier_packet_hash = _digest(
        result["verifier_packet_hash"],
        f"{name}.result.verifier_packet_hash",
    )
    verdict = _enum(
        result["verdict"],
        ("support", "refute", "indeterminate"),
        f"{name}.result.verdict",
    )
    score = _finite(result["support_score"], f"{name}.result.support_score")
    if not 0 <= score <= 1:
        raise SemanticEvalContractError(f"{name}.result.support_score must be a rate")
    _nonblank(result["summary"], f"{name}.result.summary")
    evidence_rows = _array(result["evidence"], f"{name}.result.evidence")
    evidence_identities = [
        _validate_canonical_evidence(item, f"{name}.result.evidence[{index}]")
        for index, item in enumerate(evidence_rows)
    ]
    if evidence_identities != sorted(set(evidence_identities)):
        raise SemanticEvalContractError(
            f"{name}.result.evidence must be unique and ordered"
        )
    if verdict in {"support", "refute"} and not evidence_rows:
        raise SemanticEvalContractError(f"{name}.result {verdict} requires evidence")
    verify = cast(dict[str, Any], identity["verify_composition"])
    contract = {
        "verify_contract_version": verify["verify_contract_version"],
        "verifier_packet_hash": verifier_packet_hash,
        "claim_hash": claim_hash,
        "prompt": verify["prompt"],
        "provider": verify["provider"],
        "request": verify["request"],
        "base_search_epoch": base,
        "effective_search_epoch": effective,
    }
    verify_key = hashlib.sha256(canonical_json_bytes(contract)).hexdigest()
    if row["verify_key"] != verify_key or result["verify_key"] != verify_key:
        raise SemanticEvalContractError(f"{name}.verify_key does not recompute")
    raw_hash = _digest(row["raw_response_sha256"], f"{name}.raw_response_sha256")
    provenance = _validate_provenance(row["provenance"], f"{name}.provenance")
    cache = {
        "schema_version": 1,
        "object_type": "verification-result",
        "inference_contract": contract,
        "verify_key": verify_key,
        "result": result,
        "provenance": provenance,
        "raw_response_sha256": raw_hash,
    }
    expected_cache_hash = hashlib.sha256(canonical_json_bytes(cache)).hexdigest()
    if (
        _digest(row["cache_object_sha256"], f"{name}.cache_object_sha256")
        != expected_cache_hash
    ):
        raise SemanticEvalContractError(
            f"{name}.cache_object_sha256 does not recompute"
        )
    return row, verify_key, result


def _expected_aggregate(
    results: list[dict[str, Any]], minimum_support: float
) -> tuple[str, str]:
    verdicts = [cast(dict[str, Any], item["result"])["verdict"] for item in results]
    if "refute" in verdicts:
        return "disputed", "disputed_by_verifier"
    if all(
        cast(dict[str, Any], item["result"])["verdict"] == "support"
        and cast(float, cast(dict[str, Any], item["result"])["support_score"])
        >= minimum_support
        for item in results
    ):
        return "independently_verified", "independently_verified"
    return "verification_indeterminate", "verification_indeterminate"


def _validate_event(  # noqa: C901 approved [SC-17.1] RUFF-SUP-095 exception
    value: object,
    *,
    corpus: SemanticEvalCorpus,
    identity: dict[str, Any],
    attempts: Mapping[tuple[int, str, str, str], dict[str, Any]],
    index: int,
) -> tuple[dict[str, Any], tuple[str, ...], tuple[str, ...]]:
    name = f"report.events[{index}]"
    row = _closed(value, _EVENT_FIELDS, name)
    trial = _integer(row["trial_index"], f"{name}.trial_index")
    if trial >= cast(int, identity["trials"]):
        raise SemanticEvalContractError(
            f"{name}.trial_index is outside configured trials"
        )
    case_id = _nonblank(row["case_id"], f"{name}.case_id")
    variant_id = _nonblank(row["variant_id"], f"{name}.variant_id")
    corpus.fixture(case_id, variant_id)
    packet_id = _nonblank(row["packet_id"], f"{name}.packet_id")
    attempt = attempts.get((trial, case_id, variant_id, packet_id))
    if attempt is None:
        raise SemanticEvalContractError(f"{name} has no analyzer attempt")
    obligation_id = _nonblank(row["obligation_id"], f"{name}.obligation_id")
    if obligation_id != packet_id:
        raise SemanticEvalContractError(
            f"{name}.obligation_id must equal its schema-3 packet ID"
        )
    claim_hash = _digest(row["claim_hash"], f"{name}.claim_hash")
    code = _nonblank(row["code"], f"{name}.code")
    classification = _nonblank(row["classification"], f"{name}.classification")
    if _CODE_BY_CLASSIFICATION.get(classification) != code:
        raise SemanticEvalContractError(f"{name} code/classification mismatch")
    claim_evidence = _validate_claim_evidence(
        row["claim_evidence"], f"{name}.claim_evidence"
    )
    analyzer_result = cast(dict[str, Any], attempt["primary_result"])
    expected_claim_evidence = [
        {
            key: item[key]
            for key in (
                "role",
                "path",
                "start_line",
                "end_line",
                "excerpt_sha256",
            )
        }
        for item in cast(list[dict[str, Any]], analyzer_result["evidence"])
    ]
    if analyzer_result["classification"] != classification or canonical_json_bytes(
        claim_evidence
    ) != canonical_json_bytes(expected_claim_evidence):
        raise SemanticEvalContractError(f"{name} claim differs from analyzer result")
    claim = {
        "packet_id": packet_id,
        "packet_hash": attempt["packet_hash"],
        "obligation_id": obligation_id,
        "kind": analyzer_result["kind"],
        "code": code,
        "classification": classification,
        "statement": analyzer_result["summary"],
        "evidence": claim_evidence,
    }
    if hashlib.sha256(canonical_json_bytes(claim)).hexdigest() != claim_hash:
        raise SemanticEvalContractError(f"{name}.claim_hash does not recompute")
    verify = cast(dict[str, Any], identity["verify_composition"])
    base_epochs = cast(list[str], verify["search_epochs"])
    minimum_support = cast(float, verify["minimum_support_score"])
    side_values: dict[
        str, tuple[bool, list[dict[str, Any]], str | None, str | None]
    ] = {}
    side_keys: dict[str, tuple[str, ...]] = {}
    for side in ("primary", "replay"):
        present = _boolean(row[f"{side}_present"], f"{name}.{side}_present")
        result_values = _array(row[f"{side}_results"], f"{name}.{side}_results")
        aggregate = row[f"{side}_aggregate_state"]
        context = row[f"{side}_context"]
        validated_results: list[dict[str, Any]] = []
        keys: list[str] = []
        if not present:
            if result_values or aggregate is not None or context is not None:
                raise SemanticEvalContractError(
                    f"{name}.{side} absent side is not empty"
                )
        else:
            if len(result_values) != len(base_epochs):
                raise SemanticEvalContractError(
                    f"{name}.{side} result count differs from configured epochs"
                )
            for result_index, result_value in enumerate(result_values):
                validated, verify_key, _result = _validate_event_result(
                    result_value,
                    name=f"{name}.{side}_results[{result_index}]",
                    identity=identity,
                    corpus_sha256=corpus.corpus_sha256,
                    trial=trial,
                    packet_id=packet_id,
                    packet_hash=cast(str, attempt["packet_hash"]),
                    claim_hash=claim_hash,
                    expected_base_epoch=base_epochs[result_index],
                )
                validated_results.append(validated)
                keys.append(verify_key)
            expected_aggregate, expected_context = _expected_aggregate(
                validated_results, minimum_support
            )
            if aggregate != expected_aggregate or context != expected_context:
                raise SemanticEvalContractError(
                    f"{name}.{side} aggregate/context does not recompute"
                )
        side_projection = {
            "present": present,
            "results": validated_results,
            "aggregate_state": aggregate,
            "context": context,
        }
        side_hash = hashlib.sha256(canonical_json_bytes(side_projection)).hexdigest()
        if _digest(row[f"{side}_sha256"], f"{name}.{side}_sha256") != side_hash:
            raise SemanticEvalContractError(f"{name}.{side}_sha256 does not recompute")
        side_values[side] = (
            present,
            validated_results,
            cast(str | None, aggregate),
            cast(str | None, context),
        )
        side_keys[side] = tuple(keys)
    if canonical_json_bytes(side_values["primary"]) != canonical_json_bytes(
        side_values["replay"]
    ):
        raise SemanticEvalContractError(f"{name} verifier replay is not byte-identical")
    if not side_values["primary"][0] and not side_values["replay"][0]:
        raise SemanticEvalContractError(f"{name} cannot have two absent sides")
    comparison_sides: list[dict[str, Any]] = []
    for side in ("primary", "replay"):
        present, results, aggregate, context = side_values[side]
        comparison_sides.append(
            {
                "present": present,
                "results": [
                    {
                        "verdict": cast(dict[str, Any], item["result"])["verdict"],
                        "support_score": cast(dict[str, Any], item["result"])[
                            "support_score"
                        ],
                        "evidence": cast(dict[str, Any], item["result"])["evidence"],
                    }
                    for item in results
                ],
                "aggregate_state": aggregate,
                "context": context,
            }
        )
    comparison = {
        "case_id": case_id,
        "variant_id": variant_id,
        "packet_id": packet_id,
        "code": code,
        "classification": classification,
        "claim_hash": claim_hash,
        "claim_evidence": claim_evidence,
        "primary": comparison_sides[0],
        "replay": comparison_sides[1],
    }
    expected_comparison_hash = hashlib.sha256(
        canonical_json_bytes(comparison)
    ).hexdigest()
    if (
        _digest(
            row["comparison_signature_sha256"],
            f"{name}.comparison_signature_sha256",
        )
        != expected_comparison_hash
    ):
        raise SemanticEvalContractError(
            f"{name}.comparison_signature_sha256 does not recompute"
        )
    return row, side_keys["primary"], side_keys["replay"]


def _rate(value: object, name: str) -> float | None:
    if value is None:
        return None
    result = _finite(value, name)
    if not 0 <= result <= 1:
        raise SemanticEvalContractError(f"{name} must be null or a rate")
    return result


def _validate_metric_row(value: object, name: str) -> dict[str, Any]:
    row = _closed(value, _METRIC_FIELDS, name)
    _integer(row["positive_unit_count"], f"{name}.positive_unit_count")
    _integer(row["negative_unit_count"], f"{name}.negative_unit_count")
    for field_name in (
        "evidence_sufficiency_rate",
        "conditional_precision",
        "conditional_recall",
        "end_to_end_recall",
        "recall_lower_bound",
        "false_positive_rate",
        "false_positive_upper_bound",
        "indeterminate_rate",
        "uncached_flip_rate",
    ):
        _rate(row[field_name], f"{name}.{field_name}")
    _integer(row["false_positive_count"], f"{name}.false_positive_count")
    _boolean(row["all_critical_passed"], f"{name}.all_critical_passed")
    return row


def _wilson_upper(successes: int, total: int, confidence: float) -> float | None:
    if total == 0:
        return None
    from statistics import NormalDist

    z = NormalDist().inv_cdf(0.5 + confidence / 2)
    proportion = successes / total
    denominator = 1 + z * z / total
    center = proportion + z * z / (2 * total)
    margin = z * math.sqrt(
        proportion * (1 - proportion) / total + z * z / (4 * total * total)
    )
    return (center + margin) / denominator


def _wilson_lower(successes: int, total: int, confidence: float) -> float | None:
    if total == 0:
        return None
    from statistics import NormalDist

    z = NormalDist().inv_cdf(0.5 + confidence / 2)
    proportion = successes / total
    denominator = 1 + z * z / total
    center = proportion + z * z / (2 * total)
    margin = z * math.sqrt(
        proportion * (1 - proportion) / total + z * z / (4 * total * total)
    )
    return (center - margin) / denominator


def _fraction(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


_FindingSlot = tuple[str, str, str, str, str]
_VariantKey = tuple[str, str]


def _variant_gold_projection(
    case: Mapping[str, Any], variant_id: str, field_name: str
) -> list[dict[str, Any]]:
    rows = [
        {
            key: value
            for key, value in item.items()
            if key not in {"gold_id", "variant_id"}
        }
        for item in cast(list[dict[str, Any]], case[field_name])
        if item["variant_id"] == variant_id
    ]
    rows.sort(key=canonical_json_bytes)
    return rows


def _observed_rows(
    values: tuple[Mapping[str, Any], ...], name: str
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, value in enumerate(values):
        if not isinstance(value, Mapping):
            raise SemanticEvalContractError(f"{name}[{index}] must be an object")
        row = dict(value)
        try:
            canonical_json_bytes(row)
        except (TypeError, ValueError) as exc:
            raise SemanticEvalContractError(
                f"{name}[{index}] is not canonical-JSON encodable: {exc}"
            ) from exc
        rows.append(row)
    return rows


def _packet_memberships(
    packets: tuple[dict[str, Any], ...],
) -> tuple[set[tuple[Any, ...]], set[tuple[Any, ...]]]:
    declared: set[tuple[Any, ...]] = set()
    candidates: set[tuple[Any, ...]] = set()
    for packet in packets:
        obligation_id = cast(str, packet["obligation_id"])
        for region in cast(list[dict[str, Any]], packet["declared_evidence"]):
            for source in cast(list[dict[str, Any]], region["sources"]):
                declared.add(
                    (
                        obligation_id,
                        source["source_role"],
                        source["receipt_hash"],
                        source["reciprocity_state"],
                    )
                )
        for region in cast(list[dict[str, Any]], packet["counterevidence"]):
            for candidate in cast(list[dict[str, Any]], region["candidates"]):
                candidates.add(
                    (
                        obligation_id,
                        candidate["candidate_id"],
                        candidate["candidate_kind"],
                        candidate["receipt_hash"],
                        candidate["trace_state"],
                    )
                )
    return declared, candidates


def _validate_source_bound_evidence(
    packet: dict[str, Any], result: Mapping[str, Any], name: str
) -> None:
    """Reconstruct canonical evidence from the observed production packet."""

    from backstitch.semantic_evidence import (
        SemanticResultError,
        normalize_packet_evidence,
    )

    evidence = cast(list[dict[str, Any]], result["evidence"])
    coordinates = [
        {
            "role": item["role"],
            "path": item["path"],
            "start_line": item["start_line"],
            "end_line": item["end_line"],
        }
        for item in evidence
    ]
    try:
        reconstructed = normalize_packet_evidence(packet, coordinates)
    except SemanticResultError as exc:
        raise SemanticEvalContractError(
            f"{name} evidence is not bound to the observed source packet: {exc}"
        ) from exc
    expected = [item.to_row() for item in reconstructed]
    if canonical_json_bytes(evidence) != canonical_json_bytes(expected):
        raise SemanticEvalContractError(
            f"{name} evidence bytes contradict the observed source packet"
        )


def _validate_observed_facts(  # noqa: C901 approved [SC-17.1] RUFF-SUP-097 exception
    *,
    corpus: SemanticEvalCorpus,
    report: dict[str, Any],
    observed: SemanticEvalObservedFacts,
) -> tuple[
    dict[_VariantKey, bool],
    dict[_FindingSlot, bool],
    dict[_VariantKey, dict[str, dict[str, Any]]],
]:
    """Validate source facts and derive eligibility without report input."""

    if not isinstance(observed, SemanticEvalObservedFacts):
        raise SemanticEvalContractError(
            "authoritative validation requires SemanticEvalObservedFacts"
        )
    observed_keys = tuple((item.case_id, item.variant_id) for item in observed.variants)
    if observed_keys != corpus.variant_keys:
        raise SemanticEvalContractError(
            "observed source facts do not cover corpus variants in order"
        )
    manifest = corpus.to_dict()
    case_rows = {
        cast(str, case["case_id"]): case
        for case in cast(list[dict[str, Any]], manifest["cases"])
    }
    eligibility: dict[_VariantKey, bool] = {}
    sufficient: dict[_FindingSlot, bool] = {}
    packet_maps: dict[_VariantKey, dict[str, dict[str, Any]]] = {}
    evidence_gold_by_id: dict[tuple[str, str, str], dict[str, Any]] = {}
    candidate_gold_by_id: dict[tuple[str, str, str], dict[str, Any]] = {}

    from backstitch.artifact_contracts import load_packets_bytes

    for index, facts in enumerate(observed.variants):
        name = f"observed.variants[{index}]"
        case_id = _nonblank(facts.case_id, f"{name}.case_id")
        variant_id = _nonblank(facts.variant_id, f"{name}.variant_id")
        key = (case_id, variant_id)
        case = case_rows[case_id]
        issue_count = _integer(
            facts.deterministic_issue_count,
            f"{name}.deterministic_issue_count",
        )
        if facts.deterministic_problem is not None:
            _nonblank(facts.deterministic_problem, f"{name}.deterministic_problem")
        obligations = _observed_rows(facts.obligations, f"{name}.obligations")
        evidence = _observed_rows(facts.evidence, f"{name}.evidence")
        candidates = _observed_rows(facts.candidates, f"{name}.candidates")
        obligations.sort(key=canonical_json_bytes)
        evidence.sort(key=canonical_json_bytes)
        candidates.sort(key=canonical_json_bytes)
        packet_values = _observed_rows(facts.packets, f"{name}.packets")
        packet_jsonl = b"".join(
            canonical_json_bytes(packet) + b"\n" for packet in packet_values
        )
        try:
            validated_packets = load_packets_bytes(
                packet_jsonl, source=f"semantic eval observed {case_id}/{variant_id}"
            )
        except ValueError as exc:
            raise SemanticEvalContractError(
                f"{name}.packets are invalid production packets: {exc}"
            ) from exc
        packets = tuple(packet.to_dict() for packet in validated_packets)
        if packets != tuple(packet_values):
            raise SemanticEvalContractError(
                f"{name}.packets changed during production validation"
            )
        packet_map = {cast(str, packet["packet_id"]): packet for packet in packets}
        if len(packet_map) != len(packets):
            raise SemanticEvalContractError(
                f"{name}.packets contain duplicate packet IDs"
            )
        packet_maps[key] = packet_map

        expected_obligations = _variant_gold_projection(
            case, variant_id, "gold_obligations"
        )
        expected_evidence = _variant_gold_projection(case, variant_id, "gold_evidence")
        expected_candidates = _variant_gold_projection(
            case, variant_id, "gold_candidates"
        )
        expected_packet_ids = tuple(
            cast(str, item["packet_id"]) for item in expected_obligations
        )
        if tuple(packet_map) != tuple(sorted(expected_packet_ids)):
            raise SemanticEvalContractError(
                f"{name}.packets contradict the corpus packet inventory"
            )

        declared_membership, candidate_membership = _packet_memberships(packets)
        expected_declared = {
            (
                item["obligation_id"],
                item["source_role"],
                item["receipt_hash"],
                item["reciprocity_state"],
            )
            for item in expected_evidence
        }
        expected_candidate_membership = {
            (
                item["obligation_id"],
                item["candidate_id"],
                item["candidate_kind"],
                item["receipt_hash"],
                item["trace_state"],
            )
            for item in expected_candidates
            if item["trace_state"] != "declared"
        }
        eligibility[key] = (
            issue_count == 0
            and facts.deterministic_problem is None
            and obligations == expected_obligations
            and evidence == expected_evidence
            and candidates == expected_candidates
            and declared_membership == expected_declared
            and candidate_membership == expected_candidate_membership
        )

        for item in cast(list[dict[str, Any]], case["gold_evidence"]):
            if item["variant_id"] == variant_id:
                evidence_gold_by_id[(case_id, variant_id, item["gold_id"])] = item
        for item in cast(list[dict[str, Any]], case["gold_candidates"]):
            if item["variant_id"] == variant_id:
                candidate_gold_by_id[(case_id, variant_id, item["gold_id"])] = item
        for finding in cast(list[dict[str, Any]], case["expected_findings"]):
            if finding["variant_id"] != variant_id:
                continue
            packet_id = cast(str, finding["packet_id"])
            declared_required = all(
                (
                    packet_id,
                    evidence_gold_by_id[(case_id, variant_id, gold_id)]["source_role"],
                    evidence_gold_by_id[(case_id, variant_id, gold_id)]["receipt_hash"],
                    evidence_gold_by_id[(case_id, variant_id, gold_id)][
                        "reciprocity_state"
                    ],
                )
                in declared_membership
                for gold_id in finding["required_declared_evidence_gold_ids"]
            )
            candidate_required = all(
                (
                    packet_id,
                    candidate_gold_by_id[(case_id, variant_id, gold_id)][
                        "candidate_id"
                    ],
                    candidate_gold_by_id[(case_id, variant_id, gold_id)][
                        "candidate_kind"
                    ],
                    candidate_gold_by_id[(case_id, variant_id, gold_id)][
                        "receipt_hash"
                    ],
                    candidate_gold_by_id[(case_id, variant_id, gold_id)]["trace_state"],
                )
                in candidate_membership
                for gold_id in finding["required_counterevidence_gold_ids"]
            )
            slot = (
                case_id,
                variant_id,
                packet_id,
                cast(str, finding["code"]),
                cast(str, finding["classification"]),
            )
            sufficient[slot] = (
                eligibility[key] and declared_required and candidate_required
            )

    attempts = cast(list[dict[str, Any]], report["analysis_attempts"])
    attempt_map = {
        (
            cast(int, attempt["trial_index"]),
            cast(str, attempt["case_id"]),
            cast(str, attempt["variant_id"]),
            cast(str, attempt["packet_id"]),
        ): attempt
        for attempt in attempts
    }
    for attempt_key, attempt in attempt_map.items():
        _trial, case_id, variant_id, packet_id = attempt_key
        packet = packet_maps[(case_id, variant_id)][packet_id]
        if attempt["packet_hash"] != packet["packet_hash"]:
            raise SemanticEvalContractError(
                "analysis attempt packet hash contradicts observed source packet"
            )
        _validate_source_bound_evidence(
            packet,
            cast(dict[str, Any], attempt["primary_result"]),
            "analysis result",
        )

    from backstitch.semantic_verification import (
        build_verification_request,
        derive_verification_claim,
    )

    for event in cast(list[dict[str, Any]], report["events"]):
        trial = cast(int, event["trial_index"])
        case_id = cast(str, event["case_id"])
        variant_id = cast(str, event["variant_id"])
        packet_id = cast(str, event["packet_id"])
        packet = packet_maps[(case_id, variant_id)][packet_id]
        attempt = attempt_map[(trial, case_id, variant_id, packet_id)]
        try:
            claim = derive_verification_claim(
                packet, cast(dict[str, Any], attempt["primary_result"])
            )
            request = build_verification_request(packet, claim)
        except VerificationContractError as exc:
            raise SemanticEvalContractError(
                f"verification event is not bound to observed source packet: {exc}"
            ) from exc
        if event["claim_hash"] != claim.claim_hash:
            raise SemanticEvalContractError(
                "verification event claim hash contradicts observed source packet"
            )
        for side in ("primary", "replay"):
            for result_row in cast(list[dict[str, Any]], event[f"{side}_results"]):
                result = cast(dict[str, Any], result_row["result"])
                if result["verifier_packet_hash"] != request.verifier_packet_hash:
                    raise SemanticEvalContractError(
                        "verifier packet hash contradicts observed source packet"
                    )
                _validate_source_bound_evidence(packet, result, "verification result")
    return eligibility, sufficient, packet_maps


def _metric_row_from_observed(  # noqa: C901 approved [SC-17.1] RUFF-SUP-092 exception
    *,
    corpus: SemanticEvalCorpus,
    report: dict[str, Any],
    eligibility: Mapping[_VariantKey, bool],
    sufficient: Mapping[_FindingSlot, bool],
    code: str | None,
) -> dict[str, Any]:
    manifest = corpus.to_dict()
    cases = cast(list[dict[str, Any]], manifest["cases"])
    expected: set[_FindingSlot] = set()
    critical_variants: set[_VariantKey] = set()
    all_variants = set(corpus.variant_keys)
    for case in cases:
        case_id = cast(str, case["case_id"])
        variants = [case["clean"], *case["mutations"]]
        if cast(bool, case["critical"]):
            critical_variants.update(
                (case_id, cast(str, fixture["variant_id"])) for fixture in variants
            )
        for finding in cast(list[dict[str, Any]], case["expected_findings"]):
            if code is not None and finding["code"] != code:
                continue
            expected.add(
                (
                    case_id,
                    cast(str, finding["variant_id"]),
                    cast(str, finding["packet_id"]),
                    cast(str, finding["code"]),
                    cast(str, finding["classification"]),
                )
            )
    negative_variants = {
        variant
        for variant in all_variants
        if not any(slot[:2] == variant for slot in expected)
    }
    trials = cast(int, cast(dict[str, Any], report["identity"])["trials"])
    attempt_slots: dict[tuple[int, _FindingSlot], dict[str, Any]] = {}
    for attempt in cast(list[dict[str, Any]], report["analysis_attempts"]):
        result = cast(dict[str, Any], attempt["primary_result"])
        classification = cast(str, result["classification"])
        if classification == "ok":
            continue
        result_code = _CODE_BY_CLASSIFICATION[classification]
        if code is not None and result_code != code:
            continue
        slot: _FindingSlot = (
            cast(str, attempt["case_id"]),
            cast(str, attempt["variant_id"]),
            cast(str, attempt["packet_id"]),
            result_code,
            classification,
        )
        attempt_slots[(cast(int, attempt["trial_index"]), slot)] = attempt
    event_slots: dict[tuple[int, _FindingSlot], dict[str, Any]] = {}
    for event in cast(list[dict[str, Any]], report["events"]):
        event_code = cast(str, event["code"])
        if code is not None and event_code != code:
            continue
        slot = (
            cast(str, event["case_id"]),
            cast(str, event["variant_id"]),
            cast(str, event["packet_id"]),
            event_code,
            cast(str, event["classification"]),
        )
        event_slots[(cast(int, event["trial_index"]), slot)] = event

    predictions = {
        slot
        for (_trial, slot), event in event_slots.items()
        if event["primary_context"] == "independently_verified"
    }
    stable: set[_FindingSlot] = set()
    for slot in expected:
        events = [event_slots.get((trial, slot)) for trial in range(trials)]
        if (
            all(
                event is not None
                and event["primary_context"] == "independently_verified"
                for event in events
            )
            and len(
                {
                    cast(str, event["comparison_signature_sha256"])
                    for event in events
                    if event is not None
                }
            )
            == 1
        ):
            stable.add(slot)

    sufficient_expected = {slot for slot in expected if sufficient.get(slot, False)}
    eligible_predictions = {
        slot for slot in predictions if eligibility.get(slot[:2], False)
    }
    matching_eligible_predictions = eligible_predictions & expected
    produced_expected = {
        slot
        for slot in expected
        if any((trial, slot) in attempt_slots for trial in range(trials))
    }
    indeterminate_expected: set[_FindingSlot] = set()
    for slot in produced_expected:
        for trial in range(trials):
            trial_event = event_slots.get((trial, slot))
            if (
                trial_event is not None
                and trial_event["primary_context"] == "verification_indeterminate"
            ):
                indeterminate_expected.add(slot)
                break
    false_positive_variants = {
        variant
        for variant in negative_variants
        if any(slot[:2] == variant for slot in predictions)
    }

    finding_slots = {slot for _trial, slot in attempt_slots}
    flip_count = 0
    flip_total = 0
    critical_flip_count = 0
    for slot in finding_slots:
        for left in range(trials):
            for right in range(left + 1, trials):
                left_event = event_slots.get((left, slot))
                right_event = event_slots.get((right, slot))
                left_signature = (
                    None
                    if left_event is None
                    else left_event["comparison_signature_sha256"]
                )
                right_signature = (
                    None
                    if right_event is None
                    else right_event["comparison_signature_sha256"]
                )
                flipped = left_signature != right_signature
                flip_total += 1
                flip_count += flipped
                if slot[:2] in critical_variants:
                    critical_flip_count += flipped

    critical_passed = all(
        eligibility.get(variant, False) for variant in critical_variants
    )
    critical_passed = critical_passed and all(
        slot in stable for slot in expected if slot[:2] in critical_variants
    )
    for variant in critical_variants:
        variant_expected = {slot for slot in expected if slot[:2] == variant}
        variant_predictions = {slot for slot in predictions if slot[:2] == variant}
        if not variant_predictions <= variant_expected:
            critical_passed = False
    if critical_flip_count:
        critical_passed = False

    confidence = cast(
        float,
        cast(dict[str, Any], cast(dict[str, Any], report["identity"])["eval_config"])[
            "confidence_level"
        ],
    )
    positive_count = len(expected)
    negative_count = len(negative_variants)
    stable_count = len(stable)
    false_positive_count = len(false_positive_variants)
    return {
        "positive_unit_count": positive_count,
        "negative_unit_count": negative_count,
        "evidence_sufficiency_rate": _fraction(
            len(sufficient_expected), positive_count
        ),
        "conditional_precision": _fraction(
            len(matching_eligible_predictions), len(eligible_predictions)
        ),
        "conditional_recall": _fraction(
            len(stable & sufficient_expected), len(sufficient_expected)
        ),
        "end_to_end_recall": _fraction(stable_count, positive_count),
        "recall_lower_bound": _wilson_lower(stable_count, positive_count, confidence),
        "false_positive_rate": _fraction(false_positive_count, negative_count),
        "false_positive_upper_bound": _wilson_upper(
            false_positive_count, negative_count, confidence
        ),
        "indeterminate_rate": _fraction(
            len(indeterminate_expected), len(produced_expected)
        ),
        "uncached_flip_rate": _fraction(flip_count, flip_total),
        "false_positive_count": false_positive_count,
        "all_critical_passed": critical_passed,
    }


def derive_semantic_eval_metrics(
    *,
    corpus: SemanticEvalCorpus,
    identity: Mapping[str, Any],
    analysis_attempts: tuple[Mapping[str, Any], ...],
    events: tuple[Mapping[str, Any], ...],
    observed: SemanticEvalObservedFacts,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Derive aggregate and by-code metrics from production observations.

    The evaluation runner uses this provider-free seam to construct a
    candidate report.  Authoritative validation calls the same seam again
    after closed report validation, avoiding a second metric implementation.
    """

    event_rows = [dict(item) for item in events]
    evaluation: dict[str, Any] = {
        "identity": dict(identity),
        "analysis_attempts": [dict(item) for item in analysis_attempts],
        "events": event_rows,
    }
    eligibility, sufficient, _packet_maps = _validate_observed_facts(
        corpus=corpus, report=evaluation, observed=observed
    )
    metrics = _metric_row_from_observed(
        corpus=corpus,
        report=evaluation,
        eligibility=eligibility,
        sufficient=sufficient,
        code=None,
    )
    manifest = corpus.to_dict()
    codes = {
        cast(str, finding["code"])
        for case in cast(list[dict[str, Any]], manifest["cases"])
        for finding in cast(list[dict[str, Any]], case["expected_findings"])
    }
    codes.update(
        cast(str, event["code"])
        for event in event_rows
        if event["primary_context"] == "independently_verified"
    )
    by_code = [
        {
            "code": code,
            "metrics": _metric_row_from_observed(
                corpus=corpus,
                report=evaluation,
                eligibility=eligibility,
                sufficient=sufficient,
                code=code,
            ),
        }
        for code in _SEMANTIC_CODES
        if code in codes
    ]
    return metrics, by_code


def validate_semantic_eval_report_authoritatively(
    report: Mapping[str, Any] | SemanticEvalReport,
    *,
    corpus: SemanticEvalCorpus,
    observed: SemanticEvalObservedFacts,
    path: Path | None = None,
) -> SemanticEvalReport:
    """Recompute a schema-3 report from separately derived source facts.

    This is the source-authoritative boundary.  Callers must run the ordinary
    production source pipeline and pass its projections in ``observed``.  This
    function never derives, guesses, or substitutes source facts from gold or
    from the report under review.
    """

    validated = validate_semantic_eval_report_consistency(
        report, corpus=corpus, path=path
    )
    value = validated.to_dict()
    expected_metrics, expected_by_code = derive_semantic_eval_metrics(
        corpus=corpus,
        identity=cast(dict[str, Any], value["identity"]),
        analysis_attempts=tuple(cast(list[dict[str, Any]], value["analysis_attempts"])),
        events=tuple(cast(list[dict[str, Any]], value["events"])),
        observed=observed,
    )
    if canonical_json_bytes(value["metrics"]) != canonical_json_bytes(expected_metrics):
        raise SemanticEvalContractError(
            "aggregate metrics do not recompute from observed source facts"
        )
    if canonical_json_bytes(value["by_code"]) != canonical_json_bytes(expected_by_code):
        raise SemanticEvalContractError(
            "by-code metrics do not recompute from observed source facts"
        )
    return validated


def _expected_counts(
    corpus: SemanticEvalCorpus, code: str | None = None
) -> tuple[int, int]:
    manifest = corpus.to_dict()
    positives = 0
    negatives = 0
    for case in cast(list[dict[str, Any]], manifest["cases"]):
        variants = [case["clean"], *case["mutations"]]
        findings = cast(list[dict[str, Any]], case["expected_findings"])
        for fixture in variants:
            matching = [
                finding
                for finding in findings
                if finding["variant_id"] == fixture["variant_id"]
                and (code is None or finding["code"] == code)
            ]
            positives += len(matching)
            if not matching:
                negatives += 1
    return positives, negatives


def _validate_operational(  # noqa: C901 approved [SC-17.1] RUFF-SUP-098 exception
    value: object,
    *,
    analysis_keys: tuple[str, ...],
    verify_primary_keys: tuple[str, ...],
    verify_replay_keys: tuple[str, ...],
) -> dict[str, Any]:
    row = _closed(value, _OPERATIONAL_FIELDS, "report.operational")
    counter_fields = _OPERATIONAL_FIELDS - {
        "analysis_cost",
        "verify_cost",
        "total_estimated_cost_microusd",
    }
    for field_name in counter_fields:
        _integer(row[field_name], f"report.operational.{field_name}")
    distinct_analysis = len(set(analysis_keys))
    distinct_verify_primary = len(set(verify_primary_keys))
    distinct_verify_replay = len(set(verify_replay_keys))
    expected = {
        "analyzer_primary_cache_hits": 0,
        "analyzer_primary_cache_misses": distinct_analysis,
        "analyzer_primary_provider_calls": distinct_analysis,
        "analyzer_replay_cache_hits": distinct_analysis,
        "analyzer_replay_cache_misses": 0,
        "analyzer_replay_provider_calls": 0,
        "verifier_primary_cache_hits": 0,
        "verifier_primary_cache_misses": distinct_verify_primary,
        "verifier_primary_provider_calls": distinct_verify_primary,
        "verifier_replay_cache_hits": distinct_verify_replay,
        "verifier_replay_cache_misses": 0,
        "verifier_replay_provider_calls": 0,
    }
    if any(row[name] != expected_value for name, expected_value in expected.items()):
        raise SemanticEvalContractError(
            "report operational lane counters do not recompute"
        )
    expected_hits = distinct_analysis + distinct_verify_replay
    expected_misses = distinct_analysis + distinct_verify_primary
    expected_calls = distinct_analysis + distinct_verify_primary
    if (
        row["cache_hits"] != expected_hits
        or row["cache_misses"] != expected_misses
        or row["provider_calls"] != expected_calls
    ):
        raise SemanticEvalContractError(
            "report aggregate operational counters do not recompute"
        )
    costs: list[int | None] = []
    for lane, calls in (
        ("analysis_cost", distinct_analysis),
        ("verify_cost", distinct_verify_primary),
    ):
        cost = _closed(row[lane], _COST_FIELDS, f"report.operational.{lane}")
        amount = cost["estimated_cost_microusd"]
        source = cost["cost_rate_source"]
        if amount is not None:
            _integer(
                amount,
                f"report.operational.{lane}.estimated_cost_microusd",
            )
        if source is not None:
            _nonblank(source, f"report.operational.{lane}.cost_rate_source")
        if calls == 0 and cost != {
            "estimated_cost_microusd": 0,
            "cost_rate_source": None,
        }:
            raise SemanticEvalContractError(
                f"report.operational.{lane} zero-call cost is invalid"
            )
        if calls > 0 and ((amount is None) != (source is None)):
            raise SemanticEvalContractError(
                f"report.operational.{lane} cost/source pairing is invalid"
            )
        costs.append(cast(int | None, amount))
    total = row["total_estimated_cost_microusd"]
    if total is not None:
        _integer(total, "report.operational.total_estimated_cost_microusd")
    expected_total = (
        None if any(item is None for item in costs) else sum(cast(list[int], costs))
    )
    if total != expected_total:
        raise SemanticEvalContractError(
            "report total estimated cost does not recompute"
        )
    return row


def _expected_qualification_checks(
    *,
    metrics: dict[str, Any],
    by_code: tuple[tuple[str, dict[str, Any]], ...],
    config: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    field_by_check = {
        "minimum_positive_units": "positive_unit_count",
        "minimum_negative_units": "negative_unit_count",
        "minimum_evidence_sufficiency_rate": "evidence_sufficiency_rate",
        "minimum_conditional_precision": "conditional_precision",
        "minimum_conditional_recall": "conditional_recall",
        "minimum_end_to_end_recall": "end_to_end_recall",
        "minimum_recall_lower_bound": "recall_lower_bound",
        "maximum_false_positive_rate": "false_positive_rate",
        "maximum_false_positive_upper_bound": "false_positive_upper_bound",
        "maximum_indeterminate_rate": "indeterminate_rate",
        "maximum_uncached_flip_rate": "uncached_flip_rate",
    }
    expected_checks: list[dict[str, Any]] = []
    failures: list[str] = []
    groups = [
        ("", metrics),
        *[(f"{code}:", metric) for code, metric in by_code],
    ]
    for prefix, metric in groups:
        for name in _CHECK_NAMES[:-1]:
            observed = metric[field_by_check[name]]
            comparator = ">=" if name.startswith("minimum") else "<="
            threshold = config[name]
            passed = observed is not None and (
                observed >= threshold if comparator == ">=" else observed <= threshold
            )
            check_name = prefix + name
            expected_checks.append(
                {
                    "kind": "numeric",
                    "name": check_name,
                    "comparator": comparator,
                    "threshold": threshold,
                    "observed": observed,
                    "passed": passed,
                }
            )
            if not passed:
                failures.append(check_name)
        critical_passed = (
            not config["require_all_critical"] or metric["all_critical_passed"]
        )
        critical_name = prefix + "require_all_critical"
        expected_checks.append(
            {
                "kind": "boolean",
                "name": critical_name,
                "comparator": "true",
                "threshold": True,
                "observed": metric["all_critical_passed"],
                "passed": critical_passed,
            }
        )
        if not critical_passed:
            failures.append(critical_name)
    return expected_checks, failures


def _validate_qualification(
    value: object,
    *,
    metrics: dict[str, Any],
    by_code: tuple[tuple[str, dict[str, Any]], ...],
    config: dict[str, Any],
    mode: str,
) -> None:
    row = _closed(value, _QUALIFICATION_FIELDS, "report.qualification")
    if row["mode"] != mode:
        raise SemanticEvalContractError(
            "report qualification mode differs from corpus mode"
        )
    if (
        row["positive_unit_count"] != metrics["positive_unit_count"]
        or row["negative_unit_count"] != metrics["negative_unit_count"]
    ):
        raise SemanticEvalContractError(
            "qualification sample counts differ from metrics"
        )
    expected_checks, failures = _expected_qualification_checks(
        metrics=metrics, by_code=by_code, config=config
    )
    checks = _array(row["checks"], "report.qualification.checks")
    for index, item in enumerate(checks):
        check = _closed(item, _CHECK_FIELDS, f"report.qualification.checks[{index}]")
        if check["kind"] not in {"numeric", "boolean"}:
            raise SemanticEvalContractError("qualification check kind is invalid")
    if canonical_json_bytes(checks) != canonical_json_bytes(expected_checks):
        raise SemanticEvalContractError("qualification checks do not recompute")
    reason_rows = _array(row["failure_reasons"], "report.qualification.failure_reasons")
    if reason_rows != failures:
        raise SemanticEvalContractError(
            "qualification failure reasons do not recompute"
        )
    if row["passed"] is not (not failures):
        raise SemanticEvalContractError("qualification passed flag does not recompute")


def validate_semantic_eval_report_consistency(  # noqa: C901 approved [SC-17.1] RUFF-SUP-099 exception
    report: Mapping[str, Any] | SemanticEvalReport,
    *,
    corpus: SemanticEvalCorpus,
    path: Path | None = None,
) -> SemanticEvalReport:
    """Validate report-local schema, identities, caches, metrics, and checks."""

    value = report.to_dict() if isinstance(report, SemanticEvalReport) else dict(report)
    row = _closed(value, _REPORT_FIELDS, "semantic eval report")
    if (
        row["schema_version"] != 3
        or row["artifact"] != "backstitch-verification-eval-report"
    ):
        raise SemanticEvalContractError("semantic eval report identity is invalid")
    identity = _validate_identity(row["identity"], corpus)
    attempts = _array(row["analysis_attempts"], "report.analysis_attempts")
    analysis_keys: list[str] = []
    attempt_map: dict[tuple[int, str, str, str], dict[str, Any]] = {}
    prior_attempt: tuple[int, int, str] | None = None
    variant_order = {key: index for index, key in enumerate(corpus.variant_keys)}
    for index, attempt in enumerate(attempts):
        validated, key = _validate_analysis_attempt(
            attempt, corpus=corpus, identity=identity, index=index
        )
        fixture_key = (
            cast(str, validated["case_id"]),
            cast(str, validated["variant_id"]),
        )
        attempt_order = (
            cast(int, validated["trial_index"]),
            variant_order[fixture_key],
            cast(str, validated["packet_id"]),
        )
        if prior_attempt is not None and attempt_order <= prior_attempt:
            raise SemanticEvalContractError(
                "analysis attempts are not unique and ordered"
            )
        prior_attempt = attempt_order
        analysis_keys.append(key)
        attempt_map[
            (
                cast(int, validated["trial_index"]),
                cast(str, validated["case_id"]),
                cast(str, validated["variant_id"]),
                cast(str, validated["packet_id"]),
            )
        ] = validated
    expected_attempt_keys: set[tuple[int, str, str, str]] = set()
    manifest = corpus.to_dict()
    for case in cast(list[dict[str, Any]], manifest["cases"]):
        for obligation in cast(list[dict[str, Any]], case["gold_obligations"]):
            for trial in range(cast(int, identity["trials"])):
                expected_attempt_keys.add(
                    (
                        trial,
                        cast(str, case["case_id"]),
                        cast(str, obligation["variant_id"]),
                        cast(str, obligation["packet_id"]),
                    )
                )
    if set(attempt_map) != expected_attempt_keys:
        raise SemanticEvalContractError(
            "analysis attempts do not cover every trial and gold packet"
        )
    events = _array(row["events"], "report.events")
    event_rows: list[dict[str, Any]] = []
    event_keys: set[tuple[int, str, str, str, str, str]] = set()
    verify_primary_keys: list[str] = []
    verify_replay_keys: list[str] = []
    prior_event: tuple[Any, ...] | None = None
    code_order = {code: index for index, code in enumerate(_SEMANTIC_CODES)}
    for index, event in enumerate(events):
        validated, primary_keys, replay_keys = _validate_event(
            event,
            corpus=corpus,
            identity=identity,
            attempts=attempt_map,
            index=index,
        )
        event_order = (
            cast(int, validated["trial_index"]),
            cast(str, validated["case_id"]),
            variant_order[
                (
                    cast(str, validated["case_id"]),
                    cast(str, validated["variant_id"]),
                )
            ],
            cast(str, validated["packet_id"]),
            code_order[cast(str, validated["code"])],
            cast(str, validated["classification"]),
            cast(str, validated["claim_hash"]),
        )
        if prior_event is not None and event_order <= prior_event:
            raise SemanticEvalContractError(
                "verification events are not unique and ordered"
            )
        prior_event = event_order
        event_rows.append(validated)
        event_keys.add(
            (
                cast(int, validated["trial_index"]),
                cast(str, validated["case_id"]),
                cast(str, validated["variant_id"]),
                cast(str, validated["packet_id"]),
                cast(str, validated["code"]),
                cast(str, validated["classification"]),
            )
        )
        verify_primary_keys.extend(primary_keys)
        verify_replay_keys.extend(replay_keys)
    expected_event_keys: set[tuple[int, str, str, str, str, str]] = set()
    for attempt_key, attempt in attempt_map.items():
        result = cast(dict[str, Any], attempt["primary_result"])
        classification = cast(str, result["classification"])
        if classification == "ok":
            continue
        expected_event_keys.add(
            (*attempt_key, _CODE_BY_CLASSIFICATION[classification], classification)
        )
    if event_keys != expected_event_keys:
        raise SemanticEvalContractError(
            "verification events do not cover every analyzer finding"
        )
    positive_count, negative_count = _expected_counts(corpus)
    metrics = _validate_metric_row(row["metrics"], "report.metrics")
    if (
        metrics["positive_unit_count"] != positive_count
        or metrics["negative_unit_count"] != negative_count
    ):
        raise SemanticEvalContractError(
            "aggregate metric sample counts do not match corpus"
        )
    if positive_count == 0 and not event_rows:
        null_fields = (
            "evidence_sufficiency_rate",
            "conditional_precision",
            "conditional_recall",
            "end_to_end_recall",
            "recall_lower_bound",
            "indeterminate_rate",
            "uncached_flip_rate",
        )
        if any(metrics[name] is not None for name in null_fields):
            raise SemanticEvalContractError("zero-positive metric fields must be null")
        confidence = cast(
            float,
            cast(dict[str, Any], identity["eval_config"])["confidence_level"],
        )
        if (
            metrics["false_positive_rate"] != 0.0
            or metrics["false_positive_count"] != 0
            or metrics["false_positive_upper_bound"]
            != _wilson_upper(0, negative_count, confidence)
        ):
            raise SemanticEvalContractError("negative-control metrics do not recompute")
        if metrics["all_critical_passed"] is not True:
            raise SemanticEvalContractError(
                "empty critical set must pass raw critical observation"
            )
    expected_codes = {
        cast(str, finding["code"])
        for case in cast(list[dict[str, Any]], manifest["cases"])
        for finding in cast(list[dict[str, Any]], case["expected_findings"])
    }
    expected_codes.update(
        cast(str, event["code"])
        for event in event_rows
        if event["primary_context"] == "independently_verified"
    )
    ordered_codes = tuple(code for code in _SEMANTIC_CODES if code in expected_codes)
    by_code_values = _array(row["by_code"], "report.by_code")
    if len(by_code_values) != len(ordered_codes):
        raise SemanticEvalContractError(
            "by_code rows do not cover expected and predicted codes"
        )
    by_code: list[tuple[str, dict[str, Any]]] = []
    for index, expected_code in enumerate(ordered_codes):
        code_row = _closed(
            by_code_values[index],
            _BY_CODE_FIELDS,
            f"report.by_code[{index}]",
        )
        if code_row["code"] != expected_code:
            raise SemanticEvalContractError(
                "by_code rows are out of canonical code order"
            )
        code_metrics = _validate_metric_row(
            code_row["metrics"], f"report.by_code[{index}].metrics"
        )
        code_positive, code_negative = _expected_counts(corpus, expected_code)
        if (
            code_metrics["positive_unit_count"] != code_positive
            or code_metrics["negative_unit_count"] != code_negative
        ):
            raise SemanticEvalContractError(
                f"by_code {expected_code} sample counts do not match corpus"
            )
        by_code.append((expected_code, code_metrics))
    _validate_operational(
        row["operational"],
        analysis_keys=tuple(analysis_keys),
        verify_primary_keys=tuple(verify_primary_keys),
        verify_replay_keys=tuple(verify_replay_keys),
    )
    config = cast(dict[str, Any], identity["eval_config"])
    _validate_qualification(
        row["qualification"],
        metrics=metrics,
        by_code=tuple(by_code),
        config=config,
        mode=corpus.mode,
    )
    canonical = canonical_json_bytes(row)
    return SemanticEvalReport(
        path=path,
        report_sha256="sha256:" + hashlib.sha256(canonical).hexdigest(),
        passed=cast(bool, cast(dict[str, Any], row["qualification"])["passed"]),
        identity=identity,
        _canonical=canonical,
    )


def read_semantic_eval_report_bytes(
    path: Path,
    *,
    maximum_bytes: int = _DEFAULT_REPORT_BYTES,
) -> tuple[Path, bytes]:
    """Read one report once through the bounded regular-file boundary."""

    address = path.absolute()
    try:
        address.lstat()
    except FileNotFoundError:
        raise
    raw = _read_regular(
        address, maximum_bytes=maximum_bytes, name="semantic eval report"
    )
    return address.resolve(), raw


def load_semantic_eval_report_bytes(
    raw: bytes,
    *,
    path: Path,
    corpus: SemanticEvalCorpus,
    maximum_bytes: int = _DEFAULT_REPORT_BYTES,
) -> SemanticEvalReport:
    """Validate already bounded report bytes without reopening their path."""

    _integer(maximum_bytes, "semantic eval report.maximum_bytes", minimum=1)
    if len(raw) > maximum_bytes:
        raise SemanticEvalContractError("semantic eval report exceeds its bounded read")
    value, _canonical = _parse_canonical_object(
        raw, name="semantic eval report", final_lf="required"
    )
    return validate_semantic_eval_report_consistency(value, corpus=corpus, path=path)


def load_semantic_eval_report(
    path: Path,
    *,
    corpus: SemanticEvalCorpus,
    maximum_bytes: int = _DEFAULT_REPORT_BYTES,
) -> SemanticEvalReport:
    """Bounded-load one canonical schema-3 qualification report."""

    resolved, raw = read_semantic_eval_report_bytes(path, maximum_bytes=maximum_bytes)
    return load_semantic_eval_report_bytes(
        raw,
        path=resolved,
        corpus=corpus,
        maximum_bytes=maximum_bytes,
    )
