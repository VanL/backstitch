"""Immutable semantic cache, single-flight locking, and audited cleanup.

This module owns the untrusted filesystem protocol. Callers provide validated
packets, offline inference identity inputs, and a lazy provider adapter.

Spec: docs/specs/06-semantic-gates.md [SEM-4]
"""

from __future__ import annotations

import base64
import errno
import hashlib
import json
import logging
import os
import secrets
import socket
import stat
import tempfile
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, TypeVar, cast

from backstitch.artifact_contracts import ValidatedSemanticPacket
from backstitch.canonical import canonical_json_bytes
from backstitch.grammar import is_sha256_hex
from backstitch.repository_snapshot import _file_stat_identity
from backstitch.semantic_evidence import (
    SemanticResultError,
    normalize_model_result,
    revalidate_canonical_result,
)
from backstitch.semantic_identity import (
    InferenceIdentity,
    ProviderIdentity,
    RequestIdentity,
    build_inference_identity,
)
from backstitch.semantic_packets import (
    model_request_bytes,
    semantic_packet_projection,
)
from backstitch.semantic_verification import (
    CanonicalVerificationResult,
    VerificationClaim,
    VerificationContractError,
    VerificationRequest,
    VerifyIdentity,
    load_canonical_verification_result,
    normalize_verifier_response,
    parse_verifier_response,
    validate_verification_links,
    verifier_request_bytes,
)

CacheMode = Literal["off", "read-write", "require"]
CacheSource = Literal["off", "hit", "miss"]
SemanticPacketKind = Literal["section", "invariant", "suppression"]
ProblemStage = Literal[
    "config",
    "input",
    "cache",
    "lock",
    "provider",
    "normalization",
    "completeness",
    "budget",
]
ProblemCode = Literal[
    "invalid_config",
    "invalid_input",
    "corrupt_cache",
    "stale_cache",
    "lock_timeout",
    "provider_failure",
    "malformed_result",
    "incomplete_result",
    "budget_exceeded",
]

_LOGGER = logging.getLogger(__name__)
_PublishedResult = TypeVar("_PublishedResult")

_POLL_INTERVAL_MAX_SECONDS = 1.0
# Provider failure remains the primary outcome. Owned-lock cleanup gets this
# many short guarded acquisitions before the lock is preserved for the next
# guarded participant or explicit ``cache cleanup-lock`` recovery.
_OWNED_FAILURE_CLEANUP_RETRY_LIMIT = 8
_LOCK_FIELDS = frozenset(
    {
        "schema_version",
        "object_type",
        "analysis_key",
        "owner_token",
        "pid",
        "host",
        "created_at_utc",
    }
)
_PROVENANCE_FIELDS = frozenset(
    {
        "adapter_id",
        "adapter_version",
        "plugin_version",
        "model_class",
        "provider_model_id",
        "provider_model_revision",
        "response_id",
        "input_tokens",
        "output_tokens",
    }
)
_RESULT_OBJECT_FIELDS = frozenset(
    {
        "schema_version",
        "object_type",
        "inference_contract",
        "analysis_key",
        "result",
        "provenance",
        "raw_response_sha256",
    }
)
_INFERENCE_CONTRACT_FIELDS = frozenset(
    {
        "analysis_contract_version",
        "packet_hash",
        "prompt",
        "provider",
        "request",
        "search_epoch",
    }
)
_PROMPT_FIELDS = frozenset({"id", "version", "sha256"})
_PROVIDER_FIELDS = frozenset(
    {
        "backend_id",
        "plugin_id",
        "model_id",
        "model_revision",
        "adapter_id",
        "adapter_version",
        "llm_distribution_version",
        "plugin_distribution_name",
        "plugin_distribution_version",
    }
)
_REQUEST_FIELDS = frozenset({"json_mode", "temperature", "seed", "max_tokens"})
_GUARD_FIELDS = frozenset({"schema_version", "object_type", "analysis_key"})
_PROCESS_GUARDS: dict[str, threading.Lock] = {}
_PROCESS_GUARDS_LOCK = threading.Lock()
_PENDING_OWNED_CLEANUPS: dict[str, _PendingOwnedCleanup] = {}
_PENDING_OWNED_CLEANUPS_LOCK = threading.Lock()
_VERIFY_RESULT_OBJECT_FIELDS = frozenset(
    {
        "schema_version",
        "object_type",
        "inference_contract",
        "verify_key",
        "result",
        "provenance",
        "raw_response_sha256",
    }
)
_VERIFY_LOCK_FIELDS = frozenset(
    {
        "schema_version",
        "object_type",
        "verify_key",
        "owner_token",
        "pid",
        "host",
        "created_at_utc",
    }
)
_VERIFY_GUARD_FIELDS = frozenset({"schema_version", "object_type", "verify_key"})


class CacheProtocolError(ValueError):
    """The cache filesystem or one of its untrusted objects is invalid."""


@dataclass(frozen=True, slots=True)
class _PendingOwnedCleanup:
    cache_path: Path
    key: str
    expected_lock: bytes
    verifier: bool


@dataclass(frozen=True, slots=True)
class SemanticProvenance:
    adapter_id: str
    adapter_version: int
    plugin_version: str | None
    model_class: str | None
    provider_model_id: str | None
    provider_model_revision: str | None
    response_id: str | None
    input_tokens: int | None
    output_tokens: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.adapter_id, str) or not self.adapter_id.strip():
            raise ValueError("provenance adapter_id must be nonblank")
        if (
            isinstance(self.adapter_version, bool)
            or not isinstance(self.adapter_version, int)
            or self.adapter_version < 1
        ):
            raise ValueError("provenance adapter_version must be positive")
        for string_value in (
            self.plugin_version,
            self.model_class,
            self.provider_model_id,
            self.provider_model_revision,
            self.response_id,
        ):
            if string_value is not None and (
                not isinstance(string_value, str) or not string_value.strip()
            ):
                raise ValueError("non-null provenance strings must be nonblank")
        for token_count in (self.input_tokens, self.output_tokens):
            if token_count is not None and (
                isinstance(token_count, bool)
                or not isinstance(token_count, int)
                or token_count < 0
            ):
                raise ValueError("provenance token counts must be nonnegative integers")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ProviderCallResult:
    raw_response: str
    provenance: SemanticProvenance

    def __post_init__(self) -> None:
        if not isinstance(self.raw_response, str):
            raise ValueError("raw provider response must be a string")
        if not isinstance(self.provenance, SemanticProvenance):
            raise ValueError("provider result requires trusted provenance")


ProviderAdapter = Callable[[str], ProviderCallResult]
AdapterFactory = Callable[[], ProviderAdapter]


@dataclass(slots=True)
class ProviderCallBudget:
    """One run-wide atomic provider-call ceiling shared by all workers."""

    maximum_calls: int
    _reserved_calls: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        if (
            isinstance(self.maximum_calls, bool)
            or not isinstance(self.maximum_calls, int)
            or self.maximum_calls < 0
        ):
            raise ValueError("provider-call budget must be a nonnegative integer")

    def reserve(self) -> bool:
        with self._lock:
            if self._reserved_calls >= self.maximum_calls:
                return False
            self._reserved_calls += 1
            return True

    def release(self) -> None:
        with self._lock:
            if self._reserved_calls <= 0:
                raise RuntimeError("provider-call budget release without reservation")
            self._reserved_calls -= 1


@dataclass(frozen=True, slots=True)
class SemanticProblem:
    packet_id: str | None
    stage: ProblemStage
    code: ProblemCode
    message: str


@dataclass(frozen=True, slots=True)
class SemanticCacheRun:
    _canonical_results: tuple[bytes, ...]
    problems: tuple[SemanticProblem, ...]
    result_jsonl: bytes
    cache_hits: int
    cache_misses: int
    provider_calls: int
    kind_counts: dict[str, dict[str, int]] = field(
        default_factory=lambda: _empty_analyzer_kind_counts()
    )

    @property
    def results(self) -> tuple[dict[str, Any], ...]:
        rows: list[dict[str, Any]] = []
        for encoded in self._canonical_results:
            row = json.loads(encoded)
            assert isinstance(row, dict)
            rows.append(row)
        return tuple(rows)


@dataclass(frozen=True, slots=True)
class SemanticCacheInspection:
    """Read-only preflight of cache hits and planned provider misses."""

    problems: tuple[SemanticProblem, ...]
    planned_hits: int
    planned_misses: int
    planned_miss_packet_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CleanupResult:
    audit_path: Path


@dataclass(frozen=True, slots=True)
class VerificationWork:
    packet: dict[str, Any]
    claim: VerificationClaim
    request: VerificationRequest
    identity: VerifyIdentity
    base_search_epoch: str
    effective_search_epoch: str


@dataclass(frozen=True, slots=True)
class VerificationCacheRun:
    results: tuple[CanonicalVerificationResult, ...]
    problems: tuple[SemanticProblem, ...]
    cache_hits: int
    cache_misses: int
    provider_calls: int


@dataclass(frozen=True, slots=True)
class VerificationCacheInspection:
    problems: tuple[SemanticProblem, ...]
    planned_hits: int
    planned_misses: int
    planned_miss_verify_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Resolution:
    row: dict[str, Any]
    source: CacheSource


def _empty_packet_kind_counts() -> dict[str, int]:
    return {"section": 0, "invariant": 0, "suppression": 0}


def _empty_analyzer_kind_counts() -> dict[str, dict[str, int]]:
    return {
        "cache_hits": _empty_packet_kind_counts(),
        "cache_misses": _empty_packet_kind_counts(),
        "provider_calls": _empty_packet_kind_counts(),
    }


