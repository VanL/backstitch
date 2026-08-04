"""Snapshot-only deterministic evidence discovery contract tests.

Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-4.1], [EVC-4.2],
[EVC-7], [EVC-7.1], [EVC-7.2]
Plan: docs/plans/2026-07-15-agent-guided-evidence-cases-plan.md Slice 3
"""

from __future__ import annotations

import builtins
import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

import backstitch.evidence_discovery as evidence_discovery
from backstitch.config import ProfileConfig
from backstitch.evidence_discovery import (
    EvidenceDiscoveryError,
    candidate_order,
    candidates_for_source,
    discover_evidence_candidates,
    get_candidate_by_id,
    get_candidate_neighbors,
    get_candidate_source,
    prepare_evidence_catalog,
    resolved_python_module_names,
)
from backstitch.models import (
    CodeRef,
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
    EvidenceCounts,
    ObligationRecord,
)
from backstitch.operation_progress import (
    OperationDeadlineExceeded,
    OperationProgress,
    ProgressEvent,
)
from backstitch.repository_snapshot import (
    SnapshotAlgorithms,
    SnapshotSemanticConfig,
    capture_repository_snapshot,
)
from backstitch.settings import ObligationSettings

PROFILE = ProfileConfig(
    name="test-v1",
    spec_roots=("docs/specs",),
    plan_roots=("docs/plans",),
    code_roots=("src", "tests"),
    test_roots=("tests",),
    planned_spec_globs=(),
    exploratory_spec_globs=(),
)
SETTINGS = ObligationSettings(
    maximum_candidate_items=1_000,
    maximum_catalog_items=10_000,
    maximum_lexical_seeds=1_000,
    maximum_snapshot_files=1_000,
    maximum_file_bytes=100_000,
    maximum_snapshot_bytes=1_000_000,
    maximum_work_units=1_000_000,
    static_neighbor_depth=2,
)
ALGORITHMS = SnapshotAlgorithms(1, 1, 2, 3, 1)


def _snapshot_config() -> SnapshotSemanticConfig:
    return SnapshotSemanticConfig(
        profile_name=PROFILE.name,
        spec_roots=PROFILE.spec_roots,
        plan_roots=PROFILE.plan_roots,
        code_roots=PROFILE.code_roots,
        test_roots=PROFILE.test_roots,
        exclusions=(),
        planned_spec_globs=(),
        exploratory_spec_globs=(),
        section_required_roles=("implementation",),
        maximum_candidate_items=1_000,
        maximum_catalog_items=10_000,
        maximum_lexical_seeds=1_000,
        maximum_snapshot_files=1_000,
        maximum_file_bytes=100_000,
        maximum_snapshot_bytes=1_000_000,
        maximum_work_units=1_000_000,
        maximum_packet_bytes=100_000,
        maximum_packet_report_bytes=100_000,
        static_neighbor_depth=2,
    )


def _obligation(
    *,
    obligation_id: str = "docs/specs/example.md#REQ-1",
    kind: str = "section",
    path: str = "docs/specs/example.md",
    start_line: int = 2,
    end_line: int = 3,
    title: str = "Worker parser",
) -> ObligationRecord:
    return ObligationRecord(
        obligation_id=obligation_id,
        kind=kind,  # type: ignore[arg-type]
        path=path,
        start_line=start_line,
        end_line=end_line,
        title=title,
        intent_state="identified",
        alignment_state="untraced",
        disposition="evaluate",
        obligation_rung="active",
        gate_state="not_executable",
        required_roles=("implementation",),
        evidence_counts=EvidenceCounts(),
        candidate_counts=CandidateCounts(),
        blocking_reasons=(),
        next_actions=(),
    )


def _section_report(*, issues: tuple[Issue, ...] = ()) -> Report:
    section = SpecSection(
        "docs/specs/example.md", "REQ-1", "Worker parser", 2, None, "heading"
    )
    mapping = SpecMapping(
        section.path,
        section.section_id,
        3,
        "src/worker.py::run",
        "path_symbol",
        "src/worker.py",
        "run",
    )
    backlink = CodeRef(
        "src/worker.py",
        "run",
        8,
        "Spec: docs/specs/example.md [REQ-1]",
        section.path,
        (section.section_id,),
        None,
        (),
        "asserted",
    )
    return Report(
        PROFILE.name,
        "/ignored/absolute/root",
        (section,),
        (backlink,),
        (mapping,),
        (
            Edge(
                "mapping",
                section.path,
                section.section_id,
                "src/worker.py",
                "run",
                3,
            ),
            Edge(
                "backlink",
                section.path,
                section.section_id,
                "src/worker.py",
                "run",
                8,
            ),
        ),
        issues,
    )


def _write_repository(root: Path, *, run_value: str = "payload") -> None:
    (root / "docs/specs").mkdir(parents=True, exist_ok=True)
    (root / "docs/plans").mkdir(parents=True, exist_ok=True)
    (root / "src").mkdir(exist_ok=True)
    (root / "tests").mkdir(exist_ok=True)
    (root / "docs/specs/example.md").write_text(
        "# Example\n## [REQ-1] Worker parser\nThe worker parser validates payload.\n",
        encoding="utf-8",
    )
    (root / "src/__init__.py").write_text("", encoding="utf-8")
    (root / "src/worker.py").write_text(
        "def helper():\n"
        "    return True\n\n"
        "def run():\n"
        '    """Spec: docs/specs/example.md [REQ-1]"""\n'
        f"    {run_value} = helper()\n"
        f"    return {run_value}\n\n"
        "def ambiguous():\n"
        "    return helper()\n\n"
        "def ambiguous():\n"
        "    return helper()\n\n"
        "def ambiguous_caller():\n"
        "    return ambiguous()\n\n"
        "def marker(function):\n"
        "    return function\n\n"
        "@marker\n"
        "async def async_job():\n"
        "    return helper()\n",
        encoding="utf-8",
    )
    (root / "src/worker_consumer.py").write_text(
        "from src.worker import helper as imported_helper\n"
        "import importlib\n\n"
        "def alias_caller():\n"
        "    return imported_helper()\n\n"
        "def shadowed(imported_helper):\n"
        "    return imported_helper()\n\n"
        "def dynamic_import():\n"
        "    return importlib.import_module('src.worker')\n\n"
        "def runtime_dispatch(worker):\n"
        "    return worker.helper()\n\n"
        "def computed(worker):\n"
        "    return getattr(worker, 'helper')()\n\n"
        "from src.worker import *  # noqa: F403\n\n"
        "def wildcard_call():\n"
        "    return helper()  # noqa: F405\n\n"
        "import src.worker\n"
        "src.worker.helper = imported_helper\n\n"
        "def qualified_call():\n"
        "    return src.worker.helper()\n\n"
        "def assigned_shadow():\n"
        "    imported_helper = lambda: False\n"
        "    return imported_helper()\n\n"
        "def deleted_shadow():\n"
        "    del imported_helper\n"
        "    return imported_helper()\n\n"
        "def loop_shadow():\n"
        "    for imported_helper in ():\n"
        "        pass\n"
        "    return imported_helper()\n\n"
        "def defined_shadow():\n"
        "    def imported_helper():\n"
        "        return False\n"
        "    return imported_helper()\n",
        encoding="utf-8",
    )
    (root / "src/worker_relative.py").write_text(
        "from .worker import helper as relative_helper\n\n"
        "def relative_caller():\n"
        "    return relative_helper()\n",
        encoding="utf-8",
    )
    (root / "tests/test_worker.py").write_text(
        "from src.worker import run\n\n"
        "def test_worker_parser():\n"
        "    assert run() == 'payload'\n",
        encoding="utf-8",
    )


def _capture(root: Path):  # type: ignore[no-untyped-def]
    return capture_repository_snapshot(root, _snapshot_config(), ALGORITHMS)


def test_production_uses_discovery_algorithm_version_2() -> None:
    from backstitch.obligation_runtime import ALGORITHMS as production_algorithms

    assert production_algorithms.discovery_algorithm_version == 2


@pytest.mark.parametrize(
    "deadline_phase",
    ("catalog", "relations", "closure", "candidate_detail"),
)
def test_discovery_deadline_table_cancels_in_each_real_phase(
    tmp_path: Path,
    deadline_phase: str,
) -> None:
    _write_repository(tmp_path)
    snapshot = _capture(tmp_path)
    now = [0.0]

    def expire_in_phase(event: ProgressEvent) -> None:
        if event.phase == deadline_phase:
            now[0] = 1.001

    progress = OperationProgress.start(
        1.0,
        clock=lambda: now[0],
        sink=expire_in_phase,
    )
    progress.advance("snapshot", current_identity=snapshot.snapshot_hash)

    with pytest.raises(OperationDeadlineExceeded) as raised:
        discover_evidence_candidates(
            snapshot,
            _section_report(),
            PROFILE,
            _obligation(),
            SETTINGS,
            progress=progress,
        )

    assert raised.value.phase == deadline_phase


