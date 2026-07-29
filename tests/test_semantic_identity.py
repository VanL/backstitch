"""Offline inference-contract identity.

Exercises offline inference identity before adapter construction.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Any, cast

import pytest

from backstitch.semantic_identity import (
    ProviderIdentity,
    RequestIdentity,
    build_analysis_identities,
    build_inference_identity,
    build_review_identity,
)
from backstitch.semantic_packets import semantic_packet_hash


def _packet() -> dict[str, object]:
    packet: dict[str, object] = {
        "schema_version": 2,
        "packet_id": "docs/specs/01-x.md#X-1",
        "kind": "section",
        "spec_path": "docs/specs/01-x.md",
        "section_id": "X-1",
        "title": "X",
        "section_text": "## X [X-1]",
        "section_start_line": 1,
        "owners": [],
        "tests": [],
        "issues": [],
        "packet_warnings": [],
    }
    packet["packet_hash"] = semantic_packet_hash(packet)
    return packet


def test_inference_identity_is_the_hash_of_the_closed_offline_contract() -> None:
    provider = ProviderIdentity(
        backend_id="llm",
        plugin_id="openai",
        model_id="gpt-test",
        model_revision="2026-01-01",
        adapter_id="backstitch.llm",
        adapter_version=1,
        llm_distribution_version="0.31",
        plugin_distribution_name="llm-openai",
        plugin_distribution_version="1.2.3",
    )
    request = RequestIdentity(
        json_mode="require",
        temperature=0.0,
        seed=42,
        max_tokens=512,
    )

    identity = build_inference_identity(_packet(), provider, request)

    expected = json.dumps(
        identity.contract,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    assert identity.contract["analysis_contract_version"] == 1
    assert identity.contract["search_epoch"] == "1"
    assert identity.analysis_key == hashlib.sha256(expected).hexdigest()

    changed_provider = build_inference_identity(
        _packet(), replace(provider, model_revision="2026-01-02"), request
    )
    changed_request = build_inference_identity(
        _packet(), provider, replace(request, seed=43)
    )
    assert changed_provider.analysis_key != identity.analysis_key
    assert changed_request.analysis_key != identity.analysis_key


@pytest.mark.parametrize(
    "kwargs",
    [
        {"json_mode": "bogus"},
        {"temperature": True},
        {"temperature": -0.1},
        {"temperature": 2.1},
        {"seed": True},
        {"seed": -1},
        {"seed": "1"},
        {"max_tokens": True},
        {"max_tokens": 1.5},
        {"max_tokens": 0},
    ],
)
def test_request_identity_rejects_noncanonical_runtime_values(
    kwargs: dict[str, Any],
) -> None:
    values: dict[str, Any] = {
        "json_mode": "require",
        "temperature": 0.0,
        "seed": 42,
        "max_tokens": 512,
    }
    values.update(kwargs)
    with pytest.raises(ValueError):
        RequestIdentity(**values)


def test_provider_and_contract_identity_reject_noncanonical_types() -> None:
    provider_values: dict[str, Any] = {
        "backend_id": "llm",
        "plugin_id": "",
        "model_id": "",
        "model_revision": "",
        "adapter_id": "backstitch.llm",
        "adapter_version": 1,
        "llm_distribution_version": "0.31",
        "plugin_distribution_name": "",
        "plugin_distribution_version": "",
    }
    for field, value in (("backend_id", 1), ("adapter_version", True)):
        changed = dict(provider_values, **{field: value})
        with pytest.raises(ValueError):
            ProviderIdentity(**changed)

    provider = ProviderIdentity(**provider_values)
    request = RequestIdentity("off", 0.0, 42, 512)
    with pytest.raises(ValueError):
        build_inference_identity(
            _packet(),
            provider,
            request,
            analysis_contract_version=cast(Any, 1.5),
        )
    with pytest.raises(ValueError):
        build_inference_identity(_packet(), provider, request, search_epoch=" ")


@pytest.mark.parametrize(
    "overrides",
    [
        {"adapter_id": ""},
        {"adapter_id": "   "},
        {"llm_distribution_version": ""},
        {"llm_distribution_version": "   "},
        {
            "plugin_distribution_name": "",
            "plugin_distribution_version": "1.2.3",
        },
        {
            "plugin_distribution_name": "llm-openai",
            "plugin_distribution_version": "",
        },
        {
            "plugin_distribution_name": "   ",
            "plugin_distribution_version": "1.2.3",
        },
        {
            "plugin_distribution_name": "llm-openai",
            "plugin_distribution_version": "   ",
        },
    ],
)
def test_provider_identity_rejects_invalid_unconditional_states(
    overrides: dict[str, str],
) -> None:
    values: dict[str, Any] = {
        "backend_id": "",
        "plugin_id": "",
        "model_id": "",
        "model_revision": "",
        "adapter_id": "backstitch.llm",
        "adapter_version": 1,
        "llm_distribution_version": "0.31",
        "plugin_distribution_name": "",
        "plugin_distribution_version": "",
    }
    values.update(overrides)

    with pytest.raises(ValueError):
        ProviderIdentity(**values)


def test_every_inference_contract_field_changes_analysis_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ProviderIdentity(
        "llm", "plugin", "model", "revision", "adapter", 1, "0.31", "dist", "1"
    )
    request = RequestIdentity("require", 0.0, 42, 512)
    packet = _packet()
    baseline = build_inference_identity(packet, provider, request)

    provider_changes = {
        "backend_id": "other-backend",
        "plugin_id": "other-plugin",
        "model_id": "other-model",
        "model_revision": "other-revision",
        "adapter_id": "other-adapter",
        "adapter_version": 2,
        "llm_distribution_version": "0.32",
        "plugin_distribution_name": "other-dist",
        "plugin_distribution_version": "2",
    }
    for field, value in provider_changes.items():
        changed_provider = cast(Any, replace)(provider, **{field: value})
        assert (
            build_inference_identity(packet, changed_provider, request).analysis_key
            != baseline.analysis_key
        ), field

    request_changes = {
        "json_mode": "off",
        "temperature": 0.5,
        "seed": 43,
        "max_tokens": 513,
    }
    for field, value in request_changes.items():
        changed_request = cast(Any, replace)(request, **{field: value})
        assert (
            build_inference_identity(packet, provider, changed_request).analysis_key
            != baseline.analysis_key
        ), field

    changed_packet = dict(packet, packet_hash="f" * 64)
    assert (
        build_inference_identity(changed_packet, provider, request).analysis_key
        != baseline.analysis_key
    )
    assert (
        build_inference_identity(
            packet, provider, request, analysis_contract_version=2
        ).analysis_key
        != baseline.analysis_key
    )
    assert (
        build_inference_identity(
            packet, provider, request, search_epoch="2"
        ).analysis_key
        != baseline.analysis_key
    )

    monkeypatch.setattr(
        "backstitch.semantic_identity.prompt_instruction_bytes",
        lambda kind: b"changed prompt bytes\n",
    )
    assert (
        build_inference_identity(packet, provider, request).analysis_key
        != baseline.analysis_key
    )


def test_review_identity_is_the_exact_provider_independent_contract() -> None:
    provider = ProviderIdentity(
        "llm", "plugin", "model", "revision", "adapter", 1, "0.31", "dist", "1"
    )
    request = RequestIdentity("require", 0.0, 42, 512)
    inference, review = build_analysis_identities(_packet(), provider, request)

    expected = (
        b'{"analysis_contract_version":1,"packet_hash":"'
        + str(_packet()["packet_hash"]).encode("ascii")
        + b'","prompt":{"id":"backstitch.section-analysis","sha256":'
        b'"1f0b6fc15b35f12d036bba49bb870c5a5b0f0654241f16c99e1503b102e7aede",'
        b'"version":3},"request":{"json_mode":"require","max_tokens":512,'
        b'"seed":42,"temperature":0.0},"search_epoch":"1"}'
    )

    assert review.contract_bytes == expected
    assert review.contract == json.loads(expected)
    assert review.review_key == hashlib.sha256(expected).hexdigest()
    assert inference.review_identity == review
    assert build_review_identity(_packet(), request) == review


def test_every_review_contract_field_changes_review_key_but_provider_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ProviderIdentity(
        "llm", "plugin", "model", "revision", "adapter", 1, "0.31", "dist", "1"
    )
    request = RequestIdentity("require", 0.0, 42, 512)
    packet = _packet()
    baseline = build_analysis_identities(packet, provider, request)

    changed_provider = replace(provider, model_revision="other-revision")
    changed_inference, changed_review = build_analysis_identities(
        packet, changed_provider, request
    )
    assert changed_inference.analysis_key != baseline[0].analysis_key
    assert changed_review.review_key == baseline[1].review_key

    changed_packet = dict(packet, packet_hash="f" * 64)
    assert (
        build_review_identity(changed_packet, request).review_key
        != baseline[1].review_key
    )
    assert (
        build_review_identity(packet, replace(request, seed=43)).review_key
        != baseline[1].review_key
    )
    assert (
        build_review_identity(packet, request, analysis_contract_version=2).review_key
        != baseline[1].review_key
    )
    assert (
        build_review_identity(packet, request, search_epoch="2").review_key
        != baseline[1].review_key
    )

    monkeypatch.setattr(
        "backstitch.semantic_identity.prompt_instruction_bytes",
        lambda kind: b"changed review prompt\n",
    )
    assert build_review_identity(packet, request).review_key != baseline[1].review_key
