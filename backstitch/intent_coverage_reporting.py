"""Closed schema-1 rendering for deterministic intent coverage.

Spec: docs/specs/08-intent-coverage.md [COV-3], [COV-9]
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from collections import defaultdict
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, Literal

from backstitch.canonical import canonical_json_bytes, canonical_repository_path
from backstitch.git_baseline import (
    DriftEvent,
    GitBaselineMetadata,
    PolicyEvent,
    StaleDocTrend,
)
from backstitch.grammar import is_prefixed_sha256
from backstitch.intent_coverage import (
    ClassifiedDefinition,
    CoverageCounts,
    CoverageFloorResult,
    CoverageUnscannableFile,
    IntentCoverageResult,
)
from backstitch.models import Issue, issue_sort_key

_ARTIFACT = "backstitch-intent-coverage-report"
_SCHEMA_VERSION = 1
_TOP_LEVEL_FIELDS = (
    "artifact",
    "schema_version",
    "profile",
    "repo_root",
    "mode",
    "metric_identity",
    "baseline",
    "summary",
    "trees",
    "floors",
    "unscannable_files",
    "definitions",
    "worklist",
    "requirements",
    "exemptions",
    "policy_events",
    "drift_events",
    "stale_doc_trends",
    "spec_growth",
    "issues",
    "report_sha256",
)
_METRIC_FIELDS = (
    "id",
    "algorithm_version",
    "direct_numerator",
    "direct_denominator",
    "accounted_numerator",
    "accounted_denominator",
)
_BASELINE_FIELDS = (
    "configured_ref",
    "resolved_commit",
    "merge_base",
    "current_snapshot_sha256",
    "current_content_sha256",
    "baseline_policy_sha256",
    "current_policy_sha256",
    "history_complete",
    "history_commits_inspected",
)
_SUMMARY_FIELDS = (
    "complete",
    "unscannable",
    "direct",
    "inherited",
    "exempt",
    "uncovered",
    "total",
    "unimplemented_requirements",
    "policy_events",
    "acknowledged_policy_events",
    "drift_events",
    "acknowledged_drift_events",
    "stale_doc_trends",
    "direct_rate",
    "accounted_rate",
)
_DEFINITION_FIELDS = (
    "definition_id",
    "path",
    "structural_locator",
    "qualname",
    "kind",
    "role",
    "start_line",
    "end_line",
    "tree",
    "classification",
    "changed",
    "source_projection_sha256",
    "governing_edge_ids",
    "matching_exemption_ids",
)
_REQUIREMENT_FIELDS = (
    "requirement_id",
    "path",
    "section_id",
    "rung",
    "implementation_state",
    "owner_definition_ids",
)
_EXEMPTION_FIELDS = (
    "exemption_id",
    "origin",
    "path",
    "line",
    "selector",
    "reason",
    "matched_definition_ids",
    "state",
)
_TREE_FIELDS = (
    "root",
    "role",
    "direct",
    "inherited",
    "exempt",
    "uncovered",
    "total",
    "direct_rate",
    "accounted_rate",
    "complete",
)
_FLOOR_FIELDS = (
    "scope",
    "direct",
    "inherited",
    "exempt",
    "uncovered",
    "total",
    "direct_rate",
    "accounted_rate",
    "direct_target",
    "accounted_target",
    "passes",
)
_UNSCANNABLE_FIELDS = ("path", "role", "issue_identities")
_ISSUE_IDENTITY_FIELDS = ("code", "path", "line")
_POLICY_EVENT_FIELDS = (
    "event_id",
    "key",
    "baseline_value",
    "current_value",
    "parent_commit",
    "transition_commit",
    "acknowledged",
    "acknowledgment_commit",
    "acknowledgment_reason",
)
_DRIFT_EVENT_FIELDS = (
    "event_id",
    "edge_id",
    "requirement_id",
    "definition_id",
    "parent_commit",
    "transition_commit",
    "base_projection_sha256",
    "current_projection_sha256",
    "acknowledged",
    "acknowledgment_commit",
    "acknowledgment_reason",
    "synthetic_current",
)
_TREND_FIELDS = (
    "edge_id",
    "section_change_commit",
    "unacknowledged_event_count",
    "last_event_commit",
    "history_complete",
    "commits_inspected",
)
_ISSUE_FIELDS = (
    "code",
    "severity",
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


class CoverageReportError(ValueError):
    """A coverage artifact violated its closed schema or content binding."""


def build_coverage_report(
    result: IntentCoverageResult,
    *,
    profile: str,
    repo_root: str,
    mode: Literal["report", "ratchet"],
    inherited_counts: bool,
    issues: tuple[Issue, ...],
    floors: tuple[CoverageFloorResult, ...] = (),
    unscannable_files: tuple[CoverageUnscannableFile, ...] = (),
    baseline: GitBaselineMetadata | None = None,
    changed_definition_ids: frozenset[str] = frozenset(),
    policy_events: tuple[PolicyEvent, ...] = (),
    drift_events: tuple[DriftEvent, ...] = (),
    stale_doc_trends: tuple[StaleDocTrend, ...] = (),
    spec_growth: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build and validate one closed coverage report."""

    policy_events = tuple(sorted(policy_events, key=lambda item: item.event_id))
    drift_events = tuple(sorted(drift_events, key=lambda item: item.event_id))
    payload: dict[str, Any] = {
        "artifact": _ARTIFACT,
        "schema_version": _SCHEMA_VERSION,
        "profile": profile,
        "repo_root": repo_root,
        "mode": mode,
        "metric_identity": {
            "id": "intent-coverage-definition-v1",
            "algorithm_version": 1,
            "direct_numerator": "direct",
            "direct_denominator": "total",
            "accounted_numerator": "direct+exempt+inherited_when_enabled",
            "accounted_denominator": "total",
        },
        "baseline": None if baseline is None else dataclasses.asdict(baseline),
        "summary": _summary_row(result.summary, inherited_counts=inherited_counts),
        "trees": _tree_rows(
            result.definitions,
            inherited_counts=inherited_counts,
            unscannable_files=unscannable_files,
        ),
        "floors": _floor_rows(floors),
        "unscannable_files": _unscannable_rows(unscannable_files),
        "definitions": [
            _definition_row(
                item,
                changed=(
                    item.definition.definition_id in changed_definition_ids
                    if mode == "ratchet"
                    else None
                ),
            )
            for item in result.definitions
        ],
        "worklist": list(result.worklist),
        "requirements": [
            {
                "requirement_id": item.requirement_id,
                "path": item.path,
                "section_id": item.section_id,
                "rung": item.rung,
                "implementation_state": item.implementation_state,
                "owner_definition_ids": list(item.owner_definition_ids),
            }
            for item in result.requirements
        ],
        "exemptions": [
            {
                "exemption_id": item.exemption_id,
                "origin": item.origin,
                "path": item.path,
                "line": item.line,
                "selector": item.selector,
                "reason": item.reason,
                "matched_definition_ids": list(item.matched_definition_ids),
                "state": item.state,
            }
            for item in result.exemptions
        ],
        "policy_events": [_policy_event_row(item) for item in policy_events],
        "drift_events": [_drift_event_row(item) for item in drift_events],
        "stale_doc_trends": [_trend_row(item) for item in stale_doc_trends],
        "spec_growth": spec_growth
        or {
            "changed_sections": 0,
            "utf8_byte_delta": 0,
            "requirement_ids": [],
        },
        "issues": _issue_rows(issues),
    }
    payload["summary"]["unimplemented_requirements"] = sum(
        item.implementation_state != "implemented"
        for item in result.requirements
        if item.rung == "active"
    )
    payload["summary"]["complete"] = not unscannable_files
    payload["summary"]["unscannable"] = len(unscannable_files)
    payload["summary"]["policy_events"] = len(policy_events)
    payload["summary"]["acknowledged_policy_events"] = sum(
        item.acknowledged is True for item in policy_events
    )
    payload["summary"]["drift_events"] = len(drift_events)
    payload["summary"]["acknowledged_drift_events"] = sum(
        item.acknowledged is True for item in drift_events
    )
    payload["summary"]["stale_doc_trends"] = len(stale_doc_trends)
    payload["report_sha256"] = _report_hash(payload)
    validate_coverage_report(
        payload,
        source_result=result,
        inherited_counts=inherited_counts,
        floors=floors,
        unscannable_files=unscannable_files,
        issues=issues,
        baseline=baseline,
        changed_definition_ids=changed_definition_ids,
        policy_events=policy_events,
        drift_events=drift_events,
        stale_doc_trends=stale_doc_trends,
        spec_growth=spec_growth,
    )
    return payload


