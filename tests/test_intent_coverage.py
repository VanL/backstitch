"""Intent coverage behavior through the pure classification interface.

Spec: docs/specs/08-intent-coverage.md [COV-3], [COV-6]
"""

from __future__ import annotations

from backstitch.intent_coverage import (
    CoverageDefinition,
    CoverageExemptionFact,
    CoverageFloorFact,
    classify_intent_coverage,
    coverage_definitions_from_python_inventory,
    evaluate_coverage_floors,
)
from backstitch.models import (
    Edge,
    InvariantBind,
    InvariantDeclaration,
    Report,
    SpecMapping,
    SpecSection,
)
from backstitch.python_refs import python_definition_inventory_bytes


def _report(
    *,
    edges: tuple[Edge, ...] = (),
    sections: tuple[SpecSection, ...] = (),
    mappings: tuple[SpecMapping, ...] = (),
    invariants: tuple[InvariantDeclaration, ...] = (),
    binds: tuple[InvariantBind, ...] = (),
) -> Report:
    return Report(
        profile="test",
        repo_root="/repo",
        spec_sections=sections,
        code_refs=(),
        spec_mappings=mappings,
        edges=edges,
        issues=(),
        invariants=invariants,
        binds=binds,
    )


def test_definition_without_intent_edge_is_uncovered_and_enters_worklist() -> None:
    definition = CoverageDefinition(
        definition_id="sha256:def",
        path="pkg/example.py",
        structural_locator="python-definition:run:function:0",
        qualname="run",
        kind="function",
        role="production",
        start_line=1,
        end_line=2,
        source_projection_sha256="sha256:source",
        parent_definition_id="sha256:module",
    )

    result = classify_intent_coverage((definition,), _report())

    assert result.definitions[0].classification == "uncovered"
    assert result.worklist == ("sha256:def",)


def test_canonical_inventory_projects_methods_and_parent_identities() -> None:
    inventory = python_definition_inventory_bytes(
        (
            b"class Worker:\n"
            b"    async def run(self):\n"
            b"        return None\n\n"
            b"def helper():\n"
            b"    return None\n"
        ),
        rel_path="pkg/example.py",
        module_name="pkg.example",
    )
    assert inventory is not None

    definitions = coverage_definitions_from_python_inventory(
        inventory,
        role="production",
        tree="pkg",
    )

    assert [item.kind for item in definitions] == [
        "module",
        "class",
        "async_method",
        "function",
    ]
    assert definitions[1].parent_definition_id == definitions[0].definition_id
    assert definitions[2].parent_definition_id == definitions[1].definition_id
    assert definitions[3].parent_definition_id == definitions[0].definition_id
    assert definitions[0].definition_id.startswith("sha256:")


def test_resolving_symbol_mapping_directly_covers_matching_definition() -> None:
    definition = CoverageDefinition(
        definition_id="sha256:def",
        path="pkg/example.py",
        structural_locator="python-definition:run:function:0",
        qualname="run",
        kind="function",
        role="production",
        start_line=3,
        end_line=4,
        source_projection_sha256="sha256:source",
        parent_definition_id="sha256:module",
    )
    edge = Edge(
        kind="mapping",
        spec_path="docs/specs/01-example.md",
        section_id="EX-1",
        code_path="pkg/example.py",
        code_symbol="run",
        line=8,
    )

    result = classify_intent_coverage((definition,), _report(edges=(edge,)))

    assert result.definitions[0].classification == "direct"
    assert result.worklist == ()


def test_whole_file_mapping_is_inherited_for_module_and_descendants() -> None:
    module = CoverageDefinition(
        definition_id="sha256:module",
        path="pkg/example.py",
        structural_locator="python-module:pkg.example",
        qualname="pkg.example",
        kind="module",
        role="production",
        start_line=1,
        end_line=4,
        source_projection_sha256="sha256:module-source",
        parent_definition_id=None,
    )
    function = CoverageDefinition(
        definition_id="sha256:def",
        path="pkg/example.py",
        structural_locator="python-definition:run:function:0",
        qualname="run",
        kind="function",
        role="production",
        start_line=3,
        end_line=4,
        source_projection_sha256="sha256:def-source",
        parent_definition_id="sha256:module",
    )
    edge = Edge(
        kind="mapping",
        spec_path="docs/specs/01-example.md",
        section_id="EX-1",
        code_path="pkg/example.py",
        code_symbol=None,
        line=8,
    )

    result = classify_intent_coverage((module, function), _report(edges=(edge,)))

    assert [row.classification for row in result.definitions] == [
        "inherited",
        "inherited",
    ]
    assert (
        result.definitions[0].governing_edge_ids
        == result.definitions[1].governing_edge_ids
    )
    assert result.worklist == ()