def test_relations_deadline_cancels_inside_reference_batch(tmp_path: Path) -> None:
    _write_repository(tmp_path)
    snapshot = _capture(tmp_path)
    in_relations = [False]
    relations_checks = [0]

    def record_phase(event: ProgressEvent) -> None:
        if event.phase == "relations":
            in_relations[0] = True

    def clock() -> float:
        if not in_relations[0]:
            return 0.0
        relations_checks[0] += 1
        return 1.001 if relations_checks[0] >= 12 else 0.0

    progress = OperationProgress.start(1.0, clock=clock, sink=record_phase)
    progress.advance("snapshot", current_identity=snapshot.snapshot_hash)

    with pytest.raises(OperationDeadlineExceeded) as raised:
        discover_evidence_candidates(
            snapshot,
            _section_report(),
            PROFILE,
            _obligation(),
            SETTINGS,
            progress=progress,
        )

    assert raised.value.phase == "relations"
    assert relations_checks[0] == 12


def test_discovery_emits_one_ordered_progress_sequence(tmp_path: Path) -> None:
    _write_repository(tmp_path)
    snapshot = _capture(tmp_path)
    events: list[ProgressEvent] = []
    progress = OperationProgress.start(
        1.0,
        clock=lambda: 0.0,
        sink=events.append,
    )
    progress.advance("snapshot", current_identity=snapshot.snapshot_hash)

    discover_evidence_candidates(
        snapshot,
        _section_report(),
        PROFILE,
        _obligation(),
        SETTINGS,
        progress=progress,
    )

    collapsed = tuple(dict.fromkeys(event.phase for event in events))
    assert collapsed == (
        "snapshot",
        "catalog",
        "relations",
        "closure",
        "candidate_detail",
    )


