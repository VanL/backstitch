"""Regression tests for the independent-review findings (P1/P2 remediation).

Spec: docs/specs/02-backstitch-core.md [SC-4], [SC-6], [SC-11]
Spec: docs/specs/03-backstitch-configuration.md [CFG-5], [CFG-9]
Spec: docs/specs/04-backstitch-traceability-exclusions.md [EXC-4], [EXC-5]

Each test encodes one reviewer-reproduced defect so it cannot return.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from backstitch.exclusions import (
    UnknownSuppressionCodeError,
    parse_noqa_text,
)
from backstitch.markdown_specs import parse_markdown_spec
from backstitch.profiles import get_profile
from backstitch.resolver import scan_repository_with_artifacts

PROFILE = get_profile("backstitch-style-v1").with_overrides(
    spec_roots=("docs/specs",), plan_roots=(), code_roots=("pkg",)
)


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "backstitch", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _write(tmp_path: Path, rel: str, content: str) -> None:
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


# --- P1: HTML marker on a heading must not delete the section ----------


def test_heading_with_trailing_html_meta_marker_keeps_section(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "docs/specs/01-x.md",
        "# X\n\n## One [RX-1] <!-- backstitch: meta -->\n",
    )
    parsed = parse_markdown_spec(tmp_path / "docs/specs/01-x.md", tmp_path)
    assert [s.section_id for s in parsed.sections] == ["RX-1"]
    assert parsed.section_markers == (("RX-1", True, frozenset()),)


# --- P1: config keys must be consulted, not just parsed ----------------


def test_check_format_and_output_from_config_apply(tmp_path: Path) -> None:
    _write(tmp_path, "docs/specs/01-x.md", "# X\n\n## One [CX-1]\n")
    _write(tmp_path, "pkg/mod.py", '"""Mod."""\n')
    _write(
        tmp_path,
        ".backstitch.toml",
        "\n".join(
            [
                "[profile]",
                'spec_roots = ["docs/specs"]',
                "plan_roots = []",
                'code_roots = ["pkg"]',
                "[check]",
                'format = "json"',
                'output = "configured-report.json"',
            ]
        )
        + "\n",
    )
    result = run_cli("check", "--repo-root", str(tmp_path))
    assert result.returncode == 0, result.stderr
    written = tmp_path / "configured-report.json"
    assert written.is_file(), "config check.output was not honored"
    data = json.loads(written.read_text(encoding="utf-8"))
    assert "summary" in data, "config check.format=json was not honored"


def test_analyze_concurrency_from_config_is_validated(tmp_path: Path) -> None:
    _write(tmp_path, "packets.jsonl", "")
    _write(
        tmp_path,
        ".backstitch.toml",
        "[analyze]\nconcurrency = 0\n",
    )
    result = run_cli("analyze", "--packets", str(tmp_path / "packets.jsonl"))
    # The configured value is consulted: 0 fails validation with exit 2.
    assert result.returncode == 2
    assert "concurrency" in result.stderr


# --- P1: unknown noqa codes surface as warnings under the hatch --------


def test_unknown_noqa_code_warns_under_allow_unknown(tmp_path: Path) -> None:
    _write(tmp_path, "docs/specs/01-x.md", "# X\n\n## One [NX-1]\n")
    _write(
        tmp_path,
        "pkg/mod.py",
        '"""Mod."""\n\n# backstitch: noqa NOT_A_REAL_CODE_9\ndef f() -> None:\n    pass\n',
    )
    _write(
        tmp_path,
        ".backstitch.toml",
        "allow_unknown_keys = true\n[profile]\n"
        'spec_roots = ["docs/specs"]\nplan_roots = []\ncode_roots = ["pkg"]\n',
    )
    result = run_cli("check", "--repo-root", str(tmp_path))
    assert result.returncode == 0
    assert "NOT_A_REAL_CODE_9" in result.stderr, "typo suppression was silent"


# --- P2: noqa parsing is line-oriented ----------------------------------


def test_docstring_noqa_does_not_capture_following_prose() -> None:
    codes, warnings = parse_noqa_text(
        "backstitch: noqa CODE_REF_BARE_UNRESOLVED\nMore details follow here."
    )
    assert codes == frozenset({"CODE_REF_BARE_UNRESOLVED"})
    assert warnings == []


# --- P2: section markers override file-level markers --------------------


def test_section_marker_overrides_file_level_ignore(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "docs/specs/01-x.md",
        "\n".join(
            [
                "# X",
                "",
                "_Traceability: ignore SPEC_SECTION_UNMAPPED_",
                "",
                "## Narrowed [OV-1]",
                "",
                "_Traceability: ignore CODE_REF_BROAD_",
                "",
                "## Covered [OV-2]",
            ]
        )
        + "\n",
    )
    _write(tmp_path, "pkg/mod.py", '"""Mod."""\n')
    report, artifacts = scan_repository_with_artifacts(tmp_path, PROFILE)
    assert ("docs/specs/01-x.md", "OV-1") in artifacts.sections_with_markers
    # OV-2 has no marker: file-level ignore applies (suppressed at CLI).
    # OV-1 overrides file level: its SPEC_SECTION_UNMAPPED must survive.
    result = run_cli(
        "check",
        "--repo-root",
        str(tmp_path),
        "--spec-root",
        "docs/specs",
        "--plan-root",
        "",
        "--code-root",
        "pkg",
        "--format",
        "json",
    )
    data = json.loads(result.stdout)
    unmapped = {
        i["section_id"] for i in data["issues"] if i["code"] == "SPEC_SECTION_UNMAPPED"
    }
    assert "OV-1" in unmapped
    assert "OV-2" not in unmapped


# --- P1 (agent 2): fence closer must be at least opener length ----------


def test_longer_fence_opener_requires_matching_close_length(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "docs/specs/01-x.md",
        "\n".join(
            [
                "# X",
                "",
                "## Real [FL-1]",
                "",
                "````md",
                "```",
                "## Phantom [FL-9]",
                "```",
                "````",
            ]
        )
        + "\n",
    )
    parsed = parse_markdown_spec(tmp_path / "docs/specs/01-x.md", tmp_path)
    assert [s.section_id for s in parsed.sections] == ["FL-1"]


# --- Round 2 findings (post-remediation review) --------------------------
# P1: [SC-6] packet truncation diagnostics field is `packet_warnings`
# (pinned by tests/test_analysis_packets.py::test_packet_rows_have_stable_fields).


# --- Round 2 P2: packets surfaces the same suppression diagnostics as check


def test_packets_emits_suppression_diagnostics(tmp_path: Path) -> None:
    _write(tmp_path, "docs/specs/01-x.md", "# X\n\n## One [PX-1]\n")
    _write(
        tmp_path,
        "pkg/mod.py",
        '"""Mod."""\n\n# backstitch: noqa NOT_A_REAL_CODE_9\ndef f() -> None:\n    pass\n',
    )
    _write(
        tmp_path,
        ".backstitch.toml",
        "\n".join(
            [
                "allow_unknown_keys = true",
                "[profile]",
                'spec_roots = ["docs/specs"]',
                "plan_roots = []",
                'code_roots = ["pkg"]',
                "[lint.per-file-ignores]",
                '"nonexistent/*" = ["CODE_REF_BROAD"]',
            ]
        )
        + "\n",
    )
    result = run_cli(
        "packets",
        "--repo-root",
        str(tmp_path),
        "--output",
        str(tmp_path / "p.jsonl"),
    )
    assert "NOT_A_REAL_CODE_9" in result.stderr, "unknown-code warning dropped"
    assert "unused per-file-ignore" in result.stderr, "stale-ignore warning dropped"


# --- Round 2 P2: config show serializes [packets] -------------------------


def test_config_show_includes_packets_settings(tmp_path: Path) -> None:
    _write(
        tmp_path,
        ".backstitch.toml",
        '[packets]\noutput = "out/packets.jsonl"\n',
    )
    result = run_cli("config", "show", "--repo-root", str(tmp_path))
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert "packets" in data, "config show dropped the [packets] table"
    assert data["packets"]["output"].endswith("out/packets.jsonl")


# --- Round 2 P2: malformed noqa directives are never silently accepted ----


def test_bare_noqa_directive_warns() -> None:
    codes, warnings = parse_noqa_text("backstitch: noqa")
    assert codes == frozenset()
    assert any("no issue codes" in w for w in warnings)


def test_space_separated_unknown_tail_is_not_dropped() -> None:
    # Strict mode: the tail is an unknown code, same as the comma form.
    with pytest.raises(UnknownSuppressionCodeError):
        parse_noqa_text("backstitch: noqa CODE_REF_BROAD NOT_A_CODE")
    # Hatch: the good code applies and the tail warns.
    codes, warnings = parse_noqa_text(
        "backstitch: noqa CODE_REF_BROAD NOT_A_CODE", allow_unknown=True
    )
    assert codes == frozenset({"CODE_REF_BROAD"})
    assert any("NOT_A_CODE" in w for w in warnings)


def test_unparseable_noqa_token_warns() -> None:
    codes, warnings = parse_noqa_text(
        "backstitch: noqa CODE_REF_BROAD, (huh)", allow_unknown=True
    )
    assert codes == frozenset({"CODE_REF_BROAD"})
    assert any("unparseable" in w for w in warnings)


def test_prose_mention_of_noqa_is_not_a_directive() -> None:
    # [EXC-5] grammar anchors the directive at line start; docstring prose
    # that merely mentions the marker never parses (and never warns).
    assert parse_noqa_text("Use backstitch: noqa to suppress findings.") == (
        frozenset(),
        [],
    )


def test_packets_does_not_report_used_ignores_as_stale(tmp_path: Path) -> None:
    # Round 3: the unused-ignore audit must run AFTER the suppression pass
    # (should_suppress records usage); auditing first made `packets` call
    # every used config rule stale while `check` stayed silent.
    _write(
        tmp_path,
        "docs/specs/01-x.md",
        "# X\n\n## One [X-1]\n\n_Implementation mapping_:\n\n"
        "- `pkg/mod.py`\n\n## Two [X-2]\n",
    )
    _write(tmp_path, "pkg/mod.py", '"""Spec: docs/specs/01-x.md [X-1]"""\n')
    _write(
        tmp_path,
        ".backstitch.toml",
        "\n".join(
            [
                "[profile]",
                'spec_roots = ["docs/specs"]',
                "plan_roots = []",
                'code_roots = ["pkg"]',
                "[lint.per-section-ignores]",
                '"docs/specs/01-x.md::X-2" = ["SPEC_SECTION_UNMAPPED"]',
            ]
        )
        + "\n",
    )
    check = run_cli("check", "--repo-root", str(tmp_path))
    assert check.returncode == 0, check.stdout + check.stderr
    assert "unused" not in check.stderr
    packets = run_cli(
        "packets",
        "--repo-root",
        str(tmp_path),
        "--output",
        str(tmp_path / "p.jsonl"),
    )
    assert packets.returncode == 0, packets.stdout + packets.stderr
    assert "unused" not in packets.stderr, (
        "packets reported a used ignore as stale: " + packets.stderr
    )


# --- Round 4 P2: [CFG-7] global --config / --no-config spellings -----------


def _custom_config_repo(tmp_path: Path) -> Path:
    _write(tmp_path, "docs/specs/01-x.md", "# X\n\n## One [GX-1]\n")
    _write(tmp_path, "pkg/mod.py", '"""Mod."""\n')
    _write(
        tmp_path,
        "custom.toml",
        "\n".join(
            [
                "[profile]",
                'spec_roots = ["docs/specs"]',
                "plan_roots = []",
                'code_roots = ["pkg"]',
                "[check]",
                'format = "json"',
                'output = "from-custom.json"',
            ]
        )
        + "\n",
    )
    return tmp_path / "custom.toml"


def test_global_config_flag_applies_to_check(tmp_path: Path) -> None:
    custom = _custom_config_repo(tmp_path)
    result = run_cli("--config", str(custom), "check", "--repo-root", str(tmp_path))
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "from-custom.json").is_file(), (
        "global --config spelling was not honored"
    )


def test_global_no_config_flag_applies_to_check(tmp_path: Path) -> None:
    _custom_config_repo(tmp_path)
    # Discovery skipped: the custom.toml roots never load, so the explicit
    # CLI roots are required and check runs on defaults.
    result = run_cli(
        "--no-config",
        "check",
        "--repo-root",
        str(tmp_path),
        "--spec-root",
        "docs/specs",
        "--plan-root",
        "",
        "--code-root",
        "pkg",
    )
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "from-custom.json").exists()


def test_mixed_config_spellings_are_usage_error(tmp_path: Path) -> None:
    custom = _custom_config_repo(tmp_path)
    result = run_cli(
        "--no-config",
        "check",
        "--repo-root",
        str(tmp_path),
        "--config",
        str(custom),
    )
    assert result.returncode == 2
    assert "mutually exclusive" in result.stderr


def test_config_show_and_path_honor_config_flags(tmp_path: Path) -> None:
    custom = _custom_config_repo(tmp_path)
    shown = run_cli("config", "show", "--config", str(custom))
    assert shown.returncode == 0, shown.stderr
    assert json.loads(shown.stdout)["check"]["format"] == "json"
    path = run_cli("--config", str(custom), "config", "path")
    assert path.returncode == 0
    assert path.stdout.strip() == str(custom)
    no_config_path = run_cli("--no-config", "config", "path")
    assert no_config_path.returncode == 0
    assert no_config_path.stdout.strip() == ""


# --- Round 5 P1: malformed packet files are invocation errors, exit 2 ------


def _full_packet(**overrides: object) -> dict:
    packet: dict = {
        "packet_id": "docs/specs/01-x.md#X-1",
        "spec_path": "docs/specs/01-x.md",
        "section_id": "X-1",
        "title": "One",
        "section_text": "## One [X-1]",
        "owners": [],
        "tests": [],
        "issues": [],
        "packet_warnings": [],
        "instructions": "Respond with JSON.",
    }
    packet.update(overrides)
    return packet


def _run_analyze(
    tmp_path: Path, *packet_lines: str
) -> subprocess.CompletedProcess[str]:
    packets = tmp_path / "packets.jsonl"
    packets.write_text("".join(line + "\n" for line in packet_lines), encoding="utf-8")
    return run_cli(
        "analyze",
        "--packets",
        str(packets),
        "--model",
        "fake-model",
        "--no-config",
        "--output",
        str(tmp_path / "out.jsonl"),
    )


def test_empty_object_packet_is_invocation_error(tmp_path: Path) -> None:
    # [SC-5]/[SC-6]: a malformed packets file exits 2; it must never come
    # back as an `ambiguous` analysis row with an invented packet ID.
    result = _run_analyze(tmp_path, "{}")
    assert result.returncode == 2, result.stdout + result.stderr
    assert "malformed packet" in result.stderr
    assert "<missing packet_id>" not in result.stdout
    assert not (tmp_path / "out.jsonl").exists()


def test_packet_missing_instructions_is_invocation_error(tmp_path: Path) -> None:
    packet = {k: v for k, v in _full_packet().items() if k != "instructions"}
    result = _run_analyze(tmp_path, json.dumps(packet))
    assert result.returncode == 2
    assert "instructions" in result.stderr


def test_packet_with_wrong_field_type_is_invocation_error(tmp_path: Path) -> None:
    result = _run_analyze(tmp_path, json.dumps(_full_packet(owners="not-a-list")))
    assert result.returncode == 2
    assert "owners" in result.stderr


# --- Round 6 P2: packet validation covers nested structures ----------------


def test_packet_with_malformed_nested_content_is_invocation_error(
    tmp_path: Path,
) -> None:
    # [SC-6] defines owners, issues, and packet_warnings as structured
    # content; corrupted items must be rejected at the boundary, not
    # prompted on.
    for overrides in (
        {"owners": ["bad-owner"]},
        {"issues": ["bad-issue"]},
        {"packet_warnings": [123]},
        {"tests": [42]},
        {
            "owners": [
                {"path": "p.py", "symbol": None, "start_line": True, "snippet": ""}
            ]
        },
    ):
        result = _run_analyze(tmp_path, json.dumps(_full_packet(**overrides)))
        assert result.returncode == 2, (overrides, result.stdout, result.stderr)
        assert "malformed packet" in result.stderr, (overrides, result.stderr)


def test_analyze_unknown_model_is_invocation_error(tmp_path: Path) -> None:
    # [SC-5]: an unknown model name fails adapter construction -> exit 2.
    # The total-model-failure -> exit 2 rule (analyze never exits 1;
    # semantic findings are advisory) is pinned at the unit level in
    # tests/test_analysis_llm.py::test_analyze_exit_code_rules.
    result = _run_analyze(tmp_path, json.dumps(_full_packet()))
    assert result.returncode == 2
    assert result.returncode != 1
