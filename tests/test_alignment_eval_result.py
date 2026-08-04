"""Closed Phase A/B product-evaluation result recomputation."""

from __future__ import annotations

import difflib
import hashlib
import json
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest

from backstitch.alignment_eval import (
    AlignmentEvalError,
    AlignmentEvalPlan,
    _AlignmentSessionEvaluator,
    _apply_revision,
    _candidate_artifact_value,
    _declaration_projection,
    _fixture_snapshot,
    _FixtureTree,
    _load_alignment_result_preamble,
    _production_fixture_view,
    _required_declaration_set,
    _TaskValidator,
    _validate_tree,
    load_alignment_eval_plan,
    load_alignment_eval_result,
)
from backstitch.config import ProfileConfig
from backstitch.settings import resolve_config

CORPUS = Path(__file__).parent / "product_eval/alignment-bootstrap/manifest.json"
PROPOSITIONS = [
    "repository source is the alignment authority",
    "candidates are advice",
    "Backstitch neither edits nor ratifies source relations",
    "semantic success cannot repair incomplete alignment",
]


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()


def _copy_corpus(tmp_path: Path) -> Path:
    root = tmp_path / "alignment-bootstrap"
    shutil.copytree(CORPUS.parent, root)
    return root / "manifest.json"


def _rehash_phase_b(manifest: Path, phase: dict[str, object]) -> None:
    phase_raw = _canonical(phase)
    (manifest.parent / "phase-b/fixtures.json").write_bytes(phase_raw)
    top = json.loads(manifest.read_text())
    top["phase_b_fixture_manifest_sha256"] = (
        "sha256:" + hashlib.sha256(phase_raw).hexdigest()
    )
    fixtures = cast(list[dict[str, object]], phase["fixtures"])
    top["critical_candidate_ids"] = sorted(
        f"{fixture['fixture_id']}#{gold['gold_id']}"
        for fixture in fixtures
        for gold in cast(list[dict[str, object]], fixture["gold_candidates"])
        if cast(bool, gold["critical"])
    )
    manifest.write_bytes(_canonical(top))


def _refresh_phase_b_fixture(
    manifest: Path,
    phase: dict[str, object],
    fixture: dict[str, object],
) -> None:
    phase_root = manifest.parent / "phase-b"
    fixture_root = phase_root / cast(str, fixture["fixture_path"])
    rows, _files = _fixture_snapshot(fixture_root, "mutated Phase B fixture")
    tree = {
        "schema_version": 1,
        "artifact": "backstitch-eval-fixture-tree",
        "files": rows,
    }
    tree_raw = _canonical(tree)
    tree_path = phase_root / cast(str, fixture["tree_manifest_path"])
    tree_path.write_bytes(tree_raw)
    fixture["tree_manifest_sha256"] = "sha256:" + hashlib.sha256(tree_raw).hexdigest()
    validated = _validate_tree(
        phase_base=phase_root,
        fixture_path=fixture["fixture_path"],
        tree_manifest_path=fixture["tree_manifest_path"],
        declared_tree_sha256=fixture["tree_manifest_sha256"],
        context="mutated Phase B fixture",
    )
    settings = resolve_config(validated.root, environment={})
    artifact = _candidate_artifact_value(
        validated,
        cast(str, fixture["task_obligation_id"]),
        settings,
    )
    artifact_raw = _canonical(artifact)
    artifact_path = phase_root / cast(str, fixture["candidate_artifact_path"])
    artifact_path.write_bytes(artifact_raw)
    fixture["candidate_artifact_sha256"] = (
        "sha256:" + hashlib.sha256(artifact_raw).hexdigest()
    )
    _rehash_phase_b(manifest, phase)


def _write_json(root: Path, name: str, value: object) -> tuple[str, str]:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = _canonical(value)
    path.write_bytes(raw)
    return name, "sha256:" + hashlib.sha256(raw).hexdigest()


def _tree(root: Path) -> dict[str, object]:
    files: list[dict[str, object]] = []
    for path in sorted(
        (item for item in root.rglob("*") if item.is_file()),
        key=lambda item: item.relative_to(root).as_posix(),
    ):
        raw = path.read_bytes()
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "raw_sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
                "byte_count": len(raw),
                "executable": bool(path.stat().st_mode & stat.S_IXUSR),
            }
        )
    return {
        "schema_version": 1,
        "artifact": "backstitch-eval-fixture-tree",
        "files": files,
    }


def _snapshot() -> dict[str, object]:
    return {
        "snapshot_hash": "snapshot:test",
        "file_count": 1,
        "byte_count": 1,
        "unreadable_count": 0,
    }


def _guidance(code: str) -> list[dict[str, str]]:
    return [{"code": code, "message": "Guidance.", "action": "Act."}]


