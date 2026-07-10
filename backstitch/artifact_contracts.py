"""Trust-boundary validation for Backstitch machine-readable artifacts.

Spec: docs/specs/02-backstitch-core.md [SC-6], [SC-11], [SC-13]
Spec: docs/specs/05-backstitch-invariants.md [INV-5], [INV-7]
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from backstitch.diagnostics import default_level_for, default_registry, short_code_for
from backstitch.grammar import is_valid_section_id
from backstitch.models import ISSUE_CODES

# The [SC-6] packet record contract, as produced by generate_packets().
# `packet_id` and `instructions` must additionally be non-empty: the
# pipeline addresses results by the former and prompts with the latter.
SECTION_PACKET_FIELDS: tuple[tuple[str, type], ...] = (
    ("packet_id", str),
    ("kind", str),
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
INVARIANT_PACKET_FIELDS: tuple[tuple[str, type], ...] = (
    ("packet_id", str),
    ("kind", str),
    ("invariant_id", str),
    ("tier", str),
    ("statement", str),
    ("declaration", dict),
    ("targets", list),
    ("binding_tests", list),
    ("issues", list),
    ("packet_warnings", list),
    ("instructions", str),
    ("content_hash", str),
)
INVARIANT_ONLY_PACKET_FIELDS = frozenset(
    field for field, _ in INVARIANT_PACKET_FIELDS
) - {"packet_id", "kind", "issues", "packet_warnings", "instructions"}


def invariant_content_hash(
    statement: str,
    targets: list[dict[str, Any]],
    binding_tests: list[dict[str, Any]],
) -> str:
    """Hash the bounded invariant evidence projection from [SC-6]."""

    fields = ("path", "symbol", "start_line", "snippet")
    projection = {
        "statement": statement,
        "targets": [{key: item[key] for key in fields} for item in targets],
        "binding_tests": [{key: item[key] for key in fields} for item in binding_tests],
    }
    encoded = json.dumps(
        projection,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


_INVARIANT_FIELDS = frozenset(
    {
        "invariant_id",
        "statement",
        "tier",
        "declaration_kind",
        "path",
        "line",
        "owner_symbol",
        "section_id",
    }
)
_BIND_FIELDS = frozenset(
    {
        "invariant_id",
        "test_path",
        "test_symbol",
        "marker_line",
        "start_line",
        "end_line",
    }
)


def _is_issue_record(issue: object, *, require_invariant_locator: bool = False) -> bool:
    """[SC-11] issue record: known code, real severity, path locator,
    1-based optional line, grammar-valid optional section_id, typed symbol.

    One validator for every place an issue record can arrive as untrusted
    input (packet JSONL, deterministic reports).
    """

    if not isinstance(issue, dict):
        return False
    if require_invariant_locator and "invariant_id" not in issue:
        return False
    code = issue.get("code")
    context = issue.get("context")
    invariant_id = issue.get("invariant_id")
    if not isinstance(code, str) or code not in ISSUE_CODES:
        return False
    contexts = default_registry().require(code).contexts
    if contexts:
        if not isinstance(context, str) or context not in contexts:
            return False
    elif context is not None:
        return False
    return (
        issue.get("short_code") == short_code_for(code)
        and issue.get("severity") in ("error", "warning", "info")
        and issue.get("default_severity") == default_level_for(code, context)
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
        and (
            invariant_id is None
            or (isinstance(invariant_id, str) and is_valid_section_id(invariant_id))
        )
        and not (issue.get("section_id") is not None and invariant_id is not None)
        and (code.startswith("INVARIANT_") or invariant_id is None)
        and (not code.startswith("INVARIANT_") or issue.get("section_id") is None)
        and _is_optional_name(issue.get("symbol"))
    )


def _is_optional_name(value: object) -> bool:
    """[SC-13] optional names are null or non-blank strings."""

    return value is None or (isinstance(value, str) and bool(value.strip()))


def _is_path_locator(value: object) -> bool:
    """A path locator is a non-blank string; blank means absent."""

    return isinstance(value, str) and bool(value.strip())


def _required_fields_error(
    row: dict[str, Any],
    fields: tuple[tuple[str, type], ...],
) -> str | None:
    for field_name, field_type in fields:
        value = row.get(field_name)
        if isinstance(value, bool) or not isinstance(value, field_type):
            return f"missing or invalid `{field_name}`"
    return None


def _snippet_item_error(item: object, field_name: str) -> str | None:
    if (
        not isinstance(item, dict)
        or not _is_path_locator(item.get("path"))
        or not _is_optional_name(item.get("symbol"))
        or isinstance(item.get("start_line"), bool)
        or not isinstance(item.get("start_line"), int)
        or item["start_line"] < 1
        or not isinstance(item.get("snippet"), str)
    ):
        return (
            f"invalid `{field_name}` item; expected {{non-empty path, symbol,"
            " start_line >= 1, snippet}"
        )
    return None


def _section_packet_shape_error(
    row: dict[str, Any],
    *,
    legacy: bool = False,
) -> str | None:
    """Return a section-packet contract violation, or None if valid."""

    fields = (
        tuple(item for item in SECTION_PACKET_FIELDS if item[0] != "kind")
        if legacy
        else SECTION_PACKET_FIELDS
    )
    problem = _required_fields_error(row, fields)
    if problem is not None:
        return problem
    if not legacy and row["kind"] != "section":
        return "invalid `kind`; expected `section`"
    mixed = sorted(INVARIANT_ONLY_PACKET_FIELDS.intersection(row))
    if mixed:
        return f"section packet contains invariant-only `{mixed[0]}`"
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
        problem = _snippet_item_error(owner, "owners")
        if problem is not None:
            return problem
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


def _invariant_packet_shape_error(row: dict[str, Any]) -> str | None:
    """Return an invariant-packet contract violation, or None if valid."""

    problem = _required_fields_error(row, INVARIANT_PACKET_FIELDS)
    if problem is not None:
        return problem
    if row["kind"] != "invariant":
        return "invalid `kind`; expected `invariant`"
    if not is_valid_section_id(row["invariant_id"]):
        return "invalid `invariant_id`"
    if row["packet_id"] != f"invariant::{row['invariant_id']}":
        return "`packet_id` does not match `invariant::<invariant_id>`"
    if row["tier"] not in ("required", "draft"):
        return "invalid `tier`; expected `required` or `draft`"
    if not row["statement"].strip() or not row["instructions"].strip():
        return "`statement` and `instructions` must be non-empty"

    declaration = row["declaration"]
    if (
        declaration.get("kind") not in ("code", "spec")
        or not _is_path_locator(declaration.get("path"))
        or isinstance(declaration.get("line"), bool)
        or not isinstance(declaration.get("line"), int)
        or declaration["line"] < 1
        or not _is_optional_name(declaration.get("symbol"))
        or (
            declaration.get("section_id") is not None
            and (
                not isinstance(declaration["section_id"], str)
                or not is_valid_section_id(declaration["section_id"])
            )
        )
    ):
        return "invalid `declaration` locator"
    symbol_present = declaration.get("symbol") is not None
    section_present = declaration.get("section_id") is not None
    if symbol_present == section_present:
        return "invalid `declaration`; exactly one owner locator is required"
    if declaration["kind"] == "code" and not symbol_present:
        return "invalid code `declaration`; expected `symbol` owner"
    if declaration["kind"] == "spec" and not section_present:
        return "invalid spec `declaration`; expected `section_id` owner"

    for field_name in ("targets", "binding_tests"):
        for item in row[field_name]:
            problem = _snippet_item_error(item, field_name)
            if problem is not None:
                return problem
    for issue in row["issues"]:
        if (
            not _is_issue_record(issue, require_invariant_locator=True)
            or issue.get("invariant_id") != row["invariant_id"]
        ):
            return (
                "invalid `issues` item; expected an invariant issue matching"
                " the packet invariant ID"
            )
    if not all(isinstance(w, str) for w in row["packet_warnings"]):
        return "invalid `packet_warnings` item; expected strings"

    expected_hash = invariant_content_hash(
        row["statement"], row["targets"], row["binding_tests"]
    )
    if row["content_hash"] != expected_hash:
        return "invalid `content_hash`; expected the bounded packet projection hash"
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
        kind = row.get("kind")
        problem: str | None
        if "kind" not in row:
            packet_id = row.get("packet_id")
            if isinstance(packet_id, str) and packet_id.startswith("invariant::"):
                problem = "missing `kind` for invariant packet identity"
            else:
                problem = _section_packet_shape_error(row, legacy=True)
                if problem is None:
                    row["kind"] = "section"
        elif kind == "section":
            problem = _section_packet_shape_error(row)
        elif kind == "invariant":
            problem = _invariant_packet_shape_error(row)
        else:
            problem = "invalid `kind`; expected `section` or `invariant`"
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
    _normalize_report_invariant_shape(path, report_data)
    _validate_edges(path, report_data)
    _validate_sections(path, report_data)
    _validate_code_refs(path, report_data)
    _validate_spec_mappings(path, report_data)
    _validate_invariants_and_binds(path, report_data)
    _validate_issues_and_summary(path, report_data)
    return report_data


def _normalize_report_invariant_shape(path: Path, report_data: dict[str, Any]) -> None:
    summary = report_data["summary"]
    presence = (
        "invariants" in summary,
        "invariants" in report_data,
        "binds" in report_data,
    )
    if not any(presence):
        summary["invariants"] = 0
        report_data["invariants"] = []
        report_data["binds"] = []
        for issue in report_data["issues"]:
            if isinstance(issue, dict):
                issue.setdefault("invariant_id", None)
        return
    if not all(presence):
        msg = (
            f"{path}: not a backstitch deterministic report"
            " (partial invariant report shape; `summary.invariants`,"
            " `invariants`, and `binds` must be all present or all absent)"
        )
        raise ValueError(msg)
    if not isinstance(report_data["invariants"], list) or not isinstance(
        report_data["binds"], list
    ):
        msg = (
            f"{path}: not a backstitch deterministic report"
            " (missing or invalid `invariants` or `binds`)"
        )
        raise ValueError(msg)


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


def _validate_invariants_and_binds(path: Path, report_data: dict[str, Any]) -> None:
    invariant_counts: dict[str, int] = {}
    for position, invariant in enumerate(report_data["invariants"]):
        if not isinstance(invariant, dict) or not _INVARIANT_FIELDS <= invariant.keys():
            valid = False
        else:
            invariant_id = invariant.get("invariant_id")
            owner_symbol = invariant.get("owner_symbol")
            section_id = invariant.get("section_id")
            declaration_kind = invariant.get("declaration_kind")
            owner_shape_valid = (
                declaration_kind == "code"
                and _is_path_locator(owner_symbol)
                and section_id is None
            ) or (
                declaration_kind == "spec"
                and owner_symbol is None
                and isinstance(section_id, str)
                and is_valid_section_id(section_id)
            )
            valid = (
                isinstance(invariant_id, str)
                and is_valid_section_id(invariant_id)
                and isinstance(invariant.get("statement"), str)
                and bool(invariant["statement"].strip())
                and invariant.get("tier") in ("required", "draft")
                and owner_shape_valid
                and _is_path_locator(invariant.get("path"))
                and not isinstance(invariant.get("line"), bool)
                and isinstance(invariant.get("line"), int)
                and invariant["line"] >= 1
            )
        if not valid:
            msg = (
                f"{path}: not a backstitch deterministic"
                f" report (invalid `invariants[{position}]`: expected a full"
                " invariant declaration with exactly one owner locator)"
            )
            raise ValueError(msg)
        invariant_counts[invariant["invariant_id"]] = (
            invariant_counts.get(invariant["invariant_id"], 0) + 1
        )

    section_ids = {section["section_id"] for section in report_data["spec_sections"]}
    seen_binds: set[tuple[str, str, str]] = set()
    for position, binding in enumerate(report_data["binds"]):
        if not isinstance(binding, dict) or not _BIND_FIELDS <= binding.keys():
            valid = False
        else:
            invariant_id = binding.get("invariant_id")
            line_fields = (
                binding.get("marker_line"),
                binding.get("start_line"),
                binding.get("end_line"),
            )
            valid = (
                isinstance(invariant_id, str)
                and is_valid_section_id(invariant_id)
                and invariant_counts.get(invariant_id) == 1
                and invariant_id not in section_ids
                and _is_path_locator(binding.get("test_path"))
                and _is_path_locator(binding.get("test_symbol"))
                and all(
                    not isinstance(value, bool)
                    and isinstance(value, int)
                    and value >= 1
                    for value in line_fields
                )
                and binding["start_line"] <= binding["end_line"]
            )
        if not valid:
            msg = (
                f"{path}: not a backstitch deterministic"
                f" report (invalid `binds[{position}]`: expected a unique"
                " relation to one non-colliding invariant declaration)"
            )
            raise ValueError(msg)
        invariant_id = binding["invariant_id"]
        test_path = binding["test_path"]
        test_symbol = binding["test_symbol"]
        assert isinstance(invariant_id, str)
        assert isinstance(test_path, str)
        assert isinstance(test_symbol, str)
        key = (invariant_id, test_path, test_symbol)
        if key in seen_binds:
            msg = (
                f"{path}: not a backstitch deterministic report"
                f" (duplicate bind relation at `binds[{position}]`)"
            )
            raise ValueError(msg)
        seen_binds.add(key)


def _validate_issues_and_summary(path: Path, report_data: dict[str, Any]) -> None:
    severity_counts = {"error": 0, "warning": 0, "info": 0}
    for position, issue in enumerate(report_data["issues"]):
        if not _is_issue_record(issue, require_invariant_locator=True):
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
        "invariants": len(report_data["invariants"]),
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