class _AnalysisFailure(Exception):
    def __init__(
        self,
        stage: ProblemStage,
        code: ProblemCode,
        message: str,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.code = code
        self.message = message


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _format_utc(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("timestamp must be UTC")
    return (
        value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )


def _parse_canonical_utc(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("timestamp is not canonical UTC RFC 3339")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise ValueError("timestamp is not canonical UTC RFC 3339") from None
    if _format_utc(parsed) != value:
        raise ValueError("timestamp is not canonical UTC RFC 3339")
    return parsed


def _path_exists(path: Path) -> bool:
    return os.path.lexists(path)


def _freeze_inference_identities(
    rows: tuple[dict[str, Any], ...],
    provider: ProviderIdentity,
    request: RequestIdentity,
    search_epoch: str,
    identities: Iterable[InferenceIdentity] | None,
) -> tuple[InferenceIdentity, ...]:
    frozen = (
        tuple(
            build_inference_identity(
                row,
                provider,
                request,
                search_epoch=search_epoch,
            )
            for row in rows
        )
        if identities is None
        else tuple(identities)
    )
    if len(frozen) != len(rows):
        raise ValueError("frozen inference identity count does not match packets")
    expected_provider = asdict(provider)
    expected_request = asdict(request)
    for row, identity in zip(rows, frozen, strict=True):
        contract = identity.contract
        if (
            contract.get("packet_hash") != row["packet_hash"]
            or contract.get("provider") != expected_provider
            or contract.get("request") != expected_request
            or contract.get("search_epoch") != search_epoch
        ):
            raise ValueError("frozen inference identity does not match packet request")
    return frozen


def _load_published_result_after_lock_timeout(
    failure: _AnalysisFailure,
    *,
    result_path: Path,
    load_result: Callable[[], _PublishedResult],
) -> _PublishedResult | None:
    """Adopt only a fully validated result published during lock contention."""

    if (
        failure.stage != "lock"
        or failure.code != "lock_timeout"
        or not _path_exists(result_path)
    ):
        return None
    return load_result()


def _lstat_identity(value: os.stat_result) -> tuple[int, ...]:
    return _file_stat_identity(value)


def _read_regular_bytes(path: Path) -> tuple[bytes, os.stat_result]:
    try:
        before = path.lstat()
    except FileNotFoundError:
        raise
    if not stat.S_ISREG(before.st_mode):
        raise CacheProtocolError(f"cache path is not a regular file: {path}")
    try:
        raw = path.read_bytes()
        after = path.lstat()
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise CacheProtocolError(f"cannot read cache object {path}: {exc}") from exc
    if _lstat_identity(before) != _lstat_identity(after):
        raise CacheProtocolError(f"cache object changed while being read: {path}")
    return raw, after


def _read_canonical_object(path: Path) -> tuple[dict[str, Any], bytes]:
    raw, _ = _read_regular_bytes(path)
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise CacheProtocolError(
            f"cache object is not canonical JSON: {path}"
        ) from None
    if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
        raise CacheProtocolError(f"cache object is not canonical JSON: {path}")
    return value, raw


def _ensure_cache_directory(path: Path) -> None:
    existing = path
    while not _path_exists(existing) and existing != existing.parent:
        existing = existing.parent
    if _path_exists(existing) and existing.is_symlink():
        raise CacheProtocolError(f"cache path crosses a symlink: {existing}")
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise CacheProtocolError(
            f"cannot create cache directory {path}: {exc}"
        ) from exc
    if path.is_symlink() or not path.is_dir():
        raise CacheProtocolError(f"cache directory is not a real directory: {path}")


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        if exc.errno in (errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP):
            return
        raise CacheProtocolError(
            f"cannot open cache directory for fsync: {path}"
        ) from exc
    try:
        try:
            os.fsync(descriptor)
        except OSError as exc:
            if exc.errno not in (errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP):
                raise CacheProtocolError(
                    f"cannot fsync cache directory: {path}"
                ) from exc
    finally:
        os.close(descriptor)


def _link_candidate(path: Path, content: bytes) -> bool:
    _ensure_cache_directory(path.parent)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.chmod(temporary, 0o600)
        handle = os.fdopen(descriptor, "wb", closefd=True)
        descriptor = -1
        with handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        published: bool
        try:
            os.link(temporary, path)
            published = True
        except FileExistsError:
            published = False
        except OSError as exc:
            raise CacheProtocolError(
                f"cache does not support immutable hard-link publication: {path}"
            ) from exc
        temporary.unlink()
        _fsync_directory(path.parent)
        return published
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _publish_immutable(path: Path, content: bytes) -> bool:
    published = _link_candidate(path, content)
    if published:
        return True
    existing, _ = _read_regular_bytes(path)
    if existing != content:
        raise CacheProtocolError(f"conflicting immutable cache object: {path}")
    return False


def _packet_object(packet: dict[str, Any]) -> dict[str, Any]:
    projection = semantic_packet_projection(packet)
    return {
        "schema_version": 1,
        "object_type": "semantic-packet",
        **projection,
        "packet_hash": packet["packet_hash"],
    }


def _safe_cache_child(
    cache_path: Path, directories: tuple[str, ...], filename: str
) -> Path:
    current = cache_path
    if _path_exists(current) and current.is_symlink():
        raise CacheProtocolError(f"cache path crosses a symlink: {current}")
    for directory in directories:
        current /= directory
        if _path_exists(current) and current.is_symlink():
            raise CacheProtocolError(f"cache path crosses a symlink: {current}")
    return current / filename


def _validate_inference_contract_shape(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _INFERENCE_CONTRACT_FIELDS:
        raise CacheProtocolError("cached inference contract has invalid closed shape")
    version = value.get("analysis_contract_version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise CacheProtocolError("cached inference contract version is invalid")
    packet_hash = value.get("packet_hash")
    if not is_sha256_hex(packet_hash):
        raise CacheProtocolError("cached inference packet hash is invalid")
    search_epoch = value.get("search_epoch")
    if not isinstance(search_epoch, str) or not search_epoch.strip():
        raise CacheProtocolError("cached inference search epoch is invalid")

    prompt = value.get("prompt")
    if not isinstance(prompt, dict) or set(prompt) != _PROMPT_FIELDS:
        raise CacheProtocolError("cached inference prompt has invalid closed shape")
    prompt_version = prompt.get("version")
    if (
        not isinstance(prompt.get("id"), str)
        or not prompt["id"].strip()
        or isinstance(prompt_version, bool)
        or not isinstance(prompt_version, int)
        or prompt_version < 1
        or not is_sha256_hex(prompt.get("sha256"))
    ):
        raise CacheProtocolError("cached inference prompt is invalid")

    provider = value.get("provider")
    if not isinstance(provider, dict) or set(provider) != _PROVIDER_FIELDS:
        raise CacheProtocolError("cached inference provider has invalid closed shape")
    try:
        parsed_provider = ProviderIdentity(**provider)
    except (TypeError, ValueError) as exc:
        raise CacheProtocolError(
            f"cached inference provider is invalid: {exc}"
        ) from exc
    cached_provider_fields = (
        parsed_provider.backend_id,
        parsed_provider.plugin_id,
        parsed_provider.plugin_distribution_name,
        parsed_provider.model_id,
        parsed_provider.model_revision,
    )
    if any(not item.strip() for item in cached_provider_fields):
        raise CacheProtocolError(
            "cached inference provider identity contains blank cached-mode fields"
        )

    request = value.get("request")
    if not isinstance(request, dict) or set(request) != _REQUEST_FIELDS:
        raise CacheProtocolError("cached inference request has invalid closed shape")
    try:
        RequestIdentity(**request)
    except (TypeError, ValueError) as exc:
        raise CacheProtocolError(f"cached inference request is invalid: {exc}") from exc
    return value


def _packet_path(cache_path: Path, packet_hash: str) -> Path:
    return _safe_cache_child(cache_path, ("packets",), f"{packet_hash}.json")


def _result_path(cache_path: Path, analysis_key: str) -> Path:
    return _safe_cache_child(cache_path, ("results",), f"{analysis_key}.json")


def _lock_path(cache_path: Path, analysis_key: str) -> Path:
    return _safe_cache_child(cache_path, ("locks",), f"{analysis_key}.lock")


def _guard_path(cache_path: Path, analysis_key: str) -> Path:
    return _safe_cache_child(cache_path, ("guards",), f"{analysis_key}.guard")


def _guard_bytes(analysis_key: str) -> bytes:
    return canonical_json_bytes(
        {
            "schema_version": 1,
            "object_type": "semantic-lock-guard",
            "analysis_key": analysis_key,
        }
    )


def _process_guard(path: Path) -> threading.Lock:
    key = str(path)
    with _PROCESS_GUARDS_LOCK:
        return _PROCESS_GUARDS.setdefault(key, threading.Lock())


def _try_lock_guard(handle: Any) -> bool:
    if os.name == "nt":
        import msvcrt

        windows_lock = cast(Any, msvcrt)
        handle.seek(0)
        try:
            windows_lock.locking(handle.fileno(), windows_lock.LK_NBLCK, 1)
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK) or getattr(
                exc, "winerror", None
            ) in (33, 36):
                return False
            raise CacheProtocolError(
                f"cannot lock semantic cache guard: {exc}"
            ) from exc
        return True

    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    except OSError as exc:
        raise CacheProtocolError(f"cannot lock semantic cache guard: {exc}") from exc
    return True


def _unlock_guard(handle: Any) -> None:
    if os.name == "nt":
        import msvcrt

        windows_lock = cast(Any, msvcrt)
        handle.seek(0)
        try:
            windows_lock.locking(handle.fileno(), windows_lock.LK_UNLCK, 1)
        except OSError as exc:
            raise CacheProtocolError(
                f"cannot unlock semantic cache guard: {exc}"
            ) from exc
        return

    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError as exc:
        raise CacheProtocolError(f"cannot unlock semantic cache guard: {exc}") from exc


def _guard_wait_failure(timeout_seconds: float | None) -> Exception:
    if timeout_seconds is None:
        return CacheProtocolError("semantic cache guard is busy")
    return _AnalysisFailure(
        "lock", "lock_timeout", "timed out waiting for semantic cache guard"
    )


def _remember_owned_cleanup(guard_path: Path, cleanup: _PendingOwnedCleanup) -> None:
    with _PENDING_OWNED_CLEANUPS_LOCK:
        _PENDING_OWNED_CLEANUPS[str(guard_path)] = cleanup


def _owned_cleanup_is_pending(guard_path: Path) -> bool:
    with _PENDING_OWNED_CLEANUPS_LOCK:
        return str(guard_path) in _PENDING_OWNED_CLEANUPS


def _forget_owned_cleanup(guard_path: Path) -> None:
    with _PENDING_OWNED_CLEANUPS_LOCK:
        _PENDING_OWNED_CLEANUPS.pop(str(guard_path), None)


def _drain_owned_cleanup_under_guard(guard_path: Path) -> None:
    """Finish a deferred unchanged-owner cleanup while its OS guard is held."""

    with _PENDING_OWNED_CLEANUPS_LOCK:
        cleanup = _PENDING_OWNED_CLEANUPS.get(str(guard_path))
    if cleanup is None:
        return
    lock_path = (
        _verify_lock_path(cleanup.cache_path, cleanup.key)
        if cleanup.verifier
        else _lock_path(cleanup.cache_path, cleanup.key)
    )
    try:
        if cleanup.verifier:
            current = _read_verify_lock(lock_path, cleanup.key)
        else:
            _, current = _read_valid_lock(lock_path, cleanup.key)
    except FileNotFoundError:
        _forget_owned_cleanup(guard_path)
        return
    except CacheProtocolError:
        # Leave malformed bytes to the ordinary untrusted-cache path. Failure
        # cleanup is best-effort and must not change the primary provider error.
        return
    if current != cleanup.expected_lock:
        # The failed caller no longer owns this path and has no removal authority.
        _forget_owned_cleanup(guard_path)
        return
    try:
        if cleanup.verifier:
            _remove_verify_lock(lock_path, cleanup.key, cleanup.expected_lock)
        else:
            _remove_owned_lock(lock_path, cleanup.key, cleanup.expected_lock)
    except CacheProtocolError:
        return
    _forget_owned_cleanup(guard_path)


@contextmanager
def _semantic_guard(
    cache_path: Path,
    analysis_key: str,
    *,
    timeout_seconds: float | None,
    poll_interval_seconds: float,
    drain_owned_cleanup: bool = True,
) -> Iterator[None]:
    path = _guard_path(cache_path, analysis_key)
    expected = _guard_bytes(analysis_key)
    _publish_immutable(path, expected)
    value, actual = _read_canonical_object(path)
    if set(value) != _GUARD_FIELDS or actual != expected:
        raise CacheProtocolError("semantic cache guard has invalid closed shape")

    process_guard = _process_guard(path)
    deadline = (
        time.monotonic() + timeout_seconds if timeout_seconds is not None else None
    )
    acquired_process = False
    while not acquired_process:
        acquired_process = process_guard.acquire(blocking=False)
        if acquired_process:
            break
        if deadline is None:
            raise _guard_wait_failure(timeout_seconds)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _guard_wait_failure(timeout_seconds)
        time.sleep(min(poll_interval_seconds, remaining))

    try:
        try:
            handle = path.open("r+b", buffering=0)
        except OSError as exc:
            raise CacheProtocolError(
                f"cannot open semantic cache guard: {exc}"
            ) from exc
        acquired_os = False
        try:
            while not acquired_os:
                acquired_os = _try_lock_guard(handle)
                if acquired_os:
                    break
                if deadline is None:
                    raise _guard_wait_failure(timeout_seconds)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise _guard_wait_failure(timeout_seconds)
                time.sleep(min(poll_interval_seconds, remaining))
            if drain_owned_cleanup:
                _drain_owned_cleanup_under_guard(path)
            yield
        finally:
            try:
                if acquired_os:
                    _unlock_guard(handle)
            finally:
                handle.close()
    finally:
        process_guard.release()


def _validate_packet_object(path: Path, packet: dict[str, Any]) -> None:
    expected = canonical_json_bytes(_packet_object(packet))
    _, actual = _read_canonical_object(path)
    if actual != expected:
        raise CacheProtocolError(f"cached packet does not match packet hash: {path}")


def _validate_provenance(
    value: object, provider: ProviderIdentity
) -> SemanticProvenance:
    if not isinstance(value, dict) or set(value) != _PROVENANCE_FIELDS:
        raise CacheProtocolError("cached result has invalid provenance shape")
    try:
        provenance = SemanticProvenance(**value)
    except (TypeError, ValueError) as exc:
        raise CacheProtocolError(
            f"cached result has invalid provenance: {exc}"
        ) from exc
    expected_plugin = provider.plugin_distribution_version or None
    if (
        provenance.adapter_id != provider.adapter_id
        or provenance.adapter_version != provider.adapter_version
        or provenance.plugin_version != expected_plugin
    ):
        raise _AnalysisFailure(
            "cache", "stale_cache", "cached result provenance is stale"
        )
    return provenance


def _load_hit(
    cache_path: Path,
    packet: dict[str, Any],
    identity: InferenceIdentity,
    provider: ProviderIdentity,
) -> dict[str, Any]:
    packet_path = _packet_path(cache_path, packet["packet_hash"])
    result_path = _result_path(cache_path, identity.analysis_key)
    if not _path_exists(packet_path):
        raise CacheProtocolError("cached result exists without its packet object")
    _validate_packet_object(packet_path, packet)
    value, _ = _read_canonical_object(result_path)
    if set(value) != _RESULT_OBJECT_FIELDS:
        raise CacheProtocolError("cached result object has unknown or missing fields")
    schema_version = value.get("schema_version")
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version != 1
        or value.get("object_type") != "semantic-result"
    ):
        raise CacheProtocolError("cached result object has invalid type or version")
    cached_analysis_key = value.get("analysis_key")
    if not is_sha256_hex(cached_analysis_key):
        raise CacheProtocolError("cached result analysis key is invalid")
    if cached_analysis_key != identity.analysis_key:
        raise _AnalysisFailure("cache", "stale_cache", "cached analysis key is stale")
    contract = _validate_inference_contract_shape(value.get("inference_contract"))
    recomputed = hashlib.sha256(canonical_json_bytes(contract)).hexdigest()
    if recomputed != identity.analysis_key or contract != identity.contract:
        raise _AnalysisFailure(
            "cache", "stale_cache", "cached inference contract is stale"
        )
    _validate_provenance(value.get("provenance"), provider)
    raw_hash = value.get("raw_response_sha256")
    if not is_sha256_hex(raw_hash):
        raise CacheProtocolError("cached raw response hash is invalid")
    try:
        result = revalidate_canonical_result(
            packet, value.get("result"), analysis_key=identity.analysis_key
        )
    except SemanticResultError as exc:
        raise CacheProtocolError(f"cached canonical result is invalid: {exc}") from exc
    return result.to_row()


def _validate_lock(value: object, analysis_key: str) -> None:
    if not isinstance(value, dict) or set(value) != _LOCK_FIELDS:
        raise CacheProtocolError("semantic lock has invalid closed shape")
    schema_version = value.get("schema_version")
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version != 1
        or value.get("object_type") != "semantic-lock"
    ):
        raise CacheProtocolError("semantic lock has invalid type or version")
    lock_analysis_key = value.get("analysis_key")
    if not is_sha256_hex(lock_analysis_key):
        raise CacheProtocolError("semantic lock analysis key is invalid")
    if lock_analysis_key != analysis_key:
        raise CacheProtocolError("semantic lock analysis key does not match its path")
    owner_token = value.get("owner_token")
    pid = value.get("pid")
    host = value.get("host")
    if not is_sha256_hex(owner_token):
        raise CacheProtocolError("semantic lock owner token is invalid")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid < 1:
        raise CacheProtocolError("semantic lock pid is invalid")
    if not isinstance(host, str) or not host.strip():
        raise CacheProtocolError("semantic lock host is invalid")
    try:
        _parse_canonical_utc(value.get("created_at_utc"))
    except ValueError as exc:
        raise CacheProtocolError(f"semantic lock timestamp is invalid: {exc}") from exc


def _read_valid_lock(path: Path, analysis_key: str) -> tuple[dict[str, Any], bytes]:
    value, raw = _read_canonical_object(path)
    _validate_lock(value, analysis_key)
    return value, raw


def _remove_owned_lock(path: Path, analysis_key: str, expected: bytes) -> None:
    try:
        _, current = _read_valid_lock(path, analysis_key)
    except FileNotFoundError as exc:
        raise CacheProtocolError("owned semantic lock disappeared") from exc
    if current != expected:
        raise CacheProtocolError("semantic lock ownership changed")
    try:
        path.unlink()
    except OSError as exc:
        raise CacheProtocolError(f"cannot remove owned semantic lock: {exc}") from exc
    _fsync_directory(path.parent)


def _new_lock(analysis_key: str) -> tuple[dict[str, Any], bytes]:
    value = {
        "schema_version": 1,
        "object_type": "semantic-lock",
        "analysis_key": analysis_key,
        "owner_token": secrets.token_hex(32),
        "pid": os.getpid(),
        "host": socket.gethostname().strip() or "unknown-host",
        "created_at_utc": _format_utc(_utc_now()),
    }
    return value, canonical_json_bytes(value)


def _retry_owned_failure_cleanup(
    *,
    cache_path: Path,
    key: str,
    expected_lock: bytes,
    verifier: bool,
    poll_interval_seconds: float,
) -> bool:
    """Try a fixed number of guarded cleanups, then defer to the next guard."""

    guard_path = (
        _verify_guard_path(cache_path, key)
        if verifier
        else _guard_path(cache_path, key)
    )
    _remember_owned_cleanup(
        guard_path,
        _PendingOwnedCleanup(cache_path, key, expected_lock, verifier),
    )
    guard = _verify_guard if verifier else _semantic_guard
    for _ in range(_OWNED_FAILURE_CLEANUP_RETRY_LIMIT):
        try:
            with guard(
                cache_path,
                key,
                timeout_seconds=poll_interval_seconds,
                poll_interval_seconds=poll_interval_seconds,
            ):
                pass
        except Exception:  # noqa: BLE001 - cleanup never displaces primary failure
            pass
        if not _owned_cleanup_is_pending(guard_path):
            return True
    return False


def _log_cleanup_guidance(*, key: str, verifier: bool) -> None:
    _LOGGER.warning(
        "owned %s cache lock %s was preserved after %d guarded cleanup "
        "attempts; run backstitch cache cleanup-lock when the lock is stale",
        "verifier" if verifier else "analyzer",
        key,
        _OWNED_FAILURE_CLEANUP_RETRY_LIMIT,
    )


def _wait_for_result(
    *,
    cache_path: Path,
    packet: dict[str, Any],
    identity: InferenceIdentity,
    provider: ProviderIdentity,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    lock_path = _lock_path(cache_path, identity.analysis_key)
    result_path = _result_path(cache_path, identity.analysis_key)
    deadline = time.monotonic() + timeout_seconds
    while True:
        if _path_exists(result_path):
            return _load_hit(cache_path, packet, identity, provider)
        if _path_exists(lock_path):
            remaining = deadline - time.monotonic()
            if remaining > 0:
                try:
                    with _semantic_guard(
                        cache_path,
                        identity.analysis_key,
                        timeout_seconds=remaining,
                        poll_interval_seconds=poll_interval_seconds,
                    ):
                        if _path_exists(lock_path):
                            _read_valid_lock(lock_path, identity.analysis_key)
                except _AnalysisFailure as exc:
                    published = _load_published_result_after_lock_timeout(
                        exc,
                        result_path=result_path,
                        load_result=lambda: _load_hit(
                            cache_path, packet, identity, provider
                        ),
                    )
                    if published is not None:
                        return published
                    raise
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            if _path_exists(result_path):
                return _load_hit(cache_path, packet, identity, provider)
            raise _AnalysisFailure(
                "lock", "lock_timeout", "timed out waiting for semantic cache owner"
            )
        time.sleep(min(poll_interval_seconds, remaining))


def _normalize_provider_result(
    packet: dict[str, Any],
    identity: InferenceIdentity,
    response: ProviderCallResult,
    provider: ProviderIdentity,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if (
        response.provenance.adapter_id != provider.adapter_id
        or response.provenance.adapter_version != provider.adapter_version
        or response.provenance.plugin_version
        != (provider.plugin_distribution_version or None)
    ):
        raise _AnalysisFailure(
            "normalization",
            "malformed_result",
            "provider provenance does not match the inference contract",
        )
    try:
        model_row = json.loads(response.raw_response)
    except json.JSONDecodeError:
        raise _AnalysisFailure(
            "normalization", "malformed_result", "model output is not valid JSON"
        ) from None
    try:
        canonical = normalize_model_result(
            packet, model_row, analysis_key=identity.analysis_key
        )
    except SemanticResultError as exc:
        raise _AnalysisFailure(
            "normalization", "malformed_result", f"model output invalid: {exc}"
        ) from exc
    row = canonical.to_row()
    result_object = {
        "schema_version": 1,
        "object_type": "semantic-result",
        "inference_contract": identity.contract,
        "analysis_key": identity.analysis_key,
        "result": row,
        "provenance": response.provenance.to_dict(),
        "raw_response_sha256": hashlib.sha256(
            response.raw_response.encode("utf-8")
        ).hexdigest(),
    }
    return row, result_object


def _resolve_cached_result(
    *,
    cache_path: Path,
    packet: dict[str, Any],
    identity: InferenceIdentity,
    provider: ProviderIdentity,
    call_provider: Callable[[], ProviderCallResult],
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> _Resolution:
    result_path = _result_path(cache_path, identity.analysis_key)
    if _path_exists(result_path):
        return _Resolution(_load_hit(cache_path, packet, identity, provider), "hit")

    packet_path = _packet_path(cache_path, packet["packet_hash"])
    packet_bytes = canonical_json_bytes(_packet_object(packet))
    if _path_exists(packet_path):
        _validate_packet_object(packet_path, packet)
    else:
        _publish_immutable(packet_path, packet_bytes)

    lock_path = _lock_path(cache_path, identity.analysis_key)
    _, owned_lock = _new_lock(identity.analysis_key)
    acquired = False
    try:
        with _semantic_guard(
            cache_path,
            identity.analysis_key,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        ):
            if _path_exists(result_path):
                return _Resolution(
                    _load_hit(cache_path, packet, identity, provider), "hit"
                )
            acquired = _link_candidate(lock_path, owned_lock)
            if not acquired:
                if _path_exists(result_path):
                    return _Resolution(
                        _load_hit(cache_path, packet, identity, provider), "hit"
                    )
                _read_valid_lock(lock_path, identity.analysis_key)
    except _AnalysisFailure as exc:
        published = _load_published_result_after_lock_timeout(
            exc,
            result_path=result_path,
            load_result=lambda: _load_hit(cache_path, packet, identity, provider),
        )
        if published is not None:
            return _Resolution(published, "hit")
        raise
    if not acquired:
        row = _wait_for_result(
            cache_path=cache_path,
            packet=packet,
            identity=identity,
            provider=provider,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
        return _Resolution(row, "hit")

    try:
        with _semantic_guard(
            cache_path,
            identity.analysis_key,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        ):
            try:
                _, current = _read_valid_lock(lock_path, identity.analysis_key)
            except FileNotFoundError:
                if _path_exists(result_path):
                    return _Resolution(
                        _load_hit(cache_path, packet, identity, provider), "hit"
                    )
                raise CacheProtocolError(
                    "semantic lock ownership disappeared before provider call"
                ) from None
            if current != owned_lock:
                if _path_exists(result_path):
                    return _Resolution(
                        _load_hit(cache_path, packet, identity, provider), "hit"
                    )
                raise CacheProtocolError(
                    "semantic lock ownership changed before provider call"
                )
        response = call_provider()
        row, result_object = _normalize_provider_result(
            packet, identity, response, provider
        )
        with _semantic_guard(
            cache_path,
            identity.analysis_key,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        ):
            try:
                _, current = _read_valid_lock(lock_path, identity.analysis_key)
            except FileNotFoundError:
                if _path_exists(result_path):
                    return _Resolution(
                        _load_hit(cache_path, packet, identity, provider), "hit"
                    )
                raise CacheProtocolError(
                    "semantic lock ownership disappeared before publication"
                ) from None
            if current != owned_lock:
                if _path_exists(result_path):
                    return _Resolution(
                        _load_hit(cache_path, packet, identity, provider), "hit"
                    )
                raise CacheProtocolError(
                    "semantic lock ownership changed before publication"
                )
            _publish_immutable(result_path, canonical_json_bytes(result_object))
            _remove_owned_lock(lock_path, identity.analysis_key, owned_lock)
        return _Resolution(row, "miss")
    except Exception:
        cleaned = _retry_owned_failure_cleanup(
            cache_path=cache_path,
            key=identity.analysis_key,
            expected_lock=owned_lock,
            verifier=False,
            poll_interval_seconds=poll_interval_seconds,
        )
        if not cleaned:
            _log_cleanup_guidance(key=identity.analysis_key, verifier=False)
        raise


def analyze_with_cache(
    *,
    packets: Iterable[ValidatedSemanticPacket],
    cache_path: Path,
    cache_mode: str,
    provider_identity: ProviderIdentity,
    request_identity: RequestIdentity,
    adapter_factory: AdapterFactory | None,
    search_epoch: str,
    lock_wait_timeout_seconds: float,
    poll_interval_seconds: float = 0.1,
    runtime_deadline: float | None = None,
    provider_call_budget: ProviderCallBudget | None = None,
    provider_call_packet_ids: frozenset[str] | None = None,
    identities: Iterable[InferenceIdentity] | None = None,
) -> SemanticCacheRun:
    """Resolve packets in order through off/read-write/require cache modes."""

    packet_list = tuple(packets)
    problems: list[SemanticProblem] = []
    canonical_results: list[bytes] = []
    cache_hits = 0
    cache_misses = 0
    provider_calls = 0
    kind_counts = _empty_analyzer_kind_counts()
    runtime_exceeded = False
    if cache_mode not in ("off", "read-write", "require"):
        problems.append(
            SemanticProblem(None, "config", "invalid_config", "invalid cache mode")
        )
    if not isinstance(search_epoch, str) or not search_epoch.strip():
        problems.append(
            SemanticProblem(
                None, "config", "invalid_config", "search epoch must be nonblank"
            )
        )
    if (
        isinstance(lock_wait_timeout_seconds, bool)
        or not isinstance(lock_wait_timeout_seconds, (int, float))
        or lock_wait_timeout_seconds <= 0
    ):
        problems.append(
            SemanticProblem(
                None,
                "config",
                "invalid_config",
                "lock wait timeout must be positive",
            )
        )
    if (
        isinstance(poll_interval_seconds, bool)
        or not isinstance(poll_interval_seconds, (int, float))
        or not 0 < poll_interval_seconds <= _POLL_INTERVAL_MAX_SECONDS
    ):
        problems.append(
            SemanticProblem(
                None,
                "config",
                "invalid_config",
                "poll interval must be greater than zero and no more than one second",
            )
        )
    rows = tuple(packet.to_dict() for packet in packet_list)
    packet_ids = [row["packet_id"] for row in rows]
    if len(packet_ids) != len(set(packet_ids)):
        problems.append(
            SemanticProblem(
                None, "input", "invalid_input", "duplicate semantic packet ID"
            )
        )
    if cache_mode in ("read-write", "require") and any(
        not packet.cache_eligible for packet in packet_list
    ):
        problems.append(
            SemanticProblem(
                None,
                "input",
                "invalid_input",
                "legacy-normalized packets are not cache eligible",
            )
        )
    if cache_mode in ("read-write", "require"):
        cached_identity_fields = {
            "backend_id": provider_identity.backend_id,
            "plugin_id": provider_identity.plugin_id,
            "plugin_distribution_name": provider_identity.plugin_distribution_name,
            "model_id": provider_identity.model_id,
            "model_revision": provider_identity.model_revision,
        }
        blank_fields = sorted(
            name for name, value in cached_identity_fields.items() if not value.strip()
        )
        if blank_fields:
            problems.append(
                SemanticProblem(
                    None,
                    "config",
                    "invalid_config",
                    "cached mode requires nonblank provider identity: "
                    + ", ".join(blank_fields),
                )
            )
    if cache_mode == "require" and adapter_factory is not None:
        problems.append(
            SemanticProblem(
                None,
                "config",
                "invalid_config",
                "require cache mode forbids an adapter factory",
            )
        )
    if problems:
        return SemanticCacheRun((), tuple(problems), b"", 0, 0, 0)
    try:
        frozen_identities = _freeze_inference_identities(
            rows,
            provider_identity,
            request_identity,
            search_epoch,
            identities,
        )
    except ValueError as exc:
        return SemanticCacheRun(
            (),
            (SemanticProblem(None, "input", "invalid_input", str(exc)),),
            b"",
            0,
            0,
            0,
        )
    if cache_mode != "off":
        try:
            cache_path = cache_path.resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            return SemanticCacheRun(
                (),
                (
                    SemanticProblem(
                        None,
                        "cache",
                        "corrupt_cache",
                        f"cannot resolve semantic cache path: {exc}",
                    ),
                ),
                b"",
                0,
                0,
                0,
            )

    adapter: ProviderAdapter | None = None

    def call(packet: dict[str, Any], identity: InferenceIdentity) -> ProviderCallResult:
        nonlocal adapter, provider_calls, runtime_exceeded
        if runtime_exceeded or (
            runtime_deadline is not None and time.monotonic() >= runtime_deadline
        ):
            runtime_exceeded = True
            raise _AnalysisFailure(
                "budget",
                "budget_exceeded",
                "maximum semantic analysis runtime exceeded",
            )
        if (
            provider_call_packet_ids is not None
            and packet["packet_id"] not in provider_call_packet_ids
        ):
            raise _AnalysisFailure(
                "budget",
                "budget_exceeded",
                "unplanned provider call is outside the conservative cost preflight",
            )
        reserved = False
        if provider_call_budget is not None:
            if not provider_call_budget.reserve():
                raise _AnalysisFailure(
                    "budget",
                    "budget_exceeded",
                    "maximum semantic provider calls exceeded during execution",
                )
            reserved = True
        if adapter is None:
            if adapter_factory is None:
                if reserved:
                    assert provider_call_budget is not None
                    provider_call_budget.release()
                raise _AnalysisFailure(
                    "provider", "provider_failure", "no provider adapter is available"
                )
            try:
                adapter = adapter_factory()
            except Exception as exc:  # noqa: BLE001 - external adapter boundary
                if reserved:
                    assert provider_call_budget is not None
                    provider_call_budget.release()
                detail = exc.args[0] if isinstance(exc, KeyError) and exc.args else exc
                raise _AnalysisFailure(
                    "provider",
                    "provider_failure",
                    f"adapter construction failed: {detail}",
                ) from exc
        if runtime_deadline is not None and time.monotonic() >= runtime_deadline:
            runtime_exceeded = True
            if reserved:
                assert provider_call_budget is not None
                provider_call_budget.release()
            raise _AnalysisFailure(
                "budget",
                "budget_exceeded",
                "maximum semantic analysis runtime exceeded before provider call",
            )
        provider_calls += 1
        packet_kind = cast(SemanticPacketKind, packet["kind"])
        kind_counts["provider_calls"][packet_kind] += 1
        try:
            response = adapter(
                model_request_bytes(
                    packet, instruction_bytes=identity.prompt_bytes
                ).decode("utf-8")
            )
        except _AnalysisFailure:
            raise
        except Exception as exc:  # noqa: BLE001 - external provider boundary
            raise _AnalysisFailure(
                "provider", "provider_failure", f"model call failed: {exc}"
            ) from exc
        if runtime_deadline is not None and time.monotonic() >= runtime_deadline:
            runtime_exceeded = True
        return response

    for row, identity in zip(rows, frozen_identities, strict=True):
        packet_id = row["packet_id"]
        try:
            if cache_mode == "off":
                response = call(row, identity)
                normalized, _ = _normalize_provider_result(
                    row, identity, response, provider_identity
                )
                resolution = _Resolution(normalized, "off")
            elif cache_mode == "require":
                result_path = _result_path(cache_path, identity.analysis_key)
                if not _path_exists(result_path):
                    cache_misses += 1
                    packet_kind = cast(SemanticPacketKind, row["kind"])
                    kind_counts["cache_misses"][packet_kind] += 1
                    raise _AnalysisFailure(
                        "completeness",
                        "incomplete_result",
                        "required semantic cache result is missing",
                    )
                resolution = _Resolution(
                    _load_hit(cache_path, row, identity, provider_identity), "hit"
                )
            else:
                initial_result = _path_exists(
                    _result_path(cache_path, identity.analysis_key)
                )
                if not initial_result:
                    cache_misses += 1
                    packet_kind = cast(SemanticPacketKind, row["kind"])
                    kind_counts["cache_misses"][packet_kind] += 1

                def call_current(
                    current_row: dict[str, Any] = row,
                    current_identity: InferenceIdentity = identity,
                ) -> ProviderCallResult:
                    return call(current_row, current_identity)

                resolution = _resolve_cached_result(
                    cache_path=cache_path,
                    packet=row,
                    identity=identity,
                    provider=provider_identity,
                    call_provider=call_current,
                    timeout_seconds=float(lock_wait_timeout_seconds),
                    poll_interval_seconds=float(poll_interval_seconds),
                )
                if not initial_result and resolution.source == "hit":
                    cache_misses -= 1
                    packet_kind = cast(SemanticPacketKind, row["kind"])
                    kind_counts["cache_misses"][packet_kind] -= 1
            if resolution.source == "hit":
                cache_hits += 1
                packet_kind = cast(SemanticPacketKind, row["kind"])
                kind_counts["cache_hits"][packet_kind] += 1
            canonical_results.append(canonical_json_bytes(resolution.row))
        except _AnalysisFailure as exc:
            problems.append(
                SemanticProblem(packet_id, exc.stage, exc.code, exc.message)
            )
        except CacheProtocolError as exc:
            problems.append(
                SemanticProblem(packet_id, "cache", "corrupt_cache", str(exc))
            )
        except Exception as exc:  # noqa: BLE001 - contain one packet boundary
            problems.append(
                SemanticProblem(
                    packet_id,
                    "cache",
                    "corrupt_cache",
                    f"unexpected cache failure: {exc}",
                )
            )

    if runtime_exceeded and not any(
        problem.code == "budget_exceeded" for problem in problems
    ):
        problems.append(
            SemanticProblem(
                None,
                "budget",
                "budget_exceeded",
                "maximum semantic analysis runtime exceeded",
            )
        )
    result_jsonl = b"".join(item + b"\n" for item in canonical_results)
    return SemanticCacheRun(
        tuple(canonical_results),
        tuple(problems),
        result_jsonl,
        cache_hits,
        cache_misses,
        provider_calls,
        kind_counts,
    )


def inspect_semantic_cache(
    *,
    packets: Iterable[ValidatedSemanticPacket],
    cache_path: Path,
    cache_mode: str,
    provider_identity: ProviderIdentity,
    request_identity: RequestIdentity,
    search_epoch: str,
    identities: Iterable[InferenceIdentity] | None = None,
) -> SemanticCacheInspection:
    """Validate existing hits and count misses without writes or provider work.

    The unified semantic gate uses this read-only pass to enforce provider-call
    and conservative cost ceilings across all planned misses before traffic.
    Ordinary analysis still revalidates every hit because cache state is
    untrusted and may change after inspection.
    """

    packet_list = tuple(packets)
    rows = tuple(packet.to_dict() for packet in packet_list)
    problems: list[SemanticProblem] = []
    if cache_mode not in ("off", "read-write", "require"):
        problems.append(
            SemanticProblem(None, "config", "invalid_config", "invalid cache mode")
        )
    if not isinstance(search_epoch, str) or not search_epoch.strip():
        problems.append(
            SemanticProblem(
                None, "config", "invalid_config", "search epoch must be nonblank"
            )
        )
    packet_ids = [row["packet_id"] for row in rows]
    if len(packet_ids) != len(set(packet_ids)):
        problems.append(
            SemanticProblem(
                None, "input", "invalid_input", "duplicate semantic packet ID"
            )
        )
    if cache_mode in ("read-write", "require") and any(
        not packet.cache_eligible for packet in packet_list
    ):
        problems.append(
            SemanticProblem(
                None,
                "input",
                "invalid_input",
                "legacy-normalized packets are not cache eligible",
            )
        )
    if cache_mode in ("read-write", "require"):
        cached_identity_fields = {
            "backend_id": provider_identity.backend_id,
            "plugin_id": provider_identity.plugin_id,
            "plugin_distribution_name": provider_identity.plugin_distribution_name,
            "model_id": provider_identity.model_id,
            "model_revision": provider_identity.model_revision,
        }
        blank_fields = sorted(
            name for name, value in cached_identity_fields.items() if not value.strip()
        )
        if blank_fields:
            problems.append(
                SemanticProblem(
                    None,
                    "config",
                    "invalid_config",
                    "cached mode requires nonblank provider identity: "
                    + ", ".join(blank_fields),
                )
            )
    if problems:
        return SemanticCacheInspection(tuple(problems), 0, 0, ())
    try:
        frozen_identities = _freeze_inference_identities(
            rows,
            provider_identity,
            request_identity,
            search_epoch,
            identities,
        )
    except ValueError as exc:
        return SemanticCacheInspection(
            (SemanticProblem(None, "input", "invalid_input", str(exc)),),
            0,
            0,
            (),
        )
    if cache_mode == "off":
        return SemanticCacheInspection(
            (), 0, len(rows), tuple(row["packet_id"] for row in rows)
        )

    try:
        cache_path = cache_path.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        return SemanticCacheInspection(
            (
                SemanticProblem(
                    None,
                    "cache",
                    "corrupt_cache",
                    f"cannot resolve semantic cache path: {exc}",
                ),
            ),
            0,
            0,
            (),
        )

    planned_hits = 0
    planned_misses = 0
    planned_miss_packet_ids: list[str] = []
    for row, identity in zip(rows, frozen_identities, strict=True):
        packet_id = row["packet_id"]
        try:
            result_path = _result_path(cache_path, identity.analysis_key)
            if _path_exists(result_path):
                _load_hit(cache_path, row, identity, provider_identity)
                planned_hits += 1
                continue
            planned_misses += 1
            planned_miss_packet_ids.append(packet_id)
            if cache_mode == "require":
                problems.append(
                    SemanticProblem(
                        packet_id,
                        "completeness",
                        "incomplete_result",
                        "required semantic cache result is missing",
                    )
                )
        except _AnalysisFailure as exc:
            problems.append(
                SemanticProblem(packet_id, exc.stage, exc.code, exc.message)
            )
        except CacheProtocolError as exc:
            problems.append(
                SemanticProblem(packet_id, "cache", "corrupt_cache", str(exc))
            )
        except Exception as exc:  # noqa: BLE001 - contain untrusted cache boundary
            problems.append(
                SemanticProblem(
                    packet_id,
                    "cache",
                    "corrupt_cache",
                    f"unexpected cache inspection failure: {exc}",
                )
            )
    return SemanticCacheInspection(
        tuple(problems),
        planned_hits,
        planned_misses,
        tuple(planned_miss_packet_ids),
    )


def _verify_result_path(cache_path: Path, verify_key: str) -> Path:
    return _safe_cache_child(cache_path, ("verify-results",), f"{verify_key}.json")


def _verify_lock_path(cache_path: Path, verify_key: str) -> Path:
    return _safe_cache_child(cache_path, ("verify-locks",), f"{verify_key}.lock")


def _verify_guard_path(cache_path: Path, verify_key: str) -> Path:
    return _safe_cache_child(cache_path, ("verify-guards",), f"{verify_key}.guard")


def _verify_guard_bytes(verify_key: str) -> bytes:
    return canonical_json_bytes(
        {
            "schema_version": 1,
            "object_type": "semantic-verification-lock-guard",
            "verify_key": verify_key,
        }
    )


@contextmanager
def _verify_guard(
    cache_path: Path,
    verify_key: str,
    *,
    timeout_seconds: float | None,
    poll_interval_seconds: float,
    drain_owned_cleanup: bool = True,
) -> Iterator[None]:
    path = _verify_guard_path(cache_path, verify_key)
    expected = _verify_guard_bytes(verify_key)
    _publish_immutable(path, expected)
    value, actual = _read_canonical_object(path)
    if set(value) != _VERIFY_GUARD_FIELDS or actual != expected:
        raise CacheProtocolError("verification cache guard has invalid closed shape")

    process_guard = _process_guard(path)
    deadline = (
        time.monotonic() + timeout_seconds if timeout_seconds is not None else None
    )
    while not process_guard.acquire(blocking=False):
        if deadline is None:
            raise _guard_wait_failure(timeout_seconds)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _guard_wait_failure(timeout_seconds)
        time.sleep(min(poll_interval_seconds, remaining))
    try:
        try:
            handle = path.open("r+b", buffering=0)
        except OSError as exc:
            raise CacheProtocolError(
                f"cannot open verification cache guard: {exc}"
            ) from exc
        acquired_os = False
        try:
            while not acquired_os:
                acquired_os = _try_lock_guard(handle)
                if acquired_os:
                    break
                if deadline is None:
                    raise _guard_wait_failure(timeout_seconds)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise _guard_wait_failure(timeout_seconds)
                time.sleep(min(poll_interval_seconds, remaining))
            if drain_owned_cleanup:
                _drain_owned_cleanup_under_guard(path)
            yield
        finally:
            try:
                if acquired_os:
                    _unlock_guard(handle)
            finally:
                handle.close()
    finally:
        process_guard.release()


def _validate_verify_contract(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CacheProtocolError("cached verifier inference contract is not an object")
    expected = {
        "verify_contract_version",
        "verifier_packet_hash",
        "claim_hash",
        "prompt",
        "provider",
        "request",
        "base_search_epoch",
        "effective_search_epoch",
    }
    if set(value) != expected:
        raise CacheProtocolError(
            "cached verifier inference contract has invalid closed shape"
        )
    version = value["verify_contract_version"]
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise CacheProtocolError("cached verifier contract version is invalid")
    for field_name in ("verifier_packet_hash", "claim_hash"):
        if not is_sha256_hex(value[field_name]):
            raise CacheProtocolError(f"cached verifier {field_name} is invalid")
    for field_name in ("base_search_epoch", "effective_search_epoch"):
        if not isinstance(value[field_name], str) or not value[field_name].strip():
            raise CacheProtocolError(f"cached verifier {field_name} is invalid")
    _validate_inference_contract_shape(
        {
            "analysis_contract_version": version,
            "packet_hash": value["verifier_packet_hash"],
            "prompt": value["prompt"],
            "provider": value["provider"],
            "request": value["request"],
            "search_epoch": value["effective_search_epoch"],
        }
    )
    return value


def _load_verify_hit(
    cache_path: Path,
    work: VerificationWork,
    provider: ProviderIdentity,
) -> CanonicalVerificationResult:
    packet_path = _packet_path(cache_path, work.packet["packet_hash"])
    result_path = _verify_result_path(cache_path, work.identity.verify_key)
    if not _path_exists(packet_path):
        raise CacheProtocolError(
            "cached verification result exists without its packet object"
        )
    _validate_packet_object(packet_path, work.packet)
    value, _ = _read_canonical_object(result_path)
    if set(value) != _VERIFY_RESULT_OBJECT_FIELDS:
        raise CacheProtocolError(
            "cached verification result has unknown or missing fields"
        )
    if (
        value.get("schema_version") != 1
        or value.get("object_type") != "verification-result"
    ):
        raise CacheProtocolError("cached verification result type/version is invalid")
    verify_key = value.get("verify_key")
    if not is_sha256_hex(verify_key):
        raise CacheProtocolError("cached verification key is invalid")
    contract = _validate_verify_contract(value.get("inference_contract"))
    recomputed = hashlib.sha256(canonical_json_bytes(contract)).hexdigest()
    if (
        verify_key != work.identity.verify_key
        or recomputed != work.identity.verify_key
        or contract != work.identity.contract
    ):
        raise _AnalysisFailure(
            "cache", "stale_cache", "cached verifier inference contract is stale"
        )
    _validate_provenance(value.get("provenance"), provider)
    raw_hash = value.get("raw_response_sha256")
    if not is_sha256_hex(raw_hash):
        raise CacheProtocolError("cached verifier raw response hash is invalid")
    try:
        return load_canonical_verification_result(
            work.packet,
            work.claim,
            work.request,
            work.identity,
            value.get("result"),
        )
    except VerificationContractError as exc:
        raise CacheProtocolError(
            f"cached canonical verification result is invalid: {exc}"
        ) from exc


def _validate_verify_lock(value: object, verify_key: str) -> None:
    if not isinstance(value, dict) or set(value) != _VERIFY_LOCK_FIELDS:
        raise CacheProtocolError("verification lock has invalid closed shape")
    if (
        value.get("schema_version") != 1
        or value.get("object_type") != "semantic-verification-lock"
        or value.get("verify_key") != verify_key
    ):
        raise CacheProtocolError("verification lock type or key is invalid")
    if not is_sha256_hex(value.get("owner_token")):
        raise CacheProtocolError("verification lock owner token is invalid")
    pid = value.get("pid")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid < 1:
        raise CacheProtocolError("verification lock pid is invalid")
    if not isinstance(value.get("host"), str) or not value["host"].strip():
        raise CacheProtocolError("verification lock host is invalid")
    try:
        _parse_canonical_utc(value.get("created_at_utc"))
    except ValueError as exc:
        raise CacheProtocolError(
            f"verification lock timestamp is invalid: {exc}"
        ) from exc


def _read_verify_lock(path: Path, verify_key: str) -> bytes:
    value, raw = _read_canonical_object(path)
    _validate_verify_lock(value, verify_key)
    return raw


def _new_verify_lock(verify_key: str) -> bytes:
    return canonical_json_bytes(
        {
            "schema_version": 1,
            "object_type": "semantic-verification-lock",
            "verify_key": verify_key,
            "owner_token": secrets.token_hex(32),
            "pid": os.getpid(),
            "host": socket.gethostname().strip() or "unknown-host",
            "created_at_utc": _format_utc(_utc_now()),
        }
    )


def _remove_verify_lock(path: Path, verify_key: str, expected: bytes) -> None:
    try:
        current = _read_verify_lock(path, verify_key)
    except FileNotFoundError as exc:
        raise CacheProtocolError("owned verification lock disappeared") from exc
    if current != expected:
        raise CacheProtocolError("verification lock ownership changed")
    try:
        path.unlink()
    except OSError as exc:
        raise CacheProtocolError(f"cannot remove verification lock: {exc}") from exc
    _fsync_directory(path.parent)


def _normalize_verify_provider_result(
    work: VerificationWork,
    response: ProviderCallResult,
    provider: ProviderIdentity,
) -> tuple[CanonicalVerificationResult, dict[str, Any]]:
    if not isinstance(response, ProviderCallResult):
        raise _AnalysisFailure(
            "normalization",
            "malformed_result",
            "verifier adapter returned an invalid provider result",
        )
    if (
        response.provenance.adapter_id != provider.adapter_id
        or response.provenance.adapter_version != provider.adapter_version
        or response.provenance.plugin_version
        != (provider.plugin_distribution_version or None)
    ):
        raise _AnalysisFailure(
            "normalization",
            "malformed_result",
            "provider provenance does not match verifier inference contract",
        )
    try:
        parsed = parse_verifier_response(response.raw_response)
        result = normalize_verifier_response(
            work.packet, work.claim, work.request, work.identity, parsed
        )
    except VerificationContractError as exc:
        raise _AnalysisFailure(
            "normalization", "malformed_result", f"verifier output invalid: {exc}"
        ) from exc
    result_object = {
        "schema_version": 1,
        "object_type": "verification-result",
        "inference_contract": work.identity.contract,
        "verify_key": work.identity.verify_key,
        "result": result.to_row(),
        "provenance": response.provenance.to_dict(),
        "raw_response_sha256": hashlib.sha256(
            response.raw_response.encode("utf-8")
        ).hexdigest(),
    }
    return result, result_object


def _wait_for_verify_result(
    cache_path: Path,
    work: VerificationWork,
    provider: ProviderIdentity,
    *,
    timeout_seconds: float,
    poll_interval_seconds: float,
    runtime_deadline: float | None,
) -> CanonicalVerificationResult:
    result_path = _verify_result_path(cache_path, work.identity.verify_key)
    lock_path = _verify_lock_path(cache_path, work.identity.verify_key)
    deadline = time.monotonic() + timeout_seconds
    if runtime_deadline is not None:
        deadline = min(deadline, runtime_deadline)
    while True:
        if _path_exists(result_path):
            return _load_verify_hit(cache_path, work, provider)
        if _path_exists(lock_path):
            remaining = deadline - time.monotonic()
            if remaining > 0:
                try:
                    with _verify_guard(
                        cache_path,
                        work.identity.verify_key,
                        timeout_seconds=remaining,
                        poll_interval_seconds=poll_interval_seconds,
                    ):
                        if _path_exists(lock_path):
                            _read_verify_lock(lock_path, work.identity.verify_key)
                except _AnalysisFailure as exc:
                    published = _load_published_result_after_lock_timeout(
                        exc,
                        result_path=result_path,
                        load_result=lambda: _load_verify_hit(
                            cache_path, work, provider
                        ),
                    )
                    if published is not None:
                        return published
                    raise
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            if _path_exists(result_path):
                return _load_verify_hit(cache_path, work, provider)
            raise _AnalysisFailure(
                "lock", "lock_timeout", "timed out waiting for verifier cache owner"
            )
        time.sleep(min(poll_interval_seconds, remaining))


def _resolve_cached_verify_result(
    cache_path: Path,
    work: VerificationWork,
    provider: ProviderIdentity,
    call_provider: Callable[[], ProviderCallResult],
    *,
    timeout_seconds: float,
    poll_interval_seconds: float,
    runtime_deadline: float | None,
) -> tuple[CanonicalVerificationResult, CacheSource]:
    def remaining_timeout() -> float:
        if runtime_deadline is None:
            return timeout_seconds
        remaining = runtime_deadline - time.monotonic()
        if remaining <= 0:
            raise _AnalysisFailure(
                "budget", "budget_exceeded", "maximum verifier runtime exceeded"
            )
        return min(timeout_seconds, remaining)

    result_path = _verify_result_path(cache_path, work.identity.verify_key)
    if _path_exists(result_path):
        return _load_verify_hit(cache_path, work, provider), "hit"
    packet_path = _packet_path(cache_path, work.packet["packet_hash"])
    packet_bytes = canonical_json_bytes(_packet_object(work.packet))
    if _path_exists(packet_path):
        _validate_packet_object(packet_path, work.packet)
    else:
        _publish_immutable(packet_path, packet_bytes)
    lock_path = _verify_lock_path(cache_path, work.identity.verify_key)
    owned = _new_verify_lock(work.identity.verify_key)
    acquired = False
    try:
        with _verify_guard(
            cache_path,
            work.identity.verify_key,
            timeout_seconds=remaining_timeout(),
            poll_interval_seconds=poll_interval_seconds,
        ):
            if _path_exists(result_path):
                return _load_verify_hit(cache_path, work, provider), "hit"
            acquired = _link_candidate(lock_path, owned)
            if not acquired:
                if _path_exists(result_path):
                    return _load_verify_hit(cache_path, work, provider), "hit"
                _read_verify_lock(lock_path, work.identity.verify_key)
    except _AnalysisFailure as exc:
        published = _load_published_result_after_lock_timeout(
            exc,
            result_path=result_path,
            load_result=lambda: _load_verify_hit(cache_path, work, provider),
        )
        if published is not None:
            return published, "hit"
        raise
    if not acquired:
        return (
            _wait_for_verify_result(
                cache_path,
                work,
                provider,
                timeout_seconds=remaining_timeout(),
                poll_interval_seconds=poll_interval_seconds,
                runtime_deadline=runtime_deadline,
            ),
            "hit",
        )
    try:
        with _verify_guard(
            cache_path,
            work.identity.verify_key,
            timeout_seconds=remaining_timeout(),
            poll_interval_seconds=poll_interval_seconds,
        ):
            try:
                current = _read_verify_lock(lock_path, work.identity.verify_key)
            except FileNotFoundError:
                if _path_exists(result_path):
                    return _load_verify_hit(cache_path, work, provider), "hit"
                raise CacheProtocolError(
                    "verification lock ownership disappeared before provider call"
                ) from None
            if current != owned:
                if _path_exists(result_path):
                    return _load_verify_hit(cache_path, work, provider), "hit"
                raise CacheProtocolError(
                    "verification lock ownership changed before provider call"
                )
        response = call_provider()
        result, result_object = _normalize_verify_provider_result(
            work, response, provider
        )
        with _verify_guard(
            cache_path,
            work.identity.verify_key,
            timeout_seconds=remaining_timeout(),
            poll_interval_seconds=poll_interval_seconds,
        ):
            try:
                current = _read_verify_lock(lock_path, work.identity.verify_key)
            except FileNotFoundError:
                if _path_exists(result_path):
                    return _load_verify_hit(cache_path, work, provider), "hit"
                raise CacheProtocolError(
                    "verification lock ownership disappeared before publication"
                ) from None
            if current != owned:
                if _path_exists(result_path):
                    return _load_verify_hit(cache_path, work, provider), "hit"
                raise CacheProtocolError(
                    "verification lock ownership changed before publication"
                )
            _publish_immutable(result_path, canonical_json_bytes(result_object))
            _remove_verify_lock(lock_path, work.identity.verify_key, owned)
        return result, "miss"
    except Exception:
        cleaned = _retry_owned_failure_cleanup(
            cache_path=cache_path,
            key=work.identity.verify_key,
            expected_lock=owned,
            verifier=True,
            poll_interval_seconds=poll_interval_seconds,
        )
        if not cleaned:
            _log_cleanup_guidance(key=work.identity.verify_key, verifier=True)
        raise


def inspect_verification_cache(
    *,
    work_items: Iterable[VerificationWork],
    cache_path: Path,
    cache_mode: str,
    provider_identity: ProviderIdentity,
    request_identity: RequestIdentity,
) -> VerificationCacheInspection:
    """Validate verifier hits and count misses without writes or provider work."""

    work = tuple(work_items)
    problems: list[SemanticProblem] = []
    if cache_mode not in {"off", "read-write", "require"}:
        problems.append(
            SemanticProblem(
                None, "config", "invalid_config", "invalid verifier cache mode"
            )
        )
    keys = [item.identity.verify_key for item in work]
    if len(keys) != len(set(keys)):
        problems.append(
            SemanticProblem(None, "input", "invalid_input", "duplicate verifier key")
        )
    expected_provider = asdict(provider_identity)
    expected_request = asdict(request_identity)
    for item in work:
        packet_id = item.packet.get("packet_id")
        problem_packet_id = packet_id if isinstance(packet_id, str) else None
        try:
            validate_verification_links(
                item.packet, item.claim, item.request, item.identity
            )
            contract = item.identity.contract
            if contract.get("provider") != expected_provider:
                raise VerificationContractError(
                    "verifier work provider does not match resolved provider"
                )
            if contract.get("request") != expected_request:
                raise VerificationContractError(
                    "verifier work request does not match resolved request"
                )
            if (
                contract.get("base_search_epoch") != item.base_search_epoch
                or contract.get("effective_search_epoch") != item.effective_search_epoch
            ):
                raise VerificationContractError(
                    "verifier work epochs do not match its identity"
                )
        except Exception as exc:  # noqa: BLE001 - contain untrusted work objects
            problems.append(
                SemanticProblem(
                    problem_packet_id,
                    "input",
                    "invalid_input",
                    f"invalid verifier work: {exc}",
                )
            )
    if problems:
        return VerificationCacheInspection(tuple(problems), 0, 0, ())
    if cache_mode == "off":
        return VerificationCacheInspection((), 0, len(work), tuple(keys))
    try:
        cache_path = cache_path.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        return VerificationCacheInspection(
            (
                SemanticProblem(
                    None,
                    "cache",
                    "corrupt_cache",
                    f"cannot resolve verifier cache path: {exc}",
                ),
            ),
            0,
            0,
            (),
        )
    hits = 0
    misses: list[str] = []
    for item in work:
        try:
            result_path = _verify_result_path(cache_path, item.identity.verify_key)
            if _path_exists(result_path):
                _load_verify_hit(cache_path, item, provider_identity)
                hits += 1
                continue
            misses.append(item.identity.verify_key)
            if cache_mode == "require":
                problems.append(
                    SemanticProblem(
                        item.packet["packet_id"],
                        "completeness",
                        "incomplete_result",
                        "required verifier cache result is missing",
                    )
                )
        except _AnalysisFailure as exc:
            problems.append(
                SemanticProblem(
                    item.packet["packet_id"], exc.stage, exc.code, exc.message
                )
            )
        except (CacheProtocolError, VerificationContractError) as exc:
            problems.append(
                SemanticProblem(
                    item.packet["packet_id"], "cache", "corrupt_cache", str(exc)
                )
            )
        except Exception as exc:  # noqa: BLE001 - contain untrusted cache boundary
            problems.append(
                SemanticProblem(
                    item.packet["packet_id"],
                    "cache",
                    "corrupt_cache",
                    f"unexpected verifier cache inspection failure: {exc}",
                )
            )
    return VerificationCacheInspection(
        tuple(problems), hits, len(misses), tuple(misses)
    )


def verify_with_cache(
    *,
    work_items: Iterable[VerificationWork],
    cache_path: Path,
    cache_mode: str,
    provider_identity: ProviderIdentity,
    request_identity: RequestIdentity,
    adapter_factory: AdapterFactory | None,
    lock_wait_timeout_seconds: float,
    poll_interval_seconds: float = 0.1,
    runtime_deadline: float | None = None,
    provider_call_budget: ProviderCallBudget | None = None,
) -> VerificationCacheRun:
    """Resolve finding/epoch verifier work through the immutable cache."""

    work = tuple(work_items)
    problems: list[SemanticProblem] = []
    if cache_mode not in {"off", "read-write", "require"}:
        problems.append(
            SemanticProblem(
                None, "config", "invalid_config", "invalid verifier cache mode"
            )
        )
    if (
        isinstance(lock_wait_timeout_seconds, bool)
        or not isinstance(lock_wait_timeout_seconds, (int, float))
        or lock_wait_timeout_seconds <= 0
        or isinstance(poll_interval_seconds, bool)
        or not isinstance(poll_interval_seconds, (int, float))
        or not 0 < poll_interval_seconds <= _POLL_INTERVAL_MAX_SECONDS
    ):
        problems.append(
            SemanticProblem(
                None, "config", "invalid_config", "invalid verifier cache timing"
            )
        )
    keys = [item.identity.verify_key for item in work]
    if len(keys) != len(set(keys)):
        problems.append(
            SemanticProblem(None, "input", "invalid_input", "duplicate verifier key")
        )
    if cache_mode == "require" and adapter_factory is not None:
        problems.append(
            SemanticProblem(
                None,
                "config",
                "invalid_config",
                "require verifier cache mode forbids an adapter factory",
            )
        )
    if cache_mode in {"read-write", "require"}:
        identity_fields = (
            provider_identity.backend_id,
            provider_identity.plugin_id,
            provider_identity.plugin_distribution_name,
            provider_identity.model_id,
            provider_identity.model_revision,
        )
        if any(not value.strip() for value in identity_fields):
            problems.append(
                SemanticProblem(
                    None,
                    "config",
                    "invalid_config",
                    "cached verifier mode requires complete provider identity",
                )
            )
    expected_provider = asdict(provider_identity)
    expected_request = asdict(request_identity)
    for item in work:
        packet_id = item.packet.get("packet_id")
        problem_packet_id = packet_id if isinstance(packet_id, str) else None
        try:
            validate_verification_links(
                item.packet,
                item.claim,
                item.request,
                item.identity,
            )
            contract = item.identity.contract
            if contract.get("provider") != expected_provider:
                raise VerificationContractError(
                    "verifier work provider does not match resolved provider"
                )
            if contract.get("request") != expected_request:
                raise VerificationContractError(
                    "verifier work request does not match resolved request"
                )
            if (
                contract.get("base_search_epoch") != item.base_search_epoch
                or contract.get("effective_search_epoch") != item.effective_search_epoch
            ):
                raise VerificationContractError(
                    "verifier work epochs do not match its identity"
                )
        except VerificationContractError as exc:
            problems.append(
                SemanticProblem(
                    problem_packet_id,
                    "input",
                    "invalid_input",
                    f"invalid verifier work: {exc}",
                )
            )
        except Exception as exc:  # noqa: BLE001 - contain untrusted work objects
            problems.append(
                SemanticProblem(
                    problem_packet_id,
                    "input",
                    "invalid_input",
                    f"invalid verifier work: {exc}",
                )
            )
    if problems:
        return VerificationCacheRun((), tuple(problems), 0, 0, 0)
    if runtime_deadline is not None and time.monotonic() >= runtime_deadline:
        return VerificationCacheRun(
            (),
            (
                SemanticProblem(
                    None,
                    "budget",
                    "budget_exceeded",
                    "maximum verifier runtime exceeded before work",
                ),
            ),
            0,
            0,
            0,
        )
    if cache_mode != "off":
        try:
            cache_path = cache_path.resolve(strict=False)
            _ensure_cache_directory(cache_path)
        except (OSError, RuntimeError, CacheProtocolError) as exc:
            return VerificationCacheRun(
                (),
                (SemanticProblem(None, "cache", "corrupt_cache", str(exc)),),
                0,
                0,
                0,
            )
    adapter: ProviderAdapter | None = None
    results: list[CanonicalVerificationResult] = []
    hits = 0
    misses = 0
    calls = 0
    for item in work:
        packet_id = item.packet["packet_id"]
        reserved = False

        if runtime_deadline is not None and time.monotonic() >= runtime_deadline:
            problems.append(
                SemanticProblem(
                    packet_id,
                    "budget",
                    "budget_exceeded",
                    "maximum verifier runtime exceeded before work",
                )
            )
            break

        def call(current_item: VerificationWork = item) -> ProviderCallResult:
            nonlocal adapter, calls, reserved
            if runtime_deadline is not None and time.monotonic() >= runtime_deadline:
                raise _AnalysisFailure(
                    "budget", "budget_exceeded", "maximum verifier runtime exceeded"
                )
            if provider_call_budget is not None:
                if not provider_call_budget.reserve():
                    raise _AnalysisFailure(
                        "budget", "budget_exceeded", "maximum verifier calls exceeded"
                    )
                reserved = True
            if adapter is None:
                if adapter_factory is None:
                    if reserved:
                        assert provider_call_budget is not None
                        provider_call_budget.release()
                        reserved = False
                    raise _AnalysisFailure(
                        "provider",
                        "provider_failure",
                        "no verifier adapter is available",
                    )
                try:
                    adapter = adapter_factory()
                except Exception as exc:  # noqa: BLE001
                    if reserved:
                        assert provider_call_budget is not None
                        provider_call_budget.release()
                        reserved = False
                    raise _AnalysisFailure(
                        "provider",
                        "provider_failure",
                        f"adapter construction failed: {exc}",
                    ) from exc
            calls += 1
            try:
                response = adapter(
                    verifier_request_bytes(
                        current_item.request,
                        prompt_bytes=current_item.identity.prompt_bytes,
                    ).decode("utf-8")
                )
            except Exception as exc:  # noqa: BLE001
                raise _AnalysisFailure(
                    "provider", "provider_failure", f"verifier call failed: {exc}"
                ) from exc
            if runtime_deadline is not None and time.monotonic() >= runtime_deadline:
                raise _AnalysisFailure(
                    "budget",
                    "budget_exceeded",
                    "maximum verifier runtime exceeded after provider return",
                )
            return response

        try:
            if cache_mode == "off":
                result, _ = _normalize_verify_provider_result(
                    item, call(), provider_identity
                )
            elif cache_mode == "require":
                result_path = _verify_result_path(cache_path, item.identity.verify_key)
                if not _path_exists(result_path):
                    misses += 1
                    raise _AnalysisFailure(
                        "completeness",
                        "incomplete_result",
                        "required verifier cache result is missing",
                    )
                result = _load_verify_hit(cache_path, item, provider_identity)
                hits += 1
            else:
                existed = _path_exists(
                    _verify_result_path(cache_path, item.identity.verify_key)
                )
                if not existed:
                    misses += 1
                result, source = _resolve_cached_verify_result(
                    cache_path,
                    item,
                    provider_identity,
                    call,
                    timeout_seconds=float(lock_wait_timeout_seconds),
                    poll_interval_seconds=float(poll_interval_seconds),
                    runtime_deadline=runtime_deadline,
                )
                if source == "hit":
                    hits += 1
                    if not existed:
                        misses -= 1
            results.append(result)
        except _AnalysisFailure as exc:
            problems.append(
                SemanticProblem(packet_id, exc.stage, exc.code, exc.message)
            )
        except (CacheProtocolError, VerificationContractError) as exc:
            problems.append(
                SemanticProblem(packet_id, "cache", "corrupt_cache", str(exc))
            )
        except Exception as exc:  # noqa: BLE001 - contain one verifier work item
            problems.append(
                SemanticProblem(
                    packet_id,
                    "cache",
                    "corrupt_cache",
                    f"unexpected verifier cache failure: {exc}",
                )
            )
    return VerificationCacheRun(tuple(results), tuple(problems), hits, misses, calls)


def cleanup_lock(
    *,
    cache_path: Path,
    analysis_key: str | None = None,
    verify_key: str | None = None,
    lock_stale_seconds: int,
    reason: str,
) -> CleanupResult:
    """Audit then remove one explicitly named abandoned semantic lock."""

    if (analysis_key is None) == (verify_key is None):
        raise CacheProtocolError(
            "exactly one of analysis key or verify key must be supplied"
        )
    key = analysis_key if analysis_key is not None else verify_key
    key_name = "analysis key" if analysis_key is not None else "verify key"
    assert key is not None
    if not is_sha256_hex(key):
        raise CacheProtocolError(f"{key_name} must be 64 lowercase hex characters")
    if (
        isinstance(lock_stale_seconds, bool)
        or not isinstance(lock_stale_seconds, int)
        or lock_stale_seconds < 1
    ):
        raise CacheProtocolError("lock stale interval must be a positive integer")
    if not isinstance(reason, str) or not reason.strip():
        raise CacheProtocolError("lock cleanup reason must be nonblank")
    try:
        cache_path = cache_path.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise CacheProtocolError(f"cannot resolve semantic cache path: {exc}") from exc
    guard = _semantic_guard if analysis_key is not None else _verify_guard
    with guard(
        cache_path,
        key,
        timeout_seconds=None,
        poll_interval_seconds=0.1,
        drain_owned_cleanup=False,
    ):
        return _cleanup_lock_held(
            cache_path=cache_path,
            key=key,
            verifier=verify_key is not None,
            lock_stale_seconds=lock_stale_seconds,
            reason=reason,
        )


def _cleanup_lock_held(
    *,
    cache_path: Path,
    key: str,
    verifier: bool,
    lock_stale_seconds: int,
    reason: str,
) -> CleanupResult:
    path = (
        _verify_lock_path(cache_path, key) if verifier else _lock_path(cache_path, key)
    )
    if not _path_exists(path):
        raise CacheProtocolError("semantic lock does not exist")
    raw, before = _read_regular_bytes(path)
    created_at: datetime | None = None
    try:
        value = json.loads(raw)
        if canonical_json_bytes(value) != raw:
            raise ValueError
        if verifier:
            _validate_verify_lock(value, key)
        else:
            _validate_lock(value, key)
        created_at = _parse_canonical_utc(value["created_at_utc"])
    except (CacheProtocolError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        created_at = None
    now = _utc_now()
    age_seconds = (
        (now - created_at).total_seconds()
        if created_at is not None
        else now.timestamp() - before.st_mtime_ns / 1_000_000_000
    )
    if age_seconds < lock_stale_seconds:
        raise CacheProtocolError("semantic lock is not stale")
    audit = {
        "schema_version": 1,
        "object_type": "semantic-lock-cleanup",
        ("verify_key" if verifier else "analysis_key"): key,
        "lock_sha256": hashlib.sha256(raw).hexdigest(),
        "lock_bytes": base64.b64encode(raw).decode("ascii"),
        "lock_lstat": {
            "mode": before.st_mode,
            "size": before.st_size,
            "mtime_ns": before.st_mtime_ns,
        },
        "reason": reason,
        "cleaned_at_utc": _format_utc(now),
    }
    audit_bytes = canonical_json_bytes(audit)
    audit_sha = hashlib.sha256(audit_bytes).hexdigest()
    audit_path = _safe_cache_child(
        cache_path,
        ("audit", "verify-locks" if verifier else "locks"),
        f"{key}.{audit_sha}.json",
    )
    _publish_immutable(audit_path, audit_bytes)

    current, after = _read_regular_bytes(path)
    if current != raw or _lstat_identity(after) != _lstat_identity(before):
        raise CacheProtocolError(
            "semantic lock changed after cleanup audit publication"
        )
    try:
        path.unlink()
    except OSError as exc:
        raise CacheProtocolError(f"cannot remove audited semantic lock: {exc}") from exc
    _fsync_directory(path.parent)
    return CleanupResult(audit_path=audit_path)
