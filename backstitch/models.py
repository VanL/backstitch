"""Core value types for trace graphs, issues, and reports.

Spec: docs/specs/02-backstitch-core.md [SC-2], [SC-4], [SC-6], [SC-11]
Spec: docs/specs/05-backstitch-invariants.md [INV-1], [INV-2]
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any, Literal

from backstitch.diagnostics import (
    always_error_codes,
    default_level_for,
    implemented_codes,
    short_code_for,
)

Severity = Literal["error", "warning", "info"]
InvariantTier = Literal["required", "draft"]
InvariantDeclarationKind = Literal["code", "spec"]

SectionKind = Literal["heading", "invariant", "bullet"]

MappingKind = Literal["path", "path_symbol", "symbol"]

EdgeKind = Literal["mapping", "backlink"]

# "asserted": a docstring `Spec:` marker line -- claims a specific trace
# edge. "docstring": docstring prose. "comment": code comment. Ambiguity is
# an error only in asserted context ([SC-11]).
RefContext = Literal["asserted", "docstring", "comment"]

# Compatibility inventories derived from the packaged diagnostic registry
# ([SC-11], [SC-15]). The TOML registry is the source of truth.
ISSUE_CODES = implemented_codes()
ERROR_SEVERITY_CODES = always_error_codes()


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
class InvariantDeclaration:
    """A first-class invariant declaration owned by code or a spec section."""

    invariant_id: str
    statement: str
    tier: InvariantTier
    declaration_kind: InvariantDeclarationKind
    path: str
    line: int
    owner_symbol: str | None
    section_id: str | None


@dataclass(frozen=True, slots=True)
class InvariantBind:
    """One concrete test definition claiming to bind an invariant."""

    invariant_id: str
    test_path: str
    test_symbol: str
    marker_line: int
    start_line: int
    end_line: int


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
    short_code: str | None = None
    context: str | None = None
    default_severity: Severity | None = None
    invariant_id: str | None = None

    def __post_init__(self) -> None:
        if self.short_code is None:
            object.__setattr__(self, "short_code", short_code_for(self.code))
        if self.default_severity is None:
            object.__setattr__(
                self,
                "default_severity",
                default_level_for(self.code, self.context),
            )


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
    invariants: tuple[InvariantDeclaration, ...] = ()
    binds: tuple[InvariantBind, ...] = ()

    def summary(self) -> dict[str, int]:
        return {
            "spec_sections": len(self.spec_sections),
            "code_refs": len(self.code_refs),
            "spec_mappings": len(self.spec_mappings),
            "invariants": len(self.invariants),
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
            "invariants": [dataclasses.asdict(item) for item in self.invariants],
            "binds": [dataclasses.asdict(item) for item in self.binds],
            "issues": [dataclasses.asdict(i) for i in self.issues],
        }