def _run_obligation(
    root: Path,
    output_root: Path,
    output_name: str,
    obligation_id: str,
    *,
    find_evidence: bool = False,
) -> tuple[list[str], str, str]:
    argv = ["backstitch", "obligation", obligation_id]
    if find_evidence:
        argv.extend(("--find-evidence", "--limit", "100"))
    argv.extend(("--repo-root", ".", "--format", "json"))
    completed = subprocess.run(
        [sys.executable, "-m", "backstitch", *argv[1:]],
        cwd=root,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    assert completed.stderr == b""
    path = output_root / output_name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(completed.stdout)
    return (
        argv,
        path.relative_to(output_root).as_posix(),
        "sha256:" + hashlib.sha256(completed.stdout).hexdigest(),
    )


def _delta_stats(original: Path, revised: Path) -> tuple[list[str], int]:
    before = {
        path.relative_to(original).as_posix(): path.read_bytes()
        for path in original.rglob("*")
        if path.is_file()
    }
    after = {
        path.relative_to(revised).as_posix(): path.read_bytes()
        for path in revised.rglob("*")
        if path.is_file()
    }
    paths = sorted(
        path for path in set(before) | set(after) if before.get(path) != after.get(path)
    )
    changed = 0
    for path in paths:
        matcher = difflib.SequenceMatcher(
            a=before.get(path, b"").splitlines(keepends=True),
            b=after.get(path, b"").splitlines(keepends=True),
            autojunk=False,
        )
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag != "equal":
                changed += (i2 - i1) + (j2 - j1)
    return paths, changed


def _phase_a_diff(fixture_root: Path, fixture_id: str, revised: Path) -> bytes:
    shutil.copytree(fixture_root, revised)
    changed: list[tuple[str, list[str], list[str]]] = []
    spec = revised / "docs/specs/01-core.md"
    code = revised / "src/widget.py"
    before_spec = spec.read_text().splitlines(keepends=True)
    before_code = code.read_text().splitlines(keepends=True)
    after_spec = list(before_spec)
    after_code = list(before_code)
    if fixture_id == "partial":
        after_code = [
            "def widget() -> int:\n",
            '    """Spec: docs/specs/01-core.md [BOOT-1]"""\n',
            "    return 1\n",
        ]
    elif fixture_id in {"untraced", "skipped"}:
        if fixture_id == "skipped":
            after_spec = [
                line.replace(
                    ' <!-- backstitch: skip-obligation [BOOT-1] "Generated fixture is checked by an external owner." -->',
                    "",
                )
                for line in after_spec
            ]
        after_spec.extend(
            [
                "\n",
                "_Implementation mapping_:\n",
                "\n",
                "- `src/widget.py::widget`\n",
            ]
        )
        after_code = [
            "def widget() -> int:\n",
            '    """Spec: docs/specs/01-core.md [BOOT-1]"""\n',
            "    return 1\n",
        ]
    else:
        raise AssertionError(f"unexpected Phase A revision fixture: {fixture_id}")
    spec.write_text("".join(after_spec))
    code.write_text("".join(after_code))
    changed.append(("docs/specs/01-core.md", before_spec, after_spec))
    changed.append(("src/widget.py", before_code, after_code))
    rows: list[str] = []
    for path, before, after in changed:
        if before == after:
            continue
        rows.extend(
            difflib.unified_diff(
                before,
                after,
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
            )
        )
    return "".join(rows).encode()


def _detail(obligation_id: str) -> dict[str, object]:
    return {
        "obligation_id": obligation_id,
        "kind": "section",
        "path": "docs/specs/01-core.md",
        "start_line": 3,
        "end_line": 5,
        "title": "Bootstrap",
        "intent_state": "identified",
        "alignment_state": "complete",
        "disposition": "evaluate",
        "obligation_rung": "active",
        "gate_state": "executable",
        "required_roles": ["implementation"],
        "evidence_counts": {"implementation": 1, "test": 0, "binding_test": 0},
        "candidate_counts": {
            "declared": 1,
            "partially_declared": 0,
            "untraced": 0,
            "conflicted": 0,
        },
        "blocking_reasons": [],
        "next_actions": ["RUN_CURRENT_ANALYSIS"],
    }


def _phase_a_result(root: Path, plan: AlignmentEvalPlan) -> Path:
    tasks_by_fixture: dict[str, dict[str, object]] = {}
    for fixture in plan._phase_a.fixtures:
        tree_path, tree_hash = _write_json(
            root, f"trees/a-{fixture.fixture_id}.json", _tree(fixture.tree.root)
        )
        incomplete = fixture.initial_state in {"partial", "untraced", "skipped"}
        initial_target = (
            "list"
            if incomplete or fixture.initial_state == "no_intent"
            else cast(str, fixture.task_obligation_id)
        )
        initial_argv, initial_output, initial_hash = _run_obligation(
            fixture.tree.root,
            root,
            f"outputs/a-{fixture.fixture_id}-initial.json",
            initial_target,
        )
        observations: list[dict[str, object]] = [
            {
                "ordinal": 1,
                "argv": initial_argv,
                "source_revision_ordinal": None,
                "source_tree_manifest_path": tree_path,
                "source_tree_manifest_sha256": tree_hash,
                "output_path": initial_output,
                "output_sha256": initial_hash,
            }
        ]
        revisions: list[dict[str, object]] = []
        changed_paths: list[str] = []
        changed_lines = 0
        if incomplete:
            revised = root / f"work/phase-a-{fixture.fixture_id}"
            diff = _phase_a_diff(fixture.tree.root, fixture.fixture_id, revised)
            diff_path = root / f"diffs/a-{fixture.fixture_id}.diff"
            diff_path.parent.mkdir(parents=True, exist_ok=True)
            diff_path.write_bytes(diff)
            revised_tree_path, revised_tree_hash = _write_json(
                root,
                f"trees/a-{fixture.fixture_id}-revised.json",
                _tree(revised),
            )
            revisions.append(
                {
                    "ordinal": 1,
                    "diff_path": diff_path.relative_to(root).as_posix(),
                    "diff_sha256": "sha256:" + hashlib.sha256(diff).hexdigest(),
                    "result_tree_manifest_path": revised_tree_path,
                    "result_tree_manifest_sha256": revised_tree_hash,
                    "observed_trace_declarations": [],
                }
            )
            final_argv, final_output, final_hash = _run_obligation(
                revised,
                root,
                f"outputs/a-{fixture.fixture_id}-final.json",
                cast(str, fixture.task_obligation_id),
            )
            observations.append(
                {
                    "ordinal": 2,
                    "argv": final_argv,
                    "source_revision_ordinal": 1,
                    "source_tree_manifest_path": revised_tree_path,
                    "source_tree_manifest_sha256": revised_tree_hash,
                    "output_path": final_output,
                    "output_sha256": final_hash,
                }
            )
            changed_paths, changed_lines = _delta_stats(fixture.tree.root, revised)
        tasks_by_fixture[fixture.fixture_id] = {
            "fixture_id": fixture.fixture_id,
            "human_accepted_candidate_ids": [],
            "bootstrap_outcome": fixture.expected_bootstrap_outcome,
            "elapsed_milliseconds": 1,
            "backstitch_call_count": len(observations),
            "reviewed_diff_attempt_count": len(revisions),
            "review_round_count": 1,
            "changed_source_paths": changed_paths,
            "changed_source_line_count": changed_lines,
            "source_revisions": revisions,
            "backstitch_calls": [
                {
                    "ordinal": index,
                    "argv": observation["argv"],
                    "source_revision_ordinal": observation["source_revision_ordinal"],
                }
                for index, observation in enumerate(observations, start=1)
            ],
            "cli_observations": observations,
        }
    sessions = []
    for index in range(2):
        sessions.append(
            {
                "session_id": f"phase-a-{index + 1}",
                "participant_kind": "agent",
                "participant_identity_sha256": "sha256:" + str(index + 4) * 64,
                "public_help_only": True,
                "tasks": [tasks_by_fixture[item] for item in plan.phase_a_fixture_ids],
                "authority_answers": [
                    {"proposition": proposition, "answer": True}
                    for proposition in PROPOSITIONS
                ],
            }
        )
    metrics = {
        "bootstrap_task_count": 10,
        "bootstrap_success_count": 10,
        "authority_session_count": 2,
        "authority_session_pass_count": 2,
        "bootstrap_completion_rate": 1.0,
        "authority_comprehension_rate": 1.0,
    }
    checks = [
        {
            "name": "minimum_bootstrap_completion_rate",
            "comparator": ">=",
            "threshold": 1.0,
            "observed": 1.0,
            "passed": True,
        },
        {
            "name": "minimum_authority_comprehension_rate",
            "comparator": ">=",
            "threshold": 1.0,
            "observed": 1.0,
            "passed": True,
        },
    ]
    result = {
        "schema_version": 2,
        "artifact": "backstitch-alignment-dogfood-result",
        "phase": "A",
        "phase_qualification_sha256": plan.phase_a_qualification_sha256,
        "prior_phase_result_sha256": None,
        "tested_distribution_sha256": plan.tested_distribution_sha256,
        "guide_sha256": plan.guide_sha256,
        "skill_sha256": plan.skill_sha256,
        "sessions": sessions,
        "candidate_runs": [],
        "metrics": metrics,
        "checks": checks,
        "passed": True,
        "failure_reasons": [],
    }
    path = root / "phase-a-result.json"
    path.write_bytes(_canonical(result))
    return path


def _accepted_diff(fixture_root: Path, revised: Path) -> tuple[bytes, Path]:
    shutil.copytree(fixture_root, revised)
    spec = revised / "docs/specs/01-core.md"
    before_spec = spec.read_text().splitlines(keepends=True)
    after_spec = before_spec + [
        "\n",
        "_Implementation mapping_:\n",
        "\n",
        "- `src/candidates.py::untraced_candidate`\n",
    ]
    spec.write_text("".join(after_spec))
    code = revised / "src/candidates.py"
    before_code = code.read_text().splitlines(keepends=True)
    after_code = [
        "def untraced_candidate() -> int:\n",
        '    """Spec: docs/specs/01-core.md [CAND-1]"""\n',
        "    return 1\n",
    ]
    code.write_text("".join(after_code))
    diff = list(
        difflib.unified_diff(
            before_spec,
            after_spec,
            fromfile="a/docs/specs/01-core.md",
            tofile="b/docs/specs/01-core.md",
        )
    )
    diff += list(
        difflib.unified_diff(
            before_code,
            after_code,
            fromfile="a/src/candidates.py",
            tofile="b/src/candidates.py",
        )
    )
    return "".join(diff).encode(), revised


def _phase_b_result(root: Path, plan: AlignmentEvalPlan, prior_path: Path) -> Path:
    prior_hash = "sha256:" + hashlib.sha256(prior_path.read_bytes()).hexdigest()
    task_rows: dict[str, dict[str, object]] = {}
    runs: list[dict[str, object]] = []
    eligible_count = 0
    captured_eligible_count = 0
    surfaced_count = 0
    trace_correct_count = 0
    irrelevant_count = 0
    critical_count = 0
    captured_critical_count = 0
    for fixture in plan._phase_b.fixtures:
        tree_path, tree_hash = _write_json(
            root, f"trees/b-{fixture.fixture_id}.json", _tree(fixture.tree.root)
        )
        artifact = fixture.candidate_artifact
        assert artifact is not None
        candidates = artifact["candidates"]
        assert isinstance(candidates, list)
        gold_by_candidate = {
            item["candidate_id"]: item for item in fixture.gold_candidates
        }
        eligible_count += sum(
            item["disposition_label"] in {"accepted", "rejected"}
            for item in fixture.gold_candidates
        )
        critical_count += sum(item["critical"] for item in fixture.gold_candidates)
        surfaced_count += len(candidates)
        captured_eligible_count += sum(
            gold_by_candidate[candidate["candidate_id"]]["disposition_label"]
            in {"accepted", "rejected"}
            for candidate in candidates
        )
        trace_correct_count += sum(
            candidate["trace_state"]
            == gold_by_candidate[candidate["candidate_id"]]["trace_state"]
            for candidate in candidates
        )
        captured_critical_count += sum(
            gold_by_candidate[candidate["candidate_id"]]["critical"]
            for candidate in candidates
        )
        irrelevant_count += sum(
            gold_by_candidate[candidate["candidate_id"]]["disposition_label"]
            == "irrelevant"
            for candidate in candidates
        )
        output_argv, output_path, output_hash = _run_obligation(
            fixture.tree.root,
            root,
            f"outputs/b-{fixture.fixture_id}.json",
            cast(str, fixture.task_obligation_id),
            find_evidence=True,
        )
        envelope = json.loads((root / output_path).read_text())
        assert envelope["snapshot"] == artifact["snapshot"]
        assert envelope["result"] == {
            "obligation_id": fixture.task_obligation_id,
            "candidates": candidates,
            "next_cursor": None,
        }
        projections = [
            {
                "candidate_id": candidate["candidate_id"],
                "candidate_kind": candidate["candidate_kind"],
                "path": candidate["path"],
                "start_line": candidate["start_line"],
                "end_line": candidate["end_line"],
                "trace_state": candidate["trace_state"],
                "matched_gold_id": gold_by_candidate[candidate["candidate_id"]][
                    "gold_id"
                ],
            }
            for candidate in candidates
        ]
        runs.append(
            {
                "fixture_id": fixture.fixture_id,
                "obligation_id": fixture.task_obligation_id,
                "source_tree_manifest_path": tree_path,
                "source_tree_manifest_sha256": tree_hash,
                "output_path": output_path,
                "output_sha256": output_hash,
                "candidates": projections,
            }
        )
        revisions: list[dict[str, object]] = []
        changed_paths: list[str] = []
        changed_lines = 0
        if fixture.first_diff_required:
            diff, revised = _accepted_diff(
                fixture.tree.root, root / "work/revised-accepted"
            )
            diff_path = f"diffs/{fixture.fixture_id}.diff"
            (root / "diffs").mkdir(exist_ok=True)
            (root / diff_path).write_bytes(diff)
            diff_hash = "sha256:" + hashlib.sha256(diff).hexdigest()
            revised_tree_path, revised_tree_hash = _write_json(
                root, f"trees/b-{fixture.fixture_id}-revised.json", _tree(revised)
            )
            revisions = [
                {
                    "ordinal": 1,
                    "diff_path": diff_path,
                    "diff_sha256": diff_hash,
                    "result_tree_manifest_path": revised_tree_path,
                    "result_tree_manifest_sha256": revised_tree_hash,
                    "observed_trace_declarations": list(
                        fixture.required_trace_declarations
                    ),
                }
            ]
            changed_paths, changed_lines = _delta_stats(fixture.tree.root, revised)
        task_rows[fixture.fixture_id] = {
            "fixture_id": fixture.fixture_id,
            "human_accepted_candidate_ids": sorted(
                cast(str, candidate["candidate_id"])
                for candidate in fixture.gold_candidates
                if candidate["disposition_label"] == "accepted"
            ),
            "bootstrap_outcome": None,
            "elapsed_milliseconds": 1,
            "backstitch_call_count": 1,
            "reviewed_diff_attempt_count": len(revisions),
            "review_round_count": 1,
            "changed_source_paths": changed_paths,
            "changed_source_line_count": changed_lines,
            "source_revisions": revisions,
            "backstitch_calls": [
                {
                    "ordinal": 1,
                    "argv": output_argv,
                    "source_revision_ordinal": None,
                }
            ],
            "cli_observations": [
                {
                    "ordinal": 1,
                    "argv": output_argv,
                    "source_revision_ordinal": None,
                    "source_tree_manifest_path": tree_path,
                    "source_tree_manifest_sha256": tree_hash,
                    "output_path": output_path,
                    "output_sha256": output_hash,
                }
            ],
        }
    sessions = [
        {
            "session_id": f"phase-b-{index + 1}",
            "participant_kind": "agent",
            "participant_identity_sha256": "sha256:" + str(index + 6) * 64,
            "public_help_only": True,
            "tasks": [task_rows[item] for item in plan.phase_b_fixture_ids],
            "authority_answers": [],
        }
        for index in range(2)
    ]
    candidate_capture_rate = captured_eligible_count / eligible_count
    trace_state_precision = trace_correct_count / surfaced_count
    irrelevant_candidate_rate = irrelevant_count / surfaced_count
    all_critical = captured_critical_count == critical_count
    metrics = {
        "eligible_gold_candidate_count": eligible_count,
        "captured_eligible_gold_candidate_count": captured_eligible_count,
        "captured_trace_state_correct_count": trace_correct_count,
        "surfaced_candidate_count": surfaced_count,
        "irrelevant_candidate_count": irrelevant_count,
        "first_diff_required_count": 2,
        "first_diff_correct_count": 2,
        "critical_candidate_count": critical_count,
        "critical_candidate_captured_count": captured_critical_count,
        "candidate_capture_rate": candidate_capture_rate,
        "trace_state_precision": trace_state_precision,
        "irrelevant_candidate_rate": irrelevant_candidate_rate,
        "first_diff_correct_rate": 1.0,
        "all_critical_candidates_captured": all_critical,
    }
    check_inputs = (
        (
            "minimum_candidate_capture_rate",
            ">=",
            0.9,
            candidate_capture_rate,
        ),
        (
            "minimum_trace_state_precision",
            ">=",
            1.0,
            trace_state_precision,
        ),
        (
            "maximum_irrelevant_candidate_rate",
            "<=",
            0.2,
            irrelevant_candidate_rate,
        ),
        ("minimum_first_diff_correct_rate", ">=", 1.0, 1.0),
        ("require_all_critical_candidates", "true", True, all_critical),
    )
    checks = []
    for name, comparator, threshold, observed in check_inputs:
        if comparator == ">=":
            passed = cast(float, observed) >= cast(float, threshold)
        elif comparator == "<=":
            passed = cast(float, observed) <= cast(float, threshold)
        else:
            passed = observed is True and threshold is True
        checks.append(
            {
                "name": name,
                "comparator": comparator,
                "threshold": threshold,
                "observed": observed,
                "passed": passed,
            }
        )
    passed = all(cast(bool, check["passed"]) for check in checks)
    result = {
        "schema_version": 2,
        "artifact": "backstitch-alignment-dogfood-result",
        "phase": "B",
        "phase_qualification_sha256": plan.phase_b_qualification_sha256,
        "prior_phase_result_sha256": prior_hash,
        "tested_distribution_sha256": plan.tested_distribution_sha256,
        "guide_sha256": plan.guide_sha256,
        "skill_sha256": plan.skill_sha256,
        "sessions": sessions,
        "candidate_runs": runs,
        "metrics": metrics,
        "checks": checks,
        "passed": passed,
        "failure_reasons": [
            cast(str, check["name"]) for check in checks if not check["passed"]
        ],
    }
    path = root / "phase-b-result.json"
    path.write_bytes(_canonical(result))
    return path


def test_phase_a_and_b_results_recompute_from_closed_artifacts(tmp_path: Path) -> None:
    plan = load_alignment_eval_plan(CORPUS)
    result_root = tmp_path / "results"
    result_root.mkdir()
    phase_a = _phase_a_result(result_root, plan)
    assert load_alignment_eval_result(CORPUS, phase_a).passed

    phase_b = _phase_b_result(result_root, plan, phase_a)
    loaded = load_alignment_eval_result(
        CORPUS, phase_b, prior_phase_result_path=phase_a
    )
    assert not loaded.passed
    assert json.loads(phase_b.read_text())["failure_reasons"] == [
        "minimum_candidate_capture_rate",
        "require_all_critical_candidates",
    ]
    assert loaded.metrics["eligible_gold_candidate_count"] == 62
    assert loaded.metrics["captured_eligible_gold_candidate_count"] == 49
    assert loaded.metrics["candidate_capture_rate"] == 49 / 62
    assert loaded.metrics["critical_candidate_count"] == 30
    assert loaded.metrics["critical_candidate_captured_count"] == 23
    assert loaded.metrics["surfaced_candidate_count"] == 50
    assert loaded.metrics["captured_trace_state_correct_count"] == 50
    assert loaded.metrics["irrelevant_candidate_count"] == 1


def test_phase_b_binds_human_accepted_projection_as_task_input(
    tmp_path: Path,
) -> None:
    plan = load_alignment_eval_plan(CORPUS)
    root = tmp_path / "results"
    root.mkdir()
    phase_a = _phase_a_result(root, plan)
    phase_b = _phase_b_result(root, plan, phase_a)
    row = json.loads(phase_b.read_text())
    task = row["sessions"][0]["tasks"][0]
    assert task["fixture_id"] == "accepted-implementation"
    assert len(task["human_accepted_candidate_ids"]) == 1

    task["human_accepted_candidate_ids"] = []
    row["metrics"]["first_diff_correct_count"] = 1
    row["metrics"]["first_diff_correct_rate"] = 0.5
    row["checks"][3]["observed"] = 0.5
    row["checks"][3]["passed"] = False
    row["passed"] = False
    row["failure_reasons"] = [
        "INVALID_OBSERVATION",
        "minimum_candidate_capture_rate",
        "minimum_first_diff_correct_rate",
        "require_all_critical_candidates",
    ]
    phase_b.write_bytes(_canonical(row))

    loaded = load_alignment_eval_result(
        CORPUS, phase_b, prior_phase_result_path=phase_a
    )
    assert not loaded.passed


def test_phase_a_result_survives_valid_phase_b_only_protocol_change(
    tmp_path: Path,
) -> None:
    manifest = _copy_corpus(tmp_path)
    plan = load_alignment_eval_plan(manifest)
    root = tmp_path / "results"
    root.mkdir()
    phase_a = _phase_a_result(root, plan)

    top = json.loads(manifest.read_text())
    protocol = manifest.parent / top["phase_b_reviewer_protocol_path"]
    protocol.write_bytes(protocol.read_bytes() + b"\nPhase B clarification.\n")
    top["phase_b_reviewer_protocol_sha256"] = (
        "sha256:" + hashlib.sha256(protocol.read_bytes()).hexdigest()
    )
    manifest.write_bytes(_canonical(top))

    assert load_alignment_eval_result(manifest, phase_a).passed


def _mark_one_phase_a_task_invalid(result: dict[str, Any]) -> None:
    result["metrics"]["bootstrap_success_count"] = 9
    result["metrics"]["bootstrap_completion_rate"] = 0.9
    result["checks"][0]["observed"] = 0.9
    result["checks"][0]["passed"] = False
    result["passed"] = False
    result["failure_reasons"] = [
        "INVALID_OBSERVATION",
        "minimum_bootstrap_completion_rate",
    ]


def test_phase_a_records_auxiliary_calls_separately_from_proof_observations(
    tmp_path: Path,
) -> None:
    plan = load_alignment_eval_plan(CORPUS)
    root = tmp_path / "results"
    root.mkdir()
    phase_a = _phase_a_result(root, plan)
    row = json.loads(phase_a.read_text())
    task = row["sessions"][0]["tasks"][0]
    task["backstitch_calls"].append(
        {
            "ordinal": 2,
            "argv": [
                "backstitch",
                "obligation",
                "docs/specs/01-core.md#BOOT-1",
                "--summarize-evidence",
                "--repo-root",
                ".",
            ],
            "source_revision_ordinal": None,
        }
    )
    task["backstitch_calls"].append(
        {
            "ordinal": 3,
            "argv": [
                "backstitch",
                "check",
                "--repo-root",
                ".",
                "--show-suppressions",
            ],
            "source_revision_ordinal": None,
        }
    )
    task["backstitch_call_count"] = 3
    phase_a.write_bytes(_canonical(row))

    loaded = load_alignment_eval_result(CORPUS, phase_a)

    assert loaded.passed
    assert len(task["cli_observations"]) == 1


def test_phase_a_rejects_call_count_or_proof_not_bound_to_call_log(
    tmp_path: Path,
) -> None:
    plan = load_alignment_eval_plan(CORPUS)
    root = tmp_path / "results"
    root.mkdir()
    root_two = tmp_path / "results-two"
    root_two.mkdir()
    phase_a = _phase_a_result(root_two, plan)
    row = json.loads(phase_a.read_text())
    task = row["sessions"][0]["tasks"][0]
    task["backstitch_call_count"] = 2
    _mark_one_phase_a_task_invalid(row)
    phase_a.write_bytes(_canonical(row))
    assert not load_alignment_eval_result(CORPUS, phase_a).passed

    phase_a = _phase_a_result(root, plan)
    row = json.loads(phase_a.read_text())
    task = row["sessions"][0]["tasks"][0]
    task["backstitch_calls"][0]["argv"] = [
        "backstitch",
        "check",
        "--repo-root",
        ".",
    ]
    _mark_one_phase_a_task_invalid(row)
    phase_a.write_bytes(_canonical(row))
    assert not load_alignment_eval_result(CORPUS, phase_a).passed


@pytest.mark.parametrize(
    "mutation",
    [
        "ordinal",
        "revision",
        "command",
        "root",
        "format",
    ],
)
def test_phase_a_rejects_malformed_task_call_log(tmp_path: Path, mutation: str) -> None:
    plan = load_alignment_eval_plan(CORPUS)
    root = tmp_path / "results"
    root.mkdir()
    phase_a = _phase_a_result(root, plan)
    row = json.loads(phase_a.read_text())
    call = row["sessions"][0]["tasks"][0]["backstitch_calls"][0]
    if mutation == "ordinal":
        call["ordinal"] = 2
    elif mutation == "revision":
        call["source_revision_ordinal"] = 1
    elif mutation == "command":
        call["argv"] = ["backstitch", "semantic", "--repo-root", "."]
    elif mutation == "root":
        call["argv"] = ["backstitch", "obligation", "list"]
    else:
        call["argv"] = [
            "backstitch",
            "obligation",
            "list",
            "--repo-root",
            ".",
            "--format",
            "yaml",
        ]
    _mark_one_phase_a_task_invalid(row)
    phase_a.write_bytes(_canonical(row))

    assert not load_alignment_eval_result(CORPUS, phase_a).passed


def test_phase_b_independent_trace_label_can_fail_precision_without_invalidating(
    tmp_path: Path,
) -> None:
    manifest = _copy_corpus(tmp_path)
    phase = json.loads((manifest.parent / "phase-b/fixtures.json").read_text())
    fixture = next(
        row
        for row in phase["fixtures"]
        if row["fixture_id"] == "implementation-definitions"
    )
    gold = next(
        row
        for row in fixture["gold_candidates"]
        if row["gold_id"] == "implementation-definition-declared-contradicts"
    )
    gold["trace_state"] = "untraced"
    _rehash_phase_b(manifest, phase)
    plan = load_alignment_eval_plan(manifest)
    root = tmp_path / "trace-results"
    root.mkdir()
    phase_a = _phase_a_result(root, plan)
    phase_b = _phase_b_result(root, plan, phase_a)

    result = json.loads(phase_b.read_text())
    assert result["failure_reasons"] == [
        "minimum_candidate_capture_rate",
        "minimum_trace_state_precision",
        "require_all_critical_candidates",
    ]
    loaded = load_alignment_eval_result(
        manifest, phase_b, prior_phase_result_path=phase_a
    )
    assert not loaded.passed
    assert cast(float, loaded.metrics["trace_state_precision"]) < 1.0


def test_phase_b_absent_eligible_gold_can_fail_capture_without_invalidating(
    tmp_path: Path,
) -> None:
    manifest = _copy_corpus(tmp_path)
    phase = json.loads((manifest.parent / "phase-b/fixtures.json").read_text())
    fixture = next(
        row
        for row in phase["fixtures"]
        if row["fixture_id"] == "implementation-definitions"
    )
    fixture_root = manifest.parent / "phase-b" / fixture["fixture_path"]
    for index in range(7):
        path = f"src/omitted_{index}.py"
        source = (
            f"def reviewed_snippet_{index}() -> int:\n    return {index}\n"
        ).encode()
        (fixture_root / path).write_bytes(source)
        locator = f"python-definition:reviewed_snippet_{index}:function:0"
        identity = {
            "candidate_identity_version": 1,
            "candidate_kind": "implementation_definition",
            "path": path,
            "structural_locator": locator,
        }
        fixture["gold_candidates"].append(
            {
                "gold_id": f"independent-absent-candidate-{index}",
                "candidate_id": "candidate:sha256:"
                + hashlib.sha256(_canonical(identity)).hexdigest(),
                "candidate_kind": "implementation_definition",
                "path": path,
                "start_line": 1,
                "end_line": 2,
                "structural_locator": locator,
                "receipt": {
                    "receipt_version": 1,
                    "path": path,
                    "structural_locator": locator,
                    "start_line": 1,
                    "end_line": 2,
                    "raw_sha256": hashlib.sha256(source).hexdigest(),
                },
                "trace_state": "untraced",
                "disposition_label": "rejected",
                "critical": False,
            }
        )
    fixture["gold_candidates"].sort(key=lambda row: row["gold_id"])
    _refresh_phase_b_fixture(manifest, phase, fixture)
    plan = load_alignment_eval_plan(manifest)
    root = tmp_path / "capture-results"
    root.mkdir()
    phase_a = _phase_a_result(root, plan)
    phase_b = _phase_b_result(root, plan, phase_a)

    result = json.loads(phase_b.read_text())
    assert result["failure_reasons"] == [
        "minimum_candidate_capture_rate",
        "require_all_critical_candidates",
    ]
    loaded = load_alignment_eval_result(
        manifest, phase_b, prior_phase_result_path=phase_a
    )
    assert not loaded.passed
    assert cast(float, loaded.metrics["candidate_capture_rate"]) < 0.9


def test_phase_b_absent_critical_gold_can_fail_critical_capture_cleanly(
    tmp_path: Path,
) -> None:
    manifest = _copy_corpus(tmp_path)
    phase = json.loads((manifest.parent / "phase-b/fixtures.json").read_text())
    fixture = next(
        row for row in phase["fixtures"] if row["fixture_id"] == "static-references"
    )
    gold = next(
        row
        for row in fixture["gold_candidates"]
        if row["gold_id"] == "implementation-definition-untraced-d0213ac482c5"
    )
    gold["critical"] = True
    _rehash_phase_b(manifest, phase)
    plan = load_alignment_eval_plan(manifest)
    root = tmp_path / "critical-results"
    root.mkdir()
    phase_a = _phase_a_result(root, plan)
    phase_b = _phase_b_result(root, plan, phase_a)

    result = json.loads(phase_b.read_text())
    assert result["failure_reasons"] == [
        "minimum_candidate_capture_rate",
        "require_all_critical_candidates",
    ]
    loaded = load_alignment_eval_result(
        manifest, phase_b, prior_phase_result_path=phase_a
    )
    assert not loaded.passed
    assert loaded.metrics["all_critical_candidates_captured"] is False


def test_revision_declaration_projection_uses_production_invariant_parsers(
    tmp_path: Path,
) -> None:
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "docs/specs/README.md").write_text("# Specs\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src/worker.py").write_text(
        'def worker() -> int:\n    """Invariant: [INV.WORK.1] Worker is stable."""\n'
        "    return 1\n"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_worker.py").write_text(
        'def test_worker() -> None:\n    """Tests-invariant: [INV.WORK.1]"""\n'
        "    assert True\n"
    )
    profile = ProfileConfig(
        name="backstitch-style-v1",
        spec_roots=("docs/specs",),
        plan_roots=(),
        code_roots=("src", "tests"),
        test_roots=("tests",),
        planned_spec_globs=(),
        exploratory_spec_globs=(),
        meta_spec_globs=(),
    )

    _tree_rows, files = _fixture_snapshot(tmp_path, "test declaration projection")
    tree = _FixtureTree(root=tmp_path, files=files, profile=profile)
    settings = resolve_config(tmp_path, environment={})
    _snapshot_value, candidates, _settings, _report = _production_fixture_view(
        tree,
        "invariant::INV.WORK.1",
        settings,
    )
    gold = tuple(
        {
            "candidate_id": candidate.candidate_id,
            "candidate_kind": candidate.candidate_kind,
            "path": candidate.path,
            "structural_locator": candidate.structural_locator,
            "gold_id": (
                "implementation"
                if candidate.path == "src/worker.py"
                else "binding-test"
            ),
        }
        for candidate in candidates
    )

    assert _declaration_projection(
        tmp_path,
        profile,
        settings,
        obligation_id="invariant::INV.WORK.1",
        gold_candidates=gold,
    ) == (
        {
            "form": "spec_mapping",
            "target_id": "INV.WORK.1",
            "evidence_role": "implementation",
            "gold_id": "implementation",
        },
        {
            "form": "binding_test",
            "target_id": "INV.WORK.1",
            "evidence_role": "binding_test",
            "gold_id": "binding-test",
        },
    )