def render_coverage_json(
    payload: dict[str, Any],
    *,
    source_result: IntentCoverageResult,
    inherited_counts: bool,
    floors: tuple[CoverageFloorResult, ...] = (),
    unscannable_files: tuple[CoverageUnscannableFile, ...] = (),
    issues: tuple[Issue, ...] = (),
    baseline: GitBaselineMetadata | None = None,
    changed_definition_ids: frozenset[str] = frozenset(),
    policy_events: tuple[PolicyEvent, ...] = (),
    drift_events: tuple[DriftEvent, ...] = (),
    stale_doc_trends: tuple[StaleDocTrend, ...] = (),
    spec_growth: dict[str, Any] | None = None,
) -> str:
    """Render stable human-readable JSON after validating its content binding."""

    validate_coverage_report(
        payload,
        source_result=source_result,
        inherited_counts=inherited_counts,
        floors=floors,
        unscannable_files=unscannable_files,
        issues=issues,
        baseline=baseline,
        changed_definition_ids=changed_definition_ids,
        policy_events=policy_events,
        drift_events=drift_events,
        stale_doc_trends=stale_doc_trends,
        spec_growth=spec_growth,
    )
    return json.dumps(payload, indent=2, ensure_ascii=True, allow_nan=False) + "\n"


def _require_string(value: Any, label: str, *, nonblank: bool = False) -> str:
    if not isinstance(value, str) or (nonblank and not value.strip()):
        raise CoverageReportError(f"coverage {label} must be a string")
    return value


def _require_boolean(value: Any, label: str) -> bool:
    if type(value) is not bool:
        raise CoverageReportError(f"coverage {label} must be a boolean")
    return value


def _require_integer(
    value: Any,
    label: str,
    *,
    minimum: int | None = None,
) -> int:
    if type(value) is not int or (minimum is not None and value < minimum):
        qualifier = (
            "nonnegative " if minimum == 0 else "positive " if minimum == 1 else ""
        )
        raise CoverageReportError(f"coverage {label} must be a {qualifier}integer")
    return value


def _require_rate(
    value: Any,
    label: str,
    *,
    nullable: bool = True,
) -> float | int | None:
    if value is None and nullable:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= 1
    ):
        raise CoverageReportError(f"coverage {label} must be a finite number in [0,1]")
    return value


def _require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not is_prefixed_sha256(value):
        raise CoverageReportError(f"coverage {label} must be a sha256 token")
    return value


def _require_git_oid(
    value: Any,
    label: str,
    *,
    expected_length: int | None = None,
) -> str:
    if not isinstance(value, str) or len(value) not in (40, 64):
        raise CoverageReportError(f"coverage {label} must be a lowercase Git object ID")
    try:
        decoded = bytes.fromhex(value)
    except ValueError as error:
        raise CoverageReportError(
            f"coverage {label} must be a lowercase Git object ID"
        ) from error
    if decoded.hex() != value or (
        expected_length is not None and len(value) != expected_length
    ):
        raise CoverageReportError(f"coverage {label} must be a lowercase Git object ID")
    return value


def _require_nullable_git_oid(
    value: Any,
    label: str,
    *,
    expected_length: int,
) -> str | None:
    if value is None:
        return None
    return _require_git_oid(value, label, expected_length=expected_length)


def _require_canonical_path(
    value: Any,
    label: str,
    *,
    allow_dot: bool = False,
) -> str:
    path = _require_string(value, label, nonblank=True)
    canonical = canonical_repository_path(path)
    if (
        canonical is None
        or canonical.canonical != path
        or (not allow_dot and path == ".")
    ):
        raise CoverageReportError(f"coverage {label} must be a canonical path")
    return path


def _require_string_array(
    value: Any,
    label: str,
    *,
    sha256: bool = False,
    nonblank: bool = False,
    sorted_unique: bool = True,
) -> list[str]:
    if not isinstance(value, list):
        raise CoverageReportError(f"coverage {label} must be an array")
    for item in value:
        if sha256:
            _require_sha256(item, label)
        else:
            _require_string(item, label, nonblank=nonblank)
    if sorted_unique and value != sorted(set(value)):
        raise CoverageReportError(f"coverage {label} must be sorted and unique")
    return value


def _require_json_value(value: Any, label: str) -> None:
    if value is None or type(value) in (bool, int) or isinstance(value, str):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CoverageReportError(f"coverage {label} must be finite JSON")
        return
    if isinstance(value, list):
        for item in value:
            _require_json_value(item, label)
        return
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        for item in value.values():
            _require_json_value(item, label)
        return
    raise CoverageReportError(f"coverage {label} must be a canonical JSON value")


def _validate_acknowledgment(
    row: dict[str, Any],
    *,
    label: str,
    transition_commit: str | None,
    oid_length: int,
) -> None:
    acknowledged = _require_boolean(row["acknowledged"], f"{label} acknowledged")
    acknowledgment_commit = _require_nullable_git_oid(
        row["acknowledgment_commit"],
        f"{label} acknowledgment_commit",
        expected_length=oid_length,
    )
    reason = row["acknowledgment_reason"]
    if reason is not None:
        _require_string(reason, f"{label} acknowledgment_reason", nonblank=True)
    if acknowledged:
        if (
            transition_commit is None
            or acknowledgment_commit != transition_commit
            or reason is None
        ):
            raise CoverageReportError(
                f"coverage {label} acknowledgment state is invalid"
            )
    elif acknowledgment_commit is not None or reason is not None:
        raise CoverageReportError(f"coverage {label} acknowledgment state is invalid")


def _validate_issue_row(row: dict[str, Any]) -> None:
    _require_fields(row, _ISSUE_FIELDS, "issue")
    for key in ("code", "path", "message", "short_code"):
        _require_string(row[key], f"issue {key}")
    if not isinstance(row["severity"], str) or row["severity"] not in {
        "error",
        "warning",
        "info",
    }:
        raise CoverageReportError("coverage issue severity is invalid")
    if row["line"] is not None:
        _require_integer(row["line"], "issue line", minimum=1)
    for key in ("section_id", "symbol", "context", "invariant_id"):
        if row[key] is not None:
            _require_string(row[key], f"issue {key}")
    if row["default_severity"] is not None and (
        not isinstance(row["default_severity"], str)
        or row["default_severity"] not in {"error", "warning", "info"}
    ):
        raise CoverageReportError("coverage issue default_severity is invalid")


