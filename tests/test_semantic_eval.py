"""Schema-3 semantic qualification through the production analyzer/verifier paths.

Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-10.1]
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from backstitch.semantic_analysis import (
    ResolvedSemanticSettings,
    ResolvedVerificationSettings,
)
from backstitch.semantic_cache import (
    ProviderAdapter,
    ProviderCallResult,
    SemanticProvenance,
)
from backstitch.semantic_eval import (
    _MEASURED_SHORT_CODES,
    SemanticEvalError,
    SemanticEvalRequest,
    run_semantic_eval,
)
from backstitch.semantic_eval_reports import (
    load_semantic_eval_corpus,
    load_semantic_eval_report,
)
from backstitch.semantic_identity import (
    ProviderIdentity,
    RequestIdentity,
    build_composition_identity,
)
from backstitch.semantic_packets import canonical_json_bytes
from backstitch.settings import VerifyEvalSettings

CORPUS = Path(__file__).parent / "semantic_eval/v3/manifest.json"
CORPUS_SHA256 = (
    "sha256:b5cbed195b945b5f3951faca69c2e9ee2c75cc66b563dd57ea206bc73d0f6027"
)
PROVIDER = ProviderIdentity(
    backend_id="test",
    plugin_id="controlled",
    model_id="semantic-eval-model",
    model_revision="2026-07-16",
    adapter_id="tests.semantic-eval",
    adapter_version=1,
    llm_distribution_version="test-llm-1",
    plugin_distribution_name="controlled-provider",
    plugin_distribution_version="1",
)
REQUEST = RequestIdentity("require", 0.0, 42, 512)
PROVENANCE = SemanticProvenance(
    adapter_id=PROVIDER.adapter_id,
    adapter_version=PROVIDER.adapter_version,
    plugin_version=PROVIDER.plugin_distribution_version,
    model_class="tests.ControlledSemanticEvalModel",
    provider_model_id=PROVIDER.model_id,
    provider_model_revision=PROVIDER.model_revision,
    response_id="controlled-response",
    input_tokens=100,
    output_tokens=20,
)


def test_measured_qualification_remains_explicitly_bsa001_through_bsa005() -> None:
    assert _MEASURED_SHORT_CODES == (
        "BSA001",
        "BSA002",
        "BSA003",
        "BSA004",
        "BSA005",
    )


class ControlledAnalyzer:
    def __init__(self, *, always_ok: bool = False) -> None:
        self.always_ok = always_ok
        self.factory_calls = 0
        self.provider_calls = 0
        self.prompts: list[str] = []

    def factory(self) -> ProviderAdapter:
        self.factory_calls += 1

        def adapter(prompt: str) -> ProviderCallResult:
            self.provider_calls += 1
            self.prompts.append(prompt)
            packet = json.loads(prompt.rsplit("\n\n", 1)[1])
            mutation = not self.always_ok and "return 2" in prompt
            evidence = (
                [
                    {
                        "role": "requirement",
                        "path": "docs/specs/01-feature.md",
                        "start_line": 3,
                        "end_line": 9,
                    },
                    {
                        "role": "implementation",
                        "path": "src/feature.py",
                        "start_line": 1,
                        "end_line": 3,
                    },
                ]
                if mutation
                else []
            )
            response = {
                "packet_id": packet["packet_id"],
                "classification": "confirmed_mismatch" if mutation else "ok",
                "confidence": 1.0,
                "rationale": "controlled production-path evaluation",
                "summary": "return contract differs" if mutation else "matches",
                "evidence": evidence,
            }
            return ProviderCallResult(json.dumps(response), PROVENANCE)

        return adapter


class ControlledVerifier:
    def __init__(self) -> None:
        self.factory_calls = 0
        self.provider_calls = 0
        self.prompts: list[str] = []

    def factory(self) -> ProviderAdapter:
        self.factory_calls += 1

        def adapter(prompt: str) -> ProviderCallResult:
            self.provider_calls += 1
            self.prompts.append(prompt)
            request = json.loads(prompt.rsplit("\n\n", 1)[1])
            claim = request["claim"]
            response = {
                "packet_id": claim["packet_id"],
                "claim_hash": __import__("hashlib")
                .sha256(canonical_json_bytes(claim))
                .hexdigest(),
                "verdict": "support",
                "support_score": 1.0,
                "summary": "claim survived controlled falsification",
                "evidence": [
                    {
                        key: item[key]
                        for key in ("role", "path", "start_line", "end_line")
                    }
                    for item in claim["evidence"]
                ],
            }
            return ProviderCallResult(json.dumps(response), PROVENANCE)

        return adapter


def _resolved(
    tmp_path: Path,
) -> tuple[ResolvedSemanticSettings, ResolvedVerificationSettings]:
    composition = build_composition_identity(
        PROVIDER,
        REQUEST,
        analysis_search_epoch="analysis-base",
        verify_provider=PROVIDER,
        verify_request=REQUEST,
        verify_search_epochs=("verify-base",),
        required_verdicts=1,
        minimum_support_score=0.9,
        indeterminate="report",
    )
    analyze = ResolvedSemanticSettings(
        provider_identity=PROVIDER,
        request_identity=REQUEST,
        concurrency=1,
        cache_path=tmp_path / "ordinary-analyze-cache",
        cache_mode="off",
        search_epoch="analysis-base",
        require_complete=True,
        required_kinds=("section", "invariant"),
        minimum_packets=0,
        maximum_packets=100,
        maximum_prompt_bytes=10_000_000,
        finding_handling="allow",
        maximum_provider_calls=100,
        lock_wait_timeout_seconds=5,
        maximum_runtime_seconds=300,
        maximum_estimated_cost_microusd=1_000_000_000,
        input_cost_microusd_per_million_tokens=1,
        output_cost_microusd_per_million_tokens=1,
        input_token_overhead=256,
        cost_rate_source="controlled test rates",
        dispositions=(),
    )
    verify = ResolvedVerificationSettings(
        provider_identity=PROVIDER,
        request_identity=REQUEST,
        composition_identity=composition,
        concurrency=1,
        cache_path=tmp_path / "ordinary-verify-cache",
        cache_mode="off",
        search_epochs=("verify-base",),
        required_verdicts=1,
        minimum_support_score=0.9,
        indeterminate="report",
        maximum_provider_calls=100,
        maximum_prompt_bytes=10_000_000,
        lock_wait_timeout_seconds=5,
        maximum_runtime_seconds=300,
        maximum_estimated_cost_microusd=1_000_000_000,
        input_cost_microusd_per_million_tokens=1,
        output_cost_microusd_per_million_tokens=1,
        input_token_overhead=256,
        cost_rate_source="controlled test rates",
    )
    return analyze, verify


def _eval_settings(**changes: Any) -> VerifyEvalSettings:
    values: dict[str, Any] = {
        "mode": "report",
        "qualification_corpus": "",
        "qualification_corpus_sha256": "",
        "qualification_report": "",
        "qualification_report_sha256": "",
        "trials": 2,
        "interval_method": "wilson",
        "confidence_level": 0.95,
        "minimum_positive_units": 1,
        "minimum_negative_units": 1,
        "minimum_evidence_sufficiency_rate": 0.0,
        "minimum_conditional_precision": 0.0,
        "minimum_conditional_recall": 0.0,
        "minimum_end_to_end_recall": 0.0,
        "minimum_recall_lower_bound": 0.0,
        "maximum_false_positive_rate": 1.0,
        "maximum_false_positive_upper_bound": 1.0,
        "maximum_indeterminate_rate": 1.0,
        "maximum_uncached_flip_rate": 1.0,
        "require_all_critical": False,
    }
    values.update(changes)
    return VerifyEvalSettings(**values)


def _request(
    tmp_path: Path,
    analyzer: ControlledAnalyzer,
    verifier: ControlledVerifier,
    *,
    eval_settings: VerifyEvalSettings | None = None,
    output: Path | None = None,
) -> SemanticEvalRequest:
    analyze, verify = _resolved(tmp_path)
    return SemanticEvalRequest(
        manifest_path=CORPUS,
        output_path=output or tmp_path / "report.json",
        settings=analyze,
        verification_settings=verify,
        eval_settings=eval_settings or _eval_settings(),
        adapter_factory=analyzer.factory,
        verification_adapter_factory=verifier.factory,
    )


def test_schema3_runner_uses_cold_primary_and_zero_call_replay(
    tmp_path: Path,
) -> None:
    analyzer = ControlledAnalyzer()
    verifier = ControlledVerifier()
    request = _request(tmp_path, analyzer, verifier)

    run = run_semantic_eval(request)

    assert run.exit_code == 0
    assert analyzer.factory_calls == 1
    assert analyzer.provider_calls == 4
    assert verifier.factory_calls == 1
    assert verifier.provider_calls == 2
    assert request.output_path.read_bytes() == run.report_json
    assert len(run.report["analysis_attempts"]) == 4
    assert len(run.report["events"]) == 2
    assert run.report["operational"] == {
        "cache_hits": 6,
        "cache_misses": 6,
        "provider_calls": 6,
        "analyzer_primary_cache_hits": 0,
        "analyzer_primary_cache_misses": 4,
        "analyzer_primary_provider_calls": 4,
        "analyzer_replay_cache_hits": 4,
        "analyzer_replay_cache_misses": 0,
        "analyzer_replay_provider_calls": 0,
        "verifier_primary_cache_hits": 0,
        "verifier_primary_cache_misses": 2,
        "verifier_primary_provider_calls": 2,
        "verifier_replay_cache_hits": 2,
        "verifier_replay_cache_misses": 0,
        "verifier_replay_provider_calls": 0,
        "analysis_cost": run.report["operational"]["analysis_cost"],
        "verify_cost": run.report["operational"]["verify_cost"],
        "total_estimated_cost_microusd": run.report["operational"][
            "total_estimated_cost_microusd"
        ],
    }
    metrics = run.report["metrics"]
    assert metrics["evidence_sufficiency_rate"] == 1.0
    assert metrics["conditional_precision"] == 1.0
    assert metrics["conditional_recall"] == 1.0
    assert metrics["end_to_end_recall"] == 1.0
    assert metrics["false_positive_rate"] == 0.0
    assert metrics["indeterminate_rate"] == 0.0
    assert metrics["uncached_flip_rate"] == 0.0
    assert run.report["qualification"]["passed"] is True
    assert all("gold_evidence" not in prompt for prompt in analyzer.prompts)
    assert all("expected_findings" not in prompt for prompt in analyzer.prompts)
    corpus = load_semantic_eval_corpus(CORPUS, mode="report")
    loaded = load_semantic_eval_report(request.output_path, corpus=corpus)
    assert loaded.to_json_bytes() == run.report_json


def test_report_mode_publishes_completed_failed_measurement(
    tmp_path: Path,
) -> None:
    analyzer = ControlledAnalyzer(always_ok=True)
    verifier = ControlledVerifier()

    run = run_semantic_eval(
        _request(
            tmp_path,
            analyzer,
            verifier,
            eval_settings=_eval_settings(minimum_end_to_end_recall=1.0),
        )
    )

    assert run.exit_code == 0
    assert run.report["qualification"]["passed"] is False
    assert "minimum_end_to_end_recall" in run.report["qualification"]["failure_reasons"]
    assert verifier.factory_calls == 0
    assert verifier.provider_calls == 0
    assert (tmp_path / "report.json").exists()


def test_corpus_hash_mismatch_precedes_adapter_construction(tmp_path: Path) -> None:
    analyzer = ControlledAnalyzer()
    verifier = ControlledVerifier()

    with pytest.raises(SemanticEvalError, match="corpus digest"):
        run_semantic_eval(
            _request(
                tmp_path,
                analyzer,
                verifier,
                eval_settings=_eval_settings(
                    qualification_corpus_sha256=f"sha256:{'0' * 64}"
                ),
            )
        )

    assert analyzer.factory_calls == 0
    assert verifier.factory_calls == 0
    assert not (tmp_path / "report.json").exists()


def test_output_cannot_overlap_corpus_input(tmp_path: Path) -> None:
    analyzer = ControlledAnalyzer()
    verifier = ControlledVerifier()

    with pytest.raises(SemanticEvalError, match="overlaps a corpus input"):
        run_semantic_eval(_request(tmp_path, analyzer, verifier, output=CORPUS))

    assert analyzer.factory_calls == 0
    assert verifier.factory_calls == 0


def test_output_cannot_overlap_configured_qualification_report(
    tmp_path: Path,
) -> None:
    analyzer = ControlledAnalyzer()
    verifier = ControlledVerifier()
    output = tmp_path / "candidate-report.json"

    with pytest.raises(
        SemanticEvalError, match="overlaps configured qualification report"
    ):
        run_semantic_eval(
            _request(
                tmp_path,
                analyzer,
                verifier,
                output=output,
                eval_settings=_eval_settings(
                    qualification_report=str(output),
                    qualification_report_sha256=f"sha256:{'a' * 64}",
                ),
            )
        )

    assert analyzer.factory_calls == 0
    assert verifier.factory_calls == 0
    assert not output.exists()


@pytest.mark.parametrize(
    "qualification_report",
    [
        CORPUS,
        CORPUS.parent / "trees/return-contract-clean.json",
        CORPUS.parent / "fixtures/return-contract/clean/src/feature.py",
    ],
)
def test_configured_qualification_report_cannot_overlap_corpus_inputs(
    tmp_path: Path,
    qualification_report: Path,
) -> None:
    analyzer = ControlledAnalyzer()
    verifier = ControlledVerifier()

    with pytest.raises(
        SemanticEvalError,
        match="configured qualification report overlaps a corpus input",
    ):
        run_semantic_eval(
            _request(
                tmp_path,
                analyzer,
                verifier,
                eval_settings=_eval_settings(
                    qualification_report=str(qualification_report),
                    qualification_report_sha256=f"sha256:{'a' * 64}",
                ),
            )
        )

    assert analyzer.factory_calls == 0
    assert verifier.factory_calls == 0
    assert not (tmp_path / "report.json").exists()


def test_trials_change_effective_keys_without_changing_composition(
    tmp_path: Path,
) -> None:
    analyzer = ControlledAnalyzer()
    verifier = ControlledVerifier()
    run = run_semantic_eval(_request(tmp_path, analyzer, verifier))

    attempts = run.report["analysis_attempts"]
    assert len({item["effective_search_epoch"] for item in attempts}) == 2
    assert len({item["analysis_key"] for item in attempts}) == 4
    assert {item["base_search_epoch"] for item in attempts} == {"analysis-base"}
    assert (
        run.report["identity"]["analysis_composition"]["base_search_epoch"]
        == "analysis-base"
    )
    assert (
        len(
            {
                result["effective_search_epoch"]
                for event in run.report["events"]
                for result in event["primary_results"]
            }
        )
        == 2
    )


def test_analyzer_lane_budget_is_global_across_trials(tmp_path: Path) -> None:
    analyzer = ControlledAnalyzer()
    verifier = ControlledVerifier()
    request = _request(tmp_path, analyzer, verifier)
    request = replace(
        request,
        settings=replace(request.settings, maximum_provider_calls=3),
    )

    with pytest.raises(SemanticEvalError, match="budget_exceeded"):
        run_semantic_eval(request)

    assert analyzer.provider_calls == 3
    assert verifier.provider_calls == 0
    assert not request.output_path.exists()


def test_cli_eval_rejects_disabled_verification_without_publication(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from backstitch.cli import main

    output = tmp_path / "report.json"
    exit_code = main(
        [
            "eval",
            "--corpus",
            str(CORPUS),
            "--output",
            str(output),
            "--no-config",
        ]
    )

    assert exit_code == 2
    assert "verify.enabled = true" in capsys.readouterr().err
    assert not output.exists()


def test_cli_eval_rejects_input_output_alias_before_configuration(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from backstitch.cli import main

    exit_code = main(
        [
            "eval",
            "--corpus",
            str(CORPUS),
            "--output",
            str(CORPUS),
            "--no-config",
        ]
    )

    assert exit_code == 2
    assert "must be distinct" in capsys.readouterr().err


def test_cli_eval_rejects_configured_report_alias_before_adapter_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import backstitch.analysis_llm as analysis_llm
    from backstitch.cli import main

    monkeypatch.delenv("LLM_MODEL", raising=False)
    output = tmp_path / "qualification-report.json"
    trusted_config = Path(__file__).parents[1] / "pyproject.toml"
    config = tmp_path / "eval.toml"
    config.write_text(
        f'extend = "{trusted_config.as_posix()}"\n\n'
        "[verify.eval]\n"
        f'qualification_report = "{output.as_posix()}"\n'
        f'qualification_report_sha256 = "sha256:{"a" * 64}"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        analysis_llm,
        "default_provider_adapter",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("aliased eval output constructed an adapter")
        ),
    )

    exit_code = main(
        [
            "eval",
            "--corpus",
            str(CORPUS),
            "--output",
            str(output),
            "--config",
            str(config),
            "--option",
            "verify.enabled",
            "true",
        ]
    )

    assert exit_code == 2
    assert "qualification_report" in capsys.readouterr().err
    assert not output.exists()


def test_cli_eval_rejects_configured_report_overlapping_selected_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import backstitch.analysis_llm as analysis_llm
    from backstitch.cli import main

    monkeypatch.delenv("LLM_MODEL", raising=False)
    output = tmp_path / "candidate-report.json"
    trusted_config = Path(__file__).parents[1] / "pyproject.toml"
    config = tmp_path / "eval.toml"
    config.write_text(
        f'extend = "{trusted_config.as_posix()}"\n\n'
        "[verify.eval]\n"
        f'qualification_report = "{config.as_posix()}"\n'
        f'qualification_report_sha256 = "sha256:{"a" * 64}"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        analysis_llm,
        "default_provider_adapter",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("config-aliasing report constructed an adapter")
        ),
    )

    exit_code = main(
        [
            "eval",
            "--corpus",
            str(CORPUS),
            "--output",
            str(output),
            "--config",
            str(config),
            "--option",
            "verify.enabled",
            "true",
        ]
    )

    assert exit_code == 2
    assert "selected configuration" in capsys.readouterr().err
    assert not output.exists()
