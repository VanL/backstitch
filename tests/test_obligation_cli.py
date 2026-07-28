"""Obligation CLI operation-boundary tests."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from backstitch import cli
from backstitch.obligation_api import encode_page_cursor


def _write_discovery_repo(root: Path) -> str:
    for relative in ("docs/specs", "docs/plans", "backstitch", "tests"):
        (root / relative).mkdir(parents=True, exist_ok=True)
    obligation_id = "docs/specs/01-worker.md#WORK-1"
    (root / "docs/specs/01-worker.md").write_text(
        "## Run Worker [WORK-1]\n\nThe worker must run queued work.\n",
        encoding="utf-8",
    )
    (root / "backstitch/worker.py").write_text(
        "def run_worker() -> None:\n    pass\n",
        encoding="utf-8",
    )
    return obligation_id


def test_limit_error_quotes_effective_configured_bound(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = tmp_path / ".backstitch.toml"
    config.write_text(
        "[obligations]\npage_size = 3\nmaximum_page_size = 3\n",
        encoding="utf-8",
    )

    exit_code = cli.main(
        (
            "obligation",
            "list",
            "--limit",
            "0",
            "--repo-root",
            str(tmp_path),
            "--format",
            "json",
        )
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    envelope = json.loads(captured.out)
    assert envelope["problems"][0]["details"]["reason"] == ("--limit must be in [1, 3]")


def test_find_evidence_and_candidate_detail_use_one_public_discovery_model(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    obligation_id = _write_discovery_repo(tmp_path)
    before = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    exit_code = cli.main(
        (
            "obligation",
            obligation_id,
            "--find-evidence",
            "--limit",
            "1",
            "--repo-root",
            str(tmp_path),
            "--no-config",
            "--format",
            "json",
        )
    )

    captured = capsys.readouterr()
    assert exit_code == 0, captured.out + captured.err
    discovery = json.loads(captured.out)
    assert discovery["operation"] == "obligation.find_evidence"
    assert len(discovery["result"]["candidates"]) == 1
    assert discovery["result"]["next_cursor"] is not None
    cursor = discovery["result"]["next_cursor"]

    malformed_cursor = encode_page_cursor(
        operation="obligation.find_evidence",
        snapshot_hash=discovery["snapshot"]["snapshot_hash"],
        obligation_id=obligation_id,
        selector="find_evidence",
        limit=1,
        after=("wrong", 0, 0, 0, "", 0, "", ""),
    )
    exit_code = cli.main(
        (
            "obligation",
            obligation_id,
            "--find-evidence",
            "--limit",
            "1",
            "--cursor",
            malformed_cursor,
            "--repo-root",
            str(tmp_path),
            "--no-config",
            "--format",
            "json",
        )
    )
    captured = capsys.readouterr()
    assert exit_code == 2
    malformed = json.loads(captured.out)
    assert malformed["problems"][0]["code"] == "CURSOR_INVALID"
    assert malformed["snapshot"] == discovery["snapshot"]

    exit_code = cli.main(
        (
            "obligation",
            obligation_id,
            "--find-evidence",
            "--limit",
            "1",
            "--cursor",
            cursor,
            "--repo-root",
            str(tmp_path),
            "--no-config",
            "--format",
            "json",
        )
    )
    captured = capsys.readouterr()
    assert exit_code == 0, captured.out + captured.err
    second_page = json.loads(captured.out)
    assert second_page["operation"] == "obligation.find_evidence"
    assert len(second_page["result"]["candidates"]) == 1
    assert second_page["result"]["candidates"] != discovery["result"]["candidates"]

    exit_code = cli.main(
        (
            "obligation",
            obligation_id,
            "--find-evidence",
            "--limit",
            "1",
            "--repo-root",
            str(tmp_path),
            "--no-config",
            "--format",
            "text",
        )
    )
    captured = capsys.readouterr()
    assert exit_code == 0, captured.out + captured.err
    assert captured.out.startswith(f"root {tmp_path.resolve().as_posix()}\n")
    assert "next_cursor: " in captured.out
    assert "guidance REVIEW_UNTRACED_CANDIDATE:" in captured.out
    assert "action: Review the candidate" in captured.out

    exit_code = cli.main(
        (
            "obligation",
            obligation_id,
            "--find-evidence",
            "--repo-root",
            str(tmp_path),
            "--no-config",
            "--format",
            "json",
        )
    )
    captured = capsys.readouterr()
    assert exit_code == 0, captured.out + captured.err
    discovery = json.loads(captured.out)
    candidate = next(
        item
        for item in discovery["result"]["candidates"]
        if item["owner"] == "run_worker"
    )
    assert candidate["trace_state"] == "untraced"
    assert candidate["suggested_trace_edits"]

    exit_code = cli.main(
        (
            "obligation",
            obligation_id,
            "--repo-root",
            str(tmp_path),
            "--no-config",
            "--format",
            "json",
        )
    )
    captured = capsys.readouterr()
    assert exit_code == 0, captured.out + captured.err
    default_detail = json.loads(captured.out)
    detail_counts = default_detail["result"]["candidate_counts"]
    assert detail_counts["untraced"] >= 1
    assert "REVIEW_UNTRACED_CANDIDATE" in default_detail["result"]["next_actions"]
    assert "REVIEW_UNTRACED_CANDIDATE" in {
        item["code"] for item in default_detail["guidance"]
    }

    exit_code = cli.main(
        (
            "obligation",
            obligation_id,
            "--repo-root",
            str(tmp_path),
            "--no-config",
            "--format",
            "text",
        )
    )
    captured = capsys.readouterr()
    assert exit_code == 0, captured.out + captured.err
    assert "candidate_counts: " in captured.out
    assert "blocker: " in captured.out
    assert "next_actions: " in captured.out

    exit_code = cli.main(
        (
            "obligation",
            obligation_id,
            "--candidate",
            candidate["candidate_id"],
            "--repo-root",
            str(tmp_path),
            "--no-config",
            "--format",
            "json",
        )
    )

    captured = capsys.readouterr()
    assert exit_code == 0, captured.out + captured.err
    detail = json.loads(captured.out)
    assert detail["operation"] == "obligation.get_candidate"
    assert detail["result"]["candidate"] == candidate
    assert detail["result"]["source"]["text"] == (
        "def run_worker() -> None:\n    pass\n"
    )

    exit_code = cli.main(
        (
            "obligation",
            obligation_id,
            "--candidate",
            candidate["candidate_id"],
            "--repo-root",
            str(tmp_path),
            "--no-config",
            "--format",
            "text",
        )
    )
    captured = capsys.readouterr()
    assert exit_code == 0, captured.out + captured.err
    assert f"candidate: {candidate['candidate_id']}" in captured.out
    assert "receipt_sha256: " in captured.out
    assert "advice ADD_RECIPROCAL_MAPPING:" in captured.out
    after = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_operation_deadline_discards_the_complete_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for relative in ("docs/specs", "docs/plans", "backstitch", "tests"):
        (tmp_path / relative).mkdir(parents=True, exist_ok=True)
    ticks = iter((0.0, 11.0))
    monkeypatch.setattr(cli.time, "monotonic", lambda: next(ticks))

    exit_code = cli.main(
        (
            "obligation",
            "list",
            "--repo-root",
            str(tmp_path),
            "--no-config",
            "--format",
            "json",
        )
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    envelope = json.loads(captured.out)
    assert envelope["operation"] == "obligation.list"
    assert envelope["result"] is None
    assert envelope["problems"][0]["code"] == "DEADLINE_EXCEEDED"
    assert envelope["problems"][0]["details"] == {"limit_milliseconds": 10000}
    assert captured.err == ""


def test_evidence_summary_falls_back_for_non_utf8_python_target(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for relative in ("docs/specs", "docs/plans", "backstitch", "tests"):
        (tmp_path / relative).mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs/specs/01-x.md").write_text(
        "## Contract [X-1]\n\n_Implementation mapping_:\n\n- `backstitch/binary.py`\n",
        encoding="utf-8",
    )
    (tmp_path / "backstitch/binary.py").write_bytes(b"# \xff\npass\n")

    exit_code = cli.main(
        (
            "obligation",
            "docs/specs/01-x.md#X-1",
            "--summarize-evidence",
            "--repo-root",
            str(tmp_path),
            "--no-config",
            "--format",
            "json",
        )
    )

    captured = capsys.readouterr()
    assert exit_code == 0, captured.out + captured.err
    envelope = json.loads(captured.out)
    [row] = envelope["result"]["items"]
    assert row["path"] == "docs/specs/01-x.md"
    assert row["declared_target"] == "backstitch/binary.py"
    assert row["receipt"]["structural_locator"].startswith(
        "source-declaration:spec_mapping:"
    )
    assert captured.err == ""


@pytest.mark.parametrize("exception_type", [RuntimeError, ValueError])
def test_internal_failure_after_capture_preserves_snapshot_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    exception_type: type[Exception],
) -> None:
    import backstitch.obligation_runtime as obligation_runtime

    for relative in ("docs/specs", "docs/plans", "backstitch", "tests"):
        (tmp_path / relative).mkdir(parents=True, exist_ok=True)

    def fail_after_capture(*_args: object, **_kwargs: object) -> None:
        raise exception_type("injected post-capture failure")

    monkeypatch.setattr(
        obligation_runtime, "build_check_report_from_snapshot", fail_after_capture
    )
    exit_code = cli.main(
        (
            "obligation",
            "list",
            "--repo-root",
            str(tmp_path),
            "--no-config",
            "--format",
            "json",
        )
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    envelope = json.loads(captured.out)
    assert envelope["problems"][0]["code"] == "INTERNAL_ERROR"
    assert envelope["snapshot"] is not None
    assert envelope["snapshot"]["snapshot_hash"]
    assert captured.err == ""


def test_text_problem_includes_root_code_and_required_action(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = cli.main(
        (
            "obligation",
            "list",
            "--limit",
            "0",
            "--repo-root",
            str(tmp_path),
            "--no-config",
            "--format",
            "text",
        )
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert captured.err.startswith(f"root {tmp_path.resolve().as_posix()}\n")
    assert "problem INVALID_INPUT:" in captured.err
    assert 'details: {"field":"invocation"' in captured.err
    assert "action: Correct the named invocation" in captured.err


def test_complete_catalog_reads_fail_closed_on_unreadable_semantic_source(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    obligation_id = _write_discovery_repo(tmp_path)
    unreadable = tmp_path / "backstitch/unreadable.py"
    unreadable.write_text("def hidden():\n    pass\n", encoding="utf-8")
    unreadable.chmod(0)
    try:
        for selector in (
            (),
            ("--find-evidence",),
            ("--candidate", "candidate:sha256:" + "0" * 64),
        ):
            exit_code = cli.main(
                (
                    "obligation",
                    obligation_id,
                    *selector,
                    "--repo-root",
                    str(tmp_path),
                    "--no-config",
                    "--format",
                    "json",
                )
            )
            captured = capsys.readouterr()
            assert exit_code == 2, captured.out + captured.err
            envelope = json.loads(captured.out)
            assert envelope["problems"][0]["code"] == "SOURCE_UNREADABLE"
            assert envelope["snapshot"]["unreadable_count"] == 1

        for selector in (("list",), (obligation_id, "--summarize-evidence")):
            exit_code = cli.main(
                (
                    "obligation",
                    *selector,
                    "--repo-root",
                    str(tmp_path),
                    "--no-config",
                    "--format",
                    "json",
                )
            )
            captured = capsys.readouterr()
            assert exit_code == 0, captured.out + captured.err
            assert json.loads(captured.out)["snapshot"]["unreadable_count"] == 1
    finally:
        os.chmod(unreadable, 0o600)
