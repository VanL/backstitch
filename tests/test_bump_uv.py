from __future__ import annotations

import subprocess
import sys
from importlib import util
from pathlib import Path
from types import ModuleType

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY_ROOT / "bin" / "bump_uv.py"
WORKFLOWS = (
    "ci.yml",
    "local-llm.yml",
    "release-gate.yml",
    "semantic-pr-report.yml",
    "semantic-refresh.yml",
)


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text("[tool.uv]\ndefault-groups = []\n")
    (tmp_path / "uv.lock").write_text("old lock\n")
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    for name in WORKFLOWS:
        (workflow_dir / name).write_text("name: Test\n\njobs: {}\n")
    return tmp_path


@pytest.fixture
def bump_uv_module() -> ModuleType:
    spec = util.spec_from_file_location("bump_uv", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dry_run_reports_every_managed_file_without_writing(
    repository: Path,
) -> None:
    pyproject = repository / "pyproject.toml"
    workflow_dir = repository / ".github" / "workflows"
    paths = (pyproject, *(workflow_dir / name for name in WORKFLOWS))
    before = {path: path.read_bytes() for path in paths}

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--root",
            str(repository),
            "--ci-version",
            "0.12.5",
            "--required-version",
            ">=0.12.5,<0.13",
            "--dry-run",
        ],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "pyproject.toml" in result.stdout
    assert all(name in result.stdout for name in WORKFLOWS)
    assert {path: path.read_bytes() for path in paths} == before


def test_update_and_check_cover_the_root_lock(
    repository: Path,
    bump_uv_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[list[str]] = []

    def run(command: list[str], *, cwd: Path, check: bool) -> None:
        assert cwd == repository
        assert check is True
        calls.append(command)

    monkeypatch.setattr(bump_uv_module.subprocess, "run", run)

    assert (
        bump_uv_module.main(
            [
                "--root",
                str(repository),
                "--ci-version",
                "0.12.5",
                "--required-version",
                ">=0.12.5,<0.13",
            ]
        )
        == 0
    )
    assert (
        'required-version = ">=0.12.5,<0.13"'
        in (repository / "pyproject.toml").read_text()
    )
    for name in WORKFLOWS:
        workflow = repository / ".github" / "workflows" / name
        assert workflow.read_text().count('UV_VERSION: "0.12.5"') == 1
    assert calls == [["uv", "lock"], ["uv", "lock", "--check"]]

    capsys.readouterr()
    assert bump_uv_module.main(["--root", str(repository), "--check"]) == 0
    assert calls[-1] == ["uv", "lock", "--check"]


def test_failed_lock_refresh_restores_manifests_and_lock(
    repository: Path,
    bump_uv_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_dir = repository / ".github" / "workflows"
    paths = (
        repository / "pyproject.toml",
        *(workflow_dir / name for name in WORKFLOWS),
        repository / "uv.lock",
    )
    before = {path: path.read_bytes() for path in paths}

    def fail(command: list[str], *, cwd: Path, check: bool) -> None:
        (repository / "uv.lock").write_text("changed lock\n")
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(bump_uv_module.subprocess, "run", fail)

    assert (
        bump_uv_module.main(
            [
                "--root",
                str(repository),
                "--ci-version",
                "0.12.5",
                "--required-version",
                ">=0.12.5,<0.13",
            ]
        )
        == 1
    )
    assert {path: path.read_bytes() for path in paths} == before


@pytest.mark.parametrize("problem", ["missing_jobs", "duplicate_pin", "unmanaged"])
def test_invalid_workflow_sets_fail_before_writing(
    repository: Path,
    bump_uv_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    problem: str,
) -> None:
    workflow_dir = repository / ".github" / "workflows"
    if problem == "missing_jobs":
        (workflow_dir / "ci.yml").write_text("name: Test\n")
    elif problem == "duplicate_pin":
        (workflow_dir / "ci.yml").write_text(
            'name: Test\n\nenv:\n  UV_VERSION: "0.12.4"\n'
            '  UV_VERSION: "0.12.5"\n\njobs: {}\n'
        )
    else:
        (workflow_dir / "unmanaged.yaml").write_text(
            "name: Unmanaged\nsteps:\n  - uses: astral-sh/setup-uv@abc\n"
        )

    paths = (
        repository / "pyproject.toml",
        *(workflow_dir / name for name in WORKFLOWS),
        repository / "uv.lock",
    )
    before = {path: path.read_bytes() for path in paths}
    calls: list[list[str]] = []
    monkeypatch.setattr(
        bump_uv_module.subprocess,
        "run",
        lambda command, **kwargs: calls.append(command),
    )

    assert (
        bump_uv_module.main(
            [
                "--root",
                str(repository),
                "--ci-version",
                "0.12.5",
                "--required-version",
                ">=0.12.5,<0.13",
            ]
        )
        == 1
    )
    assert calls == []
    assert {path: path.read_bytes() for path in paths} == before