def _issue_rows(issues: tuple[Issue, ...]) -> list[dict[str, Any]]:
    rows = [dataclasses.asdict(item) for item in issues]
    for row in rows:
        _validate_issue_row(row)
    return [dataclasses.asdict(item) for item in sorted(issues, key=issue_sort_key)]


class _CoverageReportValidator:
    """Validate schema sections in their contractually ordered error sequence."""

    def __init__(
        self,
        payload: dict[str, Any],
        *,
        source_result: IntentCoverageResult,
        inherited_counts: bool,
        floors: tuple[CoverageFloorResult, ...],
        unscannable_files: tuple[CoverageUnscannableFile, ...],
        issues: tuple[Issue, ...],
        baseline: GitBaselineMetadata | None,
        changed_definition_ids: frozenset[str],
        policy_events: tuple[PolicyEvent, ...],
        drift_events: tuple[DriftEvent, ...],
        stale_doc_trends: tuple[StaleDocTrend, ...],
        spec_growth: dict[str, Any] | None,
    ) -> None:
        self.payload = payload
        self.source_result = source_result
        self.inherited_counts = inherited_counts
        self.floors = floors
        self.unscannable_files = unscannable_files
        self.issues = issues
        self.baseline = baseline
        self.changed_definition_ids = changed_definition_ids
        self.policy_events = policy_events
        self.drift_events = drift_events
        self.stale_doc_trends = stale_doc_trends
        self.spec_growth = spec_growth
        self.oid_length: int | None = None
        self.event_oid_length = 40
        self.definitions: list[dict[str, Any]] = []
        self.definition_ids: set[str] = set()
        self.definition_by_id: dict[str, dict[str, Any]] = {}
        self.worklist: list[str] = []
        self.summary: dict[str, Any] = {}
        self.exemptions: list[dict[str, Any]] = []
        self.exemption_ids: set[str] = set()
        self.requirements: list[dict[str, Any]] = []
        self.requirement_ids: set[str] = set()
        self.issue_rows: list[dict[str, Any]] = []
        self.unscannable_rows: list[dict[str, Any]] = []
        self.policy_rows: list[dict[str, Any]] = []
        self.drift_rows: list[dict[str, Any]] = []
        self.trend_rows: list[dict[str, Any]] = []

    def validate(self) -> None:
        self.policy_events = tuple(
            sorted(self.policy_events, key=lambda item: item.event_id)
        )
        self.drift_events = tuple(
            sorted(self.drift_events, key=lambda item: item.event_id)
        )
        self.validate_envelope()
        self.validate_metric_identity()
        self.validate_definitions()
        self.validate_worklist()
        self.validate_summary()
        self.validate_exemptions()
        self.validate_requirements()
        self.validate_issues()
        self.validate_trees()
        self.validate_floors()
        self.validate_unscannable_files()
        self.validate_git_events()
        self.validate_aggregates_and_growth()
        self.validate_source_facts()
        self.validate_report_hash()

    def validate_envelope(self) -> None:
        payload = self.payload
        if not isinstance(payload, dict) or tuple(payload) != _TOP_LEVEL_FIELDS:
            raise CoverageReportError(
                "coverage report has unknown, missing, or unordered keys"
            )
        if (
            payload.get("artifact") != _ARTIFACT
            or type(payload.get("schema_version")) is not int
            or payload.get("schema_version") != 1
        ):
            raise CoverageReportError("coverage report identity is invalid")
        _require_string(payload["profile"], "profile", nonblank=True)
        _require_string(payload["repo_root"], "repo_root", nonblank=True)
        if not isinstance(payload.get("mode"), str) or payload["mode"] not in {
            "report",
            "ratchet",
        }:
            raise CoverageReportError("coverage report mode is invalid")
        if payload["mode"] == "report" and payload.get("baseline") is not None:
            raise CoverageReportError("report mode baseline must be null")
        if payload["mode"] == "ratchet" and payload.get("baseline") is None:
            raise CoverageReportError("ratchet mode baseline must be non-null")
        if payload["baseline"] is not None:
            self.oid_length = self.validate_baseline(payload["baseline"])

    @staticmethod
    def validate_baseline(baseline_row: dict[str, Any]) -> int:
        _require_fields(baseline_row, _BASELINE_FIELDS, "baseline")
        _require_string(
            baseline_row["configured_ref"],
            "baseline configured_ref",
            nonblank=True,
        )
        resolved_commit = _require_git_oid(
            baseline_row["resolved_commit"],
            "baseline resolved_commit",
        )
        oid_length = len(resolved_commit)
        _require_git_oid(
            baseline_row["merge_base"],
            "baseline merge_base",
            expected_length=oid_length,
        )
        for key in (
            "current_snapshot_sha256",
            "current_content_sha256",
            "baseline_policy_sha256",
            "current_policy_sha256",
        ):
            _require_sha256(baseline_row[key], f"baseline {key}")
        _require_boolean(
            baseline_row["history_complete"],
            "baseline history_complete",
        )
        _require_integer(
            baseline_row["history_commits_inspected"],
            "baseline history_commits_inspected",
            minimum=0,
        )
        return oid_length

    def validate_metric_identity(self) -> None:
        metric_identity = self.payload["metric_identity"]
        _require_fields(metric_identity, _METRIC_FIELDS, "metric_identity")
        if type(metric_identity["algorithm_version"]) is not int or metric_identity != {
            "id": "intent-coverage-definition-v1",
            "algorithm_version": 1,
            "direct_numerator": "direct",
            "direct_denominator": "total",
            "accounted_numerator": "direct+exempt+inherited_when_enabled",
            "accounted_denominator": "total",
        }:
            raise CoverageReportError("coverage metric_identity is invalid")

    def validate_definitions(self) -> None:
        definitions = self.payload["definitions"]
        if not isinstance(definitions, list):
            raise CoverageReportError("coverage definitions must be an array")
        self.definitions = definitions
        previous_key: tuple[str, str] | None = None
        for row in definitions:
            path, locator = self.validate_definition_row(row)
            definition_key = (path, locator)
            if previous_key is not None and definition_key < previous_key:
                raise CoverageReportError("coverage definitions are not canonical")
            previous_key = definition_key
            expected_id = _stable_id(["intent-definition-v1", path, locator])
            if row["definition_id"] != expected_id:
                raise CoverageReportError("coverage definition_id is invalid")
            if row["definition_id"] in self.definition_ids:
                raise CoverageReportError("coverage definition_id is duplicate")
            self.definition_ids.add(row["definition_id"])
            self.definition_by_id[row["definition_id"]] = row
            self.validate_definition_classification(row)

    @staticmethod
    def validate_definition_row(row: dict[str, Any]) -> tuple[str, str]:
        _require_fields(row, _DEFINITION_FIELDS, "definition")
        path = _require_canonical_path(row["path"], "definition path")
        locator = _require_string(
            row["structural_locator"],
            "definition structural_locator",
            nonblank=True,
        )
        kind = row["kind"]
        if not isinstance(kind, str) or kind not in {
            "module",
            "class",
            "function",
            "async_function",
            "method",
            "async_method",
        }:
            raise CoverageReportError("coverage definition kind is invalid")
        qualname = row["qualname"]
        if qualname is None:
            if kind != "module" or not locator.startswith("python-module-path:"):
                raise CoverageReportError("coverage definition qualname is invalid")
        else:
            _require_string(qualname, "definition qualname", nonblank=True)
        _require_canonical_path(row["tree"], "definition tree", allow_dot=True)
        _require_sha256(
            row["source_projection_sha256"],
            "definition source_projection_sha256",
        )
        if row["changed"] is not None:
            _require_boolean(row["changed"], "definition changed")
        for key_name in ("governing_edge_ids", "matching_exemption_ids"):
            _require_string_array(
                row[key_name],
                f"definition {key_name}",
                sha256=True,
            )
        return path, locator

    @staticmethod
    def validate_definition_classification(row: dict[str, Any]) -> None:
        if not isinstance(row["classification"], str) or row["classification"] not in {
            "direct",
            "inherited",
            "exempt",
            "uncovered",
        }:
            raise CoverageReportError("coverage definition classification is invalid")
        if not isinstance(row["role"], str) or row["role"] not in {
            "production",
            "test",
        }:
            raise CoverageReportError("coverage definition role is invalid")
        if (
            isinstance(row["start_line"], bool)
            or not isinstance(row["start_line"], int)
            or row["start_line"] < 1
            or isinstance(row["end_line"], bool)
            or not isinstance(row["end_line"], int)
            or row["end_line"] < row["start_line"]
        ):
            raise CoverageReportError("coverage definition coordinates are invalid")

    def validate_worklist(self) -> None:
        self.worklist = _require_string_array(
            self.payload["worklist"],
            "worklist",
            sha256=True,
            sorted_unique=False,
        )
        expected_worklist = [
            row["definition_id"]
            for row in sorted(
                (
                    item
                    for item in self.definitions
                    if item["classification"] == "uncovered"
                ),
                key=lambda item: (
                    0 if item["role"] == "production" else 1,
                    item["path"],
                    item["structural_locator"],
                ),
            )
        ]
        if self.worklist != expected_worklist:
            raise CoverageReportError(
                "coverage worklist does not match uncovered definitions"
            )

    def validate_summary(self) -> None:
        summary = self.payload["summary"]
        _require_fields(summary, _SUMMARY_FIELDS, "summary")
        self.summary = summary
        _require_boolean(summary["complete"], "summary complete")
        for name in (
            "unscannable",
            "direct",
            "inherited",
            "exempt",
            "uncovered",
            "total",
            "unimplemented_requirements",
            "policy_events",
            "acknowledged_policy_events",
            "drift_events",
            "acknowledged_drift_events",
            "stale_doc_trends",
        ):
            _require_integer(summary[name], f"summary {name}", minimum=0)
        _require_rate(summary["direct_rate"], "summary direct_rate")
        _require_rate(summary["accounted_rate"], "summary accounted_rate")
        counts = {
            name: sum(row["classification"] == name for row in self.definitions)
            for name in ("direct", "inherited", "exempt", "uncovered")
        }
        for name, value in (*counts.items(), ("total", len(self.definitions))):
            if summary[name] != value:
                raise CoverageReportError(f"coverage summary {name} is invalid")
        if summary["direct_rate"] != _rate(counts["direct"], len(self.definitions)):
            raise CoverageReportError("coverage summary direct_rate is invalid")
        expected_accounted = (
            counts["direct"]
            + counts["exempt"]
            + (counts["inherited"] if self.inherited_counts else 0)
        )
        if summary["accounted_rate"] != _rate(
            expected_accounted,
            len(self.definitions),
        ):
            raise CoverageReportError("coverage summary accounted_rate is invalid")

    def validate_exemptions(self) -> None:
        exemptions = self.payload["exemptions"]
        if not isinstance(exemptions, list):
            raise CoverageReportError("coverage exemptions must be an array")
        self.exemptions = exemptions
        for row in exemptions:
            exemption_id = self.validate_exemption_row(row)
            if exemption_id in self.exemption_ids:
                raise CoverageReportError("coverage exemption_id is duplicate")
            self.exemption_ids.add(exemption_id)
            if (
                row["matched_definition_ids"]
                != sorted(set(row["matched_definition_ids"]))
                or not set(row["matched_definition_ids"]) <= self.definition_ids
            ):
                raise CoverageReportError("coverage exemption join is invalid")
            if not isinstance(row["state"], str) or row["state"] not in {
                "used",
                "overlap_only",
                "unused",
            }:
                raise CoverageReportError("coverage exemption state is invalid")
        if [row["exemption_id"] for row in exemptions] != sorted(self.exemption_ids):
            raise CoverageReportError("coverage exemptions are not canonical")
        for row in self.definitions:
            if not set(row["matching_exemption_ids"]) <= self.exemption_ids:
                raise CoverageReportError(
                    "coverage definition exemption join is dangling"
                )

    @staticmethod
    def validate_exemption_row(row: dict[str, Any]) -> str:
        _require_fields(row, _EXEMPTION_FIELDS, "exemption")
        origin = row["origin"]
        if not isinstance(origin, str) or origin not in {
            "inline",
            "config_path",
            "config_glob",
        }:
            raise CoverageReportError("coverage exemption origin is invalid")
        path = _require_string(row["path"], "exemption path")
        if origin == "inline":
            path = _require_canonical_path(path, "exemption path")
        line = row["line"]
        if line is not None:
            _require_integer(line, "exemption line", minimum=1)
        selector = _require_string(
            row["selector"],
            "exemption selector",
            nonblank=True,
        )
        reason = _require_string(row["reason"], "exemption reason", nonblank=True)
        _require_string_array(
            row["matched_definition_ids"],
            "exemption matched_definition_ids",
            sha256=True,
        )
        expected_id = _stable_id(
            ["intent-exemption-v1", "inline", path, line, reason]
            if origin == "inline"
            else ["intent-exemption-v1", origin, selector]
        )
        if row["exemption_id"] != expected_id:
            raise CoverageReportError("coverage exemption_id is invalid")
        return expected_id

    def validate_requirements(self) -> None:
        requirements = self.payload["requirements"]
        if not isinstance(requirements, list):
            raise CoverageReportError("coverage requirements must be an array")
        self.requirements = requirements
        previous_key: tuple[str, str] | None = None
        for row in requirements:
            path, section_id = self.validate_requirement_row(row)
            requirement_key = (path, section_id)
            if previous_key is not None and requirement_key < previous_key:
                raise CoverageReportError("coverage requirements are not canonical")
            previous_key = requirement_key
            expected_id = _stable_id(["intent-requirement-v1", path, section_id])
            if (
                row["requirement_id"] != expected_id
                or expected_id in self.requirement_ids
            ):
                raise CoverageReportError("coverage requirement_id is invalid")
            self.requirement_ids.add(expected_id)
            if not set(row["owner_definition_ids"]) <= self.definition_ids:
                raise CoverageReportError("coverage requirement owner join is dangling")
        active_unimplemented = sum(
            row["rung"] == "active" and row["implementation_state"] != "implemented"
            for row in requirements
        )
        if self.summary["unimplemented_requirements"] != active_unimplemented:
            raise CoverageReportError(
                "coverage summary unimplemented_requirements is invalid"
            )

    @staticmethod
    def validate_requirement_row(row: dict[str, Any]) -> tuple[str, str]:
        _require_fields(row, _REQUIREMENT_FIELDS, "requirement")
        path = _require_canonical_path(row["path"], "requirement path")
        section_id = _require_string(
            row["section_id"],
            "requirement section_id",
            nonblank=True,
        )
        if not isinstance(row["rung"], str) or row["rung"] not in {
            "active",
            "planned",
            "exploratory",
            "meta",
        }:
            raise CoverageReportError("coverage requirement rung is invalid")
        if not isinstance(row["implementation_state"], str) or row[
            "implementation_state"
        ] not in {
            "implemented",
            "absent_mapping",
            "declared_without_live_owner",
        }:
            raise CoverageReportError(
                "coverage requirement implementation_state is invalid"
            )
        _require_string_array(
            row["owner_definition_ids"],
            "requirement owner_definition_ids",
            sha256=True,
        )
        return path, section_id

    def validate_issues(self) -> None:
        issue_rows = self.payload["issues"]
        if not isinstance(issue_rows, list):
            raise CoverageReportError("coverage issues must be an array")
        self.issue_rows = issue_rows
        parsed_issues: list[Issue] = []
        for row in issue_rows:
            _validate_issue_row(row)
            try:
                parsed_issues.append(Issue(**row))
            except (TypeError, ValueError) as exc:
                raise CoverageReportError("coverage issue row is invalid") from exc
        if parsed_issues != sorted(parsed_issues, key=issue_sort_key):
            raise CoverageReportError("coverage issues are not canonical")

    def validate_trees(self) -> None:
        trees = self.payload["trees"]
        if not isinstance(trees, list):
            raise CoverageReportError("coverage trees must be an array")
        previous_key: tuple[str, str] | None = None
        for row in trees:
            root, role = self.validate_tree_identity(row)
            tree_key = (root, role)
            if previous_key is not None and tree_key <= previous_key:
                raise CoverageReportError("coverage trees are not canonical")
            previous_key = tree_key
            self.validate_tree_counts(row)

    @staticmethod
    def validate_tree_identity(row: dict[str, Any]) -> tuple[str, str]:
        _require_fields(row, _TREE_FIELDS, "tree")
        root = _require_canonical_path(row["root"], "tree root", allow_dot=True)
        if not isinstance(row["role"], str) or row["role"] not in {
            "production",
            "test",
        }:
            raise CoverageReportError("coverage tree role is invalid")
        return root, row["role"]

    def validate_tree_counts(self, row: dict[str, Any]) -> None:
        for name in ("direct", "inherited", "exempt", "uncovered", "total"):
            _require_integer(row[name], f"tree {name}", minimum=0)
        if row["total"] != sum(
            row[name] for name in ("direct", "inherited", "exempt", "uncovered")
        ):
            raise CoverageReportError("coverage tree total is invalid")
        _require_rate(row["direct_rate"], "tree direct_rate")
        _require_rate(row["accounted_rate"], "tree accounted_rate")
        if row["direct_rate"] != _rate(row["direct"], row["total"]):
            raise CoverageReportError("coverage tree direct_rate is invalid")
        accounted = (
            row["direct"]
            + row["exempt"]
            + (row["inherited"] if self.inherited_counts else 0)
        )
        if row["accounted_rate"] != _rate(accounted, row["total"]):
            raise CoverageReportError("coverage tree accounted_rate is invalid")
        _require_boolean(row["complete"], "tree complete")

    def validate_floors(self) -> None:
        floor_rows = self.payload["floors"]
        if not isinstance(floor_rows, list):
            raise CoverageReportError("coverage floors must be an array")
        previous_scope: str | None = None
        for row in floor_rows:
            _require_fields(row, _FLOOR_FIELDS, "floor")
            scope = _require_canonical_path(row["scope"], "floor scope", allow_dot=True)
            if previous_scope is not None and scope <= previous_scope:
                raise CoverageReportError("coverage floors are not canonical")
            previous_scope = scope
            self.validate_floor_counts(row)

    def validate_floor_counts(self, row: dict[str, Any]) -> None:
        for name in ("direct", "inherited", "exempt", "uncovered", "total"):
            _require_integer(row[name], f"floor {name}", minimum=0)
        if row["total"] != sum(
            row[name] for name in ("direct", "inherited", "exempt", "uncovered")
        ):
            raise CoverageReportError("coverage floor total is invalid")
        _require_rate(row["direct_rate"], "floor direct_rate")
        _require_rate(row["accounted_rate"], "floor accounted_rate")
        _require_rate(row["direct_target"], "floor direct_target")
        _require_rate(row["accounted_target"], "floor accounted_target")
        _require_boolean(row["passes"], "floor passes")
        if row["direct_rate"] != _rate(row["direct"], row["total"]):
            raise CoverageReportError("coverage floor direct_rate is invalid")
        accounted = (
            row["direct"]
            + row["exempt"]
            + (row["inherited"] if self.inherited_counts else 0)
        )
        if row["accounted_rate"] != _rate(accounted, row["total"]):
            raise CoverageReportError("coverage floor accounted_rate is invalid")
        expected_passes = _meets_report_floor(
            row["direct"],
            row["total"],
            row["direct_target"],
        ) and _meets_report_floor(
            accounted,
            row["total"],
            row["accounted_target"],
        )
        if row["passes"] is not expected_passes:
            raise CoverageReportError("coverage floor passes is invalid")

    def validate_unscannable_files(self) -> None:
        rows = self.payload["unscannable_files"]
        if not isinstance(rows, list):
            raise CoverageReportError("coverage unscannable_files must be an array")
        self.unscannable_rows = rows
        previous_key: tuple[str, str] | None = None
        for row in rows:
            path, role = self.validate_unscannable_identity(row)
            key = (path, role)
            if previous_key is not None and key <= previous_key:
                raise CoverageReportError(
                    "coverage unscannable_files are not canonical"
                )
            previous_key = key
            self.validate_unscannable_issue_identities(row)

    @staticmethod
    def validate_unscannable_identity(row: dict[str, Any]) -> tuple[str, str]:
        _require_fields(row, _UNSCANNABLE_FIELDS, "unscannable_file")
        path = _require_canonical_path(row["path"], "unscannable_file path")
        if not isinstance(row["role"], str) or row["role"] not in {
            "production",
            "test",
        }:
            raise CoverageReportError("coverage unscannable_file role is invalid")
        return path, row["role"]

    @staticmethod
    def validate_unscannable_issue_identities(row: dict[str, Any]) -> None:
        identities = row["issue_identities"]
        if not isinstance(identities, list) or not identities:
            raise CoverageReportError(
                "coverage unscannable_file issue_identities is invalid"
            )
        identity_keys = [
            _validate_unscannable_identity(identity) for identity in identities
        ]
        if identity_keys != sorted(set(identity_keys)):
            raise CoverageReportError(
                "coverage unscannable issue identities are not canonical"
            )

    def validate_git_events(self) -> None:
        self.policy_rows = self.payload["policy_events"]
        self.drift_rows = self.payload["drift_events"]
        self.trend_rows = self.payload["stale_doc_trends"]
        self.validate_source_drift_events()
        for name, rows in (
            ("policy_events", self.policy_rows),
            ("drift_events", self.drift_rows),
            ("stale_doc_trends", self.trend_rows),
        ):
            if not isinstance(rows, list):
                raise CoverageReportError(f"coverage {name} must be an array")
        if (
            self.policy_rows or self.drift_rows or self.trend_rows
        ) and self.oid_length is None:
            raise CoverageReportError("coverage Git-derived facts require a baseline")
        self.event_oid_length = self.oid_length or 40
        self.validate_policy_rows()
        self.validate_drift_rows()
        self.validate_trend_rows()

    def validate_source_drift_events(self) -> None:
        for event in self.drift_events:
            _require_sha256(event.event_id, "drift_event event_id")
            _require_sha256(event.edge_id, "drift_event edge_id")
            _require_sha256(event.requirement_id, "drift_event requirement_id")
            _require_sha256(event.definition_id, "drift_event definition_id")
            requirement = next(
                (
                    item
                    for item in self.requirements
                    if item["requirement_id"] == event.requirement_id
                ),
                None,
            )
            definition = self.definition_by_id.get(event.definition_id)
            if requirement is None or definition is None:
                raise CoverageReportError("coverage drift_event join is dangling")
            edge_id = _stable_id(
                [
                    "intent-edge-v1",
                    requirement["path"],
                    requirement["section_id"],
                    definition["path"],
                    definition["structural_locator"],
                ]
            )
            if event.edge_id != edge_id:
                raise CoverageReportError("coverage drift_event edge_id is invalid")
            self.validate_source_drift_hashes(event)

    @staticmethod
    def validate_source_drift_hashes(event: DriftEvent) -> None:
        hashes = (
            event.before_section_hash,
            event.after_section_hash,
            event.before_mapping_hash,
            event.after_mapping_hash,
            event.base_projection_sha256,
            event.current_projection_sha256,
            event.before_connected_test_hash,
            event.after_connected_test_hash,
        )
        for index, value in enumerate(hashes):
            _require_sha256(value, f"drift_event preimage hash {index}")
        if event.base_projection_sha256 == event.current_projection_sha256:
            raise CoverageReportError(
                "coverage drift_event projection hashes did not change"
            )
        if (
            event.before_section_hash != event.after_section_hash
            or event.before_mapping_hash != event.after_mapping_hash
            or event.before_connected_test_hash != event.after_connected_test_hash
        ):
            raise CoverageReportError("coverage drift_event predicate is invalid")
        expected_id = _stable_id(
            [
                "intent-drift-event-v1",
                event.edge_id,
                event.parent_commit,
                event.before_section_hash,
                event.after_section_hash,
                event.before_mapping_hash,
                event.after_mapping_hash,
                event.base_projection_sha256,
                event.current_projection_sha256,
                event.before_connected_test_hash,
                event.after_connected_test_hash,
            ]
        )
        if event.event_id != expected_id:
            raise CoverageReportError("coverage drift_event event_id is invalid")

    def validate_policy_rows(self) -> None:
        previous_id: str | None = None
        for row in self.policy_rows:
            _require_fields(row, _POLICY_EVENT_FIELDS, "policy_event")
            event_id = _require_sha256(row["event_id"], "policy_event event_id")
            if previous_id is not None and event_id <= previous_id:
                raise CoverageReportError("coverage policy_events are not canonical")
            previous_id = event_id
            key = _require_string(row["key"], "policy_event key", nonblank=True)
            _require_json_value(row["baseline_value"], "policy_event baseline_value")
            _require_json_value(row["current_value"], "policy_event current_value")
            parent_commit = _require_git_oid(
                row["parent_commit"],
                "policy_event parent_commit",
                expected_length=self.event_oid_length,
            )
            transition_commit = _require_nullable_git_oid(
                row["transition_commit"],
                "policy_event transition_commit",
                expected_length=self.event_oid_length,
            )
            expected_id = _stable_id(
                [
                    "intent-policy-event-v1",
                    parent_commit,
                    key,
                    row["baseline_value"],
                    row["current_value"],
                ]
            )
            if event_id != expected_id:
                raise CoverageReportError("coverage policy_event event_id is invalid")
            _validate_acknowledgment(
                row,
                label="policy_event",
                transition_commit=transition_commit,
                oid_length=self.event_oid_length,
            )

    def validate_drift_rows(self) -> None:
        previous_id: str | None = None
        for row in self.drift_rows:
            _require_fields(row, _DRIFT_EVENT_FIELDS, "drift_event")
            event_id = _require_sha256(row["event_id"], "drift_event event_id")
            if previous_id is not None and event_id <= previous_id:
                raise CoverageReportError("coverage drift_events are not canonical")
            previous_id = event_id
            self.validate_drift_row(row)

    def validate_drift_row(self, row: dict[str, Any]) -> None:
        edge_id = _require_sha256(row["edge_id"], "drift_event edge_id")
        requirement_id = _require_sha256(
            row["requirement_id"],
            "drift_event requirement_id",
        )
        definition_id = _require_sha256(
            row["definition_id"],
            "drift_event definition_id",
        )
        requirement = next(
            (
                item
                for item in self.requirements
                if item["requirement_id"] == requirement_id
            ),
            None,
        )
        definition = self.definition_by_id.get(definition_id)
        if requirement is None or definition is None:
            raise CoverageReportError("coverage drift_event join is dangling")
        expected_edge_id = _stable_id(
            [
                "intent-edge-v1",
                requirement["path"],
                requirement["section_id"],
                definition["path"],
                definition["structural_locator"],
            ]
        )
        if edge_id != expected_edge_id:
            raise CoverageReportError("coverage drift_event edge_id is invalid")
        _require_git_oid(
            row["parent_commit"],
            "drift_event parent_commit",
            expected_length=self.event_oid_length,
        )
        transition_commit = _require_nullable_git_oid(
            row["transition_commit"],
            "drift_event transition_commit",
            expected_length=self.event_oid_length,
        )
        base_projection = _require_sha256(
            row["base_projection_sha256"],
            "drift_event base_projection_sha256",
        )
        current_projection = _require_sha256(
            row["current_projection_sha256"],
            "drift_event current_projection_sha256",
        )
        if base_projection == current_projection:
            raise CoverageReportError(
                "coverage drift_event projection hashes did not change"
            )
        synthetic_current = _require_boolean(
            row["synthetic_current"],
            "drift_event synthetic_current",
        )
        if (transition_commit is None) is not synthetic_current:
            raise CoverageReportError(
                "coverage drift_event synthetic transition is invalid"
            )
        _validate_acknowledgment(
            row,
            label="drift_event",
            transition_commit=transition_commit,
            oid_length=self.event_oid_length,
        )

    def validate_trend_rows(self) -> None:
        previous_id: str | None = None
        for row in self.trend_rows:
            _require_fields(row, _TREND_FIELDS, "stale_doc_trend")
            edge_id = _require_sha256(row["edge_id"], "stale_doc_trend edge_id")
            if previous_id is not None and edge_id <= previous_id:
                raise CoverageReportError("coverage stale_doc_trends are not canonical")
            previous_id = edge_id
            _require_nullable_git_oid(
                row["section_change_commit"],
                "stale_doc_trend section_change_commit",
                expected_length=self.event_oid_length,
            )
            _require_integer(
                row["unacknowledged_event_count"],
                "stale_doc_trend unacknowledged_event_count",
                minimum=0,
            )
            _require_nullable_git_oid(
                row["last_event_commit"],
                "stale_doc_trend last_event_commit",
                expected_length=self.event_oid_length,
            )
            _require_boolean(
                row["history_complete"],
                "stale_doc_trend history_complete",
            )
            _require_integer(
                row["commits_inspected"],
                "stale_doc_trend commits_inspected",
                minimum=0,
            )

    def validate_aggregates_and_growth(self) -> None:
        summary = self.summary
        if summary["complete"] != (not self.unscannable_rows) or summary[
            "unscannable"
        ] != len(self.unscannable_rows):
            raise CoverageReportError("coverage completeness aggregate is invalid")
        for rows_name, count_name in (
            ("policy_events", "policy_events"),
            ("drift_events", "drift_events"),
            ("stale_doc_trends", "stale_doc_trends"),
        ):
            if summary[count_name] != len(self.payload[rows_name]):
                raise CoverageReportError(f"coverage summary {count_name} is invalid")
        if summary["acknowledged_policy_events"] != sum(
            bool(row["acknowledged"]) for row in self.payload["policy_events"]
        ) or summary["acknowledged_drift_events"] != sum(
            bool(row["acknowledged"]) for row in self.payload["drift_events"]
        ):
            raise CoverageReportError("coverage acknowledgment aggregate is invalid")
        growth = self.payload["spec_growth"]
        _require_fields(
            growth,
            ("changed_sections", "utf8_byte_delta", "requirement_ids"),
            "spec_growth",
        )
        _require_integer(
            growth["changed_sections"],
            "spec_growth changed_sections",
            minimum=0,
        )
        _require_integer(growth["utf8_byte_delta"], "spec_growth utf8_byte_delta")
        _require_string_array(
            growth["requirement_ids"],
            "spec_growth requirement_ids",
            sha256=True,
        )
        if not set(growth["requirement_ids"]) <= self.requirement_ids:
            raise CoverageReportError("coverage spec_growth join is dangling")
        self.validate_report_mode(growth)

    def validate_report_mode(self, growth: dict[str, Any]) -> None:
        if self.payload["mode"] == "report" and (
            self.payload["policy_events"]
            or self.payload["drift_events"]
            or self.payload["stale_doc_trends"]
            or growth
            != {
                "changed_sections": 0,
                "utf8_byte_delta": 0,
                "requirement_ids": [],
            }
            or any(row["changed"] is not None for row in self.definitions)
        ):
            raise CoverageReportError("report mode contains Git-derived facts")

    def validate_source_facts(self) -> None:
        expected_definitions = [
            _definition_row(
                item,
                changed=(
                    item.definition.definition_id in self.changed_definition_ids
                    if self.payload["mode"] == "ratchet"
                    else None
                ),
            )
            for item in self.source_result.definitions
        ]
        if self.definitions != expected_definitions:
            raise CoverageReportError("coverage definitions differ from source facts")
        if self.worklist != list(self.source_result.worklist):
            raise CoverageReportError("coverage worklist differs from source facts")
        if self.requirements != self.expected_requirements():
            raise CoverageReportError("coverage requirements differ from source facts")
        if self.exemptions != self.expected_exemptions():
            raise CoverageReportError("coverage exemptions differ from source facts")
        if self.payload["trees"] != _tree_rows(
            self.source_result.definitions,
            inherited_counts=self.inherited_counts,
            unscannable_files=self.unscannable_files,
        ):
            raise CoverageReportError("coverage trees differ from source facts")
        if self.payload["floors"] != _floor_rows(self.floors):
            raise CoverageReportError("coverage floors differ from source facts")
        if self.payload["unscannable_files"] != _unscannable_rows(
            self.unscannable_files
        ):
            raise CoverageReportError(
                "coverage unscannable_files differ from source facts"
            )
        self.validate_history_source_facts()

    def validate_history_source_facts(self) -> None:
        expected_baseline = (
            None if self.baseline is None else dataclasses.asdict(self.baseline)
        )
        if self.payload["baseline"] != expected_baseline:
            raise CoverageReportError("coverage baseline differs from source facts")
        if self.payload["policy_events"] != [
            _policy_event_row(item) for item in self.policy_events
        ]:
            raise CoverageReportError("coverage policy_events differ from source facts")
        if self.payload["drift_events"] != [
            _drift_event_row(item) for item in self.drift_events
        ]:
            raise CoverageReportError("coverage drift_events differ from source facts")
        if self.payload["stale_doc_trends"] != [
            _trend_row(item) for item in self.stale_doc_trends
        ]:
            raise CoverageReportError(
                "coverage stale_doc_trends differ from source facts"
            )
        expected_growth = self.spec_growth or {
            "changed_sections": 0,
            "utf8_byte_delta": 0,
            "requirement_ids": [],
        }
        if self.payload["spec_growth"] != expected_growth:
            raise CoverageReportError("coverage spec_growth differs from source facts")
        if self.issues != tuple(
            sorted(self.issues, key=issue_sort_key)
        ) or self.issue_rows != [dataclasses.asdict(item) for item in self.issues]:
            raise CoverageReportError("coverage issues differ from source facts")

    def expected_requirements(self) -> list[dict[str, Any]]:
        return [
            {
                "requirement_id": item.requirement_id,
                "path": item.path,
                "section_id": item.section_id,
                "rung": item.rung,
                "implementation_state": item.implementation_state,
                "owner_definition_ids": list(item.owner_definition_ids),
            }
            for item in self.source_result.requirements
        ]

    def expected_exemptions(self) -> list[dict[str, Any]]:
        return [
            {
                "exemption_id": item.exemption_id,
                "origin": item.origin,
                "path": item.path,
                "line": item.line,
                "selector": item.selector,
                "reason": item.reason,
                "matched_definition_ids": list(item.matched_definition_ids),
                "state": item.state,
            }
            for item in self.source_result.exemptions
        ]

    def validate_report_hash(self) -> None:
        _require_sha256(self.payload["report_sha256"], "report_sha256")
        if self.payload.get("report_sha256") != _report_hash(self.payload):
            raise CoverageReportError("coverage report_sha256 does not match content")


