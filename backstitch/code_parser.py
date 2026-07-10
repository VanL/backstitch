"""Runtime-independent Python structure parsing for Backstitch.

Spec: docs/specs/02-backstitch-core.md [SC-4]
Spec: docs/specs/05-backstitch-invariants.md [INV-3]

`tree-sitter-python` owns Python syntax here. Backstitch consumes the resulting
tree as a traceability layer: owner spans, doc blocks, comments, and statement
spans. It does not maintain a parallel Python grammar.
"""

from __future__ import annotations

import ast
import bisect
from dataclasses import dataclass

import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser

_LANGUAGE_CAPSULE = tspython.language()
_LANGUAGE = Language(_LANGUAGE_CAPSULE)

_BLOCK_SEARCH_NODE_TYPES = frozenset(
    {
        "case_clause",
        "class_definition",
        "decorated_definition",
        "elif_clause",
        "else_clause",
        "except_clause",
        "finally_clause",
        "for_statement",
        "function_definition",
        "if_statement",
        "match_statement",
        "try_statement",
        "while_statement",
        "with_statement",
    }
)


@dataclass(frozen=True, slots=True)
class DocBlock:
    owner_qualname: str
    start_line: int
    text: str


@dataclass(frozen=True, slots=True)
class Definition:
    qualname: str
    name: str
    kind: str
    parent_qualname: str | None
    parent_kind: str | None
    start_line: int
    end_line: int
    attachment_line: int
    indent_column: int


@dataclass(frozen=True, slots=True)
class DocCandidate:
    owner_qualname: str
    owner_kind: str
    start_line: int
    end_line: int
    start_column: int
    raw_text: str
    node_type: str
    text: str | None
    definition_start: int
    definition_end: int


@dataclass(frozen=True, slots=True)
class CommentNode:
    line: int
    column: int
    text: str


@dataclass(frozen=True, slots=True)
class ParsedModule:
    parse_ok: bool
    error_line: int | None
    owner_spans: tuple[tuple[str, int, int], ...]
    doc_blocks: tuple[DocBlock, ...]
    comments: tuple[tuple[int, str], ...]
    statement_spans: tuple[tuple[int, int], ...]
    definitions: tuple[Definition, ...] = ()
    doc_candidates: tuple[DocCandidate, ...] = ()
    comment_nodes: tuple[CommentNode, ...] = ()


def parse_python_source(source: bytes) -> ParsedModule:
    """Parse UTF-8 Python source bytes into Backstitch's structure seam."""

    parser = Parser(_LANGUAGE)
    tree = parser.parse(source)
    root = tree.root_node
    line_index = _LineIndex(source)
    if root.has_error:
        return ParsedModule(
            parse_ok=False,
            error_line=_first_error_line(root, line_index),
            owner_spans=(),
            doc_blocks=(),
            comments=(),
            statement_spans=(),
            definitions=(),
            doc_candidates=(),
            comment_nodes=(),
        )
    source_lines = source.decode("utf-8").splitlines()
    owner_entries = _owner_entries(root, line_index, source)
    owner_spans = tuple(
        (entry.qualname, entry.start_line, entry.end_line) for entry in owner_entries
    )
    definitions = tuple(
        Definition(
            qualname=entry.qualname,
            name=entry.qualname.rsplit(".", 1)[-1],
            kind=entry.kind,
            parent_qualname=entry.parent_qualname,
            parent_kind=entry.parent_kind,
            start_line=entry.start_line,
            end_line=entry.end_line,
            attachment_line=entry.attachment_line,
            indent_column=entry.indent_column,
        )
        for entry in owner_entries
    )
    doc_candidates = tuple(
        _doc_candidates(root, owner_entries, line_index, len(source_lines), source)
    )
    doc_blocks = tuple(
        DocBlock(candidate.owner_qualname, candidate.start_line, candidate.text)
        for candidate in doc_candidates
        if candidate.text is not None
    )
    comment_nodes = tuple(_comment_nodes(root, line_index, source))
    return ParsedModule(
        parse_ok=True,
        error_line=None,
        owner_spans=owner_spans,
        doc_blocks=doc_blocks,
        comments=tuple(_comments(root, line_index)),
        statement_spans=tuple(_statement_spans(root, line_index)),
        definitions=definitions,
        doc_candidates=doc_candidates,
        comment_nodes=comment_nodes,
    )


