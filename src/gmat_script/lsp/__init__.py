"""The gmat-script language server — the ``gmat-script-lsp`` console entry.

pygls is an optional dependency (the ``lsp`` extra), kept out of the base install so
``pip install gmat-script`` stays at its single ``tree-sitter`` runtime dependency (D9). This entry
point degrades gracefully when the extra is absent; importing the server modules
(:mod:`gmat_script.lsp.server`) requires it.
"""

from __future__ import annotations

import importlib.util
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["main"]

_EXTRA_HINT = (
    "gmat-script-lsp needs the language-server extra. Install it with:\n"
    "    pip install 'gmat-script[lsp]'\n"
)


def main(argv: Sequence[str] | None = None) -> int:
    """Console entry: start the server, or hint at the ``lsp`` extra when pygls is missing."""
    if importlib.util.find_spec("pygls") is None:
        sys.stderr.write(_EXTRA_HINT)
        return 1
    from .server import main as serve

    return serve(argv)
