"""Stable serial wall-clock benchmark policy.

Spec: docs/specs/02-backstitch-core.md [SC-10]
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tests.performance.wall_clock import (
    evaluate_wall_clock,
    resolve_wall_clock_baselines,
)


def _runner_contract() -> dict[str, object]:
    return {
        "schema_version": 1,
        "workflow_path": ".github/workflows/ci.yml",
        "job_id": "benchmark",
        "runs_on": "ubuntu-24.04",
        "runner_image_os": "ubuntu24",
        "runner_image_version": "20260713.1",
        "architecture": "x86_64",
        "cpu_model": "Example CPU",
        "logical_cpu_count": 4,
        "memory_bytes": 17_179_869_184,
        "python_version": "3.12.11",
        "uv_version": "0.8.0",
        "uv_lock_sha256": "a" * 64,
    }


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def _baseline(runner_contract_path: Path) -> dict[str, object]:
    return {
        "schema_version": 1,
        "runner_contract_sha256": hashlib.sha256(
            runner_contract_path.read_bytes()
        ).hexdigest(),
        "measured_runs": 5,
        "allowed_regression_fraction": 0.2,
        "command_medians_seconds": {
            "default-check": 0.5,
            "obligation-list": 2.5,
        },
    }


def test_five_samples_report_the_median_without_unpinned_qualification() -> None:
    result = evaluate_wall_clock(
        (0.4, 0.5, 0.6, 0.7, 4.0),
        baseline_seconds=None,
        catastrophic_ceiling_seconds=3.0,
    )

    assert result.samples_seconds == (0.4, 0.5, 0.6, 0.7, 4.0)
    assert result.median_seconds == pytest.approx(0.6)
    assert result.status == "unavailable"
    assert result.reason == "baseline_unavailable"


@pytest.mark.parametrize(
    ("median", "expected_status", "expected_reason"),
    (
        (0.60, "pass", "within_relative_limit"),
        (0.61, "fail", "relative_regression"),
    ),
)
def test_pinned_baseline_allows_exactly_twenty_percent_regression(
    median: float,
    expected_status: str,
    expected_reason: str,
) -> None:
    result = evaluate_wall_clock(
        (median,) * 5,
        baseline_seconds=0.5,
        catastrophic_ceiling_seconds=3.0,
    )

    assert result.status == expected_status
    assert result.reason == expected_reason


def test_catastrophic_ceiling_fails_without_a_baseline() -> None:
    result = evaluate_wall_clock(
        (3.01,) * 5,
        baseline_seconds=None,
        catastrophic_ceiling_seconds=3.0,
    )

    assert result.status == "fail"
    assert result.reason == "catastrophic_ceiling"


@pytest.mark.parametrize(
    ("samples", "ceiling", "message"),
    (
        ((0.1,) * 4, 3.0, "requires 5 samples"),
        ((0.1, 0.1, 0.1, 0.1, float("nan")), 3.0, "finite and nonnegative"),
        ((0.1,) * 5, 0.0, "ceiling must be finite and positive"),
    ),
)
def test_wall_clock_evaluation_rejects_invalid_measurements(
    samples: tuple[float, ...],
    ceiling: float,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        evaluate_wall_clock(
            samples,
            baseline_seconds=None,
            catastrophic_ceiling_seconds=ceiling,
        )


def test_missing_runner_contract_makes_latency_qualification_unavailable(
    tmp_path: Path,
) -> None:
    resolution = resolve_wall_clock_baselines(
        runner_contract_path=tmp_path / "runner-contract.json",
        observed_runner_path=None,
        baseline_path=tmp_path / "wall-clock-baseline.json",
    )

    assert resolution.status == "unavailable"
    assert resolution.reason == "runner_contract_missing"
    assert resolution.command_medians_seconds == {}


def test_missing_baseline_makes_matching_runner_unavailable(tmp_path: Path) -> None:
    runner_path = tmp_path / "runner-contract.json"
    observed_path = tmp_path / "observed-runner.json"
    contract = _runner_contract()
    _write_json(runner_path, contract)
    _write_json(observed_path, contract)

    resolution = resolve_wall_clock_baselines(
        runner_contract_path=runner_path,
        observed_runner_path=observed_path,
        baseline_path=tmp_path / "wall-clock-baseline.json",
    )

    assert resolution.status == "unavailable"
    assert resolution.reason == "baseline_missing"


def test_matching_runner_and_content_bound_baseline_enable_qualification(
    tmp_path: Path,
) -> None:
    runner_path = tmp_path / "runner-contract.json"
    observed_path = tmp_path / "observed-runner.json"
    baseline_path = tmp_path / "wall-clock-baseline.json"
    contract = _runner_contract()
    _write_json(runner_path, contract)
    _write_json(observed_path, contract)
    _write_json(baseline_path, _baseline(runner_path))

    resolution = resolve_wall_clock_baselines(
        runner_contract_path=runner_path,
        observed_runner_path=observed_path,
        baseline_path=baseline_path,
    )

    assert resolution.status == "available"
    assert resolution.reason == "runner_and_baseline_match"
    assert resolution.command_medians_seconds == {
        "default-check": 0.5,
        "obligation-list": 2.5,
    }


def test_runner_mismatch_keeps_baseline_qualification_unavailable(
    tmp_path: Path,
) -> None:
    runner_path = tmp_path / "runner-contract.json"
    observed_path = tmp_path / "observed-runner.json"
    baseline_path = tmp_path / "wall-clock-baseline.json"
    contract = _runner_contract()
    observed = dict(contract)
    observed["cpu_model"] = "Different CPU"
    _write_json(runner_path, contract)
    _write_json(observed_path, observed)
    _write_json(baseline_path, _baseline(runner_path))

    resolution = resolve_wall_clock_baselines(
        runner_contract_path=runner_path,
        observed_runner_path=observed_path,
        baseline_path=baseline_path,
    )

    assert resolution.status == "unavailable"
    assert resolution.reason == "runtime_identity_mismatch"
    assert resolution.command_medians_seconds == {}


def test_invalid_observed_runner_keeps_qualification_unavailable(
    tmp_path: Path,
) -> None:
    runner_path = tmp_path / "runner-contract.json"
    observed_path = tmp_path / "observed-runner.json"
    baseline_path = tmp_path / "wall-clock-baseline.json"
    _write_json(runner_path, _runner_contract())
    _write_json(observed_path, {})
    _write_json(baseline_path, _baseline(runner_path))

    resolution = resolve_wall_clock_baselines(
        runner_contract_path=runner_path,
        observed_runner_path=observed_path,
        baseline_path=baseline_path,
    )

    assert resolution.status == "unavailable"
    assert resolution.reason == "runtime_identity_invalid"


def test_baseline_for_another_runner_is_unavailable(tmp_path: Path) -> None:
    runner_path = tmp_path / "runner-contract.json"
    observed_path = tmp_path / "observed-runner.json"
    baseline_path = tmp_path / "wall-clock-baseline.json"
    contract = _runner_contract()
    _write_json(runner_path, contract)
    _write_json(observed_path, contract)
    baseline = _baseline(runner_path)
    baseline["runner_contract_sha256"] = "b" * 64
    _write_json(baseline_path, baseline)

    resolution = resolve_wall_clock_baselines(
        runner_contract_path=runner_path,
        observed_runner_path=observed_path,
        baseline_path=baseline_path,
    )

    assert resolution.status == "unavailable"
    assert resolution.reason == "baseline_runner_mismatch"


def test_malformed_committed_baseline_is_fatal(tmp_path: Path) -> None:
    runner_path = tmp_path / "runner-contract.json"
    observed_path = tmp_path / "observed-runner.json"
    baseline_path = tmp_path / "wall-clock-baseline.json"
    contract = _runner_contract()
    _write_json(runner_path, contract)
    _write_json(observed_path, contract)
    malformed = _baseline(runner_path)
    malformed["measured_runs"] = 1
    _write_json(baseline_path, malformed)

    with pytest.raises(ValueError, match="measured_runs"):
        resolve_wall_clock_baselines(
            runner_contract_path=runner_path,
            observed_runner_path=observed_path,
            baseline_path=baseline_path,
        )


def test_malformed_committed_baseline_is_fatal_even_without_runner(
    tmp_path: Path,
) -> None:
    baseline_path = tmp_path / "wall-clock-baseline.json"
    _write_json(baseline_path, {})

    with pytest.raises(ValueError, match="fields"):
        resolve_wall_clock_baselines(
            runner_contract_path=tmp_path / "runner-contract.json",
            observed_runner_path=None,
            baseline_path=baseline_path,
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("schema_version", 2, "schema_version"),
        ("allowed_regression_fraction", 0.2000000000001, "regression_fraction"),
        ("runner_contract_sha256", "A" * 64, "runner_contract_sha256"),
        (
            "command_medians_seconds",
            {"default-check": 0.5},
            "exact commands",
        ),
        (
            "command_medians_seconds",
            {"default-check": 0.0, "obligation-list": 2.5},
            "default-check median",
        ),
        ("unexpected", "value", "fields"),
    ),
)
def test_committed_baseline_rejects_each_invalid_schema_element(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    runner_path = tmp_path / "runner-contract.json"
    observed_path = tmp_path / "observed-runner.json"
    baseline_path = tmp_path / "wall-clock-baseline.json"
    contract = _runner_contract()
    _write_json(runner_path, contract)
    _write_json(observed_path, contract)
    baseline = _baseline(runner_path)
    baseline[field] = value
    _write_json(baseline_path, baseline)

    with pytest.raises(ValueError, match=message):
        resolve_wall_clock_baselines(
            runner_contract_path=runner_path,
            observed_runner_path=observed_path,
            baseline_path=baseline_path,
        )
