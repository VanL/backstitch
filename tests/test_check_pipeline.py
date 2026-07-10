"""Shared check/suppression pipeline.

Spec: docs/specs/02-backstitch-core.md [SC-5], [SC-6]
Spec: docs/specs/04-backstitch-traceability-exclusions.md [EXC-6], [EXC-7]
"""

from __future__ import annotations

from pathlib import Path

from backstitch.check_pipeline import build_check_report
from backstitch.profiles import get_profile
from backstitch.settings import BackstitchSettings, LintSettings


def test_pipeline_returns_suppressed_records_and_structured_hygiene_issues(
    tmp_path: Path,
) -> None:
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "docs/plans").mkdir(parents=True)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "docs/specs/01-x.md").write_text(
        "# Spec\n\n## X [X-1]\n",
        encoding="utf-8",
    )
    profile = get_profile("backstitch-style-v1").with_overrides(
        spec_roots=("docs/specs",),
        plan_roots=("docs/plans",),
        code_roots=("pkg",),
        meta_spec_globs=("docs/specs/*.md",),
    )
    settings = BackstitchSettings(
        lint=LintSettings(per_file_ignores={"missing/*.py": ("CODE_REF_BROAD",)})
    )

    result = build_check_report(tmp_path, profile, settings)

    assert len(result.report.issues) == 1
    assert result.report.issues[0].code == "SUPPRESSION_UNUSED"
    assert "missing/*.py" in result.report.issues[0].message
    assert len(result.suppressed) == 1
    suppressed_issue, reason = result.suppressed[0]
    assert suppressed_issue.code == "SPEC_SECTION_UNMAPPED"
    assert reason == "meta"
    assert result.warnings == ()
