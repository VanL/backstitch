"""Declared-evidence summaries consume only the accepted snapshot."""

from __future__ import annotations

import hashlib
from typing import TypedDict, cast

import pytest

from backstitch.config import ProfileConfig
from backstitch.evidence_summary import (
    build_evidence_summary_items as _build_evidence_summary_items,
)
from backstitch.models import (
    Edge,
    InvariantBind,
    InvariantDeclaration,
    Report,
    SpecMapping,
    SpecSection,
)
from backstitch.obligation_api import evidence_summary_envelope
from backstitch.obligation_runtime import (
    atomic_code_invariant_ids,
    atomic_invariant_targets,
)
from backstitch.obligations import (
    ObligationInventory,
    ObligationRecord,
    SnapshotIdentity,
    build_obligation_inventory,
)
from backstitch.repository_snapshot import (
    FileStat,
    RepositorySnapshot,
    SnapshotFile,
    SnapshotPath,
)

PROFILE = ProfileConfig(
    name="test",
    spec_roots=("docs/specs",),
    plan_roots=("docs/plans",),
    code_roots=("pkg", "tests"),
    test_roots=("tests",),
    planned_spec_globs=(),
    exploratory_spec_globs=(),
)
STAT = FileStat(1, 1, 0o100644, 0, 1, 1)


class _Receipt(TypedDict):
    receipt_version: int
    path: str
    structural_locator: str
    start_line: int
    end_line: int
    raw_sha256: str


class _EvidenceDeclaration(TypedDict):
    relation_kind: str
    receipt: _Receipt


class _EvidenceItem(TypedDict):
    role: str
    relation_kinds: list[str]
    reciprocity_state: str
    path: str
    symbol: str | None
    owner: str | None
    declared_target: str | None
    start_line: int
    end_line: int
    excerpt: str
    receipt: _Receipt
    declarations: list[_EvidenceDeclaration]


def build_evidence_summary_items(
    report: Report,
    obligation: ObligationRecord,
    snapshot: RepositorySnapshot,
    profile: ProfileConfig,
) -> tuple[_EvidenceItem, ...]:
    """Give the closed public row shape a precise type for test assertions."""

    return cast(
        tuple[_EvidenceItem, ...],
        _build_evidence_summary_items(report, obligation, snapshot, profile),
    )


def _snapshot(files: dict[str, bytes]) -> RepositorySnapshot:
    rows = tuple(
        SnapshotFile(
            path=path,
            state="readable",
            raw_bytes=raw,
            raw_sha256=hashlib.sha256(raw).hexdigest(),
            error_class=None,
            file_stat=STAT,
        )
        for path, raw in sorted(files.items())
    )
    catalog = {
        SnapshotPath(".", "directory"),
        SnapshotPath("docs", "directory"),
        SnapshotPath("docs/specs", "directory"),
        SnapshotPath("pkg", "directory"),
        SnapshotPath("tests", "directory"),
        *(SnapshotPath(path, "regular_file") for path in files),
    }
    return RepositorySnapshot(
        config_inputs=(),
        files=rows,
        path_catalog=tuple(sorted(catalog, key=lambda item: item.path)),
        missing_roots=("docs/plans",),
        catalog_sha256="catalog",
        snapshot_hash="snapshot",
        _identity_bytes=b"{}",
    )


def _report(*, mappings: tuple[SpecMapping, ...], edges: tuple[Edge, ...]) -> Report:
    return Report(
        profile="test",
        repo_root="/not-addressed",
        spec_sections=(
            SpecSection(
                "docs/specs/x.md", "X-1", "Contract", 3, "contract-x-1", "heading"
            ),
        ),
        code_refs=(),
        spec_mappings=mappings,
        edges=edges,
        issues=(),
    )


def _obligation(report: Report) -> ObligationRecord:
    inventory = build_obligation_inventory(
        report,
        profile=PROFILE,
        snapshot=SnapshotIdentity("snapshot", 2, 100, 0),
        source_end_lines={"docs/specs/x.md#X-1": 5},
    )
    obligation = inventory.get("docs/specs/x.md#X-1")
    assert obligation is not None
    return obligation


def test_complete_relation_has_one_code_owned_receipt() -> None:
    spec = b"# X\n\n## Contract [X-1]\n\n- `pkg/x.py::run`\n"
    code = b"def run() -> int:\n    return 1\n"
    snapshot = _snapshot({"docs/specs/x.md": spec, "pkg/x.py": code})
    mapping = SpecMapping(
        "docs/specs/x.md", "X-1", 5, "pkg/x.py::run", "path_symbol", "pkg/x.py", "run"
    )
    report = _report(
        mappings=(mapping,),
        edges=(
            Edge("mapping", "docs/specs/x.md", "X-1", "pkg/x.py", "run", 5),
            Edge("backlink", "docs/specs/x.md", "X-1", "pkg/x.py", "run", 1),
        ),
    )

    rows = build_evidence_summary_items(report, _obligation(report), snapshot, PROFILE)

    assert len(rows) == 1
    assert rows[0]["relation_kinds"] == ["spec_mapping", "code_backlink"]
    assert rows[0]["reciprocity_state"] == "complete"
    assert rows[0]["excerpt"] == code.decode()
    assert [
        declaration["receipt"]["structural_locator"]
        for declaration in rows[0]["declarations"]
    ] == [
        "source-declaration:spec_mapping:5:0",
        "source-declaration:code_backlink:1:0",
    ]