def test_discovery_builds_all_kinds_bases_states_and_exact_helpers(
    tmp_path: Path,
) -> None:
    _write_repository(tmp_path)
    snapshot = _capture(tmp_path)
    issue = Issue(
        "SPEC_MAPPING_RECIPROCAL_MISSING",
        "warning",
        "docs/specs/example.md",
        2,
        "ambiguous section target",
        section_id="REQ-1",
    )
    report = _section_report(issues=(issue,))
    section = report.spec_sections[0]
    unresolved_owners = (
        "ambiguous_caller",
        "assigned_shadow",
        "computed",
        "deleted_shadow",
        "dynamic_import",
        "loop_shadow",
        "runtime_dispatch",
        "shadowed",
        "wildcard_call",
    )
    report = replace(
        report,
        spec_mappings=(
            *report.spec_mappings,
            *(
                SpecMapping(
                    section.path,
                    section.section_id,
                    4 + index,
                    (
                        f"src/worker.py::{owner}"
                        if owner == "ambiguous_caller"
                        else f"src/worker_consumer.py::{owner}"
                    ),
                    "path_symbol",
                    (
                        "src/worker.py"
                        if owner == "ambiguous_caller"
                        else "src/worker_consumer.py"
                    ),
                    owner,
                )
                for index, owner in enumerate(unresolved_owners)
            ),
        ),
    )

    candidates = discover_evidence_candidates(
        snapshot,
        report,
        PROFILE,
        _obligation(),
        SETTINGS,
    )

    assert tuple(candidate_order(item) for item in candidates) == tuple(
        sorted(candidate_order(item) for item in candidates)
    )
    assert {item.candidate_kind for item in candidates} == {
        "implementation_definition",
        "test_definition",
        "static_reference",
        "unresolved_reference",
        "report_issue",
    }
    assert {basis for item in candidates for basis in item.discovery_bases} == {
        "declared_relation",
        "resolver_issue",
        "lexical_match",
        "static_neighbor",
        "ambiguous_relation",
    }
    assert all(
        not item.structural_locator.startswith("python-module:")
        for item in candidates
        if "lexical_match" in item.discovery_bases
    )
    assert {item.trace_state for item in candidates} >= {
        "declared",
        "untraced",
        "partially_declared",
    }
    assert {
        relation.relation_kind
        for item in candidates
        for relation in (*item.static_relations, *item.declared_relations)
    } <= {
        "spec_mapping",
        "code_backlink",
        "invariant_declaration",
        "invariant_bind",
        "binding_test",
        "static_import",
        "static_call",
        "static_reference",
        "enclosing_definition",
        "issue_target",
    }

    run = next(
        item
        for item in candidates
        if item.structural_locator == "python-definition:run:function:0"
    )
    assert run.trace_state == "declared"
    expected_preimage = {
        "candidate_identity_version": 1,
        "candidate_kind": "implementation_definition",
        "path": "src/worker.py",
        "structural_locator": "python-definition:run:function:0",
    }
    expected_id = (
        "candidate:sha256:"
        + hashlib.sha256(
            json.dumps(
                expected_preimage,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()
    )
    assert run.candidate_id == expected_id
    assert run.receipt.to_row() == {
        "receipt_version": 1,
        "path": "src/worker.py",
        "structural_locator": "python-definition:run:function:0",
        "start_line": 4,
        "end_line": 7,
        "raw_sha256": run.receipt.raw_sha256,
    }
    assert get_candidate_by_id(candidates, run.candidate_id) is run
    assert run in candidates_for_source(candidates, "src/worker.py")
    source = get_candidate_source(run)
    assert source.text.startswith("def run():\n")
    assert source.text.endswith("    return payload\n")
    assert source.text_sha256 == run.receipt.raw_sha256
    neighbors = get_candidate_neighbors(run, candidates)
    assert neighbors == tuple(
        sorted(
            neighbors,
            key=lambda item: (
                item.relation_kind,
                item.direction,
                item.candidate_id,
            ),
        )
    )

    alias_callers = [
        item
        for item in candidates
        if item.owner == "alias_caller" and item.candidate_kind == "static_reference"
    ]
    shadowed = [
        item
        for item in candidates
        if item.owner == "shadowed" and item.candidate_kind == "unresolved_reference"
    ]
    dynamic = [
        item
        for item in candidates
        if item.owner == "dynamic_import"
        and item.candidate_kind == "unresolved_reference"
    ]
    assert alias_callers, [
        (item.owner, item.candidate_kind, item.structural_locator)
        for item in candidates
        if item.path == "src/worker_consumer.py"
    ]
    assert shadowed
    assert dynamic
    assert {
        item.owner
        for item in candidates
        if item.candidate_kind == "unresolved_reference"
    } >= {
        "runtime_dispatch",
        "computed",
        "wildcard_call",
        "assigned_shadow",
        "deleted_shadow",
        "loop_shadow",
    }
    assert {
        item.owner for item in candidates if item.candidate_kind == "static_reference"
    } >= {"qualified_call", "defined_shadow", "relative_caller"}
    duplicate_calls = [
        item
        for item in candidates
        if item.owner == "ambiguous"
        and item.candidate_kind == "static_reference"
        and ":call:" in item.structural_locator
    ]
    assert len(duplicate_calls) == 2
    assert len({item.structural_locator for item in duplicate_calls}) == 2
    async_job = next(
        item
        for item in candidates
        if item.structural_locator == "python-definition:async_job:async-function:0"
    )
    assert async_job.start_line == 21

    limited = discover_evidence_candidates(
        snapshot,
        _section_report(issues=(issue,)),
        PROFILE,
        _obligation(),
        replace(SETTINGS, maximum_lexical_seeds=1, static_neighbor_depth=0),
    )
    lexical_rows = [item for item in limited if "lexical_match" in item.discovery_bases]
    assert len(lexical_rows) == 1
    assert lexical_rows[0].candidate_kind in {
        "implementation_definition",
        "test_definition",
    }
    expected_lexical_id = min(
        (
            item
            for item in candidates
            if item.lexical_score[0] > 0
            and item.candidate_kind in {"implementation_definition", "test_definition"}
        ),
        key=lambda item: (
            -item.lexical_score[0],
            -item.lexical_score[1],
            item.candidate_id,
        ),
    ).candidate_id
    assert lexical_rows[0].candidate_id == expected_lexical_id

    conflicted = discover_evidence_candidates(
        snapshot,
        _section_report(
            issues=(
                Issue(
                    "TARGET_PATH_AMBIGUOUS",
                    "error",
                    "docs/specs/example.md",
                    2,
                    "ambiguous section target",
                    section_id="REQ-1",
                ),
            )
        ),
        PROFILE,
        _obligation(),
        SETTINGS,
    )
    assert any(item.trace_state == "conflicted" for item in conflicted)


def test_invariant_target_and_binding_test_project_reciprocal_relations(
    tmp_path: Path,
) -> None:
    _write_repository(tmp_path)
    (tmp_path / "docs/specs/example.md").write_text(
        "# Example\n- [INV.WORKER.1] Worker parser always validates payload.\n",
        encoding="utf-8",
    )
    snapshot = _capture(tmp_path)
    declaration = InvariantDeclaration(
        "INV.WORKER.1",
        "Worker parser always validates payload.",
        "required",
        "code",
        "src/worker.py",
        4,
        "run",
        None,
    )
    bind = InvariantBind(
        "INV.WORKER.1",
        "tests/test_worker.py",
        "test_worker_parser",
        3,
        3,
        4,
    )
    report = replace(_section_report(), invariants=(declaration,), binds=(bind,))
    obligation = _obligation(
        obligation_id="invariant::INV.WORKER.1",
        kind="invariant",
        start_line=2,
        end_line=2,
        title="Worker parser always validates payload",
    )

    candidates = discover_evidence_candidates(
        snapshot, report, PROFILE, obligation, SETTINGS
    )

    projected = [
        item for item in candidates if "invariant_relation" in item.discovery_bases
    ]
    assert {item.owner for item in projected} == {"run", "test_worker_parser"}
    assert all(item.trace_state == "declared" for item in projected)
    assert {
        relation.relation_kind
        for item in projected
        for relation in item.declared_relations
    } == {"invariant_declaration", "binding_test"}
    assert all(
        advice.guidance_code != "ADD_INVARIANT_BIND"
        for item in candidates
        for advice in item.suggested_trace_edits
    )

    missing_bind = discover_evidence_candidates(
        snapshot,
        replace(report, binds=()),
        PROFILE,
        obligation,
        SETTINGS,
    )
    partial_target = next(
        item
        for item in missing_bind
        if item.structural_locator == "python-definition:run:function:0"
    )
    assert partial_target.trace_state == "partially_declared"
    assert [item.guidance_code for item in partial_target.suggested_trace_edits] == [
        "ADD_BINDING_TEST"
    ]

    spec_declaration = replace(
        declaration,
        declaration_kind="spec",
        path="docs/specs/example.md",
        owner_symbol=None,
        section_id="REQ-1",
    )
    missing_target = discover_evidence_candidates(
        snapshot,
        replace(report, invariants=(spec_declaration,), edges=()),
        PROFILE,
        obligation,
        SETTINGS,
    )
    partial_binding = next(
        item
        for item in missing_target
        if item.structural_locator == "python-definition:test_worker_parser:function:0"
    )
    assert partial_binding.trace_state == "partially_declared"
    assert [item.to_row() for item in partial_binding.suggested_trace_edits] == [
        {
            "guidance_code": "ADD_INVARIANT_BIND",
            "target_id": "docs/specs/example.md#REQ-1",
            "evidence_role": "implementation",
            "supported_forms": ["spec_mapping"],
            "review_warning": (
                "Advice is not evidence; review the source relation before editing."
            ),
        }
    ]


def test_code_declared_module_invariant_projects_module_evidence(
    tmp_path: Path,
) -> None:
    _write_repository(tmp_path)
    (tmp_path / "src/module_inv.py").write_text(
        '"""Invariant: INV.MODULE.1 - Module behavior remains stable."""\nVALUE = 1\n',
        encoding="utf-8",
    )
    snapshot = _capture(tmp_path)
    declaration = InvariantDeclaration(
        "INV.MODULE.1",
        "Module behavior remains stable.",
        "required",
        "code",
        "src/module_inv.py",
        1,
        "<module>",
        None,
    )
    bind = InvariantBind(
        "INV.MODULE.1",
        "tests/test_worker.py",
        "test_worker_parser",
        3,
        3,
        4,
    )
    obligation = _obligation(
        obligation_id="invariant::INV.MODULE.1",
        kind="invariant",
        path="src/module_inv.py",
        start_line=1,
        end_line=1,
        title="Module behavior remains stable",
    )

    candidates = discover_evidence_candidates(
        snapshot,
        replace(_section_report(), invariants=(declaration,), binds=(bind,)),
        PROFILE,
        obligation,
        SETTINGS,
    )

    module = next(
        item
        for item in candidates
        if item.structural_locator == "python-module:src.module_inv"
    )
    assert module.trace_state == "declared"
    assert "invariant_relation" in module.discovery_bases
    assert {item.relation_kind for item in module.declared_relations} == {
        "invariant_declaration"
    }


def test_discovery_uses_only_captured_bytes_and_ids_ignore_body_and_unrelated_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_repository(tmp_path)
    first = _capture(tmp_path)
    report = _section_report()
    obligation = _obligation()
    first_candidates = discover_evidence_candidates(
        first, report, PROFILE, obligation, SETTINGS
    )
    first_run = next(item for item in first_candidates if item.owner == "run")

    _write_repository(tmp_path, run_value="changed")
    (tmp_path / "src/unrelated.py").write_text(
        "def elsewhere():\n    return 1\n", encoding="utf-8"
    )
    second = _capture(tmp_path)
    second_candidates = discover_evidence_candidates(
        second, report, PROFILE, obligation, SETTINGS
    )
    second_run = next(item for item in second_candidates if item.owner == "run")
    assert {item.candidate_id for item in second_candidates} == {
        item.candidate_id for item in first_candidates
    }
    assert second_run.candidate_id == first_run.candidate_id
    assert second_run.receipt.raw_sha256 != first_run.receipt.raw_sha256

    def fail_open(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("discovery reopened repository state")

    monkeypatch.setattr(builtins, "open", fail_open)
    monkeypatch.setattr(Path, "open", fail_open)
    monkeypatch.setattr(os, "open", fail_open)
    assert (
        discover_evidence_candidates(first, report, PROFILE, obligation, SETTINGS)
        == first_candidates
    )


def test_prepared_catalog_parses_once_and_isolates_obligation_derivation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_repository(tmp_path)
    snapshot = _capture(tmp_path)
    parser = Mock(wraps=evidence_discovery.parse_python_source)
    monkeypatch.setattr(evidence_discovery, "parse_python_source", parser)

    catalog = prepare_evidence_catalog(snapshot, PROFILE, SETTINGS)
    first = discover_evidence_candidates(
        snapshot,
        _section_report(),
        PROFILE,
        _obligation(),
        SETTINGS,
        prepared_catalog=catalog,
    )
    discover_evidence_candidates(
        snapshot,
        _section_report(),
        PROFILE,
        _obligation(title="Helper behavior"),
        SETTINGS,
        prepared_catalog=catalog,
    )
    replay = discover_evidence_candidates(
        snapshot,
        _section_report(),
        PROFILE,
        _obligation(),
        SETTINGS,
        prepared_catalog=catalog,
    )

    expected_parse_calls = sum(
        1
        for row in snapshot.files
        if row.path.endswith(".py")
        and row.raw_bytes is not None
        and (row.path.startswith("src/") or row.path.startswith("tests/"))
    )
    assert parser.call_count == expected_parse_calls
    assert replay == first


def test_prepared_catalog_reuses_node_tokens_but_scores_late_issue_nodes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_repository(tmp_path)
    snapshot = _capture(tmp_path)
    tokenizer = Mock(wraps=evidence_discovery._tokens)
    monkeypatch.setattr(evidence_discovery, "_tokens", tokenizer)

    catalog = prepare_evidence_catalog(snapshot, PROFILE, SETTINGS)
    calls_after_prepare = tokenizer.call_count

    discover_evidence_candidates(
        snapshot,
        _section_report(),
        PROFILE,
        _obligation(),
        SETTINGS,
        prepared_catalog=catalog,
    )
    discover_evidence_candidates(
        snapshot,
        _section_report(),
        PROFILE,
        _obligation(title="Helper behavior"),
        SETTINGS,
        prepared_catalog=catalog,
    )
    assert tokenizer.call_count == calls_after_prepare + 6

    issue_candidates = discover_evidence_candidates(
        snapshot,
        _section_report(
            issues=(
                Issue(
                    "SPEC_MAPPING_RECIPROCAL_MISSING",
                    "warning",
                    "docs/specs/example.md",
                    2,
                    "worker parser conflict",
                    section_id="REQ-1",
                ),
            )
        ),
        PROFILE,
        _obligation(),
        SETTINGS,
        prepared_catalog=catalog,
    )

    assert tokenizer.call_count == calls_after_prepare + 12
    assert any(
        item.candidate_kind == "report_issue" and item.lexical_score[0] > 0
        for item in issue_candidates
    )


@pytest.mark.parametrize(
    "relative_path",
    ("src/worker_invalid.py", "docs/specs/invalid.md"),
)
def test_non_utf8_semantic_input_fails_closed(
    tmp_path: Path,
    relative_path: str,
) -> None:
    _write_repository(tmp_path)
    (tmp_path / relative_path).write_bytes(b"\xff\n")

    with pytest.raises(EvidenceDiscoveryError) as caught:
        discover_evidence_candidates(
            _capture(tmp_path),
            _section_report(),
            PROFILE,
            _obligation(),
            SETTINGS,
        )

    assert caught.value.code == "SOURCE_UNREADABLE"
    assert caught.value.details == {"path": relative_path, "error_class": "io"}


@pytest.mark.parametrize(
    "relative_path",
    ("docs/specs/unreadable.md", "docs/plans/unreadable.md"),
)
def test_complete_semantic_catalog_rejects_unreadable_markdown(
    tmp_path: Path,
    relative_path: str,
) -> None:
    _write_repository(tmp_path)
    unreadable = tmp_path / relative_path
    unreadable.write_text("# Captured semantic input\n", encoding="utf-8")
    unreadable.chmod(0)
    try:
        snapshot = _capture(tmp_path)

        with pytest.raises(EvidenceDiscoveryError) as caught:
            discover_evidence_candidates(
                snapshot,
                _section_report(),
                PROFILE,
                _obligation(),
                SETTINGS,
            )
    finally:
        unreadable.chmod(0o600)

    assert caught.value.code == "SOURCE_UNREADABLE"
    assert caught.value.details == {
        "path": relative_path,
        "error_class": "permission",
    }


@pytest.mark.parametrize(
    ("field", "limit", "budget"),
    (
        ("maximum_snapshot_files", 1, "snapshot_files"),
        ("maximum_file_bytes", 1, "file_bytes"),
        ("maximum_snapshot_bytes", 1, "snapshot_bytes"),
        ("maximum_catalog_items", 1, "catalog_items"),
        ("maximum_work_units", 1, "work_units"),
        ("maximum_candidate_items", 1, "candidate_items"),
    ),
)
def test_discovery_budget_overflow_is_one_structured_abort(
    tmp_path: Path,
    field: str,
    limit: int,
    budget: str,
) -> None:
    _write_repository(tmp_path)
    snapshot = _capture(tmp_path)
    constrained = replace(SETTINGS, **{field: limit})  # type: ignore[arg-type]

    with pytest.raises(EvidenceDiscoveryError) as caught:
        discover_evidence_candidates(
            snapshot,
            _section_report(),
            PROFILE,
            _obligation(),
            constrained,
        )

    assert caught.value.code == "BUDGET_EXHAUSTED"
    assert caught.value.details["budget"] == budget
    assert caught.value.details["limit"] == limit


def test_work_budget_charges_the_closed_evc_7_1_units_exactly(
    tmp_path: Path,
) -> None:
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "docs/plans").mkdir(parents=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "docs/specs/example.md").write_text(
        "# Example\n## [REQ-1] Target\nTarget behavior.\n",
        encoding="utf-8",
    )
    (tmp_path / "src/__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "src/simple.py").write_text(
        "def target():\n    pass\n",
        encoding="utf-8",
    )
    snapshot = _capture(tmp_path)

    # Discovery-v2 still charges every raw static-edge inspection, but the
    # mapped module is not closure adjacency and therefore is not inserted.
    with pytest.raises(EvidenceDiscoveryError) as caught:
        discover_evidence_candidates(
            snapshot,
            _section_report(),
            PROFILE,
            _obligation(title="Target"),
            replace(SETTINGS, maximum_work_units=17),
        )
    assert caught.value.details == {
        "budget": "work_units",
        "limit": 17,
        "observed": 18,
    }

    candidates = discover_evidence_candidates(
        snapshot,
        _section_report(),
        PROFILE,
        _obligation(title="Target"),
        replace(SETTINGS, maximum_work_units=18),
    )
    assert [item.owner for item in candidates] == ["target"]


def test_collapsed_bridge_charges_edges_and_unique_insertions_exactly() -> None:
    def closure_nodes() -> dict[str, evidence_discovery._Node]:
        rows: dict[str, evidence_discovery._Node] = {}
        definitions: tuple[tuple[str, evidence_discovery.CandidateKind, str], ...] = (
            (
                "owner",
                "implementation_definition",
                "python-definition:owner:function:0",
            ),
            ("reference", "static_reference", "python-reference:owner:call:0"),
            (
                "target",
                "implementation_definition",
                "python-definition:target:function:0",
            ),
        )
        for candidate_id, candidate_kind, locator in definitions:
            rows[candidate_id] = evidence_discovery._Node(
                candidate_id=candidate_id,
                candidate_kind=candidate_kind,
                path="src/bridge.py",
                owner=candidate_id,
                symbol=candidate_id,
                module_name="src.bridge",
                role="implementation",
                start_line=1,
                end_line=1,
                node_line=1,
                structural_locator=locator,
                receipt=evidence_discovery.SourceReceipt(
                    1,
                    "src/bridge.py",
                    locator,
                    1,
                    1,
                    "0" * 64,
                ),
            )
        rows["owner"].bases.add("declared_relation")
        return rows

    edges = (
        ("enclosing_definition", "owner", "reference"),
        ("static_call", "reference", "target"),
    )
    settings = replace(
        SETTINGS,
        maximum_lexical_seeds=0,
        static_neighbor_depth=1,
    )
    work = evidence_discovery._WorkBudget(5)

    selected = evidence_discovery._closure(
        closure_nodes(),
        edges,
        settings,
        work,
    )

    assert selected == {"owner", "reference", "target"}
    assert work.used == 5  # two edge inspections plus three unique insertions

    with pytest.raises(EvidenceDiscoveryError) as caught:
        evidence_discovery._closure(
            closure_nodes(),
            edges,
            settings,
            evidence_discovery._WorkBudget(4),
        )
    assert caught.value.details == {
        "budget": "work_units",
        "limit": 4,
        "observed": 5,
    }


def test_irrelevant_issues_and_invariant_edges_each_charge_one_work_unit(
    tmp_path: Path,
) -> None:
    _write_repository(tmp_path)
    snapshot = _capture(tmp_path)
    declaration = InvariantDeclaration(
        "INV.WORK.1",
        "Work accounting remains closed.",
        "required",
        "spec",
        "docs/specs/example.md",
        2,
        None,
        "REQ-1",
    )
    obligation = _obligation(
        obligation_id="invariant::INV.WORK.1",
        kind="invariant",
        title="Work accounting",
    )
    base = replace(_section_report(), invariants=(declaration,), binds=())
    irrelevant_issues = tuple(
        Issue(
            "SPEC_SECTION_UNMAPPED",
            "warning",
            "docs/specs/other.md",
            1,
            "irrelevant",
            invariant_id="INV.OTHER",
        )
        for _index in range(5_000)
    )
    irrelevant_edges = tuple(
        Edge(
            "mapping",
            "docs/specs/other.md",
            f"OTHER-{index}",
            "src/other.py",
            "other",
            1,
        )
        for index in range(5_000)
    )
    irrelevant_declarations = tuple(
        InvariantDeclaration(
            f"INV.OTHER.{index}",
            "Irrelevant.",
            "required",
            "code",
            "src/other.py",
            1,
            "other",
            None,
        )
        for index in range(5_000)
    )
    irrelevant_binds = tuple(
        InvariantBind(
            f"INV.OTHER.{index}",
            "tests/test_other.py",
            "test_other",
            1,
            1,
            1,
        )
        for index in range(5_000)
    )
    expanded = replace(
        base,
        issues=irrelevant_issues,
        edges=(*base.edges, *irrelevant_edges),
        invariants=(*base.invariants, *irrelevant_declarations),
        binds=irrelevant_binds,
    )

    def required_work(report: Report) -> int:
        low = 0
        high = SETTINGS.maximum_work_units
        while low + 1 < high:
            middle = (low + high) // 2
            try:
                discover_evidence_candidates(
                    snapshot,
                    report,
                    PROFILE,
                    obligation,
                    replace(SETTINGS, maximum_work_units=middle),
                )
            except EvidenceDiscoveryError as exc:
                assert exc.details["budget"] == "work_units"
                low = middle
            else:
                high = middle
        return high

    base_required = required_work(base)
    expanded_required = required_work(expanded)
    assert expanded_required == base_required + 20_000

    discover_evidence_candidates(
        snapshot,
        expanded,
        PROFILE,
        obligation,
        replace(SETTINGS, maximum_work_units=expanded_required),
    )
    with pytest.raises(EvidenceDiscoveryError) as caught:
        discover_evidence_candidates(
            snapshot,
            expanded,
            PROFILE,
            obligation,
            replace(SETTINGS, maximum_work_units=expanded_required - 1),
        )
    assert caught.value.details == {
        "budget": "work_units",
        "limit": expanded_required - 1,
        "observed": expanded_required,
    }


def test_longest_module_root_wins_without_guessing_import_targets(
    tmp_path: Path,
) -> None:
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "docs/plans").mkdir(parents=True)
    (tmp_path / "src/pkg").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "docs/specs/example.md").write_text(
        "# Example\n## [REQ-1] Worker parser\nWorker parser payload.\n",
        encoding="utf-8",
    )
    (tmp_path / "src/__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "src/pkg/__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "src/pkg/mod.py").write_text(
        "def target():\n    return 1\n", encoding="utf-8"
    )
    profile = replace(PROFILE, code_roots=("src", "src/pkg", "tests"))
    config = replace(
        _snapshot_config(),
        code_roots=profile.code_roots,
    )
    snapshot = capture_repository_snapshot(tmp_path, config, ALGORITHMS)
    assert resolved_python_module_names(
        ("src/pkg/mod.py",),
        profile,
        snapshot,
    ) == {"src/pkg/mod.py": "pkg.mod"}

    candidates = discover_evidence_candidates(
        snapshot,
        _section_report(),
        profile,
        _obligation(),
        SETTINGS,
    )

    mod_rows = [item for item in candidates if item.path == "src/pkg/mod.py"]
    assert all(
        not item.structural_locator.startswith("python-module:") for item in mod_rows
    )
    assert all(item.candidate_kind != "static_reference" for item in mod_rows)


