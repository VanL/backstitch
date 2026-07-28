"""Transport-neutral Backstitch obligation read envelopes.

Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-8.4]
"""

from __future__ import annotations

import base64
import hashlib
import json
import unicodedata
from collections.abc import Iterable
from typing import Any, Literal, cast

from backstitch.canonical import canonical_json_bytes
from backstitch.evidence_discovery import (
    CandidateNeighbor,
    CandidateSource,
    EvidenceCandidate,
    candidate_order,
)
from backstitch.evidence_summary import evidence_item_order
from backstitch.grammar import candidate_ref_digest, is_sha256_hex
from backstitch.obligations import (
    CandidateCounts,
    GuidanceCode,
    ObligationInventory,
    ObligationRecord,
    with_candidate_counts,
)
from backstitch.settings import ObligationSettings

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
    "DEADLINE_EXCEEDED": frozenset({"limit_milliseconds"}),
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


def encode_page_cursor(
    *,
    operation: str,
    snapshot_hash: str,
    obligation_id: str | None,
    selector: str,
    limit: int,
    after: tuple[object, ...],
) -> str:
    """Encode the exact query context and last-row ordering tuple."""

    value = {
        "cursor_version": 1,
        "operation": operation,
        "snapshot_hash": snapshot_hash,
        "obligation_id": obligation_id,
        "selector": selector,
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
        or value.get("cursor_version") != 1
        or not isinstance(value.get("operation"), str)
        or not isinstance(value.get("snapshot_hash"), str)
        or (
            value.get("obligation_id") is not None
            and not isinstance(value.get("obligation_id"), str)
        )
        or not isinstance(value.get("selector"), str)
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


def problem_envelope(
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
        if field in {"attempts", "limit", "observed", "limit_milliseconds"}:
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

    return {
        "schema_version": 1,
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
) -> dict[str, Any]:
    """Return the successful ``obligation.list`` core object."""

    result = inventory.list_result()
    entries_value = result["entries"]
    assert isinstance(entries_value, list)
    entries = sorted(entries_value, key=_list_ordering)
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
                selector="list",
                limit=limit,
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
                selector="list",
                limit=limit,
                after=_list_ordering(page[-1]),
            )
        result = {
            "bootstrap_state": result["bootstrap_state"],
            "entries": page,
            "next_cursor": next_cursor,
        }
    return {
        "schema_version": 1,
        "operation": "obligation.list",
        "snapshot": inventory.snapshot.to_row(),
        "result": result,
        "guidance": guidance_rows(inventory.next_actions),
        "problems": [],
    }


def inventory_get_envelope(
    inventory: ObligationInventory, obligation_id: str
) -> dict[str, Any] | None:
    """Return one successful detail envelope, or ``None`` when absent."""

    obligation = inventory.get(obligation_id)
    if obligation is None:
        return None
    return {
        "schema_version": 1,
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
        "schema_version": 1,
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
        "schema_version": 1,
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
        "schema_version": 1,
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


def render_envelope_json(envelope: dict[str, Any]) -> str:
    """Render canonical JSON with one final newline."""

    return canonical_json_bytes(envelope).decode("utf-8") + "\n"


def render_envelope_text(envelope: dict[str, Any], *, resolved_root: str) -> str:
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
