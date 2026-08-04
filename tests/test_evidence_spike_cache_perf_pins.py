"""Pins for evidence-spike hardening Slices 4, 5a, and 5b.

The tests use public cache/CLI seams where possible and AST ownership
enumeration only for the deletion/consolidation contracts.
"""

from __future__ import annotations

import ast
import hashlib
import json
import threading
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from backstitch import cli
from backstitch.semantic_cache import (
    ProviderAdapter,
    ProviderCallResult,
    SemanticProvenance,
    VerificationWork,
    verify_with_cache,
)
from backstitch.semantic_evidence import normalize_model_result
from backstitch.semantic_identity import ProviderIdentity, RequestIdentity
from backstitch.semantic_packets import canonical_json_bytes, semantic_packet_hash
from backstitch.semantic_verification import (
    VerificationClaim,
    VerificationRequest,
    VerifyIdentity,
    build_verification_request,
    build_verify_identity,
    derive_verification_claim,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]


_PROVIDER = ProviderIdentity(
    backend_id="llm",
    plugin_id="test-plugin",
    model_id="test-model",
    model_revision="rev-1",
    adapter_id="backstitch.test",
    adapter_version=1,
    llm_distribution_version="1.0",
    plugin_distribution_name="test-plugin-dist",
    plugin_distribution_version="2.0",
)
_REQUEST = RequestIdentity("require", 0.0, 42, 512)
_PROVENANCE = SemanticProvenance(
    adapter_id=_PROVIDER.adapter_id,
    adapter_version=_PROVIDER.adapter_version,
    plugin_version=_PROVIDER.plugin_distribution_version,
    model_class="tests.EvidenceSpikeVerifier",
    provider_model_id=_PROVIDER.model_id,
    provider_model_revision=_PROVIDER.model_revision,
    response_id="verify-response",
    input_tokens=10,
    output_tokens=5,
)


def _verification_packet() -> dict[str, Any]:
    packet: dict[str, Any] = {
        "schema_version": 3,
        "packet_id": "docs/specs/core.md#CORE-1",
        "packet_hash": "",
        "kind": "section",
        "obligation_id": "docs/specs/core.md#CORE-1",
        "source_snapshot": {
            "snapshot_hash": "1" * 64,
            "obligation_state_hash": "2" * 64,
            "derivation_config_hash": "3" * 64,
        },
        "readiness": {
            "intent_state": "identified",
            "alignment_state": "complete",
            "disposition": "evaluate",
            "obligation_rung": "active",
            "gate_state": "executable",
            "required_roles": ["implementation"],
        },
        "requirement": {
            "role": "requirement",
            "path": "docs/specs/core.md",
            "identity": "CORE-1",
            "title": "Core",
            "start_line": 3,
            "end_line": 3,
            "text": "Must return one.",
        },
        "declared_evidence": [
            {
                "role": "implementation",
                "path": "pkg/core.py",
                "symbol": "run",
                "start_line": 8,
                "end_line": 9,
                "snippet": "def run():\n    return 2",
                "sources": [
                    {
                        "source_role": "implementation",
                        "receipt_hash": "4" * 64,
                        "relation_kinds": ["spec_mapping", "code_backlink"],
                        "reciprocity_state": "complete",
                    }
                ],
            }
        ],
        "counterevidence": [],
        "trace_summary": {
            "declared_counts": [],
            "candidate_counts": [],
            "relation_counts": [],
        },
        "evidence_regions": [
            {
                "role": "requirement",
                "path": "docs/specs/core.md",
                "start_line": 3,
                "end_line": 3,
            },
            {
                "role": "implementation",
                "path": "pkg/core.py",
                "start_line": 8,
                "end_line": 9,
            },
        ],
        "issues": [],
        "packet_warnings": [],
    }
    packet["packet_hash"] = semantic_packet_hash(packet)
    return packet


