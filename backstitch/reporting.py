"""Text and JSON rendering for deterministic reports.

Spec: docs/specs/02-backstitch-core.md [SC-5], [SC-6]

Rendering only: suppression is `backstitch.exclusions`' job ([EXC-*]) and
happens before reports reach this module. There is deliberately no
report-filtering here -- a finding that disappears from every view with no
audit trail is the anti-pattern the exclusions spec exists to prevent.
"""

from __future__ import annotations

import json

from backstitch.models import Issue, Report

_SEVERITY_ORDER = ("error", "warning", "info")
_GROUP_TITLES = {"error": "errors", "warning": "warnings", "info": "infos"}


def _issue_line(issue: Issue) -> str:
    location = issue.path if issue.line is None else f"{issue.path}:{issue.line}"
    suffix = f" (section [{issue.section_id}])" if issue.section_id else ""
    return f"  {location} [{issue.code}] {issue.message}{suffix}"


def render_text(report: Report) -> str:
    """Render a stable, grouped text report."""

    summary = report.summary()
    lines = [
        f"backstitch check: profile {report.profile}",
        f"repo root: {report.repo_root}",
        "",
        (
            f"summary: {summary['spec_sections']} spec sections,"
            f" {summary['spec_mappings']} mappings,"
            f" {summary['code_refs']} code refs,"
            f" {len(report.edges)} edges"
        ),
        (
            f"issues: {summary['errors']} errors,"
            f" {summary['warnings']} warnings,"
            f" {summary['infos']} infos"
        ),
    ]
    for severity in _SEVERITY_ORDER:
        group = [i for i in report.issues if i.severity == severity]
        if not group:
            continue
        lines.append("")
        lines.append(f"{_GROUP_TITLES[severity]}:")
        lines.extend(_issue_line(issue) for issue in group)
    return "\n".join(lines) + "\n"


def render_json(report: Report) -> str:
    """Render the exact [SC-6] JSON report contract."""

    return json.dumps(report.to_dict(), indent=2) + "\n"
