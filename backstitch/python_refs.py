"""Python code backlink parsing for the backstitch-style-v1 grammar.

Spec: docs/specs/02-backstitch-core.md [SC-4]
Spec: docs/specs/05-backstitch-invariants.md [INV-3]
Grammar: docs/implementation/04-backstitch-style-traceability.md

Python structure is read through ``tree-sitter-python`` so the parser is not
locked to the running interpreter's grammar. The parser emits every ID-shaped
bare bracket candidate;
the resolver filters candidates whose alphabetic prefix is unknown to the
spec corpus, so indexing noise like ``window[N-1]`` stays silent while
prose references like ``see [MA-1.1]`` still resolve.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import MutableMapping
from dataclasses import dataclass
from pathlib import Path

from backstitch.canonical import lf_line_count, lf_split
from backstitch.code_parser import (
    Definition,
    DocCandidate,
    NoSpecMarkerCandidate,
    ParsedModule,
    parse_python_source,
)
from backstitch.exclusions import (
    SuppressionDiagnostic,
    is_noqa_directive_line,
    parse_noqa_directives,
)
from backstitch.grammar import SECTION_ID
from backstitch.models import (
    CodeRef,
    InvariantBind,
    InvariantDeclaration,
    Issue,
    RefContext,
    SuppressionOrigin,
    SuppressionRule,
)

_ID_RE = re.compile(rf"^{SECTION_ID}$")
_PREFIX_RE = re.compile(r"^[A-Z][A-Za-z]*")
_MD_PATH_RE = re.compile(r"(?P<path>[\w.-]+(?:/[\w.-]+)*\.md)(?:#(?P<anchor>[\w-]+))?")
_BRACKET_RE = re.compile(r"\[(?P<content>[^\[\]]+)\]")
_CROSS_RANGE_RE = re.compile(
    rf"\[(?P<start>{SECTION_ID})\]\s*[-–—]{{1,2}}\s*\[(?P<end>{SECTION_ID})\]"
)
_ADJACENT_BRACKET_RE = re.compile(r"\s*(?P<sep>[,–—-]|--)?\s*\[[^\[\]]+\]")
_DASH_CHARS = "-–—"
_RESERVED_PREFIXES = ("Invariant:", "Invariant (draft):", "Tests-invariant:")
_STRING_OPEN_RE = re.compile(r"(?i)^(?:r|u|b|f|br|rb|fr|rf)?(?P<quote>'''|\"\"\"|'|\")")
_DECLARATION_RE = re.compile(rf"^\[(?P<id>{SECTION_ID})\]\s+(?P<statement>\S.*)$")
_PYTHON_DEFINITION_KINDS = frozenset({"class", "function", "async-function"})


@dataclass(frozen=True, slots=True)
class ParsedPython:
    """Parse result for one Python file.

    ``module_noqa`` holds codes suppressed for the whole file (docstring
    form, [EXC-5]); ``span_noqa`` holds ``(start, end, codes)`` for
    comment-form directives, scoped to the NEXT STATEMENT only -- file-wide
    bleed of a comment directive is a named regression.
    """

    path: str
    refs: tuple[CodeRef, ...]
    issues: tuple[Issue, ...]
    module_noqa: frozenset[str] = frozenset()
    span_noqa: tuple[tuple[int, int, frozenset[str]], ...] = ()
    noqa_diagnostics: tuple[SuppressionDiagnostic, ...] = ()
    module_suppression_rules: tuple[SuppressionRule, ...] = ()
    span_suppression_rules: tuple[tuple[int, int, SuppressionRule], ...] = ()
    invariants: tuple[InvariantDeclaration, ...] = ()
    binding_refs: tuple[InvariantBind, ...] = ()


@dataclass(frozen=True, slots=True)
class CanonicalPythonDefinition:
    """One canonical physical Python owner for intent coverage.

    Spec: docs/specs/08-intent-coverage.md [COV-3], [COV-4]
    """

    path: str
    qualname: str | None
    name: str | None
    kind: str
    structural_locator: str
    parent_locator: str | None
    ordinal: int
    start_line: int
    end_line: int
    attachment_line: int
    physical_start_byte: int
    physical_end_byte: int
    source_projection: bytes
    no_spec_markers: tuple[NoSpecMarkerCandidate, ...] = ()

    @property
    def source_projection_sha256(self) -> str:
        return f"sha256:{hashlib.sha256(self.source_projection).hexdigest()}"


def python_structural_locator(
    *,
    path: str,
    module_name: str | None = None,
    qualname: str | None = None,
    kind: str | None = None,
    ordinal: int | None = None,
) -> str:
    """Format the one canonical Python structural-locator vocabulary."""

    if qualname is None:
        if kind is not None or ordinal is not None:
            raise ValueError("module locators do not accept kind or ordinal")
        if module_name is not None:
            return f"python-module:{unicodedata.normalize('NFC', module_name)}"
        return f"python-module-path:{unicodedata.normalize('NFC', path)}"
    if (
        module_name is not None
        or kind not in _PYTHON_DEFINITION_KINDS
        or ordinal is None
        or ordinal < 0
    ):
        raise ValueError(
            "definition locators require qualname, kind, and nonnegative ordinal"
        )
    normalized = unicodedata.normalize("NFC", qualname)
    return f"python-definition:{normalized}:{kind}:{ordinal}"


def python_definition_inventory_bytes(
    source: bytes,
    *,
    rel_path: str,
    module_name: str | None,
    parsed_module: ParsedModule | None = None,
    parse_memo: MutableMapping[tuple[str, str], ParsedModule] | None = None,
) -> tuple[CanonicalPythonDefinition, ...] | None:
    """Return the canonical module/definition inventory for captured bytes.

    Spec: docs/specs/08-intent-coverage.md [COV-3], [COV-4]
    """

    try:
        source_text = source.decode("utf-8")
    except UnicodeDecodeError:
        return None
    parse_key = (rel_path, hashlib.sha256(source).hexdigest())
    parsed = parsed_module
    if parsed is None and parse_memo is not None:
        parsed = parse_memo.get(parse_key)
    if parsed is None:
        parsed = parse_python_source(source)
        if parse_memo is not None:
            parse_memo[parse_key] = parsed
    if not parsed.parse_ok:
        return None
    assert parsed.module_source_projection is not None

    normalized_path = unicodedata.normalize("NFC", rel_path)
    normalized_module = (
        None if module_name is None else unicodedata.normalize("NFC", module_name)
    )
    module_locator = python_structural_locator(
        path=normalized_path,
        module_name=normalized_module,
    )
    markers_by_scope: dict[int | None, list[NoSpecMarkerCandidate]] = {}
    for marker in parsed.no_spec_markers:
        markers_by_scope.setdefault(marker.owner_scope_start_byte, []).append(marker)
    inventory: list[CanonicalPythonDefinition] = [
        CanonicalPythonDefinition(
            path=normalized_path,
            qualname=normalized_module,
            name=(
                None
                if normalized_module is None
                else normalized_module.rsplit(".", 1)[-1]
            ),
            kind="module",
            structural_locator=module_locator,
            parent_locator=None,
            ordinal=0,
            start_line=1,
            end_line=max(1, lf_line_count(source_text)),
            attachment_line=1,
            physical_start_byte=0,
            physical_end_byte=len(source),
            source_projection=parsed.module_source_projection,
            no_spec_markers=tuple(markers_by_scope.get(None, ())),
        )
    ]
    locator_by_scope: dict[int, str] = {}
    ordinals: dict[tuple[str, str], int] = {}
    for definition in parsed.definitions:
        qualname = unicodedata.normalize("NFC", definition.qualname)
        ordinal_key = (qualname, definition.kind)
        ordinal = ordinals.get(ordinal_key, 0)
        ordinals[ordinal_key] = ordinal + 1
        locator = python_structural_locator(
            path=normalized_path,
            qualname=qualname,
            kind=definition.kind,
            ordinal=ordinal,
        )
        parent_locator = (
            module_locator
            if definition.parent_scope_start_byte is None
            else locator_by_scope[definition.parent_scope_start_byte]
        )
        inventory.append(
            CanonicalPythonDefinition(
                path=normalized_path,
                qualname=qualname,
                name=unicodedata.normalize("NFC", definition.name),
                kind=definition.kind,
                structural_locator=locator,
                parent_locator=parent_locator,
                ordinal=ordinal,
                start_line=definition.start_line,
                end_line=definition.end_line,
                attachment_line=definition.attachment_line,
                physical_start_byte=definition.physical_start_byte,
                physical_end_byte=definition.physical_end_byte,
                source_projection=definition.source_projection,
                no_spec_markers=tuple(
                    markers_by_scope.get(definition.scope_start_byte, ())
                ),
            )
        )
        locator_by_scope[definition.scope_start_byte] = locator
    return tuple(inventory)


@dataclass(frozen=True, slots=True)
class _LineRef:
    """One reference extracted from a docstring or comment line."""

    spec_path: str | None
    anchor: str | None
    section_ids: tuple[str, ...]
    ranges: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class _PhysicalDocLine:
    line: int
    text: str
    indent: int
    escaped_from_previous: bool


def _parse_bracket_content(content: str) -> tuple[list[str], list[tuple[str, str]]]:
    """Split one bracket's content into IDs and same-prefix in-bracket ranges."""

    ids: list[str] = []
    ranges: list[tuple[str, str]] = []
    for item in (part.strip() for part in content.split(",")):
        if not item:
            continue
        if (found := _in_bracket_range(item)) is not None:
            ranges.append(found)
        elif _ID_RE.match(item):
            ids.append(item)
    return ids, ranges


