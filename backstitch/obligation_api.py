"""Typed Backstitch obligation reads and transport-neutral envelopes.

Spec: docs/specs/02-backstitch-core.md [SC-5], [SC-17]
Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-8], [EVC-8.4],
[EVC-8.5], [EVC-8.7]
"""

from __future__ import annotations

import base64
import hashlib
import json
import sys
import time
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, replace
from dataclasses import field as dataclass_field
from pathlib import Path
from typing import Any, Literal, cast

from backstitch.canonical import canonical_json_bytes
from backstitch.config import ProfileConfig
from backstitch.evidence_discovery import (
    CandidateNeighbor,
    CandidateSource,
    EvidenceCandidate,
    EvidenceDiscoveryError,
    candidate_order,
    get_candidate_by_id,
    get_candidate_neighbors,
    get_candidate_source,
)
from backstitch.evidence_summary import evidence_item_order
from backstitch.grammar import candidate_ref_digest, is_sha256_hex
from backstitch.markdown_specs import MarkdownParseMemo
from backstitch.obligation_runtime import (
    ObligationRuntime,
    build_obligation_runtime_from_snapshot,
    capture_obligation_snapshot,
)
from backstitch.obligations import (
    AlignmentState,
    BlockingReasonCode,
    CandidateCounts,
    GateState,
    GuidanceCode,
    ObligationInventory,
    ObligationKind,
    ObligationRecord,
    with_candidate_counts,
)
from backstitch.operation_progress import (
    COOPERATIVE_TOLERANCE_MILLISECONDS,
    DEADLINE_PHASES,
    OperationDeadlineExceeded,
    OperationProgress,
    ProgressSink,
)
from backstitch.repository_snapshot import RepositorySnapshot, SnapshotCaptureError
from backstitch.settings import BackstitchSettings, ObligationSettings

ObligationOperation = Literal[
    "obligation.list",
    "obligation.get",
    "obligation.summarize_evidence",
    "obligation.find_evidence",
    "obligation.get_candidate",
]

OperationProblemCode = Literal[
    "INVALID_INPUT",
    "UNSUPPORTED_PLATFORM",
    "NOT_FOUND",
    "CURSOR_INVALID",
    "SNAPSHOT_UNSTABLE",
    "SOURCE_UNREADABLE",
    "BUDGET_EXHAUSTED",
    "DEADLINE_EXCEEDED",
    "INTERNAL_ERROR",
]


@dataclass(frozen=True)
class ObligationRequest:
    """One normalized, transport-independent obligation read."""

    operation: ObligationOperation
    repo_root: Path
    profile: ProfileConfig
    settings: BackstitchSettings
    obligation_id: str | None = None
    candidate_id: str | None = None
    cursor: str | None = None
    limit: int | None = None
    list_filters: ListFilters = dataclass_field(default_factory=lambda: ListFilters())