def test_invariant_required_declarations_use_owning_forms(tmp_path: Path) -> None:
    profile = ProfileConfig(
        name="backstitch-style-v1",
        spec_roots=("docs/specs",),
        plan_roots=(),
        code_roots=("src", "tests"),
        test_roots=("tests",),
        planned_spec_globs=(),
        exploratory_spec_globs=(),
        meta_spec_globs=(),
    )
    tree = _FixtureTree(root=tmp_path, files={}, profile=profile)
    gold = (
        {
            "gold_id": "implementation",
            "candidate_kind": "implementation_definition",
            "path": "src/worker.py",
            "trace_state": "untraced",
            "disposition_label": "accepted",
        },
        {
            "gold_id": "binding-test",
            "candidate_kind": "test_definition",
            "path": "tests/test_worker.py",
            "trace_state": "partially_declared",
            "disposition_label": "accepted",
        },
    )

    assert _required_declaration_set(
        tree,
        "invariant::INV.WORK.1",
        gold,
    ) == (
        {
            "form": "spec_mapping",
            "target_id": "INV.WORK.1",
            "evidence_role": "implementation",
            "gold_id": "implementation",
        },
        {
            "form": "binding_test",
            "target_id": "INV.WORK.1",
            "evidence_role": "binding_test",
            "gold_id": "binding-test",
        },
    )


