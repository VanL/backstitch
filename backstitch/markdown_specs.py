"""Markdown spec parsing for the backstitch-style-v1 grammar.

Spec: docs/specs/02-backstitch-core.md [SC-4], [SC-17]
Spec: docs/specs/05-backstitch-invariants.md [INV-3]
Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-2.1], [EVC-4.2],
[EVC-7], [EVC-8.3.2]
Grammar: docs/implementation/04-backstitch-style-traceability.md

Backstitch interprets traceability constructs over ``markdown-it-py`` CommonMark
tokens. Markdown block structure, including fences and indented code blocks,
belongs to the parser library.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import MutableMapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from markdown_it import MarkdownIt
from markdown_it.token import Token

from backstitch.canonical import canonical_repository_path, lf_split
from backstitch.exclusions import (
    RESERVED_SKIP_MARKER_RE,
    ParsedSuppressionDirective,
    SuppressionDiagnostic,
    parse_traceability_directive_line,
    parse_traceability_marker_line,
)
from backstitch.grammar import SECTION_ID
from backstitch.models import (
    InvariantDeclaration,
    Issue,
    MappingKind,
    ObligationSkipForm,
    SourceObligationSkip,
    SpecMapping,
    SpecSection,
    SuppressionDeclaration,
    SuppressionOrigin,
    SuppressionRule,
)

_MARKDOWN = MarkdownIt("commonmark")
_HEADING_ID_RE = re.compile(rf"^(?P<title>.+?)\s*\[(?P<id>{SECTION_ID})\]\s*$")
_HEADING_ID_CANDIDATE_RE = re.compile(
    r"^(?:(?P<title>.+?)\s*)?\[(?P<id>[^\[\]\r\n]*)\]\s*$"
)
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
_HTML_SKIP_PREFIX_RE = re.compile(
    r"<!--[ \t]*backstitch:[ \t]*skip-obligation\b", re.IGNORECASE
)
_TRACE_SKIP_PREFIX_RE = re.compile(
    r"^_Traceability:[ \t]*skip-obligation\b", re.IGNORECASE
)
_HTML_SKIP_RE = re.compile(
    r"^<!--[ \t]*backstitch:[ \t]*skip-obligation[ \t]+"
    r"\[(?P<target>[^\[\]\r\n]*)\][ \t]*(?P<reason>.*?)[ \t]*-->$"
)
_TRACE_SKIP_RE = re.compile(
    r"^_Traceability:[ \t]*skip-obligation[ \t]+"
    r"\[(?P<target>[^\[\]\r\n]*)\][ \t]*(?P<reason>.*?)[ \t]*_$"
)
_SUPPRESSION_DECLARATION_PREFIX_RE = re.compile(
    r"^_Traceability:[ \t]*suppression-declaration\b",
    re.IGNORECASE,
)
_SUPPRESSION_DECLARATION_RE = re.compile(
    r"^_Traceability:[ \t]*suppression-declaration[ \t]+"
    r"\[(?P<id>SUP-[A-Z0-9](?:[A-Z0-9.\-]*[A-Z0-9])?)\][ \t]+"
    r'(?P<reason>".*")[ \t]*_$',
)


@dataclass(slots=True)
class _SkipCandidate:
    target_id: str
    reason: str
    line: int
    form: ObligationSkipForm
    owner_section_id: str | None = None
    invalid: bool = False


def _skip_diagnostic(
    code: str,
    *,
    path: str,
    line: int,
    message: str,
) -> SuppressionDiagnostic:
    return SuppressionDiagnostic(
        code=code,
        path=path,
        line=line,
        message=f"{path}:{line}: {message}",
    )


def _is_skip_marker(text: str) -> bool:
    return bool(
        _HTML_SKIP_PREFIX_RE.search(text) or _TRACE_SKIP_PREFIX_RE.search(text.strip())
    )


def _parse_skip_marker(
    marker: str,
    *,
    path: str,
    line: int,
    form: ObligationSkipForm,
) -> tuple[_SkipCandidate | None, SuppressionDiagnostic | None]:
    """Parse one reserved skip line without ordinary suppression strictness."""

    stripped = marker.strip()
    match = (
        _TRACE_SKIP_RE.fullmatch(stripped)
        if form == "traceability"
        else _HTML_SKIP_RE.fullmatch(stripped)
    )
    if match is None:
        return None, _skip_diagnostic(
            "SUPPRESSION_INVALID_SYNTAX",
            path=path,
            line=line,
            message="malformed skip-obligation marker",
        )

    target_id = match.group("target").strip()
    if re.fullmatch(SECTION_ID, target_id) is None:
        return None, _skip_diagnostic(
            "SUPPRESSION_INVALID_SYNTAX",
            path=path,
            line=line,
            message="skip-obligation target is not one valid obligation ID",
        )

    raw_reason = match.group("reason").strip()
    if not raw_reason:
        return None, _skip_diagnostic(
            "SUPPRESSION_REASON_MISSING",
            path=path,
            line=line,
            message="skip-obligation requires one nonblank JSON-string reason",
        )
    if form != "traceability" and any(
        token in raw_reason for token in ("--", "<", ">")
    ):
        return None, _skip_diagnostic(
            "SUPPRESSION_INVALID_SYNTAX",
            path=path,
            line=line,
            message="HTML skip-obligation reason contains a forbidden raw token",
        )
    reason, reason_error = _decode_strict_reason(raw_reason)
    if reason_error == "syntax":
        return None, _skip_diagnostic(
            "SUPPRESSION_INVALID_SYNTAX",
            path=path,
            line=line,
            message="skip-obligation reason must be one strict JSON string",
        )
    if reason_error == "missing":
        return None, _skip_diagnostic(
            "SUPPRESSION_REASON_MISSING",
            path=path,
            line=line,
            message="skip-obligation reason is blank",
        )
    if reason_error == "bounds":
        return None, _skip_diagnostic(
            "SUPPRESSION_INVALID_SYNTAX",
            path=path,
            line=line,
            message="skip-obligation reason violates its bounded line-safe contract",
        )
    assert reason is not None
    return _SkipCandidate(target_id, reason, line, form), None


def _decode_strict_reason(raw_reason: str) -> tuple[str | None, str | None]:
    """Decode the one shared line-safe JSON reason contract ([EVC-8.3.2])."""

    try:
        reason = json.loads(raw_reason)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, "syntax"
    if not isinstance(reason, str):
        return None, "syntax"
    if not reason.strip():
        return None, "missing"
    try:
        reason_size = len(reason.encode("utf-8"))
    except UnicodeEncodeError:
        return None, "bounds"
    if reason_size > 4096 or any(char in reason for char in "\r\n\u2028\u2029"):
        return None, "bounds"
    return reason, None


def _extract_heading_skips(
    text: str,
    *,
    path: str,
    line: int,
) -> tuple[str, list[_SkipCandidate], list[SuppressionDiagnostic]]:
    """Remove reserved HTML comments so an invalid skip cannot hide a heading."""

    cleaned = text
    candidates: list[_SkipCandidate] = []
    diagnostics: list[SuppressionDiagnostic] = []
    search_from = 0
    while (prefix := _HTML_SKIP_PREFIX_RE.search(cleaned, search_from)) is not None:
        start = cleaned.rfind("<!--", 0, prefix.end())
        if start < 0:
            break
        close = cleaned.find("-->", prefix.end())
        end = len(cleaned) if close < 0 else close + 3
        marker = cleaned[start:end]
        after = cleaned[end:]
        candidate, diagnostic = _parse_skip_marker(
            marker,
            path=path,
            line=line,
            form="heading_html",
        )
        if diagnostic is not None:
            diagnostics.append(diagnostic)
        if candidate is not None:
            if after.strip():
                candidate.invalid = True
                diagnostics.append(
                    _skip_diagnostic(
                        "SUPPRESSION_INVALID_SYNTAX",
                        path=path,
                        line=line,
                        message="inline skip-obligation must be the final heading token",
                    )
                )
            candidates.append(candidate)
        cleaned = (cleaned[:start] + after).strip()
        search_from = 0
    return cleaned, candidates, diagnostics


def _resolve_skip_candidates(  # noqa: C901 approved [SC-17.1] RUFF-SUP-049 exception
    *,
    path: str,
    candidates: list[_SkipCandidate],
    sections: list[SpecSection],
    invariants: list[InvariantDeclaration],
    diagnostics: list[SuppressionDiagnostic],
) -> tuple[SourceObligationSkip, ...]:
    """Resolve target ownership only after the complete file is parsed."""

    by_target: dict[str, list[_SkipCandidate]] = {}
    for candidate in candidates:
        if not candidate.invalid:
            by_target.setdefault(candidate.target_id, []).append(candidate)
    for target_id, duplicates in by_target.items():
        if len(duplicates) < 2:
            continue
        for candidate in duplicates:
            candidate.invalid = True
        diagnostics.append(
            _skip_diagnostic(
                "SUPPRESSION_INVALID_SYNTAX",
                path=path,
                line=duplicates[1].line,
                message=f"duplicate skip-obligation for [{target_id}]",
            )
        )

    section_ids = {item.section_id for item in sections}
    invariants_by_id: dict[str, list[InvariantDeclaration]] = {}
    for declaration in invariants:
        invariants_by_id.setdefault(declaration.invariant_id, []).append(declaration)

    resolved: list[SourceObligationSkip] = []
    for candidate in candidates:
        if candidate.invalid or candidate.owner_section_id is None:
            continue
        obligation_id: str | None = None
        if candidate.target_id == candidate.owner_section_id:
            obligation_id = f"{path}#{candidate.target_id}"
        else:
            invariant_declarations = invariants_by_id.get(candidate.target_id, [])
            if any(
                item.section_id == candidate.owner_section_id
                for item in invariant_declarations
            ):
                obligation_id = f"invariant::{candidate.target_id}"
            elif candidate.target_id in section_ids or invariant_declarations:
                diagnostics.append(
                    _skip_diagnostic(
                        "SUPPRESSION_INVALID_SYNTAX",
                        path=path,
                        line=candidate.line,
                        message=(
                            f"skip-obligation target [{candidate.target_id}] is not"
                            " owned by this section"
                        ),
                    )
                )
            else:
                diagnostics.append(
                    _skip_diagnostic(
                        "SUPPRESSION_UNUSED",
                        path=path,
                        line=candidate.line,
                        message=(
                            f"skip-obligation target [{candidate.target_id}] has no"
                            " parsed obligation owner"
                        ),
                    )
                )
        if obligation_id is not None:
            resolved.append(
                SourceObligationSkip(
                    obligation_id=obligation_id,
                    target_id=candidate.target_id,
                    owner_section_id=candidate.owner_section_id,
                    reason=candidate.reason,
                    path=path,
                    line=candidate.line,
                    form=candidate.form,
                )
            )
    resolved.sort(key=lambda item: (item.path, item.line, item.obligation_id))
    return tuple(resolved)


@dataclass(frozen=True, slots=True)
class ParsedSpec:
    """Parse result for one Markdown spec file.

    Traceability markers ([EXC-4]) ride along: ``file_meta``/``file_ignores``
    from the pre-heading preamble, ``section_markers`` as
    ``(section_id, is_meta, ignore_codes)`` for markers following a section
    definition.

    Spec: docs/specs/08-intent-coverage.md [COV-8]
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
    obligation_skips: tuple[SourceObligationSkip, ...] = ()
    suppression_declarations: tuple[SuppressionDeclaration, ...] = ()
    suppression_rules: tuple[SuppressionRule, ...] = ()
    marker_diagnostics: tuple[SuppressionDiagnostic, ...] = ()
    section_spans: tuple[tuple[str, int, int], ...] = ()
    section_search_text: tuple[tuple[str, str], ...] = ()
    mapping_block_spans: tuple[tuple[str, int, int], ...] = ()