_ALIGNMENT_STATE_ORDER: tuple[AlignmentState, ...] = (
    "untraced",
    "partial",
    "complete",
    "invalid",
)
_GATE_STATE_ORDER: tuple[GateState, ...] = ("not_executable", "executable")
_KIND_ORDER: tuple[ObligationKind, ...] = ("section", "invariant", "suppression")
_REASON_ORDER: tuple[BlockingReasonCode, ...] = (
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


@dataclass(frozen=True, slots=True)
class ListFilters:
    """One normalized filter identity for list selection and pagination."""

    active_only: bool = False
    alignment_states: frozenset[AlignmentState] = frozenset()
    gate_states: frozenset[GateState] = frozenset()
    kinds: frozenset[ObligationKind] = frozenset()
    reasons: frozenset[BlockingReasonCode] = frozenset()

    def __post_init__(self) -> None:
        if not isinstance(self.active_only, bool):
            raise ValueError("active_only must be a boolean")
        for values, allowed, label in (
            (self.alignment_states, set(_ALIGNMENT_STATE_ORDER), "alignment state"),
            (self.gate_states, set(_GATE_STATE_ORDER), "gate state"),
            (self.kinds, set(_KIND_ORDER), "kind"),
            (self.reasons, set(_REASON_ORDER), "reason"),
        ):
            if not isinstance(values, frozenset) or not values <= allowed:
                raise ValueError(f"list filter has an invalid {label}")

    @property
    def active(self) -> bool:
        return bool(
            self.active_only
            or self.alignment_states
            or self.gate_states
            or self.kinds
            or self.reasons
        )

    def to_row(self) -> dict[str, object]:
        return {
            "active_only": self.active_only,
            "alignment_states": [
                value
                for value in _ALIGNMENT_STATE_ORDER
                if value in self.alignment_states
            ],
            "gate_states": [
                value for value in _GATE_STATE_ORDER if value in self.gate_states
            ],
            "kinds": [value for value in _KIND_ORDER if value in self.kinds],
            "reasons": [value for value in _REASON_ORDER if value in self.reasons],
        }

    def accepts(self, obligation: ObligationRecord) -> bool:
        if self.active_only and not (
            obligation.obligation_rung == "active"
            and obligation.disposition == "evaluate"
        ):
            return False
        if (
            self.alignment_states
            and obligation.alignment_state not in self.alignment_states
        ):
            return False
        if self.gate_states and obligation.gate_state not in self.gate_states:
            return False
        if self.kinds and obligation.kind not in self.kinds:
            return False
        reason_codes = {item.code for item in obligation.blocking_reasons}
        return not self.reasons or bool(self.reasons & reason_codes)


@dataclass(frozen=True)
class ObligationResult:
    """One complete obligation envelope plus application failure state."""

    envelope: dict[str, Any]
    failed: bool
    resolved_root: str


_GUIDANCE: dict[GuidanceCode, tuple[str, str]] = {
    "ADD_OR_CONFIGURE_SPEC_INTENT": (
        "No addressable specification intent was found.",
        "Add an ID-bearing spec section or configure the intended spec roots.",
    ),
    "FIX_OBLIGATION_IDENTITY": (
        "Some specification intent has no unique supported obligation identity.",
        "Fix the reported section or invariant identity in repository source.",
    ),
    "ADD_RECIPROCAL_MAPPING": (
        "The code declaration has no reciprocal specification mapping.",
        "Review and add a supported mapping in the owning specification section.",
    ),
    "ADD_RECIPROCAL_BACKLINK": (
        "The specification mapping has no reciprocal code backlink.",
        "Review and add a supported backlink in the mapped implementation or test.",
    ),
    "ADD_INVARIANT_BIND": (
        "The invariant has no declared implementation target.",
        "For a spec invariant, review and add an _Implementation mapping_ in its owning section; a code invariant already targets its declaring Python owner.",
    ),
    "ADD_BINDING_TEST": (
        "The invariant has no binding test.",
        "Review and add a supported binding-test declaration under a test root.",
    ),
    "REVIEW_UNTRACED_CANDIDATE": (
        "Deterministic discovery found a candidate with no complete declaration.",
        "Review the candidate and any suggested source trace edits.",
    ),
    "REVIEW_CONFLICTED_TRACE": (
        "The declared trace is ambiguous or conflicted.",
        "Run backstitch check and repair its reported source declarations before treating the obligation as executable.",
    ),
    "REVIEW_SKIP_REASON": (
        "The obligation carries a source-authored skip disposition.",
        "Run backstitch check --show-suppressions and correlate this obligation ID to review the source skip reason and alignment state.",
    ),
    "RUN_DETERMINISTIC_CHECK": (
        "Repository trace declarations should be checked as a whole.",
        "Run backstitch check after the reviewed source change.",
    ),
    "RUN_CURRENT_ANALYSIS": (
        "The obligation is ready for current-source semantic analysis.",
        "Run backstitch analyze with the repository root when semantic review is wanted.",
    ),
}

_CURSOR_KEYS = frozenset(
    {
        "cursor_version",
        "operation",
        "snapshot_hash",
        "obligation_id",
        "selector",
        "filters",
        "limit",
        "after",
    }
)
_PROBLEM_DETAIL_KEYS: dict[OperationProblemCode, frozenset[str]] = {
    "INVALID_INPUT": frozenset({"field", "reason"}),
    "UNSUPPORTED_PLATFORM": frozenset({"platform"}),
    "NOT_FOUND": frozenset({"identity"}),
    "CURSOR_INVALID": frozenset({"reason"}),
    "SNAPSHOT_UNSTABLE": frozenset({"attempts"}),
    "SOURCE_UNREADABLE": frozenset({"path", "error_class"}),
    "BUDGET_EXHAUSTED": frozenset({"budget", "limit", "observed"}),
    "DEADLINE_EXCEEDED": frozenset(
        {
            "limit_milliseconds",
            "phase",
            "configured_key",
            "cooperative_tolerance_milliseconds",
        }
    ),
    "INTERNAL_ERROR": frozenset(),
}
_BUDGET_NAMES = frozenset(
    {
        "candidate_items",
        "catalog_items",
        "snapshot_files",
        "file_bytes",
        "snapshot_bytes",
        "work_units",
        "response_bytes",
    }
)


class CursorError(ValueError):
    """A page cursor is malformed or does not address this exact query."""


def _monotonic() -> float:
    """Return the operation clock through one deterministic test seam."""

    return time.monotonic()


def encode_page_cursor(
    *,
    operation: str,
    snapshot_hash: str,
    obligation_id: str | None,
    selector: str,
    limit: int,
    after: tuple[object, ...],
    filters: dict[str, object] | None = None,
) -> str:
    """Encode the exact query context and last-row ordering tuple."""

    value = {
        "cursor_version": 2,
        "operation": operation,
        "snapshot_hash": snapshot_hash,
        "obligation_id": obligation_id,
        "selector": selector,
        "filters": filters or {},
        "limit": limit,
        "after": list(after),
    }
    raw = canonical_json_bytes(value)
    payload = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    return f"{payload}.{hashlib.sha256(raw).hexdigest()}"


def decode_page_cursor(
    token: str,
    *,
    operation: str,
    snapshot_hash: str,
    obligation_id: str | None,
    selector: str,
    limit: int,
    filters: dict[str, object] | None = None,
) -> dict[str, Any]:
    """Validate one cursor against the complete current query context."""

    try:
        payload, digest = token.split(".")
        if (
            not payload
            or "=" in payload
            or any(
                character
                not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
                for character in payload
            )
            or not is_sha256_hex(digest)
        ):
            raise ValueError
        padding = "=" * (-len(payload) % 4)
        raw = base64.b64decode(payload + padding, altchars=b"-_", validate=True)
    except (ValueError, UnicodeEncodeError) as exc:
        raise CursorError("cursor has invalid encoding or digest") from exc
    if hashlib.sha256(raw).hexdigest() != digest:
        raise CursorError("cursor digest does not match its payload")
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CursorError("cursor payload is not canonical JSON") from exc
    if (
        not isinstance(value, dict)
        or set(value) != _CURSOR_KEYS
        or canonical_json_bytes(value) != raw
        or isinstance(value.get("cursor_version"), bool)
        or not isinstance(value.get("cursor_version"), int)
        or value.get("cursor_version") != 2
        or not isinstance(value.get("operation"), str)
        or not isinstance(value.get("snapshot_hash"), str)
        or (
            value.get("obligation_id") is not None
            and not isinstance(value.get("obligation_id"), str)
        )
        or not isinstance(value.get("selector"), str)
        or not isinstance(value.get("filters"), dict)
        or isinstance(value.get("limit"), bool)
        or not isinstance(value.get("limit"), int)
        or value.get("limit", 0) < 1
        or not isinstance(value.get("after"), list)
    ):
        raise CursorError("cursor payload has an invalid shape")
    expected = {
        "operation": operation,
        "snapshot_hash": snapshot_hash,
        "obligation_id": obligation_id,
        "selector": selector,
        "filters": filters or {},
        "limit": limit,
    }
    for field, expected_value in expected.items():
        if value.get(field) != expected_value:
            raise CursorError(f"cursor {field} does not match this request")
    return value


def guidance_rows(codes: Iterable[GuidanceCode]) -> list[dict[str, str]]:
    """Project ordered guidance codes into closed, line-safe advice rows."""

    rows: list[dict[str, str]] = []
    for code in codes:
        message, action = _GUIDANCE[code]
        rows.append({"code": code, "message": message, "action": action})
    return rows


def problem_envelope(  # noqa: C901 approved [SC-17.1] RUFF-SUP-051 exception
    *,
    operation: str,
    snapshot: dict[str, object] | None,
    code: OperationProblemCode,
    message: str,
    action: str,
    details: dict[str, object],
) -> dict[str, Any]:
    """Return one closed failure envelope for an obligation read."""

    if code not in _PROBLEM_DETAIL_KEYS:
        raise ValueError(f"unknown obligation problem code: {code}")
    if set(details) != _PROBLEM_DETAIL_KEYS[code]:
        raise ValueError(f"{code} details have an invalid shape")
    for field in ("message", "action"):
        line_value = message if field == "message" else action
        if not line_value.strip() or any(
            ord(character) < 32 or ord(character) == 127 for character in line_value
        ):
            raise ValueError(f"problem {field} must be nonblank and line-safe")
        if len(line_value.encode("utf-8")) > 4096:
            raise ValueError(f"problem {field} exceeds its closed byte limit")
    for field, value in details.items():
        if field in {
            "attempts",
            "limit",
            "observed",
            "limit_milliseconds",
            "cooperative_tolerance_milliseconds",
        }:
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"problem detail {field} must be nonnegative")
        elif (
            not isinstance(value, str)
            or not value.strip()
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
            or len(value.encode("utf-8")) > 4096
        ):
            raise ValueError(f"problem detail {field} must be nonblank and line-safe")
    if code == "BUDGET_EXHAUSTED" and details["budget"] not in _BUDGET_NAMES:
        raise ValueError("problem budget is not in the closed vocabulary")
    if code == "SOURCE_UNREADABLE" and details["error_class"] not in {
        "permission",
        "not_regular",
        "io",
    }:
        raise ValueError("problem error_class is not in the closed vocabulary")
    if code == "DEADLINE_EXCEEDED" and (
        details["phase"] not in DEADLINE_PHASES
        or details["configured_key"] != "obligations.maximum_call_seconds"
        or details["cooperative_tolerance_milliseconds"]
        != COOPERATIVE_TOLERANCE_MILLISECONDS
    ):
        raise ValueError("deadline details are not in the closed vocabulary")

    return {
        "schema_version": 2,
        "operation": operation,
        "snapshot": snapshot,
        "result": None,
        "guidance": [],
        "problems": [
            {
                "code": code,
                "message": message,
                "action": action,
                "details": details,
            }
        ],
    }