def test_async_definition_receipt_uses_the_closed_async_locator_kind() -> None:
    spec = b"# X\n\n## Contract [X-1]\n\n- `pkg/x.py::run`\n"
    code = b"async def run() -> int:\n    return 1\n"
    snapshot = _snapshot({"docs/specs/x.md": spec, "pkg/x.py": code})
    mapping = SpecMapping(
        "docs/specs/x.md", "X-1", 5, "pkg/x.py::run", "path_symbol", "pkg/x.py", "run"
    )
    report = _report(
        mappings=(mapping,),
        edges=(
            Edge("mapping", "docs/specs/x.md", "X-1", "pkg/x.py", "run", 5),
            Edge("backlink", "docs/specs/x.md", "X-1", "pkg/x.py", "run", 1),
        ),
    )

    [row] = build_evidence_summary_items(report, _obligation(report), snapshot, PROFILE)

    assert row["receipt"]["structural_locator"] == (
        "python-definition:run:async-function:0"
    )


def test_comment_backlink_before_decorator_has_its_own_declaration_receipt() -> None:
    spec = b"# X\n\n## Contract [X-1]\n\n- `pkg/x.py::run`\n"
    code = (
        b"# Spec: docs/specs/x.md [X-1]\n@decorator\ndef run() -> int:\n    return 1\n"
    )
    snapshot = _snapshot({"docs/specs/x.md": spec, "pkg/x.py": code})
    mapping = SpecMapping(
        "docs/specs/x.md", "X-1", 5, "pkg/x.py::run", "path_symbol", "pkg/x.py", "run"
    )
    report = _report(
        mappings=(mapping,),
        edges=(
            Edge("mapping", "docs/specs/x.md", "X-1", "pkg/x.py", "run", 5),
            Edge("backlink", "docs/specs/x.md", "X-1", "pkg/x.py", "run", 1),
        ),
    )

    [row] = build_evidence_summary_items(report, _obligation(report), snapshot, PROFILE)

    assert (row["start_line"], row["end_line"]) == (2, 4)
    assert row["excerpt"].startswith("@decorator")
    backlink = next(
        item for item in row["declarations"] if item["relation_kind"] == "code_backlink"
    )
    assert backlink["receipt"]["start_line"] == 1
    assert backlink["receipt"]["end_line"] == 1


def test_unicode_owner_summary_normalizes_public_symbol_and_locator() -> None:
    nfd_symbol = "cafe\u0301"
    nfc_symbol = "caf\u00e9"
    spec = f"# X\n\n## Contract [X-1]\n\n- `pkg/x.py::{nfd_symbol}`\n".encode()
    code = (
        f"def {nfd_symbol}() -> int:\n"
        '    """Spec: docs/specs/x.md [X-1]"""\n'
        "    return 1\n"
    ).encode()
    snapshot = _snapshot({"docs/specs/x.md": spec, "pkg/x.py": code})
    mapping = SpecMapping(
        "docs/specs/x.md",
        "X-1",
        5,
        f"pkg/x.py::{nfd_symbol}",
        "path_symbol",
        "pkg/x.py",
        nfd_symbol,
    )
    report = _report(
        mappings=(mapping,),
        edges=(
            Edge("mapping", "docs/specs/x.md", "X-1", "pkg/x.py", nfd_symbol, 5),
            Edge("backlink", "docs/specs/x.md", "X-1", "pkg/x.py", nfd_symbol, 2),
        ),
    )

    [row] = build_evidence_summary_items(report, _obligation(report), snapshot, PROFILE)

    assert row["symbol"] == nfc_symbol
    assert row["owner"] == nfc_symbol
    assert row["receipt"]["structural_locator"] == (
        f"python-definition:{nfc_symbol}:function:0"
    )


def test_missing_mapping_target_retains_the_exact_declaration_receipt() -> None:
    spec = b"# X\n\n## Contract [X-1]\n\n- `pkg/missing.py::run`\n"
    snapshot = _snapshot({"docs/specs/x.md": spec})
    mapping = SpecMapping(
        "docs/specs/x.md",
        "X-1",
        5,
        "pkg/missing.py::run",
        "path_symbol",
        "pkg/missing.py",
        "run",
    )
    report = _report(mappings=(mapping,), edges=())

    rows = build_evidence_summary_items(report, _obligation(report), snapshot, PROFILE)

    assert len(rows) == 1
    assert rows[0]["path"] == "docs/specs/x.md"
    assert rows[0]["owner"] == "X-1"
    assert rows[0]["declared_target"] == "pkg/missing.py::run"
    assert rows[0]["reciprocity_state"] == "one_sided"
    assert rows[0]["receipt"] == {
        "receipt_version": 1,
        "path": "docs/specs/x.md",
        "structural_locator": "source-declaration:spec_mapping:5:0",
        "start_line": 5,
        "end_line": 5,
        "raw_sha256": hashlib.sha256(b"- `pkg/missing.py::run`\n").hexdigest(),
    }


