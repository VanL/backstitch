"""Path-resolution ladder contract [SC-4]: exact -> inexact -> ambiguous -> missing.

Spec: docs/specs/02-backstitch-core.md [SC-4], [SC-11]
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backstitch.models import Report
from backstitch.profiles import get_profile
from backstitch.resolver import scan_repository

FIXTURE = Path(__file__).resolve().parent / "fixtures/path_ladder_project"

PROFILE = get_profile("backstitch-style-v1").with_overrides(
    spec_roots=("docs/specs",),
    plan_roots=("docs/plans",),
    code_roots=("pkg",),
)


@pytest.fixture(scope="module")
def ladder() -> Report:
    return scan_repository(FIXTURE, PROFILE)


def _mapping_edges(report: Report, section_id: str) -> list[str]:
    return [
        e.code_path
        for e in report.edges
        if e.kind == "mapping" and e.section_id == section_id
    ]


def test_ladder_exact_path_resolves_silently(ladder: Report) -> None:
    assert _mapping_edges(ladder, "LAD-1") == ["pkg/inner/unique.py"]
    assert not any(
        i.section_id == "LAD-1"
        and i.code in {"MAPPING_PATH_INEXACT", "MAPPING_PATH_MISSING"}
        for i in ladder.issues
    )


def test_ladder_unique_suffix_resolves_with_inexact_warning(
    ladder: Report,
) -> None:
    assert _mapping_edges(ladder, "LAD-2") == ["pkg/inner/unique.py"]
    inexact = [i for i in ladder.issues if i.code == "MAPPING_PATH_INEXACT"]
    assert len(inexact) == 1
    assert inexact[0].severity == "warning"
    assert inexact[0].section_id == "LAD-2"
    assert "pkg/inner/unique.py" in inexact[0].message


def test_ladder_multiple_candidates_ambiguous_error_no_edge(
    ladder: Report,
) -> None:
    """Tests-invariant: [INV.RES.2]"""

    assert _mapping_edges(ladder, "LAD-3") == []
    ambiguous = [i for i in ladder.issues if i.code == "TARGET_PATH_AMBIGUOUS"]
    assert len(ambiguous) == 1
    assert ambiguous[0].severity == "error"
    assert ambiguous[0].section_id == "LAD-3"


def test_ladder_missing_code_path_is_error(ladder: Report) -> None:
    missing = {
        i.section_id: i for i in ladder.issues if i.code == "MAPPING_PATH_MISSING"
    }
    assert missing["LAD-4"].severity == "error"


def test_ladder_missing_plan_md_is_warning(ladder: Report) -> None:
    missing = {
        i.section_id: i for i in ladder.issues if i.code == "MAPPING_PATH_MISSING"
    }
    assert missing["LAD-5"].severity == "warning"
