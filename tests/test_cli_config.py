"""CLI + configuration integration: discovery applies, excludes are live.

Spec: docs/specs/03-backstitch-configuration.md [CFG-5], [CFG-5.1], [CFG-7],
[CFG-9]
Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-12.2]
"""

from __future__ import annotations

import json
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


def test_config_show_includes_packaged_defaults_and_resolved_policy(
    config_repo: Path,
) -> None:
    result = run_cli("config", "show", "--repo-root", str(config_repo))
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["config_layers"][0] == "packaged:backstitch/defaults.toml"
    assert "resolved_diagnostics" in data
    assert data["resolved_diagnostics"]["PYTHON_SYNTAX_ERROR"]["short_code"] == "BSC001"
    assert data["profile_overrides"]["test_roots"] == []


def test_config_show_projects_documented_suppression_settings(tmp_path: Path) -> None:
    config = tmp_path / "arbitrary.toml"
    config.write_text(
        """
[lint]
require_suppression_declarations = true

[[lint.suppressions]]
mechanism = "meta"
path = "docs/specs/01-process.md"
sections = []
codes = []
declaration = "docs/specs/04-exclusions.md#SUP-PROCESS"
""".lstrip(),
        encoding="utf-8",
    )

    result = run_cli(
        "config",
        "show",
        "--repo-root",
        str(tmp_path),
        "--config",
        str(config),
    )

    assert result.returncode == 0, result.stderr
    lint = json.loads(result.stdout)["lint"]
    assert lint["require_suppression_declarations"] is True
    assert lint["suppressions"] == [
        {
            "mechanism": "meta",
            "path": "docs/specs/01-process.md",
            "sections": [],
            "codes": [],
            "declaration": "docs/specs/04-exclusions.md#SUP-PROCESS",
            "origin": {
                "source": str(config.resolve()),
                "position": 0,
                "line": None,
            },
        }
    ]


@pytest.mark.parametrize(
    ("arguments", "expected"),
    (
        (
            (
                "--option",
                "analyze.model",
                "global-model",
                "config",
                "show",
                "--no-config",
            ),
            "global-model",
        ),
        (
            (
                "config",
                "show",
                "--no-config",
                "--option",
                "analyze.model",
                "local-model",
            ),
            "local-model",
        ),
    ),
)
def test_option_is_accepted_before_and_after_config_consuming_subcommands(
    arguments: tuple[str, ...],
    expected: str,
) -> None:
    result = run_cli(*arguments)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["analyze"]["model"] == expected


def test_option_wrong_arity_is_exit_two() -> None:
    result = run_cli("config", "show", "--no-config", "--option", "analyze.model")

    assert result.returncode == 2
    assert "expected 2 arguments" in result.stderr


def test_global_and_command_options_cannot_repeat_a_key() -> None:
    result = run_cli(
        "--option",
        "analyze.model",
        "global-model",
        "config",
        "show",
        "--no-config",
        "--option",
        "analyze.model",
        "local-model",
    )

    assert result.returncode == 2
    assert "repeats key 'analyze.model'" in result.stderr


