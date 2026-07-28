"""Runtime-independent Python structure parsing for Backstitch.

Spec: docs/specs/02-backstitch-core.md [SC-4]
Spec: docs/specs/05-backstitch-invariants.md [INV-3]
Spec: docs/specs/05-backstitch-invariants.md [INV-11]
Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-4.2], [EVC-7],
[EVC-7.2]

`tree-sitter-python` owns Python syntax here. Backstitch consumes the resulting
tree as a traceability layer: owner spans, doc blocks, comments, and statement
spans. It does not maintain a parallel Python grammar.
"""

from __future__ import annotations

import ast
import bisect
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser

from backstitch.canonical import lf_line_count, lf_split

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
_DEFINITION_SEARCH_NODE_TYPES = _BLOCK_SEARCH_NODE_TYPES | {
    "block",
    "case_clause",
    "module",
}

# Bindings beneath these nodes may not execute, may execute more than once, or
# may come from mutually exclusive branches.  The static evidence resolver
# treats them as uncertain instead of projecting a false exact target.
_CONDITIONAL_BINDING_NODE_TYPES = frozenset(
    {
        "boolean_operator",
        "conditional_expression",
        "dictionary_comprehension",
        "for_statement",
        "generator_expression",
        "if_statement",
        "list_comprehension",
        "match_statement",
        "set_comprehension",
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
    scope_start_byte: int
    parent_scope_start_byte: int | None
    conditional: bool


@dataclass(frozen=True, slots=True)
class StaticImportAlias:
    imported: tuple[str, ...]
    bound_name: str
    source_order: int


@dataclass(frozen=True, slots=True)
class StaticReference:
    owner_scope_start_byte: int | None
    owner_qualname: str | None
    node_kind: Literal["import", "call", "name", "attribute"]
    source_order: int
    line: int
    name_parts: tuple[str, ...] = ()
    import_module: str | None = None
    relative_level: int = 0
    import_aliases: tuple[StaticImportAlias, ...] = ()
    literal_argument: str | None = None
    literal_arguments: tuple[str | None, ...] = ()
    is_load: bool = True
    conditional: bool = False


@dataclass(frozen=True, slots=True)
class StaticBinding:
    owner_scope_start_byte: int | None
    owner_qualname: str | None
    name: str
    source_order: int
    kind: Literal["parameter", "import", "definition", "assignment", "delete"]
    conditional: bool = False


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
    static_references: tuple[StaticReference, ...] = ()
    static_bindings: tuple[StaticBinding, ...] = ()


def parse_python_source(
    source: bytes, *, include_static_facts: bool = False
) -> ParsedModule:
    """Parse Python structure, deriving costly static facts only on request."""

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
    source_text = source.decode("utf-8")
    owner_nodes = _owner_node_entries(root, line_index, source)
    owner_entries = _owner_entries(owner_nodes, line_index, source)
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
            scope_start_byte=entry.scope_start_byte,
            parent_scope_start_byte=entry.parent_scope_start_byte,
            conditional=entry.conditional,
        )
        for entry in owner_entries
    )
    doc_candidates = tuple(
        _doc_candidates(
            root, owner_entries, line_index, lf_line_count(source_text), source
        )
    )
    doc_blocks = tuple(
        DocBlock(candidate.owner_qualname, candidate.start_line, candidate.text)
        for candidate in doc_candidates
        if candidate.text is not None
    )
    comment_nodes = tuple(_comment_nodes(root, line_index, source))
    static_references: tuple[StaticReference, ...] = ()
    static_bindings: tuple[StaticBinding, ...] = ()
    if include_static_facts:
        static_references, static_bindings = _static_syntax_facts(
            root, owner_nodes, line_index
        )
    return ParsedModule(
        parse_ok=True,
        error_line=None,
        owner_spans=owner_spans,
        doc_blocks=doc_blocks,
        comments=tuple((item.line, item.text) for item in comment_nodes),
        statement_spans=tuple(_statement_spans(root, line_index)),
        definitions=definitions,
        doc_candidates=doc_candidates,
        comment_nodes=comment_nodes,
        static_references=static_references,
        static_bindings=static_bindings,
    )


