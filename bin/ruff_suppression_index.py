#!/usr/bin/env python3
"""Validate and render the approved Ruff suppression index."""

from __future__ import annotations

import argparse
import ast
import io
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import tokenize
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

REGISTRY_HEADING = "#### Approved Ruff Suppression Registry [SC-17.1]"
BEGIN_MARKER = "<!-- BEGIN GENERATED RUFF SUPPRESSION INDEX -->"
END_MARKER = "<!-- END GENERATED RUFF SUPPRESSION INDEX -->"
LINT_TARGETS = (
    ".",
    "bin/check-doc-paths",
    "bin/check-dom15-fixtures",
    "bin/coalesce-check",
)
RUFF_PREFIX = ("uv", "run", "--frozen", "--no-sync", "ruff")
GROUP_RE = re.compile(r"RUFF-SUP-\d{3}")
RULE_RE = re.compile(r"[A-Z]+\d+")
MARKER_RE = re.compile(
    r"^# noqa: (?P<rules>[A-Z]+\d+(?:, [A-Z]+\d+)*) approved "
    r"\[SC-17\.1\] (?P<group>RUFF-SUP-\d{3}) exception$"
)
TABLE_HEADER = (
    "| Group | Rules | Approved directives | Approved raw diagnostics by rule | "
    "Lifetime | Protected invariant | Real proof | Rejected alternatives | Approval |"
)
TABLE_DIVIDER = "|---|---|---:|---|---|---|---|---|---|"
GLOBAL_INVENTORY_PREFIX = "Global active-rule raw inventory: "
GENERATED_HEADER = "| Group | Source symbols | Directives | Raw diagnostics by rule |"
GENERATED_DIVIDER = "| --- | --- | ---: | --- |"


class PolicyMismatch(Exception):
    """The repository does not match its suppression policy."""


class ToolFailure(Exception):
    """A tool or input could not be read reliably."""


@dataclass(frozen=True)
class Group:
    name: str
    rules: tuple[str, ...]
    directives: int
    raw: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class RegistryLayout:
    by_number: dict[int, str]
    human_section: tuple[tuple[int, str], ...]
    first_row: int
    begin: int
    end: int


@dataclass(frozen=True)
class Directive:
    path: str
    line: int
    symbol: str
    group: str
    rules: tuple[str, ...]


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    code: str


def _fail(message: str) -> NoReturn:
    raise PolicyMismatch(message)


def _active_lines(text: str) -> list[tuple[int, str]]:
    active: list[tuple[int, str]] = []
    fence_character: str | None = None
    fence_width = 0
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip()
        if fence_character is None:
            match = re.match(r"(`{3,}|~{3,})", stripped)
            if match:
                token = match.group(1)
                fence_character = token[0]
                fence_width = len(token)
                continue
            active.append((number, line))
            continue
        if re.fullmatch(
            rf"{re.escape(fence_character)}{{{fence_width},}}[ \t]*", stripped
        ):
            fence_character = None
            fence_width = 0
            continue
    if fence_character is not None:
        _fail("unclosed Markdown fence in suppression registry spec")
    return active


def _single_line(lines: list[tuple[int, str]], value: str, label: str) -> int:
    matches = [number for number, line in lines if line.strip() == value]
    if len(matches) != 1:
        _fail(f"expected exactly one {label}; found {len(matches)}")
    return matches[0]


def _cells(line: str) -> list[str]:
    if not line.strip().startswith("|") or not line.strip().endswith("|"):
        _fail(f"malformed registry table row: {line!r}")
    return [cell.strip() for cell in line.strip()[1:-1].split("|")]


def _substantive(value: str, field: str, group: str) -> None:
    plain = re.sub(r"[`*_]", "", value).strip().lower().rstrip(".")
    placeholders = {
        "",
        "-",
        "none",
        "n/a",
        "na",
        "todo",
        "tbd",
        "pending",
        "placeholder",
    }
    if (
        plain in placeholders
        or plain.startswith("pending ")
        or plain.startswith("rows promoted")
    ):
        _fail(f"{group} has blank or placeholder {field}")
    score_only = re.fullmatch(
        r"(?:reduce|lower|high|current|ruff|mccabe|complexity|score|c901|\d+|[ :;,./()-])+",
        plain,
    )
    if score_only:
        _fail(f"{group} has a score-only {field}")
    if field != "approval" and any(
        phrase in plain
        for phrase in (
            "suppression is registered",
            "suppression is approved",
            "listed in the registry",
            "registry approves",
        )
    ):
        _fail(f"{group} has a circular {field}")


