"""Dependency-direction gates for architecture remediation.

Spec: docs/specs/02-backstitch-core.md [SC-17]
Spec: docs/specs/05-backstitch-invariants.md [INV-11]
Plan: docs/plans/2026-07-29-architecture-quality-remediation-plan.md Slice 2

The independent Slice-3 review pulled the package-wide DAG and ranked-boundary
gate forward once all observed SCCs had been removed.
"""

from __future__ import annotations

import ast
from importlib.util import resolve_name
from pathlib import Path

PACKAGE_ROOT = Path(__file__).parents[1] / "backstitch"

# Every substantive package module has a reviewed rank. A module may import its
# own or a lower rank. New modules require an explicit architectural placement.
_LAYER_RANK = {
    # Leaf primitives and closed value contracts.
    "backstitch.artifact_publication": 0,
    "backstitch.canonical": 0,
    "backstitch.config": 0,
    "backstitch.contract_validation": 0,
    "backstitch.diagnostics": 0,
    "backstitch.filesystem_io": 0,
    "backstitch.grammar": 0,
    "backstitch.models": 0,
    "backstitch.operation_progress": 0,
    "backstitch.scan_exclusions": 0,
    "backstitch.semantic_eval_identity": 0,
    "backstitch.semantic_packets": 0,
    "backstitch.semantic_verification_contract": 0,
    # Source and configuration adapters.
    "backstitch.artifact_contracts": 1,
    "backstitch.alignment_guide": 1,
    "backstitch.code_parser": 1,
    "backstitch.exclusions": 1,
    "backstitch.git_baseline": 1,
    "backstitch.markdown_specs": 1,
    "backstitch.profiles": 1,
    "backstitch.python_refs": 1,
    "backstitch.repository_snapshot": 1,
    "backstitch.semantic_identity": 1,
    "backstitch.settings": 1,
    "backstitch.target_roots": 1,
    # Domain computation.
    "backstitch.analysis_packets": 2,
    "backstitch.analysis_results": 2,
    "backstitch.check_pipeline": 2,
    "backstitch.evidence_discovery": 2,
    "backstitch.evidence_summary": 2,
    "backstitch.intent_coverage": 2,
    "backstitch.intent_coverage_reporting": 2,
    "backstitch.intent_history": 2,
    "backstitch.obligation_runtime": 2,
    "backstitch.obligations": 2,
    "backstitch.reporting": 2,
    "backstitch.resolver": 2,
    "backstitch.semantic_analysis": 2,
    "backstitch.semantic_budget": 2,
    "backstitch.semantic_cache": 2,
    "backstitch.semantic_evidence": 2,
    "backstitch.semantic_eval_observation": 2,
    "backstitch.semantic_eval_reports": 2,
    "backstitch.semantic_policy": 2,
    "backstitch.semantic_reports": 2,
    "backstitch.semantic_verification": 2,
    # Application workflows.
    "backstitch.alignment_eval": 3,
    "backstitch.analysis_llm": 3,
    "backstitch.check_application": 3,
    "backstitch.coverage_application": 3,
    "backstitch.doctor": 3,
    "backstitch.obligation_api": 3,
    "backstitch.packet_application": 3,
    "backstitch.semantic_application": 3,
    "backstitch.semantic_eval": 3,
    # Public adapter.
    "backstitch.__main__": 4,
    "backstitch.cli": 4,
}


def _module_name(path: Path) -> str:
    relative = path.relative_to(PACKAGE_ROOT.parent).with_suffix("")
    return ".".join(relative.parts)


