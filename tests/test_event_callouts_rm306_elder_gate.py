"""RM-306: Elder Dragon exists only after a team secures Dragon Soul.

Pre-fix ``next_callouts("sr", 2110.0, 16, 3, objective_events=[])`` returned
"Elder UP now - group for it" with ZERO drakes taken: elder was a flat
one-shot at a nominal 2100s, and the soul discriminator one line away
(_SOUL_SECURED_STACKS / _elemental_drake_counts) was never consulted.

Now the elder row is gated on a secured soul and timed from it (soul take +
_SR_ELDER_AFTER_SOUL_S, then Elder take + _SR_ELDER_RESPAWN_S). RM-307
interaction: when drake kills carry an "unknown" killer, sided counts
under-count, so the gate falls back to the TOTAL elemental count (four is
necessary for any soul) rather than suppressing Elder forever.

Mutation check: dropping the "elder" claim in _dynamic_epic_callouts makes
the zero-drake test fail.
"""
from __future__ import annotations

import unittest

from core import event_callouts as ec
from core.event_callouts import next_callouts


def _row(cs, tag):
    return next((c for c in cs if c.get("tag") == tag), None)


def _sr(t, events):
    return next_callouts("sr", t, 16, 3, max_n=99, objective_events=events)


def _drake(side, t, dtype="Fire"):
    return {"name": "dragon", "killer_team": side, "dragon_type": dtype,
            "down_at_s": t}


class ElderGate(unittest.TestCase):

    def test_no_elder_with_zero_drakes(self):
        self.assertIsNone(_row(_sr(2110.0, []), "elder"))

    def test_no_elder_without_event_data(self):
        self.assertIsNone(_row(_sr(2110.0, None), "elder"))

    def test_no_elder_on_split_drakes(self):
        evs = [_drake("ally", 300), _drake("enemy", 600), _drake("ally", 900),
               _drake("enemy", 1200), _drake("ally", 1500), _drake("enemy", 1800)]
        self.assertIsNone(_row(_sr(2400.0, evs), "elder"))

    def test_elder_up_after_four_same_side_drakes(self):
        evs = [_drake("ally", t) for t in (300.0, 700.0, 1100.0, 1500.0)]
        row = _row(_sr(2110.0, evs), "elder")
        self.assertIsNotNone(row)
        self.assertLessEqual(row["eta_s"], 0.0)
        self.assertEqual(row["line"], "Elder UP now - group for it")

    def test_elder_eta_counts_from_soul(self):
        evs = [_drake("enemy", t) for t in (300.0, 700.0, 1100.0, 1500.0)]
        row = _row(_sr(1600.0, evs), "elder")
        spawn = 1500.0 + ec._SR_ELDER_AFTER_SOUL_S
        self.assertAlmostEqual(row["eta_s"], spawn - 1600.0, places=1)

    def test_elder_respawn_after_elder_take(self):
        evs = [_drake("ally", t) for t in (300.0, 700.0, 1100.0, 1500.0)]
        evs.append(_drake("enemy", 2000.0, dtype="Elder"))
        row = _row(_sr(2100.0, evs), "elder")
        spawn = 2000.0 + ec._SR_ELDER_RESPAWN_S
        self.assertAlmostEqual(row["eta_s"], spawn - 2100.0, places=1)

    def test_unknown_killers_fall_back_to_total(self):
        # RM-307: unresolved KillerName must not suppress Elder forever.
        evs = [_drake("unknown", t) for t in (300.0, 700.0, 1100.0, 1500.0)]
        self.assertIsNotNone(_row(_sr(2110.0, evs), "elder"))

    def test_three_unknown_drakes_still_no_elder(self):
        evs = [_drake("unknown", t) for t in (300.0, 700.0, 1100.0)]
        self.assertIsNone(_row(_sr(2110.0, evs), "elder"))


if __name__ == "__main__":
    unittest.main()
