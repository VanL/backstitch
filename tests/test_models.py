"""Model contracts: the issue-code inventory mirrors the [SC-11] table.

Spec: docs/specs/02-backstitch-core.md [SC-6], [SC-11]

The inventory test parses the spec's own markdown table so the spec and the
code cannot drift silently (engineering principle 12: enumerable contracts
get executable gates).
"""

from __future__ import annotations

import re
from pathlib import Path

from backstitch.models import ERROR_SEVERITY_CODES, ISSUE_CODES, Issue, Report

SPEC = Path(__file__).resolve().parent.parent / "docs/specs/02-backstitch-core.md"

_ROW_RE = re.compile(r"^\| `([A-Z_]+)` \| (error|warning|info|error/warning) \|")


def _sc11_rows() -> dict[str, str]:
    text = SPEC.read_text(encoding="utf-8")
    section = text.split("[SC-11]", 1)[1]
    rows: dict[str, str] = {}
    for line in section.splitlines():
        match = _ROW_RE.match(line)
        if match:
            rows[match.group(1)] = match.group(2)
        elif line.startswith("## ") and rows:
            break
    return rows


def test_issue_codes_match_sc11_table() -> None:
    rows = _sc11_rows()
    assert rows, "could not parse the [SC-11] table from the spec"
    assert ISSUE_CODES == frozenset(rows)


def test_error_severity_codes_are_always_error_only() -> None:
    rows = _sc11_rows()
    always_error = frozenset(code for code, sev in rows.items() if sev == "error")
    assert ERROR_SEVERITY_CODES == always_error
    # Context-dependent codes must NOT be in the always-error set.
    assert "SPEC_SECTION_AMBIGUOUS" not in ERROR_SEVERITY_CODES
    assert "MAPPING_PATH_MISSING" not in ERROR_SEVERITY_CODES


def test_report_summary_counts_by_severity() -> None:
    issues = (
        Issue(code="SPEC_FILE_MISSING", severity="error", path="a.py", line=1, message="x"),
        Issue(code="CODE_REF_BROAD", severity="warning", path="a.py", line=2, message="y"),
    )
    report = Report(
        profile="backstitch-style-v1",
        repo_root="/tmp/x",
        spec_sections=(),
        code_refs=(),
        spec_mappings=(),
        edges=(),
        issues=issues,
    )
    summary = report.summary()
    assert summary["errors"] == 1
    assert summary["warnings"] == 1
    assert summary["infos"] == 0
    assert set(report.to_dict()) == {
        "profile",
        "repo_root",
        "summary",
        "spec_sections",
        "code_refs",
        "spec_mappings",
        "edges",
        "issues",
    }
