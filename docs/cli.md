# The command-line interface

Installing gmat-script puts a `gmat-script` console script on your `PATH` with three subcommands:

- **`parse`** — a fast, install-free syntax gate that parses `.script` / `.gmf` files and reports
  their syntax trees, exiting non-zero on a syntax error.
- **`format`** — re-emit scripts in canonical form, in place or as a check / diff, with exit codes
  that mirror `ruff format` for CI and [pre-commit](#pre-commit-hook) use.
- **`lint`** — statically check scripts against the field catalogue (unknown types and fields, type /
  enum / reference-target mismatches, duplicate names, unused or undeclared references), exiting
  non-zero on an error-severity finding.

Both are built on the library and need no GMAT, C, or Node toolchain at runtime.

## `parse` — the syntax gate

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

### Default output — the S-expression

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

### `--quiet` — diagnostics only

`--quiet` suppresses the tree (and its header), leaving only the stderr diagnostics. This is the form
you want in CI when you only care whether a file is well-formed:

```console
$ printf 'Sat.SMA = \n' | gmat-script parse --quiet -
<stdin>:1:1: unexpected token
```

A clean file under `--quiet` prints nothing and exits 0.

### `--json` — a machine-readable report

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

### Exit codes

| Code | Meaning |
|------|---------|
| `0`  | every file parsed with no `ERROR` / `MISSING` node |
| `1`  | at least one file had a syntax error |
| `2`  | a file could not be read (an operational error, distinct from a syntax error) |

The `1` / `0` split is the CI contract: drop `gmat-script parse` into a pipeline and a syntax
regression fails the build.

## `format` — canonical formatting

`format` re-emits each file in canonical form: one statement per line, consistent spacing and
indentation, per-resource grouping, with no reordering and no semantic change. It is a
deterministic, idempotent pretty-printer — safe to run on every save.

```console
$ gmat-script format --help
usage: gmat-script format [-h] [--check | --diff] FILE [FILE ...]

Format each FILE (or '-' for stdin) in canonical form. By default files are
rewritten in place and '-' writes the result to stdout; --check and --diff
write nothing. Exits non-zero under --check / --diff if any file is not
already canonical, or on a syntax or IO error.

positional arguments:
  FILE        Path to a .script or .gmf file, or '-' to read from stdin
              (writes to stdout).

options:
  -h, --help  show this help message and exit
  --check     Do not write; exit non-zero if any file is not already
              canonically formatted.
  --diff      Do not write; print a unified diff of the changes to stdout.
```

### In place (the default)

With no mode flag, `format` rewrites each file in place, touching only the ones that change (an
already-canonical file is left untouched, mtime and all). Each rewritten file is noted on stderr:

```console
$ gmat-script format mission.script
mission.script: reformatted
```

A file's original line-ending style (LF or CRLF) is preserved.

Pass `-` to format stdin and write the result to stdout — handy for piping or editor integration:

```console
$ printf 'Create Spacecraft Sat\nGMAT Sat.SMA = 7000;\n' | gmat-script format -
Create Spacecraft Sat
Sat.SMA = 7000
```

### `--check` — fail if not canonical

`--check` writes nothing and exits non-zero if any file is not already in canonical form, naming
each on stderr. This is the CI gate:

```console
$ gmat-script format --check mission.script
mission.script: would reformat
$ echo $?
1
```

### `--diff` — show what would change

`--diff` writes nothing either, but prints a unified diff of the changes to stdout:

```console
$ gmat-script format --diff mission.script
--- a/mission.script
+++ b/mission.script
@@ -1,2 +1,2 @@
 Create Spacecraft Sat
-GMAT Sat.SMA = 7000;
+Sat.SMA = 7000
```

### Exit codes

Matching `ruff format`:

| Code | Meaning |
|------|---------|
| `0`  | in place: files were formatted; `--check` / `--diff`: every file was already canonical |
| `1`  | `--check` / `--diff` only: at least one file is not canonical |
| `2`  | a file could not be read, or has a syntax error (a broken tree is never formatted) |

A rewrite in the default mode is **not** a failure — applying changes exits `0`. The `1` exit is
reserved for the read-only `--check` / `--diff` modes, so `gmat-script format --check` fails a build
when a script drifts out of canonical form.

A file with a syntax error cannot be safely formatted: `format` reports the error like
[`parse`](#parse-the-syntax-gate) (`FILE:line:col: <message>`), leaves the file untouched, and exits
`2`.

## `lint` — static checks

`lint` checks each file for structural problems against the bundled field catalogue and reports them
as diagnostics, exiting non-zero when any file has an error-severity finding. The rules, their
severities, and inline suppression are covered in [Linting](lint.md); this section is the CLI surface.

```console
$ gmat-script lint --help
usage: gmat-script lint [-h] [--json] [--select RULES] [--ignore RULES]
                        FILE [FILE ...]

Lint each FILE (or '-' for stdin) for structural problems — unknown
types and fields, type / enum / reference-target mismatches, duplicate
names, unused or undeclared references. Exits non-zero if any file has
an error-severity diagnostic.

positional arguments:
  FILE            Path to a .script or .gmf file, or '-' to read from
                  stdin.

options:
  -h, --help      show this help message and exit
  --json          Emit a machine-readable JSON report instead of text
                  diagnostics.
  --select RULES  Run only these comma-separated rule codes (an allow-
                  list).
  --ignore RULES  Skip these comma-separated rule codes (a deny-list).
```

### Default output — one line per finding

Each diagnostic is printed to stdout as `FILE:line:col: severity rule: message` (positions
1-indexed):

```console
$ gmat-script lint mission.script
mission.script:3:11: warning type-mismatch: field 'SMA' expects a number, got a quoted string
mission.script:5:8: error unknown-resource-type: unknown resource type 'Spacecaft'
```

A clean file prints nothing and exits 0. Read from stdin with `-`.

### `--select` / `--ignore` — choosing rules

Run only some rules, or drop some, by comma-separated code:

```console
$ gmat-script lint --select unknown-field,type-mismatch mission.script
$ gmat-script lint --ignore unused-resource mission.script
```

An unknown rule code is an error (exit `2`), so a typo in a flag fails loudly.

### `--json` — a machine-readable report

`--json` emits a `{file, ok, diagnostics}` report. `ok` is `true` when the file has no
*error*-severity diagnostic (a warning or info leaves it `true`). Positions are 1-indexed.

```console
$ printf 'Create Spacecaft Sat\nBeginMissionSequence\nPropagate Sat\n' | gmat-script lint --json -
{
  "file": "<stdin>",
  "ok": false,
  "diagnostics": [
    {
      "rule": "unknown-resource-type",
      "severity": "error",
      "message": "unknown resource type 'Spacecaft'",
      "start": {
        "line": 1,
        "column": 8
      },
      "end": {
        "line": 1,
        "column": 16
      }
    }
  ]
}
```

For a single file the report is one JSON object; for several files it is a JSON array of reports.

### Exit codes

| Code | Meaning |
|------|---------|
| `0`  | no file had an error-severity diagnostic (warnings and info do not fail the run) |
| `1`  | at least one file had an `error`-severity diagnostic |
| `2`  | a file could not be read, or a `--select` / `--ignore` rule code is unknown |

The `1` / `0` split is the CI contract: only error-severity findings break the build, so warnings and
the informational `unused-resource` can accumulate without blocking a merge.

## Pre-commit hook

gmat-script ships [pre-commit](https://pre-commit.com/) hooks so scripts are formatted (or checked)
automatically on commit and in CI. Add the repo to your `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/astro-tools/gmat-script
    rev: v0.2.0
    hooks:
      - id: gmat-script-format
```

`gmat-script-format` formats matching files in place (failing the commit when it changes a file, so
you re-stage and commit the canonical version). For a check-only gate that never writes — the form
you want in CI — use the `gmat-script-format-check` variant instead:

```yaml
repos:
  - repo: https://github.com/astro-tools/gmat-script
    rev: v0.2.0
    hooks:
      - id: gmat-script-format-check
```

Both hooks run on `.script` and `.gmf` files and install only gmat-script — no GMAT, C, or Node
toolchain. Then:

```console
$ pre-commit install        # run the hook on every commit
$ pre-commit run --all-files # or format the whole tree now
```

## A note on output encoding

`parse` keeps stdout ASCII (S-expression node-type names; JSON with `ensure_ascii`). `format` keeps
the CI-relevant modes (in place and `--check`) silent on stdout, and writes the only content-bearing
output — a `--diff` body or a `-` stdin reformat — as UTF-8, so a non-ASCII script (a comment, a
date) round-trips intact and never chokes a Windows console under a legacy code page. Messages stay
on stderr. `lint` keeps stdout ASCII too (text diagnostics escape any non-ASCII identifier; JSON uses
`ensure_ascii`).

For the structure of `parse`'s error records, see [Error reporting](errors.md).