def _validate_unscannable_identity(identity: dict[str, Any]) -> tuple[str, str, int]:
    _require_fields(
        identity,
        _ISSUE_IDENTITY_FIELDS,
        "unscannable issue identity",
    )
    code = _require_string(
        identity["code"],
        "unscannable issue code",
        nonblank=True,
    )
    path = _require_canonical_path(
        identity["path"],
        "unscannable issue path",
    )
    line = identity["line"]
    if line is not None:
        _require_integer(line, "unscannable issue line", minimum=1)
    return code, path, line or 0


def validate_coverage_report(
    payload: dict[str, Any],
    *,
    source_result: IntentCoverageResult,
    inherited_counts: bool,
    floors: tuple[CoverageFloorResult, ...] = (),
    unscannable_files: tuple[CoverageUnscannableFile, ...] = (),
    issues: tuple[Issue, ...] = (),
    baseline: GitBaselineMetadata | None = None,
    changed_definition_ids: frozenset[str] = frozenset(),
    policy_events: tuple[PolicyEvent, ...] = (),
    drift_events: tuple[DriftEvent, ...] = (),
    stale_doc_trends: tuple[StaleDocTrend, ...] = (),
    spec_growth: dict[str, Any] | None = None,
) -> None:
    """Reject closed-schema drift, forged aggregates, and dangling joins."""

    _CoverageReportValidator(
        payload,
        source_result=source_result,
        inherited_counts=inherited_counts,
        floors=floors,
        unscannable_files=unscannable_files,
        issues=issues,
        baseline=baseline,
        changed_definition_ids=changed_definition_ids,
        policy_events=policy_events,
        drift_events=drift_events,
        stale_doc_trends=stale_doc_trends,
        spec_growth=spec_growth,
    ).validate()


