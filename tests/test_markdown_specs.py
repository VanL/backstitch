"""Markdown spec parser tests against the fixture corpus.

Spec: docs/specs/02-backstitch-core.md [SC-4]
"""

from pathlib import Path

from backstitch.markdown_specs import parse_markdown_spec  # noqa: F401

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "traceability_project"
CORE = FIXTURE_ROOT / "docs" / "specifications" / "01-Core.md"
PLANNED = FIXTURE_ROOT / "docs" / "specifications" / "01A-Core_Planned.md"
WEFT_STYLE = FIXTURE_ROOT / "docs" / "specifications" / "02-Weft_Style.md"


def test_heading_sections_are_parsed_with_title_line_and_anchor() -> None:
    parsed = parse_markdown_spec(CORE, FIXTURE_ROOT)
    by_id = {s.section_id: s for s in parsed.sections}
    core1 = by_id["CORE-1"]
    assert core1.kind == "heading"
    assert core1.title == "Runtime Behaviour"
    assert core1.path == "docs/specifications/01-Core.md"
    assert core1.line == 6
    assert core1.anchor == "runtime-behaviour-core-1"


def test_invariant_bullets_define_sections() -> None:
    parsed = parse_markdown_spec(CORE, FIXTURE_ROOT)
    by_id = {s.section_id: s for s in parsed.sections}
    assert by_id["CORE.2.1"].kind == "invariant"
    assert by_id["CORE.2.2"].title == "partial writes are never visible to readers."
    assert by_id["CORE.2.1"].anchor is None


def test_prose_bracket_ids_do_not_define_sections() -> None:
    parsed = parse_markdown_spec(CORE, FIXTURE_ROOT)
    ids = {s.section_id for s in parsed.sections}
    assert ids == {"CORE-1", "CORE-2", "CORE.2.1", "CORE.2.2", "CORE-3", "DUP-1"}


def test_bullet_form_mapping_block_extracts_backticked_tokens() -> None:
    parsed = parse_markdown_spec(CORE, FIXTURE_ROOT)
    core1 = [m for m in parsed.mappings if m.section_id == "CORE-1"]
    assert {(m.kind, m.target) for m in core1} == {
        ("path", "src/runtime.py"),
        ("path_symbol", "src/runtime.py::Runtime.frobnicate"),
    }
    path_symbol = next(m for m in core1 if m.kind == "path_symbol")
    assert path_symbol.target_path == "src/runtime.py"
    assert path_symbol.target_symbol == "Runtime.frobnicate"


def test_bare_symbol_mapping_is_classified_as_symbol() -> None:
    parsed = parse_markdown_spec(CORE, FIXTURE_ROOT)
    core2 = {m.target: m for m in parsed.mappings if m.section_id == "CORE-2"}
    assert core2["src/missing_module.py"].kind == "path"
    assert core2["Runtime.save"].kind == "symbol"
    assert core2["Runtime.save"].target_path is None
    assert core2["Runtime.save"].target_symbol == "Runtime.save"


def test_inline_mapping_on_marker_line_weft_form() -> None:
    parsed = parse_markdown_spec(WEFT_STYLE, FIXTURE_ROOT)
    route = [m for m in parsed.mappings if m.section_id == "ROUTE-A1.1"]
    assert {(m.kind, m.target) for m in route} == {
        ("path", "src/runtime.py"),
        ("symbol", "Runtime"),
        ("symbol", "Runtime.frobnicate"),
    }


def test_per_layer_marker_variant_and_block_ends_at_blank_then_prose() -> None:
    parsed = parse_markdown_spec(WEFT_STYLE, FIXTURE_ROOT)
    layer = [m for m in parsed.mappings if m.section_id == "LAYER-1"]
    assert [(m.kind, m.target) for m in layer] == [
        ("path_symbol", "src/runtime.py::Runtime.save"),
    ]
    all_targets = {m.target for m in parsed.mappings}
    assert "src/not_a_mapping.py" not in all_targets


def test_heading_ids_at_level_three_and_letter_segments() -> None:
    parsed = parse_markdown_spec(WEFT_STYLE, FIXTURE_ROOT)
    ids = {s.section_id for s in parsed.sections}
    assert ids == {
        "ROUTE-A1.1",
        "LAYER-1",
        "LAYER-1.1",
        "DIRMAP-1",
        "DUP-1",
        "FENCE-1",
    }


