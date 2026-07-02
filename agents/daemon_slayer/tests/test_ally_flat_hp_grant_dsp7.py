"""DSP7 (ENGINE 1.133.0) - ally enchanter shield/heal flat-HP EHP-grant seam.

Extends the item-289 ally-grant family (resist denominator add + revive
numerator multiplier) with the THIRD EHP-grant mode: a flat-HP NUMERATOR ADD -
the shield/heal HP an enchanter CONFERS on a protected ally (Janna E / Lulu E /
Karma E / Soraka W / Nami W / Yuumi E / Seraphine W). Default-OFF
(apply_ally_grant=False -> 0.0; compute_ehp external_flat_hp default 0.0 ->
byte-identical). Magnitudes are the verbatim per-rank BASE shield/heal values
from data/daemon_slayer/16.12.1/champion_abilities.json (the source
ability_hps.py reads); the AP ratio is omitted (the granter's AP is a live
Phase-D input). The live consumer wiring is EXCLUDED (LIVE_GAME_GATED_SYNC.md).
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import compute_ehp
from agents.daemon_slayer._passive_ally_grant_overrides import (
    _ALLY_FLAT_HP_GRANT_OVERRIDES,
    _ALLY_SHIELD_HEAL_PROB,
    _PASSIVE_ALLY_GRANT_OVERRIDES,
    AllyGrantEntry,
    ally_flat_hp_grant,
)
from agents.daemon_slayer._passive_resist_overrides import _value_at_level


class EntryFieldDefaultsTests(unittest.TestCase):
    def test_new_flat_hp_fields_default_zero(self):
        e = AllyGrantEntry()
        self.assertEqual(e.shield_hp, 0.0)
        self.assertEqual(e.heal_hp, 0.0)

    def test_existing_resist_entries_carry_no_flat_hp(self):
        # The 4 item-289 resist/revive entries grant no shield/heal HP.
        for e in _PASSIVE_ALLY_GRANT_OVERRIDES.values():
            self.assertEqual(e.shield_hp, 0.0)
            self.assertEqual(e.heal_hp, 0.0)


class ProbConstantTests(unittest.TestCase):
    def test_midpoint(self):
        self.assertEqual(_ALLY_SHIELD_HEAL_PROB, 0.5)


class RegistryShapeTests(unittest.TestCase):
    def test_expected_champions(self):
        champs = {k[0] for k in _ALLY_FLAT_HP_GRANT_OVERRIDES}
        self.assertEqual(
            champs,
            {"Janna", "Lulu", "Karma", "Soraka", "Nami", "Yuumi", "Seraphine"},
        )

    def test_janna_shield_base_tuple(self):
        e = _ALLY_FLAT_HP_GRANT_OVERRIDES[("Janna", "E", 0)]
        self.assertEqual(e.shield_hp, (80.0, 120.0, 160.0, 200.0, 240.0))
        self.assertEqual(e.heal_hp, 0.0)
        self.assertTrue(e.rank_scaled)
        self.assertEqual(e.conditional_probability, _ALLY_SHIELD_HEAL_PROB)

    def test_soraka_heal_base_tuple(self):
        e = _ALLY_FLAT_HP_GRANT_OVERRIDES[("Soraka", "W", 0)]
        self.assertEqual(e.heal_hp, (90.0, 110.0, 130.0, 150.0, 170.0))
        self.assertEqual(e.shield_hp, 0.0)

    def test_karma_shield_base_tuple(self):
        e = _ALLY_FLAT_HP_GRANT_OVERRIDES[("Karma", "E", 0)]
        self.assertEqual(e.shield_hp, (80.0, 130.0, 180.0, 230.0, 280.0))

    def test_separate_from_resist_registry(self):
        # The item-289 resist/revive registry stays exactly its 4 clean entries
        # (the shield/heal bucket lives in this NEW separate registry, so the
        # item-289 exclusion test_ally_shields_heals_not_in_registry stays green).
        self.assertEqual(len(_PASSIVE_ALLY_GRANT_OVERRIDES), 4)
        self.assertEqual(
            {k[0] for k in _PASSIVE_ALLY_GRANT_OVERRIDES},
            {"Orianna", "Braum", "Taric", "Renata"},
        )


class AllyFlatHpGrantMathTests(unittest.TestCase):
    def test_flag_off_is_zero(self):
        for c in ("Janna", "Lulu", "Soraka", "Caitlyn"):
            self.assertEqual(ally_flat_hp_grant(c, 18, False), 0.0)

    def test_janna_shield_matches_curve(self):
        # Resolve via the same _value_at_level path (no hardcoded rank) * prob.
        base = _value_at_level(
            (80.0, 120.0, 160.0, 200.0, 240.0), 18, False, key="E", rank_scaled=True
        )
        self.assertGreater(base, 0.0)
        self.assertAlmostEqual(
            ally_flat_hp_grant("Janna", 18, True),
            base * _ALLY_SHIELD_HEAL_PROB,
            places=4,
        )

    def test_soraka_heal_matches_curve(self):
        base = _value_at_level(
            (90.0, 110.0, 130.0, 150.0, 170.0), 18, False, key="W", rank_scaled=True
        )
        self.assertAlmostEqual(
            ally_flat_hp_grant("Soraka", 18, True),
            base * _ALLY_SHIELD_HEAL_PROB,
            places=4,
        )

    def test_non_entry_champ_zero_on(self):
        # Resist-registry champs and a selfish carry contribute nothing here.
        for c in ("Caitlyn", "Garen", "Orianna", "Renata", "Taric"):
            self.assertEqual(ally_flat_hp_grant(c, 16, True), 0.0)

    def test_blank_champ_zero(self):
        self.assertEqual(ally_flat_hp_grant("", 11, True), 0.0)

    def test_monotonic_by_level(self):
        lo = ally_flat_hp_grant("Janna", 1, True)
        hi = ally_flat_hp_grant("Janna", 18, True)
        self.assertGreater(hi, lo)


class EhpExternalFlatHpSeamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def test_default_byte_identical(self):
        base = compute_ehp(self.snap, "Caitlyn", 16, item_ids=[])
        noop = compute_ehp(self.snap, "Caitlyn", 16, item_ids=[], external_flat_hp=0.0)
        self.assertEqual(noop.blended_ehp, base.blended_ehp)
        self.assertEqual(noop.ally_grant_flat_hp, 0.0)

    def test_positive_flat_hp_raises_every_axis(self):
        off = compute_ehp(self.snap, "Caitlyn", 18, item_ids=[])
        on = compute_ehp(self.snap, "Caitlyn", 18, item_ids=[], external_flat_hp=200.0)
        self.assertGreater(on.blended_ehp, off.blended_ehp)
        self.assertGreater(on.physical_ehp, off.physical_ehp)
        self.assertGreater(on.magical_ehp, off.magical_ehp)
        self.assertGreater(on.true_ehp, off.true_ehp)
        self.assertEqual(on.ally_grant_flat_hp, 200.0)

    def test_flat_hp_scales_like_bonus_hp(self):
        # +H flat HP scales each per-type numerator exactly like +H max HP on a
        # naked build (no shields/heals): per-type EHP_on == EHP_off*(hp+H)/hp.
        off = compute_ehp(self.snap, "Caitlyn", 11, item_ids=[])
        H = 300.0
        on = compute_ehp(self.snap, "Caitlyn", 11, item_ids=[], external_flat_hp=H)
        ratio = (off.hp + H) / off.hp
        self.assertAlmostEqual(on.physical_ehp, off.physical_ehp * ratio, places=2)
        self.assertAlmostEqual(on.magical_ehp, off.magical_ehp * ratio, places=2)
        self.assertAlmostEqual(on.true_ehp, off.true_ehp * ratio, places=2)

    def test_negative_flat_hp_clamped(self):
        off = compute_ehp(self.snap, "Caitlyn", 11, item_ids=[])
        on = compute_ehp(self.snap, "Caitlyn", 11, item_ids=[], external_flat_hp=-100.0)
        self.assertEqual(on.blended_ehp, off.blended_ehp)
        self.assertEqual(on.ally_grant_flat_hp, 0.0)

    def test_to_dict_carries_flat_hp(self):
        d = compute_ehp(
            self.snap, "Caitlyn", 18, item_ids=[], external_flat_hp=150.0
        ).to_dict()
        self.assertEqual(d["ally_grant_flat_hp"], 150.0)

    def test_grant_feeds_ehp_end_to_end(self):
        # Source Janna's ally shield grant, feed a protected ally's EHP.
        g = ally_flat_hp_grant("Janna", 18, True)
        self.assertGreater(g, 0.0)
        off = compute_ehp(self.snap, "Caitlyn", 18, item_ids=[])
        on = compute_ehp(self.snap, "Caitlyn", 18, item_ids=[], external_flat_hp=g)
        self.assertGreater(on.blended_ehp, off.blended_ehp)
        self.assertEqual(on.ally_grant_flat_hp, g)


class EngineVersionTests(unittest.TestCase):
    def test_engine_version(self):
        self.assertEqual(ENGINE_VERSION, "1.168.0")


if __name__ == "__main__":
    unittest.main()
