"""Executable public-command ownership for the full dogfood journey.

Spec: docs/specs/02-backstitch-core.md [SC-10]
Plan: docs/plans/2026-07-29-usability-remediation-plan.md Slice 7
"""

from __future__ import annotations

ENTRY_METADATA_CASE = (
    "tests.acceptance.test_probe_full_dogfood:"
    "test_installed_entry_metadata_and_command_help"
)
GREEN_JOURNEY_CASE = (
    "tests.acceptance.test_probe_full_dogfood:"
    "test_installed_current_analysis_replays_through_real_local_llm_plugin"
)
SELF_REPOSITORY_CASE = (
    "tests.acceptance.test_probe_full_dogfood:"
    "test_isolated_self_repository_dogfood_uses_committed_budgets"
)

# Every command maps to the callable installed-command case that exercises it.
PUBLIC_COMMAND_CASES: dict[tuple[str, ...], tuple[str, ...]] = {
    (): (ENTRY_METADATA_CASE,),
    ("analyze",): (GREEN_JOURNEY_CASE,),
    ("cache", "cleanup-lock"): (GREEN_JOURNEY_CASE,),
    ("check",): (GREEN_JOURNEY_CASE,),
    ("config", "path"): (GREEN_JOURNEY_CASE,),
    ("config", "show"): (GREEN_JOURNEY_CASE,),
    ("coverage",): (GREEN_JOURNEY_CASE,),
    ("doctor",): (GREEN_JOURNEY_CASE,),
    ("eval",): (GREEN_JOURNEY_CASE,),
    ("guide", "alignment"): (GREEN_JOURNEY_CASE,),
    ("obligation",): (GREEN_JOURNEY_CASE,),
    ("packets",): (GREEN_JOURNEY_CASE,),
    ("summarize-analysis",): (GREEN_JOURNEY_CASE,),
}

PSEUDO_SURFACE_CASES: dict[str, tuple[str, ...]] = {
    "bare_dispatch": (
        "tests.acceptance.test_probe_full_dogfood:"
        "test_installed_current_analysis_replays_through_real_local_llm_plugin",
    ),
    "historical_analyze": (
        "tests.acceptance.test_probe_full_dogfood:"
        "test_installed_current_analysis_replays_through_real_local_llm_plugin",
    ),
    "readiness_failure": (
        "tests.acceptance.test_probe_usability_dogfood:"
        "test_preflight_explains_semantic_debt_when_check_is_clean",
    ),
    "self_repository": (SELF_REPOSITORY_CASE,),
    "exact_replay": (
        "tests.acceptance.test_probe_full_dogfood:"
        "test_installed_current_analysis_replays_through_real_local_llm_plugin",
    ),
    "cache_miss": (
        "tests.acceptance.test_probe_full_dogfood:"
        "test_installed_current_analysis_replays_through_real_local_llm_plugin",
    ),
    "currentness_race": (
        "tests.acceptance.test_probe_full_dogfood:"
        "test_installed_analysis_rejects_mutation_during_model_execution",
    ),
}

REQUIRED_SEAM_RECEIPTS = frozenset(
    {
        "resolved_config",
        "preparation",
        "packet_plan",
        "analyzer_adapter_calls",
        "verifier_adapter_calls",
        "cache_decisions",
        "currentness",
        "historical_packet_loader",
        "summary_input_loader",
    }
)
