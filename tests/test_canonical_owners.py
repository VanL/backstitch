"""Closed ownership pins for the evidence-spike hardening slices.

The historical inventories document the exact Slice 0 baseline. The active
test below asserts the complete post-Slice-1 owner inventory, so a partial
migration cannot look green merely because a broad pattern stopped recognizing
one old spelling.
"""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass
from pathlib import Path

import pytest

import backstitch.alignment_eval as alignment_eval
import backstitch.canonical as canonical_module
import backstitch.diagnostics as diagnostics
import backstitch.scan_exclusions as scan_exclusions
import backstitch.semantic_cache as semantic_cache
import backstitch.settings as settings_module
from backstitch.filesystem_io import file_stat_identity

PACKAGE_ROOT = Path(__file__).parents[1] / "backstitch"
_UNRESOLVED = object()


@dataclass(frozen=True, order=True)
class Site:
    """One syntax-owned implementation site, stable across line movement."""

    module: str
    owner: str
    kind: str


def _module_name(path: Path) -> str:
    relative = path.relative_to(PACKAGE_ROOT.parent).with_suffix("")
    return ".".join(relative.parts)


def _literal(node: ast.AST) -> object:
    try:
        return ast.literal_eval(node)
    except (TypeError, ValueError):
        return _UNRESOLVED


