"""Analysis packet generation tests.

Spec: docs/specs/02-backstitch-core.md [SC-6], [SC-7]
"""

import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from backstitch.analysis_packets import (
    SourceAlignedPacketError,
    generate_source_aligned_packets,
    render_packets_jsonl,
)
from backstitch.artifact_contracts import load_packets_bytes
from backstitch.config import ProfileConfig
from backstitch.markdown_specs import project_section_packet_requirement
from backstitch.models import (
    Issue,
    SourceObligationSkip,
    SpecMapping,
    SpecSection,
    issue_sort_key,
)
from backstitch.obligation_runtime import build_obligation_runtime
from backstitch.profiles import get_profile
from backstitch.semantic_analysis import (
    SemanticAnalysisRequest,
    _packet_report_preflight,
)
from backstitch.semantic_evidence import SemanticResultError, normalize_model_result
from backstitch.semantic_identity import (
    ProviderIdentity,
    RequestIdentity,
    build_inference_identity,
)
from backstitch.semantic_packets import (
    canonical_json_bytes,
    semantic_packet_hash,
    semantic_packet_projection,
)
from backstitch.semantic_reports import (
    PacketReportError,
    build_source_packet_report,
    validate_packet_report,
)
from backstitch.settings import BackstitchSettings

FIXTURES = Path(__file__).parent / "fixtures"
BROKEN = FIXTURES / "traceability_project"
_PREFLIGHT_PROVIDER = ProviderIdentity(
    "controlled",
    "backstitch-tests",
    "controlled-adapter",
    "1",
    "backstitch.controlled",
    1,
    "controlled",
    "controlled",
    "controlled",
)
_PREFLIGHT_REQUEST = RequestIdentity("require", 0.0, 0, 512)

BROKEN_PROFILE = get_profile("backstitch-style-v1").with_overrides(
    spec_roots=("docs/specifications",),
    code_roots=("src", "tests"),
    test_roots=("tests",),
    planned_spec_globs=("docs/specifications/*A-*.md",),
)