@pytest.mark.parametrize(
    ("target", "extra_files"),
    (
        ("pkg", {}),
        ("pkg/config.json", {"pkg/config.json": b"{}\n"}),
        ("pkg/broken.py", {"pkg/broken.py": b"def broken(:\n"}),
        ("pkg/binary.py", {"pkg/binary.py": b"# \xff\npass\n"}),
    ),
)
def test_section_non_atomic_mapping_uses_honest_declaration_coordinates(
    target: str,
    extra_files: dict[str, bytes],
) -> None:
    spec = f"# X\n\n## Contract [X-1]\n\n- `{target}`\n".encode()
    snapshot = _snapshot({"docs/specs/x.md": spec, **extra_files})
    mapping = SpecMapping("docs/specs/x.md", "X-1", 5, target, "path", target, None)
    report = _report(
        mappings=(mapping,),
        edges=(Edge("mapping", "docs/specs/x.md", "X-1", target, None, 5),),
    )

    [row] = build_evidence_summary_items(report, _obligation(report), snapshot, PROFILE)

    assert row["path"] == "docs/specs/x.md"
    assert row["declared_target"] == target
    assert row["reciprocity_state"] == "one_sided"
    assert row["path"] == row["receipt"]["path"]
    assert row["start_line"] == row["receipt"]["start_line"]
    assert row["end_line"] == row["receipt"]["end_line"]
    assert row["receipt"]["structural_locator"].startswith(
        "source-declaration:spec_mapping:"
    )


def test_exact_file_receipt_is_independent_of_ambiguous_import_roots() -> None:
    profile = ProfileConfig(
        name="overlap",
        spec_roots=("docs/specs",),
        plan_roots=(),
        code_roots=("src",),
        test_roots=("src/tests",),
        planned_spec_globs=(),
        exploratory_spec_globs=(),
    )
    spec = b"# X\n\n## Contract [X-1]\n\n- `src/tests/test_x.py`\n"
    code = b"VALUE = 1\n"
    snapshot = _snapshot({"docs/specs/x.md": spec, "src/tests/test_x.py": code})
    mapping = SpecMapping(
        "docs/specs/x.md",
        "X-1",
        5,
        "src/tests/test_x.py",
        "path",
        "src/tests/test_x.py",
        None,
    )
    report = _report(
        mappings=(mapping,),
        edges=(
            Edge(
                "mapping",
                "docs/specs/x.md",
                "X-1",
                "src/tests/test_x.py",
                None,
                5,
            ),
        ),
    )

    [row] = build_evidence_summary_items(report, _obligation(report), snapshot, profile)

    assert row["path"] == "src/tests/test_x.py"
    assert row["declared_target"] == "src/tests/test_x.py"
    assert row["receipt"]["structural_locator"] == (
        "python-file:" + hashlib.sha256(b"src/tests/test_x.py").hexdigest()
    )


def test_spec_declared_invariant_summarizes_mapped_target_and_binding_test() -> None:
    spec = (
        b"# X\n\n## Contract [X-1]\n\nInvariant: [INV.X.1] The value remains stable.\n"
    )
    code = b"def run() -> int:\n    return 1\n"
    test = b"def test_run() -> None:\n    assert True\n"
    snapshot = _snapshot(
        {
            "docs/specs/x.md": spec,
            "pkg/x.py": code,
            "tests/test_x.py": test,
        }
    )
    declaration = InvariantDeclaration(
        "INV.X.1",
        "The value remains stable.",
        "required",
        "spec",
        "docs/specs/x.md",
        5,
        None,
        "X-1",
    )
    bind = InvariantBind("INV.X.1", "tests/test_x.py", "test_run", 1, 1, 2)
    report = Report(
        profile="test",
        repo_root="/not-addressed",
        spec_sections=(
            SpecSection(
                "docs/specs/x.md", "X-1", "Contract", 3, "contract-x-1", "heading"
            ),
        ),
        code_refs=(),
        spec_mappings=(),
        edges=(Edge("mapping", "docs/specs/x.md", "X-1", "pkg/x.py", "run", 3),),
        issues=(),
        invariants=(declaration,),
        binds=(bind,),
    )
    inventory = build_obligation_inventory(
        report,
        profile=PROFILE,
        snapshot=SnapshotIdentity("snapshot", 3, 100, 0),
    )
    obligation = inventory.get("invariant::INV.X.1")
    assert obligation is not None

    rows = build_evidence_summary_items(report, obligation, snapshot, PROFILE)

    assert [(row["role"], row["relation_kinds"]) for row in rows] == [
        ("implementation", ["invariant_bind"]),
        ("binding_test", ["binding_test"]),
    ]
    assert {row["reciprocity_state"] for row in rows} == {"complete"}


