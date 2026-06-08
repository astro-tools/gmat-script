"""Tests for the pygls server (:mod:`gmat_script.lsp.server`) and the console entry.

Two layers: the request handlers are driven **in-process** against a server with a populated
workspace (covering the protocol shell, the debounce, and the never-crash wrapper without a real
connection), and one end-to-end **smoke test drives the server over stdio** as a subprocess — the
issue's definition-of-done — asserting every feature responds on a known document, that diagnostics
update live on an edit, and that malformed input never crashes the connection.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import json
import queue
import subprocess
import sys
import threading
from collections.abc import Iterator
from typing import Any, cast

import pytest
from lsprotocol import types as lsp
from pygls.workspace import Workspace

from gmat_script import lsp as lsp_pkg
from gmat_script.lsp import analysis as analysis_module
from gmat_script.lsp import server as server_module

URI = "file:///mission.script"
SCRIPT = (
    "Create Spacecraft Sat\n"
    "Sat.SMA = 7000\n"
    "Create ForceModel FM\n"
    "\n"
    "BeginMissionSequence\n"
    "Propagate Prop(Sat)\n"
)


# ----------------------------------------------------------------------------
# in-process handler tests


def _server_with(text: str = SCRIPT, uri: str = URI) -> server_module.GmatScriptLanguageServer:
    """A server whose workspace already holds *text* at *uri* (no connection needed)."""
    server = server_module.create_server()
    server.protocol._workspace = Workspace(None, position_encoding=lsp.PositionEncodingKind.Utf16)
    server.workspace.put_text_document(
        lsp.TextDocumentItem(uri=uri, language_id="gmat", version=1, text=text)
    )
    return server


def _capture_publishes(
    server: server_module.GmatScriptLanguageServer,
    monkeypatch: pytest.MonkeyPatch,
) -> list[lsp.PublishDiagnosticsParams]:
    """Replace the server's publish notification with a recorder (no transport in unit tests)."""
    published: list[lsp.PublishDiagnosticsParams] = []
    monkeypatch.setattr(
        server, "text_document_publish_diagnostics", lambda params: published.append(params)
    )
    return published


def _ident(uri: str = URI) -> lsp.TextDocumentIdentifier:
    return lsp.TextDocumentIdentifier(uri=uri)


def test_did_open_publishes_diagnostics(monkeypatch: pytest.MonkeyPatch) -> None:
    server = _server_with()
    published = _capture_publishes(server, monkeypatch)
    item = lsp.TextDocumentItem(uri=URI, language_id="gmat", version=1, text=SCRIPT)
    server_module._did_open(server, lsp.DidOpenTextDocumentParams(text_document=item))
    assert len(published) == 1
    assert published[0].uri == URI
    assert any(d.code == "unused-resource" for d in published[0].diagnostics)


def test_did_change_publishes_after_debounce(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server_module, "_DEBOUNCE_SECONDS", 0)
    server = _server_with()
    published = _capture_publishes(server, monkeypatch)
    params = lsp.DidChangeTextDocumentParams(
        text_document=lsp.VersionedTextDocumentIdentifier(uri=URI, version=2),
        content_changes=[],
    )
    asyncio.run(server_module._did_change(server, params))
    assert len(published) == 1 and published[0].uri == URI


def test_did_change_superseded_does_not_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    server = _server_with()
    published = _capture_publishes(server, monkeypatch)

    async def _supersede(_: float) -> None:
        # A newer change arrives during the debounce wait, bumping the generation.
        server.generations[URI] = 999

    monkeypatch.setattr(asyncio, "sleep", _supersede)
    params = lsp.DidChangeTextDocumentParams(
        text_document=lsp.VersionedTextDocumentIdentifier(uri=URI, version=2),
        content_changes=[],
    )
    asyncio.run(server_module._did_change(server, params))
    assert published == []


def test_did_close_clears_diagnostics(monkeypatch: pytest.MonkeyPatch) -> None:
    server = _server_with()
    server.generations[URI] = 3
    published = _capture_publishes(server, monkeypatch)
    server_module._did_close(server, lsp.DidCloseTextDocumentParams(text_document=_ident()))
    assert published == [] or published[0].diagnostics == []
    assert published[-1].uri == URI and published[-1].diagnostics == []
    assert URI not in server.generations


def test_hover_handler() -> None:
    server = _server_with()
    params = lsp.HoverParams(text_document=_ident(), position=lsp.Position(line=1, character=5))
    hover = server_module._hover(server, params)
    assert hover is not None
    assert isinstance(hover.contents, lsp.MarkupContent)
    assert "SMA" in hover.contents.value


