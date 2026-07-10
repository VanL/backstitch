"""Python backlink parser tests against the fixture corpus.

Spec: docs/specs/02-backstitch-core.md [SC-4]
"""

from pathlib import Path

import pytest

from backstitch.python_refs import parse_python_file

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "traceability_project"
RUNTIME = FIXTURE_ROOT / "src" / "runtime.py"
RANGES = FIXTURE_ROOT / "src" / "ranges.py"
FIXTURE_TEST = FIXTURE_ROOT / "tests" / "test_runtime.py"


def _refs_by_owner(path: Path) -> dict[str, list]:
    parsed = parse_python_file(path, FIXTURE_ROOT)
    owners: dict[str, list] = {}
    for ref in parsed.refs:
        owners.setdefault(ref.owner_symbol, []).append(ref)
    return owners


def test_module_docstring_file_qualified_ref() -> None:
    owners = _refs_by_owner(RUNTIME)
    module_refs = owners["module"]
    assert len(module_refs) == 1
    ref = module_refs[0]
    assert ref.spec_path == "docs/specifications/01-Core.md"
    assert ref.section_ids == ("CORE-1",)
    assert ref.path == "src/runtime.py"
    assert ref.line == 3


def test_class_docstring_bare_ref() -> None:
    owners = _refs_by_owner(RUNTIME)
    ref = owners["Runtime"][0]
    assert ref.spec_path is None
    assert ref.section_ids == ("CORE-1",)


def test_method_docstring_and_comment_owners() -> None:
    owners = _refs_by_owner(RUNTIME)
    frob = owners["Runtime.frobnicate"][0]
    assert frob.spec_path == "docs/specifications/01-Core.md"
    assert frob.section_ids == ("CORE-1",)
    save = owners["Runtime.save"][0]
    assert save.spec_path == "docs/specifications/01-Core.md"
    assert save.section_ids == ("CORE-2",)
    assert save.line == 21


def test_function_comment_ref_to_planned_spec() -> None:
    owners = _refs_by_owner(RUNTIME)
    ref = owners["plan_shards"][0]
    assert ref.spec_path == "docs/specifications/01A-Core_Planned.md"
    assert ref.section_ids == ("CORE-P1",)


def test_anchor_ref_has_anchor_and_no_ids() -> None:
    owners = _refs_by_owner(RUNTIME)
    ref = owners["read_reference_docs"][0]
    assert ref.spec_path == "docs/specifications/01-Core.md"
    assert ref.anchor == "persistence-rules-core-2"
    assert ref.section_ids == ()


def test_cross_bracket_range_in_module_docstring() -> None:
    owners = _refs_by_owner(RANGES)
    range_refs = [r for r in owners["module"] if r.ranges]
    assert len(range_refs) == 1
    assert range_refs[0].ranges == (("CORE.2.1", "CORE.2.2"),)
    assert range_refs[0].spec_path is None


def test_file_qualified_multi_bracket_list() -> None:
    owners = _refs_by_owner(RANGES)
    listed = [r for r in owners["module"] if r.spec_path]
    assert len(listed) == 1
    assert listed[0].spec_path == "docs/specifications/01-Core.md"
    assert listed[0].section_ids == ("CORE-1", "CORE-2")


def test_compact_in_bracket_range() -> None:
    owners = _refs_by_owner(RANGES)
    ref = owners["compact_range"][0]
    assert ref.ranges == (("CORE.2.1", "CORE.2.2"),)


def test_comma_list_in_single_bracket() -> None:
    owners = _refs_by_owner(RANGES)
    ref = owners["comma_list"][0]
    assert ref.section_ids == ("CORE-1", "CORE-2")


def test_bare_candidates_are_emitted_even_without_spec_keyword() -> None:
    # The parser emits every ID-shaped candidate; the resolver filters by
    # known section-ID prefix (see test_resolver.py).
    owners = _refs_by_owner(RANGES)
    assert owners["indexing_noise"][0].section_ids == ("N-1",)
    assert owners["prose_reference"][0].section_ids == ("CORE-3",)


def test_endash_cross_bracket_range_parses_as_range() -> None:
    owners = _refs_by_owner(RANGES)
    ref = owners["endash_range"][0]
    assert ref.ranges == (("CORE.2.1", "CORE.2.2"),)
    assert ref.section_ids == ()


def test_endash_in_bracket_range_parses_as_range(tmp_path: Path) -> None:
    mod = tmp_path / "mod.py"
    mod.write_text(
        '"""Spec: [IMMUT.1–IMMUT.4]"""\n',
        encoding="utf-8",
    )
    parsed = parse_python_file(mod, tmp_path)
    assert parsed.refs[0].ranges == (("IMMUT.1", "IMMUT.4"),)