def apply_response_byte_budget(
    envelope: dict[str, Any], limits: ObligationSettings
) -> tuple[dict[str, Any], bool]:
    """Apply the transport-neutral response budget to canonical core JSON."""

    observed = len(canonical_json_bytes(envelope))
    if observed <= limits.maximum_response_bytes:
        return envelope, False
    snapshot_value = envelope.get("snapshot")
    snapshot = cast(
        dict[str, object] | None,
        snapshot_value if isinstance(snapshot_value, dict) else None,
    )
    return (
        problem_envelope(
            operation=str(envelope["operation"]),
            snapshot=snapshot,
            code="BUDGET_EXHAUSTED",
            message="The complete obligation response exceeds its configured budget.",
            action="Raise maximum_response_bytes or request a smaller page.",
            details={
                "budget": "response_bytes",
                "limit": limits.maximum_response_bytes,
                "observed": observed,
            },
        ),
        True,
    )


def _list_ordering(row: dict[str, Any]) -> tuple[object, ...]:
    entry_type_order = {"unaddressable_intent": 0, "obligation": 1}
    if row["entry_type"] == "obligation":
        return (
            row["path"],
            row["start_line"],
            entry_type_order["obligation"],
            row["entry_identity"],
        )
    diagnostic = row["diagnostic"]
    assert isinstance(diagnostic, dict)
    return (
        diagnostic["path"],
        diagnostic["line"] or 0,
        entry_type_order["unaddressable_intent"],
        row["entry_identity"],
    )


def _valid_list_after(value: object) -> bool:
    if not isinstance(value, list) or len(value) != 4:
        return False
    path, line, entry_type_order, identity = value
    return (
        _valid_cursor_path(path)
        and isinstance(line, int)
        and not isinstance(line, bool)
        and line >= 0
        and isinstance(entry_type_order, int)
        and not isinstance(entry_type_order, bool)
        and entry_type_order in {0, 1}
        and _valid_cursor_string(identity)
    )


def _valid_cursor_string(value: object, *, empty: bool = False) -> bool:
    return (
        isinstance(value, str)
        and (empty or bool(value))
        and unicodedata.normalize("NFC", value) == value
        and "\r" not in value
        and "\n" not in value
    )


def _valid_preserved_cursor_string(value: object) -> bool:
    return isinstance(value, str) and "\r" not in value and "\n" not in value


def _valid_cursor_path(value: object) -> bool:
    return (
        _valid_cursor_string(value)
        and isinstance(value, str)
        and not value.startswith("/")
        and all(part not in {"", ".", ".."} for part in value.split("/"))
    )


def _valid_evidence_after(value: object) -> bool:
    if not isinstance(value, list) or len(value) != 7:
        return False
    role, path, start_line, end_line, symbol, relation_kinds, declared_target = value

    def valid_integer(item: object) -> bool:
        return isinstance(item, int) and not isinstance(item, bool)

    valid_relations = {
        "spec_mapping",
        "code_backlink",
        "invariant_declaration",
        "invariant_bind",
        "binding_test",
    }
    return (
        valid_integer(role)
        and role in {0, 1, 2}
        and _valid_cursor_path(path)
        and valid_integer(start_line)
        and valid_integer(end_line)
        and start_line >= 1
        and end_line >= start_line
        and _valid_cursor_string(symbol, empty=True)
        and isinstance(relation_kinds, list)
        and bool(relation_kinds)
        and all(
            isinstance(item, str) and item in valid_relations for item in relation_kinds
        )
        and len(relation_kinds) == len(set(relation_kinds))
        and _valid_preserved_cursor_string(declared_target)
    )


