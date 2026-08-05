"""Hostile fixtures for the SC-17.1 Ruff suppression index generator."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
MODULE_SPEC = importlib.util.spec_from_file_location(
    "ruff_suppression_index", ROOT / "bin" / "ruff_suppression_index.py"
)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
index = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = index
MODULE_SPEC.loader.exec_module(index)


def _row(
    group: str,
    rules: str,
    directives: int,
    raw: str,
    *,
    lifetime: str = "permanent",
    invariant: str = "Exception translation preserves the public boundary.",
    proof: str = "test_exception_translation exercises the boundary.",
    alternatives: str = "A broad catch was rejected because it hides unrelated failures.",
    approval: str = "owner review 2026-08-05",
) -> str:
    return (
        f"| `{group}` | {rules} | `{directives}` | {raw} | {lifetime} | "
        f"{invariant} | {proof} | {alternatives} | {approval} |"
    )


def _spec(*rows: str, generated: list[str] | None = None) -> str:
    generated = generated or []
    return "\n".join(
        [
            "# Synthetic static analysis contract",
            "",
            index.REGISTRY_HEADING,
            "",
            index.TABLE_HEADER,
            index.TABLE_DIVIDER,
            *rows,
            "",
            index.BEGIN_MARKER,
            *generated,
            index.END_MARKER,
            "",
        ]
    )


def _diagnostics(path: Path, source: str) -> list[dict[str, object]]:
    diagnostics: list[dict[str, object]] = []
    for number, line in enumerate(source.splitlines(), 1):
        if "RUFF-SUP-001" in line:
            diagnostics.append(
                {"filename": str(path), "noqa_row": number, "code": "BLE001"}
            )
        if "RUFF-SUP-002" in line:
            diagnostics.append(
                {"filename": str(path), "noqa_row": number, "code": "F401"}
            )
    return diagnostics


def _patch_ruff(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
    paths: list[Path],
    raw: list[dict[str, object]],
    *,
    raw_stdout: str | None = None,
    raw_returncode: int | None = None,
    normal: list[dict[str, object]] | None = None,
) -> list[tuple[str, ...]]:
    calls: list[tuple[str, ...]] = []

    def fake_run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
        assert repo == root
        calls.append(args)
        if "--show-files" in args:
            return subprocess.CompletedProcess(
                args, 0, "\n".join(map(str, paths)) + "\n", ""
            )
        if "--ignore-noqa" in args:
            payload = json.dumps(raw) if raw_stdout is None else raw_stdout
            code = (1 if raw else 0) if raw_returncode is None else raw_returncode
            return subprocess.CompletedProcess(args, code, payload, "raw failure")
        payload = json.dumps(normal or [])
        return subprocess.CompletedProcess(args, 1 if normal else 0, payload, "")

    monkeypatch.setattr(index, "_run_ruff", fake_run)
    return calls


def _fixture(tmp_path: Path) -> tuple[Path, Path, str]:
    source = "\n".join(
        [
            "import os  # noqa: F401 approved [SC-17.1] RUFF-SUP-002 exception",
            "",
            "def translate():",
            "    try:",
            "        return 1",
            "    except Exception:  # noqa: BLE001 approved [SC-17.1] RUFF-SUP-001 exception",
            "        return 0",
            "",
        ]
    )
    path = tmp_path / "probe.py"
    path.write_text(source, encoding="utf-8")
    spec = tmp_path / "spec.md"
    spec.write_text(
        _spec(
            _row("RUFF-SUP-002", "`F401`", 1, "`F401=1`"),
            _row("RUFF-SUP-001", "`BLE001`", 1, "`BLE001=1`"),
        ),
        encoding="utf-8",
    )
    return path, spec, source


def test_multiple_groups_render_deterministically_and_check_is_nonmutating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, spec, source = _fixture(tmp_path)
    calls = _patch_ruff(monkeypatch, tmp_path, [path], _diagnostics(path, source))

    assert (
        index.main(["--repo-root", str(tmp_path), "--spec", str(spec), "--write"]) == 0
    )
    first = spec.read_bytes()
    assert b"Global active-rule raw inventory: `BLE001=1`, `F401=1`" in first
    assert b"`probe.py::<module>`" in first
    assert b"`probe.py::translate`" in first
    assert first.index(b"RUFF-SUP-001") < first.index(
        b"RUFF-SUP-002", first.index(index.BEGIN_MARKER.encode())
    )
    assert (
        index.main(["--repo-root", str(tmp_path), "--spec", str(spec), "--write"]) == 0
    )
    assert spec.read_bytes() == first
    assert (
        index.main(["--repo-root", str(tmp_path), "--spec", str(spec), "--check"]) == 0
    )
    assert spec.read_bytes() == first
    assert any(call[-4:] == index.LINT_TARGETS for call in calls)


def test_nested_and_decorated_functions_have_exact_symbol_keys(tmp_path: Path) -> None:
    source = "\n".join(
        [
            "def deco(fn):",
            "    return fn",
            "",
            "def outer():",
            "    def inner():  # noqa: BLE001 approved [SC-17.1] RUFF-SUP-001 exception",
            "        return 1",
            "    return inner()",
            "",
            "@deco  # noqa: F401 approved [SC-17.1] RUFF-SUP-002 exception",
            "def decorated():",
            "    return 2",
        ]
    )
    path = tmp_path / "symbols.py"
    path.write_text(source, encoding="utf-8")
    directives = index.scan_source(path, tmp_path)
    keyed = {(item.group, item.symbol) for item in directives}
    assert keyed == {("RUFF-SUP-001", "outer.inner"), ("RUFF-SUP-002", "decorated")}


def test_line_movement_does_not_change_generated_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, spec, source = _fixture(tmp_path)
    _patch_ruff(monkeypatch, tmp_path, [path], _diagnostics(path, source))
    assert (
        index.main(["--repo-root", str(tmp_path), "--spec", str(spec), "--write"]) == 0
    )
    before = spec.read_bytes()
    moved = "\n\n" + source
    path.write_text(moved, encoding="utf-8")
    _patch_ruff(monkeypatch, tmp_path, [path], _diagnostics(path, moved))
    assert (
        index.main(["--repo-root", str(tmp_path), "--spec", str(spec), "--check"]) == 0
    )
    assert spec.read_bytes() == before


def test_run_preserves_crlf_and_non_ascii_bytes_outside_generated_region(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = "value = 1  # noqa: BLE001 approved [SC-17.1] RUFF-SUP-001 exception\n"
    source_path = tmp_path / "probe.py"
    source_path.write_text(source, encoding="utf-8")
    spec_path = tmp_path / "policy.md"
    original = (
        _spec(_row("RUFF-SUP-001", "`BLE001`", 1, "`BLE001=1`"))
        + "## Following section\nCafé ownership stays byte-stable.\n"
    ).replace("\n", "\r\n")
    spec_path.write_bytes(original.encode("utf-8"))
    _patch_ruff(
        monkeypatch,
        tmp_path,
        [source_path],
        _diagnostics(source_path, source),
    )
    before = spec_path.read_bytes()
    index.run(tmp_path, spec_path, write=True)
    after = spec_path.read_bytes()
    begin = index.BEGIN_MARKER.encode()
    end = index.END_MARKER.encode()
    assert after.partition(begin)[0] == before.partition(begin)[0]
    assert after.partition(end)[2] == before.partition(end)[2]
    assert "Café ownership stays byte-stable.".encode() in after
    assert b"\n" not in after.replace(b"\r\n", b"")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda text: text.replace(
            index.REGISTRY_HEADING, "#### Wrong registry [SC-17.1]"
        ),
        lambda text: text.replace(
            index.REGISTRY_HEADING,
            index.REGISTRY_HEADING + "\n" + index.REGISTRY_HEADING,
        ),
        lambda text: text.replace(index.BEGIN_MARKER, "<!-- WRONG BEGIN -->"),
        lambda text: text.replace(
            index.BEGIN_MARKER, index.BEGIN_MARKER + "\n" + index.BEGIN_MARKER
        ),
        lambda text: text.replace(index.END_MARKER, "<!-- WRONG END -->"),
        lambda text: text.replace(
            index.END_MARKER, index.END_MARKER + "\n" + index.END_MARKER
        ),
    ],
)
def test_heading_and_generated_markers_are_unique_and_exact(
    mutate: Callable[[str], str],
) -> None:
    text = _spec(_row("RUFF-SUP-001", "`BLE001`", 1, "`BLE001=1`"))
    with pytest.raises(index.PolicyMismatch):
        index.parse_registry(mutate(text))


def test_markdown_fence_near_misses_are_inert() -> None:
    text = _spec(_row("RUFF-SUP-001", "`BLE001`", 1, "`BLE001=1`"))
    text += f"```md\n{index.REGISTRY_HEADING}\n{index.BEGIN_MARKER}\n{index.END_MARKER}\n```\n"
    groups, _ = index.parse_registry(text)
    assert set(groups) == {"RUFF-SUP-001"}


def test_unclosed_markdown_fence_is_rejected() -> None:
    text = _spec(_row("RUFF-SUP-001", "`BLE001`", 1, "`BLE001=1`"))
    with pytest.raises(index.PolicyMismatch, match="unclosed Markdown fence"):
        index.parse_registry(text + "```md\nnever closed\n")


def test_exactly_one_human_registry_table_is_required() -> None:
    text = _spec(_row("RUFF-SUP-001", "`BLE001`", 1, "`BLE001=1`"))
    duplicate = text.replace(
        index.BEGIN_MARKER,
        f"{index.TABLE_HEADER}\n{index.TABLE_DIVIDER}\n{index.BEGIN_MARKER}",
    )
    with pytest.raises(index.PolicyMismatch, match="exactly one human"):
        index.parse_registry(duplicate)


def test_group_shaped_row_outside_human_table_is_not_ignored() -> None:
    text = _spec(_row("RUFF-SUP-001", "`BLE001`", 1, "`BLE001=1`"))
    stray = _row("RUFF-SUP-999", "`F401`", 1, "`F401=1`")
    malformed = text.replace(
        index.BEGIN_MARKER,
        f"Human prose stops the table.\n{stray}\n\n{index.BEGIN_MARKER}",
    )
    with pytest.raises(index.PolicyMismatch, match="outside the human table"):
        index.parse_registry(malformed)


@pytest.mark.parametrize(
    "rows",
    [
        (_row("RUFF-SUP-001", "`BLE001`", 1, "`BLE001=1`"),) * 2,
        (_row("RUFF-SUP-001", "`BLE001`, `BLE001`", 1, "`BLE001=1`"),),
        (_row("RUFF-SUP-001", "`BLE001`", 1, "`BLE001=1`, `BLE001=1`"),),
        (_row("BAD-001", "`BLE001`", 1, "`BLE001=1`"),),
    ],
)
def test_duplicate_or_unknown_registry_identifiers_are_rejected(
    rows: tuple[str, ...],
) -> None:
    with pytest.raises(index.PolicyMismatch):
        index.parse_registry(_spec(*rows))


@pytest.mark.parametrize("field", ["invariant", "proof", "alternatives", "approval"])
@pytest.mark.parametrize("value", ["", "TBD", "pending owner", "placeholder"])
def test_human_registry_fields_reject_blank_and_placeholder_values(
    field: str, value: str
) -> None:
    kwargs = {field: value}
    with pytest.raises(index.PolicyMismatch):
        index.parse_registry(
            _spec(_row("RUFF-SUP-001", "`BLE001`", 1, "`BLE001=1`", **kwargs))
        )


def test_proof_must_name_executable_evidence_and_invariant_cannot_be_score_only() -> (
    None
):
    for kwargs in (
        {"proof": "The suppression is listed in the registry."},
        {"invariant": "Reduce C901 score 18."},
    ):
        with pytest.raises(index.PolicyMismatch):
            index.parse_registry(
                _spec(_row("RUFF-SUP-001", "`BLE001`", 1, "`BLE001=1`", **kwargs))
            )


def test_circular_human_rationale_is_rejected() -> None:
    with pytest.raises(index.PolicyMismatch, match="circular"):
        index.parse_registry(
            _spec(
                _row(
                    "RUFF-SUP-001",
                    "`BLE001`",
                    1,
                    "`BLE001=1`",
                    invariant="The suppression is registered in SC-17.1.",
                )
            )
        )


@pytest.mark.parametrize(
    "lifetime", ["temporary", "temporary: later", "temporary: T4 setup", "T6 cache"]
)
def test_temporary_lifetime_requires_a_named_cleanup_task(lifetime: str) -> None:
    with pytest.raises(index.PolicyMismatch):
        index.parse_registry(
            _spec(_row("RUFF-SUP-001", "`BLE001`", 1, "`BLE001=1`", lifetime=lifetime))
        )


def test_f401_is_a_generic_supported_rule() -> None:
    groups, _ = index.parse_registry(
        _spec(_row("RUFF-SUP-001", "`F401`", 1, "`F401=1`"))
    )
    assert groups["RUFF-SUP-001"].rules == ("F401",)


@pytest.mark.parametrize(
    "comment",
    [
        "# noqa: BLE001 approved [SC-17.1] [RUFF-SUP-001] exception",
        "# noqa: BLE001 [SC-17.1] RUFF-SUP-001 exception",
        "# noqa: BLE001 approved [SC-17.1] RUFF-SUP-001",
        "# noqa: BLE001,F401 approved [SC-17.1] RUFF-SUP-001 exception",
    ],
)
def test_malformed_governed_source_markers_are_rejected(
    tmp_path: Path, comment: str
) -> None:
    path = tmp_path / "bad.py"
    path.write_text(f"value = 1  {comment}\n", encoding="utf-8")
    with pytest.raises(index.PolicyMismatch):
        index.scan_source(path, tmp_path)


def test_duplicate_source_codes_are_a_policy_failure(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.py"
    path.write_text(
        "value = 1  # noqa: BLE001, BLE001 approved [SC-17.1] RUFF-SUP-001 exception\n",
        encoding="utf-8",
    )
    with pytest.raises(index.PolicyMismatch, match="duplicate noqa code"):
        index.scan_source(path, tmp_path)


@pytest.mark.parametrize(
    "unsafe", ["pipe|name.py", "tick`name.py", "line\nname.py", "line\rname.py"]
)
def test_markdown_unrepresentable_source_paths_are_rejected(
    tmp_path: Path, unsafe: str
) -> None:
    with pytest.raises(index.PolicyMismatch, match="cannot be represented"):
        index._relative(tmp_path / unsafe, tmp_path)


def test_prose_near_misses_do_not_create_source_directives(tmp_path: Path) -> None:
    path = tmp_path / "prose.py"
    path.write_text(
        'text = "# noqa: BLE001 approved [SC-17.1] RUFF-SUP-001 exception"\n'
        "# SC-17.1 discusses RUFF-SUP-001 without a noqa directive\n",
        encoding="utf-8",
    )
    assert index.scan_source(path, tmp_path) == []


def _one_group() -> Any:
    groups, _ = index.parse_registry(
        _spec(_row("RUFF-SUP-001", "`BLE001`", 1, "`BLE001=1`"))
    )
    return groups


def test_unknown_group_and_rule_are_rejected() -> None:
    groups = _one_group()
    finding = index.Finding("probe.py", 1, "BLE001")
    unknown_group = index.Directive("probe.py", 1, "work", "RUFF-SUP-999", ("BLE001",))
    unknown_rule = index.Directive("probe.py", 1, "work", "RUFF-SUP-001", ("F401",))
    with pytest.raises(index.PolicyMismatch):
        index.reconcile(groups, [unknown_group], [finding])
    with pytest.raises(index.PolicyMismatch):
        index.reconcile(groups, [unknown_rule], [finding])


def test_duplicate_source_pointer_is_rejected() -> None:
    groups = _one_group()
    directives = [
        index.Directive("probe.py", 1, "work", "RUFF-SUP-001", ("BLE001",)),
        index.Directive("probe.py", 2, "work", "RUFF-SUP-001", ("BLE001",)),
    ]
    findings = [
        index.Finding("probe.py", 1, "BLE001"),
        index.Finding("probe.py", 2, "BLE001"),
    ]
    with pytest.raises(index.PolicyMismatch, match="duplicate source pointer"):
        index.reconcile(groups, directives, findings)


@pytest.mark.parametrize("approved, include_directive", [(1, False), (3, True)])
def test_directive_cardinality_underflow_and_overflow_are_rejected(
    approved: int, include_directive: bool
) -> None:
    groups, _ = index.parse_registry(
        _spec(_row("RUFF-SUP-001", "`BLE001`", approved, f"`BLE001={approved}`"))
    )
    directive = index.Directive("probe.py", 1, "work", "RUFF-SUP-001", ("BLE001",))
    finding = index.Finding("probe.py", 1, "BLE001")
    directives = [directive] if include_directive else []
    findings = [finding] if include_directive else []
    with pytest.raises(index.PolicyMismatch, match="cardinality"):
        index.reconcile(groups, directives, findings)


def test_unregistered_raw_finding_and_directive_without_raw_are_rejected() -> None:
    groups = _one_group()
    directive = index.Directive("probe.py", 1, "work", "RUFF-SUP-001", ("BLE001",))
    with pytest.raises(index.PolicyMismatch, match="does not reconcile"):
        index.reconcile(
            groups,
            [directive],
            [
                index.Finding("probe.py", 1, "BLE001"),
                index.Finding("probe.py", 2, "F841"),
            ],
        )
    with pytest.raises(index.PolicyMismatch, match="do not match raw"):
        index.reconcile(groups, [directive], [])


def test_reviewed_multiple_raw_diagnostics_at_one_pointer_are_counted() -> None:
    groups, _ = index.parse_registry(
        _spec(_row("RUFF-SUP-001", "`BLE001`", 1, "`BLE001=2`"))
    )
    directive = index.Directive("probe.py", 1, "work", "RUFF-SUP-001", ("BLE001",))
    findings = [
        index.Finding("probe.py", 1, "BLE001"),
        index.Finding("probe.py", 1, "BLE001"),
    ]
    by_group = index.reconcile(groups, [directive], findings)
    rendered = "\n".join(index.render(groups, by_group))
    assert "Global active-rule raw inventory: `BLE001=2`" in rendered
    assert "| `RUFF-SUP-001` | `probe.py::work` | `1` | `BLE001=2` |" in rendered


def test_global_inventory_drift_is_stale_and_check_does_not_repair_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, spec, source = _fixture(tmp_path)
    _patch_ruff(monkeypatch, tmp_path, [path], _diagnostics(path, source))
    assert (
        index.main(["--repo-root", str(tmp_path), "--spec", str(spec), "--write"]) == 0
    )
    stale = spec.read_text(encoding="utf-8").replace(
        "Global active-rule raw inventory: `BLE001=1`, `F401=1`",
        "Global active-rule raw inventory: `BLE001=1`, `F401=9`",
    )
    spec.write_text(stale, encoding="utf-8")
    before = spec.read_bytes()
    assert (
        index.main(["--repo-root", str(tmp_path), "--spec", str(spec), "--check"]) == 1
    )
    assert spec.read_bytes() == before


def test_malformed_json_and_nonzero_ruff_are_tool_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, spec, source = _fixture(tmp_path)
    for stdout, returncode in (("not-json", 1), ("[]", 2)):
        _patch_ruff(
            monkeypatch,
            tmp_path,
            [path],
            _diagnostics(path, source),
            raw_stdout=stdout,
            raw_returncode=returncode,
        )
        assert (
            index.main(["--repo-root", str(tmp_path), "--spec", str(spec), "--check"])
            == 2
        )


@pytest.mark.parametrize(
    "payload",
    [
        "",
        "   \n",
        "{}",
        "[{}]",
        '[{"filename":"probe.py","filename":"other.py","noqa_row":1,"code":"F401"}]',
        '[{"filename":"probe.py","noqa_row":0,"code":"F401"}]',
        '[{"filename":"probe.py","noqa_row":-1,"code":"F401"}]',
        '[{"filename":"probe.py","noqa_row":true,"code":"F401"}]',
        '[{"filename":"probe.py","noqa_row":"1","code":"F401"}]',
    ],
)
def test_strict_ruff_json_rejects_empty_duplicate_or_invalid_rows(
    tmp_path: Path, payload: str
) -> None:
    result = subprocess.CompletedProcess([], 1, payload, "")
    with pytest.raises(index.ToolFailure):
        index._json_findings(result, tmp_path, label="Ruff raw audit")


def test_non_utf8_source_is_a_tool_failure(tmp_path: Path) -> None:
    path = tmp_path / "bad.py"
    path.write_bytes(b"\xff\xfe")
    with pytest.raises(index.ToolFailure):
        index.scan_source(path, tmp_path)


def test_ruff_reported_path_escape_is_a_tool_failure(tmp_path: Path) -> None:
    result = subprocess.CompletedProcess(
        [],
        1,
        json.dumps(
            [
                {
                    "filename": str(tmp_path.parent / "escape.py"),
                    "noqa_row": 1,
                    "code": "F401",
                }
            ]
        ),
        "",
    )
    with pytest.raises(index.ToolFailure, match="escapes"):
        index._json_findings(result, tmp_path, label="Ruff raw audit")


def test_discovery_nonzero_exit_is_a_tool_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_discovery(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 2, "", "synthetic discovery failure")

    monkeypatch.setattr(index, "_run_ruff", fail_discovery)
    with pytest.raises(index.ToolFailure, match="discovery failed"):
        index.discover_sources(tmp_path)


def test_unreadable_discovered_extensionless_source_is_a_tool_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "python-entry"
    path.write_text("#!/usr/bin/env python3\n", encoding="utf-8")

    def show_file(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 0, f"{path}\n", "")

    original_open = Path.open

    def fail_open(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self == path:
            raise OSError("synthetic unreadable entry point")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(index, "_run_ruff", show_file)
    monkeypatch.setattr(Path, "open", fail_open)
    with pytest.raises(index.ToolFailure, match="cannot read Ruff-discovered"):
        index.discover_sources(tmp_path)


def test_check_failure_does_not_mutate_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, spec, source = _fixture(tmp_path)
    _patch_ruff(monkeypatch, tmp_path, [path], _diagnostics(path, source))
    before = spec.read_bytes()
    assert (
        index.main(["--repo-root", str(tmp_path), "--spec", str(spec), "--check"]) == 1
    )
    assert spec.read_bytes() == before


def test_atomic_replacement_failure_preserves_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, spec, source = _fixture(tmp_path)
    _patch_ruff(monkeypatch, tmp_path, [path], _diagnostics(path, source))
    before = spec.read_bytes()

    def fail_replace(source_path: str, destination: Path) -> None:
        raise OSError("synthetic replacement failure")

    monkeypatch.setattr(index.os, "replace", fail_replace)
    assert (
        index.main(["--repo-root", str(tmp_path), "--spec", str(spec), "--write"]) == 2
    )
    assert spec.read_bytes() == before
    assert list(tmp_path.glob(f".{spec.name}.*")) == []


def test_atomic_replacement_preserves_mode_and_removes_temporary_file(
    tmp_path: Path,
) -> None:
    path = tmp_path / "policy.md"
    path.write_text("old\n", encoding="utf-8")
    path.chmod(0o640)
    index._atomic_write(path, "new\n")
    assert path.read_bytes() == b"new\n"
    assert path.stat().st_mode & 0o777 == 0o640
    assert list(tmp_path.glob(f".{path.name}.*")) == []


def test_unknown_generated_symbol_is_stale_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, spec, source = _fixture(tmp_path)
    _patch_ruff(monkeypatch, tmp_path, [path], _diagnostics(path, source))
    assert (
        index.main(["--repo-root", str(tmp_path), "--spec", str(spec), "--write"]) == 0
    )
    stale = spec.read_text(encoding="utf-8").replace(
        "probe.py::translate", "probe.py::missing_symbol"
    )
    spec.write_text(stale, encoding="utf-8")
    before = spec.read_bytes()
    assert (
        index.main(["--repo-root", str(tmp_path), "--spec", str(spec), "--check"]) == 1
    )
    assert spec.read_bytes() == before


def test_duplicate_generated_symbol_is_stale_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, spec, source = _fixture(tmp_path)
    _patch_ruff(monkeypatch, tmp_path, [path], _diagnostics(path, source))
    assert (
        index.main(["--repo-root", str(tmp_path), "--spec", str(spec), "--write"]) == 0
    )
    text = spec.read_text(encoding="utf-8")
    row = next(
        line
        for line in text.splitlines()
        if line.startswith("| `RUFF-SUP-001` |") and "probe.py::translate" in line
    )
    spec.write_text(
        text.replace(index.END_MARKER, f"{row}\n{index.END_MARKER}"),
        encoding="utf-8",
    )
    before = spec.read_bytes()
    assert (
        index.main(["--repo-root", str(tmp_path), "--spec", str(spec), "--check"]) == 1
    )
    assert spec.read_bytes() == before


def test_ruff_command_uses_locked_environment_and_canonical_targets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: dict[str, object] = {}

    def fake_subprocess(
        args: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        observed["args"] = args
        observed.update(kwargs)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(index.subprocess, "run", fake_subprocess)
    index._run_ruff(tmp_path, "check", *index.LINT_TARGETS)
    assert observed["args"] == [*index.RUFF_PREFIX, "check", *index.LINT_TARGETS]
    assert observed["cwd"] == tmp_path
    assert observed["check"] is False


def test_real_pinned_ruff_end_to_end_with_extensionless_governed_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UV_PROJECT", str(ROOT))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    governed = bin_dir / "check-doc-paths"
    governed.write_text(
        "#!/usr/bin/env python3\n"
        "import os  # noqa: F401 approved [SC-17.1] RUFF-SUP-001 exception\n",
        encoding="utf-8",
    )
    for name in ("check-dom15-fixtures", "coalesce-check"):
        (bin_dir / name).write_text(
            "#!/usr/bin/env python3\nvalue = 1\n", encoding="utf-8"
        )
    spec = tmp_path / "policy.md"
    spec.write_text(
        _spec(_row("RUFF-SUP-001", "`F401`", 1, "`F401=1`")),
        encoding="utf-8",
    )

    version = index._run_ruff(tmp_path, "--version")
    assert version.returncode == 0
    assert version.stdout.strip() == "ruff 0.15.21"
    discovered = index._run_ruff(tmp_path, "check", "--show-files", *index.LINT_TARGETS)
    assert discovered.returncode == 0, discovered.stderr
    assert str(governed.resolve()) in discovered.stdout.splitlines()

    normal = index._run_ruff(
        tmp_path, "check", "--output-format", "json", *index.LINT_TARGETS
    )
    raw = index._run_ruff(
        tmp_path,
        "check",
        "--ignore-noqa",
        "--output-format",
        "json",
        *index.LINT_TARGETS,
    )
    assert normal.returncode == 0
    assert json.loads(normal.stdout) == []
    assert raw.returncode == 1
    raw_payload = json.loads(raw.stdout)
    assert [(item["code"], item["noqa_row"]) for item in raw_payload] == [("F401", 2)]

    assert (
        index.main(["--repo-root", str(tmp_path), "--spec", str(spec), "--write"]) == 0
    )
    generated = spec.read_text(encoding="utf-8")
    assert "`bin/check-doc-paths::<module>`" in generated
    assert "Global active-rule raw inventory: `F401=1`" in generated
    assert (
        index.main(["--repo-root", str(tmp_path), "--spec", str(spec), "--check"]) == 0
    )


def test_cli_defaults_to_the_backstitch_core_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: dict[str, object] = {}

    def fake_run(root: Path, spec: Path, *, write: bool) -> None:
        observed.update(root=root, spec=spec, write=write)

    monkeypatch.setattr(index, "run", fake_run)
    assert index.main(["--repo-root", str(tmp_path), "--check"]) == 0
    assert observed == {
        "root": tmp_path,
        "spec": tmp_path / "docs/specs/02-backstitch-core.md",
        "write": False,
    }
