# gmat-script

Parse, format, lint, and edit [GMAT](https://gmat.gsfc.nasa.gov/) `.script` mission files
from Python — a tree-sitter grammar, a typed AST with a mutation API, a canonical formatter, a
linter, and editor tooling (LSP + VS Code extension). The whole stack operates on script
**text**; nothing here requires a GMAT install.

> **Status: early development.** The package is being scaffolded and built milestone by
> milestone — see the [issues](https://github.com/astro-tools/gmat-script/issues) and
> [milestones](https://github.com/astro-tools/gmat-script/milestones) for the v0.1 → v0.3 plan.
> No release is published yet.

## What it will do

```python
from gmat_script import parse, lint, format

ast = parse(open("flyby.script").read())
ast.spacecraft["Sat"]["SMA"] = 7000      # typed, dotted mutation
issues = lint(ast)                       # unused resources, undeclared refs, type mismatches
text = format(ast, style="canonical")    # deterministic re-emission
open("flyby.script", "w").write(text)
```

## Roadmap

| Milestone | Scope |
| --------- | ----- |
| **v0.1**  | Tree-sitter grammar, parser, `parse` CLI; the full stock R2026a sample corpus parses with zero errors and re-emits byte-for-byte. |
| **v0.2**  | Typed AST + mutation API, canonical idempotent formatter, pre-commit hook. |
| **v0.3**  | gmatpy-reflection field catalogue, linter, pygls LSP server, VS Code extension. |

## License

[MIT](LICENSE) — part of the [astro-tools](https://github.com/astro-tools) organization.
