"""Closed semantic packet and analysis sidecar report contracts.

Spec: docs/specs/02-backstitch-core.md [SC-5], [SC-7]
Spec: docs/specs/06-semantic-gates.md [SEM-7]
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
import tempfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from backstitch import __version__
from backstitch.artifact_contracts import ValidatedSemanticPacket, load_packets_bytes
from backstitch.canonical import canonical_json_bytes, lf_line_count, lf_split
from backstitch.contract_validation import make_validators
from backstitch.diagnostics import default_level_for, default_registry, short_code_for
from backstitch.grammar import is_valid_suppression_reference
from backstitch.models import ISSUE_CODES, issue_sort_key
from backstitch.obligation_runtime import ALGORITHMS, ObligationRuntime
from backstitch.semantic_identity import InferenceIdentity
from backstitch.semantic_packets import model_request_bytes

PacketReportKind = Literal["section", "invariant", "suppression", "all"]

_PACKET_REPORT_V1_FIELDS = frozenset(
    {
        "schema_version",
        "artifact",
        "packet_jsonl_sha256",
        "kind",
        "eligible_counts",
        "emitted_counts",
        "packet_warning_count",
        "prompt_byte_count",
        "packets",
    }
)
_PACKET_REPORT_V2_FIELDS = frozenset(
    {
        "schema_version",
        "artifact",
        "packet_schema_version",
        "scope",
        "source_snapshot",
        "derivation_contract",
        "packet_jsonl_sha256",
        "packet_count",
        "packet_bytes",
        "selection_status",
        "readiness_counts",
        "alignment_audit",
        "deterministic_issues",
        "packets",
        "packet_report_content_sha256",
        "tool_version",
        "created_at",
    }
)
_PACKET_REPORT_V3_FIELDS = frozenset(
    {
        "schema_version",
        "artifact",
        "packet_schema_versions",
        "scope",
        "source_snapshot",
        "derivation_contract",
        "packet_jsonl_sha256",
        "packet_count",
        "packet_bytes",
        "selection_status",
        "readiness_counts",
        "alignment_audit",
        "deterministic_issues",
        "kind_counts",
        "packets",
        "packet_report_content_sha256",
        "tool_version",
        "created_at",
    }
)
_COUNT_FIELDS = frozenset({"section", "invariant"})
_CURRENT_COUNT_FIELDS = frozenset({"section", "invariant", "suppression"})
_PACKET_IDENTITY_FIELDS = frozenset({"packet_id", "packet_hash"})
_ANALYSIS_REPORT_V1_FIELDS = frozenset(
    {
        "schema_version",
        "artifact",
        "packet_jsonl_sha256",
        "result_jsonl_sha256",
        "status",
        "analysis_exit_code",
        "packet_count",
        "result_count",
        "packet_warning_count",
        "packet_warning_debt",
        "candidate_debt",
        "cache_hits",
        "cache_misses",
        "provider_calls",
        "prompt_byte_count",
        "elapsed_milliseconds",
        "estimated_cost_microusd",
        "cost_rate_source",
        "effective_policy_layers",
        "semantic_diagnostics",
        "unused_dispositions",
        "problems",
    }
)
_ANALYSIS_REPORT_V3_FIELDS = frozenset(
    {
        "schema_version",
        "artifact",
        "scope",
        "semantic_status",
        "artifact_integrity",
        "artifact_currentness",
        "source_provenance",
        "source_snapshot",
        "packet_report_content_sha256",
        "alignment_summary",
        "alignment_audit",
        "deterministic_issues",
        "packet_jsonl_sha256",
        "result_jsonl_sha256",
        "status",
        "analysis_exit_code",
        "packet_count",
        "result_count",
        "packet_warning_count",
        "packet_warning_debt",
        "finding_debt",
        "cache_hits",
        "cache_misses",
        "provider_calls",
        "prompt_byte_count",
        "elapsed_milliseconds",
        "estimated_cost_microusd",
        "cost_rate_source",
        "effective_policy_layers",
        "semantic_diagnostics",
        "unused_dispositions",
        "problems",
        "verification",
    }
)
_ANALYSIS_REPORT_V4_FIELDS = _ANALYSIS_REPORT_V3_FIELDS | frozenset(
    {"packet_schema_versions", "kind_counts"}
)
_PROBLEM_V1_FIELDS = frozenset({"packet_id", "stage", "code", "message"})
_PROBLEM_V3_FIELDS = frozenset(
    {"packet_id", "obligation_id", "stage", "code", "message", "details"}
)
_WARNING_DEBT_FIELDS = frozenset({"packet_id", "warnings"})
_FINDING_DEBT_FIELDS = frozenset(
    {"code", "packet_id", "packet_hash", "finding_hash", "verification_state"}
)
_DISPOSITION_FIELDS = frozenset(
    {"code", "packet_id", "packet_hash", "finding_hash", "status", "reason"}
)
_DIAGNOSTIC_FIELDS = frozenset(
    {
        "code",
        "short_code",
        "classification",
        "packet_kind",
        "packet_id",
        "packet_hash",
        "finding_hash",
        "verification_state",
        "evidence",
        "default_severity",
        "severity",
        "summary",
        "rationale",
        "analysis_key",
        "winning_policy_rule",
    }
)
_EVIDENCE_FIELDS = frozenset(
    {"role", "path", "start_line", "end_line", "excerpt", "excerpt_sha256"}
)
_WINNING_RULE_FIELDS = frozenset({"source", "position", "selector", "level"})
_SEMANTIC_CODE_DATA = {
    "SEMANTIC_CONFIRMED_MISMATCH": ("BSA001", "confirmed_mismatch"),
    "SEMANTIC_PROBABLE_MISMATCH": ("BSA002", "probable_mismatch"),
    "SEMANTIC_MISSING_TRACE": ("BSA003", "missing_trace"),
    "SEMANTIC_WEAK_BINDING": ("BSA004", "weak_binding"),
    "SEMANTIC_AMBIGUOUS": ("BSA005", "ambiguous"),
    "SEMANTIC_SUPPRESSION_RATIONALE_INSUFFICIENT": (
        "BSA006",
        "rationale_insufficient",
    ),
    "SEMANTIC_SUPPRESSION_SCOPE_OVERBROAD": ("BSA007", "scope_overbroad"),
    "SEMANTIC_SUPPRESSION_RISK_UNADDRESSED": ("BSA008", "risk_unaddressed"),
}
_SUPPRESSION_ONLY_CODES = frozenset(
    {
        "SEMANTIC_SUPPRESSION_RATIONALE_INSUFFICIENT",
        "SEMANTIC_SUPPRESSION_SCOPE_OVERBROAD",
        "SEMANTIC_SUPPRESSION_RISK_UNADDRESSED",
    }
)
_QUALIFIED_SEMANTIC_CODES = (
    "SEMANTIC_CONFIRMED_MISMATCH",
    "SEMANTIC_PROBABLE_MISMATCH",
    "SEMANTIC_MISSING_TRACE",
    "SEMANTIC_WEAK_BINDING",
    "SEMANTIC_AMBIGUOUS",
)
_LEGACY_VERIFICATION_STATES = frozenset(
    {
        "evidence_bound",
        "corroborated",
        "mechanically_verified",
        "human_verified",
        "disputed",
    }
)
_CURRENT_VERIFICATION_STATES = frozenset(
    {
        "evidence_bound",
        "verification_indeterminate",
        "independently_verified",
        "mechanically_verified",
        "human_verified",
        "disputed_by_verifier",
        "human_rejected",
    }
)
_PROBLEM_CODES_BY_STAGE = {
    "config": frozenset({"invalid_config"}),
    "input": frozenset({"invalid_input"}),
    "cache": frozenset({"corrupt_cache", "stale_cache"}),
    "lock": frozenset({"lock_timeout"}),
    "provider": frozenset({"provider_failure"}),
    "normalization": frozenset({"malformed_result"}),
    "completeness": frozenset({"incomplete_result"}),
    "budget": frozenset({"budget_exceeded"}),
    "output": frozenset({"output_failure"}),
    "internal": frozenset({"internal_failure"}),
}
_PROBLEM_V3_CODES_BY_STAGE = {
    **_PROBLEM_CODES_BY_STAGE,
    "alignment": frozenset(
        {"no_active_intent", "alignment_incomplete", "readiness_blocked"}
    ),
    "snapshot": frozenset({"snapshot_unstable", "source_changed"}),
    "input": frozenset(
        {
            "invalid_input",
            "mutable_path_overlap",
            "unsupported_platform",
            "packet_report_budget_exhausted",
        }
    ),
    "qualification": frozenset({"required_qualification_unavailable"}),
}
_FAILED_REPORT_STAGES = frozenset(
    {
        "config",
        "input",
        "cache",
        "lock",
        "provider",
        "normalization",
        "output",
        "internal",
        "alignment",
        "snapshot",
        "qualification",
    }
)
_SOURCE_SNAPSHOT_FIELDS = frozenset(
    {"snapshot_hash", "file_count", "byte_count", "unreadable_count"}
)
_READINESS_COUNT_FIELDS = frozenset(
    {
        "total",
        "active",
        "out_of_scope",
        "selected",
        "skipped",
        "alignment_debt",
        "blocked",
    }
)
_VERIFICATION_FIELDS = frozenset(
    {
        "state",
        "contract",
        "events",
        "aggregate_counts",
        "cache_hits",
        "cache_misses",
        "provider_calls",
    }
)
_VERIFICATION_COUNT_FIELDS = frozenset(
    {"independently_verified", "disputed", "verification_indeterminate"}
)
_VERIFICATION_CONTRACT_FIELDS = frozenset(
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
_VERIFICATION_EVENT_FIELDS = frozenset(
    {
        "packet_id",
        "packet_hash",
        "claim_hash",
        "verifier_packet_hash",
        "required_epochs",
        "results",
        "aggregate_state",
        "context",
    }
)
_VERIFICATION_EPOCH_FIELDS = frozenset({"base_search_epoch", "effective_search_epoch"})
_VERIFICATION_RESULT_FIELDS = frozenset(
    {
        "verify_key",
        "base_search_epoch",
        "effective_search_epoch",
        "verdict",
        "support_score",
        "evidence",
    }
)


class PacketReportError(ValueError):
    """A packet report violated its closed trust-boundary contract."""


class AnalysisReportError(ValueError):
    """An analysis report violated its closed trust-boundary contract."""


_PACKET_VALIDATORS = make_validators(PacketReportError)
_ANALYSIS_VALIDATORS = make_validators(AnalysisReportError)


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_replace_bytes(path: Path, content: bytes) -> None:
    """Publish bytes through a same-directory fsynced temporary and replace."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        handle = os.fdopen(descriptor, "wb", closefd=True)
        descriptor = -1
        with handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def stage_artifact_bytes(path: Path, content: bytes) -> Path:
    """Write and fsync one same-directory staging file without publishing it."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = -1
    temporary: Path | None = None
    for _ in range(10):
        candidate = path.parent / (
            f".{path.name}.{os.getpid()}.{secrets.token_hex(16)}.tmp"
        )
        try:
            descriptor = os.open(
                candidate,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError:
            continue
        temporary = candidate
        break
    if temporary is None:
        raise FileExistsError("could not allocate a unique artifact staging path")
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        return temporary
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def publish_staged_artifact(path: Path, staged: Path) -> None:
    """Atomically replace one final path with a completed adjacent staging file."""

    os.replace(staged, path)
    _fsync_directory(path.parent)


class ArtifactPublicationError(OSError):
    """A staged artifact set failed with exact partial-publication context."""

    def __init__(
        self,
        failed_path: Path,
        published_paths: tuple[Path, ...],
        cause: OSError,
    ) -> None:
        super().__init__(str(cause))
        self.failed_path = failed_path
        self.published_paths = published_paths
        self.__cause__ = cause


def publish_artifact_set(
    ordered_items: Sequence[tuple[Path, bytes]],
    *,
    before_publish: Callable[[], None] | None = None,
) -> None:
    """Stage all artifacts, validate currentness, then publish in order."""

    staged: list[tuple[Path, Path]] = []
    try:
        for final_path, content in ordered_items:
            try:
                staged_path = stage_artifact_bytes(final_path, content)
            except OSError as exc:
                raise ArtifactPublicationError(final_path, (), exc) from exc
            staged.append((final_path, staged_path))
        if before_publish is not None:
            before_publish()
        published: list[Path] = []
        for final_path, staged_path in staged:
            try:
                publish_staged_artifact(final_path, staged_path)
            except OSError as exc:
                raise ArtifactPublicationError(
                    final_path, tuple(published), exc
                ) from exc
            published.append(final_path)
    finally:
        for _, staged_path in staged:
            try:
                staged_path.unlink()
            except FileNotFoundError:
                pass


@dataclass(frozen=True, slots=True)
class PacketReport:
    """Validated packet report stored as canonical bytes."""

    _canonical: bytes

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> PacketReport:
        normalized = _validate_packet_report_shape(value)
        return cls(canonical_json_bytes(normalized))

    def to_dict(self) -> dict[str, Any]:
        value = json.loads(self._canonical)
        assert isinstance(value, dict)
        return value

    def to_json_bytes(self) -> bytes:
        return self._canonical

    @property
    def packet_jsonl_sha256(self) -> str:
        value = self.to_dict()["packet_jsonl_sha256"]
        assert isinstance(value, str)
        return value

    @property
    def packet_warning_count(self) -> int:
        value = self.to_dict().get("packet_warning_count")
        if value is None:
            raise PacketReportError(
                "packet warning count is packet-derived in report schema 2"
            )
        assert isinstance(value, int)
        return value

    @property
    def prompt_byte_count(self) -> int:
        value = self.to_dict().get("prompt_byte_count")
        if value is None:
            raise PacketReportError(
                "prompt byte count is packet-derived in report schema 2"
            )
        assert isinstance(value, int)
        return value


@dataclass(frozen=True, slots=True)
class AnalysisReport:
    """Validated analysis report stored as canonical bytes."""

    _canonical: bytes

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AnalysisReport:
        if value.get("schema_version") in {3, 4}:
            raise AnalysisReportError(
                "analysis report schema 3 or 4 must be created through "
                "validate_analysis_report with its paired packet report"
            )
        return cls._from_shape(value)

    @classmethod
    def _from_shape(cls, value: Mapping[str, Any]) -> AnalysisReport:
        normalized = _validate_analysis_report_shape(value)
        return cls(canonical_json_bytes(normalized))

    def to_dict(self) -> dict[str, Any]:
        value = json.loads(self._canonical)
        assert isinstance(value, dict)
        return value

    def to_json_bytes(self) -> bytes:
        return self._canonical + b"\n"


def _nonnegative_int(value: object, name: str) -> int:
    try:
        return _PACKET_VALIDATORS.integer(value, name)
    except PacketReportError:
        raise PacketReportError(f"{name} must be a nonnegative integer") from None


def _nonblank_string(value: object, name: str) -> str:
    return _ANALYSIS_VALIDATORS.nonblank(value, name)


def _analysis_nonnegative_int(value: object, name: str) -> int:
    try:
        return _ANALYSIS_VALIDATORS.integer(value, name)
    except AnalysisReportError:
        raise AnalysisReportError(f"{name} must be a nonnegative integer") from None


def _analysis_digest(value: object, name: str) -> str:
    return _ANALYSIS_VALIDATORS.digest(value, name)


def _exact_record(value: object, fields: frozenset[str], name: str) -> dict[str, Any]:
    return _ANALYSIS_VALIDATORS.closed_record(
        value,
        fields,
        name,
        mismatch_message=f"{name} does not match its closed shape",
    )


def _validate_problem_v1(value: object, index: int) -> str:
    name = f"problems[{index}]"
    row = _exact_record(value, _PROBLEM_V1_FIELDS, name)
    packet_id = row["packet_id"]
    if packet_id is not None:
        _nonblank_string(packet_id, f"{name}.packet_id")
    stage = row["stage"]
    code = row["code"]
    if (
        not isinstance(stage, str)
        or not isinstance(code, str)
        or stage not in _PROBLEM_CODES_BY_STAGE
        or code not in _PROBLEM_CODES_BY_STAGE[stage]
    ):
        raise AnalysisReportError(f"{name} has an invalid stage/code pair")
    _nonblank_string(row["message"], f"{name}.message")
    return stage


def _positive_analysis_int(value: object, name: str) -> int:
    result = _analysis_nonnegative_int(value, name)
    if result < 1:
        raise AnalysisReportError(f"{name} must be a positive integer")
    return result


def _canonical_obligation_ids(value: object, name: str) -> list[str]:
    if not isinstance(value, list):
        raise AnalysisReportError(f"{name} must be an array")
    result = [_nonblank_string(item, f"{name}[]") for item in value]
    if result != sorted(set(result)):
        raise AnalysisReportError(f"{name} must be unique and canonical-sorted")
    return result


def _absolute_path(value: object, name: str) -> str:
    result = _nonblank_string(value, name)
    if not Path(result).is_absolute():
        raise AnalysisReportError(f"{name} must be an absolute path")
    return result


def _validate_qualification_details(value: object, name: str) -> None:
    fields = frozenset(
        {
            "selectors",
            "reason",
            "qualification_report_sha256",
            "expected_composition_sha256",
            "current_composition_sha256",
        }
    )
    row = _exact_record(value, fields, name)
    selectors = row["selectors"]
    if not isinstance(selectors, list) or not selectors:
        raise AnalysisReportError(f"{name}.selectors must be a nonempty array")
    selector_order: list[tuple[int, str]] = []
    seen_selectors: set[str] = set()
    for index, value in enumerate(selectors):
        selector = _nonblank_string(value, f"{name}.selectors[{index}]")
        code, separator, context = selector.partition(":")
        canonical_codes = _QUALIFIED_SEMANTIC_CODES
        short_codes = tuple(_SEMANTIC_CODE_DATA[code][0] for code in canonical_codes)
        if not separator or context != "independently_verified":
            raise AnalysisReportError(f"{name}.selectors[{index}] is invalid")
        if code in canonical_codes:
            code_index = canonical_codes.index(code)
        elif code in short_codes:
            code_index = short_codes.index(code)
        else:
            raise AnalysisReportError(f"{name}.selectors[{index}] is invalid")
        if selector in seen_selectors:
            raise AnalysisReportError(f"{name}.selectors must be unique")
        seen_selectors.add(selector)
        selector_order.append((code_index, selector))
    if selector_order != sorted(selector_order):
        raise AnalysisReportError(f"{name}.selectors are not in BSA code order")
    reason = row["reason"]
    if reason not in {"missing", "corrupt", "failed", "identity_mismatch"}:
        raise AnalysisReportError(f"{name}.reason is invalid")
    report_hash = row["qualification_report_sha256"]
    expected_hash = row["expected_composition_sha256"]
    current_hash = row["current_composition_sha256"]
    if report_hash is not None:
        _analysis_digest(report_hash, f"{name}.qualification_report_sha256")
    if expected_hash is not None:
        _analysis_digest(expected_hash, f"{name}.expected_composition_sha256")
    _analysis_digest(current_hash, f"{name}.current_composition_sha256")
    if reason == "missing" and (report_hash is not None or expected_hash is not None):
        raise AnalysisReportError(f"{name} missing reason has invalid hashes")
    if reason == "corrupt" and (report_hash is None or expected_hash is not None):
        raise AnalysisReportError(f"{name} corrupt reason has invalid hashes")
    if reason in {"failed", "identity_mismatch"} and (
        report_hash is None or expected_hash is None
    ):
        raise AnalysisReportError(f"{name} qualified reason requires both hashes")


def _validate_problem_v3(value: object, index: int) -> str:
    name = f"problems[{index}]"
    row = _exact_record(value, _PROBLEM_V3_FIELDS, name)
    for identity_field in ("packet_id", "obligation_id"):
        identity = row[identity_field]
        if identity is not None:
            _nonblank_string(identity, f"{name}.{identity_field}")
    stage = row["stage"]
    code = row["code"]
    if (
        not isinstance(stage, str)
        or not isinstance(code, str)
        or stage not in _PROBLEM_V3_CODES_BY_STAGE
        or code not in _PROBLEM_V3_CODES_BY_STAGE[stage]
    ):
        raise AnalysisReportError(f"{name} has an invalid stage/code pair")
    message = _nonblank_string(row["message"], f"{name}.message")
    if "\n" in message or "\r" in message:
        raise AnalysisReportError(f"{name}.message must be line-safe")
    details = row["details"]
    if stage in _PROBLEM_CODES_BY_STAGE and code in _PROBLEM_CODES_BY_STAGE[stage]:
        _exact_record(details, frozenset(), f"{name}.details")
    elif (stage, code) == ("alignment", "no_active_intent"):
        _exact_record(details, frozenset(), f"{name}.details")
    elif (stage, code) in {
        ("alignment", "alignment_incomplete"),
        ("alignment", "readiness_blocked"),
    }:
        detail_row = _exact_record(
            details, frozenset({"obligation_ids"}), f"{name}.details"
        )
        if not _canonical_obligation_ids(
            detail_row["obligation_ids"], f"{name}.details.obligation_ids"
        ):
            raise AnalysisReportError(f"{name}.details.obligation_ids must be nonempty")
    elif (stage, code) == ("snapshot", "snapshot_unstable"):
        detail_row = _exact_record(details, frozenset({"attempts"}), f"{name}.details")
        _positive_analysis_int(detail_row["attempts"], f"{name}.details.attempts")
    elif (stage, code) == ("snapshot", "source_changed"):
        detail_row = _exact_record(
            details,
            frozenset({"before_snapshot", "after_snapshot"}),
            f"{name}.details",
        )
        before = _analysis_digest(
            detail_row["before_snapshot"], f"{name}.details.before_snapshot"
        )
        after = _analysis_digest(
            detail_row["after_snapshot"], f"{name}.details.after_snapshot"
        )
        if before == after:
            raise AnalysisReportError(f"{name}.details snapshots must differ")
    elif (stage, code) == ("input", "mutable_path_overlap"):
        detail_row = _exact_record(
            details,
            frozenset({"mutable_path", "semantic_input"}),
            f"{name}.details",
        )
        _absolute_path(detail_row["mutable_path"], f"{name}.details.mutable_path")
        _absolute_path(detail_row["semantic_input"], f"{name}.details.semantic_input")
    elif (stage, code) == ("input", "unsupported_platform"):
        detail_row = _exact_record(details, frozenset({"platform"}), f"{name}.details")
        _nonblank_string(detail_row["platform"], f"{name}.details.platform")
    elif (stage, code) == ("input", "packet_report_budget_exhausted"):
        detail_row = _exact_record(
            details,
            frozenset({"limit_bytes", "observed_bytes"}),
            f"{name}.details",
        )
        limit = _positive_analysis_int(
            detail_row["limit_bytes"], f"{name}.details.limit_bytes"
        )
        observed = _positive_analysis_int(
            detail_row["observed_bytes"], f"{name}.details.observed_bytes"
        )
        if observed <= limit:
            raise AnalysisReportError(f"{name}.details does not describe exhaustion")
    elif (stage, code) == (
        "qualification",
        "required_qualification_unavailable",
    ):
        _validate_qualification_details(details, f"{name}.details")
    else:  # pragma: no cover - the closed pair table above owns reachability.
        raise AnalysisReportError(f"{name} has no details contract")
    return stage


def _validate_warning_debt(value: object, index: int) -> int:
    name = f"packet_warning_debt[{index}]"
    row = _exact_record(value, _WARNING_DEBT_FIELDS, name)
    _nonblank_string(row["packet_id"], f"{name}.packet_id")
    warnings = row["warnings"]
    if (
        not isinstance(warnings, list)
        or not warnings
        or not all(isinstance(item, str) for item in warnings)
    ):
        raise AnalysisReportError(f"{name}.warnings must be a nonempty string list")
    return len(warnings)


def _validate_semantic_identity(
    row: dict[str, Any], name: str, *, suppression_allowed: bool = False
) -> None:
    if not isinstance(row["code"], str) or row["code"] not in _SEMANTIC_CODE_DATA:
        raise AnalysisReportError(f"{name}.code is not canonical")
    if not suppression_allowed and row["code"] in _SUPPRESSION_ONLY_CODES:
        raise AnalysisReportError(f"{name}.code is not valid in this report schema")
    _nonblank_string(row["packet_id"], f"{name}.packet_id")
    _analysis_digest(row["packet_hash"], f"{name}.packet_hash")
    _analysis_digest(row["finding_hash"], f"{name}.finding_hash")


def _validate_finding_debt(
    value: object,
    index: int,
    *,
    current: bool,
    suppression_allowed: bool = False,
) -> None:
    name = f"{'finding' if current else 'candidate'}_debt[{index}]"
    row = _exact_record(value, _FINDING_DEBT_FIELDS, name)
    _validate_semantic_identity(row, name, suppression_allowed=suppression_allowed)
    states = (
        _CURRENT_VERIFICATION_STATES - {"human_verified", "human_rejected"}
        if current
        else {"evidence_bound", "corroborated"}
    )
    if (
        not isinstance(row["verification_state"], str)
        or row["verification_state"] not in states
    ):
        raise AnalysisReportError(f"{name}.verification_state is invalid")


def _validate_disposition(
    value: object, index: int, *, suppression_allowed: bool = False
) -> None:
    name = f"unused_dispositions[{index}]"
    row = _exact_record(value, _DISPOSITION_FIELDS, name)
    _validate_semantic_identity(row, name, suppression_allowed=suppression_allowed)
    if not isinstance(row["status"], str) or row["status"] not in {
        "accepted",
        "rejected",
    }:
        raise AnalysisReportError(f"{name}.status is invalid")
    _nonblank_string(row["reason"], f"{name}.reason")


def _validate_evidence(value: object, name: str) -> None:
    row = _exact_record(value, _EVIDENCE_FIELDS, name)
    if not isinstance(row["role"], str) or row["role"] not in {
        "requirement",
        "implementation",
        "test",
        "counterevidence",
    }:
        raise AnalysisReportError(f"{name}.role is invalid")
    _nonblank_string(row["path"], f"{name}.path")
    start = _analysis_nonnegative_int(row["start_line"], f"{name}.start_line")
    end = _analysis_nonnegative_int(row["end_line"], f"{name}.end_line")
    if start < 1 or end < start:
        raise AnalysisReportError(f"{name} has an invalid inclusive line span")
    if not isinstance(row["excerpt"], str):
        raise AnalysisReportError(f"{name}.excerpt must be a string")
    excerpt_line_count = lf_line_count(row["excerpt"]) + int(
        not row["excerpt"] or row["excerpt"].endswith("\n")
    )
    if excerpt_line_count != end - start + 1:
        raise AnalysisReportError(f"{name}.excerpt does not match its line span")
    excerpt_hash = _analysis_digest(row["excerpt_sha256"], f"{name}.excerpt_sha256")
    if excerpt_hash != hashlib.sha256(row["excerpt"].encode("utf-8")).hexdigest():
        raise AnalysisReportError(f"{name}.excerpt_sha256 does not match excerpt")


def _validate_diagnostic(
    value: object,
    index: int,
    effective_policy_layers: set[str],
    *,
    current: bool,
    suppression_allowed: bool = False,
) -> bool:
    from backstitch.diagnostics import selector_matches
    from backstitch.semantic_policy import SEMANTIC_DEFAULT_LEVELS, VerificationState

    name = f"semantic_diagnostics[{index}]"
    row = _exact_record(value, _DIAGNOSTIC_FIELDS, name)
    _validate_semantic_identity(row, name, suppression_allowed=suppression_allowed)
    short_code, classification = _SEMANTIC_CODE_DATA[row["code"]]
    if row["short_code"] != short_code or row["classification"] != classification:
        raise AnalysisReportError(f"{name} code aliases are inconsistent")
    allowed_packet_kinds = (
        {"section", "invariant", "suppression"}
        if suppression_allowed
        else {"section", "invariant"}
    )
    if (
        not isinstance(row["packet_kind"], str)
        or row["packet_kind"] not in allowed_packet_kinds
    ):
        raise AnalysisReportError(f"{name}.packet_kind is invalid")
    if (
        (row["packet_kind"] == "section" and row["classification"] == "weak_binding")
        or (
            row["packet_kind"] == "invariant"
            and row["classification"] == "missing_trace"
        )
        or (
            row["packet_kind"] == "suppression"
            and row["classification"]
            not in {
                "rationale_insufficient",
                "scope_overbroad",
                "risk_unaddressed",
                "ambiguous",
            }
        )
        or (
            row["packet_kind"] != "suppression"
            and row["code"] in _SUPPRESSION_ONLY_CODES
        )
    ):
        raise AnalysisReportError(f"{name} classification is invalid for packet kind")
    verification_states = (
        _CURRENT_VERIFICATION_STATES if current else _LEGACY_VERIFICATION_STATES
    )
    if (
        not isinstance(row["verification_state"], str)
        or row["verification_state"] not in verification_states
    ):
        raise AnalysisReportError(f"{name}.verification_state is invalid")
    evidence = row["evidence"]
    if not isinstance(evidence, list):
        raise AnalysisReportError(f"{name}.evidence must be a list")
    for evidence_index, item in enumerate(evidence):
        _validate_evidence(item, f"{name}.evidence[{evidence_index}]")
    evidence_keys = [
        (
            item["role"],
            item["path"],
            item["start_line"],
            item["end_line"],
            item["excerpt_sha256"],
        )
        for item in evidence
    ]
    if len(evidence_keys) != len(set(evidence_keys)):
        raise AnalysisReportError(f"{name}.evidence contains duplicates")
    if evidence_keys != sorted(evidence_keys):
        raise AnalysisReportError(f"{name}.evidence is not canonically ordered")
    required_roles = (
        {"requirement", "counterevidence"}
        if row["classification"] in {"scope_overbroad", "risk_unaddressed"}
        else {"requirement", "implementation"}
        if row["classification"]
        in {"confirmed_mismatch", "probable_mismatch", "weak_binding"}
        else {"requirement"}
    )
    actual_roles = {item["role"] for item in evidence}
    allowed_roles = {"requirement", "implementation", "test", "counterevidence"}
    if not required_roles.issubset(actual_roles) or not actual_roles.issubset(
        allowed_roles
    ):
        raise AnalysisReportError(f"{name}.evidence does not match the role contract")
    if current:
        finding_identity = {
            "finding_contract_version": 1,
            "code": row["code"],
            "classification": row["classification"],
            "packet_kind": row["packet_kind"],
            "packet_id": row["packet_id"],
            "packet_hash": row["packet_hash"],
            "evidence": [
                {
                    field: item[field]
                    for field in (
                        "role",
                        "path",
                        "start_line",
                        "end_line",
                        "excerpt_sha256",
                    )
                }
                for item in evidence
            ],
        }
        expected_finding_hash = hashlib.sha256(
            canonical_json_bytes(finding_identity)
        ).hexdigest()
        if row["finding_hash"] != expected_finding_hash:
            raise AnalysisReportError(f"{name}.finding_hash does not recompute")
    if not isinstance(row["default_severity"], str) or row["default_severity"] not in {
        "error",
        "warning",
        "info",
    }:
        raise AnalysisReportError(f"{name}.default_severity is invalid")
    if not isinstance(row["severity"], str) or row["severity"] not in {
        "error",
        "warning",
        "info",
        "off",
    }:
        raise AnalysisReportError(f"{name}.severity is invalid")
    verification_state_value = row["verification_state"]
    policy_state = (
        "evidence_bound"
        if verification_state_value == "corroborated"
        else "disputed_by_verifier"
        if verification_state_value == "disputed"
        else verification_state_value
    )
    verification_state = cast(VerificationState, policy_state)
    selector_state = policy_state if current else verification_state_value
    expected_default = SEMANTIC_DEFAULT_LEVELS[(row["code"], verification_state)]
    if row["default_severity"] != expected_default:
        raise AnalysisReportError(f"{name}.default_severity is inconsistent")
    if (
        policy_state
        in {
            "evidence_bound",
            "verification_indeterminate",
            "disputed_by_verifier",
            "human_rejected",
        }
        and row["severity"] == "error"
    ):
        raise AnalysisReportError(
            f"{name} non-authoritative state cannot have error severity"
        )
    _nonblank_string(row["summary"], f"{name}.summary")
    if not isinstance(row["rationale"], str):
        raise AnalysisReportError(f"{name}.rationale must be a string")
    _analysis_digest(row["analysis_key"], f"{name}.analysis_key")
    rule = _exact_record(
        row["winning_policy_rule"], _WINNING_RULE_FIELDS, f"{name}.winning_policy_rule"
    )
    source = _nonblank_string(rule["source"], f"{name}.winning_policy_rule.source")
    _analysis_nonnegative_int(rule["position"], f"{name}.winning_policy_rule.position")
    selector = _nonblank_string(
        rule["selector"], f"{name}.winning_policy_rule.selector"
    )
    if not isinstance(rule["level"], str) or rule["level"] not in {
        "error",
        "warning",
        "info",
        "off",
    }:
        raise AnalysisReportError(f"{name}.winning_policy_rule.level is invalid")
    if source not in effective_policy_layers:
        raise AnalysisReportError(f"{name} winning policy source is not effective")
    if rule["level"] != row["severity"]:
        raise AnalysisReportError(f"{name} winning policy level differs from severity")
    if not selector_matches(
        selector,
        row["code"],
        context=selector_state,
    ):
        raise AnalysisReportError(f"{name} winning selector does not match diagnostic")
    selector_code, separator, selector_context = selector.partition(":")
    level_authority = {"off": 0, "info": 1, "warning": 2, "error": 3}
    if (
        "*" in selector_code
        and level_authority[row["severity"]] > level_authority[expected_default]
    ):
        raise AnalysisReportError(f"{name} wildcard selector cannot raise severity")
    return bool(
        policy_state
        in {
            "independently_verified",
            "mechanically_verified",
            "human_verified",
        }
        and row["severity"] != "off"
        and separator
        and selector_context == selector_state
        and selector_code in {row["code"], row["short_code"]}
        and "*" not in selector_code
        and not (
            policy_state == "independently_verified"
            and row["code"] in _SUPPRESSION_ONLY_CODES
        )
    )


def _validate_analysis_report_v1_shape(value: Mapping[str, Any]) -> dict[str, Any]:
    if set(value) != _ANALYSIS_REPORT_V1_FIELDS:
        raise AnalysisReportError("analysis report does not match the closed shape")
    schema = value.get("schema_version")
    if isinstance(schema, bool) or schema != 1:
        raise AnalysisReportError("analysis report schema_version must be 1")
    if value.get("artifact") != "backstitch-analysis-report":
        raise AnalysisReportError("analysis report artifact is invalid")
    _analysis_digest(value.get("packet_jsonl_sha256"), "packet_jsonl_sha256")
    _analysis_digest(value.get("result_jsonl_sha256"), "result_jsonl_sha256")
    status = value.get("status")
    if not isinstance(status, str) or status not in {
        "complete",
        "incomplete",
        "failed",
    }:
        raise AnalysisReportError("analysis report status is invalid")
    exit_code = value.get("analysis_exit_code")
    if (
        isinstance(exit_code, bool)
        or not isinstance(exit_code, int)
        or exit_code not in {0, 1, 2}
    ):
        raise AnalysisReportError("analysis_exit_code must be 0, 1, or 2")
    count_names = (
        "packet_count",
        "result_count",
        "packet_warning_count",
        "cache_hits",
        "cache_misses",
        "provider_calls",
        "prompt_byte_count",
        "elapsed_milliseconds",
    )
    counts = {
        name: _analysis_nonnegative_int(value.get(name), name) for name in count_names
    }
    if counts["result_count"] > counts["packet_count"]:
        raise AnalysisReportError("result_count cannot exceed packet_count")

    warning_debt = value.get("packet_warning_debt")
    if not isinstance(warning_debt, list):
        raise AnalysisReportError("packet_warning_debt must be a list")
    warning_total = sum(
        _validate_warning_debt(item, index) for index, item in enumerate(warning_debt)
    )
    if warning_debt and warning_total != counts["packet_warning_count"]:
        raise AnalysisReportError("packet warning debt count is inconsistent")
    warning_packet_ids = [item["packet_id"] for item in warning_debt]
    if len(warning_packet_ids) != len(set(warning_packet_ids)):
        raise AnalysisReportError("packet_warning_debt contains duplicate packets")

    candidate_debt = value.get("candidate_debt")
    if not isinstance(candidate_debt, list):
        raise AnalysisReportError("candidate_debt must be a list")
    for index, item in enumerate(candidate_debt):
        _validate_finding_debt(item, index, current=False)
    unused_dispositions = value.get("unused_dispositions")
    if not isinstance(unused_dispositions, list):
        raise AnalysisReportError("unused_dispositions must be a list")
    for index, item in enumerate(unused_dispositions):
        _validate_disposition(item, index)

    cost = value.get("estimated_cost_microusd")
    source = value.get("cost_rate_source")
    if cost is None:
        if source is not None:
            raise AnalysisReportError("cost_rate_source must be null when cost is null")
    else:
        _analysis_nonnegative_int(cost, "estimated_cost_microusd")
        _nonblank_string(source, "cost_rate_source")

    layers = value.get("effective_policy_layers")
    if not isinstance(layers, list) or not layers:
        raise AnalysisReportError("effective_policy_layers must be a nonempty list")
    if any(not isinstance(layer, str) or not layer.strip() for layer in layers):
        raise AnalysisReportError("effective_policy_layers must contain strings")
    if len(layers) != len(set(layers)):
        raise AnalysisReportError("effective_policy_layers must be unique")

    diagnostics = value.get("semantic_diagnostics")
    if not isinstance(diagnostics, list):
        raise AnalysisReportError("semantic_diagnostics must be a list")
    authoritative_diagnostics = [
        _validate_diagnostic(item, index, set(layers), current=False)
        for index, item in enumerate(diagnostics)
    ]
    diagnostic_identities = [
        (
            item["code"],
            item["packet_id"],
            item["packet_hash"],
            item["finding_hash"],
            item["verification_state"],
        )
        for item in diagnostics
    ]
    if len(diagnostic_identities) != len(set(diagnostic_identities)):
        raise AnalysisReportError("semantic_diagnostics contains duplicate identities")
    candidate_identities = [
        (
            item["code"],
            item["packet_id"],
            item["packet_hash"],
            item["finding_hash"],
            item["verification_state"],
        )
        for item in candidate_debt
    ]
    if len(candidate_identities) != len(set(candidate_identities)):
        raise AnalysisReportError("candidate_debt contains duplicate identities")
    if not set(candidate_identities).issubset(set(diagnostic_identities)):
        raise AnalysisReportError("candidate_debt has no matching semantic diagnostic")
    disposition_identities = [
        (
            item["code"],
            item["packet_id"],
            item["packet_hash"],
            item["finding_hash"],
        )
        for item in unused_dispositions
    ]
    if len(disposition_identities) != len(set(disposition_identities)):
        raise AnalysisReportError("unused_dispositions contains duplicate identities")

    raw_problems = value.get("problems")
    if not isinstance(raw_problems, list):
        raise AnalysisReportError("problems must be a list")
    stages = [
        _validate_problem_v1(item, index) for index, item in enumerate(raw_problems)
    ]
    expected_status = (
        "failed"
        if any(stage in _FAILED_REPORT_STAGES for stage in stages)
        else "incomplete"
        if stages
        else "complete"
    )
    if value.get("status") != expected_status:
        raise AnalysisReportError(
            "analysis report status is inconsistent with problems"
        )
    prepublication_stages = [stage for stage in stages if stage != "output"]
    if prepublication_stages and exit_code != 2:
        raise AnalysisReportError("analysis_exit_code must be 2 for analysis problems")
    if not prepublication_stages and exit_code == 2:
        raise AnalysisReportError(
            "analysis_exit_code 2 requires a prepublication problem"
        )
    if exit_code == 1 and not any(authoritative_diagnostics):
        raise AnalysisReportError(
            "analysis_exit_code 1 requires an authoritative diagnostic"
        )
    normalized = json.loads(canonical_json_bytes(value))
    assert isinstance(normalized, dict)
    return normalized


def _validate_analysis_source_snapshot(value: object) -> dict[str, Any]:
    row = _exact_record(value, _SOURCE_SNAPSHOT_FIELDS, "source_snapshot")
    _analysis_digest(row["snapshot_hash"], "source_snapshot.snapshot_hash")
    for field in ("file_count", "byte_count", "unreadable_count"):
        _analysis_nonnegative_int(row[field], f"source_snapshot.{field}")
    return row


def _validate_analysis_alignment_projection(
    source_snapshot: dict[str, Any],
    counts: object,
    audit: object,
    issues: object,
    *,
    current: bool,
) -> dict[str, int]:
    if not isinstance(counts, dict) or set(counts) != _READINESS_COUNT_FIELDS:
        raise AnalysisReportError("alignment_summary is invalid")
    normalized_counts = {
        field: _analysis_nonnegative_int(counts[field], f"alignment_summary.{field}")
        for field in _READINESS_COUNT_FIELDS
    }
    selected = normalized_counts["selected"]
    audit_rows = audit if isinstance(audit, list) else []
    packets = []
    if audit_rows:
        packets = [
            {"packet_id": item.get("obligation_id"), "packet_hash": "0" * 64}
            for item in audit_rows
            if isinstance(item, dict)
            and item.get("obligation_rung") == "active"
            and item.get("disposition") == "evaluate"
            and item.get("alignment_state") == "complete"
        ]
    synthetic: dict[str, Any] = {
        "schema_version": 3 if current else 2,
        "artifact": "backstitch-packet-report",
        "scope": "source_snapshot",
        "source_snapshot": source_snapshot,
        "derivation_contract": {
            "obligation_algorithm_version": 1,
            "discovery_algorithm_version": 1,
            "normalization_version": 1,
            "semantic_config_sha256": "0" * 64,
        },
        "packet_jsonl_sha256": "0" * 64,
        "packet_count": selected,
        "packet_bytes": 0,
        "selection_status": "selected" if selected else "not_run_all_skipped",
        "readiness_counts": counts,
        "alignment_audit": audit,
        "deterministic_issues": issues,
        "packets": packets,
        "packet_report_content_sha256": "",
        "tool_version": "analysis-projection",
        "created_at": "1970-01-01T00:00:00Z",
    }
    if current:
        packet_versions = (
            [3, 4]
            if any(
                isinstance(item, dict)
                and item.get("kind") == "suppression"
                and _audit_bucket(item) == "selected"
                for item in audit_rows
            )
            else [3]
        )
        kind_counts = {
            packet_kind: sum(
                isinstance(item, dict)
                and item.get("kind") == packet_kind
                and _audit_bucket(item) == "selected"
                for item in audit_rows
            )
            for packet_kind in ("section", "invariant", "suppression")
        }
        synthetic["packet_schema_versions"] = packet_versions
        synthetic["derivation_contract"]["packet_contract_versions"] = packet_versions
        synthetic["kind_counts"] = {
            "eligible": kind_counts,
            "emitted": dict(kind_counts),
        }
    else:
        synthetic["packet_schema_version"] = 3
        synthetic["derivation_contract"]["packet_contract_version"] = 3
    synthetic["packet_report_content_sha256"] = hashlib.sha256(
        canonical_json_bytes(_packet_report_content_projection(synthetic))
    ).hexdigest()
    try:
        _packet_report_source_shape(synthetic)
    except PacketReportError as exc:
        raise AnalysisReportError(
            f"analysis alignment projection is invalid: {exc}"
        ) from None
    return normalized_counts


def _validate_verification_contract(value: object) -> dict[str, Any]:
    from backstitch.semantic_identity import ProviderIdentity, RequestIdentity
    from backstitch.semantic_verification import VERIFY_CONTRACT_VERSION

    row = _exact_record(value, _VERIFICATION_CONTRACT_FIELDS, "verification.contract")
    if row["verify_contract_version"] != VERIFY_CONTRACT_VERSION or isinstance(
        row["verify_contract_version"], bool
    ):
        raise AnalysisReportError("verification contract version is invalid")
    prompt = _exact_record(
        row["prompt"], frozenset({"id", "version", "sha256"}), "verification.prompt"
    )
    _nonblank_string(prompt["id"], "verification.prompt.id")
    _positive_analysis_int(prompt["version"], "verification.prompt.version")
    _analysis_digest(prompt["sha256"], "verification.prompt.sha256")
    provider_fields = frozenset(
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
    provider = _exact_record(row["provider"], provider_fields, "verification.provider")
    try:
        normalized_provider = asdict(ProviderIdentity(**provider))
    except (TypeError, ValueError) as exc:
        raise AnalysisReportError(f"verification.provider is invalid: {exc}") from None
    if provider != normalized_provider or any(
        not isinstance(value, str) or not value.strip()
        for field, value in provider.items()
        if field != "adapter_version"
    ):
        raise AnalysisReportError("verification.provider is not canonical and nonblank")
    request = _exact_record(
        row["request"],
        frozenset({"json_mode", "temperature", "seed", "max_tokens"}),
        "verification.request",
    )
    try:
        normalized_request = asdict(RequestIdentity(**request))
    except (TypeError, ValueError) as exc:
        raise AnalysisReportError(f"verification.request is invalid: {exc}") from None
    if request != normalized_request:
        raise AnalysisReportError("verification.request is not canonical")
    epochs = row["search_epochs"]
    if (
        not isinstance(epochs, list)
        or not epochs
        or any(not isinstance(epoch, str) or not epoch.strip() for epoch in epochs)
        or len(epochs) != len(set(epochs))
    ):
        raise AnalysisReportError(
            "verification.search_epochs must be ordered unique nonblank strings"
        )
    verdicts = _positive_analysis_int(
        row["required_verdicts"], "verification.required_verdicts"
    )
    if verdicts != len(epochs):
        raise AnalysisReportError(
            "verification.required_verdicts must equal search epoch count"
        )
    threshold = row["minimum_support_score"]
    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, (int, float))
        or not math.isfinite(threshold)
        or not 0 <= threshold <= 1
    ):
        raise AnalysisReportError("verification.minimum_support_score is invalid")
    if row["indeterminate"] not in {"allow", "report"}:
        raise AnalysisReportError("verification.indeterminate is invalid")
    return row


def _claim_hash_for_diagnostic(diagnostic: Mapping[str, Any]) -> str:
    claim = {
        "packet_id": diagnostic["packet_id"],
        "packet_hash": diagnostic["packet_hash"],
        "obligation_id": diagnostic["packet_id"],
        "kind": diagnostic["packet_kind"],
        "code": diagnostic["code"],
        "classification": diagnostic["classification"],
        "statement": diagnostic["summary"],
        "evidence": [
            {
                field: item[field]
                for field in (
                    "role",
                    "path",
                    "start_line",
                    "end_line",
                    "excerpt_sha256",
                )
            }
            for item in diagnostic["evidence"]
        ],
    }
    return hashlib.sha256(canonical_json_bytes(claim)).hexdigest()


def _validate_verification_evidence(value: object, name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise AnalysisReportError(f"{name} must be an array")
    for index, item in enumerate(value):
        _validate_evidence(item, f"{name}[{index}]")
    keys = [
        (
            item["role"],
            item["path"],
            item["start_line"],
            item["end_line"],
            item["excerpt_sha256"],
        )
        for item in value
    ]
    if keys != sorted(keys) or len(keys) != len(set(keys)):
        raise AnalysisReportError(f"{name} is not canonical and unique")
    return value


def _validate_verification_event(
    value: object,
    index: int,
    *,
    contract: Mapping[str, Any],
    diagnostic: Mapping[str, Any],
) -> str:
    name = f"verification.events[{index}]"
    row = _exact_record(value, _VERIFICATION_EVENT_FIELDS, name)
    if row["packet_id"] != diagnostic["packet_id"]:
        raise AnalysisReportError(f"{name}.packet_id does not match its finding")
    if row["packet_hash"] != diagnostic["packet_hash"]:
        raise AnalysisReportError(f"{name}.packet_hash does not match its finding")
    claim_hash = _analysis_digest(row["claim_hash"], f"{name}.claim_hash")
    if claim_hash != _claim_hash_for_diagnostic(diagnostic):
        raise AnalysisReportError(f"{name}.claim_hash does not recompute")
    verifier_packet_hash = _analysis_digest(
        row["verifier_packet_hash"], f"{name}.verifier_packet_hash"
    )
    expected_epochs = [
        {"base_search_epoch": epoch, "effective_search_epoch": epoch}
        for epoch in contract["search_epochs"]
    ]
    epochs = row["required_epochs"]
    if not isinstance(epochs, list):
        raise AnalysisReportError(f"{name}.required_epochs must be an array")
    for epoch_index, epoch in enumerate(epochs):
        _exact_record(
            epoch, _VERIFICATION_EPOCH_FIELDS, f"{name}.required_epochs[{epoch_index}]"
        )
    if epochs != expected_epochs:
        raise AnalysisReportError(f"{name}.required_epochs do not match contract")
    results = row["results"]
    if not isinstance(results, list) or len(results) != len(expected_epochs):
        raise AnalysisReportError(f"{name}.results do not match required epochs")
    observed: list[tuple[str, float]] = []
    for result_index, (result, epoch) in enumerate(zip(results, epochs, strict=True)):
        result_name = f"{name}.results[{result_index}]"
        result_row = _exact_record(result, _VERIFICATION_RESULT_FIELDS, result_name)
        if (
            result_row["base_search_epoch"] != epoch["base_search_epoch"]
            or result_row["effective_search_epoch"] != epoch["effective_search_epoch"]
        ):
            raise AnalysisReportError(f"{result_name} epoch does not match")
        inference_contract = {
            "verify_contract_version": contract["verify_contract_version"],
            "verifier_packet_hash": verifier_packet_hash,
            "claim_hash": claim_hash,
            "prompt": contract["prompt"],
            "provider": contract["provider"],
            "request": contract["request"],
            "base_search_epoch": epoch["base_search_epoch"],
            "effective_search_epoch": epoch["effective_search_epoch"],
        }
        expected_key = hashlib.sha256(
            canonical_json_bytes(inference_contract)
        ).hexdigest()
        if result_row["verify_key"] != expected_key:
            raise AnalysisReportError(f"{result_name}.verify_key does not recompute")
        verdict = result_row["verdict"]
        if verdict not in {"support", "refute", "indeterminate"}:
            raise AnalysisReportError(f"{result_name}.verdict is invalid")
        score = result_row["support_score"]
        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(score)
            or not 0 <= score <= 1
        ):
            raise AnalysisReportError(f"{result_name}.support_score is invalid")
        evidence = _validate_verification_evidence(
            result_row["evidence"], f"{result_name}.evidence"
        )
        if verdict in {"support", "refute"} and not evidence:
            raise AnalysisReportError(f"{result_name} verdict requires evidence")
        observed.append((verdict, float(score)))
    if any(verdict == "refute" for verdict, _score in observed):
        state = "disputed"
        context = "disputed_by_verifier"
    elif all(
        verdict == "support" and score >= contract["minimum_support_score"]
        for verdict, score in observed
    ):
        state = "independently_verified"
        context = "independently_verified"
    else:
        state = "verification_indeterminate"
        context = "verification_indeterminate"
    if row["aggregate_state"] != state or row["context"] != context:
        raise AnalysisReportError(f"{name} aggregate state/context do not recompute")
    if diagnostic["verification_state"] not in {
        context,
        "mechanically_verified",
        "human_verified",
        "human_rejected",
    }:
        raise AnalysisReportError(f"{name} conflicts with final policy context")
    return state


def _validate_verification(
    value: object,
    *,
    diagnostics: list[dict[str, Any]],
    status: str,
) -> None:
    row = _exact_record(value, _VERIFICATION_FIELDS, "verification")
    state = row["state"]
    if state not in {"disabled", "enabled"}:
        raise AnalysisReportError("verification.state is invalid")
    counts = _exact_record(
        row["aggregate_counts"],
        _VERIFICATION_COUNT_FIELDS,
        "verification.aggregate_counts",
    )
    normalized_counts = {
        name: _analysis_nonnegative_int(
            counts[name], f"verification.aggregate_counts.{name}"
        )
        for name in _VERIFICATION_COUNT_FIELDS
    }
    cache_hits = _analysis_nonnegative_int(row["cache_hits"], "verification.cache_hits")
    cache_misses = _analysis_nonnegative_int(
        row["cache_misses"], "verification.cache_misses"
    )
    provider_calls = _analysis_nonnegative_int(
        row["provider_calls"], "verification.provider_calls"
    )
    events = row["events"]
    if not isinstance(events, list):
        raise AnalysisReportError("verification.events must be an array")
    if state == "disabled":
        if (
            row["contract"] is not None
            or events
            or any(normalized_counts.values())
            or cache_hits
            or cache_misses
            or provider_calls
        ):
            raise AnalysisReportError("disabled verification must contain no work")
        if any(
            diagnostic["verification_state"]
            in {
                "verification_indeterminate",
                "independently_verified",
                "disputed_by_verifier",
            }
            for diagnostic in diagnostics
        ):
            raise AnalysisReportError(
                "disabled verification cannot project verifier policy contexts"
            )
        return
    contract = _validate_verification_contract(row["contract"])
    diagnostic_by_identity = {
        (
            diagnostic["packet_id"],
            diagnostic["packet_hash"],
            _claim_hash_for_diagnostic(diagnostic),
        ): diagnostic
        for diagnostic in diagnostics
    }
    if len(diagnostic_by_identity) != len(diagnostics):
        raise AnalysisReportError("semantic findings do not have unique verify claims")
    event_states: list[str] = []
    event_identities: list[tuple[str, str, str]] = []
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise AnalysisReportError(f"verification.events[{index}] must be an object")
        packet_id = event.get("packet_id")
        packet_hash = event.get("packet_hash")
        claim_hash = event.get("claim_hash")
        if not all(
            isinstance(item, str) for item in (packet_id, packet_hash, claim_hash)
        ):
            raise AnalysisReportError(
                f"verification.events[{index}] has invalid identity types"
            )
        identity = (
            cast(str, packet_id),
            cast(str, packet_hash),
            cast(str, claim_hash),
        )
        diagnostic = diagnostic_by_identity.get(identity)
        if diagnostic is None:
            raise AnalysisReportError(
                f"verification.events[{index}] has no matching semantic finding"
            )
        event_identities.append(identity)
        event_states.append(
            _validate_verification_event(
                event, index, contract=contract, diagnostic=diagnostic
            )
        )
    expected_order = [
        identity for identity in diagnostic_by_identity if identity in event_identities
    ]
    if event_identities != expected_order or len(event_identities) != len(
        set(event_identities)
    ):
        raise AnalysisReportError("verification.events are not ordered unique")
    expected_counts = {
        name: event_states.count(name) for name in _VERIFICATION_COUNT_FIELDS
    }
    if normalized_counts != expected_counts:
        raise AnalysisReportError("verification aggregate counts do not recompute")
    completed_work = len(events) * len(contract["search_epochs"])
    cache_off_shape = cache_hits == 0 and cache_misses == 0
    if not cache_off_shape and provider_calls > cache_misses:
        raise AnalysisReportError("verification provider calls exceed cache misses")
    if (
        status == "complete"
        and not diagnostics
        and (events or cache_hits or cache_misses or provider_calls)
    ):
        raise AnalysisReportError("verification with no findings must contain no work")
    if status == "complete" and (
        len(events) != len(diagnostics)
        or (
            provider_calls != completed_work
            if cache_off_shape
            else cache_hits + cache_misses != completed_work
        )
    ):
        raise AnalysisReportError("complete verification work does not recompute")


def _validate_analysis_report_source_shape(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    schema_version = value.get("schema_version")
    current = schema_version == 4 and not isinstance(schema_version, bool)
    expected_fields = (
        _ANALYSIS_REPORT_V4_FIELDS if current else _ANALYSIS_REPORT_V3_FIELDS
    )
    if set(value) != expected_fields:
        raise AnalysisReportError(
            f"analysis report schema {schema_version} does not match closed shape"
        )
    if isinstance(schema_version, bool) or schema_version not in {3, 4}:
        raise AnalysisReportError("analysis report schema_version must be 3 or 4")
    if value.get("artifact") != "backstitch-analysis-report":
        raise AnalysisReportError("analysis report artifact is invalid")
    scope = value.get("scope")
    semantic_status = value.get("semantic_status")
    currentness = value.get("artifact_currentness")
    provenance = value.get("source_provenance")
    if scope not in {"current_repository", "historical_snapshot"}:
        raise AnalysisReportError("analysis report scope is invalid")
    if value.get("artifact_integrity") != "valid":
        raise AnalysisReportError("analysis report artifact_integrity must be valid")
    if scope == "current_repository":
        if semantic_status not in {"evaluated", "not_run_all_skipped"}:
            raise AnalysisReportError("current semantic_status is invalid")
        if (currentness, provenance) != ("current", "captured_current"):
            raise AnalysisReportError(
                "current report currentness/provenance is invalid"
            )
    else:
        if semantic_status != "historical_replay":
            raise AnalysisReportError("historical semantic_status is invalid")
        valid_historical = {
            ("unverifiable", "claimed_unverified"),
            ("current", "compared_match"),
            ("stale", "compared_mismatch"),
        }
        if (currentness, provenance) not in valid_historical:
            raise AnalysisReportError(
                "historical report currentness/provenance is invalid"
            )
    source_snapshot = _validate_analysis_source_snapshot(value.get("source_snapshot"))
    _analysis_digest(
        value.get("packet_report_content_sha256"),
        "packet_report_content_sha256",
    )
    counts = _validate_analysis_alignment_projection(
        source_snapshot,
        value.get("alignment_summary"),
        value.get("alignment_audit"),
        value.get("deterministic_issues"),
        current=current,
    )
    _analysis_digest(value.get("packet_jsonl_sha256"), "packet_jsonl_sha256")
    _analysis_digest(value.get("result_jsonl_sha256"), "result_jsonl_sha256")
    status = value.get("status")
    if status not in {"complete", "incomplete", "failed"}:
        raise AnalysisReportError("analysis report status is invalid")
    exit_code = value.get("analysis_exit_code")
    if isinstance(exit_code, bool) or exit_code not in {0, 1, 2}:
        raise AnalysisReportError("analysis_exit_code must be 0, 1, or 2")
    count_names = (
        "packet_count",
        "result_count",
        "packet_warning_count",
        "cache_hits",
        "cache_misses",
        "provider_calls",
        "prompt_byte_count",
        "elapsed_milliseconds",
    )
    analysis_counts = {
        name: _analysis_nonnegative_int(value.get(name), name) for name in count_names
    }
    normalized_kind_counts: dict[str, dict[str, int]] | None = None
    if current:
        packet_schema_versions = value.get("packet_schema_versions")
        if packet_schema_versions not in ([3], [3, 4]) or any(
            isinstance(item, bool) for item in packet_schema_versions
        ):
            raise AnalysisReportError(
                "packet_schema_versions must be exactly [3] or [3, 4]"
            )
        raw_kind_counts = value.get("kind_counts")
        expected_populations = {
            "eligible",
            "emitted",
            "results",
            "cache_hits",
            "cache_misses",
            "provider_calls",
        }
        if (
            not isinstance(raw_kind_counts, dict)
            or set(raw_kind_counts) != expected_populations
        ):
            raise AnalysisReportError(
                "kind_counts does not match the closed population shape"
            )
        normalized_kind_counts = {}
        for population in (
            "eligible",
            "emitted",
            "results",
            "cache_hits",
            "cache_misses",
            "provider_calls",
        ):
            raw_counts = raw_kind_counts[population]
            if (
                not isinstance(raw_counts, dict)
                or set(raw_counts) != _CURRENT_COUNT_FIELDS
            ):
                raise AnalysisReportError(
                    f"kind_counts.{population} must contain all packet kinds"
                )
            normalized_kind_counts[population] = {
                packet_kind: _analysis_nonnegative_int(
                    raw_counts[packet_kind],
                    f"kind_counts.{population}.{packet_kind}",
                )
                for packet_kind in ("section", "invariant", "suppression")
            }
        aggregate_fields = {
            "emitted": "packet_count",
            "results": "result_count",
            "cache_hits": "cache_hits",
            "cache_misses": "cache_misses",
            "provider_calls": "provider_calls",
        }
        for population, aggregate in aggregate_fields.items():
            if (
                sum(normalized_kind_counts[population].values())
                != analysis_counts[aggregate]
            ):
                raise AnalysisReportError(
                    f"kind_counts.{population} does not equal {aggregate}"
                )
    if analysis_counts["packet_count"] != counts["selected"]:
        raise AnalysisReportError("packet_count must equal alignment_summary.selected")
    if analysis_counts["result_count"] > analysis_counts["packet_count"]:
        raise AnalysisReportError("result_count cannot exceed packet_count")
    if semantic_status == "evaluated" and analysis_counts["packet_count"] == 0:
        raise AnalysisReportError("evaluated report requires selected packets")
    if semantic_status == "not_run_all_skipped" and (
        analysis_counts["packet_count"] != 0
        or analysis_counts["result_count"] != 0
        or counts["active"] == 0
        or counts["active"] != counts["skipped"]
    ):
        raise AnalysisReportError("all-skipped report counts are invalid")
    selected_order = [
        item["obligation_id"]
        for item in value["alignment_audit"]
        if _audit_bucket(item) == "selected"
    ]
    selected_ids = set(selected_order)
    warning_debt = value.get("packet_warning_debt")
    if analysis_counts["packet_warning_count"] != 0 or warning_debt != []:
        raise AnalysisReportError(
            "packet warning count and debt must be zero and empty for schema 3"
        )
    finding_debt = value.get("finding_debt")
    if not isinstance(finding_debt, list):
        raise AnalysisReportError("finding_debt must be a list")
    for index, item in enumerate(finding_debt):
        _validate_finding_debt(
            item,
            index,
            current=True,
            suppression_allowed=current,
        )
    cost = value.get("estimated_cost_microusd")
    source = value.get("cost_rate_source")
    if cost is None:
        if source is not None:
            raise AnalysisReportError("cost_rate_source must be null when cost is null")
    else:
        _analysis_nonnegative_int(cost, "estimated_cost_microusd")
        _nonblank_string(source, "cost_rate_source")
    layers = value.get("effective_policy_layers")
    if (
        not isinstance(layers, list)
        or not layers
        or any(not isinstance(layer, str) or not layer.strip() for layer in layers)
        or len(layers) != len(set(layers))
    ):
        raise AnalysisReportError(
            "effective_policy_layers must be a nonempty unique string list"
        )
    diagnostics = value.get("semantic_diagnostics")
    if not isinstance(diagnostics, list):
        raise AnalysisReportError("semantic_diagnostics must be a list")
    authoritative = [
        _validate_diagnostic(
            item,
            index,
            set(layers),
            current=True,
            suppression_allowed=current,
        )
        for index, item in enumerate(diagnostics)
    ]
    diagnostic_identities = [
        (
            item["code"],
            item["packet_id"],
            item["packet_hash"],
            item["finding_hash"],
            item["verification_state"],
        )
        for item in diagnostics
    ]
    if len(diagnostic_identities) != len(set(diagnostic_identities)):
        raise AnalysisReportError("semantic_diagnostics contains duplicates")
    diagnostic_packet_ids = [item["packet_id"] for item in diagnostics]
    expected_diagnostic_order = [
        packet_id for packet_id in selected_order if packet_id in diagnostic_packet_ids
    ]
    if (
        len(diagnostic_packet_ids) != len(set(diagnostic_packet_ids))
        or diagnostic_packet_ids != expected_diagnostic_order
    ):
        raise AnalysisReportError(
            "semantic_diagnostics do not preserve unique selected packet order"
        )
    if not set(diagnostic_packet_ids).issubset(selected_ids):
        raise AnalysisReportError("semantic diagnostic packet is not selected")
    debt_identities = [
        (
            item["code"],
            item["packet_id"],
            item["packet_hash"],
            item["finding_hash"],
            item["verification_state"],
        )
        for item in finding_debt
    ]
    if len(debt_identities) != len(set(debt_identities)) or not set(
        debt_identities
    ).issubset(set(diagnostic_identities)):
        raise AnalysisReportError("finding_debt has invalid diagnostic identity")
    expected_debt_order = [
        identity for identity in diagnostic_identities if identity in debt_identities
    ]
    if debt_identities != expected_debt_order:
        raise AnalysisReportError("finding_debt does not preserve diagnostic order")
    unused = value.get("unused_dispositions")
    if not isinstance(unused, list):
        raise AnalysisReportError("unused_dispositions must be a list")
    for index, item in enumerate(unused):
        _validate_disposition(item, index, suppression_allowed=current)
    disposition_identities = [
        (item["code"], item["packet_id"], item["packet_hash"], item["finding_hash"])
        for item in unused
    ]
    if len(disposition_identities) != len(set(disposition_identities)):
        raise AnalysisReportError("unused_dispositions contains duplicates")
    raw_problems = value.get("problems")
    if not isinstance(raw_problems, list):
        raise AnalysisReportError("problems must be a list")
    stages = [
        _validate_problem_v3(item, index) for index, item in enumerate(raw_problems)
    ]
    expected_status = (
        "failed"
        if any(stage in _FAILED_REPORT_STAGES for stage in stages)
        else "incomplete"
        if stages or (finding_debt and exit_code == 2)
        else "complete"
    )
    if status != expected_status:
        raise AnalysisReportError(
            "analysis report status is inconsistent with problems"
        )
    prepublication_stages = [stage for stage in stages if stage != "output"]
    if prepublication_stages and exit_code != 2:
        raise AnalysisReportError("analysis_exit_code must be 2 for analysis problems")
    if not prepublication_stages and exit_code == 2 and not finding_debt:
        raise AnalysisReportError(
            "analysis_exit_code 2 requires a prepublication problem or finding debt"
        )
    if exit_code == 1 and not any(authoritative):
        raise AnalysisReportError(
            "analysis_exit_code 1 requires an authoritative diagnostic"
        )
    semantic_work_complete = status == "complete" or (
        not raw_problems and bool(finding_debt) and exit_code == 2
    )
    if semantic_work_complete:
        cache_off_shape = (
            analysis_counts["cache_hits"] == 0 and analysis_counts["cache_misses"] == 0
        )
        if cache_off_shape:
            if analysis_counts["provider_calls"] != analysis_counts["packet_count"]:
                raise AnalysisReportError(
                    "cache-off analyzer calls do not match packet count"
                )
        elif (
            analysis_counts["cache_hits"] + analysis_counts["cache_misses"]
            != analysis_counts["packet_count"]
            or analysis_counts["provider_calls"]
            > analysis_counts["cache_hits"] + analysis_counts["cache_misses"]
        ):
            raise AnalysisReportError("analyzer cache counters do not recompute")
        if normalized_kind_counts is not None:
            for packet_kind in ("section", "invariant", "suppression"):
                hits = normalized_kind_counts["cache_hits"][packet_kind]
                misses = normalized_kind_counts["cache_misses"][packet_kind]
                calls = normalized_kind_counts["provider_calls"][packet_kind]
                emitted = normalized_kind_counts["emitted"][packet_kind]
                if hits == 0 and misses == 0:
                    if calls != emitted:
                        raise AnalysisReportError(
                            f"cache-off {packet_kind} calls do not match emitted packets"
                        )
                elif hits + misses != emitted or calls > hits + misses:
                    raise AnalysisReportError(
                        f"{packet_kind} cache counters do not recompute"
                    )
    _validate_verification(
        value.get("verification"),
        diagnostics=diagnostics,
        status=("complete" if not raw_problems and finding_debt else status),
    )
    normalized = json.loads(canonical_json_bytes(value))
    assert isinstance(normalized, dict)
    return normalized


def _validate_analysis_report_shape(value: Mapping[str, Any]) -> dict[str, Any]:
    if value.get("schema_version") in {3, 4} and not isinstance(
        value.get("schema_version"), bool
    ):
        return _validate_analysis_report_source_shape(value)
    return _validate_analysis_report_v1_shape(value)


def _revalidate_result_jsonl(
    result_jsonl: bytes,
    packets: tuple[ValidatedSemanticPacket, ...],
) -> tuple[dict[str, Any], ...]:
    from backstitch.semantic_evidence import (
        SemanticResultError,
        revalidate_canonical_result,
    )

    if not result_jsonl:
        return ()
    if not result_jsonl.endswith(b"\n") or result_jsonl.endswith(b"\n\n"):
        raise AnalysisReportError("result_jsonl must end in exactly one newline")
    packet_rows = tuple(packet.to_dict() for packet in packets)
    packet_by_id = {row["packet_id"]: row for row in packet_rows}
    packet_order = [row["packet_id"] for row in packet_rows]
    rows: list[dict[str, Any]] = []
    for index, line in enumerate(lf_split(result_jsonl)):
        if not line.strip():
            raise AnalysisReportError("result_jsonl must not contain blank rows")
        try:
            parsed = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AnalysisReportError(
                f"result_jsonl row {index + 1} is not valid JSON: {exc}"
            ) from None
        if not isinstance(parsed, dict):
            raise AnalysisReportError(f"result_jsonl row {index + 1} must be an object")
        if canonical_json_bytes(parsed) != line:
            raise AnalysisReportError(
                f"result_jsonl row {index + 1} is not canonical JSON"
            )
        packet_id = parsed.get("packet_id")
        packet = packet_by_id.get(packet_id) if isinstance(packet_id, str) else None
        if packet is None:
            raise AnalysisReportError(
                f"result_jsonl row {index + 1} has no matching packet"
            )
        analysis_key = parsed.get("analysis_key")
        _analysis_digest(analysis_key, f"result_jsonl[{index}].analysis_key")
        try:
            rebuilt = revalidate_canonical_result(
                packet, parsed, analysis_key=cast(str, analysis_key)
            )
        except SemanticResultError as exc:
            raise AnalysisReportError(
                f"result_jsonl row {index + 1} is invalid: {exc}"
            ) from None
        rows.append(rebuilt.to_row())
    result_ids = [row["packet_id"] for row in rows]
    expected_order = [
        packet_id for packet_id in packet_order if packet_id in result_ids
    ]
    if len(result_ids) != len(set(result_ids)) or result_ids != expected_order:
        raise AnalysisReportError("result_jsonl rows are not unique packet order")
    return tuple(rows)


def _bind_diagnostics_to_results(
    report: Mapping[str, Any],
    results: tuple[dict[str, Any], ...],
    packets: tuple[ValidatedSemanticPacket, ...],
) -> dict[str, tuple[str, str, dict[str, Any]]]:
    from backstitch.semantic_verification import (
        build_verification_request,
        derive_verification_claim,
    )

    packet_by_id = {
        packet.to_dict()["packet_id"]: packet.to_dict() for packet in packets
    }
    findings = [row for row in results if row["classification"] != "ok"]
    finding_by_packet = {row["packet_id"]: row for row in findings}
    diagnostics = report["semantic_diagnostics"]
    diagnostic_ids = [item["packet_id"] for item in diagnostics]
    expected_ids = [row["packet_id"] for row in findings]
    if report["status"] != "failed" and diagnostic_ids != expected_ids:
        raise AnalysisReportError(
            "semantic diagnostics do not exactly project result findings"
        )
    if any(packet_id not in finding_by_packet for packet_id in diagnostic_ids):
        raise AnalysisReportError("semantic diagnostic has no result finding")
    expected_verification: dict[str, tuple[str, str, dict[str, Any]]] = {}
    for result in findings:
        packet = packet_by_id[result["packet_id"]]
        claim = derive_verification_claim(packet, result)
        request = build_verification_request(packet, claim)
        expected_verification[result["packet_id"]] = (
            claim.claim_hash,
            request.verifier_packet_hash,
            packet,
        )
    for index, diagnostic in enumerate(diagnostics):
        result = finding_by_packet[diagnostic["packet_id"]]
        expected_fields = {
            "classification": result["classification"],
            "packet_kind": result["kind"],
            "packet_id": result["packet_id"],
            "packet_hash": result["packet_hash"],
            "evidence": result["evidence"],
            "summary": result["summary"],
            "rationale": result["rationale"],
            "analysis_key": result["analysis_key"],
        }
        for field, expected in expected_fields.items():
            if canonical_json_bytes(diagnostic[field]) != canonical_json_bytes(
                expected
            ):
                raise AnalysisReportError(
                    f"semantic_diagnostics[{index}].{field} does not match result"
                )
    return expected_verification


def _bind_verification_to_results(
    verification: Mapping[str, Any],
    expected: Mapping[str, tuple[str, str, dict[str, Any]]],
    *,
    status: str,
) -> None:
    from backstitch.semantic_evidence import (
        SemanticResultError,
        normalize_packet_evidence,
    )

    if verification["state"] == "disabled":
        return
    events = verification["events"]
    event_ids = [event["packet_id"] for event in events]
    expected_ids = list(expected)
    if status != "failed" and event_ids != expected_ids:
        raise AnalysisReportError(
            "verification events do not exactly project result findings"
        )
    for event_index, event in enumerate(events):
        expectation = expected.get(event["packet_id"])
        if expectation is None:
            raise AnalysisReportError(
                f"verification.events[{event_index}] has no result finding"
            )
        claim_hash, verifier_packet_hash, packet = expectation
        if event["claim_hash"] != claim_hash:
            raise AnalysisReportError(
                f"verification.events[{event_index}].claim_hash does not match result"
            )
        if event["verifier_packet_hash"] != verifier_packet_hash:
            raise AnalysisReportError(
                "verification.events"
                f"[{event_index}].verifier_packet_hash does not match packet request"
            )
        for result_index, result in enumerate(event["results"]):
            coordinates = [
                {
                    field: evidence[field]
                    for field in ("role", "path", "start_line", "end_line")
                }
                for evidence in result["evidence"]
            ]
            try:
                rebuilt = normalize_packet_evidence(packet, coordinates)
            except SemanticResultError as exc:
                raise AnalysisReportError(
                    "verification.events"
                    f"[{event_index}].results[{result_index}] evidence is invalid: {exc}"
                ) from None
            if canonical_json_bytes(result["evidence"]) != canonical_json_bytes(
                [item.to_row() for item in rebuilt]
            ):
                raise AnalysisReportError(
                    "verification.events"
                    f"[{event_index}].results[{result_index}] evidence is not packet-bound"
                )


def _closed_counts(value: object, name: str) -> dict[str, int]:
    if not isinstance(value, dict) or set(value) != _COUNT_FIELDS:
        raise PacketReportError(f"{name} must contain exactly section and invariant")
    return {
        "section": _nonnegative_int(value["section"], f"{name}.section"),
        "invariant": _nonnegative_int(value["invariant"], f"{name}.invariant"),
    }


def _validate_packet_report_v1_shape(value: Mapping[str, Any]) -> dict[str, Any]:
    if set(value) != _PACKET_REPORT_V1_FIELDS:
        raise PacketReportError("packet report does not match the closed shape")
    if value.get("schema_version") != 1 or isinstance(
        value.get("schema_version"), bool
    ):
        raise PacketReportError("packet report schema_version must be 1")
    if value.get("artifact") != "backstitch-packet-report":
        raise PacketReportError("packet report artifact is invalid")
    digest = value.get("packet_jsonl_sha256")
    try:
        digest = _PACKET_VALIDATORS.digest(digest, "packet report digest")
    except PacketReportError:
        raise PacketReportError(
            "packet report digest must be lowercase SHA-256"
        ) from None
    kind = value.get("kind")
    if kind not in ("section", "invariant", "all"):
        raise PacketReportError("packet report kind is invalid")

    eligible = _closed_counts(value.get("eligible_counts"), "eligible_counts")
    emitted = _closed_counts(value.get("emitted_counts"), "emitted_counts")
    for packet_kind in ("section", "invariant"):
        if eligible[packet_kind] < emitted[packet_kind]:
            raise PacketReportError(
                f"eligible_counts.{packet_kind} must be at least emitted_counts"
            )
    if kind == "section" and emitted["invariant"] != 0:
        raise PacketReportError("section packet report cannot emit invariant packets")
    if kind == "invariant" and emitted["section"] != 0:
        raise PacketReportError("invariant packet report cannot emit section packets")

    warning_count = _nonnegative_int(
        value.get("packet_warning_count"), "packet_warning_count"
    )
    prompt_bytes = _nonnegative_int(value.get("prompt_byte_count"), "prompt_byte_count")
    raw_packets = value.get("packets")
    if not isinstance(raw_packets, list):
        raise PacketReportError("packet report packets must be a list")
    packets: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw_packets:
        if not isinstance(item, dict) or set(item) != _PACKET_IDENTITY_FIELDS:
            raise PacketReportError(
                "packet report identity must contain exactly packet_id and packet_hash"
            )
        packet_id = item.get("packet_id")
        packet_hash = item.get("packet_hash")
        if not isinstance(packet_id, str) or not packet_id.strip():
            raise PacketReportError("packet report packet_id must be nonblank")
        if packet_id in seen:
            raise PacketReportError("packet report contains a duplicate packet_id")
        seen.add(packet_id)
        try:
            packet_hash = _PACKET_VALIDATORS.digest(
                packet_hash, "packet report packet_hash"
            )
        except PacketReportError:
            raise PacketReportError(
                "packet report packet_hash must be lowercase SHA-256"
            ) from None
        packets.append({"packet_id": packet_id, "packet_hash": packet_hash})
    if emitted["section"] + emitted["invariant"] != len(packets):
        raise PacketReportError("emitted count mismatch with packet list")

    return {
        "schema_version": 1,
        "artifact": "backstitch-packet-report",
        "packet_jsonl_sha256": digest,
        "kind": kind,
        "eligible_counts": eligible,
        "emitted_counts": emitted,
        "packet_warning_count": warning_count,
        "prompt_byte_count": prompt_bytes,
        "packets": packets,
    }


def _packet_report_content_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    if value.get("schema_version") == 3:
        return {
            field: value[field]
            for field in (
                "schema_version",
                "artifact",
                "packet_schema_versions",
                "scope",
                "source_snapshot",
                "derivation_contract",
                "packet_jsonl_sha256",
                "packet_count",
                "packet_bytes",
                "selection_status",
                "readiness_counts",
                "alignment_audit",
                "deterministic_issues",
                "kind_counts",
                "packets",
            )
        }
    return {
        field: value[field]
        for field in (
            "schema_version",
            "artifact",
            "packet_schema_version",
            "scope",
            "source_snapshot",
            "derivation_contract",
            "packet_jsonl_sha256",
            "packet_count",
            "packet_bytes",
            "selection_status",
            "readiness_counts",
            "alignment_audit",
            "deterministic_issues",
            "packets",
        )
    }


def _packet_report_digest(value: object, name: str) -> str:
    return _PACKET_VALIDATORS.digest(value, name)


def _packet_report_nonblank(value: object, name: str) -> str:
    return _PACKET_VALIDATORS.nonblank(value, name)


def _audit_bucket(item: Mapping[str, Any]) -> str:
    if item["obligation_rung"] != "active":
        return "out_of_scope"
    if item["disposition"] == "skipped":
        return "skipped"
    if item["alignment_state"] == "complete":
        return "selected"
    return "alignment_debt"


def _packet_report_issue_error(
    item: Mapping[str, Any],
    *,
    index: int,
    occurrences: dict[tuple[object, ...], int],
    obligation_ids: frozenset[str],
) -> str | None:
    code = item.get("code")
    context = item.get("context")
    if not isinstance(code, str) or code not in ISSUE_CODES:
        return "unknown deterministic issue code"
    definition = default_registry().require(code)
    if definition.contexts:
        if not isinstance(context, str) or context not in definition.contexts:
            return "invalid deterministic issue context"
    elif context is not None:
        return "invalid deterministic issue context"
    if item.get("short_code") != short_code_for(code):
        return "deterministic issue short code does not match"
    if item.get("default_severity") != default_level_for(code, context):
        return "deterministic issue default severity does not match"
    if item.get("severity") not in {"error", "warning", "info"}:
        return "invalid deterministic issue severity"
    path = item.get("path")
    line = item.get("line")
    if path is not None and (not isinstance(path, str) or not path.strip()):
        return "invalid deterministic issue path"
    if isinstance(line, bool) or (
        line is not None and (not isinstance(line, int) or line < 1)
    ):
        return "invalid deterministic issue line"
    if not isinstance(item.get("message"), str) or not item["message"].strip():
        return "invalid deterministic issue message"
    obligation_id = item.get("obligation_id")
    if obligation_id is not None and obligation_id not in obligation_ids:
        return "deterministic issue obligation is not in the audit"
    base = (code, context, path, line, obligation_id)
    ordinal = occurrences.get(base, 0)
    occurrences[base] = ordinal + 1
    identity = {
        "code": code,
        "context": context,
        "path": path,
        "line": line,
        "obligation_id": obligation_id,
        "ordinal": ordinal,
    }
    expected = hashlib.sha256(canonical_json_bytes(identity)).hexdigest()
    if item.get("issue_identity") != expected:
        return f"deterministic issue identity does not recompute at index {index}"
    return None


def _packet_report_source_shape(value: Mapping[str, Any]) -> dict[str, Any]:
    schema_version = value.get("schema_version")
    current = schema_version == 3
    expected_fields = _PACKET_REPORT_V3_FIELDS if current else _PACKET_REPORT_V2_FIELDS
    if set(value) != expected_fields:
        raise PacketReportError(
            f"packet report schema {schema_version} does not match its closed shape"
        )
    if (
        schema_version not in {2, 3}
        or value.get("artifact") != "backstitch-packet-report"
    ):
        raise PacketReportError("packet report source identity is invalid")
    if value.get("scope") != "source_snapshot":
        raise PacketReportError("packet report schema/scope is invalid")
    if current:
        packet_versions = value.get("packet_schema_versions")
        if packet_versions not in ([3], [3, 4]):
            raise PacketReportError(
                "packet_schema_versions must be exactly [3] or [3, 4]"
            )
    elif value.get("packet_schema_version") != 3:
        raise PacketReportError("packet report schema/scope is invalid")
    source = value.get("source_snapshot")
    if not isinstance(source, dict) or set(source) != {
        "snapshot_hash",
        "file_count",
        "byte_count",
        "unreadable_count",
    }:
        raise PacketReportError("packet report source_snapshot is invalid")
    _packet_report_digest(source["snapshot_hash"], "source_snapshot.snapshot_hash")
    for field in ("file_count", "byte_count", "unreadable_count"):
        _nonnegative_int(source[field], f"source_snapshot.{field}")
    derivation = value.get("derivation_contract")
    contract_version_field = (
        "packet_contract_versions" if current else "packet_contract_version"
    )
    if not isinstance(derivation, dict) or set(derivation) != {
        "obligation_algorithm_version",
        "discovery_algorithm_version",
        contract_version_field,
        "normalization_version",
        "semantic_config_sha256",
    }:
        raise PacketReportError("packet report derivation_contract is invalid")
    for field in (
        "obligation_algorithm_version",
        "discovery_algorithm_version",
        "normalization_version",
    ):
        if (
            isinstance(derivation[field], bool)
            or not isinstance(derivation[field], int)
            or derivation[field] < 1
        ):
            raise PacketReportError(f"derivation_contract.{field} must be positive")
    if current:
        if derivation[contract_version_field] != packet_versions:
            raise PacketReportError(
                "derivation packet contract versions do not match row versions"
            )
    elif (
        isinstance(derivation[contract_version_field], bool)
        or not isinstance(derivation[contract_version_field], int)
        or derivation[contract_version_field] < 1
    ):
        raise PacketReportError(
            "derivation_contract.packet_contract_version must be positive"
        )
    _packet_report_digest(
        derivation["semantic_config_sha256"],
        "derivation_contract.semantic_config_sha256",
    )
    _packet_report_digest(value.get("packet_jsonl_sha256"), "packet_jsonl_sha256")
    packet_count = _nonnegative_int(value.get("packet_count"), "packet_count")
    _nonnegative_int(value.get("packet_bytes"), "packet_bytes")
    if value.get("selection_status") not in {"selected", "not_run_all_skipped"}:
        raise PacketReportError("packet report selection_status is invalid")
    counts = value.get("readiness_counts")
    count_fields = {
        "total",
        "active",
        "out_of_scope",
        "selected",
        "skipped",
        "alignment_debt",
        "blocked",
    }
    if not isinstance(counts, dict) or set(counts) != count_fields:
        raise PacketReportError("packet report readiness_counts are invalid")
    normalized_counts = {
        field: _nonnegative_int(counts[field], f"readiness_counts.{field}")
        for field in count_fields
    }
    if normalized_counts["total"] != (
        normalized_counts["out_of_scope"]
        + normalized_counts["selected"]
        + normalized_counts["skipped"]
        + normalized_counts["alignment_debt"]
        + normalized_counts["blocked"]
    ) or normalized_counts["active"] != (
        normalized_counts["selected"]
        + normalized_counts["skipped"]
        + normalized_counts["alignment_debt"]
        + normalized_counts["blocked"]
    ):
        raise PacketReportError("packet report readiness counts do not balance")
    if packet_count != normalized_counts["selected"]:
        raise PacketReportError("packet_count must equal readiness_counts.selected")
    if value["selection_status"] == "selected" and packet_count == 0:
        raise PacketReportError("selected packet report must contain a packet")
    if value["selection_status"] == "not_run_all_skipped" and (
        packet_count != 0
        or normalized_counts["active"] == 0
        or normalized_counts["active"] != normalized_counts["skipped"]
    ):
        raise PacketReportError("all-skipped packet report counts are invalid")

    audit = value.get("alignment_audit")
    audit_fields = {
        "obligation_id",
        "kind",
        "path",
        "start_line",
        "intent_state",
        "alignment_state",
        "disposition",
        "obligation_rung",
        "gate_state",
        "skip",
    }
    if not isinstance(audit, list) or len(audit) != normalized_counts["total"]:
        raise PacketReportError("packet report alignment_audit count is invalid")
    audit_order: list[tuple[object, ...]] = []
    for index, item in enumerate(audit):
        if not isinstance(item, dict) or set(item) != audit_fields:
            raise PacketReportError(f"alignment_audit[{index}] is invalid")
        if (
            item["kind"]
            not in (
                {"section", "invariant", "suppression"}
                if current
                else {"section", "invariant"}
            )
            or not _packet_report_nonblank(
                item["obligation_id"], f"alignment_audit[{index}].obligation_id"
            )
            or not _packet_report_nonblank(
                item["path"], f"alignment_audit[{index}].path"
            )
        ):
            raise PacketReportError(f"alignment_audit[{index}] identity is invalid")
        start_line = _nonnegative_int(
            item["start_line"], f"alignment_audit[{index}].start_line"
        )
        if start_line < 1:
            raise PacketReportError(
                f"alignment_audit[{index}].start_line must be positive"
            )
        if (
            item["intent_state"] != "identified"
            or item["alignment_state"]
            not in {"untraced", "partial", "complete", "invalid"}
            or item["disposition"] not in {"evaluate", "skipped"}
            or item["obligation_rung"]
            not in {"active", "planned", "exploratory", "meta"}
            or item["gate_state"] not in {"not_executable", "executable"}
        ):
            raise PacketReportError(f"alignment_audit[{index}] vocabulary is invalid")
        skip = item["skip"]
        if skip is not None:
            if not isinstance(skip, dict) or set(skip) != {"reason", "path", "line"}:
                raise PacketReportError(f"alignment_audit[{index}].skip is invalid")
            _packet_report_nonblank(
                skip["reason"], f"alignment_audit[{index}].skip.reason"
            )
            _packet_report_nonblank(skip["path"], f"alignment_audit[{index}].skip.path")
            if (
                _nonnegative_int(skip["line"], f"alignment_audit[{index}].skip.line")
                < 1
            ):
                raise PacketReportError(
                    f"alignment_audit[{index}].skip.line must be positive"
                )
        if (item["disposition"] == "skipped") != (skip is not None):
            raise PacketReportError(
                f"alignment_audit[{index}] skip/disposition mismatch"
            )
        expected_gate = (
            "executable"
            if item["obligation_rung"] == "active"
            and item["disposition"] == "evaluate"
            and item["alignment_state"] == "complete"
            else "not_executable"
        )
        if item["gate_state"] != expected_gate:
            raise PacketReportError(
                f"alignment_audit[{index}] gate state is inconsistent"
            )
        if item["kind"] == "section":
            spec_path, separator, section_id = item["obligation_id"].rpartition("#")
            if not separator or spec_path != item["path"] or not section_id:
                raise PacketReportError(
                    f"alignment_audit[{index}] section identity is inconsistent"
                )
        elif item["kind"] == "invariant" and not item["obligation_id"].startswith(
            "invariant::"
        ):
            raise PacketReportError(
                f"alignment_audit[{index}] invariant identity is inconsistent"
            )
        elif item["kind"] == "suppression":
            reference = item["obligation_id"].removeprefix("suppression::")
            if (
                item["obligation_id"] != f"suppression::{reference}"
                or not is_valid_suppression_reference(reference)
                or reference.rpartition("#")[0] != item["path"]
            ):
                raise PacketReportError(
                    f"alignment_audit[{index}] suppression identity is inconsistent"
                )
        audit_order.append((item["path"], item["start_line"], item["obligation_id"]))
    if audit_order != sorted(audit_order) or len(audit_order) != len(set(audit_order)):
        raise PacketReportError("packet report alignment_audit is not ordered unique")
    recomputed_counts = {
        "total": len(audit),
        "active": sum(item["obligation_rung"] == "active" for item in audit),
        "out_of_scope": 0,
        "selected": 0,
        "skipped": 0,
        "alignment_debt": 0,
        "blocked": 0,
    }
    for item in audit:
        recomputed_counts[_audit_bucket(item)] += 1
    if normalized_counts != recomputed_counts:
        raise PacketReportError(
            "packet report readiness counts do not recompute from alignment_audit"
        )

    issue_fields = {
        "issue_identity",
        "code",
        "short_code",
        "context",
        "severity",
        "default_severity",
        "path",
        "line",
        "message",
        "obligation_id",
    }
    issues = value.get("deterministic_issues")
    if not isinstance(issues, list):
        raise PacketReportError("packet report deterministic_issues must be an array")
    issue_occurrences: dict[tuple[object, ...], int] = {}
    obligation_ids = frozenset(item["obligation_id"] for item in audit)
    issue_order: list[tuple[object, ...]] = []
    for index, item in enumerate(issues):
        if (
            not isinstance(item, dict)
            or set(item) != issue_fields
            or not _packet_report_digest(
                item["issue_identity"], f"deterministic_issues[{index}].issue_identity"
            )
        ):
            raise PacketReportError(f"deterministic_issues[{index}] is invalid")
        problem = _packet_report_issue_error(
            item,
            index=index,
            occurrences=issue_occurrences,
            obligation_ids=obligation_ids,
        )
        if problem is not None:
            raise PacketReportError(f"deterministic_issues[{index}]: {problem}")
        issue_order.append(issue_sort_key(item))
    if issue_order != sorted(issue_order):
        raise PacketReportError(
            "packet report deterministic_issues are not in ordinary report order"
        )
    packets = value.get("packets")
    if not isinstance(packets, list) or len(packets) != packet_count:
        raise PacketReportError("packet report packets count is invalid")
    seen_packets: set[str] = set()
    for index, item in enumerate(packets):
        if not isinstance(item, dict) or set(item) != _PACKET_IDENTITY_FIELDS:
            raise PacketReportError(f"packets[{index}] identity is invalid")
        packet_id = _packet_report_nonblank(
            item["packet_id"], f"packets[{index}].packet_id"
        )
        if packet_id in seen_packets:
            raise PacketReportError("packet report contains duplicate packet IDs")
        seen_packets.add(packet_id)
        _packet_report_digest(item["packet_hash"], f"packets[{index}].packet_hash")
    selected_ids = [
        item["obligation_id"] for item in audit if _audit_bucket(item) == "selected"
    ]
    if [item["packet_id"] for item in packets] != selected_ids:
        raise PacketReportError(
            "packet report packet IDs do not match selected alignment audit rows"
        )
    if current:
        kind_counts = value.get("kind_counts")
        if not isinstance(kind_counts, dict) or set(kind_counts) != {
            "eligible",
            "emitted",
        }:
            raise PacketReportError("packet report kind_counts are invalid")
        normalized_kind_counts: dict[str, dict[str, int]] = {}
        for population in ("eligible", "emitted"):
            counts_value = kind_counts[population]
            if (
                not isinstance(counts_value, dict)
                or set(counts_value) != _CURRENT_COUNT_FIELDS
            ):
                raise PacketReportError(
                    f"kind_counts.{population} must contain all packet kinds"
                )
            normalized_kind_counts[population] = {
                packet_kind: _nonnegative_int(
                    counts_value[packet_kind],
                    f"kind_counts.{population}.{packet_kind}",
                )
                for packet_kind in ("section", "invariant", "suppression")
            }
        expected_kind_counts = {
            packet_kind: sum(
                item["kind"] == packet_kind and _audit_bucket(item) == "selected"
                for item in audit
            )
            for packet_kind in ("section", "invariant", "suppression")
        }
        if normalized_kind_counts["eligible"] != expected_kind_counts:
            raise PacketReportError(
                "packet report eligible kind counts do not recompute"
            )
        if normalized_kind_counts["emitted"] != expected_kind_counts:
            raise PacketReportError(
                "packet report emitted kind counts do not recompute"
            )
    expected_content_hash = hashlib.sha256(
        canonical_json_bytes(_packet_report_content_projection(value))
    ).hexdigest()
    if value.get("packet_report_content_sha256") != expected_content_hash:
        raise PacketReportError("packet_report_content_sha256 does not recompute")
    _packet_report_nonblank(value.get("tool_version"), "tool_version")
    created = _packet_report_nonblank(value.get("created_at"), "created_at")
    try:
        parsed = datetime.fromisoformat(created.replace("Z", "+00:00"))
    except ValueError:
        raise PacketReportError("created_at must be RFC 3339") from None
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise PacketReportError("created_at must be UTC")
    normalized = json.loads(canonical_json_bytes(value))
    assert isinstance(normalized, dict)
    return normalized


def _validate_packet_report_shape(value: Mapping[str, Any]) -> dict[str, Any]:
    if value.get("schema_version") in {2, 3}:
        return _packet_report_source_shape(value)
    return _validate_packet_report_v1_shape(value)


def _schema1_prompt_byte_count(
    packet_rows: tuple[dict[str, Any], ...],
    identities: Iterable[InferenceIdentity],
) -> int:
    frozen = tuple(identities)
    if len(frozen) != len(packet_rows):
        raise PacketReportError(
            "frozen inference identity count does not match schema-1 packets"
        )
    total = 0
    for row, identity in zip(packet_rows, frozen, strict=True):
        if identity.contract.get("packet_hash") != row["packet_hash"]:
            raise PacketReportError(
                "frozen inference identity does not match schema-1 packet"
            )
        total += len(model_request_bytes(row, instruction_bytes=identity.prompt_bytes))
    return total


def build_packet_report(
    *,
    packet_jsonl: bytes,
    packets: Iterable[ValidatedSemanticPacket],
    identities: Iterable[InferenceIdentity],
    kind: PacketReportKind,
    eligible_counts: Mapping[str, int],
) -> PacketReport:
    """Build a report from the exact final packet JSONL and emitted packets."""

    if not isinstance(packet_jsonl, bytes):
        raise PacketReportError("packet_jsonl must be exact bytes")
    packet_rows = tuple(packet.to_dict() for packet in packets)
    emitted = {
        "section": sum(row["kind"] == "section" for row in packet_rows),
        "invariant": sum(row["kind"] == "invariant" for row in packet_rows),
    }
    value = {
        "schema_version": 1,
        "artifact": "backstitch-packet-report",
        "packet_jsonl_sha256": hashlib.sha256(packet_jsonl).hexdigest(),
        "kind": kind,
        "eligible_counts": dict(eligible_counts),
        "emitted_counts": emitted,
        "packet_warning_count": sum(len(row["packet_warnings"]) for row in packet_rows),
        "prompt_byte_count": _schema1_prompt_byte_count(packet_rows, identities),
        "packets": [
            {"packet_id": row["packet_id"], "packet_hash": row["packet_hash"]}
            for row in packet_rows
        ],
    }
    return PacketReport.from_dict(value)


def _issue_obligation_id(runtime: ObligationRuntime, issue: Any) -> str | None:
    if issue.invariant_id is not None:
        candidate = f"invariant::{issue.invariant_id}"
        return candidate if runtime.inventory.get(candidate) is not None else None
    if issue.section_id is None:
        return None
    matches = [
        item.obligation_id
        for item in runtime.inventory.obligations
        if item.kind == "section"
        and item.path == issue.path
        and item.obligation_id.endswith(f"#{issue.section_id}")
    ]
    return matches[0] if len(matches) == 1 else None


def build_source_packet_report(
    runtime: ObligationRuntime,
    *,
    packet_jsonl: bytes,
    created_at: str | None = None,
) -> PacketReport:
    """Build the complete schema-3 current source packet report."""

    if not isinstance(packet_jsonl, bytes):
        raise PacketReportError("packet_jsonl must be exact bytes")
    if len(packet_jsonl) > runtime.settings.obligations.maximum_packet_bytes:
        raise PacketReportError("packet JSONL exceeds maximum_packet_bytes")
    if any(
        issue.severity in set(runtime.settings.diagnostics.fail_on)
        for issue in runtime.pipeline.report.issues
    ):
        raise PacketReportError(
            "current packet report cannot publish a failing deterministic run"
        )
    from backstitch.analysis_packets import (
        generate_source_aligned_packets,
        render_packets_jsonl,
    )

    regenerated = render_packets_jsonl(generate_source_aligned_packets(runtime)).encode(
        "utf-8"
    )
    if packet_jsonl != regenerated:
        raise PacketReportError(
            "packet JSONL does not byte-match the captured source derivation"
        )
    packets = load_packets_bytes(packet_jsonl, source="generated packet JSONL")
    if any(not packet.semantic_eligible for packet in packets):
        raise PacketReportError("current packet report requires packet schema 3 or 4")
    packet_rows = tuple(packet.to_dict() for packet in packets)
    packet_schema_versions = sorted(
        {cast(int, row["schema_version"]) for row in packet_rows}
    ) or [3]
    if packet_schema_versions not in ([3], [3, 4]):
        raise PacketReportError(
            "current packet population must contain schema 3, optionally with schema 4"
        )
    active = [
        item
        for item in runtime.inventory.obligations
        if item.obligation_rung == "active"
    ]
    selected = [
        item
        for item in active
        if item.disposition == "evaluate" and item.gate_state == "executable"
    ]
    skipped = [item for item in active if item.disposition == "skipped"]
    alignment_debt = [
        item
        for item in active
        if item.disposition == "evaluate" and item.gate_state != "executable"
    ]
    if not active:
        raise PacketReportError("current packet report cannot publish no-active intent")
    if alignment_debt:
        raise PacketReportError("current packet report cannot publish alignment debt")
    expected_ids = [item.obligation_id for item in selected]
    if [row["packet_id"] for row in packet_rows] != expected_ids:
        raise PacketReportError(
            "packet JSONL does not match the complete selected corpus"
        )
    for row in packet_rows:
        if row["source_snapshot"]["snapshot_hash"] != runtime.snapshot.snapshot_hash:
            raise PacketReportError("packet source snapshot does not match runtime")

    skip_by_obligation = {
        item.obligation_id: item for item in runtime.pipeline.artifacts.obligation_skips
    }
    audit = []
    for item in runtime.inventory.obligations:
        skip = skip_by_obligation.get(item.obligation_id)
        audit.append(
            {
                "obligation_id": item.obligation_id,
                "kind": item.kind,
                "path": item.path,
                "start_line": item.start_line,
                "intent_state": item.intent_state,
                "alignment_state": item.alignment_state,
                "disposition": item.disposition,
                "obligation_rung": item.obligation_rung,
                "gate_state": item.gate_state,
                "skip": None
                if skip is None
                else {"reason": skip.reason, "path": skip.path, "line": skip.line},
            }
        )
    audit.sort(
        key=lambda item: (item["path"], item["start_line"], item["obligation_id"])
    )

    issue_occurrences: dict[tuple[object, ...], int] = {}
    issue_rows: list[dict[str, object]] = []
    for issue in runtime.pipeline.report.issues:
        obligation_id = _issue_obligation_id(runtime, issue)
        base = (issue.code, issue.context, issue.path, issue.line, obligation_id)
        ordinal = issue_occurrences.get(base, 0)
        issue_occurrences[base] = ordinal + 1
        identity = {
            "code": issue.code,
            "context": issue.context,
            "path": issue.path,
            "line": issue.line,
            "obligation_id": obligation_id,
            "ordinal": ordinal,
        }
        issue_rows.append(
            {
                "issue_identity": hashlib.sha256(
                    canonical_json_bytes(identity)
                ).hexdigest(),
                "code": issue.code,
                "short_code": issue.short_code,
                "context": issue.context,
                "severity": issue.severity,
                "default_severity": issue.default_severity,
                "path": issue.path,
                "line": issue.line,
                "message": issue.message,
                "obligation_id": obligation_id,
            }
        )

    snapshot_identity = runtime.snapshot.identity_document()
    semantic_config = snapshot_identity.get("semantic_config")
    if not isinstance(semantic_config, dict):
        raise PacketReportError("runtime snapshot has no semantic configuration")
    out_of_scope = len(runtime.inventory.obligations) - len(active)
    readiness_counts = {
        "total": len(runtime.inventory.obligations),
        "active": len(active),
        "out_of_scope": out_of_scope,
        "selected": len(selected),
        "skipped": len(skipped),
        "alignment_debt": 0,
        "blocked": 0,
    }
    kind_counts = {
        packet_kind: sum(item.kind == packet_kind for item in selected)
        for packet_kind in ("section", "invariant", "suppression")
    }
    value: dict[str, object] = {
        "schema_version": 3,
        "artifact": "backstitch-packet-report",
        "packet_schema_versions": packet_schema_versions,
        "scope": "source_snapshot",
        "source_snapshot": {
            "snapshot_hash": runtime.snapshot.snapshot_hash,
            "file_count": runtime.snapshot.file_count,
            "byte_count": runtime.snapshot.byte_count,
            "unreadable_count": runtime.snapshot.unreadable_count,
        },
        "derivation_contract": {
            "obligation_algorithm_version": ALGORITHMS.obligation_algorithm_version,
            "discovery_algorithm_version": ALGORITHMS.discovery_algorithm_version,
            "packet_contract_versions": packet_schema_versions,
            "normalization_version": ALGORITHMS.normalization_version,
            "semantic_config_sha256": hashlib.sha256(
                canonical_json_bytes(semantic_config)
            ).hexdigest(),
        },
        "packet_jsonl_sha256": hashlib.sha256(packet_jsonl).hexdigest(),
        "packet_count": len(packet_rows),
        "packet_bytes": len(packet_jsonl),
        "selection_status": "selected" if packet_rows else "not_run_all_skipped",
        "readiness_counts": readiness_counts,
        "alignment_audit": audit,
        "deterministic_issues": issue_rows,
        "kind_counts": {
            "eligible": kind_counts,
            "emitted": dict(kind_counts),
        },
        "packets": [
            {"packet_id": row["packet_id"], "packet_hash": row["packet_hash"]}
            for row in packet_rows
        ],
        "packet_report_content_sha256": "",
        "tool_version": __version__,
        "created_at": created_at
        or datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    value["packet_report_content_sha256"] = hashlib.sha256(
        canonical_json_bytes(_packet_report_content_projection(value))
    ).hexdigest()
    report = PacketReport.from_dict(value)
    if (
        len(report.to_json_bytes())
        > runtime.settings.obligations.maximum_packet_report_bytes
    ):
        raise PacketReportError(
            "complete packet report exceeds maximum_packet_report_bytes"
        )
    return report


def validate_packet_report(
    report: PacketReport | Mapping[str, Any],
    *,
    packet_jsonl: bytes | None = None,
    packets: Iterable[ValidatedSemanticPacket] | None = None,
    identities: Iterable[InferenceIdentity] | None = None,
) -> PacketReport:
    """Validate shape and, when supplied, recompute packet-file facts."""

    validated = (
        report if isinstance(report, PacketReport) else PacketReport.from_dict(report)
    )
    value = validated.to_dict()
    if value["schema_version"] in {2, 3}:
        packet_values = tuple(packets) if packets is not None else None
        if packet_jsonl is not None:
            if value["packet_jsonl_sha256"] != hashlib.sha256(packet_jsonl).hexdigest():
                raise PacketReportError("packet digest mismatch")
            if value["packet_bytes"] != len(packet_jsonl):
                raise PacketReportError("packet byte count mismatch")
            try:
                loaded_values = load_packets_bytes(
                    packet_jsonl, source="packet report JSONL"
                )
            except ValueError as exc:
                raise PacketReportError(str(exc)) from None
            if packet_values is not None and [
                packet.to_dict() for packet in packet_values
            ] != [packet.to_dict() for packet in loaded_values]:
                raise PacketReportError(
                    "supplied packets do not match packet JSONL bytes"
                )
            packet_values = loaded_values
        if packet_values is not None:
            packet_rows = tuple(packet.to_dict() for packet in packet_values)
            if any(not packet.semantic_eligible for packet in packet_values):
                raise PacketReportError(
                    "source packet report requires current semantic packets"
                )
            versions = sorted(
                {cast(int, row["schema_version"]) for row in packet_rows}
            ) or [3]
            if value["schema_version"] == 2 and versions != [3]:
                raise PacketReportError("schema-2 report requires schema-3 packets")
            if (
                value["schema_version"] == 3
                and value["packet_schema_versions"] != versions
            ):
                raise PacketReportError("packet schema version population mismatch")
            expected_identities = [
                {"packet_id": row["packet_id"], "packet_hash": row["packet_hash"]}
                for row in packet_rows
            ]
            if value["packets"] != expected_identities:
                raise PacketReportError("packet identity mismatch")
            if value["packet_count"] != len(packet_rows):
                raise PacketReportError("packet count mismatch")
            if any(
                row["source_snapshot"]["snapshot_hash"]
                != value["source_snapshot"]["snapshot_hash"]
                for row in packet_rows
            ):
                raise PacketReportError("packet snapshot claim mismatch")
            derivation_hashes_by_version: dict[int, set[str]] = {}
            for row in packet_rows:
                derivation_hashes_by_version.setdefault(
                    cast(int, row["schema_version"]), set()
                ).add(row["source_snapshot"]["derivation_config_hash"])
            if any(len(hashes) > 1 for hashes in derivation_hashes_by_version.values()):
                raise PacketReportError(
                    "packet derivation configuration claims are inconsistent"
                )
            if value["schema_version"] == 3:
                emitted = {
                    packet_kind: sum(row["kind"] == packet_kind for row in packet_rows)
                    for packet_kind in ("section", "invariant", "suppression")
                }
                if value["kind_counts"]["emitted"] != emitted:
                    raise PacketReportError("packet emitted kind counts mismatch")
        return validated
    if packet_jsonl is not None:
        actual_digest = hashlib.sha256(packet_jsonl).hexdigest()
        if value["packet_jsonl_sha256"] != actual_digest:
            raise PacketReportError("packet digest mismatch")
    if packets is not None:
        packet_rows = tuple(packet.to_dict() for packet in packets)
        expected_identities = [
            {"packet_id": row["packet_id"], "packet_hash": row["packet_hash"]}
            for row in packet_rows
        ]
        if value["packets"] != expected_identities:
            raise PacketReportError("packet identity mismatch")
        expected_counts = {
            "section": sum(row["kind"] == "section" for row in packet_rows),
            "invariant": sum(row["kind"] == "invariant" for row in packet_rows),
        }
        if value["emitted_counts"] != expected_counts:
            raise PacketReportError("emitted count mismatch")
        expected_warning_count = sum(len(row["packet_warnings"]) for row in packet_rows)
        if value["packet_warning_count"] != expected_warning_count:
            raise PacketReportError("warning count mismatch")
        if identities is None:
            raise PacketReportError(
                "schema-1 packet validation requires frozen inference identities"
            )
        expected_prompt_bytes = _schema1_prompt_byte_count(packet_rows, identities)
        if value["prompt_byte_count"] != expected_prompt_bytes:
            raise PacketReportError("prompt bytes mismatch")
    return validated


def load_packet_report_bytes(
    content: bytes,
    *,
    source: Path | str = "<packet report bytes>",
    maximum_bytes: int | None = None,
) -> PacketReport:
    """Apply the byte ceiling before decoding/parsing the closed report."""

    if not isinstance(content, bytes):
        raise PacketReportError("packet report input must be exact bytes")
    if maximum_bytes is not None and (
        isinstance(maximum_bytes, bool)
        or not isinstance(maximum_bytes, int)
        or maximum_bytes < 1
    ):
        raise PacketReportError("packet report maximum_bytes must be positive")
    if maximum_bytes is not None and len(content) > maximum_bytes:
        raise PacketReportError("packet report exceeds maximum_packet_report_bytes")
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PacketReportError(
            f"packet report is not valid JSON: {source}: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise PacketReportError("packet report JSON must be an object")
    return PacketReport.from_dict(value)


def load_packet_report(path: Path, *, maximum_bytes: int | None = None) -> PacketReport:
    """Read exact report bytes, apply the ceiling, and validate the schema."""

    try:
        content = path.read_bytes()
    except OSError as exc:
        raise PacketReportError(
            f"packet report could not be read: {path}: {exc}"
        ) from exc
    return load_packet_report_bytes(content, source=path, maximum_bytes=maximum_bytes)


def validate_analysis_report(
    report: AnalysisReport | Mapping[str, Any],
    *,
    result_jsonl: bytes | None = None,
    packet_jsonl_sha256: str | None = None,
    packet_report: PacketReport | Mapping[str, Any] | None = None,
    packets: Iterable[ValidatedSemanticPacket] | None = None,
    expected_scope: str | None = None,
    expected_semantic_status: str | None = None,
    expected_artifact_currentness: str | None = None,
    expected_source_provenance: str | None = None,
) -> AnalysisReport:
    """Validate a closed report against independently known operation facts.

    Schemas 3 and 4 are paired contracts: callers must supply the validated
    immediately corresponding packet report so copied source/alignment fields
    cannot self-attest. The expected operation fields bind runtime authority.
    Schema 1 remains a bounded historical reader only.
    """

    untrusted_value: Mapping[str, Any]
    if isinstance(report, AnalysisReport):
        try:
            untrusted_value = report.to_dict()
        except (UnicodeDecodeError, json.JSONDecodeError, AssertionError) as exc:
            raise AnalysisReportError("analysis report bytes are invalid") from exc
    else:
        untrusted_value = report
    validated = AnalysisReport._from_shape(untrusted_value)
    value = validated.to_dict()
    schema_version = value["schema_version"]
    expected_fields = {
        "scope": expected_scope,
        "semantic_status": expected_semantic_status,
        "artifact_currentness": expected_artifact_currentness,
        "source_provenance": expected_source_provenance,
    }
    if schema_version in {3, 4}:
        if packet_report is None:
            raise AnalysisReportError(
                f"analysis report schema {schema_version} requires its paired "
                "packet report"
            )
        if result_jsonl is None:
            raise AnalysisReportError(
                f"analysis report schema {schema_version} requires exact "
                "result_jsonl bytes"
            )
        packet_values = tuple(packets) if packets is not None else ()
        if not packet_values and value["packet_count"] != 0:
            raise AnalysisReportError(
                f"analysis report schema {schema_version} requires its "
                "validated packets"
            )
        expected_runtime_values = {
            "scope": expected_scope,
            "semantic_status": expected_semantic_status,
            "artifact_currentness": expected_artifact_currentness,
            "source_provenance": expected_source_provenance,
        }
        if any(expected is None for expected in expected_runtime_values.values()):
            raise AnalysisReportError(
                f"analysis report schema {schema_version} requires all expected "
                "runtime authority fields"
            )
        reconstructed_packet_jsonl = b"".join(
            canonical_json_bytes(packet.to_dict()) + b"\n" for packet in packet_values
        )
        validated_packet_report = validate_packet_report(
            packet_report,
            packet_jsonl=reconstructed_packet_jsonl,
            packets=packet_values,
        )
        packet_value = validated_packet_report.to_dict()
        required_packet_report_schema = 3 if schema_version == 4 else 2
        if packet_value["schema_version"] != required_packet_report_schema:
            raise AnalysisReportError(
                f"analysis report schema {schema_version} requires packet report "
                f"schema {required_packet_report_schema}"
            )
        paired_fields = {
            "packet_jsonl_sha256": "packet_jsonl_sha256",
            "packet_count": "packet_count",
            "source_snapshot": "source_snapshot",
            "packet_report_content_sha256": "packet_report_content_sha256",
            "alignment_summary": "readiness_counts",
            "alignment_audit": "alignment_audit",
            "deterministic_issues": "deterministic_issues",
        }
        for analysis_field, packet_field in paired_fields.items():
            if canonical_json_bytes(value[analysis_field]) != canonical_json_bytes(
                packet_value[packet_field]
            ):
                raise AnalysisReportError(
                    f"analysis report {analysis_field} does not match packet report"
                )
        if schema_version == 4:
            if (
                value["packet_schema_versions"]
                != packet_value["packet_schema_versions"]
            ):
                raise AnalysisReportError(
                    "analysis report packet_schema_versions does not match packet "
                    "report"
                )
            for population in ("eligible", "emitted"):
                if (
                    value["kind_counts"][population]
                    != packet_value["kind_counts"][population]
                ):
                    raise AnalysisReportError(
                        f"analysis report kind_counts.{population} does not match "
                        "packet report"
                    )
        packet_hashes = {
            item["packet_id"]: item["packet_hash"] for item in packet_value["packets"]
        }
        for collection_name in ("semantic_diagnostics", "finding_debt"):
            for index, item in enumerate(value[collection_name]):
                if packet_hashes.get(item["packet_id"]) != item["packet_hash"]:
                    raise AnalysisReportError(
                        f"analysis report {collection_name}[{index}] packet identity "
                        "does not match packet report"
                    )
        results = _revalidate_result_jsonl(result_jsonl, packet_values)
        if value["result_count"] != len(results):
            raise AnalysisReportError(
                "analysis report result_count does not match validated results"
            )
        if schema_version == 4:
            result_kind_counts = {
                packet_kind: sum(row["kind"] == packet_kind for row in results)
                for packet_kind in ("section", "invariant", "suppression")
            }
            if value["kind_counts"]["results"] != result_kind_counts:
                raise AnalysisReportError(
                    "analysis report result kind counts do not match validated results"
                )
        verification_expectations = _bind_diagnostics_to_results(
            value, results, packet_values
        )
        _bind_verification_to_results(
            value["verification"],
            verification_expectations,
            status=value["status"],
        )
        expected_selection_status = (
            "not_run_all_skipped" if value["packet_count"] == 0 else "selected"
        )
        if packet_value["selection_status"] != expected_selection_status:
            raise AnalysisReportError(
                "analysis semantic status does not match packet selection status"
            )
        for field, expected in expected_runtime_values.items():
            if value[field] != expected:
                raise AnalysisReportError(
                    f"analysis report {field} does not match runtime operation"
                )
    elif (
        packet_report is not None
        or packets is not None
        or any(expected is not None for expected in expected_fields.values())
    ):
        raise AnalysisReportError(
            "source-report packet/scope arguments cannot validate legacy analysis "
            "report"
        )
    if result_jsonl is not None:
        if not isinstance(result_jsonl, bytes):
            raise AnalysisReportError("result_jsonl must be exact bytes")
        if value["result_jsonl_sha256"] != hashlib.sha256(result_jsonl).hexdigest():
            raise AnalysisReportError("analysis report result digest mismatch")
        if not result_jsonl:
            result_rows = 0
        else:
            if not result_jsonl.endswith(b"\n") or result_jsonl.endswith(b"\n\n"):
                raise AnalysisReportError(
                    "result_jsonl must end in exactly one newline"
                )
            lines = lf_split(result_jsonl)
            if any(not line.strip() for line in lines):
                raise AnalysisReportError("result_jsonl must not contain blank rows")
            result_rows = len(lines)
        if value["result_count"] != result_rows:
            raise AnalysisReportError(
                "analysis report result_count does not match result JSONL"
            )
    if packet_jsonl_sha256 is not None:
        expected = _analysis_digest(packet_jsonl_sha256, "packet_jsonl_sha256")
        if value["packet_jsonl_sha256"] != expected:
            raise AnalysisReportError("analysis report packet digest mismatch")
    return validated


def load_analysis_report(
    path: Path,
    *,
    result_jsonl: bytes | None = None,
    packet_jsonl_sha256: str | None = None,
    packet_report: PacketReport | Mapping[str, Any] | None = None,
    packets: Iterable[ValidatedSemanticPacket] | None = None,
    expected_scope: str | None = None,
    expected_semantic_status: str | None = None,
    expected_artifact_currentness: str | None = None,
    expected_source_provenance: str | None = None,
) -> AnalysisReport:
    """Load an analysis report as ordinary JSON and enforce the closed shape."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AnalysisReportError(
            f"analysis report is not valid JSON: {path}: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise AnalysisReportError("analysis report JSON must be an object")
    return validate_analysis_report(
        value,
        result_jsonl=result_jsonl,
        packet_jsonl_sha256=packet_jsonl_sha256,
        packet_report=packet_report,
        packets=packets,
        expected_scope=expected_scope,
        expected_semantic_status=expected_semantic_status,
        expected_artifact_currentness=expected_artifact_currentness,
        expected_source_provenance=expected_source_provenance,
    )