class _Inventory(ast.NodeVisitor):
    def __init__(self, module: str) -> None:
        self.module = module
        self.scope: list[str] = []
        self.sites: set[Site] = set()
        self.imports: dict[str, str] = {}
        self.constants: dict[str, object] = {}
        self.prompt_authorities: set[tuple[str, str]] = set()
        self.exclusive_prompt_pairs: set[tuple[str, frozenset[str]]] = set()

    @property
    def owner(self) -> str:
        return ".".join(self.scope) if self.scope else "<module>"

    def _record(self, kind: str) -> None:
        self.sites.add(Site(self.module, self.owner, kind))

    def _qualified_name(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return self.imports.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            parent = self._qualified_name(node.value)
            return None if parent is None else f"{parent}.{node.attr}"
        return None

    def _resolved_literal(self, node: ast.AST) -> object:
        if isinstance(node, ast.Name) and node.id in self.constants:
            return self.constants[node.id]
        return _literal(node)

    def _is_prompt_authority(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Constant):
            return isinstance(node.value, bytes)
        if isinstance(node, ast.Attribute):
            return node.attr == "prompt_bytes"
        if isinstance(node, ast.Name):
            return (self.owner, node.id) in self.prompt_authorities
        if isinstance(node, ast.IfExp):
            relation = self._none_relation(node.test)
            if relation is not None:
                tested_name, tested_is_non_none = relation
                frozen_branch = node.body if tested_is_non_none else node.orelse
                alternate_branch = node.orelse if tested_is_non_none else node.body
                alternate_name = self._cast_bytes_name(alternate_branch)
                if (
                    alternate_name is not None
                    and self._is_identity_prompt_bytes(frozen_branch, tested_name)
                    and (
                        self.owner,
                        frozenset((tested_name, alternate_name)),
                    )
                    in self.exclusive_prompt_pairs
                ):
                    return True
            return self._is_prompt_authority(node.body) and self._is_prompt_authority(
                node.orelse
            )
        return False

    @staticmethod
    def _none_relation(node: ast.AST) -> tuple[str, bool] | None:
        if (
            not isinstance(node, ast.Compare)
            or len(node.ops) != 1
            or len(node.comparators) != 1
            or not isinstance(node.left, ast.Name)
            or not isinstance(node.comparators[0], ast.Constant)
            or node.comparators[0].value is not None
        ):
            return None
        if isinstance(node.ops[0], ast.IsNot):
            return node.left.id, True
        if isinstance(node.ops[0], ast.Is):
            return node.left.id, False
        return None

    @staticmethod
    def _is_identity_prompt_bytes(node: ast.AST, identity_name: str) -> bool:
        return (
            isinstance(node, ast.Attribute)
            and node.attr == "prompt_bytes"
            and isinstance(node.value, ast.Name)
            and node.value.id == identity_name
        )

    def _cast_bytes_name(self, node: ast.AST) -> str | None:
        if (
            isinstance(node, ast.Call)
            and self._qualified_name(node.func) == "typing.cast"
            and len(node.args) == 2
            and self._qualified_name(node.args[0]) == "bytes"
            and isinstance(node.args[1], ast.Name)
        ):
            return node.args[1].id
        return None

    def _record_exclusive_prompt_guards(self, node: ast.FunctionDef) -> None:
        for statement in node.body:
            if (
                not isinstance(statement, ast.If)
                or not any(isinstance(item, ast.Raise) for item in statement.body)
                or not isinstance(statement.test, ast.Compare)
                or len(statement.test.ops) != 1
                or not isinstance(statement.test.ops[0], ast.Eq)
                or len(statement.test.comparators) != 1
            ):
                continue
            left = self._none_relation(statement.test.left)
            right = self._none_relation(statement.test.comparators[0])
            if left is not None and right is not None and not left[1] and not right[1]:
                self.exclusive_prompt_pairs.add(
                    (self.owner, frozenset((left[0], right[0])))
                )

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports[alias.asname or alias.name] = alias.name
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module is not None:
            for alias in node.names:
                self.imports[alias.asname or alias.name] = f"{node.module}.{alias.name}"
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        value = _literal(node.value)
        prompt_authority = self._is_prompt_authority(node.value)
        for target in node.targets:
            if isinstance(target, ast.Name):
                self.constants[target.id] = value
                key = (self.owner, target.id)
                if prompt_authority:
                    self.prompt_authorities.add(key)
                else:
                    self.prompt_authorities.discard(key)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.scope.append(node.name)
        self._record_exclusive_prompt_guards(node)
        if node.name in {"is_excluded", "_is_excluded"}:
            self._record("exclusion_matcher")
        attributes = {
            item.attr for item in ast.walk(node) if isinstance(item, ast.Attribute)
        }
        if {"open", "lstat", "fstat", "read"}.issubset(attributes):
            self._record("no_follow_read")
        calls = [item for item in ast.walk(node) if isinstance(item, ast.Call)]
        lf_split_targets: set[str] = set()
        for assignment in (
            item for item in ast.walk(node) if isinstance(item, ast.Assign)
        ):
            if isinstance(assignment.value, ast.Call) and self._qualified_name(
                assignment.value.func
            ) in {
                "backstitch.canonical.lf_split",
                "canonical.lf_split",
                "lf_split",
            }:
                lf_split_targets.update(
                    target.id
                    for target in assignment.targets
                    if isinstance(target, ast.Name)
                )

        def slices_lf_split(candidate: ast.AST) -> bool:
            if not isinstance(candidate, ast.Subscript):
                return False
            source = candidate.value
            if (
                isinstance(source, ast.Call)
                and self._qualified_name(source.func) == "typing.cast"
                and len(source.args) == 2
            ):
                source = source.args[1]
            return (
                isinstance(source, ast.Call)
                and self._qualified_name(source.func)
                in {
                    "backstitch.canonical.lf_split",
                    "canonical.lf_split",
                    "lf_split",
                }
            ) or (isinstance(source, ast.Name) and source.id in lf_split_targets)

        has_lf_slice_join = any(
            isinstance(call.func, ast.Attribute)
            and call.func.attr == "join"
            and any(slices_lf_split(item) for item in ast.walk(call))
            for call in calls
        )
        if has_lf_slice_join:
            self._record("span_primitive")
        structurally_counts_lf = any(
            isinstance(item, ast.Compare)
            and any(isinstance(operator, (ast.Eq, ast.NotEq)) for operator in item.ops)
            and 10
            in (
                self._resolved_literal(item.left),
                *(self._resolved_literal(value) for value in item.comparators),
            )
            for item in ast.walk(node)
        )
        if structurally_counts_lf:
            self._record("manual_lf_arithmetic")
        self.generic_visit(node)
        self.scope.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def _record_json_call(self, node: ast.Call, qualified: str | None) -> None:
        if qualified == "json.dumps":
            keywords = {
                item.arg: self._resolved_literal(item.value) for item in node.keywords
            }
            if (
                keywords.get("sort_keys") is True
                and "separators" in keywords
                and keywords["separators"] is _UNRESOLVED
            ):
                self._record("dynamic_canonical_json")
            if (
                keywords.get("sort_keys") is True
                and keywords.get("separators") == (",", ":")
                and keywords.get("ensure_ascii", True) is True
            ):
                self._record("canonical_json")

    def _record_prompt_call(self, node: ast.Call, qualified: str | None) -> None:
        prompt_keyword: str | None = None
        if qualified in {
            "backstitch.semantic_packets.model_request_bytes",
            "semantic_packets.model_request_bytes",
        }:
            prompt_keyword = "instruction_bytes"
        elif qualified in {
            "backstitch.semantic_verification.verifier_request_bytes",
            "semantic_verification.verifier_request_bytes",
        }:
            prompt_keyword = "prompt_bytes"
        if prompt_keyword is not None:
            authority = next(
                (item.value for item in node.keywords if item.arg == prompt_keyword),
                None,
            )
            if authority is None or not self._is_prompt_authority(authority):
                self._record("prompt_resource_read")

    def _record_sha_join_call(self, node: ast.Call) -> None:
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "join"
            and _literal(node.func.value) == ":"
            and node.args
            and isinstance(node.args[0], (ast.Tuple, ast.List))
            and [_literal(item) for item in node.args[0].elts[:2]]
            == ["candidate", "sha256"]
        ):
            self._record("sha256_grammar")

    def _record_newline_call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute):
            if node.func.attr == "splitlines":
                self._record("splitlines")
            elif (
                node.func.attr == "split"
                and node.args
                and _literal(node.args[0]) in {"\n", b"\n"}
            ):
                self._record("lf_split")
            elif (
                node.func.attr == "count"
                and node.args
                and _literal(node.args[0]) in {"\n", b"\n"}
            ):
                self._record("manual_lf_arithmetic")

    def visit_Call(self, node: ast.Call) -> None:
        qualified = self._qualified_name(node.func)
        self._record_json_call(node, qualified)
        self._record_prompt_call(node, qualified)
        self._record_sha_join_call(node)
        self._record_newline_call(node)
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str):
            if "[0-9a-f]{64}" in node.value:
                self._record("sha256_grammar")
            if node.value in {"0123456789abcdef", "candidate:sha256:"}:
                self._record("sha256_grammar")
        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> None:
        values = {
            _literal(key): _literal(value)
            for key, value in zip(node.keys, node.values, strict=True)
            if key is not None
        }
        if values == {"error": 0, "warning": 1, "info": 2}:
            self._record("issue_sort_key")
        self.generic_visit(node)

    def visit_Tuple(self, node: ast.Tuple) -> None:
        attributes = {
            child.attr for child in ast.walk(node) if isinstance(child, ast.Attribute)
        }
        if {"st_dev", "st_ino", "st_size", "st_mtime_ns"}.issubset(attributes):
            self._record("stat_identity")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr == "O_NOFOLLOW":
            self._record("no_follow_read")
        self.generic_visit(node)


