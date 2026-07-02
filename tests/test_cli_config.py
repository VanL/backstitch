"""CLI + configuration integration: discovery applies, excludes are live.

Spec: docs/specs/03-backstitch-configuration.md [CFG-5], [CFG-7], [CFG-9]
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


def run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "backstitch", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
    )


@pytest.fixture
def config_repo(tmp_path: Path) -> Path:
    """A repo whose .backstitch.toml excludes a broken subtree."""

    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "docs/specs/01-x.md").write_text(
        "# X\n\n## One [X-1]\n\n_Implementation mapping_:\n\n- `pkg/mod.py`\n",
        encoding="utf-8",
    )
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg/mod.py").write_text(
        '"""Spec: docs/specs/01-x.md [X-1]"""\n', encoding="utf-8"
    )
    fixtures = tmp_path / "pkg/fixtures"
    fixtures.mkdir()
    (fixtures / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    (tmp_path / ".backstitch.toml").write_text(
        "\n".join(
            [
                'extend_exclude = ["pkg/fixtures/**"]',
                "[profile]",
                'name = "backstitch-style-v1"',
                'spec_roots = ["docs/specs"]',
                "plan_roots = []",
                'code_roots = ["pkg"]',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return tmp_path


def test_config_applied_exclude_prevents_scanning_fixture_tree(
    config_repo: Path,
) -> None:
    result = run_cli("check", "--repo-root", str(config_repo))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PYTHON_SYNTAX_ERROR" not in result.stdout


def test_no_config_flag_restores_builtin_behavior(config_repo: Path) -> None:
    result = run_cli("check", "--repo-root", str(config_repo), "--no-config")
    # Without config: built-in profile roots (backstitch/tests) are missing
    # in this repo -> SCAN_ROOT_MISSING errors -> exit 1. Proves the config
    # was live in the other test (dogfood-delta pattern, [CFG-9]).
    assert result.returncode == 1
    assert "SCAN_ROOT_MISSING" in result.stdout


def test_unknown_config_key_exits_two(tmp_path: Path) -> None:
    (tmp_path / ".backstitch.toml").write_text(
        'spec_rootz = ["docs/specs"]\n', encoding="utf-8"
    )
    result = run_cli("check", "--repo-root", str(tmp_path))
    assert result.returncode == 2
    assert "spec_rootz" in result.stderr
    assert ".backstitch.toml" in result.stderr
    assert "Traceback" not in result.stderr
