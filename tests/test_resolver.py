"""Resolver tests over the clean and broken fixture graphs.

Spec: docs/specs/02-backstitch-core.md [SC-4], [SC-9]
"""

from pathlib import Path

import pytest

from backstitch.models import Report
from backstitch.profiles import get_profile
from backstitch.resolver import ScanError, scan_repository

FIXTURES = Path(__file__).parent / "fixtures"

BROKEN_PROFILE = get_profile("backstitch-style-v1").with_overrides(
    spec_roots=("docs/specifications",),
    code_roots=("src", "tests"),
    planned_spec_globs=("docs/specifications/*A-*.md",),
)

CLEAN_PROFILE = get_profile("backstitch-style-v1").with_overrides(
    spec_roots=("docs/specs",),
    code_roots=("pkg",),
)


@pytest.fixture(scope="module")
def broken() -> Report:
    return scan_repository(FIXTURES / "traceability_project", BROKEN_PROFILE)


@pytest.fixture(scope="module")
def clean() -> Report:
    return scan_repository(FIXTURES / "clean_project", CLEAN_PROFILE)


def _codes(report: Report, severity: str | None = None) -> list[str]:
    return [
        i.code
        for i in report.issues
        if severity is None or i.severity == severity
    ]


def test_clean_graph_has_no_issues(clean: Report) -> None:
    assert clean.issues == ()


def test_clean_graph_builds_mapping_and_backlink_edges(clean: Report) -> None:
    kinds = {(e.kind, e.code_path, e.code_symbol) for e in clean.edges}
    assert ("mapping", "pkg/mod.py", None) in kinds
    assert ("mapping", "pkg/mod.py", "do_thing") in kinds
    assert ("backlink", "pkg/mod.py", "module") in kinds
    assert ("backlink", "pkg/mod.py", "do_thing") in kinds


def test_missing_mapping_path_is_error(broken: Report) -> None:
    issues = [i for i in broken.issues if i.code == "MAPPING_PATH_MISSING"]
    assert len(issues) == 1
    issue = issues[0]
    assert issue.severity == "error"
    assert issue.path == "docs/specifications/01-Core.md"
    assert issue.section_id == "CORE-2"
    assert "src/missing_module.py" in issue.message


def test_cross_prefix_range_is_unsupported_error(broken: Report) -> None:
    issues = [i for i in broken.issues if i.code == "REF_RANGE_UNSUPPORTED"]
    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert issues[0].path == "src/ranges.py"


def test_duplicate_section_ids_warn(broken: Report) -> None:
    issues = [i for i in broken.issues if i.code == "SPEC_SECTION_DUPLICATE"]
    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert issues[0].section_id == "DUP-1"


def test_ambiguous_bare_id_in_comment_is_warning(broken: Report) -> None:
    # [SC-11] context split: the fixture's ambiguous bare ref lives in a
    # comment, so it is prose -- a warning, not an error.
    issues = [i for i in broken.issues if i.code == "SPEC_SECTION_AMBIGUOUS"]
    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert issues[0].path == "src/ranges.py"
    assert issues[0].section_id == "DUP-1"


def test_ambiguous_bare_id_in_docstring_is_error(tmp_path: Path) -> None:
    # [SC-11] context split: a docstring backlink asserts a trace edge; an
    # ambiguous ID there means the claimed edge cannot be built -- error.
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "docs/specs/01-a.md").write_text(
        "# A\n\n## One [DUP-7]\n", encoding="utf-8"
    )
    (tmp_path / "docs/specs/02-b.md").write_text(
        "# B\n\n## Two [DUP-7]\n", encoding="utf-8"
    )
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg/mod.py").write_text(
        '"""Implements [DUP-7]."""\n', encoding="utf-8"
    )
    report = scan_repository(
        tmp_path,
        get_profile("backstitch-style-v1").with_overrides(
            spec_roots=("docs/specs",), plan_roots=(), code_roots=("pkg",)
        ),
    )
    issues = [i for i in report.issues if i.code == "SPEC_SECTION_AMBIGUOUS"]
    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert issues[0].path == "pkg/mod.py"