def _production_sites() -> frozenset[Site]:
    sites: set[Site] = set()
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        visitor = _Inventory(_module_name(path))
        visitor.visit(ast.parse(path.read_bytes(), filename=path.as_posix()))
        sites.update(visitor.sites)
    return frozenset(sites)


def _sites(kind: str) -> frozenset[Site]:
    return frozenset(item for item in _production_sites() if item.kind == kind)


def test_python_structural_locator_has_one_production_formatter_owner() -> None:
    """Tests-invariant: [INV.IDENTITY.1]

    Locator consumers may inspect prefixes, but only one owner formats them.
    """

    formatters: set[Site] = set()
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_bytes(), filename=path.as_posix())
        module = _module_name(path)
        parents: dict[ast.AST, ast.AST] = {
            child: parent
            for parent in ast.walk(tree)
            for child in ast.iter_child_nodes(parent)
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.JoinedStr):
                continue
            literal = "".join(
                part.value
                for part in node.values
                if isinstance(part, ast.Constant) and isinstance(part.value, str)
            )
            if not any(
                prefix in literal
                for prefix in (
                    "python-module:",
                    "python-module-path:",
                    "python-definition:",
                )
            ):
                continue
            owner = "<module>"
            current: ast.AST | None = node
            while current is not None:
                current = parents.get(current)
                if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    owner = current.name
                    break
            formatters.add(Site(module, owner, "python_structural_locator"))

    assert formatters == {
        Site(
            "backstitch.python_refs",
            "python_structural_locator",
            "python_structural_locator",
        )
    }


