"""Python backlink parser tests against the fixture corpus.

Spec: docs/specs/02-backstitch-core.md [SC-4]
"""

from pathlib import Path

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
    assert issue.severity == "error"
    assert issue.path == "broken.py"