def _require_fields(
    value: Any,
    fields: tuple[str, ...],
    label: str,
) -> None:
    if not isinstance(value, dict) or tuple(value) != fields:
        raise CoverageReportError(
            f"coverage {label} has unknown, missing, or unordered keys"
        )


def _stable_id(preimage: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(preimage)).hexdigest()


def _summary_row(
    counts: CoverageCounts,
    *,
    inherited_counts: bool,
) -> dict[str, Any]:
    return {
        "complete": True,
        "unscannable": 0,
        "direct": counts.direct,
        "inherited": counts.inherited,
        "exempt": counts.exempt,
        "uncovered": counts.uncovered,
        "total": counts.total,
        "unimplemented_requirements": 0,
        "policy_events": 0,
        "acknowledged_policy_events": 0,
        "drift_events": 0,
        "acknowledged_drift_events": 0,
        "stale_doc_trends": 0,
        "direct_rate": _rate(counts.direct, counts.total),
        "accounted_rate": _rate(
            counts.direct
            + counts.exempt
            + (counts.inherited if inherited_counts else 0),
            counts.total,
        ),
    }


def _tree_rows(
    definitions: tuple[ClassifiedDefinition, ...],
    *,
    inherited_counts: bool,
    unscannable_files: tuple[CoverageUnscannableFile, ...],
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[ClassifiedDefinition]] = defaultdict(list)
    for item in definitions:
        groups[(item.definition.tree, item.definition.role)].append(item)
    for unscannable in unscannable_files:
        groups.setdefault((unscannable.tree, unscannable.role), [])
    rows: list[dict[str, Any]] = []
    for (root, role), items in sorted(groups.items()):
        counts = {
            name: sum(item.classification == name for item in items)
            for name in ("direct", "inherited", "exempt", "uncovered")
        }
        total = len(items)
        rows.append(
            {
                "root": root,
                "role": role,
                "direct": counts["direct"],
                "inherited": counts["inherited"],
                "exempt": counts["exempt"],
                "uncovered": counts["uncovered"],
                "total": total,
                "direct_rate": _rate(counts["direct"], total),
                "accounted_rate": _rate(
                    counts["direct"]
                    + counts["exempt"]
                    + (counts["inherited"] if inherited_counts else 0),
                    total,
                ),
                "complete": not any(
                    item.tree == root and item.role == role
                    for item in unscannable_files
                ),
            }
        )
    return rows