@dataclass(frozen=True, slots=True)
class _LineIndex:
    starts: tuple[int, ...]

    def __init__(self, source: bytes) -> None:
        starts = [0]
        cursor = 0
        for line in lf_split(source, keepends=True):
            cursor += len(line)
            if line.endswith(b"\n"):
                starts.append(cursor)
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
    scope_start_byte: int
    parent_scope_start_byte: int | None
    conditional: bool


@dataclass(frozen=True, slots=True)
class _OwnerNodeEntry:
    qualname: str
    kind: str
    definition: Node
    wrapper: Node
    parent_qualname: str | None
    parent_kind: str | None
    scope_start_byte: int
    parent_scope_start_byte: int | None
    conditional: bool


def _owner_entries(
    owner_nodes: list[_OwnerNodeEntry], line_index: _LineIndex, source: bytes
) -> list[_OwnerEntry]:
    owners: list[_OwnerEntry] = []
    for item in owner_nodes:
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
                scope_start_byte=item.scope_start_byte,
                parent_scope_start_byte=item.parent_scope_start_byte,
                conditional=item.conditional,
            )
        )
    return owners


def _owner_node_entries(
    root: Node, line_index: _LineIndex, source: bytes
) -> list[_OwnerNodeEntry]:
    owners: list[_OwnerNodeEntry] = []

    def visit(
        node: Node,
        prefix: str,
        parent_qualname: str | None,
        parent_kind: str | None,
        parent_scope_start_byte: int | None,
        conditional: bool,
    ) -> None:
        conditional = conditional or node.type in _CONDITIONAL_BINDING_NODE_TYPES
        if node.type == "comment":
            return
        definition = _definition_node(node)
        if definition is not None:
            name_node = definition.child_by_field_name("name")
            if name_node is None:
                return
            qualname = f"{prefix}{_node_text(name_node)}"
            wrapper = node if node.type == "decorated_definition" else definition
            scope_start_byte = wrapper.start_byte
            kind = (
                "class"
                if definition.type == "class_definition"
                else (
                    "async-function"
                    if any(child.type == "async" for child in definition.children)
                    else "function"
                )
            )
            owners.append(
                _OwnerNodeEntry(
                    qualname=qualname,
                    kind=kind,
                    definition=definition,
                    wrapper=wrapper,
                    parent_qualname=parent_qualname,
                    parent_kind=parent_kind,
                    scope_start_byte=scope_start_byte,
                    parent_scope_start_byte=parent_scope_start_byte,
                    conditional=conditional,
                )
            )
            for child in definition.children:
                visit(
                    child,
                    f"{qualname}.",
                    qualname,
                    kind,
                    scope_start_byte,
                    False,
                )
            return
        if node.type not in _DEFINITION_SEARCH_NODE_TYPES:
            return
        for child in node.children:
            visit(
                child,
                prefix,
                parent_qualname,
                parent_kind,
                parent_scope_start_byte,
                conditional,
            )

    visit(root, "", None, None, None, False)
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


def _field_children(node: Node, field_name: str) -> list[Node]:
    return [
        child
        for index, child in enumerate(node.children)
        if node.field_name_for_child(index) == field_name
    ]


def _name_parts(node: Node | None) -> tuple[str, ...] | None:
    if node is None:
        return None
    if node.type == "identifier":
        return (_node_text(node),)
    if node.type == "dotted_name":
        parts = tuple(
            _node_text(child)
            for child in _named_children(node)
            if child.type == "identifier"
        )
        return parts or None
    if node.type == "attribute":
        object_node = node.child_by_field_name("object")
        attribute_node = node.child_by_field_name("attribute")
        prefix = _name_parts(object_node)
        if prefix is None or attribute_node is None:
            return None
        return (*prefix, _node_text(attribute_node))
    return None


