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

# [SC-7] hermetic testing: a name no local `llm` alias could plausibly
# resolve, so CLI tests can never construct a real adapter or call a model.
HERMETIC_MODEL = "backstitch-hermetic-model-that-must-not-exist"


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
        "section_start_line": 3,
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
        HERMETIC_MODEL,
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
    # [SC-5]: an unknown model name is an invocation error -> exit 2 with a
    # clear one-line diagnostic, never "internal error" and never the
    # KeyError repr quoting. The total-model-failure -> exit 2 rule
    # (analyze never exits 1; semantic findings are advisory) is pinned at
    # the unit level in test_analysis_llm.py::test_analyze_exit_code_rules.
    result = _run_analyze(tmp_path, json.dumps(_full_packet()))
    assert result.returncode == 2
    assert "internal error" not in result.stderr, result.stderr
    assert HERMETIC_MODEL in result.stderr, result.stderr
    assert f"'Unknown model: {HERMETIC_MODEL}'" not in result.stderr, (
        "KeyError repr quoting leaked into the diagnostic"
    )


# --- Round 8 P1: exclude semantics ------------------------------------------


def test_default_exclude_covers_nested_venv(tmp_path: Path) -> None:
    # CFG-6.7: a bare `venv` in the exclude list skips the subtree at any
    # depth, not only a top-level path named exactly `venv`.
    _write(tmp_path, "docs/specs/01-x.md", "# X\n\n## One [EX-1]\n")
    _write(tmp_path, "pkg/mod.py", '"""Mod."""\n')
    _write(tmp_path, "pkg/venv/bad.py", "def broken(:\n")
    _write(
        tmp_path,
        ".backstitch.toml",
        '[profile]\nspec_roots = ["docs/specs"]\nplan_roots = []\ncode_roots = ["pkg"]\n',
    )
    result = run_cli("check", "--repo-root", str(tmp_path), "--format", "json")
    codes = {i["code"] for i in json.loads(result.stdout)["issues"]}
    assert "PYTHON_SYNTAX_ERROR" not in codes, codes


def test_empty_exclude_scans_everything_including_dot_dirs(
    tmp_path: Path,
) -> None:
    # CFG-6.7: `exclude = []` REPLACES the defaults; no hard-coded
    # dot-directory skip may sit underneath the config.
    _write(tmp_path, "docs/specs/01-x.md", "# X\n\n## One [EX-2]\n")
    _write(tmp_path, "pkg/.hidden/bad.py", "def broken(:\n")
    _write(tmp_path, "pkg/venv/bad.py", "def broken(:\n")
    _write(
        tmp_path,
        ".backstitch.toml",
        'exclude = []\n[profile]\nspec_roots = ["docs/specs"]\nplan_roots = []\ncode_roots = ["pkg"]\n',
    )
    result = run_cli("check", "--repo-root", str(tmp_path), "--format", "json")
    syntax_paths = {
        i["path"]
        for i in json.loads(result.stdout)["issues"]
        if i["code"] == "PYTHON_SYNTAX_ERROR"
    }
    assert syntax_paths == {"pkg/.hidden/bad.py", "pkg/venv/bad.py"}


# --- Round 8 P2: env expansion in profile roots -----------------------------


def test_env_vars_expand_in_config_roots(tmp_path: Path) -> None:
    import os

    _write(tmp_path, "actual-specs/01-x.md", "# X\n\n## One [EV-1]\n")
    _write(tmp_path, "pkg/mod.py", '"""Mod."""\n')
    _write(
        tmp_path,
        ".backstitch.toml",
        '[profile]\nspec_roots = ["$BACKSTITCH_TEST_SPEC_DIR"]\n'
        'plan_roots = []\ncode_roots = ["pkg"]\n',
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "backstitch",
            "check",
            "--repo-root",
            str(tmp_path),
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "BACKSTITCH_TEST_SPEC_DIR": "actual-specs"},
    )
    data = json.loads(result.stdout)
    assert data["summary"]["spec_sections"] == 1, result.stderr
    assert "SCAN_ROOT_MISSING" not in {i["code"] for i in data["issues"]}


# --- Round 8 P2: config show follows load strictness for lint codes ---------