def _floor_rows(
    floors: tuple[CoverageFloorResult, ...],
) -> list[dict[str, Any]]:
    return [
        {
            "scope": item.scope,
            "direct": item.counts.direct,
            "inherited": item.counts.inherited,
            "exempt": item.counts.exempt,
            "uncovered": item.counts.uncovered,
            "total": item.counts.total,
            "direct_rate": _rate(item.counts.direct, item.counts.total),
            "accounted_rate": _rate(
                item.counts.accounted_numerator,
                item.counts.total,
            ),
            "direct_target": item.direct_target,
            "accounted_target": item.accounted_target,
            "passes": item.passes,
        }
        for item in floors
    ]


def _unscannable_rows(
    files: tuple[CoverageUnscannableFile, ...],
) -> list[dict[str, Any]]:
    return [
        {
            "path": item.path,
            "role": item.role,
            "issue_identities": [
                {"code": code, "path": path, "line": line}
                for code, path, line in item.issue_identities
            ],
        }
        for item in sorted(files, key=lambda row: (row.path, row.role))
    ]


def _definition_row(
    item: ClassifiedDefinition,
    *,
    changed: bool | None,
) -> dict[str, Any]:
    definition = item.definition
    return {
        "definition_id": definition.definition_id,
        "path": definition.path,
        "structural_locator": definition.structural_locator,
        "qualname": definition.qualname,
        "kind": definition.kind,
        "role": definition.role,
        "start_line": definition.start_line,
        "end_line": definition.end_line,
        "tree": definition.tree,
        "classification": item.classification,
        "changed": changed,
        "source_projection_sha256": definition.source_projection_sha256,
        "governing_edge_ids": list(item.governing_edge_ids),
        "matching_exemption_ids": list(item.matching_exemption_ids),
    }


