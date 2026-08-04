"""Transport-neutral obligation inventory and readiness tests.

Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-2], [EVC-8.3]
"""

from __future__ import annotations

import hashlib
import json

import pytest

from backstitch.config import ProfileConfig
from backstitch.models import (
    Edge,
    InvariantBind,
    InvariantDeclaration,
    Issue,
    Report,
    SpecMapping,
    SpecSection,
)
from backstitch.obligations import (
    CandidateCounts,
    SnapshotIdentity,
    build_obligation_inventory,
    mapping_test_only_issues,
    resolve_evidence_atom,
)

PROFILE = ProfileConfig(
    name="test",
    spec_roots=("docs/specs",),
    plan_roots=("docs/plans",),
    code_roots=("pkg", "tests"),
    test_roots=("tests",),
    planned_spec_globs=("docs/specs/planned-*.md",),
    exploratory_spec_globs=("docs/specs/exploratory-*.md",),
    meta_spec_globs=("docs/specs/meta-*.md",),
)
SNAPSHOT = SnapshotIdentity(
    snapshot_hash="a" * 64,
    file_count=4,
    byte_count=400,
    unreadable_count=0,
)


def _report(
    *,
    sections: tuple[SpecSection, ...] = (),
    mappings: tuple[SpecMapping, ...] = (),
    edges: tuple[Edge, ...] = (),
    issues: tuple[Issue, ...] = (),
    invariants: tuple[InvariantDeclaration, ...] = (),
    binds: tuple[InvariantBind, ...] = (),
) -> Report:
    return Report(
        profile="test",
        repo_root="/not/part/of/the/result",
        spec_sections=sections,
        code_refs=(),
        spec_mappings=mappings,
        edges=edges,
        issues=issues,
        invariants=invariants,
        binds=binds,
    )


def _section(
    section_id: str = "X-1",
    *,
    path: str = "docs/specs/01-x.md",
    line: int = 3,
) -> SpecSection:
    return SpecSection(
        path, section_id, "Requirement", line, "requirement-x-1", "heading"
    )


def _mapping(
    section_id: str = "X-1",
    *,
    spec_path: str = "docs/specs/01-x.md",
    path: str = "pkg/x.py",
    symbol: str | None = "run",
    line: int = 8,
) -> SpecMapping:
    target = path if symbol is None else f"{path}::{symbol}"
    return SpecMapping(
        spec_path,
        section_id,
        line,
        target,
        "path" if symbol is None else "path_symbol",
        path,
        symbol,
    )


def _edge(
    kind: str,
    section_id: str = "X-1",
    *,
    spec_path: str = "docs/specs/01-x.md",
    path: str = "pkg/x.py",
    symbol: str | None = "run",
    line: int = 10,
) -> Edge:
    assert kind in {"mapping", "backlink"}
    return Edge(kind, spec_path, section_id, path, symbol, line)  # type: ignore[arg-type]


def test_empty_report_is_a_successful_no_intent_bootstrap() -> None:
    inventory = build_obligation_inventory(
        _report(), profile=PROFILE, snapshot=SNAPSHOT
    )

    assert inventory.snapshot.to_row() == {
        "snapshot_hash": "a" * 64,
        "file_count": 4,
        "byte_count": 400,
        "unreadable_count": 0,
    }
    assert inventory.list_result() == {
        "bootstrap_state": "no_intent",
        "entries": [],
        "next_cursor": None,
    }
    assert inventory.next_actions == ("ADD_OR_CONFIGURE_SPEC_INTENT",)


def test_reciprocal_section_mapping_is_executable_and_file_qualified() -> None:
    section = _section()
    mapping = _mapping()
    inventory = build_obligation_inventory(
        _report(
            sections=(section,),
            mappings=(mapping,),
            edges=(_edge("mapping"), _edge("backlink")),
        ),
        profile=PROFILE,
        snapshot=SNAPSHOT,
    )

    obligation = inventory.get("docs/specs/01-x.md#X-1")
    assert obligation is not None
    assert obligation.kind == "section"
    assert obligation.intent_state == "identified"
    assert obligation.alignment_state == "complete"
    assert obligation.disposition == "evaluate"
    assert obligation.obligation_rung == "active"
    assert obligation.gate_state == "executable"
    assert obligation.required_roles == ("implementation",)
    assert obligation.evidence_counts.to_row() == {
        "implementation": 1,
        "test": 0,
        "binding_test": 0,
    }
    assert obligation.blocking_reasons == ()
    assert obligation.next_actions == (
        "RUN_DETERMINISTIC_CHECK",
        "RUN_CURRENT_ANALYSIS",
    )