def test_config_show_rejects_invalid_suppression_code(tmp_path: Path) -> None:
    _write(
        tmp_path,
        ".backstitch.toml",
        '[lint.per-file-ignores]\n"pkg/*" = ["NOT_A_REAL_CODE"]\n',
    )
    strict = run_cli("config", "show", "--repo-root", str(tmp_path))
    assert strict.returncode == 2
    assert "NOT_A_REAL_CODE" in strict.stderr
    _write(
        tmp_path,
        ".backstitch.toml",
        "allow_unknown_keys = true\n"
        '[lint.per-file-ignores]\n"pkg/*" = ["NOT_A_REAL_CODE"]\n',
    )
    hatch = run_cli("config", "show", "--repo-root", str(tmp_path))
    assert hatch.returncode == 0
    assert "NOT_A_REAL_CODE" in hatch.stderr


# --- Round 8 P2: packet issue records must be real issue records ------------


def test_packet_with_bogus_issue_record_is_invocation_error(
    tmp_path: Path,
) -> None:
    bogus = {"code": "NOT_A_BACKSTITCH_CODE", "severity": "bogus", "message": "x"}
    result = _run_analyze(tmp_path, json.dumps(_full_packet(issues=[bogus])))
    assert result.returncode == 2
    assert "issues" in result.stderr


# --- Round 8 P2: model evidence stays packet-local ---------------------------


def test_evidence_outside_packet_is_rejected() -> None:
    from backstitch.analysis_llm import analyze_packets

    packet = {
        "packet_id": "docs/specs/01-x.md#X-1",
        "spec_path": "docs/specs/01-x.md",
        "section_id": "X-1",
        "title": "One",
        "section_text": "## One [X-1]",
        "owners": [
            {"path": "pkg/mod.py", "symbol": None, "start_line": 1, "snippet": "x"}
        ],
        "tests": [],
        "issues": [],
        "packet_warnings": [],
        "instructions": "Respond with JSON.",
    }
    response = json.dumps(
        {
            "packet_id": packet["packet_id"],
            "classification": "ok",
            "summary": "fine",
            "evidence": [{"path": "not-in-packet.py", "line": 999}],
        }
    )
    rows, errors = analyze_packets([packet], lambda prompt: response)
    assert rows[0]["classification"] == "ambiguous"
    assert any("not part of the packet" in e for e in errors)
    # bool is an int subclass; line=true must not validate.
    bool_line = json.dumps(
        {
            "packet_id": packet["packet_id"],
            "classification": "ok",
            "summary": "fine",
            "evidence": [{"path": "pkg/mod.py", "line": True}],
        }
    )
    rows, errors = analyze_packets([packet], lambda prompt: bool_line)
    assert rows[0]["classification"] == "ambiguous"


# --- Round 8 P2: summarize packet-ID universe = sections with packets --------


def test_forged_row_for_packetless_section_is_rejected() -> None:
    from backstitch.analysis_results import (
        load_analysis_results,
        packet_ids_from_report,
    )

    report = {
        "spec_sections": [
            {"path": "docs/specs/01-x.md", "section_id": "X-1"},
            {"path": "docs/specs/01-x.md", "section_id": "X-2"},  # no edges
        ],
        "edges": [
            {
                "kind": "backlink",
                "spec_path": "docs/specs/01-x.md",
                "section_id": "X-1",
                "code_path": "pkg/mod.py",
                "code_symbol": None,
                "line": 1,
            }
        ],
    }
    ids = packet_ids_from_report(report)
    assert ids == {"docs/specs/01-x.md#X-1"}
    forged = json.dumps(
        {
            "packet_id": "docs/specs/01-x.md#X-2",
            "classification": "ok",
            "summary": "forged",
        }
    )
    load = load_analysis_results(forged + "\n", ids)
    assert load.results == ()
    assert any("unknown packet ID" in e for e in load.errors)


# --- Round 8 P2: _Traceability marker syntax and placement -------------------


def test_bare_traceability_ignore_marker_is_strict_error(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "docs/specs/01-x.md",
        "# X\n\n## One [TM-1]\n\n_Traceability: ignore_\n",
    )
    _write(tmp_path, "pkg/mod.py", '"""Mod."""\n')
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
    )
    assert result.returncode == 2
    assert "malformed traceability marker" in result.stderr