def _policy_event_row(item: PolicyEvent) -> dict[str, Any]:
    return {
        "event_id": item.event_id,
        "key": item.key,
        "baseline_value": item.baseline_value,
        "current_value": item.current_value,
        "parent_commit": item.parent_commit,
        "transition_commit": item.transition_commit,
        "acknowledged": item.acknowledged,
        "acknowledgment_commit": item.acknowledgment_commit,
        "acknowledgment_reason": item.acknowledgment_reason,
    }


def _drift_event_row(item: DriftEvent) -> dict[str, Any]:
    return {
        "event_id": item.event_id,
        "edge_id": item.edge_id,
        "requirement_id": item.requirement_id,
        "definition_id": item.definition_id,
        "parent_commit": item.parent_commit,
        "transition_commit": item.transition_commit,
        "base_projection_sha256": item.base_projection_sha256,
        "current_projection_sha256": item.current_projection_sha256,
        "acknowledged": item.acknowledged,
        "acknowledgment_commit": item.acknowledgment_commit,
        "acknowledgment_reason": item.acknowledgment_reason,
        "synthetic_current": item.synthetic_current,
    }


def _trend_row(item: StaleDocTrend) -> dict[str, Any]:
    return {
        "edge_id": item.edge_id,
        "section_change_commit": item.section_change_commit,
        "unacknowledged_event_count": item.unacknowledged_event_count,
        "last_event_commit": item.last_event_commit,
        "history_complete": item.history_complete,
        "commits_inspected": item.commits_inspected,
    }


def _rate(numerator: int, denominator: int) -> float | None:
    _require_integer(numerator, "rate numerator", minimum=0)
    _require_integer(denominator, "rate denominator", minimum=0)
    if numerator > denominator:
        raise CoverageReportError("coverage rate numerator exceeds denominator")
    if denominator == 0:
        return None
    value = (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("0.000001"),
        rounding=ROUND_HALF_EVEN,
    )
    return float(value)


def _meets_report_floor(
    numerator: int,
    denominator: int,
    target: float | int | None,
) -> bool:
    if target is None:
        return True
    if denominator == 0:
        return Decimal(str(target)) == 0
    return Decimal(numerator) >= Decimal(str(target)) * Decimal(denominator)


def _report_hash(payload: dict[str, Any]) -> str:
    preimage = {key: value for key, value in payload.items() if key != "report_sha256"}
    try:
        encoded = canonical_json_bytes(preimage)
    except (TypeError, ValueError) as error:
        raise CoverageReportError(
            "coverage report contains a non-finite or invalid JSON value"
        ) from error
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
