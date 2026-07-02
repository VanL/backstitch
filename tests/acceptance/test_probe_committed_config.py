"""[SC-10] probe 6, committed-config form: this repo's config applies.

Spec: docs/specs/02-backstitch-core.md [SC-10]

Closes the Deviation Log entry in the reconciliation plan: probe 6's
isolated-fixture form lives in test_probe_config.py; this probe runs the
committed configuration on the repository itself.
"""

from __future__ import annotations

from pathlib import Path

from tests.acceptance.conftest import REPO_ROOT, run_cli


def test_committed_config_demonstrably_applies() -> None:
    assert (Path(REPO_ROOT) / "pyproject.toml").is_file()
    with_config = run_cli("check", "--repo-root", str(REPO_ROOT))
    without = run_cli("check", "--repo-root", str(REPO_ROOT), "--no-config")
    assert with_config.returncode == 0, with_config.stdout
    assert with_config.stdout != without.stdout