def test_marker_after_body_text_does_not_apply(tmp_path: Path) -> None:
    # [EXC-4] §4.2: section markers go immediately after the heading; a
    # marker after body text neither applies nor stays silent.
    _write(
        tmp_path,
        "docs/specs/01-x.md",
        "# X\n\n## One [TM-2]\n\nBody text first.\n\n_Traceability: meta_\n",
    )
    _write(tmp_path, "pkg/mod.py", '"""Mod."""\n')
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
    assert "TM-2" in unmapped, "misplaced marker still suppressed the section"
    assert "after body text" in result.stderr


# --- Round 8 P3: span noqa attempting an error code warns --------------------


def test_span_noqa_on_error_code_warns(tmp_path: Path) -> None:
    _write(tmp_path, "docs/specs/01-x.md", "# X\n\n## One [SP-1]\n")
    _write(
        tmp_path,
        "pkg/mod.py",
        '"""Mod."""\n\n# backstitch: noqa SPEC_FILE_MISSING\n'
        'def f() -> None:\n    """Spec: docs/specs/09-gone.md [SP-1]"""\n',
    )
    _write(
        tmp_path,
        ".backstitch.toml",
        '[profile]\nspec_roots = ["docs/specs"]\nplan_roots = []\ncode_roots = ["pkg"]\n',
    )
    result = run_cli("check", "--repo-root", str(tmp_path))
    assert result.returncode == 1  # the error finding survives
    assert "error-severity" in result.stderr, (
        "span suppression of an error code was silently ignored"
    )


# --- Round 8 P3: packets resolves configuration once -------------------------


def test_packets_prints_load_warnings_exactly_once(tmp_path: Path) -> None:
    _write(tmp_path, "docs/specs/01-x.md", "# X\n\n## One [OC-1]\n")
    _write(tmp_path, "pkg/mod.py", '"""Mod."""\n')
    _write(
        tmp_path,
        ".backstitch.toml",
        "allow_unknown_keys = true\nbogus_key = 1\n"
        '[profile]\nspec_roots = ["docs/specs"]\nplan_roots = []\ncode_roots = ["pkg"]\n',
    )
    result = run_cli(
        "packets",
        "--repo-root",
        str(tmp_path),
        "--output",
        str(tmp_path / "p.jsonl"),
    )
    assert result.stderr.count("bogus_key") == 1, result.stderr


# --- Round 9 P1: malformed trailing HTML ignore must not delete sections ----


def test_empty_html_ignore_on_heading_is_strict_error(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "docs/specs/01-x.md",
        "# X\n\n## One [HI-2] <!-- backstitch: ignore  -->\n",
    )
    _write(tmp_path, "pkg/mod.py", '"""Mod."""\n')
    result = run_cli(
        "check",
        "--repo-root",
        str(tmp_path),
        "--no-config",
        "--spec-root",
        "docs/specs",
        "--plan-root",
        "",
        "--code-root",
        "pkg",
    )
    assert result.returncode == 2
    assert "malformed traceability marker" in result.stderr


def test_empty_html_ignore_keeps_section_under_hatch(tmp_path: Path) -> None:
    # Under allow_unknown_keys the malformed marker warns -- and the
    # heading's section must survive, never be silently deleted.
    _write(
        tmp_path,
        "docs/specs/01-x.md",
        "# X\n\n## One [HI-3] <!-- backstitch: ignore  -->\n",
    )
    _write(tmp_path, "pkg/mod.py", '"""Mod."""\n')
    _write(
        tmp_path,
        ".backstitch.toml",
        "allow_unknown_keys = true\n[profile]\n"
        'spec_roots = ["docs/specs"]\nplan_roots = []\ncode_roots = ["pkg"]\n',
    )
    result = run_cli("check", "--repo-root", str(tmp_path), "--format", "json")
    data = json.loads(result.stdout)
    assert data["summary"]["spec_sections"] == 1
    assert "malformed traceability marker" in result.stderr


# --- Round 9 P2: extended config paths anchor at the defining file ----------


def test_extended_config_paths_resolve_against_defining_file(
    tmp_path: Path,
) -> None:
    shared = tmp_path / "shared"
    repo = tmp_path / "repo"
    _write(tmp_path, "shared/parent.toml", '[check]\noutput = "reports/out.json"\n')
    _write(
        tmp_path,
        "repo/.backstitch.toml",
        'extend = "../shared/parent.toml"\n',
    )
    result = run_cli("config", "show", "--repo-root", str(repo))
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)["check"]["output"]
    assert output == str((shared / "reports/out.json").resolve()), output