def test_spec_invariant_summary_retains_unresolved_mapping_declaration() -> None:
    spec = (
        b"# X\n\n## Contract [X-1]\n\n"
        b"Invariant: [INV.X.1] The value remains stable.\n\n"
        b"- `pkg/missing.py::run`\n"
    )
    test = b"def test_run() -> None:\n    assert True\n"
    snapshot = _snapshot({"docs/specs/x.md": spec, "tests/test_x.py": test})
    declaration = InvariantDeclaration(
        "INV.X.1",
        "The value remains stable.",
        "required",
        "spec",
        "docs/specs/x.md",
        5,
        None,
        "X-1",
    )
    mapping = SpecMapping(
        "docs/specs/x.md",
        "X-1",
        7,
        "pkg/missing.py::run",
        "path_symbol",
        "pkg/missing.py",
        "run",
    )
    bind = InvariantBind("INV.X.1", "tests/test_x.py", "test_run", 1, 1, 2)
    report = Report(
        profile="test",
        repo_root="/not-addressed",
        spec_sections=(
            SpecSection(
                "docs/specs/x.md", "X-1", "Contract", 3, "contract-x-1", "heading"
            ),
        ),
        code_refs=(),
        spec_mappings=(mapping,),
        edges=(),
        issues=(),
        invariants=(declaration,),
        binds=(bind,),
    )
    inventory = build_obligation_inventory(
        report,
        profile=PROFILE,
        snapshot=SnapshotIdentity("snapshot", 2, 100, 0),
    )
    obligation = inventory.get("invariant::INV.X.1")
    assert obligation is not None

    rows = build_evidence_summary_items(report, obligation, snapshot, PROFILE)

    assert [(row["role"], row["path"]) for row in rows] == [
        ("implementation", "docs/specs/x.md"),
        ("binding_test", "tests/test_x.py"),
    ]
    assert rows[0]["relation_kinds"] == ["invariant_bind"]
    assert rows[0]["reciprocity_state"] == "one_sided"
    assert rows[0]["receipt"]["path"] == "docs/specs/x.md"
    assert rows[0]["declared_target"] == "pkg/missing.py::run"


def test_spec_invariant_summary_keeps_resolved_test_target_as_test_evidence() -> None:
    spec = (
        b"# X\n\n## Contract [X-1]\n\n"
        b"Invariant: [INV.X.1] The value remains stable.\n\n"
        b"- `tests/implementation.py::run`\n"
    )
    implementation = b"def run() -> int:\n    return 1\n"
    binding = b"def test_run() -> None:\n    assert True\n"
    snapshot = _snapshot(
        {
            "docs/specs/x.md": spec,
            "tests/implementation.py": implementation,
            "tests/test_x.py": binding,
        }
    )
    declaration = InvariantDeclaration(
        "INV.X.1",
        "The value remains stable.",
        "required",
        "spec",
        "docs/specs/x.md",
        5,
        None,
        "X-1",
    )
    mapping = SpecMapping(
        "docs/specs/x.md",
        "X-1",
        7,
        "tests/implementation.py::run",
        "path_symbol",
        "tests/implementation.py",
        "run",
    )
    bind = InvariantBind("INV.X.1", "tests/test_x.py", "test_run", 1, 1, 2)
    report = Report(
        profile="test",
        repo_root="/not-addressed",
        spec_sections=(
            SpecSection(
                "docs/specs/x.md", "X-1", "Contract", 3, "contract-x-1", "heading"
            ),
        ),
        code_refs=(),
        spec_mappings=(mapping,),
        edges=(
            Edge(
                "mapping",
                "docs/specs/x.md",
                "X-1",
                "tests/implementation.py",
                "run",
                7,
            ),
        ),
        issues=(),
        invariants=(declaration,),
        binds=(bind,),
    )
    inventory = build_obligation_inventory(
        report,
        profile=PROFILE,
        snapshot=SnapshotIdentity("snapshot", 3, 100, 0),
    )
    obligation = inventory.get("invariant::INV.X.1")
    assert obligation is not None

    rows = build_evidence_summary_items(report, obligation, snapshot, PROFILE)

    test_evidence = next(row for row in rows if row["role"] == "test")
    assert test_evidence["path"] == "tests/implementation.py"
    assert test_evidence["declared_target"] == "tests/implementation.py::run"
    assert test_evidence["reciprocity_state"] == "complete"
    assert test_evidence["receipt"]["path"] == "tests/implementation.py"


