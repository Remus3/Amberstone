"""Tests for core.item_wpa: per-item WPA decomposition over the rewind
corpus. The synthetic in-memory sqlite fixture controls the gold/xp
frames + win outcomes + purchases so the expected-vs-observed math is
asserted exactly (model=None -> the deterministic fallback sigmoid).
"""
from __future__ import annotations

import os
import sqlite3
import unittest

from core import item_wpa

# Real catalog ids: 3031 Infinity Edge is a completed SR legendary;
# 1038 B.F. Sword builds into things (a component) and must be excluded.
IE = 3031
BF_SWORD = 1038

# Fallback predict_prob (model=None) is deterministic:
#   p100(+5000) = 0.8176,  p100(-5000) = 0.1824,  p100(0) = 0.5
# Team 200 flips: expected = 1 - p100.
P100_AHEAD = 0.8176   # team 100 +5000 gold
P100_BEHIND = 0.1824  # team 100 -5000 gold


def _build_db() -> sqlite3.Connection:
    """In-memory rewind_history.db with the columns item_wpa reads."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE matches (
            match_id TEXT, queue_id INTEGER, patch TEXT, has_timeline INTEGER
        );
        CREATE TABLE timeline_frames (
            match_id TEXT, timestamp_ms INTEGER, participant_id INTEGER,
            total_gold INTEGER, xp INTEGER
        );
        CREATE TABLE timeline_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT, timestamp_ms INTEGER, event_type TEXT,
            participant_id INTEGER, item_id INTEGER
        );
        CREATE TABLE participants (
            match_id TEXT, participant_id INTEGER, team_id INTEGER, win INTEGER
        );
        """
    )
    return conn


def _add_match(
    conn: sqlite3.Connection,
    match_id: str,
    *,
    team100_gold: int,
    team200_gold: int,
    team100_win: int,
    purchases: list[tuple[int, int, int]],  # (ts_ms, participant_id, item_id)
    has_timeline: int = 1,
    queue_id: int = 420,
    patch: str = "16.11.1",
    no_frames: bool = False,
) -> None:
    """Add one match. team100/team200 gold are the per-team TOTALS split
    evenly across the 5 participants, written at a frame at ts=0 (and a
    later frame so interpolation picks one)."""
    conn.execute(
        "INSERT INTO matches VALUES (?,?,?,?)",
        (match_id, queue_id, patch, has_timeline),
    )
    # participants 1-5 = team 100, 6-10 = team 200
    for pid in range(1, 11):
        team = 100 if pid <= 5 else 200
        win = team100_win if team == 100 else (1 - team100_win)
        conn.execute(
            "INSERT INTO participants VALUES (?,?,?,?)",
            (match_id, pid, team, win),
        )
    if not no_frames:
        # one frame at ts=0, one at ts=300000 (5 min) so purchases later
        # interpolate to the most recent frame at/<= their ts.
        for ts in (0, 60_000, 600_000):
            for pid in range(1, 11):
                team = 100 if pid <= 5 else 200
                gold = (team100_gold if team == 100 else team200_gold) // 5
                conn.execute(
                    "INSERT INTO timeline_frames VALUES (?,?,?,?,?)",
                    (match_id, ts, pid, gold, 1000),
                )
    for ts_ms, pid, item_id in purchases:
        conn.execute(
            "INSERT INTO timeline_events "
            "(match_id, timestamp_ms, event_type, participant_id, item_id) "
            "VALUES (?,?,?,?,?)",
            (match_id, ts_ms, "ITEM_PURCHASED", pid, item_id),
        )
    conn.commit()


class LegendaryFilterTests(unittest.TestCase):
    def test_real_catalog_yields_legendary_set(self):
        legendary = item_wpa.load_legendary_ids()
        # The catalog is TRACKED (data/daemon_slayer/<patch>/items.json, with a
        # pinned 16.11.1 fallback), so it is present in every checkout. An empty
        # result means the loader or the committed catalog is BROKEN - the exact
        # thing this test exists to catch - so it must fail, not skip.
        self.assertTrue(
            legendary,
            "load_legendary_ids() returned nothing from the tracked items.json "
            "catalog - the loader or the committed catalog is broken",
        )
        self.assertIn(IE, legendary, "Infinity Edge must be a legendary")
        self.assertNotIn(BF_SWORD, legendary, "B.F. Sword is a component")
        # Sanity band per the verify-first probe.
        self.assertGreaterEqual(len(legendary), 100)
        self.assertLessEqual(len(legendary), 200)

    def test_component_purchase_excluded(self):
        conn = _build_db()
        # Two purchases: a legendary (IE) and a component (BF Sword). Only
        # the legendary should appear in the output.
        _add_match(
            conn, "M1", team100_gold=10000, team200_gold=10000, team100_win=1,
            purchases=[(60_000, 1, IE)] * 25 + [(60_000, 1, BF_SWORD)] * 25,
        )
        legendary = item_wpa.load_legendary_ids()
        # Decidable against the tracked catalog: B.F. Sword is a component and
        # must never classify as a completed legendary.
        self.assertNotIn(
            BF_SWORD, legendary,
            "tracked catalog classifies B.F. Sword as a legendary - the "
            "completed-legendary classifier regressed",
        )
        out = item_wpa.compute_item_wpa(conn, min_n=20)
        ids = {it["item_id"] for it in out["items"]}
        self.assertIn(IE, ids)
        self.assertNotIn(BF_SWORD, ids)


