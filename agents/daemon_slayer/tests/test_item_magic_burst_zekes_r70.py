"""R70 slice A (2026-07-03) - Zeke's Convergence item-passive magic burst.

Meraki 16.13.1 item 3050 Zeke's Convergence passive "Frostfire Tempest":
"Upon casting your ultimate ability, you summon a storm of flame and ice
around you for 5 seconds, dealing {{ap|30/4}} magic damage every 0.25
seconds | {{ap|30*5}} total magic damage over the duration ... within 350
units ... (45 second cooldown, starts on ultimate cast)." That is 150.0
total FLAT magic per ult cast (no AP ratio anywhere in the text), a
SELF-centered storm - 16.13.1 has NO ally tether (the old "Conduit"
tether-ally shape is gone; the stale registry notes said otherwise).

The per-cast total rides the EXISTING default-OFF DSV6
``assume_magic_burst`` seam (ItemEffect ``magic_burst_base`` /
``magic_burst_ap_ratio`` since 1.152.0, _effects_types.py:793-794;
consumed ONLY by ``compute_burst_damage`` under the assume_magic_burst
gate via ``total_magic_burst_damage`` at effects.py:349). Pure DATA pin -
no schema change, and this file deliberately does NOT assert
ENGINE_VERSION (a sibling R70 slice owns the bump).

The DPS side stays intentionally unmodeled: a 45s-CD ult-triggered storm
is not a sustained stream, there is no PeriodicProc, so nothing
double-counts. The sibling passive "Cryocombustion" (ult haste) is
ALREADY carried by the _item_ability_haste.py lane - not re-added here.

``defensive_only`` stays True on all three entries: the flag is
documentation-only (no engine consumer in rank/dps/burst/effects filters
on it; collect_effects passes every registered entry through to
total_magic_burst_damage), and batch-35/42/43 coverage tests pin it.

Variant sweep (16.13.1 DS pool): exactly three Zeke's ids exist - 3050
(SR, maps 11/12/21/35), 223050 (Arena map-30 mirror), 323050 (ARAM
mirror, map-11 flagged in pool data). Only 3050 carries a Meraki entry;
the mirrors ride the SR truth per the mirror convention. No 443050
distributed variant exists (guarded absent, R68/R69 phantom-id pattern).
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from agents.daemon_slayer._item_ability_haste import _ITEM_ABILITY_HASTE
from agents.daemon_slayer.ability_dps import _mitigation_factor
from agents.daemon_slayer.burst import compute_burst_damage
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.effects import (
    ITEM_EFFECTS,
    collect_effects,
    total_magic_burst_damage,
)

_PATCH = "16.13.1"
_REPO_ROOT = Path(__file__).resolve().parents[3]
_MERAKI_PATH = (
    _REPO_ROOT / "data" / "daemon_slayer" / _PATCH / "items_meraki.json"
)
_ITEMS_POOL_PATH = (
    _REPO_ROOT / "data" / "daemon_slayer" / _PATCH / "items.json"
)

_ZEKES = "3050"
_ZEKES_ARENA = "223050"
_ZEKES_ARAM = "323050"
_ZEKES_ALL = (_ZEKES, _ZEKES_ARENA, _ZEKES_ARAM)
_ZEKES_PHANTOM = "443050"  # no distributed variant in the 16.13.1 pool

# R69 carriers + existing DSV6 carrier - sibling guards pin them unchanged.
_ROCKETBELT = "3152"
_ROCKETBELT_ARENA = "223152"
_LUDENS = "6655"

# Non-magic items - must stay off the seam.
_BOTRK = "3153"
_THORNMAIL = "3075"

_NO_BURST_BUILD = ["3047"]  # Plated Steelcaps - no magic_burst field
_ZEKES_BUILD = ["3047", _ZEKES]


class MerakiTruth(unittest.TestCase):
    """Registry pins derive from the vendored Meraki 16.13.1 passive text;
    a patch changing the numbers fails HERE instead of silently drifting."""

    @classmethod
    def setUpClass(cls) -> None:
        doc = json.loads(_MERAKI_PATH.read_text(encoding="utf-8"))
        cls.meraki = doc["items"]
        passives = cls.meraki[_ZEKES]["passives"]
        entry = next(
            (p for p in passives if p.get("name") == "Frostfire Tempest"),
            None,
        )
        assert entry is not None, "Meraki 3050 has no 'Frostfire Tempest'"
        cls.text = entry["effects"]

    def _parse_total(self) -> int:
        m = re.search(
            r"\{\{ap\|(\d+)\*(\d+)\}\} '''total''' magic damage", self.text
        )
        self.assertIsNotNone(
            m, f"Frostfire total formula not found in: {self.text!r}"
        )
        return int(m.group(1)) * int(m.group(2))

    def test_frostfire_total_magnitude(self) -> None:
        # {{ap|30*5}} '''total''' magic damage => 150 flat per ult cast.
        self.assertEqual(self._parse_total(), 150)

    def test_frostfire_tick_consistency(self) -> None:
        # {{ap|30/4}} magic every 0.25s over the 5s storm = 20 ticks of
        # 7.5 = 150 - the tick lane and the total lane must agree.
        m = re.search(
            r"\{\{ap\|(\d+)/(\d+)\}\} magic damage\}\} "
            r"every \{\{fd\|0\.25\}\} seconds",
            self.text,
        )
        self.assertIsNotNone(
            m, f"Frostfire tick formula not found in: {self.text!r}"
        )
        per_tick = int(m.group(1)) / int(m.group(2))
        dur = re.search(r"around you for (\d+) seconds", self.text)
        self.assertIsNotNone(dur)
        ticks = int(dur.group(1)) / 0.25
        self.assertAlmostEqual(per_tick * ticks, float(self._parse_total()))

    def test_ult_cast_trigger_and_cooldown(self) -> None:
        self.assertIn("Upon casting your ultimate ability", self.text)
        m = re.search(
            r"\((\d+) second cooldown, starts on ultimate cast\)", self.text
        )
        self.assertIsNotNone(
            m, f"Frostfire cooldown clause not found in: {self.text!r}"
        )
        self.assertEqual(int(m.group(1)), 45)

    def test_self_centered_storm_no_ally_tether(self) -> None:
        # 16.13.1 Frostfire Tempest is SELF-centered ("around you ...
        # within 350 units") - the stale registry note claimed a
        # tether-ally proximity requirement that no longer exists.
        self.assertIn("around you", self.text)
        self.assertIn("350 units", self.text)
        self.assertNotIn("ally", self.text.lower())

    def test_no_ap_ratio_in_meraki_text(self) -> None:
        # Flat-only magnitude => the ap_ratio pin must be 0.0.
        self.assertNotIn("% AP", self.text)

    def test_mirror_ids_have_no_meraki_entry(self) -> None:
        # Arena/ARAM mirrors carry no Meraki entry; their pins ride the
        # SR 3050 truth per the mirror convention (R69 223152 pattern).
        self.assertNotIn(_ZEKES_ARENA, self.meraki)
        self.assertNotIn(_ZEKES_ARAM, self.meraki)

    def test_registry_matches_meraki_values(self) -> None:
        total = float(self._parse_total())
        for iid in _ZEKES_ALL:
            eff = ITEM_EFFECTS[iid]
            self.assertAlmostEqual(eff.magic_burst_base, total, msg=iid)
            self.assertAlmostEqual(eff.magic_burst_ap_ratio, 0.0, msg=iid)


class RegistryPins(unittest.TestCase):
    """Hand-authored pins: 3050 / 223050 / 323050 carry the seam fields."""

    def test_zekes_pins(self) -> None:
        for iid in _ZEKES_ALL:
            eff = ITEM_EFFECTS[iid]
            self.assertAlmostEqual(eff.magic_burst_base, 150.0, msg=iid)
            self.assertAlmostEqual(eff.magic_burst_ap_ratio, 0.0, msg=iid)

    def test_mirrors_match_sr_exactly(self) -> None:
        base = ITEM_EFFECTS[_ZEKES]
        for iid in (_ZEKES_ARENA, _ZEKES_ARAM):
            mirror = ITEM_EFFECTS[iid]
            self.assertAlmostEqual(
                mirror.magic_burst_base, base.magic_burst_base, msg=iid
            )
            self.assertAlmostEqual(
                mirror.magic_burst_ap_ratio,
                base.magic_burst_ap_ratio,
                msg=iid,
            )

    def test_defensive_only_flag_retained(self) -> None:
        # defensive_only is documentation-only (no engine consumer filters
        # on it - collect_effects passes every entry through to
        # total_magic_burst_damage). It stays True: the entries still have
        # no sustained-DPS proc, and batch-35/42/43 coverage tests pin it.
        for iid in _ZEKES_ALL:
            eff = ITEM_EFFECTS[iid]
            self.assertTrue(eff.defensive_only, msg=iid)
            self.assertEqual(len(eff.periodics), 0, msg=iid)

    def test_cryocombustion_haste_lane_untouched(self) -> None:
        # The sibling passive Cryocombustion (ult haste) is carried by the
        # _item_ability_haste.py lane - this slice must not re-add it to
        # the effects registry (membership guard only; the hand-pinned
        # values are that registry's own concern).
        for iid in _ZEKES_ALL:
            self.assertIn(iid, _ITEM_ABILITY_HASTE, msg=iid)


class VariantSweep(unittest.TestCase):
    """Pool-derived guards: pin only what the 16.13.1 DS pool can rank."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.pool = json.loads(
            _ITEMS_POOL_PATH.read_text(encoding="utf-8")
        )["data"]

    def test_registered_ids_exist_in_ds_pool(self) -> None:
        for iid in _ZEKES_ALL:
            self.assertIn(iid, self.pool)

    def test_pool_map_flags_obtainable(self) -> None:
        # Unlike the R69 legacy-Everfrost case (all map flags False =>
        # unpinned), every Zeke's id is obtainable on at least one map.
        self.assertTrue(self.pool[_ZEKES]["maps"]["11"])
        self.assertTrue(self.pool[_ZEKES_ARENA]["maps"]["30"])
        for iid in _ZEKES_ALL:
            self.assertTrue(
                any((self.pool[iid].get("maps") or {}).values()), msg=iid
            )

    def test_pool_has_exactly_three_zekes_ids(self) -> None:
        found = {k for k in self.pool if k.endswith("3050")}
        self.assertEqual(found, set(_ZEKES_ALL))

    def test_no_phantom_distributed_variant(self) -> None:
        # 443050 is NOT in the 16.13.1 DS pool - registering it would be a
        # phantom id the ranker can never see (R68/R69 pattern).
        self.assertNotIn(_ZEKES_PHANTOM, self.pool)
        self.assertNotIn(_ZEKES_PHANTOM, ITEM_EFFECTS)


