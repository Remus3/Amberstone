"""R69 (2026-07-03) - Rocketbelt/Everfrost item-active magic burst on DSV6 seam.

Meraki 16.13.1 item 3152 Hextech Rocketbelt active "Supersonic": enemies
hit by the dash or any rocket explosion "are dealt {{as|100 {{as|(+ 10%
AP)}} magic damage|magic damage}}, once per cast." Item 446656 Everfrost
(the Arena map-30 DISTRIBUTED variant) active "Glaciate": "dealing
{{as|300|magic damage}} {{as|(+ 85% AP)}} {{as|magic damage}}" in a cone.

Both are one-cast active bursts, so their one-cast magnitude rides the
EXISTING default-OFF DSV6 ``assume_magic_burst`` seam (ItemEffect
``magic_burst_base`` / ``magic_burst_ap_ratio`` since 1.152.0; consumed
ONLY by ``compute_burst_damage`` at burst.py assume_magic_burst gate).
No schema change and no new seam. The DPS side stays intentionally
unmodeled: a long-CD active is not a sustained stream, there is no
PeriodicProc, so nothing double-counts.

``defensive_only`` stays True on all three entries: the flag is
documentation-only (defined _effects_types.py:687; described
effects.py:23) - no engine consumer in rank/dps/burst/effects filters on
it, and ``collect_effects`` (effects.py:72-83) passes every registered
entry through to ``total_magic_burst_damage`` regardless of the flag.
Batch-31/40/43 coverage tests pin defensive_only=True + no periodics for
these exact ids; both stay true after R69.

Variant sweep (16.13.1 DS pool): Rocketbelt = 3152 (SR) + 223152 (Arena
map-30 mirror, same numbers per mirror convention); no 323152. Everfrost
= 446656 (map-30 distributed) plus LEGACY 6656 / 226656 which exist in
items.json with every map flag False and have NO Meraki entry - they are
unobtainable and stay UNPINNED (magic_burst fields 0.0).
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from agents import daemon_slayer
from agents.daemon_slayer import ENGINE_VERSION
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

_ROCKETBELT = "3152"
_ROCKETBELT_ARENA = "223152"
_EVERFROST_ARENA = "446656"
_EVERFROST_LEGACY = ("6656", "226656")  # map-disabled, no Meraki truth

# Existing DSV6 carriers - sibling guards pin their values unchanged.
_LUDENS = "6655"
_STORMSURGE = "4646"
_MALIGNANCE = "3118"

# Non-magic items - must stay off the seam.
_BOTRK = "3153"
_THORNMAIL = "3075"

_NO_BURST_BUILD = ["3047"]  # Plated Steelcaps - no magic_burst field
_ROCKETBELT_BUILD = ["3047", _ROCKETBELT]


class EngineVersion(unittest.TestCase):
    def test_engine_version_bumped(self) -> None:
        self.assertEqual(ENGINE_VERSION, "1.237.0")
        self.assertEqual(daemon_slayer.ENGINE_VERSION, "1.237.0")


class MerakiTruth(unittest.TestCase):
    """Registry pins derive from the vendored Meraki 16.13.1 active text;
    a patch changing the numbers fails HERE instead of silently drifting."""

    @classmethod
    def setUpClass(cls) -> None:
        doc = json.loads(_MERAKI_PATH.read_text(encoding="utf-8"))
        cls.texts = {}
        for iid, active_name in (
            (_ROCKETBELT, "Supersonic"),
            (_EVERFROST_ARENA, "Glaciate"),
        ):
            actives = doc["items"][iid]["active"]
            entry = next(
                (a for a in actives if a.get("name") == active_name), None
            )
            assert entry is not None, f"Meraki {iid} has no '{active_name}'"
            cls.texts[iid] = entry["effects"]

    def _parse_rocketbelt(self) -> tuple[int, int]:
        m = re.search(
            r"dealt \{\{as\|(\d+) \{\{as\|\(\+ (\d+)% AP\)\}\} magic damage",
            self.texts[_ROCKETBELT],
        )
        self.assertIsNotNone(
            m, f"Supersonic formula not found in: {self.texts[_ROCKETBELT]!r}"
        )
        return int(m.group(1)), int(m.group(2))

    def _parse_everfrost(self) -> tuple[int, int]:
        m = re.search(
            r"dealing \{\{as\|(\d+)\|magic damage\}\} "
            r"\{\{as\|\(\+ (\d+)% AP\)\}\}",
            self.texts[_EVERFROST_ARENA],
        )
        self.assertIsNotNone(
            m,
            f"Glaciate formula not found in: {self.texts[_EVERFROST_ARENA]!r}",
        )
        return int(m.group(1)), int(m.group(2))

    def test_rocketbelt_meraki_magnitude(self) -> None:
        base, pct = self._parse_rocketbelt()
        self.assertEqual(base, 100)
        self.assertEqual(pct, 10)
        # One-cast semantics: the damage lands once per active cast, which
        # is exactly the burst-window magnitude the DSV6 seam credits.
        self.assertIn("once per cast", self.texts[_ROCKETBELT])

    def test_everfrost_meraki_magnitude(self) -> None:
        base, pct = self._parse_everfrost()
        self.assertEqual(base, 300)
        self.assertEqual(pct, 85)

    def test_registry_matches_meraki_values(self) -> None:
        r_base, r_pct = self._parse_rocketbelt()
        for iid in (_ROCKETBELT, _ROCKETBELT_ARENA):
            eff = ITEM_EFFECTS[iid]
            self.assertAlmostEqual(eff.magic_burst_base, float(r_base), msg=iid)
            self.assertAlmostEqual(
                eff.magic_burst_ap_ratio, r_pct / 100.0, msg=iid
            )
        e_base, e_pct = self._parse_everfrost()
        eff = ITEM_EFFECTS[_EVERFROST_ARENA]
        self.assertAlmostEqual(eff.magic_burst_base, float(e_base))
        self.assertAlmostEqual(eff.magic_burst_ap_ratio, e_pct / 100.0)


class RegistryPins(unittest.TestCase):
    """Hand-authored pins: 3152 / 223152 / 446656 carry the seam fields."""

    def test_rocketbelt_pins(self) -> None:
        eff = ITEM_EFFECTS[_ROCKETBELT]
        self.assertAlmostEqual(eff.magic_burst_base, 100.0)
        self.assertAlmostEqual(eff.magic_burst_ap_ratio, 0.10)

    def test_everfrost_pins(self) -> None:
        eff = ITEM_EFFECTS[_EVERFROST_ARENA]
        self.assertAlmostEqual(eff.magic_burst_base, 300.0)
        self.assertAlmostEqual(eff.magic_burst_ap_ratio, 0.85)

    def test_arena_rocketbelt_mirrors_sr_exactly(self) -> None:
        base = ITEM_EFFECTS[_ROCKETBELT]
        mirror = ITEM_EFFECTS[_ROCKETBELT_ARENA]
        self.assertAlmostEqual(mirror.magic_burst_base, base.magic_burst_base)
        self.assertAlmostEqual(
            mirror.magic_burst_ap_ratio, base.magic_burst_ap_ratio
        )

    def test_defensive_only_flag_retained(self) -> None:
        # defensive_only is documentation-only (no engine consumer filters
        # on it - collect_effects at effects.py:72-83 passes every entry to
        # total_magic_burst_damage). It stays True: the entries still have
        # no sustained-DPS proc, and batch-31/40/43 coverage tests pin it.
        for iid in (_ROCKETBELT, _ROCKETBELT_ARENA, _EVERFROST_ARENA):
            eff = ITEM_EFFECTS[iid]
            self.assertTrue(eff.defensive_only, msg=iid)
            self.assertEqual(len(eff.periodics), 0, msg=iid)


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
        for iid in (_ROCKETBELT, _ROCKETBELT_ARENA, _EVERFROST_ARENA):
            self.assertIn(iid, self.pool)

    def test_no_phantom_rocketbelt_mirror(self) -> None:
        # 323152 is NOT in the 16.13.1 DS pool - registering it would be a
        # phantom id the ranker can never see (R68 pattern).
        self.assertNotIn("323152", self.pool)
        self.assertNotIn("323152", ITEM_EFFECTS)

    def test_legacy_everfrost_stays_unpinned(self) -> None:
        # 6656 / 226656 exist in items.json but with every map flag False
        # (unobtainable) and carry NO Meraki entry - there is no 16.13.1
        # truth to pin, so their magic_burst fields stay inert.
        for iid in _EVERFROST_LEGACY:
            self.assertIn(iid, self.pool, msg=iid)
            self.assertFalse(
                any((self.pool[iid].get("maps") or {}).values()), msg=iid
            )
            self.assertNotIn(iid, self.meraki, msg=iid)
            eff = ITEM_EFFECTS[iid]
            self.assertEqual(eff.magic_burst_base, 0.0, msg=iid)
            self.assertEqual(eff.magic_burst_ap_ratio, 0.0, msg=iid)


class MagicBurstHelper(unittest.TestCase):
    """``total_magic_burst_damage`` folds the new pins additively."""

    def test_rocketbelt_single(self) -> None:
        effs = collect_effects([_ROCKETBELT])
        # 100 + 0.10 * 200 = 120.
        self.assertAlmostEqual(total_magic_burst_damage(effs, 200.0), 120.0)

    def test_arena_rocketbelt_single(self) -> None:
        effs = collect_effects([_ROCKETBELT_ARENA])
        self.assertAlmostEqual(total_magic_burst_damage(effs, 200.0), 120.0)

    def test_everfrost_single(self) -> None:
        effs = collect_effects([_EVERFROST_ARENA])
        # 300 + 0.85 * 100 = 385.
        self.assertAlmostEqual(total_magic_burst_damage(effs, 100.0), 385.0)

    def test_additive_with_existing_carrier(self) -> None:
        effs = collect_effects([_ROCKETBELT, _LUDENS])
        # (100 + 20) + (75 + 10) = 205 at AP=200.
        self.assertAlmostEqual(total_magic_burst_damage(effs, 200.0), 205.0)


class ComputeBurstSeam(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_default_off_byte_identical(self) -> None:
        base = compute_burst_damage(
            self.snap, "Veigar", 11, item_ids=_ROCKETBELT_BUILD,
            target_mr=60, target_max_hp=2000,
        )
        off = compute_burst_damage(
            self.snap, "Veigar", 11, item_ids=_ROCKETBELT_BUILD,
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

    def test_seam_on_rocketbelt_raises_burst(self) -> None:
        off = compute_burst_damage(
            self.snap, "Veigar", 11, item_ids=_ROCKETBELT_BUILD,
            target_mr=0, target_max_hp=2000,
        )
        on = compute_burst_damage(
            self.snap, "Veigar", 11, item_ids=_ROCKETBELT_BUILD,
            target_mr=0, target_max_hp=2000, assume_magic_burst=True,
        )
        self.assertGreater(on.total_burst_damage, off.total_burst_damage)
        # At target_mr=0 (MAGIC factor 1.0), SR (mode_mult 1.0), no Abyssal
        # (magic_amp 1.0) the delta is 100 + 0.10 * AP >= the 100 base floor.
        self.assertGreaterEqual(
            on.total_burst_damage - off.total_burst_damage, 100.0
        )

    def test_mr_routing_scales_delta(self) -> None:
        # The Rocketbelt delta must route through MR: mitigating only MR
        # shrinks it by exactly the engine's own MAGIC mitigation ratio
        # (Rocketbelt's ItemEffect carries no magic pen, so target_mr_eff
        # equals the raw target_mr and the expected ratio is clean).
        def delta(mr: float) -> float:
            off = compute_burst_damage(
                self.snap, "Veigar", 11, item_ids=_ROCKETBELT_BUILD,
                target_mr=mr, target_max_hp=2000,
            )
            on = compute_burst_damage(
                self.snap, "Veigar", 11, item_ids=_ROCKETBELT_BUILD,
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
    """Existing DSV6 carriers keep their pins; non-magic items stay off."""

    def test_existing_carriers_unchanged(self) -> None:
        for iid, base, ratio in (
            (_LUDENS, 75.0, 0.05),
            (_STORMSURGE, 125.0, 0.10),
            (_MALIGNANCE, 180.0, 0.15),
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
