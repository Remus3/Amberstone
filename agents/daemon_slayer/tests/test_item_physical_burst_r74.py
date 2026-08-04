"""R74 (2026-07-03) - Goredrinker Thirsting Slash on the NEW DSV8 physical-burst seam.

Meraki 16.13.1 item 226630 Goredrinker (Arena-only) active "Thirsting
Slash": "Deal {{as|175% '''base''' AD}} {{as|physical damage}} to enemies
in a ... 450 radius centered around you." The heal side ("20% AD (+ 8% of
your '''missing''' health) for each enemy champion hit") stays UNMODELED.

DSV8 is the PHYSICAL analogue of the DSV6 ``assume_magic_burst`` seam:
two END-appended ItemEffect fields ``physical_burst_base`` /
``physical_burst_base_ad_ratio`` (single-cast burst-window magnitude =
base + ratio * caster BASE AD), a pure facade helper
``effects.total_physical_burst_damage``, and a compute_burst_damage fold
gated on the default-OFF ``assume_physical_burst`` kwarg
(armor-mitigated PHYSICAL routing x mode_mult; NO amp layer - the engine
has no physical analogue of total_magic_amp_multiplier and the DSV6
item-proc block deliberately excludes build amps). The DPS side stays
intentionally unmodeled: long-CD active, no PeriodicProc, so compute_dps
sees nothing and nothing double-counts. compute_ability_dps accepts the
flag as a documented-inert kwarg for API symmetry only (mirrors
assume_magic_burst).

``defensive_only`` stays True on 226630: the flag is documentation-only
(no engine consumer in rank/dps/burst/effects filters on it - verified
R69, re-verified R74: only docstring prose in effects.py:23 + ehp.py:71),
and ``collect_effects`` passes every registered entry through to
``total_physical_burst_damage`` regardless of the flag.

Variant sweep (16.13.1 DS pool): 226630 is the ONLY obtainable
Goredrinker (map 30 True). Legacy SR 6630 exists in items.json with every
map flag False and has NO Meraki entry - unobtainable, stays UNPINNED.
326630 / 446630 exist in neither the pool nor the Meraki mirror.
"""
from __future__ import annotations

import dataclasses
import json
import re
import unittest
from pathlib import Path

from agents import daemon_slayer
from agents.daemon_slayer import ENGINE_VERSION
from agents.daemon_slayer.ability_dps import (
    _mitigation_factor,
    compute_ability_dps,
)
from agents.daemon_slayer.burst import compute_burst_damage
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.effects import (
    ITEM_EFFECTS,
    ItemEffect,
    collect_effects,
    total_magic_burst_damage,
    total_physical_burst_damage,
)
from agents.daemon_slayer.engine import build_champion

_PATCH = "16.13.1"
_REPO_ROOT = Path(__file__).resolve().parents[3]
_MERAKI_PATH = (
    _REPO_ROOT / "data" / "daemon_slayer" / _PATCH / "items_meraki.json"
)
_ITEMS_POOL_PATH = (
    _REPO_ROOT / "data" / "daemon_slayer" / _PATCH / "items.json"
)

_GOREDRINKER_ARENA = "226630"
_GOREDRINKER_LEGACY = "6630"  # map-disabled, no Meraki truth - stays unpinned
_GOREDRINKER_PHANTOMS = ("326630", "446630")  # in neither pool nor Meraki

# Existing DSV6 magic carrier - cross-seam isolation guard.
_LUDENS = "6655"

# Non-physical-burst items - must stay off the seam.
_THORNMAIL = "3075"

_NO_BURST_BUILD = ["3047"]  # Plated Steelcaps - no burst fields
_GOREDRINKER_BUILD = ["3047", _GOREDRINKER_ARENA]


