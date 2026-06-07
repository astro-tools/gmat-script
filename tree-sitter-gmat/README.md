# tree-sitter-gmat

A [tree-sitter](https://tree-sitter.github.io/tree-sitter/) grammar for
[GMAT](https://gmat.gsfc.nasa.gov/) (NASA's General Mission Analysis Tool) mission scripts —
`.script` files and GmatFunctions (`.gmf`), one grammar for both.

It is a deliberately permissive superset of GMAT's scripting language: `Create <Type> <name>`
accepts any resource type, and unknown command keywords parse as generic command nodes, so a new
resource or command never needs a grammar change. Any input re-emits **byte-for-byte**, comments
and layout included. The grammar parses all 162 `.script` and 9 `.gmf` files shipped with NASA
GMAT R2026a with zero errors.

## What's in the package

- the generated parser (`src/parser.c` and the external scanner) plus `grammar.js`
- `queries/highlights.scm` for editor syntax highlighting
- the `tree-sitter` config — scope `source.gmat`, file types `.script` and `.gmf`

## Usage

This package provides the grammar and highlight queries for tree-sitter-based editors and tooling.
Point a tree-sitter-aware editor (Neovim / nvim-treesitter, Helix, Zed, …) or the
[tree-sitter CLI](https://tree-sitter.github.io/tree-sitter/using-parsers/) at it for parsing and
`.script` / `.gmf` syntax highlighting. To embed the parser in another language, compile the
bundled `src/parser.c` against that language's tree-sitter bindings.

## Parsing from Python

For a batteries-included parser built on this grammar — `parse()`, structured error reporting,
byte-exact re-emission, and the `gmat-script parse` CLI — use
[`gmat-script`](https://pypi.org/project/gmat-script/):

```bash
pip install gmat-script
```

## Links

- Documentation: https://astro-tools.github.io/gmat-script/
- Source: https://github.com/astro-tools/gmat-script

## License

[MIT](https://github.com/astro-tools/gmat-script/blob/main/LICENSE) — part of the
[astro-tools](https://github.com/astro-tools) organization.