def test_definition_handler() -> None:
    server = _server_with()
    params = lsp.DefinitionParams(
        text_document=_ident(), position=lsp.Position(line=5, character=15)
    )
    locations = server_module._definition(server, params)
    assert locations and locations[0].uri == URI
    assert locations[0].range.start == lsp.Position(line=0, character=18)


def test_references_handler() -> None:
    server = _server_with()
    params = lsp.ReferenceParams(
        text_document=_ident(),
        position=lsp.Position(line=0, character=19),
        context=lsp.ReferenceContext(include_declaration=True),
    )
    locations = server_module._references(server, params)
    assert len(locations) >= 2 and all(loc.uri == URI for loc in locations)


def test_document_symbol_handler() -> None:
    server = _server_with()
    symbols = server_module._document_symbol(
        server, lsp.DocumentSymbolParams(text_document=_ident())
    )
    assert [s.name for s in symbols] == ["Sat", "FM"]


def test_completion_handler() -> None:
    server = _server_with()
    params = lsp.CompletionParams(
        text_document=_ident(), position=lsp.Position(line=5, character=0)
    )
    result = server_module._completion(server, params)
    assert result.is_incomplete is False
    assert "Sat" in {item.label for item in result.items}


def test_formatting_handler() -> None:
    server = _server_with("GMAT Sat.SMA=7000;\n")
    params = lsp.DocumentFormattingParams(
        text_document=_ident(), options=lsp.FormattingOptions(tab_size=4, insert_spaces=True)
    )
    edits = server_module._formatting(server, params)
    assert len(edits) == 1 and edits[0].new_text == "Sat.SMA = 7000\n"


def test_range_formatting_handler() -> None:
    server = _server_with("GMAT Sat.SMA=7000;\n")
    params = lsp.DocumentRangeFormattingParams(
        text_document=_ident(),
        range=lsp.Range(start=lsp.Position(0, 0), end=lsp.Position(0, 5)),
        options=lsp.FormattingOptions(tab_size=4, insert_spaces=True),
    )
    edits = server_module._range_formatting(server, params)
    assert len(edits) == 1 and edits[0].new_text == "Sat.SMA = 7000\n"


def test_safe_returns_default_on_exception() -> None:
    def boom() -> str:
        raise RuntimeError("boom")

    assert server_module._safe(boom, "fallback") == "fallback"


def test_handler_survives_analysis_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_: object, **__: object) -> None:
        raise RuntimeError("analysis blew up")

    monkeypatch.setattr(analysis_module, "hover_at", boom)
    server = _server_with()
    params = lsp.HoverParams(text_document=_ident(), position=lsp.Position(line=1, character=5))
    assert server_module._hover(server, params) is None


# ----------------------------------------------------------------------------
# console entry: graceful degradation without the extra


def test_entry_point_hints_when_pygls_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: None)
    assert lsp_pkg.main([]) == 1
    assert "gmat-script[lsp]" in capsys.readouterr().err


def test_entry_point_starts_server_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server_module, "main", lambda argv=None: 0)
    assert lsp_pkg.main([]) == 0


# ----------------------------------------------------------------------------
# end-to-end stdio smoke test (the definition-of-done integration test)


