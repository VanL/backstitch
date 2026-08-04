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
    collect_unused_ignore_diagnostics,
    parse_noqa_directives,
    parse_noqa_text,
    parse_traceability_directive_line,
    parse_traceability_marker_line,
    should_suppress,
)
from backstitch.models import (
    Issue,
    SuppressionDeclaration,
    SuppressionOrigin,
    SuppressionRule,
)
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


def test_inline_forms_preserve_valid_declaration_references() -> None:
    reference = "docs/specs/04-backstitch-traceability-exclusions.md#SUP-INLINE"
    directive, diagnostics = parse_traceability_directive_line(
        f"_Traceability: ignore BSS007 because {reference}_"
    )
    assert diagnostics == []
    assert directive is not None
    assert directive.codes == frozenset({"SPEC_SECTION_UNMAPPED"})
    assert directive.declaration == reference

    noqa, diagnostics = parse_noqa_directives(
        f"backstitch: noqa BSC003 because {reference}",
        line=7,
    )
    assert diagnostics == []
    assert noqa[0].codes == frozenset({"SPEC_MAPPING_RECIPROCAL_MISSING"})
    assert noqa[0].declaration == reference
    assert noqa[0].line == 7


@pytest.mark.parametrize(
    "marker",
    (
        "_Traceability: meta because docs/specs/01-x.md#SUP-X_",
        "<!-- backstitch: meta because docs/specs/01-x.md#SUP-X -->",
    ),
)
def test_meta_forms_preserve_valid_declaration_references(marker: str) -> None:
    directive, diagnostics = parse_traceability_directive_line(marker)

    assert diagnostics == []
    assert directive is not None
    assert directive.mechanism == "meta"
    assert directive.declaration == "docs/specs/01-x.md#SUP-X"


def test_clause_bearing_inline_form_rejects_invalid_reference_under_hatch() -> None:
    directive, diagnostics = parse_traceability_directive_line(
        "_Traceability: ignore BSS007 because ../outside.md#SUP-X_",
        allow_unknown=True,
    )
    assert directive is None
    assert [item.code for item in diagnostics] == ["SUPPRESSION_INVALID_SYNTAX"]


def test_clause_free_legacy_underscore_marker_remains_optional() -> None:
    assert parse_traceability_marker_line("_Traceability: meta") == (
        True,
        frozenset({"SPEC_SECTION_UNMAPPED"}),
        [],
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


def test_test_only_mapping_warning_is_ordinary_suppressible_policy() -> None:
    index = build_suppression_index(
        meta_spec_globs=(),
        lint=LintSettings(
            per_section_ignores={"docs/specs/01-x.md::X-1": ("SPEC_MAPPING_TEST_ONLY",)}
        ),
    )

    suppressed, reason = should_suppress(
        _issue("SPEC_MAPPING_TEST_ONLY", severity="warning"),
        index,
    )

    assert suppressed
    assert reason is SuppressionReason.CONFIG_SECTION


def test_legacy_meta_and_inline_rules_do_not_gain_unused_diagnostics() -> None:
    index = build_suppression_index(
        meta_spec_globs=("docs/specs/*.md",),
        lint=LintSettings(),
        inline_spec_ignores={
            ("docs/specs/01-x.md", "X-1"): frozenset({"SPEC_SECTION_UNMAPPED"})
        },
        inline_code_ignores={"pkg/x.py": frozenset({"CODE_REF_UNMAPPED_FROM_SPEC"})},
    )

    assert collect_unused_ignore_diagnostics(index) == []


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
            per_section_ignores={"docs/specs/01-x.md::X-1": ("SPEC_SECTION_UNMAPPED",)}
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
        lint=LintSettings(per_file_ignores={"docs/specs/*": ("MAPPING_PATH_MISSING",)}),
    )
    warning_instance = _issue("MAPPING_PATH_MISSING", severity="warning")
    suppressed, _ = should_suppress(warning_instance, index)
    assert suppressed
    error_instance = _issue("MAPPING_PATH_MISSING", severity="error")
    suppressed, _ = should_suppress(error_instance, index)
    assert not suppressed


