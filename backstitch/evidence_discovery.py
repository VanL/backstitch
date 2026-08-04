"""Deterministic, snapshot-only evidence candidate discovery.

Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-4.1], [EVC-4.2],
[EVC-7], [EVC-7.1], [EVC-7.2], [EVC-8.4]

The public entry point consumes an accepted :class:`RepositorySnapshot` and
the raw resolver report from that same view.  It never opens a repository
path, imports target code, or calls a model/provider.
"""

from __future__ import annotations

import hashlib
import heapq
import keyword
import math
import unicodedata
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import PurePosixPath
from typing import Literal

from backstitch.canonical import canonical_json_bytes, lf_slice
from backstitch.code_parser import (
    ParsedModule,
    StaticBinding,
    StaticImportAlias,
    StaticReference,
    parse_python_source,
)
from backstitch.config import ProfileConfig
from backstitch.grammar import candidate_ref
from backstitch.models import (
    CodeRef,
    Edge,
    InvariantBind,
    InvariantDeclaration,
    Issue,
    Report,
    SpecMapping,
)
from backstitch.obligations import ObligationRecord, resolve_evidence_atom
from backstitch.operation_progress import DeadlinePhase, OperationProgress
from backstitch.python_refs import python_definition_inventory_bytes
from backstitch.repository_snapshot import RepositorySnapshot
from backstitch.settings import ObligationSettings

CandidateKind = Literal[
    "implementation_definition",
    "test_definition",
    "static_reference",
    "unresolved_reference",
    "report_issue",
]
TraceState = Literal["declared", "partially_declared", "untraced", "conflicted"]
DiscoveryBasis = Literal[
    "declared_relation",
    "invariant_relation",
    "resolver_issue",
    "lexical_match",
    "static_neighbor",
    "ambiguous_relation",
]
EvidenceRole = Literal["implementation", "test", "binding_test"]

_CANDIDATE_KIND_ORDER: tuple[CandidateKind, ...] = (
    "implementation_definition",
    "test_definition",
    "static_reference",
    "unresolved_reference",
    "report_issue",
)
_TRACE_STATE_ORDER: tuple[TraceState, ...] = (
    "conflicted",
    "partially_declared",
    "untraced",
    "declared",
)
_BASIS_ORDER: tuple[DiscoveryBasis, ...] = (
    "declared_relation",
    "invariant_relation",
    "resolver_issue",
    "lexical_match",
    "static_neighbor",
    "ambiguous_relation",
)
_GUIDANCE_ORDER = (
    "ADD_RECIPROCAL_MAPPING",
    "ADD_RECIPROCAL_BACKLINK",
    "ADD_INVARIANT_BIND",
    "ADD_BINDING_TEST",
)
_STOP_TOKENS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "from",
        "this",
        "that",
        "must",
        "should",
        "will",
        "not",
        "are",
        "was",
        "into",
        "when",
        "where",
    }
)
_CONFLICT_WORDS = ("AMBIGUOUS", "DUPLICATE", "MALFORMED", "CONFLICT")
_REVIEW_WARNING = "Advice is not evidence; review the source relation before editing."


def _nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _python_identifier(value: str) -> str:
    """Return Python's runtime identifier key without changing source locators."""

    return unicodedata.normalize("NFKC", value)


def _python_dotted_identifier(value: str | None) -> str | None:
    if value is None:
        return None
    return ".".join(_python_identifier(part) for part in value.split("."))


@dataclass(frozen=True, slots=True)
class SourceReceipt:
    receipt_version: int
    path: str
    structural_locator: str
    start_line: int
    end_line: int
    raw_sha256: str

    def to_row(self) -> dict[str, object]:
        return {
            "receipt_version": self.receipt_version,
            "path": self.path,
            "structural_locator": self.structural_locator,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "raw_sha256": self.raw_sha256,
        }


@dataclass(frozen=True, slots=True)
class CandidateRelation:
    relation_kind: str
    source_candidate_id: str | None
    target_candidate_id: str | None
    source_locator: str | None
    target_locator: str | None

    def to_row(self) -> dict[str, object]:
        return {
            "relation_kind": self.relation_kind,
            "source_candidate_id": self.source_candidate_id,
            "target_candidate_id": self.target_candidate_id,
            "source_locator": self.source_locator,
            "target_locator": self.target_locator,
        }


@dataclass(frozen=True, slots=True)
class TraceAdvice:
    guidance_code: str
    target_id: str
    evidence_role: EvidenceRole
    supported_forms: tuple[str, ...]
    review_warning: str = _REVIEW_WARNING

    def to_row(self) -> dict[str, object]:
        return {
            "guidance_code": self.guidance_code,
            "target_id": self.target_id,
            "evidence_role": self.evidence_role,
            "supported_forms": list(self.supported_forms),
            "review_warning": self.review_warning,
        }


@dataclass(frozen=True, slots=True)
class EvidenceCandidate:
    candidate_id: str
    candidate_kind: CandidateKind
    path: str
    owner: str | None
    start_line: int
    end_line: int
    structural_locator: str
    receipt: SourceReceipt
    discovery_bases: tuple[DiscoveryBasis, ...]
    lexical_score: tuple[int, int]
    static_relations: tuple[CandidateRelation, ...]
    declared_relations: tuple[CandidateRelation, ...]
    trace_state: TraceState
    suggested_trace_edits: tuple[TraceAdvice, ...]
    _raw_span: bytes = field(repr=False, compare=False)

    def to_row(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "candidate_kind": self.candidate_kind,
            "path": self.path,
            "owner": self.owner,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "structural_locator": self.structural_locator,
            "receipt": self.receipt.to_row(),
            "discovery_bases": list(self.discovery_bases),
            "lexical_score": {
                "shared_token_count": self.lexical_score[0],
                "shared_token_byte_count": self.lexical_score[1],
            },
            "static_relations": [item.to_row() for item in self.static_relations],
            "declared_relations": [item.to_row() for item in self.declared_relations],
            "trace_state": self.trace_state,
            "suggested_trace_edits": [
                item.to_row() for item in self.suggested_trace_edits
            ],
        }


@dataclass(frozen=True, slots=True)
class CandidateSource:
    receipt: SourceReceipt
    text: str
    text_sha256: str

    def to_row(self) -> dict[str, object]:
        return {
            "receipt": self.receipt.to_row(),
            "text": self.text,
            "text_sha256": self.text_sha256,
        }


@dataclass(frozen=True, slots=True)
class CandidateNeighbor:
    candidate_id: str
    relation_kind: str
    direction: Literal["incoming", "outgoing"]

    def to_row(self) -> dict[str, str]:
        return {
            "candidate_id": self.candidate_id,
            "relation_kind": self.relation_kind,
            "direction": self.direction,
        }


class EvidenceDiscoveryError(Exception):
    """One closed obligation-read operation problem; never a partial result."""

    def __init__(self, code: str, message: str, details: Mapping[str, object]) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details)


def _budget_error(budget: str, limit: int, observed: int) -> EvidenceDiscoveryError:
    return EvidenceDiscoveryError(
        "BUDGET_EXHAUSTED",
        f"discovery exceeded {budget}",
        {"budget": budget, "limit": limit, "observed": observed},
    )


@dataclass(slots=True)
class _WorkBudget:
    limit: int
    progress: OperationProgress | None = None
    emit_progress: bool = True
    used: int = 0
    phase: DeadlinePhase = "catalog"
    _checkpoint_countdown: int = 0

    def enter(
        self,
        phase: DeadlinePhase,
        *,
        current_identity: str,
        total_work_units: int | None = None,
    ) -> None:
        """Name the next work phase without changing deterministic accounting."""

        self.phase = phase
        self._checkpoint_countdown = 63
        if self.progress is not None:
            if self.emit_progress:
                self.progress.advance(
                    phase,
                    completed_work_units=self.used,
                    total_work_units=total_work_units,
                    current_identity=current_identity,
                )
            else:
                self.progress.checkpoint(phase)

    def checkpoint(self) -> None:
        """Sample the deadline at a bounded interval without charging work."""

        if self.progress is None:
            return
        if self._checkpoint_countdown:
            self._checkpoint_countdown -= 1
            return
        self.progress.checkpoint(self.phase)
        self._checkpoint_countdown = 63

    def charge(self, units: int = 1) -> None:
        if units <= 0:
            return
        observed = self.used + units
        if observed > self.limit:
            raise _budget_error("work_units", self.limit, observed)
        self.used = observed
        self.checkpoint()


def _is_under(path: str, roots: Sequence[str]) -> bool:
    pure = PurePosixPath(path)
    return any(pure.is_relative_to(PurePosixPath(root)) for root in roots)


def _receipt(
    path: str,
    locator: str,
    start_line: int,
    end_line: int,
    raw: bytes,
    work: _WorkBudget,
) -> SourceReceipt:
    span = lf_slice(raw, start_line, end_line, policy="clamped")
    work.charge(math.ceil(len(span) / 4096))
    return SourceReceipt(
        receipt_version=1,
        path=path,
        structural_locator=locator,
        start_line=start_line,
        end_line=end_line,
        raw_sha256=hashlib.sha256(span).hexdigest(),
    )


def _candidate_id(kind: CandidateKind, path: str, locator: str) -> str:
    preimage = {
        "candidate_identity_version": 1,
        "candidate_kind": kind,
        "path": _nfc(path),
        "structural_locator": _nfc(locator),
    }
    digest = hashlib.sha256(canonical_json_bytes(preimage)).hexdigest()
    return candidate_ref(digest)


def _relation_order(item: CandidateRelation) -> tuple[str, str, str, str, str]:
    return (
        item.relation_kind,
        item.source_locator or "",
        item.target_locator or "",
        item.source_candidate_id or "",
        item.target_candidate_id or "",
    )


def _advice_order(item: TraceAdvice) -> tuple[int, str, str, tuple[str, ...]]:
    return (
        _GUIDANCE_ORDER.index(item.guidance_code),
        item.target_id,
        item.evidence_role,
        item.supported_forms,
    )


