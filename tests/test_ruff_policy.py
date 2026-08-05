"""Pre-activation policy tests for Backstitch's canonical Ruff environment.

Spec baseline: docs/specs/02-backstitch-core.md [SC-10], [SC-17]
Plan: docs/plans/2026-08-05-ruff-complexity-and-suppression-registry-plan.md T2

T2 freezes version, discovery, and the current rule/noqa inventory. C901
activation belongs to T4 and is intentionally not asserted here.
"""

from __future__ import annotations

import ast
import csv
import fnmatch
import hashlib
import io
import json
import re
import subprocess
import tokenize
import tomllib
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUFF_VERSION = "0.15.21"
RULE_FIXTURE = ROOT / "tests" / "fixtures" / "ruff-enabled-rules.txt"
EXCLUSION_FIXTURE = ROOT / "tests" / "fixtures" / "ruff-excluded-python.tsv"
ACTIVATION_LEDGER = (
    ROOT
    / "docs"
    / "plans"
    / "artifacts"
    / "2026-08-05-ruff-suppression-activation-ledger.tsv"
)
CANONICAL_LINT_TARGETS = (
    ".",
    "bin/check-doc-paths",
    "bin/check-dom15-fixtures",
    "bin/coalesce-check",
)
EXTENSIONLESS_PYTHON = frozenset(CANONICAL_LINT_TARGETS[1:])
FORMAT_TARGETS = ("backstitch", "bin", ".github/scripts", "tests")
REVIEWED_EXCLUSIONS = (
    "tests/fixtures/**",
    "tests/**/fixtures/**",
    "tests/semantic_eval/v1/fixture/**",
)
# These are the only Python files a pre-landing implementation may add before
# Git makes them part of the tracked authority. Missing entries are harmless;
# an unexpected untracked Python file is not silently promoted to authority.
PLANNED_PRELANDING_PYTHON = frozenset(
    {
        "bin/ruff_suppression_index.py",
        "tests/test_ruff_policy.py",
        "tests/test_ruff_suppression_index.py",
    }
)
EXCLUSION_INVENTORY_COLUMNS = (
    "path",
    "sha256",
    "reviewed_role",
    "behavioral_proof",
)
TEMPORARY_TARGET_BY_PATH = {
    "backstitch/settings.py": "T5 settings",
    "backstitch/semantic_analysis.py": "T6 cache and semantic execution",
    "backstitch/semantic_application.py": "T6 cache and semantic execution",
    "backstitch/semantic_cache.py": "T6 cache and semantic execution",
    "backstitch/semantic_eval.py": "T7 eval, reports, and artifacts",
    "backstitch/semantic_reports.py": "T7 eval, reports, and artifacts",
    "backstitch/alignment_eval.py": "T8 alignment, CLI, evidence, and coverage",
    "backstitch/cli.py": "T8 alignment, CLI, evidence, and coverage",
    "backstitch/coverage_application.py": ("T8 alignment, CLI, evidence, and coverage"),
    "backstitch/evidence_summary.py": "T8 alignment, CLI, evidence, and coverage",
    "backstitch/intent_history.py": "T8 alignment, CLI, evidence, and coverage",
    "backstitch/obligations.py": "T8 alignment, CLI, evidence, and coverage",
    "backstitch/semantic_evidence.py": ("T8 alignment, CLI, evidence, and coverage"),
    "bin/coalesce-check": "T9 tests, tools, and P3",
    "bin/release.py": "T9 tests, tools, and P3",
    "tests/live/test_live_llm.py": "T9 tests, tools, and P3",
    "tests/semantic_eval/v3/generate_qualification_candidate.py": (
        "T9 tests, tools, and P3"
    ),
    "tests/test_canonical_owners.py": "T9 tests, tools, and P3",
}
LEDGER_COLUMNS = (
    "group_id",
    "path_symbol",
    "rules",
    "rule_raw_counts",
    "directive_count",
    "score",
    "priority",
    "target_slice",
    "lifetime",
    "protected_invariant",
    "real_proof",
    "rejected_alternative",
    "approval",
    "freeze_status",
)
ACTIVE_RAW_COUNTS = Counter({"F401": 1})
DISABLED_TEXTUAL_NOQA_COUNTS = Counter({"BLE001": 22, "N802": 14, "S310": 9})