CANONICAL_JSON_DISPLAY_EXEMPTION_REASONS = {
    Site("backstitch.cli", "_cmd_packets", "canonical_json"): (
        "renders bounded error details into a failure message, never an identity"
    ),
    Site("backstitch.cli", "_analyze_failure_error", "canonical_json"): (
        "renders bounded error details into a failure message, never an identity"
    ),
}
CANONICAL_JSON_DISPLAY_EXEMPTIONS = frozenset(CANONICAL_JSON_DISPLAY_EXEMPTION_REASONS)

SLICE7_PROMPT_CONSUMERS = (
    Site(
        "backstitch.semantic_analysis",
        "_packet_report_preflight",
        "prompt_resource_read",
    ),
    Site("backstitch.semantic_analysis", "_estimate_cost", "prompt_resource_read"),
    Site(
        "backstitch.semantic_analysis",
        "_run_semantic_analysis",
        "prompt_resource_read",
    ),
    Site("backstitch.semantic_reports", "build_packet_report", "prompt_resource_read"),
    Site(
        "backstitch.semantic_reports",
        "validate_packet_report",
        "prompt_resource_read",
    ),
    Site("backstitch.semantic_eval", "_analysis_cost", "prompt_resource_read"),
    Site("backstitch.semantic_eval", "_assert_prompt_limits", "prompt_resource_read"),
)


HISTORICAL_SLICE_0_CANONICAL_JSON = frozenset(
    {
        Site("backstitch.alignment_guide", "render_alignment_guide", "canonical_json"),
        Site(
            "backstitch.artifact_contracts", "invariant_content_hash", "canonical_json"
        ),
        Site(
            "backstitch.evidence_discovery", "_canonical_json_bytes", "canonical_json"
        ),
        Site("backstitch.evidence_summary", "_merge_declarations", "canonical_json"),
        Site("backstitch.obligation_api", "_canonical_json_bytes", "canonical_json"),
        Site("backstitch.obligation_api", "render_envelope_json", "canonical_json"),
        Site("backstitch.obligation_api", "render_envelope_text", "canonical_json"),
        Site("backstitch.obligations", "_canonical_json_bytes", "canonical_json"),
        Site("backstitch.semantic_packets", "canonical_json_bytes", "canonical_json"),
    }
)

HISTORICAL_SLICE_0_SHA256_GRAMMARS = frozenset(
    {
        Site("backstitch.alignment_eval", "<module>", "sha256_grammar"),
        Site("backstitch.alignment_eval", "_candidate_projection", "sha256_grammar"),
        Site("backstitch.alignment_eval", "_validate_gold", "sha256_grammar"),
        Site(
            "backstitch.alignment_eval",
            "_validate_recorded_backstitch_argv",
            "sha256_grammar",
        ),
        Site("backstitch.analysis_results", "<module>", "sha256_grammar"),
        Site("backstitch.artifact_contracts", "_lower_sha256", "sha256_grammar"),
        Site(
            "backstitch.artifact_contracts",
            "_packet_v3_shape_error",
            "sha256_grammar",
        ),
        Site("backstitch.cli", "_validate_obligation_invocation", "sha256_grammar"),
        Site("backstitch.evidence_discovery", "_candidate_id", "sha256_grammar"),
        Site("backstitch.evidence_summary", "_valid_summary_locator", "sha256_grammar"),
        Site("backstitch.obligation_api", "_valid_candidate_after", "sha256_grammar"),
        Site("backstitch.obligation_api", "decode_page_cursor", "sha256_grammar"),
        Site("backstitch.semantic_analysis", "<module>", "sha256_grammar"),
        Site("backstitch.semantic_cache", "<module>", "sha256_grammar"),
        Site("backstitch.semantic_eval_reports", "<module>", "sha256_grammar"),
        Site("backstitch.semantic_eval_reports", "_candidate_id", "sha256_grammar"),
        Site(
            "backstitch.semantic_identity", "build_inference_identity", "sha256_grammar"
        ),
        Site("backstitch.semantic_policy", "_is_sha256", "sha256_grammar"),
        Site("backstitch.semantic_reports", "<module>", "sha256_grammar"),
        Site(
            "backstitch.semantic_verification",
            "_canonical_claim_evidence",
            "sha256_grammar",
        ),
        Site("backstitch.settings", "<module>", "sha256_grammar"),
    }
)

