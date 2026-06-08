"""Command-line interface for gmat-script — the ``gmat-script`` console script.

Two subcommands, both built on the library and needing no GMAT, C, or Node toolchain at runtime:

* **``parse``** — syntax-checks scripts and inspects their trees (built on
  :func:`gmat_script.parse`). A fast, install-free CI gate: it exits non-zero when any input has a
  syntax error and zero otherwise.
* **``format``** — re-emits scripts in canonical form (built on :func:`gmat_script.format`). It
  formats in place by default, with ``--check`` / ``--diff`` modes whose exit codes mirror
  ``ruff format`` for CI and pre-commit use.

The ``parse`` output contract follows the design decisions (D7 / D8):

* **default** — the tree-sitter S-expression of each file on stdout; every ``ERROR`` / ``MISSING``
  node as ``FILE:line:col: <message>`` on stderr.
* **``--quiet``** — suppress the S-expression; keep the diagnostics.
* **``--json``** — a ``{"file", "ok", "errors"}`` report on stdout (a single object for one file, a
  JSON array for several), with 1-indexed positions, instead of the S-expression.

The ``format`` exit-code contract (D8 conventions, matching ``ruff format``):

* **in place** (the default) — rewrite each changed file; ``-`` writes the formatted source to
  stdout. Exit ``0`` (``2`` on a syntax or IO error).
* **``--check``** — write nothing; exit ``1`` if any file is not already canonical, ``0`` if all
  are, ``2`` on error.
* **``--diff``** — print a unified diff and write nothing; exit ``1`` if any file would change,
  ``0`` otherwise, ``2`` on error.

``parse`` keeps stdout ASCII (S-expression node-type names; JSON with ``ensure_ascii``). ``format``
keeps the CI-relevant modes (in place, ``--check``) silent on stdout, and writes the only
content-bearing output — a ``--diff`` body or a ``-`` stdin reformat — as UTF-8 bytes, so a
non-ASCII script neither crashes nor mangles on a Windows console under a legacy code page; its
messages stay ASCII on stderr.
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from typing import TYPE_CHECKING

from .format import format as format_source
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

    format_cmd = subparsers.add_parser(
        "format",
        help="Re-emit .script / .gmf files in canonical form.",
        description=(
            "Format each FILE (or '-' for stdin) in canonical form. By default files are rewritten "
            "in place and '-' writes the result to stdout; --check and --diff write nothing. Exits "
            "non-zero under --check / --diff if any file is not already canonical, or on a syntax "
            "or IO error."
        ),
    )
    format_cmd.add_argument(
        "files",
        metavar="FILE",
        nargs="+",
        help="Path to a .script or .gmf file, or '-' to read from stdin (writes to stdout).",
    )
    mode = format_cmd.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="Do not write; exit non-zero if any file is not already canonically formatted.",
    )
    mode.add_argument(
        "--diff",
        action="store_true",
        help="Do not write; print a unified diff of the changes to stdout.",
    )

    return parser


def _read_source(path: str) -> str:
    """Read *path* as UTF-8 text, or read stdin when *path* is ``-``.

    Both paths read the raw bytes with newline translation disabled so the parser sees the source
    verbatim and the library performs no EOL normalisation (D6). Stdin is read through its binary
    ``buffer``; a bare ``sys.stdin.read()`` would inherit the interpreter's universal-newline
    translation (the Windows default) and collapse CRLF to LF, so ``format -`` would not match the
    library ``format()`` on the same bytes.
    """
    if path == "-":
        return sys.stdin.buffer.read().decode("utf-8")
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


def _write_source(path: str, text: str) -> None:
    """Write *text* to *path* as UTF-8 with newline translation disabled.

    ``format`` already terminates the source with the file's own newline (D6), so writing it back
    verbatim — no ``\\n``→``\\r\\n`` rewrite — keeps the file's line-ending style intact.
    """
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def _emit_stdout(text: str) -> None:
    """Write *text* to stdout as UTF-8 bytes, bypassing the console's locale codec.

    The only content-bearing ``format`` output — a ``--diff`` body or a ``-`` stdin reformat — may
    hold non-ASCII source (a comment, a date), which ``print`` would crash on under a legacy Windows
    code page. Writing the bytes directly keeps it correct and console-safe; a stdout without a
    binary ``buffer`` (a test capture) falls back to a text write.
    """
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is not None:
        buffer.write(text.encode("utf-8"))
        buffer.flush()
    else:  # pragma: no cover - real stdout always has a binary buffer
        sys.stdout.write(text)


def _unified_diff(name: str, before: str, after: str) -> str:
    """A ``git``-style unified diff turning *before* into *after* for *name*."""
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{name}",
            tofile=f"b/{name}",
        )
    )


def _run_format(args: argparse.Namespace) -> int:
    """Format each file in place (or check / diff it); return the process exit code.

    ``2`` if any file could not be read or has a syntax error (an operational error — a broken tree
    is never formatted), else ``1`` under ``--check`` / ``--diff`` if any file is not already
    canonical, else ``0``. In the default in-place mode a rewrite is not a failure, so a clean run
    that reformats still exits ``0`` (the ``ruff format`` contract).
    """
    exit_code = 0
    for raw in args.files:
        name = _STDIN_NAME if raw == "-" else raw
        try:
            source = _read_source(raw)
        except OSError as exc:
            print(f"{name}: {exc.strerror or exc}", file=sys.stderr)
            exit_code = max(exit_code, 2)
            continue

        tree = parse(source)
        if tree.has_errors:
            # A script with syntax errors cannot be safely formatted (format() would raise); report
            # the errors like `parse` does and skip the file.
            _emit_diagnostics(name, tree.errors)
            print(f"{name}: not formatted (syntax error)", file=sys.stderr)
            exit_code = max(exit_code, 2)
            continue

        formatted = format_source(tree)
        changed = formatted != source

        if args.diff:
            if changed:
                _emit_stdout(_unified_diff(name, source, formatted))
                exit_code = max(exit_code, 1)
        elif args.check:
            if changed:
                print(f"{name}: would reformat", file=sys.stderr)
                exit_code = max(exit_code, 1)
        elif raw == "-":
            _emit_stdout(formatted)
        elif changed:
            _write_source(raw, formatted)
            print(f"{name}: reformatted", file=sys.stderr)

    return exit_code


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI. Returns the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "parse":
        return _run_parse(args)
    if args.command == "format":
        return _run_format(args)

    parser.error(f"unknown command: {args.command}")  # pragma: no cover
    return 2  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