@dataclass(frozen=True, slots=True)
class _LineIndex:
    starts: tuple[int, ...]

    def __init__(self, source: bytes) -> None:
        starts = [0]
        starts.extend(index + 1 for index, byte in enumerate(source) if byte == 10)
        object.__setattr__(self, "starts", tuple(starts))

    def line_for_byte(self, offset: int) -> int:
        return bisect.bisect_right(self.starts, max(offset, 0))


def _first_error_line(node: Node, line_index: _LineIndex) -> int:
    if node.is_error or node.is_missing:
        return _start_line(node, line_index)
    for child in node.children:
        if child.has_error or child.is_error or child.is_missing:
            return _first_error_line(child, line_index)
    return _start_line(node, line_index)


def _start_line(node: Node, line_index: _LineIndex) -> int:
    return line_index.line_for_byte(node.start_byte)


def _end_line(node: Node, line_index: _LineIndex) -> int:
    return _line_span(node, line_index)[1]


def _line_span(node: Node, line_index: _LineIndex) -> tuple[int, int]:
    start_byte = node.start_byte
    end_byte = node.end_byte
    start_line = line_index.line_for_byte(start_byte)
    end_line = line_index.line_for_byte(
        end_byte - 1 if end_byte > start_byte else start_byte
    )
    return start_line, end_line


def _node_text(node: Node) -> str:
    text = node.text
    if text is None:
        return ""
    return text.decode("utf-8")


@dataclass(frozen=True, slots=True)
class _OwnerEntry:
    qualname: str
    kind: str
    parent_qualname: str | None
    parent_kind: str | None
    start_line: int
    end_line: int
    attachment_line: int
    indent_column: int
    doc_candidate: DocCandidate | None


@dataclass(frozen=True, slots=True)
class _OwnerNodeEntry:
    qualname: str
    kind: str
    definition: Node
    wrapper: Node
    parent_qualname: str | None
    parent_kind: str | None


def _owner_entries(
    root: Node, line_index: _LineIndex, source: bytes
) -> list[_OwnerEntry]:
    owners: list[_OwnerEntry] = []
    for item in _owner_node_entries(root):
        start_line, end_line = _line_span(item.definition, line_index)
        owners.append(
            _OwnerEntry(
                qualname=item.qualname,
                kind=item.kind,
                parent_qualname=item.parent_qualname,
                parent_kind=item.parent_kind,
                start_line=start_line,
                end_line=end_line,
                attachment_line=_start_line(item.wrapper, line_index),
                indent_column=_node_indent(item.wrapper, source, line_index),
                doc_candidate=_doc_candidate_for_owner(
                    item.qualname,
                    item.kind,
                    item.definition,
                    line_index,
                    start_line,
                    end_line,
                    source,
                ),
            )
        )
    return owners


def _owner_node_entries(root: Node) -> list[_OwnerNodeEntry]:
    owners: list[_OwnerNodeEntry] = []

    def visit(
        node: Node,
        prefix: str,
        parent_qualname: str | None,
        parent_kind: str | None,
    ) -> None:
        definition = _definition_node(node)
        if definition is not None:
            name_node = definition.child_by_field_name("name")
            if name_node is None:
                return
            qualname = f"{prefix}{_node_text(name_node)}"
            kind = "class" if definition.type == "class_definition" else "function"
            owners.append(
                _OwnerNodeEntry(
                    qualname=qualname,
                    kind=kind,
                    definition=definition,
                    wrapper=(
                        node if node.type == "decorated_definition" else definition
                    ),
                    parent_qualname=parent_qualname,
                    parent_kind=parent_kind,
                )
            )
            for child in definition.children:
                visit(child, f"{qualname}.", qualname, kind)
            return
        for child in node.children:
            visit(child, prefix, parent_qualname, parent_kind)

    visit(root, "", None, None)
    return owners


def _definition_node(node: Node) -> Node | None:
    if node.type in {"class_definition", "function_definition"}:
        return node
    if node.type != "decorated_definition":
        return None
    for child in _named_children(node):
        if child.type in {"class_definition", "function_definition"}:
            return child
    return None


def _doc_candidates(
    root: Node,
    owner_entries: list[_OwnerEntry],
    line_index: _LineIndex,
    source_line_count: int,
    source: bytes,
) -> list[DocCandidate]:
    candidates: list[DocCandidate] = []
    module_candidate = _doc_candidate_for_owner(
        "module",
        "module",
        root,
        line_index,
        1,
        max(source_line_count, 1),
        source,
    )
    if module_candidate is not None:
        candidates.append(module_candidate)

    for entry in owner_entries:
        if entry.doc_candidate is not None:
            candidates.append(entry.doc_candidate)
    return candidates