def test_compile_source_aligned_packet_uses_runtime_authority_and_v3_shape(
    tmp_path: Path,
) -> None:
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "docs/plans").mkdir(parents=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "docs/specs/01-core.md").write_text(
        "# Core\n\n"
        "## Candidate behavior [CAND-1]\n\n"
        "The candidate returns one.\n\n"
        "_Implementation mapping_:\n\n"
        "- `src/candidates.py::candidate`\n",
        encoding="utf-8",
    )
    source = tmp_path / "src/candidates.py"
    source.write_text(
        "def candidate() -> int:\n"
        '    """Spec: docs/specs/01-core.md [CAND-1]"""\n'
        "    return 1\n\n"
        "def candidate_decoy() -> int:\n"
        "    return 2\n",
        encoding="utf-8",
    )
    profile = ProfileConfig(
        name="packet-v3-test",
        spec_roots=("docs/specs",),
        plan_roots=("docs/plans",),
        code_roots=("src", "tests"),
        test_roots=("tests",),
        planned_spec_globs=(),
        exploratory_spec_globs=(),
    )
    runtime = build_obligation_runtime(tmp_path, profile, BackstitchSettings())

    packets = generate_source_aligned_packets(runtime)

    assert len(packets) == 1
    packet = packets[0]
    assert packet["schema_version"] == 3
    assert packet["packet_id"] == "docs/specs/01-core.md#CAND-1"
    assert packet["packet_id"] == packet["obligation_id"]
    assert packet["readiness"]["gate_state"] == "executable"
    assert packet["requirement"] == {
        "role": "requirement",
        "path": "docs/specs/01-core.md",
        "identity": "CAND-1",
        "title": "Candidate behavior",
        "start_line": 3,
        "end_line": 9,
        "text": (
            "## Candidate behavior [CAND-1]\n\nThe candidate returns one.\n\n\n\n"
        ),
    }
    assert packet["declared_evidence"]
    assert any(
        item["path"] == "src/candidates.py" and item["role"] == "implementation"
        for item in packet["declared_evidence"]
    )
    assert any(
        candidate["candidate_id"]
        for region in packet["counterevidence"]
        for candidate in region["candidates"]
    )
    assert [
        item["source_role"] for item in packet["trace_summary"]["declared_counts"]
    ] == ["implementation", "test", "binding_test"]
    assert [
        item["candidate_kind"] for item in packet["trace_summary"]["candidate_counts"]
    ] == [
        "implementation_definition",
        "test_definition",
        "static_reference",
        "unresolved_reference",
        "report_issue",
    ]
    assert packet["packet_hash"] == semantic_packet_hash(packet)
    assert semantic_packet_projection(packet)["packet_contract_version"] == 3
    assert render_packets_jsonl(packets).endswith("\n")
    loaded = load_packets_bytes(render_packets_jsonl(packets).encode("utf-8"))
    assert len(loaded) == 1
    assert loaded[0].semantic_eligible
    assert loaded[0].cache_eligible
    packet_jsonl = render_packets_jsonl(packets).encode("utf-8")
    report = build_source_packet_report(
        runtime,
        packet_jsonl=packet_jsonl,
        created_at="2026-07-16T12:00:00Z",
    )
    report_row = report.to_dict()
    assert report_row["schema_version"] == 2
    assert report_row["packet_schema_version"] == 3
    assert report_row["scope"] == "source_snapshot"
    assert report_row["packet_count"] == 1
    assert report_row["packet_bytes"] == len(packet_jsonl)
    assert report_row["readiness_counts"]["selected"] == 1
    assert report_row["alignment_audit"][0]["obligation_id"] == packet["packet_id"]
    validate_packet_report(report, packet_jsonl=packet_jsonl, packets=loaded)
    preflight_problems, preflight_report = _packet_report_preflight(
        cast(
            SemanticAnalysisRequest,
            SimpleNamespace(
                packets=loaded,
                packet_jsonl_sha256=hashlib.sha256(packet_jsonl).hexdigest(),
                packet_report=report,
                settings=SimpleNamespace(
                    require_complete=True,
                    required_kinds=("section",),
                    minimum_packets=1,
                    maximum_packets=0,
                    maximum_prompt_bytes=1_000_000,
                ),
            ),
        ),
        tuple(item.to_dict() for item in loaded),
        tuple(
            build_inference_identity(
                item.to_dict(),
                _PREFLIGHT_PROVIDER,
                _PREFLIGHT_REQUEST,
            )
            for item in loaded
        ),
    )
    assert preflight_problems == []
    assert preflight_report == report

    forged = deepcopy(packet)
    forged["readiness"]["disposition"] = "skipped"
    with pytest.raises(ValueError, match="executable obligation"):
        load_packets_bytes(render_packets_jsonl([forged]).encode("utf-8"))

    forged = deepcopy(packet)
    forged["requirement"]["path"] = "docs/specs/forged.md"
    forged["packet_hash"] = semantic_packet_hash(forged)
    with pytest.raises(ValueError, match="section identity"):
        load_packets_bytes(render_packets_jsonl([forged]).encode("utf-8"))

    forged = deepcopy(packet)
    forged["packet_id"] = "docs/specs/01-core.md#bad id"
    forged["obligation_id"] = forged["packet_id"]
    forged["requirement"]["identity"] = "bad id"
    source_rows = {
        canonical_json_bytes(source): source
        for region in forged["declared_evidence"]
        for source in region["sources"]
    }
    state = {
        "obligation_state_version": 1,
        "obligation_id": forged["obligation_id"],
        "kind": forged["kind"],
        "obligation_rung": forged["readiness"]["obligation_rung"],
        "intent_state": forged["readiness"]["intent_state"],
        "alignment_state": forged["readiness"]["alignment_state"],
        "disposition": forged["readiness"]["disposition"],
        "gate_state": forged["readiness"]["gate_state"],
        "required_roles": forged["readiness"]["required_roles"],
        "declared_sources": list(source_rows.values()),
    }
    forged["source_snapshot"]["obligation_state_hash"] = hashlib.sha256(
        canonical_json_bytes(state)
    ).hexdigest()

    forged["packet_hash"] = semantic_packet_hash(forged)
    with pytest.raises(ValueError, match="section identity"):
        load_packets_bytes(render_packets_jsonl([forged]).encode("utf-8"))

    forged = deepcopy(packet)
    forged["declared_evidence"][0]["role"] = "test"
    forged["evidence_regions"] = [
        {**item, "role": "test"} if item["role"] == "implementation" else item
        for item in forged["evidence_regions"]
    ]
    forged["packet_hash"] = semantic_packet_hash(forged)
    with pytest.raises(ValueError, match="model/source roles"):
        load_packets_bytes(render_packets_jsonl([forged]).encode("utf-8"))

    forged = deepcopy(packet)
    duplicate = deepcopy(forged["counterevidence"][0])
    duplicate["candidates"][0]["candidate_id"] = "candidate:sha256:" + "0" * 64
    forged["counterevidence"].append(duplicate)
    forged["counterevidence"].sort(
        key=lambda item: (
            item["path"],
            item["start_line"],
            item["end_line"],
            item["candidates"][0]["candidate_id"],
        )
    )
    forged["evidence_regions"].append(
        {
            "role": "counterevidence",
            "path": duplicate["path"],
            "start_line": duplicate["start_line"],
            "end_line": duplicate["end_line"],
        }
    )
    forged["evidence_regions"].sort(
        key=lambda item: (
            ("requirement", "implementation", "test", "counterevidence").index(
                item["role"]
            ),
            item["path"],
            item["start_line"],
            item["end_line"],
        )
    )
    forged["packet_hash"] = semantic_packet_hash(forged)
    with pytest.raises(ValueError, match="maximally merged"):
        load_packets_bytes(render_packets_jsonl([forged]).encode("utf-8"))

    source_forged = deepcopy(packet)
    source_forged["requirement"]["text"] = source_forged["requirement"]["text"].replace(
        "returns one", "returns two"
    )
    source_forged["packet_hash"] = semantic_packet_hash(source_forged)
    with pytest.raises(PacketReportError, match="byte-match"):
        build_source_packet_report(
            runtime,
            packet_jsonl=render_packets_jsonl([source_forged]).encode("utf-8"),
        )
    counter_region = next(
        item for item in packet["evidence_regions"] if item["role"] == "counterevidence"
    )
    requirement_region = packet["evidence_regions"][0]
    ambiguous = normalize_model_result(
        packet,
        {
            "packet_id": packet["packet_id"],
            "classification": "ambiguous",
            "confidence": 0.5,
            "rationale": "The decoy creates bounded ambiguity.",
            "summary": "Bounded ambiguity remains.",
            "evidence": [requirement_region, counter_region],
        },
        analysis_key="a" * 64,
    )
    assert {item.role for item in ambiguous.evidence} == {
        "requirement",
        "counterevidence",
    }
    with pytest.raises(SemanticResultError, match="implementation"):
        normalize_model_result(
            packet,
            {
                "packet_id": packet["packet_id"],
                "classification": "confirmed_mismatch",
                "confidence": 0.5,
                "rationale": "Counterevidence is not declared implementation.",
                "summary": "Counterevidence cannot satisfy required roles.",
                "evidence": [requirement_region, counter_region],
            },
            analysis_key="b" * 64,
        )

    frozen = render_packets_jsonl(packets)
    source.write_text("raise RuntimeError('after capture')\n", encoding="utf-8")
    assert render_packets_jsonl(generate_source_aligned_packets(runtime)) == frozen