def test_backlink_coordinates_select_one_duplicate_symbol_owner() -> None:
    first = CoverageDefinition(
        definition_id="sha256:first",
        path="pkg/example.py",
        structural_locator="python-definition:run:function:0",
        qualname="run",
        kind="function",
        role="production",
        start_line=1,
        end_line=2,
        source_projection_sha256="sha256:first-source",
        parent_definition_id="sha256:module",
    )
    second = CoverageDefinition(
        definition_id="sha256:second",
        path="pkg/example.py",
        structural_locator="python-definition:run:function:1",
        qualname="run",
        kind="function",
        role="production",
        start_line=5,
        end_line=6,
        source_projection_sha256="sha256:second-source",
        parent_definition_id="sha256:module",
    )
    backlink = Edge(
        kind="backlink",
        spec_path="docs/specs/01-example.md",
        section_id="EX-1",
        code_path="pkg/example.py",
        code_symbol="run",
        line=5,
    )

    result = classify_intent_coverage(
        (first, second),
        _report(edges=(backlink,)),
    )

    assert [item.classification for item in result.definitions] == [
        "uncovered",
        "direct",
    ]


def test_backlink_with_equal_span_ambiguous_owners_covers_neither() -> None:
    first = CoverageDefinition(
        definition_id="sha256:first",
        path="pkg/example.py",
        structural_locator="python-definition:run:function:0",
        qualname="run",
        kind="function",
        role="production",
        start_line=1,
        end_line=3,
        source_projection_sha256="sha256:first-source",
        parent_definition_id="sha256:module",
    )
    second = CoverageDefinition(
        definition_id="sha256:second",
        path="pkg/example.py",
        structural_locator="python-definition:run:function:1",
        qualname="run",
        kind="function",
        role="production",
        start_line=2,
        end_line=4,
        source_projection_sha256="sha256:second-source",
        parent_definition_id="sha256:module",
    )
    backlink = Edge(
        kind="backlink",
        spec_path="docs/specs/01-example.md",
        section_id="EX-1",
        code_path="pkg/example.py",
        code_symbol="run",
        line=2,
    )

    result = classify_intent_coverage((first, second), _report(edges=(backlink,)))

    assert [item.classification for item in result.definitions] == [
        "uncovered",
        "uncovered",
    ]


def test_module_backlink_is_inherited_for_the_whole_file() -> None:
    module = CoverageDefinition(
        definition_id="sha256:module",
        path="pkg/example.py",
        structural_locator="python-module:pkg.example",
        qualname="pkg.example",
        kind="module",
        role="production",
        start_line=1,
        end_line=4,
        source_projection_sha256="sha256:module-source",
        parent_definition_id=None,
    )
    function = CoverageDefinition(
        definition_id="sha256:def",
        path="pkg/example.py",
        structural_locator="python-definition:run:function:0",
        qualname="run",
        kind="function",
        role="production",
        start_line=3,
        end_line=4,
        source_projection_sha256="sha256:def-source",
        parent_definition_id="sha256:module",
    )
    backlink = Edge(
        kind="backlink",
        spec_path="docs/specs/01-example.md",
        section_id="EX-1",
        code_path="pkg/example.py",
        code_symbol="module",
        line=1,
    )

    result = classify_intent_coverage(
        (module, function),
        _report(edges=(backlink,)),
    )

    assert [item.classification for item in result.definitions] == [
        "inherited",
        "inherited",
    ]