@dataclass(slots=True)
class _MarkdownParseProduct:
    tokens: tuple[Token, ...]
    parser_line_to_source_line: tuple[int, ...]
    parsed_by_path: dict[str, ParsedSpec]


MarkdownParseMemo = MutableMapping[tuple[str, bool], _MarkdownParseProduct]


@dataclass(frozen=True, slots=True)
class PacketRequirementText:
    """Exact line-preserving requirement projection for packet schema 3."""

    start_line: int
    end_line: int
    text: str


def _packet_source_lines(raw: bytes) -> list[str]:
    projected: list[str] = []
    for line in lf_split(raw.decode("utf-8", errors="replace"), keepends=True):
        if not line.endswith("\n"):
            projected.append(line)
            continue
        content = line[:-1]
        projected.append(content[:-1] if content.endswith("\r") else content)
    return projected


def _strip_final_html_directive(line: str, prefix: re.Pattern[str]) -> str:
    match = prefix.search(line)
    if match is None:
        return line
    start = line.rfind("<!--", 0, match.end())
    close = line.find("-->", match.end())
    if start < 0 or close < 0 or line[close + 3 :].strip():
        return line
    return line[:start].rstrip(" \t") + line[close + 3 :]


def project_section_packet_requirement(  # noqa: C901 approved [SC-17.1] RUFF-SUP-050 exception
    raw: bytes,
    *,
    path: str,
    section: SpecSection,
    end_line: int,
    mappings: Sequence[SpecMapping],
    skips: Sequence[SourceObligationSkip],
    declarations: Sequence[SuppressionDeclaration] = (),
) -> PacketRequirementText:
    """Mask parser-owned source directives without collapsing coordinates.

    The function consumes captured bytes and parser-owned records. It performs
    no filesystem read and preserves exactly one output line per physical
    section line, as required by [EVC-9.1].
    """

    lines = _packet_source_lines(raw)
    if (
        section.path != path
        or section.line < 1
        or end_line < section.line
        or end_line > len(lines)
    ):
        raise ValueError("section packet requirement span is outside captured source")
    mapping_lines = {
        item.line
        for item in mappings
        if item.spec_path == path and item.section_id == section.section_id
    }
    valid_skips = {item.line: item for item in skips if item.path == path}
    declaration_lines = {
        line_no
        for item in declarations
        if item.path == path
        for line_no in range(item.start_line, item.end_line + 1)
    }
    projected: list[str] = []
    for line_no in range(section.line, end_line + 1):
        line = lines[line_no - 1]
        stripped = line.strip()
        if line_no in declaration_lines:
            projected.append("")
            continue
        skip = valid_skips.get(line_no)
        if skip is not None:
            if line_no == section.line and skip.form == "heading_html":
                projected.append(
                    _strip_final_html_directive(line, _HTML_SKIP_PREFIX_RE)
                )
            else:
                projected.append("")
            continue
        if RESERVED_SKIP_MARKER_RE.search(stripped):
            if line_no == section.line and _HTML_SKIP_PREFIX_RE.search(line):
                projected.append(
                    _strip_final_html_directive(line, _HTML_SKIP_PREFIX_RE)
                )
            else:
                projected.append("")
            continue
        if line_no in mapping_lines or _MAPPING_MARKER_TEXT_RE.match(stripped):
            projected.append("")
            continue
        is_meta, marker_codes, _warnings = parse_traceability_marker_line(
            line,
            allow_unknown=True,
            location="packet requirement",
            path=path,
            line=line_no,
        )
        if is_meta or marker_codes:
            if line_no == section.line:
                projected.append(
                    _TRAILING_HTML_COMMENT_RE.sub("", line).rstrip()
                    if "<!--" in line
                    else line
                )
            else:
                projected.append("")
            continue
        projected.append(line)
    return PacketRequirementText(section.line, end_line, "\n".join(projected))


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


