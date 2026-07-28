"""Shared helpers for the [SC-10] acceptance probe suite.

Probes are black-box: subprocess invocations asserting exit-code classes,
structured JSON fields, and no tracebacks. The single permitted fake is the
model boundary (probes 8-9), per [SC-10].
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, cast

import pytest

from backstitch.artifact_contracts import ValidatedSemanticPacket
from backstitch.semantic_analysis import (
    ResolvedSemanticSettings,
    SemanticAnalysisRequest,
    SemanticAnalysisRun,
    run_semantic_analysis,
)
from backstitch.semantic_cache import (
    ProviderAdapter,
    ProviderCallResult,
    SemanticProvenance,
)
from backstitch.semantic_identity import ProviderIdentity, RequestIdentity
from backstitch.semantic_packets import canonical_json_bytes, semantic_packet_hash
from backstitch.semantic_policy import materialize_semantic_policy
from backstitch.semantic_reports import PacketReport, validate_packet_report
from backstitch.settings import resolve_config

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, "-m", "backstitch", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    assert "Traceback" not in result.stderr, result.stderr
    return result


def check_json(
    repo: Path, *extra: str, expect_exit: int | None = None
) -> dict[str, Any]:
    result = run_cli(
        "check",
        "--repo-root",
        str(repo),
        "--format",
        "json",
        *extra,
    )
    if expect_exit is not None:
        assert result.returncode == expect_exit, result.stderr
    return cast(dict[str, Any], json.loads(result.stdout))


@pytest.fixture
def mini_repo(tmp_path: Path) -> Path:
    """A minimal clean corpus the probes mutate per scenario."""

    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "docs/plans").mkdir(parents=True)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "docs/specs/01-p.md").write_text(
        "# P\n\n## One [PR-1]\n\n_Implementation mapping_:\n\n- `pkg/mod.py`\n",
        encoding="utf-8",
    )
    (tmp_path / "pkg/mod.py").write_text(
        '"""Spec: docs/specs/01-p.md [PR-1]"""\n', encoding="utf-8"
    )
    return tmp_path


ROOTS = ("--spec-root", "docs/specs", "--plan-root", "docs/plans", "--code-root", "pkg")


def semantic_packet(
    packet_id: str,
    *,
    implementation: str = "return 1",
    implementation_path: str | None = None,
) -> dict[str, Any]:
    spec_path, _, identity = packet_id.partition("#")
    implementation_path = implementation_path or f"pkg/{identity.lower()}.py"
    source = {
        "source_role": "implementation",
        "receipt_hash": hashlib.sha256(packet_id.encode()).hexdigest(),
        "relation_kinds": ["spec_mapping", "code_backlink"],
        "reciprocity_state": "complete",
    }
    state = {
        "obligation_state_version": 1,
        "obligation_id": packet_id,
        "kind": "section",
        "obligation_rung": "active",
        "intent_state": "identified",
        "alignment_state": "complete",
        "disposition": "evaluate",
        "gate_state": "executable",
        "required_roles": ["implementation"],
        "declared_sources": [source],
    }
    row: dict[str, Any] = {
        "schema_version": 3,
        "packet_id": packet_id,
        "packet_hash": "",
        "kind": "section",
        "obligation_id": packet_id,
        "source_snapshot": {
            "snapshot_hash": "1" * 64,
            "obligation_state_hash": hashlib.sha256(
                canonical_json_bytes(state)
            ).hexdigest(),
            "derivation_config_hash": "3" * 64,
        },
        "readiness": {
            "intent_state": "identified",
            "alignment_state": "complete",
            "disposition": "evaluate",
            "obligation_rung": "active",
            "gate_state": "executable",
            "required_roles": ["implementation"],
        },
        "requirement": {
            "role": "requirement",
            "path": spec_path,
            "identity": identity,
            "title": identity,
            "start_line": 5,
            "end_line": 5,
            "text": "The implementation must return one.",
        },
        "declared_evidence": [
            {
                "role": "implementation",
                "path": implementation_path,
                "symbol": "value",
                "start_line": 4,
                "end_line": 4,
                "snippet": implementation,
                "sources": [source],
            }
        ],
        "counterevidence": [],
        "trace_summary": {
            "declared_counts": [
                {
                    "source_role": "implementation",
                    "total": 1,
                    "complete": 1,
                    "one_sided": 0,
                },
                {
                    "source_role": "test",
                    "total": 0,
                    "complete": 0,
                    "one_sided": 0,
                },
                {
                    "source_role": "binding_test",
                    "total": 0,
                    "complete": 0,
                    "one_sided": 0,
                },
            ],
            "candidate_counts": [
                {
                    "candidate_kind": kind,
                    "declared": 0,
                    "partially_declared": 0,
                    "untraced": 0,
                    "conflicted": 0,
                }
                for kind in (
                    "implementation_definition",
                    "test_definition",
                    "static_reference",
                    "unresolved_reference",
                    "report_issue",
                )
            ],
            "relation_counts": [
                {
                    "relation_kind": kind,
                    "count": 1 if kind in {"spec_mapping", "code_backlink"} else 0,
                }
                for kind in (
                    "spec_mapping",
                    "code_backlink",
                    "invariant_declaration",
                    "invariant_bind",
                    "binding_test",
                    "static_import",
                    "static_call",
                    "static_reference",
                    "enclosing_definition",
                    "issue_target",
                )
            ],
        },
        "evidence_regions": [
            {
                "role": "requirement",
                "path": spec_path,
                "start_line": 5,
                "end_line": 5,
            },
            {
                "role": "implementation",
                "path": implementation_path,
                "start_line": 4,
                "end_line": 4,
            },
        ],
        "issues": [],
        "packet_warnings": [],
    }
    row["packet_hash"] = semantic_packet_hash(row)
    return row


def semantic_packet_report(
    rendered: bytes,
    packets: tuple[ValidatedSemanticPacket, ...],
) -> PacketReport:
    rows = tuple(packet.to_dict() for packet in packets)
    snapshot_hashes = {row["source_snapshot"]["snapshot_hash"] for row in rows}
    if len(snapshot_hashes) != 1:
        raise ValueError("acceptance packets must share one source snapshot")
    snapshot_hash = next(iter(snapshot_hashes))
    audit = [
        {
            "obligation_id": row["obligation_id"],
            "kind": row["kind"],
            "path": row["requirement"]["path"],
            "start_line": row["requirement"]["start_line"],
            "intent_state": "identified",
            "alignment_state": "complete",
            "disposition": "evaluate",
            "obligation_rung": "active",
            "gate_state": "executable",
            "skip": None,
        }
        for row in rows
    ]
    audit.sort(
        key=lambda item: (item["path"], item["start_line"], item["obligation_id"])
    )
    value: dict[str, Any] = {
        "schema_version": 2,
        "artifact": "backstitch-packet-report",
        "packet_schema_version": 3,
        "scope": "source_snapshot",
        "source_snapshot": {
            "snapshot_hash": snapshot_hash,
            "file_count": 3,
            "byte_count": 120,
            "unreadable_count": 0,
        },
        "derivation_contract": {
            "obligation_algorithm_version": 1,
            "discovery_algorithm_version": 1,
            "packet_contract_version": 3,
            "normalization_version": 1,
            "semantic_config_sha256": "5" * 64,
        },
        "packet_jsonl_sha256": hashlib.sha256(rendered).hexdigest(),
        "packet_count": len(rows),
        "packet_bytes": len(rendered),
        "selection_status": "selected",
        "readiness_counts": {
            "total": len(rows),
            "active": len(rows),
            "out_of_scope": 0,
            "selected": len(rows),
            "skipped": 0,
            "alignment_debt": 0,
            "blocked": 0,
        },
        "alignment_audit": audit,
        "deterministic_issues": [],
        "packets": [
            {"packet_id": row["packet_id"], "packet_hash": row["packet_hash"]}
            for row in rows
        ],
        "packet_report_content_sha256": "",
        "tool_version": "test",
        "created_at": "2026-07-16T12:00:00Z",
    }
    projection = {
        key: value[key]
        for key in (
            "schema_version",
            "artifact",
            "packet_schema_version",
            "scope",
            "source_snapshot",
            "derivation_contract",
            "packet_jsonl_sha256",
            "packet_count",
            "packet_bytes",
            "selection_status",
            "readiness_counts",
            "alignment_audit",
            "deterministic_issues",
            "packets",
        )
    }
    value["packet_report_content_sha256"] = hashlib.sha256(
        canonical_json_bytes(projection)
    ).hexdigest()
    return validate_packet_report(value, packet_jsonl=rendered, packets=packets)


class SemanticAnalysisHarness(Protocol):
    def __call__(
        self,
        *,
        packets: list[dict[str, Any]],
        adapter: Callable[[str], str],
        concurrency: int = 1,
        name: str = "analysis",
    ) -> tuple[SemanticAnalysisRun, SemanticAnalysisRequest]: ...


@pytest.fixture
def semantic_analysis_harness(tmp_path: Path) -> SemanticAnalysisHarness:
    """Run the production semantic gate with only its model boundary controlled."""

    provider = ProviderIdentity(
        backend_id="llm",
        plugin_id="openai",
        model_id="acceptance-controlled-model",
        model_revision="2026-07-14",
        adapter_id="backstitch.llm",
        adapter_version=1,
        llm_distribution_version="0.31.1",
        plugin_distribution_name="llm-openai",
        plugin_distribution_version="1.2.3",
    )
    request_identity = RequestIdentity("require", 0.0, 42, 512)
    provenance = SemanticProvenance(
        adapter_id="backstitch.llm",
        adapter_version=1,
        plugin_version="1.2.3",
        model_class="tests.acceptance.ControlledModel",
        provider_model_id=provider.model_id,
        provider_model_revision=provider.model_revision,
        response_id="acceptance-response",
        input_tokens=10,
        output_tokens=5,
    )

    def run(
        *,
        packets: list[dict[str, Any]],
        adapter: Callable[[str], str],
        concurrency: int = 1,
        name: str = "analysis",
    ) -> tuple[SemanticAnalysisRun, SemanticAnalysisRequest]:
        ordered_packets = sorted(
            packets,
            key=lambda packet: (
                packet["requirement"]["path"],
                packet["requirement"]["start_line"],
                packet["obligation_id"],
            ),
        )
        validated = tuple(
            ValidatedSemanticPacket.from_row(packet, cache_eligible=True)
            for packet in ordered_packets
        )
        packet_jsonl = b"".join(
            canonical_json_bytes(packet) + b"\n" for packet in ordered_packets
        )
        packet_report = semantic_packet_report(packet_jsonl, validated)
        settings = ResolvedSemanticSettings(
            provider_identity=provider,
            request_identity=request_identity,
            concurrency=concurrency,
            cache_path=tmp_path / f"{name}-cache",
            cache_mode="off",
            search_epoch="1",
            require_complete=True,
            required_kinds=("section",),
            minimum_packets=len(packets),
            maximum_packets=max(1, len(packets)),
            maximum_prompt_bytes=1_000_000,
            finding_handling="report",
            maximum_provider_calls=len(packets),
            lock_wait_timeout_seconds=1,
            maximum_runtime_seconds=60,
            maximum_estimated_cost_microusd=0,
            input_cost_microusd_per_million_tokens=0,
            output_cost_microusd_per_million_tokens=0,
            input_token_overhead=256,
            cost_rate_source="",
            dispositions=(),
        )
        loaded = resolve_config(
            tmp_path,
            use_repo_config=False,
            environment={},
        )
        policy = materialize_semantic_policy(
            loaded.diagnostics,
            loaded.policy_rule_origins,
            loaded.config_layers,
        )

        def factory() -> ProviderAdapter:
            def call(prompt: str) -> ProviderCallResult:
                return ProviderCallResult(adapter(prompt), provenance)

            return call

        request = SemanticAnalysisRequest(
            packets=validated,
            packet_jsonl_sha256=hashlib.sha256(packet_jsonl).hexdigest(),
            packet_report=packet_report,
            settings=settings,
            policy=policy,
            adapter_factory=factory,
            result_path=tmp_path / f"{name}.jsonl",
            report_path=tmp_path / f"{name}-report.json",
        )
        return run_semantic_analysis(request), request

    return run
