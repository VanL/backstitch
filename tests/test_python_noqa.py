"""[EXC-5]/[EXC-9]: Python inline noqa — statement scope containment.

Spec: docs/specs/04-backstitch-traceability-exclusions.md [EXC-5], [EXC-9]

The file-wide bleed of a comment-form directive is the specific regression
this suite exists to catch: two findings of the same suppressible code in
one file, noqa on only one statement, exactly one suppressed.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent / "fixtures/noqa_scope_project"


def _check_json(*extra: str) -> dict:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "backstitch",
            "check",
            "--repo-root",
            str(FIXTURE),
            "--spec-root",
            "docs/specs",
            "--plan-root",
            "docs/plans",
            "--code-root",
            "pkg",
            "--format",
            "json",
            *extra,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert "Traceback" not in result.stderr, result.stderr
    return json.loads(result.stdout)


def test_comment_noqa_suppresses_next_statement_only() -> None:
    # The fixture has two SPEC_MAPPING_RECIPROCAL_MISSING findings (two
    # functions backlink an unmapped section); the noqa comment precedes
    # only the second function.
    data = _check_json()
    remaining = [
        i
        for i in data["issues"]
        if i["code"] == "SPEC_MAPPING_RECIPROCAL_MISSING"
    ]
    assert len(remaining) == 1
    assert remaining[0]["symbol"] == "uncovered"


def test_suppressed_finding_is_recoverable_with_show_suppressions() -> None:
    data = _check_json("--show-suppressions")
    suppressed = data.get("suppressed_issues", [])
    codes = {(s["code"], s["reason"]) for s in suppressed}
    assert ("SPEC_MAPPING_RECIPROCAL_MISSING", "inline_code") in codes


def test_module_docstring_noqa_is_module_scoped() -> None:
    # pkg/moddoc.py declares noqa in its module docstring; both of its
    # findings of that code are suppressed.
    data = _check_json()
    assert not any(
        i["code"] == "CODE_REF_BARE_UNRESOLVED" and i["path"] == "pkg/moddoc.py"
        for i in data["issues"]
    )
