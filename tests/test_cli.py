"""The ``gmat-script parse`` CLI: S-expression / JSON output, diagnostics, exit codes (D7 / D8)."""

from __future__ import annotations

import argparse
import io
import json
import re
from typing import TYPE_CHECKING

import pytest

from gmat_script import cli

if TYPE_CHECKING:
    from pathlib import Path

# A well-formed script spanning both sections (configuration + mission sequence).
_CLEAN = "Create Spacecraft Sat\nSat.SMA = 7000\nBeginMissionSequence\nPropagate Prop(Sat);\n"

# An unterminated If — the grammar recovers with a localised ERROR node rather than raising (D7).
_MALFORMED = "BeginMissionSequence\nManeuver Burn(Sat);\nIf Sat.TA > 90\n   Propagate Prop(Sat);\n"

# Non-ASCII only in a comment and value; the S-expression and JSON must stay ASCII on stdout.
_NON_ASCII = "% café au lait ☕\nCreate Spacecraft Sat\n"


def _write(tmp_path: Path, name: str, content: str) -> str:
    """Write *content* to *name* under *tmp_path* verbatim (no newline translation)."""
    path = tmp_path / name
    path.write_text(content, encoding="utf-8", newline="")
    return str(path)


# --- default (S-expression) mode -------------------------------------------------------------


def test_clean_file_prints_sexpr_and_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path, "ok.script", _CLEAN)

    code = cli.main(["parse", path])

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.startswith("(source_file")
    assert "ERROR" not in captured.out
    assert captured.err == ""


def test_malformed_file_prints_partial_tree_and_diagnostic(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path, "bad.script", _MALFORMED)

    code = cli.main(["parse", path])

    captured = capsys.readouterr()
    assert code == 1
    # By default the partial S-expression is still printed (D8) and carries the ERROR node.
    assert captured.out.startswith("(source_file")
    assert "ERROR" in captured.out
    # Diagnostics go to stderr as FILE:line:col: <message> with 1-indexed positions.
    first = captured.err.splitlines()[0]
    assert re.match(rf"^{re.escape(path)}:\d+:\d+: .+$", first)


def test_build_parser_returns_argument_parser() -> None:
    assert isinstance(cli.build_parser(), argparse.ArgumentParser)


# --- --quiet ----------------------------------------------------------------------------------


def test_quiet_clean_is_silent(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _write(tmp_path, "ok.script", _CLEAN)

    code = cli.main(["parse", "-q", path])

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == ""
    assert captured.err == ""


def test_quiet_suppresses_tree_but_keeps_diagnostics(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path, "bad.script", _MALFORMED)

    code = cli.main(["parse", "--quiet", path])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert captured.err.startswith(f"{path}:")


# --- --json -----------------------------------------------------------------------------------


def test_json_single_clean_is_a_bare_object(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path, "ok.script", _CLEAN)

    code = cli.main(["parse", "--json", path])

    captured = capsys.readouterr()
    assert code == 0
    report = json.loads(captured.out)
    assert report == {"file": path, "ok": True, "errors": []}


def test_json_single_malformed_reports_1indexed_positions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path, "bad.script", _MALFORMED)

    code = cli.main(["parse", "--json", path])

    captured = capsys.readouterr()
    assert code == 1
    report = json.loads(captured.out)
    assert report["file"] == path
    assert report["ok"] is False
    assert report["errors"]
    error = report["errors"][0]
    assert set(error) == {"type", "start", "end", "message"}
    assert error["type"] in {"ERROR", "MISSING"}
    assert set(error["start"]) == {"line", "column"}
    assert error["start"]["line"] >= 1
    assert error["start"]["column"] >= 1
    assert isinstance(error["message"], str) and error["message"]


# --- multiple files ---------------------------------------------------------------------------


def test_multiple_files_text_headers_and_failing_exit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ok = _write(tmp_path, "ok.script", _CLEAN)
    bad = _write(tmp_path, "bad.script", _MALFORMED)

    code = cli.main(["parse", ok, bad])

    captured = capsys.readouterr()
    assert code == 1
    # Each tree is attributed with a "; <file>" header when more than one file is given.
    assert f"; {ok}" in captured.out
    assert f"; {bad}" in captured.out
    # Only the malformed file produces a diagnostic.
    assert f"{bad}:" in captured.err
    assert f"{ok}:" not in captured.err


def test_multiple_files_json_is_an_array(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ok = _write(tmp_path, "ok.script", _CLEAN)
    bad = _write(tmp_path, "bad.script", _MALFORMED)

    code = cli.main(["parse", "--json", ok, bad])

    captured = capsys.readouterr()
    assert code == 1
    reports = json.loads(captured.out)
    assert isinstance(reports, list)
    assert [r["file"] for r in reports] == [ok, bad]
    assert reports[0]["ok"] is True
    assert reports[1]["ok"] is False


# --- stdin ------------------------------------------------------------------------------------


def test_stdin_clean(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(_CLEAN))

    code = cli.main(["parse", "-"])

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.startswith("(source_file")


def test_stdin_malformed_diagnostic_uses_stdin_name(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(_MALFORMED))

    code = cli.main(["parse", "--quiet", "-"])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.err.startswith("<stdin>:")


# --- hidden MISSING terminator (D7/D8 regression) ---------------------------------------------


def test_hidden_missing_terminator_file_exits_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A file whose statements are separated only by lone CRs parses to a tree tree-sitter flags as
    # erroneous (a MISSING hidden terminator). The CLI must treat that as a syntax error — exit 1,
    # ok:false, a diagnostic — not silently exit 0.
    path = _write(tmp_path, "cr.script", "x = 1\ry = 2\r")

    code = cli.main(["parse", "--json", path])

    captured = capsys.readouterr()
    assert code == 1
    report = json.loads(captured.out)
    assert report["ok"] is False
    assert report["errors"]
    assert report["errors"][0]["type"] == "MISSING"


# --- IO errors --------------------------------------------------------------------------------


def test_missing_file_exits_two(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = str(tmp_path / "nope.script")

    code = cli.main(["parse", missing])

    captured = capsys.readouterr()
    assert code == 2
    assert missing in captured.err


def test_io_error_takes_precedence_and_other_files_still_parse(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ok = _write(tmp_path, "ok.script", _CLEAN)
    missing = str(tmp_path / "nope.script")

    code = cli.main(["parse", ok, missing])

    captured = capsys.readouterr()
    assert code == 2  # the IO error (2) outranks a clean parse (0) and a syntax error (1)
    assert "(source_file" in captured.out  # the readable file was still parsed and printed
    assert missing in captured.err


# --- ASCII-safe stdout (DoD guard) ------------------------------------------------------------


def test_default_stdout_is_ascii_on_non_ascii_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path, "unicode.script", _NON_ASCII)

    code = cli.main(["parse", path])

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out
    assert captured.out.isascii()


def test_json_stdout_is_ascii_on_non_ascii_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path, "unicode.script", _NON_ASCII)

    cli.main(["parse", "--json", path])

    captured = capsys.readouterr()
    assert captured.out.isascii()


# --- argparse plumbing ------------------------------------------------------------------------


def test_parse_help_exits_zero() -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["parse", "--help"])
    assert exc.value.code == 0


def test_no_command_errors() -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    assert exc.value.code == 2
