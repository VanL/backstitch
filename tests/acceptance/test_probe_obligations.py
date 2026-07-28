"""Public obligation bootstrap probes ([EVC-12])."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tests.acceptance.conftest import REPO_ROOT, run_cli


def test_public_help_teaches_obligation_and_alignment_guide() -> None:
    result = run_cli("--help")

    assert result.returncode == 0
    assert "obligation" in result.stdout
    assert "guide" in result.stdout

    obligation = run_cli("obligation", "--help")
    assert obligation.returncode == 0
    assert "list" in obligation.stdout
    assert "--summarize-evidence" in obligation.stdout
    assert "--find-evidence" in obligation.stdout
    assert "--candidate" in obligation.stdout

    guide = run_cli("guide", "alignment", "--format", "json")
    assert guide.returncode == 0
    artifact = json.loads(guide.stdout)
    assert set(artifact) == {
        "guide_schema_version",
        "guide_id",
        "guide_version",
        "backstitch_version",
        "content_sha256",
        "content",
    }
    assert artifact["guide_id"] == "alignment"
    assert artifact["guide_version"] == 2
    assert artifact["content_sha256"] == (
        "195587dac2541df9a367c6f65347eefccde06236ef16a1fb0e07861774ae3dcb"
    )
    assert (
        artifact["content_sha256"]
        == hashlib.sha256(artifact["content"].encode("utf-8")).hexdigest()
    )
    for required_form in (
        "_Implementation mapping_:",
        "Spec: docs/specs/01-widget.md [WIDGET-1]",
        "Invariant: [INV.WIDGET.1]",
        "Tests-invariant: [INV.WIDGET.1]",
        "mapping, backlink, invariant-target, or binding-test guidance",
        "regular parseable Python file",
        "exact owner or the whole module",
        "the Python owner",
        "already the implementation target",
        "section mapping/backlink",
        "remove both sides together",
        "Human approval remains the authority",
        "backstitch check --repo-root . --show-suppressions",
        "authorized coding agent may prepare or apply an ordinary source diff",
        "Backstitch itself remains read-only",
        "not ratified or landed until a human reviews it",
        "Use two separate phases. Bootstrap asks",
        "snapshot-bound report",
        "consume an earlier candidate report",
        "skip-obligation [WIDGET-1]",
        "`declared`:",
        "`partially_declared`:",
        "`untraced`:",
        "`conflicted`:",
        "backstitch analyze --repo-root PATH",
    ):
        assert required_form in artifact["content"]


def test_repository_alignment_skill_teaches_the_same_authority_boundary() -> None:
    skill = (REPO_ROOT / "skills/backstitch-alignment/SKILL.md").read_text("utf-8")
    metadata = (REPO_ROOT / "skills/backstitch-alignment/agents/openai.yaml").read_text(
        "utf-8"
    )

    for required_instruction in (
        "mapping, backlink, invariant-target, or binding-test guidance",
        "Treat bootstrap and gate as separate phases",
        "Rerun discovery after source changes",
        "evidence-selection authority",
        "remove both sides together",
        "backstitch check --repo-root . --show-suppressions",
        "within the caller's authority",
        "Backstitch itself remains read-only",
        "not ratified or landed until a human reviews it",
        "Human approval remains the authority",
    ):
        assert required_instruction in skill
    assert "$backstitch-alignment" in metadata


def test_obligation_list_bootstraps_empty_repository(tmp_path: Path) -> None:
    for relative in ("docs/specs", "docs/plans", "pkg", "tests"):
        (tmp_path / relative).mkdir(parents=True, exist_ok=True)
    (tmp_path / ".backstitch.toml").write_text(
        "[profile]\n"
        'name = "backstitch-style-v1"\n'
        'spec_roots = ["docs/specs"]\n'
        'plan_roots = ["docs/plans"]\n'
        'code_roots = ["pkg", "tests"]\n'
        'test_roots = ["tests"]\n',
        encoding="utf-8",
    )

    result = run_cli(
        "obligation",
        "list",
        "--repo-root",
        str(tmp_path),
        "--format",
        "json",
    )

    assert result.returncode == 0, result.stderr
    envelope = json.loads(result.stdout)
    assert envelope["schema_version"] == 1
    assert envelope["operation"] == "obligation.list"
    assert envelope["snapshot"]["file_count"] == 1
    assert envelope["snapshot"]["unreadable_count"] == 0
    assert envelope["result"] == {
        "bootstrap_state": "no_intent",
        "entries": [],
        "next_cursor": None,
    }
    assert [item["code"] for item in envelope["guidance"]] == [
        "ADD_OR_CONFIGURE_SPEC_INTENT"
    ]
    assert envelope["problems"] == []


def test_obligation_list_reports_invalid_heading_with_exact_captured_excerpt(
    tmp_path: Path,
) -> None:
    for relative in ("docs/specs", "docs/plans", "pkg", "tests"):
        (tmp_path / relative).mkdir(parents=True, exist_ok=True)
    (tmp_path / ".backstitch.toml").write_text(
        "[profile]\n"
        'name = "backstitch-style-v1"\n'
        'spec_roots = ["docs/specs"]\n'
        'plan_roots = ["docs/plans"]\n'
        'code_roots = ["pkg", "tests"]\n'
        'test_roots = ["tests"]\n',
        encoding="utf-8",
    )
    excerpt = "## Broken contract [not-an-id]"
    (tmp_path / "docs/specs/01-broken.md").write_text(
        f"# Ordinary title\n\n{excerpt}\n\n"
        "## Ordinary ID-less prose\n\n"
        "```markdown\n## Example [also-not-an-id]\n```\n\n"
        "~~~markdown\n## Example [still-not-an-id]\n~~~\n",
        encoding="utf-8",
    )

    result = run_cli(
        "obligation",
        "list",
        "--repo-root",
        str(tmp_path),
        "--format",
        "json",
    )

    assert result.returncode == 0, result.stderr
    envelope = json.loads(result.stdout)
    [entry] = envelope["result"]["entries"]
    assert entry["entry_type"] == "unaddressable_intent"
    assert entry["diagnostic"] == {
        "code": "SPEC_SECTION_HEADING_INVALID",
        "path": "docs/specs/01-broken.md",
        "line": 3,
        "message": "ID-bearing Markdown heading has an invalid or missing section ID",
    }
    assert entry["excerpt"] == excerpt
    assert entry["action"] == "FIX_OBLIGATION_IDENTITY"
    assert envelope["result"]["bootstrap_state"] == "intent_found"


def test_obligation_detail_reports_source_declared_alignment_and_skip(
    tmp_path: Path,
) -> None:
    for relative in ("docs/specs", "docs/plans", "pkg", "tests"):
        (tmp_path / relative).mkdir(parents=True, exist_ok=True)
    (tmp_path / ".backstitch.toml").write_text(
        "[profile]\n"
        'name = "backstitch-style-v1"\n'
        'spec_roots = ["docs/specs"]\n'
        'plan_roots = ["docs/plans"]\n'
        'code_roots = ["pkg", "tests"]\n'
        'test_roots = ["tests"]\n',
        encoding="utf-8",
    )
    (tmp_path / "docs/specs/01-x.md").write_text(
        "# X\n\n"
        "## Contract [X-1] <!-- backstitch: skip-obligation [X-1] "
        '"External owner." -->\n\n'
        "_Implementation mapping_:\n\n- `pkg/x.py::run`\n",
        encoding="utf-8",
    )
    (tmp_path / "pkg/x.py").write_text(
        'def run() -> None:\n    """Spec: docs/specs/01-x.md [X-1]"""\n    pass\n',
        encoding="utf-8",
    )

    result = run_cli(
        "obligation",
        "docs/specs/01-x.md#X-1",
        "--repo-root",
        str(tmp_path),
        "--format",
        "json",
    )

    assert result.returncode == 0, result.stderr
    envelope = json.loads(result.stdout)
    assert envelope["operation"] == "obligation.get"
    assert envelope["result"]["alignment_state"] == "complete"
    assert envelope["result"]["disposition"] == "skipped"
    assert envelope["result"]["gate_state"] == "not_executable"
    assert [row["code"] for row in envelope["result"]["blocking_reasons"]] == [
        "SKIPPED"
    ]
    review_skip = next(
        row for row in envelope["guidance"] if row["code"] == "REVIEW_SKIP_REASON"
    )
    assert "backstitch check --show-suppressions" in review_skip["action"]

    listed = run_cli(
        "obligation",
        "list",
        "--repo-root",
        str(tmp_path),
        "--format",
        "text",
    )
    assert listed.returncode == 0, listed.stderr
    assert "complete skipped active not_executable" in listed.stdout

    summary = run_cli(
        "obligation",
        "docs/specs/01-x.md#X-1",
        "--summarize-evidence",
        "--repo-root",
        str(tmp_path),
        "--format",
        "text",
    )
    assert summary.returncode == 0, summary.stderr
    assert "disposition: skipped" in summary.stdout

    audit = run_cli(
        "check",
        "--repo-root",
        str(tmp_path),
        "--show-suppressions",
        "--format",
        "json",
    )
    assert audit.returncode == 0, audit.stderr
    audit_payload = json.loads(audit.stdout)
    assert audit_payload["obligation_skips"] == [
        {
            "effective_policy": "info",
            "line": 3,
            "obligation_id": "docs/specs/01-x.md#X-1",
            "path": "docs/specs/01-x.md",
            "reason": "External owner.",
            "target_id": "X-1",
        }
    ]


def test_unknown_obligation_is_a_closed_not_found_problem(tmp_path: Path) -> None:
    for relative in ("docs/specs", "docs/plans", "pkg", "tests"):
        (tmp_path / relative).mkdir(parents=True, exist_ok=True)

    result = run_cli(
        "obligation",
        "docs/specs/none.md#NOPE",
        "--repo-root",
        str(tmp_path),
        "--no-config",
        "--format",
        "json",
    )

    assert result.returncode == 2
    envelope = json.loads(result.stdout)
    assert envelope["operation"] == "obligation.get"
    assert envelope["snapshot"] is not None
    assert envelope["result"] is None
    assert envelope["guidance"] == []
    assert envelope["problems"][0]["code"] == "NOT_FOUND"
    assert envelope["problems"][0]["details"] == {"identity": "docs/specs/none.md#NOPE"}
    assert result.stderr == ""


def test_evidence_summary_points_to_exact_reciprocal_source_span(
    tmp_path: Path,
) -> None:
    for relative in ("docs/specs", "docs/plans", "pkg", "tests"):
        (tmp_path / relative).mkdir(parents=True, exist_ok=True)
    (tmp_path / ".backstitch.toml").write_text(
        "[profile]\n"
        'name = "backstitch-style-v1"\n'
        'spec_roots = ["docs/specs"]\n'
        'plan_roots = ["docs/plans"]\n'
        'code_roots = ["pkg", "tests"]\n'
        'test_roots = ["tests"]\n',
        encoding="utf-8",
    )
    (tmp_path / "docs/specs/01-x.md").write_text(
        "# X\n\n## Contract [X-1]\n\n_Implementation mapping_:\n\n- `pkg/x.py::run`\n",
        encoding="utf-8",
    )
    source = (
        'def run() -> int:\n    """Spec: docs/specs/01-x.md [X-1]"""\n    return 1\n'
    )
    (tmp_path / "pkg/x.py").write_text(source, encoding="utf-8")

    result = run_cli(
        "obligation",
        "docs/specs/01-x.md#X-1",
        "--summarize-evidence",
        "--repo-root",
        str(tmp_path),
        "--format",
        "json",
    )

    assert result.returncode == 0, result.stderr
    envelope = json.loads(result.stdout)
    assert envelope["operation"] == "obligation.summarize_evidence"
    assert envelope["result"]["alignment_state"] == "complete"
    assert envelope["result"]["disposition"] == "evaluate"
    assert envelope["result"]["next_cursor"] is None
    [item] = envelope["result"]["items"]
    assert item["role"] == "implementation"
    assert item["path"] == "pkg/x.py"
    assert item["symbol"] == "run"
    assert item["owner"] == "run"
    assert (item["start_line"], item["end_line"]) == (1, 3)
    assert item["relation_kinds"] == ["spec_mapping", "code_backlink"]
    assert item["reciprocity_state"] == "complete"
    assert [
        (row["relation_kind"], row["path"], row["line"]) for row in item["declarations"]
    ] == [
        ("spec_mapping", "docs/specs/01-x.md", 7),
        ("code_backlink", "pkg/x.py", 2),
    ]
    assert item["receipt"] == {
        "receipt_version": 1,
        "path": "pkg/x.py",
        "structural_locator": "python-definition:run:function:0",
        "start_line": 1,
        "end_line": 3,
        "raw_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
    }
    assert item["excerpt"] == source

    text = run_cli(
        "obligation",
        "docs/specs/01-x.md#X-1",
        "--summarize-evidence",
        "--repo-root",
        str(tmp_path),
        "--format",
        "text",
    )
    assert text.returncode == 0, text.stderr
    assert "declaration spec_mapping docs/specs/01-x.md:7" in text.stdout
    assert "declaration code_backlink pkg/x.py:2" in text.stdout


def test_invariant_readiness_requires_atomic_target_and_keeps_bad_mapping_honest(
    tmp_path: Path,
) -> None:
    for relative in ("docs/specs", "docs/plans", "pkg", "tests"):
        (tmp_path / relative).mkdir(parents=True, exist_ok=True)
    (tmp_path / ".backstitch.toml").write_text(
        "[profile]\n"
        'spec_roots = ["docs/specs"]\n'
        'plan_roots = ["docs/plans"]\n'
        'code_roots = ["pkg", "tests"]\n'
        'test_roots = ["tests"]\n',
        encoding="utf-8",
    )
    (tmp_path / "docs/specs/x.md").write_text(
        "## Contract [X-1]\n\n"
        "Invariant: [INV.X.1] The result remains stable.\n\n"
        "_Implementation mapping_:\n\n"
        "- `pkg/`\n",
        encoding="utf-8",
    )
    (tmp_path / "tests/test_x.py").write_text(
        "def test_result() -> None:\n"
        '    """Tests-invariant: [INV.X.1]"""\n'
        "    assert True\n",
        encoding="utf-8",
    )

    detail = run_cli(
        "obligation",
        "invariant::INV.X.1",
        "--repo-root",
        str(tmp_path),
        "--format",
        "json",
    )
    assert detail.returncode == 0, detail.stdout + detail.stderr
    detail_result = json.loads(detail.stdout)["result"]
    assert detail_result["alignment_state"] == "partial"
    assert detail_result["gate_state"] == "not_executable"
    assert detail_result["evidence_counts"] == {
        "implementation": 1,
        "test": 0,
        "binding_test": 1,
    }
    assert [row["code"] for row in detail_result["blocking_reasons"]] == [
        "INVARIANT_TARGET_MISSING"
    ]

    summary = run_cli(
        "obligation",
        "invariant::INV.X.1",
        "--summarize-evidence",
        "--repo-root",
        str(tmp_path),
        "--format",
        "json",
    )
    assert summary.returncode == 0, summary.stdout + summary.stderr
    items = json.loads(summary.stdout)["result"]["items"]
    rejected = next(item for item in items if item["role"] == "implementation")
    assert rejected["path"] == "docs/specs/x.md"
    assert rejected["declared_target"] == "pkg/"
    assert rejected["reciprocity_state"] == "one_sided"
    assert rejected["path"] == rejected["receipt"]["path"]
    assert rejected["start_line"] == rejected["receipt"]["start_line"]
    assert rejected["end_line"] == rejected["receipt"]["end_line"]

    text_summary = run_cli(
        "obligation",
        "invariant::INV.X.1",
        "--summarize-evidence",
        "--repo-root",
        str(tmp_path),
        "--format",
        "text",
    )
    assert text_summary.returncode == 0, text_summary.stderr
    assert 'declared_target="pkg/"' in text_summary.stdout

    (tmp_path / "docs/specs/x.md").write_text(
        "## Contract [X-1]\n\n"
        "Invariant: [INV.X.1] The result remains stable.\n\n"
        "_Implementation mapping_:\n\n"
        "- `pkg/x.py::run` and `pkg/`\n",
        encoding="utf-8",
    )
    (tmp_path / "pkg/x.py").write_text(
        "def run() -> int:\n    return 1\n", encoding="utf-8"
    )
    mixed = run_cli(
        "obligation",
        "invariant::INV.X.1",
        "--repo-root",
        str(tmp_path),
        "--format",
        "json",
    )
    assert mixed.returncode == 0, mixed.stdout + mixed.stderr
    assert json.loads(mixed.stdout)["result"]["alignment_state"] == "partial"

    repaired_summary = run_cli(
        "obligation",
        "invariant::INV.X.1",
        "--summarize-evidence",
        "--repo-root",
        str(tmp_path),
        "--format",
        "json",
    )
    assert repaired_summary.returncode == 0, (
        repaired_summary.stdout + repaired_summary.stderr
    )
    repaired_items = json.loads(repaired_summary.stdout)["result"]["items"]
    implementation_rows = [
        item for item in repaired_items if item["role"] == "implementation"
    ]
    assert {item["path"] for item in implementation_rows} == {
        "docs/specs/x.md",
        "pkg/x.py",
    }
    bad_row = next(
        item for item in implementation_rows if item["path"] == "docs/specs/x.md"
    )
    assert bad_row["declared_target"] == "pkg/"
    code_row = next(item for item in implementation_rows if item["path"] == "pkg/x.py")
    assert {
        declaration["declared_target"] for declaration in code_row["declarations"]
    } == {"pkg/x.py::run"}

    (tmp_path / "docs/specs/x.md").write_text(
        "## Contract [X-1]\n\n"
        "Invariant: [INV.X.1] The result remains stable.\n\n"
        "_Implementation mapping_:\n\n"
        "- `pkg/x.py::run`\n",
        encoding="utf-8",
    )
    repaired = run_cli(
        "obligation",
        "invariant::INV.X.1",
        "--repo-root",
        str(tmp_path),
        "--format",
        "json",
    )
    assert repaired.returncode == 0, repaired.stdout + repaired.stderr
    assert json.loads(repaired.stdout)["result"]["alignment_state"] == "complete"


def test_discovery_and_candidate_detail_are_snapshot_bound_read_only_cli_reads(
    tmp_path: Path,
) -> None:
    for relative in ("docs/specs", "docs/plans", "pkg", "tests"):
        (tmp_path / relative).mkdir(parents=True, exist_ok=True)
    (tmp_path / ".backstitch.toml").write_text(
        "[profile]\n"
        'name = "backstitch-style-v1"\n'
        'spec_roots = ["docs/specs"]\n'
        'plan_roots = ["docs/plans"]\n'
        'code_roots = ["pkg", "tests"]\n'
        'test_roots = ["tests"]\n',
        encoding="utf-8",
    )
    (tmp_path / "docs/specs/01-worker.md").write_text(
        "## Run Worker [WORK-1]\n\nThe worker must run queued work.\n",
        encoding="utf-8",
    )
    source = "def run_worker() -> None:\n    pass\n"
    (tmp_path / "pkg/worker.py").write_text(source, encoding="utf-8")
    before = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    obligation_id = "docs/specs/01-worker.md#WORK-1"

    discovery = run_cli(
        "obligation",
        obligation_id,
        "--find-evidence",
        "--repo-root",
        str(tmp_path),
        "--format",
        "json",
    )

    assert discovery.returncode == 0, discovery.stderr
    envelope = json.loads(discovery.stdout)
    assert envelope["operation"] == "obligation.find_evidence"
    candidate = next(
        item
        for item in envelope["result"]["candidates"]
        if item["owner"] == "run_worker"
    )
    assert candidate["trace_state"] == "untraced"
    assert (
        candidate["receipt"]["raw_sha256"]
        == hashlib.sha256(source.encode("utf-8")).hexdigest()
    )

    detail = run_cli(
        "obligation",
        obligation_id,
        "--candidate",
        candidate["candidate_id"],
        "--repo-root",
        str(tmp_path),
        "--format",
        "json",
    )

    assert detail.returncode == 0, detail.stderr
    detail_envelope = json.loads(detail.stdout)
    assert detail_envelope["operation"] == "obligation.get_candidate"
    assert detail_envelope["result"]["candidate"] == candidate
    assert detail_envelope["result"]["source"]["text"] == source
    assert {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    } == before

    repeated = run_cli(
        "obligation",
        obligation_id,
        "--find-evidence",
        "--repo-root",
        str(tmp_path),
        "--format",
        "json",
    )
    assert repeated.returncode == 0, repeated.stderr
    assert repeated.stdout == discovery.stdout

    changed_source = "def run_worker() -> None:\n    return None\n"
    (tmp_path / "pkg/worker.py").write_text(changed_source, encoding="utf-8")
    refreshed = run_cli(
        "obligation",
        obligation_id,
        "--find-evidence",
        "--repo-root",
        str(tmp_path),
        "--format",
        "json",
    )
    assert refreshed.returncode == 0, refreshed.stderr
    refreshed_envelope = json.loads(refreshed.stdout)
    refreshed_candidate = next(
        item
        for item in refreshed_envelope["result"]["candidates"]
        if item["owner"] == "run_worker"
    )
    assert refreshed_envelope["snapshot"] != envelope["snapshot"]
    assert refreshed_candidate["candidate_id"] == candidate["candidate_id"]
    assert (
        refreshed_candidate["receipt"]["raw_sha256"]
        == hashlib.sha256(changed_source.encode("utf-8")).hexdigest()
    )
    assert refreshed_candidate["receipt"] != candidate["receipt"]

    missing = run_cli(
        "obligation",
        obligation_id,
        "--candidate",
        "candidate:sha256:" + "0" * 64,
        "--repo-root",
        str(tmp_path),
        "--format",
        "json",
    )
    assert missing.returncode == 2
    missing_envelope = json.loads(missing.stdout)
    assert missing_envelope["operation"] == "obligation.get_candidate"
    assert missing_envelope["problems"][0]["code"] == "NOT_FOUND"


def test_invalid_limit_is_a_closed_operation_problem(tmp_path: Path) -> None:
    for relative in ("docs/specs", "docs/plans", "backstitch", "tests"):
        (tmp_path / relative).mkdir(parents=True, exist_ok=True)

    result = run_cli(
        "obligation",
        "list",
        "--repo-root",
        str(tmp_path),
        "--no-config",
        "--limit",
        "0",
        "--format",
        "json",
    )

    assert result.returncode == 2
    envelope = json.loads(result.stdout)
    assert envelope["operation"] == "obligation.list"
    assert envelope["snapshot"] is None
    assert envelope["result"] is None
    assert envelope["guidance"] == []
    assert envelope["problems"][0]["code"] == "INVALID_INPUT"
    assert envelope["problems"][0]["details"] == {
        "field": "invocation",
        "reason": "--limit must be in [1, 100]",
    }
    assert result.stderr == ""


def test_invalid_candidate_identity_fails_before_capture(tmp_path: Path) -> None:
    result = run_cli(
        "obligation",
        "docs/specs/x.md#X-1",
        "--candidate",
        "not-a-candidate",
        "--repo-root",
        str(tmp_path / "missing"),
        "--no-config",
        "--format",
        "json",
    )

    assert result.returncode == 2
    envelope = json.loads(result.stdout)
    assert envelope["snapshot"] is None
    assert envelope["problems"][0]["code"] == "INVALID_INPUT"
    assert envelope["problems"][0]["details"] == {
        "field": "invocation",
        "reason": "--candidate must be candidate:sha256: plus 64 lowercase hex digits",
    }


def test_oversized_unknown_identity_has_bounded_failure_without_echo(
    tmp_path: Path,
) -> None:
    for relative in ("docs/specs", "docs/plans", "backstitch", "tests"):
        (tmp_path / relative).mkdir(parents=True, exist_ok=True)
    oversized = "X" * 70_000
    result = run_cli(
        "obligation",
        oversized,
        "--repo-root",
        str(tmp_path),
        "--no-config",
        "--format",
        "json",
    )

    assert result.returncode == 2
    assert len(result.stdout.encode("utf-8")) < 16_384
    envelope = json.loads(result.stdout)
    assert envelope["snapshot"] is not None
    assert envelope["problems"][0]["code"] == "INVALID_INPUT"
    assert envelope["problems"][0]["details"] == {
        "field": "identity",
        "reason": "requested identity exceeds the closed problem detail limit",
    }
    assert oversized not in result.stdout
    assert result.stderr == ""


def test_emitted_long_identity_and_cursor_round_trip(tmp_path: Path) -> None:
    for relative in ("docs/specs", "docs/plans", "backstitch", "tests"):
        (tmp_path / relative).mkdir(parents=True, exist_ok=True)
    long_section_id = "LONG-" + "A" * 20_000 + "1"
    long_obligation_id = f"docs/specs/long.md#{long_section_id}"
    (tmp_path / "docs/specs/long.md").write_text(
        f"## First contract [{long_section_id}]\n\n"
        "Long contract intent.\n\n"
        "## Second contract [SECOND-1]\n\n"
        "Second contract intent.\n",
        encoding="utf-8",
    )
    (tmp_path / ".backstitch.toml").write_text(
        "[obligations]\nmaximum_response_bytes = 200000\n",
        encoding="utf-8",
    )

    first = run_cli(
        "obligation",
        "list",
        "--repo-root",
        str(tmp_path),
        "--limit",
        "1",
        "--format",
        "json",
    )
    assert first.returncode == 0, first.stdout + first.stderr
    first_envelope = json.loads(first.stdout)
    [entry] = first_envelope["result"]["entries"]
    assert entry["obligation_id"] == long_obligation_id
    cursor = first_envelope["result"]["next_cursor"]
    assert len(cursor.encode("utf-8")) > 16_384

    detail = run_cli(
        "obligation",
        long_obligation_id,
        "--repo-root",
        str(tmp_path),
        "--format",
        "json",
    )
    assert detail.returncode == 0, detail.stdout + detail.stderr
    assert json.loads(detail.stdout)["result"]["obligation_id"] == long_obligation_id

    second = run_cli(
        "obligation",
        "list",
        "--repo-root",
        str(tmp_path),
        "--limit",
        "1",
        "--cursor",
        cursor,
        "--format",
        "json",
    )
    assert second.returncode == 0, second.stdout + second.stderr
    [second_entry] = json.loads(second.stdout)["result"]["entries"]
    assert second_entry["obligation_id"] == "docs/specs/long.md#SECOND-1"


def test_missing_repo_root_is_a_closed_pre_capture_problem(tmp_path: Path) -> None:
    result = run_cli(
        "obligation",
        "list",
        "--repo-root",
        str(tmp_path / "missing"),
        "--no-config",
        "--format",
        "json",
    )

    assert result.returncode == 2
    envelope = json.loads(result.stdout)
    assert envelope["operation"] == "obligation.list"
    assert envelope["snapshot"] is None
    assert envelope["problems"][0]["code"] == "INVALID_INPUT"
    assert envelope["problems"][0]["details"] == {
        "field": "repo_root",
        "reason": "repository root is not an existing readable directory",
    }
    assert str(tmp_path.resolve()) not in result.stdout
    assert result.stderr == ""


def test_maximum_page_limit_fails_before_repository_capture(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    result = run_cli(
        "obligation",
        "list",
        "--repo-root",
        str(missing),
        "--no-config",
        "--limit",
        "101",
        "--format",
        "json",
    )

    assert result.returncode == 2
    envelope = json.loads(result.stdout)
    assert envelope["snapshot"] is None
    assert envelope["problems"][0]["details"] == {
        "field": "invocation",
        "reason": "--limit must be in [1, 100]",
    }


def test_configuration_failure_core_json_does_not_leak_absolute_paths(
    tmp_path: Path,
) -> None:
    missing_config = tmp_path / "private-config.toml"
    result = run_cli(
        "obligation",
        "list",
        "--repo-root",
        str(tmp_path),
        "--config",
        str(missing_config),
        "--format",
        "json",
    )

    assert result.returncode == 2
    envelope = json.loads(result.stdout)
    assert envelope["snapshot"] is None
    assert envelope["problems"][0]["details"] == {
        "field": "configuration",
        "reason": "configuration is invalid or unavailable",
    }
    assert str(tmp_path.resolve()) not in result.stdout


def test_evidence_summary_aborts_instead_of_truncating_response(
    tmp_path: Path,
) -> None:
    for relative in ("docs/specs", "docs/plans", "pkg", "tests"):
        (tmp_path / relative).mkdir(parents=True, exist_ok=True)
    (tmp_path / ".backstitch.toml").write_text(
        "[profile]\n"
        'spec_roots = ["docs/specs"]\n'
        'plan_roots = ["docs/plans"]\n'
        'code_roots = ["pkg", "tests"]\n'
        'test_roots = ["tests"]\n\n'
        "[obligations]\n"
        "maximum_response_bytes = 16384\n",
        encoding="utf-8",
    )
    (tmp_path / "docs/specs/x.md").write_text(
        "## Contract [X-1]\n\n_Implementation mapping_:\n\n- `pkg/x.py::run`\n",
        encoding="utf-8",
    )
    (tmp_path / "pkg/x.py").write_text(
        "def run() -> str:\n"
        '    """Spec: docs/specs/x.md [X-1]"""\n'
        f'    return "{"x" * 17000}"\n',
        encoding="utf-8",
    )

    result = run_cli(
        "obligation",
        "docs/specs/x.md#X-1",
        "--summarize-evidence",
        "--repo-root",
        str(tmp_path),
        "--format",
        "json",
    )

    assert result.returncode == 2
    envelope = json.loads(result.stdout)
    assert envelope["operation"] == "obligation.summarize_evidence"
    assert envelope["result"] is None
    assert envelope["problems"][0]["code"] == "BUDGET_EXHAUSTED"
    assert envelope["problems"][0]["details"]["budget"] == "response_bytes"
    assert envelope["problems"][0]["details"]["limit"] == 16384
    assert envelope["problems"][0]["details"]["observed"] > 16384
    assert len(result.stdout.encode("utf-8")) <= 16384
