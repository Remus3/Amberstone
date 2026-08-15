"""R70 (2026-07-03) - Hollow Radiance Desolate takedown eruption, DSV2 seam.

Meraki 16.13.1 item 6664 Hollow Radiance passive "Desolate" (verbatim,
champion clause): "Scoring a {{tip|takedown}} against an enemy champion
within 3 seconds of damaging them causes a larger eruption that deals
[hollow_ibase*4] (+ [hollow_ihp*4]% bonus health) magic damage ...
|400% of ''Immolate's'' damage}}to enemies within 500 units." Immolate's
own base is vardefineecho'd in the sibling passive: hollow_ibase=15,
hollow_ihp=1. So the champion-takedown eruption = 60 (+ 4% bonus
health) magic damage.

SCOPE: the champion-takedown 400% eruption ONLY. It rides the EXISTING
default-OFF DSV2 ``assume_takedown`` seam (Hubris/Collector precedent,
_effects_types.py DSV2 block) via a small schema lift: two new END-
appended ItemEffect fields ``takedown_eruption_base`` /
``takedown_eruption_bonus_hp_ratio``, a pure helper
``effects.total_takedown_eruption_damage``, and a burst.py fold that
credits the eruption ONCE as MAGIC damage under the same MR routing the
DSV6 assume_magic_burst seam uses. The smaller 200% NON-champion
eruption (minion/monster kill) stays unmodeled - farm math, not fight
math. R59 doctrine: a one-trigger payoff does NOT map to a DPS rate, so
compute_dps is untouched.

Variant sweep (16.13.1 DS pool): 6664 (SR) + 226664 (Arena map-30
mirror, same numbers per mirror convention; NO own Meraki entry). No
326664 ARAM id exists - guarded absent (R69 323152 precedent).
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from types import SimpleNamespace

from agents import daemon_slayer
from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.ability_dps import AbilityContext, _mitigation_factor
from agents.daemon_slayer.burst import compute_burst_damage
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.effects import ITEM_EFFECTS, collect_effects
from agents.daemon_slayer.engine import build_champion

_PATCH = "16.13.1"
_REPO_ROOT = Path(__file__).resolve().parents[3]
_MERAKI_PATH = (
    _REPO_ROOT / "data" / "daemon_slayer" / _PATCH / "items_meraki.json"
)
_ITEMS_POOL_PATH = (
    _REPO_ROOT / "data" / "daemon_slayer" / _PATCH / "items.json"
)

_HR = "6664"
_HR_ARENA = "226664"
_HR_ARAM_PHANTOM = "326664"  # must NOT exist (R69 323152 precedent)

# DSV2 siblings on the same assume_takedown seam - behavior must not move.
_HUBRIS = "6697"
_COLLECTOR = "6676"

# Sibling immolate item - must stay OFF the eruption fields.
_SUNFIRE = "3068"

_BOOTS = "3047"  # Plated Steelcaps - carries no eruption fields
_HR_BUILD = [_BOOTS, _HR]
_NO_CARRIER_BUILD = [_BOOTS]
_SIBLING_BUILD = [_HUBRIS, _COLLECTOR, _HR]

# Hand-derived from Meraki 16.13.1 (asserted against the vendored JSON in
# MerakiTruth below): Immolate base 15, 1% bonus HP; Desolate champion
# eruption = 400% -> 15*4 = 60 base, 1%*4 = 4% bonus HP.
_ERUPTION_BASE = 60.0
_ERUPTION_HP_RATIO = 0.04


def _eruption_helper():
    # Imported lazily so the module still collects at RED (the helper does
    # not exist pre-implementation; each consumer test fails individually).
    from agents.daemon_slayer.effects import total_takedown_eruption_damage
    return total_takedown_eruption_damage


class EngineVersion(unittest.TestCase):
    def test_engine_version_bumped(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.278.0")
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.278.0")


class MerakiTruth(unittest.TestCase):
    """Registry pins derive from the vendored Meraki 16.13.1 passive text;
    a patch changing the numbers fails HERE instead of silently drifting."""

    @classmethod
    def setUpClass(cls) -> None:
        doc = json.loads(_MERAKI_PATH.read_text(encoding="utf-8"))
        passives = doc["items"][_HR]["passives"]
        by_name = {p.get("name"): p.get("effects") for p in passives}
        assert "Immolate" in by_name, "Meraki 6664 has no 'Immolate'"
        assert "Desolate" in by_name, "Meraki 6664 has no 'Desolate'"
        cls.immolate = by_name["Immolate"]
        cls.desolate = by_name["Desolate"]

    def _parse_immolate_vars(self) -> tuple[int, int]:
        ib = re.search(
            r"\{\{#vardefineecho:hollow_ibase\|(\d+)\}\}", self.immolate
        )
        ih = re.search(
            r"\{\{#vardefineecho:hollow_ihp\|(\d+)\}\}", self.immolate
        )
        self.assertIsNotNone(ib, f"hollow_ibase not found in: {self.immolate!r}")
        self.assertIsNotNone(ih, f"hollow_ihp not found in: {self.immolate!r}")
        return int(ib.group(1)), int(ih.group(1))

    def test_immolate_base_values(self) -> None:
        ibase, ihp = self._parse_immolate_vars()
        self.assertEqual(ibase, 15)
        self.assertEqual(ihp, 1)

    def test_desolate_champion_takedown_clause(self) -> None:
        # 400% derivation: the champion eruption quadruples both Immolate
        # variables; the wiki fallback text names the multiple explicitly.
        self.assertIn("{{#var:hollow_ibase}}*4", self.desolate)
        self.assertIn("{{#var:hollow_ihp}}*4", self.desolate)
        self.assertIn("400% of ''Immolate's'' damage", self.desolate)
        # Trigger window + radius.
        self.assertIn("within 3 seconds of damaging them", self.desolate)
        self.assertIn("within 500 units", self.desolate)

    def test_desolate_non_champion_clause_out_of_scope(self) -> None:
        # The smaller 200% eruption on a NON-champion kill exists in the
        # truth text but stays UNMODELED (farm math, not fight math) - this
        # test documents the deliberate scope boundary.
        self.assertIn("non-champion unit", self.desolate)
        self.assertIn("{{#var:hollow_ibase}}*2", self.desolate)
        self.assertIn("200% of ''Immolate's'' damage", self.desolate)
        self.assertIn("within 350 units", self.desolate)

    def test_registry_matches_meraki_derivation(self) -> None:
        ibase, ihp = self._parse_immolate_vars()
        exp_base = float(ibase * 4)          # 15 * 4 = 60
        exp_ratio = (ihp * 4) / 100.0        # 1% * 4 = 0.04
        self.assertEqual(exp_base, _ERUPTION_BASE)
        self.assertEqual(exp_ratio, _ERUPTION_HP_RATIO)
        for iid in (_HR, _HR_ARENA):
            eff = ITEM_EFFECTS[iid]
            self.assertAlmostEqual(
                eff.takedown_eruption_base, exp_base, msg=iid
            )
            self.assertAlmostEqual(
                eff.takedown_eruption_bonus_hp_ratio, exp_ratio, msg=iid
            )


class RegistryPins(unittest.TestCase):
    """Hand-authored pins: 6664 + 226664 carry the eruption fields; the
    existing Immolate periodic stays byte-identical."""

    def test_hr_pins(self) -> None:
        eff = ITEM_EFFECTS[_HR]
        self.assertAlmostEqual(eff.takedown_eruption_base, 60.0)
        self.assertAlmostEqual(eff.takedown_eruption_bonus_hp_ratio, 0.04)

    def test_arena_mirror_matches_sr_exactly(self) -> None:
        base = ITEM_EFFECTS[_HR]
        mirror = ITEM_EFFECTS[_HR_ARENA]
        self.assertAlmostEqual(
            mirror.takedown_eruption_base, base.takedown_eruption_base
        )
        self.assertAlmostEqual(
            mirror.takedown_eruption_bonus_hp_ratio,
            base.takedown_eruption_bonus_hp_ratio,
        )

    def test_immolate_periodic_unchanged(self) -> None:
        # The sustained Immolate proc must stay byte-identical: 15 + 1%
        # bonus HP magic per second per target (Iter 8 pin). At 1000 bonus
        # HP and 1 target: 15 + 0.01 * 1000 = 25.0 per tick.
        ctx = SimpleNamespace(targets_in_rotation=1, caster_bonus_hp=1000.0)
        for iid in (_HR, _HR_ARENA):
            eff = ITEM_EFFECTS[iid]
            self.assertEqual(len(eff.periodics), 1, msg=iid)
            proc = eff.periodics[0]
            self.assertEqual(proc.name, "Immolate", msg=iid)
            self.assertEqual(proc.damage_type, "magical", msg=iid)
            self.assertEqual(proc.every_n_seconds, 1.0, msg=iid)
            self.assertAlmostEqual(proc.bonus_damage(ctx), 25.0, msg=iid)
            self.assertEqual(eff.unique_passive_key, "immolate", msg=iid)

    def test_notes_document_scope(self) -> None:
        for iid in (_HR, _HR_ARENA):
            note = ITEM_EFFECTS[iid].note or ""
            self.assertIn("Desolate", note, msg=iid)
            self.assertIn("assume_takedown", note, msg=iid)
            self.assertIn("non-champion", note, msg=iid)


class VariantSweep(unittest.TestCase):
    """Pool-derived guards: pin only what the 16.13.1 DS pool can rank."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.pool = json.loads(
            _ITEMS_POOL_PATH.read_text(encoding="utf-8")
        )["data"]
        cls.meraki = json.loads(
            _MERAKI_PATH.read_text(encoding="utf-8")
        )["items"]

    def test_registered_ids_exist_in_ds_pool(self) -> None:
        for iid in (_HR, _HR_ARENA):
            self.assertIn(iid, self.pool)

    def test_no_phantom_aram_mirror(self) -> None:
        # 326664 is NOT in the 16.13.1 DS pool - registering it would be a
        # phantom id the ranker can never see (R69 323152 precedent).
        self.assertNotIn(_HR_ARAM_PHANTOM, self.pool)
        self.assertNotIn(_HR_ARAM_PHANTOM, ITEM_EFFECTS)
        self.assertNotIn(_HR_ARAM_PHANTOM, self.meraki)

    def test_arena_mirror_has_no_own_meraki_entry(self) -> None:
        # 226664 carries NO Meraki entry of its own - its pins copy SR 6664
        # per the Arena mirror convention (same reason the Immolate periodic
        # mirrors SR numbers).
        self.assertNotIn(_HR_ARENA, self.meraki)


