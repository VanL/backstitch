"""Black-box packet creation through controlled semantic miss and replay."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

from backstitch.artifact_contracts import load_packets
from backstitch.semantic_analysis import (
    SemanticAnalysisRequest,
    resolve_semantic_settings,
    run_semantic_analysis,
)
from backstitch.semantic_cache import ProviderCallResult, SemanticProvenance
from backstitch.semantic_identity import ProviderIdentity, RequestIdentity
from backstitch.semantic_packets import canonical_json_bytes
from backstitch.semantic_policy import materialize_semantic_policy
from backstitch.semantic_reports import load_packet_report
from backstitch.settings import SemanticDisposition, resolve_config
from tests.acceptance.conftest import run_cli


def test_probe_suppression_semantic_miss_and_zero_call_replay(
    tmp_path: Path,
) -> None:
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "docs/specs/01-core.md").write_text(
        "_Implementation mapping_:\n"
        "\n"
        "- `pkg/ownerless.py`\n"
        "\n"
        "## Contract [SUPTEST-1]\n"
        "\n"
        '_Traceability: suppression-declaration [SUP-1] "The ownerless '
        'fixture is retained to exercise suppression governance."_\n'
        "\n"
        "_Implementation mapping_:\n"
        "\n"
        "- `pkg/core.py::run`\n",
        encoding="utf-8",
    )
    (tmp_path / "pkg/core.py").write_text(
        'def run() -> int:\n    """Spec: docs/specs/01-core.md [SUPTEST-1]"""\n'
        "    return 1\n",
        encoding="utf-8",
    )
    config_path = tmp_path / ".backstitch.toml"
    config_path.write_text(
        "[profile]\n"
        'spec_roots = ["docs/specs"]\n'
        "plan_roots = []\n"
        'code_roots = ["pkg"]\n'
        "test_roots = []\n\n"
        "[[lint.suppressions]]\n"
        'mechanism = "ignore"\n'
        'path = "docs/specs/01-core.md"\n'
        "sections = []\n"
        'codes = ["MAPPING_BLOCK_OWNERLESS"]\n'
        'declaration = "docs/specs/01-core.md#SUP-1"\n\n'
        "[[diagnostics.levels]]\n"
        'select = ["BSA006:human_verified"]\n'
        'level = "error"\n',
        encoding="utf-8",
    )
    packet_path = tmp_path / "packets.jsonl"
    packet_report_path = tmp_path / "packet-report.json"
    generated = run_cli(
        "packets",
        "--repo-root",
        str(tmp_path),
        "--config",
        str(config_path),
        "--kind",
        "all",
        "--output",
        str(packet_path),
        "--report",
        str(packet_report_path),
    )
    assert generated.returncode == 0, generated.stderr

    incomplete_report_path = tmp_path / "incomplete-packet-report.json"
    incomplete_report = json.loads(packet_report_path.read_bytes())
    incomplete_report["kind_counts"]["emitted"]["suppression"] = 0
    incomplete_report["packet_report_content_sha256"] = hashlib.sha256(
        canonical_json_bytes(
            {
                key: value
                for key, value in incomplete_report.items()
                if key
                not in {
                    "packet_report_content_sha256",
                    "tool_version",
                    "created_at",
                }
            }
        )
    ).hexdigest()
    incomplete_report_path.write_bytes(canonical_json_bytes(incomplete_report))
    invalid_output = tmp_path / "invalid-analysis.jsonl"
    invalid_report = tmp_path / "invalid-analysis-report.json"
    invalid = run_cli(
        "analyze",
        "--packets",
        str(packet_path),
        "--packet-report",
        str(incomplete_report_path),
        "--model",
        "acceptance-controlled-model",
        "--config",
        str(config_path),
        "--output",
        str(invalid_output),
        "--report",
        str(invalid_report),
    )
    assert invalid.returncode == 2
    assert "emitted kind counts" in invalid.stderr
    assert not invalid_output.exists()
    assert not invalid_report.exists()

    packets = load_packets(packet_path)
    packet_report = load_packet_report(packet_report_path)
    packet_bytes = packet_path.read_bytes()
    loaded = resolve_config(tmp_path, explicit=config_path)
    provider = ProviderIdentity(
        "controlled",
        "acceptance",
        "model",
        "revision",
        "backstitch.controlled",
        1,
        "test",
        "controlled-provider",
        "1",
    )
    settings = replace(
        resolve_semantic_settings(loaded.analyze),
        provider_identity=provider,
        request_identity=RequestIdentity("require", 0.0, 42, 512),
        cache_path=tmp_path / "cache",
        cache_mode="read-write",
        require_complete=True,
        required_kinds=("section", "suppression"),
        maximum_provider_calls=2,
    )
    policy = materialize_semantic_policy(
        loaded.diagnostics,
        loaded.policy_rule_origins,
        loaded.config_layers,
    )
    provenance = SemanticProvenance(
        adapter_id=provider.adapter_id,
        adapter_version=provider.adapter_version,
        plugin_version="1",
        model_class="tests.Controlled",
        provider_model_id=provider.model_id,
        provider_model_revision=provider.model_revision,
        response_id=None,
        input_tokens=1,
        output_tokens=1,
    )
    calls = 0

    def adapter(prompt: str) -> ProviderCallResult:
        nonlocal calls
        calls += 1
        projection = json.loads(prompt.rsplit("\n\n", 1)[1])
        suppression = projection["kind"] == "suppression"
        evidence = []
        if suppression:
            evidence = [
                {
                    key: projection["requirement"][key]
                    for key in ("role", "path", "start_line", "end_line")
                }
            ]
        response = {
            "packet_id": projection["packet_id"],
            "classification": "rationale_insufficient" if suppression else "ok",
            "confidence": 0.9,
            "rationale": "The rationale does not identify the concrete constraint.",
            "summary": "Reviewed the bounded packet.",
            "evidence": evidence,
        }
        return ProviderCallResult(json.dumps(response), provenance)

    request = SemanticAnalysisRequest(
        packets=packets,
        packet_jsonl_sha256=hashlib.sha256(packet_bytes).hexdigest(),
        packet_report=packet_report,
        settings=settings,
        policy=policy,
        adapter_factory=lambda: adapter,
        result_path=tmp_path / "analysis.jsonl",
        report_path=tmp_path / "analysis-report.json",
    )
    first = run_semantic_analysis(request)
    diagnostic = first.report["semantic_diagnostics"][0]
    disposition = SemanticDisposition(
        code=diagnostic["code"],
        packet_id=diagnostic["packet_id"],
        packet_hash=diagnostic["packet_hash"],
        finding_hash=diagnostic["finding_hash"],
        status="accepted",
        reason="The fixture suppression remains intentionally bounded.",
    )
    replay = run_semantic_analysis(
        replace(
            request,
            settings=replace(
                settings,
                cache_mode="require",
                concurrency=2,
                finding_handling="require_disposition",
                dispositions=(disposition,),
            ),
            adapter_factory=None,
            result_path=tmp_path / "replay-analysis.jsonl",
            report_path=tmp_path / "replay-analysis-report.json",
        )
    )

    assert calls == 2
    assert first.report["schema_version"] == 4
    assert first.report["kind_counts"]["provider_calls"] == {
        "section": 1,
        "invariant": 0,
        "suppression": 1,
    }
    assert first.report["semantic_diagnostics"][0]["short_code"] == "BSA006"
    assert first.exit_code == 0
    assert replay.exit_code == 1
    assert replay.report["semantic_diagnostics"][0]["verification_state"] == (
        "human_verified"
    )
    assert replay.report["semantic_diagnostics"][0]["severity"] == "error"
    assert replay.result_jsonl == first.result_jsonl
    assert replay.report["provider_calls"] == 0
    assert replay.report["kind_counts"]["cache_hits"] == {
        "section": 1,
        "invariant": 0,
        "suppression": 1,
    }
