"""Shared deterministic scan and suppression pipeline.

Spec: docs/specs/02-backstitch-core.md [SC-5], [SC-6]
Spec: docs/specs/04-backstitch-traceability-exclusions.md [EXC-6], [EXC-7]
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path

from backstitch.config import ProfileConfig
from backstitch.exclusions import (
    build_suppression_index,
    collect_unused_ignore_warnings,
    should_suppress,
)
from backstitch.models import Issue, Report
from backstitch.resolver import scan_repository_with_artifacts
from backstitch.settings import BackstitchSettings

SuppressedRecord = tuple[Issue, str]


@dataclass(frozen=True, slots=True)
class CheckPipelineResult:
    """A report after suppression, plus audit data and diagnostics."""

    report: Report
    suppressed: tuple[SuppressedRecord, ...]
    warnings: tuple[str, ...]


def build_check_report(
    repo_root: Path,
    profile: ProfileConfig,
    settings: BackstitchSettings,
) -> CheckPipelineResult:
    """Scan, apply suppression once, and return command-ready data."""

    report, artifacts = scan_repository_with_artifacts(
        repo_root,
        profile,
        exclude_globs=settings.exclude,
        allow_unknown_suppression_codes=settings.allow_unknown_keys,
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
        marker_warnings=list(artifacts.marker_warnings),
        allow_unknown=settings.allow_unknown_keys,
    )
    kept: list[Issue] = []
    suppressed: list[SuppressedRecord] = []
    for issue in report.issues:
        is_suppressed, reason = should_suppress(issue, index)
        if is_suppressed and reason is not None:
            suppressed.append((issue, reason.value))
        else:
            kept.append(issue)
    filtered_report = dataclasses.replace(report, issues=tuple(kept))
    warnings = tuple(index.suppression_warnings) + tuple(
        collect_unused_ignore_warnings(index)
    )
    return CheckPipelineResult(
        report=filtered_report,
        suppressed=tuple(suppressed),
        warnings=warnings,
    )
