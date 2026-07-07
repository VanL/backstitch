"""Traceability exclusion and suppression engine.

Spec: docs/specs/04-backstitch-traceability-exclusions.md [EXC-1], [EXC-2],
[EXC-3], [EXC-4], [EXC-6], [EXC-8]
Spec: docs/specs/02-backstitch-core.md [SC-13]

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
from collections.abc import Iterator
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
# A line that opens with the underscore marker sigil, or contains a
# backstitch HTML comment ANYWHERE (HTML markers may trail headings), but
# matches neither valid form.
MALFORMED_MARKER_RE = re.compile(r"^_Traceability:", re.IGNORECASE)
MALFORMED_HTML_MARKER_RE = re.compile(r"<!--\s*backstitch:", re.IGNORECASE)
# The codes group may be EMPTY so `<!-- backstitch: ignore -->` still
# matches and is rejected as "ignore with no codes" rather than falling
# through unrecognized (where a trailing heading marker would silently
# delete the heading's section).
HTML_IGNORE_RE = re.compile(
    r"<!--\s*backstitch:\s*ignore\b[ \t]*(.*?)\s*-->",
    re.IGNORECASE,
)
# Anchored on purpose: a directive line IS the directive ([EXC-5] grammar
# `backstitch:` then `noqa` then codes), so prose that merely mentions
# `backstitch: noqa` mid-sentence never parses, and everything after the
# marker on a directive line must be issue codes -- a silently dropped tail
# is the fake-protection class this spec exists to prevent.
NOQA_LINE_RE = re.compile(
    r"^backstitch:[ \t]*(?:noqa|ignore)\b[ \t]*(?P<rest>.*)$",
    re.IGNORECASE,
)
CODE_TOKEN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


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
    inline_code_span_ignores: dict[str, tuple[tuple[int, int, frozenset[str]], ...]] = (
        field(default_factory=dict)
    )
    # Sections carrying their own [EXC-4] marker: file-level inline markers
    # do not apply to them ("section markers override file-level markers").
    sections_with_markers: frozenset[tuple[str, str]] = frozenset()
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


def _parse_ignore_codes(
    raw: str, *, allow_unknown: bool, location: str
) -> tuple[bool, frozenset[str], list[str]]:
    codes, warnings = parse_traceability_codes(
        raw, allow_unknown=allow_unknown, location=location
    )
    if not codes and not warnings:
        # [EXC-4]: an ignore marker with no codes (`_Traceability: ignore_`,
        # `<!-- backstitch: ignore -->`) is malformed -- fake protection,
        # same strictness and hatch as an unknown code.
        message = f"malformed traceability marker in {location}: ignore with no codes"
        if not allow_unknown:
            raise UnknownSuppressionCodeError(message)
        return False, frozenset(), [message]
    return False, codes, warnings


def parse_traceability_marker_line(
    line: str, *, allow_unknown: bool = False, location: str = "inline marker"
) -> tuple[bool, frozenset[str], list[str]]:
    stripped = line.strip()
    if TRACEABILITY_META_RE.match(stripped):
        return True, META_DEFAULT_SUPPRESSED, []
    match = TRACEABILITY_IGNORE_RE.match(stripped)
    if match:
        return _parse_ignore_codes(
            match.group(1), allow_unknown=allow_unknown, location=location
        )
    if HTML_META_RE.search(stripped):
        return True, META_DEFAULT_SUPPRESSED, []
    match = HTML_IGNORE_RE.search(stripped)
    if match:
        return _parse_ignore_codes(
            match.group(1), allow_unknown=allow_unknown, location=location
        )
    # [EXC-4]: a line that STARTS like a marker but parses as neither form
    # (`_Traceability: ignore_` with no codes, `_Traceability: bogus_`) is
    # a malformed suppression -- the same fake affordance as an unknown
    # code, with the same strictness and hatch.
    if MALFORMED_MARKER_RE.match(stripped) or MALFORMED_HTML_MARKER_RE.search(stripped):
        message = f"malformed traceability marker in {location}: {stripped!r}"
        if not allow_unknown:
            raise UnknownSuppressionCodeError(message)
        return False, frozenset(), [message]
    return False, frozenset(), []


def parse_noqa_text(
    text: str, *, allow_unknown: bool = False, location: str = "inline noqa"
) -> tuple[frozenset[str], list[str]]:
    """Parse ``backstitch: noqa`` directives; returns (codes, warnings).

    Only lines that START with the marker are directives ([EXC-5] grammar).
    Malformed directives (no codes, or unparseable tokens) always warn;
    unknown codes follow [EXC-4] strictness -- error by default,
    ``allow_unknown`` downgrades to warnings. All warnings must reach
    stderr -- a discarded warning makes typo suppressions silent.
    """

    codes: set[str] = set()
    warnings: list[str] = []
    for raw_line in text.splitlines():
        match = NOQA_LINE_RE.match(raw_line.strip())
        if match is None:
            continue
        rest = match.group("rest").strip()
        if not rest:
            warnings.append(
                f"malformed `backstitch: noqa` directive in {location}: no issue codes"
            )
            continue
        tokens = [t for t in re.split(r"[,\s]+", rest) if t]
        bad = sorted({t for t in tokens if not CODE_TOKEN_RE.match(t)})
        if bad:
            warnings.append(
                f"malformed `backstitch: noqa` directive in {location}:"
                f" unparseable token(s) {', '.join(bad)}"
                " -- codes are comma-separated issue codes"
            )
        idents = ",".join(t for t in tokens if CODE_TOKEN_RE.match(t))
        parsed, parse_warnings = parse_traceability_codes(
            idents, allow_unknown=allow_unknown, location=location
        )
        codes.update(parsed)
        warnings.extend(parse_warnings)
    return frozenset(codes), warnings


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
    if section_id is not None and index.section_meta.get(
        (spec_file, section_id), False
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


def _match_config_ignore_attempts(
    issue: Issue,
    index: SuppressionIndex,
    *,
    spec_file: str | None,
    section_id: str | None,
    code_file: str | None,
) -> tuple[str | None, str | None]:
    file_rule = _match_per_file_ignore(
        spec_file or code_file or issue.path,
        issue.code,
        index.lint.per_file_ignores,
    )
    section_rule = _match_per_section_ignore(
        spec_file,
        section_id,
        issue.code,
        index.lint.per_section_ignores,
    )
    return file_rule, section_rule


def should_suppress(
    issue: Issue,
    index: SuppressionIndex,
    *,
    spec_file: str | None = None,
    section_id: str | None = None,
    code_file: str | None = None,
) -> tuple[bool, SuppressionReason | None]:
    resolved_spec_file = spec_file or (
        issue.path if issue.path and issue.path.endswith(".md") else None
    )
    resolved_section_id = section_id or issue.section_id
    resolved_code_file = code_file or (
        issue.path if issue.path and issue.path.endswith(".py") else None
    )
    file_rule, section_rule = _match_config_ignore_attempts(
        issue,
        index,
        spec_file=resolved_spec_file,
        section_id=resolved_section_id,
        code_file=resolved_code_file,
    )

    if _is_non_suppressible(issue):
        index.record_config_usage(file_rule=file_rule, section_rule=section_rule)
        _warn_error_code_suppression(
            issue,
            index,
            file_rule=file_rule,
            section_rule=section_rule,
        )
        return False, None

    suppressed = False
    reason: SuppressionReason | None = None

    if _section_is_meta(resolved_spec_file, resolved_section_id, index):
        if _meta_suppresses(issue, code_file=resolved_code_file):
            suppressed = True
            reason = SuppressionReason.META

    if file_rule is not None:
        suppressed = True
        reason = SuppressionReason.CONFIG_FILE
        index.record_config_usage(file_rule=file_rule, section_rule=None)

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

    if resolved_spec_file and (
        resolved_section_id is None
        or (resolved_spec_file, resolved_section_id) not in index.sections_with_markers
    ):
        # EXC-4.1: file-level markers apply "unless a section overrides
        # it" -- a section with its own marker opts out of file-level
        # inline ignores entirely.
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
    inline_code_span_ignores: dict[str, tuple[tuple[int, int, frozenset[str]], ...]]
    | None = None,
    sections_with_markers: frozenset[tuple[str, str]] = frozenset(),
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
        sections_with_markers=sections_with_markers,
    )
    if marker_warnings:
        index.suppression_warnings.extend(marker_warnings)
    _validate_config_codes(index, allow_unknown=allow_unknown)
    _warn_inline_error_code_attempts(index)
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


def validate_lint_codes(lint: LintSettings, *, allow_unknown: bool) -> list[str]:
    """Validate suppression codes in config lint tables ([EXC-4]).

    Raises ``UnknownSuppressionCodeError`` by default; ``allow_unknown``
    downgrades unknown codes to returned warnings. Shared by the check
    pipeline and `config show` so both apply the same load strictness.
    """

    warnings: list[str] = []
    for table_name, table in (
        ("lint.per-file-ignores", lint.per_file_ignores),
        ("lint.per-section-ignores", lint.per_section_ignores),
    ):
        for path_key, codes in table.items():
            for code in codes:
                if code not in ISSUE_CODES:
                    # [EXC-4]: unknown suppression codes fail load by
                    # default -- same hatch, same scope as [CFG-8].
                    message = (
                        f"unknown issue code `{code}` in {table_name} for {path_key}"
                    )
                    if not allow_unknown:
                        raise UnknownSuppressionCodeError(message)
                    warnings.append(message)
                elif code in ERROR_SEVERITY_CODES:
                    warnings.append(
                        f"cannot suppress error-severity code {code} in {table_name}"
                    )
    return warnings


def _validate_config_codes(index: SuppressionIndex, *, allow_unknown: bool) -> None:
    index.suppression_warnings.extend(
        validate_lint_codes(index.lint, allow_unknown=allow_unknown)
    )


def _iter_inline_ignore_code_sets(
    index: SuppressionIndex,
) -> Iterator[tuple[str, frozenset[str]]]:
    for path, codes in index.inline_file_ignores.items():
        yield path, codes
    for (spec_path, section_id), codes in index.inline_spec_ignores.items():
        yield f"{spec_path}::{section_id}", codes
    for path, codes in index.inline_code_ignores.items():
        yield path, codes
    # [EXC-5]/[EXC-8]: statement-scoped Python noqa spans are suppression
    # attempts too -- an error-severity code in a span must warn, not be
    # silently ignored.
    for path, spans in index.inline_code_span_ignores.items():
        for start, _end, codes in spans:
            yield f"{path}:{start}", codes


def _warn_inline_error_code_attempts(index: SuppressionIndex) -> None:
    """[EXC-8]: warn on EVERY inline attempt to suppress an always-error
    code, whether or not a matching finding was emitted this run -- a stale
    directive that only warns when the error fires is silent exactly when
    the author believes it works."""

    for location, codes in _iter_inline_ignore_code_sets(index):
        for code in sorted(codes & ERROR_SEVERITY_CODES):
            index.suppression_warnings.append(
                f"cannot suppress error-severity code {code} in inline"
                f" marker at {location}"
            )


def _warn_error_code_suppression(
    issue: Issue,
    index: SuppressionIndex,
    *,
    file_rule: str | None = None,
    section_rule: str | None = None,
) -> None:
    # Always-error codes already warned unconditionally at index build
    # (_warn_inline_error_code_attempts); this per-issue path covers the
    # context-dependent codes whose severity is only known per instance.
    if issue.code in ERROR_SEVERITY_CODES:
        return
    if file_rule is not None:
        index.suppression_warnings.append(
            f"suppression ignored for error-severity code {issue.code}"
            f" in lint.per-file-ignores rule {file_rule}"
        )
    if section_rule is not None:
        index.suppression_warnings.append(
            f"suppression ignored for error-severity code {issue.code}"
            f" in lint.per-section-ignores rule {section_rule}"
        )
    for _location, codes in _iter_inline_ignore_code_sets(index):
        if issue.code in codes:
            index.suppression_warnings.append(
                f"suppression ignored for error-severity code {issue.code}"
            )
            return
