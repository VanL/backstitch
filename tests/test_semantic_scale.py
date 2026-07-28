from __future__ import annotations

import json
from pathlib import Path

import pytest

from backstitch.cli import main
from tests.performance.semantic_scale import (
    RUNNER_CONTRACT_FIELDS,
    RunnerQualification,
    ScaleShape,
    assess_runner_qualification,
    compare_runner_identity,
    generate_scale_fixture,
    inspect_scale_fixture,
    load_runner_contract,
    load_scale_shape,
    validate_scale_shape,
)


def _runner_contract() -> dict[str, object]:
    return {
        "schema_version": 1,
        "workflow_path": ".github/workflows/ci.yml",
        "job_id": "semantic-scale",
        "runs_on": "ubuntu-24.04",
        "runner_image_os": "ubuntu24",
        "runner_image_version": "20260713.1",
        "architecture": "x86_64",
        "cpu_model": "Example CPU",
        "logical_cpu_count": 4,
        "memory_bytes": 17_179_869_184,
        "python_version": "3.12.11",
        "uv_version": "0.8.0",
        "uv_lock_sha256": "a" * 64,
    }


def test_runner_contract_is_closed_and_runtime_mismatch_is_unavailable(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runner-contract.json"
    contract = _runner_contract()
    path.write_text(json.dumps(contract), encoding="utf-8")

    loaded = load_runner_contract(path)

    assert set(loaded) == RUNNER_CONTRACT_FIELDS
    observed = dict(loaded)
    observed["cpu_model"] = "Different CPU"
    observed["memory_bytes"] = 16_000_000_000
    assert compare_runner_identity(loaded, observed) == (
        "cpu_model",
        "memory_bytes",
    )

    qualification = assess_runner_qualification(path, observed)
    assert qualification == RunnerQualification(
        status="unavailable",
        reason="runtime_identity_mismatch",
        mismatched_fields=("cpu_model", "memory_bytes"),
    )


def test_missing_runner_contract_makes_qualification_explicitly_unavailable(
    tmp_path: Path,
) -> None:
    qualification = assess_runner_qualification(
        tmp_path / "missing-runner-contract.json",
        _runner_contract(),
    )

    assert qualification == RunnerQualification(
        status="unavailable",
        reason="runner_contract_missing",
        mismatched_fields=(),
    )


def test_matching_runner_contract_is_available(tmp_path: Path) -> None:
    path = tmp_path / "runner-contract.json"
    contract = _runner_contract()
    path.write_text(json.dumps(contract), encoding="utf-8")

    qualification = assess_runner_qualification(path, dict(contract))

    assert qualification == RunnerQualification(
        status="available",
        reason="runtime_identity_match",
        mismatched_fields=(),
    )


def test_invalid_or_unobserved_runner_identity_stays_unavailable(
    tmp_path: Path,
) -> None:
    invalid_path = tmp_path / "invalid-runner-contract.json"
    invalid_path.write_text("{}", encoding="utf-8")
    assert assess_runner_qualification(
        invalid_path,
        _runner_contract(),
    ) == RunnerQualification(
        status="unavailable",
        reason="runner_contract_invalid",
        mismatched_fields=(),
    )

    valid_path = tmp_path / "runner-contract.json"
    valid_path.write_text(json.dumps(_runner_contract()), encoding="utf-8")
    assert assess_runner_qualification(valid_path, None) == RunnerQualification(
        status="unavailable",
        reason="runtime_identity_unobserved",
        mismatched_fields=(),
    )


def test_committed_performance_posture_is_unavailable_until_runner_is_pinned() -> None:
    contract_path = Path("tests/performance/runner-contract.json")
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert assess_runner_qualification(contract_path, None) == RunnerQualification(
        status="unavailable",
        reason="runner_contract_missing",
        mismatched_fields=(),
    )
    assert "\n  semantic-scale:" not in workflow


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("job_id", ""),
        ("runs_on", "ubuntu-*"),
        ("logical_cpu_count", 0),
        ("memory_bytes", True),
        ("uv_lock_sha256", "A" * 64),
    ),
)
def test_runner_contract_rejects_invalid_identity_fields(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    path = tmp_path / "runner-contract.json"
    contract = _runner_contract()
    contract[field] = value
    path.write_text(json.dumps(contract), encoding="utf-8")

    with pytest.raises(ValueError, match=field):
        load_runner_contract(path)


def test_scale_shape_enforces_exact_work_counts_and_qualification_floors() -> None:
    qualified = ScaleShape(
        obligation_count=1_000,
        python_module_count=5_000,
        candidates_per_module=4,
        discovery_candidate_count=20_000,
        python_source_bytes=50 * 1024 * 1024,
    )

    validate_scale_shape(qualified, require_qualification=True)

    with pytest.raises(ValueError, match="discovery_candidate_count"):
        validate_scale_shape(
            ScaleShape(
                obligation_count=1_000,
                python_module_count=5_000,
                candidates_per_module=4,
                discovery_candidate_count=19_999,
                python_source_bytes=50 * 1024 * 1024,
            ),
            require_qualification=True,
        )


def test_committed_scale_manifest_is_exact_and_qualified() -> None:
    shape = load_scale_shape(Path("tests/performance/scale-fixture.json"))

    assert shape == ScaleShape(
        obligation_count=1_000,
        python_module_count=5_000,
        candidates_per_module=4,
        discovery_candidate_count=20_000,
        python_source_bytes=50 * 1024 * 1024,
    )


def test_generated_fixture_has_exact_counts_bytes_and_digest(tmp_path: Path) -> None:
    shape = ScaleShape(
        obligation_count=2,
        python_module_count=4,
        candidates_per_module=2,
        discovery_candidate_count=8,
        python_source_bytes=16_384,
    )
    first = tmp_path / "first"
    second = tmp_path / "second"

    first_digest = generate_scale_fixture(first, shape)
    second_digest = generate_scale_fixture(second, shape)

    assert first_digest == second_digest
    assert inspect_scale_fixture(first, shape) == {
        "fixture_sha256": first_digest,
        "obligation_count": 2,
        "python_module_count": 4,
        "catalog_candidate_count": 12,
        "discovery_candidate_count": 8,
        "python_source_bytes": 16_384,
    }
    assert all(
        b'__semantic_scale_padding__ = b"' in module.read_bytes()
        for module in (first / "src").rglob("*.py")
    )


def test_generated_fixture_produces_exact_candidates_through_public_cli(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    shape = ScaleShape(
        obligation_count=2,
        python_module_count=4,
        candidates_per_module=2,
        discovery_candidate_count=8,
        python_source_bytes=16_384,
    )
    generate_scale_fixture(tmp_path, shape)

    exit_code = main(
        [
            "obligation",
            "docs/specs/01-scale.md#SCALE-0000",
            "--repo-root",
            str(tmp_path),
            "--find-evidence",
            "--limit",
            "4",
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0, captured.out + captured.err
    envelope = json.loads(captured.out)
    assert len(envelope["result"]["candidates"]) == 4
    assert envelope["result"]["next_cursor"] is None
