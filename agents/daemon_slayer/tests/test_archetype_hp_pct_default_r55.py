"""R55 - engine plumbing of the target_current_hp_pct seam into the CARRY and
BRUISER scorers.

The seam (item 374) scales ONLY the three genuine %-CURRENT-HP procs (BotRK
3153 / Hellfire 4017 / Fulmination 443055). Before R55 the seam reached only
the mage + assassin scorers; R55 plumbs it into the CARRY (rank_items) and
BRUISER (rank_items_by_hybrid) scorers too. The archetype-aware DEFAULT resolver
+ the dispatcher flag live in ``core`` (client side) and are tested in
tests/test_archetype_hp_pct_dispatcher_r55.py - this file covers only the engine
math plumbing.

Isolation method mirrors test_target_current_hp_pct_lever.py: a single-item
candidate whitelist (only_item_ids) yields exactly one ranked row, and we
difference that row's delta_dps across two lever values. The %-current-HP proc
DPS drops when the target's assumed current HP is lower, so the 1.0 vs 0.5
delta is strictly positive; the %-MAX-HP proc (Eclipse) is invariant.
"""

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.rank import rank_items
from agents.daemon_slayer.hybrid import rank_items_by_hybrid


_CHAMP = "Aatrox"          # melee sustained fighter - no ranged divergence
_LEVEL = 11
_TARGET_MAX_HP = 3000.0
_BOTRK = "3153"            # %-CURRENT-HP proc (must move with the lever)
_ECLIPSE = "6692"          # %-MAX-HP proc (must NOT move with the lever)


def _only_row_delta(result, item_id):
    """delta_dps of the single ranked row for a one-item whitelist.

    ``only_item_ids=[item_id]`` restricts the candidate pool so exactly one
    row is produced; return its delta_dps.
    """
    rows = result.ranked
    matches = [r for r in rows if r.item_id == item_id]
    assert len(matches) == 1, f"expected exactly 1 row for {item_id}, got {len(rows)}"
    return matches[0].delta_dps


class CarryRankItemsPlumbingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def _rank_botrk(self, hp_pct=None):
        kwargs = dict(
            level=_LEVEL, only_item_ids=[_BOTRK],
            target_max_hp=_TARGET_MAX_HP,
        )
        if hp_pct is not None:
            kwargs["target_current_hp_pct"] = hp_pct
        return rank_items(self.snap, _CHAMP, **kwargs)

    def _only_row_delta_default(self):
        return _only_row_delta(self._rank_botrk(None), _BOTRK)

    def test_default_is_byte_identical(self):
        base = self._only_row_delta_default()
        explicit_one = _only_row_delta(self._rank_botrk(1.0), _BOTRK)
        self.assertEqual(base, explicit_one)

    def test_botrk_delta_drops_when_lever_lower(self):
        full = _only_row_delta(self._rank_botrk(1.0), _BOTRK)
        half = _only_row_delta(self._rank_botrk(0.5), _BOTRK)
        self.assertGreater(full - half, 0.0)

    def test_eclipse_max_hp_row_invariant(self):
        def rank_eclipse(hp_pct):
            return rank_items(
                self.snap, _CHAMP, level=_LEVEL, only_item_ids=[_ECLIPSE],
                target_max_hp=_TARGET_MAX_HP, target_current_hp_pct=hp_pct,
            )
        full = _only_row_delta(rank_eclipse(1.0), _ECLIPSE)
        half = _only_row_delta(rank_eclipse(0.5), _ECLIPSE)
        self.assertEqual(full, half)


class BruiserRankHybridPlumbingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def _rank_botrk(self, hp_pct=None):
        kwargs = dict(
            level=_LEVEL, only_item_ids=[_BOTRK],
            target_max_hp=_TARGET_MAX_HP,
        )
        if hp_pct is not None:
            kwargs["target_current_hp_pct"] = hp_pct
        return rank_items_by_hybrid(self.snap, _CHAMP, **kwargs)

    def _delta_dps(self, result):
        rows = result.ranked
        matches = [r for r in rows if r.item_id == _BOTRK]
        assert len(matches) == 1
        return matches[0].delta_dps

    def test_default_is_byte_identical(self):
        base = self._delta_dps(self._rank_botrk(None))
        explicit_one = self._delta_dps(self._rank_botrk(1.0))
        self.assertEqual(base, explicit_one)

    def test_botrk_delta_drops_when_lever_lower(self):
        full = self._delta_dps(self._rank_botrk(1.0))
        half = self._delta_dps(self._rank_botrk(0.5))
        self.assertGreater(full - half, 0.0)


if __name__ == "__main__":
    unittest.main()