def test_fallback_module_identity_is_seeded_without_changing_named_identity(
    tmp_path: Path,
) -> None:
    _write_repository(tmp_path)
    (tmp_path / "src/bad-name.py").write_text("value = 1\n", encoding="utf-8")
    snapshot = _capture(tmp_path)
    assert resolved_python_module_names(
        ("src/__init__.py", "src/bad-name.py", "src/worker.py"),
        PROFILE,
        snapshot,
    ) == {
        "src/__init__.py": None,
        "src/bad-name.py": None,
        "src/worker.py": "src.worker",
    }
    section = _section_report().spec_sections[0]
    report = replace(
        _section_report(),
        spec_mappings=(
            SpecMapping(
                section.path,
                section.section_id,
                3,
                "src/bad-name.py",
                "path",
                "src/bad-name.py",
                None,
            ),
        ),
        edges=(),
    )

    candidates = discover_evidence_candidates(
        snapshot,
        report,
        PROFILE,
        _obligation(),
        SETTINGS,
    )

    fallback = next(
        item
        for item in candidates
        if item.path == "src/bad-name.py"
        and item.structural_locator.startswith("python-module-path:")
    )
    assert fallback.structural_locator == "python-module-path:src/bad-name.py"
    named_report = replace(
        _section_report(),
        spec_mappings=(
            SpecMapping(
                section.path,
                section.section_id,
                3,
                "src/worker.py",
                "path",
                "src/worker.py",
                None,
            ),
        ),
        code_refs=(),
    )
    named = next(
        item
        for item in discover_evidence_candidates(
            snapshot,
            named_report,
            PROFILE,
            _obligation(),
            SETTINGS,
        )
        if item.path == "src/worker.py"
        and item.structural_locator == "python-module:src.worker"
    )
    assert named.candidate_id == evidence_discovery._candidate_id(
        "implementation_definition",
        "src/worker.py",
        "python-module:src.worker",
    )


