"""Snapshot-backed summaries of source-declared obligation evidence.

This module projects declarations already accepted by the deterministic
resolver.  It never opens repository paths and never upgrades a declaration's
authority.

Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-4.1], [EVC-8.3]
"""

from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import Any

from backstitch.canonical import canonical_json_bytes, lf_line_count, lf_slice
from backstitch.code_parser import Definition, parse_python_source
from backstitch.config import ProfileConfig
from backstitch.grammar import is_sha256_hex
from backstitch.models import Edge, Report, SpecMapping
from backstitch.obligations import (
    ObligationRecord,
    associate_mapping_declaration_indexes,
)
from backstitch.repository_snapshot import RepositorySnapshot

_RELATION_ORDER = {
    "spec_mapping": 0,
    "code_backlink": 1,
    "invariant_declaration": 2,
    "invariant_bind": 3,
    "binding_test": 4,
}
_ROLE_ORDER = {"implementation": 0, "test": 1, "binding_test": 2}
_SUMMARY_LOCATOR_KINDS = {
    "markdown-section",
    "python-file",
    "python-module",
    "python-definition",
    "source-declaration",
}


def _is_under(path: str, roots: Sequence[str]) -> bool:
    pure = PurePosixPath(path)
    return any(pure.is_relative_to(PurePosixPath(root)) for root in roots)


def _role(path: str, profile: ProfileConfig) -> str:
    return "test" if _is_under(path, profile.test_roots) else "implementation"


def _canonical_nonnegative_decimal(value: str) -> bool:
    return value.isascii() and value.isdigit() and str(int(value)) == value


def _valid_summary_locator(value: str) -> bool:
    if unicodedata.normalize("NFC", value) != value:
        return False
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        return False
    kind, separator, remainder = value.partition(":")
    if separator != ":" or kind not in _SUMMARY_LOCATOR_KINDS:
        return False
    if kind in {"markdown-section", "python-module"}:
        return bool(remainder) and ":" not in remainder
    if kind == "python-file":
        return is_sha256_hex(remainder)
    if kind == "python-definition":
        try:
            qualname, node_kind, ordinal = remainder.rsplit(":", 2)
        except ValueError:
            return False
        return (
            bool(qualname)
            and ":" not in qualname
            and node_kind in {"class", "function", "async-function"}
            and _canonical_nonnegative_decimal(ordinal)
        )
    try:
        relation_kind, line, ordinal = remainder.split(":")
    except ValueError:
        return False
    return (
        relation_kind in _RELATION_ORDER
        and _canonical_nonnegative_decimal(line)
        and int(line) > 0
        and _canonical_nonnegative_decimal(ordinal)
    )


def _receipt(
    *,
    path: str,
    structural_locator: str,
    start_line: int,
    end_line: int,
    raw: bytes,
) -> tuple[dict[str, object], str]:
    if not _valid_summary_locator(structural_locator):
        raise AssertionError(
            f"invalid closed structural locator: {structural_locator!r}"
        )
    span = lf_slice(raw, start_line, end_line, policy="clamped")
    row = {
        "receipt_version": 1,
        "path": path,
        "structural_locator": structural_locator,
        "start_line": start_line,
        "end_line": end_line,
        "raw_sha256": hashlib.sha256(span).hexdigest(),
    }
    return row, span.decode("utf-8", errors="replace")


def _definition_locator(definition: Definition, ordinal: int) -> str:
    kind = definition.kind
    qualname = unicodedata.normalize("NFC", definition.qualname)
    return f"python-definition:{qualname}:{kind}:{ordinal}"


