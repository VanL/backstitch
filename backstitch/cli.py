"""Command-line entry point for backstitch.

Spec: docs/specs/02-backstitch-core.md [SC-1], [SC-5], [SC-5.1], [SC-13],
[SC-16], [SC-17]
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
import io
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from backstitch import __version__
from backstitch.config import ProfileConfig, uncontained_test_root
from backstitch.grammar import candidate_ref_digest
from backstitch.profiles import configured_profile
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


def _tty_progress_sink(*, enabled: bool) -> Any:
    """Return the optional noncanonical TTY stderr progress adapter."""

    if not enabled or not sys.stderr.isatty():
        return None

    def render(event: Any) -> None:
        total = (
            str(event.total_work_units) if event.total_work_units is not None else "?"
        )
        sys.stderr.write(
            "backstitch: progress "
            f"{event.phase} {event.completed_work_units}/{total} "
            f"{event.current_identity}\n"
        )
        sys.stderr.flush()

    return render


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
    obligation.add_argument("--active-only", action="store_true")
    obligation.add_argument(
        "--alignment-state",
        action="append",
        choices=("untraced", "partial", "complete", "invalid"),
        default=[],
    )
    obligation.add_argument(
        "--gate-state",
        action="append",
        choices=("not_executable", "executable"),
        default=[],
    )
    obligation.add_argument(
        "--kind",
        action="append",
        choices=("section", "invariant", "suppression"),
        default=[],
    )
    obligation.add_argument(
        "--reason",
        action="append",
        choices=(
            "IMPLEMENTATION_UNTRACED",
            "IMPLEMENTATION_PARTIAL",
            "TEST_UNTRACED",
            "TEST_PARTIAL",
            "INVARIANT_TARGET_MISSING",
            "BINDING_TEST_MISSING",
            "TRACE_CONFLICT",
            "OUT_OF_GATE_SCOPE",
            "SKIPPED",
        ),
        default=[],
    )
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
        "--preflight",
        action="store_true",
        help=(
            "prepare current analysis without credentials, cache access, "
            "provider calls, temporary files, or publication"
        ),
    )
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


def _dedicated_cli_overrides(args: argparse.Namespace) -> dict[str, Any]:  # noqa: C901 approved [SC-17.1] RUFF-SUP-030 exception
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

    return configured_profile(settings, name=name)


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
    from backstitch.check_application import (
        CheckFailure,
        CheckRequest,
        check_repository,
    )

    profile = _profile_from(args, settings)
    root = args.repo_root.resolve()
    outcome = check_repository(
        CheckRequest(
            repo_root=root,
            profile=profile,
            settings=settings,
        )
    )
    if isinstance(outcome, CheckFailure):
        raise ScanError(outcome.message)
    pipeline = outcome.pipeline

    for warning in outcome.warnings:
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
    return 1 if outcome.blocks_gate else 0


def _cmd_coverage(args: argparse.Namespace, settings: BackstitchSettings) -> int:
    from backstitch.coverage_application import (
        CoverageFailure,
        CoverageRequest,
        publish_coverage,
        run_coverage,
    )

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
    outcome = run_coverage(
        CoverageRequest(
            repo_root=root,
            profile=profile,
            settings=settings,
        )
    )
    if isinstance(outcome, CoverageFailure):
        if outcome.stage == "snapshot":
            raise ScanError(outcome.message)
        return _error(outcome.message)
    rendered = _render_coverage_result(outcome, settings.coverage.format)
    publication_failure = publish_coverage(outcome, rendered)
    if publication_failure is not None:
        return _error(publication_failure.message)
    if outcome.output_path is None:
        sys.stdout.write(rendered)
    return 1 if outcome.blocks_gate else 0


def _render_coverage_result(result: object, format_name: str) -> str:
    from backstitch.coverage_application import CoverageResult
    from backstitch.intent_coverage_reporting import render_coverage_json

    assert isinstance(result, CoverageResult)
    document = result.document
    if format_name == "json":
        return render_coverage_json(
            document.payload,
            source_result=document.source_result,
            inherited_counts=document.inherited_counts,
            floors=document.floors,
            unscannable_files=document.unscannable_files,
            issues=document.issues,
            baseline=document.baseline,
            changed_definition_ids=document.changed_definition_ids,
            policy_events=document.policy_events,
            drift_events=document.drift_events,
            stale_doc_trends=document.stale_doc_trends,
            spec_growth=document.spec_growth,
        )
    summary = document.payload["summary"]
    definition_rows = {
        item["definition_id"]: item for item in document.payload["definitions"]
    }
    worklist_lines = "".join(
        "uncovered "
        f"{definition_rows[definition_id]['role']} "
        f"{definition_rows[definition_id]['path']} "
        f"{definition_rows[definition_id]['structural_locator']}\n"
        for definition_id in document.payload["worklist"]
    )
    return (
        "Intent coverage: "
        f"{summary['direct']} direct, {summary['inherited']} inherited, "
        f"{summary['exempt']} exempt, {summary['uncovered']} uncovered, "
        f"{summary['total']} total\n"
        f"{worklist_lines}"
    )


def _cmd_packets(args: argparse.Namespace, settings: BackstitchSettings) -> int:  # noqa: C901 approved [SC-17.1] RUFF-SUP-029 exception
    from backstitch.packet_application import (
        PacketBlocked,
        PacketFailure,
        PacketRequest,
        publish_packets,
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
    outcome = publish_packets(
        PacketRequest(
            repo_root=args.repo_root,
            profile=profile,
            settings=settings,
            output_path=args.output,
            report_path=args.report,
            kind=args.kind,
            progress_sink=_tty_progress_sink(enabled=True),
        )
    )
    for warning in outcome.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if isinstance(outcome, PacketBlocked):
        sys.stdout.write(render_json(outcome.pipeline.report))
        return 1
    if isinstance(outcome, PacketFailure):
        if outcome.stage == "packet":
            assert outcome.code is not None
            return _error(f"{outcome.code}: {outcome.message}")
        if outcome.stage == "discovery":
            assert outcome.code is not None
            details = json.dumps(
                dict(outcome.details),
                sort_keys=True,
                separators=(",", ":"),
            )
            return _error(f"{outcome.code}: {outcome.message}; details={details}")
        if outcome.stage != "publication":
            return _error(outcome.message)
        assert outcome.failed_path is not None
        published_text = (
            ", ".join(path.as_posix() for path in outcome.published_paths)
            if outcome.published_paths
            else "none"
        )
        return _error(
            "packet publication failed at "
            f"{outcome.failed_path.as_posix()}; already published: "
            f"{published_text}; {outcome.message}"
        )
    print(f"wrote {outcome.packet_count} packets to {args.output}", file=sys.stderr)
    return 0


def _render_semantic_preflight(preflight: Any) -> str:
    """Render one bounded provider-free preparation assessment."""

    document = preflight.document
    readiness = document["readiness"]
    if document["ready"]:
        packet_plan = document["packet_plan"] or {}
        packet_count = packet_plan.get("packet_count", 0)
        budgets = document["budgets"]
        analyzer = budgets["analyzer"]
        limits = budgets["limits"]
        calls = (
            f"{analyzer['provider_calls']}/"
            f"{limits['maximum_provider_calls']} calls "
            f"({analyzer['provider_call_status']})"
        )
        maximum_cost = limits["maximum_estimated_cost_microusd"]
        cost = (
            "cost disabled"
            if maximum_cost is None
            else (
                f"{analyzer['estimated_cost_microusd']}/"
                f"{maximum_cost} microusd "
                f"({analyzer['estimated_cost_status']})"
            )
        )
        verifier = budgets["verifier"]["status"]
        return (
            f"analysis preflight ready: {packet_count} packet(s); "
            f"cold analyzer {calls}; {cost}; verifier {verifier}\n"
        )
    config_path = document["config"]["selected_path"]
    config_source = config_path if config_path is not None else "packaged defaults"
    lines = [
        "analysis preflight blocked",
        f"selected command: {document['selected_command']} (config: {config_source})",
    ]
    if isinstance(readiness, dict):
        lines[0] += f": {readiness['blocked']} active obligation(s)"
        for group in readiness["reason_groups"]:
            examples = ", ".join(group["example_obligation_ids"])
            lines.append(f"{group['code']}: {group['count']} ({examples})")
        lines.append(f"next: {readiness['next_command']}")
    else:
        problems = document["problems"]
        if problems:
            lines.append(f"{problems[0]['code']}: {problems[0]['action']}")
    return "\n".join(lines) + "\n"


def _render_preflight_result(
    args: argparse.Namespace, preflight: Any, *, blocked: bool = False
) -> int:
    if args.format == "json":
        # JSON is a structured result even when preparation is blocked. Keep it
        # on stdout so ordinary analyze and explicit preflight remain identical.
        sys.stdout.buffer.write(preflight.to_json_bytes())
    else:
        stream = sys.stderr if blocked else sys.stdout
        stream.write(_render_semantic_preflight(preflight))
    return cast(int, preflight.exit_code)


def _analyze_failure_error(outcome: Any) -> int:
    if outcome.stage == "packet":
        assert outcome.code is not None
        return _error(f"{outcome.code}: {outcome.message}")
    if outcome.stage == "discovery":
        assert outcome.code is not None
        details = json.dumps(
            dict(outcome.details), sort_keys=True, separators=(",", ":")
        )
        return _error(f"{outcome.code}: {outcome.message}; details={details}")
    if outcome.stage != "publication":
        return _error(outcome.message)
    assert outcome.failed_path is not None
    published = (
        ", ".join(path.as_posix() for path in outcome.published_paths)
        if outcome.published_paths
        else "none"
    )
    return _error(
        "current analyze publication failed at "
        f"{outcome.failed_path.as_posix()}; already published: {published}; "
        f"{outcome.message}"
    )


def _render_analyze_run(args: argparse.Namespace, outcome: Any) -> int:
    run = outcome.run
    for line in run.stderr_lines:
        print(line, file=sys.stderr)
    if args.repo_root is not None and run.exit_code == 2:
        return cast(int, run.exit_code)
    if args.format == "json" and run.report_json:
        sys.stdout.buffer.write(run.report_json)
    elif run.report:
        print(
            f"semantic analysis {run.report['status']}: "
            f"{run.report['result_count']} result(s), "
            f"{len(run.diagnostics)} finding(s)"
        )
    return cast(int, run.exit_code)


def _analysis_adapter_factory(
    provider: Any, resolved: Any, model_name: str | None
) -> Any:
    def build_adapter() -> Any:
        if resolved.inference is not None:
            return provider(
                resolved.inference.adapter_model_id,
                provider_identity=resolved.provider_identity,
                request_identity=resolved.request_identity,
                resolved_inference=resolved.inference,
            )
        return provider(
            model_name,
            provider_identity=resolved.provider_identity,
            request_identity=resolved.request_identity,
        )

    return build_adapter if resolved.cache_mode != "require" else None


def _verification_adapter_factory(
    provider: Any, resolved: Any, response_schema_builder: Any
) -> Any:
    if resolved is None or resolved.cache_mode == "require":
        return None

    def build_adapter() -> Any:
        if resolved.inference is not None:
            return provider(
                resolved.inference.adapter_model_id,
                provider_identity=resolved.provider_identity,
                request_identity=resolved.request_identity,
                resolved_inference=resolved.inference,
                response_schema_builder=response_schema_builder,
            )
        return provider(
            resolved.provider_identity.model_id,
            provider_identity=resolved.provider_identity,
            request_identity=resolved.request_identity,
            response_schema_builder=response_schema_builder,
        )

    return build_adapter


def _cmd_analyze(args: argparse.Namespace, settings: BackstitchSettings) -> int:
    # Lazy imports preserve the structural no-provider boundary for deterministic
    # commands ([SC-8]).
    from backstitch.analysis_llm import default_provider_adapter, resolve_model_name
    from backstitch.semantic_analysis import (
        required_independent_qualification_problem,
        resolve_semantic_settings,
        resolve_verification_settings,
    )
    from backstitch.semantic_application import (
        SemanticApplicationFailure,
        SemanticApplicationRequest,
        SemanticApplicationResult,
        SemanticPreparationBlocked,
        SemanticReadinessBlocked,
        analyze_semantics,
        preflight_semantics,
        validate_analysis_mode,
    )
    from backstitch.semantic_policy import materialize_semantic_policy
    from backstitch.semantic_verification import (
        verification_response_schema_from_prompt,
    )

    mode_failure = validate_analysis_mode(
        repo_root=args.repo_root,
        packets_path=args.packets,
        packet_report_path=args.packet_report,
        compare_repo_root=args.compare_repo_root,
        packets_output_path=args.packets_output,
        packet_report_output_path=args.packet_report_output,
    )
    if mode_failure is not None:
        return _error(mode_failure.message)
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

    adapter_factory = _analysis_adapter_factory(
        default_provider_adapter, resolved, model_name
    )
    verification_adapter_factory = _verification_adapter_factory(
        default_provider_adapter,
        resolved_verify,
        verification_response_schema_from_prompt,
    )

    profile = _configured_profile(settings)
    application_request = SemanticApplicationRequest(
        settings=settings,
        profile=profile,
        semantic_settings=resolved,
        policy=policy,
        adapter_factory=adapter_factory,
        verification_settings=resolved_verify,
        evaluation_settings=getattr(settings.verify, "eval", None),
        verification_adapter_factory=verification_adapter_factory,
        repo_root=args.repo_root,
        packets_path=args.packets,
        packet_report_path=args.packet_report,
        compare_repo_root=args.compare_repo_root,
        packets_output_path=args.packets_output,
        packet_report_output_path=args.packet_report_output,
        result_output_path=args.output,
        report_output_path=args.report,
        progress_sink=_tty_progress_sink(enabled=args.format != "json"),
    )
    if getattr(args, "preflight", False):
        preflight = preflight_semantics(application_request)
        if isinstance(preflight, SemanticApplicationFailure):
            return _error(preflight.message)
        return _render_preflight_result(args, preflight)

    outcome = analyze_semantics(application_request)
    if isinstance(outcome, SemanticPreparationBlocked):
        return _render_preflight_result(args, outcome.preflight, blocked=True)
    if isinstance(outcome, SemanticApplicationFailure):
        return _analyze_failure_error(outcome)
    if isinstance(outcome, SemanticReadinessBlocked):
        rendered = (
            render_json(outcome.report)
            if args.format == "json"
            else render_text(outcome.report)
        )
        sys.stdout.write(rendered)
        return 1
    assert isinstance(outcome, SemanticApplicationResult)
    return _render_analyze_run(args, outcome)


def _eval_paths(args: argparse.Namespace) -> tuple[Path, Path]:
    try:
        corpus = args.corpus.resolve()
        output = args.output.resolve(strict=False)
    except OSError as exc:
        raise ConfigLoadError(f"eval path resolution failed: {exc}") from exc
    if corpus == output:
        raise ConfigLoadError("eval --corpus and --output paths must be distinct")
    return corpus, output


def _validate_eval_paths(
    args: argparse.Namespace,
    settings: BackstitchSettings,
    corpus_path: Path,
    output_path: Path,
    eval_settings: Any,
) -> None:
    if eval_settings.qualification_corpus.strip() and (
        Path(eval_settings.qualification_corpus).resolve() != corpus_path
    ):
        raise ConfigLoadError(
            "configured verify.eval qualification_corpus does not match --corpus"
        )
    config_paths = {
        Path(item.path).resolve(strict=False)
        for item in settings.config_layer_identities
    }
    report_path = (
        Path(eval_settings.qualification_report).resolve(strict=False)
        if eval_settings.qualification_report.strip()
        else None
    )
    if report_path == output_path:
        raise ConfigLoadError(
            "eval --output must not overlap configured verify.eval qualification_report"
        )
    if output_path in config_paths:
        raise ConfigLoadError("eval --output overlaps selected configuration")
    if report_path in config_paths:
        raise ConfigLoadError(
            "configured verify.eval qualification_report overlaps selected configuration"
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

    corpus_path, output_path = _eval_paths(args)

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
    _validate_eval_paths(args, settings, corpus_path, output_path, eval_settings)

    def build_adapter() -> ProviderAdapter:
        if resolved.inference is not None:
            return default_provider_adapter(
                resolved.inference.adapter_model_id,
                provider_identity=resolved.provider_identity,
                request_identity=resolved.request_identity,
                resolved_inference=resolved.inference,
            )
        return default_provider_adapter(
            model_name,
            provider_identity=resolved.provider_identity,
            request_identity=resolved.request_identity,
        )

    def build_verification_adapter() -> ProviderAdapter:
        if resolved_verify.inference is not None:
            return default_provider_adapter(
                resolved_verify.inference.adapter_model_id,
                provider_identity=resolved_verify.provider_identity,
                request_identity=resolved_verify.request_identity,
                resolved_inference=resolved_verify.inference,
                response_schema_builder=verification_response_schema_from_prompt,
            )
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
        if "suppressed_issues" not in report_data and any(
            "unknown packet ID `suppression::" in error for error in load.errors
        ):
            return _error(
                "invalid analysis results: suppression result identities require "
                "a deterministic report generated by `backstitch check "
                "--show-suppressions`"
            )
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
    from backstitch.semantic_analysis import resolve_semantic_settings

    resolved = resolve_semantic_settings(settings.analyze)
    results = run_doctor(
        settings.analyze.adapter_model_id or settings.analyze.model or None,
        model_source=settings.analyze_model_source,
        probe=args.probe,
        inference=resolved.inference,
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
        if (
            args.active_only
            or args.alignment_state
            or args.gate_state
            or args.kind
            or args.reason
        ):
            raise ValueError("obligation list filters require `obligation list`")
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
    from backstitch.obligation_api import (
        ListFilters,
        ObligationOperation,
        ObligationRequest,
        read_obligation,
        render_envelope_json,
        render_envelope_text,
    )

    operation = _obligation_operation(args)
    try:
        if config_error is not None:
            raise config_error
        assert settings is not None
        _validate_obligation_invocation(args)
        result = read_obligation(
            ObligationRequest(
                operation=cast(ObligationOperation, operation),
                repo_root=args.repo_root,
                profile=_profile_from(args, settings),
                settings=settings,
                obligation_id=None
                if args.obligation_id == "list"
                else args.obligation_id,
                candidate_id=args.candidate,
                cursor=args.cursor,
                limit=args.limit,
                list_filters=ListFilters(
                    active_only=args.active_only,
                    alignment_states=frozenset(args.alignment_state),
                    gate_states=frozenset(args.gate_state),
                    kinds=frozenset(args.kind),
                    reasons=frozenset(args.reason),
                ),
            ),
            progress_sink=_tty_progress_sink(enabled=args.format != "json"),
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
        )
    rendered = (
        render_envelope_json(result.envelope)
        if args.format == "json"
        else render_envelope_text(
            result.envelope,
            resolved_root=result.resolved_root,
        )
    )
    stream = sys.stderr if result.failed and args.format == "text" else sys.stdout
    stream.write(rendered)
    return 2 if result.failed else 0


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


def _run_default_invocation(
    parser: argparse.ArgumentParser, raw_argv: Sequence[str]
) -> int:
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


def _dispatch_parsed_invocation(args: argparse.Namespace) -> int:
    if args.config is not None and args.no_config:
        raise ConfigLoadError("--config and --no-config are mutually exclusive")
    if args.command is None:
        return _error("a command is required unless configuration sets default_command")
    if args.command in CONFIG_CONSUMING_COMMANDS:
        try:
            settings = _resolve_invocation_settings(args)
        except ConfigLoadError as exc:
            if args.command == "obligation":
                return _cmd_obligation(args, None, config_error=exc)
            raise
        return _dispatch_config_command(args, settings)
    if args.config is not None or args.no_config or args.options:
        raise ConfigLoadError(
            f"{args.command} does not accept --config, --no-config, or --option"
        )
    handlers = {
        "summarize-analysis": _cmd_summarize,
        "cache": _cmd_cache,
        "guide": _cmd_guide,
    }
    handler = handlers.get(args.command)
    if handler is None:
        raise ValueError(f"unknown command: {args.command}")
    return handler(args)


def _run_parsed_invocation(args: argparse.Namespace) -> int:
    try:
        return _dispatch_parsed_invocation(args)
    except (ScanError, ValueError, OSError) as exc:
        return _error(str(exc))
    except Exception as exc:  # noqa: BLE001 -- [SC-5]: no traceback, ever.
        return _error(f"internal error: {exc}")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the backstitch CLI."""

    parser = build_parser()
    raw_argv = tuple(sys.argv[1:] if argv is None else argv)
    explicit_command = _explicit_command(raw_argv)
    parser_only = any(token in {"-h", "--help", "--version"} for token in raw_argv)
    if explicit_command is None and not parser_only:
        return _run_default_invocation(parser, raw_argv)

    args = parser.parse_args(raw_argv)
    # [CFG-7]: merge the global `backstitch --config/--no-config <command>`
    # spellings with the per-command flags; any mix of --config and
    # --no-config across spellings is a usage error (exit 2).
    _merge_config_controls(args)
    return _run_parsed_invocation(args)