def _parse_rules(value: str, group: str) -> tuple[str, ...]:
    if re.fullmatch(r"`[A-Z]+\d+`(?:, `[A-Z]+\d+`)*", value) is None:
        _fail(f"{group} has malformed rules")
    parts = tuple(part.strip("`") for part in value.split(", "))
    if len(set(parts)) != len(parts):
        _fail(f"{group} has duplicate rules")
    return tuple(sorted(parts))


def _parse_raw(value: str, group: str) -> tuple[tuple[str, int], ...]:
    if re.fullmatch(r"`[A-Z]+\d+=\d+`(?:, `[A-Z]+\d+=\d+`)*", value) is None:
        _fail(f"{group} has malformed raw diagnostic counts")
    result: list[tuple[str, int]] = []
    for part in value.split(", "):
        match = re.fullmatch(r"`([A-Z]+\d+)=(\d+)`", part)
        if not match or int(match.group(2)) < 1:
            _fail(f"{group} has malformed raw diagnostic counts")
        result.append((match.group(1), int(match.group(2))))
    if len({code for code, _ in result}) != len(result):
        _fail(f"{group} has duplicate raw diagnostic rules")
    return tuple(sorted(result))


def _registry_layout(text: str) -> RegistryLayout:
    active = _active_lines(text)
    heading = _single_line(active, REGISTRY_HEADING, "SC-17.1 registry heading")
    section_end = next(
        (
            number
            for number, line in active
            if number > heading and re.match(r"^#{1,4} ", line)
        ),
        sys.maxsize,
    )
    section = [item for item in active if heading < item[0] < section_end]
    begin = _single_line(section, BEGIN_MARKER, "generated-index begin marker")
    end = _single_line(section, END_MARKER, "generated-index end marker")
    human_section = [item for item in section if item[0] < begin]
    table_headers = [
        number for number, line in human_section if line.strip() == TABLE_HEADER
    ]
    if len(table_headers) != 1:
        _fail(
            f"expected exactly one human suppression registry table; found {len(table_headers)}"
        )
    by_number = dict(active)
    cursor = heading + 1
    while cursor in by_number and not by_number[cursor].strip():
        cursor += 1
    if (
        by_number.get(cursor, "").strip() != TABLE_HEADER
        or by_number.get(cursor + 1, "").strip() != TABLE_DIVIDER
    ):
        _fail("SC-17.1 registry table header does not match the required schema")
    if begin >= end:
        _fail("generated-index markers are reversed")
    return RegistryLayout(by_number, tuple(human_section), cursor + 2, begin, end)


def _registry_rows(layout: RegistryLayout) -> list[tuple[int, str]]:
    cursor = layout.first_row
    rows: list[tuple[int, str]] = []
    while cursor in layout.by_number and layout.by_number[cursor].strip().startswith(
        "|"
    ):
        rows.append((cursor, layout.by_number[cursor]))
        cursor += 1
    row_numbers = {number for number, _ in rows}
    ignored_rows = [
        number
        for number, line in layout.human_section
        if number not in row_numbers
        and line.strip().startswith("|")
        and "RUFF-SUP-" in line
    ]
    if ignored_rows:
        _fail(
            f"group-shaped registry rows exist outside the human table: {ignored_rows}"
        )
    if cursor > layout.begin:
        _fail("human registry table must precede the generated index")
    return rows


def _approved_directives(value: str, name: str) -> int:
    match = re.fullmatch(r"`(\d+)`", value)
    if not match or int(match.group(1)) < 1:
        _fail(f"{name} has malformed approved directive count")
    return int(match.group(1))


def _validate_human_fields(cells: list[str], name: str) -> None:
    lifetime = cells[4].strip()
    if lifetime != "permanent" and not re.fullmatch(
        r"temporary: T(?:5|6|7|8|9) .+", lifetime
    ):
        _fail(
            f"{name} has malformed lifetime; temporary entries require a named T5-T9 task"
        )
    fields = ("protected invariant", "real proof", "rejected alternatives", "approval")
    for field, value in zip(fields, cells[5:9], strict=True):
        _substantive(value, field, name)
    proof = re.sub(r"[`*_]", "", cells[6]).lower()
    evidence_words = (
        "test",
        "probe",
        "fixture",
        "suite",
        "command",
        "acceptance",
        "bin/",
    )
    if not any(word in proof for word in evidence_words):
        _fail(f"{name} real proof does not name executable evidence")