def _ruff(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("uv", "run", "--frozen", "--no-sync", "ruff", *args),
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _manifest_ruff_pin() -> str:
    with (ROOT / "pyproject.toml").open("rb") as stream:
        dev = tomllib.load(stream)["project"]["optional-dependencies"]["dev"]
    pins = [item for item in dev if item.startswith("ruff")]
    assert len(pins) == 1
    pin = pins[0]
    assert isinstance(pin, str)
    return pin


def _lock_data() -> dict[str, object]:
    with (ROOT / "uv.lock").open("rb") as stream:
        return tomllib.load(stream)


def _enabled_rules() -> set[str]:
    result = _ruff("check", "--show-settings", "backstitch/__init__.py")
    assert result.returncode == 0, result.stderr
    match = re.search(
        r"linter\.rules\.enabled = \[\n(?P<rules>.*?)\n\]",
        result.stdout,
        re.DOTALL,
    )
    assert match is not None, result.stdout
    return set(re.findall(r"\(([A-Z]+\d+)\)", match.group("rules")))


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _fixture_tree_sha256(root: Path) -> str:
    files = [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": _sha256(path.read_bytes()),
        }
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    ]
    canonical = json.dumps({"files": files}, separators=(",", ":")).encode()
    return _sha256(canonical)


def _top_level_test_symbols(path: Path) -> set[str]:
    symbols: set[str] = set()
    tree = ast.parse(path.read_bytes(), filename=path.as_posix())
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                symbols.add(node.name)
            continue
        if not isinstance(node, ast.ClassDef):
            continue
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                child.name.startswith("test_")
            ):
                symbols.add(f"{node.name}.{child.name}")
    return symbols


def _python_paths_from_git(*args: str) -> set[str]:
    result = subprocess.run(
        ("git", "ls-files", *args, "-z"),
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    paths: set[str] = set()
    for raw_path in result.stdout.split(b"\0"):
        if not raw_path:
            continue
        relative = raw_path.decode()
        path = ROOT / relative
        if relative.endswith((".py", ".pyi")):
            paths.add(relative)
            continue
        if path.is_file() and (lines := path.read_bytes().splitlines()[:1]):
            first_line = lines[0]
            if first_line.startswith(b"#!") and b"python" in first_line.lower():
                paths.add(relative)
    return paths


def _tracked_python_files() -> set[str]:
    return _python_paths_from_git("--cached")


def _planned_untracked_python_files() -> set[str]:
    untracked = _python_paths_from_git("--others", "--exclude-standard")
    unexpected = untracked - PLANNED_PRELANDING_PYTHON
    assert not unexpected, f"unreviewed untracked Python files: {sorted(unexpected)}"
    return untracked


def _lint_authority() -> set[str]:
    return _tracked_python_files() | _planned_untracked_python_files()


def _is_reviewed_exclusion(path: str) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in REVIEWED_EXCLUSIONS)


def _ruff_discovery() -> set[str]:
    result = _ruff("check", "--show-files", *CANONICAL_LINT_TARGETS)
    assert result.returncode == 0, result.stderr
    return {
        Path(line).resolve().relative_to(ROOT).as_posix()
        for line in result.stdout.splitlines()
        if line
    }


def _release_tuple(name: str) -> tuple[str, ...]:
    tree = ast.parse((ROOT / "bin" / "release.py").read_bytes())
    for node in tree.body:
        if not isinstance(node, ast.AnnAssign):
            continue
        if isinstance(node.target, ast.Name) and node.target.id == name:
            assert node.value is not None
            value = ast.literal_eval(node.value)
            assert isinstance(value, tuple)
            assert all(isinstance(item, str) for item in value)
            return value
    raise AssertionError(f"missing release command tuple {name}")