def test_backlink_to_unmapped_section_fires_reciprocal_warning(
    tmp_path: Path,
) -> None:
    # [SC-11] SPEC_MAPPING_RECIPROCAL_MISSING: code backlink to a section
    # that declares no implementation mapping at all.
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "docs/specs/01-a.md").write_text(
        "# A\n\n## One [RM-1]\n", encoding="utf-8"
    )
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg/mod.py").write_text(
        '"""Spec: docs/specs/01-a.md [RM-1]"""\n', encoding="utf-8"
    )
    report = scan_repository(
        tmp_path,
        get_profile("backstitch-style-v1").with_overrides(
            spec_roots=("docs/specs",), plan_roots=(), code_roots=("pkg",)
        ),
    )
    codes = {i.code: i for i in report.issues}
    reciprocal = codes["SPEC_MAPPING_RECIPROCAL_MISSING"]
    assert reciprocal.severity == "warning"
    assert reciprocal.path == "pkg/mod.py"
    assert reciprocal.section_id == "RM-1"


def test_planned_spec_ref_from_shipped_code_warns(broken: Report) -> None:
    issues = [i for i in broken.issues if i.code == "CODE_REF_PLANNED_SPEC"]
    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert issues[0].path == "src/runtime.py"
    assert issues[0].section_id == "CORE-P1"


def test_exploratory_glob_classification() -> None:
    profile = BROKEN_PROFILE.with_overrides(
        planned_spec_globs=(),
        exploratory_spec_globs=("docs/specifications/*A-*.md",),
    )
    report = scan_repository(FIXTURES / "traceability_project", profile)
    codes = [i.code for i in report.issues]
    assert "CODE_REF_EXPLORATORY_SPEC" in codes
    assert "CODE_REF_PLANNED_SPEC" not in codes


def test_broad_document_only_ref_warns(broken: Report) -> None:
    issues = [i for i in broken.issues if i.code == "CODE_REF_BROAD"]
    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert issues[0].path == "src/runtime.py"
    assert issues[0].symbol == "broad_reader"


def test_bare_symbol_mappings_warn(broken: Report) -> None:
    issues = [i for i in broken.issues if i.code == "MAPPING_SYMBOL_UNRESOLVED"]
    targets = {i.symbol for i in issues}
    assert "Runtime.save" in targets
    assert all(i.severity == "warning" for i in issues)


def test_path_symbol_missing_symbol_error(tmp_path: Path) -> None:
    spec_dir = tmp_path / "docs" / "specs"
    spec_dir.mkdir(parents=True)
    (spec_dir / "01-X.md").write_text(
        "# X\n\n## Thing [X-1]\n\n_Implementation mapping_:\n\n"
        "- `pkg/mod.py::nonexistent_symbol`\n",
        encoding="utf-8",
    )
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "mod.py").write_text(
        '"""Spec: docs/specs/01-X.md [X-1]"""\n', encoding="utf-8"
    )
    report = scan_repository(tmp_path, CLEAN_PROFILE)
    issues = [i for i in report.issues if i.code == "MAPPING_SYMBOL_MISSING"]
    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert issues[0].symbol == "nonexistent_symbol"


def test_reciprocal_backlink_missing_warns(broken: Report) -> None:
    issues = [
        i for i in broken.issues if i.code == "CODE_BACKLINK_RECIPROCAL_MISSING"
    ]
    sections = {i.section_id for i in issues}
    assert "LAYER-1" in sections
    assert "ROUTE-A1.1" in sections
    assert "CORE-1" not in sections
    assert "CORE-2" not in sections


def test_unmapped_sections_are_info(broken: Report) -> None:
    issues = [i for i in broken.issues if i.code == "SPEC_SECTION_UNMAPPED"]
    assert all(i.severity == "info" for i in issues)
    sections = {i.section_id for i in issues}
    assert "CORE-3" in sections
    assert "FENCE-1" in sections
    assert "CORE-1" not in sections


def test_backlink_outside_mapping_is_info(broken: Report) -> None:
    issues = [i for i in broken.issues if i.code == "CODE_REF_UNMAPPED_FROM_SPEC"]
    assert all(i.severity == "info" for i in issues)
    paths = {i.path for i in issues}
    assert "tests/test_runtime.py" in paths


