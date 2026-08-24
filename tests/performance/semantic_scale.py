"""Generated [EVC-10] scale fixture and pinned-runner contract helpers.

The 50 MiB fixture is generated outside the worktree. The committed shape is
the reviewed input; this module makes its source tree and its qualification
facts deterministic without checking a large synthetic tree into git.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

RUNNER_CONTRACT_FIELDS = frozenset(
    {
        "schema_version",
        "workflow_path",
        "job_id",
        "runs_on",
        "runner_image_os",
        "runner_image_version",
        "architecture",
        "cpu_model",
        "logical_cpu_count",
        "memory_bytes",
        "python_version",
        "uv_version",
        "uv_lock_sha256",
    }
)
_RUNNER_INTEGER_FIELDS = ("logical_cpu_count", "memory_bytes")
_RUNNER_STRING_FIELDS = tuple(
    sorted(
        RUNNER_CONTRACT_FIELDS - {"schema_version", "logical_cpu_count", "memory_bytes"}
    )
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_WILDCARD_CHARACTERS = frozenset("*?[]{}")
_SCALE_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "generator_version",
        "obligation_count",
        "python_module_count",
        "candidates_per_module",
        "discovery_candidate_count",
        "python_source_bytes",
    }
)


@dataclass(frozen=True, slots=True)
class ScaleShape:
    """Exact generator work counts and captured Python-source byte floor."""

    obligation_count: int
    python_module_count: int
    candidates_per_module: int
    discovery_candidate_count: int
    python_source_bytes: int


@dataclass(frozen=True, slots=True)
class RunnerQualification:
    """Whether the current runtime may produce a comparable scale result."""

    status: Literal["available", "unavailable"]
    reason: Literal[
        "runner_contract_missing",
        "runner_contract_invalid",
        "runtime_identity_unobserved",
        "runtime_identity_mismatch",
        "runtime_identity_match",
    ]
    mismatched_fields: tuple[str, ...]


def load_runner_contract(path: Path) -> dict[str, object]:
    """Load the one closed pinned-runtime identity from canonical JSON."""

    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"runner contract is unavailable: {path}") from exc
    if not isinstance(value, dict) or set(value) != RUNNER_CONTRACT_FIELDS:
        raise ValueError("runner contract fields do not match the schema")
    if value.get("schema_version") != 1 or isinstance(
        value.get("schema_version"), bool
    ):
        raise ValueError("runner contract schema_version must equal 1")
    for field in _RUNNER_STRING_FIELDS:
        item = value.get(field)
        if (
            not isinstance(item, str)
            or not item.strip()
            or any(character in _WILDCARD_CHARACTERS for character in item)
        ):
            raise ValueError(f"runner contract {field} must be nonblank and exact")
    for field in _RUNNER_INTEGER_FIELDS:
        item = value.get(field)
        if isinstance(item, bool) or not isinstance(item, int) or item < 1:
            raise ValueError(f"runner contract {field} must be a positive integer")
    lock_hash = value.get("uv_lock_sha256")
    if not isinstance(lock_hash, str) or _SHA256_RE.fullmatch(lock_hash) is None:
        raise ValueError("runner contract uv_lock_sha256 must be lowercase SHA-256")
    return {field: value[field] for field in sorted(RUNNER_CONTRACT_FIELDS)}


def compare_runner_identity(
    expected: dict[str, object], observed: dict[str, object]
) -> tuple[str, ...]:
    """Return exact runtime fields that make qualification unavailable."""

    identity_fields = RUNNER_CONTRACT_FIELDS - {"schema_version", "workflow_path"}
    return tuple(
        field
        for field in sorted(identity_fields)
        if expected.get(field) != observed.get(field)
    )


def assess_runner_qualification(
    contract_path: Path,
    observed: dict[str, object] | None,
) -> RunnerQualification:
    """Resolve availability before any latency or RSS measurement can run."""

    if not contract_path.is_file():
        return RunnerQualification(
            status="unavailable",
            reason="runner_contract_missing",
            mismatched_fields=(),
        )
    try:
        expected = load_runner_contract(contract_path)
    except ValueError:
        return RunnerQualification(
            status="unavailable",
            reason="runner_contract_invalid",
            mismatched_fields=(),
        )
    if observed is None:
        return RunnerQualification(
            status="unavailable",
            reason="runtime_identity_unobserved",
            mismatched_fields=(),
        )
    mismatched_fields = compare_runner_identity(expected, observed)
    if mismatched_fields:
        return RunnerQualification(
            status="unavailable",
            reason="runtime_identity_mismatch",
            mismatched_fields=mismatched_fields,
        )
    return RunnerQualification(
        status="available",
        reason="runtime_identity_match",
        mismatched_fields=(),
    )


def load_scale_shape(path: Path) -> ScaleShape:
    """Load and qualify the exact generated-fixture manifest."""

    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"scale fixture manifest is unavailable: {path}") from exc
    if not isinstance(value, dict) or set(value) != _SCALE_MANIFEST_FIELDS:
        raise ValueError("scale fixture manifest fields do not match the schema")
    if (
        value.get("schema_version") != 1
        or isinstance(value.get("schema_version"), bool)
        or value.get("generator_version") != 1
        or isinstance(value.get("generator_version"), bool)
    ):
        raise ValueError("scale fixture schema and generator versions must equal 1")
    shape = ScaleShape(
        obligation_count=value["obligation_count"],
        python_module_count=value["python_module_count"],
        candidates_per_module=value["candidates_per_module"],
        discovery_candidate_count=value["discovery_candidate_count"],
        python_source_bytes=value["python_source_bytes"],
    )
    validate_scale_shape(shape, require_qualification=True)
    return shape


def validate_scale_shape(shape: ScaleShape, *, require_qualification: bool) -> None:
    """Reject inconsistent work counts and, when requested, every EVC floor."""

    for field in (
        "obligation_count",
        "python_module_count",
        "candidates_per_module",
        "discovery_candidate_count",
        "python_source_bytes",
    ):
        value = getattr(shape, field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{field} must be a positive integer")
    if shape.python_module_count % shape.obligation_count:
        raise ValueError("python_module_count must divide evenly across obligations")
    expected_candidates = shape.python_module_count * shape.candidates_per_module
    if shape.discovery_candidate_count != expected_candidates:
        raise ValueError(
            "discovery_candidate_count must equal modules times candidates_per_module"
        )
    if not require_qualification:
        return
    floors = {
        "obligation_count": 1_000,
        "python_module_count": 5_000,
        "discovery_candidate_count": 20_000,
        "python_source_bytes": 50 * 1024 * 1024,
    }
    for field, minimum in floors.items():
        if getattr(shape, field) < minimum:
            raise ValueError(f"{field} is below the EVC-10 qualification floor")


def _obligation_token(index: int) -> str:
    value = index
    letters: list[str] = []
    for _ in range(4):
        value, remainder = divmod(value, 26)
        letters.append(chr(ord("a") + remainder))
    if value:
        raise ValueError("fixture has more obligations than the token space")
    return "q" + "".join(reversed(letters))


def _padded_module_bytes(base: bytes, target_bytes: int) -> bytes:
    remaining = target_bytes - len(base)
    prefix = b'__semantic_scale_padding__ = b"'
    suffix = b'"\n'
    if remaining < len(prefix) + len(suffix):
        raise ValueError("python_source_bytes is too small for generated modules")
    payload = b"x" * (remaining - len(prefix) - len(suffix))
    return base + prefix + payload + suffix


def _fixture_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        raw = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()


def _fixture_config(shape: ScaleShape) -> bytes:
    candidates_per_obligation = (
        shape.python_module_count
        // shape.obligation_count
        * shape.candidates_per_module
    )
    maximum_page_size = max(shape.obligation_count, candidates_per_obligation)
    return (
        "[profile]\n"
        'name = "backstitch-style-v1"\n'
        'spec_roots = ["docs/specs"]\n'
        'plan_roots = ["docs/plans"]\n'
        'code_roots = ["src"]\n'
        "test_roots = []\n"
        "\n[obligations]\n"
        f"page_size = {shape.obligation_count}\n"
        f"maximum_page_size = {maximum_page_size}\n"
        "maximum_response_bytes = 100000000\n"
        f"maximum_candidate_items = {candidates_per_obligation}\n"
        "maximum_catalog_items = 100000\n"
        f"maximum_lexical_seeds = {candidates_per_obligation}\n"
        f"maximum_snapshot_files = {shape.python_module_count + 10}\n"
        "maximum_snapshot_bytes = 100000000\n"
        "maximum_work_units = 2000000\n"
        "maximum_packet_bytes = 500000000\n"
        "maximum_packet_report_bytes = 500000000\n"
        "maximum_call_seconds = 60.0\n"
        "static_neighbor_depth = 0\n"
        "\n[analyze]\n"
        'backend_id = "llm"\n'
        'plugin_id = "performance-fixture"\n'
        'plugin_distribution_name = "llm"\n'
        'model = "pkg:service/backstitch.test/semantic-scale-fixture"\n'
        'adapter_model_id = "semantic-scale-fixture"\n'
        'model_revision = "1"\n'
        "capability_schema_version = 1\n"
        'capability_revision = "semantic-scale-fixture-v1"\n'
        "maximum_input_bytes = 500000000\n"
        "request_constraints = { "
        'json_mode = { presence = "required", allowed_values = ["require"] }, '
        'temperature = { presence = "optional", allowed_values = [0.0] }, '
        'seed = { presence = "optional", minimum = 0, maximum = 2147483647 }, '
        'max_tokens = { presence = "required", minimum = 1, maximum = 16384 }, '
        'reasoning_effort = { presence = "forbidden" }'
        " }\n"
        "input_cost_microusd_per_million_tokens = 0\n"
        "output_cost_microusd_per_million_tokens = 0\n"
        "input_token_overhead = 0\n"
        'cost_rate_source = "deterministic performance fixture"\n'
        'json_mode = "require"\n'
        'cache_path = ".backstitch/performance-cache"\n'
        'cache_mode = "require"\n'
        f"maximum_packets = {shape.obligation_count}\n"
        "maximum_prompt_bytes = 500000000\n"
        f"maximum_provider_calls = {shape.obligation_count}\n"
    ).encode()


def generate_scale_fixture(root: Path, shape: ScaleShape) -> str:
    """Materialize one path-stable deterministic source tree."""

    validate_scale_shape(shape, require_qualification=False)
    if root.exists() and any(root.iterdir()):
        raise ValueError(f"scale fixture root is not empty: {root}")
    root.mkdir(parents=True, exist_ok=True)
    spec_dir = root / "docs" / "specs"
    plans_dir = root / "docs" / "plans"
    source_dir = root / "src"
    spec_dir.mkdir(parents=True)
    plans_dir.mkdir(parents=True)
    source_dir.mkdir(parents=True)
    (root / ".backstitch.toml").write_bytes(_fixture_config(shape))
    (plans_dir / "README.md").write_bytes(b"# Performance fixture plans\n")

    modules_per_obligation = shape.python_module_count // shape.obligation_count
    spec_lines = ["# Semantic scale fixture", ""]
    quotient, remainder = divmod(shape.python_source_bytes, shape.python_module_count)
    module_index = 0
    for obligation_index in range(shape.obligation_count):
        token = _obligation_token(obligation_index)
        obligation_id = f"SCALE-{obligation_index:04d}"
        mapped_path = f"src/{token}/m0000.py"
        mapped_symbol = f"{token}_m0000_c0000"
        spec_lines.extend(
            (
                f"## {token} contract [{obligation_id}]",
                "",
                f"{token} behavior remains stable.",
                "",
                "_Implementation mapping_:",
                "",
                f"- `{mapped_path}::{mapped_symbol}`",
                "",
            )
        )
        token_dir = source_dir / token
        token_dir.mkdir()
        for local_module in range(modules_per_obligation):
            module_name = f"m{local_module:04d}"
            rows: list[str] = []
            for candidate_index in range(shape.candidates_per_module):
                symbol = f"{token}_{module_name}_c{candidate_index:04d}"
                rows.append(f"def {symbol}() -> int:")
                if local_module == 0 and candidate_index == 0:
                    rows.append(
                        f'    """Spec: docs/specs/01-scale.md [{obligation_id}]"""'
                    )
                rows.append(f"    return {candidate_index}")
                rows.append("")
            base = ("\n".join(rows) + "\n").encode("utf-8")
            target = quotient + (1 if module_index < remainder else 0)
            (token_dir / f"{module_name}.py").write_bytes(
                _padded_module_bytes(base, target)
            )
            module_index += 1
    (spec_dir / "01-scale.md").write_bytes(
        ("\n".join(spec_lines).rstrip() + "\n").encode("utf-8")
    )
    return _fixture_digest(root)


def inspect_scale_fixture(root: Path, shape: ScaleShape) -> dict[str, Any]:
    """Recompute the exact generator-owned counts from materialized bytes."""

    modules = sorted((root / "src").rglob("*.py"))
    source_bytes = sum(path.stat().st_size for path in modules)
    spec = (root / "docs" / "specs" / "01-scale.md").read_text(encoding="utf-8")
    obligation_count = sum(line.startswith("## ") for line in spec.splitlines())
    return {
        "fixture_sha256": _fixture_digest(root),
        "obligation_count": obligation_count,
        "python_module_count": len(modules),
        "catalog_candidate_count": len(modules) * (shape.candidates_per_module + 1),
        "discovery_candidate_count": len(modules) * shape.candidates_per_module,
        "python_source_bytes": source_bytes,
    }
