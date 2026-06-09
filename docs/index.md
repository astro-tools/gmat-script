# gmat-script

Parse, format, lint, and edit [GMAT](https://gmat.gsfc.nasa.gov/) `.script` mission files from
Python — built on a [tree-sitter](https://tree-sitter.github.io/tree-sitter/) grammar. The whole
stack operates on script **text**; nothing here requires a GMAT install.

```python
from gmat_script import parse

tree = parse("Create Spacecraft Sat\nSat.SMA = 7000\n")
tree.has_errors      # False
tree.to_source()     # round-trips byte-for-byte to the input
```

gmat-script ships the parser, a typed AST with a mutation API, a canonical formatter, and a static
linter, with a `gmat-script` command-line tool over the same engine — plus a language server and a
VS Code extension that bring it all to your editor.

## What it is

- A **tree-sitter grammar** for GMAT scripts (`.script`) and GmatFunctions (`.gmf`) that parses the
  full R2026a sample corpus and re-emits it byte-for-byte.
- A Python library that loads that grammar from a **vendored, precompiled** binding — so
  `pip install gmat-script` needs no C or Node toolchain, and never GMAT.
- A `gmat-script` command-line tool that parses, formats, and lints scripts from the shell or CI.

## What it is not

- **Not** a propagator or astrodynamics engine — it reads and transforms script *text*; computing
  orbits and running a mission is GMAT's job.
- **Not** dependent on a GMAT install at runtime. Reading, checking, formatting, and editing a
  script needs only this package.
- **Not** an engine-dependent validator — "does it parse" is structural and answered here; "does it
  run / converge" needs GMAT.

## Where to go next

- **[Getting started](getting-started.md)** — install and run your first parse.
- **[Grammar surface](grammar-surface.md)** — the node taxonomy and what is covered / deferred.
- **[Typed AST](typed-ast.md)** — typed resources and dict-like field access over the tree.
- **[Editing](editing.md)** — set fields, rename resources, and splice commands.
- **[Formatter](formatting.md)** — canonical, idempotent re-emission.
- **[Linter](lint.md)** — structural checks against the bundled field catalogue.
- **[Field catalogue](catalogue.md)** — the version-pinned knowledge base behind the linter and editor.
- **[CLI](cli.md)** — the `parse` syntax gate and the `format` and `lint` commands.
- **[Language server](lsp.md)** — diagnostics, hover, and completion in any LSP editor.
- **[VS Code extension](vscode.md)** — highlighting, diagnostics, and format-on-save in VS Code.
- **[Error reporting](errors.md)** — how malformed input is surfaced.
- **[API reference](api.md)** — the public Python surface.
- **[Design decisions](design/decisions.md)** — the grammar scope, CST node taxonomy, and the
  build/vendoring contract the implementation is built against.

## Installation

```bash
pip install gmat-script
```

gmat-script supports Python 3.10, 3.11, and 3.12.