def test_one_sided_mapping_is_partial_and_points_to_missing_backlink() -> None:
    inventory = build_obligation_inventory(
        _report(
            sections=(_section(),),
            mappings=(_mapping(),),
            edges=(_edge("mapping"),),
        ),
        profile=PROFILE,
        snapshot=SNAPSHOT,
    )

    obligation = inventory.get("docs/specs/01-x.md#X-1")
    assert obligation is not None
    assert obligation.alignment_state == "partial"
    assert obligation.gate_state == "not_executable"
    assert [reason.to_row() for reason in obligation.blocking_reasons] == [
        {
            "code": "IMPLEMENTATION_PARTIAL",
            "role": "implementation",
            "relation_kind": "spec_mapping",
            "issue_identity": None,
        }
    ]
    assert obligation.next_actions == (
        "ADD_RECIPROCAL_BACKLINK",
        "RUN_DETERMINISTIC_CHECK",
    )


def test_one_complete_mapping_satisfies_role_despite_extra_missing_mapping() -> None:
    resolved = _mapping(line=8)
    missing = _mapping(path="pkg/missing.py", line=8)
    inventory = build_obligation_inventory(
        _report(
            sections=(_section(),),
            mappings=(resolved, missing),
            edges=(
                _edge("mapping", line=8),
                _edge("backlink", line=10),
            ),
        ),
        profile=PROFILE,
        snapshot=SNAPSHOT,
    )

    obligation = inventory.get("docs/specs/01-x.md#X-1")
    assert obligation is not None
    assert obligation.alignment_state == "complete"
    assert obligation.gate_state == "executable"
    assert obligation.evidence_counts.to_row() == {
        "implementation": 2,
        "test": 0,
        "binding_test": 0,
    }
    assert obligation.blocking_reasons == ()


def test_one_sided_backlink_is_partial_and_points_to_missing_mapping() -> None:
    inventory = build_obligation_inventory(
        _report(
            sections=(_section(),),
            edges=(_edge("backlink"),),
        ),
        profile=PROFILE,
        snapshot=SNAPSHOT,
    )

    obligation = inventory.get("docs/specs/01-x.md#X-1")
    assert obligation is not None
    assert obligation.alignment_state == "partial"
    assert [reason.to_row() for reason in obligation.blocking_reasons] == [
        {
            "code": "IMPLEMENTATION_PARTIAL",
            "role": "implementation",
            "relation_kind": "code_backlink",
            "issue_identity": None,
        }
    ]
    assert obligation.next_actions == (
        "ADD_RECIPROCAL_MAPPING",
        "RUN_DETERMINISTIC_CHECK",
    )


def test_required_test_role_reports_test_partial_for_one_sided_mapping() -> None:
    implementation_mapping = _mapping()
    test_mapping = _mapping(path="tests/test_x.py", symbol="test_run", line=9)
    inventory = build_obligation_inventory(
        _report(
            sections=(_section(),),
            mappings=(implementation_mapping, test_mapping),
            edges=(
                _edge("mapping"),
                _edge("backlink"),
                _edge(
                    "mapping",
                    path="tests/test_x.py",
                    symbol="test_run",
                    line=9,
                ),
            ),
        ),
        profile=PROFILE,
        snapshot=SNAPSHOT,
        section_required_roles=("implementation", "test"),
    )

    obligation = inventory.get("docs/specs/01-x.md#X-1")
    assert obligation is not None
    assert obligation.alignment_state == "partial"
    assert [reason.to_row() for reason in obligation.blocking_reasons] == [
        {
            "code": "TEST_PARTIAL",
            "role": "test",
            "relation_kind": "spec_mapping",
            "issue_identity": None,
        }
    ]


def test_ambiguous_relation_is_invalid_and_never_guessed() -> None:
    issue = Issue(
        "TARGET_PATH_AMBIGUOUS",
        "error",
        "docs/specs/01-x.md",
        8,
        "mapping token matches more than one path",
        section_id="X-1",
    )
    inventory = build_obligation_inventory(
        _report(
            sections=(_section(),),
            mappings=(_mapping(),),
            issues=(issue,),
        ),
        profile=PROFILE,
        snapshot=SNAPSHOT,
    )

    obligation = inventory.get("docs/specs/01-x.md#X-1")
    assert obligation is not None
    assert obligation.intent_state == "identified"
    assert obligation.alignment_state == "invalid"
    assert obligation.gate_state == "not_executable"
    assert [reason.code for reason in obligation.blocking_reasons] == ["TRACE_CONFLICT"]
    assert obligation.blocking_reasons[0].issue_identity is None
    assert obligation.next_actions == (
        "REVIEW_CONFLICTED_TRACE",
        "RUN_DETERMINISTIC_CHECK",
    )