def test_final_frontier_relations_do_not_reference_unselected_candidates(
    tmp_path: Path,
) -> None:
    _write_repository(tmp_path)
    candidates = discover_evidence_candidates(
        _capture(tmp_path),
        _section_report(),
        PROFILE,
        _obligation(title="Helper"),
        replace(SETTINGS, maximum_lexical_seeds=1, static_neighbor_depth=1),
        obligation_search_text="Helper",
    )

    returned_ids = {item.candidate_id for item in candidates}
    referenced_ids = {
        candidate_id
        for item in candidates
        for relation in (*item.static_relations, *item.declared_relations)
        for candidate_id in (
            relation.source_candidate_id,
            relation.target_candidate_id,
        )
        if candidate_id is not None
    }
    assert referenced_ids <= returned_ids


@pytest.mark.parametrize(
    ("seed_title", "neighbor_owner"),
    (
        pytest.param("Alpha origin", "beta_target", id="direct"),
        pytest.param("Beta target", "alpha_origin", id="inverse"),
    ),
)
def test_collapsed_definition_bridge_is_symmetric_and_keeps_raw_relations(
    tmp_path: Path,
    seed_title: str,
    neighbor_owner: str,
) -> None:
    _write_repository(tmp_path)
    (tmp_path / "src/bridge.py").write_text(
        "def beta_target():\n"
        "    return True\n\n"
        "def alpha_origin():\n"
        "    return beta_target()\n",
        encoding="utf-8",
    )
    base = _section_report()
    report = replace(base, spec_mappings=(), code_refs=(), edges=())

    candidates = discover_evidence_candidates(
        _capture(tmp_path),
        report,
        PROFILE,
        _obligation(title=seed_title),
        replace(SETTINGS, maximum_lexical_seeds=1, static_neighbor_depth=1),
    )

    definitions = {
        item.owner: item
        for item in candidates
        if item.path == "src/bridge.py"
        and item.candidate_kind == "implementation_definition"
        and not item.structural_locator.startswith("python-module:")
    }
    references = [
        item
        for item in candidates
        if item.path == "src/bridge.py"
        and item.owner == "alpha_origin"
        and item.candidate_kind == "static_reference"
    ]
    assert set(definitions) == {"alpha_origin", "beta_target"}
    assert "static_neighbor" in definitions[neighbor_owner].discovery_bases
    assert len(references) == 2
    assert all("static_neighbor" in item.discovery_bases for item in references)
    assert not any(
        item.path == "src/bridge.py"
        and item.structural_locator.startswith("python-module:")
        for item in candidates
    )

    raw_relations = {
        (
            relation.relation_kind,
            relation.source_candidate_id,
            relation.target_candidate_id,
        )
        for item in candidates
        for relation in item.static_relations
    }
    reference_ids = {item.candidate_id for item in references}
    assert {row for row in raw_relations if row[0] == "enclosing_definition"} == {
        ("enclosing_definition", definitions["alpha_origin"].candidate_id, item)
        for item in reference_ids
    }
    target_rows = {row for row in raw_relations if row[0] != "enclosing_definition"}
    assert len(target_rows) == 2
    assert {row[0] for row in target_rows} == {"static_call", "static_reference"}
    assert {row[1] for row in target_rows} == reference_ids
    assert {row[2] for row in target_rows} == {definitions["beta_target"].candidate_id}
    assert not any(
        source == definitions["alpha_origin"].candidate_id
        and target == definitions["beta_target"].candidate_id
        for _kind, source, target in raw_relations
    )


def test_import_of_ambiguous_local_module_is_plausible_but_never_guessed(
    tmp_path: Path,
) -> None:
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "docs/plans").mkdir(parents=True)
    (tmp_path / "first").mkdir()
    (tmp_path / "second").mkdir()
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "docs/specs/example.md").write_text(
        "# Example\n## [REQ-1] Shared target\nShared target behavior.\n",
        encoding="utf-8",
    )
    for root in ("first", "second"):
        (tmp_path / root / "shared.py").write_text(
            "def target():\n    return True\n",
            encoding="utf-8",
        )
    (tmp_path / "app/consumer.py").write_text(
        "import shared\n\ndef call_target():\n    return shared.target()\n",
        encoding="utf-8",
    )
    profile = replace(
        PROFILE,
        code_roots=("first", "second", "app", "tests"),
    )
    config = replace(_snapshot_config(), code_roots=profile.code_roots)
    snapshot = capture_repository_snapshot(tmp_path, config, ALGORITHMS)
    section = _section_report().spec_sections[0]
    seeded_report = replace(
        _section_report(),
        spec_mappings=(
            SpecMapping(
                section.path,
                section.section_id,
                3,
                "app/consumer.py::call_target",
                "path_symbol",
                "app/consumer.py",
                "call_target",
            ),
        ),
        code_refs=(),
    )

    candidates = discover_evidence_candidates(
        snapshot,
        seeded_report,
        profile,
        _obligation(title="Call shared target"),
        SETTINGS,
    )

    unresolved = [
        item
        for item in candidates
        if item.path == "app/consumer.py"
        and item.candidate_kind == "unresolved_reference"
    ]
    assert unresolved
    assert all(
        relation.target_locator is None
        or not relation.target_locator.startswith("python-module:shared")
        for item in unresolved
        for relation in item.static_relations
    )

    reached = discover_evidence_candidates(
        snapshot,
        seeded_report,
        profile,
        _obligation(title="No lexical seed"),
        replace(SETTINGS, maximum_lexical_seeds=0, static_neighbor_depth=1),
    )
    possible_targets = [
        item
        for item in reached
        if item.owner == "target"
        and item.path in {"first/shared.py", "second/shared.py"}
    ]
    assert len(possible_targets) == 2
    assert all(
        "ambiguous_relation" in item.discovery_bases for item in possible_targets
    )
    ambiguous_call = next(
        item
        for item in reached
        if item.owner == "call_target" and ":call:" in item.structural_locator
    )
    assert ambiguous_call.candidate_kind == "unresolved_reference"
    assert "ambiguous_relation" in ambiguous_call.discovery_bases


