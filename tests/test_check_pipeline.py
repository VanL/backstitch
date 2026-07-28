"""Shared check/suppression pipeline.

Spec: docs/specs/02-backstitch-core.md [SC-5], [SC-6]
Spec: docs/specs/04-backstitch-traceability-exclusions.md [EXC-6], [EXC-7]
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backstitch.models import SuppressionOrigin, SuppressionRule
from backstitch.obligation_runtime import build_obligation_runtime
from backstitch.profiles import get_profile
from backstitch.settings import BackstitchSettings, LintSettings, resolve_config


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
    assert result.suppressed[0].issue.code == "SPEC_SECTION_UNMAPPED"
    assert result.suppressed[0].reason == "meta"
    assert result.warnings == ()


def test_declared_inline_suppression_is_auditable_end_to_end(
    tmp_path: Path,
) -> None:
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "pkg").mkdir()
    reference = "docs/specs/01-x.md#SUP-X"
    (tmp_path / "docs/specs/01-x.md").write_text(
        "## X [X-1]\n\n"
        '_Traceability: suppression-declaration [SUP-X] "Process-only section."_\n\n'
        f"_Traceability: ignore SPEC_SECTION_UNMAPPED because {reference}_\n",
        encoding="utf-8",
    )
    profile = get_profile("backstitch-style-v1").with_overrides(
        spec_roots=("docs/specs",),
        plan_roots=(),
        code_roots=("pkg",),
    )
    settings = BackstitchSettings(
        lint=LintSettings(require_suppression_declarations=True)
    )

    result = build_obligation_runtime(tmp_path, profile, settings).pipeline

    assert result.report.issues == ()
    assert len(result.suppressed) == 1
    decision = result.suppressed[0]
    assert decision.issue.code == "SPEC_SECTION_UNMAPPED"
    assert decision.reason == "inline_spec"
    assert decision.declaration == reference
    assert decision.rationale == "Process-only section."
    assert decision.rule is not None


def test_declared_html_suppression_is_auditable_end_to_end(tmp_path: Path) -> None:
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "pkg").mkdir()
    reference = "docs/specs/01-x.md#SUP-HTML"
    (tmp_path / "docs/specs/01-x.md").write_text(
        "## X [X-1]\n\n"
        '_Traceability: suppression-declaration [SUP-HTML] "HTML-local exception."_\n\n'
        "<!-- backstitch: ignore SPEC_SECTION_UNMAPPED because "
        f"{reference} -->\n",
        encoding="utf-8",
    )
    profile = get_profile("backstitch-style-v1").with_overrides(
        spec_roots=("docs/specs",), plan_roots=(), code_roots=("pkg",)
    )

    result = build_obligation_runtime(
        tmp_path,
        profile,
        BackstitchSettings(lint=LintSettings(require_suppression_declarations=True)),
    ).pipeline

    assert result.report.issues == ()
    assert [(item.reason, item.declaration) for item in result.suppressed] == [
        ("inline_spec", reference)
    ]


def test_declaration_bearing_python_docstring_and_comment_rules_fire(
    tmp_path: Path,
) -> None:
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "pkg").mkdir()
    reference = "docs/specs/01-x.md#SUP-PYTHON"
    (tmp_path / "docs/specs/01-x.md").write_text(
        "## X [X-1]\n\n"
        '_Traceability: suppression-declaration [SUP-PYTHON] "Local code citations."_\n',
        encoding="utf-8",
    )
    (tmp_path / "pkg/docstring.py").write_text(
        f'"""backstitch: noqa SPEC_MAPPING_RECIPROCAL_MISSING because {reference}"""\n\n'
        "def documented() -> None:\n"
        '    """Spec: docs/specs/01-x.md [X-1]"""\n',
        encoding="utf-8",
    )
    (tmp_path / "pkg/comment.py").write_text(
        "# backstitch: noqa SPEC_MAPPING_RECIPROCAL_MISSING because "
        f"{reference}\n"
        "def commented() -> None:\n"
        '    """Spec: docs/specs/01-x.md [X-1]"""\n',
        encoding="utf-8",
    )
    profile = get_profile("backstitch-style-v1").with_overrides(
        spec_roots=("docs/specs",), plan_roots=(), code_roots=("pkg",)
    )

    result = build_obligation_runtime(
        tmp_path,
        profile,
        BackstitchSettings(lint=LintSettings(require_suppression_declarations=True)),
    ).pipeline

    suppressed_paths = {
        item.issue.path
        for item in result.suppressed
        if item.issue.code == "SPEC_MAPPING_RECIPROCAL_MISSING"
    }
    assert suppressed_paths == {"pkg/comment.py", "pkg/docstring.py"}
    assert all(
        item.declaration == reference
        for item in result.suppressed
        if item.issue.code == "SPEC_MAPPING_RECIPROCAL_MISSING"
    )


def test_required_mode_leaves_legacy_suppression_finding_active(
    tmp_path: Path,
) -> None:
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "docs/specs/01-x.md").write_text(
        "## X [X-1]\n\n_Traceability: ignore SPEC_SECTION_UNMAPPED_\n",
        encoding="utf-8",
    )
    profile = get_profile("backstitch-style-v1").with_overrides(
        spec_roots=("docs/specs",),
        plan_roots=(),
        code_roots=("pkg",),
    )
    settings = BackstitchSettings(
        lint=LintSettings(require_suppression_declarations=True)
    )

    result = build_obligation_runtime(tmp_path, profile, settings).pipeline

    assert result.suppressed == ()
    assert {item.code for item in result.report.issues} == {
        "SPEC_SECTION_UNMAPPED",
        "SUPPRESSION_REASON_MISSING",
    }


@pytest.mark.parametrize(
    ("declaration_source", "reference", "source_hygiene"),
    (
        ("", "docs/specs/01-x.md#SUP-MISSING", None),
        (
            '_Traceability: suppression-declaration [SUP-BLANK] ""_\n',
            "docs/specs/01-x.md#SUP-BLANK",
            "SUPPRESSION_REASON_MISSING",
        ),
        (
            '_Traceability: suppression-declaration [sup-bad] "Reason."_\n',
            "docs/specs/01-x.md#SUP-BAD",
            "SUPPRESSION_INVALID_SYNTAX",
        ),
        ("", "docs/other/01-outside.md#SUP-OUTSIDE", None),
    ),
)
@pytest.mark.parametrize("require_declarations", (False, True))
def test_invalid_or_unresolved_declaration_leaves_original_finding_active(
    tmp_path: Path,
    declaration_source: str,
    reference: str,
    source_hygiene: str | None,
    require_declarations: bool,
) -> None:
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "pkg").mkdir()
    if reference.startswith("docs/other/"):
        (tmp_path / "docs/other").mkdir()
        (tmp_path / "docs/other/01-outside.md").write_text(
            "## Outside [OUT-1]\n\n"
            '_Traceability: suppression-declaration [SUP-OUTSIDE] "Outside root."_\n',
            encoding="utf-8",
        )
    (tmp_path / "docs/specs/01-x.md").write_text(
        "## X [X-1]\n\n"
        f"{declaration_source}\n"
        "_Traceability: ignore SPEC_SECTION_UNMAPPED because "
        f"{reference}_\n",
        encoding="utf-8",
    )
    profile = get_profile("backstitch-style-v1").with_overrides(
        spec_roots=("docs/specs",), plan_roots=(), code_roots=("pkg",)
    )

    result = build_obligation_runtime(
        tmp_path,
        profile,
        BackstitchSettings(
            lint=LintSettings(
                require_suppression_declarations=require_declarations,
            )
        ),
    ).pipeline

    assert result.suppressed == ()
    codes = [item.code for item in result.report.issues]
    assert "SPEC_SECTION_UNMAPPED" in codes
    assert "SUPPRESSION_REASON_MISSING" in codes
    if source_hygiene is not None:
        assert source_hygiene in codes


def test_declared_rules_preserve_inline_precedence_and_exact_section_scope(
    tmp_path: Path,
) -> None:
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "pkg").mkdir()
    reference = "docs/specs/01-x.md#SUP-SCOPE"
    (tmp_path / "docs/specs/01-x.md").write_text(
        "## One [X-1]\n\n"
        '_Traceability: suppression-declaration [SUP-SCOPE] "Exact section."_\n\n'
        "_Traceability: ignore SPEC_SECTION_UNMAPPED because "
        f"{reference}_\n\n"
        "## Two [X-2]\n",
        encoding="utf-8",
    )
    profile = get_profile("backstitch-style-v1").with_overrides(
        spec_roots=("docs/specs",), plan_roots=(), code_roots=("pkg",)
    )
    settings = BackstitchSettings(
        lint=LintSettings(
            require_suppression_declarations=True,
            suppressions=(
                SuppressionRule(
                    mechanism="ignore",
                    provenance="config_section",
                    path="docs/specs/01-x.md",
                    sections=("X-1",),
                    codes=("SPEC_SECTION_UNMAPPED",),
                    declaration=reference,
                    origin=SuppressionOrigin(source="/trusted/config.toml", position=0),
                ),
            ),
        )
    )

    result = build_obligation_runtime(tmp_path, profile, settings).pipeline

    assert [(item.issue.section_id, item.reason) for item in result.suppressed] == [
        ("X-1", "inline_spec")
    ]
    assert [
        item.section_id
        for item in result.report.issues
        if item.code == "SPEC_SECTION_UNMAPPED"
    ] == ["X-2"]


def test_resolved_structured_meta_rule_drives_check_and_obligation(
    tmp_path: Path,
) -> None:
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "pkg").mkdir()
    spec_path = "docs/specs/01-x.md"
    reference = f"{spec_path}#SUP-META"
    (tmp_path / spec_path).write_text(
        "## X [X-1]\n\n"
        '_Traceability: suppression-declaration [SUP-META] "Process contract."_\n',
        encoding="utf-8",
    )
    config = tmp_path / ".backstitch.toml"
    config.write_text(
        "[lint]\n"
        "require_suppression_declarations = true\n\n"
        "[[lint.suppressions]]\n"
        'mechanism = "meta"\n'
        f'path = "{spec_path}"\n'
        "sections = []\n"
        "codes = []\n"
        f'declaration = "{reference}"\n',
        encoding="utf-8",
    )
    profile = get_profile("backstitch-style-v1").with_overrides(
        spec_roots=("docs/specs",), plan_roots=(), code_roots=("pkg",)
    )

    runtime = build_obligation_runtime(
        tmp_path,
        profile,
        resolve_config(tmp_path, explicit=config, environment={}),
    )

    assert runtime.pipeline.effective_meta_spec_globs == (spec_path,)
    assert [(item.issue.code, item.reason) for item in runtime.pipeline.suppressed] == [
        ("SPEC_SECTION_UNMAPPED", "meta")
    ]
    obligation = runtime.inventory.get(f"{spec_path}#X-1")
    assert obligation is not None
    assert obligation.obligation_rung == "meta"


def test_duplicate_declarations_invalidate_every_reference(
    tmp_path: Path,
) -> None:
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "pkg").mkdir()
    for name, section in (("01-a.md", "A-1"), ("02-b.md", "B-1")):
        (tmp_path / "docs/specs" / name).write_text(
            f"## Contract [{section}]\n\n"
            '_Traceability: suppression-declaration [SUP-DUP] "Reason."_\n',
            encoding="utf-8",
        )
    profile = get_profile("backstitch-style-v1").with_overrides(
        spec_roots=("docs/specs",),
        plan_roots=(),
        code_roots=("pkg",),
    )

    result = build_obligation_runtime(
        tmp_path,
        profile,
        BackstitchSettings(),
    ).pipeline

    assert result.artifacts.suppression_declarations == ()
    duplicate_issues = [
        item
        for item in result.report.issues
        if item.code == "SUPPRESSION_INVALID_SYNTAX"
    ]
    assert len(duplicate_issues) == 2


def test_structured_suppression_uses_the_same_decision_path(
    tmp_path: Path,
) -> None:
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "pkg").mkdir()
    reference = "docs/specs/01-x.md#SUP-CONFIG"
    (tmp_path / "docs/specs/01-x.md").write_text(
        "## Contract [S-1]\n\n"
        '_Traceability: suppression-declaration [SUP-CONFIG] "Bounded config rule."_\n',
        encoding="utf-8",
    )
    profile = get_profile("backstitch-style-v1").with_overrides(
        spec_roots=("docs/specs",),
        plan_roots=(),
        code_roots=("pkg",),
    )
    settings = BackstitchSettings(
        lint=LintSettings(
            suppressions=(
                SuppressionRule(
                    mechanism="ignore",
                    provenance="config_section",
                    path="docs/specs/01-x.md",
                    sections=("S-1",),
                    codes=("SPEC_SECTION_UNMAPPED",),
                    declaration=reference,
                    origin=SuppressionOrigin(source="/trusted/config.toml", position=0),
                ),
            )
        )
    )

    result = build_obligation_runtime(tmp_path, profile, settings).pipeline

    assert result.report.issues == ()
    assert result.suppressed[0].reason == "config_section"
    assert result.suppressed[0].declaration == reference


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