def inventory_list_envelope(
    inventory: ObligationInventory,
    *,
    limit: int | None = None,
    cursor: str | None = None,
    filters: ListFilters | None = None,
) -> dict[str, Any]:
    """Return the successful ``obligation.list`` core object."""

    applied = filters or ListFilters()
    filtered_obligations = tuple(
        item for item in inventory.obligations if applied.accepts(item)
    )
    filtered_inventory = replace(inventory, obligations=filtered_obligations)
    result = filtered_inventory.list_result()
    entries_value = result["entries"]
    assert isinstance(entries_value, list)
    if applied.active:
        entries_value = [
            item
            for item in entries_value
            if cast(dict[str, object], item)["entry_type"] == "obligation"
        ]
    entries = sorted(entries_value, key=_list_ordering)
    filtered_count = len(entries)
    filter_row = applied.to_row()
    selector = "list"
    if limit is not None:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")
        after: tuple[object, ...] | None = None
        if cursor is not None:
            decoded = decode_page_cursor(
                cursor,
                operation="obligation.list",
                snapshot_hash=inventory.snapshot.snapshot_hash,
                obligation_id=None,
                selector=selector,
                limit=limit,
                filters=filter_row,
            )
            after_value = decoded["after"]
            if not _valid_list_after(after_value):
                raise CursorError("cursor list ordering tuple is invalid")
            after = tuple(after_value)
        if after is not None:
            entries = [row for row in entries if _list_ordering(row) > after]
        page = entries[:limit]
        next_cursor = None
        if len(entries) > limit:
            next_cursor = encode_page_cursor(
                operation="obligation.list",
                snapshot_hash=inventory.snapshot.snapshot_hash,
                obligation_id=None,
                selector=selector,
                limit=limit,
                after=_list_ordering(page[-1]),
                filters=filter_row,
            )
        result = {
            "bootstrap_state": result["bootstrap_state"],
            "entries": page,
            "next_cursor": next_cursor,
        }
    result = {
        "bootstrap_state": result["bootstrap_state"],
        "applied_filters": filter_row,
        "readiness_summary": _readiness_summary(filtered_obligations),
        "filtered_count": filtered_count,
        "entries": result["entries"],
        "next_cursor": result["next_cursor"],
    }
    return {
        "schema_version": 2,
        "operation": "obligation.list",
        "snapshot": inventory.snapshot.to_row(),
        "result": result,
        "guidance": guidance_rows(inventory.next_actions),
        "problems": [],
    }


def _readiness_summary(
    obligations: tuple[ObligationRecord, ...],
) -> dict[str, object]:
    buckets = {
        "executable": 0,
        "skipped": 0,
        "alignment_debt": 0,
        "blocked": 0,
        "out_of_scope": 0,
    }
    reason_counts = dict.fromkeys(_REASON_ORDER, 0)
    active_evaluate = 0
    for item in obligations:
        for reason in item.blocking_reasons:
            reason_counts[reason.code] += 1
        if item.obligation_rung != "active":
            buckets["out_of_scope"] += 1
        elif item.disposition == "skipped":
            buckets["skipped"] += 1
        else:
            active_evaluate += 1
            if item.alignment_state == "invalid":
                buckets["blocked"] += 1
            elif item.gate_state == "executable":
                buckets["executable"] += 1
            else:
                buckets["alignment_debt"] += 1
    return {
        "total": len(obligations),
        "active_evaluate": active_evaluate,
        **buckets,
        "reason_counts": [
            {"code": code, "count": reason_counts[code]}
            for code in _REASON_ORDER
            if reason_counts[code]
        ],
    }


def inventory_get_envelope(
    inventory: ObligationInventory, obligation_id: str
) -> dict[str, Any] | None:
    """Return one successful detail envelope, or ``None`` when absent."""

    obligation = inventory.get(obligation_id)
    if obligation is None:
        return None
    return {
        "schema_version": 2,
        "operation": "obligation.get",
        "snapshot": inventory.snapshot.to_row(),
        "result": obligation.to_row(),
        "guidance": guidance_rows(obligation.next_actions),
        "problems": [],
    }


def evidence_summary_envelope(
    inventory: ObligationInventory,
    obligation: ObligationRecord,
    items: tuple[dict[str, object], ...],
    *,
    limit: int,
    cursor: str | None,
) -> dict[str, Any]:
    """Return one paginated source-declared evidence summary."""

    after: tuple[object, ...] | None = None
    if cursor is not None:
        decoded = decode_page_cursor(
            cursor,
            operation="obligation.summarize_evidence",
            snapshot_hash=inventory.snapshot.snapshot_hash,
            obligation_id=obligation.obligation_id,
            selector="summarize_evidence",
            limit=limit,
        )
        after_value = decoded["after"]
        if not _valid_evidence_after(after_value):
            raise CursorError("cursor evidence ordering tuple is invalid")
        after = (*after_value[:5], tuple(after_value[5]), after_value[6])

    available = list(items)
    if after is not None:
        available = [row for row in available if evidence_item_order(row) > after]
    page = available[:limit]
    next_cursor = None
    if len(available) > limit:
        next_cursor = encode_page_cursor(
            operation="obligation.summarize_evidence",
            snapshot_hash=inventory.snapshot.snapshot_hash,
            obligation_id=obligation.obligation_id,
            selector="summarize_evidence",
            limit=limit,
            after=evidence_item_order(page[-1]),
        )
    return {
        "schema_version": 2,
        "operation": "obligation.summarize_evidence",
        "snapshot": inventory.snapshot.to_row(),
        "result": {
            "obligation_id": obligation.obligation_id,
            "alignment_state": obligation.alignment_state,
            "disposition": obligation.disposition,
            "items": page,
            "next_cursor": next_cursor,
        },
        "guidance": guidance_rows(obligation.next_actions),
        "problems": [],
    }


def _candidate_guidance(
    obligation: ObligationRecord,
    candidates: Iterable[EvidenceCandidate],
) -> list[dict[str, str]]:
    rows = tuple(candidates)
    projected = with_candidate_counts(
        obligation,
        CandidateCounts(
            declared=sum(item.trace_state == "declared" for item in rows),
            partially_declared=sum(
                item.trace_state == "partially_declared" for item in rows
            ),
            untraced=sum(item.trace_state == "untraced" for item in rows),
            conflicted=sum(item.trace_state == "conflicted" for item in rows),
        ),
    )
    return guidance_rows(projected.next_actions)


def _valid_candidate_after(value: object) -> bool:
    if not isinstance(value, list) or len(value) != 8:
        return False
    state, kind, shared_count, shared_bytes, path, start_line, locator, identity = value
    integers = (state, kind, shared_count, shared_bytes, start_line)
    if any(isinstance(item, bool) or not isinstance(item, int) for item in integers):
        return False
    if not 0 <= state < 4 or not 0 <= kind < 5:
        return False
    if shared_count > 0 or shared_bytes > 0 or start_line < 1:
        return False
    if not all(
        isinstance(item, str)
        and item
        and unicodedata.normalize("NFC", item) == item
        and "\r" not in item
        and "\n" not in item
        for item in (path, locator, identity)
    ):
        return False
    assert isinstance(path, str)
    if path.startswith("/") or any(part in {"", ".", ".."} for part in path.split("/")):
        return False
    assert isinstance(identity, str)
    return candidate_ref_digest(identity) is not None


