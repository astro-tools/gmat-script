"""Smoke tests: the package imports, the vendored grammar loads, and the CLI is wired."""

from __future__ import annotations

import pytest

import gmat_script
from gmat_script import cli


def test_version_is_a_nonempty_string() -> None:
    assert isinstance(gmat_script.__version__, str)
    assert gmat_script.__version__


def test_parse_is_exported_and_parses() -> None:
    tree = gmat_script.parse("Create Spacecraft Sat;")
    assert tree.root_node.type == "source_file"
    assert not tree.has_errors


def test_vendored_grammar_loads_and_parses() -> None:
    """The wheel ships a compiled grammar the tree-sitter runtime can load (D2 / D9 / D12)."""
    from tree_sitter import Language, Parser

    from gmat_script._grammar import language

    parser = Parser(Language(language()))
    tree = parser.parse(b"Create Spacecraft Sat;\nSat.SMA = 7000;\n")
    assert tree.root_node.type == "source_file"
    assert not tree.root_node.has_error


def test_cli_help_exits_zero() -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0


def test_cli_parse_subcommand_is_stubbed() -> None:
    assert cli.main(["parse", "mission.script"]) == 2
