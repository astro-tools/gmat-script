"""Command-line interface for gmat-script — the ``gmat-script`` console script.

The ``parse`` subcommand syntax-checks GMAT scripts and inspects their trees with no GMAT, C, or
Node toolchain at runtime (it is built on :func:`gmat_script.parse`). It is a fast, install-free CI
gate: the process exits non-zero when any input has a syntax error and zero otherwise.

The output contract follows the design decisions (D7 / D8):

* **default** — the tree-sitter S-expression of each file on stdout; every ``ERROR`` / ``MISSING``
  node as ``FILE:line:col: <message>`` on stderr.
* **``--quiet``** — suppress the S-expression; keep the diagnostics.
* **``--json``** — a ``{"file", "ok", "errors"}`` report on stdout (a single object for one file, a
  JSON array for several), with 1-indexed positions, instead of the S-expression.

Stdout stays ASCII — S-expressions are node-type names and JSON is emitted with ``ensure_ascii`` —
so a Windows console under a legacy code page cannot choke on it.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import TYPE_CHECKING

from .parser import parse

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .parser import ErrorNode, Tree

_STDIN_NAME = "<stdin>"


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="gmat-script",
        description="Parse, format, and lint GMAT mission scripts.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    parse_cmd = subparsers.add_parser(
        "parse",
        help="Parse .script / .gmf files and report their syntax trees.",
        description=(
            "Parse each FILE (or '-' for stdin) and print its syntax tree as an S-expression. "
            "Exits non-zero if any file has a syntax error."
        ),
    )
    parse_cmd.add_argument(
        "files",
        metavar="FILE",
        nargs="+",
        help="Path to a .script or .gmf file, or '-' to read from stdin.",
    )
    parse_cmd.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress the syntax tree; print only error diagnostics.",
    )
    parse_cmd.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON report instead of the S-expression.",
    )

    return parser


def _read_source(path: str) -> str:
    """Read *path* as UTF-8 text, or read stdin when *path* is ``-``.

    Files are opened with newline translation disabled so the parser sees the bytes verbatim and the
    library performs no EOL normalisation (D6).
    """
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def _emit_diagnostics(name: str, errors: list[ErrorNode]) -> None:
    """Print each error as ``FILE:line:col: <message>`` to stderr (positions are 1-indexed, D8)."""
    for error in errors:
        print(f"{name}:{error.start.line}:{error.start.column}: {error.message}", file=sys.stderr)


def _report(name: str, tree: Tree) -> dict[str, object]:
    """Build the D8 ``{file, ok, errors}`` JSON report for one parsed file."""
    return {
        "file": name,
        "ok": not tree.has_errors,
        "errors": [
            {
                "type": error.type,
                "start": {"line": error.start.line, "column": error.start.column},
                "end": {"line": error.end.line, "column": error.end.column},
                "message": error.message,
            }
            for error in tree.errors
        ],
    }


def _emit_json(parsed: list[tuple[str, Tree]]) -> None:
    """Emit the JSON report(s) on stdout: a single object for one file, an array otherwise (D8).

    ``json.dumps`` defaults to ``ensure_ascii=True``, so non-ASCII source never reaches stdout.
    """
    reports = [_report(name, tree) for name, tree in parsed]
    payload: object = reports[0] if len(reports) == 1 else reports
    print(json.dumps(payload, indent=2))


def _emit_text(parsed: list[tuple[str, Tree]], *, quiet: bool) -> None:
    """Emit the S-expression of each file on stdout and its diagnostics on stderr.

    With more than one file, each tree is prefixed by a ``; <file>`` header (an S-expression
    comment) so the trees stay attributable; a single file's tree is printed bare. ``quiet`` drops
    the tree (and its header) entirely, leaving only the stderr diagnostics.
    """
    multiple = len(parsed) > 1
    for index, (name, tree) in enumerate(parsed):
        if not quiet:
            if multiple:
                if index:
                    print()
                print(f"; {name}")
            print(tree.root_node)
        _emit_diagnostics(name, tree.errors)


def _run_parse(args: argparse.Namespace) -> int:
    """Read, parse, and report each file; return the process exit code.

    ``2`` if any file could not be read (an operational error, distinct from a syntax error), else
    ``1`` if any file has an ``ERROR`` / ``MISSING`` node, else ``0`` — the CI contract (D8).
    """
    parsed: list[tuple[str, Tree]] = []
    io_error = False
    for raw in args.files:
        name = _STDIN_NAME if raw == "-" else raw
        try:
            source = _read_source(raw)
        except OSError as exc:
            print(f"{name}: {exc.strerror or exc}", file=sys.stderr)
            io_error = True
            continue
        parsed.append((name, parse(source)))

    if args.json:
        _emit_json(parsed)
    else:
        _emit_text(parsed, quiet=args.quiet)

    if io_error:
        return 2
    return 1 if any(tree.has_errors for _, tree in parsed) else 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI. Returns the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "parse":
        return _run_parse(args)

    parser.error(f"unknown command: {args.command}")  # pragma: no cover
    return 2  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
