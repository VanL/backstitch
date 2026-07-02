"""Deterministic trace-graph construction and issue classification.

Spec: docs/specs/02-backstitch-core.md [SC-4], [SC-9]
Grammar and strictness table:
docs/implementation/04-backstitch-style-traceability.md

``scan_repository`` does the file IO; ``resolve`` is pure so the graph
policy can be tested from parsed records alone. Neither calls ``llm``,
the network, or target-project code [SC-4].

``resolve`` orchestrates five phases over a shared ``_GraphIndex``:
duplicate detection, mapping resolution, code-ref resolution, reciprocal
inventory, and stable ordering. Issue severity stays explicit at every
emission site; there is deliberately no code-to-severity table.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

from backstitch.config import ProfileConfig
from backstitch.markdown_specs import ParsedSpec, parse_markdown_spec
from backstitch.models import (
    CodeRef,
    Edge,
    Issue,
    Report,
    Severity,
    SpecMapping,
    SpecSection,
)
from backstitch.python_refs import (
    ParsedPython,
    parse_python_file,
    python_symbol_inventory,
)
from backstitch.settings import DEFAULT_EXCLUDES, is_excluded

_FINAL_NUMBER_RE = re.compile(r"^(?P<base>.*?)(?P<num>\d+)$")
_ALPHA_PREFIX_RE = re.compile(r"^[A-Z][A-Za-z]*")


class ScanError(Exception):
    """Raised when the target repository cannot be scanned at all.

    The CLI maps this to exit code 2 [SC-5].
    """


def _expand_range(start: str, end: str) -> tuple[str, list[str]] | str:
    """Expand a same-prefix numeric range into candidate IDs.

    Returns ``(base, ids)`` on success or an error message when the range
    cannot be expanded without guessing [SC-9].
    """

    start_match = _FINAL_NUMBER_RE.match(start)
    end_match = _FINAL_NUMBER_RE.match(end)
    if not start_match or not end_match:
        return f"range [{start}]-[{end}] does not end in numeric segments"
    if start_match.group("base") != end_match.group("base"):
        return f"range [{start}]-[{end}] does not share a common prefix"
    low = int(start_match.group("num"))
    high = int(end_match.group("num"))
    if low > high:
        return f"range [{start}]-[{end}] runs backwards"
    base = start_match.group("base")
    return base, [f"{base}{n}" for n in range(low, high + 1)]


def _is_under(path: str, roots: Sequence[str]) -> bool:
    pure = PurePosixPath(path)
    return any(pure.is_relative_to(root) for root in roots)


@dataclass(frozen=True, slots=True)
class _GraphIndex:
    """Lookup structures shared by the resolution phases.

    ``spec_paths`` and ``anchors_by_file`` come from the ParsedSpec
    records themselves: a spec file with zero ID-bearing sections still
    registers its path and its non-ID heading anchors. The other fields
    derive from the flattened section definitions.
    """

    sections_by_id: dict[str, list[SpecSection]]
    sections_by_file_id: dict[tuple[str, str], SpecSection]
    anchor_to_section: dict[tuple[str, str], SpecSection]
    ids_by_file: dict[str, set[str]]
    anchors_by_file: dict[str, set[str]]
    spec_paths: frozenset[str]
    known_prefixes: frozenset[str]


def _build_index(parsed_specs: Sequence[ParsedSpec]) -> _GraphIndex:
    sections = [s for spec in parsed_specs for s in spec.sections]

    sections_by_id: dict[str, list[SpecSection]] = {}
    sections_by_file_id: dict[tuple[str, str], SpecSection] = {}
    anchor_to_section: dict[tuple[str, str], SpecSection] = {}
    ids_by_file: dict[str, set[str]] = {}
    for section in sections:
        sections_by_id.setdefault(section.section_id, []).append(section)
        sections_by_file_id.setdefault((section.path, section.section_id), section)
        if section.anchor is not None:
            anchor_to_section.setdefault((section.path, section.anchor), section)
        ids_by_file.setdefault(section.path, set()).add(section.section_id)

    known_prefixes = frozenset(
        match.group()
        for section in sections
        if (match := _ALPHA_PREFIX_RE.match(section.section_id))
    )
    return _GraphIndex(
        sections_by_id=sections_by_id,
        sections_by_file_id=sections_by_file_id,
        anchor_to_section=anchor_to_section,
        ids_by_file=ids_by_file,
        anchors_by_file={spec.path: set(spec.anchors) for spec in parsed_specs},
        spec_paths=frozenset(spec.path for spec in parsed_specs),
        known_prefixes=known_prefixes,
    )


def _emit(
    issues: list[Issue],
    code: str,
    severity: Severity,
    path: str,
    line: int | None,
    message: str,
    *,
    section_id: str | None = None,
    symbol: str | None = None,
) -> None:
    issues.append(
        Issue(
            code=code,
            severity=severity,
            path=path,
            line=line,
            message=message,
            section_id=section_id,
            symbol=symbol,
        )
    )


def _duplicate_section_issues(index: _GraphIndex, issues: list[Issue]) -> None:
    for section_id, defs in sorted(index.sections_by_id.items()):
        if len(defs) > 1:
            locations = ", ".join(f"{d.path}:{d.line}" for d in defs)
            _emit(
                issues,
                "SPEC_SECTION_DUPLICATE",
                "warning",
                defs[0].path,
                defs[0].line,
                f"section ID [{section_id}] is defined more than once: {locations}",
                section_id=section_id,
            )


def ladder_candidates(token: str, scan_files: Sequence[str]) -> list[str]:
    """Suffix/basename candidates for a non-exact mapping token ([SC-4] ladder).

    Exact matches are the caller's rung 1 and never reach here; candidates
    are scanned files whose path ends with ``/<token>`` (which also covers
    bare basenames). Sorted for deterministic output.
    """

    suffix = "/" + token.lstrip("/")
    return sorted(rel for rel in scan_files if rel != token and rel.endswith(suffix))


def _missing_path_severity(token: str, plan_roots: tuple[str, ...]) -> Severity:
    """[SC-11] predicate: `.md` under a configured plan root is a warning."""

    if token.endswith(".md") and any(
        token.startswith(root.rstrip("/") + "/") for root in plan_roots
    ):
        return "warning"
    return "error"


def _resolve_mappings(
    mappings: Sequence[SpecMapping],
    mapping_path_exists: Mapping[str, bool],
    python_symbols: Mapping[str, frozenset[str] | None],
    scan_files: Sequence[str],
    plan_roots: tuple[str, ...],
    issues: list[Issue],
    edges: list[Edge],
) -> None:
    for mapping in mappings:
        if mapping.kind == "symbol":
            _emit(
                issues,
                "MAPPING_SYMBOL_UNRESOLVED",
                "warning",
                mapping.spec_path,
                mapping.line,
                f"bare mapping symbol `{mapping.target}` is advisory;"
                " v1 does not infer its file",
                section_id=mapping.section_id,
                symbol=mapping.target_symbol,
            )
            continue
        target_path = mapping.target_path or ""
        if not mapping_path_exists.get(target_path, False):
            # [SC-4] ladder rungs 2-4: exact failed; try unique suffix or
            # basename, report ambiguity, or report missing -- never guess.
            candidates = ladder_candidates(target_path, scan_files)
            if len(candidates) == 1:
                resolved = candidates[0]
                _emit(
                    issues,
                    "MAPPING_PATH_INEXACT",
                    "warning",
                    mapping.spec_path,
                    mapping.line,
                    f"mapping token `{target_path}` resolved via unique"
                    f" suffix match to `{resolved}`; use the exact"
                    " repo-relative path",
                    section_id=mapping.section_id,
                    symbol=mapping.target_symbol,
                )
                target_path = resolved
            elif candidates:
                listed = ", ".join(f"`{c}`" for c in candidates)
                _emit(
                    issues,
                    "TARGET_PATH_AMBIGUOUS",
                    "error",
                    mapping.spec_path,
                    mapping.line,
                    f"mapping token `{target_path}` matches multiple"
                    f" paths: {listed}; no edge emitted",
                    section_id=mapping.section_id,
                    symbol=mapping.target_symbol,
                )
                continue
            else:
                _emit(
                    issues,
                    "MAPPING_PATH_MISSING",
                    _missing_path_severity(target_path, plan_roots),
                    mapping.spec_path,
                    mapping.line,
                    f"mapping path `{target_path}` does not exist",
                    section_id=mapping.section_id,
                    symbol=mapping.target_symbol,
                )
                continue
        if mapping.kind == "path":
            edges.append(
                Edge(
                    kind="mapping",
                    spec_path=mapping.spec_path,
                    section_id=mapping.section_id,
                    code_path=target_path,
                    code_symbol=None,
                    line=mapping.line,
                )
            )
            continue
        # path_symbol
        if not target_path.endswith(".py"):
            _emit(
                issues,
                "MAPPING_SYMBOL_UNRESOLVED",
                "warning",
                mapping.spec_path,
                mapping.line,
                f"cannot inventory symbols in non-Python file `{target_path}`",
                section_id=mapping.section_id,
                symbol=mapping.target_symbol,
            )
            continue
        inventory = python_symbols.get(target_path)
        if inventory is None:
            _emit(
                issues,
                "MAPPING_SYMBOL_UNRESOLVED",
                "warning",
                mapping.spec_path,
                mapping.line,
                f"could not parse `{target_path}` to inventory symbols",
                section_id=mapping.section_id,
                symbol=mapping.target_symbol,
            )
        elif mapping.target_symbol in inventory:
            edges.append(
                Edge(
                    kind="mapping",
                    spec_path=mapping.spec_path,
                    section_id=mapping.section_id,
                    code_path=target_path,
                    code_symbol=mapping.target_symbol,
                    line=mapping.line,
                )
            )
        else:
            _emit(
                issues,
                "MAPPING_SYMBOL_MISSING",
                "error",
                mapping.spec_path,
                mapping.line,
                f"symbol `{mapping.target_symbol}` not found in `{target_path}`",
                section_id=mapping.section_id,
                symbol=mapping.target_symbol,
            )


def _classify_spec_file(path: str, profile: ProfileConfig) -> str:
    if any(fnmatch(path, glob) for glob in profile.planned_spec_globs):
        return "planned"
    if any(fnmatch(path, glob) for glob in profile.exploratory_spec_globs):
        return "exploratory"
    return "current"


def _resolve_bare(
    ref: CodeRef,
    section_id: str,
    index: _GraphIndex,
    issues: list[Issue],
) -> SpecSection | None:
    """Resolve one bare candidate ID, or emit the weak-link finding.

    Candidates whose alphabetic prefix is unknown to the corpus are
    prose noise and stay silent.
    """

    defs = index.sections_by_id.get(section_id, [])
    if len(defs) == 1:
        return defs[0]
    if not defs:
        prefix = _ALPHA_PREFIX_RE.match(section_id)
        if prefix is None or prefix.group() not in index.known_prefixes:
            return None
        _emit(
            issues,
            "CODE_REF_BARE_UNRESOLVED",
            "warning",
            ref.path,
            ref.line,
            f"bare reference [{section_id}] matches no known section",
            section_id=section_id,
            symbol=ref.owner_symbol,
        )
    else:
        locations = ", ".join(f"{d.path}:{d.line}" for d in defs)
        # [SC-11] context-dependent severity: a `Spec:` marker line ASSERTS
        # a specific trace edge that cannot be established (error); the same
        # bare ID in docstring prose or a comment is a weak link (warning).
        # Context comes from CodeRef.ref_context, set at parse time.
        severity: Severity = "error" if ref.ref_context == "asserted" else "warning"
        _emit(
            issues,
            "SPEC_SECTION_AMBIGUOUS",
            severity,
            ref.path,
            ref.line,
            f"bare reference [{section_id}] is ambiguous: {locations}",
            section_id=section_id,
            symbol=ref.owner_symbol,
        )
    return None


def _resolve_code_refs(
    refs: Sequence[CodeRef],
    index: _GraphIndex,
    profile: ProfileConfig,
    issues: list[Issue],
    edges: list[Edge],
) -> None:
    def backlink_edge(ref: CodeRef, section: SpecSection) -> None:
        edges.append(
            Edge(
                kind="backlink",
                spec_path=section.path,
                section_id=section.section_id,
                code_path=ref.path,
                code_symbol=ref.owner_symbol,
                line=ref.line,
            )
        )

    for ref in refs:
        target_files: set[str] = set()
        if ref.spec_path is not None:
            _resolve_file_qualified_ref(
                ref, index, profile, issues, backlink_edge, target_files
            )
        else:
            for section_id in ref.section_ids:
                bare_section = _resolve_bare(ref, section_id, index, issues)
                if bare_section is not None:
                    target_files.add(bare_section.path)
                    backlink_edge(ref, bare_section)
            for start, end in ref.ranges:
                # Bare ranges obey the same noise rule as bare IDs: if
                # neither endpoint's prefix is known to the corpus, the
                # candidate is prose noise, not a reference.
                prefixes = [
                    match.group()
                    for endpoint in (start, end)
                    if (match := _ALPHA_PREFIX_RE.match(endpoint))
                ]
                if not any(prefix in index.known_prefixes for prefix in prefixes):
                    continue
                expansion = _expand_range(start, end)
                if isinstance(expansion, str):
                    _emit(
                        issues,
                        "REF_RANGE_UNSUPPORTED",
                        "error",
                        ref.path,
                        ref.line,
                        expansion,
                        symbol=ref.owner_symbol,
                    )
                    continue
                for section_id in expansion[1]:
                    bare_section = _resolve_bare(ref, section_id, index, issues)
                    if bare_section is not None:
                        target_files.add(bare_section.path)
                        backlink_edge(ref, bare_section)

        for target in sorted(target_files):
            classification = _classify_spec_file(target, profile)
            if classification == "current":
                continue
            code = (
                "CODE_REF_PLANNED_SPEC"
                if classification == "planned"
                else "CODE_REF_EXPLORATORY_SPEC"
            )
            _emit(
                issues,
                code,
                "warning",
                ref.path,
                ref.line,
                f"shipped code references {classification} spec `{target}`",
                section_id=ref.section_ids[0] if ref.section_ids else None,
                symbol=ref.owner_symbol,
            )


def _resolve_file_qualified_ref(
    ref: CodeRef,
    index: _GraphIndex,
    profile: ProfileConfig,
    issues: list[Issue],
    backlink_edge: Callable[[CodeRef, SpecSection], None],
    target_files: set[str],
) -> None:
    norm = ref.spec_path
    if norm is None or not _is_under(norm, profile.spec_roots):
        return
    if norm not in index.spec_paths:
        _emit(
            issues,
            "SPEC_FILE_MISSING",
            "error",
            ref.path,
            ref.line,
            f"referenced spec file `{norm}` does not exist",
            symbol=ref.owner_symbol,
        )
        return
    target_files.add(norm)
    if ref.anchor is not None:
        if ref.anchor not in index.anchors_by_file.get(norm, set()):
            _emit(
                issues,
                "SPEC_ANCHOR_MISSING",
                "error",
                ref.path,
                ref.line,
                f"anchor `#{ref.anchor}` not found in `{norm}`",
                symbol=ref.owner_symbol,
            )
        else:
            anchored = index.anchor_to_section.get((norm, ref.anchor))
            if anchored is not None:
                backlink_edge(ref, anchored)
    for section_id in ref.section_ids:
        file_section = index.sections_by_file_id.get((norm, section_id))
        if file_section is None:
            _emit(
                issues,
                "SPEC_SECTION_MISSING",
                "error",
                ref.path,
                ref.line,
                f"section [{section_id}] not found in `{norm}`",
                section_id=section_id,
                symbol=ref.owner_symbol,
            )
        else:
            backlink_edge(ref, file_section)
    for start, end in ref.ranges:
        expansion = _expand_range(start, end)
        if isinstance(expansion, str) or not set(expansion[1]) <= index.ids_by_file.get(
            norm, set()
        ):
            detail = (
                expansion
                if isinstance(expansion, str)
                else (f"range [{start}]-[{end}] has undefined sections in `{norm}`")
            )
            _emit(
                issues,
                "REF_RANGE_UNSUPPORTED",
                "error",
                ref.path,
                ref.line,
                detail,
                symbol=ref.owner_symbol,
            )
            continue
        for section_id in expansion[1]:
            backlink_edge(ref, index.sections_by_file_id[(norm, section_id)])
    if not ref.section_ids and not ref.ranges and ref.anchor is None:
        _emit(
            issues,
            "CODE_REF_BROAD",
            "warning",
            ref.path,
            ref.line,
            f"document-only reference to `{norm}`; prefer an exact section ID",
            symbol=ref.owner_symbol,
        )


def _reciprocal_and_inventory_issues(
    sections: Sequence[SpecSection],
    mappings: Sequence[SpecMapping],
    edges: Sequence[Edge],
    issues: list[Issue],
) -> None:
    # Two distinct key sets, deliberately NOT merged: resolved mapping
    # edges drive CODE_BACKLINK_RECIPROCAL_MISSING, while raw mapping
    # declarations (including ones that failed to resolve) drive
    # SPEC_SECTION_UNMAPPED.
    mapping_targets: dict[tuple[str, str], set[str]] = {}
    backlink_capable: set[tuple[str, str]] = set()
    for edge in edges:
        if edge.kind == "mapping":
            key = (edge.spec_path, edge.section_id)
            mapping_targets.setdefault(key, set()).add(edge.code_path)
            # Only Python files and directory targets can carry backlinks;
            # a section mapped solely to documents (`.md` plan refs) must
            # not demand a reciprocal backlink it cannot have.
            basename = edge.code_path.rstrip("/").rsplit("/", 1)[-1]
            if edge.code_path.endswith(".py") or "." not in basename:
                backlink_capable.add(key)
    backlinked = {
        (edge.spec_path, edge.section_id) for edge in edges if edge.kind == "backlink"
    }
    raw_mapped_keys = {(m.spec_path, m.section_id) for m in mappings}

    for section in sections:
        key = (section.path, section.section_id)
        if key in backlink_capable and key not in backlinked:
            _emit(
                issues,
                "CODE_BACKLINK_RECIPROCAL_MISSING",
                "warning",
                section.path,
                section.line,
                f"section [{section.section_id}] is mapped to code but"
                " no code backlink points to it",
                section_id=section.section_id,
            )
        if key not in raw_mapped_keys:
            _emit(
                issues,
                "SPEC_SECTION_UNMAPPED",
                "info",
                section.path,
                section.line,
                f"section [{section.section_id}] has no implementation mapping",
                section_id=section.section_id,
            )

    def covered_by_mapping(code_path: str, targets: set[str]) -> bool:
        if code_path in targets:
            return True
        # Directory ownership: `weft/core/monitor/` covers files inside it.
        return any(code_path.startswith(target.rstrip("/") + "/") for target in targets)

    for edge in edges:
        if edge.kind != "backlink":
            continue
        key = (edge.spec_path, edge.section_id)
        targets = mapping_targets.get(key)
        if key not in raw_mapped_keys:
            # [SC-11] SPEC_MAPPING_RECIPROCAL_MISSING: the code backlink
            # asserts ownership of a section that declares no implementation
            # mapping at all -- reciprocity is broken at the spec side.
            _emit(
                issues,
                "SPEC_MAPPING_RECIPROCAL_MISSING",
                "warning",
                edge.code_path,
                edge.line,
                f"code backlink cites [{edge.section_id}] but that section"
                " declares no implementation mapping",
                section_id=edge.section_id,
                symbol=edge.code_symbol,
            )
        elif targets is not None and not covered_by_mapping(edge.code_path, targets):
            _emit(
                issues,
                "CODE_REF_UNMAPPED_FROM_SPEC",
                "info",
                edge.code_path,
                edge.line,
                f"code cites [{edge.section_id}] but is not in that"
                " section's implementation mapping",
                section_id=edge.section_id,
                symbol=edge.code_symbol,
            )


def _sort_report_parts(issues: list[Issue], edges: list[Edge]) -> None:
    severity_rank = {"error": 0, "warning": 1, "info": 2}
    issues.sort(
        key=lambda i: (
            severity_rank[i.severity],
            i.path,
            i.line or 0,
            i.code,
            i.message,
        )
    )
    edges.sort(
        key=lambda e: (
            e.spec_path,
            e.section_id,
            e.kind,
            e.code_path,
            e.code_symbol or "",
            e.line,
        )
    )


def resolve(
    *,
    profile: ProfileConfig,
    repo_root: str,
    parsed_specs: Sequence[ParsedSpec],
    parsed_python: Sequence[ParsedPython],
    scan_issues: Sequence[Issue],
    mapping_path_exists: Mapping[str, bool],
    python_symbols: Mapping[str, frozenset[str] | None],
    scan_files: Sequence[str] = (),
) -> Report:
    """Combine parsed records into a trace graph with deterministic issues."""

    issues: list[Issue] = list(scan_issues)
    edges: list[Edge] = []

    sections: list[SpecSection] = [s for spec in parsed_specs for s in spec.sections]
    mappings = [m for spec in parsed_specs for m in spec.mappings]
    refs: list[CodeRef] = [r for parsed in parsed_python for r in parsed.refs]
    issues.extend(i for parsed in parsed_specs for i in parsed.issues)
    issues.extend(i for parsed in parsed_python for i in parsed.issues)

    index = _build_index(parsed_specs)
    _duplicate_section_issues(index, issues)
    _resolve_mappings(
        mappings,
        mapping_path_exists,
        python_symbols,
        scan_files,
        profile.plan_roots,
        issues,
        edges,
    )
    _resolve_code_refs(refs, index, profile, issues, edges)
    _reciprocal_and_inventory_issues(sections, mappings, edges, issues)
    _sort_report_parts(issues, edges)

    return Report(
        profile=profile.name,
        repo_root=repo_root,
        spec_sections=tuple(sections),
        code_refs=tuple(refs),
        spec_mappings=tuple(mappings),
        edges=tuple(edges),
        issues=tuple(issues),
    )


@dataclass(frozen=True, slots=True)
class ScanArtifacts:
    """Suppression inputs gathered during the scan ([EXC-4], [EXC-5]).

    These feed ``backstitch.exclusions.build_suppression_index``; they are
    scan by-products, deliberately not part of the [SC-6] report contract.
    """

    section_meta: dict[tuple[str, str], bool]
    inline_file_ignores: dict[str, frozenset[str]]
    inline_spec_ignores: dict[tuple[str, str], frozenset[str]]
    inline_code_ignores: dict[str, frozenset[str]]
    inline_code_span_ignores: dict[str, tuple[tuple[int, int, frozenset[str]], ...]]
    sections_with_markers: frozenset[tuple[str, str]]
    marker_warnings: tuple[str, ...]


def scan_repository(
    repo_root: Path,
    profile: ProfileConfig,
    exclude_globs: tuple[str, ...] | None = None,
    *,
    allow_unknown_suppression_codes: bool = False,
) -> Report:
    """Scan a target repository and resolve its trace graph.

    Raises ``ScanError`` when the repo root itself is unusable; missing
    configured roots become ``SCAN_ROOT_MISSING`` error findings instead.
    ``exclude_globs`` are scan-boundary skips (CFG §6.7); ``None`` means
    the built-in DEFAULT_EXCLUDES, while an explicit empty tuple excludes
    nothing (`exclude = []` replaces the defaults). The CLI always passes
    the resolved settings value -- the profile carries no exclude state.
    """

    report, _artifacts = scan_repository_with_artifacts(
        repo_root,
        profile,
        exclude_globs,
        allow_unknown_suppression_codes=allow_unknown_suppression_codes,
    )
    return report


def scan_repository_with_artifacts(
    repo_root: Path,
    profile: ProfileConfig,
    exclude_globs: tuple[str, ...] | None = None,
    *,
    allow_unknown_suppression_codes: bool = False,
) -> tuple[Report, ScanArtifacts]:
    """``scan_repository`` plus the suppression inputs the CLI needs."""

    root = repo_root.resolve()
    if not root.is_dir():
        raise ScanError(f"repository root is not a directory: {repo_root}")

    # CFG §6.7/§6.9: exclusion is is_excluded's component-aware match (a
    # bare `venv` excludes the whole subtree at any depth), and the ONLY
    # skip policy -- an explicit `exclude = []` scans everything, so no
    # hard-coded dot-directory rule may sit underneath it.
    active_excludes = DEFAULT_EXCLUDES if exclude_globs is None else exclude_globs
    scan_issues: list[Issue] = []

    def excluded(path: Path) -> bool:
        rel = path.relative_to(root).as_posix()
        return is_excluded(rel, active_excludes)

    def collect(roots: Sequence[str], pattern: str) -> list[Path]:
        files: list[Path] = []
        seen: set[Path] = set()
        for rel_root in roots:
            base = root / rel_root
            if not base.is_dir():
                scan_issues.append(
                    Issue(
                        code="SCAN_ROOT_MISSING",
                        severity="error",
                        path=rel_root,
                        line=None,
                        message=f"configured root `{rel_root}` does not exist",
                    )
                )
                continue
            for path in sorted(base.rglob(pattern)):
                if path.is_file() and not excluded(path) and path not in seen:
                    seen.add(path)
                    files.append(path)
        return files

    parsed_specs: list[ParsedSpec] = []
    parsed_python: list[ParsedPython] = []

    def unreadable(path: Path, exc: Exception) -> None:
        scan_issues.append(
            Issue(
                code="FILE_UNREADABLE",
                severity="error",
                path=path.relative_to(root).as_posix(),
                line=None,
                message=f"could not read file: {exc}",
            )
        )

    for path in collect(profile.spec_roots, "*.md"):
        try:
            parsed_specs.append(
                parse_markdown_spec(
                    path,
                    root,
                    allow_unknown_codes=allow_unknown_suppression_codes,
                )
            )
        except (OSError, UnicodeDecodeError) as exc:
            unreadable(path, exc)
    for path in collect(profile.code_roots, "*.py"):
        try:
            parsed_python.append(
                parse_python_file(
                    path,
                    root,
                    allow_unknown_codes=allow_unknown_suppression_codes,
                )
            )
        except (OSError, UnicodeDecodeError) as exc:
            unreadable(path, exc)

    scan_files = sorted(
        {p.path for p in parsed_specs} | {p.path for p in parsed_python}
    )

    mapping_path_exists: dict[str, bool] = {}
    python_symbols: dict[str, frozenset[str] | None] = {}
    for spec in parsed_specs:
        for mapping in spec.mappings:
            if mapping.target_path is None:
                continue
            target = mapping.target_path
            if target not in mapping_path_exists:
                # Directory ownership (`weft/core/monitor/`) is a valid
                # mapping target, so existence covers files and directories.
                mapping_path_exists[target] = (root / target).exists()
            inventory_target: str | None = None
            if mapping_path_exists[target]:
                inventory_target = target
            else:
                # [SC-4] ladder rung 2: a unique suffix candidate will be
                # the effective path, so its symbol inventory is needed too.
                candidates = ladder_candidates(target, scan_files)
                if len(candidates) == 1:
                    inventory_target = candidates[0]
            if (
                mapping.kind == "path_symbol"
                and inventory_target is not None
                and inventory_target.endswith(".py")
                and inventory_target not in python_symbols
            ):
                python_symbols[inventory_target] = python_symbol_inventory(
                    root / inventory_target
                )

    report = resolve(
        profile=profile,
        repo_root=str(root),
        parsed_specs=parsed_specs,
        parsed_python=parsed_python,
        scan_issues=scan_issues,
        mapping_path_exists=mapping_path_exists,
        python_symbols=python_symbols,
        scan_files=scan_files,
    )

    section_meta: dict[tuple[str, str], bool] = {}
    inline_file_ignores: dict[str, frozenset[str]] = {}
    inline_spec_ignores: dict[tuple[str, str], frozenset[str]] = {}
    sections_with_markers: set[tuple[str, str]] = set()
    marker_warnings: list[str] = []
    for spec in parsed_specs:
        marker_warnings.extend(spec.marker_warnings)
        marked = {section_id for section_id, _, _ in spec.section_markers}
        sections_with_markers.update((spec.path, sid) for sid in marked)
        if spec.file_meta:
            # EXC-4.1: file-level markers apply to all sections "unless a
            # section overrides it" -- marked sections opt out entirely.
            for section in spec.sections:
                if section.section_id not in marked:
                    section_meta[(spec.path, section.section_id)] = True
        if spec.file_ignores:
            inline_file_ignores[spec.path] = spec.file_ignores
        for section_id, is_meta, codes in spec.section_markers:
            if is_meta:
                section_meta[(spec.path, section_id)] = True
            if codes:
                inline_spec_ignores[(spec.path, section_id)] = codes
    inline_code_ignores = {
        p.path: p.module_noqa for p in parsed_python if p.module_noqa
    }
    inline_code_span_ignores = {
        p.path: p.span_noqa for p in parsed_python if p.span_noqa
    }
    marker_warnings.extend(w for p in parsed_python for w in p.noqa_warnings)

    return report, ScanArtifacts(
        section_meta=section_meta,
        inline_file_ignores=inline_file_ignores,
        inline_spec_ignores=inline_spec_ignores,
        inline_code_ignores=inline_code_ignores,
        inline_code_span_ignores=inline_code_span_ignores,
        sections_with_markers=frozenset(sections_with_markers),
        marker_warnings=tuple(marker_warnings),
    )
