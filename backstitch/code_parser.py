"""Runtime-independent Python structure parsing for Backstitch.

Spec: docs/specs/02-backstitch-core.md [SC-4]

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
class ParsedModule:
    parse_ok: bool
    error_line: int | None
    owner_spans: tuple[tuple[str, int, int], ...]
    doc_blocks: tuple[DocBlock, ...]
    comments: tuple[tuple[int, str], ...]
    statement_spans: tuple[tuple[int, int], ...]


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
        )
    owner_nodes = _owner_nodes(root)
    owner_spans = tuple(
        (qualname, _start_line(node, line_index), _end_line(node, line_index))
        for qualname, node in owner_nodes
    )
    return ParsedModule(
        parse_ok=True,
        error_line=None,
        owner_spans=owner_spans,
        doc_blocks=tuple(_doc_blocks(root, owner_nodes, line_index)),
        comments=tuple(_comments(root, line_index)),
        statement_spans=tuple(_statement_spans(root, line_index)),
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
    if node.end_byte > node.start_byte:
        return line_index.line_for_byte(node.end_byte - 1)
    return line_index.line_for_byte(node.start_byte)


def _node_text(node: Node) -> str:
    text = node.text
    if text is None:
        return ""
    return text.decode("utf-8")


def _owner_nodes(root: Node) -> list[tuple[str, Node]]:
    owners: list[tuple[str, Node]] = []

    def visit(node: Node, prefix: str) -> None:
        definition = _definition_node(node)
        if definition is not None:
            name_node = definition.child_by_field_name("name")
            if name_node is None:
                return
            qualname = f"{prefix}{_node_text(name_node)}"
            owners.append((qualname, definition))
            for child in definition.children:
                visit(child, f"{qualname}.")
            return
        for child in node.children:
            visit(child, prefix)

    visit(root, "")
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


def _doc_blocks(
    root: Node, owner_nodes: list[tuple[str, Node]], line_index: _LineIndex
) -> list[DocBlock]:
    blocks: list[DocBlock] = []
    module_doc = _doc_block_for_owner("module", root, line_index)
    if module_doc is not None:
        blocks.append(module_doc)
    for qualname, node in owner_nodes:
        doc = _doc_block_for_owner(qualname, node, line_index)
        if doc is not None:
            blocks.append(doc)
    return blocks


def _doc_block_for_owner(
    owner: str, node: Node, line_index: _LineIndex
) -> DocBlock | None:
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
    value = _literal_string_value(literal_node)
    if value is None:
        return None
    return DocBlock(owner, _start_line(literal_node, line_index), value)


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
    if _contains_interpolation(node):
        return None
    try:
        value = ast.literal_eval(_node_text(node))
    except (SyntaxError, ValueError):
        return None
    if not isinstance(value, str):
        return None
    return value


def _contains_interpolation(node: Node) -> bool:
    if node.type == "interpolation":
        return True
    return any(_contains_interpolation(child) for child in node.children)


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
            spans.append(
                (_start_line(statement, line_index), _end_line(statement, line_index))
            )
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