def _in_bracket_range(item: str) -> tuple[str, str] | None:
    """Detect ``IMMUT.1-IMMUT.4`` style ranges inside one bracket.

    Only a split whose halves are both valid IDs with the same alphabetic
    prefix counts as a range; anything else stays a single candidate ID.
    """

    for pos, char in enumerate(item):
        if char not in _DASH_CHARS:
            continue
        left, right = item[:pos], item[pos + 1 :]
        if not (_ID_RE.match(left) and _ID_RE.match(right)):
            continue
        left_prefix = _PREFIX_RE.match(left)
        right_prefix = _PREFIX_RE.match(right)
        if left_prefix and right_prefix and left_prefix.group() == right_prefix.group():
            return left, right
    return None


def _extract_line_refs(line_text: str) -> list[_LineRef]:
    """Extract every reference on one line of docstring or comment text."""

    consumed: list[tuple[int, int]] = []
    results: list[_LineRef] = []

    def is_consumed(start: int, end: int) -> bool:
        return any(start < c_end and end > c_start for c_start, c_end in consumed)

    # 1. File-qualified references: an .md path plus adjacent bracket groups.
    for path_match in _MD_PATH_RE.finditer(line_text):
        ids: list[str] = []
        ranges: list[tuple[str, str]] = []
        pos = path_match.end()
        pending: str | None = None
        while True:
            adjacent = _ADJACENT_BRACKET_RE.match(line_text, pos)
            if not adjacent:
                break
            bracket = _BRACKET_RE.search(line_text, pos, adjacent.end())
            assert bracket is not None
            content = bracket.group("content")
            content_ids, content_ranges = _parse_bracket_content(content)
            ranges.extend(content_ranges)
            sep = adjacent.group("sep") or ""
            is_dash = any(char in sep for char in _DASH_CHARS)
            if pending is not None and is_dash and len(content_ids) == 1:
                ranges.append((pending, content_ids[0]))
                pending = None
            else:
                if pending is not None:
                    ids.append(pending)
                    pending = None
                if len(content_ids) == 1:
                    pending = content_ids[0]
                else:
                    ids.extend(content_ids)
            pos = adjacent.end()
        if pending is not None:
            ids.append(pending)
        consumed.append((path_match.start(), pos))
        results.append(
            _LineRef(
                spec_path=path_match.group("path").removeprefix("./"),
                anchor=path_match.group("anchor"),
                section_ids=tuple(ids),
                ranges=tuple(ranges),
            )
        )

    # Bare bracketed references are emitted for every ID-shaped candidate;
    # the resolver keeps only those whose alphabetic prefix matches a known
    # section-ID prefix, which is what filters indexing noise such as
    # ``window[N-1]`` without dropping prose refs like ``see [MA-1.1]``.

    # 2. Cross-bracket bare ranges: [A]-[B], [A]--[B], or dash variants.
    bare_ids: list[str] = []
    bare_ranges: list[tuple[str, str]] = []
    for range_match in _CROSS_RANGE_RE.finditer(line_text):
        if is_consumed(range_match.start(), range_match.end()):
            continue
        bare_ranges.append((range_match.group("start"), range_match.group("end")))
        consumed.append((range_match.start(), range_match.end()))

    # 3. Remaining bare brackets: single IDs, comma lists, in-bracket ranges.
    for bracket_match in _BRACKET_RE.finditer(line_text):
        if is_consumed(bracket_match.start(), bracket_match.end()):
            continue
        content_ids, content_ranges = _parse_bracket_content(
            bracket_match.group("content")
        )
        bare_ids.extend(content_ids)
        bare_ranges.extend(content_ranges)

    if bare_ids or bare_ranges:
        results.append(
            _LineRef(
                spec_path=None,
                anchor=None,
                section_ids=tuple(bare_ids),
                ranges=tuple(bare_ranges),
            )
        )
    return results


