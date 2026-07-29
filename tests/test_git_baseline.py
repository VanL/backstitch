from __future__ import annotations

import subprocess
from pathlib import Path
from typing import cast

import pytest

from backstitch.git_baseline import (
    DriftState,
    DriftTransition,
    GitBaselineError,
    GitLimits,
    PolicyTransition,
    baseline_metadata,
    compare_coverage_policies,
    compute_drift_event,
    compute_stale_doc_trend,
    connected_test_identity,
    current_content_identity,
    fold_policy_transitions,
    load_git_baseline,
    mapping_identity,
    parse_acknowledgments,
    section_projection_hash,
)


def _git(repo: Path, *args: str, input_bytes: bytes | None = None) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        input=input_bytes,
        capture_output=True,
        check=True,
    ).stdout


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", ".")
    _git(
        repo,
        "-c",
        "user.name=Intent Test",
        "-c",
        "user.email=intent@example.invalid",
        "commit",
        "-m",
        message,
    )
    return _git(repo, "rev-parse", "HEAD").decode().strip()


def test_load_git_baseline_binds_merge_base_blobs_and_first_parent_history(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "pkg").mkdir()
    (repo / "pkg" / "api.py").write_text("def answer():\n    return 1\n")
    base = _commit(repo, "base")
    _git(repo, "branch", "baseline")

    (repo / "pkg" / "api.py").write_text("def answer():\n    return 2\n")
    head = _commit(repo, "change answer")

    result = load_git_baseline(
        repo,
        "baseline",
        limits=GitLimits(),
        include_paths=("pkg/api.py",),
    )

    assert result.base_commit == base
    assert result.merge_base == base
    assert result.head_commit == head
    assert result.blobs == {"pkg/api.py": b"def answer():\n    return 1\n"}
    assert result.history_blobs == {"pkg/api.py": b"def answer():\n    return 1\n"}
    assert [
        (row.parent_commit, row.commit, row.message) for row in result.transitions
    ] == [(base, head, "change answer\n")]
    assert [
        (row.parent_commit, row.commit, row.message)
        for row in result.history_transitions
    ] == [(base, head, "change answer\n")]
    assert result.transitions[0].changes == (
        ("pkg/api.py", b"def answer():\n    return 2\n"),
    )
    assert result.history_transitions[0].changes == (
        ("pkg/api.py", b"def answer():\n    return 2\n"),
    )
    assert result.commands_used <= 13
    assert current_content_identity(
        {"pkg/api.py": "sha256:" + "f" * 64, "pkg/z.py": "sha256:" + "0" * 64}
    ) == ("sha256:02a80fa70c6258e39988c3757144ef94cfd7a8e8e0fe6b9255b2d20e113239bb")
    metadata = baseline_metadata(
        result,
        current_snapshot_sha256="sha256:" + "1" * 64,
        current_content_sha256="sha256:" + "2" * 64,
        baseline_policy_sha256="sha256:" + "3" * 64,
        current_policy_sha256="sha256:" + "4" * 64,
    )
    assert metadata.configured_ref == "baseline"
    assert metadata.history_commits_inspected == 1


def test_load_git_baseline_parses_multiple_path_records_for_one_transition(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "delete.py").write_text("delete = True\n")
    (repo / "modify.py").write_text("value = 1\n")
    base = _commit(repo, "base")
    _git(repo, "branch", "baseline")

    (repo / "add.py").write_text("added = True\n")
    (repo / "delete.py").unlink()
    (repo / "modify.py").write_text("value = 2\n")
    head = _commit(repo, "add modify delete")

    result = load_git_baseline(
        repo,
        "baseline",
        limits=GitLimits(),
    )

    assert [(row.parent_commit, row.commit) for row in result.transitions] == [
        (base, head)
    ]
    assert result.transitions[0].changes == (
        ("add.py", b"added = True\n"),
        ("delete.py", None),
        ("modify.py", b"value = 2\n"),
    )
    assert result.history_transitions[0].changes == result.transitions[0].changes


