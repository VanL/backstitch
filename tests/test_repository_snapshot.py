"""Immutable repository source-view contract tests.

Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-8.2], [EVC-8.3.1]
Plan: docs/plans/2026-07-15-agent-guided-evidence-cases-plan.md Slice 1
"""

from __future__ import annotations

import errno
import os
import stat
from dataclasses import replace
from pathlib import Path

import pytest

from backstitch.operation_progress import (
    OperationDeadlineExceeded,
    OperationProgress,
)
from backstitch.repository_snapshot import (
    FileStat,
    SnapshotAlgorithms,
    SnapshotCaptureError,
    SnapshotCaptureHooks,
    SnapshotSemanticConfig,
    capture_repository_snapshot,
)


def _config(repo: Path, **changes: object) -> SnapshotSemanticConfig:
    values: dict[str, object] = {
        "profile_name": "test-v1",
        "spec_roots": ("docs/specs",),
        "plan_roots": ("docs/plans",),
        "code_roots": ("src", "tests"),
        "test_roots": ("tests",),
        "exclusions": ("ignored",),
        "planned_spec_globs": ("docs/specs/planned-*.md",),
        "exploratory_spec_globs": (),
        "section_required_roles": ("implementation",),
        "maximum_candidate_items": 2000,
        "maximum_catalog_items": 100000,
        "maximum_lexical_seeds": 10,
        "maximum_snapshot_files": 100,
        "maximum_file_bytes": 1000,
        "maximum_snapshot_bytes": 10000,
        "maximum_work_units": 2000000,
        "maximum_packet_bytes": 100000,
        "maximum_packet_report_bytes": 100000,
        "static_neighbor_depth": 1,
    }
    values.update(changes)
    return SnapshotSemanticConfig(**values)  # type: ignore[arg-type]


ALGORITHMS = SnapshotAlgorithms(
    snapshot_algorithm_version=1,
    obligation_algorithm_version=1,
    discovery_algorithm_version=1,
    packet_contract_version=3,
    normalization_version=1,
)


def test_capture_returns_one_ordered_exact_byte_view(tmp_path: Path) -> None:
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "docs/plans").mkdir(parents=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "docs/specs/z.md").write_bytes(b"z\r\n")
    (tmp_path / "docs/specs/a.md").write_bytes(b"a\x00\xff")
    (tmp_path / "docs/plans/p.md").write_bytes(b"plan")
    (tmp_path / "src/main.py").write_bytes(b"value = 1\n")
    (tmp_path / "tests/test_main.py").write_bytes(b"def test_value(): pass\n")

    snapshot = capture_repository_snapshot(tmp_path, _config(tmp_path), ALGORITHMS)

    assert tuple(row.path for row in snapshot.files) == (
        "docs/plans/p.md",
        "docs/specs/a.md",
        "docs/specs/z.md",
        "src/main.py",
        "tests/test_main.py",
    )
    assert snapshot.read_bytes("docs/specs/a.md") == b"a\x00\xff"
    assert snapshot.file_count == 5
    assert snapshot.byte_count == 43
    assert snapshot.unreadable_count == 0
    source_stat = (tmp_path / "docs/specs/a.md").lstat()
    assert snapshot.file("docs/specs/a.md").file_stat == FileStat(
        st_dev=source_stat.st_dev,
        st_ino=source_stat.st_ino,
        file_type_and_permission_mode=(
            stat.S_IFMT(source_stat.st_mode) | stat.S_IMODE(source_stat.st_mode)
        ),
        st_size=source_stat.st_size,
        st_mtime_ns=source_stat.st_mtime_ns,
        st_ctime_ns=source_stat.st_ctime_ns,
    )
    (tmp_path / "docs/specs/a.md").write_bytes(b"changed after capture")
    assert snapshot.read_bytes("docs/specs/a.md") == b"a\x00\xff"


