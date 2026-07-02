"""Suppression engine contract: precedence, strict codes, severity gating.

Spec: docs/specs/04-backstitch-traceability-exclusions.md [EXC-3]-[EXC-6],
[EXC-8], [EXC-9]
"""

from __future__ import annotations

import pytest

from backstitch.exclusions import (
    SuppressionReason,
    UnknownSuppressionCodeError,
    build_suppression_index,
    collect_unused_ignore_warnings,
    parse_noqa_text,
    parse_traceability_marker_line,
    should_suppress,
)
from backstitch.models import Issue
from backstitch.settings import LintSettings


def _issue(
    code: str,
    *,
    severity: str = "info",
    path: str = "docs/specs/01-x.md",
    section_id: str | None = "X-1",
) -> Issue:
    return Issue(
        code=code,
        severity=severity,  # type: ignore[arg-type]
        path=path,
        line=3,
        message=f"{code} occurred",
        section_id=section_id,
    )


def test_meta_glob_suppresses_unmapped_but_not_missing() -> None:
    index = build_suppression_index(
        meta_spec_globs=("docs/specs/01-*.md",),
        lint=LintSettings(),
    )
    suppressed, reason = should_suppress(_issue("SPEC_SECTION_UNMAPPED"), index)
    assert suppressed and reason is SuppressionReason.META
    # Error-severity findings are never suppressed, meta or not.
    suppressed, reason = should_suppress(
        _issue("SPEC_SECTION_MISSING", severity="error"), index
    )
    assert not suppressed and reason is None


def test_inline_marker_beats_config_in_reported_reason() -> None:
    # EXC §6.2: inline wins over config so local intent beats central
    # config; both match here, the reason must say inline.
    index = build_suppression_index(
        meta_spec_globs=(),
        lint=LintSettings(
            per_file_ignores={"docs/specs/*": ("SPEC_SECTION_UNMAPPED",)}
        ),
        inline_spec_ignores={
            ("docs/specs/01-x.md", "X-1"): frozenset({"SPEC_SECTION_UNMAPPED"})
        },
    )
    suppressed, reason = should_suppress(_issue("SPEC_SECTION_UNMAPPED"), index)
    assert suppressed and reason is SuppressionReason.INLINE_SPEC


def test_per_section_ignore_suppresses_only_that_section() -> None:
    index = build_suppression_index(
        meta_spec_globs=(),
        lint=LintSettings(
            per_section_ignores={
                "docs/specs/01-x.md::X-1": ("SPEC_SECTION_UNMAPPED",)
            }
        ),
    )
    suppressed, _ = should_suppress(_issue("SPEC_SECTION_UNMAPPED"), index)
    assert suppressed
    other = _issue("SPEC_SECTION_UNMAPPED", section_id="X-2")
    suppressed, _ = should_suppress(other, index)
    assert not suppressed


def test_context_dependent_code_suppressibility_gates_on_instance_severity() -> None:
    # MAPPING_PATH_MISSING is error/warning by context ([SC-11]); only the
    # warning instance (a plan .md ref) is suppressible.
    index = build_suppression_index(
        meta_spec_globs=(),
        lint=LintSettings(
            per_file_ignores={"docs/specs/*": ("MAPPING_PATH_MISSING",)}
        ),
    )
    warning_instance = _issue("MAPPING_PATH_MISSING", severity="warning")
    suppressed, _ = should_suppress(warning_instance, index)
    assert suppressed
    error_instance = _issue("MAPPING_PATH_MISSING", severity="error")
    suppressed, _ = should_suppress(error_instance, index)
    assert not suppressed


def test_unknown_suppression_code_in_config_raises() -> None:
    with pytest.raises(UnknownSuppressionCodeError) as excinfo:
        build_suppression_index(
            meta_spec_globs=(),
            lint=LintSettings(
                per_file_ignores={"docs/specs/*": ("SPEC_SECTON_UNMAPPED",)}
            ),
        )
    assert "SPEC_SECTON_UNMAPPED" in str(excinfo.value)
    assert "per-file-ignores" in str(excinfo.value)


def test_unknown_suppression_code_in_inline_marker_raises() -> None:
    with pytest.raises(UnknownSuppressionCodeError) as excinfo:
        parse_traceability_marker_line(
            "_Traceability: ignore NOT_A_CODE_9_", location="docs/specs/01-x.md:3"
        )
    assert "NOT_A_CODE_9" in str(excinfo.value)
    assert "docs/specs/01-x.md:3" in str(excinfo.value)


def test_allow_unknown_downgrades_unknown_suppression_code() -> None:
    index = build_suppression_index(
        meta_spec_globs=(),
        lint=LintSettings(
            per_file_ignores={"docs/specs/*": ("SPEC_SECTON_UNMAPPED",)}
        ),
        allow_unknown=True,
    )
    assert any(
        "SPEC_SECTON_UNMAPPED" in warning
        for warning in index.suppression_warnings
    )


def test_error_severity_code_in_config_warns_and_does_not_suppress() -> None:
    index = build_suppression_index(
        meta_spec_globs=(),
        lint=LintSettings(
            per_file_ignores={"docs/specs/*": ("SPEC_FILE_MISSING",)}
        ),
    )
    assert any(
        "cannot suppress error-severity" in warning
        for warning in index.suppression_warnings
    )
    suppressed, _ = should_suppress(
        _issue("SPEC_FILE_MISSING", severity="error"), index
    )
    assert not suppressed


def test_unused_ignores_warn_when_enabled() -> None:
    index = build_suppression_index(
        meta_spec_globs=(),
        lint=LintSettings(
            per_file_ignores={"docs/specs/99-*.md": ("SPEC_SECTION_UNMAPPED",)}
        ),
    )
    warnings = collect_unused_ignore_warnings(index)
    assert warnings and "docs/specs/99-*.md" in warnings[0]
    quiet = build_suppression_index(
        meta_spec_globs=(),
        lint=LintSettings(
            warn_unused_ignores=False,
            per_file_ignores={"docs/specs/99-*.md": ("SPEC_SECTION_UNMAPPED",)},
        ),
    )
    assert collect_unused_ignore_warnings(quiet) == []


def test_noqa_parsing_accepts_alias_and_comma_lists() -> None:
    codes = parse_noqa_text(
        "backstitch: noqa SPEC_SECTION_UNMAPPED, CODE_REF_BROAD"
    )
    assert codes == frozenset({"SPEC_SECTION_UNMAPPED", "CODE_REF_BROAD"})
    codes = parse_noqa_text("backstitch: ignore CODE_REF_BROAD")
    assert codes == frozenset({"CODE_REF_BROAD"})
    assert parse_noqa_text("nothing here") == frozenset()