def python_symbol_spans(file_path: Path) -> dict[str, tuple[int, int]] | None:
    """Return ``{qualname: (start_line, end_line)}``, or None on syntax error."""

    try:
        source = file_path.read_bytes()
    except (OSError, UnicodeDecodeError):
        return None
    return python_symbol_spans_bytes(source)


def python_symbol_spans_bytes(source: bytes) -> dict[str, tuple[int, int]] | None:
    """Snapshot-backed symbol spans without a filesystem read."""

    try:
        source.decode("utf-8")
    except UnicodeDecodeError:
        return None
    parsed = parse_python_source(source)
    if not parsed.parse_ok:
        return None
    return {qualname: (start, end) for qualname, start, end in parsed.owner_spans}


def python_symbol_inventory(file_path: Path) -> frozenset[str] | None:
    """Return the qualified class/function names in a file, or None on
    syntax error."""

    try:
        source = file_path.read_bytes()
    except (OSError, UnicodeDecodeError):
        return None
    return python_symbol_inventory_bytes(source)


def python_symbol_inventory_bytes(
    source: bytes,
    *,
    rel_path: str | None = None,
    parsed_module: ParsedModule | None = None,
    parse_memo: MutableMapping[tuple[str, str], ParsedModule] | None = None,
) -> frozenset[str] | None:
    """Snapshot-backed qualified symbol inventory without a filesystem read."""

    try:
        source.decode("utf-8")
    except UnicodeDecodeError:
        return None
    parse_key = (
        None if rel_path is None else (rel_path, hashlib.sha256(source).hexdigest())
    )
    parsed = parsed_module
    if parsed is None and parse_memo is not None and parse_key is not None:
        parsed = parse_memo.get(parse_key)
    if parsed is None:
        parsed = parse_python_source(source)
        if parse_memo is not None and parse_key is not None:
            parse_memo[parse_key] = parsed
    if not parsed.parse_ok:
        return None
    return frozenset(qualname for qualname, _, _ in parsed.owner_spans)


