"""RM-1523 - ruff FURB105 (``print("")``) is held at zero.

FURB105 is not selected by ruff.toml. Measured 2026-11-05 with ``ruff check --isolated``
over the tree: production code carried 35 ``print("")`` calls in 7 tools/ scripts (the
replay validators, the laning-verdict probe, the 101qq probe and the slice orchestrator),
all blank-line separators in report output. ``print()`` writes the same single newline,
so ruff's fix changes no output byte.

SIM300 (yoda conditions) was measured in the same pass and is NOT fixed: ruff treats an
UPPER-CASE name as a constant, so it flips ``R == mx`` / ``H < size`` (single-letter
image-array variables) and ``_LOCK_OWNER_PID != os.getpid()`` (a module global against
a call), which makes those lines read worse. It stays out of any ratchet.

Scope: production code. ``tests/``, ``agents/daemon_slayer``, the
``agents/agent3_testing/suite`` test suite and ``tools/ds_cross_eval`` are out of scope.
The ratchet runs ruff with NO config (``--isolated``) so a per-file-ignore cannot hide a
finding, and keeps only tracked files. The baseline is empty: any finding fails.
"""
from __future__ import annotations

import collections
import contextlib
import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("ruff") is None,
    reason="ruff is not importable by this interpreter",
)

_RULES = ("FURB105",)
_OUT_OF_SCOPE = (
    "tests/",
    "agents/daemon_slayer/",
    "agents/agent3_testing/suite/",
    "tools/ds_cross_eval/",
)
_FIXED = (
    "tools/laning_verdict_information_probe.py",
    "tools/probe_101qq_hero_rank_double.py",
    "tools/replay_build_order_validate.py",
    "tools/replay_laning_verdict_validate.py",
    "tools/replay_matchup_validate.py",
    "tools/replay_pickban_validate.py",
    "tools/slice_orchestrator.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, check=False, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def tree_counts() -> dict[str, int]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    counts: collections.Counter = collections.Counter()
    for d in _ruff(["--select", ",".join(_RULES), "."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and not rel.startswith(_OUT_OF_SCOPE):
            counts[rel] += 1
    return dict(counts)


def test_tree_has_no_print_empty_string(tree_counts):
    assert not tree_counts, f"ruff {_RULES} findings, file: count: {tree_counts}"


@pytest.mark.parametrize("rel", _FIXED)
def test_fixed_module_is_ascii_and_lf(rel):
    raw = (REPO_ROOT / rel).read_bytes()
    raw.decode("ascii")
    assert b"\r" not in raw


@pytest.mark.parametrize("rel", _FIXED)
def test_fixed_module_stays_clean(rel, tree_counts):
    assert rel not in tree_counts


def test_probe_is_live():
    """The isolated run reports a minimal offender, so an empty tree result is a real scan."""
    found = _ruff(["--select", ",".join(_RULES), "--stdin-filename", "probe_mod.py", "-"],
                  stdin='print("")\n')
    assert {d["code"] for d in found} == {"FURB105"}, found


def test_print_empty_string_and_bare_print_write_the_same_bytes():
    """The premise of the fix: the rewritten separator is byte-identical output."""
    old, new = io.StringIO(), io.StringIO()
    empty = ""
    with contextlib.redirect_stdout(old):
        print(empty)
    with contextlib.redirect_stdout(new):
        print()
    assert old.getvalue() == new.getvalue() == "\n"
