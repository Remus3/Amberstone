"""RM-305: Baron / Rift Herald / Elder PERSIST on the map until taken.

`_objective_callouts` dropped every one-shot once ``eta < -30s``, which is
right for ``plates`` (a past event) and wrong for an epic monster that stands
in its pit until somebody kills it. Measured pre-fix: with no Baron take, the
baron row was present at t=1200 and t=1230 and ABSENT from t=1260 on, so the
first Baron - the one worth pre-warning - was called for a 30-second slice
of a 20-plus-minute window.

Mutation check: restoring the ``eta < -active_window`` drop for baron makes
``test_baron_still_up_at_1500_with_no_take`` fail.
"""
from __future__ import annotations

import unittest

from core import event_callouts as ec
from core.event_callouts import next_callouts


def _row(cs, tag):
    return next((c for c in cs if c.get("tag") == tag), None)


def _sr(t, events=None):
    return next_callouts("sr", t, 16, 3, max_n=99, objective_events=events)


class BaronPersists(unittest.TestCase):

    def test_baron_still_up_at_1500_with_no_take(self):
        row = _row(_sr(1500.0, []), "baron")
        self.assertIsNotNone(row)
        self.assertEqual(row["line"], "Baron UP now - contest with vision")
        self.assertAlmostEqual(row["eta_s"], -300.0, places=1)

    def test_baron_up_across_the_window(self):
        for t in (1200.0, 1260.0, 1400.0, 1800.0, 2400.0):
            row = _row(_sr(t, []), "baron")
            self.assertIsNotNone(row, t)
            self.assertLessEqual(row["eta_s"], 0.0, t)

    def test_baron_persists_when_event_data_is_absent(self):
        # Baron's first spawn is a fixed fact; no take can be inferred from
        # missing data, and the only alternative is silence on a standing
        # Baron, so the no-data branch keeps it up too.
        self.assertIsNotNone(_row(_sr(1500.0, None), "baron"))

    def test_take_retires_then_respawn_timer(self):
        ev = [{"name": "baron", "killer_team": "ally", "down_at_s": 1300.0}]
        row = _row(_sr(1500.0, ev), "baron")
        self.assertAlmostEqual(row["eta_s"], 160.0, places=1)


class HeraldPersistsUntilTakenOrDespawn(unittest.TestCase):

    def test_herald_up_at_900(self):
        row = _row(_sr(900.0, []), "herald")
        self.assertIsNotNone(row)
        self.assertLessEqual(row["eta_s"], 0.0)

    def test_herald_take_retires_it(self):
        ev = [{"name": "herald", "killer_team": "enemy", "down_at_s": 870.0}]
        self.assertIsNone(_row(_sr(900.0, ev), "herald"))

    def test_herald_gone_after_despawn(self):
        self.assertIsNone(_row(_sr(ec._SR_HERALD_DESPAWN_S + 1.0, []), "herald"))


class PlatesStayOneShot(unittest.TestCase):

    def test_plates_dropped_long_after(self):
        self.assertIsNone(_row(_sr(1500.0, []), "plates"))


class DrakeWindowUnchanged(unittest.TestCase):

    def test_active_window_constant_not_widened(self):
        self.assertEqual(ec._OBJ_ACTIVE_WINDOW_S, 30.0)


if __name__ == "__main__":
    unittest.main()