def _next_statement_span(
    line_no: int, spans: list[tuple[int, int]]
) -> tuple[int, int] | None:
    """The span the [EXC-5] comment form attaches to: the next statement."""

    for start, end in spans:
        if start > line_no:
            return (start, end)
    return None


def _reserved_marker(text: str) -> tuple[str, str] | None:
    stripped = text.lstrip()
    for prefix in _RESERVED_PREFIXES:
        if stripped.startswith(prefix):
            return prefix, stripped[len(prefix) :].strip()
    return None


def _physical_doc_lines(candidate: DocCandidate) -> list[_PhysicalDocLine]:
    raw_lines = list(lf_split(candidate.raw_text)) or [candidate.raw_text]
    opening = _STRING_OPEN_RE.match(raw_lines[0])
    if opening is None:
        return []
    quote = opening.group("quote")
    content_lines = list(raw_lines)
    content_lines[0] = content_lines[0][opening.end() :]
    if len(content_lines) == 1:
        close = content_lines[0].rfind(quote)
        if close >= 0:
            content_lines[0] = content_lines[0][:close]
    else:
        close = content_lines[-1].rfind(quote)
        if close >= 0:
            content_lines[-1] = content_lines[-1][:close]
    result: list[_PhysicalDocLine] = []
    for offset, text in enumerate(content_lines):
        base = candidate.start_column + opening.end() if offset == 0 else 0
        leading = text[: len(text) - len(text.lstrip())]
        result.append(
            _PhysicalDocLine(
                line=candidate.start_line + offset,
                text=text,
                indent=base + len(leading.expandtabs(8)),
                escaped_from_previous=(
                    offset > 0
                    and (
                        len(content_lines[offset - 1])
                        - len(content_lines[offset - 1].rstrip("\\"))
                    )
                    % 2
                    == 1
                ),
            )
        )
    return result