def test_load_git_baseline_rejects_unsafe_ref_and_enforces_aggregate_output_budget(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "one.py").write_text("x = 1\n")
    _commit(repo, "base")
    _git(repo, "branch", "baseline")

    with pytest.raises(GitBaselineError, match="ref is invalid"):
        load_git_baseline(repo, "--upload-pack=bad", limits=GitLimits())
    with pytest.raises(GitBaselineError, match="ref is invalid"):
        load_git_baseline(repo, "HEAD~1", limits=GitLimits())
    with pytest.raises(GitBaselineError, match="output budget"):
        load_git_baseline(
            repo,
            "baseline",
            limits=GitLimits(maximum_git_output_bytes=10),
        )


def test_baseline_byte_budget_counts_each_path_even_when_blobs_are_deduplicated(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "one.py").write_text("x = 1\n")
    (repo / "two.py").write_text("x = 1\n")
    _commit(repo, "base")
    _git(repo, "branch", "baseline")

    with pytest.raises(GitBaselineError, match="baseline byte budget"):
        load_git_baseline(
            repo,
            "baseline",
            limits=GitLimits(maximum_baseline_bytes=10),
        )


def test_stale_history_is_bounded_but_current_ratchet_range_is_complete(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "one.py").write_text("value = 0\n")
    _commit(repo, "zero")
    _git(repo, "branch", "baseline")
    for value in range(1, 5):
        (repo / "one.py").write_text(f"value = {value}\n")
        _commit(repo, f"change {value}")

    result = load_git_baseline(
        repo,
        "baseline",
        limits=GitLimits(maximum_history_commits=2),
    )

    assert [row.message for row in result.transitions] == [
        "change 1\n",
        "change 2\n",
        "change 3\n",
        "change 4\n",
    ]
    assert [row.message for row in result.history_transitions] == [
        "change 3\n",
        "change 4\n",
    ]
    assert result.history_blobs["one.py"] == b"value = 2\n"
    assert result.history_transitions[0].changes == (("one.py", b"value = 3\n"),)
    assert result.history_complete is False


def test_two_hundred_real_git_transitions_use_constant_count_object_batches(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "one.py").write_text("value = 0\n")
    _commit(repo, "zero")
    _git(repo, "branch", "baseline")
    for value in range(1, 201):
        (repo / "one.py").write_text(f"value = {value}\n")
        _commit(repo, f"change {value}")

    result = load_git_baseline(
        repo,
        "baseline",
        limits=GitLimits(maximum_history_commits=200),
    )

    assert len(result.transitions) == 200
    assert len(result.history_transitions) == 200
    assert all(row.changes for row in result.history_transitions)
    assert result.commands_used <= 13


def _policy() -> dict[str, object]:
    return {
        "schema": "intent-coverage-policy-v1",
        "profile": {
            "name": "default",
            "spec_roots": ["docs/specs"],
            "code_roots": ["pkg"],
            "test_roots": ["tests"],
            "planned_spec_globs": [],
            "exploratory_spec_globs": [],
            "meta_spec_globs": [],
            "process_spec_globs": [],
        },
        "exclude": [],
        "coverage": {
            "mode": "ratchet",
            "granularity": "definition",
            "inherited_counts": False,
            "ratchet_base": "origin/main",
            "exemptions": [],
            "floors": [],
        },
        "diagnostics": {"default_level": "info"},
        "suppressions": {"rules": []},
    }


