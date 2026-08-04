"""Table tests for the deadline and progress state machine.

Spec: docs/specs/02-backstitch-core.md [SC-5]
Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-8.4]
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from backstitch.operation_progress import (
    DEADLINE_PHASES,
    PROGRESS_PHASES,
    OperationDeadlineExceeded,
    OperationProgress,
    ProgressEvent,
)


class _Clock:
    def __init__(self, ticks: Iterator[float]) -> None:
        self._ticks = ticks

    def __call__(self) -> float:
        return next(self._ticks)


@pytest.mark.parametrize(
    ("current_index", "next_index", "allowed"),
    [
        (current_index, next_index, next_index >= current_index)
        for current_index in range(len(PROGRESS_PHASES))
        for next_index in range(len(PROGRESS_PHASES))
    ],
)
def test_progress_transition_table(
    current_index: int,
    next_index: int,
    allowed: bool,
) -> None:
    progress = OperationProgress(
        deadline=100.0,
        limit_milliseconds=1000,
        clock=lambda: 0.0,
        _phase=PROGRESS_PHASES[current_index],
    )
    next_phase = PROGRESS_PHASES[next_index]
    if allowed:
        progress.advance(next_phase)
        assert progress.phase == next_phase
    else:
        with pytest.raises(ValueError, match="progress phase cannot move"):
            progress.advance(next_phase)


@pytest.mark.parametrize("next_phase", PROGRESS_PHASES)
def test_progress_initial_transition_table(next_phase: str) -> None:
    progress = OperationProgress(
        deadline=100.0,
        limit_milliseconds=1000,
        clock=lambda: 0.0,
    )

    if next_phase == "snapshot":
        progress.advance(next_phase)  # type: ignore[arg-type]
        assert progress.phase == "snapshot"
    else:
        with pytest.raises(ValueError, match="progress phase cannot move"):
            progress.advance(next_phase)  # type: ignore[arg-type]


@pytest.mark.parametrize("phase", DEADLINE_PHASES)
def test_each_deadline_phase_cancels_at_its_first_crossing(phase: str) -> None:
    progress = OperationProgress.start(
        1.0,
        clock=_Clock(iter((0.0, 1.099))),
    )

    with pytest.raises(OperationDeadlineExceeded) as caught:
        progress.checkpoint(phase)  # type: ignore[arg-type]

    assert caught.value.phase == phase
    assert caught.value.limit_milliseconds == 1000
    assert caught.value.cooperative_tolerance_milliseconds == 100


def test_progress_sink_failure_disables_later_progress_without_domain_failure() -> None:
    calls: list[ProgressEvent] = []

    def broken_sink(event: ProgressEvent) -> None:
        calls.append(event)
        raise RuntimeError("renderer broke")

    progress = OperationProgress.start(
        1.0,
        clock=lambda: 0.0,
        sink=broken_sink,
    )

    progress.advance("snapshot", current_identity="repo")
    progress.advance("catalog", current_identity="repo")

    assert [event.phase for event in calls] == ["snapshot"]
    assert progress.phase == "catalog"


@pytest.mark.parametrize(
    ("completed", "total", "identity"),
    [
        (-1, None, "repo"),
        (2, 1, "repo"),
        (0, None, ""),
        (0, None, "repo\nnext"),
    ],
)
def test_progress_event_rejects_invalid_fields(
    completed: int,
    total: int | None,
    identity: str,
) -> None:
    with pytest.raises(ValueError):
        ProgressEvent("snapshot", completed, total, identity)