def _verification_contracts() -> tuple[VerificationWork, dict[str, Any]]:
    packet = _verification_packet()
    analyzer_result = normalize_model_result(
        packet,
        {
            "packet_id": packet["packet_id"],
            "classification": "confirmed_mismatch",
            "confidence": 0.9,
            "rationale": "This rationale is excluded from verifier input.",
            "summary": "Implementation returns two, not one.",
            "evidence": packet["evidence_regions"],
        },
        analysis_key="7" * 64,
    )
    claim: VerificationClaim = derive_verification_claim(packet, analyzer_result)
    request: VerificationRequest = build_verification_request(packet, claim)
    identity: VerifyIdentity = build_verify_identity(
        request,
        claim,
        _PROVIDER,
        _REQUEST,
        base_search_epoch="1",
    )
    response = {
        "packet_id": packet["packet_id"],
        "claim_hash": claim.claim_hash,
        "verdict": "support",
        "support_score": 0.95,
        "summary": "The bounded evidence supports the claim.",
        "evidence": [packet["evidence_regions"][1]],
    }
    return VerificationWork(packet, claim, request, identity, "1", "1"), response


def _verify(
    work: VerificationWork,
    cache_path: Path,
    adapter_factory: Any,
    *,
    cache_mode: str = "read-write",
) -> Any:
    return verify_with_cache(
        work_items=(work,),
        cache_path=cache_path,
        cache_mode=cache_mode,
        provider_identity=_PROVIDER,
        request_identity=_REQUEST,
        adapter_factory=adapter_factory,
        lock_wait_timeout_seconds=1,
        poll_interval_seconds=0.01,
    )


def test_provider_failure_remains_primary_while_verify_cleanup_waits_for_guard(
    tmp_path: Path,
) -> None:
    """Reproduce finding #6 at the real verifier lock/guard seam.

    The verifier owns a newly published lock when its provider raises. A second
    thread holds the persistent per-key guard for 50 ms while failure cleanup
    begins. Today cleanup requests a zero-second guard window, its lock-timeout
    exception replaces the provider failure, and the owned lock leaks. Slice 4
    must retry cleanup only under the guard, remove the unchanged owned lock once
    the guard recovers, and retain `provider_failure` as the sole primary problem.
    No guard-free unlink is permitted.
    """

    import backstitch.semantic_cache as semantic_cache

    work, _response = _verification_contracts()
    cache_path = (tmp_path / "cache").resolve()
    enter_contention = threading.Event()
    guard_acquired = threading.Event()
    release_guard = threading.Event()

    def hold_guard() -> None:
        assert enter_contention.wait(timeout=2)
        with semantic_cache._verify_guard(
            cache_path,
            work.identity.verify_key,
            timeout_seconds=1,
            poll_interval_seconds=0.01,
        ):
            guard_acquired.set()
            assert release_guard.wait(timeout=2)

    holder = threading.Thread(target=hold_guard, daemon=True)
    holder.start()

    def factory() -> ProviderAdapter:
        def fail(_prompt: str) -> ProviderCallResult:
            enter_contention.set()
            assert guard_acquired.wait(timeout=2)
            timer = threading.Timer(0.05, release_guard.set)
            timer.start()
            raise RuntimeError("controlled provider outage")

        return fail

    try:
        run = _verify(work, cache_path, factory)
    finally:
        release_guard.set()
        holder.join(timeout=2)

    lock_path = cache_path / "verify-locks" / f"{work.identity.verify_key}.lock"
    assert run.results == ()
    assert [(problem.stage, problem.code) for problem in run.problems] == [
        ("provider", "provider_failure")
    ]
    assert not lock_path.exists()