def find_evidence_envelope(
    inventory: ObligationInventory,
    obligation: ObligationRecord,
    candidates: tuple[EvidenceCandidate, ...],
    *,
    limit: int,
    cursor: str | None,
) -> dict[str, Any]:
    """Return one content-bound page from the complete candidate universe."""

    ordered = tuple(sorted(candidates, key=candidate_order))
    after: tuple[object, ...] | None = None
    if cursor is not None:
        decoded = decode_page_cursor(
            cursor,
            operation="obligation.find_evidence",
            snapshot_hash=inventory.snapshot.snapshot_hash,
            obligation_id=obligation.obligation_id,
            selector="find_evidence",
            limit=limit,
        )
        after_value = decoded["after"]
        if not _valid_candidate_after(after_value):
            raise CursorError("cursor candidate ordering tuple is invalid")
        after = tuple(after_value)

    available = list(ordered)
    if after is not None:
        available = [item for item in available if candidate_order(item) > after]
    page = available[:limit]
    next_cursor = None
    if len(available) > limit:
        next_cursor = encode_page_cursor(
            operation="obligation.find_evidence",
            snapshot_hash=inventory.snapshot.snapshot_hash,
            obligation_id=obligation.obligation_id,
            selector="find_evidence",
            limit=limit,
            after=candidate_order(page[-1]),
        )
    return {
        "schema_version": 2,
        "operation": "obligation.find_evidence",
        "snapshot": inventory.snapshot.to_row(),
        "result": {
            "obligation_id": obligation.obligation_id,
            "candidates": [item.to_row() for item in page],
            "next_cursor": next_cursor,
        },
        "guidance": _candidate_guidance(obligation, ordered),
        "problems": [],
    }


def candidate_detail_envelope(
    inventory: ObligationInventory,
    obligation: ObligationRecord,
    candidate: EvidenceCandidate,
    source: CandidateSource,
    neighbors: tuple[CandidateNeighbor, ...],
) -> dict[str, Any]:
    """Return one exact candidate, its receipt span, and bounded neighbors."""

    ordered_neighbors = sorted(
        neighbors,
        key=lambda item: (item.relation_kind, item.direction, item.candidate_id),
    )
    return {
        "schema_version": 2,
        "operation": "obligation.get_candidate",
        "snapshot": inventory.snapshot.to_row(),
        "result": {
            "obligation_id": obligation.obligation_id,
            "candidate": candidate.to_row(),
            "source": source.to_row(),
            "neighbors": [item.to_row() for item in ordered_neighbors],
        },
        "guidance": _candidate_guidance(obligation, (candidate,)),
        "problems": [],
    }