def test_context_dependent_error_config_file_attempt_warns_and_records_usage() -> None:
    # [EXC-8]: config attempts to suppress a context-dependent error instance
    # are ignored, but they are still auditable and count as matched config
    # rules rather than stale ignores.
    index = build_suppression_index(
        meta_spec_globs=(),
        lint=LintSettings(
            warn_unused_ignores=False,
            per_file_ignores={"pkg/*.py": ("SPEC_SECTION_AMBIGUOUS",)},
        ),
    )
    suppressed, reason = should_suppress(
        _issue("SPEC_SECTION_AMBIGUOUS", severity="error", path="pkg/mod.py"),
        index,
    )
    assert not suppressed and reason is None
    assert index.used_config_file_rules == {"pkg/*.py"}
    assert any(
        "suppression ignored for non-suppressible code SPEC_SECTION_AMBIGUOUS"
        in diagnostic.message
        for diagnostic in index.suppression_diagnostics
    )
    assert collect_unused_ignore_diagnostics(index) == []


def test_context_dependent_error_config_section_attempt_warns() -> None:
    index = build_suppression_index(
        meta_spec_globs=(),
        lint=LintSettings(
            warn_unused_ignores=False,
            per_section_ignores={"docs/specs/a.md::MAP-1": ("MAPPING_PATH_MISSING",)},
        ),
    )
    suppressed, reason = should_suppress(
        _issue(
            "MAPPING_PATH_MISSING",
            severity="error",
            path="docs/specs/a.md",
            section_id="MAP-1",
        ),
        index,
    )
    assert not suppressed and reason is None
    assert index.used_config_section_rules == {"docs/specs/a.md::MAP-1"}
    assert any(
        "suppression ignored for non-suppressible code MAPPING_PATH_MISSING"
        in diagnostic.message
        for diagnostic in index.suppression_diagnostics
    )
    assert collect_unused_ignore_diagnostics(index) == []


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


def test_reserved_obligation_skip_is_not_an_ordinary_suppression() -> None:
    assert parse_traceability_marker_line(
        '<!-- backstitch: skip-obligation [X-1] "Reason." -->'
    ) == (False, frozenset(), [])
    assert parse_traceability_marker_line(
        '_Traceability: skip-obligation [X-1] "Reason."_'
    ) == (False, frozenset(), [])


def test_reserved_suppression_code_in_inline_marker_raises() -> None:
    with pytest.raises(UnknownSuppressionCodeError) as excinfo:
        parse_traceability_marker_line(
            "_Traceability: ignore CONFIG_TOML_INVALID_",
            location="docs/specs/01-x.md:3",
        )
    assert "CONFIG_TOML_INVALID" in str(excinfo.value)


def test_reserved_suppression_code_in_config_raises() -> None:
    with pytest.raises(UnknownSuppressionCodeError) as excinfo:
        build_suppression_index(
            meta_spec_globs=(),
            lint=LintSettings(
                per_file_ignores={"docs/specs/*": ("CONFIG_TOML_INVALID",)}
            ),
        )
    assert "CONFIG_TOML_INVALID" in str(excinfo.value)


def test_allow_unknown_downgrades_unknown_suppression_code() -> None:
    index = build_suppression_index(
        meta_spec_globs=(),
        lint=LintSettings(per_file_ignores={"docs/specs/*": ("SPEC_SECTON_UNMAPPED",)}),
        allow_unknown=True,
    )
    assert [diagnostic.code for diagnostic in index.suppression_diagnostics] == [
        "SUPPRESSION_UNKNOWN_CODE"
    ]
    assert "SPEC_SECTON_UNMAPPED" in index.suppression_diagnostics[0].message


def test_unknown_code_in_structured_suppression_raises() -> None:
    with pytest.raises(UnknownSuppressionCodeError, match="SPEC_SECTON_UNMAPPED"):
        build_suppression_index(
            meta_spec_globs=(),
            lint=LintSettings(
                suppressions=(
                    SuppressionRule(
                        mechanism="ignore",
                        provenance="config_file",
                        path="docs/specs/*.md",
                        sections=(),
                        codes=("SPEC_SECTON_UNMAPPED",),
                        declaration=None,
                        origin=SuppressionOrigin(
                            source=".backstitch.toml",
                            position=0,
                        ),
                    ),
                )
            ),
        )