def candidate_order(item: EvidenceCandidate) -> tuple[object, ...]:
    """The exact [EVC-7] public candidate ordering tuple."""

    return (
        _TRACE_STATE_ORDER.index(item.trace_state),
        _CANDIDATE_KIND_ORDER.index(item.candidate_kind),
        -item.lexical_score[0],
        -item.lexical_score[1],
        item.path,
        item.start_line,
        item.structural_locator,
        item.candidate_id,
    )


def _tokens(value: str) -> frozenset[str]:
    normalized = unicodedata.normalize("NFC", value)
    words: list[str] = []
    current: list[str] = []
    previous: str | None = None
    for char in normalized:
        ascii_alnum = char.isascii() and char.isalnum()
        if not ascii_alnum:
            if current:
                words.append("".join(current).lower())
                current = []
            previous = None
            continue
        boundary = bool(
            current
            and previous is not None
            and (
                (previous.islower() and char.isupper())
                or (previous.isalpha() and char.isdigit())
                or (previous.isdigit() and char.isalpha())
            )
        )
        if boundary:
            words.append("".join(current).lower())
            current = []
        current.append(char)
        previous = char
    if current:
        words.append("".join(current).lower())
    return frozenset(
        word
        for word in words
        if len(word.encode("ascii")) >= 3 and word not in _STOP_TOKENS
    )


@dataclass(slots=True)
class _Node:
    candidate_id: str
    candidate_kind: CandidateKind
    path: str
    owner: str | None
    symbol: str | None
    module_name: str | None
    role: EvidenceRole
    start_line: int
    end_line: int
    node_line: int
    structural_locator: str
    receipt: SourceReceipt
    owner_candidate_id: str | None = None
    ambiguous_targets: tuple[str, ...] = ()
    closure_neighbors: set[str] = field(default_factory=set)
    trace_flags: set[str] = field(default_factory=set)
    bases: set[DiscoveryBasis] = field(default_factory=set)
    lexical_score: tuple[int, int] = (0, 0)
    lexical_tokens: frozenset[str] | None = None


@dataclass(frozen=True, slots=True)
class PreparedEvidenceCatalog:
    """Snapshot-bound parser catalog reusable across isolated obligations."""

    snapshot_hash: str
    profile: ProfileConfig
    settings: ObligationSettings
    base_work_units: int
    _nodes: tuple[_Node, ...] = field(repr=False)
    _static_edges: tuple[tuple[str, str, str], ...] = field(repr=False)


@dataclass(frozen=True, slots=True)
class _Definition:
    path: str
    module_name: str | None
    qualname: str
    name: str
    node_kind: str
    parent_qualname: str | None
    lineno: int
    source_order: int
    scope_start_byte: int
    parent_scope_start_byte: int | None
    candidate_id: str
    conditional: bool


@dataclass(frozen=True, slots=True)
class _Reference:
    path: str
    owner_qualname: str | None
    owner_candidate_id: str
    owner_locator: str
    fact: StaticReference
    locator: str


@dataclass(frozen=True, slots=True)
class _Binding:
    source_order: int
    kind: Literal["import", "definition", "shadow"]
    target_ids: tuple[str, ...] = ()
    module_name: str | None = None
    plausible_local: bool = False
    ambiguous_ids: tuple[str, ...] = ()
    conditional: bool = False


def _module_candidates(
    path: str,
    profile: ProfileConfig,
    snapshot: RepositorySnapshot,
) -> tuple[str, ...]:
    pure = PurePosixPath(path)
    names: set[str] = set()
    for raw_root in (*profile.code_roots, *profile.test_roots):
        root = PurePosixPath(raw_root)
        if not pure.is_relative_to(root):
            continue
        relative = pure.relative_to(root)
        parts = list(relative.with_suffix("").parts)
        if parts and parts[-1] == "__init__":
            parts.pop()
        if not parts:
            continue
        if snapshot.path_exists((root / "__init__.py").as_posix()) and root.name:
            parts.insert(0, root.name)
        if any(not part.isidentifier() or keyword.iskeyword(part) for part in parts):
            continue
        names.add(_nfc(".".join(parts)))
    return tuple(sorted(names))


def resolved_python_module_names(
    paths: Sequence[str],
    profile: ProfileConfig,
    snapshot: RepositorySnapshot,
) -> dict[str, str | None]:
    """Resolve the one closed module identity for each captured Python path."""

    roots = tuple(dict.fromkeys((*profile.code_roots, *profile.test_roots)))
    derived_by_path: dict[str, tuple[str, ...]] = {}
    for path in paths:
        pure = PurePosixPath(path)
        matching = [
            PurePosixPath(root)
            for root in roots
            if pure.is_relative_to(PurePosixPath(root))
        ]
        if not matching:
            derived_by_path[path] = ()
            continue
        longest = max(len(root.parts) for root in matching)
        owners = [root for root in matching if len(root.parts) == longest]
        if len(owners) != 1:
            derived_by_path[path] = ()
            continue
        owner_profile = replace(
            profile,
            code_roots=(owners[0].as_posix(),),
            test_roots=(),
        )
        derived_by_path[path] = _module_candidates(
            path,
            owner_profile,
            snapshot,
        )
    paths_by_name: dict[str, list[str]] = defaultdict(list)
    for path, names in derived_by_path.items():
        for name in names:
            paths_by_name[name].append(path)
    return {
        path: (
            names[0] if len(names) == 1 and len(paths_by_name[names[0]]) == 1 else None
        )
        for path, names in derived_by_path.items()
    }


def _source_rows(
    snapshot: RepositorySnapshot,
    profile: ProfileConfig,
    settings: ObligationSettings,
    work: _WorkBudget,
) -> tuple[tuple[str, bytes, EvidenceRole], ...]:
    if len(snapshot.path_catalog) > settings.maximum_catalog_items:
        raise _budget_error(
            "catalog_items",
            settings.maximum_catalog_items,
            len(snapshot.path_catalog),
        )
    if snapshot.file_count > settings.maximum_snapshot_files:
        raise _budget_error(
            "snapshot_files",
            settings.maximum_snapshot_files,
            snapshot.file_count,
        )
    if snapshot.byte_count > settings.maximum_snapshot_bytes:
        raise _budget_error(
            "snapshot_bytes",
            settings.maximum_snapshot_bytes,
            snapshot.byte_count,
        )
    rows: list[tuple[str, bytes, EvidenceRole]] = []
    roots = tuple(dict.fromkeys((*profile.code_roots, *profile.test_roots)))
    for row in snapshot.files:
        work.checkpoint()
        if (
            row.raw_bytes is not None
            and len(row.raw_bytes) > settings.maximum_file_bytes
        ):
            raise _budget_error(
                "file_bytes",
                settings.maximum_file_bytes,
                len(row.raw_bytes),
            )
        if not row.path.endswith(".py") or not _is_under(row.path, roots):
            continue
        if row.raw_bytes is None:
            raise EvidenceDiscoveryError(
                "SOURCE_UNREADABLE",
                f"source is unreadable: {row.path}",
                {"path": row.path, "error_class": row.error_class},
            )
        role = resolve_evidence_atom(
            path=row.path,
            symbol=None,
            relation_kinds=("enclosing_definition",),
            reciprocity_state="one_sided",
            test_roots=profile.test_roots,
        )
        rows.append((row.path, row.raw_bytes, role.source_role))
    return tuple(rows)


def _validate_semantic_utf8(
    snapshot: RepositorySnapshot,
    profile: ProfileConfig,
    work: _WorkBudget,
) -> None:
    markdown_roots = (*profile.spec_roots, *profile.plan_roots)
    python_roots = (*profile.code_roots, *profile.test_roots)
    for row in snapshot.files:
        work.checkpoint()
        semantic = (
            row.path.endswith(".md") and _is_under(row.path, markdown_roots)
        ) or (row.path.endswith(".py") and _is_under(row.path, python_roots))
        if not semantic:
            continue
        if row.raw_bytes is None:
            raise EvidenceDiscoveryError(
                "SOURCE_UNREADABLE",
                f"semantic source is unreadable: {row.path}",
                {"path": row.path, "error_class": row.error_class},
            )
        try:
            row.raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            raise EvidenceDiscoveryError(
                "SOURCE_UNREADABLE",
                f"semantic source is not UTF-8: {row.path}",
                {"path": row.path, "error_class": "io"},
            ) from None


def _make_node(
    *,
    candidate_kind: CandidateKind,
    path: str,
    owner: str | None,
    symbol: str | None,
    module_name: str | None,
    role: EvidenceRole,
    start_line: int,
    end_line: int,
    node_line: int,
    locator: str,
    raw: bytes,
    work: _WorkBudget,
    owner_candidate_id: str | None = None,
) -> _Node:
    path = _nfc(path)
    locator = _nfc(locator)
    owner = _nfc(owner) if owner is not None else None
    symbol = _nfc(symbol) if symbol is not None else None
    module_name = _nfc(module_name) if module_name is not None else None
    work.charge()
    receipt = _receipt(path, locator, start_line, end_line, raw, work)
    return _Node(
        candidate_id=_candidate_id(candidate_kind, path, locator),
        candidate_kind=candidate_kind,
        path=path,
        owner=owner,
        symbol=symbol,
        module_name=module_name,
        role=role,
        start_line=start_line,
        end_line=end_line,
        node_line=node_line,
        structural_locator=locator,
        receipt=receipt,
        owner_candidate_id=owner_candidate_id,
    )


