"""Command-line entry point for backstitch.

Spec: docs/specs/02-backstitch-core.md [SC-5]

Exit-code contract ([SC-5]): exit 1 is a statement about the target
repository (deterministic findings exist); exit 2 is a statement about the
invocation or the tool (bad arguments, unreadable target, unwritable output,
internal failure). No invocation may surface a traceback: every failure path
prints a one-line ``backstitch: error: ...`` diagnostic.
"""

from __future__ import annotations

import argparse
import dataclasses
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
from backstitch.models import Issue
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
        default="backstitch-style-v1",
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
        default="text",
        help="report format (default: text)",
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


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level parser."""

    parser = argparse.ArgumentParser(
        prog="backstitch",
        description=(
            "Backstitch style traceability checks for spec-driven"
            " repositories."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_check_parser(subparsers)
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

    profile = get_profile(settings.profile or args.profile)
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

    # [EXC-6.2]: suppression runs after emission and before exit-code and
    # render, so every view (text, JSON, exit code) agrees; suppressed
    # findings stay recoverable via --show-suppressions ([EXC-7]).
    index = build_suppression_index(
        meta_spec_globs=profile.meta_spec_globs,
        lint=settings.lint,
        section_meta=artifacts.section_meta,
        inline_file_ignores=artifacts.inline_file_ignores,
        inline_spec_ignores=artifacts.inline_spec_ignores,
        inline_code_ignores=artifacts.inline_code_ignores,
        inline_code_span_ignores=artifacts.inline_code_span_ignores,
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

    shown = suppressed if args.show_suppressions else None
    rendered = (
        render_json(report, shown)
        if args.format == "json"
        else render_text(report, shown)
    )

    if args.output is not None:
        # Known fable defect fixed at port time: an unwritable --output path
        # must be exit 2 with a one-line error, never a traceback/exit 1.
        try:
            args.output.write_text(rendered, encoding="utf-8")
        except OSError as exc:
            return _error(f"cannot write --output {args.output}: {exc}")
    else:
        sys.stdout.write(rendered)

    summary = report.summary()
    return 1 if summary["errors"] else 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the backstitch CLI."""

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            return _cmd_check(args)
        raise ValueError(f"unknown command: {args.command}")
    except (ScanError, ValueError, OSError) as exc:
        return _error(str(exc))
    except Exception as exc:  # noqa: BLE001 -- [SC-5]: no traceback, ever.
        return _error(f"internal error: {exc}")