def test_section_required_test_role_is_independent_of_implementation() -> None:
    inventory = build_obligation_inventory(
        _report(
            sections=(_section(),),
            mappings=(_mapping(),),
            edges=(_edge("mapping"), _edge("backlink")),
        ),
        profile=PROFILE,
        snapshot=SNAPSHOT,
        section_required_roles=("implementation", "test"),
    )

    obligation = inventory.get("docs/specs/01-x.md#X-1")
    assert obligation is not None
    assert obligation.alignment_state == "partial"
    assert [reason.code for reason in obligation.blocking_reasons] == ["TEST_UNTRACED"]
    assert obligation.next_actions == (
        "ADD_RECIPROCAL_MAPPING",
        "ADD_RECIPROCAL_BACKLINK",
        "RUN_DETERMINISTIC_CHECK",
    )


def test_test_root_relation_satisfies_only_the_test_role() -> None:
    implementation_mapping = _mapping()
    test_mapping = _mapping(path="tests/test_x.py", symbol="test_run", line=9)
    inventory = build_obligation_inventory(
        _report(
            sections=(_section(),),
            mappings=(implementation_mapping, test_mapping),
            edges=(
                _edge("mapping"),
                _edge("backlink"),
                _edge("mapping", path="tests/test_x.py", symbol="test_run", line=9),
                _edge("backlink", path="tests/test_x.py", symbol="test_run", line=12),
            ),
        ),
        profile=PROFILE,
        snapshot=SNAPSHOT,
        section_required_roles=("implementation", "test"),
    )

    obligation = inventory.get("docs/specs/01-x.md#X-1")
    assert obligation is not None
    assert obligation.alignment_state == "complete"
    assert obligation.evidence_counts.to_row() == {
        "implementation": 1,
        "test": 1,
        "binding_test": 0,
    }


def test_resolved_evidence_atom_classifies_test_roots_once() -> None:
    atom = resolve_evidence_atom(
        path="tests/test_x.py",
        symbol="test_run",
        relation_kinds=("code_backlink", "spec_mapping", "spec_mapping"),
        reciprocity_state="complete",
        test_roots=PROFILE.test_roots,
    )

    assert atom.to_row() == {
        "source_role": "test",
        "model_role": "test",
        "source_identity": (
            "source:sha256:"
            "417ebb2216ed48e7bb8f8d275d27ec1abf69cc1fd80cb47ce39473b99d8f928c"
        ),
        "relation_kinds": ["spec_mapping", "code_backlink"],
        "reciprocity_state": "complete",
        "eligibility": "test",
        "reason": None,
    }


def test_test_only_mapping_warning_uses_resolved_targets_only() -> None:
    test_edge = _edge(
        "mapping",
        path="tests/test_x.py",
        symbol="test_run",
        line=9,
    )
    test_mapping = _mapping(
        path="tests/test_x.py",
        symbol="test_run",
        line=9,
    )
    unresolved_production = _mapping(path="pkg/missing.py", line=10)

    [issue] = mapping_test_only_issues(
        _report(
            sections=(_section(),),
            mappings=(test_mapping, unresolved_production),
            edges=(test_edge,),
        ),
        profile=PROFILE,
        section_meta=frozenset(),
        meta_spec_globs=(),
    )

    assert issue.code == "SPEC_MAPPING_TEST_ONLY"
    assert issue.short_code == "BSC009"
    assert issue.severity == "warning"
    assert issue.path == "docs/specs/01-x.md"
    assert issue.line == 9
    assert issue.section_id == "X-1"


def test_production_mapping_clears_test_only_mapping_warning() -> None:
    issues = mapping_test_only_issues(
        _report(
            sections=(_section(),),
            mappings=(
                _mapping(),
                _mapping(path="tests/test_x.py", symbol="test_run", line=9),
            ),
            edges=(
                _edge("mapping"),
                _edge(
                    "mapping",
                    path="tests/test_x.py",
                    symbol="test_run",
                    line=9,
                ),
            ),
        ),
        profile=PROFILE,
        section_meta=frozenset(),
        meta_spec_globs=(),
    )

    assert issues == ()