@pytest.mark.parametrize(
    ("target", "target_path", "extra_files"),
    (
        ("pkg", "pkg", {}),
        ("pkg/config.json", "pkg/config.json", {"pkg/config.json": b"{}\n"}),
        ("pkg/broken.py", "pkg/broken.py", {"pkg/broken.py": b"def broken(:\n"}),
    ),
)
def test_spec_invariant_summary_falls_back_for_non_atomic_resolved_targets(
    target: str,
    target_path: str,
    extra_files: dict[str, bytes],
) -> None:
    spec = (
        b"# X\n\n## Contract [X-1]\n\n"
        b"Invariant: [INV.X.1] The value remains stable.\n\n"
        + f"- `{target}`\n".encode()
    )
    binding = b"def test_run() -> None:\n    assert True\n"
    snapshot = _snapshot(
        {
            "docs/specs/x.md": spec,
            "tests/test_x.py": binding,
            **extra_files,
        }
    )
    declaration = InvariantDeclaration(
        "INV.X.1",
        "The value remains stable.",
        "required",
        "spec",
        "docs/specs/x.md",
        5,
        None,
        "X-1",
    )
    mapping = SpecMapping(
        "docs/specs/x.md",
        "X-1",
        7,
        target,
        "path",
        target_path,
        None,
    )
    bind = InvariantBind("INV.X.1", "tests/test_x.py", "test_run", 1, 1, 2)
    report = Report(
        profile="test",
        repo_root="/not-addressed",
        spec_sections=(
            SpecSection(
                "docs/specs/x.md", "X-1", "Contract", 3, "contract-x-1", "heading"
            ),
        ),
        code_refs=(),
        spec_mappings=(mapping,),
        edges=(
            Edge(
                "mapping",
                "docs/specs/x.md",
                "X-1",
                target_path,
                None,
                7,
            ),
        ),
        issues=(),
        invariants=(declaration,),
        binds=(bind,),
    )
    inventory = build_obligation_inventory(
        report,
        profile=PROFILE,
        snapshot=SnapshotIdentity("snapshot", 2 + len(extra_files), 100, 0),
    )
    obligation = inventory.get("invariant::INV.X.1")
    assert obligation is not None

    rows = build_evidence_summary_items(report, obligation, snapshot, PROFILE)

    implementation = next(row for row in rows if row["role"] == "implementation")
    assert implementation["path"] == "docs/specs/x.md"
    assert implementation["declared_target"] == target
    assert implementation["reciprocity_state"] == "one_sided"
    assert implementation["receipt"]["path"] == "docs/specs/x.md"
    assert implementation["path"] == implementation["receipt"]["path"]
    assert implementation["start_line"] == implementation["receipt"]["start_line"]
    assert implementation["end_line"] == implementation["receipt"]["end_line"]


def test_identical_projected_evidence_rows_are_deduplicated_for_pagination() -> None:
    spec = b"# X\n\n## Contract [X-1]\n\n- `pkg/x.py::run`\n"
    code = b"def run() -> int:\n    return 1\n"
    snapshot = _snapshot({"docs/specs/x.md": spec, "pkg/x.py": code})
    mapping = SpecMapping(
        "docs/specs/x.md", "X-1", 5, "pkg/x.py::run", "path_symbol", "pkg/x.py", "run"
    )
    duplicate = Edge("mapping", "docs/specs/x.md", "X-1", "pkg/x.py", "run", 5)
    report = _report(mappings=(mapping,), edges=(duplicate, duplicate))

    rows = build_evidence_summary_items(report, _obligation(report), snapshot, PROFILE)

    assert len(rows) == 1


def test_same_line_broken_mapping_targets_remain_distinct() -> None:
    spec = (
        b"# X\n\n## Contract [X-1]\n\n"
        b"- `pkg/missing-a.py::run` and `pkg/missing-b.py::run`\n"
    )
    snapshot = _snapshot({"docs/specs/x.md": spec})
    first = SpecMapping(
        "docs/specs/x.md",
        "X-1",
        5,
        "pkg/missing-a.py::run",
        "path_symbol",
        "pkg/missing-a.py",
        "run",
    )
    second = SpecMapping(
        "docs/specs/x.md",
        "X-1",
        5,
        "pkg/missing-b.py::run",
        "path_symbol",
        "pkg/missing-b.py",
        "run",
    )
    report = _report(
        mappings=(first, second),
        edges=(
            Edge(
                "mapping",
                "docs/specs/x.md",
                "X-1",
                "pkg/missing-a.py",
                "run",
                5,
            ),
            Edge(
                "mapping",
                "docs/specs/x.md",
                "X-1",
                "pkg/missing-b.py",
                "run",
                5,
            ),
        ),
    )

    rows = build_evidence_summary_items(report, _obligation(report), snapshot, PROFILE)

    assert [row["declared_target"] for row in rows] == [
        "pkg/missing-a.py::run",
        "pkg/missing-b.py::run",
    ]
    assert all(row["path"] == row["receipt"]["path"] for row in rows)


def test_same_line_exact_and_suffix_mappings_keep_distinct_declarations() -> None:
    spec = b"# X\n\n## Contract [X-1]\n\n- `pkg/x.py::run` and `x.py::run`\n"
    code = b"def run() -> int:\n    return 1\n"
    snapshot = _snapshot({"docs/specs/x.md": spec, "pkg/x.py": code})
    exact = SpecMapping(
        "docs/specs/x.md",
        "X-1",
        5,
        "pkg/x.py::run",
        "path_symbol",
        "pkg/x.py",
        "run",
    )
    suffix = SpecMapping(
        "docs/specs/x.md",
        "X-1",
        5,
        "x.py::run",
        "path_symbol",
        "x.py",
        "run",
    )
    edge = Edge("mapping", "docs/specs/x.md", "X-1", "pkg/x.py", "run", 5)
    report = _report(mappings=(exact, suffix), edges=(edge, edge))

    rows = build_evidence_summary_items(report, _obligation(report), snapshot, PROFILE)

    assert [row["declared_target"] for row in rows] == [
        "pkg/x.py::run",
        "x.py::run",
    ]
    assert all(row["path"] == "pkg/x.py" for row in rows)
    assert [
        row["declarations"][0]["receipt"]["structural_locator"] for row in rows
    ] == [
        "source-declaration:spec_mapping:5:0",
        "source-declaration:spec_mapping:5:1",
    ]


