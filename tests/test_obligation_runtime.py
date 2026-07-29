"""One-view obligation runtime capture and target convergence.

Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-8.2]
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

import backstitch.obligation_runtime as obligation_runtime
from backstitch.analysis_packets import generate_source_aligned_packets
from backstitch.config import ProfileConfig
from backstitch.models import Issue, SuppressionOrigin, SuppressionRule
from backstitch.obligation_runtime import (
    build_obligation_runtime,
    capture_obligation_snapshot,
    unaddressable_issue_excerpts,
)
from backstitch.repository_snapshot import SnapshotCaptureError
from backstitch.settings import BackstitchSettings, LintSettings, resolve_config


def _profile() -> ProfileConfig:
    return ProfileConfig(
        name="test-v1",
        spec_roots=("docs/specs",),
        plan_roots=("docs/plans",),
        code_roots=("pkg", "tests"),
        test_roots=("tests",),
        planned_spec_globs=(),
        exploratory_spec_globs=(),
    )


def test_runtime_owns_snapshot_pipeline_inventory_summary_and_discovery(
    tmp_path: Path,
) -> None:
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "docs/specs/01-core.md").write_text(
        "## Candidate behavior [CAND-1]\n\n"
        "The candidate returns one.\n\n"
        "_Implementation mapping_:\n\n"
        "- `pkg/candidate.py::candidate`\n",
        encoding="utf-8",
    )
    source = tmp_path / "pkg/candidate.py"
    source.write_text(
        "def candidate() -> int:\n"
        '    """Spec: docs/specs/01-core.md [CAND-1]"""\n'
        "    return 1\n\n"
        "def candidate_decoy() -> int:\n"
        "    return 2\n",
        encoding="utf-8",
    )

    runtime = build_obligation_runtime(tmp_path, _profile(), BackstitchSettings())
    obligation = runtime.inventory.get("docs/specs/01-core.md#CAND-1")
    assert obligation is not None
    assert obligation.gate_state == "executable"

    declared = runtime.evidence_summary(obligation)
    discovered = runtime.discover_candidates(obligation)
    captured_hash = runtime.snapshot.snapshot_hash
    source.write_text("raise RuntimeError('post-capture mutation')\n", encoding="utf-8")

    assert runtime.snapshot.snapshot_hash == captured_hash
    assert runtime.evidence_summary(obligation) == declared
    assert runtime.discover_candidates(obligation) == discovered
    assert any(item.candidate_id for item in discovered)


def test_validated_structured_meta_rule_sets_the_shared_obligation_rung(
    tmp_path: Path,
) -> None:
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "tests").mkdir()
    spec_path = "docs/specs/01-core.md"
    (tmp_path / spec_path).write_text(
        "## Candidate behavior [CAND-1]\n\n"
        '_Traceability: suppression-declaration [SUP-META] "Process contract."_\n\n'
        "_Implementation mapping_:\n\n"
        "- `pkg/candidate.py::candidate`\n",
        encoding="utf-8",
    )
    (tmp_path / "pkg/candidate.py").write_text(
        "def candidate() -> int:\n"
        '    """Spec: docs/specs/01-core.md [CAND-1]"""\n'
        "    return 1\n",
        encoding="utf-8",
    )
    settings = BackstitchSettings(
        lint=LintSettings(
            suppressions=(
                SuppressionRule(
                    mechanism="meta",
                    provenance="meta",
                    path=spec_path,
                    sections=(),
                    codes=(),
                    declaration=f"{spec_path}#SUP-META",
                    origin=SuppressionOrigin(source="/trusted/config.toml", position=0),
                ),
            )
        )
    )

    runtime = build_obligation_runtime(tmp_path, _profile(), settings)

    obligation = runtime.inventory.get(f"{spec_path}#CAND-1")
    assert obligation is not None
    assert runtime.pipeline.effective_meta_spec_globs == (spec_path,)
    assert obligation.obligation_rung == "meta"
    assert obligation.gate_state == "not_executable"


@pytest.mark.parametrize(
    (
        "require_declarations",
        "expected_rung",
        "expected_section_meta",
        "expected_packet_ids",
    ),
    [
        (
            False,
            "meta",
            frozenset({("docs/specs/01-core.md", "CAND-1")}),
            ["docs/specs/01-core.md#CAND-2"],
        ),
        (
            True,
            "active",
            frozenset(),
            [
                "docs/specs/01-core.md#CAND-1",
                "docs/specs/01-core.md#CAND-2",
            ],
        ),
    ],
)
def test_clause_free_inline_meta_only_changes_obligation_rung_when_eligible(
    tmp_path: Path,
    require_declarations: bool,
    expected_rung: str,
    expected_section_meta: frozenset[tuple[str, str]],
    expected_packet_ids: list[str],
) -> None:
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "tests").mkdir()
    spec_path = "docs/specs/01-core.md"
    (tmp_path / spec_path).write_text(
        "## Candidate behavior [CAND-1]\n"
        "_Traceability: meta_\n\n"
        "The candidate returns one.\n\n"
        "_Implementation mapping_:\n\n"
        "- `pkg/candidate.py::candidate`\n\n"
        "## Other behavior [CAND-2]\n\n"
        "The other candidate returns two.\n\n"
        "_Implementation mapping_:\n\n"
        "- `pkg/candidate.py::candidate_two`\n",
        encoding="utf-8",
    )
    (tmp_path / "pkg/candidate.py").write_text(
        "def candidate() -> int:\n"
        '    """Spec: docs/specs/01-core.md [CAND-1]"""\n'
        "    return 1\n\n"
        "def candidate_two() -> int:\n"
        '    """Spec: docs/specs/01-core.md [CAND-2]"""\n'
        "    return 2\n",
        encoding="utf-8",
    )
    settings = BackstitchSettings(
        lint=LintSettings(
            require_suppression_declarations=require_declarations,
        )
    )

    runtime = build_obligation_runtime(tmp_path, _profile(), settings)

    obligation = runtime.inventory.get(f"{spec_path}#CAND-1")
    assert obligation is not None
    assert runtime.pipeline.artifacts.section_meta == {(spec_path, "CAND-1"): True}
    assert runtime.pipeline.effective_section_meta == expected_section_meta
    assert obligation.obligation_rung == expected_rung
    assert [
        packet["packet_id"] for packet in generate_source_aligned_packets(runtime)
    ] == (expected_packet_ids)


def test_capture_converges_declared_target_outside_code_roots(tmp_path: Path) -> None:
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "docs/plans").mkdir(parents=True)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "external").mkdir()
    (tmp_path / "docs/specs/01-x.md").write_text(
        "## X [X-1]\n\n_Implementation mapping_:\n\n- `external/worker.py::run`\n",
        encoding="utf-8",
    )
    raw = b"def run() -> None:\n    pass\n"
    (tmp_path / "external/worker.py").write_bytes(raw)

    snapshot = capture_obligation_snapshot(tmp_path, _profile(), BackstitchSettings())

    assert snapshot.path_kind("external/worker.py") == "regular_file"
    assert snapshot.read_bytes("external/worker.py") == raw
    assert "external/worker.py" in {row.path for row in snapshot.files}


def test_unaddressable_excerpt_comes_from_the_same_captured_source_line(
    tmp_path: Path,
) -> None:
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "pkg").mkdir()
    source = b"# Root\n\n## Broken contract [not-an-id]\n"
    (tmp_path / "docs/specs/01-broken.md").write_bytes(source)
    snapshot = capture_obligation_snapshot(tmp_path, _profile(), BackstitchSettings())
    issue = Issue(
        "SPEC_SECTION_HEADING_INVALID",
        "error",
        "docs/specs/01-broken.md",
        3,
        "ID-bearing Markdown heading has an invalid or missing section ID",
    )

    assert unaddressable_issue_excerpts(snapshot, (issue,)) == {
        ("SPEC_SECTION_HEADING_INVALID", "docs/specs/01-broken.md", 3, 0): (
            "## Broken contract [not-an-id]"
        )
    }


def test_missing_declared_target_is_stable_but_absent(tmp_path: Path) -> None:
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "docs/specs/01-x.md").write_text(
        "## X [X-1]\n\n_Implementation mapping_:\n\n- `missing.py`\n",
        encoding="utf-8",
    )

    snapshot = capture_obligation_snapshot(tmp_path, _profile(), BackstitchSettings())

    assert not snapshot.path_exists("missing.py")


def test_capture_binds_every_extended_config_layer_to_settings_bytes(
    tmp_path: Path,
) -> None:
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "pkg").mkdir()
    parent = tmp_path / "parent.toml"
    parent.write_bytes(b'[check]\nformat = "text"\n')
    child = tmp_path / ".backstitch.toml"
    child.write_bytes(b'extend = "parent.toml"\n[check]\nformat = "json"\n')
    settings = resolve_config(tmp_path, explicit=child)

    snapshot = capture_obligation_snapshot(tmp_path, _profile(), settings)

    expected = {
        Path(item.path).relative_to(tmp_path).as_posix(): item.raw_sha256
        for item in settings.config_layer_identities
    }
    assert {
        path: snapshot.file(path).raw_sha256 for path in sorted(expected)
    } == expected


def test_capture_binds_discovered_parent_config_without_absolute_identity(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "nested-repository"
    (repo / "docs/specs").mkdir(parents=True)
    (repo / "pkg").mkdir()
    raw = b'[check]\nformat = "json"\n'
    (tmp_path / ".backstitch.toml").write_bytes(raw)
    settings = resolve_config(repo)

    snapshot = capture_obligation_snapshot(repo, _profile(), settings)

    expected_hash = hashlib.sha256(raw).hexdigest()
    assert snapshot.identity_document()["config_inputs"] == [
        {"ordinal": 0, "raw_sha256": expected_hash}
    ]
    assert snapshot.config_inputs[0].raw_bytes == raw
    assert str(tmp_path) not in snapshot.identity_document().__repr__()
    assert all(row.path != ".backstitch.toml" for row in snapshot.files)


def test_stale_config_identity_consumes_the_shared_attempt_ceiling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "pkg").mkdir()
    config = tmp_path / ".backstitch.toml"
    config.write_bytes(b'[check]\nformat = "text"\n')
    settings = resolve_config(tmp_path, explicit=config)
    settings = replace(
        settings,
        obligations=replace(settings.obligations, snapshot_capture_attempts=2),
    )
    config.write_bytes(b'[check]\nformat = "json"\n')
    real_capture = obligation_runtime.capture_repository_snapshot
    calls = 0

    def counting_capture(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        return real_capture(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        obligation_runtime,
        "capture_repository_snapshot",
        counting_capture,
    )

    with pytest.raises(SnapshotCaptureError) as raised:
        capture_obligation_snapshot(tmp_path, _profile(), settings)

    assert raised.value.kind == "snapshot_unstable"
    assert raised.value.attempts == 2
    # Convergence retries are now internal to one accepted snapshot-capture
    # invocation, so the public work bound remains one call while the raised
    # problem still reports the configured internal attempt ceiling.
    assert calls == 1


def test_config_identity_change_cannot_recover_by_rewriting_the_same_bytes(
    tmp_path: Path,
) -> None:
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "pkg").mkdir()
    config = tmp_path / ".backstitch.toml"
    settings_bytes = b'[check]\nformat = "text"\n'
    config.write_bytes(settings_bytes)
    settings = resolve_config(tmp_path, explicit=config)
    config.write_bytes(b'[check]\nformat = "json"\n')
    config.write_bytes(settings_bytes)

    with pytest.raises(SnapshotCaptureError) as raised:
        capture_obligation_snapshot(tmp_path, _profile(), settings)

    assert raised.value.kind == "snapshot_unstable"


def test_contained_config_replaced_by_equal_byte_symlink_is_never_readdressed(
    tmp_path: Path,
) -> None:
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "pkg").mkdir()
    config = tmp_path / ".backstitch.toml"
    raw = b'[check]\nformat = "json"\n'
    config.write_bytes(raw)
    settings = resolve_config(tmp_path, explicit=config)
    outside = tmp_path.parent / f"{tmp_path.name}-outside.toml"
    outside.write_bytes(raw)
    config.unlink()
    config.symlink_to(outside)

    with pytest.raises(SnapshotCaptureError) as raised:
        capture_obligation_snapshot(tmp_path, _profile(), settings)

    assert raised.value.kind == "snapshot_unstable"
