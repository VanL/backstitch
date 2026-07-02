"""Bounded semantic-review packet generation from deterministic results.

Spec: docs/specs/02-backstitch-core.md [SC-6], [SC-7]

Packets are the semantic review boundary: the model judges only what a
packet contains and never roams the repository [SC-7]. Generation is
deterministic and never calls ``llm``.
"""

from __future__ import annotations

import dataclasses
import json
from importlib import resources
from pathlib import Path
from typing import Any

from backstitch.config import ProfileConfig
from backstitch.models import Report, SpecSection
from backstitch.python_refs import python_symbol_spans
from backstitch.resolver import scan_repository

MAX_SNIPPET_LINES = 120
MAX_OWNERS_PER_PACKET = 8
MAX_SECTION_LINES = 100


def _instructions() -> str:
    return (
        resources.files("backstitch") / "prompts" / "backstitch_style_analysis.md"
    ).read_text(encoding="utf-8")


def _is_test_path(path: str) -> bool:
    pure = Path(path)
    if pure.name.startswith("test_"):
        return True
    return bool(pure.parts) and pure.parts[0] == "tests"


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
    if symbol is not None and path.endswith(".py"):
        spans = python_symbol_spans(target)
        span = spans.get(symbol) if spans else None
        if span is not None:
            start, end = span
            lines = lines[start - 1 : end]
        else:
            warnings.append(f"symbol `{symbol}` not found in `{path}`; using file head")
    if len(lines) > MAX_SNIPPET_LINES:
        lines = lines[:MAX_SNIPPET_LINES]
        warnings.append(f"snippet for `{path}` truncated to {MAX_SNIPPET_LINES} lines")
    return "\n".join(lines), start


def generate_packets(
    repo_root: Path,
    profile: ProfileConfig,
    report: Report | None = None,
) -> list[dict[str, Any]]:
    """Generate one packet per spec section that has resolved edges."""

    root = repo_root.resolve()
    if report is None:
        report = scan_repository(root, profile)
    instructions = _instructions()

    sections_by_file: dict[str, list[SpecSection]] = {}
    for section in report.spec_sections:
        sections_by_file.setdefault(section.path, []).append(section)

    spec_lines: dict[str, list[str]] = {}
    for path in sections_by_file:
        spec_lines[path] = (
            (root / path).read_text(encoding="utf-8", errors="replace").splitlines()
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
            if edge.kind == "backlink" and _is_test_path(edge.code_path):
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
            snippet, start_line = _owner_snippet(root, path, symbol, warnings)
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
                "spec_path": section.path,
                "section_id": section.section_id,
                "title": section.title,
                "section_text": _section_text(
                    section,
                    spec_lines[section.path],
                    sections_by_file[section.path],
                    warnings,
                ),
                "owners": owners,
                "tests": tests,
                "issues": issues,
                "warnings": warnings,
                "instructions": instructions,
            }
        )
    return packets


def render_packets_jsonl(packets: list[dict[str, Any]]) -> str:
    """Render packets as JSONL, one packet per line."""

    return "".join(json.dumps(packet) + "\n" for packet in packets)
