"""Command-line entry point for backstitch.

Spec: docs/specs/02-backstitch-core.md [SC-1], [SC-5], [SC-13]

Exit-code contract ([SC-5]): exit 1 is a statement about the target
repository (deterministic findings exist); exit 2 is a statement about the
invocation or the tool (bad arguments, unreadable target, unwritable output,
internal failure). No invocation may surface a traceback: every failure path
prints a one-line ``backstitch: error: ...`` diagnostic.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from backstitch import __version__
from backstitch.check_pipeline import build_check_report
from backstitch.config import ProfileConfig
from backstitch.profiles import get_profile
from backstitch.reporting import render_json, render_text
from backstitch.resolver import ScanError
from backstitch.settings import (
    BackstitchSettings,
    ConfigLoadError,
    load_settings,
)


def _error(message: str) -> int:
    print(f"backstitch: error: {message}", file=sys.stderr)
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
        help="ignore all configuration files",
    )
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


def _add_other_parsers(subparsers: argparse._SubParsersAction[Any]) -> None:
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
    packets.add_argument("--config", type=Path, default=None, metavar="PATH")
    packets.add_argument("--no-config", action="store_true")
    packets.add_argument("--output", type=Path, required=True, metavar="PATH")

    analyze = subparsers.add_parser(
        "analyze", help="run llm-backed semantic review over packets"
    )
    analyze.add_argument("--packets", type=Path, required=True, metavar="PATH")
    analyze.add_argument("--model", default=None, metavar="MODEL")
    analyze.add_argument(
        "--output",
        type=Path,
        default=None,
        metavar="PATH",
        help="write results JSONL to PATH (default: stdout)",
    )
    analyze.add_argument("--concurrency", type=int, default=None, metavar="N")
    analyze.add_argument("--config", type=Path, default=None, metavar="PATH")
    analyze.add_argument("--no-config", action="store_true")

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
    doctor.add_argument("--no-config", action="store_true")

    config = subparsers.add_parser("config", help="inspect resolved configuration")
    config_sub = config.add_subparsers(dest="config_command", required=True)
    show = config_sub.add_parser("show", help="print effective settings as JSON")
    show.add_argument("--repo-root", type=Path, default=Path("."))
    show.add_argument("--config", type=Path, default=None, metavar="PATH")
    show.add_argument("--no-config", action="store_true")
    path_cmd = config_sub.add_parser(
        "path", help="print the discovered config file path"
    )
    path_cmd.add_argument("--repo-root", type=Path, default=Path("."))
    path_cmd.add_argument("--config", type=Path, default=None, metavar="PATH")
    path_cmd.add_argument("--no-config", action="store_true")


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
        help="ignore all configuration files",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_check_parser(subparsers)
    _add_other_parsers(subparsers)
    return parser


def _resolve_settings(args: argparse.Namespace) -> BackstitchSettings:
    """[CFG-5]: config discovery anchored at the resolved repo root."""

    if args.no_config and args.config is not None:
        msg = "--config and --no-config are mutually exclusive"
        raise ConfigLoadError(msg)
    if args.no_config:
        return BackstitchSettings()
    return load_settings(args.repo_root.resolve(), explicit=args.config)


def _profile_from(
    args: argparse.Namespace, settings: BackstitchSettings
) -> ProfileConfig:
    """[CFG-5] precedence: CLI flags > config values > built-in profile."""

    # An explicit --profile beats config; config beats the built-in default.
    name = args.profile or settings.profile or "backstitch-style-v1"
    profile = get_profile(name)
    config_overrides: dict[str, tuple[str, ...]] = {}
    for field in (
        "spec_roots",
        "plan_roots",
        "code_roots",
        "planned_spec_globs",
        "exploratory_spec_globs",
        "meta_spec_globs",
    ):
        value = getattr(settings.profile_overrides, field)
        if value is not None:
            config_overrides[field] = value
    if config_overrides:
        profile = profile.with_overrides(**config_overrides)
    cli_overrides: dict[str, tuple[str, ...]] = {}
    if args.spec_roots is not None:
        cli_overrides["spec_roots"] = tuple(args.spec_roots)
    if args.plan_roots is not None:
        cli_overrides["plan_roots"] = tuple(args.plan_roots)
    if args.code_roots is not None:
        cli_overrides["code_roots"] = tuple(args.code_roots)
    if cli_overrides:
        profile = profile.with_overrides(**cli_overrides)
    return profile


def _cmd_check(args: argparse.Namespace) -> int:
    settings = _resolve_settings(args)
    profile = _profile_from(args, settings)
    pipeline = build_check_report(args.repo_root, profile, settings)

    for warning in pipeline.warnings:
        print(f"warning: {warning}", file=sys.stderr)

    # [CFG-5]/[CFG-9]: config-set check.format and check.output apply when
    # the CLI flag is omitted; a parsed-but-unconsulted key is dead schema.
    fmt = args.format or settings.check.format or "text"
    output = args.output
    if output is None and settings.check.output is not None:
        output = Path(settings.check.output)

    shown = pipeline.suppressed if args.show_suppressions else None
    rendered = (
        render_json(pipeline.report, shown)
        if fmt == "json"
        else render_text(pipeline.report, shown)
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

    summary = pipeline.report.summary()
    warnings_as_errors = args.warnings_as_errors
    if warnings_as_errors is None:
        warnings_as_errors = bool(settings.check.warnings_as_errors)
    if summary["errors"]:
        return 1
    if warnings_as_errors and summary["warnings"]:
        return 1
    return 0


def _cmd_packets(args: argparse.Namespace) -> int:
    from backstitch.analysis_packets import generate_packets, render_packets_jsonl

    settings = _resolve_settings(args)
    profile = _profile_from(args, settings)
    pipeline = build_check_report(args.repo_root, profile, settings)
    for warning in pipeline.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    packets = generate_packets(args.repo_root, profile, report=pipeline.report)
    try:
        args.output.write_text(render_packets_jsonl(packets), encoding="utf-8")
    except OSError as exc:
        return _error(f"cannot write --output {args.output}: {exc}")
    print(f"wrote {len(packets)} packets to {args.output}", file=sys.stderr)
    # [SC-5]: packets still reports the deterministic scan outcome -- the
    # packets were written either way, but exit 1 says findings exist.
    return 1 if pipeline.report.summary()["errors"] else 0


def _cmd_analyze(args: argparse.Namespace) -> int:
    # Lazy import in the handler only: deterministic commands must be
    # structurally incapable of importing llm ([SC-8]).
    from backstitch.analysis_llm import (
        analyze_exit_code,
        analyze_packets,
        default_adapter,
        render_results_jsonl,
        resolve_model_name,
    )
    from backstitch.artifact_contracts import load_packets

    # [CFG-3]: analyze anchors config discovery at the packets file's parent.
    if args.no_config and args.config is not None:
        raise ConfigLoadError("--config and --no-config are mutually exclusive")
    if args.no_config:
        settings = BackstitchSettings()
    else:
        settings = load_settings(args.packets.resolve().parent, explicit=args.config)
    # [CFG-5]: config-set analyze.concurrency applies when the flag is
    # omitted; validation runs on the resolved value.
    concurrency = args.concurrency
    if concurrency is None:
        concurrency = settings.analyze.concurrency or 1
    if concurrency < 1:
        raise ValueError("--concurrency must be at least 1")
    packets = load_packets(args.packets)
    model = resolve_model_name(args.model, configured=settings.analyze.model)
    try:
        adapter = default_adapter(model)
    except KeyError as exc:
        # [SC-5]: an unknown model name is an invocation error with a clear
        # one-line diagnostic, not an "internal error". llm's
        # UnknownModelError subclasses KeyError, whose str() adds repr
        # quoting -- unwrap args for the clean message.
        message = exc.args[0] if exc.args else exc
        return _error(str(message))
    rows, errors = analyze_packets(packets, adapter, concurrency)
    rendered = render_results_jsonl(rows)
    if args.output is not None:
        try:
            args.output.write_text(rendered, encoding="utf-8")
        except OSError as exc:
            return _error(f"cannot write --output {args.output}: {exc}")
    else:
        sys.stdout.write(rendered)
    for problem in errors:
        print(f"warning: {problem}", file=sys.stderr)
    return analyze_exit_code(rows, errors)


def _cmd_summarize(args: argparse.Namespace) -> int:
    from backstitch.analysis_results import (
        load_analysis_results,
        packet_ids_from_report,
        render_analysis_summary,
    )
    from backstitch.artifact_contracts import load_deterministic_report

    report_data = load_deterministic_report(args.deterministic_report)
    load = load_analysis_results(
        args.analysis_results.read_text(encoding="utf-8"),
        packet_ids_from_report(report_data),
    )
    sys.stdout.write(render_analysis_summary(report_data["summary"], load))
    return 0


def _cmd_config(args: argparse.Namespace) -> int:
    from backstitch.exclusions import validate_lint_codes
    from backstitch.settings import discover_config_path, settings_to_json

    if args.config_command == "show":
        if args.no_config:
            settings = BackstitchSettings()
        else:
            settings = load_settings(args.repo_root.resolve(), explicit=args.config)
        # [CFG-9]/[EXC-4]: `config show` follows load strictness -- an
        # invalid suppression code that would fail `check` must not print
        # as effective configuration with exit 0.
        for warning in validate_lint_codes(
            settings.lint, allow_unknown=settings.allow_unknown_keys
        ):
            print(f"warning: {warning}", file=sys.stderr)
        sys.stdout.write(settings_to_json(settings))
        return 0
    if args.no_config:
        # Discovery is skipped entirely: there is no path to print.
        return 0
    path = discover_config_path(args.repo_root.resolve(), explicit=args.config)
    if path is not None:
        print(path)
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    # Lazy import in the handler only: doctor is an llm-touching command
    # like analyze; check/packets stay structurally incapable of importing
    # llm ([SC-8]), and doctor.py itself defers llm to check functions.
    from backstitch.doctor import (
        doctor_exit_code,
        render_json,
        render_text,
        run_doctor,
    )

    # [CFG-3]: doctor anchors config discovery at the current working
    # directory (it has no packets file or --repo-root to anchor on).
    if args.no_config and args.config is not None:
        raise ConfigLoadError("--config and --no-config are mutually exclusive")
    if args.no_config:
        settings = BackstitchSettings()
    else:
        settings = load_settings(Path.cwd(), explicit=args.config)
    results = run_doctor(
        args.model, configured=settings.analyze.model, probe=args.probe
    )
    rendered = render_json(results) if args.format == "json" else render_text(results)
    sys.stdout.write(rendered)
    return doctor_exit_code(results)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the backstitch CLI."""

    parser = build_parser()
    args = parser.parse_args(argv)
    # [CFG-7]: merge the global `backstitch --config/--no-config <command>`
    # spellings with the per-command flags; any mix of --config and
    # --no-config across spellings is a usage error (exit 2).
    args.config = getattr(args, "config", None) or args.global_config
    args.no_config = bool(getattr(args, "no_config", False) or args.global_no_config)
    handlers = {
        "check": _cmd_check,
        "packets": _cmd_packets,
        "analyze": _cmd_analyze,
        "summarize-analysis": _cmd_summarize,
        "doctor": _cmd_doctor,
        "config": _cmd_config,
    }
    try:
        if args.config is not None and args.no_config:
            msg = "--config and --no-config are mutually exclusive"
            raise ConfigLoadError(msg)
        handler = handlers.get(args.command)
        if handler is None:
            raise ValueError(f"unknown command: {args.command}")
        return handler(args)
    except (ScanError, ValueError, OSError) as exc:
        return _error(str(exc))
    except Exception as exc:  # noqa: BLE001 -- [SC-5]: no traceback, ever.
        return _error(f"internal error: {exc}")
