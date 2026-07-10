"""Diagnostic registry and policy tests.

Spec: docs/specs/02-backstitch-core.md [SC-6], [SC-11], [SC-15]
Spec: docs/specs/03-backstitch-configuration.md [CFG-6], [CFG-8], [CFG-9]
"""

from __future__ import annotations

import pytest

from backstitch.diagnostics import (
    DiagnosticConfigError,
    DiagnosticLevelRule,
    DiagnosticsSettings,
    apply_policy_to_report,
    canonicalize_code,
    default_registry,
    parse_policy,
    parse_registry,
    resolve_level,
)
from backstitch.models import Issue, Report


def _report(issue: Issue) -> Report:
    return Report(
        profile="backstitch-style-v1",
        repo_root="/tmp/repo",
        spec_sections=(),
        code_refs=(),
        spec_mappings=(),
        edges=(),
        issues=(issue,),
    )


def test_default_registry_has_unique_short_codes() -> None:
    registry = default_registry()
    assert registry.require("SPEC_FILE_MISSING").short_code == "BSS001"
    assert registry.canonical_code("BSS001") == "SPEC_FILE_MISSING"
    assert "CONFIG_TOML_INVALID" not in registry.implemented_codes()


def test_registry_rejects_duplicate_short_codes() -> None:
    with pytest.raises(DiagnosticConfigError, match="duplicate short"):
        parse_registry(
            {
                "ONE": {
                    "short": "BST999",
                    "status": "implemented",
                    "summary": "one",
                },
                "TWO": {
                    "short": "BST999",
                    "status": "implemented",
                    "summary": "two",
                },
            },
            source="test",
        )


def test_registry_canonical_code_follows_replacement_chains_and_short_aliases() -> None:
    registry = parse_registry(
        {
            "CURRENT": {
                "short": "TST003",
                "status": "implemented",
                "summary": "current",
            },
            "MIDDLE": {
                "short": "TST002",
                "status": "redirected",
                "summary": "middle",
                "replacement": "CURRENT",
            },
            "OLD": {
                "short": "TST001",
                "status": "deprecated",
                "summary": "old",
                "replacement": "MIDDLE",
            },
        },
        source="test",
    )

    assert registry.canonical_code("OLD") == "CURRENT"
    assert registry.canonical_code("TST001") == "CURRENT"
    assert registry.canonical_code("MIDDLE") == "CURRENT"
    assert registry.canonical_code("TST002") == "CURRENT"


def test_registry_canonical_code_rejects_replacement_cycles() -> None:
    with pytest.raises(DiagnosticConfigError, match="replacement cycle"):
        parse_registry(
            {
                "ONE": {
                    "short": "TST001",
                    "status": "deprecated",
                    "summary": "one",
                    "replacement": "TWO",
                },
                "TWO": {
                    "short": "TST002",
                    "status": "redirected",
                    "summary": "two",
                    "replacement": "ONE",
                },
            },
            source="test",
        )


def test_registry_canonical_code_rejects_reserved_terminal() -> None:
    with pytest.raises(DiagnosticConfigError, match="status reserved"):
        parse_registry(
            {
                "OLD": {
                    "short": "TST001",
                    "status": "deprecated",
                    "summary": "old",
                    "replacement": "RESERVED",
                },
                "RESERVED": {
                    "short": "TST002",
                    "status": "reserved",
                    "summary": "reserved",
                },
            },
            source="test",
        )


def test_policy_selectors_match_long_short_family_and_context() -> None:
    policy = DiagnosticsSettings(
        default_level="warning",
        levels=(
            DiagnosticLevelRule(selectors=("BSS*",), level="info"),
            DiagnosticLevelRule(
                selectors=("SPEC_SECTION_AMBIGUOUS:asserted",),
                level="error",
            ),
        ),
    )
    assert resolve_level("SPEC_FILE_MISSING", context=None, policy=policy) == "info"
    assert (
        resolve_level("SPEC_SECTION_AMBIGUOUS", context="asserted", policy=policy)
        == "error"
    )
    assert (
        resolve_level("SPEC_SECTION_AMBIGUOUS", context="weak", policy=policy) == "info"
    )


def test_later_policy_rules_win_and_star_can_override_defaults() -> None:
    policy = parse_policy(
        {
            "default_level": "warning",
            "fail_on": [],
            "suppressible_levels": ["warning", "info"],
            "levels": [
                {"select": ["SPEC_FILE_MISSING"], "level": "error"},
                {"select": ["*"], "level": "info"},
            ],
        },
        source="test",
        allow_unknown=False,
    )
    assert resolve_level("SPEC_FILE_MISSING", context=None, policy=policy) == "info"


def test_policy_rejects_off_in_fail_on_and_reserved_selector() -> None:
    with pytest.raises(DiagnosticConfigError, match="fail_on"):
        parse_policy(
            {"fail_on": ["off"]},
            source="test",
            allow_unknown=False,
        )
    with pytest.raises(DiagnosticConfigError, match="unknown diagnostic selector"):
        parse_policy(
            {
                "levels": [
                    {"select": ["CONFIG_TOML_INVALID"], "level": "warning"},
                ]
            },
            source="test",
            allow_unknown=False,
        )


def test_policy_rejects_context_for_contextless_diagnostic() -> None:
    with pytest.raises(DiagnosticConfigError, match="unknown diagnostic context"):
        parse_policy(
            {
                "levels": [
                    {"select": ["SPEC_FILE_MISSING:any"], "level": "info"},
                ]
            },
            source="test",
            allow_unknown=False,
        )


@pytest.mark.parametrize("allow_unknown", [False, True])
def test_policy_rejects_context_on_wildcard_selector(allow_unknown: bool) -> None:
    with pytest.raises(DiagnosticConfigError, match="wildcard.*context"):
        parse_policy(
            {
                "levels": [
                    {"select": ["*:bogus"], "level": "info"},
                ]
            },
            source="test",
            allow_unknown=allow_unknown,
        )


def test_reserved_diagnostics_cannot_be_emitted() -> None:
    with pytest.raises(DiagnosticConfigError, match="only implemented"):
        Issue(
            code="CONFIG_TOML_INVALID",
            severity="warning",
            path="pyproject.toml",
            line=1,
            message="bad config",
        )


def test_policy_application_preserves_default_severity_and_audits_off() -> None:
    issue = Issue(
        code="PYTHON_SYNTAX_ERROR",
        severity="warning",
        path="pkg/bad.py",
        line=1,
        message="bad",
    )
    policy = DiagnosticsSettings(
        default_level="warning",
        levels=(DiagnosticLevelRule(selectors=("PYTHON_SYNTAX_ERROR",), level="off"),),
        fail_on=(),
    )
    report, off_records = apply_policy_to_report(
        _report(issue),
        effective_policy=policy,
    )
    assert report.issues == ()
    assert len(off_records) == 1
    off_issue, reason = off_records[0]
    assert off_issue.code == "PYTHON_SYNTAX_ERROR"
    assert off_issue.default_severity == "warning"
    assert reason == "diagnostic level off"


def test_short_code_canonicalization() -> None:
    assert canonicalize_code("BSC001") == "PYTHON_SYNTAX_ERROR"
