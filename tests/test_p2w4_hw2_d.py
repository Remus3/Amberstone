# arch: P2 cycle-15 hw2 slice-D regression tests for scripts data-pipeline + match/rewind | section=tests | frozen=no
"""Regression tests for DEEP_AUDIT_CHARTER P2 cycle 15 half-wave 2 slice D
(scripts/ data-pipeline + match/rewind deep).

NO network, NO live engine, NO real DB mutation: every test feeds the pure
helpers inline values or a throwaway in-memory / tmp sqlite fixture.

FIX-NOW covered here
--------------------
1. data_pipeline.cmd_aram_builds Aggregator B winrate -> tier classification was inline
   inside the fetch loop:
     ``wr = float(entry[3]) * 100 if float(entry[3]) < 1 else float(entry[3])``
   Two faults (FRICTION class #1 non-finite + robustness):
     (a) a NON-FINITE winrate (NaN / inf) silently fell through every
         ``wr >= threshold`` check and got tagged the LOWEST tier "D",
         polluting the curated aram_champion_builds.json with a fabricated
         floor tier instead of being skipped.
     (b) ``float(entry[3])`` on a non-numeric cell raised mid-loop; because
         the loop body sits inside the outer try, ONE malformed Aggregator B row
         aborted tier extraction for EVERY remaining champion.
   Fix: a pure ``_wr_to_tier(raw, thresholds)`` helper that fail-softs to
   ``None`` (= skip this row) on non-numeric / non-finite input, normalizes
   the fraction-vs-percent ambiguity, clamps, and maps to a tier letter. A
   ``None`` return means "skip" - matching the existing blank-name skip.

2. retrofill_match_metrics._find_tracked_pid + the tracked-row pull: covered
   indirectly via a tmp-sqlite fixture proving the SELECT shape is stable
   (regression guard against the column-order assumptions the retrofill makes
   when zipping ``.description`` to ``.fetchone()``).
"""
from __future__ import annotations

import math
import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import scripts.data_pipeline as DP  # noqa: E402


# --------------------------------------------------------------------------- wr -> tier
class TestAramWinrateToTier:
    """``_wr_to_tier`` is the extracted classification helper. It must never
    map a non-finite or non-numeric winrate to a fabricated tier, and must
    treat both fraction (0.54) and percent (54.0) encodings identically."""

    THRESHOLDS = [(55.0, "S"), (53.0, "A"), (51.0, "B"), (49.0, "C")]

    def test_percent_encoding_maps_to_tier(self):
        assert DP._wr_to_tier(56.0, self.THRESHOLDS) == "S"
        assert DP._wr_to_tier(53.4, self.THRESHOLDS) == "A"
        assert DP._wr_to_tier(51.0, self.THRESHOLDS) == "B"
        assert DP._wr_to_tier(49.9, self.THRESHOLDS) == "C"

    def test_fraction_encoding_normalizes_same_as_percent(self):
        # 0.56 fraction must classify identically to 56.0 percent.
        assert DP._wr_to_tier(0.56, self.THRESHOLDS) == DP._wr_to_tier(56.0, self.THRESHOLDS)
        assert DP._wr_to_tier(0.50, self.THRESHOLDS) == "C"

    def test_below_floor_is_explicit_D(self):
        # A real, finite, sub-49% winrate is a legitimate "D".
        assert DP._wr_to_tier(40.0, self.THRESHOLDS) == "D"
        assert DP._wr_to_tier(0.40, self.THRESHOLDS) == "D"

    def test_nan_winrate_skips_not_floor_tier(self):
        # The core FRICTION #1 fix: NaN must NOT silently become "D".
        assert DP._wr_to_tier(float("nan"), self.THRESHOLDS) is None

    def test_inf_winrate_skips(self):
        assert DP._wr_to_tier(float("inf"), self.THRESHOLDS) is None
        assert DP._wr_to_tier(float("-inf"), self.THRESHOLDS) is None

    def test_non_numeric_skips_not_raises(self):
        # A non-numeric Aggregator B cell must skip THIS row only, never raise and
        # abort the whole loop.
        assert DP._wr_to_tier(None, self.THRESHOLDS) is None
        assert DP._wr_to_tier("n/a", self.THRESHOLDS) is None
        assert DP._wr_to_tier([], self.THRESHOLDS) is None

    def test_numeric_string_still_classifies(self):
        # JSON sometimes stringifies numbers; a clean numeric string should
        # still resolve rather than skip.
        assert DP._wr_to_tier("56.0", self.THRESHOLDS) == "S"

    def test_result_is_always_known_tier_or_none(self):
        for raw in (55.0, 54.0, 52.0, 50.0, 48.0, 0.55, float("nan"),
                    float("inf"), None, "x", 0):
            out = DP._wr_to_tier(raw, self.THRESHOLDS)
            assert out is None or out in {"S", "A", "B", "C", "D"}


