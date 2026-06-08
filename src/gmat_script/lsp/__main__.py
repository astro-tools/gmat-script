"""``python -m gmat_script.lsp`` — run the language server over stdio."""

from __future__ import annotations

import sys

from . import main

if __name__ == "__main__":
    sys.exit(main())
