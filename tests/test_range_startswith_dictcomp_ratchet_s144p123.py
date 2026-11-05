"""RM-1518 - three redundant-call ruff rules are held at a shrinking baseline.

None of these rules is selected by ruff.toml. Measured 2026-11-05 with
``ruff check --isolated`` over the tree, then this slice fixed the production
sites in 9 modules:

- PIE808 ``range(0, n)``: now ``range(n)``.
- PIE810 ``s.startswith(a) or s.startswith(b)``: now ``s.startswith((a, b))``.
- C416 ``{k: v for k, v in pairs}``: now ``dict(pairs)``.

Scope: production code. ``tests/``, ``agents/daemon_slayer`` (DS lane), the
``agents/agent3_testing/suite`` test suite and ``tools/ds_cross_eval`` are out of
scope; they hold the same idioms by the dozen and are not touched here.

Left in the baseline on purpose, each for a named owner:

- ``core/log_scrub.py`` is changed on the true-audit lane branch and
  ``scripts/fetch_cdragon_pbe.py`` on the queue lane
  branch (``lib/http/client.py`` left the baseline in RM-1527): a later repo cycle takes them once those lanes land.
- ``ops/rc_supervisor.py`` is FROZEN; ``tools/build_portable.py`` is PKG (main
  session). ``tools/sibling_name_sweep.py`` left the baseline in RM-1533.
- ``docs/_rescore`` and ``docs/_rsc_score`` are dated scoring scratch scripts.

The ratchet runs ruff with NO config (``--isolated``) so a per-file-ignore cannot
hide a finding, and keeps only tracked files. A new finding anywhere in scope, or
a baseline file that offends more than it did, fails; a baseline entry that has
stopped offending also fails until it is dropped, so the table only shrinks.
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

_RULES = ("PIE808", "PIE810", "C416")
_OUT_OF_SCOPE = (
    "tests/",
    "agents/daemon_slayer/",
    "agents/agent3_testing/suite/",
    "tools/ds_cross_eval/",
)
_FIXED = (
    "core/op_score_curve.py",
    "core/perf_curve.py",
    "dashboard/routes_spike_curve.py",
    "tools/champion_loadout_collapse_to_paths.py",
    "tools/gated_live_probe.py",
    "tools/inbox_responder_exec.py",
    "tools/p3_ascii_census.py",
    "tools/ci_watchdog.py",
    "tools/run_phase2_perf.py",
    "tools/sibling_name_sweep.py",
    "docs/_rescore/tally.py",  # RM-1544
    "docs/_rsc_score/calibrate.py",
    "docs/_rsc_score/calibrate_rep.py",
)
# file -> number of findings still there. Only shrinks.
_BASELINE = {
    "ops/rc_supervisor.py": 1,
    "tools/build_portable.py": 1,
}


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, **kwargs,
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


def test_no_file_gains_a_finding(tree_counts):
    worse = {f: (n, _BASELINE.get(f, 0)) for f, n in tree_counts.items()
             if n > _BASELINE.get(f, 0)}
    assert not worse, f"ruff {_RULES}, file: (now, baseline): {worse}"


def test_baseline_is_exact_so_it_only_shrinks(tree_counts):
    stale = {f: (tree_counts.get(f, 0), n) for f, n in _BASELINE.items()
             if tree_counts.get(f, 0) != n}
    assert not stale, f"lower or drop these baseline rows, file: (now, baseline): {stale}"


def test_fixed_modules_stay_clean(tree_counts):
    assert not [f for f in _FIXED if f in tree_counts]


@pytest.mark.parametrize("rel", _FIXED)
def test_fixed_module_is_ascii_and_lf(rel):
    raw = (REPO_ROOT / rel).read_bytes()
    raw.decode("ascii")
    assert b"\r" not in raw


@pytest.mark.parametrize("rule, source", [
    ("PIE808", "v = list(range(0, 5))\n"),
    ("PIE810", "s = 'x'\nv = s.startswith('a') or s.startswith('b')\n"),
    ("C416", "p = [(1, 2)]\nv = {k: w for k, w in p}\n"),
])
def test_probe_is_live(rule, source):
    """The isolated run reports a minimal offender per rule, so an empty tree
    result is a clean tree and not a dead probe."""
    found = _ruff(["--select", rule, "--stdin-filename", "probe_mod.py", "-"], stdin=source)
    assert rule in {d["code"] for d in found}, found


@pytest.mark.parametrize("key, want", [
    ("st_foo", True), ("st-foo", True), ("ST_FOO", True), ("xadaptx", True),
    ("stfoo", False), ("foo", False), ("", False),
])
def test_gated_probe_adapt_key_keeps_its_truth_table(key, want):
    from tools import gated_live_probe

    assert gated_live_probe._is_adapt_key(key) is want


@pytest.mark.parametrize("value, flagged", [
    ("/abs", True), ("\\abs", True), ("C:\\x", True), ("a..b", True),
    ("plain-value", False),
])
def test_positional_rule_keeps_flagging_rooted_values(value, flagged):
    from tools import inbox_responder_exec as ire

    got = ire._positional_rule("verb", value)
    assert (got == "executor:positional") is flagged


@pytest.mark.parametrize("rel, want", [
    ("agents/daemon_slayer/engine.py", "ZZ_ds_engine(load-bearing-arrows)"),
    ("agents/daemon_slayer/tests/test_x.py", "ZZ_tests(swept_c16_c17)"),
    ("tests/test_x.py", "ZZ_tests(swept_c16_c17)"),
    ("core/x.py", "core"),
    ("README.md", "ROOT"),
])
def test_census_bucket_keeps_its_table(rel, want):
    from tools import p3_ascii_census

    assert p3_ascii_census.bucket_of(rel) == want


def test_ci_watchdog_dry_run_plan_steps_become_a_dict():
    from tools import ci_watchdog

    plan = ci_watchdog.plan_dispatch("run1", "a" * 40, worktree="wt", repo="r")
    assert plan and all(len(step) == 2 for step in plan)
    # dict() keeps every label and its order only while the labels are unique.
    assert list(dict(plan)) == [label for label, _argv in plan]
