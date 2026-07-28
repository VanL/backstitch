"""Non-normative local wall-clock budgets for evidence-spike hardening.

Spec: docs/specs/02-backstitch-core.md [SC-10]
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.performance
@pytest.mark.benchmark
@pytest.mark.parametrize(
    ("arguments", "budget_seconds"),
    (
        (("check", "--repo-root", "."), 0.7),
        (("obligation", "list", "--repo-root", "."), 3.0),
    ),
    ids=("default-check", "obligation-list"),
)
def test_self_corpus_command_wall_clock_budget(
    arguments: tuple[str, ...], budget_seconds: float
) -> None:
    """Pin the plan's local 0.7 s / 3 s budgets outside normative specs.

    Each probe runs the real module entry point in a subprocess against the
    complete self-corpus, discards renderer output, requires exit zero, and
    measures one cold invocation with ``perf_counter``. The thresholds include
    generous local variance but are not portable qualification claims. Slice 0
    measured roughly 1.8 s for default check and 7.8 s for obligation list.
    """

    started = time.perf_counter()
    completed = subprocess.run(
        (sys.executable, "-m", "backstitch", *arguments),
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    elapsed = time.perf_counter() - started

    assert completed.returncode == 0, completed.stderr
    assert elapsed <= budget_seconds, (
        f"{arguments!r} took {elapsed:.3f}s; budget is {budget_seconds:.3f}s"
    )
