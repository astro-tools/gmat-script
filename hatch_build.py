"""Hatchling build hook: compile and vendor the tree-sitter-gmat grammar.

Compiles the grammar's generated parser (``tree-sitter-gmat/src/parser.c``), its external scanner
(``tree-sitter-gmat/src/scanner.c``, which lexes GMAT's raw rest-of-line ``unquoted_value`` — D13),
and the Python binding (``tree-sitter-gmat/bindings/python/binding.c``) into a single CPython
stable-ABI (abi3, floor 3.10) extension, vendored at ``gmat_script/_grammar/_binding``. The wheel
therefore ships the compiled grammar and needs no C or Node toolchain at install time (decisions
D2 / D9 / D12). Building it needs only a C compiler — never Node or the tree-sitter CLI, because
``parser.c`` is committed.

One abi3 wheel per platform covers every supported Python, so the wheel is tagged ``cp310-abi3-*``.
"""

from __future__ import annotations

import shutil
import sysconfig
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

# CPython stable-ABI floor: 3.10.
_ABI3_MACRO = "0x030A0000"
_ABI3_PYTHON_TAG = "cp310"

_ROOT = Path(__file__).parent
_GRAMMAR = _ROOT / "tree-sitter-gmat"
_PARSER_C = _GRAMMAR / "src" / "parser.c"
_SCANNER_C = _GRAMMAR / "src" / "scanner.c"
_BINDING_C = _GRAMMAR / "bindings" / "python" / "binding.c"
_PARSER_INCLUDE = _GRAMMAR / "src"
_QUERIES_SRC = _GRAMMAR / "queries"

_GRAMMAR_PKG_DIR = _ROOT / "src" / "gmat_script" / "_grammar"
_QUERIES_PKG_DIR = _GRAMMAR_PKG_DIR / "queries"
_EXT_FULLNAME = "gmat_script._grammar._binding"


def _platform_tag() -> str:
    """Wheel platform tag for the building host (cibuildwheel/auditwheel re-tag for manylinux)."""
    return sysconfig.get_platform().replace("-", "_").replace(".", "_")


def _compile_extension() -> Path:
    """Compile parser.c + binding.c into the vendored abi3 extension; return its path."""
    # Imported lazily: setuptools is a build-time-only dependency, never a runtime one.
    from setuptools import Distribution, Extension
    from setuptools.command.build_ext import build_ext

    # Drop any stale binding from a previous build so the post-build glob is unambiguous.
    for stale in _GRAMMAR_PKG_DIR.glob("_binding*"):
        if stale.suffix in {".so", ".pyd", ".dylib"}:
            stale.unlink()

    ext = Extension(
        name=_EXT_FULLNAME,
        sources=[str(_PARSER_C), str(_SCANNER_C), str(_BINDING_C)],
        include_dirs=[str(_PARSER_INCLUDE)],
        define_macros=[("Py_LIMITED_API", _ABI3_MACRO)],
        py_limited_api=True,
    )
    dist = Distribution({"name": "gmat-script", "ext_modules": [ext]})
    cmd = build_ext(dist)
    cmd.ensure_finalized()
    # Emit straight into the source package so editable installs import it too.
    cmd.build_lib = str(_ROOT / "src")
    cmd.run()

    built = next(
        p for p in _GRAMMAR_PKG_DIR.glob("_binding*") if p.suffix in {".so", ".pyd", ".dylib"}
    )
    return built


def _vendor_queries() -> list[Path]:
    """Copy the grammar's tree-sitter queries into the package; return the vendored paths.

    The ``.scm`` queries live canonically with the grammar (``tree-sitter-gmat/queries/``, D1) and
    ship in the sdist, but the wheel packages only ``src/gmat_script``. The language server loads
    ``locals.scm`` / ``tags.scm`` at runtime, so they must travel in the wheel. This mirrors the
    compiled-binding vendoring: copy them into ``gmat_script/_grammar/queries/`` (git-ignored, the
    canonical source stays single) so editable installs find them in the source tree, and
    force-include them so they land in the built wheel.
    """
    _QUERIES_PKG_DIR.mkdir(parents=True, exist_ok=True)
    vendored: list[Path] = []
    for query in sorted(_QUERIES_SRC.glob("*.scm")):
        dest = _QUERIES_PKG_DIR / query.name
        shutil.copyfile(query, dest)
        vendored.append(dest)
    return vendored


class TreeSitterGrammarBuildHook(BuildHookInterface):
    """Compile the vendored grammar extension and mark the wheel platform-specific (abi3)."""

    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        built = _compile_extension()
        queries = _vendor_queries()

        build_data["pure_python"] = False
        build_data["infer_tag"] = False
        build_data["tag"] = f"{_ABI3_PYTHON_TAG}-abi3-{_platform_tag()}"
        # Ship the compiled extension and the vendored queries even though they are git-ignored.
        build_data["force_include"][str(built)] = str(built.relative_to(_ROOT / "src"))
        for query in queries:
            build_data["force_include"][str(query)] = str(query.relative_to(_ROOT / "src"))
