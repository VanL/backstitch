"""Provider-free source observations for semantic qualification.

The ordinary snapshot, obligation, discovery, and packet pipeline derives
these facts. Qualification reports cannot supply the facts used to grade
themselves.

Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-10.1]
Spec: docs/specs/06-semantic-gates.md [SEM-8]
"""

from __future__ import annotations

import hashlib
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from backstitch import analysis_packets
from backstitch.artifact_contracts import ValidatedSemanticPacket, load_packets_bytes
from backstitch.canonical import canonical_json_bytes
from backstitch.config import ProfileConfig
from backstitch.obligation_runtime import ObligationRuntime, build_obligation_runtime
from backstitch.semantic_eval_reports import (
    SemanticEvalContractError,
    SemanticEvalCorpus,
    SemanticEvalObservedFacts,
    SemanticEvalObservedVariantFacts,
)
from backstitch.semantic_reports import (
    PacketReportError,
    build_source_packet_report,
)
from backstitch.settings import BackstitchSettings, ObligationSettings


class SemanticEvalError(ValueError):
    """Evaluation setup or production execution failed and maps to exit 2."""


@dataclass(frozen=True, slots=True)
class SemanticEvalVariantObservation:
    case_id: str
    variant_id: str
    critical: bool
    packet_rows: tuple[dict[str, Any], ...]
    evidence_eligible: bool
    deterministic_problem: str | None

    @property
    def packet_by_id(self) -> dict[str, dict[str, Any]]:
        return {cast(str, row["packet_id"]): row for row in self.packet_rows}


@dataclass(frozen=True, slots=True)
class SemanticEvalVariantBuild:
    observation: SemanticEvalVariantObservation
    packets: tuple[ValidatedSemanticPacket, ...]
    packet_jsonl: bytes
    runtime: ObligationRuntime


def semantic_eval_case_rows(
    corpus: SemanticEvalCorpus,
) -> dict[str, dict[str, Any]]:
    return {
        cast(str, case["case_id"]): case
        for case in cast(list[dict[str, Any]], corpus.to_dict()["cases"])
    }


def _profile(case_id: str, value: Mapping[str, Any]) -> ProfileConfig:
    return ProfileConfig(
        name=f"semantic-eval:{case_id}",
        spec_roots=tuple(cast(list[str], value["spec_roots"])),
        plan_roots=tuple(cast(list[str], value["plan_roots"])),
        code_roots=tuple(cast(list[str], value["code_roots"])),
        test_roots=tuple(cast(list[str], value["test_roots"])),
        planned_spec_globs=tuple(cast(list[str], value["planned_spec_globs"])),
        exploratory_spec_globs=tuple(cast(list[str], value["exploratory_spec_globs"])),
        meta_spec_globs=tuple(cast(list[str], value["meta_spec_globs"])),
    )


def _deterministic_settings(value: Mapping[str, Any]) -> BackstitchSettings:
    obligation_values = dict(cast(Mapping[str, Any], value["obligations"]))
    obligation_values["section_required_roles"] = tuple(
        cast(list[str], obligation_values["section_required_roles"])
    )
    obligations = ObligationSettings(**obligation_values)
    return BackstitchSettings(
        exclude=tuple(cast(list[str], value["exclude_globs"])),
        obligations=obligations,
    )


def _receipt_hash(receipt: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(dict(receipt))).hexdigest()


def _obligation_projection(runtime: ObligationRuntime) -> list[dict[str, Any]]:
    return [
        {
            "obligation_id": item.obligation_id,
            "packet_id": item.obligation_id,
            "intent_state": item.intent_state,
            "alignment_state": item.alignment_state,
            "disposition": item.disposition,
            "obligation_rung": item.obligation_rung,
            "gate_state": item.gate_state,
        }
        for item in runtime.inventory.obligations
    ]


def _evidence_projection(runtime: ObligationRuntime) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for obligation in runtime.inventory.obligations:
        for item in runtime.evidence_summary(obligation):
            receipt = cast(dict[str, Any], item["receipt"])
            rows.append(
                {
                    "obligation_id": obligation.obligation_id,
                    "source_role": item["role"],
                    "path": item["path"],
                    "structural_locator": receipt["structural_locator"],
                    "start_line": item["start_line"],
                    "end_line": item["end_line"],
                    "receipt_hash": _receipt_hash(receipt),
                    "reciprocity_state": item["reciprocity_state"],
                }
            )
    rows.sort(key=lambda item: canonical_json_bytes(item))
    return rows


def _candidate_projection(runtime: ObligationRuntime) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for obligation in runtime.inventory.obligations:
        for item in runtime.discover_candidates(obligation):
            rows.append(
                {
                    "obligation_id": obligation.obligation_id,
                    "candidate_id": item.candidate_id,
                    "candidate_kind": item.candidate_kind,
                    "path": item.path,
                    "structural_locator": item.structural_locator,
                    "start_line": item.start_line,
                    "end_line": item.end_line,
                    "receipt_hash": _receipt_hash(item.receipt.to_row()),
                    "trace_state": item.trace_state,
                }
            )
    rows.sort(key=lambda item: canonical_json_bytes(item))
    return rows


def _gold_projection(
    case: Mapping[str, Any], variant_id: str, field: str
) -> list[dict[str, Any]]:
    ignored = {"gold_id", "variant_id"}
    rows = [
        {key: item[key] for key in item if key not in ignored}
        for item in cast(list[dict[str, Any]], case[field])
        if item["variant_id"] == variant_id
    ]
    rows.sort(key=lambda item: canonical_json_bytes(item))
    return rows


