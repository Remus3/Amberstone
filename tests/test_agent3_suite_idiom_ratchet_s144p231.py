"""RM-1734 - ruff PLR0402, C420 and SIM117 are held at zero in agents/agent3_testing/suite/.

The tests/ ratchets (PLR0402 RM-1682, C420 RM-1681) scope to ``tests/``,
``agents/daemon_slayer/tests/`` and ``tools/tests/``; the agent-3 suite lives
under ``agents/agent3_testing/suite/`` and was in none of them. Measured
2026-11-06 with ``ruff check --isolated --target-version py39 --line-length 120``:
14 findings in 4 modules (11 PLR0402 in test_round42.py, 1 C420 in
test_round23.py, 1 SIM117 each in test_supervisor_stub.py and
test_warm_session.py), all fixed. ``agents/agent3_testing/suite/test_win_reconcile.py``
is not touched here (the true-audit lane branch edits it). No baseline: the
run uses no config, so a per-file-ignore cannot hide a finding.
"""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_RULES = ("PLR0402", "C420", "SIM117")
_DIR = "agents/agent3_testing/suite/"
_FIXED = (
    "agents/agent3_testing/suite/test_round23.py",
    "agents/agent3_testing/suite/test_round42.py",
    "agents/agent3_testing/suite/test_supervisor_stub.py",
    "agents/agent3_testing/suite/test_warm_session.py",
)


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


def _suite_files() -> list[str]:
    return sorted(rel for rel in (relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",)))
                  if rel.startswith(_DIR))


def test_walk_is_not_vacuous():
    files = _suite_files()
    assert set(_FIXED) <= set(files)
    assert len(files) > 10


def test_no_finding_in_the_agent3_suite():
    files = _suite_files()
    counts: dict[str, int] = {}
    for d in _ruff(files):
        rel = relative_posix(Path(d["filename"]).resolve())
        counts[rel] = counts.get(rel, 0) + 1
    assert not counts, f"ruff {_RULES} findings in the agent-3 suite, file: count: {counts}"


@pytest.mark.parametrize("rel", _FIXED)
def test_fixed_module_is_ascii_and_lf(rel):
    raw = (REPO_ROOT / rel).read_bytes()
    raw.decode("ascii")
    assert b"\r" not in raw


def test_the_rewritten_import_binds_the_submodule():
    """`import a.b as b` -> `from a import b` is equivalent only while the package attribute IS the module."""
    module = importlib.import_module("agents.agent4_coach_mentor.ui_applier")
    assert importlib.import_module("agents.agent4_coach_mentor").ui_applier is module
    assert sys.modules["agents.agent4_coach_mentor.ui_applier"] is module


def test_probe_is_live():
    """The rules report their patterns and stay quiet on the sound spellings, so an empty scan is real."""
    bad = ("import os.path as path\n"
           "d = {k: 0 for k in 'ab'}\n"
           "def f(a, b):\n"
           "    with a:\n"
           "        with b:\n"
           "            pass\n")
    good = "from os import path\nd = dict.fromkeys('ab', 0)\n"
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=bad)
    assert {d["code"] for d in found} == set(_RULES), found
    assert _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=good) == []
