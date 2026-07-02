"""Behavior-freeze contract for the deterministic core.

Spec: docs/specs/02-backstitch-core.md [SC-4], [SC-6], [SC-10]

The fixture corpus is a declared grammar contract; the golden pins resolver
classification behavior so contract changes are reviewed, not discovered.
Regenerate deliberately after an intentional classification change:

    BACKSTITCH_UPDATE_GOLDEN=1 uv run pytest tests/test_behavior_freeze.py

then hand-review the golden diff -- every hunk must trace to a named
adaptation or it is a regression. Messages are asserted structurally via
the golden's fields; no verbatim message pins live in this module
(testing-patterns Pattern 5).
"""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path

import pytest

from backstitch.models import Report
from backstitch.profiles import get_profile
from backstitch.resolver import scan_repository

FIXTURES = Path(__file__).resolve().parent / "fixtures"
GOLDEN = FIXTURES / "traceability_project.expected.json"

BROKEN_PROFILE = get_profile("backstitch-style-v1").with_overrides(
    spec_roots=("docs/specifications",),
    code_roots=("src", "tests"),
    planned_spec_globs=("docs/specifications/*A-*.md",),
)


@pytest.fixture(scope="module")
def broken() -> Report:
    return scan_repository(FIXTURES / "traceability_project", BROKEN_PROFILE)


def test_broken_fixture_summary_and_histogram_are_frozen(
    broken: Report,
) -> None:
    assert broken.summary() == {
        "spec_sections": 13,
        "code_refs": 19,
        "spec_mappings": 12,
        "errors": 2,
        "warnings": 21,
        "infos": 11,
    }
    assert dict(Counter(i.code for i in broken.issues)) == {
        "CODE_BACKLINK_RECIPROCAL_MISSING": 4,
        "CODE_REF_BARE_UNRESOLVED": 1,
        "CODE_REF_BROAD": 1,
        "CODE_REF_PLANNED_SPEC": 1,
        "CODE_REF_UNMAPPED_FROM_SPEC": 4,
        "MAPPING_PATH_MISSING": 1,
        "MAPPING_SYMBOL_UNRESOLVED": 4,
        "REF_RANGE_UNSUPPORTED": 1,
        "SPEC_MAPPING_RECIPROCAL_MISSING": 8,
        "SPEC_SECTION_AMBIGUOUS": 1,
        "SPEC_SECTION_DUPLICATE": 1,
        "SPEC_SECTION_UNMAPPED": 7,
    }


def test_broken_fixture_full_report_matches_golden(broken: Report) -> None:
    actual = json.loads(json.dumps(broken.to_dict()))
    actual.pop("repo_root")
    if os.environ.get("BACKSTITCH_UPDATE_GOLDEN"):
        regenerated = dict(actual)
        regenerated["repo_root"] = "<regenerated>"
        GOLDEN.write_text(json.dumps(regenerated, indent=2) + "\n", encoding="utf-8")
        pytest.skip("golden regenerated; rerun without the env var")
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    expected.pop("repo_root")
    assert actual == expected
