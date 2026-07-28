"""Trust-boundary validation for Backstitch machine-readable artifacts.

Spec: docs/specs/02-backstitch-core.md [SC-6], [SC-11], [SC-13]
Spec: docs/specs/05-backstitch-invariants.md [INV-5], [INV-7]
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backstitch.canonical import canonical_json_bytes, lf_line_count, lf_split
from backstitch.diagnostics import default_level_for, default_registry, short_code_for
from backstitch.grammar import (
    candidate_ref_digest,
    is_sha256_hex,
    is_valid_section_id,
    is_valid_suppression_reference,
)
from backstitch.models import ISSUE_CODES
from backstitch.semantic_packets import (
    DECLARATION_FIELDS,
    ISSUE_FIELDS,
    MAX_BINDING_TESTS_PER_PACKET,
    MAX_INVARIANT_TARGETS_PER_PACKET,
    MAX_OWNERS_PER_PACKET,
    MAX_SECTION_LINES,
    MAX_SNIPPET_LINES,
    SNIPPET_FIELDS,
    semantic_packet_hash,
)


@dataclass(frozen=True, slots=True)
class ValidatedSemanticPacket:
    """Immutable validated packet plus its cache-authority boundary."""

    _canonical_row: bytes
    cache_eligible: bool

    @classmethod
    def from_row(
        cls, row: dict[str, Any], *, cache_eligible: bool
    ) -> ValidatedSemanticPacket:
        return cls(canonical_json_bytes(row), cache_eligible)

    def to_dict(self) -> dict[str, Any]:
        row = json.loads(self._canonical_row)
        assert isinstance(row, dict)
        return row

    @property
    def semantic_eligible(self) -> bool:
        """Current schema-3 and schema-4 packets may enter inference."""

        return self.to_dict().get("schema_version") in {3, 4}


# Legacy [SC-6] schema-less packet field inventory. Schema 2 derives its
# migration shape from this inventory; current schema 3 is produced by
# generate_source_aligned_packets() and validated separately below.
# `packet_id` and `instructions` must additionally be non-empty for the legacy
# shapes: the pipeline addresses results by the former and prompts with the latter.
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
    return hashlib.sha256(canonical_json_bytes(projection)).hexdigest()


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


def _closed_snippet_item_error(item: object, field_name: str) -> str | None:
    problem = _snippet_item_error(item, field_name)
    if problem is not None:
        return problem
    assert isinstance(item, dict)
    if set(item) != set(SNIPPET_FIELDS):
        return f"invalid `{field_name}` item; expected the closed semantic shape"
    if lf_line_count(item["snippet"]) > MAX_SNIPPET_LINES:
        return f"invalid `{field_name}` item; snippet exceeds {MAX_SNIPPET_LINES} lines"
    return None


def _snippet_order_key(item: dict[str, Any]) -> tuple[str, str, int]:
    return (item["path"], item["symbol"] or "", item["start_line"])


def _ordered_unique_snippets_error(
    items: list[dict[str, Any]], field_name: str
) -> str | None:
    keys = [_snippet_order_key(item) for item in items]
    if keys != sorted(keys):
        return f"invalid `{field_name}`; expected canonical packet order"
    if len(keys) != len(set(keys)):
        return f"invalid `{field_name}`; duplicate snippet locator"
    return None


def _semantic_issue_error(
    issue: object,
    *,
    invariant_id: str | None,
) -> str | None:
    if not isinstance(issue, dict) or set(issue) != set(ISSUE_FIELDS):
        return "invalid `issues` item; expected the closed policy-neutral shape"
    candidate = dict(issue)
    candidate["severity"] = candidate.get("default_severity")
    if not _is_issue_record(
        candidate, require_invariant_locator=invariant_id is not None
    ):
        return "invalid `issues` item; expected a valid deterministic issue"
    if candidate.get("invariant_id") != invariant_id:
        return "invalid `issues` item; invariant locator does not match packet"
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


def _v2_section_packet_shape_error(row: dict[str, Any]) -> str | None:
    fields: tuple[tuple[str, type], ...] = (
        ("schema_version", int),
        *(
            (field, type_)
            for field, type_ in SECTION_PACKET_FIELDS
            if field != "instructions"
        ),
        ("packet_hash", str),
    )
    problem = _required_fields_error(row, fields)
    if problem is not None:
        return problem
    if row["schema_version"] != 2:
        return "invalid `schema_version`; expected 2"
    if "instructions" in row:
        return "v2 packet must not contain `instructions`"
    if row["kind"] != "section":
        return "invalid `kind`; expected `section`"
    mixed = sorted(INVARIANT_ONLY_PACKET_FIELDS.intersection(row))
    if mixed:
        return f"section packet contains invariant-only `{mixed[0]}`"
    if not row["packet_id"].strip():
        return "`packet_id` must be non-empty"
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
    if lf_line_count(row["section_text"]) > MAX_SECTION_LINES:
        return f"invalid `section_text`; exceeds {MAX_SECTION_LINES} lines"
    if len(row["owners"]) > MAX_OWNERS_PER_PACKET:
        return f"invalid `owners`; exceeds {MAX_OWNERS_PER_PACKET} entries"
    for owner in row["owners"]:
        problem = _closed_snippet_item_error(owner, "owners")
        if problem is not None:
            return problem
    problem = _ordered_unique_snippets_error(row["owners"], "owners")
    if problem is not None:
        return problem
    if not all(_is_path_locator(test) for test in row["tests"]):
        return "invalid `tests` item; expected non-empty path strings"
    if row["tests"] != sorted(set(row["tests"])):
        return "invalid `tests`; expected unique canonical path order"
    if not row["owners"] and not row["tests"]:
        return "invalid `owners` and `tests`; a section packet requires a resolved edge"
    for issue in row["issues"]:
        problem = _semantic_issue_error(issue, invariant_id=None)
        if problem is not None:
            return problem
    if not all(isinstance(warning, str) for warning in row["packet_warnings"]):
        return "invalid `packet_warnings` item; expected strings"
    try:
        expected_hash = semantic_packet_hash(row)
    except (KeyError, TypeError, ValueError):
        return "invalid semantic packet projection"
    if row["packet_hash"] != expected_hash:
        return "invalid `packet_hash`; expected the semantic projection hash"
    return None


def _v2_invariant_packet_shape_error(row: dict[str, Any]) -> str | None:
    fields: tuple[tuple[str, type], ...] = (
        ("schema_version", int),
        *(
            (field, type_)
            for field, type_ in INVARIANT_PACKET_FIELDS
            if field != "instructions"
        ),
        ("packet_hash", str),
    )
    problem = _required_fields_error(row, fields)
    if problem is not None:
        return problem
    if row["schema_version"] != 2:
        return "invalid `schema_version`; expected 2"
    if "instructions" in row:
        return "v2 packet must not contain `instructions`"
    if row["kind"] != "invariant":
        return "invalid `kind`; expected `invariant`"
    if not is_valid_section_id(row["invariant_id"]):
        return "invalid `invariant_id`"
    if row["packet_id"] != f"invariant::{row['invariant_id']}":
        return "`packet_id` does not match `invariant::<invariant_id>`"
    if row["tier"] not in ("required", "draft"):
        return "invalid `tier`; expected `required` or `draft`"
    if not row["statement"].strip():
        return "`statement` must be non-empty"

    declaration = row["declaration"]
    if set(declaration) != set(DECLARATION_FIELDS):
        return "invalid `declaration`; expected the closed semantic shape"
    if (
        declaration.get("kind") not in ("code", "spec")
        or not _is_path_locator(declaration.get("path"))
        or isinstance(declaration.get("line"), bool)
        or not isinstance(declaration.get("line"), int)
        or isinstance(declaration.get("start_line"), bool)
        or not isinstance(declaration.get("start_line"), int)
        or isinstance(declaration.get("end_line"), bool)
        or not isinstance(declaration.get("end_line"), int)
        or declaration["start_line"] < 1
        or declaration["end_line"] < declaration["start_line"]
        or not declaration["start_line"]
        <= declaration["line"]
        <= declaration["end_line"]
        or not isinstance(declaration.get("excerpt"), str)
        or not declaration["excerpt"].strip()
        or lf_line_count(declaration["excerpt"])
        != declaration["end_line"] - declaration["start_line"] + 1
        or not _is_optional_name(declaration.get("symbol"))
        or (
            declaration.get("section_id") is not None
            and (
                not isinstance(declaration["section_id"], str)
                or not is_valid_section_id(declaration["section_id"])
            )
        )
    ):
        return "invalid `declaration` locator or span"
    symbol_present = declaration["symbol"] is not None
    section_present = declaration["section_id"] is not None
    if symbol_present == section_present:
        return "invalid `declaration`; exactly one owner locator is required"
    if declaration["kind"] == "code" and not symbol_present:
        return "invalid code `declaration`; expected `symbol` owner"
    if declaration["kind"] == "spec" and not section_present:
        return "invalid spec `declaration`; expected `section_id` owner"
    if declaration["start_line"] != declaration["line"]:
        return "invalid `declaration`; source span must start at its marker line"
    if declaration["kind"] == "spec" and declaration["end_line"] != declaration["line"]:
        return "invalid spec `declaration`; expected a one-line declaration span"

    for field_name in ("targets", "binding_tests"):
        for item in row[field_name]:
            problem = _closed_snippet_item_error(item, field_name)
            if problem is not None:
                return problem
        problem = _ordered_unique_snippets_error(row[field_name], field_name)
        if problem is not None:
            return problem
    if not row["binding_tests"]:
        return "invalid `binding_tests`; a semantic invariant packet requires a bind"
    if len(row["targets"]) > MAX_INVARIANT_TARGETS_PER_PACKET:
        return f"invalid `targets`; exceeds {MAX_INVARIANT_TARGETS_PER_PACKET} entries"
    if len(row["binding_tests"]) > MAX_BINDING_TESTS_PER_PACKET:
        return (
            f"invalid `binding_tests`; exceeds {MAX_BINDING_TESTS_PER_PACKET} entries"
        )
    if declaration["kind"] == "code":
        expected_target = (declaration["path"], declaration["symbol"])
        actual_targets = [(item["path"], item["symbol"]) for item in row["targets"]]
        if actual_targets != [expected_target]:
            return "invalid `targets`; code invariant must target its declaration owner"
        if declaration["symbol"] == "<module>" and row["targets"][0]["start_line"] != 1:
            return "invalid `targets`; module invariant target must start at line 1"
    for issue in row["issues"]:
        problem = _semantic_issue_error(issue, invariant_id=row["invariant_id"])
        if problem is not None:
            return problem
    issue_order = [
        (
            issue["path"],
            issue["line"] is not None,
            issue["line"] or 0,
            issue["code"],
            issue["message"],
        )
        for issue in row["issues"]
    ]
    if issue_order != sorted(issue_order) or len(issue_order) != len(set(issue_order)):
        return "invalid `issues`; expected unique canonical invariant issue order"
    if not all(isinstance(warning, str) for warning in row["packet_warnings"]):
        return "invalid `packet_warnings` item; expected strings"

    expected_content_hash = invariant_content_hash(
        row["statement"], row["targets"], row["binding_tests"]
    )
    if row["content_hash"] != expected_content_hash:
        return "invalid `content_hash`; expected the bounded packet projection hash"
    try:
        expected_packet_hash = semantic_packet_hash(row)
    except (KeyError, TypeError, ValueError):
        return "invalid semantic packet projection"
    if row["packet_hash"] != expected_packet_hash:
        return "invalid `packet_hash`; expected the semantic projection hash"
    return None


def _normalize_legacy_packet(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    normalized.pop("instructions", None)
    if "kind" not in normalized:
        normalized["kind"] = "section"
    normalized["issues"] = [
        {field: issue.get(field) for field in ISSUE_FIELDS}
        for issue in normalized["issues"]
    ]
    if normalized["kind"] == "invariant":
        declaration = dict(normalized["declaration"])
        statement_lines = max(1, lf_line_count(normalized["statement"]))
        declaration.update(
            {
                "start_line": declaration["line"],
                "end_line": declaration["line"] + statement_lines - 1,
                "excerpt": normalized["statement"],
            }
        )
        normalized["declaration"] = declaration
    normalized["schema_version"] = 2
    normalized["packet_hash"] = semantic_packet_hash(normalized)
    return normalized


_PACKET_V3_FIELDS = frozenset(
    {
        "schema_version",
        "packet_id",
        "packet_hash",
        "kind",
        "obligation_id",
        "source_snapshot",
        "readiness",
        "requirement",
        "declared_evidence",
        "counterevidence",
        "trace_summary",
        "evidence_regions",
        "issues",
        "packet_warnings",
    }
)
_PACKET_V4_FIELDS = frozenset(
    {
        "schema_version",
        "packet_id",
        "packet_hash",
        "kind",
        "obligation_id",
        "source_snapshot",
        "readiness",
        "requirement",
        "suppression_rules",
        "counterevidence",
        "evidence_regions",
        "issues",
        "packet_warnings",
    }
)
_PACKET_V3_RELATIONS = (
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
_PACKET_V3_BASES = (
    "declared_relation",
    "invariant_relation",
    "resolver_issue",
    "lexical_match",
    "static_neighbor",
    "ambiguous_relation",
)
_PACKET_V3_KINDS = (
    "implementation_definition",
    "test_definition",
    "static_reference",
    "unresolved_reference",
    "report_issue",
)
_PACKET_V3_STATES = (
    "declared",
    "partially_declared",
    "untraced",
    "conflicted",
)
_PACKET_V3_ROLE_ORDER = {
    "requirement": 0,
    "implementation": 1,
    "test": 2,
    "counterevidence": 3,
}


def _packet_v3_relation_list(value: object, *, allow_empty: bool = False) -> bool:
    return (
        isinstance(value, list)
        and (allow_empty or bool(value))
        and all(item in _PACKET_V3_RELATIONS for item in value)
        and value
        == sorted(set(value), key=lambda item: _PACKET_V3_RELATIONS.index(item))
    )


def _packet_v3_span(row: dict[str, Any], text_field: str) -> bool:
    start = row.get("start_line")
    end = row.get("end_line")
    text = row.get(text_field)
    return (
        isinstance(start, int)
        and not isinstance(start, bool)
        and isinstance(end, int)
        and not isinstance(end, bool)
        and start >= 1
        and end >= start
        and isinstance(text, str)
        and max(1, lf_line_count(text) + text.endswith("\n")) == end - start + 1
    )


def _packet_v3_has_contained_regions(
    regions: list[dict[str, Any]],
) -> bool:
    """Return true when a model role/path still has an equal/contained span."""

    for index, left in enumerate(regions):
        for right in regions[index + 1 :]:
            if left["role"] != right["role"] or left["path"] != right["path"]:
                continue
            left_contains = (
                left["start_line"] <= right["start_line"]
                and right["end_line"] <= left["end_line"]
            )
            right_contains = (
                right["start_line"] <= left["start_line"]
                and left["end_line"] <= right["end_line"]
            )
            if left_contains or right_contains:
                return True
    return False


def _packet_v3_shape_error(row: dict[str, Any]) -> str | None:
    if set(row) != _PACKET_V3_FIELDS or row.get("schema_version") != 3:
        return "packet schema 3 does not match its closed top-level shape"
    if row.get("kind") not in {"section", "invariant"}:
        return "packet schema 3 has an invalid kind"
    if (
        not _is_path_locator(row.get("packet_id"))
        or row.get("packet_id") != row.get("obligation_id")
        or not is_sha256_hex(row.get("packet_hash"))
    ):
        return "packet schema 3 has invalid identity fields"
    snapshot = row.get("source_snapshot")
    if (
        not isinstance(snapshot, dict)
        or set(snapshot)
        != {
            "snapshot_hash",
            "obligation_state_hash",
            "derivation_config_hash",
        }
        or not all(is_sha256_hex(value) for value in snapshot.values())
    ):
        return "packet schema 3 has an invalid source snapshot"
    readiness = row.get("readiness")
    if not isinstance(readiness, dict) or set(readiness) != {
        "intent_state",
        "alignment_state",
        "disposition",
        "obligation_rung",
        "gate_state",
        "required_roles",
    }:
        return "packet schema 3 has invalid readiness"
    required_roles = readiness["required_roles"]
    if (
        readiness["intent_state"] != "identified"
        or readiness["alignment_state"] != "complete"
        or readiness["disposition"] != "evaluate"
        or readiness["obligation_rung"] != "active"
        or readiness["gate_state"] != "executable"
        or not isinstance(required_roles, list)
        or any(
            role not in {"implementation", "test", "binding_test"}
            for role in required_roles
        )
        or required_roles
        != sorted(
            set(required_roles),
            key=("implementation", "test", "binding_test").index,
        )
    ):
        return "packet schema 3 must describe one executable obligation"
    requirement = row.get("requirement")
    if (
        not isinstance(requirement, dict)
        or set(requirement)
        != {"role", "path", "identity", "title", "start_line", "end_line", "text"}
        or requirement.get("role") != "requirement"
        or not _is_path_locator(requirement.get("path"))
        or not _is_path_locator(requirement.get("identity"))
        or not (
            requirement.get("title") is None
            or _is_path_locator(requirement.get("title"))
        )
        or not _packet_v3_span(requirement, "text")
        or not requirement["text"].strip()
    ):
        return "packet schema 3 has an invalid requirement"
    if row["kind"] == "section":
        spec_path, separator, section_id = row["packet_id"].rpartition("#")
        if (
            not separator
            or requirement["path"] != spec_path
            or requirement["identity"] != section_id
            or not is_valid_section_id(section_id)
            or not isinstance(requirement["title"], str)
            or not requirement["title"].strip()
            or "binding_test" in required_roles
            or "implementation" not in required_roles
        ):
            return "packet schema 3 section identity/readiness is inconsistent"
    else:
        invariant_id = row["packet_id"].removeprefix("invariant::")
        if (
            row["packet_id"] != f"invariant::{invariant_id}"
            or not invariant_id
            or not is_valid_section_id(invariant_id)
            or requirement["identity"] != invariant_id
            or requirement["title"] is not None
            or required_roles != ["implementation", "binding_test"]
        ):
            return "packet schema 3 invariant identity/readiness is inconsistent"

    declared = row.get("declared_evidence")
    if not isinstance(declared, list):
        return "packet schema 3 declared_evidence must be an array"
    declared_keys: list[tuple[object, ...]] = []
    for region in declared:
        if (
            not isinstance(region, dict)
            or set(region)
            != {
                "role",
                "path",
                "symbol",
                "start_line",
                "end_line",
                "snippet",
                "sources",
            }
            or region.get("role") not in {"implementation", "test"}
            or not _is_path_locator(region.get("path"))
            or not _is_optional_name(region.get("symbol"))
            or not _packet_v3_span(region, "snippet")
            or not isinstance(region.get("sources"), list)
            or not region["sources"]
        ):
            return "packet schema 3 has an invalid declared evidence region"
        source_keys: list[tuple[object, ...]] = []
        for source in region["sources"]:
            if (
                not isinstance(source, dict)
                or set(source)
                != {
                    "source_role",
                    "receipt_hash",
                    "relation_kinds",
                    "reciprocity_state",
                }
                or source.get("source_role")
                not in {"implementation", "test", "binding_test"}
                or not is_sha256_hex(source.get("receipt_hash"))
                or not _packet_v3_relation_list(source.get("relation_kinds"))
                or source.get("reciprocity_state") not in {"complete", "one_sided"}
            ):
                return "packet schema 3 has an invalid declared source"
            expected_model_role = (
                "implementation"
                if source["source_role"] == "implementation"
                else "test"
            )
            if region["role"] != expected_model_role:
                return "packet schema 3 declared model/source roles do not match"
            source_keys.append(
                (
                    ("implementation", "test", "binding_test").index(
                        source["source_role"]
                    ),
                    source["receipt_hash"],
                    tuple(source["relation_kinds"]),
                )
            )
        if source_keys != sorted(set(source_keys)):
            return "packet schema 3 declared sources are not ordered and unique"
        declared_keys.append(
            (
                _PACKET_V3_ROLE_ORDER[region["role"]],
                region["path"],
                region["start_line"],
                region["end_line"],
                region["symbol"] or "",
            )
        )
    if declared_keys != sorted(set(declared_keys)):
        return "packet schema 3 declared regions are not ordered and unique"
    if _packet_v3_has_contained_regions(declared):
        return "packet schema 3 declared regions were not maximally merged"

    declared_sources = {
        canonical_json_bytes(source): source
        for region in declared
        for source in region["sources"]
    }
    for required_role in required_roles:
        if not any(
            source["source_role"] == required_role
            and source["reciprocity_state"] == "complete"
            for source in declared_sources.values()
        ):
            return "packet schema 3 executable readiness lacks required evidence"

    counter = row.get("counterevidence")
    if not isinstance(counter, list):
        return "packet schema 3 counterevidence must be an array"
    counter_keys: list[tuple[object, ...]] = []
    for region in counter:
        if (
            not isinstance(region, dict)
            or set(region)
            != {"role", "path", "start_line", "end_line", "snippet", "candidates"}
            or region.get("role") != "counterevidence"
            or not _is_path_locator(region.get("path"))
            or not _packet_v3_span(region, "snippet")
            or not isinstance(region.get("candidates"), list)
            or not region["candidates"]
        ):
            return "packet schema 3 has an invalid counterevidence region"
        candidate_ids: list[str] = []
        for source in region["candidates"]:
            if (
                not isinstance(source, dict)
                or set(source)
                != {
                    "candidate_id",
                    "candidate_kind",
                    "receipt_hash",
                    "trace_state",
                    "discovery_bases",
                    "relation_kinds",
                }
                or not isinstance(source.get("candidate_id"), str)
                or candidate_ref_digest(source["candidate_id"]) is None
                or source.get("candidate_kind") not in _PACKET_V3_KINDS
                or not is_sha256_hex(source.get("receipt_hash"))
                or source.get("trace_state") not in _PACKET_V3_STATES
                or not isinstance(source.get("discovery_bases"), list)
                or not source["discovery_bases"]
                or any(
                    basis not in _PACKET_V3_BASES for basis in source["discovery_bases"]
                )
                or source["discovery_bases"]
                != sorted(set(source["discovery_bases"]), key=_PACKET_V3_BASES.index)
                or not _packet_v3_relation_list(
                    source.get("relation_kinds"), allow_empty=True
                )
            ):
                return "packet schema 3 has an invalid counterevidence source"
            candidate_ids.append(source["candidate_id"])
        if candidate_ids != sorted(set(candidate_ids)):
            return "packet schema 3 candidate sources are not ordered and unique"
        counter_keys.append(
            (region["path"], region["start_line"], region["end_line"], candidate_ids[0])
        )
    if counter_keys != sorted(set(counter_keys)):
        return "packet schema 3 counterevidence regions are not ordered and unique"
    if _packet_v3_has_contained_regions(counter):
        return "packet schema 3 counterevidence regions were not maximally merged"

    summary = row.get("trace_summary")
    if not isinstance(summary, dict) or set(summary) != {
        "declared_counts",
        "candidate_counts",
        "relation_counts",
    }:
        return "packet schema 3 has an invalid trace summary"
    if not isinstance(summary["declared_counts"], list) or [
        item.get("source_role") if isinstance(item, dict) else None
        for item in summary["declared_counts"]
    ] != ["implementation", "test", "binding_test"]:
        return "packet schema 3 declared counts are incomplete"
    for item in summary["declared_counts"]:
        if (
            set(item) != {"source_role", "total", "complete", "one_sided"}
            or any(
                isinstance(item[field], bool)
                or not isinstance(item[field], int)
                or item[field] < 0
                for field in ("total", "complete", "one_sided")
            )
            or item["total"] != item["complete"] + item["one_sided"]
        ):
            return "packet schema 3 has invalid declared counts"
    if not isinstance(summary["candidate_counts"], list) or [
        item.get("candidate_kind") if isinstance(item, dict) else None
        for item in summary["candidate_counts"]
    ] != list(_PACKET_V3_KINDS):
        return "packet schema 3 candidate counts are incomplete"
    for item in summary["candidate_counts"]:
        if set(item) != {"candidate_kind", *_PACKET_V3_STATES} or any(
            isinstance(item[state], bool)
            or not isinstance(item[state], int)
            or item[state] < 0
            for state in _PACKET_V3_STATES
        ):
            return "packet schema 3 has invalid candidate counts"
    if not isinstance(summary["relation_counts"], list) or [
        item.get("relation_kind") if isinstance(item, dict) else None
        for item in summary["relation_counts"]
    ] != list(_PACKET_V3_RELATIONS):
        return "packet schema 3 relation counts are incomplete"
    if any(
        set(item) != {"relation_kind", "count"}
        or isinstance(item["count"], bool)
        or not isinstance(item["count"], int)
        or item["count"] < 0
        for item in summary["relation_counts"]
    ):
        return "packet schema 3 has invalid relation counts"

    expected_declared_counts = []
    for source_role in ("implementation", "test", "binding_test"):
        sources = [
            source
            for source in declared_sources.values()
            if source["source_role"] == source_role
        ]
        expected_declared_counts.append(
            {
                "source_role": source_role,
                "total": len(sources),
                "complete": sum(
                    source["reciprocity_state"] == "complete" for source in sources
                ),
                "one_sided": sum(
                    source["reciprocity_state"] == "one_sided" for source in sources
                ),
            }
        )
    if summary["declared_counts"] != expected_declared_counts:
        return "packet schema 3 declared trace counts do not recompute"

    state = {
        "obligation_state_version": 1,
        "obligation_id": row["obligation_id"],
        "kind": row["kind"],
        "obligation_rung": readiness["obligation_rung"],
        "intent_state": readiness["intent_state"],
        "alignment_state": readiness["alignment_state"],
        "disposition": readiness["disposition"],
        "gate_state": readiness["gate_state"],
        "required_roles": required_roles,
        "declared_sources": sorted(
            declared_sources.values(),
            key=lambda source: (
                ("implementation", "test", "binding_test").index(source["source_role"]),
                source["receipt_hash"],
                tuple(
                    _PACKET_V3_RELATIONS.index(value)
                    for value in source["relation_kinds"]
                ),
            ),
        ),
    }
    expected_state_hash = hashlib.sha256(canonical_json_bytes(state)).hexdigest()
    if snapshot["obligation_state_hash"] != expected_state_hash:
        return "packet schema 3 obligation_state_hash does not recompute"

    expected_regions = [
        {
            "role": "requirement",
            "path": requirement["path"],
            "start_line": requirement["start_line"],
            "end_line": requirement["end_line"],
        },
        *(
            {
                "role": item["role"],
                "path": item["path"],
                "start_line": item["start_line"],
                "end_line": item["end_line"],
            }
            for item in declared
            if item["snippet"].strip()
        ),
        *(
            {
                "role": "counterevidence",
                "path": item["path"],
                "start_line": item["start_line"],
                "end_line": item["end_line"],
            }
            for item in counter
            if item["snippet"].strip()
        ),
    ]
    expected_regions.sort(
        key=lambda item: (
            _PACKET_V3_ROLE_ORDER[item["role"]],
            item["path"],
            item["start_line"],
            item["end_line"],
        )
    )
    if row.get("evidence_regions") != expected_regions:
        return "packet schema 3 evidence_regions do not recompute"
    if _packet_v3_has_contained_regions(expected_regions):
        return "packet schema 3 evidence regions were not maximally merged"
    if not isinstance(row.get("issues"), list) or any(
        _semantic_issue_error(
            issue,
            invariant_id=None
            if row["kind"] == "section"
            else str(requirement["identity"]),
        )
        is not None
        for issue in row["issues"]
    ):
        return "packet schema 3 issues are invalid"
    if row["kind"] == "section" and any(
        issue.get("section_id") != requirement["identity"] for issue in row["issues"]
    ):
        return "packet schema 3 section issue attribution is invalid"
    warnings = row.get("packet_warnings")
    if warnings != []:
        return "packet schema 3 packet_warnings must be exactly empty"
    try:
        expected_hash = semantic_packet_hash(row)
    except (KeyError, TypeError, ValueError):
        return "packet schema 3 projection is invalid"
    if row["packet_hash"] != expected_hash:
        return "packet schema 3 packet_hash does not recompute"
    return None


def _suppression_rule_path(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    return (
        not value.startswith(("/", "./"))
        and "\\" not in value
        and "//" not in value
        and all(part not in {"", ".", ".."} for part in value.split("/"))
        and all(ord(character) >= 32 and ord(character) != 127 for character in value)
    )


def _packet_v4_issue_key(item: dict[str, Any]) -> tuple[object, ...]:
    severity_order = {"error": 0, "warning": 1, "info": 2}
    return (
        severity_order[str(item["default_severity"])],
        item["path"],
        item["line"] or 0,
        item["code"],
        item["message"],
        canonical_json_bytes(item),
    )


def _packet_v4_shape_error(row: dict[str, Any]) -> str | None:
    """Return a schema-4 suppression packet violation, or ``None``."""

    if set(row) != _PACKET_V4_FIELDS or row.get("schema_version") != 4:
        return "packet schema 4 does not match its closed top-level shape"
    packet_id = row.get("packet_id")
    if (
        row.get("kind") != "suppression"
        or not isinstance(packet_id, str)
        or not packet_id.startswith("suppression::")
        or row.get("obligation_id") != packet_id
        or not is_sha256_hex(row.get("packet_hash"))
    ):
        return "packet schema 4 has invalid identity fields"
    reference = packet_id.removeprefix("suppression::")
    if not is_valid_suppression_reference(reference):
        return "packet schema 4 has an invalid suppression reference"
    declaration_path, _, declaration_id = reference.rpartition("#")

    snapshot = row.get("source_snapshot")
    if (
        not isinstance(snapshot, dict)
        or set(snapshot)
        != {
            "snapshot_hash",
            "obligation_state_hash",
            "derivation_config_hash",
        }
        or not all(is_sha256_hex(value) for value in snapshot.values())
    ):
        return "packet schema 4 has an invalid source snapshot"
    readiness = row.get("readiness")
    if (
        not isinstance(readiness, dict)
        or set(readiness)
        != {
            "intent_state",
            "alignment_state",
            "disposition",
            "obligation_rung",
            "gate_state",
            "required_roles",
        }
        or readiness
        != {
            "intent_state": "identified",
            "alignment_state": "complete",
            "disposition": "evaluate",
            "obligation_rung": "active",
            "gate_state": "executable",
            "required_roles": [],
        }
    ):
        return "packet schema 4 must describe one executable suppression"

    requirement = row.get("requirement")
    if (
        not isinstance(requirement, dict)
        or set(requirement)
        != {"role", "path", "identity", "title", "start_line", "end_line", "text"}
        or requirement.get("role") != "requirement"
        or requirement.get("path") != declaration_path
        or requirement.get("identity") != declaration_id
        or not isinstance(requirement.get("title"), str)
        or not requirement["title"].strip()
        or not _packet_v3_span(requirement, "text")
        or not requirement["text"].strip()
    ):
        return "packet schema 4 has an invalid requirement"

    rules = row.get("suppression_rules")
    if not isinstance(rules, list) or not rules:
        return "packet schema 4 suppression_rules must be nonempty"
    rule_bytes: list[bytes] = []
    for rule in rules:
        if (
            not isinstance(rule, dict)
            or set(rule)
            != {
                "mechanism",
                "provenance",
                "path",
                "sections",
                "codes",
                "declaration",
                "origin",
            }
            or rule.get("mechanism") not in {"ignore", "meta"}
            or rule.get("provenance")
            not in {
                "meta",
                "config_file",
                "config_section",
                "inline_spec",
                "inline_code",
            }
            or not _suppression_rule_path(rule.get("path"))
            or rule.get("declaration") != reference
        ):
            return "packet schema 4 has an invalid suppression rule"
        sections = rule.get("sections")
        codes = rule.get("codes")
        if (
            not isinstance(sections, list)
            or any(
                not isinstance(value, str) or not is_valid_section_id(value)
                for value in sections
            )
            or sections != sorted(set(sections))
            or not isinstance(codes, list)
            or any(not isinstance(value, str) or not value.strip() for value in codes)
            or codes != sorted(set(codes))
            or (rule["mechanism"] == "meta" and (sections or codes))
            or (rule["mechanism"] == "ignore" and not codes)
            or (rule["provenance"] == "meta") != (rule["mechanism"] == "meta")
        ):
            return "packet schema 4 has invalid normalized suppression scope"
        origin = rule.get("origin")
        if (
            not isinstance(origin, dict)
            or set(origin) != {"source", "position", "line"}
            or not isinstance(origin.get("source"), str)
            or not origin["source"].strip()
            or any(
                ord(character) < 32 or ord(character) == 127
                for character in origin["source"]
            )
            or (origin["position"] is None) == (origin["line"] is None)
            or (
                origin["position"] is not None
                and (
                    isinstance(origin["position"], bool)
                    or not isinstance(origin["position"], int)
                    or origin["position"] < 0
                )
            )
            or (
                origin["line"] is not None
                and (
                    isinstance(origin["line"], bool)
                    or not isinstance(origin["line"], int)
                    or origin["line"] < 1
                )
            )
        ):
            return "packet schema 4 has an invalid suppression origin"
        rule_bytes.append(canonical_json_bytes(rule))
    if rule_bytes != sorted(set(rule_bytes)):
        return "packet schema 4 suppression_rules are not canonical unique"

    issues = row.get("issues")
    if (
        not isinstance(issues, list)
        or not issues
        or any(
            not isinstance(issue, dict)
            or set(issue) != set(ISSUE_FIELDS)
            or not _is_issue_record(
                {**issue, "severity": issue.get("default_severity")},
                require_invariant_locator=True,
            )
            for issue in issues
        )
    ):
        return "packet schema 4 issues are invalid"
    issue_keys = [_packet_v4_issue_key(issue) for issue in issues]
    if issue_keys != sorted(issue_keys):
        return "packet schema 4 issues are not in canonical order"

    counter = row.get("counterevidence")
    if not isinstance(counter, list):
        return "packet schema 4 counterevidence must be an array"
    counter_keys: list[tuple[str, int]] = []
    covered_indexes: list[int] = []
    for region in counter:
        if (
            not isinstance(region, dict)
            or set(region)
            != {
                "role",
                "path",
                "start_line",
                "end_line",
                "snippet",
                "issue_indexes",
            }
            or region.get("role") != "counterevidence"
            or not _is_path_locator(region.get("path"))
            or isinstance(region.get("start_line"), bool)
            or not isinstance(region.get("start_line"), int)
            or region["start_line"] < 1
            or region.get("end_line") != region["start_line"]
            or not isinstance(region.get("snippet"), str)
            or "\n" in region["snippet"]
            or not isinstance(region.get("issue_indexes"), list)
            or not region["issue_indexes"]
            or any(
                isinstance(index, bool)
                or not isinstance(index, int)
                or index < 0
                or index >= len(issues)
                for index in region["issue_indexes"]
            )
            or region["issue_indexes"] != sorted(set(region["issue_indexes"]))
        ):
            return "packet schema 4 has an invalid counterevidence region"
        if any(
            issues[index]["path"] != region["path"]
            or issues[index]["line"] != region["start_line"]
            for index in region["issue_indexes"]
        ):
            return "packet schema 4 counterevidence issue indexes do not match"
        counter_keys.append((region["path"], region["start_line"]))
        covered_indexes.extend(region["issue_indexes"])
    if counter_keys != sorted(set(counter_keys)):
        return "packet schema 4 counterevidence is not canonical unique"
    expected_covered = [
        index
        for index, issue in enumerate(issues)
        if isinstance(issue["path"], str)
        and bool(issue["path"])
        and isinstance(issue["line"], int)
    ]
    if sorted(covered_indexes) != expected_covered:
        return "packet schema 4 counterevidence does not cover issue locators"

    expected_regions = [
        {
            "role": "requirement",
            "path": requirement["path"],
            "start_line": requirement["start_line"],
            "end_line": requirement["end_line"],
        },
        *(
            {
                "role": "counterevidence",
                "path": region["path"],
                "start_line": region["start_line"],
                "end_line": region["end_line"],
            }
            for region in counter
        ),
    ]
    if row.get("evidence_regions") != expected_regions:
        return "packet schema 4 evidence_regions do not recompute"
    state = {
        "obligation_state_version": 1,
        "obligation_id": row["obligation_id"],
        "kind": "suppression",
        "obligation_rung": "active",
        "intent_state": "identified",
        "alignment_state": "complete",
        "disposition": "evaluate",
        "gate_state": "executable",
        "required_roles": [],
        "declared_sources": [],
    }
    if (
        snapshot["obligation_state_hash"]
        != hashlib.sha256(canonical_json_bytes(state)).hexdigest()
    ):
        return "packet schema 4 obligation_state_hash does not recompute"
    if row.get("packet_warnings") != []:
        return "packet schema 4 packet_warnings must be exactly empty"
    try:
        expected_hash = semantic_packet_hash(row)
    except (KeyError, TypeError, ValueError):
        return "packet schema 4 projection is invalid"
    if row["packet_hash"] != expected_hash:
        return "packet schema 4 packet_hash does not recompute"
    return None


def load_packets_bytes(
    content: bytes,
    *,
    source: Path | str = "<packet bytes>",
) -> tuple[ValidatedSemanticPacket, ...]:
    """Load packets from the exact bytes whose digest the caller accepted."""

    if not isinstance(content, bytes):
        raise ValueError(f"{source}: packet input must be bytes")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{source}: packet input is not valid UTF-8: {exc}") from None
    return _load_packets_text(text, source=source)


def load_packets(path: Path) -> tuple[ValidatedSemanticPacket, ...]:
    """Load and validate packet JSONL ([SC-6]).

    A malformed packets file is an invocation error ([SC-5] exit 2), never
    a model-analysis result: invalid packets must be rejected here, before
    any of them can reach analyze_packets.
    """

    return load_packets_bytes(path.read_bytes(), source=path)


def _load_packets_text(
    text: str,
    *,
    source: Path | str,
) -> tuple[ValidatedSemanticPacket, ...]:
    packets: list[ValidatedSemanticPacket] = []
    for line_no, line in enumerate(lf_split(text), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            msg = f"{source}:{line_no}: malformed packet JSONL: {exc}"
            raise ValueError(msg) from None
        if not isinstance(row, dict):
            msg = f"{source}:{line_no}: packet line is not a JSON object"
            raise ValueError(msg)
        versioned = "schema_version" in row
        if not versioned and "packet_hash" in row:
            marker_problem = "partial v2 packet markers require `schema_version = 2`"
            msg = f"{source}:{line_no}: malformed packet: {marker_problem}"
            raise ValueError(msg)
        kind = row.get("kind")
        problem: str | None
        cache_eligible = row.get("schema_version") in {3, 4}
        if versioned:
            if row.get("schema_version") == 3:
                problem = _packet_v3_shape_error(row)
            elif row.get("schema_version") == 4:
                problem = _packet_v4_shape_error(row)
            elif row.get("schema_version") != 2:
                problem = (
                    "invalid `schema_version`; expected 3 or 4 "
                    "(or 2 for migration diagnostics)"
                )
            elif kind == "section":
                problem = _v2_section_packet_shape_error(row)
            elif kind == "invariant":
                problem = _v2_invariant_packet_shape_error(row)
            else:
                problem = "invalid `kind`; expected `section` or `invariant`"
        elif "kind" not in row:
            packet_id = row.get("packet_id")
            if isinstance(packet_id, str) and packet_id.startswith("invariant::"):
                problem = "missing `kind` for invariant packet identity"
            else:
                problem = _section_packet_shape_error(row, legacy=True)
        elif kind == "section":
            problem = _section_packet_shape_error(row)
        elif kind == "invariant":
            problem = _invariant_packet_shape_error(row)
        else:
            problem = "invalid `kind`; expected `section` or `invariant`"
        if problem is not None:
            msg = f"{source}:{line_no}: malformed packet: {problem}"
            raise ValueError(msg)
        normalized = row if versioned else _normalize_legacy_packet(row)
        packets.append(
            ValidatedSemanticPacket.from_row(normalized, cache_eligible=cache_eligible)
        )
    return tuple(packets)


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