@pytest.mark.parametrize(
    ("path", "section_meta"),
    [
        ("docs/specs/planned-x.md", frozenset()),
        ("docs/specs/exploratory-x.md", frozenset()),
        ("docs/specs/meta-x.md", frozenset()),
        ("docs/specs/01-x.md", frozenset({("docs/specs/01-x.md", "X-1")})),
    ],
)
def test_non_active_mapping_does_not_fire_test_only_warning(
    path: str,
    section_meta: frozenset[tuple[str, str]],
) -> None:
    issues = mapping_test_only_issues(
        _report(
            sections=(_section(path=path),),
            mappings=(_mapping(spec_path=path, path="tests/test_x.py"),),
            edges=(_edge("mapping", spec_path=path, path="tests/test_x.py"),),
        ),
        profile=PROFILE,
        section_meta=section_meta,
        meta_spec_globs=PROFILE.meta_spec_globs,
    )

    assert issues == ()


@pytest.mark.parametrize(
    ("path", "rung"),
    [
        ("docs/specs/planned-x.md", "planned"),
        ("docs/specs/exploratory-x.md", "exploratory"),
        ("docs/specs/meta-x.md", "meta"),
    ],
)
def test_non_active_section_rungs_are_not_executable_without_alignment_debt(
    path: str, rung: str
) -> None:
    inventory = build_obligation_inventory(
        _report(sections=(_section(path=path),)),
        profile=PROFILE,
        snapshot=SNAPSHOT,
    )

    obligation = inventory.get(f"{path}#X-1")
    assert obligation is not None
    assert obligation.obligation_rung == rung
    assert obligation.gate_state == "not_executable"
    assert [reason.code for reason in obligation.blocking_reasons] == [
        "IMPLEMENTATION_UNTRACED",
        "OUT_OF_GATE_SCOPE",
    ]


def test_duplicate_section_is_unaddressable_not_a_synthetic_obligation() -> None:
    sections = (
        _section(path="docs/specs/a.md"),
        _section(path="docs/specs/b.md", line=5),
    )
    issue = Issue(
        "SPEC_SECTION_DUPLICATE",
        "warning",
        "docs/specs/a.md",
        3,
        "section ID [X-1] is defined more than once",
        section_id="X-1",
    )
    inventory = build_obligation_inventory(
        _report(sections=sections, issues=(issue,)),
        profile=PROFILE,
        snapshot=SNAPSHOT,
    )

    assert inventory.obligations == ()
    result = inventory.list_result()
    assert result["bootstrap_state"] == "intent_found"
    entries = result["entries"]
    assert isinstance(entries, list)
    assert len(entries) == 1
    assert entries[0]["entry_type"] == "unaddressable_intent"
    assert entries[0]["diagnostic"]["code"] == "SPEC_SECTION_DUPLICATE"
    assert entries[0]["entry_identity"].startswith("unaddressable:sha256:")


def test_invalid_heading_issue_becomes_unaddressable_with_exact_source_excerpt() -> (
    None
):
    issue = Issue(
        "SPEC_SECTION_HEADING_INVALID",
        "error",
        "docs/specs/broken.md",
        7,
        "ID-bearing Markdown heading has an invalid or missing section ID",
    )
    inventory = build_obligation_inventory(
        _report(issues=(issue,)),
        profile=PROFILE,
        snapshot=SNAPSHOT,
        unaddressable_excerpts={
            ("SPEC_SECTION_HEADING_INVALID", "docs/specs/broken.md", 7, 0): (
                "## Broken contract [not-an-id]"
            )
        },
    )

    assert inventory.obligations == ()
    assert inventory.list_result()["entries"] == [
        {
            "entry_type": "unaddressable_intent",
            "entry_identity": inventory.unaddressable_intent[0].entry_identity,
            "diagnostic": {
                "code": "SPEC_SECTION_HEADING_INVALID",
                "path": "docs/specs/broken.md",
                "line": 7,
                "message": (
                    "ID-bearing Markdown heading has an invalid or missing section ID"
                ),
            },
            "excerpt": "## Broken contract [not-an-id]",
            "action": "FIX_OBLIGATION_IDENTITY",
        }
    ]