def test_direct_non_module_owner_directly_covers_descendant_method() -> None:
    owner = CoverageDefinition(
        definition_id="sha256:class",
        path="pkg/example.py",
        structural_locator="python-definition:Worker:class:0",
        qualname="Worker",
        kind="class",
        role="production",
        start_line=1,
        end_line=4,
        source_projection_sha256="sha256:class-source",
        parent_definition_id="sha256:module",
    )
    method = CoverageDefinition(
        definition_id="sha256:method",
        path="pkg/example.py",
        structural_locator="python-definition:Worker.run:method:0",
        qualname="Worker.run",
        kind="method",
        role="production",
        start_line=2,
        end_line=4,
        source_projection_sha256="sha256:method-source",
        parent_definition_id="sha256:class",
    )
    edge = Edge(
        kind="backlink",
        spec_path="docs/specs/01-example.md",
        section_id="EX-1",
        code_path="pkg/example.py",
        code_symbol="Worker",
        line=1,
    )

    result = classify_intent_coverage((owner, method), _report(edges=(edge,)))

    assert [row.classification for row in result.definitions] == ["direct", "direct"]


def test_invariant_declaration_and_binding_directly_cover_exact_owners() -> None:
    implementation = CoverageDefinition(
        definition_id="sha256:impl",
        path="pkg/example.py",
        structural_locator="python-definition:run:function:0",
        qualname="run",
        kind="function",
        role="production",
        start_line=1,
        end_line=2,
        source_projection_sha256="sha256:impl-source",
        parent_definition_id="sha256:impl-module",
    )
    test = CoverageDefinition(
        definition_id="sha256:test",
        path="tests/test_example.py",
        structural_locator="python-definition:test_run:function:0",
        qualname="test_run",
        kind="function",
        role="test",
        start_line=1,
        end_line=2,
        source_projection_sha256="sha256:test-source",
        parent_definition_id="sha256:test-module",
    )
    report = _report(
        invariants=(
            InvariantDeclaration(
                invariant_id="INV.EXAMPLE.1",
                statement="Run remains stable.",
                tier="required",
                declaration_kind="code",
                path="pkg/example.py",
                line=1,
                owner_symbol="run",
                section_id=None,
            ),
        ),
        binds=(
            InvariantBind(
                invariant_id="INV.EXAMPLE.1",
                test_path="tests/test_example.py",
                test_symbol="test_run",
                marker_line=1,
                start_line=1,
                end_line=2,
            ),
        ),
    )

    result = classify_intent_coverage((implementation, test), report)

    assert [item.classification for item in result.definitions] == [
        "direct",
        "direct",
    ]


def test_exemption_precedes_inherited_but_never_hides_direct_coverage() -> None:
    inherited = CoverageDefinition(
        definition_id="sha256:inherited",
        path="pkg/example.py",
        structural_locator="python-definition:glue:function:0",
        qualname="glue",
        kind="function",
        role="production",
        start_line=2,
        end_line=2,
        source_projection_sha256="sha256:glue",
        parent_definition_id="sha256:module",
    )
    direct = CoverageDefinition(
        definition_id="sha256:direct",
        path="pkg/example.py",
        structural_locator="python-definition:run:function:0",
        qualname="run",
        kind="function",
        role="production",
        start_line=3,
        end_line=3,
        source_projection_sha256="sha256:run",
        parent_definition_id="sha256:module",
    )
    blanket = Edge(
        kind="mapping",
        spec_path="docs/specs/01-example.md",
        section_id="EX-1",
        code_path="pkg/example.py",
        code_symbol=None,
        line=8,
    )
    symbol = Edge(
        kind="mapping",
        spec_path="docs/specs/01-example.md",
        section_id="EX-2",
        code_path="pkg/example.py",
        code_symbol="run",
        line=12,
    )
    exemption = CoverageExemptionFact(
        exemption_id="sha256:exemption",
        matched_definition_ids=("sha256:inherited", "sha256:direct"),
    )

    result = classify_intent_coverage(
        (inherited, direct),
        _report(edges=(blanket, symbol)),
        exemptions=(exemption,),
    )

    assert [row.classification for row in result.definitions] == ["exempt", "direct"]
    assert result.definitions[1].matching_exemption_ids == ("sha256:exemption",)
    assert result.exemptions[0].state == "used"


