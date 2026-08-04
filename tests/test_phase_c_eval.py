"""Provider-free Phase C packet/currentness qualification.

Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-12.2]
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import unicodedata
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any, cast

import pytest

from backstitch.semantic_cache import (
    ProviderAdapter,
    ProviderCallResult,
    SemanticProvenance,
)
from backstitch.semantic_identity import ProviderIdentity
from backstitch.semantic_packets import canonical_json_bytes

PHASE_C = Path(__file__).parent / "product_eval/phase_c"
MANIFEST = PHASE_C / "manifest.json"
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_TREE_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_CANDIDATE_ID = re.compile(r"^candidate:sha256:[0-9a-f]{64}$")


def _tree_hash(root: Path) -> str:
    rows: list[dict[str, object]] = []
    normalized_paths: dict[str, str] = {}

    def visit(directory: Path) -> None:
        entries = sorted(os.scandir(directory), key=lambda item: item.name)
        for entry in entries:
            path = Path(entry.path)
            mode = entry.stat(follow_symlinks=False).st_mode
            relative = path.relative_to(root).as_posix()
            normalized = unicodedata.normalize("NFC", relative)
            assert normalized_paths.setdefault(normalized, relative) == relative
            assert "\\" not in normalized and "\x00" not in normalized
            assert all(part not in {"", ".", ".."} for part in normalized.split("/"))
            assert not stat.S_ISLNK(mode)
            if stat.S_ISDIR(mode):
                visit(path)
                continue
            assert stat.S_ISREG(mode)
            content = path.read_bytes()
            rows.append(
                {
                    "path": normalized,
                    "raw_sha256": "sha256:" + hashlib.sha256(content).hexdigest(),
                    "byte_count": len(content),
                    "executable": bool(mode & stat.S_IXUSR),
                }
            )

    visit(root)
    rows.sort(key=lambda row: cast(str, row["path"]))
    value = {
        "schema_version": 1,
        "artifact": "backstitch-eval-fixture-tree",
        "files": rows,
    }
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _manifest() -> dict[str, Any]:
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _contained_tree_path(value: object) -> Path:
    assert isinstance(value, str) and value
    assert "\\" not in value and "\x00" not in value
    assert value == unicodedata.normalize("NFC", value)
    assert all(part not in {"", ".", ".."} for part in value.split("/"))
    relative = PurePosixPath(value)
    assert not relative.is_absolute()
    current = PHASE_C
    for part in relative.parts:
        current = current / part
        mode = current.lstat().st_mode
        assert not stat.S_ISLNK(mode)
    assert current.is_dir()
    assert current.resolve().is_relative_to(PHASE_C.resolve())
    return current


def _ordered_unique_strings(value: object) -> list[str]:
    assert isinstance(value, list)
    assert all(isinstance(item, str) and item for item in value)
    assert value == sorted(set(value))
    return cast(list[str], value)


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "backstitch", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _install_controlled_adapter(
    monkeypatch: pytest.MonkeyPatch,
    before_response: Callable[[dict[str, Any]], None] | None = None,
) -> list[str]:
    import backstitch.analysis_llm as analysis_llm

    packet_ids: list[str] = []

    def factory(*args: object, **kwargs: object) -> ProviderAdapter:
        provider = cast(ProviderIdentity, kwargs["provider_identity"])

        def call(prompt: str) -> ProviderCallResult:
            packet = json.loads(prompt.rsplit("\n\n", 1)[1])
            packet_ids.append(packet["packet_id"])
            if before_response is not None:
                before_response(packet)
            evidence = []
            if packet["kind"] == "invariant":
                evidence = [
                    next(
                        region
                        for region in packet["evidence_regions"]
                        if region["role"] == "test"
                    )
                ]
            return ProviderCallResult(
                json.dumps(
                    {
                        "packet_id": packet["packet_id"],
                        "classification": "ok",
                        "confidence": 0.9,
                        "rationale": "The controlled Phase C review is supported.",
                        "summary": "The captured obligation is supported.",
                        "evidence": evidence,
                    }
                ),
                SemanticProvenance(
                    adapter_id=provider.adapter_id,
                    adapter_version=provider.adapter_version,
                    plugin_version=provider.plugin_distribution_version or None,
                    model_class="tests.phase_c.ControlledModel",
                    provider_model_id=provider.model_id or None,
                    provider_model_revision=provider.model_revision or None,
                    response_id="phase-c-response",
                    input_tokens=10,
                    output_tokens=5,
                ),
            )

        return call

    monkeypatch.setattr(analysis_llm, "default_provider_adapter", factory)
    return packet_ids


def test_phase_c_manifest_is_closed_ordered_and_binds_every_tree() -> None:
    manifest = _manifest()

    assert set(manifest) == {"schema_version", "fixtures", "scenarios"}
    assert manifest["schema_version"] == 1
    fixtures = manifest["fixtures"]
    scenarios = manifest["scenarios"]
    assert isinstance(fixtures, list)
    assert isinstance(scenarios, list)
    fixture_id_rows = [row["fixture_id"] for row in fixtures]
    scenario_id_rows = [row["scenario_id"] for row in scenarios]
    assert fixture_id_rows == sorted(set(fixture_id_rows))
    assert scenario_id_rows == sorted(set(scenario_id_rows))
    fixture_ids = {row["fixture_id"] for row in fixtures}
    assert fixture_ids == {
        "aligned-base",
        "aligned-relevant",
        "aligned-unrelated",
        "alignment-debt",
        "all-skipped",
        "deterministic-failure",
    }
    fixture_paths = [row["tree_path"] for row in fixtures]
    assert fixture_paths == sorted(set(fixture_paths))
    fixture_outcomes: dict[str, str] = {}

    for fixture in fixtures:
        assert set(fixture) == {
            "fixture_id",
            "tree_path",
            "tree_sha256",
            "expected_obligation_ids",
            "expected_packet_atoms",
            "expected_current_generation",
        }
        assert isinstance(fixture["fixture_id"], str) and fixture["fixture_id"]
        root = _contained_tree_path(fixture["tree_path"])
        assert isinstance(fixture["tree_sha256"], str)
        assert _TREE_HASH.fullmatch(fixture["tree_sha256"])
        assert _tree_hash(root) == fixture["tree_sha256"]
        obligation_ids = _ordered_unique_strings(fixture["expected_obligation_ids"])
        atoms = fixture["expected_packet_atoms"]
        assert isinstance(atoms, list)
        atom_ids = [atom["obligation_id"] for atom in atoms]
        assert atom_ids == sorted(set(atom_ids))
        assert set(atom_ids).issubset(obligation_ids)
        for atom in atoms:
            assert set(atom) == {
                "obligation_id",
                "requirement_sha256",
                "declared_receipt_hashes",
                "counter_candidate_ids",
            }
            assert isinstance(atom["obligation_id"], str)
            assert isinstance(atom["requirement_sha256"], str)
            assert _HEX_64.fullmatch(atom["requirement_sha256"])
            receipts = _ordered_unique_strings(atom["declared_receipt_hashes"])
            assert all(_HEX_64.fullmatch(item) for item in receipts)
            candidate_ids = _ordered_unique_strings(atom["counter_candidate_ids"])
            assert all(_CANDIDATE_ID.fullmatch(item) for item in candidate_ids)
        generation = fixture["expected_current_generation"]
        assert isinstance(generation, dict)
        assert set(generation) == {"outcome", "exit_code", "blocking_codes"}
        assert generation["outcome"] in {
            "evaluated",
            "not_run_all_skipped",
            "alignment_debt",
            "deterministic_failure",
        }
        assert isinstance(generation["exit_code"], int) and not isinstance(
            generation["exit_code"], bool
        )
        blocking_codes = generation["blocking_codes"]
        assert isinstance(blocking_codes, list)
        assert all(isinstance(item, str) and item for item in blocking_codes)
        assert blocking_codes == list(dict.fromkeys(blocking_codes))
        expected_generation = {
            "evaluated": (0, []),
            "not_run_all_skipped": (0, []),
            "alignment_debt": (2, ["ALIGNMENT_DEBT"]),
        }
        if generation["outcome"] == "deterministic_failure":
            assert generation["exit_code"] == 1
            assert blocking_codes
        else:
            assert (
                generation["exit_code"],
                blocking_codes,
            ) == expected_generation[generation["outcome"]]
        fixture_outcomes[fixture["fixture_id"]] = generation["outcome"]

    scenario_kinds: set[str] = set()
    corrupt_artifacts: set[str] = set()
    for scenario in scenarios:
        assert set(scenario) == {
            "scenario_id",
            "kind",
            "source_fixture_id",
            "compare_fixture_id",
            "artifact_transform",
            "expected_currentness",
            "expected_packet_identity",
        }
        assert isinstance(scenario["scenario_id"], str) and scenario["scenario_id"]
        assert scenario["source_fixture_id"] in fixture_ids
        assert scenario["compare_fixture_id"] is None or (
            scenario["compare_fixture_id"] in fixture_ids
            and scenario["compare_fixture_id"] != scenario["source_fixture_id"]
        )
        assert scenario["kind"] in {
            "current_generation",
            "historical_replay",
            "stale_comparison",
            "relevant_mutation",
            "unrelated_mutation",
            "corrupt_artifact",
        }
        scenario_kinds.add(scenario["kind"])
        assert scenario["expected_currentness"] in {
            "current",
            "stale",
            "unverifiable",
            "corrupt",
        }
        assert scenario["expected_packet_identity"] in {
            "equal",
            "different",
            "not_applicable",
        }
        transform = scenario["artifact_transform"]
        kind = scenario["kind"]
        compare = scenario["compare_fixture_id"]
        if kind == "current_generation":
            assert compare is None and transform is None
            assert scenario["expected_currentness"] == "current"
            assert scenario["expected_packet_identity"] == "equal"
        elif kind == "historical_replay":
            assert compare is None and transform is None
            assert scenario["expected_currentness"] == "unverifiable"
            assert scenario["expected_packet_identity"] == "equal"
        elif kind == "stale_comparison":
            assert compare is not None and transform is None
            assert scenario["expected_currentness"] == "stale"
            assert scenario["expected_packet_identity"] in {"equal", "different"}
        elif kind in {"relevant_mutation", "unrelated_mutation"}:
            assert compare is not None and transform is None
            assert scenario["expected_currentness"] == "stale"
            assert scenario["expected_packet_identity"] == (
                "different" if kind == "relevant_mutation" else "equal"
            )
        else:
            assert kind == "corrupt_artifact"
            assert compare is None
            assert isinstance(transform, dict)
            assert set(transform) == {"artifact", "byte_offset", "xor_mask"}
            assert transform["artifact"] in {"packet_jsonl", "packet_report"}
            assert isinstance(transform["byte_offset"], int) and not isinstance(
                transform["byte_offset"], bool
            )
            assert transform["byte_offset"] >= 0
            assert isinstance(transform["xor_mask"], int) and not isinstance(
                transform["xor_mask"], bool
            )
            assert 1 <= transform["xor_mask"] <= 255
            assert scenario["expected_currentness"] == "corrupt"
            assert scenario["expected_packet_identity"] == "not_applicable"
            corrupt_artifacts.add(transform["artifact"])
        assert fixture_outcomes[scenario["source_fixture_id"]] not in {
            "alignment_debt",
            "deterministic_failure",
        }
        if compare is not None:
            assert fixture_outcomes[compare] not in {
                "alignment_debt",
                "deterministic_failure",
            }

    assert scenario_kinds == {
        "current_generation",
        "historical_replay",
        "stale_comparison",
        "relevant_mutation",
        "unrelated_mutation",
        "corrupt_artifact",
    }
    assert corrupt_artifacts == {"packet_jsonl", "packet_report"}
    assert set(fixture_outcomes.values()) == {
        "evaluated",
        "not_run_all_skipped",
        "alignment_debt",
        "deterministic_failure",
    }


def _packet_atoms(rows: list[dict[str, Any]]) -> list[dict[str, object]]:
    atoms: list[dict[str, object]] = []
    for row in rows:
        receipt_hashes = sorted(
            {
                source["receipt_hash"]
                for evidence in row["declared_evidence"]
                for source in evidence["sources"]
            }
        )
        atoms.append(
            {
                "obligation_id": row["obligation_id"],
                "requirement_sha256": hashlib.sha256(
                    row["requirement"]["text"].encode("utf-8")
                ).hexdigest(),
                "declared_receipt_hashes": receipt_hashes,
                "counter_candidate_ids": sorted(
                    candidate["candidate_id"]
                    for region in row["counterevidence"]
                    for candidate in region["candidates"]
                ),
            }
        )
    return atoms


def test_phase_c_packet_atoms_match_source_derived_gold(tmp_path: Path) -> None:
    manifest = _manifest()
    fixtures = {
        row["fixture_id"]: row
        for row in manifest["fixtures"]
        if row["fixture_id"].startswith("aligned-")
    }

    for fixture_id, fixture in fixtures.items():
        packet_path = tmp_path / f"{fixture_id}.jsonl"
        report_path = tmp_path / f"{fixture_id}-report.json"
        result = _run_cli(
            "packets",
            "--repo-root",
            str(PHASE_C / fixture["tree_path"]),
            "--kind",
            "all",
            "--output",
            str(packet_path),
            "--report",
            str(report_path),
        )
        assert result.returncode == 0, result.stderr
        rows = [
            json.loads(line)
            for line in packet_path.read_text(encoding="utf-8").splitlines()
        ]
        assert [row["obligation_id"] for row in rows] == fixture[
            "expected_obligation_ids"
        ]
        assert _packet_atoms(rows) == fixture["expected_packet_atoms"]


def test_phase_c_current_generation_outcomes_are_source_derived(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from backstitch.cli import main

    calls = _install_controlled_adapter(monkeypatch)
    manifest = _manifest()

    for fixture in manifest["fixtures"]:
        root = PHASE_C / fixture["tree_path"]
        list_exit = main(
            [
                "obligation",
                "list",
                "--repo-root",
                str(root),
                "--limit",
                "100",
                "--format",
                "json",
            ]
        )
        listed = json.loads(capsys.readouterr().out)
        assert list_exit == 0
        assert [
            entry["obligation_id"]
            for entry in listed["result"]["entries"]
            if entry["entry_type"] == "obligation"
        ] == fixture["expected_obligation_ids"]

        generation = fixture["expected_current_generation"]
        calls_before = len(calls)
        exit_code = main(
            [
                "analyze",
                "--repo-root",
                str(root),
                "--format",
                "json",
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == generation["exit_code"]
        if generation["outcome"] in {"evaluated", "not_run_all_skipped"}:
            report = json.loads(captured.out)
            assert report["scope"] == "current_repository"
            assert report["artifact_currentness"] == "current"
            assert report["source_provenance"] == "captured_current"
            assert report["semantic_status"] == generation["outcome"]
            assert generation["blocking_codes"] == []
        elif generation["outcome"] == "alignment_debt":
            assert captured.err == ""
            assert generation["blocking_codes"] == ["ALIGNMENT_DEBT"]
            preflight = json.loads(captured.out)
            assert preflight["operation"] == "analysis.preflight"
            assert [problem["code"] for problem in preflight["problems"]] == [
                "ALIGNMENT_DEBT"
            ]
        else:
            assert generation["outcome"] == "deterministic_failure"
            assert captured.err == ""
            check = json.loads(captured.out)
            assert (
                list(
                    dict.fromkeys(
                        issue["code"]
                        for issue in check["issues"]
                        if issue["severity"] == "error"
                    )
                )
                == generation["blocking_codes"]
            )
        expected_calls = (
            [atom["obligation_id"] for atom in fixture["expected_packet_atoms"]]
            if generation["outcome"] == "evaluated"
            else []
        )
        assert calls[calls_before:] == expected_calls


def _emit_packet_pair(fixture_id: str, root: Path) -> tuple[Path, Path]:
    packet_path = root / f"{fixture_id}.jsonl"
    report_path = root / f"{fixture_id}-report.json"
    result = _run_cli(
        "packets",
        "--repo-root",
        str(PHASE_C / f"fixtures/{fixture_id}"),
        "--kind",
        "all",
        "--output",
        str(packet_path),
        "--report",
        str(report_path),
    )
    assert result.returncode == 0, result.stderr
    return packet_path, report_path


def _packet_identity(path: Path) -> list[tuple[str, str]]:
    return [
        (row["packet_id"], row["packet_hash"])
        for row in (
            json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
        )
    ]


def _fixture_files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    }


_SCENARIOS = tuple(_manifest()["scenarios"])


@pytest.mark.parametrize(
    "scenario",
    _SCENARIOS,
    ids=[scenario["scenario_id"] for scenario in _SCENARIOS],
)
def test_phase_c_manifest_scenario(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    scenario: dict[str, Any],
) -> None:
    from backstitch.cli import main

    manifest = _manifest()
    fixtures = {row["fixture_id"]: row for row in manifest["fixtures"]}
    source_fixture = fixtures[scenario["source_fixture_id"]]
    source_root = _contained_tree_path(source_fixture["tree_path"])
    expected_calls = [
        atom["obligation_id"] for atom in source_fixture["expected_packet_atoms"]
    ]
    kind = scenario["kind"]

    if kind == "current_generation":
        expected_packets, _ = _emit_packet_pair(
            scenario["source_fixture_id"], tmp_path / "expected-current"
        )
        current_packets = tmp_path / "current" / "packets.jsonl"
        current_packet_report = tmp_path / "current" / "packet-report.json"
        calls = _install_controlled_adapter(monkeypatch)
        exit_code = main(
            [
                "analyze",
                "--repo-root",
                str(source_root),
                "--packets-output",
                str(current_packets),
                "--packet-report-output",
                str(current_packet_report),
                "--format",
                "json",
            ]
        )
        captured = capsys.readouterr()
        report = json.loads(captured.out)
        assert exit_code == source_fixture["expected_current_generation"]["exit_code"]
        assert report["scope"] == "current_repository"
        assert report["artifact_currentness"] == scenario["expected_currentness"]
        assert report["source_provenance"] == "captured_current"
        actual_identity = (
            "equal"
            if _packet_identity(current_packets) == _packet_identity(expected_packets)
            else "different"
        )
        assert actual_identity == scenario["expected_packet_identity"]
        assert calls == expected_calls
        return

    packet_path, report_path = _emit_packet_pair(
        scenario["source_fixture_id"], tmp_path / "source"
    )

    if kind in {"historical_replay", "stale_comparison"}:
        calls = _install_controlled_adapter(monkeypatch)
        args = [
            "analyze",
            "--packets",
            str(packet_path),
            "--packet-report",
            str(report_path),
            "--config",
            str(source_root / ".backstitch.toml"),
            "--format",
            "json",
        ]
        if scenario["compare_fixture_id"] is not None:
            compare = fixtures[scenario["compare_fixture_id"]]
            compare_packets, _ = _emit_packet_pair(
                scenario["compare_fixture_id"], tmp_path / "compare"
            )
            actual_identity = (
                "equal"
                if _packet_identity(packet_path) == _packet_identity(compare_packets)
                else "different"
            )
            assert actual_identity == scenario["expected_packet_identity"]
            args.extend(
                ("--compare-repo-root", str(_contained_tree_path(compare["tree_path"])))
            )
        else:
            assert scenario["expected_packet_identity"] == "equal"
        exit_code = main(args)
        captured = capsys.readouterr()
        report = json.loads(captured.out)
        assert exit_code == 0
        assert report["scope"] == "historical_snapshot"
        assert report["artifact_currentness"] == scenario["expected_currentness"]
        assert report["source_provenance"] == (
            "claimed_unverified"
            if scenario["expected_currentness"] == "unverifiable"
            else "compared_mismatch"
        )
        assert calls == expected_calls
        return

    if kind == "corrupt_artifact":
        calls = _install_controlled_adapter(monkeypatch)
        transform = scenario["artifact_transform"]
        target = packet_path if transform["artifact"] == "packet_jsonl" else report_path
        raw = bytearray(target.read_bytes())
        assert transform["byte_offset"] < len(raw)
        raw[transform["byte_offset"]] ^= transform["xor_mask"]
        corrupt = tmp_path / f"corrupt-{target.name}"
        corrupt.write_bytes(raw)
        corrupt_packet = (
            corrupt if transform["artifact"] == "packet_jsonl" else packet_path
        )
        corrupt_report = (
            corrupt if transform["artifact"] == "packet_report" else report_path
        )
        exit_code = main(
            [
                "analyze",
                "--packets",
                str(corrupt_packet),
                "--packet-report",
                str(corrupt_report),
                "--config",
                str(source_root / ".backstitch.toml"),
                "--format",
                "json",
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == 2
        assert captured.out == ""
        assert scenario["expected_currentness"] == "corrupt"
        expected_error = (
            "malformed packet JSONL"
            if transform["artifact"] == "packet_jsonl"
            else "packet report is not valid JSON"
        )
        assert expected_error in captured.err
        assert calls == []
        return

    assert kind in {"relevant_mutation", "unrelated_mutation"}
    compare_fixture = fixtures[scenario["compare_fixture_id"]]
    compare_root = _contained_tree_path(compare_fixture["tree_path"])
    compare_packets, _ = _emit_packet_pair(
        scenario["compare_fixture_id"], tmp_path / "compare"
    )
    actual_identity = (
        "equal"
        if _packet_identity(packet_path) == _packet_identity(compare_packets)
        else "different"
    )
    assert actual_identity == scenario["expected_packet_identity"]

    source_files = _fixture_files(source_root)
    compare_files = _fixture_files(compare_root)
    assert set(source_files) == set(compare_files)
    changed_paths = [
        path
        for path in sorted(source_files)
        if source_files[path] != compare_files[path]
    ]
    assert changed_paths
    working = tmp_path / "working"
    shutil.copytree(source_root, working)
    mutated = False

    def mutate_once(packet: dict[str, Any]) -> None:
        nonlocal mutated
        if mutated:
            return
        for path in changed_paths:
            working.joinpath(path).write_bytes(compare_files[path])
        mutated = True

    calls = _install_controlled_adapter(monkeypatch, mutate_once)
    outputs = tuple(
        tmp_path / "artifacts" / name
        for name in (
            "packets.jsonl",
            "packet-report.json",
            "analysis.jsonl",
            "analysis-report.json",
        )
    )
    exit_code = main(
        [
            "analyze",
            "--repo-root",
            str(working),
            "--packets-output",
            str(outputs[0]),
            "--packet-report-output",
            str(outputs[1]),
            "--output",
            str(outputs[2]),
            "--report",
            str(outputs[3]),
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert scenario["expected_currentness"] == "stale"
    assert "repository source changed during current analysis" in captured.err
    assert mutated
    assert calls == expected_calls
    assert all(not output.exists() for output in outputs)


def test_phase_c_analyzer_and_verifier_replay_is_zero_call_and_byte_identical(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    from backstitch.artifact_contracts import load_packets_bytes
    from backstitch.semantic_analysis import (
        ResolvedSemanticSettings,
        ResolvedVerificationSettings,
        SemanticAnalysisRequest,
        run_semantic_analysis,
    )
    from backstitch.semantic_identity import (
        RequestIdentity,
        build_composition_identity,
    )
    from backstitch.semantic_policy import materialize_semantic_policy
    from backstitch.semantic_reports import load_packet_report
    from backstitch.settings import resolve_config

    packet_path, report_path = _emit_packet_pair("aligned-base", tmp_path)
    packet_bytes = packet_path.read_bytes()
    packets = load_packets_bytes(packet_bytes, source=packet_path)
    packet_report = load_packet_report(report_path, maximum_bytes=10_000_000)
    provider = ProviderIdentity(
        backend_id="llm",
        plugin_id="openai",
        model_id="phase-c-controlled",
        model_revision="2026-07-16",
        adapter_id="backstitch.llm",
        adapter_version=2,
        llm_distribution_version="test",
        plugin_distribution_name="llm",
        plugin_distribution_version="test",
    )
    request_identity = RequestIdentity("off", 0.0, 42, 512)
    analyze = ResolvedSemanticSettings(
        provider_identity=provider,
        request_identity=request_identity,
        concurrency=1,
        cache_path=tmp_path / "analysis-cache",
        cache_mode="read-write",
        search_epoch="phase-c-analyze",
        require_complete=True,
        required_kinds=("section", "invariant"),
        minimum_packets=2,
        maximum_packets=2,
        maximum_prompt_bytes=1_000_000,
        finding_handling="report",
        maximum_provider_calls=2,
        lock_wait_timeout_seconds=1,
        maximum_runtime_seconds=60,
        maximum_estimated_cost_microusd=0,
        input_cost_microusd_per_million_tokens=0,
        output_cost_microusd_per_million_tokens=0,
        input_token_overhead=256,
        cost_rate_source="",
        dispositions=(),
    )
    composition = build_composition_identity(
        provider,
        request_identity,
        analysis_search_epoch=analyze.search_epoch,
        verify_provider=provider,
        verify_request=request_identity,
        verify_search_epochs=("phase-c-verify",),
        required_verdicts=1,
        minimum_support_score=0.8,
        indeterminate="report",
    )
    verify = ResolvedVerificationSettings(
        provider_identity=provider,
        request_identity=request_identity,
        composition_identity=composition,
        concurrency=1,
        cache_path=tmp_path / "verify-cache",
        cache_mode="read-write",
        search_epochs=("phase-c-verify",),
        required_verdicts=1,
        minimum_support_score=0.8,
        indeterminate="report",
        maximum_provider_calls=1,
        maximum_prompt_bytes=1_000_000,
        lock_wait_timeout_seconds=1,
        maximum_runtime_seconds=60,
        maximum_estimated_cost_microusd=0,
        input_cost_microusd_per_million_tokens=0,
        output_cost_microusd_per_million_tokens=0,
        input_token_overhead=256,
        cost_rate_source="",
    )
    loaded = resolve_config(
        PHASE_C / "fixtures/aligned-base",
        explicit=PHASE_C / "fixtures/aligned-base/.backstitch.toml",
    )
    policy = materialize_semantic_policy(
        loaded.diagnostics,
        loaded.policy_rule_origins,
        loaded.config_layers,
    )
    analyze_calls = 0
    verify_calls = 0

    def provenance(response_id: str) -> SemanticProvenance:
        return SemanticProvenance(
            adapter_id=provider.adapter_id,
            adapter_version=provider.adapter_version,
            plugin_version=provider.plugin_distribution_version,
            model_class="tests.phase_c.ControlledModel",
            provider_model_id=provider.model_id,
            provider_model_revision=provider.model_revision,
            response_id=response_id,
            input_tokens=10,
            output_tokens=5,
        )

    def analyze_factory() -> ProviderAdapter:
        def call(prompt: str) -> ProviderCallResult:
            nonlocal analyze_calls
            analyze_calls += 1
            packet = json.loads(prompt.rsplit("\n\n", 1)[1])
            if packet["kind"] == "section":
                classification = "confirmed_mismatch"
                evidence = [
                    region
                    for region in packet["evidence_regions"]
                    if region["role"] in {"requirement", "implementation"}
                ]
            else:
                classification = "ok"
                evidence = [
                    next(
                        region
                        for region in packet["evidence_regions"]
                        if region["role"] == "test"
                    )
                ]
            return ProviderCallResult(
                json.dumps(
                    {
                        "packet_id": packet["packet_id"],
                        "classification": classification,
                        "confidence": 0.9,
                        "rationale": "Controlled Phase C primary result.",
                        "summary": "Controlled Phase C semantic result.",
                        "evidence": evidence,
                    }
                ),
                provenance(f"analysis-{analyze_calls}"),
            )

        return call

    def verify_factory() -> ProviderAdapter:
        def call(prompt: str) -> ProviderCallResult:
            nonlocal verify_calls
            verify_calls += 1
            request = json.loads(prompt.rsplit("\n\n", 1)[1])
            claim = request["claim"]
            return ProviderCallResult(
                json.dumps(
                    {
                        "packet_id": request["packet"]["packet_id"],
                        "claim_hash": hashlib.sha256(
                            canonical_json_bytes(claim)
                        ).hexdigest(),
                        "verdict": "support",
                        "support_score": 0.95,
                        "summary": "The controlled verifier supports the claim.",
                        "evidence": [request["packet"]["evidence_regions"][0]],
                    }
                ),
                provenance("verify-1"),
            )

        return call

    request = SemanticAnalysisRequest(
        packets=packets,
        packet_jsonl_sha256=hashlib.sha256(packet_bytes).hexdigest(),
        packet_report=packet_report,
        settings=analyze,
        policy=policy,
        adapter_factory=analyze_factory,
        result_path=None,
        report_path=None,
        verification_settings=verify,
        verification_adapter_factory=verify_factory,
        scope="historical_snapshot",
        semantic_status="historical_replay",
        artifact_currentness="unverifiable",
        source_provenance="claimed_unverified",
    )

    primary = run_semantic_analysis(request)
    replay = run_semantic_analysis(
        replace(
            request,
            settings=replace(analyze, cache_mode="require"),
            adapter_factory=None,
            verification_settings=replace(verify, cache_mode="require"),
            verification_adapter_factory=None,
        )
    )

    assert primary.exit_code == replay.exit_code == 0
    assert analyze_calls == 2
    assert verify_calls == 1
    assert primary.result_jsonl == replay.result_jsonl
    assert (
        primary.report["verification"]["events"]
        == replay.report["verification"]["events"]
    )
    assert primary.report["cache_hits"] == 0
    assert primary.report["cache_misses"] == 2
    assert primary.report["provider_calls"] == 2
    assert primary.report["verification"]["cache_hits"] == 0
    assert primary.report["verification"]["cache_misses"] == 1
    assert primary.report["verification"]["provider_calls"] == 1
    assert replay.report["cache_hits"] == 2
    assert replay.report["cache_misses"] == 0
    assert replay.report["provider_calls"] == 0
    assert replay.report["verification"]["cache_hits"] == 1
    assert replay.report["verification"]["cache_misses"] == 0
    assert replay.report["verification"]["provider_calls"] == 0