def _python_atom(
    snapshot: RepositorySnapshot,
    profile: ProfileConfig,
    path: str,
    symbol: str | None,
    *,
    owner_line: int | None = None,
) -> tuple[str | None, int, int, dict[str, object], str] | None:
    try:
        raw = snapshot.read_bytes(path)
    except (KeyError, OSError):
        return None
    if PurePosixPath(path).suffix != ".py":
        return None
    try:
        parsed = parse_python_source(raw)
    except UnicodeDecodeError:
        return None
    if not parsed.parse_ok:
        return None
    if symbol in {None, "module", "<module>"}:
        end_line = max(1, lf_line_count(raw))
        path_hash = hashlib.sha256(
            unicodedata.normalize("NFC", path).encode("utf-8")
        ).hexdigest()
        locator = f"python-file:{path_hash}"
        receipt, excerpt = _receipt(
            path=path,
            structural_locator=locator,
            start_line=1,
            end_line=end_line,
            raw=raw,
        )
        owner = "module" if symbol in {"module", "<module>"} else None
        return owner, 1, end_line, receipt, excerpt

    normalized_symbol = unicodedata.normalize("NFC", symbol)
    matches = [
        item
        for item in parsed.definitions
        if unicodedata.normalize("NFC", item.qualname) == normalized_symbol
    ]
    if owner_line is None:
        if len(matches) != 1:
            return None
        definition = matches[0]
    else:
        containing = [
            item
            for item in matches
            if item.attachment_line <= owner_line <= item.end_line
        ]
        if len(containing) == 1:
            definition = containing[0]
        else:
            following = sorted(
                (item for item in matches if item.attachment_line >= owner_line),
                key=lambda item: item.attachment_line,
            )
            if not following or (
                len(following) > 1
                and following[0].attachment_line == following[1].attachment_line
            ):
                return None
            definition = following[0]
    same = [
        item
        for item in parsed.definitions
        if unicodedata.normalize("NFC", item.qualname) == normalized_symbol
        and item.kind == definition.kind
    ]
    ordinal = same.index(definition)
    start_line = definition.attachment_line
    end_line = definition.end_line
    receipt, excerpt = _receipt(
        path=path,
        structural_locator=_definition_locator(definition, ordinal),
        start_line=start_line,
        end_line=end_line,
        raw=raw,
    )
    return normalized_symbol, start_line, end_line, receipt, excerpt


def _mapping_covers(mapping: Edge, backlink: Edge) -> bool:
    path_matches = (
        backlink.code_path == mapping.code_path
        or backlink.code_path.startswith(mapping.code_path.rstrip("/") + "/")
    )
    return path_matches and (
        mapping.code_symbol is None or mapping.code_symbol == backlink.code_symbol
    )


def _associate_edge_declarations(
    mappings: Sequence[SpecMapping], edges: Sequence[Edge]
) -> tuple[SpecMapping | None, ...]:
    indexes = associate_mapping_declaration_indexes(mappings, edges)
    return tuple(mappings[index] if index is not None else None for index in indexes)


def _mapping_line_atom(
    snapshot: RepositorySnapshot,
    mapping: SpecMapping,
    *,
    relation_kind: str,
    ordinal: int,
) -> tuple[str | None, int, int, dict[str, object], str] | None:
    try:
        raw = snapshot.read_bytes(mapping.spec_path)
    except (KeyError, OSError):
        return None
    receipt, excerpt = _receipt(
        path=mapping.spec_path,
        structural_locator=(
            f"source-declaration:{relation_kind}:{mapping.line}:{ordinal}"
        ),
        start_line=mapping.line,
        end_line=mapping.line,
        raw=raw,
    )
    return mapping.section_id, mapping.line, mapping.line, receipt, excerpt


def _declaration_row(
    snapshot: RepositorySnapshot,
    *,
    relation_kind: str,
    path: str,
    line: int,
    ordinal: int,
    declared_target: str | None = None,
) -> dict[str, object] | None:
    try:
        raw = snapshot.read_bytes(path)
    except (KeyError, OSError):
        return None
    receipt, _excerpt = _receipt(
        path=path,
        structural_locator=(f"source-declaration:{relation_kind}:{line}:{ordinal}"),
        start_line=line,
        end_line=line,
        raw=raw,
    )
    return {
        "relation_kind": relation_kind,
        "path": path,
        "line": line,
        "receipt": receipt,
        "declared_target": declared_target,
    }