def test_source_aligned_packet_filters_and_orders_relevant_issues(
    tmp_path: Path,
) -> None:
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "docs/specs/01-x.md").write_text(
        "## Contract [X-1]\n\n_Implementation mapping_:\n\n- `pkg/mod.py::run`\n",
        encoding="utf-8",
    )
    (tmp_path / "pkg/mod.py").write_text(
        'def run() -> int:\n    """Spec: docs/specs/01-x.md [X-1]"""\n    return 1\n',
        encoding="utf-8",
    )
    profile = get_profile("backstitch-style-v1").with_overrides(
        spec_roots=("docs/specs",),
        plan_roots=(),
        code_roots=("pkg",),
        test_roots=(),
    )
    runtime = build_obligation_runtime(tmp_path, profile, BackstitchSettings())
    issues = tuple(
        sorted(
            (
                Issue(
                    "MAPPING_SYMBOL_UNRESOLVED",
                    "warning",
                    "z.py",
                    4,
                    "later path",
                    section_id="X-1",
                ),
                Issue(
                    "MAPPING_SYMBOL_UNRESOLVED",
                    "warning",
                    "a.py",
                    None,
                    "null line first",
                    section_id="X-1",
                ),
                Issue(
                    "MAPPING_SYMBOL_UNRESOLVED",
                    "warning",
                    "ignored.py",
                    1,
                    "different obligation",
                    section_id="OTHER-1",
                ),
            ),
            key=issue_sort_key,
        )
    )
    filtered_report = replace(runtime.pipeline.report, issues=issues)
    runtime = replace(
        runtime,
        pipeline=replace(runtime.pipeline, report=filtered_report),
    )

    [packet] = generate_source_aligned_packets(runtime)

    assert [
        (issue["path"], issue["line"], issue["message"]) for issue in packet["issues"]
    ] == [
        ("a.py", None, "null line first"),
        ("z.py", 4, "later path"),
    ]