class EruptionHelper(unittest.TestCase):
    """``total_takedown_eruption_damage`` is a pure additive sum."""

    def test_hr_single(self) -> None:
        helper = _eruption_helper()
        effs = collect_effects([_HR])
        # 60 + 0.04 * 1000 = 100.0
        self.assertAlmostEqual(helper(effs, 1000.0), 100.0)

    def test_arena_single(self) -> None:
        helper = _eruption_helper()
        effs = collect_effects([_HR_ARENA])
        self.assertAlmostEqual(helper(effs, 1000.0), 100.0)

    def test_zero_bonus_hp_base_only(self) -> None:
        helper = _eruption_helper()
        effs = collect_effects([_HR])
        self.assertAlmostEqual(helper(effs, 0.0), 60.0)

    def test_no_carrier_zero(self) -> None:
        # Hubris + Collector sit on the same seam but carry NO eruption
        # fields; boots carry nothing. Sum must be exactly 0.0.
        helper = _eruption_helper()
        effs = collect_effects([_BOOTS, _HUBRIS, _COLLECTOR])
        self.assertEqual(helper(effs, 1000.0), 0.0)


class ZeroFieldGuards(unittest.TestCase):
    """Items that must NOT carry the eruption fields."""

    def test_sunfire_stays_off(self) -> None:
        # Sunfire Aegis 3068 is the sibling immolate item but has NO
        # Desolate passive - its eruption fields stay 0.0.
        eff = ITEM_EFFECTS[_SUNFIRE]
        self.assertEqual(eff.takedown_eruption_base, 0.0)
        self.assertEqual(eff.takedown_eruption_bonus_hp_ratio, 0.0)

    def test_dsv2_siblings_stay_off(self) -> None:
        for iid in (_HUBRIS, _COLLECTOR):
            eff = ITEM_EFFECTS[iid]
            self.assertEqual(eff.takedown_eruption_base, 0.0, msg=iid)
            self.assertEqual(
                eff.takedown_eruption_bonus_hp_ratio, 0.0, msg=iid
            )


