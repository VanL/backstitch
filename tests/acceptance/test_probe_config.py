"""Probes 6-7: config demonstrably applies; unknown keys fail loudly.

Spec: docs/specs/02-backstitch-core.md [SC-10]
Spec: docs/specs/03-backstitch-configuration.md [CFG-8], [CFG-9]
"""

from __future__ import annotations

from pathlib import Path

from tests.acceptance.conftest import run_cli


def test_probe_6_config_applies_vs_no_config(mini_repo: Path) -> None:
    (mini_repo / "pkg/fixtures").mkdir()
    (mini_repo / "pkg/fixtures/broken.py").write_text(
        "def broken(:\n", encoding="utf-8"
    )
    (mini_repo / ".backstitch.toml").write_text(
        "\n".join(
            [
                'extend_exclude = ["pkg/fixtures/**"]',
                "[profile]",
                'name = "backstitch-style-v1"',
                'spec_roots = ["docs/specs"]',
                'plan_roots = ["docs/plans"]',
                'code_roots = ["pkg"]',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    with_config = run_cli("check", "--repo-root", str(mini_repo))
    without = run_cli("check", "--repo-root", str(mini_repo), "--no-config")
    # The committed config demonstrably changes behavior ([SC-10] probe 6).
    assert with_config.returncode == 0, with_config.stdout
    assert "PYTHON_SYNTAX_ERROR" not in with_config.stdout
    assert with_config.stdout != without.stdout


def test_probe_7_unknown_config_key_exits_two_naming_key_and_file(
    mini_repo: Path,
) -> None:
    config = mini_repo / ".backstitch.toml"
    config.write_text('spec_rootz = ["docs/specs"]\n', encoding="utf-8")
    result = run_cli("check", "--repo-root", str(mini_repo))
    assert result.returncode == 2
    assert "spec_rootz" in result.stderr
    assert str(config) in result.stderr
