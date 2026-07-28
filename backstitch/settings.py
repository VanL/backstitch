"""TOML configuration discovery and resolution.

Spec: docs/specs/03-backstitch-configuration.md [CFG-1], [CFG-2], [CFG-3], [CFG-4],
[CFG-5], [CFG-5.1], [CFG-6], [CFG-6.6], [CFG-8]
Spec: docs/specs/02-backstitch-core.md [SC-5.1]
Spec: docs/specs/04-backstitch-traceability-exclusions.md [EXC-3], [EXC-6]
Spec: docs/specs/02-backstitch-core.md [SC-13]
Spec: docs/specs/06-semantic-gates.md [SEM-9]
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
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Literal

from backstitch.config import uncontained_test_root
from backstitch.diagnostics import (
    DiagnosticConfigError,
    DiagnosticsSettings,
    default_policy,
    default_registry,
    load_default_config_raw,
    parse_policy,
    policy_to_dict,
    resolved_policy_to_dict,
)
from backstitch.grammar import is_prefixed_sha256, is_sha256_hex

DEFAULT_EXCLUDES: tuple[str, ...] = tuple(load_default_config_raw()["exclude"])
PACKAGED_DEFAULTS_LAYER = "packaged:backstitch/defaults.toml"
PACKAGED_DEFAULTS_PATH = Path(__file__).with_name("defaults.toml").resolve()
MAXIMUM_CONFIG_CHAIN_FILES = 64
MAXIMUM_CONFIG_FILE_BYTES = 1_000_000
MAXIMUM_CONFIG_CHAIN_BYTES = 5_000_000

_TOP_LEVEL_KEYS = frozenset(
    {
        "defaults",
        "profile",
        "extend",
        "allow_unknown_keys",
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
    {"warn_unused_ignores", "per-file-ignores", "per-section-ignores"}
)
_CHECK_KEYS = frozenset({"format", "warnings_as_errors", "output"})
_PACKETS_KEYS = frozenset({"output"})
_ANALYZE_KEYS = frozenset(
    {
        "backend_id",
        "plugin_id",
        "plugin_distribution_name",
        "model",
        "model_revision",
        "concurrency",
        "json_mode",
        "temperature",
        "seed",
        "max_tokens",
        "cache_path",
        "cache_mode",
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
        "model_revision",
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
    }
)
_TARGET_ROOT_KEYS = frozenset({"weft"})
_DIAGNOSTICS_KEYS = frozenset(
    {"default_level", "fail_on", "suppressible_levels", "levels"}
)
_GENERIC_OPTION_LEAVES = frozenset(
    {
        "exclude",
        "extend_exclude",
        *{f"profile.{key}" for key in _PROFILE_KEYS},
        "lint.warn_unused_ignores",
        *{f"check.{key}" for key in _CHECK_KEYS},
        *{f"analyze.{key}" for key in _ANALYZE_KEYS},
        "verify.enabled",
        *{
            f"verify.{key}"
            for key in _VERIFY_KEYS
            if key not in {"enabled", "provider", "eval"}
        },
        *{f"verify.provider.{key}" for key in _VERIFY_PROVIDER_KEYS},
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
    per_file_ignores: dict[str, tuple[str, ...]] = field(default_factory=dict)
    per_section_ignores: dict[str, tuple[str, ...]] = field(default_factory=dict)


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
class SemanticDisposition:
    code: str
    packet_id: str
    packet_hash: str
    finding_hash: str
    status: str
    reason: str


@dataclass(frozen=True, slots=True)
class AnalyzeSettings:
    backend_id: str = "llm"
    plugin_id: str = ""
    plugin_distribution_name: str = ""
    model: str = ""
    model_revision: str = ""
    concurrency: int = 1
    json_mode: str = "prefer"
    temperature: float = 0.0
    seed: int = 42
    max_tokens: int = 512
    cache_path: str = ".backstitch/semantic-cache"
    cache_mode: str = "off"
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
    model_revision: str
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
    temperature: float
    seed: int
    max_tokens: int
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
    exclude: tuple[str, ...] = DEFAULT_EXCLUDES
    profile_overrides: ProfileSettings = field(default_factory=ProfileSettings)
    lint: LintSettings = field(default_factory=LintSettings)
    check: CheckSettings = field(default_factory=CheckSettings)
    packets: PacketsSettings = field(default_factory=PacketsSettings)
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


def resolve_config(
    anchor: Path,
    *,
    home: Path | None = None,
    explicit: Path | None = None,
    use_repo_config: bool = True,
    environment: Mapping[str, str] | None = None,
    cli_options: Sequence[tuple[str, str]] = (),
    cli_overrides: Mapping[str, Any] | None = None,
) -> BackstitchSettings:
    """Resolve one immutable invocation-scoped settings snapshot ([CFG-5.1])."""

    raw = copy.deepcopy(load_default_config_raw())
    _expand_raw_paths(raw, PACKAGED_DEFAULTS_PATH.parent)
    layers = [PACKAGED_DEFAULTS_LAYER]
    packaged_rules = _raw_policy_rules(raw)
    policy_origins = [
        PolicyRuleOrigin(source=PACKAGED_DEFAULTS_LAYER, position=index)
        for index in range(len(packaged_rules))
    ]
    config_layer_identities: list[ConfigLayerIdentity] = []
    explicit_analyze_keys: set[str] = set()
    analyze_model_source = "llm default model"
    config_path: Path | None = None
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
            repo_raw, warnings, repo_layers = _load_config_chain(
                config_path,
                set(),
                budget,
                preloaded,
            )
            for warning in warnings:
                print(f"warning: {warning}", file=sys.stderr)
            _validate_config_layers(repo_raw, repo_layers, config_path)
            raw = _merge_config_layers(raw, repo_raw)
            for layer in repo_layers:
                source = str(layer.path)
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
    environment_overlay = _environment_config_overlay(
        os.environ if environment is None else environment
    )
    cli_overlay = _cli_config_overlay(
        cli_options,
        cli_overrides=cli_overrides or {},
    )
    if _nested_value(environment_overlay, "analyze", "model") is not None:
        analyze_model_source = "LLM_MODEL environment variable"
    if any(key == "analyze.model" for key, _value in cli_options):
        analyze_model_source = "--option analyze.model"
    if "analyze.model" in (cli_overrides or {}):
        analyze_model_source = "--model"
    configured_model = _nested_value(raw, "analyze", "model")
    for overlay, source in (
        (environment_overlay, "environment"),
        (cli_overlay, "cli"),
    ):
        _expand_raw_paths(overlay, Path.cwd())
        _validate_overlay_traversal(raw, overlay)
        raw = _merge_config_layers(raw, overlay)
        analyze = overlay.get("analyze")
        if isinstance(analyze, dict):
            explicit_analyze_keys.update(analyze)
        policy_origins.extend(
            PolicyRuleOrigin(source=source, position=index)
            for index in range(len(_raw_policy_rules(overlay)))
        )
    _validate_model_override_identity(
        raw,
        configured_model=configured_model,
        override_supplied=(
            _nested_value(environment_overlay, "analyze", "model") is not None
            or _nested_value(cli_overlay, "analyze", "model") is not None
        ),
    )
    settings = _parse_settings(
        raw,
        source_path=config_path or PACKAGED_DEFAULTS_PATH,
        effective_config_path=config_path,
        config_layers=tuple(layers),
        config_layer_identities=tuple(config_layer_identities),
        policy_rule_origins=tuple(policy_origins),
        analyze_model_source=analyze_model_source,
        explicit_analyze_keys=frozenset(explicit_analyze_keys),
        validate_unknown_keys=config_path is None,
    )
    invalid_test_root = uncontained_test_root(
        anchor.resolve(),
        settings.profile_overrides.code_roots or (),
        settings.profile_overrides.test_roots or (),
    )
    if invalid_test_root is not None:
        msg = (
            f"test root {invalid_test_root!r} must be equal to or nested under a"
            " final effective code root"
        )
        raise ConfigLoadError(msg)
    return settings


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


def _validate_model_override_identity(
    raw: dict[str, Any],
    *,
    configured_model: Any,
    override_supplied: bool,
) -> None:
    if not override_supplied:
        return
    effective_model = _nested_value(raw, "analyze", "model")
    if (
        not isinstance(configured_model, str)
        or not configured_model.strip()
        or not isinstance(effective_model, str)
        or effective_model == configured_model
    ):
        return
    cache_mode = _nested_value(raw, "analyze", "cache_mode")
    verifier_uses_analyze = (
        _nested_value(raw, "verify", "enabled") is True
        and _nested_value(raw, "verify", "provider_source") == "analyze"
    )
    if cache_mode in {"read-write", "require"} or verifier_uses_analyze:
        raise ConfigLoadError(
            "cached model override disagrees with configured model/revision pair"
        )


def settings_to_json(settings: BackstitchSettings) -> str:
    payload = {
        "config_path": (
            str(settings.config_path) if settings.config_path is not None else None
        ),
        "profile": settings.profile,
        "allow_unknown_keys": settings.allow_unknown_keys,
        "exclude": list(settings.exclude),
        "profile_overrides": asdict(settings.profile_overrides),
        "lint": {
            "warn_unused_ignores": settings.lint.warn_unused_ignores,
            "per_file_ignores": {
                key: list(codes)
                for key, codes in settings.lint.per_file_ignores.items()
            },
            "per_section_ignores": {
                key: list(codes)
                for key, codes in settings.lint.per_section_ignores.items()
            },
        },
        "check": asdict(settings.check),
        "packets": asdict(settings.packets),
        "analyze": asdict(settings.analyze),
        "verify": asdict(settings.verify),
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
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def is_excluded(rel_path: str, excludes: tuple[str, ...]) -> bool:
    normalized = rel_path.replace("\\", "/")
    parts = set(normalized.split("/"))
    for pattern in excludes:
        if fnmatch(normalized, pattern) or fnmatch(normalized, f"**/{pattern}"):
            return True
        if pattern in parts:
            return True
        if normalized.startswith(f"{pattern}/") or normalized == pattern:
            return True
    return False


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


def expand_path_value(value: str, *, base_dir: Path) -> str:
    expanded = _expand_user_and_env(value)
    path = Path(expanded)
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
    # Lazy import avoids the settings -> snapshot -> settings import cycle;
    # repository_snapshot remains the sole stat-identity implementation owner.
    from backstitch.repository_snapshot import _file_stat_identity

    return _file_stat_identity(value)


def _read_config_source(path: Path, budget: _ConfigReadBudget) -> _ConfigSource:
    """Read one stable config layer exactly once under bootstrap ceilings."""

    # Local import avoids the repository_snapshot -> settings bootstrap cycle.
    from backstitch.repository_snapshot import StableReadError, read_regular_nofollow

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
        raw, observed = read_regular_nofollow(
            path.parent,
            path.name,
            expected_stat=before,
            maximum_bytes=MAXIMUM_CONFIG_FILE_BYTES,
        )
    except ConfigLoadError:
        raise
    except (OSError, StableReadError) as exc:
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
            )
        elif (
            key in merged and isinstance(merged[key], dict) and isinstance(value, dict)
        ):
            merged[key] = _merge_config_layers(
                merged[key],
                value,
                path=current_path,
            )
        else:
            merged[key] = value
    return merged


def _expand_raw_paths(body: dict[str, Any], base_dir: Path) -> None:
    """Expand path values against the file that DEFINED them (CFG §2).

    Must run per file BEFORE `extend` merging: a parent's relative
    `check.output` anchors at the parent's directory, not at whichever
    child extended it. expand_path_value is idempotent on the absolute
    results, so the later _parse_settings expansion is a no-op for these.
    """

    for table_name, key in (
        ("check", "output"),
        ("packets", "output"),
        ("analyze", "cache_path"),
        ("verify", "cache_path"),
    ):
        table = body.get(table_name)
        if (
            isinstance(table, dict)
            and isinstance(table.get(key), str)
            and table[key].strip()
        ):
            table[key] = expand_path_value(table[key], base_dir=base_dir)
    roots = body.get("target_roots")
    if isinstance(roots, dict):
        for name, value in roots.items():
            if isinstance(value, str):
                roots[name] = expand_path_value(value, base_dir=base_dir)
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
                    )


def _expand_contained_config_path(
    value: str,
    *,
    base_dir: Path,
    field_name: str,
) -> str:
    expanded = Path(_expand_user_and_env(value))
    base = base_dir.resolve()
    candidate = (expanded if expanded.is_absolute() else base / expanded).resolve()
    if candidate != base and not candidate.is_relative_to(base):
        raise ConfigLoadError(f"{field_name} must be contained by its config directory")
    return str(candidate)


def _load_config_chain(
    path: Path,
    seen: set[Path],
    budget: _ConfigReadBudget | None = None,
    preloaded: dict[Path, _ConfigSource] | None = None,
) -> tuple[dict[str, Any], list[str], tuple[_ConfigLayer, ...]]:
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
        return body, warnings, (layer,)

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

    parent_body, parent_warnings, parent_layers = _load_config_chain(
        parent_path,
        seen,
        budget,
        preloaded,
    )
    warnings.extend(parent_warnings)
    merged = _merge_config_layers(parent_body, body)
    merged.pop("extend", None)
    return (
        merged,
        warnings,
        (*parent_layers, layer),
    )


def _parse_settings(
    raw: dict[str, Any],
    *,
    source_path: Path,
    effective_config_path: Path | None,
    config_layers: tuple[str, ...],
    config_layer_identities: tuple[ConfigLayerIdentity, ...],
    policy_rule_origins: tuple[PolicyRuleOrigin, ...],
    analyze_model_source: str,
    explicit_analyze_keys: frozenset[str],
    validate_unknown_keys: bool,
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

    profile_value = raw.get("profile")
    if isinstance(profile_value, dict):
        profile_table = profile_value
        profile_name = profile_value.get("name")
        if profile_name is not None and not isinstance(profile_name, str):
            msg = f"profile.name must be a string in {source_path}"
            raise ConfigLoadError(msg)
        if profile_name is not None:
            # [CFG-8]: an unknown built-in profile name fails at load.
            from backstitch.profiles import get_profile

            try:
                get_profile(profile_name)
            except ValueError as exc:
                msg = f"{exc} in {source_path}"
                raise ConfigLoadError(msg) from exc
    elif profile_value is None:
        profile_name = None
        profile_table = {}
    else:
        # CFG §6.1: the only profile-name spelling is [profile].name; TOML
        # cannot represent both a top-level string and a [profile] table, so
        # the string form is rejected rather than given a "wins" rule.
        msg = (
            f"unknown config key `profile` in {source_path}: the profile"
            ' name is spelled [profile] name = "..."'
        )
        raise ConfigLoadError(msg)

    excludes = _resolve_excludes(raw)

    check_table = _expect_table(raw.get("check"), "check")
    packets_table = _expect_table(raw.get("packets"), "packets")
    analyze_table = _expect_table(raw.get("analyze"), "analyze")
    verify_table = _expect_table(raw.get("verify"), "verify")
    obligations_table = _expect_table(raw.get("obligations"), "obligations")
    target_table = _expect_table(raw.get("target_roots"), "target_roots")
    lint_table = _expect_table(raw.get("lint"), "lint")
    diagnostics_table = _expect_table(raw.get("diagnostics"), "diagnostics")

    # CFG §6.4: [packets].output is stored for forward compatibility; the
    # CLI still requires --output in v1 -- parsed here so the schema key is
    # never silently dead.
    packets_output = packets_table.get("output")
    if packets_output is not None and not isinstance(packets_output, str):
        msg = f"packets.output must be a string in {source_path}"
        raise ConfigLoadError(msg)
    if packets_output is not None:
        packets_output = expand_path_value(packets_output, base_dir=source_path.parent)

    def _roots(key: str) -> tuple[str, ...] | None:
        # CFG §4.3: roots support `~` and env expansion (but stay
        # repo-relative -- see expand_root_value).
        values = _optional_str_tuple(profile_table.get(key), f"profile.{key}")
        if values is None:
            return None
        return tuple(expand_root_value(v) for v in values)

    profile_settings = ProfileSettings(
        spec_roots=_roots("spec_roots"),
        plan_roots=_roots("plan_roots"),
        code_roots=_roots("code_roots"),
        test_roots=_roots("test_roots"),
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

    lint_settings = _parse_lint_settings(lint_table)

    check_format = check_table.get("format")
    if check_format is not None and check_format not in {"text", "json"}:
        msg = "check.format must be 'text' or 'json'"
        raise ConfigLoadError(msg)

    warnings_as_errors = check_table.get("warnings_as_errors")
    if warnings_as_errors is not None and not isinstance(warnings_as_errors, bool):
        msg = "check.warnings_as_errors must be a boolean"
        raise ConfigLoadError(msg)

    analyze_settings = _parse_analyze_settings(
        analyze_table,
        source_path=source_path,
        explicit_analyze_keys=explicit_analyze_keys,
    )
    verify_settings = _parse_verify_settings(
        verify_table,
        source_path=source_path,
        analyze=analyze_settings,
        explicit_analyze_keys=explicit_analyze_keys,
    )
    obligation_settings = _parse_obligation_settings(obligations_table)

    weft_root = target_table.get("weft")
    if weft_root is not None:
        if not isinstance(weft_root, str):
            msg = "target_roots.weft must be a string"
            raise ConfigLoadError(msg)
        weft_root = expand_path_value(weft_root, base_dir=source_path.parent)

    check_output = check_table.get("output")
    if check_output is not None and not isinstance(check_output, str):
        msg = "check.output must be a string"
        raise ConfigLoadError(msg)
    if check_output is not None:
        check_output = expand_path_value(check_output, base_dir=source_path.parent)

    try:
        diagnostics = parse_policy(
            diagnostics_table,
            registry=default_registry(),
            source=str(source_path),
            allow_unknown=allow_unknown,
        )
    except DiagnosticConfigError as exc:
        raise ConfigLoadError(str(exc)) from exc
    if len(policy_rule_origins) != len(diagnostics.levels):
        raise ConfigLoadError(
            "internal configuration error: diagnostic rule origins are not aligned"
        )

    return BackstitchSettings(
        profile=profile_name,
        allow_unknown_keys=allow_unknown,
        packets=PacketsSettings(output=packets_output),
        exclude=excludes,
        profile_overrides=profile_settings,
        lint=lint_settings,
        check=CheckSettings(
            format=check_format,
            warnings_as_errors=warnings_as_errors,
            output=check_output,
        ),
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
        analyze_model_source=analyze_model_source,
    )


def _parse_analyze_settings(
    table: dict[str, Any],
    *,
    source_path: Path,
    explicit_analyze_keys: frozenset[str],
) -> AnalyzeSettings:
    """Parse the exact semantic inference, cache, and budget surface."""

    backend_id = _require_string(table, "backend_id", "analyze")
    plugin_id = _require_string(table, "plugin_id", "analyze")
    plugin_distribution_name = _require_string(
        table, "plugin_distribution_name", "analyze"
    )
    model = _require_string(table, "model", "analyze")
    model_revision = _require_string(table, "model_revision", "analyze")
    concurrency = _require_int(table, "concurrency", "analyze", minimum=1)
    json_mode = _require_enum(
        table, "json_mode", "analyze", {"prefer", "require", "off"}
    )
    temperature = _require_number(
        table,
        "temperature",
        "analyze",
        minimum=0.0,
        maximum=2.0,
    )
    seed = _require_int(table, "seed", "analyze", minimum=0)
    max_tokens = _require_int(table, "max_tokens", "analyze", minimum=1)
    cache_path = _require_string(table, "cache_path", "analyze")
    if not cache_path.strip():
        raise ConfigLoadError("analyze.cache_path must be a nonblank path string")
    cache_path = expand_path_value(cache_path, base_dir=source_path.parent)
    cache_mode = _require_enum(
        table, "cache_mode", "analyze", {"off", "read-write", "require"}
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
        model_revision=model_revision,
        concurrency=concurrency,
        json_mode=json_mode,
        temperature=temperature,
        seed=seed,
        max_tokens=max_tokens,
        cache_path=cache_path,
        cache_mode=cache_mode,
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
    )


def _parse_verify_settings(
    table: dict[str, Any],
    *,
    source_path: Path,
    analyze: AnalyzeSettings,
    explicit_analyze_keys: frozenset[str],
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
    cache_path = expand_path_value(cache_path, base_dir=source_path.parent)
    cache_mode = _require_enum(
        table, "cache_mode", "verify", {"off", "read-write", "require"}
    )
    search_epochs = _parse_verify_search_epochs(table.get("search_epochs"))
    json_mode = _require_enum(
        table, "json_mode", "verify", {"prefer", "require", "off"}
    )
    temperature = _require_number(
        table,
        "temperature",
        "verify",
        minimum=0.0,
        maximum=2.0,
    )
    seed = _require_int(table, "seed", "verify", minimum=0)
    max_tokens = _require_int(table, "max_tokens", "verify", minimum=1)
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

    if required_verdicts != len(search_epochs):
        raise ConfigLoadError(
            "verify.required_verdicts must equal the length of verify.search_epochs"
        )
    if json_mode == "prefer" and cache_mode != "off":
        raise ConfigLoadError(
            "verify.json_mode = 'prefer' is allowed only with cache_mode = 'off'"
        )

    provider: VerifyProviderSettings | None
    if provider_source == "analyze":
        if "provider" in table:
            raise ConfigLoadError(
                "verify.provider must be absent when provider_source = 'analyze'"
            )
        provider = None
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
        if maximum_cost > 0:
            cost_keys = {
                "input_cost_microusd_per_million_tokens",
                "output_cost_microusd_per_million_tokens",
                "input_token_overhead",
            }
            missing = sorted(cost_keys - explicit_analyze_keys)
            if missing:
                raise ConfigLoadError(
                    "a positive verify.maximum_estimated_cost_microusd requires "
                    "explicit analyze rate and overhead values; missing: "
                    + ", ".join(missing)
                )
            if not analyze.cost_rate_source.strip():
                raise ConfigLoadError(
                    "a positive verify.maximum_estimated_cost_microusd requires "
                    "a nonblank analyze.cost_rate_source"
                )
    else:
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
    values = {
        key: _require_string(table, key, "verify.provider")
        for key in (
            "backend_id",
            "plugin_id",
            "plugin_distribution_name",
            "model",
            "model_revision",
        )
    }
    blank = [key for key, value in values.items() if not value.strip()]
    if blank:
        raise ConfigLoadError(
            "verify.provider identity strings must be nonblank; blank: "
            + ", ".join(blank)
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
        model_revision=values["model_revision"],
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
            "analyze.required_kinds must be an array containing section and/or invariant"
        )
    if len(value) != len(set(value)):
        raise ConfigLoadError("analyze.required_kinds must not contain duplicates")
    invalid = sorted(set(value) - {"section", "invariant"})
    if invalid:
        raise ConfigLoadError(
            "analyze.required_kinds contains unknown kinds: " + ", ".join(invalid)
        )
    return tuple(kind for kind in ("section", "invariant") if kind in value)


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
        for message in _unknown_key_messages(layer.body, layer.path):
            if not allow_unknown:
                raise ConfigLoadError(message)
            print(f"warning: {message}", file=sys.stderr)


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
                if key == "analyze":
                    dispositions = value.get("dispositions")
                    if isinstance(dispositions, list):
                        for index, disposition in enumerate(dispositions):
                            messages.extend(
                                "unknown config key "
                                f"`analyze.dispositions[{index}].{sub}` in {config_path}"
                                for sub in _unused_table_keys(
                                    disposition, _DISPOSITION_KEYS
                                )
                            )
                if key == "verify":
                    provider = value.get("provider")
                    if isinstance(provider, dict):
                        messages.extend(
                            f"unknown config key `verify.provider.{sub}` in {config_path}"
                            for sub in _unused_table_keys(
                                provider, _VERIFY_PROVIDER_KEYS
                            )
                        )
                    evaluation = value.get("eval")
                    if isinstance(evaluation, dict):
                        messages.extend(
                            f"unknown config key `verify.eval.{sub}` in {config_path}"
                            for sub in _unused_table_keys(evaluation, _VERIFY_EVAL_KEYS)
                        )
                if key == "diagnostics":
                    rules = value.get("levels")
                    if isinstance(rules, list):
                        for index, rule in enumerate(rules):
                            messages.extend(
                                "unknown config key "
                                f"`diagnostics.levels[{index}].{sub}` in {config_path}"
                                for sub in _unused_table_keys(
                                    rule, frozenset({"select", "level"})
                                )
                            )
            continue
        if key in _TOP_LEVEL_KEYS:
            continue
        messages.append(f"unknown config key `{key}` in {config_path}")
    return messages


def _is_packaged_default_path(path: Path) -> bool:
    return path.resolve() == PACKAGED_DEFAULTS_PATH


def _table_key_names(table_name: str) -> frozenset[str]:
    if table_name == "defaults":
        return _DEFAULTS_KEYS
    if table_name == "profile":
        return _PROFILE_KEYS
    if table_name == "check":
        return _CHECK_KEYS
    if table_name == "packets":
        return _PACKETS_KEYS
    if table_name == "analyze":
        return _ANALYZE_KEYS
    if table_name == "verify":
        return _VERIFY_KEYS
    if table_name == "obligations":
        return _OBLIGATION_KEYS
    if table_name == "target_roots":
        return _TARGET_ROOT_KEYS
    if table_name == "lint":
        return _LINT_KEYS
    if table_name == "diagnostics":
        return _DIAGNOSTICS_KEYS
    return frozenset()


def _parse_lint_settings(lint_table: dict[str, Any]) -> LintSettings:
    warn_unused = lint_table.get("warn_unused_ignores", True)
    if not isinstance(warn_unused, bool):
        msg = "lint.warn_unused_ignores must be a boolean"
        raise ConfigLoadError(msg)
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
        per_file_ignores=per_file,
        per_section_ignores=per_section,
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
