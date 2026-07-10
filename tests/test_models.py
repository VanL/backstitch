"""Model contracts: the issue-code inventory mirrors the [SC-11] table.

Spec: docs/specs/02-backstitch-core.md [SC-6], [SC-11]

The inventory test parses the spec's own markdown table so the spec and the
code cannot drift silently (engineering principle 12: enumerable contracts
get executable gates).
"""

from __future__ import annotations

import re
from pathlib import Path

from backstitch.diagnostics import default_registry
from backstitch.models import ERROR_SEVERITY_CODES, ISSUE_CODES, Issue, Report

SPEC = Path(__file__).resolve().parent.parent / "docs/specs/02-backstitch-core.md"

_SC11_ROW_RE = re.compile(
    r"^\| `([A-Z_]+)` \| `([A-Z0-9]+)` \|"
    r" (error|warning|info|error/warning) \|"
)
_SC15_STATUS_ROW_RE = re.compile(
    r"^\| `([A-Z_]+)` \| `([A-Z0-9]+)` \|"
    r" (implemented|reserved|deprecated|redirected) \|"
)


def _implemented_spec_rows() -> dict[str, tuple[str, str | None]]:
    text = SPEC.read_text(encoding="utf-8")
    section = text.split("## 11. Diagnostic Codes And Default Policy [SC-11]", 1)[1]
    rows: dict[str, tuple[str, str | None]] = {}
    for line in section.splitlines():
        match = _SC11_ROW_RE.match(line)
        if match:
            rows[match.group(1)] = (match.group(2), match.group(3))
        elif line.startswith("## ") and rows:
            break
    sc15 = text.split("## 15. Diagnostic Registry And Policy [SC-15]", 1)[1]
    for line in sc15.splitlines():
        match = _SC15_STATUS_ROW_RE.match(line)
        if match:
            code, short_code, status = match.groups()
            if status == "implemented":
                prior = rows.get(code)
                rows[code] = (short_code, prior[1] if prior is not None else None)
            else:
                rows.pop(code, None)
        elif line.startswith("## ") and rows:
            break
    return rows


def test_issue_codes_match_spec_tables() -> None:
    rows = _implemented_spec_rows()
    assert rows, "could not parse implemented diagnostic tables from the spec"
    assert ISSUE_CODES == frozenset(rows)
    registry = default_registry()
    for code, (short_code, _level) in rows.items():
        assert registry.require(code).short_code == short_code


def test_error_severity_codes_are_always_error_only() -> None:
    rows = _implemented_spec_rows()
    always_error = frozenset(
        code for code, (_short, level) in rows.items() if level == "error"
    )
    assert ERROR_SEVERITY_CODES == always_error
    # Context-dependent codes must NOT be in the always-error set.
    assert "SPEC_SECTION_AMBIGUOUS" not in ERROR_SEVERITY_CODES
    assert "MAPPING_PATH_MISSING" not in ERROR_SEVERITY_CODES


def test_report_summary_counts_by_severity() -> None:
    issues = (
        Issue(
            code="SPEC_FILE_MISSING", severity="error", path="a.py", line=1, message="x"
        ),
        Issue(
            code="CODE_REF_BROAD", severity="warning", path="a.py", line=2, message="y"
        ),
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
    assert issues[0].short_code == "BSS001"
    assert issues[0].default_severity == "error"
    assert set(report.to_dict()) == {
        "profile",
        "repo_root",
        "summary",
        "spec_sections",
        "code_refs",
        "spec_mappings",
        "edges",
        "invariants",
        "binds",
        "issues",
    }