def test_policy_comparison_reports_only_weakening_and_authority_sensitive_changes() -> (
    None
):
    baseline = _policy()
    current = _policy()
    current["profile"] = {
        **cast(dict[str, object], baseline["profile"]),
        "code_roots": [],
        "planned_spec_globs": ["docs/plans/**"],
    }
    current["coverage"] = {
        **cast(dict[str, object], baseline["coverage"]),
        "inherited_counts": True,
        "floors": [{"scope": "pkg", "direct": 0.8, "accounted": None}],
    }
    current["diagnostics"] = {"default_level": "warning"}

    events = compare_coverage_policies(
        baseline,
        current,
        parent_commit="1" * 40,
    )

    assert [row.key for row in events] == [
        "/coverage/inherited_counts",
        "/diagnostics",
        "/profile/code_roots/sha256:25d7edfe2d2a52aeef024412b657ffaf3f5c7a8cc9f3df8a7d2e9e9e31cd7269",
        "/profile/planned_spec_globs/sha256:79b0c1ff91e9006a6ab3baf16252f371c1bb1d67d3b3b0573727de41aa55b1ad",
    ]


def test_policy_acknowledgment_applies_only_to_its_committed_transition() -> None:
    baseline = _policy()
    current = _policy()
    current["coverage"] = {
        **cast(dict[str, object], baseline["coverage"]),
        "inherited_counts": True,
    }
    unacknowledged = compare_coverage_policies(
        baseline,
        current,
        parent_commit="1" * 40,
        transition_commit="2" * 40,
    )[0]
    trailer = (
        f"Backstitch-Coverage-Policy-Ack: {unacknowledged.event_id} -- owner approved"
    )

    acknowledged = compare_coverage_policies(
        baseline,
        current,
        parent_commit="1" * 40,
        transition_commit="2" * 40,
        commit_message=trailer,
    )[0]
    synthetic = compare_coverage_policies(
        baseline,
        current,
        parent_commit="1" * 40,
        transition_commit=None,
        commit_message=trailer,
    )[0]

    assert acknowledged.acknowledged is True
    assert acknowledged.acknowledgment_commit == "2" * 40
    assert acknowledged.acknowledgment_reason == "owner approved"
    assert synthetic.acknowledged is False


def test_policy_history_keeps_only_the_event_that_established_the_final_value() -> None:
    baseline = _policy()
    weakened = _policy()
    weakened["coverage"] = {
        **cast(dict[str, object], baseline["coverage"]),
        "inherited_counts": True,
    }
    restored = _policy()

    assert (
        fold_policy_transitions(
            (
                PolicyTransition(
                    parent_commit="1" * 40,
                    transition_commit="2" * 40,
                    before=baseline,
                    after=weakened,
                ),
                PolicyTransition(
                    parent_commit="2" * 40,
                    transition_commit="3" * 40,
                    before=weakened,
                    after=restored,
                ),
            )
        )
        == ()
    )
    final = fold_policy_transitions(
        (
            PolicyTransition(
                parent_commit="1" * 40,
                transition_commit="2" * 40,
                before=baseline,
                after=weakened,
            ),
        )
    )
    assert len(final) == 1
    assert final[0].parent_commit == "1" * 40


def _drift_transition(**changes: str) -> DriftTransition:
    before = DriftState(
        edge_id="sha256:" + "a" * 64,
        requirement_id="sha256:" + "b" * 64,
        definition_id="sha256:" + "c" * 64,
        section_hash="section-1",
        mapping_hash="mapping-1",
        implementation_hash="implementation-1",
        connected_test_hash="test-1",
    )
    after = DriftState(
        edge_id=before.edge_id,
        requirement_id=before.requirement_id,
        definition_id=before.definition_id,
        section_hash=changes.get("section_hash", before.section_hash),
        mapping_hash=changes.get("mapping_hash", before.mapping_hash),
        implementation_hash=changes.get("implementation_hash", "implementation-2"),
        connected_test_hash=changes.get(
            "connected_test_hash", before.connected_test_hash
        ),
    )
    return DriftTransition(
        parent_commit="1" * 40,
        child_commit="2" * 40,
        before=before,
        after=after,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"implementation_hash": "implementation-1"},
        {"section_hash": "section-2"},
        {"mapping_hash": "mapping-2"},
        {"connected_test_hash": "test-2"},
    ],
)
def test_drift_requires_only_implementation_to_change(changes: dict[str, str]) -> None:
    assert compute_drift_event(_drift_transition(**changes)) is None


