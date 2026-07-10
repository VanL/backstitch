"""Bounded semantic-review packet generation from deterministic results.

Spec: docs/specs/02-backstitch-core.md [SC-6], [SC-7]
Spec: docs/specs/05-backstitch-invariants.md [INV-5], [INV-6]

Packets are the semantic review boundary: the model judges only what a
packet contains and never roams the repository [SC-7]. Generation is
deterministic and never calls ``llm``.
"""

from __future__ import annotations

import dataclasses
import json
from importlib import resources
from pathlib import Path
from typing import Any, Literal

from backstitch.artifact_contracts import invariant_content_hash
from backstitch.config import ProfileConfig, resolve_profile_root
from backstitch.models import InvariantBind, Report, SpecSection
from backstitch.python_refs import python_symbol_spans
from backstitch.resolver import scan_repository

MAX_SNIPPET_LINES = 120
MAX_OWNERS_PER_PACKET = 8
MAX_SECTION_LINES = 100
MAX_INVARIANT_TARGETS_PER_PACKET = 8
MAX_BINDING_TESTS_PER_PACKET = 8
PacketKind = Literal["section", "invariant", "all"]


def _section_instructions() -> str:
    return (
        resources.files("backstitch") / "prompts" / "backstitch_style_analysis.md"
    ).read_text(encoding="utf-8")


def _invariant_instructions() -> str:
    return (
        resources.files("backstitch") / "prompts" / "invariant_binding_analysis.md"
    ).read_text(encoding="utf-8")


def _is_test_path(repo_root: Path, path: str, test_roots: tuple[str, ...]) -> bool:
    candidate = (repo_root / path).resolve()
    for value in test_roots:
        root = resolve_profile_root(repo_root, value)
        if candidate == root or candidate.is_relative_to(root):
            return True
    return False


def _section_text(
    section: SpecSection,
    file_lines: list[str],
    siblings: list[SpecSection],
    warnings: list[str],
) -> str:
    if section.kind != "heading":
        line = file_lines[section.line - 1] if section.line <= len(file_lines) else ""
        return line.strip()
    next_headings = [
        s.line for s in siblings if s.kind == "heading" and s.line > section.line
    ]
    end = min(next_headings) - 1 if next_headings else len(file_lines)
    block = file_lines[section.line - 1 : end]
    if len(block) > MAX_SECTION_LINES:
        block = block[:MAX_SECTION_LINES]
        warnings.append(f"section text truncated to {MAX_SECTION_LINES} lines")
    return "\n".join(block).rstrip()


def _owner_snippet(
    repo_root: Path,
    path: str,
    symbol: str | None,
    warnings: list[str],
    *,
    fallback_to_file_head: bool = True,
) -> tuple[str, int]:
    target = repo_root / path
    if not target.is_file():
        warnings.append(f"owner `{path}` is not a file; no snippet included")
        return "", 1
    try:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        warnings.append(f"owner `{path}` could not be read ({exc})")
        return "", 1
    start = 1
    if symbol == "<module>":
        pass
    elif symbol is not None and path.endswith(".py"):
        spans = python_symbol_spans(target)
        span = spans.get(symbol) if spans else None
        if span is not None:
            start, end = span
            lines = lines[start - 1 : end]
        else:
            suffix = "; using file head" if fallback_to_file_head else ""
            warnings.append(f"symbol `{symbol}` not found in `{path}`{suffix}")
            if not fallback_to_file_head:
                lines = []
    if not lines:
        if not any(f"`{path}`" in warning for warning in warnings):
            warnings.append(f"owner `{path}` has no readable snippet content")
        return "", start
    if len(lines) > MAX_SNIPPET_LINES:
        lines = lines[:MAX_SNIPPET_LINES]
        warnings.append(f"snippet for `{path}` truncated to {MAX_SNIPPET_LINES} lines")
    return "\n".join(lines), start