def test_bracket_bullets_in_mapping_blocks_define_sections() -> None:
    parsed = parse_markdown_spec(WEFT_STYLE, FIXTURE_ROOT)
    by_id = {s.section_id: s for s in parsed.sections}
    layer_sub = by_id["LAYER-1.1"]
    assert layer_sub.kind == "bullet"
    assert layer_sub.title == "Persistence details"
    sub_mappings = [m for m in parsed.mappings if m.section_id == "LAYER-1.1"]
    assert [(m.kind, m.target) for m in sub_mappings] == [
        ("path", "src/runtime.py"),
    ]


def test_directory_callable_and_doc_tokens() -> None:
    parsed = parse_markdown_spec(WEFT_STYLE, FIXTURE_ROOT)
    dirmap = {m.target: m for m in parsed.mappings if m.section_id == "DIRMAP-1"}
    assert dirmap["src/"].kind == "path"
    assert dirmap["frobnicate_all()"].kind == "symbol"
    assert dirmap["frobnicate_all()"].target_symbol == "frobnicate_all"
    # Backticked .md tokens are path mappings per [SC-11] -- the resolver
    # applies the plan-root severity predicate, and the reciprocity check
    # never demands backlinks from documents.
    assert dirmap["docs/specifications/01-Core.md"].kind == "path"


def test_fenced_code_blocks_define_nothing() -> None:
    parsed = parse_markdown_spec(WEFT_STYLE, FIXTURE_ROOT)
    assert "PHANTOM-9" not in {s.section_id for s in parsed.sections}
    assert "src/phantom.py" not in {m.target for m in parsed.mappings}
    assert "phantom-heading-phantom-9" not in parsed.anchors


def test_anchors_include_idless_headings_and_deduplicate() -> None:
    parsed = parse_markdown_spec(WEFT_STYLE, FIXTURE_ROOT)
    assert "queue-names" in parsed.anchors
    assert "duplicate-title" in parsed.anchors
    assert "duplicate-title-1" in parsed.anchors
    assert "advanced-routing-route-a11" in parsed.anchors


def test_planned_fixture_parses_normally() -> None:
    parsed = parse_markdown_spec(PLANNED, FIXTURE_ROOT)
    assert [s.section_id for s in parsed.sections] == ["CORE-P1"]


def test_github_anchor_punctuation_and_space_runs() -> None:
    from backstitch.markdown_specs import github_anchor

    # GitHub replaces each space with a hyphen after stripping punctuation;
    # runs must not collapse.
    assert github_anchor("Tasks & Queues", {}) == "tasks--queues"
    assert github_anchor("Task Pause / Resume CLI", {}) == "task-pause--resume-cli"
    assert github_anchor("1. TaskSpec (`weft/core/model.py`) [CC-1]", {}) == (
        "1-taskspec-weftcoremodelpy-cc-1"
    )


def test_tilde_fences_are_skipped(tmp_path: Path) -> None:
    doc = tmp_path / "01-T.md"
    doc.write_text(
        "# T\n\n## Real [T-1]\n\n~~~text\n## Phantom [T-9]\n~~~\n",
        encoding="utf-8",
    )
    parsed = parse_markdown_spec(doc, tmp_path)
    assert [s.section_id for s in parsed.sections] == ["T-1"]


def test_commonmark_heading_forms_define_sections(tmp_path: Path) -> None:
    doc = tmp_path / "01-T.md"
    doc.write_text(
        "# T\n\nSetext Section [T-1]\n====================\n\n## ATX Close [T-2] ##\n",
        encoding="utf-8",
    )
    parsed = parse_markdown_spec(doc, tmp_path)
    by_id = {s.section_id: s for s in parsed.sections}
    assert by_id["T-1"].title == "Setext Section"
    assert by_id["T-1"].anchor == "setext-section-t-1"
    assert by_id["T-2"].title == "ATX Close"
    assert by_id["T-2"].anchor == "atx-close-t-2"


def test_commonmark_fence_closer_with_info_string_does_not_close(
    tmp_path: Path,
) -> None:
    doc = tmp_path / "01-T.md"
    doc.write_text(
        "# T\n\n"
        "## Real [T-1]\n\n"
        "```\n"
        "```python\n"
        "## Phantom [T-9]\n"
        "_Implementation mapping_: `pkg/phantom.py`\n"
        "```\n",
        encoding="utf-8",
    )
    parsed = parse_markdown_spec(doc, tmp_path)
    assert [s.section_id for s in parsed.sections] == ["T-1"]
    assert parsed.mappings == ()


