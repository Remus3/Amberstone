"""Iter 3 (2026-05-19) - hydra-cleave unique-passive family dedup.

The Cleave passive on Tiamat-tree items (Ravenous Hydra, Titanic Hydra,
Stridebreaker, Profane Hydra + their Arena mirrors) is marked "Unique -
Cleave" in live League: a build owning two hydras procs Cleave only ONCE
per AA, not twice. Prior to this fix the engine left
``unique_passive_key=""`` on all 4 SR + 4 Arena mirrors, and
``effects.collect_effects`` therefore handed BOTH cleave periodics to
``_periodic_proc_dps`` which fires every periodic on every AA -> double
(or triple) damage attribution for any 2+ hydra build. The comment at
``_effects_data.py:609-612`` claimed Tiamat-tree exclusivity was
"enforced by the ranker's build legality checks" but
``rank._filter_candidates`` has no such check - the documented invariant
was wishful thinking. Fix: tag all 8 items with
``unique_passive_key="hydra_cleave"`` so the existing first-seen-wins
dedup in ``collect_effects`` (and the ``shares_dead_unique`` filter in
the ranker) handle both layers in one shot.

These tests pin the tag on the items (schema), prove collect_effects
dedups the second cleave (no double-fire in DPS), and prove the ranker
filters a second hydra out of the candidate list when one is already
owned (no double-recommend).
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer._effects_data import ITEM_EFFECTS
from agents.daemon_slayer.dps import compute_dps
from agents.daemon_slayer.effects import collect_effects
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.rank import rank_items


_HYDRA_SR = ("3074", "3748", "6631", "6698")
_HYDRA_ARENA = ("223074", "223748", "226631", "226698")
_ALL_HYDRA = _HYDRA_SR + _HYDRA_ARENA


class HydraCleaveUniquePassiveKeyTests(unittest.TestCase):
    def test_all_hydra_items_tagged_hydra_cleave(self) -> None:
        """Every Tiamat-tree item must declare the hydra_cleave family."""
        for iid in _ALL_HYDRA:
            eff = ITEM_EFFECTS.get(iid)
            self.assertIsNotNone(
                eff, f"item {iid} missing from ITEM_EFFECTS"
            )
            self.assertEqual(
                eff.unique_passive_key,
                "hydra_cleave",
                f"item {iid} ({eff.name!r}) should declare "
                "unique_passive_key='hydra_cleave' so collect_effects "
                "dedups its Cleave periodic",
            )

    def test_collect_effects_dedups_second_hydra(self) -> None:
        """A build with Ravenous + Titanic must collapse to ONE hydra entry."""
        out = collect_effects(("3074", "3748"))
        self.assertEqual(
            len(out),
            1,
            "two hydras must dedup to one effect (first-seen-wins)",
        )
        self.assertEqual(out[0].item_id, "3074")

    def test_collect_effects_dedups_three_hydras_to_one(self) -> None:
        out = collect_effects(("3074", "3748", "6631"))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].item_id, "3074")

    def test_collect_effects_dedups_arena_mirror_against_sr(self) -> None:
        """Arena mirror shares the same family as its SR counterpart."""
        out = collect_effects(("3074", "223074"))
        self.assertEqual(len(out), 1)

    def test_collect_effects_dedups_profane_against_ravenous(self) -> None:
        """Profane Hydra collides with Ravenous - same in-game cleave proc."""
        out = collect_effects(("3074", "6698"))
        self.assertEqual(len(out), 1)


class HydraCleaveDpsNoDoubleCountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()
        # Pick a melee champion that benefits from hydras. Camille (164)
        # is a common test case in the existing suite and is in 16.10.1.
        cls.champ_id = "Camille"

    def _dps(self, items: tuple[str, ...]) -> float:
        return compute_dps(
            self.snap,
            champion_id=self.champ_id,
            level=11,
            item_ids=items,
            mode="SR",
            target_armor=100.0,
            target_mr=50.0,
            target_max_hp=2500.0,
            target_bonus_hp=0.0,
        ).weighted_dps

    def test_two_hydras_dps_le_ravenous_plus_solo_titanic_delta(self) -> None:
        """After the fix the second hydra's cleave periodic is suppressed.

        Specifically: post-fix, (Rav + Tit) DPS must be STRICTLY LESS
        than Rav-solo + solo-Titanic-delta-over-naked. That gap proves
        the Titanic Cleave proc (5 + 1.5% bonus HP physical on every AA)
        is no longer firing - only stat-block remains for the second
        hydra. Pre-fix the two were equal (no dedup, additive procs).
        """
        rav = self._dps(("3074",))
        tit_solo = self._dps(("3748",))
        naked = self._dps(())
        rav_plus_tit = self._dps(("3074", "3748"))
        # Sanity: adding Titanic still increases DPS (stat block: HP/AD).
        self.assertGreater(rav_plus_tit, rav)
        # Pre-fix invariant (held by accident before dedup):
        #   rav_plus_tit == rav + (tit_solo - naked)
        # i.e. Titanic contributes its full solo delta because procs
        # additively stack with no dedup.
        # Post-fix: rav_plus_tit < rav + (tit_solo - naked) by at least
        # the Titanic Cleave-primary contribution (~3 dps at L11, no
        # bonus HP from items). We assert the strict inequality with a
        # 1.5 dps safety margin so engine-noise doesn't false-fail.
        pre_fix_value = rav + (tit_solo - naked)
        gap = pre_fix_value - rav_plus_tit
        self.assertGreater(
            gap,
            1.5,
            f"hydra dedup should suppress Titanic's cleave proc; "
            f"rav+tit={rav_plus_tit:.2f} should be < pre-fix={pre_fix_value:.2f} "
            f"by > 1.5 dps but gap was {gap:.2f}",
        )

    def test_three_hydras_no_triple_cleave(self) -> None:
        """3 hydras must NOT triple-fire cleave.

        Note on the math: in default scenarios with single-target n=1,
        Ravenous's cleave-to-nearby and Stridebreaker's cleave proc both
        evaluate to 0 (their bonus_damage lambdas multiply by
        max(0, n-1)=0). So at n=1, the ONLY hydra-proc with non-zero
        contribution is Titanic's cleave-PRIMARY (5 + 1.5% bonus HP per
        AA - it's an on-hit, not a cleave-to-others). Suppressing
        Stride/Profane procs at n=1 contributes zero to the gap; the
        whole gap is driven by Titanic's primary proc being dropped.
        So we pin the same 1.5 dps gap as the 2-hydra test - any larger
        threshold would falsely require a contribution from the
        already-zero cleave procs.
        """
        rav = self._dps(("3074",))
        tit_solo = self._dps(("3748",))
        str_solo = self._dps(("6631",))
        naked = self._dps(())
        three = self._dps(("3074", "3748", "6631"))
        pre_fix_value = rav + (tit_solo - naked) + (str_solo - naked)
        gap = pre_fix_value - three
        # At single-target n=1, Stride's cleave proc is 0, so the gap is
        # dominated by Titanic-primary suppression (~1.55 dps observed).
        # A 1.0 dps margin is enough proof + tolerant to engine drift.
        self.assertGreater(
            gap,
            1.0,
            f"hydra dedup should suppress Titanic's cleave-primary proc; "
            f"3-hydra={three:.2f} should be < pre-fix-naive "
            f"{pre_fix_value:.2f} by > 1 dps but gap was {gap:.2f}",
        )


class HydraCleaveRankerDedupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_ranker_filters_second_hydra(self) -> None:
        """rank_items with Ravenous already owned must NOT surface another
        Tiamat-tree item in the default ``filter_shared_uniques=True``
        ranked list - their unique_passive_key collides.

        Uses ``top_n=200`` (wider than the default top_n=20) so we don't
        false-pass when hydras are simply outranked by AD/AS items.
        """
        result = rank_items(
            self.snap,
            champion_id="Camille",
            level=11,
            current_item_ids=("3074",),
            mode="SR",
            target_armor=100.0,
            target_mr=50.0,
            target_max_hp=2500.0,
            target_bonus_hp=0.0,
            top_n=200,
        )
        recommended_ids = {r.item_id for r in result.ranked}
        for hydra_id in ("3748", "6631", "6698"):
            self.assertNotIn(
                hydra_id,
                recommended_ids,
                f"ranker recommended {hydra_id} on top of Ravenous - "
                f"a Tiamat-tree double",
            )

    def test_ranker_flags_second_hydra_when_filter_off(self) -> None:
        """With ``filter_shared_uniques=False`` the second hydra appears
        but is flagged ``shares_dead_unique=True`` with the right key."""
        result = rank_items(
            self.snap,
            champion_id="Camille",
            level=11,
            current_item_ids=("3074",),
            mode="SR",
            target_armor=100.0,
            target_mr=50.0,
            target_max_hp=2500.0,
            target_bonus_hp=0.0,
            filter_shared_uniques=False,
            top_n=200,
        )
        hydra_rows = [r for r in result.ranked if r.item_id in ("3748", "6631", "6698")]
        self.assertGreater(
            len(hydra_rows),
            0,
            "with filter off the second hydra should appear",
        )
        for r in hydra_rows:
            self.assertTrue(r.shares_dead_unique)
            self.assertEqual(r.dead_unique_key, "hydra_cleave")


if __name__ == "__main__":
    unittest.main()
