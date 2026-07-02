"""Section-ID grammar contract.

Spec: docs/specs/02-backstitch-core.md [SC-4]
"""

from __future__ import annotations

import pytest

from backstitch.grammar import SECTION_ID_RE, is_valid_section_id


@pytest.mark.parametrize(
    "candidate",
    ["MF-5", "CLI-1.1.1", "OBS.13.10", "SB-0.4a", "DOM-4", "MANAGER.12a", "A1"],
)
def test_documented_examples_are_valid(candidate: str) -> None:
    assert is_valid_section_id(candidate)


@pytest.mark.parametrize(
    "candidate",
    ["Task", "Manager", "TODO", "", "lower-1", "1ABC", "[MF-5]"],
)
def test_grammar_rejects_task_manager_prose(candidate: str) -> None:
    assert not is_valid_section_id(candidate)


def test_n1_is_grammar_valid_noise_filtering_is_resolver_policy() -> None:
    # `window[N-1]`-style prose noise is silenced by the resolver's
    # known-prefix rule ([SC-4]), NOT by the grammar: N-1 is a valid token.
    assert is_valid_section_id("N-1")


def test_regex_is_fully_anchored() -> None:
    assert SECTION_ID_RE.match("MF-5 trailing") is None
