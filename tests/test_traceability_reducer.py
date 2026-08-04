"""Table-driven transitions for the CommonMark traceability reducer.

Spec: docs/specs/02-backstitch-core.md [SC-4], [SC-10], [SC-17]
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from backstitch.markdown_specs import parse_markdown_spec_bytes


@dataclass(frozen=True, slots=True)
class _TransitionCase:
    name: str
    source: str
    sections: tuple[str, ...]
    mappings: tuple[tuple[str, str], ...] = ()
    markers: tuple[tuple[str, bool, frozenset[str]], ...] = ()
    skips: tuple[tuple[str, str], ...] = ()
    issue_codes: tuple[str, ...] = ()
    diagnostic_codes: tuple[str, ...] = ()


_TRANSITIONS = (
    _TransitionCase(
        name="heading opens directive window",
        source="## Contract [T-1]\n<!-- backstitch: meta -->\n",
        sections=("T-1",),
        markers=(("T-1", True, frozenset()),),
    ),
    _TransitionCase(
        name="body paragraph closes directive window",
        source=(
            "## Contract [T-1]\n\nBody.\n\n"
            "<!-- backstitch: ignore SPEC_SECTION_UNMAPPED -->\n"
        ),
        sections=("T-1",),
        diagnostic_codes=("SUPPRESSION_INVALID_SYNTAX",),
    ),
    _TransitionCase(
        name="fence closes directive window",
        source=(
            "## Contract [T-1]\n\n```text\nexample\n```\n<!-- backstitch: meta -->\n"
        ),
        sections=("T-1",),
        diagnostic_codes=("SUPPRESSION_INVALID_SYNTAX",),
    ),
    _TransitionCase(
        name="indented code closes directive window",
        source=("## Contract [T-1]\n\n    example\n<!-- backstitch: meta -->\n"),
        sections=("T-1",),
        diagnostic_codes=("SUPPRESSION_INVALID_SYNTAX",),
    ),
    _TransitionCase(
        name="ordered list closes directive window",
        source=("## Contract [T-1]\n\n1. body\n<!-- backstitch: meta -->\n"),
        sections=("T-1",),
        diagnostic_codes=("SUPPRESSION_INVALID_SYNTAX",),
    ),
    _TransitionCase(
        name="ordinary bullet closes directive window",
        source=("## Contract [T-1]\n\n- body\n<!-- backstitch: meta -->\n"),
        sections=("T-1",),
        diagnostic_codes=("SUPPRESSION_INVALID_SYNTAX",),
    ),
    _TransitionCase(
        name="blockquote closes directive window",
        source=("## Contract [T-1]\n\n> body\n<!-- backstitch: meta -->\n"),
        sections=("T-1",),
        diagnostic_codes=("SUPPRESSION_INVALID_SYNTAX",),
    ),
    _TransitionCase(
        name="ordinary HTML closes directive window",
        source=("## Contract [T-1]\n\n<div>body</div>\n\n<!-- backstitch: meta -->\n"),
        sections=("T-1",),
        diagnostic_codes=("SUPPRESSION_INVALID_SYNTAX",),
    ),
    _TransitionCase(
        name="heading without ID closes directive window",
        source=("## Contract [T-1]\n\n## Plain heading\n<!-- backstitch: meta -->\n"),
        sections=("T-1",),
        diagnostic_codes=("SUPPRESSION_INVALID_SYNTAX",),
    ),
    _TransitionCase(
        name="invalid heading closes directive window",
        source=("## Contract [T-1]\n\n## Bad [not an id]\n<!-- backstitch: meta -->\n"),
        sections=("T-1",),
        issue_codes=("SPEC_SECTION_HEADING_INVALID",),
        diagnostic_codes=("SUPPRESSION_INVALID_SYNTAX",),
    ),
    _TransitionCase(
        name="reserved skip paragraph remains in directive window",
        source=(
            "## Contract [T-1]\n\n"
            '_Traceability: skip-obligation [T-1] "External owner."_\n'
        ),
        sections=("T-1",),
        skips=(("docs/specs/01-transition.md#T-1", "traceability"),),
    ),
    _TransitionCase(
        name="body invalidates reserved skip and closes directive window",
        source=(
            "## Contract [T-1]\n\n"
            '_Traceability: skip-obligation [T-1] "External owner."_\n'
            "body\n<!-- backstitch: meta -->\n"
        ),
        sections=("T-1",),
        diagnostic_codes=(
            "SUPPRESSION_INVALID_SYNTAX",
            "SUPPRESSION_INVALID_SYNTAX",
        ),
    ),
    _TransitionCase(
        name="mapping list attaches to heading owner",
        source=("## Contract [T-1]\n\n_Implementation mapping_:\n\n- `pkg/owner.py`\n"),
        sections=("T-1",),
        mappings=(("T-1", "pkg/owner.py"),),
    ),
    _TransitionCase(
        name="mapping bullet changes mapping owner",
        source=(
            "## Contract [T-1]\n\n_Implementation mapping_:\n\n"
            "- [T-1.1] Child — `pkg/child.py`\n"
        ),
        sections=("T-1", "T-1.1"),
        mappings=(("T-1.1", "pkg/child.py"),),
    ),
    _TransitionCase(
        name="sibling heading changes mapping owner",
        source=(
            "## First [T-1]\n\n## Second [T-2]\n\n"
            "_Implementation mapping_: `pkg/second.py`\n"
        ),
        sections=("T-1", "T-2"),
        mappings=(("T-2", "pkg/second.py"),),
    ),
    _TransitionCase(
        name="invariant list item opens its directive window",
        source=(
            "## Contract [T-1]\n\n- **INV-1**: Stable output.\n"
            "<!-- backstitch: meta -->\n"
        ),
        sections=("T-1", "INV-1"),
        markers=(("INV-1", True, frozenset()),),
    ),
)


@pytest.mark.parametrize("case", _TRANSITIONS, ids=lambda case: case.name)
def test_traceability_reducer_transition_table(case: _TransitionCase) -> None:
    parsed = parse_markdown_spec_bytes(
        case.source.encode("utf-8"),
        "docs/specs/01-transition.md",
    )

    assert tuple(section.section_id for section in parsed.sections) == case.sections
    assert (
        tuple((mapping.section_id, mapping.target) for mapping in parsed.mappings)
        == case.mappings
    )
    assert parsed.section_markers == case.markers
    assert (
        tuple((skip.obligation_id, skip.form) for skip in parsed.obligation_skips)
        == case.skips
    )
    assert tuple(item.code for item in parsed.issues) == case.issue_codes
    assert tuple(item.code for item in parsed.marker_diagnostics) == (
        case.diagnostic_codes
    )