def test_persistent_guard_contention_has_a_fixed_retry_bound_and_deferred_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Eight failed guarded retries preserve the lock and disclose recovery."""

    from contextlib import contextmanager

    import backstitch.semantic_cache as semantic_cache

    work, _response = _verification_contracts()
    cache_path = (tmp_path / "cache").resolve()
    guard_path = cache_path / "verify-guards" / f"{work.identity.verify_key}.guard"
    lock_path = cache_path / "verify-locks" / f"{work.identity.verify_key}.lock"
    enter_contention = threading.Event()
    guard_acquired = threading.Event()
    release_guard = threading.Event()
    original_guard = semantic_cache._verify_guard
    guarded_calls = 0

    def hold_guard() -> None:
        assert enter_contention.wait(timeout=2)
        with original_guard(
            cache_path,
            work.identity.verify_key,
            timeout_seconds=1,
            poll_interval_seconds=0.01,
        ):
            guard_acquired.set()
            assert release_guard.wait(timeout=2)

    @contextmanager
    def count_guarded_calls(*args: Any, **kwargs: Any) -> Iterator[None]:
        nonlocal guarded_calls
        guarded_calls += 1
        with original_guard(*args, **kwargs):
            yield

    removals_under_guard: list[bool] = []
    original_remove = semantic_cache._remove_verify_lock

    def observe_remove(path: Path, key: str, expected: bytes) -> None:
        removals_under_guard.append(semantic_cache._process_guard(guard_path).locked())
        original_remove(path, key, expected)

    monkeypatch.setattr(semantic_cache, "_verify_guard", count_guarded_calls)
    monkeypatch.setattr(semantic_cache, "_remove_verify_lock", observe_remove)
    holder = threading.Thread(target=hold_guard, daemon=True)
    holder.start()

    def factory() -> ProviderAdapter:
        def fail(_prompt: str) -> ProviderCallResult:
            enter_contention.set()
            assert guard_acquired.wait(timeout=2)
            raise RuntimeError("persistent provider outage")

        return fail

    try:
        run = _verify(work, cache_path, factory)
        assert [(problem.stage, problem.code) for problem in run.problems] == [
            ("provider", "provider_failure")
        ]
        assert run.problems[0].message == (
            "verifier call failed: persistent provider outage"
        )
        assert "backstitch cache cleanup-lock" in caplog.text
        assert guarded_calls == 2 + semantic_cache._OWNED_FAILURE_CLEANUP_RETRY_LIMIT
        assert lock_path.exists()
        assert removals_under_guard == []
    finally:
        release_guard.set()
        holder.join(timeout=2)

    # The next guarded participant completes the unchanged owner's deferred
    # cleanup before entering its own critical section.
    with original_guard(
        cache_path,
        work.identity.verify_key,
        timeout_seconds=1,
        poll_interval_seconds=0.01,
    ):
        assert not lock_path.exists()
    assert removals_under_guard == [True]


def test_stolen_verify_lock_serves_an_identical_published_result_as_a_hit(
    tmp_path: Path,
) -> None:
    """Reproduce NM3 with a valid result published after ownership loss.

    A first run creates authoritative verifier packet/result bytes. The result
    is then hidden to force a miss. During the second provider call, a simulated
    winner replaces the lock token and publishes those exact valid result bytes.
    Today the original owner reports `corrupt_cache`. Slice 4 must validate and
    serve the now-published identical-key result as a hit, make no publication,
    and leave the replacement owner's lock untouched.
    """

    work, response = _verification_contracts()
    cache_path = tmp_path / "cache"

    def successful_factory() -> ProviderAdapter:
        return lambda _prompt: ProviderCallResult(json.dumps(response), _PROVENANCE)

    populated = _verify(work, cache_path, successful_factory)
    assert populated.problems == ()
    result_path = cache_path / "verify-results" / f"{work.identity.verify_key}.json"
    result_bytes = result_path.read_bytes()
    result_path.unlink()
    lock_path = cache_path / "verify-locks" / f"{work.identity.verify_key}.lock"

    def racing_factory() -> ProviderAdapter:
        def race(_prompt: str) -> ProviderCallResult:
            lock = json.loads(lock_path.read_bytes())
            lock["owner_token"] = "e" * 64
            lock_path.write_bytes(canonical_json_bytes(lock))
            result_path.write_bytes(result_bytes)
            return ProviderCallResult(json.dumps(response), _PROVENANCE)

        return race

    replay = _verify(work, cache_path, racing_factory)

    assert replay.problems == ()
    assert len(replay.results) == 1
    assert replay.cache_hits == 1
    assert replay.cache_misses == 0
    assert replay.provider_calls == 1
    assert lock_path.exists()


def test_verifier_sends_the_exact_prompt_bytes_hashed_into_its_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reproduce the prompt hash-at-use TOCTOU between identity and dispatch.

    Work identity is built while the prompt loader returns `identity prompt`.
    Before cache preflight and provider dispatch, the resource loader changes to
    `changed prompt`. Today validation rereads the resource and rejects the work
    (or dispatch would reread and send different bytes). Slice 4 must capture the
    prompt/request bytes once with the work identity, validate that closed value,
    and send the same bytes even if the resource changes afterward.
    """

    import backstitch.semantic_verification as semantic_verification

    identity_prompt = b"identity prompt\n"
    changed_prompt = b"changed prompt\n"
    monkeypatch.setattr(
        semantic_verification,
        "verification_prompt_bytes",
        lambda: identity_prompt,
    )
    work, response = _verification_contracts()
    monkeypatch.setattr(
        semantic_verification,
        "verification_prompt_bytes",
        lambda: changed_prompt,
    )
    observed: list[bytes] = []

    def factory() -> ProviderAdapter:
        def adapter(prompt: str) -> ProviderCallResult:
            observed.append(prompt.encode("utf-8"))
            return ProviderCallResult(json.dumps(response), _PROVENANCE)

        return adapter

    run = _verify(work, tmp_path / "unused", factory, cache_mode="off")

    assert run.problems == ()
    assert len(observed) == 1
    sent_prompt, sent_request = observed[0].split(b"\n\n", 1)
    expected_hash = work.identity.contract["prompt"]["sha256"]
    assert hashlib.sha256(sent_prompt + b"\n").hexdigest() == expected_hash
    assert sent_prompt + b"\n" == identity_prompt
    assert sent_request == canonical_json_bytes(work.request.value)


