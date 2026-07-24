"""R181 ds-sweep-lifesteal - Lifesteal / SpellVamp / Omnivamp drift-guard.

Locks the VERIFIED-CLEAN outcome of the R181 sweep (extends R165 ds-sweep-
sustain from "vamp is modeled + EHP-credited" to "the exact base magnitudes +
doctrine-B mode mirrors of the six headline vamp items hold"). Ground truth =
DDragon ``data/daemon_slayer/16.14.1/items.json`` via ``DataSnapshot``; Meraki's
flat ``stats`` blocks are empty for these items (vamp is conditional/percent),
so DDragon is authoritative for the base-stat magnitudes.

Contract pinned here (all VERIFIED-TRUE at write time):
  * Base-stat plumbing: ITEM_STAT_KEY_MAP routes ``PercentLifeStealMod`` ->
    ("lifesteal","pct") and ``PercentSpellVampMod`` -> ("spellvamp","pct")
    (stats.py:110-111). ``aggregate_item_stats`` sums each item's OWN block, so
    every Arena/ARAM mirror credits its own DDragon line by construction
    (R161 doctrine B is STRUCTURAL, not per-item wiring).
  * Lifesteal magnitudes + deliberately-divergent Arena spreads:
    Bloodthirster 3072=0.15 / 223072=0.18, Ravenous Hydra 3074=0.12 /
    223074=0.15, Blade of the Ruined King 3153=0.10 / 223153=0.10.
  * SpellVamp is INERT this patch: ZERO ``PercentSpellVampMod`` carriers across
    the whole 706-item index (legacy stat, mapped but unused - like mana-regen
    in R171). Nothing to mismatch.
  * The AP/hybrid vamp items carry NO base vamp stat - Riftmaker 4633, Immortal
    Shieldbow 6673 and Maw of Malmortius 3156 expose neither PercentLifeStealMod
    nor PercentSpellVampMod; their sustain (if any) is a PASSIVE, not a base
    magnitude the aggregator owes.
  * Omnivamp is a PASSIVE registry (``_item_omnivamp.py``), NOT a base stat
    (DDragon has no omnivamp key; Meraki flat block is 0.0). The registry is
    deliberately narrow: Riftmaker 4633 + Arena mirror 224633 are always-on
    max-stacks grants and ARE registered; Maw 3156 (Lifeline shield, not
    omnivamp) and Endless Hunger 2517 (takedown-gated) are deliberately EXCLUDED.
    This test pins that boundary so a future edit cannot silently fold a
    conditional-gated id into the always-on registry.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.stats import ITEM_STAT_KEY_MAP, aggregate_item_stats
from agents.daemon_slayer._item_omnivamp import _ITEM_OMNIVAMP


class _SnapBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _lifesteal_pct(self, item_id: str) -> float:
        block = self.snap.item(item_id).get("stats", {})
        return aggregate_item_stats([block]).get("lifesteal_pct", 0.0)

    def _spellvamp_pct(self, item_id: str) -> float:
        block = self.snap.item(item_id).get("stats", {})
        return aggregate_item_stats([block]).get("spellvamp_pct", 0.0)


# ---------------- mapping identity ----------------


class VampStatMappingTests(unittest.TestCase):
    def test_lifesteal_key_maps_to_lifesteal_pct(self) -> None:
        self.assertEqual(ITEM_STAT_KEY_MAP["PercentLifeStealMod"], ("lifesteal", "pct"))

    def test_spellvamp_key_maps_to_spellvamp_pct(self) -> None:
        self.assertEqual(ITEM_STAT_KEY_MAP["PercentSpellVampMod"], ("spellvamp", "pct"))


# ---------------- lifesteal magnitudes + doctrine-B mirrors ----------------


class LifestealMagnitudeTests(_SnapBase):
    def test_bloodthirster_base_is_fifteen_percent(self) -> None:
        self.assertAlmostEqual(self._lifesteal_pct("3072"), 0.15, places=9)

    def test_bloodthirster_arena_mirror_is_eighteen_percent(self) -> None:
        # Arena credits its OWN DDragon line (doctrine B) - divergent from base.
        self.assertAlmostEqual(self._lifesteal_pct("223072"), 0.18, places=9)

    def test_ravenous_hydra_base_is_twelve_percent(self) -> None:
        self.assertAlmostEqual(self._lifesteal_pct("3074"), 0.12, places=9)

    def test_ravenous_hydra_arena_mirror_is_fifteen_percent(self) -> None:
        self.assertAlmostEqual(self._lifesteal_pct("223074"), 0.15, places=9)

    def test_botrk_base_is_ten_percent(self) -> None:
        self.assertAlmostEqual(self._lifesteal_pct("3153"), 0.10, places=9)

    def test_botrk_arena_mirror_matches_base(self) -> None:
        self.assertAlmostEqual(self._lifesteal_pct("223153"), 0.10, places=9)

    def test_arena_mirror_reads_its_own_line_not_the_base(self) -> None:
        # Doctrine B is structural: the divergent items prove the aggregator does
        # NOT alias the mirror onto the base magnitude.
        self.assertNotAlmostEqual(
            self._lifesteal_pct("3072"), self._lifesteal_pct("223072"), places=9
        )
        self.assertNotAlmostEqual(
            self._lifesteal_pct("3074"), self._lifesteal_pct("223074"), places=9
        )


# ---------------- spellvamp inert ----------------


class SpellVampInertTests(_SnapBase):
    def test_no_item_carries_a_spellvamp_stat(self) -> None:
        carriers = [
            iid
            for iid, rec in self.snap.items.items()
            if "PercentSpellVampMod" in (rec.get("stats") or {})
        ]
        self.assertEqual(carriers, [])


# ---------------- AP/hybrid vamp items carry no base vamp ----------------


class ApVampItemsHaveNoBaseVampTests(_SnapBase):
    def test_riftmaker_has_no_base_lifesteal_or_spellvamp(self) -> None:
        self.assertEqual(self._lifesteal_pct("4633"), 0.0)
        self.assertEqual(self._spellvamp_pct("4633"), 0.0)

    def test_immortal_shieldbow_has_no_base_lifesteal_or_spellvamp(self) -> None:
        self.assertEqual(self._lifesteal_pct("6673"), 0.0)
        self.assertEqual(self._spellvamp_pct("6673"), 0.0)

    def test_maw_of_malmortius_has_no_base_lifesteal_or_spellvamp(self) -> None:
        self.assertEqual(self._lifesteal_pct("3156"), 0.0)
        self.assertEqual(self._spellvamp_pct("3156"), 0.0)


# ---------------- omnivamp passive-registry boundary ----------------


class OmnivampRegistryBoundaryTests(unittest.TestCase):
    def test_riftmaker_and_arena_mirror_are_registered(self) -> None:
        self.assertIn("4633", _ITEM_OMNIVAMP)
        self.assertIn("224633", _ITEM_OMNIVAMP)

    def test_conditional_gated_ids_stay_excluded(self) -> None:
        # Maw 3156 (Lifeline shield, not omnivamp) + Endless Hunger 2517
        # (takedown-gated) are deliberately NOT always-on omnivamp - keep them out.
        self.assertNotIn("3156", _ITEM_OMNIVAMP)
        self.assertNotIn("2517", _ITEM_OMNIVAMP)


if __name__ == "__main__":
    unittest.main()
