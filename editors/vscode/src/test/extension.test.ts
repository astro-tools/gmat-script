// Activation smoke test: prove the extension is discoverable, that .script / .gmf files bind to
// the `gmat` language, and that activation succeeds even with no language server installed (the
// CI runner has no `gmat-script-lsp`, so this also exercises the graceful-degradation path).

import * as assert from "assert";
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import * as vscode from "vscode";

const EXTENSION_ID = "djankov.gmat-script";

function writeTempFile(name: string, content: string): vscode.Uri {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "gmat-smoke-"));
  const file = path.join(dir, name);
  fs.writeFileSync(file, content);
  return vscode.Uri.file(file);
}

suite("GMAT Script activation", () => {
  test("the extension is installed", () => {
    assert.ok(vscode.extensions.getExtension(EXTENSION_ID), "extension not found");
  });

  test("a .script file binds to the gmat language and the extension activates", async () => {
    const uri = writeTempFile(
      "smoke.script",
      "Create Spacecraft Sat;\nBeginMissionSequence;\nPropagate Sat;\n",
    );
    const doc = await vscode.workspace.openTextDocument(uri);
    assert.strictEqual(doc.languageId, "gmat", "the .script file was not recognised as gmat");

    const ext = vscode.extensions.getExtension(EXTENSION_ID);
    if (!ext) {
      throw new Error("extension not found");
    }
    await ext.activate();
    assert.ok(ext.isActive, "extension did not activate");
  });

  test("a .gmf file binds to the gmat language", async () => {
    const uri = writeTempFile("fn.gmf", "function cross(c, a, b)\n");
    const doc = await vscode.workspace.openTextDocument(uri);
    assert.strictEqual(doc.languageId, "gmat", "the .gmf file was not recognised as gmat");
  });
});
