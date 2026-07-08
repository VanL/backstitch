"""Subprocess CLI contract: exit codes, output modes, no tracebacks.

Spec: docs/specs/02-backstitch-core.md [SC-5]
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

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
    output = tmp_path / "packets.jsonl"
    commands = [
        [
            "check",
            "--repo-root",
            str(CLEAN),
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
            "--spec-root",
            "docs/specs",
            "--plan-root",
            "docs/plans",
            "--code-root",
            "pkg",
            "--output",
            str(output),
        ],
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