HISTORICAL_SLICE_0_ISSUE_SORT_KEYS = frozenset(
    {
        Site("backstitch.check_pipeline", "_apply_check_policy", "issue_sort_key"),
        Site("backstitch.resolver", "_sort_report_parts", "issue_sort_key"),
        Site(
            "backstitch.semantic_reports", "_packet_report_v2_shape", "issue_sort_key"
        ),
    }
)

HISTORICAL_SLICE_0_NO_FOLLOW_READS = frozenset(
    {
        Site(
            "backstitch.alignment_eval",
            "_authoritative_regular_input",
            "no_follow_read",
        ),
        Site(
            "backstitch.repository_snapshot",
            "_inventory_open_directory",
            "no_follow_read",
        ),
        Site("backstitch.repository_snapshot", "_open_directory", "no_follow_read"),
        Site("backstitch.repository_snapshot", "_open_file", "no_follow_read"),
        Site(
            "backstitch.repository_snapshot",
            "_validate_config_sources",
            "no_follow_read",
        ),
        Site(
            "backstitch.repository_snapshot",
            "capture_repository_snapshot",
            "no_follow_read",
        ),
    }
)

HISTORICAL_SLICE_0_STAT_IDENTITIES = frozenset(
    {
        Site(
            "backstitch.alignment_eval", "_authoritative_stat_identity", "stat_identity"
        ),
        Site("backstitch.repository_snapshot", "_file_stat_identity", "stat_identity"),
        Site("backstitch.semantic_eval_reports", "_read_regular", "stat_identity"),
        Site("backstitch.settings", "_config_stat_identity", "stat_identity"),
    }
)

HISTORICAL_SLICE_0_EXCLUSION_MATCHERS = frozenset(
    {
        Site("backstitch.repository_snapshot", "_is_excluded", "exclusion_matcher"),
        Site("backstitch.settings", "is_excluded", "exclusion_matcher"),
    }
)

HISTORICAL_SLICE_0_LINE_SITES = frozenset(
    {
        Site("backstitch.alignment_eval", "_candidate_projection", "splitlines"),
        Site("backstitch.alignment_eval", "_tree_delta_stats", "splitlines"),
        Site("backstitch.alignment_eval", "_validate_gold", "splitlines"),
        Site("backstitch.analysis_packets", "_generate_section_packets", "splitlines"),
        Site(
            "backstitch.analysis_packets", "_invariant_declaration_record", "splitlines"
        ),
        Site("backstitch.analysis_packets", "_owner_snippet", "splitlines"),
        Site("backstitch.analysis_results", "_validate_v2_analysis_row", "lf_split"),
        Site("backstitch.analysis_results", "load_analysis_results", "splitlines"),
        Site(
            "backstitch.artifact_contracts", "_closed_snippet_item_error", "splitlines"
        ),
        Site("backstitch.artifact_contracts", "_load_packets_text", "splitlines"),
        Site("backstitch.artifact_contracts", "_normalize_legacy_packet", "splitlines"),
        Site("backstitch.artifact_contracts", "_packet_v3_span", "lf_split"),
        Site(
            "backstitch.artifact_contracts",
            "_v2_invariant_packet_shape_error",
            "splitlines",
        ),
        Site(
            "backstitch.artifact_contracts",
            "_v2_section_packet_shape_error",
            "splitlines",
        ),
        Site("backstitch.code_parser", "_LineIndex.__init__", "manual_lf_arithmetic"),
        Site("backstitch.code_parser", "parse_python_source", "splitlines"),
        Site("backstitch.evidence_discovery", "_catalog_python", "splitlines"),
        Site("backstitch.evidence_discovery", "_line_span", "splitlines"),
        Site("backstitch.evidence_summary", "_line_span", "splitlines"),
        Site("backstitch.evidence_summary", "_python_atom", "splitlines"),
        Site("backstitch.exclusions", "parse_noqa_text", "splitlines"),
        Site("backstitch.markdown_specs", "_first_inline_line", "splitlines"),
        Site("backstitch.markdown_specs", "_packet_source_lines", "lf_split"),
        Site("backstitch.markdown_specs", "parse_markdown_spec_bytes", "splitlines"),
        Site(
            "backstitch.markdown_specs",
            "parse_markdown_spec_bytes.process_html_block",
            "splitlines",
        ),
        Site(
            "backstitch.markdown_specs",
            "parse_markdown_spec_bytes.process_invariant_paragraph",
            "splitlines",
        ),
        Site(
            "backstitch.obligation_runtime",
            "unaddressable_issue_excerpts",
            "splitlines",
        ),
        Site("backstitch.python_refs", "_physical_doc_lines", "splitlines"),
        Site("backstitch.python_refs", "parse_python_bytes", "splitlines"),
        Site("backstitch.semantic_eval_reports", "_span_bytes", "splitlines"),
        Site("backstitch.semantic_evidence", "_region", "lf_split"),
        Site("backstitch.semantic_packets", "_evidence_region", "splitlines"),
        Site("backstitch.semantic_packets", "_maximal_snippet_records", "splitlines"),
        Site("backstitch.semantic_packets", "_with_derived_end_line", "splitlines"),
        Site("backstitch.semantic_packets", "semantic_packet_projection", "splitlines"),
        Site("backstitch.semantic_reports", "_revalidate_result_jsonl", "splitlines"),
        Site("backstitch.semantic_reports", "_validate_evidence", "lf_split"),
        Site("backstitch.semantic_reports", "validate_analysis_report", "splitlines"),
    }
)