def test_exemption_ledger_distinguishes_overlap_only_and_unused() -> None:
    direct = CoverageDefinition(
        definition_id="sha256:direct",
        path="pkg/example.py",
        structural_locator="python-definition:run:function:0",
        qualname="run",
        kind="function",
        role="production",
        start_line=1,
        end_line=1,
        source_projection_sha256="sha256:run",
        parent_definition_id="sha256:module",
    )
    edge = Edge(
        kind="mapping",
        spec_path="docs/specs/01-example.md",
        section_id="EX-1",
        code_path="pkg/example.py",
        code_symbol="run",
        line=8,
    )

    result = classify_intent_coverage(
        (direct,),
        _report(edges=(edge,)),
        exemptions=(
            CoverageExemptionFact(
                exemption_id="sha256:overlap",
                matched_definition_ids=("sha256:direct",),
            ),
            CoverageExemptionFact(
                exemption_id="sha256:unused",
                matched_definition_ids=(),
            ),
        ),
    )

    assert [(item.exemption_id, item.state) for item in result.exemptions] == [
        ("sha256:overlap", "overlap_only"),
        ("sha256:unused", "unused"),
    ]


def test_summary_keeps_direct_and_accounted_metric_numerators_distinct() -> None:
    definition_rows = [
        CoverageDefinition(
            definition_id=f"sha256:{name}",
            path=f"pkg/{name}.py",
            structural_locator=f"python-definition:{name}:function:0",
            qualname=name,
            kind="function",
            role="production",
            start_line=1,
            end_line=1,
            source_projection_sha256=f"sha256:{name}-source",
            parent_definition_id=f"sha256:{name}-module",
        )
        for name in ("direct", "inherited", "exempt", "uncovered")
    ]
    definition_rows[1] = CoverageDefinition(
        definition_id="sha256:inherited",
        path="pkg/inherited.py",
        structural_locator="python-module:pkg.inherited",
        qualname="pkg.inherited",
        kind="module",
        role="production",
        start_line=1,
        end_line=1,
        source_projection_sha256="sha256:inherited-source",
        parent_definition_id=None,
    )
    definitions = tuple(definition_rows)
    edges = (
        Edge(
            kind="mapping",
            spec_path="docs/specs/01-example.md",
            section_id="EX-1",
            code_path="pkg/direct.py",
            code_symbol="direct",
            line=8,
        ),
        Edge(
            kind="mapping",
            spec_path="docs/specs/01-example.md",
            section_id="EX-2",
            code_path="pkg/inherited.py",
            code_symbol=None,
            line=9,
        ),
    )
    exemption = CoverageExemptionFact(
        exemption_id="sha256:exemption-row",
        matched_definition_ids=("sha256:exempt",),
    )

    result = classify_intent_coverage(
        definitions,
        _report(edges=edges),
        exemptions=(exemption,),
        inherited_counts=False,
    )

    assert result.summary.direct == 1
    assert result.summary.inherited == 1
    assert result.summary.exempt == 1
    assert result.summary.uncovered == 1
    assert result.summary.total == 4
    assert result.summary.direct_numerator == 1
    assert result.summary.accounted_numerator == 2


def test_summary_counts_inherited_definitions_only_when_enabled() -> None:
    module = CoverageDefinition(
        definition_id="sha256:module",
        path="pkg/example.py",
        structural_locator="python-module:pkg.example",
        qualname="pkg.example",
        kind="module",
        role="production",
        start_line=1,
        end_line=2,
        source_projection_sha256="sha256:module-source",
        parent_definition_id=None,
    )
    function = CoverageDefinition(
        definition_id="sha256:function",
        path="pkg/example.py",
        structural_locator="python-definition:run:function:0",
        qualname="run",
        kind="function",
        role="production",
        start_line=2,
        end_line=2,
        source_projection_sha256="sha256:function-source",
        parent_definition_id=module.definition_id,
    )
    edge = Edge(
        kind="mapping",
        spec_path="docs/specs/01-example.md",
        section_id="EX-1",
        code_path="pkg/example.py",
        code_symbol=None,
        line=8,
    )

    excluded = classify_intent_coverage(
        (module, function),
        _report(edges=(edge,)),
        inherited_counts=False,
    )
    included = classify_intent_coverage(
        (module, function),
        _report(edges=(edge,)),
        inherited_counts=True,
    )

    assert excluded.summary.accounted_numerator == 0
    assert included.summary.accounted_numerator == 2