def test_cross_prefix_range_is_parsed_for_resolver_to_reject() -> None:
    owners = _refs_by_owner(RANGES)
    ref = owners["bad_range"][0]
    assert ref.ranges == (("CORE-1", "LAYER-1"),)


def test_fixture_test_file_refs() -> None:
    owners = _refs_by_owner(FIXTURE_TEST)
    assert owners["module"][0].section_ids == ("CORE-1",)
    assert owners["test_frobnicate"][0].section_ids == ("CORE-1",)


def test_syntax_error_yields_issue_not_crash(tmp_path: Path) -> None:
    bad = tmp_path / "broken.py"
    bad.write_text("def broken(:\n    pass\n", encoding="utf-8")
    parsed = parse_python_file(bad, tmp_path)
    assert parsed.refs == ()
    assert len(parsed.issues) == 1
    issue = parsed.issues[0]
    assert issue.code == "PYTHON_SYNTAX_ERROR"
    assert issue.severity == "warning"
    assert issue.path == "broken.py"


def test_modern_python_syntax_parses_without_runtime_ast(tmp_path: Path) -> None:
    mod = tmp_path / "modern.py"
    mod.write_text(
        '''class Box[T]:
    """Spec: [PEP-1]"""
    pass

type Alias[T] = list[T]

def pep701(items):
    """Spec: [PEP-2]"""
    return f"{items["key"]}"
''',
        encoding="utf-8",
    )
    parsed = parse_python_file(mod, tmp_path)
    assert parsed.issues == ()
    assert [(ref.owner_symbol, ref.section_ids) for ref in parsed.refs] == [
        ("Box", ("PEP-1",)),
        ("pep701", ("PEP-2",)),
    ]


def test_comment_noqa_attaches_to_elif_statement_span(tmp_path: Path) -> None:
    mod = tmp_path / "elif_noqa.py"
    mod.write_text(
        """def f(flag, other):
    if flag:
        pass
    # backstitch: noqa CODE_REF_UNMAPPED_FROM_SPEC
    elif other:  # see [X-1]
        value = 1
""",
        encoding="utf-8",
    )
    parsed = parse_python_file(mod, tmp_path)
    assert parsed.issues == ()
    assert parsed.span_noqa == ((5, 6, frozenset({"CODE_REF_UNMAPPED_FROM_SPEC"})),)
    assert [(ref.line, ref.section_ids) for ref in parsed.refs] == [(5, ("X-1",))]


def test_invariant_declarations_and_binding_docstrings_are_physical_and_isolated(
    tmp_path: Path,
) -> None:
    mod = tmp_path / "mod.py"
    mod.write_text(
        '''"""Invariant: [INV.CORE.1] first line
    second line with [SC-4]
"""

def owner():
    """Invariant (draft): [INV.CORE.2] draft statement"""

def test_owner():
    """Tests-invariant: [INV.CORE.1], [INV.CORE.2]"""
''',
        encoding="utf-8",
    )
    parsed = parse_python_file(mod, tmp_path, is_test_file=True)
    assert [
        (item.invariant_id, item.tier, item.statement, item.owner_symbol)
        for item in parsed.invariants
    ] == [
        ("INV.CORE.1", "required", "first line\nsecond line with [SC-4]", "<module>"),
        ("INV.CORE.2", "draft", "draft statement", "owner"),
    ]
    assert [
        (bind.invariant_id, bind.test_symbol, bind.start_line, bind.end_line)
        for bind in parsed.binding_refs
    ] == [
        ("INV.CORE.1", "test_owner", 8, 9),
        ("INV.CORE.2", "test_owner", 8, 9),
    ]
    assert all("INV.CORE" not in ref.section_ids for ref in parsed.refs)
    assert all("SC-4" not in ref.section_ids for ref in parsed.refs)


def test_class_binding_expands_only_direct_tests_and_comment_binds_decorated_test(
    tmp_path: Path,
) -> None:
    mod = tmp_path / "suite.py"
    mod.write_text(
        '''class Suite:
    """Tests-invariant: [INV.SUITE.1]"""

    def test_sync(self):
        pass

    async def test_async(self):
        pass

    class Nested:
        def test_nested(self):
            pass

# Tests-invariant: [INV.SUITE.2]
@case
def test_decorated():
    pass
''',
        encoding="utf-8",
    )
    parsed = parse_python_file(mod, tmp_path, is_test_file=True)
    assert [(b.invariant_id, b.test_symbol) for b in parsed.binding_refs] == [
        ("INV.SUITE.1", "Suite.test_sync"),
        ("INV.SUITE.1", "Suite.test_async"),
        ("INV.SUITE.2", "test_decorated"),
    ]


