"""Item 269 L5 - pickban-DB counter-quality validation harness unit tests.

Hermetic: synthetic targets dict + an in-memory sqlite, no live DB, no network.
Covers the claim resolver, both ground-truth scorers, the Wilson math, the gate
verdict, and fail-soft loading.
"""
from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import tools.replay_pickban_validate as pv  # noqa: E402


def _targets():
    # Garen counters {Vex}; Garen good_against {Aatrox}. Symmetric agree case:
    # Teemo counters {Garen} AND Garen good_against omits Teemo -> single vote A.
    return {
        "Garen": {"counters": {"Vex"}, "good_against": {"Aatrox", "Teemo"}},
        "Vex": {"counters": set(), "good_against": {"Garen"}},
        "Aatrox": {"counters": {"Garen"}, "good_against": set()},
        # Conflict: Yone.counters has Zed (Zed favored=A-vs... ) AND
        # Zed.counters has Yone -> votes {A from Yone side? } craft an actual conflict.
        "Yone": {"counters": {"Zed"}, "good_against": set()},
        "Zed": {"counters": {"Yone"}, "good_against": set()},
    }


class DbClaimTests(unittest.TestCase):
    def setUp(self):
        self.t = _targets()

    def test_b_in_a_counters_favors_b(self):
        # Vex in Garen.counters -> B(=Vex) favored when A=Garen, B=Vex.
        self.assertEqual(pv.db_claim(self.t, "Garen", "Vex"), "B")

    def test_b_in_a_good_against_favors_a(self):
        # Aatrox in Garen.good_against -> A(=Garen) favored.
        self.assertEqual(pv.db_claim(self.t, "Garen", "Aatrox"), "A")

    def test_symmetric_agree_collapses(self):
        # Garen.good_against has Aatrox (A favored) AND Aatrox.counters has Garen
        # (A favored) -> single vote "A".
        self.assertEqual(pv.db_claim(self.t, "Garen", "Aatrox"), "A")

    def test_conflict_excluded(self):
        # Yone.counters{Zed} -> B favored; Zed.counters{Yone} -> A favored ->
        # two distinct votes -> None.
        self.assertIsNone(pv.db_claim(self.t, "Yone", "Zed"))

    def test_no_claim_returns_none(self):
        self.assertIsNone(pv.db_claim(self.t, "Garen", "Lux"))


class ScoreGoldTests(unittest.TestCase):
    def _pair(self, ga, gb):
        return pv.LanePair(match_id="m", lane="TOP", champ_a="A", champ_b="B", gold_a=ga, gold_b=gb)

    def test_no_claim(self):
        self.assertEqual(pv.score_gold(self._pair(100, 50), None), ("no_claim", False))

    def test_gold_tie(self):
        self.assertEqual(pv.score_gold(self._pair(100, 100), "A"), ("tie", False))

    def test_decisive_agree(self):
        self.assertEqual(pv.score_gold(self._pair(200, 100), "A"), ("decisive", True))

    def test_decisive_disagree(self):
        self.assertEqual(pv.score_gold(self._pair(100, 200), "A"), ("decisive", False))


class ScoreTradeTests(unittest.TestCase):
    def _pair(self):
        return pv.LanePair(match_id="m", lane="MID", champ_a="A", champ_b="B")

    def test_no_claim(self):
        self.assertEqual(pv.score_trade(self._pair(), None, 1, 0), ("no_claim", False))

    def test_no_duel(self):
        self.assertEqual(pv.score_trade(self._pair(), "A", 0, 0), ("no_duel", False))

    def test_kill_tie(self):
        self.assertEqual(pv.score_trade(self._pair(), "A", 2, 2), ("tie", False))

    def test_decisive(self):
        self.assertEqual(pv.score_trade(self._pair(), "A", 3, 1), ("decisive", True))
        self.assertEqual(pv.score_trade(self._pair(), "B", 3, 1), ("decisive", False))


class WilsonTests(unittest.TestCase):
    def test_zero_n(self):
        self.assertEqual(pv.wilson_interval(0, 0), (None, None))

    def test_half_brackets_point_five(self):
        lo, hi = pv.wilson_interval(50, 100)
        self.assertLess(lo, 0.5)
        self.assertGreater(hi, 0.5)

    def test_strong_signal_lower_bound_above_half(self):
        lo, _hi = pv.wilson_interval(900, 1000)
        self.assertGreater(lo, 0.5)


class VerdictTests(unittest.TestCase):
    def test_insufficient_when_no_decisive(self):
        self.assertEqual(pv._verdict({"gold": {"n_decisive": 0}}), "insufficient_data")

    def test_signal_when_gate_clears(self):
        self.assertEqual(
            pv._verdict({"gold": {"n_decisive": 1000, "gate_clears_coinflip": True}}),
            "signal",
        )

    def test_no_signal_when_coinflip(self):
        self.assertEqual(
            pv._verdict({"gold": {"n_decisive": 1000, "gate_clears_coinflip": False}}),
            "no_signal",
        )


class LoadTargetsTests(unittest.TestCase):
    def test_missing_path_fail_soft(self):
        self.assertEqual(pv.load_targets(Path("/no/such/file.json")), {})


class EndToEndInMemoryTests(unittest.TestCase):
    def _db(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE matches(match_id TEXT, game_mode TEXT, has_timeline INT, game_creation_ts INT)")
        conn.execute("CREATE TABLE participants(match_id TEXT, participant_id INT, team_id INT, champion_name TEXT, team_position TEXT)")
        conn.execute("CREATE TABLE timeline_frames(match_id TEXT, participant_id INT, timestamp_ms INT, total_gold INT)")
        conn.execute("CREATE TABLE timeline_events(match_id TEXT, event_type TEXT, killer_id INT, victim_id INT, assisting_ids_json TEXT)")
        conn.execute("INSERT INTO matches VALUES('m1','CLASSIC',1,1)")
        # TOP lane: Garen (team100,pid1) vs Aatrox (team200,pid6). DB: Garen
        # good_against Aatrox -> claim A. Gold: Garen higher -> agree.
        conn.execute("INSERT INTO participants VALUES('m1',1,100,'Garen','TOP')")
        conn.execute("INSERT INTO participants VALUES('m1',6,200,'Aatrox','TOP')")
        conn.execute("INSERT INTO timeline_frames VALUES('m1',1,600000,5000)")
        conn.execute("INSERT INTO timeline_frames VALUES('m1',6,600000,3000)")
        conn.commit()
        return conn

    def test_full_pipeline_scores_a_decisive_agree(self):
        conn = self._db()
        try:
            pairs = pv.extract_lane_pairs(conn, "m1", 10)
            self.assertEqual(len(pairs), 1)
            p = pairs[0]
            self.assertEqual((p.champ_a, p.champ_b), ("Garen", "Aatrox"))
            claim = pv.db_claim(_targets(), p.champ_a, p.champ_b)
            self.assertEqual(claim, "A")
            self.assertEqual(pv.score_gold(p, claim), ("decisive", True))
        finally:
            conn.close()


class AsciiHygieneTests(unittest.TestCase):
    def test_tool_is_ascii(self):
        raw = Path(pv.__file__).read_bytes()
        self.assertEqual(raw.decode("ascii", "strict"), raw.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