def test_path_only_mapping_never_expands_the_module_candidate(tmp_path: Path) -> None:
    _write_repository(tmp_path)
    base = _section_report()
    section = base.spec_sections[0]
    report = replace(
        base,
        spec_mappings=(
            SpecMapping(
                section.path,
                section.section_id,
                3,
                "src/worker.py",
                "path",
                "src/worker.py",
                None,
            ),
        ),
        code_refs=(),
    )

    candidates = discover_evidence_candidates(
        _capture(tmp_path),
        report,
        PROFILE,
        _obligation(title="No lexical seed"),
        replace(SETTINGS, maximum_lexical_seeds=0, static_neighbor_depth=1),
    )

    mapped = [
        item
        for item in candidates
        if any(
            relation.relation_kind == "spec_mapping"
            for relation in item.declared_relations
        )
    ]
    assert [item.structural_locator for item in mapped] == ["python-module:src.worker"]
    assert [item.structural_locator for item in candidates] == [
        "python-module:src.worker"
    ]


def test_comprehension_targets_never_resolve_to_an_outer_import(
    tmp_path: Path,
) -> None:
    _write_repository(tmp_path)
    (tmp_path / "src/targets.py").write_text(
        "def chosen():\n    return 1\n",
        encoding="utf-8",
    )
    (tmp_path / "src/comprehensions.py").write_text(
        "def list_case(items):\n"
        "    from src.targets import chosen\n"
        "    return [chosen() for chosen in items]\n\n"
        "def set_case(items):\n"
        "    from src.targets import chosen\n"
        "    return {chosen() for chosen in items}\n\n"
        "def dict_case(items):\n"
        "    from src.targets import chosen\n"
        "    return {chosen: chosen() for chosen in items}\n\n"
        "def generator_case(items):\n"
        "    from src.targets import chosen\n"
        "    return tuple(chosen() for chosen in items)\n",
        encoding="utf-8",
    )

    report = _section_report()
    section = report.spec_sections[0]
    report = replace(
        report,
        spec_mappings=tuple(
            SpecMapping(
                section.path,
                section.section_id,
                3,
                f"src/comprehensions.py::{owner}",
                "path_symbol",
                "src/comprehensions.py",
                owner,
            )
            for owner in ("list_case", "set_case", "dict_case", "generator_case")
        ),
    )

    candidates = discover_evidence_candidates(
        _capture(tmp_path),
        report,
        PROFILE,
        _obligation(title="Chosen target"),
        SETTINGS,
    )

    calls = [
        item
        for item in candidates
        if item.path == "src/comprehensions.py"
        and item.owner in {"list_case", "set_case", "dict_case", "generator_case"}
        and ":call:" in item.structural_locator
    ]
    assert len(calls) == 4
    assert all(item.candidate_kind == "unresolved_reference" for item in calls)
    assert all(
        relation.relation_kind != "static_call"
        for item in calls
        for relation in item.static_relations
    )


def test_definition_ordinals_are_assigned_after_nfc_normalization(
    tmp_path: Path,
) -> None:
    _write_repository(tmp_path)
    (tmp_path / "src/unicode.py").write_text(
        "def caf\N{LATIN SMALL LETTER E WITH ACUTE}():\n"
        "    return 1\n\n"
        "def cafe\N{COMBINING ACUTE ACCENT}():\n"
        "    return 2\n",
        encoding="utf-8",
    )

    candidates = discover_evidence_candidates(
        _capture(tmp_path),
        _section_report(),
        PROFILE,
        _obligation(title="Unicode definitions"),
        SETTINGS,
    )

    definitions = [
        item
        for item in candidates
        if item.path == "src/unicode.py"
        and item.owner == "caf\N{LATIN SMALL LETTER E WITH ACUTE}"
        and item.structural_locator.startswith("python-definition:")
    ]
    assert [item.structural_locator for item in definitions] == [
        "python-definition:caf\N{LATIN SMALL LETTER E WITH ACUTE}:function:0",
        "python-definition:caf\N{LATIN SMALL LETTER E WITH ACUTE}:function:1",
    ]
    assert len({item.candidate_id for item in definitions}) == 2


def test_python_identifier_nfkc_equivalence_never_emits_a_false_exact_edge(
    tmp_path: Path,
) -> None:
    _write_repository(tmp_path)
    (tmp_path / "src/identifier_normalization.py").write_text(
        "def K():\n"
        "    return 1\n\n"
        "def \N{FULLWIDTH LATIN CAPITAL LETTER K}():\n"
        "    return 2\n\n"
        "def caller():\n"
        "    return K()\n",
        encoding="utf-8",
    )
    report = _section_report()
    section = report.spec_sections[0]
    report = replace(
        report,
        spec_mappings=(
            SpecMapping(
                section.path,
                section.section_id,
                3,
                "src/identifier_normalization.py::caller",
                "path_symbol",
                "src/identifier_normalization.py",
                "caller",
            ),
        ),
    )

    candidates = discover_evidence_candidates(
        _capture(tmp_path),
        report,
        PROFILE,
        _obligation(title="Identifier normalization"),
        SETTINGS,
    )

    call = next(
        item
        for item in candidates
        if item.path == "src/identifier_normalization.py"
        and item.owner == "caller"
        and ":call:" in item.structural_locator
    )
    assert call.candidate_kind == "unresolved_reference"
    assert all(
        relation.relation_kind != "static_call" for relation in call.static_relations
    )


def test_invalid_relative_imports_never_fall_back_to_top_level_modules(
    tmp_path: Path,
) -> None:
    _write_repository(tmp_path)
    (tmp_path / "plain").mkdir()
    (tmp_path / "plain/x.py").write_text(
        "def target():\n    return 1\n",
        encoding="utf-8",
    )
    (tmp_path / "plain/top_level_relative.py").write_text(
        "from . import x\n\ndef top_level_caller():\n    return x.target()\n",
        encoding="utf-8",
    )
    (tmp_path / "src/pkg").mkdir()
    (tmp_path / "src/pkg/__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "src/pkg/overclimb.py").write_text(
        "from ... import x\n\ndef overclimb_caller():\n    return x.target()\n",
        encoding="utf-8",
    )
    report = _section_report()
    section = report.spec_sections[0]
    report = replace(
        report,
        spec_mappings=tuple(
            SpecMapping(
                section.path,
                section.section_id,
                3,
                f"{path}::{owner}",
                "path_symbol",
                path,
                owner,
            )
            for path, owner in (
                ("plain/top_level_relative.py", "top_level_caller"),
                ("src/pkg/overclimb.py", "overclimb_caller"),
            )
        ),
    )
    profile = replace(PROFILE, code_roots=("src", "plain", "tests"))
    snapshot = capture_repository_snapshot(
        tmp_path,
        replace(_snapshot_config(), code_roots=profile.code_roots),
        ALGORITHMS,
    )

    candidates = discover_evidence_candidates(
        snapshot,
        report,
        profile,
        _obligation(title="Invalid relative import"),
        SETTINGS,
    )

    calls = [
        item
        for item in candidates
        if item.owner in {"top_level_caller", "overclimb_caller"}
        and ":call:" in item.structural_locator
    ]
    assert len(calls) == 2
    assert all(item.candidate_kind == "unresolved_reference" for item in calls)
    assert all(
        relation.relation_kind != "static_call"
        for item in calls
        for relation in item.static_relations
    )


