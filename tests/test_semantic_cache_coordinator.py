"""Shared analyzer, review, and verifier ownership-state-machine proofs.

Spec: docs/specs/06-semantic-gates.md [SEM-4], [SEM-10]
"""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pytest

import backstitch.semantic_cache as cache


@dataclass(frozen=True, slots=True)
class _Family:
    kind: Literal["analysis", "review", "verify"]
    key: str

    def result_path(self, root: Path) -> Path:
        if self.kind == "review":
            return cache._baseline_path(root, self.key)
        if self.kind == "verify":
            return cache._verify_result_path(root, self.key)
        return cache._result_path(root, self.key)

    def lock_path(self, root: Path) -> Path:
        if self.kind == "review":
            return cache._review_lock_path(root, self.key)
        if self.kind == "verify":
            return cache._verify_lock_path(root, self.key)
        return cache._lock_path(root, self.key)

    def read_lock(self, path: Path) -> bytes:
        if self.kind == "review":
            return cache._read_review_lock(path, self.key)
        if self.kind == "verify":
            return cache._read_verify_lock(path, self.key)
        return cache._read_valid_lock(path, self.key)[1]

    def remove_lock(self, path: Path, expected: bytes) -> None:
        if self.kind == "review":
            cache._remove_review_lock(path, self.key, expected)
        elif self.kind == "verify":
            cache._remove_verify_lock(path, self.key, expected)
        else:
            cache._remove_owned_lock(path, self.key, expected)


_FAMILIES = (
    _Family("analysis", "1" * 64),
    _Family("review", "2" * 64),
    _Family("verify", "3" * 64),
)


def _coordinator(
    root: Path,
    family: _Family,
    *,
    timeout: float = 0.2,
) -> cache._OwnershipCoordinator[bytes]:
    result_path = family.result_path(root)
    lock_path = family.lock_path(root)
    return cache._OwnershipCoordinator(
        cache_path=root,
        key=family.key,
        lock_kind=family.kind,
        result_path=result_path,
        lock_path=lock_path,
        timeout_seconds=timeout,
        poll_interval_seconds=0.005,
        load_result=result_path.read_bytes,
        read_lock=lambda: family.read_lock(lock_path),
        remove_lock=lambda expected: family.remove_lock(lock_path, expected),
        wait_error=f"timed out waiting for {family.kind} owner",
        ownership_name=f"{family.kind} lock",
    )


def _claim_complete_cleanup(tmp_path: Path, family: _Family) -> None:
    root = (tmp_path / family.kind).resolve()
    owner = _coordinator(root, family)

    assert owner.acquire() == (True, None)
    assert family.read_lock(family.lock_path(root)) == owner.owned_lock
    assert owner.check_owned(phase="provider call") is None
    assert (
        owner.complete(
            publish=lambda: cache._publish_immutable(
                family.result_path(root), b"complete"
            )
        )
        is None
    )
    assert family.result_path(root).read_bytes() == b"complete"
    assert not family.lock_path(root).exists()

    failed_owner = _coordinator((tmp_path / f"{family.kind}-failure").resolve(), family)
    assert failed_owner.acquire() == (True, None)
    assert failed_owner.cleanup_failure()
    assert not family.lock_path(failed_owner.cache_path).exists()


def _timeout_without_stealing(tmp_path: Path, family: _Family) -> None:
    root = (tmp_path / family.kind).resolve()
    owner = _coordinator(root, family)
    assert owner.acquire() == (True, None)
    waiter = _coordinator(root, family, timeout=0.02)

    assert waiter.acquire() == (False, None)
    with pytest.raises(cache.SemanticCacheFailure) as raised:
        waiter.wait()
    assert raised.value.code == "lock_timeout"
    assert family.read_lock(family.lock_path(root)) == owner.owned_lock
    owner.release()


def _reincarnation_preserves_successor(tmp_path: Path, family: _Family) -> None:
    root = (tmp_path / family.kind).resolve()
    first = _coordinator(root, family, timeout=1)
    assert first.acquire() == (True, None)
    waiter = _coordinator(root, family, timeout=1)
    assert waiter.acquire() == (False, None)

    with ThreadPoolExecutor(max_workers=1) as pool:
        waiting = pool.submit(waiter.wait)
        time.sleep(0.02)
        first.release()
        successor = _coordinator(root, family, timeout=1)
        assert successor.acquire() == (True, None)
        assert first.cleanup_failure()
        assert family.read_lock(family.lock_path(root)) == successor.owned_lock
        successor.complete(
            publish=lambda: cache._publish_immutable(
                family.result_path(root), b"successor"
            )
        )
        assert waiting.result(timeout=1) == b"successor"


@dataclass(frozen=True, slots=True)
class _Scenario:
    name: str
    transitions: tuple[str, ...]
    run: Callable[[Path, _Family], None]


_SCENARIOS = (
    _Scenario(
        "complete and cleanup",
        (
            "unowned -> owned",
            "owned -> provider-checked",
            "provider-checked -> published",
            "published -> unlocked",
            "owned-failure -> cleaned",
        ),
        _claim_complete_cleanup,
    ),
    _Scenario(
        "timeout without stealing",
        (
            "unowned -> owned",
            "contender -> waiting",
            "waiting -> timed-out",
            "owner-token -> unchanged",
        ),
        _timeout_without_stealing,
    ),
    _Scenario(
        "reincarnation preserves successor",
        (
            "owner-a -> released",
            "released -> owner-b",
            "owner-a-cleanup -> owner-b-unchanged",
            "waiting -> successor-result",
        ),
        _reincarnation_preserves_successor,
    ),
)


@pytest.mark.parametrize("family", _FAMILIES, ids=lambda family: family.kind)
@pytest.mark.parametrize("scenario", _SCENARIOS, ids=lambda scenario: scenario.name)
def test_shared_ownership_transition_table(
    tmp_path: Path,
    family: _Family,
    scenario: _Scenario,
) -> None:
    assert scenario.transitions
    scenario.run(tmp_path, family)
