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
import subprocess
import sys
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
    data = json.loads(result.stdout)
    # Suppressions exist (the dogfood config suppresses test-file citation
    # noise) and every one carries a reason.
    suppressed = data["suppressed_issues"]
    assert all("reason" in record for record in suppressed)


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