def test_indented_code_blocks_define_no_traceability_constructs(
    tmp_path: Path,
) -> None:
    doc = tmp_path / "01-T.md"
    doc.write_text(
        "# T\n\n"
        "## Real [T-1]\n\n"
        "    _Implementation mapping_: `pkg/phantom.py`\n"
        "    - **T-9**: Phantom invariant\n"
        "    ```\n"
        "    ## Phantom [T-10]\n"
        "    ```\n",
        encoding="utf-8",
    )
    parsed = parse_markdown_spec(doc, tmp_path)
    assert [s.section_id for s in parsed.sections] == ["T-1"]
    assert parsed.mappings == ()


def test_standalone_html_traceability_markers_still_apply(
    tmp_path: Path,
) -> None:
    doc = tmp_path / "01-T.md"
    doc.write_text(
        "<!-- backstitch: ignore SPEC_SECTION_UNMAPPED -->\n"
        "## Real [T-1]\n"
        "<!-- backstitch: meta -->\n"
        "Body text.\n",
        encoding="utf-8",
    )
    parsed = parse_markdown_spec(doc, tmp_path)
    assert parsed.file_ignores == frozenset({"SPEC_SECTION_UNMAPPED"})
    assert parsed.section_markers == (("T-1", True, frozenset()),)


def test_standalone_html_traceability_markers_are_case_insensitive(
    tmp_path: Path,
) -> None:
    doc = tmp_path / "01-T.md"
    doc.write_text(
        "<!-- BACKSTITCH: IGNORE SPEC_SECTION_UNMAPPED -->\n## Real [T-1]\n",
        encoding="utf-8",
    )
    parsed = parse_markdown_spec(doc, tmp_path)
    assert parsed.file_ignores == frozenset({"SPEC_SECTION_UNMAPPED"})


def test_traceability_paragraph_markers_are_case_insensitive(
    tmp_path: Path,
) -> None:
    doc = tmp_path / "01-T.md"
    doc.write_text(
        "_traceability: ignore SPEC_SECTION_UNMAPPED_\n## Real [T-1]\n",
        encoding="utf-8",
    )
    parsed = parse_markdown_spec(doc, tmp_path)
    assert parsed.file_ignores == frozenset({"SPEC_SECTION_UNMAPPED"})


def test_mapping_tokens_use_parser_inline_code_content_and_source_lines(
    tmp_path: Path,
) -> None:
    doc = tmp_path / "01-T.md"
    doc.write_text(
        "# T\n\n## Real [T-1]\n\n_Implementation mapping_: ` pkg/a.py `,\n`pkg/b.py`\n",
        encoding="utf-8",
    )
    parsed = parse_markdown_spec(doc, tmp_path)
    assert [(m.target, m.line) for m in parsed.mappings] == [
        ("pkg/a.py", 5),
        ("pkg/b.py", 6),
    ]


def test_duplicate_mapping_targets_on_later_lines_keep_source_lines(
    tmp_path: Path,
) -> None:
    doc = tmp_path / "01-T.md"
    doc.write_text(
        "# T\n\n## Real [T-1]\n\n_Implementation mapping_: `pkg/a.py`\n`pkg/a.py`\n",
        encoding="utf-8",
    )
    parsed = parse_markdown_spec(doc, tmp_path)
    assert [(m.target, m.line) for m in parsed.mappings] == [
        ("pkg/a.py", 5),
        ("pkg/a.py", 6),
    ]


def test_mapping_block_continues_through_tight_and_loose_lists(
    tmp_path: Path,
) -> None:
    doc = tmp_path / "01-T.md"
    doc.write_text(
        "# T\n\n"
        "## Tight [T-1]\n\n"
        "_Implementation mapping_:\n"
        "- `pkg/tight-a.py`\n"
        "- `pkg/tight-b.py`\n\n"
        "## Loose [T-2]\n\n"
        "_Implementation mapping_:\n\n"
        "- `pkg/loose-a.py`\n\n"
        "- `pkg/loose-b.py`\n",
        encoding="utf-8",
    )
    parsed = parse_markdown_spec(doc, tmp_path)
    assert [(m.section_id, m.target) for m in parsed.mappings] == [
        ("T-1", "pkg/tight-a.py"),
        ("T-1", "pkg/tight-b.py"),
        ("T-2", "pkg/loose-a.py"),
        ("T-2", "pkg/loose-b.py"),
    ]


def test_invariant_list_after_mapping_marker_is_not_mapping_continuation(
    tmp_path: Path,
) -> None:
    doc = tmp_path / "01-T.md"
    doc.write_text(
        "# T\n\n"
        "### Invariants\n\n"
        "_Implementation mapping_: `pkg/owner.py`\n\n"
        "- **INV-1**: first invariant maps no target despite `pkg/example.py`\n"
        "- **INV-2**: second invariant\n"
        "  wraps to another source line\n",
        encoding="utf-8",
    )
    parsed = parse_markdown_spec(doc, tmp_path)
    assert [(s.section_id, s.title) for s in parsed.sections] == [
        ("INV-1", "first invariant maps no target despite `pkg/example.py`"),
        ("INV-2", "second invariant"),
    ]
    assert parsed.mappings == ()
    assert [i.code for i in parsed.issues] == ["MAPPING_BLOCK_OWNERLESS"]


