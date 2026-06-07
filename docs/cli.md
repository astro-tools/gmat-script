# The `parse` CLI

Installing gmat-script puts a `gmat-script` console script on your `PATH`. Its `parse` subcommand is
a fast, install-free syntax gate: it parses `.script` / `.gmf` files and reports their syntax trees,
exiting non-zero when any input has a syntax error. It needs no GMAT, C, or Node toolchain at
runtime.

```console
$ gmat-script parse --help
usage: gmat-script parse [-h] [-q] [--json] FILE [FILE ...]

Parse each FILE (or '-' for stdin) and print its syntax tree as an
S-expression. Exits non-zero if any file has a syntax error.

positional arguments:
  FILE         Path to a .script or .gmf file, or '-' to read from stdin.

options:
  -h, --help   show this help message and exit
  -q, --quiet  Suppress the syntax tree; print only error diagnostics.
  --json       Emit a machine-readable JSON report instead of the
               S-expression.
```

## Default output — the S-expression

By default, `parse` prints each file's tree as a tree-sitter S-expression to stdout. Any
`ERROR` / `MISSING` node is reported on stderr as `FILE:line:col: <message>` (positions are
1-indexed).

```console
$ gmat-script parse mission.script
(source_file (create_command type: (identifier) name: (identifier)) (assignment_command left: (member_expression object: (identifier) property: (identifier)) right: (number)))
```

Read from stdin by passing `-`:

```console
$ printf 'Create Spacecraft Sat\nSat.SMA = 7000\n' | gmat-script parse -
(source_file (create_command type: (identifier) name: (identifier)) (assignment_command left: (member_expression object: (identifier) property: (identifier)) right: (number)))
```

With more than one file, each tree is prefixed by a `; <file>` header (an S-expression comment) so
the trees stay attributable; a single file's tree is printed bare.

## `--quiet` — diagnostics only

`--quiet` suppresses the tree (and its header), leaving only the stderr diagnostics. This is the form
you want in CI when you only care whether a file is well-formed:

```console
$ printf 'Sat.SMA = \n' | gmat-script parse --quiet -
<stdin>:1:1: unexpected token
```

A clean file under `--quiet` prints nothing and exits 0.

## `--json` — a machine-readable report

`--json` emits a `{file, ok, errors}` report instead of the S-expression. `ok` mirrors the exit code
(`true` ⇔ exit 0). Positions are 1-indexed for both line and column.

```console
$ printf 'Create Spacecraft Sat\nSat.SMA = \n' | gmat-script parse --json -
{
  "file": "<stdin>",
  "ok": false,
  "errors": [
    {
      "type": "ERROR",
      "start": {
        "line": 2,
        "column": 1
      },
      "end": {
        "line": 2,
        "column": 10
      },
      "message": "unexpected token"
    }
  ]
}
```

A clean file reports `"ok": true` with an empty `errors` list:

```console
$ printf 'Create Spacecraft Sat\n' | gmat-script parse --json -
{
  "file": "<stdin>",
  "ok": true,
  "errors": []
}
```

For a single file the report is one JSON object; for several files it is a JSON array of reports.

## Exit codes

| Code | Meaning |
|------|---------|
| `0`  | every file parsed with no `ERROR` / `MISSING` node |
| `1`  | at least one file had a syntax error |
| `2`  | a file could not be read (an operational error, distinct from a syntax error) |

The `1` / `0` split is the CI contract: drop `gmat-script parse` into a pipeline and a syntax
regression fails the build.

## A note on output encoding

Stdout stays ASCII — S-expressions are node-type names, and the JSON report is emitted with
`ensure_ascii`, so non-ASCII source never reaches stdout. A Windows console under a legacy code page
cannot choke on it.

For the structure of the error records, see [Error reporting](errors.md).
