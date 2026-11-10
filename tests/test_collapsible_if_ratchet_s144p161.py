"""RM-1678 - ruff SIM102 (nested ``if`` that collapses into one) is held at zero in the test code.

SIM102 is not in ruff.toml's ``select``. Measured 2026-11-05 with
``ruff check --isolated --line-length 120 --select SIM102`` (target py39): 25 findings in 22 test
modules under ``tests/``, ``agents/daemon_slayer/tests/`` and ``tools/tests/``. Ruff autofixed
11; the other 14 sat inside an ``elif`` branch or beyond the autofix's line budget and were
collapsed by hand into one parenthesised condition. Every collapse keeps the same short-circuit
order, so each test still evaluates the same sub-expressions in the same sequence.

Scope is the test directories only: the non-test findings (``ops/rc_supervisor.py`` is frozen, the
rest are production modules) are left to their owners. The run uses NO config (``--isolated``) so a
per-file-ignore cannot hide a finding, with ruff's own 120-column budget set to the project's.
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

_RULE = "SIM102"
_TEST_DIRS = ("tests/", "agents/daemon_slayer/tests/", "tools/tests/")
# file -> finding count that stays because another owner holds the file. Only shrinks.
_BASELINE: dict[str, int] = {}
_FIXED = (
    "agents/daemon_slayer/tests/test_ad_axis_ability_damage_rm39.py",
    "agents/daemon_slayer/tests/test_stranded_hsp_seam_r197.py",
    "tests/test_build_plan_contract.py",
    "tests/test_champ_select_deterministic.py",
    "tests/test_ds_table_generators_lf.py",
    "tests/test_planner_beam_search.py",
    "tests/test_skip_condition_hygiene.py",
    "tests/test_smart_quote_hygiene.py",
    "tests/test_tracked_writer_lf_sweep.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--line-length", "120", "--no-fix", "--no-cache", "--output-format", "json",
         "--select", _RULE, *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, check=False, **kwargs,
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


def test_no_new_findings(tree_counts):
    extra = {f: n for f, n in tree_counts.items() if n > _BASELINE.get(f, 0)}
    assert not extra, f"ruff {_RULE} findings beyond the baseline, file: count: {extra}"


def test_baseline_is_exact(tree_counts):
    stale = {f: n for f, n in _BASELINE.items() if tree_counts.get(f, 0) != n}
    assert not stale, f"baseline rows to shrink or drop (file: recorded): {stale}"


@pytest.mark.parametrize("rel", _FIXED)
def test_fixed_module_is_ascii_and_lf(rel):
    raw = (REPO_ROOT / rel).read_bytes()
    raw.decode("ascii")
    assert b"\r" not in raw


@pytest.mark.parametrize("rel", _FIXED)
def test_fixed_module_stays_clean(rel, tree_counts):
    assert rel not in tree_counts


def test_probe_is_live():
    """A nested if with no else is reported, an if with an else is not, so an empty result is a real scan."""
    probe = (
        "def f(a, b):\n"
        "    if a:\n"
        "        if b:\n"
        "            return 1\n"
        "    return 0\n"
        "\n"
        "\n"
        "def g(a, b):\n"
        "    if a:\n"
        "        if b:\n"
        "            return 1\n"
        "    else:\n"
        "        return 2\n"
        "    return 0\n"
    )
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=probe)
    assert [d["code"] for d in found] == ["SIM102"]
