"""Validation and aggregation of semantic analysis results.

Spec: docs/specs/02-backstitch-core.md [SC-6], [SC-7], [SC-13]
Spec: docs/specs/05-backstitch-invariants.md [INV-5]

Invalid analysis rows are analysis-summary errors, never repository trace
errors, and semantic findings never change deterministic issue severity.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from backstitch.grammar import is_valid_section_id

SECTION_CLASSIFICATIONS = (
    "ok",
    "confirmed_mismatch",
    "probable_mismatch",
    "missing_trace",
    "ambiguous",
)
INVARIANT_CLASSIFICATIONS = (
    "ok",
    "weak_binding",
    "confirmed_mismatch",
    "probable_mismatch",
    "ambiguous",
)
CLASSIFICATIONS = tuple(
    dict.fromkeys((*SECTION_CLASSIFICATIONS, *INVARIANT_CLASSIFICATIONS))
)
CLASSIFICATIONS_BY_KIND = {
    "section": SECTION_CLASSIFICATIONS,
    "invariant": INVARIANT_CLASSIFICATIONS,
}
_CONTENT_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    """One validated semantic finding for a packet."""

    packet_id: str
    kind: str
    content_hash: str | None
    classification: str
    confidence: float | None
    rationale: str
    evidence: tuple[tuple[str, int], ...]
    summary: str


@dataclass(frozen=True, slots=True)
class AnalysisLoad:
    """Validated results plus row-level input problems."""

    results: tuple[AnalysisResult, ...]
    errors: tuple[str, ...]


def validate_analysis_row(
    row: Any,
    known_packet_ids: set[str] | Mapping[str, str] | None,
    *,
    allowed_evidence: Mapping[str, tuple[tuple[int, int], ...]] | None = None,
) -> AnalysisResult | str:
    """Validate one untrusted model-output row ([SC-7]).

    ``allowed_evidence``, when provided, keeps evidence packet-local: the
    model may only cite paths that were in the packet it was shown, and
    only lines inside one of that path's ``(start, end)`` inclusive
    ranges. An empty range tuple means the path was named in the packet
    WITHOUT line-bounded content (linked tests): it cannot carry line
    evidence at all -- any cited line there is fabricated.
    """

    if not isinstance(row, dict):
        return "row is not a JSON object"
    packet_id = row.get("packet_id")
    if not isinstance(packet_id, str) or not packet_id.strip():
        return "missing or invalid `packet_id`"
    kind: str
    content_hash: str | None
    if "kind" not in row:
        if "content_hash" in row:
            return "legacy section result must omit `content_hash`"
        if packet_id.startswith("invariant::"):
            return "missing `kind` for invariant result identity"
        kind = "section"
        content_hash = None
    else:
        raw_kind = row.get("kind")
        if raw_kind not in CLASSIFICATIONS_BY_KIND:
            return "invalid `kind`; expected `section` or `invariant`"
        kind = raw_kind
        if kind == "section":
            if "content_hash" in row:
                return "section result must omit `content_hash`"
            if packet_id.startswith("invariant::"):
                return "section result cannot use an invariant packet identity"
            content_hash = None
        else:
            prefix = "invariant::"
            invariant_id = packet_id.removeprefix(prefix)
            if not packet_id.startswith(prefix) or not is_valid_section_id(
                invariant_id
            ):
                return "invariant result requires `invariant::<ID>` packet identity"
            raw_hash = row.get("content_hash")
            if not isinstance(raw_hash, str) or not _CONTENT_HASH_RE.fullmatch(
                raw_hash
            ):
                return (
                    "invalid `content_hash`; expected 64 lowercase hexadecimal"
                    " characters"
                )
            content_hash = raw_hash

    if known_packet_ids is not None:
        if packet_id not in known_packet_ids:
            return f"unknown packet ID `{packet_id}`"
        if isinstance(known_packet_ids, Mapping):
            expected_kind = known_packet_ids[packet_id]
            if kind != expected_kind:
                return (
                    f"result kind `{kind}` does not match packet kind `{expected_kind}`"
                )
    classification = row.get("classification")
    allowed_classifications = CLASSIFICATIONS_BY_KIND[kind]
    if classification not in allowed_classifications:
        return (
            f"unsupported classification {classification!r} for {kind} result;"
            f" expected one of {', '.join(allowed_classifications)}"
        )
    summary = row.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        # Blank means absent, same as locators and rationales.
        return "missing or invalid `summary`"
    confidence = row.get("confidence")
    if confidence is not None and (
        isinstance(confidence, bool)
        or not isinstance(confidence, int | float)
        or not 0.0 <= confidence <= 1.0
    ):
        # The prompt contract asks for a confidence between 0 and 1;
        # anything else is a malformed row, not a very confident one.
        return "invalid `confidence`; expected a number between 0 and 1"
    rationale = row.get("rationale")
    if rationale is None:
        rationale = ""
    if not isinstance(rationale, str):
        return "invalid `rationale`; expected a string"
    if confidence is None and not rationale.strip():
        # The [SC-7] record contract requires a confidence OR rationale
        # field; a row carrying neither is malformed, not low-effort.
        return "missing `confidence` or `rationale`; rows must carry at least one"
    evidence_raw = row.get("evidence")
    evidence: list[tuple[str, int]] = []
    if not isinstance(evidence_raw, list):
        # `evidence` is a required key (an empty list is a valid value:
        # it states explicitly that no evidence is cited).
        return "missing or invalid `evidence`; expected a list"
    for item in evidence_raw:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("path"), str)
            or not item["path"].strip()
            or isinstance(item.get("line"), bool)
            or not isinstance(item.get("line"), int)
            or item["line"] < 1
        ):
            return "invalid `evidence` item; expected {non-empty path, line >= 1}"
        if allowed_evidence is not None:
            # [SC-7]: model output is untrusted; evidence must stay inside
            # the packet boundary -- both the path and the line.
            ranges = allowed_evidence.get(item["path"])
            if ranges is None:
                return f"evidence path `{item['path']}` is not part of the packet"
            if not ranges:
                return (
                    f"evidence line {item['line']} in `{item['path']}` is"
                    " fabricated: the packet named this path without"
                    " line-bounded content"
                )
            if not any(start <= item["line"] <= end for start, end in ranges):
                return (
                    f"evidence line {item['line']} in `{item['path']}` is"
                    " outside the packet's shown content"
                )
        evidence.append((item["path"], item["line"]))
    return AnalysisResult(
        packet_id=packet_id,
        kind=kind,
        content_hash=content_hash,
        classification=classification,
        confidence=float(confidence) if confidence is not None else None,
        rationale=rationale,
        evidence=tuple(evidence),
        summary=summary,
    )


def analysis_result_to_row(result: AnalysisResult) -> dict[str, Any]:
    """Serialize a validated result with canonical trusted metadata."""

    row: dict[str, Any] = {
        "packet_id": result.packet_id,
        "kind": result.kind,
        "classification": result.classification,
        "summary": result.summary,
        "rationale": result.rationale,
        "evidence": [{"path": path, "line": line} for path, line in result.evidence],
    }
    if result.confidence is not None:
        row["confidence"] = result.confidence
    if result.kind == "invariant":
        row["content_hash"] = result.content_hash
    return row


def load_analysis_results(
    text: str,
    known_packet_ids: set[str] | Mapping[str, str] | None,
) -> AnalysisLoad:
    """Parse analysis JSONL; bad rows become errors, not exceptions."""

    results: list[AnalysisResult] = []
    errors: list[str] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"line {line_no}: invalid JSON ({exc.msg})")
            continue
        validated = validate_analysis_row(row, known_packet_ids)
        if isinstance(validated, str):
            errors.append(f"line {line_no}: {validated}")
        else:
            results.append(validated)
    return AnalysisLoad(results=tuple(results), errors=tuple(errors))


def packet_ids_from_report(report_data: dict[str, Any]) -> set[str]:
    """Derive valid packet IDs from a deterministic report.

    Packet generation ([SC-6]) emits a packet only for sections that have
    at least one trace edge, so the valid-ID universe is edge-bearing
    sections -- a forged analysis row for a section that never produced a
    packet must be rejected, not summarized.
    """

    return set(packet_identities_from_report(report_data))


def packet_identities_from_report(report_data: dict[str, Any]) -> dict[str, str]:
    """Derive packet IDs and kinds that a deterministic report can emit."""

    identities = {
        f"{edge['spec_path']}#{edge['section_id']}": "section"
        for edge in report_data.get("edges", [])
    }
    identities.update(
        {
            f"invariant::{bind['invariant_id']}": "invariant"
            for bind in report_data.get("binds", [])
        }
    )
    return identities


def render_analysis_summary(summary: Mapping[str, int], load: AnalysisLoad) -> str:
    """Render deterministic and semantic findings, kept clearly separate.

    ``summary`` is the deterministic report's counts mapping — either
    ``Report.summary()`` or the ``summary`` key of a parsed JSON report.
    Structurally valid JSON missing the count keys is malformed input
    ([SC-5]): raise a one-line ``ValueError`` for the CLI to map to exit 2,
    never a ``KeyError`` traceback (known fable defect fixed at port time).
    """

    # The [SC-6] summary contract has seven count keys, not just the three
    # this renderer happens to print.
    count_keys = (
        "spec_sections",
        "code_refs",
        "spec_mappings",
        "invariants",
        "errors",
        "warnings",
        "infos",
    )
    missing = [key for key in count_keys if key not in summary]
    if missing:
        msg = (
            "deterministic report summary is missing required count"
            f" keys: {', '.join(missing)}"
        )
        raise ValueError(msg)
    bad = [
        key
        for key in count_keys
        if isinstance(summary[key], bool)
        or not isinstance(summary[key], int)
        or summary[key] < 0
    ]
    if bad:
        # Counts are non-negative integers; anything else would render a
        # nonsense line like "[] warnings" instead of failing the input.
        msg = f"deterministic report summary has non-count values for: {', '.join(bad)}"
        raise ValueError(msg)

    lines = [
        "backstitch analysis summary",
        "",
        (
            f"deterministic: {summary['errors']} errors,"
            f" {summary['warnings']} warnings, {summary['infos']} infos"
            " (unchanged by semantic analysis)"
        ),
        "",
        "semantic findings (advisory):",
    ]
    for kind in ("section", "invariant"):
        kind_results = [result for result in load.results if result.kind == kind]
        lines.append(f"  {kind} packets:")
        if not kind_results:
            lines.append("    none")
            continue
        counts: dict[str, int] = {}
        for result in kind_results:
            counts[result.classification] = counts.get(result.classification, 0) + 1
        lines.append(
            "    "
            + ", ".join(
                f"{counts[classification]} {classification}"
                for classification in CLASSIFICATIONS_BY_KIND[kind]
                if classification in counts
            )
        )
        for result in kind_results:
            confidence = (
                f" (confidence {result.confidence:.2f})"
                if result.confidence is not None
                else ""
            )
            lines.append(
                f"    {result.packet_id} [{result.classification}]"
                f" {result.summary}{confidence}"
            )
    if load.errors:
        lines.append("")
        lines.append("analysis input problems:")
        lines.extend(f"  {error}" for error in load.errors)
    return "\n".join(lines) + "\n"