def _catalog_python(
    snapshot: RepositorySnapshot,
    profile: ProfileConfig,
    settings: ObligationSettings,
    work: _WorkBudget,
) -> tuple[
    dict[str, _Node],
    list[_Definition],
    dict[str, ParsedModule],
    dict[str, str | None],
    dict[str, bytes],
]:
    sources = _source_rows(snapshot, profile, settings, work)
    module_name_by_path = resolved_python_module_names(
        tuple(path for path, _, _ in sources), profile, snapshot
    )
    derived_by_path = {
        path: _module_candidates(path, profile, snapshot) for path, _, _ in sources
    }

    nodes: dict[str, _Node] = {}
    definitions: list[_Definition] = []
    parsed_by_path: dict[str, ParsedModule] = {}
    raw_by_path: dict[str, bytes] = {}
    candidate_by_scope: dict[tuple[str, int], str] = {}
    module_candidate_by_path: dict[str, str] = {}
    for path, raw, role in sources:
        work.checkpoint()
        raw_by_path[path] = raw
        module_name = module_name_by_path[path]
        try:
            parsed = parse_python_source(raw, include_static_facts=True)
        except UnicodeDecodeError:
            continue
        work.checkpoint()
        if not parsed.parse_ok:
            continue
        parsed_by_path[path] = parsed
        inventory = python_definition_inventory_bytes(
            raw,
            rel_path=path,
            module_name=module_name,
            parsed_module=parsed,
        )
        assert inventory is not None
        module_definition = inventory[0]
        module = _make_node(
            candidate_kind=(
                "test_definition" if role == "test" else "implementation_definition"
            ),
            path=path,
            owner=module_name,
            symbol=None,
            module_name=module_name,
            role=role,
            start_line=module_definition.start_line,
            end_line=module_definition.end_line,
            node_line=1,
            locator=module_definition.structural_locator,
            raw=raw,
            work=work,
        )
        nodes[module.candidate_id] = module
        module_candidate_id = module.candidate_id
        module_candidate_by_path[path] = module.candidate_id
        for parsed_definition, canonical_definition in zip(
            parsed.definitions,
            inventory[1:],
            strict=True,
        ):
            qualname = canonical_definition.qualname
            assert qualname is not None
            parent = (
                _nfc(parsed_definition.parent_qualname)
                if parsed_definition.parent_qualname is not None
                else None
            )
            kind = canonical_definition.kind
            locator = canonical_definition.structural_locator
            parent_id = (
                candidate_by_scope.get(
                    (path, parsed_definition.parent_scope_start_byte)
                )
                if parsed_definition.parent_scope_start_byte is not None
                else module_candidate_id
            )
            candidate = _make_node(
                candidate_kind=(
                    "test_definition" if role == "test" else "implementation_definition"
                ),
                path=path,
                owner=qualname,
                symbol=qualname,
                module_name=module_name,
                role=role,
                start_line=canonical_definition.attachment_line,
                end_line=canonical_definition.end_line,
                node_line=canonical_definition.start_line,
                locator=locator,
                raw=raw,
                work=work,
                owner_candidate_id=parent_id,
            )
            nodes[candidate.candidate_id] = candidate
            candidate_by_scope[(path, parsed_definition.scope_start_byte)] = (
                candidate.candidate_id
            )
            definitions.append(
                _Definition(
                    path=path,
                    module_name=module_name,
                    qualname=qualname,
                    name=_python_identifier(parsed_definition.name),
                    node_kind=kind,
                    parent_qualname=parent,
                    lineno=parsed_definition.start_line,
                    source_order=parsed_definition.scope_start_byte,
                    scope_start_byte=parsed_definition.scope_start_byte,
                    parent_scope_start_byte=parsed_definition.parent_scope_start_byte,
                    candidate_id=candidate.candidate_id,
                    conditional=parsed_definition.conditional,
                )
            )

    references: list[_Reference] = []
    for path, parsed in parsed_by_path.items():
        work.checkpoint()
        reference_ordinals: dict[tuple[str, str], int] = defaultdict(int)
        for fact in parsed.static_references:
            work.checkpoint()
            owner_id = (
                candidate_by_scope.get((path, fact.owner_scope_start_byte))
                if fact.owner_scope_start_byte is not None
                else module_candidate_by_path.get(path)
            )
            if owner_id is None:
                continue
            owner_locator = nodes[owner_id].structural_locator
            owner_hash = hashlib.sha256(owner_locator.encode("utf-8")).hexdigest()
            ordinal_key = (owner_id, fact.node_kind)
            ordinal = reference_ordinals[ordinal_key]
            reference_ordinals[ordinal_key] += 1
            references.append(
                _Reference(
                    path=path,
                    owner_qualname=fact.owner_qualname,
                    owner_candidate_id=owner_id,
                    owner_locator=owner_locator,
                    fact=fact,
                    locator=(
                        f"python-reference:{owner_hash}:{fact.node_kind}:{ordinal}"
                    ),
                )
            )

    work.enter(
        "relations",
        current_identity=snapshot.snapshot_hash,
        total_work_units=settings.maximum_work_units,
    )
    _resolve_references(
        references,
        nodes,
        definitions,
        parsed_by_path,
        module_name_by_path,
        derived_by_path,
        raw_by_path,
        work,
    )
    return nodes, definitions, parsed_by_path, module_name_by_path, raw_by_path


def _relative_module(
    current: str, is_package: bool, level: int, module: str | None
) -> str | None:
    if level == 0:
        return module or ""
    base = current.split(".") if is_package else current.split(".")[:-1]
    remove = max(0, level - 1)
    if not base or remove >= len(base):
        return None
    base = base[: len(base) - remove]
    if module:
        base.extend(module.split("."))
    return ".".join(base)


@dataclass(frozen=True, slots=True)
class _ReferenceResolution:
    targets: tuple[str, ...] = ()
    ambiguous_targets: tuple[str, ...] = ()
    plausible: bool = False
    unresolved_local: bool = False
    relation_kind: str = "static_reference"


