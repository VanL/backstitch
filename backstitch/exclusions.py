"""Traceability exclusion and suppression engine.

Spec: docs/specs/04-backstitch-traceability-exclusions.md [EXC-1], [EXC-2],
[EXC-3], [EXC-4], [EXC-6], [EXC-8]
Spec: docs/specs/02-backstitch-core.md [SC-13]

Suppression is auditable by contract: a suppressed finding moves to the
report's ``suppressed_issues`` with a reason, it never silently disappears
from every view. Non-suppressibility gates on the ISSUE INSTANCE severity
(``issue.severity == "error"``), never on bare code membership, because
diagnostic codes can have context-dependent severity.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from enum import StrEnum

from backstitch.canonical import lf_split
from backstitch.diagnostics import canonicalize_code, is_ordinary_diagnostic_code
from backstitch.grammar import is_valid_suppression_reference
from backstitch.models import (
    Issue,
    Severity,
    SuppressionDecision,
    SuppressionDeclaration,
    SuppressionOrigin,
    SuppressionRule,
)
from backstitch.settings import LintSettings

META_DEFAULT_SUPPRESSED: frozenset[str] = frozenset({"SPEC_SECTION_UNMAPPED"})

TRACEABILITY_DIRECTIVE_RE = re.compile(
    r"^_Traceability:\s*(?P<mechanism>meta|ignore)"
    r"(?:\s+(?P<body>.*?))?(?P<close>_?)\s*$",
    re.IGNORECASE,
)
# A line that opens with the underscore marker sigil, or contains a
# backstitch HTML comment ANYWHERE (HTML markers may trail headings), but
# matches neither valid form.
MALFORMED_MARKER_RE = re.compile(r"^_Traceability:", re.IGNORECASE)
MALFORMED_HTML_MARKER_RE = re.compile(r"<!--\s*backstitch:", re.IGNORECASE)
# The codes group may be EMPTY so `<!-- backstitch: ignore -->` still
# matches and is rejected as "ignore with no codes" rather than falling
# through unrecognized (where a trailing heading marker would silently
# delete the heading's section).
HTML_DIRECTIVE_RE = re.compile(
    r"<!--\s*backstitch:\s*(?P<mechanism>meta|ignore)"
    r"\b[ \t]*(?P<body>.*?)\s*-->",
    re.IGNORECASE,
)
RESERVED_SKIP_MARKER_RE = re.compile(
    r"(?:^_Traceability:|<!--\s*backstitch:)\s*skip-obligation\b",
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
class ParsedSuppressionDirective:
    mechanism: str
    codes: frozenset[str]
    declaration: str | None


@dataclass(frozen=True, slots=True)
class ParsedNoqaDirective:
    codes: frozenset[str]
    declaration: str | None
    line: int | None


@dataclass(frozen=True, slots=True)
class SuppressionDiagnostic:
    """Structured suppression-hygiene finding emitted at the parse boundary."""

    code: str
    path: str
    line: int | None
    message: str

    def to_issue(self) -> Issue:
        return Issue(
            code=self.code,
            severity="warning",
            path=self.path,
            line=self.line,
            message=self.message,
        )


def _suppression_diagnostic(
    code: str,
    message: str,
    *,
    path: str | None,
    line: int | None,
) -> SuppressionDiagnostic:
    return SuppressionDiagnostic(
        code=code,
        path=path or "<suppression>",
        line=line,
        message=message,
    )


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
    suppression_diagnostics: list[SuppressionDiagnostic] = field(default_factory=list)
    rules: tuple[SuppressionRule, ...] = ()
    declarations: dict[str, SuppressionDeclaration] = field(default_factory=dict)
    used_rules: set[SuppressionRule] = field(default_factory=set)
    referenced_declarations: set[str] = field(default_factory=set)
    inline_code_span_rules: tuple[tuple[int, int, SuppressionRule], ...] = ()

    def record_config_usage(
        self, *, file_rule: str | None, section_rule: str | None
    ) -> None:
        if file_rule is not None:
            self.used_config_file_rules.add(file_rule)
        if section_rule is not None:
            self.used_config_section_rules.add(section_rule)


def parse_traceability_codes(
    raw: str,
    *,
    allow_unknown: bool = False,
    location: str = "inline marker",
    path: str | None = None,
    line: int | None = None,
) -> tuple[frozenset[str], list[SuppressionDiagnostic]]:
    """Split a comma list of issue codes, enforcing [EXC-4] strictness.

    Unknown codes raise ``UnknownSuppressionCodeError`` naming the code and
    location; ``allow_unknown`` downgrades them to returned warnings (the
    [CFG-8] hatch, same scope, same semantics).
    """

    codes: set[str] = set()
    diagnostics: list[SuppressionDiagnostic] = []
    for part in raw.split(","):
        code = part.strip()
        if not code:
            continue
        if not is_ordinary_diagnostic_code(code):
            message = f"unknown issue code `{code}` in {location}"
            if not allow_unknown:
                raise UnknownSuppressionCodeError(message)
            diagnostics.append(
                _suppression_diagnostic(
                    "SUPPRESSION_UNKNOWN_CODE", message, path=path, line=line
                )
            )
            continue
        codes.add(canonicalize_code(code))
    return frozenset(codes), diagnostics


def _parse_ignore_codes(
    raw: str,
    *,
    allow_unknown: bool,
    location: str,
    path: str | None,
    line: int | None,
) -> tuple[bool, frozenset[str], list[SuppressionDiagnostic]]:
    codes, diagnostics = parse_traceability_codes(
        raw,
        allow_unknown=allow_unknown,
        location=location,
        path=path,
        line=line,
    )
    if not codes and not diagnostics:
        # [EXC-4]: an ignore marker with no codes (`_Traceability: ignore_`,
        # `<!-- backstitch: ignore -->`) is malformed -- fake protection,
        # same strictness and hatch as an unknown code.
        message = f"malformed traceability marker in {location}: ignore with no codes"
        if not allow_unknown:
            raise UnknownSuppressionCodeError(message)
        return (
            False,
            frozenset(),
            [
                _suppression_diagnostic(
                    "SUPPRESSION_INVALID_SYNTAX", message, path=path, line=line
                )
            ],
        )
    return False, codes, diagnostics


def parse_traceability_marker_line(
    text: str,
    *,
    allow_unknown: bool = False,
    location: str = "inline marker",
    path: str | None = None,
    line: int | None = None,
) -> tuple[bool, frozenset[str], list[SuppressionDiagnostic]]:
    directive, diagnostics = parse_traceability_directive_line(
        text,
        allow_unknown=allow_unknown,
        location=location,
        path=path,
        line=line,
    )
    if directive is None:
        return False, frozenset(), diagnostics
    return directive.mechanism == "meta", directive.codes, diagnostics


def parse_traceability_directive_line(  # noqa: C901 approved [SC-17.1] RUFF-SUP-042 exception
    text: str,
    *,
    allow_unknown: bool = False,
    location: str = "inline marker",
    path: str | None = None,
    line: int | None = None,
) -> tuple[ParsedSuppressionDirective | None, list[SuppressionDiagnostic]]:
    """Parse one ordinary spec suppression, including an optional declaration."""

    stripped = text.strip()
    # [EVC-8.3.2] owns this reserved repository-source grammar.  It is
    # deliberately not an ordinary ignore/meta marker and malformed forms do
    # not take EXC's strict unknown-code path.  The Markdown parser emits its
    # dedicated warning diagnostics independently.
    if RESERVED_SKIP_MARKER_RE.search(stripped):
        return None, []
    match = TRACEABILITY_DIRECTIVE_RE.match(stripped)
    if match is None:
        match = HTML_DIRECTIVE_RE.search(stripped)
    if match is not None:
        mechanism = match.group("mechanism").lower()
        body = (match.group("body") or "").strip()
        declaration: str | None = None
        starts_with_declaration = body.startswith("because ")
        if re.match(r"because\s+", body, re.IGNORECASE) and not starts_with_declaration:
            return None, [
                _suppression_diagnostic(
                    "SUPPRESSION_INVALID_SYNTAX",
                    f"declaration delimiter must be lowercase `because ` in {location}",
                    path=path,
                    line=line,
                )
            ]
        if re.search(r"\s+because\s+", body, re.IGNORECASE) and " because " not in body:
            return None, [
                _suppression_diagnostic(
                    "SUPPRESSION_INVALID_SYNTAX",
                    f"declaration delimiter must be lowercase ` because ` in {location}",
                    path=path,
                    line=line,
                )
            ]
        if mechanism == "meta" and starts_with_declaration:
            declaration = body.removeprefix("because ").strip()
            body = ""
            if match.re is TRACEABILITY_DIRECTIVE_RE and not match.group("close"):
                return None, [
                    _suppression_diagnostic(
                        "SUPPRESSION_INVALID_SYNTAX",
                        (
                            "underscore declaration form requires one closing `_` "
                            f"in {location}"
                        ),
                        path=path,
                        line=line,
                    )
                ]
            if not is_valid_suppression_reference(declaration):
                return None, [
                    _suppression_diagnostic(
                        "SUPPRESSION_INVALID_SYNTAX",
                        f"invalid suppression declaration reference in {location}",
                        path=path,
                        line=line,
                    )
                ]
        elif " because " in body:
            if body.count(" because ") != 1:
                return None, [
                    _suppression_diagnostic(
                        "SUPPRESSION_INVALID_SYNTAX",
                        f"malformed declaration clause in {location}",
                        path=path,
                        line=line,
                    )
                ]
            body, declaration = body.rsplit(" because ", 1)
            body = body.strip()
            declaration = declaration.strip()
            if match.re is TRACEABILITY_DIRECTIVE_RE and not match.group("close"):
                return None, [
                    _suppression_diagnostic(
                        "SUPPRESSION_INVALID_SYNTAX",
                        (
                            "underscore declaration form requires one closing `_` "
                            f"in {location}"
                        ),
                        path=path,
                        line=line,
                    )
                ]
            if not is_valid_suppression_reference(declaration):
                return None, [
                    _suppression_diagnostic(
                        "SUPPRESSION_INVALID_SYNTAX",
                        f"invalid suppression declaration reference in {location}",
                        path=path,
                        line=line,
                    )
                ]
        if mechanism == "meta":
            if body:
                return None, [
                    _suppression_diagnostic(
                        "SUPPRESSION_INVALID_SYNTAX",
                        f"malformed meta marker in {location}",
                        path=path,
                        line=line,
                    )
                ]
            return (
                ParsedSuppressionDirective(
                    mechanism="meta",
                    codes=META_DEFAULT_SUPPRESSED,
                    declaration=declaration,
                ),
                [],
            )
        _unused_meta, codes, diagnostics = _parse_ignore_codes(
            body,
            allow_unknown=allow_unknown,
            location=location,
            path=path,
            line=line,
        )
        if not codes:
            return None, diagnostics
        return (
            ParsedSuppressionDirective(
                mechanism="ignore",
                codes=codes,
                declaration=declaration,
            ),
            diagnostics,
        )
    # [EXC-4]: a line that STARTS like a marker but parses as neither form
    # (`_Traceability: ignore_` with no codes, `_Traceability: bogus_`) is
    # a malformed suppression -- the same fake affordance as an unknown
    # code, with the same strictness and hatch.
    if MALFORMED_MARKER_RE.match(stripped) or MALFORMED_HTML_MARKER_RE.search(stripped):
        message = f"malformed traceability marker in {location}: {stripped!r}"
        if not allow_unknown:
            raise UnknownSuppressionCodeError(message)
        return None, [
            _suppression_diagnostic(
                "SUPPRESSION_INVALID_SYNTAX", message, path=path, line=line
            )
        ]
    return None, []


def parse_noqa_text(
    text: str,
    *,
    allow_unknown: bool = False,
    location: str = "inline noqa",
    path: str | None = None,
    line: int | None = None,
) -> tuple[frozenset[str], list[SuppressionDiagnostic]]:
    """Parse ``backstitch: noqa`` directives into codes and diagnostics.

    Only lines that START with the marker are directives ([EXC-5] grammar).
    Malformed directives (no codes, or unparseable tokens) always warn;
    unknown codes follow [EXC-4] strictness -- error by default,
    ``allow_unknown`` downgrades to warnings. All warnings must reach
    stderr -- a discarded warning makes typo suppressions silent.
    """

    directives, diagnostics = parse_noqa_directives(
        text,
        allow_unknown=allow_unknown,
        location=location,
        path=path,
        line=line,
    )
    return (
        frozenset(code for directive in directives for code in directive.codes),
        diagnostics,
    )


def is_noqa_directive_line(text: str) -> bool:
    """Return whether one physical line has the anchored Python marker."""

    return NOQA_LINE_RE.match(text.strip()) is not None


def parse_noqa_directives(
    text: str,
    *,
    allow_unknown: bool = False,
    location: str = "inline noqa",
    path: str | None = None,
    line: int | None = None,
) -> tuple[tuple[ParsedNoqaDirective, ...], list[SuppressionDiagnostic]]:
    """Parse Python suppression directives without discarding provenance."""

    directives: list[ParsedNoqaDirective] = []
    diagnostics: list[SuppressionDiagnostic] = []
    for offset, raw_line in enumerate(lf_split(text)):
        diagnostic_line = line + offset if line is not None else None
        match = NOQA_LINE_RE.match(raw_line.strip())
        if match is None:
            continue
        rest = match.group("rest").strip()
        if not rest:
            message = (
                f"malformed `backstitch: noqa` directive in {location}: no issue codes"
            )
            diagnostics.append(
                _suppression_diagnostic(
                    "SUPPRESSION_INVALID_SYNTAX",
                    message,
                    path=path,
                    line=diagnostic_line,
                )
            )
            continue
        declaration: str | None = None
        if re.search(r"\s+because\s+", rest, re.IGNORECASE) and " because " not in rest:
            diagnostics.append(
                _suppression_diagnostic(
                    "SUPPRESSION_INVALID_SYNTAX",
                    f"declaration delimiter must be lowercase ` because ` in {location}",
                    path=path,
                    line=diagnostic_line,
                )
            )
            continue
        if " because " in rest:
            if rest.count(" because ") != 1:
                diagnostics.append(
                    _suppression_diagnostic(
                        "SUPPRESSION_INVALID_SYNTAX",
                        f"malformed declaration clause in {location}",
                        path=path,
                        line=diagnostic_line,
                    )
                )
                continue
            rest, declaration = rest.rsplit(" because ", 1)
            rest = rest.strip()
            declaration = declaration.strip()
            if not is_valid_suppression_reference(declaration):
                diagnostics.append(
                    _suppression_diagnostic(
                        "SUPPRESSION_INVALID_SYNTAX",
                        f"invalid suppression declaration reference in {location}",
                        path=path,
                        line=diagnostic_line,
                    )
                )
                continue
        tokens = [t for t in re.split(r"[,\s]+", rest) if t]
        bad = sorted({t for t in tokens if not CODE_TOKEN_RE.match(t)})
        if bad:
            message = (
                f"malformed `backstitch: noqa` directive in {location}:"
                f" unparseable token(s) {', '.join(bad)}"
                " -- codes are comma-separated issue codes"
            )
            diagnostics.append(
                _suppression_diagnostic(
                    "SUPPRESSION_INVALID_SYNTAX",
                    message,
                    path=path,
                    line=diagnostic_line,
                )
            )
        idents = ",".join(t for t in tokens if CODE_TOKEN_RE.match(t))
        parsed, parse_diagnostics = parse_traceability_codes(
            idents,
            allow_unknown=allow_unknown,
            location=location,
            path=path,
            line=diagnostic_line,
        )
        diagnostics.extend(parse_diagnostics)
        if parsed:
            directives.append(
                ParsedNoqaDirective(
                    codes=parsed,
                    declaration=declaration,
                    line=diagnostic_line,
                )
            )
    return tuple(directives), diagnostics


def _is_non_suppressible(
    issue: Issue,
    suppressible_levels: tuple[Severity, ...],
) -> bool:
    return issue.severity not in suppressible_levels


def _path_matches_glob(path: str, pattern: str) -> bool:
    return fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(path, f"**/{pattern}")


def _meta_suppresses(issue: Issue, *, code_file: str | None) -> bool:
    if issue.code in META_DEFAULT_SUPPRESSED:
        return True
    if issue.code == "CODE_BACKLINK_RECIPROCAL_MISSING":
        target = code_file or issue.path
        if target is not None and not target.endswith(".py"):
            return True
    return False


def should_suppress(
    issue: Issue,
    index: SuppressionIndex,
    *,
    spec_file: str | None = None,
    section_id: str | None = None,
    code_file: str | None = None,
    suppressible_levels: tuple[Severity, ...] = ("warning", "info"),
) -> tuple[bool, SuppressionReason | None]:
    decision = suppression_decision(
        issue,
        index,
        spec_file=spec_file,
        section_id=section_id,
        code_file=code_file,
        suppressible_levels=suppressible_levels,
    )
    if decision is None:
        return False, None
    return True, SuppressionReason(decision.reason)


def suppression_decision(  # noqa: C901 approved [SC-17.1] RUFF-SUP-043 exception
    issue: Issue,
    index: SuppressionIndex,
    *,
    spec_file: str | None = None,
    section_id: str | None = None,
    code_file: str | None = None,
    suppressible_levels: tuple[Severity, ...] = ("warning", "info"),
) -> SuppressionDecision | None:
    """Apply the one canonical ordered rule path and return its audit decision."""

    resolved_spec_file = spec_file or (
        issue.path if issue.path and issue.path.endswith(".md") else None
    )
    resolved_section_id = section_id or issue.section_id
    resolved_code_file = code_file or (
        issue.path if issue.path and issue.path.endswith(".py") else None
    )
    decision: SuppressionDecision | None = None
    span_rules = {
        rule: (start, end) for start, end, rule in index.inline_code_span_rules
    }
    for rule in index.rules:
        target_path = (
            resolved_spec_file
            if rule.provenance in {"meta", "inline_spec", "config_section"}
            or rule.sections
            else (resolved_code_file or resolved_spec_file or issue.path)
        )
        if target_path is None or not (
            target_path == rule.path or _path_matches_glob(target_path, rule.path)
        ):
            continue
        if rule.sections:
            if resolved_section_id is None or not any(
                section == "*" or section == resolved_section_id
                for section in rule.sections
            ):
                continue
        if (
            rule.provenance == "inline_spec"
            and not rule.sections
            and resolved_section_id is not None
            and (resolved_spec_file, resolved_section_id) in index.sections_with_markers
        ):
            continue
        if rule in span_rules:
            start, end = span_rules[rule]
            if issue.line is None or not start <= issue.line <= end:
                continue
        if rule.mechanism == "meta":
            if resolved_spec_file is None or not _meta_suppresses(
                issue,
                code_file=resolved_code_file,
            ):
                continue
        elif issue.code not in rule.codes:
            continue
        index.used_rules.add(rule)
        if rule.origin.source == "lint.per-file-ignores":
            index.used_config_file_rules.add(rule.path)
        elif rule.origin.source == "lint.per-section-ignores":
            index.used_config_section_rules.add(f"{rule.path}::{rule.sections[0]}")
        if _is_non_suppressible(issue, suppressible_levels):
            index.suppression_diagnostics.append(
                _suppression_diagnostic(
                    "SUPPRESSION_UNSUPPRESSIBLE_CODE",
                    (
                        f"suppression ignored for non-suppressible code {issue.code}"
                        f" in {rule.origin.source}"
                    ),
                    path=rule.origin.source,
                    line=rule.origin.line,
                )
            )
            continue
        declaration = (
            index.declarations.get(rule.declaration)
            if rule.declaration is not None
            else None
        )
        decision = SuppressionDecision(
            issue=issue,
            reason=rule.provenance,
            declaration=rule.declaration,
            rationale=declaration.rationale if declaration is not None else None,
            rule=rule,
        )
    return decision


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
    marker_diagnostics: list[SuppressionDiagnostic] | None = None,
    declarations: tuple[SuppressionDeclaration, ...] = (),
    inline_spec_rules: tuple[SuppressionRule, ...] = (),
    inline_code_rules: tuple[SuppressionRule, ...] = (),
    inline_code_span_rules: tuple[tuple[int, int, SuppressionRule], ...] = (),
    allow_unknown: bool = False,
) -> SuppressionIndex:
    canonical_lint = _canonicalize_lint_settings(lint)
    legacy_meta_rules = tuple(
        SuppressionRule(
            mechanism="meta",
            provenance="meta",
            path=pattern,
            sections=(),
            codes=(),
            declaration=None,
            origin=SuppressionOrigin(
                source="profile.meta_spec_globs",
                position=position,
            ),
        )
        for position, pattern in enumerate(meta_spec_globs)
    )
    legacy_file_rules = tuple(
        SuppressionRule(
            mechanism="ignore",
            provenance="config_file",
            path=pattern,
            sections=(),
            codes=tuple(codes),
            declaration=None,
            origin=SuppressionOrigin(
                source="lint.per-file-ignores",
                position=position,
            ),
        )
        for position, (pattern, codes) in enumerate(
            canonical_lint.per_file_ignores.items()
        )
    )
    legacy_section_rules = tuple(
        SuppressionRule(
            mechanism="ignore",
            provenance="config_section",
            path=pattern.split("::", 1)[0],
            sections=(pattern.split("::", 1)[1],),
            codes=tuple(codes),
            declaration=None,
            origin=SuppressionOrigin(
                source="lint.per-section-ignores",
                position=position,
            ),
        )
        for position, (pattern, codes) in enumerate(
            canonical_lint.per_section_ignores.items()
        )
        if "::" in pattern
    )
    structured_meta = tuple(
        rule for rule in canonical_lint.suppressions if rule.mechanism == "meta"
    )
    structured_ignore = tuple(
        rule for rule in canonical_lint.suppressions if rule.mechanism == "ignore"
    )
    legacy_inline_spec_rules = (
        ()
        if inline_spec_rules
        else (
            *(
                SuppressionRule(
                    mechanism="ignore",
                    provenance="inline_spec",
                    path=path,
                    sections=(section_id,),
                    codes=tuple(sorted(codes)),
                    declaration=None,
                    origin=SuppressionOrigin(source=path, line=1),
                )
                for (path, section_id), codes in sorted(
                    (inline_spec_ignores or {}).items()
                )
            ),
            *(
                SuppressionRule(
                    mechanism="ignore",
                    provenance="inline_spec",
                    path=path,
                    sections=(),
                    codes=tuple(sorted(codes)),
                    declaration=None,
                    origin=SuppressionOrigin(source=path, line=1),
                )
                for path, codes in sorted((inline_file_ignores or {}).items())
            ),
        )
    )
    legacy_inline_code_rules = (
        ()
        if inline_code_rules
        else tuple(
            SuppressionRule(
                mechanism="ignore",
                provenance="inline_code",
                path=path,
                sections=(),
                codes=tuple(sorted(codes)),
                declaration=None,
                origin=SuppressionOrigin(source=path, line=1),
            )
            for path, codes in sorted((inline_code_ignores or {}).items())
        )
    )
    candidate_rules = (
        *legacy_meta_rules,
        *structured_meta,
        *legacy_file_rules,
        *legacy_section_rules,
        *structured_ignore,
        *legacy_inline_spec_rules,
        *legacy_inline_code_rules,
        *inline_spec_rules,
        *inline_code_rules,
        *(rule for _start, _end, rule in inline_code_span_rules),
    )
    declarations_by_reference = {
        declaration.reference: declaration for declaration in declarations
    }
    eligible_rules: list[SuppressionRule] = []
    validation_diagnostics: list[SuppressionDiagnostic] = []
    referenced_declarations: set[str] = set()
    for rule in candidate_rules:
        if rule.declaration is None:
            if canonical_lint.require_suppression_declarations:
                validation_diagnostics.append(
                    _suppression_diagnostic(
                        "SUPPRESSION_REASON_MISSING",
                        "suppression requires a valid declaration reference",
                        path=rule.origin.source,
                        line=rule.origin.line,
                    )
                )
                continue
        else:
            referenced_declarations.add(rule.declaration)
            if rule.declaration not in declarations_by_reference:
                validation_diagnostics.append(
                    _suppression_diagnostic(
                        "SUPPRESSION_REASON_MISSING",
                        (
                            "suppression declaration reference does not resolve: "
                            f"{rule.declaration}"
                        ),
                        path=rule.origin.source,
                        line=rule.origin.line,
                    )
                )
                continue
        eligible_rules.append(rule)
    index = SuppressionIndex(
        meta_spec_globs=meta_spec_globs,
        lint=canonical_lint,
        section_meta=dict(section_meta or {}),
        inline_spec_ignores=dict(inline_spec_ignores or {}),
        inline_file_ignores=dict(inline_file_ignores or {}),
        inline_code_ignores=dict(inline_code_ignores or {}),
        inline_code_span_ignores=dict(inline_code_span_ignores or {}),
        sections_with_markers=sections_with_markers,
        rules=tuple(eligible_rules),
        declarations=declarations_by_reference,
        referenced_declarations=referenced_declarations,
        inline_code_span_rules=inline_code_span_rules,
    )
    if marker_diagnostics:
        index.suppression_diagnostics.extend(marker_diagnostics)
    index.suppression_diagnostics.extend(validation_diagnostics)
    _validate_config_codes(index, allow_unknown=allow_unknown)
    return index


def collect_unused_ignore_diagnostics(
    index: SuppressionIndex,
) -> list[SuppressionDiagnostic]:
    if not index.lint.warn_unused_ignores:
        return []
    diagnostics: list[SuppressionDiagnostic] = []
    for rule in index.rules:
        audits_unused = rule.declaration is not None or rule.origin.source in {
            "lint.per-file-ignores",
            "lint.per-section-ignores",
        }
        if audits_unused and rule not in index.used_rules:
            if rule.origin.source == "lint.per-file-ignores":
                message = f"unused per-file-ignore rule: {rule.path}"
            elif rule.origin.source == "lint.per-section-ignores":
                message = f"unused per-section-ignore rule: {rule.path}"
            else:
                message = f"unused suppression rule: {rule.path}"
            diagnostics.append(
                _suppression_diagnostic(
                    "SUPPRESSION_UNUSED",
                    message,
                    path=(
                        f"{rule.path}::{rule.sections[0]}"
                        if rule.origin.source == "lint.per-section-ignores"
                        else rule.path
                    ),
                    line=rule.origin.line,
                )
            )
    for reference, declaration in index.declarations.items():
        if reference not in index.referenced_declarations:
            diagnostics.append(
                _suppression_diagnostic(
                    "SUPPRESSION_UNUSED",
                    f"unreferenced suppression declaration: {reference}",
                    path=declaration.path,
                    line=declaration.start_line,
                )
            )
    return diagnostics


def validate_lint_codes(
    lint: LintSettings, *, allow_unknown: bool
) -> list[SuppressionDiagnostic]:
    """Validate suppression codes in config lint tables ([EXC-4]).

    Raises ``UnknownSuppressionCodeError`` by default; ``allow_unknown``
    downgrades unknown codes to returned warnings. Shared by the check
    pipeline and `config show` so both apply the same load strictness.
    """

    diagnostics: list[SuppressionDiagnostic] = []
    for table_name, table in (
        ("lint.per-file-ignores", lint.per_file_ignores),
        ("lint.per-section-ignores", lint.per_section_ignores),
    ):
        for path_key, codes in table.items():
            for code in codes:
                if not is_ordinary_diagnostic_code(code):
                    # [EXC-4]: unknown suppression codes fail load by
                    # default -- same hatch, same scope as [CFG-8].
                    message = (
                        f"unknown issue code `{code}` in {table_name} for {path_key}"
                    )
                    if not allow_unknown:
                        raise UnknownSuppressionCodeError(message)
                    diagnostics.append(
                        _suppression_diagnostic(
                            "SUPPRESSION_UNKNOWN_CODE",
                            message,
                            path=path_key,
                            line=None,
                        )
                    )
    for position, rule in enumerate(lint.suppressions):
        for code in rule.codes:
            if not is_ordinary_diagnostic_code(code):
                message = (
                    f"unknown issue code `{code}` in lint.suppressions[{position}]"
                )
                if not allow_unknown:
                    raise UnknownSuppressionCodeError(message)
                diagnostics.append(
                    _suppression_diagnostic(
                        "SUPPRESSION_UNKNOWN_CODE",
                        message,
                        path=rule.path,
                        line=None,
                    )
                )
    return diagnostics


def _canonicalize_lint_settings(lint: LintSettings) -> LintSettings:
    def canonicalize_table(
        table: dict[str, tuple[str, ...]],
    ) -> dict[str, tuple[str, ...]]:
        return {
            key: tuple(
                canonicalize_code(code) if is_ordinary_diagnostic_code(code) else code
                for code in codes
            )
            for key, codes in table.items()
        }

    return LintSettings(
        warn_unused_ignores=lint.warn_unused_ignores,
        require_suppression_declarations=lint.require_suppression_declarations,
        per_file_ignores=canonicalize_table(lint.per_file_ignores),
        per_section_ignores=canonicalize_table(lint.per_section_ignores),
        suppressions=tuple(
            SuppressionRule(
                mechanism=rule.mechanism,
                provenance=rule.provenance,
                path=rule.path,
                sections=tuple(sorted(rule.sections)),
                codes=tuple(
                    sorted(
                        canonicalize_code(code)
                        if is_ordinary_diagnostic_code(code)
                        else code
                        for code in rule.codes
                    )
                ),
                declaration=rule.declaration,
                origin=rule.origin,
            )
            for rule in lint.suppressions
        ),
    )


def _validate_config_codes(index: SuppressionIndex, *, allow_unknown: bool) -> None:
    index.suppression_diagnostics.extend(
        validate_lint_codes(index.lint, allow_unknown=allow_unknown)
    )
