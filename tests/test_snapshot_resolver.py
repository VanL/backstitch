"""Snapshot-backed deterministic resolver integration tests.

Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-8.2], [EVC-8.3.1]
Plan: docs/plans/2026-07-15-agent-guided-evidence-cases-plan.md Slice 1
"""

from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

from backstitch.check_pipeline import build_check_report_from_snapshot
from backstitch.config import ProfileConfig
from backstitch.profiles import get_profile
from backstitch.repository_snapshot import (
    SnapshotAlgorithms,
    SnapshotSemanticConfig,
    capture_repository_snapshot,
)
from backstitch.resolver import scan_snapshot_with_artifacts
from backstitch.settings import BackstitchSettings

ALGORITHMS = SnapshotAlgorithms(
    snapshot_algorithm_version=1,
    obligation_algorithm_version=1,
    discovery_algorithm_version=1,
    packet_contract_version=3,
    normalization_version=1,
)


def _profile(
    *,
    code_roots: tuple[str, ...] = ("pkg",),
) -> ProfileConfig:
    return get_profile("backstitch-style-v1").with_overrides(
        spec_roots=("docs/specs",),
        plan_roots=(),
        code_roots=code_roots,
        test_roots=(),
        planned_spec_globs=(),
        exploratory_spec_globs=(),
    )


def _config(profile: ProfileConfig) -> SnapshotSemanticConfig:
    return SnapshotSemanticConfig(
        profile_name=profile.name,
        spec_roots=profile.spec_roots,
        plan_roots=profile.plan_roots,
        code_roots=profile.code_roots,
        test_roots=profile.test_roots,
        exclusions=(),
        planned_spec_globs=profile.planned_spec_globs,
        exploratory_spec_globs=profile.exploratory_spec_globs,
        section_required_roles=("implementation",),
        maximum_candidate_items=1000,
        maximum_catalog_items=100000,
        maximum_lexical_seeds=100,
        maximum_snapshot_files=100,
        maximum_file_bytes=10000,
        maximum_snapshot_bytes=100000,
        maximum_work_units=2000000,
        maximum_packet_bytes=100000,
        maximum_packet_report_bytes=100000,
        static_neighbor_depth=1,
    )


def _write_traced_repo(root: Path) -> None:
    (root / "docs/specs").mkdir(parents=True)
    (root / "pkg").mkdir()
    (root / "docs/specs/01-x.md").write_text(
        "## Contract [X-1]\n"
        '<!-- backstitch: skip-obligation [X-1] "External owner." -->\n\n'
        "_Implementation mapping_:\n\n"
        "- `pkg/mod.py::run`\n",
        encoding="utf-8",
    )
    (root / "pkg/mod.py").write_text(
        'def run():\n    """Spec: docs/specs/01-x.md [X-1]"""\n    return 1\n',
        encoding="utf-8",
    )


def test_snapshot_scan_and_check_pipeline_share_one_projection(
    tmp_path: Path,
) -> None:
    _write_traced_repo(tmp_path)
    profile = _profile()
    settings = BackstitchSettings()
    snapshot = capture_repository_snapshot(
        tmp_path,
        _config(profile),
        ALGORITHMS,
        operational_exclusions=settings.exclude,
    )

    snapshot_report, snapshot_artifacts = scan_snapshot_with_artifacts(
        snapshot,
        str(tmp_path.resolve()),
        profile,
    )

    assert [item.code for item in snapshot_report.issues].count(
        "OBLIGATION_SKIPPED"
    ) == 1
    pipeline = build_check_report_from_snapshot(
        snapshot,
        str(tmp_path.resolve()),
        profile,
        settings,
    )
    assert pipeline.raw_report == snapshot_report
    assert pipeline.artifacts == snapshot_artifacts


def test_snapshot_scan_never_reopens_sources_after_capture(tmp_path: Path) -> None:
    _write_traced_repo(tmp_path)
    profile = _profile()
    snapshot = capture_repository_snapshot(tmp_path, _config(profile), ALGORITHMS)
    expected = scan_snapshot_with_artifacts(
        snapshot,
        str(tmp_path.resolve()),
        profile,
    )

    (tmp_path / "docs/specs/01-x.md").unlink()
    (tmp_path / "pkg/mod.py").unlink()

    assert (
        scan_snapshot_with_artifacts(
            snapshot,
            str(tmp_path.resolve()),
            profile,
        )
        == expected
    )


def test_snapshot_catalog_and_additional_bytes_resolve_external_targets(
    tmp_path: Path,
) -> None:
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "assets").mkdir()
    (tmp_path / "tools").mkdir()
    (tmp_path / "docs/specs/01-x.md").write_text(
        "## Contract [X-1]\n\n"
        "_Implementation mapping_:\n\n"
        "- `assets/`\n"
        "- `tools/owner.py::run`\n",
        encoding="utf-8",
    )
    (tmp_path / "tools/owner.py").write_text(
        "def run():\n    return 1\n",
        encoding="utf-8",
    )
    profile = _profile()
    snapshot = capture_repository_snapshot(
        tmp_path,
        _config(profile),
        ALGORITHMS,
        additional_paths=("assets/", "tools/owner.py"),
    )

    snapshot_report, _ = scan_snapshot_with_artifacts(
        snapshot,
        str(tmp_path.resolve()),
        profile,
    )
    assert {
        (edge.code_path, edge.code_symbol)
        for edge in snapshot_report.edges
        if edge.kind == "mapping"
    } == {("assets", None), ("tools/owner.py", "run")}


def test_snapshot_projects_missing_and_unreadable_source_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "docs/specs/01-x.md").write_text(
        "## Contract [X-1]\n",
        encoding="utf-8",
    )
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg/locked.py").write_text("value = 1\n", encoding="utf-8")
    real_open = os.open

    def fail_source_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if path == "locked.py" and not flags & os.O_DIRECTORY:
            raise OSError(errno.EACCES, os.strerror(errno.EACCES), path)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr("backstitch.repository_snapshot.os.open", fail_source_open)
    profile = _profile(code_roots=("pkg", "missing"))
    snapshot = capture_repository_snapshot(tmp_path, _config(profile), ALGORITHMS)

    report, _ = scan_snapshot_with_artifacts(
        snapshot,
        str(tmp_path.resolve()),
        profile,
    )

    projected = {(item.code, item.path) for item in report.issues}
    assert ("SCAN_ROOT_MISSING", "missing") in projected
    assert ("FILE_UNREADABLE", "pkg/locked.py") in projected
