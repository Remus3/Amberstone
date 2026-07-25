"""RM-94: Mejai's Soulstealer must carry an EXPECTED stack count, not the peak.

Batch 54 pinned ``ITEM_EFFECTS["3041"].bonus_ap_stacked`` at 125.0 - the value
of 25 Glory stacks, the item's hard cap - and justified it with the
"sustained-peak convention" already used for Black Cleaver's full-stack armor
reduction and Riftmaker's full ramp. That citation is a category error, and the
in-repo sibling registry says so out loud:
``_item_health_stack.py`` builds a deliberately LOW assumed-accrual curve and
names "the RM-94 Mejai's failure mode (pinned at MAX stacks, so it ranks #6 for
every mage at 2-5% real presence)" as the exact thing that curve exists to
avoid. This module is the regression fence for the correction.

THE COMPARABILITY VERDICT (the crux):
  * Black Cleaver / Riftmaker accrue from the CASTER'S OWN combat output inside
    a single fight, saturate in a few seconds, and reset out of combat. The
    modelled rotation itself generates every stack, so the full-stack value IS
    the steady state of the thing being simulated.
  * Mejai's Glory accrues from TAKEDOWNS across the whole game and 10 stacks are
    destroyed on each death (DDragon 16.14.1 3041: "Takedowns grant Glory, up to
    25. 10 Glory is lost on death. Gain 5 Ability Power per Glory"). No rotation
    the engine simulates can produce a single stack. Full stacks is a GAME-STATE
    PRECONDITION - already having won - not a combat steady state.

THE CONSTANT. The per-stack AP is EXACT and sourced (5 AP, DDragon 16.14.1); the
STACK COUNT is the single judgement number, exactly as ``_item_health_stack.py``
frames its proc curve. It is bounded ABOVE by the item's own design threshold:
Riot grants the move-speed bonus "at 10 or higher Glory", i.e. 10 is where the
item itself declares you are ahead, and 10 is also the single-death penalty, so
any sustained count at or above 10 presumes the snowball has already happened.
The assumed count is therefore the midpoint of the not-yet-ahead band 0..10 = 5
stacks -> 25.0 AP. Midpoint-of-band matches the other ``bonus_ap_stacked``
occupant (Innervating Locket 447104 = 175.0, the midpoint of its 100-250 range),
so both users of the field now express an EXPECTED value rather than a peak.
"""

from __future__ import annotations

import unittest

from agents.daemon_slayer._effects_data import ITEM_EFFECTS
from agents.daemon_slayer._rank_mage import rank_items_by_ability_dps
from agents.daemon_slayer.data_loader import DataSnapshot

# Sourced from DDragon 16.14.1 items.json entry 3041.
AP_PER_GLORY_STACK = 5.0
GLORY_CAP_STACKS = 25.0
GLORY_LOST_ON_DEATH = 10.0
# Assumed sustained stacks - the one judgement number in this lane.
EXPECTED_GLORY_STACKS = 5.0


class MejaisExpectedStackConstantTests(unittest.TestCase):
    """The registry constant itself."""

    def test_bonus_ap_stacked_is_expected_value(self) -> None:
        eff = ITEM_EFFECTS["3041"]
        self.assertAlmostEqual(
            eff.bonus_ap_stacked, EXPECTED_GLORY_STACKS * AP_PER_GLORY_STACK
        )

    def test_no_longer_pinned_at_the_full_stack_peak(self) -> None:
        eff = ITEM_EFFECTS["3041"]
        self.assertLess(eff.bonus_ap_stacked, GLORY_CAP_STACKS * AP_PER_GLORY_STACK)

    def test_assumed_stacks_stay_under_the_death_penalty(self) -> None:
        """A count at or above 10 presumes a snowball that has already landed.

        10 is simultaneously the single-death stack loss and the threshold Riot
        attaches the move-speed bonus to. Below it the item is not yet claiming
        the player is ahead, which is the only regime a simulation with no
        takedown feed is entitled to assume.
        """
        eff = ITEM_EFFECTS["3041"]
        stacks = eff.bonus_ap_stacked / AP_PER_GLORY_STACK
        self.assertGreater(stacks, 0.0)
        self.assertLess(stacks, GLORY_LOST_ON_DEATH)

    def test_still_an_active_contributor(self) -> None:
        """The fix is a re-valuation, not a demotion to defensive_only."""
        eff = ITEM_EFFECTS["3041"]
        self.assertFalse(eff.defensive_only)
        self.assertGreater(eff.bonus_ap_stacked, 0.0)