def _next_inline(tokens: Sequence[Token], index: int) -> Token | None:
    if index + 1 < len(tokens) and tokens[index + 1].type == "inline":
        return tokens[index + 1]
    return None


def _parser_line_source_map(text: str) -> tuple[int, ...]:
    """Map markdown-it parser lines to 1-based LF-physical source lines."""

    source_line = 1
    mapped = [source_line]
    index = 0
    while index < len(text):
        character = text[index]
        if character == "\r":
            if index + 1 < len(text) and text[index + 1] == "\n":
                source_line += 1
                mapped.append(source_line)
                index += 2
                continue
            mapped.append(source_line)
        elif character == "\n":
            source_line += 1
            mapped.append(source_line)
        index += 1
    return tuple(mapped)


def _token_start_line(
    token: Token,
    parser_line_to_source_line: tuple[int, ...],
    default: int = 1,
) -> int:
    if token.map:
        return parser_line_to_source_line[token.map[0]]
    return default


def _token_end_line(
    token: Token,
    parser_line_to_source_line: tuple[int, ...],
    default: int = 1,
) -> int:
    """Return Markdown-it's zero-based-exclusive end as one-based inclusive."""

    if token.map is None:
        return default
    return max(default, parser_line_to_source_line[token.map[1] - 1])


def _token_physical_content_lines(
    token: Token,
    parser_line_to_source_line: tuple[int, ...],
) -> tuple[tuple[int, str], ...]:
    """Project normalized token content back onto LF-physical source lines."""

    content_lines = lf_split(token.content)
    if not content_lines:
        return ()
    if token.map is None:
        return tuple((1, line) for line in content_lines)
    parser_start, parser_end = token.map
    if parser_start + len(content_lines) > parser_end:
        raise ValueError("markdown token content exceeds its parser line span")
    physical: list[tuple[int, str]] = []
    for offset, content in enumerate(content_lines):
        source_line = parser_line_to_source_line[parser_start + offset]
        if physical and physical[-1][0] == source_line:
            previous_line, previous_content = physical[-1]
            physical[-1] = (previous_line, previous_content + "\r" + content)
        else:
            physical.append((source_line, content))
    return tuple(physical)


def _inline_code_values(token: Token) -> tuple[str, ...]:
    return tuple(
        child.content for child in (token.children or []) if child.type == "code_inline"
    )


def _source_inline_code_values(
    token: Token,
    lines: list[str],
    parser_line_to_source_line: tuple[int, ...],
) -> tuple[str, ...]:
    """Restore exact authored scalars that markdown-it replaces before parsing."""

    parser_values = _inline_code_values(token)
    if not parser_values or token.map is None:
        return parser_values
    parser_start, parser_end = token.map
    source_start = parser_line_to_source_line[parser_start] - 1
    source_end = parser_line_to_source_line[parser_end - 1]
    source_spans = tuple(
        span
        for line in lines[source_start:source_end]
        for span in _iter_code_spans_on_line(line)
    )
    restored: list[str] = []
    span_cursor = 0
    for parser_value in parser_values:
        authored_value: str | None = None
        for index in range(span_cursor, len(source_spans)):
            source_value = source_spans[index]
            if source_value.replace("\x00", "\ufffd") != parser_value:
                continue
            authored_value = source_value
            span_cursor = index + 1
            break
        restored.append(parser_value if authored_value is None else authored_value)
    return tuple(restored)


def _normalize_code_span_source(raw: str) -> str:
    """Mirror CommonMark code-span whitespace normalization for line lookup."""

    normalized = raw.replace("\r\n", "\n").replace("\r", "\n").replace("\n", " ")
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
    token: Token,
    values: tuple[str, ...],
    lines: list[str],
    parser_line_to_source_line: tuple[int, ...],
) -> tuple[int, ...]:
    """Best-effort source lines for child code_inline tokens within token.map."""

    if not values:
        return ()
    if not token.map:
        return tuple(1 for _ in values)

    parser_start, parser_end = token.map
    start = parser_line_to_source_line[parser_start] - 1
    end = parser_line_to_source_line[parser_end - 1]
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