def test_slice_1_closed_owner_inventories_match_the_live_tree() -> None:
    """Pin every allowed implementation site after owner consolidation."""

    assert (
        _sites("canonical_json")
        == frozenset(
            {Site("backstitch.canonical", "canonical_json_bytes", "canonical_json")}
        )
        | CANONICAL_JSON_DISPLAY_EXEMPTIONS
    )
    assert _sites("sha256_grammar") == frozenset(
        {
            Site("backstitch.grammar", "<module>", "sha256_grammar"),
            Site("backstitch.grammar", "candidate_ref", "sha256_grammar"),
        }
    )
    assert _sites("issue_sort_key") == frozenset(
        {Site("backstitch.models", "issue_sort_key", "issue_sort_key")}
    )
    assert {item.module for item in _sites("no_follow_read")} == {
        "backstitch.filesystem_io",
        "backstitch.repository_snapshot",
    }
    assert _sites("stat_identity") == frozenset(
        {
            Site(
                "backstitch.filesystem_io",
                "file_stat_identity",
                "stat_identity",
            )
        }
    )
    assert _sites("exclusion_matcher") == frozenset(
        {Site("backstitch.scan_exclusions", "is_excluded", "exclusion_matcher")}
    )
    assert frozenset(
        item
        for item in _production_sites()
        if item.kind in {"splitlines", "lf_split", "manual_lf_arithmetic"}
    ) == frozenset({Site("backstitch.canonical", "lf_split", "lf_split")})


def test_canonical_json_has_one_production_owner() -> None:
    """Tests-invariant: [INV.CANON.1]

    Slice-1 pin: inline identity encoders count as implementations too.
    """

    assert _sites("canonical_json") - CANONICAL_JSON_DISPLAY_EXEMPTIONS == frozenset(
        {Site("backstitch.canonical", "canonical_json_bytes", "canonical_json")}
    )
    assert _sites("dynamic_canonical_json") == frozenset()


@pytest.mark.parametrize(
    "source",
    (
        "import json\ndef encode(value):\n"
        "    return json.dumps(value, sort_keys=True, separators=(',', ':'))\n",
        "from json import dumps as d\ndef encode(value):\n"
        "    return d(value, sort_keys=True, separators=(',', ':'))\n",
        "import json\nSEP = (',', ':')\ndef encode(value):\n"
        "    return json.dumps(value, sort_keys=True, separators=SEP)\n",
    ),
    ids=("ensure-ascii-default", "from-import-alias", "constant-separators"),
)
def test_canonical_json_inventory_closes_known_ast_evasions(source: str) -> None:
    visitor = _Inventory("synthetic")
    visitor.visit(ast.parse(source))
    assert Site("synthetic", "encode", "canonical_json") in visitor.sites


def test_canonical_json_inventory_rejects_dynamic_separators() -> None:
    visitor = _Inventory("synthetic")
    visitor.visit(
        ast.parse(
            "import json\n"
            "def encode(value, separators):\n"
            "    return json.dumps(value, sort_keys=True, separators=separators)\n"
        )
    )
    assert Site("synthetic", "encode", "dynamic_canonical_json") in visitor.sites