# --- Round 9 P2: absolute roots fail with a clear diagnostic ---------------


def test_root_outside_repo_is_clear_invocation_error(tmp_path: Path) -> None:
    import os

    outside = tmp_path / "outside-specs"
    _write(tmp_path, "outside-specs/01-y.md", "# Y\n\n## One [OS-1]\n")
    repo = tmp_path / "repo"
    _write(tmp_path, "repo/pkg/mod.py", '"""Mod."""\n')
    _write(
        tmp_path,
        "repo/.backstitch.toml",
        '[profile]\nspec_roots = ["$BACKSTITCH_TEST_ABS_ROOT"]\n'
        'plan_roots = []\ncode_roots = ["pkg"]\n',
    )
    result = subprocess.run(
        [sys.executable, "-m", "backstitch", "check", "--repo-root", str(repo)],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "BACKSTITCH_TEST_ABS_ROOT": str(outside)},
    )
    assert result.returncode == 2
    assert "outside the repository root" in result.stderr
    assert "subpath" not in result.stderr


# --- Round 9 P2: evidence is line-local, not just path-local ---------------


def test_evidence_line_outside_snippet_is_rejected() -> None:
    from backstitch.analysis_llm import analyze_packets

    packet = _full_packet(
        owners=[
            {
                "path": "pkg/mod.py",
                "symbol": None,
                "start_line": 10,
                "snippet": "a\nb\nc",
            }
        ]
    )

    def respond(line: int) -> str:
        return json.dumps(
            {
                "packet_id": packet["packet_id"],
                "classification": "ok",
                "summary": "fine",
                "evidence": [{"path": "pkg/mod.py", "line": line}],
            }
        )

    rows, errors = analyze_packets([packet], lambda prompt: respond(999999))
    assert rows[0]["classification"] == "ambiguous"
    assert any("outside the packet's shown content" in e for e in errors)
    # A line inside the snippet range (10..12) is accepted.
    rows, errors = analyze_packets([packet], lambda prompt: respond(11))
    assert rows[0]["classification"] == "ok"
    assert errors == []


# --- Round 9 P2: summarize-analysis validates the report shape --------------


def test_summarize_rejects_summary_only_report(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps({"summary": {"errors": 0, "warnings": 0, "infos": 0}}),
        encoding="utf-8",
    )
    results = tmp_path / "results.jsonl"
    results.write_text("", encoding="utf-8")
    result = run_cli(
        "summarize-analysis",
        "--deterministic-report",
        str(report),
        "--analysis-results",
        str(results),
    )
    assert result.returncode == 2
    assert "not a backstitch deterministic report" in result.stderr


# --- Round 9 P2: packet issue metadata types ---------------------------------


def test_packet_issue_with_malformed_metadata_is_invocation_error(
    tmp_path: Path,
) -> None:
    bad = {
        "code": "SPEC_SECTION_UNMAPPED",
        "severity": "info",
        "message": "x",
        "path": "docs/specs/01-x.md",
        "line": True,
        "section_id": 42,
        "symbol": [],
    }
    result = _run_analyze(tmp_path, json.dumps(_full_packet(issues=[bad])))
    assert result.returncode == 2
    assert "issues" in result.stderr


# --- Round 9 P3: stale error-code noqa warns without a matching finding -----


def test_stale_error_code_noqa_warns_unconditionally(tmp_path: Path) -> None:
    # [EXC-8]: the attempt warns even when no matching error is emitted --
    # a directive that only warns when the error fires is silent exactly
    # when its author believes it works.
    _write(tmp_path, "docs/specs/01-x.md", "# X\n\n## One [SN-1]\n")
    _write(
        tmp_path,
        "pkg/mod.py",
        '"""Mod."""\n\n# backstitch: noqa SPEC_FILE_MISSING\ndef f() -> None:\n    pass\n',
    )
    result = run_cli(
        "check",
        "--repo-root",
        str(tmp_path),
        "--no-config",
        "--spec-root",
        "docs/specs",
        "--plan-root",
        "",
        "--code-root",
        "pkg",
    )
    assert result.returncode == 0
    assert "cannot suppress error-severity code SPEC_FILE_MISSING" in result.stderr


