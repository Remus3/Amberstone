"""RM-165: the cost watchdog must read DAY-LEDGERS only, not sidecars.

`data/spend/` is not a directory of day-files. `core/cost_tracker.py` also
parks two per-match sidecars there. They are written at :461-462 off
`self._spend_dir`:

    self._spend_dir / "_match_open.json"     (by_purpose snapshot @ boundary)
    self._spend_dir / "recent_matches.json"  (rolling per-match cost, pruned)

The module-level `_MATCH_OPEN_PATH` / `_RECENT_MATCHES_PATH` constants at
:160-161 are NOT the write sites - they are referenced nowhere in `core/`
(`recent_matches.json` is read back at :514, again off `self._spend_dir`).

`tools/cost_health_watchdog.py` globbed `*.json` over that directory, so both
sidecars were read as if they were day-ledgers. `_match_open.json` carries a
`by_purpose` block, so it passes every shape check the watchdog applies, and
`_` (0x5F) sorts AFTER every digit, so a sidecar lands at the END of the
sorted list and is guaranteed to survive the `prior[-7:]` trailing window -
displacing a genuine day out of the baseline.

Both the daily-total baseline (`spend_baseline`) and the per-lane
cost-per-call baseline (`lane_cost_signals`) are affected. The fix is a
POSITIVE filename filter (a real ISO calendar date + `.json`), not a
blacklist and not a sort change: a future sidecar under any new name must be
excluded too.
"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "chw_rm165",
    str(Path(__file__).parent.parent / "tools" / "cost_health_watchdog.py"),
)
chw = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(chw)

TODAY = "2026-05-09"

# A plausible non-empty sidecar body. `_match_open.json` really is a
# by_purpose snapshot (core/cost_tracker.py:461 writes it), so it survives
# every shape check the watchdog does.
SIDECAR_BY_PURPOSE = {
    "vision_relay": {"usd": 4.0, "calls": 40},
    "aram_coach": {"usd": 1.0, "calls": 50},
}


def _write(p: Path, total_usd, by_purpose=None):
    p.write_text(json.dumps({
        "total_usd": total_usd,
        "by_purpose": by_purpose or {},
    }), encoding="utf-8")


def _populated_dir() -> Path:
    """8 genuine prior days (2026-05-01..08, total_usd 1.0..8.0), today, and
    a fat `_match_open.json` sidecar.

    Trailing window is 7, so exactly one prior day is displaced when the
    sidecar is counted. Genuine last 7 = days 02..08 -> totals 2..8 ->
    median 5.0. With the sidecar counted the window becomes days 03..08 plus
    the sidecar -> [3,4,5,6,7,8,100] -> median 6.0.
    """
    d = Path(tempfile.mkdtemp(prefix="rm165_"))
    for i in range(1, 9):
        _write(d / ("2026-05-0" + str(i) + ".json"), float(i),
               {"vision_relay": {"usd": 0.1 * i, "calls": 100}})
    _write(d / (TODAY + ".json"), 9.0,
           {"vision_relay": {"usd": 1.0, "calls": 100}})
    _write(d / "_match_open.json", 100.0, SIDECAR_BY_PURPOSE)
    return d


class DayLedgerFilterTests(unittest.TestCase):
    """The filename filter itself: positive match on a real ISO date."""

    def test_sidecars_excluded_and_displaced_day_retained(self):
        d = _populated_dir()
        (d / "recent_matches.json").write_text('{"matches": []}',
                                               encoding="utf-8")
        names = sorted(p.name for p in chw.iter_day_ledgers(d))
        self.assertNotIn("_match_open.json", names)
        self.assertNotIn("recent_matches.json", names)
        # the day the sidecar was pushing out of prior[-7:]
        self.assertIn("2026-05-02.json", names)
        self.assertEqual(len(names), 9)     # 8 prior + today

    def test_positive_match_rejects_unknown_sidecar_shapes(self):
        d = Path(tempfile.mkdtemp(prefix="rm165_neg_"))
        _write(d / "2026-05-01.json", 1.0)
        for bad in ("_match_open.json", "recent_matches.json",
                    "budget_snapshot.json", "2026-05-01.bak.json",
                    "2026-13-45.json", "2026-02-30.json", "2026-5-1.json",
                    "20260501.json"):
            _write(d / bad, 1.0, SIDECAR_BY_PURPOSE)
        names = sorted(p.name for p in chw.iter_day_ledgers(d))
        self.assertEqual(names, ["2026-05-01.json"])

    def test_uppercase_suffix_is_rejected(self):
        """Pins the exact-`.json` clause.

        `Path.glob("*.json")` is case-INSENSITIVE on this Windows/CPython -
        measured: it returns a file named `2026-05-01.JSON`. So the suffix
        has to be re-checked case-SENSITIVELY or a `.JSON` foreign file is
        admitted. Distinct dates because NTFS is case-insensitive and the two
        names would otherwise collide.
        """
        d = Path(tempfile.mkdtemp(prefix="rm165_case_"))
        _write(d / "2026-05-01.JSON", 1.0, SIDECAR_BY_PURPOSE)
        _write(d / "2026-05-02.json", 1.0)
        self.assertIn("2026-05-01.JSON",
                      [p.name for p in d.glob("*.json")],
                      "precondition: glob is expected to be case-insensitive "
                      "here; if this fails the clause below is untestable")
        names = sorted(p.name for p in chw.iter_day_ledgers(d))
        self.assertEqual(names, ["2026-05-02.json"])

    def test_iso_week_date_is_rejected(self):
        """Pins the YYYY-MM-DD regex clause.

        `date.fromisoformat` is broader than YYYY-MM-DD on 3.11+: measured on
        3.14.4, `fromisoformat("2026-W01-1")` returns 2025-12-29. That stem is
        also exactly 10 chars, so a length check does NOT exclude it - only an
        explicit YYYY-MM-DD match does. `cost_tracker._today_str()` only ever
        emits `date.today().isoformat()`, so a week-date file is foreign.
        """
        d = Path(tempfile.mkdtemp(prefix="rm165_week_"))
        _write(d / "2026-W01-1.json", 1.0, SIDECAR_BY_PURPOSE)
        _write(d / "2026-05-02.json", 1.0)
        from datetime import date as _date
        self.assertEqual(_date.fromisoformat("2026-W01-1"),
                         _date(2025, 12, 29),
                         "precondition: this Python accepts the ISO week "
                         "date; if not, the clause below is untestable")
        names = sorted(p.name for p in chw.iter_day_ledgers(d))
        self.assertEqual(names, ["2026-05-02.json"])

    def test_calendar_validity_is_enforced(self):
        """Pins the `date.fromisoformat` clause: the regex alone cannot judge
        whether YYYY-MM-DD names a real day."""
        d = Path(tempfile.mkdtemp(prefix="rm165_cal_"))
        _write(d / "2026-02-30.json", 1.0, SIDECAR_BY_PURPOSE)
        _write(d / "2026-13-45.json", 1.0, SIDECAR_BY_PURPOSE)
        _write(d / "2026-05-02.json", 1.0)
        names = sorted(p.name for p in chw.iter_day_ledgers(d))
        self.assertEqual(names, ["2026-05-02.json"])

    def test_directory_named_like_a_day_ledger_is_rejected(self):
        """Pins the `is_file()` clause: `glob("*.json")` matches DIRECTORIES
        too (measured). The sibling reader `tests/conftest.py:264` checks
        `is_file()`; this one now does as well."""
        d = Path(tempfile.mkdtemp(prefix="rm165_dir_"))
        (d / "2026-05-01.json").mkdir()
        _write(d / "2026-05-02.json", 1.0)
        self.assertIn("2026-05-01.json",
                      [p.name for p in d.glob("*.json")],
                      "precondition: glob is expected to match the directory")
        names = sorted(p.name for p in chw.iter_day_ledgers(d))
        self.assertEqual(names, ["2026-05-02.json"])


class SpendBaselineExcludesSidecarTests(unittest.TestCase):

    def test_sidecar_does_not_displace_a_genuine_day(self):
        res = chw.spend_baseline(_populated_dir(), TODAY)
        self.assertEqual(res["samples"], 7)
        # 5.0 = median of the 7 genuine trailing days (2..8).
        # 6.0 is the buggy value: the sidecar displaced day 02.
        self.assertEqual(res["baseline_usd"], 5.0)

    def test_sidecar_total_never_reaches_the_baseline(self):
        d = Path(tempfile.mkdtemp(prefix="rm165_one_"))
        _write(d / "2026-05-08.json", 2.0)
        _write(d / (TODAY + ".json"), 2.0)
        _write(d / "_match_open.json", 1000.0, SIDECAR_BY_PURPOSE)
        res = chw.spend_baseline(d, TODAY)
        self.assertEqual(res["samples"], 1)
        self.assertEqual(res["baseline_usd"], 2.0)
        self.assertFalse(res["breach"])


class LaneCostExcludesSidecarTests(unittest.TestCase):

    def test_sidecar_lane_means_stay_out_of_the_lane_baseline(self):
        d = Path(tempfile.mkdtemp(prefix="rm165_lane_"))
        # one genuine prior day: vision_relay at 0.01 usd/call
        _write(d / "2026-05-08.json", 1.0,
               {"vision_relay": {"usd": 1.0, "calls": 100}})
        # today: 0.02 usd/call == 2x the genuine baseline -> MUST flag
        _write(d / (TODAY + ".json"), 2.0,
               {"vision_relay": {"usd": 2.0, "calls": 100}})
        # sidecar: 0.1 usd/call. If counted, the lane baseline becomes the
        # median of [0.01, 0.1] = 0.055 and today's 0.02 stops being a
        # doubling - the escalation signal is silently suppressed.
        _write(d / "_match_open.json", 100.0,
               {"vision_relay": {"usd": 4.0, "calls": 40}})
        res = chw.lane_cost_signals(d, TODAY)
        self.assertEqual(res["lanes"]["vision_relay"]["samples"], 1)
        self.assertAlmostEqual(
            res["lanes"]["vision_relay"]["baseline_cost_per_call"], 0.01)
        self.assertTrue(res["p95_doubled"])
        self.assertEqual(res["flagged_lanes"], ["vision_relay"])

    def test_sidecar_only_lane_is_not_invented(self):
        """CHARACTERIZATION, not regression - this one passes against the
        UNFIXED module too. A lane that appears only in a sidecar is never in
        `today_means`, so it could not reach `lanes` even before the fix.
        Kept to pin that behaviour, but it is NOT evidence for RM-165."""
        d = Path(tempfile.mkdtemp(prefix="rm165_ghost_"))
        _write(d / "2026-05-08.json", 1.0,
               {"vision_relay": {"usd": 1.0, "calls": 100}})
        _write(d / (TODAY + ".json"), 1.0,
               {"vision_relay": {"usd": 1.0, "calls": 100}})
        _write(d / "_match_open.json", 5.0,
               {"ghost_lane": {"usd": 5.0, "calls": 10}})
        res = chw.lane_cost_signals(d, TODAY)
        self.assertNotIn("ghost_lane", res["lanes"])


if __name__ == "__main__":
    unittest.main()
