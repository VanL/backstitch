"""Core value types for trace graphs, issues, and reports.

Spec: docs/specs/02-backstitch-core.md [SC-2], [SC-4], [SC-6], [SC-11]
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any, Literal

Severity = Literal["error", "warning", "info"]

SectionKind = Literal["heading", "invariant", "bullet"]

MappingKind = Literal["path", "path_symbol", "symbol"]

EdgeKind = Literal["mapping", "backlink"]

# "asserted": a docstring `Spec:` marker line -- claims a specific trace
# edge. "docstring": docstring prose. "comment": code comment. Ambiguity is
# an error only in asserted context ([SC-11]).
RefContext = Literal["asserted", "docstring", "comment"]

# Canonical inventory of deterministic issue codes -- exactly the [SC-11]
# table. Configuration validates suppression lists against this set, and
# tests/test_models.py parses the spec table to keep the two in lockstep.
ISSUE_CODES = frozenset(
    {
        "CODE_BACKLINK_RECIPROCAL_MISSING",
        "CODE_REF_BARE_UNRESOLVED",
        "CODE_REF_BROAD",
        "CODE_REF_EXPLORATORY_SPEC",
        "CODE_REF_PLANNED_SPEC",
        "CODE_REF_UNMAPPED_FROM_SPEC",
        "FILE_UNREADABLE",
        "MAPPING_BLOCK_OWNERLESS",
        "MAPPING_PATH_INEXACT",
        "MAPPING_PATH_MISSING",
        "MAPPING_SYMBOL_MISSING",
        "MAPPING_SYMBOL_UNRESOLVED",
        "PYTHON_SYNTAX_ERROR",
        "REF_RANGE_UNSUPPORTED",
        "SCAN_ROOT_MISSING",
        "SPEC_ANCHOR_MISSING",
        "SPEC_FILE_MISSING",
        "SPEC_MAPPING_RECIPROCAL_MISSING",
        "SPEC_SECTION_AMBIGUOUS",
        "SPEC_SECTION_DUPLICATE",
        "SPEC_SECTION_MISSING",
        "SPEC_SECTION_UNMAPPED",
        "TARGET_PATH_AMBIGUOUS",
    }
)

# Codes that are ALWAYS error-severity per [SC-11]. Context-dependent codes
# (SPEC_SECTION_AMBIGUOUS, MAPPING_PATH_MISSING) are deliberately excluded:
# their severity varies per instance, so non-suppressibility decisions must
# gate on ``issue.severity == "error"``, never on membership in this set.
ERROR_SEVERITY_CODES = frozenset(
    {
        "FILE_UNREADABLE",
        "MAPPING_SYMBOL_MISSING",
        "REF_RANGE_UNSUPPORTED",
        "SCAN_ROOT_MISSING",
        "SPEC_ANCHOR_MISSING",
        "SPEC_FILE_MISSING",
        "SPEC_SECTION_MISSING",
        "TARGET_PATH_AMBIGUOUS",
    }
)


@dataclass(frozen=True, slots=True)
class SpecSection:
    """A spec section definition: an ID-bearing heading or invariant bullet."""

    path: str
    section_id: str
    title: str
    line: int
    anchor: str | None
    kind: SectionKind


@dataclass(frozen=True, slots=True)
class SpecMapping:
    """A spec-authored implementation mapping token for one section."""

    spec_path: str
    section_id: str
    line: int
    target: str
    kind: MappingKind
    target_path: str | None
    target_symbol: str | None


@dataclass(frozen=True, slots=True)
class CodeRef:
    """A spec reference found in code (docstring or comment).

    ``section_ids`` holds explicitly listed IDs (single or comma list).
    ``ranges`` holds unexpanded ``(start, end)`` range pairs; the resolver
    expands them only when every intermediate section exists [SC-4].
    A document-only reference has a ``spec_path`` but no IDs, ranges, or
    anchor. ``ref_context`` records provenance at parse time -- only a
    docstring ``Spec:`` marker line is an asserted backlink; ordinary
    docstring prose and comments are weak/prose context -- so the resolver
    can apply [SC-11] context-dependent severities without re-inspecting
    raw text.
    """

    path: str
    owner_symbol: str
    line: int
    raw: str
    spec_path: str | None
    section_ids: tuple[str, ...]
    anchor: str | None
    ranges: tuple[tuple[str, str], ...]
    ref_context: RefContext


@dataclass(frozen=True, slots=True)
class Edge:
    """A resolved trace edge between a spec section and a code owner."""

    kind: EdgeKind
    spec_path: str
    section_id: str
    code_path: str
    code_symbol: str | None
    line: int


@dataclass(frozen=True, slots=True)
class Issue:
    """A deterministic finding with a stable code and location metadata."""

    code: str
    severity: Severity
    path: str
    line: int | None
    message: str
    section_id: str | None = None
    symbol: str | None = None


@dataclass(frozen=True, slots=True)
class Report:
    """Deterministic trace report; ``to_dict`` is the JSON contract [SC-6]."""

    profile: str
    repo_root: str
    spec_sections: tuple[SpecSection, ...]
    code_refs: tuple[CodeRef, ...]
    spec_mappings: tuple[SpecMapping, ...]
    edges: tuple[Edge, ...]
    issues: tuple[Issue, ...]

    def summary(self) -> dict[str, int]:
        return {
            "spec_sections": len(self.spec_sections),
            "code_refs": len(self.code_refs),
            "spec_mappings": len(self.spec_mappings),
            "errors": sum(1 for i in self.issues if i.severity == "error"),
            "warnings": sum(1 for i in self.issues if i.severity == "warning"),
            "infos": sum(1 for i in self.issues if i.severity == "info"),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "repo_root": self.repo_root,
            "summary": self.summary(),
            "spec_sections": [dataclasses.asdict(s) for s in self.spec_sections],
            "code_refs": [dataclasses.asdict(r) for r in self.code_refs],
            "spec_mappings": [dataclasses.asdict(m) for m in self.spec_mappings],
            "edges": [dataclasses.asdict(e) for e in self.edges],
            "issues": [dataclasses.asdict(i) for i in self.issues],
        }
