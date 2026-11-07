"""S144-P-340 - ruff DTZ001 / DTZ005 / DTZ006 / DTZ007 / DTZ011 (naive datetimes) held in production code.

ruff.toml selects the DTZ family nowhere and no earlier ratchet covers it. Measured 2026-11-07 with
``ruff check --isolated`` (target py39): production code carries 78 naive-datetime findings in 44 files
(40 ``datetime.now()``, 13 ``datetime.fromtimestamp(ts)``, 12 ``date.today()``, 9 ``strptime`` with no ``%z``,
4 ``datetime(...)`` with no tzinfo). Everything else in the tree already passes a tz (``datetime.now(timezone.utc)``
is the dominant spelling), so these are the remaining reads of the machine's LOCAL wall clock. A spot check of
seven sites (``tft/sources/tft_log.py``, ``tft/tft_placement.py``, ``tft/placement_aggregator.py``,
``core/match_db.py``, ``coach_integration/_coach.py``, ``dashboard/routes_last_match.py``) found local day labels,
log timestamps and calendar-date validation, not an aware / naive comparison. The other rows are NOT individually
proven safe: each is a baseline row, not a verdict.

The failure the guard keeps new code out of: a naive value compared with, subtracted from or sorted against an
aware one raises TypeError, and a naive value serialised and read back on another host or after a DST change
means a different instant. A new site passes a tz (``datetime.now(timezone.utc)``, ``.astimezone()``) or, when the
local clock is the point, joins the baseline below in the same change with the reason in its commit message.

A baseline row that stops offending (or offends less) fails ``test_baseline_is_exact`` until it shrinks or goes;
a finding beyond a row, or in an unlisted file, fails ``test_no_new_findings``. ``tools/build_portable.py`` is a
row but owned by the packaging work: its row drops when that file passes a tz.

Scope: tracked ``.py`` files. ``tests/``, any ``*/tests/`` directory, ``agents/daemon_slayer``, the vendored
``ops/fleet_kit`` and the ``agents/agent3_testing/suite`` suite are out of scope. The run uses NO config
(``--isolated``) so a per-file-ignore cannot hide a finding.
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

_RULES = "DTZ001,DTZ005,DTZ006,DTZ007,DTZ011"
_OUT_OF_SCOPE = (
    "tests/",
    "tools/tests/",
    "agents/daemon_slayer/",
    "agents/agent3_testing/suite/",
    "ops/fleet_kit/",
)
# file -> finding count that stays (reason in the module docstring). Only shrinks.
_BASELINE = {
    "coach_integration/_coach.py": 1,
    "core/cost_tracker.py": 1,
    "core/log_setup.py": 2,
    "core/match_db.py": 1,
    "dashboard/builders.py": 3,
    "dashboard/builders_home.py": 5,
    "dashboard/routes_last_match.py": 2,
    "lib/wiki_consent.py": 1,
    "mission_control.py": 1,
    "ops/audit/p0_inventory.py": 1,
    "ops/loop/inbox_tick.py": 2,
    "ops/loop/lane_run_ledger.py": 1,
    "ops/migrate/e_move_helpers.py": 1,
    "ops/rc_transactional_deploy.py": 1,
    "performance_tracker.py": 5,
    "scripts/build_spell_cast_rates.py": 1,
    "scripts/champion_drift_alerts.py": 3,
    "scripts/db_size_monitor.py": 1,
    "scripts/repair_tft_match_rows.py": 4,
    "tft/placement_aggregator.py": 1,
    "tft/sources/tft_log.py": 1,
    "tft/tft_placement.py": 1,
    "tools/backfill_home_items_from_rewind.py": 1,
    "tools/backfill_match_ingest_misattribution.py": 4,
    "tools/build_portable.py": 1,
    "tools/cost_health_watchdog.py": 2,
    "tools/gated_g236_loadout_push.py": 3,
    "tools/gated_g312_aram_debounce_lag.py": 2,
    "tools/gated_g419_cache_freeze.py": 1,
    "tools/gated_g423_base_capture.py": 1,
    "tools/gated_g506_debounce_lag.py": 5,
    "tools/gated_rm881_duo_lobby.py": 1,
    "tools/gated_tft_live_keys.py": 1,
    "tools/gated_y01_chain_report.py": 1,
    "tools/inbox_responder_runner.py": 4,
    "tools/package_portable.py": 1,
    "tools/rc_facts.py": 2,
    "tools/recover_match_via_match_v5.py": 1,
    "tools/regen_ranged_marksman_builds_item213.py": 1,
    "tools/repin_subagent_cli.py": 1,
    "tools/repo_insights.py": 2,
    "tools/rofl_dedupe.py": 1,
    "tools/start_daemon_slayer.py": 1,
    "tools/start_ds_matchdb_mcp.py": 1,
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
    for d in _ruff(["--select", _RULES, "."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and not rel.startswith(_OUT_OF_SCOPE) and "/tests/" not in rel:
            counts[rel] += 1
    return dict(counts)


def test_no_new_findings(tree_counts):
    extra = {f: n for f, n in tree_counts.items() if n > _BASELINE.get(f, 0)}
    assert not extra, f"naive-datetime findings beyond the baseline, file: count: {extra}"


def test_baseline_is_exact(tree_counts):
    """A baseline row that no longer offends (or offends less) must shrink or go."""
    stale = {f: n for f, n in _BASELINE.items() if tree_counts.get(f, 0) != n}
    assert not stale, f"baseline rows to shrink or drop (file: recorded): {stale}"


def test_scan_is_not_empty(tree_counts):
    """An empty enumeration would pass both checks above; the measured total anchors the scan."""
    assert sum(tree_counts.values()) == sum(_BASELINE.values()) > 50


@pytest.mark.parametrize(
    ("code", "probe"),
    [
        ("DTZ005", "import datetime\nx = datetime.datetime.now()\n"),
        ("DTZ006", "import datetime\nx = datetime.datetime.fromtimestamp(1)\n"),
        ("DTZ011", "import datetime\nx = datetime.date.today()\n"),
        ("DTZ007", 'import datetime\nx = datetime.datetime.strptime("2026", "%Y")\n'),
        ("DTZ001", "import datetime\nx = datetime.datetime(2026, 1, 1)\n"),
    ],
)
def test_probe_is_live(code, probe):
    """The isolated run reports a minimal offender per rule, so an empty tree result is a real scan."""
    found = _ruff(["--select", _RULES, "--stdin-filename", "probe_mod.py", "-"], stdin=probe)
    assert code in {d["code"] for d in found}


def test_aware_spelling_is_clean():
    """The spelling a new site should use passes, so the guard cannot be satisfied only by a baseline row."""
    probe = "import datetime\nx = datetime.datetime.now(datetime.timezone.utc)\n"
    assert not _ruff(["--select", _RULES, "--stdin-filename", "probe_mod.py", "-"], stdin=probe)
