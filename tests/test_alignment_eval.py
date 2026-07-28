"""Closed product-evaluation preregistration validation.

Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-10.2]
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest

from backstitch.alignment_eval import (
    AlignmentEvalError,
    _authoritative_product_identities,
    _candidate_projection,
    _fixture_snapshot,
    load_alignment_eval_plan,
)
from backstitch.canonical import canonical_json_bytes, lf_slice

CORPUS = Path(__file__).parent / "product_eval/alignment-bootstrap/manifest.json"


def _copy_corpus(tmp_path: Path) -> Path:
    root = tmp_path / "alignment-bootstrap"
    shutil.copytree(CORPUS.parent, root)
    return root / "manifest.json"


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _rehash_phase(manifest: Path, phase_name: str) -> dict[str, object]:
    phase_path = manifest.parent / phase_name / "fixtures.json"
    phase = cast(dict[str, object], json.loads(phase_path.read_text(encoding="utf-8")))
    phase_path.write_bytes(_canonical(phase))
    top = json.loads(manifest.read_text(encoding="utf-8"))
    key = phase_name.replace("-", "_") + "_fixture_manifest_sha256"
    top[key] = "sha256:" + hashlib.sha256(_canonical(phase)).hexdigest()
    manifest.write_bytes(_canonical(top))
    return phase


def _phase_fixtures(phase: dict[str, object]) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], phase["fixtures"])


def _gold_candidates(fixture: dict[str, object]) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], fixture["gold_candidates"])


def test_committed_alignment_eval_plan_is_closed_and_content_addressed() -> None:
    plan = load_alignment_eval_plan(CORPUS)
    committed = json.loads(CORPUS.read_text(encoding="utf-8"))

    assert plan.manifest_sha256 == (
        "sha256:" + hashlib.sha256(_canonical(committed)).hexdigest()
    )
    assert plan.phase_a_qualification_sha256 != plan.manifest_sha256
    assert plan.phase_b_qualification_sha256 != plan.manifest_sha256
    assert plan.phase_a_qualification_sha256 != plan.phase_b_qualification_sha256
    assert plan.phase_a_fixture_ids == (
        "complete",
        "no-intent",
        "partial",
        "skipped",
        "untraced",
    )
    assert plan.phase_b_fixture_ids == (
        "accepted-implementation",
        "implementation-definitions",
        "report-issue-conflicted",
        "report-issue-partial",
        "static-references",
        "test-definitions",
        "unresolved-references",
    )
    assert plan.phase_a_sessions == 2
    assert plan.phase_b_sessions == 2
    assert {
        "tested_distribution_sha256": plan.tested_distribution_sha256,
        "guide_sha256": plan.guide_sha256,
        "skill_sha256": plan.skill_sha256,
    } == {
        key: committed[key]
        for key in (
            "tested_distribution_sha256",
            "guide_sha256",
            "skill_sha256",
        )
    }
    assert len(plan.critical_candidate_ids) > 0
    assert all(fixture.candidate_artifact for fixture in plan._phase_b.fixtures)
    assert any(
        gold["disposition_label"] == "accepted" and gold["trace_state"] == "declared"
        for fixture in plan._phase_b.fixtures
        for gold in fixture.gold_candidates
    )
    assert committed["thresholds"] == {
        "minimum_bootstrap_completion_rate": 1.0,
        "minimum_authority_comprehension_rate": 1.0,
        "minimum_candidate_capture_rate": 0.9,
        "minimum_trace_state_precision": 1.0,
        "maximum_irrelevant_candidate_rate": 0.2,
        "minimum_first_diff_correct_rate": 1.0,
        "require_all_critical_candidates": True,
    }
    assert (
        committed["tested_distribution_sha256"]
        != (_authoritative_product_identities()["tested_distribution_sha256"])
    )


def test_phase_qualification_identities_isolate_later_stage_inputs(
    tmp_path: Path,
) -> None:
    original = load_alignment_eval_plan(CORPUS)
    manifest = _copy_corpus(tmp_path)
    top = json.loads(manifest.read_text(encoding="utf-8"))

    phase_b_protocol = manifest.parent / top["phase_b_reviewer_protocol_path"]
    phase_b_protocol.write_bytes(phase_b_protocol.read_bytes() + b"\nPhase B note.\n")
    top["phase_b_reviewer_protocol_sha256"] = (
        "sha256:" + hashlib.sha256(phase_b_protocol.read_bytes()).hexdigest()
    )
    manifest.write_bytes(_canonical(top))

    changed = load_alignment_eval_plan(manifest)
    assert changed.phase_a_qualification_sha256 == original.phase_a_qualification_sha256
    assert changed.phase_b_qualification_sha256 != original.phase_b_qualification_sha256
    assert changed.manifest_sha256 != original.manifest_sha256


def test_phase_b_session_count_does_not_change_phase_a_identity(
    tmp_path: Path,
) -> None:
    original = load_alignment_eval_plan(CORPUS)
    manifest = _copy_corpus(tmp_path)
    top = json.loads(manifest.read_text(encoding="utf-8"))
    top["phase_b_sessions"] = 3
    manifest.write_bytes(_canonical(top))

    changed = load_alignment_eval_plan(manifest)
    assert changed.phase_a_qualification_sha256 == original.phase_a_qualification_sha256
    assert changed.phase_b_qualification_sha256 != original.phase_b_qualification_sha256


def test_valid_phase_b_fixture_change_does_not_change_phase_a_identity(
    tmp_path: Path,
) -> None:
    original = load_alignment_eval_plan(CORPUS)
    manifest = _copy_corpus(tmp_path)
    phase_path = manifest.parent / "phase-b/fixtures.json"
    phase = json.loads(phase_path.read_text(encoding="utf-8"))
    phase["fixtures"][0]["fixture_id"] = "accepted-implementation-v2"
    phase_raw = _canonical(phase)
    phase_path.write_bytes(phase_raw)
    top = json.loads(manifest.read_text(encoding="utf-8"))
    top["phase_b_fixture_manifest_sha256"] = (
        "sha256:" + hashlib.sha256(phase_raw).hexdigest()
    )
    top["critical_candidate_ids"] = sorted(
        f"{fixture['fixture_id']}#{gold['gold_id']}"
        for fixture in phase["fixtures"]
        for gold in fixture["gold_candidates"]
        if gold["critical"]
    )
    manifest.write_bytes(_canonical(top))

    changed = load_alignment_eval_plan(manifest)
    assert changed.phase_a_qualification_sha256 == original.phase_a_qualification_sha256
    assert changed.phase_b_qualification_sha256 != original.phase_b_qualification_sha256


def _minimal_product_tree(root: Path) -> None:
    (root / "backstitch/guides").mkdir(parents=True)
    (root / "skills/backstitch-alignment").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname='example'\n")
    (root / "uv.lock").write_text("version = 1\n")
    (root / "backstitch/__init__.py").write_text('__version__ = "1"\n')
    (root / "backstitch/guides/alignment.md").write_text("# Guide\n")
    (root / "skills/backstitch-alignment/SKILL.md").write_text("# Skill\n")


def test_authoritative_product_identities_are_clone_stable_and_content_bound(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _minimal_product_tree(first)
    shutil.copytree(first, second)

    baseline = _authoritative_product_identities(first)
    assert _authoritative_product_identities(second) == baseline

    (second / "backstitch/__pycache__").mkdir()
    (second / "backstitch/__pycache__/ignored.pyc").write_bytes(b"cache")
    assert _authoritative_product_identities(second) == baseline

    (second / "backstitch/__init__.py").write_text('__version__ = "2"\n')
    changed = _authoritative_product_identities(second)
    assert (
        changed["tested_distribution_sha256"] != baseline["tested_distribution_sha256"]
    )
    assert changed["guide_sha256"] == baseline["guide_sha256"]
    assert changed["skill_sha256"] == baseline["skill_sha256"]

    shutil.copytree(first, tmp_path / "guide")
    guide_root = tmp_path / "guide"
    (guide_root / "backstitch/guides/alignment.md").write_text("# Revised guide\n")
    guide_changed = _authoritative_product_identities(guide_root)
    assert (
        guide_changed["tested_distribution_sha256"]
        != baseline["tested_distribution_sha256"]
    )
    assert guide_changed["guide_sha256"] != baseline["guide_sha256"]
    assert guide_changed["skill_sha256"] == baseline["skill_sha256"]

    shutil.copytree(first, tmp_path / "mode")
    mode_root = tmp_path / "mode"
    package_input = mode_root / "backstitch/__init__.py"
    package_input.chmod(package_input.stat().st_mode | 0o100)
    mode_changed = _authoritative_product_identities(mode_root)
    assert (
        mode_changed["tested_distribution_sha256"]
        != baseline["tested_distribution_sha256"]
    )
    assert mode_changed["guide_sha256"] == baseline["guide_sha256"]
    assert mode_changed["skill_sha256"] == baseline["skill_sha256"]

    shutil.copytree(first, tmp_path / "skill")
    skill_root = tmp_path / "skill"
    (skill_root / "skills/backstitch-alignment/SKILL.md").write_text(
        "# Revised skill\n"
    )
    skill_changed = _authoritative_product_identities(skill_root)
    assert (
        skill_changed["tested_distribution_sha256"]
        == baseline["tested_distribution_sha256"]
    )
    assert skill_changed["guide_sha256"] == baseline["guide_sha256"]
    assert skill_changed["skill_sha256"] != baseline["skill_sha256"]


@pytest.mark.parametrize(
    "cache_name",
    ["__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache"],
)
def test_authoritative_product_identity_excludes_each_cache_directory(
    tmp_path: Path, cache_name: str
) -> None:
    _minimal_product_tree(tmp_path)
    baseline = _authoritative_product_identities(tmp_path)
    cache = tmp_path / "backstitch" / cache_name
    cache.mkdir()
    (cache / "ignored.bin").write_bytes(b"cache")
    assert _authoritative_product_identities(tmp_path) == baseline


@pytest.mark.parametrize("suffix", [".pyc", ".pyo"])
def test_authoritative_product_identity_excludes_each_cache_suffix(
    tmp_path: Path, suffix: str
) -> None:
    _minimal_product_tree(tmp_path)
    baseline = _authoritative_product_identities(tmp_path)
    (tmp_path / "backstitch" / f"ignored{suffix}").write_bytes(b"cache")
    assert _authoritative_product_identities(tmp_path) == baseline


@pytest.mark.parametrize(
    "relative",
    [
        "pyproject.toml",
        "uv.lock",
        "backstitch/__init__.py",
        "backstitch/guides/alignment.md",
        "skills/backstitch-alignment/SKILL.md",
    ],
)
@pytest.mark.parametrize("kind", ["symlink", "nonregular"])
def test_authoritative_product_identities_reject_nonregular_inputs(
    tmp_path: Path, kind: str, relative: str
) -> None:
    _minimal_product_tree(tmp_path)
    target = tmp_path / relative
    target.unlink()
    if kind == "symlink":
        target.symlink_to(tmp_path / "pyproject.toml")
    else:
        os.mkfifo(target)

    with pytest.raises(AlignmentEvalError, match="symlink|non-regular"):
        _authoritative_product_identities(tmp_path)


@pytest.mark.parametrize(
    "relative",
    [
        "pyproject.toml",
        "uv.lock",
        "backstitch/guides/alignment.md",
        "skills/backstitch-alignment/SKILL.md",
    ],
)
def test_authoritative_product_identities_reject_missing_required_inputs(
    tmp_path: Path, relative: str
) -> None:
    _minimal_product_tree(tmp_path)
    (tmp_path / relative).unlink()

    with pytest.raises(AlignmentEvalError, match="cannot read|cannot inspect"):
        _authoritative_product_identities(tmp_path)


@pytest.mark.parametrize(
    ("fixture_id", "required_code"),
    [
        ("complete", None),
        ("no-intent", None),
        ("partial", "CODE_BACKLINK_RECIPROCAL_MISSING"),
        ("skipped", "OBLIGATION_SKIPPED"),
        ("untraced", "SPEC_SECTION_UNMAPPED"),
    ],
)
def test_phase_a_frozen_config_drives_public_cli_source_state(
    fixture_id: str, required_code: str | None
) -> None:
    fixture = CORPUS.parent / "phase-a/fixtures" / fixture_id
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "backstitch",
            "check",
            "--repo-root",
            str(fixture),
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert "Traceback" not in result.stderr
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    codes = {issue["code"] for issue in report["issues"]}
    assert "SCAN_ROOT_MISSING" not in codes
    if required_code is not None:
        assert required_code in codes


def test_phase_a_initial_state_uses_only_exact_task_readiness(tmp_path: Path) -> None:
    manifest = _copy_corpus(tmp_path)
    fixture_root = manifest.parent / "phase-a/fixtures/complete"
    (fixture_root / "docs/specs/02-unrelated.md").write_text(
        "# Unrelated\n\n## Unmapped behavior [OTHER-1]\n\nUnrelated intent.\n"
    )
    rows, _files = _fixture_snapshot(fixture_root, "complete fixture")
    tree = {
        "schema_version": 1,
        "artifact": "backstitch-eval-fixture-tree",
        "files": rows,
    }
    tree_raw = _canonical(tree)
    (manifest.parent / "phase-a/trees/complete.json").write_bytes(tree_raw)
    phase_path = manifest.parent / "phase-a/fixtures.json"
    phase = json.loads(phase_path.read_text())
    fixture = next(row for row in phase["fixtures"] if row["fixture_id"] == "complete")
    fixture["tree_manifest_sha256"] = "sha256:" + hashlib.sha256(tree_raw).hexdigest()
    phase_path.write_bytes(_canonical(phase))
    _rehash_phase(manifest, "phase-a")

    plan = load_alignment_eval_plan(manifest)
    complete = next(
        row for row in plan._phase_a.fixtures if row.fixture_id == "complete"
    )
    assert complete.initial_state == "complete"


def test_alignment_eval_plan_rejects_missing_fixture_file(tmp_path: Path) -> None:
    manifest = _copy_corpus(tmp_path)
    missing = manifest.parent / "phase-a/fixtures/complete/src/widget.py"
    missing.unlink()

    with pytest.raises(AlignmentEvalError, match="fixture tree does not match"):
        load_alignment_eval_plan(manifest)


def test_alignment_eval_plan_rejects_extra_fixture_file(tmp_path: Path) -> None:
    manifest = _copy_corpus(tmp_path)
    extra = manifest.parent / "phase-a/fixtures/complete/src/extra.py"
    extra.write_text("EXTRA = True\n", encoding="utf-8")

    with pytest.raises(AlignmentEvalError, match="fixture tree does not match"):
        load_alignment_eval_plan(manifest)


def test_alignment_eval_plan_rejects_changed_fixture_bytes(tmp_path: Path) -> None:
    manifest = _copy_corpus(tmp_path)
    changed = manifest.parent / "phase-a/fixtures/complete/src/widget.py"
    changed.write_text("def widget() -> int:\n    return 2\n", encoding="utf-8")

    with pytest.raises(AlignmentEvalError, match="fixture tree does not match"):
        load_alignment_eval_plan(manifest)


def test_alignment_eval_plan_rejects_fixture_symlink(tmp_path: Path) -> None:
    manifest = _copy_corpus(tmp_path)
    linked = manifest.parent / "phase-a/fixtures/complete/src/widget.py"
    linked.unlink()
    linked.symlink_to(manifest.parent / "phase-a/fixtures/partial/src/widget.py")

    with pytest.raises(AlignmentEvalError, match="contains symlink"):
        load_alignment_eval_plan(manifest)


def test_alignment_eval_plan_rejects_referenced_manifest_hash_drift(
    tmp_path: Path,
) -> None:
    manifest = _copy_corpus(tmp_path)
    row = json.loads(manifest.read_text(encoding="utf-8"))
    row["phase_a_fixture_manifest_sha256"] = "sha256:" + "0" * 64
    manifest.write_bytes(_canonical(row))

    with pytest.raises(AlignmentEvalError, match="manifest hash does not match"):
        load_alignment_eval_plan(manifest)


def test_alignment_eval_plan_rejects_phase_manifest_byte_only_drift(
    tmp_path: Path,
) -> None:
    manifest = _copy_corpus(tmp_path)
    phase = manifest.parent / "phase-a/fixtures.json"
    phase.write_bytes(phase.read_bytes() + b"\n")

    with pytest.raises(
        AlignmentEvalError, match="fixture manifest must use exact canonical JSON"
    ):
        load_alignment_eval_plan(manifest)


def test_alignment_eval_plan_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    manifest = _copy_corpus(tmp_path)
    raw = manifest.read_bytes().rstrip(b"\n")
    manifest.write_bytes(raw[:-1] + b',"artifact":"duplicate"}')

    with pytest.raises(AlignmentEvalError, match="duplicate key 'artifact'"):
        load_alignment_eval_plan(manifest)


def test_alignment_eval_plan_rejects_noncanonical_manifest_bytes(
    tmp_path: Path,
) -> None:
    manifest = _copy_corpus(tmp_path)
    row = json.loads(manifest.read_text(encoding="utf-8"))
    manifest.write_text(json.dumps(row, indent=2), encoding="utf-8")

    with pytest.raises(AlignmentEvalError, match="canonical JSON bytes"):
        load_alignment_eval_plan(manifest)


def test_alignment_eval_plan_rejects_fixture_tree_manifest_hash_drift(
    tmp_path: Path,
) -> None:
    manifest = _copy_corpus(tmp_path)
    tree_path = manifest.parent / "phase-a/trees/complete.json"
    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    tree["files"][0]["raw_sha256"] = "sha256:" + "0" * 64
    tree_path.write_text(json.dumps(tree), encoding="utf-8")

    with pytest.raises(AlignmentEvalError, match="tree manifest hash does not match"):
        load_alignment_eval_plan(manifest)


def test_alignment_eval_plan_rejects_exact_threshold_drift(
    tmp_path: Path,
) -> None:
    manifest = _copy_corpus(tmp_path)
    row = json.loads(manifest.read_text(encoding="utf-8"))
    row["thresholds"]["minimum_candidate_capture_rate"] = 0.8
    manifest.write_bytes(_canonical(row))

    with pytest.raises(AlignmentEvalError, match="initial thresholds must exactly"):
        load_alignment_eval_plan(manifest)


@pytest.mark.parametrize(
    "field",
    ["tested_distribution_sha256", "guide_sha256", "skill_sha256"],
)
def test_alignment_eval_plan_rejects_authoritative_product_identity_drift(
    tmp_path: Path, field: str
) -> None:
    manifest = _copy_corpus(tmp_path)
    row = json.loads(manifest.read_text(encoding="utf-8"))
    row[field] = "sha256:" + "0" * 64
    manifest.write_bytes(_canonical(row))

    with pytest.raises(AlignmentEvalError, match="authoritative bytes"):
        load_alignment_eval_plan(manifest, require_current_product=True)


def test_alignment_eval_plan_rejects_unknown_nested_gold_key(
    tmp_path: Path,
) -> None:
    manifest = _copy_corpus(tmp_path)
    phase_path = manifest.parent / "phase-b/fixtures.json"
    phase = json.loads(phase_path.read_text(encoding="utf-8"))
    phase["fixtures"][0]["gold_candidates"][0]["unexpected"] = True
    phase_path.write_bytes(_canonical(phase))

    top = json.loads(manifest.read_text(encoding="utf-8"))
    canonical = _canonical(phase)
    top["phase_b_fixture_manifest_sha256"] = (
        "sha256:" + hashlib.sha256(canonical).hexdigest()
    )
    manifest.write_bytes(_canonical(top))

    with pytest.raises(AlignmentEvalError, match=r"gold_candidates\[0\].*invalid keys"):
        load_alignment_eval_plan(manifest)


@pytest.mark.parametrize("phase", ["phase_a", "phase_b"])
def test_alignment_eval_plan_rejects_reviewer_protocol_drift(
    tmp_path: Path, phase: str
) -> None:
    manifest = _copy_corpus(tmp_path)
    top = json.loads(manifest.read_text(encoding="utf-8"))
    protocol = manifest.parent / top[f"{phase}_reviewer_protocol_path"]
    protocol.write_text(
        protocol.read_text(encoding="utf-8") + "\nChanged rubric.\n",
        encoding="utf-8",
    )

    with pytest.raises(AlignmentEvalError, match="reviewer protocol hash"):
        load_alignment_eval_plan(manifest)


def test_alignment_eval_plan_rejects_critical_irrelevant_gold(tmp_path: Path) -> None:
    manifest = _copy_corpus(tmp_path)
    phase_path = manifest.parent / "phase-b/fixtures.json"
    phase = json.loads(phase_path.read_text(encoding="utf-8"))
    phase["fixtures"][0]["gold_candidates"][0]["disposition_label"] = "irrelevant"
    phase_path.write_bytes(_canonical(phase))
    _rehash_phase(manifest, "phase-b")

    with pytest.raises(AlignmentEvalError, match="critical gold cannot be irrelevant"):
        load_alignment_eval_plan(manifest)


def test_alignment_eval_plan_rejects_label_set_drift(tmp_path: Path) -> None:
    manifest = _copy_corpus(tmp_path)
    phase_path = manifest.parent / "phase-b/fixtures.json"
    phase = json.loads(phase_path.read_text(encoding="utf-8"))
    for fixture in phase["fixtures"]:
        for gold in fixture["gold_candidates"]:
            if gold["disposition_label"] == "irrelevant":
                gold["disposition_label"] = "rejected"
    phase_path.write_bytes(_canonical(phase))
    _rehash_phase(manifest, "phase-b")

    with pytest.raises(AlignmentEvalError, match="accepted, rejected, and irrelevant"):
        load_alignment_eval_plan(manifest)


def test_alignment_eval_plan_allows_source_bound_gold_beyond_discovery(
    tmp_path: Path,
) -> None:
    manifest = _copy_corpus(tmp_path)
    plan = load_alignment_eval_plan(manifest)
    absent: list[dict[str, object]] = []
    for fixture in plan._phase_b.fixtures:
        assert fixture.candidate_artifact is not None
        surfaced = {
            row["candidate_id"] for row in fixture.candidate_artifact["candidates"]
        }
        absent.extend(
            gold
            for gold in fixture.gold_candidates
            if gold["candidate_id"] not in surfaced
        )
    assert absent
    assert all(gold["disposition_label"] in {"accepted", "rejected"} for gold in absent)


def test_absent_human_accepted_gold_is_a_capture_miss_not_a_diff_task(
    tmp_path: Path,
) -> None:
    manifest = _copy_corpus(tmp_path)
    phase_path = manifest.parent / "phase-b/fixtures.json"
    phase = json.loads(phase_path.read_text(encoding="utf-8"))
    fixture = next(
        row for row in phase["fixtures"] if row["fixture_id"] == "static-references"
    )
    gold = next(
        row
        for row in fixture["gold_candidates"]
        if row["gold_id"] == "implementation-definition-untraced-824fc83bedfb"
    )
    gold["disposition_label"] = "accepted"
    phase_path.write_bytes(_canonical(phase))
    _rehash_phase(manifest, "phase-b")

    plan = load_alignment_eval_plan(manifest)
    loaded = next(
        row for row in plan._phase_b.fixtures if row.fixture_id == "static-references"
    )
    assert not loaded.first_diff_required
    assert loaded.required_trace_declarations == ()


def test_multiple_surfaced_human_acceptances_require_one_complete_missing_set(
    tmp_path: Path,
) -> None:
    manifest = _copy_corpus(tmp_path)
    phase_path = manifest.parent / "phase-b/fixtures.json"
    phase = json.loads(phase_path.read_text(encoding="utf-8"))
    fixture = next(
        row
        for row in phase["fixtures"]
        if row["fixture_id"] == "implementation-definitions"
    )
    accepted_ids = {
        "implementation-definition-partially-declared-bb7041d2dfa1",
        "implementation-definition-untraced-2ae955ee4d06",
    }
    for gold in fixture["gold_candidates"]:
        if gold["gold_id"] in accepted_ids:
            gold["disposition_label"] = "accepted"
    fixture["first_diff_required"] = True
    fixture["required_trace_declarations"] = [
        {
            "evidence_role": "implementation",
            "form": form,
            "gold_id": gold_id,
            "target_id": "docs/specs/01-core.md#CAND-1",
        }
        for form in ("spec_mapping", "code_backlink")
        for gold_id in sorted(accepted_ids)
        if not (
            form == "code_backlink"
            and gold_id == "implementation-definition-partially-declared-bb7041d2dfa1"
        )
    ]
    phase_path.write_bytes(_canonical(phase))
    _rehash_phase(manifest, "phase-b")

    plan = load_alignment_eval_plan(manifest)
    loaded = next(
        row
        for row in plan._phase_b.fixtures
        if row.fixture_id == "implementation-definitions"
    )
    assert loaded.first_diff_required
    assert len(loaded.required_trace_declarations) == 3


def test_alignment_eval_plan_does_not_copy_expected_trace_state_from_discovery(
    tmp_path: Path,
) -> None:
    manifest = _copy_corpus(tmp_path)
    phase = _rehash_phase(manifest, "phase-b")
    fixture = _phase_fixtures(phase)[1]
    row = next(
        gold
        for gold in _gold_candidates(fixture)
        if gold["disposition_label"] == "rejected" and gold["trace_state"] == "untraced"
    )
    row["trace_state"] = "declared"
    phase_path = manifest.parent / "phase-b/fixtures.json"
    phase_path.write_bytes(_canonical(phase))
    _rehash_phase(manifest, "phase-b")

    load_alignment_eval_plan(manifest)


def test_alignment_eval_plan_rejects_fabricated_absent_gold_locator(
    tmp_path: Path,
) -> None:
    manifest = _copy_corpus(tmp_path)
    phase = _rehash_phase(manifest, "phase-b")
    fixture = next(
        row
        for row in _phase_fixtures(phase)
        if row["fixture_id"] == "static-references"
    )
    gold = next(
        row
        for row in _gold_candidates(fixture)
        if row["gold_id"] == "implementation-definition-untraced-824fc83bedfb"
    )
    locator = "independent-review:fabricated"
    gold["structural_locator"] = locator
    cast(dict[str, object], gold["receipt"])["structural_locator"] = locator
    identity = {
        "candidate_identity_version": 1,
        "candidate_kind": gold["candidate_kind"],
        "path": gold["path"],
        "structural_locator": locator,
    }
    gold["candidate_id"] = (
        "candidate:sha256:" + hashlib.sha256(_canonical(identity)).hexdigest()
    )
    phase_path = manifest.parent / "phase-b/fixtures.json"
    phase_path.write_bytes(_canonical(phase))
    _rehash_phase(manifest, "phase-b")

    with pytest.raises(AlignmentEvalError, match="source-bound production syntax"):
        load_alignment_eval_plan(manifest)


def test_alignment_eval_plan_rejects_one_sided_required_section_declaration(
    tmp_path: Path,
) -> None:
    manifest = _copy_corpus(tmp_path)
    phase = _rehash_phase(manifest, "phase-b")
    fixture = _phase_fixtures(phase)[0]
    required = cast(list[dict[str, object]], fixture["required_trace_declarations"])
    fixture["required_trace_declarations"] = required[:1]
    phase_path = manifest.parent / "phase-b/fixtures.json"
    phase_path.write_bytes(_canonical(phase))
    _rehash_phase(manifest, "phase-b")

    with pytest.raises(AlignmentEvalError, match="exact required declaration set"):
        load_alignment_eval_plan(manifest)


@pytest.mark.parametrize(
    ("mutated_path", "message"),
    [
        ("src/cafe\u0301.py", "Unicode NFC"),
        ("src/\ud800.py", "Unicode surrogate"),
    ],
)
def test_alignment_eval_plan_rejects_noncanonical_unicode_gold_paths(
    tmp_path: Path, mutated_path: str, message: str
) -> None:
    manifest = _copy_corpus(tmp_path)
    phase_path = manifest.parent / "phase-b/fixtures.json"
    phase = json.loads(phase_path.read_text(encoding="utf-8"))
    phase["fixtures"][0]["gold_candidates"][0]["path"] = mutated_path
    phase_path.write_bytes(_canonical(phase))
    _rehash_phase(manifest, "phase-b")

    with pytest.raises(AlignmentEvalError, match=message):
        load_alignment_eval_plan(manifest)


def test_alignment_eval_plan_rejects_normalized_tree_path_collision(
    tmp_path: Path,
) -> None:
    manifest = _copy_corpus(tmp_path)
    tree_path = manifest.parent / "phase-a/trees/complete.json"
    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    first = dict(tree["files"][0])
    first["path"] = "src/caf\u00e9.py"
    second = dict(first)
    second["path"] = "src/cafe\u0301.py"
    tree["files"].extend([first, second])
    tree["files"].sort(key=lambda row: row["path"])
    tree_path.write_bytes(_canonical(tree))

    phase_path = manifest.parent / "phase-a/fixtures.json"
    phase = json.loads(phase_path.read_text(encoding="utf-8"))
    phase["fixtures"][0]["tree_manifest_sha256"] = (
        "sha256:" + hashlib.sha256(_canonical(tree)).hexdigest()
    )
    phase_path.write_bytes(_canonical(phase))
    _rehash_phase(manifest, "phase-a")

    with pytest.raises(AlignmentEvalError, match="normalized path collision"):
        load_alignment_eval_plan(manifest)


def _phase_b_candidate_fixture() -> tuple[Any, dict[str, object]]:
    plan = load_alignment_eval_plan(CORPUS)
    fixture = deepcopy(
        next(row for row in plan._phase_b.fixtures if row.candidate_artifact)
    )
    assert fixture.candidate_artifact is not None
    candidate = deepcopy(fixture.candidate_artifact["candidates"][0])
    return fixture, cast(dict[str, object], candidate)


def test_candidate_projection_rejects_span_past_fixture_line_count() -> None:
    """Slice 7.0 pin: the eval lane must not accept ``lf_slice`` truncation."""

    fixture, candidate = _phase_b_candidate_fixture()
    path = cast(str, candidate["path"])
    start = cast(int, candidate["start_line"])
    candidate["end_line"] = 10_000
    receipt = cast(dict[str, object], candidate["receipt"])
    receipt["end_line"] = 10_000
    receipt["raw_sha256"] = hashlib.sha256(
        lf_slice(fixture.tree.files[path], start, 10_000, policy="clamped")
    ).hexdigest()
    gold = next(
        row
        for row in fixture.gold_candidates
        if row["candidate_id"] == candidate["candidate_id"]
    )
    gold["end_line"] = 10_000
    gold_receipt = cast(dict[str, object], gold["receipt"])
    gold_receipt["end_line"] = 10_000
    gold_receipt["raw_sha256"] = receipt["raw_sha256"]

    with pytest.raises(AlignmentEvalError, match="span exceeds fixture bytes"):
        _candidate_projection(candidate, fixture, "candidate")


def test_candidate_projection_reports_absent_path_as_structured_error() -> None:
    """Slice 7.0 pin: an absent candidate path never leaks ``KeyError``."""

    fixture, candidate = _phase_b_candidate_fixture()
    candidate["path"] = "src/absent.py"
    receipt = cast(dict[str, object], candidate["receipt"])
    receipt["path"] = "src/absent.py"
    identity = {
        "candidate_identity_version": 1,
        "candidate_kind": candidate["candidate_kind"],
        "path": "src/absent.py",
        "structural_locator": candidate["structural_locator"],
    }
    candidate["candidate_id"] = (
        "candidate:sha256:" + hashlib.sha256(canonical_json_bytes(identity)).hexdigest()
    )

    with pytest.raises(AlignmentEvalError, match="path is absent from fixture"):
        _candidate_projection(candidate, fixture, "candidate")
