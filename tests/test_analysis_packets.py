"""Analysis packet generation tests.

Spec: docs/specs/02-backstitch-core.md [SC-6], [SC-7]
"""

import hashlib
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

from backstitch.analysis_packets import (
    MAX_BINDING_TESTS_PER_PACKET,
    MAX_INVARIANT_TARGETS_PER_PACKET,
    MAX_OWNERS_PER_PACKET,
    MAX_SNIPPET_LINES,
    generate_packets,
)
from backstitch.config import ProfileConfig
from backstitch.models import Edge, Issue
from backstitch.profiles import get_profile
from backstitch.resolver import scan_repository

FIXTURES = Path(__file__).parent / "fixtures"
BROKEN = FIXTURES / "traceability_project"

BROKEN_PROFILE = get_profile("backstitch-style-v1").with_overrides(
    spec_roots=("docs/specifications",),
    code_roots=("src", "tests"),
    test_roots=("tests",),
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
            "kind",
            "spec_path",
            "section_id",
            "title",
            "section_text",
            # [SC-6]: the section's starting line anchors evidence checks.
            "section_start_line",
            "owners",
            "tests",
            "issues",
            # [SC-6]: the truncation-diagnostics field is `packet_warnings`.
            "packet_warnings",
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
    assert any("truncated" in w for w in packet["packet_warnings"])


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
    assert any("omitted" in w for w in packet["packet_warnings"])


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


def test_cli_packets_classifies_custom_test_root_without_name_guessing(
    tmp_path: Path,
) -> None:
    spec_dir = tmp_path / "docs" / "specs"
    spec_dir.mkdir(parents=True)
    spec_dir.joinpath("01-X.md").write_text(
        "# X\n\n## Contract [X-1]\n\n_Implementation mapping_:\n\n"
        "- `pkg/mod.py`\n- `qa/contract_check.py`\n",
        encoding="utf-8",
    )
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    pkg.joinpath("mod.py").write_text(
        '"""Spec: docs/specs/01-X.md [X-1]"""\n',
        encoding="utf-8",
    )
    qa = tmp_path / "qa"
    qa.mkdir()
    qa.joinpath("contract_check.py").write_text(
        '"""Contract check without a backlink."""\n',
        encoding="utf-8",
    )
    tmp_path.joinpath(".backstitch.toml").write_text(
        "\n".join(
            [
                "[profile]",
                'spec_roots = ["docs/specs"]',
                "plan_roots = []",
                'code_roots = ["pkg", "qa"]',
            ]
        )
        + "\n",
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
            str(tmp_path),
            "--test-root",
            "qa",
            "--output",
            str(out),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    rows = [json.loads(line) for line in out.read_text().splitlines() if line]
    assert len(rows) == 1
    assert rows[0]["tests"] == ["qa/contract_check.py"]
    assert {owner["path"] for owner in rows[0]["owners"]} == {"pkg/mod.py"}


def test_test_roots_do_not_start_a_second_scan(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    pkg.joinpath("mod.py").write_text("# [X-1]\n", encoding="utf-8")
    qa = tmp_path / "qa"
    qa.mkdir()
    qa.joinpath("contract_check.py").write_text("# [X-1]\n", encoding="utf-8")
    profile = get_profile("backstitch-style-v1").with_overrides(
        spec_roots=(),
        plan_roots=(),
        code_roots=("pkg",),
        test_roots=("qa",),
    )
    report = scan_repository(tmp_path, profile)
    assert {ref.path for ref in report.code_refs} == {"pkg/mod.py"}


def _write_invariant_packet_project(
    root: Path, *, targetless_spec: bool = False
) -> ProfileConfig:
    spec_dir = root / "docs/specs"
    spec_dir.mkdir(parents=True)
    mapping = (
        "\n\n_Implementation mapping_:\n\n- `pkg/mod.py::run`\n"
        if not targetless_spec
        else "\n"
    )
    spec_dir.joinpath("01-X.md").write_text(
        "# X\n\n## Contract [X-1]\n\n"
        "Invariant: [INV.SPEC.1] spec guarantee\n"
        f"{mapping}",
        encoding="utf-8",
    )
    pkg = root / "pkg"
    pkg.mkdir()
    pkg.joinpath("mod.py").write_text(
        "def run() -> int:\n"
        '    """Spec: docs/specs/01-X.md [X-1]\n'
        "\n"
        "    Invariant: [INV.CODE.1] code guarantee\n"
        '    """\n'
        "    return 1\n",
        encoding="utf-8",
    )
    tests = root / "tests"
    tests.mkdir()
    tests.joinpath("test_mod.py").write_text(
        "def test_code() -> None:\n"
        '    """Tests-invariant: [INV.CODE.1]"""\n'
        "    assert True\n\n"
        "def test_spec() -> None:\n"
        '    """Tests-invariant: [INV.SPEC.1]"""\n'
        "    assert True\n",
        encoding="utf-8",
    )
    profile = get_profile("backstitch-style-v1").with_overrides(
        spec_roots=("docs/specs",),
        plan_roots=(),
        code_roots=("pkg", "tests"),
        test_roots=("tests",),
    )
    return profile


def _expected_invariant_hash(packet: dict) -> str:
    projection = {
        "statement": packet["statement"],
        "targets": [
            {key: item[key] for key in ("path", "symbol", "start_line", "snippet")}
            for item in packet["targets"]
        ],
        "binding_tests": [
            {key: item[key] for key in ("path", "symbol", "start_line", "snippet")}
            for item in packet["binding_tests"]
        ],
    }
    encoded = json.dumps(
        projection, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def test_invariant_packets_include_discriminated_targets_tests_and_hash(
    tmp_path: Path,
) -> None:
    profile = _write_invariant_packet_project(tmp_path)

    packets = generate_packets(tmp_path, profile, kind="all")

    assert [packet["kind"] for packet in packets] == [
        "section",
        "invariant",
        "invariant",
    ]
    invariant_packets = {
        packet["invariant_id"]: packet
        for packet in packets
        if packet["kind"] == "invariant"
    }
    spec_packet = invariant_packets["INV.SPEC.1"]
    code_packet = invariant_packets["INV.CODE.1"]
    assert [(item["path"], item["symbol"]) for item in spec_packet["targets"]] == [
        ("pkg/mod.py", "run")
    ]
    assert [(item["path"], item["symbol"]) for item in code_packet["targets"]] == [
        ("pkg/mod.py", "run")
    ]
    assert code_packet["declaration"] == {
        "kind": "code",
        "path": "pkg/mod.py",
        "line": 4,
        "symbol": "run",
        "section_id": None,
    }
    assert code_packet["binding_tests"][0]["symbol"] == "test_code"
    assert "def test_code" in code_packet["binding_tests"][0]["snippet"]
    assert "Describe a concrete target-code change" in code_packet["instructions"]
    assert all(
        packet["content_hash"] == _expected_invariant_hash(packet)
        for packet in invariant_packets.values()
    )


def test_module_invariant_target_uses_bounded_whole_file(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    pkg.joinpath("mod.py").write_text(
        '"""Invariant: [INV.MODULE.1] module guarantee"""\n'
        + "\n".join(f"value_{index} = {index}" for index in range(150))
        + "\n",
        encoding="utf-8",
    )
    tests = tmp_path / "tests"
    tests.mkdir()
    tests.joinpath("test_mod.py").write_text(
        "def test_module() -> None:\n"
        '    """Tests-invariant: [INV.MODULE.1]"""\n'
        "    assert True\n",
        encoding="utf-8",
    )
    profile = get_profile("backstitch-style-v1").with_overrides(
        spec_roots=(),
        plan_roots=(),
        code_roots=("pkg", "tests"),
        test_roots=("tests",),
    )

    packet = generate_packets(tmp_path, profile, kind="invariant")[0]

    target = packet["targets"][0]
    assert (target["symbol"], target["start_line"]) == ("<module>", 1)
    assert len(target["snippet"].splitlines()) == MAX_SNIPPET_LINES
    assert any("truncated" in warning for warning in packet["packet_warnings"])


def test_targetless_spec_invariant_still_gets_packet_and_warning(
    tmp_path: Path,
) -> None:
    profile = _write_invariant_packet_project(tmp_path, targetless_spec=True)

    packets = generate_packets(tmp_path, profile, kind="invariant")
    packet = next(item for item in packets if item["invariant_id"] == "INV.SPEC.1")

    assert packet["targets"] == []
    assert any(
        "no target code resolved for spec-declared invariant" in warning
        for warning in packet["packet_warnings"]
    )


def test_untested_invariant_has_no_semantic_packet(tmp_path: Path) -> None:
    profile = _write_invariant_packet_project(tmp_path)
    (tmp_path / "tests/test_mod.py").write_text(
        "def test_code() -> None:\n"
        '    """Tests-invariant: [INV.CODE.1]"""\n'
        "    assert True\n",
        encoding="utf-8",
    )

    packets = generate_packets(tmp_path, profile, kind="invariant")

    assert [packet["invariant_id"] for packet in packets] == ["INV.CODE.1"]


def test_invariant_packet_caps_sort_and_deduplicate_targets_and_binds(
    tmp_path: Path,
) -> None:
    spec_dir = tmp_path / "docs/specs"
    spec_dir.mkdir(parents=True)
    mapping_lines = [
        *(f"- `pkg/target{index:02}.py`" for index in reversed(range(10))),
        "- `pkg/target09.py`",
    ]
    spec_dir.joinpath("01-Wide.md").write_text(
        "# Wide\n\n## Contract [WIDE-1]\n\n"
        "Invariant: [INV.WIDE.1] wide guarantee\n\n"
        "_Implementation mapping_:\n\n" + "\n".join(mapping_lines) + "\n",
        encoding="utf-8",
    )
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    for index in range(10):
        pkg.joinpath(f"target{index:02}.py").write_text(
            f"value = {index}\n", encoding="utf-8"
        )
    pkg.joinpath("backlink_only.py").write_text(
        '"""Spec: docs/specs/01-Wide.md [WIDE-1]"""\n',
        encoding="utf-8",
    )
    tests = tmp_path / "tests"
    tests.mkdir()
    for index in reversed(range(10)):
        tests.joinpath(f"test_{index:02}.py").write_text(
            "def test_bind() -> None:\n"
            '    """Tests-invariant: [INV.WIDE.1]"""\n'
            "    assert True\n",
            encoding="utf-8",
        )
    profile = get_profile("backstitch-style-v1").with_overrides(
        spec_roots=("docs/specs",),
        plan_roots=(),
        code_roots=("pkg", "tests"),
        test_roots=("tests",),
    )

    packet = generate_packets(tmp_path, profile, kind="invariant")[0]

    assert [item["path"] for item in packet["targets"]] == [
        f"pkg/target{index:02}.py" for index in range(8)
    ]
    assert [item["path"] for item in packet["binding_tests"]] == [
        f"tests/test_{index:02}.py" for index in range(8)
    ]
    assert "pkg/backlink_only.py" not in {item["path"] for item in packet["targets"]}
    assert "2 additional targets omitted" in packet["packet_warnings"]
    assert "2 additional binding tests omitted" in packet["packet_warnings"]


def test_code_packet_ignores_mappings_and_sorts_exact_invariant_issues(
    tmp_path: Path,
) -> None:
    profile = _write_invariant_packet_project(tmp_path)
    report = scan_repository(tmp_path, profile)
    extra_mapping = Edge(
        kind="mapping",
        spec_path="docs/specs/01-X.md",
        section_id="X-1",
        code_path="pkg/not-the-code-owner.py",
        code_symbol=None,
        line=6,
    )
    issues = (
        Issue(
            "INVARIANT_UNKNOWN",
            "error",
            "z.py",
            4,
            "last path",
            invariant_id="INV.CODE.1",
        ),
        Issue(
            "INVARIANT_UNTESTED",
            "warning",
            "a.py",
            3,
            "later line",
            invariant_id="INV.CODE.1",
        ),
        Issue(
            "INVARIANT_UNKNOWN",
            "error",
            "a.py",
            None,
            "null line first",
            invariant_id="INV.CODE.1",
        ),
        Issue(
            "INVARIANT_UNKNOWN",
            "error",
            "a.py",
            1,
            "different invariant",
            invariant_id="INV.SPEC.1",
        ),
    )
    report = replace(report, edges=(*report.edges, extra_mapping), issues=issues)

    packet = next(
        item
        for item in generate_packets(tmp_path, profile, report=report, kind="invariant")
        if item["invariant_id"] == "INV.CODE.1"
    )

    assert [(item["path"], item["symbol"]) for item in packet["targets"]] == [
        ("pkg/mod.py", "run")
    ]
    assert [
        (issue["path"], issue["line"], issue["code"], issue["message"])
        for issue in packet["issues"]
    ] == [
        ("a.py", None, "INVARIANT_UNKNOWN", "null line first"),
        ("a.py", 3, "INVARIANT_UNTESTED", "later line"),
        ("z.py", 4, "INVARIANT_UNKNOWN", "last path"),
    ]


def test_cli_packet_kinds_share_exit_and_have_stable_mixed_order(
    tmp_path: Path,
) -> None:
    _write_invariant_packet_project(tmp_path)
    base = [
        sys.executable,
        "-m",
        "backstitch",
        "packets",
        "--repo-root",
        str(tmp_path),
        "--no-config",
        "--spec-root",
        "docs/specs",
        "--code-root",
        "pkg",
        "--code-root",
        "tests",
        "--test-root",
        "tests",
    ]
    rows_by_kind: dict[str, list[dict]] = {}
    exits: set[int] = set()
    for kind in ("section", "invariant", "all"):
        output = tmp_path / f"{kind}.jsonl"
        result = subprocess.run(
            [*base, "--kind", kind, "--output", str(output)],
            capture_output=True,
            text=True,
            check=False,
        )
        exits.add(result.returncode)
        rows_by_kind[kind] = [
            json.loads(line) for line in output.read_text().splitlines() if line
        ]

    assert exits == {0}
    assert {row["kind"] for row in rows_by_kind["section"]} == {"section"}
    assert {row["kind"] for row in rows_by_kind["invariant"]} == {"invariant"}
    assert [row["packet_id"] for row in rows_by_kind["all"]] == [
        *[row["packet_id"] for row in rows_by_kind["section"]],
        *[row["packet_id"] for row in rows_by_kind["invariant"]],
    ]
    assert all(
        len(row["binding_tests"]) <= MAX_BINDING_TESTS_PER_PACKET
        and len(row["targets"]) <= MAX_INVARIANT_TARGETS_PER_PACKET
        for row in rows_by_kind["invariant"]
    )
