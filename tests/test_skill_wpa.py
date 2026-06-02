"""Tests for core.skill_wpa: per-(champion, first-maxed basic) skill-order
WPA decomposition. A synthetic in-memory sqlite fixture controls the
gold/xp frames + win outcomes + SKILL_LEVEL_UP sequences so the
expected-vs-observed math + the first-maxed-basic logic are asserted
exactly (model=None -> the deterministic fallback sigmoid).
"""
from __future__ import annotations

import sqlite3
import unittest

from core import skill_wpa
from core.smoothed_rates import shrink

AHRI = 103
SYNDRA = 134

# Fallback predict_prob (model=None) is deterministic:
#   p100(+5000) = 0.8176, p100(-5000) = 0.1824, p100(0) = 0.5
P100_AHEAD = 0.8176
P100_BEHIND = 0.1824


def _build_db() -> sqlite3.Connection:
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
            participant_id INTEGER, skill_slot INTEGER
        );
        CREATE TABLE participants (
            match_id TEXT, participant_id INTEGER, team_id INTEGER,
            win INTEGER, champion_id INTEGER
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
    maxes: list[tuple[int, int, int, int]],  # (pid, champ_id, slot, max_ts_ms)
    extra_events: list[tuple[int, int, int]] | None = None,  # (ts, pid, slot)
    champ_by_pid: dict[int, int] | None = None,
    has_timeline: int = 1,
    queue_id: int = 420,
    patch: str = "16.11.1",
    no_frames: bool = False,
) -> None:
    """One match. ``maxes`` lists participants who max a basic: 5 level-ups
    in ``slot`` ending at ``max_ts_ms`` (so the 5th = the max frame)."""
    conn.execute(
        "INSERT INTO matches VALUES (?,?,?,?)",
        (match_id, queue_id, patch, has_timeline),
    )
    champ_by_pid = champ_by_pid or {}
    for pid in range(1, 11):
        team = 100 if pid <= 5 else 200
        win = team100_win if team == 100 else (1 - team100_win)
        conn.execute(
            "INSERT INTO participants VALUES (?,?,?,?,?)",
            (match_id, pid, team, win, champ_by_pid.get(pid, 0)),
        )
    if not no_frames:
        for ts in (0, 60_000, 600_000):
            for pid in range(1, 11):
                team = 100 if pid <= 5 else 200
                gold = (team100_gold if team == 100 else team200_gold) // 5
                conn.execute(
                    "INSERT INTO timeline_frames VALUES (?,?,?,?,?)",
                    (match_id, ts, pid, gold, 1000),
                )
    for pid, champ_id, slot, max_ts in maxes:
        # also register the champ for this pid in participants
        conn.execute(
            "UPDATE participants SET champion_id=? WHERE match_id=? AND participant_id=?",
            (champ_id, match_id, pid),
        )
        for i in range(5):
            ts = max_ts - (4 - i) * 1000  # last point at max_ts
            conn.execute(
                "INSERT INTO timeline_events "
                "(match_id, timestamp_ms, event_type, participant_id, skill_slot) "
                "VALUES (?,?,?,?,?)",
                (match_id, ts, "SKILL_LEVEL_UP", pid, slot),
            )
    for ts, pid, slot in (extra_events or []):
        conn.execute(
            "INSERT INTO timeline_events "
            "(match_id, timestamp_ms, event_type, participant_id, skill_slot) "
            "VALUES (?,?,?,?,?)",
            (match_id, ts, "SKILL_LEVEL_UP", pid, slot),
        )
    conn.commit()


class DecompositionMathTests(unittest.TestCase):
    def test_ahead_winner_low_positive_wpa(self):
        conn = _build_db()
        for i in range(25):
            _add_match(
                conn, f"A{i}", team100_gold=5000, team200_gold=0, team100_win=1,
                maxes=[(1, AHRI, 1, 60_000)],  # pid1 (team100) maxes Q ahead
            )
        out = skill_wpa.compute_skill_wpa(conn, min_n=20)
        row = next(it for it in out["items"]
                   if it["champion_id"] == AHRI and it["skill_slot"] == 1)
        self.assertEqual(row["n"], 25)
        self.assertEqual(row["skill"], "Q")
        self.assertAlmostEqual(row["observed_winrate"], 1.0, places=3)
        self.assertAlmostEqual(row["expected_winrate"], P100_AHEAD, places=3)
        self.assertAlmostEqual(row["wpa"], 1.0 - P100_AHEAD, places=3)
        self.assertGreater(row["wpa"], 0.0)

    def test_team200_perspective_flips_expected(self):
        conn = _build_db()
        # team 100 ahead +5000, but a TEAM 200 participant (pid 6) maxes W
        # and LOSES -> expected for team200 = 1 - p100 = 0.1824, observed 0.
        for i in range(25):
            _add_match(
                conn, f"B{i}", team100_gold=5000, team200_gold=0, team100_win=1,
                maxes=[(6, SYNDRA, 2, 60_000)],
            )
        out = skill_wpa.compute_skill_wpa(conn, min_n=20)
        row = next(it for it in out["items"]
                   if it["champion_id"] == SYNDRA and it["skill_slot"] == 2)
        self.assertEqual(row["skill"], "W")
        self.assertAlmostEqual(row["observed_winrate"], 0.0, places=3)
        self.assertAlmostEqual(row["expected_winrate"], P100_BEHIND, places=3)
        self.assertAlmostEqual(row["wpa"], 0.0 - P100_BEHIND, places=3)
        self.assertLess(row["wpa"], 0.0)


