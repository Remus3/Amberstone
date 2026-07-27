"""Tests for core.summoner_spell_wpa: per-summoner-spell WPA decomposition
over the rewind corpus. Summoner spells are a PRE-GAME choice, so the
expected baseline is the win-prob at the EARLIEST timeline frame (the
start-of-game state) rather than a mid-game purchase/max frame - the same
simplification core.rune_wpa uses. A synthetic in-memory sqlite fixture
controls the gold/xp frames + win outcomes + the per-participant
summoner1_id/summoner2_id columns so the expected-vs-observed math + the
two-spells-per-participant extraction are asserted exactly (model=None ->
the deterministic fallback sigmoid).
"""
from __future__ import annotations

import os
import sqlite3
import unittest

from core import summoner_spell_wpa
from core.smoothed_rates import shrink

# Real DDragon summoner-spell keys: 4 Flash, 14 Ignite, 12 Teleport.
# 9999 is NOT a spell in summoner.json and must be excluded.
FLASH = 4
IGNITE = 14
TELEPORT = 12
UNKNOWN_SPELL = 9999

# Fallback predict_prob (model=None) is deterministic:
#   p100(+5000) = 0.8176,  p100(-5000) = 0.1824,  p100(0) = 0.5
# Team 200 flips: expected = 1 - p100.
P100_AHEAD = 0.8176   # team 100 +5000 gold at the baseline frame
P100_BEHIND = 0.1824  # team 100 -5000 gold at the baseline frame