def _source_declaration_ordinal(
    items: Sequence[object],
    current: object,
    *,
    path_attr: str,
    line_attr: str,
    path: str,
    line: int,
) -> int:
    ordinal = 0
    for item in items:
        if item is current:
            return ordinal
        if getattr(item, path_attr) == path and getattr(item, line_attr) == line:
            ordinal += 1
    raise AssertionError("source declaration is absent from its parser-owned sequence")


def _row(
    *,
    role: str,
    path: str,
    symbol: str | None,
    owner: str | None,
    start_line: int,
    end_line: int,
    relation_kinds: Sequence[str],
    reciprocity_state: str,
    receipt: dict[str, object],
    excerpt: str,
    declared_target: str | None = None,
    declarations: Sequence[dict[str, object]] = (),
) -> dict[str, object]:
    symbol = unicodedata.normalize("NFC", symbol) if symbol is not None else None
    owner = unicodedata.normalize("NFC", owner) if owner is not None else None
    return {
        "role": role,
        "path": path,
        "symbol": symbol,
        "owner": owner,
        "start_line": start_line,
        "end_line": end_line,
        "relation_kinds": sorted(set(relation_kinds), key=_RELATION_ORDER.__getitem__),
        "reciprocity_state": reciprocity_state,
        "receipt": receipt,
        "excerpt": excerpt,
        "declared_target": declared_target,
        "declarations": sorted(
            declarations,
            key=_declaration_order,
        ),
    }


def _declaration_order(item: dict[str, object]) -> tuple[object, ...]:
    receipt = item["receipt"]
    assert isinstance(receipt, dict)
    return (
        _RELATION_ORDER[str(item["relation_kind"])],
        str(item["path"]),
        int(str(item["line"])),
        str(item["declared_target"] or ""),
        str(receipt["structural_locator"]),
    )


def _merge_declarations(
    left: Sequence[dict[str, object]], right: Sequence[dict[str, object]]
) -> list[dict[str, object]]:
    by_identity: dict[bytes, dict[str, object]] = {}
    for declaration in (*left, *right):
        identity = canonical_json_bytes(declaration)
        by_identity.setdefault(identity, declaration)
    return sorted(by_identity.values(), key=_declaration_order)


