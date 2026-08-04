"""Installed-CLI usability canaries and dogfood scaffold.

Spec: docs/specs/02-backstitch-core.md [SC-5], [SC-10]
Spec: docs/specs/06-semantic-gates.md [SEM-7]
Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-8.7]
Plan: docs/plans/2026-07-29-usability-remediation-plan.md Slice 0
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.acceptance.conftest import local_llm_environment, run_installed_cli


def _write_readiness_debt_repo(root: Path) -> None:
    (root / "docs/specs").mkdir(parents=True)
    (root / "pkg").mkdir()
    (root / "tests").mkdir()
    (root / "docs/specs/01-core.md").write_text(
        "# Core\n\n"
        "## Contract [CORE-1]\n\n"
        "The implementation returns one.\n\n"
        "_Implementation mapping_:\n\n"
        "- `pkg/core.py::value`\n",
        encoding="utf-8",
    )
    (root / "pkg/core.py").write_text(
        "def value() -> int:\n"
        '    """Spec: docs/specs/01-core.md [CORE-1]"""\n'
        "    return 1\n",
        encoding="utf-8",
    )
    (root / ".backstitch.toml").write_text(
        'default_command = "analyze"\n\n'
        "[profile]\n"
        'spec_roots = ["docs/specs"]\n'
        "plan_roots = []\n"
        'code_roots = ["pkg", "tests"]\n'
        'test_roots = ["tests"]\n\n'
        "[obligations]\n"
        'section_required_roles = ["implementation", "test"]\n\n'
        "[analyze]\n"
        'backend_id = "llm"\n'
        'plugin_id = "backstitch-acceptance-local"\n'
        'plugin_distribution_name = "llm"\n'
        'model = "pkg:service/example.com/backstitch-acceptance@fixture-v1"\n'
        'adapter_model_id = "backstitch-acceptance-local"\n'
        'model_revision = "fixture-v1"\n'
        "capability_schema_version = 1\n"
        'capability_revision = "fixture-v1"\n'
        "maximum_input_bytes = 1000000\n"
        "input_cost_microusd_per_million_tokens = 0\n"
        "output_cost_microusd_per_million_tokens = 0\n"
        "input_token_overhead = 0\n"
        'cost_rate_source = "test-owned zero rates"\n'
        'json_mode = "require"\n'
        "temperature = 0.0\n"
        "seed = 42\n"
        "max_tokens = 512\n\n"
        "[analyze.request_constraints.json_mode]\n"
        'presence = "required"\n'
        'allowed_values = ["require"]\n\n'
        "[analyze.request_constraints.temperature]\n"
        'presence = "required"\n'
        "allowed_values = [0.0]\n\n"
        "[analyze.request_constraints.seed]\n"
        'presence = "required"\n'
        "minimum = 0\n"
        "maximum = 2147483647\n\n"
        "[analyze.request_constraints.max_tokens]\n"
        'presence = "required"\n'
        "minimum = 1\n"
        "maximum = 16384\n",
        encoding="utf-8",
    )


def test_preflight_explains_semantic_debt_when_check_is_clean(
    tmp_path: Path,
) -> None:
    _write_readiness_debt_repo(tmp_path)
    ledger = tmp_path / "local-model-ledger.jsonl"
    environment = local_llm_environment(ledger)

    checked = run_installed_cli(
        "check",
        "--repo-root",
        str(tmp_path),
        "--format",
        "json",
        environment=environment,
    )
    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout)["summary"]["errors"] == 0
    assert json.loads(checked.stdout)["summary"]["warnings"] == 0

    explicit = run_installed_cli(
        "analyze",
        "--repo-root",
        str(tmp_path),
        "--preflight",
        "--format",
        "json",
        environment=environment,
    )
    assert explicit.returncode == 2
    assert explicit.stderr == ""
    report = json.loads(explicit.stdout)
    assert report["operation"] == "analysis.preflight"
    assert report["ready"] is False
    assert report["readiness"]["blocked"] == 1
    assert report["readiness"]["reason_groups"] == [
        {
            "code": "TEST_UNTRACED",
            "count": 1,
            "example_obligation_ids": ["docs/specs/01-core.md#CORE-1"],
        }
    ]
    assert "obligation list" in report["readiness"]["next_command"]
    assert report["problems"][0]["code"] == "ALIGNMENT_DEBT"
    assert "Unknown model" not in explicit.stdout

    ordinary = run_installed_cli(
        "analyze",
        "--repo-root",
        str(tmp_path),
        "--format",
        "json",
        environment=environment,
    )
    assert ordinary.returncode == explicit.returncode
    assert ordinary.stderr == explicit.stderr
    ordinary_report = json.loads(ordinary.stdout)

    bare = run_installed_cli(
        "--format",
        "json",
        cwd=tmp_path,
        environment=environment,
    )
    assert bare.returncode == explicit.returncode
    assert bare.stderr == explicit.stderr
    bare_report = json.loads(bare.stdout)
    for identity_field in (
        "config",
        "inference",
        "packet_plan",
        "readiness",
        "snapshot",
    ):
        assert ordinary_report[identity_field] == report[identity_field]
        assert bare_report[identity_field] == report[identity_field]
    assert not ledger.exists()
