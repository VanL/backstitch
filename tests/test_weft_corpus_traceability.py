"""External Weft corpus gate: known debt pinned by structured signatures.

Spec: docs/specs/02-backstitch-core.md [SC-10], [SC-12]

Debt is pinned as ``(code, path, section_id)`` signatures plus an EXACT
total count, so new errors and silently disappearing debt both fail — the
gate exists to catch change, not to force Weft's cleanup. Assertions use
structured JSON fields only; messages are never parsed (Pattern 5).
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from backstitch.target_roots import discover_weft

WEFT = discover_weft()

pytestmark = pytest.mark.skipif(
    WEFT is None, reason="Weft checkout not found (set BACKSTITCH_WEFT_ROOT)"
)

# Unique (code, path, section_id) error signatures observed 2026-07-02.
# SPEC_SECTION_AMBIGUOUS entries are errors under the reconciled [SC-11]
# context rule (docstring backlinks to Weft's duplicated section IDs).
KNOWN_WEFT_DEBT = {
    (
        "MAPPING_PATH_MISSING",
        "docs/specifications/03-Manager_Architecture.md",
        "MA-1.6a",
    ),
    ("REF_RANGE_UNSUPPORTED", "weft/core/resource_monitor.py", None),
    ("SPEC_ANCHOR_MISSING", "weft/core/tasks/consumer.py", None),
    ("SPEC_SECTION_AMBIGUOUS", "weft/commands/tasks.py", "CLI-1.2"),
    ("SPEC_SECTION_AMBIGUOUS", "weft/core/targets.py", "TS-1"),
    ("SPEC_SECTION_AMBIGUOUS", "weft/core/taskspec/model.py", "TS-0"),
    ("SPEC_SECTION_AMBIGUOUS", "weft/core/taskspec/model.py", "TS-1"),
    ("SPEC_SECTION_MISSING", "weft/commands/run.py", "MF-1"),
    ("SPEC_SECTION_MISSING", "weft/commands/types.py", "CLI-1"),
}
KNOWN_WEFT_ERROR_TOTAL = 32


@pytest.mark.integration
def test_weft_corpus_error_debt_is_exactly_the_known_set() -> None:
    assert WEFT is not None
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "backstitch",
            "check",
            "--repo-root",
            str(WEFT),
            "--no-config",
            "--spec-root",
            "docs/specifications",
            "--plan-root",
            "docs/plans",
            "--code-root",
            "weft",
            "--code-root",
            "tests",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert "Traceback" not in result.stderr, result.stderr
    data = json.loads(result.stdout)
    errors = [
        (i["code"], i["path"], i["section_id"])
        for i in data["issues"]
        if i["severity"] == "error"
    ]
    # Both directions fail: a new signature is a parser/corpus regression; a
    # vanished signature means debt was resolved and the baseline must be
    # deliberately updated.
    assert set(errors) == KNOWN_WEFT_DEBT
    assert len(errors) == KNOWN_WEFT_ERROR_TOTAL
    # Corpus sanity: the scan really covered Weft.
    assert data["summary"]["spec_sections"] > 300