def test_mapping_list_can_start_with_plain_item_then_mapping_item(
    tmp_path: Path,
) -> None:
    doc = tmp_path / "01-T.md"
    doc.write_text(
        "# T\n\n"
        "## Real [T-1]\n\n"
        "_Implementation mapping_:\n\n"
        "- note for readers\n"
        "- `pkg/owner.py`\n",
        encoding="utf-8",
    )
    parsed = parse_markdown_spec(doc, tmp_path)
    assert [(m.section_id, m.target) for m in parsed.mappings] == [
        ("T-1", "pkg/owner.py"),
    ]


def test_wrapped_bracket_bullet_mapping_defines_subsection(
    tmp_path: Path,
) -> None:
    doc = tmp_path / "01-T.md"
    doc.write_text(
        "# T\n\n"
        "## Real [T-1]\n\n"
        "_Implementation mapping_:\n\n"
        "- [T-1.1] Wrapped subsection —\n"
        "  more detail `pkg/owned.py`\n",
        encoding="utf-8",
    )
    parsed = parse_markdown_spec(doc, tmp_path)
    assert [(s.section_id, s.kind, s.title) for s in parsed.sections] == [
        ("T-1", "heading", "Real"),
        ("T-1.1", "bullet", "Wrapped subsection"),
    ]
    assert [(m.section_id, m.target, m.line) for m in parsed.mappings] == [
        ("T-1.1", "pkg/owned.py", 8),
    ]


def test_invariant_item_inside_mapping_list_is_not_mapping_content(
    tmp_path: Path,
) -> None:
    doc = tmp_path / "01-T.md"
    doc.write_text(
        "# T\n\n"
        "## Real [T-1]\n\n"
        "_Implementation mapping_:\n\n"
        "- `pkg/owner.py`\n"
        "- **INV-1**: invariant text is not a mapping `pkg/notmapping.py`\n",
        encoding="utf-8",
    )
    parsed = parse_markdown_spec(doc, tmp_path)
    assert [(s.section_id, s.kind) for s in parsed.sections] == [
        ("T-1", "heading"),
        ("INV-1", "invariant"),
    ]
    assert [(m.section_id, m.target) for m in parsed.mappings] == [
        ("T-1", "pkg/owner.py"),
    ]


def test_blockquotes_and_ordered_lists_do_not_declare_traceability(
    tmp_path: Path,
) -> None:
    doc = tmp_path / "01-T.md"
    doc.write_text(
        "# T\n\n"
        "## Real [T-1]\n\n"
        "> ## Phantom [T-9]\n"
        "> _Implementation mapping_: `pkg/quoted.py`\n\n"
        "1. _Implementation mapping_: `pkg/ordered.py`\n"
        "2. **T-10**: ordered invariant example\n",
        encoding="utf-8",
    )
    parsed = parse_markdown_spec(doc, tmp_path)
    assert [s.section_id for s in parsed.sections] == ["T-1"]
    assert parsed.mappings == ()


def test_fixture_mapping_line_numbers_come_from_source_tokens() -> None:
    parsed = parse_markdown_spec(WEFT_STYLE, FIXTURE_ROOT)
    route = sorted(m.line for m in parsed.mappings if m.section_id == "ROUTE-A1.1")
    dirmap = sorted(m.line for m in parsed.mappings if m.section_id == "DIRMAP-1")
    assert route == [11, 11, 11]
    assert dirmap == [33, 33, 34]


def test_deeper_idless_subheading_keeps_mapping_ownership(
    tmp_path: Path,
) -> None:
    # [SC-4]: a deeper ID-less subheading between an ID heading and its
    # mapping block is prose structure, not a new owner; same-or-shallower
    # ID-less headings clear ownership (see the ownerless tests below).
    doc = tmp_path / "01-T.md"
    doc.write_text(
        "# T\n\n## Schema [T-1]\n\n### 1.1 Details\n\n"
        "_Implementation mapping_:\n\n- `pkg/x.py`\n",
        encoding="utf-8",
    )
    parsed = parse_markdown_spec(doc, tmp_path)
    assert [(m.section_id, m.target) for m in parsed.mappings] == [
        ("T-1", "pkg/x.py"),
    ]
    assert parsed.issues == ()