def test_snapshot_checks_deadline_after_each_repository_file_read(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/a.py").write_bytes(b"value = 1\n")
    now = [0.0]
    progress = OperationProgress.start(1.0, clock=lambda: now[0])

    def expire_after_read(_attempt: int, _path: str, _root: Path) -> None:
        now[0] = 1.001

    with pytest.raises(OperationDeadlineExceeded) as raised:
        capture_repository_snapshot(
            tmp_path,
            _config(tmp_path),
            ALGORITHMS,
            hooks=SnapshotCaptureHooks(after_file_read=expire_after_read),
            progress=progress,
        )

    assert raised.value.phase == "snapshot"


def test_torn_attempt_discards_bytes_and_retries_from_empty(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    source = tmp_path / "src/a.py"
    source.write_bytes(b"old")
    seen_attempts: list[int] = []

    def mutate_first_attempt(attempt: int, _root: Path) -> None:
        seen_attempts.append(attempt)
        if attempt == 1:
            source.write_bytes(b"accepted")

    snapshot = capture_repository_snapshot(
        tmp_path,
        _config(tmp_path),
        ALGORITHMS,
        hooks=SnapshotCaptureHooks(after_initial_inventory=mutate_first_attempt),
    )

    assert seen_attempts == [1, 2]
    assert snapshot.read_bytes("src/a.py") == b"accepted"
    assert b"old" not in tuple(
        row.raw_bytes for row in snapshot.files if row.raw_bytes is not None
    )


def test_torn_attempt_exhaustion_reports_exact_attempt_count(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    source = tmp_path / "src/a.py"
    source.write_bytes(b"initial")

    def mutate_every_attempt(attempt: int, _root: Path) -> None:
        source.write_bytes(b"x" * attempt)

    with pytest.raises(SnapshotCaptureError) as raised:
        capture_repository_snapshot(
            tmp_path,
            _config(tmp_path),
            ALGORITHMS,
            capture_attempts=3,
            hooks=SnapshotCaptureHooks(after_initial_inventory=mutate_every_attempt),
        )

    assert raised.value.kind == "snapshot_unstable"
    assert raised.value.attempts == 3


@pytest.mark.parametrize("mutation", ("add", "delete", "replace"))
def test_membership_and_inode_changes_discard_the_complete_attempt(
    tmp_path: Path, mutation: str
) -> None:
    (tmp_path / "src").mkdir()
    source = tmp_path / "src/a.py"
    source.write_bytes(b"before")

    def mutate_first_attempt(attempt: int, _root: Path) -> None:
        if attempt != 1:
            return
        if mutation == "add":
            (tmp_path / "src/b.py").write_bytes(b"added")
        elif mutation == "delete":
            source.unlink()
        else:
            replacement = tmp_path / "replacement"
            replacement.write_bytes(b"replaced")
            replacement.replace(source)

    snapshot = capture_repository_snapshot(
        tmp_path,
        _config(tmp_path),
        ALGORITHMS,
        hooks=SnapshotCaptureHooks(after_initial_inventory=mutate_first_attempt),
    )

    expected = {
        "add": (("src/a.py", b"before"), ("src/b.py", b"added")),
        "delete": (),
        "replace": (("src/a.py", b"replaced"),),
    }
    assert (
        tuple((row.path, row.raw_bytes) for row in snapshot.files) == expected[mutation]
    )


def test_non_source_catalog_mutation_is_part_of_torn_capture_detection(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    seen_attempts: list[int] = []

    def add_catalog_path(attempt: int, _root: Path) -> None:
        seen_attempts.append(attempt)
        if attempt == 1:
            (tmp_path / "src/owner.txt").write_bytes(b"owner")

    snapshot = capture_repository_snapshot(
        tmp_path,
        _config(tmp_path),
        ALGORITHMS,
        hooks=SnapshotCaptureHooks(after_initial_inventory=add_catalog_path),
    )

    assert seen_attempts == [1, 2]
    assert snapshot.files == ()
    assert snapshot.path_exists("src/owner.txt")
    assert snapshot.path_kind("src/owner.txt") == "regular_file"


def test_catalog_captures_only_directories_regular_files_and_missing_roots(
    tmp_path: Path,
) -> None:
    (tmp_path / "src/nested").mkdir(parents=True)
    (tmp_path / "src/nested/owner.txt").write_bytes(b"owner")
    (tmp_path / "src/nested/link.txt").symlink_to("owner.txt")
    os.mkfifo(tmp_path / "src/nested/pipe.txt")
    (tmp_path / "root-owner.txt").write_bytes(b"outside configured roots")

    snapshot = capture_repository_snapshot(
        tmp_path,
        _config(tmp_path),
        ALGORITHMS,
        additional_paths=("root-owner.txt",),
    )

    assert snapshot.missing_roots == ("docs/plans", "docs/specs", "tests")
    assert snapshot.path_exists("src/nested/")
    assert snapshot.path_kind("src/nested") == "directory"
    assert snapshot.path_kind("src/nested/owner.txt") == "regular_file"
    assert not snapshot.path_exists("src/nested/link.txt")
    assert not snapshot.path_exists("src/nested/pipe.txt")
    assert snapshot.path_kind("root-owner.txt") == "regular_file"
    assert snapshot.read_bytes("root-owner.txt") == b"outside configured roots"
    assert snapshot.path_kind(".") == "directory"
    assert not snapshot.path_exists("src/nested/missing.txt")
    assert not snapshot.path_exists("../outside")

    before = snapshot.snapshot_hash
    (tmp_path / "docs/specs").mkdir(parents=True)
    after = capture_repository_snapshot(tmp_path, _config(tmp_path), ALGORITHMS)
    assert after.missing_roots == ("docs/plans", "tests")
    assert after.snapshot_hash != before


def test_operational_paths_are_excluded_without_entering_semantic_config(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/.cache/results").mkdir(parents=True)
    (tmp_path / "src/.cache/results/old.json").write_bytes(b"old")

    snapshot = capture_repository_snapshot(
        tmp_path,
        _config(tmp_path),
        ALGORITHMS,
        operational_exclusions=("src/.cache",),
    )

    assert not snapshot.path_exists("src/.cache")
    semantic_config = snapshot.identity_document()["semantic_config"]
    assert isinstance(semantic_config, dict)
    assert "operational_exclusions" not in semantic_config


def test_additional_directory_and_missing_targets_are_snapshot_addressed(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "assets").mkdir()

    snapshot = capture_repository_snapshot(
        tmp_path,
        _config(tmp_path),
        ALGORITHMS,
        additional_paths=("assets/", "missing.txt", "."),
    )

    assert snapshot.path_kind("assets/") == "directory"
    assert snapshot.path_kind("missing.txt") is None
    assert snapshot.path_kind(".") == "directory"


def test_discovered_paths_are_nfc_but_reads_use_the_native_name(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    decomposed = "cafe\u0301.py"
    (tmp_path / "src" / decomposed).write_bytes(b"native")

    snapshot = capture_repository_snapshot(tmp_path, _config(tmp_path), ALGORITHMS)

    assert tuple(row.path for row in snapshot.files) == ("src/caf\u00e9.py",)
    assert snapshot.read_bytes("src/caf\u00e9.py") == b"native"


def test_nfc_path_collision_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    composed = tmp_path / "src/caf\u00e9.py"
    decomposed = tmp_path / "src/cafe\u0301.py"
    composed.write_bytes(b"composed")
    decomposed.write_bytes(b"decomposed")

    with pytest.raises(SnapshotCaptureError) as raised:
        capture_repository_snapshot(
            tmp_path,
            _config(tmp_path),
            ALGORITHMS,
            additional_paths=("src/caf\u00e9.py", "src/cafe\u0301.py"),
        )

    assert raised.value.kind == "invalid_path"
    assert "NFC normalization" in str(raised.value)


@pytest.mark.parametrize(
    ("error_number", "expected_class"),
    ((errno.EACCES, "permission"), (errno.EIO, "io")),
)
def test_stable_open_failure_becomes_an_unreadable_manifest_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error_number: int,
    expected_class: str,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/locked.py").write_bytes(b"source")
    real_open = os.open

    def fail_source_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if path == "locked.py" and not flags & os.O_DIRECTORY:
            raise OSError(error_number, os.strerror(error_number), path)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr("backstitch.repository_snapshot.os.open", fail_source_open)

    snapshot = capture_repository_snapshot(tmp_path, _config(tmp_path), ALGORITHMS)

    assert snapshot.files[0].manifest_row() == {
        "path": "src/locked.py",
        "state": "unreadable",
        "raw_sha256": None,
        "error_class": expected_class,
    }
    assert snapshot.unreadable_count == 1
    with pytest.raises(OSError, match="unreadable"):
        snapshot.read_bytes("src/locked.py")


def test_stable_bounded_read_failure_is_classified_as_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/read-error.py").write_bytes(b"source")

    def fail_read(_file_fd: int, _byte_count: int) -> bytes:
        raise OSError(errno.EIO, os.strerror(errno.EIO))

    monkeypatch.setattr("backstitch.repository_snapshot.os.read", fail_read)

    snapshot = capture_repository_snapshot(tmp_path, _config(tmp_path), ALGORITHMS)

    assert snapshot.files[0].state == "unreadable"
    assert snapshot.files[0].error_class == "io"


def test_symlink_and_nonregular_sources_are_rejected_without_retry(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "outside.py").write_bytes(b"outside")
    (tmp_path / "src/link.py").symlink_to(tmp_path / "outside.py")
    attempts: list[int] = []

    with pytest.raises(SnapshotCaptureError) as symlink_error:
        capture_repository_snapshot(
            tmp_path,
            _config(tmp_path),
            ALGORITHMS,
            hooks=SnapshotCaptureHooks(
                after_initial_inventory=lambda attempt, _root: attempts.append(attempt)
            ),
        )

    assert symlink_error.value.kind == "symlink"
    assert symlink_error.value.path == "src/link.py"
    assert attempts == []

    (tmp_path / "src/link.py").unlink()
    os.mkfifo(tmp_path / "src/pipe.py")
    with pytest.raises(SnapshotCaptureError) as nonregular_error:
        capture_repository_snapshot(tmp_path, _config(tmp_path), ALGORITHMS)
    assert nonregular_error.value.kind == "not_regular"
    assert nonregular_error.value.path == "src/pipe.py"


def test_uncontained_and_symlinked_root_components_are_rejected(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    try:
        with pytest.raises(SnapshotCaptureError) as escape_error:
            capture_repository_snapshot(
                tmp_path,
                _config(tmp_path, code_roots=(str(outside),)),
                ALGORITHMS,
            )
        assert escape_error.value.kind == "invalid_path"

        (outside / "a.py").write_bytes(b"outside")
        (tmp_path / "src-link").symlink_to(outside, target_is_directory=True)
        with pytest.raises(SnapshotCaptureError) as link_error:
            capture_repository_snapshot(
                tmp_path,
                _config(tmp_path, code_roots=("src-link",)),
                ALGORITHMS,
            )
        assert link_error.value.kind == "symlink"
    finally:
        if (outside / "a.py").exists():
            (outside / "a.py").unlink()
        outside.rmdir()


@pytest.mark.parametrize(
    "invalid_root", ("src//nested", "src/./nested", "src/../nested", "src\\nested")
)
def test_descriptor_paths_reject_noncanonical_components(
    tmp_path: Path, invalid_root: str
) -> None:
    with pytest.raises(SnapshotCaptureError) as raised:
        capture_repository_snapshot(
            tmp_path,
            _config(tmp_path, code_roots=(invalid_root,)),
            ALGORITHMS,
        )

    assert raised.value.kind == "invalid_path"


@pytest.mark.parametrize(
    ("files", "limits", "expected_budget", "expected_limit", "expected_observed"),
    (
        (
            {"a.py": b"a", "b.py": b"b"},
            {"maximum_snapshot_files": 1},
            "snapshot_files",
            1,
            2,
        ),
        ({"a.py": b"a"}, {"maximum_catalog_items": 1}, "catalog_items", 1, 3),
        (
            {"a.py": b"four"},
            {"maximum_file_bytes": 3, "maximum_snapshot_bytes": 3},
            "file_bytes",
            3,
            4,
        ),
        (
            {"a.py": b"aaa", "b.py": b"bbb"},
            {"maximum_file_bytes": 4, "maximum_snapshot_bytes": 4},
            "snapshot_bytes",
            4,
            6,
        ),
    ),
)
def test_snapshot_budgets_abort_without_a_partial_result(
    tmp_path: Path,
    files: dict[str, bytes],
    limits: dict[str, object],
    expected_budget: str,
    expected_limit: int,
    expected_observed: int,
) -> None:
    (tmp_path / "src").mkdir()
    for name, raw in files.items():
        (tmp_path / "src" / name).write_bytes(raw)

    with pytest.raises(SnapshotCaptureError) as raised:
        capture_repository_snapshot(tmp_path, _config(tmp_path, **limits), ALGORITHMS)

    assert raised.value.kind == "budget_exceeded"
    assert raised.value.budget == expected_budget
    assert raised.value.limit == expected_limit
    assert raised.value.observed == expected_observed


def test_identity_is_canonical_and_excludes_clone_root(tmp_path: Path) -> None:
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "docs/specs/a.md").write_bytes(b"spec")
    (tmp_path / "src/a.py").write_bytes(b"code")
    (tmp_path / ".backstitch.toml").write_bytes(b"[x]\n")
    config = _config(
        tmp_path,
        spec_roots=(str(tmp_path / "docs/specs"), "docs/specs"),
        code_roots=("src", "src"),
        exclusions=("z", "a", "z"),
        planned_spec_globs=("z*.md", "a*.md", "z*.md"),
    )

    snapshot = capture_repository_snapshot(
        tmp_path, config, ALGORITHMS, config_paths=(".backstitch.toml",)
    )

    assert snapshot.identity_document() == {
        "identity": "backstitch-repository-snapshot",
        "version": 1,
        "config_inputs": [],
        "files": [
            {
                "path": ".backstitch.toml",
                "state": "readable",
                "raw_sha256": "ab14079088f3d9b190ffab0d312b7806f98372d1417d747495070fb40494de72",
                "error_class": None,
            },
            {
                "path": "docs/specs/a.md",
                "state": "readable",
                "raw_sha256": "d4f02eaafd1a9e9de7d10972ca8e47fa7a985825c3c9c1e249c72683cb3e4f19",
                "error_class": None,
            },
            {
                "path": "src/a.py",
                "state": "readable",
                "raw_sha256": "5694d08a2e53ffcae0c3103e5ad6f6076abd960eb1f8a56577040bc1028f702b",
                "error_class": None,
            },
        ],
        "catalog_sha256": "5f52e49a8261647959d8bc3ba420d411e85a3b130c36cd62a74bb502dfb623e5",
        "missing_roots": ["docs/plans", "tests"],
        "semantic_config": {
            "profile_name": "test-v1",
            "spec_roots": ["docs/specs"],
            "plan_roots": ["docs/plans"],
            "code_roots": ["src"],
            "test_roots": ["tests"],
            "exclusions": ["a", "z"],
            "planned_spec_globs": ["a*.md", "z*.md"],
            "exploratory_spec_globs": [],
            "section_required_roles": ["implementation"],
            "maximum_candidate_items": 2000,
            "maximum_catalog_items": 100000,
            "maximum_lexical_seeds": 10,
            "maximum_snapshot_files": 100,
            "maximum_file_bytes": 1000,
            "maximum_snapshot_bytes": 10000,
            "maximum_work_units": 2000000,
            "maximum_packet_bytes": 100000,
            "maximum_packet_report_bytes": 100000,
            "static_neighbor_depth": 1,
        },
        "algorithms": {
            "snapshot_algorithm_version": 1,
            "obligation_algorithm_version": 1,
            "discovery_algorithm_version": 1,
            "packet_contract_version": 3,
            "normalization_version": 1,
        },
    }
    assert (
        snapshot.snapshot_hash
        == "8f543dae80aeabe771e93ffa56dd63f95abe910bdc39bec3507a36c04a62523b"
    )


def test_every_semantic_and_algorithm_input_changes_snapshot_identity(
    tmp_path: Path,
) -> None:
    baseline_config = _config(tmp_path)
    baseline = capture_repository_snapshot(tmp_path, baseline_config, ALGORITHMS)
    config_mutations: dict[str, object] = {
        "profile_name": "other-v1",
        "spec_roots": ("other-specs",),
        "plan_roots": ("other-plans",),
        "code_roots": ("other-src",),
        "test_roots": ("other-tests",),
        "exclusions": ("other-ignore",),
        "planned_spec_globs": ("other-planned-*",),
        "exploratory_spec_globs": ("other-exploratory-*",),
        "section_required_roles": ("implementation", "test"),
        "maximum_candidate_items": 1001,
        "maximum_catalog_items": 100001,
        "maximum_lexical_seeds": 11,
        "maximum_snapshot_files": 101,
        "maximum_file_bytes": 1001,
        "maximum_snapshot_bytes": 10001,
        "maximum_work_units": 2000001,
        "maximum_packet_bytes": 100001,
        "maximum_packet_report_bytes": 100001,
        "static_neighbor_depth": 2,
    }
    for field, value in config_mutations.items():
        changed = capture_repository_snapshot(
            tmp_path, _config(tmp_path, **{field: value}), ALGORITHMS
        )
        assert changed.snapshot_hash != baseline.snapshot_hash, field

    for field in ALGORITHMS.__dataclass_fields__:
        changed_algorithms = replace(
            ALGORITHMS, **{field: getattr(ALGORITHMS, field) + 1}
        )
        changed = capture_repository_snapshot(
            tmp_path, baseline_config, changed_algorithms
        )
        assert changed.snapshot_hash != baseline.snapshot_hash, field

    assert (
        capture_repository_snapshot(
            tmp_path, baseline_config, ALGORITHMS, capture_attempts=1
        ).snapshot_hash
        == baseline.snapshot_hash
    )


def test_unsupported_platform_is_rejected_before_root_traversal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing_root = tmp_path / "does-not-exist"
    monkeypatch.setattr("backstitch.repository_snapshot._OPEN_SUPPORTS_DIR_FD", False)

    with pytest.raises(SnapshotCaptureError) as raised:
        capture_repository_snapshot(missing_root, _config(tmp_path), ALGORITHMS)

    assert raised.value.kind == "unsupported_platform"
