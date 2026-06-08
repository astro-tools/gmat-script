"""The pygls language server — a thin protocol shell over :mod:`gmat_script.lsp.analysis`.

The server registers the LSP feature handlers, syncs documents (pygls keeps each buffer
current from ``didChange`` notifications), and debounces diagnostics so a fast typist triggers one
parse per quiet window rather than one per keystroke. Every request handler delegates to a pure
analysis function and is wrapped so a malformed buffer can never crash the connection (D7); the
diagnostics path goes through the linter, which already degrades to syntax errors on a broken parse.

Handlers are module-level functions taking ``(ls, params)`` — pygls injects the server because the
first parameter is named ``ls`` — and per-URI debounce state lives on the :class:`LanguageServer`
subclass, so both are reachable in-process for unit tests; only the stdio run loop in :func:`main`
needs a real connection.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, TypeVar

from lsprotocol import types
from pygls.lsp.server import LanguageServer

from .. import __version__
from . import analysis

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["SERVER_NAME", "GmatScriptLanguageServer", "create_server", "main"]

SERVER_NAME = "gmat-script-lsp"
# Quiet window after the last keystroke before diagnostics recompute (the issue's debounce).
_DEBOUNCE_SECONDS = 0.2

_LOGGER = logging.getLogger(__name__)
_T = TypeVar("_T")


def _safe(thunk: Callable[[], _T], default: _T) -> _T:
    """Run *thunk*, returning *default* if it raises — a request must never crash the server."""
    try:
        return thunk()
    except Exception:  # an editor server stays up no matter what a buffer holds
        _LOGGER.exception("gmat-script-lsp request handler failed")
        return default


class GmatScriptLanguageServer(LanguageServer):
    """The gmat-script language server, carrying per-URI diagnostics debounce state."""

    def __init__(self) -> None:
        super().__init__(SERVER_NAME, __version__)
        # Per-URI change counter: each change bumps it, and a debounced task publishes only if its
        # generation is still current, so a superseded keystroke never publishes a stale parse.
        self.generations: dict[str, int] = {}

    def refresh_diagnostics(self, uri: str) -> None:
        """Recompute and publish diagnostics for the document at *uri*."""
        document = self.workspace.get_text_document(uri)
        self.text_document_publish_diagnostics(
            types.PublishDiagnosticsParams(
                uri=uri,
                version=document.version,
                diagnostics=analysis.diagnostics_for(document.source),
            )
        )


def _did_open(ls: GmatScriptLanguageServer, params: types.DidOpenTextDocumentParams) -> None:
    ls.refresh_diagnostics(params.text_document.uri)


async def _did_change(
    ls: GmatScriptLanguageServer, params: types.DidChangeTextDocumentParams
) -> None:
    uri = params.text_document.uri
    generation = ls.generations.get(uri, 0) + 1
    ls.generations[uri] = generation
    await asyncio.sleep(_DEBOUNCE_SECONDS)
    if ls.generations.get(uri) == generation:
        ls.refresh_diagnostics(uri)


def _did_close(ls: GmatScriptLanguageServer, params: types.DidCloseTextDocumentParams) -> None:
    uri = params.text_document.uri
    ls.generations.pop(uri, None)
    # Clear the closed file's diagnostics in the client.
    ls.text_document_publish_diagnostics(types.PublishDiagnosticsParams(uri=uri, diagnostics=[]))


def _hover(ls: GmatScriptLanguageServer, params: types.HoverParams) -> types.Hover | None:
    document = ls.workspace.get_text_document(params.text_document.uri)
    return _safe(lambda: analysis.hover_at(document.source, params.position), None)


def _definition(
    ls: GmatScriptLanguageServer, params: types.DefinitionParams
) -> list[types.Location]:
    uri = params.text_document.uri
    document = ls.workspace.get_text_document(uri)
    empty: list[types.Range] = []
    ranges = _safe(lambda: analysis.definition_ranges(document.source, params.position), empty)
    return [types.Location(uri=uri, range=found) for found in ranges]


def _references(
    ls: GmatScriptLanguageServer, params: types.ReferenceParams
) -> list[types.Location]:
    uri = params.text_document.uri
    document = ls.workspace.get_text_document(uri)
    include = params.context.include_declaration
    empty: list[types.Range] = []
    ranges = _safe(
        lambda: analysis.reference_ranges(
            document.source, params.position, include_declaration=include
        ),
        empty,
    )
    return [types.Location(uri=uri, range=found) for found in ranges]


def _document_symbol(
    ls: GmatScriptLanguageServer, params: types.DocumentSymbolParams
) -> list[types.DocumentSymbol]:
    document = ls.workspace.get_text_document(params.text_document.uri)
    return _safe(lambda: analysis.document_symbols(document.source), [])


def _completion(
    ls: GmatScriptLanguageServer, params: types.CompletionParams
) -> types.CompletionList:
    document = ls.workspace.get_text_document(params.text_document.uri)
    empty: list[types.CompletionItem] = []
    items = _safe(lambda: analysis.completions_at(document.source, params.position), empty)
    return types.CompletionList(is_incomplete=False, items=items)


def _formatting(
    ls: GmatScriptLanguageServer, params: types.DocumentFormattingParams
) -> list[types.TextEdit]:
    document = ls.workspace.get_text_document(params.text_document.uri)
    return _safe(lambda: analysis.format_edits(document.source), [])


def _range_formatting(
    ls: GmatScriptLanguageServer, params: types.DocumentRangeFormattingParams
) -> list[types.TextEdit]:
    # The formatter is whole-document (D14), so a range request reformats the whole buffer.
    document = ls.workspace.get_text_document(params.text_document.uri)
    return _safe(lambda: analysis.format_edits(document.source), [])


def _register(server: GmatScriptLanguageServer) -> None:
    """Register every feature handler on *server*."""
    server.feature(types.TEXT_DOCUMENT_DID_OPEN)(_did_open)
    server.feature(types.TEXT_DOCUMENT_DID_CHANGE)(_did_change)
    server.feature(types.TEXT_DOCUMENT_DID_CLOSE)(_did_close)
    server.feature(types.TEXT_DOCUMENT_HOVER)(_hover)
    server.feature(types.TEXT_DOCUMENT_DEFINITION)(_definition)
    server.feature(types.TEXT_DOCUMENT_REFERENCES)(_references)
    server.feature(types.TEXT_DOCUMENT_DOCUMENT_SYMBOL)(_document_symbol)
    server.feature(
        types.TEXT_DOCUMENT_COMPLETION, types.CompletionOptions(trigger_characters=["."])
    )(_completion)
    server.feature(types.TEXT_DOCUMENT_FORMATTING)(_formatting)
    server.feature(types.TEXT_DOCUMENT_RANGE_FORMATTING)(_range_formatting)


def create_server() -> GmatScriptLanguageServer:
    """Build a configured (but not yet running) language server."""
    server = GmatScriptLanguageServer()
    _register(server)
    return server


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - stdio run loop
    """Run the server over stdio until the client disconnects (*argv* is unused)."""
    create_server().start_io()
    return 0
