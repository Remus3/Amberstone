"""RM-1414 - three ruff style rules are held at a shrinking baseline.

None of these is selected by ruff.toml. Measured 2026-11-05 with
``ruff check --isolated`` over the tree, 69 sites in 55 files. This slice
fixed 14 sites in 12 production modules; the rest sit in ``_BASELINE`` below
and the set only shrinks.

- PIE810 (``s.startswith(a) or s.startswith(b)``): one ``startswith`` call with
  a tuple. Same truth table, one scan of the prefix list.
- C416 (``{k: v for k, v in pairs}`` / ``[x for x in it]``): ``dict(pairs)`` /
  ``list(it)``. Same result, no per-item bytecode.
- SIM118 (``key in d.keys()``): ``key in d``.

One site is deliberately NOT rewritten: ``core/resolved_wr.py`` reads column
names off a ``sqlite3.Row``, where ``key in row`` tests the VALUES and
``row.keys()`` is the only correct spelling. It binds ``names = row.keys()``
first, which is both correct and quiet.

Out of this slice on purpose (not edited by it): ``ops/rc_supervisor.py``
(frozen), ``tools/build_portable.py`` and ``tests/test_launcher_*`` (packaging
paths the main session owns), and ``lib/http/client.py`` /
``scripts/fetch_cdragon_pbe.py`` / ``agents/daemon_slayer/tests/
test_no_cwd_relative_paths.py`` (changed by another lane branch awaiting
landing). Everything in the baseline is test code, a docs scratch script or a
tool.

The ratchet runs ruff with NO config (``--isolated``) so a per-file-ignore cannot
hide a finding, and keeps only tracked files. A new finding anywhere, or a
baseline file that offends more than it did, fails; a baseline entry that has
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

_RULES = "PIE810,C416,SIM118"
_FIXED = (
    "agents/daemon_slayer/abilities.py",
    "coach_integration/_coach.py",
    "core/data_retention.py",
    "core/pro_match_index.py",
    "core/resolved_wr.py",
    "core/rofl_stats_backfill.py",
    "core/vision_template_match.py",
    "dashboard/routes_static.py",
    "item_advisor.py",
    "lib/icons/downloader.py",
    "performance_tracker.py",
    "tft/tft_live_analysis.py",
)
# file -> number of findings still there. Only shrinks.
_BASELINE = {
    "agents/daemon_slayer/tests/test_cast_propensity_prior_rm98.py": 1,
    "agents/daemon_slayer/tests/test_cc_conditional_wave10.py": 1,
    "agents/daemon_slayer/tests/test_cc_conditional_wave22.py": 1,
    "agents/daemon_slayer/tests/test_effects_expansion.py": 1,
    "agents/daemon_slayer/tests/test_engine_math_correctness_pipeline_c.py": 1,
    "agents/daemon_slayer/tests/test_gold_efficiency_p1l13.py": 1,
    "agents/daemon_slayer/tests/test_kit_axis_ap_scaling_guard.py": 1,
    "agents/daemon_slayer/tests/test_meraki_ingest_p1l7.py": 1,
    "docs/_rescore/tally.py": 1,
    "docs/_rsc_score/calibrate.py": 1,
    "docs/_rsc_score/calibrate_rep.py": 1,
    "lib/http/client.py": 2,
    "ops/rc_supervisor.py": 1,
    "scripts/fetch_cdragon_pbe.py": 1,
    "tests/snapshot_panels/test_objective_gauges_view.py": 1,
    "tests/test_aram_item_interaction_snapshot_tracked.py": 1,
    "tests/test_champion_loadout_autogen.py": 9,
    "tests/test_ci_docs_guard_coverage.py": 1,
    "tests/test_ci_watchdog.py": 2,
    "tests/test_claude_send_ahk_header_rm725.py": 1,
    "tests/test_data_viz_tier_y07.py": 1,
    "tests/test_inbox_responder_runner.py": 1,
    "tests/test_install_bat_embedded_pins_rm764.py": 1,
    "tests/test_install_bat_key_stage_rm779.py": 1,
    "tests/test_launcher_first_run.py": 1,
    "tests/test_launcher_key_read_rm810.py": 1,
    "tests/test_p2w4_hw2_h.py": 1,
    "tests/test_repo_walk.py": 2,
    "tests/test_routes_metrics_riot_cache.py": 1,
    "tests/test_run_deploy_test_continuations_rm826.py": 1,
    "tests/test_skip_condition_hygiene.py": 1,
    "tests/test_tft_cv_accuracy_harness.py": 1,
    "tools/build_portable.py": 1,
    "tools/sibling_name_sweep.py": 2,
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
    # The whole tree on one command line is too long for Windows: lint ".", keep
    # the tracked files (the filter the other ruff ratchets use).
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    counts: collections.Counter = collections.Counter()
    for d in _ruff(["--select", _RULES, "."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked:
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


@pytest.mark.parametrize(
    "code, expected",
    [
        ("s = 'ab'\nv = s.startswith('a') or s.startswith('b')\n", "PIE810"),
        ("pairs = [(1, 2)]\nd = {k: v for k, v in pairs}\n", "C416"),
        ("d = {}\nv = 1 in d.keys()\n", "SIM118"),
    ],
)
def test_each_probe_is_live(code, expected):
    """Every rule in the set IS reported by the isolated run on a minimal
    offender - so an empty tree result is a clean tree, not a dead probe."""
    found = _ruff(["--select", _RULES, "--stdin-filename", "probe_mod.py", "-"], stdin=code)
    assert expected in {d["code"] for d in found}, found


def test_sqlite_row_membership_tests_values_not_columns():
    """Why core/resolved_wr.py keeps .keys(): on a sqlite3.Row `in` looks at
    the values, so the SIM118 rewrite would be a silent behaviour change."""
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT 5 AS wins").fetchone()
    names = row.keys()
    assert "wins" in names
    assert "wins" not in row
    assert 5 in row


def test_resolved_wr_get_reads_a_column_by_name():
    import sqlite3

    from core import resolved_wr

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT 5 AS wins").fetchone()
    assert resolved_wr._get(row, "wins") == 5
    assert resolved_wr._get(row, "losses") is None
    assert resolved_wr._get({"wins": 2}, "wins") == 2
