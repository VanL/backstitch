"""Hermetic installed-command dogfood and command-surface ownership.

Spec: docs/specs/02-backstitch-core.md [SC-10]
Spec: docs/specs/06-semantic-gates.md [SEM-9], [SEM-10]
Plan: docs/plans/2026-07-29-usability-remediation-plan.md Slice 7
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import select
import shutil
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from backstitch.cli import build_parser
from tests.acceptance.command_surface_manifest import (
    PSEUDO_SURFACE_CASES,
    PUBLIC_COMMAND_CASES,
    REQUIRED_SEAM_RECEIPTS,
)
from tests.acceptance.conftest import (
    LOCAL_LLM_MODEL,
    REPO_ROOT,
    local_llm_environment,
    run_installed_cli,
)

EXPECTED_PSEUDO_SURFACES = frozenset(
    {
        "bare_dispatch",
        "historical_analyze",
        "readiness_failure",
        "self_repository",
        "exact_replay",
        "cache_miss",
        "currentness_race",
    }
)
EXPECTED_SEAM_RECEIPTS = frozenset(
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


def _public_command_leaves(
    parser: argparse.ArgumentParser,
    prefix: tuple[str, ...] = (),
) -> set[tuple[str, ...]]:
    subcommands = next(
        (
            action
            for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        ),
        None,
    )
    if subcommands is None:
        return {prefix}
    leaves: set[tuple[str, ...]] = set()
    for name, child in subcommands.choices.items():
        leaves.update(_public_command_leaves(child, (*prefix, name)))
    return leaves


def _write_local_model_repo(root: Path) -> None:
    (root / "docs/specs").mkdir(parents=True)
    (root / "pkg").mkdir()
    (root / "tests").mkdir()
    (root / "docs/specs/01-core.md").write_text(
        "# Core\n\n"
        "## Return one [CORE-1]\n\n"
        "The implementation returns one.\n\n"
        "_Implementation mapping_:\n\n"
        "- `pkg/core.py::value`\n"
        "- `tests/test_core.py::test_value`\n",
        encoding="utf-8",
    )
    (root / "pkg/core.py").write_text(
        "def value() -> int:\n"
        '    """Spec: docs/specs/01-core.md [CORE-1]"""\n'
        "    return 1\n\n\n"
        "def candidate_value() -> int:\n"
        '    """Nearby undeclared evidence for public discovery dogfood."""\n'
        "    return 1\n",
        encoding="utf-8",
    )
    (root / "tests/test_core.py").write_text(
        "from pkg.core import value\n\n\n"
        "def test_value() -> None:\n"
        '    """Spec: docs/specs/01-core.md [CORE-1]"""\n'
        "    assert value() == 1\n",
        encoding="utf-8",
    )
    (root / ".backstitch.toml").write_text(
        "\n".join(
            [
                'default_command = "analyze"',
                "",
                "[profile]",
                'spec_roots = ["docs/specs"]',
                "plan_roots = []",
                'code_roots = ["pkg", "tests"]',
                'test_roots = ["tests"]',
                "",
                "[obligations]",
                'section_required_roles = ["implementation", "test"]',
                "",
                "[analyze]",
                'backend_id = "llm"',
                'plugin_id = "backstitch-acceptance-local"',
                'plugin_distribution_name = "llm"',
                'model = "pkg:service/example.com/backstitch-acceptance@fixture-v1"',
                f'adapter_model_id = "{LOCAL_LLM_MODEL}"',
                'model_revision = "fixture-v1"',
                "capability_schema_version = 1",
                'capability_revision = "fixture-v1"',
                "maximum_input_bytes = 1000000",
                "concurrency = 1",
                'json_mode = "require"',
                "temperature = 0.0",
                "seed = 42",
                "max_tokens = 512",
                'cache_path = ".backstitch/semantic-cache"',
                'cache_mode = "read-write"',
                'result_reuse = "evidence-stable"',
                'search_epoch = "fixture-v1"',
                "require_complete = true",
                'required_kinds = ["section"]',
                "minimum_packets = 1",
                "maximum_packets = 10",
                "maximum_prompt_bytes = 1000000",
                'finding_handling = "report"',
                "maximum_provider_calls = 10",
                "lock_wait_timeout_seconds = 5",
                "maximum_runtime_seconds = 30",
                "maximum_estimated_cost_microusd = 0",
                "input_cost_microusd_per_million_tokens = 0",
                "output_cost_microusd_per_million_tokens = 0",
                "input_token_overhead = 0",
                'cost_rate_source = "test-owned zero rates"',
                "",
                "[analyze.request_constraints.json_mode]",
                'presence = "required"',
                'allowed_values = ["require"]',
                "",
                "[analyze.request_constraints.temperature]",
                'presence = "required"',
                "allowed_values = [0.0]",
                "",
                "[analyze.request_constraints.seed]",
                'presence = "required"',
                "minimum = 0",
                "maximum = 2147483647",
                "",
                "[analyze.request_constraints.max_tokens]",
                'presence = "required"',
                "minimum = 1",
                "maximum = 16384",
                "",
                "[analyze.request_constraints.reasoning_effort]",
                'presence = "forbidden"',
                "",
                "[verify]",
                "enabled = true",
                'provider_source = "override"',
                "concurrency = 1",
                'cache_path = ".backstitch/semantic-cache"',
                'cache_mode = "read-write"',
                'search_epochs = ["fixture-v1"]',
                'json_mode = "require"',
                "temperature = 0.0",
                "seed = 42",
                "max_tokens = 512",
                "required_verdicts = 1",
                "minimum_support_score = 0.9",
                'indeterminate = "report"',
                "maximum_provider_calls = 10",
                "maximum_prompt_bytes = 1000000",
                "lock_wait_timeout_seconds = 5",
                "maximum_runtime_seconds = 30",
                "maximum_estimated_cost_microusd = 0",
                "",
                "[verify.provider]",
                'backend_id = "llm"',
                'plugin_id = "backstitch-acceptance-local"',
                'plugin_distribution_name = "llm"',
                'model = "pkg:service/example.com/backstitch-verifier@fixture-v1"',
                'adapter_model_id = "backstitch-acceptance-verifier"',
                'model_revision = "fixture-v1"',
                "capability_schema_version = 1",
                'capability_revision = "verifier-fixture-v1"',
                "maximum_input_bytes = 1000000",
                "input_cost_microusd_per_million_tokens = 0",
                "output_cost_microusd_per_million_tokens = 0",
                "input_token_overhead = 0",
                'cost_rate_source = "test-owned zero rates"',
                "",
                "[verify.provider.request_constraints.json_mode]",
                'presence = "required"',
                'allowed_values = ["require"]',
                "",
                "[verify.provider.request_constraints.temperature]",
                'presence = "required"',
                "allowed_values = [0.0]",
                "",
                "[verify.provider.request_constraints.seed]",
                'presence = "required"',
                "minimum = 0",
                "maximum = 2147483647",
                "",
                "[verify.provider.request_constraints.max_tokens]",
                'presence = "required"',
                "minimum = 1",
                "maximum = 16384",
                "",
                "[verify.provider.request_constraints.reasoning_effort]",
                'presence = "forbidden"',
                "",
                "[verify.eval]",
                'mode = "report"',
                'qualification_corpus = ""',
                'qualification_corpus_sha256 = ""',
                'qualification_report = ""',
                'qualification_report_sha256 = ""',
                "trials = 1",
                'interval_method = "wilson"',
                "confidence_level = 0.95",
                "minimum_positive_units = 1",
                "minimum_negative_units = 1",
                "minimum_evidence_sufficiency_rate = 0.0",
                "minimum_conditional_precision = 0.0",
                "minimum_conditional_recall = 0.0",
                "minimum_end_to_end_recall = 0.0",
                "minimum_recall_lower_bound = 0.0",
                "maximum_false_positive_rate = 1.0",
                "maximum_false_positive_upper_bound = 1.0",
                "maximum_indeterminate_rate = 1.0",
                "maximum_uncached_flip_rate = 1.0",
                "require_all_critical = false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _read_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        cast(dict[str, Any], json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


def _assert_receipt_names(receipts: dict[str, Any]) -> None:
    assert set(receipts) == REQUIRED_SEAM_RECEIPTS


def _assert_green_seam_receipts(receipts: dict[str, Any]) -> None:
    """Require evidence from every real seam crossed by the green journey."""

    _assert_receipt_names(receipts)

    resolved_config = receipts["resolved_config"]
    assert resolved_config["analyze"]["adapter_model_id"] == LOCAL_LLM_MODEL
    assert resolved_config["verify"]["provider"]["adapter_model_id"] == (
        "backstitch-acceptance-verifier"
    )

    preparation = receipts["preparation"]
    assert preparation["value"]["ready"] is True
    assert preparation["value"]["config"]["settings_sha256"].startswith("sha256:")
    assert preparation["value"]["snapshot"]["snapshot_hash"].startswith("sha256:")
    assert preparation["current_snapshot_hash"] == (
        preparation["value"]["snapshot"]["snapshot_hash"].removeprefix("sha256:")
    )

    packet_plan = receipts["packet_plan"]
    assert packet_plan["value"]["complete"] is True
    assert packet_plan["value"]["packet_count"] == packet_plan["report"]["packet_count"]
    assert packet_plan["value"]["packet_bytes"] == packet_plan["report"]["packet_bytes"]
    assert (
        packet_plan["report"]["packet_jsonl_sha256"]
        == (packet_plan["actual_packet_jsonl_sha256"])
    )

    analyzer_calls = receipts["analyzer_adapter_calls"]
    assert analyzer_calls
    assert {call["role"] for call in analyzer_calls} == {"analyzer"}
    assert {call["model_id"] for call in analyzer_calls} == {LOCAL_LLM_MODEL}

    verifier_calls = receipts["verifier_adapter_calls"]
    assert verifier_calls
    assert {call["role"] for call in verifier_calls} == {"verifier"}
    assert {call["model_id"] for call in verifier_calls} == {
        "backstitch-acceptance-verifier"
    }

    cache_decisions = receipts["cache_decisions"]
    assert cache_decisions["first"] == {"hits": 0, "misses": 1, "calls": 1}
    assert cache_decisions["exact_replay"] == {
        "hits": 1,
        "misses": 0,
        "calls": 0,
    }
    assert cache_decisions["search_epoch_miss"] == {
        "hits": 0,
        "misses": 1,
        "calls": 1,
    }

    currentness = receipts["currentness"]
    assert currentness["current"] == {
        "scope": "current_repository",
        "status": "current",
    }
    assert currentness["historical"] == {
        "scope": "historical_snapshot",
        "status": "unverifiable",
    }

    historical_loader = receipts["historical_packet_loader"]
    assert historical_loader == {
        "packet_report_selection_status": "selected",
        "analysis_scope": "historical_snapshot",
        "provider_calls": 0,
        "result_bytes_match": True,
    }

    summary_loader = receipts["summary_input_loader"]
    assert summary_loader == {
        "command_exit_code": 0,
        "obligation_id": "docs/specs/01-core.md#CORE-1",
    }


def test_blocked_verified_preflight_keeps_unavailable_budget_status(
    tmp_path: Path,
) -> None:
    """A deferred verifier cannot make an absent analyzer plan look known."""

    _write_local_model_repo(tmp_path)
    spec = tmp_path / "docs/specs/01-core.md"
    spec.write_text(
        spec.read_text(encoding="utf-8").replace("- `pkg/core.py::value`\n", ""),
        encoding="utf-8",
    )
    ledger = tmp_path / "local-model-ledger.jsonl"

    result = run_installed_cli(
        "analyze",
        "--repo-root",
        str(tmp_path),
        "--preflight",
        "--format",
        "json",
        environment=local_llm_environment(ledger),
    )

    assert result.returncode == 2
    assert result.stderr == ""
    document = json.loads(result.stdout)
    assert document["ready"] is False
    assert document["packet_plan"] is None
    assert document["budgets"]["analyzer"] == {
        "provider_calls": None,
        "estimated_cost_microusd": None,
        "provider_call_status": "unavailable",
        "estimated_cost_status": "disabled",
        "cost_rate_source": None,
    }
    assert document["budgets"]["verifier"]["status"] == (
        "deferred_until_analyzer_results"
    )
    assert document["budgets"]["call_cost_status"] == "unavailable"
    assert _read_ledger(ledger) == []


def _copy_self_repository(destination: Path) -> Path:
    destination.mkdir()
    directory_names = ("backstitch", "bin", "docs", "skills", "tests", ".github")
    ignored = shutil.ignore_patterns(
        "__pycache__",
        "*.pyc",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".coverage",
        "coverage.xml",
        "fixtures",
    )
    for name in directory_names:
        shutil.copytree(
            REPO_ROOT / name,
            destination / name,
            symlinks=True,
            ignore=ignored,
        )
    for name in (
        "AGENTS.md",
        "CHANGELOG.md",
        "CLAUDE.md",
        "LICENSE",
        "README.md",
        "pyproject.toml",
        "uv.lock",
    ):
        source_path = REPO_ROOT / name
        if source_path.is_symlink():
            (destination / name).symlink_to(os.readlink(source_path))
        else:
            shutil.copy2(source_path, destination / name)

    config = destination / "pyproject.toml"
    config_text = config.read_text(encoding="utf-8")
    old = 'adapter_model_id = "gpt-5.6-luna"'
    assert config_text.count(old) == 1
    replacements = (
        (old, f'adapter_model_id = "{LOCAL_LLM_MODEL}"'),
        (
            'reasoning_effort = "max"',
            "temperature = 0.0\nseed = 42",
        ),
        (
            "[tool.backstitch.analyze.request_constraints.temperature]\n"
            'presence = "forbidden"',
            "[tool.backstitch.analyze.request_constraints.temperature]\n"
            'presence = "required"\nallowed_values = [0.0]',
        ),
        (
            "[tool.backstitch.analyze.request_constraints.seed]\n"
            'presence = "forbidden"',
            "[tool.backstitch.analyze.request_constraints.seed]\n"
            'presence = "required"\nminimum = 0\nmaximum = 2147483647',
        ),
        (
            "[tool.backstitch.analyze.request_constraints.reasoning_effort]\n"
            'presence = "optional"\nallowed_values = ["max"]',
            "[tool.backstitch.analyze.request_constraints.reasoning_effort]\n"
            'presence = "forbidden"',
        ),
    )
    for before, after in replacements:
        assert config_text.count(before) == 1
        config_text = config_text.replace(before, after, 1)
    config.write_text(config_text, encoding="utf-8")
    return destination


def test_public_command_surface_has_one_dogfood_owner() -> None:
    actual = _public_command_leaves(build_parser())
    expected = set(PUBLIC_COMMAND_CASES) - {()}
    assert actual == expected
    assert set(PSEUDO_SURFACE_CASES) == EXPECTED_PSEUDO_SURFACES
    assert REQUIRED_SEAM_RECEIPTS == EXPECTED_SEAM_RECEIPTS
    for targets in (
        *PUBLIC_COMMAND_CASES.values(),
        *PSEUDO_SURFACE_CASES.values(),
    ):
        for target in targets:
            module_name, separator, function_name = target.partition(":")
            assert separator
            assert callable(
                getattr(importlib.import_module(module_name), function_name)
            )


@pytest.mark.parametrize("deleted", sorted(EXPECTED_SEAM_RECEIPTS))
def test_seam_receipt_manifest_rejects_each_deleted_name(deleted: str) -> None:
    receipts = dict.fromkeys(EXPECTED_SEAM_RECEIPTS)
    del receipts[deleted]

    with pytest.raises(AssertionError):
        _assert_receipt_names(receipts)


def test_installed_entry_metadata_and_command_help() -> None:
    entry_help = run_installed_cli("--help")
    version = run_installed_cli("--version")
    invalid = run_installed_cli("check", "--not-a-real-option")
    assert entry_help.returncode == version.returncode == 0
    assert entry_help.stdout.startswith("usage: backstitch ")
    assert version.stdout.startswith("backstitch ")
    assert entry_help.stderr == version.stderr == ""
    assert invalid.returncode == 2
    assert invalid.stdout == ""
    assert "unrecognized arguments" in invalid.stderr

    for command in sorted(set(PUBLIC_COMMAND_CASES) - {()}):
        result = run_installed_cli(*command, "--help")
        assert result.returncode == 0, (command, result.stderr)
        assert result.stdout.startswith(f"usage: backstitch {' '.join(command)} ")
        assert result.stderr == ""


def test_installed_current_analysis_replays_through_real_local_llm_plugin(
    tmp_path: Path,
) -> None:
    _write_local_model_repo(tmp_path)
    ledger = tmp_path / "local-model-ledger.jsonl"
    environment = local_llm_environment(ledger)

    config_path = run_installed_cli(
        "config",
        "path",
        "--repo-root",
        str(tmp_path),
        environment=environment,
    )
    assert config_path.returncode == 0, config_path.stderr
    assert Path(config_path.stdout.strip()) == tmp_path / ".backstitch.toml"
    config_show = run_installed_cli(
        "config",
        "show",
        "--repo-root",
        str(tmp_path),
        environment=environment,
    )
    assert config_show.returncode == 0, config_show.stderr
    shown = json.loads(config_show.stdout)
    assert shown["analyze"]["adapter_model_id"] == LOCAL_LLM_MODEL
    assert shown["analyze"]["model"].startswith("pkg:service/")

    guide = run_installed_cli("guide", "alignment", "--format", "json")
    assert guide.returncode == 0, guide.stderr
    assert json.loads(guide.stdout)["guide_id"] == "alignment"

    check = run_installed_cli(
        "check",
        "--repo-root",
        str(tmp_path),
        "--format",
        "json",
        environment=environment,
    )
    assert check.returncode == 0, check.stderr
    deterministic = json.loads(check.stdout)
    assert deterministic["summary"]["errors"] == 0
    assert deterministic["summary"]["warnings"] == 0

    coverage = run_installed_cli(
        "coverage",
        "--repo-root",
        str(tmp_path),
        "--format",
        "json",
        environment=environment,
    )
    assert coverage.returncode == 0, coverage.stderr
    coverage_value = json.loads(coverage.stdout)
    assert coverage_value["summary"]["complete"] is True

    obligation_id = "docs/specs/01-core.md#CORE-1"
    listed = run_installed_cli(
        "obligation",
        "list",
        "--repo-root",
        str(tmp_path),
        "--format",
        "json",
        environment=environment,
    )
    assert listed.returncode == 0, listed.stderr
    listed_value = json.loads(listed.stdout)
    assert listed_value["result"]["entries"][0]["obligation_id"] == obligation_id

    detailed = run_installed_cli(
        "obligation",
        obligation_id,
        "--repo-root",
        str(tmp_path),
        "--format",
        "json",
        environment=environment,
    )
    assert detailed.returncode == 0, detailed.stderr
    assert json.loads(detailed.stdout)["result"]["obligation_id"] == obligation_id

    evidence = run_installed_cli(
        "obligation",
        obligation_id,
        "--repo-root",
        str(tmp_path),
        "--summarize-evidence",
        "--limit",
        "2",
        "--format",
        "json",
        environment=environment,
    )
    assert evidence.returncode == 0, evidence.stderr
    assert json.loads(evidence.stdout)["result"]["items"]

    discovered = run_installed_cli(
        "obligation",
        obligation_id,
        "--repo-root",
        str(tmp_path),
        "--find-evidence",
        "--limit",
        "10",
        "--format",
        "json",
        environment=environment,
    )
    assert discovered.returncode == 0, discovered.stderr
    candidate_rows = json.loads(discovered.stdout)["result"]["candidates"]
    candidate_id = next(
        row["candidate_id"]
        for row in candidate_rows
        if row["structural_locator"].startswith(
            "python-definition:candidate_value:function:"
        )
    )
    candidate = run_installed_cli(
        "obligation",
        obligation_id,
        "--repo-root",
        str(tmp_path),
        "--candidate",
        candidate_id,
        "--format",
        "json",
        environment=environment,
    )
    assert candidate.returncode == 0, candidate.stderr
    assert json.loads(candidate.stdout)["result"]["candidate"]["candidate_id"] == (
        candidate_id
    )

    standalone_packets = tmp_path / "standalone-packets.jsonl"
    standalone_report = tmp_path / "standalone-packets-report.json"
    packet_command = run_installed_cli(
        "packets",
        "--repo-root",
        str(tmp_path),
        "--kind",
        "all",
        "--output",
        str(standalone_packets),
        "--report",
        str(standalone_report),
        environment=environment,
    )
    assert packet_command.returncode == 0, packet_command.stderr
    assert standalone_packets.read_bytes()
    assert (
        json.loads(standalone_report.read_text(encoding="utf-8"))["selection_status"]
        == "selected"
    )

    preflight = run_installed_cli(
        "analyze",
        "--repo-root",
        str(tmp_path),
        "--preflight",
        "--format",
        "json",
        environment=environment,
    )
    assert preflight.returncode == 0, preflight.stderr
    prepared = json.loads(preflight.stdout)
    assert prepared["schema_version"] == 2
    assert prepared["ready"] is True
    assert prepared["budgets"] == {
        "projection": "conservative_cold",
        "limits": {
            "maximum_packets": 10,
            "maximum_prompt_bytes": 1_000_000,
            "maximum_input_bytes": 1_000_000,
            "maximum_provider_calls": 10,
            "maximum_estimated_cost_microusd": None,
            "maximum_runtime_seconds": 30,
        },
        "analyzer": {
            "provider_calls": 1,
            "estimated_cost_microusd": None,
            "provider_call_status": "within_limit",
            "estimated_cost_status": "disabled",
            "cost_rate_source": None,
        },
        "verifier": {
            "status": "deferred_until_analyzer_results",
            "maximum_input_bytes": 1_000_000,
            "maximum_prompt_bytes": 1_000_000,
            "maximum_provider_calls": 10,
            "maximum_estimated_cost_microusd": None,
            "maximum_runtime_seconds": 30,
        },
        "call_cost_status": "unknown",
    }
    assert prepared["inference"]["analyzer"]["adapter_model_id"] == LOCAL_LLM_MODEL
    assert prepared["inference"]["verifier"]["adapter_model_id"] == (
        "backstitch-acceptance-verifier"
    )
    assert (
        prepared["inference"]["verifier"]["stable_model_id"]
        != prepared["inference"]["analyzer"]["stable_model_id"]
    )

    first_packets = tmp_path / "first-packets.jsonl"
    first_packet_report = tmp_path / "first-packets-report.json"
    first_results = tmp_path / "first-results.jsonl"
    first_report = tmp_path / "first-analysis-report.json"
    first = run_installed_cli(
        "analyze",
        "--repo-root",
        str(tmp_path),
        "--packets-output",
        str(first_packets),
        "--packet-report-output",
        str(first_packet_report),
        "--output",
        str(first_results),
        "--report",
        str(first_report),
        "--format",
        "json",
        environment=environment,
    )
    assert first.returncode == 0, first.stderr
    first_report_value = json.loads(first_report.read_text(encoding="utf-8"))
    assert first_report_value["provider_calls"] == 1
    assert first_report_value["cache_misses"] == 1
    first_events = _read_ledger(ledger)
    assert [event["role"] for event in first_events] == ["analyzer"]
    assert first_events[0]["request_options"] == {
        "max_tokens": 512,
        "seed": 42,
        "temperature": 0.0,
    }

    replay_results = tmp_path / "replay-results.jsonl"
    replay_report = tmp_path / "replay-analysis-report.json"
    replay = run_installed_cli(
        "--repo-root",
        str(tmp_path),
        "--packets-output",
        str(tmp_path / "replay-packets.jsonl"),
        "--packet-report-output",
        str(tmp_path / "replay-packets-report.json"),
        "--output",
        str(replay_results),
        "--report",
        str(replay_report),
        "--format",
        "json",
        cwd=tmp_path,
        environment=environment,
    )
    assert replay.returncode == 0, replay.stderr
    replay_report_value = json.loads(replay_report.read_text(encoding="utf-8"))
    assert replay_report_value["provider_calls"] == 0
    assert replay_report_value["cache_hits"] == 1
    assert replay_results.read_bytes() == first_results.read_bytes()
    assert _read_ledger(ledger) == first_events

    historical_results = tmp_path / "historical-results.jsonl"
    historical_report = tmp_path / "historical-analysis-report.json"
    historical = run_installed_cli(
        "analyze",
        "--packets",
        str(first_packets),
        "--packet-report",
        str(first_packet_report),
        "--output",
        str(historical_results),
        "--report",
        str(historical_report),
        "--format",
        "json",
        cwd=tmp_path,
        environment=environment,
    )
    assert historical.returncode == 0, historical.stderr
    historical_value = json.loads(historical_report.read_text(encoding="utf-8"))
    assert historical_value["scope"] == "historical_snapshot"
    assert historical_value["provider_calls"] == 0
    assert historical_results.read_bytes() == first_results.read_bytes()
    assert _read_ledger(ledger) == first_events

    miss_results = tmp_path / "miss-results.jsonl"
    miss_report = tmp_path / "miss-analysis-report.json"
    miss = run_installed_cli(
        "analyze",
        "--repo-root",
        str(tmp_path),
        "--option",
        "analyze.search_epoch",
        '"fixture-v2"',
        "--output",
        str(miss_results),
        "--report",
        str(miss_report),
        "--format",
        "json",
        environment=environment,
    )
    assert miss.returncode == 0, miss.stderr
    miss_value = json.loads(miss_report.read_text(encoding="utf-8"))
    assert miss_value["provider_calls"] == 1
    assert miss_value["cache_misses"] == 1
    miss_events = _read_ledger(ledger)
    assert len(miss_events) == len(first_events) + 1

    deterministic_path = tmp_path / "deterministic-report.json"
    checked_to_file = run_installed_cli(
        "check",
        "--repo-root",
        str(tmp_path),
        "--format",
        "json",
        "--output",
        str(deterministic_path),
        environment=environment,
    )
    assert checked_to_file.returncode == 0, checked_to_file.stderr
    summarized = run_installed_cli(
        "summarize-analysis",
        "--deterministic-report",
        str(deterministic_path),
        "--analysis-results",
        str(first_results),
        environment=environment,
    )
    assert summarized.returncode == 0, summarized.stderr
    assert obligation_id in summarized.stdout

    doctor = run_installed_cli(
        "doctor",
        "--format",
        "json",
        cwd=tmp_path,
        environment=environment,
    )
    assert doctor.returncode == 0, doctor.stderr
    doctor_value = json.loads(doctor.stdout)
    assert any(
        check["name"] == "model" and check["status"] == "pass"
        for check in doctor_value["checks"]
    )

    eval_output = tmp_path / "semantic-eval-report.json"
    eval_environment = dict(environment)
    eval_environment["BACKSTITCH_DOGFOOD_MODEL_MODE"] = "eval"
    evaluated = run_installed_cli(
        "eval",
        "--corpus",
        str(REPO_ROOT / "tests/semantic_eval/v3/manifest.json"),
        "--output",
        str(eval_output),
        "--config",
        str(tmp_path / ".backstitch.toml"),
        environment=eval_environment,
    )
    assert evaluated.returncode in {0, 1}, evaluated.stderr
    eval_value = json.loads(eval_output.read_text(encoding="utf-8"))
    assert eval_value["artifact"] == "backstitch-verification-eval-report"
    eval_events = _read_ledger(ledger)
    assert [event["role"] for event in eval_events[len(miss_events) :]] == [
        "analyzer",
        "analyzer",
        "verifier",
    ]
    assert [event["model_id"] for event in eval_events[len(miss_events) :]] == [
        LOCAL_LLM_MODEL,
        LOCAL_LLM_MODEL,
        "backstitch-acceptance-verifier",
    ]
    assert eval_value["operational"]["provider_calls"] == 3

    cleanup_key = "7" * 64
    lock_path = tmp_path / ".backstitch/semantic-cache/locks" / f"{cleanup_key}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_bytes(b"legacy abandoned lock")
    old = (datetime.now(UTC) - timedelta(hours=2)).timestamp()
    os.utime(lock_path, (old, old))
    cleaned = run_installed_cli(
        "cache",
        "cleanup-lock",
        "--cache-path",
        str(tmp_path / ".backstitch/semantic-cache"),
        "--analysis-key",
        cleanup_key,
        "--lock-stale-seconds",
        "1",
        "--reason",
        "hermetic dogfood abandoned lock",
        environment=environment,
    )
    assert cleaned.returncode == 0, cleaned.stderr
    assert Path(cleaned.stdout.strip()).is_file()
    assert not lock_path.exists()

    preparation_projection = {
        key: prepared[key]
        for key in (
            "ready",
            "config",
            "inference",
            "packet_plan",
            "readiness",
            "snapshot",
        )
    }
    analyzer_events = [event for event in eval_events if event["role"] == "analyzer"]
    verifier_events = [event for event in eval_events if event["role"] == "verifier"]
    receipts = {
        "resolved_config": shown,
        "preparation": {
            "value": preparation_projection,
            "current_snapshot_hash": first_report_value["source_snapshot"][
                "snapshot_hash"
            ],
        },
        "packet_plan": {
            "value": prepared["packet_plan"],
            "report": json.loads(standalone_report.read_text(encoding="utf-8")),
            "actual_packet_jsonl_sha256": hashlib.sha256(
                standalone_packets.read_bytes()
            ).hexdigest(),
        },
        "analyzer_adapter_calls": analyzer_events,
        "verifier_adapter_calls": verifier_events,
        "cache_decisions": {
            "first": {
                "hits": first_report_value["cache_hits"],
                "misses": first_report_value["cache_misses"],
                "calls": first_report_value["provider_calls"],
            },
            "exact_replay": {
                "hits": replay_report_value["cache_hits"],
                "misses": replay_report_value["cache_misses"],
                "calls": replay_report_value["provider_calls"],
            },
            "search_epoch_miss": {
                "hits": miss_value["cache_hits"],
                "misses": miss_value["cache_misses"],
                "calls": miss_value["provider_calls"],
            },
        },
        "currentness": {
            "current": {
                "scope": first_report_value["scope"],
                "status": first_report_value["artifact_currentness"],
            },
            "historical": {
                "scope": historical_value["scope"],
                "status": historical_value["artifact_currentness"],
            },
        },
        "historical_packet_loader": {
            "packet_report_selection_status": json.loads(
                first_packet_report.read_text(encoding="utf-8")
            )["selection_status"],
            "analysis_scope": historical_value["scope"],
            "provider_calls": historical_value["provider_calls"],
            "result_bytes_match": (
                historical_results.read_bytes() == first_results.read_bytes()
            ),
        },
        "summary_input_loader": {
            "command_exit_code": summarized.returncode,
            "obligation_id": obligation_id
            if obligation_id in summarized.stdout
            else None,
        },
    }
    _assert_green_seam_receipts(receipts)


def test_installed_analysis_rejects_mutation_during_model_execution(
    tmp_path: Path,
) -> None:
    """A model-time source mutation must not publish current artifacts."""

    _write_local_model_repo(tmp_path)
    ledger = tmp_path / "local-model-ledger.jsonl"
    environment = local_llm_environment(ledger)
    environment["BACKSTITCH_DOGFOOD_MUTATE_ON_CALL"] = str(tmp_path / "pkg/core.py")
    artifacts = (
        tmp_path / "packets.jsonl",
        tmp_path / "packet-report.json",
        tmp_path / "results.jsonl",
        tmp_path / "analysis-report.json",
    )

    analyzed = run_installed_cli(
        "analyze",
        "--repo-root",
        str(tmp_path),
        "--packets-output",
        str(artifacts[0]),
        "--packet-report-output",
        str(artifacts[1]),
        "--output",
        str(artifacts[2]),
        "--report",
        str(artifacts[3]),
        "--format",
        "json",
        environment=environment,
    )

    assert analyzed.returncode == 2
    assert analyzed.stdout == ""
    assert analyzed.stderr == (
        "backstitch: error: repository source changed during current analysis\n"
    )
    assert [event["role"] for event in _read_ledger(ledger)] == ["analyzer"]
    assert not any(path.exists() for path in artifacts)


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="stdlib has no Windows pseudoterminal for the TTY-only progress contract",
)
def test_installed_analysis_rejects_mutation_after_preparation(
    tmp_path: Path,
) -> None:
    """The installed TTY event exposes the pre-execution recapture boundary."""

    import pty

    _write_local_model_repo(tmp_path)
    ledger = tmp_path / "local-model-ledger.jsonl"
    environment = local_llm_environment(ledger)
    artifacts = (
        tmp_path / "packets.jsonl",
        tmp_path / "packet-report.json",
        tmp_path / "results.jsonl",
        tmp_path / "analysis-report.json",
    )
    executable = Path(sys.executable).with_name("backstitch")
    master_fd, slave_fd = pty.openpty()
    process = subprocess.Popen(
        [
            str(executable),
            "analyze",
            "--repo-root",
            str(tmp_path),
            "--packets-output",
            str(artifacts[0]),
            "--packet-report-output",
            str(artifacts[1]),
            "--output",
            str(artifacts[2]),
            "--report",
            str(artifacts[3]),
        ],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=slave_fd,
        text=True,
    )
    os.close(slave_fd)
    stderr_bytes = b""
    progress_prefix = b"backstitch: progress packet_accounting "
    deadline = time.monotonic() + 30
    stopped = False
    try:
        while progress_prefix not in stderr_bytes:
            remaining = deadline - time.monotonic()
            assert remaining > 0, stderr_bytes.decode(errors="replace")
            readable, _, _ = select.select([master_fd], [], [], remaining)
            assert readable, stderr_bytes.decode(errors="replace")
            stderr_bytes += os.read(master_fd, 4096)

        os.kill(process.pid, signal.SIGSTOP)
        _, stop_status = os.waitpid(process.pid, os.WUNTRACED)
        assert os.WIFSTOPPED(stop_status)
        stopped = True
        assert _read_ledger(ledger) == []
        (tmp_path / "pkg/core.py").write_text(
            (tmp_path / "pkg/core.py").read_text(encoding="utf-8")
            + "\n# mutated after semantic preparation\n",
            encoding="utf-8",
        )
        os.kill(process.pid, signal.SIGCONT)
        stopped = False
        execution_deadline = time.monotonic() + 30
        while process.poll() is None:
            assert time.monotonic() < execution_deadline
            readable, _, _ = select.select([master_fd], [], [], 0.1)
            if readable:
                stderr_bytes += os.read(master_fd, 4096)
        while True:
            try:
                chunk = os.read(master_fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            stderr_bytes += chunk
        assert process.stdout is not None
        stdout = process.stdout.read()
    finally:
        os.close(master_fd)
        if stopped and process.poll() is None:
            os.kill(process.pid, signal.SIGCONT)
        if process.poll() is None:
            process.kill()
            process.wait()

    stderr = stderr_bytes.decode(errors="replace").replace("\r\n", "\n")
    assert process.returncode == 2
    assert stdout == ""
    assert "backstitch: progress packet_accounting " in stderr
    assert "repository source changed before current analysis execution" in stderr
    assert "Traceback" not in stderr
    assert _read_ledger(ledger) == []
    assert not any(path.exists() for path in artifacts)


def test_isolated_self_repository_dogfood_uses_committed_budgets(
    tmp_path: Path,
) -> None:
    repo = _copy_self_repository(tmp_path / "repo")
    artifacts = repo / ".backstitch/dogfood"
    artifacts.mkdir(parents=True)
    ledger = artifacts / "local-model-ledger.jsonl"
    environment = local_llm_environment(ledger)
    deterministic_report = artifacts / "deterministic-report.json"

    checked = run_installed_cli(
        "check",
        "--repo-root",
        str(repo),
        "--show-suppressions",
        "--format",
        "json",
        "--output",
        str(deterministic_report),
        environment=environment,
    )
    assert checked.returncode == 0, checked.stderr
    assert checked.stdout == ""
    deterministic = json.loads(deterministic_report.read_text(encoding="utf-8"))
    assert deterministic["summary"]["errors"] == 0
    assert deterministic["summary"]["warnings"] == 0

    preflight = run_installed_cli(
        "analyze",
        "--repo-root",
        str(repo),
        "--preflight",
        "--format",
        "json",
        environment=environment,
    )
    assert preflight.returncode == 0, preflight.stdout + preflight.stderr
    prepared = json.loads(preflight.stdout)
    assert prepared["schema_version"] == 2
    assert prepared["ready"] is True
    assert prepared["packet_plan"]["complete"] is True
    assert prepared["packet_plan"]["status"] == "complete"
    assert prepared["budgets"]["projection"] == "conservative_cold"
    assert prepared["budgets"]["limits"] == {
        "maximum_packets": 128,
        "maximum_prompt_bytes": 40_000_000,
        "maximum_input_bytes": 1_600_000,
        "maximum_provider_calls": 128,
        "maximum_estimated_cost_microusd": 30_000_000,
        "maximum_runtime_seconds": 1_800,
    }
    assert (
        prepared["budgets"]["analyzer"]["provider_calls"]
        == (prepared["packet_plan"]["packet_count"])
    )
    assert prepared["budgets"]["analyzer"]["provider_call_status"] == "within_limit"
    assert prepared["budgets"]["analyzer"]["estimated_cost_microusd"] > 0
    assert (
        prepared["budgets"]["analyzer"]["estimated_cost_microusd"]
        <= prepared["budgets"]["limits"]["maximum_estimated_cost_microusd"]
    )
    assert prepared["budgets"]["analyzer"]["estimated_cost_status"] == "within_limit"
    assert prepared["budgets"]["analyzer"]["cost_rate_source"].startswith(
        "OpenAI GPT-5.6 Luna model page"
    )
    assert prepared["budgets"]["verifier"] == {
        "status": "disabled",
        "maximum_input_bytes": None,
        "maximum_prompt_bytes": None,
        "maximum_provider_calls": None,
        "maximum_estimated_cost_microusd": None,
        "maximum_runtime_seconds": None,
    }
    assert prepared["budgets"]["call_cost_status"] == "within_limits"
    assert prepared["inference"]["analyzer"]["stable_model_id"] == (
        "pkg:service/openai.com/gpt-5.6-luna"
    )
    assert prepared["inference"]["analyzer"]["adapter_model_id"] == LOCAL_LLM_MODEL

    packets = artifacts / "packets.jsonl"
    packet_report = artifacts / "packet-report.json"
    generated = run_installed_cli(
        "packets",
        "--repo-root",
        str(repo),
        "--kind",
        "all",
        "--output",
        str(packets),
        "--report",
        str(packet_report),
        environment=environment,
    )
    assert generated.returncode == 0, generated.stderr
    packet_report_value = json.loads(packet_report.read_text(encoding="utf-8"))
    assert all(
        packet_report_value["kind_counts"]["emitted"][kind] > 0
        for kind in ("section", "invariant", "suppression")
    )

    first_results = artifacts / "results.jsonl"
    first_report = artifacts / "analysis-report.json"
    first = run_installed_cli(
        "analyze",
        "--repo-root",
        str(repo),
        "--packets-output",
        str(artifacts / "current-packets.jsonl"),
        "--packet-report-output",
        str(artifacts / "current-packet-report.json"),
        "--output",
        str(first_results),
        "--report",
        str(first_report),
        "--format",
        "json",
        environment=environment,
    )
    assert first.returncode == 0, first.stderr
    first_value = json.loads(first_report.read_text(encoding="utf-8"))
    assert first_value["scope"] == "current_repository"
    assert first_value["artifact_currentness"] == "current"
    assert first_value["provider_calls"] == packet_report_value["packet_count"]
    first_events = _read_ledger(ledger)
    assert len(first_events) == first_value["provider_calls"]
    assert {event["model_id"] for event in first_events} == {LOCAL_LLM_MODEL}

    replay_results = artifacts / "replay-results.jsonl"
    replay_report = artifacts / "replay-analysis-report.json"
    replay = run_installed_cli(
        "--repo-root",
        str(repo),
        "--packets-output",
        str(artifacts / "replay-packets.jsonl"),
        "--packet-report-output",
        str(artifacts / "replay-packet-report.json"),
        "--output",
        str(replay_results),
        "--report",
        str(replay_report),
        "--format",
        "json",
        cwd=repo,
        environment=environment,
    )
    assert replay.returncode == 0, replay.stderr
    replay_value = json.loads(replay_report.read_text(encoding="utf-8"))
    assert replay_value["provider_calls"] == 0
    assert replay_value["cache_hits"] == packet_report_value["packet_count"]
    assert replay_results.read_bytes() == first_results.read_bytes()
    assert _read_ledger(ledger) == first_events

    historical_results = artifacts / "historical-results.jsonl"
    historical_report = artifacts / "historical-analysis-report.json"
    historical = run_installed_cli(
        "analyze",
        "--packets",
        str(artifacts / "current-packets.jsonl"),
        "--packet-report",
        str(artifacts / "current-packet-report.json"),
        "--output",
        str(historical_results),
        "--report",
        str(historical_report),
        "--format",
        "json",
        cwd=repo,
        environment=environment,
    )
    assert historical.returncode == 0, historical.stderr
    historical_value = json.loads(historical_report.read_text(encoding="utf-8"))
    assert historical_value["scope"] == "historical_snapshot"
    assert historical_value["artifact_currentness"] == "unverifiable"
    assert historical_value["provider_calls"] == 0
    assert historical_results.read_bytes() == first_results.read_bytes()
    assert _read_ledger(ledger) == first_events

    first_result_rows = [
        json.loads(line)
        for line in first_results.read_text(encoding="utf-8").splitlines()
    ]
    assert first_result_rows
    summary_obligation = first_result_rows[0]["packet_id"]
    summarized = run_installed_cli(
        "summarize-analysis",
        "--deterministic-report",
        str(deterministic_report),
        "--analysis-results",
        str(first_results),
        cwd=repo,
        environment=environment,
    )
    assert summarized.returncode == 0, summarized.stderr
    assert summary_obligation in summarized.stdout
    assert _read_ledger(ledger) == first_events