class MagicBurstHelper(unittest.TestCase):
    """``total_magic_burst_damage`` folds the new pins additively."""

    def test_zekes_single_flat_at_500_ap(self) -> None:
        effs = collect_effects([_ZEKES])
        # ap_ratio 0.0: a lone 3050 contributes exactly 150.0 at 500 AP.
        self.assertAlmostEqual(total_magic_burst_damage(effs, 500.0), 150.0)

    def test_zekes_ap_invariant(self) -> None:
        effs = collect_effects([_ZEKES])
        for ap in (0.0, 1000.0):
            self.assertAlmostEqual(
                total_magic_burst_damage(effs, ap), 150.0, msg=str(ap)
            )

    def test_mirror_singles(self) -> None:
        for iid in (_ZEKES_ARENA, _ZEKES_ARAM):
            effs = collect_effects([iid])
            self.assertAlmostEqual(
                total_magic_burst_damage(effs, 500.0), 150.0, msg=iid
            )

    def test_additive_with_existing_carrier(self) -> None:
        effs = collect_effects([_ZEKES, _LUDENS])
        # 150 + (75 + 0.05 * 200) = 235 at AP=200.
        self.assertAlmostEqual(total_magic_burst_damage(effs, 200.0), 235.0)


class ComputeBurstSeam(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_default_off_byte_identical(self) -> None:
        base = compute_burst_damage(
            self.snap, "Veigar", 11, item_ids=_ZEKES_BUILD,
            target_mr=60, target_max_hp=2000,
        )
        off = compute_burst_damage(
            self.snap, "Veigar", 11, item_ids=_ZEKES_BUILD,
            target_mr=60, target_max_hp=2000, assume_magic_burst=False,
        )
        self.assertEqual(base.total_burst_damage, off.total_burst_damage)

    def test_seam_on_no_field_build_byte_identical(self) -> None:
        # A build with no magic_burst carrier is inert even with the flag ON.
        off = compute_burst_damage(
            self.snap, "Veigar", 11, item_ids=_NO_BURST_BUILD,
            target_mr=60, target_max_hp=2000,
        )
        on = compute_burst_damage(
            self.snap, "Veigar", 11, item_ids=_NO_BURST_BUILD,
            target_mr=60, target_max_hp=2000, assume_magic_burst=True,
        )
        self.assertAlmostEqual(
            on.total_burst_damage, off.total_burst_damage, places=4
        )

    def test_seam_on_zekes_credits_flat_magnitude(self) -> None:
        off = compute_burst_damage(
            self.snap, "Veigar", 11, item_ids=_ZEKES_BUILD,
            target_mr=0, target_max_hp=2000,
        )
        on = compute_burst_damage(
            self.snap, "Veigar", 11, item_ids=_ZEKES_BUILD,
            target_mr=0, target_max_hp=2000, assume_magic_burst=True,
        )
        self.assertGreater(on.total_burst_damage, off.total_burst_damage)
        # At target_mr=0 (MAGIC factor 1.0), SR (mode_mult 1.0), no magic
        # amp item in the build (magic_amp 1.0) and ap_ratio 0.0, the
        # delta is exactly the 150 flat storm total.
        self.assertAlmostEqual(
            on.total_burst_damage - off.total_burst_damage, 150.0, places=2
        )

    def test_mr_routing_scales_delta(self) -> None:
        # The Zeke's delta must route through MR: mitigating only MR
        # shrinks it by exactly the engine's own MAGIC mitigation ratio
        # (Zeke's ItemEffect carries no magic pen, so target_mr_eff equals
        # the raw target_mr and the expected ratio is clean).
        def delta(mr: float) -> float:
            off = compute_burst_damage(
                self.snap, "Veigar", 11, item_ids=_ZEKES_BUILD,
                target_mr=mr, target_max_hp=2000,
            )
            on = compute_burst_damage(
                self.snap, "Veigar", 11, item_ids=_ZEKES_BUILD,
                target_mr=mr, target_max_hp=2000, assume_magic_burst=True,
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


class SiblingGuards(unittest.TestCase):
    """R69 + existing DSV6 carriers keep their pins; non-magic stays off."""

    def test_r69_and_existing_carriers_unchanged(self) -> None:
        for iid, base, ratio in (
            (_ROCKETBELT, 100.0, 0.10),
            (_ROCKETBELT_ARENA, 100.0, 0.10),
            (_LUDENS, 75.0, 0.05),
        ):
            eff = ITEM_EFFECTS[iid]
            self.assertAlmostEqual(eff.magic_burst_base, base, msg=iid)
            self.assertAlmostEqual(eff.magic_burst_ap_ratio, ratio, msg=iid)

    def test_physical_and_tank_items_stay_off_seam(self) -> None:
        for iid in (_BOTRK, _THORNMAIL):
            eff = ITEM_EFFECTS[iid]
            self.assertEqual(eff.magic_burst_base, 0.0, msg=iid)
            self.assertEqual(eff.magic_burst_ap_ratio, 0.0, msg=iid)


if __name__ == "__main__":
    unittest.main()