class DecompositionMathTests(unittest.TestCase):
    def test_ahead_winner_low_positive_wpa(self):
        """Item always bought far AHEAD by a team that WINS -> high
        expected -> LOW positive wpa (selection bias removed)."""
        conn = _build_db()
        # team 100 +10000 vs 0 -> +10000 diff clamps the fallback near 1;
        # use +5000 net so p100 = 0.8176. Per participant gold: team100
        # 5000/5=1000 vs team200 0 -> gold_diff = (1000-0)*5 = 5000.
        for i in range(25):
            _add_match(
                conn, f"A{i}", team100_gold=5000, team200_gold=0, team100_win=1,
                purchases=[(60_000, 1, IE)],
            )
        out = item_wpa.compute_item_wpa(conn, min_n=20)
        row = next(it for it in out["items"] if it["item_id"] == IE)
        self.assertEqual(row["n"], 25)
        self.assertAlmostEqual(row["observed_winrate"], 1.0, places=3)
        self.assertAlmostEqual(row["expected_winrate"], P100_AHEAD, places=3)
        # wpa = 1.0 - 0.8176 = 0.1824 (positive but modest).
        self.assertAlmostEqual(row["wpa"], 1.0 - P100_AHEAD, places=3)
        self.assertGreater(row["wpa"], 0.0)
        self.assertLess(row["wpa"], 0.30)

    def test_behind_winner_high_wpa(self):
        """Item bought BEHIND that still wins -> low expected -> HIGH wpa."""
        conn = _build_db()
        for i in range(25):
            _add_match(
                conn, f"B{i}", team100_gold=0, team200_gold=5000, team100_win=1,
                purchases=[(60_000, 1, IE)],
            )
        out = item_wpa.compute_item_wpa(conn, min_n=20)
        row = next(it for it in out["items"] if it["item_id"] == IE)
        self.assertAlmostEqual(row["observed_winrate"], 1.0, places=3)
        self.assertAlmostEqual(row["expected_winrate"], P100_BEHIND, places=3)
        # wpa = 1.0 - 0.1824 = 0.8176 (high).
        self.assertAlmostEqual(row["wpa"], 1.0 - P100_BEHIND, places=3)
        self.assertGreater(row["wpa"], 0.70)

    def test_team_200_perspective_flip(self):
        """An item bought by team 200 uses 1 - p100 for the expected win.

        Team 200 is +5000 (team200_gold 5000 vs team100 0), so for them
        p100 reflects team 100's perspective (behind) = 0.1824, and their
        expected = 1 - 0.1824 = 0.8176. They WIN. wpa = 1.0 - 0.8176.
        """
        conn = _build_db()
        for i in range(25):
            _add_match(
                conn, f"T{i}", team100_gold=0, team200_gold=5000, team100_win=0,
                purchases=[(60_000, 6, IE)],  # participant 6 = team 200
            )
        out = item_wpa.compute_item_wpa(conn, min_n=20)
        row = next(it for it in out["items"] if it["item_id"] == IE)
        self.assertAlmostEqual(row["observed_winrate"], 1.0, places=3)
        # team 200 ahead -> expected = 1 - p100(behind) = 0.8176.
        self.assertAlmostEqual(row["expected_winrate"], P100_AHEAD, places=3)
        self.assertAlmostEqual(row["wpa"], 1.0 - P100_AHEAD, places=3)

    def test_min_n_gate(self):
        """Items below min_n are dropped."""
        conn = _build_db()
        # 10 purchases of IE < min_n 20.
        for i in range(10):
            _add_match(
                conn, f"G{i}", team100_gold=5000, team200_gold=5000, team100_win=1,
                purchases=[(60_000, 1, IE)],
            )
        out = item_wpa.compute_item_wpa(conn, min_n=20)
        self.assertEqual(out["items"], [])
        # lowering the gate surfaces it.
        out2 = item_wpa.compute_item_wpa(conn, min_n=5)
        self.assertTrue(any(it["item_id"] == IE for it in out2["items"]))

    def test_shrink_damps_low_n(self):
        """A low-N item's |wpa_shrunk| is strictly less than |wpa|."""
        conn = _build_db()
        for i in range(20):  # exactly min_n
            _add_match(
                conn, f"S{i}", team100_gold=0, team200_gold=5000, team100_win=1,
                purchases=[(60_000, 1, IE)],
            )
        out = item_wpa.compute_item_wpa(conn, min_n=20)
        row = next(it for it in out["items"] if it["item_id"] == IE)
        self.assertEqual(row["n"], 20)
        self.assertNotEqual(row["wpa"], 0.0)
        # shrink(20, 5) = 20/25 = 0.8, so wpa_shrunk < wpa in magnitude.
        self.assertLess(abs(row["wpa_shrunk"]), abs(row["wpa"]))
        self.assertAlmostEqual(row["wpa_shrunk"], row["wpa"] * 0.8, places=3)

    def test_sorted_by_wpa_shrunk_desc(self):
        conn = _build_db()
        # IE: high wpa (behind+win). A second legendary id with low wpa.
        # Use 3036 (Lord Dominik's) as a second SR legendary.
        other = 3036
        legendary = item_wpa.load_legendary_ids()
        # Both ids are SR legendaries in the tracked catalog, so their absence
        # is a catalog/classifier regression, not a missing capability.
        self.assertIn(other, legendary, "Lord Dominik's missing from the tracked catalog")
        self.assertIn(IE, legendary, "Infinity Edge missing from the tracked catalog")
        for i in range(25):
            _add_match(
                conn, f"H{i}", team100_gold=0, team200_gold=5000, team100_win=1,
                purchases=[(60_000, 1, IE)],
            )
        for i in range(25):
            # other bought far ahead by winner -> low positive wpa.
            _add_match(
                conn, f"L{i}", team100_gold=5000, team200_gold=0, team100_win=1,
                purchases=[(60_000, 1, other)],
            )
        out = item_wpa.compute_item_wpa(conn, min_n=20)
        order = [it["item_id"] for it in out["items"]]
        self.assertEqual(order[0], IE, "highest wpa_shrunk first")
        ws = [it["wpa_shrunk"] for it in out["items"]]
        self.assertEqual(ws, sorted(ws, reverse=True))