# --- Round 10 P1: one-space empty HTML ignore --------------------------------


def test_one_space_empty_html_ignore_is_strict_error(tmp_path: Path) -> None:
    # `<!-- backstitch: ignore -->` (single space) previously matched no
    # marker form at all, so a trailing heading marker silently deleted
    # the section; both empty-ignore spellings are malformed now.
    _write(
        tmp_path,
        "docs/specs/01-x.md",
        "# X\n\n## One [HI-4] <!-- backstitch: ignore -->\n",
    )
    _write(tmp_path, "pkg/mod.py", '"""Mod."""\n')
    result = run_cli(
        "check",
        "--repo-root",
        str(tmp_path),
        "--no-config",
        "--spec-root",
        "docs/specs",
        "--plan-root",
        "",
        "--code-root",
        "pkg",
    )
    assert result.returncode == 2
    assert "malformed traceability marker" in result.stderr


def test_bogus_html_marker_form_is_strict_error(tmp_path: Path) -> None:
    # Any backstitch HTML comment that matches neither valid form errors;
    # it must never fall through unrecognized.
    _write(
        tmp_path,
        "docs/specs/01-x.md",
        "# X\n\n## One [HI-5] <!-- backstitch: bogus -->\n",
    )
    _write(tmp_path, "pkg/mod.py", '"""Mod."""\n')
    result = run_cli(
        "check",
        "--repo-root",
        str(tmp_path),
        "--no-config",
        "--spec-root",
        "docs/specs",
        "--plan-root",
        "",
        "--code-root",
        "pkg",
    )
    assert result.returncode == 2
    assert "malformed traceability marker" in result.stderr


# --- Round 10 P2: summarize validates edge internals -------------------------


def test_summarize_rejects_malformed_edge_records(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "profile": "p",
                "repo_root": "r",
                "summary": {"errors": 0, "warnings": 0, "infos": 0},
                "spec_sections": [],
                "code_refs": [],
                "spec_mappings": [],
                "edges": [{}],
                "issues": [],
            }
        ),
        encoding="utf-8",
    )
    results = tmp_path / "results.jsonl"
    results.write_text("", encoding="utf-8")
    result = run_cli(
        "summarize-analysis",
        "--deterministic-report",
        str(report),
        "--analysis-results",
        str(results),
    )
    assert result.returncode == 2
    assert "internal error" not in result.stderr
    assert "edges[0]" in result.stderr


# --- Round 10 P2: evidence line-locality covers spec text and tests ----------


def test_evidence_into_spec_text_and_tests_is_line_local() -> None:
    from backstitch.analysis_llm import analyze_packets

    packet = _full_packet(
        section_start_line=10,
        section_text="## One [X-1]\n\nBody line.",
        tests=["tests/test_x.py"],
    )

    def respond(path: str, line: int) -> str:
        return json.dumps(
            {
                "packet_id": packet["packet_id"],
                "classification": "ok",
                "summary": "fine",
                "evidence": [{"path": path, "line": line}],
            }
        )

    # Spec citation outside the shown section text (lines 10..12): rejected.
    rows, errors = analyze_packets(
        [packet], lambda p: respond("docs/specs/01-x.md", 999999)
    )
    assert rows[0]["classification"] == "ambiguous"
    # Spec citation inside the section text: accepted.
    rows, errors = analyze_packets(
        [packet], lambda p: respond("docs/specs/01-x.md", 11)
    )
    assert rows[0]["classification"] == "ok", errors
    # Tests are named by path only; line evidence into them is fabricated.
    rows, errors = analyze_packets(
        [packet], lambda p: respond("tests/test_x.py", 999999)
    )
    assert rows[0]["classification"] == "ambiguous"
    assert any("fabricated" in e for e in errors)


# --- Round 10 P2: LLM_MODEL overrides analyze.model --------------------------


def test_llm_model_env_overrides_configured_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backstitch.analysis_llm import resolve_model_name

    # [CFG-5] assembly order: CLI > env > config > built-in default.
    monkeypatch.setenv("LLM_MODEL", "from-env")
    assert resolve_model_name(None, configured="from-config") == "from-env"
    assert resolve_model_name("from-cli", configured="from-config") == "from-cli"
    monkeypatch.delenv("LLM_MODEL")
    assert resolve_model_name(None, configured="from-config") == "from-config"
    assert resolve_model_name(None, configured=None) is None