def test_first_diff_requires_executable_revised_obligation(tmp_path: Path) -> None:
    plan = load_alignment_eval_plan(CORPUS)
    fixture = plan._phase_b.fixtures[0]
    _initial_diff, revised = _accepted_diff(
        fixture.tree.root, tmp_path / "revised-skipped"
    )
    spec = revised / "docs/specs/01-core.md"
    spec.write_text(
        spec.read_text().replace(
            "## Candidate behavior [CAND-1]",
            "## Candidate behavior [CAND-1] "
            '<!-- backstitch: skip-obligation [CAND-1] "Externally owned." -->',
        )
    )
    diff_rows: list[str] = []
    for relative in ("docs/specs/01-core.md", "src/candidates.py"):
        before = (fixture.tree.root / relative).read_text().splitlines(keepends=True)
        after = (revised / relative).read_text().splitlines(keepends=True)
        diff_rows.extend(
            difflib.unified_diff(
                before,
                after,
                fromfile=f"a/{relative}",
                tofile=f"b/{relative}",
            )
        )
    result_root = tmp_path / "artifacts"
    result_root.mkdir()
    tree_path, tree_hash = _write_json(result_root, "revised-tree.json", _tree(revised))
    (
        _root,
        temporary,
        declarations,
        _paths,
        _changed_lines,
        executable,
        _settings,
    ) = _apply_revision(
        fixture,
        "".join(diff_rows).encode(),
        result_root,
        tree_path,
        tree_hash,
        "skipped first diff",
        obligation_id=cast(str, fixture.task_obligation_id),
        gold_candidates=fixture.gold_candidates,
        original_settings=resolve_config(fixture.tree.root, environment={}),
    )
    try:
        assert declarations == fixture.required_trace_declarations
        assert not executable
    finally:
        temporary.cleanup()