def _doc_candidate_for_owner(
    owner: str,
    owner_kind: str,
    node: Node,
    line_index: _LineIndex,
    definition_start: int,
    definition_end: int,
    source: bytes,
) -> DocCandidate | None:
    body = node if node.type == "module" else node.child_by_field_name("body")
    if body is None:
        return None
    first_statement = _first_statement_child(body)
    if first_statement is None or first_statement.type != "expression_statement":
        return None
    expression = _first_non_comment_named_child(first_statement)
    if expression is None:
        return None
    literal_node = _unwrap_parenthesized(expression)
    if literal_node.type not in {"string", "concatenated_string"}:
        return None
    start_line, end_line = _line_span(literal_node, line_index)
    return DocCandidate(
        owner_qualname=owner,
        owner_kind=owner_kind,
        start_line=start_line,
        end_line=end_line,
        start_column=_node_indent(literal_node, source, line_index),
        raw_text=_node_text(literal_node),
        node_type=literal_node.type,
        text=_literal_string_value(literal_node),
        definition_start=definition_start,
        definition_end=definition_end,
    )


def _first_statement_child(container: Node) -> Node | None:
    for child in _named_children(container):
        if child.type == "comment":
            continue
        return child
    return None


def _first_non_comment_named_child(node: Node) -> Node | None:
    for child in _named_children(node):
        if child.type != "comment":
            return child
    return None


def _unwrap_parenthesized(node: Node) -> Node:
    current = node
    while current.type == "parenthesized_expression":
        child = _first_non_comment_named_child(current)
        if child is None:
            return current
        current = child
    return current


def _literal_string_value(node: Node) -> str | None:
    try:
        value = ast.literal_eval(_node_text(node))
    except (SyntaxError, ValueError):
        return None
    if not isinstance(value, str):
        return None
    return value


def _comments(root: Node, line_index: _LineIndex) -> list[tuple[int, str]]:
    comments: list[tuple[int, str]] = []

    def visit(node: Node) -> None:
        if node.type == "comment":
            comments.append(
                (_start_line(node, line_index), _node_text(node).lstrip("#").strip())
            )
            return
        for child in node.children:
            visit(child)

    visit(root)
    return comments


def _comment_nodes(
    root: Node,
    line_index: _LineIndex,
    source: bytes,
) -> list[CommentNode]:
    comments: list[CommentNode] = []

    def visit(node: Node) -> None:
        if node.type == "comment":
            comments.append(
                CommentNode(
                    line=_start_line(node, line_index),
                    column=_node_indent(node, source, line_index),
                    text=_node_text(node).lstrip("#").strip(),
                )
            )
            return
        for child in node.children:
            visit(child)

    visit(root)
    return comments


def _node_indent(node: Node, source: bytes, line_index: _LineIndex) -> int:
    start_byte = node.start_byte
    line_number = line_index.line_for_byte(start_byte)
    line_start = line_index.starts[line_number - 1]
    prefix = source[line_start:start_byte].decode("utf-8")
    return len(prefix.expandtabs(8))


def _statement_spans(root: Node, line_index: _LineIndex) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []

    def visit_container(container: Node) -> None:
        for child in _named_children(container):
            if child.type == "comment":
                continue
            if child.type == "case_clause":
                for block in _child_blocks(child):
                    visit_container(block)
                continue
            statement = _definition_node(child) or child
            spans.append(_line_span(statement, line_index))
            if child.type == "if_statement":
                _append_elif_statement_spans(child)
            for block in _child_blocks(child):
                visit_container(block)

    def _append_elif_statement_spans(if_statement: Node) -> None:
        end_line = _end_line(if_statement, line_index)
        for child in _named_children(if_statement):
            if child.type == "elif_clause":
                spans.append((_start_line(child, line_index), end_line))

    def _child_blocks(node: Node) -> list[Node]:
        blocks: list[Node] = []
        for child in _named_children(node):
            if child.type == "block":
                blocks.append(child)
            elif child.type in _BLOCK_SEARCH_NODE_TYPES:
                blocks.extend(_child_blocks(child))
        return blocks

    visit_container(root)
    spans.sort()
    return spans


def _named_children(node: Node) -> list[Node]:
    return [child for child in node.children if child.is_named]
