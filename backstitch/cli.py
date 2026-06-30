"""Command-line entry point for backstitch.

Spec: docs/specs/01-development-documentation-operating-model.md [DOM-4], [DOM-10]
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from backstitch import __version__


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level parser."""

    parser = argparse.ArgumentParser(
        prog="backstitch",
        description="Backstitch style traceability checks for spec-driven repositories.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the backstitch CLI."""

    parser = build_parser()
    parser.parse_args(argv)
    return 0
