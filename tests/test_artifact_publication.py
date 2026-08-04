"""Real-filesystem contracts for mutable artifact publication.

Spec: docs/specs/06-semantic-gates.md [SEM-7]
Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-5.1]
Spec: docs/specs/08-intent-coverage.md [COV-9]
Plan: docs/plans/2026-07-29-architecture-quality-remediation-plan.md Slice 4
"""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

import pytest

import backstitch.artifact_publication as publication
from backstitch.artifact_publication import (
    ArtifactPublicationError,
    atomic_replace_bytes,
    publish_artifact_set,
    stage_artifact_bytes,
)


def test_staging_is_exclusive_and_retries_a_real_collision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "analysis.json"
    collision_token = "0" * 32
    selected_token = "1" * 32
    collision = tmp_path / (f".{target.name}.{os.getpid()}.{collision_token}.tmp")
    collision.write_bytes(b"other run")
    tokens = iter((collision_token, selected_token))
    monkeypatch.setattr(publication.secrets, "token_hex", lambda _: next(tokens))

    staged = stage_artifact_bytes(target, b"\x00complete bytes\n")

    try:
        assert collision.read_bytes() == b"other run"
        assert staged.read_bytes() == b"\x00complete bytes\n"
        assert re.fullmatch(
            rf"\.analysis\.json\.{os.getpid()}\.[0-9a-f]{{32}}\.tmp",
            staged.name,
        )
        assert staged.name.endswith(f".{selected_token}.tmp")
        assert staged.is_file()
        assert not staged.is_symlink()
    finally:
        staged.unlink(missing_ok=True)


def test_atomic_replace_fsyncs_file_then_directory_and_preserves_exact_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "nested" / "artifact.bin"
    fsync_kinds: list[str] = []
    real_fsync = publication.os.fsync

    def observe_fsync(descriptor: int) -> None:
        mode = os.fstat(descriptor).st_mode
        fsync_kinds.append("directory" if stat.S_ISDIR(mode) else "file")
        real_fsync(descriptor)

    monkeypatch.setattr(publication.os, "fsync", observe_fsync)

    atomic_replace_bytes(target, b"\x00new bytes\r\n")

    assert target.read_bytes() == b"\x00new bytes\r\n"
    assert fsync_kinds == ["file", "directory"]
    assert tuple(target.parent.glob(f".{target.name}.*.tmp")) == ()


def test_artifact_set_stages_before_callback_then_replaces_in_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_bytes(b"old-first")
    second.write_bytes(b"old-second")
    replacements: list[Path] = []
    real_replace = publication.os.replace

    def observe_replace(source: Path, destination: Path) -> None:
        replacements.append(Path(destination))
        real_replace(source, destination)

    def confirm_current() -> None:
        assert replacements == []
        assert first.read_bytes() == b"old-first"
        assert second.read_bytes() == b"old-second"
        assert len(tuple(tmp_path.glob(".*.tmp"))) == 2

    monkeypatch.setattr(publication.os, "replace", observe_replace)

    publish_artifact_set(
        ((first, b"new-first"), (second, b"new-second")),
        before_publish=confirm_current,
    )

    assert replacements == [first, second]
    assert first.read_bytes() == b"new-first"
    assert second.read_bytes() == b"new-second"
    assert tuple(tmp_path.glob(".*.tmp")) == ()


def test_callback_failure_preserves_finals_and_cleans_staging(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_bytes(b"old-first")
    second.write_bytes(b"old-second")

    def reject() -> None:
        assert first.read_bytes() == b"old-first"
        assert second.read_bytes() == b"old-second"
        assert len(tuple(tmp_path.glob(".*.tmp"))) == 2
        raise RuntimeError("currentness rejected")

    with pytest.raises(RuntimeError, match="currentness rejected"):
        publish_artifact_set(
            ((first, b"new-first"), (second, b"new-second")),
            before_publish=reject,
        )

    assert first.read_bytes() == b"old-first"
    assert second.read_bytes() == b"old-second"
    assert tuple(tmp_path.glob(".*.tmp")) == ()


def test_publication_failure_reports_failed_and_prior_paths_then_cleans(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    second.mkdir()

    with pytest.raises(ArtifactPublicationError) as raised:
        publish_artifact_set(((first, b"first"), (second, b"second")))

    error = raised.value
    assert error.failed_path == second
    assert error.published_paths == (first,)
    assert isinstance(error.__cause__, OSError)
    assert str(error) == str(error.__cause__)
    assert first.read_bytes() == b"first"
    assert second.is_dir()
    assert tuple(tmp_path.glob(".*.tmp")) == ()


def test_staging_failure_publishes_nothing_and_cleans_prior_staging(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.json"
    first.write_bytes(b"old-first")
    blocked_parent = tmp_path / "not-a-directory"
    blocked_parent.write_bytes(b"regular file")
    second = blocked_parent / "second.json"

    with pytest.raises(ArtifactPublicationError) as raised:
        publish_artifact_set(((first, b"new-first"), (second, b"second")))

    assert raised.value.failed_path == second
    assert raised.value.published_paths == ()
    assert first.read_bytes() == b"old-first"
    assert tuple(tmp_path.glob(".*.tmp")) == ()
