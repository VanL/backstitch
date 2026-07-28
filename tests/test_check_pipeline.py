"""Shared check/suppression pipeline.

Spec: docs/specs/02-backstitch-core.md [SC-5], [SC-6]
Spec: docs/specs/04-backstitch-traceability-exclusions.md [EXC-6], [EXC-7]
"""

from __future__ import annotations

from pathlib import Path

from backstitch.obligation_runtime import build_obligation_runtime
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

    result = build_obligation_runtime(tmp_path, profile, settings).pipeline

    assert [issue.code for issue in result.raw_report.issues] == [
        "SPEC_SECTION_UNMAPPED"
    ]
    assert result.artifacts.section_meta == {}
    assert len(result.report.issues) == 1
    assert result.report.issues[0].code == "SUPPRESSION_UNUSED"
    assert "missing/*.py" in result.report.issues[0].message
    assert len(result.suppressed) == 1
    suppressed_issue, reason = result.suppressed[0]
    assert suppressed_issue.code == "SPEC_SECTION_UNMAPPED"
    assert reason == "meta"
    assert result.warnings == ()


def test_missing_skip_reason_fires_bsx010_without_strict_loader_failure(
    tmp_path: Path,
) -> None:
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "docs/specs/01-x.md").write_text(
        "## X [X-1]\n<!-- backstitch: skip-obligation [X-1] -->\n",
        encoding="utf-8",
    )
    profile = get_profile("backstitch-style-v1").with_overrides(
        spec_roots=("docs/specs",),
        plan_roots=(),
        code_roots=("pkg",),
    )

    result = build_obligation_runtime(tmp_path, profile, BackstitchSettings()).pipeline

    issue = next(
        item
        for item in result.report.issues
        if item.code == "SUPPRESSION_REASON_MISSING"
    )
    assert issue.short_code == "BSX010"
    assert issue.path == "docs/specs/01-x.md"
    assert issue.line == 2


def test_valid_skip_has_a_structured_audit_even_when_bse001_is_visible(
    tmp_path: Path,
) -> None:
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "docs/specs/01-x.md").write_text(
        "## X [X-1]\n"
        '<!-- backstitch: skip-obligation [X-1] "External conformance." -->\n',
        encoding="utf-8",
    )
    profile = get_profile("backstitch-style-v1").with_overrides(
        spec_roots=("docs/specs",),
        plan_roots=(),
        code_roots=("pkg",),
    )

    result = build_obligation_runtime(tmp_path, profile, BackstitchSettings()).pipeline

    assert [item.code for item in result.report.issues] == [
        "SPEC_SECTION_UNMAPPED",
        "OBLIGATION_SKIPPED",
    ]
    assert len(result.obligation_skip_audit) == 1
    assert result.obligation_skip_audit[0].obligation_id == ("docs/specs/01-x.md#X-1")
    assert result.obligation_skip_audit[0].target_id == "X-1"
    assert result.obligation_skip_audit[0].reason == "External conformance."
    assert result.obligation_skip_audit[0].effective_policy == "info"