def test_newline_inventory_is_structural_not_variable_name_based() -> None:
    visitor = _Inventory("synthetic")
    visitor.visit(
        ast.parse(
            "def count_lines(raw):\n"
            "    total = 1\n"
            "    for unit in raw:\n"
            "        if unit == 10:\n"
            "            total += 1\n"
            "    return total\n"
        )
    )
    assert Site("synthetic", "count_lines", "manual_lf_arithmetic") in visitor.sites


@pytest.mark.parametrize(
    "source",
    (
        "from backstitch.canonical import lf_split as split_lf\n"
        "def span(raw):\n"
        "    lines = split_lf(raw, keepends=True)\n"
        "    return b''.join(lines[1:2])\n",
        "import backstitch.canonical as canon\n"
        "def span(raw):\n"
        "    return b''.join(canon.lf_split(raw, keepends=True)[1:2])\n",
    ),
    ids=("from-import-alias", "module-alias"),
)
def test_span_inventory_resolves_aliased_lf_split_calls(source: str) -> None:
    visitor = _Inventory("synthetic")
    visitor.visit(ast.parse(source))
    assert Site("synthetic", "span", "span_primitive") in visitor.sites


def test_span_slicing_has_one_policy_owning_primitive() -> None:
    """Slice 7.0 pin for the complete INV.LINE.1 span-helper inventory."""

    assert _sites("span_primitive") == frozenset(
        {Site("backstitch.canonical", "lf_slice", "span_primitive")}
    )


@pytest.mark.parametrize(
    ("raw", "start", "end", "expected"),
    (
        (b"", 1, 1, b""),
        (b"a\nb", 0, 1, b"a\n"),
        (b"a\nb", -2, 1, b"a\n"),
        (b"a\nb", 2, 1, b""),
        (b"a\nb", 3, 3, b""),
        (b"a\nb", 1, 9, b"a\nb"),
        (b"a\n", 1, 1, b"a\n"),
        (b"a\n", 2, 2, b""),
    ),
    ids=(
        "empty",
        "zero-start",
        "negative-start",
        "reversed",
        "start-past-eof",
        "end-past-eof",
        "terminal-lf-last-line",
        "terminal-lf-no-phantom",
    ),
)
def test_clamped_span_policy_matrix(
    raw: bytes,
    start: int,
    end: int,
    expected: bytes,
) -> None:
    assert (
        canonical_module.lf_slice(
            raw,
            start,
            end,
            policy="clamped",
        )
        == expected
    )


@pytest.mark.parametrize(
    ("raw", "start", "end", "raises"),
    (
        (b"", 1, 1, True),
        (b"a\nb", 0, 1, True),
        (b"a\nb", -2, 1, True),
        (b"a\nb", 2, 1, True),
        (b"a\nb", 3, 3, True),
        (b"a\nb", 1, 9, True),
        (b"a\n", 1, 1, False),
        (b"a\n", 2, 2, True),
    ),
    ids=(
        "empty",
        "zero-start",
        "negative-start",
        "reversed",
        "start-past-eof",
        "end-past-eof",
        "terminal-lf-last-line",
        "terminal-lf-no-phantom",
    ),
)
def test_strict_span_policy_matrix(
    raw: bytes,
    start: int,
    end: int,
    raises: bool,
) -> None:
    if raises:
        with pytest.raises(ValueError):
            canonical_module.lf_slice(
                raw,
                start,
                end,
                policy="strict",
            )
    else:
        assert (
            canonical_module.lf_slice(
                raw,
                start,
                end,
                policy="strict",
            )
            == b"a\n"
        )


def test_prompt_resources_are_read_only_by_identity_freeze_owners() -> None:
    """The packet-plan owner freezes prompt resources into exact request bytes."""

    assert _sites("prompt_resource_read") == frozenset(
        {
            Site(
                "backstitch.analysis_packets",
                "_packet_contribution",
                "prompt_resource_read",
            )
        }
    )


@pytest.mark.parametrize(
    "source",
    (
        "from backstitch.semantic_packets import model_request_bytes\n"
        "def render(row):\n"
        "    return model_request_bytes(row, instruction_bytes=None)\n",
        "from backstitch.semantic_verification import verifier_request_bytes\n"
        "def render(request):\n"
        "    return verifier_request_bytes(request, prompt_bytes=None)\n",
    ),
    ids=("analyzer-none", "verifier-none"),
)
def test_prompt_inventory_rejects_explicit_none_authority(source: str) -> None:
    """A present keyword is not proof that prompt-resource fallback is disabled."""

    visitor = _Inventory("synthetic")
    visitor.visit(ast.parse(source))
    assert Site("synthetic", "render", "prompt_resource_read") in visitor.sites


