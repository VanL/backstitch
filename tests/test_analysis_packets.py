"""Analysis packet generation tests.

Spec: docs/specs/02-backstitch-core.md [SC-6], [SC-7]
"""

import json
import subprocess
import sys
from pathlib import Path

from backstitch.analysis_packets import (
    MAX_OWNERS_PER_PACKET,
    MAX_SNIPPET_LINES,
    generate_packets,
)
from backstitch.profiles import get_profile

FIXTURES = Path(__file__).parent / "fixtures"
BROKEN = FIXTURES / "traceability_project"

BROKEN_PROFILE = get_profile("backstitch-style-v1").with_overrides(
    spec_roots=("docs/specifications",),
    code_roots=("src", "tests"),
    planned_spec_globs=("docs/specifications/*A-*.md",),
)


def _packets_by_section() -> dict[str, dict]:
    packets = generate_packets(BROKEN, BROKEN_PROFILE)
    return {p["section_id"]: p for p in packets}


def test_packet_rows_have_stable_fields() -> None:
    packets = generate_packets(BROKEN, BROKEN_PROFILE)
    assert packets
    for packet in packets:
        assert list(packet.keys()) == [
            "packet_id",
            "spec_path",
            "section_id",
            "title",
            "section_text",
            "owners",
            "tests",
            "issues",
            "warnings",
            "instructions",
        ]


def test_core1_packet_owners_tests_and_snippets() -> None:
    packet = _packets_by_section()["CORE-1"]
    assert packet["packet_id"] == "docs/specifications/01-Core.md#CORE-1"
    assert packet["title"] == "Runtime Behaviour"
    assert "frobnicate exactly once" in packet["section_text"]
    owners = {(o["path"], o["symbol"]) for o in packet["owners"]}
    assert ("src/runtime.py", None) in owners
    assert ("src/runtime.py", "Runtime.frobnicate") in owners
    symbol_owner = next(
        o for o in packet["owners"] if o["symbol"] == "Runtime.frobnicate"
    )
    assert "def frobnicate" in symbol_owner["snippet"]
    assert symbol_owner["start_line"] > 1
    assert "tests/test_runtime.py" in packet["tests"]


def test_core2_packet_carries_relevant_issues() -> None:
    packet = _packets_by_section()["CORE-2"]
    codes = {i["code"] for i in packet["issues"]}
    assert "MAPPING_PATH_MISSING" in codes


def test_sections_without_edges_get_no_packet() -> None:
    sections = _packets_by_section()
    assert "FENCE-1" not in sections
    # DUP-1 is ambiguous, so bare refs to it never resolve into edges.
    assert "DUP-1" not in sections


def test_instructions_require_structured_output() -> None:
    packet = _packets_by_section()["CORE-1"]
    text = packet["instructions"]
    for token in (
        "ok",
        "confirmed_mismatch",
        "probable_mismatch",
        "missing_trace",
        "ambiguous",
        "packet_id",
        "JSON",
    ):
        assert token in text


def test_snippets_are_bounded_with_warning(tmp_path: Path) -> None:
    spec_dir = tmp_path / "docs" / "specs"
    spec_dir.mkdir(parents=True)
    (spec_dir / "01-X.md").write_text(
        "# X\n\n## Big [X-1]\n\n_Implementation mapping_:\n\n- `pkg/big.py`\n",
        encoding="utf-8",
    )
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    body = '"""Spec: docs/specs/01-X.md [X-1]"""\n' + "x = 1\n" * 400
    (pkg / "big.py").write_text(body, encoding="utf-8")
    profile = get_profile("backstitch-style-v1").with_overrides(
        spec_roots=("docs/specs",), code_roots=("pkg",)
    )
    packets = generate_packets(tmp_path, profile)
    packet = next(p for p in packets if p["section_id"] == "X-1")
    owner = packet["owners"][0]
    assert len(owner["snippet"].splitlines()) <= MAX_SNIPPET_LINES
    assert any("truncated" in w for w in packet["warnings"])