def _list_close_index(tokens: Sequence[Token], start: int) -> int:
    return _container_close_index(
        tokens, start, "bullet_list_open", "bullet_list_close"
    )


def _container_close_index(
    tokens: Sequence[Token], start: int, open_type: str, close_type: str
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
    tokens: Sequence[Token], start: int, end: int
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
    lines = lf_split(token.content)
    return lines[0].strip() if lines else ""


def _mapping_bullet_title(text: str) -> str:
    return text.split(" — ", 1)[0].removesuffix(" —").strip()


def _invariant_from_inline(token: Token) -> tuple[str, str] | None:
    invariant = _INVARIANT_TEXT_RE.match(_first_inline_line(token))
    if invariant is None:
        return None
    return invariant.group("id"), invariant.group("title").strip()


def _list_can_continue_mapping(tokens: Sequence[Token], start: int, end: int) -> bool:
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
) -> tuple[
    str,
    ParsedSuppressionDirective | None,
    list[SuppressionDiagnostic],
]:
    if "<!--" not in text:
        return text, None, []
    directive, warnings = parse_traceability_directive_line(
        text,
        allow_unknown=allow_unknown_codes,
        location=location,
        path=path,
        line=line,
    )
    if directive is not None or warnings:
        return (
            _TRAILING_HTML_COMMENT_RE.sub("", text).strip(),
            directive,
            warnings,
        )
    return text, None, []


def parse_markdown_spec(
    file_path: Path,
    repo_root: Path,
    *,
    allow_unknown_codes: bool = False,
) -> ParsedSpec:
    """Filesystem compatibility wrapper around the immutable byte parser."""

    rel_path = file_path.resolve().relative_to(repo_root.resolve()).as_posix()
    return parse_markdown_spec_bytes(
        file_path.read_bytes(),
        rel_path,
        allow_unknown_codes=allow_unknown_codes,
    )