def test_duplicate_same_line_mappings_are_consumed_in_source_order() -> None:
    spec = b"# X\n\n## Contract [X-1]\n\n- `pkg/x.py::run` and `pkg/x.py::run`\n"
    code = b'def run() -> int:\n    """Spec: docs/specs/x.md [X-1]"""\n    return 1\n'
    snapshot = _snapshot({"docs/specs/x.md": spec, "pkg/x.py": code})
    first = SpecMapping(
        "docs/specs/x.md", "X-1", 5, "pkg/x.py::run", "path_symbol", "pkg/x.py", "run"
    )
    second = SpecMapping(
        "docs/specs/x.md", "X-1", 5, "pkg/x.py::run", "path_symbol", "pkg/x.py", "run"
    )
    edge = Edge("mapping", "docs/specs/x.md", "X-1", "pkg/x.py", "run", 5)
    report = _report(
        mappings=(first, second),
        edges=(
            edge,
            edge,
            Edge("backlink", "docs/specs/x.md", "X-1", "pkg/x.py", "run", 2),
        ),
    )

    rows = build_evidence_summary_items(report, _obligation(report), snapshot, PROFILE)

    assert len(rows) == 1
    assert rows[0]["reciprocity_state"] == "complete"
    assert [
        declaration["receipt"]["structural_locator"]
        for declaration in rows[0]["declarations"]
    ] == [
        "source-declaration:spec_mapping:5:0",
        "source-declaration:spec_mapping:5:1",
        "source-declaration:code_backlink:2:0",
    ]


def test_duplicate_same_line_unresolved_mappings_deduplicate_without_crashing() -> None:
    """Reproduce the reviewed duplicate-token AssertionError exactly.

    One mapping line contains the same unresolved target twice:
    `missing.py::run` and `missing.py::run`. Because the target file is absent,
    neither declaration resolves to an edge. Both rows therefore share the
    public evidence ordering tuple but carry declaration ordinals 0 and 1.
    The current merge treats that as an impossible alias and raises
    `AssertionError("evidence order aliases distinct evidence atoms")`.
    The corrected boundary emits one deterministic one-sided evidence row and
    retains both source-declaration receipts in source order.
    """

    spec = b"# X\n\n## Contract [X-1]\n\n- `missing.py::run` and `missing.py::run`\n"
    snapshot = _snapshot({"docs/specs/x.md": spec})
    first = SpecMapping(
        "docs/specs/x.md",
        "X-1",
        5,
        "missing.py::run",
        "path_symbol",
        "missing.py",
        "run",
    )
    second = SpecMapping(
        "docs/specs/x.md",
        "X-1",
        5,
        "missing.py::run",
        "path_symbol",
        "missing.py",
        "run",
    )
    report = _report(mappings=(first, second), edges=())

    rows = build_evidence_summary_items(report, _obligation(report), snapshot, PROFILE)

    assert len(rows) == 1
    assert rows[0]["reciprocity_state"] == "one_sided"
    assert rows[0]["declared_target"] == "missing.py::run"
    assert [
        declaration["receipt"]["structural_locator"]
        for declaration in rows[0]["declarations"]
    ] == [
        "source-declaration:spec_mapping:5:0",
        "source-declaration:spec_mapping:5:1",
    ]


def test_two_backlinks_in_one_owner_merge_without_losing_declarations() -> None:
    spec = b"# X\n\n## Contract [X-1]\n\n- `pkg/x.py::run`\n"
    code = (
        b"def run() -> int:\n"
        b'    """Spec: docs/specs/x.md [X-1]\n'
        b"    Spec: docs/specs/x.md [X-1]\n"
        b'    """\n'
        b"    return 1\n"
    )
    snapshot = _snapshot({"docs/specs/x.md": spec, "pkg/x.py": code})
    mapping = SpecMapping(
        "docs/specs/x.md", "X-1", 5, "pkg/x.py::run", "path_symbol", "pkg/x.py", "run"
    )
    report = _report(
        mappings=(mapping,),
        edges=(
            Edge("mapping", "docs/specs/x.md", "X-1", "pkg/x.py", "run", 5),
            Edge("backlink", "docs/specs/x.md", "X-1", "pkg/x.py", "run", 2),
            Edge("backlink", "docs/specs/x.md", "X-1", "pkg/x.py", "run", 3),
        ),
    )

    obligation = _obligation(report)
    rows = build_evidence_summary_items(report, obligation, snapshot, PROFILE)

    assert len(rows) == 1
    assert [
        declaration["receipt"]["structural_locator"]
        for declaration in rows[0]["declarations"]
    ] == [
        "source-declaration:spec_mapping:5:0",
        "source-declaration:code_backlink:2:0",
        "source-declaration:code_backlink:3:0",
    ]
    inventory = ObligationInventory(
        snapshot=SnapshotIdentity("snapshot", 2, 100, 0),
        obligations=(obligation,),
        unaddressable_intent=(),
        next_actions=("RUN_DETERMINISTIC_CHECK",),
    )
    page = evidence_summary_envelope(
        inventory,
        obligation,
        cast(tuple[dict[str, object], ...], rows),
        limit=1,
        cursor=None,
    )
    assert page["result"]["next_cursor"] is None
    assert len(page["result"]["items"][0]["declarations"]) == 3


