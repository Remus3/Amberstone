"""RM-1683 - ruff SIM300 (a Yoda condition: the constant-looking operand on the left) is held at zero in the test code.

SIM300 is not selected by ruff.toml. Measured 2026-11-05 with ``ruff check --isolated --line-length 120``
(target py39): 95 findings in 72 modules under ``tests/``, ``agents/daemon_slayer/tests/`` and
``tools/tests/``. 91 findings in 69 modules were swapped by ruff's own fix; the 4 findings in
``tests/test_launcher_service_host.py``, ``tests/test_launcher_updater.py`` and
``tests/test_run_packaged_smoke_launcher_pkg6.py`` are modules the main session owns this session (the
``tests/test_launcher_*`` and ``tests/test_run_packaged_smoke_*`` exclusions) and were left alone, so those three
files are the whole of ``_BASELINE`` below. The baseline only shrinks: a new finding fails, and an entry that stops
offending fails ``test_baseline_is_exact`` until it is dropped.

Equivalence: the fix swaps the two operands of ``==`` / ``!=`` / ``<`` / ``<=`` / ``>`` / ``>=`` and mirrors the
ordering operator, which is exact for every type whose comparison is symmetric (ints, strs, sets, tuples, paths,
dicts, frozensets). The one asymmetric operand the swapped lines hold is ``pytest.approx``, whose comparison is
reflected by Python, so ``approx(x) == y`` and ``y == approx(x)`` agree; ``test_approx_is_symmetric`` measures it.
The run uses NO config (``--isolated``) so a per-file-ignore cannot hide a finding.
"""
from __future__ import annotations

import collections
import importlib.util
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

_RULES = ("SIM300",)
_TEST_DIRS = ("tests/", "agents/daemon_slayer/tests/", "tools/tests/")
# Modules the main session owns this session (lane exclusions tests/test_launcher_*, tests/test_run_packaged_smoke_*).
_BASELINE = {
    "tests/test_launcher_service_host.py",
    "tests/test_launcher_updater.py",
    "tests/test_run_packaged_smoke_launcher_pkg6.py",
}


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--line-length", "120", "--no-fix", "--no-cache", "--output-format", "json",
         "--select", ",".join(_RULES), *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def tree_counts() -> dict[str, int]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    assert any(rel.startswith(_TEST_DIRS) for rel in tracked), "no tracked test module was seen"
    counts: collections.Counter = collections.Counter()
    for d in _ruff(["."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and rel.startswith(_TEST_DIRS):
            counts[rel] += 1
    return dict(counts)


def test_no_new_sim300_finding_in_the_test_code(tree_counts):
    new = {rel: n for rel, n in tree_counts.items() if rel not in _BASELINE}
    assert not new, f"ruff {_RULES} findings in the test code, file: count: {new}"


def test_baseline_is_exact(tree_counts):
    """Every baseline entry still offends; one that no longer does must be dropped (the set only shrinks)."""
    assert not _BASELINE - set(tree_counts), sorted(_BASELINE - set(tree_counts))


def test_approx_is_symmetric():
    """The one asymmetric comparison operand among the swapped lines is pytest.approx; Python reflects it."""
    value = 2.0 / 0.03
    assert pytest.approx(value) == value
    assert value == pytest.approx(value)
    assert pytest.approx(1.0) != 2.0
    other = 2.0
    assert (other == pytest.approx(1.0)) is False
    assert (pytest.approx(1.0) == other) is False


def test_probe_is_live():
    """The rule reports its pattern and stays quiet on the sound spelling, so an empty result is a real scan."""
    bad = "LIMIT = 3\nvalue = 4\nassert LIMIT == value\n"
    good = "LIMIT = 3\nvalue = 4\nassert value == LIMIT\n"
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=bad)
    assert {d["code"] for d in found} == set(_RULES), found
    assert _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=good) == []
