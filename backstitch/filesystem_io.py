"""Stable bounded filesystem primitives shared by source adapters.

Spec: docs/specs/03-backstitch-configuration.md [CFG-5.1]
Spec: docs/specs/02-backstitch-core.md [SC-17]
Spec: docs/specs/05-backstitch-invariants.md [INV-11]
Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-8.2]

This leaf owns byte-stable, no-follow reads of one regular file and the exact
six-field stat identity used to prove that the addressed file did not change.
Repository inventory and retry policy remain with ``repository_snapshot``.
"""

from __future__ import annotations

import errno
import os
import stat
from pathlib import Path

# Capture capability facts before tests or instrumentation wrap these calls.
_OPEN_SUPPORTS_DIR_FD = os.open in os.supports_dir_fd
_STAT_SUPPORTS_DIR_FD = os.stat in os.supports_dir_fd


class StableReadError(Exception):
    """A bounded no-follow read could not prove one stable regular file."""


def file_stat_identity(value: os.stat_result) -> tuple[int, ...]:
    """Return the exact stable-read identity required by [EVC-8.2]."""

    try:
        identity = (
            value.st_dev,
            value.st_ino,
            stat.S_IFMT(value.st_mode) | stat.S_IMODE(value.st_mode),
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )
    except AttributeError:
        raise StableReadError(
            "POSIX no-follow descriptors require nanosecond file timestamps"
        ) from None
    return identity


def _read_bounded(descriptor: int, limit: int) -> bytes:
    chunks: list[bytes] = []
    observed = 0
    while observed <= limit:
        chunk = os.read(descriptor, min(65_536, limit + 1 - observed))
        if not chunk:
            break
        chunks.append(chunk)
        observed += len(chunk)
    return b"".join(chunks)


def _open_directory(root_fd: int, relative: str) -> int:
    current = os.dup(root_fd)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        for component in relative.split("/"):
            before = os.stat(component, dir_fd=current, follow_symlinks=False)
            if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
                raise StableReadError("symlink or non-regular path")
            next_fd = os.open(component, flags, dir_fd=current)
            try:
                if file_stat_identity(before) != file_stat_identity(os.fstat(next_fd)):
                    raise StableReadError("file changed before its bounded read")
            except BaseException:
                os.close(next_fd)
                raise
            os.close(current)
            current = next_fd
        return current
    except BaseException:
        os.close(current)
        raise


def _lstat_path(root_fd: int, path: str) -> os.stat_result:
    components = path.split("/")
    parent = "/".join(components[:-1])
    parent_fd = os.dup(root_fd) if not parent else _open_directory(root_fd, parent)
    try:
        return os.stat(components[-1], dir_fd=parent_fd, follow_symlinks=False)
    finally:
        os.close(parent_fd)


def _open_file(root_fd: int, path: str) -> int:
    components = path.split("/")
    parent = "/".join(components[:-1])
    parent_fd = os.dup(root_fd) if not parent else _open_directory(root_fd, parent)
    flags = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        return os.open(components[-1], flags, dir_fd=parent_fd)
    finally:
        os.close(parent_fd)


def read_regular_nofollow(
    root: Path,
    relative: str,
    *,
    expected_stat: os.stat_result | None = None,
    maximum_bytes: int | None = None,
) -> tuple[bytes, os.stat_result]:
    """Read one stable regular file without following any path component."""

    required = ("O_DIRECTORY", "O_NONBLOCK", "O_NOFOLLOW", "O_CLOEXEC")
    if (
        os.name != "posix"
        or any(not hasattr(os, name) for name in required)
        or not _OPEN_SUPPORTS_DIR_FD
        or not _STAT_SUPPORTS_DIR_FD
    ):
        raise StableReadError("POSIX no-follow descriptors are unavailable")
    root_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    root_fd: int | None = None
    file_fd: int | None = None
    try:
        root_fd = os.open(root, root_flags)
        file_fd = _open_file(root_fd, relative)
        before = os.fstat(file_fd)
        if not stat.S_ISREG(before.st_mode):
            raise StableReadError("path is not a regular non-symlink file")
        if expected_stat is not None and file_stat_identity(
            expected_stat
        ) != file_stat_identity(before):
            raise StableReadError("file changed before its bounded read")
        limit = before.st_size if maximum_bytes is None else maximum_bytes
        raw = _read_bounded(file_fd, limit)
        if len(raw) > limit:
            raise StableReadError("file exceeds its bounded read limit")
        after = os.fstat(file_fd)
        repeated = _lstat_path(root_fd, relative)
        if (
            file_stat_identity(before) != file_stat_identity(after)
            or file_stat_identity(after) != file_stat_identity(repeated)
            or len(raw) != after.st_size
        ):
            raise StableReadError("file changed during its bounded read")
        return raw, before
    except StableReadError:
        raise
    except OSError as exc:
        reason = (
            "symlink or non-regular path"
            if exc.errno in {errno.ENOTDIR, errno.ELOOP, errno.EISDIR, errno.ENXIO}
            else str(exc)
        )
        raise StableReadError(reason) from exc
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if root_fd is not None:
            os.close(root_fd)