def _section_items(
    report: Report,
    obligation: ObligationRecord,
    snapshot: RepositorySnapshot,
    profile: ProfileConfig,
) -> list[dict[str, object]]:
    spec_path, section_id = obligation.obligation_id.rsplit("#", 1)
    mappings = [
        item
        for item in report.spec_mappings
        if item.spec_path == spec_path and item.section_id == section_id
    ]
    mapping_edges = [
        item
        for item in report.edges
        if item.kind == "mapping"
        and item.spec_path == spec_path
        and item.section_id == section_id
    ]
    backlinks = [
        item
        for item in report.edges
        if item.kind == "backlink"
        and item.spec_path == spec_path
        and item.section_id == section_id
    ]
    rows: list[dict[str, object]] = []
    matched_mapping_edge_indexes: set[int] = set()
    matched_backlinks: set[Edge] = set()
    declaration_by_edge_index = _associate_edge_declarations(mappings, mapping_edges)
    resolved_mappings = {
        declaration
        for declaration in declaration_by_edge_index
        if declaration is not None
    }

    for backlink in backlinks:
        matching = [
            (index, item)
            for index, item in enumerate(mapping_edges)
            if _mapping_covers(item, backlink)
        ]
        if not matching:
            continue
        atom = _python_atom(
            snapshot,
            profile,
            backlink.code_path,
            backlink.code_symbol,
            owner_line=backlink.line,
        )
        if atom is None:
            continue
        matched_backlinks.add(backlink)
        matched_mapping_edge_indexes.update(index for index, _edge in matching)
        owner, start, end, receipt, excerpt = atom
        declaration_rows: list[dict[str, object]] = []
        for index, _edge in matching:
            declaration = declaration_by_edge_index[index]
            if declaration is None:
                continue
            declaration_row = _declaration_row(
                snapshot,
                relation_kind="spec_mapping",
                path=declaration.spec_path,
                line=declaration.line,
                ordinal=_source_declaration_ordinal(
                    mappings,
                    declaration,
                    path_attr="spec_path",
                    line_attr="line",
                    path=declaration.spec_path,
                    line=declaration.line,
                ),
                declared_target=declaration.target,
            )
            if declaration_row is not None:
                declaration_rows.append(declaration_row)
        backlink_declaration = _declaration_row(
            snapshot,
            relation_kind="code_backlink",
            path=backlink.code_path,
            line=backlink.line,
            ordinal=_source_declaration_ordinal(
                backlinks,
                backlink,
                path_attr="code_path",
                line_attr="line",
                path=backlink.code_path,
                line=backlink.line,
            ),
        )
        if backlink_declaration is not None:
            declaration_rows.append(backlink_declaration)
        rows.append(
            _row(
                role=_role(backlink.code_path, profile),
                path=backlink.code_path,
                symbol=backlink.code_symbol,
                owner=owner,
                start_line=start,
                end_line=end,
                relation_kinds=("spec_mapping", "code_backlink"),
                reciprocity_state="complete",
                receipt=receipt,
                excerpt=excerpt,
                declarations=declaration_rows,
            )
        )

    for edge_index, edge in enumerate(mapping_edges):
        if edge_index in matched_mapping_edge_indexes:
            continue
        atom = _python_atom(
            snapshot,
            profile,
            edge.code_path,
            edge.code_symbol,
        )
        declaration = declaration_by_edge_index[edge_index]
        declaration_fallback = atom is None and declaration is not None
        if atom is None:
            atom = (
                _mapping_line_atom(
                    snapshot,
                    declaration,
                    relation_kind="spec_mapping",
                    ordinal=_source_declaration_ordinal(
                        mappings,
                        declaration,
                        path_attr="spec_path",
                        line_attr="line",
                        path=declaration.spec_path,
                        line=declaration.line,
                    ),
                )
                if declaration is not None
                else None
            )
        if atom is None:
            continue
        owner, start, end, receipt, excerpt = atom
        source_path = edge.code_path
        source_symbol = edge.code_symbol
        if declaration_fallback:
            assert declaration is not None
            source_path = declaration.spec_path
            source_symbol = declaration.section_id
        rows.append(
            _row(
                role=_role(edge.code_path, profile),
                path=source_path,
                symbol=source_symbol,
                owner=owner,
                start_line=start,
                end_line=end,
                relation_kinds=("spec_mapping",),
                reciprocity_state="one_sided",
                receipt=receipt,
                excerpt=excerpt,
                declared_target=(
                    declaration.target if declaration is not None else None
                ),
                declarations=tuple(
                    row
                    for row in (
                        _declaration_row(
                            snapshot,
                            relation_kind="spec_mapping",
                            path=declaration.spec_path,
                            line=declaration.line,
                            ordinal=_source_declaration_ordinal(
                                mappings,
                                declaration,
                                path_attr="spec_path",
                                line_attr="line",
                                path=declaration.spec_path,
                                line=declaration.line,
                            ),
                            declared_target=declaration.target,
                        )
                        if declaration is not None
                        else None,
                    )
                    if row is not None
                ),
            )
        )

    for mapping in mappings:
        if mapping in resolved_mappings:
            continue
        atom = _mapping_line_atom(
            snapshot,
            mapping,
            relation_kind="spec_mapping",
            ordinal=_source_declaration_ordinal(
                mappings,
                mapping,
                path_attr="spec_path",
                line_attr="line",
                path=mapping.spec_path,
                line=mapping.line,
            ),
        )
        if atom is None:
            continue
        owner, start, end, receipt, excerpt = atom
        rows.append(
            _row(
                role=(
                    _role(mapping.target_path, profile)
                    if mapping.target_path is not None
                    else "implementation"
                ),
                path=mapping.spec_path,
                symbol=mapping.section_id,
                owner=owner,
                start_line=start,
                end_line=end,
                relation_kinds=("spec_mapping",),
                reciprocity_state="one_sided",
                receipt=receipt,
                excerpt=excerpt,
                declared_target=mapping.target,
                declarations=tuple(
                    row
                    for row in (
                        _declaration_row(
                            snapshot,
                            relation_kind="spec_mapping",
                            path=mapping.spec_path,
                            line=mapping.line,
                            ordinal=_source_declaration_ordinal(
                                mappings,
                                mapping,
                                path_attr="spec_path",
                                line_attr="line",
                                path=mapping.spec_path,
                                line=mapping.line,
                            ),
                            declared_target=mapping.target,
                        ),
                    )
                    if row is not None
                ),
            )
        )

    for backlink in backlinks:
        if backlink in matched_backlinks:
            continue
        atom = _python_atom(
            snapshot,
            profile,
            backlink.code_path,
            backlink.code_symbol,
            owner_line=backlink.line,
        )
        if atom is None:
            continue
        owner, start, end, receipt, excerpt = atom
        rows.append(
            _row(
                role=_role(backlink.code_path, profile),
                path=backlink.code_path,
                symbol=backlink.code_symbol,
                owner=owner,
                start_line=start,
                end_line=end,
                relation_kinds=("code_backlink",),
                reciprocity_state="one_sided",
                receipt=receipt,
                excerpt=excerpt,
                declarations=tuple(
                    row
                    for row in (
                        _declaration_row(
                            snapshot,
                            relation_kind="code_backlink",
                            path=backlink.code_path,
                            line=backlink.line,
                            ordinal=_source_declaration_ordinal(
                                backlinks,
                                backlink,
                                path_attr="code_path",
                                line_attr="line",
                                path=backlink.code_path,
                                line=backlink.line,
                            ),
                        ),
                    )
                    if row is not None
                ),
            )
        )
    return rows