def test_source_aligned_invariant_packet_sorts_and_deduplicates_module_evidence(
    tmp_path: Path,
) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "pkg/module_owner.py").write_text(
        '"""Invariant: [INV.MODULE.1] module guarantee"""\nVALUE = 1\n',
        encoding="utf-8",
    )
    (tmp_path / "tests/test_z.py").write_text(
        "def test_module_z() -> None:\n"
        '    """Tests-invariant: [INV.MODULE.1]"""\n'
        "    assert True\n",
        encoding="utf-8",
    )
    (tmp_path / "tests/test_a.py").write_text(
        "def test_module_a() -> None:\n"
        '    """Tests-invariant: [INV.MODULE.1]\n'
        "    Tests-invariant: [INV.MODULE.1]\n"
        '    """\n'
        "    assert True\n",
        encoding="utf-8",
    )
    profile = get_profile("backstitch-style-v1").with_overrides(
        spec_roots=(),
        plan_roots=(),
        code_roots=("pkg", "tests"),
        test_roots=("tests",),
    )
    runtime = build_obligation_runtime(tmp_path, profile, BackstitchSettings())

    [packet] = generate_source_aligned_packets(runtime)

    assert packet["packet_id"] == "invariant::INV.MODULE.1"
    assert [
        (item["role"], item["path"], item["start_line"], item["end_line"])
        for item in packet["declared_evidence"]
    ] == [
        ("implementation", "pkg/module_owner.py", 1, 2),
        ("test", "tests/test_a.py", 1, 5),
        ("test", "tests/test_z.py", 1, 3),
    ]
    assert [
        item["source_role"] for item in packet["trace_summary"]["declared_counts"]
    ] == ["implementation", "test", "binding_test"]


def test_cli_packets_fails_fatally_on_packet_budget_without_publication(
    tmp_path: Path,
) -> None:
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "docs/specs/01-x.md").write_text(
        "## Contract [X-1]\n\n"
        + ("required behavior remains complete\n" * 800)
        + "\n_Implementation mapping_:\n\n- `pkg/mod.py::run`\n",
        encoding="utf-8",
    )
    (tmp_path / "pkg/mod.py").write_text(
        'def run() -> int:\n    """Spec: docs/specs/01-x.md [X-1]"""\n    return 1\n',
        encoding="utf-8",
    )
    (tmp_path / ".backstitch.toml").write_text(
        "[profile]\n"
        'spec_roots = ["docs/specs"]\n'
        "plan_roots = []\n"
        'code_roots = ["pkg"]\n'
        "test_roots = []\n\n"
        "[obligations]\n"
        "maximum_packet_bytes = 16384\n",
        encoding="utf-8",
    )
    output = tmp_path / "packets.jsonl"

    settings = BackstitchSettings(
        obligations=replace(
            BackstitchSettings().obligations,
            maximum_packet_bytes=16_384,
        )
    )
    profile = get_profile("backstitch-style-v1").with_overrides(
        spec_roots=("docs/specs",),
        plan_roots=(),
        code_roots=("pkg",),
        test_roots=(),
    )
    runtime = build_obligation_runtime(tmp_path, profile, settings)

    with pytest.raises(SourceAlignedPacketError) as raised:
        generate_source_aligned_packets(runtime)
    assert raised.value.code == "PACKET_BUDGET_EXHAUSTED"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "backstitch",
            "packets",
            "--repo-root",
            str(tmp_path),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "PACKET_BUDGET_EXHAUSTED" in result.stderr
    assert not output.exists()