class _ReferenceResolver:
    """Build lexical bindings, resolve references, then project static edges."""

    def __init__(
        self,
        references: Sequence[_Reference],
        nodes: dict[str, _Node],
        definitions: Sequence[_Definition],
        parsed_by_path: Mapping[str, ParsedModule],
        module_name_by_path: Mapping[str, str | None],
        derived_module_names: Mapping[str, tuple[str, ...]],
        raw_by_path: Mapping[str, bytes],
        work: _WorkBudget,
    ) -> None:
        self.references = references
        self.nodes = nodes
        self.definitions = definitions
        self.parsed_by_path = parsed_by_path
        self.module_name_by_path = module_name_by_path
        self.derived_module_names = derived_module_names
        self.raw_by_path = raw_by_path
        self.work = work
        self.module_nodes: dict[str, str] = {}
        self.module_paths: dict[str, str] = {}
        self.plausible_module_names: frozenset[str] = frozenset()
        self.definitions_by_module_name: dict[tuple[str, str], list[str]] = defaultdict(
            list
        )
        self.possible_definitions_by_module_name: dict[tuple[str, str], list[str]] = (
            defaultdict(list)
        )
        self.definitions_by_scope_name: dict[tuple[str, int | None, str], list[str]] = (
            defaultdict(list)
        )
        self.local_definition_names: set[str] = set()
        self.local_prefixes: set[str] = set()
        self.bindings: dict[tuple[str, int | None, str], list[_Binding]] = defaultdict(
            list
        )
        self.definitions_by_scope: dict[tuple[str, int], _Definition] = {}
        self.parent_scope: dict[tuple[str, int], int | None] = {}
        self.function_scopes: set[tuple[str, int]] = set()

    def resolve(self) -> None:
        self.build_symbol_tables()
        self.bind_definitions()
        self.bind_imports()
        shadow_rows = self.shadow_rows()
        self.bind_shadows(shadow_rows)
        self.bind_closure_shadows(shadow_rows)
        self.build_parent_scopes()
        static_edges = self.resolve_all_references()
        self.project_edges(static_edges)

    def build_symbol_tables(self) -> None:
        for item in self.nodes.values():
            self.work.checkpoint()
            if (
                item.structural_locator.startswith("python-module:")
                and item.module_name is not None
            ):
                self.module_nodes[item.module_name] = item.candidate_id
        for path, module_name in self.module_name_by_path.items():
            self.work.checkpoint()
            if module_name is not None:
                self.module_paths[module_name] = path
        plausible_module_names: set[str] = set()
        for names in self.derived_module_names.values():
            self.work.checkpoint()
            plausible_module_names.update(names)
        self.plausible_module_names = frozenset(plausible_module_names)
        for definition in self.definitions:
            self.work.checkpoint()
            self.index_definition(definition)
        local_definition_names: set[str] = set()
        for definition in self.definitions:
            self.work.checkpoint()
            local_definition_names.add(definition.name)
        self.local_definition_names = local_definition_names
        local_prefixes: set[str] = set()
        for name in self.plausible_module_names:
            self.work.checkpoint()
            local_prefixes.add(name.split(".", 1)[0])
        self.local_prefixes = local_prefixes
        definitions_by_scope: dict[tuple[str, int], _Definition] = {}
        function_scopes: set[tuple[str, int]] = set()
        for definition in self.definitions:
            self.work.checkpoint()
            definitions_by_scope[(definition.path, definition.scope_start_byte)] = (
                definition
            )
            if definition.node_kind in {"function", "async-function"}:
                function_scopes.add((definition.path, definition.scope_start_byte))
        self.definitions_by_scope = definitions_by_scope
        self.function_scopes = function_scopes

    def index_definition(self, definition: _Definition) -> None:
        if definition.module_name is not None and definition.parent_qualname is None:
            self.definitions_by_module_name[
                (definition.module_name, definition.name)
            ].append(definition.candidate_id)
        if definition.parent_qualname is None:
            for possible_module in self.derived_module_names[definition.path]:
                self.work.checkpoint()
                self.possible_definitions_by_module_name[
                    (possible_module, definition.name)
                ].append(definition.candidate_id)
        self.definitions_by_scope_name[
            (definition.path, definition.parent_scope_start_byte, definition.name)
        ].append(definition.candidate_id)

    def bind_definitions(self) -> None:
        for definition in self.definitions:
            self.work.checkpoint()
            scope_key = (
                definition.path,
                definition.parent_scope_start_byte,
                definition.name,
            )
            self.bindings[scope_key].append(
                _Binding(
                    definition.source_order,
                    "definition",
                    target_ids=tuple(self.definitions_by_scope_name[scope_key]),
                    plausible_local=True,
                    conditional=definition.conditional,
                )
            )

    def bind_imports(self) -> None:
        references_by_scope: dict[tuple[str, int | None], list[_Reference]] = (
            defaultdict(list)
        )
        for reference in self.references:
            self.work.checkpoint()
            references_by_scope[
                (reference.path, reference.fact.owner_scope_start_byte)
            ].append(reference)
        for (path, owner_scope), scope_references in references_by_scope.items():
            self.work.checkpoint()
            module_name = self.module_name_by_path[path]
            if module_name is None:
                continue
            is_package = PurePosixPath(path).name == "__init__.py"
            for reference in scope_references:
                self.work.checkpoint()
                if reference.fact.node_kind == "import":
                    self.bind_import_fact(
                        path,
                        owner_scope,
                        module_name,
                        is_package,
                        reference.fact,
                    )

    def bind_import_fact(
        self,
        path: str,
        owner_scope: int | None,
        module_name: str,
        is_package: bool,
        fact: StaticReference,
    ) -> None:
        wildcard = next(
            (alias for alias in fact.import_aliases if alias.bound_name == "*"),
            None,
        )
        if wildcard is not None:
            base = _relative_module(
                module_name,
                is_package,
                fact.relative_level,
                _python_dotted_identifier(fact.import_module),
            )
            plausible = (
                base.split(".", 1)[0] in self.local_prefixes
                if base is not None
                else True
            )
            if plausible:
                self.bindings[(path, owner_scope, "*")].append(
                    _Binding(
                        wildcard.source_order,
                        "shadow",
                        plausible_local=True,
                        conditional=fact.conditional,
                    )
                )
            return
        for alias in fact.import_aliases:
            self.work.checkpoint()
            bound_name, binding = self.import_binding(
                module_name,
                is_package,
                fact,
                alias,
            )
            self.bindings[(path, owner_scope, bound_name)].append(binding)

    def import_binding(
        self,
        module_name: str,
        is_package: bool,
        fact: StaticReference,
        alias: StaticImportAlias,
    ) -> tuple[str, _Binding]:
        bound_name = _python_identifier(alias.bound_name)
        imported_parts = tuple(_python_identifier(part) for part in alias.imported)
        imported = ".".join(imported_parts)
        if fact.import_module is None and fact.relative_level == 0:
            target_module = (
                imported if bound_name != imported_parts[0] else imported.split(".")[0]
            )
            target_id = self.module_nodes.get(imported)
            return bound_name, _Binding(
                alias.source_order,
                "import",
                target_ids=(target_id,) if target_id is not None else (),
                module_name=target_module,
                plausible_local=imported.split(".", 1)[0] in self.local_prefixes,
                conditional=fact.conditional,
            )
        base = _relative_module(
            module_name,
            is_package,
            fact.relative_level,
            _python_dotted_identifier(fact.import_module),
        )
        target_ids, resolved_module, ambiguous, plausible = self.from_import_target(
            base,
            imported,
        )
        return bound_name, _Binding(
            alias.source_order,
            "import",
            target_ids=target_ids,
            module_name=resolved_module,
            plausible_local=plausible,
            ambiguous_ids=ambiguous,
            conditional=fact.conditional,
        )

    def from_import_target(
        self,
        base: str | None,
        imported: str,
    ) -> tuple[tuple[str, ...], str | None, tuple[str, ...], bool]:
        if base is None:
            return (), None, (), True
        submodule = f"{base}.{imported}" if base else imported
        submodule_id = self.module_nodes.get(submodule)
        choices = self.possible_definitions_by_module_name.get((base, imported), [])
        base_path = self.module_paths.get(base)
        base_is_package = bool(
            base_path is not None and PurePosixPath(base_path).name == "__init__.py"
        )
        target_ids: tuple[str, ...] = ()
        target_module: str | None = None
        ambiguous: tuple[str, ...] = ()
        plausible = False
        if base_path is not None and not base_is_package:
            if len(choices) == 1:
                target_ids = (choices[0],)
            elif choices:
                ambiguous = tuple(sorted(choices))
            elif submodule_id is not None:
                plausible = True
        elif submodule_id is not None and choices:
            ambiguous = tuple(sorted({submodule_id, *choices}))
        elif submodule_id is not None:
            target_module = submodule
            target_ids = (submodule_id,)
        elif base_path is not None and len(choices) == 1:
            target_ids = (choices[0],)
        elif choices:
            ambiguous = tuple(sorted(choices))
        plausible = (
            bool(base and base.split(".", 1)[0] in self.local_prefixes) or plausible
        )
        plausible = plausible or submodule in self.plausible_module_names
        return target_ids, target_module, ambiguous, plausible

    def shadow_rows(self) -> list[tuple[str, int | None, StaticBinding]]:
        rows: list[tuple[str, int | None, StaticBinding]] = []
        for path, parsed in self.parsed_by_path.items():
            self.work.checkpoint()
            for fact in parsed.static_bindings:
                self.work.checkpoint()
                if fact.kind not in {"definition", "import"}:
                    rows.append((path, fact.owner_scope_start_byte, fact))
        return rows

    def bind_shadows(
        self,
        shadow_rows: Sequence[tuple[str, int | None, StaticBinding]],
    ) -> None:
        locally_plausible_names: set[tuple[str, str]] = set()
        for (path, _owner, name), items in self.bindings.items():
            self.work.checkpoint()
            if any(
                item.target_ids or item.ambiguous_ids or item.plausible_local
                for item in items
            ):
                locally_plausible_names.add((path, name))
        for path, owner_scope, binding_fact in shadow_rows:
            self.work.checkpoint()
            binding_name = _python_identifier(binding_fact.name)
            self.bindings[(path, owner_scope, binding_name)].append(
                _Binding(
                    binding_fact.source_order,
                    "shadow",
                    plausible_local=(path, binding_name) in locally_plausible_names,
                    conditional=binding_fact.conditional,
                )
            )

    def bind_closure_shadows(
        self,
        shadow_rows: Sequence[tuple[str, int | None, StaticBinding]],
    ) -> None:
        class_scopes: set[tuple[str, int]] = set()
        for item in self.definitions:
            self.work.checkpoint()
            if item.node_kind == "class":
                class_scopes.add((item.path, item.scope_start_byte))
        descendants_by_class = self.descendant_scopes_by_class()
        for path, owner_scope, binding_fact in shadow_rows:
            self.work.checkpoint()
            if (
                binding_fact.kind != "parameter"
                or (path, owner_scope) not in class_scopes
            ):
                continue
            assert owner_scope is not None
            binding_name = _python_identifier(binding_fact.name)
            for definition in descendants_by_class.get((path, owner_scope), ()):
                self.work.checkpoint()
                self.bindings[(path, definition.scope_start_byte, binding_name)].append(
                    _Binding(0, "shadow", plausible_local=True)
                )
        for path, descendants in (
            (key[0], values) for key, values in descendants_by_class.items()
        ):
            self.work.checkpoint()
            for definition in descendants:
                self.work.checkpoint()
                if definition.node_kind in {"function", "async-function"}:
                    self.bindings[
                        (path, definition.scope_start_byte, "__class__")
                    ].append(_Binding(0, "shadow", plausible_local=True))

    def descendant_scopes_by_class(
        self,
    ) -> dict[tuple[str, int], list[_Definition]]:
        result: dict[tuple[str, int], list[_Definition]] = defaultdict(list)
        for definition in self.definitions:
            self.work.charge()
            parent = definition.parent_scope_start_byte
            while parent is not None:
                self.work.charge()
                ancestor = self.definitions_by_scope.get((definition.path, parent))
                if ancestor is None:
                    break
                if ancestor.node_kind == "class":
                    result[(definition.path, parent)].append(definition)
                parent = ancestor.parent_scope_start_byte
        return result

    def build_parent_scopes(self) -> None:
        for definition in self.definitions:
            self.work.checkpoint()
            parent = definition.parent_scope_start_byte
            while parent is not None:
                self.work.checkpoint()
                parent_definition = self.definitions_by_scope.get(
                    (definition.path, parent)
                )
                if parent_definition is None:
                    parent = None
                    break
                if parent_definition.node_kind == "class":
                    parent = parent_definition.parent_scope_start_byte
                    continue
                break
            self.parent_scope[(definition.path, definition.scope_start_byte)] = parent

    @staticmethod
    def uncertain_binding(items: Sequence[_Binding]) -> _Binding:
        possible_targets = {
            target
            for item in items
            for target in (*item.target_ids, *item.ambiguous_ids)
        }
        return _Binding(
            max((item.source_order for item in items), default=0),
            "shadow",
            plausible_local=any(item.plausible_local for item in items),
            ambiguous_ids=tuple(sorted(possible_targets)),
            conditional=any(item.conditional for item in items),
        )

    def visible_binding(
        self,
        path: str,
        owner_scope: int | None,
        name: str,
        source_order: int,
    ) -> _Binding | None:
        current = owner_scope
        direct_scope = True
        while True:
            all_choices = self.bindings.get((path, current, name), [])
            if direct_scope:
                binding = self.direct_binding(
                    path,
                    current,
                    all_choices,
                    source_order,
                )
                if binding is not None:
                    return binding
            elif all_choices:
                if (
                    len(all_choices) == 1
                    and not all_choices[0].conditional
                    and all_choices[0].source_order <= source_order
                ):
                    return all_choices[0]
                return self.uncertain_binding(all_choices)
            if current is None:
                return None
            current = self.parent_scope.get((path, current))
            direct_scope = False

    def direct_binding(
        self,
        path: str,
        current: int | None,
        all_choices: Sequence[_Binding],
        source_order: int,
    ) -> _Binding | None:
        choices = [item for item in all_choices if item.source_order <= source_order]
        if choices:
            latest = max(
                choices,
                key=lambda item: (
                    item.source_order,
                    item.kind,
                    item.target_ids,
                    item.ambiguous_ids,
                ),
            )
            return self.uncertain_binding(choices) if latest.conditional else latest
        if (path, current) in self.function_scopes and all_choices:
            return self.uncertain_binding(all_choices)
        return None

    def qualified_target(
        self,
        module_name: str,
        parts: Sequence[str],
    ) -> tuple[tuple[str, ...], tuple[str, ...], bool]:
        if not parts:
            target = self.module_nodes.get(module_name)
            return (
                (target,) if target else (),
                (),
                module_name.split(".")[0] in self.local_prefixes,
            )
        for split in range(len(parts), -1, -1):
            result = self.qualified_target_at_split(module_name, parts, split)
            if result is not None:
                return result
        return (
            (),
            (),
            module_name.split(".", 1)[0] in self.local_prefixes,
        )

    def qualified_target_at_split(
        self,
        module_name: str,
        parts: Sequence[str],
        split: int,
    ) -> tuple[tuple[str, ...], tuple[str, ...], bool] | None:
        candidate_module = ".".join((module_name, *parts[:split]))
        if candidate_module not in self.plausible_module_names:
            return None
        remaining = parts[split:]
        if candidate_module not in self.module_paths:
            ambiguous = (
                tuple(
                    sorted(
                        self.possible_definitions_by_module_name.get(
                            (candidate_module, remaining[0]), []
                        )
                    )
                )
                if len(remaining) == 1
                else ()
            )
            return (), ambiguous, True
        if not remaining:
            return ((self.module_nodes[candidate_module],), (), True)
        choices = self.definitions_by_module_name.get(
            (candidate_module, remaining[0]), []
        )
        if len(remaining) == 1:
            if len(choices) == 1:
                return ((choices[0],), (), True)
            return ((), tuple(sorted(choices)), True)
        return ((), (), True)

    def resolve_all_references(self) -> set[tuple[str, str, str]]:
        static_edges: set[tuple[str, str, str]] = set()
        for node in self.nodes.values():
            self.work.checkpoint()
            if node.owner_candidate_id is not None:
                static_edges.add(
                    ("enclosing_definition", node.owner_candidate_id, node.candidate_id)
                )
        for reference in self.references:
            self.work.checkpoint()
            resolution = self.resolve_reference(reference)
            if resolution is None:
                continue
            self.materialize_reference(reference, resolution, static_edges)
        return static_edges

    def resolve_reference(
        self,
        reference: _Reference,
    ) -> _ReferenceResolution | None:
        if reference.fact.node_kind == "import":
            resolution = self.resolve_import_reference(reference)
        else:
            resolution = self.resolve_named_reference(reference)
        if (
            not resolution.targets
            and not resolution.ambiguous_targets
            and not resolution.plausible
        ):
            return None
        return resolution

    def resolve_import_reference(
        self,
        reference: _Reference,
    ) -> _ReferenceResolution:
        all_targets: set[str] = set()
        all_ambiguous: set[str] = set()
        plausible = False
        unresolved_local = False
        for alias in reference.fact.import_aliases:
            binding = self.visible_binding(
                reference.path,
                reference.fact.owner_scope_start_byte,
                alias.bound_name,
                alias.source_order,
            )
            if binding is None:
                continue
            all_targets.update(binding.target_ids)
            all_ambiguous.update(binding.ambiguous_ids)
            plausible = plausible or binding.plausible_local
            if binding.ambiguous_ids or (
                binding.plausible_local and len(binding.target_ids) != 1
            ):
                unresolved_local = True
        return _ReferenceResolution(
            targets=tuple(sorted(all_targets)),
            ambiguous_targets=tuple(sorted(all_ambiguous)),
            plausible=plausible,
            unresolved_local=unresolved_local,
            relation_kind="static_import",
        )

    def resolve_named_reference(
        self,
        reference: _Reference,
    ) -> _ReferenceResolution:
        fact = reference.fact
        parts = (
            tuple(_python_identifier(part) for part in fact.name_parts)
            if fact.name_parts
            else None
        )
        plausible = False
        if fact.node_kind == "call" and parts in {
            ("importlib", "import_module"),
            ("__import__",),
        }:
            if fact.literal_argument is not None:
                plausible = (
                    fact.literal_argument.split(".", 1)[0] in self.local_prefixes
                )
            parts = None
        elif fact.node_kind == "call" and parts in {
            ("getattr",),
            ("setattr",),
        }:
            attribute = (
                fact.literal_arguments[1] if len(fact.literal_arguments) > 1 else None
            )
            if attribute in self.local_definition_names:
                plausible = True
            parts = None
        resolution = (
            self.resolve_name_parts(reference, parts, plausible)
            if parts
            else _ReferenceResolution(plausible=plausible)
        )
        return replace(
            resolution,
            relation_kind=(
                "static_call" if fact.node_kind == "call" else "static_reference"
            ),
        )

    def resolve_name_parts(
        self,
        reference: _Reference,
        parts: tuple[str, ...],
        plausible: bool,
    ) -> _ReferenceResolution:
        fact = reference.fact
        targets: tuple[str, ...] = ()
        ambiguous_targets: tuple[str, ...] = ()
        binding = self.visible_binding(
            reference.path,
            fact.owner_scope_start_byte,
            parts[0],
            fact.source_order,
        )
        if binding is not None:
            targets, ambiguous_targets, plausible = self.resolve_bound_name(
                binding,
                parts,
                plausible,
            )
        elif self.module_name_by_path[reference.path] is not None:
            targets, ambiguous_targets, qualified_plausible = self.qualified_target(
                parts[0], parts[1:]
            )
            plausible = qualified_plausible or parts[0] in self.local_prefixes
        wildcard_binding = self.visible_binding(
            reference.path,
            fact.owner_scope_start_byte,
            "*",
            fact.source_order,
        )
        plausible = plausible or bool(
            wildcard_binding is not None and wildcard_binding.plausible_local
        )
        if fact.node_kind == "attribute" and not fact.is_load:
            plausible = plausible or bool(targets)
            targets = ()
        if len(targets) > 1:
            ambiguous_targets = tuple(sorted(targets))
            targets = ()
        return _ReferenceResolution(
            targets=targets,
            ambiguous_targets=ambiguous_targets,
            plausible=plausible,
        )

    def resolve_bound_name(
        self,
        binding: _Binding,
        parts: tuple[str, ...],
        plausible: bool,
    ) -> tuple[tuple[str, ...], tuple[str, ...], bool]:
        plausible = binding.plausible_local
        if binding.kind == "shadow" and any(
            part in self.local_definition_names for part in parts[1:]
        ):
            plausible = True
        ambiguous_targets = binding.ambiguous_ids
        if binding.module_name is not None:
            targets, qualified_ambiguous, qualified_plausible = self.qualified_target(
                binding.module_name,
                parts[1:],
            )
            ambiguous_targets = tuple(
                sorted({*ambiguous_targets, *qualified_ambiguous})
            )
            plausible = plausible or qualified_plausible
            return targets, ambiguous_targets, plausible
        if len(parts) == 1:
            return binding.target_ids, ambiguous_targets, plausible
        return (), ambiguous_targets, plausible or bool(binding.target_ids)

    def materialize_reference(
        self,
        reference: _Reference,
        resolution: _ReferenceResolution,
        static_edges: set[tuple[str, str, str]],
    ) -> None:
        fact = reference.fact
        owner_node = self.nodes[reference.owner_candidate_id]
        exactly_resolved = (
            bool(resolution.targets)
            and not resolution.ambiguous_targets
            and not resolution.unresolved_local
            if fact.node_kind == "import"
            else len(resolution.targets) == 1
        )
        kind: CandidateKind = (
            "static_reference" if exactly_resolved else "unresolved_reference"
        )
        candidate = _make_node(
            candidate_kind=kind,
            path=reference.path,
            owner=reference.owner_qualname or owner_node.owner,
            symbol=reference.owner_qualname,
            module_name=owner_node.module_name,
            role=owner_node.role,
            start_line=owner_node.start_line,
            end_line=owner_node.end_line,
            node_line=fact.line,
            locator=reference.locator,
            raw=self.raw_by_path[reference.path],
            work=self.work,
            owner_candidate_id=reference.owner_candidate_id,
        )
        candidate.ambiguous_targets = resolution.ambiguous_targets
        if resolution.ambiguous_targets:
            candidate.bases.add("ambiguous_relation")
        self.nodes[candidate.candidate_id] = candidate
        static_edges.add(
            (
                "enclosing_definition",
                reference.owner_candidate_id,
                candidate.candidate_id,
            )
        )
        for target in resolution.targets:
            self.work.checkpoint()
            static_edges.add(
                (
                    resolution.relation_kind,
                    candidate.candidate_id,
                    target,
                )
            )
            candidate.closure_neighbors.add(target)
            self.nodes[target].closure_neighbors.add(candidate.candidate_id)
        for target in resolution.ambiguous_targets:
            self.work.checkpoint()
            candidate.closure_neighbors.add(target)
            self.nodes[target].closure_neighbors.add(candidate.candidate_id)

    def project_edges(self, static_edges: set[tuple[str, str, str]]) -> None:
        for relation_kind, source, target in static_edges:
            self.work.checkpoint()
            encoded = f"static\0{relation_kind}\0{source}\0{target}"
            self.nodes[source].trace_flags.add(encoded)
            self.nodes[target].trace_flags.add(encoded)