def _internal_imports(  # noqa: C901 approved [SC-17.1] RUFF-SUP-147 exception
    module: str,
    source: bytes,
    modules: frozenset[str],
) -> frozenset[str]:
    """Return every static package edge, including local and TYPE_CHECKING imports.

    TYPE_CHECKING edges are an intentional conservative superset of the runtime
    graph. Proving this larger graph acyclic also proves the [SC-17] runtime
    graph acyclic, while avoiding conditional-AST rules that can hide edges.
    """

    imported: set[str] = set()
    package = module.rpartition(".")[0] or module
    for node in ast.walk(ast.parse(source, filename=module)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                for end in range(len(parts), 0, -1):
                    candidate = ".".join(parts[:end])
                    if candidate in modules:
                        imported.add(candidate)
                        break
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level:
            relative = "." * node.level + (node.module or "")
            base = resolve_name(relative, package)
        else:
            base = node.module or ""
        if base in modules and base != "backstitch":
            imported.add(base)
        for alias in node.names:
            candidate = f"{base}.{alias.name}" if base else alias.name
            if candidate in modules:
                imported.add(candidate)
    imported.discard(module)
    return frozenset(imported)


def _import_graph() -> dict[str, frozenset[str]]:
    sources = {
        _module_name(path): path.read_bytes()
        for path in sorted(PACKAGE_ROOT.rglob("*.py"))
    }
    modules = frozenset(sources)
    return {
        module: _internal_imports(module, source, modules)
        for module, source in sources.items()
    }


def _strongly_connected_components(  # noqa: C901 approved [SC-17.1] RUFF-SUP-149 exception
    graph: dict[str, frozenset[str]],
) -> tuple[frozenset[str], ...]:
    """Return deterministic SCCs using two depth-first graph passes."""

    visited: set[str] = set()
    finish_order: list[str] = []

    def visit(node: str) -> None:
        if node in visited:
            return
        visited.add(node)
        for neighbor in sorted(graph[node]):
            visit(neighbor)
        finish_order.append(node)

    for node in sorted(graph):
        visit(node)

    reversed_graph: dict[str, set[str]] = {node: set() for node in graph}
    for node, neighbors in graph.items():
        for neighbor in neighbors:
            reversed_graph[neighbor].add(node)

    assigned: set[str] = set()
    components: list[frozenset[str]] = []

    def collect(node: str, component: set[str]) -> None:
        if node in assigned:
            return
        assigned.add(node)
        component.add(node)
        for neighbor in sorted(reversed_graph[node]):
            collect(neighbor, component)

    for node in reversed(finish_order):
        if node in assigned:
            continue
        component: set[str] = set()
        collect(node, component)
        components.append(frozenset(component))
    return tuple(components)


def _private_imports(  # noqa: C901 approved [SC-17.1] RUFF-SUP-148 exception
    importer: str,
    source: bytes,
) -> tuple[tuple[str, str, str], ...]:
    violations: list[tuple[str, str, str]] = []
    package = importer.rpartition(".")[0] or importer
    tree = ast.parse(source, filename=importer)
    module_aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            module_aliases.update(
                {
                    alias.asname or alias.name: alias.name
                    for alias in node.names
                    if alias.name in _LAYER_RANK
                }
            )
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level:
            relative = "." * node.level + (node.module or "")
            imported = resolve_name(relative, package)
        else:
            imported = node.module or ""
        if imported in _LAYER_RANK and _LAYER_RANK[imported] != _LAYER_RANK[importer]:
            violations.extend(
                (importer, imported, alias.name)
                for alias in node.names
                if alias.name.startswith("_")
            )
        if imported == "backstitch":
            module_aliases.update(
                {
                    alias.asname or alias.name: f"{imported}.{alias.name}"
                    for alias in node.names
                    if f"{imported}.{alias.name}" in _LAYER_RANK
                }
            )
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or not node.attr.startswith("_"):
            continue
        parts = [node.attr]
        owner = node.value
        while isinstance(owner, ast.Attribute):
            parts.append(owner.attr)
            owner = owner.value
        if not isinstance(owner, ast.Name):
            continue
        parts.append(owner.id)
        qualified = ".".join(reversed(parts))
        for alias, imported in module_aliases.items():
            if not qualified.startswith(f"{alias}."):
                continue
            if _LAYER_RANK[imported] == _LAYER_RANK[importer]:
                continue
            violations.append((importer, imported, qualified.removeprefix(alias)))
    return tuple(violations)


def _private_cross_layer_imports() -> tuple[tuple[str, str, str], ...]:
    return tuple(
        violation
        for path in sorted(PACKAGE_ROOT.rglob("*.py"))
        if (importer := _module_name(path)) in _LAYER_RANK
        for violation in _private_imports(importer, path.read_bytes())
    )


def test_import_discovery_includes_function_local_edges() -> None:
    modules = frozenset(
        {"backstitch.example", "backstitch.settings", "backstitch.filesystem_io"}
    )
    imports = _internal_imports(
        "backstitch.example",
        (
            b"from backstitch import filesystem_io\n"
            b"def load():\n"
            b"    from backstitch.settings import resolve_config\n"
        ),
        modules,
    )
    assert imports == frozenset({"backstitch.filesystem_io", "backstitch.settings"})


def test_import_discovery_intentionally_includes_type_checking_edges() -> None:
    modules = frozenset({"backstitch.example", "backstitch.check_pipeline"})
    imports = _internal_imports(
        "backstitch.example",
        (
            b"from typing import TYPE_CHECKING\n"
            b"if TYPE_CHECKING:\n"
            b"    from backstitch.check_pipeline import ObligationSkipAudit\n"
        ),
        modules,
    )
    assert imports == frozenset({"backstitch.check_pipeline"})


def test_private_import_discovery_includes_module_attribute_access() -> None:
    assert _private_imports(
        "backstitch.cli",
        (
            b"import backstitch.settings as config\n"
            b"from backstitch import repository_snapshot as snapshot\n"
            b"config._hidden()\n"
            b"snapshot._private()\n"
        ),
    ) == (
        ("backstitch.cli", "backstitch.settings", "._hidden"),
        ("backstitch.cli", "backstitch.repository_snapshot", "._private"),
    )


def test_settings_and_snapshot_are_not_one_component() -> None:
    components = _strongly_connected_components(_import_graph())
    settings_component = next(
        component for component in components if "backstitch.settings" in component
    )
    assert "backstitch.repository_snapshot" not in settings_component


def test_internal_import_graph_has_no_multimodule_components() -> None:
    components = _strongly_connected_components(_import_graph())
    assert [component for component in components if len(component) > 1] == []


def test_every_substantive_package_module_has_exactly_one_rank() -> None:
    modules = set(_import_graph()) - {"backstitch.__init__"}
    assert set(_LAYER_RANK) == modules


def test_mapped_layers_do_not_import_upward() -> None:
    graph = _import_graph()
    violations = [
        (importer, imported)
        for importer, importer_rank in _LAYER_RANK.items()
        for imported in sorted(graph[importer])
        if imported in _LAYER_RANK and importer_rank < _LAYER_RANK[imported]
    ]
    assert violations == []


def test_obligation_application_uses_runtime_evidence_summary_owner() -> None:
    tree = ast.parse(
        (PACKAGE_ROOT / "obligation_api.py").read_bytes(),
        filename="backstitch.obligation_api",
    )
    direct_builder_imports = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "backstitch.evidence_summary"
        for alias in node.names
        if alias.name == "build_evidence_summary_items"
    ]
    runtime_summary_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "evidence_summary"
    ]

    assert direct_builder_imports == []
    assert len(runtime_summary_calls) == 1


def test_mapped_layers_do_not_import_private_symbols_across_ranks() -> None:
    assert _private_cross_layer_imports() == ()