class _ObligationReader:
    """Execute one normalized read against one accepted repository view."""

    def __init__(
        self,
        request: ObligationRequest,
        progress_sink: ProgressSink | None,
    ) -> None:
        self.request = request
        self.progress_sink = progress_sink
        self.progress: OperationProgress | None = None
        self.snapshot: RepositorySnapshot | None = None
        self.root = request.repo_root.resolve(strict=False)

    def read(self) -> ObligationResult:
        try:
            self._validate_request()
            markdown_parse_memo: MarkdownParseMemo = {}
            self.progress = OperationProgress.start(
                self.request.settings.obligations.maximum_call_seconds,
                clock=_monotonic,
                sink=self.progress_sink,
            )
            self.snapshot = capture_obligation_snapshot(
                self.root,
                self.request.profile,
                self.request.settings,
                markdown_parse_memo=markdown_parse_memo,
                progress=self.progress,
            )
            runtime = build_obligation_runtime_from_snapshot(
                self.snapshot,
                self.root,
                self.request.profile,
                self.request.settings,
                markdown_parse_memo=markdown_parse_memo,
            )
            envelope, failed = self._read_runtime(runtime)
            self.progress.advance(
                "packet_accounting",
                current_identity=self.request.operation,
            )
            if not failed:
                envelope, exhausted = apply_response_byte_budget(
                    envelope, self.request.settings.obligations
                )
                failed = exhausted
            self.progress.advance(
                "complete",
                current_identity=self.request.operation,
            )
            return self._result(envelope, failed=failed)
        except OperationDeadlineExceeded as exc:
            return self._deadline_failure(exc)
        except SnapshotCaptureError as exc:
            return self._snapshot_failure(exc)
        except ValueError as exc:
            if self.snapshot is not None:
                return self._internal_failure()
            return self._problem(
                code="INVALID_INPUT",
                message="The obligation request is invalid.",
                action="Correct the named invocation or configuration value and retry.",
                details={"field": "invocation", "reason": str(exc)},
            )
        except Exception:  # noqa: BLE001 -- closed [EVC-8.4] application failure.
            return self._internal_failure()

    def _validate_request(self) -> None:
        request = self.request
        limits = request.settings.obligations
        if (
            request.limit is not None
            and not 1 <= request.limit <= limits.maximum_page_size
        ):
            raise ValueError(f"--limit must be in [1, {limits.maximum_page_size}]")
        if request.operation == "obligation.list":
            if request.obligation_id is not None or request.candidate_id is not None:
                raise ValueError("obligation list does not accept a detail selector")
            return
        if request.list_filters.active:
            raise ValueError("obligation list filters require `obligation list`")
        if request.obligation_id is None:
            raise ValueError("the selected obligation operation requires an identity")
        if request.operation == "obligation.get_candidate":
            if request.candidate_id is None:
                raise ValueError(
                    "candidate detail requires an exact candidate identity"
                )
        elif request.candidate_id is not None:
            raise ValueError("--candidate requires the candidate-detail operation")
        if request.operation not in {
            "obligation.summarize_evidence",
            "obligation.find_evidence",
        } and (request.cursor is not None or request.limit is not None):
            raise ValueError(
                "--cursor and --limit require --summarize-evidence or --find-evidence"
            )

    def _read_runtime(self, runtime: ObligationRuntime) -> tuple[dict[str, Any], bool]:
        if self.request.operation == "obligation.list":
            return self._list(runtime)
        return self._detail(runtime)

    def _list(self, runtime: ObligationRuntime) -> tuple[dict[str, Any], bool]:
        limit = self.request.limit or self.request.settings.obligations.page_size
        try:
            return (
                inventory_list_envelope(
                    runtime.inventory,
                    limit=limit,
                    cursor=self.request.cursor,
                    filters=self.request.list_filters,
                ),
                False,
            )
        except CursorError as exc:
            return (
                problem_envelope(
                    operation="obligation.list",
                    snapshot=runtime.inventory.snapshot.to_row(),
                    code="CURSOR_INVALID",
                    message="The page cursor is invalid for this repository snapshot.",
                    action="Restart pagination without a cursor.",
                    details={"reason": str(exc)},
                ),
                True,
            )

    def _detail(self, runtime: ObligationRuntime) -> tuple[dict[str, Any], bool]:
        obligation_id = self.request.obligation_id
        assert obligation_id is not None
        obligation = runtime.inventory.get(obligation_id)
        if obligation is None:
            return self._missing(runtime, obligation_id)
        if obligation.kind == "suppression":
            return self._suppression(runtime, obligation)
        if self.request.operation == "obligation.summarize_evidence":
            return self._summary(runtime, obligation)
        unreadable = next(
            (row for row in runtime.snapshot.files if row.state == "unreadable"),
            None,
        )
        if unreadable is not None:
            return (
                problem_envelope(
                    operation=self.request.operation,
                    snapshot=runtime.inventory.snapshot.to_row(),
                    code="SOURCE_UNREADABLE",
                    message="Candidate discovery requires every semantic source input.",
                    action="Make the named source readable and retry discovery.",
                    details={
                        "path": unreadable.path,
                        "error_class": unreadable.error_class or "io",
                    },
                ),
                True,
            )
        try:
            candidates = runtime.discover_candidates(
                obligation,
                progress=self.progress,
            )
        except EvidenceDiscoveryError as exc:
            source_unreadable = exc.code == "SOURCE_UNREADABLE"
            return (
                problem_envelope(
                    operation=self.request.operation,
                    snapshot=runtime.inventory.snapshot.to_row(),
                    code=cast(OperationProblemCode, exc.code),
                    message=(
                        "Candidate discovery requires UTF-8 semantic source."
                        if source_unreadable
                        else "Candidate discovery exceeded its closed operation boundary."
                    ),
                    action=(
                        "Correct the named semantic source encoding and retry."
                        if source_unreadable
                        else (
                            "Raise the named deterministic budget or narrow "
                            "configured roots."
                        )
                    ),
                    details=exc.details,
                ),
                True,
            )
        obligation, inventory = self._with_candidate_counts(
            runtime, obligation, candidates
        )
        if self.request.operation == "obligation.find_evidence":
            limit = self.request.limit or self.request.settings.obligations.page_size
            try:
                return (
                    find_evidence_envelope(
                        inventory,
                        obligation,
                        candidates,
                        limit=limit,
                        cursor=self.request.cursor,
                    ),
                    False,
                )
            except CursorError as exc:
                return (
                    problem_envelope(
                        operation="obligation.find_evidence",
                        snapshot=inventory.snapshot.to_row(),
                        code="CURSOR_INVALID",
                        message=(
                            "The page cursor is invalid for this repository snapshot."
                        ),
                        action="Restart pagination without a cursor.",
                        details={"reason": str(exc)},
                    ),
                    True,
                )
        if self.request.operation == "obligation.get_candidate":
            return self._candidate(runtime, inventory, obligation, candidates)
        envelope = inventory_get_envelope(inventory, obligation.obligation_id)
        assert envelope is not None
        return envelope, False

    def _suppression(
        self,
        runtime: ObligationRuntime,
        obligation: ObligationRecord,
    ) -> tuple[dict[str, Any], bool]:
        if self.request.operation != "obligation.get":
            return (
                problem_envelope(
                    operation=self.request.operation,
                    snapshot=runtime.inventory.snapshot.to_row(),
                    code="INVALID_INPUT",
                    message="This operation is not available for suppression obligations.",
                    action=(
                        "Inspect the suppression obligation directly; its evidence is "
                        "derived from the declaration and matched findings."
                    ),
                    details={
                        "field": "operation",
                        "reason": (
                            "suppression obligations do not support evidence discovery "
                            "or candidate selectors"
                        ),
                    },
                ),
                True,
            )
        envelope = inventory_get_envelope(
            runtime.inventory,
            obligation.obligation_id,
        )
        assert envelope is not None
        return envelope, False

    def _summary(
        self,
        runtime: ObligationRuntime,
        obligation: ObligationRecord,
    ) -> tuple[dict[str, Any], bool]:
        limit = self.request.limit or self.request.settings.obligations.page_size
        items = runtime.evidence_summary(obligation)
        try:
            return (
                evidence_summary_envelope(
                    runtime.inventory,
                    obligation,
                    items,
                    limit=limit,
                    cursor=self.request.cursor,
                ),
                False,
            )
        except CursorError as exc:
            return (
                problem_envelope(
                    operation="obligation.summarize_evidence",
                    snapshot=runtime.inventory.snapshot.to_row(),
                    code="CURSOR_INVALID",
                    message="The page cursor is invalid for this repository snapshot.",
                    action="Restart pagination without a cursor.",
                    details={"reason": str(exc)},
                ),
                True,
            )

    @staticmethod
    def _with_candidate_counts(
        runtime: ObligationRuntime,
        obligation: ObligationRecord,
        candidates: tuple[EvidenceCandidate, ...],
    ) -> tuple[ObligationRecord, ObligationInventory]:
        counts = CandidateCounts(
            declared=sum(item.trace_state == "declared" for item in candidates),
            partially_declared=sum(
                item.trace_state == "partially_declared" for item in candidates
            ),
            untraced=sum(item.trace_state == "untraced" for item in candidates),
            conflicted=sum(item.trace_state == "conflicted" for item in candidates),
        )
        obligation = with_candidate_counts(obligation, counts)
        inventory = replace(
            runtime.inventory,
            obligations=tuple(
                obligation if item.obligation_id == obligation.obligation_id else item
                for item in runtime.inventory.obligations
            ),
        )
        return obligation, inventory

    def _candidate(
        self,
        runtime: ObligationRuntime,
        inventory: ObligationInventory,
        obligation: ObligationRecord,
        candidates: tuple[EvidenceCandidate, ...],
    ) -> tuple[dict[str, Any], bool]:
        candidate_id = self.request.candidate_id
        assert candidate_id is not None
        try:
            candidate = get_candidate_by_id(candidates, candidate_id)
        except KeyError:
            return (
                problem_envelope(
                    operation="obligation.get_candidate",
                    snapshot=inventory.snapshot.to_row(),
                    code="NOT_FOUND",
                    message="The requested candidate does not exist in this snapshot.",
                    action="Run --find-evidence and use an exact returned candidate ID.",
                    details={"identity": candidate_id},
                ),
                True,
            )
        return (
            candidate_detail_envelope(
                inventory,
                obligation,
                candidate,
                get_candidate_source(candidate),
                get_candidate_neighbors(candidate, candidates),
            ),
            False,
        )

    def _missing(
        self,
        runtime: ObligationRuntime,
        obligation_id: str,
    ) -> tuple[dict[str, Any], bool]:
        if len(obligation_id.encode("utf-8")) > 4096:
            return (
                problem_envelope(
                    operation=self.request.operation,
                    snapshot=runtime.inventory.snapshot.to_row(),
                    code="INVALID_INPUT",
                    message=(
                        "The requested identity cannot be represented in a problem "
                        "response."
                    ),
                    action="Use an exact identity returned by backstitch obligation list.",
                    details={
                        "field": "identity",
                        "reason": (
                            "requested identity exceeds the closed problem detail limit"
                        ),
                    },
                ),
                True,
            )
        return (
            problem_envelope(
                operation=self.request.operation,
                snapshot=runtime.inventory.snapshot.to_row(),
                code="NOT_FOUND",
                message="The requested obligation does not exist in this snapshot.",
                action=(
                    "Run backstitch obligation list and use an exact returned identity."
                ),
                details={"identity": obligation_id},
            ),
            True,
        )

    def _snapshot_failure(self, exc: SnapshotCaptureError) -> ObligationResult:
        if exc.kind == "unsupported_platform":
            return self._problem(
                code="UNSUPPORTED_PLATFORM",
                message="This platform cannot capture a repository snapshot safely.",
                action="Run Backstitch on a supported POSIX platform.",
                details={"platform": sys.platform},
            )
        if exc.kind == "snapshot_unstable":
            return self._problem(
                code="SNAPSHOT_UNSTABLE",
                message="The repository changed during bounded snapshot capture.",
                action="Retry after concurrent repository writes have stopped.",
                details={"attempts": exc.attempts or 0},
            )
        if exc.kind == "budget_exceeded":
            return self._problem(
                code="BUDGET_EXHAUSTED",
                message="Repository snapshot capture exceeded a configured budget.",
                action="Raise the named deterministic budget or narrow configured roots.",
                details={
                    "budget": exc.budget or "snapshot_files",
                    "limit": exc.limit or 0,
                    "observed": exc.observed or 0,
                },
            )
        field = "repo_root" if exc.kind == "invalid_root" else "path"
        reason = {
            "invalid_root": "repository root is not an existing readable directory",
            "invalid_path": "repository path configuration is invalid",
            "symlink": "repository input cannot be a symlink",
            "not_regular": "repository input must be a regular file or directory",
        }.get(exc.kind, "repository input is invalid")
        return self._problem(
            code="INVALID_INPUT",
            message="Repository input is not valid for safe snapshot capture.",
            action="Correct the repository root, path, or source object and retry.",
            details={"field": field, "reason": reason},
        )

    def _internal_failure(self) -> ObligationResult:
        return self._problem(
            code="INTERNAL_ERROR",
            message="Backstitch could not complete the obligation request.",
            action="Retry and report the failure if it persists.",
            details={},
        )

    def _deadline_failure(
        self,
        exc: OperationDeadlineExceeded,
    ) -> ObligationResult:
        return self._problem(
            code="DEADLINE_EXCEEDED",
            message="The obligation operation exceeded its configured deadline.",
            action=(
                "Retry with `backstitch obligation list --repo-root . "
                "--option obligations.maximum_call_seconds 30`."
            ),
            details={
                "limit_milliseconds": exc.limit_milliseconds,
                "phase": exc.phase,
                "configured_key": "obligations.maximum_call_seconds",
                "cooperative_tolerance_milliseconds": (
                    exc.cooperative_tolerance_milliseconds
                ),
            },
        )

    def _problem(
        self,
        *,
        code: OperationProblemCode,
        message: str,
        action: str,
        details: dict[str, object],
    ) -> ObligationResult:
        snapshot = None
        if self.snapshot is not None:
            snapshot = {
                "snapshot_hash": self.snapshot.snapshot_hash,
                "file_count": self.snapshot.file_count,
                "byte_count": self.snapshot.byte_count,
                "unreadable_count": self.snapshot.unreadable_count,
            }
        return self._result(
            problem_envelope(
                operation=self.request.operation,
                snapshot=snapshot,
                code=code,
                message=message,
                action=action,
                details=details,
            ),
            failed=True,
        )

    def _result(self, envelope: dict[str, Any], *, failed: bool) -> ObligationResult:
        return ObligationResult(
            envelope=envelope,
            failed=failed,
            resolved_root=self.root.as_posix(),
        )