def _resolve_references(
    references: Sequence[_Reference],
    nodes: dict[str, _Node],
    definitions: Sequence[_Definition],
    parsed_by_path: Mapping[str, ParsedModule],
    module_name_by_path: Mapping[str, str | None],
    derived_module_names: Mapping[str, tuple[str, ...]],
    raw_by_path: Mapping[str, bytes],
    work: _WorkBudget,
) -> None:
    _ReferenceResolver(
        references,
        nodes,
        definitions,
        parsed_by_path,
        module_name_by_path,
        derived_module_names,
        raw_by_path,
        work,
    ).resolve()


def _require_obligation_source(
    snapshot: RepositorySnapshot, obligation: ObligationRecord
) -> bytes:
    try:
        row = snapshot.file(obligation.path)
    except KeyError:
        raise EvidenceDiscoveryError(
            "SOURCE_UNREADABLE",
            f"obligation source is absent: {obligation.path}",
            {"path": obligation.path, "error_class": "io"},
        ) from None
    if row.raw_bytes is None:
        raise EvidenceDiscoveryError(
            "SOURCE_UNREADABLE",
            f"obligation source is unreadable: {obligation.path}",
            {"path": obligation.path, "error_class": row.error_class},
        )
    return row.raw_bytes


def _issue_attributable(
    issue: Issue,
    obligation: ObligationRecord,
    same_section_id_count: int,
) -> bool:
    if obligation.kind == "invariant":
        invariant_id = obligation.obligation_id.removeprefix("invariant::")
        return issue.invariant_id == invariant_id
    section_id = obligation.obligation_id.rsplit("#", 1)[-1]
    return issue.section_id == section_id and (
        same_section_id_count == 1 or issue.path == obligation.path
    )


