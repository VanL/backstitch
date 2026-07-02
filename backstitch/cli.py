"""Command-line entry point for backstitch.

Spec: docs/specs/02-backstitch-core.md [SC-1], [SC-5]

Exit-code contract ([SC-5]): exit 1 is a statement about the target
repository (deterministic findings exist); exit 2 is a statement about the
invocation or the tool (bad arguments, unreadable target, unwritable output,
internal failure). No invocation may surface a traceback: every failure path
prints a one-line ``backstitch: error: ...`` diagnostic.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from backstitch import __version__
from backstitch.config import ProfileConfig
from backstitch.exclusions import (
    build_suppression_index,
    collect_unused_ignore_warnings,
    should_suppress,
)
from backstitch.models import Issue, Report
from backstitch.profiles import get_profile
from backstitch.reporting import SuppressedRecord, render_json, render_text
from backstitch.resolver import ScanError, scan_repository_with_artifacts
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
    )
    summarize.add_argument(
        "--deterministic-report", type=Path, required=True, metavar="PATH"
    )
    summarize.add_argument(
        "--analysis-results", type=Path, required=True, metavar="PATH"
    )

    config = subparsers.add_parser("config", help="inspect resolved configuration")
    config_sub = config.add_subparsers(dest="config_command", required=True)
    show = config_sub.add_parser("show", help="print effective settings as JSON")
    show.add_argument("--repo-root", type=Path, default=Path("."))
    path_cmd = config_sub.add_parser(
        "path", help="print the discovered config file path"
    )
    path_cmd.add_argument("--repo-root", type=Path, default=Path("."))


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
    report, artifacts = scan_repository_with_artifacts(
        args.repo_root,
        profile,
        exclude_globs=settings.exclude,
        allow_unknown_suppression_codes=settings.allow_unknown_keys,
    )

    # [EXC-6] precedence: suppression runs after emission and before
    # exit-code and render, so every view (text, JSON, exit code) agrees;
    # suppressed findings stay recoverable via --show-suppressions ([EXC-7]).
    index = build_suppression_index(
        meta_spec_globs=profile.meta_spec_globs,
        lint=settings.lint,
        section_meta=artifacts.section_meta,
        inline_file_ignores=artifacts.inline_file_ignores,
        inline_spec_ignores=artifacts.inline_spec_ignores,
        inline_code_ignores=artifacts.inline_code_ignores,
        inline_code_span_ignores=artifacts.inline_code_span_ignores,
        sections_with_markers=artifacts.sections_with_markers,
        marker_warnings=list(artifacts.marker_warnings),
        allow_unknown=settings.allow_unknown_keys,
    )
    kept: list[Issue] = []
    suppressed: list[SuppressedRecord] = []
    for issue in report.issues:
        is_suppressed, reason = should_suppress(issue, index)
        if is_suppressed and reason is not None:
            suppressed.append((issue, reason.value))
        else:
            kept.append(issue)
    report = dataclasses.replace(report, issues=tuple(kept))

    for warning in index.suppression_warnings:
        print(f"warning: {warning}", file=sys.stderr)
    for warning in collect_unused_ignore_warnings(index):
        print(f"warning: {warning}", file=sys.stderr)

    # [CFG-5]/[CFG-9]: config-set check.format and check.output apply when
    # the CLI flag is omitted; a parsed-but-unconsulted key is dead schema.
    fmt = args.format or settings.check.format or "text"
    output = args.output
    if output is None and settings.check.output is not None:
        output = Path(settings.check.output)

    shown = suppressed if args.show_suppressions else None
    rendered = (
        render_json(report, shown) if fmt == "json" else render_text(report, shown)
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

    summary = report.summary()
    warnings_as_errors = args.warnings_as_errors
    if warnings_as_errors is None:
        warnings_as_errors = bool(settings.check.warnings_as_errors)
    if summary["errors"]:
        return 1
    if warnings_as_errors and summary["warnings"]:
        return 1
    return 0


def _suppressed_report(args: argparse.Namespace) -> Report:
    """Scan + suppress, shared by check-style consumers (packets)."""

    settings = _resolve_settings(args)
    profile = _profile_from(args, settings)
    report, artifacts = scan_repository_with_artifacts(
        args.repo_root,
        profile,
        exclude_globs=settings.exclude,
        allow_unknown_suppression_codes=settings.allow_unknown_keys,
    )
    index = build_suppression_index(
        meta_spec_globs=profile.meta_spec_globs,
        lint=settings.lint,
        section_meta=artifacts.section_meta,
        inline_file_ignores=artifacts.inline_file_ignores,
        inline_spec_ignores=artifacts.inline_spec_ignores,
        inline_code_ignores=artifacts.inline_code_ignores,
        inline_code_span_ignores=artifacts.inline_code_span_ignores,
        sections_with_markers=artifacts.sections_with_markers,
        marker_warnings=list(artifacts.marker_warnings),
        allow_unknown=settings.allow_unknown_keys,
    )
    kept = tuple(
        issue for issue in report.issues if not should_suppress(issue, index)[0]
    )
    return dataclasses.replace(report, issues=kept)


def _cmd_packets(args: argparse.Namespace) -> int:
    from backstitch.analysis_packets import generate_packets, render_packets_jsonl

    settings = _resolve_settings(args)
    profile = _profile_from(args, settings)
    report = _suppressed_report(args)
    packets = generate_packets(args.repo_root, profile, report=report)
    try:
        args.output.write_text(render_packets_jsonl(packets), encoding="utf-8")
    except OSError as exc:
        return _error(f"cannot write --output {args.output}: {exc}")
    print(f"wrote {len(packets)} packets to {args.output}", file=sys.stderr)
    # [SC-5]: packets still reports the deterministic scan outcome -- the
    # packets were written either way, but exit 1 says findings exist.
    return 1 if report.summary()["errors"] else 0


def _load_packets(path: Path) -> list[dict[str, Any]]:
    packets: list[dict[str, Any]] = []
    for line_no, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            msg = f"{path}:{line_no}: malformed packet JSONL: {exc}"
            raise ValueError(msg) from None
        if not isinstance(row, dict):
            msg = f"{path}:{line_no}: packet line is not a JSON object"
            raise ValueError(msg)
        packets.append(row)
    return packets


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
    packets = _load_packets(args.packets)
    model = resolve_model_name(args.model, configured=settings.analyze.model)
    adapter = default_adapter(model)
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

    try:
        report_data = json.loads(args.deterministic_report.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        msg = f"{args.deterministic_report}: not valid JSON: {exc}"
        raise ValueError(msg) from None
    if not isinstance(report_data, dict) or "summary" not in report_data:
        msg = (
            f"{args.deterministic_report}: not a backstitch deterministic"
            " report (missing `summary`)"
        )
        raise ValueError(msg)
    load = load_analysis_results(
        args.analysis_results.read_text(encoding="utf-8"),
        packet_ids_from_report(report_data),
    )
    sys.stdout.write(render_analysis_summary(report_data["summary"], load))
    return 0


def _cmd_config(args: argparse.Namespace) -> int:
    from backstitch.settings import discover_config_path, settings_to_json

    if args.config_command == "show":
        settings = load_settings(args.repo_root.resolve())
        sys.stdout.write(settings_to_json(settings))
        return 0
    path = discover_config_path(args.repo_root.resolve())
    if path is not None:
        print(path)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the backstitch CLI."""

    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "check": _cmd_check,
        "packets": _cmd_packets,
        "analyze": _cmd_analyze,
        "summarize-analysis": _cmd_summarize,
        "config": _cmd_config,
    }
    try:
        handler = handlers.get(args.command)
        if handler is None:
            raise ValueError(f"unknown command: {args.command}")
        return handler(args)
    except (ScanError, ValueError, OSError) as exc:
        return _error(str(exc))
    except Exception as exc:  # noqa: BLE001 -- [SC-5]: no traceback, ever.
        return _error(f"internal error: {exc}")
