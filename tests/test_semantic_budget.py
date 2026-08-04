"""Shared semantic cost arithmetic and provider-free budget projection.

Spec: docs/specs/02-backstitch-core.md [SC-5]
Spec: docs/specs/06-semantic-gates.md [SEM-7]
Plan: docs/plans/2026-07-29-usability-remediation-plan.md Slice 5.1
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

import pytest

from backstitch.semantic_budget import (
    estimate_cost_microusd,
    project_cold_analyzer_budget,
    validate_cost_contract,
)
from backstitch.semantic_identity import ProviderIdentity, RequestIdentity


@dataclass(frozen=True, slots=True)
class _Settings:
    provider_identity: ProviderIdentity
    request_identity: RequestIdentity
    maximum_estimated_cost_microusd: int = 4
    input_cost_microusd_per_million_tokens: int = 1
    output_cost_microusd_per_million_tokens: int = 1
    input_token_overhead: int = 256
    cost_rate_source: str = "controlled test rates"
    cache_mode: str = "off"
    maximum_provider_calls: int = 2


PROVIDER = ProviderIdentity(
    backend_id="llm",
    plugin_id="openai",
    model_id="pkg:service/openai.com/gpt-test",
    model_revision="2026-07-29",
    adapter_id="backstitch.llm",
    adapter_version=1,
    llm_distribution_version="0.31.1",
    plugin_distribution_name="llm-openai",
    plugin_distribution_version="1.2.3",
)
SETTINGS = _Settings(
    provider_identity=PROVIDER,
    request_identity=RequestIdentity("require", 0.0, 42, 512),
)
REQUEST_BYTE_COUNTS = (999_744, 1)


def test_cost_estimate_ceilings_are_applied_per_request_and_direction() -> None:
    # Request one costs 1 input + 1 output; request two does too. Combining
    # directions or requests before ceiling would incorrectly produce 3.
    assert estimate_cost_microusd(REQUEST_BYTE_COUNTS, SETTINGS) == 4


@pytest.mark.parametrize(
    ("cache_mode", "maximum_calls", "maximum_cost", "expected"),
    [
        (
            "off",
            2,
            4,
            (2, 4, "within_limit", "within_limit", "within_limits"),
        ),
        (
            "off",
            1,
            3,
            (2, 4, "exceeds", "exceeds", "exceeds"),
        ),
        (
            "read-write",
            1,
            3,
            (
                2,
                4,
                "requires_cache_hits",
                "requires_cache_hits",
                "requires_cache_hits",
            ),
        ),
        (
            "require",
            0,
            1,
            (0, 0, "within_limit", "within_limit", "requires_cache_hits"),
        ),
    ],
)
def test_cold_projection_distinguishes_exact_and_cache_dependent_limits(
    cache_mode: str,
    maximum_calls: int,
    maximum_cost: int,
    expected: tuple[int, int, str, str, str],
) -> None:
    projection = project_cold_analyzer_budget(
        REQUEST_BYTE_COUNTS,
        replace(
            SETTINGS,
            cache_mode=cache_mode,
            maximum_provider_calls=maximum_calls,
            maximum_estimated_cost_microusd=maximum_cost,
        ),
    )

    assert (
        projection.provider_calls,
        projection.estimated_cost_microusd,
        projection.provider_call_status,
        projection.estimated_cost_status,
        projection.call_cost_status,
    ) == expected


def test_disabled_and_unavailable_costs_are_not_fabricated() -> None:
    disabled = project_cold_analyzer_budget(
        REQUEST_BYTE_COUNTS,
        replace(SETTINGS, maximum_estimated_cost_microusd=0),
    )
    unavailable = project_cold_analyzer_budget(None, SETTINGS)

    assert disabled.estimated_cost_microusd is None
    assert disabled.estimated_cost_status == "disabled"
    assert disabled.cost_rate_source is None
    assert unavailable.provider_calls is None
    assert unavailable.estimated_cost_microusd is None
    assert unavailable.provider_call_status == "unavailable"
    assert unavailable.estimated_cost_status == "unavailable"
    assert unavailable.call_cost_status == "unavailable"


@pytest.mark.parametrize(
    ("settings", "lane", "message"),
    [
        (
            replace(
                SETTINGS,
                provider_identity=replace(PROVIDER, plugin_id="unreviewed"),
            ),
            "analyze",
            "positive cost ceiling has no reviewed backend/plugin cost contract",
        ),
        (
            replace(SETTINGS, input_token_overhead=255),
            "analyze",
            "input token overhead is below the adapter's code-owned framing bound",
        ),
        (
            replace(SETTINGS, cost_rate_source=" "),
            "analyze",
            "positive cost ceiling requires a nonblank cost rate source",
        ),
        (
            replace(
                SETTINGS,
                input_cost_microusd_per_million_tokens=0,
                output_cost_microusd_per_million_tokens=0,
            ),
            "verify",
            "positive verifier cost ceiling cannot use two zero cloud rates",
        ),
    ],
)
def test_positive_cost_contract_rejects_unreviewed_or_incomplete_inputs(
    settings: _Settings,
    lane: Literal["analyze", "verify"],
    message: str,
) -> None:
    violation = validate_cost_contract(settings, lane=lane)

    assert violation is not None
    assert violation.message == message
