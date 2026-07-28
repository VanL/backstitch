"""Subprocess CLI contract: exit codes, output modes, no tracebacks.

Spec: docs/specs/02-backstitch-core.md [SC-5], [SC-5.1]
Spec: docs/specs/03-backstitch-configuration.md [CFG-5.1], [CFG-9]
Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-12.2]
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from backstitch.check_pipeline import CheckPipelineResult
from backstitch.config import ProfileConfig
from backstitch.markdown_specs import MarkdownParseMemo
from backstitch.repository_snapshot import RepositorySnapshot
from backstitch.settings import BackstitchSettings, ProfileSettings

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CLEAN = FIXTURES / "clean_project"
BROKEN = FIXTURES / "traceability_project"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "backstitch", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def check_clean(*extra: str) -> subprocess.CompletedProcess[str]:
    return run_cli(
        "check",
        "--repo-root",
        str(CLEAN),
        "--no-config",
        "--spec-root",
        "docs/specs",
        "--plan-root",
        "docs/plans",
        "--code-root",
        "pkg",
        *extra,
    )


def write_syntax_warning_repo(root: Path, *, inline_noqa: bool = False) -> None:
    spec_dir = root / "docs" / "specs"
    spec_dir.mkdir(parents=True)
    spec_dir.joinpath("01-x.md").write_text(
        "# X\n\n## Thing [X-1]\n\n_Implementation mapping_:\n\n- `pkg/good.py`\n",
        encoding="utf-8",
    )
    pkg = root / "pkg"
    pkg.mkdir()
    pkg.joinpath("good.py").write_text(
        '"""Spec: docs/specs/01-x.md [X-1]"""\n',
        encoding="utf-8",
    )
    prefix = "# backstitch: noqa PYTHON_SYNTAX_ERROR\n" if inline_noqa else ""
    pkg.joinpath("bad.py").write_text(f"{prefix}def broken(:\n", encoding="utf-8")


def test_clean_repo_exits_zero() -> None:
    result = check_clean()
    assert result.returncode == 0, result.stderr
    assert "0 errors" in result.stdout
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize(
    ("argv", "handler"),
    (
        (
            (
                "check",
                "--repo-root",
                ".",
                "--show-suppressions",
                "--no-config",
            ),
            "_cmd_check",
        ),
        (
            (
                "packets",
                "--repo-root",
                ".",
                "--output",
                "packets.jsonl",
                "--no-config",
            ),
            "_cmd_packets",
        ),
        (
            (
                "obligation",
                "list",
                "--repo-root",
                ".",
                "--format",
                "json",
                "--limit",
                "1",
                "--no-config",
            ),
            "_cmd_obligation",
        ),
        (
            (
                "analyze",
                "--repo-root",
                ".",
                "--packets-output",
                "packets.jsonl",
                "--packet-report-output",
                "packet-report.json",
                "--output",
                "results.jsonl",
                "--report",
                "report.json",
                "--format",
                "json",
                "--no-config",
            ),
            "_cmd_analyze",
        ),
        (
            (
                "analyze",
                "--packets",
                "packets.jsonl",
                "--packet-report",
                "packet-report.json",
                "--compare-repo-root",
                ".",
                "--output",
                "results.jsonl",
                "--report",
                "report.json",
                "--format",
                "json",
                "--no-config",
            ),
            "_cmd_analyze",
        ),
        (
            (
                "eval",
                "--corpus",
                "manifest.json",
                "--output",
                "eval-report.json",
                "--no-config",
            ),
            "_cmd_eval",
        ),
        (
            ("doctor", "--format", "json", "--no-config"),
            "_cmd_doctor",
        ),
        (
            ("config", "path", "--repo-root", ".", "--no-config"),
            "_cmd_config",
        ),
    ),
)
def test_config_consuming_invocation_resolves_settings_once(
    monkeypatch: pytest.MonkeyPatch,
    argv: tuple[str, ...],
    handler: str,
) -> None:
    import backstitch.cli as cli

    original = cli.resolve_config
    calls = 0

    def counted_resolve(*args: object, **kwargs: object) -> BackstitchSettings:
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(cli, "resolve_config", counted_resolve)
    monkeypatch.setattr(cli, handler, lambda *args, **kwargs: 0)

    assert cli.main([*argv, "--option", "diagnostics.fail_on", '["error"]']) == 0
    assert calls == 1


@pytest.mark.parametrize(
    ("argv", "handler"),
    (
        (
            (
                "check",
                "--repo-root",
                ".",
                "--show-suppressions",
                "--no-config",
            ),
            "_cmd_check",
        ),
        (
            (
                "packets",
                "--repo-root",
                ".",
                "--output",
                "packets.jsonl",
                "--report",
                "packet-report.json",
                "--no-config",
            ),
            "_cmd_packets",
        ),
        (
            (
                "obligation",
                "item",
                "--repo-root",
                ".",
                "--find-evidence",
                "--limit",
                "1",
                "--format",
                "json",
                "--no-config",
            ),
            "_cmd_obligation",
        ),
        (
            (
                "analyze",
                "--repo-root",
                ".",
                "--packets-output",
                "packets.jsonl",
                "--packet-report-output",
                "packet-report.json",
                "--output",
                "results.jsonl",
                "--report",
                "report.json",
                "--format",
                "json",
                "--no-config",
            ),
            "_cmd_analyze",
        ),
        (
            (
                "analyze",
                "--packets",
                "packets.jsonl",
                "--packet-report",
                "packet-report.json",
                "--compare-repo-root",
                ".",
                "--output",
                "results.jsonl",
                "--report",
                "report.json",
                "--format",
                "json",
                "--no-config",
            ),
            "_cmd_analyze",
        ),
        (
            (
                "eval",
                "--corpus",
                "manifest.json",
                "--output",
                "eval-report.json",
                "--no-config",
            ),
            "_cmd_eval",
        ),
        (
            ("doctor", "--format", "json", "--no-config"),
            "_cmd_doctor",
        ),
    ),
)
def test_operational_nonaliases_compose_with_generic_options(
    monkeypatch: pytest.MonkeyPatch,
    argv: tuple[str, ...],
    handler: str,
) -> None:
    import backstitch.cli as cli

    monkeypatch.setattr(cli, handler, lambda *args, **kwargs: 0)

    assert cli.main([*argv, "--option", "diagnostics.fail_on", '["error"]']) == 0


def test_check_handler_uses_injected_settings_without_ambient_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backstitch.cli as cli

    args = cli.build_parser().parse_args(
        ["check", "--repo-root", str(CLEAN), "--format", "json"]
    )
    settings = BackstitchSettings(
        profile_overrides=ProfileSettings(
            spec_roots=("docs/specs",),
            plan_roots=("docs/plans",),
            code_roots=("pkg",),
            test_roots=(),
        )
    )
    monkeypatch.setattr(
        cli,
        "resolve_config",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("handler reread ambient configuration")
        ),
    )

    assert cli._cmd_check(args, settings) == 0


def test_check_routes_through_the_snapshot_backed_core(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_syntax_warning_repo(tmp_path)

    import backstitch.cli as cli

    original = cli.build_check_report_from_snapshot
    calls = 0

    def observe(
        snapshot: RepositorySnapshot,
        repo_root_display: str,
        profile: ProfileConfig,
        settings: BackstitchSettings,
        *,
        markdown_parse_memo: MarkdownParseMemo | None = None,
    ) -> CheckPipelineResult:
        nonlocal calls
        calls += 1
        return original(
            snapshot,
            repo_root_display,
            profile,
            settings,
            markdown_parse_memo=markdown_parse_memo,
        )

    monkeypatch.setattr(cli, "build_check_report_from_snapshot", observe)

    exit_code = cli.main(
        [
            "check",
            "--repo-root",
            str(tmp_path),
            "--spec-root",
            "docs/specs",
            "--code-root",
            "pkg",
            "--format",
            "json",
        ]
    )

    assert exit_code == 0
    assert calls == 1
    assert json.loads(capsys.readouterr().out)["summary"]["warnings"] == 1


def test_python_syntax_warning_does_not_fail_check_by_default(tmp_path: Path) -> None:
    write_syntax_warning_repo(tmp_path)
    result = run_cli(
        "check",
        "--repo-root",
        str(tmp_path),
        "--spec-root",
        "docs/specs",
        "--code-root",
        "pkg",
        "--format",
        "json",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["summary"]["warnings"] == 1
    assert data["issues"][0]["code"] == "PYTHON_SYNTAX_ERROR"
    assert data["issues"][0]["severity"] == "warning"


def test_python_syntax_warning_fails_check_with_warnings_as_errors(
    tmp_path: Path,
) -> None:
    write_syntax_warning_repo(tmp_path)
    result = run_cli(
        "check",
        "--repo-root",
        str(tmp_path),
        "--spec-root",
        "docs/specs",
        "--code-root",
        "pkg",
        "--warnings-as-errors",
        "--format",
        "json",
    )
    assert result.returncode == 1, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["issues"][0]["code"] == "PYTHON_SYNTAX_ERROR"
    assert data["issues"][0]["severity"] == "warning"
    assert data["issues"][0]["default_severity"] == "warning"


def test_all_info_policy_exits_zero_and_preserves_default_severity(
    tmp_path: Path,
) -> None:
    write_syntax_warning_repo(tmp_path)
    config = tmp_path / ".backstitch.toml"
    config.write_text(
        "\n".join(
            [
                "[profile]",
                'name = "backstitch-style-v1"',
                'spec_roots = ["docs/specs"]',
                "plan_roots = []",
                'code_roots = ["pkg"]',
                "",
                "[diagnostics]",
                "fail_on = []",
                "",
                "[[diagnostics.levels]]",
                'select = ["*"]',
                'level = "info"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    result = run_cli("check", "--repo-root", str(tmp_path), "--format", "json")
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    issue = data["issues"][0]
    assert issue["code"] == "PYTHON_SYNTAX_ERROR"
    assert issue["severity"] == "info"
    assert issue["default_severity"] == "warning"


def test_all_error_policy_exits_one_for_former_warning(tmp_path: Path) -> None:
    write_syntax_warning_repo(tmp_path)
    (tmp_path / ".backstitch.toml").write_text(
        "\n".join(
            [
                "[profile]",
                'name = "backstitch-style-v1"',
                'spec_roots = ["docs/specs"]',
                "plan_roots = []",
                'code_roots = ["pkg"]',
                "",
                "[[diagnostics.levels]]",
                'select = ["*"]',
                'level = "error"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    result = run_cli("check", "--repo-root", str(tmp_path), "--format", "json")
    assert result.returncode == 1, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["issues"][0]["severity"] == "error"
    assert data["issues"][0]["default_severity"] == "warning"


def test_off_policy_hides_issue_but_show_suppressions_audits_it(
    tmp_path: Path,
) -> None:
    write_syntax_warning_repo(tmp_path)
    (tmp_path / ".backstitch.toml").write_text(
        "\n".join(
            [
                "[profile]",
                'name = "backstitch-style-v1"',
                'spec_roots = ["docs/specs"]',
                "plan_roots = []",
                'code_roots = ["pkg"]',
                "",
                "[diagnostics]",
                "fail_on = []",
                "",
                "[[diagnostics.levels]]",
                'select = ["PYTHON_SYNTAX_ERROR"]',
                'level = "off"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    result = run_cli(
        "check",
        "--repo-root",
        str(tmp_path),
        "--show-suppressions",
        "--format",
        "json",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["issues"] == []
    assert data["summary"]["warnings"] == 0
    assert data["suppressed_issues"][0]["code"] == "PYTHON_SYNTAX_ERROR"
    assert data["suppressed_issues"][0]["reason"] == "diagnostic level off"


def test_packets_obeys_diagnostic_fail_on_policy(tmp_path: Path) -> None:
    write_syntax_warning_repo(tmp_path)
    (tmp_path / ".backstitch.toml").write_text(
        "\n".join(
            [
                "[profile]",
                'name = "backstitch-style-v1"',
                'spec_roots = ["docs/specs"]',
                "plan_roots = []",
                'code_roots = ["pkg"]',
                "",
                "[diagnostics]",
                'fail_on = ["warning"]',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "packets.jsonl"
    result = run_cli(
        "packets",
        "--repo-root",
        str(tmp_path),
        "--output",
        str(output),
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert not output.exists()


def test_packets_obeys_all_error_all_info_and_off_policy(tmp_path: Path) -> None:
    write_syntax_warning_repo(tmp_path)
    config = tmp_path / ".backstitch.toml"
    output = tmp_path / "packets.jsonl"
    profile = "\n".join(
        [
            "[profile]",
            'name = "backstitch-style-v1"',
            'spec_roots = ["docs/specs"]',
            "plan_roots = []",
            'code_roots = ["pkg"]',
            "",
        ]
    )

    cases = (
        ("error", "error", 1),
        ("info", "info", 1),
        ("off", "warning", 0),
    )
    for level, fail_on, expected_exit in cases:
        output.unlink(missing_ok=True)
        config.write_text(
            profile
            + "\n".join(
                [
                    "[diagnostics]",
                    f'fail_on = ["{fail_on}"]',
                    "",
                    "[[diagnostics.levels]]",
                    'select = ["PYTHON_SYNTAX_ERROR"]',
                    f'level = "{level}"',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        result = run_cli(
            "packets",
            "--repo-root",
            str(tmp_path),
            "--output",
            str(output),
        )
        assert result.returncode == expected_exit, (
            level,
            result.stdout,
            result.stderr,
        )
        if expected_exit == 0:
            assert output.read_text(encoding="utf-8").strip()
        else:
            assert not output.exists()


def test_default_level_config_changes_real_check_output(tmp_path: Path) -> None:
    write_syntax_warning_repo(tmp_path)
    (tmp_path / ".backstitch.toml").write_text(
        "\n".join(
            [
                "[profile]",
                'name = "backstitch-style-v1"',
                'spec_roots = ["docs/specs"]',
                "plan_roots = []",
                'code_roots = ["pkg"]',
                "",
                "[diagnostics]",
                'default_level = "error"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = run_cli("check", "--repo-root", str(tmp_path), "--format", "json")
    assert result.returncode == 1, result.stdout + result.stderr
    issue = next(
        item
        for item in json.loads(result.stdout)["issues"]
        if item["code"] == "PYTHON_SYNTAX_ERROR"
    )
    assert issue["severity"] == "error"
    assert issue["default_severity"] == "warning"


def test_suppressible_levels_config_changes_real_suppression_output(
    tmp_path: Path,
) -> None:
    write_syntax_warning_repo(tmp_path)
    (tmp_path / ".backstitch.toml").write_text(
        "\n".join(
            [
                "[profile]",
                'name = "backstitch-style-v1"',
                'spec_roots = ["docs/specs"]',
                "plan_roots = []",
                'code_roots = ["pkg"]',
                "",
                "[diagnostics]",
                "suppressible_levels = []",
                "",
                "[lint.per-file-ignores]",
                '"pkg/bad.py" = ["PYTHON_SYNTAX_ERROR"]',
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = run_cli(
        "check",
        "--repo-root",
        str(tmp_path),
        "--show-suppressions",
        "--format",
        "json",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert any(i["code"] == "PYTHON_SYNTAX_ERROR" for i in data["issues"])
    assert any(i["code"] == "SUPPRESSION_UNSUPPRESSIBLE_CODE" for i in data["issues"])
    assert not any(
        i["code"] == "PYTHON_SYNTAX_ERROR" for i in data["suppressed_issues"]
    )


def test_no_config_help_names_packaged_defaults() -> None:
    help_commands = (
        ("--help",),
        ("check", "--help"),
        ("packets", "--help"),
        ("analyze", "--help"),
        ("doctor", "--help"),
        ("config", "show", "--help"),
        ("config", "path", "--help"),
    )
    for args in help_commands:
        result = run_cli(*args)
        assert result.returncode == 0, result.stderr
        assert (
            "skip repository configuration; packaged defaults still load"
            in " ".join(result.stdout.split())
        )


def test_python_syntax_warning_does_not_fail_packets(tmp_path: Path) -> None:
    write_syntax_warning_repo(tmp_path)
    output = tmp_path / "packets.jsonl"
    result = run_cli(
        "packets",
        "--repo-root",
        str(tmp_path),
        "--spec-root",
        "docs/specs",
        "--code-root",
        "pkg",
        "--output",
        str(output),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert output.read_text(encoding="utf-8").strip()


def test_python_syntax_warning_config_suppression_and_inline_noqa_boundary(
    tmp_path: Path,
) -> None:
    write_syntax_warning_repo(tmp_path, inline_noqa=True)
    unsuppressed = run_cli(
        "check",
        "--repo-root",
        str(tmp_path),
        "--spec-root",
        "docs/specs",
        "--code-root",
        "pkg",
        "--format",
        "json",
    )
    unsuppressed_data = json.loads(unsuppressed.stdout)
    assert any(i["code"] == "PYTHON_SYNTAX_ERROR" for i in unsuppressed_data["issues"])

    (tmp_path / ".backstitch.toml").write_text(
        '[lint.per-file-ignores]\n"pkg/bad.py" = ["PYTHON_SYNTAX_ERROR"]\n',
        encoding="utf-8",
    )
    suppressed = run_cli(
        "check",
        "--repo-root",
        str(tmp_path),
        "--spec-root",
        "docs/specs",
        "--code-root",
        "pkg",
        "--show-suppressions",
        "--format",
        "json",
    )
    assert suppressed.returncode == 0, suppressed.stdout + suppressed.stderr
    suppressed_data = json.loads(suppressed.stdout)
    assert not any(
        i["code"] == "PYTHON_SYNTAX_ERROR" for i in suppressed_data["issues"]
    )
    assert any(
        i["code"] == "PYTHON_SYNTAX_ERROR" and i["reason"] == "config_file"
        for i in suppressed_data["suppressed_issues"]
    )


def test_broken_repo_exits_one() -> None:
    result = run_cli(
        "check",
        "--repo-root",
        str(BROKEN),
        "--spec-root",
        "docs/specifications",
        "--code-root",
        "src",
        "--code-root",
        "tests",
    )
    assert result.returncode == 1, result.stderr
    assert "Traceback" not in result.stderr


def test_bad_repo_root_exits_two() -> None:
    result = run_cli("check", "--repo-root", "/nonexistent-backstitch-xyz")
    assert result.returncode == 2
    assert "backstitch: error:" in result.stderr
    assert "Traceback" not in result.stderr


def test_unknown_profile_exits_two() -> None:
    result = run_cli("check", "--repo-root", str(CLEAN), "--profile", "nope")
    assert result.returncode == 2
    assert "unknown profile" in result.stderr


def test_json_format_and_output_file(tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    result = check_clean("--format", "json", "--output", str(out))
    assert result.returncode == 0, result.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["summary"]["errors"] == 0


def test_check_unwritable_output_exits_two(tmp_path: Path) -> None:
    target = tmp_path / "no-such-dir" / "report.json"
    result = check_clean("--output", str(target))
    assert result.returncode == 2
    assert "backstitch: error:" in result.stderr
    assert "Traceback" not in result.stderr


def test_deterministic_commands_do_not_import_llm(tmp_path: Path) -> None:
    """Tests-invariant: [INV.CLI.1]"""

    output = tmp_path / "packets.jsonl"
    commands = [
        [
            "check",
            "--repo-root",
            str(CLEAN),
            "--no-config",
            "--spec-root",
            "docs/specs",
            "--plan-root",
            "docs/plans",
            "--code-root",
            "pkg",
        ],
        [
            "packets",
            "--repo-root",
            str(CLEAN),
            "--no-config",
            "--spec-root",
            "docs/specs",
            "--plan-root",
            "docs/plans",
            "--code-root",
            "pkg",
            "--output",
            str(output),
        ],
        [
            "obligation",
            "list",
            "--repo-root",
            str(CLEAN),
            "--no-config",
            "--format",
            "json",
        ],
        ["guide", "alignment", "--format", "json"],
    ]
    for command in commands:
        snippet = (
            "import sys\n"
            "from backstitch.cli import main\n"
            f"code = main({command!r})\n"
            "assert 'llm' not in sys.modules, sorted(k for k in sys.modules if k == 'llm')\n"
            "raise SystemExit(code)\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", snippet],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
