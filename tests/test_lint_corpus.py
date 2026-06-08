"""The linter's precision bar: zero error/warning diagnostics on the clean stock corpus (the DoD).

Every R2026a stock sample (162 ``.script`` + 9 ``.gmf``; see ``gmat-r2026a/PROVENANCE.md``) is
well-formed, so the linter must raise **no** error- or warning-severity diagnostic on it — the
no-false-positive guarantee the rule design and the curated catalogue / allow-lists are tuned to.
Info findings (``unused-resource`` — samples legitimately define resources they never use) are
allowed and not asserted against. ``test_corpus_inventory`` guards against a truncated checkout
collecting zero cases and passing vacuously.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gmat_script.lint import lint
from gmat_script.lint.diagnostics import Severity

_STOCK_DIR = Path(__file__).parent / "data" / "corpus" / "gmat-r2026a"
_EXPECTED_SCRIPTS = 162
_EXPECTED_GMF = 9

_FIXTURES = sorted([*_STOCK_DIR.rglob("*.script"), *_STOCK_DIR.rglob("*.gmf")])
_IDS = [str(p.relative_to(_STOCK_DIR)) for p in _FIXTURES]


def test_corpus_inventory() -> None:
    """The committed stock corpus is present and complete — the truncation guard."""
    scripts = list(_STOCK_DIR.rglob("*.script"))
    gmf = list(_STOCK_DIR.rglob("*.gmf"))
    assert len(scripts) == _EXPECTED_SCRIPTS, f"expected {_EXPECTED_SCRIPTS}, found {len(scripts)}"
    assert len(gmf) == _EXPECTED_GMF, f"expected {_EXPECTED_GMF}, found {len(gmf)}"


@pytest.mark.corpus
@pytest.mark.parametrize("fixture", _FIXTURES, ids=_IDS)
def test_fixture_has_no_error_or_warning_diagnostics(fixture: Path) -> None:
    offending = [
        d
        for d in lint(fixture.read_text(encoding="utf-8"))
        if d.severity in (Severity.ERROR, Severity.WARNING)
    ]
    if offending:
        first = offending[0]
        pytest.fail(
            f"{fixture.name}: {len(offending)} false positive(s); first {first.severity.value} "
            f"{first.rule} at line {first.start.line}: {first.message}"
        )
