"""Markdown spec parsing for the backstitch-style-v1 grammar.

Spec: docs/specs/02-backstitch-core.md [SC-4]
Grammar: docs/implementation/04-backstitch-style-traceability.md

Line-based parsing with compiled regexes; no Markdown AST dependency.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from backstitch.exclusions import parse_traceability_marker_line
from backstitch.grammar import SECTION_ID
from backstitch.models import Issue, MappingKind, SpecMapping, SpecSection

_HEADING_RE = re.compile(r"^(#{1,6})\s+(?P<text>.+?)\s*$")
_HEADING_ID_RE = re.compile(
    rf"^(#{{1,6}})\s+(?P<title>.+?)\s*\[(?P<id>{SECTION_ID})\]\s*$"
)
_INVARIANT_RE = re.compile(
    rf"^\s*[-*]\s+\*\*(?P<id>{SECTION_ID})\*\*\s*:\s*(?P<title>.*)$"
)
_MAPPING_MARKER_RE = re.compile(
    r"^\s*_Implementation mapping[^_]*_\s*:\s*(?P<rest>.*)$"
)
_BULLET_RE = re.compile(r"^\s*[-*]\s+")
# `- [MA-1.1] Spawn queue consumption — ...` inside a mapping block defines
# a subsection AND owns the mapping tokens on its line (observed Weft form).
_BULLET_DEF_RE = re.compile(
    rf"^\s*[-*]\s+\[(?P<id>{SECTION_ID})\]\s+(?P<title>\S.*)$"
)
_BACKTICK_TOKEN_RE = re.compile(r"`(?P<token>[^`]+)`")
_ANCHOR_STRIP_RE = re.compile(r"[^\w\s-]", re.UNICODE)


@dataclass(frozen=True, slots=True)
class ParsedSpec:
    """Parse result for one Markdown spec file.

    Traceability markers ([EXC-4]) ride along: ``file_meta``/``file_ignores``
    from the pre-heading preamble, ``section_markers`` as
    ``(section_id, is_meta, ignore_codes)`` for markers following a section
    definition.
    """

    path: str
    sections: tuple[SpecSection, ...]
    mappings: tuple[SpecMapping, ...]
    anchors: tuple[str, ...]
    issues: tuple[Issue, ...] = ()
    file_meta: bool = False
    file_ignores: frozenset[str] = frozenset()
    section_markers: tuple[tuple[str, bool, frozenset[str]], ...] = ()
    marker_warnings: tuple[str, ...] = ()


def github_anchor(heading_text: str, seen: dict[str, int]) -> str:
    """Return the GitHub-style anchor for a heading, deduplicated per file.

    GitHub replaces each space with a hyphen after stripping punctuation, so
    `Tasks & Queues` becomes `tasks--queues`; whitespace runs must not
    collapse.
    """

    base = _ANCHOR_STRIP_RE.sub("", heading_text.lower()).strip()
    base = base.replace(" ", "-")
    count = seen.get(base, 0)
    seen[base] = count + 1
    return base if count == 0 else f"{base}-{count}"


def classify_mapping_token(token: str) -> tuple[MappingKind, str | None, str | None]:
    """Classify a backticked mapping token as path, path::symbol, or symbol."""

    if "::" in token:
        path, _, symbol = token.partition("::")
        return "path_symbol", path, symbol.removesuffix("()")
    # Dotted tokens like `Runtime.save` are symbols, not files: a token
    # without a slash counts as a path only when it ends in a known file
    # extension. Trailing slashes mark directory ownership and stay paths.
    if "/" in token or re.search(
        r"\.(py|md|txt|toml|yaml|yml|json|cfg|ini|rst|sh|bash|js|jsx|ts|tsx"
        r"|sql|c|h|cpp|hpp|cc|rs|go|rb|java|kt|css|html|xml|proto|lock)$",
        token,
    ):
        return "path", token, None
    return "symbol", None, token.removesuffix("()")


def parse_markdown_spec(
    file_path: Path,
    repo_root: Path,
    *,
    allow_unknown_codes: bool = False,
) -> ParsedSpec:
    """Parse one spec file into sections, mappings, and anchor targets."""

    rel_path = file_path.resolve().relative_to(repo_root.resolve()).as_posix()
    lines = file_path.read_text(encoding="utf-8").splitlines()

    sections: list[SpecSection] = []
    mappings: list[SpecMapping] = []
    anchors: list[str] = []
    issues: list[Issue] = []
    anchor_seen: dict[str, int] = {}
    file_meta = False
    file_ignores: set[str] = set()
    section_markers: dict[str, tuple[bool, set[str]]] = {}
    marker_warnings: list[str] = []

    # Mapping blocks attach to the nearest preceding heading section.
    # Invariant bullets define sections but never own mapping blocks: a
    # mapping after a bullet group documents the heading's ownership, not
    # the last bullet's.
    current_heading_section: SpecSection | None = None
    # Mapping-block state machine: "idle" outside a block, "block" while the
    # marker paragraph or a following bullet list may still continue, and
    # "gap" right after a blank line inside a block (only a bullet may
    # continue the block from a gap).
    state = "idle"
    block_section: SpecSection | None = None

    def emit_tokens(line_text: str, line_no: int) -> None:
        if block_section is None:
            return
        for match in _BACKTICK_TOKEN_RE.finditer(line_text):
            token = match.group("token")
            kind, target_path, target_symbol = classify_mapping_token(token)
            mappings.append(
                SpecMapping(
                    spec_path=rel_path,
                    section_id=block_section.section_id,
                    line=line_no,
                    target=token,
                    kind=kind,
                    target_path=target_path,
                    target_symbol=target_symbol,
                )
            )

    def bullet_definition(text: str, text_line: int) -> None:
        nonlocal block_section
        bullet_def = _BULLET_DEF_RE.match(text)
        if bullet_def is None:
            return
        title = bullet_def.group("title").split(" — ")[0].strip()
        section = SpecSection(
            path=rel_path,
            section_id=bullet_def.group("id"),
            title=title,
            line=text_line,
            anchor=None,
            kind="bullet",
        )
        sections.append(section)
        block_section = section

    # Fenced blocks open with ``` or ~~~ and close only on the same marker.
    fence_marker: str | None = None
    for line_no, line in enumerate(lines, start=1):
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            fence_chars = stripped[:3]
            if fence_marker is None:
                fence_marker = fence_chars
            elif fence_marker == fence_chars:
                fence_marker = None
            continue
        if fence_marker is not None:
            continue
        # [EXC-4] traceability markers: file preamble before the first
        # section, section-scoped after one; fenced content never counts.
        is_meta, marker_codes, warnings = parse_traceability_marker_line(
            line,
            allow_unknown=allow_unknown_codes,
            location=f"{rel_path}:{line_no}",
        )
        marker_warnings.extend(warnings)
        if is_meta or marker_codes:
            if not sections:
                file_meta = file_meta or is_meta
                file_ignores.update(marker_codes if not is_meta else ())
            else:
                target = sections[-1].section_id
                meta_flag, codes = section_markers.setdefault(
                    target, (False, set())
                )
                section_markers[target] = (
                    meta_flag or is_meta,
                    codes | (marker_codes if not is_meta else set()),
                )
            continue
        heading = _HEADING_RE.match(line)
        if heading:
            state = "idle"
            block_section = None
            anchors.append(github_anchor(heading.group("text"), anchor_seen))
            with_id = _HEADING_ID_RE.match(line)
            if with_id:
                section = SpecSection(
                    path=rel_path,
                    section_id=with_id.group("id"),
                    title=with_id.group("title"),
                    line=line_no,
                    anchor=anchors[-1],
                    kind="heading",
                )
                sections.append(section)
                current_heading_section = section
            else:
                # An ID-less heading starts a region no section owns;
                # mapping blocks under it must not attach to the previous
                # ID-bearing section.
                current_heading_section = None
            continue

        marker = _MAPPING_MARKER_RE.match(line)
        if marker:
            state = "block"
            block_section = current_heading_section
            if block_section is None:
                issues.append(
                    Issue(
                        code="MAPPING_BLOCK_OWNERLESS",
                        severity="warning",
                        path=rel_path,
                        line=line_no,
                        message=(
                            "implementation mapping block has no preceding"
                            " ID-bearing heading; its tokens are ignored"
                        ),
                    )
                )
            emit_tokens(marker.group("rest"), line_no)
            continue

        invariant = _INVARIANT_RE.match(line)
        if invariant:
            state = "idle"
            block_section = None
            section = SpecSection(
                path=rel_path,
                section_id=invariant.group("id"),
                title=invariant.group("title").strip(),
                line=line_no,
                anchor=None,
                kind="invariant",
            )
            sections.append(section)
            continue

        if state == "block":
            if not line.strip():
                state = "gap"
            else:
                bullet_definition(line, line_no)
                emit_tokens(line, line_no)
            continue

        if state == "gap":
            if not line.strip():
                continue
            if _BULLET_RE.match(line):
                state = "block"
                bullet_definition(line, line_no)
                emit_tokens(line, line_no)
            else:
                state = "idle"
                block_section = None
            continue

    return ParsedSpec(
        path=rel_path,
        sections=tuple(sections),
        mappings=tuple(mappings),
        anchors=tuple(anchors),
        issues=tuple(issues),
        file_meta=file_meta,
        file_ignores=frozenset(file_ignores),
        section_markers=tuple(
            (section_id, meta_flag, frozenset(codes))
            for section_id, (meta_flag, codes) in sorted(section_markers.items())
        ),
        marker_warnings=tuple(marker_warnings),
    )
