# The VS Code extension

**GMAT Script** brings the grammar, linter, and [language server](lsp.md) to Visual Studio Code:
syntax highlighting, hover docs, live diagnostics, completion, go-to-definition, an outline, and
format-on-save for `.script` and `.gmf` files.

## Installing

Install **GMAT Script** from either marketplace:

- [Visual Studio Marketplace](https://marketplace.visualstudio.com/items?itemName=astro-tools.gmat-mission-script)
  — search *GMAT Script* in the Extensions view, or run
  `code --install-extension astro-tools.gmat-mission-script`.
- [Open VSX](https://open-vsx.org/extension/astro-tools/gmat-mission-script) — for VSCodium, Cursor, Gitpod,
  and other Open VSX–based editors.

The extension bundles **syntax highlighting** as a TextMate grammar, so colouring works the moment
it is installed — no Python, no further setup.

Everything richer — hover, diagnostics, completion, definition, references, the outline, and
formatting — is served by the `gmat-script` language server, which runs on Python. Install it into a
Python environment the extension can reach:

```console
$ pip install "gmat-script[lsp]"
```

This puts a `gmat-script-lsp` command on your `PATH`, which the extension launches automatically. If
it is not found, highlighting still works and the extension points you here. To use a specific
interpreter or virtual environment, set `gmatScript.server.pythonPath` (see
[Settings](#settings)).

## Features

| Feature | Needs the server? |
|---------|:-----------------:|
| Syntax highlighting — resources, commands, fields, control flow, solver blocks, GmatFunction headers | no |
| Hover — a field's type, default, allowed values, units, and reference target | yes |
| Live diagnostics as you type — syntax errors plus linter findings | yes |
| Completion — resource names, the fields valid for the resource under the cursor, and enum values | yes |
| Go to definition / find all references for resources | yes |
| Document outline — every `Create`'d resource and GmatFunction header | yes |
| Format on save — canonical, idempotent re-emission | yes |

The server-backed features are exactly those of the [language server](lsp.md); the extension is the
VS Code client that launches and talks to it. A half-typed buffer never breaks them — the
error-recovering parse keeps hover and completion working while you edit.

## Format on save

Format-on-save is **enabled for GMAT files by default**: the extension sets `editor.formatOnSave`
for the `gmat` language, so saving a `.script` or `.gmf` rewrites it into canonical form via the same
formatter the [CLI](cli.md) and library use. Turn it off per-language if you prefer:

```jsonc
"[gmat]": { "editor.formatOnSave": false }
```

## Settings

| Setting | Default | Description |
|---|---|---|
| `gmatScript.server.path` | `gmat-script-lsp` | Command used to launch the language server. Set an absolute path if it is not on your `PATH`. |
| `gmatScript.server.pythonPath` | _(empty)_ | A Python interpreter with `gmat-script[lsp]` installed; when set, the server runs as `<python> -m gmat_script.lsp` and takes precedence over `server.path`. Point it at a virtual environment. |
| `gmatScript.server.args` | `[]` | Extra arguments passed to the server on launch. |
| `gmatScript.trace.server` | `off` | Trace JSON-RPC traffic to the output channel (`off` / `messages` / `verbose`) when debugging. |

## Other editors

The same server powers any LSP-capable editor — Neovim, Emacs, Helix, and the rest. See the
[language server guide](lsp.md) for editor-agnostic setup.
