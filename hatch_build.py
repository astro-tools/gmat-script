"""Hatchling build hook: compile and vendor the tree-sitter-gmat grammar.

Compiles the grammar's generated parser (``tree-sitter-gmat/src/parser.c``) together with the
Python binding (``tree-sitter-gmat/bindings/python/binding.c``) into a single CPython
stable-ABI (abi3, floor 3.10) extension, vendored at ``gmat_script/_grammar/_binding``. The wheel
therefore ships the compiled grammar and needs no C or Node toolchain at install time (decisions
D2 / D9 / D12). Building it needs only a C compiler — never Node or the tree-sitter CLI, because
``parser.c`` is committed.

One abi3 wheel per platform covers every supported Python, so the wheel is tagged ``cp310-abi3-*``.
"""

from __future__ import annotations

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
_BINDING_C = _GRAMMAR / "bindings" / "python" / "binding.c"
_PARSER_INCLUDE = _GRAMMAR / "src"

_GRAMMAR_PKG_DIR = _ROOT / "src" / "gmat_script" / "_grammar"
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
        sources=[str(_PARSER_C), str(_BINDING_C)],
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


class TreeSitterGrammarBuildHook(BuildHookInterface):
    """Compile the vendored grammar extension and mark the wheel platform-specific (abi3)."""

    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        built = _compile_extension()

        build_data["pure_python"] = False
        build_data["infer_tag"] = False
        build_data["tag"] = f"{_ABI3_PYTHON_TAG}-abi3-{_platform_tag()}"
        # Ship the compiled extension even though it is git-ignored.
        build_data["force_include"][str(built)] = str(built.relative_to(_ROOT / "src"))
