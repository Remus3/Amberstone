"""R75 (2026-07-03) - Serpent's Fang Shield Reaver on the NEW DSV9 anti-shield seam.

Meraki 16.13.1 item 6695 Serpent's Fang passive "Shield Reaver"
(byte-exact): "Dealing damage to an enemy champion inflicts them with
venom for 3 seconds, reducing any {{tip|shield|shields}} they gain
within the duration by {{rd|50%|35%}}, and if the target was not
already afflicted by the venom, reducing all of their active shields by
the same amount." rd = melee|ranged: melee 0.50, ranged 0.35.

DSV9 (1.179.0) mirrors the DSV8 ``assume_physical_burst`` pattern: two
END-appended ItemEffect fields ``shield_cut_melee_pct`` /
``shield_cut_ranged_pct``, a pure facade helper
``effects.total_shield_cut_value``, and a compute_burst_damage fold
gated on the default-OFF ``assume_shielded_target`` kwarg. The consumer
credits ONE active-shield cut event against an assumed pool of
``_ASSUMED_TARGET_SHIELD_PCT_OF_MAX_HP`` x target max HP when a
``target_max_hp`` is supplied. Shield HP absorbs POST-mitigation
damage, so removing X shield HP is worth X post-mitigation-equivalent
damage - NO armor/MR routing, NO mode_mult, NO amp layer (stricter than
DSV8: a shield cut is not damage dealt at all). The sustained "shields
gained within the duration" reduction stays UNMODELED (utility over
time, not burst math). compute_dps sees nothing (no PeriodicProc);
compute_ability_dps accepts the flag as a documented-inert kwarg for
API symmetry only.

Slice ownership: the 6695 / 226695 registry pins land in
_effects_data.py in a SIBLING slice - the pin-dependent tests below
(EngineVersion, MerakiTruth.test_registry_matches_meraki_value,
RegistryPins.test_sr_pin / test_arena_pin) are EXPECTED RED until that
slice + the orchestrator ENGINE bump (1.178.0 -> 1.179.0) merge. The
consumer tests inject a synthetic carrier so they are GREEN in this
slice alone.

Variant sweep (16.13.1 DS pool): 6695 is the SR id (map 11), 226695 is
the Arena mirror (map 30, NO Meraki entry - pinned off the 6695 truth
per the Arena-mirror convention). 326695 exists in neither the pool nor
the Meraki mirror.
"""
from __future__ import annotations

import dataclasses
import inspect
import json
import re
import unittest
from pathlib import Path
from unittest import mock

from agents import daemon_slayer
from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.ability_dps import compute_ability_dps
from agents.daemon_slayer.burst import (
    _ASSUMED_TARGET_SHIELD_PCT_OF_MAX_HP,
    compute_burst_damage,
)
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps
from agents.daemon_slayer.effects import (
    ITEM_EFFECTS,
    ItemEffect,
    collect_effects,
    total_magic_burst_damage,
    total_physical_burst_damage,
    total_shield_cut_value,
)

_PATCH = "16.13.1"
_REPO_ROOT = Path(__file__).resolve().parents[3]
_MERAKI_PATH = (
    _REPO_ROOT / "data" / "daemon_slayer" / _PATCH / "items_meraki.json"
)
_ITEMS_POOL_PATH = (
    _REPO_ROOT / "data" / "daemon_slayer" / _PATCH / "items.json"
)

_SERPENTS_SR = "6695"
_SERPENTS_ARENA = "226695"  # Arena mirror (map 30) - pinned off 6695 truth
_SERPENTS_PHANTOM = "326695"  # in neither pool nor Meraki

# Cross-seam isolation guards.
_LUDENS = "6655"  # DSV6 magic carrier
_THORNMAIL = "3075"  # reflect item - must stay off the seam

_NO_CUT_BUILD = ["3047"]  # Plated Steelcaps - no shield_cut fields
_CUT_BUILD = ["3047", _SERPENTS_SR]

_MELEE_CHAMP = "Darius"  # attackrange 175 -> melee rd arm
_RANGED_CHAMP = "Ashe"  # attackrange 600 -> ranged rd arm