def test_section_projection_hash_removes_owned_mapping_blocks_without_normalizing() -> (
    None
):
    source = (
        b"# preface\n"
        b"## Rule [RULE-1]\n"
        b"Keep  two spaces.\r\n"
        b"_Implementation mapping_:\n"
        b"\n"
        b"- `pkg/api.py`\n"
        b"Final line"
    )

    projection, digest = section_projection_hash(
        source,
        section_start_line=2,
        section_end_line=7,
        mapping_block_spans=(("RULE-1", 4, 6),),
        section_id="RULE-1",
    )

    assert projection == (b"## Rule [RULE-1]\nKeep  two spaces.\r\nFinal line")
    assert digest == (
        "sha256:549338070e80da894ba441dbd5f5d02b31c7a0072faca627c9c123b920c440b7"
    )


def test_mapping_and_connected_test_hashes_sort_and_deduplicate_closed_rows() -> None:
    assert mapping_identity(
        (("pkg/api.py", "answer"), ("pkg/api.py", None), ("pkg/api.py", None))
    ) == mapping_identity((("pkg/api.py", None), ("pkg/api.py", "answer")))
    assert connected_test_identity(
        (("definition-b", "hash-2"), ("definition-a", "hash-1"))
    ) == connected_test_identity(
        (("definition-a", "hash-1"), ("definition-b", "hash-2"))
    )


def test_drift_acknowledgment_is_exact_and_duplicate_trailers_do_not_match() -> None:
    transition = _drift_transition()
    event = compute_drift_event(transition)
    assert event is not None
    trailer = f"Backstitch-Drift-Ack: {event.event_id} -- reviewed"

    acknowledged = compute_drift_event(
        DriftTransition(
            parent_commit=transition.parent_commit,
            child_commit=transition.child_commit,
            before=transition.before,
            after=transition.after,
            commit_message=trailer,
        )
    )
    duplicate = compute_drift_event(
        DriftTransition(
            parent_commit=transition.parent_commit,
            child_commit=transition.child_commit,
            before=transition.before,
            after=transition.after,
            commit_message=f"{trailer}\n{trailer}\n",
        )
    )

    assert acknowledged is not None and acknowledged.acknowledged is True
    assert duplicate is not None and duplicate.acknowledged is False
    assert [row.valid for row in parse_acknowledgments(f"{trailer}\n{trailer}\n")] == [
        False,
        False,
    ]
    body_mention = compute_drift_event(
        DriftTransition(
            parent_commit=transition.parent_commit,
            child_commit=transition.child_commit,
            before=transition.before,
            after=transition.after,
            commit_message=f"{trailer}\n\nThis is not a trailer block.\n",
        )
    )
    assert body_mention is not None and body_mention.acknowledged is False


def test_stale_trend_resets_at_latest_section_change_and_marks_truncation() -> None:
    old_drift = _drift_transition()
    section_change = _drift_transition(section_hash="section-2")
    after_section_change = DriftTransition(
        parent_commit="2" * 40,
        child_commit="3" * 40,
        before=section_change.after,
        after=DriftState(
            **{
                **{
                    field: getattr(section_change.after, field)
                    for field in section_change.after.__dataclass_fields__
                },
                "implementation_hash": "implementation-3",
            }
        ),
    )

    trend = compute_stale_doc_trend(
        old_drift.before.edge_id,
        (old_drift, section_change, after_section_change),
        history_complete=False,
    )
    truncated = compute_stale_doc_trend(
        old_drift.before.edge_id,
        (old_drift,),
        history_complete=False,
    )

    assert trend.section_change_commit == "2" * 40
    assert trend.unacknowledged_event_count == 1
    assert trend.last_event_commit == "3" * 40
    assert trend.history_complete is True
    assert trend.commits_inspected == 3
    assert truncated.section_change_commit is None
    assert truncated.unacknowledged_event_count == 1
    assert truncated.history_complete is False