def test_result_rejects_participant_identity_reuse(tmp_path: Path) -> None:
    plan = load_alignment_eval_plan(CORPUS)
    root = tmp_path / "results"
    root.mkdir()
    phase_a = _phase_a_result(root, plan)
    row = json.loads(phase_a.read_text())
    row["sessions"][1]["participant_identity_sha256"] = row["sessions"][0][
        "participant_identity_sha256"
    ]
    phase_a.write_bytes(_canonical(row))

    with pytest.raises(AlignmentEvalError, match="participant hashes"):
        load_alignment_eval_result(CORPUS, phase_a)


def test_result_rejects_recomputed_metric_drift(tmp_path: Path) -> None:
    plan = load_alignment_eval_plan(CORPUS)
    root = tmp_path / "results"
    root.mkdir()
    phase_a = _phase_a_result(root, plan)
    row = json.loads(phase_a.read_text())
    row["metrics"]["bootstrap_success_count"] = 9
    phase_a.write_bytes(_canonical(row))

    with pytest.raises(AlignmentEvalError, match="metrics does not recompute"):
        load_alignment_eval_result(CORPUS, phase_a)


def test_phase_a_raw_authority_answer_drives_comprehension_failure(
    tmp_path: Path,
) -> None:
    plan = load_alignment_eval_plan(CORPUS)
    root = tmp_path / "results"
    root.mkdir()
    phase_a = _phase_a_result(root, plan)
    row = json.loads(phase_a.read_text())
    row["sessions"][0]["authority_answers"][0]["answer"] = False
    row["metrics"]["authority_session_pass_count"] = 1
    row["metrics"]["authority_comprehension_rate"] = 0.5
    authority_check = next(
        check
        for check in row["checks"]
        if check["name"] == "minimum_authority_comprehension_rate"
    )
    authority_check["observed"] = 0.5
    authority_check["passed"] = False
    row["passed"] = False
    row["failure_reasons"] = ["minimum_authority_comprehension_rate"]
    phase_a.write_bytes(_canonical(row))

    loaded = load_alignment_eval_result(CORPUS, phase_a)

    assert not loaded.passed
    assert loaded.metrics["authority_session_pass_count"] == 1
    assert loaded.metrics["authority_comprehension_rate"] == 0.5


