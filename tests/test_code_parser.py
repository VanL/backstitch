"""`tree-sitter` Python analyzer contract tests.

Spec: docs/specs/02-backstitch-core.md [SC-4], [SC-10]
"""

from __future__ import annotations

import gc

from backstitch.code_parser import DocBlock, ParsedModule, parse_python_source


def _parse(source: str) -> ParsedModule:
    return parse_python_source(source.encode("utf-8"))


def test_owner_spans_include_nested_async_and_decorated_definitions() -> None:
    parsed = _parse(
        "\n".join(
            [
                "class Outer:",
                "    class Inner:",
                "        pass",
                "",
                "    async def coro(self):",
                "        pass",
                "",
                "    @decorator",
                "    def method(self):",
                "        pass",
                "",
                "@decorator",
                "class Decorated:",
                "    pass",
                "",
                "def top():",
                "    if True:",
                "        def nested():",
                "            pass",
                "",
            ]
        )
    )
    assert {name: (start, end) for name, start, end in parsed.owner_spans} == {
        "Outer": (1, 10),
        "Outer.Inner": (2, 3),
        "Outer.coro": (5, 6),
        "Outer.method": (9, 10),
        "Decorated": (13, 14),
        "top": (16, 19),
        "top.nested": (18, 19),
    }


def test_doc_blocks_match_ast_plain_string_rules_and_decoding() -> None:
    parsed = _parse(
        '''"""module doc"""

class Parenthesized:
    ("paren doc")

class Raw:
    r"raw\\ntext"

class Escaped:
    "line one\\nline two"

class Joined:
    "left " "right"

class Triple:
    """line a
line b"""

class NotFString:
    f"not {1}"
    pass

class NotBytes:
    b"not"
    pass
'''
    )
    assert parsed.doc_blocks == (
        DocBlock("module", 1, "module doc"),
        DocBlock("Parenthesized", 4, "paren doc"),
        DocBlock("Raw", 7, r"raw\ntext"),
        DocBlock("Escaped", 10, "line one\nline two"),
        DocBlock("Joined", 13, "left right"),
        DocBlock("Triple", 16, "line a\nline b"),
    )


def test_statement_spans_follow_body_child_statements_not_all_named_nodes() -> None:
    parsed = _parse(
        "\n".join(
            [
                "from __future__ import annotations",
                "",
                "type Alias[T] = list[T]",
                "",
                "@decorator",
                "def f[T](x: T) -> T:",
                "    value = x",
                "    return value",
                "",
                "if True:",
                "    pass",
                "else:",
                "    assert False",
                "",
            ]
        )
    )
    assert parsed.statement_spans == (
        (1, 1),
        (3, 3),
        (6, 8),
        (7, 7),
        (8, 8),
        (10, 13),
        (11, 11),
        (13, 13),
    )


def test_statement_spans_match_ast_for_elif_and_match_cases() -> None:
    parsed = _parse(
        "\n".join(
            [
                "if a:",
                "    pass",
                "elif b:",
                "    x = 1",
                "elif c:",
                "    y = 2",
                "else:",
                "    z = 3",
                "",
                "match value:",
                "    case 1:",
                "        a = 1",
                "    case _:",
                "        b = 2",
                "",
            ]
        )
    )
    assert parsed.statement_spans == (
        (1, 8),
        (2, 2),
        (3, 8),
        (4, 4),
        (5, 8),
        (6, 6),
        (8, 8),
        (10, 14),
        (12, 12),
        (14, 14),
    )


def test_comments_are_normalized_from_tree_sitter_comment_nodes() -> None:
    parsed = _parse(
        "\n".join(
            [
                "# module comment",
                "class C:",
                "    # owner comment",
                "    def f(self):",
                "        value = 1  # trailing comment",
                "",
            ]
        )
    )
    assert parsed.comments == (
        (1, "module comment"),
        (3, "owner comment"),
        (5, "trailing comment"),
    )


def test_parse_error_is_all_or_nothing() -> None:
    parsed = _parse("def broken(:\n    pass\n")
    assert not parsed.parse_ok
    assert parsed.error_line == 1
    assert parsed.owner_spans == ()
    assert parsed.doc_blocks == ()
    assert parsed.comments == ()
    assert parsed.statement_spans == ()


def test_runtime_version_independent_syntax_parses() -> None:
    parsed = _parse(
        "\n".join(
            [
                "class Box[T]:",
                "    pass",
                "",
                "type Alias[T] = list[T]",
                "",
                "def pep701(items):",
                '    return f"{items["key"]}"',
                "",
            ]
        )
    )
    assert parsed.parse_ok
    assert parsed.owner_spans == (("Box", 1, 2), ("pep701", 6, 7))


def test_parser_exposes_definition_and_physical_docstring_metadata() -> None:
    parsed = _parse(
        '''class Suite:
    """Tests-invariant: [INV.TEST.1]"""

    @case
    async def test_async(self):
        pass
'''
    )
    suite, test_async = parsed.definitions
    assert (suite.qualname, suite.kind, suite.parent_qualname) == (
        "Suite",
        "class",
        None,
    )
    assert (
        test_async.qualname,
        test_async.kind,
        test_async.parent_qualname,
        test_async.attachment_line,
    ) == ("Suite.test_async", "function", "Suite", 4)
    candidate = parsed.doc_candidates[0]
    assert candidate.owner_qualname == "Suite"
    assert candidate.node_type == "string"
    assert candidate.raw_text == '"""Tests-invariant: [INV.TEST.1]"""'


def test_repeated_definition_metadata_parsing_keeps_native_nodes_isolated() -> None:
    source = "\n\n".join(
        (f'# Comment {index}\ndef function_{index}() -> None:\n    """Doc {index}."""')
        for index in range(20)
    ).encode("utf-8")

    for _ in range(25):
        parsed = parse_python_source(source)
        assert len(parsed.definitions) == 20

    gc.collect()
    assert parsed.doc_candidates[-1].text == "Doc 19."
    assert parsed.comment_nodes[-1].text == "Comment 19"
