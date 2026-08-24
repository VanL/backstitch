"""Self-corpus gate: this repository passes its own check, clean.

Spec: docs/specs/02-backstitch-core.md [SC-10]
Spec: docs/specs/05-backstitch-invariants.md [INV-10]

Success criteria per [SC-10]: exit 0, zero error-severity and zero
warning-severity findings in the default output, and every suppression
recoverable via --show-suppressions. A clean report produced by unauditable
hiding is a failure, not a pass.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _check(*extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "backstitch",
            "check",
            "--repo-root",
            str(REPO_ROOT),
            "--format",
            "json",
            *extra,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_self_corpus_zero_errors_and_warnings() -> None:
    result = _check()
    assert "Traceback" not in result.stderr, result.stderr
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["summary"]["errors"] == 0, data["summary"]
    assert data["summary"]["warnings"] == 0, data["summary"]


def test_self_corpus_suppressions_are_auditable() -> None:
    result = _check("--show-suppressions")
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    suppressed = data["suppressed_issues"]
    expected_counts = {
        "docs/specs/04-backstitch-traceability-exclusions.md#SUP-DOM-META": 15,
        "docs/specs/04-backstitch-traceability-exclusions.md#SUP-AT-PRIMER-META": 5,
        "docs/specs/04-backstitch-traceability-exclusions.md#SUP-EVC-PROCESS": 2,
        "docs/specs/04-backstitch-traceability-exclusions.md#SUP-EVC-DEFERRED-MCP": 2,
        "docs/specs/04-backstitch-traceability-exclusions.md#SUP-DOCUMENTATION-META": 2,
        "docs/specs/04-backstitch-traceability-exclusions.md#SUP-RUFF-REGISTRY-SEMANTIC": 1,
        # T4 adds governed Ruff policy/spec backlinks while the test-only
        # citation policy keeps their non-owning trace records auditable.
        "docs/specs/04-backstitch-traceability-exclusions.md#SUP-TEST-CITATIONS": 240,
        "docs/specs/04-backstitch-traceability-exclusions.md#SUP-VERIFICATION-META": 7,
    }
    assert Counter(record["declaration"] for record in suppressed) == expected_counts
    assert all(record["reason"] for record in suppressed)
    assert all(record["rationale"].strip() for record in suppressed)

    for record in suppressed:
        declaration = record["declaration"]
        if declaration.endswith("#SUP-DOM-META"):
            assert record["path"] == (
                "docs/specs/01-development-documentation-operating-model.md"
            )
        elif declaration.endswith("#SUP-AT-PRIMER-META"):
            assert record["path"] == (
                "docs/specs/09-agent-theory-and-program-theory.md"
            )
            assert record["code"] == "SPEC_SECTION_UNMAPPED"
        elif declaration.endswith("#SUP-EVC-PROCESS"):
            assert record["path"] == (
                "docs/specs/07-verification-and-evidence-cases.md"
            )
            assert record["section_id"] in {"EVC-1", "EVC-12.1"}
        elif declaration.endswith("#SUP-EVC-DEFERRED-MCP"):
            assert record["path"] == (
                "docs/specs/07-verification-and-evidence-cases.md"
            )
            assert record["section_id"] == "EVC-8.6"
        elif declaration.endswith("#SUP-DOCUMENTATION-META"):
            assert (record["path"], record["section_id"]) in {
                ("docs/specs/03-backstitch-configuration.md", "CFG-10"),
                (
                    "docs/specs/04-backstitch-traceability-exclusions.md",
                    "EXC-10",
                ),
            }
            assert record["code"] == "SPEC_SECTION_UNMAPPED"
        elif declaration.endswith("#SUP-RUFF-REGISTRY-SEMANTIC"):
            assert record["path"] == "docs/specs/02-backstitch-core.md"
            assert record["section_id"] == "SC-17.1"
            assert record["code"] == "OBLIGATION_SKIPPED"
        elif declaration.endswith("#SUP-VERIFICATION-META"):
            assert (record["path"], record["section_id"]) in {
                ("docs/specs/02-backstitch-core.md", "SC-10"),
                ("docs/specs/03-backstitch-configuration.md", "CFG-9"),
                (
                    "docs/specs/04-backstitch-traceability-exclusions.md",
                    "EXC-9",
                ),
                ("docs/specs/05-backstitch-invariants.md", "INV-9"),
                ("docs/specs/05-backstitch-invariants.md", "INV-10"),
                (
                    "docs/specs/07-verification-and-evidence-cases.md",
                    "EVC-10",
                ),
                (
                    "docs/specs/07-verification-and-evidence-cases.md",
                    "EVC-12",
                ),
            }
            assert record["code"] == "SPEC_SECTION_UNMAPPED"
        else:
            assert declaration.endswith("#SUP-TEST-CITATIONS")
            assert record["path"].startswith("tests/")
            assert record["code"] in {
                "CODE_REF_UNMAPPED_FROM_SPEC",
                "SPEC_MAPPING_RECIPROCAL_MISSING",
            }


def test_dogfood_enables_documented_suppression_governance() -> None:
    environment = os.environ.copy()
    environment.pop("LLM_MODEL", None)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "backstitch",
            "config",
            "show",
            "--repo-root",
            str(REPO_ROOT),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    config = json.loads(result.stdout)
    assert config["lint"]["require_suppression_declarations"] is True
    assert len(config["lint"]["suppressions"]) == 5
    ruff_registry = next(
        item
        for item in config["lint"]["suppressions"]
        if item["declaration"].endswith("#SUP-RUFF-REGISTRY-SEMANTIC")
    )
    assert ruff_registry["mechanism"] == "ignore"
    assert ruff_registry["path"] == "docs/specs/02-backstitch-core.md"
    assert ruff_registry["sections"] == ["SC-17.1"]
    assert ruff_registry["codes"] == ["OBLIGATION_SKIPPED"]
    assert config["analyze"]["required_kinds"] == [
        "section",
        "invariant",
        "suppression",
    ]


def test_dogfood_config_delta_is_live() -> None:
    # [CFG-9]: the committed configuration must produce an observable
    # difference against --no-config, so a loader regression that silently
    # no-ops fails here instead of passing quietly.
    with_config = _check()
    without_config = _check("--no-config")
    assert with_config.stdout != without_config.stdout
    without_summary = json.loads(without_config.stdout)["summary"]
    with_summary = json.loads(with_config.stdout)["summary"]
    # Without config the fixture corpora are scanned: strictly more errors.
    assert without_summary["errors"] > with_summary["errors"]