def _invariant_items(
    report: Report,
    obligation: ObligationRecord,
    snapshot: RepositorySnapshot,
    profile: ProfileConfig,
) -> list[dict[str, object]]:
    invariant_id = obligation.obligation_id.removeprefix("invariant::")
    declarations = [
        item for item in report.invariants if item.invariant_id == invariant_id
    ]
    binds = [item for item in report.binds if item.invariant_id == invariant_id]
    rows: list[dict[str, object]] = []
    targets: list[tuple[str, str | None, tuple[str, ...], SpecMapping | None]] = []
    rejected_mappings: list[SpecMapping] = []
    for declaration in declarations:
        if declaration.declaration_kind == "code":
            targets.append(
                (
                    declaration.path,
                    declaration.owner_symbol,
                    ("invariant_declaration", "invariant_bind"),
                    None,
                )
            )
            continue
        if declaration.section_id is None:
            continue
        declaration_mappings = [
            mapping
            for mapping in report.spec_mappings
            if mapping.spec_path == declaration.path
            and mapping.section_id == declaration.section_id
        ]
        declaration_edges = [
            edge
            for edge in report.edges
            if edge.kind == "mapping"
            and edge.spec_path == declaration.path
            and edge.section_id == declaration.section_id
        ]
        associated_mappings: set[SpecMapping] = set()
        edge_declarations = _associate_edge_declarations(
            declaration_mappings, declaration_edges
        )
        for edge, mapping in zip(declaration_edges, edge_declarations, strict=True):
            if mapping is not None:
                associated_mappings.add(mapping)
            if _role(edge.code_path, profile) != "implementation":
                if mapping is not None:
                    rejected_mappings.append(mapping)
                continue
            targets.append(
                (
                    edge.code_path,
                    edge.code_symbol,
                    ("invariant_bind",),
                    mapping,
                )
            )
        rejected_mappings.extend(
            mapping
            for mapping in declaration_mappings
            if mapping not in associated_mappings
        )
    unique_targets = tuple(
        dict.fromkeys(
            sorted(
                targets,
                key=lambda item: (
                    item[0],
                    item[1] or "",
                    item[2],
                    item[3].line if item[3] else -1,
                ),
            )
        )
    )
    target_atoms: list[
        tuple[
            str,
            str | None,
            tuple[str, ...],
            SpecMapping | None,
            tuple[str | None, int, int, dict[str, object], str],
        ]
    ] = []
    for path, symbol, relation_kinds, mapping in unique_targets:
        code_declaration = next(
            (
                declaration
                for declaration in declarations
                if declaration.declaration_kind == "code"
                and declaration.path == path
                and declaration.owner_symbol == symbol
            ),
            None,
        )
        atom = _python_atom(
            snapshot,
            profile,
            path,
            symbol,
            owner_line=(code_declaration.line if code_declaration else None),
        )
        if atom is None:
            if mapping is not None:
                rejected_mappings.append(mapping)
            continue
        target_atoms.append((path, symbol, relation_kinds, mapping, atom))

    bind_atoms = [
        (bind, atom)
        for bind in binds
        if (
            atom := _python_atom(
                snapshot,
                profile,
                bind.test_path,
                bind.test_symbol,
                owner_line=bind.start_line,
            )
        )
        is not None
    ]
    complete = bool(target_atoms and bind_atoms)
    for path, symbol, relation_kinds, mapping, atom in target_atoms:
        owner, start, end, receipt, excerpt = atom
        code_declaration = next(
            (
                declaration
                for declaration in declarations
                if declaration.declaration_kind == "code"
                and declaration.path == path
                and declaration.owner_symbol == symbol
            ),
            None,
        )
        declaration_rows = tuple(
            row
            for row in (
                _declaration_row(
                    snapshot,
                    relation_kind="invariant_bind",
                    path=mapping.spec_path,
                    line=mapping.line,
                    ordinal=_source_declaration_ordinal(
                        report.spec_mappings,
                        mapping,
                        path_attr="spec_path",
                        line_attr="line",
                        path=mapping.spec_path,
                        line=mapping.line,
                    ),
                    declared_target=mapping.target,
                )
                if mapping is not None
                else (
                    _declaration_row(
                        snapshot,
                        relation_kind="invariant_declaration",
                        path=code_declaration.path,
                        line=code_declaration.line,
                        ordinal=_source_declaration_ordinal(
                            declarations,
                            code_declaration,
                            path_attr="path",
                            line_attr="line",
                            path=code_declaration.path,
                            line=code_declaration.line,
                        ),
                    )
                    if code_declaration is not None
                    else None
                ),
            )
            if row is not None
        )
        rows.append(
            _row(
                role="implementation",
                path=path,
                symbol=symbol,
                owner=owner,
                start_line=start,
                end_line=end,
                relation_kinds=relation_kinds,
                reciprocity_state="complete" if complete else "one_sided",
                receipt=receipt,
                excerpt=excerpt,
                declared_target=(mapping.target if mapping is not None else None),
                declarations=declaration_rows,
            )
        )
    for mapping in dict.fromkeys(rejected_mappings):
        atom = _mapping_line_atom(
            snapshot,
            mapping,
            relation_kind="invariant_bind",
            ordinal=_source_declaration_ordinal(
                report.spec_mappings,
                mapping,
                path_attr="spec_path",
                line_attr="line",
                path=mapping.spec_path,
                line=mapping.line,
            ),
        )
        if atom is None:
            continue
        owner, start, end, receipt, excerpt = atom
        rows.append(
            _row(
                role="implementation",
                path=mapping.spec_path,
                symbol=mapping.section_id,
                owner=owner,
                start_line=start,
                end_line=end,
                relation_kinds=("invariant_bind",),
                reciprocity_state="one_sided",
                receipt=receipt,
                excerpt=excerpt,
                declared_target=mapping.target,
                declarations=tuple(
                    row
                    for row in (
                        _declaration_row(
                            snapshot,
                            relation_kind="invariant_bind",
                            path=mapping.spec_path,
                            line=mapping.line,
                            ordinal=_source_declaration_ordinal(
                                report.spec_mappings,
                                mapping,
                                path_attr="spec_path",
                                line_attr="line",
                                path=mapping.spec_path,
                                line=mapping.line,
                            ),
                            declared_target=mapping.target,
                        ),
                    )
                    if row is not None
                ),
            )
        )
    for bind, atom in bind_atoms:
        owner, start, end, receipt, excerpt = atom
        rows.append(
            _row(
                role="binding_test",
                path=bind.test_path,
                symbol=bind.test_symbol,
                owner=owner,
                start_line=start,
                end_line=end,
                relation_kinds=("binding_test",),
                reciprocity_state="complete" if complete else "one_sided",
                receipt=receipt,
                excerpt=excerpt,
                declarations=tuple(
                    row
                    for row in (
                        _declaration_row(
                            snapshot,
                            relation_kind="binding_test",
                            path=bind.test_path,
                            line=bind.marker_line,
                            ordinal=_source_declaration_ordinal(
                                binds,
                                bind,
                                path_attr="test_path",
                                line_attr="marker_line",
                                path=bind.test_path,
                                line=bind.marker_line,
                            ),
                        ),
                    )
                    if row is not None
                ),
            )
        )
    return rows