def _build_db() -> sqlite3.Connection:
    """In-memory rewind_history.db with the columns summoner_spell_wpa reads."""
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
            summoner1_id INTEGER, summoner2_id INTEGER
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
    spells: dict[int, tuple[int, int]],  # pid -> (summoner1_id, summoner2_id)
    has_timeline: int = 1,
    queue_id: int = 420,
    patch: str = "16.11.1",
    no_frames: bool = False,
    baseline_ts: int = 0,
) -> None:
    """Add one match. team100/team200 gold are the per-team TOTALS split
    evenly across the 5 participants, written at the baseline frame (and a
    later frame so the earliest-frame pick is unambiguous). ``spells`` maps
    a participant id to its (D, F) summoner-spell pair."""
    conn.execute(
        "INSERT INTO matches VALUES (?,?,?,?)",
        (match_id, queue_id, patch, has_timeline),
    )
    # participants 1-5 = team 100, 6-10 = team 200
    for pid in range(1, 11):
        team = 100 if pid <= 5 else 200
        win = team100_win if team == 100 else (1 - team100_win)
        s1, s2 = spells.get(pid, (0, 0))
        conn.execute(
            "INSERT INTO participants VALUES (?,?,?,?,?,?)",
            (match_id, pid, team, win, int(s1 or 0), int(s2 or 0)),
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
    def test_both_spells_emitted(self):
        conn = _build_db()
        for i in range(25):
            _add_match(
                conn, f"A{i}", team100_gold=0, team200_gold=0, team100_win=1,
                spells={1: (FLASH, IGNITE)},
            )
        out = summoner_spell_wpa.compute_summoner_spell_wpa(conn, min_n=20)
        flash = next(it for it in out["items"] if it["spell_id"] == FLASH)
        self.assertEqual(flash["n"], 25)
        ignite = next(it for it in out["items"] if it["spell_id"] == IGNITE)
        self.assertEqual(ignite["n"], 25)

    def test_unknown_spell_id_excluded(self):
        conn = _build_db()
        for i in range(25):
            _add_match(
                conn, f"U{i}", team100_gold=0, team200_gold=0, team100_win=1,
                spells={1: (FLASH, UNKNOWN_SPELL)},
            )
        out = summoner_spell_wpa.compute_summoner_spell_wpa(conn, min_n=20)
        ids = {it["spell_id"] for it in out["items"]}
        self.assertIn(FLASH, ids)
        self.assertNotIn(UNKNOWN_SPELL, ids)

    def test_zero_spell_id_skipped(self):
        conn = _build_db()
        for i in range(25):
            _add_match(
                conn, f"Z{i}", team100_gold=0, team200_gold=0, team100_win=1,
                spells={1: (0, 0)},
            )
        out = summoner_spell_wpa.compute_summoner_spell_wpa(conn, min_n=20)
        self.assertEqual(out["items"], [])


class DecompositionMathTests(unittest.TestCase):
    def test_ahead_winner_low_positive_wpa(self):
        """Spell always run far AHEAD by a team that WINS -> high
        expected -> LOW positive wpa (selection bias removed)."""
        conn = _build_db()
        for i in range(25):
            _add_match(
                conn, f"A{i}", team100_gold=5000, team200_gold=0,
                team100_win=1, spells={1: (FLASH, 0)},
            )
        out = summoner_spell_wpa.compute_summoner_spell_wpa(conn, min_n=20)
        row = next(it for it in out["items"] if it["spell_id"] == FLASH)
        self.assertEqual(row["n"], 25)
        self.assertAlmostEqual(row["observed_winrate"], 1.0, places=3)
        self.assertAlmostEqual(row["expected_winrate"], P100_AHEAD, places=3)
        self.assertAlmostEqual(row["wpa"], 1.0 - P100_AHEAD, places=3)
        self.assertGreater(row["wpa"], 0.0)

    def test_behind_winner_high_wpa(self):
        """Spell run BEHIND that still wins -> low expected -> HIGH wpa."""
        conn = _build_db()
        for i in range(25):
            _add_match(
                conn, f"B{i}", team100_gold=0, team200_gold=5000,
                team100_win=1, spells={1: (FLASH, 0)},
            )
        out = summoner_spell_wpa.compute_summoner_spell_wpa(conn, min_n=20)
        row = next(it for it in out["items"] if it["spell_id"] == FLASH)
        self.assertAlmostEqual(row["observed_winrate"], 1.0, places=3)
        self.assertAlmostEqual(row["expected_winrate"], P100_BEHIND, places=3)
        self.assertAlmostEqual(row["wpa"], 1.0 - P100_BEHIND, places=3)
        self.assertGreater(row["wpa"], 0.70)

    def test_team_200_perspective_flip(self):
        """A spell run by team 200 uses 1 - p100 for the expected win."""
        conn = _build_db()
        for i in range(25):
            _add_match(
                conn, f"T{i}", team100_gold=0, team200_gold=5000,
                team100_win=0, spells={6: (FLASH, 0)},
            )
        out = summoner_spell_wpa.compute_summoner_spell_wpa(conn, min_n=20)
        row = next(it for it in out["items"] if it["spell_id"] == FLASH)
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
                s1 = FLASH if pid == 1 else 0
                conn.execute(
                    "INSERT INTO participants VALUES (?,?,?,?,?,?)",
                    (f"E{i}", pid, team, 1 if team == 100 else 0, s1, 0),
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
        out = summoner_spell_wpa.compute_summoner_spell_wpa(conn, min_n=20)
        row = next(it for it in out["items"] if it["spell_id"] == FLASH)
        # Earliest frame is even -> expected 0.5, NOT the +5000 frame's 0.8176.
        self.assertAlmostEqual(row["expected_winrate"], 0.5, places=3)


class GateAndShrinkTests(unittest.TestCase):
    def test_min_n_gate(self):
        conn = _build_db()
        for i in range(10):  # below min_n=20
            _add_match(
                conn, f"G{i}", team100_gold=5000, team200_gold=5000,
                team100_win=1, spells={1: (FLASH, 0)},
            )
        out = summoner_spell_wpa.compute_summoner_spell_wpa(conn, min_n=20)
        self.assertEqual(out["items"], [])
        out2 = summoner_spell_wpa.compute_summoner_spell_wpa(conn, min_n=5)
        self.assertTrue(any(it["spell_id"] == FLASH for it in out2["items"]))

    def test_shrink_damps_low_n(self):
        conn = _build_db()
        for i in range(20):  # exactly min_n
            _add_match(
                conn, f"S{i}", team100_gold=0, team200_gold=5000,
                team100_win=1, spells={1: (FLASH, 0)},
            )
        out = summoner_spell_wpa.compute_summoner_spell_wpa(conn, min_n=20)
        row = next(it for it in out["items"] if it["spell_id"] == FLASH)
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
        # FLASH: high wpa (behind+win). TELEPORT: low wpa (ahead+win).
        for i in range(25):
            _add_match(
                conn, f"H{i}", team100_gold=0, team200_gold=5000,
                team100_win=1, spells={1: (FLASH, 0)},
            )
        for i in range(25):
            _add_match(
                conn, f"L{i}", team100_gold=5000, team200_gold=0,
                team100_win=1, spells={1: (TELEPORT, 0)},
            )
        out = summoner_spell_wpa.compute_summoner_spell_wpa(conn, min_n=20)
        ws = [it["wpa_shrunk"] for it in out["items"]]
        self.assertEqual(ws, sorted(ws, reverse=True))
        self.assertEqual(out["items"][0]["spell_id"], FLASH)


class FailSoftTests(unittest.TestCase):
    def test_match_with_no_frames_skipped(self):
        conn = _build_db()
        for i in range(20):
            _add_match(
                conn, f"OK{i}", team100_gold=5000, team200_gold=0,
                team100_win=1, spells={1: (FLASH, 0)},
            )
        _add_match(
            conn, "NOFRAMES", team100_gold=5000, team200_gold=0,
            team100_win=1, spells={1: (FLASH, 0)},
            no_frames=True,
        )
        out = summoner_spell_wpa.compute_summoner_spell_wpa(conn, min_n=20)
        self.assertTrue(out["ok"])
        row = next(it for it in out["items"] if it["spell_id"] == FLASH)
        self.assertEqual(row["n"], 20)

    def test_queue_filter(self):
        conn = _build_db()
        for i in range(25):
            _add_match(
                conn, f"Q{i}", team100_gold=5000, team200_gold=0,
                team100_win=1, spells={1: (FLASH, 0)},
                queue_id=420,
            )
        for i in range(25):
            _add_match(
                conn, f"R{i}", team100_gold=0, team200_gold=5000,
                team100_win=1, spells={1: (FLASH, 0)},
                queue_id=450,
            )
        out = summoner_spell_wpa.compute_summoner_spell_wpa(
            conn, min_n=20, queue_id=420)
        row = next(it for it in out["items"] if it["spell_id"] == FLASH)
        self.assertEqual(row["n"], 25)
        self.assertAlmostEqual(row["expected_winrate"], P100_AHEAD, places=3)

    def test_missing_db_fail_soft(self):
        out = summoner_spell_wpa.compute_summoner_spell_wpa_from_db(
            db_path=__import__("pathlib").Path("does_not_exist_12345.db"))
        self.assertFalse(out["ok"])
        self.assertIn("missing", out["error"])


class SpellNameTests(unittest.TestCase):
    def test_real_catalog_names_resolve(self):
        names = summoner_spell_wpa.load_spell_names()
        # summoner.json is TRACKED under data/meta_build/ddragon/<patch>/
        # (pinned 16.11.1 fallback), so it is present in every checkout. An
        # empty catalog means the loader is broken - fail rather than skip.
        self.assertTrue(
            names,
            "load_spell_names() returned nothing from the tracked summoner.json "
            "catalog",
        )
        self.assertEqual(names.get(FLASH), "Flash")
        self.assertEqual(names.get(IGNITE), "Ignite")
        # A bogus id is NOT a spell in summoner.json.
        self.assertNotIn(UNKNOWN_SPELL, names)

    def test_name_and_icon_populated_in_output(self):
        names = summoner_spell_wpa.load_spell_names()
        # Decidable against the tracked catalog - see the sibling test above.
        self.assertEqual(
            names.get(FLASH), "Flash",
            "tracked summoner.json did not resolve Flash",
        )
        conn = _build_db()
        for i in range(25):
            _add_match(
                conn, f"N{i}", team100_gold=0, team200_gold=0,
                team100_win=1, spells={1: (FLASH, 0)},
            )
        out = summoner_spell_wpa.compute_summoner_spell_wpa(conn, min_n=20)
        row = next(it for it in out["items"] if it["spell_id"] == FLASH)
        self.assertEqual(row["name"], "Flash")
        # icon = the DDragon spell id slug (serves /icons/spells/<slug>.png).
        self.assertEqual(row["icon"], "SummonerFlash")


class RealDbSmokeTests(unittest.TestCase):
    @unittest.skipUnless(
        os.path.exists("data/rewind_history.db"),
        "rewind_history.db not present",
    )
    def test_real_db_returns_spells(self):
        out = summoner_spell_wpa.compute_summoner_spell_wpa_from_db(min_n=20)
        self.assertTrue(out.get("ok"), out)
        self.assertIsInstance(out["items"], list)
        for it in out["items"]:
            self.assertGreaterEqual(it["n"], 20)
            for k in ("spell_id", "name", "n", "observed_winrate",
                      "expected_winrate", "wpa", "wpa_shrunk"):
                self.assertIn(k, it)


class AsciiHygieneTests(unittest.TestCase):
    def test_module_files_are_ascii(self):
        for path in ("core/summoner_spell_wpa.py",
                     "dashboard/routes_summspell_wpa.py",
                     "tests/test_summspell_wpa.py"):
            with open(path, "rb") as f:
                data = f.read()
            try:
                data.decode("ascii")
            except UnicodeDecodeError as exc:
                self.fail(f"{path} is not ASCII-clean: {exc}")


if __name__ == "__main__":
    unittest.main()
