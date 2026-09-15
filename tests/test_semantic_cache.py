"""Immutable semantic cache, locking, replay, and cleanup tests.

Spec: docs/specs/06-semantic-gates.md [SEM-4], [SEM-10]
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import types
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from backstitch.artifact_contracts import (
    ValidatedSemanticPacket,
    invariant_content_hash,
)
from backstitch.semantic_cache import (
    AdapterFactory,
    CacheProtocolError,
    ProviderAdapter,
    ProviderCallResult,
    SemanticCacheFailure,
    SemanticCacheRun,
    SemanticProvenance,
    SemanticResultEnvelope,
    analyze_with_cache,
    cleanup_lock,
    inspect_semantic_cache,
    load_required_evidence_stable_result,
    load_semantic_baseline,
    prepare_evidence_stable_cache,
    resolve_prepared_evidence_stable_result,
)
from backstitch.semantic_identity import (
    ProviderIdentity,
    RequestIdentity,
    build_analysis_identities,
    build_inference_identity,
)
from backstitch.semantic_packets import canonical_json_bytes, semantic_packet_hash


def _packet(section_id: str = "X-1") -> dict[str, Any]:
    packet: dict[str, Any] = {
        "schema_version": 2,
        "packet_id": f"docs/specs/01-X.md#{section_id}",
        "kind": "section",
        "spec_path": "docs/specs/01-X.md",
        "section_id": section_id,
        "title": "Thing",
        "section_text": f"## Thing [{section_id}]\n\nMust frob.",
        "section_start_line": 1,
        "owners": [
            {
                "path": "pkg/mod.py",
                "symbol": "frob",
                "start_line": 10,
                "snippet": "def frob():\n    return True",
            }
        ],
        "tests": [],
        "issues": [],
        "packet_warnings": [],
    }
    packet["packet_hash"] = semantic_packet_hash(packet)
    return packet


def _validated(
    section_id: str = "X-1", *, cache_eligible: bool = True
) -> ValidatedSemanticPacket:
    return ValidatedSemanticPacket.from_row(
        _packet(section_id), cache_eligible=cache_eligible
    )


def _invariant_packet() -> dict[str, Any]:
    targets = [
        {
            "path": "pkg/mod.py",
            "symbol": "frob",
            "start_line": 10,
            "snippet": "def frob():\n    return True",
        }
    ]
    binding_tests = [
        {
            "path": "tests/test_mod.py",
            "symbol": "test_frob",
            "start_line": 20,
            "snippet": "def test_frob():\n    assert frob() is True",
        }
    ]
    packet: dict[str, Any] = {
        "schema_version": 2,
        "packet_id": "invariant::INV.X.1",
        "kind": "invariant",
        "invariant_id": "INV.X.1",
        "tier": "required",
        "statement": "Frob remains true.",
        "declaration": {
            "kind": "code",
            "path": "pkg/mod.py",
            "line": 5,
            "symbol": "frob",
            "section_id": None,
            "start_line": 5,
            "end_line": 5,
            "excerpt": "Invariant: [INV.X.1] Frob remains true.",
        },
        "targets": targets,
        "binding_tests": binding_tests,
        "issues": [],
        "packet_warnings": [],
        "content_hash": invariant_content_hash(
            "Frob remains true.", targets, binding_tests
        ),
    }
    packet["packet_hash"] = semantic_packet_hash(packet)
    return packet


PROVIDER = ProviderIdentity(
    backend_id="llm",
    plugin_id="openai",
    model_id="gpt-test",
    model_revision="2026-01-01",
    adapter_id="backstitch.llm",
    adapter_version=1,
    llm_distribution_version="0.31.1",
    plugin_distribution_name="llm-openai",
    plugin_distribution_version="1.2.3",
)
REQUEST = RequestIdentity("require", 0.0, 42, 512)
PROVENANCE = SemanticProvenance(
    adapter_id="backstitch.llm",
    adapter_version=1,
    plugin_version="1.2.3",
    model_class="tests.ControlledModel",
    provider_model_id="gpt-test-2026-01-01",
    provider_model_revision="2026-01-01",
    response_id="response-1",
    input_tokens=100,
    output_tokens=20,
)


def _response_for_prompt(prompt: str) -> ProviderCallResult:
    packet = json.loads(prompt.rsplit("\n\n", 1)[1])
    raw = json.dumps(
        {
            "packet_id": packet["packet_id"],
            "assessment": {"classification": "ok", "evidence": {}},
            "confidence": 0.9,
            "rationale": "bounded review",
            "summary": "Looks aligned.",
        }
    )
    return ProviderCallResult(raw_response=raw, provenance=PROVENANCE)


def _run(
    cache_path: Path,
    packets: tuple[ValidatedSemanticPacket, ...],
    *,
    cache_mode: str = "read-write",
    adapter_factory: AdapterFactory | None = None,
    lock_wait_timeout_seconds: float = 1,
    provider_identity: ProviderIdentity = PROVIDER,
    request_identity: RequestIdentity = REQUEST,
    search_epoch: str = "1",
) -> SemanticCacheRun:
    if adapter_factory is None and cache_mode != "require":

        def default_factory() -> ProviderAdapter:
            return _response_for_prompt

        adapter_factory = default_factory
    return analyze_with_cache(
        packets=packets,
        cache_path=cache_path,
        cache_mode=cache_mode,
        provider_identity=provider_identity,
        request_identity=request_identity,
        adapter_factory=adapter_factory,
        search_epoch=search_epoch,
        lock_wait_timeout_seconds=lock_wait_timeout_seconds,
        poll_interval_seconds=0.01,
    )


def test_read_write_publishes_exact_canonical_packet_and_result_objects(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache"
    packet = _packet()
    run = _run(cache_path, (_validated(),))

    assert run.problems == ()
    assert run.cache_hits == 0
    assert run.cache_misses == 1
    assert run.provider_calls == 1
    assert len(run.results) == 1
    result = run.results[0]
    assert run.result_jsonl == canonical_json_bytes(result) + b"\n"

    identity = build_inference_identity(packet, PROVIDER, REQUEST)
    packet_path = cache_path / "packets" / f"{packet['packet_hash']}.json"
    result_path = cache_path / "results" / f"{identity.analysis_key}.json"
    guard_path = cache_path / "guards" / f"{identity.analysis_key}.guard"
    packet_object = json.loads(packet_path.read_bytes())
    result_object = json.loads(result_path.read_bytes())

    assert set(packet_object) == {
        "schema_version",
        "object_type",
        "packet_id",
        "kind",
        "spec_path",
        "section_id",
        "title",
        "section_text",
        "section_start_line",
        "section_end_line",
        "evidence_regions",
        "owners",
        "tests",
        "issues",
        "packet_warnings",
        "packet_hash",
    }
    assert packet_object["schema_version"] == 1
    assert packet_object["object_type"] == "semantic-packet"
    assert packet_path.read_bytes() == canonical_json_bytes(packet_object)
    assert set(result_object) == {
        "schema_version",
        "object_type",
        "inference_contract",
        "analysis_key",
        "result",
        "provenance",
        "raw_response_sha256",
    }
    assert guard_path.read_bytes() == canonical_json_bytes(
        {
            "schema_version": 1,
            "object_type": "semantic-lock-guard",
            "analysis_key": identity.analysis_key,
        }
    )
    assert result_object["inference_contract"] == identity.contract
    assert result_object["analysis_key"] == identity.analysis_key
    assert result_object["result"] == result
    assert result_object["provenance"] == PROVENANCE.to_dict()
    assert (
        result_object["raw_response_sha256"]
        == hashlib.sha256(
            _response_for_prompt("x\n\n" + json.dumps(packet)).raw_response.encode()
        ).hexdigest()
    )
    assert result_path.read_bytes() == canonical_json_bytes(result_object)


def test_reasoning_effort_is_part_of_closed_cache_identity_and_replay(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache"
    request = replace(REQUEST, reasoning_effort="max")

    populated = _run(
        cache_path,
        (_validated(),),
        request_identity=request,
    )
    replay = _run(
        cache_path,
        (_validated(),),
        cache_mode="require",
        request_identity=request,
    )

    assert populated.problems == ()
    assert populated.provider_calls == 1
    assert replay.problems == ()
    assert replay.cache_hits == 1
    assert replay.provider_calls == 0
    identity = build_inference_identity(_packet(), PROVIDER, request)
    cached = json.loads(
        (cache_path / "results" / f"{identity.analysis_key}.json").read_bytes()
    )
    assert cached["inference_contract"]["request"]["reasoning_effort"] == "max"


def test_evidence_stable_preparation_backfills_and_carries_immutable_baseline(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache"
    packet = _validated()
    exact = _run(cache_path, (packet,))
    old_identity, review = build_analysis_identities(
        packet.to_dict(), PROVIDER, REQUEST
    )

    with prepare_evidence_stable_cache(
        packets=(packet,),
        cache_path=cache_path,
        cache_mode="read-write",
        provider_identity=PROVIDER,
        identities=(old_identity,),
        lock_wait_timeout_seconds=1,
        poll_interval_seconds=0.01,
    ) as prepared:
        assert prepared.owned_review_keys == (review.review_key,)
        assert prepared.items[0].selection is not None
        assert prepared.items[0].selection.source == "exact-cache"
        selection = resolve_prepared_evidence_stable_result(
            prepared.items[0],
            call_provider=lambda: pytest.fail("exact hit must not call provider"),
        )

    assert selection.source == "exact-cache"
    assert isinstance(selection.envelope, SemanticResultEnvelope)
    assert prepared.selection_events == (selection,)
    assert prepared.result_envelopes == (selection.envelope,)
    assert selection.envelope.result == exact.results[0]
    baseline_path = cache_path / "baselines" / f"{review.review_key}.json"
    baseline = json.loads(baseline_path.read_bytes())
    assert baseline == {
        "schema_version": 1,
        "object_type": "semantic-result-baseline",
        "review_contract": review.contract,
        "review_key": review.review_key,
        "analysis_key": old_identity.analysis_key,
    }
    assert baseline_path.read_bytes() == canonical_json_bytes(baseline)

    new_provider = replace(PROVIDER, model_id="gpt-new", model_revision="2026-02-01")
    new_identity, same_review = build_analysis_identities(
        packet.to_dict(), new_provider, REQUEST
    )
    assert same_review.review_key == review.review_key
    with prepare_evidence_stable_cache(
        packets=(packet,),
        cache_path=cache_path,
        cache_mode="require",
        provider_identity=new_provider,
        identities=(new_identity,),
        lock_wait_timeout_seconds=1,
        poll_interval_seconds=0.01,
    ) as replay:
        carried = replay.items[0].selection

    assert carried is not None
    assert carried.source == "carried"
    assert carried.envelope.analysis_key == old_identity.analysis_key
    assert carried.envelope.provider_identity == PROVIDER
    assert carried.envelope.result == exact.results[0]
    assert replay.items[0].producing_provider_identity == PROVIDER


def test_baseline_validation_rejects_absent_target_and_mismatched_review_key(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache"
    packet = _validated()
    identity, review = build_analysis_identities(packet.to_dict(), PROVIDER, REQUEST)
    baseline_path = cache_path / "baselines" / f"{review.review_key}.json"
    baseline_path.parent.mkdir(parents=True)
    baseline_path.write_bytes(
        canonical_json_bytes(
            {
                "schema_version": 1,
                "object_type": "semantic-result-baseline",
                "review_contract": review.contract,
                "review_key": review.review_key,
                "analysis_key": identity.analysis_key,
            }
        )
    )

    with pytest.raises(CacheProtocolError, match="without its result object"):
        load_semantic_baseline(cache_path, packet.to_dict(), review)

    mismatched_path = cache_path / "baselines" / f"{'f' * 64}.json"
    mismatched_path.write_bytes(baseline_path.read_bytes())
    with pytest.raises(CacheProtocolError, match="review key does not match its path"):
        load_semantic_baseline(
            cache_path,
            packet.to_dict(),
            replace(review, review_key="f" * 64),
        )


def test_evidence_stable_preparation_acquires_unique_review_locks_lexically(
    tmp_path: Path,
) -> None:
    packets = (_validated("X-2"), _validated("X-1"))
    identities = tuple(
        build_analysis_identities(packet.to_dict(), PROVIDER, REQUEST)[0]
        for packet in packets
    )
    expected = tuple(
        sorted(identity.review_identity.review_key for identity in identities)
    )

    with prepare_evidence_stable_cache(
        packets=packets,
        cache_path=tmp_path / "cache",
        cache_mode="read-write",
        provider_identity=PROVIDER,
        identities=identities,
        lock_wait_timeout_seconds=1,
        poll_interval_seconds=0.01,
    ) as prepared:
        assert prepared.owned_review_keys == expected
        assert all(item.selection is None for item in prepared.items)
        assert all(
            item.producing_provider_identity == PROVIDER for item in prepared.items
        )
        for key in expected:
            assert (tmp_path / "cache" / "review-locks" / f"{key}.lock").is_file()

    assert not any((tmp_path / "cache" / "review-locks").glob("*.lock"))


def test_require_evidence_stable_lookup_is_read_only_and_returns_exact_fallback(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache"
    packet = _validated()
    _run(cache_path, (packet,))
    identity, _ = build_analysis_identities(packet.to_dict(), PROVIDER, REQUEST)
    before = {
        path.relative_to(cache_path): path.read_bytes()
        for path in cache_path.rglob("*")
        if path.is_file()
    }

    selection = load_required_evidence_stable_result(
        cache_path,
        packet.to_dict(),
        identity,
        PROVIDER,
    )

    assert selection is not None
    assert selection.source == "exact-cache"
    after = {
        path.relative_to(cache_path): path.read_bytes()
        for path in cache_path.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert not (cache_path / "review-guards").exists()


def test_different_provider_race_makes_one_call_and_one_baseline(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache"
    packet = _validated()
    providers = (
        PROVIDER,
        replace(PROVIDER, model_id="gpt-new", model_revision="2026-02-01"),
    )
    barrier = threading.Barrier(2)
    calls: list[str] = []
    calls_lock = threading.Lock()

    def worker(provider: ProviderIdentity) -> Any:
        identity, _ = build_analysis_identities(packet.to_dict(), provider, REQUEST)
        barrier.wait(timeout=2)
        with prepare_evidence_stable_cache(
            packets=(packet,),
            cache_path=cache_path,
            cache_mode="read-write",
            provider_identity=provider,
            identities=(identity,),
            lock_wait_timeout_seconds=2,
            poll_interval_seconds=0.01,
        ) as prepared:

            def call() -> ProviderCallResult:
                with calls_lock:
                    calls.append(provider.model_id)
                return _response_for_prompt(
                    identity.prompt_bytes.decode("utf-8")
                    + "\n\n"
                    + json.dumps(packet.to_dict())
                )

            return resolve_prepared_evidence_stable_result(
                prepared.items[0], call_provider=call
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(worker, providers))

    assert len(calls) == 1
    assert sorted(result.source for result in results) == ["carried", "live"]
    assert len({result.envelope.analysis_key for result in results}) == 1
    assert len(list((cache_path / "baselines").glob("*.json"))) == 1
    assert not list((cache_path / "review-locks").glob("*.lock"))


def test_require_second_baseline_read_wins_real_publication_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backstitch.semantic_cache as semantic_cache

    cache_path = tmp_path / "cache"
    packet = _validated()
    old_provider = PROVIDER
    selected_provider = replace(
        PROVIDER, model_id="gpt-new", model_revision="2026-02-01"
    )
    _run(cache_path, (packet,), provider_identity=old_provider)
    _run(cache_path, (packet,), provider_identity=selected_provider)
    old_identity, _ = build_analysis_identities(packet.to_dict(), old_provider, REQUEST)
    selected_identity, _ = build_analysis_identities(
        packet.to_dict(), selected_provider, REQUEST
    )
    exact_read = threading.Event()
    allow_second_read = threading.Event()
    real_exact_read = semantic_cache.load_exact_semantic_result

    with prepare_evidence_stable_cache(
        packets=(packet,),
        cache_path=cache_path,
        cache_mode="read-write",
        provider_identity=old_provider,
        identities=(old_identity,),
        lock_wait_timeout_seconds=2,
        poll_interval_seconds=0.01,
    ) as prepared:

        def read_exact_then_pause(*args: Any, **kwargs: Any) -> Any:
            result = real_exact_read(*args, **kwargs)
            exact_read.set()
            assert allow_second_read.wait(timeout=2)
            return result

        monkeypatch.setattr(
            semantic_cache, "load_exact_semantic_result", read_exact_then_pause
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                load_required_evidence_stable_result,
                cache_path,
                packet.to_dict(),
                selected_identity,
                selected_provider,
            )
            assert exact_read.wait(timeout=2)
            published = resolve_prepared_evidence_stable_result(
                prepared.items[0],
                call_provider=lambda: pytest.fail("old exact result must be reused"),
            )
            allow_second_read.set()
            selected = future.result(timeout=2)

    assert published.envelope.analysis_key == old_identity.analysis_key
    assert selected is not None
    assert selected.source == "carried"
    assert selected.envelope.analysis_key == old_identity.analysis_key


def test_baseline_rejects_corrupt_target_without_fallback(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache"
    packet = _validated()
    _run(cache_path, (packet,))
    identity, review = build_analysis_identities(packet.to_dict(), PROVIDER, REQUEST)
    with prepare_evidence_stable_cache(
        packets=(packet,),
        cache_path=cache_path,
        cache_mode="read-write",
        provider_identity=PROVIDER,
        identities=(identity,),
        lock_wait_timeout_seconds=1,
        poll_interval_seconds=0.01,
    ) as prepared:
        resolve_prepared_evidence_stable_result(
            prepared.items[0],
            call_provider=lambda: pytest.fail("exact result must be reused"),
        )
    result_path = cache_path / "results" / f"{identity.analysis_key}.json"
    target = json.loads(result_path.read_bytes())
    target["raw_response_sha256"] = "not-a-hash"
    result_path.write_bytes(canonical_json_bytes(target))

    with pytest.raises(CacheProtocolError, match="raw response hash"):
        load_semantic_baseline(cache_path, packet.to_dict(), review)


def test_provider_failure_remains_primary_and_releases_review_lock(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache"
    packet = _validated()
    identity, review = build_analysis_identities(packet.to_dict(), PROVIDER, REQUEST)

    with pytest.raises(RuntimeError, match="provider unavailable"):
        with prepare_evidence_stable_cache(
            packets=(packet,),
            cache_path=cache_path,
            cache_mode="read-write",
            provider_identity=PROVIDER,
            identities=(identity,),
            lock_wait_timeout_seconds=1,
            poll_interval_seconds=0.01,
        ) as prepared:
            resolve_prepared_evidence_stable_result(
                prepared.items[0],
                call_provider=lambda: (_ for _ in ()).throw(
                    RuntimeError("provider unavailable")
                ),
            )

    assert not (cache_path / "review-locks" / f"{review.review_key}.lock").exists()
    assert not (cache_path / "baselines" / f"{review.review_key}.json").exists()


def test_review_lock_wait_is_capped_by_absolute_runtime_deadline(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache"
    packet = _validated()
    identity, review = build_analysis_identities(packet.to_dict(), PROVIDER, REQUEST)

    with prepare_evidence_stable_cache(
        packets=(packet,),
        cache_path=cache_path,
        cache_mode="read-write",
        provider_identity=PROVIDER,
        identities=(identity,),
        lock_wait_timeout_seconds=2,
        poll_interval_seconds=0.01,
    ):
        started = time.monotonic()
        with pytest.raises(SemanticCacheFailure) as raised:
            with prepare_evidence_stable_cache(
                packets=(packet,),
                cache_path=cache_path,
                cache_mode="read-write",
                provider_identity=PROVIDER,
                identities=(identity,),
                lock_wait_timeout_seconds=2,
                poll_interval_seconds=0.01,
                runtime_deadline=started + 0.05,
            ):
                pytest.fail("contending review owner must not acquire the lock")

    assert raised.value.stage == "budget"
    assert raised.value.code == "budget_exceeded"
    assert time.monotonic() - started < 0.5
    assert not (cache_path / "review-locks" / f"{review.review_key}.lock").exists()


def test_nested_analysis_lock_wait_respects_runtime_and_publishes_no_baseline(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache"
    packet = _validated()
    identity, review = build_analysis_identities(packet.to_dict(), PROVIDER, REQUEST)
    provider_entered = threading.Event()
    release_provider = threading.Event()

    def blocked_adapter(prompt: str) -> ProviderCallResult:
        provider_entered.set()
        assert release_provider.wait(timeout=2)
        return _response_for_prompt(prompt)

    with prepare_evidence_stable_cache(
        packets=(packet,),
        cache_path=cache_path,
        cache_mode="read-write",
        provider_identity=PROVIDER,
        identities=(identity,),
        lock_wait_timeout_seconds=2,
        poll_interval_seconds=0.01,
    ) as prepared:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                analyze_with_cache,
                packets=(packet,),
                cache_path=cache_path,
                cache_mode="read-write",
                provider_identity=PROVIDER,
                request_identity=REQUEST,
                adapter_factory=lambda: blocked_adapter,
                search_epoch="1",
                lock_wait_timeout_seconds=2,
                poll_interval_seconds=0.01,
            )
            assert provider_entered.wait(timeout=2)
            try:
                with pytest.raises(SemanticCacheFailure) as raised:
                    resolve_prepared_evidence_stable_result(
                        prepared.items[0],
                        call_provider=lambda: pytest.fail(
                            "analysis-lock waiter must not call the provider"
                        ),
                        runtime_deadline=time.monotonic() + 0.05,
                    )
            finally:
                release_provider.set()
            exact = future.result(timeout=2)

    assert raised.value.stage == "budget"
    assert raised.value.code == "budget_exceeded"
    assert exact.problems == ()
    assert not (cache_path / "baselines" / f"{review.review_key}.json").exists()


def test_provider_runtime_overrun_publishes_neither_result_nor_baseline(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache"
    packet = _validated()
    identity, review = build_analysis_identities(packet.to_dict(), PROVIDER, REQUEST)

    with prepare_evidence_stable_cache(
        packets=(packet,),
        cache_path=cache_path,
        cache_mode="read-write",
        provider_identity=PROVIDER,
        identities=(identity,),
        lock_wait_timeout_seconds=2,
        poll_interval_seconds=0.01,
    ) as prepared:

        def overlong_provider() -> ProviderCallResult:
            time.sleep(0.08)
            return _response_for_prompt(
                identity.prompt_bytes.decode("utf-8")
                + "\n\n"
                + json.dumps(packet.to_dict())
            )

        with pytest.raises(SemanticCacheFailure) as raised:
            resolve_prepared_evidence_stable_result(
                prepared.items[0],
                call_provider=overlong_provider,
                runtime_deadline=time.monotonic() + 0.04,
            )

    assert raised.value.stage == "budget"
    assert raised.value.code == "budget_exceeded"
    assert not (cache_path / "results" / f"{identity.analysis_key}.json").exists()
    assert not (cache_path / "baselines" / f"{review.review_key}.json").exists()


def test_required_replay_is_byte_identical_and_constructs_no_adapter(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache"
    populated = _run(cache_path, (_validated(),))

    replay = _run(
        cache_path,
        (_validated(),),
        cache_mode="require",
        adapter_factory=None,
    )

    assert replay.problems == ()
    assert replay.cache_hits == 1
    assert replay.cache_misses == 0
    assert replay.provider_calls == 0
    assert replay.result_jsonl == populated.result_jsonl


def test_analyzer_operational_counts_are_recorded_at_each_kind_event(
    tmp_path: Path,
) -> None:
    packets = (
        _validated(),
        ValidatedSemanticPacket.from_row(_invariant_packet(), cache_eligible=True),
    )

    run = _run(tmp_path / "cache", packets, cache_mode="off")

    assert run.kind_counts == {
        "cache_hits": {"section": 0, "invariant": 0, "suppression": 0},
        "cache_misses": {"section": 0, "invariant": 0, "suppression": 0},
        "provider_calls": {"section": 1, "invariant": 1, "suppression": 0},
    }


def test_idle_cache_root_deletion_rebuilds_or_fails_by_selected_mode(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache"
    populated = _run(cache_path, (_validated(),))

    shutil.rmtree(cache_path)
    rebuilt = _run(cache_path, (_validated(),))

    assert rebuilt.problems == ()
    assert rebuilt.cache_hits == 0
    assert rebuilt.cache_misses == 1
    assert rebuilt.provider_calls == 1
    assert rebuilt.result_jsonl == populated.result_jsonl

    shutil.rmtree(cache_path)
    required = _run(
        cache_path,
        (_validated(),),
        cache_mode="require",
        adapter_factory=None,
    )

    assert required.results == ()
    assert required.provider_calls == 0
    assert required.problems[0].stage == "completeness"
    assert required.problems[0].code == "incomplete_result"
    assert not cache_path.exists()


def test_invariant_packet_cache_omits_content_hash_but_result_requires_it(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache"
    packet = _invariant_packet()
    validated = ValidatedSemanticPacket.from_row(packet, cache_eligible=True)

    def respond(prompt: str) -> ProviderCallResult:
        projection = json.loads(prompt.rsplit("\n\n", 1)[1])
        raw = json.dumps(
            {
                "packet_id": projection["packet_id"],
                "assessment": {
                    "classification": "ok",
                    "evidence": {
                        "test": [
                            {
                                "path": "tests/test_mod.py",
                                "start_line": 20,
                                "end_line": 21,
                            }
                        ]
                    },
                },
                "confidence": 0.9,
                "rationale": "the binding assertion is shown",
                "summary": "The invariant is bound.",
            }
        )
        return ProviderCallResult(raw, PROVENANCE)

    run = _run(cache_path, (validated,), adapter_factory=lambda: respond)
    packet_path = cache_path / "packets" / f"{packet['packet_hash']}.json"

    assert run.problems == ()
    assert "content_hash" not in json.loads(packet_path.read_bytes())
    assert run.results[0]["content_hash"] == packet["content_hash"]


def test_mixed_hit_and_miss_stays_packet_ordered_and_calls_once(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache"
    _run(cache_path, (_validated("X-1"),))
    calls: list[str] = []
    factory_calls = 0

    def adapter(prompt: str) -> ProviderCallResult:
        calls.append(prompt)
        return _response_for_prompt(prompt)

    def factory() -> ProviderAdapter:
        nonlocal factory_calls
        factory_calls += 1
        return adapter

    run = _run(
        cache_path,
        (_validated("X-1"), _validated("X-2")),
        adapter_factory=factory,
    )

    assert run.problems == ()
    assert [row["packet_id"] for row in run.results] == [
        "docs/specs/01-X.md#X-1",
        "docs/specs/01-X.md#X-2",
    ]
    assert run.cache_hits == 1
    assert run.cache_misses == 1
    assert run.provider_calls == 1
    assert factory_calls == 1
    assert len(calls) == 1


def test_cache_inspection_plans_misses_then_hits_without_provider_or_writes(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache"
    before = inspect_semantic_cache(
        packets=(_validated("X-1"), _validated("X-2")),
        cache_path=cache_path,
        cache_mode="read-write",
        provider_identity=PROVIDER,
        request_identity=REQUEST,
        search_epoch="1",
    )

    assert before.problems == ()
    assert before.planned_hits == 0
    assert before.planned_misses == 2
    assert before.planned_miss_packet_ids == (
        "docs/specs/01-X.md#X-1",
        "docs/specs/01-X.md#X-2",
    )
    assert not cache_path.exists()

    _run(cache_path, (_validated("X-1"),))
    after = inspect_semantic_cache(
        packets=(_validated("X-1"), _validated("X-2")),
        cache_path=cache_path,
        cache_mode="read-write",
        provider_identity=PROVIDER,
        request_identity=REQUEST,
        search_epoch="1",
    )

    assert after.problems == ()
    assert after.planned_hits == 1
    assert after.planned_misses == 1
    assert after.planned_miss_packet_ids == ("docs/specs/01-X.md#X-2",)


def test_cache_inspection_require_reports_missing_and_off_ignores_cache(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache"
    required = inspect_semantic_cache(
        packets=(_validated(),),
        cache_path=cache_path,
        cache_mode="require",
        provider_identity=PROVIDER,
        request_identity=REQUEST,
        search_epoch="1",
    )
    off = inspect_semantic_cache(
        packets=(_validated(cache_eligible=False),),
        cache_path=cache_path,
        cache_mode="off",
        provider_identity=PROVIDER,
        request_identity=REQUEST,
        search_epoch="1",
    )

    assert required.planned_hits == 0
    assert required.planned_misses == 1
    assert required.problems[0].stage == "completeness"
    assert required.problems[0].code == "incomplete_result"
    assert off.problems == ()
    assert off.planned_hits == 0
    assert off.planned_misses == 1
    assert not cache_path.exists()


def test_runtime_deadline_stops_later_provider_calls_and_reports_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0
    moments = iter((0.0, 0.0, 2.0))

    def adapter(prompt: str) -> ProviderCallResult:
        nonlocal calls
        calls += 1
        return _response_for_prompt(prompt)

    monkeypatch.setattr(
        "backstitch.semantic_cache.time.monotonic", lambda: next(moments)
    )
    run = analyze_with_cache(
        packets=(_validated("X-1"), _validated("X-2")),
        cache_path=tmp_path / "unused",
        cache_mode="off",
        provider_identity=PROVIDER,
        request_identity=REQUEST,
        adapter_factory=lambda: adapter,
        search_epoch="1",
        lock_wait_timeout_seconds=1,
        runtime_deadline=1.0,
    )

    assert calls == run.provider_calls == 1
    assert len(run.results) == 1
    assert run.problems[-1].stage == "budget"
    assert run.problems[-1].code == "budget_exceeded"


def test_runtime_deadline_expiring_during_factory_prevents_provider_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backstitch.semantic_cache as semantic_cache

    clock = iter((0.0, 2.0))
    monkeypatch.setattr(semantic_cache.time, "monotonic", lambda: next(clock))
    provider_calls = 0

    def factory() -> ProviderAdapter:
        def call(prompt: str) -> ProviderCallResult:
            nonlocal provider_calls
            provider_calls += 1
            return _response_for_prompt(prompt)

        return call

    run = analyze_with_cache(
        packets=(_validated(),),
        cache_path=tmp_path / "cache",
        cache_mode="off",
        provider_identity=PROVIDER,
        request_identity=REQUEST,
        adapter_factory=factory,
        search_epoch="1",
        lock_wait_timeout_seconds=1,
        runtime_deadline=1.0,
    )

    assert run.provider_calls == 0
    assert run.problems[0].stage == "budget"
    assert run.problems[0].code == "budget_exceeded"
    assert provider_calls == 0


@pytest.mark.parametrize("change", ["provider", "request", "epoch", "prompt"])
def test_every_inference_identity_family_creates_a_cache_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    from dataclasses import replace

    cache_path = tmp_path / "cache"
    _run(cache_path, (_validated(),))
    provider_identity = PROVIDER
    request_identity = REQUEST
    search_epoch = "1"
    if change == "provider":
        provider_identity = replace(PROVIDER, model_revision="2026-01-02")
    elif change == "request":
        request_identity = replace(REQUEST, seed=43)
    elif change == "epoch":
        search_epoch = "2"
    else:
        monkeypatch.setattr(
            "backstitch.semantic_identity.prompt_instruction_bytes",
            lambda kind: b"changed prompt bytes\n",
        )

    run = _run(
        cache_path,
        (_validated(),),
        provider_identity=provider_identity,
        request_identity=request_identity,
        search_epoch=search_epoch,
    )

    assert run.problems == ()
    assert run.cache_hits == 0
    assert run.cache_misses == 1
    assert run.provider_calls == 1
    assert len(list((cache_path / "packets").glob("*.json"))) == 1
    assert len(list((cache_path / "results").glob("*.json"))) == 2


def test_analyzer_sends_the_prompt_bytes_captured_by_its_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import backstitch.semantic_cache as semantic_cache
    import backstitch.semantic_packets as semantic_packets

    original_build = semantic_cache.build_inference_identity
    identities = []

    def build_then_change_resource(*args: Any, **kwargs: Any) -> Any:
        identity = original_build(*args, **kwargs)
        identities.append(identity)
        monkeypatch.setattr(
            semantic_packets,
            "prompt_instruction_bytes",
            lambda kind: b"changed after identity\n",
        )
        return identity

    observed: list[bytes] = []

    def adapter(prompt: str) -> ProviderCallResult:
        observed.append(prompt.encode("utf-8"))
        return _response_for_prompt(prompt)

    monkeypatch.setattr(
        semantic_cache, "build_inference_identity", build_then_change_resource
    )
    run = _run(
        tmp_path / "unused",
        (_validated(),),
        cache_mode="off",
        adapter_factory=lambda: adapter,
    )

    assert run.problems == ()
    assert len(identities) == len(observed) == 1
    identity = identities[0]
    assert observed[0].startswith(identity.prompt_bytes + b"\n\n")
    assert (
        hashlib.sha256(identity.prompt_bytes).hexdigest()
        == identity.contract["prompt"]["sha256"]
    )


def test_off_mode_ignores_cache_and_cache_ineligible_is_rejected_in_cached_modes(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache"
    corrupt = cache_path / "results" / ("a" * 64 + ".json")
    corrupt.parent.mkdir(parents=True)
    corrupt.write_text("corrupt", encoding="utf-8")

    off = _run(cache_path, (_validated(cache_eligible=False),), cache_mode="off")
    before = corrupt.read_bytes()
    rejected = _run(cache_path, (_validated(cache_eligible=False),))

    assert off.problems == ()
    assert off.provider_calls == 1
    assert off.cache_hits == off.cache_misses == 0
    assert corrupt.read_bytes() == before
    assert rejected.results == ()
    assert rejected.problems[0].stage == "input"
    assert rejected.problems[0].code == "invalid_input"
    assert rejected.provider_calls == 0


def test_off_mode_does_not_even_stat_the_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "backstitch.semantic_cache._path_exists",
        lambda path: (_ for _ in ()).throw(AssertionError("cache was inspected")),
    )

    run = _run(tmp_path / "cache", (_validated(),), cache_mode="off")

    assert run.problems == ()
    assert run.provider_calls == 1


def test_require_hit_does_not_recreate_an_unneeded_guard(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache"
    populated = _run(cache_path, (_validated(),))
    guard_dir = cache_path / "guards"
    for path in guard_dir.iterdir():
        path.unlink()
    guard_dir.rmdir()

    replay = _run(
        cache_path,
        (_validated(),),
        cache_mode="require",
        adapter_factory=None,
    )

    assert replay.problems == ()
    assert replay.result_jsonl == populated.result_jsonl
    assert not guard_dir.exists()


def test_invalid_search_epoch_fails_before_cache_or_adapter(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache"

    run = _run(cache_path, (_validated(),), search_epoch="   ")

    assert run.results == ()
    assert run.problems[0].stage == "config"
    assert run.provider_calls == 0
    assert not cache_path.exists()


def test_required_miss_and_duplicate_ids_fail_before_adapter_or_mutation(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache"
    required = _run(
        cache_path,
        (_validated(),),
        cache_mode="require",
        adapter_factory=None,
    )
    duplicate = _run(
        cache_path,
        (_validated(), _validated()),
        adapter_factory=lambda: (_ for _ in ()).throw(AssertionError()),
    )

    assert required.results == ()
    assert required.problems[0].stage == "completeness"
    assert required.problems[0].code == "incomplete_result"
    assert required.provider_calls == 0
    assert not cache_path.exists()
    assert duplicate.results == ()
    assert duplicate.problems[0].code == "invalid_input"
    assert duplicate.provider_calls == 0
    assert not cache_path.exists()


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("extra-provenance", "corrupt_cache"),
        ("stale-contract", "stale_cache"),
        ("forged-evidence", "corrupt_cache"),
    ],
)
def test_cache_hit_revalidates_closed_schema_identity_and_packet_local_evidence(
    tmp_path: Path, mutation: str, code: str
) -> None:
    cache_path = tmp_path / "cache"
    packet = _packet()
    _run(cache_path, (_validated(),))
    identity = build_inference_identity(packet, PROVIDER, REQUEST)
    path = cache_path / "results" / f"{identity.analysis_key}.json"
    value = json.loads(path.read_bytes())
    if mutation == "extra-provenance":
        value["provenance"]["headers"] = {"secret": "must not persist"}
    elif mutation == "stale-contract":
        value["inference_contract"]["search_epoch"] = "other"
    else:
        value["result"]["classification"] = "missing_trace"
        value["result"]["evidence"] = []
    path.write_bytes(canonical_json_bytes(value))

    inspection = inspect_semantic_cache(
        packets=(_validated(),),
        cache_path=cache_path,
        cache_mode="require",
        provider_identity=PROVIDER,
        request_identity=REQUEST,
        search_epoch="1",
    )

    replay = _run(
        cache_path,
        (_validated(),),
        cache_mode="require",
        adapter_factory=None,
    )

    assert inspection.problems[0].code == code
    assert replay.results == ()
    assert replay.problems[0].code == code
    assert replay.provider_calls == 0


@pytest.mark.parametrize("location", ["top", "prompt", "provider", "request"])
def test_unknown_inference_contract_fields_are_corruption_not_staleness(
    tmp_path: Path, location: str
) -> None:
    cache_path = tmp_path / "cache"
    packet = _packet()
    _run(cache_path, (_validated(),))
    identity = build_inference_identity(packet, PROVIDER, REQUEST)
    path = cache_path / "results" / f"{identity.analysis_key}.json"
    value = json.loads(path.read_bytes())
    target = (
        value["inference_contract"]
        if location == "top"
        else value["inference_contract"][location]
    )
    target["unknown"] = 1
    path.write_bytes(canonical_json_bytes(value))

    replay = _run(
        cache_path,
        (_validated(),),
        cache_mode="require",
        adapter_factory=None,
    )

    assert replay.results == ()
    assert replay.problems[0].code == "corrupt_cache"
    assert replay.provider_calls == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [("schema_version", True), ("analysis_key", True)],
)
def test_malformed_result_identity_fields_are_corruption(
    tmp_path: Path, field: str, value: object
) -> None:
    cache_path = tmp_path / "cache"
    packet = _packet()
    _run(cache_path, (_validated(),))
    identity = build_inference_identity(packet, PROVIDER, REQUEST)
    path = cache_path / "results" / f"{identity.analysis_key}.json"
    cached = json.loads(path.read_bytes())
    cached[field] = value
    path.write_bytes(canonical_json_bytes(cached))

    replay = _run(
        cache_path,
        (_validated(),),
        cache_mode="require",
        adapter_factory=None,
    )

    assert replay.results == ()
    assert replay.problems[0].code == "corrupt_cache"


def test_boolean_lock_schema_version_is_corruption(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache"
    packet = _packet()
    identity = build_inference_identity(packet, PROVIDER, REQUEST)
    lock_path = cache_path / "locks" / f"{identity.analysis_key}.lock"
    lock_path.parent.mkdir(parents=True)
    lock = {
        "schema_version": True,
        "object_type": "semantic-lock",
        "analysis_key": identity.analysis_key,
        "owner_token": "f" * 64,
        "pid": 123,
        "host": "other-host",
        "created_at_utc": datetime.now(UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
    }
    lock_path.write_bytes(canonical_json_bytes(lock))

    run = _run(
        cache_path,
        (_validated(),),
        adapter_factory=lambda: (_ for _ in ()).throw(
            AssertionError("malformed lock constructed adapter")
        ),
    )

    assert run.results == ()
    assert run.problems[0].code == "corrupt_cache"
    assert run.provider_calls == 0


@pytest.mark.parametrize("mutation", ["missing-packet", "noncanonical-result"])
def test_result_without_packet_or_with_noncanonical_bytes_is_corruption(
    tmp_path: Path, mutation: str
) -> None:
    cache_path = tmp_path / "cache"
    packet = _packet()
    _run(cache_path, (_validated(),))
    identity = build_inference_identity(packet, PROVIDER, REQUEST)
    if mutation == "missing-packet":
        (cache_path / "packets" / f"{packet['packet_hash']}.json").unlink()
    else:
        result_path = cache_path / "results" / f"{identity.analysis_key}.json"
        result_path.write_bytes(result_path.read_bytes() + b"\n")

    replay = _run(
        cache_path,
        (_validated(),),
        cache_mode="require",
        adapter_factory=None,
    )

    assert replay.results == ()
    assert replay.problems[0].code == "corrupt_cache"
    assert replay.provider_calls == 0


def test_single_flight_waiter_never_calls_and_reuses_owner_result(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache"
    entered = threading.Event()
    release = threading.Event()
    calls = 0

    def owner_adapter(prompt: str) -> ProviderCallResult:
        nonlocal calls
        calls += 1
        entered.set()
        assert release.wait(timeout=2)
        return _response_for_prompt(prompt)

    with ThreadPoolExecutor(max_workers=2) as pool:
        owner = pool.submit(
            _run,
            cache_path,
            (_validated(),),
            adapter_factory=lambda: owner_adapter,
        )
        assert entered.wait(timeout=2)
        waiter = pool.submit(
            _run,
            cache_path,
            (_validated(),),
            adapter_factory=lambda: (_ for _ in ()).throw(
                AssertionError("waiter constructed adapter")
            ),
        )
        release.set()
        owner_run = owner.result(timeout=2)
        waiter_run = waiter.result(timeout=2)

    assert owner_run.problems == waiter_run.problems == ()
    assert owner_run.result_jsonl == waiter_run.result_jsonl
    assert calls == 1
    assert owner_run.provider_calls == 1
    assert waiter_run.provider_calls == 0
    assert waiter_run.cache_hits == 1
    assert waiter_run.kind_counts == {
        "cache_hits": {"section": 1, "invariant": 0, "suppression": 0},
        "cache_misses": {"section": 0, "invariant": 0, "suppression": 0},
        "provider_calls": {"section": 0, "invariant": 0, "suppression": 0},
    }


def test_waiter_accepts_result_published_before_lock_reopen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Owner completion after FileExists is a hit, not corrupt cache."""

    import backstitch.semantic_cache as semantic_cache

    cache_path = tmp_path / "cache"
    packet = _packet()
    populated = _run(cache_path, (_validated(),))
    identity = build_inference_identity(packet, PROVIDER, REQUEST)
    result_path = cache_path / "results" / f"{identity.analysis_key}.json"
    result_bytes = result_path.read_bytes()
    result_path.unlink()
    original_link = semantic_cache._link_candidate

    def complete_owner_before_waiter_reopens(path: Path, content: bytes) -> bool:
        if path.parent.name == "locks":
            result_path.write_bytes(result_bytes)
            return False
        return original_link(path, content)

    monkeypatch.setattr(
        semantic_cache, "_link_candidate", complete_owner_before_waiter_reopens
    )
    replay = _run(
        cache_path,
        (_validated(),),
        adapter_factory=lambda: (_ for _ in ()).throw(
            AssertionError("waiter constructed adapter")
        ),
    )

    assert replay.problems == ()
    assert replay.result_jsonl == populated.result_jsonl
    assert replay.cache_hits == 1
    assert replay.provider_calls == 0