def _snippet_record(
    repo_root: Path,
    path: str,
    symbol: str | None,
    warnings: list[str],
) -> dict[str, Any]:
    snippet, start_line = _owner_snippet(
        repo_root,
        path,
        symbol,
        warnings,
        fallback_to_file_head=False,
    )
    return {
        "path": path,
        "symbol": symbol,
        "start_line": start_line,
        "snippet": snippet,
    }


def _bounded_snippet_records(
    repo_root: Path,
    keys: set[tuple[str, str | None]],
    cap: int,
    label: str,
    warnings: list[str],
) -> list[dict[str, Any]]:
    ordered = sorted(keys, key=lambda item: (item[0], item[1] or ""))
    if len(ordered) > cap:
        warnings.append(f"{len(ordered) - cap} additional {label} omitted")
        ordered = ordered[:cap]
    records = [
        _snippet_record(repo_root, path, symbol, warnings) for path, symbol in ordered
    ]
    records.sort(
        key=lambda item: (
            item["path"],
            item["symbol"] or "",
            item["start_line"],
        )
    )
    return records


def _generate_section_packets(
    repo_root: Path,
    profile: ProfileConfig,
    report: Report,
) -> list[dict[str, Any]]:
    """Generate one section packet for each spec section with resolved edges."""

    instructions = _section_instructions()

    sections_by_file: dict[str, list[SpecSection]] = {}
    for section in report.spec_sections:
        sections_by_file.setdefault(section.path, []).append(section)

    spec_lines: dict[str, list[str]] = {}
    for path in sections_by_file:
        spec_lines[path] = (
            (repo_root / path)
            .read_text(encoding="utf-8", errors="replace")
            .splitlines()
        )

    edges_by_key: dict[tuple[str, str], list] = {}
    for edge in report.edges:
        edges_by_key.setdefault((edge.spec_path, edge.section_id), []).append(edge)

    packets: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    for section in report.spec_sections:
        key = (section.path, section.section_id)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        edges = edges_by_key.get(key, [])
        if not edges:
            continue

        warnings: list[str] = []
        owner_keys: list[tuple[str, str | None]] = []
        tests: list[str] = []
        for edge in edges:
            if _is_test_path(repo_root, edge.code_path, profile.test_roots):
                if edge.code_path not in tests:
                    tests.append(edge.code_path)
                continue
            symbol = edge.code_symbol
            if edge.kind == "backlink" and symbol == "module":
                symbol = None
            owner_key = (edge.code_path, symbol)
            if owner_key not in owner_keys:
                owner_keys.append(owner_key)

        if len(owner_keys) > MAX_OWNERS_PER_PACKET:
            omitted = len(owner_keys) - MAX_OWNERS_PER_PACKET
            owner_keys = owner_keys[:MAX_OWNERS_PER_PACKET]
            warnings.append(f"{omitted} additional owners omitted")

        owners = []
        for path, symbol in owner_keys:
            snippet, start_line = _owner_snippet(repo_root, path, symbol, warnings)
            owners.append(
                {
                    "path": path,
                    "symbol": symbol,
                    "start_line": start_line,
                    "snippet": snippet,
                }
            )

        owner_paths = {path for path, _ in owner_keys}
        issues = [
            dataclasses.asdict(issue)
            for issue in report.issues
            if issue.section_id == section.section_id
            and (
                issue.path == section.path
                or issue.path in owner_paths
                or issue.path in tests
            )
        ]

        packets.append(
            {
                "packet_id": f"{section.path}#{section.section_id}",
                "kind": "section",
                "spec_path": section.path,
                "section_id": section.section_id,
                "title": section.title,
                "section_text": _section_text(
                    section,
                    spec_lines[section.path],
                    sections_by_file[section.path],
                    warnings,
                ),
                # [SC-6]: the section's starting line anchors evidence
                # line-locality checks against the shown section text.
                "section_start_line": section.line,
                "owners": owners,
                "tests": tests,
                "issues": issues,
                # [SC-6] field name is contractual: consumers look for
                # `packet_warnings` for truncation/omission context.
                "packet_warnings": warnings,
                "instructions": instructions,
            }
        )
    return packets