def test_wrapped_invariant_requirement_keeps_its_true_span_through_packet_load(
    tmp_path: Path,
) -> None:
    """Reproduce finding #1 with a real wrapped declaration and v3 loader.

    The fixture assembles this exact two-line declaration (the display adds a
    space before the colon so the self-corpus parser does not treat the
    reproduction as a live declaration)::

        Invariant : [INV.WRAP .1] the first clause holds and the
        second clause remains part of the same requirement.

    Remove both display-only spaces for the exact fixture bytes. The current
    producer reports only the first line, so the closed v3 packet
    loader rejects the producer's own packet. The fix must preserve both text
    lines and report the true inclusive span without relaxing validation.
    """

    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "docs/specs/01-wrap.md").write_text(
        "## Wrapped invariant [WRAP-1]\n\n"
        "Invariant: [INV.WRAP.1] the first clause holds and the\n"
        "second clause remains part of the same requirement.\n\n"
        "_Implementation mapping_:\n\n"
        "- `pkg/wrapped.py::wrapped`\n",
        encoding="utf-8",
    )
    (tmp_path / "pkg/wrapped.py").write_text(
        "def wrapped() -> bool:\n"
        '    """Spec: docs/specs/01-wrap.md [WRAP-1]"""\n'
        "    return True\n",
        encoding="utf-8",
    )
    (tmp_path / "tests/test_wrapped.py").write_text(
        "def test_wrapped() -> None:\n"
        '    """Tests-invariant: [INV.WRAP.1]"""\n'
        "    assert True\n",
        encoding="utf-8",
    )
    profile = get_profile("backstitch-style-v1").with_overrides(
        spec_roots=("docs/specs",),
        plan_roots=(),
        code_roots=("pkg", "tests"),
        test_roots=("tests",),
    )
    runtime = build_obligation_runtime(tmp_path, profile, BackstitchSettings())

    packet = next(
        row
        for row in generate_source_aligned_packets(runtime)
        if row["packet_id"] == "invariant::INV.WRAP.1"
    )
    requirement = cast(dict[str, object], packet["requirement"])

    assert requirement["text"] == (
        "the first clause holds and the\n"
        "second clause remains part of the same requirement."
    )
    assert (requirement["start_line"], requirement["end_line"]) == (3, 4)
    loaded = load_packets_bytes(render_packets_jsonl([packet]).encode("utf-8"))
    assert loaded[0].semantic_eligible


def test_section_requirement_masks_parser_directives_without_moving_lines() -> None:
    raw = (
        b'## Candidate behavior [CAND-1] <!-- backstitch: skip-obligation [CAND-1] "External owner." -->\r\n'
        b"Behavior text.\r\n"
        b"_Traceability: meta_\r\n"
        b"_Implementation mapping_:\r\n"
        b"- `src/candidate.py::candidate`\r\n"
    )
    section = SpecSection(
        "docs/specs/01-core.md",
        "CAND-1",
        "Candidate behavior",
        1,
        "candidate-behavior",
        "heading",
    )
    mapping = SpecMapping(
        "docs/specs/01-core.md",
        "CAND-1",
        5,
        "src/candidate.py::candidate",
        "path_symbol",
        "src/candidate.py",
        "candidate",
    )
    skip = SourceObligationSkip(
        "docs/specs/01-core.md#CAND-1",
        "CAND-1",
        "CAND-1",
        "External owner.",
        "docs/specs/01-core.md",
        1,
        "heading_html",
    )

    projected = project_section_packet_requirement(
        raw,
        path="docs/specs/01-core.md",
        section=section,
        end_line=5,
        mappings=(mapping,),
        skips=(skip,),
    )

    assert projected.start_line == 1
    assert projected.end_line == 5
    assert projected.text == ("## Candidate behavior [CAND-1]\nBehavior text.\n\n\n")
    assert len(projected.text.split("\n")) == 5


