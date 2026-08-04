"""Expected-red boundary pins for the evidence-spike hardening plan Slice 0.

Plan: docs/plans/2026-07-16-evidence-spike-hardening-plan.md Slice 0

These tests intentionally describe the target behavior before the owning fix
slices land. Each test carries its complete reproduction so the failure remains
understandable without the implementation-review scratchpad.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tomllib
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

import backstitch
from backstitch.analysis_packets import (
    generate_source_aligned_packets,
    render_packets_jsonl,
)
from backstitch.artifact_contracts import load_packets_bytes
from backstitch.canonical import canonical_repository_path, lf_slice
from backstitch.markdown_specs import parse_markdown_spec_bytes
from backstitch.obligation_runtime import build_obligation_runtime
from backstitch.profiles import get_profile
from backstitch.repository_snapshot import (
    SnapshotCaptureError,
    _normalize_lookup_path,
)
from backstitch.semantic_packets import semantic_packet_hash
from backstitch.settings import (
    BackstitchSettings,
    ConfigLoadError,
    ObligationSettings,
    resolve_config,
)


def _write_repo(root: Path, *, mapping_token: str) -> None:
    root.joinpath("docs/specs").mkdir(parents=True)
    root.joinpath("docs/plans").mkdir(parents=True)
    root.joinpath("pkg").mkdir()
    root.joinpath("tests").mkdir()
    root.joinpath(".backstitch.toml").write_text(
        "[profile]\n"
        'name = "backstitch-style-v1"\n'
        'spec_roots = ["docs/specs"]\n'
        'plan_roots = ["docs/plans"]\n'
        'code_roots = ["pkg", "tests"]\n'
        'test_roots = ["tests"]\n',
        encoding="utf-8",
    )
    root.joinpath("docs/specs/01-x.md").write_text(
        "# X\n\n"
        "## Contract [X-1]\n\n"
        "The implementation returns one.\n\n"
        "_Implementation mapping_:\n\n"
        f"- `{mapping_token}`\n",
        encoding="utf-8",
    )


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "backstitch", *args],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    ("separator", "expected_statement", "expected_receipt"),
    (
        ("\r\n", "alpha\nbeta", b"Invariant: [INV.X.1] alpha\r\nbeta\n"),
        ("\r", "alpha\rbeta", b"Invariant: [INV.X.1] alpha\rbeta\n"),
        ("\f", "alpha\fbeta", b"Invariant: [INV.X.1] alpha\fbeta\n"),
        ("\v", "alpha\vbeta", b"Invariant: [INV.X.1] alpha\vbeta\n"),
        ("\x85", "alpha\x85beta", "Invariant: [INV.X.1] alpha\x85beta\n".encode()),
        (
            "\u2028",
            "alpha\u2028beta",
            "Invariant: [INV.X.1] alpha\u2028beta\n".encode(),
        ),
        (
            "\u2029",
            "alpha\u2029beta",
            "Invariant: [INV.X.1] alpha\u2029beta\n".encode(),
        ),
    ),
    ids=("crlf", "bare-cr", "form-feed", "vertical-tab", "nel", "ls", "ps"),
)
def test_markdown_invariant_projection_preserves_lf_physical_coordinates(
    separator: str,
    expected_statement: str,
    expected_receipt: bytes,
) -> None:
    """Slice 7.0 pin for INV.LINE.1 and amended [EVC-9.1].

    Parser text is a projection. Coordinates and receipts continue to address
    the exact raw bytes using LF as the only physical line delimiter. CRLF is
    normalized in requirement text; every other break-like character remains
    literal in-line content.
    """

    source = (
        f"## Contract [X-1]\n\nInvariant: [INV.X.1] alpha{separator}beta\n\nAfter.\n"
    ).encode()

    parsed = parse_markdown_spec_bytes(source, "docs/specs/01-x.md")

    [invariant] = parsed.invariants
    assert invariant.statement == expected_statement
    assert invariant.line == 3
    receipt_end = 4 if separator == "\r\n" else 3
    assert lf_slice(source, 3, receipt_end, policy="strict") == expected_receipt
    assert hashlib.sha256(
        lf_slice(source, 3, receipt_end, policy="strict")
    ).hexdigest() == (hashlib.sha256(expected_receipt).hexdigest())


def test_bare_cr_does_not_shift_subsequent_lf_physical_coordinates() -> None:
    """A parser-only CR line break must map back to the original LF line."""

    source = (
        b"## Contract [X-1]\n\n"
        b"Prelude\ris still one physical line.\n\n"
        b"Invariant: [INV.X.1] exact coordinates\n"
    )

    parsed = parse_markdown_spec_bytes(source, "docs/specs/01-x.md")

    [invariant] = parsed.invariants
    assert invariant.line == 5
    assert lf_slice(source, 5, 5, policy="strict") == (
        b"Invariant: [INV.X.1] exact coordinates\n"
    )


def test_ordinary_lf_markdown_projection_and_receipt_are_unchanged() -> None:
    """Control pin: Slice 7.1 must not rewrite already-canonical LF input."""

    source = b"## Contract [X-1]\n\nInvariant: [INV.X.1] alpha\nbeta\n"

    parsed = parse_markdown_spec_bytes(source, "docs/specs/01-x.md")

    [invariant] = parsed.invariants
    assert invariant.statement == "alpha\nbeta"
    assert invariant.line == 3
    assert lf_slice(source, 3, 4, policy="strict") == (
        b"Invariant: [INV.X.1] alpha\nbeta\n"
    )


@pytest.mark.parametrize("token", ("../escape.py", "/abs/x.py", "src\\util.py"))
def test_malformed_mapping_token_is_a_located_check_finding(
    tmp_path: Path, token: str
) -> None:
    """Reproduce finding #2 through the public check command.

    A repository contains one active section named ``01-x.md`` under the
    fixture's ``docs/specs`` directory and
    line 9 contains exactly one of ``../escape.py``, ``/abs/x.py``, or
    ``src\\util.py`` as its backticked mapping token. Running
    ``backstitch check --format json`` must finish the repository scan, exit 1,
    and report a MAPPING_PATH_* finding whose structured path, line, and message
    name that fixture spec, line 9, and the exact token. Before Slice 3 the
    token reaches snapshot address normalization and check exits 2 without a
    deterministic report.
    """

    _write_repo(tmp_path, mapping_token=token)

    completed = _run_cli("check", "--repo-root", str(tmp_path), "--format", "json")

    assert completed.returncode == 1, completed.stderr
    report = json.loads(completed.stdout)
    issue = next(
        row for row in report["issues"] if row["code"].startswith("MAPPING_PATH_")
    )
    assert issue["path"] == "docs/specs/01-x.md"
    assert issue["line"] == 9
    assert token in issue["message"]


@pytest.mark.parametrize("token", ("../escape.py", "/abs/x.py", "src\\util.py"))
def test_malformed_mapping_token_is_a_located_one_sided_declaration(
    tmp_path: Path, token: str
) -> None:
    """Malformed targets remain raw, located evidence on the affected item."""

    _write_repo(tmp_path, mapping_token=token)

    completed = _run_cli(
        "obligation",
        "docs/specs/01-x.md#X-1",
        "--summarize-evidence",
        "--repo-root",
        str(tmp_path),
        "--format",
        "json",
    )

    assert completed.returncode == 0, completed.stderr
    envelope = json.loads(completed.stdout)
    assert envelope["problems"] == []
    [item] = envelope["result"]["items"]
    assert item["declared_target"] == token
    assert item["path"] == "docs/specs/01-x.md"
    assert item["start_line"] == item["end_line"] == 9
    assert item["reciprocity_state"] == "one_sided"


def _write_path_boundary_repo(root: Path, *, mapping_tokens: tuple[str, ...]) -> None:
    root.joinpath("docs/specs").mkdir(parents=True)
    root.joinpath("docs/plans").mkdir(parents=True)
    root.joinpath("pkg").mkdir()
    root.joinpath("tests").mkdir()
    root.joinpath(".backstitch.toml").write_text(
        "[profile]\n"
        'name = "backstitch-style-v1"\n'
        'spec_roots = ["docs/specs"]\n'
        'plan_roots = ["docs/plans"]\n'
        'code_roots = ["pkg", "tests"]\n'
        'test_roots = ["tests"]\n',
        encoding="utf-8",
    )
    rendered_tokens = "".join(f"- `{token}`\n" for token in mapping_tokens)
    root.joinpath("docs/specs/01-paths.md").write_text(
        "# Paths\n\n"
        "## Broken target [PATH-1]\n\n"
        "The implementation has one target.\n\n"
        "_Implementation mapping_:\n\n"
        f"{rendered_tokens}\n"
        "## Healthy target [PATH-2]\n\n"
        "The implementation returns one.\n\n"
        "_Implementation mapping_:\n\n"
        "- `pkg/good.py::run`\n",
        encoding="utf-8",
    )
    root.joinpath("pkg/good.py").write_text(
        'def run() -> int:\n    """Spec: docs/specs/01-paths.md [PATH-2]"""\n'
        "    return 1\n",
        encoding="utf-8",
    )


def test_dot_prefixed_mapping_normalizes_before_check_and_obligation_resolution(
    tmp_path: Path,
) -> None:
    """[EVC-8.2]/[SC-4]: ``./`` is canonicalized before rung-1 lookup."""

    _write_path_boundary_repo(tmp_path, mapping_tokens=("./pkg",))

    checked = _run_cli("check", "--repo-root", str(tmp_path), "--format", "json")
    listed = _run_cli(
        "obligation",
        "list",
        "--repo-root",
        str(tmp_path),
        "--format",
        "json",
    )

    assert checked.returncode != 2, checked.stderr
    check_report = json.loads(checked.stdout)
    assert not any(
        issue["code"].startswith("MAPPING_PATH_")
        or issue["code"] == "TARGET_PATH_AMBIGUOUS"
        for issue in check_report["issues"]
    )
    mapping = next(
        row for row in check_report["spec_mappings"] if row["section_id"] == "PATH-1"
    )
    assert mapping["target"] == "./pkg"
    assert mapping["target_path"] == "pkg"
    assert any(
        edge["section_id"] == "PATH-1" and edge["code_path"] == "pkg"
        for edge in check_report["edges"]
    )
    assert listed.returncode == 0, listed.stderr
    envelope = json.loads(listed.stdout)
    assert envelope["problems"] == []
    assert envelope["result"] is not None
    assert {
        row["obligation_id"]
        for row in envelope["result"]["entries"]
        if row["entry_type"] == "obligation"
    } >= {
        "docs/specs/01-paths.md#PATH-1",
        "docs/specs/01-paths.md#PATH-2",
    }


@pytest.mark.parametrize(
    "token",
    ("../escape.py", "/abs/x.py", "pkg\\x.py", "pkg//x.py"),
    ids=("dot-dot", "absolute", "backslash", "empty-component"),
)
def test_authorable_malformed_mapping_degrades_per_target_in_both_lanes(
    tmp_path: Path,
    token: str,
) -> None:
    """Malformed authored targets do not turn either batch into exit 2."""

    _write_path_boundary_repo(tmp_path, mapping_tokens=(token,))

    checked = _run_cli("check", "--repo-root", str(tmp_path), "--format", "json")
    listed = _run_cli(
        "obligation",
        "list",
        "--repo-root",
        str(tmp_path),
        "--format",
        "json",
    )

    assert checked.returncode == 1, checked.stderr
    report = json.loads(checked.stdout)
    assert any(
        issue["code"].startswith("MAPPING_PATH_") and token in issue["message"]
        for issue in report["issues"]
    )
    assert listed.returncode == 0, listed.stderr
    envelope = json.loads(listed.stdout)
    assert envelope["problems"] == []
    assert envelope["result"] is not None
    rows = {
        row["obligation_id"]: row
        for row in envelope["result"]["entries"]
        if row["entry_type"] == "obligation"
    }
    assert rows["docs/specs/01-paths.md#PATH-1"]["gate_state"] != "executable"
    assert "docs/specs/01-paths.md#PATH-2" in rows


def test_authored_nul_mapping_preserves_raw_ineligible_evidence(
    tmp_path: Path,
) -> None:
    """Markdown-it replacement must not erase an authored NUL at capture."""

    token = "pkg/\x00x.py"
    _write_path_boundary_repo(tmp_path, mapping_tokens=(token,))

    checked = _run_cli("check", "--repo-root", str(tmp_path), "--format", "json")
    listed = _run_cli(
        "obligation",
        "list",
        "--repo-root",
        str(tmp_path),
        "--format",
        "json",
    )
    summarized = _run_cli(
        "obligation",
        "docs/specs/01-paths.md#PATH-1",
        "--summarize-evidence",
        "--repo-root",
        str(tmp_path),
        "--format",
        "json",
    )

    assert checked.returncode == 1, checked.stderr
    report = json.loads(checked.stdout)
    issue = next(
        row for row in report["issues"] if row["code"].startswith("MAPPING_PATH_")
    )
    assert token in issue["message"]
    assert "\ufffd" not in issue["message"]
    mapping = next(
        row for row in report["spec_mappings"] if row["section_id"] == "PATH-1"
    )
    assert mapping["target"] == token
    assert mapping["target_path"] == token
    assert listed.returncode == 0, listed.stderr
    listed_envelope = json.loads(listed.stdout)
    assert listed_envelope["problems"] == []
    rows = {
        row["obligation_id"]: row
        for row in listed_envelope["result"]["entries"]
        if row["entry_type"] == "obligation"
    }
    assert rows["docs/specs/01-paths.md#PATH-1"]["gate_state"] != "executable"
    assert "docs/specs/01-paths.md#PATH-2" in rows
    assert summarized.returncode == 0, summarized.stderr
    summary_envelope = json.loads(summarized.stdout)
    item = next(
        row
        for row in summary_envelope["result"]["items"]
        if row["declared_target"] == token
    )
    assert item["reciprocity_state"] == "one_sided"
    assert token in item["excerpt"]
    receipt = item["receipt"]
    source = tmp_path.joinpath("docs/specs/01-paths.md").read_bytes()
    receipt_bytes = lf_slice(
        source,
        receipt["start_line"],
        receipt["end_line"],
        policy="strict",
    )
    assert receipt["raw_sha256"] == hashlib.sha256(receipt_bytes).hexdigest()
    assert b"\x00" in receipt_bytes


def test_surrogate_mapping_scalar_is_rejected_at_canonical_boundary() -> None:
    """A UTF-8 Markdown fixture cannot contain a surrogate scalar."""

    assert _normalize_lookup_path("\ud800") is None


@pytest.mark.parametrize(
    ("token", "expected"),
    (
        (".", "."),
        ("./pkg", "pkg"),
        ("pkg/./x.py", "pkg/x.py"),
        ("pkg/", "pkg"),
        ("pkg//", None),
        ("pkg/../x.py", None),
        ("", None),
    ),
)
def test_canonical_repository_path_applies_the_evc82_order(
    token: str,
    expected: str | None,
) -> None:
    normalized = canonical_repository_path(token)
    assert (None if normalized is None else normalized.canonical) == expected


def test_canonical_repository_path_preserves_native_unicode_spelling() -> None:
    normalized = canonical_repository_path("pkg/cafe\u0301.py")
    assert normalized is not None
    assert normalized.native == "pkg/cafe\u0301.py"
    assert normalized.canonical == "pkg/caf\u00e9.py"


@pytest.mark.parametrize(
    "tokens",
    (
        ("./pkg", "pkg"),
        ("pkg/", "./pkg/"),
        ("pkg/caf\u00e9.py", "pkg/cafe\u0301.py"),
    ),
    ids=("dot-normalization", "trailing-slash-normalization", "nfc-normalization"),
)
def test_declared_tokens_colliding_on_one_canonical_path_fail_capture(
    tmp_path: Path,
    tokens: tuple[str, str],
) -> None:
    """[EVC-8.2] rejects collisions instead of silently coalescing tokens."""

    _write_path_boundary_repo(tmp_path, mapping_tokens=tokens)
    if tokens[0].startswith("pkg/caf"):
        tmp_path.joinpath("pkg/caf\u00e9.py").write_text("VALUE = 1\n")

    for args in (
        ("check", "--repo-root", str(tmp_path), "--format", "json"),
        (
            "obligation",
            "list",
            "--repo-root",
            str(tmp_path),
            "--format",
            "json",
        ),
    ):
        completed = _run_cli(*args)
        assert completed.returncode == 2


def test_identical_raw_paths_with_different_symbols_remain_legal(
    tmp_path: Path,
) -> None:
    """Collision detection precedes path coalescing but ignores symbol suffixes."""

    _write_path_boundary_repo(
        tmp_path,
        mapping_tokens=("pkg/good.py::run", "pkg/good.py::missing"),
    )

    checked = _run_cli("check", "--repo-root", str(tmp_path), "--format", "json")
    listed = _run_cli(
        "obligation",
        "list",
        "--repo-root",
        str(tmp_path),
        "--format",
        "json",
    )

    assert checked.returncode != 2, checked.stderr
    assert listed.returncode == 0, listed.stderr


def test_multiple_malformed_mapping_tokens_do_not_fail_obligation_batch(
    tmp_path: Path,
) -> None:
    """Malformed targets leave the success envelope free of mixed problems."""

    _write_repo(tmp_path, mapping_token="../first.py")
    tmp_path.joinpath("docs/specs/01-x.md").write_text(
        "# X\n\n"
        "## Contract [X-1]\n\n"
        "The implementation returns one.\n\n"
        "_Implementation mapping_:\n\n"
        "- `/second.py`\n"
        "- `../first.py`\n",
        encoding="utf-8",
    )

    completed = _run_cli(
        "obligation",
        "list",
        "--repo-root",
        str(tmp_path),
        "--format",
        "json",
    )

    assert completed.returncode == 0, completed.stderr
    envelope = json.loads(completed.stdout)
    assert envelope["problems"] == []
    assert envelope["result"] is not None
    [row] = [
        row
        for row in envelope["result"]["entries"]
        if row["entry_type"] == "obligation"
    ]
    assert row["gate_state"] != "executable"


def test_concrete_obligation_dataclass_defaults_equal_packaged_defaults(
    tmp_path: Path,
) -> None:
    """Tests-invariant: [INV.CFG.2]

    Reproduce finding #7 by comparing both owners of concrete defaults.

    Construct ``ObligationSettings()`` directly, then load settings with no
    repository configuration so only packaged ``backstitch/defaults.toml`` is
    effective. Every field in this dataclass has a concrete default and the two
    complete dictionaries must be equal. Before Slice 3 the dataclass says
    ``maximum_lexical_seeds=100`` while packaged TOML says 10.
    """

    packaged = resolve_config(tmp_path, use_repo_config=False).obligations

    assert asdict(ObligationSettings()) == asdict(packaged)


def test_packet_warnings_is_not_an_advertised_analyzer_setting(
    tmp_path: Path,
) -> None:
    """Reproduce finding #10 at both configuration boundaries.

    The packaged ``backstitch/defaults.toml`` must not advertise
    ``analyze.packet_warnings``, and an explicit repository config using
    ``packet_warnings = "error"`` must fail as an unknown key. Schema-3 packet
    warnings are required empty by [EVC-9.1], so there is no conforming event
    this setting could control. Before Slice 2 the key is packaged, parsed,
    hashed, and accepted despite having no reachable effect.
    """

    defaults_path = Path(backstitch.__file__).with_name("defaults.toml")
    defaults = tomllib.loads(defaults_path.read_text(encoding="utf-8"))
    assert "packet_warnings" not in defaults["analyze"]
    assert not hasattr(
        resolve_config(tmp_path, use_repo_config=False).analyze, "packet_warnings"
    )

    tmp_path.joinpath(".backstitch.toml").write_text(
        '[analyze]\npacket_warnings = "error"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigLoadError, match="packet_warnings"):
        resolve_config(tmp_path)


def test_schema3_loader_rejects_nonempty_packet_warnings(tmp_path: Path) -> None:
    """Reproduce finding #10 at the closed schema-3 packet boundary.

    Build one real current-repository packet, replace its exact empty warning
    list with ``["degraded evidence"]``, and recompute the packet hash. Loading
    must still reject the row: a valid hash cannot make a nonempty schema-3
    compatibility field conforming. Before Slice 2 the closed loader accepts
    the warning even though no producer can emit it and no analyzer setting can
    reach a meaningful policy branch.
    """

    _write_repo(tmp_path, mapping_token="pkg/x.py::run")
    tmp_path.joinpath("pkg/x.py").write_text(
        'def run() -> int:\n    """Spec: docs/specs/01-x.md [X-1]"""\n    return 1\n',
        encoding="utf-8",
    )
    profile = get_profile("backstitch-style-v1").with_overrides(
        spec_roots=("docs/specs",),
        plan_roots=("docs/plans",),
        code_roots=("pkg", "tests"),
        test_roots=("tests",),
    )
    runtime = build_obligation_runtime(tmp_path, profile, BackstitchSettings())
    [packet] = generate_source_aligned_packets(runtime)
    packet["packet_warnings"] = ["degraded evidence"]
    packet["packet_hash"] = semantic_packet_hash(packet)

    with pytest.raises(ValueError, match="packet_warnings"):
        load_packets_bytes(render_packets_jsonl([packet]).encode("utf-8"))


@pytest.mark.parametrize("failure_kind", ("snapshot", "discovery"))
def test_packets_maps_typed_repository_failures_without_internal_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure_kind: str,
) -> None:
    """Reproduce finding #8 at the packets command's two typed seams.

    Build a clean reciprocal repository, then inject snapshot instability or
    configure a real discovery-catalog overflow. Calling ``packets`` must exit
    2 with a specific one-line diagnostic and no ``internal error`` label.
    """

    _write_repo(tmp_path, mapping_token="pkg/x.py::run")
    tmp_path.joinpath("pkg/x.py").write_text(
        'def run() -> int:\n    """Spec: docs/specs/01-x.md [X-1]"""\n    return 1\n',
        encoding="utf-8",
    )
    from backstitch import obligation_runtime
    from backstitch.cli import main

    if failure_kind == "snapshot":

        def fail_runtime(*_args: object, **_kwargs: object) -> Any:
            raise SnapshotCaptureError(
                "snapshot_unstable",
                "SNAPSHOT_UNSTABLE after 3 capture attempts",
                attempts=3,
            )

        monkeypatch.setattr(
            obligation_runtime, "build_obligation_runtime", fail_runtime
        )
        expected = "SNAPSHOT_UNSTABLE"
    else:
        with tmp_path.joinpath(".backstitch.toml").open(
            "a", encoding="utf-8"
        ) as config:
            config.write("\n[obligations]\nmaximum_candidate_items = 1\n")
        tmp_path.joinpath("pkg/x.py").write_text(
            "def run() -> int:\n"
            '    """Spec: docs/specs/01-x.md [X-1]"""\n'
            "    return 1\n\n"
            "def nearby_candidate_one() -> int:\n"
            "    return 1\n\n"
            "def nearby_candidate_two() -> int:\n"
            "    return 1\n",
            encoding="utf-8",
        )
        expected = "candidate_items"

    exit_code = main(
        [
            "packets",
            "--repo-root",
            str(tmp_path),
            "--output",
            str(tmp_path / "packets.jsonl"),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "internal error" not in captured.err
    assert expected in captured.err


def test_packets_partial_publication_reports_failed_and_prior_paths(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Keep packet publication accounting equal to current analyze."""

    _write_repo(tmp_path, mapping_token="pkg/x.py::run")
    with tmp_path.joinpath(".backstitch.toml").open("a", encoding="utf-8") as config:
        config.write('\n[obligations]\nsection_required_roles = ["implementation"]\n')
    tmp_path.joinpath("pkg/x.py").write_text(
        'def run() -> int:\n    """Spec: docs/specs/01-x.md [X-1]"""\n    return 1\n',
        encoding="utf-8",
    )
    packets = tmp_path / "artifacts/packets.jsonl"
    report = tmp_path / "artifacts/packet-report.json"
    from backstitch.cli import main

    report.mkdir(parents=True)

    exit_code = main(
        [
            "packets",
            "--repo-root",
            str(tmp_path),
            "--output",
            str(packets),
            "--kind",
            "all",
            "--report",
            str(report),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 2
    assert packets.exists(), captured.err
    assert report.is_dir()
    assert str(report) in captured.err
    assert str(packets) in captured.err
    assert "already published" in captured.err
    assert tuple((tmp_path / "artifacts").glob(".*.tmp")) == ()


def test_current_analyze_maps_discovery_failure_without_internal_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Reproduce finding #8 on current-repository analyze packet discovery.

    Build a clean reciprocal repository and exhaust the real candidate catalog
    before any provider call. JSON analysis must return one structured
    preparation failure on stdout.
    """

    _write_repo(tmp_path, mapping_token="pkg/x.py::run")
    tmp_path.joinpath("pkg/x.py").write_text(
        'def run() -> int:\n    """Spec: docs/specs/01-x.md [X-1]"""\n    return 1\n',
        encoding="utf-8",
    )
    from backstitch.cli import main

    with tmp_path.joinpath(".backstitch.toml").open("a", encoding="utf-8") as config:
        config.write("\n[obligations]\nmaximum_candidate_items = 1\n")
    tmp_path.joinpath("pkg/x.py").write_text(
        "def run() -> int:\n"
        '    """Spec: docs/specs/01-x.md [X-1]"""\n'
        "    return 1\n\n"
        "def nearby_candidate_one() -> int:\n"
        "    return 1\n\n"
        "def nearby_candidate_two() -> int:\n"
        "    return 1\n",
        encoding="utf-8",
    )

    exit_code = main(["analyze", "--repo-root", str(tmp_path), "--format", "json"])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert captured.err == ""
    failure = json.loads(captured.out)
    assert [problem["code"] for problem in failure["problems"]] == ["BUDGET_EXHAUSTED"]
    assert failure["problems"][0]["details"]["budget"] == "candidate_items"


def test_packets_deterministic_debt_exit_one_renders_the_report(
    tmp_path: Path,
) -> None:
    """Reproduce finding #9 for both current-repository semantic commands.

    The only section maps line 9 to absent ``pkg/missing.py::run``, producing a
    deterministic MAPPING_PATH_MISSING error before packet generation or model
    work. Running either ``packets`` or current ``analyze`` must exit 1 and
    render the deterministic report to stdout, including the code, source path,
    and mapping token. Before Slice 3 both handlers return 1 before rendering,
    so stdout and stderr are empty.
    """

    _write_repo(tmp_path, mapping_token="pkg/missing.py::run")
    args = [
        "packets",
        "--repo-root",
        str(tmp_path),
        "--output",
        str(tmp_path / "packets.jsonl"),
    ]

    completed = _run_cli(*args)

    assert completed.returncode == 1, completed.stderr
    assert "MAPPING_PATH_MISSING" in completed.stdout
    assert "docs/specs/01-x.md" in completed.stdout
    assert "pkg/missing.py::run" in completed.stdout


def test_analyze_deterministic_debt_stops_at_structured_preflight(
    tmp_path: Path,
) -> None:
    """Current analysis reports readiness before packet generation."""

    _write_repo(tmp_path, mapping_token="pkg/missing.py::run")

    completed = _run_cli(
        "analyze",
        "--repo-root",
        str(tmp_path),
        "--format",
        "json",
    )

    assert completed.returncode == 2
    assert completed.stderr == ""
    preflight = json.loads(completed.stdout)
    assert preflight["operation"] == "analysis.preflight"
    assert [problem["code"] for problem in preflight["problems"]] == ["ALIGNMENT_DEBT"]
    assert preflight["problems"][0]["details"]["obligation_ids"] == [
        "docs/specs/01-x.md#X-1"
    ]


def _legacy_packet(packet_id: str) -> dict[str, Any]:
    packet: dict[str, Any] = {
        "schema_version": 2,
        "packet_id": packet_id,
        "kind": "section",
        "spec_path": "docs/specs/01-x.md",
        "section_id": "X-1",
        "title": "Contract",
        "section_text": "## Contract [X-1]\n\nReturn one.",
        "section_start_line": 3,
        "owners": [
            {
                "path": "pkg/x.py",
                "symbol": "run",
                "start_line": 1,
                "snippet": "def run() -> int:\n    return 1",
            }
        ],
        "tests": [],
        "issues": [],
        "packet_warnings": [],
    }
    packet["packet_hash"] = semantic_packet_hash(packet)
    return packet


def test_nonsemantic_unreadable_additional_path_does_not_poison_discovery(
    tmp_path: Path,
) -> None:
    """Reproduce NM4 with an unreadable row outside semantic file kinds.

    Build the standard evidence-discovery repository, capture an additional
    ``assets/blob.bin`` whose permission bits make it unreadable, and run
    section candidate discovery. Since ``.bin`` is neither Markdown under a
    spec/plan root nor Python under a code/test root, UTF-8/readability
    validation must filter it out and discovery must still return candidates.
    Before Slice 3 ``_validate_semantic_utf8`` rejects ``raw_bytes is None``
    before calculating that semantic-file predicate, raising SOURCE_UNREADABLE.
    """

    from backstitch.evidence_discovery import discover_evidence_candidates
    from backstitch.repository_snapshot import capture_repository_snapshot
    from tests.test_evidence_discovery import (
        ALGORITHMS,
        PROFILE,
        SETTINGS,
        _obligation,
        _section_report,
        _snapshot_config,
        _write_repository,
    )

    _write_repository(tmp_path)
    blob = tmp_path / "assets/blob.bin"
    blob.parent.mkdir()
    blob.write_bytes(b"not semantic\n")
    blob.chmod(0)
    try:
        snapshot = capture_repository_snapshot(
            tmp_path,
            _snapshot_config(),
            ALGORITHMS,
            additional_paths=("assets/blob.bin",),
        )
    finally:
        blob.chmod(0o600)

    candidates = discover_evidence_candidates(
        snapshot,
        _section_report(),
        PROFILE,
        _obligation(),
        SETTINGS,
    )

    assert candidates


def test_mid_read_growth_is_torn_capture_before_file_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reproduce the budget-vs-torn race inside one bounded file read.

    Inventory ``src/a.py`` at exactly four bytes with
    ``maximum_file_bytes=4``. On the first descriptor read, append one byte via
    another descriptor after the opening fstat has matched inventory. With one
    capture attempt, this is a changed-file/torn attempt and must raise
    ``SnapshotCaptureError(kind="snapshot_unstable", attempts=1)``. Before
    Slice 3 `_bounded_read_attempt` sees the fifth byte and raises
    ``budget_exceeded`` before comparing the closing fstat.
    """

    import backstitch.repository_snapshot as repository_snapshot
    from backstitch.repository_snapshot import (
        SnapshotAlgorithms,
        SnapshotSemanticConfig,
        capture_repository_snapshot,
    )

    source = tmp_path / "src/a.py"
    source.parent.mkdir()
    source.write_bytes(b"four")
    config = SnapshotSemanticConfig(
        profile_name="test-v1",
        spec_roots=("docs/specs",),
        plan_roots=("docs/plans",),
        code_roots=("src",),
        test_roots=(),
        exclusions=(),
        planned_spec_globs=(),
        exploratory_spec_globs=(),
        section_required_roles=("implementation",),
        maximum_candidate_items=100,
        maximum_catalog_items=100,
        maximum_lexical_seeds=10,
        maximum_snapshot_files=10,
        maximum_file_bytes=4,
        maximum_snapshot_bytes=100,
        maximum_work_units=100,
        maximum_packet_bytes=16_384,
        maximum_packet_report_bytes=16_384,
        static_neighbor_depth=1,
    )
    algorithms = SnapshotAlgorithms(1, 1, 1, 3, 1)
    real_read = os.read
    mutated = False

    def grow_then_read(descriptor: int, byte_count: int) -> bytes:
        nonlocal mutated
        if not mutated:
            source.write_bytes(b"four+")
            mutated = True
        return real_read(descriptor, byte_count)

    monkeypatch.setattr(repository_snapshot.os, "read", grow_then_read)

    with pytest.raises(SnapshotCaptureError) as caught:
        capture_repository_snapshot(
            tmp_path,
            config,
            algorithms,
            capture_attempts=1,
        )

    assert caught.value.kind == "snapshot_unstable"
    assert caught.value.attempts == 1
