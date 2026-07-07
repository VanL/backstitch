"""Trust-boundary validation for Backstitch machine-readable artifacts.

Spec: docs/specs/02-backstitch-core.md [SC-6], [SC-11], [SC-13]
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backstitch.grammar import is_valid_section_id
from backstitch.models import ISSUE_CODES

# The [SC-6] packet record contract, as produced by generate_packets().
# `packet_id` and `instructions` must additionally be non-empty: the
# pipeline addresses results by the former and prompts with the latter.
PACKET_FIELDS: tuple[tuple[str, type], ...] = (
    ("packet_id", str),
    ("spec_path", str),
    ("section_id", str),
    ("title", str),
    ("section_text", str),
    ("section_start_line", int),
    ("owners", list),
    ("tests", list),
    ("issues", list),
    ("packet_warnings", list),
    ("instructions", str),
)


def _is_issue_record(issue: object) -> bool:
    """[SC-11] issue record: known code, real severity, path locator,
    1-based optional line, grammar-valid optional section_id, typed symbol.

    One validator for every place an issue record can arrive as untrusted
    input (packet JSONL, deterministic reports).
    """

    return (
        isinstance(issue, dict)
        and issue.get("code") in ISSUE_CODES
        and issue.get("severity") in ("error", "warning", "info")
        and isinstance(issue.get("message"), str)
        and _is_path_locator(issue.get("path"))
        and not isinstance(issue.get("line"), bool)
        and (
            issue.get("line") is None
            or (isinstance(issue["line"], int) and issue["line"] >= 1)
        )
        and (
            issue.get("section_id") is None
            or (
                isinstance(issue["section_id"], str)
                and is_valid_section_id(issue["section_id"])
            )
        )
        and _is_optional_name(issue.get("symbol"))
    )


def _is_optional_name(value: object) -> bool:
    """[SC-13] optional names are null or non-blank strings."""

    return value is None or (isinstance(value, str) and bool(value.strip()))


def _is_path_locator(value: object) -> bool:
    """A path locator is a non-blank string; blank means absent."""

    return isinstance(value, str) and bool(value.strip())


def _packet_shape_error(row: dict[str, Any]) -> str | None:
    """Return an [SC-6] contract violation description, or None if valid."""

    for field_name, field_type in PACKET_FIELDS:
        value = row.get(field_name)
        if isinstance(value, bool) or not isinstance(value, field_type):
            return f"missing or invalid `{field_name}`"
    if not row["packet_id"].strip() or not row["instructions"].strip():
        return "`packet_id` and `instructions` must be non-empty"
    if not _is_path_locator(row["spec_path"]):
        return "`spec_path` and `section_id` must be non-empty"
    if not row["title"].strip():
        return "`title` must be non-empty"
    if not is_valid_section_id(row["section_id"]):
        return "invalid `section_id`; expected a spec section ID"
    if row["packet_id"] != f"{row['spec_path']}#{row['section_id']}":
        return "`packet_id` does not match `spec_path#section_id`"
    if row["section_start_line"] < 1:
        return "invalid `section_start_line`; expected an integer >= 1"
    for owner in row["owners"]:
        if (
            not isinstance(owner, dict)
            or not _is_path_locator(owner.get("path"))
            or not _is_optional_name(owner.get("symbol"))
            or isinstance(owner.get("start_line"), bool)
            or not isinstance(owner.get("start_line"), int)
            or owner["start_line"] < 1
            or not isinstance(owner.get("snippet"), str)
        ):
            return (
                "invalid `owners` item; expected {non-empty path, symbol,"
                " start_line >= 1, snippet}"
            )
    if not all(_is_path_locator(t) for t in row["tests"]):
        return "invalid `tests` item; expected non-empty path strings"
    for issue in row["issues"]:
        if not _is_issue_record(issue):
            return (
                "invalid `issues` item; expected a deterministic issue"
                " record (known code, severity, message, path, and typed"
                " line/section_id/symbol)"
            )
    if not all(isinstance(w, str) for w in row["packet_warnings"]):
        return "invalid `packet_warnings` item; expected strings"
    return None


def load_packets(path: Path) -> list[dict[str, Any]]:
    """Load and validate packet JSONL ([SC-6]).

    A malformed packets file is an invocation error ([SC-5] exit 2), never
    a model-analysis result: invalid packets must be rejected here, before
    any of them can reach analyze_packets.
    """

    packets: list[dict[str, Any]] = []
    for line_no, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            msg = f"{path}:{line_no}: malformed packet JSONL: {exc}"
            raise ValueError(msg) from None
        if not isinstance(row, dict):
            msg = f"{path}:{line_no}: packet line is not a JSON object"
            raise ValueError(msg)
        problem = _packet_shape_error(row)
        if problem is not None:
            msg = f"{path}:{line_no}: malformed packet: {problem}"
            raise ValueError(msg)
        packets.append(row)
    return packets


def load_deterministic_report(path: Path) -> dict[str, Any]:
    """Load and validate a deterministic JSON report ([SC-13])."""

    try:
        report_data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        msg = f"{path}: not valid JSON: {exc}"
        raise ValueError(msg) from None
    if not isinstance(report_data, dict):
        msg = f"{path}: not a backstitch deterministic report"
        raise ValueError(msg)
    report_keys = (
        ("profile", str),
        ("repo_root", str),
        ("summary", dict),
        ("spec_sections", list),
        ("code_refs", list),
        ("spec_mappings", list),
        ("edges", list),
        ("issues", list),
    )
    for key, key_type in report_keys:
        if not isinstance(report_data.get(key), key_type):
            msg = (
                f"{path}: not a backstitch deterministic"
                f" report (missing or invalid `{key}`)"
            )
            raise ValueError(msg)
    _validate_edges(path, report_data)
    _validate_sections(path, report_data)
    _validate_code_refs(path, report_data)
    _validate_spec_mappings(path, report_data)
    _validate_issues_and_summary(path, report_data)
    return report_data


def _validate_edges(path: Path, report_data: dict[str, Any]) -> None:
    for position, edge in enumerate(report_data["edges"]):
        if (
            not isinstance(edge, dict)
            or edge.get("kind") not in ("mapping", "backlink")
            or not _is_path_locator(edge.get("spec_path"))
            or not isinstance(edge.get("section_id"), str)
            or not is_valid_section_id(edge["section_id"])
            or not _is_path_locator(edge.get("code_path"))
            or not _is_optional_name(edge.get("code_symbol"))
            or isinstance(edge.get("line"), bool)
            or not isinstance(edge.get("line"), int)
            or edge["line"] < 1
        ):
            msg = (
                f"{path}: not a backstitch deterministic"
                f" report (invalid `edges[{position}]`: expected a full trace"
                " edge record)"
            )
            raise ValueError(msg)


def _validate_sections(path: Path, report_data: dict[str, Any]) -> None:
    sections: set[tuple[str, str]] = set()
    for position, section in enumerate(report_data["spec_sections"]):
        if (
            not isinstance(section, dict)
            or not _is_path_locator(section.get("path"))
            or not isinstance(section.get("section_id"), str)
            or not is_valid_section_id(section["section_id"])
            or not isinstance(section.get("title"), str)
            or not section["title"].strip()
            or isinstance(section.get("line"), bool)
            or not isinstance(section.get("line"), int)
            or section["line"] < 1
            or not (
                section.get("anchor") is None
                or (isinstance(section["anchor"], str) and section["anchor"].strip())
            )
            or section.get("kind") not in ("heading", "invariant", "bullet")
        ):
            msg = (
                f"{path}: not a backstitch deterministic"
                f" report (invalid `spec_sections[{position}]`: expected a"
                " full section record)"
            )
            raise ValueError(msg)
        sections.add((section["path"], section["section_id"]))
    for position, edge in enumerate(report_data["edges"]):
        if (edge["spec_path"], edge["section_id"]) not in sections:
            msg = (
                f"{path}: not a backstitch deterministic"
                f" report (`edges[{position}]` references"
                f" `{edge['spec_path']}#{edge['section_id']}`, which is not"
                " in `spec_sections`)"
            )
            raise ValueError(msg)


def _validate_code_refs(path: Path, report_data: dict[str, Any]) -> None:
    for position, ref in enumerate(report_data["code_refs"]):
        if (
            not isinstance(ref, dict)
            or not _is_path_locator(ref.get("path"))
            or not isinstance(ref.get("owner_symbol"), str)
            or not ref["owner_symbol"].strip()
            or isinstance(ref.get("line"), bool)
            or not isinstance(ref.get("line"), int)
            or ref["line"] < 1
            or not isinstance(ref.get("raw"), str)
            or not (ref.get("spec_path") is None or _is_path_locator(ref["spec_path"]))
            or not isinstance(ref.get("section_ids"), list)
            or not all(
                isinstance(s, str) and is_valid_section_id(s)
                for s in ref["section_ids"]
            )
            or not _is_optional_name(ref.get("anchor"))
            or not isinstance(ref.get("ranges"), list)
            or not all(
                isinstance(r, list)
                and len(r) == 2
                and all(isinstance(x, str) for x in r)
                for r in ref["ranges"]
            )
            or ref.get("ref_context") not in ("asserted", "docstring", "comment")
        ):
            msg = (
                f"{path}: not a backstitch deterministic"
                f" report (invalid `code_refs[{position}]`: expected a full"
                " code reference record)"
            )
            raise ValueError(msg)


def _validate_spec_mappings(path: Path, report_data: dict[str, Any]) -> None:
    for position, mapping in enumerate(report_data["spec_mappings"]):
        if (
            not isinstance(mapping, dict)
            or not _is_path_locator(mapping.get("spec_path"))
            or not isinstance(mapping.get("section_id"), str)
            or not is_valid_section_id(mapping["section_id"])
            or isinstance(mapping.get("line"), bool)
            or not isinstance(mapping.get("line"), int)
            or mapping["line"] < 1
            or not isinstance(mapping.get("target"), str)
            or not mapping["target"].strip()
            or mapping.get("kind") not in ("path", "path_symbol", "symbol")
            or not (
                mapping.get("target_path") is None
                or _is_path_locator(mapping["target_path"])
            )
            or not _is_optional_name(mapping.get("target_symbol"))
        ):
            msg = (
                f"{path}: not a backstitch deterministic"
                f" report (invalid `spec_mappings[{position}]`: expected a"
                " full mapping record)"
            )
            raise ValueError(msg)


def _validate_issues_and_summary(path: Path, report_data: dict[str, Any]) -> None:
    severity_counts = {"error": 0, "warning": 0, "info": 0}
    for position, issue in enumerate(report_data["issues"]):
        if not _is_issue_record(issue):
            msg = (
                f"{path}: not a backstitch deterministic"
                f" report (invalid `issues[{position}]`: expected a"
                " deterministic issue record)"
            )
            raise ValueError(msg)
        severity_counts[issue["severity"]] += 1
    expected_counts = {
        "spec_sections": len(report_data["spec_sections"]),
        "code_refs": len(report_data["code_refs"]),
        "spec_mappings": len(report_data["spec_mappings"]),
        "errors": severity_counts["error"],
        "warnings": severity_counts["warning"],
        "infos": severity_counts["info"],
    }
    summary_data = report_data["summary"]
    missing = [key for key in expected_counts if key not in summary_data]
    if missing:
        msg = (
            f"{path}: not a backstitch deterministic"
            " report (summary is missing required count keys:"
            f" {', '.join(missing)})"
        )
        raise ValueError(msg)
    bad = [
        key
        for key in expected_counts
        if isinstance(summary_data[key], bool)
        or not isinstance(summary_data[key], int)
        or summary_data[key] < 0
    ]
    if bad:
        msg = (
            f"{path}: not a backstitch deterministic"
            " report (summary has non-count values for:"
            f" {', '.join(bad)})"
        )
        raise ValueError(msg)
    disagreeing = [
        key
        for key, expected in expected_counts.items()
        if summary_data[key] != expected
    ]
    if disagreeing:
        msg = (
            f"{path}: not a backstitch deterministic"
            " report (summary counts disagree with report contents for:"
            f" {', '.join(disagreeing)})"
        )
        raise ValueError(msg)
