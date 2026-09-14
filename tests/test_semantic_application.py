"""Typed semantic application workflow and CLI equivalence.

Spec: docs/specs/02-backstitch-core.md [SC-5], [SC-7], [SC-10]
Spec: docs/specs/06-semantic-gates.md [SEM-1], [SEM-7]
Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-5.1], [EVC-8.7],
[EVC-9]
Plan: docs/plans/2026-07-29-architecture-quality-remediation-plan.md Slice 5
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import replace
from functools import wraps
from pathlib import Path
from typing import Any, ParamSpec, TypeVar

import pytest

from backstitch import cli, semantic_application
from backstitch.operation_progress import ProgressEvent, ProgressSink
from backstitch.profiles import configured_profile
from backstitch.semantic_analysis import (
    SemanticAnalysisRun,
    resolve_semantic_settings,
    resolve_verification_settings,
)
from backstitch.semantic_application import (
    SemanticApplicationFailure,
    SemanticApplicationRequest,
    SemanticApplicationResult,
    analyze_semantics,
    preflight_semantics,
)
from backstitch.semantic_cache import ProviderAdapter
from backstitch.semantic_policy import materialize_semantic_policy
from backstitch.settings import BackstitchSettings, resolve_config

_CallParams = ParamSpec("_CallParams")
_CallResult = TypeVar("_CallResult")


def _counted_call(
    call: Callable[_CallParams, _CallResult],
    record_call: Callable[[], None],
) -> Callable[_CallParams, _CallResult]:
    @wraps(call)
    def counted(*args: _CallParams.args, **kwargs: _CallParams.kwargs) -> _CallResult:
        record_call()
        return call(*args, **kwargs)

    return counted


def _write_all_skipped_repo(root: Path) -> None:
    for directory in ("docs/specs", "docs/plans", "backstitch", "tests"):
        root.joinpath(directory).mkdir(parents=True, exist_ok=True)
    root.joinpath("docs/specs/01-core.md").write_text(
        "# Core\n\n"
        "## Contract [CORE-1] <!-- backstitch: skip-obligation [CORE-1] "
        '"External owner." -->\n\n'
        "The external owner supplies this behavior.\n",
        encoding="utf-8",
    )


def _write_executable_repo(root: Path) -> None:
    for directory in ("docs/specs", "docs/plans", "backstitch", "tests"):
        root.joinpath(directory).mkdir(parents=True, exist_ok=True)
    root.joinpath("docs/specs/01-core.md").write_text(
        "# Core\n\n"
        "## Contract [CORE-1]\n\n"
        "The implementation returns one.\n\n"
        "_Implementation mapping_:\n\n"
        "- `backstitch/impl.py::fulfill`\n"
        "- `tests/test_impl.py::test_fulfill`\n",
        encoding="utf-8",
    )
    root.joinpath("backstitch/impl.py").write_text(
        "def fulfill() -> int:\n"
        '    """Spec: docs/specs/01-core.md [CORE-1]"""\n'
        "    return 1\n",
        encoding="utf-8",
    )
    root.joinpath("tests/test_impl.py").write_text(
        "from backstitch.impl import fulfill\n\n\n"
        "def test_fulfill() -> None:\n"
        '    """Spec: docs/specs/01-core.md [CORE-1]"""\n'
        "    assert fulfill() == 1\n",
        encoding="utf-8",
    )


def _request(
    settings: BackstitchSettings,
    *,
    repo_root: Path | None = None,
    packets_path: Path | None = None,
    packet_report_path: Path | None = None,
    compare_repo_root: Path | None = None,
    packets_output_path: Path | None = None,
    packet_report_output_path: Path | None = None,
    result_output_path: Path | None = None,
    report_output_path: Path | None = None,
    progress_sink: ProgressSink | None = None,
) -> SemanticApplicationRequest:
    resolved = resolve_semantic_settings(settings.analyze)
    return SemanticApplicationRequest(
        settings=settings,
        profile=configured_profile(settings),
        semantic_settings=resolved,
        policy=materialize_semantic_policy(
            settings.diagnostics,
            settings.policy_rule_origins,
            settings.config_layers,
        ),
        adapter_factory=None,
        verification_settings=resolve_verification_settings(
            settings.verify,
            resolved,
        ),
        evaluation_settings=getattr(settings.verify, "eval", None),
        verification_adapter_factory=None,
        repo_root=repo_root,
        packets_path=packets_path,
        packet_report_path=packet_report_path,
        compare_repo_root=compare_repo_root,
        packets_output_path=packets_output_path,
        packet_report_output_path=packet_report_output_path,
        result_output_path=result_output_path,
        report_output_path=report_output_path,
        progress_sink=progress_sink,
    )


def _settings(anchor: Path) -> BackstitchSettings:
    return resolve_config(
        anchor,
        use_repo_config=False,
        environment={},
        invocation_command="analyze",
    )


def test_preflight_schema_two_projects_closed_provider_free_budgets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_executable_repo(tmp_path)
    cache_reads = 0
    packet_plans = 0
    real_plan_packets = (
        semantic_application.analysis_packets.plan_source_aligned_packets
    )

    def record_packet_plan() -> None:
        nonlocal packet_plans
        packet_plans += 1

    count_packet_plan = _counted_call(real_plan_packets, record_packet_plan)

    def forbidden_cache_read(*_args: object, **_kwargs: object) -> object:
        nonlocal cache_reads
        cache_reads += 1
        raise AssertionError("provider-free preflight read semantic cache state")

    monkeypatch.setattr(
        semantic_application.semantic_analysis,
        "inspect_semantic_cache",
        forbidden_cache_read,
    )
    monkeypatch.setattr(
        semantic_application.semantic_analysis,
        "inspect_verification_cache",
        forbidden_cache_read,
    )
    monkeypatch.setattr(
        semantic_application.analysis_packets,
        "plan_source_aligned_packets",
        count_packet_plan,
    )

    outcome = preflight_semantics(_request(_settings(tmp_path), repo_root=tmp_path))

    assert not isinstance(outcome, SemanticApplicationFailure)
    assert outcome.exit_code == 0
    assert cache_reads == 0
    assert packet_plans == 1
    assert set(outcome.document) == {
        "schema_version",
        "operation",
        "ready",
        "selected_command",
        "config",
        "snapshot",
        "readiness",
        "packet_plan",
        "inference",
        "budgets",
        "outputs",
        "problems",
    }
    assert outcome.document["schema_version"] == 2
    budgets = outcome.document["budgets"]
    assert isinstance(budgets, dict)
    assert set(budgets) == {
        "projection",
        "limits",
        "analyzer",
        "verifier",
        "call_cost_status",
    }
    assert budgets["projection"] == "conservative_cold"
    assert budgets["analyzer"] == {
        "provider_calls": 1,
        "estimated_cost_microusd": None,
        "provider_call_status": "within_limit",
        "estimated_cost_status": "disabled",
        "cost_rate_source": None,
    }
    assert budgets["verifier"] == {
        "status": "disabled",
        "maximum_input_bytes": None,
        "maximum_prompt_bytes": None,
        "maximum_provider_calls": None,
        "maximum_estimated_cost_microusd": None,
        "maximum_runtime_seconds": None,
    }
    assert budgets["call_cost_status"] == "within_limits"
    assert cli._render_semantic_preflight(outcome) == (
        "analysis preflight ready: 1 packet(s); "
        "cold analyzer 1/1000 calls (within_limit); cost disabled; "
        "verifier disabled\n"
    )


def test_preflight_fires_invalid_cost_contract_before_provider_work(
    tmp_path: Path,
) -> None:
    _write_executable_repo(tmp_path)
    request = _request(_settings(tmp_path), repo_root=tmp_path)
    request = replace(
        request,
        semantic_settings=replace(
            request.semantic_settings,
            provider_identity=replace(
                request.semantic_settings.provider_identity,
                plugin_id="unreviewed",
            ),
            inference=None,
            maximum_estimated_cost_microusd=1,
            input_cost_microusd_per_million_tokens=1,
            output_cost_microusd_per_million_tokens=1,
            input_token_overhead=256,
            cost_rate_source="controlled test rates",
        ),
    )

    outcome = preflight_semantics(request)

    assert not isinstance(outcome, SemanticApplicationFailure)
    assert outcome.exit_code == 2
    assert outcome.document["problems"] == [
        {
            "stage": "config",
            "code": "INVALID_COST_CONTRACT",
            "details": {},
            "action": "Correct the reported preparation problem, then rerun preflight.",
        }
    ]


def test_preflight_fires_exact_no_cache_budget_exhaustion(
    tmp_path: Path,
) -> None:
    _write_executable_repo(tmp_path)
    request = _request(_settings(tmp_path), repo_root=tmp_path)
    request = replace(
        request,
        semantic_settings=replace(
            request.semantic_settings,
            cache_mode="off",
            maximum_provider_calls=0,
        ),
    )

    outcome = preflight_semantics(request)

    assert not isinstance(outcome, SemanticApplicationFailure)
    assert outcome.exit_code == 2
    budgets = outcome.document["budgets"]
    assert isinstance(budgets, dict)
    assert budgets["analyzer"] == {
        "provider_calls": 1,
        "estimated_cost_microusd": None,
        "provider_call_status": "exceeds",
        "estimated_cost_status": "disabled",
        "cost_rate_source": None,
    }
    assert budgets["call_cost_status"] == "exceeds"
    assert outcome.document["problems"] == [
        {
            "stage": "budget",
            "code": "COLD_BUDGET_EXHAUSTED",
            "details": budgets["analyzer"],
            "action": "Correct the reported preparation problem, then rerun preflight.",
        }
    ]


def test_current_application_matches_cli_report_bytes_and_exit(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_all_skipped_repo(tmp_path)
    settings = _settings(tmp_path)
    outcome = analyze_semantics(_request(settings, repo_root=tmp_path))
    assert isinstance(outcome, SemanticApplicationResult)

    args = cli.build_parser().parse_args(
        [
            "analyze",
            "--repo-root",
            str(tmp_path),
            "--no-config",
            "--format",
            "json",
        ]
    )
    exit_code = cli._cmd_analyze(args, settings)
    captured = capsys.readouterr()

    assert exit_code == outcome.run.exit_code == 0
    assert captured.out.encode("utf-8") == outcome.run.report_json
    assert captured.err == "".join(f"{line}\n" for line in outcome.run.stderr_lines)


def test_historical_cli_replay_reports_status_and_exit(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = tmp_path / "repo"
    _write_all_skipped_repo(repo)
    packets_path = tmp_path / "artifacts/packets.jsonl"
    packet_report_path = tmp_path / "artifacts/packet-report.json"
    settings = _settings(repo)
    current = analyze_semantics(
        _request(
            settings,
            repo_root=repo,
            packets_output_path=packets_path,
            packet_report_output_path=packet_report_path,
        )
    )
    assert isinstance(current, SemanticApplicationResult)
    replay = analyze_semantics(
        _request(
            settings,
            packets_path=packets_path,
            packet_report_path=packet_report_path,
        )
    )
    assert isinstance(replay, SemanticApplicationResult)

    args = cli.build_parser().parse_args(
        [
            "analyze",
            "--packets",
            str(packets_path),
            "--packet-report",
            str(packet_report_path),
            "--no-config",
            "--format",
            "json",
        ]
    )
    exit_code = cli._cmd_analyze(args, settings)
    captured = capsys.readouterr()

    assert exit_code == replay.run.exit_code == 0
    assert json.loads(captured.out)["semantic_status"] == "historical_replay"


def test_current_exit_two_suppresses_report_but_historical_replay_renders_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report_json = b'{"result_count":0,"status":"incomplete"}\n'
    run = SemanticAnalysisRun(
        results=(),
        diagnostics=(),
        problems=(),
        result_jsonl=b"",
        report={"result_count": 0, "status": "incomplete"},
        report_json=report_json,
        stderr_lines=("problem",),
        exit_code=2,
    )
    monkeypatch.setattr(
        semantic_application,
        "analyze_semantics",
        lambda _request: SemanticApplicationResult(run),
    )
    settings = _settings(tmp_path)
    current_args = cli.build_parser().parse_args(
        [
            "analyze",
            "--repo-root",
            str(tmp_path),
            "--no-config",
            "--format",
            "json",
        ]
    )

    assert cli._cmd_analyze(current_args, settings) == 2
    current = capsys.readouterr()
    assert current.out == ""
    assert current.err == "problem\n"

    historical_args = cli.build_parser().parse_args(
        [
            "analyze",
            "--packets",
            str(tmp_path / "input-packets.jsonl"),
            "--packet-report",
            str(tmp_path / "input-report.json"),
            "--no-config",
            "--format",
            "json",
        ]
    )
    assert cli._cmd_analyze(historical_args, settings) == 2
    historical = capsys.readouterr()
    assert historical.out.encode("utf-8") == report_json
    assert historical.err == "problem\n"


def test_current_exit_two_does_not_publish_application_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_all_skipped_repo(tmp_path)
    run = SemanticAnalysisRun(
        results=(),
        diagnostics=(),
        problems=(),
        result_jsonl=b"partial results\n",
        report={"result_count": 0, "status": "incomplete"},
        report_json=b'{"result_count":0,"status":"incomplete"}\n',
        stderr_lines=("problem",),
        exit_code=2,
    )
    monkeypatch.setattr(
        semantic_application.semantic_analysis,
        "run_semantic_analysis",
        lambda _request: run,
    )
    publication_calls = 0

    def forbidden_publication(*_args: object, **_kwargs: object) -> object:
        nonlocal publication_calls
        publication_calls += 1
        raise AssertionError("exit-2 current run reached artifact publication")

    monkeypatch.setattr(
        semantic_application.artifact_publication,
        "publish_artifact_set",
        forbidden_publication,
    )
    output_paths = (
        tmp_path / "artifacts/packets.jsonl",
        tmp_path / "artifacts/packet-report.json",
        tmp_path / "artifacts/results.jsonl",
        tmp_path / "artifacts/analysis-report.json",
    )

    outcome = analyze_semantics(
        _request(
            _settings(tmp_path),
            repo_root=tmp_path,
            packets_output_path=output_paths[0],
            packet_report_output_path=output_paths[1],
            result_output_path=output_paths[2],
            report_output_path=output_paths[3],
        )
    )

    assert outcome == SemanticApplicationResult(run)
    assert publication_calls == 0
    assert all(not path.exists() for path in output_paths)


def test_validation_precedes_provider_construction_and_cli_maps_exact_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import backstitch.analysis_llm as analysis_llm

    _write_all_skipped_repo(tmp_path)
    output = tmp_path / "backstitch/analysis.jsonl"
    settings = _settings(tmp_path)
    outcome = analyze_semantics(
        _request(
            settings,
            repo_root=tmp_path,
            result_output_path=output,
        )
    )
    assert isinstance(outcome, SemanticApplicationFailure)
    assert outcome.stage == "validation"

    constructions = 0

    def forbidden_adapter(*args: object, **kwargs: object) -> object:
        nonlocal constructions
        constructions += 1
        raise AssertionError("validation failure constructed a provider")

    monkeypatch.setattr(
        analysis_llm,
        "default_provider_adapter",
        forbidden_adapter,
    )
    args = cli.build_parser().parse_args(
        [
            "analyze",
            "--repo-root",
            str(tmp_path),
            "--no-config",
            "--output",
            str(output),
        ]
    )
    exit_code = cli._cmd_analyze(args, settings)
    captured = capsys.readouterr()

    assert exit_code == 2
    assert constructions == 0
    assert captured.out == ""
    assert captured.err == f"backstitch: error: {outcome.message}\n"


def test_cache_parent_of_source_root_is_rejected_before_provider_or_writes(
    tmp_path: Path,
) -> None:
    _write_all_skipped_repo(tmp_path)
    source = tmp_path / "docs/specs/01-core.md"
    before = source.read_bytes()
    tmp_path.joinpath(".backstitch.toml").write_text(
        '[analyze]\ncache_path = "."\n', encoding="utf-8"
    )
    settings = resolve_config(
        tmp_path,
        environment={},
        invocation_command="analyze",
    )
    paths_before = {path.relative_to(tmp_path) for path in tmp_path.rglob("*")}
    constructions = 0

    def forbidden_adapter() -> ProviderAdapter:
        nonlocal constructions
        constructions += 1
        raise AssertionError("overlap failure constructed a provider")

    outcome = analyze_semantics(
        replace(
            _request(settings, repo_root=tmp_path),
            adapter_factory=forbidden_adapter,
        )
    )

    assert isinstance(outcome, SemanticApplicationFailure)
    assert outcome.stage == "validation"
    assert "mutable path overlaps a semantic input root" in outcome.message
    assert constructions == 0
    assert source.read_bytes() == before
    assert {path.relative_to(tmp_path) for path in tmp_path.rglob("*")} == paths_before


def test_currentness_recapture_precedes_every_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_all_skipped_repo(tmp_path)
    output = tmp_path / "artifacts/analysis.jsonl"

    def mutate_repository(
        _request: object,
    ) -> SemanticAnalysisRun:
        tmp_path.joinpath("docs/specs/01-core.md").write_text(
            "# Core changed during analysis\n",
            encoding="utf-8",
        )
        return SemanticAnalysisRun((), (), (), b"", {}, b"", (), 0)

    monkeypatch.setattr(
        semantic_application.semantic_analysis,
        "run_semantic_analysis",
        mutate_repository,
    )

    outcome = analyze_semantics(
        _request(
            _settings(tmp_path),
            repo_root=tmp_path,
            result_output_path=output,
        )
    )

    assert outcome == SemanticApplicationFailure(
        stage="currentness",
        message="repository source changed during current analysis",
    )
    assert not output.exists()


def test_source_change_after_preparation_precedes_semantic_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_all_skipped_repo(tmp_path)
    real_capture = semantic_application.obligation_runtime.capture_obligation_snapshot
    captures = 0

    def mutate_before_second_capture(*args: Any, **kwargs: Any) -> Any:
        nonlocal captures
        captures += 1
        if captures == 2:
            tmp_path.joinpath("docs/specs/01-core.md").write_text(
                "# Core changed before execution\n",
                encoding="utf-8",
            )
        return real_capture(*args, **kwargs)

    def forbidden_execution(_request: object) -> object:
        raise AssertionError("changed preparation reached semantic execution")

    monkeypatch.setattr(
        semantic_application.obligation_runtime,
        "capture_obligation_snapshot",
        mutate_before_second_capture,
    )
    monkeypatch.setattr(
        semantic_application.semantic_analysis,
        "run_semantic_analysis",
        forbidden_execution,
    )

    outcome = analyze_semantics(_request(_settings(tmp_path), repo_root=tmp_path))

    assert outcome == SemanticApplicationFailure(
        stage="currentness",
        message="repository source changed before current analysis execution",
    )
    assert captures == 2


def test_progress_boundary_can_invalidate_preparation_before_provider_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_all_skipped_repo(tmp_path)
    events: list[ProgressEvent] = []
    provider_calls = 0

    def mutate_at_accounting(event: ProgressEvent) -> None:
        events.append(event)
        if event.phase == "packet_accounting":
            tmp_path.joinpath("docs/specs/01-core.md").write_text(
                "# Core changed after preparation\n",
                encoding="utf-8",
            )

    def forbidden_execution(_request: Any) -> Any:
        nonlocal provider_calls
        provider_calls += 1
        raise AssertionError("invalidated preparation reached provider work")

    monkeypatch.setattr(
        semantic_application.semantic_analysis,
        "run_semantic_analysis",
        forbidden_execution,
    )

    outcome = analyze_semantics(
        _request(
            _settings(tmp_path),
            repo_root=tmp_path,
            progress_sink=mutate_at_accounting,
        )
    )

    assert outcome == SemanticApplicationFailure(
        stage="currentness",
        message="repository source changed before current analysis execution",
    )
    assert provider_calls == 0
    assert "packet_accounting" in [event.phase for event in events]


def test_partial_publication_context_remains_typed_and_ordered(
    tmp_path: Path,
) -> None:
    _write_all_skipped_repo(tmp_path)
    packets = tmp_path / "artifacts/packets.jsonl"
    packet_report = tmp_path / "artifacts/packet-report.json"
    results = tmp_path / "artifacts/analysis.jsonl"
    report = tmp_path / "artifacts/analysis-report.json"
    results.mkdir(parents=True)

    outcome = analyze_semantics(
        _request(
            _settings(tmp_path),
            repo_root=tmp_path,
            packets_output_path=packets,
            packet_report_output_path=packet_report,
            result_output_path=results,
            report_output_path=report,
        )
    )

    assert isinstance(outcome, SemanticApplicationFailure)
    assert outcome.stage == "publication"
    assert outcome.failed_path == results
    assert outcome.published_paths == (packets, packet_report)
    assert packets.is_file()
    assert packet_report.is_file()
    assert results.is_dir()
    assert not report.exists()
    assert tuple(results.parent.glob(".*.tmp")) == ()


def test_semantic_application_executes_without_provider_imports(
    tmp_path: Path,
) -> None:
    _write_all_skipped_repo(tmp_path)
    snippet = (
        "import sys\n"
        "from pathlib import Path\n"
        "from backstitch.profiles import configured_profile\n"
        "from backstitch.semantic_analysis import "
        "resolve_semantic_settings, resolve_verification_settings\n"
        "from backstitch.semantic_application import "
        "SemanticApplicationRequest, SemanticApplicationResult, analyze_semantics\n"
        "from backstitch.semantic_policy import materialize_semantic_policy\n"
        "from backstitch.settings import resolve_config\n"
        f"root = Path({str(tmp_path)!r})\n"
        "settings = resolve_config(root, use_repo_config=False, "
        "environment={}, invocation_command='analyze')\n"
        "resolved = resolve_semantic_settings(settings.analyze)\n"
        "outcome = analyze_semantics(SemanticApplicationRequest("
        "settings=settings, profile=configured_profile(settings), repo_root=root, "
        "semantic_settings=resolved, policy=materialize_semantic_policy("
        "settings.diagnostics, settings.policy_rule_origins, settings.config_layers), "
        "adapter_factory=None, verification_settings=resolve_verification_settings("
        "settings.verify, resolved), evaluation_settings=None, "
        "verification_adapter_factory=None))\n"
        "assert isinstance(outcome, SemanticApplicationResult)\n"
        "assert 'llm' not in sys.modules\n"
        "assert 'backstitch.analysis_llm' not in sys.modules\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", snippet],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
