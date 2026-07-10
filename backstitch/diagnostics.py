"""Diagnostic registry, aliases, and ordered reporting policy.

Spec: docs/specs/02-backstitch-core.md [SC-6], [SC-11], [SC-15]
Spec: docs/specs/03-backstitch-configuration.md [CFG-5], [CFG-6], [CFG-8]
Spec: docs/specs/04-backstitch-traceability-exclusions.md [EXC-4], [EXC-8]
Spec: docs/specs/05-backstitch-invariants.md [INV-4], [INV-8]
"""

from __future__ import annotations

import dataclasses
import functools
import importlib.resources
import tomllib
from dataclasses import dataclass
from typing import Any, Literal

Severity = Literal["error", "warning", "info"]
DiagnosticLevel = Literal["error", "warning", "info", "off"]
DiagnosticStatus = Literal["implemented", "reserved", "deprecated", "redirected"]

SEVERITIES: frozenset[str] = frozenset({"error", "warning", "info"})
DIAGNOSTIC_LEVELS: frozenset[str] = frozenset({"error", "warning", "info", "off"})
DIAGNOSTIC_STATUSES: frozenset[str] = frozenset(
    {"implemented", "reserved", "deprecated", "redirected"}
)
DEFAULTS_RESOURCE = "defaults.toml"
OFF_AUDIT_REASON = "diagnostic level off"


class DiagnosticConfigError(ValueError):
    """The packaged diagnostic registry or configured policy is invalid."""


@dataclass(frozen=True, slots=True)
class DiagnosticDefinition:
    code: str
    short_code: str
    status: DiagnosticStatus
    summary: str
    contexts: tuple[str, ...] = ()
    replacement: str | None = None


@dataclass(frozen=True, slots=True)
class DiagnosticRegistry:
    definitions: dict[str, DiagnosticDefinition]
    short_to_code: dict[str, str]

    def require(self, code: str) -> DiagnosticDefinition:
        try:
            return self.definitions[code]
        except KeyError:
            raise DiagnosticConfigError(f"unknown diagnostic code: {code}") from None

    def canonical_code(self, code_or_short: str) -> str:
        if code_or_short in self.definitions:
            code = code_or_short
        elif code_or_short in self.short_to_code:
            code = self.short_to_code[code_or_short]
        else:
            raise DiagnosticConfigError(f"unknown diagnostic code: {code_or_short}")

        chain: list[str] = []
        seen: set[str] = set()
        while True:
            if code in seen:
                cycle = " -> ".join((*chain, code))
                raise DiagnosticConfigError(
                    f"diagnostic replacement cycle detected: {cycle}"
                )
            seen.add(code)
            chain.append(code)

            definition = self.require(code)
            if definition.status == "implemented":
                return code
            if definition.status not in {"deprecated", "redirected"}:
                raise DiagnosticConfigError(
                    f"diagnostic {code_or_short} resolves to {code} with status"
                    f" {definition.status}; expected implemented"
                )
            if definition.replacement is None:
                raise DiagnosticConfigError(
                    f"diagnostic {code} has status {definition.status} but no replacement"
                )
            if definition.replacement not in self.definitions:
                raise DiagnosticConfigError(
                    f"diagnostic {code} replacement is not a known diagnostic:"
                    f" {definition.replacement}"
                )
            code = definition.replacement

    def implemented_codes(self) -> frozenset[str]:
        return frozenset(
            code
            for code, definition in self.definitions.items()
            if definition.status == "implemented"
        )


@dataclass(frozen=True, slots=True)
class DiagnosticLevelRule:
    selectors: tuple[str, ...]
    level: DiagnosticLevel


@dataclass(frozen=True, slots=True)
class DiagnosticsSettings:
    default_level: DiagnosticLevel = "warning"
    levels: tuple[DiagnosticLevelRule, ...] = ()
    fail_on: tuple[Severity, ...] = ("error",)
    suppressible_levels: tuple[Severity, ...] = ("warning", "info")