def _issue_locator(issue: Issue, obligation: ObligationRecord, ordinal: int) -> str:
    target = unicodedata.normalize("NFC", obligation.obligation_id)
    return f"resolver-issue:{issue.code}:{target}:{ordinal}"


def _add_issue_candidates(
    nodes: dict[str, _Node],
    snapshot: RepositorySnapshot,
    report: Report,
    obligation: ObligationRecord,
    work: _WorkBudget,
) -> tuple[Issue, ...]:
    raw = _require_obligation_source(snapshot, obligation)
    ordinals: dict[str, int] = defaultdict(int)
    conflict_issues: list[Issue] = []
    section_id = obligation.obligation_id.rsplit("#", 1)[-1]
    same_section_id_count = (
        sum(item.section_id == section_id for item in report.spec_sections)
        if obligation.kind == "section"
        else 0
    )
    for issue in report.issues:
        work.charge()
        if not _issue_attributable(
            issue,
            obligation,
            same_section_id_count,
        ):
            continue
        is_conflict = any(word in issue.code for word in _CONFLICT_WORDS)
        if is_conflict:
            conflict_issues.append(issue)
        ordinal = ordinals[issue.code]
        ordinals[issue.code] += 1
        locator = _issue_locator(issue, obligation, ordinal)
        candidate = _make_node(
            candidate_kind="report_issue",
            path=obligation.path,
            owner=issue.code,
            symbol=issue.symbol,
            module_name=None,
            role="implementation",
            start_line=obligation.start_line,
            end_line=obligation.end_line,
            node_line=issue.line or obligation.start_line,
            locator=locator,
            raw=raw,
            work=work,
        )
        candidate.bases.add("resolver_issue")
        candidate.trace_flags.add("issue_conflict" if is_conflict else "issue_partial")
        nodes[candidate.candidate_id] = candidate
    return tuple(conflict_issues)


def _path_symbol_matches(node: _Node, path: str, symbol: str | None) -> bool:
    path_matches = node.path == path or node.path.startswith(path.rstrip("/") + "/")
    if not path_matches:
        return False
    is_module = node.structural_locator.startswith(
        ("python-module:", "python-module-path:")
    )
    if symbol is None or symbol == "<module>":
        return node.path == path and is_module
    node_symbol = node.symbol or ("module" if is_module else node.owner)
    return symbol == node_symbol


def _declaration_matches(
    node: _Node,
    path: str,
    symbol: str | None,
    work: _WorkBudget,
) -> bool:
    """Charge one exact candidate-to-declaration comparison."""

    work.charge()
    return _path_symbol_matches(node, path, symbol)


def _section_declarations(
    node: _Node,
    mappings: Sequence[SpecMapping],
    references: Sequence[CodeRef],
    work: _WorkBudget,
) -> tuple[bool, bool]:
    has_mapping = False
    has_backlink = False
    for mapping in mappings:
        if mapping.target_path is not None and _declaration_matches(
            node, mapping.target_path, mapping.target_symbol, work
        ):
            has_mapping = True
    for reference in references:
        if not _declaration_matches(node, reference.path, reference.owner_symbol, work):
            continue
        has_backlink = True
    return has_mapping, has_backlink


def _section_inputs(
    report: Report,
    obligation: ObligationRecord,
    work: _WorkBudget,
) -> tuple[tuple[SpecMapping, ...], tuple[CodeRef, ...]]:
    if obligation.kind != "section":
        return (), ()
    spec_path, section_id = obligation.obligation_id.rsplit("#", 1)
    mappings: list[SpecMapping] = []
    for mapping in report.spec_mappings:
        work.charge()
        if mapping.spec_path == spec_path and mapping.section_id == section_id:
            mappings.append(mapping)
    references: list[CodeRef] = []
    for reference in report.code_refs:
        work.charge()
        if (
            reference.ref_context == "asserted"
            and reference.spec_path == spec_path
            and section_id in reference.section_ids
        ):
            references.append(reference)
    return tuple(mappings), tuple(references)


def _invariant_declarations(
    node: _Node,
    declarations: Sequence[InvariantDeclaration],
    binds: Sequence[InvariantBind],
    edges_by_spec_target: Mapping[tuple[str, str], Sequence[Edge]],
    work: _WorkBudget,
) -> tuple[str | None, bool]:
    target_relation: str | None = None
    is_binding = False
    for declaration in declarations:
        if declaration.declaration_kind == "code" and _declaration_matches(
            node,
            declaration.path,
            declaration.owner_symbol,
            work,
        ):
            target_relation = "invariant_declaration"
        elif declaration.section_id is not None:
            for edge in edges_by_spec_target.get(
                (declaration.path, declaration.section_id), ()
            ):
                if _declaration_matches(
                    node,
                    edge.code_path,
                    edge.code_symbol,
                    work,
                ):
                    target_relation = "invariant_bind"
    for bind in binds:
        if _declaration_matches(
            node,
            bind.test_path,
            bind.test_symbol,
            work,
        ):
            is_binding = True
    return target_relation, is_binding


def _invariant_inputs(
    report: Report,
    obligation: ObligationRecord,
    work: _WorkBudget,
) -> tuple[
    tuple[InvariantDeclaration, ...],
    tuple[InvariantBind, ...],
    Mapping[tuple[str, str], tuple[Edge, ...]],
]:
    if obligation.kind != "invariant":
        return (), (), {}
    invariant_id = obligation.obligation_id.removeprefix("invariant::")
    declarations_list: list[InvariantDeclaration] = []
    for declaration in report.invariants:
        work.charge()
        if declaration.invariant_id == invariant_id:
            declarations_list.append(declaration)
    binds_list: list[InvariantBind] = []
    for bind in report.binds:
        work.charge()
        if bind.invariant_id == invariant_id:
            binds_list.append(bind)
    declarations = tuple(declarations_list)
    binds = tuple(binds_list)
    spec_targets = {
        (item.path, item.section_id)
        for item in declarations
        if item.declaration_kind == "spec" and item.section_id is not None
    }
    edges: dict[tuple[str, str], list[Edge]] = defaultdict(list)
    if spec_targets:
        for edge in report.edges:
            work.charge()
            key = (edge.spec_path, edge.section_id)
            if edge.kind == "mapping" and key in spec_targets:
                edges[key].append(edge)
    return declarations, binds, {key: tuple(items) for key, items in edges.items()}


def _obligation_locator(
    obligation: ObligationRecord,
    nodes: Mapping[str, _Node],
    invariant_declarations: Sequence[InvariantDeclaration],
    work: _WorkBudget,
) -> str | None:
    if obligation.kind == "section":
        return f"markdown-section:{obligation.obligation_id.rsplit('#', 1)[-1]}"
    invariant_id = obligation.obligation_id.removeprefix("invariant::")
    declaration = next(iter(invariant_declarations), None)
    if (
        declaration is not None
        and declaration.declaration_kind == "spec"
        and declaration.section_id is not None
    ):
        return f"markdown-invariant:{declaration.section_id}:{invariant_id}"
    if declaration is not None:
        matching = sorted(
            node.structural_locator
            for node in nodes.values()
            if node.candidate_kind in ("implementation_definition", "test_definition")
            and _declaration_matches(
                node,
                declaration.path,
                declaration.owner_symbol,
                work,
            )
        )
        if len(matching) == 1:
            return matching[0]
    return None