def test_bare_range_expands_to_backlink_edges(broken: Report) -> None:
    edges = [
        e
        for e in broken.edges
        if e.kind == "backlink"
        and e.code_path == "src/ranges.py"
        and e.section_id in {"CORE.2.1", "CORE.2.2"}
    ]
    assert len(edges) == 6
    assert sorted((e.code_symbol, e.section_id) for e in edges) == [
        ("compact_range", "CORE.2.1"),
        ("compact_range", "CORE.2.2"),
        ("endash_range", "CORE.2.1"),
        ("endash_range", "CORE.2.2"),
        ("module", "CORE.2.1"),
        ("module", "CORE.2.2"),
    ]


def test_anchor_ref_resolves_to_id_section_edge(broken: Report) -> None:
    edges = [
        e
        for e in broken.edges
        if e.kind == "backlink" and e.code_symbol == "read_reference_docs"
    ]
    assert [e.section_id for e in edges] == ["CORE-2"]


def test_missing_anchor_is_error(tmp_path: Path) -> None:
    spec_dir = tmp_path / "docs" / "specs"
    spec_dir.mkdir(parents=True)
    (spec_dir / "01-X.md").write_text("# X\n\n## Thing [X-1]\n", encoding="utf-8")
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "mod.py").write_text(
        '"""Spec: docs/specs/01-X.md#no-such-anchor"""\n', encoding="utf-8"
    )
    report = scan_repository(tmp_path, CLEAN_PROFILE)
    codes = {i.code: i.severity for i in report.issues}
    assert codes.get("SPEC_ANCHOR_MISSING") == "error"


def test_missing_spec_file_and_section_are_errors(tmp_path: Path) -> None:
    spec_dir = tmp_path / "docs" / "specs"
    spec_dir.mkdir(parents=True)
    (spec_dir / "01-X.md").write_text("# X\n\n## Thing [X-1]\n", encoding="utf-8")
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "mod.py").write_text(
        '"""Refs.\n\nSpec: docs/specs/09-Gone.md [X-1]\n'
        "Spec: docs/specs/01-X.md [X-9]\n"
        '"""\n',
        encoding="utf-8",
    )
    report = scan_repository(tmp_path, CLEAN_PROFILE)
    codes = {i.code: i.severity for i in report.issues}
    assert codes.get("SPEC_FILE_MISSING") == "error"
    assert codes.get("SPEC_SECTION_MISSING") == "error"


def test_refs_to_md_outside_spec_roots_are_ignored(tmp_path: Path) -> None:
    spec_dir = tmp_path / "docs" / "specs"
    spec_dir.mkdir(parents=True)
    (spec_dir / "01-X.md").write_text("# X\n\n## Thing [X-1]\n", encoding="utf-8")
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "mod.py").write_text(
        '"""Spec: README.md and docs/plans/2026-01-01-x.md are not specs."""\n',
        encoding="utf-8",
    )
    report = scan_repository(tmp_path, CLEAN_PROFILE)
    assert "SPEC_FILE_MISSING" not in {i.code for i in report.issues}


def test_unknown_bare_ref_with_known_prefix_warns(broken: Report) -> None:
    issues = [i for i in broken.issues if i.code == "CODE_REF_BARE_UNRESOLVED"]
    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert issues[0].section_id == "CORE-99"


def test_unknown_prefix_bare_candidates_stay_silent(broken: Report) -> None:
    # `window[N-1]` parses as a candidate but prefix N is unknown to the
    # corpus, so it produces neither an issue nor an edge.
    assert not any(i.section_id == "N-1" for i in broken.issues)
    assert not any(e.section_id == "N-1" for e in broken.edges)


def test_prose_see_reference_resolves_to_edge(broken: Report) -> None:
    edges = [
        e
        for e in broken.edges
        if e.kind == "backlink" and e.code_symbol == "prose_reference"
    ]
    assert [e.section_id for e in edges] == ["CORE-3"]


def test_endash_range_expands(broken: Report) -> None:
    edges = [
        e
        for e in broken.edges
        if e.kind == "backlink" and e.code_symbol == "endash_range"
    ]
    assert {e.section_id for e in edges} == {"CORE.2.1", "CORE.2.2"}


