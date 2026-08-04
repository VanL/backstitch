"""Durable same-directory publication for mutable command artifacts.

Spec: docs/specs/02-backstitch-core.md [SC-17]
Spec: docs/specs/06-semantic-gates.md [SEM-7]
Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-5.1]
Spec: docs/specs/08-intent-coverage.md [COV-9]
"""

from __future__ import annotations

import os
import secrets
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

__all__ = (
    "ArtifactPublicationError",
    "atomic_replace_bytes",
    "publish_artifact_set",
    "publish_staged_artifact",
    "stage_artifact_bytes",
)


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_replace_bytes(path: Path, content: bytes) -> None:
    """Publish bytes through a same-directory fsynced temporary and replace."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        handle = os.fdopen(descriptor, "wb", closefd=True)
        descriptor = -1
        with handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def stage_artifact_bytes(path: Path, content: bytes) -> Path:
    """Write and fsync one same-directory staging file without publishing it."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = -1
    temporary: Path | None = None
    for _ in range(10):
        candidate = path.parent / (
            f".{path.name}.{os.getpid()}.{secrets.token_hex(16)}.tmp"
        )
        try:
            descriptor = os.open(
                candidate,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError:
            continue
        temporary = candidate
        break
    if temporary is None:
        raise FileExistsError("could not allocate a unique artifact staging path")
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        return temporary
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def publish_staged_artifact(path: Path, staged: Path) -> None:
    """Atomically replace one final path with a completed adjacent staging file."""

    os.replace(staged, path)
    _fsync_directory(path.parent)


class ArtifactPublicationError(OSError):
    """A staged artifact set failed with exact partial-publication context."""

    def __init__(
        self,
        failed_path: Path,
        published_paths: tuple[Path, ...],
        cause: OSError,
    ) -> None:
        super().__init__(str(cause))
        self.failed_path = failed_path
        self.published_paths = published_paths
        self.__cause__ = cause


def publish_artifact_set(
    ordered_items: Sequence[tuple[Path, bytes]],
    *,
    before_publish: Callable[[], None] | None = None,
) -> None:
    """Stage all artifacts, validate currentness, then publish in order."""

    staged: list[tuple[Path, Path]] = []
    try:
        for final_path, content in ordered_items:
            try:
                staged_path = stage_artifact_bytes(final_path, content)
            except OSError as exc:
                raise ArtifactPublicationError(final_path, (), exc) from exc
            staged.append((final_path, staged_path))
        if before_publish is not None:
            before_publish()
        published: list[Path] = []
        for final_path, staged_path in staged:
            try:
                publish_staged_artifact(final_path, staged_path)
            except OSError as exc:
                raise ArtifactPublicationError(
                    final_path, tuple(published), exc
                ) from exc
            published.append(final_path)
    finally:
        for _, staged_path in staged:
            try:
                staged_path.unlink()
            except FileNotFoundError:
                pass
