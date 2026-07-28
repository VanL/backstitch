"""Shared deterministic scan and suppression pipeline.

Spec: docs/specs/02-backstitch-core.md [SC-5], [SC-6]
Spec: docs/specs/04-backstitch-traceability-exclusions.md [EXC-6], [EXC-7]
Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-8.2], [EVC-8.3.2]
"""

from __future__ import annotations

import dataclasses
from collections.abc import MutableMapping
from dataclasses import dataclass

from backstitch.code_parser import ParsedModule
from backstitch.config import ProfileConfig
from backstitch.diagnostics import apply_policy_to_report, issue_with_policy
from backstitch.exclusions import (
    build_suppression_index,
    collect_unused_ignore_diagnostics,
    suppression_decision,
)
from backstitch.markdown_specs import MarkdownParseMemo
from backstitch.models import (
    Issue,
    Report,
    SuppressionDecision,
    issue_sort_key,
)
from backstitch.repository_snapshot import RepositorySnapshot
from backstitch.resolver import ScanArtifacts, scan_snapshot_with_artifacts
from backstitch.settings import BackstitchSettings


@dataclass(frozen=True, slots=True)
class ObligationSkipAudit:
    """One valid skip plus the effective BSE001 policy projection."""

    obligation_id: str
    target_id: str
    path: str
    line: int
    reason: str
    effective_policy: str


@dataclass(frozen=True, slots=True)
class CheckPipelineResult:
    """A report after suppression, plus audit data and diagnostics."""

    raw_report: Report
    report: Report
    artifacts: ScanArtifacts
    suppressed: tuple[SuppressionDecision, ...]
    effective_meta_spec_globs: tuple[str, ...]
    effective_section_meta: frozenset[tuple[str, str]]
    obligation_skip_audit: tuple[ObligationSkipAudit, ...]
    warnings: tuple[str, ...]


def build_check_report_from_snapshot(
    snapshot: RepositorySnapshot,
    repo_root_display: str,
    profile: ProfileConfig,
    settings: BackstitchSettings,
    *,
    python_parse_memo: MutableMapping[tuple[str, str], ParsedModule] | None = None,
    markdown_parse_memo: MarkdownParseMemo | None = None,
) -> CheckPipelineResult:
    """Build a command-ready report without reopening captured source files."""

    raw_report, artifacts = scan_snapshot_with_artifacts(
        snapshot,
        repo_root_display,
        profile,
        allow_unknown_suppression_codes=settings.allow_unknown_keys,
        python_parse_memo=python_parse_memo,
        markdown_parse_memo=markdown_parse_memo,
    )
    return _apply_check_policy(raw_report, artifacts, profile, settings)


def _apply_check_policy(
    raw_report: Report,
    artifacts: ScanArtifacts,
    profile: ProfileConfig,
    settings: BackstitchSettings,
) -> CheckPipelineResult:
    report, off_records = apply_policy_to_report(
        raw_report,
        effective_policy=settings.diagnostics,
    )
    index = build_suppression_index(
        meta_spec_globs=profile.meta_spec_globs,
        lint=settings.lint,
        section_meta=artifacts.section_meta,
        inline_file_ignores=artifacts.inline_file_ignores,
        inline_spec_ignores=artifacts.inline_spec_ignores,
        inline_code_ignores=artifacts.inline_code_ignores,
        inline_code_span_ignores=artifacts.inline_code_span_ignores,
        sections_with_markers=artifacts.sections_with_markers,
        marker_diagnostics=list(artifacts.marker_diagnostics),
        declarations=artifacts.suppression_declarations,
        inline_spec_rules=artifacts.inline_spec_rules,
        inline_code_rules=artifacts.inline_code_rules,
        inline_code_span_rules=artifacts.inline_code_span_rules,
        allow_unknown=settings.allow_unknown_keys,
    )
    kept: list[Issue] = []
    suppressed: list[SuppressionDecision] = [
        SuppressionDecision(
            issue=issue,
            reason="diagnostic level off",
            declaration=None,
            rationale=None,
            rule=None,
        )
        for issue, _reason in off_records
    ]
    for issue in report.issues:
        decision = suppression_decision(
            issue,
            index,
            suppressible_levels=settings.diagnostics.suppressible_levels,
        )
        if decision is not None:
            suppressed.append(decision)
        else:
            kept.append(issue)
    diagnostics = tuple(index.suppression_diagnostics) + tuple(
        collect_unused_ignore_diagnostics(index)
    )
    for diagnostic in diagnostics:
        issue = diagnostic.to_issue()
        patched, off_issue = issue_with_policy(
            issue,
            effective_policy=settings.diagnostics,
        )
        if patched is not None:
            kept.append(patched)
        elif off_issue is not None:
            suppressed.append(
                SuppressionDecision(
                    issue=off_issue,
                    reason="diagnostic level off",
                    declaration=None,
                    rationale=None,
                    rule=None,
                )
            )
    kept.sort(key=issue_sort_key)
    filtered_report = dataclasses.replace(report, issues=tuple(kept))
    active_bse = {
        (issue.path, issue.line, issue.invariant_id or issue.section_id): issue.severity
        for issue in kept
        if issue.code == "OBLIGATION_SKIPPED"
    }
    off_bse = {
        (
            decision.issue.path,
            decision.issue.line,
            decision.issue.invariant_id or decision.issue.section_id,
        ): (
            "off"
            if decision.reason == "diagnostic level off"
            else decision.issue.severity
        )
        for decision in suppressed
        if decision.issue.code == "OBLIGATION_SKIPPED"
    }
    skip_audit = tuple(
        ObligationSkipAudit(
            obligation_id=item.obligation_id,
            target_id=item.target_id,
            path=item.path,
            line=item.line,
            reason=item.reason,
            effective_policy=(
                active_bse.get(
                    (item.path, item.line, item.target_id),
                    off_bse.get((item.path, item.line, item.target_id), "info"),
                )
            ),
        )
        for item in artifacts.obligation_skips
    )
    return CheckPipelineResult(
        raw_report=raw_report,
        report=filtered_report,
        artifacts=artifacts,
        suppressed=tuple(suppressed),
        effective_meta_spec_globs=tuple(
            sorted(
                {
                    rule.path
                    for rule in index.rules
                    if rule.mechanism == "meta" and not rule.sections
                }
            )
        ),
        effective_section_meta=frozenset(
            (rule.path, section_id)
            for rule in index.rules
            if rule.mechanism == "meta"
            for section_id in rule.sections
        ),
        obligation_skip_audit=skip_audit,
        warnings=(),
    )