@functools.cache
def load_default_config_raw() -> dict[str, Any]:
    """Return Backstitch's packaged default TOML body."""

    resource = importlib.resources.files("backstitch").joinpath(DEFAULTS_RESOURCE)
    try:
        return tomllib.loads(resource.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise DiagnosticConfigError(f"invalid packaged defaults TOML: {exc}") from exc


@functools.cache
def default_registry() -> DiagnosticRegistry:
    raw = load_default_config_raw()
    diagnostics = _expect_table(raw.get("diagnostics"), "diagnostics")
    registry = _expect_table(diagnostics.get("registry"), "diagnostics.registry")
    return parse_registry(registry, source=DEFAULTS_RESOURCE)


@functools.cache
def default_policy() -> DiagnosticsSettings:
    raw = load_default_config_raw()
    diagnostics = _expect_table(raw.get("diagnostics"), "diagnostics")
    return parse_policy(
        diagnostics,
        registry=default_registry(),
        source=DEFAULTS_RESOURCE,
        allow_unknown=False,
    )


def parse_registry(raw: dict[str, Any], *, source: str) -> DiagnosticRegistry:
    definitions: dict[str, DiagnosticDefinition] = {}
    short_to_code: dict[str, str] = {}
    for code, value in sorted(raw.items()):
        if not isinstance(code, str) or not code:
            raise DiagnosticConfigError(
                f"invalid diagnostic code in {source}: {code!r}"
            )
        table = _expect_table(value, f"diagnostics.registry.{code}")
        short = table.get("short")
        status = table.get("status")
        summary = table.get("summary")
        replacement = table.get("replacement")
        contexts = table.get("contexts", [])
        if not isinstance(short, str) or not short:
            raise DiagnosticConfigError(f"{code} short code must be a non-empty string")
        if short in short_to_code:
            other = short_to_code[short]
            raise DiagnosticConfigError(
                f"duplicate short diagnostic code {short}: {other}, {code}"
            )
        if status not in DIAGNOSTIC_STATUSES:
            raise DiagnosticConfigError(f"{code} has invalid status {status!r}")
        if not isinstance(summary, str) or not summary.strip():
            raise DiagnosticConfigError(f"{code} summary must be a non-empty string")
        if replacement is not None and not isinstance(replacement, str):
            raise DiagnosticConfigError(f"{code} replacement must be a string")
        if not isinstance(contexts, list) or not all(
            isinstance(item, str) and item for item in contexts
        ):
            raise DiagnosticConfigError(f"{code} contexts must be an array of strings")
        definitions[code] = DiagnosticDefinition(
            code=code,
            short_code=short,
            status=status,
            summary=summary,
            contexts=tuple(contexts),
            replacement=replacement,
        )
        short_to_code[short] = code

    for definition in definitions.values():
        if definition.status in {"deprecated", "redirected"}:
            if definition.replacement not in definitions:
                raise DiagnosticConfigError(
                    f"{definition.code} replacement is not a known diagnostic"
                )
    registry = DiagnosticRegistry(definitions=definitions, short_to_code=short_to_code)
    for definition in definitions.values():
        if definition.status in {"deprecated", "redirected"}:
            registry.canonical_code(definition.code)
    return registry


def parse_policy(
    raw: dict[str, Any],
    *,
    registry: DiagnosticRegistry | None = None,
    source: str,
    allow_unknown: bool,
) -> DiagnosticsSettings:
    registry = registry or default_registry()
    default_level = raw.get("default_level", "warning")
    if default_level not in DIAGNOSTIC_LEVELS:
        raise DiagnosticConfigError(
            f"diagnostics.default_level must be one of error, warning, info, off"
            f" in {source}"
        )
    fail_on = _parse_severity_list(raw.get("fail_on", ["error"]), "fail_on", source)
    suppressible = _parse_severity_list(
        raw.get("suppressible_levels", ["warning", "info"]),
        "suppressible_levels",
        source,
    )
    rules_raw = raw.get("levels", [])
    if not isinstance(rules_raw, list):
        raise DiagnosticConfigError(f"diagnostics.levels must be an array in {source}")
    rules: list[DiagnosticLevelRule] = []
    for index, rule_raw in enumerate(rules_raw):
        rule = _expect_table(rule_raw, f"diagnostics.levels[{index}]")
        selectors = rule.get("select")
        level = rule.get("level")
        if not isinstance(selectors, list) or not all(
            isinstance(item, str) and item.strip() for item in selectors
        ):
            raise DiagnosticConfigError(
                f"diagnostics.levels[{index}].select must be an array of strings"
            )
        if level not in DIAGNOSTIC_LEVELS:
            raise DiagnosticConfigError(
                f"diagnostics.levels[{index}].level must be one of"
                " error, warning, info, off"
            )
        for selector in selectors:
            validate_selector(selector, registry=registry, allow_unknown=allow_unknown)
        rules.append(
            DiagnosticLevelRule(
                selectors=tuple(selector.strip() for selector in selectors),
                level=level,
            )
        )
    return DiagnosticsSettings(
        default_level=default_level,
        levels=tuple(rules),
        fail_on=fail_on,
        suppressible_levels=suppressible,
    )


def policy_to_dict(policy: DiagnosticsSettings) -> dict[str, Any]:
    return {
        "default_level": policy.default_level,
        "fail_on": list(policy.fail_on),
        "suppressible_levels": list(policy.suppressible_levels),
        "levels": [
            {"select": list(rule.selectors), "level": rule.level}
            for rule in policy.levels
        ],
    }


def resolved_policy_to_dict(
    policy: DiagnosticsSettings,
    *,
    registry: DiagnosticRegistry | None = None,
) -> dict[str, dict[str, str]]:
    registry = registry or default_registry()
    resolved: dict[str, dict[str, str]] = {}
    for code in sorted(registry.implemented_codes()):
        definition = registry.require(code)
        contexts = definition.contexts or (None,)
        for context in contexts:
            key = code if context is None else f"{code}:{context}"
            resolved[key] = {
                "short_code": definition.short_code,
                "level": resolve_level(code, context=context, policy=policy),
            }
    return resolved


def canonicalize_code(code_or_short: str) -> str:
    return default_registry().canonical_code(code_or_short)


def short_code_for(code: str) -> str:
    definition = default_registry().require(code)
    if definition.status != "implemented":
        raise DiagnosticConfigError(
            f"diagnostic {code} has status {definition.status}; only implemented"
            " diagnostics may be emitted"
        )
    return definition.short_code


def is_known_diagnostic_code(code_or_short: str) -> bool:
    registry = default_registry()
    return (
        code_or_short in registry.definitions or code_or_short in registry.short_to_code
    )


def is_ordinary_diagnostic_code(code_or_short: str) -> bool:
    """Return whether a code is valid for emitted issues and suppressions."""

    try:
        code = default_registry().canonical_code(code_or_short)
    except DiagnosticConfigError:
        return False
    return default_registry().require(code).status == "implemented"


def implemented_codes() -> frozenset[str]:
    return default_registry().implemented_codes()


def always_error_codes() -> frozenset[str]:
    policy = default_policy()
    registry = default_registry()
    result: set[str] = set()
    for code in registry.implemented_codes():
        definition = registry.require(code)
        contexts = definition.contexts or (None,)
        if all(
            resolve_level(code, context=context, policy=policy) == "error"
            for context in contexts
        ):
            result.add(code)
    return frozenset(result)


def default_level_for(code: str, context: str | None = None) -> Severity:
    definition = default_registry().require(code)
    if definition.status != "implemented":
        raise DiagnosticConfigError(
            f"diagnostic {code} has status {definition.status}; only implemented"
            " diagnostics may be emitted"
        )
    level = resolve_level(code, context=context, policy=default_policy())
    if level == "off":
        raise DiagnosticConfigError(f"default policy cannot disable {code}")
    return level


def resolve_level(
    code: str,
    *,
    context: str | None,
    policy: DiagnosticsSettings,
    registry: DiagnosticRegistry | None = None,
) -> DiagnosticLevel:
    registry = registry or default_registry()
    canonical = registry.canonical_code(code)
    level: DiagnosticLevel = policy.default_level
    for rule in policy.levels:
        if any(
            selector_matches(selector, canonical, context=context, registry=registry)
            for selector in rule.selectors
        ):
            level = rule.level
    return level


def selector_matches(
    selector: str,
    code: str,
    *,
    context: str | None,
    registry: DiagnosticRegistry | None = None,
) -> bool:
    registry = registry or default_registry()
    selector_code, selector_context = _split_selector(selector)
    if selector_context is not None and selector_context != context:
        return False
    if selector_code == "*":
        return True
    if selector_code.endswith("*"):
        prefix = selector_code[:-1]
        definition = registry.require(code)
        return code.startswith(prefix) or definition.short_code.startswith(prefix)
    try:
        return registry.canonical_code(selector_code) == code
    except DiagnosticConfigError:
        return False


def validate_selector(
    selector: str,
    *,
    registry: DiagnosticRegistry | None = None,
    allow_unknown: bool,
) -> None:
    registry = registry or default_registry()
    selector_code, selector_context = _split_selector(selector)
    if selector_context is not None and selector_code.endswith("*"):
        raise DiagnosticConfigError(
            f"wildcard diagnostic selector cannot include a context: {selector}"
        )
    if selector_code == "*":
        return
    selectable_statuses = {"implemented", "deprecated", "redirected"}
    matches = [
        code
        for code, definition in registry.definitions.items()
        if definition.status in selectable_statuses
        and selector_matches(
            selector, code, context=selector_context, registry=registry
        )
    ]
    if not matches and not allow_unknown:
        raise DiagnosticConfigError(f"unknown diagnostic selector: {selector}")
    for code in matches:
        contexts = registry.require(code).contexts
        if (
            selector_context is not None
            and (not contexts or selector_context not in contexts)
            and not allow_unknown
        ):
            raise DiagnosticConfigError(
                f"unknown diagnostic context in selector: {selector}"
            )


def issue_with_policy(
    issue: Any,
    *,
    effective_policy: DiagnosticsSettings,
    default_policy_: DiagnosticsSettings | None = None,
) -> tuple[Any | None, Any | None]:
    default_policy_ = default_policy_ or default_policy()
    context = getattr(issue, "context", None)
    default_level = resolve_level(issue.code, context=context, policy=default_policy_)
    effective_level = resolve_level(
        issue.code,
        context=context,
        policy=effective_policy,
    )
    if default_level == "off":
        raise DiagnosticConfigError(f"default policy cannot disable {issue.code}")
    patched = dataclasses.replace(
        issue,
        short_code=short_code_for(issue.code),
        default_severity=default_level,
        severity=default_level if effective_level == "off" else effective_level,
    )
    if effective_level == "off":
        return None, patched
    return patched, None


def apply_policy_to_report(
    report: Any,
    *,
    effective_policy: DiagnosticsSettings,
    default_policy_: DiagnosticsSettings | None = None,
) -> tuple[Any, tuple[tuple[Any, str], ...]]:
    kept: list[Any] = []
    off_records: list[tuple[Any, str]] = []
    for issue in report.issues:
        patched, off_issue = issue_with_policy(
            issue,
            effective_policy=effective_policy,
            default_policy_=default_policy_,
        )
        if patched is not None:
            kept.append(patched)
        elif off_issue is not None:
            off_records.append((off_issue, OFF_AUDIT_REASON))
    return dataclasses.replace(report, issues=tuple(kept)), tuple(off_records)


def _parse_severity_list(
    value: Any, field_name: str, source: str
) -> tuple[Severity, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise DiagnosticConfigError(
            f"diagnostics.{field_name} must be an array in {source}"
        )
    invalid = [item for item in value if item not in SEVERITIES]
    if invalid:
        joined = ", ".join(invalid)
        raise DiagnosticConfigError(
            f"diagnostics.{field_name} may contain only error, warning, info"
            f" in {source}; invalid: {joined}"
        )
    return tuple(value)


def _split_selector(selector: str) -> tuple[str, str | None]:
    code, sep, context = selector.partition(":")
    return code, context if sep else None


def _expect_table(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DiagnosticConfigError(f"[{name}] must be a table")
    return value