def test_directory_mapping_and_child_backlink_share_one_complete_row() -> None:
    spec = b"# X\n\n## Contract [X-1]\n\n- `pkg/`\n"
    code = b'def run() -> int:\n    """Spec: docs/specs/x.md [X-1]"""\n    return 1\n'
    snapshot = _snapshot({"docs/specs/x.md": spec, "pkg/x.py": code})
    mapping = SpecMapping("docs/specs/x.md", "X-1", 5, "pkg/", "path", "pkg/", None)
    report = _report(
        mappings=(mapping,),
        edges=(
            Edge("mapping", "docs/specs/x.md", "X-1", "pkg/", None, 5),
            Edge("backlink", "docs/specs/x.md", "X-1", "pkg/x.py", "run", 2),
        ),
    )

    rows = build_evidence_summary_items(report, _obligation(report), snapshot, PROFILE)

    assert len(rows) == 1
    assert rows[0]["reciprocity_state"] == "complete"
    assert [
        declaration["relation_kind"] for declaration in rows[0]["declarations"]
    ] == ["spec_mapping", "code_backlink"]


def test_spec_invariant_nfc_collision_is_not_executable_or_code_owned() -> None:
    nfd_symbol = "cafe\u0301"
    nfc_symbol = "caf\u00e9"
    spec = (
        "# X\n\n## Contract [X-1]\n\n"
        "Invariant: [INV.X.1] Stable.\n\n"
        f"- `pkg/x.py::{nfc_symbol}`\n"
    ).encode()
    code = (
        f"def {nfd_symbol}() -> int:\n    return 1\n\n"
        f"def {nfc_symbol}() -> int:\n    return 2\n"
    ).encode()
    tests = (
        b"def test_run() -> None:\n"
        b'    """Tests-invariant: [INV.X.1]"""\n'
        b"    assert True\n"
    )
    snapshot = _snapshot(
        {
            "docs/specs/x.md": spec,
            "pkg/x.py": code,
            "tests/test_x.py": tests,
        }
    )
    declaration = InvariantDeclaration(
        "INV.X.1", "Stable.", "required", "spec", "docs/specs/x.md", 5, None, "X-1"
    )
    mapping = SpecMapping(
        "docs/specs/x.md",
        "X-1",
        7,
        f"pkg/x.py::{nfc_symbol}",
        "path_symbol",
        "pkg/x.py",
        nfc_symbol,
    )
    bind = InvariantBind("INV.X.1", "tests/test_x.py", "test_run", 2, 1, 3)
    report = Report(
        profile="test",
        repo_root="/not-addressed",
        spec_sections=(
            SpecSection(
                "docs/specs/x.md", "X-1", "Contract", 3, "contract-x-1", "heading"
            ),
        ),
        code_refs=(),
        spec_mappings=(mapping,),
        edges=(Edge("mapping", "docs/specs/x.md", "X-1", "pkg/x.py", nfc_symbol, 7),),
        issues=(),
        invariants=(declaration,),
        binds=(bind,),
    )
    atomic_targets = atomic_invariant_targets(snapshot, report, PROFILE)
    inventory = build_obligation_inventory(
        report,
        profile=PROFILE,
        snapshot=SnapshotIdentity("snapshot", 3, 100, 0),
        atomic_invariant_targets=atomic_targets,
    )
    obligation = inventory.get("invariant::INV.X.1")
    assert obligation is not None

    rows = build_evidence_summary_items(report, obligation, snapshot, PROFILE)

    assert atomic_targets == frozenset()
    assert obligation.gate_state == "not_executable"
    assert obligation.alignment_state == "partial"
    assert all(row["path"] != "pkg/x.py" for row in rows)
    assert any(row["declared_target"] == f"pkg/x.py::{nfc_symbol}" for row in rows)


def test_duplicate_code_and_binding_owners_use_parser_owned_exact_lines() -> None:
    code = (
        b"def run() -> int:\n    return 0\n\n"
        b"def run() -> int:\n"
        b'    """Invariant: [INV.X.1] Stable."""\n'
        b"    return 1\n"
    )
    tests = (
        b"def test_run() -> None:\n    pass\n\n"
        b"# Tests-invariant: [INV.X.1]\n"
        b"@case\n"
        b"def test_run() -> None:\n"
        b"    assert True\n"
    )
    snapshot = _snapshot({"pkg/x.py": code, "tests/test_x.py": tests})
    declaration = InvariantDeclaration(
        "INV.X.1", "Stable.", "required", "code", "pkg/x.py", 5, "run", None
    )
    bind = InvariantBind("INV.X.1", "tests/test_x.py", "test_run", 4, 5, 7)
    report = Report(
        profile="test",
        repo_root="/not-addressed",
        spec_sections=(),
        code_refs=(),
        spec_mappings=(),
        edges=(),
        issues=(),
        invariants=(declaration,),
        binds=(bind,),
    )
    assert atomic_code_invariant_ids(snapshot, report) == frozenset({"INV.X.1"})
    inventory = build_obligation_inventory(
        report,
        profile=PROFILE,
        snapshot=SnapshotIdentity("snapshot", 2, 100, 0),
        atomic_code_invariant_ids=frozenset({"INV.X.1"}),
    )
    obligation = inventory.get("invariant::INV.X.1")
    assert obligation is not None
    assert obligation.alignment_state == "complete"

    rows = build_evidence_summary_items(report, obligation, snapshot, PROFILE)

    assert [row["receipt"]["structural_locator"] for row in rows] == [
        "python-definition:run:function:1",
        "python-definition:test_run:function:1",
    ]
    assert [(row["start_line"], row["end_line"]) for row in rows] == [
        (4, 6),
        (5, 7),
    ]
    binding_row = next(row for row in rows if row["role"] == "binding_test")
    [binding_declaration] = binding_row["declarations"]
    assert binding_declaration["receipt"]["start_line"] == 4