def _import_aliases(node: Node) -> tuple[StaticImportAlias, ...]:
    aliases: list[StaticImportAlias] = []
    for item in _field_children(node, "name"):
        imported_node = item.child_by_field_name("name")
        alias_node = item.child_by_field_name("alias")
        if imported_node is None:
            imported_node = item
        imported = _name_parts(imported_node)
        if imported is None:
            continue
        bound_name = (
            _node_text(alias_node)
            if alias_node is not None
            else (imported[0] if node.type == "import_statement" else imported[-1])
        )
        aliases.append(
            StaticImportAlias(
                imported=imported,
                bound_name=bound_name,
                source_order=item.start_byte,
            )
        )
    if node.type == "import_from_statement":
        wildcard = next(
            (
                child
                for child in _named_children(node)
                if child.type == "wildcard_import"
            ),
            None,
        )
        if wildcard is not None:
            aliases.append(
                StaticImportAlias(
                    imported=("*",),
                    bound_name="*",
                    source_order=wildcard.start_byte,
                )
            )
    return tuple(aliases)


def _import_module(node: Node) -> tuple[str | None, int]:
    if node.type != "import_from_statement":
        return None, 0
    module_node = node.child_by_field_name("module_name")
    if module_node is None:
        return None, 0
    raw = _node_text(module_node)
    level = len(raw) - len(raw.lstrip("."))
    module = raw[level:] or None
    return module, level


def _literal_call_arguments(node: Node) -> tuple[str | None, ...]:
    arguments = node.child_by_field_name("arguments")
    if arguments is None:
        return ()
    values = tuple(
        child for child in _named_children(arguments) if child.type != "comment"
    )
    return tuple(
        _portable_static_string_value(value)
        if value.type in {"string", "concatenated_string"}
        else None
        for value in values
    )


def _portable_static_string_value(node: Node) -> str | None:
    """Decode the conservative literal subset used by static relation hints."""

    if node.type == "concatenated_string":
        values = [
            _portable_static_string_value(child)
            for child in _named_children(node)
            if child.type == "string"
        ]
        return (
            None
            if not values or any(value is None for value in values)
            else "".join(value for value in values if value is not None)
        )
    raw = _node_text(node)
    quote_index = next(
        (index for index, character in enumerate(raw) if character in {'"', "'"}),
        None,
    )
    if quote_index is None:
        return None
    prefix = raw[:quote_index].lower()
    if any(character not in "ru" for character in prefix):
        return None
    quote = raw[quote_index]
    delimiter = quote * 3 if raw[quote_index:].startswith(quote * 3) else quote
    if not raw.endswith(delimiter):
        return None
    body = raw[quote_index + len(delimiter) : -len(delimiter)]
    if "r" in prefix:
        return body
    # Static module and attribute names have no need for escape evaluation.
    # Rejecting escapes is conservative and, unlike ``ast.literal_eval``, does
    # not vary with the host interpreter's accepted Python grammar.
    return None if "\\" in body else body


def _target_identifiers(node: Node | None) -> list[Node]:
    if node is None:
        return []
    if node.type == "identifier":
        return [node]
    if node.type in {"attribute", "subscript"}:
        return []
    if node.type == "as_pattern":
        alias = node.child_by_field_name("alias") or next(
            (
                child
                for child in reversed(_named_children(node))
                if child.type == "identifier"
            ),
            None,
        )
        return _target_identifiers(alias)
    identifiers: list[Node] = []
    for child in _named_children(node):
        identifiers.extend(_target_identifiers(child))
    return identifiers