@pytest.mark.parametrize("mutation", ["old-key", "proposition", "order", "type"])
def test_phase_a_rejects_malformed_raw_authority_answers(
    tmp_path: Path, mutation: str
) -> None:
    plan = load_alignment_eval_plan(CORPUS)
    root = tmp_path / "results"
    root.mkdir()
    phase_a = _phase_a_result(root, plan)
    row = json.loads(phase_a.read_text())
    answers = row["sessions"][0]["authority_answers"]
    if mutation == "old-key":
        answers[0]["correct"] = answers[0].pop("answer")
    elif mutation == "proposition":
        answers[0]["proposition"] = "the recorder decides correctness"
    elif mutation == "order":
        answers[0], answers[1] = answers[1], answers[0]
    else:
        answers[0]["answer"] = "true"
    phase_a.write_bytes(_canonical(row))

    with pytest.raises(
        AlignmentEvalError, match="invalid keys|do not match the frozen rubric"
    ):
        load_alignment_eval_result(CORPUS, phase_a)


@pytest.mark.parametrize(
    "field",
    ["tested_distribution_sha256", "guide_sha256", "skill_sha256"],
)
def test_result_rejects_product_identity_drift(tmp_path: Path, field: str) -> None:
    plan = load_alignment_eval_plan(CORPUS)
    root = tmp_path / "results"
    root.mkdir()
    phase_a = _phase_a_result(root, plan)
    row = json.loads(phase_a.read_text())
    row[field] = "sha256:" + "0" * 64
    phase_a.write_bytes(_canonical(row))

    with pytest.raises(AlignmentEvalError, match="product identities"):
        load_alignment_eval_result(CORPUS, phase_a)


def test_phase_b_rejects_prior_result_hash_drift(tmp_path: Path) -> None:
    plan = load_alignment_eval_plan(CORPUS)
    root = tmp_path / "results"
    root.mkdir()
    phase_a = _phase_a_result(root, plan)
    phase_b = _phase_b_result(root, plan, phase_a)
    row = json.loads(phase_b.read_text())
    row["prior_phase_result_sha256"] = "sha256:" + "0" * 64
    phase_b.write_bytes(_canonical(row))

    with pytest.raises(AlignmentEvalError, match="prior result hash"):
        load_alignment_eval_result(CORPUS, phase_b, prior_phase_result_path=phase_a)


def test_result_rejects_cli_output_mutation_after_recording(tmp_path: Path) -> None:
    plan = load_alignment_eval_plan(CORPUS)
    root = tmp_path / "results"
    root.mkdir()
    phase_a = _phase_a_result(root, plan)
    row = json.loads(phase_a.read_text())
    output = root / row["sessions"][0]["tasks"][0]["cli_observations"][0]["output_path"]
    output.write_bytes(output.read_bytes() + b" ")

    with pytest.raises(
        AlignmentEvalError,
        match="canonical JSON|hash does not match|metrics does not recompute",
    ):
        load_alignment_eval_result(CORPUS, phase_a)


def test_phase_b_rejects_parser_derived_declaration_drift(tmp_path: Path) -> None:
    plan = load_alignment_eval_plan(CORPUS)
    root = tmp_path / "results"
    root.mkdir()
    phase_a = _phase_a_result(root, plan)
    phase_b = _phase_b_result(root, plan, phase_a)
    row = json.loads(phase_b.read_text())
    first_revision = row["sessions"][0]["tasks"][0]["source_revisions"][0]
    first_revision["observed_trace_declarations"] = first_revision[
        "observed_trace_declarations"
    ][:1]
    phase_b.write_bytes(_canonical(row))

    with pytest.raises(
        AlignmentEvalError,
        match="do not recompute|metrics does not recompute",
    ):
        load_alignment_eval_result(CORPUS, phase_b, prior_phase_result_path=phase_a)