def test_ownerless_mapping_block_is_flagged_and_dropped(tmp_path: Path) -> None:
    doc = tmp_path / "01-T.md"
    doc.write_text(
        "# T\n\n## Real [T-1]\n\n## Open Questions\n\n"
        "_Implementation mapping_:\n\n- `pkg/x.py`\n",
        encoding="utf-8",
    )
    parsed = parse_markdown_spec(doc, tmp_path)
    assert parsed.mappings == ()
    assert [i.code for i in parsed.issues] == ["MAPPING_BLOCK_OWNERLESS"]


def test_bracket_bullet_in_ownerless_block_still_owns_its_tokens(
    tmp_path: Path,
) -> None:
    # Documented exception: a bracket bullet defines its own subsection,
    # so its tokens are owned even when the enclosing block is ownerless.
    doc = tmp_path / "01-T.md"
    doc.write_text(
        "# T\n\n## Open Questions\n\n_Implementation mapping_:\n\n"
        "- `pkg/orphan.py`\n"
        "- [T-1.1] Sub thing — `pkg/owned.py`\n",
        encoding="utf-8",
    )
    parsed = parse_markdown_spec(doc, tmp_path)
    assert [i.code for i in parsed.issues] == ["MAPPING_BLOCK_OWNERLESS"]
    assert [(m.section_id, m.target) for m in parsed.mappings] == [
        ("T-1.1", "pkg/owned.py"),
    ]
    assert [s.section_id for s in parsed.sections] == ["T-1.1"]


def test_script_extension_tokens_classify_as_paths() -> None:
    from backstitch.markdown_specs import classify_mapping_token

    assert classify_mapping_token("deploy.sh")[0] == "path"
    assert classify_mapping_token("schema.sql")[0] == "path"
    assert classify_mapping_token("Runtime.save")[0] == "symbol"


def test_markdown_invariant_markers_bind_to_enclosing_section(tmp_path: Path) -> None:
    doc = tmp_path / "01-T.md"
    doc.write_text(
        "# T\n\n## Contract [T-1]\n\n"
        "Invariant: [INV.MD.1] first line\n"
        "continued statement\n\n"
        "Invariant (draft): [INV.MD.2] draft\n",
        encoding="utf-8",
    )
    parsed = parse_markdown_spec(doc, tmp_path)
    assert [
        (item.invariant_id, item.tier, item.statement, item.section_id, item.line)
        for item in parsed.invariants
    ] == [
        ("INV.MD.1", "required", "first line\ncontinued statement", "T-1", 5),
        ("INV.MD.2", "draft", "draft", "T-1", 8),
    ]


def test_markdown_marker_outside_section_is_invalid_and_blocks_are_silent(
    tmp_path: Path,
) -> None:
    doc = tmp_path / "01-T.md"
    doc.write_text(
        "Invariant: [INV.OUT.1] ownerless\n\n"
        "## Contract [T-1]\n\n"
        "```text\nInvariant: [INV.FENCE.1] example\n```\n\n"
        "- Invariant: [INV.LIST.1] example\n",
        encoding="utf-8",
    )
    parsed = parse_markdown_spec(doc, tmp_path)
    assert parsed.invariants == ()
    assert [(issue.code, issue.line) for issue in parsed.issues] == [
        ("INVARIANT_MARKER_INVALID", 1)
    ]


def test_adjacent_markdown_markers_terminate_each_other(tmp_path: Path) -> None:
    doc = tmp_path / "01-T.md"
    doc.write_text(
        "# T\n\n## Contract [T-1]\n\n"
        "Invariant: [INV.MD.1] first\n"
        "Invariant (draft): [INV.MD.2] second\n",
        encoding="utf-8",
    )

    parsed = parse_markdown_spec(doc, tmp_path)

    assert [
        (item.invariant_id, item.statement, item.tier, item.line)
        for item in parsed.invariants
    ] == [
        ("INV.MD.1", "first", "required", 5),
        ("INV.MD.2", "second", "draft", 6),
    ]


def test_malformed_markdown_marker_under_section_keeps_parseable_id(
    tmp_path: Path,
) -> None:
    doc = tmp_path / "01-T.md"
    doc.write_text(
        "# T\n\n## Contract [T-1]\n\nInvariant: [INV.BAD.1]\n",
        encoding="utf-8",
    )

    parsed = parse_markdown_spec(doc, tmp_path)

    assert parsed.invariants == ()
    assert [
        (issue.code, issue.line, issue.invariant_id) for issue in parsed.issues
    ] == [("INVARIANT_MARKER_INVALID", 5, "INV.BAD.1")]