@dataclass(slots=True)
class _TraceabilityReducer:
    """Reduce CommonMark tokens through Backstitch's cross-block state machine."""

    rel_path: str
    lines: list[str]
    tokens: tuple[Token, ...]
    parser_line_to_source_line: tuple[int, ...]
    allow_unknown_codes: bool
    sections: list[SpecSection] = field(default_factory=list)
    mappings: list[SpecMapping] = field(default_factory=list)
    invariants: list[InvariantDeclaration] = field(default_factory=list)
    anchors: list[str] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    anchor_seen: dict[str, int] = field(default_factory=dict)
    file_meta: bool = False
    file_ignores: set[str] = field(default_factory=set)
    section_markers: dict[str, tuple[bool, set[str]]] = field(default_factory=dict)
    skip_candidates: list[_SkipCandidate] = field(default_factory=list)
    suppression_declarations: list[SuppressionDeclaration] = field(default_factory=list)
    suppression_rules: list[SuppressionRule] = field(default_factory=list)
    marker_diagnostics: list[SuppressionDiagnostic] = field(default_factory=list)
    nonsemantic_lines: set[int] = field(default_factory=set)
    processed_declaration_lines: set[int] = field(default_factory=set)
    # Mapping blocks attach to the nearest preceding heading section.
    # Invariant bullets define sections but never own mapping blocks.
    current_heading_section: SpecSection | None = None
    current_heading_level: int = 0
    mapping_section: SpecSection | None = None
    last_non_marker_block: str = "other"
    mapping_block_spans: list[tuple[str, int, int]] = field(default_factory=list)
    active_mapping_block_index: int | None = None
    # [EXC-4] §4.2: this window opens on a section definition and closes on
    # its first body block. Only directives in the window attach to a section.
    marker_window_open: bool = False
    current_directive_owner: SpecSection | None = None
    ordinary_marker_count: int = 0
    block_skip_candidates: list[_SkipCandidate] = field(default_factory=list)

    def begin_directive_block(self, owner: SpecSection | None) -> None:
        self.current_directive_owner = owner
        self.ordinary_marker_count = 0
        self.block_skip_candidates = []

    def invalidate_block_skips(self, line_no: int, message: str) -> None:
        active = [item for item in self.block_skip_candidates if not item.invalid]
        if not active:
            return
        for item in active:
            item.invalid = True
        self.marker_diagnostics.append(
            _skip_diagnostic(
                "SUPPRESSION_INVALID_SYNTAX",
                path=self.rel_path,
                line=line_no,
                message=message,
            )
        )

    def record_skip(self, candidate: _SkipCandidate) -> None:
        if not self.marker_window_open or self.current_directive_owner is None:
            candidate.invalid = True
            self.marker_diagnostics.append(
                _skip_diagnostic(
                    "SUPPRESSION_INVALID_SYNTAX",
                    path=self.rel_path,
                    line=candidate.line,
                    message=(
                        "skip-obligation is outside the owning section's"
                        " directive block"
                    ),
                )
            )
        else:
            candidate.owner_section_id = self.current_directive_owner.section_id
            if self.ordinary_marker_count > 1:
                candidate.invalid = True
                self.marker_diagnostics.append(
                    _skip_diagnostic(
                        "SUPPRESSION_INVALID_SYNTAX",
                        path=self.rel_path,
                        line=candidate.line,
                        message=(
                            "skip-obligation cannot coexist with more than one"
                            " ordinary traceability directive"
                        ),
                    )
                )
        self.skip_candidates.append(candidate)
        self.block_skip_candidates.append(candidate)

    def record_marker(
        self,
        is_meta: bool,
        marker_codes: frozenset[str],
        line_no: int,
        declaration: str | None = None,
    ) -> None:
        if not self.sections:
            self.file_meta = self.file_meta or is_meta
            self.file_ignores.update(marker_codes if not is_meta else ())
            self.suppression_rules.append(
                SuppressionRule(
                    mechanism="meta" if is_meta else "ignore",
                    provenance="inline_spec",
                    path=self.rel_path,
                    sections=(),
                    codes=() if is_meta else tuple(sorted(marker_codes)),
                    declaration=declaration,
                    origin=SuppressionOrigin(source=self.rel_path, line=line_no),
                )
            )
            return
        if not self.marker_window_open:
            self.marker_diagnostics.append(
                SuppressionDiagnostic(
                    code="SUPPRESSION_INVALID_SYNTAX",
                    path=self.rel_path,
                    line=line_no,
                    message=(
                        f"{self.rel_path}:{line_no}: traceability marker after body"
                        " text is ignored ([EXC-4]: markers go immediately after"
                        " the heading)"
                    ),
                )
            )
            self.invalidate_block_skips(
                line_no,
                "body text cannot interleave an obligation skip and an ordinary"
                " traceability directive",
            )
            return
        self.ordinary_marker_count += 1
        if self.ordinary_marker_count > 1:
            self.invalidate_block_skips(
                line_no,
                "skip-obligation cannot coexist with more than one ordinary"
                " traceability directive",
            )
        elif any(item.form != "heading_html" for item in self.block_skip_candidates):
            self.invalidate_block_skips(
                line_no,
                "a standalone skip-obligation must follow the ordinary"
                " traceability directive",
            )
        target = (
            self.current_directive_owner.section_id
            if self.current_directive_owner is not None
            else self.sections[-1].section_id
        )
        meta_flag, codes = self.section_markers.setdefault(target, (False, set()))
        self.section_markers[target] = (
            meta_flag or is_meta,
            codes | (marker_codes if not is_meta else set()),
        )
        self.suppression_rules.append(
            SuppressionRule(
                mechanism="meta" if is_meta else "ignore",
                provenance="inline_spec",
                path=self.rel_path,
                sections=(target,),
                codes=() if is_meta else tuple(sorted(marker_codes)),
                declaration=declaration,
                origin=SuppressionOrigin(source=self.rel_path, line=line_no),
            )
        )

    def parse_marker_text(self, text: str, line_no: int) -> bool:
        directive, warnings = parse_traceability_directive_line(
            text,
            allow_unknown=self.allow_unknown_codes,
            location=f"{self.rel_path}:{line_no}",
            path=self.rel_path,
            line=line_no,
        )
        self.marker_diagnostics.extend(warnings)
        if directive is None:
            return False
        self.record_marker(
            directive.mechanism == "meta",
            directive.codes,
            line_no,
            directive.declaration,
        )
        self.nonsemantic_lines.add(line_no)
        return True

    def process_suppression_declaration(self, inline: Token, line_no: int) -> bool:
        """Parse one declaration paragraph without treating it as an ignore."""

        stripped = inline.content.strip()
        if _SUPPRESSION_DECLARATION_PREFIX_RE.match(stripped) is None:
            return False
        self.processed_declaration_lines.add(line_no)
        physical = _token_physical_content_lines(
            inline,
            self.parser_line_to_source_line,
        )
        match = (
            _SUPPRESSION_DECLARATION_RE.fullmatch(stripped)
            if len(physical) == 1
            else None
        )
        if match is None:
            self.marker_diagnostics.append(
                _skip_diagnostic(
                    "SUPPRESSION_INVALID_SYNTAX",
                    path=self.rel_path,
                    line=line_no,
                    message="malformed suppression-declaration marker",
                )
            )
            return True
        if self.current_heading_section is None:
            self.marker_diagnostics.append(
                _skip_diagnostic(
                    "SUPPRESSION_INVALID_SYNTAX",
                    path=self.rel_path,
                    line=line_no,
                    message=(
                        "suppression-declaration must be under an ID-bearing section"
                    ),
                )
            )
            return True
        rationale, reason_error = _decode_strict_reason(match.group("reason"))
        if reason_error is not None:
            self.marker_diagnostics.append(
                _skip_diagnostic(
                    (
                        "SUPPRESSION_REASON_MISSING"
                        if reason_error == "missing"
                        else "SUPPRESSION_INVALID_SYNTAX"
                    ),
                    path=self.rel_path,
                    line=line_no,
                    message=(
                        "suppression-declaration reason is blank"
                        if reason_error == "missing"
                        else (
                            "suppression-declaration reason violates its strict "
                            "bounded line-safe JSON-string contract"
                        )
                    ),
                )
            )
            return True
        assert rationale is not None
        declaration_id = match.group("id")
        self.suppression_declarations.append(
            SuppressionDeclaration(
                declaration_id=declaration_id,
                reference=f"{self.rel_path}#{declaration_id}",
                rationale=rationale,
                path=self.rel_path,
                owner_section_id=self.current_heading_section.section_id,
                owner_title=self.current_heading_section.title,
                start_line=line_no,
                end_line=line_no,
            )
        )
        self.nonsemantic_lines.add(line_no)
        return True

    def process_reserved_skip_lines(  # noqa: C901 approved [SC-17.1] RUFF-SUP-048 exception
        self,
        source_lines: Sequence[tuple[int, str]],
    ) -> tuple[bool, bool]:
        """Return whether a skip block was recognized and whether it had body."""

        if not any(_is_skip_marker(line) for _line_no, line in source_lines):
            return False, False
        contains_body = False
        local_candidates: list[_SkipCandidate] = []
        for line_no, raw_line in source_lines:
            stripped = raw_line.strip()
            if not stripped:
                continue
            if _is_skip_marker(stripped):
                form: ObligationSkipForm = (
                    "traceability" if _TRACE_SKIP_PREFIX_RE.search(stripped) else "html"
                )
                candidate, diagnostic = _parse_skip_marker(
                    stripped,
                    path=self.rel_path,
                    line=line_no,
                    form=form,
                )
                if diagnostic is not None:
                    self.marker_diagnostics.append(diagnostic)
                if candidate is not None:
                    self.record_skip(candidate)
                    local_candidates.append(candidate)
                continue
            if stripped.lower().startswith("_traceability:") or (
                stripped.startswith("<!--") and "backstitch:" in stripped.lower()
            ):
                if self.parse_marker_text(stripped, line_no):
                    continue
            contains_body = True
        active = [item for item in local_candidates if not item.invalid]
        if contains_body and active:
            for item in active:
                item.invalid = True
            self.marker_diagnostics.append(
                _skip_diagnostic(
                    "SUPPRESSION_INVALID_SYNTAX",
                    path=self.rel_path,
                    line=active[0].line,
                    message="body text interleaves the skip-obligation directive block",
                )
            )
        return True, contains_body

    def emit_mapping_tokens(self, token: Token, owner: SpecSection | None) -> None:
        if owner is None:
            return
        values = _source_inline_code_values(
            token,
            self.lines,
            self.parser_line_to_source_line,
        )
        line_numbers = _line_numbers_for_code_values(
            token,
            values,
            self.lines,
            self.parser_line_to_source_line,
        )
        start_line = _token_start_line(token, self.parser_line_to_source_line)
        end_line = _token_end_line(
            token,
            self.parser_line_to_source_line,
            start_line,
        )
        self.nonsemantic_lines.update(range(start_line, end_line + 1))
        for value, line_no in zip(values, line_numbers, strict=True):
            kind, target_path, target_symbol = classify_mapping_token(value)
            if target_path is not None:
                canonical_target = canonical_repository_path(target_path)
                if canonical_target is not None:
                    target_path = canonical_target.canonical
            self.mappings.append(
                SpecMapping(
                    spec_path=self.rel_path,
                    section_id=owner.section_id,
                    line=line_no,
                    target=value,
                    kind=kind,
                    target_path=target_path,
                    target_symbol=target_symbol,
                )
            )

    def report_ownerless_mapping(self, line_no: int) -> None:
        self.issues.append(
            Issue(
                code="MAPPING_BLOCK_OWNERLESS",
                severity="warning",
                path=self.rel_path,
                line=line_no,
                message=(
                    "implementation mapping block has no preceding"
                    " ID-bearing heading; its tokens are ignored"
                ),
            )
        )

    def process_invariant_paragraph(self, inline: Token) -> bool:
        source_lines = _token_physical_content_lines(
            inline,
            self.parser_line_to_source_line,
        )
        if not source_lines or not source_lines[0][1].lstrip().startswith(
            _RESERVED_INVARIANT_PREFIXES
        ):
            return False
        cursor = 0
        while cursor < len(source_lines):
            marker_line, source_text = source_lines[cursor]
            marker_text = source_text.lstrip()
            if not marker_text.startswith(_RESERVED_INVARIANT_PREFIXES):
                break
            next_marker = cursor + 1
            while next_marker < len(source_lines) and not source_lines[next_marker][
                1
            ].lstrip().startswith(_RESERVED_INVARIANT_PREFIXES):
                next_marker += 1
            self.record_invariant_declaration(
                marker_text,
                marker_line,
                source_lines[cursor + 1 : next_marker],
            )
            cursor = next_marker
        return True

    def record_invariant_declaration(
        self,
        marker_text: str,
        marker_line: int,
        continuation_lines: Sequence[tuple[int, str]],
    ) -> None:
        declaration = _INVARIANT_DECLARATION_RE.fullmatch(marker_text)
        parsed_id = None
        bracket = re.search(r"\[([^\[\]]+)\]", marker_text)
        if bracket is not None and re.fullmatch(SECTION_ID, bracket.group(1).strip()):
            parsed_id = bracket.group(1).strip()
        if declaration is None or self.current_heading_section is None:
            self.issues.append(
                Issue(
                    code="INVARIANT_MARKER_INVALID",
                    severity="error",
                    path=self.rel_path,
                    line=marker_line,
                    message=(
                        "Markdown invariant declaration requires one valid ID"
                        " and statement under an ID-bearing heading"
                    ),
                    invariant_id=parsed_id,
                )
            )
            return
        statement_lines = [declaration.group("statement").strip()]
        statement_lines.extend(line.strip() for _line_no, line in continuation_lines)
        self.invariants.append(
            InvariantDeclaration(
                invariant_id=declaration.group("id"),
                statement="\n".join(statement_lines),
                tier=(
                    "draft"
                    if declaration.group("prefix") == "Invariant (draft)"
                    else "required"
                ),
                declaration_kind="spec",
                path=self.rel_path,
                line=marker_line,
                owner_symbol=None,
                section_id=self.current_heading_section.section_id,
            )
        )

    def define_mapping_bullet_section(self, token: Token) -> SpecSection | None:
        bullet_def = _BULLET_DEF_TEXT_RE.match(_first_inline_line(token))
        if bullet_def is None:
            return None
        section = SpecSection(
            path=self.rel_path,
            section_id=bullet_def.group("id"),
            title=_mapping_bullet_title(bullet_def.group("title")),
            line=_token_start_line(token, self.parser_line_to_source_line),
            anchor=None,
            kind="bullet",
        )
        self.sections.append(section)
        self.begin_directive_block(section)
        return section

    def process_heading(self, index: int) -> None:
        heading_open = self.tokens[index]
        inline = _next_inline(self.tokens, index)
        if inline is None:
            return
        line_no = _token_start_line(heading_open, self.parser_line_to_source_line)
        level = _heading_level(heading_open)
        without_skip, heading_skips, skip_diagnostics = _extract_heading_skips(
            inline.content,
            path=self.rel_path,
            line=line_no,
        )
        self.marker_diagnostics.extend(skip_diagnostics)
        heading_text, trailing_directive, warnings = (
            _strip_recognized_trailing_html_marker(
                without_skip,
                allow_unknown_codes=self.allow_unknown_codes,
                location=f"{self.rel_path}:{line_no}",
                path=self.rel_path,
                line=line_no,
            )
        )
        self.marker_diagnostics.extend(warnings)
        self.mapping_section = None
        self.last_non_marker_block = "other"
        self.anchors.append(github_anchor(heading_text, self.anchor_seen))
        with_id = _HEADING_ID_RE.match(heading_text)
        if with_id:
            self.open_heading(
                with_id.group("id"),
                with_id.group("title"),
                line_no,
                level,
                heading_skips,
                trailing_directive,
            )
            return
        invalid_heading = _HEADING_ID_CANDIDATE_RE.match(heading_text)
        if invalid_heading is not None:
            self.reject_heading(
                invalid_heading.group("id"),
                invalid_heading.group("title"),
                line_no,
                level,
                heading_skips,
            )
            return
        if level <= self.current_heading_level:
            self.current_heading_section = None
            self.marker_window_open = False
            self.begin_directive_block(None)
            for candidate in heading_skips:
                self.record_skip(candidate)
        elif heading_skips:
            for candidate in heading_skips:
                candidate.invalid = True
                self.skip_candidates.append(candidate)
            self.marker_diagnostics.append(
                _skip_diagnostic(
                    "SUPPRESSION_INVALID_SYNTAX",
                    path=self.rel_path,
                    line=line_no,
                    message="inline skip-obligation heading has no obligation owner",
                )
            )

    def open_heading(
        self,
        section_id: str,
        title: str,
        line_no: int,
        level: int,
        heading_skips: Sequence[_SkipCandidate],
        trailing_directive: ParsedSuppressionDirective | None,
    ) -> None:
        section = SpecSection(
            path=self.rel_path,
            section_id=section_id,
            title=title,
            line=line_no,
            anchor=self.anchors[-1],
            kind="heading",
        )
        self.sections.append(section)
        self.current_heading_section = section
        self.current_heading_level = level
        self.marker_window_open = True
        self.begin_directive_block(section)
        for candidate in heading_skips:
            self.record_skip(candidate)
        if trailing_directive is None:
            return
        self.record_marker(
            trailing_directive.mechanism == "meta",
            trailing_directive.codes,
            line_no,
            trailing_directive.declaration,
        )
        if heading_skips:
            self.invalidate_block_skips(
                line_no,
                "an inline heading skip must be followed by an ordinary"
                " directive on the next source line",
            )

    def reject_heading(
        self,
        candidate_id: str,
        candidate_title: str | None,
        line_no: int,
        level: int,
        heading_skips: Sequence[_SkipCandidate],
    ) -> None:
        if candidate_id and re.fullmatch(SECTION_ID, candidate_id):
            message = "ID-bearing Markdown heading is missing a section title"
        elif candidate_title and candidate_title.strip():
            message = "ID-bearing Markdown heading has an invalid or missing section ID"
        else:
            message = "ID-bearing Markdown heading is missing a title and section ID"
        self.issues.append(
            Issue(
                code="SPEC_SECTION_HEADING_INVALID",
                severity="error",
                path=self.rel_path,
                line=line_no,
                message=message,
            )
        )
        if level <= self.current_heading_level:
            self.current_heading_section = None
            self.marker_window_open = False
            self.begin_directive_block(None)
        for candidate in heading_skips:
            candidate.invalid = True
            self.skip_candidates.append(candidate)

    def process_paragraph(self, index: int) -> None:
        paragraph_open = self.tokens[index]
        inline = _next_inline(self.tokens, index)
        if inline is None:
            return
        line_no = _token_start_line(
            inline,
            self.parser_line_to_source_line,
            _token_start_line(paragraph_open, self.parser_line_to_source_line),
        )
        source_start = _token_start_line(
            paragraph_open,
            self.parser_line_to_source_line,
            line_no,
        )
        source_end = _token_end_line(
            paragraph_open,
            self.parser_line_to_source_line,
            source_start,
        )
        recognized_skip, contains_body = self.process_reserved_skip_lines(
            _token_physical_content_lines(inline, self.parser_line_to_source_line)
        )
        if recognized_skip:
            if contains_body:
                self.close_marker_window()
            return
        stripped = inline.content.strip()
        if self.process_suppression_declaration(inline, line_no):
            return
        if stripped.lower().startswith("_traceability:") and self.parse_marker_text(
            stripped, line_no
        ):
            return
        if self.process_invariant_paragraph(inline):
            self.close_marker_window()
            return
        if _MAPPING_MARKER_TEXT_RE.match(inline.content):
            self.open_mapping_block(inline, line_no, source_start, source_end)
            return
        if stripped:
            self.active_mapping_block_index = None
            self.close_marker_window()

    def close_marker_window(self) -> None:
        self.marker_window_open = False
        self.mapping_section = None
        self.last_non_marker_block = "other"

    def open_mapping_block(
        self,
        inline: Token,
        line_no: int,
        source_start: int,
        source_end: int,
    ) -> None:
        self.nonsemantic_lines.update(range(source_start, source_end + 1))
        self.marker_window_open = False
        self.mapping_section = self.current_heading_section
        if self.mapping_section is None:
            self.report_ownerless_mapping(line_no)
            self.active_mapping_block_index = None
        else:
            self.mapping_block_spans.append(
                (self.mapping_section.section_id, source_start, source_end)
            )
            self.active_mapping_block_index = len(self.mapping_block_spans) - 1
        self.emit_mapping_tokens(inline, self.mapping_section)
        self.last_non_marker_block = "mapping_marker"

    def process_mapping_list(self, start: int, end: int) -> None:
        self.marker_window_open = False
        self.extend_active_mapping_span(start)
        for inline in _iter_list_item_first_inlines(self.tokens, start, end):
            invariant = _invariant_from_inline(inline)
            if invariant is not None:
                section_id, title = invariant
                section = self.append_list_section(
                    inline, section_id, title, "invariant"
                )
                self.begin_directive_block(section)
                self.marker_window_open = True
                continue
            mapping_bullet = self.define_mapping_bullet_section(inline)
            if mapping_bullet is not None:
                self.mapping_section = mapping_bullet
            self.record_mapping_bullet_span(inline)
            self.emit_mapping_tokens(inline, self.mapping_section)
        self.last_non_marker_block = "mapping_list"

    def extend_active_mapping_span(self, start: int) -> None:
        if self.active_mapping_block_index is None:
            return
        section_id, start_line, _ = self.mapping_block_spans[
            self.active_mapping_block_index
        ]
        list_end_line = _token_end_line(
            self.tokens[start],
            self.parser_line_to_source_line,
            start_line,
        )
        self.mapping_block_spans[self.active_mapping_block_index] = (
            section_id,
            start_line,
            list_end_line,
        )

    def append_list_section(
        self,
        inline: Token,
        section_id: str,
        title: str,
        kind: Literal["invariant", "bullet"],
    ) -> SpecSection:
        section = SpecSection(
            path=self.rel_path,
            section_id=section_id,
            title=title,
            line=_token_start_line(inline, self.parser_line_to_source_line),
            anchor=None,
            kind=kind,
        )
        self.sections.append(section)
        return section

    def record_mapping_bullet_span(self, inline: Token) -> None:
        if (
            self.mapping_section is None
            or self.mapping_section is self.current_heading_section
            or not _inline_code_values(inline)
        ):
            return
        mapping_line_start = _token_start_line(
            inline,
            self.parser_line_to_source_line,
        )
        self.mapping_block_spans.append(
            (
                self.mapping_section.section_id,
                mapping_line_start,
                _token_end_line(
                    inline,
                    self.parser_line_to_source_line,
                    mapping_line_start,
                ),
            )
        )

    def process_regular_list(self, start: int, end: int) -> None:
        self.mapping_section = None
        self.last_non_marker_block = "other"
        for inline in _iter_list_item_first_inlines(self.tokens, start, end):
            invariant = _invariant_from_inline(inline)
            if invariant is not None:
                section_id, title = invariant
                section = self.append_list_section(
                    inline, section_id, title, "invariant"
                )
                self.begin_directive_block(section)
                self.marker_window_open = True
            elif inline.content.strip():
                self.marker_window_open = False

    def process_html_block(self, token: Token) -> None:
        line_no = _token_start_line(token, self.parser_line_to_source_line)
        recognized_skip, contains_body = self.process_reserved_skip_lines(
            _token_physical_content_lines(token, self.parser_line_to_source_line)
        )
        if recognized_skip:
            if contains_body:
                self.close_marker_window()
            return
        stripped = token.content.strip()
        if stripped.startswith("<!--") and self.parse_marker_text(stripped, line_no):
            return
        if stripped:
            self.close_marker_window()

    def walk_tokens(self) -> None:
        index = 0
        while index < len(self.tokens):
            index = self.advance(index)

    def advance(self, index: int) -> int:
        """Apply one CommonMark block-token transition and return the next index."""

        token = self.tokens[index]
        if token.type == "heading_open":
            self.process_heading(index)
            return index + 3
        if token.type == "paragraph_open":
            self.process_paragraph(index)
            return index + 3
        if token.type == "bullet_list_open":
            return self.process_list(index)
        if token.type == "ordered_list_open":
            return self.skip_container(index, "ordered_list_open", "ordered_list_close")
        if token.type == "blockquote_open":
            return self.skip_container(index, "blockquote_open", "blockquote_close")
        if token.type == "html_block":
            self.process_html_block(token)
        elif token.type in {"fence", "code_block"}:
            self.close_marker_window()
        return index + 1

    def process_list(self, index: int) -> int:
        end = _list_close_index(self.tokens, index)
        if self.last_non_marker_block in {
            "mapping_marker",
            "mapping_list",
        } and _list_can_continue_mapping(self.tokens, index, end):
            self.process_mapping_list(index, end)
        else:
            self.process_regular_list(index, end)
        return end + 1

    def skip_container(self, index: int, open_type: str, close_type: str) -> int:
        end = _container_close_index(self.tokens, index, open_type, close_type)
        self.close_marker_window()
        return end + 1

    def declaration_candidate_lines(self) -> set[int]:
        return {
            line_no
            for line_no, source_line in enumerate(self.lines, start=1)
            if "suppression-declaration" in source_line.lower()
            and (
                source_line.strip().lower().startswith("_traceability:")
                or (
                    source_line.strip().startswith(("<!--", "#"))
                    and "_traceability:" in source_line.lower()
                )
            )
        }

    def finish(self) -> ParsedSpec:
        obligation_skips = _resolve_skip_candidates(
            path=self.rel_path,
            candidates=self.skip_candidates,
            sections=self.sections,
            invariants=self.invariants,
            diagnostics=self.marker_diagnostics,
        )
        self.report_unprocessed_declarations()
        section_spans = self.build_section_spans()
        self.nonsemantic_lines.update(item.line for item in obligation_skips)
        section_search_text = self.build_section_search_text(section_spans)
        return ParsedSpec(
            path=self.rel_path,
            sections=tuple(self.sections),
            mappings=tuple(self.mappings),
            anchors=tuple(self.anchors),
            issues=tuple(self.issues),
            invariants=tuple(self.invariants),
            file_meta=self.file_meta,
            file_ignores=frozenset(self.file_ignores),
            section_markers=tuple(
                (section_id, meta_flag, frozenset(codes))
                for section_id, (meta_flag, codes) in sorted(
                    self.section_markers.items()
                )
            ),
            obligation_skips=obligation_skips,
            suppression_declarations=tuple(self.suppression_declarations),
            suppression_rules=tuple(self.suppression_rules),
            marker_diagnostics=tuple(self.marker_diagnostics),
            section_spans=tuple(section_spans),
            section_search_text=section_search_text,
            mapping_block_spans=tuple(self.mapping_block_spans),
        )

    def report_unprocessed_declarations(self) -> None:
        unprocessed = (
            self.declaration_candidate_lines() - self.processed_declaration_lines
        )
        for line_no in sorted(unprocessed):
            self.marker_diagnostics.append(
                _skip_diagnostic(
                    "SUPPRESSION_INVALID_SYNTAX",
                    path=self.rel_path,
                    line=line_no,
                    message=(
                        "suppression-declaration must be ordinary paragraph content "
                        "under an ID-bearing section"
                    ),
                )
            )

    def build_section_spans(self) -> list[tuple[str, int, int]]:
        heading_boundaries = [
            (
                _token_start_line(token, self.parser_line_to_source_line),
                _heading_level(token),
            )
            for token in self.tokens
            if token.type == "heading_open"
        ]
        inline_ends = self.inline_end_lines()
        file_end_line = max(1, len(self.lines))
        return [
            (
                section.section_id,
                section.line,
                self.section_end_line(
                    section, heading_boundaries, inline_ends, file_end_line
                ),
            )
            for section in self.sections
        ]

    def inline_end_lines(self) -> dict[int, int]:
        inline_ends: dict[int, int] = {}
        for token in self.tokens:
            if token.type != "inline":
                continue
            start = _token_start_line(token, self.parser_line_to_source_line)
            inline_ends[start] = max(
                inline_ends.get(start, start),
                _token_end_line(token, self.parser_line_to_source_line, start),
            )
        return inline_ends

    @staticmethod
    def section_end_line(
        section: SpecSection,
        heading_boundaries: Sequence[tuple[int, int]],
        inline_ends: dict[int, int],
        file_end_line: int,
    ) -> int:
        if section.kind != "heading":
            return inline_ends.get(section.line, section.line)
        level = next(
            (
                heading_level
                for heading_line, heading_level in heading_boundaries
                if heading_line == section.line
            ),
            0,
        )
        for heading_line, heading_level in heading_boundaries:
            if heading_line > section.line and heading_level <= level:
                return heading_line - 1
        return file_end_line

    def build_section_search_text(
        self,
        section_spans: Sequence[tuple[str, int, int]],
    ) -> tuple[tuple[str, str], ...]:
        return tuple(
            (
                section_id,
                "\n".join(
                    self.lines[line_no - 1]
                    for line_no in range(start_line, end_line + 1)
                    if line_no not in self.nonsemantic_lines
                ),
            )
            for section_id, start_line, end_line in section_spans
        )