# --------------------------------------------------------------------------- retrofill SELECT shape
def _make_rewind_fixture() -> sqlite3.Connection:
    """Minimal in-memory rewind_history.db shape for the retrofill pid lookup.

    Only the columns retrofill_match_metrics._find_tracked_pid reads
    (match_id, champion_name, team_id, participant_id) are needed.
    """
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE participants ("
        " match_id TEXT, participant_id INTEGER,"
        " team_id INTEGER, champion_name TEXT, kills INTEGER)"
    )
    conn.executemany(
        "INSERT INTO participants (match_id, participant_id, team_id, champion_name, kills)"
        " VALUES (?,?,?,?,?)",
        [
            ("NA1_1", 1, 100, "Ahri", 5),
            ("NA1_1", 6, 200, "Zed", 7),
        ],
    )
    conn.commit()
    return conn


class TestRetrofillTrackedPidLookup:
    """``_find_tracked_pid`` must resolve the operator participant by the
    (match_id, champion_name, team_id) triple and return None on a miss -
    the retrofill skips a match it cannot map rather than crashing."""

    def test_resolves_existing_pid(self):
        import scripts.retrofill_match_metrics as RF
        conn = _make_rewind_fixture()
        try:
            assert RF._find_tracked_pid(conn, "NA1_1", "Ahri", 100) == 1
            assert RF._find_tracked_pid(conn, "NA1_1", "Zed", 200) == 6
        finally:
            conn.close()

    def test_missing_triple_returns_none(self):
        import scripts.retrofill_match_metrics as RF
        conn = _make_rewind_fixture()
        try:
            assert RF._find_tracked_pid(conn, "NA1_1", "Ahri", 200) is None
            assert RF._find_tracked_pid(conn, "NA1_999", "Ahri", 100) is None
        finally:
            conn.close()


# --------------------------------------------------------------------------- db_size_monitor.evaluate
class TestDbSizeMonitorEvaluate:
    """``evaluate`` is pure: given a collected report + thresholds it must flag
    exactly the rows whose byte size exceeds its mapped cap and leave the rest
    clean. Regression guard against an off-by-one / missing-key breach miss."""

    def _report(self, rewind_bytes: int, logs_bytes: int, spend_bytes: int) -> dict:
        return {
            "rows": [
                {"label": "data/rewind_history.db", "exists": True, "bytes": rewind_bytes},
                {"label": "logs", "exists": True, "bytes": logs_bytes},
                {"label": "data/spend", "exists": True, "bytes": spend_bytes},
            ]
        }

    def test_no_breach_when_all_under(self):
        import scripts.db_size_monitor as DBM
        thresholds = {"rewind_history.db": 100, "logs": 100, "data/spend": 100}
        breaches = DBM.evaluate(self._report(50, 50, 50), thresholds)
        assert breaches == []

    def test_strictly_over_breaches(self):
        import scripts.db_size_monitor as DBM
        thresholds = {"rewind_history.db": 100, "logs": 100, "data/spend": 100}
        breaches = DBM.evaluate(self._report(101, 50, 50), thresholds)
        assert len(breaches) == 1
        assert breaches[0]["label"] == "data/rewind_history.db"
        assert breaches[0]["over_by"] == 1

    def test_equal_to_threshold_is_not_a_breach(self):
        import scripts.db_size_monitor as DBM
        thresholds = {"rewind_history.db": 100, "logs": 100, "data/spend": 100}
        breaches = DBM.evaluate(self._report(100, 100, 100), thresholds)
        assert breaches == []