class MejaisStackedApSiblingSweepTests(unittest.TestCase):
    """Every other full-stack / full-ramp AP pin, adjudicated.

    ``bonus_ap_stacked`` has exactly two occupants in the registry. The sweep
    result is recorded here so a later patch cannot silently re-open it.
    """

    def test_dark_seal_carries_no_stacked_ap_pin(self) -> None:
        """1082 Dark Seal is the obvious sibling and is NOT affected.

        It is the same Glory passive at a smaller cap (up to 10 stacks, 5 lost
        on death, 4 AP per stack -> a 40 AP peak), but the engine models it as
        stats-only and never credited the ramp at all. It UNDER-states rather
        than over-states, so the RM-94 reasoning does not apply and widening the
        pin to it would introduce the defect this slice removes.
        """
        eff = ITEM_EFFECTS["1082"]
        self.assertAlmostEqual(eff.bonus_ap_stacked, 0.0)

    def test_innervating_locket_keeps_its_midpoint(self) -> None:
        """447104 is the only other occupant and is NOT the same failure mode.

        Fill the Soul charges accrue from the caster's AND allies' casts inside
        an Arena round, carry no death penalty, and the registry already stores
        the MIDPOINT of the item's 100-250 level range rather than its peak. It
        is already an expected value, so it is left alone.
        """
        eff = ITEM_EFFECTS["447104"]
        self.assertAlmostEqual(eff.bonus_ap_stacked, 175.0, places=1)

    def test_stacked_ap_field_has_no_other_occupants(self) -> None:
        occupied = sorted(
            iid for iid, e in ITEM_EFFECTS.items() if e.bonus_ap_stacked > 0.0
        )
        self.assertEqual(occupied, ["3041", "447104"])


class MejaisMageRankDemotionTests(unittest.TestCase):
    """The pin bought Mejai's a slot it does not deserve; it must give it back.

    Probed on the MAGE archetype route (``rank_items_by_ability_dps``, the
    ``/rank-mage`` scorer) at realistic build depth with non-zero target state -
    the generic carry route and an empty build both manufacture wrong numbers.
    The pool is whitelisted to Mejai's plus the items that surrounded it in the
    measured pre-fix ordering so the assertion is cheap and unambiguous.
    """

    snap: DataSnapshot

    # The measured pre-fix mage head plus Mejai's and its immediate neighbours.
    POOL = [
        "2503", "3135", "4645", "3089", "4646",
        "667112", "3137", "8010", "3041", "4633", "3102",
    ]
    BUILD = ["6653", "3020"]   # Liandry's Torment + Sorcerer's Shoes

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _ranks(self, champion_id: str) -> dict[str, int]:
        res = rank_items_by_ability_dps(
            self.snap, champion_id, level=13,
            current_item_ids=self.BUILD, mode="SR",
            target_armor=60.0, target_mr=50.0,
            target_max_hp=2200.0, target_bonus_hp=1200.0,
            only_item_ids=self.POOL, top_n=200,
        )
        return {r.item_id: i for i, r in enumerate(res.ranked, start=1)}

    def test_mejais_ranks_below_riftmaker_on_lux(self) -> None:
        ranks = self._ranks("Lux")
        self.assertIn("3041", ranks)
        self.assertIn("4633", ranks)
        self.assertGreater(ranks["3041"], ranks["4633"])

    def test_mejais_ranks_below_riftmaker_on_xerath(self) -> None:
        ranks = self._ranks("Xerath")
        self.assertIn("3041", ranks)
        self.assertIn("4633", ranks)
        self.assertGreater(ranks["3041"], ranks["4633"])


if __name__ == "__main__":
    unittest.main()
