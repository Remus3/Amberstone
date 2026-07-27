"""Tests for core.rune_wpa: per-rune (keystone + minor) WPA decomposition
over the rewind corpus. Runes are a PRE-GAME choice, so the expected
baseline is the win-prob at the EARLIEST timeline frame (the start-of-game
state) rather than a mid-game purchase/max frame. A synthetic in-memory
sqlite fixture controls the gold/xp frames + win outcomes + the per-
participant rune columns so the expected-vs-observed math + the
keystone/minor extraction are asserted exactly (model=None -> the
deterministic fallback sigmoid).
"""
from __future__ import annotations

import os
import sqlite3
import unittest

from core import rune_wpa
from core.smoothed_rates import shrink

# Real runesReforged ids: 8112 Electrocute (keystone, Domination tree);
# 8126 Cheap Shot (a minor in Domination). 5008 is a stat shard (NOT a
# named rune) and must be excluded.
ELECTROCUTE = 8112
CHEAP_SHOT = 8126
PRESS_THE_ATTACK = 8005
STAT_SHARD = 5008

# Fallback predict_prob (model=None) is deterministic:
#   p100(+5000) = 0.8176,  p100(-5000) = 0.1824,  p100(0) = 0.5
# Team 200 flips: expected = 1 - p100.
P100_AHEAD = 0.8176   # team 100 +5000 gold at the baseline frame
P100_BEHIND = 0.1824  # team 100 -5000 gold at the baseline frame


def _build_db() -> sqlite3.Connection:
    """In-memory rewind_history.db with the columns rune_wpa reads."""
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
        CREATE TABLE participants (
            match_id TEXT, participant_id INTEGER, team_id INTEGER, win INTEGER,
            rune_keystone_id INTEGER,
            rune_p0 INTEGER, rune_p1 INTEGER, rune_p2 INTEGER, rune_p3 INTEGER,
            rune_s0 INTEGER, rune_s1 INTEGER
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
    runes: dict[int, dict],  # pid -> {keystone, minors:[...]}
    has_timeline: int = 1,
    queue_id: int = 420,
    patch: str = "16.11.1",
    no_frames: bool = False,
    baseline_ts: int = 0,
) -> None:
    """Add one match. team100/team200 gold are the per-team TOTALS split
    evenly across the 5 participants, written at the baseline frame (and a
    later frame so the earliest-frame pick is unambiguous). ``runes`` maps
    a participant id to its keystone + up to 5 minor runes."""
    conn.execute(
        "INSERT INTO matches VALUES (?,?,?,?)",
        (match_id, queue_id, patch, has_timeline),
    )
    # participants 1-5 = team 100, 6-10 = team 200
    for pid in range(1, 11):
        team = 100 if pid <= 5 else 200
        win = team100_win if team == 100 else (1 - team100_win)
        rr = runes.get(pid, {})
        ks = int(rr.get("keystone", 0) or 0)
        minors = list(rr.get("minors", []) or [])
        minors = (minors + [0, 0, 0, 0, 0])[:5]
        # rune_p0 mirrors the keystone (primary slot 0) in the live writer.
        conn.execute(
            "INSERT INTO participants VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (match_id, pid, team, win, ks, ks,
             minors[0], minors[1], minors[2], minors[3], minors[4]),
        )
    if not no_frames:
        # earliest frame at baseline_ts, plus a later frame.
        for ts in (baseline_ts, baseline_ts + 600_000):
            for pid in range(1, 11):
                team = 100 if pid <= 5 else 200
                gold = (team100_gold if team == 100 else team200_gold) // 5
                conn.execute(
                    "INSERT INTO timeline_frames VALUES (?,?,?,?,?)",
                    (match_id, ts, pid, gold, 1000),
                )
    conn.commit()