def parse_markdown_spec_bytes(
    source: bytes,
    rel_path: str,
    *,
    allow_unknown_codes: bool = False,
    parse_memo: MarkdownParseMemo | None = None,
) -> ParsedSpec:
    """Parse one captured Markdown source without reopening the repository.

    Spec: docs/specs/08-intent-coverage.md [COV-8]
    """

    text = source.decode("utf-8")
    memo_key = (hashlib.sha256(source).hexdigest(), allow_unknown_codes)
    product = None if parse_memo is None else parse_memo.get(memo_key)
    if product is not None:
        cached_result = product.parsed_by_path.get(rel_path)
        if cached_result is not None:
            return cached_result
    else:
        product = _MarkdownParseProduct(
            tuple(_MARKDOWN.parse(text)),
            _parser_line_source_map(text),
            {},
        )
        if parse_memo is not None:
            parse_memo[memo_key] = product

    reducer = _TraceabilityReducer(
        rel_path=rel_path,
        lines=list(lf_split(text)),
        tokens=product.tokens,
        parser_line_to_source_line=product.parser_line_to_source_line,
        allow_unknown_codes=allow_unknown_codes,
    )
    reducer.walk_tokens()
    result = reducer.finish()
    if parse_memo is not None:
        product.parsed_by_path[rel_path] = result
    return result
