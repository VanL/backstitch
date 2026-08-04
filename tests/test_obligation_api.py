"""Transport-neutral obligation response envelope tests.

Spec: docs/specs/02-backstitch-core.md [SC-10]
Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-8.4]
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import replace
from typing import Any, cast

import pytest

from backstitch.canonical import canonical_json_bytes
from backstitch.evidence_discovery import (
    CandidateNeighbor,
    CandidateSource,
    EvidenceCandidate,
    SourceReceipt,
)
from backstitch.models import (
    SuppressionDeclaration,
    SuppressionOrigin,
    SuppressionRule,
)
from backstitch.obligation_api import (
    CursorError,
    ListFilters,
    OperationProblemCode,
    apply_response_byte_budget,
    candidate_detail_envelope,
    decode_page_cursor,
    encode_page_cursor,
    evidence_summary_envelope,
    find_evidence_envelope,
    inventory_get_envelope,
    inventory_list_envelope,
    problem_envelope,
    render_envelope_json,
    render_envelope_text,
)
from backstitch.obligations import (
    BlockingReason,
    CandidateCounts,
    EvidenceCounts,
    ObligationInventory,
    ObligationRecord,
    SnapshotIdentity,
    SuppressionObligationDetail,
    UnaddressableIntent,
)
from backstitch.operation_progress import DEADLINE_PHASES
from backstitch.settings import BackstitchSettings


def test_response_budget_uses_exact_canonical_core_json_for_every_adapter() -> None:
    envelope = {
        "schema_version": 2,
        "operation": "obligation.list",
        "snapshot": None,
        "result": {"entries": []},
        "guidance": [],
        "problems": [],
    }
    golden = (
        b'{"guidance":[],"operation":"obligation.list","problems":[],'
        b'"result":{"entries":[]},"schema_version":2,"snapshot":null}'
    )
    assert canonical_json_bytes(envelope) == golden
    limits = replace(
        BackstitchSettings().obligations,
        maximum_response_bytes=len(golden) - 1,
    )

    budgeted_json, json_exhausted = apply_response_byte_budget(envelope, limits)
    budgeted_text, text_exhausted = apply_response_byte_budget(envelope, limits)

    assert json_exhausted is text_exhausted is True
    assert canonical_json_bytes(budgeted_json) == canonical_json_bytes(budgeted_text)
    details = budgeted_json["problems"][0]["details"]
    assert details == {
        "budget": "response_bytes",
        "limit": len(golden) - 1,
        "observed": len(golden),
    }
    assert render_envelope_json(budgeted_json).endswith("\n")
    assert render_envelope_text(budgeted_text, resolved_root="/repo").startswith(
        "root /repo\n"
    )


def test_empty_inventory_has_one_closed_bootstrap_guidance_row() -> None:
    snapshot = SnapshotIdentity("a" * 64, 1, 20, 0)
    inventory = ObligationInventory(
        snapshot=snapshot,
        obligations=(),
        unaddressable_intent=(),
        next_actions=("ADD_OR_CONFIGURE_SPEC_INTENT",),
    )

    envelope = inventory_list_envelope(inventory)

    assert envelope == {
        "schema_version": 2,
        "operation": "obligation.list",
        "snapshot": {
            "snapshot_hash": "a" * 64,
            "file_count": 1,
            "byte_count": 20,
            "unreadable_count": 0,
        },
        "result": {
            "bootstrap_state": "no_intent",
            "applied_filters": {
                "active_only": False,
                "alignment_states": [],
                "gate_states": [],
                "kinds": [],
                "reasons": [],
            },
            "readiness_summary": {
                "total": 0,
                "active_evaluate": 0,
                "executable": 0,
                "skipped": 0,
                "alignment_debt": 0,
                "blocked": 0,
                "out_of_scope": 0,
                "reason_counts": [],
            },
            "filtered_count": 0,
            "entries": [],
            "next_cursor": None,
        },
        "guidance": [
            {
                "code": "ADD_OR_CONFIGURE_SPEC_INTENT",
                "message": "No addressable specification intent was found.",
                "action": "Add an ID-bearing spec section or configure the intended spec roots.",
            }
        ],
        "problems": [],
    }
    rendered = render_envelope_json(envelope)
    assert rendered.endswith("\n")
    assert json.loads(rendered) == envelope
    assert rendered == render_envelope_json(envelope)


def test_list_filters_precede_pagination_and_bind_cursor_identity() -> None:
    snapshot = SnapshotIdentity("a" * 64, 4, 80, 0)

    def obligation(
        identity: str,
        *,
        kind: str,
        alignment: str,
        disposition: str = "evaluate",
        rung: str = "active",
        gate: str = "not_executable",
        reasons: tuple[BlockingReason, ...] = (),
    ) -> ObligationRecord:
        return ObligationRecord(
            obligation_id=f"docs/specs/a.md#{identity}",
            kind=cast(Any, kind),
            path="docs/specs/a.md",
            start_line=int(identity.rsplit("-", 1)[1]),
            end_line=int(identity.rsplit("-", 1)[1]),
            title=identity,
            intent_state="identified",
            alignment_state=cast(Any, alignment),
            disposition=cast(Any, disposition),
            obligation_rung=cast(Any, rung),
            gate_state=cast(Any, gate),
            required_roles=("implementation",),
            evidence_counts=EvidenceCounts(),
            candidate_counts=CandidateCounts(),
            blocking_reasons=reasons,
            next_actions=("RUN_DETERMINISTIC_CHECK",),
        )

    partial = BlockingReason(
        "IMPLEMENTATION_PARTIAL",
        "implementation",
        "spec_mapping",
        None,
    )
    skipped = BlockingReason("SKIPPED", None, None, None)
    inventory = ObligationInventory(
        snapshot,
        (
            obligation("A-1", kind="section", alignment="complete", gate="executable"),
            obligation(
                "A-2",
                kind="invariant",
                alignment="partial",
                reasons=(partial,),
            ),
            obligation(
                "A-3",
                kind="suppression",
                alignment="complete",
                disposition="skipped",
                reasons=(skipped,),
            ),
            obligation(
                "A-4",
                kind="section",
                alignment="complete",
                rung="planned",
            ),
        ),
        (),
        ("RUN_DETERMINISTIC_CHECK",),
    )
    filters = ListFilters(
        active_only=True,
        gate_states=frozenset({"not_executable"}),
        reasons=frozenset({"IMPLEMENTATION_PARTIAL", "TRACE_CONFLICT"}),
    )

    envelope = inventory_list_envelope(
        inventory,
        limit=1,
        filters=filters,
    )

    assert envelope["result"]["applied_filters"] == {
        "active_only": True,
        "alignment_states": [],
        "gate_states": ["not_executable"],
        "kinds": [],
        "reasons": ["IMPLEMENTATION_PARTIAL", "TRACE_CONFLICT"],
    }
    assert envelope["result"]["filtered_count"] == 1
    assert [item["obligation_id"] for item in envelope["result"]["entries"]] == [
        "docs/specs/a.md#A-2"
    ]
    assert envelope["result"]["readiness_summary"] == {
        "total": 1,
        "active_evaluate": 1,
        "executable": 0,
        "skipped": 0,
        "alignment_debt": 1,
        "blocked": 0,
        "out_of_scope": 0,
        "reason_counts": [{"code": "IMPLEMENTATION_PARTIAL", "count": 1}],
    }

    two_sections = inventory_list_envelope(
        inventory,
        limit=1,
        filters=ListFilters(kinds=frozenset({"section"})),
    )
    cursor = two_sections["result"]["next_cursor"]
    assert isinstance(cursor, str)
    with pytest.raises(CursorError, match="filters"):
        inventory_list_envelope(
            inventory,
            limit=1,
            cursor=cursor,
            filters=ListFilters(kinds=frozenset({"invariant"})),
        )


def test_suppression_get_projects_declaration_rules_and_matched_count() -> None:
    snapshot = SnapshotIdentity("a" * 64, 1, 20, 0)
    declaration = SuppressionDeclaration(
        declaration_id="SUP-1",
        reference="docs/specs/a.md#SUP-1",
        rationale="The fixture intentionally retains this warning.",
        path="docs/specs/a.md",
        owner_section_id="A-1",
        owner_title="Suppression policy",
        start_line=5,
        end_line=5,
    )
    rule = SuppressionRule(
        mechanism="ignore",
        provenance="config_file",
        path="pkg/a.py",
        sections=(),
        codes=("CODE_REF_PATH_UNRESOLVED",),
        declaration=declaration.reference,
        origin=SuppressionOrigin(source=".backstitch.toml", position=0),
    )
    obligation = ObligationRecord(
        obligation_id="suppression::docs/specs/a.md#SUP-1",
        kind="suppression",
        path=declaration.path,
        start_line=5,
        end_line=5,
        title=declaration.owner_title,
        intent_state="identified",
        alignment_state="complete",
        disposition="evaluate",
        obligation_rung="active",
        gate_state="executable",
        required_roles=(),
        evidence_counts=EvidenceCounts(),
        candidate_counts=CandidateCounts(),
        blocking_reasons=(),
        next_actions=("RUN_DETERMINISTIC_CHECK", "RUN_CURRENT_ANALYSIS"),
        suppression=SuppressionObligationDetail(declaration, (rule,), 2),
    )
    inventory = ObligationInventory(
        snapshot=snapshot,
        obligations=(obligation,),
        unaddressable_intent=(),
        next_actions=obligation.next_actions,
    )

    envelope = inventory_get_envelope(inventory, obligation.obligation_id)

    assert envelope is not None
    assert envelope["result"]["declaration"]["rationale"] == declaration.rationale
    assert envelope["result"]["suppression_rules"][0]["declaration"] == (
        declaration.reference
    )
    assert envelope["result"]["matched_issue_count"] == 2
    assert "matched_issue_count: 2" in render_envelope_text(
        envelope, resolved_root="/repo"
    )


def test_not_found_problem_has_null_result_and_no_success_guidance() -> None:
    envelope = problem_envelope(
        operation="obligation.get",
        snapshot={
            "snapshot_hash": "a" * 64,
            "file_count": 1,
            "byte_count": 20,
            "unreadable_count": 0,
        },
        code="NOT_FOUND",
        message="The requested obligation does not exist in this snapshot.",
        action="Run backstitch obligation list and use an exact returned identity.",
        details={"identity": "docs/specs/a.md#NOPE"},
    )

    assert envelope["result"] is None
    assert envelope["guidance"] == []
    assert envelope["problems"] == [
        {
            "code": "NOT_FOUND",
            "message": "The requested obligation does not exist in this snapshot.",
            "action": "Run backstitch obligation list and use an exact returned identity.",
            "details": {"identity": "docs/specs/a.md#NOPE"},
        }
    ]


@pytest.mark.parametrize(
    ("code", "details"),
    (
        ("INVALID_INPUT", {"field": "limit", "reason": "must be positive"}),
        ("UNSUPPORTED_PLATFORM", {"platform": "unsupported"}),
        ("NOT_FOUND", {"identity": "missing"}),
        ("CURSOR_INVALID", {"reason": "digest mismatch"}),
        ("SNAPSHOT_UNSTABLE", {"attempts": 3}),
        ("SOURCE_UNREADABLE", {"path": "pkg/x.py", "error_class": "io"}),
        (
            "BUDGET_EXHAUSTED",
            {"budget": "work_units", "limit": 10, "observed": 11},
        ),
        (
            "DEADLINE_EXCEEDED",
            {
                "limit_milliseconds": 1000,
                "phase": "candidate_detail",
                "configured_key": "obligations.maximum_call_seconds",
                "cooperative_tolerance_milliseconds": 100,
            },
        ),
        ("INTERNAL_ERROR", {}),
    ),
)
def test_every_closed_problem_detail_shape_fires(
    code: str, details: dict[str, object]
) -> None:
    envelope = problem_envelope(
        operation="obligation.get",
        snapshot=None,
        code=cast(OperationProblemCode, code),
        message="Operation failed.",
        action="Correct the problem and retry.",
        details=details,
    )

    assert envelope["problems"][0]["code"] == code


@pytest.mark.parametrize("phase", DEADLINE_PHASES)
def test_every_deadline_phase_fires_in_the_closed_problem_shape(phase: str) -> None:
    envelope = problem_envelope(
        operation="obligation.get",
        snapshot=None,
        code="DEADLINE_EXCEEDED",
        message="Operation exceeded its deadline.",
        action="Raise obligations.maximum_call_seconds and retry.",
        details={
            "limit_milliseconds": 1000,
            "phase": phase,
            "configured_key": "obligations.maximum_call_seconds",
            "cooperative_tolerance_milliseconds": 100,
        },
    )

    assert envelope["problems"][0]["details"]["phase"] == phase


def test_problem_envelope_rejects_open_or_malformed_detail_shapes() -> None:
    with pytest.raises(ValueError, match="invalid shape"):
        problem_envelope(
            operation="obligation.get",
            snapshot=None,
            code="NOT_FOUND",
            message="Operation failed.",
            action="Retry.",
            details={"identity": "x", "extra": True},
        )
    with pytest.raises(ValueError, match="invalid shape"):
        problem_envelope(
            operation="obligation.list",
            snapshot=None,
            code="INVALID_INPUT",
            message="Operation failed.",
            action="Retry.",
            details={"field": "path", "reason": "invalid mapping", "line": 9},
        )
    with pytest.raises(ValueError, match="closed vocabulary"):
        problem_envelope(
            operation="obligation.get",
            snapshot=None,
            code="BUDGET_EXHAUSTED",
            message="Operation failed.",
            action="Retry.",
            details={"budget": "tokens", "limit": 1, "observed": 2},
        )
    with pytest.raises(ValueError, match="line-safe"):
        problem_envelope(
            operation="obligation.get",
            snapshot=None,
            code="NOT_FOUND",
            message="Operation failed.",
            action="Retry.",
            details={"identity": "bad\x00identity"},
        )
    with pytest.raises(ValueError, match="line-safe"):
        problem_envelope(
            operation="obligation.get",
            snapshot=None,
            code="NOT_FOUND",
            message="Operation failed.",
            action="Retry.",
            details={"identity": "x" * 4097},
        )


def test_page_cursor_is_content_addressed_and_context_bound() -> None:
    token = encode_page_cursor(
        operation="obligation.list",
        snapshot_hash="a" * 64,
        obligation_id=None,
        selector="list",
        limit=25,
        after=("docs/specs/a.md", 3, "obligation", "docs/specs/a.md#A-1"),
    )

    decoded = decode_page_cursor(
        token,
        operation="obligation.list",
        snapshot_hash="a" * 64,
        obligation_id=None,
        selector="list",
        limit=25,
    )

    assert decoded["after"] == [
        "docs/specs/a.md",
        3,
        "obligation",
        "docs/specs/a.md#A-1",
    ]
    assert decoded["cursor_version"] == 2
    assert decoded["filters"] == {}
    with pytest.raises(CursorError, match="digest"):
        decode_page_cursor(
            token[:-1] + ("0" if token[-1] != "0" else "1"),
            operation="obligation.list",
            snapshot_hash="a" * 64,
            obligation_id=None,
            selector="list",
            limit=25,
        )
    with pytest.raises(CursorError, match="snapshot"):
        decode_page_cursor(
            token,
            operation="obligation.list",
            snapshot_hash="b" * 64,
            obligation_id=None,
            selector="list",
            limit=25,
        )

    boolean_limit = encode_page_cursor(
        operation="obligation.list",
        snapshot_hash="a" * 64,
        obligation_id=None,
        selector="list",
        limit=True,
        after=("docs/specs/a.md", 3, 1, "docs/specs/a.md#A-1"),
    )
    with pytest.raises(CursorError, match="shape"):
        decode_page_cursor(
            boolean_limit,
            operation="obligation.list",
            snapshot_hash="a" * 64,
            obligation_id=None,
            selector="list",
            limit=1,
        )

    boolean_version_value = {
        "cursor_version": True,
        "operation": "obligation.list",
        "snapshot_hash": "a" * 64,
        "obligation_id": None,
        "selector": "list",
        "filters": {},
        "limit": 25,
        "after": ["docs/specs/a.md", 3, 1, "docs/specs/a.md#A-1"],
    }
    raw = json.dumps(
        boolean_version_value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    payload = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    boolean_version = f"{payload}.{hashlib.sha256(raw).hexdigest()}"
    with pytest.raises(CursorError, match="shape"):
        decode_page_cursor(
            boolean_version,
            operation="obligation.list",
            snapshot_hash="a" * 64,
            obligation_id=None,
            selector="list",
            limit=25,
        )

    padded_payload, padded_digest = token.split(".")
    with pytest.raises(CursorError, match="encoding"):
        decode_page_cursor(
            f"{padded_payload}=.{padded_digest}",
            operation="obligation.list",
            snapshot_hash="a" * 64,
            obligation_id=None,
            selector="list",
            limit=25,
        )


def test_list_pagination_resumes_after_the_exact_ordering_tuple() -> None:
    snapshot = SnapshotIdentity("a" * 64, 2, 40, 0)

    def record(section_id: str, line: int) -> ObligationRecord:
        return ObligationRecord(
            obligation_id=f"docs/specs/a.md#{section_id}",
            kind="section",
            path="docs/specs/a.md",
            start_line=line,
            end_line=line,
            title=section_id,
            intent_state="identified",
            alignment_state="untraced",
            disposition="evaluate",
            obligation_rung="active",
            gate_state="not_executable",
            required_roles=("implementation",),
            evidence_counts=EvidenceCounts(),
            candidate_counts=CandidateCounts(),
            blocking_reasons=(),
            next_actions=("RUN_DETERMINISTIC_CHECK",),
        )

    inventory = ObligationInventory(
        snapshot=snapshot,
        obligations=(record("A-1", 3), record("A-2", 8)),
        unaddressable_intent=(),
        next_actions=("RUN_DETERMINISTIC_CHECK",),
    )

    first = inventory_list_envelope(inventory, limit=1)
    cursor = first["result"]["next_cursor"]
    assert [row["obligation_id"] for row in first["result"]["entries"]] == [
        "docs/specs/a.md#A-1"
    ]
    assert isinstance(cursor, str)

    second = inventory_list_envelope(inventory, limit=1, cursor=cursor)
    assert [row["obligation_id"] for row in second["result"]["entries"]] == [
        "docs/specs/a.md#A-2"
    ]
    assert second["result"]["next_cursor"] is None


def test_list_uses_closed_entry_type_order_and_rejects_typed_cursor_drift() -> None:
    snapshot = SnapshotIdentity("a" * 64, 2, 40, 0)
    obligation = ObligationRecord(
        obligation_id="docs/specs/a.md#A-1",
        kind="section",
        path="docs/specs/a.md",
        start_line=3,
        end_line=3,
        title="A-1",
        intent_state="identified",
        alignment_state="untraced",
        disposition="evaluate",
        obligation_rung="active",
        gate_state="not_executable",
        required_roles=("implementation",),
        evidence_counts=EvidenceCounts(),
        candidate_counts=CandidateCounts(),
        blocking_reasons=(),
        next_actions=("RUN_DETERMINISTIC_CHECK",),
    )
    unaddressable = UnaddressableIntent(
        "unaddressable:sha256:" + "1" * 64,
        "SPEC_SECTION_DUPLICATE",
        "docs/specs/a.md",
        3,
        "duplicate",
        "## Duplicate [A-1]",
    )
    inventory = ObligationInventory(
        snapshot,
        (obligation,),
        (unaddressable,),
        ("FIX_OBLIGATION_IDENTITY",),
    )

    envelope = inventory_list_envelope(inventory, limit=2)
    assert [item["entry_type"] for item in envelope["result"]["entries"]] == [
        "unaddressable_intent",
        "obligation",
    ]

    malformed = encode_page_cursor(
        operation="obligation.list",
        snapshot_hash=snapshot.snapshot_hash,
        obligation_id=None,
        selector="list",
        limit=1,
        after=("docs/specs/a.md", "3", 0, unaddressable.entry_identity),
        filters=ListFilters().to_row(),
    )
    with pytest.raises(CursorError, match="ordering tuple"):
        inventory_list_envelope(inventory, limit=1, cursor=malformed)


def test_evidence_pagination_binds_obligation_selector_limit_and_snapshot() -> None:
    snapshot = SnapshotIdentity("a" * 64, 2, 40, 0)
    obligation = ObligationRecord(
        obligation_id="docs/specs/a.md#A-1",
        kind="section",
        path="docs/specs/a.md",
        start_line=3,
        end_line=6,
        title="A-1",
        intent_state="identified",
        alignment_state="complete",
        disposition="evaluate",
        obligation_rung="active",
        gate_state="executable",
        required_roles=("implementation",),
        evidence_counts=EvidenceCounts(2, 0, 0),
        candidate_counts=CandidateCounts(),
        blocking_reasons=(),
        next_actions=("RUN_DETERMINISTIC_CHECK",),
    )
    inventory = ObligationInventory(
        snapshot=snapshot,
        obligations=(obligation,),
        unaddressable_intent=(),
        next_actions=("RUN_DETERMINISTIC_CHECK",),
    )

    def item(path: str, line: int) -> dict[str, object]:
        return {
            "role": "implementation",
            "path": path,
            "symbol": "run",
            "owner": "run",
            "start_line": line,
            "end_line": line,
            "relation_kinds": ["spec_mapping", "code_backlink"],
            "reciprocity_state": "complete",
            "receipt": {},
            "excerpt": "pass\n",
            "declared_target": None,
        }

    first = evidence_summary_envelope(
        inventory,
        obligation,
        (item("pkg/a.py", 1), item("pkg/b.py", 2)),
        limit=1,
        cursor=None,
    )
    cursor = first["result"]["next_cursor"]
    assert isinstance(cursor, str)
    assert [row["path"] for row in first["result"]["items"]] == ["pkg/a.py"]

    second = evidence_summary_envelope(
        inventory,
        obligation,
        (item("pkg/a.py", 1), item("pkg/b.py", 2)),
        limit=1,
        cursor=cursor,
    )
    assert [row["path"] for row in second["result"]["items"]] == ["pkg/b.py"]
    assert second["result"]["next_cursor"] is None

    with pytest.raises(CursorError, match="limit"):
        evidence_summary_envelope(
            inventory,
            obligation,
            (item("pkg/a.py", 1), item("pkg/b.py", 2)),
            limit=2,
            cursor=cursor,
        )

    malformed = encode_page_cursor(
        operation="obligation.summarize_evidence",
        snapshot_hash=snapshot.snapshot_hash,
        obligation_id=obligation.obligation_id,
        selector="summarize_evidence",
        limit=1,
        after=("implementation", "pkg/a.py", 1, 1, "run", ["spec_mapping"]),
    )
    with pytest.raises(CursorError, match="ordering tuple"):
        evidence_summary_envelope(
            inventory,
            obligation,
            (item("pkg/a.py", 1), item("pkg/b.py", 2)),
            limit=1,
            cursor=malformed,
        )

    first_target = item("docs/specs/a.md", 3)
    first_target["declared_target"] = "pkg/a.py::run"
    second_target = item("docs/specs/a.md", 3)
    second_target["declared_target"] = "pkg/b.py::run"
    target_page = evidence_summary_envelope(
        inventory,
        obligation,
        (first_target, second_target),
        limit=1,
        cursor=None,
    )
    target_cursor = target_page["result"]["next_cursor"]
    assert target_cursor is not None
    target_second_page = evidence_summary_envelope(
        inventory,
        obligation,
        (first_target, second_target),
        limit=1,
        cursor=target_cursor,
    )
    assert [
        row["declared_target"] for row in target_second_page["result"]["items"]
    ] == ["pkg/b.py::run"]

    nfd_target = item("docs/specs/a.md", 3)
    nfd_target["declared_target"] = "pkg/cafe\u0301.py::run"
    later_target = item("docs/specs/a.md", 3)
    later_target["declared_target"] = "pkg/z.py::run"
    nfd_page = evidence_summary_envelope(
        inventory,
        obligation,
        (nfd_target, later_target),
        limit=1,
        cursor=None,
    )
    nfd_cursor = nfd_page["result"]["next_cursor"]
    assert nfd_cursor is not None
    assert evidence_summary_envelope(
        inventory,
        obligation,
        (nfd_target, later_target),
        limit=1,
        cursor=nfd_cursor,
    )["result"]["items"] == [later_target]


def test_candidate_pagination_and_detail_share_the_exact_candidate_projection() -> None:
    snapshot = SnapshotIdentity("a" * 64, 2, 40, 0)
    obligation = ObligationRecord(
        obligation_id="docs/specs/a.md#A-1",
        kind="section",
        path="docs/specs/a.md",
        start_line=3,
        end_line=6,
        title="A-1",
        intent_state="identified",
        alignment_state="untraced",
        disposition="evaluate",
        obligation_rung="active",
        gate_state="not_executable",
        required_roles=("implementation",),
        evidence_counts=EvidenceCounts(),
        candidate_counts=CandidateCounts(),
        blocking_reasons=(),
        next_actions=("RUN_DETERMINISTIC_CHECK",),
    )
    inventory = ObligationInventory(
        snapshot=snapshot,
        obligations=(obligation,),
        unaddressable_intent=(),
        next_actions=("RUN_DETERMINISTIC_CHECK",),
    )

    def candidate(path: str, candidate_id: str) -> EvidenceCandidate:
        receipt = SourceReceipt(1, path, "python-module:pkg.a", 1, 1, "b" * 64)
        return EvidenceCandidate(
            candidate_id=candidate_id,
            candidate_kind="implementation_definition",
            path=path,
            owner="module",
            start_line=1,
            end_line=1,
            structural_locator="python-module:pkg.a",
            receipt=receipt,
            discovery_bases=("lexical_match",),
            lexical_score=(1, 3),
            static_relations=(),
            declared_relations=(),
            trace_state="untraced",
            suggested_trace_edits=(),
            _raw_span=b"pass\n",
        )

    first_candidate = candidate("pkg/a.py", "candidate:sha256:" + "1" * 64)
    second_candidate = candidate("pkg/b.py", "candidate:sha256:" + "2" * 64)
    first = find_evidence_envelope(
        inventory,
        obligation,
        (first_candidate, second_candidate),
        limit=1,
        cursor=None,
    )
    cursor = first["result"]["next_cursor"]
    assert isinstance(cursor, str)
    assert first["result"]["candidates"] == [first_candidate.to_row()]

    second = find_evidence_envelope(
        inventory,
        obligation,
        (first_candidate, second_candidate),
        limit=1,
        cursor=cursor,
    )
    assert second["result"]["candidates"] == [second_candidate.to_row()]
    assert second["result"]["next_cursor"] is None

    source = CandidateSource(first_candidate.receipt, "pass\n", "c" * 64)
    neighbors = (
        CandidateNeighbor(second_candidate.candidate_id, "static_call", "outgoing"),
    )
    detail = candidate_detail_envelope(
        inventory,
        obligation,
        first_candidate,
        source,
        neighbors,
    )
    assert detail["operation"] == "obligation.get_candidate"
    assert detail["result"] == {
        "obligation_id": obligation.obligation_id,
        "candidate": first_candidate.to_row(),
        "source": source.to_row(),
        "neighbors": [neighbors[0].to_row()],
    }

    malformed = encode_page_cursor(
        operation="obligation.find_evidence",
        snapshot_hash=inventory.snapshot.snapshot_hash,
        obligation_id=obligation.obligation_id,
        selector="find_evidence",
        limit=1,
        after=("wrong", 0, 0, 0, "", 0, "", ""),
    )
    with pytest.raises(CursorError, match="ordering tuple"):
        find_evidence_envelope(
            inventory,
            obligation,
            (first_candidate, second_candidate),
            limit=1,
            cursor=malformed,
        )
