"""Typed deterministic-check application and CLI equivalence.

Spec: docs/specs/02-backstitch-core.md [SC-5], [SC-10]
Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-8.2], [EVC-8.7]
Plan: docs/plans/2026-07-29-architecture-quality-remediation-plan.md Slice 5
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backstitch import check_application, cli
from backstitch.check_application import (
    CheckFailure,
    CheckRequest,
    CheckResult,
    check_repository,
)
from backstitch.config import ProfileConfig
from backstitch.profiles import get_profile
from backstitch.reporting import render_json
from backstitch.repository_snapshot import SnapshotCaptureError
from backstitch.resolver import ScanError
from backstitch.settings import (
    BackstitchSettings,
    CheckSettings,
    ProfileSettings,
)


def _write_warning_repo(root: Path) -> None:
    spec_dir = root / "docs/specs"
    spec_dir.mkdir(parents=True)
    spec_dir.joinpath("01-x.md").write_text(
        "# X\n\n## Thing [X-1]\n\n_Implementation mapping_:\n\n- `pkg/good.py`\n",
        encoding="utf-8",
    )
    package = root / "pkg"
    package.mkdir()
    package.joinpath("good.py").write_text(
        '"""Spec: docs/specs/01-x.md [X-1]"""\n',
        encoding="utf-8",
    )
    package.joinpath("bad.py").write_text("def broken(:\n", encoding="utf-8")


def _settings(*, warnings_as_errors: bool) -> BackstitchSettings:
    return BackstitchSettings(
        profile_overrides=ProfileSettings(
            spec_roots=("docs/specs",),
            plan_roots=(),
            code_roots=("pkg",),
            test_roots=(),
        ),
        check=CheckSettings(format="json", warnings_as_errors=warnings_as_errors),
    )


def _profile() -> ProfileConfig:
    return get_profile("backstitch-style-v1").with_overrides(
        spec_roots=("docs/specs",),
        plan_roots=(),
        code_roots=("pkg",),
        test_roots=(),
    )


@pytest.mark.parametrize(
    ("warnings_as_errors", "expected_exit"),
    ((False, 0), (True, 1)),
)
def test_check_application_matches_cli_bytes_and_gate_classification(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    warnings_as_errors: bool,
    expected_exit: int,
) -> None:
    _write_warning_repo(tmp_path)
    settings = _settings(warnings_as_errors=warnings_as_errors)
    outcome = check_repository(CheckRequest(tmp_path, _profile(), settings))
    assert isinstance(outcome, CheckResult)

    args = cli.build_parser().parse_args(
        ["check", "--repo-root", str(tmp_path), "--format", "json"]
    )
    exit_code = cli._cmd_check(args, settings)
    captured = capsys.readouterr()

    assert outcome.blocks_gate is warnings_as_errors
    assert exit_code == expected_exit
    assert captured.out == render_json(outcome.pipeline.report)
    assert captured.err == "".join(
        f"warning: {warning}\n" for warning in outcome.warnings
    )


def test_check_application_classifies_snapshot_failure_before_cli_mapping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = _settings(warnings_as_errors=False)

    def fail_capture(*_args: object, **_kwargs: object) -> object:
        raise SnapshotCaptureError(
            "snapshot_unstable",
            "SNAPSHOT_UNSTABLE after 3 capture attempts",
            attempts=3,
        )

    monkeypatch.setattr(
        check_application.obligation_runtime,
        "capture_obligation_snapshot",
        fail_capture,
    )
    outcome = check_repository(CheckRequest(tmp_path, _profile(), settings))
    assert outcome == CheckFailure(
        code="snapshot_unstable",
        message="SNAPSHOT_UNSTABLE after 3 capture attempts",
    )

    args = cli.build_parser().parse_args(
        ["check", "--repo-root", str(tmp_path), "--format", "json"]
    )
    with pytest.raises(ScanError, match="SNAPSHOT_UNSTABLE"):
        cli._cmd_check(args, settings)
    assert capsys.readouterr().out == ""
