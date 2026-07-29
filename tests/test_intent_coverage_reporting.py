"""Closed intent-coverage report behavior.

Spec: docs/specs/08-intent-coverage.md [COV-3], [COV-9]
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from typing import Any, TypeVar, cast

import pytest

from backstitch.canonical import canonical_json_bytes
from backstitch.git_baseline import (
    DriftEvent,
    GitBaselineMetadata,
    PolicyEvent,
    StaleDocTrend,
)
from backstitch.intent_coverage import (
    ClassifiedDefinition,
    CoverageCounts,
    CoverageDefinition,
    CoverageExemptionFact,
    CoverageFloorResult,
    CoverageUnscannableFile,
    IntentCoverageResult,
    RequirementCoverage,
    classify_intent_coverage,
)
from backstitch.intent_coverage_reporting import (
    CoverageReportError,
    build_coverage_report,
    render_coverage_json,
    validate_coverage_report,
)
from backstitch.models import Issue, Report

T = TypeVar("T")


def _raw_report() -> Report:
    return Report(
        profile="test",
        repo_root="/repo",
        spec_sections=(),
        code_refs=(),
        spec_mappings=(),
        edges=(),
        issues=(),
    )


def _definition_id(path: str, locator: str) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            canonical_json_bytes(["intent-definition-v1", path, locator])
        ).hexdigest()
    )


def _sha256(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _stable_id(preimage: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(preimage)).hexdigest()


def _unsafe_replace(instance: T, changes: dict[str, object]) -> T:
    return cast(T, dataclasses.replace(cast(Any, instance), **changes))


def _baseline() -> GitBaselineMetadata:
    return GitBaselineMetadata(
        configured_ref="refs/heads/main",
        resolved_commit="a" * 40,
        merge_base="b" * 40,
        current_snapshot_sha256=_sha256("snapshot"),
        current_content_sha256=_sha256("content"),
        baseline_policy_sha256=_sha256("baseline-policy"),
        current_policy_sha256=_sha256("current-policy"),
        history_complete=True,
        history_commits_inspected=0,
    )


def _empty_result() -> IntentCoverageResult:
    return classify_intent_coverage((), _raw_report())


def _ratchet_report(
    *,
    result: IntentCoverageResult | None = None,
    baseline: GitBaselineMetadata | None = None,
    policy_events: tuple[PolicyEvent, ...] = (),
    drift_events: tuple[DriftEvent, ...] = (),
    stale_doc_trends: tuple[StaleDocTrend, ...] = (),
    issues: tuple[Issue, ...] = (),
) -> dict[str, Any]:
    return build_coverage_report(
        result or _empty_result(),
        profile="test",
        repo_root="/repo",
        mode="ratchet",
        inherited_counts=False,
        issues=issues,
        baseline=baseline or _baseline(),
        policy_events=policy_events,
        drift_events=drift_events,
        stale_doc_trends=stale_doc_trends,
    )


def test_report_mode_builds_content_bound_closed_json() -> None:
    path = "pkg/example.py"
    locator = "python-definition:run:function:0"
    definition = CoverageDefinition(
        definition_id=_definition_id(path, locator),
        path=path,
        structural_locator=locator,
        qualname="run",
        kind="function",
        role="production",
        start_line=1,
        end_line=2,
        source_projection_sha256=_sha256("source"),
        parent_definition_id="sha256:module",
        tree="pkg",
    )
    result = classify_intent_coverage((definition,), _raw_report())

    payload = build_coverage_report(
        result,
        profile="test",
        repo_root="/repo",
        mode="report",
        inherited_counts=False,
        issues=(),
    )
    rendered = render_coverage_json(
        payload,
        source_result=result,
        inherited_counts=False,
    )
    decoded = json.loads(rendered)

    assert decoded["artifact"] == "backstitch-intent-coverage-report"
    assert decoded["schema_version"] == 1
    assert decoded["baseline"] is None
    assert decoded["summary"]["uncovered"] == 1
    assert decoded["worklist"] == [definition.definition_id]
    assert decoded["report_sha256"].startswith("sha256:")
    validate_coverage_report(
        decoded,
        source_result=result,
        inherited_counts=False,
    )


def test_report_validator_rejects_mutated_content_hash() -> None:
    result = classify_intent_coverage((), _raw_report())
    payload = build_coverage_report(
        result,
        profile="test",
        repo_root="/repo",
        mode="report",
        inherited_counts=False,
        issues=(),
    )
    payload["summary"]["total"] = 1

    with pytest.raises(CoverageReportError, match="summary total"):
        validate_coverage_report(
            payload,
            source_result=result,
            inherited_counts=False,
        )


def test_unscannable_file_marks_repository_and_tree_incomplete() -> None:
    result = classify_intent_coverage((), _raw_report())
    payload = build_coverage_report(
        result,
        profile="test",
        repo_root="/repo",
        mode="report",
        inherited_counts=False,
        issues=(),
        unscannable_files=(
            CoverageUnscannableFile(
                path="pkg/bad.py",
                role="production",
                tree="pkg",
                issue_identities=(("PYTHON_SYNTAX_ERROR", "pkg/bad.py", 1),),
            ),
        ),
    )

    assert payload["summary"]["complete"] is False
    assert payload["summary"]["unscannable"] == 1
    assert payload["trees"][0]["complete"] is False
    assert payload["unscannable_files"][0]["issue_identities"] == [
        {"code": "PYTHON_SYNTAX_ERROR", "path": "pkg/bad.py", "line": 1}
    ]


def test_report_validator_rejects_unknown_nested_keys() -> None:
    result = classify_intent_coverage((), _raw_report())
    payload = build_coverage_report(
        result,
        profile="test",
        repo_root="/repo",
        mode="report",
        inherited_counts=False,
        issues=(),
    )
    payload["summary"]["invented"] = 0

    with pytest.raises(CoverageReportError, match="summary"):
        validate_coverage_report(
            payload,
            source_result=result,
            inherited_counts=False,
        )


def test_report_validator_recomputes_accounted_rate_from_source_facts() -> None:
    result = classify_intent_coverage((), _raw_report())
    payload = build_coverage_report(
        result,
        profile="test",
        repo_root="/repo",
        mode="report",
        inherited_counts=False,
        issues=(),
    )
    payload["summary"]["accounted_rate"] = 0.5

    with pytest.raises(CoverageReportError, match="accounted_rate"):
        validate_coverage_report(
            payload,
            source_result=result,
            inherited_counts=False,
        )


def test_report_validator_rejects_forged_classification_partition() -> None:
    path = "pkg/example.py"
    locator = "python-definition:run:function:0"
    result = classify_intent_coverage(
        (
            CoverageDefinition(
                definition_id=_definition_id(path, locator),
                path=path,
                structural_locator=locator,
                qualname="run",
                kind="function",
                role="production",
                start_line=1,
                end_line=1,
                source_projection_sha256=_sha256("source"),
                parent_definition_id=None,
                tree="pkg",
            ),
        ),
        _raw_report(),
    )
    payload = build_coverage_report(
        result,
        profile="test",
        repo_root="/repo",
        mode="report",
        inherited_counts=False,
        issues=(),
    )
    payload["definitions"][0]["classification"] = "exempt"
    payload["worklist"] = []
    payload["summary"]["exempt"] = 1
    payload["summary"]["uncovered"] = 0
    payload["summary"]["accounted_rate"] = 1.0

    with pytest.raises(CoverageReportError, match="source facts"):
        validate_coverage_report(
            payload,
            source_result=result,
            inherited_counts=False,
        )


@pytest.mark.parametrize(
    ("field", "value", "error"),
    (
        ("resolved_commit", "A" * 40, "Git object ID"),
        ("merge_base", "a" * 64, "Git object ID"),
        ("current_content_sha256", "sha256:not-a-digest", "sha256 token"),
        ("history_complete", 1, "boolean"),
        ("history_commits_inspected", -1, "nonnegative integer"),
    ),
)
def test_report_builder_rejects_malformed_baseline_source_facts(
    field: str,
    value: object,
    error: str,
) -> None:
    baseline = _unsafe_replace(_baseline(), {field: value})

    with pytest.raises(CoverageReportError, match=error):
        _ratchet_report(baseline=baseline)


@pytest.mark.parametrize(
    ("field", "value", "error"),
    (
        ("complete", 1, "boolean"),
        ("unscannable", -1, "nonnegative integer"),
        ("direct", True, "nonnegative integer"),
        ("direct_rate", float("nan"), "finite number"),
    ),
)
def test_report_validator_rejects_malformed_summary_primitives(
    field: str,
    value: object,
    error: str,
) -> None:
    result = _empty_result()
    payload = build_coverage_report(
        result,
        profile="test",
        repo_root="/repo",
        mode="report",
        inherited_counts=False,
        issues=(),
    )
    payload["summary"][field] = value

    with pytest.raises(CoverageReportError, match=error):
        validate_coverage_report(
            payload,
            source_result=result,
            inherited_counts=False,
        )


def _policy_event(
    *,
    key: str = "/coverage/inherited_counts",
    before: object = False,
    after: object = True,
) -> PolicyEvent:
    parent_commit = "c" * 40
    return PolicyEvent(
        event_id=_stable_id(
            [
                "intent-policy-event-v1",
                parent_commit,
                key,
                before,
                after,
            ]
        ),
        parent_commit=parent_commit,
        key=key,
        baseline_value=before,
        current_value=after,
        transition_commit=None,
    )


def test_report_builder_canonicalizes_multiple_policy_events_by_event_id() -> None:
    events = tuple(
        sorted(
            (
                _policy_event(key="/coverage/inherited_counts"),
                _policy_event(
                    key="/diagnostics",
                    before={"default_level": "info"},
                    after={"default_level": "warning"},
                ),
            ),
            key=lambda item: item.event_id,
            reverse=True,
        )
    )

    payload = _ratchet_report(policy_events=events)

    assert [row["event_id"] for row in payload["policy_events"]] == sorted(
        item.event_id for item in events
    )


@pytest.mark.parametrize(
    ("changes", "error"),
    (
        ({"event_id": _sha256("forged")}, "event_id is invalid"),
        ({"event_id": "sha256:short"}, "sha256 token"),
        ({"parent_commit": "C" * 40}, "Git object ID"),
        ({"acknowledged": 1}, "boolean"),
        ({"acknowledged": True}, "acknowledgment state"),
        ({"baseline_value": float("inf")}, "non-finite"),
    ),
)
def test_report_builder_rejects_malformed_policy_event_source_facts(
    changes: dict[str, object],
    error: str,
) -> None:
    event = _unsafe_replace(_policy_event(), changes)

    with pytest.raises(CoverageReportError, match=error):
        _ratchet_report(policy_events=(event,))


def _drift_result_and_event() -> tuple[IntentCoverageResult, DriftEvent]:
    path = "pkg/example.py"
    locator = "python-definition:run:function:0"
    definition_id = _definition_id(path, locator)
    definition = CoverageDefinition(
        definition_id=definition_id,
        path=path,
        structural_locator=locator,
        qualname="run",
        kind="function",
        role="production",
        start_line=1,
        end_line=2,
        source_projection_sha256=_sha256("current projection"),
        parent_definition_id=None,
        tree="pkg",
    )
    requirement_path = "docs/specs/example.md"
    section_id = "EX-1"
    requirement_id = _stable_id(["intent-requirement-v1", requirement_path, section_id])
    result = IntentCoverageResult(
        definitions=(ClassifiedDefinition(definition, "direct"),),
        worklist=(),
        summary=CoverageCounts(
            direct=1,
            inherited=0,
            exempt=0,
            uncovered=0,
            total=1,
            direct_numerator=1,
            accounted_numerator=1,
        ),
        requirements=(
            RequirementCoverage(
                requirement_id=requirement_id,
                path=requirement_path,
                section_id=section_id,
                rung="active",
                implementation_state="implemented",
                owner_definition_ids=(definition_id,),
            ),
        ),
        exemptions=(),
    )
    edge_id = _stable_id(
        [
            "intent-edge-v1",
            requirement_path,
            section_id,
            path,
            locator,
        ]
    )
    before_section = _sha256("section")
    after_section = before_section
    before_mapping = _sha256("mapping")
    after_mapping = before_mapping
    before_tests = _sha256("tests")
    after_tests = before_tests
    base_projection = _sha256("base projection")
    current_projection = _sha256("current projection")
    event = DriftEvent(
        event_id=_stable_id(
            [
                "intent-drift-event-v1",
                edge_id,
                "d" * 40,
                before_section,
                after_section,
                before_mapping,
                after_mapping,
                base_projection,
                current_projection,
                before_tests,
                after_tests,
            ]
        ),
        edge_id=edge_id,
        requirement_id=requirement_id,
        definition_id=definition_id,
        parent_commit="d" * 40,
        transition_commit=None,
        base_projection_sha256=base_projection,
        current_projection_sha256=current_projection,
        before_section_hash=before_section,
        after_section_hash=after_section,
        before_mapping_hash=before_mapping,
        after_mapping_hash=after_mapping,
        before_connected_test_hash=before_tests,
        after_connected_test_hash=after_tests,
        synthetic_current=True,
    )
    return result, event


def _drift_event_with_parent(event: DriftEvent, parent_commit: str) -> DriftEvent:
    return dataclasses.replace(
        event,
        event_id=_stable_id(
            [
                "intent-drift-event-v1",
                event.edge_id,
                parent_commit,
                event.before_section_hash,
                event.after_section_hash,
                event.before_mapping_hash,
                event.after_mapping_hash,
                event.base_projection_sha256,
                event.current_projection_sha256,
                event.before_connected_test_hash,
                event.after_connected_test_hash,
            ]
        ),
        parent_commit=parent_commit,
    )


def test_report_builder_canonicalizes_multiple_drift_events_by_event_id() -> None:
    result, source_event = _drift_result_and_event()
    events = tuple(
        sorted(
            (
                source_event,
                _drift_event_with_parent(source_event, "e" * 40),
            ),
            key=lambda item: item.event_id,
            reverse=True,
        )
    )

    payload = _ratchet_report(result=result, drift_events=events)

    assert [row["event_id"] for row in payload["drift_events"]] == sorted(
        item.event_id for item in events
    )


@pytest.mark.parametrize(
    ("changes", "error"),
    (
        ({"event_id": "sha256:short"}, "sha256 token"),
        ({"edge_id": _sha256("forged edge")}, "edge_id is invalid"),
        ({"base_projection_sha256": "sha256:short"}, "sha256 token"),
        (
            {"base_projection_sha256": _sha256("current projection")},
            "did not change",
        ),
        ({"synthetic_current": 1}, "boolean"),
        ({"synthetic_current": False}, "synthetic transition"),
        ({"acknowledged": True}, "acknowledgment state"),
    ),
)
def test_report_builder_rejects_malformed_drift_event_source_facts(
    changes: dict[str, object],
    error: str,
) -> None:
    result, source_event = _drift_result_and_event()
    event = _unsafe_replace(source_event, changes)

    with pytest.raises(CoverageReportError, match=error):
        _ratchet_report(result=result, drift_events=(event,))


@pytest.mark.parametrize(
    ("changes", "error"),
    (
        ({"edge_id": "sha256:short"}, "sha256 token"),
        ({"section_change_commit": "E" * 40}, "Git object ID"),
        ({"unacknowledged_event_count": -1}, "nonnegative integer"),
        ({"history_complete": 1}, "boolean"),
        ({"commits_inspected": True}, "nonnegative integer"),
    ),
)
def test_report_builder_rejects_malformed_stale_trend_source_facts(
    changes: dict[str, object],
    error: str,
) -> None:
    trend = _unsafe_replace(
        StaleDocTrend(
            edge_id=_sha256("historical edge"),
            section_change_commit=None,
            unacknowledged_event_count=0,
            last_event_commit=None,
            history_complete=True,
            commits_inspected=0,
        ),
        changes,
    )

    with pytest.raises(CoverageReportError, match=error):
        _ratchet_report(stale_doc_trends=(trend,))


def test_report_builder_rejects_malformed_issue_source_dataclass() -> None:
    issue = Issue(
        code="BSN001",
        severity=cast(Any, "fatal"),
        path="pkg/example.py",
        line=1,
        message="uncovered",
        short_code="BSN001",
        default_severity=cast(Any, "fatal"),
    )

    with pytest.raises(CoverageReportError, match="issue severity"):
        _ratchet_report(issues=(issue,))


def test_report_builder_rejects_forged_definition_id_source_fact() -> None:
    result, _ = _drift_result_and_event()
    source_row = result.definitions[0]
    forged_definition = dataclasses.replace(
        source_row.definition,
        definition_id=_sha256("forged definition"),
    )
    forged_result = dataclasses.replace(
        result,
        definitions=(dataclasses.replace(source_row, definition=forged_definition),),
    )

    with pytest.raises(CoverageReportError, match="definition_id is invalid"):
        build_coverage_report(
            forged_result,
            profile="test",
            repo_root="/repo",
            mode="report",
            inherited_counts=False,
            issues=(),
        )


def test_report_builder_rejects_forged_requirement_id_source_fact() -> None:
    result, _ = _drift_result_and_event()
    forged_result = dataclasses.replace(
        result,
        requirements=(
            dataclasses.replace(
                result.requirements[0],
                requirement_id=_sha256("forged requirement"),
            ),
        ),
    )

    with pytest.raises(CoverageReportError, match="requirement_id is invalid"):
        build_coverage_report(
            forged_result,
            profile="test",
            repo_root="/repo",
            mode="report",
            inherited_counts=False,
            issues=(),
        )


def test_report_builder_rejects_forged_exemption_id_source_fact() -> None:
    result, _ = _drift_result_and_event()
    definition = result.definitions[0].definition
    selector = definition.path
    exemption_id = _stable_id(["intent-exemption-v1", "config_path", selector])
    exempt_result = classify_intent_coverage(
        (definition,),
        _raw_report(),
        exemptions=(
            CoverageExemptionFact(
                exemption_id=exemption_id,
                matched_definition_ids=(definition.definition_id,),
                origin="config_path",
                path="/repo/.backstitch.toml",
                selector=selector,
                reason="generated adapter",
            ),
        ),
    )
    forged_result = dataclasses.replace(
        exempt_result,
        exemptions=(
            dataclasses.replace(
                exempt_result.exemptions[0],
                exemption_id=_sha256("forged exemption"),
            ),
        ),
    )

    with pytest.raises(CoverageReportError, match="exemption_id is invalid"):
        build_coverage_report(
            forged_result,
            profile="test",
            repo_root="/repo",
            mode="report",
            inherited_counts=False,
            issues=(),
        )


@pytest.mark.parametrize(
    ("changes", "error"),
    (
        ({"passes": 1}, "boolean"),
        ({"direct_target": float("inf")}, "non-finite"),
    ),
)
def test_report_builder_rejects_malformed_floor_source_facts(
    changes: dict[str, object],
    error: str,
) -> None:
    floor = _unsafe_replace(
        CoverageFloorResult(
            scope=".",
            counts=CoverageCounts(
                direct=0,
                inherited=0,
                exempt=0,
                uncovered=0,
                total=0,
                direct_numerator=0,
                accounted_numerator=0,
            ),
            direct_target=0.0,
            accounted_target=None,
            passes=True,
        ),
        changes,
    )

    with pytest.raises(CoverageReportError, match=error):
        build_coverage_report(
            _empty_result(),
            profile="test",
            repo_root="/repo",
            mode="report",
            inherited_counts=False,
            issues=(),
            floors=(floor,),
        )


def test_report_builder_rejects_boolean_unscannable_line_source_fact() -> None:
    with pytest.raises(CoverageReportError, match="positive integer"):
        build_coverage_report(
            _empty_result(),
            profile="test",
            repo_root="/repo",
            mode="report",
            inherited_counts=False,
            issues=(),
            unscannable_files=(
                CoverageUnscannableFile(
                    path="pkg/bad.py",
                    role="production",
                    tree="pkg",
                    issue_identities=(
                        ("PYTHON_SYNTAX_ERROR", "pkg/bad.py", cast(Any, True)),
                    ),
                ),
            ),
        )


def test_report_validator_rejects_non_sha256_report_hash() -> None:
    result = _empty_result()
    payload = build_coverage_report(
        result,
        profile="test",
        repo_root="/repo",
        mode="report",
        inherited_counts=False,
        issues=(),
    )
    payload["report_sha256"] = "sha256:short"

    with pytest.raises(CoverageReportError, match="report_sha256"):
        validate_coverage_report(
            payload,
            source_result=result,
            inherited_counts=False,
        )
