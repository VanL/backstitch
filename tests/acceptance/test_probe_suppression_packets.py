"""Black-box suppression obligation and mixed-packet acceptance probes."""

from __future__ import annotations

import json
from pathlib import Path

from tests.acceptance.conftest import run_cli


def test_probe_cli_emits_mixed_current_packets_without_provider_work(
    tmp_path: Path,
) -> None:
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "docs/specs/01-core.md").write_bytes(
        b"_Implementation mapping_:\r\n"
        b"\r\n"
        b"- `pkg/ownerless.py`\r\n"
        b"\r\n"
        b"## Contract [SUPTEST-1]\r\n"
        b"\r\n"
        b'_Traceability: suppression-declaration [SUP-1] "The ownerless '
        b'example is retained to exercise suppression governance."_\r\n'
        b"\r\n"
        b"_Implementation mapping_:\r\n"
        b"\r\n"
        b"- `pkg/core.py::run`\r\n"
    )
    (tmp_path / "pkg/core.py").write_text(
        'def run() -> int:\n    """Spec: docs/specs/01-core.md [SUPTEST-1]"""\n'
        "    return 1\n",
        encoding="utf-8",
    )
    config = tmp_path / ".backstitch.toml"
    config.write_text(
        "[profile]\n"
        'spec_roots = ["docs/specs"]\n'
        "plan_roots = []\n"
        'code_roots = ["pkg"]\n'
        "test_roots = []\n\n"
        "[[lint.suppressions]]\n"
        'mechanism = "ignore"\n'
        'path = "docs/specs/01-core.md"\n'
        "sections = []\n"
        'codes = ["MAPPING_BLOCK_OWNERLESS"]\n'
        'declaration = "docs/specs/01-core.md#SUP-1"\n',
        encoding="utf-8",
    )
    packet_path = tmp_path / "packets.jsonl"
    report_path = tmp_path / "packet-report.json"

    result = run_cli(
        "packets",
        "--repo-root",
        str(tmp_path),
        "--config",
        str(config),
        "--kind",
        "all",
        "--output",
        str(packet_path),
        "--report",
        str(report_path),
    )

    assert result.returncode == 0, result.stderr
    rows = [
        json.loads(line)
        for line in packet_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert sorted(row["schema_version"] for row in rows) == [3, 4]
    suppression = next(row for row in rows if row["kind"] == "suppression")
    assert suppression["counterevidence"] == [
        {
            "role": "counterevidence",
            "path": "docs/specs/01-core.md",
            "start_line": 1,
            "end_line": 1,
            "snippet": "_Implementation mapping_:\r",
            "issue_indexes": [0],
        }
    ]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["schema_version"] == 3
    assert report["packet_schema_versions"] == [3, 4]
    assert report["kind_counts"] == {
        "eligible": {"section": 1, "invariant": 0, "suppression": 1},
        "emitted": {"section": 1, "invariant": 0, "suppression": 1},
    }

    obligation_id = "suppression::docs/specs/01-core.md#SUP-1"
    listed = run_cli(
        "obligation",
        "list",
        "--repo-root",
        str(tmp_path),
        "--config",
        str(config),
        "--format",
        "json",
    )
    assert listed.returncode == 0, listed.stderr
    entries = json.loads(listed.stdout)["result"]["entries"]
    assert obligation_id in {
        entry["obligation_id"]
        for entry in entries
        if entry["entry_type"] == "obligation"
    }

    detail = run_cli(
        "obligation",
        obligation_id,
        "--repo-root",
        str(tmp_path),
        "--config",
        str(config),
        "--format",
        "json",
    )
    assert detail.returncode == 0, detail.stderr
    detail_row = json.loads(detail.stdout)["result"]
    assert detail_row["matched_issue_count"] == 1
    assert detail_row["declaration"]["reference"] == ("docs/specs/01-core.md#SUP-1")

    unsupported = run_cli(
        "obligation",
        obligation_id,
        "--find-evidence",
        "--repo-root",
        str(tmp_path),
        "--config",
        str(config),
        "--format",
        "json",
    )
    assert unsupported.returncode == 2
    assert json.loads(unsupported.stdout)["problems"][0]["code"] == "INVALID_INPUT"