def test_from_import_is_ambiguous_when_package_definition_and_submodule_collide(
    tmp_path: Path,
) -> None:
    _write_repository(tmp_path)
    (tmp_path / "src/collision").mkdir()
    (tmp_path / "src/collision/__init__.py").write_text(
        "def selected():\n    return 'definition'\n",
        encoding="utf-8",
    )
    (tmp_path / "src/collision/selected.py").write_text(
        "VALUE = 'submodule'\n",
        encoding="utf-8",
    )
    (tmp_path / "src/collision_consumer.py").write_text(
        "from src.collision import selected\n\ndef caller():\n    return selected()\n",
        encoding="utf-8",
    )
    report = _section_report()
    section = report.spec_sections[0]
    report = replace(
        report,
        spec_mappings=(
            SpecMapping(
                section.path,
                section.section_id,
                3,
                "src/collision_consumer.py::caller",
                "path_symbol",
                "src/collision_consumer.py",
                "caller",
            ),
        ),
    )

    candidates = discover_evidence_candidates(
        _capture(tmp_path),
        report,
        PROFILE,
        _obligation(title="Collision consumer"),
        SETTINGS,
    )

    call = next(
        item
        for item in candidates
        if item.path == "src/collision_consumer.py"
        and item.owner == "caller"
        and ":call:" in item.structural_locator
    )
    assert call.candidate_kind == "unresolved_reference"
    assert "ambiguous_relation" in call.discovery_bases
    assert all(
        relation.relation_kind != "static_call" for relation in call.static_relations
    )


def test_nested_definition_seed_never_reaches_its_lexical_owner(
    tmp_path: Path,
) -> None:
    _write_repository(tmp_path)
    (tmp_path / "src/nested.py").write_text(
        "class Owner:\n    def nested(self):\n        return 1\n",
        encoding="utf-8",
    )
    report = _section_report()
    section = report.spec_sections[0]
    report = replace(
        report,
        spec_mappings=(
            SpecMapping(
                section.path,
                section.section_id,
                3,
                "src/nested.py::Owner.nested",
                "path_symbol",
                "src/nested.py",
                "Owner.nested",
            ),
        ),
    )

    candidates = discover_evidence_candidates(
        _capture(tmp_path),
        report,
        PROFILE,
        _obligation(title="No lexical seed"),
        replace(SETTINGS, maximum_lexical_seeds=0, static_neighbor_depth=1),
    )

    nested = next(
        item
        for item in candidates
        if item.structural_locator == "python-definition:Owner.nested:function:0"
    )
    assert nested
    assert not any(
        item.structural_locator == "python-definition:Owner:class:0"
        for item in candidates
    )