def test_invalid_and_non_test_markers_emit_structured_diagnostics_without_refs(
    tmp_path: Path,
) -> None:
    mod = tmp_path / "markers.py"
    mod.write_text(
        '''"""Invariant: [INV.BAD.1]"""

def helper():
    """Tests-invariant: [INV.BAD.2]"""

# Invariant: [INV.BAD.3] comments cannot declare
def test_real():
    pass
''',
        encoding="utf-8",
    )
    parsed = parse_python_file(mod, tmp_path, is_test_file=True)
    assert [issue.code for issue in parsed.issues] == [
        "INVARIANT_MARKER_INVALID",
        "INVARIANT_BINDING_NOT_TEST",
        "INVARIANT_MARKER_INVALID",
    ]
    assert parsed.invariants == ()
    assert parsed.binding_refs == ()
    assert parsed.refs == ()


def test_concatenated_docstring_marker_is_invalid_at_opening_line(
    tmp_path: Path,
) -> None:
    mod = tmp_path / "joined.py"
    mod.write_text(
        '"Invariant: " "[INV.JOIN.1] joined"\n',
        encoding="utf-8",
    )
    parsed = parse_python_file(mod, tmp_path)
    assert [(issue.code, issue.line) for issue in parsed.issues] == [
        ("INVARIANT_MARKER_INVALID", 1)
    ]
    assert parsed.invariants == ()
    assert parsed.refs == ()


def test_escaped_newline_marker_is_invalid_at_docstring_opening(tmp_path: Path) -> None:
    mod = tmp_path / "escaped.py"
    mod.write_text(
        '"""' + "\\" + "\nInvariant: [INV.ESC.1] escaped\n" + '"""\n',
        encoding="utf-8",
    )

    parsed = parse_python_file(mod, tmp_path)

    assert parsed.invariants == ()
    assert [
        (issue.code, issue.line, issue.invariant_id) for issue in parsed.issues
    ] == [("INVARIANT_MARKER_INVALID", 1, "INV.ESC.1")]
    assert parsed.refs == ()


def test_interpolated_docstring_marker_is_invalid_at_opening_line(
    tmp_path: Path,
) -> None:
    mod = tmp_path / "interpolated.py"
    mod.write_text(
        'f"""Invariant: [INV.FSTRING.1] value is {value}."""\n',
        encoding="utf-8",
    )

    parsed = parse_python_file(mod, tmp_path)

    assert parsed.invariants == ()
    assert [(issue.code, issue.line) for issue in parsed.issues] == [
        ("INVARIANT_MARKER_INVALID", 1)
    ]
    assert parsed.refs == ()


def test_ordinary_docstring_refs_keep_evaluated_escape_behavior(
    tmp_path: Path,
) -> None:
    mod = tmp_path / "escaped_ref.py"
    mod.write_text('"""Spec: [\\x41B-1]"""\n', encoding="utf-8")

    parsed = parse_python_file(mod, tmp_path)

    assert [(ref.line, ref.section_ids) for ref in parsed.refs] == [(1, ("AB-1",))]


def test_same_indent_line_terminates_declaration_and_remains_a_code_ref(
    tmp_path: Path,
) -> None:
    mod = tmp_path / "termination.py"
    mod.write_text(
        '"""Invariant: [INV.TERM.1] first line\nSpec: [SC-4]\n"""\n',
        encoding="utf-8",
    )

    parsed = parse_python_file(mod, tmp_path)

    assert [(item.invariant_id, item.statement) for item in parsed.invariants] == [
        ("INV.TERM.1", "first line")
    ]
    assert [(ref.line, ref.section_ids) for ref in parsed.refs] == [(2, ("SC-4",))]


@pytest.mark.parametrize(
    "source",
    [
        "# Tests-invariant: [INV.ATTACH.1]\n\ndef test_value():\n    pass\n",
        (
            "# Tests-invariant: [INV.ATTACH.1]\n"
            "# intervening comment\n"
            "def test_value():\n"
            "    pass\n"
        ),
        (
            "if True:\n"
            "# Tests-invariant: [INV.ATTACH.1]\n"
            "    def test_value():\n"
            "        pass\n"
        ),
    ],
    ids=["blank-line", "non-final", "wrong-indent"],
)
def test_binding_comment_attachment_breaks_create_no_bind(
    tmp_path: Path, source: str
) -> None:
    mod = tmp_path / "attachment.py"
    mod.write_text(source, encoding="utf-8")

    parsed = parse_python_file(mod, tmp_path, is_test_file=True)

    assert parsed.binding_refs == ()
    assert [issue.code for issue in parsed.issues] == ["INVARIANT_BINDING_NOT_TEST"]
