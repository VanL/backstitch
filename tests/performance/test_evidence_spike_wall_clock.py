"""Sampled wall-clock checks for evidence-spike hardening.

Spec: docs/specs/02-backstitch-core.md [SC-10]
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.performance.wall_clock import (
    MEASURED_RUNS,
    evaluate_wall_clock,
    resolve_wall_clock_baselines,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER_CONTRACT_PATH = REPO_ROOT / "tests/performance/wall-clock-runner-contract.json"
BASELINE_PATH = REPO_ROOT / "tests/performance/wall-clock-baseline.json"
OBSERVED_RUNNER_ENV = "BACKSTITCH_BENCHMARK_RUNNER_IDENTITY_PATH"
COMMAND_TIMEOUT_SECONDS = 30


def _run_command(arguments: tuple[str, ...]) -> float:
    started = time.perf_counter()
    completed = subprocess.run(
        (sys.executable, "-m", "backstitch", *arguments),
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    elapsed = time.perf_counter() - started
    assert completed.returncode == 0, completed.stderr
    return elapsed


def _measurement_report(
    command_id: str,
    samples: tuple[float, ...],
    median: float,
) -> str:
    rendered_samples = ", ".join(f"{sample:.3f}s" for sample in samples)
    return f"{command_id}: samples=[{rendered_samples}], median={median:.3f}s"


def _report_to_terminal(pytestconfig: pytest.Config, message: str) -> None:
    terminal_reporter = pytestconfig.pluginmanager.get_plugin("terminalreporter")
    if terminal_reporter is None:
        print(message, flush=True)
        return
    terminal_reporter.write_line(message)


@pytest.mark.benchmark
@pytest.mark.parametrize(
    ("command_id", "arguments", "catastrophic_ceiling_seconds"),
    (
        ("default-check", ("check", "--repo-root", "."), 3.0),
        ("obligation-list", ("obligation", "list", "--repo-root", "."), 12.0),
    ),
    ids=("default-check", "obligation-list"),
)
def test_self_corpus_command_wall_clock(
    pytestconfig: pytest.Config,
    command_id: str,
    arguments: tuple[str, ...],
    catastrophic_ceiling_seconds: float,
) -> None:
    """Measure the real self-corpus command without inventing comparability."""

    _run_command(arguments)
    samples = tuple(_run_command(arguments) for _ in range(MEASURED_RUNS))
    observed_path_value = os.environ.get(OBSERVED_RUNNER_ENV)
    baseline_resolution = resolve_wall_clock_baselines(
        runner_contract_path=RUNNER_CONTRACT_PATH,
        observed_runner_path=(
            Path(observed_path_value) if observed_path_value is not None else None
        ),
        baseline_path=BASELINE_PATH,
    )
    baseline = baseline_resolution.command_medians_seconds.get(command_id)
    evaluation = evaluate_wall_clock(
        samples,
        baseline_seconds=baseline,
        catastrophic_ceiling_seconds=catastrophic_ceiling_seconds,
    )
    report = _measurement_report(command_id, samples, evaluation.median_seconds)
    qualification = baseline_resolution.reason
    _report_to_terminal(
        pytestconfig,
        f"{report}; status={evaluation.status}; qualification={qualification}",
    )

    if evaluation.status == "fail":
        pytest.fail(f"{report}; reason={evaluation.reason}")