def test_import_candidate_kind_reflects_complete_alias_resolution(
    tmp_path: Path,
) -> None:
    _write_repository(tmp_path)
    (tmp_path / "src/first.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "src/second.py").write_text("VALUE = 2\n", encoding="utf-8")
    (tmp_path / "src/multi_import.py").write_text(
        "def multi_import():\n"
        "    import src.first as first, src.second as second\n"
        "    return first, second\n",
        encoding="utf-8",
    )
    (tmp_path / "src/mixed_import.py").write_text(
        "def mixed_import():\n"
        "    import src.first as first, shared as shared\n"
        "    return first, shared\n",
        encoding="utf-8",
    )
    for root in ("first", "second"):
        (tmp_path / root).mkdir()
        (tmp_path / root / "shared.py").write_text(
            "VALUE = 3\n",
            encoding="utf-8",
        )
    profile = replace(
        PROFILE,
        code_roots=("src", "first", "second", "tests"),
    )
    snapshot = capture_repository_snapshot(
        tmp_path,
        replace(_snapshot_config(), code_roots=profile.code_roots),
        ALGORITHMS,
    )
    base = _section_report()
    section = base.spec_sections[0]
    report = replace(
        base,
        spec_mappings=tuple(
            SpecMapping(
                section.path,
                section.section_id,
                3 + index,
                f"{path}::{symbol}" if symbol is not None else path,
                "path_symbol" if symbol is not None else "path",
                path,
                symbol,
            )
            for index, (path, symbol) in enumerate(
                (
                    ("src/mixed_import.py", "mixed_import"),
                    ("src/multi_import.py", "multi_import"),
                    ("src/first.py", None),
                    ("src/second.py", None),
                )
            )
        ),
        code_refs=(),
    )

    candidates = discover_evidence_candidates(
        snapshot,
        report,
        profile,
        _obligation(title="Multi mixed import"),
        SETTINGS,
    )

    imports = {
        item.path: item
        for item in candidates
        if item.path in {"src/multi_import.py", "src/mixed_import.py"}
        and ":import:" in item.structural_locator
    }
    assert imports["src/multi_import.py"].candidate_kind == "static_reference"
    assert {
        relation.target_locator
        for relation in imports["src/multi_import.py"].static_relations
        if relation.relation_kind == "static_import"
    } == {"python-module:src.first", "python-module:src.second"}
    assert imports["src/mixed_import.py"].candidate_kind == "unresolved_reference"


def test_as_pattern_capture_shadows_an_imported_name(
    tmp_path: Path,
) -> None:
    _write_repository(tmp_path)
    (tmp_path / "src/targets.py").write_text(
        "def alias():\n    return 1\n",
        encoding="utf-8",
    )
    (tmp_path / "src/patterns.py").write_text(
        "from src.targets import alias\n\n"
        "def caller(value):\n"
        "    match value:\n"
        "        case chosen as alias:\n"
        "            return alias()\n",
        encoding="utf-8",
    )
    report = _section_report()
    section = report.spec_sections[0]
    report = replace(
        report,
        spec_mappings=(
            SpecMapping(
                section.path,
                section.section_id,
                3,
                "src/patterns.py::caller",
                "path_symbol",
                "src/patterns.py",
                "caller",
            ),
        ),
    )

    candidates = discover_evidence_candidates(
        _capture(tmp_path),
        report,
        PROFILE,
        _obligation(title="Pattern caller"),
        SETTINGS,
    )

    call = next(
        item
        for item in candidates
        if item.path == "src/patterns.py"
        and item.owner == "caller"
        and ":call:" in item.structural_locator
    )
    assert call.candidate_kind == "unresolved_reference"
    assert all(
        relation.relation_kind != "static_call" for relation in call.static_relations
    )


def test_method_implicit_class_cell_shadows_a_module_import(
    tmp_path: Path,
) -> None:
    _write_repository(tmp_path)
    (tmp_path / "src/targets.py").write_text(
        "class Imported:\n    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "src/class_cell.py").write_text(
        "from src.targets import Imported as __class__\n\n"
        "class Owner:\n"
        "    def method(self):\n"
        "        return __class__()\n",
        encoding="utf-8",
    )
    report = _section_report()
    section = report.spec_sections[0]
    report = replace(
        report,
        spec_mappings=(
            SpecMapping(
                section.path,
                section.section_id,
                3,
                "src/class_cell.py::Owner.method",
                "path_symbol",
                "src/class_cell.py",
                "Owner.method",
            ),
        ),
    )

    candidates = discover_evidence_candidates(
        _capture(tmp_path),
        report,
        PROFILE,
        _obligation(title="Class cell"),
        SETTINGS,
    )

    call = next(
        item
        for item in candidates
        if item.path == "src/class_cell.py"
        and item.owner == "Owner.method"
        and ":call:" in item.structural_locator
    )
    assert call.candidate_kind == "unresolved_reference"
    assert all(
        relation.relation_kind != "static_call" for relation in call.static_relations
    )


def test_method_bare_name_does_not_resolve_through_class_namespace(
    tmp_path: Path,
) -> None:
    _write_repository(tmp_path)
    (tmp_path / "src/worker.py").write_text(
        "def module_helper():\n"
        "    return True\n\n"
        "class Worker:\n"
        "    def module_helper(self):\n"
        "        return False\n\n"
        "    def run(self):\n"
        "        return module_helper()\n",
        encoding="utf-8",
    )
    snapshot = _capture(tmp_path)

    candidates = discover_evidence_candidates(
        snapshot,
        _section_report(),
        PROFILE,
        _obligation(title="Module helper"),
        SETTINGS,
    )

    method_targets = {
        relation.target_locator
        for item in candidates
        if item.owner == "Worker.run" and item.candidate_kind == "static_reference"
        for relation in item.static_relations
        if relation.relation_kind in {"static_call", "static_reference"}
    }
    assert method_targets == {"python-definition:module_helper:function:0"}


def test_class_body_uses_its_scope_but_method_skips_the_class_namespace(
    tmp_path: Path,
) -> None:
    _write_repository(tmp_path)
    (tmp_path / "src/targets.py").write_text(
        "def module_target():\n    return 1\n\ndef class_target():\n    return 2\n",
        encoding="utf-8",
    )
    (tmp_path / "src/scopes.py").write_text(
        "from src.targets import module_target as chosen\n\n"
        "class Scope:\n"
        "    from src.targets import class_target as chosen\n"
        "    class_value = chosen()\n\n"
        "    def method(self):\n"
        "        return chosen()\n",
        encoding="utf-8",
    )
    snapshot = _capture(tmp_path)

    candidates = discover_evidence_candidates(
        snapshot,
        _section_report(),
        PROFILE,
        _obligation(title="Chosen target"),
        SETTINGS,
    )

    targets_by_owner = {
        owner: {
            relation.target_locator
            for item in candidates
            if item.owner == owner and item.candidate_kind == "static_reference"
            for relation in item.static_relations
            if relation.relation_kind == "static_call"
        }
        for owner in ("Scope", "Scope.method")
    }
    assert targets_by_owner == {
        "Scope": {"python-definition:class_target:function:0"},
        "Scope.method": {"python-definition:module_target:function:0"},
    }


def test_pep695_static_resolution_uses_exact_source_order_without_runtime_ast(
    tmp_path: Path,
) -> None:
    _write_repository(tmp_path)
    (tmp_path / "src/targets.py").write_text(
        "def first():\n    return 1\n\ndef second():\n    return 2\n",
        encoding="utf-8",
    )
    (tmp_path / "src/ordered.py").write_text(
        "from src.targets import first as chosen, second as chosen; chosen()\n\n"
        "def sequence[T](value: T):\n"
        "    from src.targets import first as chosen; chosen(); del chosen; "
        "chosen(); from src.targets import second as chosen; chosen(); "
        "chosen = value; chosen()\n",
        encoding="utf-8",
    )
    snapshot = _capture(tmp_path)
    base = _section_report()
    section = base.spec_sections[0]
    report = replace(
        base,
        spec_mappings=(
            SpecMapping(
                section.path,
                section.section_id,
                3,
                "src/ordered.py::sequence",
                "path_symbol",
                "src/ordered.py",
                "sequence",
            ),
        ),
        code_refs=(),
    )

    candidates = discover_evidence_candidates(
        snapshot,
        report,
        PROFILE,
        _obligation(title="Ordered chosen target"),
        SETTINGS,
    )

    assert not any(
        item.owner == "src.ordered" and ":call:" in item.structural_locator
        for item in candidates
    )

    sequence_calls = sorted(
        (
            item
            for item in candidates
            if item.owner == "sequence" and ":call:" in item.structural_locator
        ),
        key=lambda item: item.structural_locator,
    )
    assert [item.candidate_kind for item in sequence_calls] == [
        "static_reference",
        "unresolved_reference",
        "static_reference",
        "unresolved_reference",
    ]
    assert [
        {
            relation.target_locator
            for relation in item.static_relations
            if relation.relation_kind == "static_call"
        }
        for item in sequence_calls
    ] == [
        {"python-definition:first:function:0"},
        set(),
        {"python-definition:second:function:0"},
        set(),
    ]


def test_static_resolution_fails_closed_for_lexical_and_branch_uncertainty(
    tmp_path: Path,
) -> None:
    _write_repository(tmp_path)
    (tmp_path / "src/targets.py").write_text(
        "def first():\n    return 1\n\ndef second():\n    return 2\n",
        encoding="utf-8",
    )
    (tmp_path / "src/uncertain_target.py").write_text(
        "from src.targets import first as chosen\n\n"
        "def target_before_local_assignment():\n"
        "    chosen()\n"
        "    chosen = lambda: 0\n\n"
        "def target_before_local_definition():\n"
        "    chosen()\n"
        "    def chosen():\n"
        "        return 0\n\n"
        "def target_before_module_rebind():\n"
        "    return chosen()\n\n"
        "def target_before_type_alias():\n"
        "    chosen()\n"
        "    type chosen = int\n\n"
        "def target_type_parameter[chosen]():\n"
        "    return chosen()\n\n"
        "class TargetGenericClass[chosen]:\n"
        "    def target_generic_method(self):\n"
        "        return chosen()\n\n"
        "    class Nested:\n"
        "        value = chosen()\n"
        "        def target_nested_generic_method(self):\n"
        "            return chosen()\n\n"
        "def target_outer_rebind():\n"
        "    def target_nested():\n"
        "        return chosen()\n"
        "    chosen = lambda: 0\n"
        "    return target_nested()\n\n"
        "chosen = lambda: 0\n\n"
        "def target_conditional_import(flag):\n"
        "    if flag:\n"
        "        from src.targets import first as selected\n"
        "    return selected()\n\n"
        "def target_alternative_import():\n"
        "    try:\n"
        "        from src.targets import first as branch\n"
        "    except Exception:\n"
        "        from src.targets import second as branch\n"
        "    return branch()\n",
        encoding="utf-8",
    )
    base = _section_report()
    section = base.spec_sections[0]
    uncertain_owners = {
        "target_before_local_assignment",
        "target_before_local_definition",
        "target_before_module_rebind",
        "target_before_type_alias",
        "target_type_parameter",
        "TargetGenericClass.target_generic_method",
        "TargetGenericClass.Nested",
        "TargetGenericClass.Nested.target_nested_generic_method",
        "target_outer_rebind.target_nested",
        "target_conditional_import",
        "target_alternative_import",
    }
    report = replace(
        base,
        spec_mappings=tuple(
            SpecMapping(
                section.path,
                section.section_id,
                3 + index,
                f"src/uncertain_target.py::{owner}",
                "path_symbol",
                "src/uncertain_target.py",
                owner,
            )
            for index, owner in enumerate(sorted(uncertain_owners))
        ),
        code_refs=(),
    )

    candidates = discover_evidence_candidates(
        _capture(tmp_path),
        report,
        PROFILE,
        _obligation(title="Uncertain target"),
        SETTINGS,
    )

    calls = [
        item
        for item in candidates
        if item.owner in uncertain_owners and ":call:" in item.structural_locator
    ]
    assert {item.owner for item in calls} == uncertain_owners
    assert all(item.candidate_kind == "unresolved_reference" for item in calls)
    assert not {
        relation.target_locator
        for item in calls
        for relation in item.static_relations
        if relation.relation_kind == "static_call"
    }
    assert {
        item.structural_locator
        for item in candidates
        if "ambiguous_relation" in item.discovery_bases
    } >= {
        "python-definition:first:function:0",
        "python-definition:second:function:0",
    }


@pytest.mark.parametrize("depth", (0, 1))
def test_ambiguous_targets_expand_only_after_the_reference_is_reached(
    tmp_path: Path,
    depth: int,
) -> None:
    _write_repository(tmp_path)
    snapshot = _capture(tmp_path)
    report = _section_report()
    if depth == 1:
        section = report.spec_sections[0]
        report = replace(
            report,
            spec_mappings=(
                SpecMapping(
                    section.path,
                    section.section_id,
                    3,
                    "src/worker.py::ambiguous_caller",
                    "path_symbol",
                    "src/worker.py",
                    "ambiguous_caller",
                ),
            ),
            code_refs=(),
        )

    candidates = discover_evidence_candidates(
        snapshot,
        report,
        PROFILE,
        _obligation(title="Ambiguous caller"),
        replace(
            SETTINGS,
            maximum_lexical_seeds=1_000 if depth == 0 else 0,
            static_neighbor_depth=depth,
        ),
    )

    ambiguous_definitions = [
        item
        for item in candidates
        if item.owner == "ambiguous"
        and item.candidate_kind == "implementation_definition"
    ]
    assert len(ambiguous_definitions) == 2
    assert all(
        ("ambiguous_relation" in item.discovery_bases) is (depth == 1)
        for item in ambiguous_definitions
    )


def test_lexical_search_uses_explicit_parser_owned_text_only(tmp_path: Path) -> None:
    _write_repository(tmp_path)
    (tmp_path / "src/search_only.py").write_text(
        "def masked_token():\n    return True\n",
        encoding="utf-8",
    )
    snapshot = _capture(tmp_path)
    obligation = _obligation(title="Unrelated title")

    without_search_text = discover_evidence_candidates(
        snapshot,
        _section_report(),
        PROFILE,
        obligation,
        replace(SETTINGS, static_neighbor_depth=0),
    )
    with_search_text = discover_evidence_candidates(
        snapshot,
        _section_report(),
        PROFILE,
        obligation,
        replace(SETTINGS, static_neighbor_depth=0),
        obligation_search_text="masked token",
    )

    assert not any(
        item.owner == "masked_token" and "lexical_match" in item.discovery_bases
        for item in without_search_text
    )
    assert any(
        item.owner == "masked_token" and "lexical_match" in item.discovery_bases
        for item in with_search_text
    )
