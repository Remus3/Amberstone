"""R111 (1.209.0): Overlord's Bloodmail "Retribution" caster-missing-HP AD steroid.

New DS OFFENSE seam paralleling the DSV2 takedown / kill-state lane. Overlord's
Bloodmail (SR 2501 / Arena 447111) "Retribution" grants bonus attack damage equal
to 0-12% of the wielder's total AD "from other sources", ramping linearly as the
wielder's missing HP goes 0 -> 70% (Meraki 16.13.1 items.2501). It was flagged
"not modeled" / "deferred" in _effects_data. R111 adds
``ItemEffect.missing_hp_ad_amp_max_pct`` (0.12 on SR 2501, 0.175 on Arena 447111)
and folds it into ``compute_dps`` + ``compute_burst_damage`` behind a default-OFF
``assume_caster_lowhp`` kwarg. The consumer assumes a conservative caster
missing-HP midpoint (``_ASSUMED_CASTER_MISSING_HP`` = 0.35 of the
``_RETRIBUTION_CAP_MISSING_HP`` = 0.70 ramp -> realizes half the max amp). Default
OFF -> every existing item + caller byte-identical; the amp realizes only at an
explicit assume_caster_lowhp=True on a build carrying the item.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer._effects_types import ItemEffect
from agents.daemon_slayer.burst import compute_burst_damage
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import (
    _ASSUMED_CASTER_MISSING_HP,
    _RETRIBUTION_CAP_MISSING_HP,
    compute_dps,
    total_missing_hp_bonus_ad,
)
from agents.daemon_slayer.effects import ITEM_EFFECTS

_PATCH = "16.13.1"
_REPO_ROOT = Path(__file__).resolve().parents[3]
_MERAKI_PATH = _REPO_ROOT / "data" / "daemon_slayer" / _PATCH / "items_meraki.json"

_BLOODMAIL_SR = "2501"
_BLOODMAIL_ARENA = "447111"
_BLOODMAIL_ARAM = "322501"  # NOT registered (grep-confirmed) - guard its absence
_SR_MAX_PCT = 0.12
_ARENA_MAX_PCT = 0.175
# Realized share of the max amp at the assumed midpoint: 0.35 / 0.70 = 0.5.
_REALIZED = 0.5
# Sibling AD items that carry NO missing-HP-AD field (must stay 0 even ON).
_INFINITY_EDGE = "3031"
_BLOODTHIRSTER = "3072"


class SchemaField(unittest.TestCase):
    """The END-appended field defaults 0.0 (byte-identical seam OFF)."""

    def test_default_zero(self) -> None:
        self.assertEqual(
            ItemEffect(item_id="x", name="x").missing_hp_ad_amp_max_pct, 0.0
        )

    def test_registry_pins(self) -> None:
        self.assertAlmostEqual(
            ITEM_EFFECTS[_BLOODMAIL_SR].missing_hp_ad_amp_max_pct, _SR_MAX_PCT
        )
        self.assertAlmostEqual(
            ITEM_EFFECTS[_BLOODMAIL_ARENA].missing_hp_ad_amp_max_pct,
            _ARENA_MAX_PCT,
        )

    def test_aram_mirror_absent(self) -> None:
        # No 322501 ARAM mirror in the pool - guard so a future add is deliberate.
        self.assertNotIn(_BLOODMAIL_ARAM, ITEM_EFFECTS)

    def test_consumer_constants(self) -> None:
        self.assertEqual(_RETRIBUTION_CAP_MISSING_HP, 0.70)
        self.assertEqual(_ASSUMED_CASTER_MISSING_HP, 0.35)


class MerakiTruth(unittest.TestCase):
    """Registry pins derive from the vendored Meraki 16.13.1 'Retribution' text;
    a patch changing the numbers fails HERE instead of silently drifting."""

    @classmethod
    def setUpClass(cls) -> None:
        doc = json.loads(_MERAKI_PATH.read_text(encoding="utf-8"))
        passives = doc["items"][_BLOODMAIL_SR]["passives"]
        entry = next(
            (p for p in passives if p.get("name") == "Retribution"), None
        )
        assert entry is not None, "Meraki 2501 has no 'Retribution' passive"
        cls.text = entry["effects"]

    def test_source_numbers(self) -> None:
        # 0 to 12(%) amp, ramping over 0 to 70(%) MISSING health -> the two
        # numbers behind the 0.12 field + the 0.70 cap constant.
        self.assertIn("0 to 12", self.text)
        self.assertIn("0 to 70", self.text)
        self.assertIn("missing", self.text)
        # "from other sources" is the exact scope the total_ad approximation
        # documents as a conservative simplification.
        self.assertIn("from other sources", self.text)


class Helper(unittest.TestCase):
    """total_missing_hp_bonus_ad resolves the seam math (flag-gated)."""

    def test_off_returns_zero(self) -> None:
        # Flag False (the default) -> 0.0 before crediting any item.
        self.assertEqual(total_missing_hp_bonus_ad([_BLOODMAIL_SR], 200.0), 0.0)
        self.assertEqual(
            total_missing_hp_bonus_ad(
                [_BLOODMAIL_SR], 200.0, assume_caster_lowhp=False
            ),
            0.0,
        )

    def test_on_magnitude(self) -> None:
        # 0.12 max * (0.35 / 0.70) realized * 200 total AD = 0.06 * 200 = 12.0.
        self.assertAlmostEqual(
            total_missing_hp_bonus_ad(
                [_BLOODMAIL_SR], 200.0, assume_caster_lowhp=True
            ),
            _SR_MAX_PCT * _REALIZED * 200.0,
        )
        self.assertAlmostEqual(
            total_missing_hp_bonus_ad(
                [_BLOODMAIL_SR], 200.0, assume_caster_lowhp=True
            ),
            12.0,
        )

    def test_arena_variant_magnitude(self) -> None:
        # Arena 447111 pins 0.175 -> 0.175 * 0.5 * 200 = 17.5.
        self.assertAlmostEqual(
            total_missing_hp_bonus_ad(
                [_BLOODMAIL_ARENA], 200.0, assume_caster_lowhp=True
            ),
            _ARENA_MAX_PCT * _REALIZED * 200.0,
        )

    def test_sibling_items_zero_even_on(self) -> None:
        # IE / Bloodthirster carry no field -> 0 extra AD even with the flag ON.
        self.assertEqual(
            total_missing_hp_bonus_ad(
                [_INFINITY_EDGE, _BLOODTHIRSTER], 200.0, assume_caster_lowhp=True
            ),
            0.0,
        )

    def test_empty_build_zero(self) -> None:
        self.assertEqual(
            total_missing_hp_bonus_ad([], 200.0, assume_caster_lowhp=True), 0.0
        )


class ComputeDpsSeam(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_default_off_byte_identical(self) -> None:
        base = compute_dps(self.snap, "Talon", level=11,
                           item_ids=[_BLOODMAIL_SR], target_armor=80)
        off = compute_dps(self.snap, "Talon", level=11,
                          item_ids=[_BLOODMAIL_SR], target_armor=80,
                          assume_caster_lowhp=False)
        self.assertEqual(base.weighted_dps, off.weighted_dps)

    def test_lowhp_raises_dps(self) -> None:
        off = compute_dps(self.snap, "Talon", level=11,
                          item_ids=[_BLOODMAIL_SR], target_armor=80)
        on = compute_dps(self.snap, "Talon", level=11,
                         item_ids=[_BLOODMAIL_SR], target_armor=80,
                         assume_caster_lowhp=True)
        self.assertGreater(on.weighted_dps, off.weighted_dps)

    def test_sibling_build_byte_identical_even_on(self) -> None:
        # Bloodthirster carries no field -> ON == OFF (no phantom AD).
        off = compute_dps(self.snap, "Talon", level=11,
                          item_ids=[_BLOODTHIRSTER], target_armor=80)
        on = compute_dps(self.snap, "Talon", level=11,
                         item_ids=[_BLOODTHIRSTER], target_armor=80,
                         assume_caster_lowhp=True)
        self.assertEqual(off.weighted_dps, on.weighted_dps)


class ComputeBurstSeam(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_default_off_byte_identical(self) -> None:
        base = compute_burst_damage(self.snap, "Talon", level=11,
                                    item_ids=[_BLOODMAIL_SR], target_armor=80,
                                    target_max_hp=2000)
        off = compute_burst_damage(self.snap, "Talon", level=11,
                                   item_ids=[_BLOODMAIL_SR], target_armor=80,
                                   target_max_hp=2000, assume_caster_lowhp=False)
        self.assertEqual(base.total_burst_damage, off.total_burst_damage)

    def test_lowhp_raises_burst(self) -> None:
        off = compute_burst_damage(self.snap, "Talon", level=11,
                                   item_ids=[_BLOODMAIL_SR], target_armor=80,
                                   target_max_hp=2000)
        on = compute_burst_damage(self.snap, "Talon", level=11,
                                  item_ids=[_BLOODMAIL_SR], target_armor=80,
                                  target_max_hp=2000, assume_caster_lowhp=True)
        self.assertGreater(on.total_burst_damage, off.total_burst_damage)

    def test_sibling_build_byte_identical_even_on(self) -> None:
        off = compute_burst_damage(self.snap, "Talon", level=11,
                                   item_ids=[_BLOODTHIRSTER], target_armor=80,
                                   target_max_hp=2000)
        on = compute_burst_damage(self.snap, "Talon", level=11,
                                  item_ids=[_BLOODTHIRSTER], target_armor=80,
                                  target_max_hp=2000, assume_caster_lowhp=True)
        self.assertEqual(off.total_burst_damage, on.total_burst_damage)


class EngineVersionPin(unittest.TestCase):
    def test_engine_version(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.219.0")


if __name__ == "__main__":
    unittest.main()