# --- Round 11 P2: empty snippets carry no line evidence ----------------------


def test_empty_owner_snippet_rejects_line_evidence() -> None:
    from backstitch.analysis_llm import analyze_packets

    # Directory mappings produce owners with empty snippets: the path was
    # named, but no line content was shown -- same rule as tests.
    packet = _full_packet(
        owners=[{"path": "pkg/", "symbol": None, "start_line": 1, "snippet": ""}]
    )
    response = json.dumps(
        {
            "packet_id": packet["packet_id"],
            "classification": "ok",
            "summary": "fine",
            "evidence": [{"path": "pkg/", "line": 1}],
        }
    )
    rows, errors = analyze_packets([packet], lambda prompt: response)
    assert rows[0]["classification"] == "ambiguous"
    assert any("fabricated" in e for e in errors)


# --- Round 11 P2: start lines must be positive --------------------------------


def test_non_positive_start_lines_are_invocation_errors(tmp_path: Path) -> None:
    zero_section = _full_packet(section_start_line=0)
    result = _run_analyze(tmp_path, json.dumps(zero_section))
    assert result.returncode == 2
    assert "section_start_line" in result.stderr

    zero_owner = _full_packet(
        owners=[{"path": "p.py", "symbol": None, "start_line": 0, "snippet": "x"}]
    )
    result = _run_analyze(tmp_path, json.dumps(zero_owner))
    assert result.returncode == 2
    assert "owners" in result.stderr


# --- Round 12 P2: packet locators must be non-empty and consistent -----------


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"spec_path": ""}, "spec_path"),
        (
            {"section_id": "", "packet_id": "docs/specs/01-x.md#"},
            "section_id",
        ),
        ({"packet_id": "other.md#Y-9"}, "does not match"),
        (
            {"owners": [{"path": "", "symbol": None, "start_line": 1, "snippet": "x"}]},
            "owners",
        ),
    ],
)
def test_empty_or_mismatched_packet_locators_are_invocation_errors(
    tmp_path: Path, overrides: dict, fragment: str
) -> None:
    result = _run_analyze(tmp_path, json.dumps(_full_packet(**overrides)))
    assert result.returncode == 2
    assert fragment in result.stderr


def test_empty_paths_never_become_evidence_paths() -> None:
    from backstitch.analysis_llm import analyze_packets

    # Library callers can bypass CLI load validation; the evidence
    # boundary itself must not admit "" as a citable path.
    packet = _full_packet(
        spec_path="",
        owners=[{"path": "", "symbol": None, "start_line": 1, "snippet": "x"}],
    )
    response = json.dumps(
        {
            "packet_id": packet["packet_id"],
            "classification": "ok",
            "summary": "fine",
            "evidence": [{"path": "", "line": 1}],
        }
    )
    rows, errors = analyze_packets([packet], lambda prompt: response)
    assert rows[0]["classification"] == "ambiguous"


# --- Round 12 P2: report edges need non-empty locators ------------------------


def test_summarize_rejects_empty_edge_locators(tmp_path: Path) -> None:
    report = {
        "profile": "backstitch-style-v1",
        "repo_root": ".",
        "summary": {"errors": 0, "warnings": 0, "infos": 0},
        "spec_sections": [],
        "code_refs": [],
        "spec_mappings": [],
        "edges": [
            {
                "spec_path": "",
                "section_id": "X-1",
                "kind": "mapping",
                "code_path": "p.py",
                "code_symbol": None,
            }
        ],
        "issues": [],
    }
    _write(tmp_path, "report.json", json.dumps(report))
    _write(
        tmp_path,
        "rows.jsonl",
        json.dumps(
            {
                "packet_id": "#X-1",
                "classification": "ok",
                "summary": "fine",
                "evidence": [],
            }
        )
        + "\n",
    )
    result = run_cli(
        "summarize-analysis",
        "--deterministic-report",
        str(tmp_path / "report.json"),
        "--analysis-results",
        str(tmp_path / "rows.jsonl"),
    )
    assert result.returncode == 2
    assert "edges[0]" in result.stderr