class ExtractionTests(unittest.TestCase):
    def test_keystone_and_minors_emitted(self):
        conn = _build_db()
        for i in range(25):
            _add_match(
                conn, f"A{i}", team100_gold=0, team200_gold=0, team100_win=1,
                runes={1: {"keystone": ELECTROCUTE,
                           "minors": [CHEAP_SHOT]}},
            )
        out = rune_wpa.compute_rune_wpa(conn, min_n=20)
        ks = next(it for it in out["items"]
                  if it["rune_id"] == ELECTROCUTE)
        self.assertEqual(ks["slot_kind"], "keystone")
        self.assertEqual(ks["n"], 25)
        minor = next(it for it in out["items"]
                     if it["rune_id"] == CHEAP_SHOT)
        self.assertEqual(minor["slot_kind"], "minor")
        self.assertEqual(minor["n"], 25)

    def test_stat_shard_excluded(self):
        conn = _build_db()
        for i in range(25):
            _add_match(
                conn, f"S{i}", team100_gold=0, team200_gold=0, team100_win=1,
                runes={1: {"keystone": ELECTROCUTE,
                           "minors": [STAT_SHARD]}},
            )
        out = rune_wpa.compute_rune_wpa(conn, min_n=20)
        ids = {it["rune_id"] for it in out["items"]}
        self.assertIn(ELECTROCUTE, ids)
        self.assertNotIn(STAT_SHARD, ids)

    def test_zero_rune_id_skipped(self):
        conn = _build_db()
        for i in range(25):
            _add_match(
                conn, f"Z{i}", team100_gold=0, team200_gold=0, team100_win=1,
                runes={1: {"keystone": 0, "minors": [0, 0]}},
            )
        out = rune_wpa.compute_rune_wpa(conn, min_n=20)
        self.assertEqual(out["items"], [])


class DecompositionMathTests(unittest.TestCase):
    def test_ahead_winner_low_positive_wpa(self):
        """Keystone always run far AHEAD by a team that WINS -> high
        expected -> LOW positive wpa (selection bias removed)."""
        conn = _build_db()
        for i in range(25):
            _add_match(
                conn, f"A{i}", team100_gold=5000, team200_gold=0,
                team100_win=1, runes={1: {"keystone": ELECTROCUTE}},
            )
        out = rune_wpa.compute_rune_wpa(conn, min_n=20)
        row = next(it for it in out["items"] if it["rune_id"] == ELECTROCUTE)
        self.assertEqual(row["n"], 25)
        self.assertAlmostEqual(row["observed_winrate"], 1.0, places=3)
        self.assertAlmostEqual(row["expected_winrate"], P100_AHEAD, places=3)
        self.assertAlmostEqual(row["wpa"], 1.0 - P100_AHEAD, places=3)
        self.assertGreater(row["wpa"], 0.0)

    def test_behind_winner_high_wpa(self):
        """Keystone run BEHIND that still wins -> low expected -> HIGH wpa."""
        conn = _build_db()
        for i in range(25):
            _add_match(
                conn, f"B{i}", team100_gold=0, team200_gold=5000,
                team100_win=1, runes={1: {"keystone": ELECTROCUTE}},
            )
        out = rune_wpa.compute_rune_wpa(conn, min_n=20)
        row = next(it for it in out["items"] if it["rune_id"] == ELECTROCUTE)
        self.assertAlmostEqual(row["observed_winrate"], 1.0, places=3)
        self.assertAlmostEqual(row["expected_winrate"], P100_BEHIND, places=3)
        self.assertAlmostEqual(row["wpa"], 1.0 - P100_BEHIND, places=3)
        self.assertGreater(row["wpa"], 0.70)

    def test_team_200_perspective_flip(self):
        """A rune run by team 200 uses 1 - p100 for the expected win."""
        conn = _build_db()
        for i in range(25):
            _add_match(
                conn, f"T{i}", team100_gold=0, team200_gold=5000,
                team100_win=0, runes={6: {"keystone": ELECTROCUTE}},
            )
        out = rune_wpa.compute_rune_wpa(conn, min_n=20)
        row = next(it for it in out["items"] if it["rune_id"] == ELECTROCUTE)
        self.assertAlmostEqual(row["observed_winrate"], 1.0, places=3)
        # team 200 ahead -> expected = 1 - p100(behind) = 0.8176.
        self.assertAlmostEqual(row["expected_winrate"], P100_AHEAD, places=3)
        self.assertAlmostEqual(row["wpa"], 1.0 - P100_AHEAD, places=3)

    def test_baseline_uses_earliest_frame(self):
        """Pre-game: the expected baseline must come from the EARLIEST
        frame, not a later one. Earliest frame is even (gold 0/0 -> 0.5);
        the later frame is lopsided. Expected must be ~0.5, not skewed."""
        conn = _build_db()
        for i in range(25):
            conn.execute(
                "INSERT INTO matches VALUES (?,?,?,?)",
                (f"E{i}", 420, "16.11.1", 1),
            )
            for pid in range(1, 11):
                team = 100 if pid <= 5 else 200
                ks = ELECTROCUTE if pid == 1 else 0
                conn.execute(
                    "INSERT INTO participants VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (f"E{i}", pid, team, 1 if team == 100 else 0,
                     ks, ks, 0, 0, 0, 0, 0),
                )
            # earliest frame even (0/0), later frame team100 +5000.
            for pid in range(1, 11):
                conn.execute(
                    "INSERT INTO timeline_frames VALUES (?,?,?,?,?)",
                    (f"E{i}", 0, pid, 0, 1000),
                )
            for pid in range(1, 11):
                team = 100 if pid <= 5 else 200
                conn.execute(
                    "INSERT INTO timeline_frames VALUES (?,?,?,?,?)",
                    (f"E{i}", 600_000, pid, 1000 if team == 100 else 0, 1000),
                )
        conn.commit()
        out = rune_wpa.compute_rune_wpa(conn, min_n=20)
        row = next(it for it in out["items"] if it["rune_id"] == ELECTROCUTE)
        # Earliest frame is even -> expected 0.5, NOT the +5000 frame's 0.8176.
        self.assertAlmostEqual(row["expected_winrate"], 0.5, places=3)


