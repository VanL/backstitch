"""Markdown spec parsing for the backstitch-style-v1 grammar.

Spec: docs/specs/02-backstitch-core.md [SC-4]
Spec: docs/specs/05-backstitch-invariants.md [INV-3]
Grammar: docs/implementation/04-backstitch-style-traceability.md

Backstitch interprets traceability constructs over ``markdown-it-py`` CommonMark
tokens. Markdown block structure, including fences and indented code blocks,
belongs to the parser library.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from markdown_it import MarkdownIt
from markdown_it.token import Token

from backstitch.exclusions import SuppressionDiagnostic, parse_traceability_marker_line
from backstitch.grammar import SECTION_ID
from backstitch.models import (
    InvariantDeclaration,
    Issue,
    MappingKind,
    SpecMapping,
    SpecSection,
)

_MARKDOWN = MarkdownIt("commonmark")
_HEADING_ID_RE = re.compile(rf"^(?P<title>.+?)\s*\[(?P<id>{SECTION_ID})\]\s*$")
_INVARIANT_TEXT_RE = re.compile(rf"^\*\*(?P<id>{SECTION_ID})\*\*\s*:\s*(?P<title>.*)$")
_MAPPING_MARKER_TEXT_RE = re.compile(r"^_Implementation mapping[^_]*_\s*:\s*")
# `- [MA-1.1] Spawn queue consumption — ...` inside a mapping block defines
# a subsection AND owns the mapping tokens on its line (observed Weft form).
_BULLET_DEF_TEXT_RE = re.compile(rf"^\[(?P<id>{SECTION_ID})\]\s+(?P<title>\S.*)$")
_TRAILING_HTML_COMMENT_RE = re.compile(r"\s*<!--.*?-->\s*$")
_ANCHOR_STRIP_RE = re.compile(r"[^\w\s-]", re.UNICODE)
_INVARIANT_DECLARATION_RE = re.compile(
    rf"^(?P<prefix>Invariant(?: \(draft\))?):\s*"
    rf"\[(?P<id>{SECTION_ID})\]\s+(?P<statement>\S.*)$"
)
_RESERVED_INVARIANT_PREFIXES = (
    "Invariant:",
    "Invariant (draft):",
    "Tests-invariant:",
)


@dataclass(frozen=True, slots=True)
class ParsedSpec:
    """Parse result for one Markdown spec file.

    Traceability markers ([EXC-4]) ride along: ``file_meta``/``file_ignores``
    from the pre-heading preamble, ``section_markers`` as
    ``(section_id, is_meta, ignore_codes)`` for markers following a section
    definition.
    """

    path: str
    sections: tuple[SpecSection, ...]
    mappings: tuple[SpecMapping, ...]
    anchors: tuple[str, ...]
    issues: tuple[Issue, ...] = ()
    invariants: tuple[InvariantDeclaration, ...] = ()
    file_meta: bool = False
    file_ignores: frozenset[str] = frozenset()
    section_markers: tuple[tuple[str, bool, frozenset[str]], ...] = ()
    marker_diagnostics: tuple[SuppressionDiagnostic, ...] = ()


def github_anchor(heading_text: str, seen: dict[str, int]) -> str:
    """Return the GitHub-style anchor for a heading, deduplicated per file.

    GitHub replaces each space with a hyphen after stripping punctuation, so
    `Tasks & Queues` becomes `tasks--queues`; whitespace runs must not
    collapse.
    """

    base = _ANCHOR_STRIP_RE.sub("", heading_text.lower()).strip()
    base = base.replace(" ", "-")
    count = seen.get(base, 0)
    seen[base] = count + 1
    return base if count == 0 else f"{base}-{count}"


def classify_mapping_token(token: str) -> tuple[MappingKind, str | None, str | None]:
    """Classify a backticked mapping token as path, path::symbol, or symbol."""

    if "::" in token:
        path, _, symbol = token.partition("::")
        return "path_symbol", path, symbol.removesuffix("()")
    # Dotted tokens like `Runtime.save` are symbols, not files: a token
    # without a slash counts as a path only when it ends in a known file
    # extension. Trailing slashes mark directory ownership and stay paths.
    if "/" in token or re.search(
        r"\.(py|md|txt|toml|yaml|yml|json|cfg|ini|rst|sh|bash|js|jsx|ts|tsx"
        r"|sql|c|h|cpp|hpp|cc|rs|go|rb|java|kt|css|html|xml|proto|lock)$",
        token,
    ):
        return "path", token, None
    return "symbol", None, token.removesuffix("()")


def _heading_level(token: Token) -> int:
    if token.tag.startswith("h") and token.tag[1:].isdigit():
        return int(token.tag[1:])
    return 0


def _next_inline(tokens: list[Token], index: int) -> Token | None:
    if index + 1 < len(tokens) and tokens[index + 1].type == "inline":
        return tokens[index + 1]
    return None


def _token_start_line(token: Token, default: int = 1) -> int:
    if token.map:
        return token.map[0] + 1
    return default


def _inline_code_values(token: Token) -> tuple[str, ...]:
    return tuple(
        child.content for child in (token.children or []) if child.type == "code_inline"
    )


def _normalize_code_span_source(raw: str) -> str:
    """Mirror CommonMark code-span whitespace normalization for line lookup."""

    normalized = raw.replace("\n", " ")
    if (
        len(normalized) >= 2
        and normalized[0] == " "
        and normalized[-1] == " "
        and any(char != " " for char in normalized)
    ):
        return normalized[1:-1]
    return normalized


def _iter_code_spans_on_line(line: str) -> tuple[str, ...]:
    spans: list[str] = []
    index = 0
    while index < len(line):
        start = line.find("`", index)
        if start == -1:
            break
        tick_end = start
        while tick_end < len(line) and line[tick_end] == "`":
            tick_end += 1
        marker = "`" * (tick_end - start)
        close = line.find(marker, tick_end)
        if close == -1:
            index = tick_end
            continue
        spans.append(_normalize_code_span_source(line[tick_end:close]))
        index = close + len(marker)
    return tuple(spans)


def _line_numbers_for_code_values(
    token: Token, values: tuple[str, ...], lines: list[str]
) -> tuple[int, ...]:
    """Best-effort source lines for child code_inline tokens within token.map."""

    if not values:
        return ()
    if not token.map:
        return tuple(1 for _ in values)

    start, end = token.map
    source_lines = lines[start:end]
    line_numbers: list[int] = []
    line_cursor = 0
    span_cursor = 0
    for value in values:
        found: int | None = None
        for offset in range(line_cursor, len(source_lines)):
            spans = _iter_code_spans_on_line(source_lines[offset])
            first_span = span_cursor if offset == line_cursor else 0
            for span_index in range(first_span, len(spans)):
                if spans[span_index] != value:
                    continue
                found = start + offset + 1
                line_cursor = offset
                span_cursor = span_index + 1
                break
            if found is not None:
                break
        line_numbers.append(found if found is not None else start + 1)
    return tuple(line_numbers)


def _list_close_index(tokens: list[Token], start: int) -> int:
    return _container_close_index(
        tokens, start, "bullet_list_open", "bullet_list_close"
    )


def _container_close_index(
    tokens: list[Token], start: int, open_type: str, close_type: str
) -> int:
    depth = 0
    for index in range(start, len(tokens)):
        token = tokens[index]
        if token.type == open_type:
            depth += 1
        elif token.type == close_type:
            depth -= 1
            if depth == 0:
                return index
    return len(tokens) - 1


def _iter_list_item_first_inlines(
    tokens: list[Token], start: int, end: int
) -> tuple[Token, ...]:
    inlines: list[Token] = []
    for index in range(start + 1, end):
        token = tokens[index]
        if token.type != "list_item_open":
            continue
        item_level = token.level
        for candidate in tokens[index + 1 : end]:
            if candidate.type == "list_item_close" and candidate.level == item_level:
                break
            if candidate.type == "inline":
                inlines.append(candidate)
                break
    return tuple(inlines)


def _first_inline_line(token: Token) -> str:
    return token.content.splitlines()[0].strip() if token.content else ""


def _mapping_bullet_title(text: str) -> str:
    return text.split(" — ", 1)[0].removesuffix(" —").strip()


def _invariant_from_inline(token: Token) -> tuple[str, str] | None:
    invariant = _INVARIANT_TEXT_RE.match(_first_inline_line(token))
    if invariant is None:
        return None
    return invariant.group("id"), invariant.group("title").strip()


def _list_can_continue_mapping(tokens: list[Token], start: int, end: int) -> bool:
    for inline in _iter_list_item_first_inlines(tokens, start, end):
        if not inline.content.strip():
            continue
        if _invariant_from_inline(inline) is not None:
            continue
        if _inline_code_values(inline) or _BULLET_DEF_TEXT_RE.match(
            _first_inline_line(inline)
        ):
            return True
    return False


def _strip_recognized_trailing_html_marker(
    text: str,
    *,
    allow_unknown_codes: bool,
    location: str,
    path: str,
    line: int,
) -> tuple[str, bool, frozenset[str], list[SuppressionDiagnostic]]:
    if "<!--" not in text:
        return text, False, frozenset(), []
    is_meta, marker_codes, warnings = parse_traceability_marker_line(
        text,
        allow_unknown=allow_unknown_codes,
        location=location,
        path=path,
        line=line,
    )
    if is_meta or marker_codes or warnings:
        return (
            _TRAILING_HTML_COMMENT_RE.sub("", text).strip(),
            is_meta,
            marker_codes,
            warnings,
        )
    return text, False, frozenset(), []


def parse_markdown_spec(
    file_path: Path,
    repo_root: Path,
    *,
    allow_unknown_codes: bool = False,
) -> ParsedSpec:
    """Parse one spec file into sections, mappings, and anchor targets."""

    rel_path = file_path.resolve().relative_to(repo_root.resolve()).as_posix()
    text = file_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    tokens = _MARKDOWN.parse(text)

    sections: list[SpecSection] = []
    mappings: list[SpecMapping] = []
    invariants: list[InvariantDeclaration] = []
    anchors: list[str] = []
    issues: list[Issue] = []
    anchor_seen: dict[str, int] = {}
    file_meta = False
    file_ignores: set[str] = set()
    section_markers: dict[str, tuple[bool, set[str]]] = {}
    marker_diagnostics: list[SuppressionDiagnostic] = []

    # Mapping blocks attach to the nearest preceding heading section.
    # Invariant bullets define sections but never own mapping blocks: a
    # mapping after a bullet group documents the heading's ownership, not
    # the last bullet's.
    current_heading_section: SpecSection | None = None
    current_heading_level = 0
    mapping_section: SpecSection | None = None
    last_non_marker_block = "other"

    # [EXC-4] §4.2 placement window: True from a section-defining heading
    # or invariant bullet until the first body block; only markers inside
    # the window attach to the section.
    marker_window_open = False

    def record_marker(
        is_meta: bool, marker_codes: frozenset[str], line_no: int
    ) -> None:
        if not sections:
            nonlocal file_meta
            file_meta = file_meta or is_meta
            file_ignores.update(marker_codes if not is_meta else ())
            return
        # [EXC-4] §4.2: a section marker goes IMMEDIATELY after the heading
        # or invariant bullet, before body text. A misplaced marker never
        # applies -- and silently not applying is fake protection, so warn.
        if not marker_window_open:
            marker_diagnostics.append(
                SuppressionDiagnostic(
                    code="SUPPRESSION_INVALID_SYNTAX",
                    path=rel_path,
                    line=line_no,
                    message=(
                        f"{rel_path}:{line_no}: traceability marker after body text"
                        " is ignored ([EXC-4]: markers go immediately after the"
                        " heading)"
                    ),
                )
            )
            return
        target = sections[-1].section_id
        meta_flag, codes = section_markers.setdefault(target, (False, set()))
        section_markers[target] = (
            meta_flag or is_meta,
            codes | (marker_codes if not is_meta else set()),
        )

    def parse_marker_text(text: str, line_no: int) -> bool:
        is_meta, marker_codes, warnings = parse_traceability_marker_line(
            text,
            allow_unknown=allow_unknown_codes,
            location=f"{rel_path}:{line_no}",
            path=rel_path,
            line=line_no,
        )
        marker_diagnostics.extend(warnings)
        if is_meta or marker_codes:
            record_marker(is_meta, marker_codes, line_no)
            return True
        return False

    def emit_mapping_tokens(token: Token, owner: SpecSection | None) -> None:
        if owner is None:
            return
        values = _inline_code_values(token)
        line_numbers = _line_numbers_for_code_values(token, values, lines)
        for value, line_no in zip(values, line_numbers, strict=True):
            kind, target_path, target_symbol = classify_mapping_token(value)
            mappings.append(
                SpecMapping(
                    spec_path=rel_path,
                    section_id=owner.section_id,
                    line=line_no,
                    target=value,
                    kind=kind,
                    target_path=target_path,
                    target_symbol=target_symbol,
                )
            )

    def report_ownerless_mapping(line_no: int) -> None:
        issues.append(
            Issue(
                code="MAPPING_BLOCK_OWNERLESS",
                severity="warning",
                path=rel_path,
                line=line_no,
                message=(
                    "implementation mapping block has no preceding"
                    " ID-bearing heading; its tokens are ignored"
                ),
            )
        )

    def process_invariant_paragraph(inline: Token, line_no: int) -> bool:
        source_lines = inline.content.splitlines()
        if not source_lines or not source_lines[0].lstrip().startswith(
            _RESERVED_INVARIANT_PREFIXES
        ):
            return False

        cursor = 0
        while cursor < len(source_lines):
            marker_text = source_lines[cursor].lstrip()
            if not marker_text.startswith(_RESERVED_INVARIANT_PREFIXES):
                break
            next_marker = cursor + 1
            while next_marker < len(source_lines) and not source_lines[
                next_marker
            ].lstrip().startswith(_RESERVED_INVARIANT_PREFIXES):
                next_marker += 1

            declaration = _INVARIANT_DECLARATION_RE.fullmatch(marker_text)
            parsed_id = None
            bracket = re.search(r"\[([^\[\]]+)\]", marker_text)
            if bracket is not None and re.fullmatch(
                SECTION_ID, bracket.group(1).strip()
            ):
                parsed_id = bracket.group(1).strip()
            marker_line = line_no + cursor
            if declaration is None or current_heading_section is None:
                issues.append(
                    Issue(
                        code="INVARIANT_MARKER_INVALID",
                        severity="error",
                        path=rel_path,
                        line=marker_line,
                        message=(
                            "Markdown invariant declaration requires one valid ID"
                            " and statement under an ID-bearing heading"
                        ),
                        invariant_id=parsed_id,
                    )
                )
                cursor = next_marker
                continue

            statement_lines = [declaration.group("statement").strip()]
            statement_lines.extend(
                line.strip() for line in source_lines[cursor + 1 : next_marker]
            )
            invariants.append(
                InvariantDeclaration(
                    invariant_id=declaration.group("id"),
                    statement="\n".join(statement_lines),
                    tier=(
                        "draft"
                        if declaration.group("prefix") == "Invariant (draft)"
                        else "required"
                    ),
                    declaration_kind="spec",
                    path=rel_path,
                    line=marker_line,
                    owner_symbol=None,
                    section_id=current_heading_section.section_id,
                )
            )
            cursor = next_marker
        return True

    def define_mapping_bullet_section(token: Token) -> SpecSection | None:
        bullet_def = _BULLET_DEF_TEXT_RE.match(_first_inline_line(token))
        if bullet_def is None:
            return None
        title = _mapping_bullet_title(bullet_def.group("title"))
        section = SpecSection(
            path=rel_path,
            section_id=bullet_def.group("id"),
            title=title,
            line=_token_start_line(token),
            anchor=None,
            kind="bullet",
        )
        sections.append(section)
        return section

    def process_heading(index: int) -> None:
        nonlocal current_heading_level
        nonlocal current_heading_section
        nonlocal last_non_marker_block
        nonlocal mapping_section
        nonlocal marker_window_open

        heading_open = tokens[index]
        inline = _next_inline(tokens, index)
        if inline is None:
            return
        line_no = _token_start_line(heading_open)
        level = _heading_level(heading_open)
        heading_text, trailing_meta, trailing_codes, warnings = (
            _strip_recognized_trailing_html_marker(
                inline.content,
                allow_unknown_codes=allow_unknown_codes,
                location=f"{rel_path}:{line_no}",
                path=rel_path,
                line=line_no,
            )
        )
        marker_diagnostics.extend(warnings)

        mapping_section = None
        last_non_marker_block = "other"
        anchors.append(github_anchor(heading_text, anchor_seen))
        with_id = _HEADING_ID_RE.match(heading_text)
        if with_id:
            section = SpecSection(
                path=rel_path,
                section_id=with_id.group("id"),
                title=with_id.group("title"),
                line=line_no,
                anchor=anchors[-1],
                kind="heading",
            )
            sections.append(section)
            current_heading_section = section
            current_heading_level = level
            marker_window_open = True
            if trailing_meta or trailing_codes:
                record_marker(trailing_meta, trailing_codes, line_no)
        elif level <= current_heading_level:
            # A same-or-shallower ID-less heading starts a region no section
            # owns. Deeper ID-less subheadings stay inside the owner so local
            # prose structure does not detach the next mapping block.
            current_heading_section = None
            marker_window_open = False

    def process_paragraph(index: int) -> None:
        nonlocal last_non_marker_block
        nonlocal mapping_section
        nonlocal marker_window_open

        paragraph_open = tokens[index]
        inline = _next_inline(tokens, index)
        if inline is None:
            return
        line_no = _token_start_line(inline, _token_start_line(paragraph_open))
        stripped = inline.content.strip()
        if stripped.lower().startswith("_traceability:") and parse_marker_text(
            stripped, line_no
        ):
            return
        if process_invariant_paragraph(inline, line_no):
            marker_window_open = False
            mapping_section = None
            last_non_marker_block = "other"
            return
        if _MAPPING_MARKER_TEXT_RE.match(inline.content):
            marker_window_open = False
            mapping_section = current_heading_section
            if mapping_section is None:
                report_ownerless_mapping(line_no)
            emit_mapping_tokens(inline, mapping_section)
            last_non_marker_block = "mapping_marker"
            return
        if inline.content.strip():
            marker_window_open = False
            mapping_section = None
            last_non_marker_block = "other"

    def process_mapping_list(start: int, end: int) -> None:
        nonlocal last_non_marker_block
        nonlocal mapping_section
        nonlocal marker_window_open

        marker_window_open = False
        for inline in _iter_list_item_first_inlines(tokens, start, end):
            invariant = _invariant_from_inline(inline)
            if invariant is not None:
                section_id, title = invariant
                section = SpecSection(
                    path=rel_path,
                    section_id=section_id,
                    title=title,
                    line=_token_start_line(inline),
                    anchor=None,
                    kind="invariant",
                )
                sections.append(section)
                marker_window_open = True
                continue
            mapping_bullet = define_mapping_bullet_section(inline)
            if mapping_bullet is not None:
                mapping_section = mapping_bullet
            emit_mapping_tokens(inline, mapping_section)
        last_non_marker_block = "mapping_list"

    def process_regular_list(start: int, end: int) -> None:
        nonlocal last_non_marker_block
        nonlocal mapping_section
        nonlocal marker_window_open

        mapping_section = None
        last_non_marker_block = "other"
        for inline in _iter_list_item_first_inlines(tokens, start, end):
            invariant = _invariant_from_inline(inline)
            if invariant is not None:
                section_id, title = invariant
                section = SpecSection(
                    path=rel_path,
                    section_id=section_id,
                    title=title,
                    line=_token_start_line(inline),
                    anchor=None,
                    kind="invariant",
                )
                sections.append(section)
                marker_window_open = True
            elif inline.content.strip():
                marker_window_open = False

    def process_html_block(token: Token) -> None:
        nonlocal last_non_marker_block
        nonlocal mapping_section
        nonlocal marker_window_open

        line_no = _token_start_line(token)
        stripped = token.content.strip()
        if stripped.startswith("<!--") and parse_marker_text(stripped, line_no):
            return
        if stripped:
            marker_window_open = False
            mapping_section = None
            last_non_marker_block = "other"

    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.type == "heading_open":
            process_heading(index)
            index += 3
            continue
        if token.type == "paragraph_open":
            process_paragraph(index)
            index += 3
            continue
        if token.type == "bullet_list_open":
            end = _list_close_index(tokens, index)
            if last_non_marker_block in {
                "mapping_marker",
                "mapping_list",
            } and _list_can_continue_mapping(tokens, index, end):
                process_mapping_list(index, end)
            else:
                process_regular_list(index, end)
            index = end + 1
            continue
        if token.type == "ordered_list_open":
            end = _container_close_index(
                tokens, index, "ordered_list_open", "ordered_list_close"
            )
            marker_window_open = False
            mapping_section = None
            last_non_marker_block = "other"
            index = end + 1
            continue
        if token.type == "blockquote_open":
            end = _container_close_index(
                tokens, index, "blockquote_open", "blockquote_close"
            )
            marker_window_open = False
            mapping_section = None
            last_non_marker_block = "other"
            index = end + 1
            continue
        if token.type == "html_block":
            process_html_block(token)
            index += 1
            continue
        if token.type in {"fence", "code_block"}:
            marker_window_open = False
            mapping_section = None
            last_non_marker_block = "other"
        index += 1

    return ParsedSpec(
        path=rel_path,
        sections=tuple(sections),
        mappings=tuple(mappings),
        anchors=tuple(anchors),
        issues=tuple(issues),
        invariants=tuple(invariants),
        file_meta=file_meta,
        file_ignores=frozenset(file_ignores),
        section_markers=tuple(
            (section_id, meta_flag, frozenset(codes))
            for section_id, (meta_flag, codes) in sorted(section_markers.items())
        ),
        marker_diagnostics=tuple(marker_diagnostics),
    )
