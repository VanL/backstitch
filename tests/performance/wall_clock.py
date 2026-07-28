"""Sampling and qualification policy for serial wall-clock benchmarks.

Spec: docs/specs/02-backstitch-core.md [SC-10]
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from tests.performance.semantic_scale import (
    assess_runner_qualification,
    load_runner_contract,
)

MEASURED_RUNS = 5
ALLOWED_REGRESSION_FRACTION = 0.20
BASELINE_FIELDS = frozenset(
    {
        "schema_version",
        "runner_contract_sha256",
        "measured_runs",
        "allowed_regression_fraction",
        "command_medians_seconds",
    }
)
COMMAND_IDS = frozenset({"default-check", "obligation-list"})
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class WallClockEvaluation:
    """One five-sample median and its qualification state."""

    samples_seconds: tuple[float, ...]
    median_seconds: float
    status: Literal["pass", "fail", "unavailable"]
    reason: Literal[
        "within_relative_limit",
        "relative_regression",
        "catastrophic_ceiling",
        "baseline_unavailable",
    ]


@dataclass(frozen=True, slots=True)
class BaselineResolution:
    """Availability and values for one pinned wall-clock baseline."""

    status: Literal["available", "unavailable"]
    reason: str
    command_medians_seconds: dict[str, float]


def _load_wall_clock_baseline(path: Path) -> tuple[str, dict[str, float]]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"wall-clock baseline is invalid: {path}") from exc
    if not isinstance(value, dict) or set(value) != BASELINE_FIELDS:
        raise ValueError("wall-clock baseline fields do not match the schema")
    if value.get("schema_version") != 1 or isinstance(
        value.get("schema_version"), bool
    ):
        raise ValueError("wall-clock baseline schema_version must equal 1")
    if value.get("measured_runs") != MEASURED_RUNS or isinstance(
        value.get("measured_runs"), bool
    ):
        raise ValueError(
            f"wall-clock baseline measured_runs must equal {MEASURED_RUNS}"
        )
    regression_fraction = value.get("allowed_regression_fraction")
    if (
        isinstance(regression_fraction, bool)
        or not isinstance(regression_fraction, (int, float))
        or regression_fraction != ALLOWED_REGRESSION_FRACTION
    ):
        raise ValueError(
            "wall-clock baseline allowed_regression_fraction must equal "
            f"{ALLOWED_REGRESSION_FRACTION}"
        )
    runner_hash = value.get("runner_contract_sha256")
    if not isinstance(runner_hash, str) or _SHA256_RE.fullmatch(runner_hash) is None:
        raise ValueError(
            "wall-clock baseline runner_contract_sha256 must be lowercase SHA-256"
        )
    medians = value.get("command_medians_seconds")
    if not isinstance(medians, dict) or set(medians) != COMMAND_IDS:
        raise ValueError(
            "wall-clock baseline command_medians_seconds must contain exact commands"
        )
    for command_id, median in medians.items():
        if (
            isinstance(median, bool)
            or not isinstance(median, (int, float))
            or not math.isfinite(median)
            or median <= 0
        ):
            raise ValueError(
                f"wall-clock baseline {command_id} median must be finite and positive"
            )
    return runner_hash, {
        command_id: float(medians[command_id]) for command_id in sorted(COMMAND_IDS)
    }


def resolve_wall_clock_baselines(
    *,
    runner_contract_path: Path,
    observed_runner_path: Path | None,
    baseline_path: Path,
) -> BaselineResolution:
    """Resolve comparable baselines without treating absence as failure."""

    loaded_baseline = (
        _load_wall_clock_baseline(baseline_path) if baseline_path.is_file() else None
    )
    if not runner_contract_path.is_file():
        return BaselineResolution("unavailable", "runner_contract_missing", {})
    if observed_runner_path is None or not observed_runner_path.is_file():
        return BaselineResolution("unavailable", "runtime_identity_unobserved", {})
    if loaded_baseline is None:
        return BaselineResolution("unavailable", "baseline_missing", {})
    runner_hash, medians = loaded_baseline
    try:
        observed = load_runner_contract(observed_runner_path)
    except ValueError:
        return BaselineResolution("unavailable", "runtime_identity_invalid", {})
    qualification = assess_runner_qualification(runner_contract_path, observed)
    if qualification.status == "unavailable":
        return BaselineResolution("unavailable", qualification.reason, {})
    current_runner_hash = hashlib.sha256(runner_contract_path.read_bytes()).hexdigest()
    if runner_hash != current_runner_hash:
        return BaselineResolution("unavailable", "baseline_runner_mismatch", {})
    return BaselineResolution("available", "runner_and_baseline_match", medians)


def evaluate_wall_clock(
    samples_seconds: tuple[float, ...],
    *,
    baseline_seconds: float | None,
    catastrophic_ceiling_seconds: float,
) -> WallClockEvaluation:
    """Evaluate one exact five-sample median without inventing comparability."""

    if len(samples_seconds) != MEASURED_RUNS:
        raise ValueError(f"wall-clock benchmark requires {MEASURED_RUNS} samples")
    if any(not math.isfinite(value) or value < 0 for value in samples_seconds):
        raise ValueError("wall-clock samples must be finite and nonnegative")
    if (
        not math.isfinite(catastrophic_ceiling_seconds)
        or catastrophic_ceiling_seconds <= 0
    ):
        raise ValueError("catastrophic ceiling must be finite and positive")
    median_seconds = statistics.median(samples_seconds)
    if median_seconds > catastrophic_ceiling_seconds:
        return WallClockEvaluation(
            samples_seconds,
            median_seconds,
            "fail",
            "catastrophic_ceiling",
        )
    if baseline_seconds is None:
        return WallClockEvaluation(
            samples_seconds,
            median_seconds,
            "unavailable",
            "baseline_unavailable",
        )
    relative_limit = baseline_seconds * (1 + ALLOWED_REGRESSION_FRACTION)
    if median_seconds > relative_limit:
        return WallClockEvaluation(
            samples_seconds,
            median_seconds,
            "fail",
            "relative_regression",
        )
    return WallClockEvaluation(
        samples_seconds,
        median_seconds,
        "pass",
        "within_relative_limit",
    )