def _parse_group_row(number: int, row: str) -> Group:
    cells = _cells(row)
    if len(cells) != 9:
        _fail(f"registry row {number} must contain nine columns")
    group_cell = re.fullmatch(r"`(RUFF-SUP-\d{3})`", cells[0])
    if group_cell is None:
        _fail(f"registry row {number} has malformed group id")
    name = group_cell.group(1)
    rules = _parse_rules(cells[1], name)
    raw = _parse_raw(cells[3], name)
    if set(rules) != {code for code, _ in raw}:
        _fail(f"{name} rules do not match its raw diagnostic rules")
    _validate_human_fields(cells, name)
    return Group(name, rules, _approved_directives(cells[2], name), raw)


def parse_registry(text: str) -> tuple[dict[str, Group], tuple[int, int]]:
    layout = _registry_layout(text)
    groups: dict[str, Group] = {}
    for number, row in _registry_rows(layout):
        group = _parse_group_row(number, row)
        if group.name in groups:
            _fail(f"duplicate registry group {group.name}")
        groups[group.name] = group
    if not groups:
        _fail("SC-17.1 registry has no groups")
    return groups, (layout.begin, layout.end)


@dataclass(frozen=True)
class _Span:
    start: int
    end: int
    name: str


class _SpanVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.parts: list[str] = []
        self.spans: list[_Span] = []

    def _definition(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
    ) -> None:
        start = min(
            (decorator.lineno for decorator in node.decorator_list), default=node.lineno
        )
        name = ".".join((*self.parts, node.name))
        self.spans.append(_Span(start, node.end_lineno or node.lineno, name))
        self.parts.append(node.name)
        self.generic_visit(node)
        self.parts.pop()

    visit_FunctionDef = _definition
    visit_AsyncFunctionDef = _definition
    visit_ClassDef = _definition


def _symbol_spans(source: str, path: Path) -> list[_Span]:
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        raise ToolFailure(f"cannot parse {path}: {exc}") from exc
    visitor = _SpanVisitor()
    visitor.visit(tree)
    return visitor.spans


def _symbol_at(spans: list[_Span], line: int) -> str:
    matches = [span for span in spans if span.start <= line <= span.end]
    if not matches:
        return "<module>"
    return min(matches, key=lambda span: (span.end - span.start, -span.start)).name


def _relative(path: Path, root: Path) -> str:
    try:
        relative = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ToolFailure(f"Ruff path escapes repository root: {path}") from exc
    if any(character in relative for character in ("|", "`", "\r", "\n")):
        _fail(f"{relative!r} cannot be represented in the Markdown index")
    return relative


def scan_source(path: Path, root: Path) -> list[Directive]:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ToolFailure(f"cannot read UTF-8 Python source {path}: {exc}") from exc
    spans = _symbol_spans(source, path)
    directives: list[Directive] = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for token in tokens:
            if token.type != tokenize.COMMENT:
                continue
            comment = token.string.strip()
            match = MARKER_RE.fullmatch(comment)
            if match:
                rules = tuple(sorted(match.group("rules").split(", ")))
                if len(rules) != len(set(rules)):
                    _fail(
                        f"duplicate noqa code at {_relative(path, root)}:{token.start[0]}"
                    )
                directives.append(
                    Directive(
                        _relative(path, root),
                        token.start[0],
                        _symbol_at(spans, token.start[0]),
                        match.group("group"),
                        rules,
                    )
                )
            elif "# noqa:" in comment and (
                "[SC-17.1]" in comment or "RUFF-SUP-" in comment
            ):
                _fail(
                    f"malformed governed Ruff marker at {_relative(path, root)}:{token.start[0]}"
                )
    except (tokenize.TokenError, IndentationError) as exc:
        raise ToolFailure(f"cannot tokenize {path}: {exc}") from exc
    return directives


