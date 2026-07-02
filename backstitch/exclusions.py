"""Traceability exclusion and suppression engine.

Spec: docs/specs/04-backstitch-traceability-exclusions.md [EXC-1], [EXC-2],
[EXC-3], [EXC-4], [EXC-6], [EXC-8]

Suppression is auditable by contract: a suppressed finding moves to the
report's ``suppressed_issues`` with a reason, it never silently disappears
from every view. Non-suppressibility gates on the ISSUE INSTANCE severity
(``issue.severity == "error"``), never on bare code membership, because
[SC-11] has context-dependent codes whose warning-context instances must
stay suppressible.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from enum import StrEnum

from backstitch.models import ERROR_SEVERITY_CODES, ISSUE_CODES, Issue
from backstitch.settings import LintSettings

META_DEFAULT_SUPPRESSED: frozenset[str] = frozenset({"SPEC_SECTION_UNMAPPED"})

TRACEABILITY_META_RE = re.compile(r"^_Traceability:\s*meta_?\s*$", re.IGNORECASE)
TRACEABILITY_IGNORE_RE = re.compile(
    r"^_Traceability:\s*ignore\s+(.+?)_?\s*$",
    re.IGNORECASE,
)
HTML_META_RE = re.compile(r"<!--\s*backstitch:\s*meta\s*-->", re.IGNORECASE)
HTML_IGNORE_RE = re.compile(
    r"<!--\s*backstitch:\s*ignore\s+(.+?)\s*-->",
    re.IGNORECASE,
)
NOQA_RE = re.compile(
    r"backstitch:\s*(?:noqa|ignore)\s+([\w_,\s]+)",
    re.IGNORECASE,
)


class UnknownSuppressionCodeError(ValueError):
    """A suppression names an issue code that does not exist ([EXC-4]).

    The same fake affordance as a typo'd config key: it looks like
    protection and does nothing. Exit 2 by default; ``allow_unknown_keys``
    downgrades to warnings.
    """


class SuppressionReason(StrEnum):
    META = "meta"
    CONFIG_FILE = "config_file"
    CONFIG_SECTION = "config_section"
    INLINE_SPEC = "inline_spec"
    INLINE_CODE = "inline_code"


@dataclass(frozen=True, slots=True)
class SuppressedIssue:
    issue: Issue
    reason: SuppressionReason


@dataclass
class SuppressionIndex:
    meta_spec_globs: tuple[str, ...] = ()
    lint: LintSettings = field(default_factory=LintSettings)
    section_meta: dict[tuple[str, str], bool] = field(default_factory=dict)
    inline_spec_ignores: dict[tuple[str, str], frozenset[str]] = field(
        default_factory=dict
    )
    inline_file_ignores: dict[str, frozenset[str]] = field(default_factory=dict)
    inline_code_ignores: dict[str, frozenset[str]] = field(default_factory=dict)
    inline_code_span_ignores: dict[
        str, tuple[tuple[int, int, frozenset[str]], ...]
    ] = field(default_factory=dict)
    used_config_file_rules: set[str] = field(default_factory=set)
    used_config_section_rules: set[str] = field(default_factory=set)
    suppression_warnings: list[str] = field(default_factory=list)

    def record_config_usage(
        self, *, file_rule: str | None, section_rule: str | None
    ) -> None:
        if file_rule is not None:
            self.used_config_file_rules.add(file_rule)
        if section_rule is not None:
            self.used_config_section_rules.add(section_rule)


def parse_traceability_codes(
    raw: str, *, allow_unknown: bool = False, location: str = "inline marker"
) -> tuple[frozenset[str], list[str]]:
    """Split a comma list of issue codes, enforcing [EXC-4] strictness.

    Unknown codes raise ``UnknownSuppressionCodeError`` naming the code and
    location; ``allow_unknown`` downgrades them to returned warnings (the
    [CFG-8] hatch, same scope, same semantics).
    """

    codes: set[str] = set()
    warnings: list[str] = []
    for part in raw.split(","):
        code = part.strip()
        if not code:
            continue
        if code not in ISSUE_CODES:
            message = f"unknown issue code `{code}` in {location}"
            if not allow_unknown:
                raise UnknownSuppressionCodeError(message)
            warnings.append(message)
            continue
        codes.add(code)
    return frozenset(codes), warnings


def parse_traceability_marker_line(
    line: str, *, allow_unknown: bool = False, location: str = "inline marker"
) -> tuple[bool, frozenset[str], list[str]]:
    stripped = line.strip()
    if TRACEABILITY_META_RE.match(stripped):
        return True, META_DEFAULT_SUPPRESSED, []
    match = TRACEABILITY_IGNORE_RE.match(stripped)
    if match:
        codes, warnings = parse_traceability_codes(
            match.group(1), allow_unknown=allow_unknown, location=location
        )
        return False, codes, warnings
    if HTML_META_RE.search(stripped):
        return True, META_DEFAULT_SUPPRESSED, []
    match = HTML_IGNORE_RE.search(stripped)
    if match:
        codes, warnings = parse_traceability_codes(
            match.group(1), allow_unknown=allow_unknown, location=location
        )
        return False, codes, warnings
    return False, frozenset(), []


def parse_noqa_text(
    text: str, *, allow_unknown: bool = False, location: str = "inline noqa"
) -> frozenset[str]:
    codes: set[str] = set()
    for match in NOQA_RE.finditer(text):
        parsed, _ = parse_traceability_codes(
            match.group(1), allow_unknown=allow_unknown, location=location
        )
        codes.update(parsed)
    return frozenset(codes)


def _is_non_suppressible(issue: Issue) -> bool:
    # Per-instance severity is the gate: [SC-11]'s context-dependent codes
    # (SPEC_SECTION_AMBIGUOUS, MAPPING_PATH_MISSING) are errors only when
    # this instance is an error. ERROR_SEVERITY_CODES members are always
    # errors, so the severity check alone is sufficient and authoritative.
    return issue.severity == "error"


def _path_matches_glob(path: str, pattern: str) -> bool:
    return fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(path, f"**/{pattern}")


def _file_is_meta(path: str | None, index: SuppressionIndex) -> bool:
    if path is None:
        return False
    return any(_path_matches_glob(path, glob) for glob in index.meta_spec_globs)


def _section_is_meta(
    spec_file: str | None,
    section_id: str | None,
    index: SuppressionIndex,
) -> bool:
    if spec_file is None:
        return False
    if (
        section_id is not None
        and index.section_meta.get((spec_file, section_id), False)
    ):
        return True
    return _file_is_meta(spec_file, index)


def _meta_suppresses(issue: Issue, *, code_file: str | None) -> bool:
    if issue.code in META_DEFAULT_SUPPRESSED:
        return True
    if issue.code == "CODE_BACKLINK_RECIPROCAL_MISSING":
        target = code_file or issue.path
        if target is not None and not target.endswith(".py"):
            return True
    return False


def _match_per_file_ignore(
    path: str | None,
    issue_code: str,
    ignores: dict[str, tuple[str, ...]],
) -> str | None:
    if path is None:
        return None
    for pattern, codes in ignores.items():
        if issue_code not in codes:
            continue
        if _path_matches_glob(path, pattern) or path == pattern:
            return pattern
    return None


def _match_per_section_ignore(
    spec_file: str | None,
    section_id: str | None,
    issue_code: str,
    ignores: dict[str, tuple[str, ...]],
) -> str | None:
    if spec_file is None:
        return None
    candidates: list[str] = []
    if section_id is not None:
        candidates.append(f"{spec_file}::{section_id}")
    candidates.append(f"{spec_file}::*")
    for key in candidates:
        codes = ignores.get(key)
        if codes is not None and issue_code in codes:
            return key
    for pattern, codes in ignores.items():
        if issue_code not in codes:
            continue
        if "::" not in pattern:
            continue
        file_pattern, section_pattern = pattern.split("::", 1)
        if (
            not _path_matches_glob(spec_file, file_pattern)
            and spec_file != file_pattern
        ):
            continue
        if section_pattern == "*" or section_pattern == section_id:
            return pattern
    return None


def should_suppress(
    issue: Issue,
    index: SuppressionIndex,
    *,
    spec_file: str | None = None,
    section_id: str | None = None,
    code_file: str | None = None,
) -> tuple[bool, SuppressionReason | None]:
    if _is_non_suppressible(issue):
        _warn_error_code_suppression(issue, index)
        return False, None

    resolved_spec_file = spec_file or (
        issue.path if issue.path and issue.path.endswith(".md") else None
    )
    resolved_section_id = section_id or issue.section_id
    resolved_code_file = code_file or (
        issue.path if issue.path and issue.path.endswith(".py") else None
    )

    suppressed = False
    reason: SuppressionReason | None = None

    if _section_is_meta(resolved_spec_file, resolved_section_id, index):
        if _meta_suppresses(issue, code_file=resolved_code_file):
            suppressed = True
            reason = SuppressionReason.META

    file_rule = _match_per_file_ignore(
        resolved_spec_file or resolved_code_file or issue.path,
        issue.code,
        index.lint.per_file_ignores,
    )
    if file_rule is not None:
        suppressed = True
        reason = SuppressionReason.CONFIG_FILE
        index.record_config_usage(file_rule=file_rule, section_rule=None)

    section_rule = _match_per_section_ignore(
        resolved_spec_file,
        resolved_section_id,
        issue.code,
        index.lint.per_section_ignores,
    )
    if section_rule is not None:
        suppressed = True
        reason = SuppressionReason.CONFIG_SECTION
        index.record_config_usage(file_rule=None, section_rule=section_rule)

    if resolved_spec_file and resolved_section_id:
        section_codes = index.inline_spec_ignores.get(
            (resolved_spec_file, resolved_section_id),
            frozenset(),
        )
        if issue.code in section_codes:
            suppressed = True
            reason = SuppressionReason.INLINE_SPEC

    if resolved_spec_file:
        file_codes = index.inline_file_ignores.get(resolved_spec_file, frozenset())
        if issue.code in file_codes:
            suppressed = True
            reason = SuppressionReason.INLINE_SPEC

    if resolved_code_file:
        code_codes = index.inline_code_ignores.get(resolved_code_file, frozenset())
        if issue.code in code_codes:
            suppressed = True
            reason = SuppressionReason.INLINE_CODE
        # [EXC-5] comment form: statement-scoped -- the issue's line must
        # fall inside the span the directive attached to.
        if issue.line is not None:
            for start, end, codes in index.inline_code_span_ignores.get(
                resolved_code_file, ()
            ):
                if start <= issue.line <= end and issue.code in codes:
                    suppressed = True
                    reason = SuppressionReason.INLINE_CODE
                    break

    return suppressed, reason


def build_suppression_index(
    *,
    meta_spec_globs: tuple[str, ...],
    lint: LintSettings,
    section_meta: dict[tuple[str, str], bool] | None = None,
    inline_file_ignores: dict[str, frozenset[str]] | None = None,
    inline_spec_ignores: dict[tuple[str, str], frozenset[str]] | None = None,
    inline_code_ignores: dict[str, frozenset[str]] | None = None,
    inline_code_span_ignores: dict[
        str, tuple[tuple[int, int, frozenset[str]], ...]
    ]
    | None = None,
    marker_warnings: list[str] | None = None,
    allow_unknown: bool = False,
) -> SuppressionIndex:
    index = SuppressionIndex(
        meta_spec_globs=meta_spec_globs,
        lint=lint,
        section_meta=dict(section_meta or {}),
        inline_spec_ignores=dict(inline_spec_ignores or {}),
        inline_file_ignores=dict(inline_file_ignores or {}),
        inline_code_ignores=dict(inline_code_ignores or {}),
        inline_code_span_ignores=dict(inline_code_span_ignores or {}),
    )
    if marker_warnings:
        index.suppression_warnings.extend(marker_warnings)
    _validate_config_codes(index, allow_unknown=allow_unknown)
    return index


def collect_unused_ignore_warnings(index: SuppressionIndex) -> list[str]:
    if not index.lint.warn_unused_ignores:
        return []
    warnings: list[str] = []
    for pattern in index.lint.per_file_ignores:
        if pattern not in index.used_config_file_rules:
            warnings.append(f"unused per-file-ignore: {pattern}")
    for pattern in index.lint.per_section_ignores:
        if pattern not in index.used_config_section_rules:
            warnings.append(f"unused per-section-ignore: {pattern}")
    return warnings


def _validate_config_codes(index: SuppressionIndex, *, allow_unknown: bool) -> None:
    for table_name, table in (
        ("lint.per-file-ignores", index.lint.per_file_ignores),
        ("lint.per-section-ignores", index.lint.per_section_ignores),
    ):
        for path_key, codes in table.items():
            for code in codes:
                if code not in ISSUE_CODES:
                    # [EXC-4]: unknown suppression codes fail load by
                    # default -- same hatch, same scope as [CFG-8].
                    message = (
                        f"unknown issue code `{code}` in {table_name}"
                        f" for {path_key}"
                    )
                    if not allow_unknown:
                        raise UnknownSuppressionCodeError(message)
                    index.suppression_warnings.append(message)
                elif code in ERROR_SEVERITY_CODES:
                    index.suppression_warnings.append(
                        f"cannot suppress error-severity code {code}"
                        f" in {table_name}"
                    )


def _warn_error_code_suppression(issue: Issue, index: SuppressionIndex) -> None:
    for source in (
        index.inline_file_ignores.values(),
        index.inline_spec_ignores.values(),
        index.inline_code_ignores.values(),
    ):
        for codes in source:
            if issue.code in codes:
                index.suppression_warnings.append(
                    f"suppression ignored for error-severity code {issue.code}"
                )
                return
