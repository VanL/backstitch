"""Shared section-ID grammar for `backstitch-style-v1`.

Spec: docs/specs/02-backstitch-core.md [SC-4]

A section ID starts with an uppercase letter and may contain uppercase
letters, lowercase suffixes, digits, `-`, and `.`, and MUST contain at least
one digit somewhere in the token (the digit may appear anywhere, not only
after a `-`/`.` separator -- e.g. `A1` matches). Examples: `MF-5`,
`CLI-1.1.1`, `OBS.13.10`, `SB-0.4a`, `DOM-4`, `MANAGER.12a`.

The governing docs do not explicitly require a digit, but every documented
valid example contains at least one digit, and real spec prose contains
glossary-style bullets such as `- **Task**: ...` and `- **Manager**: ...`
that satisfy a digit-free reading of the grammar but are clearly not section
IDs. Requiring at least one digit excludes those false positives while still
accepting every documented example.

Both `backstitch/markdown_specs.py` (spec-side parsing) and
`backstitch/python_refs.py` (code-side parsing) import `SECTION_ID` from
this module rather than each defining their own copy of the regex literal,
so the grammar rule lives in exactly one place.

This module is part of backstitch's deterministic core: it must never
import or invoke `llm`, and never touches the network.
"""

from __future__ import annotations

import re

SECTION_ID = r"[A-Z][A-Za-z0-9.\-]*[0-9][A-Za-z0-9]*"
"""Regex fragment (no anchors) matching one section ID token, unbracketed."""

SECTION_ID_RE = re.compile(rf"^{SECTION_ID}$")
"""Fully-anchored compiled pattern for validating a standalone ID string."""


def is_valid_section_id(candidate: str) -> bool:
    """Return True if `candidate` is a syntactically valid section ID.

    This checks the bare token -- a stem plus digits, with no surrounding
    brackets -- not a bracketed marker (brackets are how a reference is
    written in prose/code, e.g. ``[ID]``; they are never part of the ID).
    """

    return bool(SECTION_ID_RE.match(candidate))


__all__ = ["SECTION_ID", "SECTION_ID_RE", "is_valid_section_id"]