# Synthetic carrier: consumer tests must be GREEN in THIS slice without the
# sibling registry slice, so the Shield Reaver magnitudes are injected onto
# the real pool id via mock.patch.dict - collect_effects reads the same
# ITEM_EFFECTS dict object, and both ON and OFF legs run inside the patch so
# the delta isolates the seam exactly.
_SYN_REAVER = ItemEffect(
    item_id=_SERPENTS_SR,
    name="synthetic shield reaver",
    shield_cut_melee_pct=0.50,
    shield_cut_ranged_pct=0.35,
)


class EngineVersion(unittest.TestCase):
    """EXPECTED RED in the engine slice - the orchestrator owns the bump."""

    def test_engine_version_bumped(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.264.0")
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.264.0")


class SchemaDefaults(unittest.TestCase):
    """END-appended fields default 0.0 - every existing item is inert."""

    def test_defaults_are_zero(self) -> None:
        eff = ItemEffect(item_id="0", name="synthetic")
        self.assertEqual(eff.shield_cut_melee_pct, 0.0)
        self.assertEqual(eff.shield_cut_ranged_pct, 0.0)

    def test_fields_appended_at_end(self) -> None:
        # Mid-class insert breaks positional construction (repo convention).
        # R113 (1.210.0) appended ``physical_burst_total_ad_ratio`` at the very
        # END -> it is now the last field; R111's ``missing_hp_ad_amp_max_pct``
        # is second-to-last, R86's ``enemy_attack_speed_slow`` third-to-last,
        # R80's ``basic_attack_damage_reduction`` fourth-to-last, R77's
        # ``crit_damage_reduction`` fifth-to-last, the DSV9 shield-cut pair
        # sixth/seventh-to-last, the DSV8 physical-burst base pair
        # eighth/ninth-to-last (order preserved).
        names = [f.name for f in dataclasses.fields(ItemEffect)]
        self.assertEqual(names[-1], "physical_burst_total_ad_ratio")
        self.assertEqual(names[-2], "missing_hp_ad_amp_max_pct")
        self.assertEqual(names[-3], "enemy_attack_speed_slow")
        self.assertEqual(names[-4], "basic_attack_damage_reduction")
        self.assertEqual(names[-5], "crit_damage_reduction")
        self.assertEqual(
            names[-7:-5], ["shield_cut_melee_pct", "shield_cut_ranged_pct"]
        )
        self.assertEqual(
            names[-9:-7],
            ["physical_burst_base", "physical_burst_base_ad_ratio"],
        )


class MerakiTruth(unittest.TestCase):
    """Registry pin derives from the vendored Meraki 16.13.1 passive text;
    a patch changing the numbers fails HERE instead of silently drifting."""

    @classmethod
    def setUpClass(cls) -> None:
        doc = json.loads(_MERAKI_PATH.read_text(encoding="utf-8"))
        passives = doc["items"][_SERPENTS_SR]["passives"]
        entry = next(
            (p for p in passives if p.get("name") == "Shield Reaver"), None
        )
        assert entry is not None, "Meraki 6695 has no 'Shield Reaver'"
        cls.text = entry["effects"]

    def _parse_rd(self) -> tuple[int, int]:
        m = re.search(r"\{\{rd\|(\d+)%\|(\d+)%\}\}", self.text)
        self.assertIsNotNone(
            m, f"Shield Reaver rd arms not found in: {self.text!r}"
        )
        return int(m.group(1)), int(m.group(2))

    def test_meraki_magnitude(self) -> None:
        # rd = melee|ranged per the Meraki template convention.
        self.assertEqual(self._parse_rd(), (50, 35))
        self.assertIn("venom for 3 seconds", self.text)
        # The one-time ACTIVE-shield cut is the modeled event.
        self.assertIn(
            "reducing all of their active shields by the same amount",
            self.text,
        )

    def test_sustained_reduction_present_but_unmodeled(self) -> None:
        # The "shields they gain within the duration" rider exists in the
        # truth text and is deliberately NOT modeled - utility over time,
        # not burst math; no field carries it.
        self.assertIn("they gain within the duration", self.text)

    def test_registry_matches_meraki_value(self) -> None:
        # EXPECTED RED until the sibling registry slice pins 6695.
        melee, ranged = self._parse_rd()
        eff = ITEM_EFFECTS[_SERPENTS_SR]
        self.assertAlmostEqual(eff.shield_cut_melee_pct, melee / 100.0)
        self.assertAlmostEqual(eff.shield_cut_ranged_pct, ranged / 100.0)


class RegistryPins(unittest.TestCase):
    """Hand-authored pins: 6695 + Arena 226695 carry the DSV9 seam fields.
    The two pin tests are EXPECTED RED until the sibling registry slice."""

    def test_sr_pin(self) -> None:
        eff = ITEM_EFFECTS[_SERPENTS_SR]
        self.assertAlmostEqual(eff.shield_cut_melee_pct, 0.50)
        self.assertAlmostEqual(eff.shield_cut_ranged_pct, 0.35)

    def test_arena_pin(self) -> None:
        eff = ITEM_EFFECTS[_SERPENTS_ARENA]
        self.assertAlmostEqual(eff.shield_cut_melee_pct, 0.50)
        self.assertAlmostEqual(eff.shield_cut_ranged_pct, 0.35)

    def test_no_phantom_variant(self) -> None:
        # 326695 is in NEITHER the 16.13.1 DS pool NOR the Meraki mirror -
        # registering it would be a phantom id (R68 pattern).
        pool = json.loads(_ITEMS_POOL_PATH.read_text(encoding="utf-8"))["data"]
        meraki = json.loads(_MERAKI_PATH.read_text(encoding="utf-8"))["items"]
        self.assertNotIn(_SERPENTS_PHANTOM, pool)
        self.assertNotIn(_SERPENTS_PHANTOM, meraki)
        self.assertNotIn(_SERPENTS_PHANTOM, ITEM_EFFECTS)

    def test_non_carrier_items_stay_off_seam(self) -> None:
        for iid in (_LUDENS, _THORNMAIL, "3047"):
            eff = ITEM_EFFECTS[iid]
            self.assertEqual(eff.shield_cut_melee_pct, 0.0, msg=iid)
            self.assertEqual(eff.shield_cut_ranged_pct, 0.0, msg=iid)


class ShieldCutHelper(unittest.TestCase):
    """``total_shield_cut_value`` facade unit math."""

    def test_melee_arm(self) -> None:
        self.assertAlmostEqual(
            total_shield_cut_value([_SYN_REAVER], True, 100.0), 50.0
        )

    def test_ranged_arm(self) -> None:
        self.assertAlmostEqual(
            total_shield_cut_value([_SYN_REAVER], False, 100.0), 35.0
        )

    def test_zero_or_negative_pool_returns_zero(self) -> None:
        self.assertEqual(total_shield_cut_value([_SYN_REAVER], True, 0.0), 0.0)
        self.assertEqual(
            total_shield_cut_value([_SYN_REAVER], True, -50.0), 0.0
        )

    def test_none_entries_skipped(self) -> None:
        self.assertAlmostEqual(
            total_shield_cut_value([None, _SYN_REAVER], True, 100.0), 50.0
        )

    def test_no_carrier_returns_zero(self) -> None:
        self.assertEqual(total_shield_cut_value([], True, 500.0), 0.0)
        self.assertEqual(
            total_shield_cut_value(
                collect_effects(_NO_CUT_BUILD), True, 500.0
            ),
            0.0,
        )

    def test_additive_across_items(self) -> None:
        # Sums commute if a second carrier ever lands.
        self.assertAlmostEqual(
            total_shield_cut_value([_SYN_REAVER, _SYN_REAVER], False, 100.0),
            70.0,
        )

    def test_cross_seam_facade_isolation(self) -> None:
        # The shield-cut fields feed NO other facade helper.
        self.assertEqual(total_physical_burst_damage([_SYN_REAVER], 999.0), 0.0)
        self.assertEqual(total_magic_burst_damage([_SYN_REAVER], 999.0), 0.0)


class ComputeBurstSeam(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _delta(
        self,
        champ: str,
        *,
        mode: str = "SR",
        armor: float = 60.0,
        mr: float = 0.0,
        max_hp: float = 2000.0,
        **flags,
    ) -> float:
        # Both legs run inside the SAME registry patch so the ON-OFF delta
        # isolates the shield-cut fold exactly.
        with mock.patch.dict(ITEM_EFFECTS, {_SERPENTS_SR: _SYN_REAVER}):
            off = compute_burst_damage(
                self.snap, champ, 11, item_ids=_CUT_BUILD, mode=mode,
                target_armor=armor, target_mr=mr, target_max_hp=max_hp,
                **flags,
            )
            on = compute_burst_damage(
                self.snap, champ, 11, item_ids=_CUT_BUILD, mode=mode,
                target_armor=armor, target_mr=mr, target_max_hp=max_hp,
                assume_shielded_target=True, **flags,
            )
        return on.total_burst_damage - off.total_burst_damage

    def test_assumed_pool_constant(self) -> None:
        self.assertEqual(_ASSUMED_TARGET_SHIELD_PCT_OF_MAX_HP, 0.20)

    def test_default_off_byte_identical(self) -> None:
        with mock.patch.dict(ITEM_EFFECTS, {_SERPENTS_SR: _SYN_REAVER}):
            base = compute_burst_damage(
                self.snap, _MELEE_CHAMP, 11, item_ids=_CUT_BUILD,
                target_armor=60, target_max_hp=2000,
            )
            off = compute_burst_damage(
                self.snap, _MELEE_CHAMP, 11, item_ids=_CUT_BUILD,
                target_armor=60, target_max_hp=2000,
                assume_shielded_target=False,
            )
        self.assertEqual(base.total_burst_damage, off.total_burst_damage)

    def test_seam_on_non_carrier_build_byte_identical(self) -> None:
        # Real registry (no patch): a build with no shield_cut carrier is
        # inert even with the flag ON.
        off = compute_burst_damage(
            self.snap, _MELEE_CHAMP, 11, item_ids=_NO_CUT_BUILD,
            target_armor=60, target_max_hp=2000,
        )
        on = compute_burst_damage(
            self.snap, _MELEE_CHAMP, 11, item_ids=_NO_CUT_BUILD,
            target_armor=60, target_max_hp=2000,
            assume_shielded_target=True,
        )
        self.assertAlmostEqual(
            on.total_burst_damage, off.total_burst_damage, places=4
        )

    def test_zero_target_max_hp_inert(self) -> None:
        # No target_max_hp supplied -> no assumed pool -> no credit, even
        # with a carrier + the flag ON.
        self.assertAlmostEqual(
            self._delta(_MELEE_CHAMP, max_hp=0.0), 0.0, places=6
        )

    def test_melee_credit_exact(self) -> None:
        # Melee rd arm: exactly 0.50 * 0.20 * 2000 = 200.0 - no mitigation,
        # no mode_mult, no amp.
        self.assertAlmostEqual(
            self._delta(_MELEE_CHAMP),
            0.50 * _ASSUMED_TARGET_SHIELD_PCT_OF_MAX_HP * 2000.0,
            places=6,
        )

    def test_ranged_credit_exact(self) -> None:
        # Ranged rd arm: exactly 0.35 * 0.20 * 2000 = 140.0.
        self.assertAlmostEqual(
            self._delta(_RANGED_CHAMP),
            0.35 * _ASSUMED_TARGET_SHIELD_PCT_OF_MAX_HP * 2000.0,
            places=6,
        )

    def test_armor_and_mr_insensitive(self) -> None:
        # A shield cut is not damage dealt at all - the credit must not
        # route through EITHER resist.
        expected = 0.50 * _ASSUMED_TARGET_SHIELD_PCT_OF_MAX_HP * 2000.0
        for armor, mr in ((0.0, 0.0), (200.0, 0.0), (0.0, 200.0),
                          (300.0, 300.0)):
            self.assertAlmostEqual(
                self._delta(_MELEE_CHAMP, armor=armor, mr=mr),
                expected,
                places=6,
                msg=f"armor={armor} mr={mr}",
            )

    def test_mode_mult_insensitive(self) -> None:
        # Darius carries aramDamageDealt != 1.0 in the lolmath mirror, so an
        # accidental mode_mult fold would break the exact-credit equality in
        # ARAM; ARENA covers the mode_mult=1.0 lane.
        expected = 0.50 * _ASSUMED_TARGET_SHIELD_PCT_OF_MAX_HP * 2000.0
        for mode in ("ARAM", "ARENA"):
            self.assertAlmostEqual(
                self._delta(_MELEE_CHAMP, mode=mode),
                expected,
                places=6,
                msg=mode,
            )

    def test_cross_seam_isolation(self) -> None:
        # With the DSV8 / DSV6 / DSV2 seams ON, the shield-cut delta is
        # unchanged - and turning shield ON does not disturb what those
        # seams contribute (the delta would drift otherwise).
        expected = 0.50 * _ASSUMED_TARGET_SHIELD_PCT_OF_MAX_HP * 2000.0
        self.assertAlmostEqual(
            self._delta(
                _MELEE_CHAMP,
                assume_physical_burst=True,
                assume_magic_burst=True,
                assume_takedown=True,
            ),
            expected,
            places=6,
        )


class ComputeDpsSurface(unittest.TestCase):
    """compute_dps deliberately sees nothing - the one-time cut lives only
    in the burst window (no PeriodicProc, no kwarg, no double-count)."""

    def test_compute_dps_has_no_seam_kwarg(self) -> None:
        self.assertNotIn(
            "assume_shielded_target",
            inspect.signature(compute_dps).parameters,
        )

    def test_kwarg_end_appended_on_both_consumers(self) -> None:
        # END-append convention: the new kwarg is the LAST parameter of the
        # burst consumer and of the API-symmetry inert consumer.
        burst_params = list(
            inspect.signature(compute_burst_damage).parameters
        )
        dps_params = list(inspect.signature(compute_ability_dps).parameters)
        # R110 END-appended a new burst seam on BOTH consumers (inert on dps),
        # advancing this end marker from assume_shielded_target.
        self.assertEqual(burst_params[-1], "assume_item_lowhp_magic_crit")
        # A-07 / RM-82 TERM 2 END-appended apply_passive_aura_damage to
        # compute_ability_dps ONLY (the passive-aura seam has no burst-side
        # sibling), advancing the ability-dps end marker off
        # assume_item_lowhp_magic_crit. The convention this test exists to
        # guard is unchanged and is asserted directly below: a new kwarg goes
        # at the END, so assume_item_lowhp_magic_crit must still sit after
        # every pre-R110 seam and the new kwarg must be last.
        self.assertEqual(dps_params[-1], "apply_passive_aura_damage")
        self.assertEqual(dps_params[-2], "assume_item_lowhp_magic_crit")
        self.assertLess(
            dps_params.index("assume_shielded_target"),
            dps_params.index("assume_item_lowhp_magic_crit"),
        )


class AbilityDpsInertKwarg(unittest.TestCase):
    """compute_ability_dps accepts assume_shielded_target for API symmetry
    but is DELIBERATELY INERT (mirrors the DSV8 assume_physical_burst
    kwarg)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_inert_on_equals_off(self) -> None:
        with mock.patch.dict(ITEM_EFFECTS, {_SERPENTS_SR: _SYN_REAVER}):
            off = compute_ability_dps(
                self.snap, _MELEE_CHAMP, 11, item_ids=_CUT_BUILD,
                target_armor=60, target_max_hp=2000,
                assume_shielded_target=False,
            )
            on = compute_ability_dps(
                self.snap, _MELEE_CHAMP, 11, item_ids=_CUT_BUILD,
                target_armor=60, target_max_hp=2000,
                assume_shielded_target=True,
            )
        self.assertEqual(on.total_ability_dps, off.total_ability_dps)


if __name__ == "__main__":
    unittest.main()
