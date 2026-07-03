from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _load_gate_module() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "scripts"
        / "require_green_workflows.py"
    )
    spec = importlib.util.spec_from_file_location("backstitch_release_gate", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gate = _load_gate_module()


def _run(
    run_id: int,
    *,
    name: str = "CI",
    status: str = "completed",
    conclusion: str | None = "success",
    created_at: str = "2026-07-03T00:00:00Z",
    run_attempt: int = 1,
) -> object:
    return gate.WorkflowRun(
        id=run_id,
        name=name,
        status=status,
        conclusion=conclusion,
        url=f"https://example.invalid/runs/{run_id}",
        created_at=created_at,
        run_attempt=run_attempt,
    )


def test_evaluate_required_workflows_accepts_green_run() -> None:
    check = gate.evaluate_required_workflows([_run(1)], ["CI"])

    assert check.ready is True
    assert [run.id for run in check.passed] == [1]
    assert check.missing == ()
    assert check.pending == ()
    assert check.failed == ()


def test_gate_excludes_current_release_run() -> None:
    check = gate.evaluate_required_workflows(
        [
            _run(1, conclusion="failure", created_at="2026-07-03T00:01:00Z"),
            _run(2, created_at="2026-07-03T00:00:00Z"),
        ],
        ["CI"],
        exclude_run_id=1,
    )

    assert check.ready is True
    assert [run.id for run in check.passed] == [2]


def test_evaluate_required_workflows_reports_missing_pending_and_failed() -> None:
    check = gate.evaluate_required_workflows(
        [
            _run(1, name="CI", status="in_progress", conclusion=None),
            _run(2, name="Lint", conclusion="failure"),
        ],
        ["CI", "Lint", "Packaging"],
    )

    assert check.ready is False
    assert [run.name for run in check.pending] == ["CI"]
    assert [run.name for run in check.failed] == ["Lint"]
    assert check.missing == ("Packaging",)


def test_describe_gate_check_includes_actionable_status() -> None:
    check = gate.evaluate_required_workflows(
        [_run(1, status="in_progress", conclusion=None)],
        ["CI", "Packaging"],
    )

    description = gate.describe_gate_check(check)

    assert "pending: CI [in_progress]" in description
    assert "missing: Packaging" in description


def test_wait_for_required_workflows_raises_on_failed_run() -> None:
    with pytest.raises(RuntimeError, match="required workflow run failed"):
        gate.wait_for_required_workflows(
            fetch_runs=lambda: (_run(1, conclusion="failure"),),
            required_workflows=["CI"],
            exclude_run_id=None,
            timeout_seconds=60,
            missing_timeout_seconds=30,
            poll_interval_seconds=1,
        )
