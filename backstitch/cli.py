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
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from backstitch import __version__
from backstitch.profiles import get_profile
from backstitch.reporting import render_json, render_text
from backstitch.resolver import ScanError, scan_repository


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


def _cmd_check(args: argparse.Namespace) -> int:
    profile = get_profile(args.profile)
    overrides: dict[str, tuple[str, ...]] = {}
    if args.spec_roots is not None:
        overrides["spec_roots"] = tuple(args.spec_roots)
    if args.plan_roots is not None:
        overrides["plan_roots"] = tuple(args.plan_roots)
    if args.code_roots is not None:
        overrides["code_roots"] = tuple(args.code_roots)
    if overrides:
        profile = profile.with_overrides(**overrides)

    report = scan_repository(args.repo_root, profile)
    rendered = render_json(report) if args.format == "json" else render_text(report)

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