def test_unaddressable_identity_uses_ascii_canonical_json_for_unicode_path() -> None:
    issue = Issue(
        "SPEC_SECTION_HEADING_INVALID",
        "error",
        "docs/specs/caf\u00e9.md",
        2,
        "invalid heading",
    )
    inventory = build_obligation_inventory(
        _report(issues=(issue,)), profile=PROFILE, snapshot=SNAPSHOT
    )
    preimage = json.dumps(
        {
            "code": issue.code,
            "path": issue.path,
            "line": issue.line,
            "ordinal": 0,
        },
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert inventory.unaddressable_intent[0].entry_identity == (
        "unaddressable:sha256:" + hashlib.sha256(preimage).hexdigest()
    )


def test_code_invariant_uses_owner_target_and_binding_test() -> None:
    declaration = InvariantDeclaration(
        "INV.X.1", "Always one", "required", "code", "pkg/x.py", 2, "run", None
    )
    bind = InvariantBind("INV.X.1", "tests/test_x.py", "test_run", 4, 3, 5)
    inventory = build_obligation_inventory(
        _report(invariants=(declaration,), binds=(bind,)),
        profile=PROFILE,
        snapshot=SNAPSHOT,
        atomic_code_invariant_ids=frozenset({"INV.X.1"}),
    )

    obligation = inventory.get("invariant::INV.X.1")
    assert obligation is not None
    assert obligation.kind == "invariant"
    assert obligation.required_roles == ("implementation", "binding_test")
    assert obligation.alignment_state == "complete"
    assert obligation.gate_state == "executable"
    assert obligation.evidence_counts.to_row() == {
        "implementation": 1,
        "test": 0,
        "binding_test": 1,
    }


def test_spec_invariant_needs_a_resolved_section_target_and_binding_test() -> None:
    section = _section("S-1")
    declaration = InvariantDeclaration(
        "INV.X.2",
        "Always two",
        "required",
        "spec",
        section.path,
        6,
        None,
        section.section_id,
    )
    bind = InvariantBind("INV.X.2", "tests/test_x.py", "test_two", 4, 3, 5)
    inventory = build_obligation_inventory(
        _report(sections=(section,), invariants=(declaration,), binds=(bind,)),
        profile=PROFILE,
        snapshot=SNAPSHOT,
    )

    obligation = inventory.get("invariant::INV.X.2")
    assert obligation is not None
    assert obligation.alignment_state == "partial"
    assert [reason.to_row() for reason in obligation.blocking_reasons] == [
        {
            "code": "INVARIANT_TARGET_MISSING",
            "role": "implementation",
            "relation_kind": "invariant_bind",
            "issue_identity": None,
        }
    ]
    assert obligation.next_actions == (
        "ADD_INVARIANT_BIND",
        "RUN_DETERMINISTIC_CHECK",
    )

    resolved = build_obligation_inventory(
        _report(
            sections=(section,),
            mappings=(_mapping("S-1"),),
            edges=(_edge("mapping", "S-1", line=8),),
            invariants=(declaration,),
            binds=(bind,),
        ),
        profile=PROFILE,
        snapshot=SNAPSHOT,
        atomic_invariant_targets=frozenset({("pkg/x.py", "run")}),
    ).get("invariant::INV.X.2")
    assert resolved is not None
    assert resolved.alignment_state == "complete"

    broken_mapping = _mapping("S-1", path="pkg/missing.py")
    mixed = build_obligation_inventory(
        _report(
            sections=(section,),
            mappings=(_mapping("S-1"), broken_mapping),
            edges=(_edge("mapping", "S-1", line=8),),
            invariants=(declaration,),
            binds=(bind,),
        ),
        profile=PROFILE,
        snapshot=SNAPSHOT,
        atomic_invariant_targets=frozenset({("pkg/x.py", "run")}),
    ).get("invariant::INV.X.2")
    assert mixed is not None
    assert mixed.alignment_state == "partial"
    assert mixed.gate_state == "not_executable"
    assert mixed.evidence_counts.implementation == 2
    assert [reason.code for reason in mixed.blocking_reasons] == [
        "INVARIANT_TARGET_MISSING"
    ]


def test_test_mapping_neither_satisfies_nor_poisons_spec_invariant_target() -> None:
    section = _section("S-1")
    declaration = InvariantDeclaration(
        "INV.X.TEST.1",
        "Always stable",
        "required",
        "spec",
        section.path,
        6,
        None,
        section.section_id,
    )
    production_mapping = _mapping("S-1")
    test_mapping = _mapping(
        "S-1",
        path="tests/test_x.py",
        symbol="test_run",
        line=9,
    )
    bind = InvariantBind(
        "INV.X.TEST.1",
        "tests/test_x.py",
        "test_run",
        4,
        3,
        5,
    )

    obligation = build_obligation_inventory(
        _report(
            sections=(section,),
            mappings=(production_mapping, test_mapping),
            edges=(
                _edge("mapping", "S-1", line=8),
                _edge(
                    "mapping",
                    "S-1",
                    path="tests/test_x.py",
                    symbol="test_run",
                    line=9,
                ),
            ),
            invariants=(declaration,),
            binds=(bind,),
        ),
        profile=PROFILE,
        snapshot=SNAPSHOT,
        atomic_invariant_targets=frozenset({("pkg/x.py", "run")}),
    ).get("invariant::INV.X.TEST.1")

    assert obligation is not None
    assert obligation.alignment_state == "complete"
    assert obligation.gate_state == "executable"
    assert obligation.evidence_counts.to_row() == {
        "implementation": 1,
        "test": 0,
        "binding_test": 1,
    }


def test_spec_invariant_with_no_target_or_binding_test_is_untraced() -> None:
    section = _section("S-1")
    declaration = InvariantDeclaration(
        "INV.X.4",
        "Always four",
        "required",
        "spec",
        section.path,
        6,
        None,
        section.section_id,
    )
    obligation = build_obligation_inventory(
        _report(sections=(section,), invariants=(declaration,)),
        profile=PROFILE,
        snapshot=SNAPSHOT,
    ).get("invariant::INV.X.4")

    assert obligation is not None
    assert obligation.alignment_state == "untraced"
    assert [reason.code for reason in obligation.blocking_reasons] == [
        "INVARIANT_TARGET_MISSING",
        "BINDING_TEST_MISSING",
    ]
    assert obligation.next_actions == (
        "ADD_INVARIANT_BIND",
        "ADD_BINDING_TEST",
        "RUN_DETERMINISTIC_CHECK",
    )


def test_valid_skip_hook_preserves_alignment_and_code_only_is_unskippable() -> None:
    section_id = "docs/specs/01-x.md#X-1"
    report = _report(
        sections=(_section(),),
        mappings=(_mapping(),),
        edges=(_edge("mapping"), _edge("backlink")),
    )
    obligation = build_obligation_inventory(
        report,
        profile=PROFILE,
        snapshot=SNAPSHOT,
        skipped_obligation_ids=frozenset({section_id}),
    ).get(section_id)
    assert obligation is not None
    assert obligation.alignment_state == "complete"
    assert obligation.disposition == "skipped"
    assert obligation.gate_state == "not_executable"
    assert [reason.code for reason in obligation.blocking_reasons] == ["SKIPPED"]
    assert obligation.next_actions == (
        "REVIEW_SKIP_REASON",
        "RUN_DETERMINISTIC_CHECK",
    )

    code_declaration = InvariantDeclaration(
        "INV.X.3", "Always three", "required", "code", "pkg/x.py", 2, "run", None
    )
    with pytest.raises(ValueError, match="code-only invariant"):
        build_obligation_inventory(
            _report(invariants=(code_declaration,)),
            profile=PROFILE,
            snapshot=SNAPSHOT,
            skipped_obligation_ids=frozenset({"invariant::INV.X.3"}),
        )


def test_candidate_counts_are_injected_without_rescanning() -> None:
    obligation_id = "docs/specs/01-x.md#X-1"
    obligation = build_obligation_inventory(
        _report(sections=(_section(),)),
        profile=PROFILE,
        snapshot=SNAPSHOT,
        candidate_counts={obligation_id: CandidateCounts(untraced=2)},
    ).get(obligation_id)

    assert obligation is not None
    assert obligation.gate_state == "not_executable"
    assert obligation.candidate_counts.to_row() == {
        "declared": 0,
        "partially_declared": 0,
        "untraced": 2,
        "conflicted": 0,
    }
    assert [reason.code for reason in obligation.blocking_reasons] == [
        "IMPLEMENTATION_UNTRACED"
    ]


@pytest.mark.parametrize(
    "roles",
    [(), ("test",), ("implementation", "implementation"), ("test", "implementation")],
)
def test_required_section_roles_are_closed_and_ordered(roles: tuple[str, ...]) -> None:
    with pytest.raises(ValueError, match="section_required_roles"):
        build_obligation_inventory(
            _report(),
            profile=PROFILE,
            snapshot=SNAPSHOT,
            section_required_roles=roles,  # type: ignore[arg-type]
        )