def _parse_binding_ids(payload: str) -> tuple[str, ...] | None:
    matches = list(_BRACKET_RE.finditer(payload))
    if not matches:
        return None
    remainder_parts: list[str] = []
    cursor = 0
    ids: list[str] = []
    for match in matches:
        remainder_parts.append(payload[cursor : match.start()])
        content_ids, ranges = _parse_bracket_content(match.group("content"))
        if ranges or not content_ids:
            return None
        ids.extend(content_ids)
        cursor = match.end()
    remainder_parts.append(payload[cursor:])
    remainder = "".join(remainder_parts)
    if remainder.strip(" ,\t"):
        return None
    return tuple(ids)


def _parsed_id(text: str) -> str | None:
    match = _BRACKET_RE.search(text)
    if match is None:
        return None
    candidate = match.group("content").strip()
    return candidate if _ID_RE.fullmatch(candidate) else None


def parse_python_file(
    file_path: Path,
    repo_root: Path,
    *,
    allow_unknown_codes: bool = False,
    is_test_file: bool = False,
) -> ParsedPython:
    """Filesystem compatibility wrapper around the immutable byte parser."""

    rel_path = file_path.resolve().relative_to(repo_root.resolve()).as_posix()
    return parse_python_bytes(
        file_path.read_bytes(),
        rel_path,
        allow_unknown_codes=allow_unknown_codes,
        is_test_file=is_test_file,
    )