def _invariant_issue_rows(
    report: Report,
    invariant_id: str,
) -> list[dict[str, Any]]:
    issues = [issue for issue in report.issues if issue.invariant_id == invariant_id]
    issues.sort(
        key=lambda issue: (
            issue.path,
            issue.line is not None,
            issue.line or 0,
            issue.code,
            issue.message,
        )
    )
    return [dataclasses.asdict(issue) for issue in issues]


def _generate_invariant_packets(
    repo_root: Path,
    report: Report,
) -> list[dict[str, Any]]:
    """Generate one bounded packet for each invariant with a valid bind."""

    mappings_by_section: dict[tuple[str, str], set[tuple[str, str | None]]] = {}
    for edge in report.edges:
        if edge.kind != "mapping":
            continue
        key = (edge.spec_path, edge.section_id)
        mappings_by_section.setdefault(key, set()).add(
            (edge.code_path, edge.code_symbol)
        )

    binds_by_invariant: dict[str, list[InvariantBind]] = {}
    for bind in report.binds:
        binds_by_invariant.setdefault(bind.invariant_id, []).append(bind)

    packets: list[dict[str, Any]] = []
    instructions = _invariant_instructions()
    for declaration in report.invariants:
        binds = binds_by_invariant.get(declaration.invariant_id, [])
        if not binds:
            continue

        warnings: list[str] = []
        if declaration.declaration_kind == "code":
            target_keys = {(declaration.path, declaration.owner_symbol)}
        else:
            target_keys = mappings_by_section.get(
                (declaration.path, declaration.section_id or ""),
                set(),
            )
            if not target_keys:
                warnings.append("no target code resolved for spec-declared invariant")

        targets = _bounded_snippet_records(
            repo_root,
            target_keys,
            MAX_INVARIANT_TARGETS_PER_PACKET,
            "targets",
            warnings,
        )
        binding_tests = _bounded_snippet_records(
            repo_root,
            {(bind.test_path, bind.test_symbol) for bind in binds},
            MAX_BINDING_TESTS_PER_PACKET,
            "binding tests",
            warnings,
        )
        packet: dict[str, Any] = {
            "packet_id": f"invariant::{declaration.invariant_id}",
            "kind": "invariant",
            "invariant_id": declaration.invariant_id,
            "tier": declaration.tier,
            "statement": declaration.statement,
            "declaration": {
                "kind": declaration.declaration_kind,
                "path": declaration.path,
                "line": declaration.line,
                "symbol": declaration.owner_symbol,
                "section_id": declaration.section_id,
            },
            "targets": targets,
            "binding_tests": binding_tests,
            "issues": _invariant_issue_rows(report, declaration.invariant_id),
            "packet_warnings": warnings,
            "instructions": instructions,
        }
        packet["content_hash"] = invariant_content_hash(
            declaration.statement,
            targets,
            binding_tests,
        )
        packets.append(packet)
    return packets


def generate_packets(
    repo_root: Path,
    profile: ProfileConfig,
    report: Report | None = None,
    *,
    kind: PacketKind = "section",
) -> list[dict[str, Any]]:
    """Generate deterministic section, invariant, or mixed review packets."""

    root = repo_root.resolve()
    if report is None:
        report = scan_repository(root, profile)
    if kind == "section":
        return _generate_section_packets(root, profile, report)
    if kind == "invariant":
        return _generate_invariant_packets(root, report)
    if kind == "all":
        return [
            *_generate_section_packets(root, profile, report),
            *_generate_invariant_packets(root, report),
        ]
    raise ValueError(f"unknown packet kind: {kind}")


def render_packets_jsonl(packets: list[dict[str, Any]]) -> str:
    """Render packets as JSONL, one packet per line."""

    return "".join(json.dumps(packet) + "\n" for packet in packets)