def _packet_gold_matches(
    packets: tuple[dict[str, Any], ...],
    gold_evidence: list[dict[str, Any]],
    gold_candidates: list[dict[str, Any]],
) -> bool:
    declared = sorted(
        {
            cast(str, source["receipt_hash"])
            for packet in packets
            for region in cast(list[dict[str, Any]], packet["declared_evidence"])
            for source in cast(list[dict[str, Any]], region["sources"])
        }
    )
    candidates = sorted(
        {
            (
                cast(str, item["candidate_id"]),
                cast(str, item["receipt_hash"]),
            )
            for packet in packets
            for region in cast(list[dict[str, Any]], packet["counterevidence"])
            for item in cast(list[dict[str, Any]], region["candidates"])
        }
    )
    return declared == sorted(item["receipt_hash"] for item in gold_evidence) and (
        candidates
        == sorted(
            (item["candidate_id"], item["receipt_hash"])
            for item in gold_candidates
            if item["trace_state"] != "declared"
        )
    )


def derive_semantic_eval_variant(
    corpus: SemanticEvalCorpus,
    case: Mapping[str, Any],
    variant_id: str,
    destination: Path,
) -> SemanticEvalVariantBuild:
    """Derive one frozen variant through the production source pipeline."""

    case_id = cast(str, case["case_id"])
    fixture = corpus.fixture(case_id, variant_id)
    fixture.materialize(destination)
    deterministic = cast(Mapping[str, Any], case["deterministic_config"])
    runtime = build_obligation_runtime(
        destination,
        _profile(case_id, cast(Mapping[str, Any], deterministic["profile"])),
        _deterministic_settings(deterministic),
    )
    problem: str | None = None
    packet_rows: tuple[dict[str, Any], ...] = ()
    packet_jsonl = b""
    packets: tuple[ValidatedSemanticPacket, ...] = ()
    try:
        packet_plan = analysis_packets.plan_source_aligned_packets(runtime)
        packet_jsonl = packet_plan.packet_jsonl
        packets = load_packets_bytes(packet_jsonl, source=f"{case_id}/{variant_id}")
        build_source_packet_report(runtime, packet_plan=packet_plan)
        packet_rows = tuple(packet.to_dict() for packet in packets)
    except (
        PacketReportError,
        analysis_packets.SourceAlignedPacketError,
        ValueError,
    ) as exc:
        problem = str(exc)

    expected_obligations = _gold_projection(case, variant_id, "gold_obligations")
    expected_evidence = _gold_projection(case, variant_id, "gold_evidence")
    expected_candidates = _gold_projection(case, variant_id, "gold_candidates")
    actual_obligations = _obligation_projection(runtime)
    actual_evidence = _evidence_projection(runtime)
    actual_candidates = _candidate_projection(runtime)
    expected_packet_ids = [item["packet_id"] for item in expected_obligations]
    evidence_eligible = (
        problem is None
        and not runtime.pipeline.report.issues
        and actual_obligations == expected_obligations
        and actual_evidence == expected_evidence
        and actual_candidates == expected_candidates
        and [row["packet_id"] for row in packet_rows] == expected_packet_ids
        and _packet_gold_matches(packet_rows, expected_evidence, expected_candidates)
    )
    return SemanticEvalVariantBuild(
        observation=SemanticEvalVariantObservation(
            case_id=case_id,
            variant_id=variant_id,
            critical=cast(bool, case["critical"]),
            packet_rows=packet_rows,
            evidence_eligible=evidence_eligible,
            deterministic_problem=problem,
        ),
        packets=packets,
        packet_jsonl=packet_jsonl,
        runtime=runtime,
    )


def observed_semantic_eval_facts(
    builds: tuple[SemanticEvalVariantBuild, ...],
) -> SemanticEvalObservedFacts:
    """Project trusted facts from already-derived variants."""

    return SemanticEvalObservedFacts(
        variants=tuple(
            SemanticEvalObservedVariantFacts(
                case_id=build.observation.case_id,
                variant_id=build.observation.variant_id,
                obligations=tuple(_obligation_projection(build.runtime)),
                evidence=tuple(_evidence_projection(build.runtime)),
                candidates=tuple(_candidate_projection(build.runtime)),
                packets=build.observation.packet_rows,
                deterministic_issue_count=len(build.runtime.pipeline.report.issues),
                deterministic_problem=build.observation.deterministic_problem,
            )
            for build in builds
        )
    )


def derive_semantic_eval_observed_facts(
    corpus: SemanticEvalCorpus,
) -> SemanticEvalObservedFacts:
    """Run only the provider-free production source pipeline for a frozen corpus."""

    cases = semantic_eval_case_rows(corpus)
    builds: list[SemanticEvalVariantBuild] = []
    with tempfile.TemporaryDirectory(prefix="backstitch-semantic-observed-") as raw:
        root = Path(raw)
        for case_id, variant_id in corpus.variant_keys:
            try:
                builds.append(
                    derive_semantic_eval_variant(
                        corpus,
                        cases[case_id],
                        variant_id,
                        root / case_id / variant_id,
                    )
                )
            except (OSError, SemanticEvalContractError, ValueError) as exc:
                raise SemanticEvalError(
                    f"cannot derive semantic fixture {case_id}/{variant_id}: {exc}"
                ) from exc
    return observed_semantic_eval_facts(tuple(builds))
