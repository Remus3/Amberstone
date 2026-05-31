"""DS V2 slice S1 - ability_hps wired into the live enchanter HPS scorer.

``compute_hps`` (hps.py) historically scored ONLY curated ENCHANTER ITEM
throughput and explicitly omitted champion-spell heals/shields. V2 folds
``compute_ability_hps`` (ability_hps.py) into ``total_throughput`` so an
enchanter's own kit counts (Soraka W, Lulu E shield, Janna E shield, ...).

These tests pin the wire contract:
  (a) a heal champion (Soraka) shows ability_hps_total > 0 and
      total_throughput == direct + buff + ability_hps_total
  (b) a non-heal champion (Caitlyn) shows ability_hps_total == 0.0 and
      total_throughput byte-identical to a manual direct+buff sum
  (c) an enchanter with items shows BOTH item and ability contributions
  (d) ARAM aramHealing/aramShielding still folds correctly

NO ENGINE_VERSION assertion here - the orchestrator owns the version bump.
"""

from __future__ import annotations

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.hps import HpsResult, compute_hps


class AbilityHpsWireTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    # --- (a) heal champion: ability HPS present and folded into total ---

    def test_soraka_ability_hps_present_and_folded(self) -> None:
        r = compute_hps(self.snap, "Soraka", level=11, mode="SR")
        self.assertIsInstance(r, HpsResult)
        # Soraka has ability heal blocks at the current snapshot.
        self.assertGreater(r.ability_hps_total, 0.0)
        # total_throughput == direct + buff + ability_hps_total exactly.
        self.assertAlmostEqual(
            r.total_throughput,
            r.direct_throughput + r.ally_buff_credit + r.ability_hps_total,
            places=9,
        )
        # The 3 V2 fields are internally consistent.
        self.assertAlmostEqual(
            r.ability_hps_total,
            r.ability_heal_hps + r.ability_shield_hps,
            places=9,
        )

    def test_soraka_itemless_total_equals_ability_hps(self) -> None:
        # Itemless Soraka: no item direct, no buff -> total is purely the
        # ability heal/shield throughput (the V2 contribution in isolation).
        r = compute_hps(self.snap, "Soraka", level=11, mode="SR")
        self.assertEqual(r.direct_throughput, 0.0)
        self.assertEqual(r.ally_buff_credit, 0.0)
        self.assertAlmostEqual(r.total_throughput, r.ability_hps_total, places=9)
        self.assertGreater(r.total_throughput, 0.0)

    def test_soraka_total_surfaces_in_to_dict(self) -> None:
        r = compute_hps(self.snap, "Soraka", level=11, mode="SR")
        d = r.to_dict()
        self.assertIn("ability_heal_hps", d)
        self.assertIn("ability_shield_hps", d)
        self.assertIn("ability_hps_total", d)
        self.assertEqual(d["ability_hps_total"], r.ability_hps_total)

    def test_soraka_note_announces_ability_contribution(self) -> None:
        r = compute_hps(self.snap, "Soraka", level=11, mode="SR")
        joined = " ".join(r.notes).lower()
        self.assertIn("champion-ability heal/shield throughput", joined)

    # --- (b) non-heal champion: byte-identical to manual direct+buff ---

    def test_caitlyn_ability_hps_zero_and_total_byte_identical(self) -> None:
        r = compute_hps(self.snap, "Caitlyn", level=11, mode="SR")
        # Caitlyn (marksman) has no ability heal/shield blocks.
        self.assertEqual(r.ability_hps_total, 0.0)
        self.assertEqual(r.ability_heal_hps, 0.0)
        self.assertEqual(r.ability_shield_hps, 0.0)
        # total_throughput is byte-identical to the manual direct+buff sum.
        manual = r.direct_throughput + r.ally_buff_credit
        self.assertEqual(r.total_throughput, manual)

    def test_caitlyn_with_dps_item_still_zero_ability(self) -> None:
        # A DPS item (BotRK 3153) contributes 0 enchanter-item HPS and
        # Caitlyn has no ability heals -> total stays exactly 0.0.
        r = compute_hps(self.snap, "Caitlyn", level=11, item_ids=["3153"], mode="SR")
        self.assertEqual(r.ability_hps_total, 0.0)
        self.assertEqual(r.total_throughput, 0.0)

    def test_non_heal_no_ability_note(self) -> None:
        r = compute_hps(self.snap, "Caitlyn", level=11, mode="SR")
        joined = " ".join(r.notes).lower()
        self.assertNotIn("champion-ability heal/shield throughput", joined)

    # --- (c) enchanter with items: BOTH item and ability contributions ---

    def test_soraka_with_items_has_both_contributions(self) -> None:
        # Soraka + Redemption (3107, direct heal) + Ardent (3504, buff
        # credit) -> item direct + buff present AND ability heal present.
        r = compute_hps(
            self.snap, "Soraka", level=11, item_ids=["3107", "3504"], mode="SR"
        )
        self.assertGreater(r.direct_throughput, 0.0)  # Redemption heal
        self.assertGreater(r.ally_buff_credit, 0.0)    # Ardent credit
        self.assertGreater(r.ability_hps_total, 0.0)   # Soraka kit
        self.assertAlmostEqual(
            r.total_throughput,
            r.direct_throughput + r.ally_buff_credit + r.ability_hps_total,
            places=9,
        )

    def test_ability_hps_grows_with_ap_in_ranker(self) -> None:
        # AP-scaling ability heals grow with AP, so adding an AP item raises
        # Soraka's ability_hps_total (recomputed per build, not special-cased).
        base = compute_hps(self.snap, "Soraka", level=11, mode="SR")
        # Rabadon's Deathcap (3089) is pure AP.
        amped = compute_hps(
            self.snap, "Soraka", level=11, item_ids=["3089"], mode="SR"
        )
        self.assertGreater(amped.ability_hps_total, base.ability_hps_total)

    # --- (d) ARAM aramHealing/aramShielding still folds correctly ---

    def test_aram_mode_does_not_crash_and_folds(self) -> None:
        r = compute_hps(self.snap, "Soraka", level=11, mode="ARAM")
        # ARAM heal modifier still applies; ability HPS is present + folded.
        self.assertGreater(r.ability_hps_total, 0.0)
        self.assertAlmostEqual(
            r.total_throughput,
            r.direct_throughput + r.ally_buff_credit + r.ability_hps_total,
            places=9,
        )

    def test_aram_fold_is_consistent(self) -> None:
        # Soraka's ARAM ability heal is present and folds into the ARAM total
        # consistently. (SR vs ARAM differ when the aramHealing modifier is
        # non-unity; both fold the same additive way.)
        sr = compute_hps(self.snap, "Soraka", level=11, mode="SR")
        aram = compute_hps(self.snap, "Soraka", level=11, mode="ARAM")
        self.assertGreater(sr.ability_hps_total, 0.0)
        self.assertGreater(aram.ability_hps_total, 0.0)
        self.assertAlmostEqual(
            aram.total_throughput,
            aram.direct_throughput + aram.ally_buff_credit
            + aram.ability_hps_total,
            places=9,
        )

    # --- empty-result / no-heal path keeps the 3 fields at 0.0 ---

    def test_no_heal_champion_zero_ability_fields(self) -> None:
        # Re-affirm the zero-ability contract for a no-heal champion: all 3
        # V2 fields stay exactly 0.0 (the byte-identical path).
        r = compute_hps(self.snap, "Caitlyn", level=11, mode="SR")
        self.assertEqual(r.ability_heal_hps, 0.0)
        self.assertEqual(r.ability_shield_hps, 0.0)
        self.assertEqual(r.ability_hps_total, 0.0)


class AbilityHpsAsciiHygieneTests(unittest.TestCase):
    def test_module_is_ascii(self) -> None:
        import agents.daemon_slayer.tests.test_hps_ability_wire as mod

        with open(mod.__file__, "rb") as fh:
            raw = fh.read()
        for i, b in enumerate(raw):
            self.assertLess(
                b, 128, msg=f"non-ASCII byte 0x{b:02x} at offset {i}"
            )


if __name__ == "__main__":
    unittest.main()