class EngineVersion(unittest.TestCase):
    def test_engine_version_bumped(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.271.0")
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.271.0")


class SchemaDefaults(unittest.TestCase):
    """END-appended fields default 0.0 - every existing item is inert."""

    def test_defaults_are_zero(self) -> None:
        eff = ItemEffect(item_id="0", name="synthetic")
        self.assertEqual(eff.physical_burst_base, 0.0)
        self.assertEqual(eff.physical_burst_base_ad_ratio, 0.0)

    def test_fields_appended_at_end(self) -> None:
        # Mid-class insert breaks positional construction (repo convention).
        # R75 DSV9 END-appended its own pair after this one, so the durable
        # convention check is "contiguous, in order, after the R70 takedown
        # pair" - a LAST-two pin would go stale on every later seam (the
        # newest seam's own test owns the last-two assertion).
        names = [f.name for f in dataclasses.fields(ItemEffect)]
        i = names.index("physical_burst_base")
        self.assertEqual(
            names[i:i + 2],
            ["physical_burst_base", "physical_burst_base_ad_ratio"],
        )
        self.assertGreater(
            i, names.index("takedown_eruption_bonus_hp_ratio")
        )


class MerakiTruth(unittest.TestCase):
    """Registry pin derives from the vendored Meraki 16.13.1 active text;
    a patch changing the numbers fails HERE instead of silently drifting."""

    @classmethod
    def setUpClass(cls) -> None:
        doc = json.loads(_MERAKI_PATH.read_text(encoding="utf-8"))
        actives = doc["items"][_GOREDRINKER_ARENA]["active"]
        entry = next(
            (a for a in actives if a.get("name") == "Thirsting Slash"), None
        )
        assert entry is not None, "Meraki 226630 has no 'Thirsting Slash'"
        cls.text = entry["effects"]

    def _parse_ratio(self) -> int:
        m = re.search(
            r"Deal \{\{as\|(\d+)% '''base''' AD\}\} "
            r"\{\{as\|physical damage\}\}",
            self.text,
        )
        self.assertIsNotNone(
            m, f"Thirsting Slash formula not found in: {self.text!r}"
        )
        return int(m.group(1))

    def test_meraki_magnitude(self) -> None:
        self.assertEqual(self._parse_ratio(), 175)
        # AoE semantics - one cast hits everything in the radius; the seam
        # credits the single-cast magnitude once (single-target model).
        self.assertIn("450 radius", self.text)

    def test_heal_side_present_but_unmodeled(self) -> None:
        # The heal rider exists in the truth text (20% AD + 8% missing HP
        # per champion hit) and is deliberately NOT modeled - no heal field
        # on the entry, damage-lane only.
        self.assertIn("{{tip|Heal}}", self.text)
        self.assertIn("missing", self.text)

    def test_registry_matches_meraki_value(self) -> None:
        ratio = self._parse_ratio()
        eff = ITEM_EFFECTS[_GOREDRINKER_ARENA]
        self.assertAlmostEqual(
            eff.physical_burst_base_ad_ratio, ratio / 100.0
        )
        self.assertEqual(eff.physical_burst_base, 0.0)  # no flat term


class RegistryPins(unittest.TestCase):
    """Hand-authored pin: 226630 carries the DSV8 seam fields."""

    def test_goredrinker_pin(self) -> None:
        eff = ITEM_EFFECTS[_GOREDRINKER_ARENA]
        self.assertEqual(eff.physical_burst_base, 0.0)
        self.assertAlmostEqual(eff.physical_burst_base_ad_ratio, 1.75)

    def test_no_cross_seam_bleed(self) -> None:
        # The physical pin must NOT leak onto the magic seam.
        eff = ITEM_EFFECTS[_GOREDRINKER_ARENA]
        self.assertEqual(eff.magic_burst_base, 0.0)
        self.assertEqual(eff.magic_burst_ap_ratio, 0.0)

    def test_defensive_only_flag_retained_and_no_periodics(self) -> None:
        # defensive_only is documentation-only (no engine consumer filters
        # on it - re-verified R74: effects.py:23 + ehp.py:71 are docstring
        # prose only). It stays True: the entry still has no sustained-DPS
        # proc, so compute_dps sees nothing from Goredrinker.
        eff = ITEM_EFFECTS[_GOREDRINKER_ARENA]
        self.assertTrue(eff.defensive_only)
        self.assertEqual(len(eff.periodics), 0)

    def test_compute_dps_surface_untouched(self) -> None:
        # Beyond the DSV8 pair + identity/doc fields, 226630 must equal a
        # default ItemEffect - proving compute_dps (which never reads the
        # DSV8 pair) has nothing else to consume.
        eff = ITEM_EFFECTS[_GOREDRINKER_ARENA]
        default = ItemEffect(item_id="0", name="synthetic")
        skip = {
            "item_id", "name", "note", "defensive_only",
            "physical_burst_base", "physical_burst_base_ad_ratio",
        }
        for f in dataclasses.fields(ItemEffect):
            if f.name in skip:
                continue
            self.assertEqual(
                getattr(eff, f.name), getattr(default, f.name), msg=f.name
            )

    def test_non_physical_items_stay_off_seam(self) -> None:
        for iid in (_LUDENS, _THORNMAIL):
            eff = ITEM_EFFECTS[iid]
            self.assertEqual(eff.physical_burst_base, 0.0, msg=iid)
            self.assertEqual(eff.physical_burst_base_ad_ratio, 0.0, msg=iid)


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

    def test_arena_id_is_the_obtainable_one(self) -> None:
        self.assertIn(_GOREDRINKER_ARENA, self.pool)
        maps = self.pool[_GOREDRINKER_ARENA].get("maps") or {}
        self.assertTrue(maps.get("30"), "226630 must be Arena (map 30)")

    def test_legacy_sr_goredrinker_stays_unpinned(self) -> None:
        # 6630 exists in items.json but with every map flag False
        # (unobtainable) and carries NO Meraki entry - there is no 16.13.1
        # truth to pin, so its physical_burst fields stay inert.
        self.assertIn(_GOREDRINKER_LEGACY, self.pool)
        self.assertFalse(
            any((self.pool[_GOREDRINKER_LEGACY].get("maps") or {}).values())
        )
        self.assertNotIn(_GOREDRINKER_LEGACY, self.meraki)
        eff = ITEM_EFFECTS[_GOREDRINKER_LEGACY]
        self.assertEqual(eff.physical_burst_base, 0.0)
        self.assertEqual(eff.physical_burst_base_ad_ratio, 0.0)

    def test_no_phantom_goredrinker_variants(self) -> None:
        # 326630 / 446630 are in NEITHER the 16.13.1 DS pool NOR the Meraki
        # mirror - registering either would be a phantom id (R68 pattern).
        for iid in _GOREDRINKER_PHANTOMS:
            self.assertNotIn(iid, self.pool, msg=iid)
            self.assertNotIn(iid, self.meraki, msg=iid)
            self.assertNotIn(iid, ITEM_EFFECTS, msg=iid)


class PhysicalBurstHelper(unittest.TestCase):
    """``total_physical_burst_damage`` facade unit math."""

    def test_goredrinker_single(self) -> None:
        effs = collect_effects([_GOREDRINKER_ARENA])
        # 0 + 1.75 * 100 = 175.
        self.assertAlmostEqual(
            total_physical_burst_damage(effs, 100.0), 175.0
        )

    def test_scales_with_base_ad_only(self) -> None:
        effs = collect_effects([_GOREDRINKER_ARENA])
        self.assertAlmostEqual(total_physical_burst_damage(effs, 0.0), 0.0)
        self.assertAlmostEqual(
            total_physical_burst_damage(effs, 80.0), 140.0
        )

    def test_no_carrier_build_returns_zero(self) -> None:
        effs = collect_effects(_NO_BURST_BUILD)
        self.assertEqual(total_physical_burst_damage(effs, 999.0), 0.0)

    def test_cross_seam_isolation(self) -> None:
        # The magic helper ignores the physical pin and vice versa.
        effs = collect_effects([_GOREDRINKER_ARENA, _LUDENS])
        # Physical: only Goredrinker contributes (1.75 * 100).
        self.assertAlmostEqual(
            total_physical_burst_damage(effs, 100.0), 175.0
        )
        # Magic: only Luden's contributes (75 + 0.05 * 200).
        self.assertAlmostEqual(total_magic_burst_damage(effs, 200.0), 85.0)


class ComputeBurstSeam(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_default_off_byte_identical(self) -> None:
        base = compute_burst_damage(
            self.snap, "Darius", 11, item_ids=_GOREDRINKER_BUILD,
            mode="ARENA", target_armor=60, target_max_hp=2000,
        )
        off = compute_burst_damage(
            self.snap, "Darius", 11, item_ids=_GOREDRINKER_BUILD,
            mode="ARENA", target_armor=60, target_max_hp=2000,
            assume_physical_burst=False,
        )
        self.assertEqual(base.total_burst_damage, off.total_burst_damage)

    def test_seam_on_no_field_build_byte_identical(self) -> None:
        # A build with no physical_burst carrier is inert even with the
        # flag ON.
        off = compute_burst_damage(
            self.snap, "Darius", 11, item_ids=_NO_BURST_BUILD,
            mode="ARENA", target_armor=60, target_max_hp=2000,
        )
        on = compute_burst_damage(
            self.snap, "Darius", 11, item_ids=_NO_BURST_BUILD,
            mode="ARENA", target_armor=60, target_max_hp=2000,
            assume_physical_burst=True,
        )
        self.assertAlmostEqual(
            on.total_burst_damage, off.total_burst_damage, places=4
        )

    def test_seam_on_credits_175_pct_base_ad(self) -> None:
        # At armor 0 (PHYSICAL factor 1.0), ARENA (mode_mult 1.0), no amp
        # layer, the delta is exactly 1.75 * the champion's BASE AD at
        # level (build items add no armor pen here, so armor_eff = 0).
        off = compute_burst_damage(
            self.snap, "Darius", 11, item_ids=_GOREDRINKER_BUILD,
            mode="ARENA", target_armor=0, target_max_hp=2000,
        )
        on = compute_burst_damage(
            self.snap, "Darius", 11, item_ids=_GOREDRINKER_BUILD,
            mode="ARENA", target_armor=0, target_max_hp=2000,
            assume_physical_burst=True,
        )
        resolved = build_champion(
            self.snap, "Darius", 11, item_ids=_GOREDRINKER_BUILD,
            mode="ARENA",
        )
        base_ad = float(resolved.base_stats["ad"])
        self.assertGreater(base_ad, 0.0)
        self.assertAlmostEqual(
            on.total_burst_damage - off.total_burst_damage,
            1.75 * base_ad,
            places=2,
        )

    def test_armor_routing_scales_delta(self) -> None:
        # The Goredrinker delta must route through ARMOR: raising only
        # armor shrinks it by exactly the engine's own PHYSICAL mitigation
        # ratio (226630's ItemEffect carries no armor pen, so armor_eff
        # equals the raw target_armor and the expected ratio is clean).
        def delta(armor: float) -> float:
            off = compute_burst_damage(
                self.snap, "Darius", 11, item_ids=_GOREDRINKER_BUILD,
                mode="ARENA", target_armor=armor, target_max_hp=2000,
            )
            on = compute_burst_damage(
                self.snap, "Darius", 11, item_ids=_GOREDRINKER_BUILD,
                mode="ARENA", target_armor=armor, target_max_hp=2000,
                assume_physical_burst=True,
            )
            return on.total_burst_damage - off.total_burst_damage

        d0 = delta(0.0)
        d100 = delta(100.0)
        self.assertGreater(d0, 0.0)
        self.assertLess(d100, d0)
        expected_ratio = (
            _mitigation_factor("PHYSICAL", 100.0, 0.0)
            / _mitigation_factor("PHYSICAL", 0.0, 0.0)
        )
        self.assertAlmostEqual(d100, d0 * expected_ratio, places=2)

    def test_mr_insensitive(self) -> None:
        # A PHYSICAL burst must not care about MR.
        def delta(mr: float) -> float:
            off = compute_burst_damage(
                self.snap, "Darius", 11, item_ids=_GOREDRINKER_BUILD,
                mode="ARENA", target_armor=60, target_mr=mr,
                target_max_hp=2000,
            )
            on = compute_burst_damage(
                self.snap, "Darius", 11, item_ids=_GOREDRINKER_BUILD,
                mode="ARENA", target_armor=60, target_mr=mr,
                target_max_hp=2000, assume_physical_burst=True,
            )
            return on.total_burst_damage - off.total_burst_damage

        self.assertAlmostEqual(delta(0.0), delta(200.0), places=4)


class AbilityDpsInertKwarg(unittest.TestCase):
    """compute_ability_dps accepts assume_physical_burst for API symmetry
    but is DELIBERATELY INERT (mirrors the DSV6 assume_magic_burst kwarg)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_inert_on_equals_off(self) -> None:
        off = compute_ability_dps(
            self.snap, "Darius", 11, item_ids=_GOREDRINKER_BUILD,
            mode="ARENA", target_armor=60, target_max_hp=2000,
            assume_physical_burst=False,
        )
        on = compute_ability_dps(
            self.snap, "Darius", 11, item_ids=_GOREDRINKER_BUILD,
            mode="ARENA", target_armor=60, target_max_hp=2000,
            assume_physical_burst=True,
        )
        self.assertEqual(on.total_ability_dps, off.total_ability_dps)


if __name__ == "__main__":
    unittest.main()
