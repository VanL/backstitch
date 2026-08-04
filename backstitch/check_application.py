"""Typed application seam for one deterministic repository check.

Spec: docs/specs/02-backstitch-core.md [SC-5], [SC-17]
Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-8.2], [EVC-8.7]
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backstitch import check_pipeline, obligation_runtime
from backstitch.check_pipeline import CheckPipelineResult
from backstitch.config import ProfileConfig
from backstitch.markdown_specs import MarkdownParseMemo
from backstitch.repository_snapshot import SnapshotCaptureError
from backstitch.settings import BackstitchSettings

__all__ = (
    "CheckFailure",
    "CheckRequest",
    "CheckResult",
    "check_repository",
)


@dataclass(frozen=True, slots=True)
class CheckRequest:
    """Resolved inputs for one deterministic check."""

    repo_root: Path
    profile: ProfileConfig
    settings: BackstitchSettings


@dataclass(frozen=True, slots=True)
class CheckResult:
    """One captured check pipeline and its effective gate classification."""

    pipeline: CheckPipelineResult
    warnings: tuple[str, ...]
    blocks_gate: bool


@dataclass(frozen=True, slots=True)
class CheckFailure:
    """A repository snapshot failure classified before CLI presentation."""

    code: str
    message: str


def check_repository(request: CheckRequest) -> CheckResult | CheckFailure:
    """Capture one repository view and classify its effective check result."""

    root = request.repo_root.resolve()
    markdown_parse_memo: MarkdownParseMemo = {}
    try:
        snapshot = obligation_runtime.capture_obligation_snapshot(
            root,
            request.profile,
            request.settings,
            markdown_parse_memo=markdown_parse_memo,
        )
    except SnapshotCaptureError as exc:
        return CheckFailure(code=exc.kind, message=str(exc))
    pipeline = check_pipeline.build_check_report_from_snapshot(
        snapshot,
        root.as_posix(),
        request.profile,
        request.settings,
        markdown_parse_memo=markdown_parse_memo,
    )
    fail_on = set(request.settings.diagnostics.fail_on)
    if request.settings.check.warnings_as_errors:
        fail_on.add("warning")
    return CheckResult(
        pipeline=pipeline,
        warnings=pipeline.warnings,
        blocks_gate=any(issue.severity in fail_on for issue in pipeline.report.issues),
    )