def _textual_noqa_counts(paths: set[str]) -> Counter[str]:
    counts: Counter[str] = Counter()
    pattern = re.compile(r"#\s*noqa:\s*(?P<rules>.*)", re.IGNORECASE)
    for relative in sorted(paths):
        path = ROOT / relative
        try:
            tokens = tokenize.tokenize(io.BytesIO(path.read_bytes()).readline)
            for token in tokens:
                if token.type != tokenize.COMMENT:
                    continue
                match = pattern.search(token.string)
                if match is None:
                    continue
                for raw_rule in match.group("rules").split(","):
                    rule = re.match(r"\s*([A-Z]+\d+)", raw_rule)
                    if rule is not None:
                        counts[rule.group(1)] += 1
        except (IndentationError, SyntaxError, tokenize.TokenError):
            raise AssertionError(
                f"lint-eligible source is not tokenizable: {relative}"
            ) from None
    return counts


def test_manifest_lock_metadata_and_running_binary_use_one_exact_ruff() -> None:
    assert _manifest_ruff_pin() == f"ruff=={RUFF_VERSION}"

    packages = _lock_data()["package"]
    assert isinstance(packages, list)
    ruff_packages = [item for item in packages if item["name"] == "ruff"]
    assert [item["version"] for item in ruff_packages] == [RUFF_VERSION]
    root_packages = [item for item in packages if item["name"] == "backstitch"]
    assert len(root_packages) == 1
    requirements = root_packages[0]["metadata"]["requires-dist"]
    locked_requirements = [item for item in requirements if item["name"] == "ruff"]
    assert locked_requirements == [
        {
            "name": "ruff",
            "marker": "extra == 'dev'",
            "specifier": f"=={RUFF_VERSION}",
        }
    ]

    result = _ruff("--version")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"ruff {RUFF_VERSION}"


def test_effective_rules_match_the_pinned_binary_fixture() -> None:
    expected = set(RULE_FIXTURE.read_text(encoding="utf-8").splitlines())
    assert expected
    assert _enabled_rules() == expected


def test_canonical_lint_discovery_matches_tracked_eligible_sources() -> None:
    tracked = _tracked_python_files()
    planned_untracked = _planned_untracked_python_files()
    authority = tracked | planned_untracked
    eligible = {path for path in authority if not _is_reviewed_exclusion(path)}
    discovered = _ruff_discovery()

    assert EXTENSIONLESS_PYTHON <= tracked
    assert EXTENSIONLESS_PYTHON <= discovered
    assert planned_untracked <= PLANNED_PRELANDING_PYTHON
    assert discovered & authority == eligible
    assert discovered - eligible == {"pyproject.toml"}


def test_each_excluded_python_input_has_an_exact_reviewed_role_and_digest() -> None:
    tracked = _tracked_python_files()
    excluded = {path for path in tracked if _is_reviewed_exclusion(path)}

    with EXCLUSION_FIXTURE.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        rows = list(reader)

    assert tuple(reader.fieldnames or ()) == EXCLUSION_INVENTORY_COLUMNS
    assert all(all(value.strip() for value in row.values()) for row in rows)
    assert [row["path"] for row in rows] == sorted(excluded)
    assert len({row["path"] for row in rows}) == len(rows)
    for row in rows:
        fixture = ROOT / row["path"]
        proof_parts = row["behavioral_proof"].split("::", 1)
        assert len(proof_parts) == 2, row["behavioral_proof"]
        proof_path, proof_symbol = proof_parts
        assert _sha256(fixture.read_bytes()) == row["sha256"]
        assert proof_symbol in _top_level_test_symbols(ROOT / proof_path), row[
            "behavioral_proof"
        ]


def test_legacy_semantic_eval_v1_manifest_hashes_every_fixture_input() -> None:
    corpus = ROOT / "tests" / "semantic_eval" / "v1"
    manifest = json.loads((corpus / "manifest.json").read_bytes())
    cases = manifest["cases"]
    assert isinstance(cases, list)

    fixture_names = {case["fixture"] for case in cases}
    assert fixture_names == {"fixture"}
    fixture = corpus / "fixture"
    python_inputs = {
        path.relative_to(fixture).as_posix() for path in fixture.rglob("*.py")
    }
    assert len(python_inputs) == 9

    fixture_hashes = {case["fixture_sha256"] for case in cases}
    assert fixture_hashes == {_fixture_tree_sha256(fixture)}

    transformed_paths: set[str] = set()
    for case in cases:
        transform = case["transform"]
        relative = transform["path"]
        source = (fixture / relative).read_bytes()
        before = transform["before"].encode()
        after = transform["after"].encode()
        assert _sha256(source) == transform["source_sha256"]
        assert source.count(before) == 1
        assert _sha256(source.replace(before, after)) == transform["mutated_sha256"]
        transformed_paths.add(relative)

    assert transformed_paths <= python_inputs
    assert python_inputs - transformed_paths == {"backstitch/binding_case.py"}


