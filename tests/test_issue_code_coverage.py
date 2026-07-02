"""[SC-10] contract-coverage gate: every [SC-11] code has a firing proof.

Spec: docs/specs/02-backstitch-core.md [SC-10], [SC-11]

One corpus exercises every deterministic issue code; the parametrized test
fails for any code in ``ISSUE_CODES`` that never fires here, and asserts the
default severity for always-error codes. A declared code with no firing
test is an untested contract and a verification failure (engineering
principle 12).
"""

from __future__ import annotations

import pytest

from backstitch.models import ERROR_SEVERITY_CODES, ISSUE_CODES, Report
from backstitch.profiles import get_profile
from backstitch.resolver import scan_repository

_FILES: dict[str, str | bytes] = {
    # Sections, duplicates, unmapped, planned/exploratory docs.
    "docs/specs/01-a.md": (
        "# A\n\n"
        "_Implementation mapping_:\n\n- `pkg/orphan_block.py`\n\n"  # ownerless
        "## One [AA-1]\n\n_Implementation mapping_:\n\n- `pkg/impl.py`\n\n"
        "## Two [AA-2]\n\n"  # unmapped section
        "## Dup [DD-1]\n\n"
        "## Dup Again [DD-1]\n\n"  # duplicate id
        "## Inexact [AA-3]\n\n_Implementation mapping_:\n\n- `unique_leaf.py`\n\n"
        "## Ambi [AA-4]\n\n_Implementation mapping_:\n\n- `twin.py`\n\n"
        "## MissCode [AA-5]\n\n_Implementation mapping_:\n\n- `pkg/gone.py`\n\n"
        "## MissPlan [AA-6]\n\n_Implementation mapping_:\n\n"
        "- `docs/plans/2099-future.md`\n\n"
        "## NoSym [AA-7]\n\n_Implementation mapping_:\n\n"
        "- `pkg/impl.py::not_there`\n\n"
        "## BareSym [AA-8]\n\n_Implementation mapping_:\n\n- `Runtime.save`\n\n"
        "## MappedElse [AA-9]\n\n_Implementation mapping_:\n\n- `pkg/other.py`\n"
    ),
    "docs/specs/02-planned-p.md": "# P\n\n## Planned [PP-1]\n",
    "docs/specs/03-exploratory-x.md": "# X\n\n## Expl [XX-1]\n",
    "pkg/impl.py": (
        '"""Spec: docs/specs/01-a.md [AA-1]"""\n'
        "\n"
        "\n"
        "def one() -> None:\n"
        '    """Covers docs/specs/01-a.md."""\n'  # broad, document-only
        "\n"
        "\n"
        "def two() -> None:\n"
        '    """Spec: docs/specs/01-a.md [AA-2]"""\n'  # backlink, unmapped
        "\n"
        "\n"
        "def three() -> None:\n"
        '    """Spec: docs/specs/01-a.md [AA-9]"""\n'  # mapped elsewhere
        "\n"
        "\n"
        "def refs() -> None:\n"
        '    """Refs.\n'
        "\n"
        "    Spec: docs/specs/09-gone.md [ZZ-1]\n"  # missing spec file
        "    Spec: docs/specs/01-a.md [ZZ-9]\n"  # missing section
        "    Spec: docs/specs/01-a.md#no-such-anchor\n"  # missing anchor
        "    Spec: docs/specs/02-planned-p.md [PP-1]\n"  # planned ref
        "    Spec: docs/specs/03-exploratory-x.md [XX-1]\n"  # exploratory
        '    """\n'
        "    # [AA-77] known-prefix bare ref, no match\n"
        "    # [DD-1] ambiguous bare ref in a comment\n"
        "    # range: [AA-2]-[AA-1]\n"  # reversed -> unsupported
    ),
    "pkg/other.py": '"""Other owner, no backlink."""\n',
    "pkg/unique/unique_leaf.py": '"""Leaf."""\n',
    "pkg/t1/twin.py": '"""Twin one."""\n',
    "pkg/t2/twin.py": '"""Twin two."""\n',
    "pkg/broken.py": "def broken(:\n",
    "pkg/binary.py": b"\xff\xfe not utf8 \xff",
    "docs/plans/.keep": "",
}

PROFILE = get_profile("backstitch-style-v1").with_overrides(
    spec_roots=("docs/specs",),
    plan_roots=("docs/plans",),
    code_roots=("pkg",),
    planned_spec_globs=("docs/specs/02-planned-*.md",),
    exploratory_spec_globs=("docs/specs/03-exploratory-*.md",),
)


@pytest.fixture(scope="module")
def everything(tmp_path_factory: pytest.TempPathFactory) -> Report:
    root = tmp_path_factory.mktemp("everything_corpus")
    for rel, content in _FILES.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")
    return scan_repository(root, PROFILE)


@pytest.fixture(scope="module")
def missing_root_report(
    tmp_path_factory: pytest.TempPathFactory,
) -> Report:
    root = tmp_path_factory.mktemp("missing_root_corpus")
    (root / "pkg").mkdir()
    return scan_repository(root, PROFILE)


@pytest.mark.parametrize("code", sorted(ISSUE_CODES))
def test_every_issue_code_fires(
    code: str, everything: Report, missing_root_report: Report
) -> None:
    fired = [i for i in everything.issues if i.code == code]
    if code == "SCAN_ROOT_MISSING":
        fired = [i for i in missing_root_report.issues if i.code == code]
    assert fired, f"{code} never fires: untested contract ([SC-10])"
    if code in ERROR_SEVERITY_CODES:
        assert all(i.severity == "error" for i in fired), code


def test_context_dependent_severities_fire_both_ways(
    everything: Report,
) -> None:
    # [SC-11] severity gate for the two error/warning codes.
    mapping_missing = {
        i.section_id: i.severity
        for i in everything.issues
        if i.code == "MAPPING_PATH_MISSING"
    }
    assert mapping_missing["AA-5"] == "error"
    assert mapping_missing["AA-6"] == "warning"
    ambiguous = [i for i in everything.issues if i.code == "SPEC_SECTION_AMBIGUOUS"]
    assert {i.severity for i in ambiguous} == {"warning"}