def test_floor_enforcement_uses_exact_integer_numerators() -> None:
    definitions = tuple(
        CoverageDefinition(
            definition_id=f"sha256:{name}",
            path=f"pkg/{name}.py",
            structural_locator=f"python-definition:{name}:function:0",
            qualname=name,
            kind="function",
            role="production",
            start_line=1,
            end_line=1,
            source_projection_sha256=f"sha256:{name}-source",
            parent_definition_id=f"sha256:{name}-module",
        )
        for name in ("one", "two", "three")
    )
    edges = tuple(
        Edge(
            kind="mapping",
            spec_path="docs/specs/01-example.md",
            section_id=f"EX-{index}",
            code_path=definition.path,
            code_symbol=definition.qualname,
            line=index,
        )
        for index, definition in enumerate(definitions[:2], start=1)
    )
    result = classify_intent_coverage(definitions, _report(edges=edges))

    floors = evaluate_coverage_floors(
        result,
        (
            CoverageFloorFact(
                scope="pkg",
                direct_target=0.666666,
                accounted_target=None,
            ),
            CoverageFloorFact(
                scope="pkg/one.py",
                direct_target=1.0,
                accounted_target=1.0,
            ),
            CoverageFloorFact(
                scope="vendor",
                direct_target=0.0,
                accounted_target=0.0,
            ),
            CoverageFloorFact(
                scope="vendor/generated",
                direct_target=0.1,
                accounted_target=None,
            ),
        ),
        inherited_counts=False,
    )

    assert [item.passes for item in floors] == [True, True, True, False]
    assert floors[0].counts.direct_numerator == 2
    assert floors[0].counts.total == 3


def test_reverse_complement_distinguishes_absent_and_unresolved_mappings() -> None:
    sections = (
        SpecSection(
            path="docs/specs/01-example.md",
            section_id="EX-1",
            title="Absent",
            line=3,
            anchor="absent-ex-1",
            kind="heading",
        ),
        SpecSection(
            path="docs/specs/01-example.md",
            section_id="EX-2",
            title="Unresolved",
            line=8,
            anchor="unresolved-ex-2",
            kind="heading",
        ),
    )
    unresolved = SpecMapping(
        spec_path="docs/specs/01-example.md",
        section_id="EX-2",
        line=12,
        target="pkg/missing.py",
        kind="path",
        target_path="pkg/missing.py",
        target_symbol=None,
    )

    result = classify_intent_coverage(
        (),
        _report(sections=sections, mappings=(unresolved,)),
    )

    assert [row.implementation_state for row in result.requirements] == [
        "absent_mapping",
        "declared_without_live_owner",
    ]


def test_path_mapping_requirement_owner_is_only_the_synthesized_module() -> None:
    section = SpecSection(
        path="docs/specs/01-example.md",
        section_id="EX-1",
        title="Mapped",
        line=3,
        anchor="mapped-ex-1",
        kind="heading",
    )
    mapping = SpecMapping(
        spec_path=section.path,
        section_id=section.section_id,
        line=8,
        target="pkg/example.py",
        kind="path",
        target_path="pkg/example.py",
        target_symbol=None,
    )
    edge = Edge(
        kind="mapping",
        spec_path=section.path,
        section_id=section.section_id,
        code_path="pkg/example.py",
        code_symbol=None,
        line=8,
    )
    module = CoverageDefinition(
        definition_id="sha256:module",
        path="pkg/example.py",
        structural_locator="python-module:pkg.example",
        qualname="pkg.example",
        kind="module",
        role="production",
        start_line=1,
        end_line=4,
        source_projection_sha256="sha256:module-source",
        parent_definition_id=None,
    )
    function = CoverageDefinition(
        definition_id="sha256:function",
        path="pkg/example.py",
        structural_locator="python-definition:run:function:0",
        qualname="run",
        kind="function",
        role="production",
        start_line=3,
        end_line=4,
        source_projection_sha256="sha256:function-source",
        parent_definition_id="sha256:module",
    )

    result = classify_intent_coverage(
        (module, function),
        _report(edges=(edge,), sections=(section,), mappings=(mapping,)),
    )

    assert result.requirements[0].owner_definition_ids == ("sha256:module",)