class GateAndShrinkTests(unittest.TestCase):
    def test_min_n_gate(self):
        conn = _build_db()
        for i in range(10):  # below min_n=20
            _add_match(
                conn, f"G{i}", team100_gold=5000, team200_gold=5000,
                team100_win=1, runes={1: {"keystone": ELECTROCUTE}},
            )
        out = rune_wpa.compute_rune_wpa(conn, min_n=20)
        self.assertEqual(out["items"], [])
        out2 = rune_wpa.compute_rune_wpa(conn, min_n=5)
        self.assertTrue(any(it["rune_id"] == ELECTROCUTE for it in out2["items"]))

    def test_shrink_damps_low_n(self):
        conn = _build_db()
        for i in range(20):  # exactly min_n
            _add_match(
                conn, f"S{i}", team100_gold=0, team200_gold=5000,
                team100_win=1, runes={1: {"keystone": ELECTROCUTE}},
            )
        out = rune_wpa.compute_rune_wpa(conn, min_n=20)
        row = next(it for it in out["items"] if it["rune_id"] == ELECTROCUTE)
        self.assertEqual(row["n"], 20)
        self.assertNotEqual(row["wpa"], 0.0)
        # shrink(20, 5) = 20/25 = 0.8.
        self.assertLess(abs(row["wpa_shrunk"]), abs(row["wpa"]))
        self.assertAlmostEqual(
            row["wpa_shrunk"],
            round(row["wpa"] * shrink(float(row["n"]), 5.0), 4),
            places=4)

    def test_sorted_by_wpa_shrunk_desc(self):
        conn = _build_db()
        # ELECTROCUTE: high wpa (behind+win). PRESS_THE_ATTACK: low wpa.
        for i in range(25):
            _add_match(
                conn, f"H{i}", team100_gold=0, team200_gold=5000,
                team100_win=1, runes={1: {"keystone": ELECTROCUTE}},
            )
        for i in range(25):
            _add_match(
                conn, f"L{i}", team100_gold=5000, team200_gold=0,
                team100_win=1, runes={1: {"keystone": PRESS_THE_ATTACK}},
            )
        out = rune_wpa.compute_rune_wpa(conn, min_n=20)
        ws = [it["wpa_shrunk"] for it in out["items"]]
        self.assertEqual(ws, sorted(ws, reverse=True))
        self.assertEqual(out["items"][0]["rune_id"], ELECTROCUTE)


