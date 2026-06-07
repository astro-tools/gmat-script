# gmat-script

Parse, format, lint, and edit [GMAT](https://gmat.gsfc.nasa.gov/) `.script` mission files from
Python — built on a [tree-sitter](https://tree-sitter.github.io/tree-sitter/) grammar. The whole
stack operates on script **text**; nothing here requires a GMAT install.

Today it ships the parser and the `gmat-script parse` command-line tool. The typed AST and mutation
API, the canonical formatter, the linter, and the editor tooling build on top of the same tree as
they land.

## Install

```bash
pip install gmat-script
```

gmat-script supports Python 3.10, 3.11, and 3.12. The wheel bundles a precompiled grammar, so the
install needs no C or Node toolchain — and never GMAT.

## Quick start

```python
from gmat_script import parse

tree = parse("Create Spacecraft Sat\nSat.SMA = 7000\n")

tree.has_errors      # False — the script is well-formed
tree.to_source()     # round-trips byte-for-byte to the input
```

`parse` never raises on malformed input: it returns a tree carrying `ERROR` / `MISSING` nodes
localised to the broken construct, surfaced through `tree.errors`. The same engine drives the CLI,
a fast, install-free syntax gate for CI:

```console
$ gmat-script parse mission.script        # prints the syntax tree; exits non-zero on a syntax error
$ gmat-script parse --json mission.script  # machine-readable {file, ok, errors} report
```

## The grammar surface

The tree-sitter grammar parses GMAT scripts (`.script`) and GmatFunctions (`.gmf`) — the same
grammar for both — and re-emits any input **byte-for-byte**, comments and layout included. It is a
deliberately permissive superset: `Create <Type> <name>` accepts any resource type and unknown
command keywords parse as generic command nodes, so a new resource or command never needs a grammar
change. The acceptance bar is concrete: every one of the 162 `.script` and 9 `.gmf` files shipped
with NASA GMAT R2026a parses with zero errors and round-trips exactly.

See the [grammar surface reference](https://astro-tools.github.io/gmat-script/grammar-surface/) for
the node taxonomy and the covered / deferred constructs.

## The GMAT-free guarantee

Reading, checking, formatting, and transforming a script needs only this package — never a GMAT
install. `pip install gmat-script` never pulls in, requires, or looks for GMAT or `gmatpy`; the only
runtime dependency is `tree-sitter`. (GMAT is used at build time only, to generate the field
catalogue that later semantic tooling will check against.)

## GMAT version

The grammar targets **GMAT R2026a**. Because it never enumerates resource types or command keywords,
parsing is effectively version-independent — scripts from other releases parse too. Semantics that
*do* vary by release (valid field names, enums, defaults) belong to the later linter and are scoped
to R2026a.

## What gmat-script is not

- **Not a propagator or astrodynamics engine.** It reads and transforms script *text*; it computes
  no orbits and models no physics.
- **Not a mission runner.** Running a script is GMAT's job — gmat-script does no execution.
- **Not an engine-dependent validator.** "Does it parse" is a structural question answered here;
  "does it run / converge" is a different question that needs GMAT.

## Documentation

Full documentation — getting started, the grammar surface, the `parse` CLI, the error-reporting
model, and the API reference — is at
**[astro-tools.github.io/gmat-script](https://astro-tools.github.io/gmat-script/)**.

## License

[MIT](LICENSE) — part of the [astro-tools](https://github.com/astro-tools) organization.
