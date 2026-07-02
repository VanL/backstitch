"""Probes 1-5: anchors, fences, encoding, broad refs, duplicates ([SC-10]).

Spec: docs/specs/02-backstitch-core.md [SC-10]
"""

from __future__ import annotations

from pathlib import Path

from tests.acceptance.conftest import ROOTS, check_json


def test_probe_1_github_anchor_with_id_resolves(mini_repo: Path) -> None:
    (mini_repo / "docs/specs/02-anchor.md").write_text(
        "# Anchor\n\n## Alpha Feature [AF-1]\n", encoding="utf-8"
    )
    (mini_repo / "pkg/anchored.py").write_text(
        '"""Spec: docs/specs/02-anchor.md#alpha-feature-af-1"""\n',
        encoding="utf-8",
    )
    data = check_json(mini_repo, *ROOTS, expect_exit=0)
    assert not any(i["code"] == "SPEC_ANCHOR_MISSING" for i in data["issues"])


def test_probe_2_backtick_and_tilde_fences_create_nothing(
    mini_repo: Path,
) -> None:
    (mini_repo / "docs/specs/03-fence.md").write_text(
        "# F\n\n## Real [FN-1]\n\n"
        "```md\n## Fake Backtick [FB-9]\n```\n\n"
        "~~~text\n## Fake Tilde [FT-9]\n~~~\n\n"
        "_Implementation mapping_:\n\n- `pkg/mod.py`\n",
        encoding="utf-8",
    )
    data = check_json(mini_repo, *ROOTS)
    ids = {s["section_id"] for s in data["spec_sections"]}
    assert "FB-9" not in ids and "FT-9" not in ids
    # The mapping block after the fences belongs to the REAL section.
    mapped = {m["section_id"] for m in data["spec_mappings"]}
    assert "FN-1" in mapped


def test_probe_3_non_utf8_file_degrades_and_scan_continues(
    mini_repo: Path,
) -> None:
    (mini_repo / "pkg/binary.py").write_bytes(b"\xff\xfe junk \xff")
    data = check_json(mini_repo, *ROOTS, expect_exit=1)
    unreadable = [i for i in data["issues"] if i["code"] == "FILE_UNREADABLE"]
    assert unreadable and unreadable[0]["path"] == "pkg/binary.py"
    # Full report still produced: the clean section is present.
    assert any(s["section_id"] == "PR-1" for s in data["spec_sections"])


def test_probe_4_document_only_reference_fires_broad(mini_repo: Path) -> None:
    (mini_repo / "pkg/broad.py").write_text(
        '"""Covers docs/specs/01-p.md."""\n', encoding="utf-8"
    )
    data = check_json(mini_repo, *ROOTS)
    assert any(i["code"] == "CODE_REF_BROAD" for i in data["issues"])


def test_probe_5_unreferenced_duplicate_id_fires(mini_repo: Path) -> None:
    (mini_repo / "docs/specs/04-dup.md").write_text(
        "# D\n\n## First [DU-1]\n\n## Second [DU-1]\n", encoding="utf-8"
    )
    data = check_json(mini_repo, *ROOTS)
    assert any(i["code"] == "SPEC_SECTION_DUPLICATE" for i in data["issues"])
