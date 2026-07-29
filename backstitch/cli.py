"""Command-line entry point for backstitch.

Spec: docs/specs/02-backstitch-core.md [SC-1], [SC-5], [SC-5.1], [SC-13], [SC-16]
Spec: docs/specs/03-backstitch-configuration.md [CFG-5.1]
Spec: docs/specs/05-backstitch-invariants.md [INV-5]

Lane identity ([SC-16]): deterministic commands are the trace lane and
hard-gate by default; `analyze` is the semantic lane and advisory by
default; the policy layer in configuration is the only authority that
promotes a finding to blocking.

Exit-code contract ([SC-5]): exit 1 is a statement about the target
repository (deterministic findings exist); exit 2 is a statement about the
invocation or the tool (bad arguments, unreadable target, unwritable output,
internal failure). No invocation may surface a traceback: every failure path
prints a one-line ``backstitch: error: ...`` diagnostic.

Invariant: [INV.CLI.1] Deterministic commands never import ``llm``.

Spec: docs/specs/06-semantic-gates.md [SEM-7], [SEM-8], [SEM-9]
Spec: docs/specs/07-verification-and-evidence-cases.md [EVC-5.1], [EVC-8],
[EVC-8.7]
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import hashlib
import io
import json
import os
import sys
import time
from collections.abc import Sequence
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast

from backstitch import __version__
from backstitch.check_pipeline import (
    apply_check_policy,
    build_check_report_from_snapshot,
    scan_check_report_from_snapshot,
)
from backstitch.config import ProfileConfig, uncontained_test_root
from backstitch.grammar import candidate_ref_digest
from backstitch.profiles import get_profile
from backstitch.reporting import render_json, render_text
from backstitch.resolver import ScanError
from backstitch.settings import (
    CONFIG_CONSUMING_COMMANDS,
    BackstitchSettings,
    ConfigLoadError,
    resolve_config,
)

NO_CONFIG_HELP = "skip repository configuration; packaged defaults still load"
_TOP_LEVEL_COMMANDS = frozenset(
    {
        *CONFIG_CONSUMING_COMMANDS,
        "summarize-analysis",
        "cache",
        "guide",
    }
)


def _add_option_argument(
    parser: argparse.ArgumentParser,
    *,
    dest: str = "options",
) -> None:
    parser.add_argument(
        "--option",
        action="append",
        nargs=2,
        default=[],
        dest=dest,
        metavar=("KEY", "VALUE"),
        help="override one runtime setting by canonical dotted key (repeatable)",
    )


def _error(message: str) -> int:
    print(f"backstitch: error: {message}", file=sys.stderr)
    return 2


def _analysis_problem_error(problem: Any) -> int:
    """Preserve one closed analysis problem in the traceback-free CLI error."""

    row = problem.to_row()
    encoded = json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    message = " ".join(str(problem.message).split())
    print(
        f"backstitch: error: {problem.stage}/{problem.code}: {message}; "
        f"problem={encoded}",
        file=sys.stderr,
    )
    return 2


def _add_check_parser(subparsers: argparse._SubParsersAction[Any]) -> None:
    check = subparsers.add_parser(
        "check", help="run the deterministic traceability scan"
    )
    check.add_argument(
        "--repo-root",
        type=Path,
        default=Path("."),
        metavar="PATH",
        help="target repository root (default: current directory)",
    )
    check.add_argument(
        "--profile",
        default=None,
        help="built-in profile name (default: backstitch-style-v1)",
    )
    check.add_argument(
        "--spec-root",
        action="append",
        dest="spec_roots",
        metavar="PATH",
        help="override profile spec roots (repeatable)",
    )
    check.add_argument(
        "--plan-root",
        action="append",
        dest="plan_roots",
        metavar="PATH",
        help="override profile plan roots (repeatable)",
    )
    check.add_argument(
        "--code-root",
        action="append",
        dest="code_roots",
        metavar="PATH",
        help="override profile code roots (repeatable)",
    )
    check.add_argument(
        "--test-root",
        action="append",
        dest="test_roots",
        metavar="PATH",
        help="override profile test-role roots within code roots (repeatable)",
    )
    check.add_argument(
        "--format",
        choices=("text", "json"),
        default=None,
        help="report format (default: text, or configuration)",
    )
    check.add_argument(
        "--output",
        type=Path,
        default=None,
        metavar="PATH",
        help="write the report to PATH instead of stdout",
    )
    check.add_argument(
        "--config",
        type=Path,
        default=None,
        metavar="PATH",
        help="use exactly this configuration file (skips discovery)",
    )
    check.add_argument(
        "--no-config",
        action="store_true",
        help=NO_CONFIG_HELP,
    )
    _add_option_argument(check)
    check.add_argument(
        "--show-suppressions",
        action="store_true",
        help="include suppressed findings with reasons in the output",
    )
    check.add_argument(
        "--warnings-as-errors",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "exit 1 when warnings exist, not only errors; the explicit"
            " --no-warnings-as-errors overrides a config-set value"
        ),
    )


def _add_coverage_parser(subparsers: argparse._SubParsersAction[Any]) -> None:
    coverage = subparsers.add_parser(
        "coverage",
        help="measure intent coverage for canonical Python definitions",
    )
    coverage.add_argument(
        "path",
        nargs="?",
        type=Path,
        metavar="PATH",
        help="target repository root (default: current directory)",
    )
    coverage.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        metavar="PATH",
        help="target repository root (exact alias of positional PATH)",
    )
    coverage.add_argument("--profile", default=None, help="built-in profile name")
    coverage.add_argument("--format", choices=("text", "json"), default=None)
    coverage.add_argument("--output", type=Path, default=None, metavar="PATH")
    coverage.add_argument("--config", type=Path, default=None, metavar="PATH")
    coverage.add_argument("--no-config", action="store_true", help=NO_CONFIG_HELP)
    _add_option_argument(coverage)
    coverage.add_argument(
        "--require-ratchet",
        default=None,
        metavar="REF",
        help="require ratchet mode with exactly this configured base ref",
    )


def _add_other_parsers(subparsers: argparse._SubParsersAction[Any]) -> None:
    obligation = subparsers.add_parser(
        "obligation",
        help="list obligations or inspect one obligation and its evidence",
        description=(
            "Bootstrap with `backstitch obligation list`. Declared evidence"
            " comes from repository trace annotations; discovered candidates"
            " are read-only advice and never ratify a source relation."
        ),
    )
    obligation.add_argument("obligation_id", metavar="OBLIGATION_ID|list")
    obligation.add_argument("--repo-root", type=Path, default=Path("."))
    obligation.add_argument("--format", choices=("text", "json"), default="text")
    detail = obligation.add_mutually_exclusive_group()
    detail.add_argument("--summarize-evidence", action="store_true")
    detail.add_argument("--find-evidence", action="store_true")
    detail.add_argument("--candidate", metavar="CANDIDATE_ID")
    obligation.add_argument("--cursor", metavar="TOKEN")
    obligation.add_argument("--limit", type=int, metavar="N")
    obligation.add_argument("--config", type=Path, default=None, metavar="PATH")
    obligation.add_argument("--no-config", action="store_true", help=NO_CONFIG_HELP)
    _add_option_argument(obligation)

    guide = subparsers.add_parser(
        "guide", help="print an installed versioned workflow guide"
    )
    guide_sub = guide.add_subparsers(dest="guide_command", required=True)
    alignment = guide_sub.add_parser(
        "alignment", help="turn source-aligned intent into an executable gate"
    )
    alignment.add_argument("--format", choices=("text", "json"), default="text")

    packets = subparsers.add_parser(
        "packets", help="generate semantic-review packets (no model calls)"
    )
    packets.add_argument("--repo-root", type=Path, default=Path("."))
    packets.add_argument("--profile", default=None)
    packets.add_argument(
        "--spec-root", action="append", dest="spec_roots", metavar="PATH"
    )
    packets.add_argument(
        "--plan-root", action="append", dest="plan_roots", metavar="PATH"
    )
    packets.add_argument(
        "--code-root", action="append", dest="code_roots", metavar="PATH"
    )
    packets.add_argument(
        "--test-root", action="append", dest="test_roots", metavar="PATH"
    )
    packets.add_argument("--config", type=Path, default=None, metavar="PATH")
    packets.add_argument("--no-config", action="store_true", help=NO_CONFIG_HELP)
    _add_option_argument(packets)
    packets.add_argument(
        "--kind",
        choices=("section", "invariant", "suppression", "all"),
        default="section",
        help="packet kind to emit (default: section)",
    )
    packets.add_argument("--output", type=Path, required=True, metavar="PATH")
    packets.add_argument("--report", type=Path, default=None, metavar="PATH")

    analyze = subparsers.add_parser(
        "analyze", help="run llm-backed semantic review over packets"
    )
    analyze_input = analyze.add_mutually_exclusive_group(required=True)
    analyze_input.add_argument("--repo-root", type=Path, metavar="PATH")
    analyze_input.add_argument("--packets", type=Path, metavar="PATH")
    analyze.add_argument("--packet-report", type=Path, default=None, metavar="PATH")
    analyze.add_argument("--compare-repo-root", type=Path, default=None, metavar="PATH")
    analyze.add_argument("--packets-output", type=Path, default=None, metavar="PATH")
    analyze.add_argument(
        "--packet-report-output", type=Path, default=None, metavar="PATH"
    )
    analyze.add_argument("--model", default=None, metavar="MODEL")
    analyze.add_argument(
        "--output",
        type=Path,
        default=None,
        metavar="PATH",
        help="write canonical semantic result JSONL to PATH",
    )
    analyze.add_argument("--report", type=Path, default=None, metavar="PATH")
    analyze.add_argument("--concurrency", type=int, default=None, metavar="N")
    analyze.add_argument("--format", choices=("text", "json"), default="text")
    analyze.add_argument("--config", type=Path, default=None, metavar="PATH")
    analyze.add_argument("--no-config", action="store_true", help=NO_CONFIG_HELP)
    _add_option_argument(analyze)

    evaluate = subparsers.add_parser(
        "eval", help="measure semantic review against a closed corpus"
    )
    evaluate.add_argument(
        "--corpus",
        type=Path,
        required=True,
        metavar="MANIFEST",
        help="closed semantic-eval manifest",
    )
    evaluate.add_argument(
        "--output",
        type=Path,
        required=True,
        metavar="PATH",
        help="write the canonical semantic-eval report to PATH",
    )
    evaluate.add_argument("--config", type=Path, default=None, metavar="PATH")
    evaluate.add_argument("--no-config", action="store_true", help=NO_CONFIG_HELP)
    _add_option_argument(evaluate)

    summarize = subparsers.add_parser(
        "summarize-analysis",
        help="combine a deterministic report with semantic results",
        description=(
            "Combine a deterministic report with semantic analysis results."
            " Validates the schema of both inputs and rejects rows whose"
            " packet ID no section in the report could have produced."
            " Packet-local evidence bounds are enforced by `backstitch"
            " analyze` (which wrote the results file), not re-checked here:"
            " this command never sees the packets."
        ),
    )
    summarize.add_argument(
        "--deterministic-report", type=Path, required=True, metavar="PATH"
    )
    summarize.add_argument(
        "--analysis-results", type=Path, required=True, metavar="PATH"
    )

    doctor = subparsers.add_parser(
        "doctor",
        help="diagnose the llm/model/endpoint environment analyze depends on",
        description=(
            "Diagnose the semantic-analysis environment per [SC-14]: llm"
            " installation, model resolution, credentials,"
            " constrained-decoding capability, and (with --probe) endpoint"
            " reachability. Exits 0 when no check fails, 2 otherwise;"
            " never 1."
        ),
    )
    doctor.add_argument("--model", default=None, metavar="MODEL")
    doctor.add_argument(
        "--probe",
        action="store_true",
        help="also test endpoint reachability (the only network the command"
        " ever performs; no credential is sent, nothing is generated)",
    )
    doctor.add_argument("--format", choices=("text", "json"), default="text")
    doctor.add_argument("--config", type=Path, default=None, metavar="PATH")
    doctor.add_argument("--no-config", action="store_true", help=NO_CONFIG_HELP)
    _add_option_argument(doctor)

    config = subparsers.add_parser("config", help="inspect resolved configuration")
    config_sub = config.add_subparsers(dest="config_command", required=True)
    show = config_sub.add_parser("show", help="print effective settings as JSON")
    show.add_argument("--repo-root", type=Path, default=Path("."))
    show.add_argument("--config", type=Path, default=None, metavar="PATH")
    show.add_argument("--no-config", action="store_true", help=NO_CONFIG_HELP)
    _add_option_argument(show)
    path_cmd = config_sub.add_parser(
        "path", help="print the discovered config file path"
    )
    path_cmd.add_argument("--repo-root", type=Path, default=Path("."))
    path_cmd.add_argument("--config", type=Path, default=None, metavar="PATH")
    path_cmd.add_argument("--no-config", action="store_true", help=NO_CONFIG_HELP)
    _add_option_argument(path_cmd)

    cache = subparsers.add_parser(
        "cache", help="perform explicit semantic-cache maintenance"
    )
    cache_sub = cache.add_subparsers(dest="cache_command", required=True)
    cleanup = cache_sub.add_parser(
        "cleanup-lock", help="audit and remove one abandoned semantic lock"
    )
    cleanup.add_argument("--cache-path", type=Path, required=True, metavar="PATH")
    cleanup_key = cleanup.add_mutually_exclusive_group(required=True)
    cleanup_key.add_argument("--analysis-key", metavar="HASH")
    cleanup_key.add_argument("--review-key", metavar="HASH")
    cleanup_key.add_argument("--verify-key", metavar="HASH")
    cleanup.add_argument(
        "--lock-stale-seconds", type=int, required=True, metavar="SECONDS"
    )
    cleanup.add_argument("--reason", required=True, metavar="TEXT")


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level parser."""

    parser = argparse.ArgumentParser(
        prog="backstitch",
        description=(
            "Backstitch style traceability checks for spec-driven repositories."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    # [CFG-7] global spellings: `backstitch --config PATH <command>` and
    # `backstitch --no-config <command>`. Distinct dests so a subcommand's
    # own --config/--no-config defaults never clobber a global value;
    # main() merges the two spellings.
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        metavar="PATH",
        dest="global_config",
        help="use exactly this configuration file (skips discovery)",
    )
    parser.add_argument(
        "--no-config",
        action="store_true",
        dest="global_no_config",
        help=NO_CONFIG_HELP,
    )
    _add_option_argument(parser, dest="global_options")
    subparsers = parser.add_subparsers(dest="command")
    _add_check_parser(subparsers)
    _add_coverage_parser(subparsers)
    _add_other_parsers(subparsers)
    return parser


def _coverage_root(args: argparse.Namespace) -> Path:
    if args.path is not None and args.repo_root is not None:
        raise ConfigLoadError("positional PATH and --repo-root are mutually exclusive")
    return cast(Path, args.repo_root or args.path or Path(".")).resolve()


def _settings_anchor(args: argparse.Namespace) -> Path:
    if args.command is None:
        return Path.cwd()
    if args.command == "coverage":
        return _coverage_root(args)
    if args.command in {"check", "packets", "obligation", "config"}:
        return cast(Path, args.repo_root).resolve()
    if args.command == "analyze":
        if args.repo_root is not None:
            return cast(Path, args.repo_root).resolve()
        assert args.packets is not None
        return cast(Path, args.packets).resolve().parent
    if args.command == "eval":
        return cast(Path, args.corpus).resolve().parent
    if args.command == "doctor":
        return Path.cwd()
    raise ConfigLoadError(f"{args.command} does not consume configuration")


def _dedicated_cli_overrides(args: argparse.Namespace) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    if args.command in {"check", "packets", "coverage"}:
        if args.profile is not None:
            overrides["profile.name"] = args.profile
    if args.command in {"check", "packets"}:
        for attribute, key in (
            ("spec_roots", "profile.spec_roots"),
            ("plan_roots", "profile.plan_roots"),
            ("code_roots", "profile.code_roots"),
            ("test_roots", "profile.test_roots"),
        ):
            values = getattr(args, attribute, None)
            if values is not None:
                overrides[key] = [value for value in values if value]
    if args.command == "check":
        if args.format is not None:
            overrides["check.format"] = args.format
        if args.output is not None:
            overrides["check.output"] = str(args.output)
        if args.warnings_as_errors is not None:
            overrides["check.warnings_as_errors"] = args.warnings_as_errors
    if args.command == "coverage":
        if args.format is not None:
            overrides["coverage.format"] = args.format
        if args.output is not None:
            overrides["coverage.output"] = str(args.output)
    if args.command in {"analyze", "doctor"} and args.model is not None:
        overrides["analyze.model"] = args.model
    if args.command == "analyze" and args.concurrency is not None:
        overrides["analyze.concurrency"] = args.concurrency
    return overrides


def _resolve_invocation_settings(args: argparse.Namespace) -> BackstitchSettings:
    return resolve_config(
        _settings_anchor(args),
        explicit=args.config,
        use_repo_config=not args.no_config,
        environment=os.environ,
        cli_options=tuple((key, value) for key, value in args.options),
        cli_overrides=_dedicated_cli_overrides(args),
        invocation_command=args.command,
    )


def _profile_from(
    args: argparse.Namespace, settings: BackstitchSettings
) -> ProfileConfig:
    """Build the scan profile from the already resolved settings snapshot."""

    profile = _configured_profile(settings)
    _validate_test_root_containment(args.repo_root.resolve(), profile)
    return profile


def _configured_profile(
    settings: BackstitchSettings, *, name: str | None = None
) -> ProfileConfig:
    """Apply repository profile settings without command-line root overrides."""

    profile = get_profile(name or settings.profile or "backstitch-style-v1")
    config_overrides: dict[str, tuple[str, ...]] = {}
    for field in (
        "spec_roots",
        "plan_roots",
        "code_roots",
        "test_roots",
        "planned_spec_globs",
        "exploratory_spec_globs",
        "meta_spec_globs",
    ):
        value = getattr(settings.profile_overrides, field)
        if value is not None:
            config_overrides[field] = value
    if config_overrides:
        profile = profile.with_overrides(**config_overrides)
    return profile


def _validate_test_root_containment(
    repo_root: Path,
    profile: ProfileConfig,
) -> None:
    invalid_test_root = uncontained_test_root(
        repo_root,
        profile.code_roots,
        profile.test_roots,
    )
    if invalid_test_root is not None:
        msg = (
            f"test root {invalid_test_root!r} must be equal to or nested under a"
            " final effective code root"
        )
        raise ConfigLoadError(msg)


def _cmd_check(args: argparse.Namespace, settings: BackstitchSettings) -> int:
    from backstitch.markdown_specs import MarkdownParseMemo
    from backstitch.obligation_runtime import capture_obligation_snapshot
    from backstitch.repository_snapshot import SnapshotCaptureError

    profile = _profile_from(args, settings)
    root = args.repo_root.resolve()
    markdown_parse_memo: MarkdownParseMemo = {}
    try:
        snapshot = capture_obligation_snapshot(
            root,
            profile,
            settings,
            markdown_parse_memo=markdown_parse_memo,
        )
    except SnapshotCaptureError as exc:
        raise ScanError(str(exc)) from exc
    pipeline = build_check_report_from_snapshot(
        snapshot,
        root.as_posix(),
        profile,
        settings,
        markdown_parse_memo=markdown_parse_memo,
    )

    for warning in pipeline.warnings:
        print(f"warning: {warning}", file=sys.stderr)

    # [CFG-5]: config-set check.format and check.output apply when
    # the CLI flag is omitted; a parsed-but-unconsulted key is dead schema.
    fmt = settings.check.format or "text"
    output = Path(settings.check.output) if settings.check.output is not None else None

    shown = pipeline.suppressed if args.show_suppressions else None
    shown_skips = pipeline.obligation_skip_audit if args.show_suppressions else None
    rendered = (
        render_json(pipeline.report, shown, shown_skips)
        if fmt == "json"
        else render_text(pipeline.report, shown, shown_skips)
    )

    if output is not None:
        # Known fable defect fixed at port time: an unwritable --output path
        # must be exit 2 with a one-line error, never a traceback/exit 1.
        try:
            output.write_text(rendered, encoding="utf-8")
        except OSError as exc:
            return _error(f"cannot write --output {output}: {exc}")
    else:
        sys.stdout.write(rendered)

    fail_on = set(settings.diagnostics.fail_on)
    warnings_as_errors = bool(settings.check.warnings_as_errors)
    if warnings_as_errors:
        fail_on.add("warning")
    if any(issue.severity in fail_on for issue in pipeline.report.issues):
        return 1
    return 0


def _cmd_coverage(args: argparse.Namespace, settings: BackstitchSettings) -> int:
    from backstitch.diagnostics import issue_with_policy
    from backstitch.evidence_discovery import resolved_python_module_names
    from backstitch.git_baseline import (
        DriftEvent,
        DriftTransition,
        GitBaselineError,
        PolicyEvent,
        PolicyTransition,
        StaleDocTrend,
        baseline_metadata,
        compute_drift_event,
        current_content_identity,
        fold_policy_transitions,
        load_git_baseline,
        policy_identity,
    )
    from backstitch.intent_coverage import (
        CoverageDefinition,
        CoverageExemptionFact,
        CoverageFloorFact,
        CoverageUnscannableFile,
        DefinitionRole,
        classify_intent_coverage,
        coverage_definitions_from_python_inventory,
        evaluate_coverage_floors,
    )
    from backstitch.intent_coverage_reporting import (
        build_coverage_report,
        render_coverage_json,
    )
    from backstitch.intent_history import (
        IntentRevisionProjector,
        build_stale_doc_history,
    )
    from backstitch.markdown_specs import MarkdownParseMemo
    from backstitch.models import Issue
    from backstitch.obligation_runtime import capture_obligation_snapshot
    from backstitch.python_refs import python_definition_inventory_bytes
    from backstitch.repository_snapshot import SnapshotCaptureError
    from backstitch.semantic_reports import atomic_replace_bytes
    from backstitch.settings import resolve_repository_config_from_blobs

    root = _coverage_root(args)
    profile = _configured_profile(settings)
    _validate_test_root_containment(root, profile)
    if args.require_ratchet is not None and (
        settings.coverage.mode != "ratchet"
        or settings.coverage.ratchet_base != args.require_ratchet
    ):
        return _error(
            "--require-ratchet requires ratchet mode and an exact matching "
            "coverage.ratchet_base"
        )
    markdown_parse_memo: MarkdownParseMemo = {}
    python_parse_memo: dict[tuple[str, str], Any] = {}
    try:
        snapshot = capture_obligation_snapshot(
            root,
            profile,
            settings,
            markdown_parse_memo=markdown_parse_memo,
        )
    except SnapshotCaptureError as exc:
        raise ScanError(str(exc)) from exc
    git_baseline = None
    ratchet_phase_deadline: float | None = None
    if settings.coverage.mode == "ratchet":
        ratchet_phase_deadline = (
            time.monotonic() + settings.coverage.maximum_runtime_seconds
        )
        try:
            git_baseline = load_git_baseline(
                root,
                settings.coverage.ratchet_base,
                limits=_coverage_git_limits(
                    settings,
                    maximum_runtime_seconds=max(
                        ratchet_phase_deadline - time.monotonic(),
                        0.000_001,
                    ),
                ),
            )
        except GitBaselineError as exc:
            return _error(str(exc))
    raw_report, artifacts = scan_check_report_from_snapshot(
        snapshot,
        root.as_posix(),
        profile,
        settings,
        python_parse_memo=python_parse_memo,
        markdown_parse_memo=markdown_parse_memo,
    )
    python_rows = tuple(
        row
        for row in snapshot.files
        if row.path.endswith(".py") and _path_under_any(row.path, profile.code_roots)
    )
    module_names = resolved_python_module_names(
        tuple(row.path for row in python_rows),
        profile,
        snapshot,
    )
    definitions: list[CoverageDefinition] = []
    exemption_facts: list[CoverageExemptionFact] = []
    invalid_exemption_markers: list[tuple[str, int, str | None]] = []
    unscannable_paths: list[str] = []
    for row in python_rows:
        if row.raw_bytes is None:
            unscannable_paths.append(row.path)
            continue
        inventory = python_definition_inventory_bytes(
            row.raw_bytes,
            rel_path=row.path,
            module_name=module_names[row.path],
            parse_memo=python_parse_memo,
        )
        if inventory is None:
            unscannable_paths.append(row.path)
            continue
        role: DefinitionRole = (
            "test" if _path_under_any(row.path, profile.test_roots) else "production"
        )
        projected = coverage_definitions_from_python_inventory(
            inventory,
            role=role,
            tree=_longest_root(row.path, profile.code_roots),
        )
        definitions.extend(projected)
        definition_by_locator = {item.structural_locator: item for item in projected}
        for source_definition in inventory:
            owner = definition_by_locator[source_definition.structural_locator]
            for marker in source_definition.no_spec_markers:
                if not marker.valid or marker.reason is None:
                    invalid_exemption_markers.append(
                        (row.path, marker.line, owner.qualname)
                    )
                    continue
                exemption_facts.append(
                    CoverageExemptionFact(
                        exemption_id=_coverage_stable_id(
                            [
                                "intent-exemption-v1",
                                "inline",
                                row.path,
                                marker.line,
                                marker.reason,
                            ]
                        ),
                        matched_definition_ids=(owner.definition_id,),
                        origin="inline",
                        path=row.path,
                        line=marker.line,
                        selector=owner.structural_locator,
                        reason=marker.reason,
                    )
                )

    for configured in settings.coverage.exemptions:
        matched = tuple(
            sorted(
                item.definition_id
                for item in definitions
                if (
                    item.path == configured.selector
                    if configured.kind == "path"
                    else fnmatch(item.path, configured.selector)
                )
            )
        )
        origin: Literal["config_path", "config_glob"] = (
            "config_path" if configured.kind == "path" else "config_glob"
        )
        exemption_facts.append(
            CoverageExemptionFact(
                exemption_id=_coverage_stable_id(
                    [
                        "intent-exemption-v1",
                        origin,
                        configured.selector,
                    ]
                ),
                matched_definition_ids=matched,
                origin=origin,
                path=(
                    settings.config_path.as_posix()
                    if settings.config_path is not None
                    else ""
                ),
                line=None,
                selector=configured.selector,
                reason=configured.reason,
            )
        )

    changed_definition_ids: frozenset[str] = frozenset()
    baseline_row = None
    policy_events: tuple[PolicyEvent, ...] = ()
    drift_events: tuple[DriftEvent, ...] = ()
    ratchet_definition_locations: dict[str, CoverageDefinition] = {}
    stale_doc_trends: tuple[StaleDocTrend, ...] = ()
    spec_growth: dict[str, object] | None = None
    if git_baseline is not None:
        if settings.config_path is None:
            return _error("ratchet mode requires a repository config file")
        try:
            config_path = settings.config_path.resolve().relative_to(root).as_posix()
        except (OSError, ValueError):
            return _error("ratchet config path must be inside the repository")
        assert ratchet_phase_deadline is not None
        phase_deadline = ratchet_phase_deadline
        revision_projector = IntentRevisionProjector()
        try:
            _coverage_check_deadline(phase_deadline)
        except ValueError as exc:
            return _error(str(exc))
        try:
            revision_blobs = dict(git_baseline.blobs)
            baseline_settings = resolve_repository_config_from_blobs(
                root,
                config_path,
                revision_blobs,
            )
            baseline_profile = _configured_profile(baseline_settings)
            baseline_policy = _coverage_policy_projection(
                baseline_settings,
                baseline_profile,
            )
            previous_policy = baseline_policy
            previous_state = revision_projector.project(
                git_baseline.merge_base,
                revision_blobs,
                repo_root=root,
                settings=baseline_settings,
            )
            baseline_state = previous_state
            ratchet_definition_locations.update(baseline_state.definitions)
            policy_transitions: list[PolicyTransition] = []
            drift_rows: list[DriftEvent] = []
            for transition in git_baseline.transitions:
                _coverage_check_deadline(phase_deadline)
                for path, raw in transition.changes:
                    if raw is None:
                        revision_blobs.pop(path, None)
                    else:
                        revision_blobs[path] = raw
                revision_settings = resolve_repository_config_from_blobs(
                    root,
                    config_path,
                    revision_blobs,
                )
                revision_profile = _configured_profile(revision_settings)
                revision_policy = _coverage_policy_projection(
                    revision_settings,
                    revision_profile,
                )
                revision_state = revision_projector.project(
                    transition.commit,
                    revision_blobs,
                    repo_root=root,
                    settings=revision_settings,
                )
                ratchet_definition_locations.update(revision_state.definitions)
                policy_transitions.append(
                    PolicyTransition(
                        parent_commit=transition.parent_commit,
                        transition_commit=transition.commit,
                        before=previous_policy,
                        after=revision_policy,
                        commit_message=transition.message,
                    )
                )
                for edge_id in sorted(
                    previous_state.drift_states.keys()
                    & revision_state.drift_states.keys()
                ):
                    event = compute_drift_event(
                        DriftTransition(
                            parent_commit=transition.parent_commit,
                            child_commit=transition.commit,
                            before=previous_state.drift_states[edge_id],
                            after=revision_state.drift_states[edge_id],
                            commit_message=transition.message,
                            current_diff=True,
                        )
                    )
                    if event is not None:
                        drift_rows.append(event)
                previous_policy = revision_policy
                previous_state = revision_state
            head_state = previous_state
            current_blobs = _coverage_current_blobs(
                revision_blobs,
                snapshot,
                settings,
                profile,
                root,
            )
            current_state = revision_projector.project(
                f"accepted:{snapshot.snapshot_hash}",
                current_blobs,
                repo_root=root,
                settings=settings,
            )
            ratchet_definition_locations.update(current_state.definitions)
            current_policy = _coverage_policy_projection(settings, profile)
            policy_transitions.append(
                PolicyTransition(
                    parent_commit=git_baseline.head_commit,
                    transition_commit=None,
                    before=previous_policy,
                    after=current_policy,
                )
            )
            for edge_id in sorted(
                previous_state.drift_states.keys() & current_state.drift_states.keys()
            ):
                event = compute_drift_event(
                    DriftTransition(
                        parent_commit=git_baseline.head_commit,
                        child_commit=None,
                        before=previous_state.drift_states[edge_id],
                        after=current_state.drift_states[edge_id],
                        current_diff=True,
                    )
                )
                if event is not None:
                    drift_rows.append(event)
            policy_events = fold_policy_transitions(policy_transitions)
            drift_events = tuple(sorted(drift_rows, key=lambda item: item.event_id))
            changed_definition_ids = frozenset(
                item.definition_id
                for item in definitions
                if (
                    item.definition_id not in baseline_state.definitions
                    or baseline_state.definitions[
                        item.definition_id
                    ].source_projection_sha256
                    != item.source_projection_sha256
                )
            )
            current_policy_sha256 = policy_identity(current_policy)
            baseline_policy_sha256 = policy_identity(baseline_policy)
            source_hashes = {
                row.path: f"sha256:{row.raw_sha256}"
                for row in snapshot.files
                if row.raw_sha256 is not None
            }
            baseline_row = baseline_metadata(
                git_baseline,
                current_snapshot_sha256=f"sha256:{snapshot.snapshot_hash}",
                current_content_sha256=current_content_identity(source_hashes),
                baseline_policy_sha256=baseline_policy_sha256,
                current_policy_sha256=current_policy_sha256,
            )
            changed_sections = {
                key
                for key in baseline_state.section_rows.keys()
                | current_state.section_rows.keys()
                if baseline_state.section_rows.get(key)
                != current_state.section_rows.get(key)
            }
            spec_growth = {
                "changed_sections": len(changed_sections),
                "utf8_byte_delta": sum(
                    current_state.section_rows.get(key, ("", 0))[1]
                    - baseline_state.section_rows.get(key, ("", 0))[1]
                    for key in changed_sections
                ),
                "requirement_ids": sorted(
                    _coverage_stable_id(["intent-requirement-v1", path, section_id])
                    for path, section_id in changed_sections
                ),
            }
            stale_history = build_stale_doc_history(
                git_baseline.history_blobs,
                git_baseline.history_transitions,
                repo_root=root,
                config_path=config_path,
                current_state=head_state,
                history_complete=git_baseline.history_complete,
                projector=revision_projector,
                deadline=phase_deadline,
            )
            stale_doc_trends = stale_history.trends
            _coverage_check_deadline(phase_deadline)
        except (ConfigLoadError, GitBaselineError, ValueError) as exc:
            return _error(str(exc))

    result = classify_intent_coverage(
        tuple(
            sorted(
                definitions,
                key=lambda item: (item.path, item.structural_locator),
            )
        ),
        raw_report,
        exemptions=tuple(exemption_facts),
        inherited_counts=settings.coverage.inherited_counts,
        requirement_rungs={
            (section.path, section.section_id): _coverage_requirement_rung(
                section.path,
                profile,
            )
            for section in raw_report.spec_sections
        },
    )
    floor_results = evaluate_coverage_floors(
        result,
        tuple(
            CoverageFloorFact(
                scope=item.scope,
                direct_target=item.direct,
                accounted_target=item.accounted,
            )
            for item in settings.coverage.floors
        ),
        inherited_counts=settings.coverage.inherited_counts,
    )
    coverage_issues: list[Issue] = []
    for item in result.definitions:
        code = (
            "INTENT_UNCOVERED_DEFINITION"
            if item.classification == "uncovered"
            else (
                "INTENT_INHERITED_ONLY" if item.classification == "inherited" else None
            )
        )
        if code is None:
            continue
        issue, _ = issue_with_policy(
            Issue(
                code=code,
                severity="info",
                path=item.definition.path,
                line=item.definition.start_line,
                symbol=item.definition.qualname,
                context="repository",
                message=(
                    "definition has no direct intent edge"
                    if code == "INTENT_UNCOVERED_DEFINITION"
                    else "definition is covered only by a whole-file intent edge"
                ),
            ),
            effective_policy=settings.diagnostics,
        )
        if issue is not None:
            coverage_issues.append(issue)
        if item.definition.definition_id in changed_definition_ids and (
            item.classification == "uncovered"
            or (
                item.classification == "inherited"
                and not settings.coverage.inherited_counts
            )
        ):
            patch_issue, _ = issue_with_policy(
                Issue(
                    code=code,
                    severity="error",
                    path=item.definition.path,
                    line=item.definition.start_line,
                    symbol=item.definition.qualname,
                    context="patch",
                    message="changed definition lacks direct intent coverage",
                ),
                effective_policy=settings.diagnostics,
            )
            if patch_issue is not None:
                coverage_issues.append(patch_issue)
    for path in unscannable_paths:
        issue, _ = issue_with_policy(
            Issue(
                code="INTENT_COVERAGE_INCOMPLETE",
                severity="info",
                path=path,
                line=None,
                context="repository",
                message="Python file could not be classified for intent coverage",
            ),
            effective_policy=settings.diagnostics,
        )
        if issue is not None:
            coverage_issues.append(issue)
        current_row = next(row for row in python_rows if row.path == path)
        if (
            git_baseline is not None
            and git_baseline.blobs.get(path) != current_row.raw_bytes
        ):
            patch_issue, _ = issue_with_policy(
                Issue(
                    code="INTENT_COVERAGE_INCOMPLETE",
                    severity="error",
                    path=path,
                    line=None,
                    context="patch",
                    message="changed Python file could not be classified",
                ),
                effective_policy=settings.diagnostics,
            )
            if patch_issue is not None:
                coverage_issues.append(patch_issue)
    for path, line, symbol in invalid_exemption_markers:
        issue, _ = issue_with_policy(
            Issue(
                code="INTENT_EXEMPTION_UNREASONED",
                severity="error",
                path=path,
                line=line,
                symbol=symbol,
                message="inline no-spec marker requires a valid nonblank reason",
            ),
            effective_policy=settings.diagnostics,
        )
        if issue is not None:
            coverage_issues.append(issue)
    for exemption in result.exemptions:
        if exemption.state != "unused":
            continue
        issue, _ = issue_with_policy(
            Issue(
                code="INTENT_EXEMPTION_UNUSED",
                severity="warning",
                path=exemption.path,
                line=exemption.line,
                message=f"intent exemption matches no definition: {exemption.selector}",
            ),
            effective_policy=settings.diagnostics,
        )
        if issue is not None:
            coverage_issues.append(issue)
    for requirement in result.requirements:
        if (
            requirement.rung != "active"
            or requirement.implementation_state != "declared_without_live_owner"
        ):
            continue
        issue, _ = issue_with_policy(
            Issue(
                code="INTENT_REQUIREMENT_UNIMPLEMENTED",
                severity="info",
                path=requirement.path,
                line=None,
                section_id=requirement.section_id,
                message="implementation mappings resolve to no live definition owner",
            ),
            effective_policy=settings.diagnostics,
        )
        if issue is not None:
            coverage_issues.append(issue)
    for floor in floor_results:
        if floor.passes:
            continue
        issue, _ = issue_with_policy(
            Issue(
                code="INTENT_COVERAGE_FLOOR_REGRESSION",
                severity="error",
                path=floor.scope,
                line=None,
                message="intent coverage is below a configured floor",
            ),
            effective_policy=settings.diagnostics,
        )
        if issue is not None:
            coverage_issues.append(issue)
    for event in drift_events:
        if event.acknowledged:
            continue
        definition = ratchet_definition_locations.get(event.definition_id)
        if definition is None:
            return _error(f"drift event has no retained definition: {event.event_id}")
        issue, _ = issue_with_policy(
            Issue(
                code="INTENT_DRIFT_SUSPECT",
                severity="info",
                path=definition.path,
                line=definition.start_line,
                symbol=definition.qualname,
                message="implementation changed without governing evidence movement",
            ),
            effective_policy=settings.diagnostics,
        )
        if issue is not None:
            coverage_issues.append(issue)
    combined_report = dataclasses.replace(
        raw_report,
        issues=(*raw_report.issues, *coverage_issues),
    )
    pipeline = apply_check_policy(
        combined_report,
        artifacts,
        profile,
        settings,
    )
    policy_issues = tuple(
        Issue(
            code="INTENT_COVERAGE_POLICY_REGRESSION",
            severity="error",
            path=(
                settings.config_path.resolve().relative_to(root).as_posix()
                if settings.config_path is not None
                else ""
            ),
            line=None,
            message=(
                "unacknowledged intent coverage policy transition "
                f"{event.key}: {event.event_id}"
            ),
        )
        for event in policy_events
        if not event.acknowledged
    )
    from backstitch.models import issue_sort_key

    issues = tuple(
        sorted(
            (*pipeline.report.issues, *policy_issues),
            key=issue_sort_key,
        )
    )
    unscannable_files = tuple(
        CoverageUnscannableFile(
            path=path,
            role=(
                "test" if _path_under_any(path, profile.test_roots) else "production"
            ),
            tree=_longest_root(path, profile.code_roots),
            issue_identities=tuple(
                sorted(
                    {
                        (issue.code, issue.path, issue.line)
                        for issue in raw_report.issues
                        if issue.path == path
                    },
                    key=lambda row: (row[0], row[1], row[2] or 0),
                )
            ),
        )
        for path in sorted(unscannable_paths)
    )
    payload = build_coverage_report(
        result,
        profile=profile.name,
        repo_root=root.as_posix(),
        mode=settings.coverage.mode,
        inherited_counts=settings.coverage.inherited_counts,
        issues=issues,
        floors=floor_results,
        unscannable_files=unscannable_files,
        baseline=baseline_row,
        changed_definition_ids=changed_definition_ids,
        policy_events=policy_events,
        drift_events=drift_events,
        stale_doc_trends=stale_doc_trends,
        spec_growth=spec_growth,
    )
    if settings.coverage.format == "json":
        rendered = render_coverage_json(
            payload,
            source_result=result,
            inherited_counts=settings.coverage.inherited_counts,
            floors=floor_results,
            unscannable_files=unscannable_files,
            issues=issues,
            baseline=baseline_row,
            changed_definition_ids=changed_definition_ids,
            policy_events=policy_events,
            drift_events=drift_events,
            stale_doc_trends=stale_doc_trends,
            spec_growth=spec_growth,
        )
    else:
        summary = payload["summary"]
        definition_rows = {
            item["definition_id"]: item for item in payload["definitions"]
        }
        worklist_lines = "".join(
            "uncovered "
            f"{definition_rows[definition_id]['role']} "
            f"{definition_rows[definition_id]['path']} "
            f"{definition_rows[definition_id]['structural_locator']}\n"
            for definition_id in payload["worklist"]
        )
        rendered = (
            "Intent coverage: "
            f"{summary['direct']} direct, {summary['inherited']} inherited, "
            f"{summary['exempt']} exempt, {summary['uncovered']} uncovered, "
            f"{summary['total']} total\n"
            f"{worklist_lines}"
        )
    output = (
        Path(settings.coverage.output) if settings.coverage.output is not None else None
    )
    if output is not None:
        try:
            atomic_replace_bytes(output, rendered.encode("utf-8"))
        except OSError as exc:
            return _error(f"cannot write --output {output}: {exc}")
    else:
        sys.stdout.write(rendered)
    fail_on = set(settings.diagnostics.fail_on)
    return (
        1 if policy_issues or any(issue.severity in fail_on for issue in issues) else 0
    )


def _path_under_any(path: str, roots: Sequence[str]) -> bool:
    pure = PurePosixPath(path)
    return any(pure.is_relative_to(PurePosixPath(root)) for root in roots)


def _coverage_stable_id(preimage: object) -> str:
    from backstitch.canonical import canonical_json_bytes

    return "sha256:" + hashlib.sha256(canonical_json_bytes(preimage)).hexdigest()


def _coverage_requirement_rung(
    path: str,
    profile: ProfileConfig,
) -> Literal["active", "planned", "exploratory", "meta"]:
    if any(fnmatch(path, pattern) for pattern in profile.meta_spec_globs):
        return "meta"
    if any(fnmatch(path, pattern) for pattern in profile.planned_spec_globs):
        return "planned"
    if any(fnmatch(path, pattern) for pattern in profile.exploratory_spec_globs):
        return "exploratory"
    return "active"


def _coverage_git_limits(
    settings: BackstitchSettings,
    *,
    maximum_runtime_seconds: float | None = None,
) -> Any:
    from backstitch.git_baseline import GitLimits

    coverage = settings.coverage
    return GitLimits(
        maximum_baseline_files=coverage.maximum_baseline_files,
        maximum_file_bytes=coverage.maximum_file_bytes,
        maximum_baseline_bytes=coverage.maximum_baseline_bytes,
        maximum_history_commits=coverage.maximum_history_commits,
        maximum_git_command_seconds=coverage.maximum_git_command_seconds,
        maximum_git_commands=coverage.maximum_git_commands,
        maximum_git_output_bytes=coverage.maximum_git_output_bytes,
        maximum_commit_message_bytes=coverage.maximum_commit_message_bytes,
        maximum_runtime_seconds=(
            coverage.maximum_runtime_seconds
            if maximum_runtime_seconds is None
            else maximum_runtime_seconds
        ),
    )


def _coverage_policy_projection(
    settings: BackstitchSettings,
    profile: ProfileConfig,
) -> dict[str, object]:
    """Project the exact closed COV-5 policy mapping."""

    coverage = settings.coverage
    diagnostics = settings.diagnostics
    lint = settings.lint
    return {
        "schema": "intent-coverage-policy-v1",
        "profile": {
            "name": settings.profile,
            "spec_roots": list(profile.spec_roots),
            "code_roots": list(profile.code_roots),
            "test_roots": list(profile.test_roots),
            "planned_spec_globs": list(profile.planned_spec_globs),
            "exploratory_spec_globs": list(profile.exploratory_spec_globs),
            "meta_spec_globs": list(profile.meta_spec_globs),
            "process_spec_globs": list(
                settings.profile_overrides.process_spec_globs or ()
            ),
        },
        "exclude": list(settings.exclude),
        "coverage": {
            "mode": coverage.mode,
            "granularity": coverage.granularity,
            "inherited_counts": coverage.inherited_counts,
            "ratchet_base": coverage.ratchet_base,
            "exemptions": [
                {
                    "id": _coverage_stable_id(
                        [
                            "intent-exemption-v1",
                            ("config_path" if item.kind == "path" else "config_glob"),
                            item.selector,
                        ]
                    ),
                    "kind": item.kind,
                    "selector": item.selector,
                    "reason": item.reason,
                }
                for item in coverage.exemptions
            ],
            "floors": [
                {
                    "scope": item.scope,
                    "direct": item.direct,
                    "accounted": item.accounted,
                }
                for item in sorted(coverage.floors, key=lambda row: row.scope)
            ],
            "maximum_baseline_files": coverage.maximum_baseline_files,
            "maximum_file_bytes": coverage.maximum_file_bytes,
            "maximum_baseline_bytes": coverage.maximum_baseline_bytes,
            "maximum_history_commits": coverage.maximum_history_commits,
            "maximum_git_command_seconds": coverage.maximum_git_command_seconds,
            "maximum_git_commands": coverage.maximum_git_commands,
            "maximum_git_output_bytes": coverage.maximum_git_output_bytes,
            "maximum_commit_message_bytes": coverage.maximum_commit_message_bytes,
            "maximum_runtime_seconds": coverage.maximum_runtime_seconds,
        },
        "diagnostics": {
            "default_level": diagnostics.default_level,
            "fail_on": list(diagnostics.fail_on),
            "suppressible_levels": list(diagnostics.suppressible_levels),
            "levels": [
                {"selectors": list(item.selectors), "level": item.level}
                for item in diagnostics.levels
            ],
        },
        "suppressions": {
            "warn_unused_ignores": lint.warn_unused_ignores,
            "require_suppression_declarations": (lint.require_suppression_declarations),
            "per_file_ignores": [
                {"selector": selector, "codes": list(codes)}
                for selector, codes in sorted(lint.per_file_ignores.items())
            ],
            "per_section_ignores": [
                {"selector": selector, "codes": list(codes)}
                for selector, codes in sorted(lint.per_section_ignores.items())
            ],
            "rules": [
                {
                    "mechanism": item.mechanism,
                    "provenance": item.provenance,
                    "path": item.path,
                    "sections": list(item.sections),
                    "codes": list(item.codes),
                    "declaration": item.declaration,
                    "origin": {
                        "source": item.origin.source,
                        "position": item.origin.position,
                        "line": item.origin.line,
                    },
                }
                for item in lint.suppressions
            ],
        },
    }


def _coverage_current_blobs(
    head_blobs: dict[str, bytes],
    snapshot: Any,
    settings: BackstitchSettings,
    profile: ProfileConfig,
    root: Path,
) -> dict[str, bytes]:
    """Overlay the accepted snapshot on HEAD without reopening source paths."""

    current = dict(head_blobs)
    roots = tuple(
        dict.fromkeys(
            (
                *profile.spec_roots,
                *profile.plan_roots,
                *profile.code_roots,
                *profile.test_roots,
            )
        )
    )
    for path in tuple(current):
        if _path_under_any(path, roots) and snapshot.path_kind(path) != "regular_file":
            current.pop(path)
    for row in snapshot.files:
        if row.raw_bytes is None:
            current.pop(row.path, None)
        else:
            current[row.path] = row.raw_bytes
    for identity in settings.config_layer_identities:
        try:
            path = Path(identity.path).resolve().relative_to(root).as_posix()
        except (OSError, ValueError) as exc:
            raise ValueError(
                "ratchet config layer must be inside the repository"
            ) from exc
        current[path] = identity.raw_bytes
    return current


def _coverage_check_deadline(deadline: float) -> None:
    if time.monotonic() > deadline:
        raise ValueError("intent coverage Git phase exceeded runtime budget")


def _longest_root(path: str, roots: Sequence[str]) -> str:
    pure = PurePosixPath(path)
    matches = [
        PurePosixPath(root)
        for root in roots
        if pure.is_relative_to(PurePosixPath(root))
    ]
    if not matches:
        raise ValueError(f"Python path is outside configured code roots: {path}")
    longest = max(len(root.parts) for root in matches)
    owners = sorted({root.as_posix() for root in matches if len(root.parts) == longest})
    if len(owners) != 1:
        raise ConfigLoadError(
            f"Python path has equal-specificity code-root owners: {path}"
        )
    return owners[0]


def _cmd_packets(args: argparse.Namespace, settings: BackstitchSettings) -> int:
    from backstitch.analysis_packets import (
        SourceAlignedPacketError,
        generate_source_aligned_packets,
        render_packets_jsonl,
    )
    from backstitch.evidence_discovery import EvidenceDiscoveryError
    from backstitch.obligation_runtime import build_obligation_runtime
    from backstitch.repository_snapshot import SnapshotCaptureError
    from backstitch.semantic_reports import (
        ArtifactPublicationError,
        PacketReportError,
        build_source_packet_report,
        publish_artifact_set,
    )

    if args.report is not None:
        if args.kind != "all":
            return _error("packet --report requires --kind all")
        try:
            same_path = args.output.resolve(strict=False) == args.report.resolve(
                strict=False
            )
        except (OSError, RuntimeError) as exc:
            return _error(f"cannot resolve packet output/report paths: {exc}")
        if same_path:
            return _error("packet --output and --report paths must be distinct")

    profile = _profile_from(args, settings)
    try:
        runtime = build_obligation_runtime(args.repo_root, profile, settings)
    except SnapshotCaptureError as exc:
        return _error(str(exc))
    pipeline = runtime.pipeline
    for warning in pipeline.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    fail_on = set(settings.diagnostics.fail_on)
    if any(issue.severity in fail_on for issue in pipeline.report.issues):
        sys.stdout.write(render_json(pipeline.report))
        return 1
    try:
        population = generate_source_aligned_packets(
            runtime,
            require_complete_corpus=args.report is not None,
            kind=args.kind,
        )
    except SourceAlignedPacketError as exc:
        return _error(f"{exc.code}: {exc}")
    except EvidenceDiscoveryError as exc:
        details = json.dumps(exc.details, sort_keys=True, separators=(",", ":"))
        return _error(f"{exc.code}: {exc}; details={details}")
    packets = population
    rendered = render_packets_jsonl(packets).encode("utf-8")
    try:
        packet_report = (
            build_source_packet_report(runtime, packet_jsonl=rendered)
            if args.report is not None
            else None
        )
    except PacketReportError as exc:
        return _error(str(exc))
    try:
        artifacts = [(args.output, rendered)]
        if args.report is not None:
            assert packet_report is not None
            artifacts.append((args.report, packet_report.to_json_bytes()))
        publish_artifact_set(artifacts)
    except ArtifactPublicationError as exc:
        published_text = (
            ", ".join(path.as_posix() for path in exc.published_paths)
            if exc.published_paths
            else "none"
        )
        return _error(
            "packet publication failed at "
            f"{exc.failed_path.as_posix()}; already published: "
            f"{published_text}; {exc}"
        )
    print(f"wrote {len(packets)} packets to {args.output}", file=sys.stderr)
    return 0


def _cmd_analyze(args: argparse.Namespace, settings: BackstitchSettings) -> int:
    # Lazy imports preserve the structural no-provider boundary for deterministic
    # commands ([SC-8]).
    from backstitch.analysis_llm import default_provider_adapter, resolve_model_name
    from backstitch.analysis_packets import (
        SourceAlignedPacketError,
        generate_source_aligned_packets,
        render_packets_jsonl,
    )
    from backstitch.artifact_contracts import load_packets_bytes
    from backstitch.evidence_discovery import EvidenceDiscoveryError
    from backstitch.obligation_runtime import (
        build_obligation_runtime,
        capture_obligation_snapshot,
    )
    from backstitch.repository_snapshot import SnapshotCaptureError
    from backstitch.semantic_analysis import (
        SemanticAnalysisRequest,
        required_independent_qualification_problem,
        resolve_semantic_settings,
        resolve_verification_settings,
        run_semantic_analysis,
    )
    from backstitch.semantic_cache import ProviderAdapter
    from backstitch.semantic_policy import materialize_semantic_policy
    from backstitch.semantic_reports import (
        ArtifactPublicationError,
        PacketReportError,
        build_source_packet_report,
        load_packet_report,
        publish_artifact_set,
        validate_packet_report,
    )
    from backstitch.semantic_verification import (
        verification_response_schema_from_prompt,
    )

    current_mode = args.repo_root is not None
    if current_mode:
        if args.packet_report is not None or args.compare_repo_root is not None:
            return _error(
                "current analyze forbids --packet-report and --compare-repo-root"
            )
        if (args.packets_output is None) != (args.packet_report_output is None):
            return _error(
                "--packets-output and --packet-report-output must be supplied together"
            )
        anchor = args.repo_root.resolve()
    else:
        assert args.packets is not None
        if args.packet_report is None:
            return _error("historical analyze requires --packet-report")
        if args.packets_output is not None or args.packet_report_output is not None:
            return _error("historical analyze forbids packet output flags")
        anchor = args.packets.resolve().parent

    analyze_settings = settings.analyze
    model_name = resolve_model_name(
        None,
        configured=analyze_settings.adapter_model_id or analyze_settings.model or None,
    )
    resolved = resolve_semantic_settings(analyze_settings)
    resolved_verify = resolve_verification_settings(settings.verify, resolved)
    policy = materialize_semantic_policy(
        settings.diagnostics,
        settings.policy_rule_origins,
        settings.config_layers,
    )
    qualification_problem = required_independent_qualification_problem(
        policy,
        resolved_verify,
        getattr(settings.verify, "eval", None),
    )
    if qualification_problem is not None:
        return _analysis_problem_error(qualification_problem)

    def build_adapter() -> ProviderAdapter:
        return default_provider_adapter(
            model_name,
            provider_identity=resolved.provider_identity,
            request_identity=resolved.request_identity,
        )

    adapter_factory = build_adapter if resolved.cache_mode != "require" else None

    verification_adapter_factory: Any = None
    if resolved_verify is not None and resolved_verify.cache_mode != "require":

        def build_verification_adapter() -> ProviderAdapter:
            return default_provider_adapter(
                resolved_verify.provider_identity.model_id,
                provider_identity=resolved_verify.provider_identity,
                request_identity=resolved_verify.request_identity,
                response_schema_builder=verification_response_schema_from_prompt,
            )

        verification_adapter_factory = build_verification_adapter

    profile = _configured_profile(settings)
    if current_mode:
        _validate_test_root_containment(anchor, profile)
        output_paths = tuple(
            path
            for path in (
                args.packets_output,
                args.packet_report_output,
                args.output,
                args.report,
            )
            if path is not None
        )
        resolved_outputs = tuple(path.resolve(strict=False) for path in output_paths)
        if len(resolved_outputs) != len(set(resolved_outputs)):
            return _error("every requested analyze output path must be distinct")
        semantic_roots = tuple(
            (anchor / root).resolve(strict=False)
            for root in (
                *profile.spec_roots,
                *profile.plan_roots,
                *profile.code_roots,
                *profile.test_roots,
            )
        )
        for output in resolved_outputs:
            if any(
                output == root or output.is_relative_to(root) for root in semantic_roots
            ):
                return _error(
                    f"analyze output overlaps a semantic input root: {output}"
                )
        mutable_paths = [*resolved_outputs, resolved.cache_path.resolve(strict=False)]
        if resolved_verify is not None:
            mutable_paths.append(resolved_verify.cache_path.resolve(strict=False))
        config_paths = {
            Path(item.path).resolve(strict=False)
            for item in settings.config_layer_identities
        }
        for mutable in mutable_paths:
            if mutable in config_paths:
                return _error(
                    f"analyze mutable path overlaps selected configuration: {mutable}"
                )
            if any(
                mutable == root or mutable.is_relative_to(root)
                for root in semantic_roots
            ):
                return _error(
                    f"analyze mutable path overlaps a semantic input root: {mutable}"
                )
        operational_exclusions: list[str] = []
        for path in mutable_paths:
            if path.is_relative_to(anchor):
                relative = path.relative_to(anchor).as_posix()
                operational_exclusions.extend(
                    (
                        relative,
                        f"{Path(relative).parent.as_posix()}/.{Path(relative).name}.*.tmp",
                    )
                )
        try:
            runtime = build_obligation_runtime(
                anchor,
                profile,
                settings,
                operational_exclusions=tuple(operational_exclusions),
            )
        except SnapshotCaptureError as exc:
            return _error(str(exc))
        fail_on = set(settings.diagnostics.fail_on)
        if any(issue.severity in fail_on for issue in runtime.pipeline.report.issues):
            rendered = (
                render_json(runtime.pipeline.report)
                if args.format == "json"
                else render_text(runtime.pipeline.report)
            )
            sys.stdout.write(rendered)
            return 1
        try:
            packet_rows = generate_source_aligned_packets(runtime)
            packet_bytes = render_packets_jsonl(packet_rows).encode("utf-8")
            packet_report = build_source_packet_report(
                runtime, packet_jsonl=packet_bytes
            )
        except SourceAlignedPacketError as exc:
            return _error(f"{exc.code}: {exc}")
        except EvidenceDiscoveryError as exc:
            details = json.dumps(exc.details, sort_keys=True, separators=(",", ":"))
            return _error(f"{exc.code}: {exc}; details={details}")
        except PacketReportError as exc:
            return _error(str(exc))
        validated_packets = load_packets_bytes(
            packet_bytes, source="current repository"
        )
        run = run_semantic_analysis(
            SemanticAnalysisRequest(
                packets=validated_packets,
                packet_jsonl_sha256=hashlib.sha256(packet_bytes).hexdigest(),
                packet_report=packet_report,
                settings=resolved,
                policy=policy,
                adapter_factory=adapter_factory,
                result_path=None,
                report_path=None,
                verification_settings=resolved_verify,
                evaluation_settings=getattr(settings.verify, "eval", None),
                verification_adapter_factory=verification_adapter_factory,
                scope="current_repository",
                semantic_status=(
                    "not_run_all_skipped" if not validated_packets else "evaluated"
                ),
                artifact_currentness="current",
                source_provenance="captured_current",
            )
        )
        if run.exit_code == 2:
            for line in run.stderr_lines:
                print(line, file=sys.stderr)
            return 2

        class RepositoryChangedDuringAnalysis(RuntimeError):
            pass

        artifacts = tuple(
            (final_path, content)
            for final_path, content in (
                (args.packets_output, packet_bytes),
                (args.packet_report_output, packet_report.to_json_bytes()),
                (args.output, run.result_jsonl),
                (args.report, run.report_json),
            )
            if final_path is not None
        )

        def require_current_snapshot() -> None:
            final_snapshot = capture_obligation_snapshot(
                anchor,
                profile,
                settings,
                operational_exclusions=tuple(operational_exclusions),
            )
            if final_snapshot.snapshot_hash != runtime.snapshot.snapshot_hash:
                raise RepositoryChangedDuringAnalysis

        try:
            publish_artifact_set(
                artifacts,
                before_publish=require_current_snapshot,
            )
        except SnapshotCaptureError as exc:
            return _error(str(exc))
        except RepositoryChangedDuringAnalysis:
            return _error("repository source changed during current analysis")
        except ArtifactPublicationError as exc:
            published_text = (
                ", ".join(path.as_posix() for path in exc.published_paths)
                if exc.published_paths
                else "none"
            )
            return _error(
                "current analyze publication failed at "
                f"{exc.failed_path.as_posix()}; already published: "
                f"{published_text}; {exc}"
            )
    else:
        assert args.packets is not None
        assert args.packet_report is not None
        inputs = {
            args.packets.resolve(strict=False),
            args.packet_report.resolve(strict=False),
        }
        outputs = tuple(
            path.resolve(strict=False)
            for path in (args.output, args.report)
            if path is not None
        )
        if len(outputs) != len(set(outputs)) or any(path in inputs for path in outputs):
            return _error("historical analyze input and output paths must be distinct")
        packet_bytes = args.packets.read_bytes()
        validated_packets = load_packets_bytes(packet_bytes, source=args.packets)
        packet_report = load_packet_report(
            args.packet_report,
            maximum_bytes=settings.obligations.maximum_packet_report_bytes,
        )
        report_schema = packet_report.to_dict()["schema_version"]
        packet_report = validate_packet_report(
            packet_report,
            packet_jsonl=packet_bytes,
            packets=validated_packets if report_schema == 2 else None,
        )
        artifact_currentness = "unverifiable"
        source_provenance = "claimed_unverified"
        if args.compare_repo_root is not None:
            compare_root = args.compare_repo_root.resolve()
            _validate_test_root_containment(compare_root, profile)
            try:
                comparison = capture_obligation_snapshot(
                    compare_root, profile, settings
                )
            except SnapshotCaptureError as exc:
                return _error(str(exc))
            claimed_snapshot = packet_report.to_dict()["source_snapshot"][
                "snapshot_hash"
            ]
            if comparison.snapshot_hash == claimed_snapshot:
                artifact_currentness = "current"
                source_provenance = "compared_match"
            else:
                artifact_currentness = "stale"
                source_provenance = "compared_mismatch"
        run = run_semantic_analysis(
            SemanticAnalysisRequest(
                packets=validated_packets,
                packet_jsonl_sha256=hashlib.sha256(packet_bytes).hexdigest(),
                packet_report=packet_report,
                settings=resolved,
                policy=policy,
                adapter_factory=adapter_factory,
                result_path=args.output,
                report_path=args.report,
                verification_settings=resolved_verify,
                evaluation_settings=getattr(settings.verify, "eval", None),
                verification_adapter_factory=verification_adapter_factory,
                scope="historical_snapshot",
                semantic_status="historical_replay",
                artifact_currentness=cast(Any, artifact_currentness),
                source_provenance=cast(Any, source_provenance),
            )
        )
    for line in run.stderr_lines:
        print(line, file=sys.stderr)
    if args.format == "json" and run.report_json:
        sys.stdout.buffer.write(run.report_json)
    elif run.report:
        print(
            f"semantic analysis {run.report['status']}: "
            f"{run.report['result_count']} result(s), "
            f"{len(run.diagnostics)} finding(s)"
        )
    return run.exit_code


def _cmd_eval(args: argparse.Namespace, settings: BackstitchSettings) -> int:
    # Like analyze, eval is an explicitly model-touching command. Keep all
    # provider imports inside this handler so deterministic commands retain
    # the structural no-llm guarantee ([SC-8]).
    from backstitch.analysis_llm import default_provider_adapter, resolve_model_name
    from backstitch.semantic_analysis import (
        resolve_semantic_settings,
        resolve_verification_settings,
    )
    from backstitch.semantic_cache import ProviderAdapter
    from backstitch.semantic_eval import (
        SemanticEvalError,
        SemanticEvalRequest,
        run_semantic_eval,
    )
    from backstitch.semantic_verification import (
        verification_response_schema_from_prompt,
    )
    from backstitch.settings import VerifySettings

    try:
        corpus_path = args.corpus.resolve()
        output_path = args.output.resolve(strict=False)
    except OSError as exc:
        raise ConfigLoadError(f"eval path resolution failed: {exc}") from exc
    if corpus_path == output_path:
        raise ConfigLoadError("eval --corpus and --output paths must be distinct")

    model_name = resolve_model_name(
        None,
        configured=settings.analyze.adapter_model_id or settings.analyze.model or None,
    )
    resolved = resolve_semantic_settings(settings.analyze)
    resolved_verify = resolve_verification_settings(settings.verify, resolved)
    if resolved_verify is None or not isinstance(settings.verify, VerifySettings):
        raise ConfigLoadError("semantic eval requires verify.enabled = true")
    eval_settings = settings.verify.eval
    if eval_settings is None:
        raise ConfigLoadError("semantic eval requires the complete verify.eval table")
    if eval_settings.qualification_corpus.strip() and (
        Path(eval_settings.qualification_corpus).resolve() != corpus_path
    ):
        raise ConfigLoadError(
            "configured verify.eval qualification_corpus does not match --corpus"
        )
    if eval_settings.qualification_report.strip() and (
        Path(eval_settings.qualification_report).resolve(strict=False) == output_path
    ):
        raise ConfigLoadError(
            "eval --output must not overlap configured verify.eval qualification_report"
        )
    config_paths = {
        Path(item.path).resolve(strict=False)
        for item in settings.config_layer_identities
    }
    if output_path in config_paths:
        raise ConfigLoadError("eval --output overlaps selected configuration")
    if eval_settings.qualification_report.strip() and (
        Path(eval_settings.qualification_report).resolve(strict=False) in config_paths
    ):
        raise ConfigLoadError(
            "configured verify.eval qualification_report overlaps selected "
            "configuration"
        )
    try:
        if args.output.is_symlink() or (
            args.output.exists() and not args.output.is_file()
        ):
            raise ConfigLoadError(
                "eval --output must be absent or a regular non-symlink file"
            )
    except OSError as exc:
        raise ConfigLoadError(f"cannot inspect eval --output: {exc}") from exc

    def build_adapter() -> ProviderAdapter:
        return default_provider_adapter(
            model_name,
            provider_identity=resolved.provider_identity,
            request_identity=resolved.request_identity,
        )

    def build_verification_adapter() -> ProviderAdapter:
        return default_provider_adapter(
            resolved_verify.provider_identity.model_id,
            provider_identity=resolved_verify.provider_identity,
            request_identity=resolved_verify.request_identity,
            response_schema_builder=verification_response_schema_from_prompt,
        )

    try:
        run = run_semantic_eval(
            SemanticEvalRequest(
                manifest_path=corpus_path,
                output_path=output_path,
                settings=resolved,
                verification_settings=resolved_verify,
                eval_settings=eval_settings,
                adapter_factory=build_adapter,
                verification_adapter_factory=build_verification_adapter,
            )
        )
    except SemanticEvalError as exc:
        raise SemanticEvalError(f"{args.corpus}: {exc}") from exc
    for line in run.stderr_lines:
        print(line, file=sys.stderr)
    return run.exit_code


def _cmd_summarize(args: argparse.Namespace) -> int:
    from backstitch.analysis_results import (
        load_analysis_results,
        packet_identities_from_report,
        render_analysis_summary,
    )
    from backstitch.artifact_contracts import load_deterministic_report

    report_data = load_deterministic_report(args.deterministic_report)
    load = load_analysis_results(
        args.analysis_results.read_text(encoding="utf-8"),
        packet_identities_from_report(report_data),
    )
    if load.errors:
        return _error("invalid analysis results: " + "; ".join(load.errors))
    sys.stdout.write(render_analysis_summary(report_data["summary"], load))
    return 0


def _cmd_config(args: argparse.Namespace, settings: BackstitchSettings) -> int:
    from backstitch.exclusions import validate_lint_codes
    from backstitch.settings import settings_to_json

    if args.config_command == "show":
        # [EXC-4]: `config show` follows load strictness -- an
        # invalid suppression code that would fail `check` must not print
        # as effective configuration with exit 0.
        for diagnostic in validate_lint_codes(
            settings.lint, allow_unknown=settings.allow_unknown_keys
        ):
            print(f"warning: {diagnostic.message}", file=sys.stderr)
        sys.stdout.write(settings_to_json(settings))
        return 0
    if settings.config_path is not None:
        print(settings.config_path)
    return 0


def _cmd_cache(args: argparse.Namespace) -> int:
    from backstitch.semantic_cache import cleanup_lock

    if args.config is not None or args.no_config:
        raise ValueError("cache cleanup-lock does not accept configuration flags")
    if args.cache_command != "cleanup-lock":
        raise ValueError(f"unknown cache command: {args.cache_command}")
    result = cleanup_lock(
        cache_path=args.cache_path,
        analysis_key=args.analysis_key,
        review_key=args.review_key,
        verify_key=args.verify_key,
        lock_stale_seconds=args.lock_stale_seconds,
        reason=args.reason,
    )
    print(result.audit_path)
    return 0


def _cmd_doctor(args: argparse.Namespace, settings: BackstitchSettings) -> int:
    # Lazy import in the handler only: doctor is an llm-touching command
    # like analyze; check/packets stay structurally incapable of importing
    # llm ([SC-8]), and doctor.py itself defers llm to check functions.
    from backstitch.doctor import (
        doctor_exit_code,
        render_json,
        render_text,
        run_doctor,
    )

    results = run_doctor(
        settings.analyze.adapter_model_id or settings.analyze.model or None,
        model_source=settings.analyze_model_source,
        probe=args.probe,
    )
    rendered = render_json(results) if args.format == "json" else render_text(results)
    sys.stdout.write(rendered)
    return doctor_exit_code(results)


def _cmd_guide(args: argparse.Namespace) -> int:
    from backstitch.alignment_guide import render_alignment_guide

    if args.guide_command != "alignment":
        raise ValueError(f"unknown guide: {args.guide_command}")
    sys.stdout.write(render_alignment_guide(args.format))
    return 0


def _obligation_operation(args: argparse.Namespace) -> str:
    if args.obligation_id == "list":
        return "obligation.list"
    if args.summarize_evidence:
        return "obligation.summarize_evidence"
    if args.find_evidence:
        return "obligation.find_evidence"
    if args.candidate is not None:
        return "obligation.get_candidate"
    return "obligation.get"


def _emit_obligation_problem(
    args: argparse.Namespace,
    envelope: dict[str, Any],
    *,
    resolved_root: str,
) -> None:
    from backstitch.obligation_api import render_envelope_json, render_envelope_text

    if args.format == "json":
        sys.stdout.write(render_envelope_json(envelope))
    else:
        sys.stderr.write(render_envelope_text(envelope, resolved_root=resolved_root))


def _render_obligation_problem(
    args: argparse.Namespace,
    *,
    operation: str,
    code: str,
    message: str,
    action: str,
    details: dict[str, object],
    snapshot: dict[str, object] | None = None,
) -> int:
    from backstitch.obligation_api import (
        OperationProblemCode,
        problem_envelope,
    )

    envelope = problem_envelope(
        operation=operation,
        snapshot=snapshot,
        code=cast(OperationProblemCode, code),
        message=message,
        action=action,
        details=details,
    )
    _emit_obligation_problem(
        args,
        envelope,
        resolved_root=args.repo_root.resolve(strict=False).as_posix(),
    )
    return 2


def _validate_obligation_invocation(args: argparse.Namespace) -> None:
    def validate_text(
        name: str, value: str | None, maximum_bytes: int | None = None
    ) -> None:
        if value is None:
            return
        if maximum_bytes is not None and len(value.encode("utf-8")) > maximum_bytes:
            raise ValueError(f"{name} exceeds {maximum_bytes} UTF-8 bytes")
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError(f"{name} must not contain control characters")

    validate_text("OBLIGATION_ID", args.obligation_id)
    validate_text("--candidate", args.candidate)
    validate_text("--cursor", args.cursor)
    validate_text("--repo-root", args.repo_root.as_posix(), 4096)
    validate_text(
        "--config",
        args.config.as_posix() if args.config is not None else None,
        4096,
    )
    if args.candidate is not None and candidate_ref_digest(args.candidate) is None:
        raise ValueError(
            "--candidate must be candidate:sha256: plus 64 lowercase hex digits"
        )
    if args.obligation_id == "list" and (
        args.summarize_evidence or args.find_evidence or args.candidate is not None
    ):
        raise ValueError("obligation list does not accept a detail selector")
    if args.obligation_id != "list":
        paginated = args.summarize_evidence or args.find_evidence
        if not paginated and (args.cursor is not None or args.limit is not None):
            raise ValueError(
                "--cursor and --limit require --summarize-evidence or --find-evidence"
            )


def _cmd_obligation(
    args: argparse.Namespace,
    settings: BackstitchSettings | None,
    *,
    config_error: ConfigLoadError | None = None,
) -> int:
    from backstitch.repository_snapshot import SnapshotCaptureError

    operation = _obligation_operation(args)
    try:
        if config_error is not None:
            raise config_error
        assert settings is not None
        _validate_obligation_invocation(args)
        return _run_obligation(args, settings)
    except SnapshotCaptureError as exc:
        if exc.kind == "unsupported_platform":
            return _render_obligation_problem(
                args,
                operation=operation,
                code="UNSUPPORTED_PLATFORM",
                message="This platform cannot capture a repository snapshot safely.",
                action="Run Backstitch on a supported POSIX platform.",
                details={"platform": sys.platform},
            )
        if exc.kind == "snapshot_unstable":
            return _render_obligation_problem(
                args,
                operation=operation,
                code="SNAPSHOT_UNSTABLE",
                message="The repository changed during bounded snapshot capture.",
                action="Retry after concurrent repository writes have stopped.",
                details={"attempts": exc.attempts or 0},
            )
        if exc.kind == "budget_exceeded":
            return _render_obligation_problem(
                args,
                operation=operation,
                code="BUDGET_EXHAUSTED",
                message="Repository snapshot capture exceeded a configured budget.",
                action="Raise the named deterministic budget or narrow configured roots.",
                details={
                    "budget": exc.budget or "snapshot_files",
                    "limit": exc.limit or 0,
                    "observed": exc.observed or 0,
                },
            )
        field = "repo_root" if exc.kind == "invalid_root" else "path"
        reason = {
            "invalid_root": "repository root is not an existing readable directory",
            "invalid_path": "repository path configuration is invalid",
            "symlink": "repository input cannot be a symlink",
            "not_regular": "repository input must be a regular file or directory",
        }.get(exc.kind, "repository input is invalid")
        return _render_obligation_problem(
            args,
            operation=operation,
            code="INVALID_INPUT",
            message="Repository input is not valid for safe snapshot capture.",
            action="Correct the repository root, path, or source object and retry.",
            details={"field": field, "reason": reason},
        )
    except ConfigLoadError:
        return _render_obligation_problem(
            args,
            operation=operation,
            code="INVALID_INPUT",
            message="The obligation request configuration is invalid.",
            action="Inspect the selected configuration path and schema, then retry.",
            details={
                "field": "configuration",
                "reason": "configuration is invalid or unavailable",
            },
        )
    except ValueError as exc:
        accepted_snapshot = getattr(args, "_accepted_obligation_snapshot", None)
        if accepted_snapshot is not None:
            return _render_obligation_problem(
                args,
                operation=operation,
                code="INTERNAL_ERROR",
                message="Backstitch could not complete the obligation request.",
                action="Retry and report the failure if it persists.",
                details={},
                snapshot=accepted_snapshot,
            )
        return _render_obligation_problem(
            args,
            operation=operation,
            code="INVALID_INPUT",
            message="The obligation request is invalid.",
            action="Correct the named invocation or configuration value and retry.",
            details={"field": "invocation", "reason": str(exc)},
        )
    except Exception:  # noqa: BLE001 -- closed [EVC-8.4] failure, no traceback.
        return _render_obligation_problem(
            args,
            operation=operation,
            code="INTERNAL_ERROR",
            message="Backstitch could not complete the obligation request.",
            action="Retry and report the failure if it persists.",
            details={},
            snapshot=getattr(args, "_accepted_obligation_snapshot", None),
        )


def _run_obligation(
    args: argparse.Namespace,
    settings: BackstitchSettings,
) -> int:
    from dataclasses import replace

    from backstitch.evidence_discovery import (
        EvidenceDiscoveryError,
        discover_evidence_candidates,
        get_candidate_by_id,
        get_candidate_neighbors,
        get_candidate_source,
    )
    from backstitch.evidence_summary import build_evidence_summary_items
    from backstitch.markdown_specs import MarkdownParseMemo
    from backstitch.obligation_api import (
        CursorError,
        OperationProblemCode,
        apply_response_byte_budget,
        candidate_detail_envelope,
        evidence_summary_envelope,
        find_evidence_envelope,
        inventory_get_envelope,
        inventory_list_envelope,
        problem_envelope,
        render_envelope_json,
        render_envelope_text,
    )
    from backstitch.obligation_runtime import (
        build_obligation_runtime_from_snapshot,
        capture_obligation_snapshot,
    )
    from backstitch.obligations import CandidateCounts, with_candidate_counts

    started = time.monotonic()
    profile = _profile_from(args, settings)
    limits = settings.obligations
    if args.limit is not None and not 1 <= args.limit <= limits.maximum_page_size:
        raise ValueError(f"--limit must be in [1, {limits.maximum_page_size}]")
    root = args.repo_root.resolve()
    markdown_parse_memo: MarkdownParseMemo = {}
    snapshot = capture_obligation_snapshot(
        root,
        profile,
        settings,
        markdown_parse_memo=markdown_parse_memo,
    )
    args._accepted_obligation_snapshot = {
        "snapshot_hash": snapshot.snapshot_hash,
        "file_count": snapshot.file_count,
        "byte_count": snapshot.byte_count,
        "unreadable_count": snapshot.unreadable_count,
    }
    runtime = build_obligation_runtime_from_snapshot(
        snapshot,
        root,
        profile,
        settings,
        markdown_parse_memo=markdown_parse_memo,
    )
    pipeline = runtime.pipeline
    inventory = runtime.inventory
    envelope: dict[str, Any] | None

    if args.obligation_id == "list":
        if args.summarize_evidence or args.find_evidence or args.candidate is not None:
            raise ValueError("obligation list does not accept a detail selector")
        limit = args.limit if args.limit is not None else limits.page_size
        try:
            envelope = inventory_list_envelope(
                inventory, limit=limit, cursor=args.cursor
            )
        except CursorError as exc:
            envelope = problem_envelope(
                operation="obligation.list",
                snapshot=inventory.snapshot.to_row(),
                code="CURSOR_INVALID",
                message="The page cursor is invalid for this repository snapshot.",
                action="Restart pagination without a cursor.",
                details={"reason": str(exc)},
            )
            _emit_obligation_problem(args, envelope, resolved_root=root.as_posix())
            return 2
    else:
        if (
            not args.summarize_evidence
            and not args.find_evidence
            and (args.cursor is not None or args.limit is not None)
        ):
            raise ValueError(
                "--cursor and --limit require --summarize-evidence or --find-evidence"
            )
        obligation = inventory.get(args.obligation_id)
        if obligation is not None and obligation.kind == "suppression":
            if (
                args.summarize_evidence
                or args.find_evidence
                or args.candidate is not None
            ):
                envelope = problem_envelope(
                    operation=_obligation_operation(args),
                    snapshot=inventory.snapshot.to_row(),
                    code="INVALID_INPUT",
                    message="This operation is not available for suppression obligations.",
                    action=(
                        "Inspect the suppression obligation directly; its evidence is "
                        "derived from the declaration and matched findings."
                    ),
                    details={
                        "field": "operation",
                        "reason": (
                            "suppression obligations do not support evidence discovery "
                            "or candidate selectors"
                        ),
                    },
                )
                _emit_obligation_problem(args, envelope, resolved_root=root.as_posix())
                return 2
            envelope = inventory_get_envelope(inventory, obligation.obligation_id)
        elif obligation is not None and not args.summarize_evidence:
            unreadable = next(
                (row for row in snapshot.files if row.state == "unreadable"),
                None,
            )
            if unreadable is not None:
                envelope = problem_envelope(
                    operation=_obligation_operation(args),
                    snapshot=inventory.snapshot.to_row(),
                    code="SOURCE_UNREADABLE",
                    message="Candidate discovery requires every semantic source input.",
                    action="Make the named source readable and retry discovery.",
                    details={
                        "path": unreadable.path,
                        "error_class": unreadable.error_class or "io",
                    },
                )
                _emit_obligation_problem(args, envelope, resolved_root=root.as_posix())
                return 2
            try:
                candidates = discover_evidence_candidates(
                    snapshot,
                    pipeline.raw_report,
                    profile,
                    obligation,
                    limits,
                    obligation_search_text=(
                        pipeline.artifacts.obligation_search_text.get(
                            obligation.obligation_id,
                            "",
                        )
                    ),
                )
            except EvidenceDiscoveryError as exc:
                source_unreadable = exc.code == "SOURCE_UNREADABLE"
                envelope = problem_envelope(
                    operation=_obligation_operation(args),
                    snapshot=inventory.snapshot.to_row(),
                    code=cast(OperationProblemCode, exc.code),
                    message=(
                        "Candidate discovery requires UTF-8 semantic source."
                        if source_unreadable
                        else "Candidate discovery exceeded its closed operation boundary."
                    ),
                    action=(
                        "Correct the named semantic source encoding and retry."
                        if source_unreadable
                        else "Raise the named deterministic budget or narrow configured roots."
                    ),
                    details=exc.details,
                )
                _emit_obligation_problem(args, envelope, resolved_root=root.as_posix())
                return 2
            counts = CandidateCounts(
                declared=sum(item.trace_state == "declared" for item in candidates),
                partially_declared=sum(
                    item.trace_state == "partially_declared" for item in candidates
                ),
                untraced=sum(item.trace_state == "untraced" for item in candidates),
                conflicted=sum(item.trace_state == "conflicted" for item in candidates),
            )
            obligation = with_candidate_counts(obligation, counts)
            inventory = replace(
                inventory,
                obligations=tuple(
                    obligation
                    if item.obligation_id == obligation.obligation_id
                    else item
                    for item in inventory.obligations
                ),
            )
            if args.find_evidence:
                limit = args.limit if args.limit is not None else limits.page_size
                try:
                    envelope = find_evidence_envelope(
                        inventory,
                        obligation,
                        candidates,
                        limit=limit,
                        cursor=args.cursor,
                    )
                except CursorError as exc:
                    envelope = problem_envelope(
                        operation="obligation.find_evidence",
                        snapshot=inventory.snapshot.to_row(),
                        code="CURSOR_INVALID",
                        message="The page cursor is invalid for this repository snapshot.",
                        action="Restart pagination without a cursor.",
                        details={"reason": str(exc)},
                    )
                    _emit_obligation_problem(
                        args, envelope, resolved_root=root.as_posix()
                    )
                    return 2
            elif args.candidate is not None:
                try:
                    candidate = get_candidate_by_id(candidates, args.candidate)
                except KeyError:
                    envelope = problem_envelope(
                        operation="obligation.get_candidate",
                        snapshot=inventory.snapshot.to_row(),
                        code="NOT_FOUND",
                        message="The requested candidate does not exist in this snapshot.",
                        action="Run --find-evidence and use an exact returned candidate ID.",
                        details={"identity": args.candidate},
                    )
                    _emit_obligation_problem(
                        args, envelope, resolved_root=root.as_posix()
                    )
                    return 2
                envelope = candidate_detail_envelope(
                    inventory,
                    obligation,
                    candidate,
                    get_candidate_source(candidate),
                    get_candidate_neighbors(candidate, candidates),
                )
            else:
                envelope = inventory_get_envelope(inventory, obligation.obligation_id)
        elif args.summarize_evidence and obligation is not None:
            limit = args.limit if args.limit is not None else limits.page_size
            items = build_evidence_summary_items(
                pipeline.raw_report,
                obligation,
                snapshot,
                profile,
            )
            try:
                envelope = evidence_summary_envelope(
                    inventory,
                    obligation,
                    items,
                    limit=limit,
                    cursor=args.cursor,
                )
            except CursorError as exc:
                envelope = problem_envelope(
                    operation="obligation.summarize_evidence",
                    snapshot=inventory.snapshot.to_row(),
                    code="CURSOR_INVALID",
                    message="The page cursor is invalid for this repository snapshot.",
                    action="Restart pagination without a cursor.",
                    details={"reason": str(exc)},
                )
                _emit_obligation_problem(args, envelope, resolved_root=root.as_posix())
                return 2
        else:
            envelope = inventory_get_envelope(inventory, args.obligation_id)
        if envelope is None:
            operation = _obligation_operation(args)
            if len(args.obligation_id.encode("utf-8")) > 4096:
                envelope = problem_envelope(
                    operation=operation,
                    snapshot=inventory.snapshot.to_row(),
                    code="INVALID_INPUT",
                    message="The requested identity cannot be represented in a problem response.",
                    action="Use an exact identity returned by backstitch obligation list.",
                    details={
                        "field": "identity",
                        "reason": "requested identity exceeds the closed problem detail limit",
                    },
                )
            else:
                envelope = problem_envelope(
                    operation=operation,
                    snapshot=inventory.snapshot.to_row(),
                    code="NOT_FOUND",
                    message="The requested obligation does not exist in this snapshot.",
                    action=(
                        "Run backstitch obligation list and use an exact returned identity."
                    ),
                    details={"identity": args.obligation_id},
                )
            _emit_obligation_problem(args, envelope, resolved_root=root.as_posix())
            return 2

    assert envelope is not None
    envelope, response_budget_exhausted = apply_response_byte_budget(envelope, limits)
    if response_budget_exhausted:
        _emit_obligation_problem(args, envelope, resolved_root=root.as_posix())
        return 2
    if time.monotonic() - started > limits.maximum_call_seconds:
        envelope = problem_envelope(
            operation=str(envelope["operation"]),
            snapshot=inventory.snapshot.to_row(),
            code="DEADLINE_EXCEEDED",
            message="The obligation operation exceeded its configured deadline.",
            action="Retry after reducing repository load or raise maximum_call_seconds.",
            details={"limit_milliseconds": int(limits.maximum_call_seconds * 1000)},
        )
        _emit_obligation_problem(args, envelope, resolved_root=root.as_posix())
        return 2
    if args.format == "json":
        rendered = render_envelope_json(envelope)
    else:
        rendered = render_envelope_text(envelope, resolved_root=root.as_posix())
    sys.stdout.write(rendered)
    return 0


def _merge_config_controls(args: argparse.Namespace) -> None:
    """Normalize global and subcommand config spellings onto one namespace."""

    local_config = getattr(args, "config", None)
    args.config = local_config or args.global_config
    args.no_config = bool(getattr(args, "no_config", False) or args.global_no_config)
    args.options = [
        *args.global_options,
        *getattr(args, "options", []),
    ]


def _dispatch_config_command(
    args: argparse.Namespace,
    settings: BackstitchSettings,
) -> int:
    if args.command == "check":
        return _cmd_check(args, settings)
    if args.command == "coverage":
        return _cmd_coverage(args, settings)
    if args.command == "packets":
        return _cmd_packets(args, settings)
    if args.command == "analyze":
        return _cmd_analyze(args, settings)
    if args.command == "eval":
        return _cmd_eval(args, settings)
    if args.command == "doctor":
        return _cmd_doctor(args, settings)
    if args.command == "config":
        return _cmd_config(args, settings)
    if args.command == "obligation":
        return _cmd_obligation(args, settings)
    raise ValueError(f"unknown command: {args.command}")


def _explicit_command(argv: Sequence[str]) -> str | None:
    """Return an explicit top-level command after leading global controls."""

    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--no-config":
            index += 1
            continue
        if token == "--config":
            index += 2
            continue
        if token.startswith("--config="):
            index += 1
            continue
        if token == "--option":
            index += 3
            continue
        if token in _TOP_LEVEL_COMMANDS:
            return token
        return None
    return None


def _default_candidate_argv(
    command: str,
    argv: Sequence[str],
) -> tuple[str, ...]:
    """Translate bare shorthand into one selected command candidate."""

    controls: list[str] = []
    remaining = list(argv)
    while remaining:
        token = remaining[0]
        width = (
            1
            if token == "--no-config" or token.startswith("--config=")
            else 2
            if token == "--config"
            else 3
            if token == "--option"
            else 0
        )
        if width == 0 or len(remaining) < width:
            break
        controls.extend(remaining[:width])
        del remaining[:width]
    if remaining and not remaining[0].startswith("-"):
        repo_root = remaining.pop(0)
        return (command, *controls, "--repo-root", repo_root, *remaining)
    owns_input = "--repo-root" in remaining or (
        command == "analyze" and "--packets" in remaining
    )
    if owns_input:
        return (command, *controls, *remaining)
    return (command, *controls, "--repo-root", ".", *remaining)


def _parse_default_candidates(
    parser: argparse.ArgumentParser,
    argv: Sequence[str],
) -> dict[str, argparse.Namespace]:
    """Parse allowed defaults without emitting errors for the other command."""

    candidates: dict[str, argparse.Namespace] = {}
    for command in ("check", "analyze"):
        with contextlib.redirect_stderr(io.StringIO()):
            try:
                args = parser.parse_args(_default_candidate_argv(command, argv))
            except SystemExit:
                continue
        _merge_config_controls(args)
        candidates[command] = args
    return candidates


def _resolve_default_invocation_settings(
    candidates: dict[str, argparse.Namespace],
) -> BackstitchSettings:
    """Resolve bare dispatch once with command-specific dedicated overrides."""

    controls = next(iter(candidates.values()))
    return resolve_config(
        Path.cwd(),
        explicit=controls.config,
        use_repo_config=not controls.no_config,
        environment=os.environ,
        cli_options=tuple((key, value) for key, value in controls.options),
        cli_overrides_by_command={
            command: _dedicated_cli_overrides(args)
            for command, args in candidates.items()
        },
        invocation_command=None,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the backstitch CLI."""

    parser = build_parser()
    raw_argv = tuple(sys.argv[1:] if argv is None else argv)
    explicit_command = _explicit_command(raw_argv)
    parser_only = any(token in {"-h", "--help", "--version"} for token in raw_argv)
    if explicit_command is None and not parser_only:
        candidates = _parse_default_candidates(parser, raw_argv)
        if not candidates:
            parser.parse_args(raw_argv)
            raise AssertionError("argument parser returned after rejecting arguments")
        try:
            settings = _resolve_default_invocation_settings(candidates)
            if settings.default_command is None:
                return _error(
                    "a command is required unless configuration sets default_command"
                )
            args = candidates.get(settings.default_command)
            if args is None:
                parser.parse_args(
                    _default_candidate_argv(settings.default_command, raw_argv)
                )
                raise AssertionError(
                    "argument parser returned after rejecting default arguments"
                )
            return _dispatch_config_command(args, settings)
        except (ScanError, ValueError, OSError) as exc:
            return _error(str(exc))
        except Exception as exc:  # noqa: BLE001 -- [SC-5]: no traceback, ever.
            return _error(f"internal error: {exc}")

    args = parser.parse_args(raw_argv)
    # [CFG-7]: merge the global `backstitch --config/--no-config <command>`
    # spellings with the per-command flags; any mix of --config and
    # --no-config across spellings is a usage error (exit 2).
    _merge_config_controls(args)
    try:
        if args.config is not None and args.no_config:
            msg = "--config and --no-config are mutually exclusive"
            raise ConfigLoadError(msg)
        if args.command is None:
            return _error(
                "a command is required unless configuration sets default_command"
            )
        if args.command not in CONFIG_CONSUMING_COMMANDS:
            if args.config is not None or args.no_config or args.options:
                raise ConfigLoadError(
                    f"{args.command} does not accept --config, --no-config, or --option"
                )
            if args.command == "summarize-analysis":
                return _cmd_summarize(args)
            if args.command == "cache":
                return _cmd_cache(args)
            if args.command == "guide":
                return _cmd_guide(args)
            raise ValueError(f"unknown command: {args.command}")

        try:
            settings = _resolve_invocation_settings(args)
        except ConfigLoadError as exc:
            if args.command == "obligation":
                return _cmd_obligation(args, None, config_error=exc)
            raise
        return _dispatch_config_command(args, settings)
    except (ScanError, ValueError, OSError) as exc:
        return _error(str(exc))
    except Exception as exc:  # noqa: BLE001 -- [SC-5]: no traceback, ever.
        return _error(f"internal error: {exc}")