def test_backwards_range_is_unsupported(tmp_path: Path) -> None:
    spec_dir = tmp_path / "docs" / "specs"
    spec_dir.mkdir(parents=True)
    (spec_dir / "01-X.md").write_text(
        "# X\n\n## A [X-1]\n\n## B [X-2]\n", encoding="utf-8"
    )
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "mod.py").write_text(
        '"""Spec: docs/specs/01-X.md [X-2]-[X-1]"""\n', encoding="utf-8"
    )
    report = scan_repository(tmp_path, CLEAN_PROFILE)
    issues = [i for i in report.issues if i.code == "REF_RANGE_UNSUPPORTED"]
    assert len(issues) == 1
    assert "backwards" in issues[0].message


def test_unreadable_file_is_error_finding_not_crash(tmp_path: Path) -> None:
    spec_dir = tmp_path / "docs" / "specs"
    spec_dir.mkdir(parents=True)
    (spec_dir / "01-X.md").write_text("# X\n\n## Thing [X-1]\n", encoding="utf-8")
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "mod.py").write_bytes(b"\xff\xfe invalid utf-8 \xff")
    report = scan_repository(tmp_path, CLEAN_PROFILE)
    issues = [i for i in report.issues if i.code == "FILE_UNREADABLE"]
    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert issues[0].path == "pkg/mod.py"


def test_directory_mapping_covers_contained_files(tmp_path: Path) -> None:
    spec_dir = tmp_path / "docs" / "specs"
    spec_dir.mkdir(parents=True)
    (spec_dir / "01-X.md").write_text(
        "# X\n\n## Thing [X-1]\n\n_Implementation mapping_:\n\n- `pkg/`\n",
        encoding="utf-8",
    )
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "mod.py").write_text(
        '"""Spec: docs/specs/01-X.md [X-1]"""\n', encoding="utf-8"
    )
    report = scan_repository(tmp_path, CLEAN_PROFILE)
    assert "CODE_REF_UNMAPPED_FROM_SPEC" not in {i.code for i in report.issues}


def test_ownerless_mapping_block_warns(tmp_path: Path) -> None:
    spec_dir = tmp_path / "docs" / "specs"
    spec_dir.mkdir(parents=True)
    (spec_dir / "01-X.md").write_text(
        "# X\n\n## Thing [X-1]\n\n## Open Questions\n\n"
        "_Implementation mapping_:\n\n- `pkg/mod.py`\n",
        encoding="utf-8",
    )
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text(
        '"""Spec: docs/specs/01-X.md [X-1]"""\n', encoding="utf-8"
    )
    report = scan_repository(tmp_path, CLEAN_PROFILE)
    codes = {i.code for i in report.issues}
    assert "MAPPING_BLOCK_OWNERLESS" in codes
    # The block under the ID-less heading must NOT attach to X-1.
    assert not any(
        m.section_id == "X-1" for m in report.spec_mappings
    ), "ownerless mapping block leaked to the previous section"


def test_missing_scan_root_is_error(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    report = scan_repository(tmp_path, CLEAN_PROFILE)
    issues = [i for i in report.issues if i.code == "SCAN_ROOT_MISSING"]
    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert "docs/specs" in issues[0].message


def test_unreadable_repo_root_raises_scan_error(tmp_path: Path) -> None:
    with pytest.raises(ScanError):
        scan_repository(tmp_path / "does-not-exist", CLEAN_PROFILE)


def test_python_syntax_error_surfaces_in_report(tmp_path: Path) -> None:
    spec_dir = tmp_path / "docs" / "specs"
    spec_dir.mkdir(parents=True)
    (spec_dir / "01-X.md").write_text("# X\n\n## Thing [X-1]\n", encoding="utf-8")
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "mod.py").write_text("def broken(:\n", encoding="utf-8")
    report = scan_repository(tmp_path, CLEAN_PROFILE)
    codes = {i.code: i.severity for i in report.issues}
    assert codes.get("PYTHON_SYNTAX_ERROR") == "error"


def test_report_is_stable_across_runs(broken: Report) -> None:
    again = scan_repository(FIXTURES / "traceability_project", BROKEN_PROFILE)
    assert again.to_dict() == broken.to_dict()
