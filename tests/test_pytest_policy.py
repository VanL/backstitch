"""Firing tests for the repository-owned live LLM pytest policy.

Spec: docs/specs/02-backstitch-core.md [SC-10]
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import _live_llm_enabled


class _Config:
    def __init__(self, run_live_llm: bool) -> None:
        self.run_live_llm = run_live_llm

    def getini(self, name: str) -> Any:
        assert name == "run_live_llm"
        return self.run_live_llm


@pytest.mark.parametrize(
    ("ini_enabled", "environment", "expected"),
    [
        (False, None, False),
        (True, None, True),
        (False, "1", True),
        (True, "1", True),
    ],
)
def test_live_llm_policy_truth_table(
    monkeypatch: pytest.MonkeyPatch,
    ini_enabled: bool,
    environment: str | None,
    expected: bool,
) -> None:
    if environment is None:
        monkeypatch.delenv("BACKSTITCH_LIVE_LLM", raising=False)
    else:
        monkeypatch.setenv("BACKSTITCH_LIVE_LLM", environment)

    assert _live_llm_enabled(_Config(ini_enabled)) is expected
