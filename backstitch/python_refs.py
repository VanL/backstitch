"""Python code backlink parsing for the backstitch-style-v1 grammar.

Spec: docs/specs/02-backstitch-core.md [SC-4]
Grammar: docs/implementation/04-backstitch-style-traceability.md

Docstrings are read through ``ast``; comments through ``tokenize`` so line
numbers are real. The parser emits every ID-shaped bare bracket candidate;
the resolver filters candidates whose alphabetic prefix is unknown to the
spec corpus, so indexing noise like ``window[N-1]`` stays silent while
prose references like ``see [MA-1.1]`` still resolve.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from dataclasses import dataclass
from pathlib import Path

from backstitch.grammar import SECTION_ID
from backstitch.models import CodeRef, Issue, RefContext

_ID_RE = re.compile(rf"^{SECTION_ID}$")
_PREFIX_RE = re.compile(r"^[A-Z][A-Za-z]*")
_MD_PATH_RE = re.compile(
    r"(?P<path>[\w.-]+(?:/[\w.-]+)*\.md)(?:#(?P<anchor>[\w-]+))?"
)
_BRACKET_RE = re.compile(r"\[(?P<content>[^\[\]]+)\]")
_CROSS_RANGE_RE = re.compile(
    rf"\[(?P<start>{SECTION_ID})\]\s*[-–—]{{1,2}}\s*\[(?P<end>{SECTION_ID})\]"
)
_ADJACENT_BRACKET_RE = re.compile(r"\s*(?P<sep>[,–—-]|--)?\s*\[[^\[\]]+\]")
_DASH_CHARS = "-–—"


@dataclass(frozen=True, slots=True)
class ParsedPython:
    """Parse result for one Python file."""

    path: str
    refs: tuple[CodeRef, ...]
    issues: tuple[Issue, ...]


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
        if (
            left_prefix
            and right_prefix
            and left_prefix.group() == right_prefix.group()
        ):
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


def _iter_owner_spans(tree: ast.Module) -> list[tuple[str, int, int, ast.AST]]:
    """Return ``(qualname, start, end, node)`` for classes and functions."""

    spans: list[tuple[str, int, int, ast.AST]] = []

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(
                child, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
            ):
                qualname = f"{prefix}{child.name}"
                end = child.end_lineno or child.lineno
                spans.append((qualname, child.lineno, end, child))
                visit(child, f"{qualname}.")
            else:
                visit(child, prefix)

    visit(tree, "")
    return spans


def _docstring_node(node: ast.AST) -> ast.Constant | None:
    body = getattr(node, "body", None)
    if not body:
        return None
    first = body[0]
    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        return first.value
    return None


def python_symbol_spans(file_path: Path) -> dict[str, tuple[int, int]] | None:
    """Return ``{qualname: (start_line, end_line)}``, or None on syntax error."""

    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
    except SyntaxError:
        return None
    return {
        qualname: (start, end)
        for qualname, start, end, _node in _iter_owner_spans(tree)
    }


def python_symbol_inventory(file_path: Path) -> frozenset[str] | None:
    """Return the qualified class/function names in a file, or None on
    syntax error."""

    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
    except SyntaxError:
        return None
    return frozenset(qualname for qualname, _, _, _ in _iter_owner_spans(tree))


def parse_python_file(file_path: Path, repo_root: Path) -> ParsedPython:
    """Parse one Python file into code refs, or a syntax-error issue."""

    rel_path = file_path.resolve().relative_to(repo_root.resolve()).as_posix()
    source = file_path.read_text(encoding="utf-8")

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        issue = Issue(
            code="PYTHON_SYNTAX_ERROR",
            severity="error",
            path=rel_path,
            line=exc.lineno,
            message=f"could not parse requested Python file: {exc.msg}",
        )
        return ParsedPython(path=rel_path, refs=(), issues=(issue,))

    refs: list[CodeRef] = []

    def emit(
        owner: str, line_no: int, text: str, context: RefContext
    ) -> None:
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

    owner_spans = _iter_owner_spans(tree)

    # Docstrings: module first, then each class/function owner.
    docstring_owners: list[tuple[str, ast.AST]] = [("module", tree)]
    docstring_owners.extend((qualname, node) for qualname, _, _, node in owner_spans)
    for owner, node in docstring_owners:
        docstring = _docstring_node(node)
        if docstring is None:
            continue
        for offset, text_line in enumerate(str(docstring.value).splitlines()):
            emit(owner, docstring.lineno + offset, text_line, "docstring")

    # Comments, with the innermost enclosing owner.
    def owner_for_line(line_no: int) -> str:
        best: str | None = None
        best_size: int | None = None
        for qualname, start, end, _node in owner_spans:
            if start <= line_no <= end:
                size = end - start
                if best_size is None or size < best_size:
                    best, best_size = qualname, size
        return best or "module"

    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            comment_text = token.string.lstrip("#").strip()
            emit(
                owner_for_line(token.start[0]),
                token.start[0],
                comment_text,
                "comment",
            )

    return ParsedPython(path=rel_path, refs=tuple(refs), issues=())