def test_phase_b_rejects_diff_mutation_after_recording(tmp_path: Path) -> None:
    plan = load_alignment_eval_plan(CORPUS)
    root = tmp_path / "results"
    root.mkdir()
    phase_a = _phase_a_result(root, plan)
    phase_b = _phase_b_result(root, plan, phase_a)
    row = json.loads(phase_b.read_text())
    revision = row["sessions"][0]["tasks"][0]["source_revisions"][0]
    diff = root / revision["diff_path"]
    diff.write_bytes(diff.read_bytes() + b"\n")

    with pytest.raises(
        AlignmentEvalError,
        match="hash does not match|metrics does not recompute",
    ):
        load_alignment_eval_result(CORPUS, phase_b, prior_phase_result_path=phase_a)


def test_phase_b_rejects_result_tree_manifest_mutation(tmp_path: Path) -> None:
    plan = load_alignment_eval_plan(CORPUS)
    root = tmp_path / "results"
    root.mkdir()
    phase_a = _phase_a_result(root, plan)
    phase_b = _phase_b_result(root, plan, phase_a)
    row = json.loads(phase_b.read_text())
    revision = row["sessions"][0]["tasks"][0]["source_revisions"][0]
    tree_path = root / revision["result_tree_manifest_path"]
    tree = json.loads(tree_path.read_text())
    tree["files"][0]["byte_count"] += 1
    tree_path.write_bytes(_canonical(tree))

    with pytest.raises(
        AlignmentEvalError,
        match="hash does not match|metrics does not recompute",
    ):
        load_alignment_eval_result(CORPUS, phase_b, prior_phase_result_path=phase_a)


def test_phase_b_reconstructs_candidate_rows_from_cli_output(tmp_path: Path) -> None:
    plan = load_alignment_eval_plan(CORPUS)
    root = tmp_path / "results"
    root.mkdir()
    phase_a = _phase_a_result(root, plan)
    phase_b = _phase_b_result(root, plan, phase_a)
    row = json.loads(phase_b.read_text())
    run = row["candidate_runs"][0]
    output_path = root / run["output_path"]
    output = json.loads(output_path.read_text())
    output["result"]["candidates"][0]["candidate_id"] += ":changed"
    raw = _canonical(output)
    output_path.write_bytes(raw)
    changed_hash = "sha256:" + hashlib.sha256(raw).hexdigest()
    run["output_sha256"] = changed_hash
    for session in row["sessions"]:
        observation = session["tasks"][0]["cli_observations"][0]
        observation["output_sha256"] = changed_hash
    phase_b.write_bytes(_canonical(row))

    with pytest.raises(
        AlignmentEvalError,
        match="do not reconstruct|metrics does not recompute",
    ):
        load_alignment_eval_result(CORPUS, phase_b, prior_phase_result_path=phase_a)


def test_phase_b_rejects_synthetic_full_candidate_envelope(tmp_path: Path) -> None:
    plan = load_alignment_eval_plan(CORPUS)
    root = tmp_path / "results"
    root.mkdir()
    phase_a = _phase_a_result(root, plan)
    phase_b = _phase_b_result(root, plan, phase_a)
    row = json.loads(phase_b.read_text())
    run = row["candidate_runs"][0]
    output_path = root / run["output_path"]
    output = json.loads(output_path.read_text())
    output["guidance"] = _guidance("SYNTHETIC_NOT_PUBLIC_OUTPUT")
    raw = _canonical(output)
    output_path.write_bytes(raw)
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    run["output_sha256"] = digest
    for session in row["sessions"]:
        session["tasks"][0]["cli_observations"][0]["output_sha256"] = digest
    phase_b.write_bytes(_canonical(row))

    with pytest.raises(
        AlignmentEvalError, match="metrics does not recompute|byte-exact public command"
    ):
        load_alignment_eval_result(
            CORPUS,
            phase_b,
            prior_phase_result_path=phase_a,
        )


def test_phase_b_zero_surfaced_denominators_are_null_and_fail(tmp_path: Path) -> None:
    plan = load_alignment_eval_plan(CORPUS)
    root = tmp_path / "results"
    root.mkdir()
    phase_a = _phase_a_result(root, plan)
    phase_b = _phase_b_result(root, plan, phase_a)
    row = json.loads(phase_b.read_text())
    hashes: dict[str, str] = {}
    for run in row["candidate_runs"]:
        output_path = root / run["output_path"]
        output = json.loads(output_path.read_text())
        output["result"]["candidates"] = []
        raw = _canonical(output)
        output_path.write_bytes(raw)
        digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        hashes[run["output_path"]] = digest
        run["output_sha256"] = digest
        run["candidates"] = []
    for session in row["sessions"]:
        for task in session["tasks"]:
            observation = task["cli_observations"][0]
            observation["output_sha256"] = hashes[observation["output_path"]]
    row["metrics"].update(
        {
            "captured_eligible_gold_candidate_count": 0,
            "captured_trace_state_correct_count": 0,
            "surfaced_candidate_count": 0,
            "irrelevant_candidate_count": 0,
            "critical_candidate_captured_count": 0,
            "candidate_capture_rate": 0.0,
            "trace_state_precision": None,
            "irrelevant_candidate_rate": None,
            "first_diff_correct_count": 0,
            "first_diff_correct_rate": 0.0,
            "all_critical_candidates_captured": False,
        }
    )
    observed = (0.0, None, None, 0.0, False)
    passed = (False, False, False, False, False)
    for check, check_observed, check_passed in zip(
        row["checks"], observed, passed, strict=True
    ):
        check["observed"] = check_observed
        check["passed"] = check_passed
    row["passed"] = False
    row["failure_reasons"] = [
        "INVALID_OBSERVATION",
        "minimum_candidate_capture_rate",
        "minimum_trace_state_precision",
        "maximum_irrelevant_candidate_rate",
        "minimum_first_diff_correct_rate",
        "require_all_critical_candidates",
    ]
    phase_b.write_bytes(_canonical(row))

    loaded = load_alignment_eval_result(
        CORPUS, phase_b, prior_phase_result_path=phase_a
    )
    assert not loaded.passed
    assert loaded.metrics["trace_state_precision"] is None
    assert loaded.metrics["irrelevant_candidate_rate"] is None


def test_result_rejects_non_nfc_artifact_path(tmp_path: Path) -> None:
    plan = load_alignment_eval_plan(CORPUS)
    root = tmp_path / "results"
    root.mkdir()
    phase_a = _phase_a_result(root, plan)
    row = json.loads(phase_a.read_text())
    row["sessions"][0]["tasks"][0]["cli_observations"][0]["output_path"] = (
        "outputs/cafe\u0301.json"
    )
    phase_a.write_bytes(_canonical(row))

    with pytest.raises(
        AlignmentEvalError,
        match="Unicode NFC|metrics does not recompute",
    ):
        load_alignment_eval_result(CORPUS, phase_a)


def test_phase_a_records_unrevised_incomplete_task_as_invalid_observation(
    tmp_path: Path,
) -> None:
    """Partial/untraced/skipped authoring tasks fire INVALID_OBSERVATION."""

    plan = load_alignment_eval_plan(CORPUS)
    root = tmp_path / "results"
    root.mkdir()
    phase_a = _phase_a_result(root, plan)
    row = json.loads(phase_a.read_text())
    task = row["sessions"][0]["tasks"][2]
    task["backstitch_call_count"] = 1
    task["reviewed_diff_attempt_count"] = 0
    task["changed_source_paths"] = []
    task["changed_source_line_count"] = 0
    task["source_revisions"] = []
    task["backstitch_calls"] = task["backstitch_calls"][:1]
    task["cli_observations"] = task["cli_observations"][:1]
    row["metrics"]["bootstrap_success_count"] = 9
    row["metrics"]["bootstrap_completion_rate"] = 0.9
    row["checks"][0]["observed"] = 0.9
    row["checks"][0]["passed"] = False
    row["passed"] = False
    row["failure_reasons"] = [
        "INVALID_OBSERVATION",
        "minimum_bootstrap_completion_rate",
    ]
    phase_a.write_bytes(_canonical(row))

    loaded = load_alignment_eval_result(CORPUS, phase_a)
    assert not loaded.passed
    assert loaded.metrics["bootstrap_success_count"] == 9