def _project_declared_relations(
    nodes: Mapping[str, _Node],
    report: Report,
    obligation: ObligationRecord,
    conflict_issues: Sequence[Issue],
    section_mappings: Sequence[SpecMapping],
    section_references: Sequence[CodeRef],
    invariant_declarations: Sequence[InvariantDeclaration],
    invariant_binds: Sequence[InvariantBind],
    invariant_edges: Mapping[tuple[str, str], Sequence[Edge]],
    work: _WorkBudget,
) -> dict[str, tuple[CandidateRelation, ...]]:
    rows: dict[str, list[CandidateRelation]] = defaultdict(list)
    obligation_locator = _obligation_locator(
        obligation,
        nodes,
        invariant_declarations,
        work,
    )
    invariant_targets: set[str] = set()
    invariant_bindings: set[str] = set()
    for node in nodes.values():
        if node.candidate_kind == "report_issue":
            rows[node.candidate_id].append(
                CandidateRelation(
                    "issue_target",
                    node.candidate_id,
                    None,
                    node.structural_locator,
                    obligation_locator,
                )
            )
            continue
        conflict = False
        for issue in conflict_issues:
            work.charge()
            if (issue.path in {node.path, obligation.path}) and (
                issue.symbol is None or issue.symbol in {node.symbol, node.owner}
            ):
                conflict = True
                break
        if conflict:
            node.trace_flags.add("conflict")
        if obligation.kind == "section":
            mapping, backlink = _section_declarations(
                node, section_mappings, section_references, work
            )
            if mapping:
                node.trace_flags.add("mapping")
                node.bases.add("declared_relation")
                rows[node.candidate_id].append(
                    CandidateRelation(
                        "spec_mapping",
                        None,
                        node.candidate_id,
                        obligation_locator,
                        node.structural_locator,
                    )
                )
            if backlink:
                node.trace_flags.add("backlink")
                node.bases.add("declared_relation")
                rows[node.candidate_id].append(
                    CandidateRelation(
                        "code_backlink",
                        node.candidate_id,
                        None,
                        node.structural_locator,
                        obligation_locator,
                    )
                )
        else:
            target_relation, binding = _invariant_declarations(
                node,
                invariant_declarations,
                invariant_binds,
                invariant_edges,
                work,
            )
            if target_relation is not None:
                invariant_targets.add(node.candidate_id)
                node.trace_flags.add("invariant_target")
                node.bases.add("invariant_relation")
                rows[node.candidate_id].append(
                    CandidateRelation(
                        target_relation,
                        None,
                        node.candidate_id,
                        obligation_locator,
                        node.structural_locator,
                    )
                )
            if binding:
                invariant_bindings.add(node.candidate_id)
                node.trace_flags.add("binding_test")
                node.bases.add("invariant_relation")
                rows[node.candidate_id].append(
                    CandidateRelation(
                        "binding_test",
                        node.candidate_id,
                        None,
                        node.structural_locator,
                        obligation_locator,
                    )
                )
    for candidate_id in invariant_targets:
        nodes[candidate_id].trace_flags.add(
            "reciprocal" if invariant_bindings else "missing_binding_test"
        )
    for candidate_id in invariant_bindings:
        nodes[candidate_id].trace_flags.add(
            "reciprocal" if invariant_targets else "missing_invariant_target"
        )
    return {
        candidate_id: tuple(sorted(set(items), key=_relation_order))
        for candidate_id, items in rows.items()
    }


def _static_edges(
    nodes: Mapping[str, _Node],
) -> tuple[tuple[str, str, str], ...]:
    rows: set[tuple[str, str, str]] = set()
    for node in nodes.values():
        for encoded in node.trace_flags:
            if not encoded.startswith("static\0"):
                continue
            _prefix, relation_kind, source, target = encoded.split("\0")
            rows.add((relation_kind, source, target))
    return tuple(sorted(rows))


def _static_relations(
    nodes: Mapping[str, _Node],
    static_edges: Sequence[tuple[str, str, str]],
    work: _WorkBudget,
) -> dict[str, tuple[CandidateRelation, ...]]:
    rows: dict[str, set[CandidateRelation]] = defaultdict(set)
    for relation_kind, source, target in static_edges:
        work.charge()
        relation = CandidateRelation(
            relation_kind,
            source,
            target,
            nodes[source].structural_locator,
            nodes[target].structural_locator,
        )
        rows[source].add(relation)
        rows[target].add(relation)
    return {
        candidate_id: tuple(sorted(items, key=_relation_order))
        for candidate_id, items in rows.items()
    }


@dataclass(frozen=True, slots=True)
class _CollapsedBridge:
    """One private discovery-v2 hop; public relations remain uncollapsed."""

    target_definition_id: str
    orienting_reference_id: str


def _is_collapsed_endpoint(node: _Node) -> bool:
    return node.candidate_kind in {
        "implementation_definition",
        "test_definition",
    } and not node.structural_locator.startswith(
        ("python-module:", "python-module-path:")
    )


def _collapsed_bridge_index(
    nodes: Mapping[str, _Node],
    static_edges: Sequence[tuple[str, str, str]],
    work: _WorkBudget,
) -> dict[str, tuple[_CollapsedBridge, ...]]:
    """Collapse owner-reference-target facts into symmetric definition hops."""

    owners_by_reference: dict[str, set[str]] = defaultdict(set)
    target_edges: list[tuple[str, str]] = []
    for relation_kind, source, target in static_edges:
        # [EVC-7.1]: constructing this per-obligation index inspects each raw
        # edge exactly once. Pairing the already inspected facts below does not
        # create another raw-edge charge.
        work.charge()
        target_node = nodes.get(target)
        if target_node is None:
            continue
        if relation_kind == "enclosing_definition" and target_node.candidate_kind in {
            "static_reference",
            "unresolved_reference",
        }:
            owners_by_reference[target].add(source)
        elif relation_kind in {
            "static_import",
            "static_call",
            "static_reference",
        }:
            target_edges.append((source, target))

    bridge_rows: dict[str, set[_CollapsedBridge]] = defaultdict(set)
    for reference_id, target_id in target_edges:
        work.checkpoint()
        reference = nodes[reference_id]
        resolved_target = nodes[target_id]
        owners = owners_by_reference.get(reference_id, set())
        if (
            reference.candidate_kind != "static_reference"
            or len(owners) != 1
            or not _is_collapsed_endpoint(resolved_target)
        ):
            continue
        owner_id = next(iter(owners))
        owner = nodes[owner_id]
        if not _is_collapsed_endpoint(owner):
            continue
        bridge_rows[owner_id].add(_CollapsedBridge(target_id, reference_id))
        bridge_rows[target_id].add(_CollapsedBridge(owner_id, reference_id))
    return {
        candidate_id: tuple(
            sorted(
                rows,
                key=lambda item: (
                    item.target_definition_id,
                    item.orienting_reference_id,
                ),
            )
        )
        for candidate_id, rows in bridge_rows.items()
    }


def _trace_state(node: _Node) -> TraceState:
    if "conflict" in node.trace_flags or "issue_conflict" in node.trace_flags:
        return "conflicted"
    if node.candidate_kind == "report_issue":
        return "partially_declared"
    if "reciprocal" in node.trace_flags:
        return "declared"
    if "mapping" in node.trace_flags and "backlink" in node.trace_flags:
        return "declared"
    if node.trace_flags.intersection(
        {"mapping", "backlink", "invariant_target", "binding_test", "issue_partial"}
    ):
        return "partially_declared"
    return "untraced"


def _advice(
    node: _Node,
    obligation: ObligationRecord,
    invariant_declarations: Sequence[InvariantDeclaration],
) -> tuple[TraceAdvice, ...]:
    if node.candidate_kind == "report_issue":
        return ()
    items: list[TraceAdvice] = []
    role: EvidenceRole = (
        "binding_test"
        if node.role == "test" and obligation.kind == "invariant"
        else node.role
    )
    spec_declaration = next(
        (
            item
            for item in invariant_declarations
            if item.declaration_kind == "spec" and item.section_id is not None
        ),
        None,
    )
    spec_target_id = (
        f"{spec_declaration.path}#{spec_declaration.section_id}"
        if spec_declaration is not None
        else None
    )
    if obligation.kind == "section":
        if "mapping" not in node.trace_flags:
            items.append(
                TraceAdvice(
                    "ADD_RECIPROCAL_MAPPING",
                    obligation.obligation_id,
                    role,
                    ("spec_mapping",),
                )
            )
        if "backlink" not in node.trace_flags:
            items.append(
                TraceAdvice(
                    "ADD_RECIPROCAL_BACKLINK",
                    obligation.obligation_id,
                    role,
                    ("code_backlink",),
                )
            )
    elif "missing_binding_test" in node.trace_flags:
        items.append(
            TraceAdvice(
                "ADD_BINDING_TEST",
                obligation.obligation_id,
                "binding_test",
                ("binding_test",),
            )
        )
    elif "missing_invariant_target" in node.trace_flags and spec_target_id is not None:
        items.append(
            TraceAdvice(
                "ADD_INVARIANT_BIND",
                spec_target_id,
                "implementation",
                ("spec_mapping",),
            )
        )
    elif role == "binding_test":
        if "binding_test" not in node.trace_flags:
            items.append(
                TraceAdvice(
                    "ADD_BINDING_TEST",
                    obligation.obligation_id,
                    role,
                    ("binding_test",),
                )
            )
    elif "invariant_target" not in node.trace_flags and spec_target_id is not None:
        items.append(
            TraceAdvice(
                "ADD_INVARIANT_BIND",
                spec_target_id,
                role,
                ("spec_mapping",),
            )
        )
    return tuple(sorted(items, key=_advice_order))


def _obligation_tokens(
    obligation: ObligationRecord,
    obligation_search_text: str,
) -> frozenset[str]:
    return frozenset().union(
        _tokens(obligation.obligation_id),
        _tokens(obligation.title or ""),
        _tokens(obligation_search_text),
    )


def _candidate_tokens(node: _Node) -> frozenset[str]:
    return frozenset().union(
        _tokens(node.path),
        _tokens(node.module_name or ""),
        _tokens(node.symbol or node.owner or ""),
    )