class _StdioClient:
    """A minimal LSP JSON-RPC client speaking to the server subprocess over stdio."""

    def __init__(self) -> None:
        self._proc = subprocess.Popen(
            [sys.executable, "-m", "gmat_script.lsp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._messages: queue.Queue[dict[str, Any]] = queue.Queue()
        self._id = 0
        self._stdout = self._proc.stdout
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self._stderr_chunks: list[bytes] = []
        self._draining = threading.Thread(target=self._drain_stderr, daemon=True)
        self._draining.start()

    def _drain_stderr(self) -> None:
        stderr = self._proc.stderr
        assert stderr is not None
        for chunk in iter(lambda: stderr.read(4096), b""):
            self._stderr_chunks.append(chunk)

    def _read_loop(self) -> None:
        assert self._stdout is not None
        try:
            while True:
                header = b""
                while not header.endswith(b"\r\n\r\n"):
                    byte = self._stdout.read(1)
                    if not byte:
                        return
                    header += byte
                length = next(
                    int(line.split(b":", 1)[1])
                    for line in header.split(b"\r\n")
                    if line.lower().startswith(b"content-length")
                )
                self._messages.put(json.loads(self._stdout.read(length)))
        except Exception:  # the loop ends when the process closes its pipe
            return

    def _write(self, payload: dict[str, Any]) -> None:
        assert self._proc.stdin is not None
        data = json.dumps(payload).encode("utf-8")
        self._proc.stdin.write(f"Content-Length: {len(data)}\r\n\r\n".encode() + data)
        self._proc.stdin.flush()

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def request(self, method: str, params: dict[str, Any], timeout: float = 15.0) -> Any:
        self._id += 1
        request_id = self._id
        self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        return self._await(lambda m: m.get("id") == request_id, timeout)["result"]

    def await_notification(self, method: str, timeout: float = 15.0) -> dict[str, Any]:
        params = self._await(lambda m: m.get("method") == method, timeout)["params"]
        return cast("dict[str, Any]", params)

    def _await(self, predicate: Any, timeout: float) -> dict[str, Any]:
        deadline = timeout
        while True:
            try:
                message = self._messages.get(timeout=deadline)
            except queue.Empty:  # pragma: no cover - only on a hung/broken server
                stderr = b"".join(self._stderr_chunks).decode(errors="replace")
                raise AssertionError(f"timed out; server stderr:\n{stderr}") from None
            if predicate(message):
                return message

    def close(self) -> int:
        with contextlib.suppress(OSError):  # the pipe may already be closed
            self._proc.stdin.close()  # type: ignore[union-attr]
        return self._proc.wait(timeout=15)


@pytest.fixture
def client() -> Iterator[_StdioClient]:
    connection = _StdioClient()
    try:
        yield connection
    finally:
        if connection._proc.poll() is None:  # pragma: no cover - normal path exits via `exit`
            connection._proc.kill()
            connection._proc.wait(timeout=10)


def _open(client: _StdioClient, text: str = SCRIPT) -> None:
    client.request("initialize", {"processId": None, "rootUri": None, "capabilities": {}})
    client.notify("initialized", {})
    client.notify(
        "textDocument/didOpen",
        {"textDocument": {"uri": URI, "languageId": "gmat", "version": 1, "text": text}},
    )


def test_stdio_smoke(client: _StdioClient) -> None:
    _open(client)

    # didOpen triggers diagnostics (FM is unused).
    diagnostics = client.await_notification("textDocument/publishDiagnostics")["diagnostics"]
    assert any(d["code"] == "unused-resource" for d in diagnostics)

    hover = client.request(
        "textDocument/hover",
        {"textDocument": {"uri": URI}, "position": {"line": 1, "character": 5}},
    )
    assert "SMA" in hover["contents"]["value"]

    definition = client.request(
        "textDocument/definition",
        {"textDocument": {"uri": URI}, "position": {"line": 5, "character": 15}},
    )
    assert definition[0]["range"]["start"] == {"line": 0, "character": 18}

    references = client.request(
        "textDocument/references",
        {
            "textDocument": {"uri": URI},
            "position": {"line": 0, "character": 19},
            "context": {"includeDeclaration": True},
        },
    )
    assert len(references) >= 2

    symbols = client.request("textDocument/documentSymbol", {"textDocument": {"uri": URI}})
    assert [s["name"] for s in symbols] == ["Sat", "FM"]

    completion = client.request(
        "textDocument/completion",
        {"textDocument": {"uri": URI}, "position": {"line": 5, "character": 0}},
    )
    assert "Sat" in {item["label"] for item in completion["items"]}

    formatting = client.request(
        "textDocument/formatting",
        {"textDocument": {"uri": URI}, "options": {"tabSize": 4, "insertSpaces": True}},
    )
    assert len(formatting) >= 1

    range_formatting = client.request(
        "textDocument/rangeFormatting",
        {
            "textDocument": {"uri": URI},
            "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 5}},
            "options": {"tabSize": 4, "insertSpaces": True},
        },
    )
    assert len(range_formatting) >= 1

    client.request("shutdown", {})
    client.notify("exit", {})
    assert client.close() == 0


def test_stdio_live_diagnostics_update_and_survive_malformed(client: _StdioClient) -> None:
    _open(
        client,
        "Create Spacecraft Sat\nSat.SMA = 7000\n\nBeginMissionSequence\nPropagate Prop(Sat)\n",
    )
    first = client.await_notification("textDocument/publishDiagnostics")
    assert first["diagnostics"] == []

    # A malformed edit must not crash the server, and must republish with a syntax error.
    client.notify(
        "textDocument/didChange",
        {
            "textDocument": {"uri": URI, "version": 2},
            "contentChanges": [{"text": "Create Spacecraft\nSat.SMA = = =\n"}],
        },
    )
    updated = client.await_notification("textDocument/publishDiagnostics")
    assert any(d["severity"] == lsp.DiagnosticSeverity.Error for d in updated["diagnostics"])

    client.request("shutdown", {})
    client.notify("exit", {})
    assert client.close() == 0
