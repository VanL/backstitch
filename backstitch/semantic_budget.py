"""Shared semantic cost contract and provider-free analyzer projections.

Spec: docs/specs/02-backstitch-core.md [SC-5]
Spec: docs/specs/06-semantic-gates.md [SEM-7]
Plan: docs/plans/2026-07-29-usability-remediation-plan.md Slice 5.1
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from backstitch.semantic_identity import ProviderIdentity, RequestIdentity

BudgetStatus = Literal[
    "within_limit",
    "requires_cache_hits",
    "exceeds",
    "disabled",
    "unavailable",
]
CallCostStatus = Literal[
    "within_limits",
    "requires_cache_hits",
    "exceeds",
    "unknown",
    "unavailable",
]

_COST_FRAMING_TOKEN_BOUNDS: dict[tuple[str, str], int] = {
    # The built-in llm/OpenAI adapter is the first reviewed positive-cost
    # contract. Other backend/plugin pairs remain disabled until reviewed.
    ("llm", "openai"): 256,
}


class SemanticCostSettings(Protocol):
    """Resolved fields consumed by the shared cost contract."""

    @property
    def provider_identity(self) -> ProviderIdentity: ...

    @property
    def request_identity(self) -> RequestIdentity: ...

    @property
    def maximum_estimated_cost_microusd(self) -> int: ...

    @property
    def input_cost_microusd_per_million_tokens(self) -> int: ...

    @property
    def output_cost_microusd_per_million_tokens(self) -> int: ...

    @property
    def input_token_overhead(self) -> int: ...

    @property
    def cost_rate_source(self) -> str: ...


class AnalyzerBudgetSettings(SemanticCostSettings, Protocol):
    """Resolved analyzer fields needed for a cold projection."""

    @property
    def cache_mode(self) -> str: ...

    @property
    def maximum_provider_calls(self) -> int: ...


@dataclass(frozen=True, slots=True)
class CostContractViolation:
    """One provider-free cost-contract failure."""

    message: str


@dataclass(frozen=True, slots=True)
class AnalyzerBudgetProjection:
    """One complete-plan conservative analyzer call/cost projection."""

    provider_calls: int | None
    estimated_cost_microusd: int | None
    provider_call_status: BudgetStatus
    estimated_cost_status: BudgetStatus
    cost_rate_source: str | None
    call_cost_status: CallCostStatus

    def to_row(self) -> dict[str, object]:
        return {
            "provider_calls": self.provider_calls,
            "estimated_cost_microusd": self.estimated_cost_microusd,
            "provider_call_status": self.provider_call_status,
            "estimated_cost_status": self.estimated_cost_status,
            "cost_rate_source": self.cost_rate_source,
        }


def validate_cost_contract(
    settings: SemanticCostSettings,
    *,
    lane: Literal["analyze", "verify"],
) -> CostContractViolation | None:
    """Validate the reviewed positive-cost framing contract."""

    if settings.maximum_estimated_cost_microusd == 0:
        return None
    pair = (
        settings.provider_identity.backend_id,
        settings.provider_identity.plugin_id,
    )
    minimum_overhead = _COST_FRAMING_TOKEN_BOUNDS.get(pair)
    lane_label = "verifier " if lane == "verify" else ""
    if minimum_overhead is None:
        contract_label = (
            "reviewed backend/plugin contract"
            if lane == "verify"
            else "reviewed backend/plugin cost contract"
        )
        return CostContractViolation(
            f"positive {lane_label}cost ceiling has no {contract_label}"
        )
    if settings.input_token_overhead < minimum_overhead:
        framing_label = (
            "verifier input token overhead is below the adapter framing bound"
            if lane == "verify"
            else "input token overhead is below the adapter's code-owned framing bound"
        )
        return CostContractViolation(framing_label)
    if not settings.cost_rate_source.strip():
        source_label = (
            "positive verifier cost ceiling requires a nonblank rate source"
            if lane == "verify"
            else "positive cost ceiling requires a nonblank cost rate source"
        )
        return CostContractViolation(source_label)
    if (
        pair == ("llm", "openai")
        and settings.input_cost_microusd_per_million_tokens == 0
        and settings.output_cost_microusd_per_million_tokens == 0
    ):
        zero_label = (
            "positive verifier cost ceiling cannot use two zero cloud rates"
            if lane == "verify"
            else "positive cost ceiling cannot use zero rates for both cloud directions"
        )
        return CostContractViolation(zero_label)
    return None


def estimate_cost_microusd(
    request_byte_counts: tuple[int, ...],
    settings: SemanticCostSettings,
) -> int:
    """Return the existing conservative per-request ceiling sum."""

    max_tokens = settings.request_identity.max_tokens
    if max_tokens is None:
        raise ValueError("costed inference requires present max_tokens")
    total = 0
    for request_byte_count in request_byte_counts:
        input_tokens = request_byte_count + settings.input_token_overhead
        total += _ceil_million(
            input_tokens * settings.input_cost_microusd_per_million_tokens
        )
        total += _ceil_million(
            max_tokens * settings.output_cost_microusd_per_million_tokens
        )
    return total


def project_cold_analyzer_budget(
    request_byte_counts: tuple[int, ...] | None,
    settings: AnalyzerBudgetSettings,
) -> AnalyzerBudgetProjection:
    """Project calls and cost without reading semantic cache state."""

    if request_byte_counts is None:
        return AnalyzerBudgetProjection(
            provider_calls=None,
            estimated_cost_microusd=None,
            provider_call_status="unavailable",
            estimated_cost_status=(
                "disabled"
                if settings.maximum_estimated_cost_microusd == 0
                else "unavailable"
            ),
            cost_rate_source=None,
            call_cost_status="unavailable",
        )

    cache_mode = settings.cache_mode
    provider_calls = 0 if cache_mode == "require" else len(request_byte_counts)
    provider_call_status = _limit_status(
        provider_calls,
        settings.maximum_provider_calls,
        cache_mode=cache_mode,
    )
    if settings.maximum_estimated_cost_microusd == 0:
        estimated_cost = None
        estimated_cost_status: BudgetStatus = "disabled"
        cost_source = None
    else:
        estimated_cost = (
            0
            if cache_mode == "require"
            else estimate_cost_microusd(request_byte_counts, settings)
        )
        estimated_cost_status = _limit_status(
            estimated_cost,
            settings.maximum_estimated_cost_microusd,
            cache_mode=cache_mode,
        )
        cost_source = settings.cost_rate_source

    statuses = {provider_call_status, estimated_cost_status}
    if "exceeds" in statuses:
        combined: CallCostStatus = "exceeds"
    elif cache_mode == "require" or "requires_cache_hits" in statuses:
        combined = "requires_cache_hits"
    else:
        combined = "within_limits"
    return AnalyzerBudgetProjection(
        provider_calls=provider_calls,
        estimated_cost_microusd=estimated_cost,
        provider_call_status=provider_call_status,
        estimated_cost_status=estimated_cost_status,
        cost_rate_source=cost_source,
        call_cost_status=combined,
    )


def _limit_status(
    value: int,
    maximum: int,
    *,
    cache_mode: str,
) -> BudgetStatus:
    if value <= maximum:
        return "within_limit"
    if cache_mode == "read-write":
        return "requires_cache_hits"
    return "exceeds"


def _ceil_million(value: int) -> int:
    return (value + 999_999) // 1_000_000