def test_owner_count_is_bounded_with_warning(tmp_path: Path) -> None:
    spec_dir = tmp_path / "docs" / "specs"
    spec_dir.mkdir(parents=True)
    n_files = MAX_OWNERS_PER_PACKET + 3
    mapping_lines = "\n".join(f"- `pkg/m{i}.py`" for i in range(n_files))
    (spec_dir / "01-X.md").write_text(
        f"# X\n\n## Wide [X-1]\n\n_Implementation mapping_:\n\n{mapping_lines}\n",
        encoding="utf-8",
    )
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    for i in range(n_files):
        (pkg / f"m{i}.py").write_text(
            '"""Spec: docs/specs/01-X.md [X-1]"""\n', encoding="utf-8"
        )
    profile = get_profile("backstitch-style-v1").with_overrides(
        spec_roots=("docs/specs",), code_roots=("pkg",)
    )
    packets = generate_packets(tmp_path, profile)
    packet = next(p for p in packets if p["section_id"] == "X-1")
    assert len(packet["owners"]) == MAX_OWNERS_PER_PACKET
    assert any("omitted" in w for w in packet["warnings"])


def test_cli_packets_writes_jsonl(tmp_path: Path) -> None:
    out = tmp_path / "packets.jsonl"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "backstitch",
            "packets",
            "--repo-root",
            str(BROKEN),
            "--spec-root",
            "docs/specifications",
            "--code-root",
            "src",
            "--code-root",
            "tests",
            "--no-config",
            "--output",
            str(out),
        ],
        capture_output=True,
        text=True,
    )
    # The broken fixture has deterministic errors, so [SC-5] exit code 1
    # applies; the packet output is still written.
    assert result.returncode == 1, result.stderr
    rows = [
        json.loads(line)
        for line in out.read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert rows
    assert all("packet_id" in row for row in rows)


def test_suppressed_codes_never_reach_packet_issues(tmp_path: Path) -> None:
    # [EXC-6]: packets embed the SUPPRESSION-FILTERED report's issues, so a
    # finding suppressed in configuration must not surface in any packet.
    # (Fable's top-level `ignore` filter was rejected; the adopted mechanism
    # is lint.per-section-ignores, and only non-error findings are eligible.)
    import os

    home = tmp_path / "home"
    project = home / "repo"
    spec_dir = project / "docs" / "specs"
    spec_dir.mkdir(parents=True)
    (spec_dir / "01-X.md").write_text(
        "# X\n\n## Thing [X-1]\n\n_Implementation mapping_:\n\n"
        "- `pkg/mod.py`\n\n## Unmapped [X-2]\n",
        encoding="utf-8",
    )
    (project / "pkg").mkdir()
    (project / "pkg" / "mod.py").write_text(
        '"""Spec: docs/specs/01-X.md [X-1], [X-2]"""\n', encoding="utf-8"
    )
    (project / ".backstitch.toml").write_text(
        "[lint.per-section-ignores]\n"
        '"docs/specs/01-X.md::X-2" = ["SPEC_SECTION_UNMAPPED"]\n',
        encoding="utf-8",
    )
    out = tmp_path / "packets.jsonl"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "backstitch",
            "packets",
            "--repo-root",
            str(project),
            "--spec-root",
            "docs/specs",
            "--code-root",
            "pkg",
            "--output",
            str(out),
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(home)},
    )
    assert result.returncode == 0, result.stderr
    rows = [
        json.loads(line)
        for line in out.read_text(encoding="utf-8").splitlines()
        if line
    ]
    packet_codes = {i["code"] for row in rows for i in row["issues"]}
    assert "SPEC_SECTION_UNMAPPED" not in packet_codes


def test_cli_packets_clean_corpus_exits_zero(tmp_path: Path) -> None:
    out = tmp_path / "packets.jsonl"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "backstitch",
            "packets",
            "--repo-root",
            str(FIXTURES / "clean_project"),
            "--spec-root",
            "docs/specs",
            "--code-root",
            "pkg",
            "--no-config",
            "--output",
            str(out),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert out.read_text(encoding="utf-8").strip()