class FailSoftTests(unittest.TestCase):
    def test_match_with_no_frames_does_not_crash(self):
        conn = _build_db()
        # One good match + one with no frames (purchase has no frame to
        # interpolate -> skipped silently).
        for i in range(20):
            _add_match(
                conn, f"OK{i}", team100_gold=5000, team200_gold=0, team100_win=1,
                purchases=[(60_000, 1, IE)],
            )
        _add_match(
            conn, "NOFRAMES", team100_gold=5000, team200_gold=0, team100_win=1,
            purchases=[(60_000, 1, IE)], no_frames=True,
        )
        out = item_wpa.compute_item_wpa(conn, min_n=20)
        self.assertTrue(out["ok"])
        row = next(it for it in out["items"] if it["item_id"] == IE)
        # the no-frames match contributed nothing.
        self.assertEqual(row["n"], 20)

    def test_purchase_before_any_frame_skipped(self):
        conn = _build_db()
        # frames start at ts=0; a purchase at a negative ts has no earlier
        # frame -> skipped. (All our frames begin at 0, so use ts < 0.)
        for i in range(20):
            _add_match(
                conn, f"P{i}", team100_gold=5000, team200_gold=0, team100_win=1,
                purchases=[(60_000, 1, IE), (-1, 1, IE)],
            )
        out = item_wpa.compute_item_wpa(conn, min_n=20)
        row = next(it for it in out["items"] if it["item_id"] == IE)
        # only the ts=60000 purchase counts; the ts=-1 one is skipped.
        self.assertEqual(row["n"], 20)

    def test_queue_filter(self):
        conn = _build_db()
        for i in range(25):
            _add_match(
                conn, f"Q{i}", team100_gold=5000, team200_gold=0, team100_win=1,
                purchases=[(60_000, 1, IE)], queue_id=420,
            )
        for i in range(25):
            _add_match(
                conn, f"R{i}", team100_gold=0, team200_gold=5000, team100_win=1,
                purchases=[(60_000, 1, IE)], queue_id=450,
            )
        out = item_wpa.compute_item_wpa(conn, min_n=20, queue_id=420)
        row = next(it for it in out["items"] if it["item_id"] == IE)
        # only queue 420 matches (ahead+win) -> expected ~0.8176, n=25.
        self.assertEqual(row["n"], 25)
        self.assertAlmostEqual(row["expected_winrate"], P100_AHEAD, places=3)


class RealDbSmokeTests(unittest.TestCase):
    @unittest.skipUnless(
        os.path.exists("data/rewind_history.db"),
        "rewind_history.db not present",
    )
    def test_real_db_returns_items(self):
        out = item_wpa.compute_item_wpa_from_db(min_n=20)
        self.assertTrue(out.get("ok"), out)
        self.assertIsInstance(out["items"], list)
        # Do NOT pin exact numbers - the corpus drifts.
        self.assertGreater(len(out["items"]), 0, "expected some items at min_n=20")
        first = out["items"][0]
        for k in ("item_id", "name", "n", "observed_winrate",
                  "expected_winrate", "wpa", "wpa_shrunk", "avg_purchase_time_s"):
            self.assertIn(k, first)


class AsciiHygieneTests(unittest.TestCase):
    def test_module_files_are_ascii(self):
        for path in ("core/item_wpa.py", "dashboard/routes_item_wpa.py",
                     "tests/test_item_wpa.py"):
            with open(path, "rb") as f:
                data = f.read()
            try:
                data.decode("ascii")
            except UnicodeDecodeError as exc:
                self.fail(f"{path} is not ASCII-clean: {exc}")


if __name__ == "__main__":
    unittest.main()