def test_lint_vector_does_not_expand_the_formatter_scope() -> None:
    with (ROOT / "pyproject.toml").open("rb") as stream:
        ruff_config = tomllib.load(stream)["tool"]["ruff"]
    assert "extend-include" not in ruff_config
    assert tuple(ruff_config["extend-exclude"]) == REVIEWED_EXCLUSIONS
    assert _release_tuple("RUFF_FORMAT_COMMAND") == (
        "uv",
        "run",
        "ruff",
        "format",
        "--check",
        *FORMAT_TARGETS,
    )
    assert not EXTENSIONLESS_PYTHON.intersection(FORMAT_TARGETS)
    default_bin = _ruff("check", "--show-files", "bin")
    assert default_bin.returncode == 0, default_bin.stderr
    assert {
        Path(line).resolve().relative_to(ROOT).as_posix()
        for line in default_bin.stdout.splitlines()
        if line
    } == {"bin/release.py", "bin/ruff_suppression_index.py"}


def test_provisional_activation_ledger_has_the_reviewed_t2_inventory() -> None:
    with ACTIVATION_LEDGER.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        rows = list(reader)

    assert tuple(reader.fieldnames or ()) == LEDGER_COLUMNS
    assert len(rows) == 153
    assert all(all(value.strip() for value in row.values()) for row in rows)
    assert [row["group_id"] for row in rows] == [
        f"RUFF-SUP-{number:03d}" for number in range(1, 154)
    ]
    assert [(row["rules"], row["path_symbol"]) for row in rows] == sorted(
        (row["rules"], row["path_symbol"]) for row in rows
    )
    assert Counter(row["rules"] for row in rows) == Counter({"C901": 152, "F401": 1})
    assert Counter(
        row["priority"] for row in rows if row["rules"] == "C901"
    ) == Counter({"P1": 22, "P2": 27, "P3": 103})
    temporary = [row for row in rows if row["lifetime"] == "temporary"]
    assert all(
        row["target_slice"]
        == TEMPORARY_TARGET_BY_PATH[row["path_symbol"].split("::", 1)[0]]
        for row in temporary
    )
    assert all(row["approval"] == "pending owner" for row in rows)
    assert all(row["freeze_status"] == "proposed" for row in rows)


def test_raw_active_and_disabled_textual_noqa_are_separate() -> None:
    result = _ruff(
        "check",
        "--ignore-noqa",
        "--output-format",
        "json",
        *CANONICAL_LINT_TARGETS,
    )
    assert result.returncode == 1, result.stderr
    diagnostics = json.loads(result.stdout)
    assert Counter(item["code"] for item in diagnostics) == ACTIVE_RAW_COUNTS
    assert [
        Path(item["filename"]).resolve().relative_to(ROOT).as_posix()
        for item in diagnostics
    ] == ["backstitch/doctor.py"]

    enabled = _enabled_rules()
    authority = _lint_authority()
    textual = _textual_noqa_counts(
        authority - {path for path in authority if _is_reviewed_exclusion(path)}
    )
    active_textual = Counter(
        {rule: count for rule, count in textual.items() if rule in enabled}
    )
    disabled_textual = textual - active_textual
    assert active_textual == ACTIVE_RAW_COUNTS
    assert disabled_textual == DISABLED_TEXTUAL_NOQA_COUNTS


def test_current_canonical_lint_vector_is_clean_without_c901_activation() -> None:
    result = _ruff("check", *CANONICAL_LINT_TARGETS)
    assert result.returncode == 0, result.stdout + result.stderr