def test_section_requirement_masks_resolved_invariant_targeted_skip() -> None:
    """Reproduce finding #4 without asking packet code to parse directives.

    The parser has already resolved the exact source line
    `_Traceability: skip-obligation [INV.CAND .1] "rareReasonToken"_` (with
    the display-only space removed) to the
    invariant obligation. A model-visible section requirement must mask that
    resolved directive just as it masks a section-targeted directive. The
    reserved marker fallback must also mask the line when no resolved record
    is available; neither the target ID nor the human reason may leak into
    requirement text.
    """

    raw = (
        b"## Candidate behavior [CAND-1]\n"
        b"Behavior text.\n"
        b'_Traceability: skip-obligation [INV.CAND.1] "rareReasonToken"_\n'
    )
    section = SpecSection(
        "docs/specs/01-core.md",
        "CAND-1",
        "Candidate behavior",
        1,
        "candidate-behavior",
        "heading",
    )
    skip = SourceObligationSkip(
        "invariant::INV.CAND.1",
        "INV.CAND.1",
        "INV.CAND.1",
        "rareReasonToken",
        "docs/specs/01-core.md",
        3,
        "traceability",
    )

    projected = project_section_packet_requirement(
        raw,
        path="docs/specs/01-core.md",
        section=section,
        end_line=3,
        mappings=(),
        skips=(skip,),
    )

    assert projected.text == "## Candidate behavior [CAND-1]\nBehavior text.\n"
    assert "INV.CAND.1" not in projected.text
    assert "rareReasonToken" not in projected.text

    unresolved = project_section_packet_requirement(
        raw,
        path="docs/specs/01-core.md",
        section=section,
        end_line=3,
        mappings=(),
        skips=(),
    )
    assert unresolved.text == projected.text


def test_cli_packets_reports_deterministic_debt_without_partial_jsonl(
    tmp_path: Path,
) -> None:
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
    assert result.returncode == 1
    assert result.stderr == ""
    assert not out.exists()


def test_cli_packets_writes_valid_report_and_rejects_same_output_path(
    tmp_path: Path,
) -> None:
    from backstitch.artifact_contracts import load_packets
    from backstitch.semantic_reports import load_packet_report, validate_packet_report

    out = tmp_path / "packets.jsonl"
    report_path = tmp_path / "packet-report.json"
    command = [
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
        "--kind",
        "all",
        "--output",
        str(out),
    ]
    result = subprocess.run(
        [*command, "--report", str(report_path)],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    validate_packet_report(
        load_packet_report(report_path),
        packet_jsonl=out.read_bytes(),
        packets=load_packets(out),
    )

    same = subprocess.run(
        [*command, "--report", str(out)],
        capture_output=True,
        text=True,
    )
    assert same.returncode == 2
    assert "distinct" in same.stderr


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
        "- `pkg/mod.py`\n\n"
        '## Unmapped [X-2] <!-- backstitch: skip-obligation [X-2] "Suppressed fixture debt." -->\n',
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
    assert any(
        item["role"] == "test" and item["path"] == "qa/contract_check.py"
        for item in rows[0]["declared_evidence"]
    )
    assert {
        item["path"]
        for item in rows[0]["declared_evidence"]
        if item["role"] == "implementation"
    } == {"pkg/mod.py"}


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
    report = build_obligation_runtime(
        tmp_path, profile, BackstitchSettings()
    ).pipeline.raw_report
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
    assert all(row["packet_warnings"] == [] for row in rows_by_kind["invariant"])
    assert all(
        {item["role"] for item in row["declared_evidence"]}
        == {"implementation", "test"}
        for row in rows_by_kind["invariant"]
    )
