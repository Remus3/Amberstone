"""RM-1543 - ruff RSE102, SIM118 and C416 are held at zero across the tracked tree.

None of the three is in ruff.toml's ``select``, so a finding could land unnoticed.
Measured 2026-11-05 with ``ruff check --isolated --select RSE102,SIM118,C416``
(target py39): 25 findings in 15 test modules, none in production code.

- RSE102: ``raise Cls()`` with an empty call; ``raise Cls`` instantiates it the same way.
- SIM118: ``k in d.keys()`` / ``for k in d.keys()``; iterating a mapping yields its keys.
- C416: an identity comprehension (``[x for x in it]``, ``{k: v for k, v in m.items()}``,
  ``{d for d in it}``) that is ``list(it)`` / ``dict(m)`` / ``set(it)``: same shallow copy.

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

_RULES = "RSE102,SIM118,C416"
# file -> finding count that stays because another owner holds the file. Only shrinks.
_BASELINE: dict[str, int] = {
    "tests/test_launcher_first_run.py": 1,  # blocked: main session owns the launcher tests (PKG)
    "tools/build_portable.py": 1,  # blocked: main session owns tools/build_portable.py (PKG)
}
_FIXED = (
    "tests/test_base_worker_true_audit_s144.py",
    "tests/test_edge_watcher_true_audit_s144.py",
    "tests/test_lcu_agent_auto_accept_pref_sync_rm1222.py",
    "tests/test_routes_loadout_lane8_cycle38.py",
    "tests/test_routes_state_stream_true_audit_s144.py",
    "tests/test_champion_loadout_autogen.py",
    "tests/test_ci_watchdog.py",
    "tests/test_tft_cv_accuracy_harness.py",
    "tests/snapshot_panels/test_objective_gauges_view.py",
    "agents/daemon_slayer/tests/test_cast_propensity_prior_rm98.py",
    "agents/daemon_slayer/tests/test_engine_math_correctness_pipeline_c.py",
    "agents/daemon_slayer/tests/test_kit_axis_ap_scaling_guard.py",
    "agents/daemon_slayer/tests/test_meraki_ingest_p1l7.py",
    "agents/daemon_slayer/tests/test_cc_conditional_wave10.py",
    "agents/daemon_slayer/tests/test_cc_conditional_wave22.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", "--select", _RULES, *args],
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
    for d in _ruff(["."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked:
            counts[rel] += 1
    return dict(counts)


def test_no_new_findings(tree_counts):
    extra = {f: n for f, n in tree_counts.items() if n > _BASELINE.get(f, 0)}
    assert not extra, f"ruff {_RULES} findings beyond the baseline, file: count: {extra}"


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
    """A minimal offender per rule is reported, so an empty tree result is a real scan."""
    probe = (
        "class E(Exception):\n"
        "    pass\n"
        "\n"
        "\n"
        "def f(d, xs):\n"
        "    a = [x for x in xs]\n"
        "    b = 'k' in d.keys()\n"
        "    raise E()\n"
    )
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=probe)
    assert sorted(d["code"] for d in found) == ["C416", "RSE102", "SIM118"]
