"""Absolute operation deadlines and noncanonical progress events.

Spec: docs/specs/02-backstitch-core.md [SC-5]
Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-8.4]
Plan: docs/plans/2026-07-29-usability-remediation-plan.md Slice 3

The deadline phase passed to :meth:`OperationProgress.checkpoint` describes
the work currently executing. Progress events instead form one ordered state
machine. Keeping those concerns separate lets a high-level packet phase call
lower-level discovery code without emitting phase regressions.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, TypeAlias

DeadlinePhase = Literal[
    "snapshot",
    "catalog",
    "relations",
    "closure",
    "candidate_detail",
    "packet_materialization",
    "packet_accounting",
]
ProgressPhase = Literal[
    "snapshot",
    "catalog",
    "relations",
    "closure",
    "candidate_detail",
    "packet_materialization",
    "packet_accounting",
    "complete",
]

PROGRESS_PHASES: tuple[ProgressPhase, ...] = (
    "snapshot",
    "catalog",
    "relations",
    "closure",
    "candidate_detail",
    "packet_materialization",
    "packet_accounting",
    "complete",
)
DEADLINE_PHASES: tuple[DeadlinePhase, ...] = (
    "snapshot",
    "catalog",
    "relations",
    "closure",
    "candidate_detail",
    "packet_materialization",
    "packet_accounting",
)
COOPERATIVE_TOLERANCE_MILLISECONDS = 100
_PHASE_INDEX = {phase: index for index, phase in enumerate(PROGRESS_PHASES)}


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    """One bounded, line-safe, noncanonical progress observation."""

    phase: ProgressPhase
    completed_work_units: int
    total_work_units: int | None
    current_identity: str

    def __post_init__(self) -> None:
        if (
            isinstance(self.completed_work_units, bool)
            or not isinstance(self.completed_work_units, int)
            or self.completed_work_units < 0
        ):
            raise ValueError("completed_work_units must be a nonnegative integer")
        if self.total_work_units is not None and (
            isinstance(self.total_work_units, bool)
            or not isinstance(self.total_work_units, int)
            or self.total_work_units < self.completed_work_units
        ):
            raise ValueError(
                "total_work_units must be null or at least completed_work_units"
            )
        if not self.current_identity.strip() or any(
            ord(character) < 32 or ord(character) == 127
            for character in self.current_identity
        ):
            raise ValueError("current_identity must be nonblank and line-safe")


ProgressSink: TypeAlias = Callable[[ProgressEvent], None]
MonotonicClock: TypeAlias = Callable[[], float]


class OperationDeadlineExceeded(RuntimeError):
    """The absolute operation deadline crossed at one cooperative checkpoint."""

    def __init__(self, phase: DeadlinePhase, limit_milliseconds: int) -> None:
        super().__init__(f"operation deadline exceeded during {phase}")
        self.phase = phase
        self.limit_milliseconds = limit_milliseconds
        self.cooperative_tolerance_milliseconds = COOPERATIVE_TOLERANCE_MILLISECONDS


@dataclass(slots=True)
class OperationProgress:
    """One absolute deadline plus an ordered best-effort progress machine."""

    deadline: float
    limit_milliseconds: int
    clock: MonotonicClock
    sink: ProgressSink | None = None
    _phase: ProgressPhase | None = None

    @classmethod
    def start(
        cls,
        maximum_seconds: float,
        *,
        clock: MonotonicClock = time.monotonic,
        sink: ProgressSink | None = None,
    ) -> OperationProgress:
        """Start one absolute deadline at the supplied monotonic clock."""

        if (
            isinstance(maximum_seconds, bool)
            or not isinstance(maximum_seconds, (int, float))
            or not math.isfinite(maximum_seconds)
            or maximum_seconds <= 0
        ):
            raise ValueError("maximum_seconds must be finite and positive")
        started = clock()
        if not math.isfinite(started):
            raise ValueError("monotonic clock must return a finite value")
        return cls(
            deadline=started + maximum_seconds,
            limit_milliseconds=int(maximum_seconds * 1000),
            clock=clock,
            sink=sink,
        )

    @property
    def phase(self) -> ProgressPhase | None:
        """Return the latest successfully emitted progress phase."""

        return self._phase

    def checkpoint(
        self,
        phase: DeadlinePhase,
    ) -> None:
        """Cancel at the first cooperative check after the absolute deadline."""

        if phase not in DEADLINE_PHASES:
            raise ValueError(f"unknown deadline phase: {phase}")
        observed = self.clock()
        if not math.isfinite(observed):
            raise ValueError("monotonic clock must return a finite value")
        if observed > self.deadline:
            raise OperationDeadlineExceeded(phase, self.limit_milliseconds)

    def advance(
        self,
        phase: ProgressPhase,
        *,
        completed_work_units: int = 0,
        total_work_units: int | None = None,
        current_identity: str = ".",
    ) -> None:
        """Advance monotonically and publish one best-effort event."""

        if phase not in PROGRESS_PHASES:
            raise ValueError(f"unknown progress phase: {phase}")
        if not self.can_advance(phase):
            current = self._phase or "<not-started>"
            raise ValueError(f"progress phase cannot move from {current} to {phase}")
        deadline_phase = self._deadline_phase_for(phase)
        self.checkpoint(deadline_phase)
        event = ProgressEvent(
            phase=phase,
            completed_work_units=completed_work_units,
            total_work_units=total_work_units,
            current_identity=current_identity,
        )
        self._phase = phase
        if self.sink is not None:
            try:
                self.sink(event)
            except Exception:  # noqa: BLE001 - progress is explicitly best effort.
                self.sink = None
        self.checkpoint(deadline_phase)

    def can_advance(self, phase: ProgressPhase) -> bool:
        """Return whether ``phase`` is valid from the current machine state."""

        if phase not in PROGRESS_PHASES:
            return False
        if self._phase == "complete":
            return phase == "complete"
        if self._phase is None:
            return phase == "snapshot"
        return _PHASE_INDEX[phase] >= _PHASE_INDEX[self._phase]

    def _deadline_phase_for(self, phase: ProgressPhase) -> DeadlinePhase:
        if phase != "complete":
            return phase
        if self._phase is None:
            raise ValueError("progress cannot complete before it starts")
        if self._phase == "complete":
            return "packet_accounting"
        return self._phase