def test_cli_option_paths_use_cwd_while_scan_roots_remain_target_relative(
    tmp_path: Path,
) -> None:
    result = run_cli(
        "config",
        "show",
        "--no-config",
        "--option",
        "check.output",
        "reports/check.json",
        "--option",
        "profile.code_roots",
        '["src"]',
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    settings = json.loads(result.stdout)
    assert settings["check"]["output"] == str(
        (tmp_path / "reports/check.json").resolve()
    )
    assert settings["profile_overrides"]["code_roots"] == ["src"]


@pytest.mark.parametrize(
    "command",
    (
        ("guide", "alignment"),
        (
            "summarize-analysis",
            "--deterministic-report",
            "missing-report.json",
            "--analysis-results",
            "missing-results.jsonl",
        ),
        (
            "cache",
            "cleanup-lock",
            "--cache-path",
            "missing-cache",
            "--analysis-key",
            "0" * 64,
            "--lock-stale-seconds",
            "1",
            "--reason",
            "test",
        ),
    ),
)
@pytest.mark.parametrize(
    "control",
    (
        ("--config", "arbitrary.toml"),
        ("--no-config",),
        ("--option", "analyze.model", "model"),
    ),
)
def test_non_config_commands_reject_global_configuration_controls(
    command: tuple[str, ...],
    control: tuple[str, ...],
) -> None:
    result = run_cli(*control, *command)

    assert result.returncode == 2
    assert "does not accept --config, --no-config, or --option" in result.stderr


@pytest.mark.parametrize(
    ("command", "dedicated", "key", "value"),
    (
        ("check", ("--profile", "backstitch-style-v1"), "profile.name", "x"),
        ("check", ("--spec-root", "docs"), "profile.spec_roots", '["docs"]'),
        ("check", ("--plan-root", "plans"), "profile.plan_roots", '["plans"]'),
        ("check", ("--code-root", "src"), "profile.code_roots", '["src"]'),
        ("check", ("--test-root", "tests"), "profile.test_roots", '["tests"]'),
        ("check", ("--format", "json"), "check.format", "text"),
        ("check", ("--output", "out.txt"), "check.output", "other.txt"),
        (
            "check",
            ("--warnings-as-errors",),
            "check.warnings_as_errors",
            "false",
        ),
        ("packets", ("--profile", "backstitch-style-v1"), "profile.name", "x"),
        ("packets", ("--spec-root", "docs"), "profile.spec_roots", '["docs"]'),
        ("packets", ("--plan-root", "plans"), "profile.plan_roots", '["plans"]'),
        ("packets", ("--code-root", "src"), "profile.code_roots", '["src"]'),
        ("packets", ("--test-root", "tests"), "profile.test_roots", '["tests"]'),
        ("analyze", ("--model", "dedicated"), "analyze.model", "generic"),
        ("analyze", ("--concurrency", "2"), "analyze.concurrency", "3"),
        ("doctor", ("--model", "dedicated"), "analyze.model", "generic"),
    ),
)
def test_each_dedicated_setting_alias_conflicts_with_its_generic_option(
    tmp_path: Path,
    command: str,
    dedicated: tuple[str, ...],
    key: str,
    value: str,
) -> None:
    command_args: tuple[str, ...]
    if command == "packets":
        command_args = (
            "packets",
            "--repo-root",
            str(tmp_path),
            "--output",
            str(tmp_path / "packets.jsonl"),
        )
    elif command == "analyze":
        command_args = ("analyze", "--repo-root", str(tmp_path))
    elif command == "check":
        command_args = ("check", "--repo-root", str(tmp_path))
    else:
        command_args = ("doctor",)

    result = run_cli(
        *command_args,
        *dedicated,
        "--option",
        key,
        value,
    )

    assert result.returncode == 2
    assert "conflicts with its dedicated CLI flag" in result.stderr


def test_empty_profile_still_conflicts_with_generic_profile_option(
    config_repo: Path,
) -> None:
    result = run_cli(
        "check",
        "--repo-root",
        str(config_repo),
        "--profile",
        "",
        "--option",
        "profile.name",
        '""',
    )

    assert result.returncode == 2
    assert "conflicts with its dedicated CLI flag" in result.stderr


@pytest.mark.parametrize(
    ("command", "cwd"),
    (
        (("check", "--repo-root", "{root}"), None),
        (
            (
                "packets",
                "--repo-root",
                "{root}",
                "--output",
                "{root}/packets.jsonl",
            ),
            None,
        ),
        (("obligation", "list", "--repo-root", "{root}"), None),
        (("analyze", "--repo-root", "{root}"), None),
        (
            (
                "analyze",
                "--packets",
                "{root}/packets.jsonl",
                "--packet-report",
                "{root}/packet-report.json",
            ),
            None,
        ),
        (
            (
                "eval",
                "--corpus",
                "{root}/manifest.json",
                "--output",
                "{root}/report.json",
            ),
            None,
        ),
        (("doctor",), "{root}"),
    ),
)
def test_each_config_command_discovers_from_its_command_anchor(
    tmp_path: Path,
    command: tuple[str, ...],
    cwd: str | None,
) -> None:
    root = tmp_path / "anchor"
    root.mkdir()
    runner = tmp_path / "runner"
    runner.mkdir()
    config = root / ".backstitch.toml"
    config.write_text("unknown_anchor_key = true\n", encoding="utf-8")
    rendered = tuple(part.format(root=root) for part in command)

    result = run_cli(
        *rendered,
        cwd=root if cwd is not None else runner,
    )

    assert result.returncode == 2
    if command[0] == "obligation":
        assert "configuration is invalid or unavailable" in result.stderr
    else:
        assert "unknown_anchor_key" in result.stderr
        assert str(config) in result.stderr


def test_test_root_must_be_contained_by_final_code_roots(config_repo: Path) -> None:
    result = run_cli(
        "check",
        "--repo-root",
        str(config_repo),
        "--code-root",
        "pkg",
        "--test-root",
        "qa",
    )
    assert result.returncode == 2
    assert "test root" in result.stderr
    assert "qa" in result.stderr


def test_lone_cli_test_root_retains_inherited_code_roots(config_repo: Path) -> None:
    result = run_cli(
        "check",
        "--repo-root",
        str(config_repo),
        "--test-root",
        "pkg",
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_config_path_no_config_prints_no_packaged_path(config_repo: Path) -> None:
    result = run_cli("config", "path", "--repo-root", str(config_repo), "--no-config")
    assert result.returncode == 0
    assert result.stdout == ""


def test_unknown_config_key_exits_two(tmp_path: Path) -> None:
    (tmp_path / ".backstitch.toml").write_text(
        'spec_rootz = ["docs/specs"]\n', encoding="utf-8"
    )
    result = run_cli("check", "--repo-root", str(tmp_path))
    assert result.returncode == 2
    assert "spec_rootz" in result.stderr
    assert ".backstitch.toml" in result.stderr
    assert "Traceback" not in result.stderr