class ComputeBurstSeam(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_default_off_byte_identical(self) -> None:
        base = compute_burst_damage(
            self.snap, "Veigar", 11, item_ids=_HR_BUILD,
            target_mr=60, target_max_hp=2000,
        )
        off = compute_burst_damage(
            self.snap, "Veigar", 11, item_ids=_HR_BUILD,
            target_mr=60, target_max_hp=2000, assume_takedown=False,
        )
        self.assertEqual(base.total_burst_damage, off.total_burst_damage)
        self.assertEqual(
            getattr(off, "takedown_eruption_damage", None), 0.0
        )
        self.assertFalse(any("Desolate" in n for n in off.notes))

    def test_seam_on_no_carrier_inert(self) -> None:
        off = compute_burst_damage(
            self.snap, "Veigar", 11, item_ids=_NO_CARRIER_BUILD,
            target_mr=60, target_max_hp=2000,
        )
        on = compute_burst_damage(
            self.snap, "Veigar", 11, item_ids=_NO_CARRIER_BUILD,
            target_mr=60, target_max_hp=2000, assume_takedown=True,
        )
        self.assertAlmostEqual(
            on.total_burst_damage, off.total_burst_damage, places=4
        )
        self.assertEqual(
            getattr(on, "takedown_eruption_damage", None), 0.0
        )

    def test_seam_on_credits_exact_mr_mitigated_eruption(self) -> None:
        # Build has NO Hubris (takedown_bonus_ad = 0) and NO Collector
        # (execute = 0), so the ON-OFF delta must equal the eruption credit
        # EXACTLY. Hand arithmetic at target_mr=60, no pen in build:
        #   mit    = 100 / (100 + 60) = 0.625
        #   raw    = 60 + 0.04 * caster_bonus_hp
        #   credit = raw * mode_mult(1.0 SR) * magic_amp(1.0) * 0.625
        off = compute_burst_damage(
            self.snap, "Veigar", 11, item_ids=_HR_BUILD,
            target_mr=60, target_max_hp=2000,
        )
        on = compute_burst_damage(
            self.snap, "Veigar", 11, item_ids=_HR_BUILD,
            target_mr=60, target_max_hp=2000, assume_takedown=True,
        )
        # Derive caster bonus HP exactly as burst.py does (engine lines:
        # AbilityContext.from_build(stats, base_stats) ->
        # caster_bonus_hp = max(0, caster_max_hp - caster_base_hp)).
        resolved = build_champion(
            self.snap, "Veigar", 11, item_ids=_HR_BUILD, mode="SR",
        )
        ctx = AbilityContext.from_build(
            stats=resolved.stats,
            base_stats=resolved.base_stats,
            target_armor=0.0,
            target_mr=60.0,
            target_max_hp=2000.0,
            target_bonus_hp=0.0,
            target_current_hp_pct=1.0,
        )
        self.assertGreater(ctx.caster_bonus_hp, 0.0)  # HR grants HP
        raw = 60.0 + 0.04 * ctx.caster_bonus_hp
        mit = _mitigation_factor(
            "MAGIC", on.target_armor_after_pen, on.target_mr_after_pen
        )
        self.assertAlmostEqual(mit, 0.625)  # HR carries no magic pen
        expected = raw * mit
        self.assertAlmostEqual(
            getattr(on, "takedown_eruption_damage", -1.0), expected, places=4
        )
        self.assertAlmostEqual(
            on.total_burst_damage - off.total_burst_damage, expected,
            places=4,
        )
        self.assertTrue(any("Desolate" in n for n in on.notes))

    def test_mr_routing_scales_delta(self) -> None:
        # The eruption delta must route through MR: raising only target MR
        # shrinks it by exactly the engine's own MAGIC mitigation ratio.
        def delta(mr: float) -> float:
            off = compute_burst_damage(
                self.snap, "Veigar", 11, item_ids=_HR_BUILD,
                target_mr=mr, target_max_hp=2000,
            )
            on = compute_burst_damage(
                self.snap, "Veigar", 11, item_ids=_HR_BUILD,
                target_mr=mr, target_max_hp=2000, assume_takedown=True,
            )
            return on.total_burst_damage - off.total_burst_damage

        d0 = delta(0.0)
        d100 = delta(100.0)
        self.assertGreater(d0, 0.0)
        self.assertLess(d100, d0)
        expected_ratio = (
            _mitigation_factor("MAGIC", 0.0, 100.0)
            / _mitigation_factor("MAGIC", 0.0, 0.0)
        )
        self.assertAlmostEqual(d100, d0 * expected_ratio, places=2)

    def test_hubris_collector_siblings_unchanged_under_on(self) -> None:
        # Registry pins first (drift here would invalidate the behavior
        # checks below).
        self.assertAlmostEqual(
            ITEM_EFFECTS[_HUBRIS].takedown_bonus_ad_base, 15.0
        )
        self.assertAlmostEqual(
            ITEM_EFFECTS[_HUBRIS].takedown_bonus_ad_per_stack, 2.0
        )
        self.assertAlmostEqual(
            ITEM_EFFECTS[_COLLECTOR].execute_max_hp_pct, 0.05
        )
        on = compute_burst_damage(
            self.snap, "Veigar", 11, item_ids=_SIBLING_BUILD,
            target_mr=60, target_max_hp=2000, assume_takedown=True,
        )
        # Hubris Eminence at 1 assumed stack: 15 + 2*1 = 17 bonus AD.
        self.assertAlmostEqual(on.takedown_bonus_ad, 17.0)
        # Collector execute: 5% of 2000 target max HP = 100 true damage.
        self.assertAlmostEqual(on.execute_finisher_damage, 100.0)
        # And the HR eruption is credited alongside, not instead.
        self.assertGreater(
            getattr(on, "takedown_eruption_damage", 0.0), 0.0
        )

    def test_to_dict_carries_field(self) -> None:
        on = compute_burst_damage(
            self.snap, "Veigar", 11, item_ids=_HR_BUILD,
            target_mr=60, target_max_hp=2000, assume_takedown=True,
        )
        d = on.to_dict()
        self.assertIn("takedown_eruption_damage", d)
        self.assertAlmostEqual(
            d["takedown_eruption_damage"], on.takedown_eruption_damage,
        )


if __name__ == "__main__":
    unittest.main()
