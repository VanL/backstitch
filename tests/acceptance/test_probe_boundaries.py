"""Probes 10-12: worktree discovery, exit-2 honesty, path ladder.

Spec: docs/specs/02-backstitch-core.md [SC-4], [SC-5], [SC-10], [SC-12]
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tests.acceptance.conftest import ROOTS, run_cli


def test_probe_10_sibling_discovery_from_linked_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backstitch.target_roots import discover_weft

    main = tmp_path / "mainrepo"
    main.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=main, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=t@example.com",
            "-c",
            "user.name=t",
            "commit",
            "--allow-empty",
            "-q",
            "-m",
            "init",
        ],
        cwd=main,
        check=True,
    )
    worktree = main / ".worktrees" / "feature"
    subprocess.run(
        ["git", "worktree", "add", "-q", str(worktree), "-b", "feature"],
        cwd=main,
        check=True,
    )
    sibling = tmp_path / "weft"
    sibling.mkdir()
    monkeypatch.delenv("BACKSTITCH_WEFT_ROOT", raising=False)
    assert discover_weft(anchor=worktree) == sibling.resolve()


def test_probe_11_malformed_inputs_exit_two_with_one_line_errors(
    tmp_path: Path, mini_repo: Path
) -> None:
    degenerate = tmp_path / "degenerate.json"
    degenerate.write_text('{"summary": {}}\n', encoding="utf-8")
    results = tmp_path / "empty.jsonl"
    results.write_text("", encoding="utf-8")
    outcome = run_cli(
        "summarize-analysis",
        "--deterministic-report",
        str(degenerate),
        "--analysis-results",
        str(results),
    )
    assert outcome.returncode == 2
    assert "backstitch: error:" in outcome.stderr

    bad_packets = tmp_path / "bad.jsonl"
    bad_packets.write_text("not json {\n", encoding="utf-8")
    outcome = run_cli(
        "analyze",
        "--packets",
        str(bad_packets),
        "--no-config",
        "--model",
        "irrelevant",
    )
    assert outcome.returncode == 2
    assert "backstitch: error:" in outcome.stderr

    unwritable = tmp_path / "no-dir" / "out.json"
    outcome = run_cli(
        "check",
        "--repo-root",
        str(mini_repo),
        *ROOTS,
        "--output",
        str(unwritable),
    )
    assert outcome.returncode == 2
    assert "backstitch: error:" in outcome.stderr


def test_probe_12_path_ladder_ambiguous_and_inexact(mini_repo: Path) -> None:
    (mini_repo / "pkg/d1").mkdir()
    (mini_repo / "pkg/d2").mkdir()
    (mini_repo / "pkg/d1/twin.py").write_text('"""One."""\n', encoding="utf-8")
    (mini_repo / "pkg/d2/twin.py").write_text('"""Two."""\n', encoding="utf-8")
    (mini_repo / "pkg/d1/leaf.py").write_text('"""Leaf."""\n', encoding="utf-8")
    (mini_repo / "docs/specs/05-ladder.md").write_text(
        "# L\n\n## Ambi [LP-1]\n\n_Implementation mapping_:\n\n- `twin.py`\n\n"
        "## Inex [LP-2]\n\n_Implementation mapping_:\n\n- `leaf.py`\n",
        encoding="utf-8",
    )
    result = run_cli("check", "--repo-root", str(mini_repo), *ROOTS, "--format", "json")
    data = json.loads(result.stdout)
    codes = {i["code"]: i for i in data["issues"]}
    assert codes["TARGET_PATH_AMBIGUOUS"]["section_id"] == "LP-1"
    ambiguous_edges = [e for e in data["edges"] if e["section_id"] == "LP-1"]
    assert ambiguous_edges == []
    assert codes["MAPPING_PATH_INEXACT"]["section_id"] == "LP-2"
    inexact_edges = [e for e in data["edges"] if e["section_id"] == "LP-2"]
    assert len(inexact_edges) == 1