def evidence_item_order(row: dict[str, Any]) -> tuple[object, ...]:
    """Canonical public ordering and pagination tuple."""

    relation_kinds = row["relation_kinds"]
    assert isinstance(relation_kinds, list)
    return (
        _ROLE_ORDER[str(row["role"])],
        row["path"],
        row["start_line"],
        row["end_line"],
        row["symbol"] or "",
        tuple(relation_kinds),
        row.get("declared_target") or "",
    )


def build_evidence_summary_items(
    report: Report,
    obligation: ObligationRecord,
    snapshot: RepositorySnapshot,
    profile: ProfileConfig,
) -> tuple[dict[str, object], ...]:
    """Return exact declared evidence rows from one captured report/view."""

    if obligation.kind == "section":
        rows = _section_items(report, obligation, snapshot, profile)
    else:
        rows = _invariant_items(report, obligation, snapshot, profile)
    rows.sort(key=evidence_item_order)
    merged: dict[tuple[object, ...], dict[str, object]] = {}
    for row in rows:
        order = evidence_item_order(row)
        existing = merged.get(order)
        if existing is None:
            merged[order] = row
            continue
        comparable_existing = {**existing, "declarations": []}
        comparable_row = {**row, "declarations": []}
        for comparable in (comparable_existing, comparable_row):
            receipt = comparable["receipt"]
            assert isinstance(receipt, dict)
            # Same-line duplicate declarations have distinct source ordinals,
            # but identify one evidence atom whose declaration receipts merge.
            comparable["receipt"] = {**receipt, "structural_locator": None}
        if comparable_existing != comparable_row:
            raise AssertionError("evidence order aliases distinct evidence atoms")
        left = existing["declarations"]
        right = row["declarations"]
        assert isinstance(left, list) and isinstance(right, list)
        existing["declarations"] = _merge_declarations(left, right)
    return tuple(merged.values())