class FirstMaxedLogicTests(unittest.TestCase):
    def test_first_slot_to_five_wins(self):
        # pid1 levels W to 5 (ending ts=50000) BEFORE Q reaches 5
        # (Q points after). first_maxed must be W (slot 2), not Q.
        conn = _build_db()
        for i in range(22):
            _add_match(
                conn, f"C{i}", team100_gold=0, team200_gold=0, team100_win=1,
                maxes=[(1, AHRI, 2, 50_000)],  # W maxed at 50000
                extra_events=[(60_000 + j, 1, 1) for j in range(5)],  # Q after
            )
        out = skill_wpa.compute_skill_wpa(conn, min_n=20)
        rows = [it for it in out["items"] if it["champion_id"] == AHRI]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["skill_slot"], 2)
        self.assertEqual(rows[0]["skill"], "W")

    def test_ult_slot_excluded(self):
        # pid1 gets 5 points in slot 4 (R) only -> no basic maxed -> absent.
        conn = _build_db()
        for i in range(25):
            _add_match(
                conn, f"D{i}", team100_gold=0, team200_gold=0, team100_win=1,
                maxes=[(1, AHRI, 4, 60_000)],  # slot 4 = R
            )
        out = skill_wpa.compute_skill_wpa(conn, min_n=20)
        self.assertEqual(
            [it for it in out["items"] if it["champion_id"] == AHRI], [])

    def test_never_maxed_skipped(self):
        # Only 4 points in any basic -> never reaches rank 5 -> absent.
        conn = _build_db()
        for i in range(25):
            _add_match(
                conn, f"E{i}", team100_gold=0, team200_gold=0, team100_win=1,
                maxes=[],
                extra_events=[(10_000 + j, 1, 1) for j in range(4)],  # Q x4
                champ_by_pid={1: AHRI},
            )
        out = skill_wpa.compute_skill_wpa(conn, min_n=20)
        self.assertEqual(
            [it for it in out["items"] if it["champion_id"] == AHRI], [])


class GateAndShrinkTests(unittest.TestCase):
    def test_min_n_gate(self):
        conn = _build_db()
        for i in range(10):  # below min_n=20
            _add_match(
                conn, f"F{i}", team100_gold=0, team200_gold=0, team100_win=1,
                maxes=[(1, AHRI, 1, 60_000)],
            )
        out = skill_wpa.compute_skill_wpa(conn, min_n=20)
        self.assertEqual(out["items"], [])
        out2 = skill_wpa.compute_skill_wpa(conn, min_n=10)
        self.assertTrue(any(it["champion_id"] == AHRI for it in out2["items"]))

    def test_shrink_relationship(self):
        conn = _build_db()
        for i in range(40):
            _add_match(
                conn, f"G{i}", team100_gold=3000, team200_gold=0,
                team100_win=(1 if i % 2 == 0 else 0),
                maxes=[(1, AHRI, 1, 60_000)],
            )
        out = skill_wpa.compute_skill_wpa(conn, min_n=20)
        row = next(it for it in out["items"] if it["champion_id"] == AHRI)
        self.assertAlmostEqual(
            row["wpa_shrunk"], round(row["wpa"] * shrink(float(row["n"]), 5.0), 4),
            places=4)

    def test_champ_id_zero_excluded(self):
        conn = _build_db()
        for i in range(25):
            _add_match(
                conn, f"H{i}", team100_gold=0, team200_gold=0, team100_win=1,
                maxes=[(1, 0, 1, 60_000)],  # champion_id 0
            )
        out = skill_wpa.compute_skill_wpa(conn, min_n=20)
        self.assertEqual(out["items"], [])


class FailSoftTests(unittest.TestCase):
    def test_no_frames_match_skipped(self):
        conn = _build_db()
        for i in range(25):
            _add_match(
                conn, f"I{i}", team100_gold=0, team200_gold=0, team100_win=1,
                maxes=[(1, AHRI, 1, 60_000)], no_frames=True,
            )
        out = skill_wpa.compute_skill_wpa(conn, min_n=20)
        self.assertTrue(out["ok"])
        self.assertEqual(out["items"], [])


class RealDbSmokeTests(unittest.TestCase):
    def test_real_db_compute(self):
        from pathlib import Path
        db = Path("data") / "rewind_history.db"
        if not db.exists():
            self.skipTest("rewind_history.db not present")
        out = skill_wpa.compute_skill_wpa_from_db(min_n=20)
        self.assertTrue(out.get("ok"))
        self.assertIsInstance(out.get("items"), list)
        for it in out["items"]:
            self.assertIn(it["skill_slot"], (1, 2, 3))
            self.assertIn(it["skill"], ("Q", "W", "E"))
            self.assertGreaterEqual(it["n"], 20)


if __name__ == "__main__":
    unittest.main()