@pytest.mark.parametrize("consumer", SLICE7_PROMPT_CONSUMERS)
def test_each_prompt_consumer_requires_explicit_frozen_bytes(consumer: Site) -> None:
    """Each reviewed read site fires independently, so partial migration stays red."""

    assert consumer not in _sites("prompt_resource_read")


def test_sha256_and_candidate_grammars_have_one_production_owner() -> None:
    """Tests-invariant: [INV.CANON.1]

    Slice-1 pin: regex and manual length/hex spellings share one owner.
    """

    sites = _sites("sha256_grammar")
    assert sites
    assert {item.module for item in sites} == {"backstitch.grammar"}


def test_issue_sort_key_has_one_production_owner() -> None:
    """Tests-invariant: [INV.CANON.1]"""

    assert _sites("issue_sort_key") == frozenset(
        {Site("backstitch.models", "issue_sort_key", "issue_sort_key")}
    )


def test_no_follow_read_and_stat_identity_have_one_owner_module() -> None:
    """Tests-invariant: [INV.CANON.1]

    The generic stable-read owner is a leaf. Snapshot keeps only its
    domain-specific whole-capture descriptor walk and retry policy.
    """

    assert {item.module for item in _sites("no_follow_read")} == {
        "backstitch.filesystem_io",
        "backstitch.repository_snapshot",
    }
    assert {item.module for item in _sites("stat_identity")} == {
        "backstitch.filesystem_io"
    }


def test_exclusion_matcher_has_one_production_owner() -> None:
    assert _sites("exclusion_matcher") == frozenset(
        {Site("backstitch.scan_exclusions", "is_excluded", "exclusion_matcher")}
    )


def test_line_arithmetic_uses_the_lf_only_owner() -> None:
    """Tests-invariant: [INV.LINE.1]

    Slice-1 pin for all splitlines, LF splits, and byte-10 arithmetic.

    Parser projections map back to LF-physical coordinates through the
    production owner; no Markdown splitlines exemption remains.
    """

    unexpected = {
        (item.module, item.owner, item.kind)
        for item in _production_sites()
        if item.kind in {"splitlines", "lf_split", "manual_lf_arithmetic"}
        and item.module != "backstitch.canonical"
    }
    assert not unexpected


def test_semantic_cache_uses_the_shared_six_field_stat_identity(tmp_path: Path) -> None:
    """NM2 reproduction: the cache currently omits dev, inode, and ctime."""

    path = tmp_path / "object.json"
    path.write_bytes(b"{}")
    observed = path.lstat()
    expected = file_stat_identity(observed)
    assert alignment_eval._authoritative_stat_identity(observed) == expected
    assert settings_module._config_stat_identity(observed) == expected
    assert semantic_cache._lstat_identity(observed) == expected


def test_diagnostic_registry_family_owns_deterministic_classification() -> None:
    """D7 pin: code prefixes must not classify diagnostic families."""

    registry = diagnostics.default_registry()
    families = {
        code: getattr(definition, "family", None)
        for code, definition in registry.definitions.items()
    }
    assert set(families.values()) == {"deterministic", "semantic"}
    assert {
        code
        for code, family in families.items()
        if family == "deterministic" and registry.require(code).status == "implemented"
    } == diagnostics.deterministic_issue_codes()


def test_scan_exclusion_matcher_normalizes_backslashes() -> None:
    """D9 characterization for the behavior missing from the snapshot twin."""

    assert scan_exclusions.is_excluded("src\\generated\\item.py", ("src/generated/**",))


def test_os_stat_fixture_exposes_all_shared_identity_fields(tmp_path: Path) -> None:
    """Guard the NM2 fixture itself against a platform-degenerate false positive."""

    path = tmp_path / "identity"
    path.write_text("identity", encoding="utf-8")
    observed = os.lstat(path)
    identity = file_stat_identity(observed)
    assert len(identity) == 6
    assert identity[0] == observed.st_dev
    assert identity[1] == observed.st_ino
