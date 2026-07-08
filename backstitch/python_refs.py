"""Python code backlink parsing for the backstitch-style-v1 grammar.

Spec: docs/specs/02-backstitch-core.md [SC-4]
Grammar: docs/implementation/04-backstitch-style-traceability.md

Python structure is read through ``tree-sitter-python`` so the parser is not
locked to the running interpreter's grammar. The parser emits every ID-shaped
bare bracket candidate;
the resolver filters candidates whose alphabetic prefix is unknown to the
spec corpus, so indexing noise like ``window[N-1]`` stays silent while
prose references like ``see [MA-1.1]`` still resolve.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from backstitch.code_parser import parse_python_source
from backstitch.exclusions import parse_noqa_text
from backstitch.grammar import SECTION_ID
from backstitch.models import CodeRef, Issue, RefContext

_ID_RE = re.compile(rf"^{SECTION_ID}$")
_PREFIX_RE = re.compile(r"^[A-Z][A-Za-z]*")
_MD_PATH_RE = re.compile(r"(?P<path>[\w.-]+(?:/[\w.-]+)*\.md)(?:#(?P<anchor>[\w-]+))?")
_BRACKET_RE = re.compile(r"\[(?P<content>[^\[\]]+)\]")
_CROSS_RANGE_RE = re.compile(
    rf"\[(?P<start>{SECTION_ID})\]\s*[-–—]{{1,2}}\s*\[(?P<end>{SECTION_ID})\]"
)
_ADJACENT_BRACKET_RE = re.compile(r"\s*(?P<sep>[,–—-]|--)?\s*\[[^\[\]]+\]")
_DASH_CHARS = "-–—"


@dataclass(frozen=True, slots=True)
class ParsedPython:
    """Parse result for one Python file.

    ``module_noqa`` holds codes suppressed for the whole file (docstring
    form, [EXC-5]); ``span_noqa`` holds ``(start, end, codes)`` for
    comment-form directives, scoped to the NEXT STATEMENT only -- file-wide
    bleed of a comment directive is the [EXC-9] regression class.
    """

    path: str
    refs: tuple[CodeRef, ...]
    issues: tuple[Issue, ...]
    module_noqa: frozenset[str] = frozenset()
    span_noqa: tuple[tuple[int, int, frozenset[str]], ...] = ()
    noqa_warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _LineRef:
    """One reference extracted from a docstring or comment line."""

    spec_path: str | None
    anchor: str | None
    section_ids: tuple[str, ...]
    ranges: tuple[tuple[str, str], ...]


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
        source = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    parsed = parse_python_source(source.encode("utf-8"))
    if not parsed.parse_ok:
        return None
    return {qualname: (start, end) for qualname, start, end in parsed.owner_spans}


def python_symbol_inventory(file_path: Path) -> frozenset[str] | None:
    """Return the qualified class/function names in a file, or None on
    syntax error."""

    try:
        source = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    parsed = parse_python_source(source.encode("utf-8"))
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


def parse_python_file(
    file_path: Path,
    repo_root: Path,
    *,
    allow_unknown_codes: bool = False,
) -> ParsedPython:
    """Parse one Python file into code refs, or a syntax-error issue."""

    rel_path = file_path.resolve().relative_to(repo_root.resolve()).as_posix()
    source = file_path.read_text(encoding="utf-8")
    parsed = parse_python_source(source.encode("utf-8"))
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

    # Doc blocks: module first, then each class/function owner.
    for doc_block in parsed.doc_blocks:
        for offset, text_line in enumerate(doc_block.text.splitlines()):
            # [SC-11] context: a `Spec:` marker line ASSERTS a trace edge;
            # any other docstring line is prose. The distinction is made
            # here, at parse time, never re-inferred downstream.
            context: RefContext = (
                "asserted" if text_line.lstrip().startswith("Spec:") else "docstring"
            )
            emit(
                doc_block.owner_qualname,
                doc_block.start_line + offset,
                text_line,
                context,
            )

    # [EXC-5] module-docstring noqa: file-scoped suppression codes.
    noqa_warnings: list[str] = []
    module_doc = next(
        (doc for doc in parsed.doc_blocks if doc.owner_qualname == "module"), None
    )
    if module_doc is not None:
        module_noqa, doc_warnings = parse_noqa_text(
            module_doc.text,
            allow_unknown=allow_unknown_codes,
            location=f"{rel_path} module docstring",
        )
        noqa_warnings.extend(doc_warnings)
    else:
        module_noqa = frozenset()

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
    for line_no, comment_text in parsed.comments:
        codes, comment_warnings = parse_noqa_text(
            comment_text,
            allow_unknown=allow_unknown_codes,
            location=f"{rel_path}:{line_no}",
        )
        noqa_warnings.extend(comment_warnings)
        if codes:
            # [EXC-5] comment form: next statement only, never file-wide.
            span = _next_statement_span(line_no, statement_spans)
            if span is not None:
                span_noqa.append((span[0], span[1], codes))
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
        issues=(),
        module_noqa=module_noqa,
        span_noqa=tuple(span_noqa),
        noqa_warnings=tuple(noqa_warnings),
    )