def test_code_declared_module_invariant_has_whole_module_receipt() -> None:
    code = b'"""Invariant: [INV.MODULE.1] Stable module."""\nVALUE = 1\n'
    tests = (
        b"def test_module() -> None:\n"
        b'    """Tests-invariant: [INV.MODULE.1]"""\n'
        b"    assert True\n"
    )
    snapshot = _snapshot({"pkg/x.py": code, "tests/test_x.py": tests})
    declaration = InvariantDeclaration(
        "INV.MODULE.1",
        "Stable module.",
        "required",
        "code",
        "pkg/x.py",
        1,
        "module",
        None,
    )
    bind = InvariantBind("INV.MODULE.1", "tests/test_x.py", "test_module", 2, 1, 3)
    report = Report(
        profile="test",
        repo_root="/not-addressed",
        spec_sections=(),
        code_refs=(),
        spec_mappings=(),
        edges=(),
        issues=(),
        invariants=(declaration,),
        binds=(bind,),
    )
    atomic_ids = atomic_code_invariant_ids(snapshot, report)
    assert atomic_ids == frozenset({"INV.MODULE.1"})
    inventory = build_obligation_inventory(
        report,
        profile=PROFILE,
        snapshot=SnapshotIdentity("snapshot", 2, 100, 0),
        atomic_code_invariant_ids=atomic_ids,
    )
    obligation = inventory.get("invariant::INV.MODULE.1")
    assert obligation is not None
    assert obligation.gate_state == "executable"

    rows = build_evidence_summary_items(report, obligation, snapshot, PROFILE)

    implementation = next(row for row in rows if row["role"] == "implementation")
    assert implementation["owner"] == "module"
    assert implementation["receipt"]["structural_locator"] == (
        "python-file:" + hashlib.sha256(b"pkg/x.py").hexdigest()
    )


def test_outside_root_file_invariant_readiness_and_summary_agree() -> None:
    spec = (
        b"# X\n\n## Contract [X-1]\n\n"
        b"Invariant: [INV.OUTSIDE.1] Stable vendor module.\n\n"
        b"- `vendor/x.py`\n"
    )
    code = b"VALUE = 1\n"
    tests = (
        b"def test_vendor() -> None:\n"
        b'    """Tests-invariant: [INV.OUTSIDE.1]"""\n'
        b"    assert True\n"
    )
    snapshot = _snapshot(
        {
            "docs/specs/x.md": spec,
            "vendor/x.py": code,
            "tests/test_x.py": tests,
        }
    )
    declaration = InvariantDeclaration(
        "INV.OUTSIDE.1",
        "Stable vendor module.",
        "required",
        "spec",
        "docs/specs/x.md",
        5,
        None,
        "X-1",
    )
    mapping = SpecMapping(
        "docs/specs/x.md", "X-1", 7, "vendor/x.py", "path", "vendor/x.py", None
    )
    bind = InvariantBind("INV.OUTSIDE.1", "tests/test_x.py", "test_vendor", 2, 1, 3)
    report = Report(
        profile="test",
        repo_root="/not-addressed",
        spec_sections=(
            SpecSection(
                "docs/specs/x.md", "X-1", "Contract", 3, "contract-x-1", "heading"
            ),
        ),
        code_refs=(),
        spec_mappings=(mapping,),
        edges=(Edge("mapping", "docs/specs/x.md", "X-1", "vendor/x.py", None, 7),),
        issues=(),
        invariants=(declaration,),
        binds=(bind,),
    )
    atomic_targets = atomic_invariant_targets(snapshot, report, PROFILE)
    inventory = build_obligation_inventory(
        report,
        profile=PROFILE,
        snapshot=SnapshotIdentity("snapshot", 3, 100, 0),
        atomic_invariant_targets=atomic_targets,
    )
    obligation = inventory.get("invariant::INV.OUTSIDE.1")
    assert obligation is not None

    rows = build_evidence_summary_items(report, obligation, snapshot, PROFILE)

    assert atomic_targets == frozenset({("vendor/x.py", None)})
    assert obligation.gate_state == "executable"
    implementation = next(row for row in rows if row["role"] == "implementation")
    assert implementation["path"] == "vendor/x.py"
    assert implementation["reciprocity_state"] == "complete"
    assert implementation["receipt"]["structural_locator"] == (
        "python-file:" + hashlib.sha256(b"vendor/x.py").hexdigest()
    )
