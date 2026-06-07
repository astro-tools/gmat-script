# gmat-script

Parse, format, lint, and edit [GMAT](https://gmat.gsfc.nasa.gov/) `.script` mission files from
Python — built on a [tree-sitter](https://tree-sitter.github.io/tree-sitter/) grammar, with a typed
AST and mutation API, a canonical formatter, a linter, and editor tooling (LSP + VS Code extension)
layered on top. The whole stack operates on script **text**; nothing here requires a GMAT install.

```python
from gmat_script import parse

tree = parse(open("flyby.script").read())
```

!!! note "Early development"
    The package is being built milestone by milestone. The tree-sitter grammar, the `parse` entry
    point, and the `gmat-script parse` CLI come first; the typed AST, formatter, and linter follow.
    See the [issues](https://github.com/astro-tools/gmat-script/issues) and
    [milestones](https://github.com/astro-tools/gmat-script/milestones) for the plan. No release is
    published yet.

## What it is

- A **tree-sitter grammar** for GMAT scripts (`.script`) and GmatFunctions (`.gmf`) that parses the
  full R2026a sample corpus and re-emits it byte-for-byte.
- A Python library that loads that grammar from a **vendored, precompiled** binding — so
  `pip install gmat-script` needs no C or Node toolchain, and never GMAT.
- A `gmat-script` command-line tool for parsing (and, as later milestones land, formatting and
  linting) scripts from the shell or CI.

## What it is not

- **Not** a propagator or astrodynamics engine — it reads and transforms script *text*; running a
  mission is GMAT's job.
- **Not** dependent on a GMAT install at runtime. Reading, checking, formatting, and editing a
  script needs only this package.

## Where to go next

- **[API reference](api.md)** — the public surface.
- **[Design decisions](design/decisions.md)** — the grammar scope, CST node taxonomy, and the
  build/vendoring contract the implementation is built against.

## Installation

```bash
pip install gmat-script
```

gmat-script supports Python 3.10, 3.11, and 3.12.
