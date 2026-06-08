# Getting started

## Install

```bash
pip install gmat-script
```

gmat-script supports Python 3.10, 3.11, and 3.12. The wheel bundles a precompiled tree-sitter
grammar, so the install needs **no C or Node toolchain** — and never GMAT (see
[the GMAT-free guarantee](#the-gmat-free-guarantee) below).

The only runtime dependency is [`tree-sitter`](https://pypi.org/project/tree-sitter/), pulled in
automatically.

## Your first parse

`parse` takes script text and returns a `Tree` — a thin wrapper over the tree-sitter concrete syntax
tree (CST):

```python
from gmat_script import parse

source = """\
Create Spacecraft Sat
Sat.SMA = 7000
"""

tree = parse(source)

tree.has_errors          # False — the script is well-formed
tree.to_source() == source  # True — re-emission is byte-for-byte
```

The raw tree-sitter root is available as `tree.root_node`, and printing it gives the S-expression
form of the parse:

```pycon
>>> print(tree.root_node)
(source_file (create_command type: (identifier) name: (identifier)) (assignment_command left: (member_expression object: (identifier) property: (identifier)) right: (number)))
```

`parse` reads UTF-8 text and preserves the original line endings exactly — it never normalises
CRLF↔LF. Concatenating the tree's leaf tokens with their interstitial layout (whitespace, comments,
the `...` continuation, the optional `;`) reproduces the input byte-for-byte; that round-trip
guarantee is what the layers above it — the formatter and the editing API — build on.

## Malformed input never raises

`parse` does not raise on a broken script. It returns a partial tree carrying `ERROR` / `MISSING`
nodes localised to the problem, which you read through `tree.errors`:

```python
bad = parse("Create Spacecraft Sat\nSat.SMA = \n")

bad.has_errors   # True
for error in bad.errors:
    print(error.type, error.start.line, error.start.column, error.message)
# ERROR 2 1 unexpected token
```

This is what makes editor-grade feedback on a half-typed buffer possible. See
[Error reporting](errors.md) for the full model.

## From the command line

The same engine drives a command-line syntax gate — useful in CI with no GMAT, C, or Node toolchain
present:

```console
$ gmat-script parse mission.script
(source_file ...)

$ echo "Create Spacecraft Sat" | gmat-script parse -
(source_file (create_command type: (identifier) name: (identifier)))
```

It exits non-zero when any input has a syntax error and zero otherwise. The `--json` flag emits a
machine-readable report instead of the S-expression. See the [`parse` CLI reference](cli.md) for the
output modes and exit codes.

## The GMAT-free guarantee

Reading, checking, formatting, and transforming a script needs only this package — never a GMAT
install.

- `pip install gmat-script` never pulls in, requires, or looks for GMAT or `gmatpy`.
- The library imports neither GMAT nor `gmatpy` — not at runtime, not in tests.
- GMAT is used at *build time only*, to generate the field catalogue that later semantic tooling
  checks against.

This is the project's defining boundary: running a script needs GMAT; reading, checking, formatting,
and transforming its text does not.

## Next steps

- [Grammar surface](grammar-surface.md) — what the parser understands, node by node.
- [Typed AST](typed-ast.md) — typed resources and dict-like field access over the tree.
- [Editing](editing.md) — set a field, rename a resource, splice a command.
- [Formatter](formatting.md) — canonical, idempotent re-emission.
- [CLI](cli.md) — the `parse` syntax gate and the `format` command.
- [Error reporting](errors.md) — `ERROR` / `MISSING` nodes, positions, and exit codes.
- [API reference](api.md) — the public Python surface.