def _parameter_identifiers(parameters: Node | None) -> list[Node]:
    if parameters is None:
        return []
    rows: list[Node] = []
    for item in _named_children(parameters):
        if item.type == "identifier":
            rows.append(item)
            continue
        name = item.child_by_field_name("name")
        if name is not None:
            rows.extend(_target_identifiers(name))
            continue
        if item.type in {
            "typed_parameter",
            "list_splat",
            "list_splat_pattern",
            "dictionary_splat",
            "dictionary_splat_pattern",
        }:
            first_identifier = next(
                (
                    child
                    for child in _named_children(item)
                    if child.type == "identifier"
                ),
                None,
            )
            if first_identifier is not None:
                rows.append(first_identifier)
    return rows


def _type_parameter_identifiers(parameters: Node | None) -> list[Node]:
    if parameters is None:
        return []
    rows: list[Node] = []
    for item in _named_children(parameters):
        name = _first_identifier(item)
        if name is not None:
            rows.append(name)
    return rows


def _first_identifier(node: Node | None) -> Node | None:
    if node is None:
        return None
    if node.type == "identifier":
        return node
    for child in _named_children(node):
        found = _first_identifier(child)
        if found is not None:
            return found
    return None


def _static_syntax_facts(
    root: Node,
    owners: Sequence[_OwnerNodeEntry],
    line_index: _LineIndex,
) -> tuple[tuple[StaticReference, ...], tuple[StaticBinding, ...]]:
    """Materialize parser-owned reference and binding facts as plain values."""

    references: list[StaticReference] = []
    bindings: list[StaticBinding] = []

    def add_reference(
        node: Node,
        node_kind: Literal["import", "call", "name", "attribute"],
        owner: _OwnerNodeEntry | None,
        *,
        name_parts: tuple[str, ...] = (),
        is_load: bool = True,
        conditional: bool = False,
    ) -> None:
        module, relative_level = _import_module(node)
        literal_arguments = _literal_call_arguments(node) if node_kind == "call" else ()
        references.append(
            StaticReference(
                owner_scope_start_byte=(
                    owner.scope_start_byte if owner is not None else None
                ),
                owner_qualname=owner.qualname if owner is not None else None,
                node_kind=node_kind,
                source_order=node.start_byte,
                line=_start_line(node, line_index),
                name_parts=name_parts,
                import_module=module,
                relative_level=relative_level,
                import_aliases=(_import_aliases(node) if node_kind == "import" else ()),
                literal_argument=(literal_arguments[0] if literal_arguments else None),
                literal_arguments=literal_arguments,
                is_load=is_load,
                conditional=conditional,
            )
        )

    def visit_reference(
        node: Node,
        owner: _OwnerNodeEntry | None,
        conditional: bool = False,
    ) -> None:
        conditional = conditional or node.type in _CONDITIONAL_BINDING_NODE_TYPES
        if _definition_node(node) is not None or node.type == "lambda":
            return
        if node.type in {"global_statement", "nonlocal_statement"}:
            return
        if node.type in {"import_statement", "import_from_statement"}:
            add_reference(node, "import", owner, conditional=conditional)
            return
        if node.type == "type_alias_statement":
            # The alias name binds in the surrounding scope, while its value
            # and type parameters execute in a distinct annotation scope.
            # Omitting that annotation-only subgraph is conservative.
            return
        if node.type in {"assignment", "annotated_assignment"}:
            right = node.child_by_field_name("right") or node.child_by_field_name(
                "value"
            )
            if right is not None:
                visit_reference(right, owner, conditional)
            left = node.child_by_field_name("left")
            if left is not None and left.type == "attribute":
                add_reference(
                    left,
                    "attribute",
                    owner,
                    name_parts=_name_parts(left) or (),
                    is_load=False,
                    conditional=conditional,
                )
                object_node = left.child_by_field_name("object")
                if object_node is not None:
                    visit_reference(object_node, owner, conditional)
            return
        if node.type == "augmented_assignment":
            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            if left is not None:
                visit_reference(left, owner, conditional)
            if right is not None:
                visit_reference(right, owner, conditional)
            return
        if node.type == "delete_statement":
            for child in _named_children(node):
                if child.type == "attribute":
                    add_reference(
                        child,
                        "attribute",
                        owner,
                        name_parts=_name_parts(child) or (),
                        is_load=False,
                        conditional=conditional,
                    )
                    object_node = child.child_by_field_name("object")
                    if object_node is not None:
                        visit_reference(object_node, owner, conditional)
            return
        if node.type == "named_expression":
            value = node.child_by_field_name("value")
            if value is not None:
                visit_reference(value, owner, conditional)
            return
        if node.type == "as_pattern":
            for index, child in enumerate(node.children):
                if child.is_named and node.field_name_for_child(index) != "alias":
                    visit_reference(child, owner, conditional)
            return
        if node.type == "for_in_clause":
            right = node.child_by_field_name("right")
            if right is not None:
                visit_reference(right, owner, conditional)
            for condition in _field_children(node, "condition"):
                visit_reference(condition, owner, conditional)
            return
        if node.type in {
            "case_pattern",
            "class_pattern",
            "complex_pattern",
            "dict_pattern",
            "keyword_pattern",
            "list_pattern",
            "splat_pattern",
            "tuple_pattern",
            "union_pattern",
        }:
            return
        if node.type in {"for_statement", "while_statement"}:
            right = node.child_by_field_name("right")
            condition_node = node.child_by_field_name("condition")
            for item in (right, condition_node):
                if item is not None:
                    visit_reference(item, owner, conditional)
            for field in ("body", "alternative"):
                for item in _field_children(node, field):
                    visit_reference(item, owner, conditional)
            return
        if node.type == "with_item":
            value = node.child_by_field_name("value")
            if value is not None:
                visit_reference(value, owner, conditional)
            return
        if node.type == "keyword_argument":
            value = node.child_by_field_name("value")
            if value is not None:
                visit_reference(value, owner, conditional)
            return
        if node.type == "call":
            function = node.child_by_field_name("function")
            add_reference(
                node,
                "call",
                owner,
                name_parts=_name_parts(function) or (),
                conditional=conditional,
            )
            for child in _named_children(node):
                visit_reference(child, owner, conditional)
            return
        if node.type == "attribute":
            add_reference(
                node,
                "attribute",
                owner,
                name_parts=_name_parts(node) or (),
                conditional=conditional,
            )
            object_node = node.child_by_field_name("object")
            if object_node is not None:
                visit_reference(object_node, owner, conditional)
            return
        if node.type == "identifier":
            add_reference(
                node,
                "name",
                owner,
                name_parts=(_node_text(node),),
                conditional=conditional,
            )
            return
        for child in _named_children(node):
            visit_reference(child, owner, conditional)

    owner_by_scope = {item.scope_start_byte: item for item in owners}

    def add_binding(
        name: Node,
        kind: Literal["parameter", "import", "definition", "assignment", "delete"],
        owner: _OwnerNodeEntry | None,
        conditional: bool,
        *,
        source_order: int | None = None,
    ) -> None:
        bindings.append(
            StaticBinding(
                owner.scope_start_byte if owner is not None else None,
                owner.qualname if owner is not None else None,
                _node_text(name),
                name.start_byte if source_order is None else source_order,
                kind,
                conditional,
            )
        )

    def visit_bindings(
        node: Node,
        owner: _OwnerNodeEntry | None,
        conditional: bool = False,
    ) -> None:
        conditional = conditional or node.type in _CONDITIONAL_BINDING_NODE_TYPES
        definition = _definition_node(node)
        if definition is not None:
            name = definition.child_by_field_name("name")
            if name is not None:
                add_binding(name, "definition", owner, conditional)
            return
        if node.type in {"import_statement", "import_from_statement"}:
            for alias in _import_aliases(node):
                bindings.append(
                    StaticBinding(
                        owner.scope_start_byte if owner is not None else None,
                        owner.qualname if owner is not None else None,
                        alias.bound_name,
                        alias.source_order,
                        "import",
                        conditional,
                    )
                )
            return
        if node.type == "type_alias_statement":
            name = _first_identifier(node.child_by_field_name("left"))
            if name is not None:
                add_binding(name, "assignment", owner, conditional)
            return
        if node.type in {
            "dictionary_comprehension",
            "generator_expression",
            "list_comprehension",
            "set_comprehension",
        }:
            # The result expression precedes its ``for`` target in source but
            # executes after that target is bound in the comprehension's
            # implicit scope.  Project the shadow from the comprehension start
            # so source-order lookup cannot climb to an outer import.
            for clause in (
                child
                for child in _named_children(node)
                if child.type == "for_in_clause"
            ):
                for target in _field_children(clause, "left"):
                    for name in _target_identifiers(target):
                        add_binding(
                            name,
                            "assignment",
                            owner,
                            True,
                            source_order=node.start_byte,
                        )
        binding_fields: tuple[str, ...] = ()
        if node.type in {"assignment", "annotated_assignment", "named_expression"}:
            binding_fields = ("name" if node.type == "named_expression" else "left",)
        elif node.type == "augmented_assignment":
            binding_fields = ("left",)
        elif node.type in {"for_statement", "for_in_clause"}:
            binding_fields = ("left",)
        elif node.type == "as_pattern":
            pattern_alias = node.child_by_field_name("alias") or next(
                (
                    child
                    for child in reversed(_named_children(node))
                    if child.type == "identifier"
                ),
                None,
            )
            if pattern_alias is not None:
                add_binding(pattern_alias, "assignment", owner, conditional)
        elif node.type == "splat_pattern":
            for name in _target_identifiers(node):
                add_binding(name, "assignment", owner, conditional)
        elif node.type == "case_pattern":
            dotted = next(
                (
                    child
                    for child in _named_children(node)
                    if child.type == "dotted_name"
                ),
                None,
            )
            if dotted is not None:
                names = [
                    child
                    for child in _named_children(dotted)
                    if child.type == "identifier" and _node_text(child) != "_"
                ]
                if len(names) == 1:
                    name = names[0]
                    add_binding(name, "assignment", owner, conditional)
        for field_name in binding_fields:
            for target in _field_children(node, field_name):
                for name in _target_identifiers(target):
                    add_binding(name, "assignment", owner, conditional)
        if node.type == "delete_statement":
            for target in _named_children(node):
                for name in _target_identifiers(target):
                    add_binding(name, "delete", owner, conditional)
        for child in _named_children(node):
            visit_bindings(child, owner, conditional)

    visit_reference(root, None)
    visit_bindings(root, None)
    for item in owners:
        body = item.definition.child_by_field_name("body")
        if body is not None:
            visit_reference(body, item)
            visit_bindings(body, item)
        parameters = item.definition.child_by_field_name("parameters")
        type_parameters = item.definition.child_by_field_name("type_parameters")
        for name in (
            *_parameter_identifiers(parameters),
            *_type_parameter_identifiers(type_parameters),
        ):
            bindings.append(
                StaticBinding(
                    item.scope_start_byte,
                    item.qualname,
                    _node_text(name),
                    0,
                    "parameter",
                    False,
                )
            )

    references.sort(key=lambda item: (item.source_order, item.node_kind))
    bindings.sort(
        key=lambda item: (
            -1 if item.owner_scope_start_byte is None else item.owner_scope_start_byte,
            item.source_order,
            item.name,
            item.kind,
        )
    )
    assert set(owner_by_scope) == {item.scope_start_byte for item in owners}
    return tuple(references), tuple(bindings)


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
        if node.type not in _DEFINITION_SEARCH_NODE_TYPES:
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
