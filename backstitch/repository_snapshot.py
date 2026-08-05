"""Capture one immutable, byte-exact repository source view.

Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-8.2], [EVC-8.3.1]
Spec: docs/specs/05-backstitch-invariants.md [INV-11]
Plan: docs/plans/2026-07-15-agent-guided-evidence-cases-plan.md Slice 1

This module is the sole whole-capture lifecycle owner for an EVC operation.
Generic stable reads and stat identity live in ``filesystem_io``; this module
owns inventory, retry, immutable-view, and snapshot-identity policy. Callers
provide resolved semantic settings and get a frozen byte view whose identity
is independent of the clone's absolute path. Parsers and resolvers consume
:class:`RepositorySnapshot` and never reopen addressed source paths.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, NoReturn

from backstitch.canonical import canonical_json_bytes, canonical_repository_path
from backstitch.filesystem_io import file_stat_identity
from backstitch.operation_progress import OperationProgress
from backstitch.scan_exclusions import is_excluded

UnreadableClass = Literal["permission", "not_regular", "io"]
CatalogPathKind = Literal["directory", "regular_file"]
SnapshotProblemKind = Literal[
    "unsupported_platform",
    "invalid_root",
    "invalid_path",
    "symlink",
    "not_regular",
    "budget_exceeded",
    "snapshot_unstable",
]

# Capture capability facts before tests or instrumentation wrap ``os.open``.
# The operation still checks them before it traverses the repository.
_OPEN_SUPPORTS_DIR_FD = os.open in os.supports_dir_fd
_STAT_SUPPORTS_DIR_FD = os.stat in os.supports_dir_fd


class SnapshotCaptureError(Exception):
    """Structured fatal snapshot problem for the invocation-error projection."""

    def __init__(
        self,
        kind: SnapshotProblemKind,
        message: str,
        *,
        path: str | None = None,
        attempts: int | None = None,
        budget: str | None = None,
        limit: int | None = None,
        observed: int | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.path = path
        self.attempts = attempts
        self.budget = budget
        self.limit = limit
        self.observed = observed


class _TornCapture(Exception):
    """Internal signal: discard the complete attempt and retry from empty."""


@dataclass(frozen=True, slots=True)
class _NormalizedPath:
    native: str
    canonical: str


@dataclass(frozen=True, slots=True)
class SnapshotAlgorithms:
    """Exact algorithm epochs included in repository snapshot identity."""

    snapshot_algorithm_version: int
    obligation_algorithm_version: int
    discovery_algorithm_version: int
    packet_contract_version: int
    normalization_version: int

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")

    def to_identity(self) -> dict[str, int]:
        return {
            "snapshot_algorithm_version": self.snapshot_algorithm_version,
            "obligation_algorithm_version": self.obligation_algorithm_version,
            "discovery_algorithm_version": self.discovery_algorithm_version,
            "packet_contract_version": self.packet_contract_version,
            "normalization_version": self.normalization_version,
        }


@dataclass(frozen=True, slots=True)
class SnapshotSemanticConfig:
    """The complete [EVC-8.2] configuration identity projection.

    Presentation limits, deadlines, capture retries, output paths, policy, and
    provider settings intentionally have no fields here, so they cannot enter
    source identity by accident.
    """

    profile_name: str
    spec_roots: tuple[str, ...]
    plan_roots: tuple[str, ...]
    code_roots: tuple[str, ...]
    test_roots: tuple[str, ...]
    exclusions: tuple[str, ...]
    planned_spec_globs: tuple[str, ...]
    exploratory_spec_globs: tuple[str, ...]
    section_required_roles: tuple[str, ...]
    maximum_candidate_items: int
    maximum_catalog_items: int
    maximum_lexical_seeds: int
    maximum_snapshot_files: int
    maximum_file_bytes: int
    maximum_snapshot_bytes: int
    maximum_work_units: int
    maximum_packet_bytes: int
    maximum_packet_report_bytes: int
    static_neighbor_depth: int

    def __post_init__(self) -> None:
        if not self.profile_name.strip():
            raise ValueError("profile_name must be non-blank")
        if (
            not self.section_required_roles
            or self.section_required_roles[0] != "implementation"
            or len(set(self.section_required_roles)) != len(self.section_required_roles)
            or any(
                role not in ("implementation", "test")
                for role in self.section_required_roles
            )
        ):
            raise ValueError(
                "section_required_roles must be a unique ordered subset of "
                "implementation then test and contain implementation"
            )
        positive = (
            "maximum_candidate_items",
            "maximum_catalog_items",
            "maximum_lexical_seeds",
            "maximum_snapshot_files",
            "maximum_file_bytes",
            "maximum_snapshot_bytes",
            "maximum_work_units",
            "maximum_packet_bytes",
            "maximum_packet_report_bytes",
        )
        for name in positive:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.maximum_snapshot_bytes < self.maximum_file_bytes:
            raise ValueError("maximum_snapshot_bytes must be >= maximum_file_bytes")
        if self.maximum_packet_bytes < 16384:
            raise ValueError("maximum_packet_bytes must be >= 16384")
        if self.maximum_packet_report_bytes < 16384:
            raise ValueError("maximum_packet_report_bytes must be >= 16384")
        if (
            isinstance(self.static_neighbor_depth, bool)
            or not isinstance(self.static_neighbor_depth, int)
            or self.static_neighbor_depth not in range(4)
        ):
            raise ValueError("static_neighbor_depth must be in [0, 3]")


@dataclass(frozen=True, slots=True)
class FileStat:
    """The exact [EVC-8.2] identity tuple for one input file."""

    st_dev: int
    st_ino: int
    file_type_and_permission_mode: int
    st_size: int
    st_mtime_ns: int
    st_ctime_ns: int


@dataclass(frozen=True, slots=True)
class SnapshotFile:
    """One immutable readable or stably unreadable source record."""

    path: str
    state: Literal["readable", "unreadable"]
    raw_bytes: bytes | None
    raw_sha256: str | None
    error_class: UnreadableClass | None
    file_stat: FileStat

    def manifest_row(self) -> dict[str, str | None]:
        return {
            "path": self.path,
            "state": self.state,
            "raw_sha256": self.raw_sha256,
            "error_class": self.error_class,
        }


@dataclass(frozen=True, slots=True)
class SnapshotConfigSource:
    """One exact config layer retained by the bounded bootstrap loader."""

    path: Path
    raw_bytes: bytes
    raw_sha256: str
    stat_identity: tuple[int, ...]

    def __post_init__(self) -> None:
        if not self.path.is_absolute():
            raise ValueError("config source path must be absolute")
        if hashlib.sha256(self.raw_bytes).hexdigest() != self.raw_sha256:
            raise ValueError("config source raw_sha256 does not match raw_bytes")
        if len(self.stat_identity) != 6 or any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in self.stat_identity
        ):
            raise ValueError("config source stat_identity must contain six integers")


@dataclass(frozen=True, slots=True)
class SnapshotConfigInput:
    """Path-free config identity plus retained exact bytes."""

    ordinal: int
    raw_bytes: bytes
    raw_sha256: str

    def manifest_row(self) -> dict[str, int | str]:
        return {"ordinal": self.ordinal, "raw_sha256": self.raw_sha256}


@dataclass(frozen=True, slots=True)
class SnapshotPath:
    """One no-follow existence fact captured with the source inventory."""

    path: str
    kind: CatalogPathKind

    def identity_row(self) -> dict[str, str]:
        return {"path": self.path, "kind": self.kind}


@dataclass(frozen=True, slots=True)
class RepositorySnapshot:
    """Frozen source bytes and their canonical repository identity."""

    config_inputs: tuple[SnapshotConfigInput, ...]
    files: tuple[SnapshotFile, ...]
    path_catalog: tuple[SnapshotPath, ...]
    missing_roots: tuple[str, ...]
    catalog_sha256: str
    snapshot_hash: str
    _identity_bytes: bytes
    _contained_config_input_count: int = 0
    _contained_config_input_bytes: int = 0

    @property
    def file_count(self) -> int:
        return (
            len(self.files)
            + len(self.config_inputs)
            - self._contained_config_input_count
        )

    @property
    def byte_count(self) -> int:
        file_bytes = sum(
            len(row.raw_bytes) for row in self.files if row.raw_bytes is not None
        )
        config_bytes = sum(len(row.raw_bytes) for row in self.config_inputs)
        return file_bytes + config_bytes - self._contained_config_input_bytes

    @property
    def unreadable_count(self) -> int:
        return sum(row.state == "unreadable" for row in self.files)

    def file(self, path: str) -> SnapshotFile:
        normalized = _normalize_lookup_path(path)
        if normalized is None:
            raise KeyError(path)
        for row in self.files:
            if row.path == normalized:
                return row
        raise KeyError(path)

    def read_bytes(self, path: str) -> bytes:
        row = self.file(path)
        if row.raw_bytes is None:
            raise OSError(f"snapshot source is unreadable: {path}")
        return row.raw_bytes

    def path_exists(self, path: str) -> bool:
        """Return captured no-follow existence for a repository-relative path."""

        normalized = _normalize_lookup_path(path)
        return normalized is not None and any(
            row.path == normalized for row in self.path_catalog
        )

    def path_kind(self, path: str) -> CatalogPathKind | None:
        normalized = _normalize_lookup_path(path)
        if normalized is None:
            return None
        for row in self.path_catalog:
            if row.path == normalized:
                return row.kind
        return None

    def identity_document(self) -> dict[str, object]:
        value = json.loads(self._identity_bytes)
        assert isinstance(value, dict)
        return value


AfterInventoryHook = Callable[[int, Path], None]
AfterFileReadHook = Callable[[int, str, Path], None]
AdditionalPathsDeriver = Callable[[RepositorySnapshot], tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class SnapshotCaptureHooks:
    """Test-only mutation seams; production callers leave this unset."""

    after_initial_inventory: AfterInventoryHook | None = None
    after_file_read: AfterFileReadHook | None = None


def _platform_supported() -> bool:
    required_constants = ("O_NOFOLLOW", "O_DIRECTORY", "O_CLOEXEC")
    return (
        os.name == "posix"
        and all(hasattr(os, name) for name in required_constants)
        and _OPEN_SUPPORTS_DIR_FD
        and _STAT_SUPPORTS_DIR_FD
        and hasattr(os.stat_result, "st_mtime_ns")
        and hasattr(os.stat_result, "st_ctime_ns")
    )


def _require_platform() -> None:
    if not _platform_supported():
        raise SnapshotCaptureError(
            "unsupported_platform",
            "UNSUPPORTED_PLATFORM: POSIX descriptor-walk primitives are required",
        )


def _file_stat(value: os.stat_result) -> FileStat:
    try:
        mtime_ns = value.st_mtime_ns
        ctime_ns = value.st_ctime_ns
    except AttributeError:
        raise SnapshotCaptureError(
            "unsupported_platform",
            "UNSUPPORTED_PLATFORM: nanosecond file timestamps are required",
        ) from None
    return FileStat(
        st_dev=value.st_dev,
        st_ino=value.st_ino,
        file_type_and_permission_mode=(
            stat.S_IFMT(value.st_mode) | stat.S_IMODE(value.st_mode)
        ),
        st_size=value.st_size,
        st_mtime_ns=mtime_ns,
        st_ctime_ns=ctime_ns,
    )


def _read_descriptor_bounded(descriptor: int, limit: int) -> bytes:
    chunks: list[bytes] = []
    observed = 0
    while observed <= limit:
        chunk = os.read(descriptor, min(65_536, limit + 1 - observed))
        if not chunk:
            break
        chunks.append(chunk)
        observed += len(chunk)
    return b"".join(chunks)


def _validate_config_sources(
    config_sources: tuple[SnapshotConfigSource, ...],
    progress: OperationProgress | None,
) -> None:
    for source in config_sources:
        if progress is not None:
            progress.checkpoint("snapshot")
        try:
            before = source.path.lstat()
            if not stat.S_ISREG(before.st_mode):
                raise _TornCapture
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
            descriptor = os.open(source.path, flags)
            try:
                opened = os.fstat(descriptor)
                raw = _read_descriptor_bounded(descriptor, len(source.raw_bytes))
                after = os.fstat(descriptor)
            finally:
                os.close(descriptor)
            repeated = source.path.lstat()
        except OSError:
            raise _TornCapture from None
        if (
            file_stat_identity(before) != source.stat_identity
            or file_stat_identity(before) != file_stat_identity(opened)
            or file_stat_identity(opened) != file_stat_identity(after)
            or file_stat_identity(after) != file_stat_identity(repeated)
            or raw != source.raw_bytes
        ):
            raise _TornCapture
        if progress is not None:
            progress.checkpoint("snapshot")


def _normalize_address(
    repo_root: Path,
    raw: str,
    *,
    allow_root: bool = False,
    strip_trailing_slash: bool = False,
) -> _NormalizedPath:
    candidate_raw = raw.rstrip("/") if strip_trailing_slash else raw
    if allow_root and candidate_raw == ".":
        return _NormalizedPath(native=".", canonical=".")
    if not candidate_raw or "\x00" in candidate_raw or "\\" in candidate_raw:
        raise SnapshotCaptureError(
            "invalid_path", f"invalid repository path: {raw!r}", path=raw
        )
    candidate = Path(candidate_raw)
    raw_parts = candidate_raw.split("/")
    if candidate.is_absolute():
        raw_parts = raw_parts[1:]
    if any(part in ("", ".", "..") for part in raw_parts):
        raise SnapshotCaptureError(
            "invalid_path", f"invalid repository path: {raw!r}", path=raw
        )
    if candidate.is_absolute():
        try:
            relative = candidate.relative_to(repo_root)
        except ValueError:
            raise SnapshotCaptureError(
                "invalid_path",
                f"repository path is outside the repository root: {raw}",
                path=raw,
            ) from None
    else:
        relative = candidate
    if not relative.parts:
        raise SnapshotCaptureError(
            "invalid_path", f"invalid repository path: {raw!r}", path=raw
        )
    native = relative.as_posix()
    return _NormalizedPath(
        native=native,
        canonical=unicodedata.normalize("NFC", native),
    )


def _normalize_relative(repo_root: Path, raw: str) -> str:
    return _normalize_address(repo_root, raw).canonical


def _normalize_pattern(raw: str) -> str:
    if not raw or "\x00" in raw or "\\" in raw:
        raise SnapshotCaptureError(
            "invalid_path", f"invalid repository pattern: {raw!r}", path=raw
        )
    return unicodedata.normalize("NFC", raw)


def _normalize_lookup_path(raw: str) -> str | None:
    """Canonicalize one resolver lookup without touching the filesystem."""

    normalized = canonical_repository_path(raw)
    return None if normalized is None else normalized.canonical


def is_valid_repository_path(raw: str) -> bool:
    """Return whether one source token is a safe repo-relative lookup path."""

    return _normalize_lookup_path(raw) is not None


def _open_directory(root_fd: int, relative: str) -> int:
    current = os.dup(root_fd)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        for component in relative.split("/"):
            try:
                expected = os.stat(component, dir_fd=current, follow_symlinks=False)
            except FileNotFoundError:
                raise
            if stat.S_ISLNK(expected.st_mode):
                raise SnapshotCaptureError(
                    "symlink",
                    f"symlink is not allowed in repository input: {relative}",
                    path=relative,
                )
            if not stat.S_ISDIR(expected.st_mode):
                raise SnapshotCaptureError(
                    "not_regular",
                    f"non-directory component in repository input: {relative}",
                    path=relative,
                )
            try:
                next_fd = os.open(component, flags, dir_fd=current)
            except OSError as exc:
                if exc.errno in (
                    errno.ELOOP,
                    errno.EMLINK,
                    errno.ENOTDIR,
                    errno.EISDIR,
                ):
                    # The no-follow lstat above proved this was a directory.
                    # A different open result means this attempt was torn.
                    raise _TornCapture from None
                if exc.errno in (errno.ENOENT, errno.ESTALE):
                    raise _TornCapture from None
                raise SnapshotCaptureError(
                    "invalid_path",
                    f"cannot open repository input directory `{relative}`: {exc}",
                    path=relative,
                ) from None
            if _file_stat(os.fstat(next_fd)) != _file_stat(expected):
                os.close(next_fd)
                raise _TornCapture
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


def _raise_nonregular(path: str, mode: int) -> NoReturn:
    kind: SnapshotProblemKind = "symlink" if stat.S_ISLNK(mode) else "not_regular"
    noun = "symlink" if kind == "symlink" else "non-regular object"
    raise SnapshotCaptureError(
        kind, f"{noun} is not allowed in repository input: {path}", path=path
    )


def _catalog_kind(mode: int) -> CatalogPathKind | None:
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISREG(mode):
        return "regular_file"
    return None


@dataclass(frozen=True, slots=True)
class _SourceInput:
    native_path: str
    file_stat: FileStat


@dataclass(frozen=True, slots=True)
class _CatalogInput:
    native_path: str
    row: SnapshotPath
    file_stat: FileStat


def _normalized_collision(canonical: str, first: str, second: str) -> None:
    raise SnapshotCaptureError(
        "invalid_path",
        "repository paths collide after NFC normalization: "
        f"`{first}` and `{second}` -> `{canonical}`",
        path=canonical,
    )


def _record_catalog_path(
    rows: dict[str, _CatalogInput],
    address: _NormalizedPath,
    value: os.stat_result | FileStat,
    kind: CatalogPathKind,
) -> None:
    file_stat = value if isinstance(value, FileStat) else _file_stat(value)
    item = _CatalogInput(
        native_path=address.native,
        row=SnapshotPath(address.canonical, kind),
        file_stat=file_stat,
    )
    previous = rows.setdefault(address.canonical, item)
    if previous.native_path != address.native:
        _normalized_collision(address.canonical, previous.native_path, address.native)
    if previous != item:
        raise _TornCapture


def _record_source_path(
    rows: dict[str, _SourceInput],
    address: _NormalizedPath,
    value: FileStat,
) -> None:
    item = _SourceInput(address.native, value)
    previous = rows.setdefault(address.canonical, item)
    if previous.native_path != address.native:
        _normalized_collision(address.canonical, previous.native_path, address.native)
    if previous != item:
        raise _TornCapture


def _inventory_directory(
    root_fd: int,
    root_address: _NormalizedPath,
    suffixes: tuple[str, ...],
    exclusions: tuple[str, ...],
    source_rows: dict[str, _SourceInput],
    catalog_rows: dict[str, _CatalogInput],
    progress: OperationProgress | None,
) -> None:
    if progress is not None:
        progress.checkpoint("snapshot")
    directory_fd = _open_directory(root_fd, root_address.native)
    try:
        _record_catalog_path(
            catalog_rows, root_address, os.fstat(directory_fd), "directory"
        )
        _inventory_open_directory(
            directory_fd,
            root_address,
            suffixes,
            exclusions,
            source_rows,
            catalog_rows,
            progress,
        )
    finally:
        os.close(directory_fd)


def _inventory_open_directory(  # noqa: C901 approved [SC-17.1] RUFF-SUP-062 exception
    directory_fd: int,
    directory: _NormalizedPath,
    suffixes: tuple[str, ...],
    exclusions: tuple[str, ...],
    source_rows: dict[str, _SourceInput],
    catalog_rows: dict[str, _CatalogInput],
    progress: OperationProgress | None,
) -> None:
    if progress is not None:
        progress.checkpoint("snapshot")
    try:
        names = os.listdir(directory_fd)
    except OSError as exc:
        raise SnapshotCaptureError(
            "invalid_path",
            f"cannot enumerate repository input directory `{directory.canonical}`: {exc}",
            path=directory.canonical,
        ) from None

    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    for name in sorted(
        names, key=lambda value: (unicodedata.normalize("NFC", value), value)
    ):
        if progress is not None:
            progress.checkpoint("snapshot")
        if not name or name in (".", "..") or "\\" in name or "\x00" in name:
            raise SnapshotCaptureError(
                "invalid_path", f"invalid repository path component: {name!r}"
            )
        native_path = f"{directory.native}/{name}" if directory.native != "." else name
        canonical_name = unicodedata.normalize("NFC", name)
        canonical_path = (
            f"{directory.canonical}/{canonical_name}"
            if directory.canonical != "."
            else canonical_name
        )
        address = _NormalizedPath(native_path, canonical_path)
        if is_excluded(canonical_path, exclusions):
            continue
        try:
            before_os = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            raise _TornCapture from None
        except OSError as exc:
            raise SnapshotCaptureError(
                "invalid_path",
                f"cannot inspect repository input `{canonical_path}`: {exc}",
                path=canonical_path,
            ) from None
        before = _file_stat(before_os)
        kind = _catalog_kind(before_os.st_mode)
        if kind is None:
            if any(canonical_path.endswith(suffix) for suffix in suffixes):
                _raise_nonregular(canonical_path, before_os.st_mode)
            continue
        _record_catalog_path(catalog_rows, address, before, kind)
        if stat.S_ISDIR(before_os.st_mode):
            try:
                child_fd = os.open(name, flags, dir_fd=directory_fd)
            except FileNotFoundError:
                raise _TornCapture from None
            except OSError as exc:
                if exc.errno in (errno.ELOOP, errno.EMLINK, errno.ENOTDIR):
                    raise _TornCapture from None
                raise SnapshotCaptureError(
                    "invalid_path",
                    f"cannot open repository input directory `{canonical_path}`: {exc}",
                    path=canonical_path,
                ) from None
            try:
                if _file_stat(os.fstat(child_fd)) != before:
                    raise _TornCapture
                _inventory_open_directory(
                    child_fd,
                    address,
                    suffixes,
                    exclusions,
                    source_rows,
                    catalog_rows,
                    progress,
                )
            finally:
                os.close(child_fd)
            continue
        if not stat.S_ISREG(before_os.st_mode):
            continue
        if any(canonical_path.endswith(suffix) for suffix in suffixes):
            _record_source_path(source_rows, address, before)


@dataclass(slots=True)
class _Inventory:
    source_rows: dict[str, _SourceInput]
    catalog_rows: dict[str, _CatalogInput]
    missing_roots: tuple[str, ...]


def _inventory(  # noqa: C901 approved [SC-17.1] RUFF-SUP-061 exception
    root_fd: int,
    repo_root: Path,
    config: SnapshotSemanticConfig,
    config_paths: tuple[str, ...],
    additional_paths: tuple[str, ...],
    operational_exclusions: tuple[str, ...],
    progress: OperationProgress | None,
) -> _Inventory:
    exclusions = tuple(
        sorted(
            {
                _normalize_pattern(pattern)
                for pattern in (*config.exclusions, *operational_exclusions)
            }
        )
    )
    roots: dict[str, tuple[_NormalizedPath, set[str]]] = {}
    for raw in (*config.spec_roots, *config.plan_roots):
        address = _normalize_address(repo_root, raw)
        previous = roots.get(address.canonical)
        if previous is not None and previous[0].native != address.native:
            _normalized_collision(address.canonical, previous[0].native, address.native)
        roots.setdefault(address.canonical, (address, set()))[1].add(".md")
    for raw in (*config.code_roots, *config.test_roots):
        address = _normalize_address(repo_root, raw)
        previous = roots.get(address.canonical)
        if previous is not None and previous[0].native != address.native:
            _normalized_collision(address.canonical, previous[0].native, address.native)
        roots.setdefault(address.canonical, (address, set()))[1].add(".py")

    source_rows: dict[str, _SourceInput] = {}
    catalog_rows: dict[str, _CatalogInput] = {}
    missing_roots: list[str] = []
    _record_catalog_path(
        catalog_rows,
        _NormalizedPath(native=".", canonical="."),
        os.fstat(root_fd),
        "directory",
    )
    for canonical_root in sorted(roots):
        root_address, suffixes = roots[canonical_root]
        try:
            _inventory_directory(
                root_fd,
                root_address,
                tuple(sorted(suffixes)),
                exclusions,
                source_rows,
                catalog_rows,
                progress,
            )
        except FileNotFoundError:
            missing_roots.append(canonical_root)

    for raw in config_paths:
        if progress is not None:
            progress.checkpoint("snapshot")
        address = _normalize_address(repo_root, raw)
        try:
            value = _lstat_path(root_fd, address.native)
        except FileNotFoundError:
            raise SnapshotCaptureError(
                "invalid_path",
                f"included config file does not exist: {address.canonical}",
                path=address.canonical,
            ) from None
        if not stat.S_ISREG(value.st_mode):
            _raise_nonregular(address.canonical, value.st_mode)
        config_stat = _file_stat(value)
        _record_source_path(source_rows, address, config_stat)
        _record_catalog_path(catalog_rows, address, config_stat, "regular_file")

    for raw in additional_paths:
        if progress is not None:
            progress.checkpoint("snapshot")
        normalized = canonical_repository_path(raw)
        if normalized is None:
            raise SnapshotCaptureError(
                "invalid_path", f"invalid repository path: {raw!r}", path=raw
            )
        address = _NormalizedPath(
            native=normalized.native,
            canonical=normalized.canonical,
        )
        if address.canonical == ".":
            continue
        try:
            value = _lstat_path(root_fd, address.native)
        except FileNotFoundError:
            continue
        kind = _catalog_kind(value.st_mode)
        if kind is None:
            _raise_nonregular(address.canonical, value.st_mode)
        file_stat = _file_stat(value)
        _record_catalog_path(catalog_rows, address, file_stat, kind)
        if kind == "regular_file":
            _record_source_path(source_rows, address, file_stat)

    if len(source_rows) > config.maximum_snapshot_files:
        raise SnapshotCaptureError(
            "budget_exceeded",
            "snapshot file count exceeds maximum_snapshot_files",
            budget="snapshot_files",
            limit=config.maximum_snapshot_files,
            observed=len(source_rows),
        )
    if len(catalog_rows) > config.maximum_catalog_items:
        raise SnapshotCaptureError(
            "budget_exceeded",
            "snapshot path catalog exceeds maximum_catalog_items",
            budget="catalog_items",
            limit=config.maximum_catalog_items,
            observed=len(catalog_rows),
        )
    for path, source_input in source_rows.items():
        if source_input.file_stat.st_size > config.maximum_file_bytes:
            raise SnapshotCaptureError(
                "budget_exceeded",
                f"snapshot input exceeds maximum_file_bytes: {path}",
                path=path,
                budget="file_bytes",
                limit=config.maximum_file_bytes,
                observed=source_input.file_stat.st_size,
            )
    return _Inventory(source_rows, catalog_rows, tuple(missing_roots))


def _classify_open_error(exc: OSError) -> UnreadableClass:
    if exc.errno in (errno.EACCES, errno.EPERM):
        return "permission"
    if exc.errno in (errno.EISDIR, errno.ENOTDIR, errno.ELOOP, errno.ENXIO):
        return "not_regular"
    return "io"


def _open_file(root_fd: int, path: str) -> int:
    components = path.split("/")
    parent = "/".join(components[:-1])
    parent_fd = os.dup(root_fd) if not parent else _open_directory(root_fd, parent)
    flags = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        return os.open(components[-1], flags, dir_fd=parent_fd)
    finally:
        os.close(parent_fd)


def _validate_expected_lstat(root_fd: int, path: str, expected: FileStat) -> None:
    try:
        current = _file_stat(_lstat_path(root_fd, path))
    except (FileNotFoundError, SnapshotCaptureError):
        raise _TornCapture from None
    if current != expected:
        raise _TornCapture


def _bounded_read_attempt(  # noqa: C901 approved [SC-17.1] RUFF-SUP-059 exception
    root_fd: int,
    path: str,
    expected: FileStat,
    maximum_file_bytes: int,
    progress: OperationProgress | None,
) -> tuple[bytes | None, OSError | None]:
    if progress is not None:
        progress.checkpoint("snapshot")
    try:
        file_fd = _open_file(root_fd, path)
    except SnapshotCaptureError:
        raise _TornCapture from None
    except OSError as read_error:
        _validate_expected_lstat(root_fd, path, expected)
        return None, read_error

    try:
        try:
            first_fstat = _file_stat(os.fstat(file_fd))
            if first_fstat != expected:
                raise _TornCapture
            chunks: list[bytes] = []
            byte_count = 0
            while True:
                if progress is not None:
                    progress.checkpoint("snapshot")
                chunk = os.read(
                    file_fd, min(65536, maximum_file_bytes + 1 - byte_count)
                )
                if progress is not None:
                    progress.checkpoint("snapshot")
                if not chunk:
                    break
                byte_count += len(chunk)
                if byte_count > maximum_file_bytes:
                    # Inventory and the opening descriptor stat already proved
                    # this file was within budget. Extra bytes therefore mean
                    # the file changed during capture, even if a later stat is
                    # changed back before we can inspect it.
                    raise _TornCapture
                chunks.append(chunk)
            second_fstat = _file_stat(os.fstat(file_fd))
        except OSError as read_error:
            _validate_expected_lstat(root_fd, path, expected)
            return None, read_error
    finally:
        os.close(file_fd)
    _validate_expected_lstat(root_fd, path, expected)
    if first_fstat != second_fstat or second_fstat != expected:
        raise _TornCapture
    return b"".join(chunks), None


def _read_file(
    root_fd: int,
    path: str,
    expected: FileStat,
    maximum_file_bytes: int,
    progress: OperationProgress | None,
) -> tuple[bytes | None, UnreadableClass | None]:
    raw, first_error = _bounded_read_attempt(
        root_fd, path, expected, maximum_file_bytes, progress
    )
    if first_error is None:
        assert raw is not None
        return raw, None
    first_class = _classify_open_error(first_error)
    repeated_raw, second_error = _bounded_read_attempt(
        root_fd, path, expected, maximum_file_bytes, progress
    )
    if second_error is None or repeated_raw is not None:
        raise _TornCapture
    if _classify_open_error(second_error) != first_class:
        raise _TornCapture
    return None, first_class


def _normalized_identity_config(
    repo_root: Path, config: SnapshotSemanticConfig
) -> dict[str, object]:
    def roots(values: tuple[str, ...]) -> list[str]:
        return sorted({_normalize_relative(repo_root, value) for value in values})

    def patterns(values: tuple[str, ...]) -> list[str]:
        return sorted({_normalize_pattern(value) for value in values})

    return {
        "profile_name": config.profile_name,
        "spec_roots": roots(config.spec_roots),
        "plan_roots": roots(config.plan_roots),
        "code_roots": roots(config.code_roots),
        "test_roots": roots(config.test_roots),
        "exclusions": patterns(config.exclusions),
        "planned_spec_globs": patterns(config.planned_spec_globs),
        "exploratory_spec_globs": patterns(config.exploratory_spec_globs),
        "section_required_roles": sorted(set(config.section_required_roles)),
        "maximum_candidate_items": config.maximum_candidate_items,
        "maximum_catalog_items": config.maximum_catalog_items,
        "maximum_lexical_seeds": config.maximum_lexical_seeds,
        "maximum_snapshot_files": config.maximum_snapshot_files,
        "maximum_file_bytes": config.maximum_file_bytes,
        "maximum_snapshot_bytes": config.maximum_snapshot_bytes,
        "maximum_work_units": config.maximum_work_units,
        "maximum_packet_bytes": config.maximum_packet_bytes,
        "maximum_packet_report_bytes": config.maximum_packet_report_bytes,
        "static_neighbor_depth": config.static_neighbor_depth,
    }


def _capture_attempt(  # noqa: C901 approved [SC-17.1] RUFF-SUP-060 exception
    root_fd: int,
    repo_root: Path,
    config: SnapshotSemanticConfig,
    config_paths: tuple[str, ...],
    additional_paths: tuple[str, ...],
    operational_exclusions: tuple[str, ...],
    attempt: int,
    hooks: SnapshotCaptureHooks | None,
    progress: OperationProgress | None,
) -> tuple[tuple[SnapshotFile, ...], tuple[SnapshotPath, ...], tuple[str, ...]]:
    initial = _inventory(
        root_fd,
        repo_root,
        config,
        config_paths,
        additional_paths,
        operational_exclusions,
        progress,
    )
    if hooks is not None and hooks.after_initial_inventory is not None:
        hooks.after_initial_inventory(attempt, repo_root)

    rows: list[SnapshotFile] = []
    byte_count = 0
    source_paths = sorted(initial.source_rows)
    for index, path in enumerate(source_paths):
        source_input = initial.source_rows[path]
        if progress is not None:
            progress.advance(
                "snapshot",
                completed_work_units=index,
                total_work_units=len(source_paths),
                current_identity=path,
            )
        raw, error_class = _read_file(
            root_fd,
            source_input.native_path,
            source_input.file_stat,
            config.maximum_file_bytes,
            progress,
        )
        if hooks is not None and hooks.after_file_read is not None:
            hooks.after_file_read(attempt, path, repo_root)
        if progress is not None:
            progress.advance(
                "snapshot",
                completed_work_units=index + 1,
                total_work_units=len(source_paths),
                current_identity=path,
            )
        if raw is None:
            rows.append(
                SnapshotFile(
                    path=path,
                    state="unreadable",
                    raw_bytes=None,
                    raw_sha256=None,
                    error_class=error_class,
                    file_stat=source_input.file_stat,
                )
            )
            continue
        byte_count += len(raw)
        if byte_count > config.maximum_snapshot_bytes:
            raise SnapshotCaptureError(
                "budget_exceeded",
                "snapshot bytes exceed maximum_snapshot_bytes",
                budget="snapshot_bytes",
                limit=config.maximum_snapshot_bytes,
                observed=byte_count,
            )
        rows.append(
            SnapshotFile(
                path=path,
                state="readable",
                raw_bytes=raw,
                raw_sha256=hashlib.sha256(raw).hexdigest(),
                error_class=None,
                file_stat=source_input.file_stat,
            )
        )

    try:
        repeated = _inventory(
            root_fd,
            repo_root,
            config,
            config_paths,
            additional_paths,
            operational_exclusions,
            progress,
        )
    except SnapshotCaptureError as exc:
        if exc.kind in ("symlink", "not_regular", "budget_exceeded"):
            raise _TornCapture from None
        raise
    if repeated != initial:
        raise _TornCapture
    return (
        tuple(rows),
        tuple(initial.catalog_rows[path].row for path in sorted(initial.catalog_rows)),
        initial.missing_roots,
    )


def _catalog_hash(
    path_catalog: tuple[SnapshotPath, ...], missing_roots: tuple[str, ...]
) -> str:
    preimage = {
        "catalog_version": 1,
        "paths": [row.identity_row() for row in path_catalog],
        "missing_roots": list(missing_roots),
    }
    return hashlib.sha256(canonical_json_bytes(preimage)).hexdigest()


def capture_repository_snapshot(  # noqa: C901 approved [SC-17.1] RUFF-SUP-063 exception
    repo_root: Path,
    semantic_config: SnapshotSemanticConfig,
    algorithms: SnapshotAlgorithms,
    *,
    config_sources: tuple[SnapshotConfigSource, ...] = (),
    config_paths: tuple[str, ...] = (),
    additional_paths: tuple[str, ...] = (),
    operational_exclusions: tuple[str, ...] = (),
    capture_attempts: int = 3,
    hooks: SnapshotCaptureHooks | None = None,
    additional_paths_deriver: AdditionalPathsDeriver | None = None,
    progress: OperationProgress | None = None,
) -> RepositorySnapshot:
    """Capture one accepted source view or raise a structured fatal problem."""

    _require_platform()
    if (
        isinstance(capture_attempts, bool)
        or not isinstance(capture_attempts, int)
        or capture_attempts not in range(1, 11)
    ):
        raise ValueError("capture_attempts must be in [1, 10]")
    try:
        canonical_root = repo_root.resolve(strict=True)
    except OSError:
        raise SnapshotCaptureError(
            "invalid_root",
            f"repository root is not a directory: {repo_root}",
            path=str(repo_root),
        ) from None
    if not canonical_root.is_dir():
        raise SnapshotCaptureError(
            "invalid_root",
            f"repository root is not a directory: {repo_root}",
            path=str(repo_root),
        )

    config_inputs = tuple(
        SnapshotConfigInput(
            ordinal=ordinal,
            raw_bytes=source.raw_bytes,
            raw_sha256=source.raw_sha256,
        )
        for ordinal, source in enumerate(config_sources)
    )
    normalized_config_paths = frozenset(config_paths)
    contained_config_sources = tuple(
        source
        for source in config_sources
        if source.path.is_absolute()
        and source.path.is_relative_to(canonical_root)
        and source.path.relative_to(canonical_root).as_posix()
        in normalized_config_paths
    )
    external_config_sources = tuple(
        source for source in config_sources if source not in contained_config_sources
    )
    for source in external_config_sources:
        if len(source.raw_bytes) > semantic_config.maximum_file_bytes:
            raise SnapshotCaptureError(
                "budget_exceeded",
                "config input exceeds maximum_file_bytes",
                budget="file_bytes",
                limit=semantic_config.maximum_file_bytes,
                observed=len(source.raw_bytes),
            )

    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        root_fd = os.open(canonical_root, flags)
    except OSError as exc:
        raise SnapshotCaptureError(
            "invalid_root",
            f"cannot open repository root `{repo_root}`: {exc}",
            path=str(repo_root),
        ) from None
    if progress is not None:
        progress.advance("snapshot", current_identity=canonical_root.as_posix())
    try:
        converged_additional_paths = additional_paths
        for attempt in range(1, capture_attempts + 1):
            try:
                _validate_config_sources(config_sources, progress)
                files, path_catalog, missing_roots = _capture_attempt(
                    root_fd,
                    canonical_root,
                    semantic_config,
                    config_paths,
                    converged_additional_paths,
                    operational_exclusions,
                    attempt,
                    hooks,
                    progress,
                )
                _validate_config_sources(config_sources, progress)
            except _TornCapture:
                continue
            observed_file_count = len(files) + len(external_config_sources)
            if observed_file_count > semantic_config.maximum_snapshot_files:
                raise SnapshotCaptureError(
                    "budget_exceeded",
                    "snapshot file count exceeds maximum_snapshot_files",
                    budget="snapshot_files",
                    limit=semantic_config.maximum_snapshot_files,
                    observed=observed_file_count,
                )
            external_config_bytes = sum(
                len(source.raw_bytes) for source in external_config_sources
            )
            observed_byte_count = external_config_bytes + sum(
                len(row.raw_bytes) for row in files if row.raw_bytes is not None
            )
            if observed_byte_count > semantic_config.maximum_snapshot_bytes:
                raise SnapshotCaptureError(
                    "budget_exceeded",
                    "snapshot bytes exceed maximum_snapshot_bytes",
                    budget="snapshot_bytes",
                    limit=semantic_config.maximum_snapshot_bytes,
                    observed=observed_byte_count,
                )
            catalog_sha256 = _catalog_hash(path_catalog, missing_roots)
            identity = {
                "identity": "backstitch-repository-snapshot",
                "version": 1,
                "config_inputs": [row.manifest_row() for row in config_inputs],
                "files": [row.manifest_row() for row in files],
                "catalog_sha256": catalog_sha256,
                "missing_roots": list(missing_roots),
                "semantic_config": _normalized_identity_config(
                    canonical_root, semantic_config
                ),
                "algorithms": algorithms.to_identity(),
            }
            identity_bytes = canonical_json_bytes(identity)
            snapshot = RepositorySnapshot(
                config_inputs=config_inputs,
                files=files,
                path_catalog=path_catalog,
                missing_roots=missing_roots,
                catalog_sha256=catalog_sha256,
                snapshot_hash=hashlib.sha256(identity_bytes).hexdigest(),
                _identity_bytes=identity_bytes,
                _contained_config_input_count=len(contained_config_sources),
                _contained_config_input_bytes=sum(
                    len(source.raw_bytes) for source in contained_config_sources
                ),
            )
            if additional_paths_deriver is not None:
                derived_paths = additional_paths_deriver(snapshot)
                if derived_paths != converged_additional_paths:
                    converged_additional_paths = derived_paths
                    continue
            return snapshot
    finally:
        os.close(root_fd)

    raise SnapshotCaptureError(
        "snapshot_unstable",
        f"SNAPSHOT_UNSTABLE after {capture_attempts} capture attempts",
        attempts=capture_attempts,
    )