def read_obligation(
    request: ObligationRequest,
    *,
    progress_sink: ProgressSink | None = None,
) -> ObligationResult:
    """Run one obligation operation without presentation or process-exit policy."""

    return _ObligationReader(request, progress_sink).read()


def render_envelope_json(envelope: dict[str, Any]) -> str:
    """Render canonical JSON with one final newline."""

    return canonical_json_bytes(envelope).decode("utf-8") + "\n"


def render_envelope_text(envelope: dict[str, Any], *, resolved_root: str) -> str:  # noqa: C901 approved [SC-17.1] RUFF-SUP-052 exception
    """Render one compact human view while keeping root outside core JSON."""

    lines = [f"root {resolved_root}"]
    snapshot = envelope["snapshot"]
    if isinstance(snapshot, dict):
        lines.append(f"snapshot {snapshot['snapshot_hash']}")
    problems = envelope["problems"]
    if isinstance(problems, list) and problems:
        for problem in problems:
            assert isinstance(problem, dict)
            lines.extend(
                (
                    f"problem {problem['code']}: {problem['message']}",
                    "details: "
                    + canonical_json_bytes(problem["details"]).decode("utf-8"),
                    f"action: {problem['action']}",
                )
            )
        return "\n".join(lines) + "\n"

    result = envelope["result"]
    assert isinstance(result, dict)
    operation = envelope["operation"]
    if operation == "obligation.list":
        lines.append(f"bootstrap: {result['bootstrap_state']}")
        lines.append(
            "filters: "
            + canonical_json_bytes(result["applied_filters"]).decode("utf-8")
        )
        lines.append(
            "readiness: "
            + canonical_json_bytes(result["readiness_summary"]).decode("utf-8")
        )
        lines.append(f"filtered_count: {result['filtered_count']}")
        entries = result["entries"]
        assert isinstance(entries, list)
        for entry in entries:
            assert isinstance(entry, dict)
            if entry["entry_type"] == "obligation":
                lines.append(
                    f"obligation {entry['obligation_id']} {entry['kind']} "
                    f"{entry['alignment_state']} {entry['disposition']} "
                    f"{entry['obligation_rung']} {entry['gate_state']} "
                    f"{entry['path']}:{entry['start_line']}"
                )
            else:
                diagnostic = entry["diagnostic"]
                assert isinstance(diagnostic, dict)
                lines.append(
                    f"unaddressable {entry['entry_identity']} "
                    f"{diagnostic['code']} {diagnostic['path']}:"
                    f"{diagnostic['line'] or 0}"
                )
                lines.append(f"  action: {entry['action']}")
    elif operation == "obligation.get":
        lines.extend(
            (
                f"obligation: {result['obligation_id']}",
                f"source: {result['path']}:{result['start_line']}-{result['end_line']}",
                f"kind: {result['kind']}",
                f"intent: {result['intent_state']}",
                f"alignment: {result['alignment_state']}",
                f"disposition: {result['disposition']}",
                f"rung: {result['obligation_rung']}",
                f"gate: {result['gate_state']}",
                "required_roles: " + ",".join(result["required_roles"]),
                "evidence_counts: "
                + canonical_json_bytes(result["evidence_counts"]).decode("utf-8"),
                "candidate_counts: "
                + canonical_json_bytes(result["candidate_counts"]).decode("utf-8"),
            )
        )
        blockers = result["blocking_reasons"]
        assert isinstance(blockers, list)
        for blocker in blockers:
            assert isinstance(blocker, dict)
            lines.append("blocker: " + canonical_json_bytes(blocker).decode("utf-8"))
        if result["kind"] == "suppression":
            lines.extend(
                (
                    "declaration: "
                    + canonical_json_bytes(result["declaration"]).decode("utf-8"),
                    "suppression_rules: "
                    + canonical_json_bytes(result["suppression_rules"]).decode("utf-8"),
                    f"matched_issue_count: {result['matched_issue_count']}",
                )
            )
        lines.append("next_actions: " + ",".join(result["next_actions"]))
    elif operation == "obligation.summarize_evidence":
        lines.extend(
            (
                f"obligation: {result['obligation_id']}",
                f"alignment: {result['alignment_state']}",
                f"disposition: {result['disposition']}",
            )
        )
        items = result["items"]
        assert isinstance(items, list)
        for item in items:
            assert isinstance(item, dict)
            symbol = f"::{item['symbol']}" if item["symbol"] else ""
            declared_target = (
                " declared_target="
                + json.dumps(str(item["declared_target"]), ensure_ascii=True)
                if item.get("declared_target")
                else ""
            )
            lines.append(
                f"{item['role']} {item['path']}:{item['start_line']}-"
                f"{item['end_line']}{symbol} {item['reciprocity_state']} "
                f"relations={','.join(item['relation_kinds'])} "
                f"sha256={item['receipt']['raw_sha256']}{declared_target}"
            )
            for declaration in item.get("declarations", []):
                assert isinstance(declaration, dict)
                declaration_target = (
                    " declared_target="
                    + json.dumps(str(declaration["declared_target"]), ensure_ascii=True)
                    if declaration.get("declared_target")
                    else ""
                )
                receipt = declaration["receipt"]
                assert isinstance(receipt, dict)
                lines.append(
                    f"  declaration {declaration['relation_kind']} "
                    f"{declaration['path']}:{declaration['line']} "
                    f"sha256={receipt['raw_sha256']}{declaration_target}"
                )
    elif operation == "obligation.find_evidence":
        lines.append(f"obligation: {result['obligation_id']}")
        candidates = result["candidates"]
        assert isinstance(candidates, list)
        for candidate in candidates:
            assert isinstance(candidate, dict)
            owner = f"::{candidate['owner']}" if candidate["owner"] else ""
            lines.append(
                f"{candidate['trace_state']} {candidate['candidate_kind']} "
                f"{candidate['path']}:{candidate['start_line']}-"
                f"{candidate['end_line']}{owner} {candidate['candidate_id']} "
                f"bases={','.join(candidate['discovery_bases'])}"
            )
            for advice in candidate["suggested_trace_edits"]:
                lines.append(
                    f"  advice {advice['guidance_code']}: target="
                    f"{advice['target_id']} forms="
                    f"{','.join(advice['supported_forms'])}"
                )
    else:
        assert operation == "obligation.get_candidate"
        lines.append(f"obligation: {result['obligation_id']}")
        candidate = result["candidate"]
        source = result["source"]
        assert isinstance(candidate, dict)
        assert isinstance(source, dict)
        lines.extend(
            (
                f"candidate: {candidate['candidate_id']}",
                f"trace: {candidate['trace_state']}",
                f"source: {candidate['path']}:{candidate['start_line']}",
                f"receipt_sha256: {candidate['receipt']['raw_sha256']}",
                str(source["text"]),
            )
        )
        neighbors = result["neighbors"]
        assert isinstance(neighbors, list)
        for neighbor in neighbors:
            assert isinstance(neighbor, dict)
            lines.append(
                f"neighbor {neighbor['direction']} {neighbor['relation_kind']} "
                f"{neighbor['candidate_id']}"
            )
        for advice in candidate["suggested_trace_edits"]:
            lines.append(
                f"advice {advice['guidance_code']}: target={advice['target_id']} "
                f"forms={','.join(advice['supported_forms'])}"
            )
    next_cursor = result.get("next_cursor")
    if next_cursor is not None:
        lines.append(f"next_cursor: {next_cursor}")
    guidance = envelope["guidance"]
    assert isinstance(guidance, list)
    for row in guidance:
        assert isinstance(row, dict)
        lines.extend(
            (
                f"guidance {row['code']}: {row['message']}",
                f"action: {row['action']}",
            )
        )
    return "\n".join(lines) + "\n"
