"""RM-308: duplicate inhibitor rows, and the drake row's data honesty.

(a) Both teams own a top inhibitor and the inhibitor tag is side-less, so
``Barracks_T1_L1`` down at 1000 plus ``Barracks_T2_L1`` down at 1010, read at
1020, returned two ``inhib_top`` rows with identical text. Now one row per
tag, soonest respawn kept.

(b) With no take observed, ``next_callouts("sr", 1000.0, ...)`` said "Drake
spawns 5:00 - set up vision" at eta 200 although the drake had stood since
300s (drakes respawn 5:00 after a TAKE, not on a game-start grid). Decision:
``objective_events`` as a list (even []) is event DATA, so "no take" is a
fact and the drake is UP since 300; ``None`` is NO DATA, so past the
just-spawned window the row is silent. The producers keep the two apart:
dashboard/_liveclient emits None on a failed read, and
dashboard/_deterministic_coaching stamps an empty list instead of dropping it.
"""
from __future__ import annotations

import unittest

from core.event_callouts import inhibitor_callouts, next_callouts


def _row(cs, tag):
    return next((c for c in cs if c.get("tag") == tag), None)


class InhibitorDedupe(unittest.TestCase):

    def test_two_top_inhibs_one_row_soonest_eta(self):
        ev = [{"name": "Barracks_T1_L1", "down_at_s": 1000.0},
              {"name": "Barracks_T2_L1", "down_at_s": 1010.0}]
        rows = inhibitor_callouts(ev, 1020.0)
        self.assertEqual([r["tag"] for r in rows], ["inhib_top"])
        self.assertAlmostEqual(rows[0]["eta_s"], 280.0, places=1)

    def test_order_independent(self):
        ev = [{"name": "Barracks_T2_L1", "down_at_s": 1010.0},
              {"name": "Barracks_T1_L1", "down_at_s": 1000.0}]
        rows = inhibitor_callouts(ev, 1020.0)
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["eta_s"], 280.0, places=1)

    def test_different_lanes_stay_separate(self):
        ev = [{"name": "Barracks_T1_L1", "down_at_s": 1000.0},
              {"name": "Barracks_T1_C1", "down_at_s": 1000.0}]
        tags = sorted(r["tag"] for r in inhibitor_callouts(ev, 1020.0))
        self.assertEqual(tags, ["inhib_mid", "inhib_top"])

    def test_panel_not_double_spent(self):
        ev = [{"name": "Barracks_T1_L1", "down_at_s": 1000.0},
              {"name": "Barracks_T2_L1", "down_at_s": 1010.0}]
        cs = next_callouts("sr", 1020.0, 13, 3, max_n=99, inhib_events=ev)
        self.assertEqual(sum(1 for c in cs if c["tag"] == "inhib_top"), 1)


class DrakeRowHonesty(unittest.TestCase):

    def test_data_no_takes_drake_up_since_first_spawn(self):
        row = _row(next_callouts("sr", 1000.0, 11, 2, max_n=99,
                                 objective_events=[]), "dragon")
        self.assertIsNotNone(row)
        self.assertEqual(row["line"], "Drake UP now - contest or trade")
        self.assertAlmostEqual(row["eta_s"], -700.0, places=1)

    def test_no_data_drake_row_silent(self):
        cs = next_callouts("sr", 1000.0, 11, 2, max_n=99, objective_events=None)
        self.assertIsNone(_row(cs, "dragon"))

    def test_no_false_spawns_claim_in_either_branch(self):
        for evs in ([], None):
            cs = next_callouts("sr", 1000.0, 11, 2, max_n=99,
                               objective_events=evs)
            for c in cs:
                self.assertNotIn("Drake spawns", c["line"], evs)

    def test_first_spawn_eta_is_fact_in_both_branches(self):
        for evs in ([], None):
            row = _row(next_callouts("sr", 240.0, 5, 0, max_n=99,
                                     objective_events=evs), "dragon")
            self.assertAlmostEqual(row["eta_s"], 60.0, places=1)

    def test_just_spawned_window_active_without_data(self):
        row = _row(next_callouts("sr", 305.0, 6, 1, max_n=99), "dragon")
        self.assertLessEqual(row["eta_s"], 0.0)


class ProducersKeepTheBranchesApart(unittest.TestCase):

    def test_deterministic_coaching_stamps_empty_list(self):
        from dashboard import _deterministic_coaching as dc
        gs = dc._build_game_state({"champion": "Aatrox"},
                                  {"objective_events": []}, "sr")
        self.assertEqual(gs.get("objective_events"), [])

    def test_liveclient_no_events_list_is_no_data(self):
        from tests.test_liveclient_objective_events import (
            _PLAYERS, _allgamedata, _summary)
        agd = _allgamedata("Ashe", _PLAYERS, [])
        agd["events"] = {"Events": "garbled"}
        self.assertIsNone(_summary(agd)["objective_events"])
        self.assertEqual(
            _summary(_allgamedata("Ashe", _PLAYERS, []))["objective_events"], [])

    def test_deterministic_coaching_omits_no_data(self):
        from dashboard import _deterministic_coaching as dc
        gs = dc._build_game_state({"champion": "Aatrox"}, {}, "sr")
        self.assertNotIn("objective_events", gs)


if __name__ == "__main__":
    unittest.main()
