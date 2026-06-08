// GMAT Script — a thin VS Code client over the gmat-script language server.
//
// Highlighting comes from the bundled TextMate grammar and works with no server. Everything
// richer — hover, diagnostics, definition, references, symbols, completion, and the formatter
// that drives format-on-save — is served by the pygls language server (`gmat-script-lsp`), which
// the user installs with `pip install "gmat-script[lsp]"`. The client launches that process over
// stdio. If it cannot start, the extension degrades to highlighting only and hints once at the
// install step rather than failing activation.

import {
  workspace,
  window,
  type ExtensionContext,
  type WorkspaceConfiguration,
} from "vscode";
import {
  LanguageClient,
  TransportKind,
  type Executable,
  type LanguageClientOptions,
  type ServerOptions,
} from "vscode-languageclient/node";

let client: LanguageClient | undefined;
let hintShown = false;

/** The client id. `vscode-languageclient` derives the `gmatScript.trace.server` setting from it. */
const CLIENT_ID = "gmatScript";

/** Resolve the server launch command from configuration (`pythonPath` wins over `path`). */
function resolveServer(config: WorkspaceConfiguration): Executable {
  const extraArgs = config.get<string[]>("server.args", []);
  const pythonPath = config.get<string>("server.pythonPath", "").trim();
  if (pythonPath) {
    return {
      command: pythonPath,
      args: ["-m", "gmat_script.lsp", ...extraArgs],
      transport: TransportKind.stdio,
    };
  }
  const command = config.get<string>("server.path", "gmat-script-lsp");
  return { command, args: extraArgs, transport: TransportKind.stdio };
}

/** Tell the user once that highlighting works but the richer features need the server. */
function hintMissingServer(): void {
  if (hintShown) {
    return;
  }
  hintShown = true;
  void window.showWarningMessage(
    "GMAT Script: the language server could not start. Syntax highlighting still works, but " +
      "hover, diagnostics, completion, and formatting need it. Install it with " +
      '`pip install "gmat-script[lsp]"`, then reload the window — or set ' +
      "`gmatScript.server.pythonPath` to a Python environment that has it.",
  );
}

export async function activate(context: ExtensionContext): Promise<void> {
  const config = workspace.getConfiguration("gmatScript");
  const serverOptions: ServerOptions = resolveServer(config);

  const clientOptions: LanguageClientOptions = {
    documentSelector: [
      { scheme: "file", language: "gmat" },
      { scheme: "untitled", language: "gmat" },
    ],
    // A broken server must never break the editor: surface the install hint instead of reinitializing.
    initializationFailedHandler: () => {
      hintMissingServer();
      return false;
    },
  };

  client = new LanguageClient(
    CLIENT_ID,
    "GMAT Script Language Server",
    serverOptions,
    clientOptions,
  );
  context.subscriptions.push(client);

  try {
    await client.start();
  } catch {
    // The server binary is missing or failed to spawn — keep highlighting, hint once.
    hintMissingServer();
    client = undefined;
  }
}

export function deactivate(): Thenable<void> | undefined {
  return client?.stop();
}
