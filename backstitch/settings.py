"""TOML configuration discovery and resolution.

Spec: docs/specs/03-backstitch-configuration.md [CFG-1], [CFG-2], [CFG-3], [CFG-4],
[CFG-5], [CFG-5.1], [CFG-6], [CFG-6.6], [CFG-8]
Spec: docs/specs/02-backstitch-core.md [SC-5.1], [SC-17]
Spec: docs/specs/04-backstitch-traceability-exclusions.md [EXC-3], [EXC-6]
Spec: docs/specs/02-backstitch-core.md [SC-13]
Spec: docs/specs/06-semantic-gates.md [SEM-9]
Spec: docs/specs/06-semantic-gates.md [SEM-9.1]
Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-8.2], [EVC-8.3.1]
Spec: docs/specs/05-backstitch-invariants.md [INV-11]
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import stat
import sys
import tomllib
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Literal, cast
from urllib.parse import quote, unquote_to_bytes

from backstitch import filesystem_io
from backstitch.canonical import canonical_repository_path
from backstitch.config import lexical_absolute_path, uncontained_test_root
from backstitch.diagnostics import (
    DiagnosticConfigError,
    DiagnosticsSettings,
    canonicalize_code,
    default_policy,
    default_registry,
    is_ordinary_diagnostic_code,
    load_default_config_raw,
    parse_policy,
    policy_to_dict,
    resolved_policy_to_dict,
)
from backstitch.grammar import (
    SECTION_ID_RE,
    is_prefixed_sha256,
    is_sha256_hex,
    is_valid_suppression_reference,
)
from backstitch.models import SuppressionOrigin, SuppressionRule
from backstitch.semantic_identity import (
    REASONING_EFFORT_VALUES,
    ReasoningEffort,
    RequestConstraints,
    RequestFieldConstraint,
)

DEFAULT_EXCLUDES: tuple[str, ...] = tuple(load_default_config_raw()["exclude"])
PACKAGED_DEFAULTS_LAYER = "packaged:backstitch/defaults.toml"
PACKAGED_DEFAULTS_PATH = Path(__file__).with_name("defaults.toml").resolve()
MAXIMUM_CONFIG_CHAIN_FILES = 64
MAXIMUM_CONFIG_FILE_BYTES = 1_000_000
MAXIMUM_CONFIG_CHAIN_BYTES = 5_000_000
_INVOCATION_COMMAND_UNSET = object()
CONFIG_CONSUMING_COMMANDS = frozenset(
    {
        "check",
        "packets",
        "coverage",
        "analyze",
        "eval",
        "doctor",
        "config",
        "obligation",
    }
)
_MODEL_ENVIRONMENT_COMMANDS = frozenset({"analyze", "eval", "doctor", "config"})

_TOP_LEVEL_KEYS = frozenset(
    {
        "defaults",
        "profile",
        "extend",
        "allow_unknown_keys",
        "default_command",
        "exclude",
        "extend_exclude",
        "lint",
    }
)
_TABLE_KEYS = frozenset(
    {
        "defaults",
        "profile",
        "check",
        "packets",
        "analyze",
        "coverage",
        "verify",
        "obligations",
        "target_roots",
        "lint",
        "diagnostics",
    }
)
_DEFAULTS_KEYS = frozenset({"schema_version"})
_PROFILE_KEYS = frozenset(
    {
        "name",
        "spec_roots",
        "plan_roots",
        "code_roots",
        "test_roots",
        "planned_spec_globs",
        "exploratory_spec_globs",
        "meta_spec_globs",
        "process_spec_globs",
    }
)
_LINT_KEYS = frozenset(
    {
        "warn_unused_ignores",
        "require_suppression_declarations",
        "per-file-ignores",
        "per-section-ignores",
        "suppressions",
    }
)
_SUPPRESSION_KEYS = frozenset({"mechanism", "path", "sections", "codes", "declaration"})
_CHECK_KEYS = frozenset({"format", "warnings_as_errors", "output"})
_PACKETS_KEYS = frozenset({"output"})
_COVERAGE_KEYS = frozenset(
    {
        "mode",
        "format",
        "output",
        "granularity",
        "inherited_counts",
        "ratchet_base",
        "exemptions",
        "floors",
        "maximum_baseline_files",
        "maximum_file_bytes",
        "maximum_baseline_bytes",
        "maximum_history_commits",
        "maximum_git_command_seconds",
        "maximum_git_commands",
        "maximum_git_output_bytes",
        "maximum_commit_message_bytes",
        "maximum_runtime_seconds",
    }
)
_COVERAGE_EXEMPTION_KEYS = frozenset({"path", "glob", "reason"})
_COVERAGE_FLOOR_KEYS = frozenset({"direct", "accounted"})
_COVERAGE_PRESENTATION_KEYS = frozenset({"coverage.format", "coverage.output"})
_ANALYZE_REQUIRED_FLAT_DESCRIPTOR_KEYS = frozenset(
    {
        "backend_id",
        "plugin_id",
        "plugin_distribution_name",
        "model",
        "model_revision",
        "capability_schema_version",
        "capability_revision",
        "request_constraints",
        "maximum_input_bytes",
        "input_cost_microusd_per_million_tokens",
        "output_cost_microusd_per_million_tokens",
        "input_token_overhead",
        "cost_rate_source",
    }
)
_ANALYZE_FLAT_DESCRIPTOR_KEYS = _ANALYZE_REQUIRED_FLAT_DESCRIPTOR_KEYS | {
    "adapter_model_id"
}
_ANALYZE_CATALOG_DESCRIPTOR_KEYS = (
    _ANALYZE_REQUIRED_FLAT_DESCRIPTOR_KEYS - {"model"}
) | {"adapter_model_id"}
_SERVICE_PURL_RE = re.compile(
    r"^pkg:service/"
    r"(?P<namespace>[^/@?#]+)/"
    r"(?P<name>[^/@?#]+)"
    r"(?:@(?P<version>[^?#]+))?"
    r"(?:\?(?P<qualifiers>[^#]+))?$"
)
_DNS_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_SERVICE_QUALIFIER_KEY_RE = re.compile(r"^[a-z][a-z0-9._-]*$")
_COMMON_DNS_TLDS = frozenset(
    {
        "ac",
        "ai",
        "app",
        "art",
        "audio",
        "cn",
        "co",
        "com",
        "dev",
        "edu",
        "gov",
        "io",
        "mil",
        "net",
        "org",
        "tech",
    }
)
_SERVICE_PRIVATE_ONLY_QUALIFIERS = frozenset(
    {"repository", "repository_path", "repository_url", "repo_path"}
)
_ANALYZE_KEYS = frozenset(
    {
        "backend_id",
        "plugin_id",
        "plugin_distribution_name",
        "model",
        "adapter_model_id",
        "model_revision",
        "capability_schema_version",
        "capability_revision",
        "request_constraints",
        "maximum_input_bytes",
        "concurrency",
        "json_mode",
        "temperature",
        "seed",
        "max_tokens",
        "reasoning_effort",
        "cache_path",
        "cache_mode",
        "result_reuse",
        "search_epoch",
        "require_complete",
        "required_kinds",
        "minimum_packets",
        "maximum_packets",
        "maximum_prompt_bytes",
        "finding_handling",
        "candidate_handling",
        "maximum_provider_calls",
        "lock_wait_timeout_seconds",
        "maximum_runtime_seconds",
        "maximum_estimated_cost_microusd",
        "input_cost_microusd_per_million_tokens",
        "output_cost_microusd_per_million_tokens",
        "input_token_overhead",
        "cost_rate_source",
        "dispositions",
        "models",
    }
)
_VERIFY_KEYS = frozenset(
    {
        "enabled",
        "provider_source",
        "concurrency",
        "cache_path",
        "cache_mode",
        "search_epochs",
        "json_mode",
        "temperature",
        "seed",
        "max_tokens",
        "reasoning_effort",
        "required_verdicts",
        "minimum_support_score",
        "indeterminate",
        "maximum_provider_calls",
        "maximum_prompt_bytes",
        "lock_wait_timeout_seconds",
        "maximum_runtime_seconds",
        "maximum_estimated_cost_microusd",
        "provider",
        "eval",
    }
)
_VERIFY_PROVIDER_KEYS = frozenset(
    {
        "backend_id",
        "plugin_id",
        "plugin_distribution_name",
        "model",
        "adapter_model_id",
        "model_revision",
        "capability_schema_version",
        "capability_revision",
        "request_constraints",
        "maximum_input_bytes",
        "input_cost_microusd_per_million_tokens",
        "output_cost_microusd_per_million_tokens",
        "input_token_overhead",
        "cost_rate_source",
    }
)
_VERIFY_EVAL_KEYS = frozenset(
    {
        "mode",
        "qualification_corpus",
        "qualification_corpus_sha256",
        "qualification_report",
        "qualification_report_sha256",
        "trials",
        "interval_method",
        "confidence_level",
        "minimum_positive_units",
        "minimum_negative_units",
        "minimum_evidence_sufficiency_rate",
        "minimum_conditional_precision",
        "minimum_conditional_recall",
        "minimum_end_to_end_recall",
        "minimum_recall_lower_bound",
        "maximum_false_positive_rate",
        "maximum_false_positive_upper_bound",
        "maximum_indeterminate_rate",
        "maximum_uncached_flip_rate",
        "require_all_critical",
    }
)
_OBLIGATION_KEYS = frozenset(
    {
        "section_required_roles",
        "page_size",
        "maximum_page_size",
        "maximum_response_bytes",
        "maximum_candidate_items",
        "maximum_catalog_items",
        "maximum_lexical_seeds",
        "maximum_snapshot_files",
        "maximum_file_bytes",
        "maximum_snapshot_bytes",
        "maximum_work_units",
        "maximum_packet_bytes",
        "maximum_packet_report_bytes",
        "maximum_call_seconds",
        "snapshot_capture_attempts",
        "static_neighbor_depth",
    }
)
_DISPOSITION_KEYS = frozenset(
    {"code", "packet_id", "packet_hash", "finding_hash", "status", "reason"}
)
_SEMANTIC_CODES = frozenset(
    {
        "SEMANTIC_CONFIRMED_MISMATCH",
        "SEMANTIC_PROBABLE_MISMATCH",
        "SEMANTIC_MISSING_TRACE",
        "SEMANTIC_WEAK_BINDING",
        "SEMANTIC_AMBIGUOUS",
        "SEMANTIC_SUPPRESSION_RATIONALE_INSUFFICIENT",
        "SEMANTIC_SUPPRESSION_SCOPE_OVERBROAD",
        "SEMANTIC_SUPPRESSION_RISK_UNADDRESSED",
    }
)
_TARGET_ROOT_KEYS = frozenset({"weft"})
_DIAGNOSTICS_KEYS = frozenset(
    {"default_level", "fail_on", "suppressible_levels", "levels"}
)
_TABLE_KEY_NAMES: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "defaults": _DEFAULTS_KEYS,
        "profile": _PROFILE_KEYS,
        "check": _CHECK_KEYS,
        "packets": _PACKETS_KEYS,
        "coverage": _COVERAGE_KEYS,
        "analyze": _ANALYZE_KEYS,
        "verify": _VERIFY_KEYS,
        "obligations": _OBLIGATION_KEYS,
        "target_roots": _TARGET_ROOT_KEYS,
        "lint": _LINT_KEYS,
        "diagnostics": _DIAGNOSTICS_KEYS,
    }
)
_GENERIC_OPTION_LEAVES = frozenset(
    {
        "exclude",
        "extend_exclude",
        *{f"profile.{key}" for key in _PROFILE_KEYS},
        "lint.warn_unused_ignores",
        "lint.require_suppression_declarations",
        *{f"check.{key}" for key in _CHECK_KEYS},
        *{
            f"coverage.{key}"
            for key in _COVERAGE_KEYS
            if key not in {"exemptions", "floors"}
        },
        *{
            f"analyze.{key}"
            for key in _ANALYZE_KEYS
            if key
            not in (
                (_ANALYZE_CATALOG_DESCRIPTOR_KEYS - {"adapter_model_id"})
                | {"adapter_model_id", "models"}
            )
        },
        "verify.enabled",
        *{
            f"verify.{key}"
            for key in _VERIFY_KEYS
            if key not in {"enabled", "provider", "eval"}
        },
        *{f"verify.eval.{key}" for key in _VERIFY_EVAL_KEYS},
        *{f"obligations.{key}" for key in _OBLIGATION_KEYS},
        *{f"target_roots.{key}" for key in _TARGET_ROOT_KEYS},
        *{f"diagnostics.{key}" for key in _DIAGNOSTICS_KEYS},
    }
)
_GENERIC_OPTION_TABLE_PATHS = frozenset(
    {
        "profile",
        "lint",
        "check",
        "coverage",
        "analyze",
        "verify",
        "verify.provider",
        "verify.eval",
        "obligations",
        "target_roots",
        "diagnostics",
    }
)


@dataclass(frozen=True, slots=True)
class ProfileSettings:
    spec_roots: tuple[str, ...] | None = None
    plan_roots: tuple[str, ...] | None = None
    code_roots: tuple[str, ...] | None = None
    test_roots: tuple[str, ...] | None = None
    planned_spec_globs: tuple[str, ...] | None = None
    exploratory_spec_globs: tuple[str, ...] | None = None
    meta_spec_globs: tuple[str, ...] | None = None
    process_spec_globs: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class LintSettings:
    warn_unused_ignores: bool = True
    require_suppression_declarations: bool = False
    per_file_ignores: dict[str, tuple[str, ...]] = field(default_factory=dict)
    per_section_ignores: dict[str, tuple[str, ...]] = field(default_factory=dict)
    suppressions: tuple[SuppressionRule, ...] = ()


class ConfigLoadError(ValueError):
    """A configuration file failed to load or validate ([CFG-8]).

    The CLI maps this to exit 2: config problems are invocation problems,
    never target-repository findings.
    """


@dataclass(frozen=True, slots=True)
class _ConfigLayer:
    path: Path
    body: dict[str, Any]
    raw_sha256: str
    raw_bytes: bytes
    stat_identity: tuple[int, ...]


@dataclass(slots=True)
class _ConfigReadBudget:
    file_count: int = 0
    byte_count: int = 0


@dataclass(frozen=True, slots=True)
class _ConfigSource:
    raw: bytes
    stat_identity: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ConfigLayerIdentity:
    """Exact repository config bytes that produced resolved settings."""

    path: str
    raw_sha256: str
    raw_bytes: bytes = field(repr=False)
    stat_identity: tuple[int, ...] = field(repr=False)


@dataclass(frozen=True, slots=True)
class CheckSettings:
    format: str | None = None
    warnings_as_errors: bool | None = None
    output: str | None = None


@dataclass(frozen=True, slots=True)
class PacketsSettings:
    output: str | None = None


@dataclass(frozen=True, slots=True)
class CoverageExemption:
    """One reasoned repository-relative intent-coverage exemption ([COV-4])."""

    kind: Literal["path", "glob"]
    selector: str
    reason: str


@dataclass(frozen=True, slots=True)
class CoverageFloor:
    """One independent intent-coverage assertion below a code root ([COV-5])."""

    scope: str
    direct: float | None = None
    accounted: float | None = None


@dataclass(frozen=True, slots=True)
class CoverageSettings:
    """Closed intent-coverage settings and Git/history budgets ([COV-5])."""

    mode: Literal["report", "ratchet"] = "report"
    format: Literal["text", "json"] = "text"
    output: str | None = None
    granularity: Literal["definition"] = "definition"
    inherited_counts: bool = False
    ratchet_base: str = ""
    exemptions: tuple[CoverageExemption, ...] = ()
    floors: tuple[CoverageFloor, ...] = ()
    maximum_baseline_files: int = 20_000
    maximum_file_bytes: int = 5_000_000
    maximum_baseline_bytes: int = 100_000_000
    maximum_history_commits: int = 1_000
    maximum_git_command_seconds: float = 10.0
    maximum_git_commands: int = 64
    maximum_git_output_bytes: int = 100_000_000
    maximum_commit_message_bytes: int = 1_000_000
    maximum_runtime_seconds: float = 60.0


ConfigSourceKind = Literal[
    "packaged",
    "repository_candidate",
    "external_file",
    "environment",
    "cli",
]


@dataclass(frozen=True, slots=True)
class ConfigValueProvenance:
    """One effective ratchet-policy input contribution.

    ``repository_candidate`` is deliberately provisional: the Git baseline
    phase must still prove that the no-follow file is in the accepted snapshot
    and addressable at the merge base. This settings phase can reject external
    and invocation-owned inputs before any Git work starts.
    """

    key: str
    source: str
    source_kind: ConfigSourceKind


@dataclass(frozen=True, slots=True)
class SemanticDisposition:
    code: str
    packet_id: str
    packet_hash: str
    finding_hash: str
    status: str
    reason: str


@dataclass(frozen=True, slots=True)
class AnalyzeModelDescriptor:
    """One complete trusted analyzer model descriptor ([CFG-6.5])."""

    model: str
    adapter_model_id: str
    backend_id: str
    plugin_id: str
    plugin_distribution_name: str
    model_revision: str
    capability_schema_version: Literal[1]
    capability_revision: str
    request_constraints: RequestConstraints
    maximum_input_bytes: int
    input_cost_microusd_per_million_tokens: int
    output_cost_microusd_per_million_tokens: int
    input_token_overhead: int
    cost_rate_source: str


@dataclass(frozen=True, slots=True)
class AnalyzeSettings:
    backend_id: str = "llm"
    plugin_id: str = ""
    plugin_distribution_name: str = ""
    model: str = ""
    adapter_model_id: str = ""
    model_revision: str = ""
    capability_schema_version: Literal[1] = 1
    capability_revision: str = "packaged-compatible-v1"
    request_constraints: RequestConstraints = field(
        default_factory=lambda: RequestConstraints(
            json_mode=RequestFieldConstraint(
                "required", ("require", "off"), None, None
            ),
            temperature=RequestFieldConstraint("optional", (0.0,), None, None),
            seed=RequestFieldConstraint("optional", None, 0, 2**63 - 1),
            max_tokens=RequestFieldConstraint("required", None, 1, 2**31 - 1),
            reasoning_effort=RequestFieldConstraint("forbidden", None, None, None),
        )
    )
    maximum_input_bytes: int = 10_000_000
    concurrency: int = 1
    json_mode: str = "prefer"
    temperature: float | None = None
    seed: int | None = None
    max_tokens: int = 512
    reasoning_effort: ReasoningEffort | None = None
    cache_path: str = ".backstitch/semantic-cache"
    cache_mode: str = "off"
    result_reuse: str = "evidence-stable"
    search_epoch: str = "1"
    require_complete: bool = False
    required_kinds: tuple[str, ...] = ()
    minimum_packets: int = 0
    maximum_packets: int = 1000
    maximum_prompt_bytes: int = 10_000_000
    finding_handling: str = "report"
    maximum_provider_calls: int = 1000
    lock_wait_timeout_seconds: int = 300
    maximum_runtime_seconds: int = 1800
    maximum_estimated_cost_microusd: int = 0
    input_cost_microusd_per_million_tokens: int = 0
    output_cost_microusd_per_million_tokens: int = 0
    input_token_overhead: int = 256
    cost_rate_source: str = ""
    dispositions: tuple[SemanticDisposition, ...] = ()
    available_models: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DisabledVerifySettings:
    """The complete closed representation of disabled verification ([EVC-5])."""

    enabled: Literal[False] = False


@dataclass(frozen=True, slots=True)
class VerifyProviderSettings:
    backend_id: str
    plugin_id: str
    plugin_distribution_name: str
    model: str
    adapter_model_id: str
    model_revision: str
    capability_schema_version: Literal[1]
    capability_revision: str
    request_constraints: RequestConstraints
    maximum_input_bytes: int
    input_cost_microusd_per_million_tokens: int
    output_cost_microusd_per_million_tokens: int
    input_token_overhead: int
    cost_rate_source: str


@dataclass(frozen=True, slots=True)
class VerifyEvalSettings:
    mode: str
    qualification_corpus: str
    qualification_corpus_sha256: str
    qualification_report: str
    qualification_report_sha256: str
    trials: int
    interval_method: str
    confidence_level: float
    minimum_positive_units: int
    minimum_negative_units: int
    minimum_evidence_sufficiency_rate: float
    minimum_conditional_precision: float
    minimum_conditional_recall: float
    minimum_end_to_end_recall: float
    minimum_recall_lower_bound: float
    maximum_false_positive_rate: float
    maximum_false_positive_upper_bound: float
    maximum_indeterminate_rate: float
    maximum_uncached_flip_rate: float
    require_all_critical: bool


@dataclass(frozen=True, slots=True)
class VerifySettings:
    enabled: Literal[True]
    provider_source: str
    concurrency: int
    cache_path: str
    cache_mode: str
    search_epochs: tuple[str, ...]
    json_mode: str
    temperature: float | None
    seed: int | None
    max_tokens: int
    reasoning_effort: ReasoningEffort | None
    required_verdicts: int
    minimum_support_score: float
    indeterminate: str
    maximum_provider_calls: int
    maximum_prompt_bytes: int
    lock_wait_timeout_seconds: int
    maximum_runtime_seconds: int
    maximum_estimated_cost_microusd: int
    provider: VerifyProviderSettings | None
    eval: VerifyEvalSettings | None


@dataclass(frozen=True, slots=True)
class ObligationSettings:
    """Closed deterministic obligation/read-model limits ([EVC-8.3.1])."""

    section_required_roles: tuple[str, ...] = ("implementation",)
    page_size: int = 5
    maximum_page_size: int = 100
    maximum_response_bytes: int = 65_536
    maximum_candidate_items: int = 2_000
    maximum_catalog_items: int = 100_000
    maximum_lexical_seeds: int = 10
    maximum_snapshot_files: int = 20_000
    maximum_file_bytes: int = 5_000_000
    maximum_snapshot_bytes: int = 100_000_000
    maximum_work_units: int = 2_000_000
    maximum_packet_bytes: int = 10_000_000
    maximum_packet_report_bytes: int = 10_000_000
    maximum_call_seconds: float = 10.0
    snapshot_capture_attempts: int = 3
    static_neighbor_depth: int = 1


@dataclass(frozen=True, slots=True)
class PolicyRuleOrigin:
    """Source and zero-based within-source index for one effective rule."""

    source: str
    position: int


@dataclass(frozen=True, slots=True)
class TargetRootSettings:
    weft: str | None = None


@dataclass(frozen=True, slots=True)
class BackstitchSettings:
    profile: str | None = None
    allow_unknown_keys: bool = False
    default_command: Literal["check", "analyze"] | None = None
    exclude: tuple[str, ...] = DEFAULT_EXCLUDES
    profile_overrides: ProfileSettings = field(default_factory=ProfileSettings)
    lint: LintSettings = field(default_factory=LintSettings)
    check: CheckSettings = field(default_factory=CheckSettings)
    packets: PacketsSettings = field(default_factory=PacketsSettings)
    coverage: CoverageSettings = field(default_factory=CoverageSettings)
    analyze: AnalyzeSettings = field(default_factory=AnalyzeSettings)
    verify: DisabledVerifySettings | VerifySettings = field(
        default_factory=DisabledVerifySettings
    )
    obligations: ObligationSettings = field(default_factory=ObligationSettings)
    target_roots: TargetRootSettings = field(default_factory=TargetRootSettings)
    diagnostics: DiagnosticsSettings = field(default_factory=default_policy)
    config_path: Path | None = None
    config_dir: Path | None = None
    config_layers: tuple[str, ...] = (PACKAGED_DEFAULTS_LAYER,)
    config_layer_identities: tuple[ConfigLayerIdentity, ...] = ()
    policy_rule_origins: tuple[PolicyRuleOrigin, ...] = ()
    ratchet_policy_provenance: tuple[ConfigValueProvenance, ...] = ()
    analyze_model_source: str = "llm default model"


def discover_config_path(
    anchor: Path,
    *,
    home: Path | None = None,
    explicit: Path | None = None,
) -> Path | None:
    return _discover_config_path(
        anchor,
        home=home,
        explicit=explicit,
        budget=_ConfigReadBudget(),
        preloaded={},
    )


def _discover_config_path(
    anchor: Path,
    *,
    home: Path | None,
    explicit: Path | None,
    budget: _ConfigReadBudget,
    preloaded: dict[Path, _ConfigSource],
) -> Path | None:
    if explicit is not None:
        path = _canonical_config_address(explicit.expanduser())
        _require_regular_config(path, missing_message=f"Config file not found: {path}")
        return path

    resolved_home = (home or Path.home()).resolve()
    current = anchor.resolve()
    while True:
        backstitch_toml = current / ".backstitch.toml"
        if _config_path_exists(backstitch_toml):
            _require_regular_config(backstitch_toml)
            return backstitch_toml
        pyproject = current / "pyproject.toml"
        if _config_path_exists(pyproject):
            _require_regular_config(pyproject)
            source = _read_config_source(pyproject, budget)
            if _pyproject_has_backstitch(pyproject, source.raw):
                preloaded[pyproject] = source
                return pyproject
        if current == resolved_home:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def _canonical_config_address(path: Path) -> Path:
    """Canonicalize parent components without ever following the config leaf."""

    absolute = path if path.is_absolute() else Path.cwd() / path
    return absolute.parent.resolve() / absolute.name


def _config_path_exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise ConfigLoadError(f"could not inspect config {path}: {exc}") from exc
    return True


def _require_regular_config(path: Path, *, missing_message: str | None = None) -> None:
    try:
        value = path.lstat()
    except FileNotFoundError:
        raise ConfigLoadError(
            missing_message or f"Config file not found: {path}"
        ) from None
    except OSError as exc:
        raise ConfigLoadError(f"could not inspect config {path}: {exc}") from exc
    if not stat.S_ISREG(value.st_mode):
        raise ConfigLoadError(f"config is not a regular file: {path}")


def _scope_invocation_environment(
    *,
    invocation_command: str | None | object,
    default_command: Literal["check", "analyze"] | None,
    environment: Mapping[str, str],
) -> tuple[str | None, Mapping[str, str]]:
    if invocation_command is _INVOCATION_COMMAND_UNSET:
        return None, environment
    if invocation_command is not None and (
        not isinstance(invocation_command, str)
        or invocation_command not in CONFIG_CONSUMING_COMMANDS
    ):
        raise ConfigLoadError(
            f"unknown config-consuming invocation command: {invocation_command!r}"
        )
    selected_command = (
        default_command if invocation_command is None else invocation_command
    )
    scoped = {
        key: value
        for key, value in environment.items()
        if key == "BACKSTITCH_WEFT_ROOT"
        or (key == "LLM_MODEL" and selected_command in _MODEL_ENVIRONMENT_COMMANDS)
    }
    return selected_command, scoped


def _resolve_cli_overrides(
    cli_overrides: Mapping[str, Any] | None,
    cli_overrides_by_command: Mapping[str, Mapping[str, Any]] | None,
    *,
    invocation_command: str | None | object,
    selected_command: str | None,
) -> dict[str, Any]:
    effective = dict(cli_overrides or {})
    if cli_overrides_by_command is None:
        return effective
    unknown_commands = sorted(set(cli_overrides_by_command) - {"check", "analyze"})
    if unknown_commands:
        raise ConfigLoadError(
            f"unknown deferred default command override owner: {unknown_commands[0]!r}"
        )
    if invocation_command is not None:
        raise ConfigLoadError(
            "deferred default command overrides require a bare invocation"
        )
    if selected_command is not None:
        effective.update(cli_overrides_by_command.get(selected_command, {}))
    return effective


def _validate_final_test_roots(repo_root: Path, settings: BackstitchSettings) -> None:
    invalid = uncontained_test_root(
        repo_root,
        settings.profile_overrides.code_roots or (),
        settings.profile_overrides.test_roots or (),
    )
    if invalid is not None:
        raise ConfigLoadError(
            f"test root {invalid!r} must be equal to or nested under a"
            " final effective code root"
        )


def _merged_repository_raw(
    repository_layers: tuple[tuple[_ConfigLayer, ConfigSourceKind], ...],
    *,
    config_path: Path,
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for layer, _source_kind in repository_layers:
        merged = _merge_config_layers(merged, layer.body, file_layer=True)
    merged.pop("extend", None)
    _validate_config_layers(
        merged,
        tuple(layer for layer, _source_kind in repository_layers),
        config_path,
    )
    return merged


def _analyze_model_source_after_overlays(
    configured_source: str,
    *,
    environment_overlay: dict[str, Any],
    cli_options: Sequence[tuple[str, str]],
    cli_overrides: Mapping[str, Any],
) -> str:
    source = configured_source
    if _nested_value(environment_overlay, "analyze", "model") is not None:
        source = "LLM_MODEL environment variable"
    if any(key == "analyze.model" for key, _value in cli_options):
        source = "--option analyze.model"
    if "analyze.model" in cli_overrides:
        source = "--model"
    return source


def _assemble_settings(
    repo_root: Path,
    *,
    config_path: Path | None,
    repository_layers: tuple[tuple[_ConfigLayer, ConfigSourceKind], ...],
    environment: Mapping[str, str],
    cli_options: Sequence[tuple[str, str]] = (),
    cli_overrides: Mapping[str, Any] | None = None,
    cli_overrides_by_command: Mapping[str, Mapping[str, Any]] | None = None,
    invocation_command: str | None | object = _INVOCATION_COMMAND_UNSET,
    resolve_symlinks: bool = True,
) -> BackstitchSettings:
    """Merge, project provenance, parse, and validate every config source."""

    raw = copy.deepcopy(load_default_config_raw())
    _expand_raw_paths(
        raw,
        PACKAGED_DEFAULTS_PATH.parent,
        resolve_symlinks=resolve_symlinks,
    )
    packaged_raw = copy.deepcopy(raw)
    provenance_layers: list[tuple[dict[str, Any], str, ConfigSourceKind]] = [
        (copy.deepcopy(packaged_raw), PACKAGED_DEFAULTS_LAYER, "packaged")
    ]
    layers = [PACKAGED_DEFAULTS_LAYER]
    policy_origins = [
        PolicyRuleOrigin(source=PACKAGED_DEFAULTS_LAYER, position=index)
        for index in range(len(_raw_policy_rules(packaged_raw)))
    ]
    suppression_rule_source = PACKAGED_DEFAULTS_LAYER
    config_layer_identities: list[ConfigLayerIdentity] = []
    explicit_analyze_keys: set[str] = set()
    analyze_model_source = "llm default model"

    if repository_layers:
        assert config_path is not None
        repo_raw = _merged_repository_raw(
            repository_layers,
            config_path=config_path,
        )
        raw = _merge_config_layers(raw, repo_raw, file_layer=True)
        for layer, source_kind in repository_layers:
            source = str(layer.path)
            provenance_layers.append((copy.deepcopy(layer.body), source, source_kind))
            layers.append(source)
            config_layer_identities.append(
                ConfigLayerIdentity(
                    path=source,
                    raw_sha256=layer.raw_sha256,
                    raw_bytes=layer.raw_bytes,
                    stat_identity=layer.stat_identity,
                )
            )
            analyze = layer.body.get("analyze")
            if isinstance(analyze, dict):
                explicit_analyze_keys.update(analyze)
                if "model" in analyze:
                    analyze_model_source = "config [analyze].model"
            policy_origins.extend(
                PolicyRuleOrigin(source=source, position=index)
                for index in range(len(_raw_policy_rules(layer.body)))
            )
            lint_layer = layer.body.get("lint")
            if isinstance(lint_layer, dict) and "suppressions" in lint_layer:
                suppression_rule_source = source

    source_path = config_path or PACKAGED_DEFAULTS_PATH
    default_command = _parse_default_command(raw, source_path=source_path)
    selected_command, scoped_environment = _scope_invocation_environment(
        invocation_command=invocation_command,
        default_command=default_command,
        environment=environment,
    )
    effective_cli_overrides = _resolve_cli_overrides(
        cli_overrides,
        cli_overrides_by_command,
        invocation_command=invocation_command,
        selected_command=selected_command,
    )

    environment_overlay = _environment_config_overlay(scoped_environment)
    cli_overlay = _cli_config_overlay(
        cli_options,
        cli_overrides=effective_cli_overrides,
    )
    analyze_model_source = _analyze_model_source_after_overlays(
        analyze_model_source,
        environment_overlay=environment_overlay,
        cli_options=cli_options,
        cli_overrides=effective_cli_overrides,
    )
    configured_model = _nested_value(raw, "analyze", "model")
    for overlay, source in (
        (environment_overlay, "environment"),
        (cli_overlay, "cli"),
    ):
        if overlay:
            _expand_raw_paths(
                overlay,
                Path.cwd(),
                resolve_symlinks=resolve_symlinks,
            )
            provenance_layers.append(
                (
                    copy.deepcopy(overlay),
                    source,
                    cast(ConfigSourceKind, source),
                )
            )
        _validate_overlay_traversal(raw, overlay)
        raw = _merge_config_layers(raw, overlay)
        analyze = overlay.get("analyze")
        if isinstance(analyze, dict):
            explicit_analyze_keys.update(analyze)
        policy_origins.extend(
            PolicyRuleOrigin(source=source, position=index)
            for index in range(len(_raw_policy_rules(overlay)))
        )

    available_models, selected_catalog_descriptor = _select_analyze_model_descriptor(
        raw,
        configured_model=configured_model,
    )
    if selected_catalog_descriptor:
        explicit_analyze_keys.update(_ANALYZE_REQUIRED_FLAT_DESCRIPTOR_KEYS)
    settings = _parse_settings(
        raw,
        source_path=source_path,
        effective_config_path=config_path,
        config_layers=tuple(layers),
        config_layer_identities=tuple(config_layer_identities),
        policy_rule_origins=tuple(policy_origins),
        suppression_rule_source=suppression_rule_source,
        analyze_model_source=analyze_model_source,
        explicit_analyze_keys=frozenset(explicit_analyze_keys),
        validate_unknown_keys=config_path is None,
        default_command=default_command,
        available_models=available_models,
        ratchet_policy_provenance=_ratchet_policy_provenance(provenance_layers),
        resolve_symlinks=resolve_symlinks,
    )
    _validate_final_test_roots(repo_root, settings)
    return settings


def resolve_config(
    anchor: Path,
    *,
    home: Path | None = None,
    explicit: Path | None = None,
    use_repo_config: bool = True,
    environment: Mapping[str, str] | None = None,
    cli_options: Sequence[tuple[str, str]] = (),
    cli_overrides: Mapping[str, Any] | None = None,
    cli_overrides_by_command: Mapping[str, Mapping[str, Any]] | None = None,
    invocation_command: str | None | object = _INVOCATION_COMMAND_UNSET,
) -> BackstitchSettings:
    """Resolve one immutable invocation-scoped settings snapshot ([CFG-5.1])."""

    resolved_anchor = anchor.resolve()
    config_path: Path | None = None
    repository_layers: tuple[tuple[_ConfigLayer, ConfigSourceKind], ...] = ()
    if use_repo_config:
        budget = _ConfigReadBudget()
        preloaded: dict[Path, _ConfigSource] = {}
        config_path = _discover_config_path(
            anchor,
            home=home,
            explicit=explicit,
            budget=budget,
            preloaded=preloaded,
        )
        if config_path is not None:
            warnings, loaded_layers = _load_config_chain(
                config_path,
                set(),
                budget,
                preloaded,
            )
            for warning in warnings:
                print(f"warning: {warning}", file=sys.stderr)
            repository_layers = tuple(
                (
                    layer,
                    "repository_candidate"
                    if _path_is_within(layer.path, resolved_anchor)
                    else "external_file",
                )
                for layer in loaded_layers
            )

    settings = _assemble_settings(
        resolved_anchor,
        config_path=config_path,
        repository_layers=repository_layers,
        environment=os.environ if environment is None else environment,
        cli_options=cli_options,
        cli_overrides=cli_overrides,
        cli_overrides_by_command=cli_overrides_by_command,
        invocation_command=invocation_command,
    )
    if invocation_command == "coverage" and settings.coverage.mode == "ratchet":
        _validate_ratchet_invocation_sources(
            settings,
            root=resolved_anchor,
            explicit=explicit,
            use_repo_config=use_repo_config,
            cli_options=cli_options,
            cli_overrides=dict(cli_overrides or {}),
        )
    return settings


def _load_blob_config_chain(
    path: str,
    *,
    root: Path,
    blobs: Mapping[str, bytes],
    seen: set[str],
    budget: _ConfigReadBudget,
) -> tuple[_ConfigLayer, ...]:
    if path in seen:
        raise ConfigLoadError(f"Circular extend chain detected at {path}")
    seen.add(path)
    raw = blobs.get(path)
    if raw is None:
        raise ConfigLoadError(f"historical config layer is missing: {path}")
    budget.file_count += 1
    budget.byte_count += len(raw)
    if budget.file_count > MAXIMUM_CONFIG_CHAIN_FILES:
        raise ConfigLoadError(
            f"config extend chain exceeds {MAXIMUM_CONFIG_CHAIN_FILES} config files"
        )
    if len(raw) > MAXIMUM_CONFIG_FILE_BYTES:
        raise ConfigLoadError(f"config file exceeds 1,000,000 raw bytes: {path}")
    if budget.byte_count > MAXIMUM_CONFIG_CHAIN_BYTES:
        raise ConfigLoadError("config extend chain exceeds 5,000,000 raw bytes")
    display_path = root / PurePosixPath(path)
    body = _extract_config_body(display_path, raw)
    layer = _ConfigLayer(
        path=display_path,
        body=copy.deepcopy(body),
        raw_sha256=hashlib.sha256(raw).hexdigest(),
        raw_bytes=raw,
        stat_identity=(0, 0, 0, len(raw), 0, 0),
    )
    _expand_raw_paths(body, display_path.parent, resolve_symlinks=False)
    extend = body.get("extend")
    if extend is None:
        return (layer,)
    if not isinstance(extend, str) or not extend.strip():
        raise ConfigLoadError(f"Invalid extend value in {path}")
    expanded = Path(_expand_user_and_env(extend.strip()))
    if expanded.is_absolute():
        raise ConfigLoadError(
            "historical config extend must remain inside the repository"
        )
    candidate = (PurePosixPath(path).parent / expanded.as_posix()).as_posix()
    normalized = canonical_repository_path(candidate)
    if normalized is None or normalized.canonical != candidate:
        raise ConfigLoadError("historical config extend path is unsafe")
    return (
        *_load_blob_config_chain(
            candidate,
            root=root,
            blobs=blobs,
            seen=seen,
            budget=budget,
        ),
        layer,
    )


def resolve_repository_config_from_blobs(
    repo_root: Path,
    config_path: str,
    blobs: Mapping[str, bytes],
) -> BackstitchSettings:
    """Resolve one repository-owned config chain from immutable Git blobs.

    This is the ratchet-side counterpart to :func:`resolve_config`: it never
    discovers or reads a filesystem path and admits only relative config
    layers present in the supplied object-database snapshot.
    """

    if not repo_root.is_absolute():
        raise ConfigLoadError("historical repository root must be absolute")
    root = lexical_absolute_path(repo_root, base_dir=repo_root)
    canonical = canonical_repository_path(config_path)
    if canonical is None or canonical.canonical != config_path:
        raise ConfigLoadError("historical config path is not repository-relative")
    repo_layers = _load_blob_config_chain(
        config_path,
        root=root,
        blobs=blobs,
        seen=set(),
        budget=_ConfigReadBudget(),
    )
    effective_path = root / PurePosixPath(config_path)
    return _assemble_settings(
        root,
        config_path=effective_path,
        repository_layers=tuple(
            (layer, "repository_candidate") for layer in repo_layers
        ),
        environment={},
        resolve_symlinks=False,
    )


def _environment_config_overlay(environment: Mapping[str, str]) -> dict[str, Any]:
    overlay: dict[str, Any] = {}
    model = environment.get("LLM_MODEL", "").strip()
    if model:
        _set_option_value(overlay, "analyze.model", model)
    weft_root = environment.get("BACKSTITCH_WEFT_ROOT", "").strip()
    if weft_root:
        _set_option_value(overlay, "target_roots.weft", weft_root)
    return overlay


def _cli_config_overlay(
    options: Sequence[tuple[str, str]],
    *,
    cli_overrides: Mapping[str, Any],
) -> dict[str, Any]:
    overlay: dict[str, Any] = {}
    generic_keys: set[str] = set()
    for key, raw_value in options:
        _validate_option_key(key)
        if key in generic_keys:
            raise ConfigLoadError(f"--option repeats key {key!r}")
        generic_keys.add(key)
        _set_option_value(overlay, key, _parse_option_value(raw_value))

    for key, value in cli_overrides.items():
        _validate_option_key(key)
        if key in generic_keys:
            raise ConfigLoadError(
                f"--option {key!r} conflicts with its dedicated CLI flag"
            )
        _set_option_value(overlay, key, value)
    return overlay


def _validate_option_key(key: str) -> None:
    if not key or any(not segment for segment in key.split(".")):
        raise ConfigLoadError(f"invalid --option key {key!r}")
    if any(character in key for character in "\"'\\"):
        raise ConfigLoadError(f"invalid --option key {key!r}")
    if key not in _GENERIC_OPTION_LEAVES:
        raise ConfigLoadError(
            f"--option key {key!r} is unknown, non-leaf, or not runtime-overridable"
        )


def _parse_option_value(value: str) -> Any:
    has_forbidden_character = any(character in value for character in "\x00\r\n")
    try:
        parsed = tomllib.loads(f"value = {value}")
    except tomllib.TOMLDecodeError:
        if has_forbidden_character:
            raise ConfigLoadError(
                "--option VALUE may not contain NUL, CR, or LF"
            ) from None
        return value
    if set(parsed) != {"value"}:
        raise ConfigLoadError("--option VALUE must be exactly one TOML assignment")
    if has_forbidden_character:
        raise ConfigLoadError("--option VALUE may not contain NUL, CR, or LF")
    return parsed["value"]


def _set_option_value(overlay: dict[str, Any], key: str, value: Any) -> None:
    cursor = overlay
    segments = key.split(".")
    for segment in segments[:-1]:
        child = cursor.setdefault(segment, {})
        if not isinstance(child, dict):
            raise ConfigLoadError(f"--option key {key!r} crosses a non-leaf value")
        cursor = child
    cursor[segments[-1]] = value


def _validate_overlay_traversal(
    base: dict[str, Any],
    overlay: dict[str, Any],
    *,
    path: tuple[str, ...] = (),
) -> None:
    """Do not let a later dict overlay hide an invalid configured table."""

    for key, value in overlay.items():
        existing = base.get(key)
        current_path = (*path, key)
        if (
            isinstance(value, dict)
            and ".".join(current_path) in _GENERIC_OPTION_TABLE_PATHS
            and existing is not None
        ):
            if not isinstance(existing, dict):
                raise ConfigLoadError(f"[{'.'.join(current_path)}] must be a table")
            _validate_overlay_traversal(
                existing,
                value,
                path=current_path,
            )


def _nested_value(raw: dict[str, Any], *segments: str) -> Any:
    value: Any = raw
    for segment in segments:
        if not isinstance(value, dict) or segment not in value:
            return None
        value = value[segment]
    return value


def _analyze_alias_owners(
    catalog: Mapping[str, AnalyzeModelDescriptor],
    *,
    flat_model: str,
    flat_adapter_model_id: str,
) -> dict[str, list[str]]:
    owners: dict[str, list[str]] = {}
    if flat_model.strip():
        owners.setdefault(flat_adapter_model_id, []).append(flat_model)
    for selector, descriptor in catalog.items():
        owners.setdefault(descriptor.adapter_model_id, []).append(selector)
    return owners


def _apply_analyze_model_descriptor(
    analyze: dict[str, Any], descriptor: AnalyzeModelDescriptor
) -> None:
    analyze.update(
        {
            "backend_id": descriptor.backend_id,
            "plugin_id": descriptor.plugin_id,
            "plugin_distribution_name": descriptor.plugin_distribution_name,
            "model": descriptor.model,
            "adapter_model_id": descriptor.adapter_model_id,
            "model_revision": descriptor.model_revision,
            "capability_schema_version": descriptor.capability_schema_version,
            "capability_revision": descriptor.capability_revision,
            "request_constraints": asdict(descriptor.request_constraints),
            "maximum_input_bytes": descriptor.maximum_input_bytes,
            "input_cost_microusd_per_million_tokens": (
                descriptor.input_cost_microusd_per_million_tokens
            ),
            "output_cost_microusd_per_million_tokens": (
                descriptor.output_cost_microusd_per_million_tokens
            ),
            "input_token_overhead": descriptor.input_token_overhead,
            "cost_rate_source": descriptor.cost_rate_source,
        }
    )


def _select_analyze_model_descriptor(
    raw: dict[str, Any],
    *,
    configured_model: Any,
) -> tuple[tuple[str, ...], bool]:
    """Select one complete file-owned descriptor after model precedence."""

    analyze = _expect_table(raw.get("analyze"), "analyze")
    effective_model = _require_string(analyze, "model", "analyze")
    catalog = _parse_analyze_model_catalog(analyze.get("models"))

    flat_model = configured_model if isinstance(configured_model, str) else ""
    if flat_model and flat_model in catalog:
        raise ConfigLoadError(
            f"analyze model {flat_model!r} must have exactly one descriptor owner"
        )
    available_models = tuple(
        sorted({*(catalog.keys()), *([flat_model] if flat_model.strip() else [])})
    )

    flat_adapter_model_id = analyze.get("adapter_model_id")
    if flat_adapter_model_id is None or flat_adapter_model_id == "":
        flat_adapter_model_id = flat_model
    if not isinstance(flat_adapter_model_id, str):
        raise ConfigLoadError("analyze.adapter_model_id must be a string")

    alias_owners = _analyze_alias_owners(
        catalog,
        flat_model=flat_model,
        flat_adapter_model_id=flat_adapter_model_id,
    )
    ambiguous_aliases = sorted(
        alias for alias, owners in alias_owners.items() if len(owners) > 1
    )
    if ambiguous_aliases:
        raise ConfigLoadError(
            f"ambiguous analyze adapter_model_id alias: {ambiguous_aliases[0]!r}"
        )

    selected_model = effective_model
    if effective_model not in catalog and effective_model != flat_model:
        alias_owner = alias_owners.get(effective_model)
        if alias_owner is not None:
            selected_model = alias_owner[0]

    if selected_model in catalog:
        descriptor = catalog[selected_model]
        _apply_analyze_model_descriptor(analyze, descriptor)
        return available_models, True

    if flat_model.strip() and selected_model == flat_model:
        analyze["model"] = flat_model
        analyze["adapter_model_id"] = flat_adapter_model_id
        return available_models, False
    if flat_model.strip():
        raise ConfigLoadError(
            f"model {effective_model!r} has no trusted analyze model descriptor"
        )
    analyze["adapter_model_id"] = effective_model
    return available_models, False


def _canonical_purl_component(
    value: str,
    *,
    field_name: str,
    safe: str,
    selector_label: str,
) -> str:
    if re.search(r"%(?![0-9A-Fa-f]{2})", value):
        raise ConfigLoadError(
            f"{selector_label} has invalid percent encoding in {field_name}"
        )
    try:
        decoded = unquote_to_bytes(value).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigLoadError(
            f"{selector_label} has invalid UTF-8 in {field_name}"
        ) from exc
    if not decoded or any(ord(character) < 0x20 for character in decoded):
        raise ConfigLoadError(f"{selector_label} has invalid {field_name}")
    canonical = quote(decoded, safe=safe, encoding="utf-8", errors="strict")
    if canonical != value:
        raise ConfigLoadError(f"{selector_label} must be a canonical pkg:service PURL")
    return decoded


def _validate_dns_order_service_namespace(
    namespace: str,
    *,
    selector_label: str,
) -> None:
    for domain in namespace.split(":"):
        labels = domain.split(".")
        if (
            len(labels) < 2
            or any(not _DNS_LABEL_RE.fullmatch(label) for label in labels)
            or (labels[0] in _COMMON_DNS_TLDS and labels[-1] not in _COMMON_DNS_TLDS)
        ):
            raise ConfigLoadError(
                f"{selector_label} pkg:service namespace must be DNS-order"
            )


def _validate_canonical_service_purl(
    selector: str,
    *,
    selector_label: str = "analyze model selector",
) -> None:
    match = _SERVICE_PURL_RE.fullmatch(selector)
    if match is None:
        raise ConfigLoadError(f"{selector_label} must be a canonical pkg:service PURL")
    namespace = match.group("namespace")
    _validate_dns_order_service_namespace(
        namespace,
        selector_label=selector_label,
    )
    name = _canonical_purl_component(
        match.group("name"),
        field_name="service name",
        safe=":._-~",
        selector_label=selector_label,
    )
    if name in {".", ".."}:
        raise ConfigLoadError(f"{selector_label} must contain a stable service name")
    version = match.group("version")
    if version is not None:
        _canonical_purl_component(
            version,
            field_name="version",
            safe="/:._-~",
            selector_label=selector_label,
        )
    qualifiers = match.group("qualifiers")
    if qualifiers is None:
        return
    parsed_qualifiers: list[tuple[str, str]] = []
    seen: set[str] = set()
    for assignment in qualifiers.split("&"):
        key, separator, raw_value = assignment.partition("=")
        if not separator or not _SERVICE_QUALIFIER_KEY_RE.fullmatch(key) or key in seen:
            raise ConfigLoadError(
                f"{selector_label} has invalid pkg:service qualifiers"
            )
        if key in _SERVICE_PRIVATE_ONLY_QUALIFIERS:
            raise ConfigLoadError(
                f"{selector_label} pkg:service forbids qualifier {key}"
            )
        _canonical_purl_component(
            raw_value,
            field_name=f"qualifier {key}",
            safe="/:._-~",
            selector_label=selector_label,
        )
        seen.add(key)
        parsed_qualifiers.append((key, raw_value))
    canonical = "&".join(f"{key}={value}" for key, value in sorted(parsed_qualifiers))
    if canonical != qualifiers:
        raise ConfigLoadError(f"{selector_label} must be a canonical pkg:service PURL")


def _parse_analyze_model_catalog(
    value: Any,
) -> dict[str, AnalyzeModelDescriptor]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigLoadError("analyze.models must be a table")

    catalog: dict[str, AnalyzeModelDescriptor] = {}
    for selector, raw_descriptor in value.items():
        if not isinstance(selector, str):
            raise ConfigLoadError(
                "analyze model selector must be a canonical pkg:service PURL"
            )
        _validate_canonical_service_purl(selector)
        if not isinstance(raw_descriptor, dict):
            raise ConfigLoadError(
                f"analyze.models.{selector} must be a complete descriptor table"
            )
        supplied = set(raw_descriptor)
        missing = sorted(_ANALYZE_CATALOG_DESCRIPTOR_KEYS - supplied)
        unknown = sorted(supplied - _ANALYZE_CATALOG_DESCRIPTOR_KEYS)
        if missing:
            raise ConfigLoadError(
                f"analyze.models.{selector} must be a complete descriptor; "
                f"missing: {', '.join(missing)}"
            )
        if unknown:
            raise ConfigLoadError(
                f"unknown analyze.models.{selector} descriptor field: {unknown[0]}"
            )

        identity_values = {
            key: _require_string(
                raw_descriptor,
                key,
                f"analyze.models.{selector}",
            )
            for key in (
                "backend_id",
                "plugin_id",
                "plugin_distribution_name",
                "model_revision",
                "cost_rate_source",
                "adapter_model_id",
            )
        }
        blank = [key for key, item in identity_values.items() if not item.strip()]
        if blank:
            raise ConfigLoadError(
                f"analyze.models.{selector}.{blank[0]} must be nonblank"
            )
        catalog[selector] = AnalyzeModelDescriptor(
            model=selector,
            adapter_model_id=identity_values["adapter_model_id"],
            backend_id=identity_values["backend_id"],
            plugin_id=identity_values["plugin_id"],
            plugin_distribution_name=identity_values["plugin_distribution_name"],
            model_revision=identity_values["model_revision"],
            capability_schema_version=_parse_capability_schema_version(
                raw_descriptor,
                f"analyze.models.{selector}",
            ),
            capability_revision=_parse_capability_revision(
                raw_descriptor,
                f"analyze.models.{selector}",
            ),
            request_constraints=_parse_request_constraints(
                raw_descriptor.get("request_constraints"),
                f"analyze.models.{selector}.request_constraints",
                authored=True,
            ),
            maximum_input_bytes=_require_int(
                raw_descriptor,
                "maximum_input_bytes",
                f"analyze.models.{selector}",
                minimum=1,
            ),
            input_cost_microusd_per_million_tokens=_require_int(
                raw_descriptor,
                "input_cost_microusd_per_million_tokens",
                f"analyze.models.{selector}",
                minimum=0,
            ),
            output_cost_microusd_per_million_tokens=_require_int(
                raw_descriptor,
                "output_cost_microusd_per_million_tokens",
                f"analyze.models.{selector}",
                minimum=0,
            ),
            input_token_overhead=_require_int(
                raw_descriptor,
                "input_token_overhead",
                f"analyze.models.{selector}",
                minimum=0,
            ),
            cost_rate_source=identity_values["cost_rate_source"],
        )
    return catalog


def _parse_capability_schema_version(
    table: dict[str, Any],
    label: str,
) -> Literal[1]:
    value = _require_int(table, "capability_schema_version", label, minimum=1)
    if value != 1:
        raise ConfigLoadError(f"{label}.capability_schema_version must equal 1")
    return 1


def _parse_capability_revision(table: dict[str, Any], label: str) -> str:
    value = _require_string(table, "capability_revision", label)
    if not value.strip():
        raise ConfigLoadError(f"{label}.capability_revision must be nonblank")
    return value


def _request_constraint_keys_are_valid(
    raw: dict[str, Any],
    *,
    authored_keys: set[str],
    authored: bool,
) -> bool:
    normalized_keys = {"presence", "allowed_values", "minimum", "maximum"}
    supplied_keys = frozenset(raw)
    if authored:
        return supplied_keys == authored_keys
    if supplied_keys not in {frozenset(authored_keys), frozenset(normalized_keys)}:
        return False
    if supplied_keys != normalized_keys:
        return True
    unused_keys = normalized_keys - authored_keys
    return all(raw.get(key) is None for key in unused_keys)


def _parse_allowed_request_values(
    field_name: str,
    allowed_raw: Any,
    *,
    field_label: str,
    authored: bool,
) -> tuple[object, ...]:
    allowed_collection_types = (list,) if authored else (list, tuple)
    if not isinstance(allowed_raw, allowed_collection_types) or not allowed_raw:
        raise ConfigLoadError(f"{field_label}.allowed_values must be a nonempty array")
    if field_name == "json_mode":
        if any(item not in {"require", "off"} for item in allowed_raw):
            raise ConfigLoadError(
                f"{field_label}.allowed_values may contain require and off"
            )
    elif field_name == "reasoning_effort":
        if any(
            not isinstance(item, str) or item not in REASONING_EFFORT_VALUES
            for item in allowed_raw
        ):
            raise ConfigLoadError(
                f"{field_label}.allowed_values may contain none, minimal, low, "
                "medium, high, xhigh, and max"
            )
    elif any(
        isinstance(item, bool)
        or not isinstance(item, (int, float))
        or not math.isfinite(float(item))
        or not 0 <= float(item) <= 2
        for item in allowed_raw
    ):
        raise ConfigLoadError(
            f"{field_label}.allowed_values must contain finite numbers from 0 through 2"
        )
    if any(
        item == earlier
        for index, item in enumerate(allowed_raw)
        for earlier in allowed_raw[:index]
    ):
        raise ConfigLoadError(
            f"{field_label}.allowed_values must not contain duplicates"
        )
    return tuple(allowed_raw)


def _parse_request_integer_bounds(
    field_name: str,
    minimum: Any,
    maximum: Any,
    *,
    field_label: str,
) -> tuple[int, int]:
    if (
        isinstance(minimum, bool)
        or isinstance(maximum, bool)
        or not isinstance(minimum, int)
        or not isinstance(maximum, int)
        or minimum > maximum
        or (field_name == "seed" and minimum < 0)
        or (field_name == "max_tokens" and minimum < 1)
    ):
        raise ConfigLoadError(f"{field_label} has invalid integer bounds")
    return minimum, maximum


def _parse_request_field_constraint(
    field_name: str,
    raw: Any,
    *,
    label: str,
    authored: bool,
) -> RequestFieldConstraint:
    field_label = f"{label}.{field_name}"
    if not isinstance(raw, dict):
        raise ConfigLoadError(f"{field_label} must be a table")
    unknown = sorted(set(raw) - {"presence", "allowed_values", "minimum", "maximum"})
    if unknown:
        raise ConfigLoadError(f"{field_label} has unknown field: {unknown[0]}")
    presence = raw.get("presence")
    if presence not in {"required", "optional", "forbidden"}:
        raise ConfigLoadError(
            f"{field_label}.presence must be required, optional, or forbidden"
        )
    allowed_raw = raw.get("allowed_values")
    minimum = raw.get("minimum")
    maximum = raw.get("maximum")
    if presence == "forbidden":
        if not _request_constraint_keys_are_valid(
            raw,
            authored_keys={"presence"},
            authored=authored,
        ):
            raise ConfigLoadError(
                f"{field_label} forbidden form contains only presence"
            )
        allowed: tuple[object, ...] | None = None
    elif field_name in {"json_mode", "temperature", "reasoning_effort"}:
        if not _request_constraint_keys_are_valid(
            raw,
            authored_keys={"presence", "allowed_values"},
            authored=authored,
        ):
            raise ConfigLoadError(
                f"{field_label} must contain presence and allowed_values"
            )
        allowed = _parse_allowed_request_values(
            field_name,
            allowed_raw,
            field_label=field_label,
            authored=authored,
        )
        minimum = maximum = None
    else:
        if not _request_constraint_keys_are_valid(
            raw,
            authored_keys={"presence", "minimum", "maximum"},
            authored=authored,
        ):
            raise ConfigLoadError(
                f"{field_label} must contain presence, minimum, and maximum"
            )
        minimum, maximum = _parse_request_integer_bounds(
            field_name,
            minimum,
            maximum,
            field_label=field_label,
        )
        allowed = None
    try:
        return RequestFieldConstraint(
            cast(Any, presence),
            allowed,
            cast(int | float | None, minimum),
            cast(int | float | None, maximum),
        )
    except ValueError as exc:
        raise ConfigLoadError(f"{field_label}: {exc}") from None


def _parse_request_constraints(
    value: Any,
    label: str,
    *,
    authored: bool = False,
) -> RequestConstraints:
    """Parse concise TOML rules into SEM-3's exact null-bearing records."""

    if not isinstance(value, dict):
        raise ConfigLoadError(f"{label} must be a table")
    field_names = (
        "json_mode",
        "temperature",
        "seed",
        "max_tokens",
        "reasoning_effort",
    )
    if set(value) != set(field_names):
        missing = sorted(set(field_names) - set(value))
        unknown = sorted(set(value) - set(field_names))
        detail = (
            f"missing: {', '.join(missing)}"
            if missing
            else f"unknown: {', '.join(unknown)}"
        )
        raise ConfigLoadError(f"{label} must contain exactly five fields; {detail}")

    parsed = {
        field_name: _parse_request_field_constraint(
            field_name,
            value[field_name],
            label=label,
            authored=authored,
        )
        for field_name in field_names
    }
    return RequestConstraints(**parsed)


