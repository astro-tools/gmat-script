"""Command-line interface for gmat-script — the ``gmat-script`` console script.

Scaffold skeleton. The argument parser and the ``parse`` subcommand are wired so the CLI surface
is stable; the subcommand's behaviour (emit the syntax tree as an S-expression, or a JSON report
under ``--json``, with the exit code reflecting whether the tree has errors) is filled in once the
parser is implemented. See ``docs/design/decisions.md`` for the output-format contract.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

_NOT_IMPLEMENTED = (
    "gmat-script parse is not implemented yet — the grammar is being built up "
    "before it is wired in."
)


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="gmat-script",
        description="Parse, format, and lint GMAT mission scripts.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    parse_cmd = subparsers.add_parser(
        "parse", help="Parse a .script or .gmf file and report its syntax tree."
    )
    parse_cmd.add_argument("file", help="Path to the .script or .gmf file to parse.")
    parse_cmd.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable report instead of the default S-expression.",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI. Returns the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "parse":
        print(_NOT_IMPLEMENTED, file=sys.stderr)
        return 2

    parser.error(f"unknown command: {args.command}")  # pragma: no cover
    return 2  # pragma: no cover


if __name__ == "__main__":
    sys.exit(main())
