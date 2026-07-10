"""TOML configuration discovery and resolution.

Spec: docs/specs/03-backstitch-configuration.md [CFG-1], [CFG-2], [CFG-3], [CFG-4],
[CFG-5], [CFG-6], [CFG-8]
Spec: docs/specs/04-backstitch-traceability-exclusions.md [EXC-3], [EXC-6]
Spec: docs/specs/02-backstitch-core.md [SC-13]
"""

from __future__ import annotations

import json
import os
import re
import sys
import tomllib
from dataclasses import asdict, dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

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

DEFAULT_EXCLUDES: tuple[str, ...] = tuple(load_default_config_raw()["exclude"])
PACKAGED_DEFAULTS_LAYER = "packaged:backstitch/defaults.toml"

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
_ANALYZE_KEYS = frozenset({"model", "concurrency"})
_TARGET_ROOT_KEYS = frozenset({"weft"})
_DIAGNOSTICS_KEYS = frozenset(
    {"default_level", "fail_on", "suppressible_levels", "levels"}
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
class CheckSettings:
    format: str | None = None
    warnings_as_errors: bool | None = None
    output: str | None = None


@dataclass(frozen=True, slots=True)
class PacketsSettings:
    output: str | None = None


@dataclass(frozen=True, slots=True)
class AnalyzeSettings:
    model: str | None = None
    concurrency: int | None = None


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
    target_roots: TargetRootSettings = field(default_factory=TargetRootSettings)
    diagnostics: DiagnosticsSettings = field(default_factory=default_policy)
    config_path: Path | None = None
    config_dir: Path | None = None
    config_layers: tuple[str, ...] = (PACKAGED_DEFAULTS_LAYER,)


def discover_config_path(
    anchor: Path,
    *,
    home: Path | None = None,
    explicit: Path | None = None,
) -> Path | None:
    if explicit is not None:
        path = explicit.expanduser()
        if not path.is_file():
            msg = f"Config file not found: {path}"
            raise ConfigLoadError(msg)
        return path.resolve()

    resolved_home = (home or Path.home()).resolve()
    current = anchor.resolve()
    while True:
        backstitch_toml = current / ".backstitch.toml"
        if backstitch_toml.is_file():
            return backstitch_toml.resolve()
        pyproject = current / "pyproject.toml"
        if pyproject.is_file() and _pyproject_has_backstitch(pyproject):
            return pyproject.resolve()
        if current == resolved_home:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def load_settings(
    anchor: Path,
    *,
    home: Path | None = None,
    explicit: Path | None = None,
    use_repo_config: bool = True,
) -> BackstitchSettings:
    raw = dict(load_default_config_raw())
    layers = [PACKAGED_DEFAULTS_LAYER]
    config_path: Path | None = None
    if use_repo_config:
        config_path = discover_config_path(anchor, home=home, explicit=explicit)
        if config_path is not None:
            repo_raw, warnings = _load_config_chain(config_path, set())
            for warning in warnings:
                print(f"warning: {warning}", file=sys.stderr)
            _validate_unknown_keys(repo_raw, config_path)
            raw = _merge_config_layers(raw, repo_raw)
            layers.append(str(config_path))
    settings = _parse_settings(
        raw,
        source_path=config_path or Path("backstitch/defaults.toml"),
        effective_config_path=config_path,
        config_layers=tuple(layers),
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
        "target_roots": asdict(settings.target_roots),
        "diagnostics": policy_to_dict(settings.diagnostics),
        "resolved_diagnostics": resolved_policy_to_dict(settings.diagnostics),
        "config_layers": list(settings.config_layers),
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


def _pyproject_has_backstitch(path: Path) -> bool:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        # [CFG-8]: a pyproject.toml that does not parse cannot be checked
        # for a [tool.backstitch] table -- exit 2 naming the file, never a
        # silent skip to the next ancestor.
        msg = f"Invalid TOML in {path} during config discovery: {exc}"
        raise ConfigLoadError(msg) from exc
    return "backstitch" in data.get("tool", {})


def _extract_config_body(path: Path) -> dict[str, Any]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
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

    for table_name, key in (("check", "output"), ("packets", "output")):
        table = body.get(table_name)
        if isinstance(table, dict) and isinstance(table.get(key), str):
            table[key] = expand_path_value(table[key], base_dir=base_dir)
    roots = body.get("target_roots")
    if isinstance(roots, dict):
        for name, value in roots.items():
            if isinstance(value, str):
                roots[name] = expand_path_value(value, base_dir=base_dir)


def _load_config_chain(
    path: Path,
    seen: set[Path],
) -> tuple[dict[str, Any], list[str]]:
    resolved = path.resolve()
    if resolved in seen:
        msg = f"Circular extend chain detected at {resolved}"
        raise ConfigLoadError(msg)
    seen.add(resolved)

    body = _extract_config_body(resolved)
    _expand_raw_paths(body, resolved.parent)
    extend = body.get("extend")
    warnings: list[str] = []
    if extend is None:
        return body, warnings

    if not isinstance(extend, str) or not extend.strip():
        msg = f"Invalid extend value in {resolved}"
        raise ConfigLoadError(msg)

    parent_path = (
        resolved.parent / expand_path_value(extend.strip(), base_dir=resolved.parent)
    ).resolve()
    if not parent_path.is_file():
        msg = f"extend target not found: {parent_path}"
        raise ConfigLoadError(msg)

    parent_body, parent_warnings = _load_config_chain(parent_path, seen)
    warnings.extend(parent_warnings)
    merged = _merge_config_layers(parent_body, body)
    merged.pop("extend", None)
    return merged, warnings


def _parse_settings(
    raw: dict[str, Any],
    *,
    source_path: Path,
    effective_config_path: Path | None,
    config_layers: tuple[str, ...],
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

    analyze_model = analyze_table.get("model")
    if analyze_model is not None and not isinstance(analyze_model, str):
        msg = "analyze.model must be a string"
        raise ConfigLoadError(msg)

    analyze_concurrency = analyze_table.get("concurrency")
    if analyze_concurrency is not None:
        # bool is an int subclass: `concurrency = true` is a type error
        # under strict config, not concurrency 1.
        if (
            isinstance(analyze_concurrency, bool)
            or not isinstance(analyze_concurrency, int)
            or analyze_concurrency < 1
        ):
            msg = "analyze.concurrency must be a positive integer"
            raise ConfigLoadError(msg)

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
        analyze=AnalyzeSettings(
            model=analyze_model,
            concurrency=analyze_concurrency,
        ),
        target_roots=TargetRootSettings(weft=weft_root),
        diagnostics=diagnostics,
        config_path=effective_config_path,
        config_dir=effective_config_path.parent if effective_config_path else None,
        config_layers=config_layers,
    )


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
            continue
        if key in _TOP_LEVEL_KEYS:
            continue
        messages.append(f"unknown config key `{key}` in {config_path}")
    return messages


def _is_packaged_default_path(path: Path) -> bool:
    return path.as_posix() == "backstitch/defaults.toml"


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