def _run_ruff(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [*RUFF_PREFIX, *args],
            cwd=root,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
    except (OSError, UnicodeError) as exc:
        raise ToolFailure(f"could not execute Ruff: {exc}") from exc


def discover_sources(root: Path) -> list[Path]:
    result = _run_ruff(root, "check", "--show-files", *LINT_TARGETS)
    if result.returncode != 0:
        raise ToolFailure(
            f"Ruff source discovery failed ({result.returncode}): {result.stderr.strip()}"
        )
    sources: list[Path] = []
    for raw in result.stdout.splitlines():
        path = Path(raw)
        if not path.is_absolute():
            path = root / path
        _relative(path, root)
        if path.suffix in {".py", ".pyi"}:
            sources.append(path)
            continue
        if path.suffix:
            continue
        try:
            with path.open("rb") as source:
                first_line = source.readline()
        except OSError as exc:
            raise ToolFailure(
                f"cannot read Ruff-discovered source {path}: {exc}"
            ) from exc
        if first_line.startswith(b"#!") and b"python" in first_line.lower():
            sources.append(path)
    return sorted(set(sources), key=lambda path: _relative(path, root))


def _reject_duplicate_json_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _decode_ruff_payload(
    result: subprocess.CompletedProcess[str], label: str
) -> list[object]:
    if result.returncode not in (0, 1):
        raise ToolFailure(
            f"{label} failed ({result.returncode}): {result.stderr.strip()}"
        )
    if not result.stdout.strip():
        raise ToolFailure(f"{label} emitted empty JSON output")
    try:
        payload = json.loads(
            result.stdout, object_pairs_hook=_reject_duplicate_json_keys
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise ToolFailure(f"{label} emitted malformed JSON") from exc
    if not isinstance(payload, list):
        raise ToolFailure(f"{label} JSON must be a list")
    return payload


def _finding_from_item(item: object, root: Path, label: str) -> Finding:
    try:
        if not isinstance(item, dict):
            raise TypeError
        raw_filename = item["filename"]
        raw_line = item["noqa_row"]
        raw_code = item["code"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ToolFailure(f"{label} emitted an invalid diagnostic object") from exc
    valid = (
        isinstance(raw_filename, str)
        and type(raw_line) is int
        and raw_line > 0
        and isinstance(raw_code, str)
        and RULE_RE.fullmatch(raw_code) is not None
    )
    if not valid:
        raise ToolFailure(f"{label} emitted an invalid diagnostic object")
    filename = Path(raw_filename)
    if not filename.is_absolute():
        filename = root / filename
    return Finding(_relative(filename, root), raw_line, raw_code)


def _json_findings(
    result: subprocess.CompletedProcess[str], root: Path, *, label: str
) -> list[Finding]:
    return [
        _finding_from_item(item, root, label)
        for item in _decode_ruff_payload(result, label)
    ]


def collect_findings(root: Path) -> list[Finding]:
    normal = _run_ruff(root, "check", "--output-format", "json", *LINT_TARGETS)
    normal_findings = _json_findings(normal, root, label="Ruff policy check")
    if normal_findings:
        _fail("normal Ruff policy check is not clean")
    raw = _run_ruff(
        root, "check", "--ignore-noqa", "--output-format", "json", *LINT_TARGETS
    )
    return _json_findings(raw, root, label="Ruff raw audit")


def _index_directives(
    groups: dict[str, Group], directives: list[Directive]
) -> dict[str, list[Directive]]:
    by_group: dict[str, list[Directive]] = defaultdict(list)
    pointers: set[tuple[str, str, str]] = set()
    for directive in directives:
        group = groups.get(directive.group)
        if group is None:
            _fail(f"source marker references unknown group {directive.group}")
        unknown = set(directive.rules) - set(group.rules)
        if unknown:
            _fail(
                f"{directive.group} source marker uses unregistered rules: {sorted(unknown)}"
            )
        pointer = (directive.group, directive.path, directive.symbol)
        if pointer in pointers:
            _fail(
                f"duplicate source pointer for {directive.group}: {directive.path}::{directive.symbol}"
            )
        pointers.add(pointer)
        by_group[directive.group].append(directive)
    return by_group


def _raw_by_location(
    findings: list[Finding],
) -> dict[tuple[str, int], Counter[str]]:
    locations: dict[tuple[str, int], Counter[str]] = defaultdict(Counter)
    for finding in findings:
        locations[(finding.path, finding.line)][finding.code] += 1
    return locations


def _directive_raw(
    directive: Directive,
    raw_locations: dict[tuple[str, int], Counter[str]],
) -> Counter[str]:
    actual = raw_locations[(directive.path, directive.line)]
    if set(actual) != set(directive.rules):
        _fail(
            f"governed directive rules do not match raw diagnostics at "
            f"{directive.path}:{directive.line}"
        )
    return actual


def _validate_group(
    group: Group,
    owned: list[Directive],
    raw_locations: dict[tuple[str, int], Counter[str]],
) -> None:
    if len(owned) != group.directives:
        _fail(
            f"{group.name} directive cardinality is {len(owned)}; expected {group.directives}"
        )
    used_rules = {code for directive in owned for code in directive.rules}
    if used_rules != set(group.rules):
        _fail(f"{group.name} live directive rules do not match the registry")
    group_raw: Counter[str] = Counter()
    for directive in owned:
        group_raw.update(raw_locations[(directive.path, directive.line)])
    if group_raw != Counter(dict(group.raw)):
        _fail(f"{group.name} raw diagnostic cardinality does not match the registry")


def _raw_inventory(
    raw_locations: dict[tuple[str, int], Counter[str]],
) -> Counter[tuple[str, int, str]]:
    inventory: Counter[tuple[str, int, str]] = Counter()
    for (path, line), counts in raw_locations.items():
        for code, count in counts.items():
            inventory[(path, line, code)] += count
    return inventory


def reconcile(
    groups: dict[str, Group], directives: list[Directive], findings: list[Finding]
) -> dict[str, list[Directive]]:
    by_group = _index_directives(groups, directives)
    raw_locations = _raw_by_location(findings)
    consumed: Counter[tuple[str, int, str]] = Counter()
    for directive in directives:
        for code, count in _directive_raw(directive, raw_locations).items():
            consumed[(directive.path, directive.line, code)] += count
    locations = _raw_inventory(raw_locations)
    if locations != consumed:
        extra = list((locations - consumed).elements())
        missing = list((consumed - locations).elements())
        _fail(
            f"raw Ruff inventory does not reconcile; unregistered={extra}, excess-directives={missing}"
        )
    for name, group in groups.items():
        _validate_group(group, by_group.get(name, []), raw_locations)
    return by_group


def render(groups: dict[str, Group], by_group: dict[str, list[Directive]]) -> list[str]:
    global_raw: Counter[str] = Counter()
    for group in groups.values():
        global_raw.update(dict(group.raw))
    inventory = ", ".join(f"`{code}={global_raw[code]}`" for code in sorted(global_raw))
    lines = [
        BEGIN_MARKER,
        f"{GLOBAL_INVENTORY_PREFIX}{inventory}",
        "",
        GENERATED_HEADER,
        GENERATED_DIVIDER,
    ]
    for name in sorted(groups):
        directives = sorted(
            by_group[name], key=lambda item: (item.path, item.symbol, item.rules)
        )
        pointers = "<br>".join(
            f"`{directive.path}::{directive.symbol}`" for directive in directives
        )
        raw = ", ".join(f"`{code}={count}`" for code, count in groups[name].raw)
        lines.append(f"| `{name}` | {pointers} | `{len(directives)}` | {raw} |")
    lines.append(END_MARKER)
    return lines


def replace_generated(text: str, rendered: list[str]) -> str:
    _, (begin_line, end_line) = parse_registry(text)
    lines = text.splitlines(keepends=True)
    begin = begin_line - 1
    end = end_line
    marker_line = lines[begin]
    newline = "\r\n" if marker_line.endswith("\r\n") else "\n"
    trailing = newline if lines[end - 1].endswith(("\n", "\r")) else ""
    return (
        "".join(lines[:begin])
        + newline.join(rendered)
        + trailing
        + "".join(lines[end:])
    )


def _atomic_write(path: Path, text: str) -> None:
    temporary: str | None = None
    try:
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{path.name}.", dir=path.parent
        )
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
        os.replace(temporary, path)
        temporary = None
    except OSError as exc:
        raise ToolFailure(f"could not atomically replace {path}: {exc}") from exc
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def run(root: Path, spec: Path, *, write: bool) -> None:
    try:
        original = spec.read_bytes()
        text = original.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise ToolFailure(f"cannot read UTF-8 suppression spec {spec}: {exc}") from exc
    groups, _ = parse_registry(text)
    directives = [
        directive
        for path in discover_sources(root)
        for directive in scan_source(path, root)
    ]
    by_group = reconcile(groups, directives, collect_findings(root))
    updated = replace_generated(text, render(groups, by_group))
    updated_bytes = updated.encode("utf-8")
    if write:
        if updated_bytes != original:
            _atomic_write(spec, updated)
    elif updated_bytes != original:
        _fail("generated Ruff suppression index is stale; run with --write")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--spec", type=Path, default=Path("docs/specs/02-backstitch-core.md")
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    spec = args.spec if args.spec.is_absolute() else root / args.spec
    try:
        run(root, spec, write=args.write)
    except PolicyMismatch as exc:
        print(f"ruff-suppression-index: policy mismatch: {exc}", file=sys.stderr)
        return 1
    except ToolFailure as exc:
        print(f"ruff-suppression-index: tool failure: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
