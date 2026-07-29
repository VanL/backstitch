from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from backstitch.git_baseline import DriftState, GitTransition
from backstitch.intent_coverage import CoverageDefinition
from backstitch.intent_history import (
    IntentRevisionProjector,
    IntentRevisionState,
    fold_stale_doc_history,
)
from backstitch.profiles import get_profile
from backstitch.settings import BackstitchSettings, ProfileSettings


def _definition(index: int) -> CoverageDefinition:
    return CoverageDefinition(
        definition_id=f"definition-{index}",
        path=f"pkg/module_{index}.py",
        structural_locator=f"module_{index}.symbol_{index}",
        qualname=f"symbol_{index}",
        kind="function",
        role="production",
        start_line=index + 1,
        end_line=index + 1,
        source_projection_sha256=f"sha256:{index:064x}",
        parent_definition_id=None,
        tree="pkg",
    )


def _drift_state(index: int, *, implementation: int = 0) -> DriftState:
    return DriftState(
        edge_id=f"edge-{index}",
        requirement_id=f"requirement-{index}",
        definition_id=f"definition-{index}",
        section_hash="section",
        mapping_hash="mapping",
        implementation_hash=f"implementation-{implementation}",
        connected_test_hash="tests",
    )


def _revision(
    states: dict[str, DriftState],
    definitions: dict[str, CoverageDefinition],
) -> IntentRevisionState:
    edge_sections = {
        edge_id: ("docs/specs/feature.md", f"REQ-{index}")
        for index, edge_id in enumerate(states)
    }
    path_edge_sets: dict[str, set[str]] = {}
    for index, definition in enumerate(definitions.values()):
        edge_id = f"edge-{index}"
        if edge_id in states:
            path_edge_sets.setdefault(definition.path, set()).add(edge_id)
    path_edge_sets["docs/specs/feature.md"] = set(states)
    path_edges = {
        path: tuple(sorted(edge_ids)) for path, edge_ids in path_edge_sets.items()
    }
    return IntentRevisionState(
        profile=get_profile("backstitch-style-v1"),
        definitions=definitions,
        drift_states=states,
        section_rows=dict.fromkeys(edge_sections.values(), ("section", 10)),
        edge_sections=edge_sections,
        path_edges=path_edges,
    )


def test_stale_history_scale_indexes_changed_paths_instead_of_edges_times_commits() -> (
    None
):
    definitions = {f"definition-{index}": _definition(index) for index in range(10_000)}
    states = {f"edge-{index}": _drift_state(index) for index in range(1_000)}
    before = _revision(states, definitions)
    indexed = []
    for index in range(200):
        edge_id = f"edge-{index}"
        after_states = dict(before.drift_states)
        after_states[edge_id] = replace(
            after_states[edge_id],
            implementation_hash=f"implementation-{index + 1}",
        )
        after = _revision(after_states, definitions)
        indexed.append(
            (
                GitTransition(
                    parent_commit=f"{index + 1:040x}",
                    commit=f"{index + 2:040x}",
                    message="",
                    changes=((definitions[f"definition-{index}"].path, b"changed"),),
                ),
                before,
                after,
            )
        )
        before = after

    result = fold_stale_doc_history(
        tuple(indexed),
        current_state=before,
        history_complete=False,
    )

    assert len(result.trends) == 1_000
    assert result.work.definitions_indexed == 10_000
    assert result.work.edges_indexed == 1_000
    assert result.work.transitions_indexed == 200
    assert result.work.edge_transitions_evaluated == 200
    assert result.work.edge_transitions_evaluated < 1_000 * 200
    assert sum(row.unacknowledged_event_count for row in result.trends) == 200
    assert all(row.history_complete is False for row in result.trends)


def test_stale_history_resets_on_latest_section_change_and_keeps_exact_ack() -> None:
    definitions = {"definition-0": _definition(0)}
    initial = _revision({"edge-0": _drift_state(0)}, definitions)
    drifted = _revision(
        {"edge-0": _drift_state(0, implementation=1)},
        definitions,
    )
    section_changed = _revision(
        {
            "edge-0": replace(
                _drift_state(0, implementation=1),
                section_hash="section-2",
            )
        },
        definitions,
    )
    section_changed = replace(
        section_changed,
        section_rows={("docs/specs/feature.md", "REQ-0"): ("section-2", 10)},
    )
    drifted_again = _revision(
        {
            "edge-0": replace(
                _drift_state(0, implementation=2),
                section_hash="section-2",
            )
        },
        definitions,
    )
    drifted_again = replace(
        drifted_again,
        section_rows={("docs/specs/feature.md", "REQ-0"): ("section-2", 10)},
    )
    transitions = (
        (
            GitTransition("1" * 40, "2" * 40, "", (("pkg/module_0.py", b"1"),)),
            initial,
            drifted,
        ),
        (
            GitTransition(
                "2" * 40,
                "3" * 40,
                "",
                (("docs/specs/feature.md", b"section"),),
            ),
            drifted,
            section_changed,
        ),
        (
            GitTransition("3" * 40, "4" * 40, "", (("pkg/module_0.py", b"2"),)),
            section_changed,
            drifted_again,
        ),
    )

    result = fold_stale_doc_history(
        transitions,
        current_state=drifted_again,
        history_complete=False,
    )

    assert result.trends[0].section_change_commit == "3" * 40
    assert result.trends[0].unacknowledged_event_count == 1
    assert result.trends[0].last_event_commit == "4" * 40
    assert result.trends[0].history_complete is True
    assert result.trends[0].commits_inspected == 3


def test_revision_projector_reuses_one_real_graph_projection_by_commit_identity(
    tmp_path: Path,
) -> None:
    blobs = {
        "docs/specs/feature.md": (
            b"# Feature\n\n## Rule [REQ-1]\n\n"
            b"_Implementation mapping_:\n\n- `pkg/api.py::answer`\n"
        ),
        "pkg/api.py": (
            b"def answer():\n"
            b'    """Spec: docs/specs/feature.md [REQ-1]"""\n'
            b"    return 1\n"
        ),
    }
    settings = BackstitchSettings(
        profile_overrides=ProfileSettings(
            spec_roots=("docs/specs",),
            plan_roots=(),
            code_roots=("pkg",),
            test_roots=(),
        )
    )
    projector = IntentRevisionProjector()

    first = projector.project(
        "1" * 40,
        blobs,
        repo_root=tmp_path,
        settings=settings,
    )
    second = projector.project(
        "1" * 40,
        blobs,
        repo_root=tmp_path,
        settings=settings,
    )

    assert first is second
    assert projector.projection_builds == 1
    assert projector.cache_hits == 1
