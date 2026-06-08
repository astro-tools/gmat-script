"""The shipped ``.pre-commit-hooks.yaml`` — its contract, and an end-to-end run through pre-commit.

Two layers:

* **static** — the hook metadata declares what consumers rely on (ids, the ``gmat-script format``
  entry, the ``--check`` variant, the ``.script`` / ``.gmf`` targeting).
* **end-to-end** — a throwaway git "sample repo" whose ``.pre-commit-config.yaml`` runs the
  *shipped* hook entry/args/file-filter as a local ``system`` hook (so no per-cell wheel rebuild or
  network is needed), asserting the in-place hook reformats-then-passes and the check hook fails
  dirty / passes clean. Skipped when ``pre-commit`` or the ``gmat-script`` console script is absent.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import yaml

from gmat_script import format

if TYPE_CHECKING:
    from collections.abc import Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
_HOOKS_FILE = _REPO_ROOT / ".pre-commit-hooks.yaml"

# A valid but non-canonical script (redundant GMAT prefix + trailing ;) and its canonical form.
_DIRTY = "Create Spacecraft Sat\nGMAT Sat.SMA = 7000;\n"
_CANONICAL = format(_DIRTY)


def _load_hooks() -> list[dict[str, Any]]:
    hooks: list[dict[str, Any]] = yaml.safe_load(_HOOKS_FILE.read_text(encoding="utf-8"))
    return hooks


# =============================================================================================
# static contract
# =============================================================================================


def test_hooks_file_is_ascii() -> None:
    # Hook metadata feeds tooling on every platform; keep it ASCII.
    assert _HOOKS_FILE.read_text(encoding="utf-8").isascii()


def test_declares_both_hooks() -> None:
    hooks = _load_hooks()
    assert {hook["id"] for hook in hooks} == {"gmat-script-format", "gmat-script-format-check"}


@pytest.mark.parametrize("hook", _load_hooks(), ids=lambda hook: str(hook["id"]))
def test_hook_contract(hook: dict[str, Any]) -> None:
    assert hook["language"] == "python"  # installs this package; no GMAT / C / Node toolchain
    assert hook["entry"] == "gmat-script format"
    # Targets GMAT scripts and GmatFunctions, nothing else.
    assert hook["files"] == r"\.(script|gmf)$"
    is_check = hook["id"] == "gmat-script-format-check"
    assert hook.get("args", []) == (["--check"] if is_check else [])


# =============================================================================================
# end-to-end through pre-commit
# =============================================================================================


def _pre_commit_cmd() -> list[str] | None:
    exe = shutil.which("pre-commit")
    if exe is not None:
        return [exe]
    if find_spec("pre_commit") is not None:
        return [sys.executable, "-m", "pre_commit"]
    return None


_PRE_COMMIT = _pre_commit_cmd()
_GMAT_SCRIPT = shutil.which("gmat-script")
_GIT = shutil.which("git")

requires_pre_commit = pytest.mark.skipif(
    _PRE_COMMIT is None or _GMAT_SCRIPT is None or _GIT is None,
    reason="end-to-end run needs pre-commit, the installed gmat-script console script, and git",
)


def _local_config() -> str:
    """A ``.pre-commit-config.yaml`` running the *shipped* hooks as local ``system`` hooks.

    The entry, args, and file filter are taken verbatim from ``.pre-commit-hooks.yaml`` — only the
    language is swapped to ``system`` so pre-commit invokes the already-installed ``gmat-script`` on
    PATH instead of building an isolated environment. The shipped entry/args/files contract is thus
    what actually runs.
    """
    hooks = []
    for shipped in _load_hooks():
        hook: dict[str, Any] = {
            "id": shipped["id"],
            "name": shipped["name"],
            "entry": shipped["entry"],
            "language": "system",
            "files": shipped["files"],
            "types": list(shipped.get("types", ["file"])),
            "pass_filenames": True,
        }
        if shipped.get("args"):
            hook["args"] = list(shipped["args"])
        hooks.append(hook)
    return yaml.safe_dump({"repos": [{"repo": "local", "hooks": hooks}]}, sort_keys=False)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    """A throwaway git repo carrying the shipped hooks as a local pre-commit config."""
    repo = tmp_path / "sample"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / ".pre-commit-config.yaml").write_text(_local_config(), encoding="utf-8")
    return repo


def _run_hook(repo: Path, hook_id: str, target: str) -> subprocess.CompletedProcess[str]:
    assert _PRE_COMMIT is not None  # guarded by requires_pre_commit
    _git(repo, "add", "-A")
    env = {**os.environ, "PRE_COMMIT_HOME": str(repo / ".pre-commit-cache")}
    cmd: Sequence[str] = [*_PRE_COMMIT, "run", hook_id, "--files", str(repo / target)]
    return subprocess.run(cmd, cwd=repo, env=env, capture_output=True, text=True, timeout=180)


@requires_pre_commit
def test_format_hook_reformats_then_passes(sample_repo: Path) -> None:
    target = sample_repo / "mission.script"
    target.write_text(_DIRTY, encoding="utf-8", newline="")

    first = _run_hook(sample_repo, "gmat-script-format", "mission.script")

    # The hook rewrote the file in place, so pre-commit reports the modification and fails.
    assert first.returncode != 0, first.stdout + first.stderr
    assert target.read_text(encoding="utf-8") == _CANONICAL

    second = _run_hook(sample_repo, "gmat-script-format", "mission.script")

    # Nothing left to change — a second pass is clean.
    assert second.returncode == 0, second.stdout + second.stderr


@requires_pre_commit
def test_format_check_hook_fails_dirty_passes_clean(sample_repo: Path) -> None:
    target = sample_repo / "mission.script"

    target.write_text(_DIRTY, encoding="utf-8", newline="")
    dirty = _run_hook(sample_repo, "gmat-script-format-check", "mission.script")
    assert dirty.returncode != 0, dirty.stdout + dirty.stderr
    assert target.read_text(encoding="utf-8") == _DIRTY  # --check never writes

    target.write_text(_CANONICAL, encoding="utf-8", newline="")
    clean = _run_hook(sample_repo, "gmat-script-format-check", "mission.script")
    assert clean.returncode == 0, clean.stdout + clean.stderr