def test_phase_b_task_must_bind_the_canonical_find_evidence_run(
    tmp_path: Path,
) -> None:
    plan = load_alignment_eval_plan(CORPUS)
    root = tmp_path / "results"
    root.mkdir()
    phase_a = _phase_a_result(root, plan)
    phase_b = _phase_b_result(root, plan, phase_a)
    row = json.loads(phase_b.read_text())
    task = row["sessions"][0]["tasks"][0]
    fixture = plan._phase_b.fixtures[0]
    output_argv, output_path, output_hash = _run_obligation(
        fixture.tree.root,
        root,
        "outputs/arbitrary-get.json",
        cast(str, fixture.task_obligation_id),
    )
    task["backstitch_calls"][0]["argv"] = output_argv
    task["cli_observations"][0]["argv"] = output_argv
    task["cli_observations"][0]["output_path"] = output_path
    task["cli_observations"][0]["output_sha256"] = output_hash
    phase_b.write_bytes(_canonical(row))

    preamble = _load_alignment_result_preamble(
        plan,
        phase_b,
        prior_phase_result_path=phase_a,
        require_current_product=False,
    )
    evaluator = _AlignmentSessionEvaluator(preamble)
    evaluator.validate_candidate_runs()
    with pytest.raises(
        AlignmentEvalError,
        match="final observation must be obligation.find_evidence",
    ):
        _TaskValidator(
            result_base=preamble.result_base,
            fixture=fixture,
            value=task,
            phase="B",
            context="candidate-run task",
            candidate_run=evaluator.candidate_bindings[fixture.fixture_id],
        ).validate()


def test_phase_b_task_paths_bind_the_canonical_candidate_run(tmp_path: Path) -> None:
    plan = load_alignment_eval_plan(CORPUS)
    root = tmp_path / "results"
    root.mkdir()
    phase_a = _phase_a_result(root, plan)
    phase_b = _phase_b_result(root, plan, phase_a)
    row = json.loads(phase_b.read_text())
    observation = row["sessions"][0]["tasks"][1]["cli_observations"][0]
    original = root / observation["source_tree_manifest_path"]
    duplicate = root / "trees/duplicate-source-tree.json"
    duplicate.write_bytes(original.read_bytes())
    observation["source_tree_manifest_path"] = duplicate.relative_to(root).as_posix()
    row["passed"] = False
    row["failure_reasons"] = [
        "INVALID_OBSERVATION",
        "minimum_candidate_capture_rate",
        "require_all_critical_candidates",
    ]
    phase_b.write_bytes(_canonical(row))

    loaded = load_alignment_eval_result(
        CORPUS, phase_b, prior_phase_result_path=phase_a
    )
    assert not loaded.passed
    assert row["failure_reasons"] == [
        "INVALID_OBSERVATION",
        "minimum_candidate_capture_rate",
        "require_all_critical_candidates",
    ]


def test_phase_b_task_rejects_extra_public_observations(tmp_path: Path) -> None:
    plan = load_alignment_eval_plan(CORPUS)
    root = tmp_path / "results"
    root.mkdir()
    phase_a = _phase_a_result(root, plan)
    phase_b = _phase_b_result(root, plan, phase_a)
    row = json.loads(phase_b.read_text())
    task = row["sessions"][0]["tasks"][0]
    duplicate = dict(task["cli_observations"][0])
    duplicate["ordinal"] = 2
    task["cli_observations"].append(duplicate)
    duplicate_call = dict(task["backstitch_calls"][0])
    duplicate_call["ordinal"] = 2
    task["backstitch_calls"].append(duplicate_call)
    task["backstitch_call_count"] = 2
    phase_b.write_bytes(_canonical(row))

    with pytest.raises(
        AlignmentEvalError,
        match="exactly one candidate run|metrics does not recompute",
    ):
        load_alignment_eval_result(
            CORPUS,
            phase_b,
            prior_phase_result_path=phase_a,
        )


def test_phase_b_candidate_run_checks_obligation_identity(tmp_path: Path) -> None:
    plan = load_alignment_eval_plan(CORPUS)
    root = tmp_path / "results"
    root.mkdir()
    phase_a = _phase_a_result(root, plan)
    phase_b = _phase_b_result(root, plan, phase_a)
    row = json.loads(phase_b.read_text())
    run = row["candidate_runs"][0]
    output_path = root / run["output_path"]
    output = json.loads(output_path.read_text())
    output["result"]["obligation_id"] = "docs/specs/01-core.md#WRONG"
    raw = _canonical(output)
    output_path.write_bytes(raw)
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    run["output_sha256"] = digest
    for session in row["sessions"]:
        observation = session["tasks"][0]["cli_observations"][0]
        observation["output_sha256"] = digest
    phase_b.write_bytes(_canonical(row))

    with pytest.raises(
        AlignmentEvalError,
        match="obligation_id|candidate run|metrics does not recompute",
    ):
        load_alignment_eval_result(CORPUS, phase_b, prior_phase_result_path=phase_a)


def test_phase_b_rejects_duplicate_surfaced_candidate_coordinates(
    tmp_path: Path,
) -> None:
    plan = load_alignment_eval_plan(CORPUS)
    root = tmp_path / "results"
    root.mkdir()
    phase_a = _phase_a_result(root, plan)
    phase_b = _phase_b_result(root, plan, phase_a)
    row = json.loads(phase_b.read_text())
    run = row["candidate_runs"][0]
    output_path = root / run["output_path"]
    output = json.loads(output_path.read_text())
    duplicate = dict(output["result"]["candidates"][0])
    duplicate["candidate_id"] += ":duplicate"
    output["result"]["candidates"].insert(1, duplicate)
    projection = dict(run["candidates"][0])
    projection["candidate_id"] = duplicate["candidate_id"]
    run["candidates"].insert(1, projection)
    raw = _canonical(output)
    output_path.write_bytes(raw)
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    run["output_sha256"] = digest
    for session in row["sessions"]:
        observation = session["tasks"][0]["cli_observations"][0]
        observation["output_sha256"] = digest
    row["metrics"]["captured_trace_state_correct_count"] += 1
    row["metrics"]["surfaced_candidate_count"] += 1
    phase_b.write_bytes(_canonical(row))

    with pytest.raises(
        AlignmentEvalError,
        match="coordinates|duplicate|metrics does not recompute",
    ):
        load_alignment_eval_result(CORPUS, phase_b, prior_phase_result_path=phase_a)


def test_result_rejects_noncanonical_recorded_argv_and_snapshot(
    tmp_path: Path,
) -> None:
    plan = load_alignment_eval_plan(CORPUS)
    root = tmp_path / "results"
    root.mkdir()
    phase_a = _phase_a_result(root, plan)
    row = json.loads(phase_a.read_text())
    observation = row["sessions"][0]["tasks"][0]["cli_observations"][0]
    observation["argv"] = ["anything"]
    output_path = root / observation["output_path"]
    output = json.loads(output_path.read_text())
    output["snapshot"] = {
        "snapshot_hash": "not-the-bound-tree",
        "file_count": 0,
        "byte_count": 0,
        "unreadable_count": 0,
    }
    raw = _canonical(output)
    output_path.write_bytes(raw)
    observation["output_sha256"] = "sha256:" + hashlib.sha256(raw).hexdigest()
    phase_a.write_bytes(_canonical(row))

    with pytest.raises(
        AlignmentEvalError,
        match="argv|snapshot|public command|metrics does not recompute",
    ):
        load_alignment_eval_result(CORPUS, phase_a)