def _write_clean_check_repo(root: Path) -> None:
    (root / "docs/specs").mkdir(parents=True)
    (root / "pkg").mkdir()
    (root / "docs/specs/01-x.md").write_text(
        "## Thing [X-1]\n\n"
        "The thing must return true.\n\n"
        "_Implementation mapping_:\n\n"
        "- `pkg/mod.py`\n",
        encoding="utf-8",
    )
    (root / "pkg/mod.py").write_text(
        '"""Spec: docs/specs/01-x.md [X-1]"""\n\n'
        "def thing() -> bool:\n"
        "    return True\n",
        encoding="utf-8",
    )


def _run_check(root: Path) -> int:
    return cli.main(
        (
            "check",
            "--repo-root",
            str(root),
            "--no-config",
            "--spec-root",
            "docs/specs",
            "--code-root",
            "pkg",
            "--format",
            "json",
        )
    )


def test_default_check_performs_zero_static_syntax_fact_derivations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Tests-invariant: [INV.PERF.1]

    Reproduce the default-check regression on one valid mapped Python file.
    `parse_python_source` currently derives import/binding/reference facts for
    every file even though the deterministic resolver never consumes them.
    Slice 5a must keep ordinary structural parsing but make static-syntax fact
    derivation opt-in, so the public default check performs exactly zero calls
    to `_static_syntax_facts`.
    """

    import backstitch.code_parser as code_parser

    _write_clean_check_repo(tmp_path)
    calls = 0
    original = code_parser._static_syntax_facts

    def counted(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(code_parser, "_static_syntax_facts", counted)
    exit_code = _run_check(tmp_path)
    captured = capsys.readouterr()

    assert exit_code == 0, captured.out + captured.err
    assert calls == 0


def test_default_check_captures_an_already_covered_mapping_target_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Tests-invariant: [INV.PERF.1]

    Reproduce the snapshot-convergence overcapture. The declared target
    `pkg/mod.py` is already inside the configured code root and therefore fully
    represented by the first immutable capture. Today discovering that target
    changes `additional_paths` and forces a redundant second whole-repository
    capture. Slice 5a must accept the first snapshot when every derived target
    is already represented, while retaining recapture for unresolved/out-of-root
    targets.
    """

    import backstitch.obligation_runtime as obligation_runtime

    _write_clean_check_repo(tmp_path)
    calls = 0
    original = obligation_runtime.capture_repository_snapshot

    def counted(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(
        obligation_runtime,
        "capture_repository_snapshot",
        counted,
    )
    exit_code = _run_check(tmp_path)
    captured = capsys.readouterr()

    assert exit_code == 0, captured.out + captured.err
    assert calls == 1


def test_self_corpus_default_check_uses_one_external_snapshot_capture(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Tests-invariant: [INV.PERF.1]

    The accepted capture owner may use its bounded internal convergence
    attempts, but the advertised default check enters that owner exactly once.
    This self-corpus proof covers out-of-root path-only mapping targets that the
    small already-covered fixture does not contain.
    """

    import backstitch.obligation_runtime as obligation_runtime

    calls = 0
    original = obligation_runtime.capture_repository_snapshot

    def counted(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(
        obligation_runtime,
        "capture_repository_snapshot",
        counted,
    )
    exit_code = cli.main(("check", "--repo-root", str(_REPO_ROOT)))
    captured = capsys.readouterr()

    assert exit_code == 0, captured.out + captured.err
    assert calls == 1


def test_bare_self_check_resolves_once_without_extra_parse_or_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Tests-invariant: [INV.PERF.1]"""

    import backstitch.code_parser as code_parser
    import backstitch.obligation_runtime as obligation_runtime

    config_calls = 0
    snapshot_calls = 0
    syntax_calls = 0
    original_resolve = cli.resolve_config
    original_capture = obligation_runtime.capture_repository_snapshot
    original_syntax = code_parser._static_syntax_facts
    config = tmp_path / "bare-check.toml"
    config.write_text(
        (
            f'extend = "{(_REPO_ROOT / "pyproject.toml").as_posix()}"\n'
            'default_command = "check"\n'
        ),
        encoding="utf-8",
    )

    def counted_resolve(*args: Any, **kwargs: Any) -> Any:
        nonlocal config_calls
        config_calls += 1
        return original_resolve(*args, **kwargs)

    def counted_capture(*args: Any, **kwargs: Any) -> Any:
        nonlocal snapshot_calls
        snapshot_calls += 1
        return original_capture(*args, **kwargs)

    def counted_syntax(*args: Any, **kwargs: Any) -> Any:
        nonlocal syntax_calls
        syntax_calls += 1
        return original_syntax(*args, **kwargs)

    monkeypatch.chdir(_REPO_ROOT)
    monkeypatch.setattr(cli, "resolve_config", counted_resolve)
    monkeypatch.setattr(
        obligation_runtime,
        "capture_repository_snapshot",
        counted_capture,
    )
    monkeypatch.setattr(code_parser, "_static_syntax_facts", counted_syntax)

    exit_code = cli.main(("--config", str(config)))
    captured = capsys.readouterr()

    assert exit_code == 0, captured.out + captured.err
    assert config_calls == 1
    assert snapshot_calls == 1
    assert syntax_calls == 0


def _write_obligation_repo(root: Path, *, obligation_count: int = 1) -> None:
    for relative in ("docs/specs", "docs/plans", "backstitch", "extra", "tests"):
        (root / relative).mkdir(parents=True, exist_ok=True)
    sections = []
    for index in range(obligation_count):
        identity = f"WORK-{index + 1}"
        sections.append(
            f"## Worker contract {index + 1:03d} {('x' * 80)} [{identity}]\n\n"
            "The worker must return one stable result.\n"
        )
    if obligation_count == 1:
        sections.append(
            "\n_Implementation mapping_:\n\n"
            "- `backstitch/worker.py::run_worker`\n"
            "- `extra/outside.py::outside_worker`\n"
        )
    (root / "docs/specs/01-worker.md").write_text("\n".join(sections), encoding="utf-8")
    (root / "backstitch/worker.py").write_text(
        '"""Spec: docs/specs/01-worker.md [WORK-1]"""\n\n'
        "def run_worker() -> int:\n"
        "    return 1\n",
        encoding="utf-8",
    )
    (root / "extra/outside.py").write_text(
        "def outside_worker() -> str:\n    return 'outside configured code roots'\n",
        encoding="utf-8",
    )


def test_obligation_list_parses_each_unique_python_file_at_most_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Tests-invariant: [INV.PERF.1]

    Reproduce repeated Python parsing in the public obligation-list operation.
    The in-root mapped file is parsed by the normal code scan. The out-of-root
    path::symbol target is first parsed by mapping resolution. Both are later
    consulted while the obligation inventory derives atomic mapping targets.
    Counts are keyed by exact content SHA-256 so path aliases cannot hide
    duplicate deterministic work. Slice 5a must share one invocation-scoped
    parse product and leave every unique Python content hash with a count no
    greater than one.
    """

    import backstitch.obligation_runtime as obligation_runtime
    import backstitch.python_refs as python_refs

    _write_obligation_repo(tmp_path)
    counts: Counter[str] = Counter()
    original = python_refs.parse_python_source

    def counted(source: bytes) -> Any:
        counts[hashlib.sha256(source).hexdigest()] += 1
        return original(source)

    monkeypatch.setattr(python_refs, "parse_python_source", counted)
    monkeypatch.setattr(obligation_runtime, "parse_python_source", counted)
    exit_code = cli.main(
        (
            "obligation",
            "list",
            "--repo-root",
            str(tmp_path),
            "--no-config",
            "--format",
            "json",
        )
    )
    captured = capsys.readouterr()

    assert exit_code == 0, captured.out + captured.err
    assert counts
    assert max(counts.values()) <= 1, counts


@dataclass(frozen=True)
class _FunctionOwner:
    module: str
    function: str
    calls: frozenset[str]
    attributes: frozenset[str]


def _production_functions() -> Iterator[_FunctionOwner]:
    package = Path(__file__).resolve().parents[1] / "backstitch"
    for path in sorted(package.glob("*.py")):
        tree = ast.parse(path.read_bytes(), filename=path.as_posix())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            calls: set[str] = set()
            attributes: set[str] = set()
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    function = child.func
                    if isinstance(function, ast.Name):
                        calls.add(function.id)
                    elif isinstance(function, ast.Attribute):
                        calls.add(function.attr)
                if isinstance(child, ast.Attribute):
                    attributes.add(child.attr)
            yield _FunctionOwner(
                module=path.name,
                function=node.name,
                calls=frozenset(calls),
                attributes=frozenset(attributes),
            )


def test_live_scan_and_legacy_packet_twins_have_no_production_owner() -> None:
    """Tests-invariant: [INV.SCAN.1]

    Enumerate every production definition and call site for the three retired
    legacy entry points. Snapshot-backed scanning and
    `generate_source_aligned_packets` are the only production paths.
    """

    forbidden = {
        "scan_repository",
        "scan_repository_with_artifacts",
        "generate_packets",
    }
    owners = [
        (owner.module, owner.function, sorted(owner.calls.intersection(forbidden)))
        for owner in _production_functions()
        if owner.function in forbidden or owner.calls.intersection(forbidden)
    ]

    assert owners == []


def test_response_budget_decision_has_one_core_owner_outside_cli() -> None:
    """Reproduce D8's adapter-dependent response-budget ownership.

    Before the Slice 5 application seam, `_run_obligation` read
    `maximum_response_bytes` and synthesized `BUDGET_EXHAUSTED` in the CLI.
    The completed seam leaves no response-budget decision owner in `cli.py`
    and exactly one owner in `obligation_api.py`, where the decision is made
    from canonical core JSON before adapter rendering.
    """

    response_budget_owners = [
        owner
        for owner in _production_functions()
        if "maximum_response_bytes" in owner.attributes
    ]
    cli_owners = [
        owner.function for owner in response_budget_owners if owner.module == "cli.py"
    ]
    core_owners = [
        owner.function
        for owner in response_budget_owners
        if owner.module == "obligation_api.py"
    ]

    assert cli_owners == []
    assert len(core_owners) == 1


def test_staging_and_publication_protocol_has_exactly_one_production_owner() -> None:
    """Reproduce D10's two command-local staging/publication state machines.

    Both `_cmd_packets` and `_cmd_analyze` currently stage an ordered artifact
    set, publish it, and clean temporary files independently; the packets copy
    omits analyze's deterministic partial-publication accounting. Slice 5b must
    move that protocol behind one helper. This AST gate allows primitive staging
    and publication functions to remain separate, but requires exactly one
    production function to call both primitives and forbids direct CLI ownership.
    """

    protocol_owners = [
        owner
        for owner in _production_functions()
        if {"stage_artifact_bytes", "publish_staged_artifact"}.issubset(owner.calls)
    ]

    assert len(protocol_owners) == 1
    assert protocol_owners[0].module != "cli.py"