def parse_python_bytes(
    source_bytes: bytes,
    rel_path: str,
    *,
    allow_unknown_codes: bool = False,
    is_test_file: bool = False,
    parsed_module: ParsedModule | None = None,
    parse_memo: MutableMapping[tuple[str, str], ParsedModule] | None = None,
) -> ParsedPython:
    """Parse one captured Python source without reopening the repository."""

    source_bytes.decode("utf-8")
    parse_key = (rel_path, hashlib.sha256(source_bytes).hexdigest())
    parsed = parsed_module
    if parsed is None and parse_memo is not None:
        parsed = parse_memo.get(parse_key)
    if parsed is None:
        parsed = parse_python_source(source_bytes)
        if parse_memo is not None:
            parse_memo[parse_key] = parsed
    if not parsed.parse_ok:
        issue = Issue(
            code="PYTHON_SYNTAX_ERROR",
            severity="warning",
            path=rel_path,
            line=parsed.error_line,
            message="could not analyze requested Python file: parser reported invalid syntax",
        )
        return ParsedPython(path=rel_path, refs=(), issues=(issue,))

    refs: list[CodeRef] = []
    invariants: list[InvariantDeclaration] = []
    binding_refs: list[InvariantBind] = []
    marker_issues: list[Issue] = []
    consumed_doc_lines: set[int] = set()

    def emit(owner: str, line_no: int, text: str, context: RefContext) -> None:
        for line_ref in _extract_line_refs(text):
            refs.append(
                CodeRef(
                    path=rel_path,
                    owner_symbol=owner,
                    line=line_no,
                    raw=text.strip(),
                    spec_path=line_ref.spec_path,
                    section_ids=line_ref.section_ids,
                    anchor=line_ref.anchor,
                    ranges=line_ref.ranges,
                    ref_context=context,
                )
            )

    definitions = {item.qualname: item for item in parsed.definitions}

    def marker_issue(
        code: str,
        line: int,
        message: str,
        *,
        owner: str | None,
        invariant_id: str | None,
    ) -> None:
        marker_issues.append(
            Issue(
                code=code,
                severity=(
                    "warning" if code == "INVARIANT_BINDING_NOT_TEST" else "error"
                ),
                path=rel_path,
                line=line,
                message=message,
                symbol=owner,
                invariant_id=invariant_id,
            )
        )

    def concrete_tests(owner: str) -> list[Definition]:
        definition = definitions.get(owner)
        if not is_test_file or definition is None:
            return []
        if definition.kind in {
            "function",
            "async-function",
        } and definition.name.startswith("test_"):
            return [definition]
        if definition.kind == "class":
            return [
                item
                for item in parsed.definitions
                if item.parent_qualname == definition.qualname
                and item.parent_kind == "class"
                and item.kind in {"function", "async-function"}
                and item.name.startswith("test_")
            ]
        return []

    def add_bindings(ids: tuple[str, ...], owner: str, marker_line: int) -> None:
        targets = concrete_tests(owner)
        if not targets:
            marker_issue(
                "INVARIANT_BINDING_NOT_TEST",
                marker_line,
                "invariant binding marker is not attached to a concrete test definition",
                owner=owner,
                invariant_id=ids[0] if ids else None,
            )
            return
        for invariant_id in ids:
            for target in targets:
                binding_refs.append(
                    InvariantBind(
                        invariant_id=invariant_id,
                        test_path=rel_path,
                        test_symbol=target.qualname,
                        marker_line=marker_line,
                        start_line=target.start_line,
                        end_line=target.end_line,
                    )
                )

    for candidate in parsed.doc_candidates:
        physical_lines = _physical_doc_lines(candidate)
        if candidate.node_type != "string" or candidate.text is None:
            evaluated_has_marker = bool(
                candidate.text
                and any(_reserved_marker(line) for line in lf_split(candidate.text))
            )
            physical_has_marker = any(
                _reserved_marker(line.text) for line in physical_lines
            )
            if evaluated_has_marker or physical_has_marker:
                marker_issue(
                    "INVARIANT_MARKER_INVALID",
                    candidate.start_line,
                    "invariant marker must be on a physical line in one non-interpolated string literal",
                    owner=candidate.owner_qualname,
                    invariant_id=_parsed_id(candidate.text or candidate.raw_text),
                )
                consumed_doc_lines.update(
                    range(candidate.start_line, candidate.end_line + 1)
                )
            continue

        index = 0
        while index < len(physical_lines):
            physical = physical_lines[index]
            marker = _reserved_marker(physical.text)
            if marker is None:
                index += 1
                continue
            prefix, payload = marker
            consumed_doc_lines.add(physical.line)
            if physical.escaped_from_previous:
                marker_issue(
                    "INVARIANT_MARKER_INVALID",
                    candidate.start_line,
                    "escaped newline cannot create an invariant marker line",
                    owner=candidate.owner_qualname,
                    invariant_id=_parsed_id(payload),
                )
                index += 1
                continue
            if prefix == "Tests-invariant:":
                ids = _parse_binding_ids(payload)
                if ids is None:
                    marker_issue(
                        "INVARIANT_MARKER_INVALID",
                        physical.line,
                        "malformed Tests-invariant ID list",
                        owner=candidate.owner_qualname,
                        invariant_id=_parsed_id(payload),
                    )
                else:
                    add_bindings(ids, candidate.owner_qualname, physical.line)
                index += 1
                continue

            declaration = _DECLARATION_RE.fullmatch(payload)
            if declaration is None:
                marker_issue(
                    "INVARIANT_MARKER_INVALID",
                    physical.line,
                    "invariant declaration requires one valid ID and a statement",
                    owner=candidate.owner_qualname,
                    invariant_id=_parsed_id(payload),
                )
                index += 1
                continue
            segments = [declaration.group("statement").strip()]
            continuation = index + 1
            while continuation < len(physical_lines):
                next_line = physical_lines[continuation]
                if (
                    not next_line.text.strip()
                    or _reserved_marker(next_line.text) is not None
                    or next_line.indent <= physical.indent
                ):
                    break
                segments.append(next_line.text.strip())
                consumed_doc_lines.add(next_line.line)
                continuation += 1
            invariants.append(
                InvariantDeclaration(
                    invariant_id=declaration.group("id"),
                    statement="\n".join(segments),
                    tier=("draft" if prefix == "Invariant (draft):" else "required"),
                    declaration_kind="code",
                    path=rel_path,
                    line=physical.line,
                    owner_symbol=(
                        "<module>"
                        if candidate.owner_qualname == "module"
                        else candidate.owner_qualname
                    ),
                    section_id=None,
                )
            )
            index = continuation

    # Doc blocks: module first, then each class/function owner.
    for doc_block in parsed.doc_blocks:
        source_lines = (
            (doc_block.start_line + offset, text_line)
            for offset, text_line in enumerate(lf_split(doc_block.text))
        )
        for line_no, text_line in source_lines:
            if line_no in consumed_doc_lines or _reserved_marker(text_line):
                continue
            # A declaration-bearing noqa contains a spec path by design, but
            # that path is suppression metadata, not an asserted/prose code
            # reference. The canonical directive parser below owns it.
            if is_noqa_directive_line(text_line):
                continue
            # [SC-11] context: a `Spec:` marker line ASSERTS a trace edge;
            # any other docstring line is prose. The distinction is made
            # here, at parse time, never re-inferred downstream.
            context: RefContext = (
                "asserted" if text_line.lstrip().startswith("Spec:") else "docstring"
            )
            emit(
                doc_block.owner_qualname,
                line_no,
                text_line,
                context,
            )

    # [EXC-5] module-docstring noqa: file-scoped suppression codes.
    noqa_diagnostics: list[SuppressionDiagnostic] = []
    source_markers = [
        (doc.start_line + offset, source_line)
        for doc in parsed.doc_blocks
        for offset, source_line in enumerate(lf_split(doc.text))
    ]
    source_markers.extend(
        (comment.line, comment.text) for comment in parsed.comment_nodes
    )
    for line_no, source_line in source_markers:
        lowered = source_line.strip().lower()
        if "suppression-declaration" in lowered and lowered.startswith(
            ("_traceability:", "backstitch:")
        ):
            noqa_diagnostics.append(
                SuppressionDiagnostic(
                    code="SUPPRESSION_INVALID_SYNTAX",
                    path=rel_path,
                    line=line_no,
                    message=(
                        f"{rel_path}:{line_no}: suppression-declaration is not "
                        "valid in Python source"
                    ),
                )
            )
    module_doc = next(
        (doc for doc in parsed.doc_blocks if doc.owner_qualname == "module"), None
    )
    if module_doc is not None:
        module_directives, doc_warnings = parse_noqa_directives(
            module_doc.text,
            allow_unknown=allow_unknown_codes,
            location=f"{rel_path} module docstring",
            path=rel_path,
            line=module_doc.start_line,
        )
        noqa_diagnostics.extend(doc_warnings)
        module_noqa = frozenset(
            code for directive in module_directives for code in directive.codes
        )
        module_suppression_rules = tuple(
            SuppressionRule(
                mechanism="ignore",
                provenance="inline_code",
                path=rel_path,
                sections=(),
                codes=tuple(sorted(directive.codes)),
                declaration=directive.declaration,
                origin=SuppressionOrigin(
                    source=rel_path,
                    line=directive.line or module_doc.start_line,
                ),
            )
            for directive in module_directives
        )
    else:
        module_noqa = frozenset()
        module_suppression_rules = ()

    # Comments, with the innermost enclosing owner.
    def owner_for_line(line_no: int) -> str:
        best: str | None = None
        best_size: int | None = None
        for qualname, start, end in parsed.owner_spans:
            if start <= line_no <= end:
                size = end - start
                if best_size is None or size < best_size:
                    best, best_size = qualname, size
        return best or "module"

    statement_spans = list(parsed.statement_spans)
    span_noqa: list[tuple[int, int, frozenset[str]]] = []
    span_suppression_rules: list[tuple[int, int, SuppressionRule]] = []
    for comment in parsed.comment_nodes:
        line_no = comment.line
        comment_text = comment.text
        comment_directives, comment_warnings = parse_noqa_directives(
            comment_text,
            allow_unknown=allow_unknown_codes,
            location=f"{rel_path}:{line_no}",
            path=rel_path,
            line=line_no,
        )
        noqa_diagnostics.extend(comment_warnings)
        codes = frozenset(
            code for directive in comment_directives for code in directive.codes
        )
        if codes:
            # [EXC-5] comment form: next statement only, never file-wide.
            span = _next_statement_span(line_no, statement_spans)
            if span is not None:
                span_noqa.append((span[0], span[1], codes))
                span_suppression_rules.extend(
                    (
                        span[0],
                        span[1],
                        SuppressionRule(
                            mechanism="ignore",
                            provenance="inline_code",
                            path=rel_path,
                            sections=(),
                            codes=tuple(sorted(directive.codes)),
                            declaration=directive.declaration,
                            origin=SuppressionOrigin(
                                source=rel_path,
                                line=directive.line or line_no,
                            ),
                        ),
                    )
                    for directive in comment_directives
                )
            continue
        marker = _reserved_marker(comment_text)
        if marker is not None:
            prefix, payload = marker
            if prefix != "Tests-invariant:":
                marker_issue(
                    "INVARIANT_MARKER_INVALID",
                    line_no,
                    "Invariant declarations are not allowed in comments",
                    owner=owner_for_line(line_no),
                    invariant_id=_parsed_id(payload),
                )
                continue
            ids = _parse_binding_ids(payload)
            if ids is None:
                marker_issue(
                    "INVARIANT_MARKER_INVALID",
                    line_no,
                    "malformed Tests-invariant ID list",
                    owner=owner_for_line(line_no),
                    invariant_id=_parsed_id(payload),
                )
                continue
            attached = next(
                (
                    item
                    for item in parsed.definitions
                    if item.attachment_line == line_no + 1
                    and item.indent_column == comment.column
                ),
                None,
            )
            if attached is None:
                marker_issue(
                    "INVARIANT_BINDING_NOT_TEST",
                    line_no,
                    "invariant binding comment is not immediately attached to a definition",
                    owner=owner_for_line(line_no),
                    invariant_id=ids[0],
                )
            else:
                add_bindings(ids, attached.qualname, line_no)
            continue
        emit(
            owner_for_line(line_no),
            line_no,
            comment_text,
            "comment",
        )

    return ParsedPython(
        path=rel_path,
        refs=tuple(refs),
        issues=tuple(marker_issues),
        module_noqa=module_noqa,
        span_noqa=tuple(span_noqa),
        noqa_diagnostics=tuple(noqa_diagnostics),
        module_suppression_rules=module_suppression_rules,
        span_suppression_rules=tuple(span_suppression_rules),
        invariants=tuple(invariants),
        binding_refs=tuple(binding_refs),
    )