def _closure(
    nodes: Mapping[str, _Node],
    static_edges: Sequence[tuple[str, str, str]],
    settings: ObligationSettings,
    work: _WorkBudget,
) -> set[str]:
    selected: set[str] = set()
    attempted: set[str] = set()

    def insert(candidate_id: str, basis: DiscoveryBasis | None) -> bool:
        if candidate_id not in attempted:
            attempted.add(candidate_id)
            work.charge()
        if candidate_id in selected:
            if basis is not None:
                nodes[candidate_id].bases.add(basis)
            return False
        selected.add(candidate_id)
        if basis is not None:
            nodes[candidate_id].bases.add(basis)
        return True

    for candidate_id in sorted(nodes):
        node = nodes[candidate_id]
        if node.bases.intersection(
            {"declared_relation", "invariant_relation", "resolver_issue"}
        ):
            insert(candidate_id, None)
    lexical = sorted(
        (
            node
            for node in nodes.values()
            if node.lexical_score[0] > 0
            and node.candidate_kind in {"implementation_definition", "test_definition"}
            and not node.structural_locator.startswith(
                ("python-module:", "python-module-path:")
            )
        ),
        key=lambda item: (
            -item.lexical_score[0],
            -item.lexical_score[1],
            item.candidate_id,
        ),
    )[: settings.maximum_lexical_seeds]
    for node in lexical:
        insert(node.candidate_id, "lexical_match")

    bridges = _collapsed_bridge_index(nodes, static_edges, work)

    def expand_ambiguities(frontier_ids: Sequence[str]) -> list[str]:
        queue = sorted(set(frontier_ids))
        heapq.heapify(queue)
        expanded: list[str] = []
        while queue:
            candidate_id = heapq.heappop(queue)
            if nodes[candidate_id].candidate_kind != "unresolved_reference":
                continue
            for ambiguous in nodes[candidate_id].ambiguous_targets:
                if insert(ambiguous, "ambiguous_relation"):
                    expanded.append(ambiguous)
                    heapq.heappush(queue, ambiguous)
        return expanded

    frontier = sorted(selected)
    frontier = sorted({*frontier, *expand_ambiguities(frontier)})
    for _depth in range(settings.static_neighbor_depth):
        next_frontier: list[str] = []
        for candidate_id in sorted(frontier):
            for bridge in bridges.get(candidate_id, ()):
                insert(bridge.orienting_reference_id, "static_neighbor")
                if insert(bridge.target_definition_id, "static_neighbor"):
                    next_frontier.append(bridge.target_definition_id)
        next_frontier.extend(expand_ambiguities(next_frontier))
        frontier = sorted(set(next_frontier))
        if not frontier:
            break
    if len(selected) > settings.maximum_candidate_items:
        raise _budget_error(
            "candidate_items", settings.maximum_candidate_items, len(selected)
        )
    return selected


def prepare_evidence_catalog(
    snapshot: RepositorySnapshot,
    profile: ProfileConfig,
    settings: ObligationSettings,
    *,
    progress: OperationProgress | None = None,
    emit_progress: bool = True,
) -> PreparedEvidenceCatalog:
    """Parse one immutable snapshot once for a batch of obligation reads."""

    work = _WorkBudget(
        settings.maximum_work_units,
        progress=progress,
        emit_progress=emit_progress,
    )
    work.enter(
        "catalog",
        current_identity=snapshot.snapshot_hash,
        total_work_units=settings.maximum_work_units,
    )
    _validate_semantic_utf8(snapshot, profile, work)
    nodes, _definitions, _trees, _module_names, _raw = _catalog_python(
        snapshot, profile, settings, work
    )
    for node in nodes.values():
        node.lexical_tokens = _candidate_tokens(node)
    return PreparedEvidenceCatalog(
        snapshot_hash=snapshot.snapshot_hash,
        profile=profile,
        settings=settings,
        base_work_units=work.used,
        _nodes=tuple(nodes[candidate_id] for candidate_id in sorted(nodes)),
        _static_edges=_static_edges(nodes),
    )


def _catalog_nodes_for_obligation(
    catalog: PreparedEvidenceCatalog,
) -> dict[str, _Node]:
    """Clone mutable derivation state while retaining immutable parse products."""

    return {
        node.candidate_id: replace(
            node,
            closure_neighbors=set(node.closure_neighbors),
            trace_flags=set(node.trace_flags),
            bases=set(node.bases),
            lexical_score=(0, 0),
        )
        for node in catalog._nodes
    }


def discover_evidence_candidates(
    snapshot: RepositorySnapshot,
    report: Report,
    profile: ProfileConfig,
    obligation: ObligationRecord,
    settings: ObligationSettings,
    obligation_search_text: str = "",
    *,
    prepared_catalog: PreparedEvidenceCatalog | None = None,
    progress: OperationProgress | None = None,
    emit_progress: bool = True,
) -> tuple[EvidenceCandidate, ...]:
    """Build the complete deterministic candidate universe for one obligation."""

    catalog = prepared_catalog or prepare_evidence_catalog(
        snapshot,
        profile,
        settings,
        progress=progress,
        emit_progress=emit_progress,
    )
    if (
        catalog.snapshot_hash != snapshot.snapshot_hash
        or catalog.profile != profile
        or catalog.settings != settings
    ):
        raise ValueError("prepared evidence catalog authority mismatch")
    work = _WorkBudget(
        settings.maximum_work_units,
        progress=progress,
        emit_progress=emit_progress,
        used=catalog.base_work_units,
    )
    work.enter(
        "relations",
        current_identity=obligation.obligation_id,
        total_work_units=settings.maximum_work_units,
    )
    nodes = _catalog_nodes_for_obligation(catalog)
    conflict_issues = _add_issue_candidates(nodes, snapshot, report, obligation, work)
    if len(nodes) > settings.maximum_catalog_items:
        raise _budget_error("catalog_items", settings.maximum_catalog_items, len(nodes))
    invariant_declarations, invariant_binds, invariant_edges = _invariant_inputs(
        report, obligation, work
    )
    section_mappings, section_references = _section_inputs(report, obligation, work)
    declared = _project_declared_relations(
        nodes,
        report,
        obligation,
        conflict_issues,
        section_mappings,
        section_references,
        invariant_declarations,
        invariant_binds,
        invariant_edges,
        work,
    )
    static_edges = catalog._static_edges
    static = _static_relations(nodes, static_edges, work)
    obligation_tokens = _obligation_tokens(obligation, obligation_search_text)
    for node in nodes.values():
        if node.lexical_tokens is None:
            node.lexical_tokens = _candidate_tokens(node)
        shared = obligation_tokens.intersection(node.lexical_tokens)
        node.lexical_score = (
            len(shared),
            sum(len(token.encode("ascii")) for token in shared),
        )
    work.enter(
        "closure",
        current_identity=obligation.obligation_id,
        total_work_units=settings.maximum_work_units,
    )
    selected = _closure(nodes, static_edges, settings, work)
    work.enter(
        "candidate_detail",
        current_identity=obligation.obligation_id,
        total_work_units=settings.maximum_work_units,
    )

    def closed_static_relations(
        relations: Sequence[CandidateRelation],
    ) -> tuple[CandidateRelation, ...]:
        rows: list[CandidateRelation] = []
        for relation in relations:
            work.charge()
            if not (
                (
                    relation.source_candidate_id is None
                    or relation.source_candidate_id in selected
                )
                and (
                    relation.target_candidate_id is None
                    or relation.target_candidate_id in selected
                )
            ):
                continue
            rows.append(relation)
        return tuple(rows)

    candidates: list[EvidenceCandidate] = []
    for candidate_id in selected:
        node = nodes[candidate_id]
        work.checkpoint()
        candidates.append(
            EvidenceCandidate(
                candidate_id=node.candidate_id,
                candidate_kind=node.candidate_kind,
                path=node.path,
                owner=node.owner,
                start_line=node.start_line,
                end_line=node.end_line,
                structural_locator=node.structural_locator,
                receipt=node.receipt,
                discovery_bases=tuple(
                    basis for basis in _BASIS_ORDER if basis in node.bases
                ),
                lexical_score=node.lexical_score,
                static_relations=closed_static_relations(
                    static.get(node.candidate_id, ())
                ),
                declared_relations=declared.get(node.candidate_id, ()),
                trace_state=_trace_state(node),
                suggested_trace_edits=_advice(
                    node,
                    obligation,
                    invariant_declarations,
                ),
                _raw_span=lf_slice(
                    snapshot.read_bytes(node.path),
                    node.start_line,
                    node.end_line,
                    policy="clamped",
                ),
            )
        )
    candidates.sort(key=candidate_order)
    return tuple(candidates)


def get_candidate_by_id(
    candidates: Sequence[EvidenceCandidate], candidate_id: str
) -> EvidenceCandidate:
    matches = [item for item in candidates if item.candidate_id == candidate_id]
    if len(matches) != 1:
        raise KeyError(candidate_id)
    return matches[0]


def get_candidate_source(candidate: EvidenceCandidate) -> CandidateSource:
    text = candidate._raw_span.decode("utf-8", errors="replace")
    encoded = text.encode("utf-8")
    return CandidateSource(candidate.receipt, text, hashlib.sha256(encoded).hexdigest())


def candidates_for_source(
    candidates: Sequence[EvidenceCandidate], path: str
) -> tuple[EvidenceCandidate, ...]:
    return tuple(item for item in candidates if item.path == path)


def get_candidate_neighbors(
    candidate: EvidenceCandidate,
    candidates: Sequence[EvidenceCandidate],
) -> tuple[CandidateNeighbor, ...]:
    known = {item.candidate_id for item in candidates}
    rows: set[CandidateNeighbor] = set()
    for relation in (*candidate.static_relations, *candidate.declared_relations):
        if (
            relation.source_candidate_id == candidate.candidate_id
            and relation.target_candidate_id in known
        ):
            assert relation.target_candidate_id is not None
            rows.add(
                CandidateNeighbor(
                    relation.target_candidate_id,
                    relation.relation_kind,
                    "outgoing",
                )
            )
        if (
            relation.target_candidate_id == candidate.candidate_id
            and relation.source_candidate_id in known
        ):
            assert relation.source_candidate_id is not None
            rows.add(
                CandidateNeighbor(
                    relation.source_candidate_id,
                    relation.relation_kind,
                    "incoming",
                )
            )
    return tuple(
        sorted(
            rows,
            key=lambda item: (item.relation_kind, item.direction, item.candidate_id),
        )
    )


# Public evaluation-boundary aliases. Product evaluation may reuse these
# deterministic mechanics without importing private implementation names.
WorkBudget = _WorkBudget
catalog_python = _catalog_python
add_issue_candidates = _add_issue_candidates