def test_waiter_allows_sequential_valid_lock_owners_until_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A waiter owns no lock and must tolerate owner A yielding to owner B."""

    import backstitch.semantic_cache as semantic_cache

    cache_path = tmp_path / "cache"
    packet = _packet()
    populated = _run(cache_path, (_validated(),))
    identity = build_inference_identity(packet, PROVIDER, REQUEST)
    result_path = cache_path / "results" / f"{identity.analysis_key}.json"
    result_bytes = result_path.read_bytes()
    result_path.unlink()
    lock_path = cache_path / "locks" / f"{identity.analysis_key}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    first_lock = {
        "schema_version": 1,
        "object_type": "semantic-lock",
        "analysis_key": identity.analysis_key,
        "owner_token": "a" * 64,
        "pid": 101,
        "host": "owner-a",
        "created_at_utc": datetime.now(UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
    }
    second_lock = dict(first_lock, owner_token="b" * 64, pid=202, host="owner-b")
    lock_path.write_bytes(canonical_json_bytes(first_lock))
    original_read = semantic_cache._read_valid_lock
    reads = 0

    def rotate_owner_then_publish(
        path: Path, analysis_key: str
    ) -> tuple[dict[str, Any], bytes]:
        nonlocal reads
        value = original_read(path, analysis_key)
        reads += 1
        if reads == 1:
            path.write_bytes(canonical_json_bytes(second_lock))
        elif reads == 2:
            result_path.write_bytes(result_bytes)
        return value

    monkeypatch.setattr(semantic_cache, "_read_valid_lock", rotate_owner_then_publish)
    replay = _run(
        cache_path,
        (_validated(),),
        adapter_factory=lambda: (_ for _ in ()).throw(
            AssertionError("waiter constructed adapter")
        ),
    )

    assert replay.problems == ()
    assert replay.result_jsonl == populated.result_jsonl
    assert replay.cache_hits == 1
    assert replay.provider_calls == 0
    assert lock_path.read_bytes() == canonical_json_bytes(second_lock)


def test_lock_timeout_never_steals_or_constructs_adapter(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache"
    packet = _packet()
    identity = build_inference_identity(packet, PROVIDER, REQUEST)
    lock_path = cache_path / "locks" / f"{identity.analysis_key}.lock"
    lock_path.parent.mkdir(parents=True)
    lock = {
        "schema_version": 1,
        "object_type": "semantic-lock",
        "analysis_key": identity.analysis_key,
        "owner_token": "f" * 64,
        "pid": 123,
        "host": "other-host",
        "created_at_utc": datetime.now(UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
    }
    lock_bytes = canonical_json_bytes(lock)
    lock_path.write_bytes(lock_bytes)

    run = _run(
        cache_path,
        (_validated(),),
        adapter_factory=lambda: (_ for _ in ()).throw(
            AssertionError("waiter constructed adapter")
        ),
        lock_wait_timeout_seconds=0.05,
    )

    assert run.results == ()
    assert run.problems[0].stage == "lock"
    assert run.problems[0].code == "lock_timeout"
    assert run.provider_calls == 0
    assert lock_path.read_bytes() == lock_bytes


def test_guard_wait_is_bounded_and_cleanup_fails_busy_without_mutation(
    tmp_path: Path,
) -> None:
    import backstitch.semantic_cache as semantic_cache

    cache_path = (tmp_path / "cache").resolve()
    packet = _packet()
    identity = build_inference_identity(packet, PROVIDER, REQUEST)
    lock_path = cache_path / "locks" / f"{identity.analysis_key}.lock"
    lock_path.parent.mkdir(parents=True)
    stale = {
        "schema_version": 1,
        "object_type": "semantic-lock",
        "analysis_key": identity.analysis_key,
        "owner_token": "c" * 64,
        "pid": 303,
        "host": "dead-owner",
        "created_at_utc": (datetime.now(UTC) - timedelta(hours=2))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
    }
    stale_bytes = canonical_json_bytes(stale)
    lock_path.write_bytes(stale_bytes)

    with semantic_cache._semantic_guard(
        cache_path,
        identity.analysis_key,
        timeout_seconds=1,
        poll_interval_seconds=0.01,
    ):
        run = _run(
            cache_path,
            (_validated(),),
            lock_wait_timeout_seconds=0.03,
            adapter_factory=lambda: (_ for _ in ()).throw(
                AssertionError("busy guard constructed adapter")
            ),
        )
        with pytest.raises(CacheProtocolError, match="guard is busy"):
            cleanup_lock(
                cache_path=cache_path,
                analysis_key=identity.analysis_key,
                lock_stale_seconds=1,
                reason="owner confirmed dead",
            )

    assert run.results == ()
    assert run.problems[0].code == "lock_timeout"
    assert run.provider_calls == 0
    assert lock_path.read_bytes() == stale_bytes


@pytest.mark.parametrize("route", ["resolve", "wait"])
def test_result_visible_before_guard_deadline_wins_over_guard_timeout(
    tmp_path: Path, route: str
) -> None:
    import backstitch.semantic_cache as semantic_cache

    cache_path = (tmp_path / "cache").resolve()
    packet = _packet()
    populated = _run(cache_path, (_validated(),))
    identity = build_inference_identity(packet, PROVIDER, REQUEST)
    result_path = cache_path / "results" / f"{identity.analysis_key}.json"
    result_bytes = result_path.read_bytes()
    result_path.unlink()
    lock_path = cache_path / "locks" / f"{identity.analysis_key}.lock"
    lock = {
        "schema_version": 1,
        "object_type": "semantic-lock",
        "analysis_key": identity.analysis_key,
        "owner_token": "e" * 64,
        "pid": 505,
        "host": "publishing-owner",
        "created_at_utc": datetime.now(UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
    }
    lock_path.write_bytes(canonical_json_bytes(lock))

    with semantic_cache._semantic_guard(
        cache_path,
        identity.analysis_key,
        timeout_seconds=1,
        poll_interval_seconds=0.01,
    ):
        with ThreadPoolExecutor(max_workers=1) as pool:
            future: Future[Any]
            if route == "resolve":
                future = pool.submit(
                    _run,
                    cache_path,
                    (_validated(),),
                    lock_wait_timeout_seconds=0.05,
                    adapter_factory=lambda: (_ for _ in ()).throw(
                        AssertionError("waiter constructed adapter")
                    ),
                )
            else:
                coordinator = semantic_cache._OwnershipCoordinator(
                    cache_path=cache_path,
                    key=identity.analysis_key,
                    lock_kind="analysis",
                    result_path=result_path,
                    lock_path=lock_path,
                    timeout_seconds=0.05,
                    poll_interval_seconds=0.01,
                    load_result=lambda: semantic_cache._load_hit(
                        cache_path, packet, identity, PROVIDER
                    ),
                    read_lock=lambda: semantic_cache._read_valid_lock(
                        lock_path, identity.analysis_key
                    )[1],
                    remove_lock=lambda expected: semantic_cache._remove_owned_lock(
                        lock_path, identity.analysis_key, expected
                    ),
                    wait_error="timed out waiting for semantic cache owner",
                    ownership_name="semantic lock",
                )
                future = pool.submit(
                    coordinator.wait,
                )
            threading.Event().wait(0.01)
            result_path.write_bytes(result_bytes)
            replay = future.result(timeout=0.2)

    if route == "resolve":
        assert replay.problems == ()
        assert replay.result_jsonl == populated.result_jsonl
        assert replay.cache_hits == 1
        assert replay.provider_calls == 0
    else:
        assert canonical_json_bytes(replay) + b"\n" == populated.result_jsonl


def test_cleanup_critical_section_precedes_fresh_analyzer_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import backstitch.semantic_cache as semantic_cache

    cache_path = (tmp_path / "cache").resolve()
    packet = _packet()
    identity = build_inference_identity(packet, PROVIDER, REQUEST)
    lock_path = cache_path / "locks" / f"{identity.analysis_key}.lock"
    lock_path.parent.mkdir(parents=True)
    stale = {
        "schema_version": 1,
        "object_type": "semantic-lock",
        "analysis_key": identity.analysis_key,
        "owner_token": "d" * 64,
        "pid": 404,
        "host": "dead-owner",
        "created_at_utc": (datetime.now(UTC) - timedelta(hours=2))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
    }
    lock_path.write_bytes(canonical_json_bytes(stale))
    audit_entered = threading.Event()
    release_cleanup = threading.Event()
    provider_entered = threading.Event()
    original_publish = semantic_cache._publish_immutable

    def pause_audit(path: Path, content: bytes) -> bool:
        if path.parent.name == "locks" and path.parent.parent.name == "audit":
            audit_entered.set()
            assert release_cleanup.wait(timeout=2)
        return original_publish(path, content)

    def respond(prompt: str) -> ProviderCallResult:
        provider_entered.set()
        return _response_for_prompt(prompt)

    monkeypatch.setattr(semantic_cache, "_publish_immutable", pause_audit)
    with ThreadPoolExecutor(max_workers=2) as pool:
        cleanup_future = pool.submit(
            cleanup_lock,
            cache_path=cache_path,
            analysis_key=identity.analysis_key,
            lock_stale_seconds=1,
            reason="owner confirmed dead",
        )
        assert audit_entered.wait(timeout=2)
        analyzer_future = pool.submit(
            _run,
            cache_path,
            (_validated(),),
            adapter_factory=lambda: respond,
        )
        assert not provider_entered.wait(timeout=0.05)
        release_cleanup.set()
        cleanup = cleanup_future.result(timeout=2)
        run = analyzer_future.result(timeout=2)

    assert cleanup.audit_path.is_file()
    assert run.problems == ()
    assert run.provider_calls == 1
    assert provider_entered.is_set()
    assert not lock_path.exists()


def test_provider_runs_outside_guard_but_publish_and_unlink_run_inside(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import backstitch.semantic_cache as semantic_cache

    cache_path = (tmp_path / "cache").resolve()
    identity = build_inference_identity(_packet(), PROVIDER, REQUEST)
    guard_path = cache_path / "guards" / f"{identity.analysis_key}.guard"
    original_publish = semantic_cache._publish_immutable
    original_remove = semantic_cache._remove_owned_lock
    observations: list[tuple[str, bool]] = []

    def process_guard_locked() -> bool:
        return semantic_cache._process_guard(guard_path).locked()

    def respond(prompt: str) -> ProviderCallResult:
        observations.append(("provider", process_guard_locked()))
        return _response_for_prompt(prompt)

    def observe_publish(path: Path, content: bytes) -> bool:
        if path.parent.name == "results":
            observations.append(("publish", process_guard_locked()))
        return original_publish(path, content)

    def observe_remove(path: Path, analysis_key: str, expected: bytes) -> None:
        observations.append(("remove", process_guard_locked()))
        original_remove(path, analysis_key, expected)

    monkeypatch.setattr(semantic_cache, "_publish_immutable", observe_publish)
    monkeypatch.setattr(semantic_cache, "_remove_owned_lock", observe_remove)

    run = _run(cache_path, (_validated(),), adapter_factory=lambda: respond)

    assert run.problems == ()
    assert observations == [
        ("provider", False),
        ("publish", True),
        ("remove", True),
    ]


def test_guard_unlocks_after_exception_and_both_platform_branches_fire(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import backstitch.semantic_cache as semantic_cache

    cache_path = (tmp_path / "cache").resolve()
    analysis_key = "6" * 64
    with pytest.raises(RuntimeError, match="inside guard"):
        with semantic_cache._semantic_guard(
            cache_path,
            analysis_key,
            timeout_seconds=1,
            poll_interval_seconds=0.01,
        ):
            raise RuntimeError("inside guard")
    with semantic_cache._semantic_guard(
        cache_path,
        analysis_key,
        timeout_seconds=1,
        poll_interval_seconds=0.01,
    ):
        pass

    class _Handle:
        def seek(self, offset: int) -> None:
            assert offset == 0

        def fileno(self) -> int:
            return 9

    calls: list[tuple[int, int, int]] = []
    fake_msvcrt = types.SimpleNamespace(
        LK_NBLCK=1,
        LK_UNLCK=2,
        locking=lambda fd, mode, count: calls.append((fd, mode, count)),
    )
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
    monkeypatch.setattr(semantic_cache.os, "name", "nt")
    handle = _Handle()
    assert semantic_cache._try_lock_guard(handle) is True
    semantic_cache._unlock_guard(handle)
    assert calls == [(9, 1, 1), (9, 2, 1)]


@pytest.mark.parametrize(
    "field",
    [
        "backend_id",
        "plugin_id",
        "plugin_distribution_name",
        "model_id",
        "model_revision",
    ],
)
def test_cached_modes_reject_blank_provider_identity_before_side_effects(
    tmp_path: Path, field: str
) -> None:
    from dataclasses import replace

    cache_path = tmp_path / "cache"
    if field == "backend_id":
        provider = replace(PROVIDER, backend_id="")
    elif field == "plugin_id":
        provider = replace(PROVIDER, plugin_id="")
    elif field == "plugin_distribution_name":
        provider = replace(
            PROVIDER,
            plugin_distribution_name="",
            plugin_distribution_version="",
        )
    elif field == "model_id":
        provider = replace(PROVIDER, model_id="")
    else:
        provider = replace(PROVIDER, model_revision="")

    run = _run(
        cache_path,
        (_validated(),),
        provider_identity=provider,
        adapter_factory=lambda: (_ for _ in ()).throw(
            AssertionError("invalid config constructed adapter")
        ),
    )

    assert run.results == ()
    assert run.problems[0].stage == "config"
    assert run.problems[0].code == "invalid_config"
    assert run.provider_calls == 0
    assert not cache_path.exists()


def test_owner_failure_removes_only_its_unchanged_lock(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache"
    packet = _packet()
    identity = build_inference_identity(packet, PROVIDER, REQUEST)

    def fail(prompt: str) -> ProviderCallResult:
        raise RuntimeError("provider down")

    run = _run(cache_path, (_validated(),), adapter_factory=lambda: fail)

    assert run.results == ()
    assert run.problems[0].stage == "provider"
    assert run.problems[0].code == "provider_failure"
    assert run.kind_counts == {
        "cache_hits": {"section": 0, "invariant": 0, "suppression": 0},
        "cache_misses": {"section": 1, "invariant": 0, "suppression": 0},
        "provider_calls": {"section": 1, "invariant": 0, "suppression": 0},
    }
    assert not (cache_path / "locks" / f"{identity.analysis_key}.lock").exists()


def test_analyzer_provider_failure_stays_primary_while_cleanup_waits_for_guard(
    tmp_path: Path,
) -> None:
    import backstitch.semantic_cache as semantic_cache

    cache_path = (tmp_path / "cache").resolve()
    identity = build_inference_identity(_packet(), PROVIDER, REQUEST)
    enter_contention = threading.Event()
    guard_acquired = threading.Event()
    release_guard = threading.Event()

    def hold_guard() -> None:
        assert enter_contention.wait(timeout=2)
        with semantic_cache._semantic_guard(
            cache_path,
            identity.analysis_key,
            timeout_seconds=1,
            poll_interval_seconds=0.01,
        ):
            guard_acquired.set()
            assert release_guard.wait(timeout=2)

    holder = threading.Thread(target=hold_guard, daemon=True)
    holder.start()

    def fail(_prompt: str) -> ProviderCallResult:
        enter_contention.set()
        assert guard_acquired.wait(timeout=2)
        threading.Timer(0.05, release_guard.set).start()
        raise RuntimeError("controlled analyzer outage")

    try:
        run = _run(cache_path, (_validated(),), adapter_factory=lambda: fail)
    finally:
        release_guard.set()
        holder.join(timeout=2)

    assert run.results == ()
    assert [
        (problem.stage, problem.code, problem.message) for problem in run.problems
    ] == [
        (
            "provider",
            "provider_failure",
            "model call failed: controlled analyzer outage",
        )
    ]
    assert not (cache_path / "locks" / f"{identity.analysis_key}.lock").exists()


@pytest.mark.parametrize("ownership_state", ["replaced", "absent"])
def test_analyzer_ownership_loss_serves_an_identical_published_result_as_hit(
    tmp_path: Path,
    ownership_state: str,
) -> None:
    cache_path = tmp_path / "cache"
    packet = _packet()
    identity = build_inference_identity(packet, PROVIDER, REQUEST)
    populated = _run(cache_path, (_validated(),))
    result_path = cache_path / "results" / f"{identity.analysis_key}.json"
    result_bytes = result_path.read_bytes()
    result_path.unlink()
    lock_path = cache_path / "locks" / f"{identity.analysis_key}.lock"

    def publish_winner(prompt: str) -> ProviderCallResult:
        if ownership_state == "replaced":
            lock = json.loads(lock_path.read_bytes())
            lock["owner_token"] = "e" * 64
            lock_path.write_bytes(canonical_json_bytes(lock))
        else:
            lock_path.unlink()
        result_path.write_bytes(result_bytes)
        return _response_for_prompt(prompt)

    replay = _run(
        cache_path,
        (_validated(),),
        adapter_factory=lambda: publish_winner,
    )

    assert replay.problems == ()
    assert replay.result_jsonl == populated.result_jsonl
    assert replay.cache_hits == 1
    assert replay.cache_misses == 0
    assert replay.provider_calls == 1
    assert replay.kind_counts == {
        "cache_hits": {"section": 1, "invariant": 0, "suppression": 0},
        "cache_misses": {"section": 0, "invariant": 0, "suppression": 0},
        "provider_calls": {"section": 1, "invariant": 0, "suppression": 0},
    }
    assert lock_path.exists() is (ownership_state == "replaced")


def test_owner_does_not_publish_or_delete_after_lock_token_changes(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache"
    packet = _packet()
    identity = build_inference_identity(packet, PROVIDER, REQUEST)
    lock_path = cache_path / "locks" / f"{identity.analysis_key}.lock"

    def mutate_lock(prompt: str) -> ProviderCallResult:
        lock = json.loads(lock_path.read_bytes())
        lock["owner_token"] = "e" * 64
        lock_path.write_bytes(canonical_json_bytes(lock))
        return _response_for_prompt(prompt)

    run = _run(cache_path, (_validated(),), adapter_factory=lambda: mutate_lock)

    assert run.results == ()
    assert run.problems[0].code == "corrupt_cache"
    assert run.provider_calls == 1
    assert lock_path.exists()
    assert not (cache_path / "results" / f"{identity.analysis_key}.json").exists()


def test_conflicting_result_publication_is_corruption_and_never_replaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import backstitch.semantic_cache as semantic_cache

    cache_path = tmp_path / "cache"
    original_publish = semantic_cache._publish_immutable
    conflict = b"{}"

    def publish_with_conflict(path: Path, content: bytes) -> bool:
        if path.parent.name == "results" and not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(conflict)
        return original_publish(path, content)

    monkeypatch.setattr(semantic_cache, "_publish_immutable", publish_with_conflict)
    run = _run(cache_path, (_validated(),))
    identity = build_inference_identity(_packet(), PROVIDER, REQUEST)
    result_path = cache_path / "results" / f"{identity.analysis_key}.json"

    assert run.results == ()
    assert run.problems[0].code == "corrupt_cache"
    assert run.provider_calls == 1
    assert result_path.read_bytes() == conflict


def test_symlinked_cache_subdirectory_is_rejected_before_provider(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache"
    outside = tmp_path / "outside"
    outside.mkdir()
    cache_path.mkdir()
    try:
        (cache_path / "packets").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    run = _run(cache_path, (_validated(),))

    assert run.results == ()
    assert run.problems[0].code == "corrupt_cache"
    assert run.provider_calls == 0
    assert list(outside.iterdir()) == []


def test_cache_root_below_symlinked_ancestor_is_canonicalized_once(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    cache_path = outside / "cache"
    cache_path.mkdir(parents=True)
    link = tmp_path / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    run = _run(link / "cache", (_validated(),))

    assert run.problems == ()
    assert run.provider_calls == 1
    assert (cache_path / "packets").is_dir()
    assert (cache_path / "results").is_dir()


def test_symlink_loop_cache_root_is_a_structured_error_for_analysis_and_cleanup(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    try:
        first.symlink_to(second)
        second.symlink_to(first)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    run = _run(first, (_validated(),))

    assert run.results == ()
    assert run.problems[0].code == "corrupt_cache"
    assert run.provider_calls == 0
    with pytest.raises(CacheProtocolError):
        cleanup_lock(
            cache_path=first,
            analysis_key="5" * 64,
            lock_stale_seconds=1,
            reason="loop probe",
        )


def test_cleanup_lock_publishes_closed_audit_before_removing_stale_lock(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache"
    analysis_key = "a" * 64
    lock_path = cache_path / "locks" / f"{analysis_key}.lock"
    lock_path.parent.mkdir(parents=True)
    created = datetime.now(UTC) - timedelta(hours=2)
    lock = {
        "schema_version": 1,
        "object_type": "semantic-lock",
        "analysis_key": analysis_key,
        "owner_token": "b" * 64,
        "pid": 123,
        "host": "host",
        "created_at_utc": created.isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        ),
    }
    lock_bytes = canonical_json_bytes(lock)
    lock_path.write_bytes(lock_bytes)
    before = lock_path.lstat()

    cleanup = cleanup_lock(
        cache_path=cache_path,
        analysis_key=analysis_key,
        lock_stale_seconds=60,
        reason="owner process was confirmed dead",
    )

    assert not lock_path.exists()
    audit = json.loads(cleanup.audit_path.read_bytes())
    assert set(audit) == {
        "schema_version",
        "object_type",
        "analysis_key",
        "lock_sha256",
        "lock_bytes",
        "lock_lstat",
        "reason",
        "cleaned_at_utc",
    }
    assert audit["object_type"] == "semantic-lock-cleanup"
    assert base64.b64decode(audit["lock_bytes"]) == lock_bytes
    assert audit["lock_sha256"] == hashlib.sha256(lock_bytes).hexdigest()
    assert audit["lock_lstat"] == {
        "mode": before.st_mode,
        "size": before.st_size,
        "mtime_ns": before.st_mtime_ns,
    }
    audit_sha = hashlib.sha256(canonical_json_bytes(audit)).hexdigest()
    assert cleanup.audit_path.name == f"{analysis_key}.{audit_sha}.json"
    assert cleanup.audit_path.read_bytes() == canonical_json_bytes(audit)


def test_cleanup_rejects_fresh_lock_and_uses_mtime_for_malformed_legacy_lock(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache"
    fresh_key = "c" * 64
    fresh_path = cache_path / "locks" / f"{fresh_key}.lock"
    fresh_path.parent.mkdir(parents=True)
    fresh = {
        "schema_version": 1,
        "object_type": "semantic-lock",
        "analysis_key": fresh_key,
        "owner_token": "d" * 64,
        "pid": 123,
        "host": "host",
        "created_at_utc": datetime.now(UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
    }
    fresh_path.write_bytes(canonical_json_bytes(fresh))

    with pytest.raises(CacheProtocolError, match="not stale"):
        cleanup_lock(
            cache_path=cache_path,
            analysis_key=fresh_key,
            lock_stale_seconds=60,
            reason="too early",
        )

    legacy_key = "e" * 64
    legacy_path = cache_path / "locks" / f"{legacy_key}.lock"
    legacy_path.write_bytes(b"legacy malformed lock")
    old = (datetime.now(UTC) - timedelta(hours=2)).timestamp()
    os.utime(legacy_path, (old, old))
    cleanup = cleanup_lock(
        cache_path=cache_path,
        analysis_key=legacy_key,
        lock_stale_seconds=60,
        reason="remove abandoned legacy lock",
    )

    assert cleanup.audit_path.exists()
    assert not legacy_path.exists()


def test_cleanup_rejects_absent_lock_and_preserves_changed_lock_after_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import backstitch.semantic_cache as semantic_cache

    cache_path = tmp_path / "cache"
    analysis_key = "9" * 64
    with pytest.raises(CacheProtocolError, match="does not exist"):
        cleanup_lock(
            cache_path=cache_path,
            analysis_key=analysis_key,
            lock_stale_seconds=1,
            reason="nothing to clean",
        )

    lock_path = cache_path / "locks" / f"{analysis_key}.lock"
    lock_path.parent.mkdir(parents=True)
    lock_path.write_bytes(b"malformed stale lock")
    old = (datetime.now(UTC) - timedelta(hours=2)).timestamp()
    os.utime(lock_path, (old, old))
    original_publish = semantic_cache._publish_immutable

    def publish_then_change(path: Path, content: bytes) -> bool:
        published = original_publish(path, content)
        if path.parent.name == "locks" and path.parent.parent.name == "audit":
            lock_path.write_bytes(b"changed after audit")
        return published

    monkeypatch.setattr(semantic_cache, "_publish_immutable", publish_then_change)
    with pytest.raises(CacheProtocolError, match="changed after cleanup audit"):
        cleanup_lock(
            cache_path=cache_path,
            analysis_key=analysis_key,
            lock_stale_seconds=1,
            reason="owner dead",
        )

    assert lock_path.read_bytes() == b"changed after audit"
    assert list((cache_path / "audit" / "locks").glob("*.json"))


def test_hard_link_publication_failure_is_a_cache_problem_before_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import errno

    monkeypatch.setattr(
        "backstitch.semantic_cache.os.link",
        lambda source, target: (_ for _ in ()).throw(
            OSError(errno.EPERM, "hard links unsupported")
        ),
    )
    run = _run(tmp_path / "cache", (_validated(),))

    assert run.results == ()
    assert run.problems[0].stage == "cache"
    assert run.problems[0].code == "corrupt_cache"
    assert run.provider_calls == 0


def test_cleanup_lock_cli_uses_only_explicit_inputs_and_prints_audit_path(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache"
    analysis_key = "7" * 64
    lock_path = cache_path / "locks" / f"{analysis_key}.lock"
    lock_path.parent.mkdir(parents=True)
    lock_path.write_bytes(b"legacy stale lock")
    old = (datetime.now(UTC) - timedelta(hours=2)).timestamp()
    os.utime(lock_path, (old, old))
    (tmp_path / ".backstitch.toml").write_text("not valid toml", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "backstitch",
            "cache",
            "cleanup-lock",
            "--cache-path",
            str(cache_path),
            "--analysis-key",
            analysis_key,
            "--lock-stale-seconds",
            "1",
            "--reason",
            "owner confirmed dead",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()).is_file()
    assert not lock_path.exists()


def test_verifier_cleanup_uses_disjoint_lock_guard_and_audit_paths(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache"
    verify_key = "8" * 64
    lock_path = cache_path / "verify-locks" / f"{verify_key}.lock"
    lock_path.parent.mkdir(parents=True)
    lock_path.write_bytes(b"legacy stale verifier lock")
    old = (datetime.now(UTC) - timedelta(hours=2)).timestamp()
    os.utime(lock_path, (old, old))

    cleanup = cleanup_lock(
        cache_path=cache_path,
        verify_key=verify_key,
        lock_stale_seconds=1,
        reason="verifier owner confirmed dead",
    )

    assert not lock_path.exists()
    assert cleanup.audit_path.parent == cache_path / "audit" / "verify-locks"
    assert (cache_path / "verify-guards" / f"{verify_key}.guard").is_file()
    assert not (cache_path / "guards" / f"{verify_key}.guard").exists()
    audit = json.loads(cleanup.audit_path.read_text(encoding="utf-8"))
    assert audit["verify_key"] == verify_key
    assert "analysis_key" not in audit


def test_cleanup_requires_exactly_one_analysis_review_or_verify_key(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache"
    with pytest.raises(CacheProtocolError, match="exactly one"):
        cleanup_lock(
            cache_path=cache_path,
            lock_stale_seconds=1,
            reason="owner dead",
        )
    with pytest.raises(CacheProtocolError, match="exactly one"):
        cleanup_lock(
            cache_path=cache_path,
            analysis_key="1" * 64,
            review_key="3" * 64,
            verify_key="2" * 64,
            lock_stale_seconds=1,
            reason="owner dead",
        )


def test_cleanup_lock_cli_accepts_verify_key(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache"
    verify_key = "9" * 64
    lock_path = cache_path / "verify-locks" / f"{verify_key}.lock"
    lock_path.parent.mkdir(parents=True)
    lock_path.write_bytes(b"legacy stale verifier lock")
    old = (datetime.now(UTC) - timedelta(hours=2)).timestamp()
    os.utime(lock_path, (old, old))

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "backstitch",
            "cache",
            "cleanup-lock",
            "--cache-path",
            str(cache_path),
            "--verify-key",
            verify_key,
            "--lock-stale-seconds",
            "1",
            "--reason",
            "verifier owner confirmed dead",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()).is_file()
    assert not lock_path.exists()


def test_review_cleanup_uses_disjoint_closed_audit_and_cli_key(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache"
    review_key = "8" * 64
    lock_path = cache_path / "review-locks" / f"{review_key}.lock"
    lock_path.parent.mkdir(parents=True)
    lock_path.write_bytes(b"legacy stale review lock")
    old = (datetime.now(UTC) - timedelta(hours=2)).timestamp()
    os.utime(lock_path, (old, old))

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "backstitch",
            "cache",
            "cleanup-lock",
            "--cache-path",
            str(cache_path),
            "--review-key",
            review_key,
            "--lock-stale-seconds",
            "1",
            "--reason",
            "review owner confirmed dead",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    audit_path = Path(result.stdout.strip())
    assert audit_path.parent == cache_path / "audit" / "review-locks"
    assert not lock_path.exists()
    assert (cache_path / "review-guards" / f"{review_key}.guard").is_file()
    audit = json.loads(audit_path.read_bytes())
    assert set(audit) == {
        "schema_version",
        "object_type",
        "review_key",
        "lock_sha256",
        "lock_bytes",
        "lock_lstat",
        "reason",
        "cleaned_at_utc",
    }
    assert audit["object_type"] == "semantic-review-lock-cleanup"
    assert audit["review_key"] == review_key
