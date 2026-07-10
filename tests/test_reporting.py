"""Render contracts: stable text layout, exact JSON keys, no filtering.

Spec: docs/specs/02-backstitch-core.md [SC-6]
"""

from __future__ import annotations

import json

import backstitch.reporting as reporting
from backstitch.models import InvariantDeclaration, Issue, Report
from backstitch.reporting import render_json, render_text

REPORT = Report(
    profile="backstitch-style-v1",
    repo_root="/tmp/x",
    spec_sections=(),
    code_refs=(),
    spec_mappings=(),
    edges=(),
    issues=(
        Issue(
            code="SPEC_FILE_MISSING",
            severity="error",
            path="pkg/mod.py",
            line=3,
            message="referenced spec file `docs/specs/09.md` does not exist",
        ),
    ),
)


def test_render_text_groups_by_severity() -> None:
    text = render_text(REPORT)
    assert "errors:" in text
    assert "pkg/mod.py:3" in text
    assert "[BSS001 SPEC_FILE_MISSING]" in text
    assert "1 errors, 0 warnings, 0 infos" in text


def test_render_text_counts_invariants_and_uses_invariant_locator() -> None:
    report = Report(
        profile=REPORT.profile,
        repo_root=REPORT.repo_root,
        spec_sections=(),
        code_refs=(),
        spec_mappings=(),
        edges=(),
        invariants=(
            InvariantDeclaration(
                invariant_id="INV.TEXT.1",
                statement="Text locates invariants.",
                tier="draft",
                declaration_kind="code",
                path="pkg/mod.py",
                line=2,
                owner_symbol="render",
                section_id=None,
            ),
        ),
        binds=(),
        issues=(
            Issue(
                code="INVARIANT_UNTESTED",
                severity="warning",
                path="pkg/mod.py",
                line=2,
                message="draft invariant has no binding test",
                context="draft",
                invariant_id="INV.TEXT.1",
            ),
        ),
    )

    text = render_text(report)

    assert "1 invariants, 0 binds" in text
    assert "invariant [INV.TEXT.1]" in text


def test_render_json_matches_sc6_keys() -> None:
    data = json.loads(render_json(REPORT))
    assert set(data) == {
        "profile",
        "repo_root",
        "summary",
        "spec_sections",
        "code_refs",
        "spec_mappings",
        "edges",
        "invariants",
        "binds",
        "issues",
    }


def test_filter_report_does_not_exist() -> None:
    # Fable's audit-free filter layer is deliberately not ported ([EXC-*]).
    assert not hasattr(reporting, "filter_report")