def settings_to_json(settings: BackstitchSettings) -> str:
    analyze = asdict(settings.analyze)
    verify = asdict(settings.verify)
    for request in (analyze, verify):
        for field_name in ("temperature", "seed", "reasoning_effort"):
            if request.get(field_name) is None:
                request.pop(field_name, None)
    payload = {
        "config_path": (
            str(settings.config_path) if settings.config_path is not None else None
        ),
        "profile": settings.profile,
        "allow_unknown_keys": settings.allow_unknown_keys,
        "default_command": settings.default_command,
        "exclude": list(settings.exclude),
        "profile_overrides": asdict(settings.profile_overrides),
        "lint": {
            "warn_unused_ignores": settings.lint.warn_unused_ignores,
            "require_suppression_declarations": (
                settings.lint.require_suppression_declarations
            ),
            "per_file_ignores": {
                key: list(codes)
                for key, codes in settings.lint.per_file_ignores.items()
            },
            "per_section_ignores": {
                key: list(codes)
                for key, codes in settings.lint.per_section_ignores.items()
            },
            "suppressions": [
                {
                    "mechanism": rule.mechanism,
                    "path": rule.path,
                    "sections": list(rule.sections),
                    "codes": list(rule.codes),
                    "declaration": rule.declaration,
                    "origin": asdict(rule.origin),
                }
                for rule in settings.lint.suppressions
            ],
        },
        "check": asdict(settings.check),
        "packets": asdict(settings.packets),
        "coverage": asdict(settings.coverage),
        "analyze": analyze,
        "verify": verify,
        "obligations": asdict(settings.obligations),
        "target_roots": asdict(settings.target_roots),
        "diagnostics": policy_to_dict(settings.diagnostics),
        "resolved_diagnostics": resolved_policy_to_dict(settings.diagnostics),
        "config_layers": list(settings.config_layers),
        "config_layer_identities": [
            {"path": identity.path, "raw_sha256": identity.raw_sha256}
            for identity in settings.config_layer_identities
        ],
        "policy_rule_origins": [
            asdict(origin) for origin in settings.policy_rule_origins
        ],
        "ratchet_policy_provenance": [
            asdict(item) for item in settings.ratchet_policy_provenance
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _expand_user_and_env(value: str) -> str:
    expanded = os.path.expanduser(value)
    return re.sub(
        r"\$\{([^}]+)\}|\$([A-Za-z_][A-Za-z0-9_]*)",
        lambda match: os.environ.get(
            match.group(1) or match.group(2) or "",
            match.group(0),
        ),
        expanded,
    )


def expand_path_value(
    value: str,
    *,
    base_dir: Path,
    resolve_symlinks: bool = True,
) -> str:
    expanded = _expand_user_and_env(value)
    path = Path(expanded)
    if not resolve_symlinks:
        return str(lexical_absolute_path(path, base_dir=base_dir))
    if path.is_absolute():
        return str(path.resolve())
    return str((base_dir / path).resolve())


def expand_root_value(value: str) -> str:
    """CFG §4.3 expansion for scan roots: `~` and env vars only.

    Roots are relative to the TARGET repo root ([SC-3]), not to the config
    file, so the config-dir resolution step of expand_path_value must not
    apply -- a `$HOME` config declaring `docs/specs` would otherwise anchor
    the root at `$HOME/docs/specs`. An expanded absolute result passes
    through unchanged.
    """

    return _expand_user_and_env(value)


def _pyproject_has_backstitch(path: Path, raw: bytes) -> bool:
    try:
        text = raw.decode("utf-8")
        data = tomllib.loads(text)
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        # [CFG-8]: a pyproject.toml that does not parse cannot be checked
        # for a [tool.backstitch] table -- exit 2 naming the file, never a
        # silent skip to the next ancestor.
        msg = f"Invalid TOML in {path} during config discovery: {exc}"
        raise ConfigLoadError(msg) from exc
    return "backstitch" in data.get("tool", {})


def _config_stat_identity(value: os.stat_result) -> tuple[int, ...]:
    return filesystem_io.file_stat_identity(value)


def _read_config_source(path: Path, budget: _ConfigReadBudget) -> _ConfigSource:
    """Read one stable config layer exactly once under bootstrap ceilings."""

    if budget.file_count >= MAXIMUM_CONFIG_CHAIN_FILES:
        raise ConfigLoadError(
            f"config extend chain exceeds {MAXIMUM_CONFIG_CHAIN_FILES} config files"
        )
    budget.file_count += 1
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode):
            raise ConfigLoadError(f"config is not a regular file: {path}")
        if before.st_size > MAXIMUM_CONFIG_FILE_BYTES:
            raise ConfigLoadError(f"config file exceeds 1,000,000 raw bytes: {path}")
        if budget.byte_count + before.st_size > MAXIMUM_CONFIG_CHAIN_BYTES:
            raise ConfigLoadError("config extend chain exceeds 5,000,000 raw bytes")
        raw, observed = filesystem_io.read_regular_nofollow(
            path.parent,
            path.name,
            expected_stat=before,
            maximum_bytes=MAXIMUM_CONFIG_FILE_BYTES,
        )
    except ConfigLoadError:
        raise
    except (OSError, filesystem_io.StableReadError) as exc:
        raise ConfigLoadError(f"could not read config {path}: {exc}") from exc
    if budget.byte_count + len(raw) > MAXIMUM_CONFIG_CHAIN_BYTES:
        raise ConfigLoadError("config extend chain exceeds 5,000,000 raw bytes")
    budget.byte_count += len(raw)
    return _ConfigSource(
        raw=raw,
        stat_identity=_config_stat_identity(observed),
    )


def _extract_config_body(path: Path, raw: bytes) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        msg = f"Invalid UTF-8 in {path}: {exc}"
        raise ConfigLoadError(msg) from exc
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        msg = f"Invalid TOML in {path}: {exc}"
        raise ConfigLoadError(msg) from exc
    if path.name == "pyproject.toml":
        tool = data.get("tool", {})
        if "backstitch" not in tool:
            msg = f"Missing [tool.backstitch] in {path}"
            raise ConfigLoadError(msg)
        body = tool["backstitch"]
        if not isinstance(body, dict):
            msg = f"Invalid [tool.backstitch] table in {path}"
            raise ConfigLoadError(msg)
        return body
    if not isinstance(data, dict):
        msg = f"Invalid config root in {path}"
        raise ConfigLoadError(msg)
    return data


def _merge_config_layers(
    base: dict[str, Any],
    overlay: dict[str, Any],
    *,
    path: tuple[str, ...] = (),
    file_layer: bool = False,
) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        current_path = (*path, key)
        if (
            current_path == ("diagnostics", "levels")
            and isinstance(merged.get(key), list)
            and isinstance(value, list)
        ):
            merged[key] = [*merged[key], *value]
        elif (
            current_path == ("profile",)
            and isinstance(merged.get(key), dict)
            and isinstance(value, dict)
        ):
            profile_overlay = dict(value)
            if "code_roots" in profile_overlay and "test_roots" not in profile_overlay:
                profile_overlay["test_roots"] = []
            merged[key] = _merge_config_layers(
                merged[key],
                profile_overlay,
                path=current_path,
                file_layer=file_layer,
            )
        elif (
            file_layer
            and current_path == ("analyze",)
            and isinstance(merged.get(key), dict)
            and isinstance(value, dict)
            and _ANALYZE_FLAT_DESCRIPTOR_KEYS.intersection(value)
        ):
            # [CFG-6.5]: file layers replace the flat descriptor as one unit.
            # Environment and CLI overlays still select only analyze.model.
            analyze_base = {
                child_key: child_value
                for child_key, child_value in merged[key].items()
                if child_key not in _ANALYZE_FLAT_DESCRIPTOR_KEYS
            }
            merged[key] = _merge_config_layers(
                analyze_base,
                value,
                path=current_path,
                file_layer=file_layer,
            )
        elif (
            file_layer
            and current_path == ("analyze", "models")
            and isinstance(merged.get(key), dict)
            and isinstance(value, dict)
        ):
            # Catalog children are immutable descriptor units. A later selector
            # replaces the earlier child instead of inheriting omitted fields.
            merged[key] = {**merged[key], **value}
        elif (
            key in merged and isinstance(merged[key], dict) and isinstance(value, dict)
        ):
            merged[key] = _merge_config_layers(
                merged[key],
                value,
                path=current_path,
                file_layer=file_layer,
            )
        else:
            merged[key] = value
    return merged


def _ratchet_policy_provenance(  # noqa: C901 approved [SC-17.1] RUFF-SUP-134 exception
    layers: Sequence[tuple[dict[str, Any], str, ConfigSourceKind]],
) -> tuple[ConfigValueProvenance, ...]:
    """Retain the effective source of each gate-affecting config value.

    This mirrors the relevant merge rules instead of recording every historical
    author. Replaced values disappear; ordered diagnostic rules retain every
    contributing layer. Git later upgrades ``repository_candidate`` to trusted
    repository ownership against the accepted current and baseline snapshots.
    """

    effective: dict[str, list[ConfigValueProvenance]] = {}

    def set_origin(
        key: str,
        source: str,
        source_kind: ConfigSourceKind,
        *,
        append: bool = False,
    ) -> None:
        if key.startswith("coverage.floors."):
            effective.pop("coverage.floors", None)
        item = ConfigValueProvenance(
            key=key,
            source=source,
            source_kind=source_kind,
        )
        if append:
            effective.setdefault(key, []).append(item)
        else:
            effective[key] = [item]

    for body, source, source_kind in layers:
        profile = body.get("profile")
        if (
            isinstance(profile, dict)
            and "code_roots" in profile
            and "test_roots" not in profile
        ):
            set_origin(
                "profile.test_roots",
                source,
                source_kind,
            )
        for key in _flatten_ratchet_policy_layer(body):
            if key == "extend_exclude":
                set_origin("exclude", source, source_kind, append=True)
            elif key == "diagnostics.levels":
                set_origin(key, source, source_kind, append=True)
            else:
                set_origin(key, source, source_kind)

    # These empty collections are semantic packaged defaults even when their
    # TOML table spelling is absent. Naming them closes provenance for the
    # canonical policy rather than making an empty value source-less.
    for key in (
        "coverage.exemptions",
        "coverage.floors",
        "lint.per_file_ignores",
        "lint.per_section_ignores",
    ):
        if key == "coverage.floors" and any(
            item.startswith("coverage.floors.") for item in effective
        ):
            continue
        effective.setdefault(
            key,
            [
                ConfigValueProvenance(
                    key=key,
                    source=PACKAGED_DEFAULTS_LAYER,
                    source_kind="packaged",
                )
            ],
        )

    return tuple(item for key in sorted(effective) for item in effective[key])


def _flatten_ratchet_policy_layer(  # noqa: C901 approved [SC-17.1] RUFF-SUP-128 exception
    body: Mapping[str, Any],
) -> tuple[str, ...]:
    keys: list[str] = []

    def walk(prefix: str, value: Any) -> None:
        if isinstance(value, dict) and value:
            for child_key, child_value in value.items():
                walk(f"{prefix}.{child_key}", child_value)
            return
        keys.append(prefix)

    for top_level in ("profile", "coverage", "diagnostics", "lint"):
        table = body.get(top_level)
        if not isinstance(table, dict):
            continue
        for key, value in table.items():
            if top_level == "profile" and key == "plan_roots":
                continue
            if top_level == "diagnostics" and key == "registry":
                continue
            if top_level == "coverage" and key in {"format", "output"}:
                continue
            if top_level == "coverage" and key == "floors" and isinstance(value, dict):
                if not value:
                    keys.append("coverage.floors")
                    continue
                for raw_scope, raw_floor in value.items():
                    candidate = (
                        raw_scope[:-1]
                        if isinstance(raw_scope, str) and raw_scope.endswith("/")
                        else raw_scope
                    )
                    canonical_scope = (
                        canonical_repository_path(candidate)
                        if isinstance(candidate, str)
                        else None
                    )
                    scope = (
                        canonical_scope.canonical
                        if canonical_scope is not None
                        else candidate
                    )
                    walk(f"coverage.floors.{scope}", raw_floor)
                continue
            canonical_key = key.replace("-", "_") if top_level == "lint" else key
            walk(f"{top_level}.{canonical_key}", value)
    if "exclude" in body:
        keys.append("exclude")
    if "extend_exclude" in body:
        keys.append("extend_exclude")
    return tuple(keys)


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _validate_ratchet_invocation_sources(
    settings: BackstitchSettings,
    *,
    root: Path,
    explicit: Path | None,
    use_repo_config: bool,
    cli_options: Sequence[tuple[str, str]],
    cli_overrides: Mapping[str, Any],
) -> None:
    """Reject untrusted ratchet inputs before the Git baseline phase."""

    if explicit is not None:
        raise ConfigLoadError(
            "coverage ratchet mode rejects explicit --config selection"
        )
    if not use_repo_config:
        raise ConfigLoadError(
            "coverage ratchet mode requires ordinary repository config discovery"
        )
    if cli_options:
        raise ConfigLoadError("coverage ratchet mode rejects every --option")
    disallowed_overrides = sorted(set(cli_overrides) - _COVERAGE_PRESENTATION_KEYS)
    if disallowed_overrides:
        raise ConfigLoadError(
            "coverage ratchet mode rejects gate-affecting CLI override "
            f"{disallowed_overrides[0]!r}"
        )
    outside = [
        identity.path
        for identity in settings.config_layer_identities
        if not _path_is_within(Path(identity.path), root)
    ]
    if outside:
        raise ConfigLoadError(
            f"coverage ratchet config layer is outside the repository root: {outside[0]}"
        )
    untrusted = [
        item
        for item in settings.ratchet_policy_provenance
        if item.source_kind not in {"packaged", "repository_candidate"}
    ]
    if untrusted:
        first = untrusted[0]
        raise ConfigLoadError(
            "coverage ratchet policy has an external contribution at "
            f"{first.key!r} from {first.source}"
        )


def _expand_named_output_paths(
    body: dict[str, Any],
    base_dir: Path,
    *,
    resolve_symlinks: bool,
) -> None:
    for table_name, key in (
        ("check", "output"),
        ("packets", "output"),
        ("coverage", "output"),
        ("analyze", "cache_path"),
        ("verify", "cache_path"),
    ):
        table = body.get(table_name)
        if isinstance(table, dict):
            value = table.get(key)
            if isinstance(value, str) and value.strip():
                table[key] = expand_path_value(
                    value,
                    base_dir=base_dir,
                    resolve_symlinks=resolve_symlinks,
                )


def _canonicalize_coverage_floors(body: dict[str, Any]) -> None:
    coverage = body.get("coverage")
    if not isinstance(coverage, dict):
        return
    floors = coverage.get("floors")
    if not isinstance(floors, dict):
        return
    canonical_floors: dict[str, Any] = {}
    for raw_scope, floor in floors.items():
        scope = _canonical_coverage_selector(
            raw_scope,
            label=f"coverage.floors.{raw_scope}",
            allow_trailing_slash=True,
        )
        if scope in canonical_floors:
            raise ConfigLoadError(
                f"coverage.floors contains duplicate canonical scope {scope!r}"
            )
        canonical_floors[scope] = floor
    coverage["floors"] = canonical_floors


def _expand_raw_paths(
    body: dict[str, Any],
    base_dir: Path,
    *,
    resolve_symlinks: bool = True,
) -> None:
    """Expand path values against the file that DEFINED them (CFG §2).

    Must run per file BEFORE `extend` merging: a parent's relative
    `check.output` anchors at the parent's directory, not at whichever
    child extended it. expand_path_value is idempotent on the absolute
    results, so the later _parse_settings expansion is a no-op for these.
    """

    _expand_named_output_paths(
        body,
        base_dir,
        resolve_symlinks=resolve_symlinks,
    )
    _canonicalize_coverage_floors(body)
    roots = body.get("target_roots")
    if isinstance(roots, dict):
        for name, value in roots.items():
            if isinstance(value, str):
                roots[name] = expand_path_value(
                    value,
                    base_dir=base_dir,
                    resolve_symlinks=resolve_symlinks,
                )
    verify = body.get("verify")
    if isinstance(verify, dict):
        evaluation = verify.get("eval")
        if isinstance(evaluation, dict):
            for key in ("qualification_corpus", "qualification_report"):
                value = evaluation.get(key)
                if isinstance(value, str) and value.strip():
                    evaluation[key] = _expand_contained_config_path(
                        value,
                        base_dir=base_dir,
                        field_name=f"verify.eval.{key}",
                        resolve_symlinks=resolve_symlinks,
                    )


def _expand_contained_config_path(
    value: str,
    *,
    base_dir: Path,
    field_name: str,
    resolve_symlinks: bool = True,
) -> str:
    expanded = Path(_expand_user_and_env(value))
    if resolve_symlinks:
        base = base_dir.resolve()
        candidate = (expanded if expanded.is_absolute() else base / expanded).resolve()
    else:
        if not base_dir.is_absolute():
            raise ConfigLoadError(f"{field_name} config directory must be absolute")
        base = lexical_absolute_path(base_dir, base_dir=base_dir)
        candidate = lexical_absolute_path(expanded, base_dir=base)
    if candidate != base and not candidate.is_relative_to(base):
        raise ConfigLoadError(f"{field_name} must be contained by its config directory")
    return str(candidate)


def _load_config_chain(
    path: Path,
    seen: set[Path],
    budget: _ConfigReadBudget | None = None,
    preloaded: dict[Path, _ConfigSource] | None = None,
) -> tuple[list[str], tuple[_ConfigLayer, ...]]:
    if budget is None:
        budget = _ConfigReadBudget()
    if preloaded is None:
        preloaded = {}
    resolved = _canonical_config_address(path)
    if resolved in seen:
        msg = f"Circular extend chain detected at {resolved}"
        raise ConfigLoadError(msg)
    seen.add(resolved)

    source = preloaded.pop(resolved, None)
    if source is None:
        source = _read_config_source(resolved, budget)
    else:
        try:
            current_identity = _config_stat_identity(resolved.lstat())
        except OSError as exc:
            raise ConfigLoadError(f"could not read config {resolved}: {exc}") from exc
        if current_identity != source.stat_identity:
            raise ConfigLoadError(f"config changed identity while reading: {resolved}")
    raw = source.raw
    body = _extract_config_body(resolved, raw)
    layer = _ConfigLayer(
        path=resolved,
        body=body,
        raw_sha256=hashlib.sha256(raw).hexdigest(),
        raw_bytes=raw,
        stat_identity=source.stat_identity,
    )
    _expand_raw_paths(body, resolved.parent)
    extend = body.get("extend")
    warnings: list[str] = []
    if extend is None:
        return warnings, (layer,)

    if not isinstance(extend, str) or not extend.strip():
        msg = f"Invalid extend value in {resolved}"
        raise ConfigLoadError(msg)

    expanded_extend = Path(_expand_user_and_env(extend.strip()))
    parent_path = _canonical_config_address(
        expanded_extend
        if expanded_extend.is_absolute()
        else resolved.parent / expanded_extend
    )
    _require_regular_config(
        parent_path,
        missing_message=f"extend target not found: {parent_path}",
    )

    parent_warnings, parent_layers = _load_config_chain(
        parent_path,
        seen,
        budget,
        preloaded,
    )
    warnings.extend(parent_warnings)
    return warnings, (*parent_layers, layer)


def _parse_profile_settings(
    raw: dict[str, Any], source_path: Path
) -> tuple[str | None, ProfileSettings]:
    profile_value = raw.get("profile")
    if isinstance(profile_value, dict):
        profile_table = profile_value
        profile_name = profile_value.get("name")
        if profile_name is not None and not isinstance(profile_name, str):
            raise ConfigLoadError(f"profile.name must be a string in {source_path}")
        if profile_name is not None:
            from backstitch.profiles import get_profile

            try:
                get_profile(profile_name)
            except ValueError as exc:
                raise ConfigLoadError(f"{exc} in {source_path}") from exc
    elif profile_value is None:
        profile_name = None
        profile_table = {}
    else:
        raise ConfigLoadError(
            f"unknown config key `profile` in {source_path}: the profile"
            ' name is spelled [profile] name = "..."'
        )

    def roots(key: str) -> tuple[str, ...] | None:
        values = _optional_str_tuple(profile_table.get(key), f"profile.{key}")
        return None if values is None else tuple(expand_root_value(v) for v in values)

    return profile_name, ProfileSettings(
        spec_roots=roots("spec_roots"),
        plan_roots=roots("plan_roots"),
        code_roots=roots("code_roots"),
        test_roots=roots("test_roots"),
        planned_spec_globs=_optional_str_tuple(
            profile_table.get("planned_spec_globs"),
            "profile.planned_spec_globs",
        ),
        exploratory_spec_globs=_optional_str_tuple(
            profile_table.get("exploratory_spec_globs"),
            "profile.exploratory_spec_globs",
        ),
        meta_spec_globs=_merged_meta_globs(profile_table),
        process_spec_globs=_optional_str_tuple(
            profile_table.get("process_spec_globs"),
            "profile.process_spec_globs",
        ),
    )


def _parse_optional_output_path(
    table: dict[str, Any],
    *,
    field_name: str,
    source_path: Path,
    resolve_symlinks: bool,
    include_source_in_error: bool = False,
) -> str | None:
    value = table.get("output")
    if value is not None and not isinstance(value, str):
        suffix = f" in {source_path}" if include_source_in_error else ""
        raise ConfigLoadError(f"{field_name} must be a string{suffix}")
    if value is None:
        return None
    return expand_path_value(
        value,
        base_dir=source_path.parent,
        resolve_symlinks=resolve_symlinks,
    )


def _parse_check_settings(
    table: dict[str, Any],
    *,
    source_path: Path,
    resolve_symlinks: bool,
) -> CheckSettings:
    check_format = table.get("format")
    if check_format is not None and check_format not in {"text", "json"}:
        raise ConfigLoadError("check.format must be 'text' or 'json'")
    warnings_as_errors = table.get("warnings_as_errors")
    if warnings_as_errors is not None and not isinstance(warnings_as_errors, bool):
        raise ConfigLoadError("check.warnings_as_errors must be a boolean")
    return CheckSettings(
        format=check_format,
        warnings_as_errors=warnings_as_errors,
        output=_parse_optional_output_path(
            table,
            field_name="check.output",
            source_path=source_path,
            resolve_symlinks=resolve_symlinks,
        ),
    )


def _parse_weft_root(
    table: dict[str, Any], *, source_path: Path, resolve_symlinks: bool
) -> str | None:
    value = table.get("weft")
    if value is not None and not isinstance(value, str):
        raise ConfigLoadError("target_roots.weft must be a string")
    if value is None:
        return None
    return expand_path_value(
        value,
        base_dir=source_path.parent,
        resolve_symlinks=resolve_symlinks,
    )


def _parse_diagnostics_settings(
    table: dict[str, Any], *, source_path: Path, allow_unknown: bool
) -> DiagnosticsSettings:
    try:
        return parse_policy(
            table,
            registry=default_registry(),
            source=str(source_path),
            allow_unknown=allow_unknown,
        )
    except DiagnosticConfigError as exc:
        raise ConfigLoadError(str(exc)) from exc


def _parse_settings(
    raw: dict[str, Any],
    *,
    source_path: Path,
    effective_config_path: Path | None,
    config_layers: tuple[str, ...],
    config_layer_identities: tuple[ConfigLayerIdentity, ...],
    policy_rule_origins: tuple[PolicyRuleOrigin, ...],
    suppression_rule_source: str,
    analyze_model_source: str,
    explicit_analyze_keys: frozenset[str],
    validate_unknown_keys: bool,
    default_command: Literal["check", "analyze"] | None,
    available_models: tuple[str, ...],
    ratchet_policy_provenance: tuple[ConfigValueProvenance, ...],
    resolve_symlinks: bool = True,
) -> BackstitchSettings:
    allow_unknown = raw.get("allow_unknown_keys", False)
    if not isinstance(allow_unknown, bool):
        msg = f"allow_unknown_keys must be a boolean in {source_path}"
        raise ConfigLoadError(msg)

    # [CFG-8]: unknown keys are load errors by default -- a typo'd key that
    # silently does nothing is a fake affordance. allow_unknown_keys = true
    # is the forward-compatibility hatch and downgrades to stderr warnings;
    # it never suppresses type errors on known keys.
    if validate_unknown_keys:
        _validate_unknown_keys(raw, source_path)

    profile_name, profile_settings = _parse_profile_settings(raw, source_path)
    excludes = _resolve_excludes(raw)

    check_table = _expect_table(raw.get("check"), "check")
    packets_table = _expect_table(raw.get("packets"), "packets")
    coverage_table = _expect_table(raw.get("coverage"), "coverage")
    analyze_table = _expect_table(raw.get("analyze"), "analyze")
    verify_table = _expect_table(raw.get("verify"), "verify")
    obligations_table = _expect_table(raw.get("obligations"), "obligations")
    target_table = _expect_table(raw.get("target_roots"), "target_roots")
    lint_table = _expect_table(raw.get("lint"), "lint")
    diagnostics_table = _expect_table(raw.get("diagnostics"), "diagnostics")

    # CFG §6.4: [packets].output is stored for forward compatibility; the
    # CLI still requires --output in v1 -- parsed here so the schema key is
    # never silently dead.
    packets_output = _parse_optional_output_path(
        packets_table,
        field_name="packets.output",
        source_path=source_path,
        resolve_symlinks=resolve_symlinks,
        include_source_in_error=True,
    )
    coverage_settings = _parse_coverage_settings(
        coverage_table,
        source_path=source_path,
        code_roots=profile_settings.code_roots or (),
        resolve_symlinks=resolve_symlinks,
    )

    lint_settings = _parse_lint_settings(
        lint_table,
        suppression_rule_source=suppression_rule_source,
        allow_unknown=allow_unknown,
    )

    analyze_settings = _parse_analyze_settings(
        analyze_table,
        source_path=source_path,
        explicit_analyze_keys=explicit_analyze_keys,
        available_models=available_models,
        resolve_symlinks=resolve_symlinks,
    )
    verify_settings = _parse_verify_settings(
        verify_table,
        source_path=source_path,
        analyze=analyze_settings,
        explicit_analyze_keys=explicit_analyze_keys,
        resolve_symlinks=resolve_symlinks,
    )
    obligation_settings = _parse_obligation_settings(obligations_table)

    check_settings = _parse_check_settings(
        check_table,
        source_path=source_path,
        resolve_symlinks=resolve_symlinks,
    )
    weft_root = _parse_weft_root(
        target_table,
        source_path=source_path,
        resolve_symlinks=resolve_symlinks,
    )
    diagnostics = _parse_diagnostics_settings(
        diagnostics_table,
        source_path=source_path,
        allow_unknown=allow_unknown,
    )
    if len(policy_rule_origins) != len(diagnostics.levels):
        raise ConfigLoadError(
            "internal configuration error: diagnostic rule origins are not aligned"
        )

    return BackstitchSettings(
        profile=profile_name,
        allow_unknown_keys=allow_unknown,
        default_command=default_command,
        packets=PacketsSettings(output=packets_output),
        exclude=excludes,
        profile_overrides=profile_settings,
        lint=lint_settings,
        check=check_settings,
        coverage=coverage_settings,
        analyze=analyze_settings,
        verify=verify_settings,
        obligations=obligation_settings,
        target_roots=TargetRootSettings(weft=weft_root),
        diagnostics=diagnostics,
        config_path=effective_config_path,
        config_dir=effective_config_path.parent if effective_config_path else None,
        config_layers=config_layers,
        config_layer_identities=config_layer_identities,
        policy_rule_origins=policy_rule_origins,
        ratchet_policy_provenance=ratchet_policy_provenance,
        analyze_model_source=analyze_model_source,
    )


def _parse_default_command(
    raw: Mapping[str, Any],
    *,
    source_path: Path,
) -> Literal["check", "analyze"] | None:
    raw_default_command = raw.get("default_command", False)
    if raw_default_command is False:
        return None
    if isinstance(raw_default_command, str) and raw_default_command in {
        "check",
        "analyze",
    }:
        return cast(Literal["check", "analyze"], raw_default_command)
    raise ConfigLoadError(
        f"default_command must be false, 'check', or 'analyze' in {source_path}"
    )


def _parse_coverage_settings(
    table: dict[str, Any],
    *,
    source_path: Path,
    code_roots: tuple[str, ...],
    resolve_symlinks: bool,
) -> CoverageSettings:
    """Parse the closed deterministic coverage table ([COV-4], [COV-5])."""

    mode_value = table.get("mode", "report")
    if mode_value not in {"report", "ratchet"}:
        raise ConfigLoadError("coverage.mode must be 'report' or 'ratchet'")
    mode = cast(Literal["report", "ratchet"], mode_value)

    format_value = table.get("format", "text")
    if format_value not in {"text", "json"}:
        raise ConfigLoadError("coverage.format must be 'text' or 'json'")
    output = table.get("output")
    if output is not None and (not isinstance(output, str) or not output.strip()):
        raise ConfigLoadError("coverage.output must be a nonblank string when set")

    granularity_value = table.get("granularity", "definition")
    if granularity_value != "definition":
        raise ConfigLoadError("coverage.granularity must be 'definition'")
    inherited_counts = table.get("inherited_counts", False)
    if not isinstance(inherited_counts, bool):
        raise ConfigLoadError("coverage.inherited_counts must be a boolean")

    ratchet_base = table.get("ratchet_base", "")
    if (
        not isinstance(ratchet_base, str)
        or ratchet_base != ratchet_base.strip()
        or any(character in ratchet_base for character in "\x00\r\n")
    ):
        raise ConfigLoadError(
            "coverage.ratchet_base must be a trimmed single-line string"
        )
    if mode == "ratchet" and not ratchet_base:
        raise ConfigLoadError(
            "coverage.ratchet_base must be nonblank when coverage.mode is 'ratchet'"
        )

    exemptions = _parse_coverage_exemptions(table.get("exemptions"))
    floors = _parse_coverage_floors(
        table.get("floors"),
        code_roots=code_roots,
    )

    maximum_git_command_seconds = _coverage_positive_number(
        table,
        "maximum_git_command_seconds",
        default=10.0,
    )
    maximum_runtime_seconds = _coverage_positive_number(
        table,
        "maximum_runtime_seconds",
        default=60.0,
    )
    parsed_output = (
        None
        if output is None
        else expand_path_value(
            output,
            base_dir=source_path.parent,
            resolve_symlinks=resolve_symlinks,
        )
    )
    return CoverageSettings(
        mode=mode,
        format=cast(Literal["text", "json"], format_value),
        output=parsed_output,
        granularity="definition",
        inherited_counts=inherited_counts,
        ratchet_base=ratchet_base,
        exemptions=exemptions,
        floors=floors,
        maximum_baseline_files=_coverage_positive_int(
            table, "maximum_baseline_files", default=20_000
        ),
        maximum_file_bytes=_coverage_positive_int(
            table, "maximum_file_bytes", default=5_000_000
        ),
        maximum_baseline_bytes=_coverage_positive_int(
            table, "maximum_baseline_bytes", default=100_000_000
        ),
        maximum_history_commits=_coverage_positive_int(
            table, "maximum_history_commits", default=1_000
        ),
        maximum_git_command_seconds=maximum_git_command_seconds,
        maximum_git_commands=_coverage_positive_int(
            table, "maximum_git_commands", default=64
        ),
        maximum_git_output_bytes=_coverage_positive_int(
            table, "maximum_git_output_bytes", default=100_000_000
        ),
        maximum_commit_message_bytes=_coverage_positive_int(
            table, "maximum_commit_message_bytes", default=1_000_000
        ),
        maximum_runtime_seconds=maximum_runtime_seconds,
    )


def _parse_coverage_exemptions(value: Any) -> tuple[CoverageExemption, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ConfigLoadError("coverage.exemptions must be an array of tables")
    exemptions: list[CoverageExemption] = []
    for position, raw in enumerate(value):
        label = f"coverage.exemptions[{position}]"
        if not isinstance(raw, dict):
            raise ConfigLoadError(f"{label} must be a table")
        unknown = sorted(set(raw) - _COVERAGE_EXEMPTION_KEYS)
        if unknown:
            raise ConfigLoadError(f"{label} has unknown keys: {', '.join(unknown)}")
        selector_keys = {"path", "glob"}.intersection(raw)
        if len(selector_keys) != 1:
            raise ConfigLoadError(f"{label} requires exactly one of path or glob")
        kind = cast(Literal["path", "glob"], next(iter(selector_keys)))
        selector = _canonical_coverage_selector(
            raw[kind],
            label=f"{label}.{kind}",
        )
        if kind == "path" and any(character in selector for character in "*?[]"):
            raise ConfigLoadError(f"{label}.path must not contain glob syntax")
        exemptions.append(
            CoverageExemption(
                kind=kind,
                selector=selector,
                reason=_normalize_coverage_reason(
                    raw.get("reason"),
                    label=f"{label}.reason",
                ),
            )
        )
    return tuple(exemptions)


def _parse_coverage_floors(
    value: Any,
    *,
    code_roots: tuple[str, ...],
) -> tuple[CoverageFloor, ...]:
    if value is None:
        return ()
    if not isinstance(value, dict):
        raise ConfigLoadError("coverage.floors must be a table")
    roots = tuple(
        canonical.canonical
        for root in code_roots
        if (canonical := canonical_repository_path(root)) is not None
    )
    floors: list[CoverageFloor] = []
    seen: set[str] = set()
    for raw_scope, raw_floor in value.items():
        if not isinstance(raw_scope, str):
            raise ConfigLoadError("coverage.floors keys must be strings")
        scope = _canonical_coverage_selector(
            raw_scope,
            label=f"coverage.floors.{raw_scope}",
            allow_trailing_slash=True,
        )
        if scope in seen:
            raise ConfigLoadError(
                f"coverage.floors contains duplicate canonical scope {scope!r}"
            )
        seen.add(scope)
        if not any(
            root == "." or scope == root or scope.startswith(f"{root}/")
            for root in roots
        ):
            raise ConfigLoadError(
                f"coverage floor scope {scope!r} must equal or be nested within"
                " a final effective code root"
            )
        if not isinstance(raw_floor, dict):
            raise ConfigLoadError(f"coverage.floors.{scope} must be a table")
        unknown = sorted(set(raw_floor) - _COVERAGE_FLOOR_KEYS)
        if unknown:
            raise ConfigLoadError(
                f"coverage.floors.{scope} has unknown keys: {', '.join(unknown)}"
            )
        if not _COVERAGE_FLOOR_KEYS.intersection(raw_floor):
            raise ConfigLoadError(
                f"coverage.floors.{scope} requires at least one of direct or accounted"
            )
        direct = (
            _require_rate(raw_floor, "direct", f"coverage.floors.{scope}")
            if "direct" in raw_floor
            else None
        )
        accounted = (
            _require_rate(raw_floor, "accounted", f"coverage.floors.{scope}")
            if "accounted" in raw_floor
            else None
        )
        floors.append(CoverageFloor(scope=scope, direct=direct, accounted=accounted))
    return tuple(sorted(floors, key=lambda floor: floor.scope))


def _canonical_coverage_selector(
    value: Any,
    *,
    label: str,
    allow_trailing_slash: bool = False,
) -> str:
    if (
        not isinstance(value, str)
        or not value
        or any(character in value for character in "\x00\r\n\t")
    ):
        raise ConfigLoadError(f"{label} must be a nonblank repo-relative POSIX path")
    if not allow_trailing_slash and value.endswith("/"):
        raise ConfigLoadError(f"{label} must be a nonblank repo-relative POSIX path")
    candidate = value[:-1] if allow_trailing_slash and value.endswith("/") else value
    if any(part in {"", ".", ".."} for part in candidate.split("/")):
        raise ConfigLoadError(f"{label} must be a nonblank repo-relative POSIX path")
    canonical = canonical_repository_path(candidate)
    if canonical is None:
        raise ConfigLoadError(f"{label} must be a nonblank repo-relative POSIX path")
    return canonical.canonical


def _normalize_coverage_reason(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise ConfigLoadError(f"{label} must be a nonblank string")
    if any(character in value for character in "\x00\r\n"):
        raise ConfigLoadError(f"{label} must be a single-line string")
    normalized = unicodedata.normalize("NFC", value.strip())
    if not normalized:
        raise ConfigLoadError(f"{label} must be a nonblank string")
    try:
        encoded = normalized.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ConfigLoadError(f"{label} must be valid Unicode") from exc
    if len(encoded) > 4096:
        raise ConfigLoadError(f"{label} must encode to at most 4096 UTF-8 bytes")
    return normalized


def _coverage_positive_int(
    table: dict[str, Any],
    key: str,
    *,
    default: int,
) -> int:
    value = table.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigLoadError(f"coverage.{key} must be an integer at least 1")
    return value


def _coverage_positive_number(
    table: dict[str, Any],
    key: str,
    *,
    default: float,
) -> float:
    value = table.get(key, default)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) <= 0.0
    ):
        raise ConfigLoadError(f"coverage.{key} must be a finite positive number")
    return float(value)


def _parse_analyze_settings(  # noqa: C901 approved [SC-17.1] RUFF-SUP-129 exception
    table: dict[str, Any],
    *,
    source_path: Path,
    explicit_analyze_keys: frozenset[str],
    available_models: tuple[str, ...],
    resolve_symlinks: bool,
) -> AnalyzeSettings:
    """Parse the exact semantic inference, cache, and budget surface."""

    backend_id = _require_string(table, "backend_id", "analyze")
    plugin_id = _require_string(table, "plugin_id", "analyze")
    plugin_distribution_name = _require_string(
        table, "plugin_distribution_name", "analyze"
    )
    model = _require_string(table, "model", "analyze")
    adapter_model_id = _require_string(table, "adapter_model_id", "analyze")
    model_revision = _require_string(table, "model_revision", "analyze")
    capability_schema_version = _parse_capability_schema_version(table, "analyze")
    capability_revision = _parse_capability_revision(table, "analyze")
    request_constraints = _parse_request_constraints(
        table.get("request_constraints"),
        "analyze.request_constraints",
    )
    maximum_input_bytes = _require_int(
        table, "maximum_input_bytes", "analyze", minimum=1
    )
    concurrency = _require_int(table, "concurrency", "analyze", minimum=1)
    json_mode = _require_enum(
        table, "json_mode", "analyze", {"prefer", "require", "off"}
    )
    temperature = (
        _require_number(
            table,
            "temperature",
            "analyze",
            minimum=0.0,
            maximum=2.0,
        )
        if "temperature" in table
        else None
    )
    seed = (
        _require_int(table, "seed", "analyze", minimum=0) if "seed" in table else None
    )
    max_tokens = _require_int(table, "max_tokens", "analyze", minimum=1)
    reasoning_effort = (
        cast(
            ReasoningEffort,
            _require_enum(
                table,
                "reasoning_effort",
                "analyze",
                set(REASONING_EFFORT_VALUES),
            ),
        )
        if "reasoning_effort" in table
        else None
    )
    cache_path = _require_string(table, "cache_path", "analyze")
    if not cache_path.strip():
        raise ConfigLoadError("analyze.cache_path must be a nonblank path string")
    cache_path = expand_path_value(
        cache_path,
        base_dir=source_path.parent,
        resolve_symlinks=resolve_symlinks,
    )
    cache_mode = _require_enum(
        table, "cache_mode", "analyze", {"off", "read-write", "require"}
    )
    result_reuse = _require_enum(
        table,
        "result_reuse",
        "analyze",
        {"evidence-stable", "exact-inference"},
    )
    search_epoch = _require_string(table, "search_epoch", "analyze")
    if not search_epoch.strip():
        raise ConfigLoadError("analyze.search_epoch must be nonblank")
    require_complete = _require_bool(table, "require_complete", "analyze")
    required_kinds = _parse_required_kinds(table.get("required_kinds"))
    minimum_packets = _require_int(table, "minimum_packets", "analyze", minimum=0)
    maximum_packets = _require_int(table, "maximum_packets", "analyze", minimum=0)
    maximum_prompt_bytes = _require_int(
        table, "maximum_prompt_bytes", "analyze", minimum=0
    )
    alias_declared = "candidate_handling" in explicit_analyze_keys
    canonical_declared = "finding_handling" in explicit_analyze_keys
    if alias_declared and canonical_declared:
        raise ConfigLoadError(
            "analyze.finding_handling and analyze.candidate_handling cannot both "
            "be supplied"
        )
    finding_key = "candidate_handling" if alias_declared else "finding_handling"
    finding_handling = _require_enum(
        table,
        finding_key,
        "analyze",
        {"allow", "report", "require_disposition"},
    )
    maximum_provider_calls = _require_int(
        table, "maximum_provider_calls", "analyze", minimum=0
    )
    lock_wait_timeout_seconds = _require_int(
        table, "lock_wait_timeout_seconds", "analyze", minimum=1
    )
    maximum_runtime_seconds = _require_int(
        table, "maximum_runtime_seconds", "analyze", minimum=1
    )
    maximum_estimated_cost_microusd = _require_int(
        table, "maximum_estimated_cost_microusd", "analyze", minimum=0
    )
    input_cost = _require_int(
        table,
        "input_cost_microusd_per_million_tokens",
        "analyze",
        minimum=0,
    )
    output_cost = _require_int(
        table,
        "output_cost_microusd_per_million_tokens",
        "analyze",
        minimum=0,
    )
    input_token_overhead = _require_int(
        table, "input_token_overhead", "analyze", minimum=0
    )
    cost_rate_source = _require_string(table, "cost_rate_source", "analyze")

    dispositions = _parse_dispositions(table.get("dispositions", []))

    if json_mode == "prefer" and cache_mode != "off":
        raise ConfigLoadError(
            "analyze.json_mode = 'prefer' is allowed only with cache_mode = 'off'"
        )
    if cache_mode in {"read-write", "require"}:
        identities = {
            "backend_id": backend_id,
            "plugin_id": plugin_id,
            "plugin_distribution_name": plugin_distribution_name,
            "model_revision": model_revision,
        }
        blank = [name for name, value in identities.items() if not value.strip()]
        if blank:
            raise ConfigLoadError(
                "analyze cached modes require nonblank backend_id, plugin_id, "
                "plugin_distribution_name, and model_revision before model "
                "precedence is applied; blank: " + ", ".join(blank)
            )
    if maximum_packets and maximum_packets < minimum_packets:
        raise ConfigLoadError(
            "analyze.maximum_packets must be zero or at least minimum_packets"
        )
    if maximum_estimated_cost_microusd > 0:
        cost_inputs = {
            "input_cost_microusd_per_million_tokens",
            "output_cost_microusd_per_million_tokens",
            "input_token_overhead",
        }
        missing = sorted(cost_inputs - explicit_analyze_keys)
        if missing:
            raise ConfigLoadError(
                "a positive analyze.maximum_estimated_cost_microusd requires "
                "explicit rate and overhead values in repository config; missing: "
                + ", ".join(missing)
            )
        if not cost_rate_source.strip():
            raise ConfigLoadError(
                "a positive analyze.maximum_estimated_cost_microusd requires a "
                "nonblank analyze.cost_rate_source"
            )

    return AnalyzeSettings(
        backend_id=backend_id,
        plugin_id=plugin_id,
        plugin_distribution_name=plugin_distribution_name,
        model=model,
        adapter_model_id=adapter_model_id,
        model_revision=model_revision,
        capability_schema_version=capability_schema_version,
        capability_revision=capability_revision,
        request_constraints=request_constraints,
        maximum_input_bytes=maximum_input_bytes,
        concurrency=concurrency,
        json_mode=json_mode,
        temperature=temperature,
        seed=seed,
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
        cache_path=cache_path,
        cache_mode=cache_mode,
        result_reuse=result_reuse,
        search_epoch=search_epoch,
        require_complete=require_complete,
        required_kinds=required_kinds,
        minimum_packets=minimum_packets,
        maximum_packets=maximum_packets,
        maximum_prompt_bytes=maximum_prompt_bytes,
        finding_handling=finding_handling,
        maximum_provider_calls=maximum_provider_calls,
        lock_wait_timeout_seconds=lock_wait_timeout_seconds,
        maximum_runtime_seconds=maximum_runtime_seconds,
        maximum_estimated_cost_microusd=maximum_estimated_cost_microusd,
        input_cost_microusd_per_million_tokens=input_cost,
        output_cost_microusd_per_million_tokens=output_cost,
        input_token_overhead=input_token_overhead,
        cost_rate_source=cost_rate_source,
        dispositions=dispositions,
        available_models=available_models,
    )


def _validate_analyze_verify_provider(
    table: dict[str, Any],
    *,
    analyze: AnalyzeSettings,
    explicit_analyze_keys: frozenset[str],
    maximum_cost: int,
) -> None:
    if "provider" in table:
        raise ConfigLoadError(
            "verify.provider must be absent when provider_source = 'analyze'"
        )
    identities = {
        "backend_id": analyze.backend_id,
        "plugin_id": analyze.plugin_id,
        "plugin_distribution_name": analyze.plugin_distribution_name,
        "model": analyze.model,
        "model_revision": analyze.model_revision,
    }
    blank = [name for name, value in identities.items() if not value.strip()]
    if blank:
        raise ConfigLoadError(
            "verify provider_source = 'analyze' requires a complete nonblank "
            "analyze provider descriptor; blank: " + ", ".join(blank)
        )
    if maximum_cost == 0:
        return
    cost_keys = {
        "input_cost_microusd_per_million_tokens",
        "output_cost_microusd_per_million_tokens",
        "input_token_overhead",
    }
    missing = sorted(cost_keys - explicit_analyze_keys)
    if missing:
        raise ConfigLoadError(
            "a positive verify.maximum_estimated_cost_microusd requires "
            "explicit analyze rate and overhead values; missing: " + ", ".join(missing)
        )
    if not analyze.cost_rate_source.strip():
        raise ConfigLoadError(
            "a positive verify.maximum_estimated_cost_microusd requires "
            "a nonblank analyze.cost_rate_source"
        )


def _resolve_verify_provider_override(
    table: dict[str, Any], *, maximum_cost: int
) -> VerifyProviderSettings:
    if "provider" not in table:
        raise ConfigLoadError(
            "verify.provider is required when provider_source = 'override'"
        )
    provider = _parse_verify_provider(
        _expect_table(table["provider"], "verify.provider")
    )
    if maximum_cost > 0 and not provider.cost_rate_source.strip():
        raise ConfigLoadError(
            "a positive verify.maximum_estimated_cost_microusd requires a "
            "nonblank verify.provider.cost_rate_source"
        )
    return provider


def _resolve_verify_provider(
    table: dict[str, Any],
    *,
    provider_source: Literal["analyze", "override"],
    analyze: AnalyzeSettings,
    explicit_analyze_keys: frozenset[str],
    maximum_cost: int,
) -> VerifyProviderSettings | None:
    if provider_source == "analyze":
        _validate_analyze_verify_provider(
            table,
            analyze=analyze,
            explicit_analyze_keys=explicit_analyze_keys,
            maximum_cost=maximum_cost,
        )
        return None
    return _resolve_verify_provider_override(table, maximum_cost=maximum_cost)


def _validate_verify_mode_constraints(
    *,
    required_verdicts: int,
    search_epochs: tuple[str, ...],
    json_mode: str,
    cache_mode: str,
) -> None:
    if required_verdicts != len(search_epochs):
        raise ConfigLoadError(
            "verify.required_verdicts must equal the length of verify.search_epochs"
        )
    if json_mode == "prefer" and cache_mode != "off":
        raise ConfigLoadError(
            "verify.json_mode = 'prefer' is allowed only with cache_mode = 'off'"
        )


def _parse_verify_settings(
    table: dict[str, Any],
    *,
    source_path: Path,
    analyze: AnalyzeSettings,
    explicit_analyze_keys: frozenset[str],
    resolve_symlinks: bool,
) -> DisabledVerifySettings | VerifySettings:
    enabled = _require_bool(table, "enabled", "verify")
    if not enabled:
        if set(table) == {"enabled"}:
            return DisabledVerifySettings()

    provider_source = _require_enum(
        table, "provider_source", "verify", {"analyze", "override"}
    )
    concurrency = _require_int(table, "concurrency", "verify", minimum=1)
    cache_path = _require_string(table, "cache_path", "verify")
    if not cache_path.strip():
        raise ConfigLoadError("verify.cache_path must be a nonblank path string")
    cache_path = expand_path_value(
        cache_path,
        base_dir=source_path.parent,
        resolve_symlinks=resolve_symlinks,
    )
    cache_mode = _require_enum(
        table, "cache_mode", "verify", {"off", "read-write", "require"}
    )
    search_epochs = _parse_verify_search_epochs(table.get("search_epochs"))
    json_mode = _require_enum(
        table, "json_mode", "verify", {"prefer", "require", "off"}
    )
    temperature = (
        _require_number(
            table,
            "temperature",
            "verify",
            minimum=0.0,
            maximum=2.0,
        )
        if "temperature" in table
        else None
    )
    seed = _require_int(table, "seed", "verify", minimum=0) if "seed" in table else None
    max_tokens = _require_int(table, "max_tokens", "verify", minimum=1)
    reasoning_effort = (
        cast(
            ReasoningEffort,
            _require_enum(
                table,
                "reasoning_effort",
                "verify",
                set(REASONING_EFFORT_VALUES),
            ),
        )
        if "reasoning_effort" in table
        else None
    )
    required_verdicts = _require_int(table, "required_verdicts", "verify", minimum=1)
    minimum_support_score = _require_number(
        table,
        "minimum_support_score",
        "verify",
        minimum=0.0,
        maximum=1.0,
    )
    indeterminate = _require_enum(table, "indeterminate", "verify", {"allow", "report"})
    maximum_provider_calls = _require_int(
        table, "maximum_provider_calls", "verify", minimum=0
    )
    maximum_prompt_bytes = _require_int(
        table, "maximum_prompt_bytes", "verify", minimum=1
    )
    lock_wait_timeout_seconds = _require_int(
        table, "lock_wait_timeout_seconds", "verify", minimum=1
    )
    maximum_runtime_seconds = _require_int(
        table, "maximum_runtime_seconds", "verify", minimum=1
    )
    maximum_cost = _require_int(
        table, "maximum_estimated_cost_microusd", "verify", minimum=0
    )

    _validate_verify_mode_constraints(
        required_verdicts=required_verdicts,
        search_epochs=search_epochs,
        json_mode=json_mode,
        cache_mode=cache_mode,
    )
    provider = _resolve_verify_provider(
        table,
        provider_source=cast(Literal["analyze", "override"], provider_source),
        analyze=analyze,
        explicit_analyze_keys=explicit_analyze_keys,
        maximum_cost=maximum_cost,
    )

    evaluation = None
    if "eval" in table:
        evaluation = _parse_verify_eval_settings(
            _expect_table(table["eval"], "verify.eval")
        )

    resolved = VerifySettings(
        enabled=True,
        provider_source=provider_source,
        concurrency=concurrency,
        cache_path=cache_path,
        cache_mode=cache_mode,
        search_epochs=search_epochs,
        json_mode=json_mode,
        temperature=temperature,
        seed=seed,
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
        required_verdicts=required_verdicts,
        minimum_support_score=minimum_support_score,
        indeterminate=indeterminate,
        maximum_provider_calls=maximum_provider_calls,
        maximum_prompt_bytes=maximum_prompt_bytes,
        lock_wait_timeout_seconds=lock_wait_timeout_seconds,
        maximum_runtime_seconds=maximum_runtime_seconds,
        maximum_estimated_cost_microusd=maximum_cost,
        provider=provider,
        eval=evaluation,
    )
    return resolved if enabled else DisabledVerifySettings()


def _parse_verify_search_epochs(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigLoadError("verify.search_epochs must be an array of strings")
    if not value:
        raise ConfigLoadError("verify.search_epochs must not be empty")
    if any(not item.strip() for item in value):
        raise ConfigLoadError("verify.search_epochs must contain only nonblank strings")
    if len(value) != len(set(value)):
        raise ConfigLoadError("verify.search_epochs must not contain duplicates")
    return tuple(value)


def _parse_verify_provider(table: dict[str, Any]) -> VerifyProviderSettings:
    supplied = set(table)
    missing = sorted(_VERIFY_PROVIDER_KEYS - supplied)
    unknown = sorted(supplied - _VERIFY_PROVIDER_KEYS)
    if missing:
        raise ConfigLoadError(
            "verify.provider must be a complete descriptor; missing: "
            + ", ".join(missing)
        )
    if unknown:
        raise ConfigLoadError(f"unknown config key `verify.provider.{unknown[0]}`")
    values = {
        key: _require_string(table, key, "verify.provider")
        for key in (
            "backend_id",
            "plugin_id",
            "plugin_distribution_name",
            "model",
            "adapter_model_id",
            "model_revision",
            "capability_revision",
        )
    }
    blank = [key for key, value in values.items() if not value.strip()]
    if blank:
        raise ConfigLoadError(
            "verify.provider identity strings must be nonblank; blank: "
            + ", ".join(blank)
        )
    _validate_canonical_service_purl(
        values["model"],
        selector_label="verify.provider.model",
    )
    input_cost = _require_int(
        table,
        "input_cost_microusd_per_million_tokens",
        "verify.provider",
        minimum=0,
    )
    output_cost = _require_int(
        table,
        "output_cost_microusd_per_million_tokens",
        "verify.provider",
        minimum=0,
    )
    overhead = _require_int(table, "input_token_overhead", "verify.provider", minimum=0)
    cost_source = _require_string(table, "cost_rate_source", "verify.provider")
    return VerifyProviderSettings(
        backend_id=values["backend_id"],
        plugin_id=values["plugin_id"],
        plugin_distribution_name=values["plugin_distribution_name"],
        model=values["model"],
        adapter_model_id=values["adapter_model_id"],
        model_revision=values["model_revision"],
        capability_schema_version=_parse_capability_schema_version(
            table,
            "verify.provider",
        ),
        capability_revision=values["capability_revision"],
        request_constraints=_parse_request_constraints(
            table.get("request_constraints"),
            "verify.provider.request_constraints",
            authored=True,
        ),
        maximum_input_bytes=_require_int(
            table,
            "maximum_input_bytes",
            "verify.provider",
            minimum=1,
        ),
        input_cost_microusd_per_million_tokens=input_cost,
        output_cost_microusd_per_million_tokens=output_cost,
        input_token_overhead=overhead,
        cost_rate_source=cost_source,
    )


def _parse_verify_eval_settings(table: dict[str, Any]) -> VerifyEvalSettings:
    mode = _require_enum(table, "mode", "verify.eval", {"report", "enforce"})
    qualification_corpus = _require_string(table, "qualification_corpus", "verify.eval")
    qualification_corpus_sha256 = _require_qualification_hash(
        table, "qualification_corpus_sha256"
    )
    qualification_report = _require_string(table, "qualification_report", "verify.eval")
    qualification_report_sha256 = _require_qualification_hash(
        table, "qualification_report_sha256"
    )
    if bool(qualification_report.strip()) != bool(qualification_report_sha256):
        raise ConfigLoadError(
            "verify.eval qualification report path and hash must be both blank or "
            "both nonblank"
        )
    trials = _require_int(table, "trials", "verify.eval", minimum=1)
    interval_method = _require_enum(table, "interval_method", "verify.eval", {"wilson"})
    confidence_level = _require_number(
        table,
        "confidence_level",
        "verify.eval",
        minimum=0.0,
        maximum=1.0,
        minimum_exclusive=True,
        maximum_exclusive=True,
    )
    minimum_positive_units = _require_int(
        table, "minimum_positive_units", "verify.eval", minimum=0
    )
    minimum_negative_units = _require_int(
        table, "minimum_negative_units", "verify.eval", minimum=0
    )
    minimum_evidence_sufficiency_rate = _require_rate(
        table, "minimum_evidence_sufficiency_rate", "verify.eval"
    )
    minimum_conditional_precision = _require_rate(
        table, "minimum_conditional_precision", "verify.eval"
    )
    minimum_conditional_recall = _require_rate(
        table, "minimum_conditional_recall", "verify.eval"
    )
    minimum_end_to_end_recall = _require_rate(
        table, "minimum_end_to_end_recall", "verify.eval"
    )
    minimum_recall_lower_bound = _require_rate(
        table, "minimum_recall_lower_bound", "verify.eval"
    )
    maximum_false_positive_rate = _require_rate(
        table, "maximum_false_positive_rate", "verify.eval"
    )
    maximum_false_positive_upper_bound = _require_rate(
        table, "maximum_false_positive_upper_bound", "verify.eval"
    )
    maximum_indeterminate_rate = _require_rate(
        table, "maximum_indeterminate_rate", "verify.eval"
    )
    maximum_uncached_flip_rate = _require_rate(
        table, "maximum_uncached_flip_rate", "verify.eval"
    )
    require_all_critical = _require_bool(table, "require_all_critical", "verify.eval")

    minimum_rates = (
        minimum_evidence_sufficiency_rate,
        minimum_conditional_precision,
        minimum_conditional_recall,
        minimum_end_to_end_recall,
        minimum_recall_lower_bound,
    )
    maximum_rates = (
        maximum_false_positive_upper_bound,
        maximum_indeterminate_rate,
        maximum_uncached_flip_rate,
    )
    if mode == "enforce" and (
        not qualification_corpus.strip()
        or not qualification_corpus_sha256
        or trials < 2
        or minimum_positive_units <= 0
        or minimum_negative_units <= 0
        or any(value <= 0.0 for value in minimum_rates)
        or maximum_false_positive_rate != 0.0
        or any(value >= 1.0 for value in maximum_rates)
        or not require_all_critical
    ):
        raise ConfigLoadError(
            "verify.eval enforce mode requires a contained nonblank corpus path and "
            "canonical hash, at least two trials, positive sample floors and minimum "
            "thresholds, zero false-positive rate, maximum thresholds below one, and "
            "require_all_critical = true"
        )

    return VerifyEvalSettings(
        mode=mode,
        qualification_corpus=qualification_corpus,
        qualification_corpus_sha256=qualification_corpus_sha256,
        qualification_report=qualification_report,
        qualification_report_sha256=qualification_report_sha256,
        trials=trials,
        interval_method=interval_method,
        confidence_level=confidence_level,
        minimum_positive_units=minimum_positive_units,
        minimum_negative_units=minimum_negative_units,
        minimum_evidence_sufficiency_rate=minimum_evidence_sufficiency_rate,
        minimum_conditional_precision=minimum_conditional_precision,
        minimum_conditional_recall=minimum_conditional_recall,
        minimum_end_to_end_recall=minimum_end_to_end_recall,
        minimum_recall_lower_bound=minimum_recall_lower_bound,
        maximum_false_positive_rate=maximum_false_positive_rate,
        maximum_false_positive_upper_bound=maximum_false_positive_upper_bound,
        maximum_indeterminate_rate=maximum_indeterminate_rate,
        maximum_uncached_flip_rate=maximum_uncached_flip_rate,
        require_all_critical=require_all_critical,
    )


def _parse_obligation_settings(table: dict[str, Any]) -> ObligationSettings:
    roles_value = table.get("section_required_roles")
    if not isinstance(roles_value, list) or not all(
        isinstance(item, str) for item in roles_value
    ):
        raise ConfigLoadError(
            "obligations.section_required_roles must be an array of strings"
        )
    if len(roles_value) != len(set(roles_value)):
        raise ConfigLoadError(
            "obligations.section_required_roles must not contain duplicates"
        )
    invalid_roles = sorted(set(roles_value) - {"implementation", "test"})
    if invalid_roles:
        raise ConfigLoadError(
            "obligations.section_required_roles contains unknown roles: "
            + ", ".join(invalid_roles)
        )
    if "implementation" not in roles_value:
        raise ConfigLoadError(
            "obligations.section_required_roles must contain implementation"
        )
    roles = tuple(role for role in ("implementation", "test") if role in roles_value)

    page_size = _require_int(table, "page_size", "obligations", minimum=1)
    maximum_page_size = _require_int(
        table, "maximum_page_size", "obligations", minimum=1
    )
    maximum_response_bytes = _require_int(
        table, "maximum_response_bytes", "obligations", minimum=16_384
    )
    maximum_candidate_items = _require_int(
        table, "maximum_candidate_items", "obligations", minimum=1
    )
    maximum_catalog_items = _require_int(
        table, "maximum_catalog_items", "obligations", minimum=1
    )
    maximum_lexical_seeds = _require_int(
        table, "maximum_lexical_seeds", "obligations", minimum=1
    )
    maximum_snapshot_files = _require_int(
        table, "maximum_snapshot_files", "obligations", minimum=1
    )
    maximum_file_bytes = _require_int(
        table, "maximum_file_bytes", "obligations", minimum=1
    )
    maximum_snapshot_bytes = _require_int(
        table, "maximum_snapshot_bytes", "obligations", minimum=1
    )
    maximum_work_units = _require_int(
        table, "maximum_work_units", "obligations", minimum=1
    )
    maximum_packet_bytes = _require_int(
        table, "maximum_packet_bytes", "obligations", minimum=16_384
    )
    maximum_packet_report_bytes = _require_int(
        table, "maximum_packet_report_bytes", "obligations", minimum=16_384
    )
    maximum_call_seconds_value = table.get("maximum_call_seconds")
    if (
        isinstance(maximum_call_seconds_value, bool)
        or not isinstance(maximum_call_seconds_value, (int, float))
        or not math.isfinite(float(maximum_call_seconds_value))
        or float(maximum_call_seconds_value) <= 0.0
    ):
        raise ConfigLoadError(
            "obligations.maximum_call_seconds must be finite and positive"
        )
    maximum_call_seconds = float(maximum_call_seconds_value)
    snapshot_capture_attempts = _require_int(
        table, "snapshot_capture_attempts", "obligations", minimum=1
    )
    static_neighbor_depth = _require_int(
        table, "static_neighbor_depth", "obligations", minimum=0
    )

    if page_size > maximum_page_size:
        raise ConfigLoadError("obligations.page_size must be at most maximum_page_size")
    if maximum_snapshot_bytes < maximum_file_bytes:
        raise ConfigLoadError(
            "obligations.maximum_snapshot_bytes must be at least maximum_file_bytes"
        )
    if snapshot_capture_attempts > 10:
        raise ConfigLoadError(
            "obligations.snapshot_capture_attempts must be at most 10"
        )
    if static_neighbor_depth > 3:
        raise ConfigLoadError("obligations.static_neighbor_depth must be at most 3")

    return ObligationSettings(
        section_required_roles=roles,
        page_size=page_size,
        maximum_page_size=maximum_page_size,
        maximum_response_bytes=maximum_response_bytes,
        maximum_candidate_items=maximum_candidate_items,
        maximum_catalog_items=maximum_catalog_items,
        maximum_lexical_seeds=maximum_lexical_seeds,
        maximum_snapshot_files=maximum_snapshot_files,
        maximum_file_bytes=maximum_file_bytes,
        maximum_snapshot_bytes=maximum_snapshot_bytes,
        maximum_work_units=maximum_work_units,
        maximum_packet_bytes=maximum_packet_bytes,
        maximum_packet_report_bytes=maximum_packet_report_bytes,
        maximum_call_seconds=maximum_call_seconds,
        snapshot_capture_attempts=snapshot_capture_attempts,
        static_neighbor_depth=static_neighbor_depth,
    )


def _parse_required_kinds(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigLoadError(
            "analyze.required_kinds must be an array containing section, invariant, "
            "and/or suppression"
        )
    if len(value) != len(set(value)):
        raise ConfigLoadError("analyze.required_kinds must not contain duplicates")
    invalid = sorted(set(value) - {"section", "invariant", "suppression"})
    if invalid:
        raise ConfigLoadError(
            "analyze.required_kinds contains unknown kinds: " + ", ".join(invalid)
        )
    return tuple(
        kind for kind in ("section", "invariant", "suppression") if kind in value
    )


def _parse_dispositions(value: Any) -> tuple[SemanticDisposition, ...]:
    if not isinstance(value, list):
        raise ConfigLoadError("analyze.dispositions must be an array of tables")
    parsed: list[SemanticDisposition] = []
    identities: set[tuple[str, str, str, str]] = set()
    for index, raw in enumerate(value):
        name = f"analyze.dispositions[{index}]"
        table = _expect_table(raw, name)
        missing = sorted(_DISPOSITION_KEYS - set(table))
        if missing:
            raise ConfigLoadError(f"{name} is missing required key {missing[0]}")
        code = _require_string(table, "code", name)
        if code not in _SEMANTIC_CODES:
            raise ConfigLoadError(f"{name}.code must be a canonical long semantic code")
        packet_id = _require_string(table, "packet_id", name)
        if not packet_id.strip():
            raise ConfigLoadError(f"{name}.packet_id must be nonblank")
        packet_hash = _require_string(table, "packet_hash", name)
        if not is_sha256_hex(packet_hash):
            raise ConfigLoadError(
                f"{name}.packet_hash must be a canonical lowercase SHA-256"
            )
        finding_hash = _require_string(table, "finding_hash", name)
        if not is_sha256_hex(finding_hash):
            raise ConfigLoadError(
                f"{name}.finding_hash must be a canonical lowercase SHA-256"
            )
        status = _require_enum(table, "status", name, {"accepted", "rejected"})
        reason = _require_string(table, "reason", name)
        if not reason.strip():
            raise ConfigLoadError(f"{name}.reason must be nonblank")
        identity = (code, packet_id, packet_hash, finding_hash)
        if identity in identities:
            raise ConfigLoadError(f"duplicate disposition identity at {name}")
        identities.add(identity)
        parsed.append(
            SemanticDisposition(
                code=code,
                packet_id=packet_id,
                packet_hash=packet_hash,
                finding_hash=finding_hash,
                status=status,
                reason=reason,
            )
        )
    return tuple(parsed)


def _require_string(table: dict[str, Any], key: str, prefix: str) -> str:
    value = table.get(key)
    if not isinstance(value, str):
        raise ConfigLoadError(f"{prefix}.{key} must be a string")
    return value


def _require_bool(table: dict[str, Any], key: str, prefix: str) -> bool:
    value = table.get(key)
    if not isinstance(value, bool):
        raise ConfigLoadError(f"{prefix}.{key} must be a boolean")
    return value


def _require_int(table: dict[str, Any], key: str, prefix: str, *, minimum: int) -> int:
    value = table.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ConfigLoadError(f"{prefix}.{key} must be an integer at least {minimum}")
    return value


def _require_number(
    table: dict[str, Any],
    key: str,
    prefix: str,
    *,
    minimum: float,
    maximum: float,
    minimum_exclusive: bool = False,
    maximum_exclusive: bool = False,
) -> float:
    value = table.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigLoadError(f"{prefix}.{key} must be a finite number")
    parsed = float(value)
    below = parsed <= minimum if minimum_exclusive else parsed < minimum
    above = parsed >= maximum if maximum_exclusive else parsed > maximum
    if not math.isfinite(parsed) or below or above:
        left = "greater than" if minimum_exclusive else "at least"
        right = "less than" if maximum_exclusive else "at most"
        raise ConfigLoadError(
            f"{prefix}.{key} must be finite, {left} {minimum}, and {right} {maximum}"
        )
    return parsed


def _require_rate(table: dict[str, Any], key: str, prefix: str) -> float:
    return _require_number(
        table,
        key,
        prefix,
        minimum=0.0,
        maximum=1.0,
    )


def _require_qualification_hash(table: dict[str, Any], key: str) -> str:
    value = _require_string(table, key, "verify.eval")
    if value and not is_prefixed_sha256(value):
        raise ConfigLoadError(
            f"verify.eval.{key} must be blank or sha256:<64 lowercase hex>"
        )
    return value


def _require_enum(
    table: dict[str, Any],
    key: str,
    prefix: str,
    choices: set[str],
) -> str:
    value = table.get(key)
    if not isinstance(value, str) or value not in choices:
        rendered = ", ".join(sorted(choices))
        raise ConfigLoadError(f"{prefix}.{key} must be one of {rendered}")
    return value


def _raw_policy_rules(raw: dict[str, Any]) -> list[Any]:
    diagnostics = raw.get("diagnostics")
    if not isinstance(diagnostics, dict):
        return []
    rules = diagnostics.get("levels")
    return rules if isinstance(rules, list) else []


def _resolve_excludes(raw: dict[str, Any]) -> tuple[str, ...]:
    exclude = raw.get("exclude")
    extend_exclude = raw.get("extend_exclude")
    if exclude is None:
        patterns = list(DEFAULT_EXCLUDES)
    else:
        patterns = list(_require_str_list(exclude, "exclude"))
    if extend_exclude is not None:
        patterns.extend(_require_str_list(extend_exclude, "extend_exclude"))
    return tuple(patterns)


def _expect_table(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        msg = f"[{name}] must be a table"
        raise ConfigLoadError(msg)
    return value


def _optional_str_tuple(value: Any, field_name: str) -> tuple[str, ...] | None:
    if value is None:
        return None
    return tuple(_require_str_list(value, field_name))


def _require_str_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        msg = f"{field_name} must be an array of strings"
        raise ConfigLoadError(msg)
    return value


def _validate_unknown_keys(raw: dict[str, Any], config_path: Path) -> None:
    allow_unknown = raw.get("allow_unknown_keys", False)
    if not isinstance(allow_unknown, bool):
        msg = f"allow_unknown_keys must be a boolean in {config_path}"
        raise ConfigLoadError(msg)
    unknown = _unknown_key_messages(raw, config_path)
    if unknown:
        if not allow_unknown:
            raise ConfigLoadError(unknown[0])
        for message in unknown:
            print(f"warning: {message}", file=sys.stderr)


def _validate_config_layers(
    merged: dict[str, Any],
    layers: tuple[_ConfigLayer, ...],
    effective_path: Path,
) -> None:
    """Validate unknown keys before array replacement can hide parent errors."""

    allow_unknown = merged.get("allow_unknown_keys", False)
    if not isinstance(allow_unknown, bool):
        raise ConfigLoadError(
            f"allow_unknown_keys must be a boolean in {effective_path}"
        )
    for layer in layers:
        _validate_analyze_descriptor_file_layer(layer.body, layer.path)
        _validate_verify_provider_file_layer(layer.body, layer.path)
        for message in _unknown_key_messages(layer.body, layer.path):
            if not allow_unknown:
                raise ConfigLoadError(message)
            print(f"warning: {message}", file=sys.stderr)


def _validate_analyze_descriptor_file_layer(
    raw: dict[str, Any],
    path: Path,
) -> None:
    """Reject descriptor inheritance before merged values can hide it."""

    analyze = raw.get("analyze")
    if not isinstance(analyze, dict):
        return
    supplied = _ANALYZE_FLAT_DESCRIPTOR_KEYS.intersection(analyze)
    required_supplied = _ANALYZE_REQUIRED_FLAT_DESCRIPTOR_KEYS.intersection(analyze)
    if supplied and required_supplied != _ANALYZE_REQUIRED_FLAT_DESCRIPTOR_KEYS:
        missing = sorted(_ANALYZE_REQUIRED_FLAT_DESCRIPTOR_KEYS - required_supplied)
        raise ConfigLoadError(
            f"analyze flat descriptor in {path} must be complete in one file "
            f"layer; missing: {', '.join(missing)}"
        )
    if supplied:
        for key in (
            "model",
            "backend_id",
            "plugin_id",
            "plugin_distribution_name",
            "model_revision",
            "cost_rate_source",
        ):
            value = analyze.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ConfigLoadError(
                    f"analyze flat descriptor {key} in {path} must be nonblank"
                )
        adapter_model_id = analyze.get("adapter_model_id")
        if adapter_model_id is not None and (
            not isinstance(adapter_model_id, str) or not adapter_model_id.strip()
        ):
            raise ConfigLoadError(
                f"analyze flat descriptor adapter_model_id in {path} "
                "must be nonblank when supplied"
            )
        _parse_capability_schema_version(analyze, "analyze")
        _parse_capability_revision(analyze, "analyze")
        _parse_request_constraints(
            analyze.get("request_constraints"),
            "analyze.request_constraints",
            authored=True,
        )
        _require_int(analyze, "maximum_input_bytes", "analyze", minimum=1)
    # Parse each layer independently so a later catalog child cannot inherit
    # omitted fields from an earlier descriptor with the same selector.
    _parse_analyze_model_catalog(analyze.get("models"))


def _validate_verify_provider_file_layer(
    raw: dict[str, Any],
    path: Path,
) -> None:
    """Reject partial verifier overrides before deep merge can hide them."""

    verify = raw.get("verify")
    if not isinstance(verify, dict) or "provider" not in verify:
        return
    provider = verify.get("provider")
    if not isinstance(provider, dict):
        raise ConfigLoadError(f"verify.provider in {path} must be a table")
    supplied = set(provider)
    missing = sorted(_VERIFY_PROVIDER_KEYS - supplied)
    unknown = sorted(supplied - _VERIFY_PROVIDER_KEYS)
    if missing:
        raise ConfigLoadError(
            f"verify.provider in {path} must be complete in one file layer; "
            f"missing: {', '.join(missing)}"
        )
    if unknown:
        raise ConfigLoadError(
            f"unknown config key `verify.provider.{unknown[0]}` in {path}"
        )
    _parse_verify_provider(provider)


def _analyze_nested_unknown_keys(value: dict[str, Any], path: Path) -> list[str]:
    messages: list[str] = []
    dispositions = value.get("dispositions")
    if isinstance(dispositions, list):
        for index, disposition in enumerate(dispositions):
            messages.extend(
                f"unknown config key `analyze.dispositions[{index}].{sub}` in {path}"
                for sub in _unused_table_keys(disposition, _DISPOSITION_KEYS)
            )
    models = value.get("models")
    if isinstance(models, dict):
        for selector, descriptor in models.items():
            if isinstance(descriptor, dict):
                messages.extend(
                    f"unknown config key `analyze.models.{selector}.{sub}` in {path}"
                    for sub in _unused_table_keys(
                        descriptor,
                        _ANALYZE_CATALOG_DESCRIPTOR_KEYS,
                    )
                )
    return messages


def _lint_nested_unknown_keys(value: dict[str, Any], path: Path) -> list[str]:
    suppressions = value.get("suppressions")
    if not isinstance(suppressions, list):
        return []
    return [
        f"unknown config key `lint.suppressions[{index}].{sub}` in {path}"
        for index, suppression in enumerate(suppressions)
        for sub in _unused_table_keys(suppression, _SUPPRESSION_KEYS)
    ]


def _coverage_nested_unknown_keys(value: dict[str, Any], path: Path) -> list[str]:
    messages: list[str] = []
    exemptions = value.get("exemptions")
    if isinstance(exemptions, list):
        for index, exemption in enumerate(exemptions):
            if isinstance(exemption, dict):
                messages.extend(
                    f"unknown config key `coverage.exemptions[{index}].{sub}` in {path}"
                    for sub in _unused_table_keys(exemption, _COVERAGE_EXEMPTION_KEYS)
                )
    floors = value.get("floors")
    if isinstance(floors, dict):
        for scope, floor in floors.items():
            if isinstance(floor, dict):
                messages.extend(
                    f"unknown config key `coverage.floors.{scope}.{sub}` in {path}"
                    for sub in _unused_table_keys(floor, _COVERAGE_FLOOR_KEYS)
                )
    return messages


def _verify_nested_unknown_keys(value: dict[str, Any], path: Path) -> list[str]:
    messages: list[str] = []
    provider = value.get("provider")
    if isinstance(provider, dict):
        messages.extend(
            f"unknown config key `verify.provider.{sub}` in {path}"
            for sub in _unused_table_keys(provider, _VERIFY_PROVIDER_KEYS)
        )
    evaluation = value.get("eval")
    if isinstance(evaluation, dict):
        messages.extend(
            f"unknown config key `verify.eval.{sub}` in {path}"
            for sub in _unused_table_keys(evaluation, _VERIFY_EVAL_KEYS)
        )
    return messages


def _diagnostics_nested_unknown_keys(value: dict[str, Any], path: Path) -> list[str]:
    rules = value.get("levels")
    if not isinstance(rules, list):
        return []
    return [
        f"unknown config key `diagnostics.levels[{index}].{sub}` in {path}"
        for index, rule in enumerate(rules)
        for sub in _unused_table_keys(rule, frozenset({"select", "level"}))
    ]


def _nested_unknown_key_messages(
    table_name: str, value: dict[str, Any], config_path: Path
) -> list[str]:
    parser = {
        "analyze": _analyze_nested_unknown_keys,
        "lint": _lint_nested_unknown_keys,
        "coverage": _coverage_nested_unknown_keys,
        "verify": _verify_nested_unknown_keys,
        "diagnostics": _diagnostics_nested_unknown_keys,
    }.get(table_name)
    return [] if parser is None else parser(value, config_path)


def _unknown_key_messages(raw: dict[str, Any], config_path: Path) -> list[str]:
    """[CFG-8] unknown-key inventory, each message naming key and file."""

    messages: list[str] = []
    for key, value in raw.items():
        if key in _TABLE_KEYS:
            if isinstance(value, dict):
                allowed = _table_key_names(key)
                if key == "diagnostics" and _is_packaged_default_path(config_path):
                    allowed = allowed | frozenset({"registry"})
                messages.extend(
                    f"unknown config key `{key}.{sub}` in {config_path}"
                    for sub in _unused_table_keys(value, allowed)
                )
                messages.extend(_nested_unknown_key_messages(key, value, config_path))
            continue
        if key in _TOP_LEVEL_KEYS:
            continue
        messages.append(f"unknown config key `{key}` in {config_path}")
    return messages


def _is_packaged_default_path(path: Path) -> bool:
    return path.resolve() == PACKAGED_DEFAULTS_PATH


def _table_key_names(table_name: str) -> frozenset[str]:
    return _TABLE_KEY_NAMES.get(table_name, frozenset())


def _parse_lint_settings(
    lint_table: dict[str, Any],
    *,
    suppression_rule_source: str,
    allow_unknown: bool,
) -> LintSettings:
    warn_unused = lint_table.get("warn_unused_ignores", True)
    if not isinstance(warn_unused, bool):
        msg = "lint.warn_unused_ignores must be a boolean"
        raise ConfigLoadError(msg)
    require_declarations = lint_table.get("require_suppression_declarations", False)
    if not isinstance(require_declarations, bool):
        raise ConfigLoadError("lint.require_suppression_declarations must be a boolean")
    per_file = _parse_ignore_table(
        lint_table.get("per-file-ignores"),
        "lint.per-file-ignores",
    )
    per_section = _parse_ignore_table(
        lint_table.get("per-section-ignores"),
        "lint.per-section-ignores",
    )
    return LintSettings(
        warn_unused_ignores=warn_unused,
        require_suppression_declarations=require_declarations,
        per_file_ignores=per_file,
        per_section_ignores=per_section,
        suppressions=_parse_structured_suppressions(
            lint_table.get("suppressions"),
            source=suppression_rule_source,
            allow_unknown=allow_unknown,
        ),
    )


def _parse_suppression_path(value: Any, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value.startswith("/")
        or value.startswith("./")
        or "\\" in value
        or "//" in value
        or any(char in value for char in "\x00\r\n\t")
        or ".." in PurePosixPath(value).parts
    ):
        raise ConfigLoadError(
            f"{label}.path must be one nonblank repo-relative POSIX glob"
        )
    return value


def _parse_suppression_sections(raw: Any, *, label: str) -> tuple[str, ...]:
    sections = _require_str_list(raw, f"{label}.sections")
    if len(sections) != len(set(sections)):
        raise ConfigLoadError(f"{label}.sections must not contain duplicates")
    invalid = sorted(
        section for section in sections if SECTION_ID_RE.fullmatch(section) is None
    )
    if invalid:
        raise ConfigLoadError(
            f"{label}.sections contains invalid section IDs: " + ", ".join(invalid)
        )
    return tuple(sorted(sections))


def _parse_suppression_codes(raw: Any, *, label: str) -> tuple[str, ...]:
    codes = _require_str_list(raw, f"{label}.codes")
    canonical = tuple(
        canonicalize_code(code) if is_ordinary_diagnostic_code(code) else code
        for code in codes
    )
    if len(canonical) != len(set(canonical)):
        raise ConfigLoadError(
            f"{label}.codes must not contain duplicate diagnostic identities"
        )
    return tuple(sorted(canonical))


def _parse_structured_suppression(
    raw: Any,
    *,
    position: int,
    source: str,
    allow_unknown: bool,
) -> SuppressionRule:
    label = f"lint.suppressions[{position}]"
    if not isinstance(raw, dict):
        raise ConfigLoadError(f"{label} must be a table")
    missing = sorted(_SUPPRESSION_KEYS - set(raw))
    extra = sorted(set(raw) - _SUPPRESSION_KEYS)
    if missing:
        raise ConfigLoadError(f"{label} missing required keys: {', '.join(missing)}")
    if extra and not allow_unknown:
        raise ConfigLoadError(f"{label} has unknown keys: {', '.join(extra)}")
    raw_mechanism = raw["mechanism"]
    if not isinstance(raw_mechanism, str) or raw_mechanism not in {"ignore", "meta"}:
        raise ConfigLoadError(f"{label}.mechanism must be 'ignore' or 'meta'")
    mechanism = cast(Literal["ignore", "meta"], raw_mechanism)
    path = _parse_suppression_path(raw["path"], label=label)
    sections = _parse_suppression_sections(raw["sections"], label=label)
    canonical_codes = _parse_suppression_codes(raw["codes"], label=label)
    declaration = raw["declaration"]
    if not is_valid_suppression_reference(declaration):
        raise ConfigLoadError(
            f"{label}.declaration must be repo/relative/spec.md#SUP-ID"
        )
    if mechanism == "ignore" and not canonical_codes:
        raise ConfigLoadError(f"{label} ignore rules require at least one code")
    if mechanism == "meta" and (sections or canonical_codes):
        raise ConfigLoadError(
            f"{label} meta rules require sections = [] and codes = []"
        )
    return SuppressionRule(
        mechanism=mechanism,
        provenance=(
            "meta"
            if mechanism == "meta"
            else ("config_file" if not sections else "config_section")
        ),
        path=path,
        sections=sections,
        codes=canonical_codes,
        declaration=declaration,
        origin=SuppressionOrigin(source=source, position=position),
    )


def _parse_structured_suppressions(
    value: Any,
    *,
    source: str,
    allow_unknown: bool,
) -> tuple[SuppressionRule, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ConfigLoadError("lint.suppressions must be an array of tables")
    return tuple(
        _parse_structured_suppression(
            raw,
            position=position,
            source=source,
            allow_unknown=allow_unknown,
        )
        for position, raw in enumerate(value)
    )


def _parse_ignore_table(value: Any, field_name: str) -> dict[str, tuple[str, ...]]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        msg = f"{field_name} must be a table"
        raise ConfigLoadError(msg)
    parsed: dict[str, tuple[str, ...]] = {}
    for path_key, codes in value.items():
        if not isinstance(path_key, str):
            msg = f"{field_name} keys must be strings"
            raise ConfigLoadError(msg)
        parsed[path_key] = tuple(_require_str_list(codes, f"{field_name}.{path_key}"))
    return parsed


def _merged_meta_globs(profile_table: dict[str, Any]) -> tuple[str, ...] | None:
    """EXC §3.2: `process_spec_globs` is a v1 alias of `meta_spec_globs`;
    both keys merge at load time."""

    meta = _optional_str_tuple(
        profile_table.get("meta_spec_globs"), "profile.meta_spec_globs"
    )
    process = _optional_str_tuple(
        profile_table.get("process_spec_globs"), "profile.process_spec_globs"
    )
    if meta is None and process is None:
        return None
    return tuple(dict.fromkeys((meta or ()) + (process or ())))


def _unused_table_keys(table: Any, allowed: frozenset[str]) -> list[str]:
    if not isinstance(table, dict):
        return []
    return [key for key in table if key not in allowed]
