"""Arena CONVERSION augments: Aim for the Head (crit cap + excess -> crit
damage) and Tap Dancer (move speed per hit, move speed -> attack speed).

Source of every magnitude: the cdragon arena dump carried in the DS
snapshot (``data/daemon_slayer/16.18.1/arena_augments.json``,
AimForTheHead id 336 / TapDancer id 81), cross-checked by name + id
against the refetched ``cherry_augments.json`` catalogue. Tests read the
magnitudes from the snapshot rather than hard-coding them, so a patch
re-extract that moves a number moves the expectation with it.
"""

import unittest

from agents.daemon_slayer.augments import (
    ASSUMED_TAP_DANCER_STACKS,
    Augment,
    soft_capped_move_speed,
)
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps
from agents.daemon_slayer.engine import build_champion

# Arena mirrors of four 25%-crit items (DDragon stat block, maps.30).
IE = "223031"          # Infinity Edge, 25% crit, +30% crit damage passive
LDR = "223036"         # Lord Dominik's Regards, 25% crit
PD = "223046"          # Phantom Dancer, 25% crit
RFC = "223094"         # Rapid Firecannon, 25% crit
YUN_TAL = "223032"     # Yun Tal Wildarrows, crit via item EFFECT (0.25)

MAINS = ("Tristana", "Vayne")


def _dv(snap, api, key, idx=0):
    return float(Augment.from_record(snap.arena_augment(api)).data_values[key][idx])


class AimForTheHeadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()
        cls.ceiling = _dv(cls.snap, "AimForTheHead", "CritChanceCeiling")
        cls.ratio = _dv(cls.snap, "AimForTheHead", "CritChanceToDamageRatio")
        cls.chance = _dv(cls.snap, "AimForTheHead", "CritChanceBonus")
        cls.dmg = _dv(cls.snap, "AimForTheHead", "CritDamageBonus")

    def test_data_values_are_the_16_18_1_text(self) -> None:
        self.assertEqual(self.ceiling, 0.5)
        self.assertAlmostEqual(self.ratio, 0.4, places=6)
        self.assertEqual(self.chance, 0.25)
        self.assertEqual(self.dmg, 0.25)

    def test_no_crit_items_grants_flat_chance_and_damage(self) -> None:
        for champ in MAINS:
            bare = build_champion(self.snap, champ, level=18, mode="ARENA")
            aug = build_champion(
                self.snap, champ, level=18, mode="ARENA", augments=["AimForTheHead"]
            )
            self.assertAlmostEqual(aug.stats["crit"] - bare.stats["crit"], self.chance)
            self.assertAlmostEqual(aug.stats["crit_damage"], self.dmg)

    def test_two_crit_items_caps_and_converts_excess(self) -> None:
        for champ in MAINS:
            r = build_champion(
                self.snap, champ, level=18, item_ids=[IE, LDR], mode="ARENA",
                augments=["AimForTheHead"],
            )
            raw = 0.25 + 0.25 + self.chance  # 75% before the ceiling
            self.assertAlmostEqual(r.stats["crit"], self.ceiling)
            self.assertAlmostEqual(
                r.stats["crit_damage"], self.dmg + self.ratio * (raw - self.ceiling)
            )

    def test_four_crit_items_converts_past_the_100_percent_cap(self) -> None:
        r = build_champion(
            self.snap, "Tristana", level=18, item_ids=[IE, LDR, PD, RFC],
            mode="ARENA", augments=["AimForTheHead"],
        )
        self.assertAlmostEqual(r.stats["crit"], self.ceiling)
        self.assertAlmostEqual(
            r.stats["crit_damage"], self.dmg + self.ratio * (1.25 - self.ceiling)
        )

    def test_resolves_by_numeric_id(self) -> None:
        by_api = build_champion(
            self.snap, "Vayne", level=18, item_ids=[IE, LDR], mode="ARENA",
            augments=["AimForTheHead"],
        )
        by_id = build_champion(
            self.snap, "Vayne", level=18, item_ids=[IE, LDR], mode="ARENA",
            augments=[336],
        )
        self.assertEqual(by_api.stats, by_id.stats)

    def test_dps_rises_at_two_item_depth(self) -> None:
        # Two crit items already sit AT the 50% ceiling, so the augment costs
        # no chance and adds crit damage - DPS must strictly rise.
        for champ in MAINS:
            bare = compute_dps(self.snap, champ, level=18, item_ids=[IE, LDR], mode="ARENA")
            aug = compute_dps(
                self.snap, champ, level=18, item_ids=[IE, LDR], mode="ARENA",
                augments=["AimForTheHead"],
            )
            self.assertGreater(aug.raw_attack_dps, bare.raw_attack_dps)
            self.assertGreater(aug.weighted_dps, bare.weighted_dps)

    def test_dps_consumes_crit_damage_exactly(self) -> None:
        # raw_attack_dps = AD * AS * (1 + crit * crit_bonus); both builds have
        # the same AD / AS / crit, so the ratio isolates crit_bonus.
        bare = compute_dps(self.snap, "Tristana", level=18, item_ids=[IE, LDR], mode="ARENA")
        aug = compute_dps(
            self.snap, "Tristana", level=18, item_ids=[IE, LDR], mode="ARENA",
            augments=["AimForTheHead"],
        )
        ad_as_bare = bare.raw_attack_dps / (1 + 0.5 * (0.75 + 0.30))
        extra = self.dmg + self.ratio * 0.25
        # The augment's +25% crit chance is fully discarded at the ceiling,
        # so AD and AS are unchanged: the only term that moves is crit_bonus.
        self.assertAlmostEqual(
            aug.raw_attack_dps, ad_as_bare * (1 + 0.5 * (0.75 + 0.30 + extra)), places=6
        )

    def test_item_effect_crit_is_also_capped_and_converted(self) -> None:
        # Yun Tal's crit rides the ITEM-EFFECT channel (added in compute_dps,
        # not the stat block), so the ceiling must bind there too.
        aug = compute_dps(
            self.snap, "Tristana", level=18, item_ids=[IE, YUN_TAL], mode="ARENA",
            augments=["AimForTheHead"],
        )
        notes = " ".join(aug.notes)
        self.assertIn("Aim for the Head", notes)
        # stat crit 0.25 + 0.25 aug = 0.50 (no stat excess), effect +0.25 ->
        # 0.25 effect excess converted at the ratio.
        self.assertIn(f"+{self.ratio * 0.25:.4f}", notes)

    def test_unrelated_augments_carry_no_crit_damage_key(self) -> None:
        for api in ("ItsCritical", "TheBrutalizer", "LegDay"):
            r = build_champion(
                self.snap, "Tristana", level=18, item_ids=[IE, LDR], mode="ARENA",
                augments=[api],
            )
            self.assertNotIn("crit_damage", r.stats, api)
        r = build_champion(
            self.snap, "Tristana", level=18, item_ids=[IE, LDR], mode="ARENA",
            augments=["ItsCritical"],
        )
        self.assertEqual(r.stats["crit"], 1.0)


class TapDancerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()
        cls.ms_per_hit = _dv(cls.snap, "TapDancer", "MSPerHit")
        cls.conv = _dv(cls.snap, "TapDancer", "MSToASConversion")

    def test_data_values_are_the_16_18_1_text(self) -> None:
        self.assertEqual(self.ms_per_hit, 6.0)
        self.assertAlmostEqual(self.conv, 0.001, places=9)

    def test_soft_cap_is_continuous_at_the_breakpoints(self) -> None:
        self.assertAlmostEqual(soft_capped_move_speed(415.0), 415.0)
        self.assertAlmostEqual(soft_capped_move_speed(490.0), 475.0)
        self.assertAlmostEqual(soft_capped_move_speed(300.0), 300.0)
        self.assertLess(soft_capped_move_speed(600.0), 600.0)

    def test_as_and_ms_match_the_text_at_given_stacks(self) -> None:
        for champ in MAINS:
            bare = build_champion(self.snap, champ, level=18, item_ids=[IE], mode="ARENA")
            r = build_champion(
                self.snap, champ, level=18, item_ids=[IE], mode="ARENA",
                augments=["TapDancer"], augment_stacks={"TapDancer": 4},
            )
            ms = bare.stats["ms"] + 4 * self.ms_per_hit
            self.assertAlmostEqual(r.stats["ms"], ms)
            base_as = float(self.snap.champion(champ)["stats"]["attackspeed"])
            expected_as = min(
                2.5, bare.stats["as"] + base_as * self.conv * soft_capped_move_speed(ms)
            )
            self.assertAlmostEqual(r.stats["as"], expected_as)

    def test_default_stacks_is_the_documented_assumption(self) -> None:
        a = build_champion(
            self.snap, "Vayne", level=18, mode="ARENA", augments=["TapDancer"],
        )
        b = build_champion(
            self.snap, "Vayne", level=18, mode="ARENA", augments=["TapDancer"],
            augment_stacks={"TapDancer": ASSUMED_TAP_DANCER_STACKS},
        )
        self.assertEqual(a.stats, b.stats)

    def test_monotonic_in_stacks_until_the_attack_speed_cap(self) -> None:
        # The text names no stack cap; the only ceiling is League's 2.5 AS.
        for champ in MAINS:
            prev_as = None
            for stacks in (0, 1, 5, 10, 20, 40):
                r = build_champion(
                    self.snap, champ, level=18, item_ids=[IE, PD], mode="ARENA",
                    augments=["TapDancer"], augment_stacks={"TapDancer": stacks},
                )
                self.assertLessEqual(r.stats["as"], 2.5)
                if prev_as is not None:
                    self.assertGreaterEqual(r.stats["as"], prev_as)
                prev_as = r.stats["as"]
            big = build_champion(
                self.snap, champ, level=18, item_ids=[IE, PD], mode="ARENA",
                augments=["TapDancer"], augment_stacks={"TapDancer": 10_000},
            )
            self.assertEqual(big.stats["as"], 2.5)

    def test_zero_stacks_still_converts_base_move_speed(self) -> None:
        bare = build_champion(self.snap, "Tristana", level=18, mode="ARENA")
        r = build_champion(
            self.snap, "Tristana", level=18, mode="ARENA",
            augments=["TapDancer"], augment_stacks={"TapDancer": 0},
        )
        self.assertGreater(r.stats["as"], bare.stats["as"])
        self.assertAlmostEqual(r.stats["ms"], bare.stats["ms"])

    def test_dps_rises_with_tap_dancer(self) -> None:
        for champ in MAINS:
            bare = compute_dps(self.snap, champ, level=18, item_ids=[IE, PD], mode="ARENA")
            aug = compute_dps(
                self.snap, champ, level=18, item_ids=[IE, PD], mode="ARENA",
                augments=["TapDancer"],
            )
            self.assertGreater(aug.weighted_dps, bare.weighted_dps)

    def test_tap_dancer_alone_does_not_emit_unregistered_note(self) -> None:
        r = build_champion(
            self.snap, "Vayne", level=18, mode="ARENA", augments=["TapDancer"],
        )
        self.assertFalse(any("none in stat-overlay registry" in n for n in r.notes))

    def test_unrelated_augment_as_unchanged(self) -> None:
        bare = build_champion(self.snap, "Vayne", level=18, item_ids=[PD], mode="ARENA")
        r = build_champion(
            self.snap, "Vayne", level=18, item_ids=[PD], mode="ARENA",
            augments=["TheBrutalizer"], augment_stacks={"TapDancer": 50},
        )
        self.assertEqual(r.stats["as"], bare.stats["as"])
        self.assertEqual(r.stats["ms"], bare.stats["ms"])


if __name__ == "__main__":
    unittest.main()