def test_non_suppressible_code_in_config_warns_when_matching_issue() -> None:
    index = build_suppression_index(
        meta_spec_globs=(),
        lint=LintSettings(per_file_ignores={"docs/specs/*": ("SPEC_FILE_MISSING",)}),
    )
    suppressed, _ = should_suppress(
        _issue("SPEC_FILE_MISSING", severity="error"), index
    )
    assert not suppressed
    assert any(
        "suppression ignored for non-suppressible code SPEC_FILE_MISSING"
        in diagnostic.message
        for diagnostic in index.suppression_diagnostics
    )


def test_unused_ignores_warn_when_enabled() -> None:
    index = build_suppression_index(
        meta_spec_globs=(),
        lint=LintSettings(
            per_file_ignores={"docs/specs/99-*.md": ("SPEC_SECTION_UNMAPPED",)}
        ),
    )
    diagnostics = collect_unused_ignore_diagnostics(index)
    assert [diagnostic.code for diagnostic in diagnostics] == ["SUPPRESSION_UNUSED"]
    assert diagnostics[0].path == "docs/specs/99-*.md"
    quiet = build_suppression_index(
        meta_spec_globs=(),
        lint=LintSettings(
            warn_unused_ignores=False,
            per_file_ignores={"docs/specs/99-*.md": ("SPEC_SECTION_UNMAPPED",)},
        ),
    )
    assert collect_unused_ignore_diagnostics(quiet) == []


def test_unused_documented_rule_and_unreferenced_declaration_both_warn() -> None:
    reference = "docs/specs/01-x.md#SUP-X"
    declaration = SuppressionDeclaration(
        declaration_id="SUP-X",
        reference=reference,
        rationale="The generated section has no implementation.",
        path="docs/specs/01-x.md",
        owner_section_id="X-1",
        owner_title="X",
        start_line=4,
        end_line=4,
    )
    unreferenced = build_suppression_index(
        meta_spec_globs=(),
        lint=LintSettings(),
        declarations=(declaration,),
    )
    assert [
        diagnostic.message
        for diagnostic in collect_unused_ignore_diagnostics(unreferenced)
    ] == [f"unreferenced suppression declaration: {reference}"]

    unused_rule = build_suppression_index(
        meta_spec_globs=(),
        lint=LintSettings(
            suppressions=(
                SuppressionRule(
                    mechanism="ignore",
                    provenance="config_file",
                    path="docs/specs/99-*.md",
                    sections=(),
                    codes=("SPEC_SECTION_UNMAPPED",),
                    declaration=reference,
                    origin=SuppressionOrigin(
                        source=".backstitch.toml",
                        position=0,
                    ),
                ),
            )
        ),
        declarations=(declaration,),
    )
    assert [
        diagnostic.message
        for diagnostic in collect_unused_ignore_diagnostics(unused_rule)
    ] == ["unused suppression rule: docs/specs/99-*.md"]


def test_noqa_parsing_accepts_alias_and_comma_lists() -> None:
    codes, warnings = parse_noqa_text(
        "backstitch: noqa SPEC_SECTION_UNMAPPED, CODE_REF_BROAD"
    )
    assert codes == frozenset({"SPEC_SECTION_UNMAPPED", "CODE_REF_BROAD"})
    assert warnings == []
    codes, warnings = parse_noqa_text("backstitch: ignore CODE_REF_BROAD")
    assert codes == frozenset({"CODE_REF_BROAD"})
    assert warnings == []
    assert parse_noqa_text("nothing here") == (frozenset(), [])


def test_short_suppression_codes_canonicalize_to_long_codes() -> None:
    codes, warnings = parse_noqa_text("backstitch: noqa BSC005")
    assert codes == frozenset({"CODE_REF_BROAD"})
    assert warnings == []
    index = build_suppression_index(
        meta_spec_globs=(),
        lint=LintSettings(per_file_ignores={"pkg/*.py": ("BSC005",)}),
    )
    suppressed, reason = should_suppress(
        _issue("CODE_REF_BROAD", severity="warning", path="pkg/mod.py"),
        index,
    )
    assert suppressed and reason is SuppressionReason.CONFIG_FILE