class FailSoftTests(unittest.TestCase):
    def test_match_with_no_frames_skipped(self):
        conn = _build_db()
        for i in range(20):
            _add_match(
                conn, f"OK{i}", team100_gold=5000, team200_gold=0,
                team100_win=1, runes={1: {"keystone": ELECTROCUTE}},
            )
        _add_match(
            conn, "NOFRAMES", team100_gold=5000, team200_gold=0,
            team100_win=1, runes={1: {"keystone": ELECTROCUTE}},
            no_frames=True,
        )
        out = rune_wpa.compute_rune_wpa(conn, min_n=20)
        self.assertTrue(out["ok"])
        row = next(it for it in out["items"] if it["rune_id"] == ELECTROCUTE)
        self.assertEqual(row["n"], 20)

    def test_queue_filter(self):
        conn = _build_db()
        for i in range(25):
            _add_match(
                conn, f"Q{i}", team100_gold=5000, team200_gold=0,
                team100_win=1, runes={1: {"keystone": ELECTROCUTE}},
                queue_id=420,
            )
        for i in range(25):
            _add_match(
                conn, f"R{i}", team100_gold=0, team200_gold=5000,
                team100_win=1, runes={1: {"keystone": ELECTROCUTE}},
                queue_id=450,
            )
        out = rune_wpa.compute_rune_wpa(conn, min_n=20, queue_id=420)
        row = next(it for it in out["items"] if it["rune_id"] == ELECTROCUTE)
        self.assertEqual(row["n"], 25)
        self.assertAlmostEqual(row["expected_winrate"], P100_AHEAD, places=3)


class RuneNameTests(unittest.TestCase):
    def test_real_catalog_names_resolve(self):
        names = rune_wpa.load_rune_names()
        # runesReforged.json is TRACKED under data/meta_build/ddragon/<patch>/
        # (pinned 16.11.1 fallback), so it is present in every checkout. An
        # empty catalog means the loader is broken, not that a capability is
        # missing - fail rather than skip past every assertion below.
        self.assertTrue(
            names,
            "load_rune_names() returned nothing from the tracked "
            "runesReforged.json catalog",
        )
        self.assertEqual(names.get(ELECTROCUTE), "Electrocute")
        self.assertEqual(names.get(CHEAP_SHOT), "Cheap Shot")
        # A stat shard id is NOT a named rune in runesReforged.
        self.assertNotIn(STAT_SHARD, names)

    def test_name_populated_in_output(self):
        names = rune_wpa.load_rune_names()
        # Decidable against the tracked catalog - see the sibling test above.
        self.assertEqual(
            names.get(ELECTROCUTE), "Electrocute",
            "tracked runesReforged.json did not resolve Electrocute",
        )
        conn = _build_db()
        for i in range(25):
            _add_match(
                conn, f"N{i}", team100_gold=0, team200_gold=0,
                team100_win=1, runes={1: {"keystone": ELECTROCUTE}},
            )
        out = rune_wpa.compute_rune_wpa(conn, min_n=20)
        row = next(it for it in out["items"] if it["rune_id"] == ELECTROCUTE)
        self.assertEqual(row["name"], "Electrocute")


class RealDbSmokeTests(unittest.TestCase):
    @unittest.skipUnless(
        os.path.exists("data/rewind_history.db"),
        "rewind_history.db not present",
    )
    def test_real_db_returns_runes(self):
        out = rune_wpa.compute_rune_wpa_from_db(min_n=20)
        self.assertTrue(out.get("ok"), out)
        self.assertIsInstance(out["items"], list)
        for it in out["items"]:
            self.assertIn(it["slot_kind"], ("keystone", "minor"))
            self.assertGreaterEqual(it["n"], 20)
            for k in ("rune_id", "name", "n", "observed_winrate",
                      "expected_winrate", "wpa", "wpa_shrunk"):
                self.assertIn(k, it)


class AsciiHygieneTests(unittest.TestCase):
    def test_module_files_are_ascii(self):
        for path in ("core/rune_wpa.py", "dashboard/routes_rune_wpa.py",
                     "tests/test_rune_wpa.py"):
            with open(path, "rb") as f:
                data = f.read()
            try:
                data.decode("ascii")
            except UnicodeDecodeError as exc:
                self.fail(f"{path} is not ASCII-clean: {exc}")


if __name__ == "__main__":
    unittest.main()
