# The language server

gmat-script ships a [Language Server Protocol](https://microsoft.github.io/language-server-protocol/)
server that brings the parser, linter, field catalogue, and tree-sitter queries to any LSP-capable
editor — Neovim, Emacs, VS Code, Helix, and the rest. It is editor-agnostic: the editor speaks LSP
to the server, so a single backend serves every client.

The server is built on [pygls](https://github.com/openlawlibrary/pygls) and, like the rest of the
library, needs no GMAT, C, or Node toolchain at runtime.

## Installing

pygls is an optional dependency, so the server lives behind the `lsp` extra — a plain
`pip install gmat-script` stays lean and pulls in only the parser:

```console
$ pip install "gmat-script[lsp]"
```

This puts a `gmat-script-lsp` console script on your `PATH`. The server speaks LSP over stdin/stdout;
you do not run it by hand — your editor launches it and talks to it. Running it without the extra
installed prints a one-line hint to install `gmat-script[lsp]`.

## Features

The server responds to the standard requests, each backed by an existing library layer:

| Capability | What you get | Backed by |
|------------|--------------|-----------|
| `publishDiagnostics` | Live errors and warnings as you type, debounced on change | the linter (and the parser's syntax errors) |
| `hover` | Field documentation — type, default, allowed values, units, reference target | the field catalogue |
| `completion` | Resource names, the fields valid for the resource under the cursor, and a field's enum values | the catalogue + the parsed model |
| `definition` | Jump to a resource's `Create` declaration | the `locals` query |
| `references` | Every use of a resource across the file | the `locals` query |
| `documentSymbol` | The outline — every `Create`'d resource and GmatFunction header | the `tags` query |
| `formatting` / `rangeFormatting` | Canonical re-emission on save or on demand | the formatter |

Diagnostics update on every edit and a malformed, half-typed buffer never crashes the server: the
error-recovering parse still yields a usable tree, so completion and hover keep working while you
type. Completion and hover quality follow the catalogue — a field GMAT does not reflect simply has
no hover, and the feature degrades quietly rather than guessing.

## Editor setup

Point your editor's LSP client at the `gmat-script-lsp` command for GMAT `.script` and `.gmf` files.

### Neovim (`nvim-lspconfig` style)

```lua
vim.api.nvim_create_autocmd("FileType", {
  pattern = { "gmat" },
  callback = function(args)
    vim.lsp.start({
      name = "gmat-script-lsp",
      cmd = { "gmat-script-lsp" },
      root_dir = vim.fs.dirname(args.file),
    })
  end,
})
```

(Map the `gmat` filetype to `*.script` / `*.gmf` with an `autocmd`/`filetype` rule of your choice.)

### Emacs (`eglot`)

```elisp
(add-to-list 'eglot-server-programs '(gmat-mode . ("gmat-script-lsp")))
```

### VS Code

The VS Code extension bundles a client that launches this server for you — install it from the
Marketplace rather than configuring the command by hand.

## How it fits together

The server is a thin shell over the same functions the [CLI](cli.md) and Python API use:

- diagnostics come from [`lint`](lint.md) and the parser's [error reporting](errors.md);
- hover and completion read the bundled field catalogue;
- definition, references, and the symbol outline run the grammar's tree-sitter queries;
- formatting calls the [canonical formatter](formatting.md).

Positions cross the boundary cleanly: the library reports 1-indexed byte positions, and the server
converts them to the protocol's 0-indexed UTF-16 positions (so multi-byte characters land in the
right column).
